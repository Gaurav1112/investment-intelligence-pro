"""Fixed income: T-bills, G-secs/SDLs and listed corporate bonds (calculation-methodology.md §4).

Conventions (see the spec for verification status):

* T-bills: money-market yield, Actual/365 simple, ``P = 100 / (1 + y·D/365)`` (RBI FAQ). 364 is a tenor, not a basis.
* G-secs/SDLs: semi-annual coupons of ``C/2``; accrual 30E/360 from the last coupon to settlement;
  price/YTM by the RBI/Excel ``PRICE`` formula (basis 4, frequency 2) with ``E = 360/f``.
* Listed corporate bonds: SEBI Actual/Actual. The denominator is 366 for every coupon period of a one-year
  window that contains 29-Feb; windows are anchored on the maturity date (the anchor is NOT VERIFIED).
* Every yield carries an explicit :class:`Compounding` tag.  Cross-instrument comparison uses the effective
  annual yield.
* Prices are per ₹100 face and are **not** quantized (rule R1).  The only replication quantities are the quoted
  accrued interest (0.0001, HALF_UP — RBI FAQ example 1.5943) and the settlement consideration (paise).
* Record date / shut period: positioned only through ``Bond.shut_days`` (NOT VERIFIED).  A settlement inside
  ``[coupon − shut_days, coupon)`` is refused; there is no negative (ex-interest) accrual in this model.
* Floats appear only inside the YTM bracket solver.  The root is polished and verified in Decimal.
"""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any

from iip.engine.dates import DayCount, add_months, contains_feb29, days_30e_360, days_between, is_month_end
from iip.engine.errors import InvalidInput, NumericalError
from iip.engine.money import ONE, ZERO, engine_context, from_float, money, quantize


def brentq(*args: Any, **kwargs: Any) -> Any:  # lazy scipy (A05 / RC-5): loaded on first use, not at app start
    from scipy.optimize import brentq as solver  # noqa: PLC0415

    return solver(*args, **kwargs)


HUNDRED = Decimal(100)
BASIS_POINT = Decimal("0.0001")
ACCRUED_QUOTE_QUANTUM = Decimal("0.0001")
YTM_PRICE_TOLERANCE = Decimal("1e-10")  # per ₹100 face (spec §4.3)
FULL_REPRICE_THRESHOLD = Decimal("0.01")  # |Δy| > 100 bp → the approximation is explanation only (§4.4)
YTM_BRACKET = (-0.5, 1.0)
TBILL_MAX_DAYS = 364
DEFAULT_EXIT_SHOCKS_BP: tuple[int, ...] = (-100, -50, 0, 50, 100, 200)

# Warning / flag codes.
NEGATIVE_YIELD = "NEGATIVE_YIELD"
YIELD_CONVERTED = "YIELD_CONVERTED_TO_COUPON_FREQUENCY"
LARGE_SHOCK = "LARGE_SHOCK_APPROXIMATION_EXPLANATION_ONLY"
YTM_ASSUMES_REINVESTMENT = "YTM_ASSUMES_HOLD_TO_MATURITY_AND_REINVESTMENT_AT_YTM"
CALL_LOWERS_YIELD = "YTM_OVERSTATES_YIELD_IF_CALLED"
EXIT_SPREAD_ASSUMED = "EXIT_SPREAD_ASSUMPTION_NOT_VERIFIED"
CREDIT_RISK = "CORPORATE_CREDIT_RISK_NOT_CAPTURED"
SPREAD_DURATION_APPROX = "SPREAD_DURATION_EQUALS_MODIFIED_DURATION_FOR_FIXED_BULLET"


class UnsupportedSchedule(InvalidInput):
    """Odd first/last coupons, off-schedule call dates and 30E/360 periods the spec does not define (§4.3)."""

    code = "UNSUPPORTED_SCHEDULE"


class Compounding(StrEnum):
    SIMPLE = "simple"  # money-market (T-bill) yield: no compounding, ACT/365
    ANNUAL = "annual"
    SEMIANNUAL = "semiannual"
    QUARTERLY = "quarterly"
    MONTHLY = "monthly"


_PERIODS_PER_YEAR: dict[Compounding, int] = {
    Compounding.ANNUAL: 1,
    Compounding.SEMIANNUAL: 2,
    Compounding.QUARTERLY: 4,
    Compounding.MONTHLY: 12,
}


def compounding_for_frequency(frequency: int) -> Compounding:
    for comp, periods in _PERIODS_PER_YEAR.items():
        if periods == frequency:
            return comp
    raise InvalidInput(f"unsupported coupon frequency {frequency}; expected 1, 2, 4 or 12")


@dataclass(frozen=True)
class Yield:
    """A nominal annual yield (fraction) with its compounding tag. Never pass a bare number as a yield."""

    value: Decimal
    compounding: Compounding

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal) or not self.value.is_finite():
            raise InvalidInput(f"yield must be a finite Decimal, got {self.value!r}")

    @property
    def periods_per_year(self) -> int:
        if self.compounding is Compounding.SIMPLE:
            raise InvalidInput("a simple money-market yield has no compounding frequency; convert it using its term")
        return _PERIODS_PER_YEAR[self.compounding]

    def effective_annual(self) -> Decimal:
        m = self.periods_per_year
        with engine_context():
            base = ONE + self.value / m
            if base <= 0:
                raise InvalidInput(f"yield {self.value} ≤ −{m} has no meaning under {self.compounding} compounding")
            return base**m - ONE

    def to(self, compounding: Compounding) -> Yield:
        """Equivalent yield under another compounding (same effective annual yield)."""
        if compounding is self.compounding:
            return self
        target = Yield(ZERO, compounding).periods_per_year
        ear = self.effective_annual()
        with engine_context():
            return Yield(target * ((ONE + ear) ** (ONE / Decimal(target)) - ONE), compounding)


# --------------------------------------------------------------------------------------------- T-bills


@dataclass(frozen=True)
class TBillResult:
    price: Decimal  # per ₹100 face, unrounded
    money_market_yield: Yield  # SIMPLE, Actual/365
    days: int  # settlement → maturity
    effective_annual_yield: Decimal  # (100/P)^(365/D) − 1; comparison only
    face_amount: Decimal | None
    consideration: Decimal | None  # face × P / 100, unrounded
    maturity_value: Decimal | None  # face (paid on maturity; holiday → next business day, no extra discount)
    day_count: DayCount
    formula_id: str
    conventions: tuple[str, ...]
    warnings: tuple[str, ...]


_TBILL_CONVENTIONS = (
    "money-market yield, Actual/365 (RBI FAQ); 364 is a tenor, not the day basis",
    "D = actual days from settlement to scheduled maturity",
)


def tbill_days(settlement: date, maturity: date) -> int:
    return days_between(settlement, maturity)


def _check_tbill_days(days: int) -> None:
    if isinstance(days, bool) or not isinstance(days, int):
        raise InvalidInput("days must be an int")
    if days < 1:
        raise InvalidInput("a T-bill needs at least 1 day to maturity; on maturity use the face value")
    if days > TBILL_MAX_DAYS:
        raise InvalidInput(f"T-bills run at most {TBILL_MAX_DAYS} days; got {days}")


def _tbill_result(price: Decimal, y: Decimal, days: int, face_amount: Decimal | None, formula: str) -> TBillResult:
    warnings: list[str] = []
    if y < 0:
        warnings.append(NEGATIVE_YIELD)
    consideration = maturity_value = None
    if face_amount is not None:
        if face_amount <= 0:
            raise InvalidInput("face_amount must be positive")
        with engine_context():
            consideration = face_amount * price / HUNDRED
        maturity_value = face_amount
    with engine_context():
        eay = (HUNDRED / price) ** (Decimal(365) / Decimal(days)) - ONE
    return TBillResult(
        price=price,
        money_market_yield=Yield(y, Compounding.SIMPLE),
        days=days,
        effective_annual_yield=eay,
        face_amount=face_amount,
        consideration=consideration,
        maturity_value=maturity_value,
        day_count=DayCount.ACT_365F,
        formula_id=formula,
        conventions=_TBILL_CONVENTIONS,
        warnings=tuple(warnings),
    )


def tbill_price(y: Decimal, days: int, *, face_amount: Decimal | None = None) -> TBillResult:
    """``P = 100 / (1 + y·D/365)``. ``y`` is the simple money-market yield (fraction)."""
    _check_tbill_days(days)
    with engine_context():
        denom = ONE + y * Decimal(days) / Decimal(365)
        if denom <= 0:
            raise InvalidInput(f"yield {y} implies a non-positive discount factor over {days} days")
        price = HUNDRED / denom
    return _tbill_result(price, y, days, face_amount, "TBILL_PRICE@1")


def tbill_yield(price: Decimal, days: int, *, face_amount: Decimal | None = None) -> TBillResult:
    """``y = (100 − P)/P × 365/D`` (RBI FAQ)."""
    _check_tbill_days(days)
    if price <= 0:
        raise InvalidInput("price must be positive")
    with engine_context():
        y = (HUNDRED - price) / price * Decimal(365) / Decimal(days)
    return _tbill_result(price, y, days, face_amount, "TBILL_YIELD@1")


# --------------------------------------------------------------------------------------------- bonds


class BondKind(StrEnum):
    GSEC = "G-sec"
    SDL = "SDL"
    CORPORATE = "corporate"


@dataclass(frozen=True)
class Bond:
    """A plain fixed-rate bullet. Coupon dates are generated backwards from ``maturity`` (EDATE)."""

    kind: BondKind
    coupon_rate: Decimal  # fraction, e.g. Decimal("0.071")
    maturity: date
    frequency: int
    day_count: DayCount
    shut_days: int  # record-date shut period in calendar days (positioning NOT VERIFIED)
    redemption: Decimal = HUNDRED  # per ₹100 face
    issue_date: date | None = None
    end_of_month: bool = False

    def __post_init__(self) -> None:
        compounding_for_frequency(self.frequency)
        if not isinstance(self.coupon_rate, Decimal) or not self.coupon_rate.is_finite() or self.coupon_rate < 0:
            raise InvalidInput("coupon_rate must be a finite non-negative Decimal fraction")
        if self.redemption <= 0:
            raise InvalidInput("redemption must be positive")
        if self.shut_days < 0:
            raise InvalidInput("shut_days must be ≥ 0")
        if self.day_count not in (DayCount.THIRTY_E_360, DayCount.ACT_ACT_SEBI):
            raise InvalidInput(f"coupon bonds support 30E/360 (G-sec/SDL) or ACT/ACT-SEBI only, not {self.day_count}")
        if self.kind in (BondKind.GSEC, BondKind.SDL):
            if self.day_count is not DayCount.THIRTY_E_360 or self.frequency != 2:
                raise InvalidInput("G-secs/SDLs are semi-annual 30E/360 (RBI FAQ)")
        elif self.day_count is not DayCount.ACT_ACT_SEBI:
            raise InvalidInput("listed corporate bonds use ACT/ACT-SEBI")
        if self.end_of_month and not is_month_end(self.maturity):
            raise InvalidInput("end_of_month requires a month-end maturity")
        if self.issue_date is not None:
            if self.issue_date >= self.maturity:
                raise InvalidInput("issue_date must precede maturity")
            j = 0
            while _coupon_date(self, j) > self.issue_date:
                j += 1
            if _coupon_date(self, j) != self.issue_date:
                raise UnsupportedSchedule("odd first coupon (issue date off the regular schedule) is out of scope v1")

    @property
    def months_per_period(self) -> int:
        return 12 // self.frequency

    @property
    def compounding(self) -> Compounding:
        return compounding_for_frequency(self.frequency)


def gsec(
    coupon_rate: Decimal,
    maturity: date,
    *,
    issue_date: date | None = None,
    end_of_month: bool = False,
    shut_days: int = 1,
    kind: BondKind = BondKind.GSEC,
) -> Bond:
    """Dated G-sec or SDL: semi-annual, 30E/360, 1-day shut period (RBI FAQ; record-date position NOT VERIFIED)."""
    if kind is BondKind.CORPORATE:
        raise InvalidInput("use corporate_bond() for corporate bonds")
    return Bond(kind, coupon_rate, maturity, 2, DayCount.THIRTY_E_360, shut_days, HUNDRED, issue_date, end_of_month)


def corporate_bond(
    coupon_rate: Decimal,
    maturity: date,
    frequency: int,
    *,
    shut_days: int,
    issue_date: date | None = None,
    end_of_month: bool = False,
    redemption: Decimal = HUNDRED,
) -> Bond:
    """Listed corporate bond (SEBI ACT/ACT). ``shut_days`` (record date) must come from the term sheet."""
    return Bond(
        BondKind.CORPORATE,
        coupon_rate,
        maturity,
        frequency,
        DayCount.ACT_ACT_SEBI,
        shut_days,
        redemption,
        issue_date,
        end_of_month,
    )


def _coupon_date(bond: Bond, j: int) -> date:
    """The j-th scheduled date counting back from maturity (j = 0 is maturity)."""
    d = add_months(bond.maturity, -j * (12 // bond.frequency))
    if bond.end_of_month:
        d = date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
    return d


def _year_denominator(bond: Bond, end_index: int) -> int:
    """SEBI ACT/ACT: 366 for every period in a one-year window (anchored on maturity) containing 29-Feb."""
    y = end_index // bond.frequency
    start = _coupon_date(bond, (y + 1) * bond.frequency)
    end = _coupon_date(bond, y * bond.frequency)
    return 366 if contains_feb29(start, end) else 365


@dataclass(frozen=True)
class CouponPeriod:
    start: date
    end: date  # coupon payment date (scheduled; a holiday pays next business day without extra interest)
    amount: Decimal  # per ₹100 face
    accrual_days: int  # 360/f for 30E/360; actual days for ACT/ACT-SEBI
    actual_days: int
    denominator: int  # 360, 365 or 366


def _period(bond: Bond, end_index: int) -> CouponPeriod:
    start, end = _coupon_date(bond, end_index + 1), _coupon_date(bond, end_index)
    actual = days_between(start, end)
    with engine_context():
        if bond.day_count is DayCount.THIRTY_E_360:
            nominal = 360 // bond.frequency
            amount = HUNDRED * bond.coupon_rate / bond.frequency
            return CouponPeriod(start, end, amount, nominal, actual, 360)
        denom = _year_denominator(bond, end_index)
        amount = HUNDRED * bond.coupon_rate * Decimal(actual) / Decimal(denom)
        return CouponPeriod(start, end, amount, actual, actual, denom)


@dataclass(frozen=True)
class CouponSchedule:
    periods: tuple[CouponPeriod, ...]
    total_coupons: Decimal  # per ₹100
    redemption: Decimal
    day_count: DayCount
    compounding: Compounding
    formula_id: str
    conventions: tuple[str, ...]


def coupon_schedule(bond: Bond, from_date: date | None = None) -> CouponSchedule:
    """All regular coupon periods ending after ``from_date`` (default: the issue date)."""
    start = from_date if from_date is not None else bond.issue_date
    if start is None:
        raise InvalidInput("coupon_schedule needs an issue_date on the bond or an explicit from_date")
    if start >= bond.maturity:
        raise InvalidInput("from_date must precede maturity")
    periods: list[CouponPeriod] = []
    j = 0
    while _coupon_date(bond, j) > start:
        periods.append(_period(bond, j))
        j += 1
    periods.reverse()
    with engine_context():
        total = sum((p.amount for p in periods), ZERO)
    return CouponSchedule(
        periods=tuple(periods),
        total_coupons=total,
        redemption=bond.redemption,
        day_count=bond.day_count,
        compounding=bond.compounding,
        formula_id="COUPON_SCHEDULE@1",
        conventions=_bond_conventions(bond),
    )


def _bond_conventions(bond: Bond) -> tuple[str, ...]:
    base = [
        f"day_count={bond.day_count}",
        f"frequency={bond.frequency}",
        "schedule generated backwards from maturity (EDATE); unadjusted dates",
        f"shut_days={bond.shut_days} (record-date position NOT VERIFIED; no ex-interest accrual)",
    ]
    if bond.day_count is DayCount.THIRTY_E_360:
        base.append("price formula: RBI/Excel PRICE basis 4, E = 360/f, DSC = E − A")
    else:
        base.append("SEBI ACT/ACT: 366 for a one-year window containing 29-Feb; window anchored on maturity")
    return tuple(base)


@dataclass(frozen=True)
class CashFlow:
    pay_date: date
    amount: Decimal  # per ₹100 face
    kind: str  # "coupon" | "redemption"
    index: int  # k − 1 (whole periods after the next coupon date)
    periods: Decimal  # n_k = k − 1 + w
    years: Decimal  # n_k / f


@dataclass(frozen=True)
class _Position:
    settlement: date
    previous_coupon: date
    next_coupon: date
    accrued_days: int  # A
    period_days: int  # E
    days_to_next: int  # DSC
    w: Decimal
    accrued: Decimal  # per ₹100, unrounded
    flows: tuple[CashFlow, ...]
    remaining_coupons: int
    redemption_date: date


def _position(bond: Bond, settlement: date, call: tuple[date, Decimal] | None = None) -> _Position:
    if settlement >= bond.maturity:
        raise InvalidInput("settlement on/after maturity; use maturity_proceeds()")
    if bond.issue_date is not None and settlement < bond.issue_date:
        raise InvalidInput("settlement before issue date")
    j = 1
    while _coupon_date(bond, j) > settlement:
        j += 1
    prev, nxt = _coupon_date(bond, j), _coupon_date(bond, j - 1)
    if bond.shut_days and days_between(settlement, nxt) <= bond.shut_days:
        raise InvalidInput(f"settlement {settlement} falls in the {bond.shut_days}-day shut period before {nxt}")

    last_index = 0
    redemption = bond.redemption
    if call is not None:
        call_date, call_price = call
        if call_price <= 0:
            raise InvalidInput("call price must be positive")
        if call_date <= settlement:
            raise InvalidInput("call date must be after settlement")
        last_index = next((c for c in range(j) if _coupon_date(bond, c) == call_date), -1)
        if last_index < 0:
            raise UnsupportedSchedule(f"call date {call_date} is not a coupon date of the bond")
        redemption = call_price

    current = _period(bond, j - 1)
    with engine_context():
        if bond.day_count is DayCount.THIRTY_E_360:
            e = 360 // bond.frequency
            a = days_30e_360(prev, settlement)
            dsc = e - a
            if dsc <= 0:
                raise UnsupportedSchedule(
                    f"30E/360 accrual {a} ≥ nominal period {e} (February month-end period); "
                    "the spec's PRICE formula is undefined here — FIMMDA convention needed"
                )
        else:
            e = current.actual_days
            a = days_between(prev, settlement)
            dsc = e - a
        w = Decimal(dsc) / Decimal(e)
        accrued = current.amount * Decimal(a) / Decimal(e)
        flows: list[CashFlow] = []
        f = Decimal(bond.frequency)
        for k, end_index in enumerate(range(j - 1, last_index - 1, -1)):
            n = Decimal(k) + w
            period = _period(bond, end_index)
            if period.amount != 0:
                flows.append(CashFlow(period.end, period.amount, "coupon", k, n, n / f))
            if end_index == last_index:
                flows.append(CashFlow(period.end, redemption, "redemption", k, n, n / f))
    return _Position(
        settlement=settlement,
        previous_coupon=prev,
        next_coupon=nxt,
        accrued_days=a,
        period_days=e,
        days_to_next=dsc,
        w=w,
        accrued=accrued,
        flows=tuple(flows),
        remaining_coupons=j - last_index,
        redemption_date=_coupon_date(bond, last_index),
    )


def _periodic(bond: Bond, ytm: Yield) -> tuple[Decimal, list[str]]:
    if ytm.compounding is Compounding.SIMPLE:
        raise InvalidInput("a simple money-market yield cannot price a coupon bond")
    warnings: list[str] = []
    y = ytm
    if ytm.compounding is not bond.compounding:
        y = ytm.to(bond.compounding)
        warnings.append(f"{YIELD_CONVERTED}:{ytm.compounding}->{bond.compounding}")
    with engine_context():
        if ONE + y.value / bond.frequency <= 0:
            raise InvalidInput(f"yield {y.value} ≤ −{bond.frequency} is meaningless for this bond")
    if y.value < 0:
        warnings.append(NEGATIVE_YIELD)
    return y.value, warnings


def _pvs(pos: _Position, y: Decimal, frequency: int) -> list[Decimal]:
    """Present values of ``pos.flows`` at periodic yield y/f (exponents n_k = k − 1 + w)."""
    with engine_context():
        v = ONE / (ONE + y / frequency)
        vw = v**pos.w
        return [cf.amount * vw * v**cf.index for cf in pos.flows]


def _dirty(pos: _Position, y: Decimal, frequency: int) -> Decimal:
    with engine_context():
        return sum(_pvs(pos, y, frequency), ZERO)


def _dirty_derivative(pos: _Position, y: Decimal, frequency: int) -> Decimal:
    with engine_context():
        base = ONE + y / frequency
        return -sum((pv * cf.periods for pv, cf in zip(_pvs(pos, y, frequency), pos.flows, strict=True)), ZERO) / (
            frequency * base
        )


@dataclass(frozen=True)
class AccruedInterestResult:
    accrued: Decimal  # per ₹100, unrounded
    accrued_quoted: Decimal  # 0.0001 HALF_UP (replicates RBI FAQ 1.5943)
    previous_coupon: date
    next_coupon: date
    accrued_days: int
    day_count: DayCount
    formula_id: str
    conventions: tuple[str, ...]


def accrued_30e_360(coupon_rate: Decimal, last_coupon: date, settlement: date) -> Decimal:
    """RBI FAQ primitive: ``AI = 100·C × days30E(last_coupon, settlement) / 360`` per ₹100 (unrounded)."""
    if settlement < last_coupon:
        raise InvalidInput("settlement before last coupon")
    with engine_context():
        return HUNDRED * coupon_rate * Decimal(days_30e_360(last_coupon, settlement)) / Decimal(360)


def accrued_interest(bond: Bond, settlement: date) -> AccruedInterestResult:
    pos = _position(bond, settlement)
    return AccruedInterestResult(
        accrued=pos.accrued,
        accrued_quoted=quantize(pos.accrued, ACCRUED_QUOTE_QUANTUM, ROUND_HALF_UP),
        previous_coupon=pos.previous_coupon,
        next_coupon=pos.next_coupon,
        accrued_days=pos.accrued_days,
        day_count=bond.day_count,
        formula_id="ACCRUED@1",
        conventions=(*_bond_conventions(bond), "accrued from last coupon up to the day before settlement"),
    )


@dataclass(frozen=True)
class ConsiderationResult:
    clean_price: Decimal
    accrued_quoted: Decimal
    dirty_price: Decimal  # clean + quoted accrued (replication)
    face_amount: Decimal
    consideration: Decimal  # paise, HALF_UP
    rounding_mode: str
    formula_id: str


def settlement_consideration(
    bond: Bond, settlement: date, clean_price: Decimal, face_amount: Decimal
) -> ConsiderationResult:
    """Replication (rule R4): consideration = face × (clean + AI quoted to 4 dp) / 100, to paise."""
    if face_amount <= 0 or clean_price <= 0:
        raise InvalidInput("face_amount and clean_price must be positive")
    ai = accrued_interest(bond, settlement).accrued_quoted
    with engine_context():
        dirty = clean_price + ai
        consideration = money(face_amount * dirty / HUNDRED)
    return ConsiderationResult(
        clean_price,
        ai,
        dirty,
        face_amount,
        consideration,
        "AI 0.0001 HALF_UP; consideration paise HALF_UP",
        "CONSIDERATION@1",
    )


@dataclass(frozen=True)
class CashFlowSchedule:
    settlement: date
    flows: tuple[CashFlow, ...]
    total_coupons: Decimal
    redemption: Decimal
    total: Decimal
    formula_id: str


def bond_cashflows(bond: Bond, settlement: date) -> CashFlowSchedule:
    """Remaining flows a buyer settling on ``settlement`` receives (a coupon on the settlement date is the seller's)."""
    pos = _position(bond, settlement)
    with engine_context():
        coupons = sum((cf.amount for cf in pos.flows if cf.kind == "coupon"), ZERO)
        redemption = sum((cf.amount for cf in pos.flows if cf.kind == "redemption"), ZERO)
        total = coupons + redemption
    return CashFlowSchedule(settlement, pos.flows, coupons, redemption, total, "BOND_CASHFLOWS@1")


@dataclass(frozen=True)
class BondPriceResult:
    clean: Decimal
    dirty: Decimal
    accrued: Decimal
    ytm: Yield  # in the bond's coupon compounding (bond-equivalent)
    effective_annual_yield: Decimal
    settlement: date
    previous_coupon: date
    next_coupon: date
    accrued_days: int  # A
    period_days: int  # E
    days_to_next: int  # DSC
    remaining_coupons: int
    redemption_date: date
    cashflows: tuple[CashFlow, ...]
    day_count: DayCount
    formula_id: str
    conventions: tuple[str, ...]
    warnings: tuple[str, ...]


def _price_result(bond: Bond, pos: _Position, y: Decimal, warnings: list[str], formula: str) -> BondPriceResult:
    dirty = _dirty(pos, y, bond.frequency)
    ytm = Yield(y, bond.compounding)
    with engine_context():
        clean = dirty - pos.accrued
    return BondPriceResult(
        clean=clean,
        dirty=dirty,
        accrued=pos.accrued,
        ytm=ytm,
        effective_annual_yield=ytm.effective_annual(),
        settlement=pos.settlement,
        previous_coupon=pos.previous_coupon,
        next_coupon=pos.next_coupon,
        accrued_days=pos.accrued_days,
        period_days=pos.period_days,
        days_to_next=pos.days_to_next,
        remaining_coupons=pos.remaining_coupons,
        redemption_date=pos.redemption_date,
        cashflows=pos.flows,
        day_count=bond.day_count,
        formula_id=formula,
        conventions=_bond_conventions(bond),
        warnings=tuple([*warnings, YTM_ASSUMES_REINVESTMENT]),
    )


def price_from_yield(bond: Bond, settlement: date, ytm: Yield) -> BondPriceResult:
    """Clean/dirty price per ₹100 from a yield (converted to the coupon compounding if tagged otherwise)."""
    y, warnings = _periodic(bond, ytm)
    return _price_result(bond, _position(bond, settlement), y, warnings, "BOND_PRICE@1")


@dataclass(frozen=True)
class YieldResult:
    ytm: Yield
    effective_annual_yield: Decimal
    clean_price: Decimal
    dirty_price: Decimal
    accrued: Decimal
    residual: Decimal  # |clean(y) − clean_price| in Decimal, ≤ YTM_PRICE_TOLERANCE
    redemption_date: date
    redemption_price: Decimal
    formula_id: str
    conventions: tuple[str, ...]
    warnings: tuple[str, ...]


def _solve(bond: Bond, pos: _Position, clean_price: Decimal) -> tuple[Decimal, Decimal]:
    """Brent on the float price function within YTM_BRACKET, then Decimal Newton polish + verification."""
    if clean_price <= 0:
        raise InvalidInput("clean price must be positive")
    f = bond.frequency
    amounts = [float(cf.amount) for cf in pos.flows]
    periods = [float(cf.periods) for cf in pos.flows]
    target = float(clean_price + pos.accrued)

    def g(y: float) -> float:
        base = 1.0 + y / f
        return float(sum(a * base**-n for a, n in zip(amounts, periods, strict=True))) - target

    lo, hi = YTM_BRACKET
    if g(lo) * g(hi) > 0:
        raise NumericalError(f"price {clean_price} has no yield in [{lo:.0%}, {hi:.0%}]")
    y = from_float(float(brentq(g, lo, hi, xtol=1e-15, maxiter=200)))
    target_dirty = clean_price + pos.accrued
    with engine_context():
        for _ in range(5):
            diff = _dirty(pos, y, f) - target_dirty
            if abs(diff) <= YTM_PRICE_TOLERANCE / 1000:
                break
            y = y - diff / _dirty_derivative(pos, y, f)
        residual = abs(_dirty(pos, y, f) - target_dirty)
    if residual > YTM_PRICE_TOLERANCE:
        raise NumericalError(f"YTM failed Decimal verification: residual {residual} per ₹100")
    return y, residual


def _yield_result(
    bond: Bond, pos: _Position, clean_price: Decimal, formula: str, extra: tuple[str, ...] = ()
) -> YieldResult:
    y, residual = _solve(bond, pos, clean_price)
    ytm = Yield(y, bond.compounding)
    warnings = [YTM_ASSUMES_REINVESTMENT, *extra]
    if y < 0:
        warnings.insert(0, NEGATIVE_YIELD)
    with engine_context():
        dirty = clean_price + pos.accrued
    redemption = next(cf.amount for cf in pos.flows if cf.kind == "redemption")
    return YieldResult(
        ytm=ytm,
        effective_annual_yield=ytm.effective_annual(),
        clean_price=clean_price,
        dirty_price=dirty,
        accrued=pos.accrued,
        residual=residual,
        redemption_date=pos.redemption_date,
        redemption_price=redemption,
        formula_id=formula,
        conventions=(*_bond_conventions(bond), f"yield compounding={bond.compounding} (bond-equivalent)"),
        warnings=tuple(warnings),
    )


def yield_from_price(bond: Bond, settlement: date, clean_price: Decimal) -> YieldResult:
    return _yield_result(bond, _position(bond, settlement), clean_price, "BOND_YTM@1")


def yield_to_call(
    bond: Bond, settlement: date, clean_price: Decimal, call_date: date, call_price: Decimal
) -> YieldResult:
    """YTC: the price equation with the call date as maturity and the call price as redemption (§4.6)."""
    return _yield_result(bond, _position(bond, settlement, (call_date, call_price)), clean_price, "YTC@1")


@dataclass(frozen=True)
class CallOption:
    call_date: date
    call_price: Decimal  # per ₹100


@dataclass(frozen=True)
class YieldToWorstResult:
    ytm: YieldResult
    ytc: tuple[YieldResult, ...]
    yield_to_worst: Yield
    worst_date: date
    headline: str  # "YTW" for callable bonds
    formula_id: str
    warnings: tuple[str, ...]


def yield_to_worst(
    bond: Bond, settlement: date, clean_price: Decimal, calls: Sequence[CallOption]
) -> YieldToWorstResult:
    """YTW = min(YTM, YTC over every call date after settlement). The headline for callable bonds."""
    ytm = yield_from_price(bond, settlement, clean_price)
    ytcs = tuple(
        yield_to_call(bond, settlement, clean_price, c.call_date, c.call_price)
        for c in sorted(calls, key=lambda c: c.call_date)
        if c.call_date > settlement
    )
    worst = min((ytm, *ytcs), key=lambda r: r.ytm.value)
    warnings = [CALL_LOWERS_YIELD] if worst is not ytm else []
    return YieldToWorstResult(
        ytm=ytm,
        ytc=ytcs,
        yield_to_worst=worst.ytm,
        worst_date=worst.redemption_date,
        headline="YTW" if ytcs else "YTM",
        formula_id="YTW@1",
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class BondRiskResult:
    macaulay_duration: Decimal  # years
    modified_duration: Decimal  # years
    convexity: Decimal  # years²
    dv01: Decimal  # per ₹100 face, for 1 bp
    dirty_price: Decimal
    ytm: Yield
    formula_id: str
    conventions: tuple[str, ...]
    warnings: tuple[str, ...]


def bond_risk(bond: Bond, settlement: date, ytm: Yield) -> BondRiskResult:
    """Macaulay/modified duration and convexity per spec §4.4 (dirty-price based)."""
    y, warnings = _periodic(bond, ytm)
    pos = _position(bond, settlement)
    pvs = _pvs(pos, y, bond.frequency)
    f = bond.frequency
    with engine_context():
        dirty = sum(pvs, ZERO)
        base = ONE + y / f
        mac = sum((cf.years * pv for cf, pv in zip(pos.flows, pvs, strict=True)), ZERO) / dirty
        mod = mac / base
        conv = sum((pv * cf.periods * (cf.periods + 1) for cf, pv in zip(pos.flows, pvs, strict=True)), ZERO) / (
            Decimal(f * f) * base * base * dirty
        )
        dv01 = mod * dirty * BASIS_POINT
    return BondRiskResult(
        mac, mod, conv, dv01, dirty, Yield(y, bond.compounding), "BOND_RISK@1", _bond_conventions(bond), tuple(warnings)
    )


@dataclass(frozen=True)
class PriceChangeResult:
    shock: Decimal  # Δy (fraction)
    dirty_before: Decimal
    dirty_after: Decimal
    exact_change: Decimal  # ΔP/P by full repricing — the headline
    duration_only: Decimal  # −D_mod Δy
    duration_convexity: Decimal  # −D_mod Δy + ½ Conv Δy²
    approximation_error: Decimal  # duration_convexity − exact
    headline_method: str  # always "FULL_REPRICE"
    formula_id: str
    warnings: tuple[str, ...]


def price_change(bond: Bond, settlement: date, ytm: Yield, shock: Decimal) -> PriceChangeResult:
    """ΔP/P: full repricing (headline) vs the duration and duration+convexity approximations (explanation)."""
    risk = bond_risk(bond, settlement, ytm)
    y = risk.ytm.value
    after = price_from_yield(bond, settlement, Yield(y + shock, bond.compounding))
    warnings = list(risk.warnings)
    if abs(shock) > FULL_REPRICE_THRESHOLD:
        warnings.append(LARGE_SHOCK)
    with engine_context():
        exact = after.dirty / risk.dirty_price - ONE
        d_only = -risk.modified_duration * shock
        d_conv = d_only + risk.convexity * shock * shock / 2
    return PriceChangeResult(
        shock=shock,
        dirty_before=risk.dirty_price,
        dirty_after=after.dirty,
        exact_change=exact,
        duration_only=d_only,
        duration_convexity=d_conv,
        approximation_error=d_conv - exact,
        headline_method="FULL_REPRICE",
        formula_id="PRICE_CHANGE@1",
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class SpreadSensitivityResult:
    benchmark_yield: Yield
    spread: Decimal
    bond_yield: Yield  # benchmark + spread (additive, same compounding)
    spread_duration: Decimal  # = modified duration for a fixed-rate bullet
    price_before: Decimal  # dirty
    price_after: Decimal  # dirty, fully repriced at benchmark + spread + rate_shock + spread_shock
    exact_change: Decimal
    approximate_change: Decimal  # −D_spread × (Δs + Δr)
    formula_id: str
    warnings: tuple[str, ...]


def spread_sensitivity(
    bond: Bond,
    settlement: date,
    benchmark_yield: Yield,
    spread: Decimal,
    spread_shock: Decimal,
    *,
    rate_shock: Decimal = ZERO,
) -> SpreadSensitivityResult:
    """§4.7: y = y_gsec(T) + s. Rate and spread shocks combine additively in Δy and are fully repriced."""
    with engine_context():
        y0 = Yield(benchmark_yield.value + spread, benchmark_yield.compounding)
    risk = bond_risk(bond, settlement, y0)
    with engine_context():
        y1 = Yield(risk.ytm.value + spread_shock + rate_shock, bond.compounding)
    after = price_from_yield(bond, settlement, y1)
    warnings = [*risk.warnings, SPREAD_DURATION_APPROX, CREDIT_RISK]
    with engine_context():
        exact = after.dirty / risk.dirty_price - ONE
        approx = -risk.modified_duration * (spread_shock + rate_shock)
    return SpreadSensitivityResult(
        benchmark_yield=benchmark_yield,
        spread=spread,
        bond_yield=y0,
        spread_duration=risk.modified_duration,
        price_before=risk.dirty_price,
        price_after=after.dirty,
        exact_change=exact,
        approximate_change=approx,
        formula_id="SPREAD_DURATION@1",
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class MaturityProceedsResult:
    face_amount: Decimal
    principal: Decimal  # face × redemption / 100
    final_coupon: Decimal  # face × last coupon / 100
    total: Decimal
    total_display: Decimal  # paise HALF_UP
    maturity: date
    formula_id: str
    warnings: tuple[str, ...]


def maturity_proceeds(bond: Bond, face_amount: Decimal) -> MaturityProceedsResult:
    """Hold to maturity: face + final coupon. Known amounts; only credit risk is uncertain (corporates)."""
    if face_amount <= 0:
        raise InvalidInput("face_amount must be positive")
    last = _period(bond, 0)
    with engine_context():
        principal = face_amount * bond.redemption / HUNDRED
        coupon = face_amount * last.amount / HUNDRED
        total = principal + coupon
    warnings = (CREDIT_RISK,) if bond.kind is BondKind.CORPORATE else ()
    return MaturityProceedsResult(
        face_amount, principal, coupon, total, money(total), bond.maturity, "MATURITY_PROCEEDS@1", warnings
    )


@dataclass(frozen=True)
class ExitScenario:
    shock: Decimal
    exit_yield: Yield  # entry yield + shock + exit spread
    exit_clean: Decimal
    exit_dirty: Decimal
    coupons_received: Decimal  # per ₹100, including reinvestment growth if any
    holding_period_return: Decimal  # (P_H dirty + coupons − P_0 dirty) / P_0 dirty


@dataclass(frozen=True)
class EarlyExitResult:
    entry_dirty: Decimal
    entry_yield: Yield
    entry_settlement: date
    exit_settlement: date
    exit_spread: Decimal  # yield add-on (fraction)
    reinvestment_rate: Yield | None
    scenarios: tuple[ExitScenario, ...]
    formula_id: str
    conventions: tuple[str, ...]
    warnings: tuple[str, ...]


_DEFAULT_EXIT_SPREAD_BP = {BondKind.GSEC: 25, BondKind.SDL: 25, BondKind.CORPORATE: 100}


def early_exit_scenarios(
    bond: Bond,
    entry_settlement: date,
    entry_yield: Yield,
    exit_settlement: date,
    *,
    shocks_bp: Sequence[int] = DEFAULT_EXIT_SHOCKS_BP,
    exit_spread_bp: int | None = None,
    reinvestment_rate: Yield | None = None,
) -> EarlyExitResult:
    """§4.9: reprice the residual bond at exit on a yield grid; HPR from dirty prices plus coupons received.

    ``exit_spread_bp`` is applied as a **yield** add-on at exit (the spec's unit is ambiguous; NOT VERIFIED).
    Default 25 bp for G-sec/SDL and 100 bp for corporates (spec defaults).  Reinvestment of received coupons
    compounds at ``reinvestment_rate`` over Actual/365 years to the exit date.
    """
    if exit_settlement <= entry_settlement:
        raise InvalidInput("exit must be after entry")
    if exit_settlement >= bond.maturity:
        raise InvalidInput("exit on/after maturity; use maturity_proceeds()")
    entry = price_from_yield(bond, entry_settlement, entry_yield)
    warnings = [w for w in entry.warnings if w != YTM_ASSUMES_REINVESTMENT]
    spread_bp = _DEFAULT_EXIT_SPREAD_BP[bond.kind] if exit_spread_bp is None else exit_spread_bp
    if spread_bp < 0:
        raise InvalidInput("exit_spread_bp must be ≥ 0")
    if spread_bp:
        warnings.append(EXIT_SPREAD_ASSUMED)
    received = [cf for cf in entry.cashflows if cf.kind == "coupon" and cf.pay_date <= exit_settlement]
    with engine_context():
        coupons = ZERO
        for cf in received:
            growth = ONE
            if reinvestment_rate is not None:
                m = reinvestment_rate.periods_per_year
                t = Decimal(days_between(cf.pay_date, exit_settlement)) / Decimal(365)
                growth = (ONE + reinvestment_rate.value / m) ** (m * t)
            coupons += cf.amount * growth
        spread = Decimal(spread_bp) * BASIS_POINT
    scenarios: list[ExitScenario] = []
    for bp in shocks_bp:
        with engine_context():
            shock = Decimal(bp) * BASIS_POINT
            y_exit = Yield(entry.ytm.value + shock + spread, bond.compounding)
        exit_price = price_from_yield(bond, exit_settlement, y_exit)
        with engine_context():
            hpr = (exit_price.dirty + coupons - entry.dirty) / entry.dirty
        scenarios.append(ExitScenario(shock, y_exit, exit_price.clean, exit_price.dirty, coupons, hpr))
    return EarlyExitResult(
        entry_dirty=entry.dirty,
        entry_yield=entry.ytm,
        entry_settlement=entry_settlement,
        exit_settlement=exit_settlement,
        exit_spread=spread,
        reinvestment_rate=reinvestment_rate,
        scenarios=tuple(scenarios),
        formula_id="EARLY_EXIT@1",
        conventions=(
            *_bond_conventions(bond),
            "exit yield = entry yield + shock + exit spread; full repricing",
            "HPR is not annualised",
        ),
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class RealisedReturnResult:
    purchase_dirty: Decimal
    ytm: Yield
    reinvestment_rate: Yield  # converted to the coupon compounding
    future_value: Decimal  # per ₹100 at maturity
    years: Decimal  # (N − 1 + w) / f
    realised_effective_annual: Decimal
    realised_bond_equivalent: Yield
    formula_id: str
    conventions: tuple[str, ...]
    warnings: tuple[str, ...]


def realised_return(bond: Bond, settlement: date, ytm: Yield, reinvestment_rate: Yield) -> RealisedReturnResult:
    """§4.8: FV = Σ coupon_k (1 + r/f)^(N − k) + redemption; realised return from the dirty purchase price."""
    price = price_from_yield(bond, settlement, ytm)
    r, warnings = _periodic(bond, reinvestment_rate)
    f = bond.frequency
    with engine_context():
        last = max(price.cashflows, key=lambda cf: cf.index)
        fv = sum((cf.amount * (ONE + r / f) ** (last.index - cf.index) for cf in price.cashflows), ZERO)
        years = last.periods / f
        growth = fv / price.dirty
        ear = growth ** (ONE / years) - ONE
        bey = f * (growth ** (ONE / (years * f)) - ONE)
    return RealisedReturnResult(
        purchase_dirty=price.dirty,
        ytm=price.ytm,
        reinvestment_rate=Yield(r, bond.compounding),
        future_value=fv,
        years=years,
        realised_effective_annual=ear,
        realised_bond_equivalent=Yield(bey, bond.compounding),
        formula_id="REALISED_RETURN@1",
        conventions=(*_bond_conventions(bond), "coupons reinvested to maturity at the given rate; held to maturity"),
        warnings=tuple(w for w in (*price.warnings, *warnings) if w != YTM_ASSUMES_REINVESTMENT),
    )
