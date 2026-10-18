from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum


class IncidentStatus(str, Enum):
    OPEN = "open"
    PENDING_CONFIRMATION = "pending_confirmation"
    BLOCKED = "blocked"
    RESOLVED = "resolved"
    UNRESOLVED_RECOMMENDED = "unresolved_recommended"


@dataclass
class Incident:
    id: str
    host_id: str
    issue_id: str
    severity: str
    status: str
    summary: str
    explanation: str
    recommended: bool = False
    recommendation_playbook_id: str | None = None
    recommendation_verifier_id: str | None = None
    verifier_output: str | None = None
    recommended_explanation: str | None = None


def _incident_id(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if hasattr(value, "id"):
        return _incident_id(value.id)
    return str(value)



class IncidentRepository:
    def __init__(self, conn):
        self.conn = conn

    def save(self, incident: Incident) -> None:
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            """INSERT OR REPLACE INTO incidents (id, host_id, status, issue_id, severity, created_at, updated_at, summary, explanation)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                incident.id,
                incident.host_id,
                incident.status,
                incident.issue_id,
                incident.severity,
                getattr(incident, "created_at", now),
                now,
                incident.summary,
                incident.explanation,
            ),
        )
        self.conn.commit()

    def get(self, incident_id: str):
        row = self.conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        return row

    def list_incidents(self):
        return self.conn.execute("SELECT * FROM incidents ORDER BY created_at DESC").fetchall()

    def record_run(self, incident_id, host_id=None, playbook_id=None, verifier_id=None, status="completed", exit_code=None, stdout=None, stderr=None, detail=None):
        import json as _json
        import uuid as _uuid
        self.conn.execute(
            """INSERT INTO incident_runs (id, incident_id, host_id, playbook_id, verifier_id, status, started_at, finished_at, exit_code, stdout, stderr, detail_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(_uuid.uuid4()),
                incident_id,
                host_id,
                playbook_id,
                verifier_id,
                status,
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
                exit_code,
                stdout,
                stderr,
                _json.dumps(detail or {}),
            ),
        )
        self.conn.commit()


class IncidentManager:
    def __init__(self, conn=None, repository=None, audit=None, *args, **kwargs):
        if conn is None:
            conn = kwargs.get("conn", kwargs.get("connection"))
        if repository is None:
            repository = kwargs.get("incident_repository", kwargs.get("repository"))
        self.conn = conn
        self.audit = audit
        if repository is None and self.conn is not None:
            repository = IncidentRepository(self.conn)
        self.repository = repository
        self.incidents: dict[str, Incident] = {}

    def _get(self, ref):
        incident_id = _incident_id(ref)
        if incident_id is not None and incident_id in self.incidents:
            return self.incidents[incident_id]
        if isinstance(ref, Incident):
            self.incidents[ref.id] = ref
            return ref
        if hasattr(ref, "id"):
            self.incidents[ref.id] = ref  # type: ignore[assignment]
            return ref  # type: ignore[return-value]
        raise KeyError(f"unknown incident: {ref!r}")

    def _persist(self, incident):
        if self.repository is not None:
            try:
                self.repository.save(incident)
            except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error):
                pass

    def create_issue(self, host_id, issue_id, severity, summary, explanation, *, status="open"):
        incident = Incident(
            id=str(uuid.uuid4()),
            host_id=host_id,
            issue_id=issue_id,
            severity=severity,
            status=status,
            summary=summary,
            explanation=explanation,
        )
        self.incidents[incident.id] = incident
        self._persist(incident)
        return incident

    def create(self, *args, **kwargs):
        return self.create_issue(*args, **kwargs)

    def mark_resolved(self, incident=None, *, incident_id=None, verifier_output=None):
        target = self._get(incident if incident is not None else incident_id)
        target.status = "resolved"
        if verifier_output is not None:
            target.verifier_output = str(verifier_output)
        self._persist(target)
        return target

    def mark_unresolved(self, incident, verifier_output=None, *args, **kwargs):
        target = self._get(incident)
        target.status = "unresolved_recommended"
        target.recommended = True
        output = verifier_output
        if output is None and args:
            output = args[0]
        if output is None:
            output = kwargs.get("verifier_output", kwargs.get("output"))
        if output is not None:
            text = str(output)
            target.verifier_output = text
            target.explanation = target.explanation + "\nVerifier output: " + text
        if "playbook_id" in kwargs or "recommended_playbook_id" in kwargs:
            self.recommend(target, **kwargs)
        self._persist(target)
        return target

    def resolve_with_verifier(self, incident, *args, **kwargs):
        target = self._get(incident)
        healthy = kwargs.get("healthy", kwargs.get("ok", kwargs.get("success")))
        verifier_output = kwargs.get("verifier_output", kwargs.get("output"))
        outcome = kwargs.get("outcome", kwargs.get("result", kwargs.get("verifier")))
        for arg in args:
            if isinstance(arg, bool):
                healthy = arg
            elif hasattr(arg, "healthy"):
                healthy = arg.healthy
                if verifier_output is None and hasattr(arg, "stdout"):
                    verifier_output = arg.stdout
            elif isinstance(arg, dict):
                healthy = arg.get("healthy", arg.get("ok", healthy))
                if verifier_output is None:
                    verifier_output = arg.get("verifier_output", arg.get("output"))
            elif isinstance(arg, str) and verifier_output is None:
                verifier_output = arg
        if healthy is None and outcome is not None:
            if hasattr(outcome, "healthy"):
                healthy = outcome.healthy
            elif isinstance(outcome, dict):
                healthy = outcome.get("healthy", outcome.get("ok"))
            elif isinstance(outcome, bool):
                healthy = outcome
        if verifier_output is not None and healthy is None:
            healthy = False
        if healthy is None:
            healthy = False
        if healthy:
            target.status = "resolved"
            if verifier_output is not None:
                target.verifier_output = str(verifier_output)
            self._persist(target)
            return target
        output = verifier_output if verifier_output is not None else "verifier failed"
        text = str(output)
        target.status = "unresolved_recommended"
        target.recommended = True
        target.verifier_output = text
        target.explanation = target.explanation + "\nVerifier output: " + text
        self._persist(target)
        return target

    def recommend(self, incident, *args, **kwargs):
        target = self._get(incident)
        playbook_id = kwargs.get("playbook_id", kwargs.get("recommended_playbook_id"))
        verifier_id = kwargs.get("verifier_id", kwargs.get("recommended_verifier_id"))
        explanation = kwargs.get("explanation", kwargs.get("recommended_explanation", kwargs.get("message")))
        if playbook_id is None and args:
            first = args[0]
            if not isinstance(first, bool) and not hasattr(first, "healthy"):
                playbook_id = first.id if hasattr(first, "id") else first
        if verifier_id is None and len(args) >= 2:
            second = args[1]
            if not isinstance(second, bool):
                verifier_id = second.id if hasattr(second, "id") else second
        if explanation is None and len(args) >= 3 and isinstance(args[2], str):
            explanation = args[2]
        if playbook_id is not None and hasattr(playbook_id, "id"):
            playbook_id = playbook_id.id
        if verifier_id is not None and hasattr(verifier_id, "id"):
            verifier_id = verifier_id.id
        target.status = "unresolved_recommended"
        target.recommended = True
        if playbook_id is not None:
            target.recommendation_playbook_id = playbook_id
        if verifier_id is not None:
            target.recommendation_verifier_id = verifier_id
        if explanation is not None:
            target.recommended_explanation = explanation
            target.explanation = target.explanation + "\nRecommendation: " + str(explanation)
        self._persist(target)
        return target

    def mark_blocked(self, incident=None, *, incident_id=None, reason=None):
        target = self._get(incident if incident is not None else incident_id)
        target.status = "blocked"
        if reason is not None:
            target.explanation = target.explanation + "\nBlocked: " + str(reason)
        self._persist(target)
        return target

    def mark_pending_confirmation(self, incident=None, *, incident_id=None):
        target = self._get(incident if incident is not None else incident_id)
        target.status = "pending_confirmation"
        self._persist(target)
        return target
