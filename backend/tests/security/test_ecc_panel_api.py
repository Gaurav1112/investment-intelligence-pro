"""ECC review panel (2026-10-15) regressions at the API layer: fastapi-reviewer F2 and F3, silent-failure-hunter F4."""

import logging
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import APIRouter
from starlette.testclient import TestClient

from iip.api.app import create_app
from iip.api.routes import all_routers
from iip.api.settings import Settings
from iip.services import ingestion

from .conftest import BASE, ORIGIN

SECRET = "units=123.45 amount=₹9,87,654"


def _boom_router() -> APIRouter:
    r = APIRouter()

    @r.get("/api/boom-values")
    def boom() -> None:
        raise ValueError(SECRET)

    return r


def test_f2_no_exception_escapes_the_asgi_app(settings: Settings, caplog: pytest.LogCaptureFixture) -> None:
    """Starlette re-raises after its 500 handler; uvicorn then logged the traceback and the message (with values).
    With raise_server_exceptions=True, any exception leaving the outermost middleware fails this test."""
    app = create_app(settings, routers=[_boom_router()])
    token = settings.token_path.read_text().strip()
    caplog.set_level(logging.DEBUG)
    with TestClient(app, base_url=BASE, raise_server_exceptions=True) as c:
        assert c.post("/api/session", json={"token": token}, headers={"Origin": ORIGIN}).status_code == 200
        r = c.get("/api/boom-values")
    assert r.status_code == 500 and r.json()["code"] == "INTERNAL_ERROR"
    assert SECRET not in caplog.text and "9,87,654" not in caplog.text
    assert "ValueError" in caplog.text  # the class is logged (SEC-21), never the message


def _seed_scheme(conn: sqlite3.Connection, code: str = "990001") -> None:
    conn.execute(
        "INSERT INTO instruments(instrument_id, kind, name, amfi_code, origin, created_at)"
        " VALUES (?, 'mf_scheme', 'TEST Fund - Direct Growth', ?, 'fixture', '2026-10-15')",
        (f"mf:{code}", code),
    )
    conn.execute(
        "INSERT INTO mf_schemes(instrument_id, amc, category_raw, sebi_category, plan)"
        " VALUES (?, 'TEST AMC', 'Liquid', 'Liquid', 'direct')",
        (f"mf:{code}",),
    )


def test_f3_backfill_is_rate_limited_paced_and_shares_one_breaker(
    authed: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, csrf = authed
    st = client.app.app.state.iip  # type: ignore[attr-defined]
    _seed_scheme(st.conn)
    seen: list[dict[str, Any]] = []

    def discover(_conn: object, fetcher: object, _amc: str, _day: object, **kw: Any) -> int:
        seen.append({"fetcher": fetcher, **kw})
        return 9

    def backfill(_conn: object, fetcher: object, **kw: Any) -> ingestion.RunSummary:
        seen.append({"fetcher": fetcher, **kw})
        return ingestion.RunSummary("run_x", "amfi.navhistory", "ok", 0, 0, 0, "stub")

    monkeypatch.setattr(ingestion, "discover_fund_house_id", discover)
    monkeypatch.setattr(ingestion, "backfill_history", backfill)
    h = {"Origin": ORIGIN, "X-IIP-CSRF": csrf}
    assert client.post("/api/ingestion/backfill/990001", json={"years": 1}, headers=h).status_code == 200
    second = client.post("/api/ingestion/backfill/990001", json={"years": 1}, headers=h)
    assert second.status_code == 429 and second.json()["code"] == "RATE_LIMITED"
    assert int(second.headers["retry-after"]) > 0
    assert len(seen) == 2  # the refused call made no outbound request
    assert all(s["pause"] is st.pause for s in seen)  # requests are paced
    assert seen[0]["fetcher"].breaker is st.breaker  # breaker state outlives the request (C-16)


def test_f3_unknown_scheme_does_not_consume_the_refresh_slot(authed: tuple[TestClient, str]) -> None:
    client, csrf = authed
    h = {"Origin": ORIGIN, "X-IIP-CSRF": csrf}
    assert client.post("/api/ingestion/backfill/123", json={"years": 1}, headers=h).status_code == 404
    st = client.app.app.state.iip  # type: ignore[attr-defined]
    assert st.claim_refresh("amfi.navhistory:123") is None


def test_backfill_limit_is_per_scheme_and_one_backfill_runs_at_a_time(
    authed: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """User decision 2026-10-15: 1 backfill per scheme per 15 min, so several schemes can be filled back to back;
    only one backfill runs at a time, so AMFI still sees at most the paced rate."""
    client, csrf = authed
    st = client.app.app.state.iip  # type: ignore[attr-defined]
    _seed_scheme(st.conn, "990001")
    _seed_scheme(st.conn, "990002")
    monkeypatch.setattr(ingestion, "discover_fund_house_id", lambda *_a, **_k: 9)
    stub = ingestion.RunSummary("run_x", "amfi.navhistory", "ok", 0, 0, 0, "stub")
    monkeypatch.setattr(ingestion, "backfill_history", lambda *_a, **_k: stub)
    h = {"Origin": ORIGIN, "X-IIP-CSRF": csrf}
    assert client.post("/api/ingestion/backfill/990001", json={"years": 1}, headers=h).status_code == 200
    assert client.post("/api/ingestion/backfill/990002", json={"years": 1}, headers=h).status_code == 200
    assert client.post("/api/ingestion/backfill/990001", json={"years": 1}, headers=h).status_code == 429
    with st.backfill_lock:  # another backfill in progress → refused at once, and no slot is used
        busy = client.post("/api/ingestion/backfill/990003", json={"years": 1}, headers=h)
    assert busy.status_code == 404  # unknown scheme is still checked first
    _seed_scheme(st.conn, "990003")
    with st.backfill_lock:
        busy = client.post("/api/ingestion/backfill/990003", json={"years": 1}, headers=h)
    assert busy.status_code == 429 and busy.json()["code"] == "BACKFILL_IN_PROGRESS"
    assert client.post("/api/ingestion/backfill/990003", json={"years": 1}, headers=h).status_code == 200


def test_f3_refresh_claim_is_atomic_across_threads(authed: tuple[TestClient, str]) -> None:
    st = authed[0].app.app.state.iip  # type: ignore[attr-defined]
    barrier = threading.Barrier(8)
    granted: list[bool] = []

    def worker() -> None:
        barrier.wait(5)
        granted.append(st.claim_refresh("amfi.navall") is None)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert granted.count(True) == 1


def test_f4_startup_marks_runs_left_running_as_interrupted(tmp_path: Path) -> None:
    s = Settings(env="test", data_dir=tmp_path / "iip", auth=False)
    first = create_app(s, routers=all_routers())
    conn = first.app.state.iip.conn  # type: ignore[attr-defined]
    ingestion.sync_sources(conn)
    conn.execute("INSERT INTO ingestion_runs(run_id, source_id, started_at, status) VALUES"
                 " ('run_old', 'amfi.navall', '2026-10-15T00:00:00+00:00', 'running')")  # fmt: skip
    first.app.state.iip.close()  # type: ignore[attr-defined]
    second = create_app(s, clock=lambda: datetime(2026, 10, 15, 6, 0, tzinfo=UTC))
    row = second.app.state.iip.conn.execute("SELECT status, error FROM ingestion_runs").fetchone()  # type: ignore[attr-defined]
    assert tuple(row) == ("failed", ingestion.INTERRUPTED)
    second.app.state.iip.close()  # type: ignore[attr-defined]
