from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def row_to_dict(row):
    return dict(row) if row is not None else {}


@dataclass(frozen=True)
class Host:
    id: str
    name: str
    address: str
    execution_mode: str = "local"
    ssh_user: str | None = None
    ssh_port: int = 22
    ssh_key_path: str | None = None
    tags: tuple[str, ...] = ()
    is_active: bool = True

    def tags_json(self) -> str:
        return json.dumps(list(self.tags))

    @classmethod
    def from_row(cls, row):
        tags = tuple(json.loads(row["tags_json"] or "[]"))
        return cls(
            id=row["id"],
            name=row["name"],
            address=row["address"],
            execution_mode=row["execution_mode"],
            ssh_user=row["ssh_user"],
            ssh_port=row["ssh_port"],
            ssh_key_path=row["ssh_key_path"],
            tags=tags,
            is_active=bool(row["is_active"]),
        )


@dataclass(frozen=True)
class SnapshotRecord:
    id: str
    host_id: str
    collected_at: datetime | str
    interval_seconds: int
    snapshot: dict[str, Any] = field(default_factory=dict)
    snapshot_json: str = "{}"

    def __post_init__(self):
        if not self.snapshot and self.snapshot_json and self.snapshot_json != "{}":
            object.__setattr__(self, "snapshot", json.loads(self.snapshot_json or "{}"))

    @classmethod
    def from_row(cls, row):
        return cls(
            id=row["id"],
            host_id=row["host_id"],
            collected_at=row["collected_at"],
            interval_seconds=row["interval_seconds"],
            snapshot=json.loads(row["snapshot_json"] or "{}"),
            snapshot_json=row["snapshot_json"] or "{}",
        )


@dataclass(frozen=True)
class IncidentRecord:
    id: str
    host_id: str
    status: str
    issue_id: str
    severity: str
    created_at: str
    updated_at: str
    summary: str
    explanation: str

    @classmethod
    def from_row(cls, row):
        return cls(
            id=row["id"],
            host_id=row["host_id"],
            status=row["status"],
            issue_id=row["issue_id"],
            severity=row["severity"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            summary=row["summary"],
            explanation=row["explanation"],
        )


@dataclass(frozen=True)
class AuditEventRecord:
    id: str
    host_id: str | None = None
    created_at: str = ""
    event_type: str = ""
    message: str = ""
    detail_json: str = "{}"
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.detail and self.detail_json and self.detail_json not in ("", "{}"):
            object.__setattr__(self, "detail", json.loads(self.detail_json or "{}"))
        if not self.detail_json or self.detail_json == "{}":
            object.__setattr__(self, "detail_json", json.dumps(self.detail or {}))

    @classmethod
    def from_row(cls, row):
        return cls(
            id=row["id"],
            host_id=row["host_id"],
            created_at=row["created_at"],
            event_type=row["event_type"],
            message=row["message"],
            detail_json=row["detail_json"] or "{}",
            detail=json.loads(row["detail_json"] or "{}"),
        )


@dataclass(frozen=True)
class PlaybookRevisionRecord:
    id: str
    playbook_id: str
    revision: int
    risk: str
    auto_run: bool = False
    verifier_id: str | None = None
    content_yaml: str = ""
    created_at: str = ""

    @classmethod
    def from_row(cls, row):
        return cls(
            id=row["id"],
            playbook_id=row["playbook_id"],
            revision=row["revision"],
            risk=row["risk"],
            auto_run=bool(row["auto_run"]),
            verifier_id=row["verifier_id"],
            content_yaml=row["content_yaml"],
            created_at=row["created_at"],
        )


# Interface aliases required by task contract
HostRecord = Host
MetricSnapshotRecord = SnapshotRecord
IncidentRecord = IncidentRecord
AuditEventRecord = AuditEventRecord
PlaybookRevisionRecord = PlaybookRevisionRecord
