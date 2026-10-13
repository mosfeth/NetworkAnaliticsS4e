from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .models import MeasurementSample


class ProbeExecutionError(RuntimeError):
    """Raised when the local ping process itself could not run."""


@dataclass(frozen=True)
class ProbeResult:
    latency_ms: float | None
    jitter_ms: float | None
    packet_loss_percent: float
    packets_sent: int
    packets_received: int
    status: str


def _build_sample(client_id: str, machine_id: str, result: ProbeResult) -> MeasurementSample:
    return MeasurementSample(
        client_id=client_id,
        machine_id=machine_id,
        latency_ms=result.latency_ms,
        jitter_ms=result.jitter_ms,
        packet_loss_percent=result.packet_loss_percent,
        packets_sent=result.packets_sent,
        packets_received=result.packets_received,
        status=result.status,
        measured_at=datetime.now(timezone.utc).isoformat(),
    )


def _run_ping_windows(ip: str, count: int, timeout_ms: int) -> list[int]:
    """Run ping.exe on Windows and return list of RTTs in ms."""
    cmd = ["ping", "-n", str(count), "-w", str(timeout_ms), ip]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=(count * timeout_ms / 1000) + 10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProbeExecutionError(f"Não foi possível executar ping para {ip}: {exc}") from exc
    
    round_trips: list[int] = []
    # Parse each line for RTT (handles Portuguese "tempo" and English "time")
    for line in completed.stdout.splitlines():
        match = re.search(r"(?:tempo|time)\s*[=<]\s*(\d+(?:[.,]\d+)?)\s*ms", line, re.IGNORECASE)
        if match:
            round_trips.append(int(float(match.group(1).replace(",", "."))))
    return round_trips


def _run_ping_unix(ip: str, count: int, timeout_ms: int) -> list[int]:
    """Run ping on Unix-like systems and return list of RTTs in ms."""
    timeout_s = max(1, timeout_ms / 1000)
    cmd = ["ping", "-c", str(count), "-W", str(int(timeout_s)), ip]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=(count * timeout_s) + 10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProbeExecutionError(f"Não foi possível executar ping para {ip}: {exc}") from exc
    
    round_trips: list[int] = []
    for line in completed.stdout.splitlines():
        match = re.search(r"time[=<]\s*(\d+(?:\.\d+)?)\s*ms", line)
        if match:
            round_trips.append(int(float(match.group(1))))
    return round_trips


def measure_host(
    ip: str,
    client_id: str,
    machine_id: str,
    count: int = 100,
    timeout_seconds: float = 2.0,
    probe: Callable[[str, int], int | None] | None = None,
) -> MeasurementSample:
    normalized = ip.strip()
    timeout_ms = max(1, int(timeout_seconds * 1000))
    
    if probe is None:
        # Use subprocess ping (reliable on both Windows and Unix)
        if os.name == "nt":
            round_trips = _run_ping_windows(normalized, count, timeout_ms)
        else:
            round_trips = _run_ping_unix(normalized, count, timeout_ms)
    else:
        round_trips = []
        for _ in range(count):
            value = probe(normalized, timeout_ms)
            if value is not None:
                round_trips.append(max(0, int(value)))
    
    received = len(round_trips)
    loss = 100.0 if count == 0 else ((count - received) / count) * 100
    latency = round(sum(round_trips) / received, 3) if received else None
    differences = [abs(current - previous) for previous, current in zip(round_trips, round_trips[1:])]
    jitter = round(sum(differences) / len(differences), 3) if len(differences) > 1 else (0.0 if received > 1 else None)
    
    if received == count:
        status = "ok"
    elif received:
        status = "partial"
    else:
        status = "unreachable"
    
    result = ProbeResult(latency, jitter, round(loss, 2), count, received, status)
    return _build_sample(client_id, machine_id, result)
