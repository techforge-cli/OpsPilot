from opspilot.config import Settings
from opspilot.models import Host
from opspilot.playbooks import Playbook
from opspilot.safety import SafetyGuard


def test_blocks_fork_bomb():
    playbook = Playbook.from_dict({"id": "bad", "risk": "confirm", "steps": [{"command": ":(){ :|:& };:"}]}, source="custom")
    guard = SafetyGuard()
    settings = Settings(data_dir="/tmp", ollama_base_url="x", ollama_model="m")
    host = Host("local", "Local", "127.0.0.1")
    result = guard.evaluate(playbook, host, settings)
    assert result.allowed is False


def test_requires_confirmation_for_custom():
    playbook = Playbook.from_dict({"id": "x", "risk": "auto", "auto_run": True, "steps": [{"command": "uptime"}]}, source="custom")
    guard = SafetyGuard()
    settings = Settings(data_dir="/tmp", ollama_base_url="x", ollama_model="m", global_auto_mode=True)
    host = Host("local", "Local", "127.0.0.1")
    result = guard.evaluate(playbook, host, settings)
    assert result.requires_confirmation is True
    assert result.allowed is True
