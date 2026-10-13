from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from supabase import Client, create_client
from supabase.lib.client_options import ClientOptions

from .config import Settings
from .models import Client, Machine, Measurement, MeasurementSample


class RepositoryError(RuntimeError):
    pass


class SupabaseRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        options = ClientOptions(schema="public")
        self.client: Client = create_client(settings.supabase_url, settings.supabase_key, options=options)

    def healthcheck(self) -> tuple[bool, str]:
        try:
            response = httpx.get(
                f"{self.settings.supabase_url}/rest/v1/",
                headers={
                    "apikey": self.settings.supabase_key,
                    "Authorization": f"Bearer {self.settings.supabase_key}",
                },
                timeout=5.0,
            )
            if response.status_code < 500:
                return True, f"Supabase respondeu com HTTP {response.status_code}."
            return False, f"Supabase indisponível: HTTP {response.status_code}."
        except httpx.HTTPError as exc:
            return False, f"Não foi possível alcançar o Supabase: {exc.__class__.__name__}."

    def create_client(self, name: str) -> Client:
        try:
            response = self.client.table("clients").insert({"name": name}).execute()
        except Exception as exc:
            raise RepositoryError(self._message(exc)) from exc
        row = self._single(response.data, "cliente")
        return self._client(row)

    def find_client_by_name(self, name: str) -> Client | None:
        try:
            response = self.client.table("clients").select("*").eq("name", name).limit(1).execute()
        except Exception as exc:
            raise RepositoryError(self._message(exc)) from exc
        rows = self._rows(response.data)
        return self._client(rows[0]) if rows else None

    def list_clients(self) -> list[Client]:
        try:
            response = self.client.table("clients").select("*").order("name").execute()
        except Exception as exc:
            raise RepositoryError(self._message(exc)) from exc
        return [self._client(row) for row in self._rows(response.data)]

    def get_client(self, client_id: str) -> Client:
        try:
            response = self.client.table("clients").select("*").eq("id", client_id).limit(1).execute()
        except Exception as exc:
            raise RepositoryError(self._message(exc)) from exc
        rows = self._rows(response.data)
        if not rows:
            raise RepositoryError(f"Cliente {client_id} não foi encontrado.")
        return self._client(rows[0])

    def update_client(self, client_id: str, name: str) -> Client:
        try:
            response = self.client.table("clients").update({"name": name}).eq("id", client_id).execute()
        except Exception as exc:
            raise RepositoryError(self._message(exc)) from exc
        rows = self._rows(response.data)
        if not rows:
            raise RepositoryError(f"Cliente {client_id} não foi encontrado.")
        return self._client(rows[0])

    def delete_client(self, client_id: str) -> None:
        try:
            response = self.client.table("clients").delete().eq("id", client_id).execute()
        except Exception as exc:
            raise RepositoryError(self._message(exc)) from exc
        if not self._rows(response.data) and not getattr(response, "count", 0):
            raise RepositoryError(f"Cliente {client_id} não foi encontrado.")

    def create_machine(self, client_id: str, tag: str, ip: str, frequency_seconds: int) -> Machine:
        try:
            response = self.client.table("machines").insert(
                {
                    "client_id": client_id,
                    "tag": tag,
                    "ip": ip,
                    "frequency_seconds": frequency_seconds,
                }
            ).execute()
        except Exception as exc:
            raise RepositoryError(self._message(exc)) from exc
        row = self._single(response.data, "máquina")
        return self._machine(row)

    def list_machines(self, client_id: str | None = None, active_only: bool = False) -> list[Machine]:
        try:
            query = self.client.table("machines").select("*")
            if client_id is not None:
                query = query.eq("client_id", client_id)
            if active_only:
                query = query.eq("active", True)
            response = query.order("tag").execute()
        except Exception as exc:
            raise RepositoryError(self._message(exc)) from exc
        return [self._machine(row) for row in self._rows(response.data)]

    def get_machine(self, machine_id: str) -> Machine:
        try:
            response = self.client.table("machines").select("*").eq("id", machine_id).limit(1).execute()
        except Exception as exc:
            raise RepositoryError(self._message(exc)) from exc
        rows = self._rows(response.data)
        if not rows:
            raise RepositoryError(f"Máquina {machine_id} não foi encontrada.")
        return self._machine(rows[0])

    def update_machine(
        self,
        machine_id: str,
        *,
        tag: str | None = None,
        ip: str | None = None,
        frequency_seconds: int | None = None,
        active: bool | None = None,
    ) -> Machine:
        payload = {
            key: value
            for key, value in {
                "tag": tag,
                "ip": ip,
                "frequency_seconds": frequency_seconds,
                "active": active,
            }.items()
            if value is not None
        }
        if not payload:
            raise RepositoryError("Nenhum campo foi informado para atualizar a máquina.")
        try:
            response = self.client.table("machines").update(payload).eq("id", machine_id).execute()
        except Exception as exc:
            raise RepositoryError(self._message(exc)) from exc
        rows = self._rows(response.data)
        if not rows:
            raise RepositoryError(f"Máquina {machine_id} não foi encontrada.")
        return self._machine(rows[0])

    def delete_machine(self, machine_id: str) -> None:
        try:
            response = self.client.table("machines").delete().eq("id", machine_id).execute()
        except Exception as exc:
            raise RepositoryError(self._message(exc)) from exc
        if not self._rows(response.data) and not getattr(response, "count", 0):
            raise RepositoryError(f"Máquina {machine_id} não foi encontrada.")

    def record_device_status_event(
        self,
        machine_id: str,
        client_id: str,
        event_type: str,
        packet_loss_percent: float | None,
        latency_ms: float | None,
        jitter_ms: float | None,
        packets_sent: int,
        packets_received: int,
        previous_status: str | None,
        measured_at: str,
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
            "measured_at": measured_at,
        }
        try:
            self.client.table("device_status_events").insert(payload).execute()
        except Exception as exc:
            raise RepositoryError(self._message(exc)) from exc

    def insert_measurement(self, sample: MeasurementSample) -> Measurement:
        try:
            response = self.client.table("measurements").insert(sample.as_insert()).execute()
        except Exception as exc:
            raise RepositoryError(self._message(exc)) from exc
        row = self._single(response.data, "medição")
        return self._measurement(row)

    def list_measurements(self, machine_id: str | None = None, limit: int = 100) -> list[Measurement]:
        try:
            query = self.client.table("measurements").select("*").order("measured_at", desc=True).limit(limit)
            if machine_id is not None:
                query = query.eq("machine_id", machine_id)
            response = query.execute()
        except Exception as exc:
            raise RepositoryError(self._message(exc)) from exc
        return [self._measurement(row) for row in self._rows(response.data)]

    def cleanup_old_measurements(self, older_than: datetime | None = None) -> int:
        cutoff = older_than or (datetime.now(timezone.utc) - timedelta(days=self.settings.retention_days))
        try:
            response = self.client.table("measurements").delete().lt("measured_at", cutoff.isoformat()).execute()
        except Exception as exc:
            raise RepositoryError(self._message(exc)) from exc
        count = getattr(response, "count", None)
        if count is not None:
            return int(count)
        return len(self._rows(response.data))

    @staticmethod
    def _rows(data: Any) -> list[dict[str, Any]]:
        if data is None:
            return []
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        return []

    @classmethod
    def _single(cls, data: Any, label: str) -> dict[str, Any]:
        rows = cls._rows(data)
        if not rows:
            raise RepositoryError(f"Nenhuma resposta foi recebida ao criar {label}.")
        return rows[0]

    @staticmethod
    def _message(error: Any) -> str:
        detail = getattr(error, "detail", None)
        if detail is not None:
            return str(detail)
        return str(error)

    @staticmethod
    def _client(row: dict[str, Any]) -> Client:
        return Client(
            id=str(row["id"]),
            name=str(row["name"]),
            created_at=str(row.get("created_at") or ""),
        )

    @staticmethod
    def _machine(row: dict[str, Any]) -> Machine:
        return Machine(
            id=str(row["id"]),
            client_id=str(row["client_id"]),
            tag=str(row["tag"]),
            ip=str(row["ip"]),
            frequency_seconds=int(row.get("frequency_seconds") or 60),
            active=bool(row.get("active", True)),
            created_at=str(row.get("created_at") or ""),
        )

    @staticmethod
    def _measurement(row: dict[str, Any]) -> Measurement:
        return Measurement(
            id=str(row.get("id") or ""),
            client_id=str(row["client_id"]),
            machine_id=str(row["machine_id"]),
            latency_ms=_optional_float(row.get("latency_ms")),
            jitter_ms=_optional_float(row.get("jitter_ms")),
            packet_loss_percent=_optional_float(row.get("packet_loss_percent")),
            packets_sent=int(row.get("packets_sent") or 0),
            packets_received=int(row.get("packets_received") or 0),
            status=str(row.get("status") or "unknown"),
            measured_at=str(row.get("measured_at") or row.get("created_at") or ""),
        )


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)
