from __future__ import annotations

import shutil
import subprocess
import sys
import time
from dataclasses import dataclass

from .config import Settings


class SchedulerError(RuntimeError):
    pass


@dataclass(frozen=True)
class SchedulerStatus:
    installed: bool
    output: str


class WindowsScheduler:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def install(self) -> SchedulerStatus:
        executable = shutil.which("schtasks.exe")
        if not executable:
            raise SchedulerError("schtasks.exe não foi encontrado.")
        action = subprocess.list2cmdline([sys.executable, "-m", "supadiag", "monitor"])
        command = [
            executable,
            "/Create",
            "/F",
            "/TN",
            self.settings.task_name,
            "/TR",
            action,
            "/SC",
            "ONSTART",
            "/RU",
            "SYSTEM",
            "/RL",
            "HIGHEST",
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if completed.returncode != 0:
            raise SchedulerError(completed.stderr.strip() or completed.stdout.strip() or "Falha ao criar tarefa.")
        return self.status()

    def status(self) -> SchedulerStatus:
        executable = shutil.which("schtasks.exe")
        if not executable:
            return SchedulerStatus(False, "schtasks.exe não foi encontrado.")
        completed = subprocess.run(
            [executable, "/Query", "/TN", self.settings.task_name, "/V", "/FO", "LIST"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return SchedulerStatus(completed.returncode == 0, (completed.stdout + completed.stderr).strip())

    def restart(self) -> SchedulerStatus:
        """Restart the scheduled task by removing and reinstalling it."""
        try:
            self.remove()
        except SchedulerError:
            # If removal fails, continue anyway (task might not exist)
            pass
        # Small delay to ensure clean state
        time.sleep(1)
        return self.install()

    def is_running(self) -> bool:
        """Check if the scheduled task is currently running."""
        executable = shutil.which("schtasks.exe")
        if not executable:
            return False
        # Query for running instances of the task
        completed = subprocess.run(
            [executable, "/Query", "/TN", self.settings.task_name, "/FO", "LIST", "/V"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            return False
        # Look for "Running" status in the output
        output = completed.stdout.upper()
        return "RUNNING" in output or "EM EXECUÇÃO" in output

    def remove(self) -> None:
        executable = shutil.which("schtasks.exe")
        if not executable:
            raise SchedulerError("schtasks.exe não foi encontrado.")
        completed = subprocess.run(
            [executable, "/Delete", "/TN", self.settings.task_name, "/F"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            raise SchedulerError(completed.stderr.strip() or completed.stdout.strip() or "Falha ao remover tarefa.")
