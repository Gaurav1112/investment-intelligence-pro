"""PLAN B03: the cron route and jobs J1-J5, on SQLite AND libSQL, hermetic (MockTransport, fake clock and monotonic).

Covers the acceptance checks: stale-``running`` takeover; the outbox reaper never resends; a duplicate delivery is a
no-op; the run_key is derived (from the data, not the clock) AFTER a cheap conditional fetch; each job is one bounded,
resumable step that catches up since the last success; production only. Every scheme code, name and NAV comes from the
SYNTHETIC fixtures (fictional AMCs and codes); no real market data."""

from __future__ import annotations

import secrets
import sqlite3
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from starlette.testclient import TestClient

from iip.data.fetch import CircuitBreaker, Fetcher
from iip.services import cron
from iip.services import ingestion as ing
from iip.store import coordination
from iip.store import ledger as lg
from iip.store.coordination import DbLease
from iip.store.db import connect, connect_libsql, migrate
from tests.data.conftest import load_fixture
from tests.data.test_fetch import PUBLIC_IP
from tests.services.test_portfolio import nav

from .conftest import ORIGIN, TOKEN, hosted_settings, make_client, state

NAVALL = load_fixture("amfi_navall_excerpt.txt")  # synthetic; newest NAV date 14-Oct-2026
HISTORY = load_fixture("amfi_navhistory_excerpt.txt")  # synthetic; 13/14-Oct-2026, fictional "Halcyon Mutual Fund"
NAV_DATE = "2026-10-14"
J1_TIME = datetime(2026, 10, 15, 1, 10, tzinfo=UTC)  # 06:40 IST, inside J1's hour
LAST_MODIFIED = datetime(2026, 10, 14, 17, 0, tzinfo=UTC)
DRIVERS = ("sqlite", "libsql")
DEPLOY = "iip-b03test-owner.vercel.app"
HALCYON = "Halcyon Mutual Fund"
CODE_A, CODE_B = 971181, 928470  # fictional codes present in the synthetic NAV-history fixture


# ----------------------------------------------------------------------------------------------------- harness


class Clock:
    def __init__(self, t: datetime = J1_TIME) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t


class Mono:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class Amfi:
    """Synthetic AMFI: NAVAll (optionally with Last-Modified and 304 on a conditional GET) and NAV history."""

    def __init__(self, *, last_modified: datetime | None = None, body: bytes = NAVALL) -> None:
        self.last_modified = last_modified
        self.body = body
        self.navall_gets = 0
        self.conditional = 0
        self.history_gets = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.amfiindia.com":
            return httpx.Response(302, headers={"location": "https://portal.amfiindia.com/spages/NAVAll.txt"})
        if "NAVHistory" in request.url.path:
            self.history_gets += 1
            return httpx.Response(200, headers={"content-type": "text/plain"}, content=HISTORY)
        self.navall_gets += 1
        if "if-modified-since" in request.headers:
            self.conditional += 1
            if self.last_modified is not None:
                return httpx.Response(304)
        headers = {"content-type": "text/plain"}
        if self.last_modified is not None:
            headers["last-modified"] = format_datetime(self.last_modified, usegmt=True)
        return httpx.Response(200, headers=headers, content=self.body)


def make_fetcher(handler: Amfi) -> Callable[[], Fetcher]:
    breaker = CircuitBreaker(clock=lambda: J1_TIME)
    return lambda: Fetcher(
        transport=httpx.MockTransport(handler), resolver=lambda _h: [PUBLIC_IP], jitter_seed=1,
        sleep=lambda _s: None, clock=lambda: J1_TIME, breaker=breaker,
    )  # fmt: skip


class Sent:
    def __init__(self, fail: bool = False) -> None:
        self.rows: list[tuple[str, str, str]] = []
        self.fail = fail

    def __call__(self, row: sqlite3.Row) -> None:
        if self.fail:
            raise RuntimeError("synthetic send failure")
        self.rows.append((str(row["outbox_key"]), str(row["channel"]), str(row["kind"])))


def hooks(**kw: Any) -> cron.CronHooks:
    base: dict[str, Any] = {"navall_scope_enforced": True, "channels": ("owner-test",), "sender": Sent()}
    return cron.CronHooks(**{**base, **kw})


def open_conn(path: Path, driver: str) -> sqlite3.Connection:
    c = connect_libsql(str(path), hosted=True) if driver == "libsql" else connect(path)
    migrate(c, J1_TIME.isoformat())
    ing.sync_sources(c)
    return c


@pytest.fixture(params=DRIVERS)
def conn(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = open_conn(tmp_path / "cron.db", request.param)
    yield c
    c.close()


def ctx_for(
    conn: sqlite3.Connection, amfi: Amfi, h: cron.CronHooks | None = None, *, clock: Clock | None = None,
    budget: float = 90.0, mono: Mono | None = None,
) -> cron.CronContext:  # fmt: skip
    return cron.CronContext(
        conn=conn, fetcher=make_fetcher(amfi), now=clock or Clock(), monotonic=mono or Mono(), budget_s=budget,
        navall_lock=threading.Lock(), backfill_lock=threading.Lock(), pause=None, hooks=h or hooks(),
    )  # fmt: skip


def run_row(conn: sqlite3.Connection, job: str, key: str) -> dict[str, Any] | None:
    r = conn.execute("SELECT * FROM cron_runs WHERE job=? AND run_key=?", (job, key)).fetchone()
    return None if r is None else dict(r)


def obs_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0])


def outbox(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    return [(r["outbox_key"], r["kind"], r["state"]) for r in conn.execute(
        "SELECT outbox_key, kind, state FROM notification_outbox ORDER BY outbox_key")]  # fmt: skip


# ----------------------------------------------------------------------------------------------------- J1


def test_j1_fetches_then_keys_the_run_on_the_data_date_then_claims_and_stores(conn: sqlite3.Connection) -> None:
    amfi = Amfi()
    res = cron.run_job(ctx_for(conn, amfi, clock=Clock(J1_TIME + timedelta(days=2))), "navall")
    assert (res.state, res.code, res.run_key) == ("done", "STORED", NAV_DATE)  # data date, not the clock's date
    row = run_row(conn, "navall", NAV_DATE)
    assert row is not None and row["state"] == "done" and row["attempts"] == 1 and row["detail_code"] == "STORED"
    assert obs_count(conn) > 0 and amfi.navall_gets == 1
    assert coordination.load_job(conn, ing.NAVALL_JOB) is None and coordination.load_job(conn, cron.NAVALL_OPEN) is None


def test_j1_duplicate_delivery_is_a_noop_after_a_304(conn: sqlite3.Connection) -> None:
    amfi = Amfi(last_modified=LAST_MODIFIED)
    assert cron.run_job(ctx_for(conn, amfi), "navall").code == "STORED"
    before = obs_count(conn)
    res = cron.run_job(ctx_for(conn, amfi), "navall")
    assert (res.state, res.code, res.run_key) == ("noop", "NOT_MODIFIED", NAV_DATE)
    assert amfi.conditional == 1 and obs_count(conn) == before
    assert run_row(conn, "navall", NAV_DATE)["attempts"] == 1  # type: ignore[index]


def test_j1_duplicate_delivery_without_validators_is_still_a_noop(conn: sqlite3.Connection) -> None:
    amfi = Amfi()  # no Last-Modified: every call is a full GET (accepted, documented)
    assert cron.run_job(ctx_for(conn, amfi), "navall").code == "STORED"
    assert cron.run_job(ctx_for(conn, amfi), "navall").code == "UNCHANGED"  # same bytes
    coordination.clear_job(conn, cron.NAVALL_LAST)  # even without the hash, the claim refuses a finished run
    res = cron.run_job(ctx_for(conn, amfi), "navall")
    assert (res.state, res.code) == ("noop", "DUPLICATE")
    assert run_row(conn, "navall", NAV_DATE)["attempts"] == 1  # type: ignore[index]
    assert conn.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0] == 1


def _seed_run(conn: sqlite3.Connection, job: str, key: str, state_: str, started: datetime) -> None:
    conn.execute(
        "INSERT INTO cron_runs(job, run_key, state, attempts, started_at) VALUES (?, ?, ?, 1, ?)",
        (job, key, state_, started.isoformat()),
    )


def test_stale_running_claim_is_taken_over(conn: sqlite3.Connection) -> None:
    _seed_run(conn, "navall", NAV_DATE, "running", J1_TIME - timedelta(seconds=cron.CLAIM_STALE_S + 70))
    res = cron.run_job(ctx_for(conn, Amfi()), "navall")
    assert (res.state, res.code) == ("done", "STORED")
    row = run_row(conn, "navall", NAV_DATE)
    assert row is not None and row["state"] == "done" and row["attempts"] == 2


def test_live_running_claim_makes_a_duplicate_a_noop(conn: sqlite3.Connection) -> None:
    _seed_run(conn, "navall", NAV_DATE, "running", J1_TIME - timedelta(seconds=10))
    res = cron.run_job(ctx_for(conn, Amfi()), "navall")
    assert (res.state, res.code) == ("noop", "DUPLICATE")
    assert run_row(conn, "navall", NAV_DATE)["attempts"] == 1  # type: ignore[index]
    assert obs_count(conn) == 0


def test_failed_run_is_retried_by_the_next_delivery(conn: sqlite3.Connection) -> None:
    _seed_run(conn, "navall", NAV_DATE, "failed", J1_TIME - timedelta(seconds=5))
    assert cron.run_job(ctx_for(conn, Amfi()), "navall").code == "STORED"
    assert run_row(conn, "navall", NAV_DATE)["attempts"] == 2  # type: ignore[index]


def test_two_concurrent_deliveries_have_exactly_one_owner(tmp_path: Path) -> None:
    db = tmp_path / "race.db"
    open_conn(db, "libsql").close()
    results: list[cron.CronResult] = []
    barrier = threading.Barrier(2)
    amfi = Amfi()

    def deliver() -> None:
        c = connect_libsql(str(db), hosted=True)
        clock = Clock()
        ctx = ctx_for(c, amfi)
        ctx.navall_lock = DbLease(lambda: c, "navall", ttl_s=330, clock=lambda: clock().timestamp())
        barrier.wait(5)
        results.append(cron.run_job(ctx, "navall"))
        c.close()

    threads = [threading.Thread(target=deliver) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r.state for r in results) == ["done", "noop"]
    c = connect_libsql(str(db), hosted=True)
    assert c.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0] == 1
    assert run_row(c, "navall", NAV_DATE)["attempts"] == 1  # type: ignore[index]


def test_hosted_navall_fails_closed_until_the_u01_scope_is_enforced(conn: sqlite3.Connection) -> None:
    amfi = Amfi()
    res = cron.run_job(ctx_for(conn, amfi, hooks(navall_scope_enforced=False)), "navall")
    assert (res.state, res.code) == ("failed", "U01_SCOPE_NOT_ENFORCED")
    assert amfi.navall_gets == 0 and obs_count(conn) == 0


def test_unknown_job_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown job"):
        cron.run_job(None, "navall; DROP")  # type: ignore[arg-type]


def test_step_never_exceeds_the_90_second_limit(conn: sqlite3.Connection) -> None:
    mono = Mono()
    ctx = ctx_for(conn, Amfi(), budget=280.0, mono=mono)
    ctx.start()
    assert ctx.remaining() == cron.STEP_LIMIT_S == 90.0


# ----------------------------------------------------------------------------------------------------- J2


def test_a_crash_mid_step_resumes_and_j2_finishes_the_open_run(conn: sqlite3.Connection) -> None:
    amfi = Amfi()
    first = cron.run_job(ctx_for(conn, amfi, budget=0.0), "navall")  # the fetch and staging only
    assert (first.state, first.code, first.run_key) == ("partial", "NAVALL_STORING", NAV_DATE)
    assert run_row(conn, "navall", NAV_DATE)["state"] == "running"  # type: ignore[index]
    res = cron.run_job(ctx_for(conn, amfi, clock=Clock(J1_TIME + timedelta(hours=1))), "navall-continue")
    assert res.state == "done" and res.steps["navall"] == "STORED"
    assert amfi.navall_gets == 1  # the continuation never fetched again
    assert run_row(conn, "navall", NAV_DATE)["state"] == "done"  # type: ignore[index]
    assert run_row(conn, "navall-continue", NAV_DATE)["state"] == "done"  # type: ignore[index]
    assert obs_count(conn) > 0


def test_a_missed_j1_is_caught_up_by_j2(conn: sqlite3.Connection) -> None:
    res = cron.run_job(ctx_for(conn, Amfi(), clock=Clock(J1_TIME + timedelta(hours=1))), "navall-continue")
    assert res.state == "done" and res.run_key == NAV_DATE and res.steps["navall"] == "STORED"
    assert run_row(conn, "navall", NAV_DATE)["state"] == "done"  # type: ignore[index]


def test_j2_polls_run_once_per_nav_date_and_report_missing_steps(conn: sqlite3.Connection) -> None:
    calls: list[str] = []

    def poll(c: sqlite3.Connection, f: Fetcher, now: Callable[[], datetime]) -> dict[str, int]:
        calls.append("rbi")
        return {"stored": 2}

    h = hooks(polls=(("rbi.tbill", poll), ("mospi.cpi", None)))
    res = cron.run_job(ctx_for(conn, Amfi(), h), "navall-continue")
    assert res.steps == {"navall": "STORED", "rbi.tbill": "OK", "mospi.cpi": "NOT_IMPLEMENTED"}
    assert res.counts["rbi.tbill.stored"] == 2
    dup = cron.run_job(ctx_for(conn, Amfi(), h), "navall-continue")
    assert (dup.state, dup.code) == ("noop", "DUPLICATE") and calls == ["rbi"]


def test_j2_poll_failure_marks_the_run_failed_so_the_next_delivery_retries(conn: sqlite3.Connection) -> None:
    def boom(c: sqlite3.Connection, f: Fetcher, now: Callable[[], datetime]) -> dict[str, int]:
        raise RuntimeError("synthetic")

    res = cron.run_job(ctx_for(conn, Amfi(), hooks(polls=(("rbi.tbill", boom),))), "navall-continue")
    assert (res.state, res.code, res.steps["rbi.tbill"]) == ("failed", "POLL_FAILED", "FAILED")
    assert run_row(conn, "navall-continue", NAV_DATE)["state"] == "failed"  # type: ignore[index]


# ----------------------------------------------------------------------------------------------------- J3


def test_gap_window_rules() -> None:
    assert cron.gap_window({}, None, "2026-10-12") is None
    assert cron.gap_window({1: "2026-10-01"}, "2026-10-09", "2026-10-12") is None  # Fri → Mon: J1 stored Monday
    assert cron.gap_window({1: "2026-10-01"}, "2026-10-08", "2026-10-12") == (date(2026, 10, 9), date(2026, 10, 12))
    assert cron.gap_window({1: "2026-10-01", 2: "2026-10-11"}, None, "2026-10-14") == (
        date(2026, 10, 2), date(2026, 10, 14))  # fmt: skip
    capped = cron.gap_window({}, "2025-01-01", "2026-10-14")
    assert capped == (date(2026, 10, 14) - timedelta(days=cron.GAP_FILL_MAX_DAYS), date(2026, 10, 14))


def _seed_halcyon(conn: sqlite3.Connection) -> None:
    for code in (CODE_A, CODE_B):
        conn.execute(
            "INSERT INTO instruments(instrument_id, kind, name, amfi_code, origin, created_at)"
            " VALUES (?, 'mf_scheme', ?, ?, 'fixture', ?)",
            (f"mf:{code}", f"Fictional scheme {code}", str(code), J1_TIME.isoformat()),
        )
        conn.execute(
            "INSERT INTO mf_schemes(instrument_id, amc, category_raw, plan) VALUES (?, ?, 'Equity', 'direct')",
            (f"mf:{code}", HALCYON),
        )
        conn.execute(
            "INSERT INTO watchlist(instrument_id, added_at) VALUES (?, ?)", (f"mf:{code}", J1_TIME.isoformat())
        )
    conn.execute("INSERT INTO settings(key, value_json) VALUES (?, '7')", (f"amfi.mf_id:{HALCYON.lower()}",))
    for d, v in (("2026-08-31", "17.000"), ("2026-09-30", "17.500"), ("2026-10-01", "17.600")):
        nav(conn, CODE_A, d, v)
    nav(conn, CODE_B, "2026-10-14", "1385.402")


def test_j3_fills_the_gap_since_the_last_success_then_refreshes_the_grid(conn: sqlite3.Connection) -> None:
    _seed_halcyon(conn)
    amfi = Amfi()
    res = cron.run_job(ctx_for(conn, amfi), "history")
    assert (res.state, res.code, res.run_key) == ("done", "GAP_FILLED", NAV_DATE)
    assert amfi.history_gets == 1 and res.counts["windows_done"] == res.counts["windows_total"] == 1
    got = {r["observation_date"] for r in conn.execute(
        "SELECT observation_date FROM observations WHERE series_id=?", (f"nav:{CODE_A}",))}  # fmt: skip
    assert {"2026-10-13", "2026-10-14"} <= got
    grid = lg.series_grid(conn, [f"mf:{CODE_A}", f"mf:{CODE_B}"])
    assert [m for m, _ in grid[f"mf:{CODE_A}"]] == ["2026-08", "2026-09"]  # October is still open: trimmed
    assert grid[f"mf:{CODE_B}"] == [] and res.counts["grid_skipped"] == 1  # no valid month-end yet: not guessed
    assert run_row(conn, "history", NAV_DATE)["state"] == "done"  # type: ignore[index]
    dup = cron.run_job(ctx_for(conn, amfi), "history")
    assert (dup.state, dup.code) == ("noop", "DUPLICATE") and amfi.history_gets == 1


def test_j3_next_day_without_a_gap_fetches_nothing(conn: sqlite3.Connection) -> None:
    _seed_halcyon(conn)
    amfi = Amfi()
    cron.run_job(ctx_for(conn, amfi), "history")
    nav(conn, CODE_B, "2026-10-15", "1390.000")  # J1 stored the next day's NAV
    res = cron.run_job(ctx_for(conn, amfi, clock=Clock(J1_TIME + timedelta(days=1))), "history")
    assert (res.state, res.code, res.run_key) == ("done", "NO_GAP", "2026-10-15") and amfi.history_gets == 1


def test_j3_resumes_a_partial_gap_fill(conn: sqlite3.Connection) -> None:
    _seed_halcyon(conn)
    coordination.save_job(conn, cron.HISTORY_LAST, {"run_key": "2026-07-01"}, J1_TIME.isoformat())
    amfi = Amfi()
    first = cron.run_job(ctx_for(conn, amfi, budget=0.0), "history")  # one window per step, then stop
    assert (first.state, first.code) == ("partial", "GAP_FILLING") and amfi.history_gets == 1
    second = cron.run_job(ctx_for(conn, amfi), "history")
    assert (second.state, second.code) == ("done", "GAP_FILLED") and amfi.history_gets == 2
    assert run_row(conn, "history", NAV_DATE)["attempts"] == 1  # type: ignore[index]


def test_grid_refresh_skips_conflicting_navs(conn: sqlite3.Connection) -> None:
    _seed_halcyon(conn)
    conn.execute(
        "INSERT INTO observations(series_id, kind, value, unit, currency, observation_date, retrieved_at, source_id,"
        " source_url, quality_status, raw_sha256) VALUES (?, 'nav', '99.000', 'INR/unit', 'INR', '2026-09-30', ?,"
        " 'amfi.navhistory', 'https://example.test/synthetic', 'ok', ?)",
        (f"nav:{CODE_A}", J1_TIME.isoformat(), "b" * 64),
    )
    points, skipped = cron.refresh_series_grid(conn, [CODE_A], J1_TIME.isoformat())
    assert (points, skipped) == (0, 1)


# ----------------------------------------------------------------------------------------------------- J4


def fake_snapshot(cards: str) -> cron.SnapshotStep:
    """A stand-in for B02's step: content-addressed, ABSTAIN stored too (identifiers only, no values)."""

    def step(c: sqlite3.Connection, now: datetime) -> cron.SnapshotOutcome:
        as_of = cron.newest_nav_date(c) or ""
        sid = f"snap-{as_of}-{cards}"
        written = lg.put_snapshot(c, lg.SignalSnapshot(sid, as_of, "e1", "r1", f"m-{as_of}", "ABSTAIN",
                                                       f"cards-{cards}", '{"cards":[]}', now.isoformat()))  # fmt: skip
        return cron.SnapshotOutcome(sid, as_of, "ABSTAIN", f"cards-{cards}", written)

    return step


def _j4(conn: sqlite3.Connection, amfi: Amfi, cards: str, sent: Sent, day: int = 0) -> cron.CronResult:
    at = Clock(J1_TIME + timedelta(hours=4, days=day))
    return cron.run_job(ctx_for(conn, amfi, hooks(snapshot=fake_snapshot(cards), sender=sent), clock=at), "snapshot")


def test_j4_stores_the_snapshot_and_pings_once_only_when_the_card_set_changes(conn: sqlite3.Connection) -> None:
    amfi = Amfi(last_modified=LAST_MODIFIED)
    cron.run_job(ctx_for(conn, amfi), "navall")
    sent = Sent()
    res = _j4(conn, amfi, "A", sent)
    assert (res.state, res.code, res.run_key) == ("done", "SNAPSHOT_STORED", NAV_DATE)
    assert res.steps == {"late_navs": "NOT_MODIFIED", "verdict": "ABSTAIN"}
    assert res.counts["pings_queued"] == 1 and sent.rows == [(f"snap-{NAV_DATE}-A", "owner-test", "report")]
    dup = _j4(conn, amfi, "A", sent)
    assert (dup.state, dup.code) == ("noop", "DUPLICATE") and len(sent.rows) == 1
    # Next NAV date, same card set: a new snapshot, but a quiet day sends nothing.
    nav(conn, CODE_A, "2026-10-15", "18.000")
    same = _j4(conn, amfi, "A", sent, day=1)
    assert same.code == "SNAPSHOT_STORED" and same.counts["pings_queued"] == 0 and len(sent.rows) == 1
    nav(conn, CODE_A, "2026-10-16", "18.100")
    changed = _j4(conn, amfi, "B", sent, day=2)
    assert changed.counts["pings_queued"] == 1 and len(sent.rows) == 2
    assert all(s == "sent" for _, _, s in outbox(conn))


def test_j4_without_the_snapshot_step_fails_closed(conn: sqlite3.Connection) -> None:
    amfi = Amfi(last_modified=LAST_MODIFIED)
    cron.run_job(ctx_for(conn, amfi), "navall")
    res = cron.run_job(ctx_for(conn, amfi, hooks(snapshot=None)), "snapshot")
    assert (res.state, res.code) == ("failed", "SNAPSHOT_NOT_IMPLEMENTED")
    assert conn.execute("SELECT COUNT(*) FROM signal_snapshots").fetchone()[0] == 0 and outbox(conn) == []


def test_j4_restores_late_navs_for_a_finished_nav_date(conn: sqlite3.Connection) -> None:
    amfi = Amfi()
    cron.run_job(ctx_for(conn, amfi), "navall")
    amfi.body = NAVALL + b"\r\n"  # the file changed later in the day (late FoF NAVs), same newest NAV date
    res = cron.run_job(ctx_for(conn, amfi, hooks(snapshot=fake_snapshot("A"))), "snapshot")
    assert res.steps["late_navs"] == "LATE_NAVS_STORED" and res.code == "SNAPSHOT_STORED"
    assert run_row(conn, "navall", NAV_DATE)["attempts"] == 1  # type: ignore[index]


def test_no_channel_means_no_outbox_row(conn: sqlite3.Connection) -> None:
    amfi = Amfi(last_modified=LAST_MODIFIED)
    cron.run_job(ctx_for(conn, amfi), "navall")
    res = cron.run_job(ctx_for(conn, amfi, hooks(snapshot=fake_snapshot("A"), channels=(), sender=None)), "snapshot")
    assert res.code == "SNAPSHOT_STORED" and outbox(conn) == []


# ----------------------------------------------------------------------------------------------------- outbox


def test_outbox_reaper_marks_stale_sending_failed_and_never_resends(conn: sqlite3.Connection) -> None:
    old = (J1_TIME - timedelta(seconds=cron.OUTBOX_LEASE_S + 1)).isoformat()
    fresh = (J1_TIME - timedelta(seconds=30)).isoformat()
    for key, claimed in (("watchdog:stale", old), ("watchdog:live", fresh)):
        conn.execute(
            "INSERT INTO notification_outbox(outbox_key, channel, kind, state, created_at, updated_at, claimed_at)"
            " VALUES (?, 'owner-test', 'watchdog', 'sending', ?, ?, ?)",
            (key, claimed, claimed, claimed),
        )
    sent = Sent()
    ctx = ctx_for(conn, Amfi(), hooks(sender=sent))
    assert cron.reap_and_drain(ctx) == {"pings_reaped": 1, "pings_sent": 0}
    assert outbox(conn) == [("watchdog:live", "watchdog", "sending"), ("watchdog:stale", "watchdog", "failed")]
    later = ctx_for(conn, Amfi(), hooks(sender=sent), clock=Clock(J1_TIME + timedelta(hours=2)))
    cron.reap_and_drain(later)
    assert sent.rows == [] and {s for _, _, s in outbox(conn)} == {"failed"}


def test_a_failed_send_is_never_retried(conn: sqlite3.Connection) -> None:
    lg.enqueue_ping(conn, "watchdog:x", "owner-test", "watchdog", None, J1_TIME.isoformat())
    cron.reap_and_drain(ctx_for(conn, Amfi(), hooks(sender=Sent(fail=True))))
    assert outbox(conn) == [("watchdog:x", "watchdog", "sending")]
    ok = Sent()
    cron.reap_and_drain(ctx_for(conn, Amfi(), hooks(sender=ok), clock=Clock(J1_TIME + timedelta(hours=1))))
    assert ok.rows == [] and outbox(conn) == [("watchdog:x", "watchdog", "failed")]


def test_pending_ping_is_sent_exactly_once(conn: sqlite3.Connection) -> None:
    lg.enqueue_ping(conn, "watchdog:y", "owner-test", "watchdog", None, J1_TIME.isoformat())
    sent = Sent()
    for _ in range(3):
        cron.reap_and_drain(ctx_for(conn, Amfi(), hooks(sender=sent)))
    assert sent.rows == [("watchdog:y", "owner-test", "watchdog")]


# ----------------------------------------------------------------------------------------------------- J5


J5_TIME = datetime(2026, 10, 15, 13, 10, tzinfo=UTC)  # 18:40 IST Thursday → expects Wednesday's NAV date


def test_j5_queues_one_attention_ping_when_the_snapshot_is_missing(conn: sqlite3.Connection) -> None:
    sent = Sent()
    res = cron.run_job(ctx_for(conn, Amfi(), hooks(sender=sent), clock=Clock(J5_TIME)), "watchdog")
    assert (res.state, res.code, res.run_key) == ("done", "ATTENTION", NAV_DATE)
    assert res.steps == {"SNAPSHOT_MISSING": "FOUND", "NAV_STALE": "FOUND"}
    assert sent.rows == [(f"watchdog:{NAV_DATE}", "owner-test", "watchdog")]
    dup = cron.run_job(ctx_for(conn, Amfi(), hooks(sender=sent), clock=Clock(J5_TIME)), "watchdog")
    assert (dup.state, dup.code) == ("noop", "DUPLICATE") and len(sent.rows) == 1


def test_j5_is_quiet_when_the_pipeline_is_healthy(conn: sqlite3.Connection) -> None:
    amfi = Amfi(last_modified=LAST_MODIFIED)
    cron.run_job(ctx_for(conn, amfi), "navall")
    cron.run_job(ctx_for(conn, amfi, hooks(snapshot=fake_snapshot("A"), channels=())), "snapshot")
    sent = Sent()
    res = cron.run_job(ctx_for(conn, amfi, hooks(sender=sent), clock=Clock(J5_TIME)), "watchdog")
    assert (res.code, res.steps, sent.rows) == ("HEALTHY", {}, [])


def test_j5_reports_a_failed_job(conn: sqlite3.Connection) -> None:
    _seed_run(conn, "snapshot", NAV_DATE, "failed", J5_TIME - timedelta(hours=8))
    res = cron.run_job(ctx_for(conn, Amfi(), hooks(), clock=Clock(J5_TIME)), "watchdog")
    assert "JOB_FAILED" in res.steps


def test_expected_nav_date_skips_weekends() -> None:
    assert cron.expected_nav_date(date(2026, 10, 12)) == date(2026, 10, 9)  # Monday → Friday
    assert cron.expected_nav_date(date(2026, 10, 15)) == date(2026, 10, 14)


# ----------------------------------------------------------------------------------------------------- route


SECRET = secrets.token_urlsafe(32)


@pytest.fixture
def cron_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("CRON_SECRET", SECRET)
    monkeypatch.setenv("VERCEL_URL", DEPLOY)
    monkeypatch.setenv("VERCEL_ENV", "production")
    with make_client(tmp_path / "hosted.db", clock=lambda: J5_TIME) as c:
        yield c


BEARER = {"Authorization": f"Bearer {SECRET}", "host": DEPLOY}


def test_route_runs_a_job_on_the_deployment_host_and_answers_codes_and_counts_only(cron_client: TestClient) -> None:
    cron_client.app.app.state.cron_hooks = hooks(channels=(), sender=None)  # type: ignore[attr-defined]
    r = cron_client.get("/api/cron/watchdog", headers=BEARER)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"job", "state", "code", "run_key", "counts", "steps"}
    assert (body["job"], body["state"], body["code"], body["run_key"]) == ("watchdog", "done", "ATTENTION", NAV_DATE)
    assert all(isinstance(v, int) for v in body["counts"].values())
    assert r.headers["cache-control"] == "no-store"
    again = cron_client.post("/api/cron/watchdog", headers=BEARER)
    assert again.status_code == 200 and again.json()["code"] == "DUPLICATE"


def test_route_runs_j1_with_the_app_fetcher(cron_client: TestClient) -> None:
    st = state(cron_client)
    st.fetcher_factory = make_fetcher(Amfi())
    st.clock = lambda: J1_TIME
    cron_client.app.app.state.cron_hooks = hooks()  # type: ignore[attr-defined]
    r = cron_client.get("/api/cron/navall", headers=BEARER)
    assert r.status_code == 200 and r.json()["code"] == "STORED"


def test_route_default_hooks_fail_closed_until_other_packages_land(cron_client: TestClient) -> None:
    r = cron_client.get("/api/cron/navall", headers=BEARER)
    assert r.status_code == 500 and r.json()["code"] == "U01_SCOPE_NOT_ENFORCED"


@pytest.mark.parametrize("path", ["/api/cron/unknown", "/api/cron/navall-continuex"])
def test_route_refuses_jobs_outside_the_fixed_set(cron_client: TestClient, path: str) -> None:
    assert cron_client.get(path, headers=BEARER).status_code == 404


def test_route_takes_no_parameters(cron_client: TestClient) -> None:
    r = cron_client.get("/api/cron/watchdog?force=1", headers=BEARER)
    assert r.status_code == 400 and r.json()["code"] == "NO_PARAMETERS"


def test_route_needs_the_bearer_and_other_routes_still_refuse_the_deployment_host(cron_client: TestClient) -> None:
    assert cron_client.get("/api/cron/watchdog", headers={"host": DEPLOY}).status_code == 401
    assert cron_client.get("/api/health", headers={"host": DEPLOY}).status_code == 400
    assert cron_client.get("/api/health").status_code == 200


def test_route_is_404_when_cron_is_not_configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("CRON_SECRET", "VERCEL_URL", "VERCEL_ENV"):
        monkeypatch.delenv(k, raising=False)
    with make_client(tmp_path / "off.db") as c:
        assert c.get("/api/cron/navall", headers={"Authorization": f"Bearer {SECRET}"}).status_code == 404


def test_route_is_404_on_a_preview_deployment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRON_SECRET", SECRET)
    monkeypatch.setenv("VERCEL_URL", DEPLOY)
    monkeypatch.setenv("VERCEL_ENV", "preview")
    with make_client(tmp_path / "preview.db") as c:
        assert c.get("/api/cron/navall", headers={"Authorization": f"Bearer {SECRET}"}).status_code == 404


def test_route_is_404_without_the_middleware_cron_mark(tmp_path: Path) -> None:
    """Defence in depth: even if a request reached the handler without the cron exception, it is not served."""
    from iip.api.app import create_app
    from iip.api.routes import all_routers

    asgi = create_app(hosted_settings(tmp_path / "x.db"), routers=all_routers())
    inner = asgi.app  # type: ignore[attr-defined]
    with TestClient(inner, base_url=ORIGIN) as c:
        assert c.get("/api/cron/watchdog").status_code == 404
    assert TOKEN  # the hosted conftest's token is never the cron secret


def test_an_ingestion_crash_leaves_a_takeoverable_claim_and_no_stale_marker(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    def crash(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("synthetic crash")

    monkeypatch.setattr(ing, "ingest_navall_resumable", crash)
    res = cron.run_job(ctx_for(conn, Amfi()), "navall")
    assert (res.state, res.code) == ("failed", "INTERNAL_ERROR")
    assert coordination.load_job(conn, cron.NAVALL_OPEN) is None
    assert run_row(conn, "navall", NAV_DATE)["state"] == "running"  # type: ignore[index]
    monkeypatch.undo()
    later = Clock(J1_TIME + timedelta(seconds=cron.CLAIM_STALE_S + 1))
    assert cron.run_job(ctx_for(conn, Amfi(), clock=later), "navall").code == "STORED"
    assert run_row(conn, "navall", NAV_DATE)["attempts"] == 2  # type: ignore[index]
