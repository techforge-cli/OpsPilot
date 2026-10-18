import sqlite3
from datetime import UTC, datetime, timedelta
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
    recommended INTEGER NOT NULL DEFAULT 0,
    recommendation_playbook_id TEXT,
    recommendation_verifier_id TEXT,
    verifier_output TEXT,
    recommended_explanation TEXT,
    playbook_id TEXT,
    verifier_id TEXT,
    FOREIGN KEY (host_id) REFERENCES hosts(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS incident_runs (
    id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    host_id TEXT,
    playbook_id TEXT,
    verifier_id TEXT,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    exit_code INTEGER,
    stdout TEXT,
    stderr TEXT,
    detail_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (incident_id) REFERENCES incidents(id) ON DELETE CASCADE
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
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metric_snapshots_host_time ON metric_snapshots (host_id, collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_incidents_host_issue_status ON incidents (host_id, issue_id, status);
CREATE INDEX IF NOT EXISTS idx_audit_events_created ON audit_events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_incident_runs_incident ON incident_runs (incident_id);
"""

COLUMNS_TO_ADD = {
    "incidents": [
        ("recommended", "INTEGER NOT NULL DEFAULT 0"),
        ("recommendation_playbook_id", "TEXT"),
        ("recommendation_verifier_id", "TEXT"),
        ("verifier_output", "TEXT"),
        ("recommended_explanation", "TEXT"),
        ("playbook_id", "TEXT"),
        ("verifier_id", "TEXT"),
    ],
}


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
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
        _migrate(conn)
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {row["name"]: row for row in conn.execute("PRAGMA table_info(incidents)").fetchall()}
    for table, add_cols in COLUMNS_TO_ADD.items():
        for col_name, col_def in add_cols:
            if col_name not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                cols[col_name] = {"name": col_name}
    conn.commit()


def prune_snapshots(conn: sqlite3.Connection, days: int = 7) -> int:
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    cur = conn.execute("SELECT COUNT(*) FROM metric_snapshots WHERE collected_at < ?", (cutoff,))
    total = cur.fetchone()[0] if cur else 0
    if total > 0:
        conn.execute("DELETE FROM metric_snapshots WHERE collected_at < ?", (cutoff,))
    return total


def latest_snapshot(conn: sqlite3.Connection, host_id: str) -> dict:
    import json

    row = conn.execute(
        "SELECT snapshot_json FROM metric_snapshots WHERE host_id = ? ORDER BY collected_at DESC LIMIT 1",
        (host_id,),
    ).fetchone()
    if row is None:
        return {}
    try:
        return json.loads(row["snapshot_json"] or "{}")
    except (ValueError, TypeError):
        return {}