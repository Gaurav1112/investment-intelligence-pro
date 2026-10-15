"""Fixed deposits and DICGC — calculation-methodology.md §3 fixtures (FD-1..7, FD-P1) + research §5 rules."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from iip.engine.deposits import (
    ABOVE_LIMIT,
    DICGC_LIMIT,
    LEAP_SPLIT,
    NO_INTEREST_BEFORE_MIN_TENURE,
    NOT_INSURED,
    RATE_FLOORED_AT_ZERO,
    DepositHolding,
    FDMethod,
    InstitutionType,
    PrematureRateBasis,
    dicgc_coverage,
    fd_effective_annual_yield,
    fd_maturity,
    fd_premature_withdrawal,
)
from iip.engine.errors import InvalidInput, RuleNotFound
from iip.engine.money import engine_context, quantize

LAKH = Decimal(100000)
TOL = Decimal("0.05")  # spec §3.2 tolerance for maturity amounts
START = date(2025, 10, 15)


def pct4(x: Decimal) -> Decimal:
    with engine_context():
        return quantize(x * 100, Decimal("0.0001"))


@pytest.mark.parametrize(
    ("rate", "maturity", "expected", "method", "quarters"),
    [
        ("0.07", date(2026, 10, 15), "107185.90", FDMethod.QUARTERLY_COMPOUND, 4),  # FD-1
        ("0.07", date(2027, 10, 15), "114888.18", FDMethod.QUARTERLY_COMPOUND, 8),  # FD-2
        ("0.07", START + timedelta(days=90), "101726.03", FDMethod.SIMPLE, 0),  # FD-3
        ("0.07", START + timedelta(days=179), "103432.88", FDMethod.SIMPLE, 0),  # FD-4
        ("0.07", date(2026, 11, 19), "107905.37", FDMethod.QUARTERLY_COMPOUND, 4),  # FD-5
        ("0.075", date(2030, 10, 15), "144994.80", FDMethod.QUARTERLY_COMPOUND, 20),  # FD-7
    ],
    ids=["FD-1", "FD-2", "FD-3", "FD-4", "FD-5", "FD-7"],
)
def test_fd_fixtures(rate: str, maturity: date, expected: str, method: FDMethod, quarters: int) -> None:
    r = fd_maturity(LAKH, Decimal(rate), START, maturity)
    assert r.maturity_amount_display == Decimal(expected)
    assert abs(r.maturity_amount - Decimal(expected)) <= TOL
    assert r.method is method
    assert r.complete_quarters == quarters
    assert r.formula_id == "FD_MATURITY@1"


def test_fd5_broken_period_detail() -> None:
    r = fd_maturity(LAKH, Decimal("0.07"), START, date(2026, 11, 19))
    assert (r.days, r.broken_days) == (400, 35)
    with engine_context():
        compounded = LAKH * Decimal("1.0175") ** 4
        assert abs(compounded * Decimal("0.07") * 35 / 365 - Decimal("719.4670")) < Decimal("0.0001")


def test_fd6_leap_year_and_denominator_sensitivity() -> None:
    start, end = date(2027, 10, 15), date(2028, 11, 19)
    r365 = fd_maturity(LAKH, Decimal("0.07"), start, end)
    assert r365.days == 401
    assert r365.maturity_amount_display == Decimal("107905.37")
    r366 = fd_maturity(LAKH, Decimal("0.07"), start, end, leap_denominator=366)
    with engine_context():
        broken = r366.maturity_amount - LAKH * Decimal("1.0175") ** 4
    assert quantize(broken, Decimal("0.01")) == Decimal("717.50")  # spec FD-6, 366 bank
    assert r366.maturity_amount < r365.maturity_amount
    assert LEAP_SPLIT not in r366.warnings


def test_leap_denominator_split_across_years_is_flagged() -> None:
    r = fd_maturity(LAKH, Decimal("0.07"), date(2027, 12, 1), date(2028, 1, 30), leap_denominator=366)
    with engine_context():
        expected = LAKH * (1 + Decimal("0.07") * (Decimal(31) / 365 + Decimal(29) / 366))
    assert abs(r.maturity_amount - expected) < Decimal("1e-25")
    assert LEAP_SPLIT in r.warnings
    with pytest.raises(InvalidInput):
        fd_maturity(LAKH, Decimal("0.07"), START, date(2026, 10, 15), leap_denominator=364)


def test_eay() -> None:
    assert pct4(fd_effective_annual_yield(Decimal("0.07"))) == Decimal("7.1859")
    assert pct4(fd_effective_annual_yield(Decimal("0.075"))) == Decimal("7.7136")
    assert pct4(fd_maturity(LAKH, Decimal("0.07"), START, date(2026, 10, 15)).effective_annual_yield) == Decimal(
        "7.1859"
    )


def test_short_tenure_cutoff_is_per_bank() -> None:
    end = START + timedelta(days=120)  # 3 complete months + broken days
    indian_bank = fd_maturity(LAKH, Decimal("0.07"), START, end)  # default < 6 m → simple
    au_sfb = fd_maturity(LAKH, Decimal("0.07"), START, end, short_tenure_cutoff_months=3)
    assert indian_bank.method is FDMethod.SIMPLE
    assert au_sfb.method is FDMethod.QUARTERLY_COMPOUND
    assert au_sfb.complete_quarters == 1
    with engine_context():
        # Oct-15 → Jan-15 is one quarter at r/4; the remaining 28 days are simple on the compounded balance.
        assert au_sfb.broken_days == 28
        assert au_sfb.maturity_amount == LAKH * Decimal("1.0175") * (1 + Decimal("0.07") * 28 / Decimal(365))
        assert indian_bank.maturity_amount == LAKH * (1 + Decimal("0.07") * 120 / Decimal(365))
    six = fd_maturity(LAKH, Decimal("0.07"), START, date(2026, 4, 15))  # exactly 6 months → compounding
    assert six.method is FDMethod.QUARTERLY_COMPOUND and six.complete_quarters == 2


def test_month_end_deposit_quarters_use_edate() -> None:
    r = fd_maturity(LAKH, Decimal("0.07"), date(2026, 1, 31), date(2026, 7, 31))
    assert r.complete_quarters == 2 and r.broken_days == 0  # 31-Jan → 30-Apr → 31-Jul


def test_fd_validation() -> None:
    with pytest.raises(InvalidInput):
        fd_maturity(LAKH, Decimal("0.07"), START, START + timedelta(days=6))
    with pytest.raises(InvalidInput):
        fd_maturity(LAKH, Decimal("-0.01"), START, date(2026, 10, 15))
    with pytest.raises(InvalidInput):
        fd_maturity(Decimal(0), Decimal("0.07"), START, date(2026, 10, 15))
    assert fd_maturity(LAKH, Decimal(0), START, date(2026, 10, 15)).maturity_amount == LAKH


def test_fd_large_principal() -> None:
    p = Decimal("100000000000000")  # ₹100 lakh crore
    r = fd_maturity(p, Decimal("0.07"), START, date(2026, 10, 15))
    with engine_context():
        assert abs(r.maturity_amount - p * Decimal("1.0175") ** 4) < Decimal("1e-15")


# ---------------------------------------------------------------------------------------------- §3.3


def test_fd_p1_premature_withdrawal() -> None:
    r = fd_premature_withdrawal(
        LAKH,
        Decimal("0.0725"),
        START,
        date(2027, 10, 15),
        date(2026, 10, 15),
        period_card_rate=Decimal("0.068"),
        penalty=Decimal("0.01"),
    )
    assert r.effective_rate == Decimal("0.058")
    assert r.payout_display == Decimal("105927.37")
    assert quantize(r.at_booked_rate, Decimal("0.01")) == Decimal("107449.50")
    assert quantize(r.cost_of_breaking, Decimal("0.01")) == Decimal("1522.13")


def test_premature_penalty_has_no_default() -> None:
    with pytest.raises(TypeError):
        fd_premature_withdrawal(  # type: ignore[call-arg]
            LAKH, Decimal("0.0725"), START, date(2027, 10, 15), date(2026, 10, 15), period_card_rate=Decimal("0.068")
        )


def test_premature_rate_basis_floor_and_min_tenure() -> None:
    args = (LAKH, Decimal("0.06"), START, date(2027, 10, 15), date(2026, 10, 15))
    lower = fd_premature_withdrawal(
        *args,
        period_card_rate=Decimal("0.068"),
        penalty=Decimal("0.01"),
        rate_basis=PrematureRateBasis.MIN_BOOKED_PERIOD_CARD,
    )
    assert lower.effective_rate == Decimal("0.05")
    floored = fd_premature_withdrawal(*args, period_card_rate=Decimal("0.005"), penalty=Decimal("0.01"))
    assert floored.effective_rate == 0 and RATE_FLOORED_AT_ZERO in floored.warnings
    assert floored.payout == LAKH
    early = fd_premature_withdrawal(
        LAKH, Decimal("0.07"), START, date(2026, 10, 15), START + timedelta(days=5),
        period_card_rate=Decimal("0.03"), penalty=Decimal("0.005"),
    )  # fmt: skip
    assert early.payout == LAKH and early.payout_detail is None
    assert NO_INTEREST_BEFORE_MIN_TENURE in early.warnings
    with pytest.raises(InvalidInput):
        fd_premature_withdrawal(*args[:4], date(2027, 10, 15), period_card_rate=Decimal("0.068"), penalty=Decimal(0))


# ---------------------------------------------------------------------------------------------- DICGC


def _h(inst: str, kind: InstitutionType, dep: str, p: str, i: str, cap: str = "individual") -> DepositHolding:
    return DepositHolding(inst, kind, dep, Decimal(p), Decimal(i), cap)


AS_OF = date(2026, 10, 15)


def test_dicgc_aggregates_branches_principal_plus_interest() -> None:
    r = dicgc_coverage(
        [
            _h("SBI", InstitutionType.BANK, "me", "300000", "20000"),  # branch A
            _h("SBI", InstitutionType.BANK, "me", "200000", "10000"),  # branch B → 5,30,000 total
            _h("HDFC", InstitutionType.BANK, "me", "400000", "0"),
        ],
        as_of=AS_OF,
    )
    sbi = next(g for g in r.groups if g.institution_id == "SBI")
    assert (sbi.total, sbi.insured, sbi.uninsured) == (Decimal(530000), DICGC_LIMIT, Decimal(30000))
    assert ABOVE_LIMIT in sbi.flags
    assert (r.insured, r.uninsured, r.total) == (Decimal(900000), Decimal(30000), Decimal(930000))
    assert r.limit == Decimal(500000)


def test_dicgc_capacities_and_depositors_separate() -> None:
    r = dicgc_coverage(
        [
            _h("SBI", InstitutionType.BANK, "me", "500000", "0"),
            _h("SBI", InstitutionType.BANK, "me", "500000", "0", cap="guardian:child"),
            _h("SBI", InstitutionType.BANK, "spouse", "500000", "0"),
        ],
        as_of=AS_OF,
    )
    assert len(r.groups) == 3
    assert r.uninsured == 0


def test_nbfc_hfc_never_insured() -> None:
    r = dicgc_coverage(
        [
            _h("BajajFin", InstitutionType.NBFC, "me", "100000", "5000"),
            _h("SomeHFC", InstitutionType.HFC, "me", "1", "0"),
            _h("CoopBank", InstitutionType.COOPERATIVE_BANK, "me", "100000", "0"),
        ],
        as_of=AS_OF,
    )
    by = {g.institution_id: g for g in r.groups}
    assert by["BajajFin"].insured == 0 and by["BajajFin"].uninsured == Decimal(105000)
    assert NOT_INSURED in by["SomeHFC"].flags
    assert by["CoopBank"].insured == Decimal(100000)


def test_dicgc_rule_dates_and_validation() -> None:
    with pytest.raises(RuleNotFound):
        dicgc_coverage([], as_of=date(2020, 2, 3))
    assert dicgc_coverage([], as_of=date(2020, 2, 4)).total == 0
    with pytest.raises(InvalidInput):
        dicgc_coverage(
            [_h("X", InstitutionType.BANK, "me", "1", "0"), _h("X", InstitutionType.NBFC, "me", "1", "0")],
            as_of=AS_OF,
        )
    with pytest.raises(InvalidInput):
        dicgc_coverage([_h("X", InstitutionType.BANK, "me", "-1", "0")], as_of=AS_OF)
