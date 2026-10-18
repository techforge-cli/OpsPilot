import uuid
from datetime import UTC, datetime, timedelta

from opspilot.db import connect, init_db, prune_snapshots
from opspilot.hosts import HostRepository, default_local_host
from opspilot.incidents import IncidentManager


def make_repo(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    conn = connect(db_path)
    HostRepository(conn).save(default_local_host())
    return conn, IncidentManager(conn=conn)


def test_saving_incident_again_keeps_its_runs(tmp_path):
    _conn, manager = make_repo(tmp_path)
    repo = manager.repository
    assert repo is not None
    incident = manager.create_issue("local", "sample_issue", "warning", "s", "e", playbook_id="sample-noop")

    repo.record_run(incident.id, host_id="local", playbook_id="sample-noop", status="completed", exit_code=0)
    manager.mark_resolved(incident)

    runs = repo.list_runs(incident.id)
    assert len(runs) == 1
    stored = repo.get(incident.id)
    assert stored is not None
    assert stored.status == "resolved"


def test_find_active_ignores_closed_incidents(tmp_path):
    _conn, manager = make_repo(tmp_path)
    repo = manager.repository
    assert repo is not None
    incident = manager.create_issue("local", "sample_issue", "warning", "s", "e")
    assert repo.find_active("local", "sample_issue") is not None

    manager.mark_resolved(incident)
    assert repo.find_active("local", "sample_issue") is None


def test_prune_snapshots_drops_only_old_rows(tmp_path):
    conn, _manager = make_repo(tmp_path)
    now = datetime.now(UTC)
    rows = [
        (str(uuid.uuid4()), "local", now.isoformat(), 30, "{}"),
        (str(uuid.uuid4()), "local", (now - timedelta(days=30)).isoformat(), 30, "{}"),
    ]
    conn.executemany(
        "INSERT INTO metric_snapshots (id, host_id, collected_at, interval_seconds, snapshot_json) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()

    removed = prune_snapshots(conn, days=7)

    assert removed == 1
    remaining = conn.execute("SELECT COUNT(*) FROM metric_snapshots").fetchone()[0]
    assert remaining == 1
