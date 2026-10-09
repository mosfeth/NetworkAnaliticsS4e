# src/supadiag/network_quality.py
# Módulo de qualidade de rede com aprendizado contínuo

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import Settings
from .supabase_repository import SupabaseRepository


class NetworkQualityError(RuntimeError):
    """Erro no cálculo de qualidade de rede."""
    pass


@dataclass(frozen=True)
class HourlyQualityMetrics:
    """Métricas horárias de qualidade de rede."""
    machine_id: str
    measured_at: str
    avg_latency_ms: float | None
    avg_jitter_ms: float | None
    packet_loss_pct: float
    total_measurements: int
    quality_status: str
    created_at: str


@dataclass(frozen=True)
class UserFeedback:
    """Feedback do usuário sobre qualidade de rede."""
    machine_id: str
    label: str
    avg_latency_ms: float | None
    avg_jitter_ms: float | None
    packet_loss_pct: float
    hour_of_day: int
    day_of_week: int
    created_at: str


REACHABLE_STATUSES = {"ok", "partial"}


class NetworkQualityAnalyzer:
    """Analisador de qualidade de rede com classificação BOM/MÉDIO/RUIM."""

    def __init__(self, settings: Settings, repository: SupabaseRepository) -> None:
        self.settings = settings
        self.repository = repository

    def classify_quality(
        self,
        avg_jitter_ms: float | None,
        avg_latency_ms: float | None,
        packet_loss_pct: float,
    ) -> str:
        """
        Classifica qualidade da conexão baseado em thresholds.

        Regras:
        - BOM: jitter < 20ms, latência < 100ms, perda < 0.5%
        - MÉDIO: jitter < 30ms, latência < 150ms, perda < 1%
        - RUIM: qualquer valor acima dos limites MÉDIO
        """
        jitter = avg_jitter_ms if avg_jitter_ms is not None else 0.0
        latency = avg_latency_ms if avg_latency_ms is not None else 0.0
        loss = packet_loss_pct if packet_loss_pct is not None else 0.0

        if jitter < 20 and latency < 100 and loss < 0.5:
            return "BOM"
        elif jitter < 30 and latency < 150 and loss < 1:
            return "MEDIO"
        else:
            return "RUIM"

    def calculate_hourly_metrics(self, machine_id: str, hours: int = 1) -> dict[str, Any]:
        """
        Calcula métricas horárias agregadas a partir das medições recentes.

        Args:
            machine_id: ID da máquina
            hours: Janela de tempo para cálculo (padrão: 1 hora)

        Returns:
            Dict com métricas calculadas
        """
        measurements = self.repository.get_measurements(machine_id, hours=hours, limit=500)
        measurements = [m for m in measurements if m.get("status") in REACHABLE_STATUSES]
        if not measurements:
            return {
                "avg_latency_ms": None,
                "avg_jitter_ms": None,
                "packet_loss_pct": 0.0,
                "total_measurements": 0,
                "quality_status": "Sem dados",
            }

        latencies = [m.get("latency_ms") for m in measurements if m.get("latency_ms") is not None]
        jitters = [m.get("jitter_ms") for m in measurements if m.get("jitter_ms") is not None]
        losses = [m.get("packet_loss_percent", 0) for m in measurements]

        avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else None
        avg_jitter = round(sum(jitters) / len(jitters), 1) if jitters else None
        avg_loss = round(sum(losses) / len(losses), 2) if losses else 0.0
        total_count = len(measurements)

        quality_status = self.classify_quality(avg_jitter, avg_latency, avg_loss)

        return {
            "avg_latency_ms": avg_latency,
            "avg_jitter_ms": avg_jitter,
            "packet_loss_pct": avg_loss,
            "total_measurements": total_count,
            "quality_status": quality_status,
        }

    def get_user_feedback_stats(self, machine_id: str, limit: int = 100) -> dict[str, Any]:
        """
        Obtém estatísticas de feedback do usuário para uma máquina.

        Returns:
            Dict com contagem por label (bom, medio, ruim)
        """
        feedbacks = self.repository.list_machine_feedback(machine_id=machine_id, limit=limit)
        stats = {"bom": 0, "medio": 0, "ruim": 0, "total": len(feedbacks)}

        for fb in feedbacks:
            label = fb.get("label", "")
            if label in stats:
                stats[label] += 1

        return stats

    def save_user_feedback(
        self,
        machine_id: str,
        label: str,
        avg_latency_ms: float | None,
        avg_jitter_ms: float | None,
        packet_loss_pct: float,
    ) -> UserFeedback:
        """
        Salva feedback do usuário sobre qualidade de rede.

        Args:
            machine_id: ID da máquina
            label: "bom", "medio" ou "ruim"
            avg_latency_ms: Latência média no momento do feedback
            avg_jitter_ms: Jitter médio no momento do feedback
            packet_loss_pct: Perda de pacotes no momento do feedback

        Returns:
            UserFeedback criado
        """
        now = datetime.now(timezone.utc)
        hour_of_day = now.hour
        day_of_week = now.weekday()
        created_at = now.isoformat()

        data = {
            "machine_id": machine_id,
            "label": label,
            "latency_ms": avg_latency_ms,
            "jitter_ms": avg_jitter_ms,
            "packet_loss_percent": packet_loss_pct,
            "hour_of_day": hour_of_day,
            "day_of_week": day_of_week,
            "created_at": created_at,
        }

        result = self.repository.save_feedback(machine_id, label, {
            "latency_ms": avg_latency_ms,
            "jitter_ms": avg_jitter_ms,
            "packet_loss_percent": packet_loss_pct,
        })

        if not result:
            raise NetworkQualityError("Falha ao salvar feedback")

        return UserFeedback(
            machine_id=machine_id,
            label=label,
            avg_latency_ms=avg_latency_ms,
            avg_jitter_ms=avg_jitter_ms,
            packet_loss_pct=packet_loss_pct,
            hour_of_day=hour_of_day,
            day_of_week=day_of_week,
            created_at=created_at,
        )
