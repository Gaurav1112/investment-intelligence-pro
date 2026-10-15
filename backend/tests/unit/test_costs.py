"""Fixtures from calculation-methodology.md §2.8–§2.10 (costs) plus edge cases."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from iip.engine.costs import (
    BER_EFFECTIVE_FROM,
    STAMP_DUTY_EFFECTIVE_FROM,
    ExpenseRatio,
    ExpenseRatioKind,
    LoadTier,
    Lot,
    ReturnBasis,
    exit_load,
    expense_net_factor,
    stamp_duty,
)
from iip.engine.errors import InvalidInput, MissingData, RuleNotFound
from iip.engine.money import D, rate_store

TRADE = date(2026, 10, 15)

# ---------------------------------------------------------------- §2.10 stamp duty


@pytest.mark.parametrize(
    ("gross", "txn", "stamp", "invested"),
    [
        ("50000", "0", "2.50", "49997.50"),  # SD-1
        ("50000", "100", "2.49", "49897.51"),  # SD-2 (ABSL example)
        ("100000", "0", "5.00", "99995.00"),  # SD-3 (HDFC FAQ)
        ("100100", "100", "5.00", "99995.00"),  # SD-3 as printed in the HDFC FAQ
        ("10000000", "0", "499.98", "9999500.02"),  # SD-4
    ],
)
def test_stamp_duty_fixtures(gross: str, txn: str, stamp: str, invested: str) -> None:
    r = stamp_duty(D(gross), trade_date=TRADE, transaction_charge=D(txn))
    assert r.stamp_duty == D(stamp)
    assert r.invested == D(invested)
    assert r.formula_id == "STAMP_DUTY_MF@1"
    assert r.rounding_mode == "ROUND_HALF_UP"


def test_stamp_duty_unrounded_values() -> None:
    assert stamp_duty(D(50000), trade_date=TRADE).stamp_duty_unrounded == D("2.499875006249687515624218789060547")


def test_sd1_units_at_nav() -> None:
    r = stamp_duty(D(50000), trade_date=TRADE, nav=D("25.4321"))
    assert r.units == D("1965.921")


def test_stamp_duty_before_effective_date_has_no_rule() -> None:
    with pytest.raises(RuleNotFound):
        stamp_duty(D(50000), trade_date=STAMP_DUTY_EFFECTIVE_FROM - timedelta(days=1))
    assert stamp_duty(D(50000), trade_date=STAMP_DUTY_EFFECTIVE_FROM).stamp_duty == D("2.50")


def test_stamp_duty_zero_rate_override() -> None:
    r = stamp_duty(D(50000), trade_date=TRADE, rate=D(0))
    assert r.stamp_duty == D("0.00")
    assert r.invested == D(50000)
    assert "RATE_OVERRIDDEN" in r.flags


@pytest.mark.parametrize(("gross", "txn"), [("0", "0"), ("-1", "0"), ("100", "100"), ("100", "-1")])
def test_stamp_duty_invalid(gross: str, txn: str) -> None:
    with pytest.raises(InvalidInput):
        stamp_duty(D(gross), trade_date=TRADE, transaction_charge=D(txn))


def test_stamp_duty_invalid_nav_and_rate() -> None:
    with pytest.raises(InvalidInput):
        stamp_duty(D(100), trade_date=TRADE, nav=D(0))
    with pytest.raises(InvalidInput):
        stamp_duty(D(100), trade_date=TRADE, rate=D("-0.1"))


def test_stamp_duty_tiny_amount_rounds_to_zero() -> None:
    r = stamp_duty(D(100), trade_date=TRADE)
    assert r.stamp_duty == D("0.00")
    assert r.invested == D(100)


# ---------------------------------------------------------------- §2.9 exit load

ONE_PCT_1Y = (LoadTier(window_days=365, rate=D("0.01")),)
NAV = D("25.4321")


def test_el1_inside_window() -> None:
    lots = [Lot(TRADE - timedelta(days=100), D(1000))]
    r = exit_load(lots, D(1000), TRADE, NAV, ONE_PCT_1Y)
    assert r.gross == D("25432.10")
    assert r.load_unrounded == D("254.321")
    assert r.load == D("254.32")
    assert r.net == D("25177.78")
    assert r.formula_id == "EXIT_LOAD@1"
    assert "BOUNDARY_CONVENTION_NOT_VERIFIED" in r.flags


@pytest.mark.parametrize(("days", "load"), [(365, "254.32"), (366, "0.00")])
def test_el2_boundary_both_sides(days: int, load: str) -> None:
    r = exit_load([Lot(TRADE - timedelta(days=days), D(1000))], D(1000), TRADE, NAV, ONE_PCT_1Y)
    assert r.load == D(load)
    assert r.lots[0].days_held == days


def test_el3_fifo_two_lots() -> None:
    lots = [Lot(TRADE - timedelta(days=100), D(400)), Lot(TRADE - timedelta(days=400), D(600))]
    r = exit_load(lots, D(700), TRADE, NAV, ONE_PCT_1Y)
    assert r.load_unrounded == D("25.4321")
    assert r.load == D("25.43")
    assert [(c.units, c.rate) for c in r.lots] == [(D(600), D(0)), (D(100), D("0.01"))]
    assert r.remaining == (Lot(TRADE - timedelta(days=100), D(300)),)


def test_exit_load_tiered_schedule() -> None:
    tiers = (LoadTier(90, D("0.01")), LoadTier(365, D("0.005")))
    r = exit_load([Lot(TRADE - timedelta(days=200), D(100))], D(100), TRADE, D(10), tiers)
    assert r.load_unrounded == D("5.000")


def test_exit_load_no_schedule_no_load() -> None:
    r = exit_load([Lot(TRADE - timedelta(days=1), D(100))], D(100), TRADE, D(10), ())
    assert r.load == D("0.00")
    assert r.net == D("1000.00")


def test_exit_load_same_day_redemption_is_inside_window() -> None:
    r = exit_load([Lot(TRADE, D(100))], D(100), TRADE, D(10), ONE_PCT_1Y)
    assert r.lots[0].days_held == 0
    assert r.load == D("10.00")


def test_exit_load_over_redemption_rejected() -> None:
    with pytest.raises(InvalidInput):
        exit_load([Lot(TRADE - timedelta(days=10), D(100))], D("100.001"), TRADE, NAV, ONE_PCT_1Y)


def test_exit_load_future_lot_rejected() -> None:
    with pytest.raises(InvalidInput):
        exit_load([Lot(TRADE + timedelta(days=1), D(100))], D(1), TRADE, NAV, ONE_PCT_1Y)


@pytest.mark.parametrize("units", ["0", "-5"])
def test_exit_load_invalid_units(units: str) -> None:
    with pytest.raises(InvalidInput):
        exit_load([Lot(TRADE - timedelta(days=10), D(100))], D(units), TRADE, NAV, ONE_PCT_1Y)


def test_exit_load_invalid_schedule() -> None:
    with pytest.raises(InvalidInput):
        exit_load([Lot(TRADE, D(1))], D(1), TRADE, NAV, (LoadTier(365, D("1.5")),))
    with pytest.raises(InvalidInput):
        exit_load([Lot(TRADE, D(1))], D(1), TRADE, NAV, (LoadTier(365, D("0.01")), LoadTier(365, D("0.02"))))
    with pytest.raises(InvalidInput):
        exit_load([Lot(TRADE, D(1))], D(1), TRADE, D(0), ONE_PCT_1Y)


def test_exit_load_very_large_amount() -> None:
    lots = [Lot(TRADE - timedelta(days=10), D("10000000"))]
    r = exit_load(lots, D("10000000"), TRADE, D("1000.0000"), ONE_PCT_1Y)
    assert r.load == D("100000000.00")
    assert r.net == D("9900000000.00")


# ---------------------------------------------------------------- §2.8 TER / BER


def test_ter1_forward_net_factor() -> None:
    er = ExpenseRatio(ExpenseRatioKind.TER, D("0.01"), as_of=date(2025, 6, 1))
    r = expense_net_factor(D("0.08"), er, basis=ReturnBasis.FORWARD_GROSS)
    assert rate_store(r.drag_factor) == D("0.990050")
    assert rate_store(r.net_return) == D("0.069254")
    assert r.net_return != D("0.07")
    assert r.formula_id == "TER_NET_FACTOR@1"
    assert "ACCRUAL_BASIS_NOT_VERIFIED" in r.flags


def test_ter_never_applied_to_nav_returns() -> None:
    er = ExpenseRatio(ExpenseRatioKind.TER, D("0.01"), as_of=date(2025, 6, 1))
    with pytest.raises(InvalidInput, match="double"):
        expense_net_factor(D("0.08"), er, basis=ReturnBasis.NAV_HISTORICAL)


def test_ber_requires_levies_estimate() -> None:
    er = ExpenseRatio(ExpenseRatioKind.BER, D("0.009"), as_of=date(2026, 6, 1))
    with pytest.raises(MissingData):
        expense_net_factor(D("0.08"), er, basis=ReturnBasis.FORWARD_GROSS)
    r = expense_net_factor(D("0.08"), er, basis=ReturnBasis.FORWARD_GROSS, levies_estimate=D("0.001"))
    ter_equiv = expense_net_factor(
        D("0.08"), ExpenseRatio(ExpenseRatioKind.TER, D("0.01"), date(2025, 6, 1)), ReturnBasis.FORWARD_GROSS
    )
    assert r.net_return == ter_equiv.net_return
    assert r.effective_rate == D("0.010")
    assert "LEVIES_ESTIMATED" in r.flags


def test_ter_rejects_levies_estimate() -> None:
    er = ExpenseRatio(ExpenseRatioKind.TER, D("0.01"), as_of=date(2025, 6, 1))
    with pytest.raises(InvalidInput):
        expense_net_factor(D("0.08"), er, ReturnBasis.FORWARD_GROSS, levies_estimate=D("0.001"))


def test_ber_before_regulation_rejected() -> None:
    er = ExpenseRatio(ExpenseRatioKind.BER, D("0.009"), as_of=BER_EFFECTIVE_FROM - timedelta(days=1))
    with pytest.raises(InvalidInput):
        expense_net_factor(D("0.08"), er, ReturnBasis.FORWARD_GROSS, levies_estimate=D("0.001"))


def test_ter_after_ber_transition_warns() -> None:
    er = ExpenseRatio(ExpenseRatioKind.TER, D("0.01"), as_of=BER_EFFECTIVE_FROM)
    r = expense_net_factor(D("0.08"), er, ReturnBasis.FORWARD_GROSS)
    assert "TER_DATED_AFTER_BER_TRANSITION" in r.warnings


def test_zero_ter_is_identity() -> None:
    er = ExpenseRatio(ExpenseRatioKind.TER, D(0), as_of=date(2025, 6, 1))
    r = expense_net_factor(D("0.08"), er, ReturnBasis.FORWARD_GROSS)
    assert r.net_return == D("0.08")


def test_forward_horizon_days() -> None:
    er = ExpenseRatio(ExpenseRatioKind.TER, D("0.0365"), as_of=date(2025, 6, 1))
    r = expense_net_factor(D("0"), er, ReturnBasis.FORWARD_GROSS, days=1)
    assert r.drag_factor == D("0.9999")


@pytest.mark.parametrize(("gross", "rate"), [("-1.5", "0.01"), ("0.08", "-0.01"), ("0.08", "1")])
def test_expense_invalid(gross: str, rate: str) -> None:
    er = ExpenseRatio(ExpenseRatioKind.TER, D(rate), as_of=date(2025, 6, 1))
    with pytest.raises(InvalidInput):
        expense_net_factor(D(gross), er, ReturnBasis.FORWARD_GROSS)


def test_expense_invalid_days() -> None:
    er = ExpenseRatio(ExpenseRatioKind.TER, D("0.01"), as_of=date(2025, 6, 1))
    with pytest.raises(InvalidInput):
        expense_net_factor(D("0.08"), er, ReturnBasis.FORWARD_GROSS, days=0)


def test_decimal_type_sanity() -> None:
    assert isinstance(D("1"), Decimal)
