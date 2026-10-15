"""Bank / NBFC / HFC fixed deposits and DICGC coverage (calculation-methodology.md §3; research §5).

* Cumulative deposits compound quarterly: complete quarters (EDATE steps from the deposit date — anchor NOT
  VERIFIED), then simple interest on the compounded balance for the broken period, Actual/365.
* Below ``short_tenure_cutoff_months`` (per bank; default 6) the deposit earns simple interest at maturity.
* ``leap_denominator`` = 365 (IBA text) or 366 (some banks; NOT VERIFIED).  Under 366, days falling in a leap
  calendar year are divided by 366 and other days by 365 (the split across years is NOT VERIFIED).
* The maturity amount is quantized to paise HALF_UP once, at maturity (replication, rule R4).
* Premature-withdrawal penalties are bank-board policy: the caller must supply the penalty — there is no default.
* DICGC: ₹5,00,000 per depositor per bank per capacity, principal + interest combined, from 4-Feb-2020.
  NBFC/HFC deposits are never insured.  Bank dues set-off is not modelled (the insured figure is an upper bound).
"""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise

from iip.engine.dates import add_months, days_between
from iip.engine.errors import InvalidInput, MissingData, RuleNotFound
from iip.engine.money import ONE, ZERO, engine_context, money

DEFAULT_SHORT_TENURE_CUTOFF_MONTHS = 6
DEFAULT_MIN_TENURE_DAYS = 7
QUARTER_MONTHS = 3
DICGC_LIMIT = Decimal(500000)
DICGC_LIMIT_EFFECTIVE = date(2020, 2, 4)

LEAP_SPLIT = "LEAP_DENOMINATOR_SPLIT_ACROSS_YEARS_NOT_VERIFIED"
QUARTER_ANCHOR = "QUARTER_ANCHOR_DEPOSIT_DATE_NOT_VERIFIED"
NO_INTEREST_BEFORE_MIN_TENURE = "NO_INTEREST_BEFORE_MIN_TENURE"
RATE_FLOORED_AT_ZERO = "EFFECTIVE_RATE_FLOORED_AT_ZERO"
NOT_INSURED = "NOT_DICGC_INSURED"
SET_OFF_NOT_MODELLED = "BANK_DUES_SET_OFF_NOT_MODELLED"
ABOVE_LIMIT = "EXCEEDS_DICGC_LIMIT"


class FDMethod(StrEnum):
    QUARTERLY_COMPOUND = "quarterly_compound+broken_period_simple"
    SIMPLE = "simple"


def _complete_months(start: date, end: date) -> int:
    m = (end.year - start.year) * 12 + (end.month - start.month)
    while m > 0 and add_months(start, m) > end:
        m -= 1
    return m


def _simple_year_fraction(start: date, end: date, leap_denominator: int) -> tuple[Decimal, bool]:
    """Days/365, or (leap_denominator=366) days in leap years /366 + other days /365. Returns (fraction, split)."""
    with engine_context():
        if leap_denominator == 365:
            return Decimal(days_between(start, end)) / Decimal(365), False
        total = ZERO
        kinds: set[bool] = set()
        cur = start
        while cur < end:
            nxt = min(end, date(cur.year + 1, 1, 1))
            leap = calendar.isleap(cur.year)
            kinds.add(leap)
            total += Decimal(days_between(cur, nxt)) / Decimal(366 if leap else 365)
            cur = nxt
        return total, len(kinds) > 1


@dataclass(frozen=True)
class FDMaturityResult:
    principal: Decimal
    rate: Decimal  # nominal annual, fraction
    start: date
    maturity: date
    days: int
    complete_months: int
    complete_quarters: int
    broken_days: int
    method: FDMethod
    maturity_amount: Decimal  # unrounded
    maturity_amount_display: Decimal  # paise, HALF_UP (bank replication)
    interest: Decimal  # unrounded
    effective_annual_yield: Decimal  # (1 + r/4)^4 − 1, comparison only
    short_tenure_cutoff_months: int
    leap_denominator: int
    formula_id: str
    conventions: tuple[str, ...]
    warnings: tuple[str, ...]


def _validate_common(principal: Decimal, rate: Decimal, leap_denominator: int, cutoff: int) -> None:
    if principal <= 0:
        raise InvalidInput("principal must be positive")
    if rate < 0:
        raise InvalidInput("FD rate must be ≥ 0")
    if leap_denominator not in (365, 366):
        raise InvalidInput("leap_denominator must be 365 or 366")
    if cutoff < 0:
        raise InvalidInput("short_tenure_cutoff_months must be ≥ 0")


def fd_effective_annual_yield(rate: Decimal) -> Decimal:
    """``EAY = (1 + r/4)^4 − 1``."""
    if rate < 0:
        raise InvalidInput("FD rate must be ≥ 0")
    with engine_context():
        return (ONE + rate / 4) ** 4 - ONE


def fd_maturity(
    principal: Decimal,
    rate: Decimal,
    start: date,
    maturity: date,
    *,
    short_tenure_cutoff_months: int = DEFAULT_SHORT_TENURE_CUTOFF_MONTHS,
    leap_denominator: int = 365,
    min_tenure_days: int = DEFAULT_MIN_TENURE_DAYS,
) -> FDMaturityResult:
    """Cumulative (reinvestment) FD maturity value, §3.2."""
    _validate_common(principal, rate, leap_denominator, short_tenure_cutoff_months)
    days = days_between(start, maturity)
    if days < min_tenure_days:
        raise InvalidInput(f"tenure {days} days is below the minimum {min_tenure_days} days")
    months = _complete_months(start, maturity)
    warnings: list[str] = []
    with engine_context():
        if months >= short_tenure_cutoff_months:
            q = months // QUARTER_MONTHS
            anchor = add_months(start, q * QUARTER_MONTHS)
            broken = days_between(anchor, maturity)
            frac, split = _simple_year_fraction(anchor, maturity, leap_denominator)
            amount = principal * (ONE + rate / 4) ** q * (ONE + rate * frac)
            method = FDMethod.QUARTERLY_COMPOUND
            warnings.append(QUARTER_ANCHOR)
        else:
            q, broken = 0, days
            frac, split = _simple_year_fraction(start, maturity, leap_denominator)
            amount = principal * (ONE + rate * frac)
            method = FDMethod.SIMPLE
        interest = amount - principal
    if split:
        warnings.append(LEAP_SPLIT)
    return FDMaturityResult(
        principal=principal,
        rate=rate,
        start=start,
        maturity=maturity,
        days=days,
        complete_months=months,
        complete_quarters=q,
        broken_days=broken,
        method=method,
        maturity_amount=amount,
        maturity_amount_display=money(amount),
        interest=interest,
        effective_annual_yield=fd_effective_annual_yield(rate),
        short_tenure_cutoff_months=short_tenure_cutoff_months,
        leap_denominator=leap_denominator,
        formula_id="FD_MATURITY@1",
        conventions=(
            "quarterly compounding A = P(1 + r/4)^q × (1 + r·b/denominator)",
            f"simple interest below {short_tenure_cutoff_months} complete months",
            f"broken-period denominator {leap_denominator}",
            "quarters are EDATE steps from the deposit date; interim quarters not rounded",
        ),
        warnings=tuple(warnings),
    )


class PrematureRateBasis(StrEnum):
    PERIOD_CARD = "period_card"
    MIN_BOOKED_PERIOD_CARD = "min(booked,period_card)"


@dataclass(frozen=True)
class PrematureWithdrawalResult:
    booked_rate: Decimal
    period_card_rate: Decimal
    penalty: Decimal
    rate_basis: PrematureRateBasis
    effective_rate: Decimal  # max(0, base − penalty)
    payout: Decimal  # unrounded
    payout_display: Decimal  # paise HALF_UP
    payout_detail: FDMaturityResult | None  # None when no interest is paid (before the minimum tenure)
    at_booked_rate: Decimal  # same run tenure at the booked rate (what the user expects)
    cost_of_breaking: Decimal  # at_booked_rate − payout
    days_run: int
    formula_id: str
    conventions: tuple[str, ...]
    warnings: tuple[str, ...]


def fd_premature_withdrawal(
    principal: Decimal,
    booked_rate: Decimal,
    start: date,
    booked_maturity: date,
    withdrawal_date: date,
    *,
    period_card_rate: Decimal,
    penalty: Decimal,
    rate_basis: PrematureRateBasis = PrematureRateBasis.PERIOD_CARD,
    short_tenure_cutoff_months: int = DEFAULT_SHORT_TENURE_CUTOFF_MONTHS,
    leap_denominator: int = 365,
    min_tenure_days: int = DEFAULT_MIN_TENURE_DAYS,
) -> PrematureWithdrawalResult:
    """§3.3: rate for the tenure actually run (card rate on the booking date) minus the bank's penalty.

    ``penalty`` has no default: it is per-bank board policy (NOT VERIFIED) and must be supplied.
    """
    _validate_common(principal, booked_rate, leap_denominator, short_tenure_cutoff_months)
    if period_card_rate < 0 or penalty < 0:
        raise InvalidInput("period_card_rate and penalty must be ≥ 0")
    if not start < withdrawal_date < booked_maturity:
        raise InvalidInput("withdrawal must fall strictly between the deposit date and the booked maturity")
    days_run = days_between(start, withdrawal_date)
    base = period_card_rate
    if rate_basis is PrematureRateBasis.MIN_BOOKED_PERIOD_CARD:
        base = min(booked_rate, period_card_rate)
    warnings: list[str] = []
    with engine_context():
        r_eff = base - penalty
    if r_eff < 0:
        r_eff = ZERO
        warnings.append(RATE_FLOORED_AT_ZERO)
    kwargs = {
        "short_tenure_cutoff_months": short_tenure_cutoff_months,
        "leap_denominator": leap_denominator,
        "min_tenure_days": min_tenure_days,
    }
    detail: FDMaturityResult | None
    if days_run < min_tenure_days:
        detail, payout, at_booked = None, principal, principal
        warnings.append(NO_INTEREST_BEFORE_MIN_TENURE)
    else:
        detail = fd_maturity(principal, r_eff, start, withdrawal_date, **kwargs)
        payout = detail.maturity_amount
        at_booked = fd_maturity(principal, booked_rate, start, withdrawal_date, **kwargs).maturity_amount
        warnings.extend(detail.warnings)
    with engine_context():
        cost = at_booked - payout
    return PrematureWithdrawalResult(
        booked_rate=booked_rate,
        period_card_rate=period_card_rate,
        penalty=penalty,
        rate_basis=rate_basis,
        effective_rate=r_eff,
        payout=payout,
        payout_display=money(payout),
        payout_detail=detail,
        at_booked_rate=at_booked,
        cost_of_breaking=cost,
        days_run=days_run,
        formula_id="FD_PREMATURE@1",
        conventions=(
            f"r_eff = max(0, {rate_basis} − penalty)",
            "penalty supplied by caller (bank board policy, NOT VERIFIED)",
        ),
        warnings=tuple(dict.fromkeys(warnings)),
    )


@dataclass(frozen=True)
class CardRateBucket:
    """One row of a bank's published card-rate table: deposits of ``min_days``–``max_days`` earn ``rate``."""

    min_days: int
    max_days: int
    rate: Decimal


def validate_card_rate_table(buckets: Sequence[CardRateBucket]) -> tuple[CardRateBucket, ...]:
    """Sorted, non-overlapping tenure buckets with non-negative finite rates (a malformed table is refused)."""
    if not buckets:
        raise InvalidInput("a card-rate table needs at least one tenure bucket")
    ordered = tuple(sorted(buckets, key=lambda b: b.min_days))
    for b in ordered:
        if b.min_days < 1 or b.max_days < b.min_days:
            raise InvalidInput(f"invalid tenure bucket {b.min_days}–{b.max_days} days")
        if not isinstance(b.rate, Decimal) or not b.rate.is_finite() or b.rate < 0:
            raise InvalidInput(f"invalid card rate {b.rate!r}")
    for a, b in pairwise(ordered):
        if b.min_days <= a.max_days:
            raise InvalidInput(f"tenure buckets overlap: {a.min_days}–{a.max_days} and {b.min_days}–{b.max_days} days")
    return ordered


def card_rate_for_tenure(buckets: Sequence[CardRateBucket], days_run: int) -> CardRateBucket:
    """calc §3.3: the card rate for the tenure the deposit actually ran. No bucket covers it → ``MissingData``
    (the rate is never taken from a neighbouring bucket)."""
    for b in validate_card_rate_table(buckets):
        if b.min_days <= days_run <= b.max_days:
            return b
    raise MissingData(f"the card-rate table has no bucket covering a {days_run}-day tenure")


class InstitutionType(StrEnum):
    BANK = "bank"  # commercial banks incl. SFBs, RRBs, foreign bank branches in India
    COOPERATIVE_BANK = "cooperative_bank"
    NBFC = "nbfc"
    HFC = "hfc"


_INSURED_TYPES = frozenset({InstitutionType.BANK, InstitutionType.COOPERATIVE_BANK})


@dataclass(frozen=True)
class DepositHolding:
    institution_id: str
    institution_type: InstitutionType
    depositor_id: str
    principal: Decimal
    accrued_interest: Decimal
    capacity: str = "individual"  # same right and same capacity aggregate together


@dataclass(frozen=True)
class CoverageGroup:
    institution_id: str
    institution_type: InstitutionType
    depositor_id: str
    capacity: str
    principal: Decimal
    interest: Decimal
    total: Decimal
    insured: Decimal
    uninsured: Decimal
    flags: tuple[str, ...]


@dataclass(frozen=True)
class DICGCCoverageResult:
    groups: tuple[CoverageGroup, ...]
    total: Decimal
    insured: Decimal
    uninsured: Decimal
    limit: Decimal
    as_of: date
    formula_id: str
    conventions: tuple[str, ...]
    warnings: tuple[str, ...]


def dicgc_coverage(holdings: Sequence[DepositHolding], *, as_of: date) -> DICGCCoverageResult:
    """Aggregate per (institution, depositor, capacity); insured = min(principal + interest, ₹5,00,000)."""
    if as_of < DICGC_LIMIT_EFFECTIVE:
        raise RuleNotFound(f"DICGC ₹5 lakh limit applies from {DICGC_LIMIT_EFFECTIVE}; no rule loaded for {as_of}")
    types: dict[str, InstitutionType] = {}
    sums: dict[tuple[str, str, str], tuple[Decimal, Decimal]] = {}
    with engine_context():
        for h in holdings:
            if h.principal < 0 or h.accrued_interest < 0:
                raise InvalidInput("principal and accrued interest must be ≥ 0")
            if types.setdefault(h.institution_id, h.institution_type) is not h.institution_type:
                raise InvalidInput(f"institution {h.institution_id!r} given with conflicting types")
            key = (h.institution_id, h.depositor_id, h.capacity)
            p, i = sums.get(key, (ZERO, ZERO))
            sums[key] = (p + h.principal, i + h.accrued_interest)
        groups: list[CoverageGroup] = []
        for (inst, dep, cap), (p, i) in sorted(sums.items()):
            itype = types[inst]
            total = p + i
            flags: list[str] = []
            if itype in _INSURED_TYPES:
                insured = min(total, DICGC_LIMIT)
                if total > DICGC_LIMIT:
                    flags.append(ABOVE_LIMIT)
            else:
                insured = ZERO
                flags.append(NOT_INSURED)
            groups.append(CoverageGroup(inst, itype, dep, cap, p, i, total, insured, total - insured, tuple(flags)))
        total_all = sum((g.total for g in groups), ZERO)
        insured_all = sum((g.insured for g in groups), ZERO)
    return DICGCCoverageResult(
        groups=tuple(groups),
        total=total_all,
        insured=insured_all,
        uninsured=total_all - insured_all,
        limit=DICGC_LIMIT,
        as_of=as_of,
        formula_id="DICGC_COVERAGE@1",
        conventions=(
            "₹5,00,000 per depositor per bank, principal + interest, all branches aggregated (DICGC FAQ)",
            "different capacities insured separately",
            "NBFC/HFC deposits are not insured",
        ),
        warnings=(SET_OFF_NOT_MODELLED,),
    )
