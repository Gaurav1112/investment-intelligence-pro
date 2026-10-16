# Design: a risk-first deterministic signal engine for Investment Intelligence Pro

Wave 1 · design angle **risk-first** · Date: 2026-10-15 · Status: design proposal. Nothing is implemented, no other repo file was
changed and nothing was committed.

> **The angle in one line.** Allocation, loss limits and position sizes decide everything. A "signal" may only move money
> *inside* limits the user has already set, and only after a documented, out-of-sample, cost- and tax-aware backtest supports it.
> Until then the engine says what the *rules the user chose* require today, and it abstains on market timing.
>
> Not investment advice. This is a design for a private, single-user decision-support tool. All ₹ figures in examples are
> **fictional** and are labelled as such.

## Status labels and evidence tags

| Label | Meaning in this document |
|---|---|
| **VERIFIED** | Confirmed from a primary source or from repo code in wave 1, and not weakened by the wave-1 verify pass. |
| **NOT VERIFIED** | Not confirmed, or weakened to "ambiguous" by a verify file. The engine may not use it as a number. |
| **REQUIRES CONFIGURATION** | Works once the user supplies an input, an account or a decision. |
| **BLOCKED** | Ruled out by terms of use, law, or missing lawful data. |
| **PARAMETER** | A design choice made in advance (for example a band width). It is not evidence. It is shown to the user as a choice, with who chose it and when. |

External claims in this document are **carried over from the wave-1 reports**. URLs and quotes are as recorded there; the access
date is 2026-10-15. **No new web research was done for this design.** Every claim that a wave-1 verify file refuted or weakened is
used here only in its corrected form; §14 lists the corrections.

---

## 0. Summary

1. **What the user gets.** A daily *Today* page that answers "what do my own rules say I should do with my money now?" It covers
   the emergency fund, goal safety, the loss budget, drift against target allocation, where the next rupee should go, tax actions,
   cost actions and data health. Each answer is a plain-English action card with ₹ amounts, cost and tax, and a provenance trail.
   When nothing is needed, or the evidence is missing, the card says so.
2. **The order of authority is fixed.** Data integrity, then liquidity, then goal-date safety, then the loss budget, then
   concentration limits, then target allocation and bands, then tax and cost actions, then validated signal tilts. A lower layer can
   never override a higher one (§4).
3. **The loss budget sets equity, not the 20–25 % aspiration.** The maximum equity share comes from the user's rupee loss budget and
   a cited table of historical worst drawdowns, for example Nifty 500 TRI −67.0 % and Midcap 150 TRI −72.9 % (`return-target-
   feasibility.md` §2.4 [C]). Worked fictional example: a ₹10,00,000 bucket with a ₹2,50,000 loss budget allows 34 % broad
   equity (§5.3).
4. **Market-timing signals start in ABSTAIN and will very likely stay there for years.** Every timing technique reviewed was refuted
   out of sample, untested on Indian data after cost and tax, or carried crash risk at least as bad as buy-and-hold
   (`research-evidence-allocation.md` §9). The joint evidence gates need roughly 11–25 years of out-of-sample monthly data for a
   Sharpe-0.5 edge (`research-backtest-method.md` §9.4, verify BT-9). The registry and gates are still built, because they are what
   *stops* a false signal from reaching real money.
5. **Signals can only tilt within budgets.** If a signal ever passes, its output is a bounded weight change, clamped to the policy band
   and to the loss-budget equity cap. It is executed with new cash first, and a sale is allowed only if its validated after-tax edge
   exceeds the tax and exit load it triggers (§7).
6. **Data that is actually permitted:** AMFI NAVs (personal use, minimised storage), the user's own CAS and documents, MoSPI CPI, RBI
   T-bill press releases (RSS), and nothing scraped. Stock prices are BLOCKED for automation; free broker APIs are REQUIRES
   CONFIGURATION / NOT VERIFIED and local-only. Index TRI history from niftyindices.com needs written permission to copy or upload
   (§2).
7. **Stocks, "when to buy and sell":** BLOCKED / ABSTAIN. If the user later configures a broker API in local mode, a risk-first stock
   sleeve with hard size limits is specified, but no buy or sell signal is emitted without passing the same gates (§6.6).
8. **Automation:** five daily Vercel cron jobs on a narrow `/api/cron/{job}` route with a separate `CRON_SECRET`, idempotent claims,
   content-addressed snapshots (an ABSTAIN is stored too) and a content-free notification ping (§9).
9. **Performance fixes come first**, because a risk engine that takes 300 s is useless (§10). The order is: move Turso to `bom1`,
   batch discovery, take the session lookup off the event loop, serve the UI from the CDN, fix the N+1 queries, and stop shipping full
   NAV histories to the browser.
10. **Build plan:** 28 work packages in three waves (20 + 6 + 2). Each package owns its files exclusively within its wave (§13).

---

## 1. Design principles (binding, restated for this angle)

| # | Principle | Consequence in the design |
|---|---|---|
| P1 | **Protect capital before growing it** | The risk layers (§4) run before any ranking or signal. A failed risk layer suppresses every lower card for that goal. |
| P2 | **Deterministic engine** | `engine/` uses Decimal for money, units, costs and tax, and has no clock, IO or randomness. `as_of`, data snapshots and seeds are passed in. The existing `test_engine_purity.py` covers every new module. |
| P3 | **Abstain on missing context** | The supervisor manifest (ADR-0003) is extended per goal. A missing input causes an abstention for that goal only, and names the input. |
| P4 | **No fabricated numbers** | Every number on a card has a `fact_id` (source + retrieval) or a `formula_id` (engine function + version). Parameters are labelled PARAMETER, with who set them. |
| P5 | **Evidence gate for signals** | A timing or selection signal exists only if G1–G12 pass (`research-backtest-method.md` §10). Otherwise it is `ABSTAIN` or `NO_SIGNAL`, with the failing gate named. |
| P6 | **Ex-ante sizing beats ex-post stopping** | No stop-loss, volatility-timing or drawdown-triggered selling. All three are "ABSTAIN" in the evidence (`research-evidence-allocation.md` §5–6). Drawdown is controlled by *sizing* before the fall. |
| P7 | **Cash flows before sales** | India taxes every sale (STCG 20 %, LTCG 12.5 % above ₹1.25 lakh; repo `india.yaml`) and FIFO fixes which lots are sold (verify-evidence-allocation, CBDT Circular 768). Rebalancing and tilts use new money first. |
| P8 | **Private by construction** | Signals are only shown behind login, to one principal, with no share or export of named-security signals (`research-regulation.md` §8.1). |

---

## 2. Data layer: sources that are actually permitted

### 2.1 Source table

| Source | What it feeds | Permitted use (quote as recorded in wave 1) | Status | Storage rule |
|---|---|---|---|---|
| **AMFI NAVAll** (`portal.amfiindia.com/spages/NAVAll.txt`) | Latest NAV, scheme master, categories | "personal and non-commercial use only"; "You shall not store electronically any significant portion of any part of the Site" (https://www.amfiindia.com/terms-of-use, via `source-registry.md` §2.1) | VERIFIED as live adapter; **hosted mode is flagged REQUIRES LICENCE / WRITTEN PERMISSION by the registry itself** (registry line 91), an open conflict to record in ADR-0017 | Full file parsed in memory. Persist only the rows for held, watched and core-universe schemes |
| **AMFI NAV history** | Monthly series for risk statistics and backtests | Same terms | VERIFIED adapter | Only for the **capped core universe** (§3) plus holdings. Each series is reduced to a month-end grid (§10, `series_grid`) |
| **User's CAS** (CAMS/KFin PDF the user downloads) | Holdings, lots, Regular/Direct, exit load charged | The user's own data | VERIFIED (existing `routes_cas.py`) | Encrypted at rest as today |
| **User-supplied documents** (factsheet, monthly portfolio file, SID "Load Structure" text) | Duration, YTM, credit mix, exit loads | Uploaded by the user and parsed deterministically. **No crawling**, because AMC and bank terms forbid it (`audit-automation.md` §2.2) | REQUIRES CONFIGURATION | Parsed facts plus file hash; the raw file is discarded after parsing unless the user keeps it |
| **MoSPI CPI API** | Real returns, inflation context | Government open data; filtered queries need no login (`audit-automation.md` §3.1) | VERIFIED source; **the adapter is broken for base 2024** (it uses `getCPIIndex`, the wrong field name, and needless credentials) | One row per month |
| **RBI press-release RSS** (T-bill auction results) | Risk-free series for Sharpe and the cash leg of backtests | RBI offers the feed for automatic updates. HTTP 200 to an honest UA. `robots.txt` returns 418 (`audit-automation.md` §3.2) | VERIFIED probe; the feed keeps only 10 items, so a daily poll can miss one; a deterministic self-check applies: `yield = (100 − P)/P × 365/days` reproduces the published yields to 4 dp | Store yields with a citation. **Do not render RBI deep links**: the RBI disclaimer says deep links need permission (`audit-automation.md` §2.3) |
| **AMFI TER JSON endpoint** | Cost comparator, Regular→Direct break-even | The AMFI terms ban "reverse engineering"; the endpoint is undocumented | **User decision, off by default** (`audit-automation.md` §3.3) | — |
| **NSE website / bhavcopy (automated)** | Stock prices | ToU: "User is prohibited to conduct any systematic or automated data collection activities (including scraping…)" (`research-equity-data-nse.md`) | **BLOCKED** | — |
| **NSE bhavcopy, manual browser download, parsed locally** | Stock prices, local only | The ToU has "Unless the information or Content is available for download, not to aggregate, copy or duplicate…" and "stored in an electronic retrieval system" clauses (verify NSE-6, EQ-alt missing item) | **NOT VERIFIED (ambiguous)**. User decision; local mode only | Local only, never Turso |
| **NSE Indices TRI CSVs** (niftyindices.com) | Long index history for stress tables and backtests | "personal, non-commercial use only"; "No material from the Site may be copied, modified, reproduced, republished, uploaded, transmitted … without prior written permission" (verify MOM-8) | **BLOCKED for upload to hosted mode; NOT VERIFIED for local manual import** (the copy clause applies) | The stress table (§5) cites the *published companion computation* as a rule-table constant, not a stored series |
| **Upstox / Angel One SmartAPI** (user's own account) | Daily stock and ETF candles | Upstox: "All trading + data APIs are free of cost" (upstox.com/trading-api, verify EVQ-1). Upstox staff: "Currently, we only adjust for bonuses and splits" (community.upstox.com/t/3548, verify EQ-6). Developer terms on storage and backtesting are **unread** | **REQUIRES CONFIGURATION + NOT VERIFIED**; local mode only (a conservative policy choice, verify EQ-7) | Frozen snapshot plus diff on every download, because split adjustment rescales history (verify BT-7) |
| **Zerodha Kite Connect** | Stock candles | ₹500/month; terms forbid "Scrape, build databases, or otherwise create permanent copies" and ban "virtual/mock trading apps" (verify NSE-8, R12) | **BLOCKED** (paid key, and the database clause conflicts with a backtest store) | — |
| **yfinance / jugaad-data / nsepython / nsetools** | — | Yahoo bans automated collection; the NSE libraries scrape NSE (verify R2: PKScreener differs, but is still unusable) | **BLOCKED** | — |
| **IIMA factor library** | Optional "factor evidence" panel | Citation requested, no licence stated (`research-evidence-value-quality.md`) | REQUIRES CONFIGURATION (manual import, personal use) | Pin the release by hash; assert the HML sign on import |

### 2.2 Provenance record (every stored fact)

`fact_id, source_id, licence_class (PERSONAL_USE_ONLY | PUBLIC_GOVT | LICENSED | USER_OWNED | UNKNOWN), retrieved_at (service
layer), known_time, as_of, content_hash, status (VERIFIED | NOT VERIFIED | REQUIRES CONFIGURATION | BLOCKED)`. This extends the
existing registry schema (`source-registry.md`: `licence_class` already exists). A fact with `UNKNOWN` licence or `BLOCKED` status
cannot enter `engine/`. The service layer refuses it, and gate G1 refuses it again.

### 2.3 Point-in-time and mutable vendors

- Store data **bitemporally** (`as_of`, `known_time`), as `research-backtest-method.md` §3.1 specifies.
- Any vendor series that can be restated (broker candles after a split) is stored as a **frozen snapshot** with a content hash. The
  next download is diffed against it; a mismatch opens a `restatement` record, and backtests keep using the frozen snapshot named in
  their manifest (verify BT-7, verify references "vendor history is mutable").

---

## 3. Universe

| Universe | Contents | Why | Status |
|---|---|---|---|
| **U0 Holdings** | Every instrument in the user's CAS or manual holdings | Risk is measured on what the user owns | Buildable now |
| **U1 Core growth universe** | A capped, user-approved list with one Direct-Growth scheme per broad exposure: Nifty 50, Nifty Next 50, Nifty 500 or total market, Midcap 150, Smallcap 250, gold, overnight, liquid, a gilt or constant-maturity fund, an arbitrage fund. Cap: **≤ 40 schemes** (PARAMETER). History is auto-tracked | Gives the risk engine and backtests series without manual backfill (audit-journey C5 Fix C). The cap is the AMFI "significant portion" minimisation; whether it is acceptable is **user decision D3** | Buildable now |
| **U2 Category peers** | Latest NAVAll row of every scheme in the same SEBI category as a holding (no history kept) | Cost comparator and the "same exposure at lower cost" card | Buildable now (in memory) |
| **U3 Disclosed-risk sleeves** | Momentum, quality and low-volatility index funds (Nifty200 Momentum 30, Midcap150 Momentum 50, Nifty200 Quality 30, Nifty100 Low Vol 30 trackers) | Shown only as *candidates with risk disclosure*, never as timing signals (`research-evidence-momentum.md` S-C). Quality funds have only about 13–25 months of live NAV (verify FD), so their statistics abstain on history length | User opt-in |
| **U4 Stocks and ETFs on an exchange** | — | No lawful automated data in hosted mode | **BLOCKED** (hosted), REQUIRES CONFIGURATION + NOT VERIFIED (local, broker API) |

**Classification fixes needed before U1 works** (`audit-journey.md` §2.2, measured on today's file, VERIFIED):
- 812 of 1,779 in-scope schemes have tax class UNKNOWN. That includes the 74 "Index Funds - Equity Funds" schemes, which are a plain
  false negative in `mf_tax_class_from_category` (`engine/candidates.py` around line 843). Fix A: classify that label as equity, and
  add a cited name-pattern table for "Other Scheme - Index Funds" (Nifty/Sensex/Midcap/Smallcap → equity; Gilt/SDL/G-Sec/Bharat
  Bond/CRISIL IBX → debt), flagged `TAX_CLASS_INFERRED_FROM_NAME`.
- Only 93 schemes have a known exit load. For U1 index funds, the exit load comes from (a) CAS transactions where a load was charged,
  (b) an uploaded SID, or (c) the user typing it once. **The "1 % within 365 days upper bound" idea is NOT VERIFIED** and must not be
  used until researched from SIDs. Until a load is known, risk-first behaviour is: any action that sells a lot inside 365 days of
  purchase abstains for that lot with `EXIT_LOAD_UNKNOWN`.
- `MIN_HISTORY_POINTS = 60` and `prune_untracked_history` stop Discovery from discovering. U1 auto-tracking resolves this for the
  core set.

---

## 4. The risk hierarchy (the heart of the design)

The engine evaluates layers in this fixed order for every goal. A layer returns `PASS`, `ACTION` (a card), `BREACH` (a card that
suppresses lower layers for that goal) or `ABSTAIN` (named missing input).

| Layer | Question | Inputs | Suppresses lower layers when |
|---|---|---|---|
| **L0 Data integrity** | Are the inputs fresh, licensed and complete? | Freshness, licence_class, manifest | Any required fact is stale, BLOCKED or missing → `ABSTAIN` for that goal |
| **L1 Liquidity** | Is the emergency fund funded? | Essential monthly expenses, months chosen, liquid reserves | Shortfall > 0 → `BREACH`: every new rupee goes to the reserve first |
| **L2 Goal-date safety** | Is money due soon held in instruments that can fall? | Goal date, holding classes | Equity or long-duration holdings inside a goal due in fewer than `h_safe` years (PARAMETER, user-set; default proposal 3 y with the cited 3-year loss rates shown) → `BREACH` |
| **L3 Loss budget** | Would a historically observed crash cost more than the user said they can bear? | ₹ loss budget, stress table, holdings | Stress loss > budget → `BREACH` |
| **L4 Concentration and default limits** | Is too much in one scheme, AMC, sector, issuer or bank? | Holdings, limits | Over a limit → `ACTION` (not suppressing) |
| **L5 Policy target and bands** | Has the allocation drifted past the band? | Target per goal, band | Drift > band at a review date → `ACTION` |
| **L6 Tax and cost** | Is there a free or cheap improvement? | Lots, FY gains, slab, BER | Always `ACTION` or `PASS`, never suppressing |
| **L7 Validated signal tilts** | Does a gate-passed signal ask for a tilt? | Signal registry | Empty at launch: every entry is ABSTAIN |
| **L8 Information** | Context: goal funded %, real returns, data health | — | — |

**Why this order.** Each layer protects against a larger and less recoverable loss than the one below it. Forced selling in an
emergency (L1) or a goal due in a crash (L2) cause permanent loss. A panic sale past the loss budget (L3) locks one in. Concentration
(L4) risks single-point failure. Drift (L5) is slow. Tax and cost (L6) are small but certain. Signal tilts (L7) are uncertain by
nature, so they come last.

---

## 5. Exact formulas (Decimal; every parameter fixed in advance)

All functions are pure. Money is `Decimal` under `engine_context()` (`engine/money.py`). Percentages are fractions. Rounding of
caps is `ROUND_FLOOR` to a 0.01 grid (a 1 percentage-point step), so a cap never rounds up.

### 5.1 L1 Emergency-fund gate — `risk.emergency_gate@1`

```
target_reserve   = months × essential_monthly_expenses                         (both user inputs; months default range 3–6 shown
                                                                                 with the Investor.gov citation, labelled as US-
                                                                                 regulator guidance; SEBI attribution NOT VERIFIED)
liquid_reserves  = savings + sweep_FD + Σ_overnight/liquid MF (MV − exit_load_if_redeemed_today)
shortfall        = max(0, target_reserve − liquid_reserves)
```

- ELSS and other lock-ins count as **zero** liquidity (existing liquidity ladder, `portfolio._ladder`).
- DICGC: balances above ₹5,00,000 per bank "in the same right and same capacity" are flagged; NBFC and corporate FDs are not covered
  (https://www.dicgc.org.in/FAQs, [P] in `research-evidence-allocation.md` §8). The existing `engine/deposits.dicgc_coverage` is
  reused.
- Missing expenses or months → `ABSTAIN(emergency_inputs_missing)`. Growth views still render, under a banner.

### 5.2 L3 Stress table — `rules/risk/stress_drawdowns.yaml`

A versioned rule table. Each row is a **historical worst observed peak-to-trough fall** with its source. It is not a forecast; the
card says "the worst fall in the available history of X was Y". Values:

| Risk class | Stress `s` | Recovery (peak→recovery, years) | Source (rule-table citation) | Status |
|---|---|---|---|---|
| EQ_LARGE (large-cap, Nifty 50 / Sensex index funds) | 0.595 | 3.8 (2000 episode); 2.7 (2008) | Nifty 50 TRI 2008 −59.5 %; `return-target-feasibility.md` §2.4 [C] | VERIFIED-computed (companion) |
| EQ_BROAD (flexi, multi, focused, value, contra, ELSS, Nifty 500 / total market) | 0.670 | 6.2 | Nifty 500 TRI 2000–01 −67.0 %; 2008 episode recovered 27-Mar-2014 | same |
| EQ_MID | 0.729 | 6.4 | Midcap 150 TRI 2008 −72.9 % (pre-2016 history back-calculated) | same; back-calculation flag |
| EQ_SMALL | 0.756 | 6.4 | Smallcap 250 TRI 2008 −75.6 % (back-calculated) | same; flag |
| EQ_FACTOR (momentum and other strategy indices) | 0.73 | NOT VERIFIED | NSE whitepaper Apr-2026: "68%, 73%, and 70%" ([P] in `research-evidence-allocation.md` §6) | VERIFIED quote; back-calculated history |
| EQ_SECTOR_THEMATIC | 0.928 | not recovered | Nifty Realty TRI −92.8 %, "Not recovered" (`return-target-feasibility.md` §2.5 [C]) | same |
| GOLD | 0.298 | NOT VERIFIED | Kotak Gold ETF NAV −29.8 % (2013–15) [C], **computed from an unofficial AMFI mirror** (verify EA "missing") | **NOT VERIFIED until recomputed in-app from AMFI NAV history** (WP A21) |
| HYBRID (any) | treated as EQ_BROAD × 1.0 | — | Conservative. A category equity-share table from the SEBI categorisation circular would refine it; **not cited yet** | PARAMETER (conservative) |
| DEBT_MTM (MF with duration) | `D_mod × Δy + D_spread × Δs` with Δy = 0.02, Δs = 0.03 for AA-and-below, 0.01 for AAA | — | Formula and shock sizes from `docs/finance/risk-methodology.md` §7.5 scenario table | Formula VERIFIED (repo); shocks are PARAMETERs. Missing duration → `ABSTAIN(duration_missing)` for that holding |
| CASH_LIKE (savings, overnight; FD and T-bill held to maturity) | 0 market stress | — | No MTM (risk-methodology §7.4) | Default risk is handled in L4, not here |
| STOCK (single company, if U4 is ever enabled) | 1.00 | — | Total loss is possible for a single company; no lawful survivorship data exists to bound it | PARAMETER (deliberately maximal) |

Rule: **all equity classes are added with correlation 1** (no diversification credit between equity sleeves). That is conservative
by construction, and avoids estimating a correlation the data cannot support.

**Effective sample caveat (shown on every card):** about 26–31 years of index history give only about 2 independent 10-year windows
(`research-evidence-allocation.md` §2). The worst observed fall is not the worst possible fall; the card says so in those words.
Pre-1995 Sensex history exists (verify EA-1) but is not in the table because it is price-only and was not computed.

### 5.3 L3 Loss budget and the equity cap — `risk.loss_budget@1`

Inputs per goal `g` (user-entered, mandatory for any goal with equity): `B_g` (₹ largest fall they would sit through without
selling) and `T_g` (longest months they would wait to recover). The existing `RankingRequest.loss_budget` (a fraction,
`engine/ranking.py` line 115) is derived as `B_g / V_g`.

```
stress_loss_g   = Σ_i  MV_i × s(class_i)                            (debt rows use the DEBT_MTM formula)
breach_g        = stress_loss_g > B_g

# Maximum equity share for a goal, holding the non-equity sleeve mix fixed:
b               = B_g / V_g
s_e             = MV-weighted stress of the goal's equity sleeves  (or of the policy's equity mix when the goal is empty)
s_d             = MV-weighted stress of the goal's non-equity sleeves
if b < s_d:      ABSTAIN(budget_below_non_equity_stress)           (even 0 % equity breaches the budget)
e_cap_g         = floor_to_0.01( min( policy_cap(h_g, objective_g),  (b − s_d) / (s_e − s_d) ) )
```

**Fictional worked example (not the user's numbers).** `V = ₹10,00,000`, `B = ₹2,50,000` (b = 0.25). Equity sleeve all EQ_BROAD
(s_e = 0.670). The debt sleeve is a fictional fund with D_mod = 1.0 and AAA paper: s_d = 1.0 × 0.02 + 1.0 × 0.01 = 0.03.
`e_cap = (0.25 − 0.03) / (0.670 − 0.03) = 0.34375 → 0.34` (34 %). The card reads: "With your ₹2,50,000 loss limit, at most 34 % of
this goal can be in broad Indian equity. In the worst fall in the available history (Nifty 500 TRI, −67.0 %, 2000–01), 34 % in
equity would have lost about ₹2,27,800 plus about ₹19,800 on the debt sleeve under the rate-and-spread scenario."

**Recovery check:** if `T_g` (months) is less than the class's peak→recovery duration in the stress table, the card adds: "In the
worst episode, recovery took 6.2 years; your limit is 3 years." This is a historical fact, not a prediction.

**What happens on breach.** The engine never says "sell now". It computes the smallest move that restores the budget, in this order:
(1) redirect new SIP and lump sums to non-equity sleeves (zero tax); (2) if the user enables it, the FIFO sales of equity units with
the lowest tax and exit-load cost per rupee across schemes and folios (lots *within* a scheme or folio cannot be picked: FIFO); (3)
show the ₹ tax and load of each step. The card is worded as "your loss limit is exceeded because your equity grew"; this is the
risk-first equivalent of a "sell signal" and it rests on arithmetic, not timing.

### 5.4 L2 Goal-date safety — `risk.goal_date@1`

```
years_to_goal = year_fraction(as_of, goal_date)    (existing engine/dates.py)
for each holding mapped to the goal:
  if years_to_goal < h_safe and class ∈ EQUITY_CLASSES ∪ {GOLD}:     → BREACH(equity_inside_safe_window)
  if class == DEBT_MTM and macaulay_duration_years > years_to_goal:    → ACTION(duration_exceeds_horizon)
```

`h_safe` is a PARAMETER set by the user; the card shows the cited share of negative 3-year windows from the feasibility engine for
the relevant index to inform the choice. The duration rule is mechanical (ICI: "4-year duration means about −4 % for +1 pp in
rates", via `research-evidence-mf.md` §8, VERIFIED-SECONDARY).

### 5.5 L4 Limits — `risk.limits@1`

| Limit | Formula | Default | Status |
|---|---|---|---|
| Single scheme | `MV_scheme / V_total ≤ c_scheme` | PARAMETER, user-set | — |
| Single AMC | `Σ MV_amc / V_total ≤ c_amc` | PARAMETER | Reflects AMC operational risk; no cited default |
| Sector or thematic | `Σ MV_sector / V_total ≤ c_theme` | PARAMETER; the card shows Realty −92.8 % and PSU Bank 12.8-year recovery from the stress table | — |
| Factor sleeve (U3) | `Σ MV_factor / V_equity ≤ c_factor` | PARAMETER (user decision D9) | Momentum 68–73 % drawdowns and −19.47 pp (2009) / −14.13 pp (2025) relative years disclosed |
| Bank deposits | `Σ deposit_bank > ₹5,00,000` | Statutory cover limit | VERIFIED [P] (DICGC) |
| Uninsured single issuer (NBFC/corporate FD, bond) | `exposure_issuer / V_total ≤ c_issuer` | PARAMETER | Recovery rate is NOT VERIFIED, so no loss number is shown; only the exposure |
| HHI | existing HHI | display | existing |

### 5.6 L5 Target allocation and bands — `policy.rebalance@1`

- **Target per goal** comes from `rules/risk/allocation_policy.yaml`. That table is keyed by horizon band and objective. Every value
  is a **user decision recorded with a date**; the engine never invents it (audit-journey C2). Each target is then capped:
  `w_equity_target = min(policy_value, e_cap_g)`.
- **Band:** absolute ±5 percentage points by default, with annual review. This is Vanguard's "annual or semiannual monitoring, with
  rebalancing at 5% thresholds", read in the **Nov-2015 edition** (Zilbering, Jaconetti, Kinniry; 1926–2014 data), not the 2010
  edition (verify EA-6). It is US evidence; transfer to India is NOT VERIFIED. Label: PARAMETER with a cited default.
- **Trigger:** `|w_actual − w_target| > band` at the user's review date. Out-of-cycle drift is *shown* daily but only triggers a
  card at review dates, except when L3 breaches.
- **Execution plan** (`actions.rebalance@1`), in order:
  1. Redirect upcoming SIPs and lump sums to underweight sleeves (computed for the next N contributions until drift < band/2).
  2. If drift remains and the user allows sales: choose sell sources across *schemes and folios* by
     `cost_per_rupee = (tax(FIFO lots consumed) + exit_load(FIFO lots consumed)) / amount_sold`, ascending; never sell lots inside an
     exit-load window unless the user allows it; show STCG and LTCG separately; use the remaining ₹1.25 lakh exemption first.
  3. Report the residual drift after the plan and the ₹ cost of every step.

### 5.7 Next-rupee planner — `actions.next_rupee@1` (the most-used card)

For a contribution `C` (the next SIP total or a lump sum):

```
1. a1 = min(C, emergency_shortfall)                        → overnight/liquid sleeve
2. for goals in user priority order:
     need_g = max(0, w_target_g × V_g_after − MV_g_sleeve) per sleeve, with w_target capped by e_cap_g
     allocate the remaining C pro rata to need_g, sleeve by sleeve
3. any remainder → the goal with the largest funded-% gap (ties: earliest goal date)
4. within a sleeve: pick the U1 scheme already held; else the U1 scheme with the lowest BER if BER is known; else ABSTAIN on the
   choice and show only the sleeve amount
```

No forecast is involved; it is allocation arithmetic. Stamp duty 0.005 % on purchase is applied (`engine/costs.stamp_duty`).

### 5.8 L6 Tax and cost actions

| Action | Formula | Abstains when |
|---|---|---|
| **LTCG harvest** `tax.ltcg_harvest@1` | `E_rem = 125000 − realised_LTCG_FY − harvest_already_done`. Walk FIFO lots older than 12 months from the oldest; accumulate units until cumulative gain = `E_rem`; stop at the first lot younger than 12 months (FIFO blocks skipping it). Deferred tax shown = `harvested_gain × 0.125 × (1 + cess)` with cess from the rule table. Costs shown: STT 0.001 % on redemption, stamp 0.005 % on rebuy, exit load on the lots consumed, and one NAV day out of the market (described, not priced) | Slab, residential status, regime or realised gains unknown; old regime or non-resident (not modelled); any FIFO lot ahead of the target lots is short-term |
| **STCG wait date** `tax.lt_date@1` | `date_long_term = acquisition_date + 12 months` per lot; "selling lot k before D costs ₹(gain × (0.20 − 0.125))" | Lots unknown |
| **Regular → Direct** `cost.reg_to_direct@1` | `annual_saving = MV × (BER_reg − BER_dir)`; `switch_cost = exit_load(FIFO) + tax(FIFO, regime, E_rem) + stamp(0.005 %)`; `breakeven_years = switch_cost / annual_saving` (first-order, as `research-evidence-mf.md` §4.2). Plan-switch load varies by AMC → per scheme REQUIRES CONFIGURATION | BER unknown (TER source is a user decision), exit-load wording unknown |
| **Same exposure, lower cost** `cost.index_alternative@1` | BER gap in basis points vs the cheapest U1 fund on the same index | BER unknown |
| **Persistent underperformer review** `info.review_flag@1` | Fund net 3 y **and** 5 y return below the cheapest index fund on its benchmark index, from AMFI NAVs | Fewer than 5 y of NAVs; benchmark mapping missing. **Wording: "review", never "exit"**, because loser persistence is not established as an exit rule (verify MF-2) |

---

## 6. Signal rules (research track) and how they are bounded

### 6.1 Registry

`signals/<id>@<version>.yaml` (committed; contains rules only, never results on named securities):

```yaml
id: S-E
version: 1
family: trend_timing
status: PRE_REGISTERED            # PRE_REGISTERED | ABSTAIN | NO_SIGNAL | ACCEPTED | SUSPENDED | RETIRED
universe: [core:nifty50_index_direct, core:nifty500_index_direct]   # U1 ids
observation: month_end_nav
rule: "S_m = 1 if C_m > mean(C_{m-9..m}) else 0"
execution: "first business day of month m+1, MF cut-off, next-day NAV, 3 working-day cash gap on switches"
out_asset: core:liquid_direct
tilt_bounds: {min: -0.20, max: 0.0}     # PARAMETER: may only REDUCE equity, at most 20 pp, never below policy floor
costs: rules/costs (stamp 0.005 %, STT 0.001 %, exit load per lot)
tax: lot-level FIFO, regime in force at each date, exemption assumed used, highest slab (conservative bound)
benchmark: buy-and-hold same fund, liquidated at end, after tax
splits: {walk_forward_from: <fixed before first run>, vault: last 20 % or ≥ 3 y}
variants_counted: 1
gates: G1..G12
```

Pre-registered families (specs frozen from `research-evidence-momentum.md` §6; data = AMFI NAVs of U1 funds, not TRI):

| ID | Rule | Expected outcome (stated in advance) |
|---|---|---|
| S-E | 10-month SMA trend filter, index fund ↔ liquid fund | Fail G5/G9 (Zakamulin, Huang et al. 2020, Mitra 2011 predict no edge after costs; Zakamulin finds "substantially lower long-term capital growth", verify MOM missing) |
| S-D | 12-1 absolute momentum vs T-bill | Fail G9 |
| S-F | Dual momentum across Nifty 500 index fund, gold ETF NAV, gilt fund | Fail G5 (about 19 annual decisions since 2007) |
| S-G | Drawdown top-up: extra new cash into an index fund when it is ≥ X % below its high (cash flow only, no sales) | Unknown; X is pre-registered at a single value, chosen before data is seen |

There are **no** stock-level, factor-timing, valuation-band (BLOCKED: P/E data is from NSE Indices), category-rotation or
"winner fund" signals in the registry. Each is ABSTAIN with its reason (§12).

### 6.2 Gates (fail closed)

The engine implements G1–G12 from `research-backtest-method.md` §10, with these risk-first additions:

- **G6 is evaluated at the conservative tax bound**: highest slab, LTCG exemption already used, all positions liquidated at the end.
  Before 2024-04-01 the repo has no equity tax rows, and it abstains on lots bought on or before 31-Jan-2018 (verify BT-3). So **every
  backtest window that starts before 2024 ends in `ABSTAIN(tax_rules_missing)`** until historical rows (pre-2018 exemption; 2018–24
  10 %/15 % with grandfathering; ₹1.25 lakh for 1-Apr to 22-Jul-2024 per the repo yaml) are added from primary sources and reviewed
  (WP A13).
- **G13 (new) Risk-budget compatibility:** the strategy's own worst historical drawdown, applied to the user's bucket at the maximum
  tilt, must not breach L3. A signal that raises drawdown above the loss budget is `NO_SIGNAL(exceeds_loss_budget)` even if it has
  an edge.
- **G14 (new) Drawdown non-inferiority:** max drawdown of the strategy ≤ the benchmark's max drawdown + 0 pp over the OOS window.
  A risk-first engine does not accept higher crash risk for higher mean.
- **Honest power statement (shown on the Signals page):** with about 12 years or less of OOS data after the vault, t ≥ 3 needs an
  annualised Sharpe of about 0.87, and 80 % power at Sharpe 0.5 needs about 298 months (verify BT-9, verify backtest "joint power").
  The gates are close to unpassable; this is intended.
- **Gates implemented later (fail closed until built):** PBO/CSCV and Hansen SPA. A gate that is not implemented returns
  `ABSTAIN(gate_not_implemented)`, so deferring them can never let a signal through.

### 6.3 How a signal moves money (only after ACCEPTED)

```
w_policy        = target from allocation_policy (already capped by e_cap)
Δw              = signal output, clamped to tilt_bounds
w_star          = clamp(w_policy + Δw, policy_floor, min(policy_ceiling, e_cap_g))
execution       = next_rupee planner with w_star; a sale is allowed only if
                  validated_after_tax_edge_per_rupee × min(horizon, signal_hold) > (tax + exit_load + stamp + STT) per rupee
                  using the lower 80 % bound of the OOS edge, not the median
```

The lower layers (L0–L4) are re-evaluated after the tilt. If any breaches, the tilt is dropped.

### 6.4 Live decay and the outcome ledger

Every emitted card that names an instrument is stored in `outcome_ledger` (engine version, snapshot id, rule, as-of). Realised NAVs
later score it. G12: if the rolling 24-period realised edge is below 0 and below the lower 80 % bound, the signal auto-reverts to
`SUSPENDED(decay)`. Policy cards (rebalance, emergency) are logged too, so the user can see, after the fact, what following the
rules did.

### 6.5 Disclosed-risk sleeves (not signals)

A momentum, quality or low-volatility fund is shown as a *candidate* in the ranking (ADR-0005) with mandatory disclosures: backtest
vs live split (Nifty200 Momentum 30 launched 25-Aug-2020; Midcap150 Momentum 50 launched 16-Aug-2022, verify EA), maximum drawdown
68–73 %, the worst relative years, churn, and that the live-period excess (+2.79 pp/yr over 5 years) is statistically
indistinguishable from zero (t ≈ 0.64, verify MOM-2). The NSE since-inception CAGRs (19.19 %/15.08 %) do not reconcile with NSE's own
calendar-year table (verify MOM-9), so **they are not displayed**; only figures the app recomputes from AMFI NAVs are shown. Size is
capped by L4 `c_factor` and by L3.

### 6.6 Stocks (U4): risk-first spec, gated

Status: hosted **BLOCKED**; local **REQUIRES CONFIGURATION + NOT VERIFIED** (broker terms unread, NSE "simulation" clause ambiguous,
verify NSE-2). If the user configures a broker in local mode (decision D2):

- **Sleeve cap:** `Σ MV_stocks ≤ c_stock × V_equity` (PARAMETER). The stock sleeve counts in L3 at `s = 1.00` per position.
- **Per-position size:** `MV_position ≤ min(c_single × V_total, R_position)`, where `R_position` is the ₹ the user accepts losing
  entirely on one company. With s = 1.00, the size limit equals the loss limit.
- **Total stock loss budget:** `Σ MV_stocks ≤ B_stocks`, carved out of the goal's B.
- **What is shown:** holdings, sizes against limits, corporate-action-adjusted price history (frozen snapshot), cost of a round trip
  (fixture C-1: ₹237.82 on ₹1,00,000, 0.238 %; VERIFIED-SECONDARY from the Zerodha page), and the STCG/LTCG date per lot.
- **What is not shown:** any buy or sell signal. Single-stock signals fail G2 (no survivorship-free, point-in-time data; Upstox
  "Expired Instruments" covers only derivatives, verify EQ-6) and G3 (dividends and demergers unadjusted). `ABSTAIN(no_lawful_
  survivorship_free_data)`.
- **Order placement:** never from hosted mode (no static IP on Vercel Hobby; NSE "A static IP can only be mapped to one client at a
  time", verify R missing). Local-mode order automation is NOT VERIFIED (verify R5) and out of scope.

---

## 7. From engine output to plain-English action, with provenance

### 7.1 ActionCard schema (engine dataclass, frozen)

```
ActionCard {
  card_id            sha256(kind | goal_id | instrument_ids | snapshot_id)
  kind               EMERGENCY_SHORTFALL | GOAL_DATE_BREACH | LOSS_BUDGET_BREACH | LIMIT_BREACH | REBALANCE_DUE |
                     NEXT_RUPEE | LTCG_HARVEST | LT_DATE | REG_TO_DIRECT | LOWER_COST_SAME_EXPOSURE | REVIEW_FLAG |
                     SIGNAL_TILT | ABSTAIN | NO_ACTION_NEEDED | DATA_ATTENTION
  layer              L0..L8
  priority           (layer, severity, ₹ at stake desc, goal priority)
  goal_id
  steps[]            {verb: REDIRECT_SIP | INVEST | REDEEM | SWITCH | WAIT_UNTIL | REVIEW, instrument_id, units?, amount,
                      folio?, lots_consumed[], cost{exit_load, stamp, stt}, tax{stcg, ltcg, cess}, net_effect}
  why                rule_id@version + parameter values + who set them and when
  numbers[]          {value, unit, fact_ids[] | formula_id, as_of}
  status             VERIFIED | NOT VERIFIED | REQUIRES CONFIGURATION | BLOCKED
  abstentions[]      {code, missing_input, how_to_fix}
  engine_version, rules_version, input_manifest_hash, snapshot_id
}
```

### 7.2 Templates (`rules/action_templates.yaml`; no LLM in the numeric path)

Each template is a fixed string with typed slots filled by the engine. The compliance guard checks the rendered text. Examples with
**fictional** values:

| Kind | Rendered text |
|---|---|
| EMERGENCY_SHORTFALL | "Your emergency reserve is ₹1,20,000 short of the 6 months you chose. Rule `risk.emergency_gate@1`: put the next ₹1,20,000 of contributions into your overnight fund before anything else." |
| LOSS_BUDGET_BREACH | "Your loss limit for *House 2031* is ₹3,00,000. In the worst fall in the available history of the funds you hold, this goal would have lost ₹3,46,000. Your rule says: send the next ₹1,60,000 of SIPs to the debt sleeve. No sale is needed." |
| REBALANCE_DUE | "Annual review: equity is 71 % against your 60 % target (band ±5 pp). Redirecting 4 months of SIPs closes most of it. Selling instead would cost ₹6,240 in tax and ₹0 in exit load." |
| LTCG_HARVEST | "₹82,000 of your ₹1,25,000 long-term gains allowance is unused this year. Redeeming 1,412.3 units of *Fund A* (oldest lots, all over 12 months) and buying back uses it, deferring about ₹10,660 of tax. Exit load ₹0; stamp duty ₹4." |
| ABSTAIN | "No trend or timing signal is active. Reason: no rule has passed the evidence gates (S-E: needs 132 months of out-of-sample data, has 0). This is the expected result, not an error." |
| NO_ACTION_NEEDED | "All your rules are within limits today (data as of 14-Oct NAV)." |

Every number in a card links to its Evidence page (`/evidence/:obsId`, existing) or formula page (Methodology, existing).

### 7.3 Vocabulary

Following `research-regulation.md` §8.2:

- Policy cards use **"your rule says"**, plus the verbs redirect, invest, redeem, switch, wait and review. Never "buy now", "strong
  buy", "target price" or "stop-loss".
- An accepted signal (if one ever exists) uses **"entry condition met" / "exit condition met"** next to the rule id, version, backtest
  card and as-of date. A BUY/SELL badge appears only if the owner opts in (decision D1). The compliance guard keeps BLOCKing those
  phrases on every export, share and unauthenticated surface.
- Every page with cards carries: "Personal decision-support tool. Output of rules you configured. Not investment advice or research;
  not registered with SEBI."
- If the optional LLM paraphrases a card, the paraphrase is labelled "AI-generated text", cannot contain digits (an existing
  guard), and the engine text stays visible.

---

## 8. Portfolio integration

| Element | Design |
|---|---|
| **Goals** | New `goals` table: name, target ₹, date, priority, objective (A–E, existing), `B_g`, `T_g`, `h_safe`, policy version |
| **Mapping** | `holding_goal_map` (instrument + folio → goal, with a split fraction). Unmapped holdings go into an "Unassigned" goal that still gets L1/L3/L4 checks at portfolio level |
| **Risk profile** | `risk_profile`: essential expenses, emergency months, tax slab, regime, residential status, LTCG used this FY (or "assume used" as the conservative default, labelled) |
| **Policy** | `policy_versions`: the user's targets, bands, limits, `c_*` parameters, each row with the decision date |
| **Supervisor** | `supervisor/manifest.py` gains a per-goal manifest: required facts for each layer; a missing fact → abstain for that layer and goal only |
| **Lots** | Reuse `services/portfolio.fifo_positions` (FIFO lots) and `engine/tax.compute_tax`. Lots are **per folio**; FIFO applies per folio/demat account (CBDT Circular 768 for demat; RTA practice for folios, NOT VERIFIED primary) |
| **CAS gaps to close** | Accept Regular-plan ISINs (known-limitations, CAS gap 1); capture exit load charged per redemption as a USER_OWNED fact |
| **Decision log** | `decisions_log`: the user marks a card "done", "not now" or "disagree", with an optional note. This is the RA-style rationale record the regulation report recommends, and it feeds the outcome ledger |

---

## 9. Automation (cron) and alerts

### 9.1 Jobs (Vercel Hobby: at most once a day each, fires anywhere in the named UTC hour, 300 s limit, no retries, may be skipped or duplicated; VERIFIED in `research-automation-infra.md` §1.1)

| Job | UTC hour → IST window | Work (each step ≤ 90 s, resumable) |
|---|---|---|
| J1 `navall` | 01 → 06:30–07:29 | Fetch NAVAll; upsert held, watched and U1 rows only |
| J2 `navall-continue` | 02 → 07:30–08:29 | Finish an open run; RBI RSS poll; MoSPI CPI check (monthly no-op otherwise) |
| J3 `history` | 03 → 08:30–09:29 | Gap-fill history for U0 + U1 only; refresh `series_grid` for changed schemes |
| J4 `snapshot` | 05 → 10:30–11:29 | Late FoF/overseas NAVs (AMFI T+1 10:00 IST deadline), then the risk engine over all goals → `signal_snapshots` (content-addressed; ABSTAIN stored too) → outbox |
| J5 `watchdog` | 13 → 18:30–19:29 | If today's snapshot is missing or a dataset is stale, queue one "pipeline needs attention" ping |

Business days are decided inside the job from the calendar, not in the cron expression. The XBOM/NSE calendar oracles end on
2026-12-31 (verify references), so a task to load the 2027 NSE holiday circular by hand is part of WP B06.

### 9.2 Security exception (new ADR-0014)

`GET|POST /api/cron/{job}` only, with `job` from a fixed enum and no parameters. The `$VERCEL_URL` host is accepted on this route
only. `Authorization: Bearer CRON_SECRET` (≥ 32 chars, different from the access token, compared with `hmac.compare_digest`).
Production only. A wrong secret is rate-limited like login. The response carries codes and counts only. A test asserts that every
other route still returns 400 on the deployment host. **Untested on this project:** whether the cron request's Host is the
deployment URL, and whether Vercel Deployment Protection intercepts it (verify AUTO missing items). The first live run checks both.

### 9.3 Idempotency, with the verify-file fixes

- Claim: `INSERT … ON CONFLICT(job, run_key) DO UPDATE SET attempts = attempts + 1, state = 'running', started_at = :now WHERE
  cron_runs.state = 'failed' OR (cron_runs.state = 'running' AND cron_runs.started_at < :stale_before)`. This fixes the defect that a
  killed run blocked its key forever (verify AUTO-3). `:now` and `:stale_before` come from the service layer.
- `run_key` is **always the data as-of date** (the AMFI NAV date the job targets), never the wall-clock date. J1 may fetch before it
  can claim; duplicate fetches are accepted because all writes are idempotent upserts.
- The outbox reaper marks `sending` rows older than the lease TTL as `failed` and never resends them. Losing a ping is the safe
  direction.

### 9.4 Alerts and notifications

- **In-app first:** the Today page shows the latest snapshot. If no channel is configured, nothing breaks.
- **Push content is a ping only:** "IIP: daily report ready (data as of 14-Oct). Open the app." There are no amounts, scheme names,
  verbs or prices. A test enforces the template with sentinel amounts.
- **Channel choice is decision D7.** The wave-1 reports conflict: automation-infra recommends a Telegram bot for v1, while
  regulation §8.1.3 says "No push to third-party channels (Telegram…)". Risk-first resolution: the default is `off`; Web Push
  (VAPID, payload end-to-end encrypted per RFC 8291) is the preferred channel; Telegram is allowed only as a content-free ping to the
  owner's own chat, which carries nothing the regulation note is worried about. ntfy.sh public topics and Gmail app passwords are
  rejected (spoofable or credential-heavy).
- **Ping only on change:** the outbox gets a row only when the set of `card_id`s at layers L1–L5 differs from the previous snapshot,
  or when the watchdog fires. A quiet day sends nothing.

---

## 10. Performance fixes (prerequisite; from the two performance audits)

| # | Fix | Evidence | Expected effect |
|---|---|---|---|
| F1 | Create a Turso database in `bom1` and migrate (store `database-blue-flower` is in `iad1`) | ~0.40 s per statement, VERIFIED | Large; per-statement latency after the move is NOT VERIFIED and must be measured |
| F2 | Batch discovery: one query per kind, not one COUNT per scheme (1,791 statements → 504 at 300 s); a 60 s time budget with partial-result marking | VERIFIED | Discovery returns; no instance kill |
| F3 | Session lookup off the event loop (threadpool); update `last_seen` at most every 5 minutes (PARAMETER) | 2 statements per request, VERIFIED | −0.8 s per API call on today's region |
| F4 | Serve the built UI from Vercel's CDN (`public/`); copy security headers into `vercel.json`; long cache on hashed assets | `max-age=0`, MISS on repeat, 9 cold starts in ~90 s, VERIFIED | Removes the parallel cold starts |
| F5 | Data-health: one query for all sources; instrument detail: one query, not 8 serial ones | VERIFIED | 10.5 s → about 1 statement's latency |
| F6 | Read-only startup; import scipy lazily in the 4 engine modules that import it at top level (`fixed_income.py`, `returns.py`, `forecasting/validation.py`, `stats/metrics.py`) | Cold start ~6 s, VERIFIED install; split estimated | Faster cold start; bundle size under 225 MB NOT VERIFIED |
| F7 | `GET /api/instruments/{id}/summary` for names; `?from=&grid=monthly` for charts; stop downloading the full ~0.73 MB history (synthetic measurement) | VERIFIED pattern | Fewer bytes; no N+1 on Fixed income |
| F8 | `useApi` shared cache keyed by URL with a TTL; parallel landing-page requests | VERIFIED pattern | Fewer round trips |
| F9 | **`series_grid` table:** month-end NAV per U0/U1 scheme, refreshed by J3. The risk engine reads one batched query per snapshot, never raw daily history | Design | The risk snapshot fits a 90 s step |
| F10 | The risk snapshot is computed by J4 and read by the UI. **The Today page never runs the engine on page load** | Design | Today loads in about one query |

---

## 11. UX that removes manual entry

**Onboarding becomes "one upload, five questions":**

1. Upload CAS (holdings, lots, folios, Regular/Direct, exit loads charged).
2. Essential monthly expenses and emergency months.
3. Goals: name, amount, date (pre-filled suggestions "Emergency", "Long-term growth"; nothing pre-filled with numbers).
4. Loss limit per goal in ₹, shown next to the stress-table history ("the worst fall of a broad Indian index fund in the available
   history was 67 %; on ₹X that is ₹Y"). The aspiration of 20–25 % is shown afterwards, on the feasibility page, as a historical
   frequency, never as an input that raises equity.
5. Tax slab and regime, or "use the conservative assumption" (highest slab, exemption used).

**Automatic from then on:** NAVs (J1–J4), CPI (MoSPI), T-bill yields (RBI RSS), U1 history, lots (from CAS re-uploads).

**Still manual, by law or terms, made cheaper:** factsheet duration and credit mix (upload the AMC's portfolio file, parsed
deterministically), SID exit loads (paste the "Load Structure" text, strict grammar, abstain on anything else), FD card rates (paste
a table). Each manual fact shows its age, and goes stale after 45 days (risk-methodology gate table).

**Pages.** New `/` = **Today** (cards by layer; "No action needed" is a valid, explicit state). New `/goals` (goals, mapping, loss
limits, targets, bands, limits). New `/signals` (registry, each signal's gate panel and its power statement; every row ABSTAIN at
launch). The existing Discovery, Risk, Scenarios and Evidence pages stay, linked from cards.

---

## 12. What to cut, defer or refuse

| Item | Decision | Why |
|---|---|---|
| Stock buy/sell signals | **Refuse** (ABSTAIN); local risk-only stock sleeve is optional | No lawful survivorship-free data; G2/G3 cannot pass |
| Stock fundamentals scoring, F-score, PEAD, pledge-based signals | **Refuse**; regulatory-threshold disclosures only | `research-fundamentals-data.md`; NSE simulation clause |
| Valuation bands (index P/E) | **Refuse** | NSE Indices copy clause |
| Volatility targeting, stop-losses, drawdown-triggered selling | **Refuse** | Cederburg et al. 2020 real-time failure; Kaminski & Lo; no Indian test |
| Kelly sizing and the "over-betting warning" | **Cut** | The app allows no leverage, so a warning against f* ≈ 1.5 never fires; f* spans −0.11 to 3.11 |
| Mean-variance optimiser | **Refuse** | DeMiguel et al. 2009 |
| Factor timing, category rotation, "top-quartile fund" switching | **Refuse** (registry ABSTAIN) | `research-evidence-mf.md` §2, §6; verify EVQ-9 scopes this claim |
| "Probability of profit" wording | **Refuse** | ADR-0010 |
| PBO/CSCV and Hansen SPA implementation | **Defer** (fail closed) | No candidate will reach G9/G10 first |
| Historical tax rows before 2024 | **Required before any backtest verdict**; build early (A13) | G6 abstains without them |
| Web Push | **Defer to v2**; in-app first | Build cost |
| GitHub Actions watchdog | **Defer** | Public logs; switches off after 60 idle days |
| LLM explanations near cards | **Optional, off by default** | No number may come from the LLM |
| Exports of cards or signals | **Do not build**; a private-watermarked holdings export only | `research-regulation.md` §8.1 |
| Fixed-income bond quote screens (G-sec, SDL, CCIL) | **Keep as is**, no automation | BLOCKED sources |

---

## 13. Build plan: 28 work packages in three waves

Rules for agents: one git worktree per package; **a file appears in only one package per wave**; new engine modules must pass
`backend/tests/unit/test_engine_purity.py`; Python tools via `backend/.venv/bin/...`; frontend scripts via `node --run <script>`;
tests are hermetic with synthetic fixtures (no real market data committed; the repo is public). Interfaces between packages are the
dataclasses in §5 and §7.1; wave A packages code against those signatures.

### Wave A — foundations and pure engine (20 packages, all parallel)

| WP | Name | Files touched (exclusive) | Done when |
|---|---|---|---|
| A01 | Docs: ADRs and ops runbook | `docs/architecture/architecture-decision-records/0014-scheduled-jobs.md`, `0015-risk-budget-engine.md`, `0016-signal-registry-and-gates.md`, `0017-data-rights-equity-index-amfi-hosted.md`, `0000-index.md`; `docs/operations/turso-bom1-move.md`; `scripts/turso_latency_probe.py` | ADRs accepted by the user; probe prints per-statement latency |
| A02 | Discovery batching + time budget | `backend/src/iip/services/discovery.py`; `backend/tests/services/test_discovery_batching.py` | ≤ 10 statements for the universe; partial results flagged |
| A03 | Session off the event loop; `last_seen` throttle | `backend/src/iip/api/security.py`; `backend/tests/security/test_session_offloop.py` | Concurrency test passes; writes ≤ 1 per 5 min |
| A04 | Static UI via CDN + headers | `vercel.json`; `scripts/vercel-build.sh`; `app.py` (root); `backend/tests/hosted/test_static_headers.py` | Hashed assets served with immutable cache; headers unchanged |
| A05 | Core-route query fixes + summary/grid endpoints | `backend/src/iip/api/routes_core.py`; `backend/src/iip/services/instruments.py`; `backend/tests/api/test_core_batched.py` | Data-health 1 query; instrument detail ≤ 2; `/summary` and `?grid=monthly` exist |
| A06 | Read-only startup + lazy scipy | `backend/src/iip/api/app.py`; `backend/src/iip/store/db.py` (startup path only); `engine/fixed_income.py`, `engine/returns.py`, `engine/forecasting/validation.py`, `engine/stats/metrics.py` (import lines only); `backend/tests/unit/test_lazy_imports.py` | `import iip.api.app` does not import scipy; startup issues no writes |
| A07 | Frontend fetch fixes | `frontend/src/lib/useApi.ts`, `frontend/src/lib/api.ts`, `frontend/src/pages/Risk.tsx`, `Scenarios.tsx`, `FixedIncome.tsx`, `Overview.tsx`, plus their `*.test.tsx` | No full-history fetch for names; no per-row requests |
| A08 | MoSPI CPI adapter fix | `backend/src/iip/data/mospi.py`; `backend/tests/data/test_mospi_base2024.py` | Base 2012 and 2024 parse from synthetic fixtures; no credentials needed |
| A09 | RBI T-bill RSS adapter | `backend/src/iip/data/rbi_tbill.py` (new); `backend/src/iip/data/registry.py`; `backend/src/iip/data/fetch.py` (allowlist); `backend/tests/data/test_rbi_tbill.py` | Self-check `(100−P)/P × 365/days` to 4 dp; no deep link rendered |
| A10 | MF classification fix | `backend/src/iip/engine/candidates.py` (classification functions only); `backend/src/iip/rules/mf_categories.yaml`; `backend/src/iip/rules/index_name_patterns.yaml` (new); `backend/tests/unit/test_mf_classification.py` | The 74 "Index Funds - Equity Funds" classify; inferred classes flagged |
| A11 | Schema migration 0004 | `backend/src/iip/store/migrations/0004_risk_signals.sql`; `backend/tests/store/test_migration_0004.py` | Tables: goals, holding_goal_map, risk_profile, policy_versions, decisions_log, series_grid, cron_runs, signal_snapshots, notification_outbox, backtest_trials, signal_state, outcome_ledger; works on SQLite and libSQL |
| A12 | Risk and cost rule tables + loader | `backend/src/iip/rules/risk/stress_drawdowns.yaml`, `rules/risk/allocation_policy.yaml` (structure only; values REQUIRES CONFIGURATION), `rules/costs/india_equity.yaml`, `backend/src/iip/rules/loader.py`; `backend/tests/unit/test_rules_risk.py` | Every row has source, status, `effective_from`; loader rejects missing citations |
| A13 | Historical tax rows (pre-2024) | `backend/src/iip/rules/tax/india.yaml`; `docs/research/indian-instruments-and-tax.md` (fix stale ₹1 lakh at line 485); `backend/tests/unit/test_tax_history_rows.py` | Rows cite primary sources; status NOT VERIFIED until CA review; existing tax tests green |
| A14 | `engine/risk/` budget, goal-date and limits | `backend/src/iip/engine/risk/__init__.py`, `budget.py`, `limits.py` (new); `backend/tests/unit/test_risk_budget.py`, `test_risk_limits.py` | §5.1–5.5 formulas with fixtures, including the 34 % fictional example |
| A15 | `engine/actions/rebalance.py` + `next_rupee.py` | new files under `backend/src/iip/engine/actions/`; `backend/tests/unit/test_rebalance.py`, `test_next_rupee.py` | Cash-flow-first; FIFO per folio; never picks lots within a folio |
| A16 | `engine/actions/tax_actions.py` | new file; `backend/tests/unit/test_tax_actions.py` | LTCG harvest stops at the first short-term FIFO lot; break-even matches the `research-evidence-mf.md` §4.2 fixtures |
| A17 | `engine/actions/cards.py` + templates | new `cards.py`; `backend/src/iip/rules/action_templates.yaml`; `backend/tests/unit/test_cards.py` | Every number slot carries a fact or formula id; compliance phrases checked |
| A18 | `engine/backtest/` ledger, equity costs, tax lots | `backend/src/iip/engine/backtest/__init__.py`, `ledger.py`, `costs_equity.py`, `tax_lots.py`; `backend/tests/unit/test_backtest_ledger.py` | Fixture C-1 (₹237.82) and T-1 reproduce |
| A19 | `engine/backtest/stats_gates.py` | new file (stdlib `statistics.NormalDist`, no scipy); `backend/tests/unit/test_stats_gates.py` | DSR-1 (0.9004 / 0.9505), MT-1, MT-2, MT-3 reproduce; PBO and SPA return `gate_not_implemented` |
| A20 | `engine/stats/series_grid.py` | new file; `backend/tests/unit/test_series_grid.py` | Month-end grid, blended path, MDD and recovery durations; gold drawdown recomputable from AMFI NAVs |

### Wave B — services, API, cron (6 packages, parallel; after wave A merges)

| WP | Name | Files touched (exclusive) | Done when |
|---|---|---|---|
| B01 | Goals service and routes | `backend/src/iip/services/goals.py`, `backend/src/iip/api/routes_goals.py` (new), `backend/src/iip/api/routes.py` (register router); `backend/tests/api/test_goals_api.py` | CRUD + mapping + risk profile; CSRF and session as other routes |
| B02 | Risk snapshot service + supervisor manifest | `backend/src/iip/services/risk_snapshot.py` (new); `backend/src/iip/supervisor/manifest.py`; `backend/tests/services/test_risk_snapshot.py` | Byte-identical snapshot on re-run; per-goal abstention; outcome-ledger rows written |
| B03 | Cron route, claims, outbox | `backend/src/iip/api/routes_cron.py`, `backend/src/iip/services/cron.py` (new); `backend/src/iip/api/security.py` (host exception); `vercel.json` (`crons`); `backend/tests/hosted/test_cron.py` | All §9.3 tests, including stale-`running` takeover and the outbox reaper; other routes still 400 on `VERCEL_URL` |
| B04 | Notifications + vocabulary | `backend/src/iip/services/notify.py` (new); `backend/src/iip/data/fetch.py` (notify host); `backend/src/iip/rules/compliance_phrases.yaml`; `backend/src/iip/supervisor/compliance.py` (surface-aware rules); `backend/tests/security/test_notify_ping_only.py` | Default `off`; sentinel amounts never appear in a ping; BLOCK phrases kept on export surfaces |
| B05 | Backtest runner + pre-registered signals | `backend/src/iip/services/backtest_runner.py`, `backend/src/iip/engine/backtest/walkforward.py`, `backend/src/iip/engine/backtest/gates.py` (new); `signals/S-E@1.yaml`, `S-D@1.yaml`, `S-F@1.yaml`, `S-G@1.yaml`; `backend/scripts/run_backtest.py`; `backend/tests/services/test_backtest_runner.py` | Trials logged automatically; a synthetic zero-skill fixture ends in ABSTAIN/NO_SIGNAL; results are never written into the repo |
| B06 | Core universe tracking + CAS gaps + calendar | `backend/src/iip/services/ingestion.py`; `backend/src/iip/services/cas.py`; `backend/src/iip/data/parsers/amfi_navhistory.py` (if needed for grid refresh); `backend/src/iip/rules/core_universe.yaml` (user-approved list, ≤ 40); `backend/tests/services/test_core_universe.py` | U1 auto-tracked without manual backfill; Regular-plan ISINs accepted; 2027 holiday task recorded |

### Wave C — frontend (2 packages, parallel; after wave B merges)

| WP | Name | Files touched (exclusive) | Done when |
|---|---|---|---|
| C01 | Today + Signals pages, ActionCard, routing | `frontend/src/pages/Today.tsx`, `frontend/src/pages/Signals.tsx`, `frontend/src/components/ActionCard.tsx`, `frontend/src/components/GatePanel.tsx`, `frontend/src/App.tsx`, `frontend/src/lib/types-actions.ts`, plus tests | `/` is Today; "No action needed" and ABSTAIN are first-class states; every number links to evidence |
| C02 | Goals and onboarding | `frontend/src/pages/Goals.tsx`, `frontend/src/pages/Onboarding.tsx`, `frontend/src/pages/Settings.tsx` (notification channel, vocabulary opt-in), `frontend/src/lib/types-goals.ts`, plus tests | One upload and five questions; loss limit shown with stress history before any return figure |

**Totals:** 20 + 6 + 2 = **28 packages**. **Critical path:** A11 + A12 + A14 → B02 → C01. **First user-visible milestone:** after
waves A and B, the J4 snapshot produces the Today cards (L0–L6) daily. Every registry signal shows ABSTAIN with its gate panel.

---

## 14. Corrections from the verify pass that this design depends on

| Claim (wave-1 report) | Verify result | How the design uses it |
|---|---|---|
| "Redeem lowest-tax lots first" (allocation §4) | WEAKENED (EA-6): FIFO per scheme/folio | Sales choose between schemes and folios, never between lots in one folio |
| Vanguard "July 2010, 1926–2009" | WEAKENED: Nov-2015 edition | The band default is cited to the 2015 edition |
| Momentum excess "decayed ~50 %" | WEAKENED (MOM-2): live t ≈ 0.64 | Shown as "indistinguishable from zero", not as decay |
| NSE 19.19 %/15.08 % since inception | WEAKENED (MOM-9): inconsistent | Not displayed |
| Low-vol "reliably" cuts drawdown | WEAKENED (EVQ-6): one ETF, one crash | Low-vol is a candidate characteristic only |
| Stock data "BLOCKED" | WEAKENED (EVQ-1, AUTO-7, BT-5): broker API is REQUIRES CONFIGURATION | Hosted BLOCKED; local REQUIRES CONFIGURATION + NOT VERIFIED; signals still ABSTAIN on G2/G3 |
| Kite is the "only" licensed path | REFUTED (R9) | Kite excluded (paid key, database clause) |
| Backtest = "simulation" under NSE ToU | WEAKENED (NSE-2): ambiguous | Recorded as NOT VERIFIED residual risk in ADR-0017 |
| Cron claim SQL | WEAKENED (AUTO-3): stale `running` blocked | Fixed claim in §9.3 |
| "11 years is enough" for Sharpe 0.5 | WEAKENED (BT-9): ~25 years for 80 % power | Power statement on the Signals page |
| Loser persistence "only" robust effect | WEAKENED (MF-2) | Review flag only, never an exit |
| Investor timing gap 2.5–5.8 %/yr | WEAKENED (MF-5) | Not quoted to the user |
| s.10(23D) citation | WEAKENED (EVQ-7): Income-tax Act 2025 in force; Schedule mapping NOT VERIFIED | Not cited in cards; tax rows carry Act versions (existing `ActPeriod`) |
| ETF STT = 0.1 % | WEAKENED (BT-4) | ETF cost rows marked NOT VERIFIED; costs ×1.5 stress applies |

---

## 15. Decisions only the user can make

| # | Decision | Default until decided |
|---|---|---|
| D1 | Vocabulary in the private view: "entry/exit condition met" only, or opt-in BUY/SELL badges | Neutral wording |
| D2 | Equity price source: none, Upstox/Angel One in local mode, manual bhavcopy (NOT VERIFIED), or written request to NSE | None; stocks ABSTAIN |
| D3 | Core universe list (≤ 40 schemes) and acceptance of AMFI minimised storage in **hosted** mode, which the registry flags as needing a licence | Local-mode-only auto-tracking until decided |
| D4 | Loss limit `B_g` and recovery tolerance `T_g` per goal | No equity recommendation for that goal (ABSTAIN) |
| D5 | Emergency months and essential expenses | Banner; growth cards still shown |
| D6 | Allocation policy targets, bands (±5 pp default) and whether rebalancing may sell | Cash-flow-only rebalancing |
| D7 | Notification channel: off / Web Push / Telegram content-free ping | Off |
| D8 | TER source: AMFI JSON endpoint (terms ban reverse engineering), factsheet upload, or typed | Factsheet upload/typed |
| D9 | Factor sleeve cap `c_factor` and whether U3 appears at all | U3 hidden |
| D10 | Tax inputs (slab, regime, LTCG used) or the conservative assumption | Conservative assumption, labelled |
| D11 | Accept that timing signals will likely stay ABSTAIN for years, and that the 20–25 %/yr aspiration is shown as historical frequency (0 % of 10-year windows reached 25 % on the four broad TRIs), not planned for | — |

---

## 16. Residual risks and open items (NOT VERIFIED)

- AMFI terms vs hosted mode (registry line 91); Turso latency after the region move; cron Host header and Deployment Protection;
  Vercel bundle size after lazy imports.
- Hybrid category equity bounds (SEBI categorisation) not cited; the conservative 100 % equity treatment stays until they are.
- The gold stress figure must be recomputed in-app from AMFI NAVs before it leaves NOT VERIFIED.
- Upstox developer terms on storage and backtesting are unread; the NSE "simulation" clause is ambiguous.
- Loss set-off and carry-forward under the Income-tax Act 2025 are not modelled; tax-loss harvesting is therefore not in the action
  set.
- XBOM calendar ends 2026-12-31.
- The public repo has no LICENSE (verify references); signal YAML files contain rules only.
