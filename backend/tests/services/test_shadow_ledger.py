"""B02: the daily shadow ledger and outcomes. Acceptance checks:

* every registered S rule gets a daily ``rule_evaluations`` row (PRE_REGISTERED and ABSTAIN rules included), and is
  NEVER shown as an action;
* outcomes are scored once, at the rule's horizon.

All NAVs, ids and rates are SYNTHETIC and fictional (no market data, no real scheme, no real tax rate claim).
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from iip.engine.money import engine_context
from iip.services import outcomes as oc
from iip.services import risk_snapshot as rs
from iip.services import shadow
from iip.store import ledger
from tests.services import _snapshot_fixtures as fx

TREND = """id: S-X
version: 1
family: trend_timing
roles: {in: index_fund.fictional.direct, out: liquid_fund.fictional.direct}
params: {lookback_months: 3}
horizon_months: 1
"""
MOMENTUM = """id: S-Y
version: 1
family: absolute_momentum
roles: {in: index_fund.fictional.direct, hurdle: liquid_fund.fictional.direct}
params: {lookback_months: 3, skip_months: 1}
horizon_months: 1
"""
UNKNOWN = """id: S-Z
version: 1
family: dual_momentum
"""
EQ, LIQ = "mf:971001", "mf:971002"

# Fictional rates, chosen for easy arithmetic (not a claim about any real rate).
BASIS = oc.CostTaxBasis(
    stamp_duty=Decimal("0"), stt_equity_redemption=Decimal("0"), exit_load=Decimal("0"),
    equity_short_rate=Decimal("0.2"), equity_long_rate=Decimal("0.1"), other_rate=Decimal("0.3"), cess=Decimal("0"),
    sources=("synthetic test basis",),
)  # fmt: skip


def _grid(conn: Any, iid: str, navs: dict[str, str]) -> None:
    ledger.upsert_series_grid(
        conn, [ledger.GridPoint(iid, m, f"{m}-28", Decimal(v), None, fx.NOW) for m, v in sorted(navs.items())]
    )


@pytest.fixture
def conn(tmp_path: Path) -> Any:
    c = fx.open_db(tmp_path / "iip.db")
    fx.add_scheme(c, EQ, "971001", "Fictional Index Fund", "Equity Scheme - Large Cap Fund")
    fx.add_scheme(c, LIQ, "971002", "Fictional Liquid Fund", "Debt Scheme - Liquid Fund")
    ledger.bind_roles(
        c,
        [ledger.RoleBinding("index_fund.fictional.direct", EQ, "fixture", fx.NOW),
         ledger.RoleBinding("liquid_fund.fictional.direct", LIQ, "fixture", fx.NOW)],
    )  # fmt: skip
    # completed months before 2026-10: rising equity (trend: in), liquid creeping up
    _grid(c, EQ, {"2026-06": "100", "2026-07": "110", "2026-08": "120", "2026-09": "130"})
    _grid(c, LIQ, {"2026-06": "10", "2026-07": "10.1", "2026-08": "10.2", "2026-09": "10.3"})
    yield c
    c.close()


def _rows(conn: Any) -> list[Any]:
    return list(conn.execute("SELECT * FROM rule_evaluations ORDER BY rule_id, as_of_date"))


# --------------------------------------------------------------------------------------------- shadow ledger


def test_every_registered_s_rule_gets_a_daily_row(conn: Any) -> None:
    fx.register_s_rule(conn, "S-X", TREND)
    fx.register_s_rule(conn, "S-Y", MOMENTUM, state="ABSTAIN")
    fx.register_s_rule(conn, "S-Z", UNKNOWN)
    fx.register_s_rule(conn, "S-R", TREND.replace("S-X", "S-R"), state="RETIRED")
    run = shadow.run_shadow(conn, as_of=fx.AS_OF, snapshot_id="a" * 64, now=fx.NOW)
    assert (run.rules, run.written) == (3, 3)
    rows = {r["rule_id"]: r for r in _rows(conn)}
    assert set(rows) == {"S-X", "S-Y", "S-Z"}  # RETIRED is no longer evaluated
    assert rows["S-X"]["state"] == "PRE_REGISTERED" and rows["S-Y"]["state"] == "ABSTAIN"
    z = json.loads(rows["S-Z"]["payload_json"])
    assert rows["S-Z"]["condition_met"] is None and z["reason"] == "evaluator_not_implemented"
    assert all(json.loads(r["payload_json"])["shown_as_action"] is False for r in rows.values())

    again = shadow.run_shadow(conn, as_of=fx.AS_OF, snapshot_id="a" * 64, now="2026-10-16T09:00:00+00:00")
    assert (again.written, again.already_recorded) == (0, 3)
    nxt = shadow.run_shadow(conn, as_of=date(2026, 10, 16), snapshot_id="b" * 64, now=fx.NOW)
    assert nxt.written == 3 and len(_rows(conn)) == 6


def test_trend_condition_uses_completed_months_only(conn: Any) -> None:
    fx.register_s_rule(conn, "S-X", TREND)
    _grid(conn, EQ, {"2026-10": "1"})  # a part-month point for the as-of month must be ignored
    shadow.run_shadow(conn, as_of=fx.AS_OF, snapshot_id="a" * 64, now=fx.NOW)
    row = _rows(conn)[0]
    p = json.loads(row["payload_json"])
    assert p["observation_month"] == "2026-09" and p["months_used"] == ["2026-07", "2026-08", "2026-09"]
    assert row["condition_met"] == 1  # 130 > mean(110, 120, 130)
    assert p["horizon_end"] == "2026-10-31" and row["scope_id"] == "role:index_fund.fictional.direct"


def test_trend_condition_not_met(conn: Any) -> None:
    fx.register_s_rule(conn, "S-X", TREND)
    _grid(conn, EQ, {"2026-09": "90"})  # 90 < mean(110, 120, 90)
    shadow.run_shadow(conn, as_of=fx.AS_OF, snapshot_id="a" * 64, now=fx.NOW)
    assert _rows(conn)[0]["condition_met"] == 0


def test_momentum_vs_liquid_hurdle(conn: Any) -> None:
    fx.register_s_rule(conn, "S-Y", MOMENTUM)
    shadow.run_shadow(conn, as_of=fx.AS_OF, snapshot_id="a" * 64, now=fx.NOW)
    row = _rows(conn)[0]
    # 12-1 style with L=3, S=1: R = C(2026-08)/C(2026-06) − 1 → equity 0.20 > liquid 0.02
    assert json.loads(row["payload_json"])["months_used"] == ["2026-06", "2026-08"]
    assert row["condition_met"] == 1


def test_unbound_role_and_short_history_abstain_with_a_row(conn: Any) -> None:
    fx.register_s_rule(conn, "S-X", TREND.replace("liquid_fund.fictional.direct", "liquid_fund.unbound"))
    fx.register_s_rule(conn, "S-Q", TREND.replace("S-X", "S-Q").replace("lookback_months: 3", "lookback_months: 9"))
    shadow.run_shadow(conn, as_of=fx.AS_OF, snapshot_id="a" * 64, now=fx.NOW)
    rows = {r["rule_id"]: json.loads(r["payload_json"]) for r in _rows(conn)}
    assert rows["S-X"]["reason"] == "role_unbound:liquid_fund.unbound"
    assert rows["S-Q"]["reason"] == "insufficient_history"


def test_s_rules_are_never_shown_as_actions(conn: Any) -> None:
    fx.seed_two_goals(conn)
    fx.register_s_rule(conn, "S-X", TREND)
    daily = rs.run_daily(conn, as_of=fx.AS_OF, now=fx.NOW, stress_table=fx.stress_table(), templates=fx.TEMPLATES)
    assert daily.shadow.written == 1
    row = _rows(conn)[0]
    assert row["condition_met"] == 1 and row["snapshot_id"] == daily.snapshot.snapshot_id
    today = rs.read_today(conn)
    blob = json.dumps(today)
    assert "S-X" not in blob and "SIGNAL_TILT" not in blob
    assert all(c["kind"] != "SIGNAL_TILT" for c in today["cards"])


# --------------------------------------------------------------------------------------------- outcomes


def _evaluate(conn: Any, spec: str = TREND, rule: str = "S-X") -> None:
    fx.register_s_rule(conn, rule, spec)
    shadow.run_shadow(conn, as_of=fx.AS_OF, snapshot_id="a" * 64, now=fx.NOW)


def test_outcome_waits_for_the_horizon_then_scores_once(conn: Any) -> None:
    fx.register_s_rule(conn, "S-X", TREND)
    _grid(conn, EQ, {"2026-09": "90"})  # condition not met → the rule holds the liquid fund
    shadow.run_shadow(conn, as_of=fx.AS_OF, snapshot_id="a" * 64, now=fx.NOW)
    before = oc.score_outcomes(conn, as_of=date(2026, 10, 31), now=fx.NOW, basis=BASIS)
    assert before.not_yet_due == 0 and before.waiting_for_data == 1  # horizon reached, Oct month-end not in grid yet
    early = oc.score_outcomes(conn, as_of=date(2026, 10, 20), now=fx.NOW, basis=BASIS)
    assert early.not_yet_due == 1 and early.scored == 0
    _grid(conn, EQ, {"2026-10": "99"})
    _grid(conn, LIQ, {"2026-10": "10.4"})
    run = oc.score_outcomes(conn, as_of=date(2026, 11, 2), now=fx.NOW, basis=BASIS)
    assert run.scored == 1
    out = conn.execute("SELECT * FROM outcomes").fetchone()
    assert out["status"] == "scored" and out["horizon_end"] == "2026-10-31"
    with engine_context():
        held = (Decimal("10.4") / Decimal("10.3") - 1) * (1 - Decimal("0.3"))  # liquid, gain taxed at 0.3
        bench = Decimal("99") / Decimal("90") - 1 - (Decimal("99") / Decimal("90") - 1) * Decimal("0.2")
        expected = held - bench
    assert abs(Decimal(out["edge_after_cost_tax"]) - expected) < Decimal("1e-25")  # same value, Decimal rounding
    assert Decimal(out["edge_after_cost_tax"]) < 0  # being out missed the equity fund's rise from 90 to 99
    again = oc.score_outcomes(conn, as_of=date(2026, 11, 3), now=fx.NOW, basis=BASIS)
    assert again.scored == 0 and conn.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0] == 1


def test_condition_met_keeps_the_benchmark_and_scores_zero(conn: Any) -> None:
    _evaluate(conn)
    _grid(conn, EQ, {"2026-10": "140"})
    _grid(conn, LIQ, {"2026-10": "10.4"})
    assert oc.score_outcomes(conn, as_of=date(2026, 11, 2), now=fx.NOW, basis=BASIS).scored == 1
    assert Decimal(conn.execute("SELECT edge_after_cost_tax FROM outcomes").fetchone()[0]) == 0


def test_no_basis_means_nothing_is_scored(conn: Any) -> None:
    _evaluate(conn)
    _grid(conn, EQ, {"2026-10": "140"})
    _grid(conn, LIQ, {"2026-10": "10.4"})
    run = oc.score_outcomes(conn, as_of=date(2026, 11, 2), now=fx.NOW, basis=None)
    assert run.waiting_for_basis == 1 and conn.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0] == 0


def test_abstained_evaluation_is_unscorable_at_its_horizon(conn: Any) -> None:
    _evaluate(conn, TREND.replace("lookback_months: 3", "lookback_months: 9"))
    assert oc.score_outcomes(conn, as_of=date(2026, 10, 20), now=fx.NOW, basis=BASIS).not_yet_due == 1
    run = oc.score_outcomes(conn, as_of=date(2026, 11, 2), now=fx.NOW, basis=BASIS)
    assert run.unscorable == 1
    row = conn.execute("SELECT * FROM outcomes").fetchone()
    assert row["status"] == "unscorable" and row["unscorable_reason"] == "evaluation_abstained:insufficient_history"


def test_missing_nav_after_grace_is_unscorable(conn: Any) -> None:
    _evaluate(conn)
    run = oc.score_outcomes(conn, as_of=date(2026, 12, 31), now=fx.NOW, basis=BASIS)
    assert run.unscorable == 1
    assert conn.execute("SELECT unscorable_reason FROM outcomes").fetchone()[0] == "nav_missing"


def test_net_return_formula() -> None:
    basis = oc.CostTaxBasis(
        stamp_duty=Decimal("0.001"), stt_equity_redemption=Decimal("0.002"), exit_load=Decimal("0.01"),
        equity_short_rate=Decimal("0.2"), equity_long_rate=Decimal("0.1"), other_rate=Decimal("0.3"),
        cess=Decimal("0.04"), sources=("synthetic",),
    )  # fmt: skip
    with engine_context():
        proceeds = (1 - Decimal("0.001")) / Decimal(100) * Decimal(120) * (1 - Decimal("0.012"))
        expected = proceeds - (proceeds - 1) * Decimal("0.2") * Decimal("1.04") - 1
    assert oc.net_return(Decimal(100), Decimal(120), equity=True, months=1, basis=basis) == expected
    # a loss earns no tax credit
    with engine_context():
        loss = (1 - Decimal("0.001")) / Decimal(100) * Decimal(80) * (1 - Decimal("0.01")) - 1
    assert oc.net_return(Decimal(100), Decimal(80), equity=False, months=1, basis=basis) == loss
    with pytest.raises(ValueError):
        oc.CostTaxBasis(Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"),
                        Decimal("0"), ())  # fmt: skip
