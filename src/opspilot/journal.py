import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from pathlib import Path


class AuditJournal:
    def __init__(self, path, secret=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.secret = secret.encode() if secret else None
        self._last_hash = self._load_last_hash()

    def _load_last_hash(self) -> str:
        if not self.path.exists():
            return "0" * 64
        try:
            lines = self.path.read_text().strip().splitlines()
            if not lines:
                return "0" * 64
            last = json.loads(lines[-1])
            return last.get("prev_hash", "0" * 64)
        except (json.JSONDecodeError, OSError):
            return "0" * 64

    def append(self, event: dict) -> None:
        payload = event | {"written_at": datetime.now(UTC).isoformat()}
        payload["prev_hash"] = self._last_hash
        line = json.dumps(payload, sort_keys=True, default=str)
        if self.secret:
            payload["hmac"] = hmac.new(self.secret, line.encode(), hashlib.sha256).hexdigest()
            line = json.dumps(payload, sort_keys=True, default=str)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._last_hash = hashlib.sha256(line.encode()).hexdigest()

    def verify(self) -> list[dict]:
        issues = []
        if not self.path.exists():
            return issues
        prev_hash = "0" * 64
        lines = self.path.read_text().strip().splitlines()
        for i, line in enumerate(lines):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                issues.append({"line": i + 1, "reason": "invalid JSON"})
                continue
            if event.get("prev_hash") != prev_hash:
                issues.append({"line": i + 1, "reason": "hash chain broken"})
            if self.secret:
                stored_hmac = event.pop("hmac", None)
                canonical = json.dumps(event, sort_keys=True, default=str)
                expected = hmac.new(self.secret, canonical.encode(), hashlib.sha256).hexdigest()
                if not hmac.compare_digest(stored_hmac or "", expected):
                    issues.append({"line": i + 1, "reason": "HMAC mismatch"})
            prev_hash = hashlib.sha256(line.encode()).hexdigest()
        return issues
