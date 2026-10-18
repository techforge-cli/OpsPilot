import types

import pytest
from fastapi.testclient import TestClient

from opspilot import web as web_module
from opspilot.analyzer import Analysis
from opspilot.config import Settings
from opspilot.executor import PlaybookExecutor
from opspilot.scheduler import Scheduler


class StubExecutor(PlaybookExecutor):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.commands = []

    def _run_one(self, command, timeout, host):
        self.commands.append(command)
        return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")


class OkAnalyzer:
    client = None

    def analyze(self, snapshot, playbooks, **kwargs):
        return Analysis(status="ok")

    def analyze_recommendation(self, snapshot, playbooks, **kwargs):
        return Analysis(status="ok")


@pytest.fixture
def harness(tmp_path, monkeypatch):
    state = {}
    real_build = web_module.build_runtime

    def fake_build(settings, conn, audit_repo=None):
        runtime = real_build(settings, conn, audit_repo)
        runtime["executor"] = StubExecutor(settings=settings, safety_guard=runtime["safety_guard"], audit=audit_repo)
        runtime["analyzer"] = OkAnalyzer()
        state["runtime"] = runtime
        return runtime

    def fake_start_background(settings=None, repo=None, **kwargs):
        scheduler = Scheduler(settings=settings, repo=repo, **kwargs)
        state["scheduler"] = scheduler
        return scheduler

    monkeypatch.setattr(web_module, "build_runtime", fake_build)
    monkeypatch.setattr(web_module.Scheduler, "start_background", staticmethod(fake_start_background))
    return state


def make_client(tmp_path, harness, *, read_only=False, **overrides):
    settings = Settings(
        data_dir=str(tmp_path),
        ollama_base_url="x",
        ollama_model="m",
        global_auto_mode=True,
        admin_password="" if read_only else "secret",
        **overrides,
    )
    app = web_module.create_app(settings)
    harness["app"] = app
    return TestClient(app)


AUTH = ("admin", "secret")


def make_pending(client):
    manager = client.app.state.runtime["incident_manager"]
    incident = manager.create_issue(
        "local",
        "sample_issue",
        "warning",
        "summary",
        "explanation",
        status="pending_confirmation",
        playbook_id="sample-noop",
        verifier_id="sample-verify",
    )
    return incident


def test_confirm_executes_and_resolves(tmp_path, harness):
    client = make_client(tmp_path, harness)
    incident = make_pending(client)

    response = client.post(f"/incidents/{incident.id}/confirm", auth=AUTH, follow_redirects=False)

    assert response.status_code == 303
    stored = harness["app"].state.incident_repo.get(incident.id)
    assert stored is not None
    assert stored.status == "resolved"
    assert harness["runtime"]["executor"].commands


def test_confirm_is_single_flight(tmp_path, harness):
    client = make_client(tmp_path, harness)
    incident = make_pending(client)

    first = client.post(f"/incidents/{incident.id}/confirm", auth=AUTH, follow_redirects=False)
    second = client.post(f"/incidents/{incident.id}/confirm", auth=AUTH, follow_redirects=False)

    assert first.status_code == 303
    assert second.status_code == 409


def test_confirm_refused_in_read_only_mode(tmp_path, harness):
    client = make_client(tmp_path, harness, read_only=True)
    incident = make_pending(client)

    response = client.post(f"/incidents/{incident.id}/confirm", follow_redirects=False)

    assert response.status_code == 403
    stored = harness["app"].state.incident_repo.get(incident.id)
    assert stored is not None
    assert stored.status == "pending_confirmation"


def test_dismiss_marks_incident(tmp_path, harness):
    client = make_client(tmp_path, harness)
    incident = make_pending(client)

    response = client.post(f"/incidents/{incident.id}/dismiss", auth=AUTH, follow_redirects=False)

    assert response.status_code == 303
    stored = harness["app"].state.incident_repo.get(incident.id)
    assert stored is not None
    assert stored.status == "dismissed"


def test_read_only_mode_requires_no_password_but_blocks_writes(tmp_path, harness):
    client = make_client(tmp_path, harness, read_only=True)
    assert client.get("/").status_code == 200
    assert client.get("/incidents").status_code == 200
