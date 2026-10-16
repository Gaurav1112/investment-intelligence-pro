"""L6 tax actions: LTCG harvest within the annual exemption, and the "lot turns long-term soon → wait" modifier.

Sources: design-risk-first.md §5.8 (``tax.ltcg_harvest@1``), grafted per design-judgement.md §2.2 item 10 with
design-user-first.md §4.3 (ELSS excluded, Feb–Mar window as a PARAMETER, 45-day wait modifier, tax-loss harvesting off).

Pure: Decimal only, no clock, no IO.  ``as_of`` is the data date supplied by the caller.  Every tax rate, the annual
exemption, cess, surcharge caps, STT and stamp duty come from the versioned rule table (``TaxRuleSet``); this module
holds no statutory numbers.

Conventions:
* Redemption inside one folio is FIFO (CBDT Circular 768 / RTA practice).  The engine never picks lots inside a folio;
  it only chooses *which folio* to redeem from and how many units, and takes that folio's FIFO prefix.
* A harvest prefix stops at the first lot that is short-term, is inside a known exit-load window, or is not in the
  equity LTCG exemption pool.  FIFO means nothing behind such a lot can be reached without selling it.
* An unknown exit-load schedule makes a lot held ≤ ``UNKNOWN_LOAD_ABSTAIN_DAYS`` days abstain; older lots are assumed
  load-free and the result is flagged.
* Losses are never set off (the tax engine does not model set-off) and tax-loss harvesting is off until the 2025-Act
  set-off rows are verified.  A loss lot ahead of a gain lot is redeemed only because FIFO forces it; it earns no
  credit.
* NAVs are held at the ``as_of`` value for any later date (flagged ``NAV_HELD_CONSTANT``): no forecast is made.
"""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from iip.engine.costs import LoadTier, Lot, exit_load
from iip.engine.dates import add_months, days_between
from iip.engine.errors import InvalidInput, MissingData, RuleNotFound
from iip.engine.money import ONE, ZERO, D, engine_context, money, units_allotment
from iip.engine.tax import (
    CessRule,
    Disposal,
    GainType,
    RateKind,
    Regime,
    ResidentialStatus,
    SurchargeRule,
    TaxRule,
    TaxRuleSet,
    TransactionLevy,
    Verification,
    compute_levy,
    financial_year_start,
    select_dated,
    select_rule,
)

HARVEST_FORMULA_ID = "tax.ltcg_harvest@1"
WAIT_FORMULA_ID = "tax.lt_wait_modifier@1"
SALE_TAX_FORMULA_ID = "tax.sale_tax@1"

MF_INSTRUMENT_CLASS = "MUTUAL_FUND"
STT_RULE_ID = "STT-MF-01"
STAMP_RULE_ID = "STAMP-MF-01"

TAX_LOSS_HARVESTING_ENABLED = False  # off until set-off rows under the 2025 Act are verified (UF §4.3)
DEFAULT_WAIT_HORIZON_DAYS = 45  # PARAMETER (UF §4.3)
UNKNOWN_LOAD_ABSTAIN_DAYS = 365  # PARAMETER (PLAN A15): unknown exit load abstains for lots held ≤ this many days

F_WASH_SALE = "WASH_SALE_TREATMENT_NOT_VERIFIED"
F_ONE_DAY_OUT = "ONE_NAV_DAY_OUT_OF_MARKET"
F_OUTSIDE_WINDOW = "OUTSIDE_HARVEST_WINDOW"
F_LOAD_ASSUMED_ZERO = "EXIT_LOAD_ASSUMED_ZERO_AFTER_365_DAYS"
F_NAV_CONSTANT = "NAV_HELD_CONSTANT"
F_LOSS_NO_SETOFF = "LOSS_LOT_REDEEMED_NO_SET_OFF"
F_UNVERIFIED_RULE = "UNVERIFIED_TAX_ASSUMPTION"
F_NEXT_FY_POOL = "NEXT_FY_EXEMPTION_ASSUMED_USED"
F_NAV_DATE_DIFFERS = "NAV_DATE_DIFFERS_FROM_AS_OF"


class ActionStatus(StrEnum):
    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT VERIFIED"
    REQUIRES_CONFIGURATION = "REQUIRES CONFIGURATION"
    BLOCKED = "BLOCKED"


# --- inputs -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TaxLot:
    """One purchase lot inside a folio (from the CAS)."""

    lot_id: str
    acquisition_date: date
    units: Decimal
    cost_inr: Decimal

    def __post_init__(self) -> None:
        if D(self.units) <= 0:
            raise InvalidInput(f"lot {self.lot_id}: units must be > 0")
        if D(self.cost_inr) < 0:
            raise InvalidInput(f"lot {self.lot_id}: cost must be ≥ 0")


@dataclass(frozen=True, slots=True)
class FolioHolding:
    """One scheme+folio with its lots.  ``exit_load_schedule=None`` means the schedule is unknown; ``()`` means nil.

    ``domestic_equity_share``/``debt_share`` are the fractions the tax rules test (None = unknown → abstain where the
    outcome depends on them).
    """

    folio_id: str
    scheme_id: str
    nav: Decimal
    nav_date: date
    lots: tuple[TaxLot, ...]
    domestic_equity_share: Decimal | None
    debt_share: Decimal | None
    listed: bool | None = None
    is_elss: bool = False
    exit_load_schedule: tuple[LoadTier, ...] | None = None

    def __post_init__(self) -> None:
        if D(self.nav) <= 0:
            raise InvalidInput(f"folio {self.folio_id}: nav must be > 0")
        ids = [lot.lot_id for lot in self.lots]
        if len(ids) != len(set(ids)):
            raise InvalidInput(f"folio {self.folio_id}: duplicate lot ids")
        for share in (self.domestic_equity_share, self.debt_share):
            if share is not None and not ZERO <= share <= ONE:
                raise InvalidInput(f"folio {self.folio_id}: shares must be fractions in [0, 1]")

    def fifo_lots(self) -> tuple[TaxLot, ...]:
        """Oldest allotment first; same-date lots keep input order (stable sort)."""
        return tuple(sorted(self.lots, key=lambda lot: lot.acquisition_date))

    @property
    def units(self) -> Decimal:
        with engine_context():
            return sum((lot.units for lot in self.lots), ZERO)


@dataclass(frozen=True, slots=True)
class TaxContext:
    """The user's tax context (U-05).  ``None`` = unknown; the engine abstains where the answer depends on it."""

    regime: Regime | None
    residential_status: ResidentialStatus | None
    slab_rate: Decimal | None
    surcharge_rate: Decimal | None
    realised_ltcg_in_app_fy: Decimal = ZERO
    realised_ltcg_elsewhere_fy: Decimal | None = None
    harvest_already_done_fy: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class HarvestWindow:
    """Harvest window inside the financial year (PARAMETER; default 15-Feb to 31-Mar, UF §4.3)."""

    start_month: int = 2
    start_day: int = 15
    end_month: int = 3
    end_day: int = 31

    def __post_init__(self) -> None:
        for month, day in ((self.start_month, self.start_day), (self.end_month, self.end_day)):
            if not 1 <= month <= 12 or not 1 <= day <= calendar.monthrange(2001, month)[1]:  # non-leap reference year
                raise InvalidInput(f"invalid window day {day}/{month}")

    def window_for(self, on: date) -> tuple[date, date]:
        """The window inside the financial year that contains ``on``."""
        fy = financial_year_start(on)

        def in_fy(month: int, day: int) -> date:
            return date(fy.year if month >= 4 else fy.year + 1, month, day)

        start, end = in_fy(self.start_month, self.start_day), in_fy(self.end_month, self.end_day)
        if end < start:
            raise InvalidInput("harvest window end precedes its start inside the financial year")
        return start, end

    def contains(self, on: date) -> bool:
        start, end = self.window_for(on)
        return start <= on <= end


# --- results ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Abstention:
    code: str
    missing_input: str
    how_to_fix: str
    unlock_upper_bound_inr: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ConsumedLot:
    lot_id: str
    acquisition_date: date
    units: Decimal
    cost_inr: Decimal  # pro-rata share of the lot's cost (unrounded)
    proceeds_inr: Decimal  # units × NAV (unrounded)
    gain_inr: Decimal  # proceeds − cost (unrounded; may be negative)


@dataclass(frozen=True, slots=True)
class LotTaxLine:
    lot_id: str
    rule_id: str
    gain_type: GainType
    gain_inr: Decimal
    exempt_inr: Decimal
    taxable_inr: Decimal
    base_tax_inr: Decimal
    surcharge_inr: Decimal
    cess_inr: Decimal
    total_tax_inr: Decimal


@dataclass(frozen=True, slots=True)
class SaleTax:
    formula_id: str
    transfer_date: date
    lines: tuple[LotTaxLine, ...]
    total_tax_inr: Decimal
    pool_used_inr: Decimal
    rule_ids_used: tuple[str, ...]
    unverified_rule_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SaleCosts:
    exit_load_inr: Decimal
    stt_inr: Decimal
    stamp_duty_inr: Decimal  # on the re-investment (0 when there is none)
    rule_ids_used: tuple[str, ...]
    flags: tuple[str, ...]

    @property
    def total_inr(self) -> Decimal:
        with engine_context():
            return self.exit_load_inr + self.stt_inr + self.stamp_duty_inr


@dataclass(frozen=True, slots=True)
class HarvestStep:
    """Redeem ``units`` (the FIFO prefix in ``lots_consumed``) and re-invest the net proceeds in the same scheme."""

    folio_id: str
    scheme_id: str
    units: Decimal
    lots_consumed: tuple[ConsumedLot, ...]
    proceeds_inr: Decimal
    harvested_gain_inr: Decimal
    reinvest_amount_inr: Decimal
    costs: SaleCosts


@dataclass(frozen=True, slots=True)
class FolioNote:
    folio_id: str
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class LtcgHarvestResult:
    formula_id: str
    as_of: date
    status: ActionStatus
    abstentions: tuple[Abstention, ...]
    pool_total_inr: Decimal | None
    pool_left_before_inr: Decimal | None
    pool_left_after_inr: Decimal | None
    steps: tuple[HarvestStep, ...]
    harvested_gain_inr: Decimal
    tax_deferred_inr: Decimal
    in_window: bool
    deadline: date | None
    skipped: tuple[FolioNote, ...]
    rule_ids_used: tuple[str, ...]
    flags: tuple[str, ...]
    impact_basis: str = "TAX_DEFERRED"  # "tax deferred, not a gain": a re-buy resets the cost basis


@dataclass(frozen=True, slots=True)
class WaitModifier:
    """Selling now vs at ``wait_until`` (when the last of the soon-to-turn lots becomes long-term)."""

    formula_id: str
    folio_id: str
    as_of: date
    wait_until: date
    days_to_wait: int
    lots_turning_long_term: tuple[str, ...]
    tax_now_inr: Decimal
    tax_if_wait_inr: Decimal
    tax_avoided_inr: Decimal
    exit_load_now_inr: Decimal
    exit_load_if_wait_inr: Decimal
    rule_ids_used: tuple[str, ...]
    flags: tuple[str, ...]


# --- shared helpers (also used by regular_direct.py) --------------------------------------------------------------


def pool_left_for(ctx: TaxContext, annual_exemption_inr: Decimal) -> Decimal | None:
    """Exemption left this FY; ``None`` when gains realised outside the app are unknown."""
    if ctx.realised_ltcg_elsewhere_fy is None:
        return None
    with engine_context():
        used = ctx.realised_ltcg_in_app_fy + ctx.realised_ltcg_elsewhere_fy + ctx.harvest_already_done_fy
        return max(ZERO, annual_exemption_inr - used)


def check_modelled(ctx: TaxContext) -> Abstention | None:
    """Only resident individuals under the new regime are modelled (tax.py scope)."""
    if ctx.regime is None or ctx.residential_status is None:
        return Abstention(
            "TAX_REGIME_UNKNOWN",
            "tax regime and residential status",
            "Enter your tax regime and residential status in Settings → Tax.",
        )
    if ctx.regime is not Regime.NEW or ctx.residential_status is not ResidentialStatus.RESIDENT:
        return Abstention(
            "TAX_PROFILE_NOT_MODELLED",
            "a resident, new-regime tax profile",
            "Only resident individuals under the new regime are modelled; this action is not available.",
        )
    return None


def first_long_term_date(acquired: date, threshold_months: int) -> date:
    """The first transfer date classified LTCG: strictly after acquisition + N months (tax.classify_holding)."""
    return add_months(acquired, threshold_months) + timedelta(days=1)


def fifo_consume(folio: FolioHolding, units: Decimal, on: date) -> tuple[ConsumedLot, ...]:
    """The FIFO prefix that a redemption of ``units`` consumes, valued at the folio NAV."""
    want = D(units)
    if want <= 0:
        raise InvalidInput(f"units must be > 0, got {want}")
    out: list[ConsumedLot] = []
    with engine_context():
        if want > folio.units:
            raise InvalidInput(f"folio {folio.folio_id}: redeeming {want} units exceeds holdings {folio.units}")
        left = want
        for lot in folio.fifo_lots():
            if left == 0:
                break
            if lot.acquisition_date > on:
                raise InvalidInput(f"lot {lot.lot_id} acquired after {on}")
            take = min(left, lot.units)
            out.append(consume_lot(lot, take, folio.nav))
            left -= take
    return tuple(out)


def consume_lot(lot: TaxLot, take: Decimal, nav: Decimal) -> ConsumedLot:
    """``take`` units of ``lot`` valued at ``nav``, with a pro-rata share of the lot cost."""
    with engine_context():
        cost = lot.cost_inr if take == lot.units else lot.cost_inr * take / lot.units
        proceeds = take * nav
        return ConsumedLot(lot.lot_id, lot.acquisition_date, take, cost, proceeds, proceeds - cost)


def _disposal(folio: FolioHolding, c: ConsumedLot, transfer: date) -> Disposal:
    return Disposal(
        lot_id=c.lot_id,
        instrument_class=MF_INSTRUMENT_CLASS,
        transfer_date=transfer,
        gain_inr=c.gain_inr,
        acquisition_date=c.acquisition_date,
        listed=folio.listed,
        domestic_equity_share=folio.domestic_equity_share,
        debt_share=folio.debt_share,
    )


def rule_for(folio: FolioHolding, c: ConsumedLot, transfer: date, ruleset: TaxRuleSet) -> TaxRule:
    """The unique tax rule for this lot sold on ``transfer`` (raises RuleNotFound / MissingData / AmbiguousRule)."""
    return select_rule(ruleset, _disposal(folio, c, transfer))


def _surcharge_rule(ruleset: TaxRuleSet, fy_start: date, band: Decimal) -> SurchargeRule | None:
    if band == 0:
        return None
    rule = select_dated(ruleset.surcharges, fy_start, "surcharge")
    if band not in {b.rate for b in rule.bands}:
        raise InvalidInput(f"surcharge band {band} is not in {rule.rule_id}")
    return rule


def _rate_tax(rule: TaxRule, taxable: Decimal, ctx: TaxContext) -> Decimal:
    if rule.rate_kind is RateKind.EXEMPT:
        return ZERO
    if rule.rate_kind is RateKind.SPECIAL:
        if rule.rate is None:
            raise InvalidInput(f"rule {rule.rule_id} is SPECIAL without a rate")
        return taxable * rule.rate
    if ctx.slab_rate is None:
        raise MissingData(f"rule {rule.rule_id} is slab-taxed and the slab rate is unknown")
    return taxable * ctx.slab_rate


def _loaded(
    base: Decimal,
    rule: TaxRule,
    band: Decimal,
    surcharge_rule: SurchargeRule | None,
    cess_rule: CessRule,
) -> tuple[Decimal, Decimal]:
    """(surcharge, cess) on ``base`` tax, with the special-rate surcharge cap from the rule table."""
    s_rate = band
    if (
        surcharge_rule is not None
        and rule.rate_kind is RateKind.SPECIAL
        and rule.section in surcharge_rule.capped_sections
    ):
        s_rate = min(band, surcharge_rule.special_rate_cap)
    surcharge = base * s_rate
    return surcharge, (base + surcharge) * cess_rule.rate


def tax_on_sale(
    folio: FolioHolding,
    consumed: Sequence[ConsumedLot],
    transfer: date,
    ruleset: TaxRuleSet,
    ctx: TaxContext,
    pool_left_inr: Decimal,
) -> SaleTax:
    """Tax on selling ``consumed`` on ``transfer``, using ``pool_left_inr`` of the equity LTCG exemption FIFO.

    Raises ``MissingData`` (slab or surcharge band unknown, tax facts missing), ``RuleNotFound`` (not modelled,
    grandfathered lot, beyond rule-table coverage) or ``InvalidInput``.  Positive gains only; losses earn no credit.
    """
    if (abst := check_modelled(ctx)) is not None:
        raise RuleNotFound(abst.code)
    fy_start = financial_year_start(transfer)
    lines: list[LotTaxLine] = []
    used: list[str] = []
    pool = D(pool_left_inr)
    with engine_context():
        start_pool = pool
        rows: list[tuple[ConsumedLot, TaxRule, Decimal, Decimal, Decimal]] = []  # lot, rule, exempt, taxable, base
        for c in consumed:
            rule = rule_for(folio, c, transfer, ruleset)
            positive = max(c.gain_inr, ZERO)
            exempt = ZERO
            if rule.exemption_scope is not None and rule.rate_kind is not RateKind.EXEMPT:
                exempt = min(positive, pool)
                pool -= exempt
            taxable = ZERO if rule.rate_kind is RateKind.EXEMPT else positive - exempt
            rows.append((c, rule, exempt, taxable, _rate_tax(rule, taxable, ctx)))
            used.append(rule.rule_id)
        surcharge_rule: SurchargeRule | None = None
        cess_rule: CessRule | None = None
        band = ZERO
        if any(base > 0 for *_, base in rows):
            if ctx.surcharge_rate is None:
                raise MissingData("surcharge band unknown")
            band = D(ctx.surcharge_rate)
            surcharge_rule = _surcharge_rule(ruleset, fy_start, band)
            cess_rule = select_dated(ruleset.cess, fy_start, "cess")
            used.extend(r.rule_id for r in (surcharge_rule, cess_rule) if r is not None)
        for c, rule, exempt, taxable, base in rows:
            surcharge, cess = ZERO, ZERO
            if base > 0 and cess_rule is not None:
                surcharge, cess = _loaded(base, rule, band, surcharge_rule, cess_rule)
            lines.append(
                LotTaxLine(
                    lot_id=c.lot_id,
                    rule_id=rule.rule_id,
                    gain_type=rule.gain_type,
                    gain_inr=money(c.gain_inr),
                    exempt_inr=money(exempt),
                    taxable_inr=money(taxable),
                    base_tax_inr=money(base),
                    surcharge_inr=money(surcharge),
                    cess_inr=money(cess),
                    total_tax_inr=money(base + surcharge + cess),
                )
            )
        total = sum((ln.total_tax_inr for ln in lines), ZERO)
        ids = tuple(dict.fromkeys(used))
        status = ruleset.status_by_rule_id()
        return SaleTax(
            formula_id=SALE_TAX_FORMULA_ID,
            transfer_date=transfer,
            lines=tuple(lines),
            total_tax_inr=money(total),
            pool_used_inr=start_pool - pool,
            rule_ids_used=ids,
            unverified_rule_ids=tuple(r for r in ids if status[r] is Verification.NV),
        )


def _levy(ruleset: TaxRuleSet, rule_id: str, on: date) -> TransactionLevy:
    return select_dated((lv for lv in ruleset.levies if lv.rule_id == rule_id), on, rule_id)


def sale_costs(
    folio: FolioHolding,
    consumed: Sequence[ConsumedLot],
    transfer: date,
    ruleset: TaxRuleSet,
    *,
    reinvest: bool,
    equity_oriented: bool,
) -> SaleCosts:
    """Exit load (FIFO, scheme schedule), STT on an equity-oriented redemption, stamp duty on a re-investment.

    Unknown schedule: raises ``MissingData`` if any consumed lot is held ≤ ``UNKNOWN_LOAD_ABSTAIN_DAYS`` days on
    ``transfer``; otherwise the load is taken as zero and flagged.
    """
    flags: list[str] = []
    used: list[str] = []
    with engine_context():
        proceeds = sum((c.proceeds_inr for c in consumed), ZERO)
        units = sum((c.units for c in consumed), ZERO)
        if folio.exit_load_schedule is None:
            young = [
                c.lot_id for c in consumed if days_between(c.acquisition_date, transfer) <= UNKNOWN_LOAD_ABSTAIN_DAYS
            ]
            if young:
                raise MissingData(f"folio {folio.folio_id}: exit-load schedule unknown for lots {young}")
            load = ZERO
            flags.append(F_LOAD_ASSUMED_ZERO)
        else:
            lots = [Lot(c.acquisition_date, c.units) for c in consumed]
            load = exit_load(lots, units, transfer, folio.nav, folio.exit_load_schedule).load
        stt = ZERO
        if equity_oriented:
            stt_levy = _levy(ruleset, STT_RULE_ID, transfer)
            stt = compute_levy(stt_levy, proceeds, transfer).value_inr
            used.append(stt_levy.rule_id)
        stamp = ZERO
        if reinvest:
            stamp_levy = _levy(ruleset, STAMP_RULE_ID, transfer)
            stamp = compute_levy(stamp_levy, proceeds - load - stt, transfer, inclusive=True).value_inr
            used.append(stamp_levy.rule_id)
        return SaleCosts(money(load), money(stt), money(stamp), tuple(used), tuple(flags))


def is_equity_pool_rule(rule: TaxRule) -> bool:
    """A long-term rule that shares the annual equity LTCG exemption (rule-table driven, no literals)."""
    return (
        rule.gain_type is GainType.LTCG
        and rule.exemption_scope is not None
        and rule.annual_exemption_inr is not None
        and rule.rate_kind is RateKind.SPECIAL
    )


# --- LTCG harvest -------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Prefix:
    folio: FolioHolding
    lots: tuple[TaxLot, ...]
    rule: TaxRule
    gain_per_rupee: Decimal


def _harvest_prefix(folio: FolioHolding, ruleset: TaxRuleSet, as_of: date, flags: list[str]) -> _Prefix | FolioNote:
    """The folio's harvestable FIFO prefix, or the reason it has none."""
    lots: list[TaxLot] = []
    pool_rule: TaxRule | None = None
    for lot in folio.fifo_lots():
        c = consume_lot(lot, lot.units, folio.nav)
        try:
            rule = rule_for(folio, c, as_of, ruleset)
        except (RuleNotFound, MissingData) as exc:
            return FolioNote(
                folio.folio_id, "TAX_RULE_NOT_FOUND" if isinstance(exc, RuleNotFound) else "TAX_FACTS_MISSING", str(exc)
            )
        if rule.gain_type is not GainType.LTCG and rule.holding_threshold_months is not None:
            break  # first short-term lot: FIFO blocks everything behind it
        if not is_equity_pool_rule(rule):
            return FolioNote(folio.folio_id, "NOT_EQUITY_LTCG_POOL", f"rule {rule.rule_id} has no equity exemption")
        held = days_between(lot.acquisition_date, as_of)
        if folio.exit_load_schedule is None:
            if held <= UNKNOWN_LOAD_ABSTAIN_DAYS:
                return FolioNote(folio.folio_id, "EXIT_LOAD_UNKNOWN", f"lot {lot.lot_id} held {held} days")
            flags.append(F_LOAD_ASSUMED_ZERO)
        elif any(held <= t.window_days and D(t.rate) > 0 for t in folio.exit_load_schedule):
            break  # inside a load window: stop the prefix
        lots.append(lot)
        pool_rule = rule
    if pool_rule is None:
        return FolioNote(folio.folio_id, "NO_LONG_TERM_PREFIX", "the oldest lot is short-term or inside a load window")
    with engine_context():
        consumed = [consume_lot(lot, lot.units, folio.nav) for lot in lots]
        gain = sum((max(c.gain_inr, ZERO) for c in consumed), ZERO)
        if gain <= 0:
            return FolioNote(folio.folio_id, "NO_POSITIVE_LONG_TERM_GAIN", "tax-loss harvesting is off")
        proceeds = sum((c.proceeds_inr for c in consumed), ZERO)
        return _Prefix(folio, tuple(lots), pool_rule, gain / proceeds)


def _take_from_prefix(p: _Prefix, pool: Decimal, flags: list[str]) -> tuple[tuple[ConsumedLot, ...], Decimal]:
    """FIFO-take lots from the prefix until ``pool`` is used; the last lot may be partial (units truncated)."""
    taken: list[ConsumedLot] = []
    with engine_context():
        left = pool
        for lot in p.lots:
            if left <= 0:
                break
            full = consume_lot(lot, lot.units, p.folio.nav)
            if full.gain_inr <= 0:
                taken.append(full)  # FIFO forces it; no credit (losses are not set off)
                flags.append(F_LOSS_NO_SETOFF)
                continue
            if full.gain_inr <= left:
                taken.append(full)
                left -= full.gain_inr
                continue
            units = min(lot.units, units_allotment(left / (full.gain_inr / lot.units)))
            if units > 0:
                part = consume_lot(lot, units, p.folio.nav)
                taken.append(part)
                left -= part.gain_inr
            break
        while taken and taken[-1].gain_inr <= 0:
            taken.pop()  # never end a step on a loss lot that buys nothing
        gain = sum((max(c.gain_inr, ZERO) for c in taken), ZERO)
    return tuple(taken), gain


def _deferred_tax(
    gain: Decimal, rule: TaxRule, ctx: TaxContext, ruleset: TaxRuleSet, as_of: date
) -> tuple[Decimal, list[str]]:
    """Tax the harvested gain would bear later without the exemption: gain × rate × (1 + surcharge) × (1 + cess)."""
    fy_start = financial_year_start(as_of)
    band = D(ctx.surcharge_rate) if ctx.surcharge_rate is not None else ZERO
    surcharge_rule = _surcharge_rule(ruleset, fy_start, band)
    cess_rule = select_dated(ruleset.cess, fy_start, "cess")
    with engine_context():
        base = _rate_tax(rule, gain, ctx)
        surcharge, cess = _loaded(base, rule, band, surcharge_rule, cess_rule)
        used = [rule.rule_id, cess_rule.rule_id, *([surcharge_rule.rule_id] if surcharge_rule else [])]
        return money(base + surcharge + cess), used


def _scan(
    folios: Sequence[FolioHolding], ruleset: TaxRuleSet, as_of: date, flags: list[str]
) -> tuple[list[_Prefix], list[FolioNote]]:
    """Each folio's harvestable FIFO prefix, or the reason it has none (ELSS, short-term, non-equity, abstain)."""
    skipped: list[FolioNote] = []
    prefixes: list[_Prefix] = []
    for folio in sorted(folios, key=lambda f: f.folio_id):
        if folio.nav_date != as_of:
            flags.append(F_NAV_DATE_DIFFERS)
        if folio.is_elss:
            skipped.append(FolioNote(folio.folio_id, "ELSS_EXCLUDED", "a re-buy restarts the 3-year lock-in"))
            continue
        p = _harvest_prefix(folio, ruleset, as_of, flags)
        if isinstance(p, FolioNote):
            skipped.append(p)
        else:
            prefixes.append(p)
    return prefixes, skipped


def _harvest_empty(
    as_of: date,
    window: HarvestWindow,
    *,
    status: ActionStatus,
    abstentions: tuple[Abstention, ...] = (),
    pool_total: Decimal | None = None,
    skipped: Sequence[FolioNote] = (),
    flags: Sequence[str] = (),
) -> LtcgHarvestResult:
    return LtcgHarvestResult(
        formula_id=HARVEST_FORMULA_ID,
        as_of=as_of,
        status=status,
        abstentions=abstentions,
        pool_total_inr=pool_total,
        pool_left_before_inr=None,
        pool_left_after_inr=None,
        steps=(),
        harvested_gain_inr=money(ZERO),
        tax_deferred_inr=money(ZERO),
        in_window=window.contains(as_of),
        deadline=None,
        skipped=tuple(skipped),
        rule_ids_used=(),
        flags=tuple(dict.fromkeys(flags)),
    )


def ltcg_harvest(
    folios: Sequence[FolioHolding],
    ctx: TaxContext,
    ruleset: TaxRuleSet,
    *,
    as_of: date,
    window: HarvestWindow | None = None,
) -> LtcgHarvestResult:
    """``tax.ltcg_harvest@1``: use the unused equity LTCG exemption by redeeming and re-investing long-term lots.

    Greedy over folios by (gain per ₹ redeemed desc, folio id); inside a folio the FIFO prefix only.  Outside the
    window the result is a notice (``in_window=False``, no deadline).  The exemption amount and every rate come from
    the rule row that taxes the harvested lots.
    """
    window = window or HarvestWindow()
    if (abst := check_modelled(ctx)) is not None:
        status = (
            ActionStatus.BLOCKED if abst.code == "TAX_PROFILE_NOT_MODELLED" else ActionStatus.REQUIRES_CONFIGURATION
        )
        return _harvest_empty(as_of, window, status=status, abstentions=(abst,))
    flags: list[str] = []
    prefixes, skipped = _scan(folios, ruleset, as_of, flags)
    if not prefixes:  # nothing harvestable: a valid "no action" result, not an abstention
        return _harvest_empty(as_of, window, status=ActionStatus.NOT_VERIFIED, skipped=skipped, flags=flags)
    pool_rule = prefixes[0].rule
    pool_total = pool_rule.annual_exemption_inr
    if pool_total is None:  # pragma: no cover - is_equity_pool_rule guarantees it
        raise InvalidInput(f"rule {pool_rule.rule_id} has no annual exemption")
    pool = pool_left_for(ctx, pool_total)
    if pool is None:
        with engine_context():
            bound = money(pool_total * (pool_rule.rate or ZERO))
        abst = Abstention(
            "LTCG_ELSEWHERE_UNKNOWN",
            "long-term equity gains realised outside the app this financial year",
            "Enter gains already realised elsewhere this year (0 if none).",
            bound,
        )
        return _harvest_empty(
            as_of, window, status=ActionStatus.REQUIRES_CONFIGURATION, abstentions=(abst,), pool_total=pool_total
        )
    if ctx.surcharge_rate is None:
        abst = Abstention("SURCHARGE_BAND_UNKNOWN", "surcharge band", "Enter your surcharge band (0 if none).")
        return _harvest_empty(
            as_of, window, status=ActionStatus.REQUIRES_CONFIGURATION, abstentions=(abst,), pool_total=pool_total
        )
    return _harvest(prefixes, skipped, flags, ctx, ruleset, as_of, window, pool_rule, pool)


def _harvest(
    prefixes: list[_Prefix],
    skipped: list[FolioNote],
    flags: list[str],
    ctx: TaxContext,
    ruleset: TaxRuleSet,
    as_of: date,
    window: HarvestWindow,
    pool_rule: TaxRule,
    pool: Decimal,
) -> LtcgHarvestResult:
    flags = [F_WASH_SALE, F_ONE_DAY_OUT, *flags]
    prefixes.sort(key=lambda p: (-p.gain_per_rupee, p.folio.folio_id))
    steps: list[HarvestStep] = []
    used: list[str] = []
    left = pool
    with engine_context():
        for p in prefixes:
            if left <= 0:
                break
            taken, gain = _take_from_prefix(p, left, flags)
            if not taken or gain <= 0:
                continue
            costs = sale_costs(p.folio, taken, as_of, ruleset, reinvest=True, equity_oriented=True)
            flags.extend(costs.flags)
            used.extend(costs.rule_ids_used)
            proceeds = sum((c.proceeds_inr for c in taken), ZERO)
            steps.append(
                HarvestStep(
                    folio_id=p.folio.folio_id,
                    scheme_id=p.folio.scheme_id,
                    units=sum((c.units for c in taken), ZERO),
                    lots_consumed=taken,
                    proceeds_inr=money(proceeds),
                    harvested_gain_inr=money(gain),
                    reinvest_amount_inr=money(proceeds - costs.exit_load_inr - costs.stt_inr),
                    costs=costs,
                )
            )
            left -= gain
        harvested = sum((max(c.gain_inr, ZERO) for s in steps for c in s.lots_consumed), ZERO)
    deferred, tax_ids = _deferred_tax(harvested, pool_rule, ctx, ruleset, as_of) if steps else (money(ZERO), [])
    ids = tuple(dict.fromkeys([*tax_ids, *used]))
    status_by_id = ruleset.status_by_rule_id()
    if any(status_by_id[r] is Verification.NV for r in ids):
        flags.append(F_UNVERIFIED_RULE)
    in_window = window.contains(as_of)
    if not in_window:
        flags.append(F_OUTSIDE_WINDOW)
    return LtcgHarvestResult(
        formula_id=HARVEST_FORMULA_ID,
        as_of=as_of,
        status=ActionStatus.NOT_VERIFIED,
        abstentions=(),
        pool_total_inr=pool_rule.annual_exemption_inr,
        pool_left_before_inr=money(pool),
        pool_left_after_inr=money(max(ZERO, pool - harvested)),
        steps=tuple(steps),
        harvested_gain_inr=money(harvested),
        tax_deferred_inr=deferred,
        in_window=in_window,
        deadline=window.window_for(as_of)[1] if in_window else None,
        skipped=tuple(skipped),
        rule_ids_used=ids,
        flags=tuple(dict.fromkeys(flags)),
    )


# --- "lot turns long-term within 45 days → wait" modifier --------------------------------------------------------


def pool_on(transfer: date, as_of: date, pool_left_inr: Decimal, flags: list[str]) -> Decimal:
    """The pool usable on ``transfer``: this FY's ``pool_left``; a later FY is assumed fully used (conservative)."""
    if financial_year_start(transfer) == financial_year_start(as_of):
        return pool_left_inr
    flags.append(F_NEXT_FY_POOL)
    return ZERO


def lt_wait_modifier(
    folio: FolioHolding,
    units: Decimal,
    ctx: TaxContext,
    ruleset: TaxRuleSet,
    *,
    as_of: date,
    pool_left_inr: Decimal,
    horizon_days: int = DEFAULT_WAIT_HORIZON_DAYS,
) -> WaitModifier | None:
    """Applied to any card that sells ``units`` of ``folio``: if a consumed short-term lot turns long-term within
    ``horizon_days``, compare selling now with selling on the day the last such lot turns long-term.

    Returns ``None`` when no consumed lot turns long-term inside the horizon, or waiting saves nothing.  Raises the
    tax engine's ``MissingData`` / ``RuleNotFound`` when the comparison cannot be made (the caller abstains).
    """
    if horizon_days < 0:
        raise InvalidInput("horizon_days must be ≥ 0")
    consumed = fifo_consume(folio, units, as_of)
    turning: list[tuple[str, date]] = []
    for c in consumed:
        rule = rule_for(folio, c, as_of, ruleset)
        if rule.gain_type is not GainType.STCG or rule.holding_threshold_months is None:
            continue  # already long-term, or no holding test (e.g. debt specified-MF units)
        lt_day = first_long_term_date(c.acquisition_date, rule.holding_threshold_months)
        if days_between(as_of, lt_day) <= horizon_days:
            turning.append((c.lot_id, lt_day))
    if not turning:
        return None
    wait_until = max(d for _, d in turning)
    flags: list[str] = [F_NAV_CONSTANT]
    now = tax_on_sale(folio, consumed, as_of, ruleset, ctx, pool_left_inr)
    later = tax_on_sale(folio, consumed, wait_until, ruleset, ctx, pool_on(wait_until, as_of, pool_left_inr, flags))
    load_now = sale_costs(folio, consumed, as_of, ruleset, reinvest=False, equity_oriented=False)
    load_later = sale_costs(folio, consumed, wait_until, ruleset, reinvest=False, equity_oriented=False)
    with engine_context():
        avoided = now.total_tax_inr - later.total_tax_inr
    if avoided <= 0 and load_now.exit_load_inr <= load_later.exit_load_inr:
        return None
    return WaitModifier(
        formula_id=WAIT_FORMULA_ID,
        folio_id=folio.folio_id,
        as_of=as_of,
        wait_until=wait_until,
        days_to_wait=days_between(as_of, wait_until),
        lots_turning_long_term=tuple(lot_id for lot_id, _ in turning),
        tax_now_inr=now.total_tax_inr,
        tax_if_wait_inr=later.total_tax_inr,
        tax_avoided_inr=money(avoided),
        exit_load_now_inr=load_now.exit_load_inr,
        exit_load_if_wait_inr=load_later.exit_load_inr,
        rule_ids_used=tuple(dict.fromkeys([*now.rule_ids_used, *later.rule_ids_used])),
        flags=tuple(dict.fromkeys([*flags, *load_now.flags, *load_later.flags])),
    )
