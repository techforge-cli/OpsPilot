import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from opspilot.journal import AuditJournal


def _resolve_journal(value):
    if value is None:
        return None
    if isinstance(value, AuditJournal):
        return value
    if hasattr(value, "append") and callable(value.append):
        return value
    return AuditJournal(Path(value))


class AuditRepository:
    def __init__(self, conn: sqlite3.Connection, *args, **kwargs):
        self.conn = conn
        candidate = kwargs.get(
            "journal",
            kwargs.get(
                "journal_path",
                kwargs.get(
                    "audit_journal",
                    kwargs.get("path", kwargs.get("journal_file")),
                ),
            ),
        )
        if candidate is None and args:
            candidate = args[0]
        self.journal = _resolve_journal(candidate)

    def record(
        self,
        event_type: str,
        host_id: str | None = None,
        message: str = "",
        detail: dict | None = None,
    ) -> None:
        if message is None:
            message = ""
        if detail is None:
            detail = {}
        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO audit_events (id, host_id, created_at, event_type, message, detail_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (event_id, host_id, now, event_type, message, json.dumps(detail)),
        )
        self.conn.commit()
        if self.journal is not None:
            self.journal.append(
                {
                    "id": event_id,
                    "host_id": host_id,
                    "created_at": now,
                    "event_type": event_type,
                    "message": message,
                    "detail": detail,
                }
            )

    def list_events(self, limit: int = 100) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
