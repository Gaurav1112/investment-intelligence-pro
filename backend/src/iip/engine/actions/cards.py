"""Deterministic card wording: template set, template linter and renderer (design-risk-first.md §7.2–7.3).

* Templates live in ``rules/action_templates.yaml``. This module never reads the file (the engine does no IO); the
  rules loader or a test passes the parsed mapping to :func:`parse_templates`.
* :func:`lint_template_text` rejects forecast language in every card class (design-evidence-first.md §3.1; graft 11),
  BUY/SELL and other trade-call words (U-11: neutral wording), and literal numbers in static text, so every number on a
  card comes from a slot backed by a :class:`~iip.engine.actions.contracts.CardNumber` with a fact_id or formula_id.
  Policy text must speak as "your rule" and name ``{rule_ref}``; signal text must say "entry/exit condition met".
* :func:`render_card` fills the slots. Text supplied by callers (names, free text) is linted too, so a forecast or a
  number cannot be smuggled in through a name.
* No LLM anywhere in this path (ADR-0007).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from iip.engine.actions.contracts import (
    KIND_CLASS,
    ActionCard,
    CardClass,
    CardKind,
    NumberUnit,
)
from iip.engine.errors import InvalidInput
from iip.engine.money import ZERO, engine_context, money

SUPPORTED_SCHEMA = "action_templates@1"
REQUIRED_LINTER_CATEGORIES = ("forecast", "trade_call", "literal_number")
# Slot types that are text rather than numbers. "name" = an entity name from the user's data (may contain digits, e.g.
# an index name, but never a currency amount or a percentage); "text" = free text (no digits at all).
TEXT_SLOT_TYPES = frozenset({"text", "name"})
RULE_REF_SLOT = "rule_ref"
_SLOT_TYPES = frozenset({u.value for u in NumberUnit}) | TEXT_SLOT_TYPES | {RULE_REF_SLOT}
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
_STRAY_BRACE = re.compile(r"[{}]")
_TEMPLATE_KEYS = frozenset({"kind", "card_class", "text", "slots"})
_TOP_KEYS = frozenset({"version", "source", "footer_ref", "linter", "voice", "templates"})
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_NAME_NUMBERISH = re.compile(r"₹|%|\bRs\.?\s?\d|\d[\d,]*\.\d|\d{1,3}(?:,\d{2,3})+")

# Invisible or look-alike characters that would let banned wording slip past a regex.
_INVISIBLE = dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\u2060\ufeff\u180e"), None)
_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe63\uff0d"), "-")


def _normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).translate(_INVISIBLE).translate(_DASHES)
    return re.sub(r"\s+", " ", t)


# --- template set -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LinterRule:
    category: str
    applies_to: frozenset[CardClass]
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class VoiceRule:
    must_match: tuple[re.Pattern[str], ...]
    must_have_slots: tuple[str, ...]


@dataclass(frozen=True)
class Linter:
    rules: tuple[LinterRule, ...]
    voice: Mapping[CardClass, VoiceRule]


@dataclass(frozen=True)
class CardTemplate:
    template_id: str
    kind: CardKind
    card_class: CardClass
    text: str
    slots: Mapping[str, str]  # slot name -> NumberUnit value | "text" | "name" | "rule_ref"


@dataclass(frozen=True)
class TemplateSet:
    version: str
    footer_ref: str | None
    linter: Linter
    templates: Mapping[str, CardTemplate]


@dataclass(frozen=True)
class LintFinding:
    category: str
    detail: str


def _as_mapping(name: str, value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidInput(f"{name} must be a mapping")
    return value


def _compile(category: str, pattern: Any) -> re.Pattern[str]:
    if not isinstance(pattern, str) or not pattern:
        raise InvalidInput(f"linter {category}: patterns must be non-empty strings")
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise InvalidInput(f"linter {category}: bad regex {pattern!r}: {exc}") from exc


def _parse_linter(raw_linter: Any, raw_voice: Any) -> Linter:
    lin = _as_mapping("linter", raw_linter)
    missing = [cat for cat in REQUIRED_LINTER_CATEGORIES if cat not in lin]
    if missing:
        raise InvalidInput(f"linter is missing required categories: {missing}")
    rules: list[LinterRule] = []
    for category, body in lin.items():
        spec = _as_mapping(f"linter.{category}", body)
        if set(spec) != {"applies_to", "patterns"}:
            raise InvalidInput(f"linter.{category} needs exactly applies_to and patterns")
        scope = spec["applies_to"]
        if scope == "all":
            classes = frozenset(CardClass)
        elif isinstance(scope, list) and scope:
            try:
                classes = frozenset(CardClass(s) for s in scope)
            except ValueError as exc:
                raise InvalidInput(f"linter.{category}: unknown card class in {scope}") from exc
        else:
            raise InvalidInput(f"linter.{category}.applies_to must be 'all' or a list of card classes")
        patterns = spec["patterns"]
        if not isinstance(patterns, list) or not patterns:
            raise InvalidInput(f"linter.{category}.patterns must be a non-empty list")
        rules.extend(LinterRule(str(category), classes, _compile(str(category), p)) for p in patterns)
    voice: dict[CardClass, VoiceRule] = {}
    for cls_name, body in _as_mapping("voice", raw_voice).items():
        try:
            cls = CardClass(cls_name)
        except ValueError as exc:
            raise InvalidInput(f"voice: unknown card class {cls_name!r}") from exc
        spec = _as_mapping(f"voice.{cls_name}", body)
        if set(spec) != {"must_match", "must_have_slots"}:
            raise InvalidInput(f"voice.{cls_name} needs exactly must_match and must_have_slots")
        voice[cls] = VoiceRule(
            must_match=tuple(_compile(f"voice.{cls_name}", p) for p in spec["must_match"]),
            must_have_slots=tuple(str(s) for s in spec["must_have_slots"]),
        )
    for required in (CardClass.POLICY, CardClass.SIGNAL):
        if required not in voice:
            raise InvalidInput(f"voice rules for {required} are required")
    return Linter(rules=tuple(rules), voice=voice)


def lint_template_text(text: str, card_class: CardClass, linter: Linter) -> list[LintFinding]:
    """Lint the static text of a template (placeholders are ignored, except for the voice check)."""
    findings: list[LintFinding] = []
    placeholders = set(_PLACEHOLDER.findall(text))
    static = _normalise(_PLACEHOLDER.sub(" ", text))
    for rule in linter.rules:
        if card_class in rule.applies_to:
            m = rule.pattern.search(static)
            if m:
                findings.append(LintFinding(rule.category, f"{m.group(0)!r} matches {rule.pattern.pattern!r}"))
    if _STRAY_BRACE.search(static):
        findings.append(LintFinding("syntax", "stray brace outside a {slot} placeholder"))
    voice = linter.voice.get(card_class)
    if voice is not None:
        category = f"{card_class.value.lower()}_voice"
        for pattern in voice.must_match:
            if not pattern.search(static):
                findings.append(LintFinding(category, f"text must match {pattern.pattern!r}"))
        for slot in voice.must_have_slots:
            if slot not in placeholders:
                findings.append(LintFinding(category, f"text must contain {{{slot}}}"))
    return findings


def _parse_template(template_id: str, body: Any, linter: Linter) -> CardTemplate:
    spec = _as_mapping(f"templates.{template_id}", body)
    if set(spec) != _TEMPLATE_KEYS:
        raise InvalidInput(
            f"templates.{template_id}: fields must be exactly {sorted(_TEMPLATE_KEYS)}, got {sorted(spec)}"
        )
    try:
        kind = CardKind(spec["kind"])
        card_class = CardClass(spec["card_class"])
    except ValueError as exc:
        raise InvalidInput(f"templates.{template_id}: {exc}") from exc
    if card_class is not KIND_CLASS[kind]:
        raise InvalidInput(f"templates.{template_id}: {kind} is a {KIND_CLASS[kind]} card, not {card_class}")
    text = spec["text"]
    if not isinstance(text, str) or not text.strip():
        raise InvalidInput(f"templates.{template_id}: text must be a non-empty string")
    slots = {str(k): str(v) for k, v in _as_mapping(f"templates.{template_id}.slots", spec["slots"]).items()}
    for name, typ in slots.items():
        if typ not in _SLOT_TYPES:
            raise InvalidInput(f"templates.{template_id}: slot {name!r} has unknown type {typ!r}")
        if (name == RULE_REF_SLOT) != (typ == RULE_REF_SLOT):
            raise InvalidInput(f"templates.{template_id}: slot type rule_ref is reserved for the slot rule_ref")
    used = set(_PLACEHOLDER.findall(text))
    if used != set(slots):
        raise InvalidInput(
            f"templates.{template_id}: slot mismatch; undeclared {sorted(used - set(slots))}, "
            f"unused {sorted(set(slots) - used)}"
        )
    findings = lint_template_text(text, card_class, linter)
    if findings:
        detail = "; ".join(f"{f.category}: {f.detail}" for f in findings)
        raise InvalidInput(f"templates.{template_id} fails the linter: {detail}")
    return CardTemplate(template_id=template_id, kind=kind, card_class=card_class, text=text, slots=slots)


def parse_templates(raw: Mapping[str, Any]) -> TemplateSet:
    """Validate a parsed ``action_templates.yaml``. Every template is linted; one failure rejects the whole set."""
    top = _as_mapping("action_templates", raw)
    unknown = set(top) - _TOP_KEYS
    if unknown:
        raise InvalidInput(f"action_templates: unknown fields {sorted(unknown)}")
    version = top.get("version")
    if not isinstance(version, str) or not version.startswith(SUPPORTED_SCHEMA):
        raise InvalidInput(f"action_templates: version must start with {SUPPORTED_SCHEMA!r}")
    linter = _parse_linter(top.get("linter"), top.get("voice"))
    templates = {
        str(tid): _parse_template(str(tid), body, linter)
        for tid, body in _as_mapping("templates", top.get("templates")).items()
    }
    if not templates:
        raise InvalidInput("action_templates: no templates")
    footer = top.get("footer_ref")
    if footer is not None and not isinstance(footer, str):
        raise InvalidInput("footer_ref must be a string")
    return TemplateSet(version=version, footer_ref=footer, linter=linter, templates=templates)


# --- formatting --------------------------------------------------------------------------------------------------


def _group_indian(integer_digits: str) -> str:
    if len(integer_digits) <= 3:
        return integer_digits
    head, tail = integer_digits[:-3], integer_digits[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join([*groups, tail])


def _grouped(value: Decimal, places: int) -> str:
    text = format(abs(value), "f")
    whole, _, frac = text.partition(".")
    out = _group_indian(whole)
    if places:
        out += "." + (frac + "0" * places)[:places]
    return out


def _integral(value: Decimal, unit: NumberUnit) -> int:
    if value != value.to_integral_value():
        raise InvalidInput(f"{unit.value} must be a whole number, got {value}")
    return int(value)


def _plural(n: Decimal | int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def format_number(value: Decimal | date, unit: NumberUnit) -> str:
    """Display a card number. INR uses Indian digit grouping and paise only when non-zero (ROUND_HALF_UP, matching
    statements); rates use ROUND_HALF_EVEN to 0.1 (calculation-methodology.md §1)."""
    if unit is NumberUnit.DATE:
        if not isinstance(value, date):
            raise InvalidInput("a DATE number needs a date value")
        return f"{value.day:02d}-{_MONTHS[value.month - 1]}-{value.year}"
    if not isinstance(value, Decimal):
        raise InvalidInput(f"a {unit.value} number needs a Decimal value")
    with engine_context():
        if unit is NumberUnit.INR:
            q = money(value)
            places = 0 if q == q.to_integral_value() else 2
            sign = "−" if q < ZERO else ""
            return f"{sign}₹{_grouped(q, places)}"
        if unit in (NumberUnit.PCT, NumberUnit.PP):
            q = (value * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN)
            sign = "−" if q < ZERO else ""
            return f"{sign}{_grouped(q, 1)}%" if unit is NumberUnit.PCT else f"{sign}{_grouped(q, 1)} pp"
        if unit is NumberUnit.UNITS:
            q = value.quantize(Decimal("0.001"), rounding=ROUND_HALF_EVEN)
            return _grouped(q, 3)
        if unit is NumberUnit.YEARS:
            if value == value.to_integral_value():
                return _plural(int(value), "year")
            q = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN)
            return f"{q} years"
        if unit is NumberUnit.MONTHS:
            return _plural(_integral(value, unit), "month")
        if unit is NumberUnit.DAYS:
            return _plural(_integral(value, unit), "day")
        if unit is NumberUnit.COUNT:
            return _group_indian(str(_integral(value, unit)))
    raise InvalidInput(f"unsupported unit {unit}")  # pragma: no cover - enum is exhaustive


# --- rendering ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class NumberDisplay:
    slot: str
    display: str
    fact_ids: tuple[str, ...]
    formula_id: str | None


@dataclass(frozen=True)
class RenderedCard:
    card_id: str
    template_id: str
    text: str
    numbers: tuple[NumberDisplay, ...]
    names: tuple[str, ...]  # entity names placed in the text (the numeric validator allowlists their digits)


def _forbidden_hit(text: str, card_class: CardClass, linter: Linter, categories: tuple[str, ...]) -> str | None:
    body = _normalise(text)
    for rule in linter.rules:
        if rule.category in categories and card_class in rule.applies_to:
            m = rule.pattern.search(body)
            if m:
                return f"{rule.category}: {m.group(0)!r}"
    return None


def check_slot_value(slot: str, value: str, slot_type: str, linter: Linter | None = None) -> None:
    """Validate caller-supplied text for a text or name slot. Raises :class:`InvalidInput`."""
    if not isinstance(value, str) or not value.strip():
        raise InvalidInput(f"slot {slot!r} needs non-empty text")
    body = _normalise(value)
    if _PLACEHOLDER.search(body) or _STRAY_BRACE.search(body):
        raise InvalidInput(f"slot {slot!r}: braces are not allowed in slot text")
    if slot_type == "text" and re.search(r"\d", body):
        raise InvalidInput(f"slot {slot!r}: free text may not contain a number; use a number slot")
    if slot_type == "name" and _NAME_NUMBERISH.search(body):
        raise InvalidInput(f"slot {slot!r}: a name may not carry a number-like amount; use a number slot")
    if linter is not None:
        categories = ("forecast", "trade_call", "literal_number") if slot_type == "text" else ("forecast", "trade_call")
        hit = _forbidden_hit(body, CardClass.POLICY, linter, categories)
        if hit:
            raise InvalidInput(f"slot {slot!r} text rejected ({hit})")


def render_card(card: ActionCard, templates: TemplateSet, text_slots: Mapping[str, str]) -> RenderedCard:
    """Fill a card's template. Number slots come only from ``card.numbers`` (each traceable); ``rule_ref`` comes only
    from ``card.why``; every other text slot comes from ``text_slots`` and is linted."""
    template = templates.templates.get(card.template_id)
    if template is None:
        raise InvalidInput(f"unknown template {card.template_id!r}")
    if template.kind is not card.kind:
        raise InvalidInput(f"template {template.template_id!r} is for kind {template.kind}, card is {card.kind}")
    expected_text = {s for s, t in template.slots.items() if t in TEXT_SLOT_TYPES}
    extra = set(text_slots) - expected_text
    if extra:
        raise InvalidInput(f"text slots not in template {template.template_id!r}: {sorted(extra)}")
    values: dict[str, str] = {}
    displays: list[NumberDisplay] = []
    names: list[str] = []
    for slot, typ in template.slots.items():
        if typ == RULE_REF_SLOT:
            values[slot] = card.why.rule_ref
        elif typ in TEXT_SLOT_TYPES:
            if slot not in text_slots:
                raise InvalidInput(f"missing text slot {slot!r} for template {template.template_id!r}")
            check_slot_value(slot, text_slots[slot], typ, templates.linter)
            values[slot] = _normalise(text_slots[slot]).strip()
            if typ == "name":
                names.append(values[slot])
        else:
            number = card.number(slot)
            if number is None:
                raise InvalidInput(f"card has no number for slot {slot!r} (template {template.template_id!r})")
            if number.unit.value != typ:
                raise InvalidInput(f"slot {slot!r}: template wants unit {typ!r}, card number has {number.unit.value!r}")
            display = format_number(number.value, number.unit)
            values[slot] = display
            displays.append(NumberDisplay(slot, display, number.fact_ids, number.formula_id))
    text = _PLACEHOLDER.sub(lambda m: values[m.group(1)], template.text)
    hit = _forbidden_hit(text, template.card_class, templates.linter, ("forecast", "trade_call"))
    if hit:  # defence in depth: the parts were checked, the whole is checked again
        raise InvalidInput(f"rendered card text rejected ({hit})")
    return RenderedCard(
        card_id=card.card_id,
        template_id=template.template_id,
        text=text,
        numbers=tuple(displays),
        names=tuple(names),
    )
