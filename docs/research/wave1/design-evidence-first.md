# Design: an evidence-first, abstain-by-default signal engine (wave 1 synthesis, "evidence-first")

- **Date:** 2026-10-15. **Author role:** design synthesis over the wave-1 audits, research reports and their verifier notes.
- **Scope:** data layer, universe, signal rules, evidence gates, signal ledger, plain-English actions, portfolio integration,
  automation and alerts, performance, manual-entry removal, regulatory wording, a phased build plan of 28 work packages, and
  what to cut.
- **Angle:** only signals whose verified research survives the skeptic pass may exist. The engine **abstains by default**.
  Every rule has a **ledger** that holds its pre-registration, its walk-forward evidence and its forward (post-registration)
  record.
- **Inputs read:** every `docs/research/wave1/*.md` file named in the task, including all `verify-*.md` notes. Every refuted
  or weakened claim listed in the task is respected below; §0.3 lists how each one changed the design.
- **External claims.** I made no new web fetches. Every external fact below is quoted from a wave-1 report that fetched it on
  2026-10-15. Each citation gives the original URL, the access date 2026-10-15, a short quote, and the wave-1 report it came
  from. Facts that the wave-1 verifiers could not confirm stay **NOT VERIFIED** here.
- **Status labels:** VERIFIED · VERIFIED-SECONDARY · NOT VERIFIED · REQUIRES CONFIGURATION · BLOCKED.
- **What this is not:** investment, tax or legal advice. This file is a design. No code or other repo file was changed.

---

## 0. Bottom line

### 0.1 The design in ten points

1. **Three output classes, kept strictly apart** (§3):
   - **P — policy actions.** These are the arithmetic consequences of rules the user chose: rebalance on drift,
     regular→direct break-even, LTCG harvesting, "lot turns long-term on date X", emergency-fund gap, duration vs horizon,
     maturity rollover and concentration. They make **no return or timing claim**, so they need no alpha backtest. Their
     gate is arithmetic correctness: oracle tests, a complete supervisor manifest and VERIFIED rule rows.
   - **D — descriptive flags and disclosed-risk candidates.** Examples: a persistent-underperformer *review* flag, and live
     statistics for factor index funds. They never use an action verb.
   - **S — evidence-gated signals.** These are timing or selection rules that imply an edge. They exist only after gates
     G1–G12 pass. Otherwise they show `ABSTAIN`, `NO_SIGNAL`, `BLOCKED`, `RETIRED` or `SUSPENDED`, each with the failing
     gate and what evidence would change the answer.
2. **What the evidence actually supports today.** It supports cost control, plan choice, allocation discipline, horizon
   matching and tax-aware execution (`research-evidence-mf.md` §1, §12; `research-evidence-allocation.md` §9). It does not
   support "buy this fund, it will outperform", category rotation, rate-cycle calls, volatility targeting, stop-losses,
   factor timing or stock picking. So on day one the Today page is mostly **P** cards and an honest list of **S** rules in
   `ABSTAIN` or `SHADOW`.
3. **Single-stock buy/sell is not offered.** Its status is BLOCKED for automated exchange data, and REQUIRES CONFIGURATION
   plus NOT VERIFIED for a broker API. Even the free broker route (Upstox, Angel One) cannot supply a survivorship-free,
   dividend-adjusted, point-in-time history, so G2 and G3 cannot pass. The engine says this plainly and does not pretend.
   Equity growth is pursued through index and equity **funds**, which AMFI covers.
4. **The only permitted automated data is official and terms-compatible:**
   - AMFI NAVAll, NAV history and scheme master (personal, non-commercial, minimised);
   - the MoSPI CPI API;
   - the RBI press-release RSS for T-bill cut-offs;
   - the user's own CAS and files the user supplies (factsheets, SIDs, holdings files).

   NSE, BSE, niftyindices, screener, Yahoo and every NSE-scraping library are BLOCKED for automation.
5. **The universe is capped and explicit** (§2):
   - U0 is the user's holdings and watchlist;
   - U1 is a "core index universe" of at most about 30 Direct-Growth index funds plus their Regular-plan twins for history
     (cap set by decision D3);
   - U2 is today's AMFI cross-section, latest NAV only, used for cost comparisons.

   Index funds stop being dropped as tax class `UNKNOWN`.
6. **Signal rules are pre-registered YAML specs** with frozen parameters, one variant per family, instrument *roles* instead
   of named schemes, and a hash. Five S rules are seeded (§4.3): a 10-month trend filter, 12-1 absolute momentum, a
   drawdown top-up, dual momentum and a loser-exit rule. **All five are expected to abstain.** The verifier's joint-power
   check shows that the stacked gates need an annualised excess Sharpe of about **0.93** on the roughly 10.5 years of
   Direct-plan NAVs left before the vault (my arithmetic: 3/√10.5).
7. **The signal ledger is the product's spine** (§5). It holds:
   - the registry (`signal_rules`);
   - the trial log (`backtest_trials`, append-only, every configuration ever run);
   - run manifests with data-snapshot hashes;
   - a **forward ledger** (`rule_evaluations`) that records every rule's daily state, including rules still in shadow mode;
   - `outcomes`, scored after each rule's horizon;
   - the user's own `action_decisions`.

   Shadow evaluation is the only clean out-of-sample evidence the app can ever gather, so it starts on day one.
8. **Automation:**
   - five daily Vercel cron jobs (Hobby plan: once a day each, ±59 min) behind a narrow `/api/cron/{job}` route with a
     separate `CRON_SECRET`;
   - idempotent claims keyed on the data date;
   - content-addressed snapshots, with an `ABSTAIN` result stored too;
   - a send-once outbox;
   - ping-only notifications to the owner's own channel.

   Backtests themselves run **locally** (CLI). Only their evidence bundles (statistics and hashes, no raw market data) go to
   the hosted database.
9. **Performance fixes come first.** They are the precondition for daily jobs inside 300 s:
   - batch the 1,791-statement discovery N+1;
   - move Turso to `bom1`;
   - take the session lookup off the event loop;
   - serve the UI from the CDN;
   - stop shipping full NAV histories to the browser;
   - lazy-load scipy.
10. **The plan:** 28 work packages in two phases with disjoint file ownership (§11). Phase A has 19 packages and no
    dependencies. Phase B has 9 packages built on A.

### 0.2 What the user should expect (honest framing)

- "Signals that grow my money" will at first mean **policy actions with a rupee effect**. Their value is real and has
  evidence: rupees saved on expense ratio, on tax and on exit loads, plus drift and risk kept inside the user's own loss
  budget. Market-beating timing calls will not be part of it.
- An S rule may graduate only after years of evidence. The likely result for most rules is a permanent, documented
  "No suitable candidate". **That is the design working.**
- 20–25 %/yr is an aspiration. The record is:
  - Nifty 50 TRI since 1995: 12.12 %/yr, SD 22.39 % (`research-evidence-allocation.md` §0, NSE factsheet 30-Sep-2026);
  - 5–18 % of rolling 10-year windows on the four broad Nifty TRIs reached 20 %, and none reached 25 %. This is scoped to
    TRI history since 1995/2005, about 2 independent 10-year windows; the verifier weakened EA-1's "never".

  The engine therefore treats the aim as a feasibility question (`docs/research/return-target-feasibility.md`), never as an
  optimiser target.

### 0.3 How each refuted or weakened wave-1 claim changed this design

| Claim | Verifier verdict | Effect on this design |
|---|---|---|
| R9 "licensed path only via Kite" | **Refuted**. Upstox and Angel One are free; Kite costs ₹500/month and breaks the no-paid-keys rule | Kite is cut. The broker route is Upstox/Angel One, **local only, REQUIRES CONFIGURATION, terms NOT VERIFIED** (§1.3) |
| NSE-2 "backtest = simulation" | Weakened to NOT VERIFIED (ambiguous) | No NSE-sourced data may feed a backtest (project policy, recorded as a conservative choice, not as a settled legal finding) |
| NSE-6 "manual entry with citation allowed" | Weakened | Manual bhavcopy import is **not** built. Decision D9 stays open |
| NSE-8 / R12 broker terms | Kite bans "build databases … permanent copies" and "virtual/mock trading apps" | Kite is cut. Upstox data is used only after its developer terms are read (WP gate, §1.3) |
| NSE-10 / EQ-6 / BT-7 corporate actions | Upstox and Kite adjust splits and bonuses only, not dividends; history is rescaled retroactively | Broker candles are price-return only. They are frozen per download and diffed on every re-fetch (§1.4). A TRI-consistent series cannot be built, so equity S rules fail G3 |
| EQ-7 local-only is compelled | Relabelled as a conservative **policy** choice | The design keeps broker data local, as policy |
| MOM-1/2/9 momentum magnitudes | IIMA WML is now about 10.7–11 %/yr; live excess t ≈ 0.64; NSE CAGRs internally inconsistent | S-C (momentum fund) is a **D** item with live-only statistics. No backtest CAGR is shown. NSE white-paper CAGRs are never quoted as inputs |
| MOM-5 dual momentum has no India evidence | Wrong for stock level; holds for multi-asset GEM | SIG-DM-01 is kept as a multi-asset test-only rule, expected to fail G5 |
| MOM-6 fund vs DIY tax magnitudes | Direction holds; magnitudes unreliable | Only the direction is used: fund wrappers defer tax under s.10(23D), now Income-tax Act 2025 Sch. VII (NOT VERIFIED primary) |
| MOM-8 niftyindices ToU | "personal, non-commercial use only", no copying or uploading without permission | User-imported TRI CSVs are **local mode only**, never uploaded to hosted Turso (decision D8) |
| MOM-10 / gate-4 exemption for S-C | Backfilled excess t ≈ 2.0 fails t > 3 | S-C is **not ranked by past excess** and carries no "better" wording. It appears only as a disclosed-risk candidate. That is the justification for not applying gate G9 |
| EVQ-1 per-stock prices BLOCKED by terms | Weakened: they are REQUIRES CONFIGURATION | The blocker for stock factor signals is recorded as **G2/G3 data** (survivorship, point-in-time), not terms |
| EVQ-6 low-vol "reliably" cuts risk | One ETF, one window | Low-vol is shown as a descriptive risk statistic only |
| EVQ-7 / EA-6 section numbers | Income-tax Act 2025 in force from 1-Apr-2026 | Rule rows cite the 2025 Act sections where the repo has them (s.196/198/76) and are otherwise NOT VERIFIED |
| EVQ-9 / EVQ-10 factor timing and quality evidence | The negative evidence was cherry-picked | Quality and low-vol stay **D** (descriptive), not "evidence against". No timing rule is seeded for them |
| MF-2 loser persistence "only" | Overstated | The R2 review flag stays **descriptive**. The exit rule SIG-LX-01 is gated on survivorship (G2) |
| MF-3 expense ratio predicts | Deb 2019 (India) finds the opposite, marginally | Cost is used **only where equivalence holds by construction**: same index tracked, or the same scheme's regular vs direct plan. It is never used as a cross-category predictor |
| MF-5 Morningstar investor gap | Not a clean timing measure | Not quoted as "you lose 2.5–5.8 % to timing" |
| EA-3 volatility management | US data, not Indian factors | Volatility targeting is ABSTAIN with no India evidence |
| EA-6 "lowest-tax lot first" | Infeasible under FIFO (CBDT Circular 768 / RTA practice) | The rebalance planner chooses **which scheme** to sell, never which lot. FIFO within a folio is enforced (§4.1 P1) |
| EA-7 "90 % from allocation" | Time-series figure; cross-sectional figure is 40 % | Not quoted |
| BT-3 pre-2024 tax gap | ₹1.25 lakh threshold (not ₹1 lakh) for 1-Apr to 22-Jul-2024; abstain rule for lots bought ≤ 31-Jan-2018 | WP17 adds historical rows from primary sources. Until then, windows with missing rows are `ABSTAIN (tax_rules_missing)` |
| BT-4 ETF STT | 0.1 % stock STT not shown to apply to ETFs | ETF cost rows are NOT VERIFIED. ETF rules use a ×1.5 upper bound flagged `costs_estimated` and cannot reach VERIFIED |
| BT-5 single stocks BLOCKED | BLOCKED for automation; NOT VERIFIED for the manual route | Recorded as such (§1.3) |
| BT-9 MinTRL is a floor | 80 % power needs about 298 months | The gate panel shows **both** MinTRL and the 80 %-power length |
| Verifier: joint gate power | The gates are near-unpassable | Stated plainly in the UI and in §6.4 |
| Verifier: regime split overlaps the vault | 2023+ ≈ vault | Regimes are redefined on pre-vault data only (§6.2) |
| AUTO-3 claim SQL | Cannot take over a stale `running` row; `sending` never reaped | Corrected claim SQL and reapers are specified in §8.2 |
| AUTO-7 equity BLOCKED | NSE wording misattributed; broker route exists | Fixed in §1.3 |
| R5 retail-algo registration | NOT VERIFIED | Order placement is cut entirely (§12) |
| R14 exports | The regulation report allows watermarked exports | Named-security S/D outputs are not exportable. P cards export with a watermark (§10) |
| R1/R2/R4/R7 references | Scope and default-lag errors | Library defaults (bt lag = 0, skfolio purge = 0) become mandatory parameters with no defaults (§6.1) |
| FD-3 / FD-4 fundamentals | One working paper, in-sample; pledge wording overstated | Fundamentals signals are cut. Quality-factor funds are D items, and abstain because their live history (13–25 months) is too short |

---

## 1. Data layer: what is actually permitted

### 1.1 Source table

| Source id | What | Access | Terms (quote, URL, accessed 2026-10-15) | Status in this design |
|---|---|---|---|---|
| `amfi.navall` | Latest NAV, about 14.4k rows | HTTPS, no auth | "for your personal and non-commercial use only … You shall not store electronically any significant portion of any part of the Site." https://www.amfiindia.com/terms-of-use (via `docs/data/source-registry.md` line 88) | **LIVE**, cron J1. Store full history only for U0 ∪ U1 (§2) |
| `amfi.navhistory` | Per fund house, date range | HTTPS | Same AMFI terms | **LIVE**, cron J3 gap fill for U0 ∪ U1 only. Requests ≤ 90 days per call (registry §2.2) |
| `amfi.schememaster` | Category, launch and closure dates, ISINs | HTTPS, 4.1 MB | Same | **LIVE**, weekly. Its `Closure Date` column feeds `scheme_status` (rule S3) |
| `amfi.ter` (undocumented JSON) | TER/BER | HTTPS | AMFI terms ban "reverse engineering" (`audit-automation.md` §3.3) | **Off by default.** User decision D5 |
| `mospi.cpi` | CPI index and YoY, base 2012 and 2024 | Public API, no login | Probed OK (`audit-automation.md` §3.1) | **LIVE** after the adapter fix (WP11) |
| `rbi.pr.tbill` | 91/182/364-day cut-off yields | RBI Press Releases RSS | RBI offers RSS "for automatic updates" (`audit-automation.md` §3.2); deep links need permission per the RBI disclaimer (§2.3) | **LIVE** (WP12). The feed keeps 10 items, so a missed Wednesday is filled from the release page. Citations are rendered as plain text, not deep links |
| `user.cas` | The user's own CAMS/KFin CAS | Upload | User-owned data | **LIVE**. Fix the Regular-plan rejection (known-limitations CAS gap 1) |
| `user.factsheet` / `user.portfolio` | Duration, YTM, riskometer, holdings | User-supplied file | AMC terms forbid crawling (`audit-automation.md` §3.4) | Deterministic parse of files the user hands over (WP15) |
| `user.sid_exit_load` | Exit-load text | User-supplied SID text or CAS-observed loads | — | Strict-grammar parser that **abstains** on anything outside the grammar (WP14) |
| `user.index_tri_csv` | Index TRI history | Manual download by the user | niftyindices: "personal, non-commercial use only"; "No material from the Site may be copied, modified, reproduced, republished, uploaded, transmitted … without prior written permission" (`verify-evidence-momentum.md` MOM-8; https://www.niftyindices.com/terms-of-use) | **Local mode only, off by default**, decision D8. Never uploaded to hosted Turso |
| `user.iima_factors` | IIM-A factor CSV | Manual | Citation requested, no licence (`research-evidence-value-quality.md`) | Optional D-panel, local only. Pin release `2025-12` and assert the HML sign on import |
| `broker.upstox` / `broker.angel` | Daily candles | Free API on the user's own account | "All trading + data APIs are free of cost." https://upstox.com/trading-api. Developer storage and backtesting terms **NOT VERIFIED** (`research-equity-data-alt.md`) | **REQUIRES CONFIGURATION + NOT VERIFIED.** Local only. Not built until WP-X1 reads the developer terms (§12) |
| `nse.*`, `bse.*`, `niftyindices` automation, jugaad/nsepython/nselib/nsetools/eod2, yfinance | — | — | NSE: "User is prohibited to conduct any systematic or automated data collection activities (including scraping…)" (https://www.nseindia.com/, ToU updated 29/10/2025, via `research-equity-data-nse.md`); Yahoo bans automated collection "for any purpose" (`research-equity-data-alt.md`) | **BLOCKED** |
| `ccil`, `fbil`, CRISIL ratings, bank FD sites | — | — | CCIL "discouraged from extracting"; SBI forbids crawling (`audit-automation.md`) | **BLOCKED** for automation. FD rates come from a user paste parser |

### 1.2 Unresolved licence tension that the user must own

`docs/data/source-registry.md` line 91 says: "Treat any hosted or commercial deployment as REQUIRES LICENCE / WRITTEN
PERMISSION". The hosted Vercel/Turso app already stores AMFI history for tracked schemes, and this design adds persisted
snapshots on top. **This design does not resolve that.** It reduces the exposure:

- history is kept only for U0 ∪ U1, at most about 30 index schemes plus holdings;
- snapshots carry derived statistics, not NAV files;
- backtests and any user-imported TRI or factor data stay local.

It then records decision **D-H**: (a) email AMFI for written permission for a single-user hosted copy; (b) accept the residual
risk, with the date recorded; or (c) run signals in local mode only. The AMFI clause on "derivative works" may also reach a
persisted backtest; that is NOT VERIFIED.

### 1.3 Equity data, stated precisely

| Route | Status | Why |
|---|---|---|
| NSE/BSE site automation | **BLOCKED** | NSE ToU automation ban (verbatim, VERIFIED); BSE "reproduction, redistribution or transmission … strictly prohibited" |
| Manual bhavcopy import | **NOT VERIFIED** (ambiguous) | The NSE ToU "Unless the information or Content is available for download, not to aggregate, copy or duplicate" exception sits beside "stored … in an electronic retrieval system" and "simulation activities" (`verify-equity-data-alt.md`). **Not built.** Decision D9 |
| Upstox / Angel One API, local | **REQUIRES CONFIGURATION, NOT VERIFIED** | Free. Upstox candles adjust "only for bonuses and splits" (Upstox staff, https://community.upstox.com/t/3548, via `verify-equity-data-alt.md`). No delisted equities (the Expired Instruments endpoints are derivatives only) |
| Kite Connect | **Cut** | ₹500/month breaks the no-paid-keys rule. Its terms ban "build databases, or otherwise create permanent copies" (https://kite.trade/terms/, via `verify-equity-data-nse.md`) |

**Consequence for signals.** For single stocks, G2 (survivorship) and G3 (total-return consistency) cannot pass on any
permitted route, so stock S rules are `BLOCKED (no_survivorship_free_pit_data)`. Index ETFs on broker candles could pass G2,
because they are single instruments. They would still fail TRI consistency for dividends, and ETF STT is NOT VERIFIED. Even
after the broker terms are read, ETF rules can reach at most NOT VERIFIED evidence. **Index funds on AMFI NAVs are the
first-class route**, because growth-option NAV is already total return net of expenses (`research-backtest-method.md` §3.3).

### 1.4 Data contracts (applies to every input)

- **Bitemporal facts:** `valid_time` and `known_time` (`research-backtest-method.md` §3.1). MF NAV for day d has
  `known_time` = d + 1 business day, the repo's conservative rule.
- **Snapshot hashing:** every backtest and every daily snapshot records `data_snapshot_hash` =
  sha256 over the canonical rows read.
- **Freeze and diff:** broker or user-imported series are stored as immutable download snapshots. A re-download that changes
  any past value creates a new snapshot and a `RESTATEMENT` event. A trial can be reproduced only against its own snapshot.
  This closes the retroactive-rescaling hazard (BT-7).
- **Provenance:** reuse the existing `observations` provenance contract (`source-registry.md` §3).
- **No fabricated values:** a missing input is a supervisor gap, never a default. The only exception is a **named,
  researched, labelled upper bound** that the user has approved (for example a conservative exit load, decision D7). Such a
  value always carries the flag `ASSUMED_UPPER_BOUND` and blocks VERIFIED status.

---

## 2. Universe

| Id | Contents | History kept | Used for |
|---|---|---|---|
| **U0** | User holdings (CAS), watchlist, goal-linked schemes, FDs, T-bills, bonds | Full, for MF schemes | P and D items, forward ledger |
| **U1** | **Core index universe**: one Direct-Growth scheme per index family, plus the same scheme's Regular-Growth plan (longest investable series). Families: Nifty 50; Nifty Next 50; Nifty 500 or Total Market; Midcap 150; Smallcap 250; Nifty200 Momentum 30; Midcap150 Momentum 50; Nifty200 Quality 30; Nifty100 Low Vol 30; a gold ETF FoF; one overnight and one liquid fund; one gilt/constant-maturity index fund. **Cap: ≤ 30 schemes** (decision D3) | Full | S rules (roles), D items, comparators |
| **U2** | AMFI cross-section of in-scope schemes (about 1,779) | **Latest NAV only** | Cost comparator (TER gap within the same index), tax class, category |

- **Role binding.** S rule specs name **roles** (`role: index_fund.nifty50.direct`), not schemes. The binding role → AMFI
  code is user configuration stored in the DB. It is chosen by a deterministic rule (longest history, then lowest TER, then
  largest AUM if known) and confirmed by the user. Named-security results therefore never enter the public repo
  (`research-regulation.md` §8.1.7).
- **Tax class fix (WP13).**
  - "Index Funds - Equity Funds" → equity-oriented.
  - A cited name-pattern table maps "Other Scheme - Index Funds" (Nifty/Sensex/Midcap/Smallcap → equity; Gilt, SDL, G-Sec,
    Bharat Bond, CRISIL IBX → debt) and flags `TAX_CLASS_INFERRED_FROM_NAME`.
  - Everything else stays UNKNOWN.
  - Measurable target: the UNKNOWN count falls from 812 (`audit-journey.md` §2.2).
- **History gate.** Replace the hard `MIN_HISTORY_POINTS = 60` skip (`services/discovery.py:45`) with a **reasoned
  exclusion** that names the auto-tracking fix. U1 schemes accumulate history on their own through cron J3.
- **Survivorship (G2).** Any cross-sectional universe (a category, or "funds like mine") is `ABSTAIN (survivorship_unverified)`
  until WP16's probe shows that AMFI NAV history returns closed or merged schemes (`tp=2`/`tp=3` and the scheme-master
  `Closure Date`). This is rule S1 in `validation-methodology.md` §3.4. Single-instrument rules pass G2 (rule S2).

---

## 3. Output classes and states

### 3.1 Classes

| Class | Definition | Needs an alpha backtest? | What gates it | Wording |
|---|---|---|---|---|
| **P** policy action | A deterministic consequence of the user's **own** configured rule and data (allocation band, emergency months, tax facts). No claim about future returns | No. It predicts nothing. The *policy itself* cites evidence (Vanguard rebalancing; cost arithmetic) | Supervisor manifest complete; rule rows VERIFIED; oracle tests on the arithmetic; FIFO and tax per lot | "Your rule R-REB@1 triggered …" plus options with ₹ effects |
| **D** descriptive | A statistic or flag with no action | No | Data provenance (G1), minimum history, survivorship banner where relevant | "Review flag", "risk characteristics", never a verb |
| **S** evidence-gated signal | A timing or selection rule whose value depends on future returns | **Yes**: G1–G12 | §6 | "Entry/exit condition met (rule SIG-…@v)" next to the evidence card. BUY/SELL badges only if D1 opts in |

**Why P is not a "signal".** The binding rule covers signals, meaning claims of edge. A rebalance card says "you set 60 %
equity ±5 pp; you are at 68 %; here is what it costs in tax to fix". It does not say "equity will fall". This matches
`research-evidence-allocation.md` §9 ("ALLOWED (policy analytics, not a signal)") and `research-evidence-mf.md` §12. ADR-0015
(WP01) must record this distinction so that a P card can never smuggle in a forecast. The template linter rejects any P card
text that matches `forecast_certainty` or uses future-return language.

### 3.2 States (one enum, used everywhere)

`SIGNAL_VERIFIED` · `SIGNAL_EVIDENCE_INCOMPLETE` (all gates pass but an input or rule row is VERIFIED-SECONDARY) ·
`NO_SIGNAL(<reason>)` · `ABSTAIN(<reason>)` · `SHADOW` (registered, being evaluated forward, never shown as an action) ·
`RETIRED(vault_fail)` · `SUSPENDED(decay)` · `BLOCKED(<reason>)` · `REQUIRES_CONFIGURATION(<field>)`.

Reason codes extend `validation-methodology.md` §8: `data_unverified`, `survivorship_unverified`,
`unadjusted_prices_suspected`, `leakage`, `insufficient_evidence(has,needs_minTRL,needs_80pct_power)`,
`edge_not_positive_after_costs_tax`, `tax_rules_missing`, `costs_estimated`, `fragile_to_costs`, `trials_unknown`,
`not_significant_after_multiple_testing`, `not_robust`, `illiquid`, `context_missing(<field>)`,
`no_survivorship_free_pit_data`, `licence_blocked`.

---

## 4. Rules with exact formulas (parameters fixed in advance)

Every number below is either a user decision (marked **[D-n]**), a cited constant, or the output of a formula. All money is
`Decimal` under `engine_context` (ADR-0002). Engine functions take `as_of`, the data and the rule tables as arguments; they
read no clock, do no IO and use no randomness, except a seed passed in for bootstraps. Every output number carries a
`formula_id` and its input fact ids.

### 4.1 Class P: policy actions

**P1 Rebalance (R-REB@1).**
- Weights: `w_i = MV_i / Σ_j MV_j` per asset class *i*, within a goal. MV comes from NAV(as_of) × units, using FIFO lots
  from `fifo_positions`.
- Trigger, on a review date only: `|w_i − t_i| ≥ b`, with target `t` and band `b` = 5 pp by default (Vanguard: "annual or
  semiannual monitoring, with rebalancing at 5% thresholds", https://www.aaii.com/journal/article/best-practices-for-portfolio-rebalancing,
  via `research-evidence-mf.md` §9.2). The review cadence defaults to semi-annual. Both are **[D-4]**.
- Option A, cash flow only:
  - `gap_₹ = (t_i − w_i) × Σ MV` for the most underweight class;
  - `months_to_close = ceil(gap_₹ / monthly_new_money)`;
  - cost is ₹0 tax, and stamp duty is 0.005 % of each purchase.
- Option B, sale (only if the user allows taxable rebalancing, **[D-4]**):
  - choose **which schemes** to redeem from the overweight class, ordered by after-tax cost per rupee freed;
  - within a scheme, lots are consumed **FIFO** (CBDT Circular 768 / RTA practice; lots cannot be picked, EA-6);
  - cost per scheme = exit load on the FIFO lots consumed + tax via `tax.compute_tax` (STCG 20 %; LTCG 12.5 % above the
    remaining exemption; slab for specified debt MFs) + STT 0.001 % on equity-oriented redemption + stamp 0.005 % on
    switch-in;
  - out-of-market days on a switch = T+3 working days (T+5 for schemes with ≥ 80 % overseas assets, SEBI circular 2022/161,
    VERIFIED-SECONDARY via `verify-backtest-method.md`).
- The card shows: drift before and after, rupees per option, tax per option, and "Option A closes the gap in N months".
- Abstain if any of these is missing: target allocation, holdings fresh within the freshness SLA, user slab, exemption
  used this FY, or the exit-load schedule of a scheme being sold.

**P2 Regular → Direct (R-R2D@1).** From `research-evidence-mf.md` §4.2, extended with a "wait" option:
- `S = MV × (BER_reg − BER_dir)` per year.
- `C_now = exit_load(FIFO lots) + tax(FIFO lots, today) + 0.005 % × MV`.
- For each future date d at which a FIFO block turns long-term or leaves its exit-load window:
  `C_d = cost at d + S × (d − today)/365`. This is the saving forgone by waiting.
- The recommended timing is `argmin_d C_d` over `d ∈ {today} ∪ {lot-transition dates within 13 months}`. The card shows
  `break-even years = C_now / S`.
- Fresh money defaults to Direct. This is a cost fact, not a forecast.
- Abstain if BER for either plan is missing (it needs a factsheet file or D5) or the exit-load schedule is missing. A
  switch's exit-load treatment is AMC-specific (VERIFIED-SECONDARY), so it is REQUIRES CONFIGURATION per scheme.

**P3 LTCG harvest (R-LTH@1).**
- `E_rem = 1,25,000 − LTCG_realised_FY − LTCG_planned_FY`, where the user supplies gains realised outside the app **[D-10]**.
- Walk FIFO lots that are long-term, have zero exit load, and belong to equity-oriented schemes. Accumulate gain `g` until
  `Σg ≤ E_rem`. The units to redeem and re-buy are those lots.
- Benefit, shown as a **deferred** tax effect: `Σg × 12.5 % × (1 + 4 % cess)`.
- Costs: STT 0.001 % on the sell, stamp 0.005 % on the buy, and one day out of the market (redemption, then fresh purchase),
  shown as a risk and not priced.
- Abstain if: residency or tax regime is not configured; a lot was bought on or before 31-Jan-2018 (the repo abstains on
  grandfathering, BT-3); or the FY mixes rate regimes.

**P4 Lot calendar (R-LTC@1).** For each FIFO lot, the date it becomes long-term is computed by the existing tax engine's
holding-period rule. It is not hand-coded here. The card reads "₹X of gain turns long-term on DD-MMM; selling before then
costs about ₹Y more tax", where `Y = gain × (20 % − 12.5 %) × 1.04` if the exemption is used, else the full STCG.

**P5 Emergency-fund gate (R-EF@1).**
- `need = months [D-2] × essential_expenses [D-2]`.
- `have = Σ` MV of liquid/overnight funds and sweep or FD balances mapped to the EF goal.
- If `have < need`: "gap ₹(need − have)". Candidates come from the existing Discovery for objective C.
- A per-bank DICGC note: deposits insured up to ₹5 lakh per bank (DICGC primary, via `research-evidence-allocation.md` §8;
  per capacity, NBFC deposits excluded).
- This gate is evaluated **before** any growth card: if the EF is short, growth P cards are shown as "after EF".

**P6 Duration vs horizon (R-DUR@1).** Flag when Macaulay duration (from a factsheet the user supplied) exceeds the goal's
remaining years. Show `ΔNAV ≈ −ModD × Δy × MV` for Δy = ±100 bp and ±200 bp (ICI: "a 1 percentage point increase in
interest rates alone would be expected to lower the overall net asset value of the fund by 4 percent" for duration 4,
https://www.ici.org/viewpoints/view_18_bond_duration, via `research-evidence-mf.md` §8.1). Use the 2026 SEBI category
names (`rules/mf_categories.yaml`, MF-CAT-2026). No rate-direction call.

**P7 Maturity rollover (R-MAT@1).** An FD, T-bill or bond maturing within N days **[D-11]** (default 30) runs Discovery for
that amount and the goal's remaining horizon. This exists today; the change is to schedule it.

**P8 Concentration (R-CON@1).** `HHI = Σ w_k²` over schemes and over AMCs. Flag above the user's limit **[D-11]**. Show which
new-money allocation brings HHI under the limit, with no sale.

**P9 Same-index cost gap (R-CST@1).** Within U2, for schemes that track **the same named index** (name-pattern match
confirmed by the user): `gap_bp = (BER_held − BER_min) × 10,000`. Flag if `gap_bp ≥ 15` **[D-11]**. Equivalence holds by
construction, which avoids the MF-3 India contradiction about expense ratios as a predictor. For active funds, show only
the index alternative, with the SPIVA India base rate already VERIFIED in `return-target-feasibility.md`. Never call it
"better".

### 4.2 Class D: descriptive

**D1 Persistent-underperformer review flag (F-UND@1).** The benchmark is the U1 **index fund that tracks the scheme's stated
benchmark**, using AMFI NAVs. Benchmark TRI files are not used, because niftyindices automation is BLOCKED and the index fund
is the investable alternative.
- `x3 = CAGR_fund(3y) − CAGR_idx(3y)` and `x5 = CAGR_fund(5y) − CAGR_idx(5y)`, both Direct-Growth, both ending at the
  same NAV date.
- The flag shows if `x3 < 0` **and** `x5 < 0`.
- Text: "Trailed the index-fund alternative over 3 and 5 years. Review flag only; no backtest supports an exit rule."
- If either series is shorter than 5 years, the state is `ABSTAIN(insufficient_history)`.

**D2 Factor and strategy index funds (F-FAC@1; covers S-C momentum, quality, low-vol).**
- Show live, post-launch statistics only, from AMFI NAVs: CAGR, volatility, max drawdown, worst rolling 12-month return
  relative to the Nifty 50 index fund **and** to the parent-universe index fund (this fixes the EVQ benchmark mismatch).
- Mandatory banners: back-calculated history before launch (Nifty200 Momentum 30 launched 25-Aug-2020; Midcap150 Momentum 50
  launched 16-Aug-2022, `verify-evidence-allocation.md`), the historical max drawdown range (−68 % to −73 %), a decay
  statement, and "tax: STCG if sold within 12 months".
- `ABSTAIN(insufficient_history)` if live NAV history is under 36 months. Quality-30 funds (13–25 months live) abstain today.
- Never ranked by excess return.

**D3 Feasibility vs the 20–25 % aim (F-FEAS).** Reuse `engine/feasibility.py`, scoped by series and start date with n_eff
shown, per EA-1.

### 4.3 Class S: seeded, pre-registered rules (all start in SHADOW)

Common rules:
- Monthly decision at the last business day m. The decision uses NAVs with `known_time ≤ τ`.
- Orders go in on business day m+1, after NAV(m) is known. The fill is at NAV(m+2), the next-day-NAV conservative rule
  (`research-backtest-method.md` §4.1), and switches carry the T+3 cash gap.
- Benchmark: buy-and-hold of the same role, taxed identically and **liquidated at the end**.
- Tax: lot-level FIFO; conservative bound (exemption already used; highest slab).
- One variant per family. Any change is a new trial.

| Rule id | Formula (frozen) | Out asset | Benchmark | Expected verdict and why |
|---|---|---|---|---|
| **SIG-TF-01** trend filter | `S_m = 1 if NAV_m > (1/10) Σ_{k=0..9} NAV_{m−k} else 0` on month-end NAV of role `index_fund.nifty50` | role `liquid_fund` | B&H `index_fund.nifty50` | ABSTAIN or NO_SIGNAL: G5/G9 power (§6.4). Global OOS evidence is contested; India MA profits vanish after costs (Mitra 2011, via `research-evidence-momentum.md` §3.3) |
| **SIG-AM-01** 12-1 absolute momentum | `S_m = 1 if NAV_{m−1}/NAV_{m−12} − 1 > L_{m−1}/L_{m−12} − 1 else 0`, where L is the liquid-fund NAV. The hurdle is chosen **before** testing because a historical T-bill series source is NOT VERIFIED | liquid | same | Expected to match a sample-mean strategy (Huang et al. 2020, via momentum §6) |
| **SIG-DD-01** drawdown top-up (cash-flow only, no sales) | Reserve R parked in liquid. If `NAV_m ≤ 0.80 × max(NAV_{m−11..m})`, move min(R, 1 × monthly SIP) to the index fund | — | the same cash deployed on the fixed SIP schedule | No tax drag. Few trigger events (2020 and possibly 2008 on Regular history), so G5 fails |
| **SIG-DM-01** dual momentum (multi-asset) | Pick the highest 12-month return among roles {`index_fund.nifty500`, `gold_fof`, `gilt_index`}. Hold it only if its return beats liquid's; else hold liquid | liquid | static equal-weight mix, rebalanced annually | About 19 annual decisions since gold ETF inception in 2007, so G5 fails (`research-evidence-momentum.md` S-F) |
| **SIG-LX-01** loser exit | If D1 holds and the fund is in the bottom quartile of its category on 3-year return, switch to the index-fund alternative | index fund | hold | `ABSTAIN(survivorship_unverified)` until WP16. A category cross-section is needed |
| SIG-EQ-* | Any single-stock rule | — | — | `BLOCKED(no_survivorship_free_pit_data)` |
| SIG-VAL-* | P/E bands | — | — | `BLOCKED(licence_blocked)`: niftyindices P/E |

**History.**
- SIG-TF/AM/DD use the **Regular-Growth plan** of the same index fund before the Direct plan exists (Direct plans date from
  1-Jan-2013, `research-evidence-mf.md` §4.1, VERIFIED-SECONDARY). That series is real, investable history; TER cancels
  between strategy and benchmark within the same plan.
- The earliest AMFI NAV-history date for these schemes is **NOT VERIFIED**. WP16 probes it.
- Using Regular-plan data changes nothing in the rule. It only lengthens the test, and the label `history: regular_plan_pre_2013`
  is shown.

**Why these and not others.** They are the only rules with (a) a published global evidence base, (b) data the app may
lawfully use (AMFI only), and (c) a single-instrument universe that passes G2 (except LX, which is gated). The rules cut in
§12 fail one of these three.

---

## 5. The signal ledger

### 5.1 Tables (new migrations owned by WP09)

```sql
-- Registry: one row per (rule_id, version); the spec body is the committed YAML, stored with its hash.
CREATE TABLE signal_rules (
  rule_id TEXT NOT NULL, version INTEGER NOT NULL, class TEXT NOT NULL CHECK (class IN ('P','D','S')),
  family TEXT NOT NULL, spec_yaml TEXT NOT NULL, spec_hash TEXT NOT NULL,
  registered_at TEXT NOT NULL,                       -- service-layer stamp; pre-registration evidence
  state TEXT NOT NULL,                               -- §3.2 enum
  state_reason TEXT, PRIMARY KEY (rule_id, version));

-- Role binding (user config; never in the public repo).
CREATE TABLE rule_role_bindings (role TEXT PRIMARY KEY, instrument_id TEXT NOT NULL, bound_at TEXT NOT NULL,
  rule_of_choice TEXT NOT NULL);                     -- e.g. 'longest_history>lowest_ter'

-- Trial log: append-only; every configuration ever evaluated, including abandoned ones (G8).
CREATE TABLE backtest_trials (
  trial_id TEXT PRIMARY KEY, rule_id TEXT NOT NULL, version INTEGER NOT NULL, family TEXT NOT NULL,
  params_json TEXT NOT NULL, universe_id TEXT NOT NULL, horizon TEXT NOT NULL, benchmark_id TEXT NOT NULL,
  data_snapshot_hash TEXT NOT NULL, code_version TEXT NOT NULL, rules_version TEXT NOT NULL, seed TEXT NOT NULL,
  oos_edge_hash TEXT, n_periods INTEGER, sr_hat TEXT, skew TEXT, kurt TEXT,
  status TEXT NOT NULL CHECK (status IN ('active','retired','vaulted_pass','vaulted_fail')),
  created_at TEXT NOT NULL);
CREATE TRIGGER backtest_trials_no_update BEFORE UPDATE OF params_json, data_snapshot_hash ON backtest_trials
  BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER backtest_trials_no_delete BEFORE DELETE ON backtest_trials BEGIN SELECT RAISE(ABORT,'append-only'); END;

-- Evidence bundle per run: gate panel + statistics; NO raw market data (hosted-safe).
CREATE TABLE backtest_runs (
  run_id TEXT PRIMARY KEY, trial_id TEXT NOT NULL, manifest_json TEXT NOT NULL, output_hash TEXT NOT NULL,
  gates_json TEXT NOT NULL, stats_json TEXT NOT NULL, verdict TEXT NOT NULL, vault_opened INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL);

-- Forward ledger: one row per rule per data date, written by cron J4 (P, D and S incl. SHADOW).
CREATE TABLE rule_evaluations (
  rule_id TEXT NOT NULL, version INTEGER NOT NULL, as_of_date TEXT NOT NULL, scope_id TEXT NOT NULL,  -- goal or role
  state TEXT NOT NULL, condition_met INTEGER, payload_json TEXT NOT NULL, input_hash TEXT NOT NULL,
  snapshot_id TEXT NOT NULL, PRIMARY KEY (rule_id, version, as_of_date, scope_id));

-- Scored later from realised NAVs (paper outcome of the rule's implied position vs its benchmark, after cost/tax model).
CREATE TABLE outcomes (
  rule_id TEXT NOT NULL, version INTEGER NOT NULL, as_of_date TEXT NOT NULL, scope_id TEXT NOT NULL,
  horizon_end TEXT NOT NULL, edge_after_cost_tax TEXT, status TEXT NOT NULL,   -- 'scored'|'pending'|'unscorable(<reason>)'
  PRIMARY KEY (rule_id, version, as_of_date, scope_id));

-- The user's own decisions (acted / not acted / snoozed) — never inferred.
CREATE TABLE action_decisions (
  card_id TEXT PRIMARY KEY, rule_id TEXT NOT NULL, as_of_date TEXT NOT NULL, decision TEXT NOT NULL,
  note TEXT, decided_at TEXT NOT NULL);
```

`cron_runs`, `signal_snapshots` and `notification_outbox` follow `research-automation-infra.md` §4, with the fixes in §8.2.
`goals`, `holding_goal_map`, `allocation_policy` and `user_tax_context` (slab, residency, regime, LTCG used this FY) follow
`audit-journey.md` C2.

### 5.2 Evidence per rule (what the Rule page shows)

1. The spec: formula, roles, horizon, benchmark, the `registered_at` hash, and the git commit of the YAML.
2. The **trial count** N in the family (and N_eff if computed), with the full trial list.
3. **Walk-forward evidence**: the latest `backtest_runs` gate panel G1–G12, a layered return table (gross, after cost,
   after cost and tax; both exemption bounds; liquidated and deferred), the edge with 80 % and 95 % bootstrap intervals,
   PSR, DSR, MinTRL **and** the 80 %-power length ("needs 132 months for PSR 0.95, about 298 for 80 % power; has 126"),
   regime table, sensitivity grid, and turnover with the STCG/LTCG mix (`research-backtest-method.md` §11).
4. **Forward record** since `registered_at`: count of evaluations, conditions met, scored outcomes, and the rolling
   24-period edge versus the backtest's 80 % band (G12).
5. The **state**, with the plain reason and "what would change this".
6. For P rules: the policy source citation and the oracle-test ids instead of a backtest.

### 5.3 Shadow mode

Every S rule is evaluated daily from the moment it is registered. Its state is recorded and its paper outcome is scored at
horizon. The result is **never** shown as an action. It is shown only on the Rule page as "shadow record". This is the only
evidence that is out-of-sample with respect to the registration itself, so it is the antidote to the vault slowly turning
in-sample. It also answers the user's need to "watch my signals" honestly.

---

## 6. Backtest and evidence gates

### 6.1 Adopted

Gates G1–G12 are adopted from `research-backtest-method.md` §10 unchanged in meaning: provenance, survivorship, corporate
actions, leakage with a shuffle canary, sample size, costs and tax, cost stress, trial registry, multiple testing (DSR ≥ 0.95;
Holm if N ≤ 20, else SPA; HAC t ≥ 3), robustness (regimes, rolling window, PBO ≤ 0.20, neighbouring parameters), a one-shot
vault, and a live decay monitor.

Also adopted: the momentum report's gate 7 **decay haircut**. Any user-facing expected excess is OOS × 0.5, or the full
distribution is shown instead.

The thresholds are user decision **D6** and must be fixed **before** the first run. They are recorded in ADR-0015.

### 6.2 Amendments from the verifier notes

| Amendment | Reason |
|---|---|
| Show **MinTRL and the 80 %-power length** side by side in G5 | BT-9 |
| Regimes are defined on **pre-vault** data: (a) up to 2013-03 (Regular-plan only), (b) 2013-04 to 2019-12, (c) 2020-01 to the vault start | The vault overlaps 2023+ |
| Library defaults are banned. `lag`, `purge`, `embargo` and `fill_rule` are mandatory arguments with no default | R7 (bt `_DEFAULT_LAG` = 0; skfolio purge and embargo = 0) |
| ETF and stock cost rows without primary verification → `costs_estimated`, which caps the state at `SIGNAL_EVIDENCE_INCOMPLETE` | BT-4 |
| Windows that cross a tax period without a verified row → `ABSTAIN(tax_rules_missing)`. Pre-2024 rows (WP17) must use ₹1.25 lakh for 1-Apr to 22-Jul-2024 and abstain on lots bought ≤ 31-Jan-2018 | BT-3 |
| **Literature-fixed parameters** (10 months, 12-1, 20 % drawdown) count as one trial each. The family N also adds +1 per variant known to have been tried *in this project's history* (documented in the ADR) | R-registry honesty |
| A **"post-publication" tag**: OOS months after the source paper's publication date are reported separately (Faber-style SMA: about 2007; MOP TSMOM: 2012) | McLean–Pontiff decay |
| G2 for SIG-LX-01 depends on the WP16 probe result | S1 |

### 6.3 Where backtests run

- A **local CLI only**: `python -m iip.backtest run SIG-TF-01` (WP21). It needs the full U1 history and the bootstraps
  (B ≥ 5,000; CSCV with C(16,8) = 12,870 combinations), and it must never be bounded by a 300 s serverless step.
- Output: an **evidence bundle** made of the `backtest_trials` row, the `backtest_runs` row and a manifest. It contains
  statistics and hashes and **no raw NAVs**.
- The bundle is imported into hosted mode through the existing `import_snapshots` path. Hosted mode re-verifies the bundle
  hash and never reruns the backtest.
- Determinism: `seed = sha256(rule_id|version|data_snapshot_hash|trial_id)`. Rerunning a manifest must reproduce
  `output_hash` (ADR-0011 oracle).

### 6.4 Honest power arithmetic (shown in the UI)

| History available before the vault | HAC t ≥ 3 needs annualised excess Sharpe of at least |
|---|---|
| about 10.5 years (Direct plans 2013-04 → about 2023-10) | **≈ 0.93** |
| about 12 years | ≈ 0.87 (`verify-backtest-method.md`) |
| about 17 years (with Regular-plan history from about 2006, earliest date NOT VERIFIED) | ≈ 0.73 |

(My arithmetic: t ≈ SR_ann × √years for monthly data.) For comparison, the best of 100 zero-skill variants over 10 years
shows an SR of about 0.80 by luck (fixture MT-1). The realistic outcome is therefore `ABSTAIN` or `NO_SIGNAL` for every
seeded S rule, with the shadow ledger as the only path to graduation over many years. The gate thresholds are **not**
lowered to manufacture output. If the user wants a lower bar, that is decision D6, made before any run, and the cards then
carry the lower bar's label.

---

## 7. From engine output to a plain-English action, with provenance

### 7.1 ActionCard contract (extends `audit-journey.md` C3)

```
ActionCard {
  card_id = sha256(rule_id|version|as_of|scope_id|input_hash)
  class: P|D|S, rule_id, version, state, scope (goal_id | role)
  headline_template_id, fields{…}            # every field is a fact id → (value, unit, formula_id, inputs, source ids)
  options[]: {label_template_id, amount, units_by_scheme, exit_load, tax, stamp, stt, out_of_market_days, net_effect}
  evidence_ref: backtest run_id | policy citation id | oracle test ids
  as_of_date, data_freshness[], gaps[] (supervisor), disclaimers[] (compliance ids)
  engine_version, rules_version, snapshot_id
}
```

- Text is assembled **only from templates** in `rules/action_templates.yaml` (WP26), with numbers inserted from facts.
  `supervisor/contracts.validate_contract` already enforces that template fields resolve to facts.
- The optional LLM may *rephrase around* the card. It is labelled "AI-generated text", cannot alter a number (ADR-0007), and
  is off by default.

### 7.2 Examples (fictional numbers)

- **P1:** "Your rebalance rule R-REB@1 (band 5 pp, reviewed half-yearly) triggered for goal 'Retirement': equity 68.2 % vs
  target 60 %. Option A: send the next 4 monthly investments to the debt fund (no tax). Option B: switch ₹1,23,000 from
  [scheme] to [scheme] now: exit load ₹0, tax ₹2,870, out of the market for 3 working days. Data as of NAV 14-Oct-2026."
- **P2:** "Direct plan of [scheme] costs 0.80 pp a year less (₹3,200 a year on your holding). Switching today costs ₹10,020
  (mostly short-term tax). On 12-Mar-2027 your oldest lots turn long-term and the switch costs about ₹410. Waiting gives up
  about ₹1,300 of savings. Lower total: wait until 12-Mar-2027."
- **S, today:** "Trend rule SIG-TF-01: engine abstained. Not enough out-of-sample evidence: needs about 132 months at the
  PSR 0.95 floor (about 298 for 80 % power); has 126 after excluding the sealed final 3 years. Shadow record since
  15-Oct-2026: 0 scored outcomes."
- **D1:** "Review flag: [scheme] trailed its index-fund alternative by 1.9 pp a year over 3 years and 1.2 pp over 5 years.
  This is a description, not an exit signal."

### 7.3 Supervisor

A new worker, `supervisor/workers/actions.py` (WP26), builds the manifest per goal: profile, tax context, holdings, fresh
NAVs, policy version and rule-table versions. Any gap → `ABSTAIN(context_missing(<field>))` **for that goal only**
(ADR-0003). It reports cards, abstentions and gaps; it never fills a gap.

---

## 8. Portfolio integration, automation and alerts

### 8.1 Portfolio loop

CAS import (or broker holdings, read-only, decision D4) → FIFO lots → goals and the holding→goal map → allocation policy
table (user-set, versioned) → P1–P9 → D1–D3 → S states → `signal_snapshots` → Today page → user decision log →
outcomes. The single "amount + date" profile becomes one goal type among several (`audit-journey.md` C2).

### 8.2 Cron (Vercel Hobby; schedule from `research-automation-infra.md` §1.3)

Facts (via `audit-journey.md` C1, https://vercel.com/docs/cron-jobs/usage-and-pricing, accessed 2026-10-15): "Hobby accounts
are limited to cron jobs that run **once per day**", precision "Per-hour (±59 min)"; "Vercel will not retry an invocation if
a cron job fails"; delivery "can also occasionally invoke the same scheduled run more than once"
(https://vercel.com/docs/cron-jobs/manage-cron-jobs).

| Job | UTC | Work (one resumable step ≤ 90 s each) |
|---|---|---|
| J1 `navall` | 01h | NAVAll for the newest unseen NAV date; U2 latest-only upsert; U0 ∪ U1 history append |
| J2 `navall-continue` | 02h | Finish any open run; MoSPI CPI on release days; RBI RSS poll |
| J3 `history` | 03h | History gap fill for U0 ∪ U1 (bounded windows) |
| J4 `snapshot` | 05h | FoF/overseas late-NAV re-run; then **evaluate all rules** → `rule_evaluations`, score due `outcomes`, write `signal_snapshots` (ABSTAIN stored too), queue the outbox |
| J5 `watchdog` | 13h | A missing snapshot or stale source triggers one "pipeline needs attention" ping |

Corrections to the wave-1 claim SQL (AUTO-3):
- **Claim:**
  `INSERT INTO cron_runs(job,run_key,state,attempts,started_at) VALUES(?,?,'running',1,?) ON CONFLICT(job,run_key) DO UPDATE SET attempts=attempts+1, state='running', started_at=excluded.started_at WHERE cron_runs.state='failed' OR (cron_runs.state='running' AND cron_runs.started_at < ?)`.
  The last parameter is now minus the lease TTL (330 s), computed in the service layer. This lets a killed run be taken over.
- **`run_key` is the target data date.** For J1, the run_key is derived **after** a cheap conditional fetch
  (`If-None-Match` / `Last-Modified`) of NAVAll. Duplicate deliveries may both fetch, which is accepted (one extra GET) and
  documented, but only one wins the claim.
- **Outbox reaper:** a `sending` row older than 10 minutes → `failed` (at most one lost ping; never a duplicate).
- **Tests for both stale states** are added (WP10).

Route: `GET /api/cron/{job}`. The `VERCEL_URL` host is accepted **on this route only**, with `Authorization: Bearer
CRON_SECRET` (≥ 32 chars, different from the access token, compared with `hmac.compare_digest`), production only, and wrong
secrets rate-limited. This needs an ADR-0008 amendment (ADR-0014). Live check: press "Run" in the dashboard, record the Host
value received, confirm `noop` on a second press, and confirm Vercel Authentication does not intercept the call (NOT
VERIFIED, `verify-automation-infra.md`).

### 8.3 Alerts

- **In-app first.** The Today page is authoritative.
- **Ping-only** push to the **owner's own** channel: "IIP: daily report ready (data as of 14-Oct). Open the app." No
  amounts, schemes or verbs.
- Channel options (decision D12):
  - **Telegram bot to the owner's chat** (v1). Free; "bots are able to message their users at no cost",
    https://core.telegram.org/bots/faq, via `research-automation-infra.md` §5.
  - **Web Push** (v2; end-to-end encrypted per RFC 8291).
  - **Off** (default).
- Conflict to resolve in D12: `research-regulation.md` §8.1.3 says "No push to third-party channels (Telegram …)". It also
  says "Alerts go only to the owner's own channel". A content-free ping to the owner's own Telegram chat fits the second
  sentence. The user must confirm.
- Rejected: ntfy.sh public topics ("the topic is essentially a password", https://docs.ntfy.sh/publish/), Gmail app
  passwords, and the GitHub Actions worker.

---

## 9. Performance fixes (from the audits; precondition for cron)

| # | Fix | Evidence (audit) | WP |
|---|---|---|---|
| F1 | Batch `build_universe` (one grouped `COUNT … GROUP BY instrument_id` instead of one per scheme); add a time budget to discovery; stop writing a DB row on every Discovery visit (cache by input hash) | 1,791 statements; `POST /api/discover` 504 at 300.1 s (`audit-perf-hosted.md`) | WP02 |
| F2 | Move Turso to a new `bom1` database. The function runs in `bom1`; the DB primary is in `iad1` | About 0.40 s per statement; `/api/data-health` 10.5–11.3 s | WP06 (ops; the post-move latency is NOT VERIFIED and must be measured) |
| F3 | Session lookup in a threadpool; update `last_seen` at most every 5 minutes | 2 statements per call on the event loop | WP03 |
| F4 | Serve `index.html` and `/assets/*` from the Vercel CDN via `public/`, with the security headers copied into `vercel.json`; immutable cache for hashed assets | `max-age=0`, MISS on every repeat; 9 cold starts in about 90 s | WP04 |
| F5 | Batch the data-health query (one per source) and the instrument detail page (8 serial statements); replace the full-table `COUNT … GROUP BY` behind the "data as of" line with a maintained `source_freshness` row | audits | WP05 |
| F6 | Read-only startup; lazy-load scipy inside `engine/forecasting/validation.py` call sites only; trim the bundle below 225 MB so dependencies stop being reinstalled on each cold start | 6.14 s cold start; 2.35–2.63 s of dependency install | WP05 |
| F7 | A `/api/instruments/{id}/summary` endpoint (name and latest facts) and server-side downsampling of chart series (the backend picks one point per period, deterministically) | About 0.73 MB of synthetic JSON per call; N+1 on the Fixed income tables | WP07 |
| F8 | A shared client cache in `useApi` (keyed GETs, in-flight de-dupe); run the landing page's fetches in parallel; break cross-page imports | data-health fetched twice; about 5 serial round trips | WP08 |
| F9 | Move the 98 s NAV refresh out of the browser session into cron J1–J3; the button only queues work | `audit-journey.md` §3 | WP10 |

All wall-clock figures after these fixes are NOT VERIFIED until measured. WP06 and WP10 record measurements in
`docs/operations/known-limitations.md`.

---

## 10. Removing manual entry (UX)

**Inputs the user still owns.** They are entered once, at onboarding, and only these:
- goals (amount, date, priority);
- loss budget;
- target allocation per goal (from a cited policy table, user-confirmed);
- emergency months and essential expenses;
- tax context (slab, regime, residency, LTCG used outside the app this FY);
- rebalance band and cadence;
- notification channel.

Everything else is automatic or file-based:

| Today typed | Becomes | WP |
|---|---|---|
| CPI | MoSPI API, cron | WP11 |
| 91-day T-bill / risk-free | RBI RSS, with self-check `y = (100−P)/P × 365/days` reproduced to 4 dp | WP12 |
| Fund history backfill | Auto-tracked U0 ∪ U1 history, cron J3 | WP13, WP10 |
| Tax class of index funds | Category rule plus name-pattern table | WP13 |
| Exit loads | SID grammar parser, plus loads observed in the CAS; abstain outside the grammar; optional labelled upper bound (D7) | WP14 |
| Regular-plan holdings rejected | CAS fix | WP14 |
| Duration, YTM, credit mix, riskometer | Parse the factsheet or portfolio file the user drops in; compute credit mix from holdings | WP15 |
| TER | From the factsheet file; or the AMFI JSON (D5, off by default) | WP15 |
| FD card rates | Paste parser; per-bank allowlist only where terms allow | existing |
| G-sec quotes, ratings | BLOCKED. Stays manual or absent | — |

**Pages.**
- **Today** (new `/`): data-as-of, freshness, P cards ranked by ₹ effect, D flags, a list of S states, the decision log.
- **Goals:** funded % and policy.
- **Rules:** the ledger per §5.2.
- **Data health:** unchanged, faster.
- Overview moves to `/overview`.

**Regulatory wording and surfaces** (`research-regulation.md` §8, VERIFIED definitions, read as personal use, not legal
advice):
- Signals and cards exist **only behind authentication**. There is one principal and no share links.
- A **new compliance channel `operator_private`** (decision D1) allows "entry condition met" / "exit condition met" and,
  only if the user opts in, BUY/SELL badges, always next to the rule id, version, evidence card and as-of date. Every
  existing BLOCK stays in force on export, share and unauthenticated surfaces.
- P cards may use "switch ₹X from A to B" in `operator_private`, because the action is the user's own rule. The text must
  name that rule.
- No exports of named-security S or D outputs. P-card exports carry the owner's name and a "private, not for distribution"
  watermark (R14).
- **Public repo:** rule specs use roles only. No backtest results, screenshots or return claims; the README has no
  performance claims. Add `X-Robots-Tag: noindex` and a disallow-all `robots.txt` on the hosted origin (NOT VERIFIED today).
- **Showing the app publicly** (LinkedIn, job search) uses synthetic data only (decision D13; the "non-cash consideration"
  question is for a lawyer).
- **No order placement**, in any mode.

---

## 11. Phased build plan: 28 work packages in parallel worktrees

**Conflict rules.**
1. Each file has exactly one owning WP.
2. Every new table lives in WP09's migrations, numbered `0004_signals.sql`, `0005_cron.sql` and `0006_goals.sql`.
3. Router registration switches to autodiscovery of `api/routes_*.py` in WP05, so later WPs only **add** router files.
4. `vercel.json` is owned by WP04 (headers **and** the `crons` array).
5. `security.py` is owned by WP03 (session fix **and** the cron host exception).
6. `App.tsx` routes are owned by WP27.
7. `data/registry.py` source entries are owned by WP12, for every new source id.
8. Tests live next to their WP under `backend/tests/<wp-area>/` or as `*.test.tsx` beside the page.
9. Python runs as `backend/.venv/bin/...`; frontend scripts as `node --run <script>`.

### Phase A: no dependencies (19 WPs, all start together)

| WP | Name | Files touched (owned) | Done when |
|---|---|---|---|
| WP01 | ADRs and methodology | `docs/architecture/architecture-decision-records/0014-scheduled-jobs.md`, `0015-signal-classes-and-gates.md`, `0016-operator-private-wording.md`, `0000-index.md`; `docs/forecasting/backtest-methodology.md`; `docs/product/decisions-register.md` (D1–D13, D-H) | ADRs accepted by the user; decisions recorded with dates |
| WP02 | Discovery N+1 and time budget | `backend/src/iip/services/discovery.py`; `backend/tests/discovery/test_batching.py` | Statement count O(1) in the number of schemes (counted with a fake driver); budget abort is reasoned, not a 504 |
| WP03 | Security middleware | `backend/src/iip/api/security.py`; `backend/tests/security/test_session_threadpool.py`, `test_cron_host_exception.py` | Session lookup off the event loop; `last_seen` throttled; `VERCEL_URL` accepted only on `/api/cron/*` with the bearer (every other route still returns 400) |
| WP04 | CDN static and vercel.json | `vercel.json`, `scripts/vercel-build.sh`, `public/` build output wiring | Hashed assets served with `immutable`, x-vercel-cache HIT on repeat; security headers equal to today's; `crons` J1–J5 present but **disabled** until WP10 ships (empty secret → 404) |
| WP05 | App startup, router autodiscovery, query batching | `backend/src/iip/api/app.py`, `backend/src/iip/api/routes.py`, `backend/src/iip/api/routes_core.py`, `backend/src/iip/services/instruments.py`; `backend/src/iip/engine/forecasting/validation.py` (lazy scipy import only) | Cold-start imports exclude scipy; data-health uses ≤ 3 statements; instrument detail uses ≤ 2 |
| WP06 | Turso `bom1` migration runbook | `docs/operations/turso-migration.md`, `backend/scripts/turso_copy.py` | Runbook with a dry run on a copy; latency measured before and after (user executes; REQUIRES CONFIGURATION) |
| WP07 | Instrument summary and downsampling | `backend/src/iip/api/routes_instrument_summary.py`, `backend/src/iip/services/series_view.py`; `frontend/src/pages/Risk.tsx`, `Scenarios.tsx`, `FixedIncome.tsx` | No page fetches a full history to show a name; FD/T-bill tables make 1 request |
| WP08 | Client cache | `frontend/src/lib/useApi.ts`, `frontend/src/lib/api.ts`, `frontend/src/pages/Overview.tsx`, `frontend/src/pages/Watchlist.tsx` | De-duped GETs; parallel landing page; no cross-page module imports |
| WP09 | Ledger schema and repositories | `backend/src/iip/store/migrations/0004_signals.sql`, `0005_cron.sql`, `0006_goals.sql`; `backend/src/iip/store/ledger.py`, `backend/src/iip/store/goals_repo.py` | Migrations apply on SQLite and libSQL; append-only triggers tested; repositories batch writes |
| WP11 | MoSPI CPI adapter fix | `backend/src/iip/data/mospi.py`; `backend/tests/data/test_mospi.py` | `getCPIData` for base 2024; "CPI (General)" label; no credentials; synthetic fixtures |
| WP12 | RBI T-bill RSS and source registry | `backend/src/iip/data/rbi_tbill.py`, `backend/src/iip/data/parsers/rbi_pr.py`, `backend/src/iip/data/registry.py`, `backend/src/iip/data/fetch.py` (allowlist hosts: RBI, Telegram API) | Parser self-check reproduces published yields to 4 dp on a synthetic fixture; abstains on mismatch; citations rendered as plain text |
| WP13 | Tax class and core universe | `backend/src/iip/rules/mf_categories.yaml`, `backend/src/iip/rules/index_name_patterns.yaml` (new), `backend/src/iip/data/parsers/_amfi.py`, `backend/src/iip/services/ingestion.py` | UNKNOWN count drops (measured on today's file, not stored); U1 role-binding proposer; history kept only for U0 ∪ U1 |
| WP14 | Exit-load grammar and CAS fixes | `backend/src/iip/data/parsers/sid_exit_load.py` (new), `backend/src/iip/services/cas.py` | Grammar parses a documented set of phrasings and abstains on everything else; Regular-plan CAS rows accepted; CAS-charged loads recorded as observed facts |
| WP15 | Factsheet and portfolio file parsers | `backend/src/iip/data/parsers/factsheet_file.py` (new), `backend/src/iip/services/inputs.py`, `backend/src/iip/api/routes_inputs.py` | Duration, YTM, TER and credit mix parsed from a user file with page or cell provenance; abstain on ambiguity |
| WP16 | AMFI survivorship probe and `scheme_status` | `backend/scripts/probe_amfi_closed.py`, `backend/src/iip/data/parsers/amfi_navhistory.py`, `backend/src/iip/data/parsers/amfi_scheme_master.py`, `docs/data/probes/amfi-closed-schemes.md` | VERIFIED or NOT VERIFIED answer on whether closed schemes appear (`tp=2`/`3`; Closure Date); earliest history date per U1 role; `scheme_status` rows populated |
| WP17 | Rule tables: costs and historical tax | `backend/src/iip/rules/costs/india_equity.yaml` (new), `backend/src/iip/rules/tax/india.yaml`, `backend/src/iip/rules/loader.py` | Every row has a source and a status; pre-2024 rows NOT VERIFIED until a primary source is cited; ETF STT row NOT VERIFIED; loader rejects rows without a status |
| WP18 | Backtest ledger engine | `backend/src/iip/engine/backtest/__init__.py`, `ledger.py`, `costs_equity.py`, `tax_lots.py` | Fixtures C-1 (₹237.8212) and T-1 (₹4,160 / ₹2,600 / ₹0) reproduce in Decimal; FIFO enforced; terminal liquidation in both modes |
| WP19 | Walk-forward, timing and vault | `backend/src/iip/engine/backtest/walkforward.py`, `timing.py` | Mandatory `lag`/`purge`/`embargo`/`fill_rule`; leakage invariants 1–8 raise `LeakageError`; vault opens once (flag persisted by the caller) |
| WP20 | Multiple testing and power | `backend/src/iip/engine/backtest/multiple_testing.py` | Fixtures DSR-1 (0.9004 / 0.9505), MT-1, MT-2, MT-3 and the 298-month power case reproduce; Holm, SPA (stationary bootstrap, deterministic seed), PBO/CSCV with S = 16 |

### Phase B: builds on Phase A (9 WPs)

| WP | Name | Depends on | Files touched (owned) | Done when |
|---|---|---|---|---|
| WP10 | Cron routes and jobs | 03, 04, 09, 12, 13 | `backend/src/iip/api/routes_cron.py`, `backend/src/iip/services/cron.py`; `backend/tests/cron/*` | All tests in `research-automation-infra.md` §4 plus stale-claim and stale-outbox reapers; duplicate delivery is a no-op; live check recorded |
| WP21 | Gates, report, registry loader and local CLI | 18, 19, 20, 09, 17 | `backend/src/iip/engine/backtest/gates.py`, `report.py`; `backend/src/iip/engine/signals/registry.py`; `backend/src/iip/backtest_cli.py`; `signals/*.yaml` schema (`backend/src/iip/rules/signals/schema.yaml`) | G1–G12 fail closed with reason codes; evidence bundle with no raw data; manifest re-run reproduces `output_hash`; shuffle canary passes |
| WP22 | Seeded S rules | 21 | `backend/src/iip/engine/signals/rules_index.py`; `backend/src/iip/rules/signals/SIG-TF-01.yaml`, `SIG-AM-01.yaml`, `SIG-DD-01.yaml`, `SIG-DM-01.yaml`, `SIG-LX-01.yaml` | Pure functions over (as_of, series); specs committed **before** any run (git timestamp is the pre-registration evidence); first local run results stored in the DB only, never committed |
| WP23 | Goals and allocation policy | 09 | `backend/src/iip/engine/policy/__init__.py`, `goals.py`, `allocation.py`; `backend/src/iip/services/goals.py`; `backend/src/iip/api/routes_goals.py`; `backend/src/iip/rules/allocation_policy.yaml` (values empty until D5/D4) | Funded % per goal; the policy table refuses to load without user-set values; EF gate |
| WP24 | Policy actions P1–P9 | 23, 17 | `backend/src/iip/engine/policy/actions.py`; `backend/src/iip/services/actions.py` | Oracle tests per formula (independent re-implementation per ADR-0011); FIFO-only sale plans; each card abstains on its own gaps |
| WP25 | Descriptive flags D1–D3 | 09, 13 | `backend/src/iip/engine/policy/flags.py`; `backend/src/iip/services/flags.py` | D1 against the index-fund proxy; D2 live-only statistics with mandatory banners; 36-month floor |
| WP26 | Supervisor worker, snapshots and compliance channel | 21, 24, 25 | `backend/src/iip/supervisor/workers/actions.py`, `backend/src/iip/supervisor/compliance.py`, `backend/src/iip/rules/compliance_phrases.yaml`, `backend/src/iip/rules/action_templates.yaml`, `backend/src/iip/services/snapshot.py` | Content-addressed snapshots; `operator_private` channel; template linter blocks forecast language in P text; ABSTAIN snapshots stored |
| WP27 | Frontend: Today, Goals, Rules, onboarding | 23–26 (can start against typed stubs) | `frontend/src/App.tsx`, `frontend/src/pages/Today.tsx`, `Goals.tsx`, `Rules.tsx`, `RuleDetail.tsx`, `Onboarding.tsx`; `frontend/src/components/ActionCard.tsx`, `GatePanel.tsx`; `frontend/src/lib/types-signals.ts` | Every number shows its formula and source in the ExplainDrawer; abstentions show "what would change this"; a11y tests pass |
| WP28 | Notifications (ping-only) | 10, 26 | `backend/src/iip/services/notify.py`; `frontend/src/pages/Settings.tsx` (notification section) | `IIP_NOTIFY=off` by default; a sentinel test proves no amounts or names ever appear in a ping; outbox sends once |

**Critical path:** WP03/04/09 → WP10 → J4 needs WP26 → WP28. Backtest results need WP18–20 → 21 → 22, and run locally.

**Optional, gated on decisions (not counted in the 28):**
- WP-X1: read the Upstox and Angel One developer terms, then a local-only candle adapter with freeze-and-diff (D9).
- WP-X2: local TRI CSV import (D8).
- WP-X3: IIM-A factor panel.
- WP-X4: Web Push.
- WP-X5: read-only broker holdings sync (D4; the Zerodha FAQ says a static IP is needed only for order placement).

---

## 12. What to cut

| Cut | Reason |
|---|---|
| Single-stock buy/sell signals, stock screeners, fundamentals signals (F-score, accruals, PEAD, pledge-as-signal), valuation (P/E) bands | BLOCKED data (survivorship, point-in-time, licence). Evidence is weak or in-sample (`research-fundamentals-data.md`, FD-3) |
| Kite Connect, Dhan and any paid feed | Breaks the no-paid-keys rule; Kite terms ban building databases |
| NSE/BSE/niftyindices scrapers and libraries (jugaad, nsepython, nselib, nsetools, eod2, PKScreener paths, yfinance) | Terms ban automation |
| Order placement and algo execution, any mode | Static-IP and registration rules NOT VERIFIED; Vercel static IPs are shared; nothing in the evidence needs it |
| Volatility targeting, stop-loss rules, mean-variance optimisers, Kelly sizing (except as an over-betting warning), factor timing, category or sector rotation, rate-cycle duration calls, "SIP beats lump sum" return claims, star-rating or manager-change exits, rolling-return "consistency" picks | `ABSTAIN`: no India out-of-sample, after-cost and after-tax evidence (allocation §9; MF §1) |
| Ranking by past returns or past excess | Persistence is weak (MF R1); it is the main way a dashboard misleads |
| ntfy.sh public topics, Gmail SMTP, GitHub Actions as the worker | Spoofable, credential blast radius, or unreliable |
| The browser-held 98 s NAV refresh; Discovery writing a row per visit; full-history JSON to the browser | Performance (§9) |
| LLM text near numbers, unless labelled and off by default | ADR-0007; regulation §8.4 |
| Any README, LinkedIn or resume performance claim | Regulation §8.1.7; prohibited activity (ii) |
| Manual bhavcopy import (for now) | NOT VERIFIED licence (D9) |

---

## 13. Decisions only the user can make (fix before the first backtest run)

| Id | Decision | Default proposed here |
|---|---|---|
| D1 | Action wording in the private view: neutral "condition met" only, or opt-in BUY/SELL badges | Neutral only |
| D2 | Emergency months and essential expenses | REQUIRES CONFIGURATION |
| D3 | U1 cap (number of auto-tracked index schemes), given AMFI's "significant portion" clause | ≤ 30 |
| D4 | Rebalance band and cadence; allow taxable sales or cash flows only; read-only broker holdings | 5 pp, semi-annual, cash flows first |
| D5 | Target allocation per goal (policy table values); use of the AMFI TER JSON | REQUIRES CONFIGURATION; JSON off |
| D6 | Gate thresholds (DSR ≥ 0.95, PBO ≤ 0.20, HAC t ≥ 3, ≥ 30 OOS periods plus MinTRL, survive ×2 slippage, vault max(20 %, 3 y), decay ×0.5) | Keep as written |
| D7 | Accept a researched, labelled exit-load upper bound | No, until researched |
| D8 | Local TRI CSV import for longer history | Off |
| D9 | Equity route: open an Upstox account for local ETF data, or stay out | Stay out until the terms are read |
| D10 | Tax context: slab, regime, residency, LTCG used elsewhere this FY | REQUIRES CONFIGURATION; until set, the highest slab with the exemption used is the conservative bound for gates |
| D11 | Limits for P7, P8 and P9 (days, HHI, bp) | 30 days; user-set HHI; 15 bp |
| D12 | Notification channel (Telegram ping vs the regulation report's caution) | Off |
| D13 | Any public showcase | Synthetic data only |
| D-H | AMFI data in hosted mode: request permission, accept the risk, or local-only signals | Ask AMFI; meanwhile minimised U0 ∪ U1 |

---

## 14. Open items (NOT VERIFIED)

1. Whether AMFI NAV history includes closed or merged schemes, and the earliest available date per U1 scheme (WP16).
2. Turso latency after the move to `bom1`; how cron interacts with Vercel Authentication; the Host header received on cron
   calls.
3. ETF STT treatment; pre-2024 historical tax rows from primary sources; the Income-tax Act 2025 schedule references for the
   fund tax exemption.
4. Upstox and Angel One developer terms on storage and backtesting, including whether delisted equities are available.
5. The exit-load treatment of a same-scheme Regular→Direct switch per AMC.
6. A historical 91-day T-bill series source (the RBI RSS keeps 10 items). SIG-AM-01 uses a liquid-fund hurdle instead,
   chosen in advance.
7. Whether AMFI's "derivative works" clause reaches a persisted backtest statistic.

---

## 15. Sources

All URLs below were accessed on 2026-10-15 by the wave-1 report named in each row. This document quotes them from those
reports and did not re-fetch them.

| Claim | URL | Short quote | Via |
|---|---|---|---|
| AMFI terms | https://www.amfiindia.com/terms-of-use | "personal and non-commercial use only … shall not store electronically any significant portion" | `docs/data/source-registry.md` |
| NSE automation ban | https://www.nseindia.com/ (Terms of Use, updated 29/10/2025) | "prohibited to conduct any systematic or automated data collection activities" | `research-equity-data-nse.md` |
| niftyindices terms | https://www.niftyindices.com/terms-of-use | "personal, non-commercial use only"; "No material … uploaded, transmitted … without prior written permission" | `verify-evidence-momentum.md` |
| Upstox free API | https://upstox.com/trading-api | "All trading + data APIs are free of cost." | `verify-equity-data-nse.md` |
| Upstox adjustment | https://community.upstox.com/t/3548 | "Currently, we only adjust for bonuses and splits." | `verify-equity-data-alt.md` |
| Kite terms | https://kite.trade/terms/ | "Scrape, build databases, or otherwise create permanent copies" | `verify-equity-data-nse.md` |
| Vercel Hobby cron | https://vercel.com/docs/cron-jobs/usage-and-pricing | "limited to cron jobs that run once per day" | `audit-journey.md` |
| Vercel cron delivery | https://vercel.com/docs/cron-jobs/manage-cron-jobs | "will not retry"; "can also occasionally invoke the same scheduled run more than once" | `audit-journey.md` |
| Cron host refusal (third party) | https://github.com/namphuongtran/familyroots/issues/265 | "Vercel Cron calls the deployment's own host, which ALLOWED_HOSTS refuses" | `research-automation-infra.md` |
| Telegram bots | https://core.telegram.org/bots/faq | "bots are able to message their users at no cost" | `research-automation-infra.md` |
| ntfy topics | https://docs.ntfy.sh/publish/ | "the topic is essentially a password" | `research-automation-infra.md` |
| Rebalancing bands | https://www.aaii.com/journal/article/best-practices-for-portfolio-rebalancing | "annual or semiannual monitoring, with rebalancing at 5% thresholds" | `research-evidence-mf.md`, `verify-evidence-mf.md` |
| Bond duration | https://www.ici.org/viewpoints/view_18_bond_duration | "lower the overall net asset value of the fund by 4 percent" | `research-evidence-mf.md` |
| Lump sum vs averaging | https://www.nl.vanguard/professional/vanguard-365/cost-averaging | "a lump-sum approach won between 61.6% and 73.7% of the time" | `research-evidence-mf.md` |
| Deflated Sharpe, MinTRL | Bailey & López de Prado 2014 (SSRN) | worked example DSR 0.9505 | `research-backtest-method.md` [S4] |
| t > 3 hurdle | Harvey, Liu & Zhu 2016 | "t-ratio greater than 3.0" (quote NOT VERIFIED by re-check) | `research-backtest-method.md` [S12] |
| Zerodha delivery charges | https://zerodha.com/charges | ₹1,00,000 round trip ₹237.82 (VERIFIED-SECONDARY) | `research-backtest-method.md` |

Repo documents relied on: `docs/forecasting/validation-methodology.md` (§3.4 S1–S3, §6, §8),
`docs/data/source-registry.md` (§2.1–2.3, line 91), ADR-0002, 0003, 0005, 0007, 0008, 0009, 0010, 0011, 0012 and 0013, and
`docs/research/return-target-feasibility.md`.
