"""Encaminha a inicialização para o launcher único da raiz do projeto."""

import subprocess
import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    launcher = project_root / "start.bat"
    if not launcher.exists():
        print(f"Launcher não encontrado: {launcher}")
        return 1
    completed = subprocess.run(["cmd.exe", "/c", str(launcher)], cwd=project_root)
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main())
