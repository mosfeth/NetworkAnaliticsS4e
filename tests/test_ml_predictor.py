from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from supadiag.ml_predictor import NetworkQualityPredictor


class _FakeRepo:
    def get_machine(self, machine_id: str):
        return SimpleNamespace(id=machine_id, client_id="client-1", tag="LOCAL-1", frequency_seconds=300)

    def list_machines(self, client_id: str | None = None, active_only: bool = True):
        return [
            SimpleNamespace(id="m1", client_id="client-1", tag="LOCAL-1", frequency_seconds=300),
            SimpleNamespace(id="m-inet", client_id="client-1", tag="INTERNET-CHECK", frequency_seconds=300),
        ]


def test_predict_series_sliding_window(tmp_path: Path):
    settings = SimpleNamespace(project_root=tmp_path)
    predictor = NetworkQualityPredictor(settings, _FakeRepo())
    predictor.loaded_machine_id = "m1"
    predictor.scaler_mean = np.zeros(10, dtype=np.float32)
    predictor.scaler_scale = np.ones(10, dtype=np.float32)

    base = datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc)
    measurements = [
        {
            "measured_at": (base + timedelta(minutes=5 * i)).isoformat(),
            "latency_ms": 20.0 + i,
            "jitter_ms": 2.0,
            "packet_loss_percent": 0.0,
        }
        for i in range(15)
    ]
    internet = [
        {
            "measured_at": (base + timedelta(minutes=5 * i)).isoformat(),
            "latency_ms": 30.0,
            "jitter_ms": 3.0,
            "packet_loss_percent": 0.0,
        }
        for i in range(15)
    ]

    for i in range(15):
        if i == 5:
            measurements[i]["latency_ms"] = float("nan")
            measurements[i]["jitter_ms"] = None

    series = predictor.predict_series(
        "m1", measurements, internet_measurements=internet, max_points=10, horizon_seconds=30
    )

    assert len(series) == 4  # 15 - 12 + 1 = 4 janelas
    for point in series:
        assert point["predicted_class"] in (0, 1, 2)
        assert point["predicted_label"] in ("BOM", "MÉDIO", "RUIM")
        assert 0.0 <= point["confidence"] <= 1.0
        assert np.isfinite(point["confidence"])
        assert len(point["probs"]) == 3
        assert abs(sum(point["probs"]) - 1.0) < 1e-4
        base_dt = datetime.fromisoformat(point["base_at"])
        forecast_dt = datetime.fromisoformat(point["forecast_at"])
        assert forecast_dt - base_dt == timedelta(seconds=30)
