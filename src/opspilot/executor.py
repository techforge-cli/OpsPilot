from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from opspilot.playbooks import Playbook
from opspilot.safety import SafetyGuard, SafetyResult


@dataclass
class ExecutionResult:
    healthy: bool
    stdout: str = ""
    stderr: str = ""
    blocked: bool = False
    safety: SafetyResult | None = None
    metric_recheck: bool | None = None


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
        check=False,
    )


class PlaybookExecutor:
    def __init__(self, settings=None, safety_guard=None, audit=None):
        self.settings = settings
        self.safety_guard = safety_guard if safety_guard is not None else SafetyGuard()
        self.audit = audit

    def _run_one(self, command: str, timeout: int, host: Any):
        if getattr(host, "execution_mode", "local") == "ssh":
            return subprocess.run(
                [
                    "ssh",
                    "-i",
                    getattr(host, "ssh_key_path", None),
                    "-p",
                    str(getattr(host, "ssh_port", 22)),
                    f"{getattr(host, 'ssh_user', '')}@{getattr(host, 'address', '')}",
                    "bash",
                    "-lc",
                    command,
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=_local_env(),
                check=False,
            )
        return _run_local(command, timeout)

    def run(
        self,
        playbook: Playbook,
        host: Any,
        verifier: Playbook | None = None,
        metric_recheck: Callable[[], bool] | None = None,
        metric_checker: Callable[[], bool] | None = None,
        recheck: Callable[[], bool] | None = None,
        safety_guard: SafetyGuard | None = None,
        **kwargs: Any,
    ) -> ExecutionResult:
        guard = safety_guard if safety_guard is not None else self.safety_guard
        if metric_recheck is None:
            metric_recheck = metric_checker if metric_checker is not None else recheck
        if metric_recheck is None:
            metric_recheck = kwargs.get("metric_checker", kwargs.get("recheck", kwargs.get("metric_recheck")))
        settings = kwargs.get("settings", self.settings)
        if settings is None:
            from opspilot.config import Settings

            settings = Settings()  # type: ignore[call-arg]
        safety = guard.evaluate(playbook, host, settings, audit=self.audit)
        if not safety.allowed:
            return ExecutionResult(healthy=False, blocked=True, safety=safety, stderr="; ".join(safety.reasons))
        stdout = ""
        stderr = ""
        healthy = True
        for step in playbook.steps:
            if not isinstance(step, dict):
                healthy = False
                stderr += "malformed step"
                break
            command = step.get("command", "")
            timeout = int(step.get("timeout_seconds", 30) or 30)
            try:
                proc = self._run_one(command, timeout, host)
            except (OSError, subprocess.SubprocessError, ValueError, TypeError) as exc:
                stderr += str(exc)
                healthy = False
                break
            stdout += proc.stdout or ""
            stderr += proc.stderr or ""
            if proc.returncode != 0:
                healthy = False
                break
        if healthy and verifier is not None and getattr(verifier, "is_verifier", False):
            verifier_safety = guard.evaluate(verifier, host, settings, audit=self.audit)
            if not verifier_safety.allowed:
                return ExecutionResult(healthy=False, blocked=True, safety=verifier_safety, stdout=stdout, stderr=stderr + "; " + "; ".join(verifier_safety.reasons))
            for step in verifier.steps:
                if not isinstance(step, dict):
                    healthy = False
                    stderr += "malformed step"
                    break
                command = step.get("command", "")
                timeout = int(step.get("timeout_seconds", 30) or 30)
                try:
                    proc = self._run_one(command, timeout, host)
                except (OSError, subprocess.SubprocessError, ValueError, TypeError) as exc:
                    stderr += str(exc)
                    healthy = False
                    break
                stdout += proc.stdout or ""
                stderr += proc.stderr or ""
                if proc.returncode != 0:
                    healthy = False
                    break
        recheck_result = None
        if healthy and metric_recheck is not None:
            try:
                recheck_result = bool(metric_recheck())
            except (OSError, RuntimeError, ValueError, TypeError):
                recheck_result = False
            healthy = healthy and bool(recheck_result)
        return ExecutionResult(healthy=healthy, stdout=stdout, stderr=stderr, safety=safety, metric_recheck=recheck_result)
