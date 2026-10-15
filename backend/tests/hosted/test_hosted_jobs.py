"""Hosted mode (ADR-0013): DB-backed refresh claims and leases, resumable NAVAll and NAV-history jobs that give the
SAME stored data as the local single-call versions, and the refusals and substitutes for disk-only features."""

from __future__ import annotations

import itertools
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from iip.data.parsers.amfi_navhistory import parse_navhistory
from iip.services import ingestion as ing
from iip.services import portfolio as pf
from iip.store import coordination
from iip.store.db import connect, connect_libsql, migrate
from tests.data.conftest import NAVHISTORY_RETRIEVED, NAVHISTORY_URL, load_fixture, make_payload
from tests.services.test_ingestion import amfi, fetcher
from tests.services.test_portfolio import CSV_OK, make_pf, seed_market

from .conftest import NOW, ORIGIN, login, make_client, state

HISTORY = load_fixture("amfi_navhistory_excerpt.txt")


def _hosted_conn(db: Path) -> Any:
    c = connect_libsql(str(db), hosted=True)
    migrate(c, NOW.isoformat())
    return c


def _observations(c: Any) -> set[tuple[str, str, str]]:
    return {(r["series_id"], r["observation_date"], r["value"]) for r in c.execute(
        "SELECT series_id, observation_date, value FROM observations WHERE superseded_by IS NULL")}  # fmt: skip


# ----------------------------------------------------------------------------- claims and leases


def test_refresh_claim_is_atomic_and_shared(tmp_path: Path) -> None:
    db = tmp_path / "h.db"
    _hosted_conn(db)
    local = threading.local()
    granted: list[bool] = []
    barrier = threading.Barrier(12)
    t0 = NOW.timestamp()

    def claim() -> None:
        if not hasattr(local, "c"):
            local.c = connect_libsql(str(db), hosted=True)
        barrier.wait(5)
        granted.append(coordination.claim_refresh(local.c, "amfi.navall", t0, 900) is None)

    threads = [threading.Thread(target=claim) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert granted.count(True) == 1
    c = connect_libsql(str(db), hosted=True)
    assert coordination.claim_refresh(c, "amfi.navall", t0 + 60, 900) == 841  # seconds left, rounded up
    assert coordination.claim_refresh(c, "amfi.navall", t0 + 900, 900) is None  # the slot reopens
    assert coordination.claim_refresh(c, "amfi.navhistory:1", t0, 900) is None  # keys are independent


def test_lease_is_exclusive_lapses_and_is_released_only_by_its_holder(tmp_path: Path) -> None:
    db = tmp_path / "h.db"
    c = _hosted_conn(db)
    now = [100.0]
    a = coordination.DbLease(lambda: c, "backfill", ttl_s=330, clock=lambda: now[0])
    b = coordination.DbLease(lambda: c, "backfill", ttl_s=330, clock=lambda: now[0])
    assert a.acquire() and not b.acquire()
    b.release()  # not the holder: no effect
    assert not b.acquire()
    now[0] += 331  # the holder was killed at its time limit and never released
    assert b.acquire()
    a.release()  # a's lease lapsed and b holds it now: a must not free b's lease
    assert not a.acquire()
    b.release()
    assert a.acquire()


# ----------------------------------------------------------------------------- resumable jobs: parity with local


class _Metered:
    """A connection whose every statement advances a fake clock by ``cost`` units: a stand-in for a remote database
    where time is spent in round trips (ADR-0013). Everything else is delegated."""

    def __init__(self, conn: Any, cost: float = 1.0) -> None:
        self._conn, self.cost, self.clock = conn, cost, 0.0

    def execute(self, sql: str, params: Any = ()) -> Any:
        self.clock += self.cost
        return self._conn.execute(sql, params)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def _counting(handler: Any) -> tuple[Any, list[str]]:
    seen: list[str] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return handler(request)  # type: ignore[no-any-return]

    return wrapped, seen


def _run_steps(conn: _Metered, budget: float, chunk: int = 2) -> tuple[list[dict[str, object]], list[float], list[str]]:
    """Call the hosted NAVAll step until done; each call gets ``budget`` units. Returns the progress of each call,
    the units each call actually used, and every URL fetched."""
    handler, urls = _counting(amfi)
    steps: list[dict[str, object]] = []
    used: list[float] = []
    while True:
        start = conn.clock
        out = ing.ingest_navall_resumable(conn, fetcher(handler), lambda: NOW, lambda s=start: s + budget - conn.clock,
                                          monotonic=lambda: conn.clock, chunk=chunk)  # type: ignore[misc]  # fmt: skip
        steps.append(out)
        used.append(conn.clock - start)
        if out["done"]:
            return steps, used, urls
        assert len(steps) < 500


def _local(tmp_path: Path) -> Any:
    local = connect(tmp_path / "local.db")
    migrate(local, NOW.isoformat())
    ing.sync_sources(local)
    ing.ingest_navall(local, fetcher(amfi), lambda: NOW)
    return local


def _table(c: Any, sql: str) -> list[tuple[Any, ...]]:
    return [tuple(r) for r in c.execute(sql)]


def test_resumable_navall_stores_exactly_what_the_local_ingest_stores(tmp_path: Path) -> None:
    local = _local(tmp_path)
    hosted = _Metered(_hosted_conn(tmp_path / "hosted.db"))
    ing.sync_sources(hosted)
    steps, _used, _urls = _run_steps(hosted, budget=15)
    assert len(steps) > 2 and all(not s["done"] for s in steps[:-1])
    assert [s["schemes_done"] for s in steps] == sorted(s["schemes_done"] for s in steps)  # monotone progress
    assert _observations(hosted) == _observations(local)
    for sql in ("SELECT instrument_id, name, isin, amfi_code FROM instruments ORDER BY instrument_id",
                "SELECT * FROM mf_schemes ORDER BY instrument_id",
                "SELECT series_id, observation_date, value, quality_status, source_id, superseded_by IS NULL"
                " FROM observations ORDER BY series_id, observation_date, source_id, obs_id"):  # fmt: skip
        assert _table(hosted, sql) == _table(local, sql)
    runs = _table(hosted, "SELECT status, raw_sha256 FROM ingestion_runs WHERE source_id='amfi.navall'")
    assert runs == _table(local, "SELECT status, raw_sha256 FROM ingestion_runs WHERE source_id='amfi.navall'")
    assert [r[0] for r in runs] == ["ok"]  # ONE run across all the calls, recording the one file read
    assert hosted.execute("SELECT COUNT(*) FROM job_progress").fetchone()[0] == 0  # staging cleared


def test_continuations_never_fetch_again(tmp_path: Path) -> None:
    """The first call fetches NAVAll once and stages the minimised scope; every later call reads the staging."""
    hosted = _Metered(_hosted_conn(tmp_path / "hosted.db"))
    ing.sync_sources(hosted)
    steps, _used, urls = _run_steps(hosted, budget=15)
    assert len(steps) > 2
    assert [u for u in urls if u.endswith("NAVAll.txt")] == [  # the 302 and its target: ONE logical fetch
        "https://www.amfiindia.com/spages/NAVAll.txt", "https://portal.amfiindia.com/spages/NAVAll.txt",
    ]  # fmt: skip


def test_a_step_never_starts_work_past_its_budget(tmp_path: Path) -> None:
    """Old behaviour: a full chunk was forced before the clock was checked (the 504 on the first deploy). Now no
    block starts once the budget is spent, and none starts unless its measured cost fits: a call overshoots its
    budget by at most one block's statements (a first, unmeasured block)."""
    hosted = _Metered(_hosted_conn(tmp_path / "hosted.db"))
    ing.sync_sources(hosted)
    steps, used, _urls = _run_steps(hosted, budget=30)
    block_statements = 12  # load + BEGIN + 2 scheme upserts + 2 reads + ≤ 2 writes + clear + save + COMMIT
    staging_statements = 40  # first call only: run start, sources, scope reads, staged rows
    assert used[0] <= 30 + staging_statements + block_statements
    assert all(u <= 30 + block_statements for u in used[1:-1]), used
    assert [s["schemes_done"] for s in steps][-1] == steps[-1]["schemes_total"]


def test_a_slow_database_still_progresses_one_scheme_per_call(tmp_path: Path) -> None:
    """Even when a single scheme costs more than the whole budget, every call stores at least one (a partial block,
    the rest staying staged), so the job can never stall; the result is still identical to the local ingest."""
    local = _local(tmp_path)
    hosted = _Metered(_hosted_conn(tmp_path / "hosted.db"), cost=4.0)
    ing.sync_sources(hosted)
    # A 3-scheme block costs ~12 statements x 4 = ~48 units against a 30-unit budget: it can never fit whole.
    steps, _used, _urls = _run_steps(hosted, budget=30, chunk=3)
    progress = [int(str(s["schemes_done"])) for s in steps]
    assert all(b > a for a, b in itertools.pairwise(progress[1:])), progress  # forward on every call after staging
    assert len(steps) > len(set(progress)) - 1 >= 3  # partial blocks: more calls than whole blocks
    assert _observations(hosted) == _observations(local)


def test_a_failure_marks_the_run_failed_and_clears_the_staging(tmp_path: Path, monkeypatch: Any) -> None:
    hosted = _Metered(_hosted_conn(tmp_path / "hosted.db"))
    ing.sync_sources(hosted)
    calls = {"n": 0}
    real = ing.upsert_observations_batch

    def flaky(*a: Any, **k: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return real(*a, **k)

    monkeypatch.setattr(ing, "upsert_observations_batch", flaky)
    try:
        _run_steps(hosted, budget=1000, chunk=2)
    except RuntimeError:
        pass
    else:
        raise AssertionError("the injected failure must surface")
    assert _table(hosted, "SELECT status, error FROM ingestion_runs WHERE source_id='amfi.navall'") == [
        ("failed", "RuntimeError")
    ]
    assert hosted.execute("SELECT COUNT(*) FROM job_progress").fetchone()[0] == 0
    monkeypatch.setattr(ing, "upsert_observations_batch", real)
    steps, _used, _urls = _run_steps(hosted, budget=1000)  # a fresh run starts and completes
    assert steps[-1]["status"] == "ok"


def test_a_job_saved_by_the_previous_version_is_restarted_cleanly(tmp_path: Path) -> None:
    """The first deploy left a pre-staging job row (and its 'running' run) in the hosted database."""
    hosted = _Metered(_hosted_conn(tmp_path / "hosted.db"))
    ing.sync_sources(hosted)
    hosted.execute("INSERT INTO ingestion_runs(run_id, source_id, started_at, status) VALUES"
                   " ('run_old', 'amfi.navall', ?, 'running')", (NOW.isoformat(),))  # fmt: skip
    coordination.save_job(hosted, ing.NAVALL_JOB, {"run_id": "run_old", "next_code": 0, "stored": 0}, NOW.isoformat())
    steps, _used, _urls = _run_steps(hosted, budget=1000)
    assert steps[-1]["status"] == "ok"
    old = hosted.execute("SELECT status, error FROM ingestion_runs WHERE run_id='run_old'").fetchone()
    assert tuple(old) == ("failed", ing.INTERRUPTED)


def _history_scheme() -> tuple[int, str]:
    """The first scheme and its AMC in the history fixture (derived, so the test follows the fixture's content)."""
    payload = make_payload("amfi.navhistory", HISTORY, NAVHISTORY_URL, NAVHISTORY_RETRIEVED)
    rec = parse_navhistory(payload).records[0]
    return rec.scheme_code, str(rec.amc)


def _probe_handler(answer_id: int):  # type: ignore[no-untyped-def]
    """Fund-house ids below ``answer_id`` answer with an empty report; ``answer_id`` with the real excerpt."""

    def handler(request: httpx.Request) -> httpx.Response:
        mf = int(request.url.params.get("mf", "0"))
        body = HISTORY if mf == answer_id else b""
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=body)

    return handler


def test_resumable_backfill_discovers_then_fetches_and_matches_local(tmp_path: Path) -> None:
    code, amc = _history_scheme()
    start, end = date(2025, 10, 1), date(2026, 10, 15)
    local = connect(tmp_path / "local.db")
    migrate(local, NOW.isoformat())
    ing.sync_sources(local)
    ing.backfill_history(local, fetcher(_probe_handler(3)), scheme_code=code, mf_id=3, start=start, end=end,
                         now=lambda: NOW)  # fmt: skip

    hosted = _hosted_conn(tmp_path / "hosted.db")
    ing.sync_sources(hosted)
    phases: list[str] = []
    while True:
        out = ing.backfill_resumable(
            hosted, fetcher(_probe_handler(3)), scheme_code=code, amc_name=amc, start=start, end=end,
            now=lambda: NOW, pause=None, stop=lambda: True,
        )  # fmt: skip
        phases.append(str(out["phase"]))
        if out["done"]:
            break
        assert len(phases) < 50
    assert phases[:3] == ["discovering", "discovering", "fetching"]  # ids 1 and 2 miss; id 3 is found
    windows = int(str(out["windows_total"]))
    assert phases.count("fetching") == windows  # then one 90-day window per call (budget always exhausted)
    assert out["windows_done"] == windows and out["status"] in {"ok", "partial"}
    assert _observations(hosted) == _observations(local) and _observations(local)
    assert coordination.load_job(hosted, ing.backfill_job_key(code)) is None


def test_backfill_with_unknown_fund_house_ends_cleanly(tmp_path: Path) -> None:
    hosted = _hosted_conn(tmp_path / "h.db")
    ing.sync_sources(hosted)
    try:
        for _ in range(10):
            ing.backfill_resumable(
                hosted, fetcher(_probe_handler(999)), scheme_code=1, amc_name="No Such AMC", start=date(2026, 1, 1),
                end=date(2026, 10, 15), now=lambda: NOW, pause=None, stop=lambda: False, max_id=4,
            )  # fmt: skip
        raise AssertionError("expected FundHouseNotFound")
    except ing.FundHouseNotFound:
        pass
    assert coordination.load_job(hosted, ing.backfill_job_key(1)) is None
    assert hosted.execute("SELECT status FROM ingestion_runs").fetchone()["status"] == "failed"


# ----------------------------------------------------------------------------- the API in hosted mode


def _seed_history_scheme(st: Any) -> int:
    code, amc = _history_scheme()
    ing.sync_sources(st.conn)  # as the NAVAll fetch does before any scheme exists
    st.conn.execute(
        "INSERT INTO instruments(instrument_id, kind, name, amfi_code, origin, created_at)"
        " VALUES (?, 'mf_scheme', 'FIXTURE scheme', ?, 'fixture', ?)",
        (f"mf:{code}", str(code), NOW.isoformat()),
    )
    st.conn.execute(
        "INSERT INTO mf_schemes(instrument_id, amc, category_raw, sebi_category, plan)"
        " VALUES (?, ?, 'x', 'x', 'direct')",
        (f"mf:{code}", amc),
    )
    return code


def test_backfill_route_continues_until_done_and_limits_new_runs(db: Path) -> None:
    with make_client(db) as c:
        h = login(c)
        st = state(c)
        code = _seed_history_scheme(st)
        st.fetcher_factory = lambda: fetcher(_probe_handler(1))
        st.pause = lambda _s: None
        st.job_budget_s = 0.0  # every call does exactly one unit of work
        calls = []
        while True:
            r = c.post(f"/api/ingestion/backfill/{code}", json={"years": 1}, headers=h)
            assert r.status_code == 200, r.text
            calls.append(r.json())
            if r.json()["done"]:
                break
            assert len(calls) < 30
        assert len(calls) > 2 and calls[-1]["stored"] >= 1
        again = c.post(f"/api/ingestion/backfill/{code}", json={"years": 1}, headers=h)
        assert again.status_code == 429 and again.json()["code"] == "RATE_LIMITED"  # a NEW run within 15 min
        lease = coordination.DbLease(lambda: st.conn, "backfill", ttl_s=330, clock=st.epoch)
        assert lease.acquire()  # the route released the lease after every call
        busy = c.post(f"/api/ingestion/backfill/{code}", json={"years": 1}, headers=h)
        assert busy.status_code == 429 and busy.json()["code"] == "BACKFILL_IN_PROGRESS"
        lease.release()


def test_navall_route_is_resumable_and_rate_limited(db: Path) -> None:
    with make_client(db) as c:
        h = login(c)
        st = state(c)
        st.fetcher_factory = lambda: fetcher(amfi)
        r = c.post("/api/ingestion/amfi-navall", json={}, headers=h)
        assert r.status_code == 200 and r.json()["done"] is True and r.json()["status"] in {"ok", "partial"}
        again = c.post("/api/ingestion/amfi-navall", json={}, headers=h)
        assert again.status_code == 429


def test_disk_only_features_are_refused_or_substituted(db: Path) -> None:
    with make_client(db) as c:
        h = login(c)
        state(c)
        backup = c.post("/api/backup", json={}, headers=h)
        assert backup.status_code == 409 and backup.json()["code"] == "BACKUP_NOT_AVAILABLE_HOSTED"
        llm = c.put("/api/llm/config", json={"mode": "local", "model": "m"}, headers=h)
        assert llm.status_code == 422 and llm.json()["code"] == "LLM_LOCAL_NOT_AVAILABLE_HOSTED"
        assert c.post("/api/dev/seed-fixtures", json={}, headers=h).status_code == 403
        inv = c.get("/api/privacy/inventory").json()
        assert inv["backups"]["count"] == 0 and "Turso" in inv["backups"]["note"]
    assert not (db.parent / "must-not-be-used").exists()


def test_import_apply_takes_an_in_database_snapshot_instead_of_a_file_backup(db: Path) -> None:
    with make_client(db) as c:
        h = login(c)
        st = state(c)
        seed_market(st.conn)
        pid = make_pf(st.conn)
        p = pf.preview_holdings_import(st.conn, pid, CSV_OK, "h.csv", None, NOW)
        r = c.post(f"/api/holdings/import/{p['batch_id']}/apply", json={"sha256": p["file_sha256"]}, headers=h)
        assert r.status_code == 200, r.text
        snaps = st.conn.execute("SELECT tag, row_count FROM import_snapshots").fetchall()
        assert [(s["tag"], s["row_count"]) for s in snaps] == [("pre-import", 0)]  # the book BEFORE the import
        assert st.conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == len(p["will_store"])


def test_privacy_erase_removes_every_user_row_in_the_hosted_store(db: Path) -> None:
    with make_client(db) as c:
        h = login(c)
        st = state(c)
        seed_market(st.conn)
        pid = make_pf(st.conn)
        p = pf.preview_holdings_import(st.conn, pid, CSV_OK, "h.csv", None, NOW)
        c.post(f"/api/holdings/import/{p['batch_id']}/apply", json={"sha256": p["file_sha256"]}, headers=h)
        obs_before = st.conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        r = c.post("/api/privacy/erase", json={"confirm": "ERASE ALL MY DATA"}, headers=h)
        assert r.status_code == 200, r.text
        assert "Turso" in r.json()["provider_retention"]
        for t in pf.USER_TABLES:
            assert st.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0, t
        assert st.conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == obs_before
        assert c.get("/api/me").status_code == 200  # the session survives: it is not user data


def test_a_cold_start_does_not_interrupt_a_job_still_in_progress(db: Path) -> None:
    with make_client(db) as c:
        st = state(c)
        ing.sync_sources(st.conn)
        run_id = ing._start_run(st.conn, "amfi.navhistory", NOW - timedelta(minutes=20))
        coordination.save_job(st.conn, "backfill:1", {"run_id": run_id}, NOW.isoformat())
        stale = ing._start_run(st.conn, "amfi.navall", NOW - timedelta(minutes=20))
    with make_client(db) as c2:  # a new instance starts (cold start)
        rows = {r["run_id"]: r["status"] for r in state(c2).conn.execute("SELECT run_id, status FROM ingestion_runs")}
    assert rows[run_id] == "running" and rows[stale] == "failed"
    assert ORIGIN
