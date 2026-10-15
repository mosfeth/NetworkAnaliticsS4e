# src/supadiag/ml_model.py
# Modelo PyTorch para previsão de qualidade de rede (LSTM)

import torch
import torch.nn as nn
import numpy as np


class NetworkQualityLSTM(nn.Module):
    """
    LSTM para classificação de qualidade de rede.
    
    Entrada: (batch, sequence_length, features)
    Saída: (batch, 3) - probabilidades para BOM, MÉDIO, RUIM
    """

    def __init__(
        self,
        input_features: int = 10,
        hidden_size: int = 64,
        num_layers: int = 2,
        output_classes: int = 3,
        dropout: float = 0.3,
    ) -> None:
        super().__init__()
        self.hidden_size = hidden_size
        self.num_layers = num_layers

        self.lstm = nn.LSTM(
            input_size=input_features,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.dropout = nn.Dropout(dropout)
        self.fc1 = nn.Linear(hidden_size, 16)
        self.relu = nn.ReLU()
        self.fc2 = nn.Linear(16, output_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Forward pass.
        
        Args:
            x: Tensor de entrada (batch, seq_len, features)
            
        Returns:
            Tensor de saída (batch, 3) com probabilidades
        """
        lstm_out, _ = self.lstm(x)
        last_timestep = lstm_out[:, -1, :]
        out = self.dropout(last_timestep)
        out = self.fc1(out)
        out = self.relu(out)
        out = self.fc2(out)
        return out

    def predict_class(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Prediz classe e probabilidade.

        Returns:
            (classes, probabilidades)
        """
        self.eval()
        with torch.no_grad():
            probs = torch.softmax(self.forward(x), dim=1)
            classes = torch.argmax(probs, dim=1)
        return classes, probs


def state_dict_to_jsonable(state_dict: dict) -> dict:
    """Converte um state_dict do PyTorch em estrutura JSON-serializável (listas)."""
    return {name: tensor.detach().cpu().tolist() for name, tensor in state_dict.items()}


def jsonable_to_state_dict(payload: dict) -> dict:
    """Converte listas do Supabase de volta para tensores do PyTorch."""
    return {name: torch.tensor(values) for name, values in payload.items()}
