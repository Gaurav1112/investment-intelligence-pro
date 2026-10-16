"""POLL-1: J2 runs the official-source polls (RBI T-bill RSS, MoSPI CPI) and reports done / noop / failed honestly.

Hermetic: the B03 cron harness (MockTransport, fake clock and monotonic, SQLite and libSQL). Every NAV, feed, release
and CPI record is SYNTHETIC (fictional schemes, prices, index values).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

from iip.data.fetch import Fetcher
from iip.services import cron, official_polls
from iip.services.official_polls import PollOutcome
from tests.data.test_mospi_base2024 import ROW_2024, doc
from tests.data.test_rbi_tbill import TITLE, feed, item, release_html

from .test_cron import DRIVERS, J1_TIME, J5_TIME, NAV_DATE, Amfi, Clock, ctx_for, hooks, open_conn, run_row

LATER = Clock(J1_TIME + timedelta(hours=1))


@pytest.fixture(params=DRIVERS)
def conn(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = open_conn(tmp_path / "cron.db", request.param)
    yield c
    c.close()


Step = Callable[[sqlite3.Connection, Fetcher, Callable[[], datetime]], PollOutcome]


def step(outcome: PollOutcome, calls: list[str] | None = None) -> Step:
    def run(c: sqlite3.Connection, f: Fetcher, now: Callable[[], datetime]) -> PollOutcome:
        if calls is not None:
            calls.append(outcome.code)
        return outcome

    return run


def test_default_hooks_wire_both_official_polls() -> None:
    polls = dict(cron.default_hooks().polls)
    assert polls == {"rbi.tbill": official_polls.poll_rbi_tbill, "mospi.cpi": official_polls.poll_mospi_cpi}


def test_j2_with_nothing_new_anywhere_is_a_noop(conn: sqlite3.Connection) -> None:
    assert cron.run_job(ctx_for(conn, Amfi()), "navall").state == "done"
    h = hooks(polls=(("rbi.tbill", step(PollOutcome("noop", "NOT_MODIFIED"))),
                     ("mospi.cpi", step(PollOutcome("noop", "UP_TO_DATE")))))  # fmt: skip
    res = cron.run_job(ctx_for(conn, Amfi(), h, clock=LATER), "navall-continue")
    assert res.state == "noop", res.as_dict()
    assert res.steps == {"navall": "UNCHANGED", "rbi.tbill": "NOT_MODIFIED", "mospi.cpi": "UP_TO_DATE"}
    assert run_row(conn, "navall-continue", NAV_DATE)["state"] == "noop"  # type: ignore[index]


def test_j2_is_done_when_a_poll_stored_something(conn: sqlite3.Connection) -> None:
    assert cron.run_job(ctx_for(conn, Amfi()), "navall").state == "done"
    h = hooks(polls=(("rbi.tbill", step(PollOutcome("done", "STORED", {"stored": 3}))),
                     ("mospi.cpi", step(PollOutcome("noop", "UP_TO_DATE")))))  # fmt: skip
    res = cron.run_job(ctx_for(conn, Amfi(), h, clock=LATER), "navall-continue")
    assert (res.state, res.steps["rbi.tbill"], res.counts["rbi.tbill.stored"]) == ("done", "STORED", 3)
    assert run_row(conn, "navall-continue", NAV_DATE)["state"] == "done"  # type: ignore[index]


def test_a_failed_poll_outcome_fails_j2_and_is_retried(conn: sqlite3.Connection) -> None:
    calls: list[str] = []
    bad = PollOutcome("failed", "ABSTAINED:SELF_CHECK_MISMATCH", {"abstained": 1})
    h = hooks(polls=(("rbi.tbill", step(bad, calls)), ("mospi.cpi", step(PollOutcome("noop", "UP_TO_DATE")))))
    res = cron.run_job(ctx_for(conn, Amfi(), h), "navall-continue")
    assert (res.state, res.code) == ("failed", "POLL_FAILED")
    assert res.steps["rbi.tbill"] == "ABSTAINED:SELF_CHECK_MISMATCH" and res.counts["rbi.tbill.abstained"] == 1
    row = run_row(conn, "navall-continue", NAV_DATE)
    assert row is not None and row["state"] == "failed" and "SELF_CHECK_MISMATCH" in row["detail_code"]
    again = cron.run_job(ctx_for(conn, Amfi(), h, clock=LATER), "navall-continue")
    assert again.state == "failed" and calls == [bad.code, bad.code]  # a failed run is taken over and retried


# ----------------------------------------------------------------------------------------------------- end to end

# SYNTHETIC: fictional prices; yields from the self-check formula; release dated the NAV date of the harness.
PRICES = ("98.6000", "97.1000", "94.2000")
YIELDS = ("5.6951", "5.9896", "6.1740")


class Everything(Amfi):
    """AMFI (from the harness) plus RBI's feed and MoSPI's CPI API, all synthetic."""

    def __init__(self) -> None:
        super().__init__()
        self.rbi = 0
        self.mospi = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.rbi.org.in":
            self.rbi += 1
            body = feed(item(TITLE, 9101, release_html(PRICES, YIELDS, date_line="Oct 14, 2026", ref="2026-2027/9101"),
                             pub="Wed, 14 Oct 2026 17:00:00"))  # fmt: skip
            return httpx.Response(200, headers={"content-type": "text/xml"}, content=body)
        if request.url.host == "api.mospi.gov.in":
            self.mospi += 1
            row = {**ROW_2024, "year": "2026", "month": "September", "index": "123.45", "inflation": "3.21"}
            return httpx.Response(200, headers={"content-type": "application/json"},
                                  content=json.dumps(doc(row)).encode())  # fmt: skip
        return super().__call__(request)


def test_j2_runs_the_real_polls_end_to_end_and_reports_no_missing_step(conn: sqlite3.Connection) -> None:
    source = Everything()
    h = hooks(polls=cron.default_hooks().polls)
    res = cron.run_job(ctx_for(conn, source, h, clock=LATER), "navall-continue")
    assert res.state == "done", res.as_dict()
    assert res.steps == {"navall": "STORED", "rbi.tbill": "STORED", "mospi.cpi": "STORED"}
    assert res.counts["rbi.tbill.stored"] == 3 and res.counts["mospi.cpi.stored"] == 1
    assert source.rbi == 1 and source.mospi == 1
    row = run_row(conn, "navall-continue", NAV_DATE)
    assert row is not None and row["state"] == "done" and cron.POLLS_NOT_IMPLEMENTED not in row["detail_code"]
    got = {r["series_id"]: r["value"] for r in conn.execute(
        "SELECT series_id, value FROM observations WHERE source_id IN ('rbi.pr.tbill', 'mospi.cpi')"
    )}  # fmt: skip
    assert got == {
        "riskfree:tbill91": "0.056951", "riskfree:tbill182": "0.059896", "riskfree:tbill364": "0.06174",
        "cpi:all-india:base2024": "123.45", "cpi-yoy:all-india:base2024": "3.21",
    }  # fmt: skip
    wd = cron.run_job(ctx_for(conn, source, hooks(), clock=Clock(J5_TIME)), "watchdog")
    assert "STEP_NOT_IMPLEMENTED" not in wd.steps and "JOB_FAILED" not in wd.steps
