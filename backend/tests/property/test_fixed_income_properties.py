"""Hypothesis properties for fixed income (calculation-methodology.md §5 property list)."""

from datetime import date, timedelta
from decimal import Decimal

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from iip.engine.fixed_income import (
    Bond,
    BondKind,
    Compounding,
    Yield,
    bond_cashflows,
    bond_risk,
    compounding_for_frequency,
    corporate_bond,
    coupon_schedule,
    gsec,
    price_change,
    price_from_yield,
    tbill_price,
    tbill_yield,
    yield_from_price,
)
from iip.engine.money import engine_context

PROFILE = settings(max_examples=150, deadline=None)


@st.composite
def bonds(draw: st.DrawFn) -> tuple[Bond, date]:
    """Option-free bullets: G-secs (30E/360, coupon day ≤ 28 so every period is 180 30E-days) and SEBI corporates."""
    coupon = Decimal(draw(st.integers(0, 1500))) / 10000
    maturity = date(draw(st.integers(2027, 2060)), draw(st.integers(1, 12)), draw(st.integers(1, 28)))
    settle = maturity - timedelta(days=draw(st.integers(2, 365 * 30)))
    assume(settle >= date(2020, 1, 1))
    if draw(st.booleans()):
        bond = gsec(coupon, maturity, shut_days=0)
    else:
        bond = corporate_bond(coupon, maturity, draw(st.sampled_from([1, 2, 4, 12])), shut_days=0)
    return bond, settle


yields = st.integers(-150, 2500).map(lambda bp: Decimal(bp) / 10000)


def _y(bond: Bond, v: Decimal) -> Yield:
    return Yield(v, compounding_for_frequency(bond.frequency))


@PROFILE
@given(bonds(), yields, st.integers(1, 500))
def test_price_strictly_decreases_as_yield_rises(case: tuple[Bond, date], y0: Decimal, step_bp: int) -> None:
    bond, settle = case
    y1 = y0 + Decimal(step_bp) / 10000
    p0 = price_from_yield(bond, settle, _y(bond, y0))
    p1 = price_from_yield(bond, settle, _y(bond, y1))
    assert p1.clean < p0.clean
    assert p1.dirty < p0.dirty


@PROFILE
@given(bonds(), yields)
def test_zero_shock_gives_zero_change(case: tuple[Bond, date], y0: Decimal) -> None:
    bond, settle = case
    c = price_change(bond, settle, _y(bond, y0), Decimal(0))
    assert c.exact_change == 0
    assert c.duration_only == 0
    assert c.duration_convexity == 0


@PROFILE
@given(bonds(), yields)
def test_price_ytm_price_round_trip(case: tuple[Bond, date], y0: Decimal) -> None:
    bond, settle = case
    p = price_from_yield(bond, settle, _y(bond, y0))
    back = yield_from_price(bond, settle, p.clean)
    assert back.residual <= Decimal("1e-10")
    again = price_from_yield(bond, settle, back.ytm)
    assert abs(again.clean - p.clean) <= Decimal("1e-10")
    assert abs(back.ytm.value - y0) <= Decimal("1e-9")


@PROFILE
@given(bonds(), yields)
def test_cash_flow_totals_reconcile(case: tuple[Bond, date], y0: Decimal) -> None:
    bond, settle = case
    flows = bond_cashflows(bond, settle)
    p = price_from_yield(bond, settle, _y(bond, y0))
    with engine_context():
        assert flows.total == flows.total_coupons + flows.redemption
        assert flows.redemption == bond.redemption
        assert abs(p.clean + p.accrued - p.dirty) < Decimal("1e-28")  # exact up to the 34th digit
        sched = coupon_schedule(bond, settle)
        assert flows.total_coupons == sched.total_coupons
        assert len(sched.periods) == p.remaining_coupons
        if y0 == 0:  # at a zero yield the dirty price is the undiscounted sum of the flows
            assert abs(p.dirty - flows.total) < Decimal("1e-25")
        if bond.kind is not BondKind.CORPORATE:
            assert flows.total_coupons == bond.coupon_rate * 100 / 2 * p.remaining_coupons


@PROFILE
@given(bonds(), st.integers(0, 2500).map(lambda bp: Decimal(bp) / 10000))
def test_duration_and_convexity_positive(case: tuple[Bond, date], y0: Decimal) -> None:
    bond, settle = case
    r = bond_risk(bond, settle, _y(bond, y0))
    years_to_maturity = Decimal((bond.maturity - settle).days) / 365
    assert r.macaulay_duration > 0
    assert 0 < r.modified_duration <= r.macaulay_duration
    assert r.macaulay_duration <= years_to_maturity + Decimal("0.02")  # 30E vs actual-day slack
    assert r.convexity > 0
    assert r.dv01 > 0


@PROFILE
@given(st.integers(1, 364), st.integers(-100, 2000).map(lambda bp: Decimal(bp) / 10000))
def test_tbill_price_decreasing_and_round_trip(days: int, y0: Decimal) -> None:
    p0 = tbill_price(y0, days).price
    p1 = tbill_price(y0 + Decimal("0.0001"), days).price
    assert p1 < p0
    assert abs(tbill_yield(p0, days).money_market_yield.value - y0) < Decimal("1e-28")


@PROFILE
@given(st.integers(-100, 2000).map(lambda bp: Decimal(bp) / 10000), st.sampled_from(list(Compounding)[1:]))
def test_yield_conversion_preserves_effective_annual(v: Decimal, comp: Compounding) -> None:
    y = Yield(v, Compounding.SEMIANNUAL)
    assert abs(y.to(comp).effective_annual() - y.effective_annual()) < Decimal("1e-30")
