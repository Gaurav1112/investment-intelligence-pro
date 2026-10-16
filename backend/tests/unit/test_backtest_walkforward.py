"""Walk-forward timeline invariants (WP B05): lag, fill after decision, switch gap, vault split, costs coverage.
Synthetic panels only."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from decimal import Decimal

import pytest

from iip.engine.backtest import walkforward as wf
from iip.engine.backtest.ledger import CostBasisPolicy
from iip.engine.backtest.tax_lots import TaxRateTable
from iip.engine.errors import InvalidInput

D = Decimal
RISK, LIQ = "index_fund.x.direct", "liquid_fund.direct"


def _dates(n: int, start: date = date(2010, 1, 4)) -> tuple[date, ...]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return tuple(out)


def _panel(n: int = 2600) -> wf.NavPanel:
    dates = _dates(n)
    # Fictional deterministic paths: index i encoded in the NAV so a test can tell which observation was used.
    return wf.NavPanel(
        dates,
        {RISK: tuple(D(10) + D(i) / D(1000) for i in range(n)), LIQ: tuple(D(100) + D(i) / D(10000) for i in range(n))},
    )


def _setup(**kw: object) -> wf.BacktestSetup:
    base: dict[str, object] = {
        "strategy": wf.RuleSpec(kind="trend_sma", params={"lookback_months": 3}, slots={"risk": RISK, "out": LIQ}),
        "benchmark": wf.RuleSpec(kind="buy_and_hold", params={}, slots={"risk": RISK}),
        "config": wf.WalkForwardConfig(
            lag=1, purge=1, embargo=1, fill_rule=wf.FillRule(name="t", nav_offset=1, switch_cash_gap=3)
        ),
        "decision_every_months": 1,
        "initial_capital": D(100000),
        "contribution": D(0),
        "tax_classes": {RISK: "EQUITY", LIQ: "DEBT"},
        "costs": wf.MfCostSchedule(rows=(), slippage_rate=D(0)),
        "cost_policy": CostBasisPolicy(deductible_components=frozenset(), status="NOT VERIFIED"),
        "tax_table": TaxRateTable(rows=()),
        "vault": wf.VaultSpec(fraction=D("0.20"), min_months=12),
        "regimes": (wf.RegimeSpec(regime_id="all", start=None, end=None),),
    }
    base.update(kw)
    return wf.BacktestSetup(**base)  # type: ignore[arg-type]


def test_month_end_grid_excludes_the_final_month() -> None:
    dates = (date(2020, 1, 30), date(2020, 1, 31), date(2020, 2, 3), date(2020, 2, 28), date(2020, 3, 2))
    assert wf.month_end_indices(dates) == (1, 3)
    assert wf.decision_indices(dates, 2) == (1,)


def test_rule_sees_only_lagged_month_end_navs(monkeypatch: pytest.MonkeyPatch) -> None:
    panel = _panel()
    seen: list[tuple[int, Decimal]] = []
    real = wf.build_rule

    def spy(spec: wf.RuleSpec) -> wf.RuleFn:
        fn = real(spec)

        def wrapped(hist: Mapping[str, Sequence[Decimal]], view: wf.PortfolioView) -> Mapping[str, Decimal] | None:
            if spec.kind == "trend_sma":
                seen.append((len(hist[RISK]), hist[RISK][-1]))
            return fn(hist, view)

        return wrapped

    monkeypatch.setattr(wf, "build_rule", spy)
    res = wf.run_walk_forward(panel, _setup())
    grid = wf.month_end_indices(panel.dates)
    for length, last in seen:
        i = grid[length - 1]
        assert last == panel.navs[RISK][i - 1]  # NAV[decision − lag], never NAV[decision]
    assert res.leakage_checks == len(res.periods)


def test_switches_sell_after_the_decision_and_buy_after_the_cash_gap() -> None:
    panel = _panel()
    # Falling-then-rising risk NAV forces switches; check every realisation and lot date against decisions.
    n = len(panel.dates)
    navs = tuple(D(20) - D(i) / D(200) if i < n // 2 else D(7) + D(i - n // 2) / D(100) for i in range(n))
    panel = wf.NavPanel(panel.dates, {RISK: navs, LIQ: panel.navs[LIQ]})
    res = wf.run_walk_forward(panel, _setup())
    decisions = set(res.decision_dates)
    term = res.strategy.terminal
    assert res.strategy.n_trades >= 2
    assert term.as_of in decisions
    idx = {d: i for i, d in enumerate(panel.dates)}
    for d in decisions:
        assert d in idx
    for d in res.decision_dates[:-1]:
        assert idx[d] + 1 < len(panel.dates)


def test_decision_spacing_must_exceed_fill_plus_gap() -> None:
    cfg = wf.WalkForwardConfig(
        lag=0, purge=1, embargo=0, fill_rule=wf.FillRule(name="x", nav_offset=15, switch_cash_gap=10)
    )
    with pytest.raises(InvalidInput, match="closer than"):
        wf.run_walk_forward(_panel(), _setup(config=cfg))


@pytest.mark.parametrize("bad", [{"lag": -1}, {"purge": 0}, {"embargo": -1}, {"lag": True}, {"lag": 1.0}])
def test_config_values_are_strict(bad: dict[str, object]) -> None:
    kw: dict[str, object] = {
        "lag": 1,
        "purge": 1,
        "embargo": 1,
        "fill_rule": wf.FillRule(name="f", nav_offset=1, switch_cash_gap=0),
    }
    kw.update(bad)
    with pytest.raises(InvalidInput):
        wf.WalkForwardConfig(**kw)  # type: ignore[arg-type]


def test_vault_split() -> None:
    v = wf.VaultSpec(fraction=D("0.20"), min_months=36)
    assert wf.split_vault(100, v, 1) == 36
    assert wf.split_vault(300, v, 1) == 60
    assert wf.split_vault(20, v, 12) == 4


def test_max_drawdown() -> None:
    assert wf.max_drawdown([D("0.1"), D("-0.5"), D("0.2")]) == D("0.5")
    assert wf.max_drawdown([]) == D(0)


def test_uncovered_cost_rows_fail_closed() -> None:
    late = wf.CostRateRow(
        rule_id="FIC",
        component="stamp_duty",
        side="buy",
        tax_classes=frozenset({"EQUITY", "DEBT"}),
        rate=D("0.00005"),
        effective_from=date(2030, 1, 1),
        effective_to=None,
        status="VERIFIED-SECONDARY",
    )
    res = wf.run_walk_forward(_panel(), _setup(costs=wf.MfCostSchedule(rows=(late,), slippage_rate=D(0))))
    assert res.cost_rules_missing and wf.R_COST_RULES_MISSING in res.reason_codes
    assert res.tax_rules_missing  # empty tax table: fail closed, never a silent zero tax
    assert res.edge_after_tax is None


def test_unknown_rule_kind_is_refused() -> None:
    with pytest.raises(InvalidInput):
        wf.build_rule(wf.RuleSpec(kind="winner_fund", params={}, slots={}))
