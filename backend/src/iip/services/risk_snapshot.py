"""The daily risk snapshot (job J4 compute; PLAN.md wave 2, package B02).

design-risk-first.md §4 (risk hierarchy), §5.1–5.5 (formulas, engine package A12), §7 (ActionCard, A16) and §9.1 (J4):

1. :func:`load_inputs` reads everything the engine needs in a fixed, small number of statements (goals and the
   goal map, the risk profile, the latest policy, the user's actual holdings, their latest NAV and factsheet facts).
2. :func:`compute_snapshot` is a PURE function of those inputs: for every scope (the household for L1/L4, each goal
   for L2/L3) the supervisor's per-goal manifest (:mod:`iip.supervisor.manifest`) gates the layer first; a missing
   fact abstains that layer for that scope only. The engine (``iip.engine.risk``) runs only behind a complete gate.
   Results become :class:`~iip.engine.actions.contracts.ActionCard` objects, ranked (``actions.ranking@1``) with the
   "Needs from you" list (``actions.needs@1``), and rendered from ``rules/action_templates.yaml``.
3. The snapshot is **content-addressed**: ``input_manifest_hash = sha256(canonical inputs)`` and
   ``snapshot_id = sha256(engine version, rules version, input manifest hash)``. The payload is canonical JSON with
   no wall-clock value in it, so re-running on the same inputs gives a byte-identical payload and the same id.
4. :func:`run_snapshot` stores it (``signal_snapshots``; an ABSTAIN snapshot is stored too). The Today page reads it
   in ONE statement (:func:`read_today`, served by :mod:`iip.api.routes_today`); the engine never runs on page
   load.

Signal (S) rules are never evaluated here and never become cards: the shadow ledger (:mod:`iip.services.shadow`)
records them separately.

Scope of this version (stated, not hidden): layers L1–L4. Rebalance, next-rupee and tax/cost cards (L5/L6, engine
packages A14/A15) need user targets and contribution plans that are not collected yet; they are not emitted.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from iip.engine.actions.cards import TemplateSet, render_card
from iip.engine.actions.contracts import (
    CONTRACT_VERSION,
    Abstention,
    ActionCard,
    CardKind,
    CardNumber,
    CardStatus,
    Impact,
    ImpactBasis,
    Layer,
    NumberUnit,
    Step,
    Verb,
    Why,
)
from iip.engine.actions.needs import NEEDS_VERSION, Need, collect_needs
from iip.engine.actions.ranking import RANKING_VERSION, TodayState, rank_cards
from iip.engine.determinism import canonical_json, content_hash
from iip.engine.errors import InvalidInput
from iip.engine.freshness import nav_is_stale
from iip.engine.money import ZERO, engine_context, money
from iip.engine.risk import EQUITY_CLASSES, Outcome, RiskClass, Status
from iip.engine.risk import Abstention as RiskAbstention
from iip.engine.risk.budget import BudgetHolding, LossBudgetResult, loss_budget
from iip.engine.risk.emergency import EmergencyResult, LiquidityKind, ReserveHolding, emergency_gate
from iip.engine.risk.goal_date import GoalDateHolding, GoalDateResult, goal_date_safety
from iip.engine.risk.limits import LimitHolding, LimitKind, LimitParams, LimitsResult, check_limits
from iip.engine.risk.stress import (
    TABLE_CLASSES,
    CitedStress,
    ClassStress,
    CreditBucket,
    DebtShock,
    build_stress_table,
)
from iip.engine.tax import financial_year_label
from iip.rules.loader import RowStatus, RuleTableError, StressTable, ValueSource
from iip.services import notify, shadow
from iip.services.portfolio import USABLE_QUALITY, PortfolioError, Txn, fifo_positions
from iip.store import ledger
from iip.store.db import write_tx
from iip.store.goals_repo import Goal, GoalLink, RiskProfile, load_goal_context
from iip.supervisor.manifest import (
    GOAL_MANIFEST_VERSION,
    HOUSEHOLD_SCOPE,
    ITEM_EMERGENCY_MONTHS,
    ITEM_ESSENTIAL_EXPENSES,
    ITEM_GOAL_DATE,
    ITEM_H_SAFE,
    ITEM_HOLDINGS_CLASSIFIED,
    ITEM_HOLDINGS_VALUED,
    ITEM_LIMITS_POLICY,
    ITEM_LOSS_BUDGET,
    ITEM_RECOVERY_MONTHS,
    ITEM_STRESS_TABLE,
    ContextValue,
    Gap,
    RiskLayer,
    ScopeGate,
    evaluate_scope,
)

if TYPE_CHECKING:
    from iip.services import cas as cas_types
    from iip.services import cron as cron_types


ENGINE_VERSION = "risk_snapshot@1"
PAYLOAD_SCHEMA = "today_snapshot@1"
SNAPSHOT_FORMULA = "risk.snapshot@1"
# max(0, E / e_cap − V): new non-equity money that brings the goal's equity share down to its cap (§5.3 remedy 1).
REDIRECT_FORMULA = "risk.loss_budget_redirect@1"
# exposure − cap × base: the ₹ above a concentration limit (§5.5).
LIMIT_EXCESS_FORMULA = "risk.limits_excess@1"
UNASSIGNED_SCOPE = "unassigned"

RULE_EMERGENCY = ("risk.emergency_gate", 1)
RULE_GOAL_DATE = ("risk.goal_date", 1)
RULE_LOSS_BUDGET = ("risk.loss_budget", 1)
RULE_LIMITS = ("risk.limits", 1)

VERDICT_ACTIONS = "ACTIONS"
VERDICT_NOTHING = "NOTHING_NEEDED"
VERDICT_ABSTAIN = "ABSTAIN"

_LAYER_OF = {RiskLayer.L1: Layer.L1, RiskLayer.L2: Layer.L2, RiskLayer.L3: Layer.L3, RiskLayer.L4: Layer.L4}
_RULE_OF = {
    RiskLayer.L1: RULE_EMERGENCY,
    RiskLayer.L2: RULE_GOAL_DATE,
    RiskLayer.L3: RULE_LOSS_BUDGET,
    RiskLayer.L4: RULE_LIMITS,
}

# ------------------------------------------------------------------------------------------------ classification
#
# SEBI/AMFI category text → risk class (design-risk-first.md §5.2). Matching is on normalised category text only,
# never on scheme names. Ambiguous cases take the HIGHER-stress class (large & mid → EQ_MID; any hybrid, including
# arbitrage, → HYBRID = 100 % EQ_BROAD). A category this table does not know (index funds and ETFs with no index
# mapping, fund of funds, solution-oriented, …) stays unclassified and the layers that need it abstain.

_CLASS_PATTERNS: tuple[tuple[str, RiskClass], ...] = (
    ("overnight", RiskClass.CASH_LIKE),
    ("large & mid", RiskClass.EQ_MID),
    ("large and mid", RiskClass.EQ_MID),
    ("large cap", RiskClass.EQ_LARGE),
    ("mid cap", RiskClass.EQ_MID),
    ("small cap", RiskClass.EQ_SMALL),
    ("sectoral", RiskClass.EQ_SECTOR_THEMATIC),
    ("thematic", RiskClass.EQ_SECTOR_THEMATIC),
    ("flexi cap", RiskClass.EQ_BROAD),
    ("multi cap", RiskClass.EQ_BROAD),
    ("focused", RiskClass.EQ_BROAD),
    ("value fund", RiskClass.EQ_BROAD),
    ("contra", RiskClass.EQ_BROAD),
    ("elss", RiskClass.EQ_BROAD),
    ("dividend yield", RiskClass.EQ_BROAD),
    ("hybrid", RiskClass.HYBRID),
    ("balanced advantage", RiskClass.HYBRID),
    ("dynamic asset allocation", RiskClass.HYBRID),
    ("multi asset", RiskClass.HYBRID),
    ("arbitrage", RiskClass.HYBRID),
    ("equity savings", RiskClass.HYBRID),
    ("gold", RiskClass.GOLD),
    ("liquid", RiskClass.DEBT_MTM),
    ("money market", RiskClass.DEBT_MTM),
    ("ultra short", RiskClass.DEBT_MTM),
    ("low duration", RiskClass.DEBT_MTM),
    ("short duration", RiskClass.DEBT_MTM),
    ("short term", RiskClass.DEBT_MTM),
    ("medium", RiskClass.DEBT_MTM),
    ("long duration", RiskClass.DEBT_MTM),
    ("long term fund", RiskClass.DEBT_MTM),
    ("dynamic bond", RiskClass.DEBT_MTM),
    ("dynamic term", RiskClass.DEBT_MTM),
    ("corporate bond", RiskClass.DEBT_MTM),
    ("credit risk", RiskClass.DEBT_MTM),
    ("banking and psu", RiskClass.DEBT_MTM),
    ("gilt", RiskClass.DEBT_MTM),
    ("floater", RiskClass.DEBT_MTM),
    ("floating interest", RiskClass.DEBT_MTM),
)
_UNCLASSIFIABLE = ("index fund", "etf", "fund of fund", "fof", "solution oriented", "retirement", "children")


def classify_category(category: str | None) -> RiskClass | None:
    """Risk class from the category text, or None (unknown → the layers that need it abstain)."""
    if not category:
        return None
    text = " ".join(category.lower().replace("-", " ").split())
    if "gold" in text and "multi asset" not in text:
        return RiskClass.GOLD
    if any(token in text for token in _UNCLASSIFIABLE):
        return None
    for token, risk_class in _CLASS_PATTERNS:
        if token in text:
            return risk_class
    return None


def liquidity_kind(category: str | None, risk_class: RiskClass | None) -> LiquidityKind:
    text = (category or "").lower()
    if "overnight" in text:
        return LiquidityKind.OVERNIGHT_MF
    if "liquid" in text:
        return LiquidityKind.LIQUID_MF
    if "elss" in text:
        return LiquidityKind.LOCK_IN
    return LiquidityKind.OTHER


# ------------------------------------------------------------------------------------------------ inputs


@dataclass(frozen=True)
class HoldingFact:
    """One instrument the user holds, aggregated over every actual portfolio, valued at the latest usable NAV."""

    instrument_id: str
    name: str
    kind: str
    category: str | None
    amc: str | None
    units: Decimal
    nav: Decimal | None
    nav_date: date | None
    nav_obs_id: int | None
    market_value: Decimal | None  # ₹ (money-quantised); None = excluded (see exclusion)
    exclusion: str | None
    risk_class: RiskClass | None
    liquidity: LiquidityKind
    modified_duration: Decimal | None = None
    macaulay_duration: Decimal | None = None
    credit: CreditBucket | None = None
    fund_fact_id: int | None = None

    @property
    def fact_ids(self) -> tuple[str, ...]:
        ids = []
        if self.nav_obs_id is not None:
            ids.append(f"obs:{self.nav_obs_id}")
        if self.fund_fact_id is not None:
            ids.append(f"fund_fact:{self.fund_fact_id}")
        return tuple(ids)


@dataclass(frozen=True)
class SnapshotInputs:
    as_of: date
    goals: tuple[Goal, ...]
    links: tuple[GoalLink, ...]
    risk_profile: RiskProfile | None
    limits: LimitParams | None
    policy_version_id: int | None
    holdings: tuple[HoldingFact, ...]
    stress: tuple[ClassStress, ...]
    debt_shock: DebtShock
    stress_table_version: str
    flags: tuple[str, ...] = ()
    # (portfolio_id, error code) of every ACTUAL portfolio whose ledger cannot be replayed (e.g. a sell with no
    # prior buy). Its holdings are unknown, so every holdings-based card abstains (silent-failure-hunter-01).
    invalid_portfolios: tuple[tuple[str, str], ...] = ()


def _dec(v: object) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def _status(row_status: RowStatus) -> Status:
    if row_status in (RowStatus.P, RowStatus.S, RowStatus.PARAMETER):
        return Status.VERIFIED
    if row_status is RowStatus.REQUIRES_CONFIGURATION:
        return Status.REQUIRES_CONFIGURATION
    return Status.NOT_VERIFIED


def stress_from_table(table: StressTable) -> tuple[tuple[ClassStress, ...], DebtShock]:
    """The engine stress table from the rule table (cited values; the AMFI recompute is not wired yet, so every
    class carries ``RECOMPUTED_DRAWDOWN_MISSING`` and NOT VERIFIED, per ``risk.stress_combinator@1``)."""
    cited: dict[RiskClass, CitedStress] = {}
    for rc in TABLE_CLASSES:
        try:
            value = table.cited_stress(rc.value)
            row = table.row(rc.value)
        except RuleTableError:
            continue
        if value is None or value <= 0:
            continue
        cited[rc] = CitedStress(
            value=value, citation=row.source_url, status=_status(row.verification_status),
            recovery_years=row.recovery_years,
        )  # fmt: skip
    built = build_stress_table(cited=cited, recomputed={})
    shock = DebtShock()
    for row in table.rows:
        if row.value_source is ValueSource.FORMULA and row.formula is not None:
            shock = DebtShock(delta_y=row.formula.dy, delta_s_aaa=row.formula.ds_aaa,
                              delta_s_below_aaa=row.formula.ds_below_aaa)  # fmt: skip
    return tuple(built[rc] for rc in sorted(built, key=lambda r: r.value)), shock


def _limit_params(policy: Mapping[str, Any] | None) -> LimitParams | None:
    if policy is None:
        return None
    raw = policy.get("limits")
    if not isinstance(raw, Mapping):
        return None
    names = ("c_scheme", "c_amc", "c_theme", "c_factor", "c_issuer")
    return LimitParams(**{n: _dec(raw.get(n)) for n in names})


def _actual_positions(
    conn: sqlite3.Connection,
) -> tuple[dict[str, Decimal], list[str], list[tuple[str, str]]]:
    """Units held per instrument over every ACTUAL portfolio (FIFO per portfolio), the flags, and the portfolios
    whose ledger is invalid (``(portfolio_id, error code)``; their units are left out and the snapshot fails closed
    on them, see :func:`compute_snapshot`). One statement."""
    rows = conn.execute(
        "SELECT t.portfolio_id, t.txn_id, t.instrument_id, t.txn_date, t.txn_type, t.units, t.amount, t.created_at"
        " FROM transactions t JOIN portfolios p ON p.portfolio_id = t.portfolio_id WHERE p.nature = 'actual'"
        " ORDER BY t.portfolio_id, t.txn_date, t.created_at, t.txn_id"
    ).fetchall()
    per: dict[str, list[Txn]] = defaultdict(list)
    for r in rows:
        per[r["portfolio_id"]].append(
            Txn(r["txn_id"], r["instrument_id"], date.fromisoformat(r["txn_date"]), r["txn_type"],
                Decimal(r["units"]) if r["units"] is not None else ZERO, Decimal(r["amount"]), r["created_at"])
        )  # fmt: skip
    units: dict[str, Decimal] = defaultdict(Decimal)
    flags: list[str] = []
    invalid: list[tuple[str, str]] = []
    for pid in sorted(per):
        try:
            positions = fifo_positions(per[pid])
        except PortfolioError as exc:
            flags.append("PORTFOLIO_LEDGER_INVALID_EXCLUDED")
            invalid.append((str(pid), exc.code))
            continue
        for iid, pos in positions.items():
            if pos.units > 0:
                units[iid] += pos.units
    return dict(units), sorted(set(flags)), invalid


def _in(n: int) -> str:
    return ",".join("?" * n)


def _credit(lowest_rating: str | None, share_below_aaa: Decimal | None) -> CreditBucket | None:
    if share_below_aaa is not None:
        return CreditBucket.BELOW_AAA if share_below_aaa > 0 else CreditBucket.AAA
    if lowest_rating is None:
        return None
    text = lowest_rating.upper().replace(" ", "")
    if text.startswith(("AAA", "SOV", "A1+")):
        return CreditBucket.AAA
    return CreditBucket.BELOW_AAA


def load_holdings(
    conn: sqlite3.Connection, as_of: date
) -> tuple[tuple[HoldingFact, ...], list[str], list[tuple[str, str]]]:
    """Holdings valued at the latest usable NAV on or before ``as_of``. Statements: one for positions, then (per
    chunk of instruments) one for metadata, one for NAVs and one for factsheet facts — never one per holding."""
    units, flags, invalid = _actual_positions(conn)
    ids = sorted(units)
    meta: dict[str, Any] = {}
    navs: dict[str, Any] = {}
    facts: dict[str, Any] = {}
    for part in ledger.chunks(ids, ledger.MAX_PARAMS - 2):
        p = list(part)
        for r in conn.execute(
            "SELECT i.instrument_id, i.kind, i.name, i.amfi_code, m.amc, m.category_raw, m.sebi_category"  # noqa: S608
            " FROM instruments i LEFT JOIN mf_schemes m ON m.instrument_id = i.instrument_id"
            f" WHERE i.instrument_id IN ({_in(len(p))})",
            p,
        ):
            meta[r["instrument_id"]] = r
        series = [f"nav:{meta[i]['amfi_code']}" for i in p if i in meta and meta[i]["amfi_code"]]
        if series:
            ok = _in(len(USABLE_QUALITY))
            for r in conn.execute(
                "SELECT o.obs_id, o.series_id, o.value, o.observation_date, o.quality_status FROM observations o"  # noqa: S608
                " JOIN (SELECT series_id, MAX(observation_date) AS d FROM observations"
                f" WHERE series_id IN ({_in(len(series))}) AND superseded_by IS NULL AND quality_status != 'rejected'"
                " AND observation_date <= ? GROUP BY series_id) m"
                " ON o.series_id = m.series_id AND o.observation_date = m.d"
                f" WHERE o.superseded_by IS NULL AND o.quality_status IN ({ok})"
                " ORDER BY o.series_id, o.obs_id DESC",
                [*series, as_of.isoformat(), *USABLE_QUALITY],
            ):
                navs.setdefault(r["series_id"], r)
        for r in conn.execute(
            "SELECT f.* FROM fund_facts f JOIN (SELECT instrument_id, MAX(as_of_date) AS d FROM fund_facts"  # noqa: S608
            f" WHERE instrument_id IN ({_in(len(p))}) AND as_of_date <= ? GROUP BY instrument_id) m"
            " ON f.instrument_id = m.instrument_id AND f.as_of_date = m.d ORDER BY f.instrument_id, f.entered_at DESC,"
            " f.fact_id DESC",
            [*p, as_of.isoformat()],
        ):
            facts.setdefault(r["instrument_id"], r)

    out: list[HoldingFact] = []
    for iid in ids:
        m = meta.get(iid)
        if m is None:
            continue
        kind = m["kind"]
        category = (m["sebi_category"] or m["category_raw"]) if kind == "mf_scheme" else kind
        risk_class = classify_category(category) if kind == "mf_scheme" else None
        nav_row = navs.get(f"nav:{m['amfi_code']}") if m["amfi_code"] else None
        nav = nav_date = obs_id = mv = None
        exclusion: str | None = None
        if kind != "mf_scheme":
            exclusion = "NOT_VALUED"
        elif nav_row is None:
            exclusion = "NO_NAV_STORED"
        else:
            nav, nav_date, obs_id = (
                Decimal(nav_row["value"]),
                date.fromisoformat(nav_row["observation_date"]),
                int(nav_row["obs_id"]),
            )
            if nav_is_stale(nav_date, as_of):
                exclusion = "STALE_NAV"
            else:
                with engine_context():
                    mv = money(units[iid] * nav)
        f = facts.get(iid)
        out.append(
            HoldingFact(
                instrument_id=iid, name=m["name"], kind=kind, category=category, amc=m["amc"], units=units[iid],
                nav=nav, nav_date=nav_date, nav_obs_id=obs_id, market_value=mv, exclusion=exclusion,
                risk_class=risk_class, liquidity=liquidity_kind(category, risk_class),
                modified_duration=_dec(f["modified_duration"]) if f is not None else None,
                macaulay_duration=_dec(f["macaulay_duration"]) if f is not None else None,
                credit=_credit(f["lowest_rating"], _dec(f["share_below_aaa"])) if f is not None else None,
                fund_fact_id=int(f["fact_id"]) if f is not None else None,
            )
        )  # fmt: skip
    return tuple(out), flags, invalid


def load_inputs(conn: sqlite3.Connection, as_of: date, stress_table: StressTable) -> SnapshotInputs:
    ctx = load_goal_context(conn, financial_year_label(as_of))
    holdings, flags, invalid = load_holdings(conn, as_of)
    stress, shock = stress_from_table(stress_table)
    return SnapshotInputs(
        as_of=as_of,
        goals=tuple(ctx.goals),
        links=tuple(ctx.links),
        risk_profile=ctx.risk_profile,
        limits=_limit_params(ctx.policy.policy if ctx.policy is not None else None),
        policy_version_id=ctx.policy.policy_version_id if ctx.policy is not None else None,
        holdings=holdings,
        stress=stress,
        debt_shock=shock,
        stress_table_version=stress_table.table_version,
        flags=tuple(flags),
        invalid_portfolios=tuple(invalid),
    )


def latest_data_date(conn: sqlite3.Connection) -> date | None:
    """The newest usable NAV date among the user's actual holdings (one statement): the default ``as_of``."""
    row = conn.execute(
        "SELECT MAX(o.observation_date) AS d FROM observations o JOIN instruments i ON o.series_id = 'nav:' ||"
        " i.amfi_code WHERE o.superseded_by IS NULL AND o.quality_status IN ('ok','manual','fixture') AND"
        " i.instrument_id IN (SELECT t.instrument_id FROM transactions t JOIN portfolios p ON p.portfolio_id ="
        " t.portfolio_id WHERE p.nature = 'actual')"
    ).fetchone()
    return date.fromisoformat(row["d"]) if row is not None and row["d"] else None


# ------------------------------------------------------------------------------------------------ pure compute


@dataclass(frozen=True)
class ScopeHolding:
    fact: HoldingFact
    fraction: Decimal
    market_value: Decimal | None


@dataclass
class _Builder:
    inputs: SnapshotInputs
    templates: TemplateSet
    snapshot_id: str
    input_manifest_hash: str
    rules_version: str
    cards: list[ActionCard] = field(default_factory=list)
    texts: dict[str, dict[str, str]] = field(default_factory=dict)
    scopes: list[dict[str, Any]] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)

    def card(
        self,
        kind: CardKind,
        layer: Layer,
        rule: tuple[str, int],
        *,
        goal_id: str | None,
        template_id: str,
        status: CardStatus,
        numbers: Sequence[CardNumber] = (),
        steps: Sequence[Step] = (),
        impact: Impact | None = None,
        abstentions: Sequence[Abstention] = (),
        text_slots: Mapping[str, str] | None = None,
    ) -> ActionCard:
        c = ActionCard(
            kind=kind, layer=layer, goal_id=goal_id, as_of=self.inputs.as_of, deadline=None, impact=impact,
            steps=tuple(steps), why=Why(rule[0], rule[1]), numbers=tuple(numbers), template_id=template_id,
            status=status, abstentions=tuple(abstentions), engine_version=ENGINE_VERSION,
            rules_version=self.rules_version, input_manifest_hash=self.input_manifest_hash,
            snapshot_id=self.snapshot_id,
        )  # fmt: skip
        self.cards.append(c)
        self.texts[c.card_id] = dict(text_slots or {})
        return c


def _num(slot: str, value: Decimal | date, unit: NumberUnit, as_of: date, *, facts: Iterable[str] = (),
         formula: str | None = None) -> CardNumber:  # fmt: skip
    return CardNumber(slot, value, unit, as_of, tuple(sorted(set(facts))), formula)


def _scope_holdings(
    inputs: SnapshotInputs,
) -> tuple[dict[str, list[ScopeHolding]], list[ScopeHolding], set[str], dict[str, list[str]]]:
    """Split each holding over goals by the user's fractions; the remainder is Unassigned. Links with a folio are
    not applied (holdings carry no folio yet): their instruments stay Unassigned (flagged), and the goals they were
    meant for are returned (``goal_id -> instrument ids``) so those goals fail closed instead of being checked
    without the holding."""
    flags: set[str] = set()
    by_inst: dict[str, list[GoalLink]] = defaultdict(list)
    goal_ids = {g.goal_id for g in inputs.goals}
    held = {h.instrument_id for h in inputs.holdings}
    folio_goals: dict[str, list[str]] = defaultdict(list)
    for link in inputs.links:
        if link.folio != "":
            flags.add("FOLIO_LINK_NOT_APPLIED")
            if link.goal_id in goal_ids and link.instrument_id in held:
                folio_goals[link.goal_id].append(link.instrument_id)
            continue
        if link.goal_id in goal_ids:
            by_inst[link.instrument_id].append(link)
    per_goal: dict[str, list[ScopeHolding]] = {g.goal_id: [] for g in inputs.goals}
    unassigned: list[ScopeHolding] = []
    for h in inputs.holdings:
        used = ZERO
        for link in sorted(by_inst.get(h.instrument_id, []), key=lambda lk: lk.goal_id):
            with engine_context():
                mv = None if h.market_value is None else money(h.market_value * link.fraction)
                used += link.fraction
            per_goal[link.goal_id].append(ScopeHolding(h, link.fraction, mv))
        if used < 1:
            with engine_context():
                rest = Decimal(1) - used
                mv = None if h.market_value is None else money(h.market_value * rest)
            unassigned.append(ScopeHolding(h, rest, mv))
    return per_goal, unassigned, flags, {g: sorted(set(ids)) for g, ids in folio_goals.items()}


def _valued(items: Sequence[ScopeHolding]) -> ContextValue:
    missing = sorted(s.fact.instrument_id for s in items if s.market_value is None)
    dates = [s.fact.nav_date for s in items if s.fact.nav_date is not None]
    return ContextValue(
        ITEM_HOLDINGS_VALUED, present=True, observation_date=min(dates) if dates else None,
        source_id="amfi" if dates else None, provenance_complete=True, valid=not missing,
        fact_ids=tuple(sorted({f for s in items for f in s.fact.fact_ids})),
        note="no fresh NAV for " + ", ".join(missing) if missing else "",
    )  # fmt: skip


def _classified(items: Sequence[ScopeHolding]) -> ContextValue:
    missing = sorted(s.fact.instrument_id for s in items if s.fact.risk_class is None)
    return ContextValue(
        ITEM_HOLDINGS_CLASSIFIED, present=True, provenance_complete=True, valid=not missing,
        note="no risk class for the category of " + ", ".join(missing) if missing else "",
    )  # fmt: skip


def _user(item: str, value: object) -> ContextValue:
    return ContextValue(item, present=value is not None, valid=value is not None)


_FIX = {
    ITEM_EMERGENCY_MONTHS: "enter how many months of essential expenses your reserve should cover",
    ITEM_ESSENTIAL_EXPENSES: "enter your essential monthly expenses",
    ITEM_GOAL_DATE: "enter the goal's target date",
    ITEM_H_SAFE: "choose how many years before the goal date money must be out of instruments that can fall",
    ITEM_LOSS_BUDGET: "view the worst-fall table, then enter the largest rupee fall you would sit through",
    ITEM_RECOVERY_MONTHS: "enter the longest number of months you would wait for this goal to recover",
    ITEM_STRESS_TABLE: "add the stress values to your local config",
    ITEM_HOLDINGS_VALUED: "refresh NAVs (AMFI ingestion) so every holding has a fresh value",
    ITEM_HOLDINGS_CLASSIFIED: "the category of a holding has no risk class yet; review it on the holdings page",
    ITEM_LIMITS_POLICY: "set your concentration limits in your policy",
}

# Digit-free phrases for the ABSTAIN card text slot (the template linter forbids digits in free text). The full,
# specific missing input is kept in the card's abstentions and in "Needs from you".
_PHRASE = {
    RiskLayer.L1: "an emergency-fund input",
    RiskLayer.L2: "a goal-date input",
    RiskLayer.L3: "a loss-limit input",
    RiskLayer.L4: "a concentration-limit input",
}


def _gap_abstention(gap: Gap, scope_label: str) -> Abstention:
    detail = f" ({gap.detail})" if gap.detail else ""
    return Abstention(
        code=f"context_{gap.reason.value.lower()}:{gap.item_id}",
        missing_input=f"{gap.description} — {scope_label}{detail}",
        how_to_fix=_FIX.get(gap.item_id, "provide the missing input"),
    )


def _risk_abstention(a: RiskAbstention) -> Abstention:
    return Abstention(code=a.code, missing_input=a.missing_input, how_to_fix=a.how_to_fix)


def _abstain_card(b: _Builder, layer: RiskLayer, scope_id: str | None, abstentions: Sequence[Abstention]) -> None:
    uniq = {(a.code, a.missing_input): a for a in abstentions}
    b.card(
        CardKind.ABSTAIN, _LAYER_OF[layer], _RULE_OF[layer], goal_id=scope_id, template_id="abstain_missing_input",
        status=CardStatus.REQUIRES_CONFIGURATION, abstentions=[uniq[k] for k in sorted(uniq)],
        text_slots={"missing_input": _PHRASE[layer]},
    )  # fmt: skip


def _integrity_card(b: _Builder, scope_id: str | None, abstentions: Sequence[Abstention], phrase: str) -> None:
    """An L0 (data-integrity) abstention. The ranking suppresses every lower-layer card of its scope (the whole
    household when ``scope_id`` is None) and keeps them in ``suppressed``: nothing computed on a partial picture is
    shown as an action, and the reason is visible on Today and in "Needs from you"."""
    uniq = {(a.code, a.missing_input): a for a in abstentions}
    b.card(
        CardKind.ABSTAIN, Layer.L0, ("risk.snapshot", 1), goal_id=scope_id, template_id="abstain_missing_input",
        status=CardStatus.REQUIRES_CONFIGURATION, abstentions=[uniq[k] for k in sorted(uniq)],
        text_slots={"missing_input": phrase},
    )  # fmt: skip


def _gate_summary(gate: ScopeGate) -> dict[str, Any]:
    return {
        "complete": gate.result.complete,
        "gaps": [
            {"item_id": g.item_id, "reason": g.reason.value, "required": g.required, "detail": g.detail}
            for g in gate.result.gaps
        ],
    }


def _stress_status(stress: Mapping[RiskClass, ClassStress], classes: Iterable[RiskClass]) -> CardStatus:
    for rc in classes:
        cs = stress.get(rc)
        if cs is not None and cs.status is not Status.VERIFIED:
            return CardStatus.NOT_VERIFIED
    return CardStatus.VERIFIED


# --- L1 ----------------------------------------------------------------------------------------------------------


def _l1(b: _Builder, all_holdings: Sequence[ScopeHolding]) -> dict[str, Any]:
    inputs = b.inputs
    rp = inputs.risk_profile
    months = rp.emergency_months if rp is not None else None
    expenses = rp.essential_monthly_expenses if rp is not None else None
    liquid = [s for s in all_holdings if s.fact.liquidity in (LiquidityKind.OVERNIGHT_MF, LiquidityKind.LIQUID_MF)]
    gate = evaluate_scope(
        HOUSEHOLD_SCOPE, RiskLayer.L1,
        {ITEM_EMERGENCY_MONTHS: _user(ITEM_EMERGENCY_MONTHS, months),
         ITEM_ESSENTIAL_EXPENSES: _user(ITEM_ESSENTIAL_EXPENSES, expenses),
         ITEM_HOLDINGS_VALUED: _valued(liquid)},
        inputs.as_of,
    )  # fmt: skip
    summary: dict[str, Any] = {"gate": _gate_summary(gate)}
    if not gate.result.complete:
        _abstain_card(b, RiskLayer.L1, None, [_gap_abstention(g, "household") for g in gate.result.blocking])
        summary["outcome"] = Outcome.ABSTAIN.value
        return summary
    assert months is not None and expenses is not None
    reserves: list[ReserveHolding] = []
    if rp is not None and rp.savings_balance is not None:
        reserves.append(ReserveHolding("savings", LiquidityKind.SAVINGS, rp.savings_balance))
    if rp is not None and rp.sweep_fd_balance is not None:
        reserves.append(ReserveHolding("sweep_fd", LiquidityKind.SWEEP_FD, rp.sweep_fd_balance))
    for s in all_holdings:
        if s.market_value is not None and s.fact.liquidity is not LiquidityKind.OTHER:
            reserves.append(ReserveHolding(s.fact.instrument_id, s.fact.liquidity, s.market_value))
    res: EmergencyResult = emergency_gate(months=months, essential_monthly_expenses=expenses, holdings=reserves)
    flags = set(res.flags)
    counted_mf = any(r.kind in (LiquidityKind.OVERNIGHT_MF, LiquidityKind.LIQUID_MF) for r in reserves)
    if counted_mf:
        flags.add("EXIT_LOAD_TODAY_NOT_MODELLED")
    if rp is not None and (rp.savings_balance is None or rp.sweep_fd_balance is None):
        flags.add("BANK_BALANCE_NOT_PROVIDED_COUNTED_AS_ZERO")
    summary.update(outcome=res.outcome.value, flags=sorted(flags),
                   liquid_reserves=str(res.liquid_reserves),
                   target_reserve=None if res.target_reserve is None else str(res.target_reserve),
                   shortfall=None if res.shortfall is None else str(res.shortfall))  # fmt: skip
    if res.outcome is Outcome.ABSTAIN:
        _abstain_card(b, RiskLayer.L1, None, [_risk_abstention(a) for a in res.abstentions])
    elif res.outcome is Outcome.BREACH:
        assert res.shortfall is not None
        nav_facts = [f for s in liquid for f in s.fact.fact_ids]
        shortfall = money(res.shortfall)
        b.card(
            CardKind.EMERGENCY_SHORTFALL, Layer.L1, RULE_EMERGENCY, goal_id=None, template_id="emergency_shortfall",
            status=CardStatus.NOT_VERIFIED if counted_mf else CardStatus.VERIFIED,
            numbers=[
                _num("shortfall", shortfall, NumberUnit.INR, inputs.as_of,
                     facts=["user:risk_profile.essential_monthly_expenses", "user:risk_profile.emergency_months",
                            *nav_facts], formula="risk.emergency_gate@1"),
                _num("months", Decimal(months), NumberUnit.MONTHS, inputs.as_of,
                     facts=["user:risk_profile.emergency_months"]),
            ],
            steps=[Step(Verb.INVEST, None, "risk.emergency_gate@1", amount_inr=shortfall)],
            impact=Impact(shortfall, ImpactBasis.SHORTFALL, "shortfall"),
            text_slots={"reserve_fund": "your overnight or liquid fund"},
        )  # fmt: skip
    return summary


# --- L2 / L3 per goal ----------------------------------------------------------------------------------------------


def _goal_values(goal: Goal, items: Sequence[ScopeHolding]) -> dict[str, ContextValue]:
    return {
        ITEM_GOAL_DATE: _user(ITEM_GOAL_DATE, goal.target_date),
        ITEM_H_SAFE: _user(ITEM_H_SAFE, goal.h_safe_years),
        ITEM_LOSS_BUDGET: _user(ITEM_LOSS_BUDGET, goal.loss_budget_inr),
        ITEM_RECOVERY_MONTHS: _user(ITEM_RECOVERY_MONTHS, goal.recovery_months),
        ITEM_STRESS_TABLE: ContextValue(ITEM_STRESS_TABLE, present=True, provenance_complete=True, valid=True),
        ITEM_HOLDINGS_VALUED: _valued(items),
        ITEM_HOLDINGS_CLASSIFIED: _classified(items),
    }


def _l2(b: _Builder, goal: Goal, items: Sequence[ScopeHolding], values: dict[str, ContextValue]) -> dict[str, Any]:
    as_of = b.inputs.as_of
    gate = evaluate_scope(goal.goal_id, RiskLayer.L2, values, as_of)
    summary: dict[str, Any] = {"gate": _gate_summary(gate)}
    label = f'goal "{goal.name}"'
    if not gate.result.complete:
        _abstain_card(b, RiskLayer.L2, goal.goal_id, [_gap_abstention(g, label) for g in gate.result.blocking])
        summary["outcome"] = Outcome.ABSTAIN.value
        return summary
    assert goal.target_date is not None and goal.h_safe_years is not None
    goal_date = date.fromisoformat(goal.target_date)
    res: GoalDateResult = goal_date_safety(
        goal.goal_id, as_of=as_of, goal_date=goal_date, h_safe_years=goal.h_safe_years,
        holdings=[GoalDateHolding(s.fact.instrument_id, s.fact.risk_class, s.market_value or ZERO,
                                  s.fact.macaulay_duration)
                  for s in items if s.fact.risk_class is not None],
    )  # fmt: skip
    summary.update(outcome=res.outcome.value, flags=sorted(res.flags), years_to_goal=str(res.years_to_goal),
                   findings=[{"instrument_id": f.holding_id, "outcome": f.outcome.value, "code": f.code}
                             for f in res.findings])  # fmt: skip
    if res.outcome is Outcome.BREACH:
        breached = [f.holding_id for f in res.findings if f.outcome is Outcome.BREACH]
        facts = [f for s in items if s.fact.instrument_id in breached for f in s.fact.fact_ids]
        at_risk = money(res.at_risk_value)
        b.card(
            CardKind.GOAL_DATE_BREACH, Layer.L2, RULE_GOAL_DATE, goal_id=goal.goal_id, template_id="goal_date_breach",
            status=CardStatus.VERIFIED,
            numbers=[
                _num("goal_date", goal_date, NumberUnit.DATE, as_of, facts=[f"user:goal:{goal.goal_id}.target_date"]),
                _num("h_safe", goal.h_safe_years, NumberUnit.YEARS, as_of,
                     facts=[f"user:goal:{goal.goal_id}.h_safe_years"]),
                _num("at_risk", at_risk, NumberUnit.INR, as_of, facts=facts, formula="risk.goal_date@1"),
            ],
            steps=[Step(Verb.REDIRECT_SIP, None, "risk.goal_date@1")],
            impact=Impact(at_risk, ImpactBasis.AMOUNT_AT_RISK, "at_risk"),
            text_slots={"goal_name": goal.name, "safe_sleeve": "your debt or liquid sleeve"},
        )  # fmt: skip
    # Each ACTION (debt duration longer than the time left to the goal) is its own neutral GOAL_DATE_DURATION card
    # (TPL-1): redirect new money and review the holding at the next rebalance. Never a sale, and not a BREACH, so it
    # suppresses nothing below it. The engine's abstentions still go to one L2 abstain card.
    by_id = {s.fact.instrument_id: s for s in items}
    for f in res.findings:
        if f.outcome is not Outcome.ACTION:
            continue
        held = by_id[f.holding_id].fact
        assert held.macaulay_duration is not None  # the engine abstains on a debt holding with no duration
        b.card(
            CardKind.GOAL_DATE_DURATION, Layer.L2, RULE_GOAL_DATE, goal_id=goal.goal_id,
            template_id="goal_date_duration", status=CardStatus.VERIFIED,
            numbers=[
                _num("duration", held.macaulay_duration, NumberUnit.YEARS, as_of,
                     facts=[x for x in held.fact_ids if x.startswith("fund_fact:")]),
                _num("years_to_goal", res.years_to_goal, NumberUnit.YEARS, as_of,
                     facts=[f"user:goal:{goal.goal_id}.target_date"], formula="risk.goal_date@1"),
                _num("goal_date", goal_date, NumberUnit.DATE, as_of, facts=[f"user:goal:{goal.goal_id}.target_date"]),
            ],
            steps=[Step(Verb.REDIRECT_SIP, None, "risk.goal_date@1"),
                   Step(Verb.REVIEW, f.holding_id, "risk.goal_date@1")],
            text_slots={"holding_name": held.name, "goal_name": goal.name,
                        "safe_sleeve": "your debt or liquid sleeve"},
        )  # fmt: skip
    if res.outcome is Outcome.ABSTAIN:
        _abstain_card(b, RiskLayer.L2, goal.goal_id, [_risk_abstention(a) for a in res.abstentions])
    return summary


def _redirect_amount(res: LossBudgetResult) -> Decimal | None:
    """``max(0, E / e_cap − V)`` (REDIRECT_FORMULA), or None when the cap is unknown or zero (no amount of new
    non-equity money brings the equity share to a zero cap)."""
    if res.e_cap is None or res.e_cap <= 0:
        return None
    with engine_context():
        return money(max(ZERO, res.equity_value / res.e_cap - res.goal_value))


def _l3(b: _Builder, goal: Goal, items: Sequence[ScopeHolding], values: dict[str, ContextValue]) -> dict[str, Any]:
    as_of = b.inputs.as_of
    has_equity = any(s.fact.risk_class in EQUITY_CLASSES for s in items)
    gate = evaluate_scope(goal.goal_id, RiskLayer.L3, values, as_of, goal_has_equity=has_equity)
    summary: dict[str, Any] = {"gate": _gate_summary(gate)}
    label = f'goal "{goal.name}"'
    if not gate.result.complete:
        _abstain_card(b, RiskLayer.L3, goal.goal_id, [_gap_abstention(g, label) for g in gate.result.blocking])
        summary["outcome"] = Outcome.ABSTAIN.value
        return summary
    stress = {cs.risk_class: cs for cs in b.inputs.stress}
    holdings = []
    spread_proxy = False
    for s in items:
        assert s.fact.risk_class is not None and s.market_value is not None  # the gate checked both
        spread = s.fact.modified_duration
        spread_proxy = spread_proxy or (s.fact.risk_class is RiskClass.DEBT_MTM and spread is not None)
        holdings.append(BudgetHolding(s.fact.instrument_id, s.fact.risk_class, s.market_value,
                                      s.fact.modified_duration, spread, s.fact.credit))  # fmt: skip
    res = loss_budget(
        goal.goal_id, loss_budget_inr=goal.loss_budget_inr, holdings=holdings, stress_table=stress,
        recovery_tolerance_months=goal.recovery_months, planned_value=goal.target_amount or None,
        debt_shock=b.inputs.debt_shock,
    )  # fmt: skip
    flags = set(res.flags)
    if spread_proxy:
        flags.add("SPREAD_DURATION_FROM_MODIFIED_DURATION_CONSERVATIVE")
    summary.update(
        outcome=res.outcome.value, flags=sorted(flags), stress_loss=str(res.stress_loss),
        loss_budget_inr=None if res.loss_budget_inr is None else str(res.loss_budget_inr),
        e_cap=None if res.e_cap is None else str(res.e_cap),
        worst_recovery_years=None if res.worst_recovery_years is None else str(res.worst_recovery_years),
    )  # fmt: skip
    if res.outcome is Outcome.BREACH:
        assert goal.loss_budget_inr is not None
        facts = [f for s in items for f in s.fact.fact_ids]
        stress_loss = money(res.stress_loss)
        excess = money(res.excess_stress_loss)
        redirect = _redirect_amount(res)
        numbers = [
            _num("loss_limit", goal.loss_budget_inr, NumberUnit.INR, as_of,
                 facts=[f"user:goal:{goal.goal_id}.loss_budget_inr"]),
            _num("stress_loss", stress_loss, NumberUnit.INR, as_of, facts=facts, formula="risk.loss_budget@1"),
            _num("excess", excess, NumberUnit.INR, as_of, facts=facts, formula="risk.loss_budget@1"),
        ]  # fmt: skip
        steps: list[Step] = []
        if redirect is not None:
            numbers.append(_num("redirect_amount", redirect, NumberUnit.INR, as_of, facts=facts,
                                formula=REDIRECT_FORMULA))  # fmt: skip
            steps.append(Step(Verb.REDIRECT_SIP, None, REDIRECT_FORMULA, amount_inr=redirect))
        else:
            b.flags.add("LOSS_BUDGET_REDIRECT_NOT_COMPUTABLE")
        b.card(
            CardKind.LOSS_BUDGET_BREACH, Layer.L3, RULE_LOSS_BUDGET, goal_id=goal.goal_id,
            template_id="loss_budget_breach",
            status=_stress_status(stress, {h.risk_class for h in holdings}), numbers=numbers, steps=steps,
            impact=Impact(excess, ImpactBasis.AMOUNT_AT_RISK, "excess"),
            text_slots={"goal_name": goal.name, "debt_sleeve": "your debt sleeve"},
        )  # fmt: skip
    elif res.outcome is Outcome.ABSTAIN:
        _abstain_card(b, RiskLayer.L3, goal.goal_id, [_risk_abstention(a) for a in res.abstentions])
    return summary


# --- L4 household ------------------------------------------------------------------------------------------------

_LIMIT_SCOPE = {LimitKind.FACTOR: "your equity"}
_LIMIT_PARAM = {
    LimitKind.SCHEME: "c_scheme", LimitKind.AMC: "c_amc", LimitKind.THEME: "c_theme", LimitKind.FACTOR: "c_factor",
    LimitKind.ISSUER: "c_issuer",
}  # fmt: skip


def _l4(b: _Builder, all_holdings: Sequence[ScopeHolding]) -> dict[str, Any]:
    inputs = b.inputs
    as_of = inputs.as_of
    gate = evaluate_scope(
        HOUSEHOLD_SCOPE, RiskLayer.L4,
        {ITEM_LIMITS_POLICY: _user(ITEM_LIMITS_POLICY, inputs.limits),
         ITEM_HOLDINGS_VALUED: _valued(all_holdings), ITEM_HOLDINGS_CLASSIFIED: _classified(all_holdings)},
        as_of,
    )  # fmt: skip
    summary: dict[str, Any] = {"gate": _gate_summary(gate)}
    if not gate.result.complete or inputs.limits is None:
        _abstain_card(b, RiskLayer.L4, None, [_gap_abstention(g, "household") for g in gate.result.blocking])
        summary["outcome"] = Outcome.ABSTAIN.value
        return summary
    holdings = []
    for s in all_holdings:
        assert s.fact.risk_class is not None and s.market_value is not None
        rc = s.fact.risk_class
        # theme=None: no sector/theme attribute is collected yet. The SEBI category text ("Sectoral/ Thematic") is
        # shared by unrelated sectors, so grouping by it would sum banking + pharma + tech into one "theme" and
        # raise a VERIFIED breach no single theme has (python-reviewer-3). The theme limit abstains below instead.
        holdings.append(LimitHolding(
            s.fact.instrument_id, rc, s.market_value, scheme_id=s.fact.instrument_id, amc=s.fact.amc, theme=None,
            is_factor=rc is RiskClass.EQ_FACTOR,
        ))  # fmt: skip
    res: LimitsResult = check_limits(holdings, inputs.limits)
    themed = sorted(
        {s.fact.name for s in all_holdings if s.fact.risk_class is RiskClass.EQ_SECTOR_THEMATIC and s.market_value}
    )
    theme_gap = (
        [Abstention(
            code="theme_unknown", missing_input="the sector or theme of " + ", ".join(themed),
            how_to_fix=("no sector or theme is recorded for these schemes yet, so the theme limit cannot be checked"
                        " (their SEBI category is shared by unrelated sectors and is not a theme)"),
        )]
        if themed else []
    )  # fmt: skip
    outcome = Outcome.ABSTAIN if theme_gap and res.outcome is Outcome.PASS else res.outcome
    summary.update(outcome=outcome.value, findings=len(res.findings), theme="UNKNOWN" if theme_gap else None)
    names = {s.fact.instrument_id: s.fact.name for s in all_holdings}
    pv = inputs.policy_version_id
    for f in res.findings:
        if f.kind is LimitKind.BANK_DEPOSIT or f.share is None:
            continue
        members = sorted(
            h.holding_id for h in holdings
            if (f.kind is LimitKind.SCHEME and h.scheme_id == f.key) or (f.kind is LimitKind.AMC and h.amc == f.key)
            or (f.kind is LimitKind.THEME and h.theme == f.key) or (f.kind is LimitKind.FACTOR and h.is_factor)
            or (f.kind is LimitKind.ISSUER and h.uninsured_issuer == f.key)
        )  # fmt: skip
        base = res.equity_value if f.kind is LimitKind.FACTOR else res.total_value
        with engine_context():
            excess = money(max(ZERO, f.exposure - f.cap * base))
        facts = [x for s in all_holdings if s.fact.instrument_id in members for x in s.fact.fact_ids]
        param_fact = f"user:policy:{pv}.limits.{_LIMIT_PARAM[f.kind]}"
        holding_name = names.get(f.key, f.key) if f.kind is LimitKind.SCHEME else f.key
        if f.kind is LimitKind.FACTOR:
            holding_name = "your factor funds"
        b.card(
            CardKind.LIMIT_BREACH, Layer.L4, (f"risk.limits.{f.kind.value.lower()}", 1), goal_id=None,
            template_id="limit_breach", status=CardStatus.VERIFIED,
            numbers=[
                _num("actual_share", f.share, NumberUnit.PCT, as_of, facts=facts, formula="risk.limits@1"),
                _num("limit_share", f.cap, NumberUnit.PCT, as_of, facts=[param_fact]),
                _num("excess", excess, NumberUnit.INR, as_of, facts=[*facts, param_fact],
                     formula=LIMIT_EXCESS_FORMULA),
            ],
            steps=[Step(Verb.REDIRECT_SIP, iid, "risk.limits@1") for iid in members],
            impact=Impact(excess, ImpactBasis.AMOUNT_TO_MOVE, "excess"),
            text_slots={"holding_name": holding_name, "scope_name": _LIMIT_SCOPE.get(f.kind, "your portfolio")},
        )  # fmt: skip
    if res.abstentions or theme_gap:
        _abstain_card(b, RiskLayer.L4, None, [*(_risk_abstention(a) for a in res.abstentions), *theme_gap])
    return summary


# --- assembly ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    as_of: date
    rules_version: str
    input_manifest_hash: str
    verdict: str
    card_set_hash: str
    payload_json: str
    cards: tuple[ActionCard, ...]
    needs: tuple[Need, ...]


def rules_version(inputs: SnapshotInputs, templates: TemplateSet) -> str:
    return "|".join((inputs.stress_table_version, templates.version, GOAL_MANIFEST_VERSION, CONTRACT_VERSION,
                     RANKING_VERSION, NEEDS_VERSION))  # fmt: skip


def snapshot_identity(inputs: SnapshotInputs, templates: TemplateSet) -> tuple[str, str, str]:
    """``(snapshot_id, input_manifest_hash, rules_version)``, all content-derived."""
    rv = rules_version(inputs, templates)
    manifest_hash = content_hash(inputs)
    sid = content_hash({"engine_version": ENGINE_VERSION, "rules_version": rv, "input_manifest_hash": manifest_hash})
    return sid, manifest_hash, rv


def _render(card: ActionCard, templates: TemplateSet, slots: Mapping[str, str]) -> dict[str, Any]:
    try:
        r = render_card(card, templates, slots)
    except InvalidInput:
        # A user-supplied name the linter refuses (e.g. it carries an amount): retry with neutral names, then give up
        # on text (the numbers still carry their provenance).
        neutral = {k: ("this goal" if k == "goal_name" else v) for k, v in slots.items()}
        try:
            r = render_card(card, templates, neutral)
        except InvalidInput:
            return {"text": None, "text_error": "RENDER_REFUSED", "displays": []}
    return {
        "text": r.text,
        "displays": [{"slot": d.slot, "display": d.display, "fact_ids": list(d.fact_ids), "formula_id": d.formula_id}
                     for d in r.numbers],
    }  # fmt: skip


def _card_json(card: ActionCard, templates: TemplateSet, slots: Mapping[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(canonical_json(card))
    out["card_class"] = card.card_class.value
    out["is_action"] = card.is_action
    out["rule_ref"] = card.why.rule_ref
    out["card_key"] = notify.card_key(card)  # snapshot-independent: carries an unchecked "I did this" forward
    out.update(_render(card, templates, slots))
    return out


def card_identity(card: ActionCard) -> list[Any]:
    """A card's identity WITHOUT the snapshot id, so the L1–L5 set can be compared across days (ping on change)."""
    return [card.kind.value, card.why.rule_ref, card.goal_id, list(card.instrument_ids)]


def compute_snapshot(inputs: SnapshotInputs, templates: TemplateSet) -> Snapshot:
    """Pure: the same inputs and templates always give the same snapshot, byte for byte."""
    sid, manifest_hash, rv = snapshot_identity(inputs, templates)
    b = _Builder(inputs, templates, sid, manifest_hash, rv, flags=set(inputs.flags))
    per_goal, unassigned, split_flags, folio_goals = _scope_holdings(inputs)
    b.flags |= split_flags
    if inputs.invalid_portfolios:
        _integrity_card(b, None, [
            Abstention(
                code="portfolio_ledger_invalid",
                missing_input=f"a valid transaction history for portfolio {pid} ({code})",
                how_to_fix=("re-import the CAS statement or correct the transaction in that portfolio; until then no"
                            " card is computed from your holdings"),
            )
            for pid, code in inputs.invalid_portfolios
        ], "a valid transaction history for every portfolio")  # fmt: skip
    goal_names = {g.goal_id: g.name for g in inputs.goals}
    for gid in sorted(folio_goals):
        _integrity_card(b, gid, [
            Abstention(
                code="folio_link_not_applied",
                missing_input=f'a goal mapping without a folio for {iid} (goal "{goal_names[gid]}")',
                how_to_fix=("map the whole holding to the goal (no folio) on the Goals page; a folio-level mapping"
                            " is not applied yet, so this goal is not checked without it"),
            )
            for iid in folio_goals[gid]
        ], "a goal mapping that can be applied")  # fmt: skip
    whole = [ScopeHolding(h, Decimal(1), h.market_value) for h in inputs.holdings]

    household: dict[str, Any] = {"scope_id": HOUSEHOLD_SCOPE, "layers": {}}
    household["layers"]["L1"] = _l1(b, whole)
    household["layers"]["L4"] = _l4(b, whole)
    b.scopes.append(household)

    for goal in inputs.goals:
        items = per_goal[goal.goal_id]
        values = _goal_values(goal, items)
        with engine_context():
            value = sum((s.market_value for s in items if s.market_value is not None), ZERO)
        b.scopes.append({
            "scope_id": goal.goal_id, "name": goal.name, "priority": goal.priority, "value": str(value),
            "layers": {"L2": _l2(b, goal, items, values), "L3": _l3(b, goal, items, values)},
        })  # fmt: skip

    portfolio_gaps: list[Abstention] = []
    if not inputs.goals:
        portfolio_gaps.append(Abstention("goals_missing", "at least one goal with a loss limit",
                                         "create a goal and enter its loss limit on the Goals page"))  # fmt: skip
    with engine_context():
        unassigned_value = sum((s.market_value or ZERO for s in unassigned), ZERO)
    if any(s.fraction > 0 for s in unassigned) and inputs.holdings:
        portfolio_gaps.append(Abstention(
            "holdings_unassigned", "a goal for every holding",
            "map each holding to a goal on the Goals page; unmapped holdings get no loss-limit check",
        ))  # fmt: skip
    if portfolio_gaps:
        _abstain_card(b, RiskLayer.L3, None, portfolio_gaps)
    b.scopes.append({"scope_id": UNASSIGNED_SCOPE, "value": str(unassigned_value),
                     "instrument_ids": sorted({s.fact.instrument_id for s in unassigned})})  # fmt: skip

    ranked = rank_cards(b.cards)
    if ranked.state is TodayState.NOTHING_NEEDED and not b.cards:
        b.card(
            CardKind.NO_ACTION_NEEDED, Layer.L8, ("risk.snapshot", 1), goal_id=None, template_id="no_action_needed",
            status=CardStatus.VERIFIED,
            numbers=[_num("as_of", inputs.as_of, NumberUnit.DATE, inputs.as_of, formula=SNAPSHOT_FORMULA)],
        )  # fmt: skip
        ranked = rank_cards(b.cards)
    needs = collect_needs(b.cards)
    verdict = {TodayState.ACTIONS: VERDICT_ACTIONS, TodayState.NOTHING_NEEDED: VERDICT_NOTHING}.get(
        ranked.state, VERDICT_ABSTAIN
    )
    # "Ping only on change" key (B04 notify.card_set_hash: snapshot-independent card keys, layers L1-L5), over the
    # ACTION cards only, so abstentions and the empty state never ping.
    card_set_hash = notify.card_set_hash(c for c in ranked.ordered if c.is_action)
    payload = {
        "schema": PAYLOAD_SCHEMA,
        "snapshot_id": sid,
        "as_of": inputs.as_of,
        "engine_version": ENGINE_VERSION,
        "rules_version": rv,
        "input_manifest_hash": manifest_hash,
        "verdict": verdict,
        "state": ranked.state.value,
        "cards": [_card_json(c, templates, b.texts[c.card_id]) for c in ranked.ordered],
        "shown_count": len(ranked.shown),
        "more_count": ranked.more_count,
        "suppressed": [
            {"suppressed_by": s.suppressed_by, "card": _card_json(s.card, templates, b.texts[s.card.card_id])}
            for s in ranked.suppressed
        ],
        "needs": [json.loads(canonical_json(n)) for n in needs],
        "scopes": b.scopes,
        "footer_ref": templates.footer_ref,
        "flags": sorted(b.flags),
        "card_set_hash": card_set_hash,
    }
    return Snapshot(
        snapshot_id=sid, as_of=inputs.as_of, rules_version=rv, input_manifest_hash=manifest_hash, verdict=verdict,
        card_set_hash=card_set_hash, payload_json=canonical_json(payload), cards=tuple(b.cards), needs=needs,
    )  # fmt: skip


# ------------------------------------------------------------------------------------------------ store


@dataclass(frozen=True)
class SnapshotRun:
    snapshot_id: str
    as_of: date
    verdict: str
    created: bool  # False when an identical snapshot was already stored (re-run)
    card_set_hash: str
    card_set_changed: bool  # vs the previous stored snapshot (a ping fires only on change, package B04)


def store_snapshot(conn: sqlite3.Connection, snap: Snapshot, now: str) -> SnapshotRun:
    """Store a computed snapshot (content-addressed; idempotent) and record this computation as the current one.
    Three statements: the current snapshot's card-set hash, the conditional insert and the run row (plus one more
    only when the id already exists, to verify the stored payload)."""
    prev = conn.execute(
        "SELECT s.card_set_hash FROM snapshot_runs r JOIN signal_snapshots s ON s.snapshot_id = r.snapshot_id"  # noqa: S608
        f" ORDER BY {ledger.LATEST_RUN_ORDER} LIMIT 1"  # module constant
    ).fetchone()
    created = ledger.put_snapshot(
        conn,
        ledger.SignalSnapshot(
            snapshot_id=snap.snapshot_id, as_of_date=snap.as_of.isoformat(), engine_version=ENGINE_VERSION,
            rules_version=snap.rules_version, input_manifest_hash=snap.input_manifest_hash, verdict=snap.verdict,
            card_set_hash=snap.card_set_hash, payload_json=snap.payload_json, created_at=now,
        ),
    )  # fmt: skip
    changed = prev is None or prev["card_set_hash"] != snap.card_set_hash
    return SnapshotRun(snap.snapshot_id, snap.as_of, snap.verdict, created, snap.card_set_hash, changed)


def run_snapshot(
    conn: sqlite3.Connection,
    *,
    as_of: date,
    now: str,
    stress_table: StressTable,
    templates: TemplateSet,
) -> tuple[Snapshot, SnapshotRun]:
    """Load, compute and store one snapshot. The caller owns the transaction."""
    snap = compute_snapshot(load_inputs(conn, as_of, stress_table), templates)
    return snap, store_snapshot(conn, snap, now)


# ------------------------------------------------------------------------------------------------ Today (read side)

# ONE statement: the snapshot of the newest computation (snapshot_runs, so inputs reverted A -> B -> A show A again),
# the decisions already recorded against its cards, and every "I did this" no CAS has checked yet (any snapshot), so
# it can be carried to the same card today (json_group_array is in SQLite's JSON1 and in libSQL). Served by
# ix_snapshot_runs_latest, ix_decisions_log_snapshot and the partial ix_decisions_log_pending_done. The engine never
# runs here.
TODAY_SQL = (
    "SELECT s.snapshot_id, s.as_of_date, s.verdict, s.payload_json, r.computed_at,"  # noqa: S608 - module constant
    " (SELECT json_group_array(json_object('decision_id', d.decision_id, 'card_id', d.card_id,"
    " 'decision', d.decision, 'decided_at', d.decided_at, 'cas_confirmed', d.cas_confirmed))"
    " FROM decisions_log d WHERE d.snapshot_id = s.snapshot_id) AS decisions,"
    " (SELECT json_group_array(json_object('decision_id', p.decision_id, 'card_id', p.card_id,"
    " 'snapshot_id', p.snapshot_id, 'card_key', p.card_key, 'decided_at', p.decided_at))"
    " FROM decisions_log p WHERE p.decision = 'done' AND p.cas_confirmed IS NULL AND p.card_key IS NOT NULL)"
    " AS pending_done"
    " FROM snapshot_runs r JOIN signal_snapshots s ON s.snapshot_id = r.snapshot_id"
    f" ORDER BY {ledger.LATEST_RUN_ORDER} LIMIT 1"
)
NO_SNAPSHOT = "NO_SNAPSHOT"
DECISIONS = ("done", "not_now", "disagree")


def read_today(conn: sqlite3.Connection) -> dict[str, Any]:
    """The Today payload in one statement. With no snapshot yet, a first-class ``NO_SNAPSHOT`` state."""
    row = conn.execute(TODAY_SQL).fetchone()
    if row is None:
        return {"state": NO_SNAPSHOT, "verdict": None, "cards": [], "needs": [], "decisions": []}
    payload: dict[str, Any] = json.loads(row["payload_json"])
    decisions = json.loads(row["decisions"]) if row["decisions"] else []
    decisions += _carried_done(payload, decisions, json.loads(row["pending_done"]) if row["pending_done"] else [])
    payload["decisions"] = sorted(
        decisions, key=lambda d: (d["decided_at"], d["card_id"], d["decision"], d.get("decision_id") or 0)
    )
    payload["computed_at"] = row["computed_at"]
    return payload


def _carried_done(
    payload: Mapping[str, Any], own: Sequence[Mapping[str, Any]], pending: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """An "I did this" that no CAS has checked yet stays attached to the SAME card (same ``card_key``: kind, rule,
    goal, instruments) in later snapshots, so the card does not come back unmarked and invite the same transaction
    twice (design-judgement.md §1 graft 9; silent-failure-hunter-04). A CAS that contradicts it (cas_confirmed = 0)
    ends the carry and the card is shown as open again. Each carried entry names the decision it came from."""
    sid = payload.get("snapshot_id")
    latest: dict[str, Mapping[str, Any]] = {}
    for p in sorted(pending, key=lambda p: (str(p["decided_at"]), int(p["decision_id"]))):
        if p.get("snapshot_id") != sid:
            latest[str(p["card_key"])] = p
    if not latest:
        return []
    marked = {str(d["card_id"]) for d in own if d.get("decision") == "done"}
    out: list[dict[str, Any]] = []
    for c in payload.get("cards", []):
        src = latest.get(str(c.get("card_key")))
        if src is None or not c.get("is_action") or str(c["card_id"]) in marked:
            continue
        out.append({
            "decision_id": src["decision_id"], "card_id": c["card_id"], "decision": "done",
            "decided_at": src["decided_at"], "cas_confirmed": None,
            "carried_from_snapshot_id": src["snapshot_id"], "carried_from_card_id": src["card_id"],
        })  # fmt: skip
    return out


def read_needs(conn: sqlite3.Connection) -> dict[str, Any]:
    """ "Needs from you" from the newest snapshot (the same single statement)."""
    today = read_today(conn)
    return {
        "state": today["state"],
        "snapshot_id": today.get("snapshot_id"),
        "as_of": today.get("as_of"),
        "needs": today.get("needs", []),
    }


_DECISION_ROW_SQL = (
    "SELECT decision_id, decided_at, cas_confirmed FROM decisions_log"
    " WHERE card_id = ? AND snapshot_id = ? AND decision = ? ORDER BY decision_id LIMIT 1"
)


class DecisionRejected(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def record_decision(
    conn: sqlite3.Connection,
    *,
    snapshot_id: str,
    card_id: str,
    decision: str,
    note: str | None,
    now: str,
) -> dict[str, Any]:
    """ "I did this" (or "not now" / "disagree") for one ACTION card of a stored snapshot. Abstain, empty-state and
    shadow-ledger entries cannot be acted on.

    Idempotent per (card_id, snapshot_id, decision): a retry after a network error returns the row already logged
    (``status`` ``already_recorded``) instead of appending a second one. Statements: the snapshot read, the existing
    row lookup, and (only when new) the append-only insert plus the read-back of its ``decision_id``."""
    if decision not in DECISIONS:
        raise DecisionRejected("BAD_DECISION", f"decision must be one of {DECISIONS}")
    row = conn.execute("SELECT payload_json FROM signal_snapshots WHERE snapshot_id = ?", (snapshot_id,)).fetchone()
    if row is None:
        raise DecisionRejected("UNKNOWN_SNAPSHOT", "no such snapshot")
    payload = json.loads(row["payload_json"])
    cards = [*payload.get("cards", []), *(s["card"] for s in payload.get("suppressed", []))]
    card = next((c for c in cards if c.get("card_id") == card_id), None)
    if card is None:
        raise DecisionRejected("UNKNOWN_CARD", "the card is not part of that snapshot")
    if not card.get("is_action"):
        raise DecisionRejected("NOT_AN_ACTION", "only action cards can be marked")
    existing = conn.execute(_DECISION_ROW_SQL, (card_id, snapshot_id, decision)).fetchone()
    status = "already_recorded"
    if existing is None:
        ledger.append_decisions(
            conn,
            [ledger.Decision(card_id=card_id, snapshot_id=snapshot_id, goal_id=card.get("goal_id"), decision=decision,
                             note=note, decided_at=now, card_key=card.get("card_key"))],
        )  # fmt: skip
        existing = conn.execute(_DECISION_ROW_SQL, (card_id, snapshot_id, decision)).fetchone()
        status = "recorded"
    cas = existing["cas_confirmed"]
    return {
        "status": status, "snapshot_id": snapshot_id, "card_id": card_id,
        "decision": {"decision_id": str(existing["decision_id"]), "decision": decision,
                     "decided_at": existing["decided_at"], "cas_confirmed": None if cas is None else bool(cas)},
    }  # fmt: skip


# ------------------------------------------------------------------------------------------------ CAS confirmation

_MOVE_OF_VERB = {"INVEST": "in", "REDEEM": "out", "SWITCH": "out"}


def cas_decision_checks(conn: sqlite3.Connection) -> list[cas_types.DecisionCheck]:
    """ "I did this" entries no CAS has checked yet, with the unit movements their card's steps imply (B06
    :func:`iip.services.cas.moves_from_steps` rules, read from the stored snapshot payload). Two statements: the
    pending decisions and their snapshots. A card whose steps name no scheme (e.g. REDIRECT_SIP) has no movement to
    look for, so the CAS check leaves it UNDETERMINED."""
    from iip.services import cas  # noqa: PLC0415 - cas pulls in the statement parser; only the CAS routes need it

    pending = cas.pending_done_decisions(conn)
    sids = sorted({str(r["snapshot_id"]) for r in pending if r["snapshot_id"]})
    payloads: dict[str, dict[str, Any]] = {}
    if sids:
        for r in conn.execute(
            "SELECT snapshot_id, payload_json FROM signal_snapshots"
            " WHERE snapshot_id IN (SELECT value FROM json_each(?))",
            (json.dumps(sids),),
        ).fetchall():
            payloads[str(r["snapshot_id"])] = json.loads(r["payload_json"])
    checks: list[cas.DecisionCheck] = []
    for r in pending:
        payload = payloads.get(str(r["snapshot_id"]), {})
        cards = [*payload.get("cards", []), *(x["card"] for x in payload.get("suppressed", []))]
        card = next((c for c in cards if c.get("card_id") == r["card_id"]), None)
        moves: list[cas.ExpectedMove] = []
        for step in (card or {}).get("steps", []):
            direction = _MOVE_OF_VERB.get(str(step.get("verb")))
            if direction is not None and step.get("instrument_id"):
                moves.append(cas.ExpectedMove(str(step["instrument_id"]), "in" if direction == "in" else "out"))
        checks.append(cas.DecisionCheck(
            decision_id=int(r["decision_id"]), decided_on=date.fromisoformat(str(r["decided_at"])[:10]),
            moves=tuple(dict.fromkeys(moves)),
        ))  # fmt: skip
    return checks


# ------------------------------------------------------------------------------------------------ J4 (one step)


def cron_snapshot_step(conn: sqlite3.Connection, now: datetime) -> cron_types.SnapshotOutcome:
    """Job J4's snapshot hook for :mod:`iip.services.cron` (resolved there by name): one :func:`run_daily`.

    * ``as_of`` is the DATA date: the newest NAV among the user's holdings, else the newest stored NAV date; never
      the wall clock. With no NAV at all the step refuses (cron reports the failure; nothing is invented).
    * The stress table is the public rule table only. The user's cited stress values live in LOCAL config (U-08),
      which a hosted deployment does not have, so those classes stay REQUIRES CONFIGURATION and their layers abstain.
    * No cost/tax basis is loaded yet (no verified MF-redemption STT row), so shadow outcomes wait for one.

    Returns an :class:`iip.services.cron.SnapshotOutcome` (identifiers and codes only)."""
    from iip.rules.loader import load_action_templates, load_stress_table  # noqa: PLC0415 - keep import cost off J1-J3
    from iip.services import cron  # noqa: PLC0415 - cron resolves this hook by name; avoid an import cycle

    as_of = latest_data_date(conn)
    if as_of is None:
        newest = cron.newest_nav_date(conn)
        if newest is None:
            raise ValueError("no NAV data to compute a snapshot from")
        as_of = date.fromisoformat(newest)
    as_of = min(as_of, now.date())
    daily = run_daily(conn, as_of=as_of, now=now.isoformat(), stress_table=load_stress_table(),
                      templates=load_action_templates())  # fmt: skip
    snap = daily.snapshot
    return cron.SnapshotOutcome(
        snapshot_id=snap.snapshot_id, as_of_date=snap.as_of.isoformat(), verdict=snap.verdict,
        card_set_hash=snap.card_set_hash, written=snap.created,
    )  # fmt: skip


@dataclass(frozen=True)
class DailyRun:
    snapshot: SnapshotRun
    shadow: Any  # iip.services.shadow.ShadowRun
    outcomes: Any  # iip.services.outcomes.OutcomeRun


def run_daily(
    conn: sqlite3.Connection,
    *,
    as_of: date,
    now: str,
    stress_table: StressTable,
    templates: TemplateSet,
    basis: Any = None,
) -> DailyRun:
    """Job J4's compute step (design-risk-first.md §9.1): the risk snapshot, the shadow ledger for every registered
    S rule, then outcomes now due. All-or-nothing in one write transaction. ``as_of`` is the DATA date the job
    targets (the run_key), never the wall clock; ``now`` only stamps rows. ``basis`` is an
    :class:`iip.services.outcomes.CostTaxBasis` or None (then nothing is scored yet)."""
    from iip.services import outcomes  # noqa: PLC0415 - outcomes imports this module's classifier (cycle)

    with write_tx(conn):
        _snap, run = run_snapshot(conn, as_of=as_of, now=now, stress_table=stress_table, templates=templates)
        sh = shadow.run_shadow(conn, as_of=as_of, snapshot_id=run.snapshot_id, now=now)
        oc = outcomes.score_outcomes(conn, as_of=as_of, now=now, basis=basis)
    return DailyRun(run, sh, oc)
