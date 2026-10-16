# ADR-0016: Signal registry, shadow ledger and evidence gates

Status: **Proposed (2026-10-16), awaiting the owner's acceptance.** The gate thresholds were confirmed by the owner on
2026-10-16 (U-06: kept as written, frozen before any run). Built by A10 (tables), A17–A18 (ledger, stats gates), B02
(shadow evaluation), B05 (runner, walk-forward, CLI), C03 (Signals page). Method: `docs/forecasting/backtest-methodology.md`.

## Context

- ADR-0010 covers forecasts only. Nothing governs trading signals; multiple-testing control is "guidance only, not used
  in v1" (`validation-methodology.md`, verify BT-2).
- The best of 100 zero-skill variants over 10 years shows an annualised Sharpe of about 0.80 by luck (fixture MT-1).
- A true 0.5-Sharpe edge needs about 132 out-of-sample months for PSR 0.95 at roughly 50 % power, and about 298 months
  for 80 % power (MT-3; verify BT-9).

## Decision

1. **Registry of frozen rules.** Each signal is a committed YAML spec (`rules/signals/<id>@<version>.yaml`): family,
   observation, rule, execution, out-asset, tilt bounds, costs, tax bound, benchmark, splits, gates. Specs name
   **roles** (for example `index_fund.nifty50.direct`), never schemes; the role → scheme binding is owner config in the
   database (graft 6), so no named-security result can reach the public repo.
2. **Seed rules** (B05): S-E 10-month trend; S-D 12-1 absolute momentum **against a liquid-fund NAV hurdle**, not
   T-bills (graft 2); S-F; S-G. Each states its expected outcome in advance. No stock-level, factor-timing,
   valuation-band, category-rotation or "winner fund" signal exists (PLAN §6).
3. **Shadow mode first.** J4 evaluates every registered rule daily into `rule_evaluations` (including `PRE_REGISTERED`
   and `ABSTAIN` rules) and scores `outcomes` at the rule's horizon (graft 1). A shadow result is **never** shown as an
   action.
4. **Gates G1–G14, fail closed** (`backtest-methodology.md` §8). Thresholds, frozen before any run (U-06):
   DSR ≥ 0.95; HAC t ≥ 3.0; Holm-adjusted p < 0.05 (N ≤ 20) else SPA p < 0.05; PBO ≤ 0.20; ≥ 30 non-overlapping OOS
   periods and OOS length ≥ MinTRL; vault = last max(20 %, 3 years), evaluated once; ×0.5 decay haircut on any expected
   excess shown; G13 risk-budget compatibility; G14 drawdown non-inferiority.
5. **A gate that is not built returns `gate_not_implemented` and fails closed.** PBO/CSCV and Hansen SPA start that way
   (A18); X-05 builds them when a rule first reaches G9.
6. **Append-only trial log enforced in SQL:** triggers on `backtest_trials` abort UPDATE of params or snapshot hash and
   abort DELETE (graft 5). Every evaluated configuration is logged automatically; N is the family's row count.
7. **Walk-forward arguments `lag`, `purge`, `embargo`, `fill_rule` are mandatory with no default** (B05). MF fills use
   next-day NAV (U-16 default).
8. **Backtests run only in the local CLI.** Hosted mode imports evidence bundles that hold no raw NAVs (graft 16).
   Results are never written into the repo (public).
9. **A signal moves money only after ACCEPTED**, as a bounded tilt inside the risk layers (ADR-0015 L7): clamped to its
   tilt bounds and to `e_cap`; L0–L4 are re-evaluated after the tilt; a sale needs the lower 80 % bound of the
   after-tax edge to exceed the round-trip cost. G12 suspends a decaying signal.
10. **Status display** (C03): every row shows its failing gate, trial count, MinTRL next to the 80 %-power length,
    "earliest possible review: YYYY-MM" (= registration + max(30, MinTRL) months), the post-publication tag and the
    decay haircut. Wording follows ADR-0018.

## Consequences

- Every rule will read ABSTAIN for years, and most rules will never pass. That is the design refusing to make
  something up, not a defect (PLAN §1).
- Pre-2024 windows end in `ABSTAIN(tax_rules_missing)` until historical tax rows are added and reviewed (A11).
- Stocks ABSTAIN (U-10); ADR-0017.

## Not verified

- Whether `arch`'s SPA API is usable as-is (if used, pin and cross-check against an in-repo reference).
- The `t > 3` floor is a contested convention, not a settled standard (verify-backtest-method §3).
- ETF STT treatment (verify BT-4) — matters only for ETF-based rules.

## Evidence

`docs/research/wave1/research-backtest-method.md` §9–§13; `verify-backtest-method.md`; `design-risk-first.md` §6;
`design-judgement.md` §2.1 items 1, 2, 5, 6 and §2.2 items 12, 15, 16; PLAN §3 (U-06, U-16), rows A17, A18, B02, B05,
C03.
