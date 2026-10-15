"""QuantLib 1.44 oracle for fixed income and FD compounding (calculation-methodology.md §3.4, §4, §5).

Tolerances (QuantLib works in float64, so these are float-precision bounds, not Decimal ones):

| Quantity                       | Tolerance             | Spec §5 requirement |
|--------------------------------|-----------------------|---------------------|
| T-bill price (per ₹100)        | 1e-10                 | 1e-10               |
| Clean / dirty price (per ₹100) | 1e-8                  | 1e-8                |
| Accrued interest (per ₹100)    | 1e-10                 | 1e-4                |
| YTM (rate)                     | 1e-10                 | (price 1e-8)        |
| Macaulay / modified duration   | 1e-8 years            | 1e-8                |
| Convexity                      | 1e-8 years²           | 1e-8                |
| Coupon schedule dates          | exact                 | —                   |
| FD maturity (₹)                | ₹1e-6 (spec ₹0.05)    | ₹0.05               |

Documented disagreements (asserted below so they cannot drift silently):
1. 30E/360 G-sec periods that start or end on a February month-end: QuantLib ``FixedRateBond`` pays
   ``C × days30E/360`` (e.g. 178/360), the engine pays the fixed ``C/2`` (RBI FAQ: coupon is C/2 on the
   coupon dates). Cause: QuantLib accrues the coupon amount by day count; Indian G-secs pay a fixed half-coupon.
2. Semi-annual SEBI ACT/ACT: QuantLib has no SEBI convention. ``ActualActual(ISMA)`` pays C/2 every period;
   SEBI pays ``C × actual days / 365|366`` (3.9781 / 4.0219 in CB-1). Annual-coupon SEBI bonds agree exactly.
"""

from datetime import date
from decimal import Decimal

import pytest
import QuantLib as ql
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from iip.engine.dates import add_months
from iip.engine.deposits import fd_maturity
from iip.engine.fixed_income import (
    Bond,
    BondKind,
    Yield,
    accrued_interest,
    bond_risk,
    compounding_for_frequency,
    corporate_bond,
    coupon_schedule,
    gsec,
    price_from_yield,
    tbill_price,
    yield_from_price,
)

pytestmark = pytest.mark.oracle

PRICE_TOL = 1e-8
AI_TOL = 1e-10
YTM_TOL = 1e-10
RISK_TOL = 1e-8
TBILL_TOL = 1e-10

_QL_FREQ = {1: ql.Annual, 2: ql.Semiannual, 4: ql.Quarterly, 12: ql.Monthly}


def qd(d: date) -> ql.Date:
    return ql.Date(d.day, d.month, d.year)


def _schedule(bond: Bond, start: date) -> ql.Schedule:
    return ql.Schedule(
        qd(start),
        qd(bond.maturity),
        ql.Period(_QL_FREQ[bond.frequency]),
        ql.NullCalendar(),
        ql.Unadjusted,
        ql.Unadjusted,
        ql.DateGeneration.Backward,
        bond.end_of_month,
    )


def _ql_bond(bond: Bond, start: date) -> tuple[ql.FixedRateBond, ql.DayCounter]:
    sched = _schedule(bond, start)
    if bond.kind is BondKind.CORPORATE:
        dc = ql.ActualActual(ql.ActualActual.ISMA, sched)
    else:
        dc = ql.Thirty360(ql.Thirty360.European)
    qb = ql.FixedRateBond(0, 100.0, sched, [float(bond.coupon_rate)], dc, ql.Unadjusted, float(bond.redemption))
    return qb, dc


def _start(bond: Bond, settle: date) -> date:
    """A regular schedule date at or before settlement (so QuantLib generates no stub)."""
    j = 0
    m = 12 // bond.frequency
    while add_months(bond.maturity, -j * m) > settle:
        j += 1
    return add_months(bond.maturity, -(j + 2) * m)


def _compare(bond: Bond, settle: date, y: str) -> None:
    ql.Settings.instance().evaluationDate = qd(settle)
    qb, dc = _ql_bond(bond, _start(bond, settle))
    freq = _QL_FREQ[bond.frequency]
    yv = float(y)
    rate = ql.InterestRate(yv, dc, ql.Compounded, freq)
    ours = price_from_yield(bond, settle, Yield(Decimal(y), compounding_for_frequency(bond.frequency)))
    risk = bond_risk(bond, settle, ours.ytm)

    assert abs(float(ours.clean) - ql.BondFunctions.cleanPrice(qb, rate, qd(settle))) < PRICE_TOL
    assert abs(float(ours.dirty) - ql.CashFlows.npv(qb.cashflows(), rate, False, qd(settle), qd(settle))) < PRICE_TOL
    assert abs(float(ours.accrued) - qb.accruedAmount(qd(settle))) < AI_TOL
    assert (
        abs(float(risk.macaulay_duration) - ql.BondFunctions.duration(qb, rate, ql.Duration.Macaulay, qd(settle)))
        < RISK_TOL
    )
    assert (
        abs(float(risk.modified_duration) - ql.BondFunctions.duration(qb, rate, ql.Duration.Modified, qd(settle)))
        < RISK_TOL
    )
    assert abs(float(risk.convexity) - ql.BondFunctions.convexity(qb, rate, qd(settle))) < RISK_TOL

    ytm = yield_from_price(bond, settle, ours.clean)
    ql_ytm = ql.BondFunctions.bondYield(
        qb, ql.BondPrice(float(ours.clean), ql.BondPrice.Clean), dc, ql.Compounded, freq, qd(settle), 1e-14, 200, 0.05
    )
    assert abs(float(ytm.ytm.value) - ql_ytm) < YTM_TOL
    assert abs(float(ytm.ytm.value) - yv) < YTM_TOL


# ---------------------------------------------------------------------------------------------- T-bills


@pytest.mark.parametrize(("days", "y"), [(91, "0.065"), (182, "0.066"), (364, "0.067"), (1, "0.065"), (41, "-0.002")])
def test_tbill_price_vs_quantlib(days: int, y: str) -> None:
    settle = date(2026, 10, 16)
    maturity = date.fromordinal(settle.toordinal() + days)
    ql.Settings.instance().evaluationDate = qd(settle)
    zcb = ql.ZeroCouponBond(0, ql.NullCalendar(), 100.0, qd(maturity), ql.Unadjusted, 100.0, qd(settle))
    ql_price = ql.BondFunctions.cleanPrice(zcb, float(y), ql.Actual365Fixed(), ql.Simple, ql.Annual, qd(settle))
    assert abs(float(tbill_price(Decimal(y), days).price) - ql_price) < TBILL_TOL


# ---------------------------------------------------------------------------------------------- G-secs


@pytest.mark.parametrize(
    ("bond", "settle", "y"),
    [
        (gsec(Decimal("0.071"), date(2036, 4, 15)), date(2026, 10, 16), "0.065"),  # Y-2 / D-2
        (gsec(Decimal("0.08"), date(2029, 4, 15)), date(2026, 4, 15), "0.08"),  # D-1 (on coupon date)
        (gsec(Decimal("0.08"), date(2028, 4, 15)), date(2026, 4, 15), "0.069121"),  # Y-1
        (gsec(Decimal("0.0883"), date(2023, 11, 25)), date(2014, 1, 30), "0.0875"),  # AI-1 bond
        (gsec(Decimal("0.0726"), date(2033, 1, 31)), date(2026, 11, 20), "0.0671"),  # 31-Jan/31-Jul coupons
        (gsec(Decimal("0.09"), date(2030, 12, 1)), date(2026, 3, 31), "0.0712"),  # 31st settlement
        (gsec(Decimal("0.055"), date(2055, 6, 15)), date(2027, 1, 5), "0.0745"),  # 30-year
        (gsec(Decimal("0.02"), date(2028, 4, 15)), date(2026, 5, 2), "-0.004"),  # negative yield
        (
            gsec(Decimal("0.0"), date(2031, 4, 15)),
            date(2026, 7, 9),
            "0.07",
        ),  # zero coupon, 30E/360
    ],
)
def test_gsec_vs_quantlib(bond: Bond, settle: date, y: str) -> None:
    _compare(bond, settle, y)


def test_rbi_faq_accrued_vs_quantlib() -> None:
    bond = gsec(Decimal("0.0883"), date(2023, 11, 25))
    ql.Settings.instance().evaluationDate = qd(date(2014, 1, 30))
    qb, _ = _ql_bond(bond, date(2012, 11, 25))
    ai = accrued_interest(bond, date(2014, 1, 30))
    assert abs(float(ai.accrued) - qb.accruedAmount(qd(date(2014, 1, 30)))) < AI_TOL
    assert ai.accrued_quoted == Decimal("1.5943")


@settings(max_examples=100, deadline=None)
@given(
    st.integers(0, 1400),
    st.integers(2027, 2056),
    st.integers(1, 12),
    st.integers(1, 28),
    st.integers(2, 365 * 25),
    st.integers(-50, 2000),
)
def test_gsec_random_vs_quantlib(coupon_bp: int, yr: int, mo: int, dy: int, back: int, y_bp: int) -> None:
    maturity = date(yr, mo, dy)
    settle = date.fromordinal(maturity.toordinal() - back)
    assume(settle.year >= 2001)
    bond = gsec(Decimal(coupon_bp) / 10000, maturity, shut_days=0)
    _compare(bond, settle, str(Decimal(y_bp) / 10000))


# ---------------------------------------------------------------------------------------------- corporate


@pytest.mark.parametrize(
    ("bond", "settle", "y"),
    [
        (corporate_bond(Decimal("0.09"), date(2031, 6, 30), 1, shut_days=0), date(2026, 6, 30), "0.08"),  # SP-1
        (corporate_bond(Decimal("0.09"), date(2031, 6, 30), 1, shut_days=0), date(2027, 11, 3), "0.0836"),
        (corporate_bond(Decimal("0.085"), date(2029, 3, 1), 1, shut_days=0), date(2027, 9, 17), "0.091"),  # leap yr
        (corporate_bond(Decimal("0.0"), date(2030, 1, 1), 1, shut_days=0), date(2027, 5, 5), "0.08"),  # zero cpn
    ],
)
def test_annual_sebi_corporate_vs_quantlib_isma(bond: Bond, settle: date, y: str) -> None:
    _compare(bond, settle, y)


def test_semiannual_sebi_disagrees_with_isma_by_design() -> None:
    bond = corporate_bond(Decimal("0.08"), date(2019, 1, 1), 2, shut_days=0, issue_date=date(2016, 1, 1))
    qb, _ = _ql_bond(bond, date(2016, 1, 1))
    ql_amounts = [cf.amount() for cf in qb.cashflows()][:2]
    ours = [p.amount for p in coupon_schedule(bond).periods][:2]
    assert ql_amounts == pytest.approx([4.0, 4.0], abs=1e-12)
    assert [round(float(a), 4) for a in ours] == [3.9781, 4.0219]  # SEBI CB-1


# ---------------------------------------------------------------------------------------------- schedules


@pytest.mark.parametrize(
    ("maturity", "eom", "start"),
    [
        (date(2036, 4, 15), False, date(2026, 4, 15)),
        (date(2036, 8, 31), False, date(2026, 8, 31)),
        (date(2036, 8, 31), True, date(2026, 8, 31)),
        (date(2027, 2, 28), True, date(2020, 8, 31)),
        (date(2027, 2, 28), False, date(2020, 8, 28)),
        (date(2033, 1, 31), False, date(2027, 1, 31)),
    ],
)
def test_coupon_schedule_vs_quantlib(maturity: date, eom: bool, start: date) -> None:
    bond = gsec(Decimal("0.07"), maturity, end_of_month=eom)
    ours = [start] + [p.end for p in coupon_schedule(bond, start).periods]
    theirs = [date(d.year(), d.month(), d.dayOfMonth()) for d in _schedule(bond, start)]
    assert ours == theirs


def test_february_month_end_coupon_disagrees_by_design() -> None:
    bond = gsec(Decimal("0.071"), date(2036, 8, 31))
    qb, _ = _ql_bond(bond, date(2025, 8, 31))
    first = qb.cashflows()[0]  # 31-Aug-2025 → 28-Feb-2026: 178 30E days
    assert first.amount() == pytest.approx(7.1 * 178 / 360, abs=1e-12)
    assert coupon_schedule(bond, date(2025, 8, 31)).periods[0].amount == Decimal("3.55")


# ---------------------------------------------------------------------------------------------- FDs


@pytest.mark.parametrize(
    ("rate", "maturity"),
    [
        ("0.07", date(2026, 10, 15)),
        ("0.07", date(2027, 10, 15)),
        ("0.075", date(2030, 10, 15)),
        ("0.07", date(2026, 11, 19)),
    ],
    ids=["FD-1", "FD-2", "FD-7", "FD-5"],
)
def test_fd_vs_quantlib_interest_rate(rate: str, maturity: date) -> None:
    start = date(2025, 10, 15)
    r = fd_maturity(Decimal(100000), Decimal(rate), start, maturity)
    q = ql.InterestRate(float(rate), ql.Actual365Fixed(), ql.Compounded, ql.Quarterly)
    simple = ql.InterestRate(float(rate), ql.Actual365Fixed(), ql.Simple, ql.Annual)
    expected = 100000 * q.compoundFactor(r.complete_quarters / 4) * simple.compoundFactor(r.broken_days / 365)
    assert abs(float(r.maturity_amount) - expected) < 1e-6
