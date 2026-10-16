"""Context manifests and the completeness gate (ADR-0003 §1–§4; requirements.md §3.6a)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

MANIFEST_VERSION = "context_manifest@1.0.0"


class ContextKind(StrEnum):
    USER_INPUT = "user_input"
    OBSERVATION = "observation"
    RULE = "rule"
    TERMS = "terms"


@dataclass(frozen=True)
class ContextItem:
    item_id: str
    kind: ContextKind
    description: str
    required: bool = True
    max_age_days: int | None = None  # freshness rule, measured from observation_date to as_of
    acceptable_sources: frozenset[str] | None = None  # None = any registered source


@dataclass(frozen=True)
class ContextValue:
    """What a context provider found for one manifest item."""

    item_id: str
    present: bool
    observation_date: date | None = None
    source_id: str | None = None
    provenance_complete: bool = False
    valid: bool = False
    fact_ids: tuple[str, ...] = ()
    note: str = ""


class GapReason(StrEnum):
    MISSING = "MISSING"
    STALE = "STALE"
    UNACCEPTABLE_SOURCE = "UNACCEPTABLE_SOURCE"
    PROVENANCE_INCOMPLETE = "PROVENANCE_INCOMPLETE"
    INVALID = "INVALID"


@dataclass(frozen=True)
class Gap:
    item_id: str
    reason: GapReason
    required: bool
    description: str
    detail: str = ""


@dataclass(frozen=True)
class ContextManifest:
    question_type: str
    items: tuple[ContextItem, ...]
    version: str = MANIFEST_VERSION

    def item(self, item_id: str) -> ContextItem:
        for it in self.items:
            if it.item_id == item_id:
                return it
        raise KeyError(item_id)


@dataclass(frozen=True)
class GateResult:
    complete: bool
    gaps: tuple[Gap, ...]
    checked: tuple[str, ...] = field(default_factory=tuple)

    @property
    def blocking(self) -> tuple[Gap, ...]:
        return tuple(g for g in self.gaps if g.required)


def evaluate_gate(manifest: ContextManifest, values: dict[str, ContextValue], as_of: date) -> GateResult:
    """Deterministic completeness check. Never fills a gap; only reports it."""
    gaps: list[Gap] = []
    for item in manifest.items:
        v = values.get(item.item_id)
        if v is None or not v.present:
            gaps.append(Gap(item.item_id, GapReason.MISSING, item.required, item.description))
            continue
        if item.kind is not ContextKind.USER_INPUT and not v.provenance_complete:
            gaps.append(Gap(item.item_id, GapReason.PROVENANCE_INCOMPLETE, item.required, item.description))
            continue
        if not v.valid:
            gaps.append(Gap(item.item_id, GapReason.INVALID, item.required, item.description, v.note))
            continue
        if item.acceptable_sources is not None and v.source_id not in item.acceptable_sources:
            gaps.append(
                Gap(item.item_id, GapReason.UNACCEPTABLE_SOURCE, item.required, item.description, str(v.source_id))
            )
            continue
        if item.max_age_days is not None:
            if v.observation_date is None:
                gaps.append(Gap(item.item_id, GapReason.PROVENANCE_INCOMPLETE, item.required, item.description))
                continue
            age = (as_of - v.observation_date).days
            if age > item.max_age_days or age < 0:
                detail = f"observed {v.observation_date.isoformat()}, {age} days before {as_of.isoformat()}"
                if age < 0:
                    detail = f"observation date {v.observation_date.isoformat()} is after as-of {as_of.isoformat()}"
                gaps.append(Gap(item.item_id, GapReason.STALE, item.required, item.description, detail))
    complete = not any(g.required for g in gaps)
    return GateResult(complete=complete, gaps=tuple(gaps), checked=tuple(i.item_id for i in manifest.items))


# ------------------------------------------------------------------------------------------------- per-goal manifest
#
# design-risk-first.md §8 ("Supervisor"): a per-goal manifest names the facts each risk layer needs. A missing fact
# abstains THAT layer for THAT goal only; other layers and other goals still run (PLAN.md wave 2, package B02).
# Household layers (L1 emergency fund, L4 limits) use the scope id ``household``.

GOAL_MANIFEST_VERSION = "goal_manifest@1"
HOUSEHOLD_SCOPE = "household"


class RiskLayer(StrEnum):
    L1 = "L1"  # emergency fund (household)
    L2 = "L2"  # goal-date safety (per goal)
    L3 = "L3"  # loss budget (per goal)
    L4 = "L4"  # concentration limits (household)


# Item ids. User inputs are named after the column the user fills in; observations after what they describe.
ITEM_EMERGENCY_MONTHS = "user.emergency_months"
ITEM_ESSENTIAL_EXPENSES = "user.essential_monthly_expenses"
ITEM_GOAL_DATE = "goal.target_date"
ITEM_H_SAFE = "goal.h_safe_years"
ITEM_LOSS_BUDGET = "goal.loss_budget_inr"
ITEM_RECOVERY_MONTHS = "goal.recovery_months"
ITEM_HOLDINGS_VALUED = "holdings.valued"
ITEM_HOLDINGS_CLASSIFIED = "holdings.classified"
ITEM_STRESS_TABLE = "rules.stress_table"
ITEM_LIMITS_POLICY = "policy.limits"


def _items(*items: ContextItem) -> tuple[ContextItem, ...]:
    return items


def layer_manifest(layer: RiskLayer, *, goal_has_equity: bool = True) -> ContextManifest:
    """The context a risk layer needs. ``goal_has_equity`` makes the recovery tolerance required only for goals that
    hold (or plan) equity, as ``risk.loss_budget@1`` does."""
    valued = ContextItem(ITEM_HOLDINGS_VALUED, ContextKind.OBSERVATION, "a fresh NAV for every holding in scope")
    classified = ContextItem(ITEM_HOLDINGS_CLASSIFIED, ContextKind.RULE, "a risk class for every holding in scope")
    items: tuple[ContextItem, ...]
    if layer is RiskLayer.L1:
        items = _items(
            ContextItem(ITEM_EMERGENCY_MONTHS, ContextKind.USER_INPUT, "months of essential expenses to hold"),
            ContextItem(ITEM_ESSENTIAL_EXPENSES, ContextKind.USER_INPUT, "essential monthly expenses"),
            valued,
        )
    elif layer is RiskLayer.L2:
        items = _items(
            ContextItem(ITEM_GOAL_DATE, ContextKind.USER_INPUT, "the goal's target date"),
            ContextItem(ITEM_H_SAFE, ContextKind.USER_INPUT, "the goal's safety window in years"),
            valued,
            classified,
        )
    elif layer is RiskLayer.L3:
        items = _items(
            ContextItem(ITEM_LOSS_BUDGET, ContextKind.USER_INPUT, "the goal's loss limit in rupees"),
            ContextItem(
                ITEM_RECOVERY_MONTHS,
                ContextKind.USER_INPUT,
                "the longest wait for a recovery, in months",
                required=goal_has_equity,
            ),
            ContextItem(ITEM_STRESS_TABLE, ContextKind.RULE, "the stress table (worst observed falls)"),
            valued,
            classified,
        )
    else:
        items = _items(
            ContextItem(ITEM_LIMITS_POLICY, ContextKind.USER_INPUT, "your concentration limits"),
            valued,
            classified,
        )
    return ContextManifest(question_type=f"risk.{layer.value.lower()}", items=items, version=GOAL_MANIFEST_VERSION)


@dataclass(frozen=True)
class ScopeGate:
    """The gate result for one (scope, layer). ``scope_id`` is a goal id or :data:`HOUSEHOLD_SCOPE`."""

    scope_id: str
    layer: RiskLayer
    result: GateResult


def evaluate_scope(
    scope_id: str,
    layer: RiskLayer,
    values: dict[str, ContextValue],
    as_of: date,
    *,
    goal_has_equity: bool = True,
) -> ScopeGate:
    """Gate one layer for one scope. Deterministic; never fills a gap."""
    manifest = layer_manifest(layer, goal_has_equity=goal_has_equity)
    return ScopeGate(scope_id, layer, evaluate_gate(manifest, values, as_of))
