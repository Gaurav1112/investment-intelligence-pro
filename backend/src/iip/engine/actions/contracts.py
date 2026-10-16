"""ActionCard contract (design-risk-first.md §7.1, amended by design-judgement.md §2 grafts 7, 8 and 11).

A card is the only way the engine tells the user to do something. It is a frozen value object:

* **No forecast field.** There is no ``expected_return`` (ADR-0010; PLAN §6), no probability and no projection. A unit
  test (``tests/unit/test_cards.py``) enforces this on every dataclass in this module.
* **Every number is traceable.** A displayed number is a :class:`CardNumber` carrying at least one ``fact_id`` or a
  ``formula_id`` (``name@version``). Every :class:`Step` names the formula that produced its amounts. The card's
  :class:`Impact` must point at one of the card's own INR numbers, so the ranking ₹ is itself traceable.
* **₹ is never added across bases.** :func:`sum_impacts` refuses mixed :class:`ImpactBasis` values.
* **Identity is content-addressed.** ``card_id`` is computed, never supplied: sha256 of the canonical JSON of
  (kind, rule_ref, goal_id, sorted instrument ids, snapshot_id). ``rule_ref`` is added to the frozen §7.1 key so that
  two abstentions for one goal from different rules in the same snapshot do not collide.

Pure: no clock, IO or randomness (``tests/unit/test_engine_purity.py``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import IntEnum, StrEnum
from typing import Literal

from iip.engine.determinism import content_hash
from iip.engine.errors import InvalidInput
from iip.engine.money import ZERO

CONTRACT_VERSION = "action_card@1"

FORMULA_ID = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*@[1-9]\d*$")
RULE_ID = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*$")
SLOT_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class Layer(IntEnum):
    """Risk hierarchy (design-risk-first.md §4). Lower value = protects against a larger, less recoverable loss."""

    L0 = 0  # data integrity
    L1 = 1  # liquidity / emergency fund
    L2 = 2  # goal-date safety
    L3 = 3  # loss budget
    L4 = 4  # concentration and default limits
    L5 = 5  # policy target and bands
    L6 = 6  # tax and cost
    L7 = 7  # validated signal tilts
    L8 = 8  # information


class CardKind(StrEnum):
    EMERGENCY_SHORTFALL = "EMERGENCY_SHORTFALL"
    GOAL_DATE_BREACH = "GOAL_DATE_BREACH"
    GOAL_DATE_DURATION = "GOAL_DATE_DURATION"  # L2 ACTION: debt duration longer than the time left to the goal
    LOSS_BUDGET_BREACH = "LOSS_BUDGET_BREACH"
    LIMIT_BREACH = "LIMIT_BREACH"
    REBALANCE_DUE = "REBALANCE_DUE"
    NEXT_RUPEE = "NEXT_RUPEE"
    LTCG_HARVEST = "LTCG_HARVEST"
    LT_DATE = "LT_DATE"
    REG_TO_DIRECT = "REG_TO_DIRECT"
    LOWER_COST_SAME_EXPOSURE = "LOWER_COST_SAME_EXPOSURE"
    REVIEW_FLAG = "REVIEW_FLAG"
    SIGNAL_TILT = "SIGNAL_TILT"
    ABSTAIN = "ABSTAIN"
    NO_ACTION_NEEDED = "NO_ACTION_NEEDED"
    DATA_ATTENTION = "DATA_ATTENTION"


class CardClass(StrEnum):
    """Wording class (design-evidence-first.md §3.1). POLICY = the user's own rule; DESCRIPTIVE = a flag, no verb;
    SIGNAL = an evidence-gated rule (neutral "entry/exit condition met" wording, U-11); STATUS = abstain/empty/data."""

    POLICY = "POLICY"
    DESCRIPTIVE = "DESCRIPTIVE"
    SIGNAL = "SIGNAL"
    STATUS = "STATUS"


# Fixed layer per kind. ABSTAIN is the one kind that may sit at any layer (it abstains where the input is missing).
KIND_LAYER: dict[CardKind, Layer] = {
    CardKind.DATA_ATTENTION: Layer.L0,
    CardKind.EMERGENCY_SHORTFALL: Layer.L1,
    CardKind.GOAL_DATE_BREACH: Layer.L2,
    CardKind.GOAL_DATE_DURATION: Layer.L2,
    CardKind.LOSS_BUDGET_BREACH: Layer.L3,
    CardKind.LIMIT_BREACH: Layer.L4,
    CardKind.REBALANCE_DUE: Layer.L5,
    CardKind.NEXT_RUPEE: Layer.L5,
    CardKind.LTCG_HARVEST: Layer.L6,
    CardKind.LT_DATE: Layer.L6,
    CardKind.REG_TO_DIRECT: Layer.L6,
    CardKind.LOWER_COST_SAME_EXPOSURE: Layer.L6,
    CardKind.REVIEW_FLAG: Layer.L6,
    CardKind.SIGNAL_TILT: Layer.L7,
    CardKind.NO_ACTION_NEEDED: Layer.L8,
}

KIND_CLASS: dict[CardKind, CardClass] = {
    CardKind.EMERGENCY_SHORTFALL: CardClass.POLICY,
    CardKind.GOAL_DATE_BREACH: CardClass.POLICY,
    CardKind.GOAL_DATE_DURATION: CardClass.POLICY,
    CardKind.LOSS_BUDGET_BREACH: CardClass.POLICY,
    CardKind.LIMIT_BREACH: CardClass.POLICY,
    CardKind.REBALANCE_DUE: CardClass.POLICY,
    CardKind.NEXT_RUPEE: CardClass.POLICY,
    CardKind.LTCG_HARVEST: CardClass.POLICY,
    CardKind.LT_DATE: CardClass.POLICY,
    CardKind.REG_TO_DIRECT: CardClass.POLICY,
    CardKind.LOWER_COST_SAME_EXPOSURE: CardClass.POLICY,
    CardKind.REVIEW_FLAG: CardClass.DESCRIPTIVE,
    CardKind.SIGNAL_TILT: CardClass.SIGNAL,
    CardKind.ABSTAIN: CardClass.STATUS,
    CardKind.NO_ACTION_NEEDED: CardClass.STATUS,
    CardKind.DATA_ATTENTION: CardClass.STATUS,
}

# A BREACH suppresses lower layers for its goal (design-risk-first.md §4); so does an L0 data-integrity abstention.
BREACH_KINDS = frozenset({CardKind.EMERGENCY_SHORTFALL, CardKind.GOAL_DATE_BREACH, CardKind.LOSS_BUDGET_BREACH})
# Kinds that are not an action for the user (they feed "Needs from you" or the empty state).
NON_ACTION_KINDS = frozenset({CardKind.ABSTAIN, CardKind.NO_ACTION_NEEDED, CardKind.DATA_ATTENTION})


class CardStatus(StrEnum):
    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT VERIFIED"
    REQUIRES_CONFIGURATION = "REQUIRES CONFIGURATION"
    BLOCKED = "BLOCKED"


class Verb(StrEnum):
    """The only verbs a card may use (design-risk-first.md §7.3). No BUY/SELL (U-11)."""

    REDIRECT_SIP = "REDIRECT_SIP"
    INVEST = "INVEST"
    REDEEM = "REDEEM"
    SWITCH = "SWITCH"
    WAIT_UNTIL = "WAIT_UNTIL"
    REVIEW = "REVIEW"


class ImpactBasis(StrEnum):
    """What a ₹ impact measures. Amounts on different bases are never added (design-user-first.md §7.2)."""

    SHORTFALL = "SHORTFALL"
    TAX_DEFERRED = "TAX_DEFERRED"
    TAX_AVOIDED = "TAX_AVOIDED"
    ANNUAL_COST_SAVED = "ANNUAL_COST_SAVED"
    AMOUNT_TO_MOVE = "AMOUNT_TO_MOVE"
    AMOUNT_AT_RISK = "AMOUNT_AT_RISK"


class NumberUnit(StrEnum):
    INR = "inr"
    PCT = "pct"  # a fraction: 0.6824 → 68.2%
    PP = "pp"  # percentage points, as a fraction: 0.05 → 5.0 pp
    UNITS = "units"  # fund units
    MONTHS = "months"
    YEARS = "years"
    DAYS = "days"
    COUNT = "count"
    DATE = "date"


ParameterSetter = Literal["user", "default", "rule_table"]


def _require_text(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidInput(f"{name} must be a non-empty string")


def _require_decimal(name: str, value: object, *, non_negative: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise InvalidInput(f"{name} must be a Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise InvalidInput(f"{name} must be finite")
    if non_negative and value < ZERO:
        raise InvalidInput(f"{name} must be ≥ 0")


def _optional_decimal(name: str, value: object, *, non_negative: bool = False) -> None:
    if value is not None:
        _require_decimal(name, value, non_negative=non_negative)


def _require_date(name: str, value: object) -> None:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise InvalidInput(f"{name} must be a date")


def _require_formula_id(name: str, value: object) -> None:
    if not isinstance(value, str) or not FORMULA_ID.fullmatch(value):
        raise InvalidInput(f"{name} must be a formula_id of the form 'name@version', got {value!r}")


@dataclass(frozen=True)
class CardNumber:
    """One number shown on a card. Carries at least one ``fact_id`` or a ``formula_id`` (both is allowed and better:
    the formula plus the facts it consumed)."""

    slot: str
    value: Decimal | date
    unit: NumberUnit
    as_of: date
    fact_ids: tuple[str, ...] = ()
    formula_id: str | None = None

    def __post_init__(self) -> None:
        if not SLOT_NAME.fullmatch(self.slot or ""):
            raise InvalidInput(f"bad slot name {self.slot!r}")
        if not isinstance(self.unit, NumberUnit):
            raise InvalidInput("unit must be a NumberUnit")
        if self.unit is NumberUnit.DATE:
            _require_date(f"{self.slot}.value", self.value)
        else:
            _require_decimal(f"{self.slot}.value", self.value)
        _require_date(f"{self.slot}.as_of", self.as_of)
        if not isinstance(self.fact_ids, tuple):
            raise InvalidInput("fact_ids must be a tuple")
        for f in self.fact_ids:
            _require_text(f"{self.slot}.fact_id", f)
        if self.formula_id is not None:
            _require_formula_id(f"{self.slot}.formula_id", self.formula_id)
        if not self.fact_ids and self.formula_id is None:
            raise InvalidInput(f"number {self.slot!r} needs a fact_id or formula_id (no untraceable numbers)")


@dataclass(frozen=True)
class Impact:
    """The ₹ that ranks a card. ``slot`` names the card's own INR :class:`CardNumber` that carries its provenance."""

    amount_inr: Decimal
    basis: ImpactBasis
    slot: str

    def __post_init__(self) -> None:
        _require_decimal("impact.amount_inr", self.amount_inr, non_negative=True)
        if not isinstance(self.basis, ImpactBasis):
            raise InvalidInput("impact.basis must be an ImpactBasis")
        _require_text("impact.slot", self.slot)


def sum_impacts(impacts: Iterable[Impact]) -> tuple[ImpactBasis, Decimal]:
    """Add ₹ impacts that share one basis. Mixed bases raise: ₹ is never added across different bases."""
    items = tuple(impacts)
    if not items:
        raise InvalidInput("nothing to sum")
    bases = {i.basis for i in items}
    if len(bases) != 1:
        raise InvalidInput(f"refusing to add ₹ across different bases: {sorted(bases)}")
    total = ZERO
    for i in items:
        total += i.amount_inr
    return items[0].basis, total


@dataclass(frozen=True)
class StepCost:
    exit_load_inr: Decimal = ZERO
    stamp_inr: Decimal = ZERO
    stt_inr: Decimal = ZERO

    def __post_init__(self) -> None:
        for name in ("exit_load_inr", "stamp_inr", "stt_inr"):
            _require_decimal(name, getattr(self, name), non_negative=True)


@dataclass(frozen=True)
class StepTax:
    stcg_inr: Decimal = ZERO
    ltcg_inr: Decimal = ZERO
    cess_inr: Decimal = ZERO

    def __post_init__(self) -> None:
        for name in ("stcg_inr", "ltcg_inr", "cess_inr"):
            _require_decimal(name, getattr(self, name), non_negative=True)


_NEEDS_INSTRUMENT = frozenset({Verb.REDEEM, Verb.SWITCH})


@dataclass(frozen=True)
class Step:
    """One thing to do. ``formula_id`` names the rule formula that produced every amount on the step."""

    verb: Verb
    instrument_id: str | None
    formula_id: str
    amount_inr: Decimal | None = None
    units: Decimal | None = None
    folio: str | None = None
    lots_consumed: tuple[str, ...] = ()
    cost: StepCost | None = None
    tax: StepTax | None = None
    net_effect_inr: Decimal | None = None
    wait_until: date | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.verb, Verb):
            raise InvalidInput("step.verb must be a Verb")
        _require_formula_id("step.formula_id", self.formula_id)
        if self.instrument_id is not None:
            _require_text("step.instrument_id", self.instrument_id)
        elif self.verb in _NEEDS_INSTRUMENT:
            raise InvalidInput(f"{self.verb} needs an instrument_id")
        _optional_decimal("step.amount_inr", self.amount_inr, non_negative=True)
        _optional_decimal("step.units", self.units, non_negative=True)
        _optional_decimal("step.net_effect_inr", self.net_effect_inr)
        if self.lots_consumed and self.verb not in _NEEDS_INSTRUMENT:
            raise InvalidInput("only REDEEM or SWITCH consume lots")
        if (self.verb is Verb.WAIT_UNTIL) != (self.wait_until is not None):
            raise InvalidInput("wait_until is required for WAIT_UNTIL and only for it")
        if self.wait_until is not None:
            _require_date("step.wait_until", self.wait_until)


@dataclass(frozen=True)
class ParameterValue:
    """A rule parameter as shown under "why": its value, who set it and when (None = a cited default never set)."""

    name: str
    value: str
    set_by: ParameterSetter
    set_on: date | None = None

    def __post_init__(self) -> None:
        _require_text("parameter.name", self.name)
        _require_text("parameter.value", self.value)
        if self.set_by not in ("user", "default", "rule_table"):
            raise InvalidInput(f"parameter.set_by {self.set_by!r}")
        if self.set_on is not None:
            _require_date("parameter.set_on", self.set_on)


@dataclass(frozen=True)
class Why:
    rule_id: str
    rule_version: int
    parameters: tuple[ParameterValue, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id, str) or not RULE_ID.fullmatch(self.rule_id):
            raise InvalidInput(f"bad rule_id {self.rule_id!r}")
        if isinstance(self.rule_version, bool) or not isinstance(self.rule_version, int) or self.rule_version < 1:
            raise InvalidInput("rule_version must be a positive int")

    @property
    def rule_ref(self) -> str:
        return f"{self.rule_id}@{self.rule_version}"


@dataclass(frozen=True)
class Abstention:
    """A named missing input. When the engine can bound the ₹ the input unlocks, the bound carries its basis and the
    formula that computed it, so "Needs from you" can rank by it without inventing a number."""

    code: str
    missing_input: str
    how_to_fix: str
    unlock_upper_bound_inr: Decimal | None = None
    unlock_basis: ImpactBasis | None = None
    unlock_formula_id: str | None = None

    def __post_init__(self) -> None:
        _require_text("abstention.code", self.code)
        _require_text("abstention.missing_input", self.missing_input)
        _require_text("abstention.how_to_fix", self.how_to_fix)
        if self.unlock_upper_bound_inr is None:
            if self.unlock_basis is not None or self.unlock_formula_id is not None:
                raise InvalidInput("unlock basis/formula given without an unlock bound")
            return
        _require_decimal("abstention.unlock_upper_bound_inr", self.unlock_upper_bound_inr, non_negative=True)
        if not isinstance(self.unlock_basis, ImpactBasis):
            raise InvalidInput("an unlock bound needs an ImpactBasis")
        _require_formula_id("abstention.unlock_formula_id", self.unlock_formula_id)


def make_card_id(
    kind: CardKind, rule_ref: str, goal_id: str | None, instrument_ids: Iterable[str], snapshot_id: str
) -> str:
    return content_hash(
        {
            "kind": kind,
            "rule_ref": rule_ref,
            "goal_id": goal_id,
            "instrument_ids": sorted(set(instrument_ids)),
            "snapshot_id": snapshot_id,
        }
    )


@dataclass(frozen=True)
class ActionCard:
    """design-risk-first.md §7.1, frozen. There is deliberately no ``expected_return`` field (ADR-0010)."""

    kind: CardKind
    layer: Layer
    goal_id: str | None
    as_of: date
    deadline: date | None
    impact: Impact | None
    steps: tuple[Step, ...]
    why: Why
    numbers: tuple[CardNumber, ...]
    template_id: str
    status: CardStatus
    abstentions: tuple[Abstention, ...]
    engine_version: str
    rules_version: str
    input_manifest_hash: str
    snapshot_id: str
    card_id: str = field(init=False)

    def __post_init__(self) -> None:
        self._validate()
        object.__setattr__(
            self,
            "card_id",
            make_card_id(self.kind, self.why.rule_ref, self.goal_id, self.instrument_ids, self.snapshot_id),
        )

    @property
    def instrument_ids(self) -> tuple[str, ...]:
        return tuple(sorted({s.instrument_id for s in self.steps if s.instrument_id is not None}))

    @property
    def card_class(self) -> CardClass:
        return KIND_CLASS[self.kind]

    @property
    def suppresses_lower_layers(self) -> bool:
        return self.kind in BREACH_KINDS or self.layer is Layer.L0

    @property
    def is_action(self) -> bool:
        return self.kind not in NON_ACTION_KINDS

    def number(self, slot: str) -> CardNumber | None:
        for n in self.numbers:
            if n.slot == slot:
                return n
        return None

    def _validate(self) -> None:
        if not isinstance(self.kind, CardKind):
            raise InvalidInput("kind must be a CardKind")
        if not isinstance(self.layer, Layer):
            raise InvalidInput("layer must be a Layer")
        if self.kind is not CardKind.ABSTAIN and self.layer is not KIND_LAYER[self.kind]:
            raise InvalidInput(f"{self.kind} must sit at layer {KIND_LAYER[self.kind].name}, not {self.layer.name}")
        if self.goal_id is not None:
            _require_text("goal_id", self.goal_id)
        _require_date("as_of", self.as_of)
        if self.deadline is not None:
            _require_date("deadline", self.deadline)
        if not isinstance(self.status, CardStatus):
            raise InvalidInput("status must be a CardStatus")
        if not isinstance(self.why, Why):
            raise InvalidInput("why must be a Why")
        for name in ("template_id", "engine_version", "rules_version", "input_manifest_hash", "snapshot_id"):
            _require_text(name, getattr(self, name))
        for name, items, typ in (
            ("steps", self.steps, Step),
            ("numbers", self.numbers, CardNumber),
            ("abstentions", self.abstentions, Abstention),
        ):
            if not isinstance(items, tuple) or not all(isinstance(x, typ) for x in items):
                raise InvalidInput(f"{name} must be a tuple of {typ.__name__}")
        slots = [n.slot for n in self.numbers]
        if len(slots) != len(set(slots)):
            raise InvalidInput(f"duplicate number slots: {sorted(slots)}")
        self._validate_impact()
        self._validate_kind_shape()

    def _validate_impact(self) -> None:
        if self.impact is None:
            return
        if not isinstance(self.impact, Impact):
            raise InvalidInput("impact must be an Impact")
        n = self.number(self.impact.slot)
        if n is None or n.unit is not NumberUnit.INR or n.value != self.impact.amount_inr:
            raise InvalidInput(f"impact must equal the card's INR number in slot {self.impact.slot!r}")

    def _validate_kind_shape(self) -> None:
        if self.kind in (CardKind.ABSTAIN, CardKind.DATA_ATTENTION):
            if not self.abstentions:
                raise InvalidInput(f"{self.kind} needs at least one abstention")
            if self.steps or self.impact is not None:
                raise InvalidInput(f"{self.kind} carries no steps and no impact")
        if self.kind is CardKind.NO_ACTION_NEEDED and (
            self.steps or self.impact is not None or self.abstentions or self.goal_id is not None
        ):
            raise InvalidInput("NO_ACTION_NEEDED carries no steps, impact, abstentions or goal")
        if self.status is CardStatus.BLOCKED and self.steps:
            raise InvalidInput("a BLOCKED card carries no steps")
