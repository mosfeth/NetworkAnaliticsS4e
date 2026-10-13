from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from ipaddress import ip_address
from typing import Any
import uuid


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
    id: str | None
    client_id: str
    machine_id: str
    latency_ms: float | None
    jitter_ms: float | None
    packet_loss_percent: float | None
    packets_sent: int
    packets_received: int
    status: str
    measured_at: str


@dataclass(frozen=True)
class MeasurementSample:
    client_id: str
    machine_id: str
    latency_ms: float | None
    jitter_ms: float | None
    packet_loss_percent: float | None
    packets_sent: int
    packets_received: int
    status: str
    measured_at: str | None = None
    sample_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def as_insert(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            # Reuse the measurements table's existing primary key as an
            # idempotency key. A retry of the same sample then becomes an upsert.
            "id": self.sample_id,
            "client_id": self.client_id,
            "machine_id": self.machine_id,
            "latency_ms": self.latency_ms,
            "jitter_ms": self.jitter_ms,
            "packet_loss_percent": self.packet_loss_percent,
            "packets_sent": self.packets_sent,
            "packets_received": self.packets_received,
            "status": self.status,
        }
        if self.measured_at is not None:
            payload["measured_at"] = self.measured_at
        return payload


@dataclass(frozen=True)
class TracerouteHop:
    hop_number: int
    ip: str | None
    hostname: str | None
    latency_ms: float | None
    packet_loss_percent: float


@dataclass(frozen=True)
class TracerouteResult:
    target_ip: str
    max_hops: int
    total_hops: int
    destination_reached: bool
    hops: list[TracerouteHop]


@dataclass(frozen=True)
class AlertRule:
    id: str
    client_id: str
    machine_id: str | None
    name: str
    metric: str
    condition: str
    threshold_warn: float
    threshold_crit: float
    evaluation_window_seconds: int
    cooldown_seconds: int
    enabled: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class MachineFeedback:
    id: str | None
    machine_id: str
    label: str  # "bom", "medio", "ruim"
    latency_ms: float | None
    jitter_ms: float | None
    packet_loss_percent: float
    packets_received: int
    packets_sent: int
    hour_of_day: int
    day_of_week: int
    notes: str | None
    created_at: str


@dataclass(frozen=True)
class AlertEvent:
    id: str
    rule_id: str
    client_id: str
    machine_id: str
    status: str
    severity: str
    metric_value: float
    threshold_value: float
    started_at: str
    resolved_at: str | None
    acknowledged_at: str | None
    acknowledged_by: str | None
    created_at: str


def validate_ip(value: str) -> str:
    try:
        return str(ip_address(value.strip()))
    except ValueError as exc:
        raise ValueError(f"IP inválido: {value}") from exc


def validate_tag(value: str) -> str:
    tag = value.strip()
    if not tag:
        raise ValueError("A tag da máquina é obrigatória.")
    if len(tag) > 120:
        raise ValueError("A tag da máquina deve ter no máximo 120 caracteres.")
    return tag


def validate_client_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise ValueError("O nome do cliente é obrigatório.")
    if len(name) > 160:
        raise ValueError("O nome do cliente deve ter no máximo 160 caracteres.")
    return name


def validate_frequency(value: int | str) -> int:
    try:
        frequency = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("A frequência deve ser um número inteiro em segundos.") from exc
    if frequency < 10:
        raise ValueError("A frequência mínima é de 10 segundos.")
    return frequency


def utc_now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
