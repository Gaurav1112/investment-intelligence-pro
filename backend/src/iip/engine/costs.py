"""Transaction and holding costs for mutual funds (calculation-methodology.md §2.8–§2.10).

* Stamp duty on unit creation: ``net × r / (1 + r)``, paise HALF_UP (replication, Rule R4).
* Exit load: FIFO lots; ``days_held = redemption − allotment``; load applies if
  ``days_held ≤ window_days`` (boundary convention NOT VERIFIED; scheme-specific).
* Expense ratio (TER / BER): forward models only.  A published NAV is already net of expenses, so
  applying an expense ratio to a NAV-based historical return is a double count and is refused.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from iip.engine.dates import days_between
from iip.engine.errors import InvalidInput, MissingData, RuleNotFound
from iip.engine.money import ONE, ZERO, D, engine_context, money, units_allotment

# ---------------------------------------------------------------- §2.10 stamp duty

STAMP_DUTY_EFFECTIVE_FROM = date(2020, 7, 1)
STAMP_DUTY_MF_PURCHASE_RATE = Decimal("0.00005")  # 0.005 % — VERIFIED (secondary), §2.10


@dataclass(frozen=True, slots=True)
class StampDutyResult:
    gross_amount: Decimal
    transaction_charge: Decimal
    net_amount: Decimal
    rate: Decimal
    stamp_duty_unrounded: Decimal
    stamp_duty: Decimal
    invested: Decimal
    nav: Decimal | None
    units: Decimal | None
    trade_date: date
    formula_id: str = "STAMP_DUTY_MF@1"
    rounding_mode: str = ROUND_HALF_UP
    flags: tuple[str, ...] = ()


def stamp_duty(
    gross_amount: Decimal,
    *,
    trade_date: date,
    transaction_charge: Decimal = ZERO,
    nav: Decimal | None = None,
    rate: Decimal | None = None,
) -> StampDutyResult:
    """Stamp duty on MF unit creation (purchase, SIP, switch-in, IDCW reinvestment).

    ``net = gross − txn_charge``; ``stamp = net × r / (1 + r)`` → paise HALF_UP;
    ``invested = net − stamp``; ``units = invested / NAV`` truncated to 3 dp (NOT VERIFIED, AMC practice).
    ``rate`` overrides the statutory rate (flagged ``RATE_OVERRIDDEN``).
    """
    if trade_date < STAMP_DUTY_EFFECTIVE_FROM:
        raise RuleNotFound(f"no MF stamp-duty rule before {STAMP_DUTY_EFFECTIVE_FROM}; trade on {trade_date}")
    gross = D(gross_amount)
    charge = D(transaction_charge)
    if gross <= 0:
        raise InvalidInput(f"gross_amount must be > 0, got {gross}")
    if charge < 0:
        raise InvalidInput(f"transaction_charge must be ≥ 0, got {charge}")
    r = STAMP_DUTY_MF_PURCHASE_RATE if rate is None else D(rate)
    if not ZERO <= r < ONE:
        raise InvalidInput(f"stamp-duty rate must be in [0, 1), got {r}")
    nav_value: Decimal | None = None
    if nav is not None:
        nav_value = D(nav)
        if nav_value <= 0:
            raise InvalidInput(f"nav must be > 0, got {nav_value}")
    with engine_context():
        net = gross - charge
        if net <= 0:
            raise InvalidInput(f"transaction charge {charge} consumes the whole amount {gross}")
        raw = net * r / (ONE + r)
        duty = money(raw)
        invested = net - duty
        units = None if nav_value is None else units_allotment(invested / nav_value)
    return StampDutyResult(
        gross_amount=gross,
        transaction_charge=charge,
        net_amount=net,
        rate=r,
        stamp_duty_unrounded=raw,
        stamp_duty=duty,
        invested=invested,
        nav=nav_value,
        units=units,
        trade_date=trade_date,
        flags=("RATE_OVERRIDDEN",) if rate is not None else (),
    )


# ---------------------------------------------------------------- §2.9 exit load


@dataclass(frozen=True, slots=True)
class LoadTier:
    """Load ``rate`` applies when ``days_held ≤ window_days`` (smallest matching window wins)."""

    window_days: int
    rate: Decimal


@dataclass(frozen=True, slots=True)
class Lot:
    allotment_date: date
    units: Decimal


@dataclass(frozen=True, slots=True)
class LotConsumption:
    allotment_date: date
    units: Decimal
    days_held: int
    rate: Decimal
    load_unrounded: Decimal


@dataclass(frozen=True, slots=True)
class ExitLoadResult:
    redemption_date: date
    nav: Decimal
    units_redeemed: Decimal
    lots: tuple[LotConsumption, ...]
    remaining: tuple[Lot, ...]
    gross: Decimal
    load_unrounded: Decimal
    load: Decimal
    net: Decimal
    formula_id: str = "EXIT_LOAD@1"
    convention: str = "days_held = redemption_date − allotment_date; load if days_held ≤ window_days"
    rounding_mode: str = ROUND_HALF_UP
    flags: tuple[str, ...] = ("BOUNDARY_CONVENTION_NOT_VERIFIED",)


def _validate_schedule(schedule: Sequence[LoadTier]) -> tuple[LoadTier, ...]:
    tiers = tuple(sorted(schedule, key=lambda t: t.window_days))
    seen: set[int] = set()
    for tier in tiers:
        if tier.window_days < 0:
            raise InvalidInput(f"window_days must be ≥ 0, got {tier.window_days}")
        if tier.window_days in seen:
            raise InvalidInput(f"duplicate load window {tier.window_days} days")
        seen.add(tier.window_days)
        rate = D(tier.rate)
        if not ZERO <= rate < ONE:
            raise InvalidInput(f"load rate must be in [0, 1), got {rate}")
    return tiers


def _load_rate(tiers: Sequence[LoadTier], days_held: int) -> Decimal:
    for tier in tiers:  # ascending windows → smallest matching window wins
        if days_held <= tier.window_days:
            return D(tier.rate)
    return ZERO


def exit_load(
    lots: Sequence[Lot],
    units_redeemed: Decimal,
    redemption_date: date,
    nav: Decimal,
    schedule: Sequence[LoadTier],
) -> ExitLoadResult:
    """Exit load on a redemption, consuming lots FIFO (oldest allotment first).

    Replication rounding: gross and the aggregate load are each quantized to paise (HALF_UP) and
    ``net = gross − load``.  Per-lot loads are kept unrounded.
    """
    units = D(units_redeemed)
    nav_value = D(nav)
    if units <= 0:
        raise InvalidInput(f"units_redeemed must be > 0, got {units}")
    if nav_value <= 0:
        raise InvalidInput(f"nav must be > 0, got {nav_value}")
    tiers = _validate_schedule(schedule)
    for lot in lots:
        if D(lot.units) <= 0:
            raise InvalidInput(f"lot units must be > 0, got {lot.units}")
        if lot.allotment_date > redemption_date:
            raise InvalidInput(f"lot allotted {lot.allotment_date} after redemption {redemption_date}")
    ordered = sorted(lots, key=lambda lot: lot.allotment_date)  # stable: same-date lots keep input order
    consumed: list[LotConsumption] = []
    remaining: list[Lot] = []
    with engine_context():
        if units > sum((D(lot.units) for lot in ordered), ZERO):
            raise InvalidInput(f"redeeming {units} units exceeds holdings")
        left = units
        total_load = ZERO
        for lot in ordered:
            if left == 0:
                remaining.append(lot)
                continue
            take = min(left, D(lot.units))
            held = days_between(lot.allotment_date, redemption_date)
            rate = _load_rate(tiers, held)
            lot_load = rate * take * nav_value
            total_load += lot_load
            consumed.append(LotConsumption(lot.allotment_date, take, held, rate, lot_load))
            if take < lot.units:
                remaining.append(Lot(lot.allotment_date, D(lot.units) - take))
            left -= take
        gross = money(units * nav_value)
        load = money(total_load)
        net = gross - load
    return ExitLoadResult(
        redemption_date=redemption_date,
        nav=nav_value,
        units_redeemed=units,
        lots=tuple(consumed),
        remaining=tuple(remaining),
        gross=gross,
        load_unrounded=total_load,
        load=load,
        net=net,
    )


# ---------------------------------------------------------------- §2.8 TER / BER forward model

BER_EFFECTIVE_FROM = date(2026, 4, 1)  # SEBI (Mutual Funds) Regulations 2026, reg. 66(7) — per Agent B


class ExpenseRatioKind(StrEnum):
    TER = "TER"
    BER = "BER"


class ReturnBasis(StrEnum):
    NAV_HISTORICAL = "NAV_HISTORICAL"  # already net of expenses — never subtract an expense ratio
    FORWARD_GROSS = "FORWARD_GROSS"  # a gross forward quantity (e.g. portfolio YTM)


@dataclass(frozen=True, slots=True)
class ExpenseRatio:
    kind: ExpenseRatioKind
    rate: Decimal  # annual, decimal fraction
    as_of: date


@dataclass(frozen=True, slots=True)
class ExpenseNetFactor:
    gross_return: Decimal
    net_return: Decimal
    drag_factor: Decimal
    effective_rate: Decimal
    expense_ratio: ExpenseRatio
    levies_estimate: Decimal | None
    days: int
    formula_id: str = "TER_NET_FACTOR@1"
    warnings: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()


def expense_net_factor(
    gross_return: Decimal,
    expense_ratio: ExpenseRatio,
    basis: ReturnBasis,
    *,
    levies_estimate: Decimal | None = None,
    days: int = 365,
) -> ExpenseNetFactor:
    """Forward model: ``net = (1 + gross) × (1 − ER/365)^days − 1`` (daily accrual approximation).

    ``gross_return`` is the gross return over ``days``.  For BER the effective rate is
    ``BER + levies_estimate`` (the estimate is mandatory and flagged); for TER levies are included.
    """
    if basis is ReturnBasis.NAV_HISTORICAL:
        raise InvalidInput(
            "NAV-based returns are already net of scheme expenses; subtracting TER/BER would double count"
        )
    if days <= 0:
        raise InvalidInput(f"days must be > 0, got {days}")
    gross = D(gross_return)
    if gross < -ONE:
        raise InvalidInput(f"gross return below −100 %: {gross}")
    rate = D(expense_ratio.rate)
    warnings: list[str] = []
    flags: list[str] = ["ACCRUAL_BASIS_NOT_VERIFIED"]
    levies: Decimal | None = None
    with engine_context():
        if expense_ratio.kind is ExpenseRatioKind.BER:
            if expense_ratio.as_of < BER_EFFECTIVE_FROM:
                raise InvalidInput(f"BER cannot be dated before {BER_EFFECTIVE_FROM}: {expense_ratio.as_of}")
            if levies_estimate is None:
                raise MissingData("BER excludes levies/brokerage: a labelled levies_estimate is required")
            levies = D(levies_estimate)
            if levies < 0:
                raise InvalidInput(f"levies_estimate must be ≥ 0, got {levies}")
            effective = rate + levies
            flags.append("LEVIES_ESTIMATED")
        else:
            if levies_estimate is not None:
                raise InvalidInput("TER already includes levies; levies_estimate applies to BER only")
            if expense_ratio.as_of >= BER_EFFECTIVE_FROM:
                warnings.append("TER_DATED_AFTER_BER_TRANSITION")
            effective = rate
        if not ZERO <= rate < ONE or not ZERO <= effective < ONE:
            raise InvalidInput(f"expense ratio must be in [0, 1), got {effective}")
        drag = (ONE - effective / Decimal(365)) ** days
        net = (ONE + gross) * drag - ONE
    return ExpenseNetFactor(
        gross_return=gross,
        net_return=net,
        drag_factor=drag,
        effective_rate=effective,
        expense_ratio=expense_ratio,
        levies_estimate=levies,
        days=days,
        warnings=tuple(warnings),
        flags=tuple(flags),
    )
