"""Batch NAV-history backfill (walkthrough 2026-10-15): selected schemes grouped by fund house, one pass per fund house,
only the selected schemes stored. Synthetic AMFI-format bytes over MockTransport — no network."""

import re
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from iip.data.fetch import BreakerStatus, CircuitBreaker, Fetcher
from iip.services import ingestion as ing
from iip.store.coordination import load_job
from iip.store.db import connect, migrate
from tests.data.conftest import load_fixture
from tests.data.test_fetch import PUBLIC_IP

NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
HALCYON = load_fixture("amfi_navhistory_excerpt.txt")  # fictional fund house "Halcyon Mutual Fund" (codes 9xxxxx)
# A second fictional fund house: same layout, its own name and scheme codes (8xxxxx).
BOREALIS = re.sub(rb"(?m)^9(\d{5});", rb"8\1;", HALCYON.replace(b"Halcyon", b"Borealis"))
NO_DATA_PAGE = b"<!DOCTYPE html><html><head><title>\r\n\tView/Download NAV History\r\n</title></head></html>"
BODIES = {9: HALCYON, 12: BOREALIS}
END = date(2026, 10, 14)
START = date(2026, 3, 1)  # 3 windows of ≤ 90 days; only the newest contains the fixture's 13/14-Oct rows


class Amfi:
    """Serves each fund house's file for windows covering the fixture dates; AMFI's no-data page otherwise."""

    def __init__(self) -> None:
        self.requests: list[tuple[int, str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        q = parse_qs(request.url.query.decode())
        mf, frm, to = int(q["mf"][0]), q["frmdt"][0], q["todt"][0]
        self.requests.append((mf, frm, to))
        to_d = datetime.strptime(to, "%d-%b-%Y").date()
        frm_d = datetime.strptime(frm, "%d-%b-%Y").date()
        probe = frm_d == to_d  # discovery asks for one day; answer with the fund house so it can be recognised
        if mf in BODIES and (probe or frm_d <= date(2026, 10, 13) <= to_d):
            return httpx.Response(200, headers={"content-type": "text/plain"}, content=BODIES[mf])
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=NO_DATA_PAGE)

    def windows(self) -> list[tuple[int, str, str]]:
        return [r for r in self.requests if r[1] != r[2]]


def fetcher(handler: Amfi, breaker: CircuitBreaker | None = None) -> Fetcher:
    return Fetcher(
        transport=httpx.MockTransport(handler), resolver=lambda _h: [PUBLIC_IP], jitter_seed=1, sleep=lambda _s: None,
        clock=lambda: NOW, breaker=breaker or CircuitBreaker(clock=lambda: NOW),
    )  # fmt: skip


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[Any]:
    c = connect(tmp_path / "x.db")
    migrate(c, NOW.isoformat())
    ing.sync_sources(c)
    yield c
    c.close()


def _cache_ids(conn: Any) -> None:
    for name, mf in (("halcyon mutual fund", 9), ("borealis mutual fund", 12)):
        conn.execute("INSERT INTO settings(key, value_json) VALUES (?, ?)", (f"amfi.mf_id:{name}", str(mf)))


GROUPS = {"Halcyon Mutual Fund": [928470, 972505], "Borealis Mutual Fund": [828470]}


def _series(conn: Any) -> set[str]:
    return {r["series_id"] for r in conn.execute("SELECT DISTINCT series_id FROM observations")}


def test_one_pass_per_fund_house_and_only_selected_schemes_are_stored(conn: Any) -> None:
    _cache_ids(conn)
    amfi = Amfi()
    ing.start_batch_backfill(conn, groups=GROUPS, skipped=[], start=START, end=END, now=lambda: NOW)
    out = ing.run_batch_backfill_locally(conn, fetcher(amfi), now=lambda: NOW, pause=None)

    # 2 fund houses × 3 windows = 6 requests, no discovery (ids cached); each fund house fetched once per window.
    assert len(amfi.requests) == 6
    assert sorted(mf for mf, _f, _t in amfi.windows()) == [9, 9, 9, 12, 12, 12]
    assert _series(conn) == {"nav:928470", "nav:972505", "nav:828470"}  # other schemes in the files are NOT kept
    assert out["done"] is True and out["status"] == "ok" and out["stored"] == 6
    houses = {h["amc"]: h for h in out["fund_houses"]}
    assert houses["Halcyon Mutual Fund"]["schemes"] == [
        {"amfi_code": 928470, "stored": 2},
        {"amfi_code": 972505, "stored": 2},
    ]
    assert houses["Borealis Mutual Fund"]["schemes"] == [{"amfi_code": 828470, "stored": 2}]
    assert "3 scheme(s) across 2 fund house(s)" in out["detail"]
    run = conn.execute("SELECT status, source_id FROM ingestion_runs").fetchall()
    assert [(r["status"], r["source_id"]) for r in run] == [("ok", "amfi.navhistory")]  # one run per batch
    assert load_job(conn, ing.BATCH_JOB) is None


def test_fund_house_ids_are_discovered_once_and_no_data_pages_never_trip_the_breaker(conn: Any) -> None:
    amfi = Amfi()
    breaker = CircuitBreaker(clock=lambda: NOW)
    ing.start_batch_backfill(conn, groups=GROUPS, skipped=[], start=START, end=END, now=lambda: NOW)
    out = ing.run_batch_backfill_locally(conn, fetcher(amfi, breaker), now=lambda: NOW, pause=None, max_id=15)

    probes = [r for r in amfi.requests if r[1] == r[2]]
    # Borealis (first by name) is probed up to id 12; Halcyon was seen at id 9 on the way and is then cached.
    assert [mf for mf, _f, _t in probes] == list(range(1, 13))
    assert out["status"] == "ok" and out["stored"] == 6
    assert breaker.allow("amfi.navhistory") is BreakerStatus.CLOSED


def test_an_unknown_fund_house_fails_alone_and_the_rest_completes(conn: Any) -> None:
    conn.execute("INSERT INTO settings(key, value_json) VALUES ('amfi.mf_id:halcyon mutual fund', '9')")
    groups = {"Halcyon Mutual Fund": [928470], "Nowhere Mutual Fund": [700001]}
    ing.start_batch_backfill(conn, groups=groups, skipped=[], start=START, end=END, now=lambda: NOW)
    out = ing.run_batch_backfill_locally(conn, fetcher(Amfi()), now=lambda: NOW, pause=None, max_id=5)

    houses = {h["amc"]: h for h in out["fund_houses"]}
    assert houses["Nowhere Mutual Fund"]["status"] == "failed"
    assert "could not be found" in houses["Nowhere Mutual Fund"]["error"]
    assert houses["Halcyon Mutual Fund"]["status"] == "done"
    assert out["status"] == "partial" and _series(conn) == {"nav:928470"}
    assert out["windows_done"] == out["windows_total"] == 6


def test_hosted_steps_store_exactly_what_the_local_run_stores(tmp_path: Path) -> None:
    def db(name: str) -> Any:
        c = connect(tmp_path / name)
        migrate(c, NOW.isoformat())
        ing.sync_sources(c)
        _cache_ids(c)
        ing.start_batch_backfill(c, groups=GROUPS, skipped=[], start=START, end=END, now=lambda: NOW)
        return c

    local = db("local.db")
    ing.run_batch_backfill_locally(local, fetcher(Amfi()), now=lambda: NOW, pause=None)

    hosted, steps, out = db("hosted.db"), 0, {"done": False}
    while not out["done"]:
        out = ing.backfill_batch_step(hosted, fetcher(Amfi()), now=lambda: NOW, pause=None, stop=lambda: True)
        steps += 1
        if not out["done"]:
            assert {"amcs_done", "amcs_total", "windows_done", "windows_total", "stored"} <= out.keys()
    assert steps == 6 + 1  # one window per step, then the step that finishes the last group

    def content(c: Any) -> list[tuple[str, str, str]]:
        q = "SELECT series_id, observation_date, value FROM observations ORDER BY series_id, observation_date"
        return [(r[0], r[1], r[2]) for r in c.execute(q)]

    assert content(local) == content(hosted) and content(local)
    assert out["status"] == "ok" and out["stored"] == 6


def test_a_crash_mid_run_marks_the_run_failed(conn: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _cache_ids(conn)

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(ing, "_fetch_window_many", boom)
    ing.start_batch_backfill(conn, groups=GROUPS, skipped=[], start=START, end=END, now=lambda: NOW)
    with pytest.raises(RuntimeError):
        ing.run_batch_backfill_locally(conn, fetcher(Amfi()), now=lambda: NOW, pause=None)
    run = conn.execute("SELECT status, error FROM ingestion_runs").fetchone()
    assert run["status"] == "failed" and "RuntimeError" in run["error"]


def test_all_selected_schemes_recent_means_nothing_to_do() -> None:
    out = ing.skipped_only_result([{"amfi_code": 928470, "retry_after_s": 300}])
    assert out["done"] is True and out["status"] == "skipped" and out["run_id"] is None
    assert out["skipped"] == [{"amfi_code": 928470, "retry_after_s": 300}]
