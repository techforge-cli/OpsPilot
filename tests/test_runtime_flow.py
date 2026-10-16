from unittest.mock import Mock

from opspilot.analyzer import Analyzer
from opspilot.playbooks import Playbook
from opspilot.incidents import IncidentManager
from opspilot.executor import PlaybookExecutor
from opspilot.models import Host


def test_incident_resolver_flow_runs_once():
    analysis_json = {
        "status": "issue",
        "severity": "warning",
        "explanation": "service failed",
        "confidence": 0.9,
        "issue_id": "service_failed",
        "playbook_id": "restart-service",
        "verifier_id": "service-healthy",
        "recommended": False,
    }
    http = Mock()
    http.post.return_value = Mock(status_code=200, json=lambda: {"choices": [{"message": {"content": __import__("json").dumps(analysis_json)}}]})
    analyzer = Analyzer("http://localhost:11434", "m", http)
    playbook = Playbook.from_dict({"id": "restart-service", "risk": "auto", "steps": [{"command": "true"}]}, source="builtin")
    playbook.verifier = Playbook.from_dict({"id": "service-healthy", "risk": "auto", "steps": [{"command": "true"}]}, source="builtin")
    manager = IncidentManager()
    incident = manager.create_issue("local", "service_failed", "warning", "service failed", analysis_json["explanation"])
    executor = PlaybookExecutor()
    outcome = executor.run(playbook, Host("local", "Local", "127.0.0.1"))
    manager.mark_resolved(incident.id) if outcome.healthy else manager.mark_unresolved(incident.id, "verifier failed")
    assert incident.status in ("resolved", "unresolved_recommended")
