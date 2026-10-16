"""PLAN A03 / rank 10 (SEC-cron-2): the deployment host ($VERCEL_URL) is accepted ONLY on /api/cron/{job} with a valid
CRON_SECRET bearer; every other route still returns 400 on that host; wrong secrets are rate-limited. Synthetic hosts
and secrets only."""

from __future__ import annotations

import asyncio
import secrets
import sqlite3
from typing import Any

import pytest

from iip.api.security import (
    CRON_RATE_LIMIT,
    CronAuth,
    DbRateLimiter,
    RateLimiter,
    SecurityMiddleware,
    SessionStore,
    cron_auth_from_env,
)
from iip.api.settings import Settings, StartupRefused

PUBLIC = "iip.example.test"
DEPLOY = "iip-abc123-owner.vercel.app"
SECRET = secrets.token_urlsafe(32)
ACCESS = secrets.token_urlsafe(32)


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _settings() -> Settings:
    return Settings(env="test", deploy="vercel", public_origin=f"https://{PUBLIC}", access_token=ACCESS)


class _App:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        self.calls.append(dict(scope.get("state", {})))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})


def _mw(cron: CronAuth | None, sessions: SessionStore | None = None) -> tuple[SecurityMiddleware, _App]:
    app = _App()
    return SecurityMiddleware(app, _settings(), sessions or SessionStore(), cron=cron), app


def _cron(clock: _Clock | None = None) -> CronAuth:
    return CronAuth(SECRET, DEPLOY, RateLimiter(limit=CRON_RATE_LIMIT, window_s=60, clock=clock or _Clock()))


def call(
    mw: SecurityMiddleware,
    path: str,
    *,
    host: str = DEPLOY,
    method: str = "GET",
    bearer: str | None = SECRET,
    extra: list[tuple[bytes, bytes]] | None = None,
) -> int:
    headers = [(b"host", host.encode())]
    if bearer is not None:
        headers.append((b"authorization", f"Bearer {bearer}".encode()))
    headers.extend(extra or [])
    scope = {"type": "http", "method": method, "path": path, "headers": headers, "query_string": b""}
    status: list[int] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Any) -> None:
        if message["type"] == "http.response.start":
            status.append(message["status"])

    asyncio.run(mw(scope, receive, send))
    return status[0]


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_deployment_host_with_valid_bearer_reaches_the_cron_route(method: str) -> None:
    mw, app = _mw(_cron())
    assert call(mw, "/api/cron/navall", method=method) == 200
    assert app.calls == [{"session": None, "cron": True}]


def test_public_host_with_valid_bearer_also_works() -> None:
    mw, _ = _mw(_cron())
    assert call(mw, "/api/cron/navall-continue", host=PUBLIC) == 200


@pytest.mark.parametrize(
    "path",
    [
        "/", "/index.html", "/assets/app.js", "/api", "/api/", "/api/health", "/api/session", "/api/holdings",
        "/api/cron", "/api/cron/", "/api/cron/navall/extra", "/api/cronx/navall", "/api/cron/NAVALL",
        "/api/cron/../holdings", "/api/cron/nav all", "/api/data-health",
    ],
)  # fmt: skip
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_every_other_route_still_refuses_the_deployment_host(path: str, method: str) -> None:
    mw, app = _mw(_cron())
    assert call(mw, path, method=method) == 400
    assert app.calls == []


def test_deployment_host_refused_on_cron_route_when_cron_is_off() -> None:
    mw, _ = _mw(None)
    assert call(mw, "/api/cron/navall") == 400


def test_cron_route_is_404_when_no_secret_configured() -> None:
    mw, app = _mw(None)
    assert call(mw, "/api/cron/navall", host=PUBLIC) == 404
    assert app.calls == []


def test_unknown_host_refused_on_cron_route() -> None:
    mw, _ = _mw(_cron())
    assert call(mw, "/api/cron/navall", host="other-xyz.vercel.app") == 400
    assert call(mw, "/api/cron/navall", host=f"{DEPLOY}:443") == 400


@pytest.mark.parametrize(
    "auth",
    [
        None,
        [(b"authorization", b"Bearer wrong")],
        [(b"authorization", f"Basic {SECRET}".encode())],
        [(b"authorization", SECRET.encode())],
        [(b"authorization", f"Bearer {SECRET} ".encode())],
        [(b"authorization", f"Bearer {SECRET}".encode()), (b"authorization", f"Bearer {SECRET}".encode())],
    ],
)
def test_missing_or_wrong_bearer_is_401(auth: list[tuple[bytes, bytes]] | None) -> None:
    mw, app = _mw(_cron())
    assert call(mw, "/api/cron/navall", bearer=None, extra=auth) == 401
    assert app.calls == []


def test_session_cookie_is_neither_required_nor_accepted() -> None:
    sessions = SessionStore()
    s = sessions.create()
    mw, _ = _mw(_cron(), sessions)
    cookie = [(b"cookie", f"iip_session={s.session_id}".encode())]
    assert call(mw, "/api/cron/navall", bearer=None, extra=cookie) == 401
    assert call(mw, "/api/cron/navall", extra=cookie) == 200


def test_access_token_is_not_a_cron_secret() -> None:
    mw, _ = _mw(_cron())
    assert call(mw, "/api/cron/navall", bearer=ACCESS) == 401


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE", "OPTIONS"])
def test_other_methods_are_405(method: str) -> None:
    mw, _ = _mw(_cron())
    assert call(mw, "/api/cron/navall", method=method) == 405


def test_body_cap_still_applies() -> None:
    mw, _ = _mw(_cron())
    too_big = [(b"content-length", str(10 * 1024 * 1024).encode())]
    assert call(mw, "/api/cron/navall", method="POST", extra=too_big) == 413


def test_wrong_secrets_are_rate_limited_but_never_lock_out_the_right_one() -> None:
    """fastapi-reviewer-1 / security-reviewer-3: only wrong attempts are limited. The correct secret still runs the
    job during a lockout (otherwise anyone could suppress the public cron schedule with junk bearers)."""
    clock = _Clock()
    mw, app = _mw(_cron(clock))
    for _ in range(CRON_RATE_LIMIT):
        assert call(mw, "/api/cron/navall", bearer="guess") == 401
    assert call(mw, "/api/cron/navall", bearer="guess") == 429
    assert call(mw, "/api/cron/navall") == 200
    assert len(app.calls) == 1
    clock.t += 61
    assert call(mw, "/api/cron/navall", bearer="guess") == 401


def test_junk_on_the_public_host_cannot_suppress_the_scheduled_jobs() -> None:
    clock = _Clock()
    mw, app = _mw(_cron(clock))
    for _ in range(CRON_RATE_LIMIT + 3):
        assert call(mw, "/api/cron/x", host=PUBLIC, bearer="junk") in (401, 429)
    for job in ("navall", "navall-continue", "history", "snapshot", "watchdog"):
        assert call(mw, f"/api/cron/{job}") == 200
    assert len(app.calls) == 5


def test_correct_secret_does_not_consume_the_limit() -> None:
    mw, _ = _mw(_cron())
    for _ in range(CRON_RATE_LIMIT * 2):
        assert call(mw, "/api/cron/navall") == 200


def test_db_rate_limiter_exhausted_is_shared_and_separate_from_login() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE rate_hits (key TEXT NOT NULL, at REAL NOT NULL)")
    clock = _Clock()
    cron = DbRateLimiter(lambda: conn, "cron", limit=2, window_s=60, clock=clock)
    login = DbRateLimiter(lambda: conn, "login", limit=2, window_s=60, clock=clock)
    assert not cron.exhausted()
    assert cron.allow() and cron.allow()
    assert cron.exhausted() and not login.exhausted()
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    assert cron.exhausted()
    assert not any(s.upper().startswith(("INSERT", "DELETE")) for s in statements)  # looking records nothing
    clock.t += 61
    assert not cron.exhausted()


# ---- configuration -------------------------------------------------------------------------------------------------

ENV = {"CRON_SECRET": SECRET, "VERCEL_URL": DEPLOY.upper(), "VERCEL_ENV": "production"}


def _limiter() -> RateLimiter:
    return RateLimiter(limit=CRON_RATE_LIMIT, window_s=60)


def test_from_env_enables_with_lowercased_host() -> None:
    cron = cron_auth_from_env(_settings(), dict(ENV), _limiter())
    assert cron is not None and cron.deployment_host == DEPLOY and cron.secret == SECRET
    assert SECRET not in repr(cron)


@pytest.mark.parametrize(
    "override",
    [{"CRON_SECRET": ""}, {"CRON_SECRET": "   "}, {"VERCEL_URL": ""}, {"VERCEL_ENV": "preview"}, {"VERCEL_ENV": ""}],
)
def test_from_env_off(override: dict[str, str]) -> None:
    assert cron_auth_from_env(_settings(), {**ENV, **override}, _limiter()) is None


def test_from_env_off_when_not_hosted() -> None:
    assert cron_auth_from_env(Settings(env="test"), dict(ENV), _limiter()) is None


@pytest.mark.parametrize(
    "override",
    [
        {"CRON_SECRET": "x" * 31},
        {"CRON_SECRET": ACCESS},
        {"VERCEL_URL": f"https://{DEPLOY}"},
        {"VERCEL_URL": f"{DEPLOY}/path"},
        {"VERCEL_URL": f"user@{DEPLOY}"},
        {"VERCEL_URL": f"{DEPLOY}:443"},
        {"VERCEL_URL": "localhost"},
    ],
)
def test_from_env_refuses_startup_on_weak_config(override: dict[str, str]) -> None:
    with pytest.raises(StartupRefused):
        cron_auth_from_env(_settings(), {**ENV, **override}, _limiter())
