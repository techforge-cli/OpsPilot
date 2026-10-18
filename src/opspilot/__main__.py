import argparse
import os

from opspilot.config import settings_from_env
from opspilot.db import init_db
from opspilot.web import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="OpsPilot")
    parser.add_argument("--config-check", action="store_true", help="validate settings and exit")
    parser.add_argument("--host", default=None, help="override bind host")
    parser.add_argument("--port", type=int, default=None, help="override bind port")
    args = parser.parse_args()
    settings = settings_from_env()
    init_db(settings.data_path / "opspilot.sqlite")
    if args.config_check:
        os.makedirs(settings.data_path, exist_ok=True)
        print(f"configuration valid; data_dir={settings.data_dir}")
        return
    import uvicorn

    host = args.host or settings.bind_host
    port = args.port or settings.bind_port
    uvicorn.run(
        create_app(settings),
        host=host,
        port=port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
