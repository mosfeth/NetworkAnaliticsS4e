from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    project_root: Path
    supabase_url: str
    supabase_key: str
    data_dir: Path
    memory_file: Path
    queue_file: Path
    task_name: str
    ping_count: int
    ping_timeout_seconds: float
    retention_days: int
    internet_check_enabled: bool
    internet_check_ip: str
    internet_check_frequency_seconds: int
    traceroute_enabled: bool
    traceroute_frequency_seconds: int
    traceroute_max_hops: int
    traceroute_timeout_seconds: float
    alert_enabled: bool
    alert_latency_warn: int
    alert_latency_crit: int
    alert_loss_warn: float
    alert_loss_crit: float
    alert_jitter_warn: int
    alert_jitter_crit: int
    alert_webhook_url: str
    alert_evaluation_window: int
    alert_cooldown: int

    @property
    def db_dir(self) -> Path:
        return self.data_dir


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_settings(root: Path | None = None) -> Settings:
    root = (root or project_root()).resolve()
    load_dotenv(root / ".env")

    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    supabase_key = os.getenv("SUPABASE_SECRET_KEY", "").strip() or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not supabase_url:
        raise ConfigError("SUPABASE_URL não está configurada. Copie .env.example para .env e preencha o arquivo.")
    if not supabase_key:
        raise ConfigError("Configure SUPABASE_SECRET_KEY (ou a chave legada SUPABASE_SERVICE_ROLE_KEY) no .env.")
    parsed_url = urlparse(supabase_url)
    if parsed_url.scheme != "https" or not parsed_url.hostname:
        raise ConfigError("SUPABASE_URL inválida. Use https://<project-ref>.supabase.co.")
    if supabase_key.startswith("sb_publishable_"):
        raise ConfigError("Use uma chave sb_secret_ ou service_role em SUPABASE_SECRET_KEY; chave publishable não tem acesso administrativo.")

    data_dir = Path(os.getenv("SUPADIAG_DATA_DIR", "data")).expanduser()
    if not data_dir.is_absolute():
        data_dir = root / data_dir

    return Settings(
        project_root=root,
        supabase_url=supabase_url.rstrip("/"),
        supabase_key=supabase_key,
        data_dir=data_dir,
        memory_file=root / "memory.txt",
        queue_file=data_dir / "pending_measurements.jsonl",
        task_name=os.getenv("SUPADIAG_TASK_NAME", "SupaDiag Monitor"),
        ping_count=int(os.getenv("SUPADIAG_PING_COUNT", "4")),
        ping_timeout_seconds=float(os.getenv("SUPADIAG_PING_TIMEOUT_SECONDS", "2.0")),
        retention_days=int(os.getenv("SUPADIAG_RETENTION_DAYS", "180")),
        internet_check_enabled=os.getenv("SUPADIAG_INTERNET_CHECK_ENABLED", "true").lower() == "true",
        internet_check_ip=os.getenv("SUPADIAG_INTERNET_CHECK_IP", "8.8.8.8").strip(),
        internet_check_frequency_seconds=int(os.getenv("SUPADIAG_INTERNET_CHECK_FREQUENCY", "300")),
        traceroute_enabled=os.getenv("SUPADIAG_TRACEROUTE_ENABLED", "true").lower() == "true",
        traceroute_frequency_seconds=int(os.getenv("SUPADIAG_TRACEROUTE_FREQUENCY", "3600")),
        traceroute_max_hops=int(os.getenv("SUPADIAG_TRACEROUTE_MAX_HOPS", "30")),
        traceroute_timeout_seconds=float(os.getenv("SUPADIAG_TRACEROUTE_TIMEOUT", "5.0")),
        alert_enabled=os.getenv("SUPADIAG_ALERT_ENABLED", "true").lower() == "true",
        alert_latency_warn=int(os.getenv("SUPADIAG_ALERT_LATENCY_WARN", "80")),
        alert_latency_crit=int(os.getenv("SUPADIAG_ALERT_LATENCY_CRIT", "150")),
        alert_loss_warn=float(os.getenv("SUPADIAG_ALERT_LOSS_WARN", "2")),
        alert_loss_crit=float(os.getenv("SUPADIAG_ALERT_LOSS_CRIT", "5")),
        alert_jitter_warn=int(os.getenv("SUPADIAG_ALERT_JITTER_WARN", "30")),
        alert_jitter_crit=int(os.getenv("SUPADIAG_ALERT_JITTER_CRIT", "50")),
        alert_webhook_url=os.getenv("SUPADIAG_ALERT_WEBHOOK_URL", "").strip(),
        alert_evaluation_window=int(os.getenv("SUPADIAG_ALERT_EVALUATION_WINDOW", "300")),
        alert_cooldown=int(os.getenv("SUPADIAG_ALERT_COOLDOWN", "900")),
    )


def ensure_runtime_files(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.memory_file.touch(exist_ok=True)
    settings.queue_file.parent.mkdir(parents=True, exist_ok=True)


def public_dict(settings: Settings) -> dict[str, Any]:
    return {
        "project_root": str(settings.project_root),
        "supabase_url": settings.supabase_url,
        "data_dir": str(settings.data_dir),
        "memory_file": str(settings.memory_file),
        "queue_file": str(settings.queue_file),
        "task_name": settings.task_name,
        "ping_count": settings.ping_count,
        "retention_days": settings.retention_days,
        "internet_check_enabled": settings.internet_check_enabled,
        "internet_check_ip": settings.internet_check_ip,
        "internet_check_frequency_seconds": settings.internet_check_frequency_seconds,
        "traceroute_enabled": settings.traceroute_enabled,
        "traceroute_frequency_seconds": settings.traceroute_frequency_seconds,
        "traceroute_max_hops": settings.traceroute_max_hops,
        "traceroute_timeout_seconds": settings.traceroute_timeout_seconds,
        "alert_enabled": settings.alert_enabled,
        "alert_latency_warn": settings.alert_latency_warn,
        "alert_latency_crit": settings.alert_latency_crit,
        "alert_loss_warn": settings.alert_loss_warn,
        "alert_loss_crit": settings.alert_loss_crit,
        "alert_jitter_warn": settings.alert_jitter_warn,
        "alert_jitter_crit": settings.alert_jitter_crit,
        "alert_webhook_url": settings.alert_webhook_url,
        "alert_evaluation_window": settings.alert_evaluation_window,
        "alert_cooldown": settings.alert_cooldown,
    }
