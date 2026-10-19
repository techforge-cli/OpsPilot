import hmac
import os
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
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

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    app.state.settings = settings
    _login_attempts: dict[str, list[float]] = {}
    _login_lock = threading.Lock()
    app.state.conn = connect(db_path)
    app.state.host_repo = HostRepository(app.state.conn)
    app.state.audit_repo = AuditRepository(
        app.state.conn,
        journal_path=data_path / "audit" / "audit.jsonl",
    )
    audit_secret = os.environ.get("OPSPILOT_AUDIT_SECRET", "")
    if audit_secret and app.state.audit_repo.journal is not None:
        app.state.audit_repo.journal.secret = audit_secret.encode()
    app.state.write_lock = threading.Lock()

    try:
        if not app.state.host_repo.list_hosts():
            app.state.host_repo.save(default_local_host())
    except (OSError, RuntimeError, ValueError, TypeError):
        pass

    runtime = build_runtime(settings, app.state.conn, app.state.audit_repo)
    app.state.runtime = runtime

    if settings.demo_mode:
        from opspilot.demo import DemoSession
        app.state.demo_session = DemoSession(
            app.state.conn,
            app.state.audit_repo,
            runtime["safety_guard"],
            runtime["executor"],
        )
        app.state.demo_session.seed_hosts()
    else:
        app.state.demo_session = None

    if settings.demo_mode:
        from opspilot.demo import DemoSession
        app.state.demo_session = DemoSession(
            app.state.conn,
            app.state.audit_repo,
            runtime["safety_guard"],
            runtime["executor"],
        )
        app.state.demo_session.seed_hosts()
    else:
        app.state.demo_session = None
    app.state.analyzer = runtime["analyzer"]
    app.state.executor = runtime["executor"]
    app.state.incident_repo = runtime["incident_manager"].repository if runtime["incident_manager"] else None

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    security = HTTPBasic(auto_error=False)

    def require_admin(request: Request, credentials: HTTPBasicCredentials | None = Depends(security)):  # noqa: B008
        cookie = request.cookies.get("opspilot_session")
        if cookie and hmac.compare_digest(cookie, _session_token(settings)):
            return "admin"
        if not settings.admin_password:
            if credentials is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                    headers={"WWW-Authenticate": 'Basic realm="OpsPilot"'},
                )
            return "read-only"
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
        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with _login_lock:
            attempts = _login_attempts.setdefault(client_ip, [])
            attempts[:] = [t for t in attempts if now - t < 300]
            if len(attempts) >= 5:
                raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many login attempts")
            attempts.append(now)
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

    @app.get("/readyz")
    def readyz():
        checks = {}
        try:
            app.state.conn.execute("SELECT 1").fetchone()
            checks["database"] = "ok"
        except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error):
            checks["database"] = "error"
        ollama_url = getattr(app.state.settings, "ollama_base_url", "")
        if ollama_url:
            try:
                resp = httpx.get(f"{ollama_url.rstrip('/')}/api/tags", timeout=5)
                checks["ollama"] = "ok" if resp.status_code == 200 else "unavailable"
            except (OSError, RuntimeError, ValueError, TypeError, ImportError, httpx.HTTPError):
                checks["ollama"] = "unavailable"
        else:
            checks["ollama"] = "not_configured"
        all_ok = all(v in ("ok", "not_configured") for v in checks.values())
        return JSONResponse({"status": "ok" if all_ok else "degraded", "checks": checks}, status_code=200 if all_ok else 503)

    @app.post("/demo/trigger/{tier}")
    def demo_trigger(tier: int, request: Request, _admin=Depends(require_admin)):
        if not hasattr(app.state, "demo_session") or app.state.demo_session is None:
            raise HTTPException(status_code=404, detail="demo mode not enabled")
        return app.state.demo_session.trigger_tier(tier)

    @app.post("/demo/confirm")
    def demo_confirm(request: Request, _admin=Depends(require_admin)):
        if not hasattr(app.state, "demo_session") or app.state.demo_session is None:
            raise HTTPException(status_code=404, detail="demo mode not enabled")
        return app.state.demo_session.confirm()

    @app.get("/demo/status")
    def demo_status(request: Request, _admin=Depends(require_admin)):
        if not hasattr(app.state, "demo_session") or app.state.demo_session is None:
            raise HTTPException(status_code=404, detail="demo mode not enabled")
        return app.state.demo_session.get_status()

    return app
