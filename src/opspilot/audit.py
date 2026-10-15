import json
import sqlite3
import uuid
from datetime import datetime, timezone


class AuditRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

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

    def list_events(self, limit: int = 100) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
