from unittest.mock import Mock

from opspilot.analyzer import Analyzer


def test_analyzer_parses_strict_json():
    http = Mock()
    http.post.return_value = Mock(
        status_code=200,
        json=lambda: {"choices": [{"message": {"content": '{"status":"ok","severity":"info","explanation":"usable","confidence":0.9,"issue_id":"","playbook_id":null,"verifier_id":null,"recommended":false}'}}]},
    )
    analyzer = Analyzer("http://localhost:11434", "m", http)
    result = analyzer.analyze({"metrics": {}}, [])
    assert result.status == "ok"
    assert result.playbook_id is None
