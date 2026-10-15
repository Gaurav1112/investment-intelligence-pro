"""Entry point: `python -m iip.api`. Refuses unsafe configuration before binding (C-01)."""

from __future__ import annotations

import sys

import uvicorn

from iip.api.app import create_app
from iip.api.routes import all_routers
from iip.api.settings import StartupRefused, from_env


def main() -> int:
    try:
        settings = from_env()
    except StartupRefused as exc:
        print(f"iip: refusing to start: {exc}", file=sys.stderr)
        return 2
    app = create_app(settings, routers=all_routers())
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        server_header=False,
        proxy_headers=False,
        log_level="info",
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
