import hmac
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from opspilot.config import Settings
from opspilot.db import connect, init_db


def create_app(settings: Settings):
    data_path = Path(settings.data_dir)
    db_path = data_path / "opspilot.sqlite"
    init_db(db_path)
    templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
    app = FastAPI(title="OpsPilot")
    app.state.settings = settings
    app.state.conn = connect(db_path)

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

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request, _admin=Depends(require_admin)):
        return templates.TemplateResponse(
            request,
            "index.html",
            {"request": request, "settings": settings},
        )

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app
