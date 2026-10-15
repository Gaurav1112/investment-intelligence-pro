"""FastAPI application factory (system-design.md §4). Security is enforced by SecurityMiddleware (first layer)."""

from __future__ import annotations

import hmac
import logging
import secrets
import sqlite3
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from iip.api.security import SESSION_COOKIE, RateLimiter, SecurityMiddleware, SessionStore
from iip.api.settings import Settings, ensure_access_token
from iip.store.db import connect, current_version, migrate

log = logging.getLogger("iip.api")
APP_VERSION = "0.1.0"


class TokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=16, max_length=256)


def utc_now() -> datetime:
    return datetime.now(UTC)


class AppState:
    """Shared application state. SQLite connections are PER THREAD: FastAPI runs sync endpoints in a thread pool, and a
    single shared connection used from several threads fails with sqlite3.InterfaceError (found in the live browser
    pass, 2026-10-15). WAL allows concurrent readers; writes serialise via BEGIN IMMEDIATE + busy_timeout."""

    def __init__(self, settings: Settings, clock: Callable[[], datetime] = utc_now) -> None:
        self.settings = settings
        self.clock = clock
        self.sessions = SessionStore()
        self.login_limiter = RateLimiter(limit=10, window_s=60)
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.token = ensure_access_token(settings) if settings.auth else ""
        self._local = threading.local()
        self._all: list[sqlite3.Connection] = []
        self._lock = threading.Lock()
        migrate(self.conn, clock().isoformat())

    @property
    def conn(self) -> sqlite3.Connection:
        c: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if c is None:
            c = connect(self.settings.db_path)
            self._local.conn = c
            with self._lock:
                self._all.append(c)
        return c

    def close(self) -> None:
        with self._lock:
            for c in self._all:
                c.close()
            self._all.clear()


def create_app(
    settings: Settings, *, clock: Callable[[], datetime] = utc_now, routers: list[APIRouter] | None = None
) -> Any:
    state = AppState(settings, clock)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        state.close()

    dev = settings.env in {"dev", "test"}
    app = FastAPI(
        title="Investment Intelligence Pro",
        version=APP_VERSION,
        lifespan=lifespan,
        docs_url="/api/docs" if dev else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if dev else None,
    )
    app.state.iip = state

    @app.exception_handler(Exception)
    async def generic_error(request: Request, exc: Exception) -> JSONResponse:  # SEC-21
        request_id = secrets.token_hex(8)
        log.error("unhandled error request_id=%s type=%s", request_id, type(exc).__name__)
        return JSONResponse({"code": "INTERNAL_ERROR", "request_id": request_id}, status_code=500)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/ready")
    def ready() -> dict[str, Any]:
        version = current_version(state.conn)
        return {
            "status": "ready" if version >= 1 else "not_ready",
            "schema_version": version,
            "app_version": APP_VERSION,
        }

    @app.post("/api/session")
    def login(body: TokenIn, response: Response) -> Any:
        if not state.login_limiter.allow():
            return JSONResponse({"code": "RATE_LIMITED"}, status_code=429)
        if not settings.auth or not hmac.compare_digest(body.token.encode(), state.token.encode()):
            log.warning("failed login attempt")  # never log the presented value
            return JSONResponse({"code": "BAD_TOKEN"}, status_code=401)
        session = state.sessions.create()
        response.set_cookie(
            SESSION_COOKIE, session.session_id, httponly=True, samesite="strict", path="/", secure=False
        )
        return {"csrf": session.csrf}

    @app.delete("/api/session")
    def logout(request: Request, response: Response) -> dict[str, str]:
        sess = request.scope.get("state", {}).get("session")
        if sess is not None:
            state.sessions.sessions.pop(sess.session_id, None)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"status": "logged_out"}

    @app.get("/api/me")
    def me(request: Request) -> dict[str, Any]:
        sess = request.scope.get("state", {}).get("session")
        return {"authenticated": True, "csrf": sess.csrf if sess else None, "env": settings.env}

    for router in routers or []:
        app.include_router(router)

    dist = Path(__file__).resolve().parents[4] / "frontend" / "dist"
    if dist.exists():
        index = dist / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str) -> Response:
            if full_path.startswith("api/"):
                return JSONResponse({"code": "NOT_FOUND"}, status_code=404)
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and dist in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(index)

    return SecurityMiddleware(app, settings, state.sessions)
