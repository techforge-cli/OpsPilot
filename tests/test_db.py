import tempfile
from pathlib import Path

from opspilot.db import connect, init_db


def test_init_creates_all_tables():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.sqlite"
        init_db(path)
        conn = connect(path)
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"hosts", "metric_snapshots", "incidents", "audit_events", "playbooks", "playbook_revisions"} <= names


def test_hot_query_indexes_exist(tmp_path):
    from opspilot.db import connect, init_db
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    conn = connect(db_path)
    indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'")}
    assert "idx_metric_snapshots_host_time" in indexes
    assert "idx_incidents_host_issue_status" in indexes
    assert "idx_audit_events_created" in indexes
    assert "idx_incident_runs_incident" in indexes
