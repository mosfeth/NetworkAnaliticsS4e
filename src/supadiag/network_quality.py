# src/supadiag/network_quality.py
# Módulo de qualidade de rede com aprendizado contínuo

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
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

DEFAULT_THRESHOLDS = {
    "latency_ms": {"warn": 100.0, "crit": 150.0},
    "jitter_ms": {"warn": 20.0, "crit": 30.0},
    "packet_loss_percent": {"warn": 0.5, "crit": 1.0},
}
DEFAULT_LATENCY_CENTROIDS = {"BOM": 30.0, "MÉDIO": 80.0, "RUIM": 180.0}


def learn_quality_thresholds(feedbacks: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Aprende as faixas de qualidade (BOM / MÉDIO / RUIM) a partir dos feedbacks
    salvos pelo operador em `machine_feedback`.
    """
    counts = {"bom": 0, "medio": 0, "ruim": 0}
    grouped: dict[str, dict[str, list[float]]] = {
        metric: {"bom": [], "medio": [], "ruim": []}
        for metric in DEFAULT_THRESHOLDS
    }

    for row in feedbacks or []:
        label = str(row.get("label", "")).lower()
        if label not in counts:
            continue
        counts[label] += 1
        for metric in DEFAULT_THRESHOLDS:
            raw = row.get(metric)
            if raw is None and metric == "packet_loss_percent":
                raw = row.get("packet_loss_pct")
            try:
                val = float(raw)
                if math.isfinite(val) and val >= 0:
                    grouped[metric][label].append(val)
            except (TypeError, ValueError):
                continue

    thresholds: dict[str, dict[str, float]] = {}
    ranges: dict[str, dict[str, tuple[float, float | None]]] = {}
    for metric, defaults in DEFAULT_THRESHOLDS.items():
        bom_vals = sorted(grouped[metric]["bom"])
        medio_vals = sorted(grouped[metric]["medio"])
        ruim_vals = sorted(grouped[metric]["ruim"])

        bom_med = median(bom_vals) if bom_vals else None
        medio_med = median(medio_vals) if medio_vals else None
        ruim_med = median(ruim_vals) if ruim_vals else None

        warn = defaults["warn"]
        if bom_med is not None and medio_med is not None and bom_med < medio_med:
            warn = (bom_med + medio_med) / 2.0
        elif bom_med is not None and ruim_med is not None and bom_med < ruim_med:
            warn = bom_med + (ruim_med - bom_med) / 3.0
        elif bom_vals and bom_vals[-1] > 0:
            warn = max(defaults["warn"], bom_vals[-1] * 1.1)
        elif medio_vals and medio_vals[0] > 0:
            warn = min(defaults["warn"], medio_vals[0])

        crit = defaults["crit"]
        if medio_med is not None and ruim_med is not None and medio_med < ruim_med:
            crit = (medio_med + ruim_med) / 2.0
        elif bom_med is not None and ruim_med is not None and bom_med < ruim_med:
            crit = bom_med + 2.0 * (ruim_med - bom_med) / 3.0
        elif ruim_vals and ruim_vals[0] > warn:
            crit = ruim_vals[0]

        if crit <= warn:
            crit = max(warn * 1.25, warn + 1.0)

        warn = round(warn, 2)
        crit = round(crit, 2)
        thresholds[metric] = {"warn": warn, "crit": crit}
        ranges[metric] = {
            "bom": (0.0, warn),
            "medio": (warn, crit),
            "ruim": (crit, None),
        }

    lat_grouped = grouped["latency_ms"]
    latency_centroids = {
        "BOM": round(median(lat_grouped["bom"]), 1) if lat_grouped["bom"] else DEFAULT_LATENCY_CENTROIDS["BOM"],
        "MÉDIO": round(median(lat_grouped["medio"]), 1) if lat_grouped["medio"] else DEFAULT_LATENCY_CENTROIDS["MÉDIO"],
        "RUIM": round(median(lat_grouped["ruim"]), 1) if lat_grouped["ruim"] else DEFAULT_LATENCY_CENTROIDS["RUIM"],
    }

    metric_centroids: dict[str, tuple[float, float, float]] = {}
    for metric, defaults in DEFAULT_THRESHOLDS.items():
        g = grouped[metric]
        fallback_bom = DEFAULT_LATENCY_CENTROIDS["BOM"] if metric == "latency_ms" else round(defaults["warn"] * 0.5, 2)
        fallback_med = DEFAULT_LATENCY_CENTROIDS["MÉDIO"] if metric == "latency_ms" else round((defaults["warn"] + defaults["crit"]) / 2.0, 2)
        fallback_ruim = DEFAULT_LATENCY_CENTROIDS["RUIM"] if metric == "latency_ms" else round(defaults["crit"] * 1.5, 2)
        metric_centroids[metric] = (
            round(median(g["bom"]), 2) if g["bom"] else fallback_bom,
            round(median(g["medio"]), 2) if g["medio"] else fallback_med,
            round(median(g["ruim"]), 2) if g["ruim"] else fallback_ruim,
        )

    total = sum(counts.values())
    return {
        "total_feedbacks": total,
        "counts": counts,
        "has_learned": total > 0,
        "thresholds": thresholds,
        "ranges": ranges,
        "latency_centroids": latency_centroids,
        "metric_centroids": metric_centroids,
    }


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
        learned_thresholds: dict[str, Any] | None = None,
    ) -> str:
        """
        Classifica qualidade da conexão baseado em thresholds (fixos ou aprendidos dos feedbacks).
        """
        jitter = avg_jitter_ms if avg_jitter_ms is not None else 0.0
        latency = avg_latency_ms if avg_latency_ms is not None else 0.0
        loss = packet_loss_pct if packet_loss_pct is not None else 0.0

        th = (learned_thresholds or {}).get("thresholds", DEFAULT_THRESHOLDS)
        lat_th = th.get("latency_ms", DEFAULT_THRESHOLDS["latency_ms"])
        jit_th = th.get("jitter_ms", DEFAULT_THRESHOLDS["jitter_ms"])
        loss_th = th.get("packet_loss_percent", DEFAULT_THRESHOLDS["packet_loss_percent"])

        if jitter < jit_th["warn"] and latency < lat_th["warn"] and loss < loss_th["warn"]:
            return "BOM"
        elif jitter < jit_th["crit"] and latency < lat_th["crit"] and loss < loss_th["crit"]:
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
