import hmac
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from opspilot.audit import AuditRepository
from opspilot.config import Settings
from opspilot.db import connect, init_db
from opspilot.hosts import HostRepository, default_local_host
from opspilot.scheduler import Scheduler


def _session_token(settings: Settings) -> str:
    return hmac.new(settings.session_secret.encode("utf-8"), b"opspilot-admin", digestmod="sha256").hexdigest()


def create_app(settings: Settings):
    data_path = Path(settings.data_dir)
    db_path = data_path / "opspilot.sqlite"
    init_db(db_path)
    templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
    app = FastAPI(title="OpsPilot")
    app.state.settings = settings
    app.state.conn = connect(db_path)
    app.state.host_repo = HostRepository(app.state.conn)
    app.state.audit_repo = AuditRepository(app.state.conn, journal_path=data_path / "audit" / "audit.jsonl")

    try:
        if not app.state.host_repo.list_hosts():
            app.state.host_repo.save(default_local_host())
    except (OSError, RuntimeError, ValueError, TypeError):
        pass

    security = HTTPBasic(auto_error=False)

    def require_admin(request: Request, credentials: HTTPBasicCredentials | None = Depends(security)):  # noqa: B008
        if not settings.admin_password:
            return None
        cookie = request.cookies.get("opspilot_session")
        if cookie and hmac.compare_digest(cookie, _session_token(settings)):
            return "admin"
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
    except (OSError, RuntimeError, ValueError, TypeError):
        app.state.scheduler = None

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        return templates.TemplateResponse(request, "login.html", {"request": request, "settings": settings})

    @app.post("/login")
    async def login(request: Request):
        username = None
        password = None
        try:
            form = await request.form()
            username = form.get("username")
            password = form.get("password")
        except (OSError, RuntimeError, ValueError, TypeError):
            username = None
            password = None
        if username is None and password is None:
            try:
                body = await request.json()
                username = body.get("username")
                password = body.get("password")
            except (OSError, RuntimeError, ValueError, TypeError):
                pass
        if not settings.admin_password:
            return JSONResponse({"status": "read-only"})
        if not (isinstance(password, str) and hmac.compare_digest(password.encode("utf-8"), settings.admin_password.encode("utf-8"))):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            "opspilot_session",
            _session_token(settings),
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            path="/",
        )
        return response

    @app.post("/logout")
    def logout():
        response = RedirectResponse(url="/", status_code=302)
        response.delete_cookie("opspilot_session", path="/")
        return response

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request, _admin=Depends(require_admin)):  # noqa: B008
        return templates.TemplateResponse(request, "index.html", {"request": request, "settings": settings})

    @app.get("/hosts", response_class=HTMLResponse)
    def hosts_page(request: Request, _admin=Depends(require_admin)):  # noqa: B008
        hosts = []
        try:
            hosts = app.state.host_repo.list_hosts()
        except (OSError, RuntimeError, ValueError, TypeError):
            hosts = []
        return templates.TemplateResponse(request, "hosts.html", {"request": request, "settings": settings, "hosts": hosts})

    @app.get("/incidents", response_class=HTMLResponse)
    def incidents_page(request: Request, _admin=Depends(require_admin)):  # noqa: B008
        events = []
        try:
            events = app.state.audit_repo.list_events(limit=50)
        except (OSError, RuntimeError, ValueError, TypeError):
            events = []
        return templates.TemplateResponse(request, "incidents.html", {"request": request, "settings": settings, "events": events})

    @app.get("/playbooks", response_class=HTMLResponse)
    def playbooks_page(request: Request, _admin=Depends(require_admin)):  # noqa: B008
        from opspilot.playbooks import load_builtin_playbooks

        playbooks = []
        try:
            playbooks = load_builtin_playbooks()
        except (OSError, RuntimeError, ValueError, TypeError):
            playbooks = []
        return templates.TemplateResponse(request, "playbooks.html", {"request": request, "settings": settings, "playbooks": playbooks})

    @app.get("/audit", response_class=HTMLResponse)
    def audit_page(request: Request, _admin=Depends(require_admin)):  # noqa: B008
        events = []
        try:
            events = app.state.audit_repo.list_events(limit=100)
        except (OSError, RuntimeError, ValueError, TypeError):
            events = []
        return templates.TemplateResponse(request, "audit.html", {"request": request, "settings": settings, "events": events})

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, _admin=Depends(require_admin)):  # noqa: B008
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
