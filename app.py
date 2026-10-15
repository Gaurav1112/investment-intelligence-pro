"""Vercel entrypoint for the HOSTED mode (ADR-0013). Locally, run `make run` instead — this file is not used there.

Vercel's Python runtime loads the top-level ``app`` (an ASGI callable) from this file. The package lives in
backend/src, which Vercel bundles because it is reachable from the project root. Configuration comes only from the
project's encrypted environment variables (see docs/operations/deployment.md, "Hosted on Vercel"); a missing or
weak value refuses startup with a message, never a silent default.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend" / "src"))

os.environ.setdefault("IIP_DEPLOY", "vercel")

from iip.api.app import create_app  # noqa: E402 - the path above must be set first
from iip.api.routes import all_routers  # noqa: E402
from iip.api.settings import from_env  # noqa: E402

app = create_app(from_env(), routers=all_routers())
