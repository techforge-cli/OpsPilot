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
