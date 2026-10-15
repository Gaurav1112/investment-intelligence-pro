"""Every Explained number in every API response obeys ONE contract (ux-design §5.1), and the frontend's freshness
vocabulary matches the backend's exactly."""

import re
from pathlib import Path
from typing import Any

from starlette.testclient import TestClient

from iip.services.explain import FRESHNESS, contract_errors, iter_explained
from tests.api.test_analysis_api import EQUITY, FD, LIQUID, TBILL, api  # noqa: F401 - fixture re-export


def _all_errors(payload: Any) -> tuple[int, list[str]]:
    items = list(iter_explained(payload))
    return len(items), [e for item in items for e in contract_errors(item)]


def test_every_explained_value_obeys_the_contract(api: tuple[TestClient, dict[str, str]]) -> None:  # noqa: F811
    c, h = api
    profile = {"amount": "500000", "withdrawal_date": "2027-04-15", "objective": "A_capital_preservation",
               "loss_acceptable": False, "early_need": "possible", "max_days_to_cash": 7}  # fmt: skip
    assert c.put("/api/profile", json=profile, headers=h).status_code == 200
    responses = {
        "discover": c.post("/api/discover", json={"include_fixtures": True}, headers=h).json(),
        "compare": c.post("/api/compare", json={"instrument_ids": [TBILL, FD, LIQUID, EQUITY]}, headers=h).json(),
        "simulate": c.post("/api/simulate", json={"allocations": [{"instrument_id": TBILL, "weight": "0.5"},
                                                                  {"instrument_id": LIQUID, "weight": "0.5"}]},
                           headers=h).json(),
        "scenario": c.post("/api/scenario", json={"instrument_id": EQUITY, "shocks": {"equity_pct": "-0.10"}},
                           headers=h).json(),
        "risk": c.get(f"/api/risk/{EQUITY}").json(),
        "forecast": c.get(f"/api/forecast/{LIQUID}?horizon_days=91").json(),
        "feasibility": c.post("/api/feasibility", json={"instrument_id": EQUITY, "target_annual": "0.20",
                                                        "horizon_years": 1}, headers=h).json(),
    }  # fmt: skip
    pid = c.post("/api/portfolios", json={"name": "contract", "nature": "hypothetical"}, headers=h).json()[
        "portfolio_id"
    ]
    txn = {"instrument_id": LIQUID, "txn_type": "buy", "txn_date": "2025-01-10", "units": "100", "amount": "1000.00"}
    assert c.post(f"/api/portfolios/{pid}/transactions", json=txn, headers=h).status_code == 200
    responses["summary"] = c.get(f"/api/portfolios/{pid}/summary").json()

    total = 0
    problems: list[str] = []
    for name, payload in responses.items():
        n, errs = _all_errors(payload)
        total += n
        problems += [f"{name}: {e}" for e in errs]
    assert total > 50, "expected many Explained values across the responses"
    assert problems == []


def test_frontend_freshness_type_matches_backend_vocabulary() -> None:
    types_ts = Path(__file__).resolve().parents[3] / "frontend" / "src" / "lib" / "types.ts"
    m = re.search(r"export type Freshness\s*=\s*([^;]+);", types_ts.read_text())
    assert m, "Freshness union not found in frontend/src/lib/types.ts"
    frontend = set(re.findall(r'"([A-Z_]+)"', m.group(1)))
    assert frontend == set(FRESHNESS), f"frontend {sorted(frontend)} != backend {sorted(FRESHNESS)}"


def test_feasibility_headline_names_the_instrument_not_an_internal_id(api: tuple[TestClient, dict[str, str]]) -> None:  # noqa: F811
    c, h = api
    out = c.post("/api/feasibility", json={"instrument_id": LIQUID, "target_annual": "0.065", "horizon_years": 1},
                 headers=h).json()  # fmt: skip
    assert "nav:" not in out["headline"] and "FIXTURE Liquid Fund A" in out["headline"]
