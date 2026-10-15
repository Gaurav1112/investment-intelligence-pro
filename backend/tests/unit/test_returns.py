"""Fixtures from calculation-methodology.md §2 (returns) plus edge cases."""

import ast
import pathlib
from datetime import date, timedelta
from decimal import Decimal

import pytest

from iip.engine.dates import DayCount
from iip.engine.errors import InsufficientHistory, InvalidInput, MissingDistributionData, NumericalError
from iip.engine.money import D, engine_context, money, rate_display, rate_store
from iip.engine.returns import (
    ANNUALISED_FROM_SHORT_PERIOD,
    CashFlow,
    Distribution,
    HeadlineKind,
    PlanOption,
    TwrObservation,
    XirrOutcome,
    absolute_return,
    after_tax_return,
    cagr,
    headline_return,
    real_return,
    simple_annualised_return,
    total_return,
    twr,
    xirr,
)

BP = Decimal("0.000001")  # 0.0001 % — the fixtures' printed precision


def close(actual: Decimal, expected: str, tol: Decimal = BP) -> bool:
    with engine_context():
        return abs(actual - D(expected)) <= tol


# ---------------------------------------------------------------- §2.1 absolute return


def test_absolute_return_basic() -> None:
    r = absolute_return(D(100), D(112))
    assert r.value == D("0.12")
    assert r.gain == D(12)
    assert r.formula_id == "ABS_RETURN@1"


def test_absolute_return_total_loss_is_minus_100pct() -> None:
    assert absolute_return(D(100), D(0)).value == D(-1)


@pytest.mark.parametrize("start", ["0", "-1"])
def test_absolute_return_rejects_non_positive_start(start: str) -> None:
    with pytest.raises(InvalidInput):
        absolute_return(D(start), D(10))


def test_absolute_return_rejects_negative_end() -> None:
    with pytest.raises(InvalidInput):
        absolute_return(D(100), D(-1))


def test_absolute_return_very_large_amounts_exact() -> None:
    r = absolute_return(D("1000000000000000"), D("1000000000000001.23"))
    assert r.value == D("1.23E-15")


# ---------------------------------------------------------------- §2.2 / §2.3 A-1


def test_a1_simple_annualised_7_days() -> None:
    r = simple_annualised_return(D(1000), D(1001), date(2026, 1, 1), date(2026, 1, 8))
    assert rate_store(r.value) == D("0.052143")
    assert ANNUALISED_FROM_SHORT_PERIOD in r.warnings
    assert r.days == 7


def test_a1_headline_is_absolute_under_365_days() -> None:
    h = headline_return(D(1000), D(1001), date(2026, 1, 1), date(2026, 1, 8))
    assert h.kind is HeadlineKind.ABSOLUTE
    assert h.headline == D("0.001")
    assert rate_display(h.headline) == D("0.0010")  # "0.10 % in 7 days"
    assert h.gain == D(1)
    assert h.days == 7
    assert h.simple_annualised is not None and rate_store(h.simple_annualised) == D("0.052143")
    assert h.compound_annualised is not None and rate_store(h.compound_annualised) == D("0.053499")
    assert ANNUALISED_FROM_SHORT_PERIOD in h.warnings
    assert "HEADLINE_NOT_ANNUALISED" in h.flags


def test_a1_headline_is_cagr_at_365_days() -> None:
    h = headline_return(D(100), D(112), date(2025, 1, 1), date(2026, 1, 1))
    assert h.kind is HeadlineKind.CAGR
    assert h.headline == D("0.12")
    assert h.absolute == D("0.12")
    assert h.warnings == ()


def test_a1_boundary_364_vs_365_days() -> None:
    start = date(2025, 3, 1)
    assert headline_return(D(100), D(110), start, start + timedelta(days=364)).kind is HeadlineKind.ABSOLUTE
    assert headline_return(D(100), D(110), start, start + timedelta(days=365)).kind is HeadlineKind.CAGR


def test_single_day_horizon() -> None:
    h = headline_return(D(100), D(101), date(2026, 1, 1), date(2026, 1, 2))
    assert h.kind is HeadlineKind.ABSOLUTE
    assert h.headline == D("0.01")
    assert h.simple_annualised == D("3.65")
    c = cagr(D(100), D(101), date(2026, 1, 1), date(2026, 1, 2))
    assert ANNUALISED_FROM_SHORT_PERIOD in c.warnings
    assert close(c.value, "36.783434", Decimal("0.000001"))  # 1.01^365 − 1


def test_zero_day_horizon_rejected() -> None:
    d0 = date(2026, 1, 1)
    with pytest.raises(InvalidInput):
        headline_return(D(100), D(101), d0, d0)
    with pytest.raises(InvalidInput):
        simple_annualised_return(D(100), D(101), d0, d0)


def test_end_before_start_rejected() -> None:
    with pytest.raises(InvalidInput):
        cagr(D(100), D(101), date(2026, 1, 2), date(2026, 1, 1))


# ---------------------------------------------------------------- §2.4 CAGR


@pytest.mark.parametrize(
    ("v0", "v1", "start", "end", "days", "expected"),
    [
        ("100", "112", date(2025, 1, 1), date(2026, 1, 1), 365, "0.120000"),  # CAGR-1
        ("100", "121", date(2024, 1, 1), date(2026, 1, 1), 731, "0.099857"),  # CAGR-2
        ("10.0000", "13.3100", date(2023, 10, 13), date(2026, 10, 13), 1096, "0.099904"),  # CAGR-3
    ],
)
def test_cagr_fixtures(v0: str, v1: str, start: date, end: date, days: int, expected: str) -> None:
    r = cagr(D(v0), D(v1), start, end)
    assert r.days == days
    assert rate_store(r.value) == D(expected)
    assert r.day_count is DayCount.ACT_365F
    assert r.formula_id == "CAGR@1"
    assert r.warnings == ()


def test_cagr_leap_days_differ_from_integer_years() -> None:
    # CAGR-2/3: the integer-years shortcut would give exactly 10 %.
    assert cagr(D(100), D(121), date(2024, 1, 1), date(2026, 1, 1)).value < D("0.1")


def test_cagr_zero_end_is_minus_100pct() -> None:
    assert cagr(D(100), D(0), date(2024, 1, 1), date(2026, 1, 1)).value == D(-1)


def test_cagr_zero_days_rejected() -> None:
    with pytest.raises(InvalidInput):
        cagr(D(100), D(110), date(2026, 1, 1), date(2026, 1, 1))


def test_cagr_negative_start_rejected() -> None:
    with pytest.raises(InvalidInput):
        cagr(D(-100), D(110), date(2025, 1, 1), date(2026, 1, 1))


def test_cagr_very_large_amounts() -> None:
    r = cagr(D("100000000000000"), D("112000000000000"), date(2025, 1, 1), date(2026, 1, 1))
    assert r.value == D("0.12")


# ---------------------------------------------------------------- §2.5 TWR


def test_twr_1() -> None:
    obs = [
        TwrObservation(date(2026, 1, 1), D(0), D(10000)),
        TwrObservation(date(2026, 1, 2), D(10500), D(5000)),
        TwrObservation(date(2026, 1, 3), D(14725), D(0)),
    ]
    r = twr(obs)
    assert r.value == D("-0.0025")
    assert r.sub_period_returns == (D("0.05"), D("-0.05"))
    assert r.formula_id == "TWR@1"
    assert r.excluded_periods == ()


def test_twr_2_contrast_with_mwr() -> None:
    obs = [
        TwrObservation(date(2024, 1, 1), D(0), D(10000)),
        TwrObservation(date(2025, 1, 1), D(15000), D(30000)),
        TwrObservation(date(2026, 1, 1), D(36000), D(0)),
    ]
    assert twr(obs).value == D("0.2")


def test_twr_order_independent_input() -> None:
    obs = [
        TwrObservation(date(2026, 1, 3), D(14725), D(0)),
        TwrObservation(date(2026, 1, 1), D(0), D(10000)),
        TwrObservation(date(2026, 1, 2), D(10500), D(5000)),
    ]
    assert twr(obs).value == D("-0.0025")


def test_twr_restarts_after_zero_balance_and_flags() -> None:
    obs = [
        TwrObservation(date(2026, 1, 1), D(0), D(100)),
        TwrObservation(date(2026, 1, 2), D(110), D(-110)),  # full exit
        TwrObservation(date(2026, 1, 3), D(0), D(200)),  # re-entry
        TwrObservation(date(2026, 1, 4), D(220), D(0)),
    ]
    r = twr(obs)
    assert r.value == D("0.21")  # 1.1 × 1.1 − 1; the empty period is excluded
    assert r.excluded_periods == (date(2026, 1, 3),)
    assert "TWR_CHAIN_RESTARTED" in r.flags


def test_twr_value_from_nothing_after_zero_balance_rejected() -> None:
    obs = [
        TwrObservation(date(2026, 1, 1), D(0), D(100)),
        TwrObservation(date(2026, 1, 2), D(100), D(-100)),
        TwrObservation(date(2026, 1, 3), D(50), D(0)),
    ]
    with pytest.raises(InvalidInput):
        twr(obs)


def test_twr_negative_value_rejected() -> None:
    obs = [
        TwrObservation(date(2026, 1, 1), D(0), D(100)),
        TwrObservation(date(2026, 1, 2), D(100), D(-150)),
    ]
    with pytest.raises(InvalidInput):
        twr(obs)


def test_twr_duplicate_dates_rejected() -> None:
    obs = [TwrObservation(date(2026, 1, 1), D(0), D(100)), TwrObservation(date(2026, 1, 1), D(100), D(0))]
    with pytest.raises(InvalidInput):
        twr(obs)


def test_twr_insufficient_history() -> None:
    with pytest.raises(InsufficientHistory):
        twr([TwrObservation(date(2026, 1, 1), D(0), D(100))])
    with pytest.raises(InsufficientHistory):
        twr([TwrObservation(date(2026, 1, 1), D(0), D(0)), TwrObservation(date(2026, 1, 2), D(0), D(0))])


# ---------------------------------------------------------------- §2.6 XIRR


def _cf(y: int, m: int, d: int, amount: str) -> CashFlow:
    return CashFlow(date(y, m, d), D(amount))


@pytest.mark.parametrize(
    ("flows", "expected", "short"),
    [
        ([_cf(2025, 1, 1, "-10000"), _cf(2026, 1, 1, "11000")], "0.100000", False),  # X-1
        ([_cf(2024, 1, 1, "-10000"), _cf(2025, 1, 1, "11000")], "0.099714", False),  # X-2
        (
            [
                _cf(2025, 1, 10, "-5000"),
                _cf(2025, 2, 10, "-5000"),
                _cf(2025, 3, 10, "-5000"),
                _cf(2025, 4, 10, "-5000"),
                _cf(2025, 10, 10, "21500"),
            ],
            "0.122645",
            True,
        ),  # X-3
        ([_cf(2024, 2, 29, "-10000"), _cf(2025, 2, 28, "500"), _cf(2026, 2, 28, "10500")], "0.050000", False),
        (
            [_cf(2024, 1, 1, "-10000"), _cf(2025, 1, 1, "-30000"), _cf(2026, 1, 1, "36000")],
            "-0.081282",
            False,
        ),  # X-7
    ],
)
def test_xirr_fixtures(flows: list[CashFlow], expected: str, short: bool) -> None:
    r = xirr(flows)
    assert r.outcome is XirrOutcome.SOLVED
    assert r.rate is not None
    assert rate_store(r.rate) == D(expected)
    assert r.stored_rate == D(expected)
    assert len(r.roots) == 1
    assert r.formula_id == "XIRR@1"
    assert r.day_count is DayCount.ACT_365F
    assert (ANNUALISED_FROM_SHORT_PERIOD in r.warnings) is short
    assert r.headline_allowed is (not short)


def test_xirr_x3_reports_span() -> None:
    flows = [_cf(2025, 1, 10, "-5000"), _cf(2025, 10, 10, "5500")]
    r = xirr(flows)
    assert r.span_days == 273


def test_xirr_x5_multiple_roots() -> None:
    r = xirr([_cf(2025, 1, 1, "-100"), _cf(2026, 1, 1, "230"), _cf(2027, 1, 1, "-132")])
    assert r.outcome is XirrOutcome.MULTIPLE_ROOTS
    assert r.rate is None
    assert r.headline_allowed is False
    assert [rate_store(x) for x in r.roots] == [D("0.100000"), D("0.200000")]
    assert r.sign_changes == 2


def test_xirr_x6_no_outflow() -> None:
    r = xirr([_cf(2025, 1, 1, "100"), _cf(2026, 1, 1, "200")])
    assert r.outcome is XirrOutcome.NO_SOLUTION
    assert r.rate is None
    assert r.roots == ()


def test_xirr_no_inflow() -> None:
    assert xirr([_cf(2025, 1, 1, "-100"), _cf(2026, 1, 1, "-200")]).outcome is XirrOutcome.NO_SOLUTION


def test_xirr_root_above_grid_is_no_solution() -> None:
    # 10 % gain in 1 day ≈ 1.28e15 annualised: far above the 1000 % grid ceiling.
    r = xirr([_cf(2025, 1, 1, "-100"), _cf(2025, 1, 2, "110")])
    assert r.outcome is XirrOutcome.NO_SOLUTION
    assert r.reason is not None


def test_xirr_same_date_flows_are_netted() -> None:
    a = xirr([_cf(2025, 1, 1, "-6000"), _cf(2025, 1, 1, "-4000"), _cf(2026, 1, 1, "11000")])
    assert a.rate is not None and rate_store(a.rate) == D("0.100000")
    assert a.flows == (CashFlow(date(2025, 1, 1), D(-10000)), CashFlow(date(2026, 1, 1), D(11000)))


def test_xirr_netting_to_one_sign_is_no_solution() -> None:
    r = xirr([_cf(2025, 1, 1, "-100"), _cf(2025, 1, 1, "100"), _cf(2026, 1, 1, "50")])
    assert r.outcome is XirrOutcome.NO_SOLUTION


def test_xirr_unsorted_input() -> None:
    a = xirr([_cf(2026, 1, 1, "11000"), _cf(2025, 1, 1, "-10000")])
    assert a.rate is not None and rate_store(a.rate) == D("0.100000")


def test_xirr_zero_rate_on_grid_point() -> None:
    r = xirr([_cf(2025, 1, 1, "-100"), _cf(2026, 1, 1, "100")])
    assert r.outcome is XirrOutcome.SOLVED
    assert r.rate == D(0)


def test_xirr_total_loss_rejected_as_no_solution() -> None:
    # Root is r = −100 %, outside (−99 %, …]: not meaningful.
    r = xirr([_cf(2025, 1, 1, "-100"), _cf(2026, 1, 1, "0.0000001")])
    assert r.outcome is XirrOutcome.NO_SOLUTION


@pytest.mark.parametrize("n", [0, 1])
def test_xirr_fewer_than_two_flows_invalid(n: int) -> None:
    with pytest.raises(InvalidInput):
        xirr([_cf(2025, 1, 1, "-100")][:n])


def test_xirr_very_large_amounts() -> None:
    r = xirr([_cf(2025, 1, 1, "-10000000000000"), _cf(2026, 1, 1, "11000000000000")])
    assert r.rate is not None and rate_store(r.rate) == D("0.100000")


def test_xirr_rate_verified_in_decimal() -> None:
    r = xirr([_cf(2024, 1, 1, "-10000"), _cf(2025, 1, 1, "-30000"), _cf(2026, 1, 1, "36000")])
    assert r.xnpv_at_rate is not None
    with engine_context():
        assert abs(r.xnpv_at_rate) <= Decimal("1e-9") * D(76000)


def test_numerical_error_is_typed() -> None:
    assert issubclass(NumericalError, Exception)


# ---------------------------------------------------------------- §2.7 total return (IDCW)


def test_tr1_idcw_reinvested() -> None:
    r = total_return(
        nav_start=D("11.60"),
        nav_end=D("11.80"),
        start=date(2025, 1, 1),
        end=date(2025, 12, 31),
        option=PlanOption.IDCW,
        distributions=[Distribution(date(2025, 6, 1), D("0.50"), D("11.52"))],
    )
    assert rate_store(r.value) == D("0.061392")
    assert rate_store(r.price_return) == D("0.017241")
    assert r.formula_id == "TR_IDCW@1"


def test_tr_idcw_missing_feed_raises_never_price_only() -> None:
    with pytest.raises(MissingDistributionData):
        total_return(
            nav_start=D("11.60"),
            nav_end=D("11.80"),
            start=date(2025, 1, 1),
            end=date(2025, 12, 31),
            option=PlanOption.IDCW,
            distributions=None,
        )


def test_tr_idcw_feed_present_no_distributions() -> None:
    r = total_return(
        nav_start=D(10),
        nav_end=D(11),
        start=date(2025, 1, 1),
        end=date(2025, 12, 31),
        option=PlanOption.IDCW,
        distributions=[],
    )
    assert r.value == D("0.1")


def test_tr_growth_is_price_return() -> None:
    r = total_return(
        nav_start=D(10),
        nav_end=D(11),
        start=date(2025, 1, 1),
        end=date(2025, 12, 31),
        option=PlanOption.GROWTH,
        distributions=None,
    )
    assert r.value == D("0.1")


def test_tr_growth_with_distributions_rejected() -> None:
    with pytest.raises(InvalidInput):
        total_return(
            nav_start=D(10),
            nav_end=D(11),
            start=date(2025, 1, 1),
            end=date(2025, 12, 31),
            option=PlanOption.GROWTH,
            distributions=[Distribution(date(2025, 6, 1), D("0.5"), D("10"))],
        )


def test_tr_distribution_outside_window_rejected() -> None:
    with pytest.raises(InvalidInput):
        total_return(
            nav_start=D(10),
            nav_end=D(11),
            start=date(2025, 1, 1),
            end=date(2025, 12, 31),
            option=PlanOption.IDCW,
            distributions=[Distribution(date(2026, 6, 1), D("0.5"), D("10"))],
        )


def test_tr_after_tax_reinvests_net_distribution() -> None:
    # Fictional τ = 0.30 (examples never carry real user values).
    r = total_return(
        nav_start=D("11.60"),
        nav_end=D("11.80"),
        start=date(2025, 1, 1),
        end=date(2025, 12, 31),
        option=PlanOption.IDCW,
        distributions=[Distribution(date(2025, 6, 1), D("0.50"), D("11.52"))],
        distribution_tax_rate=D("0.30"),
    )
    with engine_context():
        expected = D("11.80") / D("11.60") * (1 + D("0.35") / D("11.52")) - 1
    assert r.value == expected


@pytest.mark.parametrize("bad", ["0", "-1"])
def test_tr_invalid_navs(bad: str) -> None:
    with pytest.raises(InvalidInput):
        total_return(
            nav_start=D(bad),
            nav_end=D(11),
            start=date(2025, 1, 1),
            end=date(2025, 12, 31),
            option=PlanOption.GROWTH,
            distributions=None,
        )


# ---------------------------------------------------------------- §2.11 Fisher


@pytest.mark.parametrize(
    ("nom", "infl", "real", "approx"),
    [
        ("0.07", "0.05", "0.019048", "0.02"),  # F-1
        ("0.065", "0.054", "0.010436", "0.011"),  # F-2
        ("0.04", "0.06", "-0.018868", "-0.02"),  # F-3
    ],
)
def test_fisher_fixtures(nom: str, infl: str, real: str, approx: str) -> None:
    r = real_return(D(nom), D(infl))
    assert rate_store(r.value) == D(real)
    assert r.approximation == D(approx)
    assert r.formula_id == "FISHER@1"


def test_fisher_f3_flags_real_loss() -> None:
    assert "REAL_LOSS" in real_return(D("0.04"), D("0.06")).flags


@pytest.mark.parametrize(("nom", "infl"), [("-1.5", "0.05"), ("0.05", "-1"), ("0.05", "-2")])
def test_fisher_invalid(nom: str, infl: str) -> None:
    with pytest.raises(InvalidInput):
        real_return(D(nom), D(infl))


# ---------------------------------------------------------------- §2.12 after-tax


def test_tax1_after_tax_gain() -> None:
    # TAX-1: gain ₹10,000, fictional tax ₹2,080 (20 % × 1.04) → ₹7,920.00 after tax.
    r = after_tax_return(D(100000), D(110000), tax_amount=D(2080))
    assert money(r.gain_after_tax) == D("7920.00")
    assert r.gain_pre_tax == D(10000)
    assert r.absolute_after_tax == D("0.0792")
    assert r.cagr_after_tax is None


def test_after_tax_with_dates_uses_cagr_and_guard() -> None:
    r = after_tax_return(D(100000), D(110000), tax_amount=D(2080), start=date(2025, 1, 1), end=date(2026, 1, 1))
    assert r.cagr_after_tax == D("0.0792")
    short = after_tax_return(D(100000), D(101000), tax_amount=D(208), start=date(2025, 1, 1), end=date(2025, 2, 1))
    assert ANNUALISED_FROM_SHORT_PERIOD in short.warnings


def test_after_tax_negative_tax_rejected() -> None:
    with pytest.raises(InvalidInput):
        after_tax_return(D(100), D(110), tax_amount=D(-1))


def test_after_tax_dates_must_be_paired() -> None:
    with pytest.raises(InvalidInput):
        after_tax_return(D(100), D(110), tax_amount=D(1), start=date(2025, 1, 1))


# ---------------------------------------------------------------- §2.8 guard: no TER in NAV returns


def test_no_expense_ratio_term_in_nav_return_code() -> None:
    src = (pathlib.Path(__file__).resolve().parents[2] / "src" / "iip" / "engine" / "returns.py").read_text()
    tree = ast.parse(src)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    lowered = {n.lower() for n in names}
    assert not any("expense" in n or n in {"ter", "ber"} or "costs" in n for n in lowered), lowered
