"""HTTP layer for the Stage D analysis endpoints. Instrument data is FIXTURE (synthetic) via /api/dev/seed-fixtures."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from iip.api.app import create_app
from iip.api.routes import all_routers
from iip.api.settings import Settings

ORIGIN = "http://127.0.0.1:8741"
NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
TBILL = "tbill:182d:2027-04-13"
FD = "fd:fixture-bank:180d"
LIQUID, EQUITY = "mf:900001", "mf:900003"


@pytest.fixture
def api(tmp_path: Path) -> Iterator[tuple[TestClient, dict[str, str]]]:
    settings = Settings(env="dev", data_dir=tmp_path / "dev")
    c = TestClient(create_app(settings, routers=all_routers(), clock=lambda: NOW), base_url=ORIGIN)
    c.__enter__()
    token = settings.token_path.read_text().strip()
    csrf = c.post("/api/session", json={"token": token}, headers={"Origin": ORIGIN}).json()["csrf"]
    h = {"Origin": ORIGIN, "X-IIP-CSRF": csrf}
    assert c.post("/api/dev/seed-fixtures", json={}, headers=h).status_code == 200
    yield c, h
    c.__exit__(None, None, None)


def _json_no_floats(text: str) -> Any:
    return json.loads(text, parse_float=lambda s: pytest.fail(f"float in API response: {s}"))


def test_compare_endpoint(api: tuple[TestClient, dict[str, str]]) -> None:
    c, h = api
    body = {"instrument_ids": [TBILL, FD, LIQUID], "amount": "500000", "withdrawal_date": "2027-04-15"}
    r = c.post("/api/compare", json=body, headers=h)
    assert r.status_code == 200, r.text
    out = _json_no_floats(r.text)
    assert out["fixture"] is True and len(out["rows"]) == 3 and len(out["what_would_change_order"]) == 2
    again = c.post("/api/compare", json=body, headers=h).json()
    assert again["run"]["result_hash"] == out["run"]["result_hash"]


def test_scenario_simulate_feasibility_forecast_risk_endpoints(api: tuple[TestClient, dict[str, str]]) -> None:
    c, h = api
    sc = c.post("/api/scenario", json={"instrument_id": EQUITY, "shocks": {"equity_pct": "0"}}, headers=h)
    assert sc.status_code == 200, sc.text
    assert _json_no_floats(sc.text)["results"][0]["values"][1]["impact"]["value"] == "0.00"
    sim = c.post(
        "/api/simulate",
        json={"allocations": [{"instrument_id": LIQUID, "weight": "0.25"}, {"instrument_id": FD, "weight": "0.75"}],
              "amount": "100000.03", "withdrawal_date": "2027-04-15"},
        headers=h,
    )  # fmt: skip
    assert sim.status_code == 200, sim.text
    s = _json_no_floats(sim.text)
    assert [x["allocation"]["value"] for x in s["holdings"]] == ["25000.01", "75000.02"]
    fe = c.post("/api/feasibility", json={"instrument_id": EQUITY, "target_annual": "0.20", "horizon_years": 1},
                headers=h)  # fmt: skip
    assert fe.status_code == 200 and _json_no_floats(fe.text)["status"] == "SUFFICIENT"
    fc = c.get("/api/forecast/mf:900002?horizon_days=91")
    assert fc.status_code == 200 and _json_no_floats(fc.text)["promotion"]["status"] == "baseline retained"
    rk = c.get(f"/api/risk/{LIQUID}")
    assert rk.status_code == 200 and _json_no_floats(rk.text)["metrics"]["volatility"]["status"] == "refused"


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/compare", {"instrument_ids": [LIQUID]}),
        ("/api/compare", {"instrument_ids": [LIQUID, LIQUID]}),
        ("/api/compare", {"instrument_ids": [LIQUID, FD], "amount": 100000.5}),
        ("/api/compare", {"instrument_ids": [LIQUID, FD], "amount": "100.001"}),
        ("/api/compare", {"instrument_ids": [LIQUID, FD], "withdrawal_date": "2026-10-01"}),
        ("/api/compare", {"instrument_ids": [LIQUID, FD], "extra": 1}),
        ("/api/scenario", {"instrument_id": EQUITY, "shocks": {}}),
        ("/api/scenario", {"instrument_id": EQUITY, "shocks": {"equity_pct": "10"}}),
        ("/api/scenario", {"instrument_id": EQUITY, "shocks": {"rate_bp": 50.5}}),
        ("/api/simulate", {"allocations": [{"instrument_id": LIQUID, "weight": "0.5"},
                                           {"instrument_id": FD, "weight": "0.49"}]}),
        ("/api/simulate", {"allocations": [{"instrument_id": LIQUID, "weight": 1}]}),
        ("/api/simulate", {"allocations": [{"instrument_id": LIQUID, "weight": 1.0}]}),
        ("/api/feasibility", {"instrument_id": EQUITY, "target_annual": "0.2", "horizon_years": 2}),
        ("/api/feasibility", {"instrument_id": EQUITY, "target_annual": 0.2, "horizon_years": 1}),
        ("/api/feasibility", {"instrument_id": FD, "target_annual": "0.2", "horizon_years": 1}),
    ],
)  # fmt: skip
def test_validation_errors_are_422(api: tuple[TestClient, dict[str, str]], path: str, body: dict[str, Any]) -> None:
    c, h = api
    r = c.post(path, json=body, headers=h)
    assert r.status_code == 422, (path, body, r.text)


def test_get_validation_and_not_found(api: tuple[TestClient, dict[str, str]]) -> None:
    c, h = api
    assert c.get("/api/forecast/mf:900002?horizon_days=0").status_code == 422
    assert c.get(f"/api/risk/{FD}").status_code == 422
    assert c.get("/api/risk/mf:nope").status_code == 404
    r = c.post("/api/compare", json={"instrument_ids": [LIQUID, "mf:nope"]}, headers=h)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "NOT_FOUND"


def test_auth_and_csrf_enforced(api: tuple[TestClient, dict[str, str]], tmp_path: Path) -> None:
    c, h = api
    body = {"instrument_ids": [LIQUID, FD]}
    no_csrf = {"Origin": ORIGIN}
    for path, payload in (
        ("/api/compare", body),
        ("/api/scenario", {"instrument_id": EQUITY, "shocks": {"equity_pct": "-5"}}),
        ("/api/simulate", {"allocations": [{"instrument_id": LIQUID, "weight": "1"}]}),
        ("/api/feasibility", {"instrument_id": EQUITY, "target_annual": "0.2", "horizon_years": 1}),
    ):
        assert c.post(path, json=payload, headers=no_csrf).status_code == 403, path
        assert c.post(path, json=payload, headers={**h, "X-IIP-CSRF": "wrong"}).status_code == 403, path
    fresh = TestClient(create_app(Settings(env="dev", data_dir=tmp_path / "anon"), routers=all_routers(),
                                  clock=lambda: NOW), base_url=ORIGIN)  # fmt: skip
    with fresh:
        assert fresh.post("/api/compare", json=body, headers={"Origin": ORIGIN}).status_code == 401
        assert fresh.get(f"/api/risk/{EQUITY}").status_code == 401
        assert fresh.get(f"/api/forecast/{EQUITY}").status_code == 401
