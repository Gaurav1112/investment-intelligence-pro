"""Rebalance execution plan — ``actions.rebalance@1`` (design-risk-first.md §5.6, policy ``policy.rebalance@1``).

Pure, deterministic allocation arithmetic: no clock, no IO, no forecast.  Money is ``Decimal`` under
``engine_context()``; amounts are quantized to paise only at the output boundary.

Order of the plan (cash-flow-first):

1. **Trigger.** ``|w_actual − w_target| > band`` for some sleeve, at a review date or when L3 breaches.
   Out-of-cycle drift is reported (``DRIFT_SHOWN_NOT_DUE``) but produces no step.
2. **Redirect contributions.** Upcoming contributions are applied one at a time, each split across sleeves pro rata
   to ``need_s = max(0, w_s × (V + c) − MV_s)`` (``cash_flow_split``), until ``max |drift| < band / 2``.  Zero tax.
3. **Sales** (only if the user allows them and drift is still outside the band): every overweight sleeve is sold
   down to its target.  Sell sources are chosen **between schemes and folios only**.  Inside one (scheme, folio)
   the lots are consumed strictly FIFO (oldest allotment first) — the engine never picks a lot.  At each step the
   engine takes, among all sources, the next FIFO slice with the lowest
   ``cost_per_rupee = (tax + exit_load + STT) / gross`` (ties: instrument_id, folio).  The remaining LTCG
   exemption is applied as gains are realised, so exempt gains are naturally used first.
   A source is **blocked** (the engine cannot skip its oldest lot) when its next lot is locked in, has no cost
   basis, sits inside an exit-load window the user did not allow, has an unknown exit load while younger than
   ``UNKNOWN_LOAD_ABSTAIN_DAYS``, has an unknown tax rate, or is short-term with a gain and turns long-term within
   ``lt_wait_days`` (then the card says "wait until").
   Proceeds net of exit load and STT are reinvested into underweight sleeves (stamp duty applied).  Tax is shown,
   not deducted: it is paid at filing (``TAX_PAID_SEPARATELY``).
4. **Residual drift** after the plan and the ₹ cost of every step are reported.

Not modelled (flagged): loss set-off, surcharge, grandfathering (caller must not pass pre-2018 lots), wash-sale rules.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Literal

from iip.engine.costs import LoadTier, stamp_duty
from iip.engine.dates import add_months, days_between
from iip.engine.errors import InvalidInput
from iip.engine.money import ONE, PAISA, UNITS_QUANTUM, ZERO, D, engine_context, money

FORMULA_ID = "actions.rebalance@1"
POLICY_ID = "policy.rebalance@1"

# PARAMETER (PLAN.md A15 row): an unknown exit-load schedule abstains for lots held this many days or fewer.
UNKNOWN_LOAD_ABSTAIN_DAYS = 365

Status = Literal["PASS", "ACTION", "ABSTAIN"]
Verb = Literal["REDIRECT_SIP", "INVEST", "REDEEM", "WAIT_UNTIL"]
BlockReason = Literal[
    "locked_in",
    "cost_basis_unknown",
    "exit_load_unknown",
    "inside_exit_load_window",
    "tax_rate_unknown",
    "turns_long_term_soon",
]


# ---------------------------------------------------------------- shared contracts (also used by next_rupee)


@dataclass(frozen=True, slots=True)
class Abstention:
    code: str
    missing_input: str
    how_to_fix: str


@dataclass(frozen=True, slots=True)
class StepCost:
    exit_load: Decimal = ZERO
    stamp: Decimal = ZERO
    stt: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class StepTax:
    stcg: Decimal = ZERO
    ltcg: Decimal = ZERO
    cess: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class LotConsumed:
    lot_id: str
    allotment_date: date
    units: Decimal
    days_held: int
    gain_type: Literal["STCG", "LTCG"]
    gain: Decimal
    exempt_gain: Decimal
    exit_load: Decimal
    tax: Decimal


@dataclass(frozen=True, slots=True)
class PlanStep:
    """One step of a plan; mirrors the ActionCard ``steps[]`` shape (design-risk-first.md §7.1)."""

    verb: Verb
    sleeve_id: str
    amount: Decimal
    instrument_id: str | None = None
    folio: str | None = None
    units: Decimal | None = None
    goal_id: str | None = None
    layer: str | None = None
    lots_consumed: tuple[LotConsumed, ...] = ()
    cost: StepCost = field(default_factory=StepCost)
    tax: StepTax = field(default_factory=StepTax)
    net_effect: Decimal = ZERO
    wait_until: date | None = None
    abstention: Abstention | None = None


# ---------------------------------------------------------------- inputs


@dataclass(frozen=True, slots=True)
class SleeveState:
    sleeve_id: str
    market_value: Decimal
    target_weight: Decimal | None  # None = the user has not set it → ABSTAIN


@dataclass(frozen=True, slots=True)
class HeldLot:
    lot_id: str
    allotment_date: date
    units: Decimal
    cost_per_unit: Decimal | None  # None = unknown cost basis → the source is blocked


@dataclass(frozen=True, slots=True)
class TaxTreatment:
    """Rates come from the versioned rule table (rules/tax); the engine holds none of them.

    ``lt_threshold_months=None`` means the gain is never long-term (e.g. specified MFs taxed at slab).
    ``st_rate=None`` means the rate is unknown (e.g. slab not given) → the source is blocked for ST lots.
    """

    st_rate: Decimal | None
    lt_rate: Decimal | None
    lt_threshold_months: int | None
    exemption_eligible: bool
    rule_id: str = "rules/tax"


@dataclass(frozen=True, slots=True)
class SaleSource:
    """One (scheme, folio) the plan may redeem from.  Its lots are consumed FIFO, never picked."""

    instrument_id: str
    folio: str
    sleeve_id: str
    nav: Decimal
    lots: tuple[HeldLot, ...]
    exit_load: tuple[LoadTier, ...] | None  # None = schedule unknown; () = no load
    tax: TaxTreatment
    stt_rate: Decimal
    lock_in_days: int = 0


@dataclass(frozen=True, slots=True)
class RebalanceParams:
    band: Decimal  # absolute, e.g. 0.05 = ±5 pp (PARAMETER, cited default in design §5.6)
    is_review_date: bool
    allow_sales: bool
    allow_exit_load_sales: bool
    lt_wait_days: int  # PARAMETER: a short-term lot that turns long-term within this many days → wait (0 = off)
    cess_rate: Decimal | None  # from the tax rule table; None → sales abstain
    ltcg_exemption_remaining: Decimal | None  # ₹ left this FY; None → sales abstain ("assume used" = pass 0)
    l3_breach: bool = False


# ---------------------------------------------------------------- outputs


@dataclass(frozen=True, slots=True)
class SleeveDrift:
    sleeve_id: str
    market_value: Decimal
    actual_weight: Decimal
    target_weight: Decimal
    drift: Decimal


@dataclass(frozen=True, slots=True)
class BlockedSource:
    instrument_id: str
    folio: str
    lot_id: str
    reason: BlockReason
    wait_until: date | None = None


@dataclass(frozen=True, slots=True)
class RebalancePlan:
    status: Status
    as_of: date
    total_value: Decimal
    band: Decimal
    triggered: bool
    drift_before: tuple[SleeveDrift, ...]
    contributions_used: int
    steps: tuple[PlanStep, ...]
    drift_after: tuple[SleeveDrift, ...]
    residual_max_drift: Decimal
    blocked: tuple[BlockedSource, ...]
    exemption_used: Decimal
    total_cost: StepCost
    total_tax: StepTax
    abstentions: tuple[Abstention, ...] = ()
    flags: tuple[str, ...] = ()
    formula_id: str = FORMULA_ID
    policy_id: str = POLICY_ID


# ---------------------------------------------------------------- shared arithmetic


def cash_flow_split(market_values: Sequence[Decimal], weights: Sequence[Decimal], amount: Decimal) -> list[Decimal]:
    """Split ``amount`` of new money across sleeves pro rata to ``need_s = max(0, w_s × (V + amount) − MV_s)``.

    With ``Σ w = 1`` the needs sum to at least ``amount``, so every share is ≤ its need.  Unrounded.
    """
    with engine_context():
        if amount <= 0:
            return [ZERO for _ in market_values]
        v_after = sum(market_values, ZERO) + amount
        needs = [max(ZERO, w * v_after - mv) for mv, w in zip(market_values, weights, strict=True)]
        total = sum(needs, ZERO)
        return [amount * n / total for n in needs]


def split_to_paise(total: Decimal, raw: Sequence[Decimal]) -> list[Decimal]:
    """Round raw shares down to paise and give the leftover paise, one each, to the largest remainders
    (ties: earlier index), so the rounded parts sum exactly to ``total`` (which must be in paise)."""
    with engine_context():
        if total != total.quantize(PAISA):
            raise InvalidInput(f"amount must be in whole paise, got {total}")
        floors = [(r / PAISA).to_integral_value(rounding="ROUND_FLOOR") * PAISA for r in raw]
        left = int((total - sum(floors, ZERO)) / PAISA)
        if left < 0 or left > len(raw):
            raise InvalidInput("shares do not add up to the total")  # pragma: no cover - guarded by callers
        order = sorted(range(len(raw)), key=lambda i: (-(raw[i] - floors[i]), i))
        for i in order[:left]:
            floors[i] += PAISA
        return floors


def _weights(sleeves: Sequence[SleeveState], values: Sequence[Decimal]) -> tuple[Decimal, list[Decimal]]:
    with engine_context():
        total = sum(values, ZERO)
        if total == 0:
            return total, [ZERO for _ in values]
        return total, [v / total for v in values]


def _drifts(sleeves: Sequence[SleeveState], targets: Sequence[Decimal], values: Sequence[Decimal]) -> list[SleeveDrift]:
    _, ws = _weights(sleeves, values)
    with engine_context():
        return [
            SleeveDrift(s.sleeve_id, v, w, t, w - t) for s, t, v, w in zip(sleeves, targets, values, ws, strict=True)
        ]


def _max_abs(drifts: Sequence[SleeveDrift]) -> Decimal:
    return max((abs(d.drift) for d in drifts), default=ZERO)


def _validate(sleeves: Sequence[SleeveState], params: RebalanceParams) -> None:
    ids = [s.sleeve_id for s in sleeves]
    if not sleeves or len(set(ids)) != len(ids):
        raise InvalidInput("sleeves must be non-empty with unique ids")
    for s in sleeves:
        if D(s.market_value) < 0:
            raise InvalidInput(f"market value of {s.sleeve_id} must be ≥ 0")
        if s.target_weight is not None and not ZERO <= D(s.target_weight) <= ONE:
            raise InvalidInput(f"target weight of {s.sleeve_id} must be in [0, 1]")
    targets = [s.target_weight for s in sleeves if s.target_weight is not None]
    if len(targets) == len(sleeves):
        with engine_context():
            if sum(targets, ZERO) != ONE:
                raise InvalidInput("target weights must sum to exactly 1")
    if not ZERO < D(params.band) < ONE:
        raise InvalidInput("band must be in (0, 1)")
    if params.lt_wait_days < 0:
        raise InvalidInput("lt_wait_days must be ≥ 0")


# ---------------------------------------------------------------- sale selection (FIFO per folio)


@dataclass(slots=True)
class _Cursor:
    src: SaleSource
    lots: list[HeldLot]
    idx: int = 0
    used: Decimal = ZERO  # units already taken from lots[idx]
    blocked: BlockedSource | None = None
    consumed: list[LotConsumed] = field(default_factory=list)
    stt: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class _Slice:
    cost_per_rupee: Decimal
    key: tuple[str, str]
    units: Decimal
    gross: Decimal
    gain_type: Literal["STCG", "LTCG"]
    gain: Decimal
    exempt: Decimal
    load: Decimal
    stt: Decimal
    tax_base: Decimal  # tax before cess
    days_held: int


def _is_long_term(lot: HeldLot, as_of: date, months: int | None) -> bool:
    return months is not None and as_of > add_months(lot.allotment_date, months)


def _load_rate(schedule: tuple[LoadTier, ...], days_held: int) -> Decimal:
    for tier in sorted(schedule, key=lambda t: t.window_days):
        if days_held <= tier.window_days:
            return D(tier.rate)
    return ZERO


def _block_reason(cur: _Cursor, as_of: date, params: RebalanceParams) -> tuple[BlockReason, date | None] | None:
    src, lot = cur.src, cur.lots[cur.idx]
    held = days_between(lot.allotment_date, as_of)
    if held < src.lock_in_days:
        return "locked_in", lot.allotment_date + timedelta(days=src.lock_in_days)
    if lot.cost_per_unit is None:
        return "cost_basis_unknown", None
    if src.exit_load is None:
        if held <= UNKNOWN_LOAD_ABSTAIN_DAYS:
            return "exit_load_unknown", None
    elif _load_rate(src.exit_load, held) > 0 and not params.allow_exit_load_sales:
        return "inside_exit_load_window", None
    lt = _is_long_term(lot, as_of, src.tax.lt_threshold_months)
    if (src.tax.lt_rate if lt else src.tax.st_rate) is None:
        return "tax_rate_unknown", None
    if not lt and src.tax.lt_threshold_months is not None and params.lt_wait_days > 0:
        lt_from = add_months(lot.allotment_date, src.tax.lt_threshold_months) + timedelta(days=1)
        with engine_context():
            has_gain = D(src.nav) > D(lot.cost_per_unit)
        if has_gain and days_between(as_of, lt_from) <= params.lt_wait_days:
            return "turns_long_term_soon", lt_from
    return None


def _next_slice(cur: _Cursor, need: Decimal, as_of: date, exemption: Decimal, cess: Decimal) -> _Slice | None:
    src, lot = cur.src, cur.lots[cur.idx]
    nav = D(src.nav)
    cpu = D(lot.cost_per_unit)  # type: ignore[arg-type]  # guarded by _block_reason
    with engine_context():
        available = D(lot.units) - cur.used
        wanted = (need / nav).quantize(UNITS_QUANTUM, rounding=ROUND_CEILING)
        units = min(available, wanted)
        if units <= 0:
            return None
        gross = units * nav
        gain = units * (nav - cpu)
        held = days_between(lot.allotment_date, as_of)
        lt = _is_long_term(lot, as_of, src.tax.lt_threshold_months)
        exempt = min(max(gain, ZERO), exemption) if lt and src.tax.exemption_eligible else ZERO
        rate = D(src.tax.lt_rate if lt else src.tax.st_rate)  # type: ignore[arg-type]
        tax_base = max(gain - exempt, ZERO) * rate
        load = ZERO if not src.exit_load else _load_rate(src.exit_load, held) * gross
        stt = gross * D(src.stt_rate)
        cpr = (tax_base * (ONE + cess) + load + stt) / gross
    return _Slice(
        cost_per_rupee=cpr,
        key=(src.instrument_id, src.folio),
        units=units,
        gross=gross,
        gain_type="LTCG" if lt else "STCG",
        gain=gain,
        exempt=exempt,
        load=load,
        stt=stt,
        tax_base=tax_base,
        days_held=held,
    )


def _select_sales(
    sources: Sequence[SaleSource], need: Decimal, as_of: date, params: RebalanceParams, exemption: Decimal
) -> tuple[list[_Cursor], Decimal, Decimal]:
    """Greedy over each source's next FIFO slice; returns cursors, the unmet need and the exemption used."""
    cess = D(params.cess_rate)  # type: ignore[arg-type]  # checked by the caller
    cursors = {
        (s.instrument_id, s.folio): _Cursor(s, sorted(s.lots, key=lambda lot: lot.allotment_date))
        for s in sorted(sources, key=lambda s: (s.instrument_id, s.folio))
    }
    used_exemption = ZERO
    with engine_context():
        while need > 0:
            best: _Slice | None = None
            for cur in cursors.values():
                if cur.blocked is not None or cur.idx >= len(cur.lots):
                    continue
                reason = _block_reason(cur, as_of, params)
                if reason is not None:
                    lot = cur.lots[cur.idx]
                    cur.blocked = BlockedSource(cur.src.instrument_id, cur.src.folio, lot.lot_id, reason[0], reason[1])
                    continue
                cand = _next_slice(cur, need, as_of, exemption - used_exemption, cess)
                if cand is not None and (
                    best is None or (cand.cost_per_rupee, cand.key) < (best.cost_per_rupee, best.key)
                ):
                    best = cand
            if best is None:
                break
            cur = cursors[best.key]
            lot = cur.lots[cur.idx]
            cur.consumed.append(
                LotConsumed(
                    lot_id=lot.lot_id,
                    allotment_date=lot.allotment_date,
                    units=best.units,
                    days_held=best.days_held,
                    gain_type=best.gain_type,
                    gain=best.gain,
                    exempt_gain=best.exempt,
                    exit_load=best.load,
                    tax=best.tax_base,
                )
            )
            cur.stt += best.stt
            cur.used += best.units
            if cur.used == D(lot.units):
                cur.idx += 1
                cur.used = ZERO
            used_exemption += best.exempt
            need -= best.gross
    return list(cursors.values()), max(need, ZERO), used_exemption


def _redeem_step(cur: _Cursor, cess: Decimal) -> PlanStep:
    src = cur.src
    with engine_context():
        units = sum((c.units for c in cur.consumed), ZERO)
        gross = units * D(src.nav)
        load = sum((c.exit_load for c in cur.consumed), ZERO)
        stcg = sum((c.tax for c in cur.consumed if c.gain_type == "STCG"), ZERO)
        ltcg = sum((c.tax for c in cur.consumed if c.gain_type == "LTCG"), ZERO)
        cess_amt = (stcg + ltcg) * cess
        cost = StepCost(exit_load=money(load), stt=money(cur.stt))
        tax = StepTax(stcg=money(stcg), ltcg=money(ltcg), cess=money(cess_amt))
        amount = money(gross)
        net = amount - cost.exit_load - cost.stt
    return PlanStep(
        verb="REDEEM",
        sleeve_id=src.sleeve_id,
        amount=amount,
        instrument_id=src.instrument_id,
        folio=src.folio,
        units=units,
        lots_consumed=_merge_lots(cur.consumed),
        cost=cost,
        tax=tax,
        net_effect=net,
        layer="L5",
    )


def _merge_lots(items: Sequence[LotConsumed]) -> tuple[LotConsumed, ...]:
    out: list[LotConsumed] = []
    with engine_context():
        for c in items:
            if out and out[-1].lot_id == c.lot_id:
                p = out[-1]
                out[-1] = LotConsumed(
                    p.lot_id,
                    p.allotment_date,
                    p.units + c.units,
                    p.days_held,
                    p.gain_type,
                    p.gain + c.gain,
                    p.exempt_gain + c.exempt_gain,
                    p.exit_load + c.exit_load,
                    p.tax + c.tax,
                )
            else:
                out.append(c)
    return tuple(out)


def _redirect(
    sleeves: Sequence[SleeveState],
    targets: Sequence[Decimal],
    values: list[Decimal],
    contributions: Sequence[Decimal],
    band: Decimal,
) -> tuple[list[PlanStep], list[Decimal], int]:
    """Step 1: apply contributions one at a time until ``max |drift| < band / 2``. Zero tax."""
    redirected = [ZERO for _ in sleeves]
    used = 0
    with engine_context():
        half = band / 2
        for c in contributions:
            amount = D(c)
            if amount <= 0:
                raise InvalidInput("contributions must be > 0")
            if _max_abs(_drifts(sleeves, targets, values)) < half:
                break
            shares = split_to_paise(amount, cash_flow_split(values, targets, amount))
            values = [v + s for v, s in zip(values, shares, strict=True)]
            redirected = [r + s for r, s in zip(redirected, shares, strict=True)]
            used += 1
    steps = [
        PlanStep("REDIRECT_SIP", s.sleeve_id, money(amt), net_effect=money(amt), layer="L5")
        for s, amt in zip(sleeves, redirected, strict=True)
        if amt > 0
    ]
    return steps, values, used


def _sell_and_reinvest(
    sleeves: Sequence[SleeveState],
    targets: Sequence[Decimal],
    values: list[Decimal],
    sources: Sequence[SaleSource],
    as_of: date,
    params: RebalanceParams,
    flags: list[str],
) -> tuple[list[PlanStep], list[BlockedSource], Decimal]:
    """Steps 2–3: sell each overweight sleeve down to target (FIFO per folio), reinvest net proceeds.

    Mutates ``values`` (post-plan market values) and appends to ``flags``.
    """
    steps: list[PlanStep] = []
    blocked: list[BlockedSource] = []
    exemption_left = D(params.ltcg_exemption_remaining)  # type: ignore[arg-type]  # checked by the caller
    cess = D(params.cess_rate)  # type: ignore[arg-type]
    exemption_used = ZERO
    proceeds = ZERO
    exhausted = False
    with engine_context():
        v_now = sum(values, ZERO)
        for i, s in enumerate(sleeves):
            excess = values[i] - targets[i] * v_now
            if excess <= 0:
                continue
            own = [x for x in sources if x.sleeve_id == s.sleeve_id]
            cursors, unmet, ex_used = _select_sales(own, excess, as_of, params, exemption_left)
            exemption_left -= ex_used
            exemption_used += ex_used
            exhausted = exhausted or unmet > 0
            for cur in cursors:
                if cur.blocked is not None:
                    blocked.append(cur.blocked)
                if cur.consumed:
                    step = _redeem_step(cur, cess)
                    steps.append(step)
                    values[i] -= step.amount
                    proceeds += step.net_effect
        if exhausted:
            flags.append("SALE_SOURCES_EXHAUSTED")
        if proceeds > 0:
            flags.append("TAX_PAID_SEPARATELY")
            shares = split_to_paise(proceeds, cash_flow_split(values, targets, proceeds))
            for i, s in enumerate(sleeves):
                if shares[i] <= 0:
                    continue
                sd = stamp_duty(shares[i], trade_date=as_of)
                steps.append(
                    PlanStep(
                        "INVEST",
                        s.sleeve_id,
                        shares[i],
                        cost=StepCost(stamp=sd.stamp_duty),
                        net_effect=sd.invested,
                        layer="L5",
                    )
                )
                values[i] += sd.invested
    return steps, blocked, exemption_used


def _wait_steps(blocked: Sequence[BlockedSource], sources: Sequence[SaleSource]) -> list[PlanStep]:
    sleeve_of = {(x.instrument_id, x.folio): x.sleeve_id for x in sources}
    return [
        PlanStep(
            "WAIT_UNTIL",
            sleeve_of[(b.instrument_id, b.folio)],
            ZERO,
            instrument_id=b.instrument_id,
            folio=b.folio,
            wait_until=b.wait_until,
            layer="L5",
        )
        for b in blocked
        if b.reason == "turns_long_term_soon" and b.wait_until is not None
    ]


# ---------------------------------------------------------------- the planner


def plan_rebalance(
    sleeves: Sequence[SleeveState],
    *,
    as_of: date,
    params: RebalanceParams,
    contributions: Sequence[Decimal] = (),
    sources: Sequence[SaleSource] = (),
) -> RebalancePlan:
    """Build the cash-flow-first rebalance plan for one goal (or one portfolio) on ``as_of``."""
    _validate(sleeves, params)
    for src in sources:
        if D(src.nav) <= 0 or any(D(lot.units) <= 0 for lot in src.lots):
            raise InvalidInput(f"source {src.instrument_id}/{src.folio}: NAV and lot units must be > 0")
        if any(lot.allotment_date > as_of for lot in src.lots):
            raise InvalidInput(f"source {src.instrument_id}/{src.folio} has a lot allotted after {as_of}")
        if src.sleeve_id not in {s.sleeve_id for s in sleeves}:
            raise InvalidInput(f"source {src.instrument_id}/{src.folio} maps to unknown sleeve {src.sleeve_id}")
    band = D(params.band)
    values = [D(s.market_value) for s in sleeves]
    total = sum(values, ZERO)
    zero_tax, zero_cost = StepTax(), StepCost()

    missing = [s.sleeve_id for s in sleeves if s.target_weight is None]
    if missing:
        ab = Abstention(
            "target_missing", f"target weight for {', '.join(missing)}", "Set the policy target per sleeve."
        )
        return RebalancePlan(
            "ABSTAIN", as_of, total, band, False, (), 0, (), (), ZERO, (), ZERO, zero_cost, zero_tax, (ab,)
        )
    targets = [D(s.target_weight) for s in sleeves]  # type: ignore[arg-type]
    before = _drifts(sleeves, targets, values)
    flags: list[str] = []
    if total == 0:
        return RebalancePlan(
            "PASS", as_of, total, band, False, (), 0, (), (), ZERO, (), ZERO, zero_cost, zero_tax, (), ("EMPTY",)
        )
    outside = _max_abs(before) > band
    triggered = outside and (params.is_review_date or params.l3_breach)
    if not triggered:
        if outside:
            flags.append("DRIFT_SHOWN_NOT_DUE")
        return RebalancePlan(
            "PASS",
            as_of,
            total,
            band,
            False,
            tuple(before),
            0,
            (),
            tuple(before),
            _max_abs(before),
            (),
            ZERO,
            zero_cost,
            zero_tax,
            (),
            tuple(flags),
        )

    steps, values, used = _redirect(sleeves, targets, values, contributions, band)
    abstentions: list[Abstention] = []
    blocked: list[BlockedSource] = []
    exemption_used = ZERO
    if _max_abs(_drifts(sleeves, targets, values)) > band:
        if not params.allow_sales:
            flags.append("SALES_NOT_ALLOWED")
        elif params.cess_rate is None or params.ltcg_exemption_remaining is None:
            abstentions.append(
                Abstention(
                    "tax_context_missing",
                    "cess rate and LTCG exemption used this financial year",
                    "Add your tax context (or choose 'assume the exemption is used').",
                )
            )
        else:
            sale_steps, blocked, exemption_used = _sell_and_reinvest(
                sleeves, targets, values, sources, as_of, params, flags
            )
            steps.extend(sale_steps)
    steps.extend(_wait_steps(blocked, sources))

    after = _drifts(sleeves, targets, values)
    with engine_context():
        total_cost = StepCost(
            exit_load=sum((s.cost.exit_load for s in steps), ZERO),
            stamp=sum((s.cost.stamp for s in steps), ZERO),
            stt=sum((s.cost.stt for s in steps), ZERO),
        )
        total_tax = StepTax(
            stcg=sum((s.tax.stcg for s in steps), ZERO),
            ltcg=sum((s.tax.ltcg for s in steps), ZERO),
            cess=sum((s.tax.cess for s in steps), ZERO),
        )
    if any(s.verb == "REDEEM" for s in steps):
        flags.append("LOSS_SET_OFF_NOT_MODELLED")
    return RebalancePlan(
        status="ACTION",
        as_of=as_of,
        total_value=total,
        band=band,
        triggered=True,
        drift_before=tuple(before),
        contributions_used=used,
        steps=tuple(steps),
        drift_after=tuple(after),
        residual_max_drift=_max_abs(after),
        blocked=tuple(blocked),
        exemption_used=exemption_used,
        total_cost=total_cost,
        total_tax=total_tax,
        abstentions=tuple(abstentions),
        flags=tuple(flags),
    )
