"""A16: the ActionCard contract (design-risk-first.md §7.1, grafts 8 and 11 in design-judgement.md §2.2).

All values are SYNTHETIC. No real scheme, ISIN, NAV or rate appears here.
"""

from __future__ import annotations

import re
from dataclasses import fields, is_dataclass, replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from iip.engine.actions import contracts as c
from iip.engine.actions.cards import parse_templates, render_card
from iip.engine.determinism import content_hash
from iip.engine.errors import InvalidInput

TEMPLATES_PATH = Path(__file__).resolve().parents[2] / "src" / "iip" / "rules" / "action_templates.yaml"
AS_OF = date(2031, 3, 14)


def _templates() -> Any:
    return parse_templates(yaml.safe_load(TEMPLATES_PATH.read_text(encoding="utf-8")))


def num(slot: str, value: str | date, unit: c.NumberUnit, **kw: Any) -> c.CardNumber:
    if "fact_ids" not in kw and "formula_id" not in kw:
        kw["fact_ids"] = (f"fact:synthetic:{slot}",)
    v: Decimal | date = value if isinstance(value, date) else Decimal(value)
    return c.CardNumber(slot=slot, value=v, unit=unit, as_of=AS_OF, **kw)


def why(rule_id: str = "risk.emergency_gate", version: int = 1) -> c.Why:
    return c.Why(
        rule_id=rule_id,
        rule_version=version,
        parameters=(c.ParameterValue(name="months", value="6", set_by="user", set_on=date(2031, 1, 2)),),
    )


def emergency_card(**over: Any) -> c.ActionCard:
    base: dict[str, Any] = {
        "kind": c.CardKind.EMERGENCY_SHORTFALL,
        "layer": c.Layer.L1,
        "goal_id": None,
        "as_of": AS_OF,
        "deadline": None,
        "impact": c.Impact(amount_inr=Decimal(120000), basis=c.ImpactBasis.SHORTFALL, slot="shortfall"),
        "steps": (
            c.Step(
                verb=c.Verb.REDIRECT_SIP,
                instrument_id="inst-synthetic-overnight",
                amount_inr=Decimal(120000),
                formula_id="risk.emergency_gate@1",
            ),
        ),
        "why": why(),
        "numbers": (
            num("shortfall", "120000", c.NumberUnit.INR, formula_id="risk.emergency_gate@1"),
            num("months", "6", c.NumberUnit.MONTHS, fact_ids=("user:emergency_months",)),
        ),
        "template_id": "emergency_shortfall",
        "status": c.CardStatus.VERIFIED,
        "abstentions": (),
        "engine_version": "engine@test",
        "rules_version": "rules@test",
        "input_manifest_hash": "a" * 64,
        "snapshot_id": "snap-synthetic-1",
    }
    base.update(over)
    return c.ActionCard(**base)


# --- the binding acceptance check -------------------------------------------------------------------------------


def test_action_card_has_no_expected_return_field() -> None:
    names = {f.name for f in fields(c.ActionCard)}
    assert "expected_return" not in names


def _all_contract_dataclasses() -> list[type]:
    return [v for v in vars(c).values() if isinstance(v, type) and is_dataclass(v)]


def test_no_contract_dataclass_carries_a_forecast_field() -> None:
    forecastish = re.compile(r"expected|probab|forecast|predict|projected|upside|return_pct|cagr|xirr", re.I)
    offenders = [
        f"{cls.__name__}.{f.name}"
        for cls in _all_contract_dataclasses()
        for f in fields(cls)
        if forecastish.search(f.name)
    ]
    assert offenders == []


def test_action_card_rejects_an_expected_return_keyword() -> None:
    with pytest.raises(TypeError):
        emergency_card(expected_return=Decimal("0.12"))


# --- provenance on every number ---------------------------------------------------------------------------------


def test_card_number_requires_fact_id_or_formula_id() -> None:
    with pytest.raises(InvalidInput, match="fact_id or formula_id"):
        c.CardNumber(slot="x", value=Decimal(1), unit=c.NumberUnit.INR, as_of=AS_OF)


def test_card_number_rejects_blank_fact_ids_and_malformed_formula_ids() -> None:
    with pytest.raises(InvalidInput):
        c.CardNumber(slot="x", value=Decimal(1), unit=c.NumberUnit.INR, as_of=AS_OF, fact_ids=("",))
    with pytest.raises(InvalidInput, match="formula_id"):
        c.CardNumber(slot="x", value=Decimal(1), unit=c.NumberUnit.INR, as_of=AS_OF, formula_id="no-version")


def test_card_number_accepts_both_a_formula_and_its_input_facts() -> None:
    n = c.CardNumber(
        slot="x",
        value=Decimal(1),
        unit=c.NumberUnit.INR,
        as_of=AS_OF,
        fact_ids=("fact:a",),
        formula_id="tax.ltcg_harvest@1",
    )
    assert n.formula_id == "tax.ltcg_harvest@1"


def test_card_number_rejects_floats_and_non_finite_values() -> None:
    with pytest.raises(InvalidInput):
        c.CardNumber(slot="x", value=1.5, unit=c.NumberUnit.INR, as_of=AS_OF, fact_ids=("f",))  # type: ignore[arg-type]
    with pytest.raises(InvalidInput):
        c.CardNumber(slot="x", value=Decimal("NaN"), unit=c.NumberUnit.INR, as_of=AS_OF, fact_ids=("f",))


def test_date_unit_and_date_value_go_together() -> None:
    with pytest.raises(InvalidInput):
        c.CardNumber(slot="d", value=Decimal(1), unit=c.NumberUnit.DATE, as_of=AS_OF, fact_ids=("f",))
    with pytest.raises(InvalidInput):
        c.CardNumber(slot="d", value=AS_OF, unit=c.NumberUnit.INR, as_of=AS_OF, fact_ids=("f",))


def test_step_requires_a_formula_id() -> None:
    with pytest.raises(InvalidInput, match="formula_id"):
        c.Step(verb=c.Verb.INVEST, instrument_id=None, amount_inr=Decimal(1), formula_id="")


def test_impact_must_point_at_an_inr_number_with_the_same_value() -> None:
    with pytest.raises(InvalidInput, match="impact"):
        emergency_card(impact=c.Impact(amount_inr=Decimal(1), basis=c.ImpactBasis.SHORTFALL, slot="shortfall"))
    with pytest.raises(InvalidInput, match="impact"):
        emergency_card(impact=c.Impact(amount_inr=Decimal(6), basis=c.ImpactBasis.SHORTFALL, slot="months"))
    with pytest.raises(InvalidInput, match="impact"):
        emergency_card(impact=c.Impact(amount_inr=Decimal(6), basis=c.ImpactBasis.SHORTFALL, slot="missing"))


def test_duplicate_number_slots_are_rejected() -> None:
    dup = num("shortfall", "120000", c.NumberUnit.INR)
    with pytest.raises(InvalidInput, match="duplicate"):
        emergency_card(numbers=(dup, dup))


# --- identity, layers and kinds ---------------------------------------------------------------------------------


def test_card_id_is_sha256_of_kind_rule_goal_instruments_snapshot() -> None:
    card = emergency_card()
    expected = content_hash(
        {
            "kind": "EMERGENCY_SHORTFALL",
            "rule_ref": "risk.emergency_gate@1",
            "goal_id": None,
            "instrument_ids": ["inst-synthetic-overnight"],
            "snapshot_id": "snap-synthetic-1",
        }
    )
    assert card.card_id == expected
    assert re.fullmatch(r"[0-9a-f]{64}", card.card_id)


def test_card_id_is_stable_and_changes_with_snapshot() -> None:
    assert emergency_card().card_id == emergency_card().card_id
    assert emergency_card().card_id != emergency_card(snapshot_id="snap-synthetic-2").card_id


def test_card_id_cannot_be_supplied_by_the_caller() -> None:
    with pytest.raises(TypeError):
        emergency_card(card_id="forged")


def test_layer_must_match_kind() -> None:
    with pytest.raises(InvalidInput, match="layer"):
        emergency_card(layer=c.Layer.L5)


def test_every_kind_has_a_layer_and_a_class() -> None:
    for kind in c.CardKind:
        assert kind in c.KIND_CLASS
        assert kind is c.CardKind.ABSTAIN or kind in c.KIND_LAYER


def test_abstain_card_needs_an_abstention_and_no_steps() -> None:
    with pytest.raises(InvalidInput):
        emergency_card(kind=c.CardKind.ABSTAIN, layer=c.Layer.L3, impact=None, steps=(), abstentions=())
    ok = emergency_card(
        kind=c.CardKind.ABSTAIN,
        layer=c.Layer.L3,
        impact=None,
        steps=(),
        template_id="abstain_missing_input",
        abstentions=(c.Abstention(code="LOSS_LIMIT_MISSING", missing_input="loss_limit_inr", how_to_fix="Enter it"),),
    )
    assert ok.layer is c.Layer.L3


def test_no_action_needed_card_is_empty_by_construction() -> None:
    with pytest.raises(InvalidInput):
        emergency_card(kind=c.CardKind.NO_ACTION_NEEDED, layer=c.Layer.L8)
    card = emergency_card(
        kind=c.CardKind.NO_ACTION_NEEDED,
        layer=c.Layer.L8,
        impact=None,
        steps=(),
        numbers=(num("as_of", AS_OF, c.NumberUnit.DATE, fact_ids=("snapshot:data_date",)),),
        template_id="no_action_needed",
    )
    assert card.steps == ()


def test_abstention_upper_bound_needs_basis_and_formula() -> None:
    with pytest.raises(InvalidInput):
        c.Abstention(code="X", missing_input="y", how_to_fix="z", unlock_upper_bound_inr=Decimal(10))
    a = c.Abstention(
        code="X",
        missing_input="y",
        how_to_fix="z",
        unlock_upper_bound_inr=Decimal(15625),
        unlock_basis=c.ImpactBasis.TAX_DEFERRED,
        unlock_formula_id="needs.ltcg_unlock@1",
    )
    assert a.unlock_upper_bound_inr == Decimal(15625)


def test_breach_kinds_and_l0_suppress_lower_layers() -> None:
    assert emergency_card().suppresses_lower_layers
    assert not emergency_card(
        kind=c.CardKind.REBALANCE_DUE, layer=c.Layer.L5, template_id="rebalance_due", goal_id="g1"
    ).suppresses_lower_layers


# --- money arithmetic never mixes bases --------------------------------------------------------------------------


def test_sum_impacts_refuses_mixed_bases() -> None:
    a = c.Impact(amount_inr=Decimal(100), basis=c.ImpactBasis.SHORTFALL, slot="a")
    b = c.Impact(amount_inr=Decimal(50), basis=c.ImpactBasis.TAX_DEFERRED, slot="b")
    with pytest.raises(InvalidInput, match="bases"):
        c.sum_impacts((a, b))
    assert c.sum_impacts((a, replace(a, amount_inr=Decimal(5)))) == (c.ImpactBasis.SHORTFALL, Decimal(105))


# --- rendering ---------------------------------------------------------------------------------------------------


def test_render_emergency_card_fills_slots_with_indian_grouping() -> None:
    out = render_card(emergency_card(), _templates(), {"reserve_fund": "your overnight fund"})
    assert "₹1,20,000" in out.text
    assert "6 months" in out.text
    assert "risk.emergency_gate@1" in out.text
    assert "{" not in out.text
    slots = {d.slot: d for d in out.numbers}
    assert slots["shortfall"].formula_id == "risk.emergency_gate@1"
    assert slots["months"].fact_ids == ("user:emergency_months",)


def test_render_refuses_a_missing_number_or_text_slot() -> None:
    card = emergency_card(numbers=(num("shortfall", "120000", c.NumberUnit.INR),))
    with pytest.raises(InvalidInput, match="months"):
        render_card(card, _templates(), {"reserve_fund": "your overnight fund"})
    with pytest.raises(InvalidInput, match="reserve_fund"):
        render_card(emergency_card(), _templates(), {})


def test_render_refuses_a_number_slot_with_the_wrong_unit() -> None:
    card = emergency_card(
        numbers=(num("shortfall", "120000", c.NumberUnit.INR), num("months", "6", c.NumberUnit.DAYS)),
    )
    with pytest.raises(InvalidInput, match="unit"):
        render_card(card, _templates(), {"reserve_fund": "your overnight fund"})


def test_render_refuses_a_number_smuggled_in_through_a_name_slot() -> None:
    with pytest.raises(InvalidInput, match="number"):
        render_card(emergency_card(), _templates(), {"reserve_fund": "fund returning ₹12"})
    with pytest.raises(InvalidInput, match="number"):
        render_card(emergency_card(), _templates(), {"reserve_fund": "fund returning 12%"})


def test_name_slots_may_contain_digits_but_text_slots_may_not() -> None:
    out = render_card(emergency_card(), _templates(), {"reserve_fund": "Synthetic Index 50 Fund"})
    assert "Synthetic Index 50 Fund" in out.text
    assert out.names == ("Synthetic Index 50 Fund",)
    from iip.engine.actions.cards import check_slot_value

    with pytest.raises(InvalidInput, match="number"):
        check_slot_value("x", "missing 12 inputs", "text")


def test_render_refuses_forecast_language_smuggled_in_through_a_text_slot() -> None:
    with pytest.raises(InvalidInput, match="forecast"):
        render_card(emergency_card(), _templates(), {"reserve_fund": "a fund that will double"})


def test_render_refuses_template_of_another_kind() -> None:
    card = emergency_card(template_id="rebalance_due")
    with pytest.raises(InvalidInput, match="kind"):
        render_card(card, _templates(), {"reserve_fund": "x"})


def test_formatters() -> None:
    from iip.engine.actions.cards import format_number

    assert format_number(Decimal("12345678.5"), c.NumberUnit.INR) == "₹1,23,45,678.50"
    assert format_number(Decimal("999"), c.NumberUnit.INR) == "₹999"
    assert format_number(Decimal("-4000"), c.NumberUnit.INR) == "−₹4,000"
    assert format_number(Decimal("0.6824"), c.NumberUnit.PCT) == "68.2%"
    assert format_number(Decimal("0.05"), c.NumberUnit.PP) == "5.0 pp"
    assert format_number(Decimal("1412.3456"), c.NumberUnit.UNITS) == "1,412.346"
    assert format_number(Decimal("1"), c.NumberUnit.MONTHS) == "1 month"
    assert format_number(Decimal("4"), c.NumberUnit.MONTHS) == "4 months"
    assert format_number(Decimal("2.5"), c.NumberUnit.YEARS) == "2.5 years"
    assert format_number(Decimal("45"), c.NumberUnit.DAYS) == "45 days"
    assert format_number(Decimal("3"), c.NumberUnit.COUNT) == "3"
    assert format_number(date(2026, 10, 14), c.NumberUnit.DATE) == "14-Oct-2026"
