"""A16: the action-template linter (design-evidence-first.md §3.1; design-judgement.md graft 11; PLAN U-11).

Every shipped template is linted at parse time, rendered with SYNTHETIC values, and then re-checked by the existing
compliance guard and numeric-provenance validator (``iip.supervisor.compliance``).
"""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from iip.engine.actions import contracts as c
from iip.engine.actions.cards import (
    TEXT_SLOT_TYPES,
    LintFinding,
    TemplateSet,
    format_number,
    lint_template_text,
    parse_templates,
    render_card,
)
from iip.engine.errors import InvalidInput
from iip.supervisor.compliance import blocked, unsupported_numbers

TEMPLATES_PATH = Path(__file__).resolve().parents[2] / "src" / "iip" / "rules" / "action_templates.yaml"
AS_OF = date(2031, 3, 14)


def _raw() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(TEMPLATES_PATH.read_text(encoding="utf-8"))
    return data


def _set() -> TemplateSet:
    return parse_templates(_raw())


def _lint(text: str, card_class: c.CardClass = c.CardClass.POLICY) -> list[LintFinding]:
    return lint_template_text(text, card_class, _set().linter)


# --- the shipped templates ---------------------------------------------------------------------------------------


def test_shipped_templates_parse_and_lint_clean() -> None:
    ts = _set()
    assert ts.version.startswith("action_templates@")
    for t in ts.templates.values():
        assert lint_template_text(t.text, t.card_class, ts.linter) == [], t.template_id


def test_every_card_kind_has_a_template() -> None:
    kinds = {t.kind for t in _set().templates.values()}
    assert kinds == set(c.CardKind)


def test_template_class_matches_kind_class() -> None:
    for t in _set().templates.values():
        assert t.card_class is c.KIND_CLASS[t.kind], t.template_id


# --- the linter rejects forecast language ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Your rule {rule_ref} says: this fund will return more than the index.",
        "Your rule {rule_ref} says: the expected return of {scheme_name} is high.",
        "Your rule {rule_ref} says: equity is likely to rise from here.",
        "Your rule {rule_ref} says: the probability of profit is high.",
        "Your rule {rule_ref} says: our forecast shows growth.",
        "Your rule {rule_ref} says: we predict a recovery.",
        "Your rule {rule_ref} says: your goal is on track.",
        "Your rule {rule_ref} says: this sleeve should outperform.",
        "Your rule {rule_ref} says: there is upside left.",
        "Your rule {rule_ref} says: the potential gains are large.",
        "Your rule {rule_ref} says: future returns favour equity.",
        "Your rule {rule_ref} says: this could double your money.",
        "Your rule {rule_ref} says: the fund will beat inflation.",
    ],
)
def test_linter_rejects_forecast_language_in_policy_text(text: str) -> None:
    findings = _lint(text)
    assert any(f.category == "forecast" for f in findings), text


@pytest.mark.parametrize(
    "text",
    [
        "Your rule {rule_ref} says: buy {scheme_name}.",
        "Your rule {rule_ref} says: sell {scheme_name}.",
        "Your rule {rule_ref} says: selling now avoids a fall.",
        "Your rule {rule_ref} says: set a stop-loss.",
        "Your rule {rule_ref} says: the target price is reached.",
        "Your rule {rule_ref} says: strong buy.",
        "Your rule {rule_ref} says: book profits.",
    ],
)
def test_linter_rejects_trade_call_words_per_u11(text: str) -> None:
    assert any(f.category == "trade_call" for f in _lint(text)), text


def test_trade_call_words_are_rejected_in_signal_cards_too() -> None:
    text = "Entry condition met: rule {rule_ref}. BUY {scheme_name}."
    assert any(f.category == "trade_call" for f in _lint(text, c.CardClass.SIGNAL))


def test_forecast_words_are_rejected_in_every_class() -> None:
    for cls in c.CardClass:
        assert any(f.category == "forecast" for f in _lint("It will rise. {rule_ref} your rule says", cls)), cls


def test_linter_rejects_literal_digits_and_number_words_in_static_text() -> None:
    assert any(f.category == "literal_number" for f in _lint("Your rule {rule_ref} says: keep 6 months."))
    assert any(f.category == "literal_number" for f in _lint("Your rule {rule_ref} says: keep six months."))
    assert any(f.category == "literal_number" for f in _lint("Your rule {rule_ref} says: halve it."))


def test_linter_sees_through_invisible_and_fullwidth_characters() -> None:
    assert any(f.category == "forecast" for f in _lint("Your rule {rule_ref} says: it wi\u200bll return more."))
    assert any(f.category == "trade_call" for f in _lint("Your rule {rule_ref} says: \uff42\uff55\uff59 it."))


def test_policy_text_must_say_your_rule_and_carry_the_rule_ref() -> None:
    assert any(f.category == "policy_voice" for f in _lint("Put money into {scheme_name}."))
    assert any(f.category == "policy_voice" for f in _lint("Your rule says: redirect the SIP."))


def test_signal_text_must_use_neutral_condition_wording() -> None:
    bad = _lint("Rule {rule_ref} fired for {scheme_name}.", c.CardClass.SIGNAL)
    assert any(f.category == "signal_voice" for f in bad)
    ok = _lint("Exit condition met: rule {rule_ref}, as of {as_of}.", c.CardClass.SIGNAL)
    assert ok == []


def test_allowed_neutral_words_pass() -> None:
    text = (
        "Your rule {rule_ref} says: redirect the SIP, invest {amount}, redeem {units} units, switch, wait until "
        "{lt_date} and review. Exit load {exit_load}. In the worst fall in the history of the funds you hold, "
        "this goal would have lost {stress_loss}. This is the expected result, not an error."
    )
    assert _lint(text) == []


# --- parse-time enforcement --------------------------------------------------------------------------------------


def test_parse_rejects_a_template_with_forecast_language() -> None:
    raw = copy.deepcopy(_raw())
    tid = next(iter(raw["templates"]))
    raw["templates"][tid]["text"] += " This will grow."
    with pytest.raises(InvalidInput, match="forecast"):
        parse_templates(raw)


def test_parse_rejects_undeclared_or_unused_slots() -> None:
    raw = copy.deepcopy(_raw())
    tid = next(iter(raw["templates"]))
    raw["templates"][tid]["text"] += " {undeclared_slot}"
    with pytest.raises(InvalidInput, match="slot"):
        parse_templates(raw)
    raw = copy.deepcopy(_raw())
    raw["templates"][tid]["slots"]["unused_slot"] = "inr"
    with pytest.raises(InvalidInput, match="slot"):
        parse_templates(raw)


def test_parse_rejects_unknown_fields_kinds_and_units() -> None:
    raw = copy.deepcopy(_raw())
    tid = next(iter(raw["templates"]))
    raw["templates"][tid]["surprise"] = 1
    with pytest.raises(InvalidInput):
        parse_templates(raw)
    raw = copy.deepcopy(_raw())
    raw["templates"][tid]["kind"] = "BUY_SIGNAL"
    with pytest.raises(InvalidInput):
        parse_templates(raw)
    raw = copy.deepcopy(_raw())
    first_slot = next(iter(raw["templates"][tid]["slots"]))
    raw["templates"][tid]["slots"][first_slot] = "furlongs"
    with pytest.raises(InvalidInput):
        parse_templates(raw)


def test_parse_rejects_a_missing_linter_category() -> None:
    raw = copy.deepcopy(_raw())
    del raw["linter"]["forecast"]
    with pytest.raises(InvalidInput, match="forecast"):
        parse_templates(raw)


# --- the rendered text passes the existing compliance guard and numeric validator ------------------------------

_SYNTHETIC_VALUE: dict[c.NumberUnit, Decimal | date] = {
    c.NumberUnit.INR: Decimal("123456"),
    c.NumberUnit.PCT: Decimal("0.6824"),
    c.NumberUnit.PP: Decimal("0.05"),
    c.NumberUnit.UNITS: Decimal("1412.346"),
    c.NumberUnit.MONTHS: Decimal(4),
    c.NumberUnit.YEARS: Decimal(3),
    c.NumberUnit.DAYS: Decimal(45),
    c.NumberUnit.COUNT: Decimal(7),
    c.NumberUnit.DATE: date(2031, 2, 1),
}


def _card_for(template_id: str, kind: c.CardKind, numbers: tuple[c.CardNumber, ...]) -> c.ActionCard:
    layer = c.KIND_LAYER.get(kind, c.Layer.L3)
    abst: tuple[c.Abstention, ...] = ()
    if kind in (c.CardKind.ABSTAIN, c.CardKind.DATA_ATTENTION):
        abst = (c.Abstention(code="SYNTHETIC", missing_input="synthetic_input", how_to_fix="Enter it"),)
    return c.ActionCard(
        kind=kind,
        layer=layer,
        goal_id=None,
        as_of=AS_OF,
        deadline=None,
        impact=None,
        steps=(),
        why=c.Why(rule_id="policy.synthetic", rule_version=1, parameters=()),
        numbers=numbers,
        template_id=template_id,
        status=c.CardStatus.NOT_VERIFIED,
        abstentions=abst,
        engine_version="engine@test",
        rules_version="rules@test",
        input_manifest_hash="b" * 64,
        snapshot_id="snap-synthetic",
    )


def test_every_template_renders_clean_under_the_compliance_guard() -> None:
    ts = _set()
    for t in ts.templates.values():
        numbers = tuple(
            c.CardNumber(
                slot=s,
                value=_SYNTHETIC_VALUE[c.NumberUnit(u)],
                unit=c.NumberUnit(u),
                as_of=AS_OF,
                fact_ids=(f"fact:synthetic:{s}",),
            )  # every number traceable
            for s, u in t.slots.items()
            if u not in TEXT_SLOT_TYPES and s != "rule_ref"
        )
        text_values = {
            s: "Synthetic Fund Alpha" for s, u in t.slots.items() if u in TEXT_SLOT_TYPES and s != "rule_ref"
        }
        out = render_card(_card_for(t.template_id, t.kind, numbers), ts, text_values)
        assert blocked(out.text) == [], (t.template_id, out.text)
        displays = frozenset(d.display for d in out.numbers) | frozenset({"policy.synthetic@1"}) | frozenset(out.names)
        assert unsupported_numbers(out.text, displays) == [], (t.template_id, out.text)
        for d in out.numbers:
            assert d.fact_ids or d.formula_id, (t.template_id, d.slot)


def test_rendered_numbers_use_the_shared_formatter() -> None:
    assert format_number(Decimal("123456"), c.NumberUnit.INR) == "₹1,23,456"
