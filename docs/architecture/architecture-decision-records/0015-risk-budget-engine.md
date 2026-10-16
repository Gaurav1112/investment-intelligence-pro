# ADR-0015: Risk-budget engine (risk-first spine)

Status: **Proposed (2026-10-16), awaiting the owner's acceptance.** Built by packages A11 (rule tables), A12
(`engine/risk/`), A13 (`series_grid`), A14–A16 (actions and cards), B01–B02 (services).

## Context

- The owner asked what to do with his money, including "when to buy and sell", and named an aim of 20–25 %/yr.
- Wave-1 evidence (PLAN §2): no timing rule can pass honest evidence gates on Indian Direct-plan history for years; the
  20–25 % aim was reached by only 5–18 % of rolling 10-year windows of four broad TRIs and never at 25 %, with about 2
  independent windows (`research-evidence-allocation.md` §3, scoped by verify EA-1).
- What the app can say reliably is arithmetic on the owner's own holdings: sizing against a loss limit, safety, drift,
  cost and tax.
- Three designs were judged; risk-first won (51/60) with grafts (`design-judgement.md` §0, §2).

## Decision

1. **A fixed risk hierarchy per goal**, evaluated in this order; each layer returns `PASS`, `ACTION`, `BREACH`
   (suppresses lower layers for that goal) or `ABSTAIN` (named missing input):
   L0 data integrity → L1 emergency fund → L2 goal-date safety → L3 loss budget → L4 limits → L5 target and bands →
   L6 tax and cost → L7 validated signal tilts (empty at launch, ADR-0016) → L8 information
   (`design-risk-first.md` §4).
2. **The loss limit sets equity; the return aim never does.** Per goal `g` the owner enters `B_g` (₹ he would sit
   through without selling) and `T_g` (months he would wait to recover). With `b = B_g / V_g`:
   `e_cap_g = floor_to_0.01( min(policy_cap, (b − s_d) / (s_e − s_d)) )`, and `ABSTAIN(budget_below_non_equity_stress)`
   when `b < s_d` (`design-risk-first.md` §5.3). Fictional check: ₹10,00,000 and ₹2,50,000 give
   (0.25 − 0.03)/(0.67 − 0.03) = 0.34375 → 34 %. Until the owner sets `B_g` (U-02), that goal gets no equity
   recommendation.
3. **Stress per class = max(cited table value, drawdown recomputed in-app from AMFI index-fund NAVs)**, with both values
   and the AMFI series start date returned (graft 4). All equity sleeves are added at correlation 1; hybrids count as
   100 % equity until a cited equity-share table exists; a single stock (if ever enabled) is 1.00.
4. **The cited stress constants live in local config, not in the public repo** (U-08 default). The rule table
   `rules/risk/stress_drawdowns.yaml` keeps the schema and a citation pointer only. Provenance question: ADR-0017.
5. **No sale is ever triggered by a drawdown.** A breach is restored first by redirecting new money; a sale is offered
   only if the owner allows sales (U-04 default: cash-flow-only), chosen across schemes and folios by cost per rupee,
   with FIFO inside a folio (the engine never picks lots inside a folio).
6. **Pure and deterministic:** Decimal under `engine_context()`, `ROUND_FLOOR` on caps, no clock, IO or randomness in
   `engine/` (enforced by `backend/tests/unit/test_engine_purity.py`).
7. **Every output is an ActionCard** (`design-risk-first.md` §7.1, frozen) with a `fact_id` or `formula_id` on every
   number and **no `expected_return` field** (a unit test enforces this, A16). "Nothing needs doing today" is a valid
   result. Ranking key: (layer, deadline, ₹ impact, card_id); ₹ is never added across different bases.
8. **The supervisor abstains per goal and per layer** when a required fact is missing (ADR-0003 extended by
   `supervisor/manifest.py`, B02).

## Consequences

- On most days the honest answer is "nothing needs doing"; the app says so.
- Equity recommendations need the owner's ₹ loss limit first; setup asks for it with the crash history shown before
  any return figure.
- Worst observed falls are not worst possible falls; every stress card says so in those words.
- The 20–25 % aim is shown only as a feasibility range with historical frequencies.

## Not verified

- Stress constants' licence position (ADR-0017); gold stress until recomputed from AMFI NAVs; bounds for hybrid
  categories; the Vanguard ±5 pp band is US evidence (transfer to India NOT VERIFIED).

## Evidence

`docs/research/wave1/design-risk-first.md` §4–§5, §7; `design-judgement.md` §2.1 item 4, §2.2 items 7–11;
`research-evidence-allocation.md`; PLAN §2, §3 (U-02, U-04, U-08), rows A11–A16.
