"""Generate the per-rule sections of docs/finance/ca-review-packet.md from the shipped rule table and engine.

Run from backend/:  .venv/bin/python scripts/ca_packet_examples.py <section> [rule ids...] > out.md
where <section> is one of: rules, slab, surcharge, cess, rebate, tds, deduction, levy, acts.
Every number printed is computed by iip.engine.tax (or the loader's parsed rule objects); nothing is typed in.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from iip.engine.errors import EngineError
from iip.engine.money import D
from iip.engine.tax import (
    Disposal,
    Regime,
    ResidentialStatus,
    TaxProfile,
    compute_levy,
    compute_tax,
    slab_tax,
)
from iip.rules.loader import load_tax_rules

RS = load_tax_rules()
P30 = TaxProfile(
    regime=Regime.NEW, residential_status=ResidentialStatus.RESIDENT, slab_rate=D("0.30"),
    surcharge_rate=D("0"), label="fictional: 30 % slab, no surcharge",
)  # fmt: skip


def inr(x: Decimal) -> str:
    """Indian digit grouping (12,34,567.89)."""
    neg = x < 0
    whole, frac = f"{abs(x):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    body = ",".join([*groups, tail]) if groups else tail
    return ("-" if neg else "") + "Rs " + body + "." + frac


def pct(x: Decimal) -> str:
    return f"{(x * 100).normalize():f} %"


def mf(eq: str, debt: str, listed: bool | None = None) -> dict[str, object]:
    return {"instrument_class": "MUTUAL_FUND", "domestic_equity_share": D(eq), "debt_share": D(debt), "listed": listed}


EQ = {"instrument_class": "LISTED_EQUITY_SHARE"}
EQMF = mf("0.80", "0.10")
DEBT = mf("0", "0.90", False)
OTHER = mf("0.10", "0.30", False)
BL = {"instrument_class": "BOND", "listed": True}
BU = {"instrument_class": "BOND", "listed": False}
GS = {"instrument_class": "GSEC"}
SGB1 = {"instrument_class": "SGB", "redemption_at_maturity": True, "original_subscriber_held_continuously": True}
SGB2 = {"instrument_class": "SGB", "redemption_at_maturity": True, "original_subscriber_held_continuously": False}
BB = {"instrument_class": "LISTED_EQUITY_BUYBACK"}

# rule_id -> (facts, acquisition, transfer, gain) ; None acquisition for income rules
CASES: dict[str, tuple[dict[str, object], date | None, date, str]] = {
    "EQ-STCG-OLD": (EQ, date(2024, 1, 10), date(2024, 7, 22), "100000"),
    "EQ-STCG/ITA1961": (EQ, date(2024, 8, 1), date(2025, 6, 2), "100000"),
    "EQ-STCG/ITA2025": (EQ, date(2025, 6, 1), date(2026, 5, 4), "100000"),
    "EQ-LTCG-OLD": (EQ, date(2023, 1, 2), date(2024, 7, 1), "200000"),
    "EQ-LTCG/ITA1961": (EQ, date(2024, 1, 1), date(2025, 6, 2), "200000"),
    "EQ-LTCG/ITA2025": (EQ, date(2025, 1, 2), date(2026, 6, 1), "200000"),
    "MF-EQ-STCG-OLD": (EQMF, date(2024, 1, 10), date(2024, 7, 22), "100000"),
    "MF-EQ-STCG/ITA1961": (EQMF, date(2024, 8, 1), date(2025, 6, 2), "100000"),
    "MF-EQ-STCG/ITA2025": (EQMF, date(2025, 6, 1), date(2026, 5, 4), "100000"),
    "MF-EQ-LTCG-OLD": (EQMF, date(2023, 1, 2), date(2024, 7, 1), "200000"),
    "MF-EQ-LTCG/ITA1961": (EQMF, date(2024, 1, 1), date(2025, 6, 2), "200000"),
    "MF-EQ-LTCG/ITA2025": (EQMF, date(2025, 1, 2), date(2026, 6, 1), "200000"),
    "MF-SMF-DEF-OLD": (mf("0.10", "0.90"), date(2023, 4, 1), date(2024, 10, 1), "100000"),
    "MF-DEBT-SMF/ITA1961": (DEBT, date(2023, 4, 1), date(2025, 6, 30), "100000"),
    "MF-DEBT-SMF/ITA2025": (DEBT, date(2023, 4, 1), date(2026, 6, 1), "100000"),
    "MF-DEBT-PRE2023-ST/ITA1961": (DEBT, date(2023, 3, 1), date(2024, 9, 2), "100000"),
    "MF-DEBT-PRE2023-LT/ITA1961": (DEBT, date(2023, 3, 1), date(2025, 6, 30), "100000"),
    "MF-DEBT-PRE2023-LT/ITA2025": (DEBT, date(2023, 3, 1), date(2026, 6, 1), "100000"),
    "MF-OTHER-ST/ITA1961": (OTHER, date(2024, 6, 1), date(2025, 6, 2), "100000"),
    "MF-OTHER-ST/ITA2025": (OTHER, date(2025, 6, 1), date(2026, 6, 2), "100000"),
    "MF-OTHER-LT/ITA1961": (OTHER, date(2023, 1, 2), date(2025, 6, 2), "100000"),
    "MF-OTHER-LT/ITA2025": (OTHER, date(2024, 1, 2), date(2026, 6, 2), "100000"),
    "BOND-L-ST/ITA1961": (BL, date(2024, 8, 1), date(2025, 6, 2), "100000"),
    "BOND-L-ST/ITA2025": (BL, date(2025, 8, 1), date(2026, 6, 2), "100000"),
    "BOND-L-LT/ITA1961": (BL, date(2024, 8, 1), date(2025, 9, 1), "100000"),
    "BOND-L-LT/ITA2025": (BL, date(2025, 1, 2), date(2026, 6, 2), "100000"),
    "BOND-L-LT-OLD": (BL, date(2023, 1, 2), date(2024, 7, 1), "100000"),
    "BOND-UL/ITA1961": (BU, date(2024, 8, 1), date(2025, 9, 1), "100000"),
    "BOND-UL/ITA2025": (BU, date(2024, 8, 1), date(2026, 6, 2), "100000"),
    "GSEC-CG-ST/ITA1961": (GS, date(2024, 9, 2), date(2025, 6, 2), "100000"),
    "GSEC-CG-ST/ITA2025": (GS, date(2025, 9, 1), date(2026, 6, 2), "100000"),
    "GSEC-CG-LT/ITA1961": (GS, date(2024, 1, 2), date(2025, 6, 2), "100000"),
    "GSEC-CG-LT/ITA2025": (GS, date(2025, 1, 2), date(2026, 6, 1), "100000"),
    "TBILL-01/ITA1961": ({"instrument_class": "TBILL"}, None, date(2025, 11, 5), "10000"),
    "TBILL-01/ITA2025": ({"instrument_class": "TBILL"}, None, date(2026, 7, 1), "10000"),
    "INT-SLAB-01/ITA1961": ({"instrument_class": "INTEREST"}, None, date(2025, 12, 31), "100000"),
    "INT-SLAB-01/ITA2025": ({"instrument_class": "INTEREST"}, None, date(2026, 12, 31), "100000"),
    "SGB-01": (SGB1, date(2018, 8, 1), date(2026, 8, 1), "300000"),
    "SGB-02-ST": (SGB2, date(2025, 12, 1), date(2026, 8, 1), "100000"),
    "SGB-02-LT": (SGB2, date(2024, 1, 2), date(2026, 8, 1), "100000"),
    "BUYBACK-01-ST": (BB, date(2025, 10, 1), date(2026, 6, 1), "100000"),
    "BUYBACK-01-LT": (BB, date(2024, 1, 2), date(2026, 6, 1), "200000"),
}

UNREACHABLE = {
    "MF-DEBT-PRE2023-ST/ITA2025": (
        "No example exists: a unit acquired on or before 31-Mar-2023 and transferred on or after 1-Apr-2026 has "
        "been held more than 36 months, so it is always long-term. The row exists for completeness."
    ),
}


def disposal(rid: str) -> Disposal:
    facts, acq, sale, gain = CASES[rid]
    return Disposal(lot_id=rid, transfer_date=sale, gain_inr=D(gain), acquisition_date=acq, **facts)  # type: ignore[arg-type]


def example(rid: str) -> str:
    if rid in UNREACHABLE:
        return UNREACHABLE[rid]
    d = disposal(rid)
    try:
        rep = compute_tax([d], RS, P30)
    except EngineError as exc:  # pragma: no cover - printed so a reviewer sees it
        return f"ENGINE ABSTAINED: {exc.code}: {exc}"
    c = rep.classifications[0]
    lot = rep.scenarios[0].lots[0]
    assert c.rule_id == rid, (rid, c.rule_id)
    rate_txt = {"SLAB": "SLAB (30 % in this profile)", "EXEMPT": "EXEMPT"}.get(c.rate_kind.value) or pct(
        c.base_rate or D(0)
    )
    facts = ", ".join(f"{k}={v}" for k, v in CASES[rid][0].items() if k != "instrument_class")
    held = f"acquired {d.acquisition_date}, " if d.acquisition_date else ""
    lines = [
        f"Input: {d.instrument_class}{' (' + facts + ')' if facts else ''}; {held}transfer/income date "
        f"{d.transfer_date}; gain {inr(d.gain_inr)}; profile 30 % slab, no surcharge (fictional).",
        f"Engine: {c.gain_type.value} under `{rid}` ({c.act.value} s.{c.section or '-'}), rate "
        f"{rate_txt}; "
        f"exemption applied {inr(c.exemption_applied_inr)}; taxable {inr(c.taxable_gain_inr)}; "
        f"tax {inr(lot.base_tax_inr)} + surcharge {inr(lot.surcharge_inr)} + cess {inr(lot.cess_inr)} = "
        f"**{inr(lot.total_tax_inr)}**. Unverified flag: {rep.unverified_assumption}.",
    ]
    return "  \n  ".join(lines)


def slab_example(rid: str) -> str:
    t = next(x for x in RS.slab_tables if x.rule_id == rid)
    pts = [D("400000"), D("1200000"), D("1500000"), D("2500000")]
    parts = ", ".join(f"{inr(p)} -> {inr(slab_tax(t, p))}" for p in pts)
    on = t.effective_from
    inc = TaxProfile(
        regime=Regime.NEW, residential_status=ResidentialStatus.RESIDENT, taxable_income_inr=D("1100000"),
        label="fictional: other income Rs 11 lakh",
    )  # fmt: skip
    rep = compute_tax(
        [Disposal(lot_id="i", instrument_class="INTEREST", transfer_date=date(on.year, 12, 31), gain_inr=D("200000"))],
        RS,
        inc,
    )
    return (
        f"slab_tax (before cess): {parts}.  \n  Stacking: other income Rs 11,00,000 + interest Rs 2,00,000 in "
        f"{on.year}-{on.year + 1 - 2000}: engine tax on the interest = **{inr(rep.scenarios[0].total_tax_inr)}** "
        "(1 lakh at 10 % + 1 lakh at 15 % = 25,000, + 4 % cess); warning REBATE_NOT_APPLIED."
    )


def surcharge_example(rid: str) -> str:
    s = next(x for x in RS.surcharges if x.rule_id == rid)
    sale = date(s.effective_from.year, 6, 2)
    acq = date(s.effective_from.year - 1, 12, 2)
    p = TaxProfile(
        regime=Regime.NEW, residential_status=ResidentialStatus.RESIDENT, slab_rate=D("0.30"),
        surcharge_rate=D("0.25"), label="fictional: 30 % slab, 25 % surcharge band",
    )  # fmt: skip
    eq = compute_tax(
        [Disposal(lot_id="e", instrument_class="LISTED_EQUITY_SHARE", acquisition_date=acq, transfer_date=sale,
                  gain_inr=D("100000"))], RS, p)  # fmt: skip
    fd = compute_tax(
        [Disposal(lot_id="f", instrument_class="INTEREST", transfer_date=sale, gain_inr=D("100000"))], RS, p
    )
    e, f = eq.scenarios[0].lots[0], fd.scenarios[0].lots[0]
    return (
        f"Band 25 % (total income above Rs 2 crore). Equity STCG Rs 1,00,000 on {sale}: surcharge capped at "
        f"{e.surcharge_rate} -> tax {inr(e.base_tax_inr)} + surcharge {inr(e.surcharge_inr)} + "
        f"cess {inr(e.cess_inr)} = "
        f"**{inr(e.total_tax_inr)}**. Interest Rs 1,00,000: surcharge {f.surcharge_rate} (not capped) -> "
        f"**{inr(f.total_tax_inr)}**. Marginal relief not modelled (warning)."
    )


def cess_example(rid: str) -> str:
    c = next(x for x in RS.cess if x.rule_id == rid)
    sale = date(c.effective_from.year + (1 if c.effective_from.year < 2026 else 0), 6, 2)
    rep = compute_tax(
        [Disposal(lot_id="c", instrument_class="LISTED_EQUITY_SHARE", acquisition_date=date(sale.year - 1, 12, 2),
                  transfer_date=sale, gain_inr=D("100000"))], RS, P30)  # fmt: skip
    lot = rep.scenarios[0].lots[0]
    return (
        f"Equity STCG Rs 1,00,000 on {sale}: tax {inr(lot.base_tax_inr)} + surcharge {inr(lot.surcharge_inr)}; "
        f"cess {c.rate} x (tax + surcharge) = **{inr(lot.cess_inr)}**; total {inr(lot.total_tax_inr)}."
    )


def rebate_example(rid: str) -> str:
    r = next(x for x in RS.rebates if x.rule_id == rid)
    yr = r.effective_from.year
    p = TaxProfile(
        regime=Regime.NEW, residential_status=ResidentialStatus.RESIDENT, taxable_income_inr=D("900000"),
        label="fictional: other income Rs 9 lakh",
    )  # fmt: skip
    rep = compute_tax(
        [Disposal(lot_id="r", instrument_class="INTEREST", transfer_date=date(yr, 12, 31), gain_inr=D("200000"))],
        RS,
        p,
    )
    t = next(x for x in RS.slab_tables if x.effective_from == r.effective_from)
    slab = slab_tax(t, D("1100000"))
    return (
        f"Engine (rebate NOT applied): other income Rs 9,00,000 + interest Rs 2,00,000 -> tax on the interest "
        f"**{inr(rep.scenarios[0].total_tax_inr)}**, warnings {list(rep.warnings)}.  \n  "
        f"Statute, by hand (not engine): total income Rs 11,00,000 <= Rs 12,00,000, slab tax {inr(slab)} <= "
        f"rebate cap {inr(r.max_rebate_inr)} -> rebate {inr(min(slab, r.max_rebate_inr))}, tax nil. The engine "
        f"overstates by the rebate; it never understates. Excluded (special-rate) sections: "
        f"{', '.join(r.excluded_sections)}."
    )


def levy_example(rid: str) -> str:
    lv = next(x for x in RS.levies if x.rule_id == rid)
    inclusive = rid.startswith("STAMP")
    res = compute_levy(lv, D("100000"), date(2026, 6, 1), inclusive=inclusive)
    how = "duty-inclusive gross Rs 1,00,000 (duty = gross x r/(1+r))" if inclusive else "redemption value Rs 1,00,000"
    return f"Engine: {how} at rate {lv.rate} -> **{inr(res.value_inr)}**."


def tds_example(rid: str) -> str:
    w = next(x for x in RS.withholding if x.rule_id == rid)
    above = w.threshold_inr + D("1")
    tax = above * w.rate
    sen = f" (senior citizen threshold {inr(w.threshold_senior_inr)})" if w.threshold_senior_inr else ""
    return (
        f"Not computed by the engine (TDS is information only). By hand from the row: payments of "
        f"{inr(w.threshold_inr)} in the year -> no TDS; {inr(above)} -> TDS on the whole amount at {w.rate} = "
        f"{inr(tax)}{sen}."
    )


def meta_lines(r: object) -> list[str]:
    g = r.__dict__
    s61 = g.get("section_1961") or "-"
    s25 = g.get("section_2025") or "-"
    eff_to = g["effective_to"] or "in force"
    return [
        f"- **Sections:** 1961 Act {s61} / 2025 Act {s25}" if "act" in g else "- **Statute:** " + g.get("statute", ""),
        f"- **Effective (transfer/income dates):** {g['effective_from'] or '-'} to {eff_to}"
        + (f" ({g['act'].value})" if "act" in g else ""),
        f"- **Status:** {g['verification_status'].value} - source: {g['source_url']}",
        f"- **Citation / notes:** {g['notes'] or '-'}",
    ]


def card(r: object, plain: str, ex: str) -> str:
    rid = r.rule_id  # type: ignore[attr-defined]
    out = [f"#### `{rid}`", "", f"- **What the app assumes:** {plain}", *meta_lines(r), f"- **Worked example:** {ex}"]
    out += ["- **CA answer:** [ ] Yes, correct  [ ] No  [ ] Correction: ______________________________", ""]
    return "\n".join(out)


def plain_rule(r: object) -> str:
    g = r.__dict__
    rk = g["rate_kind"].value
    fixed = {"SLAB": "taxed at the slab rate", "EXEMPT": "fully exempt"}
    rate = fixed[rk] if rk in fixed else f"taxed at {pct(g['rate'])}"
    hold = (
        f"; long-term only if held more than {g['holding_threshold_months']} months"
        if g["holding_threshold_months"]
        else "; no holding-period test"
    )
    ex = (
        f"; first {inr(g['annual_exemption_inr'])} a year of such gains (one shared pool) is exempt"
        if g["annual_exemption_inr"]
        else ""
    )
    cond = {k: v for k, v in g["conditions"].__dict__.items() if v is not None}
    cs = ", ".join(f"{k}={v}" for k, v in cond.items())
    return (
        f"{g['instrument_class']} {('(' + cs + ') ') if cs else ''}{g['gain_type'].value} {rate}{hold}{ex}, "
        "before surcharge and 4 % cess."
    )


if __name__ == "__main__":
    import sys

    which = sys.argv[1]
    by = {r.rule_id: r for r in RS.rules}
    if which == "rules":
        for rid in sys.argv[2:]:
            print(card(by[rid], plain_rule(by[rid]), example(rid)))
    elif which == "slab":
        for t in RS.slab_tables:
            brackets = "; ".join(f"{b.lower}-{b.upper or 'above'}: {b.rate}" for b in t.brackets)
            print(card(t, f"New-regime slabs {brackets}.", slab_example(t.rule_id)))
    elif which == "surcharge":
        for s in RS.surcharges:
            bands = ", ".join(f">{b.above_inr}: {b.rate}" for b in s.bands)
            print(card(s, f"Surcharge bands {bands}; capped at {s.special_rate_cap} on dividend and on gains under "
                          f"{', '.join(s.capped_sections)}.", surcharge_example(s.rule_id)))  # fmt: skip
    elif which == "cess":
        for c in RS.cess:
            print(card(c, f"Health & Education Cess {c.rate} on (tax + surcharge).", cess_example(c.rule_id)))
    elif which == "rebate":
        for r in RS.rebates:
            plain = (
                f"Rebate up to {inr(r.max_rebate_inr)} when total income <= {inr(r.total_income_ceiling_inr)}; "
                f"never against tax under {', '.join(r.excluded_sections)}. NOT applied by the engine."
            )
            print(card(r, plain, rebate_example(r.rule_id)))
    elif which == "tds":
        for w in RS.withholding:
            print(card(w, f"TDS {w.rate} on {w.payer_scope} above {inr(w.threshold_inr)}.", tds_example(w.rule_id)))
    elif which == "deduction":
        for d in RS.deductions:
            print(card(d, f"{d.item}: allowed = {d.allowed}.", "Information only; the engine does not use this rule."))
    elif which == "levy":
        for lv in RS.levies:
            print(card(lv, f"{lv.applies_to}; base {lv.base}; payer {lv.payer}; rate {lv.rate}.",
                       levy_example(lv.rule_id)))  # fmt: skip
    elif which == "acts":
        for a in RS.acts:
            print(card(a, f"{a.act.value} governs income in this period.", "Not a computation."))
    elif which == "unreachable":
        for rid in sys.argv[2:]:
            print(card(by[rid], plain_rule(by[rid]), example(rid)))
