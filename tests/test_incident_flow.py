from opspilot.incidents import IncidentManager


def test_unresolved_incident_becomes_recommendation():
    manager = IncidentManager()
    incident = manager.create_issue("host", "service_down", "warning", "service failed", "engineering details")
    result = manager.mark_unresolved(incident.id, "verifier failed")
    assert result.status == "unresolved_recommended"
    assert result.recommended is True
