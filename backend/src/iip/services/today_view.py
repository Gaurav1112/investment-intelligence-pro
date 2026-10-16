"""Today wire view (wave-2 integration: B02 stored payload -> C01 ``TodayResponse``).

The stored ``today_snapshot@1`` payload (:mod:`iip.services.risk_snapshot`) is canonical engine JSON. The Today page
(``frontend/src/lib/types-actions.ts``) needs every number with its exact display string and an ``Explained`` object
so the explain drawer opens without a second request. This module is a PURE reshaping of the payload that
:func:`iip.services.risk_snapshot.read_today` already returned (one statement); it computes nothing new:

* displays come from the rendered template (``displays``) or, for numbers the template does not show, from
  :func:`iip.engine.actions.cards.format_number` on the stored value;
* an ``Explained`` names the number's formula id and fact ids exactly as stored. Fact ids are NOT resolved to source
  documents here (that would cost more statements), and the explanation says so in ``limitations``;
* there is no expected return, probability or projection anywhere (ADR-0010).

The raw payload keys (``verdict``, ``decisions``, ``scopes``, ``flags``, ...) are kept, so the view is additive.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from iip.engine.actions.cards import format_number
from iip.engine.actions.contracts import NumberUnit
from iip.engine.actions.ranking import DEFAULT_TOP_N
from iip.engine.determinism import content_hash

VIEW_VERSION = "today_view@1"
NO_SNAPSHOT = "NO_SNAPSHOT"
_FACT_LIMITATION = (
    "Fact ids are listed under inputs; this view does not resolve them to source documents. "
    "See Data health for the sources behind stored facts."
)
_STEP_FIELDS: tuple[tuple[str, str, NumberUnit], ...] = (
    ("amount_inr", "amount", NumberUnit.INR),
    ("units", "units", NumberUnit.UNITS),
    ("net_effect_inr", "net effect", NumberUnit.INR),
)
_STEP_NESTED: tuple[tuple[str, str, str], ...] = (
    ("cost", "exit_load_inr", "exit load"),
    ("cost", "stamp_inr", "stamp duty"),
    ("cost", "stt_inr", "STT"),
    ("tax", "stcg_inr", "short-term gains tax"),
    ("tax", "ltcg_inr", "long-term gains tax"),
    ("tax", "cess_inr", "cess"),
)


def _display(value: str, unit: NumberUnit) -> str:
    if unit is NumberUnit.DATE:
        return format_number(date.fromisoformat(value), unit)
    return format_number(Decimal(value), unit)


def _freshness(fact_ids: Sequence[str], formula_id: str | None) -> str:
    if formula_id is None and fact_ids and all(f.startswith("user:") for f in fact_ids):
        return "USER_INPUT"
    return "DERIVED"


def number_view(
    *,
    eid: str,
    slot: str,
    label: str,
    value: str,
    unit: str,
    as_of: str,
    fact_ids: Sequence[str],
    formula_id: str | None,
    display: str | None,
    engine_version: str,
) -> dict[str, Any]:
    """One ``CardNumberView``: the stored number, its display and its ``Explained``."""
    u = NumberUnit(unit)
    shown = display if display is not None else _display(value, u)
    facts = list(fact_ids)
    inputs = [f"fact {f}" for f in facts]
    if formula_id is not None:
        formula, what = formula_id, f"The {label} on this card, computed by formula {formula_id}."
    else:
        formula, what = "stored fact (no formula)", f"The {label} on this card, taken as stored."
    core = {"id": eid, "value": value, "unit": unit, "formula_id": formula_id or "", "inputs": inputs,
            "engine_version": engine_version}  # fmt: skip
    explain = {
        "id": eid,
        "label": label,
        "display": shown,
        "value": value,
        "unit": unit,
        "what": what,
        "formula_id": formula_id or "",
        "formula": formula,
        "substituted": None,
        "inputs": inputs,
        "sources": [],
        "observed": as_of,
        "freshness": _freshness(facts, formula_id),
        "assumptions": [],
        "sensitivity": [],
        "limitations": [_FACT_LIMITATION] if facts else [],
        "engine_version": engine_version,
        "hash": content_hash(core),
    }
    return {"slot": slot, "value": value, "unit": unit, "as_of": as_of, "fact_ids": facts, "formula_id": formula_id,
            "display": shown, "explain": explain}  # fmt: skip


def _label(slot: str) -> str:
    return slot.replace("_", " ")


def _step_view(card: Mapping[str, Any], i: int, step: Mapping[str, Any], engine_version: str) -> dict[str, Any]:
    cid = str(card["card_id"])
    numbers: list[dict[str, Any]] = []

    def add(slot: str, label: str, value: Any, unit: NumberUnit) -> None:
        if value is None:
            return
        numbers.append(number_view(
            eid=f"{cid[:12]}.step{i}.{slot}", slot=slot, label=label, value=str(value), unit=unit.value,
            as_of=str(card["as_of"]), fact_ids=(), formula_id=str(step["formula_id"]), display=None,
            engine_version=engine_version,
        ))  # fmt: skip

    for key, label, unit in _STEP_FIELDS:
        add(key, label, step.get(key), unit)
    for group, key, label in _STEP_NESTED:
        sub = step.get(group)
        if isinstance(sub, Mapping) and sub.get(key) is not None and Decimal(str(sub[key])) != 0:
            add(key, label, sub[key], NumberUnit.INR)
    return {
        "verb": step["verb"],
        "instrument_id": step.get("instrument_id"),
        "instrument_name": None,  # not in the stored payload; the page falls back to the instrument id
        "formula_id": step["formula_id"],
        "folio": step.get("folio"),
        "lots_consumed": list(step.get("lots_consumed") or []),
        "wait_until": step.get("wait_until"),
        "numbers": numbers,
    }


def _layer(value: Any) -> str:
    return value if isinstance(value, str) and value.startswith("L") else f"L{int(value)}"


def _why(card: Mapping[str, Any]) -> dict[str, Any]:
    why = card.get("why") or {}
    rule_id, version = str(why.get("rule_id", "")), int(why.get("rule_version", 0))
    return {
        "rule_id": rule_id,
        "rule_version": version,
        "rule_ref": str(card.get("rule_ref") or f"{rule_id}@{version}"),
        "parameters": [
            {"name": p["name"], "value": p["value"], "set_by": p["set_by"], "set_on": p.get("set_on")}
            for p in why.get("parameters", [])
        ],
    }


def card_view(
    card: Mapping[str, Any],
    *,
    goal_names: Mapping[str, str],
    decision: Mapping[str, Any] | None,
    engine_version: str,
) -> dict[str, Any]:
    """One ``CardView`` from a stored card."""
    cid = str(card["card_id"])
    displays = {d["slot"]: d["display"] for d in card.get("displays") or []}
    numbers = [
        number_view(
            eid=f"{cid[:12]}.{n['slot']}", slot=n["slot"], label=_label(n["slot"]), value=str(n["value"]),
            unit=n["unit"], as_of=str(n["as_of"]), fact_ids=n.get("fact_ids") or (), formula_id=n.get("formula_id"),
            display=displays.get(n["slot"]), engine_version=engine_version,
        )
        for n in card.get("numbers") or []
    ]  # fmt: skip
    goal_id = card.get("goal_id")
    text = card.get("text")
    return {
        "card_id": cid,
        "kind": card["kind"],
        "layer": _layer(card["layer"]),
        "card_class": card["card_class"],
        "is_action": bool(card["is_action"]),
        "goal_id": goal_id,
        "goal_name": goal_names.get(goal_id) if goal_id else None,
        "as_of": card["as_of"],
        "deadline": card.get("deadline"),
        "status": card["status"],
        "template_id": card["template_id"],
        # A refused render keeps the numbers (with provenance) but has no sentence; say so instead of inventing one.
        "text": text if isinstance(text, str) else "This card's text could not be rendered; its numbers are below.",
        "impact": card.get("impact"),
        "steps": [_step_view(card, i, s, engine_version) for i, s in enumerate(card.get("steps") or [])],
        "why": _why(card),
        "numbers": numbers,
        "abstentions": [
            {"code": a["code"], "missing_input": a["missing_input"], "how_to_fix": a["how_to_fix"]}
            for a in card.get("abstentions") or []
        ],
        "decision": dict(decision) if decision else None,
    }


def _need_view(need: Mapping[str, Any], as_of: str, engine_version: str) -> dict[str, Any]:
    unlocks = [
        {
            "card_id": u["card_id"],
            "basis": u["basis"],
            "number": number_view(
                eid=f"{str(u['card_id'])[:12]}.unlock", slot="unlock_bound", label="amount this input unlocks",
                value=str(u["amount_inr"]), unit=NumberUnit.INR.value, as_of=as_of, fact_ids=(),
                formula_id=u["formula_id"], display=None, engine_version=engine_version,
            ),
        }
        for u in need.get("unlocks") or []
    ]  # fmt: skip
    return {
        "missing_input": need["missing_input"],
        "codes": list(need.get("codes") or []),
        "how_to_fix": list(need.get("how_to_fix") or []),
        "card_ids": list(need.get("card_ids") or []),
        "unlocks": unlocks,
    }


def decision_view(row: Mapping[str, Any]) -> dict[str, Any]:
    """A ``DecisionView`` from a ``decisions_log`` row (or its JSON form)."""
    cas = row.get("cas_confirmed")
    return {
        "decision_id": str(row["decision_id"]),
        "decided_at": row["decided_at"],
        "cas_confirmed": None if cas is None else bool(cas),
    }


def _latest_done(decisions: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for d in decisions:  # sorted by decided_at already; the last 'done' per card wins
        if d.get("decision") == "done" and d.get("decision_id") is not None:
            out[str(d["card_id"])] = decision_view(d)
    return out


def today_response(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Reshape :func:`read_today`'s result into the ``TodayResponse`` wire contract (additive: raw keys stay)."""
    out = dict(raw)
    if raw.get("state") == NO_SNAPSHOT or not raw.get("snapshot_id"):
        out.update({
            "state": NO_SNAPSHOT, "snapshot_id": None, "as_of": None, "computed_at": None, "engine_version": None,
            "rules_version": None, "input_manifest_hash": None, "top_n": DEFAULT_TOP_N, "cards": [], "suppressed": [],
            "needs": [],
        })  # fmt: skip
        return out
    ev = str(raw.get("engine_version") or "")
    as_of = str(raw.get("as_of") or "")
    goal_names = {str(s["scope_id"]): str(s["name"]) for s in raw.get("scopes") or [] if isinstance(s.get("name"), str)}
    done = _latest_done(raw.get("decisions") or [])
    out["cards"] = [
        card_view(c, goal_names=goal_names, decision=done.get(str(c["card_id"])), engine_version=ev)
        for c in raw.get("cards") or []
    ]
    out["suppressed"] = [
        {"card_id": s["card"]["card_id"], "kind": s["card"]["kind"], "layer": _layer(s["card"]["layer"]),
         "goal_id": s["card"].get("goal_id"), "suppressed_by": s["suppressed_by"]}
        for s in raw.get("suppressed") or []
    ]  # fmt: skip
    out["needs"] = [_need_view(n, as_of, ev) for n in raw.get("needs") or []]
    out["top_n"] = DEFAULT_TOP_N  # compute_snapshot ranks with the default top_n
    out["view_version"] = VIEW_VERSION
    return out
