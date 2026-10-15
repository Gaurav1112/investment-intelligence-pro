"""Fixed income fixtures — calculation-methodology.md §4 (every TB/AI/Y/D/CB/YC/SP/RR/EE fixture) + edge cases."""

from dataclasses import FrozenInstanceError
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pytest

from iip.engine.dates import DayCount, days_30e_360
from iip.engine.errors import InvalidInput, NumericalError
from iip.engine.fixed_income import (
    CREDIT_RISK,
    LARGE_SHOCK,
    NEGATIVE_YIELD,
    Bond,
    BondKind,
    CallOption,
    Compounding,
    UnsupportedSchedule,
    Yield,
    accrued_30e_360,
    accrued_interest,
    bond_cashflows,
    bond_risk,
    corporate_bond,
    coupon_schedule,
    early_exit_scenarios,
    gsec,
    maturity_proceeds,
    price_change,
    price_from_yield,
    realised_return,
    settlement_consideration,
    spread_sensitivity,
    tbill_days,
    tbill_price,
    tbill_yield,
    yield_from_price,
    yield_to_call,
    yield_to_worst,
)
from iip.engine.money import engine_context, quantize

SEMI = Compounding.SEMIANNUAL
ANNUAL = Compounding.ANNUAL


def q4(x: Decimal) -> Decimal:
    return quantize(x, Decimal("0.0001"))


def pct4(x: Decimal) -> Decimal:
    """Fraction → percent at 4 dp (the spec's fixture precision)."""
    with engine_context():
        return quantize(x * 100, Decimal("0.0001"))


def y(v: str, comp: Compounding = SEMI) -> Yield:
    return Yield(Decimal(v), comp)


# ---------------------------------------------------------------------------------------------- T-bills §4.1


@pytest.mark.parametrize(
    ("days", "rate", "price"),
    [(91, "0.065", "98.4053"), (182, "0.066", "96.8139"), (364, "0.067", "93.7368")],
    ids=["TB-1", "TB-2", "TB-3"],
)
def test_tbill_price_fixtures(days: int, rate: str, price: str) -> None:
    r = tbill_price(Decimal(rate), days)
    assert q4(r.price) == Decimal(price)
    assert r.money_market_yield.compounding is Compounding.SIMPLE
    assert r.day_count is DayCount.ACT_365F
    assert r.formula_id == "TBILL_PRICE@1"


@pytest.mark.parametrize(
    ("days", "price", "yield_pct"),
    [(182, "96.80", "6.6297"), (41, "99.25", "6.7273"), (91, "98", "8.1857")],
    ids=["TB-4", "TB-5", "TB-7"],
)
def test_tbill_yield_fixtures(days: int, price: str, yield_pct: str) -> None:
    assert pct4(tbill_yield(Decimal(price), days).money_market_yield.value) == Decimal(yield_pct)


def test_tb6_364_basis_is_wrong_and_quantified() -> None:
    right = tbill_price(Decimal("0.065"), 91).price
    with engine_context():
        wrong = Decimal(100) / (1 + Decimal("0.065") * 91 / Decimal(364))
    assert q4(wrong) == Decimal("98.4010")
    assert q4(right - wrong) == Decimal("0.0043")


def test_tb1_effective_yield_and_rupee_outcome() -> None:
    r = tbill_price(Decimal("0.065"), 91, face_amount=Decimal(100000))
    assert pct4(r.effective_annual_yield) == Decimal("6.6603")
    assert quantize(r.consideration or Decimal(0), Decimal("0.01"), ROUND_HALF_UP) == Decimal("98405.30")
    assert r.maturity_value == Decimal(100000)


@pytest.mark.parametrize(
    ("price", "days", "rbi_yield_pct"),
    [("98.5920", 91, "5.7281"), ("96.9592", 182, "6.2896"), ("93.9220", 364, "6.4891")],
)
def test_tbill_yield_reproduces_rbi_auction_cutoffs(price: str, days: int, rbi_yield_pct: str) -> None:
    # RBI press release of 14-Oct-2026 (cut-off), rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=63803.
    assert pct4(tbill_yield(Decimal(price), days).money_market_yield.value) == Decimal(rbi_yield_pct)


def test_tbill_round_trip_and_days_helper() -> None:
    d = tbill_days(date(2026, 10, 16), date(2027, 1, 15))
    assert d == 91
    p = tbill_price(Decimal("0.0573"), d).price
    assert abs(tbill_yield(p, d).money_market_yield.value - Decimal("0.0573")) < Decimal("1e-30")


def test_tbill_last_day_and_matured() -> None:
    r = tbill_price(Decimal("0.065"), 1)
    with engine_context():
        assert r.price == Decimal(100) / (1 + Decimal("0.065") / 365)
    with pytest.raises(InvalidInput):
        tbill_price(Decimal("0.065"), 0)
    with pytest.raises(InvalidInput):
        tbill_yield(Decimal(100), 0)
    with pytest.raises(InvalidInput):
        tbill_price(Decimal("0.065"), 365)


def test_tbill_negative_yield_flagged_not_hidden() -> None:
    r = tbill_yield(Decimal("100.01"), 91)
    assert r.money_market_yield.value < 0
    assert NEGATIVE_YIELD in r.warnings
    assert q4(tbill_price(r.money_market_yield.value, 91).price) == Decimal("100.0100")
    with pytest.raises(InvalidInput):
        tbill_price(Decimal("-5"), 91)  # 1 + y·D/365 ≤ 0
    with pytest.raises(InvalidInput):
        tbill_yield(Decimal(0), 91)


def test_tbill_extremely_large_face_is_exact() -> None:
    face = Decimal("10000000000000")  # ₹10 lakh crore
    r = tbill_price(Decimal("0.065"), 91, face_amount=face)
    assert r.consideration is not None
    # 34 significant digits leave ~20 decimal places at ₹10^13: far below a paisa.
    with engine_context():
        assert abs(r.consideration - face * r.price / 100) < Decimal("1e-18")
    assert quantize(r.consideration, Decimal("0.01"), ROUND_HALF_UP) == Decimal("9840529501368.24")


# ---------------------------------------------------------------------------------------------- accrual §4.2

AI1_BOND = gsec(Decimal("0.0883"), date(2023, 11, 25))


def test_ai1_rbi_faq_example() -> None:
    settle = date(2014, 1, 30)
    ai = accrued_interest(AI1_BOND, settle)
    assert ai.accrued_days == 65
    assert ai.previous_coupon == date(2013, 11, 25)
    assert ai.next_coupon == date(2014, 5, 25)
    assert ai.accrued_quoted == Decimal("1.5943")
    c = settlement_consideration(AI1_BOND, settle, Decimal("100.50"), Decimal(50000000))
    assert c.dirty_price == Decimal("102.0943")
    assert c.consideration == Decimal("51047150.00")
    assert accrued_30e_360(Decimal("0.0883"), date(2013, 11, 25), settle) == ai.accrued


@pytest.mark.parametrize(
    ("start", "end", "days30e", "actual"),
    [
        (date(2025, 8, 31), date(2026, 2, 28), 178, 181),  # AI-2
        (date(2027, 8, 31), date(2028, 2, 29), 179, 182),  # AI-3 leap
        (date(2028, 1, 31), date(2028, 3, 1), 31, 30),  # AI-4: 30E can exceed actual
    ],
    ids=["AI-2", "AI-3", "AI-4"],
)
def test_30e_month_end_fixtures(start: date, end: date, days30e: int, actual: int) -> None:
    assert days_30e_360(start, end) == days30e
    assert (end - start).days == actual


def test_ai2_accrued_value() -> None:
    ai = accrued_30e_360(Decimal("0.071"), date(2025, 8, 31), date(2026, 2, 28))
    assert quantize(ai, Decimal("0.0001"), ROUND_HALF_UP) == Decimal("3.5106")


def test_month_end_bond_accrual_before_february_coupon() -> None:
    b = gsec(Decimal("0.071"), date(2036, 8, 31), shut_days=0)
    ai = accrued_interest(b, date(2026, 2, 27))
    assert (ai.previous_coupon, ai.next_coupon) == (date(2025, 8, 31), date(2026, 2, 28))
    assert ai.accrued_days == 177
    with engine_context():
        assert ai.accrued == Decimal("7.1") * 177 / 360


def test_february_start_period_over_accrual_is_refused() -> None:
    # 28-Feb → 31-Aug has 182 30E days > E = 180: the spec's PRICE formula gives DSC < 0. Spec issue; refuse.
    b = gsec(Decimal("0.071"), date(2036, 8, 31), shut_days=0)
    assert accrued_interest(b, date(2026, 8, 15)).accrued_days == 167
    with pytest.raises(UnsupportedSchedule):
        price_from_yield(b, date(2026, 8, 30), y("0.065"))


def test_end_of_month_schedule_flag() -> None:
    eom = gsec(Decimal("0.07"), date(2027, 2, 28), end_of_month=True)
    plain = gsec(Decimal("0.07"), date(2027, 2, 28))
    eom_ends = [p.end for p in coupon_schedule(eom, date(2023, 9, 1)).periods]
    plain_ends = [p.end for p in coupon_schedule(plain, date(2023, 9, 1)).periods]
    assert eom_ends == [
        date(2024, 2, 29), date(2024, 8, 31), date(2025, 2, 28), date(2025, 8, 31),
        date(2026, 2, 28), date(2026, 8, 31), date(2027, 2, 28),
    ]  # fmt: skip
    assert plain_ends[1] == date(2024, 8, 28)
    with pytest.raises(InvalidInput):
        gsec(Decimal("0.07"), date(2027, 2, 27), end_of_month=True)


def test_settlement_on_coupon_date() -> None:
    b = gsec(Decimal("0.08"), date(2029, 4, 15))
    r = price_from_yield(b, date(2026, 4, 15), y("0.08"))
    assert r.accrued == 0 and r.accrued_days == 0
    assert r.clean == r.dirty
    assert r.previous_coupon == date(2026, 4, 15)
    assert r.cashflows[0].pay_date == date(2026, 10, 15)  # the coupon on the settlement date is the seller's
    assert r.remaining_coupons == 6
    assert q4(r.clean) == Decimal("100.0000")  # Y-3 par check


def test_shut_period_refused_and_parameterised() -> None:
    b = gsec(Decimal("0.071"), date(2036, 4, 15))
    with pytest.raises(InvalidInput, match="shut period"):
        accrued_interest(b, date(2026, 10, 14))
    b0 = gsec(Decimal("0.071"), date(2036, 4, 15), shut_days=0)
    assert accrued_interest(b0, date(2026, 10, 14)).accrued_days == 179


# ---------------------------------------------------------------------------------------------- price/YTM §4.3


def test_y1_rbi_box_iii() -> None:
    b = gsec(Decimal("0.08"), date(2028, 4, 15))
    r = yield_from_price(b, date(2026, 4, 15), Decimal(102))
    assert pct4(r.ytm.value) == Decimal("6.9121")
    assert r.ytm.compounding is SEMI
    assert r.residual <= Decimal("1e-10")


Y2 = gsec(Decimal("0.071"), date(2036, 4, 15))
Y2_SETTLE = date(2026, 10, 16)


def test_y2_synthetic_gsec() -> None:
    r = price_from_yield(Y2, Y2_SETTLE, y("0.065"))
    assert (r.remaining_coupons, r.accrued_days, r.days_to_next, r.period_days) == (19, 1, 179, 180)
    assert q4(r.clean) == Decimal("104.2024")
    assert q4(r.accrued) == Decimal("0.0197")
    assert q4(r.dirty) == Decimal("104.2221")
    back = yield_from_price(Y2, Y2_SETTLE, r.clean)
    assert abs(back.ytm.value - Decimal("0.065")) < Decimal("1e-12")


def test_effective_annual_yield() -> None:
    assert pct4(y("0.065").effective_annual()) == Decimal("6.6056")


def test_yield_tag_conversion_is_explicit() -> None:
    annual = y("0.08", ANNUAL)
    semi = annual.to(SEMI)
    assert abs(semi.effective_annual() - Decimal("0.08")) < Decimal("1e-30")
    a = price_from_yield(Y2, Y2_SETTLE, annual)
    b = price_from_yield(Y2, Y2_SETTLE, semi)
    assert abs(a.clean - b.clean) < Decimal("1e-25")
    assert any(w.startswith("YIELD_CONVERTED") for w in a.warnings)
    with pytest.raises(InvalidInput):
        price_from_yield(Y2, Y2_SETTLE, y("0.065", Compounding.SIMPLE))


def test_negative_ytm_is_meaningful_and_flagged() -> None:
    b = gsec(Decimal("0.02"), date(2028, 4, 15))
    total = bond_cashflows(b, date(2026, 4, 15)).total
    r = yield_from_price(b, date(2026, 4, 15), total + 1)  # paying more than every future rupee
    assert r.ytm.value < 0
    assert NEGATIVE_YIELD in r.warnings
    assert abs(price_from_yield(b, date(2026, 4, 15), r.ytm).clean - (total + 1)) < Decimal("1e-10")
    with pytest.raises(InvalidInput):
        price_from_yield(b, date(2026, 4, 15), y("-2"))  # 1 + y/2 = 0


def test_unsolvable_price_raises_not_degrades() -> None:
    with pytest.raises(NumericalError):
        yield_from_price(Y2, Y2_SETTLE, Decimal(1000000))
    with pytest.raises(InvalidInput):
        yield_from_price(Y2, Y2_SETTLE, Decimal(0))


def test_settlement_bounds_and_odd_schedules() -> None:
    with pytest.raises(InvalidInput):
        price_from_yield(Y2, date(2036, 4, 15), y("0.065"))
    with pytest.raises(UnsupportedSchedule):
        gsec(Decimal("0.07"), date(2036, 4, 15), issue_date=date(2026, 5, 1))
    b = gsec(Decimal("0.07"), date(2036, 4, 15), issue_date=date(2026, 4, 15))
    with pytest.raises(InvalidInput):
        price_from_yield(b, date(2026, 4, 1), y("0.07"))
    with pytest.raises(InvalidInput):
        Bond(BondKind.GSEC, Decimal("0.07"), date(2036, 4, 15), 1, DayCount.THIRTY_E_360, 1)
    with pytest.raises(InvalidInput):
        Bond(BondKind.CORPORATE, Decimal("0.07"), date(2036, 4, 15), 2, DayCount.THIRTY_E_360, 0)


def test_results_are_frozen() -> None:
    r = price_from_yield(Y2, Y2_SETTLE, y("0.065"))
    with pytest.raises(FrozenInstanceError):
        r.clean = Decimal(1)  # type: ignore[misc]


# ---------------------------------------------------------------------------------------------- risk §4.4

D1 = gsec(Decimal("0.08"), date(2029, 4, 15))
D1_SETTLE = date(2026, 4, 15)


def test_d1_hand_computable() -> None:
    r = bond_risk(D1, D1_SETTLE, y("0.08"))
    assert q4(r.macaulay_duration) == Decimal("2.7259")
    assert q4(r.modified_duration) == Decimal("2.6211")
    assert q4(r.convexity) == Decimal("8.5329")
    c = price_change(D1, D1_SETTLE, y("0.08"), Decimal("0.01"))
    assert q4(c.dirty_after) == Decimal("97.4211")
    assert pct4(c.exact_change) == Decimal("-2.5789")
    assert pct4(c.duration_convexity) == Decimal("-2.5784")
    assert c.headline_method == "FULL_REPRICE"
    assert LARGE_SHOCK not in c.warnings


def test_d2_risk() -> None:
    r = bond_risk(Y2, Y2_SETTLE, y("0.065"))
    assert q4(r.macaulay_duration) == Decimal("7.1215")
    assert q4(r.modified_duration) == Decimal("6.8973")
    assert q4(r.convexity) == Decimal("60.0072")
    with engine_context():
        assert r.dv01 == r.modified_duration * r.dirty_price * Decimal("0.0001")


@pytest.mark.parametrize(
    ("shock", "exact", "dur_conv", "dur_only"),
    [
        ("0.005", "-3.3749", "-3.3737", "-3.4487"),
        ("-0.005", "3.5249", "3.5237", "3.4487"),
        ("0.02", "-12.6678", "-12.5946", "-13.7947"),
    ],
)
def test_d2_shock_table(shock: str, exact: str, dur_conv: str, dur_only: str) -> None:
    c = price_change(Y2, Y2_SETTLE, y("0.065"), Decimal(shock))
    assert pct4(c.exact_change) == Decimal(exact)
    assert pct4(c.duration_convexity) == Decimal(dur_conv)
    assert pct4(c.duration_only) == Decimal(dur_only)
    assert (LARGE_SHOCK in c.warnings) is (abs(Decimal(shock)) > Decimal("0.01"))


# ---------------------------------------------------------------------------------------------- corporate §4.5


def test_cb1_sebi_leap_year_example() -> None:
    b = corporate_bond(Decimal("0.08"), date(2019, 1, 1), 2, shut_days=0, issue_date=date(2016, 1, 1))
    p = coupon_schedule(b).periods
    assert (p[0].start, p[0].end, p[0].actual_days, p[0].denominator) == (date(2016, 1, 1), date(2016, 7, 1), 182, 366)
    assert q4(p[0].amount) == Decimal("3.9781")
    assert (p[1].actual_days, p[1].denominator) == (184, 366)
    assert q4(p[1].amount) == Decimal("4.0219")
    with engine_context():
        assert p[0].amount + p[1].amount == Decimal("8.000000000000000000000000000000000")
    ai = accrued_interest(b, date(2016, 4, 1))
    with engine_context():
        assert abs(ai.accrued - Decimal(8) * 91 / 366) < Decimal("1e-32")


def test_cb2_sebi_non_leap() -> None:
    b = corporate_bond(Decimal("0.08"), date(2028, 1, 1), 2, shut_days=0, issue_date=date(2025, 1, 1))
    p = coupon_schedule(b).periods
    assert [q4(x.amount) for x in p[:2]] == [Decimal("3.9671"), Decimal("4.0329")]
    assert [x.denominator for x in p[:2]] == [365, 365]


def test_zero_coupon_bond() -> None:
    b = corporate_bond(Decimal(0), date(2031, 6, 30), 1, shut_days=0)
    r = price_from_yield(b, date(2026, 6, 30), y("0.08", ANNUAL))
    with engine_context():
        assert abs(r.clean - Decimal(100) / Decimal("1.08") ** 5) < Decimal("1e-28")
    assert [cf.kind for cf in r.cashflows] == ["redemption"]
    assert r.accrued == 0
    risk = bond_risk(b, date(2026, 6, 30), r.ytm)
    assert abs(risk.macaulay_duration - 5) < Decimal("1e-28")
    mid = bond_risk(b, date(2027, 1, 1), r.ytm)  # w = 180/365 of a period
    with engine_context():
        assert abs(mid.macaulay_duration - (4 + Decimal(180) / 365)) < Decimal("1e-28")
    assert yield_from_price(b, date(2026, 6, 30), r.clean).residual <= Decimal("1e-10")


# ---------------------------------------------------------------------------------------------- YTC/YTW §4.6

YC1 = corporate_bond(Decimal("0.09"), date(2031, 6, 30), 1, shut_days=0)
YC1_SETTLE = date(2026, 6, 30)


def test_yc1() -> None:
    r = yield_to_worst(YC1, YC1_SETTLE, Decimal("102.50"), [CallOption(date(2028, 6, 30), Decimal(100))])
    assert pct4(r.ytm.ytm.value) == Decimal("8.3678")
    assert pct4(r.ytc[0].ytm.value) == Decimal("7.6057")
    assert r.yield_to_worst == r.ytc[0].ytm
    assert r.worst_date == date(2028, 6, 30)
    assert r.headline == "YTW"
    assert r.ytm.ytm.compounding is ANNUAL


def test_ytw_ignores_past_calls_and_rejects_off_schedule_call() -> None:
    r = yield_to_worst(YC1, YC1_SETTLE, Decimal("95"), [CallOption(date(2025, 6, 30), Decimal(100))])
    assert r.headline == "YTM" and r.ytc == ()
    with pytest.raises(UnsupportedSchedule):
        yield_to_call(YC1, YC1_SETTLE, Decimal(100), date(2028, 3, 31), Decimal(100))


# ---------------------------------------------------------------------------------------------- spread §4.7


def test_sp1_spread_duration() -> None:
    r = spread_sensitivity(YC1, YC1_SETTLE, y("0.065", ANNUAL), Decimal("0.015"), Decimal("0.01"))
    assert q4(r.price_before) == Decimal("103.9927")
    assert q4(r.spread_duration) == Decimal("3.9406")
    assert q4(bond_risk(YC1, YC1_SETTLE, r.bond_yield).macaulay_duration) == Decimal("4.2559")
    assert q4(r.price_after) == Decimal("100.0000")
    assert pct4(r.exact_change) == Decimal("-3.8394")
    assert pct4(r.approximate_change) == Decimal("-3.9406")
    assert CREDIT_RISK in r.warnings


# ---------------------------------------------------------------------------------------------- §4.8, §4.9


def test_rr1_realised_return() -> None:
    r = realised_return(D1, D1_SETTLE, y("0.08"), y("0.06"))
    assert q4(r.future_value) == Decimal("125.8736")
    assert pct4(r.realised_effective_annual) == Decimal("7.9721")
    assert pct4(r.realised_bond_equivalent.value) == Decimal("7.8193")
    assert r.realised_bond_equivalent.compounding is SEMI


@pytest.mark.parametrize(
    ("shock_bp", "exit_price", "hpr_pct"),
    [(100, "98.2062", "6.2062"), (-100, "101.8365", "9.8365"), (0, "100.0000", "8.0000")],
)
def test_ee1_early_exit(shock_bp: int, exit_price: str, hpr_pct: str) -> None:
    r = early_exit_scenarios(D1, D1_SETTLE, y("0.08"), date(2027, 4, 15), shocks_bp=(shock_bp,), exit_spread_bp=0)
    s = r.scenarios[0]
    assert q4(s.exit_clean) == Decimal(exit_price)
    assert s.coupons_received == Decimal(8)
    assert pct4(s.holding_period_return) == Decimal(hpr_pct)


def test_early_exit_default_spread_and_reinvestment() -> None:
    r = early_exit_scenarios(D1, D1_SETTLE, y("0.08"), date(2027, 4, 15), reinvestment_rate=y("0.06"))
    assert r.exit_spread == Decimal("0.0025")  # G-sec default 25 bp (NOT VERIFIED; flagged)
    assert "EXIT_SPREAD_ASSUMPTION_NOT_VERIFIED" in r.warnings
    assert [s.shock for s in r.scenarios] == [Decimal(b) / 10000 for b in (-100, -50, 0, 50, 100, 200)]
    assert r.scenarios[0].coupons_received > 8  # first coupon grew for 182 days
    with pytest.raises(InvalidInput):
        early_exit_scenarios(D1, D1_SETTLE, y("0.08"), date(2029, 4, 15))


def test_maturity_proceeds_and_large_face() -> None:
    face = Decimal("1000000000000000")  # ₹10^15
    r = maturity_proceeds(D1, face)
    assert r.principal == face
    assert r.final_coupon == face * 4 / 100
    assert r.total_display == Decimal("1040000000000000.00")
    c = settlement_consideration(Y2, Y2_SETTLE, Decimal("104.2024"), Decimal("10000000000000"))
    assert c.consideration == Decimal("10422210000000.00")  # 10^13 × (104.2024 + 0.0197) / 100
    assert CREDIT_RISK in maturity_proceeds(YC1, Decimal(10000)).warnings
