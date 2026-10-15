from unittest.mock import Mock

from opspilot.executor import PlaybookExecutor
from opspilot.playbooks import Playbook


def test_executor_runs_step_and_captures_output(monkeypatch):
    playbook = Playbook.from_dict({"id": "x", "risk": "auto", "steps": [{"command": "echo hi"}]}, source="builtin")
    subprocess = Mock()
    subprocess.run.return_value = Mock(returncode=0, stdout="hi\n", stderr="")
    monkeypatch.setattr("opspilot.executor.subprocess.run", subprocess.run)
    executor = PlaybookExecutor(settings=None)
    result = executor.run(playbook, Mock(execution_mode="local"))
    assert result.healthy is True
    assert "hi" in result.stdout
