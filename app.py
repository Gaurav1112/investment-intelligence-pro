"""Vercel entrypoint for the HOSTED mode (ADR-0013). Locally, run `make run` instead — this file is not used there.

Vercel's Python runtime loads the top-level ``app`` (an ASGI callable) from this file. The package lives in
backend/src, which Vercel bundles because it is reachable from the project root. Configuration comes only from the
project's encrypted environment variables (see docs/operations/deployment.md, "Hosted on Vercel"); a missing or
weak value refuses startup with a message, never a silent default.

The UI itself is served from Vercel's CDN (``public/``, built by scripts/vercel-build.sh, WP A04); this function
serves /api and remains a fallback for the UI.

Cron jobs J1–J5 are declared in vercel.json but ship DISABLED: while ``CRON_SECRET`` is empty, every ``/api/cron``
request is answered 404 here, before any other check (design-judgement §2 graft 18). The route and its bearer check
are WP B03; the host exception is WP A03.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend" / "src"))

os.environ.setdefault("IIP_DEPLOY", "vercel")

from iip.api.app import create_app  # noqa: E402 - the path above must be set first
from iip.api.routes import all_routers  # noqa: E402
from iip.api.security import HSTS, SECURITY_HEADERS  # noqa: E402
from iip.api.settings import from_env  # noqa: E402

CRON_PATH = "/api/cron"
_NOT_FOUND = json.dumps({"code": "NOT_FOUND"}).encode()


def cron_gate(inner: Any, cron_secret: str) -> Any:
    """Answer 404 on /api/cron and /api/cron/* while the secret is empty; otherwise pass everything through."""
    if cron_secret.strip():
        return inner

    async def gated(scope: Any, receive: Any, send: Any) -> None:
        path = scope.get("path", "") if scope["type"] == "http" else ""
        if path == CRON_PATH or path.startswith(CRON_PATH + "/"):
            headers = [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(_NOT_FOUND)).encode()),
                (b"cache-control", b"no-store"),
                *SECURITY_HEADERS,
                HSTS,
            ]
            await send({"type": "http.response.start", "status": 404, "headers": headers})
            await send({"type": "http.response.body", "body": _NOT_FOUND})
            return
        await inner(scope, receive, send)

    return gated


app = cron_gate(create_app(from_env(), routers=all_routers()), os.environ.get("CRON_SECRET", ""))
