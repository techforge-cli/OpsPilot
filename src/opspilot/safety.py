import logging
import re
import sqlite3
from dataclasses import dataclass

from opspilot.config import Settings
from opspilot.models import Host
from opspilot.playbooks import Playbook

logger = logging.getLogger("opspilot.safety")

MAX_COMMAND_LENGTH = 2000
MAX_TIMEOUT_SECONDS = 300

DENY_PATTERNS = [
    r":\(\)\s*\{",
    r"\brm\s+-rf\s+/",
    r"\brm\s+-rf\s+/\*",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bcurl\s+\S+\s*\|\s*(sh|bash)\b",
    r"\bwget\s+.*\|\s*(sh|bash)\b",
    r"\b/etc/shadow\b",
    r"\b/etc/sudoers\b",
    r"\b/boot\b",
    r"\b/proc/sys\b",
    r"/dev/tcp/",
    r"\bnc\s+-e\b",
    r"\bncat\b",
    r"\bmknod\b",
    r"\bmkfifo\b",
    r"bash\s+-i",
    r"\breverse.shell\b",
]


@dataclass
class SafetyResult:
    allowed: bool
    requires_confirmation: bool
    reasons: list[str]


def _is_read_only_command(command: str) -> bool:
    lowered = command.lower()
    write_markers = (">", ">>", "tee ", "rm ", "mv ", "cp ", "chmod ", "chown ", "dd ", "mkfs", "systemctl restart", "systemctl stop", "systemctl disable")
    return not any(marker in lowered for marker in write_markers)


class SafetyGuard:
    def evaluate(self, playbook: Playbook, host: Host, settings: Settings, audit=None, **kwargs):
        reasons: list[str] = []
        if not playbook.steps:
            reasons.append("playbook has no steps")
        host_tags = getattr(host, "tags", ()) or ()
        applies_to = getattr(playbook, "applies_to", None) or {}
        if isinstance(applies_to, dict):
            host_scope = applies_to.get("hosts", {}) or {}
            allowed_tags = host_scope.get("tags", []) if isinstance(host_scope, dict) else []
            if allowed_tags and not (set(allowed_tags) & set(host_tags)):
                reasons.append("host not in playbook allowlist")
        for step in playbook.steps:
            if not isinstance(step, dict):
                reasons.append("malformed step")
                continue
            command = step.get("command", "")
            if not isinstance(command, str) or not command.strip():
                reasons.append("empty command")
                continue
            if len(command) > MAX_COMMAND_LENGTH:
                reasons.append("command length limit exceeded")
            try:
                timeout = int(step.get("timeout_seconds", 30))
            except (TypeError, ValueError):
                reasons.append("invalid timeout")
                timeout = 0
            if timeout <= 0 or timeout > MAX_TIMEOUT_SECONDS:
                reasons.append("command timeout limit exceeded")
            for pattern in DENY_PATTERNS:
                if re.search(pattern, command, re.IGNORECASE):
                    reasons.append(f"deny pattern matched: {pattern}")
        if getattr(playbook, "verifier_document", False) or getattr(playbook, "is_verifier", False):
            for step in playbook.steps:
                command = step.get("command", "") if isinstance(step, dict) else ""
                if isinstance(command, str) and command.strip() and not _is_read_only_command(command):
                    reasons.append("verifier step is not read-only")
        requires_confirmation = (
            getattr(playbook, "risk", "confirm") != "auto"
            or getattr(playbook, "source", "") != "builtin"
            or not settings.global_auto_mode
            or not getattr(playbook, "auto_run", False)
        )
        allowed = not reasons
        result = SafetyResult(allowed=allowed, requires_confirmation=requires_confirmation, reasons=reasons)
        message = "permitted" if allowed else "blocked"
        logger.info("safety %s playbook=%s host=%s reasons=%s", message, getattr(playbook, "id", ""), getattr(host, "id", ""), reasons)
        if audit is not None and callable(getattr(audit, "record", None)):
            try:
                audit.record(
                    "safety_decision",
                    host_id=getattr(host, "id", None),
                    message=message,
                    detail={"playbook_id": getattr(playbook, "id", None), "allowed": allowed, "reasons": reasons},
                )
            except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error):
                pass
        return result
