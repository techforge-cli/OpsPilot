import hmac
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from opspilot.audit import AuditRepository
from opspilot.config import Settings
from opspilot.db import connect, init_db, latest_snapshot
from opspilot.hosts import HostRepository, default_local_host
from opspilot.playbooks import load_builtin_playbooks
from opspilot.runtime import build_runtime
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
    app.state.write_lock = threading.Lock()

    try:
        if not app.state.host_repo.list_hosts():
            app.state.host_repo.save(default_local_host())
    except (OSError, RuntimeError, ValueError, TypeError):
        pass

    runtime = build_runtime(settings, app.state.conn, app.state.audit_repo)
    app.state.runtime = runtime
    app.state.analyzer = runtime["analyzer"]
    app.state.executor = runtime["executor"]
    app.state.incident_repo = runtime["incident_manager"].repository if runtime["incident_manager"] else None

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

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

    def require_write(request: Request):
        if settings.read_only_web_mode:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Read-only mode")
        origin = request.headers.get("origin")
        if origin is not None:
            host = request.headers.get("host")
            if host is not None and not origin.endswith(host):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request refused")

    try:
        app.state.scheduler = Scheduler.start_background(
            settings,
            app.state.conn,
            analyzer=runtime["analyzer"],
            safety_guard=runtime["safety_guard"],
            executor=runtime["executor"],
            incident_manager=runtime["incident_manager"],
            playbooks=runtime["playbooks"],
            audit=app.state.audit_repo,
            write_lock=app.state.write_lock,
        )
    except (OSError, RuntimeError, ValueError, TypeError):
        app.state.scheduler = None

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        yield
        scheduler = application.state.scheduler
        if scheduler is not None:
            try:
                scheduler.stop()
            except (RuntimeError, ValueError):
                pass
        client = getattr(application.state.analyzer, "client", None)
        if client is not None and hasattr(client, "close"):
            try:
                client.close()
            except (OSError, RuntimeError):
                pass

    app.router.lifespan_context = lifespan  # type: ignore[assignment]

    def _render(request: Request, name: str, context: dict):
        return templates.TemplateResponse(request, name, {"request": request, "settings": settings, **context})

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        return _render(request, "login.html", {})

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

    def _snapshots(hosts):
        return {host.id: latest_snapshot(app.state.conn, host.id) for host in hosts}

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request, _admin=Depends(require_admin)):  # noqa: B008
        hosts = app.state.host_repo.list_hosts()
        incidents = app.state.incident_repo.list_incidents() if app.state.incident_repo else []
        return _render(
            request,
            "index.html",
            {
                "hosts": hosts,
                "snapshots": _snapshots(hosts),
                "latest_incident": incidents[0] if incidents else None,
                "pending": [i for i in incidents if i.status == "pending_confirmation"],
            },
        )

    @app.get("/partials/status", response_class=HTMLResponse)
    def status_partial(request: Request, _admin=Depends(require_admin)):  # noqa: B008
        hosts = app.state.host_repo.list_hosts()
        return templates.TemplateResponse(
            request, "_status.html", {"request": request, "hosts": hosts, "snapshots": _snapshots(hosts)}
        )

    @app.get("/hosts", response_class=HTMLResponse)
    def hosts_page(request: Request, _admin=Depends(require_admin)):  # noqa: B008
        return _render(request, "hosts.html", {"hosts": app.state.host_repo.list_hosts()})

    @app.get("/incidents", response_class=HTMLResponse)
    def incidents_page(request: Request, _admin=Depends(require_admin)):  # noqa: B008
        incidents = app.state.incident_repo.list_incidents() if app.state.incident_repo else []
        return _render(request, "incidents.html", {"incidents": incidents})

    @app.get("/incidents/{incident_id}", response_class=HTMLResponse)
    def incident_detail(incident_id: str, request: Request, _admin=Depends(require_admin)):  # noqa: B008
        repo = app.state.incident_repo
        incident = repo.get(incident_id) if repo else None
        if incident is None:
            raise HTTPException(status_code=404, detail="incident not found")
        return _render(request, "incident_detail.html", {"incident": incident, "runs": repo.list_runs(incident_id)})

    @app.post("/incidents/{incident_id}/confirm")
    def confirm_incident(incident_id: str, request: Request, _admin=Depends(require_admin)):  # noqa: B008
        require_write(request)
        scheduler = app.state.scheduler
        repo = app.state.incident_repo
        if scheduler is None or repo is None:
            raise HTTPException(status_code=503, detail="scheduler unavailable")
        with app.state.write_lock:
            if not repo.set_status(incident_id, "executing", expected="pending_confirmation"):
                existing = repo.get(incident_id)
                if existing is None:
                    raise HTTPException(status_code=404, detail="incident not found")
                raise HTTPException(status_code=409, detail=f"incident is {existing.status}, not pending")
            incident = repo.get(incident_id)
            playbook = scheduler._find_playbook(scheduler._playbooks(), incident.playbook_id)
            if playbook is None:
                repo.set_status(incident_id, "blocked")
                raise HTTPException(status_code=409, detail="playbook no longer in catalog")
            host = app.state.host_repo.get_host(incident.host_id) or default_local_host()
            snapshot = latest_snapshot(app.state.conn, host.id)
            scheduler.execute_incident(incident, playbook, host, snapshot)
        return RedirectResponse(url=f"/incidents/{incident_id}", status_code=303)

    @app.post("/incidents/{incident_id}/dismiss")
    def dismiss_incident(incident_id: str, request: Request, _admin=Depends(require_admin)):  # noqa: B008
        require_write(request)
        repo = app.state.incident_repo
        if repo is None:
            raise HTTPException(status_code=503, detail="repository unavailable")
        incident = repo.get(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="incident not found")
        if incident.status in ("resolved", "dismissed"):
            raise HTTPException(status_code=409, detail=f"incident already {incident.status}")
        repo.set_status(incident_id, "dismissed")
        app.state.audit_repo.record("incident_dismissed", host_id=incident.host_id, message="dismissed by operator", detail={"incident_id": incident_id})
        return RedirectResponse(url=f"/incidents/{incident_id}", status_code=303)

    @app.get("/playbooks", response_class=HTMLResponse)
    def playbooks_page(request: Request, _admin=Depends(require_admin)):  # noqa: B008
        return _render(request, "playbooks.html", {"playbooks": load_builtin_playbooks()})

    @app.get("/audit", response_class=HTMLResponse)
    def audit_page(request: Request, _admin=Depends(require_admin)):  # noqa: B008
        events = app.state.audit_repo.list_events(limit=200)
        return _render(request, "audit.html", {"events": events})

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, _admin=Depends(require_admin)):  # noqa: B008
        return _render(request, "settings.html", {})

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app
