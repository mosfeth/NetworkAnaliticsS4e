"""Inicia o dashboard usando o launcher isolado da pasta FrontEnd."""

import subprocess
import sys
from pathlib import Path


def main() -> int:
    frontend_dir = Path(__file__).resolve().parent
    launcher = frontend_dir / "start.bat"
    if not launcher.exists():
        print(f"Launcher não encontrado: {launcher}")
        return 1
    completed = subprocess.run(["cmd.exe", "/c", str(launcher)], cwd=frontend_dir)
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main())
