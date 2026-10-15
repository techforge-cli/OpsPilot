from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opspilot.models import Host


@dataclass
class ExecutionResult:
    healthy: bool
    stdout: str
    stderr: str


def _local_env() -> dict[str, str]:
    path = os.environ.get("PATH")
    return {"PATH": path} if path is not None else {"PATH": ""}


def _run_local(command: str, timeout: int = 30):
    return subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_local_env(),
    )


class PlaybookExecutor:
    def __init__(self, settings=None):
        self.settings = settings

    def run(self, playbook, host):
        stdout = ""
        stderr = ""
        healthy = True
        for step in playbook.steps:
            try:
                timeout = int(step.get("timeout_seconds", 30))
                command = step["command"]
                if host.execution_mode == "ssh":
                    proc = subprocess.run(
                        [
                            "ssh",
                            "-i",
                            host.ssh_key_path,
                            "-p",
                            str(host.ssh_port),
                            f"{host.ssh_user}@{host.address}",
                            "bash",
                            "-lc",
                            command,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        env=_local_env(),
                    )
                else:
                    proc = _run_local(command, timeout)
            except Exception as exc:  # noqa: BLE001
                stderr += str(exc)
                healthy = False
                break
            stdout += proc.stdout or ""
            stderr += proc.stderr or ""
            if proc.returncode != 0:
                healthy = False
                break
        return ExecutionResult(healthy=healthy, stdout=stdout, stderr=stderr)
