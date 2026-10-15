from opspilot.config import Settings

def test_settings_require_password_for_web():
    settings = Settings(  # type: ignore[call-arg]
        data_dir="/tmp/opspilot",
        ollama_base_url="http://localhost:11434",
        ollama_model="qwen2.5:7b",
    )
    assert settings.read_only_web_mode is True

def test_admin_password_enables_admin_mode():
    settings = Settings(
        data_dir="/tmp/opspilot",
        ollama_base_url="http://localhost:11434",
        ollama_model="qwen2.5:7b",
        admin_password="correct horse",
    )
    assert settings.read_only_web_mode is False
