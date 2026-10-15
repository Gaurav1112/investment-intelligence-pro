"""HTTP layer for the Track 1 data-input endpoints (/api/inputs/*) and the analysis outputs they unblock.

Instrument data is FIXTURE (synthetic). CPI, T-bill yields, factsheet facts and card rates are hand-made TEST values
with a test citation URL — not market data.
"""

import json
from datetime import timedelta
from typing import Any

import httpx
import pytest
from starlette.testclient import TestClient

from iip.data.fetch import Fetcher, RetryPolicy
from iip.engine.dates import add_months
from iip.services.explain import contract_errors, iter_explained
from tests.api.test_analysis_api import EQUITY, FD, LIQUID, NOW, api  # noqa: F401 - fixture re-export

API = tuple[TestClient, dict[str, str]]
CITE = "https://example.test/citation"
SHORT_DUR = "mf:900002"


def _no_floats(text: str) -> Any:
    return json.loads(text, parse_float=lambda s: pytest.fail(f"float in API response: {s}"))


def _contract(payload: Any) -> int:
    items = list(iter_explained(payload))
    assert [e for i in items for e in contract_errors(i)] == []
    return len(items)


def test_cpi_endpoints(api: API) -> None:  # noqa: F811
    c, h = api
    body = {"base_year": "2024", "month": "2026-09", "index": "104.2", "yoy_inflation_pct": "1.54",
            "provisional": True, "citation": {"url": CITE, "as_of": "2026-10-12"}}  # fmt: skip
    r = c.post("/api/inputs/cpi", json=body, headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {"series_id": "cpi:all-india:base2024", "outcome": "inserted"}
    old = {**body, "base_year": "2012", "month": "2025-12", "index": "195.0", "yoy_inflation_pct": None,
           "provisional": False, "citation": {"url": CITE, "as_of": "2026-01-12"}}  # fmt: skip
    assert c.post("/api/inputs/cpi", json=old, headers=h).status_code == 200
    out = _no_floats(c.get("/api/inputs/cpi").text)
    assert [(s["base_year"], [p["month"] for p in s["points"]]) for s in out["series"]] == [
        ("2012", ["2025-12"]), ("2024", ["2026-09"])]  # fmt: skip
    assert out["series"][1]["points"][0]["provisional"] is True
    assert c.post("/api/inputs/cpi", json={**body, "index": 104.2}, headers=h).status_code == 422
    assert c.post("/api/inputs/cpi", json={**body, "citation": {"url": CITE, "as_of": "2026-10-20"}},
                  headers=h).status_code == 422  # future release date  # fmt: skip
    assert c.post("/api/inputs/cpi", json=body).status_code in (401, 403)  # no CSRF → refused


def test_riskfree_endpoints(api: API) -> None:  # noqa: F811
    c, h = api
    assert c.get("/api/inputs/riskfree").json()["freshness"] == "UNAVAILABLE"
    r = c.post("/api/inputs/riskfree", json={"yield_fraction": "0.057281",
                                              "citation": {"url": CITE, "as_of": "2026-10-14"}}, headers=h)  # fmt: skip
    assert r.status_code == 200 and r.json()["series_id"] == "riskfree:tbill91"
    out = _no_floats(c.get("/api/inputs/riskfree").text)
    assert out["freshness"] == "FRESH" and out["latest"]["yield_fraction"] == "0.057281"
    bad = c.post(
        "/api/inputs/riskfree",
        json={"yield_fraction": "0.05", "citation": {"url": "ftp://x", "as_of": "2026-10-14"}},
        headers=h,
    )
    assert bad.status_code == 422


def test_fund_facts_endpoints_and_unblocked_rate_shock(api: API) -> None:  # noqa: F811
    c, h = api
    empty = c.get(f"/api/inputs/fund-facts/{SHORT_DUR}").json()
    assert empty["latest"] is None and empty["stale_after_days"] == 45
    body = {
        "as_of_month": "2026-09",
        "modified_duration": "2.5",
        "ytm": "0.0712",
        "expense_ratio": "0.0035",
        "expense_ratio_kind": "TER",
        "lowest_rating": "AAA",
        "citation": {"url": CITE, "as_of": "2026-10-10"},
    }
    r = c.post(f"/api/inputs/fund-facts/{SHORT_DUR}", json=body, headers=h)
    assert r.status_code == 200, r.text
    latest = _no_floats(c.get(f"/api/inputs/fund-facts/{SHORT_DUR}").text)["latest"]
    assert latest["as_of_date"] == "2026-09-30" and latest["freshness"] == "FRESH" and latest["ytm"] == "0.0712"
    assert c.post(f"/api/inputs/fund-facts/{FD}", json=body, headers=h).status_code == 422
    assert c.post("/api/inputs/fund-facts/mf:nope", json=body, headers=h).status_code == 404
    assert c.post(f"/api/inputs/fund-facts/{SHORT_DUR}", json={**body, "ytm": 0.07}, headers=h).status_code == 422
    sc = c.post("/api/scenario", json={"instrument_id": SHORT_DUR, "shocks": {"rate_bp": "100"}}, headers=h)
    entry = _no_floats(sc.text)["results"][0]
    assert entry["status"] == "applied" and entry["approximate"] is True
    fc = _no_floats(c.get(f"/api/forecast/{SHORT_DUR}?horizon_days=91").text)
    assert fc["yield_carry"]["status"] == "OK"
    _contract(sc.json())
    _contract(fc)


def test_fd_rate_endpoints_and_unblocked_early_exit(api: API) -> None:  # noqa: F811
    c, h = api
    body = {"institution": "FIXTURE Bank", "buckets": [{"min_days": 7, "max_days": 45, "rate": "0.03"},
                                                       {"min_days": 46, "max_days": 179, "rate": "0.055"}],
            "citation": {"url": CITE, "as_of": "2026-10-10"}}  # fmt: skip
    r = c.post("/api/inputs/fd-rates", json=body, headers=h)
    assert r.status_code == 200 and r.json()["institution_key"] == "fixture-bank"
    tables = c.get("/api/inputs/fd-rates").json()["tables"]
    assert len(tables) == 1 and [b["rate"] for b in tables[0]["buckets"]] == ["0.03", "0.055"]
    overlap = {**body, "buckets": [{"min_days": 7, "max_days": 50, "rate": "0.03"},
                                   {"min_days": 46, "max_days": 179, "rate": "0.055"}]}  # fmt: skip
    assert c.post("/api/inputs/fd-rates", json=overlap, headers=h).status_code == 422
    sc = c.post("/api/scenario", json={"instrument_id": FD, "shocks": {"exit_before_maturity_days": 60}}, headers=h)
    entry = _no_floats(sc.text)["results"][0]
    assert entry["status"] == "applied" and entry["scenario_id"] == "SCN_FD_PREMATURE@1"
    _contract(sc.json())


def test_inflation_shock_and_sharpe_unblocked_over_http(api: API) -> None:  # noqa: F811
    c, h = api
    cpi = {"base_year": "2024", "month": "2026-09", "index": "104.2", "yoy_inflation_pct": "1.54",
           "citation": {"url": CITE, "as_of": "2026-10-12"}}  # fmt: skip
    assert c.post("/api/inputs/cpi", json=cpi, headers=h).status_code == 200
    sc = _no_floats(c.post("/api/scenario", json={"instrument_id": LIQUID, "shocks": {"inflation_pct": "2"}},
                           headers=h).text)  # fmt: skip
    assert sc["results"][0]["status"] == "applied"
    cmp_ = _no_floats(c.post("/api/compare", json={"instrument_ids": [FD, LIQUID]}, headers=h).text)
    assert cmp_["rows"][0]["real_return"]["q50"]["formula_id"] == "FISHER@1"
    d = add_months(NOW.date() - timedelta(days=1), -36) - timedelta(days=10)
    while d < NOW.date():
        r = c.post(
            "/api/inputs/riskfree",
            json={"yield_fraction": "0.065", "citation": {"url": CITE, "as_of": d.isoformat()}},
            headers=h,
        )
        assert r.status_code == 200
        d += timedelta(days=7)
    rk = _no_floats(c.get(f"/api/risk/{EQUITY}").text)
    assert rk["metrics"]["sharpe"].get("status") != "refused", rk["metrics"]["sharpe"]
    for payload in (sc, cmp_, rk):
        _contract(payload)


def test_mospi_status_and_fetch(api: API, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, h = api
    for var in ("IIP_MOSPI_TOKEN", "IIP_MOSPI_USER", "IIP_MOSPI_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    st = c.get("/api/inputs/mospi/status").json()
    assert st["status"] == "REQUIRES_CONFIGURATION" and st["verified"] is False
    r = c.post("/api/inputs/mospi/fetch", json={"base_year": 2024, "year": 2026, "month": 9}, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "REQUIRES_CONFIGURATION"

    monkeypatch.setenv("IIP_MOSPI_TOKEN", "tok-test")
    assert c.get("/api/inputs/mospi/status").json()["status"] == "CONFIGURED"
    record = {
        "baseyear": "2024",
        "year": 2026,
        "month": "September",
        "state": "All India",
        "sector": "Combined",
        "group": "General",
        "subgroup": "General",
        "index": "123.4",
        "inflation": "1.11",
        "status": "F",
    }

    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/json"}, json={"data": [record]})

    c.app.app.state.iip.fetcher_factory = lambda: Fetcher(  # type: ignore[attr-defined]
        transport=httpx.MockTransport(handler), resolver=lambda _h: ["23.0.0.1"], clock=lambda: NOW,
        retry=RetryPolicy(max_attempts=1), sleep=lambda _s: None,
    )  # fmt: skip
    r = c.post("/api/inputs/mospi/fetch", json={"base_year": 2024, "year": 2026, "month": 9}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "stored" and r.json()["verified"] is False
    pts = c.get("/api/inputs/cpi").json()["series"][1]["points"]
    assert pts[0]["index"] == "123.4" and pts[0]["source_id"] == "mospi.cpi" and pts[0]["quality_status"] == "ok"
    assert "tok-test" not in json.dumps(c.get("/api/inputs/mospi/status").json())
