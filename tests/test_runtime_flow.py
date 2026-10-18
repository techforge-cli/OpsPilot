import json
from unittest.mock import Mock

from opspilot.analyzer import Analyzer
from opspilot.executor import PlaybookExecutor
from opspilot.incidents import IncidentManager
from opspilot.models import Host
from opspilot.playbooks import Playbook

ANALYSIS_JSON = {
    "status": "issue",
    "severity": "warning",
    "explanation": "service failed",
    "confidence": 0.9,
    "issue_id": "service_failed",
    "playbook_id": "restart-service",
    "verifier_id": "service-healthy",
    "recommended": False,
}


def _analyzer():
    http = Mock()
    http.post.return_value = Mock(
        status_code=200,
        json=lambda: {"choices": [{"message": {"content": json.dumps(ANALYSIS_JSON)}}]},
    )
    return Analyzer("http://localhost:11434", "m", http), ANALYSIS_JSON


def test_incident_resolver_flow_runs_once():
    analyzer, _analysis_json = _analyzer()
    analysis = analyzer.analyze({"metrics": {}}, [{"id": "restart-service", "description": "restart"}, {"id": "service-healthy", "description": "healthy"}])
    assert analysis.playbook_id == "restart-service"

    playbook = Playbook.from_dict(
        {"id": "restart-service", "risk": "auto", "steps": [{"command": "true"}]},
        source="builtin",
    )
    playbook.verifier = Playbook.from_dict(
        {"id": "service-healthy", "risk": "auto", "steps": [{"command": "true"}]},
        source="builtin",
    )

    manager = IncidentManager()
    incident = manager.create_issue(
        "local", analysis.issue_id, analysis.severity, "service failed", analysis.explanation
    )
    executor = PlaybookExecutor()
    outcome = executor.run(playbook, Host("local", "Local", "127.0.0.1"))

    if outcome.healthy:
        manager.mark_resolved(incident, verifier_output=outcome.stdout)
    else:
        manager.mark_unresolved(incident, "verifier failed")

    assert outcome.healthy is True
    assert incident.status == "resolved"


def test_incident_resolver_flow_failed_execution():
    analyzer, _analysis_json = _analyzer()
    analysis = analyzer.analyze({"metrics": {}}, [{"id": "restart-service", "description": "restart"}, {"id": "service-healthy", "description": "healthy"}])
    assert analysis.playbook_id == "restart-service"

    playbook = Playbook.from_dict(
        {"id": "restart-service", "risk": "auto", "steps": [{"command": "false"}]},
        source="builtin",
    )

    manager = IncidentManager()
    incident = manager.create_issue(
        "local", analysis.issue_id, analysis.severity, "service failed", analysis.explanation
    )
    executor = PlaybookExecutor()
    outcome = executor.run(playbook, Host("local", "Local", "127.0.0.1"))

    if outcome.healthy:
        manager.mark_resolved(incident, verifier_output=outcome.stdout)
    else:
        manager.mark_unresolved(incident, "verifier failed")

    assert outcome.healthy is False
    assert incident.status == "unresolved_recommended"
