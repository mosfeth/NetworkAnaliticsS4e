#!/usr/bin/env python3
# src/supadiag/ml_train.py
# Script de treino do modelo LSTM - pode ser executado periodicamente

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch

# Garante que o pacote src é importável
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.supadiag.config import Settings
from src.supadiag.supabase_repository import SupabaseRepository
from src.supadiag.ml_trainer import NetworkQualityTrainer
from src.supadiag.ml_model import NetworkQualityLSTM


def main() -> int:
    parser = argparse.ArgumentParser(description="Treina modelo LSTM de qualidade de rede")
    parser.add_argument("--machine-id", required=True, help="ID da máquina para treinar")
    parser.add_argument("--epochs", type=int, default=50, help="Número de épocas")
    parser.add_argument("--batch-size", type=int, default=8, help="Tamanho do batch")
    parser.add_argument("--limit", type=int, default=5000, help="Limite de medições")
    parser.add_argument("--output", default="models", help="Diretório de saída")
    args = parser.parse_args()

    print(f"Treinando modelo para machine_id={args.machine_id}")
    print(f"Épocas: {args.epochs}, Batch: {args.batch_size}, Limit: {args.limit}")

    settings = Settings()
    repo = SupabaseRepository(settings)
    trainer = NetworkQualityTrainer(settings, repo)

    try:
        result = trainer.train(
            machine_id=args.machine_id,
            epochs=args.epochs,
            batch_size=args.batch_size,
            limit=args.limit,
        )

        print(f"\n[OK] Treino concluído!")
        print(f"  Épocas treinadas: {result.epochs_trained}")
        print(f"  Acurácia teste: {result.accuracy:.2%}")
        print(f"  F1-score: {result.f1_score:.2%}")
        print(f"  Acurácia validação: {result.val_accuracy:.2%}")
        print(f"  Melhor validação loss: {result.best_val_loss:.4f}")

        # Salva modelo
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)

        model_path = output_dir / f"model_{args.machine_id[:8]}.pth"
        torch.save(trainer.model.state_dict(), model_path)
        print(f"\n[OK] Modelo salvo em: {model_path}")

        # Salva métricas
        metrics_path = output_dir / f"metrics_{args.machine_id[:8]}.json"
        metrics_data = {
            "accuracy": result.accuracy,
            "f1_score": result.f1_score,
            "val_accuracy": result.val_accuracy,
            "val_f1": result.val_f1,
            "epochs_trained": result.epochs_trained,
            "best_val_loss": result.best_val_loss,
            "trained_at": result.trained_at,
            "machine_id": args.machine_id,
        }
        with open(metrics_path, "w") as f:
            json.dump(metrics_data, f, indent=2)
        print(f"[OK] Métricas salvas em: {metrics_path}")

        return 0

    except Exception as e:
        print(f"\n[ERRO] Erro no treino: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
