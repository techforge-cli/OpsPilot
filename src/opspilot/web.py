import hmac
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from opspilot.audit import AuditRepository
from opspilot.config import Settings
from opspilot.db import connect, init_db
from opspilot.hosts import HostRepository, default_local_host
from opspilot.scheduler import Scheduler


def create_app(settings: Settings):
    data_path = Path(settings.data_dir)
    db_path = data_path / "opspilot.sqlite"
    init_db(db_path)
    templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
    app = FastAPI(title="OpsPilot")
    app.state.settings = settings
    app.state.conn = connect(db_path)
    app.state.host_repo = HostRepository(app.state.conn)
    app.state.audit_repo = AuditRepository(app.state.conn)

    try:
        if not app.state.host_repo.list_hosts():
            app.state.host_repo.save(default_local_host())
    except Exception:
        pass

    security = HTTPBasic(auto_error=False)

    def require_admin(credentials: HTTPBasicCredentials | None = Depends(security)):
        if not settings.admin_password:
            return None
        if credentials is None or not hmac.compare_digest(
            credentials.password.encode("utf-8"), settings.admin_password.encode("utf-8")
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": 'Basic realm="OpsPilot"'},
            )
        return credentials.username

    try:
        app.state.scheduler = Scheduler.start_background(settings, app.state.conn)
    except Exception:
        app.state.scheduler = None

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request, _admin=Depends(require_admin)):
        return templates.TemplateResponse(
            request,
            "index.html",
            {"request": request, "settings": settings},
        )

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, _admin=Depends(require_admin)):
        html = (
            "<!DOCTYPE html><html><head><title>OpsPilot Settings</title></head><body>"
            "<h1>Settings</h1>"
            f"<p>Bind host: {settings.bind_host}</p>"
            f"<p>Bind port: {settings.bind_port}</p>"
            f"<p>Ollama base URL: {settings.ollama_base_url}</p>"
            f"<p>Ollama model: {settings.ollama_model}</p>"
            f"<p>Collection interval seconds: {settings.interval_seconds}</p>"
            f"<p>Global auto mode: {settings.global_auto_mode}</p>"
            f"<p>Read-only web mode: {settings.read_only_web_mode}</p>"
            "</body></html>"
        )
        return HTMLResponse(html)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app