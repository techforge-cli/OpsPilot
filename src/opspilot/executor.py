from __future__ import annotations

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


def _run_local(command: str, timeout: int = 30):
    return subprocess.run(
        ["bash", "-lc", command], capture_output=True, text=True, timeout=timeout
    )


class PlaybookExecutor:
    def __init__(self, settings=None):
        self.settings = settings

    def run(self, playbook, host):
        stdout = ""
        stderr = ""
        healthy = True
        for step in playbook.steps:
            timeout = int(step.get("timeout_seconds", 30))
            command = step["command"]
            if getattr(host, "execution_mode", "local") == "ssh":
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
                )
            else:
                proc = _run_local(command, timeout)
            stdout += proc.stdout or ""
            stderr += proc.stderr or ""
            if proc.returncode != 0:
                healthy = False
                break
        return ExecutionResult(healthy=healthy, stdout=stdout, stderr=stderr)
