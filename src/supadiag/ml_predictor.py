# src/supadiag/ml_predictor.py
# Preditor de qualidade de rede usando modelo LSTM treinado

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import torch

from .ml_model import NetworkQualityLSTM
from .config import Settings
from .supabase_repository import SupabaseRepository


@dataclass
class PredictionResult:
    """Resultado de uma predição."""
    machine_id: str
    predicted_class: int
    predicted_label: str
    confidence: float
    predicted_at: str
    forecast_hours: list[str]
    forecast_classes: list[int]
    forecast_labels: list[str]
    forecast_confidences: list[float]


class NetworkQualityPredictor:
    """Preditor de qualidade de rede."""

    def __init__(
        self,
        settings: Settings,
        repository: SupabaseRepository,
        model_path: str | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = NetworkQualityLSTM(input_features=10)
        self.model = self.model.to(self.device)
        self.model.eval()
        self.model_path = Path(model_path) if model_path else None
        self.scaler_mean: np.ndarray | None = None
        self.scaler_scale: np.ndarray | None = None
        self.loaded_machine_id: str | None = None

    def load_model(self, path: str) -> None:
        """Carrega pesos e normalizador persistidos pelo comando de treino."""
        artifact = torch.load(path, map_location=self.device, weights_only=True)
        if not isinstance(artifact, dict) or "state_dict" not in artifact:
            raise ValueError("Artefato de IA antigo/incompleto; treine o modelo novamente.")
        try:
            self.model.load_state_dict(artifact["state_dict"])
        except RuntimeError as exc:
            raise ValueError("Modelo antigo: registre avaliações para treinar a versão combinada.") from exc
        self.scaler_mean = np.asarray(artifact["scaler_mean"], dtype=np.float32)
        self.scaler_scale = np.asarray(artifact["scaler_scale"], dtype=np.float32)
        self.loaded_machine_id = artifact.get("machine_id")
        self.model.eval()

    def predict_next_4h(
        self, machine_id: str, measurements: list[dict] | None = None
    ) -> PredictionResult:
        """
        Prediz qualidade para as próximas 4 horas.
        
        Args:
            machine_id: ID da máquina
            measurements: Lista de medições (opcional, busca do banco se None)
            
        Returns:
            PredictionResult com previsão
        """
        if measurements is None:
            measurements = self.repository.get_measurements(machine_id, hours=24, limit=500)

        machine = self.repository.get_machine(machine_id)
        related = self.repository.list_machines(client_id=machine.client_id, active_only=True) if machine else []
        internet_machine = next((item for item in related if item.tag == "INTERNET-CHECK"), None)
        if machine and machine.tag == "INTERNET-CHECK":
            internet_measurements = measurements
            internet_only = True
        else:
            internet_measurements = (
                self.repository.get_measurements(internet_machine.id, hours=24, limit=500)
                if internet_machine else []
            )
            internet_only = False

        model_path = self.model_path or (
            self.settings.project_root / "models" / f"model_{machine_id[:8]}.pth"
        )
        if not model_path.is_file():
            raise FileNotFoundError(
                f"Modelo ainda não treinado para esta máquina. Treine pelo botão do dashboard. ({model_path})"
            )
        if self.loaded_machine_id != machine_id:
            self.load_model(str(model_path))
        if self.loaded_machine_id != machine_id:
            raise ValueError("O modelo salvo pertence a outra máquina; treine novamente.")

        if len(measurements) < 12:
            raise ValueError("Dados insuficientes para previsão (mínimo 12 medições)")

        # Prepara sequência de entrada
        local_frequency = (getattr(machine, "frequency_seconds", 300) or 300) if machine else 300
        internet_frequency = (getattr(internet_machine, "frequency_seconds", 300) or 300) if internet_machine else 300
        pair_age = timedelta(seconds=max(900, local_frequency * 3, internet_frequency * 3))
        sequence = self._prepare_sequence(
            measurements[-12:], internet_measurements, internet_only, pair_age
        )

        # Predição para cada hora futura
        forecast_classes = []
        forecast_labels = []
        forecast_confidences = []
        forecast_hours = []

        current_sequence = sequence.copy()
        now = datetime.now(timezone.utc)

        for h in range(1, 5):
            # Prediz próxima hora
            input_tensor = torch.FloatTensor(current_sequence).unsqueeze(0).to(self.device)
            with torch.no_grad():
                probs = torch.softmax(self.model(input_tensor), dim=1)
                confidence, class_idx = torch.max(probs, dim=1)

            forecast_classes.append(class_idx.item())
            forecast_confidences.append(confidence.item())
            forecast_labels.append(["BOM", "MÉDIO", "RUIM"][class_idx.item()])
            forecast_hours.append((now + timedelta(hours=h)).strftime("%H:%M"))

            # Atualiza sequência para próxima predição
            # (simplificado: repete última entrada com features da hora predita)
            # Sem um modelo temporal multivariado de horizonte, carregar o último
            # estado é uma extrapolação estável e reproduzível, não ruído aleatório.
            last_features = current_sequence[-1].copy()
            current_sequence = np.vstack([current_sequence[1:], last_features])

        # Predição principal (próxima hora)
        main_class = forecast_classes[0]
        main_label = forecast_labels[0]
        main_confidence = forecast_confidences[0]

        return PredictionResult(
            machine_id=machine_id,
            predicted_class=main_class,
            predicted_label=main_label,
            confidence=main_confidence,
            predicted_at=now.isoformat(),
            forecast_hours=forecast_hours,
            forecast_classes=forecast_classes,
            forecast_labels=forecast_labels,
            forecast_confidences=forecast_confidences,
        )

    def _prepare_sequence(
        self,
        measurements: list[dict],
        internet_measurements: list[dict] | None = None,
        internet_only: bool = False,
        max_pair_age: timedelta = timedelta(minutes=15),
    ) -> np.ndarray:
        """Combine local and Internet signals using readings available at each time."""
        internet_measurements = internet_measurements or []

        def parse_stamp(row: dict) -> datetime:
            stamp = datetime.fromisoformat(str(row.get("measured_at", "")).replace("Z", "+00:00"))
            return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)

        timed_internet = sorted(
            ((parse_stamp(row), row) for row in internet_measurements), key=lambda pair: pair[0]
        )
        internet_times = [stamp for stamp, _ in timed_internet]
        sequence = []
        for row in measurements:
            stamp = parse_stamp(row)
            local_stamp = stamp.astimezone(ZoneInfo("America/Sao_Paulo"))
            internet_row = None
            internet_index = bisect_right(internet_times, stamp) - 1
            if internet_index >= 0 and stamp - internet_times[internet_index] <= max_pair_age:
                internet_row = timed_internet[internet_index][1]
            if internet_only:
                internet_row = internet_row or row
                local_metrics = (0.0, 0.0, 0.0)
            else:
                local_metrics = tuple(float(row.get(field) or 0) for field in (
                    "latency_ms", "jitter_ms", "packet_loss_percent"
                ))
            internet_metrics = tuple(float((internet_row or {}).get(field) or 0) for field in (
                "latency_ms", "jitter_ms", "packet_loss_percent"
            ))
            hour, day = local_stamp.hour, local_stamp.weekday()
            sequence.append([
                *local_metrics, *internet_metrics,
                np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24),
                np.sin(2 * np.pi * day / 7), np.cos(2 * np.pi * day / 7),
            ])

        values = np.asarray(sequence, dtype=np.float32)
        if self.scaler_mean is not None and self.scaler_scale is not None:
            values = (values - self.scaler_mean) / np.where(self.scaler_scale == 0, 1, self.scaler_scale)
        return values
