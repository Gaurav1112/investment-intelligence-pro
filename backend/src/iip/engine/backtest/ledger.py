"""Backtest lot ledger (research-backtest-method.md §7.2): cash, FIFO lots, realisations, terminal liquidation.

Pure and deterministic. The ledger is an immutable value: every operation returns a new ``LedgerState``.

* Every buy creates a lot. Every sell consumes that instrument's lots **FIFO** (oldest acquisition first, ties by
  creation order). There is no API to choose lots, and ``assert_fifo`` re-checks any realisation sequence.
* Trades are chronological (a trade dated before the ledger's last date is rejected), long-only and unlevered
  (a buy needs enough cash for the price and all its costs; a sell cannot exceed the units held).
* Which cost components enter the tax cost basis (buy side) or are deductible from proceeds (sell side) is a rule row
  (``CostBasisPolicy``). That treatment is NOT VERIFIED, so an unverified policy adds ``cost_treatment_unverified``.
* Any trade whose costs are estimated makes the ledger ``costs_estimated`` for good; the reason code
  ``costs_estimated`` caps the evidence state downstream (gates, not this module).
* ``terminal_valuation`` reports both a **liquidated** (sell everything, pay costs and tax) and a **deferred**
  (hold; tax only on gains already realised) value, each under both exemption bounds. The gating value is
  liquidated + ``USED_ELSEWHERE``. Tax is settled at the terminal date (no interim payments): this is flagged.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from types import MappingProxyType

from iip.engine.backtest.tax_lots import (
    R_TAX_RULES_MISSING,
    ExemptionMode,
    Realisation,
    TaxRateTable,
    tax_on_realisations,
)
from iip.engine.errors import InvalidInput
from iip.engine.money import ONE, ZERO, D, engine_context

__all__ = [
    "R_COSTS_ESTIMATED",
    "W_COST_TREATMENT_UNVERIFIED",
    "W_TAX_SETTLED_AT_TERMINAL",
    "CostBasisPolicy",
    "LedgerState",
    "Lot",
    "ModeValues",
    "Realisation",
    "TerminalValuation",
    "TradeCost",
    "assert_fifo",
    "buy",
    "sell",
    "terminal_valuation",
]

FORMULA_ID = "BT-LEDGER@1"

R_COSTS_ESTIMATED = "costs_estimated"
W_COST_TREATMENT_UNVERIFIED = "cost_treatment_unverified"
W_TAX_SETTLED_AT_TERMINAL = "tax_settled_at_terminal_date"

_VERIFIED = frozenset({"VERIFIED-PRIMARY", "VERIFIED-SECONDARY"})


@dataclass(frozen=True, kw_only=True)
class TradeCost:
    """All charges on one order, by component name (₹, unrounded except where the rule rounds)."""

    components: Mapping[str, Decimal]
    rule_id: str
    costs_estimated: bool
    reasons: tuple[str, ...]
    multiplier: Decimal = ONE

    def __post_init__(self) -> None:
        for name, v in self.components.items():
            if not isinstance(v, Decimal) or not v.is_finite() or v < ZERO:
                raise InvalidInput(f"cost component {name} must be a non-negative finite Decimal")
        object.__setattr__(self, "components", MappingProxyType(dict(self.components)))

    @property
    def total_inr(self) -> Decimal:
        with engine_context():
            return sum(self.components.values(), ZERO)

    def sum_of(self, names: Iterable[str]) -> Decimal:
        with engine_context():
            return sum((self.components.get(n, ZERO) for n in names), ZERO)


@dataclass(frozen=True, kw_only=True)
class CostBasisPolicy:
    """Which cost components are capitalised into a lot (buy) or deducted from proceeds (sell) for tax."""

    deductible_components: frozenset[str]
    status: str


@dataclass(frozen=True, kw_only=True)
class Lot:
    lot_id: str
    instrument_id: str
    asset_class: str
    acquired: date
    units: Decimal
    cost_basis_inr: Decimal
    seq: int


@dataclass(frozen=True, kw_only=True)
class LedgerState:
    cash_inr: Decimal
    as_of: date
    lots: tuple[Lot, ...] = ()
    realisations: tuple[Realisation, ...] = ()
    costs_paid_inr: Decimal = ZERO
    costs_estimated: bool = False
    reason_codes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    next_seq: int = 1

    @classmethod
    def open(cls, *, cash: Decimal, on: date) -> LedgerState:
        cash = D(cash)
        if cash < ZERO:
            raise InvalidInput("opening cash must be non-negative")
        return cls(cash_inr=cash, as_of=on)

    def open_lots(self, instrument_id: str) -> tuple[Lot, ...]:
        """The instrument's open lots in FIFO order."""
        return tuple(
            sorted((lot for lot in self.lots if lot.instrument_id == instrument_id), key=lambda x: (x.acquired, x.seq))
        )

    def units_held(self, instrument_id: str) -> Decimal:
        with engine_context():
            return sum((lot.units for lot in self.lots if lot.instrument_id == instrument_id), ZERO)


def _positive(name: str, v: Decimal) -> Decimal:
    v = D(v)
    if v <= ZERO:
        raise InvalidInput(f"{name} must be positive, got {v}")
    return v


def _check_date(state: LedgerState, on: date) -> None:
    if on < state.as_of:
        raise InvalidInput(f"trade on {on} is before the ledger date {state.as_of}; trades must be chronological")


@dataclass(frozen=True)
class _Flags:
    costs_estimated: bool
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]


def _flags(state: LedgerState, cost: TradeCost, policy: CostBasisPolicy) -> _Flags:
    reasons = list(state.reason_codes)
    warnings = list(state.warnings)
    if cost.costs_estimated:
        reasons.extend((R_COSTS_ESTIMATED, *cost.reasons))
    if policy.status not in _VERIFIED:
        warnings.append(W_COST_TREATMENT_UNVERIFIED)
    return _Flags(
        costs_estimated=state.costs_estimated or cost.costs_estimated,
        reason_codes=tuple(dict.fromkeys(reasons)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def buy(
    state: LedgerState,
    instrument_id: str,
    asset_class: str,
    on: date,
    units: Decimal,
    price: Decimal,
    cost: TradeCost,
    policy: CostBasisPolicy,
) -> LedgerState:
    """Buy ``units`` at ``price``; debit price × units + all costs; open one lot."""
    _check_date(state, on)
    units = _positive("units", units)
    price = _positive("price", price)
    with engine_context():
        value = units * price
        debit = value + cost.total_inr
        if debit > state.cash_inr:
            raise InvalidInput(f"buy of ₹{value} plus costs needs ₹{debit}; cash is ₹{state.cash_inr} (no leverage)")
        basis = value + cost.sum_of(policy.deductible_components)
        lot = Lot(
            lot_id=f"{instrument_id}#{state.next_seq}",
            instrument_id=instrument_id,
            asset_class=asset_class,
            acquired=on,
            units=units,
            cost_basis_inr=basis,
            seq=state.next_seq,
        )
        flags = _flags(state, cost, policy)
        return replace(
            state,
            cash_inr=state.cash_inr - debit,
            as_of=on,
            lots=(*state.lots, lot),
            costs_paid_inr=state.costs_paid_inr + cost.total_inr,
            next_seq=state.next_seq + 1,
            costs_estimated=flags.costs_estimated,
            reason_codes=flags.reason_codes,
            warnings=flags.warnings,
        )


def sell(
    state: LedgerState,
    instrument_id: str,
    on: date,
    units: Decimal,
    price: Decimal,
    cost: TradeCost,
    policy: CostBasisPolicy,
) -> LedgerState:
    """Sell ``units`` at ``price``, consuming lots FIFO; credit proceeds − all costs; record realisations."""
    _check_date(state, on)
    units = _positive("units", units)
    price = _positive("price", price)
    fifo = state.open_lots(instrument_id)
    with engine_context():
        held = sum((lot.units for lot in fifo), ZERO)
        if units > held:
            raise InvalidInput(f"sell of {units} units of {instrument_id} exceeds {held} held (no short sales)")
        deductible_total = cost.sum_of(policy.deductible_components)
        remaining_units = units
        allocated_deductible = ZERO
        consumed: dict[str, Lot | None] = {}
        new_real: list[Realisation] = []
        for lot in fifo:
            if remaining_units <= ZERO:
                break
            take = min(lot.units, remaining_units)
            remaining_units -= take
            last_piece = remaining_units <= ZERO
            if take == lot.units:
                basis = lot.cost_basis_inr
                consumed[lot.lot_id] = None
            else:
                basis = lot.cost_basis_inr * take / lot.units
                consumed[lot.lot_id] = replace(lot, units=lot.units - take, cost_basis_inr=lot.cost_basis_inr - basis)
            if last_piece:
                ded = deductible_total - allocated_deductible
            else:
                ded = deductible_total * take / units
                allocated_deductible += ded
            new_real.append(
                Realisation(
                    lot_id=lot.lot_id,
                    instrument_id=instrument_id,
                    asset_class=lot.asset_class,
                    acquired=lot.acquired,
                    transferred=on,
                    units=take,
                    cost_basis_inr=basis,
                    proceeds_inr=take * price,
                    sell_costs_deductible_inr=ded,
                )
            )
        lots: list[Lot] = []
        for lot in state.lots:
            if lot.lot_id in consumed:
                kept = consumed[lot.lot_id]
                if kept is not None:
                    lots.append(kept)
            else:
                lots.append(lot)
        flags = _flags(state, cost, policy)
        return replace(
            state,
            cash_inr=state.cash_inr + units * price - cost.total_inr,
            as_of=on,
            lots=tuple(lots),
            realisations=(*state.realisations, *new_real),
            costs_paid_inr=state.costs_paid_inr + cost.total_inr,
            costs_estimated=flags.costs_estimated,
            reason_codes=flags.reason_codes,
            warnings=flags.warnings,
        )


def assert_fifo(realisations: Iterable[Realisation]) -> None:
    """Raise InvalidInput unless, per instrument, consumed lots never go back to an earlier acquisition."""
    last: dict[str, tuple[date, date]] = {}
    for r in realisations:
        key = (r.transferred, r.acquired)
        prev = last.get(r.instrument_id)
        if prev is not None and (key[0] < prev[0] or key[1] < prev[1]):
            raise InvalidInput(f"non-FIFO consumption of {r.instrument_id}: lot {r.lot_id} acquired {r.acquired}")
        last[r.instrument_id] = key


@dataclass(frozen=True, kw_only=True)
class ModeValues:
    value_before_tax_inr: Decimal
    tax_inr: Mapping[ExemptionMode, Decimal]  # empty when tax rules are missing
    value_after_tax_inr: Mapping[ExemptionMode, Decimal]  # empty when tax rules are missing
    tax_rules_missing: bool


@dataclass(frozen=True, kw_only=True)
class TerminalValuation:
    formula_id: str
    as_of: date
    cash_inr: Decimal
    market_value_inr: Decimal
    liquidation_costs_inr: Decimal
    deferred: ModeValues
    liquidated: ModeValues
    gating_value_inr: Decimal | None  # liquidated, exemption USED_ELSEWHERE; None when tax rules are missing
    tax_rules_missing: bool
    costs_estimated: bool
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]


SellCostFn = Callable[[str, date, Decimal], TradeCost]


def _mode_values(
    value: Decimal, realisations: tuple[Realisation, ...], table: TaxRateTable
) -> tuple[ModeValues, list[str], list[str]]:
    taxes: dict[ExemptionMode, Decimal] = {}
    after: dict[ExemptionMode, Decimal] = {}
    reasons: list[str] = []
    warnings: list[str] = []
    missing = False
    for mode in (ExemptionMode.USED_ELSEWHERE, ExemptionMode.AVAILABLE):
        res = tax_on_realisations(realisations, table, mode)
        reasons.extend(res.reasons)
        warnings.extend(res.warnings)
        if res.total_tax_inr is None:
            missing = True
            continue
        taxes[mode] = res.total_tax_inr
        with engine_context():
            after[mode] = value - res.total_tax_inr
    if missing:
        taxes, after = {}, {}
    mv = ModeValues(
        value_before_tax_inr=value,
        tax_inr=MappingProxyType(taxes),
        value_after_tax_inr=MappingProxyType(after),
        tax_rules_missing=missing,
    )
    return mv, reasons, warnings


def terminal_valuation(
    state: LedgerState,
    on: date,
    prices: Mapping[str, Decimal],
    sell_cost: SellCostFn,
    tax_table: TaxRateTable,
    *,
    policy: CostBasisPolicy,
) -> TerminalValuation:
    """Value the ledger at the end of the test, liquidated and deferred, under both exemption bounds."""
    _check_date(state, on)
    instruments = sorted({lot.instrument_id for lot in state.lots})
    liquidated_state = state
    with engine_context():
        market_value = ZERO
        for inst in instruments:
            if inst not in prices:
                raise InvalidInput(f"no terminal price for {inst}")
            price = _positive(f"terminal price of {inst}", prices[inst])
            units = state.units_held(inst)
            market_value += units * price
            cost = sell_cost(inst, on, units * price)
            liquidated_state = sell(liquidated_state, inst, on, units, price, cost, policy)
        liquidation_costs = liquidated_state.costs_paid_inr - state.costs_paid_inr
        deferred, r1, w1 = _mode_values(state.cash_inr + market_value, state.realisations, tax_table)
        liquidated, r2, w2 = _mode_values(liquidated_state.cash_inr, liquidated_state.realisations, tax_table)

    gating = liquidated.value_after_tax_inr.get(ExemptionMode.USED_ELSEWHERE)
    reasons = [*liquidated_state.reason_codes, *r1, *r2]
    if liquidated.tax_rules_missing:
        reasons.append(R_TAX_RULES_MISSING)
    warnings = [*liquidated_state.warnings, *w1, *w2, W_TAX_SETTLED_AT_TERMINAL]
    return TerminalValuation(
        formula_id=FORMULA_ID,
        as_of=on,
        cash_inr=state.cash_inr,
        market_value_inr=market_value,
        liquidation_costs_inr=liquidation_costs,
        deferred=deferred,
        liquidated=liquidated,
        gating_value_inr=gating,
        tax_rules_missing=liquidated.tax_rules_missing,
        costs_estimated=liquidated_state.costs_estimated,
        reason_codes=tuple(dict.fromkeys(reasons)),
        warnings=tuple(dict.fromkeys(warnings)),
    )
