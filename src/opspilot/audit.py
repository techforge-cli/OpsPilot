import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any


_MISSING = object()


class AuditRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def record(
        self,
        event_type: str,
        *args: Any,
        host_id: Any = _MISSING,
        message: Any = _MISSING,
        detail: Any = _MISSING,
        **kwargs: Any,
    ) -> None:
        # Allow hosts second alias from kwargs
        if "host_id" in kwargs:
            host_id = kwargs.pop("host_id")
        if "message" in kwargs:
            message = kwargs.pop("message")
        if "detail" in kwargs:
            detail = kwargs.pop("detail")
        # leftover kwargs (e.g. detail_json) ignore

        pos = list(args)
        # trailing dict -> detail
        if pos and isinstance(pos[-1], dict):
            if detail is _MISSING:
                detail = pos.pop()
            else:
                pos.pop()

        if host_id is _MISSING:
            host_id = None
        if message is _MISSING:
            message = ""
        if detail is _MISSING:
            detail = None

        remaining = pos
        if len(remaining) == 1:
            value = remaining[0]
            if isinstance(value, str) and self._host_exists(value):
                host_id = value
            else:
                message = value
        elif len(remaining) == 2:
            first, second = remaining
            first_host = isinstance(first, str) and self._host_exists(first)
            second_host = isinstance(second, str) and self._host_exists(second)
            if first_host and not second_host:
                host_id, message = first, second
            elif second_host and not first_host:
                message, host_id = first, second
            else:
                # fallback to plan snippet order: message, host_id
                message, host_id = first, second

        if host_id is _MISSING:
            host_id = None
        if message is _MISSING:
            message = ""
        if detail is None:
            detail = {}

        if not isinstance(detail, dict):
            detail = {} if detail is None else {"value": detail}

        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO audit_events (id, host_id, created_at, event_type, message, detail_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (event_id, host_id, now, event_type, message, json.dumps(detail)),
        )
        self.conn.commit()

    def _host_exists(self, host_id: str) -> bool:
        try:
            row = self.conn.execute("SELECT 1 FROM hosts WHERE id = ?", (host_id,)).fetchone()
            return row is not None
        except Exception:
            return False

    def list_events(self, limit: int = 100) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
