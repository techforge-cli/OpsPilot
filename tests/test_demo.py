import pytest
from opspilot.demo import DemoSession
from opspilot.db import connect, init_db
from opspilot.audit import AuditRepository
from opspilot.safety import SafetyGuard
from opspilot.executor import PlaybookExecutor


@pytest.fixture
def demo(tmp_path):
    db_path = tmp_path / "demo.sqlite"
    init_db(db_path)
    conn = connect(db_path)
    audit = AuditRepository(conn, journal_path=None)
    guard = SafetyGuard()
    executor = PlaybookExecutor(settings=None, safety_guard=guard, audit=audit)
    session = DemoSession(conn, audit, guard, executor)
    return session, conn


def test_demo_seeds_hosts(demo):
    session, conn = demo
    session.seed_hosts()
    from opspilot.hosts import HostRepository
    hosts = HostRepository(conn).list_hosts()
    assert len(hosts) == 3
    assert {h.id for h in hosts} == {"web-01", "db-01", "cache-01"}


def test_tier1_auto_runs(demo):
    session, _ = demo
    result = session.trigger_tier(1)
    assert result["status"] == "resolved"
    assert result["tier"] == 1
    assert len(result["logs"]) > 0


def test_tier2_pending_then_confirm(demo):
    session, _ = demo
    result = session.trigger_tier(2)
    assert result["status"] == "pending_confirmation"
    assert result["tier"] == 2
    confirm_result = session.confirm()
    assert confirm_result["status"] == "resolved"
    assert len(confirm_result["logs"]) > 0


def test_tier3_blocked_by_guard(demo):
    session, _ = demo
    result = session.trigger_tier(3)
    assert result["status"] == "blocked"
    assert result["tier"] == 3
    assert len(result["logs"]) > 0


def test_get_status(demo):
    session, _ = demo
    status = session.get_status()
    assert status["stage"] == "idle"
    assert status["tier"] is None
