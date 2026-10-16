"""ECC silent-failure-hunter-02/06: a scheduled-job failure, and a poll step that is not built, are VISIBLE - a
failed (or never 'done') cron_runs row that J5 reports, and a failed ingestion run that Data health and the
"ingestion run failed" alert show. On SQLite and libSQL; synthetic fixtures only."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from iip.services import cron
from iip.services import ingestion as ing

from .conftest import navall_codes, watch_schemes
from .test_cron import DRIVERS, J1_TIME, J5_TIME, NAV_DATE, Amfi, Clock, ctx_for, hooks, open_conn, run_row

ATTEMPT = f"attempt:{J1_TIME.date().isoformat()}"  # 06:40 IST on the same calendar day


@pytest.fixture(params=DRIVERS)
def conn(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = open_conn(tmp_path / "cron.db", request.param)
    yield c
    c.close()


class Down(Amfi):
    def __call__(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)


def _last_run(c: sqlite3.Connection, source: str) -> dict[str, Any] | None:
    r = c.execute(
        "SELECT status, error FROM ingestion_runs WHERE source_id=? ORDER BY started_at DESC, run_id DESC LIMIT 1",
        (source,),
    ).fetchone()
    return None if r is None else dict(r)


def _runs(c: sqlite3.Connection, source: str) -> int:
    return int(c.execute("SELECT COUNT(*) FROM ingestion_runs WHERE source_id=?", (source,)).fetchone()[0])


def test_a_u01_refusal_is_recorded_and_reported_by_the_watchdog(conn: sqlite3.Connection) -> None:
    res = cron.run_job(ctx_for(conn, Amfi(), hooks(navall_scope_enforced=False)), "navall")
    assert (res.state, res.code) == ("failed", "U01_SCOPE_NOT_ENFORCED")
    row = run_row(conn, "navall", ATTEMPT)
    assert row is not None and row["state"] == "failed" and row["detail_code"] == "U01_SCOPE_NOT_ENFORCED"
    wd = cron.run_job(ctx_for(conn, Amfi(), hooks(), clock=Clock(J5_TIME)), "watchdog")
    assert "JOB_FAILED" in wd.steps


def test_a_fetch_failure_shows_in_cron_runs_and_on_data_health(conn: sqlite3.Connection) -> None:
    res = cron.run_job(ctx_for(conn, Down()), "navall")
    assert res.state == "failed" and res.code.startswith("FETCH_FAILED")
    assert run_row(conn, "navall", ATTEMPT)["state"] == "failed"  # type: ignore[index]
    last = _last_run(conn, "amfi.navall")
    assert last is not None and last["status"] == "failed" and last["error"].startswith("CRON_NAVALL: FETCH_FAILED")
    again = cron.run_job(ctx_for(conn, Down(), clock=Clock(J1_TIME + timedelta(hours=1))), "navall-continue")
    assert again.state == "failed" and run_row(conn, "navall-continue", ATTEMPT)["state"] == "failed"  # type: ignore[index]


def test_a_late_nav_failure_in_j4_is_recorded(conn: sqlite3.Connection) -> None:
    cron.run_job(ctx_for(conn, Down(), hooks(snapshot=None), clock=Clock(J1_TIME + timedelta(hours=4))), "snapshot")
    assert run_row(conn, "snapshot", ATTEMPT)["state"] == "failed"  # type: ignore[index]


def test_an_internal_error_before_the_claim_is_recorded(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    def crash(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("synthetic")

    monkeypatch.setattr(cron, "newest_nav_date", crash)
    res = cron.run_job(ctx_for(conn, Amfi()), "history")
    assert (res.state, res.code) == ("failed", "INTERNAL_ERROR")
    row = run_row(conn, "history", ATTEMPT)
    assert row is not None and (row["state"], row["detail_code"]) == ("failed", "INTERNAL_ERROR")


def test_missing_polls_make_j2_partial_never_done_and_are_reported(conn: sqlite3.Connection) -> None:
    watch_schemes(conn, navall_codes()[:2])
    h = hooks(polls=cron.default_hooks().polls)  # production: neither poll is built yet
    assert all(step is None for _, step in h.polls)
    res = cron.run_job(ctx_for(conn, Amfi(), h), "navall-continue")
    assert (res.state, res.code) == ("partial", "POLLS_NOT_IMPLEMENTED")
    assert res.steps["navall"] == "STORED" and res.steps["rbi.tbill"] == res.steps["mospi.cpi"] == "NOT_IMPLEMENTED"
    row = run_row(conn, "navall-continue", NAV_DATE)
    assert row is not None and row["state"] != "done" and row["detail_code"].startswith("POLLS_NOT_IMPLEMENTED")
    for source in ("rbi.pr.tbill", "mospi.cpi"):  # Data health's last run for the source says so
        assert _last_run(conn, source) == {"status": "failed", "error": cron.NOT_IMPLEMENTED_RUN}
    dup = cron.run_job(ctx_for(conn, Amfi(), h), "navall-continue")
    assert (dup.state, dup.code) == ("noop", "DUPLICATE")
    wd = cron.run_job(ctx_for(conn, Amfi(), hooks(), clock=Clock(J5_TIME)), "watchdog")
    assert wd.code == "ATTENTION" and "STEP_NOT_IMPLEMENTED" in wd.steps


def test_a_standing_missing_poll_is_recorded_once_not_daily(conn: sqlite3.Connection) -> None:
    for day in range(3):
        at = Clock(J1_TIME + timedelta(days=day))
        assert ing.record_failed_run(conn, "mospi.cpi", at(), cron.NOT_IMPLEMENTED_RUN, once=True) is (day == 0)
    assert _runs(conn, "mospi.cpi") == 1


def test_a_failure_for_an_unregistered_source_writes_nothing(conn: sqlite3.Connection) -> None:
    assert ing.record_failed_run(conn, "no.such.source", J1_TIME, "X") is False
