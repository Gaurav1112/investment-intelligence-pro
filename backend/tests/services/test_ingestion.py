"""Ingestion pipeline over the real AMFI probe bytes (served by MockTransport — no network)."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from iip.data.fetch import CircuitBreaker, Fetcher
from iip.services import ingestion as ing
from iip.store.db import connect, migrate
from tests.data.conftest import load_fixture
from tests.data.test_fetch import PUBLIC_IP

NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
NAVALL = load_fixture("amfi_navall_excerpt.txt")
HISTORY = load_fixture("amfi_navhistory_excerpt.txt")


def fetcher(handler: object) -> Fetcher:
    return Fetcher(
        transport=httpx.MockTransport(handler),
        resolver=lambda _h: [PUBLIC_IP],
        jitter_seed=1,
        sleep=lambda _s: None,
        clock=lambda: NOW,
        breaker=CircuitBreaker(clock=lambda: NOW),
    )


def amfi(request: httpx.Request) -> httpx.Response:
    if request.url.host == "www.amfiindia.com":
        return httpx.Response(302, headers={"location": "https://portal.amfiindia.com/spages/NAVAll.txt"})
    if "NAVHistory" in request.url.path:
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=HISTORY)
    return httpx.Response(200, headers={"content-type": "text/plain"}, content=NAVALL)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[object]:
    c = connect(tmp_path / "x.db")
    migrate(c, NOW.isoformat())
    ing.sync_sources(c)
    yield c
    c.close()


def test_sources_are_mirrored_from_the_code_registry(conn) -> None:  # type: ignore[no-untyped-def]
    rows = {r["source_id"]: r for r in conn.execute("SELECT * FROM sources")}
    assert rows["amfi.navall"]["mode"] == "live" and rows["amfi.navall"]["official"] == 1
    assert "mfapi" not in "".join(rows) or rows.get("mfapi.in", {"mode": "disabled"})["mode"] == "disabled"


def test_navall_ingests_only_the_minimised_scope_with_provenance(conn) -> None:  # type: ignore[no-untyped-def]
    summary = ing.ingest_navall(conn, fetcher(amfi), lambda: NOW)
    assert summary.status in {"ok", "partial"} and summary.stored > 0
    names = [r["name"] for r in conn.execute("SELECT name FROM instruments")]
    assert names and all("direct" in n.lower() and "growth" in n.lower() and "(AMFI " in n for n in names)
    # AMFI reuses "Axis Children's Fund" for two Direct-Growth codes: names must stay distinguishable.
    assert len(set(names)) == len(names)
    obs = conn.execute("SELECT * FROM observations").fetchall()
    assert obs and all(o["source_id"] == "amfi.navall" and o["raw_sha256"] and o["retrieved_at"] for o in obs)
    assert all("." in o["value"] or o["value"].isdigit() for o in obs)  # decimal strings, never floats
    # Regression (live run 2026-10-15): a unit-string mismatch silently stored every row as 'rejected'.
    assert {o["quality_status"] for o in obs} == {"ok"}
    run = conn.execute("SELECT * FROM ingestion_runs").fetchone()
    assert run["status"] == summary.status and run["raw_sha256"]


def test_reingesting_the_same_file_is_idempotent(conn) -> None:  # type: ignore[no-untyped-def]
    ing.ingest_navall(conn, fetcher(amfi), lambda: NOW)
    n1 = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    ing.ingest_navall(conn, fetcher(amfi), lambda: NOW)
    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == n1


def test_fetch_failure_is_recorded_not_hidden(conn) -> None:  # type: ignore[no-untyped-def]
    summary = ing.ingest_navall(conn, fetcher(lambda _r: httpx.Response(500)), lambda: NOW)
    assert summary.status == "failed"
    assert conn.execute("SELECT status FROM ingestion_runs").fetchone()[0] == "failed"
    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0


def test_schema_change_fails_closed(conn) -> None:  # type: ignore[no-untyped-def]
    def changed(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"Code;Name;NAV\r\n1;x;10\r\n")

    summary = ing.ingest_navall(conn, fetcher(changed), lambda: NOW)
    assert summary.status == "failed" and "SchemaChanged" in summary.detail
    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0


def test_history_backfill_keeps_only_the_requested_scheme(conn) -> None:  # type: ignore[no-untyped-def]
    summary = ing.backfill_history(
        conn,
        fetcher(amfi),
        scheme_code=119018,
        mf_id=9,
        start=date(2026, 10, 13),
        end=date(2026, 10, 14),
        now=lambda: NOW,
    )
    assert summary.stored == 2
    series = {r["series_id"] for r in conn.execute("SELECT series_id FROM observations")}
    assert series == {"nav:119018"}
    values = [r["value"] for r in conn.execute("SELECT value FROM observations ORDER BY observation_date")]
    assert values == ["1393.087", "1385.402"]  # verbatim from the probe (HDFC Large Cap Direct Growth)
    statuses = {r["quality_status"] for r in conn.execute("SELECT quality_status FROM observations")}
    assert statuses == {"ok"}
