from __future__ import annotations

import asyncio
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, time as datetime_time, timedelta, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from .config import Settings
from .diary import Diary
from .icmp import measure_host
from .models import Machine, MeasurementSample, TracerouteResult, AlertRule, AlertEvent
from .queue import LocalQueue
from .supabase_repository import SupabaseRepository
from .traceroute import run_traceroute


INTERNET_CHECK_MACHINE_TAG = "INTERNET-CHECK"
INTERNET_CHECK_MACHINE_IP = "8.8.8.8"

REACHABLE_STATUSES = {"ok", "partial"}
UNREACHABLE_STATUSES = {"unreachable", "error"}


@dataclass
class MonitorEvent:
    machine_id: str
    tag: str
    ip: str
    status: str
    latency_ms: float | None
    jitter_ms: float | None
    packet_loss: float
    timestamp: str


class MonitorService:
    def __init__(
        self,
        settings: Settings,
        repository: SupabaseRepository,
        queue: LocalQueue,
        diary: Diary,
        event_callback: Optional[Callable[[MonitorEvent], None]] = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.queue = queue
        self.diary = diary
        self.event_callback = event_callback
        self._executor = ThreadPoolExecutor(max_workers=16)
        self._stop = asyncio.Event()
        self._last_cleanup = time.monotonic()
        self._last_run: dict[str, float] = {}
        self._last_internet_check: dict[str, float] = {}
        self._last_traceroute: dict[str, float] = {}
        self._last_alert_check: dict[str, float] = {}
        self._last_internet_status: dict[str, str] = {}
        self._last_reachability: dict[str, str] = {}
        self._work_schedules: dict[str, dict] = {}

    def stop(self) -> None:
        self._stop.set()

    async def run_forever(self) -> None:
        while not self._stop.is_set():
            await self.run_cycle()
            await asyncio.sleep(1)

    async def run_cycle(self) -> None:
        now = time.monotonic()
        self._work_schedules = self._load_work_schedules()
        
        # 1. Verifica máquinas regulares
        machines = await asyncio.to_thread(self.repository.list_machines, active_only=True)
        due_machines = [
            m for m in machines
            if self._is_within_work_schedule(m.id) and self._is_due(m, now)
        ]
        if due_machines:
            await self._measure_batch(due_machines, now)
        
        # 2. Verifica internet check (se habilitado)
        if self.settings.internet_check_enabled:
            await self._run_internet_checks(now)
        
        # 3. Verifica traceroute (se habilitado)
        if self.settings.traceroute_enabled:
            await self._run_traceroute_checks(now)
        
        # 4. Verifica alertas (se habilitado)
        if self.settings.alert_enabled:
            await self._run_alert_checks(now)
        
        # 5. Processa fila de retry e limpeza
        await self._retry_queue(now)
        await self._maybe_cleanup(now)

    def _load_work_schedules(self) -> dict[str, dict]:
        schedule_file = self.settings.data_dir / "work_schedules.json"
        try:
            with schedule_file.open("r", encoding="utf-8") as file:
                data = json.load(file)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            self.diary.log("HORARIO_TRABALHO_ERRO", "Não foi possível ler horários de trabalho; usando padrão 07:00–18:00.", {"error": str(exc)})
            return {}

    def _is_within_work_schedule(self, machine_id: str) -> bool:
        schedule = self._work_schedules.get(machine_id, {})
        if schedule.get("enabled", True) is False:
            return True
        try:
            start = datetime_time.fromisoformat(schedule.get("start", "07:00"))
            end = datetime_time.fromisoformat(schedule.get("end", "18:00"))
        except (TypeError, ValueError):
            start, end = datetime_time(7, 0), datetime_time(18, 0)
        local_now = datetime.now(ZoneInfo("America/Sao_Paulo")).time().replace(second=0, microsecond=0)
        if start <= end:
            return start <= local_now <= end
        return local_now >= start or local_now <= end

    def _is_due(self, machine: Machine, now: float) -> bool:
        last = self._last_run.get(machine.id, 0)
        interval = max(1, machine.frequency_seconds)
        if now - last >= interval:
            self._last_run[machine.id] = now
            return True
        return False

    def _is_internet_check_due(self, client_id: str, now: float) -> bool:
        last = self._last_internet_check.get(client_id, 0)
        interval = max(1, self.settings.internet_check_frequency_seconds)
        if now - last >= interval:
            self._last_internet_check[client_id] = now
            return True
        return False

    def _is_traceroute_due(self, machine_id: str, now: float) -> bool:
        last = self._last_traceroute.get(machine_id, 0)
        interval = max(1, self.settings.traceroute_frequency_seconds)
        if now - last >= interval:
            self._last_traceroute[machine_id] = now
            return True
        return False

    async def _run_internet_checks(self, now: float) -> None:
        """Executa verificação de conectividade com internet (8.8.8.8) para cada cliente."""
        try:
            clients = await asyncio.to_thread(self.repository.list_clients)
            for client in clients:
                if not self._is_internet_check_due(client.id, now):
                    continue
                
                # Busca ou cria máquina de internet check para este cliente
                internet_machine = await self._get_or_create_internet_machine(client.id)
                if not internet_machine:
                    continue
                if not self._is_within_work_schedule(internet_machine.id):
                    continue
                
                # Executa medição com 100 pings
                sample = await asyncio.to_thread(
                    self._measure_machine,
                    internet_machine,
                    count=self.settings.ping_count,
                    timeout_seconds=self.settings.ping_timeout_seconds,
                )
                
                # Salva medição apenas se alcançável
                if sample.status in UNREACHABLE_STATUSES:
                    await self._record_unreachable(internet_machine, sample.packet_loss_percent, sample.packets_sent, sample.packets_received)
                    self.diary.log(
                        "INTERNET_CHECK_UNREACHABLE",
                        f"Internet check inacessível {client.name}",
                        {"client_id": client.id, "loss": sample.packet_loss_percent},
                    )
                    continue

                try:
                    await asyncio.to_thread(self.repository.save_measurement, sample)
                    await self._record_reachable(internet_machine, sample)
                    self._last_internet_status[internet_machine.id] = sample.status
                    self.diary.log(
                        "INTERNET_CHECK_OK",
                        f"Verificação internet {client.name}",
                        {"client_id": client.id, "latency": sample.latency_ms, "loss": sample.packet_loss_percent},
                    )
                except Exception as exc:
                    self.diary.log(
                        "INTERNET_CHECK_ERRO_ENVIO",
                        f"Falha ao enviar internet check para {client.name}",
                        {"client_id": client.id, "error": str(exc)},
                    )
                    self.queue.enqueue(sample)
                    
        except Exception as exc:
            self.diary.log(
                "INTERNET_CHECK_ERRO",
                "Falha ao executar verificações de internet",
                {"error": str(exc)},
            )

    async def _run_traceroute_checks(self, now: float) -> None:
        """Executa traceroute para máquinas ativas."""
        try:
            machines = await asyncio.to_thread(self.repository.list_machines, active_only=True)
            
            for machine in machines:
                if not self._is_within_work_schedule(machine.id):
                    continue
                if machine.tag == INTERNET_CHECK_MACHINE_TAG:
                    if not self._should_run_internet_traceroute(machine.id, now):
                        continue
                elif not self._is_traceroute_due(machine.id, now):
                    continue
                
                result = await asyncio.to_thread(
                    run_traceroute,
                    ip=machine.ip,
                    max_hops=self.settings.traceroute_max_hops,
                    timeout_seconds=self.settings.traceroute_timeout_seconds,
                )
                
                try:
                    await asyncio.to_thread(
                        self.repository.save_traceroute,
                        result,
                        machine.client_id,
                        machine.id,
                    )
                    self.diary.log(
                        "TRACEROUTE_OK",
                        f"Traceroute {machine.tag} ({machine.ip})",
                        {
                            "machine_id": machine.id,
                            "total_hops": result.total_hops,
                            "destination_reached": result.destination_reached,
                        },
                    )
                except Exception as exc:
                    self.diary.log(
                        "TRACEROUTE_ERRO_ENVIO",
                        f"Falha ao enviar traceroute para {machine.tag}",
                        {"machine_id": machine.id, "error": str(exc)},
                    )
                    
        except Exception as exc:
            self.diary.log(
                "TRACEROUTE_ERRO",
                "Falha ao executar traceroutes",
                {"error": str(exc)},
            )
    
    def _should_run_internet_traceroute(self, machine_id: str, now: float) -> bool:
        """Verifica se deve rodar traceroute para INTERNET-CHECK."""
        current_status = self._last_internet_status.get(machine_id, "ok")
        if current_status == "ok":
            return False
        last_run = self._last_traceroute.get(machine_id, 0)
        if now - last_run >= 300:
            self._last_traceroute[machine_id] = now
            return True
        return False
    
    async def _get_or_create_internet_machine(self, client_id: str) -> Machine | None:
        """Busca ou cria máquina de internet check para o cliente."""
        try:
            # Busca máquina existente com tag INTERNET-CHECK
            machines = await asyncio.to_thread(
                self.repository.list_machines, client_id=client_id, active_only=False
            )
            for m in machines:
                if m.tag == INTERNET_CHECK_MACHINE_TAG:
                    # Garante que está ativa e com IP correto
                    if not m.active or m.ip != self.settings.internet_check_ip:
                        await asyncio.to_thread(
                            self.repository.update_machine,
                            m.id,
                            active=True,
                            ip=self.settings.internet_check_ip,
                            frequency_seconds=self.settings.internet_check_frequency_seconds,
                        )
                    return m
            
            # Cria nova máquina de internet check
            machine = await asyncio.to_thread(
                self.repository.create_machine,
                client_id=client_id,
                tag=INTERNET_CHECK_MACHINE_TAG,
                ip=self.settings.internet_check_ip,
                frequency_seconds=self.settings.internet_check_frequency_seconds,
            )
            self.diary.log(
                "INTERNET_CHECK_MACHINE_CRIADA",
                f"Máquina de internet check criada para cliente",
                {"client_id": client_id, "machine_id": machine.id},
            )
            return machine
        except Exception as exc:
            self.diary.log(
                "INTERNET_CHECK_MACHINE_ERRO",
                f"Falha ao obter/criar máquina internet check",
                {"client_id": client_id, "error": str(exc)},
            )
            return None

    async def _measure_batch(self, machines: list[Machine], now: float) -> None:
        loop = asyncio.get_running_loop()
        tasks = [
            loop.run_in_executor(
                self._executor,
                self._measure_machine,
                machine,
            )
            for machine in machines
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for machine, result in zip(machines, results):
            if isinstance(result, Exception):
                self.diary.log(
                    "ERRO_MEDICAO",
                    f"Falha ao medir {machine.tag} ({machine.ip})",
                    {"machine_id": machine.id, "error": str(result)},
                )
                await self._record_unreachable(machine, 100.0, 0, 0)
                continue
            sample = result
            if sample.status in UNREACHABLE_STATUSES:
                await self._record_unreachable(machine, sample.packet_loss_percent, sample.packets_sent, sample.packets_received)
                continue
            try:
                await asyncio.to_thread(self.repository.save_measurement, sample)
                await self._record_reachable(machine, sample)
                self.diary.log(
                    "MEDICAO_OK",
                    f"Medição enviada para {sample.machine_id}",
                    {"machine_id": sample.machine_id, "latency": sample.latency_ms},
                )
            except Exception as exc:
                self.diary.log(
                    "ERRO_ENVIO",
                    f"Falha ao enviar medição para Supabase",
                    {"machine_id": sample.machine_id, "error": str(exc)},
                )
                self.queue.enqueue(sample)

    def _measure_machine(self, machine: Machine, count: int | None = None, timeout_seconds: float | None = None) -> MeasurementSample:
        return measure_host(
            ip=machine.ip,
            client_id=machine.client_id,
            machine_id=machine.id,
            count=count or self.settings.ping_count,
            timeout_seconds=timeout_seconds or self.settings.ping_timeout_seconds,
        )

    async def _retry_queue(self, now: float) -> None:
        due = await asyncio.to_thread(self.queue.due_entries)
        for entry in due:
            sample_data = entry.get("sample", {})
            sample = MeasurementSample(**sample_data)
            try:
                await asyncio.to_thread(self.repository.save_measurement, sample)
                await asyncio.to_thread(self.queue.acknowledge, entry["id"])
                self.diary.log(
                    "RETRY_OK",
                    "Medição reenviada com sucesso",
                    {"entry_id": entry["id"]},
                )
            except Exception as exc:
                await asyncio.to_thread(self.queue.fail, entry["id"], str(exc))
                self.diary.log(
                    "RETRY_FALHA",
                    "Falha ao reenviar medição",
                    {"entry_id": entry["id"], "error": str(exc)},
                )

    async def _maybe_cleanup(self, now: float) -> None:
        if now - self._last_cleanup > 86400:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=self.settings.retention_days)).isoformat()
            try:
                await asyncio.to_thread(self.repository.cleanup_old_measurements, cutoff)
                self.diary.log("LIMPEZA", f"Medições antigas removidas (>{self.settings.retention_days} dias)")
            except Exception as exc:
                self.diary.log("ERRO_LIMPEZA", "Falha ao limpar medições antigas", {"error": str(exc)})
            try:
                await asyncio.to_thread(self.repository.cleanup_internet_check_traceroutes)
                self.diary.log("LIMPEZA", "Traceroutes INTERNET-CHECK removidos")
            except Exception as exc:
                self.diary.log("ERRO_LIMPEZA", "Falha ao limpar traceroutes INTERNET-CHECK", {"error": str(exc)})
            self._last_cleanup = now

    def _is_alert_due(self, machine_id: str, now: float) -> bool:
        """Verifica se é hora de avaliar alertas para esta máquina."""
        last = self._last_alert_check.get(machine_id, 0)
        interval = max(1, self.settings.alert_evaluation_window)
        if now - last >= interval:
            self._last_alert_check[machine_id] = now
            return True
        return False

    async def _record_unreachable(self, machine: Machine, packet_loss: float, packets_sent: int, packets_received: int) -> None:
        """Registra evento de inacessibilidade e não salva medição na tabela measurements."""
        previous = self._last_reachability.get(machine.id)
        now_iso = datetime.now(timezone.utc).isoformat()

        if previous in UNREACHABLE_STATUSES or previous is None:
            event_type = "packet_loss"
        else:
            event_type = "unreachable"

        self._last_reachability[machine.id] = "unreachable"

        # Preserve failed probes as measurements: packet loss is still useful
        # even when latency and jitter cannot be calculated.
        try:
            sample = MeasurementSample(
                client_id=machine.client_id,
                machine_id=machine.id,
                latency_ms=None,
                jitter_ms=None,
                packet_loss_percent=packet_loss,
                packets_sent=packets_sent,
                packets_received=packets_received,
                status="unreachable",
                measured_at=now_iso,
            )
            await asyncio.to_thread(self.repository.save_measurement, sample)
        except Exception as exc:
            self.diary.log(
                "MEDICAO_INALCANCAVEL_ERRO",
                f"Falha ao salvar a perda de conectividade para {machine.tag}",
                {"machine_id": machine.id, "error": str(exc)},
            )

        try:
            await asyncio.to_thread(
                self.repository.record_device_status_event,
                machine_id=machine.id,
                client_id=machine.client_id,
                event_type=event_type,
                packet_loss_percent=packet_loss,
                latency_ms=None,
                jitter_ms=None,
                packets_sent=packets_sent,
                packets_received=packets_received,
                previous_status=previous,
                measured_at=now_iso,
            )
        except Exception as exc:
            self.diary.log(
                "EVENTO_STATUS_ERRO",
                f"Falha ao registrar evento de status para {machine.tag}",
                {"machine_id": machine.id, "error": str(exc)},
            )

    async def _record_reachable(self, machine: Machine, sample: MeasurementSample) -> None:
        """Registra evento de alcançabilidade se a máquina estava inacessível."""
        previous = self._last_reachability.get(machine.id)
        if previous in UNREACHABLE_STATUSES or previous is None:
            now_iso = datetime.now(timezone.utc).isoformat()
            try:
                await asyncio.to_thread(
                    self.repository.record_device_status_event,
                    machine_id=machine.id,
                    client_id=machine.client_id,
                    event_type="reachable",
                    packet_loss_percent=sample.packet_loss_percent,
                    latency_ms=sample.latency_ms,
                    jitter_ms=sample.jitter_ms,
                    packets_sent=sample.packets_sent,
                    packets_received=sample.packets_received,
                    previous_status=previous,
                    measured_at=now_iso,
                )
            except Exception as exc:
                self.diary.log(
                    "EVENTO_STATUS_ERRO",
                    f"Falha ao registrar evento de recuperação para {machine.tag}",
                    {"machine_id": machine.id, "error": str(exc)},
                )
        self._last_reachability[machine.id] = sample.status

    async def _get_last_reachability(self, machine_id: str) -> str | None:
        """Retorna o último status de alcançabilidade conhecido."""
        return self._last_reachability.get(machine_id)

    async def _run_alert_checks(self, now: float) -> None:
        """Avalia regras de alerta para máquinas ativas."""
        if not self.settings.alert_enabled:
            return
        
        try:
            # Busca regras de alerta ativas
            rules = await asyncio.to_thread(
                self.repository.list_alert_rules, enabled_only=True
            )
            
            if not rules:
                return
            
            # Agrupa regras por machine_id
            rules_by_machine: dict[str, list[dict]] = {}
            for rule in rules:
                mid = rule.get("machine_id")
                if mid:
                    rules_by_machine.setdefault(mid, []).append(rule)
            
            # Avalia cada máquina que tem regras
            for machine_id, machine_rules in rules_by_machine.items():
                if not self._is_within_work_schedule(machine_id):
                    continue
                if not self._is_alert_due(machine_id, now):
                    continue
                
                await self._evaluate_machine_alerts(machine_id, machine_rules)
                
        except Exception as exc:
            self.diary.log(
                "ALERT_ERRO",
                "Falha ao avaliar alertas",
                {"error": str(exc)},
            )

    async def _evaluate_machine_alerts(self, machine_id: str, rules: list[dict]) -> None:
        """Avalia todas as regras para uma máquina específica."""
        try:
            # Busca medições na janela de avaliação
            window = self.settings.alert_evaluation_window
            measurements = await asyncio.to_thread(
                self.repository.get_measurements_window, machine_id, window
            )
            
            if not measurements:
                return
            
            for rule in rules:
                await self._evaluate_rule(machine_id, rule, measurements)
                
        except Exception as exc:
            self.diary.log(
                "ALERT_ERRO_AVALIACAO",
                f"Falha ao avaliar alertas para máquina {machine_id}",
                {"error": str(exc)},
            )

    async def _evaluate_rule(self, machine_id: str, rule: dict, measurements: list[dict]) -> None:
        """Avalia uma regra específica contra as medições."""
        metric = rule["metric"]
        condition = rule["condition"]
        threshold_warn = rule["threshold_warn"]
        threshold_crit = rule["threshold_crit"]
        cooldown = rule.get("cooldown_seconds", 900)
        
        # Extrai valores da métrica
        values = [m.get(metric + "_ms") if metric in ["latency", "jitter"] else m.get("packet_loss_percent") 
                  for m in measurements if m.get(metric + "_ms") is not None or metric == "loss"]
        
        if not values:
            return
        
        # Calcula valor agregado (média para latency/jitter, max para loss)
        if metric == "loss":
            current_value = max(values) if values else 0
        else:
            current_value = sum(values) / len(values) if values else 0
        
        # Verifica se excede threshold
        severity = None
        threshold_value = None
        
        if self._check_condition(current_value, condition, threshold_crit):
            severity = "critical"
            threshold_value = threshold_crit
        elif self._check_condition(current_value, condition, threshold_warn):
            severity = "warning"
            threshold_value = threshold_warn
        else:
            # Valor normal - verifica se há alerta ativo para resolver
            await self._resolve_alert_if_active(rule["id"])
            return
        
        # Verifica cooldown
        active_event = await asyncio.to_thread(self.repository.get_active_alert_event, rule["id"])
        if active_event:
            # Alerta já ativo - verifica se mudou severidade
            if active_event["severity"] != severity:
                await asyncio.to_thread(
                    self.repository.update_alert_event,
                    active_event["id"],
                    {"severity": severity, "metric_value": current_value, "threshold_value": threshold_value}
                )
                self.diary.log("ALERT_SEVERIDADE_ALTERADA", f"Severidade alterada para {severity}", {
                    "rule_id": rule["id"], "machine_id": machine_id, "severity": severity
                })
            return
        
        # Verifica cooldown desde último alerta resolvido
        recent_events = await asyncio.to_thread(
            self.repository.list_alert_events, machine_id=machine_id, status="resolved", limit=1
        )
        if recent_events:
            from datetime import datetime, timezone
            last_resolved = datetime.fromisoformat(recent_events[0]["resolved_at"].replace("Z", "+00:00"))
            time_since_resolved = (datetime.now(timezone.utc) - last_resolved).total_seconds()
            if time_since_resolved < cooldown:
                return  # Ainda em cooldown
        
        # Cria novo evento de alerta
        event_data = {
            "rule_id": rule["id"],
            "client_id": rule["client_id"],
            "machine_id": machine_id,
            "status": "firing",
            "severity": severity,
            "metric_value": current_value,
            "threshold_value": threshold_value,
        }
        
        try:
            event_id = await asyncio.to_thread(self.repository.create_alert_event, event_data)
            self.diary.log("ALERT_DISPARADO", f"Alerta {severity} disparado", {
                "rule_id": rule["id"], "machine_id": machine_id, 
                "metric": metric, "value": current_value, "threshold": threshold_value
            })
        except Exception as exc:
            self.diary.log("ALERT_ERRO_CRIACAO", "Falha ao criar evento de alerta", {"error": str(exc)})

    def _check_condition(self, value: float, condition: str, threshold: float) -> bool:
        """Verifica se valor atende à condição."""
        if condition == "gt":
            return value > threshold
        elif condition == "gte":
            return value >= threshold
        elif condition == "lt":
            return value < threshold
        elif condition == "lte":
            return value <= threshold
        return False

    async def _resolve_alert_if_active(self, rule_id: str) -> None:
        """Resolve alerta ativo se valor voltou ao normal."""
        active_event = await asyncio.to_thread(self.repository.get_active_alert_event, rule_id)
        if active_event:
            await asyncio.to_thread(
                self.repository.update_alert_event,
                active_event["id"],
                {"status": "resolved", "resolved_at": datetime.now(timezone.utc).isoformat()}
            )
            self.diary.log("ALERT_RESOLVIDO", "Alerta resolvido automaticamente", {
                "rule_id": rule_id, "event_id": active_event["id"]
            })
