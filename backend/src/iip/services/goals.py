"""Goals, the risk profile, the tax context, the allocation policy and the six-answer setup (PLAN.md wave 2, B01).

What this service guarantees (B01 acceptance checks):

* The loss limit is stored in ₹ per goal (``goals.loss_budget_inr``, A10); the fraction ``b = B / V`` that the loss
  budget engine uses is only derived for display, never stored.
* Every view that carries goal figures puts the **stress history first** — the worst observed historical fall per
  risk class, and what that fall would be on the goal's amount — and carries no return figure at all. A return
  aspiration belongs on the feasibility view (C02), after the user has seen the falls.
* The allocation policy **refuses to load** until the user has set its target weights themselves
  (:class:`PolicyNotConfigured`); band, review cadence and rebalancing mode fall back to the shipped PARAMETER
  defaults (U-04) and are labelled as such.
* Nothing here invents a number. Values the user has not given stay ``None``, and the affected goal abstains.

Stress values come from the public rule table plus the user's local config (U-08) through the rule loader, combined
by the pure engine (``engine/risk/stress.py``: ``max(cited, AMFI-recomputed)``). The AMFI-recomputed drawdowns are
an optional input here; until a caller supplies them every cited value is labelled NOT VERIFIED by the engine.

The clock is the caller's: every function that needs "today" or "now" takes it as an argument.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, ValidationError, model_validator

from iip.engine.money import engine_context, money, rate_store
from iip.engine.ranking import Objective
from iip.engine.risk import Outcome, RiskClass
from iip.engine.risk import Status as EngineStatus
from iip.engine.risk.stress import CitedStress, ClassStress, RecomputedDrawdown, build_stress_table
from iip.rules import loader
from iip.store import goals_repo as repo
from iip.store.db import write_tx

GOAL_ID_PATTERN = r"^g-[0-9a-f]{12}$"
STRESS_ON_AMOUNT_ID = "goals.stress_on_amount@1"  # loss_on_amount = amount × s(class), paise HALF_UP
LOSS_FRACTION_ID = "risk.loss_budget@1#b"  # b = B_g / V_g (design-risk-first.md §5.3)
MAX_INR = Decimal("1000000000000")  # ₹1 lakh crore, as the investor profile
MAX_GOALS_PER_SETUP = 20

CONSERVATIVE_TAX_LABEL = (
    "CONSERVATIVE_ASSUMPTION: highest slab and the LTCG exemption already used elsewhere this FY "
    "(regime and slab not entered)"
)
CONSERVATIVE_LTCG_LABEL = "CONSERVATIVE_ASSUMPTION: the LTCG exemption is assumed already used elsewhere this FY"

STRESS_CAVEATS = (
    "Each value is the worst fall observed in the available history of that kind of fund. It is not a forecast.",
    "The worst observed fall is not the worst possible fall.",
    "About 26-31 years of index history give only about 2 independent 10-year windows, so these are few episodes.",
    "All equity holdings are added as if they fall together (no diversification credit between equity funds).",
)

# Display order of the stress history. STOCK is left out on purpose: no stock data is used (U-10), stocks abstain.
_DISPLAY_ORDER: tuple[RiskClass, ...] = (
    RiskClass.EQ_LARGE,
    RiskClass.EQ_BROAD,
    RiskClass.EQ_MID,
    RiskClass.EQ_SMALL,
    RiskClass.EQ_FACTOR,
    RiskClass.EQ_SECTOR_THEMATIC,
    RiskClass.HYBRID,
    RiskClass.GOLD,
    RiskClass.DEBT_MTM,
    RiskClass.CASH_LIKE,
)


class GoalsError(Exception):
    """A request the service refuses; ``status`` is the HTTP status the route returns."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class PolicyNotConfigured(GoalsError):
    def __init__(self, message: str) -> None:
        super().__init__(409, "POLICY_REQUIRES_USER_VALUES", message)


def _no_float(v: object) -> object:
    if isinstance(v, float):
        raise ValueError("send decimals as strings, not floats")
    return v


Dec = Annotated[Decimal, BeforeValidator(_no_float)]  # Decimal from a string or int; a JSON float is refused


def financial_year(on: date) -> str:
    """Indian financial year (1 April – 31 March) containing ``on``, as ``'2026-27'``."""
    start = on.year if on.month >= 4 else on.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


# ================================================================================================ stress history


class StressRowView(BaseModel):
    risk_class: str
    description: str
    outcome: str  # PASS (a value exists) | ABSTAIN
    stress: Decimal | None  # fraction of value lost in the worst observed fall
    loss_on_amount: Decimal | None  # amount × stress, ₹ (only when an amount is given)
    loss_formula_id: str
    recovery_years: Decimal | None
    episode: str | None
    back_calculated: bool
    chosen: str  # CITED | RECOMPUTED | DERIVED | FIXED | NONE
    status: str  # VERIFIED | NOT VERIFIED | REQUIRES CONFIGURATION
    cited_value: Decimal | None
    recomputed_value: Decimal | None
    series_start: date | None
    series_end: date | None
    source_url: str
    formula_id: str | None
    formula: str | None  # DEBT_MTM: holding-specific, so no single value
    flags: list[str]
    abstentions: list[str]
    # Wire fields for the Goals/Setup pages (C02 types-goals.ts StressHistoryRow); derived, nothing new is computed.
    label: str = ""  # = description
    citation: str | None = None  # = source_url of the rule-table row
    fact_id: str | None = None  # = the rule-table row id the cited value comes from
    abstain_reason: str | None = None  # the missing input, when the row abstains


class StressHistory(BaseModel):
    kind: Literal["HISTORICAL_WORST_OBSERVED_FALL"] = "HISTORICAL_WORST_OBSERVED_FALL"
    table_version: str
    local_values_loaded: bool
    requires_configuration: list[str]
    amount: Decimal | None
    caveats: list[str]
    rows: list[StressRowView]
    caveat: str = ""  # every caveat in one sentence block, shown verbatim (C02 wire field)


def load_stress_rules(data_dir: Path) -> loader.StressTable:
    """Public stress table plus the user's local values (U-08), read on every call so an edited file applies."""
    return loader.load_stress_table(local_values_path=loader.local_stress_values_path(data_dir))


def _cited(table: loader.StressTable) -> dict[RiskClass, CitedStress]:
    out: dict[RiskClass, CitedStress] = {}
    for row in table.rows:
        try:
            rc = RiskClass(row.risk_class)
        except ValueError:
            continue
        value = table.cited_stress(row.risk_class)
        if value is None or row.value_source is loader.ValueSource.ALIAS:
            continue  # aliases (HYBRID) are derived by the engine from their base class
        status = EngineStatus.VERIFIED if row.verification_status is loader.RowStatus.P else EngineStatus.NOT_VERIFIED
        out[rc] = CitedStress(value=value, citation=row.source_url, status=status, recovery_years=row.recovery_years)
    return out


def _loss_on(amount: Decimal | None, stress: Decimal | None) -> Decimal | None:
    if amount is None or stress is None:
        return None
    with engine_context():
        return money(amount * stress)


def stress_history(
    table: loader.StressTable,
    amount: Decimal | None = None,
    recomputed: Mapping[RiskClass, RecomputedDrawdown] | None = None,
) -> StressHistory:
    """The worst observed fall per risk class, and (given ``amount``) what it would be on that amount in ₹."""
    combined: dict[RiskClass, ClassStress] = build_stress_table(cited=_cited(table), recomputed=recomputed or {})
    rows: list[StressRowView] = []
    for rc in _DISPLAY_ORDER:
        meta = table.row(rc.value)
        if rc is RiskClass.DEBT_MTM:
            assert meta.formula is not None  # loader invariant for FORMULA rows
            rows.append(
                StressRowView(
                    risk_class=rc.value, description=meta.description, outcome=Outcome.ABSTAIN.value, stress=None,
                    loss_on_amount=None, loss_formula_id=STRESS_ON_AMOUNT_ID, recovery_years=None,
                    episode=meta.episode, back_calculated=meta.back_calculated, chosen="NONE",
                    status=EngineStatus.NOT_VERIFIED.value, cited_value=None, recomputed_value=None,
                    series_start=None, series_end=None, source_url=meta.source_url,
                    formula_id=meta.formula.formula_id, formula=meta.formula.expression,
                    flags=["PER_HOLDING_DURATION_NEEDED"], abstentions=["duration_missing"],
                    label=meta.description, citation=meta.source_url, fact_id=meta.rule_id,
                    abstain_reason="the duration of each debt holding",
                )
            )  # fmt: skip
            continue
        cs = combined[rc]
        rows.append(
            StressRowView(
                risk_class=rc.value, description=meta.description, outcome=cs.outcome.value, stress=cs.value,
                loss_on_amount=_loss_on(amount, cs.value), loss_formula_id=STRESS_ON_AMOUNT_ID,
                recovery_years=cs.recovery_years, episode=meta.episode, back_calculated=meta.back_calculated,
                chosen=cs.chosen, status=cs.status.value, cited_value=cs.cited_value,
                recomputed_value=cs.recomputed_value, series_start=cs.series_start, series_end=cs.series_end,
                source_url=meta.source_url, formula_id=cs.formula_id, formula=None, flags=list(cs.flags),
                abstentions=[a.code for a in cs.abstentions], label=meta.description, citation=meta.source_url,
                fact_id=meta.rule_id,
                abstain_reason=None if cs.outcome is Outcome.PASS else f"stress value for {rc.value}",
            )
        )  # fmt: skip
    return StressHistory(
        table_version=table.table_version,
        local_values_loaded=table.local_values_loaded,
        requires_configuration=list(table.requires_configuration()),
        amount=amount,
        caveats=list(STRESS_CAVEATS),
        rows=rows,
        caveat=" ".join(STRESS_CAVEATS),
    )


# ================================================================================================ goals


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class GoalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    target_amount: Dec | None = Field(default=None, gt=0, le=MAX_INR)
    target_date: date | None = None
    objective: Objective | None = None
    loss_budget_inr: Dec | None = Field(default=None, ge=0, le=MAX_INR)  # B_g, ₹
    recovery_months: int | None = Field(default=None, ge=0, le=600)  # T_g
    h_safe_years: Dec | None = Field(default=None, ge=0, le=50)
    priority: int | None = Field(default=None, ge=1, le=1000)

    @model_validator(mode="after")
    def _consistent(self) -> GoalIn:
        if (
            self.loss_budget_inr is not None
            and self.target_amount is not None
            and self.loss_budget_inr > self.target_amount
        ):
            raise ValueError("the loss limit cannot be larger than the goal's amount")
        return self


class GoalPatchIn(BaseModel):
    """An update to a stored goal: only the fields the body carries change (GOAL-1).

    An omitted field keeps its stored value; an explicit ``null`` clears it. The name cannot be cleared. The merged
    goal is validated as a whole (:class:`GoalIn`) before anything is written.
    """

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    target_amount: Dec | None = Field(default=None, gt=0, le=MAX_INR)
    target_date: date | None = None
    objective: Objective | None = None
    loss_budget_inr: Dec | None = Field(default=None, ge=0, le=MAX_INR)
    recovery_months: int | None = Field(default=None, ge=0, le=600)
    h_safe_years: Dec | None = Field(default=None, ge=0, le=50)
    priority: int | None = Field(default=None, ge=1, le=1000)

    @model_validator(mode="after")
    def _name_kept(self) -> GoalPatchIn:
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("a goal's name cannot be cleared")
        return self

    def given(self) -> dict[str, Any]:
        """The fields this body carries (explicit ``null`` included), by name."""
        return {k: getattr(self, k) for k in self.model_fields_set if k in GoalIn.model_fields}


class SetupGoalIn(GoalPatchIn):
    """A setup goal: with ``goal_id`` it updates that goal (merge); without it creates one, which needs a name."""

    goal_id: Annotated[str, StringConstraints(pattern=GOAL_ID_PATTERN)] | None = None

    @model_validator(mode="after")
    def _new_goal_named(self) -> SetupGoalIn:
        if self.goal_id is None and self.name is None:
            raise ValueError("a new goal needs a name")
        return self


class WorstFallLine(BaseModel):
    risk_class: str
    stress: Decimal
    loss_on_amount: Decimal
    formula_id: str
    status: str


class GoalHolding(BaseModel):
    instrument_id: str
    folio: str
    name: str
    fraction: Decimal


class GoalView(BaseModel):
    # First: what the worst observed falls would have meant for this goal (no return figure anywhere).
    worst_fall_on_target: list[WorstFallLine]
    recovery_notes: list[str]
    goal_id: str
    name: str
    priority: int
    target_amount: Decimal | None
    target_date: date | None
    objective: Objective | None
    loss_budget_inr: Decimal | None
    loss_budget_fraction: Decimal | None
    loss_budget_fraction_formula_id: str
    recovery_months: int | None
    h_safe_years: Decimal | None
    equity_status: Literal["INPUTS_COMPLETE", "ABSTAIN"]
    missing: list[str]
    # Wire fields for the Goals page (C02 types-goals.ts GoalView).
    holdings: list[GoalHolding] = Field(default_factory=list)
    outcome: Literal["PASS", "ABSTAIN"] = "ABSTAIN"  # PASS = every input the equity layers need is present
    abstentions: list[str] = Field(default_factory=list)  # = missing


_OBJ_BY_LETTER = {o.value[0]: o for o in Objective}


def _letter(o: Objective | None) -> str | None:
    return None if o is None else o.value[0]


def _fmt_years(months: int) -> str:
    with engine_context():
        return f"{(Decimal(months) / Decimal(12)).quantize(Decimal('0.1'))}"


def goal_view(g: repo.Goal, history: StressHistory, holdings: Sequence[GoalHolding] = ()) -> GoalView:
    amount = g.target_amount
    lines: list[WorstFallLine] = []
    notes: list[str] = []
    for row in history.rows:
        if row.stress is None or row.risk_class == RiskClass.CASH_LIKE.value or row.outcome != Outcome.PASS.value:
            continue
        loss = _loss_on(amount, row.stress)
        if loss is not None:
            lines.append(WorstFallLine(risk_class=row.risk_class, stress=row.stress, loss_on_amount=loss,
                                       formula_id=STRESS_ON_AMOUNT_ID, status=row.status))  # fmt: skip
        if (
            g.recovery_months is not None
            and row.recovery_years is not None
            and row.risk_class != RiskClass.HYBRID.value
            and Decimal(g.recovery_months) < row.recovery_years * 12
        ):
            notes.append(
                f"{row.risk_class}: in the worst episode in the available history, recovery took "
                f"{row.recovery_years} years; your limit is {_fmt_years(g.recovery_months)} years. "
                "This is a historical fact, not a prediction."
            )
    missing: list[str] = []
    if g.target_amount is None:
        missing.append("Goal amount (₹)")
    if g.target_date is None:
        missing.append("Goal date")
    if g.loss_budget_inr is None:
        missing.append("Loss limit in ₹ (no equity recommendation until it is set, U-02)")
    if g.recovery_months is None:
        missing.append("Longest wait for a recovery, in months")
    fraction: Decimal | None = None
    if g.loss_budget_inr is not None and g.target_amount is not None and g.target_amount > 0:
        with engine_context():
            fraction = rate_store(g.loss_budget_inr / g.target_amount).normalize()
    return GoalView(
        worst_fall_on_target=lines,
        recovery_notes=notes,
        goal_id=g.goal_id,
        name=g.name,
        priority=g.priority,
        target_amount=g.target_amount,
        target_date=None if g.target_date is None else date.fromisoformat(g.target_date),
        objective=None if g.objective is None else _OBJ_BY_LETTER[g.objective],
        loss_budget_inr=g.loss_budget_inr,
        loss_budget_fraction=fraction,
        loss_budget_fraction_formula_id=LOSS_FRACTION_ID,
        recovery_months=g.recovery_months,
        h_safe_years=g.h_safe_years,
        equity_status="ABSTAIN" if missing else "INPUTS_COMPLETE",
        missing=missing,
        holdings=list(holdings),
        outcome="ABSTAIN" if missing else "PASS",
        abstentions=list(missing),
    )


def goal_holdings(conn: sqlite3.Connection, links: Sequence[repo.GoalLink]) -> dict[str, list[GoalHolding]]:
    """Each goal's mapped holdings with their instrument names (one statement, only when there are links)."""
    names: dict[str, str] = {}
    ids = sorted({link.instrument_id for link in links})
    if ids:
        rows = conn.execute(
            "SELECT instrument_id, name FROM instruments WHERE instrument_id IN (SELECT value FROM json_each(?))",
            (json.dumps(ids),),
        ).fetchall()
        names = {str(r["instrument_id"]): str(r["name"]) for r in rows}
    out: dict[str, list[GoalHolding]] = {}
    for link in links:
        out.setdefault(link.goal_id, []).append(GoalHolding(
            instrument_id=link.instrument_id, folio=link.folio, name=names.get(link.instrument_id, link.instrument_id),
            fraction=link.fraction,
        ))  # fmt: skip
    return out


def _audit(conn: sqlite3.Connection, now: str, action: str, subject: str, fields: Sequence[str]) -> None:
    conn.execute(
        "INSERT INTO audit_events(at, action, subject, detail) VALUES (?, ?, ?, ?)",
        (now, action, subject, json.dumps(sorted(fields))),
    )


def _given(model: BaseModel) -> list[str]:
    return [k for k, v in model.model_dump().items() if v is not None]


def _given_fields(model: BaseModel) -> dict[str, Any]:
    return {k: getattr(model, k) for k in model.model_fields_set}


def _new_goal_id() -> str:
    return "g-" + secrets.token_hex(6)


def _next_priority(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(priority), 0) + 1 AS p FROM goals").fetchone()
    return int(row["p"])


def _get_goal(conn: sqlite3.Connection, goal_id: str) -> repo.Goal | None:
    return next((g for g in repo.list_goals(conn) if g.goal_id == goal_id), None)


def _stored_fields(g: repo.Goal) -> dict[str, Any]:
    """A stored goal as :class:`GoalIn` field values (the base an update merges onto)."""
    return {
        "name": g.name,
        "target_amount": g.target_amount,
        "target_date": None if g.target_date is None else date.fromisoformat(g.target_date),
        "objective": None if g.objective is None else _OBJ_BY_LETTER[g.objective],
        "loss_budget_inr": g.loss_budget_inr,
        "recovery_months": g.recovery_months,
        "h_safe_years": g.h_safe_years,
        "priority": g.priority,
    }


def _merged(base: Mapping[str, Any], given: Mapping[str, Any]) -> GoalIn:
    try:
        return GoalIn.model_validate({**base, **given})
    except ValidationError as exc:
        msg = "; ".join(str(e.get("msg", "")) for e in exc.errors()) or "invalid goal"
        raise GoalsError(422, "INVALID_INPUT", msg) from exc


def _to_goal(goal_id: str, body: GoalIn, priority: int, keep: repo.Goal | None) -> repo.Goal:
    return repo.Goal(
        goal_id=goal_id,
        name=body.name,
        priority=priority,
        target_amount=body.target_amount,
        target_date=None if body.target_date is None else body.target_date.isoformat(),
        objective=_letter(body.objective),
        loss_budget_inr=body.loss_budget_inr,
        recovery_months=body.recovery_months,
        h_safe_years=body.h_safe_years,
        policy_version_id=None if keep is None else keep.policy_version_id,
    )


def _write_goal(conn: sqlite3.Connection, goal_id: str | None, given: Mapping[str, Any], now: str) -> repo.Goal:
    """Create (``goal_id`` None) or update one goal; must run inside a write transaction.

    ``given`` holds only the fields the request carried. An update merges them onto the stored goal (an omitted field
    keeps its value, an explicit ``None`` clears it) and validates the merged goal before writing.
    """
    keep: repo.Goal | None = None
    if goal_id is not None:
        keep = _get_goal(conn, goal_id)
        if keep is None:
            raise GoalsError(404, "GOAL_NOT_FOUND", f"no goal {goal_id}")
    body = _merged({} if keep is None else _stored_fields(keep), given)
    gid = goal_id or _new_goal_id()
    priority = body.priority or (keep.priority if keep is not None else _next_priority(conn))
    goal = _to_goal(gid, body, priority, keep)
    repo.upsert_goals(conn, [goal], now)
    _audit(conn, now, "goal.update" if keep else "goal.create", gid, sorted(given))
    return goal


def save_goal(conn: sqlite3.Connection, goal_id: str | None, body: GoalIn | GoalPatchIn, now: str) -> repo.Goal:
    """Create a goal from a full :class:`GoalIn`, or merge a :class:`GoalPatchIn` onto the stored goal."""
    given = body.given() if isinstance(body, GoalPatchIn) else _given_fields(body)
    with write_tx(conn):
        return _write_goal(conn, goal_id, given, now)


def delete_goal(conn: sqlite3.Connection, goal_id: str, now: str) -> None:
    with write_tx(conn):
        if not repo.delete_goal(conn, goal_id):
            raise GoalsError(404, "GOAL_NOT_FOUND", f"no goal {goal_id}")
        _audit(conn, now, "goal.delete", goal_id, [])


# ================================================================================================ mapping


class LinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_id: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    folio: Annotated[str, StringConstraints(max_length=100)] = ""
    goal_id: Annotated[str, StringConstraints(pattern=GOAL_ID_PATTERN)]
    fraction: Dec = Field(gt=0, le=1)


class MappingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    links: list[LinkIn] = Field(max_length=5000)


class LinkView(BaseModel):
    instrument_id: str
    folio: str
    goal_id: str
    fraction: Decimal


def replace_mapping(conn: sqlite3.Connection, body: MappingIn, now: str) -> None:
    links = [repo.GoalLink(x.instrument_id, x.folio, x.goal_id, x.fraction) for x in body.links]
    try:
        with write_tx(conn):
            repo.replace_goal_map(conn, links, now)
            _audit(conn, now, "goal_map.replace", "holding_goal_map", [f"links={len(links)}"])
    except ValueError as exc:
        raise GoalsError(422, "INVALID_MAPPING", str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise GoalsError(422, "INVALID_MAPPING", "unknown goal or holding in the mapping") from exc


def mapping_view(links: Sequence[repo.GoalLink]) -> list[LinkView]:
    return [LinkView(instrument_id=x.instrument_id, folio=x.folio, goal_id=x.goal_id, fraction=x.fraction)
            for x in links]  # fmt: skip


# ================================================================================================ risk profile


class RiskProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    essential_monthly_expenses: Dec | None = Field(default=None, ge=0, le=MAX_INR)
    emergency_months: int | None = Field(default=None, ge=1, le=60)
    savings_balance: Dec | None = Field(default=None, ge=0, le=MAX_INR)
    sweep_fd_balance: Dec | None = Field(default=None, ge=0, le=MAX_INR)


class RiskProfileView(BaseModel):
    essential_monthly_expenses: Decimal | None
    emergency_months: int | None
    savings_balance: Decimal | None
    sweep_fd_balance: Decimal | None
    missing: list[str]


def risk_profile_view(p: repo.RiskProfile | None) -> RiskProfileView:
    p = p or repo.RiskProfile()
    missing: list[str] = []
    if p.essential_monthly_expenses is None:
        missing.append("Essential monthly expenses (₹)")
    if p.emergency_months is None:
        missing.append("Emergency fund size in months")
    return RiskProfileView(
        essential_monthly_expenses=p.essential_monthly_expenses, emergency_months=p.emergency_months,
        savings_balance=p.savings_balance, sweep_fd_balance=p.sweep_fd_balance, missing=missing,
    )  # fmt: skip


def _write_risk_profile(conn: sqlite3.Connection, body: RiskProfileIn, now: str) -> None:
    repo.set_risk_profile(conn, repo.RiskProfile(**body.model_dump()), now)
    _audit(conn, now, "risk_profile.update", "risk_profile", _given(body))


def save_risk_profile(conn: sqlite3.Connection, body: RiskProfileIn, now: str) -> None:
    with write_tx(conn):
        _write_risk_profile(conn, body, now)


# ================================================================================================ tax context


class TaxIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use_conservative_assumption: bool = False
    regime: Literal["new", "old"] | None = None
    slab_rate: Dec | None = Field(default=None, ge=0, le=Decimal("0.5"))
    residency: Literal["resident", "non_resident"] | None = None
    ltcg_used_inr: Dec | None = Field(default=None, ge=0, le=MAX_INR)

    @model_validator(mode="after")
    def _exclusive(self) -> TaxIn:
        if self.use_conservative_assumption and (
            self.regime is not None or self.slab_rate is not None or self.ltcg_used_inr is not None
        ):
            raise ValueError("either enter regime, slab and LTCG used, or choose the conservative assumption")
        return self


class TaxContextView(BaseModel):
    fy: str
    regime: str | None
    slab_rate: Decimal | None
    residency: str | None
    ltcg_used_inr: Decimal | None
    ltcg_used_assumed: bool
    assumption: str | None
    answered: bool


def tax_view(fy: str, ctx: repo.TaxContext | None) -> TaxContextView:
    c = ctx or repo.TaxContext(fy=fy)
    if c.regime is None or c.slab_rate is None:
        assumption: str | None = CONSERVATIVE_TAX_LABEL
    elif c.ltcg_used_assumed:
        assumption = CONSERVATIVE_LTCG_LABEL
    else:
        assumption = None
    return TaxContextView(
        fy=c.fy, regime=c.regime, slab_rate=c.slab_rate, residency=c.residency, ltcg_used_inr=c.ltcg_used_inr,
        ltcg_used_assumed=c.ltcg_used_assumed, assumption=assumption, answered=ctx is not None,
    )  # fmt: skip


def _write_tax(conn: sqlite3.Connection, fy: str, body: TaxIn, now: str) -> None:
    ctx = repo.TaxContext(
        fy=fy,
        regime=body.regime,
        slab_rate=body.slab_rate,
        residency=body.residency,
        ltcg_used_inr=body.ltcg_used_inr,
        ltcg_used_assumed=body.ltcg_used_inr is None,
    )
    repo.set_tax_context(conn, ctx, now)
    _audit(conn, now, "tax_context.update", fy, _given(body))


def save_tax(conn: sqlite3.Connection, fy: str, body: TaxIn, now: str) -> None:
    with write_tx(conn):
        _write_tax(conn, fy, body, now)


# ================================================================================================ policy

_POLICY_SCHEMA = "user-policy@1"
_PARAM_NAMES = ("band_abs", "review_cadence", "rebalance_mode")


class PolicyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decided_on: date
    targets: list[dict[str, Any]] = Field(max_length=200)
    band_abs: Dec | None = Field(default=None, gt=0, lt=1)
    review_cadence: Literal["ANNUAL", "SEMI_ANNUAL"] | None = None
    rebalance_mode: Literal["CASH_FLOW_ONLY", "SALES_ALLOWED"] | None = None


class PolicyParameterView(BaseModel):
    parameter: str
    value: Decimal | str
    set_by: Literal["user", "PARAMETER_DEFAULT"]


class TargetView(BaseModel):
    band_id: str
    objective: str
    weights: dict[str, Decimal]
    decided_on: date


class PolicyView(BaseModel):
    status: Literal["USER_SET"] = "USER_SET"
    policy_version_id: int
    policy_hash: str
    decided_at: str
    structure_version: str
    targets: list[TargetView]
    parameters: list[PolicyParameterView]


class PolicyStatus(BaseModel):
    status: Literal["USER_SET", "REQUIRES CONFIGURATION"]
    policy_version_id: int | None
    decided_at: str | None
    reason: str | None


class LoadedPolicy(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    view: PolicyView
    targets: tuple[loader.UserTarget, ...]


def _validated_targets(
    structure: loader.AllocationPolicy, rows: Sequence[Mapping[str, Any]]
) -> tuple[loader.UserTarget, ...]:
    if not rows:
        raise PolicyNotConfigured("the policy has no target weights set by you; the engine never invents them")
    for raw in rows:
        for w in dict(raw.get("weights") or {}).values():
            _no_float(w)
    try:
        return loader.parse_user_targets(structure, rows)
    except loader.RuleTableError as exc:
        raise GoalsError(422, "INVALID_POLICY", str(exc)) from exc


def save_policy(conn: sqlite3.Connection, body: PolicyIn, today: date, now: str) -> PolicyView:
    if body.decided_on > today:
        raise GoalsError(422, "INVALID_POLICY", "the decision date cannot be in the future")
    structure = loader.load_allocation_policy()
    try:
        targets = _validated_targets(structure, body.targets)
    except PolicyNotConfigured as exc:
        raise GoalsError(422, exc.code, exc.message) from exc
    params: dict[str, Any] = {
        name: (str(v) if isinstance(v, Decimal) else v)
        for name in _PARAM_NAMES
        if (v := getattr(body, name)) is not None
    }
    policy = {
        "schema": _POLICY_SCHEMA,
        "structure_version": structure.table_version,
        "targets": [
            {"band_id": t.band_id, "objective": t.objective, "decided_on": t.decided_on.isoformat(), "set_by": "user",
             "weights": {s: str(w) for s, w in t.weights}}
            for t in targets
        ],
        "parameters": params,
    }  # fmt: skip
    with write_tx(conn):
        version_id, created = repo.append_policy_version(conn, policy, body.decided_on.isoformat(), now)
        if created:
            _audit(conn, now, "policy.version", str(version_id), [*params, f"targets={len(targets)}"])
    return load_policy(conn).view


def load_policy(conn: sqlite3.Connection) -> LoadedPolicy:
    """The latest user policy, re-validated. Refuses (``PolicyNotConfigured``) when the user has not set targets."""
    pv = repo.latest_policy_version(conn)
    if pv is None:
        raise PolicyNotConfigured("no policy has been set; enter your target weights first")
    body = pv.policy
    if body.get("schema") != _POLICY_SCHEMA:
        raise PolicyNotConfigured(f"policy version {pv.policy_version_id} has an unknown schema")
    structure = loader.load_allocation_policy()
    raw_targets = body.get("targets") or []
    if any(t.get("set_by") != "user" for t in raw_targets):
        raise PolicyNotConfigured("every target weight must be set by you")
    targets = _validated_targets(structure, raw_targets)
    stored = body.get("parameters") or {}
    params: list[PolicyParameterView] = []
    for name in _PARAM_NAMES:
        if name in stored:
            v = stored[name]
            params.append(PolicyParameterView(parameter=name, value=Decimal(v) if name == "band_abs" else v,
                                              set_by="user"))  # fmt: skip
        else:
            params.append(PolicyParameterView(parameter=name, value=structure.parameter(name),
                                              set_by="PARAMETER_DEFAULT"))  # fmt: skip
    view = PolicyView(
        policy_version_id=pv.policy_version_id,
        policy_hash=pv.policy_hash,
        decided_at=pv.decided_at,
        structure_version=str(body.get("structure_version")),
        targets=[
            TargetView(band_id=t.band_id, objective=t.objective, weights=dict(t.weights), decided_on=t.decided_on)
            for t in targets
        ],
        parameters=params,
    )
    return LoadedPolicy(view=view, targets=targets)


def policy_status(conn: sqlite3.Connection) -> PolicyStatus:
    try:
        v = load_policy(conn).view
    except PolicyNotConfigured as exc:
        return PolicyStatus(status="REQUIRES CONFIGURATION", policy_version_id=None, decided_at=None,
                            reason=exc.message)  # fmt: skip
    return PolicyStatus(status="USER_SET", policy_version_id=v.policy_version_id, decided_at=v.decided_at, reason=None)


# ================================================================================================ overview and setup


class Answers(BaseModel):
    given: int
    of: int
    missing: list[str]


class GoalsOverview(BaseModel):
    # Stress history first, before any goal figure. This view carries no return figure.
    stress_history: StressHistory
    answers: Answers
    goals: list[GoalView]
    mapping: list[LinkView]
    risk_profile: RiskProfileView
    tax_context: TaxContextView
    policy: PolicyStatus
    # Wire fields for the Goals page (C02 types-goals.ts GoalsView).
    as_of: date | None = None
    setup_complete: bool = False
    missing: list[str] = Field(default_factory=list)


_ANSWERS = (
    "Essential monthly expenses (₹)",
    "Emergency fund size in months",
    "At least one goal with its amount and date",
    "A loss limit in ₹ for every goal",
    "The longest wait for a recovery for every goal",
    "Tax regime and slab, or the conservative assumption",
)


def _answers(ctx: repo.GoalContext) -> Answers:
    rp, goals = ctx.risk_profile, ctx.goals
    flags = (
        rp is not None and rp.essential_monthly_expenses is not None,
        rp is not None and rp.emergency_months is not None,
        bool(goals) and all(g.target_amount is not None and g.target_date is not None for g in goals),
        bool(goals) and all(g.loss_budget_inr is not None for g in goals),
        bool(goals) and all(g.recovery_months is not None for g in goals),
        ctx.tax_context is not None,
    )
    return Answers(given=sum(flags), of=len(_ANSWERS), missing=[q for q, ok in zip(_ANSWERS, flags, strict=True)
                                                               if not ok])  # fmt: skip


def overview(conn: sqlite3.Connection, table: loader.StressTable, today: date) -> GoalsOverview:
    fy = financial_year(today)
    ctx = repo.load_goal_context(conn, fy)
    history = stress_history(table)
    held = goal_holdings(conn, ctx.links)
    answers = _answers(ctx)
    return GoalsOverview(
        stress_history=history,
        answers=answers,
        goals=[goal_view(g, history, held.get(g.goal_id, ())) for g in ctx.goals],
        mapping=mapping_view(ctx.links),
        risk_profile=risk_profile_view(ctx.risk_profile),
        tax_context=tax_view(fy, ctx.tax_context),
        policy=policy_status(conn),
        as_of=today,
        setup_complete=answers.given == answers.of,
        missing=list(answers.missing),
    )


class SetupIn(BaseModel):
    """The about-six answers of onboarding (the CAS upload is its own route)."""

    model_config = ConfigDict(extra="forbid")

    essential_monthly_expenses: Dec | None = Field(default=None, ge=0, le=MAX_INR)
    emergency_months: int | None = Field(default=None, ge=1, le=60)
    goals: list[SetupGoalIn] = Field(default_factory=list, max_length=MAX_GOALS_PER_SETUP)
    tax: TaxIn | None = None
    savings_balance: Dec | None = Field(default=None, ge=0, le=MAX_INR)
    sweep_fd_balance: Dec | None = Field(default=None, ge=0, le=MAX_INR)


def setup(conn: sqlite3.Connection, body: SetupIn, fy: str, now: str) -> None:
    """Store every answer in one transaction: all of it or nothing."""
    with write_tx(conn):
        if any(v is not None for v in (body.essential_monthly_expenses, body.emergency_months, body.savings_balance,
                                        body.sweep_fd_balance)):  # fmt: skip
            current = repo.get_risk_profile(conn) or repo.RiskProfile()
            merged = RiskProfileIn(
                essential_monthly_expenses=(
                    body.essential_monthly_expenses
                    if body.essential_monthly_expenses is not None
                    else current.essential_monthly_expenses
                ),
                emergency_months=body.emergency_months
                if body.emergency_months is not None
                else current.emergency_months,
                savings_balance=body.savings_balance if body.savings_balance is not None else current.savings_balance,
                sweep_fd_balance=(
                    body.sweep_fd_balance if body.sweep_fd_balance is not None else current.sweep_fd_balance
                ),
            )
            _write_risk_profile(conn, merged, now)
        for g in body.goals:
            _write_goal(conn, g.goal_id, g.given(), now)
        if body.tax is not None:
            _write_tax(conn, fy, body.tax, now)


# ================================================================================================ setup wire (C02)
# GET/PUT /api/goals/setup speak the Setup page's shapes (frontend/src/lib/types-goals.ts SetupState/SetupAnswers).
# They are a re-arrangement of the same stores the six-answer POST /api/goals/setup writes; nothing new is computed.


class WireTax(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use_conservative: bool = False
    regime: Literal["new", "old"] | None = None
    slab_rate: Dec | None = Field(default=None, ge=0, le=Decimal("0.5"))


class WireEmergency(BaseModel):
    model_config = ConfigDict(extra="forbid")

    essential_monthly_expenses: Dec | None = Field(default=None, ge=0, le=MAX_INR)
    months: int | None = Field(default=None, ge=1, le=60)  # engine/risk/emergency.py rejects 0


class WireExtras(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ltcg_used_inr: Dec | None = Field(default=None, ge=0, le=MAX_INR)
    savings_balance: Dec | None = Field(default=None, ge=0, le=MAX_INR)
    sweep_fd_balance: Dec | None = Field(default=None, ge=0, le=MAX_INR)


class SetupAnswersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tax: WireTax = Field(default_factory=WireTax)
    emergency: WireEmergency = Field(default_factory=WireEmergency)
    goals: list[SetupGoalIn] = Field(default_factory=list, max_length=MAX_GOALS_PER_SETUP)
    extras: WireExtras = Field(default_factory=WireExtras)

    def to_setup(self) -> SetupIn:
        t, x = self.tax, self.extras
        answered = t.use_conservative or t.regime is not None or t.slab_rate is not None or x.ltcg_used_inr is not None
        tax = (
            TaxIn(use_conservative_assumption=t.use_conservative, regime=t.regime, slab_rate=t.slab_rate,
                  ltcg_used_inr=x.ltcg_used_inr)
            if answered
            else None
        )  # fmt: skip
        return SetupIn(
            essential_monthly_expenses=self.emergency.essential_monthly_expenses,
            emergency_months=self.emergency.months,
            goals=self.goals,
            tax=tax,
            savings_balance=x.savings_balance,
            sweep_fd_balance=x.sweep_fd_balance,
        )


class SetupGoalOut(BaseModel):
    goal_id: str
    name: str
    priority: int
    target_amount: Decimal | None
    target_date: date | None
    objective: Objective | None
    loss_budget_inr: Decimal | None
    recovery_months: int | None
    h_safe_years: Decimal | None


class SetupAnswersOut(BaseModel):
    tax: dict[str, Any]
    emergency: dict[str, Any]
    goals: list[SetupGoalOut]
    extras: dict[str, Any]


class SetupState(BaseModel):
    # Stress history first, before any answer (B01 acceptance; C02 relies on it).
    stress_history: StressHistory
    answers: SetupAnswersOut
    cas_imported: bool
    missing: list[str]
    complete: bool


def cas_imported(conn: sqlite3.Connection) -> bool:
    """True once a CAS import batch has been APPLIED (the import ledger in ``settings``; one statement)."""
    for r in conn.execute("SELECT value_json FROM settings WHERE key LIKE 'import.batch:%'").fetchall():
        rec = json.loads(r["value_json"])
        if rec.get("kind") == "cas_pdf" and rec.get("status") == "applied":
            return True
    return False


def setup_state(conn: sqlite3.Connection, table: loader.StressTable, today: date) -> SetupState:
    fy = financial_year(today)
    ctx = repo.load_goal_context(conn, fy)
    rp, tc = ctx.risk_profile or repo.RiskProfile(), ctx.tax_context
    answers = _answers(ctx)
    conservative = tc is not None and tc.regime is None and tc.slab_rate is None and tc.ltcg_used_inr is None
    return SetupState(
        stress_history=stress_history(table),
        answers=SetupAnswersOut(
            tax={"use_conservative": conservative, "regime": tc.regime if tc else None,
                 "slab_rate": tc.slab_rate if tc else None},
            emergency={"essential_monthly_expenses": rp.essential_monthly_expenses, "months": rp.emergency_months},
            goals=[
                SetupGoalOut(
                    goal_id=g.goal_id, name=g.name, priority=g.priority, target_amount=g.target_amount,
                    target_date=None if g.target_date is None else date.fromisoformat(g.target_date),
                    objective=None if g.objective is None else _OBJ_BY_LETTER[g.objective],
                    loss_budget_inr=g.loss_budget_inr, recovery_months=g.recovery_months, h_safe_years=g.h_safe_years,
                )
                for g in ctx.goals
            ],
            extras={"ltcg_used_inr": tc.ltcg_used_inr if tc else None, "savings_balance": rp.savings_balance,
                    "sweep_fd_balance": rp.sweep_fd_balance},
        ),
        cas_imported=cas_imported(conn),
        missing=list(answers.missing),
        complete=answers.given == answers.of,
    )  # fmt: skip


__all__ = [
    "CONSERVATIVE_LTCG_LABEL",
    "CONSERVATIVE_TAX_LABEL",
    "GOAL_ID_PATTERN",
    "STRESS_ON_AMOUNT_ID",
    "GoalIn",
    "GoalPatchIn",
    "GoalView",
    "GoalsError",
    "GoalsOverview",
    "LinkIn",
    "MappingIn",
    "PolicyIn",
    "PolicyNotConfigured",
    "RiskProfileIn",
    "SetupAnswersIn",
    "SetupIn",
    "SetupState",
    "StressHistory",
    "TaxIn",
    "delete_goal",
    "financial_year",
    "goal_view",
    "load_policy",
    "load_stress_rules",
    "overview",
    "replace_mapping",
    "save_goal",
    "save_policy",
    "save_risk_profile",
    "save_tax",
    "setup",
    "setup_state",
    "stress_history",
]
