from fastapi.testclient import TestClient

from opspilot.config import Settings
from opspilot.web import create_app


def test_root_requires_auth_in_admin_mode():
    settings = Settings(data_dir="/tmp/opspilotweb", ollama_base_url="x", ollama_model="m", admin_password="secret")
    client = TestClient(create_app(settings))
    response = client.get("/")
    assert response.status_code in (401, 302, 403)


def test_root_allows_read_only_mode_with_any_credentials():
    settings = Settings(data_dir="/tmp/opspilotweb_ro", ollama_base_url="x", ollama_model="m")
    client = TestClient(create_app(settings))
    response = client.get("/", auth=("user", "any-password"))
    assert response.status_code == 200


def test_root_allows_valid_admin_password():
    settings = Settings(data_dir="/tmp/opspilotweb_ok", ollama_base_url="x", ollama_model="m", admin_password="secret")
    client = TestClient(create_app(settings))
    response = client.get("/", auth=("admin", "secret"))
    assert response.status_code == 200


def test_root_rejects_bad_admin_password():
    settings = Settings(data_dir="/tmp/opspilotweb_bad", ollama_base_url="x", ollama_model="m", admin_password="secret")
    client = TestClient(create_app(settings))
    response = client.get("/", auth=("admin", "wrong"))
    assert response.status_code == 401


def test_healthz():
    settings = Settings(data_dir="/tmp/opspilotweb_hz", ollama_base_url="x", ollama_model="m")
    client = TestClient(create_app(settings))
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_read_only_mode_requires_auth():
    from fastapi.testclient import TestClient

    from opspilot.config import Settings
    from opspilot.web import create_app

    settings = Settings(admin_password="", data_dir="/tmp/opspilot_test")
    app = create_app(settings)
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 401


def test_login_rate_limited():
    from fastapi.testclient import TestClient

    from opspilot.config import Settings
    from opspilot.web import create_app

    settings = Settings(admin_password="", data_dir="/tmp/opspilot_test")
    app = create_app(settings)
    client = TestClient(app)
    response = None
    for _ in range(6):
        response = client.post("/login", data={"username": "x", "password": "y"})
    assert response is not None
    assert response.status_code == 429
