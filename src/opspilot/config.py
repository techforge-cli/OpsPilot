import secrets
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPSPILOT_", case_sensitive=False)

    admin_password: str = ""
    bind_host: str = "127.0.0.1"
    bind_port: int = 8443
    data_dir: str = "/var/lib/opspilot"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b"
    interval_seconds: int = 30
    global_auto_mode: bool = False
    demo_mode: bool = False
    ssh_key_path: str = "/etc/opspilot/operator.key"
    log_level: str = "INFO"
    session_secret: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    ollama_timeout: int = 60
    snapshot_retention_days: int = 7

    @property
    def read_only_web_mode(self) -> bool:
        return self.admin_password == ""

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)


def settings_from_env() -> Settings:
    return Settings()


settings = settings_from_env()
