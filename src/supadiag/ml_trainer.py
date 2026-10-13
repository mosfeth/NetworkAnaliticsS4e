# src/supadiag/ml_trainer.py
# Treinamento do modelo LSTM para qualidade de rede

from __future__ import annotations

import math
import json
from bisect import bisect_right
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, time as datetime_time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader, random_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, f1_score

from .supabase_repository import SupabaseRepository
from .config import Settings
from .ml_model import NetworkQualityLSTM


class NetworkQualityDataset(Dataset):
    """Dataset para séries temporais de qualidade de rede."""

    def __init__(self, sequences: np.ndarray, labels: np.ndarray) -> None:
        self.sequences = torch.FloatTensor(sequences)
        self.labels = torch.LongTensor(labels)

    def __len__(self) -> int:
        return len(self.sequences)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        return self.sequences[idx], self.labels[idx]


@dataclass
class TrainingResult:
    """Resultado do treinamento."""
    accuracy: float
    f1_score: float
    val_accuracy: float
    val_f1: float
    epochs_trained: int
    best_val_loss: float
    trained_at: str


class NetworkQualityTrainer:
    """Treinador do modelo LSTM."""

    def __init__(
        self,
        settings: Settings,
        repository: SupabaseRepository,
        sequence_length: int = 12,
        horizon: int = 4,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.sequence_length = sequence_length
        self.horizon = horizon
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.scaler = StandardScaler()
        self.model: NetworkQualityLSTM | None = None

    def prepare_data(self, machine_id: str, limit: int = 5000) -> tuple[np.ndarray, np.ndarray]:
        """Build labeled windows from operator feedback and paired local/Internet signals."""
        machine = self.repository.get_machine(machine_id)
        if not machine:
            raise ValueError("Equipamento não encontrado para treinamento.")

        primary = self.repository.get_measurements(machine_id, hours=720, limit=limit)
        feedbacks = self.repository.list_machine_feedback(machine_id=machine_id, limit=2000)
        related = self.repository.list_machines(client_id=machine.client_id, active_only=True)
        internet_machine = next((item for item in related if item.tag == "INTERNET-CHECK"), None)

        try:
            schedule_file = self.settings.data_dir / "work_schedules.json"
            schedules = json.loads(schedule_file.read_text(encoding="utf-8"))
            if not isinstance(schedules, dict):
                schedules = {}
        except (OSError, json.JSONDecodeError):
            schedules = {}

        def filter_schedule(rows: list[dict], equipment_id: str) -> list[dict]:
            schedule = {"enabled": True, "start": "07:00", "end": "18:00"}
            saved = schedules.get(equipment_id, {})
            if isinstance(saved, dict):
                schedule.update(saved)
            if not schedule.get("enabled", True):
                return rows
            try:
                start = datetime_time.fromisoformat(schedule.get("start", "07:00"))
                end = datetime_time.fromisoformat(schedule.get("end", "18:00"))
            except (TypeError, ValueError):
                start, end = datetime_time(7), datetime_time(18)
            result = []
            for row in rows:
                try:
                    parsed = datetime.fromisoformat(str(row.get("measured_at", "")).replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    local_time = parsed.astimezone(ZoneInfo("America/Sao_Paulo")).time().replace(second=0, microsecond=0)
                except (TypeError, ValueError):
                    continue
                inside = start <= local_time <= end if start <= end else local_time >= start or local_time <= end
                if inside:
                    result.append(row)
            return result

        primary = filter_schedule(primary, machine_id)
        if machine.tag == "INTERNET-CHECK":
            internet_rows = primary
        else:
            internet_rows = []
            if internet_machine and internet_machine.id != machine_id:
                internet_rows = self.repository.get_measurements(internet_machine.id, hours=720, limit=limit)
                internet_rows = filter_schedule(internet_rows, internet_machine.id)

        if len(primary) < self.sequence_length:
            raise ValueError("Ainda não há medições suficientes para montar uma sequência de treino.")
        if not feedbacks:
            raise ValueError("Ainda não há avaliações humanas para treinar o modelo.")

        def parse_timestamp(value: str) -> datetime | None:
            if not value:
                return None
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
            except (TypeError, ValueError):
                return None

        timed_primary = [
            (stamp, row) for row in primary
            if (stamp := parse_timestamp(row.get("measured_at", ""))) is not None
        ]
        timed_internet = [
            (stamp, row) for row in internet_rows
            if (stamp := parse_timestamp(row.get("measured_at", ""))) is not None
        ]
        times = [stamp for stamp, _ in timed_primary]
        internet_times = [stamp for stamp, _ in timed_internet]
        if len(timed_primary) < self.sequence_length:
            raise ValueError("Ainda não há medições válidas suficientes para formar as sequências.")

        frequency = getattr(machine, "frequency_seconds", 300) or 300
        internet_frequency = (getattr(internet_machine, "frequency_seconds", 300) or 300) if internet_machine else 300
        max_feedback_age = timedelta(seconds=max(900, frequency * 3))
        max_pair_age = timedelta(seconds=max(900, frequency * 3, internet_frequency * 3))
        class_ids = {"bom": 0, "medio": 1, "ruim": 2}
        labeled_windows: dict[int, tuple[list[list[float]], int]] = {}

        def number(row: dict, field: str) -> float:
            try:
                return float(row.get(field) or 0)
            except (TypeError, ValueError):
                return 0.0

        for feedback in sorted(feedbacks, key=lambda row: row.get("created_at", ""), reverse=True):
            label = class_ids.get(str(feedback.get("label", "")).lower())
            if label is None:
                continue
            notes = str(feedback.get("notes") or "")
            source_time = notes.removeprefix("source_measurement_at=") if notes.startswith("source_measurement_at=") else ""
            feedback_time = parse_timestamp(source_time) or parse_timestamp(feedback.get("created_at", ""))
            if feedback_time is None:
                continue
            target = bisect_right(times, feedback_time) - 1
            if target < self.sequence_length - 1 or target in labeled_windows:
                continue
            if feedback_time - times[target] > max_feedback_age:
                continue

            sequence = []
            valid_window = True
            for stamp, local_row in timed_primary[target - self.sequence_length + 1:target + 1]:
                internet_row = None
                if timed_internet:
                    internet_index = bisect_right(internet_times, stamp) - 1
                    if internet_index >= 0 and stamp - internet_times[internet_index] <= max_pair_age:
                        internet_row = timed_internet[internet_index][1]
                if machine.tag == "INTERNET-CHECK":
                    internet_row = internet_row or local_row
                    local_metrics = (0.0, 0.0, 0.0)
                else:
                    local_metrics = tuple(number(local_row, field) for field in (
                        "latency_ms", "jitter_ms", "packet_loss_percent"
                    ))
                if internet_machine and machine.tag != "INTERNET-CHECK" and internet_row is None:
                    valid_window = False
                    break
                internet_metrics = tuple(number(internet_row or {}, field) for field in (
                    "latency_ms", "jitter_ms", "packet_loss_percent"
                ))
                local_stamp = stamp.astimezone(ZoneInfo("America/Sao_Paulo"))
                hour, day = local_stamp.hour, local_stamp.weekday()
                sequence.append([
                    *local_metrics, *internet_metrics,
                    math.sin(2 * math.pi * hour / 24), math.cos(2 * math.pi * hour / 24),
                    math.sin(2 * math.pi * day / 7), math.cos(2 * math.pi * day / 7),
                ])
            if valid_window and len(sequence) == self.sequence_length:
                labeled_windows[target] = (sequence, label)

        samples = list(labeled_windows.values())
        if len(samples) < 15:
            raise ValueError(f"O treino aguarda 15 avaliações distintas com dados pareados válidos; disponíveis: {len(samples)}.")
        label_counts = np.bincount([label for _, label in samples], minlength=3)
        if np.any(label_counts < 5):
            raise ValueError("Classifique ao menos 5 amostras como Boa, 5 como Média e 5 como Ruim antes do treino.")

        features = np.asarray([sequence for sequence, _ in samples], dtype=np.float32)
        labels = np.asarray([label for _, label in samples], dtype=np.int64)
        n_samples, n_steps, n_features = features.shape
        scaled = self.scaler.fit_transform(features.reshape(-1, n_features))
        return scaled.reshape(n_samples, n_steps, n_features), labels
    def train(
        self,
        machine_id: str,
        epochs: int = 50,
        batch_size: int = 8,
        learning_rate: float = 0.001,
        limit: int = 5000,
    ) -> TrainingResult:
        """
        Treina o modelo LSTM.
        
        Args:
            machine_id: ID da máquina
            epochs: Número de épocas
            batch_size: Tamanho do batch
            learning_rate: Taxa de aprendizado
            limit: Limite de medições
            
        Returns:
            TrainingResult com métricas
        """
        # Prepara dados
        features, labels = self.prepare_data(machine_id, limit)
        if len(features) < 5:
            raise ValueError("Dados insuficientes: são necessárias pelo menos 5 janelas para treino, validação e teste.")

        # Dataset e DataLoader
        dataset = NetworkQualityDataset(features, labels)
        train_size = int(0.7 * len(dataset))
        val_size = int(0.2 * len(dataset))
        test_size = len(dataset) - train_size - val_size

        train_dataset, val_dataset, test_dataset = random_split(
            dataset, [train_size, val_size, test_size]
        )

        train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
        val_loader = DataLoader(val_dataset, batch_size=batch_size)
        test_loader = DataLoader(test_dataset, batch_size=batch_size)

        # Modelo
        model = NetworkQualityLSTM(input_features=10)
        model = model.to(self.device)

        # Loss e optimizer
        criterion = nn.CrossEntropyLoss()
        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode="min", patience=5, factor=0.5
        )

        # Treino
        best_val_loss = float("inf")
        best_model_state = None
        patience_counter = 0
        early_stopping_patience = 10

        for epoch in range(epochs):
            # Treino
            model.train()
            train_loss = 0.0
            for batch_x, batch_y in train_loader:
                batch_x = batch_x.to(self.device)
                batch_y = batch_y.to(self.device)

                optimizer.zero_grad()
                outputs = model(batch_x)
                loss = criterion(outputs, batch_y)
                loss.backward()
                optimizer.step()

                train_loss += loss.item() * batch_x.size(0)

            train_loss /= len(train_loader.dataset)

            # Validação
            model.eval()
            val_loss = 0.0
            all_preds = []
            all_labels = []

            with torch.no_grad():
                for batch_x, batch_y in val_loader:
                    batch_x = batch_x.to(self.device)
                    batch_y = batch_y.to(self.device)

                    outputs = model(batch_x)
                    loss = criterion(outputs, batch_y)

                    val_loss += loss.item() * batch_x.size(0)
                    preds = torch.argmax(outputs, dim=1)
                    all_preds.extend(preds.cpu().numpy())
                    all_labels.extend(batch_y.cpu().numpy())

            val_loss /= len(val_loader.dataset)

            # Métricas
            val_accuracy = accuracy_score(all_labels, all_preds)
            val_f1 = f1_score(all_labels, all_preds, average="weighted")

            # Scheduler
            scheduler.step(val_loss)

            # Early stopping
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_model_state = deepcopy(model.state_dict())
                patience_counter = 0
            else:
                patience_counter += 1

            if patience_counter >= early_stopping_patience:
                break

        # Carrega melhor modelo
        if best_model_state:
            model.load_state_dict(best_model_state)
        self.model = model

        # Avaliação final no teste
        model.eval()
        test_preds = []
        test_labels = []

        with torch.no_grad():
            for batch_x, batch_y in test_loader:
                batch_x = batch_x.to(self.device)
                outputs = model(batch_x)
                preds = torch.argmax(outputs, dim=1)
                test_preds.extend(preds.cpu().numpy())
                test_labels.extend(batch_y.cpu().numpy())

        test_accuracy = accuracy_score(test_labels, test_preds)
        test_f1 = f1_score(test_labels, test_preds, average="weighted")

        return TrainingResult(
            accuracy=test_accuracy,
            f1_score=test_f1,
            val_accuracy=val_accuracy,
            val_f1=val_f1,
            epochs_trained=epoch + 1,
            best_val_loss=best_val_loss,
            trained_at=datetime.now(timezone.utc).isoformat(),
        )
