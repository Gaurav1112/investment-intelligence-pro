from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from iip.api.app import create_app
from iip.api.routes import all_routers
from iip.api.settings import Settings

ORIGIN = "http://127.0.0.1:8741"
NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)


def make(tmp_path: Path, env: str) -> tuple[TestClient, dict[str, str]]:
    settings = Settings(env=env, data_dir=tmp_path / env)
    c = TestClient(create_app(settings, routers=all_routers(), clock=lambda: NOW), base_url=ORIGIN)
    c.__enter__()
    token = settings.token_path.read_text().strip()
    csrf = c.post("/api/session", json={"token": token}, headers={"Origin": ORIGIN}).json()["csrf"]
    return c, {"Origin": ORIGIN, "X-IIP-CSRF": csrf}


@pytest.fixture
def dev(tmp_path: Path) -> Iterator[tuple[TestClient, dict[str, str]]]:
    c, h = make(tmp_path, "dev")
    yield c, h
    c.__exit__(None, None, None)


def test_fixture_seeding_is_refused_in_prod(tmp_path: Path) -> None:
    c, h = make(tmp_path, "prod")
    assert c.post("/api/dev/seed-fixtures", json={}, headers=h).status_code == 403
    c.__exit__(None, None, None)


def test_discover_flow_end_to_end(dev: tuple[TestClient, dict[str, str]]) -> None:
    c, h = dev
    # Empty universe → ABSTAIN, with a reason the UI can show.
    assert c.post("/api/discover", json={}, headers=h).json()["status"] == "ABSTAIN"
    seeded = c.post("/api/dev/seed-fixtures", json={}, headers=h).json()
    assert "FIXTURE" in seeded["warning"] and len(seeded["created"]) == 6
    body = {
        "amount": "500000",
        "withdrawal_date": "2027-04-15",
        "objective": "A_capital_preservation",
        "loss_acceptable": False,
        "early_need": "possible",
        "max_days_to_cash": 7,
    }
    assert c.put("/api/profile", json=body, headers=h).json()["mode"] == "PERSONALISED"
    refused = c.post("/api/discover", json={}, headers=h).json()
    assert refused["status"] == "NO_SUITABLE_CANDIDATE"  # personalised mode never ranks fixtures by default
    out = c.post("/api/discover", json={"include_fixtures": True}, headers=h).json()
    assert out["status"] == "RANKED" and out["ranked"][0]["tier"] == "T1"
    run = c.get(f"/api/runs/{out['run']['run_id']}").json()
    assert run["output_hash"] == out["run"]["result_hash"]


def test_manual_tbill_requires_https_citation_and_decimal_strings(dev: tuple[TestClient, dict[str, str]]) -> None:
    c, h = dev
    good = {
        "name": "182-day T-bill (my entry)",
        "tenor": "182",
        "maturity": "2027-04-08",
        "yield_fraction": "0.0629",
        "citation": {
            "url": "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=63804",
            "as_of": "2026-10-14",
        },
    }
    assert c.post("/api/instruments/tbill", json=good, headers=h).status_code == 200
    assert c.post("/api/instruments/tbill", json={**good, "yield_fraction": 0.0629}, headers=h).status_code == 422
    bad_url = {**good, "citation": {"url": "http://example.com", "as_of": "2026-10-14"}}
    assert c.post("/api/instruments/tbill", json=bad_url, headers=h).status_code == 422
    items = c.get("/api/instruments?kind=tbill").json()["items"]
    assert items and items[0]["origin"] == "manual"


def test_instrument_search_escapes_like_wildcards(dev: tuple[TestClient, dict[str, str]]) -> None:
    c, h = dev
    c.post("/api/dev/seed-fixtures", json={}, headers=h)
    assert c.get("/api/instruments?q=%25").json()["items"] == []  # a literal "%" matches nothing
    assert len(c.get("/api/instruments?q=FIXTURE").json()["items"]) == 6


def test_data_health_and_methodology(dev: tuple[TestClient, dict[str, str]]) -> None:
    c, _ = dev
    health = c.get("/api/data-health").json()
    ids = {s["source_id"] for s in health["sources"]}
    assert "amfi.navall" in ids and health["tax_rules_loaded"] is True
    meth = c.get("/api/methodology").json()
    assert meth["versions"]["ranking_policy"] == "ranking_policy@1.2.0"
    assert any(r["verification"] == "NV" for r in meth["tax"]["rules"])


def test_data_health_jobs_lists_scheduled_job_problems(tmp_path: Path) -> None:
    """silent-failure-hunter-02 (d): cron failures and watchdog findings reach the API (codes only)."""
    from iip.store.db import connect

    c, _ = make(tmp_path, "dev")
    try:
        assert c.get("/api/data-health/jobs").json() == {"lookback_days": 14, "problems": []}
        raw = connect(Settings(env="dev", data_dir=tmp_path / "dev").db_path)
        raw.execute(
            "INSERT INTO cron_runs(job, run_key, state, started_at, finished_at, detail_code) VALUES"
            " ('snapshot', 'attempt:2026-10-15', 'failed', ?, ?, 'INTERNAL_ERROR'),"
            " ('watchdog', '2026-10-14', 'done', ?, ?, 'ATTENTION;SNAPSHOT_MISSING'),"
            " ('navall', '2026-10-14', 'done', ?, ?, 'STORED')",
            (NOW.isoformat(),) * 6,
        )
        raw.close()
        body = c.get("/api/data-health/jobs").json()
        assert [(p["job"], p["detail_code"]) for p in body["problems"]] == [
            ("snapshot", "INTERNAL_ERROR"),
            ("watchdog", "ATTENTION;SNAPSHOT_MISSING"),
        ]
    finally:
        c.__exit__(None, None, None)
