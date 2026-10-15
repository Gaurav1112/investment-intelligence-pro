"""POST /api/ingestion/backfill-batch (walkthrough 2026-10-15): validation, unknown schemes, the per-scheme 15-minute
limit inside a batch, and one backfill (single or batch) at a time."""

import sqlite3
from typing import Any

import pytest
from starlette.testclient import TestClient

from iip.services import ingestion
from iip.store.coordination import clear_job, load_job

from .conftest import ORIGIN

URL = "/api/ingestion/backfill-batch"


def _seed(conn: sqlite3.Connection, code: int, amc: str, origin: str = "source") -> None:
    conn.execute(
        "INSERT INTO instruments(instrument_id, kind, name, amfi_code, origin, created_at)"
        " VALUES (?, 'mf_scheme', ?, ?, ?, '2026-10-15')",
        (f"mf:{code}", f"Fund {code} - Direct Growth", str(code), origin),
    )
    conn.execute(
        "INSERT INTO mf_schemes(instrument_id, amc, category_raw, sebi_category, plan)"
        " VALUES (?, ?, 'Liquid', 'Liquid', 'direct')",
        (f"mf:{code}", amc),
    )


def _headers(csrf: str) -> dict[str, str]:
    return {"Origin": ORIGIN, "X-IIP-CSRF": csrf}


@pytest.fixture
def api(authed: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, str, Any, list[Any]]:
    """Authed client with three stored schemes in two fund houses; the batch runner is stubbed to record the job it
    was given (no fetching here — the service tests cover that)."""
    client, csrf = authed
    st = client.app.app.state.iip  # type: ignore[attr-defined]
    ingestion.sync_sources(st.conn)
    _seed(st.conn, 990001, "Alpha Mutual Fund")
    _seed(st.conn, 990002, "Alpha Mutual Fund")
    _seed(st.conn, 990003, "Beta Mutual Fund")
    _seed(st.conn, 990009, "Alpha Mutual Fund", origin="fixture")
    jobs: list[Any] = []

    def run(conn: sqlite3.Connection, _fetcher: object, **_k: object) -> dict[str, Any]:
        job = load_job(conn, ingestion.BATCH_JOB)
        jobs.append(job)
        clear_job(conn, ingestion.BATCH_JOB)
        return {"done": True, "status": "ok", "skipped": job["skipped"] if job else []}

    monkeypatch.setattr(ingestion, "run_batch_backfill_locally", run)
    return client, csrf, st, jobs


@pytest.mark.parametrize(
    "body",
    [
        {"amfi_codes": []},
        {"amfi_codes": list(range(1, 102))},  # 101 > 100
        {"amfi_codes": [990001, 990001]},
        {"amfi_codes": [990001], "years": 21},
        {"amfi_codes": [990001], "extra": True},
    ],
)
def test_invalid_bodies_are_422(api: tuple[TestClient, str, Any, list[Any]], body: dict[str, Any]) -> None:
    client, csrf, _st, jobs = api
    assert client.post(URL, json=body, headers=_headers(csrf)).status_code == 422
    assert jobs == []


def test_unknown_and_fixture_schemes_are_listed_and_nothing_starts(api: tuple[TestClient, str, Any, list[Any]]) -> None:
    client, csrf, st, jobs = api
    r = client.post(URL, json={"amfi_codes": [990001, 123456, 990009]}, headers=_headers(csrf))
    assert r.status_code == 404
    assert r.json()["detail"]["unknown"] == [123456, 990009]
    assert jobs == [] and st.claim_refresh("amfi.navhistory:990001") is None  # no slot used


def test_schemes_are_grouped_by_fund_house(api: tuple[TestClient, str, Any, list[Any]]) -> None:
    client, csrf, _st, jobs = api
    r = client.post(URL, json={"amfi_codes": [990003, 990002, 990001], "years": 2}, headers=_headers(csrf))
    assert r.status_code == 200, r.text
    groups = {g["amc"]: g["codes"] for g in jobs[0]["groups"]}
    assert groups == {"Alpha Mutual Fund": [990001, 990002], "Beta Mutual Fund": [990003]}


def test_recently_backfilled_schemes_are_skipped_not_the_whole_batch(
    api: tuple[TestClient, str, Any, list[Any]],
) -> None:
    client, csrf, st, jobs = api
    assert st.claim_refresh("amfi.navhistory:990001") is None  # e.g. a single backfill a moment ago
    r = client.post(URL, json={"amfi_codes": [990001, 990002]}, headers=_headers(csrf))
    assert r.status_code == 200
    assert [s["amfi_code"] for s in r.json()["skipped"]] == [990001]
    assert {g["amc"]: g["codes"] for g in jobs[0]["groups"]} == {"Alpha Mutual Fund": [990002]}
    # Both are now recent: nothing to do, no job, no AMFI request.
    again = client.post(URL, json={"amfi_codes": [990001, 990002]}, headers=_headers(csrf)).json()
    assert again["status"] == "skipped" and len(again["skipped"]) == 2 and len(jobs) == 1


def test_one_backfill_at_a_time_single_or_batch(api: tuple[TestClient, str, Any, list[Any]]) -> None:
    client, csrf, st, jobs = api
    with st.backfill_lock:
        busy = client.post(URL, json={"amfi_codes": [990001]}, headers=_headers(csrf))
    assert busy.status_code == 429 and busy.json()["code"] == "BACKFILL_IN_PROGRESS"
    # A batch part-way through (hosted steps) blocks a single-scheme backfill and a different batch.
    ingestion.start_batch_backfill(
        st.conn, groups={"Alpha Mutual Fund": [990001]}, skipped=[], start=st.clock().date(), end=st.clock().date(),
        now=st.clock,
    )  # fmt: skip
    single = client.post("/api/ingestion/backfill/990002", json={"years": 1}, headers=_headers(csrf))
    assert single.status_code == 429 and single.json()["code"] == "BACKFILL_IN_PROGRESS"
    other = client.post(URL, json={"amfi_codes": [990003]}, headers=_headers(csrf))
    assert other.status_code == 429
    # The same selection continues the job in progress.
    same = client.post(URL, json={"amfi_codes": [990001]}, headers=_headers(csrf))
    assert same.status_code == 200 and jobs[-1]["groups"][0]["codes"] == [990001]
