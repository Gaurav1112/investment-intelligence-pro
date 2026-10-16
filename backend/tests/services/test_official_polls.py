"""POLL-1: the J2 official-source polls (PLAN B03 with the A07 adapters): RBI T-bill cut-offs and MoSPI CPI.

Hermetic: a fake transport (httpx.MockTransport), a fixed clock, a temporary SQLite store. Every feed, release page
and CPI record is SYNTHETIC (the layouts of the A07 test fixtures, fictional dates in 2099 and fictional values).

Checked here: conditional fetch state (If-Modified-Since + payload hash, release ids already handled), releases stored
with provenance, the T-bill yield self-check abstaining on a mismatch, the honest user-agent with no credentials, and
honest done / noop / failed outcomes with an ingestion run row for Data health whenever something was stored or failed.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from iip.data.fetch import USER_AGENT, BreakerStatus, Fetcher, RetryPolicy
from iip.services import ingestion, official_polls
from iip.services.official_polls import PollOutcome
from iip.store.db import connect, migrate
from tests.data.test_mospi_base2024 import ROW_2024, doc
from tests.data.test_rbi_tbill import PRICES, TITLE, YIELDS, feed, html_page, item, release_html

RBI_NOW = datetime(2099, 1, 7, 12, 0, tzinfo=UTC)
FEED_LM = "Wed, 07 Jan 2099 11:30:00 GMT"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(tmp_path / "polls.db")
    migrate(c, RBI_NOW.isoformat())
    ingestion.sync_sources(c)
    yield c
    c.close()


class Server:
    """Fake transport: RBI's feed and release pages, MoSPI's CPI API. Records every request."""

    def __init__(self) -> None:
        self.feed_body: bytes = feed()
        self.feed_status = 200
        self.honour_ims = True
        self.pages: dict[int, httpx.Response] = {}
        self.cpi: dict[tuple[int, int], object] = {}  # (year, month) → JSON body
        self.cpi_status = 200
        self.requests: list[httpx.Request] = []

    def __call__(self, r: httpx.Request) -> httpx.Response:
        self.requests.append(r)
        if r.url.host == "api.mospi.gov.in":
            if self.cpi_status != 200:
                return httpx.Response(self.cpi_status)
            key = (int(r.url.params["year"]), int(r.url.params["month_code"]))
            body = self.cpi.get(key, {"data": [], "msg": "No Data Found", "statusCode": False})
            return httpx.Response(200, headers={"content-type": "application/json"}, content=json.dumps(body).encode())
        if r.url.path == "/pressreleases_rss.xml":
            if self.feed_status != 200:
                return httpx.Response(self.feed_status)
            if self.honour_ims and "if-modified-since" in r.headers:
                return httpx.Response(304)
            return httpx.Response(200, headers={"content-type": "text/xml", "last-modified": FEED_LM},
                                  content=self.feed_body)  # fmt: skip
        return self.pages[int(r.url.params["prid"])]

    def paths(self, host: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.host == host]


def fetcher_for(server: Server, now: datetime) -> Fetcher:
    return Fetcher(transport=httpx.MockTransport(server), resolver=lambda _h: ["23.0.0.1"], jitter_seed=1,
                   sleep=lambda _s: None, clock=lambda: now, retry=RetryPolicy(max_attempts=1))  # fmt: skip


def run_rbi(conn: sqlite3.Connection, server: Server, now: datetime = RBI_NOW) -> PollOutcome:
    return official_polls.poll_rbi_tbill(conn, fetcher_for(server, now), lambda: now)


def run_cpi(conn: sqlite3.Connection, server: Server, now: datetime) -> PollOutcome:
    return official_polls.poll_mospi_cpi(conn, fetcher_for(server, now), lambda: now)


def obs(conn: sqlite3.Connection, prefix: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM observations WHERE series_id LIKE ? ORDER BY series_id, observation_date, obs_id",
        (prefix + "%",),
    ).fetchall()
    return [dict(r) for r in rows]


def runs(conn: sqlite3.Connection, source_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT status, rows_ok, rows_rejected, raw_sha256, error FROM ingestion_runs WHERE source_id=?"
        " ORDER BY started_at, run_id",
        (source_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def assert_honest_requests(server: Server) -> None:
    assert server.requests
    for r in server.requests:
        assert r.headers["user-agent"] == USER_AGENT
        assert "authorization" not in r.headers and "cookie" not in r.headers


# ============================================================================================ RBI T-bill


def with_table(prid: int = 9001) -> bytes:
    return feed(item(TITLE, prid, release_html()))


def test_tbill_release_is_stored_with_provenance(conn: sqlite3.Connection) -> None:
    server = Server()
    server.feed_body = with_table()
    out = run_rbi(conn, server)
    assert (out.state, out.code) == ("done", "STORED")
    assert out.counts == {"releases": 1, "stored": 3, "unchanged": 0, "abstained": 0, "page_requests": 0}
    rows = obs(conn, "riskfree:tbill")
    assert [r["series_id"] for r in rows] == ["riskfree:tbill182", "riskfree:tbill364", "riskfree:tbill91"]
    by = {r["series_id"]: r for r in rows}
    assert by["riskfree:tbill91"]["value"] == "0.056951"  # = 5.6951 % as published, self-checked
    for r in rows:
        assert r["source_id"] == "rbi.pr.tbill" and r["quality_status"] == "ok" and r["kind"] == "yield"
        assert r["observation_date"] == "2099-01-07" and r["publication_time"] == "2099-01-07"
        assert r["convention"] == "RBI_TBILL_IMPLICIT_YIELD_AS_PUBLISHED" and r["unit"] == "fraction"
        assert r["raw_sha256"] and r["retrieved_at"] == RBI_NOW.isoformat()
        assert r["source_url"].endswith("prid=9001")
    (run,) = runs(conn, "rbi.pr.tbill")
    assert run["status"] == "ok" and run["rows_ok"] == 3 and run["raw_sha256"] == rows[0]["raw_sha256"]
    prov = official_polls.tbill_provenance(conn)
    assert prov["9001"] == {
        "outcome": "stored", "press_release_ref": "2098-2099/9001", "release_date": "2099-01-07",
        "date_basis": "release_text", "auction_date": None,
        "citation_text": prov["9001"]["citation_text"], "self_check": "PASS",
    }  # fmt: skip
    assert "http" not in prov["9001"]["citation_text"]  # plain text, never a link (RBI disclaimer)
    assert_honest_requests(server)


def test_tbill_second_poll_is_conditional_and_a_noop(conn: sqlite3.Connection) -> None:
    server = Server()
    server.feed_body = with_table()
    assert run_rbi(conn, server).state == "done"
    out = run_rbi(conn, server)
    assert (out.state, out.code) == ("noop", "NOT_MODIFIED")
    second = server.requests[-1]
    assert second.headers["if-modified-since"] == FEED_LM
    assert len(obs(conn, "riskfree:tbill")) == 3 and len(runs(conn, "rbi.pr.tbill")) == 1


def test_tbill_same_feed_without_304_is_unchanged_and_fetches_no_page(conn: sqlite3.Connection) -> None:
    server = Server()
    server.honour_ims = False
    server.feed_body = feed(item(TITLE, 9001, "<p>no table here</p>"))
    server.pages[9001] = html_page(release_html())
    first = run_rbi(conn, server)
    assert (first.state, first.counts["page_requests"]) == ("done", 1)
    again = run_rbi(conn, server)
    assert (again.state, again.code) == ("noop", "UNCHANGED")
    # The feed changed around the same release: the release is known, so its page is not requested again.
    server.feed_body = feed(item("Some other press release", 9002), item(TITLE, 9001, "<p>no table here</p>"))
    changed = run_rbi(conn, server)
    assert (changed.state, changed.code) == ("noop", "NO_NEW_CUTOFF")
    assert len([r for r in server.requests if "prid" in r.url.params]) == 1


def test_tbill_self_check_mismatch_abstains_and_stores_nothing(conn: sqlite3.Connection) -> None:
    bad = list(YIELDS)
    bad[0] = "5.6952"  # one unit off in the 4th decimal: the recomputed yield disagrees
    server = Server()
    server.feed_body = feed(item(TITLE, 9001, release_html(PRICES, tuple(bad))))
    out = run_rbi(conn, server)
    assert (out.state, out.code) == ("failed", "ABSTAINED:SELF_CHECK_MISMATCH")
    assert out.counts["abstained"] == 1 and out.counts["stored"] == 0
    assert obs(conn, "riskfree:tbill") == []
    (run,) = runs(conn, "rbi.pr.tbill")
    assert run["status"] == "failed" and run["error"] == "ABSTAINED:SELF_CHECK_MISMATCH"
    assert official_polls.tbill_provenance(conn)["9001"]["outcome"] == "abstained:SELF_CHECK_MISMATCH"


def test_tbill_mixed_stores_the_good_release_and_reports_the_abstention(conn: sqlite3.Connection) -> None:
    bad = (PRICES[1], PRICES[0], PRICES[2])  # swapped columns fail the self-check
    server = Server()
    server.feed_body = feed(
        item(TITLE, 9001, release_html()),
        item(TITLE, 9002, release_html(bad, (YIELDS[1], YIELDS[0], YIELDS[2]))),
    )
    out = run_rbi(conn, server)
    assert (out.state, out.code) == ("done", "STORED_WITH_ABSTENTIONS")
    assert out.counts["stored"] == 3 and out.counts["abstained"] == 1
    (run,) = runs(conn, "rbi.pr.tbill")
    assert run["status"] == "partial" and run["rows_ok"] == 3 and run["rows_rejected"] == 1


def test_tbill_access_denied_fails_and_trips_the_breaker(conn: sqlite3.Connection) -> None:
    server = Server()
    server.feed_body = feed(item(TITLE, 9001, "<p>no table</p>"))
    server.pages[9001] = html_page("<h1>Unauthorised Access</h1>")
    f = fetcher_for(server, RBI_NOW)
    out = official_polls.poll_rbi_tbill(conn, f, lambda: RBI_NOW)
    assert (out.state, out.code) == ("failed", "ABSTAINED:ACCESS_DENIED")
    assert obs(conn, "riskfree:tbill") == []
    assert f.breaker.state("rbi.pr.tbill").status is BreakerStatus.OPEN  # no evasion, no retry under another identity


def test_tbill_feed_failure_fails_honestly(conn: sqlite3.Connection) -> None:
    server = Server()
    server.feed_status = 500
    out = run_rbi(conn, server)
    assert out.state == "failed" and out.code.startswith("FETCH_FAILED:")
    (run,) = runs(conn, "rbi.pr.tbill")
    assert run["status"] == "failed" and run["error"] == out.code
    # Nothing was learnt: the next poll is unconditional again.
    server.feed_status = 200
    server.feed_body = with_table()
    assert run_rbi(conn, server).state == "done"
    assert "if-modified-since" not in server.requests[-1].headers


def test_tbill_feed_without_a_cutoff_item_is_a_noop(conn: sqlite3.Connection) -> None:
    server = Server()
    server.feed_body = feed(item("Some other press release", 9002))
    out = run_rbi(conn, server)
    assert (out.state, out.code) == ("noop", "NO_CUTOFF_IN_FEED")
    assert runs(conn, "rbi.pr.tbill") == []


# ============================================================================================ MoSPI CPI

AFTER_RELEASE = datetime(2099, 2, 20, 6, 0, tzinfo=UTC)  # 20-Feb 11:30 IST: January's CPI is due (12th, 16:00 IST)
BEFORE_RELEASE = datetime(2099, 2, 12, 10, 0, tzinfo=UTC)  # 12-Feb 15:30 IST: not yet


def cpi_row(year: int, month: str, index: str = "111.11", inflation: str = "2.22") -> dict[str, Any]:
    return {**ROW_2024, "year": str(year), "month": month, "index": index, "inflation": inflation}


def test_cpi_due_month_is_fetched_and_stored_with_provenance(conn: sqlite3.Connection) -> None:
    server = Server()
    server.cpi[(2099, 1)] = doc(cpi_row(2099, "January"))
    out = run_cpi(conn, server, AFTER_RELEASE)
    assert (out.state, out.code) == ("done", "STORED")
    assert out.counts == {"requests": 1, "stored": 1, "unchanged": 0}
    (req,) = server.requests
    assert req.url.path == "/api/cpi/getCPIData" and req.url.params["base_year"] == "2024"
    assert (req.url.params["year"], req.url.params["month_code"]) == ("2099", "1")
    idx = obs(conn, "cpi:all-india:base2024")
    yoy = obs(conn, "cpi-yoy:all-india:base2024")
    assert [(r["observation_date"], r["value"]) for r in idx] == [("2099-01-01", "111.11")]
    assert [r["value"] for r in yoy] == ["2.22"]
    r = idx[0]
    assert r["source_id"] == "mospi.cpi" and r["quality_status"] == "ok" and r["raw_sha256"]
    assert r["source_url"].startswith("https://api.mospi.gov.in/") and r["retrieved_at"] == AFTER_RELEASE.isoformat()
    assert r["convention"] == "CPI_COMBINED_GENERAL_INDEX_BASE2024|PROVISIONAL"  # never invented as final
    (run,) = runs(conn, "mospi.cpi")
    assert run["status"] == "ok" and run["rows_ok"] == 1 and run["raw_sha256"] == r["raw_sha256"]
    assert_honest_requests(server)


def test_cpi_once_stored_the_month_is_up_to_date_without_a_request(conn: sqlite3.Connection) -> None:
    server = Server()
    server.cpi[(2099, 1)] = doc(cpi_row(2099, "January"))
    assert run_cpi(conn, server, AFTER_RELEASE).state == "done"
    out = run_cpi(conn, server, AFTER_RELEASE)
    assert (out.state, out.code) == ("noop", "UP_TO_DATE") and len(server.requests) == 1


def test_cpi_due_month_not_published_yet_is_a_noop_and_rechecks_the_month_before(conn: sqlite3.Connection) -> None:
    server = Server()
    server.cpi[(2098, 12)] = doc(cpi_row(2098, "December"))
    out = run_cpi(conn, server, AFTER_RELEASE)
    assert (out.state, out.code) == ("done", "STORED")
    assert [(r.url.params["year"], r.url.params["month_code"]) for r in server.requests] == [
        ("2099", "1"),
        ("2098", "12"),
    ]
    assert [r["observation_date"] for r in obs(conn, "cpi:all-india:base2024")] == ["2098-12-01"]
    nothing = Server()
    out2 = run_cpi(conn, nothing, AFTER_RELEASE)
    assert (out2.state, out2.code) == ("noop", "NOT_PUBLISHED")


def test_cpi_before_release_day_rechecks_the_month_before_for_revisions(conn: sqlite3.Connection) -> None:
    server = Server()
    server.cpi[(2098, 12)] = doc(cpi_row(2098, "December"))
    assert run_cpi(conn, server, BEFORE_RELEASE).code == "STORED"
    assert [(r.url.params["year"], r.url.params["month_code"]) for r in server.requests] == [("2098", "12")]
    same = run_cpi(conn, server, BEFORE_RELEASE)
    assert (same.state, same.code) == ("noop", "UNCHANGED")
    server.cpi[(2098, 12)] = doc(cpi_row(2098, "December", index="111.50"))  # MoSPI revised the month
    rev = run_cpi(conn, server, BEFORE_RELEASE)
    assert (rev.state, rev.code) == ("done", "STORED")
    rows = obs(conn, "cpi:all-india:base2024")
    assert [r["value"] for r in rows] == ["111.11", "111.50"]  # the revision appends; history is kept
    assert rows[0]["superseded_by"] == rows[1]["obs_id"]


@pytest.mark.parametrize(
    "body",
    [
        doc(cpi_row(2099, "January"), cpi_row(2099, "January")),  # two records where one is expected
        doc(cpi_row(2099, "January"), total=40),  # truncated at the page cap
        doc({**cpi_row(2099, "January"), "state": "Kerala"}),  # not All India
        {"unexpected": True},  # schema surprise
    ],
)
def test_cpi_refuses_anything_but_one_matching_record(conn: sqlite3.Connection, body: object) -> None:
    server = Server()
    server.cpi[(2099, 1)] = body
    out = run_cpi(conn, server, AFTER_RELEASE)
    assert out.state == "failed" and out.code.startswith("REFUSED:")
    assert obs(conn, "cpi") == []
    (run,) = runs(conn, "mospi.cpi")
    assert run["status"] == "failed" and run["error"] == out.code


def test_cpi_fetch_failure_fails_honestly(conn: sqlite3.Connection) -> None:
    server = Server()
    server.cpi_status = 500
    out = run_cpi(conn, server, AFTER_RELEASE)
    assert out.state == "failed" and out.code.startswith("FETCH_FAILED:")
    assert runs(conn, "mospi.cpi")[0]["status"] == "failed"


def test_outcome_codes_carry_no_values() -> None:
    """C-13: outcomes are codes and integer counts only."""
    o = PollOutcome("done", "STORED", {"stored": 3})
    assert o.as_counts() == {"stored": 3}


def test_poll_steps_have_the_cron_signature() -> None:
    step: Callable[[sqlite3.Connection, Fetcher, Callable[[], datetime]], PollOutcome]
    step = official_polls.poll_rbi_tbill
    step = official_polls.poll_mospi_cpi
    assert callable(step)
