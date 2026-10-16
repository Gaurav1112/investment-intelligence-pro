"""PLAN A03 / rank 3: the session lookup runs off the event loop, and a hosted session's last_seen is written at most
once per LAST_SEEN_THROTTLE_S. Synthetic sessions only; no network."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from typing import Any

from iip.api.security import (
    IDLE_TIMEOUT_S,
    LAST_SEEN_THROTTLE_S,
    DbSessionStore,
    SecurityMiddleware,
    Session,
)
from iip.api.settings import Settings

HOST = "127.0.0.1:8741"


async def _ok_app(scope: Any, receive: Any, send: Any) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": b"ok"})


async def _call(app: Any, path: str, cookie: str | None = None) -> int:
    headers = [(b"host", HOST.encode())]
    if cookie:
        headers.append((b"cookie", f"iip_session={cookie}".encode()))
    scope = {"type": "http", "method": "GET", "path": path, "headers": headers, "query_string": b""}
    status: list[int] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Any) -> None:
        if message["type"] == "http.response.start":
            status.append(message["status"])

    await app(scope, receive, send)
    return status[0]


class _SlowSessions:
    """``get('slow')`` blocks its thread until released; any other id returns at once."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.released_in_time: bool | None = None

    def get(self, session_id: str | None) -> Session | None:
        if session_id == "slow":
            self.released_in_time = self.release.wait(timeout=5)
        return Session(session_id or "", "csrf", 0.0, 0.0) if session_id else None

    def create(self) -> Session:  # pragma: no cover - unused
        raise NotImplementedError

    def revoke(self, session_id: str) -> None:  # pragma: no cover - unused
        pass

    def revoke_all(self) -> None:  # pragma: no cover - unused
        pass


def test_slow_session_lookup_does_not_block_a_second_request() -> None:
    sessions = _SlowSessions()
    mw = SecurityMiddleware(_ok_app, Settings(env="test"), sessions)

    async def scenario() -> tuple[int, int]:
        slow = asyncio.create_task(_call(mw, "/api/holdings", cookie="slow"))
        await asyncio.sleep(0.05)  # the slow lookup is now in progress
        # If the lookup ran on the event loop, this second request could not even start until the 5 s timeout.
        fast = await asyncio.wait_for(_call(mw, "/api/holdings", cookie="fast"), timeout=2)
        sessions.release.set()
        return fast, await slow

    fast, slow = asyncio.run(scenario())
    assert (fast, slow) == (200, 200)
    assert sessions.released_in_time is True


def test_public_route_answers_while_a_lookup_is_stalled() -> None:
    sessions = _SlowSessions()
    mw = SecurityMiddleware(_ok_app, Settings(env="test"), sessions)

    async def scenario() -> int:
        slow = asyncio.create_task(_call(mw, "/api/holdings", cookie="slow"))
        await asyncio.sleep(0.05)
        health = await asyncio.wait_for(_call(mw, "/api/health"), timeout=2)
        sessions.release.set()
        await slow
        return health

    assert asyncio.run(scenario()) == 200
    assert sessions.released_in_time is True


# ---- last_seen throttle (hosted DbSessionStore) -----------------------------------------------------------------


class _Clock:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _store() -> tuple[DbSessionStore, _Clock, list[str]]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE web_sessions (id_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, created REAL, last_seen REAL)"
    )
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    clock = _Clock(1_000_000.0)
    return DbSessionStore(lambda: conn, clock=clock), clock, statements


def _updates(statements: list[str]) -> int:
    return sum(1 for s in statements if s.lstrip().upper().startswith("UPDATE WEB_SESSIONS"))


def test_throttle_parameter_is_five_minutes() -> None:
    assert LAST_SEEN_THROTTLE_S == 300


def test_last_seen_written_at_most_once_per_five_minutes() -> None:
    store, clock, statements = _store()
    s = store.create()
    t0 = clock.t
    statements.clear()
    for dt in (1, 60, 150, 299):
        clock.t = t0 + dt
        got = store.get(s.session_id)
        assert got is not None and got.last_seen == t0
    assert _updates(statements) == 0
    clock.t = t0 + 300
    assert store.get(s.session_id) is not None
    assert _updates(statements) == 1
    clock.t = t0 + 300 + 299
    store.get(s.session_id)
    assert _updates(statements) == 1
    clock.t = t0 + 600
    got = store.get(s.session_id)
    assert _updates(statements) == 2 and got is not None and got.last_seen == t0 + 600


def test_throttled_lookup_is_one_statement() -> None:
    store, clock, statements = _store()
    s = store.create()
    clock.t += 10
    statements.clear()
    store.get(s.session_id)
    assert len(statements) == 1 and statements[0].lstrip().upper().startswith("SELECT")


def test_idle_timeout_still_applies_from_stored_last_seen() -> None:
    store, clock, _ = _store()
    s = store.create()
    t0 = clock.t
    clock.t = t0 + 200  # within the throttle: not written
    assert store.get(s.session_id) is not None
    clock.t = t0 + IDLE_TIMEOUT_S + 1
    assert store.get(s.session_id) is None


def test_session_kept_alive_by_regular_use() -> None:
    store, clock, _ = _store()
    s = store.create()
    for _ in range(int(IDLE_TIMEOUT_S * 2 / 240)):  # a request every 4 minutes for 16 hours (< 24 h absolute)
        clock.t += 240
        assert store.get(s.session_id) is not None
