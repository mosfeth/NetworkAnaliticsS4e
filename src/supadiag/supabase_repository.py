from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from supabase import create_client, Client

from .config import Settings
from .models import Client, Machine, MeasurementSample, TracerouteHop, TracerouteResult, AlertRule, AlertEvent


class RepositoryError(RuntimeError):
    pass


class SupabaseRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client: Client = create_client(settings.supabase_url, settings.supabase_key)

    def health_check(self) -> tuple[bool, str]:
        try:
            response = httpx.get(
                f"{self.settings.supabase_url}/rest/v1/",
                headers={
                    "apikey": self.settings.supabase_key,
                    "Authorization": f"Bearer {self.settings.supabase_key}",
                },
                timeout=5.0,
            )
            if 200 <= response.status_code < 300:
                return True, "Cloud disponível"
            return False, f"Cloud respondeu com status {response.status_code}"
        except httpx.HTTPError as exc:
            return False, f"Falha de conexão com Cloud: {exc}"

    def _execute(self, query):
        try:
            response = query.execute()
        except Exception as exc:
            raise RepositoryError(f"Erro ao executar consulta: {exc}") from exc
        error = getattr(response, "error", None)
        if error:
            raise RepositoryError(str(error))
        return response.data

    def create_client(self, name: str) -> Client:
        data = self._execute(self.client.table("clients").insert({"name": name}))
        row = data[0] if data else {}
        return Client(
            id=row.get("id"),
            name=row.get("name"),
            created_at=row.get("created_at"),
        )

    def list_clients(self) -> list[Client]:
        data = self._execute(self.client.table("clients").select("*").order("name"))
        return [
            Client(id=row["id"], name=row["name"], created_at=row["created_at"])
            for row in data
        ]

    def get_client(self, client_id: str) -> Client | None:
        data = self._execute(
            self.client.table("clients").select("*").eq("id", client_id).limit(1)
        )
        if not data:
            return None
        row = data[0]
        return Client(id=row["id"], name=row["name"], created_at=row["created_at"])

    def update_client(self, client_id: str, name: str) -> Client:
        data = self._execute(
            self.client.table("clients").update({"name": name}).eq("id", client_id)
        )
        row = data[0] if data else {}
        return Client(
            id=row.get("id"),
            name=row.get("name"),
            created_at=row.get("created_at"),
        )

    def delete_client(self, client_id: str) -> None:
        self._execute(self.client.table("clients").delete().eq("id", client_id))

    def create_machine(
        self,
        client_id: str,
        tag: str,
        ip: str,
        frequency_seconds: int,
    ) -> Machine:
        payload = {
            "client_id": client_id,
            "tag": tag,
            "ip": ip,
            "frequency_seconds": frequency_seconds,
            "active": True,
        }
        data = self._execute(self.client.table("machines").insert(payload))
        row = data[0] if data else {}
        return Machine(
            id=row.get("id"),
            client_id=row.get("client_id"),
            tag=row.get("tag"),
            ip=row.get("ip"),
            frequency_seconds=row.get("frequency_seconds"),
            active=row.get("active"),
            created_at=row.get("created_at"),
        )

    def list_machines(self, client_id: str | None = None, active_only: bool = False) -> list[Machine]:
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

    def update_machine(
        self,
        machine_id: str,
        tag: str | None = None,
        ip: str | None = None,
        frequency_seconds: int | None = None,
        active: bool | None = None,
    ) -> Machine:
        payload = {}
        if tag is not None:
            payload["tag"] = tag
        if ip is not None:
            payload["ip"] = ip
        if frequency_seconds is not None:
            payload["frequency_seconds"] = frequency_seconds
        if active is not None:
            payload["active"] = active
        if not payload:
            return self.get_machine(machine_id)  # type: ignore
        data = self._execute(
            self.client.table("machines").update(payload).eq("id", machine_id)
        )
        row = data[0] if data else {}
        return Machine(
            id=row.get("id"),
            client_id=row.get("client_id"),
            tag=row.get("tag"),
            ip=row.get("ip"),
            frequency_seconds=row.get("frequency_seconds"),
            active=row.get("active"),
            created_at=row.get("created_at"),
        )

    def delete_machine(self, machine_id: str) -> None:
        self._execute(self.client.table("machines").delete().eq("id", machine_id))

    def save_measurement(self, sample: MeasurementSample) -> None:
        payload = sample.as_insert()
        self._execute(
            self.client.table("measurements").upsert(payload, on_conflict="id")
        )

    def get_latest_reachability_status(self, machine_id: str) -> str | None:
        """Return the latest actual probe state, ignoring collector errors."""
        data = self._execute(
            self.client.table("measurements")
            .select("status")
            .eq("machine_id", machine_id)
            .in_("status", ["ok", "partial", "unreachable"])
            .order("measured_at", desc=True)
            .limit(1)
        ) or []
        return data[0].get("status") if data else None

    def latest_measurements(self, limit: int = 50) -> list[dict]:
        data = self._execute(
            self.client.table("measurements")
            .select("*, machines(tag, ip)")
            .order("measured_at", desc=True)
            .limit(limit)
        )
        return data

    def get_measurements(self, machine_id: str, hours: int = 24, limit: int = 500) -> list[dict]:
        """Busca medições recentes de uma máquina em ordem cronológica crescente."""
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        data = self._execute(
            self.client.table("measurements")
            .select("*")
            .eq("machine_id", machine_id)
            .gte("measured_at", since)
            .order("measured_at", desc=True)
            .limit(limit)
        ) or []
        return list(reversed(data))

    def list_machine_feedback(self, machine_id: str, limit: int = 100) -> list[dict]:
        """Busca avaliações humanas mais recentes de uma máquina."""
        return self._execute(
            self.client.table("machine_feedback")
            .select("*")
            .eq("machine_id", machine_id)
            .order("created_at", desc=True)
            .limit(limit)
        ) or []

    def record_device_status_event(
        self,
        machine_id: str,
        client_id: str,
        event_type: str,
        packet_loss_percent: float | None = None,
        latency_ms: float | None = None,
        jitter_ms: float | None = None,
        packets_sent: int | None = None,
        packets_received: int | None = None,
        previous_status: str | None = None,
        measured_at: str | None = None,
    ) -> None:
        payload = {
            "machine_id": machine_id,
            "client_id": client_id,
            "event_type": event_type,
            "packet_loss_percent": packet_loss_percent,
            "latency_ms": latency_ms,
            "jitter_ms": jitter_ms,
            "packets_sent": packets_sent,
            "packets_received": packets_received,
            "previous_status": previous_status,
            "measured_at": measured_at or datetime.now(timezone.utc).isoformat(),
        }
        self._execute(self.client.table("device_status_events").insert(payload))

    def cleanup_old_measurements(self, cutoff_iso: str) -> int:
        data = self._execute(
            self.client.table("measurements").delete().lt("measured_at", cutoff_iso)
        )
        return len(data) if data else 0
    
    def cleanup_internet_check_traceroutes(self) -> int:
        """Remove dados de traceroute de máquinas INTERNET-CHECK (stale)."""
        machines = self._execute(
            self.client.table("machines").select("id").eq("tag", "INTERNET-CHECK")
        )
        if not machines:
            return 0
        machine_ids = [m["id"] for m in machines]
        data = self._execute(
            self.client.table("traceroutes").delete().in_("machine_id", machine_ids)
        )
        return len(data) if data else 0
    
    def save_traceroute(self, result: TracerouteResult, client_id: str, machine_id: str) -> str:
        """Salva resultado de traceroute e retorna ID do traceroute."""
        # Insere traceroute principal
        traceroute_data = self._execute(
            self.client.table("traceroutes").insert({
                "client_id": client_id,
                "machine_id": machine_id,
                "target_ip": result.target_ip,
                "max_hops": result.max_hops,
                "total_hops": result.total_hops,
                "destination_reached": result.destination_reached,
            })
        )
        traceroute_id = traceroute_data[0]["id"] if traceroute_data else None
        
        if not traceroute_id or not result.hops:
            return traceroute_id
        
        # Insere hops
        hops_payload = []
        for hop in result.hops:
            hops_payload.append({
                "traceroute_id": traceroute_id,
                "hop_number": hop.hop_number,
                "ip": hop.ip,
                "hostname": hop.hostname,
                "latency_ms": hop.latency_ms,
                "packet_loss_percent": hop.packet_loss_percent,
            })
        
        self._execute(self.client.table("traceroute_hops").insert(hops_payload))
        return traceroute_id

    def get_latest_traceroute(self, machine_id: str) -> dict | None:
        """Retorna o traceroute mais recente com seus hops."""
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

    # ========== ALERT METHODS ==========

    def create_alert_rule(self, rule_data: dict) -> str:
        """Cria uma regra de alerta e retorna o ID."""
        data = self._execute(self.client.table("alert_rules").insert(rule_data))
        return data[0]["id"] if data else None

    def list_alert_rules(self, client_id: str | None = None, machine_id: str | None = None, enabled_only: bool = True) -> list[dict]:
        """Lista regras de alerta."""
        query = self.client.table("alert_rules").select("*").order("created_at", desc=True)
        if client_id:
            query = query.eq("client_id", client_id)
        if machine_id:
            query = query.eq("machine_id", machine_id)
        if enabled_only:
            query = query.eq("enabled", True)
        return self._execute(query) or []

    def get_alert_rule(self, rule_id: str) -> dict | None:
        data = self._execute(self.client.table("alert_rules").select("*").eq("id", rule_id).limit(1))
        return data[0] if data else None

    def update_alert_rule(self, rule_id: str, updates: dict) -> dict | None:
        updates["updated_at"] = "now()"
        data = self._execute(self.client.table("alert_rules").update(updates).eq("id", rule_id))
        return data[0] if data else None

    def delete_alert_rule(self, rule_id: str) -> None:
        self._execute(self.client.table("alert_rules").delete().eq("id", rule_id))

    def create_alert_event(self, event_data: dict) -> str:
        """Cria evento de alerta e retorna o ID."""
        data = self._execute(self.client.table("alert_events").insert(event_data))
        return data[0]["id"] if data else None

    def get_active_alert_event(self, rule_id: str) -> dict | None:
        """Retorna evento ativo (firing/acknowledged) para uma regra."""
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

    def list_alert_events(self, machine_id: str | None = None, status: str | None = None, limit: int = 50) -> list[dict]:
        """Lista eventos de alerta."""
        query = self.client.table("alert_events").select("*").order("started_at", desc=True)
        if machine_id:
            query = query.eq("machine_id", machine_id)
        if status:
            query = query.eq("status", status)
        query = query.limit(limit)
        return self._execute(query) or []

    def get_measurements_window(self, machine_id: str, window_seconds: int) -> list[dict]:
        """Retorna medições dos últimos N segundos para uma máquina."""
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=window_seconds)).isoformat()
        data = self._execute(
            self.client.table("measurements")
            .select("status, latency_ms, jitter_ms, packet_loss_percent, measured_at")
            .eq("machine_id", machine_id)
            .gte("measured_at", cutoff)
            .order("measured_at", desc=False)
        )
        return data or []

    # ========== MACHINE FEEDBACK METHODS ==========

    def save_machine_feedback(self, data: dict) -> str | None:
        """Salva feedback do operador e retorna o ID."""
        result = self._execute(self.client.table("machine_feedback").insert(data))
        if result:
            return result[0].get("id")
        return None

    def list_machine_feedback(
        self,
        machine_id: str | None = None,
        label: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Lista feedbacks do Supabase."""
        query = self.client.table("machine_feedback").select("*").order("created_at", desc=True)
        if machine_id:
            query = query.eq("machine_id", machine_id)
        if label:
            query = query.eq("label", label)
        query = query.limit(limit)
        return self._execute(query) or []

    def get_feedback_stats(self, machine_id: str) -> dict:
        """Retorna estatísticas de feedback para uma máquina."""
        feedbacks = self.list_machine_feedback(machine_id=machine_id, limit=1000)
        if not feedbacks:
            return {"total": 0, "bom": 0, "medio": 0, "ruim": 0}
        
        stats = {"total": len(feedbacks), "bom": 0, "medio": 0, "ruim": 0}
        for fb in feedbacks:
            label = fb.get("label", "")
            if label in stats:
                stats[label] += 1
        return stats

    def get_machine_accuracy(self, machine_id: str) -> float:
        """Calcula acurácia da máquina baseada nos feedbacks (bom = 1.0, medio = 0.5, ruim = 0.0)."""
        stats = self.get_feedback_stats(machine_id)
        total = stats["total"]
        if total == 0:
            return 0.0
        score = stats["bom"] * 1.0 + stats["medio"] * 0.5 + stats["ruim"] * 0.0
        return round(score / total * 100, 1)

    def get_ai_events(self, limit: int = 20) -> list[dict]:
        """Retorna eventos de treinamento/IA (placeholder - integrar com tabela de logs de treino)."""
        return []

    # ========== ML MODEL WEIGHTS METHODS ==========

    @staticmethod
    def ml_model_name(machine_id: str) -> str:
        """Nome canônico do modelo de qualidade de rede de um equipamento."""
        return f"network_quality_{machine_id}"

    def save_model_weights(
        self,
        model_name: str,
        model_version: str,
        weights: dict,
        accuracy: float | None = None,
    ) -> dict | None:
        """Persiste os pesos de um modelo no Supabase (nunca sobrescreve: cria versão)."""
        data = {
            "model_name": model_name,
            "model_version": model_version,
            "weights": weights,
            "accuracy": accuracy,
        }
        result = self._execute(self.client.table("ml_model_weights").insert(data))
        return result[0] if result else None

    def list_model_weights(self, model_name: str, limit: int = 50) -> list[dict]:
        """Lista versões de pesos salvas de um modelo, da melhor para a pior."""
        query = (
            self.client.table("ml_model_weights")
            .select("id, model_name, model_version, accuracy, trained_at, created_at")
            .eq("model_name", model_name)
            .limit(limit)
        )
        rows = self._execute(query) or []
        return sorted(
            rows,
            key=lambda row: (row.get("accuracy") is not None, row.get("accuracy") or 0.0),
            reverse=True,
        )

    def get_best_model_weights(self, model_name: str) -> dict | None:
        """Retorna a versão de maior acurácia já salva no Supabase (sem os pesos)."""
        versions = self.list_model_weights(model_name, limit=50)
        return versions[0] if versions else None

    def get_model_weights_payload(self, model_name: str, preferred_version: str | None = None) -> dict | None:
        """Retorna o payload completo (pesos + normalizador + métricas) de um modelo."""
        query = (
            self.client.table("ml_model_weights")
            .select("*")
            .eq("model_name", model_name)
            .limit(1)
        )
        if preferred_version:
            query = (
                self.client.table("ml_model_weights")
                .select("*")
                .eq("model_name", model_name)
                .eq("model_version", preferred_version)
                .limit(1)
            )
        result = self._execute(query) or []
        if not result:
            return None
        row = result[0]
        payload = row.get("weights")
        if isinstance(payload, dict):
            return payload
        return None

    def get_best_model_weights_payload(self, model_name: str) -> tuple[dict, dict] | None:
        """Retorna (payload, linha) da melhor versão válida de pesos salva no Supabase."""
        for candidate in self.list_model_weights(model_name, limit=50):
            payload = self.get_model_weights_payload(model_name, candidate.get("model_version"))
            if payload is None:
                continue
            if "state_dict" not in payload or not payload.get("state_dict"):
                continue
            return payload, candidate
        return None

    def save_training_history(
        self,
        model_name: str,
        model_version: str,
        training_samples: int,
        accuracy: float | None = None,
        training_duration_seconds: float | None = None,
        metadata: dict | None = None,
    ) -> dict | None:
        """Registra uma execução de treino no histórico do Supabase."""
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
