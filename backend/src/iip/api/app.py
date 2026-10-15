"""FastAPI application factory (system-design.md §4). Security is enforced by SecurityMiddleware (first layer)."""

from __future__ import annotations

import hmac
import logging
import os
import secrets
import sqlite3
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from iip.api.security import (
    SESSION_COOKIE,
    DbRateLimiter,
    DbSessionStore,
    LoginLimiter,
    RateLimiter,
    SecurityMiddleware,
    SessionBackend,
    SessionStore,
)
from iip.api.settings import Settings, ensure_access_token
from iip.data.fetch import CircuitBreaker, Fetcher
from iip.services import ingestion
from iip.store import coordination
from iip.store.coordination import DbLease
from iip.store.db import connect, connect_libsql, current_version, migrate

log = logging.getLogger("iip.api")
APP_VERSION = "0.1.0"
REFRESH_MIN_INTERVAL_S = 15 * 60  # SEC-86: one manual refresh per source per 15 minutes
# Hosted (ADR-0013). Vercel Hobby with Fluid compute: maxDuration ≤ 300 s (vercel.json sets 300). A job stops
# starting new upstream requests after HOSTED_JOB_BUDGET_S, leaving room for one slow request and the DB writes. A
# function killed at its limit never releases its lease, so leases lapse a little after the limit.
HOSTED_JOB_BUDGET_S = 200.0
LEASE_TTL_S = 330.0


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
        self.hosted = settings.hosted
        self._local = threading.local()
        self._all: list[sqlite3.Connection] = []
        self._lock = threading.Lock()
        # C-16 / SEC-86 (ECC F3): one breaker for the process so its state outlives a request; outbound requests are
        # paced; manual refreshes are limited per source, with an atomic check-and-set (routes run in a thread pool).
        self.breaker = CircuitBreaker(clock=clock)
        self.pause: Callable[[float], object] = time.sleep
        self.monotonic: Callable[[], float] = time.monotonic
        self.fetcher_factory: Callable[[], Fetcher] | None = None
        self._refresh_lock = threading.Lock()
        self._last_refresh: dict[str, datetime] = {}
        # Hosted resumable jobs (ADR-0013): work per call stops starting new requests after this many seconds, well
        # inside the platform's function time limit; the next call resumes from the stored progress.
        self.job_budget_s = HOSTED_JOB_BUDGET_S
        self.sessions: SessionBackend
        self.login_limiter: LoginLimiter
        # Only one NAV-history backfill runs at a time, so AMFI sees at most the paced rate (C-16).
        self.backfill_lock: threading.Lock | DbLease
        self.navall_lock: threading.Lock | DbLease  # hosted only: one resumable NAVAll job at a time
        if self.hosted:
            # ADR-0013: no local disk, no memory shared between instances. The token comes from the platform's
            # encrypted environment; sessions, limits and the backfill lock live in the database.
            self.token = settings.access_token
            epoch = self.epoch
            self.sessions = DbSessionStore(lambda: self.conn, clock=epoch)
            self.login_limiter = DbRateLimiter(lambda: self.conn, "login", limit=10, window_s=60, clock=epoch)
            self.backfill_lock = DbLease(lambda: self.conn, "backfill", ttl_s=LEASE_TTL_S, clock=epoch)
            self.navall_lock = DbLease(lambda: self.conn, "navall", ttl_s=LEASE_TTL_S, clock=epoch)
        else:
            self.sessions = SessionStore()
            self.login_limiter = RateLimiter(limit=10, window_s=60)
            self.settings.data_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(self.settings.data_dir, 0o700)  # SEC-82: private financial data
            self.token = ensure_access_token(settings) if settings.auth else ""
            self.backfill_lock = threading.Lock()
            self.navall_lock = threading.Lock()
        migrate(self.conn, clock().isoformat())
        if not self.hosted:
            _restrict_db_files(self.settings.db_path)
        # Hosted: another instance may be running a job right now, so only runs older than any function could live
        # are "interrupted"; locally one process means every 'running' row was cut off.
        started_before = clock() - timedelta(seconds=LEASE_TTL_S) if self.hosted else None
        if ingestion.mark_interrupted_runs(self.conn, clock(), started_before=started_before):
            log.warning("ingestion runs left 'running' by a previous process were marked failed (interrupted)")

    def epoch(self) -> float:
        return self.clock().timestamp()

    def fetcher(self) -> Fetcher:
        """A fetcher sharing the process-wide circuit breaker (tests inject ``fetcher_factory``)."""
        if self.fetcher_factory is not None:
            return self.fetcher_factory()
        return Fetcher(breaker=self.breaker)

    def claim_refresh(self, source_id: str) -> int | None:
        """Reserve this source's manual-refresh slot. None = granted; otherwise the seconds to wait."""
        if self.hosted:
            return coordination.claim_refresh(self.conn, source_id, self.epoch(), REFRESH_MIN_INTERVAL_S)
        with self._refresh_lock:
            now = self.clock()
            last = self._last_refresh.get(source_id)
            if last is not None and (elapsed := (now - last).total_seconds()) < REFRESH_MIN_INTERVAL_S:
                return int(REFRESH_MIN_INTERVAL_S - elapsed) + 1
            self._last_refresh[source_id] = now
            return None

    @property
    def conn(self) -> sqlite3.Connection:
        c: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if c is None:
            if self.hosted:
                c = connect_libsql(self.settings.db_url, self.settings.db_auth_token, hosted=True)
            else:
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


def _restrict_db_files(db: Path) -> None:
    """SEC-82: the database and its WAL/SHM side files are readable only by the owner."""
    for p in (db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")):
        if p.exists():
            os.chmod(p, 0o600)


def frontend_dist() -> Path:
    """The built UI (``make build``) served by the backend."""
    return Path(__file__).resolve().parents[4] / "frontend" / "dist"


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
        # Hosted (HTTPS): Secure, so the cookie is never sent over plain HTTP. Locally the app is plain-HTTP loopback.
        response.set_cookie(
            SESSION_COOKIE, session.session_id, httponly=True, samesite="strict", path="/", secure=settings.hosted
        )
        return {"csrf": session.csrf}

    @app.delete("/api/session")
    def logout(request: Request, response: Response) -> dict[str, str]:
        sess = request.scope.get("state", {}).get("session")
        if sess is not None:
            state.sessions.revoke(sess.session_id)
        response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict", secure=settings.hosted)
        return {"status": "logged_out"}

    @app.get("/api/me")
    def me(request: Request) -> dict[str, Any]:
        sess = request.scope.get("state", {}).get("session")
        return {
            "authenticated": True,
            "csrf": sess.csrf if sess else None,
            "env": settings.env,
            "deploy": settings.deploy,
        }

    for router in routers or []:
        app.include_router(router)

    dist = frontend_dist()
    if not (dist / "index.html").exists():
        # Clean-machine finding: starting the backend before `make build` silently served the API only (every page
        # 404). Say so once at startup; `make run` always builds first.
        log.warning("frontend build missing at %s: only the API is served; run `make build`", dist)
    else:
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
