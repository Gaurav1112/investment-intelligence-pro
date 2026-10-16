# Decisions register (owner decisions U-01 … U-17)

- **Purpose:** one place that records what the owner decided, when, and what the app does until a decision is made.
  The options, trade-offs and evidence for each id are in `docs/research/wave1/PLAN.md` §3; this file does not repeat
  the evidence.
- **Recorded:** 2026-10-16 (wave-2 start). Ids map to `design-judgement.md` §4 (J-n) where one exists.
- **How to read the state column:**
  - **DECIDED (date)** — the owner chose; the app implements that choice.
  - **DEFAULT** — not yet decided; the app uses the PLAN §3 "Default until decided" value. The owner can change it at
    any time; changing it is a new row in the change log below, never an edit of history.
- ⚑ marks decisions that block the first backtest run or the first hosted cron run.
- Not investment, tax or legal advice.

## Register

| Id | Decision | State | What the app does | Owning ADR / package |
|---|---|---|---|---|
| **U-01 ⚑** (J-1) | AMFI data in hosted (Vercel/Turso) mode | **DECIDED 2026-10-16**: local-first, and ask AMFI in parallel | Full auto-tracking of the core universe runs locally (`make run`). Hosted stores only rows for held and watched schemes. The permission letter is drafted for the owner to send (`docs/operations/amfi-permission-letter-draft.md`) | ADR-0017; B03, B06 |
| **U-02 ⚑** (J-2) | Loss limit per goal (₹) and recovery tolerance | DEFAULT | That goal gets no equity recommendation (ABSTAIN) until the owner sets it | ADR-0015; A12, B01, C02 |
| **U-03** (J-3) | Emergency fund: months and essential monthly expenses | DEFAULT | Banner; growth cards marked "after the emergency fund" | ADR-0015; A12, B01 |
| **U-04 ⚑** (J-4) | Target allocation per goal, band, review cadence, whether rebalancing may sell | DEFAULT | Cash-flow-only rebalancing | ADR-0015; A14 |
| **U-05** (J-5) | Tax context (regime, slab, surcharge, LTCG realised elsewhere) | DEFAULT | Conservative assumption (highest slab, exemption already used), labelled | ADR-0015; A15 |
| **U-06 ⚑** (J-6) | Evidence gate thresholds | **DECIDED 2026-10-16**: kept as written, frozen before any run | DSR ≥ 0.95, HAC t ≥ 3, PBO ≤ 0.20, MinTRL + ≥ 30 OOS periods, vault max(20 %, 3 y), ×0.5 decay haircut, G13/G14 | ADR-0016; A18, B05 |
| **U-07 ⚑** (J-7) | Core universe (U1) and size | DEFAULT | A ≤ 30-scheme proposal is shown; nothing is tracked until the owner confirms | ADR-0017; B06 |
| **U-08** (J-8) | Stress-table constants (niftyindices-derived) | DEFAULT | Values live in local config, not the public repo; the engine uses max(cited, AMFI-recomputed) | ADR-0015, ADR-0017; A11 |
| **U-09** (J-9) | Notification channel | DEFAULT | Off | ADR-0018; B04 |
| **U-10** (J-10) | Equity (stock and ETF) data route | **DECIDED 2026-10-16**: (a) none | No stock data; stocks ABSTAIN | ADR-0017 |
| **U-11** (J-11) | Wording in the private view | **DECIDED 2026-10-16**: neutral wording | "entry/exit condition met"; no BUY/SELL badges | ADR-0018; B04, C03 |
| **U-12** | Execute the Turso move to `bom1` | **DECIDED 2026-10-16**: now, via the runbook after a dry run on a copy; the owner runs the account steps | Runbook `docs/operations/turso-bom1-move.md`; until the owner completes it the database stays in `iad1` | ADR-0013; A01 |
| **U-13** | Factor/momentum sleeve (U3) | DEFAULT | Hidden | ADR-0015 |
| **U-14** | TER source | DEFAULT | Off | ADR-0015; A15 |
| **U-15** | Who sees the app; public showcase | DEFAULT | Only the owner | ADR-0018 |
| **U-16** | MF fill timing in backtests | DEFAULT | Next-day NAV | ADR-0016; B05 |
| **U-17** | Optional permission letters (NSE, NSE Indices, AMFI, IIMA authors) | DEFAULT (none sent) — note that U-01 asks for the AMFI letter in parallel; sending it is the owner's action | The AMFI draft exists; nothing is sent by the app or by any agent | ADR-0017 |

## Open owner actions

| Action | From | Status |
|---|---|---|
| Review and send the AMFI permission letter | U-01, U-17 | NOT DONE — draft ready; the owner fills the placeholders and sends it |
| Run the Turso `bom1` move (dry run on a copy first) | U-12 | NOT DONE — runbook ready; post-move latency NOT VERIFIED until measured |
| Accept or amend ADRs 0014–0018 | PLAN row A01 | NOT DONE — all five are *Proposed* |
| Shortest path to a useful app: answer U-02, U-03, U-05, U-07 | PLAN §3 | NOT DONE |

## Change log

| Date | Id | Change | Recorded by |
|---|---|---|---|
| 2026-10-16 | U-01 | Decided: local-first auto-tracking; hosted stores only held and watched schemes; AMFI letter drafted for the owner to send | Owner decision, recorded by package A01 |
| 2026-10-16 | U-06 | Decided: gates kept as written, frozen before any run | Owner decision, recorded by package A01 |
| 2026-10-16 | U-10 | Decided: (a) no stock data; stocks ABSTAIN | Owner decision, recorded by package A01 |
| 2026-10-16 | U-11 | Decided: neutral wording ("entry/exit condition met") | Owner decision, recorded by package A01 |
| 2026-10-16 | U-12 | Decided: move Turso to `bom1` now via the runbook, after a dry run on a copy; the owner runs the account steps | Owner decision, recorded by package A01 |
| 2026-10-16 | U-02…U-05, U-07…U-09, U-13…U-17 | Default until decided (PLAN §3) | Package A01 |
