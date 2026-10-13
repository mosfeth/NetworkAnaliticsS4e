"""Executa o retreinamento supervisionado sem bloquear o dashboard."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

from .config import load_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Retreinamento supervisionado em segundo plano")
    parser.add_argument("--machine-id", required=True)
    parser.add_argument("--epochs", type=int, default=15)
    args = parser.parse_args()

    settings = load_settings()
    lock_dir = settings.data_dir / "ml_training"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = lock_dir / f"{args.machine_id}.lock"

    if lock_file.exists() and lock_file.stat().st_mtime < time.time() - 3600:
        lock_file.unlink(missing_ok=True)
    try:
        with lock_file.open("x", encoding="utf-8") as lock:
            lock.write(str(os.getpid()))
    except FileExistsError:
        print("Um treinamento para este equipamento já está em andamento.")
        return 0

    command = [
        sys.executable, "-m", "supadiag", "ml-train",
        "--machine-id", args.machine_id,
        "--epochs", str(args.epochs),
        "--limit", "5000",
    ]
    try:
        return subprocess.run(command, cwd=settings.project_root, check=False).returncode
    finally:
        lock_file.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
