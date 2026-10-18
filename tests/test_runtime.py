from opspilot.audit import AuditRepository
from opspilot.config import Settings
from opspilot.db import connect, init_db
from opspilot.runtime import build_runtime


def test_build_runtime_wires_real_components(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    conn = connect(db_path)
    settings = Settings(data_dir=str(tmp_path), ollama_timeout=17)

    runtime = build_runtime(settings, conn, AuditRepository(conn, journal_path=None))

    assert set(runtime) >= {"analyzer", "safety_guard", "executor", "incident_manager", "playbooks"}
    assert runtime["analyzer"] is not None
    assert runtime["analyzer"].client is not None
    assert runtime["analyzer"].timeout == 17
    assert runtime["executor"] is not None
    assert runtime["incident_manager"] is not None
    assert runtime["incident_manager"].repository is not None
    assert runtime["playbooks"], "builtin catalog should load"


def test_scheduler_uses_runtime_components(tmp_path):
    from opspilot.scheduler import Scheduler

    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    conn = connect(db_path)
    settings = Settings(data_dir=str(tmp_path))
    runtime = build_runtime(settings, conn)

    scheduler = Scheduler(
        settings,
        conn,
        analyzer=runtime["analyzer"],
        safety_guard=runtime["safety_guard"],
        executor=runtime["executor"],
        incident_manager=runtime["incident_manager"],
        playbooks=runtime["playbooks"],
        audit=runtime["incident_manager"].audit,
    )

    assert scheduler.analyzer is runtime["analyzer"]
    assert scheduler.executor is runtime["executor"]
    assert scheduler.incident_manager is runtime["incident_manager"]
    assert scheduler.safety_guard is runtime["safety_guard"]
