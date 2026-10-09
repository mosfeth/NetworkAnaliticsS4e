# FrontEnd/repository.py
# Camada de acesso a dados do Supabase para o FrontEnd

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from supabase import create_client, Client

from config import settings


@dataclass(frozen=True)
class Client:
    id: str
    name: str
    created_at: str


@dataclass(frozen=True)
class Machine:
    id: str
    client_id: str
    tag: str
    ip: str
    frequency_seconds: int
    active: bool
    created_at: str


@dataclass(frozen=True)
class Measurement:
    id: str
    client_id: str
    machine_id: str
    latency_ms: float | None
    jitter_ms: float | None
    packet_loss_percent: float
    packets_sent: int
    packets_received: int
    status: str
    measured_at: str


@dataclass(frozen=True)
class TracerouteHop:
    hop_number: int
    ip: str | None
    hostname: str | None
    latency_ms: float | None
    packet_loss_percent: float


@dataclass(frozen=True)
class Traceroute:
    id: str
    client_id: str
    machine_id: str
    target_ip: str
    max_hops: int
    total_hops: int
    destination_reached: bool
    measured_at: str
    hops: list[dict]


class RepositoryError(RuntimeError):
    """Erro na comunicação com Supabase."""
    pass


REACHABLE_STATUSES = {"ok", "partial"}


class FrontendRepository:
    """Repositório para leitura de dados do Supabase no FrontEnd."""
    
    def __init__(self) -> None:
        if not settings.validate():
            raise RepositoryError("Configurações do Supabase não encontradas. Verifique .env")
        self.client: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    
    def _execute(self, query) -> list[dict[str, Any]]:
        """Executa query e retorna dados ou levanta exceção."""
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                response = query.execute()
                error = getattr(response, "error", None)
                if error:
                    raise RepositoryError(str(error))
                return response.data or []
            except Exception as exc:
                last_error = exc
                if attempt < max_retries - 1:
                    import time
                    time.sleep(0.5 * (attempt + 1))
                    continue
                break
        
        raise RepositoryError(f"Erro ao executar consulta: {last_error}")
    
    def health_check(self) -> tuple[bool, str]:
        """Verifica conectividade com Supabase."""
        try:
            self._execute(self.client.table("clients").select("id").limit(1))
            return True, "Supabase disponível"
        except RepositoryError as exc:
            return False, str(exc)
    
    def list_clients(self) -> list[Client]:
        """Lista todos os clientes ordenados por nome."""
        data = self._execute(
            self.client.table("clients").select("*").order("name")
        )
        return [
            Client(id=row["id"], name=row["name"], created_at=row["created_at"])
            for row in data
        ]
    
    def list_machines(self, client_id: str | None = None, active_only: bool = True) -> list[Machine]:
        """Lista máquinas, opcionalmente filtradas por cliente e status ativo."""
        query = self.client.table("machines").select("*").order("tag")
        
        if client_id:
            query = query.eq("client_id", client_id)
        if active_only:
            query = query.eq("active", True)
        
        data = self._execute(query)
        return [
            Machine(
                id=row["id"],
                client_id=row["client_id"],
                tag=row["tag"],
                ip=row["ip"],
                frequency_seconds=row["frequency_seconds"],
                active=row["active"],
                created_at=row["created_at"],
            )
            for row in data
        ]
    
    def get_machine(self, machine_id: str) -> Machine | None:
        """Obtém uma máquina específica pelo ID."""
        data = self._execute(
            self.client.table("machines").select("*").eq("id", machine_id).limit(1)
        )
        if not data:
            return None
        row = data[0]
        return Machine(
            id=row["id"],
            client_id=row["client_id"],
            tag=row["tag"],
            ip=row["ip"],
            frequency_seconds=row["frequency_seconds"],
            active=row["active"],
            created_at=row["created_at"],
        )
    
    def get_client(self, client_id: str) -> Client | None:
        """Obtém um cliente específico pelo ID."""
        data = self._execute(
            self.client.table("clients").select("*").eq("id", client_id).limit(1)
        )
        if not data:
            return None
        row = data[0]
        return Client(id=row["id"], name=row["name"], created_at=row["created_at"])
    
    def get_measurements(
        self,
        machine_id: str,
        hours: int = 24,
        limit: int = 500
    ) -> list[dict]:
        """Busca medições de uma máquina nas últimas N horas."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        data = self._execute(
            self.client.table("measurements")
            .select("*")
            .eq("machine_id", machine_id)
            .gte("measured_at", cutoff)
            .order("measured_at", desc=False)
            .limit(limit)
        )
        data = [m for m in data if m.get("status") in REACHABLE_STATUSES]
        return data
    
    def get_latest_measurement(self, machine_id: str) -> dict | None:
        """Retorna a medição mais recente de uma máquina."""
        data = self._execute(
            self.client.table("measurements")
            .select("*")
            .eq("machine_id", machine_id)
            .order("measured_at", desc=True)
            .limit(1)
        )
        if not data:
            return None
        return data[0]
    
    def get_latest_traceroute(self, machine_id: str) -> dict | None:
        """Retorna o traceroute mais recente de uma máquina com seus hops."""
        data = self._execute(
            self.client.table("traceroutes")
            .select("*, traceroute_hops(*)")
            .eq("machine_id", machine_id)
            .order("measured_at", desc=True)
            .limit(1)
        )
        if not data:
            return None
        return data[0]
    
    def get_traceroute_history(self, machine_id: str, limit: int = 10) -> list[dict]:
        """Retorna histórico de traceroutes para uma máquina."""
        data = self._execute(
            self.client.table("traceroutes")
            .select("*")
            .eq("machine_id", machine_id)
            .order("measured_at", desc=True)
            .limit(limit)
        )
        return data or []

    def get_sparkline_data(self, machine_id: str, hours: int = 24) -> list[dict]:
        """Retorna dados para sparkline (latência nos últimos N horas)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        data = self._execute(
            self.client.table("measurements")
            .select("latency_ms, measured_at")
            .eq("machine_id", machine_id)
            .gte("measured_at", cutoff)
            .order("measured_at", desc=False)
            .limit(200)  # Suficiente para sparkline
        )
        return data or []
    
    def get_alert_events(self, machine_id: str, status: str | None = None, limit: int = 50) -> list[dict]:
        """Lista eventos de alerta para uma máquina."""
        query = self.client.table("alert_events").select("*").order("started_at", desc=True)
        if machine_id:
            query = query.eq("machine_id", machine_id)
        if status:
            query = query.eq("status", status)
        query = query.limit(limit)
        return self._execute(query) or []
    
    def get_latest_alert_event(self, machine_id: str) -> dict | None:
        """Retorna o evento de alerta mais recente para uma máquina."""
        events = self.get_alert_events(machine_id)
        if not events:
            return None
        return max(events, key=lambda x: x.get("started_at", ""))
    
    def list_alert_rules(self, machine_id: str | None = None) -> list[dict]:
        """Lista regras de alerta para uma máquina."""
        query = self.client.table("alert_rules").select("*").order("created_at", desc=True)
        if machine_id:
            query = query.eq("machine_id", machine_id)
        query = query.eq("enabled", True)
        return self._execute(query) or []
    
    def get_active_alert_event(self, rule_id: str) -> dict | None:
        """Retorna evento ativo para uma regra."""
        data = self._execute(
            self.client.table("alert_events")
            .select("*")
            .eq("rule_id", rule_id)
            .in_("status", ["firing", "acknowledged"])
            .order("started_at", desc=True)
            .limit(1)
        )
        return data[0] if data else None
    
    def update_alert_event(self, event_id: str, updates: dict) -> dict | None:
        data = self._execute(self.client.table("alert_events").update(updates).eq("id", event_id))
        return data[0] if data else None
    
    def get_machines_with_latest_status(self) -> list[dict[str, Any]]:
        """
        Retorna todas as máquinas com sua última medição para exibição em cards.
        Útil para a view principal de cards.
        """
        machines = self.list_machines(active_only=True)
        result = []
        
        for machine in machines:
            latest = self.get_latest_measurement(machine.id)
            client = self.get_client(machine.client_id)
            
            result.append({
                "machine": machine,
                "client": client,
                "latest_measurement": latest,
            })
        
        return result
    
    def get_clients_with_machines_summary(self) -> list[dict[str, Any]]:
        """
        Retorna clientes agrupados com suas máquinas (rede local + internet check),
        incluindo última medição de cada máquina para exibição no card consolidado.
        """
        clients = self.list_clients()
        result = []
        
        for client in clients:
            machines = self.list_machines(client_id=client.id, active_only=True)
            
            local_machines = []
            internet_machine = None
            
            for machine in machines:
                latest = self.get_latest_measurement(machine.id)
                quality = self.get_network_quality_metrics(machine.id, hours=1)
                status_events = self.get_device_status_events(machine_id=machine.id, hours=24, limit=5)
                machine_data = {
                    "machine": machine,
                    "latest_measurement": latest,
                    "quality_metrics": quality,
                    "status_events": status_events,
                }
                if machine.tag == "INTERNET-CHECK":
                    internet_machine = machine_data
                else:
                    local_machines.append(machine_data)
            
            if local_machines or internet_machine:
                result.append({
                    "client": client,
                    "local_machines": local_machines,
                    "internet_machine": internet_machine,
                })
        
        return result
    
    def save_feedback(self, machine_id: str, label: str, measurement: Optional[dict]) -> dict | None:
        """Salva feedback do operador no Supabase."""
        from datetime import datetime, timezone
        
        data = {
            "machine_id": machine_id,
            "label": label,
            "latency_ms": measurement.get("latency_ms") if measurement else None,
            "jitter_ms": measurement.get("jitter_ms") if measurement else None,
            "packet_loss_percent": measurement.get("packet_loss_percent", 0) if measurement else 0.0,
            "packets_received": measurement.get("packets_received", 0) if measurement else 0,
            "packets_sent": measurement.get("packets_sent", 0) if measurement else 0,
            "hour_of_day": datetime.now(timezone.utc).hour,
            "day_of_week": datetime.now(timezone.utc).weekday(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        
        result = self._execute(self.client.table("machine_feedback").insert(data))
        return result[0] if result else None
    
    def list_machine_feedback(self, machine_id: str, limit: int = 100) -> list[dict]:
        """Lista feedbacks de uma máquina."""
        data = self._execute(
            self.client.table("machine_feedback")
            .select("*")
            .eq("machine_id", machine_id)
            .order("created_at", desc=True)
            .limit(limit)
        )
        return data or []
    
    def get_network_quality_metrics(self, machine_id: str, hours: int = 24) -> dict[str, Any]:
        """
        Calcula métricas de qualidade de rede a partir das medições recentes.
        
        Returns:
            Dict com:
            - avg_latency
            - avg_jitter
            - availability_pct
            - min_latency
            - max_latency
            - total_count
            - ok_count
            - status_detail
        """
        measurements = self.get_measurements(machine_id, hours=hours, limit=500)
        measurements = [m for m in measurements if m.get("status") in REACHABLE_STATUSES]
        if not measurements:
            return {
                "avg_latency": None,
                "avg_jitter": None,
                "availability_pct": None,
                "min_latency": None,
                "max_latency": None,
                "total_count": 0,
                "ok_count": 0,
                "status_detail": "Sem dados",
            }
        
        latencies = [m.get("latency_ms") for m in measurements if m.get("latency_ms") is not None]
        jitters = [m.get("jitter_ms") for m in measurements if m.get("jitter_ms") is not None]
        packet_losses = [m.get("packet_loss_percent", 0) for m in measurements if m.get("packet_loss_percent") is not None]
        ok_count = sum(1 for m in measurements if m.get("status") == "ok")
        total_count = len(measurements)
        availability = round((ok_count / total_count) * 100, 1) if total_count else 0.0
        avg_packet_loss = round(sum(packet_losses) / len(packet_losses), 1) if packet_losses else 0.0
        
        if availability >= 95:
            status_detail = "Estável"
        elif availability >= 80:
            status_detail = "Instável"
        elif availability > 0:
            status_detail = "Crítico"
        else:
            status_detail = "Sem dados"
        
        return {
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
            "avg_jitter_ms": round(sum(jitters) / len(jitters), 1) if jitters else None,
            "packet_loss_pct": avg_packet_loss,
            "availability_pct": availability,
            "min_latency": round(min(latencies), 1) if latencies else None,
            "max_latency": round(max(latencies), 1) if latencies else None,
            "total_count": total_count,
            "ok_count": ok_count,
            "status_detail": status_detail,
        }

    def save_network_quality_metric(self, machine_id: str, metrics: dict[str, Any]) -> dict | None:
        """Salva métrica horária de qualidade de rede no Supabase."""
        data = {
            "machine_id": machine_id,
            "measured_at": metrics.get("measured_at") or datetime.now(timezone.utc).isoformat(),
            "avg_latency_ms": metrics.get("avg_latency_ms"),
            "avg_jitter_ms": metrics.get("avg_jitter_ms"),
            "packet_loss_pct": metrics.get("packet_loss_pct", 0.0),
            "total_measurements": metrics.get("total_measurements", 0),
            "quality_status": metrics.get("quality_status", "Sem dados"),
        }
        result = self._execute(self.client.table("network_quality_metrics").insert(data))
        return result[0] if result else None

    def list_network_quality_metrics(self, machine_id: str, limit: int = 200) -> list[dict]:
        """Lista métricas horárias de qualidade de rede."""
        data = self._execute(
            self.client.table("network_quality_metrics")
            .select("*")
            .eq("machine_id", machine_id)
            .order("measured_at", desc=True)
            .limit(limit)
        )
        return data or []

    def save_ml_model_weights(self, model_name: str, model_version: str, weights: dict, accuracy: float | None = None) -> dict | None:
        """Salva pesos do modelo ML no Supabase."""
        data = {
            "model_name": model_name,
            "model_version": model_version,
            "weights": weights,
            "accuracy": accuracy,
        }
        result = self._execute(self.client.table("ml_model_weights").insert(data))
        return result[0] if result else None

    def get_latest_ml_model_weights(self, model_name: str) -> dict | None:
        """Obtém os pesos mais recentes de um modelo ML."""
        data = self._execute(
            self.client.table("ml_model_weights")
            .select("*")
            .eq("model_name", model_name)
            .order("trained_at", desc=True)
            .limit(1)
        )
        return data[0] if data else None

    def save_ml_training_history(self, model_name: str, model_version: str, training_samples: int, accuracy: float | None = None, training_duration_seconds: float | None = None, metadata: dict | None = None) -> dict | None:
        """Salva histórico de treino do modelo ML."""
        data = {
            "model_name": model_name,
            "model_version": model_version,
            "training_samples": training_samples,
            "accuracy": accuracy,
            "training_duration_seconds": training_duration_seconds,
            "metadata": metadata or {},
        }
        result = self._execute(self.client.table("ml_training_history").insert(data))
        return result[0] if result else None

    def list_ml_training_history(self, model_name: str, limit: int = 50) -> list[dict]:
        """Lista histórico de treinos de um modelo."""
        data = self._execute(
            self.client.table("ml_training_history")
            .select("*")
            .eq("model_name", model_name)
            .order("trained_at", desc=True)
            .limit(limit)
        )
        return data or []

    def get_device_status_events(
        self, machine_id: str | None = None, client_id: str | None = None, hours: int = 24, limit: int = 100
    ) -> list[dict]:
        """Retorna eventos de status do dispositivo (alcançável/inacessível)."""
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        query = self.client.table("device_status_events").select("*").gte("measured_at", cutoff).order("measured_at", desc=True).limit(limit)
        if machine_id:
            query = query.eq("machine_id", machine_id)
        if client_id:
            query = query.eq("client_id", client_id)
        data = self._execute(query)
        return data or []