# src/supadiag/ml_trainer.py
# Treinamento do modelo LSTM para qualidade de rede

from __future__ import annotations

import math
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

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

    def prepare_data(self, machine_id: str, limit: int = 5000) -> tuple[np.ndarray, np.ndarray]:
        """
        Prepara dados para treinamento.
        
        Args:
            machine_id: ID da máquina
            limit: Limite de medições para buscar
            
        Returns:
            (sequences, labels) arrays numpy
        """
        measurements = self.repository.get_measurements(machine_id, hours=720, limit=limit)
        if not measurements or len(measurements) < self.sequence_length + self.horizon:
            raise ValueError("Dados insuficientes para treinamento")

        # Extrai features
        features = []
        labels = []

        for i in range(len(measurements) - self.sequence_length - self.horizon + 1):
            window = measurements[i : i + self.sequence_length]
            target_idx = i + self.sequence_length + self.horizon - 1
            target = measurements[target_idx]

            # Features do window
            seq_features = []
            for m in window:
                ts = datetime.fromisoformat(m.get("measured_at", ""))
                hour = ts.hour
                day = ts.weekday()

                seq_features.append([
                    m.get("latency_ms") or 0,
                    m.get("jitter_ms") or 0,
                    m.get("packet_loss_percent") or 0,
                    m.get("packets_received", 0) / max(m.get("packets_sent", 1), 1) * 100,
                    math.sin(2 * math.pi * hour / 24),
                    math.cos(2 * math.pi * hour / 24),
                    math.sin(2 * math.pi * day / 7),
                    math.cos(2 * math.pi * day / 7),
                ])

            features.append(seq_features)

            # Label: baseado nas regras atuais
            latency = target.get("latency_ms") or 0
            jitter = target.get("jitter_ms") or 0
            loss = target.get("packet_loss_percent") or 0

            if jitter < 20 and latency < 100 and loss < 0.5:
                labels.append(0)  # BOM
            elif jitter < 30 and latency < 150 and loss < 1:
                labels.append(1)  # MÉDIO
            else:
                labels.append(2)  # RUIM

        features = np.array(features, dtype=np.float32)
        labels = np.array(labels, dtype=np.int64)

        # Normaliza features
        n_samples, n_steps, n_features = features.shape
        features_reshaped = features.reshape(-1, n_features)
        features_scaled = self.scaler.fit_transform(features_reshaped)
        features = features_scaled.reshape(n_samples, n_steps, n_features)

        return features, labels

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
        model = NetworkQualityLSTM(input_features=8)
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
                best_model_state = model.state_dict().copy()
                patience_counter = 0
            else:
                patience_counter += 1

            if patience_counter >= early_stopping_patience:
                break

        # Carrega melhor modelo
        if best_model_state:
            model.load_state_dict(best_model_state)

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
