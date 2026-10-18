from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

try:
    from importlib.resources import files as resource_files
except (ImportError, OSError):  # pragma: no cover
    resource_files = None


class Playbook:
    def __init__(
        self,
        id: str,
        title: str,
        description: str,
        risk: str,
        auto_run: bool,
        source: str,
        verifier_id: str | None,
        steps: list[dict[str, Any]],
        issue_ids: list[str],
        builtin: bool = False,
        verifier: Playbook | None = None,
        applies_to: Any = None,
        verifier_document: bool = False,
    ):
        self.id = id
        self.title = title
        self.description = description
        self.risk = risk
        self.auto_run = auto_run
        self.source = source
        self.verifier_id = verifier_id
        self.steps = steps
        self.issue_ids = issue_ids
        self.is_builtin = builtin
        self.verifier = verifier
        self.applies_to = applies_to
        self.verifier_document = verifier_document

    @classmethod
    def from_dict(cls, data: dict, source: str):
        applies_to = data.get("applies_to", {}) or {}
        if isinstance(applies_to, dict):
            issue_ids = applies_to.get("issue_ids", []) or []
        elif isinstance(applies_to, list):
            issue_ids = applies_to
        else:
            issue_ids = []
        return cls(
            id=data["id"],
            title=data.get("title", data["id"]),
            description=data.get("description", ""),
            risk=data.get("risk", "confirm"),
            auto_run=bool(data.get("auto_run", False)),
            source=source,
            verifier_id=data.get("verifier_id"),
            steps=data.get("steps", []) or [],
            issue_ids=list(issue_ids),
            builtin=source == "builtin",
            applies_to=applies_to,
            verifier_document=bool(data.get("verifier", False)),
        )

    def commands(self) -> list[str]:
        return [str(step.get("command", "") if isinstance(step, dict) else step) for step in self.steps]

    @property
    def is_verifier(self) -> bool:
        return bool(self.verifier_document)


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _candidate_builtin_dirs(path: str | Path | None = None):
    if path is not None:
        yield Path(path)
        return
    seen: set[str] = set()
    candidates = [
        _REPO_ROOT / "opspilot" / "playbooks" / "builtin",
        Path.cwd() / "opspilot" / "playbooks" / "builtin",
        Path(__file__).resolve().parent / "playbooks" / "builtin",
    ]
    if resource_files is not None:
        try:
            candidates.append(Path(str(resource_files("opspilot") / "playbooks" / "builtin")))
        except (OSError, RuntimeError, ValueError, TypeError):
            _ = None
    for candidate in candidates:
        try:
            key = str(candidate.resolve())
        except OSError:
            key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        yield candidate


def load_builtin_playbooks(path: str | Path | None = None) -> list[Playbook]:
    playbooks: list[Playbook] = []
    seen_files: set[str] = set()
    for directory in _candidate_builtin_dirs(path):
        directory = Path(directory)
        if directory.is_file():
            candidates = [directory]
        elif directory.is_dir():
            candidates = sorted(
                list(directory.glob("*.yaml")) + list(directory.glob("*.yml"))
            )
        else:
            continue
        for file_path in candidates:
            try:
                key = str(file_path.resolve())
            except OSError:
                key = str(file_path)
            if key in seen_files:
                continue
            seen_files.add(key)
            with file_path.open("r", encoding="utf-8") as handle:
                document = yaml.safe_load(handle)
            if not isinstance(document, dict):
                continue
            playbooks.append(Playbook.from_dict(document, source="builtin"))
    return playbooks


class PlaybookRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def save(self, playbook: Playbook) -> None:
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            """INSERT OR REPLACE INTO playbooks (id, kind, title, is_builtin, source, current_revision_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                playbook.id,
                "verifier" if playbook.is_verifier else "playbook",
                playbook.title,
                int(playbook.is_builtin),
                playbook.source,
                None,
                now,
                now,
            ),
        )
        self.conn.commit()

    def list_playbooks(self) -> list[Playbook]:
        return load_builtin_playbooks()

    def get(self, playbook_id: str) -> Playbook | None:
        for playbook in load_builtin_playbooks():
            if playbook.id == playbook_id:
                return playbook
        return None
