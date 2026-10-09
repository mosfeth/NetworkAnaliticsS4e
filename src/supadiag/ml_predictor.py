# src/supadiag/ml_predictor.py
# Preditor de qualidade de rede usando modelo LSTM treinado

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

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
        self.model = NetworkQualityLSTM(input_features=8)
        self.model = self.model.to(self.device)
        self.model.eval()

        if model_path:
            self.load_model(model_path)

    def load_model(self, path: str) -> None:
        """Carrega pesos do modelo."""
        state_dict = torch.load(path, map_location=self.device)
        self.model.load_state_dict(state_dict)

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

        if len(measurements) < 12:
            raise ValueError("Dados insuficientes para previsão (mínimo 12 medições)")

        # Prepara sequência de entrada
        sequence = self._prepare_sequence(measurements[-12:])

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
                probs = self.model(input_tensor)
                confidence, class_idx = torch.max(probs, dim=1)

            forecast_classes.append(class_idx.item())
            forecast_confidences.append(confidence.item())
            forecast_labels.append(["BOM", "MÉDIO", "RUIM"][class_idx.item()])
            forecast_hours.append((now + timedelta(hours=h)).strftime("%H:%M"))

            # Atualiza sequência para próxima predição
            # (simplificado: repete última entrada com features da hora predita)
            last_features = current_sequence[-1].copy()
            last_features[0] = last_features[0] * (1 + np.random.normal(0, 0.1))  # latency
            last_features[1] = last_features[1] * (1 + np.random.normal(0, 0.1))  # jitter
            last_features[2] = last_features[2] * (1 + np.random.normal(0, 0.1))  # loss
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

    def _prepare_sequence(self, measurements: list[dict]) -> np.ndarray:
        """Prepara sequência de features para o modelo."""
        sequence = []

        for m in measurements:
            ts = datetime.fromisoformat(m.get("measured_at", ""))
            hour = ts.hour
            day = ts.weekday()

            sequence.append([
                m.get("latency_ms") or 0,
                m.get("jitter_ms") or 0,
                m.get("packet_loss_percent") or 0,
                m.get("packets_received", 0) / max(m.get("packets_sent", 1), 1) * 100,
                np.sin(2 * np.pi * hour / 24),
                np.cos(2 * np.pi * hour / 24),
                np.sin(2 * np.pi * day / 7),
                np.cos(2 * np.pi * day / 7),
            ])

        return np.array(sequence, dtype=np.float32)
