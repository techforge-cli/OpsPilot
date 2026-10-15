import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS hosts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    address TEXT NOT NULL,
    execution_mode TEXT NOT NULL DEFAULT 'local',
    ssh_user TEXT,
    ssh_port INTEGER NOT NULL DEFAULT 22,
    ssh_key_path TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS metric_snapshots (
    id TEXT PRIMARY KEY,
    host_id TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    interval_seconds INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    FOREIGN KEY (host_id) REFERENCES hosts(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    host_id TEXT NOT NULL,
    status TEXT NOT NULL,
    issue_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    summary TEXT NOT NULL,
    explanation TEXT NOT NULL,
    FOREIGN KEY (host_id) REFERENCES hosts(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    host_id TEXT,
    created_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS playbooks (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    is_builtin INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    current_revision_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS playbook_revisions (
    id TEXT PRIMARY KEY,
    playbook_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    risk TEXT NOT NULL,
    auto_run INTEGER NOT NULL DEFAULT 0,
    verifier_id TEXT,
    content_yaml TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (playbook_id) REFERENCES playbooks(id) ON DELETE CASCADE
);
"""

def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
