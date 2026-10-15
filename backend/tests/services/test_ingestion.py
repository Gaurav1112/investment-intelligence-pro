"""Ingestion pipeline over synthetic AMFI-format bytes (served by MockTransport — no network)."""

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
    # AMFI reuses "Asteria Children's Fund" for two Direct-Growth codes: names must stay distinguishable.
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
        scheme_code=928470,
        mf_id=9,
        start=date(2026, 10, 13),
        end=date(2026, 10, 14),
        now=lambda: NOW,
    )
    assert summary.stored == 2
    series = {r["series_id"] for r in conn.execute("SELECT series_id FROM observations")}
    assert series == {"nav:928470"}
    values = [r["value"] for r in conn.execute("SELECT value FROM observations ORDER BY observation_date")]
    assert values == ["1393.087", "1385.402"]  # verbatim from the fixture (fictional)
    statuses = {r["quality_status"] for r in conn.execute("SELECT quality_status FROM observations")}
    assert statuses == {"ok"}


def test_untracked_schemes_keep_only_the_latest_nav(conn) -> None:  # type: ignore[no-untyped-def]
    """RT-21: no daily NAV archive accumulates for schemes the user neither holds, watches nor backfilled."""
    from iip.store.observations import ObservationRow, upsert_observation

    ing.ingest_navall(conn, fetcher(amfi), lambda: NOW)
    sid = conn.execute("SELECT series_id FROM observations LIMIT 1").fetchone()[0]
    upsert_observation(conn, ObservationRow(
        series_id=sid, kind="nav", value="1.0", unit="INR_per_unit", currency="INR", observation_date="2026-09-01",
        retrieved_at=NOW.isoformat(), source_id="amfi.navall", source_url="https://portal.amfiindia.com/x",
        quality_status="ok", raw_sha256="a" * 64))  # fmt: skip
    assert conn.execute("SELECT COUNT(*) FROM observations WHERE series_id=?", (sid,)).fetchone()[0] == 2
    ing.ingest_navall(conn, fetcher(amfi), lambda: NOW)
    assert conn.execute("SELECT COUNT(*) FROM observations WHERE series_id=?", (sid,)).fetchone()[0] == 1


def test_backfilled_schemes_keep_their_history(conn) -> None:  # type: ignore[no-untyped-def]
    ing.backfill_history(conn, fetcher(amfi), scheme_code=928470, mf_id=9, start=date(2026, 10, 13),
                         end=date(2026, 10, 14), now=lambda: NOW)  # fmt: skip
    ing.ingest_navall(conn, fetcher(amfi), lambda: NOW)
    assert conn.execute("SELECT COUNT(*) FROM observations WHERE series_id='nav:928470'").fetchone()[0] >= 2


def test_register_held_schemes_by_exact_isin_including_reinvestment_alias(conn) -> None:  # type: ignore[no-untyped-def]
    """CAS holdings outside the minimised scope (Regular/IDCW) are registered by EXACT ISIN from the live file."""
    from iip.data.parsers.amfi_navall import parse_navall
    from tests.data.conftest import NAVALL_RETRIEVED, NAVALL_URL, make_payload

    recs = parse_navall(make_payload("amfi.navall", NAVALL, NAVALL_URL, NAVALL_RETRIEVED)).records
    regular_idcw = next(r for r in recs if r.isin_reinvest and "regular" in (r.plan or "").lower())
    wanted = {regular_idcw.isin_growth or "", regular_idcw.isin_reinvest or "", "INE000000000"}
    found = ing.register_schemes_by_isin(conn, fetcher(amfi), wanted, lambda: NOW)
    iid = ing.instrument_id(regular_idcw.scheme_code)
    assert found[regular_idcw.isin_reinvest] == iid and "INE000000000" not in found
    assert conn.execute("SELECT COUNT(*) FROM observations WHERE series_id=?",
                        (ing.series_id(regular_idcw.scheme_code),)).fetchone()[0] >= 1  # fmt: skip
    alias = conn.execute("SELECT value_json FROM settings WHERE key=?",
                         ("isin.alias:" + regular_idcw.isin_reinvest,)).fetchone()  # fmt: skip
    assert alias is not None


def test_register_by_isin_fetch_failure_is_reported_not_returned_as_no_match(conn) -> None:  # type: ignore[no-untyped-def]
    """F3 (ECC panel): a failed AMFI lookup must not look like "no stored instrument has this ISIN"."""
    with pytest.raises(ing.IsinLookupFailed):
        ing.register_schemes_by_isin(conn, fetcher(lambda _r: httpx.Response(500)), {"INF000A01AB9"}, lambda: NOW)
    assert conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0] == 0  # nothing guessed or registered


# ------------------------------------------------------------------ ECC panel (track A) regressions


def _nav_row(sid: str, day: str, value: str) -> object:
    from iip.store.observations import ObservationRow

    return ObservationRow(
        series_id=sid, kind="nav", value=value, unit="INR_per_unit", currency="INR", observation_date=day,
        retrieved_at=NOW.isoformat(), source_id="amfi.navall", source_url="https://portal.amfiindia.com/x",
        quality_status="ok", raw_sha256="a" * 64)  # fmt: skip


def test_prune_survives_a_same_day_nav_correction(conn) -> None:  # type: ignore[no-untyped-def]
    """PR-1 / DB-1: a corrected NAV (old row superseded by a new row, same date) that falls behind the latest date
    used to be re-linked as current by the prune, breaching ux_obs_current; every later NAVAll then failed."""
    from iip.store.observations import upsert_observation

    sid = "nav:990001"
    upsert_observation(conn, _nav_row(sid, "2026-10-13", "10.0000"))  # type: ignore[arg-type]
    upsert_observation(conn, _nav_row(sid, "2026-10-13", "10.0100"))  # type: ignore[arg-type]  # a correction
    upsert_observation(conn, _nav_row(sid, "2026-10-14", "10.0200"))  # type: ignore[arg-type]
    assert ing.prune_untracked_history(conn, set()) == 2
    rows = conn.execute("SELECT observation_date, superseded_by FROM observations WHERE series_id=?", (sid,))
    assert [tuple(r) for r in rows] == [("2026-10-14", None)]
    assert ing.prune_untracked_history(conn, set()) == 0  # and the next run is clean too


def test_navall_failure_after_start_marks_the_run_failed_and_reraises(conn, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """F4: an unexpected error after the fetch used to leave the run 'running' forever, so no alert fired."""
    import sqlite3

    from iip.services import alerts

    def boom(*_a: object, **_k: object) -> int:
        raise sqlite3.OperationalError("database is locked units=123.45")

    monkeypatch.setattr(ing, "prune_untracked_history", boom)
    with pytest.raises(sqlite3.OperationalError):
        ing.ingest_navall(conn, fetcher(amfi), lambda: NOW)
    run = conn.execute("SELECT status, finished_at, error FROM ingestion_runs").fetchone()
    assert run["status"] == "failed" and run["finished_at"] is not None
    assert run["error"] == "OperationalError"  # class only: an exception message may carry values (C-13)
    assert [c.kind for c in alerts._ingestion(conn, NOW, 7)] == ["ingestion_failed"]


def test_backfill_failure_after_start_marks_the_run_failed(conn, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def boom(*_a: object, **_k: object) -> int:
        raise RuntimeError("bad")

    monkeypatch.setattr(ing, "_store_observations", boom)
    with pytest.raises(RuntimeError):
        ing.backfill_history(conn, fetcher(amfi), scheme_code=928470, mf_id=9, start=date(2026, 10, 13),
                             end=date(2026, 10, 14), now=lambda: NOW)  # fmt: skip
    assert tuple(conn.execute("SELECT status, error FROM ingestion_runs").fetchone()) == ("failed", "RuntimeError")


def test_runs_left_running_by_a_previous_process_are_marked_interrupted(conn) -> None:  # type: ignore[no-untyped-def]
    from iip.services import alerts

    conn.execute("INSERT INTO ingestion_runs(run_id, source_id, started_at, status) VALUES"
                 " ('run_old', 'amfi.navall', ?, 'running')", (NOW.isoformat(),))  # fmt: skip
    assert ing.mark_interrupted_runs(conn, NOW) == 1
    row = conn.execute("SELECT status, finished_at, error FROM ingestion_runs").fetchone()
    assert row["status"] == "failed" and row["finished_at"] == NOW.isoformat()
    assert row["error"] == ing.INTERRUPTED
    alert = alerts._ingestion(conn, NOW, 7)
    assert [c.kind for c in alert] == ["ingestion_failed"] and "interrupted" in alert[0].message
    assert ing.mark_interrupted_runs(conn, NOW) == 0
