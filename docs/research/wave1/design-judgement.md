# Judgement: three wave-1 signal-engine designs compared

- **Date written:** 2026-10-16. **Role:** judge over `design-evidence-first.md` (EF), `design-user-first.md` (UF) and
  `design-risk-first.md` (RF), all in this directory.
- **Method:** I read all three designs in full. I checked a few repo facts they depend on: `engine/candidates.py:843`
  `mf_tax_class_from_category`; `services/discovery.py:45` `MIN_HISTORY_POINTS = 60`; `docs/data/source-registry.md` line 91,
  the hosted-licence caveat; `docs/research/return-target-feasibility.md` §2.4 and Appendix A, the provenance of the
  drawdown table; and that both a root `app.py` and `backend/src/iip/api/app.py` exist. I also re-did each design's
  arithmetic.
- **External claims:** I did no new web research. Every external fact named here is carried from the wave-1 reports. Those
  reports hold the URL, the access date 2026-10-15 and the quote, and each design's source table names the report.
  Anything a wave-1 verifier weakened stays in its weakened form.
- **What this is not:** investment, tax or legal advice. No other repo file was changed and nothing was committed.

---

## 0. Verdict

**Winner: risk-first (RF), as the base design.** It gets grafts from user-first (UF) for the cost and setup experience, and
from evidence-first (EF) for the signal ledger and the backtest discipline.

| Criterion (1–10) | Evidence-first | User-first | **Risk-first** |
|---|---|---|---|
| Honesty and safety with real money | 9 | 8 | **10** |
| Evidence support | **9** | 8 | 8 |
| User value ("tells me what to do") | 6 | **9** | 8 |
| Feasibility under data and licence limits | 7 | **9** | 8 |
| Performance | 8 | **9** | **9** |
| Buildability by about 28 parallel agents | **8** | 7 | 8 |
| **Total (of 60)** | 47 | 50 | **51** |

**Why RF wins although UF is close.**
- The binding rules put real-money safety first. RF is the only design in which the user's own **rupee loss limit**
  mechanically caps equity per goal. The cap uses a cited worst-drawdown table with no diversification credit and includes
  the debt sleeve's stress.
- RF also forbids every drawdown-triggered sale.
- RF lets a validated signal sell only when the **lower 80 % bound** of its after-tax edge beats the tax and exit load the
  sale triggers.
- RF fails closed on any gate that has not been built yet (`gate_not_implemented`).

Those properties are the ones that stop the 20–25 % aspiration from quietly turning into an equity overweight. UF's loss
budget sizes equity from a single AMFI series whose start date is NOT VERIFIED and that may miss 2008, and it ignores debt
stress. That is weaker exactly where real money is at stake.

RF also has the most actionable everyday card, the **next-rupee planner**: "this month's SIP goes here". That is the
honest form of "when to buy" that the evidence supports.

**The honest headline for the user is the same in all three designs.** On day one there are no market-timing buy/sell
signals. Every pre-registered timing rule is expected to abstain, because the gates need roughly 11–25 years of
out-of-sample data. Single-stock buy/sell is BLOCKED or ABSTAIN. What the app *can* tell the user every day, with ₹
amounts, is:
- where new money goes;
- how much equity their loss limit allows;
- when they have drifted out of band;
- what costs or tax they can save, and when to act to save it.

None of the designs fabricates around this, and the judgement keeps it that way.

---

## 1. Design-by-design assessment

### 1.1 Evidence-first (EF): 47/60

**Strengths**
- **A clean P/D/S taxonomy**, enforced by a template linter: P is policy actions (no return claim), D is descriptive flags
  (never a verb), S is gated signals. This is the clearest statement of why a rebalance card is not a "signal" under the
  binding rule. ADR-0015 records it.
- **The signal ledger is the spine.** It contains:
  - `signal_rules` with a spec hash;
  - `backtest_trials`, append-only through SQL triggers (§5.1);
  - `backtest_runs` evidence bundles that hold **no raw market data**, so they are safe to store hosted;
  - `rule_evaluations`, a **daily forward record that includes SHADOW rules**;
  - `outcomes`, scored at each rule's horizon;
  - `action_decisions`.

  Shadow evaluation from day one is the only clean out-of-sample evidence the app will ever gather. EF says so and builds
  for it.
- **The best evidence hygiene:**
  - library defaults are banned (`lag`, `purge`, `embargo` and `fill_rule` become mandatory arguments);
  - regimes are defined on pre-vault data only;
  - post-publication out-of-sample months are tagged;
  - expected excess gets a ×0.5 decay haircut;
  - MinTRL is shown next to the 80 %-power length;
  - Regular-plan history before 2013 is used, and labelled, to lengthen tests;
  - **instrument roles instead of named schemes**, so no named-security result enters the public repo.
- **Power arithmetic is correct.** I re-checked t ≈ SR × √years: 3/√10.5 = 0.926, 3/√12 = 0.866, 3/√17 = 0.728.
- **It fixes a data gap the other two miss.** SIG-AM-01 uses a **liquid-fund NAV hurdle**, chosen in advance, because a
  historical 91-day T-bill series source is NOT VERIFIED; the RBI RSS keeps only about 10 items. UF's T-2 and RF's S-D both
  specify "vs T-bill" without a lawful historical series.
- **Regular→Direct "wait" optimisation.** It takes the argmin of the switch cost over the dates when FIFO lot blocks turn
  long-term or leave the exit-load window. Its fictional example adds up: 410 + about 1,333 forgone < 10,020.
- **The AMFI survivorship probe (WP16)** is a concrete experiment that decides whether any cross-sectional rule can ever pass
  G2.
- **The most parallel plan:** 19 Phase-A packages with no dependencies, explicit file-ownership rules, and router
  autodiscovery so later packages only add files. Cron entries ship disabled until WP10 is done.

**Weaknesses**
- **User value is the lowest.** The Today page is "mostly P cards and an honest list of S rules in ABSTAIN". There is no
  next-rupee planner and no loss-limit-to-equity link. The target allocation is a user decision entered with no derivation
  help, and setup asks for more inputs: D1–D13 plus D-H. The user said they do not want "a place where I enter things", so
  this matters.
- **Regular→Direct (P2) and the same-index cost gap (P9) need BER/TER.** That means a factsheet upload or the AMFI TER JSON,
  whose terms ban "reverse engineering", so P2 abstains for most users at first. UF's NAV-measured gap removes this input.
- **Least conservative on the AMFI hosted-licence tension.** D-H defaults to "ask AMFI; meanwhile minimised U0 ∪ U1" in
  hosted mode. UF and RF default to local-first until the user decides. Registry line 91 says to treat hosted use as
  "REQUIRES LICENCE / WRITTEN PERMISSION".
- **Telegram is offered as the v1 ping channel.** That conflicts with `research-regulation.md` §8.1.3. EF does flag the
  conflict and defaults to off.
- **An ownership gap in the build plan.** The tax-class false negative lives in `engine/candidates.py:843`
  (`mf_tax_class_from_category` takes only `category`; the name-pattern table needs the scheme name, so the signature and its
  caller in `services/analysis.py` change). WP13 does not own `candidates.py`, so an agent would edit a file no package owns.
- Seeding SIG-DM-01 and SIG-LX-01, both expected to fail, adds trials and build effort for no expected user value. This is
  harmless but optional.

### 1.2 User-first (UF): 50/60

**Strengths**
- **The best product framing.** It has an explicit success test: with only a CAS and six answers, the next morning shows
  ranked ₹ actions or a reasoned abstention. **Setup is six answers plus one CAS upload.**
- **"Needs from you" (§5.3)** lists each missing input with the **₹ upper bound it unlocks**, for example realised LTCG
  elsewhere unlocks ≤ ₹15,625 (= 1,25,000 × 12.5 %, correct). The user is asked only for what pays. This is the strongest
  answer to "not a place where I enter things".
- **The Regular→Direct cost gap is measured from AMFI NAVs of both plans** (§4.4):
  `g_12m = ln(NAV_dir ratio) − ln(NAV_reg ratio)`.
  - Same portfolio, so the gap is a pure cost transfer. No TER input and no grey-area TER JSON are needed.
  - It sidesteps verifier MF-3's caution about expense ratios as a predictor.
  - Option (d), "stop new SIP into Regular, start it in Direct", costs zero tax and is shown first.
- **The tax-timing details are the most complete:**
  - an LTCG harvest window (15 Feb–31 Mar, a parameter);
  - ELSS excluded from harvesting (a re-buy restarts the lock-in);
  - a "lot turns long-term within 45 days" wait modifier applied to *other* cards;
  - wash-sale treatment marked NOT VERIFIED and sent for CA review;
  - tax-loss harvesting kept off until set-off rows under the 2025 Act are verified.
- **Ranking without a composite score:** `(priority_class, deadline, impact ₹, card_id)`. Impacts with different bases are
  never added together, and "Nothing needs doing today" is a valid result.
- **An "I did this" action log** that is suppressed until the next CAS confirms the action, and re-raised if the CAS
  contradicts it.
- **The ActionCard has no `expected_return` field**, and a unit test enforces this. A structural guarantee beats a linter.
- **A "earliest possible review: YYYY-MM" line per abstaining signal**, computed as
  `registration + max(30, MinTRL) months`. This is honest and concrete.
- **The most conservative licence default** (D2): write to AMFI; run local-first until it answers.
- **Performance:** Today is read in one statement, and CI runs a statement-count test per endpoint so N+1 regressions fail.
- **DICGC and maturity cards** are P1 safety items.

**Weaknesses**
- **Loss budget → equity (§5.2):** `w_eq = min(1, L / |MDD_eq|)`.
  - MDD comes from the longest AMFI Nifty 50 index-fund series, whose start date is NOT VERIFIED and may exclude 2008.
    There is a banner, but the number can still **understate** the drawdown and allow too much equity.
  - It ignores debt-sleeve stress and treats all equity as Nifty 50, though midcap and smallcap funds fell about 73–76 %.
  - It takes a percentage, not ₹ per goal.

  This is the main real-money weakness.
- **T-2 uses a "12-month T-bill" hurdle** with no lawful historical series; see EF's fix.
- **Persistent-underperformer flag:** it requires "below 0 at each of the last 3 year-ends" on rolling 36-month windows.
  That is reasonable, but the flag is less tied to the investable alternative than EF's 3y/5y rule. It is a minor point.
- **Less parallel:** a serial scaffold (WP-01) owns all the hot files, followed by four phases. WP-07 edits `api/app.py`
  after WP-01. One migration file holds every table, which is safe but serial. Throughput for 28 parallel agents is lower.
- **A thinner evidence layer than EF:** no role bindings, no mandatory lag/purge arguments, no post-publication tag, and no
  survivorship probe. Dual momentum and the loser-exit rule are excluded outright, which is fine.

### 1.3 Risk-first (RF): 51/60

**Strengths**
- **A fixed risk hierarchy L0–L8.** A lower layer can never override a higher one:
  data → liquidity → goal-date safety → loss budget → limits → bands → tax/cost → signal tilts.

  Each layer returns PASS, ACTION, BREACH (suppresses lower layers for that goal) or ABSTAIN with the input it needs. This is
  the right shape for real money.
- **Loss budget in ₹ per goal → equity cap** (§5.3):
  `e_cap = (b − s_d)/(s_e − s_d)`, floor-rounded. All equity sleeves have correlation 1, debt stress is included, and the
  engine abstains when even 0 % equity would breach the budget.
  - I re-checked the fictional example: (0.25 − 0.03)/(0.67 − 0.03) = 0.34375 → 34 %.
  - Stress loss = 2,27,800 + 19,800 = 2,47,600 ≤ 2,50,000.
  - A recovery-time check (`T_g` against the episode's recovery years) is added as a historical fact.
- **Ex-ante sizing, never ex-post stopping.** There are no stop-losses, no volatility timing and no drawdown-triggered
  sales. In a crash, equity MV falls, so the stress loss falls and the cap does **not** force a sale at the bottom. A breach
  comes from equity *growth* and is answered with SIP redirection first.
- **The next-rupee planner** (§5.7) is pure allocation arithmetic and the most-used daily card. It answers "what do I buy
  with this month's money", which is the lawful, evidence-supported core of "when to buy".
- **Signal containment** (§6.3) adds two new gates:
  - G13: a signal must not breach the user's loss budget at maximum tilt;
  - G14: its drawdown must be no worse than buy-and-hold's.

  Tilts are bounded (S-E may only *reduce* equity, by at most 20 pp). A sale needs the lower 80 % bound of the edge to beat
  the triggered costs. Lower layers are re-run after a tilt.
- **Fail closed on unbuilt gates:** PBO/CSCV and SPA return `gate_not_implemented`. Deferring work therefore never lets a
  signal through, and wave A gets smaller.
- **Conservative defaults everywhere:**
  - the factor sleeve is hidden;
  - hybrid funds are stressed as 100 % equity;
  - the gold stress is NOT VERIFIED until recomputed from AMFI;
  - an unknown exit load means the engine abstains on lots younger than 365 days, with no assumed "1 % upper bound";
  - tax defaults to the highest slab with the exemption already used, labelled;
  - the stock sleeve uses s = 1.00 per position.
- **Performance:** a `series_grid` month-end table means the engine never reads raw daily history in the snapshot. Today
  never runs the engine on page load. Pings go out **only when the L1–L5 card set changes**, so quiet days stay quiet.
- **Build plan:** three waves of 20 + 6 + 2 packages, with files exclusive within each wave. I checked one apparent clash:
  A04's `app.py (root)` is the repo-root `app.py` and A06's is `backend/src/iip/api/app.py`, so there is no collision.
  Package A10 correctly owns `engine/candidates.py`. Package A13 also fixes the stale ₹1 lakh at
  `indian-instruments-and-tax.md` line 485.
- **Cutting the Kelly over-betting warning is honest.** With no leverage, f* ≈ 1.5 can never trigger the warning.

**Weaknesses (fixed by the grafts in §2)**
- **No daily shadow ledger for abstaining rules.** The outcome ledger (§6.4) logs only *emitted* cards. A rule stuck in
  ABSTAIN therefore builds no forward record, and the only path by which a signal could ever honestly graduate is missing.
  This is the most important gap.
- **S-D is "12-1 absolute momentum vs T-bill"**, the same unavailable-history problem as UF's T-2.
- **Regular→Direct needs BER**, a TER source (D8), so it abstains for most users at first.
- **Licence provenance of the stress table.** The −59.5/−67.0/−72.9/−75.6 % figures are **[C]** values. They were computed
  from niftyindices TRI series (`return-target-feasibility.md` §2.2, Appendix A, which calls a niftyindices endpoint).
  niftyindices terms say "No material from the Site may be copied … uploaded … without prior written permission" (verifier
  MOM-8). Whether a handful of derived drawdown statistics in a public rule table falls under that clause is
  **NOT VERIFIED**. RF does not state this tension explicitly.
- **There is no "Needs from you" list.** Abstentions name the missing input, but they are not ranked by the ₹ each input
  unlocks.
- **Only two frontend packages in wave C**, so the UI is the bottleneck at the end. There is no Rules/ledger page beyond the
  Signals gate panel.

---

## 2. Grafts into the winning design

The items are ordered by importance. Each names its source design.

### 2.1 Must graft (they fix real gaps in RF)

1. **The daily shadow forward ledger (from EF §5.1 and §5.3; also UF §6.4).**
   - Add `rule_evaluations` (one row per rule, version, data date and scope, including rules in `PRE_REGISTERED` or
     `ABSTAIN`) and `outcomes`, scored at each rule's horizon, to RF's migration 0004 (package A11).
   - Snapshot job J4 evaluates every registered S rule daily and never shows the result as an action.
   - Without this, no RF signal can ever pass G12 or accumulate post-registration evidence.
2. **Liquid-fund hurdle for absolute momentum (from EF SIG-AM-01).** Replace "vs T-bill" in RF's S-D with the liquid-fund
   NAV hurdle, frozen before any run. A historical T-bill series is NOT VERIFIED, because the RBI RSS keeps about 10 items.
3. **NAV-measured Regular→Direct gap (from UF §4.4)** plus the **argmin "wait until lots turn long-term" timing (from EF
   P2)** plus **option (d) "redirect the SIP to Direct first" (UF)**. Together these remove the TER/BER dependency (RF D8
   becomes mostly moot), and the card gives a concrete date.
4. **Conservative stress values with stated provenance.** For each equity class, use
   `s = max(cited [C] table value, drawdown recomputed in-app from AMFI index-fund NAVs)`. Show both, with the AMFI series
   start date. UF's AMFI-only approach can miss 2008; RF's table carries a niftyindices-derived provenance question.
   - Record that question as **NOT VERIFIED** in ADR-0017.
   - Add a user decision: keep the derived constants in the public rule table, or move the values into the user's DB or
     local config.
5. **Append-only trial log enforced in SQL (from EF §5.1):** triggers on `backtest_trials` that reject UPDATE of params or
   snapshot hash and reject DELETE. Also the mandatory `lag`/`purge`/`embargo`/`fill_rule` arguments (EF §6.2) in package
   B05's walk-forward code.
6. **Role bindings instead of named schemes in signal YAML (from EF §2).** Specs name roles such as
   `index_fund.nifty50.direct`. The role → AMFI code binding is user config in the DB. No named-security result can then
   reach the public repo.

### 2.2 Should graft (large gain in user value or evidence, low cost)

7. **"Needs from you", ranked by the ₹ each input unlocks (from UF §5.3)**, plus UF's **six-answer setup** merged with RF's
   "loss limit in ₹ per goal, shown with stress history before any return figure".
8. **Ranking key and empty state (from UF §7.2):** layer first (RF), then deadline, then ₹ impact, then card_id. Never add ₹
   across different bases. "Nothing needs doing today" is a first-class result.
9. **"I did this" action log with CAS confirmation (from UF §11)**, merged into RF's `decisions_log`.
10. **Tax-timing details (from UF §4.3):** ELSS excluded from harvesting; a Feb–Mar harvest window as a parameter; the
    "lot turns long-term within 45 days → wait" modifier applied across all cards that sell; wash-sale treatment NOT
    VERIFIED and sent for CA review; tax-loss harvesting off.
11. **ActionCard without an `expected_return` field, enforced by a unit test (from UF §1)**, plus **EF's template linter**
    that rejects forecast language in policy-card text.
12. **Power and status display (from EF §6.4, UF §6.4):** MinTRL next to the 80 %-power length; "earliest possible
    review: YYYY-MM"; the post-publication out-of-sample tag; and the ×0.5 decay haircut on any expected excess shown.
13. **The AMFI survivorship probe (EF WP16)** as a wave-A package. It also measures the earliest NAV-history date per
    core-universe role. That date is needed for the stress recompute in item 4 and for test lengths.
14. **Regular-plan history before 2013, labelled (from EF §4.3)**, so single-instrument tests are longer. TER cancels within
    the same plan.
15. **Pre-vault regime definitions (from EF §6.2)** for G10.
16. **Backtests in a local CLI only; hosted mode imports evidence bundles that hold no raw NAVs (from EF §6.3).** This keeps
    hosted AMFI exposure minimal.

### 2.3 Nice to graft (engineering)

17. **A statement-count CI test per endpoint (UF §10 #10)**, so N+1 regressions fail CI.
18. **Router autodiscovery of `api/routes_*.py` (EF §11 rule 3)**, so later packages add files instead of editing
    `routes.py`. Also EF's rule that `vercel.json` crons ship **disabled** (an empty secret returns 404) until the cron
    package lands.
19. **The run_key for J1 is derived after a cheap conditional fetch (EF §8.2)**, which settles RF's "fetch before claim"
    note.
20. **Milestones M1–M4 (UF §12)** as checkpoints the user sees: a fast, self-refreshing app; the daily digest; pings; shadow
    signals with honest status.
21. **Split RF's wave C into four packages:** Today, Goals and onboarding, Signals and Rules ledger (EF's `RuleDetail`), and
    Settings and notifications. Shrink wave A by deferring PBO/SPA, which fail closed. The total stays 28.

### 2.4 Do not graft

- **EF's Telegram as the v1 channel.** Keep RF's default: off, Web Push preferred, Telegram only as a content-free ping to
  the owner's own chat after the user decides.
- **EF's hosted-by-default AMFI posture.** Keep RF and UF: local-first auto-tracking until the user records decision D3/D-H.
- **UF's single-series `w_eq = L/|MDD|` sizing.** RF's ₹-per-goal, multi-class, debt-inclusive formula replaces it.
- **The Kelly over-betting warning** (EF, UF). RF is right that it can never fire without leverage.
- **SIG-DM-01 and SIG-LX-01 as day-one seeds** (EF). Register them later if the survivorship probe passes. Every seeded
  family adds build and multiple-testing cost with no expected user value.

---

## 3. Points the three designs share (no judgement needed; keep them)

- Permitted automated data is limited to AMFI (minimised), the MoSPI CPI API after the adapter fix, the RBI T-bill RSS with
  the `(100−P)/P × 365/days` self-check, and the user's own CAS and uploaded files.
- NSE, BSE, niftyindices automation, Yahoo and NSE-scraping libraries are BLOCKED. Kite is excluded. Upstox and Angel One
  are REQUIRES CONFIGURATION, NOT VERIFIED and local-only.
- Single-stock buy/sell is ABSTAIN or BLOCKED on G2/G3: no survivorship-free, point-in-time, dividend-adjusted data on any
  permitted route.
- Within a folio, lots are redeemed FIFO; the engine chooses only which scheme or folio to sell from.
- Five daily Vercel Hobby cron jobs sit on a narrow `/api/cron/{job}` route with a separate `CRON_SECRET`.
  - The claim SQL takes over stale `running` rows.
  - An outbox reaper never resends.
  - Snapshots are content-addressed, and ABSTAIN snapshots are stored.
  - Pings carry no content.
- The performance fixes come first: Turso moves to `bom1`, discovery is batched, the session lookup moves off the event
  loop, the UI is served from the CDN, endpoints return summaries and downsampled series, and scipy is lazy-loaded.
- 20–25 %/yr is a feasibility range, never an optimiser target. Five to eighteen per cent of rolling 10-year windows on the
  four broad TRIs reached 20 % and none reached 25 %, with about 2 independent windows (verifier EA-1 scoping).
- All three designs flag the same open items as NOT VERIFIED: the cron Host header and Deployment Protection, post-move
  Turso latency, ETF STT, pre-2024 tax rows, broker developer terms, and the AMFI "derivative works" reach.

---

## 4. Decisions that block the merged design (user only)

Merged from RF §15, EF §13 and UF §13. These must be fixed before the first backtest run.

| Id | Decision | Default until decided |
|---|---|---|
| J-1 | AMFI data in **hosted** mode: write to AMFI, accept the risk in writing, or local-only (registry line 91) | Local-first auto-tracking; hosted shows only what is already stored for holdings |
| J-2 | Loss limit `B_g` in ₹ and recovery tolerance `T_g` per goal; `h_safe` | That goal gets no equity recommendation (ABSTAIN) |
| J-3 | Emergency months and essential expenses | Banner; growth cards still shown, marked "after the emergency fund" |
| J-4 | Target allocation per goal (capped by `e_cap`), band (±5 pp), review cadence, whether rebalancing may sell | Cash-flow-only rebalancing |
| J-5 | Tax context (regime, slab, surcharge, LTCG realised elsewhere) or the labelled conservative assumption | Conservative assumption |
| J-6 | Gate thresholds (DSR ≥ 0.95, HAC t ≥ 3, PBO ≤ 0.20, MinTRL plus ≥ 30 out-of-sample periods, vault max(20 %, 3 y), decay ×0.5, G13 and G14), knowing they are near-unpassable | Keep as written |
| J-7 | Core universe list (≤ 30–40 schemes) and role bindings | Proposed by the deterministic rule; user confirms |
| J-8 | Whether the stress-table constants (niftyindices-derived) stay in the public repo or move to local config | Move to local config until clarified |
| J-9 | Notification channel | Off; Web Push when enabled |
| J-10 | Equity data route (none, Upstox/Angel One local, or ask NSE about manual bhavcopy) | None; stocks ABSTAIN |
| J-11 | Wording in the private view: "condition met" only, or opt-in BUY/SELL badges | Neutral wording |

---

## 5. One-paragraph brief for the build orchestrator

Build **risk-first** as the spine: the L0–L8 hierarchy, the ₹ loss-budget equity cap, the next-rupee planner, cash-flow-first
rebalancing, tax and cost cards, and fail-closed gates G1–G14 with PBO/SPA deferred. Add, before wave A starts:
- EF's **shadow forward ledger** (`rule_evaluations` + `outcomes`), the **append-only trial triggers** and the **role
  bindings**;
- EF's **liquid-fund momentum hurdle** in place of "vs T-bill";
- UF's **NAV-measured Regular→Direct gap**, with EF's argmin wait date;
- the **max(cited, AMFI-recomputed) stress rule**, with its licence question recorded as NOT VERIFIED;
- UF's **"Needs from you" ₹-unlock list**, the six-answer setup and the "I did this" CAS-confirmed log.

Keep everything local-first until the user settles J-1. Expect every timing signal to read ABSTAIN with an "earliest
possible review" date. That is the design working, not a defect.
