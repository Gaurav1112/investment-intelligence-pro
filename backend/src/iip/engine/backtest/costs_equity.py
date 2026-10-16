"""Equity-delivery and ETF trading costs, point-in-time (research-backtest-method.md §6.1, fixture C-1).

Pure and deterministic. Rates are versioned rule rows supplied by the caller (``rules/costs/india_equity.yaml`` is
owned by the runner package); this module only applies them.

Per order (one side), with ``v`` the traded value:

* brokerage   = min(v × brokerage_rate, brokerage_cap)            (broker-specific, REQUIRES CONFIGURATION)
* STT         = round(v × stt_rate, stt_rounding_quantum, HALF_UP)  (buy and sell; rounded per side, "paise ≥ 50 up")
* exchange    = v × exchange_txn_rate
* SEBI fee    = v × sebi_fee_rate                                    (₹10 per crore = 1e-6)
* stamp       = v × stamp_rate_buy                                   (buy side only)
* GST         = gst_rate × (brokerage + SEBI fee + exchange)
* DP charge   = fixed ₹ per scrip per sell day                       (sell side; only the first sell of the day)

Only STT is rounded here (the rule says so); the other components stay unrounded because contract-note rounding is
NOT VERIFIED. Display rounds once at the boundary.

``costs_estimated`` — when no row covers the trade date, when the row is not verified, or for ETFs (the 0.1 % STT row
is not shown to apply to ETFs, verify BT-4), every rate and fixed charge of the latest row (or the matched row) is
scaled by ``estimate_multiplier`` (≥ 1, a conservative upper bound) and the result is flagged. The flag caps the
evidence state downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from itertools import pairwise

from iip.engine.backtest.ledger import R_COSTS_ESTIMATED, TradeCost
from iip.engine.errors import InvalidInput
from iip.engine.money import ONE, ZERO, D, engine_context

__all__ = [
    "FORMULA_ID",
    "R_COSTS_ESTIMATED",
    "R_ETF_STT_UNVERIFIED",
    "R_NO_COST_ROW",
    "R_ROW_NOT_VERIFIED",
    "R_ROW_REQUIRES_CONFIGURATION",
    "CostStatus",
    "EquityCostRow",
    "EquityCostSchedule",
    "InstrumentKind",
    "Side",
    "equity_trade_cost",
]

FORMULA_ID = "BT-COST-EQ@1"

R_NO_COST_ROW = "no_cost_row_for_date"
R_ROW_NOT_VERIFIED = "cost_row_not_verified"
R_ROW_REQUIRES_CONFIGURATION = "cost_row_requires_configuration"
R_ETF_STT_UNVERIFIED = "etf_stt_unverified"


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class InstrumentKind(StrEnum):
    EQUITY_DELIVERY = "EQUITY_DELIVERY"
    ETF = "ETF"


class CostStatus(StrEnum):
    VERIFIED_PRIMARY = "VERIFIED-PRIMARY"
    VERIFIED_SECONDARY = "VERIFIED-SECONDARY"
    NOT_VERIFIED = "NOT VERIFIED"
    REQUIRES_CONFIGURATION = "REQUIRES CONFIGURATION"


_RATE_FIELDS = ("brokerage_rate", "stt_rate", "exchange_txn_rate", "sebi_fee_rate", "stamp_rate_buy", "gst_rate")


@dataclass(frozen=True, kw_only=True)
class EquityCostRow:
    """One versioned cost row, in force for trades in [effective_from, effective_to] (inclusive)."""

    rule_id: str
    effective_from: date
    effective_to: date | None
    brokerage_rate: Decimal
    brokerage_cap_inr: Decimal | None
    stt_rate: Decimal
    stt_rounding_quantum: Decimal
    exchange_txn_rate: Decimal
    sebi_fee_rate: Decimal
    stamp_rate_buy: Decimal
    gst_rate: Decimal
    dp_charge_per_scrip_sell_day_inr: Decimal
    status: CostStatus
    source: str

    def __post_init__(self) -> None:
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise InvalidInput(f"{self.rule_id}: effective_to before effective_from")
        for name in _RATE_FIELDS:
            v = getattr(self, name)
            if not isinstance(v, Decimal) or not ZERO <= v <= ONE:
                raise InvalidInput(f"{self.rule_id}: {name} must be a Decimal fraction in [0, 1]")
        for name in ("dp_charge_per_scrip_sell_day_inr", "stt_rounding_quantum"):
            v = getattr(self, name)
            if not isinstance(v, Decimal) or v < ZERO:
                raise InvalidInput(f"{self.rule_id}: {name} must be a non-negative Decimal")
        if self.stt_rounding_quantum <= ZERO:
            raise InvalidInput(f"{self.rule_id}: stt_rounding_quantum must be positive")
        if self.brokerage_cap_inr is not None and (
            not isinstance(self.brokerage_cap_inr, Decimal) or self.brokerage_cap_inr < ZERO
        ):
            raise InvalidInput(f"{self.rule_id}: brokerage_cap_inr must be a non-negative Decimal")

    def covers(self, on: date) -> bool:
        return self.effective_from <= on and (self.effective_to is None or on <= self.effective_to)


@dataclass(frozen=True, kw_only=True)
class EquityCostSchedule:
    rows: tuple[EquityCostRow, ...]
    estimate_multiplier: Decimal

    def __post_init__(self) -> None:
        if not self.rows:
            raise InvalidInput("a cost schedule needs at least one row")
        if not isinstance(self.estimate_multiplier, Decimal) or self.estimate_multiplier < ONE:
            raise InvalidInput("estimate_multiplier must be a Decimal ≥ 1 (an upper bound)")
        ordered = sorted(self.rows, key=lambda r: r.effective_from)
        for a, b in pairwise(ordered):
            if a.effective_to is None or a.effective_to >= b.effective_from:
                raise InvalidInput(f"overlapping cost rows: {a.rule_id}, {b.rule_id}")
        object.__setattr__(self, "rows", tuple(ordered))

    def row_for(self, on: date) -> EquityCostRow | None:
        hits = [r for r in self.rows if r.covers(on)]
        return hits[0] if hits else None

    @property
    def latest(self) -> EquityCostRow:
        return self.rows[-1]


def equity_trade_cost(
    side: Side,
    value_inr: Decimal,
    on: date,
    schedule: EquityCostSchedule,
    kind: InstrumentKind,
    *,
    first_sell_of_scrip_today: bool | None = None,
) -> TradeCost:
    """All charges on one order of ``value_inr`` traded on ``on``. Sells must say whether the DP charge applies."""
    value = D(value_inr)
    if value <= ZERO:
        raise InvalidInput(f"traded value must be positive, got {value}")
    if side is Side.SELL and first_sell_of_scrip_today is None:
        raise InvalidInput("a sell must state first_sell_of_scrip_today (DP charge is per scrip per sell day)")

    reasons: list[str] = []
    row = schedule.row_for(on)
    if row is None:
        row = schedule.latest
        reasons.append(R_NO_COST_ROW)
    if row.status is CostStatus.NOT_VERIFIED:
        reasons.append(R_ROW_NOT_VERIFIED)
    elif row.status is CostStatus.REQUIRES_CONFIGURATION:
        reasons.append(R_ROW_REQUIRES_CONFIGURATION)
    if kind is InstrumentKind.ETF:
        reasons.append(R_ETF_STT_UNVERIFIED)
    estimated = bool(reasons)
    m = schedule.estimate_multiplier if estimated else ONE

    with engine_context():
        brokerage = value * row.brokerage_rate * m
        if row.brokerage_cap_inr is not None:
            brokerage = min(brokerage, row.brokerage_cap_inr * m)
        stt = (value * row.stt_rate * m).quantize(row.stt_rounding_quantum, rounding=ROUND_HALF_UP)
        exchange = value * row.exchange_txn_rate * m
        sebi = value * row.sebi_fee_rate * m
        stamp = value * row.stamp_rate_buy * m if side is Side.BUY else ZERO
        gst = (brokerage + sebi + exchange) * min(row.gst_rate * m, ONE)
        dp = row.dp_charge_per_scrip_sell_day_inr * m if side is Side.SELL and first_sell_of_scrip_today else ZERO

    return TradeCost(
        components={
            "brokerage": brokerage,
            "stt": stt,
            "exchange_txn": exchange,
            "sebi_fee": sebi,
            "stamp": stamp,
            "gst": gst,
            "dp_charge": dp,
        },
        rule_id=row.rule_id,
        costs_estimated=estimated,
        reasons=tuple(reasons),
        multiplier=m,
    )
