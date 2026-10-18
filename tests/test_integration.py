from types import SimpleNamespace

from opspilot.collector import ShellRunner
from opspilot.executor import PlaybookExecutor
from opspilot.metrics import collect_native_snapshot
from opspilot.playbooks import Playbook


def test_executor_runs_real_subprocess():
    playbook = Playbook.from_dict(
        {"id": "real", "risk": "auto", "steps": [{"command": "echo hello-opspilot"}]},
        source="builtin",
    )
    executor = PlaybookExecutor(settings=None)
    result = executor.run(playbook, SimpleNamespace(execution_mode="local", ssh_key_path=None, ssh_user="", address="127.0.0.1", ssh_port=22))
    assert result.healthy is True
    assert "hello-opspilot" in result.stdout


def test_collector_runs_real_shell_commands():
    runner = ShellRunner()
    returncode, stdout, _, _ = runner.run("echo test-output && exit 0")
    assert returncode == 0
    assert "test-output" in stdout


def test_collect_native_snapshot_real_commands():
    runner = ShellRunner()
    snapshot = collect_native_snapshot(runner, host_id="local", interval_seconds=30)
    assert snapshot["host_id"] == "local"
    assert "metrics" in snapshot
    assert "load" in snapshot["metrics"]
    assert "memory" in snapshot["metrics"]
    assert "disk" in snapshot["metrics"]


def test_executor_stops_on_nonzero_exit():
    playbook = Playbook.from_dict(
        {"id": "failing", "risk": "auto", "steps": [{"command": "exit 1"}]},
        source="builtin",
    )
    executor = PlaybookExecutor(settings=None)
    result = executor.run(playbook, SimpleNamespace(execution_mode="local", ssh_key_path=None, ssh_user="", address="127.0.0.1", ssh_port=22))
    assert result.healthy is False


def test_executor_respects_timeout():
    playbook = Playbook.from_dict(
        {"id": "slow", "risk": "auto", "steps": [{"command": "sleep 10", "timeout_seconds": 1}]},
        source="builtin",
    )
    executor = PlaybookExecutor(settings=None)
    result = executor.run(playbook, SimpleNamespace(execution_mode="local", ssh_key_path=None, ssh_user="", address="127.0.0.1", ssh_port=22))
    assert result.healthy is False
    assert "timed out" in result.stderr
