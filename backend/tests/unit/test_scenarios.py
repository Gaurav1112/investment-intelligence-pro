"""Scenario fixtures: calculation-methodology §2.11, §4.4, §4.7, §4.8, §4.9; risk-methodology §7.4–7.5."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from iip.engine.determinism import canonical_json
from iip.engine.errors import InvalidInput
from iip.engine.money import D
from iip.engine.scenarios import (
    BulletBond,
    ScenarioLabel,
    aggregate_portfolio,
    bond_analytics,
    bond_rate_shock,
    bond_spread_shock,
    early_sale,
    early_sale_grid,
    equity_drawdown_shock,
    inflation_scenario,
    liquidity_deterioration,
    rate_shock_duration,
    real_return,
    reinvestment_scenario,
    spread_shock_duration,
)


def near(value: Decimal, expected: str, tol: str = "5e-5") -> bool:
    return abs(value - Decimal(expected)) <= Decimal(tol)


D1 = BulletBond(coupon_rate=D("0.08"), frequency=2, periods_remaining=6)
D2 = BulletBond(coupon_rate=D("0.071"), frequency=2, periods_remaining=19, first_period_fraction=D(179) / D(180))
SP1 = BulletBond(coupon_rate=D("0.09"), frequency=1, periods_remaining=5)


class TestBondAnalytics:
    def test_d1(self) -> None:
        a = bond_analytics(D1, D("0.08"))
        assert near(a.dirty_price, "100.0000", "1e-9")
        assert near(a.macaulay_duration, "2.7259")
        assert near(a.modified_duration, "2.6211")
        assert near(a.convexity, "8.5329")
        assert near(a.dv01, str(a.modified_duration * a.dirty_price * D("0.0001")), "1e-20")

    def test_d2_y2(self) -> None:
        a = bond_analytics(D2, D("0.065"))
        assert near(a.clean_price, "104.2024")
        assert near(a.accrued_interest, "0.0197")
        assert near(a.dirty_price, "104.2221")
        assert near(a.macaulay_duration, "7.1215")
        assert near(a.modified_duration, "6.8973")
        assert near(a.convexity, "60.0072", "5e-5")

    def test_sp1(self) -> None:
        a = bond_analytics(SP1, D("0.08"))
        assert near(a.dirty_price, "103.9927")
        assert near(a.macaulay_duration, "4.2559")
        assert near(a.modified_duration, "3.9406")

    def test_y3_par(self) -> None:
        assert near(bond_analytics(D1, D("0.08")).clean_price, "100", "1e-25")

    def test_invalid_bond(self) -> None:
        with pytest.raises(InvalidInput):
            BulletBond(coupon_rate=D("0.08"), frequency=3, periods_remaining=6)
        with pytest.raises(InvalidInput):
            BulletBond(coupon_rate=D("0.08"), frequency=2, periods_remaining=0)
        with pytest.raises(InvalidInput):
            BulletBond(coupon_rate=D("0.08"), frequency=2, periods_remaining=3, first_period_fraction=D(0))


class TestRateShock:
    def test_d1_approximation(self) -> None:
        res = rate_shock_duration(D(100000), D("2.6211"), D("0.01"), convexity=D("8.5329"))
        assert near(res.impact_fraction * 100, "-2.5784", "5e-4")
        assert res.approximate
        assert res.label is ScenarioLabel.STRESS
        assert res.input("delta_yield") == D("0.01")
        assert res.input("modified_duration") == D("2.6211")

    @pytest.mark.parametrize(
        ("bp", "exact", "dur_conv", "dur_only"),
        [
            (50, "-3.3749", "-3.3737", "-3.4487"),
            (-50, "3.5249", "3.5237", "3.4487"),
            (200, "-12.6678", "-12.5946", "-13.7947"),
        ],
    )
    def test_d2_table(self, bp: int, exact: str, dur_conv: str, dur_only: str) -> None:
        dy = D(bp) / D(10000)
        res = bond_rate_shock(D2, D("0.065"), dy, position_value=D(100))
        assert not res.approximate  # full repricing headline
        assert near(res.impact_fraction * 100, exact, "1e-4")
        assert near(res.output("approx_duration_convexity") * 100, dur_conv, "1e-4")
        assert near(res.output("approx_duration_only") * 100, dur_only, "1e-4")

    def test_d1_exact_plus_100(self) -> None:
        res = bond_rate_shock(D1, D("0.08"), D("0.01"), position_value=D(100))
        assert near(res.output("shocked_dirty_price"), "97.4211")
        assert near(res.impact_fraction * 100, "-2.5789", "1e-4")

    def test_large_shock_on_fund_is_flagged(self) -> None:
        res = rate_shock_duration(D(100), D("5"), D("0.02"), convexity=D("30"))
        assert "FULL_REPRICING_UNAVAILABLE_LARGE_SHOCK" in res.caveats

    def test_missing_convexity_and_stale_duration(self) -> None:
        res = rate_shock_duration(
            D(100), D("3"), D("0.01"), duration_as_of=date(2025, 1, 1), as_of=date(2025, 1, 1) + timedelta(days=46)
        )
        assert "CONVEXITY_NOT_PROVIDED" in res.caveats
        assert "STALE_DURATION" in res.caveats

    def test_negative_duration_rejected(self) -> None:
        with pytest.raises(InvalidInput):
            rate_shock_duration(D(100), D("-1"), D("0.01"))


class TestSpread:
    def test_sp1_exact_and_approx(self) -> None:
        res = bond_spread_shock(
            SP1, gsec_yield=D("0.065"), spread=D("0.015"), delta_spread=D("0.01"), position_value=D(100)
        )
        assert near(res.output("shocked_dirty_price"), "100.0000")
        assert near(res.impact_fraction * 100, "-3.8394", "1e-4")
        assert near(res.output("approx_spread_duration") * 100, "-3.9406", "1e-4")
        assert res.input("delta_yield") == D(0)

    def test_spread_duration_approx(self) -> None:
        res = spread_shock_duration(D(1000), D("3.9406"), D("0.01"))
        assert near(res.impact, "-39.406", "1e-9")
        assert res.approximate

    def test_spread_and_rate_combine_additively(self) -> None:
        both = bond_spread_shock(
            SP1,
            gsec_yield=D("0.065"),
            spread=D("0.015"),
            delta_spread=D("0.005"),
            delta_yield=D("0.005"),
            position_value=D(100),
        )
        one = bond_rate_shock(SP1, D("0.08"), D("0.01"), position_value=D(100))
        assert both.impact == one.impact


class TestEquityInflationLiquidity:
    @pytest.mark.parametrize(("shock", "loss"), [("-0.10", "-10000"), ("-0.20", "-20000"), ("-0.35", "-35000")])
    def test_equity(self, shock: str, loss: str) -> None:
        res = equity_drawdown_shock(D(100000), D(shock), beta=D(1))
        assert res.impact == D(loss)

    def test_equity_beta(self) -> None:
        res = equity_drawdown_shock(D(100000), D("-0.20"), beta=D("1.2"))
        assert res.impact == D("-24000")

    def test_equity_bounds(self) -> None:
        with pytest.raises(InvalidInput):
            equity_drawdown_shock(D(100), D("0.1"), beta=D(1))
        with pytest.raises(InvalidInput):
            equity_drawdown_shock(D(100), D("-0.8"), beta=D("1.5"))  # > 100 % loss

    @pytest.mark.parametrize(
        ("nom", "infl", "real", "approx"),
        [
            ("0.07", "0.05", "1.9048", "2.00"),
            ("0.065", "0.054", "1.0436", "1.10"),
            ("0.04", "0.06", "-1.8868", "-2.00"),
        ],
    )
    def test_fisher(self, nom: str, infl: str, real: str, approx: str) -> None:
        res = real_return(D(nom), D(infl))
        assert near(res.value * 100, real)
        assert res.approximation * 100 == D(approx)
        assert res.method_id == "FISHER@1"

    def test_inflation_scenario(self) -> None:
        res = inflation_scenario(
            D(100000), nominal_return=D("0.07"), base_inflation=D("0.05"), delta_inflation=D("0.01")
        )
        assert near(res.output("real_return_base") * 100, "1.9048")
        assert near(res.output("real_return_shocked"), str(D("1.07") / D("1.06") - 1), "1e-25")
        assert res.measure == "real_inr"
        assert res.impact < 0

    def test_liquidity(self) -> None:
        res = liquidity_deterioration(D(100000), exit_cost=D("0.01"), haircut=D("0.05"))
        assert res.shocked_value == D(100000) * D("0.95") * D("0.99")
        assert res.impact == D("-5950")
        assert res.input("haircut") == D("0.05")

    def test_liquidity_bounds(self) -> None:
        with pytest.raises(InvalidInput):
            liquidity_deterioration(D(100), exit_cost=D("1"), haircut=D(0))


class TestEarlySaleReinvestment:
    @pytest.mark.parametrize(
        ("y", "price", "hpr"),
        [("0.09", "98.2062", "6.2062"), ("0.07", "101.8365", "9.8365"), ("0.08", "100.0000", "8.0000")],
    )
    def test_ee1(self, y: str, price: str, hpr: str) -> None:
        res = early_sale(D1, purchase_price=D(100), exit_after_periods=2, exit_yield=D(y))
        assert near(res.output("exit_price"), price)
        assert near(res.output("holding_period_return") * 100, hpr)
        assert res.output("coupons_received") == D(8)

    def test_exit_spread(self) -> None:
        res = early_sale(D1, purchase_price=D(100), exit_after_periods=2, exit_yield=D("0.08"), exit_spread_bp=D(25))
        assert near(res.output("exit_price_after_spread"), "99.75", "1e-25")

    def test_grid(self) -> None:
        grid = early_sale_grid(D1, purchase_price=D(100), exit_after_periods=2, base_yield=D("0.08"))
        assert [r.input("exit_yield") for r in grid] == [
            D("0.07"),
            D("0.075"),
            D("0.08"),
            D("0.085"),
            D("0.09"),
            D("0.10"),
        ]

    def test_exit_must_precede_maturity(self) -> None:
        with pytest.raises(InvalidInput):
            early_sale(D1, purchase_price=D(100), exit_after_periods=6, exit_yield=D("0.08"))

    def test_rr1(self) -> None:
        res = reinvestment_scenario(D1, purchase_price=D(100), ytm=D("0.08"), reinvest_rate=D("0.06"))
        assert near(res.output("future_value"), "125.8736")
        assert near(res.output("realised_effective_annual") * 100, "7.9721")
        assert near(res.output("realised_bond_equivalent") * 100, "7.8193")
        assert near(res.output("future_value_at_ytm"), str(D("1.04") ** 6 * 100), "1e-25")
        assert res.impact < 0


class TestAggregationAndLabels:
    def test_portfolio_sum(self) -> None:
        a = equity_drawdown_shock(D(60000), D("-0.20"), beta=D(1))
        b = rate_shock_duration(D(40000), D("3"), D("0.01"))
        agg = aggregate_portfolio(D(100000), [("eq", a), ("debt", b)], scenario_name="equity -20% & rates +100bp")
        assert agg.total_impact == D(-12000) + D(-1200)
        assert agg.impact_fraction == D("-0.132")
        assert agg.approximate  # one leg is an approximation
        assert not agg.probability_weighted
        assert agg.components[0] == ("eq", a.impact)

    def test_aggregation_rejects_mixed_measures(self) -> None:
        a = equity_drawdown_shock(D(100), D("-0.1"), beta=D(1))
        r = inflation_scenario(D(100), nominal_return=D("0.07"), base_inflation=D("0.05"), delta_inflation=D("0.01"))
        with pytest.raises(InvalidInput):
            aggregate_portfolio(D(200), [("a", a), ("r", r)], scenario_name="x")

    def test_aggregation_rejects_duplicate_ids(self) -> None:
        a = equity_drawdown_shock(D(100), D("-0.1"), beta=D(1))
        with pytest.raises(InvalidInput):
            aggregate_portfolio(D(200), [("a", a), ("a", a)], scenario_name="x")

    def test_never_labelled_worst_case(self) -> None:
        results = [
            rate_shock_duration(D(100), D(3), D("0.01")),
            bond_rate_shock(D1, D("0.08"), D("0.02"), position_value=D(100)),
            spread_shock_duration(D(100), D(3), D("0.01")),
            equity_drawdown_shock(D(100), D("-0.35"), beta=D(1)),
            inflation_scenario(D(100), nominal_return=D("0.07"), base_inflation=D("0.05"), delta_inflation=D("0.01")),
            liquidity_deterioration(D(100), exit_cost=D("0.01"), haircut=D("0.05")),
            early_sale(D1, purchase_price=D(100), exit_after_periods=2, exit_yield=D("0.10")),
            reinvestment_scenario(D1, purchase_price=D(100), ytm=D("0.08"), reinvest_rate=D("0.06")),
        ]
        agg = aggregate_portfolio(D(800), [(str(i), r) for i, r in enumerate(results[:4])], scenario_name="s")
        for r in [*results, agg]:
            text = canonical_json(r).lower()
            assert "worst" not in text
            assert r.label in (ScenarioLabel.STRESS, ScenarioLabel.ILLUSTRATIVE_DOWNSIDE)

    def test_inputs_always_returned(self) -> None:
        r = liquidity_deterioration(D(100), exit_cost=D("0.01"), haircut=D("0.05"))
        names = {q.name for q in r.inputs}
        assert {"value", "exit_cost", "haircut"} <= names
        with pytest.raises(KeyError):
            r.input("nope")
