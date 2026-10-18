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


def test_shell_runner_timeout_returns_error_not_exception(monkeypatch):
    import subprocess

    from opspilot.collector import ShellRunner

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="sleep 100", timeout=0.001)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    runner = ShellRunner()
    result = runner.run("sleep 100", timeout=1)
    assert result[0] == 124
    assert "timed out" in result[2]
