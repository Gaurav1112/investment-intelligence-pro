"""Regular → Direct switch, ``cost.reg_to_direct@1``, with the cost gap measured from AMFI NAVs of both plans.

Sources: design-risk-first.md §5.8, grafted per design-judgement.md §2.1 item 3:
* the realised cost gap from both plans' NAVs (design-user-first.md §4.4), so no TER/BER input is needed:
  ``g_12m = ln(NAV_dir(t)/NAV_dir(t−365d)) − ln(NAV_reg(t)/NAV_reg(t−365d))``; ``annual_saving = V_reg × (e^g − 1)``;
* the "wait" timing as an argmin over lot-transition dates (design-evidence-first.md P2):
  ``C_d = switch_cost(d) + annual_saving × (d − today)/365`` over ``d ∈ {today} ∪ {dates within 13 months when a FIFO
  lot turns long-term or leaves its exit-load window}``;
* options in the order (d) redirect the SIP to Direct (free, always first), (b) switch only long-term lots inside the
  unused exemption, (c) wait until the argmin date, (a) switch everything now.
``breakeven_months = 12 × switch_cost / annual_saving`` (first-order, research-evidence-mf.md §4.2).

The gap is a past cost fact, not a forecast: both plans hold the same portfolio, so the difference is a pure cost
transfer.  Pure: Decimal only, no clock, no IO; NAVs for later dates are held at today's value (flagged).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from iip.engine.actions.tax_actions import (
    F_NAV_CONSTANT,
    Abstention,
    ActionStatus,
    ConsumedLot,
    FolioHolding,
    LotTaxLine,
    TaxContext,
    TaxLot,
    check_modelled,
    consume_lot,
    fifo_consume,
    first_long_term_date,
    is_equity_pool_rule,
    pool_left_for,
    pool_on,
    rule_for,
    sale_costs,
    tax_on_sale,
)
from iip.engine.dates import BusinessCalendar, add_months, days_between
from iip.engine.errors import InvalidInput, MissingData, RuleNotFound
from iip.engine.money import ONE, ZERO, D, engine_context, money, quantize, units_allotment
from iip.engine.tax import GainType, TaxRule, TaxRuleSet, Verification

REG_TO_DIRECT_FORMULA_ID = "cost.reg_to_direct@1"
NAV_GAP_FORMULA_ID = "cost.reg_to_direct.nav_gap@1"

GAP_LOOKBACK_DAYS = 365  # UF §4.4
DEFAULT_NAV_TOLERANCE_BUSINESS_DAYS = 3  # UF §4.4: both NAVs must exist within ± 3 business days, else abstain
DEFAULT_WAIT_HORIZON_MONTHS = 13  # EF P2: lot-transition dates within 13 months
MONTHS_QUANTUM = Decimal("0.01")

F_WAIT_NOT_CHEAPER = "WAIT_NOT_CHEAPER"
F_BEYOND_COVERAGE = "WAIT_CANDIDATE_BEYOND_RULE_COVERAGE"
F_EXEMPTION_ASSUMED_USED = "EXEMPTION_ASSUMED_USED"
F_PLAN_SWITCH_LOAD = "PLAN_SWITCH_LOAD_VARIES_BY_AMC"  # REQUIRES CONFIGURATION per scheme (EF P2)
F_UNVERIFIED_RULE = "UNVERIFIED_TAX_ASSUMPTION"
F_NO_LT_IN_POOL = "NO_LONG_TERM_LOTS_INSIDE_EXEMPTION"

_WEEKENDS = BusinessCalendar("weekends-only", frozenset())


# --- inputs -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NavPoint:
    on: date
    nav: Decimal

    def __post_init__(self) -> None:
        if D(self.nav) <= 0:
            raise InvalidInput(f"NAV on {self.on} must be > 0")


@dataclass(frozen=True, slots=True)
class PlanPair:
    """A Regular plan and its Direct sibling (same scheme, same option).  ``sibling_match_unique`` is decided by the
    caller from the scheme master; anything but a unique match abstains."""

    regular_scheme_id: str
    direct_scheme_id: str | None
    sibling_match_unique: bool
    regular_navs: tuple[NavPoint, ...]
    direct_navs: tuple[NavPoint, ...]


# --- results ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NavGap:
    formula_id: str
    t: date
    t0: date
    nav_reg_t: Decimal
    nav_reg_t0: Decimal
    nav_dir_t: Decimal
    nav_dir_t0: Decimal
    g_12m: Decimal  # log-return difference, Direct minus Regular
    annual_cost_gap: Decimal  # e^g − 1, a fraction per year


@dataclass(frozen=True, slots=True)
class SwitchOption:
    option_id: str  # "d" | "b" | "c" | "a"
    verb: str  # REDIRECT_SIP | SWITCH | WAIT_UNTIL
    switch_date: date | None
    units: Decimal
    amount_inr: Decimal | None  # SIP amount for (d) when known
    lots_consumed: tuple[ConsumedLot, ...]
    tax_lines: tuple[LotTaxLine, ...]
    exit_load_inr: Decimal
    tax_inr: Decimal
    stt_inr: Decimal
    stamp_duty_inr: Decimal
    switch_cost_inr: Decimal
    forgone_saving_inr: Decimal
    total_cost_inr: Decimal
    breakeven_months: Decimal | None


@dataclass(frozen=True, slots=True)
class RegularToDirectResult:
    formula_id: str
    as_of: date
    folio_id: str
    regular_scheme_id: str
    direct_scheme_id: str | None
    status: ActionStatus
    abstentions: tuple[Abstention, ...]
    nav_gap: NavGap | None
    holding_value_inr: Decimal
    annual_saving_inr: Decimal | None
    options: tuple[SwitchOption, ...]
    recommended_timing: str | None  # "a" or "c" for the full switch
    rule_ids_used: tuple[str, ...]
    flags: tuple[str, ...]
    impact_basis: str = "ANNUAL_COST_SAVED"


# --- NAV-measured gap ---------------------------------------------------------------------------------------------


def _business_days_after(found: date, target: date, cal: BusinessCalendar) -> int:
    """Business days in (found, target]."""
    n, cur = 0, found
    while cur < target:
        cur += timedelta(days=1)
        if cal.is_business_day(cur):
            n += 1
    return n


def _common_on_or_before(
    common: dict[date, tuple[Decimal, Decimal]], target: date, tolerance: int, cal: BusinessCalendar
) -> date | None:
    eligible = [d for d in common if d <= target]
    if not eligible:
        return None
    best = max(eligible)
    return best if _business_days_after(best, target, cal) <= tolerance else None


def measure_nav_gap(
    pair: PlanPair,
    as_of: date,
    *,
    calendar: BusinessCalendar | None = None,
    tolerance_business_days: int = DEFAULT_NAV_TOLERANCE_BUSINESS_DAYS,
) -> NavGap | Abstention:
    """The realised 12-month cost gap from both plans' NAVs on the same two dates, or why it cannot be measured."""
    cal = calendar or _WEEKENDS
    reg = {p.on: p.nav for p in pair.regular_navs}
    dirn = {p.on: p.nav for p in pair.direct_navs}
    common = {d: (reg[d], dirn[d]) for d in reg.keys() & dirn.keys()}
    target0 = as_of - timedelta(days=GAP_LOOKBACK_DAYS)
    if not common or min(common) > target0:
        return Abstention(
            "INSUFFICIENT_HISTORY",
            "365 days of NAVs for both plans",
            "Wait until both plans have a year of NAV history in the app.",
        )
    t = _common_on_or_before(common, as_of, tolerance_business_days, cal)
    t0 = _common_on_or_before(common, target0, tolerance_business_days, cal)
    if t is None or t0 is None:
        return Abstention(
            "NAV_MISSING_NEAR_DATE",
            f"NAVs of both plans within {tolerance_business_days} business days of {as_of} and {target0}",
            "Refresh NAV history for both plans.",
        )
    (r_t, d_t), (r_0, d_0) = common[t], common[t0]
    with engine_context():
        g = (d_t / d_0).ln() - (r_t / r_0).ln()
        gap = g.exp() - ONE
    return NavGap(NAV_GAP_FORMULA_ID, t, t0, r_t, r_0, d_t, d_0, g, gap)


# --- switch cost on a date ----------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Cost:
    on: date
    consumed: tuple[ConsumedLot, ...]
    tax_lines: tuple[LotTaxLine, ...]
    tax: Decimal
    exit_load: Decimal
    stt: Decimal
    stamp: Decimal
    rule_ids: tuple[str, ...]
    flags: tuple[str, ...]

    @property
    def switch_cost(self) -> Decimal:
        with engine_context():
            return self.tax + self.exit_load + self.stt + self.stamp


def _cost_on(
    folio: FolioHolding,
    consumed: tuple[ConsumedLot, ...],
    on: date,
    as_of: date,
    ruleset: TaxRuleSet,
    ctx: TaxContext,
    pool: Decimal,
    equity: bool,
) -> _Cost:
    flags: list[str] = []
    tax = tax_on_sale(folio, consumed, on, ruleset, ctx, pool_on(on, as_of, pool, flags))
    costs = sale_costs(folio, consumed, on, ruleset, reinvest=True, equity_oriented=equity)
    return _Cost(
        on=on,
        consumed=consumed,
        tax_lines=tax.lines,
        tax=tax.total_tax_inr,
        exit_load=costs.exit_load_inr,
        stt=costs.stt_inr,
        stamp=costs.stamp_duty_inr,
        rule_ids=(*tax.rule_ids_used, *costs.rule_ids_used),
        flags=(*flags, *costs.flags),
    )


def _breakeven(cost: Decimal, saving: Decimal) -> Decimal:
    with engine_context():
        return quantize(Decimal(12) * cost / saving, MONTHS_QUANTUM, ROUND_HALF_EVEN)


def _option(oid: str, verb: str, c: _Cost, saving: Decimal, as_of: date) -> SwitchOption:
    with engine_context():
        forgone = saving * Decimal(days_between(as_of, c.on)) / Decimal(365)
        units = sum((x.units for x in c.consumed), ZERO)
        return SwitchOption(
            option_id=oid,
            verb=verb,
            switch_date=c.on,
            units=units,
            amount_inr=None,
            lots_consumed=c.consumed,
            tax_lines=c.tax_lines,
            exit_load_inr=c.exit_load,
            tax_inr=c.tax,
            stt_inr=c.stt,
            stamp_duty_inr=c.stamp,
            switch_cost_inr=money(c.switch_cost),
            forgone_saving_inr=money(forgone),
            total_cost_inr=money(c.switch_cost + forgone),
            breakeven_months=_breakeven(c.switch_cost, saving),
        )


def _redirect_sip(sip_amount: Decimal | None) -> SwitchOption:
    zero = money(ZERO)
    return SwitchOption(
        option_id="d",
        verb="REDIRECT_SIP",
        switch_date=None,
        units=ZERO,
        amount_inr=sip_amount,
        lots_consumed=(),
        tax_lines=(),
        exit_load_inr=zero,
        tax_inr=zero,
        stt_inr=zero,
        stamp_duty_inr=zero,
        switch_cost_inr=zero,
        forgone_saving_inr=zero,
        total_cost_inr=zero,
        breakeven_months=None,
    )


# --- option (b): long-term lots inside the exemption --------------------------------------------------------------


def _lt_prefix_in_pool(folio: FolioHolding, ruleset: TaxRuleSet, as_of: date, pool: Decimal) -> tuple[ConsumedLot, ...]:
    """FIFO prefix of long-term, load-free lots whose positive gain fits the pool (last lot may be partial)."""
    taken: list[ConsumedLot] = []
    with engine_context():
        left = pool
        for lot in folio.fifo_lots():
            if left <= 0:
                break
            full = consume_lot(lot, lot.units, folio.nav)
            rule = rule_for(folio, full, as_of, ruleset)
            if (
                rule.gain_type is not GainType.LTCG
                or not is_equity_pool_rule(rule)
                or _in_load_window(folio, lot, as_of)
            ):
                break
            gain = max(full.gain_inr, ZERO)
            if gain <= left:
                taken.append(full)
                left -= gain
                continue
            units = min(lot.units, units_allotment(left / (gain / lot.units)))
            if units > 0:
                taken.append(consume_lot(lot, units, folio.nav))
            break
    return tuple(taken)


def _in_load_window(folio: FolioHolding, lot: TaxLot, on: date) -> bool:
    if folio.exit_load_schedule is None:
        return False  # sale_costs abstains or flags; nothing to stop on here
    held = days_between(lot.acquisition_date, on)
    return any(held <= t.window_days and D(t.rate) > 0 for t in folio.exit_load_schedule)


# --- option (c): candidate dates ----------------------------------------------------------------------------------


def _candidate_dates(folio: FolioHolding, ruleset: TaxRuleSet, as_of: date, horizon_months: int) -> list[date]:
    """Dates within the horizon when a FIFO lot turns long-term or leaves an exit-load window (or the 365-day
    unknown-load threshold)."""
    end = add_months(as_of, horizon_months)
    out: set[date] = set()
    for lot in folio.lots:
        rule = rule_for(folio, consume_lot(lot, lot.units, folio.nav), as_of, ruleset)
        if rule.gain_type is GainType.STCG and rule.holding_threshold_months is not None:
            out.add(first_long_term_date(lot.acquisition_date, rule.holding_threshold_months))
        windows = [365] if folio.exit_load_schedule is None else [t.window_days for t in folio.exit_load_schedule]
        out.update(lot.acquisition_date + timedelta(days=w + 1) for w in windows)
    return sorted(d for d in out if as_of < d <= end)


def _best_wait(
    folio: FolioHolding,
    consumed: tuple[ConsumedLot, ...],
    ruleset: TaxRuleSet,
    ctx: TaxContext,
    as_of: date,
    pool: Decimal,
    equity: bool,
    saving: Decimal,
    horizon_months: int,
    flags: list[str],
) -> _Cost | None:
    best: tuple[Decimal, _Cost] | None = None
    for d in _candidate_dates(folio, ruleset, as_of, horizon_months):
        try:
            c = _cost_on(folio, consumed, d, as_of, ruleset, ctx, pool, equity)
        except RuleNotFound:
            flags.append(F_BEYOND_COVERAGE)
            continue
        except MissingData:
            continue  # e.g. a lot still inside the unknown-load threshold on d
        with engine_context():
            total = c.switch_cost + saving * Decimal(days_between(as_of, d)) / Decimal(365)
        if best is None or total < best[0]:
            best = (total, c)
    return None if best is None else best[1]


# --- entry point --------------------------------------------------------------------------------------------------


def _result(
    folio: FolioHolding,
    pair: PlanPair,
    as_of: date,
    *,
    status: ActionStatus,
    abstentions: Sequence[Abstention] = (),
    gap: NavGap | None = None,
    saving: Decimal | None = None,
    options: Sequence[SwitchOption] = (),
    recommended: str | None = None,
    rule_ids: Sequence[str] = (),
    flags: Sequence[str] = (),
) -> RegularToDirectResult:
    with engine_context():
        value = money(folio.units * folio.nav)
    return RegularToDirectResult(
        formula_id=REG_TO_DIRECT_FORMULA_ID,
        as_of=as_of,
        folio_id=folio.folio_id,
        regular_scheme_id=pair.regular_scheme_id,
        direct_scheme_id=pair.direct_scheme_id,
        status=status,
        abstentions=tuple(abstentions),
        nav_gap=gap,
        holding_value_inr=value,
        annual_saving_inr=saving,
        options=tuple(options),
        recommended_timing=recommended,
        rule_ids_used=tuple(dict.fromkeys(rule_ids)),
        flags=tuple(dict.fromkeys(flags)),
    )


def _abstention_for(exc: Exception, folio: FolioHolding, ctx: TaxContext) -> tuple[Abstention, ActionStatus]:
    text = str(exc)
    if isinstance(exc, MissingData) and "exit-load schedule unknown" in text:
        return (
            Abstention(
                "EXIT_LOAD_UNKNOWN",
                f"exit-load schedule of {folio.scheme_id}",
                "Upload the scheme's KIM/SID or enter its exit-load wording.",
            ),
            ActionStatus.REQUIRES_CONFIGURATION,
        )
    if isinstance(exc, MissingData) and ctx.surcharge_rate is None and "surcharge" in text:
        return (
            Abstention("SURCHARGE_BAND_UNKNOWN", "surcharge band", "Enter your surcharge band (0 if none)."),
            ActionStatus.REQUIRES_CONFIGURATION,
        )
    if isinstance(exc, MissingData):
        return Abstention("TAX_FACTS_MISSING", text, "Complete the tax context or scheme facts."), (
            ActionStatus.REQUIRES_CONFIGURATION
        )
    return Abstention("TAX_RULE_NOT_FOUND", text, "Not modelled; see the tax methodology."), ActionStatus.BLOCKED


def regular_to_direct(
    folio: FolioHolding,
    pair: PlanPair,
    ctx: TaxContext,
    ruleset: TaxRuleSet,
    *,
    as_of: date,
    sip_amount_inr: Decimal | None = None,
    calendar: BusinessCalendar | None = None,
    wait_horizon_months: int = DEFAULT_WAIT_HORIZON_MONTHS,
) -> RegularToDirectResult:
    """``cost.reg_to_direct@1`` for one Regular-plan folio.  Options are ordered (d), (b), (c), (a)."""
    if folio.scheme_id != pair.regular_scheme_id:
        raise InvalidInput(f"folio {folio.folio_id} holds {folio.scheme_id}, not {pair.regular_scheme_id}")
    if not pair.sibling_match_unique or pair.direct_scheme_id is None:
        abst = Abstention(
            "SIBLING_NOT_UNIQUE", "a unique Direct-plan sibling", "Confirm which Direct plan matches this scheme."
        )
        return _result(folio, pair, as_of, status=ActionStatus.REQUIRES_CONFIGURATION, abstentions=(abst,))
    gap = measure_nav_gap(pair, as_of, calendar=calendar)
    if isinstance(gap, Abstention):
        return _result(folio, pair, as_of, status=ActionStatus.BLOCKED, abstentions=(gap,))
    if gap.g_12m <= 0:
        abst = Abstention("NO_COST_GAP", "a positive cost gap", "Direct did not cost less over the last 12 months.")
        return _result(folio, pair, as_of, status=ActionStatus.BLOCKED, abstentions=(abst,), gap=gap)
    with engine_context():
        saving = money(folio.units * folio.nav * gap.annual_cost_gap)
    d_option = _redirect_sip(sip_amount_inr)
    if (unmodelled := check_modelled(ctx)) is not None:
        status = (
            ActionStatus.BLOCKED
            if unmodelled.code == "TAX_PROFILE_NOT_MODELLED"
            else ActionStatus.REQUIRES_CONFIGURATION
        )
        return _result(
            folio, pair, as_of, status=status, abstentions=(unmodelled,), gap=gap, saving=saving, options=(d_option,)
        )
    if folio.is_elss:
        abst = Abstention("ELSS_LOCK_IN_NOT_MODELLED", "ELSS lock-in dates", "Switching ELSS units is not modelled.")
        return _result(
            folio,
            pair,
            as_of,
            status=ActionStatus.BLOCKED,
            abstentions=(abst,),
            gap=gap,
            saving=saving,
            options=(d_option,),
        )
    try:
        return _switch_options(folio, pair, ctx, ruleset, as_of, gap, saving, d_option, wait_horizon_months)
    except (MissingData, RuleNotFound) as exc:
        abst, status = _abstention_for(exc, folio, ctx)
        return _result(
            folio, pair, as_of, status=status, abstentions=(abst,), gap=gap, saving=saving, options=(d_option,)
        )


def _switch_options(
    folio: FolioHolding,
    pair: PlanPair,
    ctx: TaxContext,
    ruleset: TaxRuleSet,
    as_of: date,
    gap: NavGap,
    saving: Decimal,
    d_option: SwitchOption,
    horizon_months: int,
) -> RegularToDirectResult:
    flags: list[str] = [F_NAV_CONSTANT, F_PLAN_SWITCH_LOAD]
    pool_rule = _pool_rule(folio, ruleset, as_of)
    equity = pool_rule is not None  # equity-oriented ⇔ its long-term rule shares the equity exemption pool
    pool = None if pool_rule is None else pool_left_for(ctx, pool_rule.annual_exemption_inr or ZERO)
    if pool is None:
        pool = ZERO
        if pool_rule is not None:
            flags.append(F_EXEMPTION_ASSUMED_USED)
    consumed = fifo_consume(folio, folio.units, as_of)
    now = _cost_on(folio, consumed, as_of, as_of, ruleset, ctx, pool, equity)
    options: list[SwitchOption] = [d_option]
    rule_ids: list[str] = list(now.rule_ids)
    flags.extend(now.flags)
    b_lots = _lt_prefix_in_pool(folio, ruleset, as_of, pool) if pool > 0 else ()
    if b_lots:
        b = _cost_on(folio, b_lots, as_of, as_of, ruleset, ctx, pool, equity)
        options.append(_option("b", "SWITCH", b, saving, as_of))
        rule_ids.extend(b.rule_ids)
    else:
        flags.append(F_NO_LT_IN_POOL)
    wait = _best_wait(folio, consumed, ruleset, ctx, as_of, pool, equity, saving, horizon_months, flags)
    a_option = _option("a", "SWITCH", now, saving, as_of)
    recommended = "a"
    if wait is not None:
        c_option = _option("c", "WAIT_UNTIL", wait, saving, as_of)
        if c_option.total_cost_inr < a_option.total_cost_inr:
            options.append(c_option)
            rule_ids.extend(wait.rule_ids)
            flags.extend(wait.flags)
            recommended = "c"
        else:
            flags.append(F_WAIT_NOT_CHEAPER)
    else:
        flags.append(F_WAIT_NOT_CHEAPER)
    options.append(a_option)
    status_by_id = ruleset.status_by_rule_id()
    if any(status_by_id.get(r) is Verification.NV for r in rule_ids):
        flags.append(F_UNVERIFIED_RULE)
    return _result(
        folio,
        pair,
        as_of,
        status=ActionStatus.NOT_VERIFIED,
        gap=gap,
        saving=saving,
        options=options,
        recommended=recommended,
        rule_ids=rule_ids,
        flags=flags,
    )


def _pool_rule(folio: FolioHolding, ruleset: TaxRuleSet, as_of: date) -> TaxRule | None:
    """The equity-pool LTCG rule for this scheme (probe: a 2-year-old lot), or None when it is not equity-oriented."""
    probe = ConsumedLot("__probe__", add_months(as_of, -24), ONE, ZERO, folio.nav, folio.nav)
    rule = rule_for(folio, probe, as_of, ruleset)
    return rule if is_equity_pool_rule(rule) else None
