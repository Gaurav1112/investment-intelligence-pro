"""QuantLib oracle for the bond CANDIDATE (engine/candidates.bond_candidate): the held-to-maturity proceeds and the
early-exit sale price are rebuilt from QuantLib's own cash flows, accrued interest and yield pricing.

Tolerances: QuantLib is float64. Per-₹100 quantities agree to 1e-8 (spec §5 price tolerance); ₹ totals are those
per-₹100 differences scaled by the position (≤ ₹1e-4 for the positions here).
Annual-coupon SEBI ACT/ACT bonds agree exactly with ``ActualActual(ISMA)`` (see test_fixed_income_oracle.py note 2).
"""

from datetime import date
from decimal import Decimal

import pytest
import QuantLib as ql

from iip.engine import candidates as cb
from iip.engine import fixed_income as fi
from iip.engine.tax import Regime, ResidentialStatus, TaxProfile
from iip.rules.loader import load_tax_rules

pytestmark = pytest.mark.oracle

RULES = load_tax_rules()
AS_OF = date(2026, 10, 15)
SETTLE = date(2026, 10, 16)
P30 = TaxProfile(
    regime=Regime.NEW,
    residential_status=ResidentialStatus.RESIDENT,
    slab_rate=Decimal("0.30"),
    surcharge_rate=Decimal(),
)
PER_100_TOL = 1e-8
INR_TOL = 1e-4


def qd(d: date) -> ql.Date:
    return ql.Date(d.day, d.month, d.year)


def _ql_bond(coupon: float, start: date, maturity: date, freq: int, gsec: bool) -> ql.FixedRateBond:
    period = {1: ql.Annual, 2: ql.Semiannual}[freq]
    sched = ql.Schedule(qd(start), qd(maturity), ql.Period(period), ql.NullCalendar(), ql.Unadjusted, ql.Unadjusted,
                        ql.DateGeneration.Backward, False)  # fmt: skip
    dc = ql.Thirty360(ql.Thirty360.European) if gsec else ql.ActualActual(ql.ActualActual.ISMA, sched)
    return ql.FixedRateBond(0, 100.0, sched, [coupon], dc, ql.Unadjusted, 100.0)


def _remaining(qb: ql.FixedRateBond, after: date) -> float:
    return sum(cf.amount() for cf in qb.cashflows() if cf.date() > qd(after))


@pytest.mark.parametrize(
    ("kind", "coupon", "freq", "issue", "maturity", "withdrawal", "clean", "face"),
    [
        (fi.BondKind.GSEC, "0.071", 2, date(2022, 4, 15), date(2027, 4, 15), date(2027, 4, 15), "99.80", "100"),
        (fi.BondKind.GSEC, "0.0726", 2, date(2023, 1, 31), date(2029, 1, 31), date(2029, 3, 1), "101.15", "100"),
        (fi.BondKind.SDL, "0.0745", 2, date(2021, 11, 20), date(2031, 11, 20), date(2032, 1, 1), "100.40", "100"),
        (fi.BondKind.CORPORATE, "0.09", 1, date(2024, 10, 15), date(2029, 10, 15), date(2029, 11, 1), "102.50",
         "10000"),
        (fi.BondKind.CORPORATE, "0.085", 1, date(2024, 3, 1), date(2029, 3, 1), date(2029, 3, 1), "99.10", "1000"),
    ],
)  # fmt: skip
def test_held_to_maturity_proceeds_vs_quantlib(
    kind: fi.BondKind,
    coupon: str,
    freq: int,
    issue: date,
    maturity: date,
    withdrawal: date,
    clean: str,
    face: str,
) -> None:
    ql.Settings.instance().evaluationDate = qd(SETTLE)
    gsec = kind is not fi.BondKind.CORPORATE
    terms = cb.BondTerms(kind, Decimal(coupon), freq, issue, maturity, Decimal(face), 1 if gsec else 15, True)
    rating = cb.NO_RATING if gsec else cb.BondRating("AAA", "CRISIL", date(2026, 6, 1))
    b = cb.bond_candidate(
        instrument_id="o", name="oracle", amount=Decimal("500000"), as_of=AS_OF, withdrawal=withdrawal, terms=terms,
        quote=cb.BondQuote(date(2026, 10, 14), clean_price=Decimal(clean)), rating=rating,
        transaction_spread=Decimal(0), ruleset=RULES, profile=P30,
    )  # fmt: skip
    assert b.evidence is not None and b.evidence.gross_end_value is not None, b.ineligible_reasons
    inputs = dict(b.evidence.inputs)
    qb = _ql_bond(float(coupon), issue, maturity, freq, gsec)

    accrued = float(inputs["accrued_per_100"])
    assert abs(accrued - qb.accruedAmount(qd(SETTLE))) < PER_100_TOL
    units = int(inputs["units"])
    factor = units * float(face) / 100
    dirty = float(clean) + qb.accruedAmount(qd(SETTLE))
    assert units == int(500000 // (float(face) * dirty / 100))
    idle = 500000 - factor * dirty
    expected_gross = idle + factor * _remaining(qb, SETTLE)
    assert abs(float(b.evidence.gross_end_value) - expected_gross) < INR_TOL


def test_ytm_quote_clean_price_vs_quantlib() -> None:
    """Corporate YTM quoted with ANNUAL compounding (9 % annual-coupon bond): QuantLib clean price at the same yield."""
    ql.Settings.instance().evaluationDate = qd(SETTLE)
    terms = cb.BondTerms(fi.BondKind.CORPORATE, Decimal("0.09"), 1, date(2024, 10, 15), date(2029, 10, 15),
                         Decimal("10000"), 15, True)  # fmt: skip
    quote = cb.BondQuote(date(2026, 10, 14), ytm=Decimal("0.0812"), ytm_compounding=fi.Compounding.ANNUAL)
    b = cb.bond_candidate(
        instrument_id="o", name="oracle", amount=Decimal("500000"), as_of=AS_OF, withdrawal=date(2029, 11, 1),
        terms=terms, quote=quote,
        rating=cb.BondRating("AAA", "CRISIL", date(2026, 6, 1)), transaction_spread=Decimal(0), ruleset=RULES,
        profile=P30,
    )  # fmt: skip
    assert b.evidence is not None
    qb = _ql_bond(0.09, date(2024, 10, 15), date(2029, 10, 15), 1, False)
    dc = ql.ActualActual(ql.ActualActual.ISMA)
    ql_clean = ql.BondFunctions.cleanPrice(qb, ql.InterestRate(0.0812, dc, ql.Compounded, ql.Annual), qd(SETTLE))
    assert abs(float(dict(b.evidence.inputs)["clean_price_per_100"]) - ql_clean) < PER_100_TOL


def test_early_exit_mid_scenario_vs_quantlib() -> None:
    """Y-2 bond (7.10 % GS 2036) at 6.50 %, sold 15-Apr-2027 at 6.50 % + 0 bp + 25 bp exit spread."""
    exit_day = date(2027, 4, 15)
    terms = cb.BondTerms(fi.BondKind.GSEC, Decimal("0.071"), 2, date(2026, 4, 15), date(2036, 4, 15), Decimal(100), 1,
                         True)  # fmt: skip
    b = cb.bond_candidate(
        instrument_id="o", name="oracle", amount=Decimal("100000"), as_of=AS_OF, withdrawal=exit_day, terms=terms,
        quote=cb.BondQuote(date(2026, 10, 14), ytm=Decimal("0.065")), rating=cb.NO_RATING,
        transaction_spread=Decimal(0), ruleset=RULES, profile=P30,
    )  # fmt: skip
    assert b.evidence is not None and b.evidence.band_gross is not None
    inputs = dict(b.evidence.inputs)
    qb = _ql_bond(0.071, date(2026, 4, 15), date(2036, 4, 15), 2, True)
    ql.Settings.instance().evaluationDate = qd(exit_day)
    rate = ql.InterestRate(0.0675, ql.Thirty360(ql.Thirty360.European), ql.Compounded, ql.Semiannual)
    exit_dirty = ql.BondFunctions.cleanPrice(qb, rate, qd(exit_day)) + qb.accruedAmount(qd(exit_day))
    coupons = sum(cf.amount() for cf in qb.cashflows() if qd(SETTLE) < cf.date() <= qd(exit_day))
    units = int(inputs["units"])
    expected = float(inputs["cash_left_idle"]) + units * (coupons + exit_dirty)
    assert abs(float(b.evidence.band_gross[1]) - expected) < INR_TOL
