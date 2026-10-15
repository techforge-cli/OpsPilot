import re
from dataclasses import dataclass

from opspilot.config import Settings
from opspilot.models import Host
from opspilot.playbooks import Playbook


@dataclass
class SafetyResult:
    allowed: bool
    requires_confirmation: bool
    reasons: list[str]


DENY_PATTERNS = [
    r":\(\)\s*\{",
    r"\brm\s+-rf\s+/",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bcurl\s+\S+\s*\|\s*(sh|bash)\b",
    r"\bwget\s+.*\|\s*(sh|bash)\b",
    r"\b/shadow\b",
    r"\b/boot\b",
    r"\b/proc/sys\b",
]


class SafetyGuard:
    def evaluate(self, playbook: Playbook, host: Host, settings: Settings):
        reasons: list[str] = []
        if not playbook.steps:
            reasons.append("playbook has no steps")
        for command in playbook.commands():
            if not isinstance(command, str) or not command.strip():
                reasons.append("empty command")
                continue
            for pattern in DENY_PATTERNS:
                if re.search(pattern, command):
                    reasons.append(f"deny pattern matched: {pattern}")
        requires_confirmation = (
            playbook.risk != "auto"
            or playbook.source != "builtin"
            or not settings.global_auto_mode
            or not playbook.auto_run
        )
        return SafetyResult(allowed=not reasons, requires_confirmation=requires_confirmation, reasons=reasons)
