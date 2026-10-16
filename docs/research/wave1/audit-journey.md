# Audit: the user journey, from "a place to enter things" to "tells me what to do with my money"

Wave 1 · audit "journey" · written 2026-10-15 · repo state `8f56a8d` (main)
Status labels: **VERIFIED** (checked in code, by a measurement, or against a primary source on 2026-10-15) ·
**NOT VERIFIED** · **REQUIRES CONFIGURATION** · **BLOCKED**.

The user's verdict: *"too slow, lots of issues, it's just a place to enter things."*
The user's aim: *signals, mutual funds and everything needed to grow my money*, including **when to buy and sell**
equities, with a 20–25 %/yr aspiration, real money, an Indian resident investing in INR.

This audit reads the product as a critic. It covers the 17 frontend pages and the backend services behind them. It
explains why the verdict is accurate, and it ranks every missing capability by its value to the user. Each capability
comes with a deterministic implementation sketch that fits the binding rules: Decimal engine, supervisor abstains,
no fabricated data, the LLM never produces numbers, no paid keys, AMFI personal use with minimised storage, and no
signal without a documented out-of-sample, cost- and tax-aware backtest.

---

## 0. Executive summary

1. **The app answers a different question from the one the user is asking.** It was specified as a *horizon-matched
   parking decision*: "compare options for a **specific amount and withdrawal date** (1, 3, 6, 12 months)"
   (`docs/product/requirements.md` §2). The user wants an *ongoing wealth manager* that watches their money and says
   what to do next. Nearly every gap below follows from this mismatch, not from bugs.
2. **Signals are excluded by the app's own rules today.** `requirements.md` §8 lists "intraday trading signals" and
   "automated portfolio changes" as out of scope. Regulatory finding F15 and guard G2 require that alerts "never say
   'buy/sell now'". The Compliance Guard blocks phrases such as `(buy|sell|switch|exit) now`, `accumulate`,
   `target price` and `stop[- ]?loss` (`docs/security/regulatory-readiness.md` lines 171, 192, 229). However, G2 limits
   the ban to calls made "**to anyone other than the operator**". For a single-user, personal deployment, the user can
   decide to allow operator-only action wording (see §6, decision D1).
3. **Discovery can evaluate almost nothing out of the box. This is measured, not assumed.** Today's AMFI NAVAll was
   parsed with the app's own parser and scope rule (§2.2). Of the **1,779** in-scope schemes:
   - **812 (45.6 %)** get tax class `UNKNOWN` and are excluded. This includes **357 index funds** (283 under
     "Other Scheme - Index Funds" and 74 under "Index Funds - Equity Funds").
   - Only **93** have an exit load the engine knows (liquid and overnight). Every other scheme is excluded as
     `EXIT_LOAD_UNKNOWN` until the user types its load.
   - Any scheme with fewer than **60** stored NAVs is skipped. NAVAll keeps only the latest NAV for untracked schemes,
     so history exists only for schemes the user has backfilled by hand.

   The result: on day one, the only funds Discovery can rank are liquid and overnight funds the user has already
   backfilled. Equity growth, the user's stated aim, cannot be evaluated at all without many manual entries.
4. **Every input is manual and every refresh is user-driven.** NAVAll ingestion, history backfill and alert evaluation
   run only when a button is pressed. There is no scheduler (`vercel.json` has no `crons`, and a grep for
   `cron|schedul` in `backend/src` and `frontend/src` finds nothing). The user also types FD rates, T-bill yields,
   G-sec quotes, ratings, factsheet facts, exit loads, CPI, the risk-free rate and transactions.
5. **"Too slow" has concrete structural causes** (§3):
   - N+1 query loops run against a **remote** Turso database, so each query is an HTTP round trip.
   - The 98 s NAVAll refresh runs in the user's browser session.
   - The client has no cache, so every navigation refetches.
   - A full-table `COUNT … GROUP BY` on `observations` runs on every page load for the top-bar "data as of" line.
6. **What exists is a strong foundation.** It includes a Decimal engine, a tax engine with a dated rule table, FIFO
   lots, XIRR, a feasibility engine with a SIP formula, a walk-forward validation protocol, a supervisor with
   abstention, provenance on every observation, and a resumable hosted job framework. The missing layer is the
   **decision loop**: scheduled data → evaluation of the user's whole money → a small set of ranked, explained,
   backtest-gated actions → delivery to the user's phone.
7. **The largest wins, in order:**
   - (1) automatic daily data refresh with a Vercel cron;
   - (2) a goals-and-target-allocation model replacing the single "amount + date" profile;
   - (3) portfolio-level action engine: rebalancing, SIP plan, LTCG harvesting, Regular→Direct switch;
   - (4) a daily digest with push delivery;
   - (5) unblocking equity and index funds in the universe;
   - (6) a signal registry with a backtest gate, starting with trend and drawdown rules on index-fund NAVs;
   - (7) performance fixes.

   **Single-stock buy/sell signals are BLOCKED on data.** NSE, BSE and NSE Indices terms forbid automated collection or
   storage. Zerodha's free Personal API has "No historical or real-time data". The paid Connect plan costs ₹500/month
   (§5). This is decision D2 for the user.

---

## 1. What the product is today (page by page)

Navigation (`frontend/src/App.tsx`): **Decide** (Overview, Discovery, Compare, Scenarios, Simulator, Risk) ·
**Research** (Mutual funds, Fixed income, Watchlist, Alerts) · **Trust** (Evidence, Methodology, Data health) ·
plus Onboarding, Settings, Instrument detail and CAS import.

| Page | What it does | What the user must do first | Tells the user what to do? |
|---|---|---|---|
| Onboarding (427 lines) | One profile: amount, withdrawal date, objective A–E, loss tolerance, early-need, days-to-cash, credit floor, slab, surcharge, aspiration | Type it | No |
| Overview (1,128) | Portfolio CRUD, transactions, CSV import, market value, XIRR, concentration, maturities, DICGC | Create a portfolio and type or import every transaction | No: descriptive only |
| Discovery (477) | Supervisor-run ranking of stored instruments for the one profile | Profile + backfilled NAV history + typed exit loads + typed FD/T-bill/bond data | Ranks for **one lump sum and one date**; no "do this now" |
| Compare (864) | Net proceeds of picked instruments on one axis | Pick instruments | No |
| Scenarios (786) | Shocks + return-target feasibility for one instrument | Pick an instrument with history | No (historical frequency only, by design) |
| Simulator (424) | Weights → portfolio band, ladder, DICGC | Type the weights | No |
| Risk (405) | Volatility, Sharpe, forecast band, walk-forward validation per instrument | Backfilled history; T-bill series for Sharpe | No |
| Mutual funds (543) | Browse stored schemes; **"Fetch latest NAV"** and **"Backfill"** buttons; exit-load entry | Click, wait (hosted: up to 200 resumable calls) | No |
| Fixed income (1,358) | Manual T-bill, FD, G-sec, SDL and corporate-bond entry with citations | Type every rate and quote | No |
| Watchlist (365) | Change since added | Add items | No |
| Alerts (374) | 6 rule types (stale data, maturity, HHI, decline since added, tax coverage, ingestion failed); **"Evaluate"** button; delivery `"local only"` | Press Evaluate | Threshold notices only, worded "Your rule … triggered" |
| Evidence / Methodology / Data health | Provenance, formulas, source status | — | No |
| CAS import (336) | CAMS/KFintech PDF → ledger | Upload; Regular-plan and IDCW ISINs are rejected as unmatched unless the AMFI lookup finds them | No |

**Verdict: VERIFIED.** Every "Decide" page is a calculator the user drives. None runs on its own. None looks across the
user's whole money. None outputs an action. The product is a careful **research workbench**. The user asked for an
**advisor-like loop**.

---

## 2. Why it feels like "a place to enter things"

### 2.1 Count of manual inputs before a useful answer (VERIFIED from code and `known-limitations.md`)

| Input | Where | Needed for |
|---|---|---|
| Profile (8–11 fields) | Onboarding | Any personalised result |
| Portfolio + every transaction (or CSV/CAS) | Overview / CAS | Anything about "my money" |
| Press "Fetch latest NAV" | Mutual funds | Fresh NAVs |
| Press "Backfill" per scheme (or tick ≤ 100) | Mutual funds | Any MF in Discovery, Risk, Scenarios |
| Exit load per non-liquid scheme, with citation | Mutual funds / Instrument | Any non-liquid MF in Discovery |
| Factsheet facts (duration, YTM, TER, lowest rating) monthly | Instrument detail | Debt funds with a credit floor; yield carry; rate shocks |
| T-bill cut-off yields | Fixed income | T-bills; the Sharpe risk-free series |
| FD rates + card-rate tables + penalty | Fixed income | FDs and FD early exit |
| G-sec / SDL / corporate quotes, ratings, rationale URL | Fixed income | Bonds |
| CPI month | Data health | Real returns |
| Press "Evaluate" | Alerts | Any alert |

Most of these are manual for **good, documented reasons**. RBI blocks scripted access and forbids caching. Rating
agencies and NSE/BSE forbid automated collection. Factsheets are per-AMC with unverified terms
(`docs/data/source-registry.md`). The fix is **not** to scrape. It is to (a) automate the one source that is allowed
(AMFI), (b) remove gates that exclude whole asset classes needlessly, and (c) make the product useful with **only**
AMFI data plus the user's holdings.

### 2.2 Measured: how much of the AMFI universe Discovery can evaluate (VERIFIED, 2026-10-15)

Method: today's `https://portal.amfiindia.com/spages/NAVAll.txt` was streamed into the app's own `parse_navall`,
`in_minimised_scope`, `mf_tax_class_from_category` and `sebi_default_exit_load`, in memory only. Nothing was stored,
which keeps within AMFI's personal-use terms.

```
in scope 1779
{'unknown': 812, 'specified_debt': 355, 'equity_oriented': 612}
SEBI default exit load known: 93
index/ETF-like: 402
283 Other Scheme - Index Funds
 91 Other Scheme - FoF Domestic
 74 Index Funds - Equity Funds
 64 Fund of Funds Scheme (Domestic) - Fund of Funds Scheme (Domestic)
 30 Other Scheme - FoF Overseas
 22 Hybrid Scheme - Dynamic Asset Allocation or Balanced Advantage
 22 Index Funds - Debt Funds
 22 Solution Oriented Scheme - Retirement Fund
 19 Hybrid Scheme - Multi Asset Allocation
 19 Overseas Fund of Funds - Fund of Funds investing overseas
```

Three gates apply in `backend/src/iip/engine/candidates.py` and `services/discovery.py`:

- **Tax class.** `mf_tax_class_from_category` returns `EQUITY_ORIENTED` only when the category starts with
  `"equity scheme"` or contains `arbitrage` or `elss` (lines 843–855). So **"Index Funds - Equity Funds" (74 schemes)
  is UNKNOWN even though the label itself says equity.** This is a straightforward false negative. The 283 "Other
  Scheme - Index Funds" are genuinely ambiguous (equity and debt index funds share the label), but the scheme name
  usually identifies the index ("Nifty 50", "Sensex", "Nifty Next 50", "Gilt", "SDL"). A deterministic name-pattern
  table, with citations and a flag, could classify most of them. The resulting class would carry
  `TAX_CLASS_INFERRED_FROM_NAME`. Coverage is NOT VERIFIED until that table is built and measured.
- **Exit load.** `mf_candidate` adds `EXIT_LOAD_UNKNOWN` whenever no load was entered and SEBI fixes none (line
  1050–1052). This applies **even when the horizon is far longer than any plausible load period**, which excludes
  1,686 of 1,779 schemes. A conservative fix: a user-acknowledged **upper-bound assumption**, e.g. 1 % if redeemed
  within 365 days, labelled `EXIT_LOAD_ASSUMED_UPPER_BOUND`. It would only overstate cost, and it would not apply to
  horizons beyond the bound. Whether 1 % / 365 days really is an upper bound across categories is **NOT VERIFIED** and
  must be researched from SIDs before adoption.
- **History.** Schemes with fewer than `MIN_HISTORY_POINTS = 60` usable NAVs are skipped (`discovery.py` line 47).
  `prune_untracked_history` deletes history of schemes that are neither held, watched nor backfilled
  (`ingestion.py` 330). Discovery therefore cannot *discover*. It can only re-rank what the user already chose to
  backfill.

### 2.3 The profile model is one bucket

`/api/profile` stores exactly one amount, one withdrawal date and one objective. Real money has several buckets:
emergency fund, short-term goals, long-term growth, tax-saving. Each bucket has its own horizon and risk, and there is
also monthly cash flow (SIP). The engine already supports per-horizon evaluation. It is only the product surface that
collapses everything into one bucket.

---

## 3. Why it is slow (structural causes)

| # | Cause | Evidence | Status |
|---|---|---|---|
| S1 | **Remote DB, N+1 queries.** Hosted mode opens `libsql.connect("libsql://…")`, a remote connection with no embedded replica (`store/db.py` 59–80), so each `execute` is a network round trip. `build_universe` issues one `COUNT(DISTINCT observation_date)` per scheme over all 1,779 schemes, then `_nav_series` and `fund_credit_facts` for each eligible one (`discovery.py` 164–206). `portfolio_summary` calls `latest_nav` + `latest_freshness` (2 queries) per holding; `watchlist` calls `watch_change` per row | Code | Query count VERIFIED from code; wall-clock on Vercel+Turso **NOT VERIFIED** (not measured; needs the token) |
| S2 | **Data refresh happens inside the user's session.** NAVAll stores 1,779 schemes in about 98 s (ADR-0013). The MF page loops `runUntilDone` while the user waits; backfill is paced at 1 request/s with 90-day windows | `MfExplorer.tsx` 273–300; ADR-0013 | VERIFIED |
| S3 | **No client cache.** `useApi` sets `data=null` and refetches on every mount (`lib/useApi.ts`), so every navigation shows a loader | Code | VERIFIED |
| S4 | **Top bar hits `/api/data-health` on every app load.** It runs ~20 per-source queries plus a full `COUNT(*) … GROUP BY quality_status` over `observations` | `routes_core.py` 334–360; `App.tsx` 166 | VERIFIED (cost on Turso NOT VERIFIED) |
| S5 | **Cold start** of a 286 MB Python bundle (scipy, numpy, casparser_isin) | ADR-0013 | Size VERIFIED; cold-start latency NOT VERIFIED |
| S6 | Discovery recomputes everything per request; nothing is precomputed overnight | Code | VERIFIED |

**Deterministic fixes (no behaviour change):**
- Replace per-scheme `COUNT` with one `GROUP BY series_id HAVING COUNT(DISTINCT observation_date) >= 60`.
- Batch `latest_nav` for all holdings with one window query (`ROW_NUMBER() OVER (PARTITION BY series_id ORDER BY
  observation_date DESC)`).
- Add a `series_stats` table (`series_id, n_usable, first_date, last_date, last_value, last_quality`) maintained by
  ingestion, so reads never scan `observations`.
- Move the top-bar line to a tiny `/api/data-asof` that reads one row.
- Add a stale-while-revalidate cache in `useApi`, keyed by path, that shows the previous data with a "refreshing"
  badge. It must never present cached data as fresh.
- Precompute the daily snapshot in the cron (§4, C1) so pages read stored results keyed by their input hash. Runs
  are already deterministic and hash-stored (`store_run`).

Before and after must be measured with a request-timing log (count of statements per request, ms) on the hosted
deployment. Until then, every latency claim stays NOT VERIFIED.

---

## 4. Missing capabilities, ranked by value to the user

Ranking criterion: **expected ₹ impact on the user's real money × how often it matters ÷ effort**, given the data
the app can legally obtain. Each item lists: what the user gets, a deterministic sketch, data status and the gate.

### C1. Automatic daily data refresh (Vercel cron) — value: highest; it unblocks everything

- **User gets:** fresh NAVs every morning without clicking, and history that grows by itself for every held, watched or
  goal-linked scheme.
- **Facts (VERIFIED, accessed 2026-10-15):**
  - Hobby plan: "Once per day" minimum interval, "Per-hour (±59 min)" precision, 100 cron jobs per project
    (<https://vercel.com/docs/cron-jobs/usage-and-pricing>: "Hobby accounts are limited to cron jobs that run **once per day**").
  - Trigger: "Vercel makes an HTTP GET request to your project's production deployment URL … `https://*.vercel.app/api/cron`".
    Timezone: "The timezone is always UTC". User agent: `vercel-cron/1.0`
    (<https://vercel.com/docs/cron-jobs>).
  - Securing: "The value of the variable [`CRON_SECRET`] will be automatically sent as an `Authorization` header".
    Retries: "Vercel will not retry an invocation if a cron job fails". Delivery: "Cron job delivery is best effort …
    can also occasionally invoke the same scheduled run more than once"
    (<https://vercel.com/docs/cron-jobs/manage-cron-jobs>).
- **Blocker to design around:** the app refuses raw deployment URLs with 400 (ADR-0013, Host allowlist). Cron calls
  arrive on the generated `*.vercel.app` host, so **the cron would be refused as the code stands**. A third-party
  report shows exactly this failure mode (<https://github.com/namphuongtran/familyroots/issues/265>, accessed
  2026-10-15: "Vercel Cron calls the deployment's own host, which ALLOWED_HOSTS refuses"). Fix: allow the
  `VERCEL_URL` host **only** for `GET /api/cron/*`, **only** with `Authorization: Bearer $CRON_SECRET`
  (constant-time compare). There is no cookie or session on that path, and it stays rate-limited.
- **Sketch:**
  - `vercel.json` `crons`, staggered to fit the 90 s step budget and best-effort delivery. Every job is idempotent and
    reconciling: "process everything outstanding since the last success". Job 1 runs NAVAll at ~17:30 UTC
    (≈ 23:00 IST, after NAVs publish; the SLO in source-registry is "NAV for T by 23:00 IST"). Jobs 2–4 are
    continuations one hour apart, which advance the resumable `job_progress` run. Job 5 backfills the history gap for
    tracked schemes. Job 6 builds the snapshot and digest (C4).
  - Because Hobby allows only daily jobs, use **several distinct daily jobs at different hours** rather than one
    frequent job. Each runs at most one 90 s step.
  - Results go to `ingestion_runs`. A missed run is caught up by the next one, since each job processes "since last
    success".
- **Data:** AMFI only. AMFI terms allow personal, non-commercial use and forbid storing a "significant portion"
  (source-registry §2.1, quoting <https://www.amfiindia.com/terms-of-use>). Keep the existing minimisation: history
  only for tracked schemes plus a capped signal universe (C6).
- **Status:** REQUIRES CONFIGURATION (`CRON_SECRET`, host exception). Everything else is buildable now.

### C2. Goals, buckets and a target allocation — value: very high (the "what is my money for" model)

- **User gets:** several goals (emergency fund, a 2028 house down payment, retirement…), each with amount, date,
  priority, objective A–E and a loss budget. Plus a **target allocation per goal** derived from rules the user accepts,
  and a "funded %" per goal.
- **Sketch:**
  - New `goals` table. A `goal_id` on transactions (or a holding→goal mapping table), so each rupee belongs to one
    bucket.
  - Funded % = Σ market value of mapped holdings ÷ PV of the goal. The PV uses a **user-chosen** discount rate shown
    as an assumption. It is never a forecast.
  - Target allocation comes from a versioned, cited **policy table** (`allocation_policy@1`) keyed by horizon band and
    objective. Example: horizon < 1 y → T1–T3 instruments only; 1–3 y → debt-dominant; > 5 y with objective D/E →
    equity band [x, y] set by the loss budget and computed from historical drawdowns already produced by the
    feasibility engine. The table values are a **user decision**, recorded with the date. The engine never invents
    them.
  - The supervisor manifest per goal: profile fields, holdings, fresh NAVs, policy version. Anything missing →
    ABSTAIN for that goal only.
- **Data:** user input + AMFI. **Status:** buildable now.

### C3. Portfolio action engine — value: very high (the core of "tell me what to do")

All actions are deterministic, computed on the user's own holdings and rules, and each carries a ₹ effect after cost
and tax using the existing tax engine and FIFO lots. These are **policy actions**, not market-timing claims. They do
not need alpha evidence, but each still shows cost and tax drag, and each abstains on missing context.

| Action | Rule (deterministic) | ₹ effect shown | Existing parts reused |
|---|---|---|---|
| **Rebalance** | Drift band: act when \|w_actual − w_target\| > band (user-set, e.g. 5 pp absolute). Prefer **cash-flow rebalancing**: direct new SIP money to underweights before any sale. Sales picked lot by lot to minimise tax (LTCG lots first, then within the ₹1.25 lakh exemption) | Units per scheme, exit load, STCG/LTCG, net drift after | `fifo_positions`, `tax.compute_tax`, exit-load spec |
| **SIP plan per goal** | `monthly SIP = goal·i/((1+i)^n − 1)` already exists in `feasibility.py` (line 1057), at user-chosen rates; show the historical-frequency band from the feasibility engine for the chosen fund's series | Monthly ₹ per goal and per scheme | `feasibility.py` |
| **LTCG harvesting** (equity-oriented) | In each FY, if realised LTCG + unrealised LTCG on lots held > 12 months < ₹1.25 lakh exemption, propose sell-and-rebuy of exactly the units that use the remaining exemption. Show the next-day NAV risk and exit load. **Abstain** if the old regime / non-resident applies (not modelled) | Tax saved later = harvested gain × 12.5 % (+ cess), shown as a deferred-tax effect | Tax table `india-tax@2026-10-15.r2` (s.112A → s.198, 12.5 % above ₹1.25 lakh, `docs/research/indian-instruments-and-tax.md` line 410) |
| **Tax-loss harvesting** | Book capital losses to set off gains in the same FY. Set-off rules must come from the rule table; carry-forward is not modelled today | Tax saved | Needs new rule rows; **NOT VERIFIED** until CA review |
| **Regular → Direct switch** | CAS shows Regular-plan ISINs. Propose a switch when (TER_regular − TER_direct) × remaining horizon > exit load + tax on switch | Breakeven months | Needs TER entry (factsheet) and a fix to the CAS Regular-plan rejection (known-limitations, CAS gap 1) |
| **Idle cash / emergency fund** | If the emergency goal is under-funded, or cash sits above N months of expenses, propose a liquid/overnight fund from the eligible set | ₹ and days-to-cash | Existing Discovery for objective C |
| **Maturity rollover** | FD/T-bill/bond maturing within N days → run Discovery for that amount and the goal's remaining horizon | Ranked options | Existing alert + Discovery |
| **Concentration** | HHI or single-AMC/scheme share above the user's limit → show which flows reduce it | Post-action HHI | Existing HHI |

**Output format:** an `ActionCard` with fields `{kind, goal_id, instrument_ids, units, amount, why_rule, cost, tax,
net_effect, evidence_refs, engine_version, input_hash, status}`. Every number is traced to a fact id, as in
discovery's FactSheet. Wording is controlled by decision D1.

### C4. Daily digest with push delivery — value: very high (the "signals" experience)

- **User gets:** one short message each morning, for example: "3 actions, 1 alert, data as of 15-Oct NAV". It links
  to a Today page listing the action cards, triggered rules, goal funded % changes and data health.
- **Sketch:**
  - The cron job (C1, job 6) runs the supervisor over all goals. It stores a `digest` row (date, input hash, cards,
    abstentions) and marks new versus unchanged cards with a dedupe key, as `alerts` already does.
  - **Today** becomes the landing page, replacing Overview as `/`.
  - **Push:** ntfy, which describes itself this way: "send push notifications to your phone or desktop via scripts
    from any computer, using simple HTTP PUT or POST requests". It is open source and self-hostable
    (<https://docs.ntfy.sh/>, accessed 2026-10-15). The terms and privacy of the public `ntfy.sh` server are
    **NOT VERIFIED**.
  - **Privacy rule:** the push body carries **no amounts, holdings or scheme names**, only counts and a link, because
    the topic is readable by anyone who knows it. Alternatively, use an unguessable topic on a self-hosted instance.
- **Status:** REQUIRES CONFIGURATION (topic or self-hosted server).

### C5. Unblock equity and index funds in the universe — value: high (the 20–25 % aim lives here)

- **Fix A:** classify "Index Funds - Equity Funds" as equity-oriented. Add a cited name-pattern table for "Other
  Scheme - Index Funds" (Nifty / Sensex / Midcap / Smallcap → equity; Gilt / SDL / G-Sec / Bharat Bond / CRISIL IBX →
  debt). Flag `TAX_CLASS_INFERRED_FROM_NAME`. Leave everything else UNKNOWN.
- **Fix B:** the exit-load upper-bound assumption described in §2.2, applied only after a researched bound. Also
  ingest exit loads from the user's CAS transactions where load was charged. That is data the user owns.
- **Fix C:** a "growth universe" auto-tracks a capped list of broad index funds (one Direct-Growth scheme per index
  family), so they keep history without manual backfill. The cap must be justified against AMFI's "significant
  portion" wording. A few dozen of ~14,400 schemes looks small, but **whether this is acceptable is a judgement for
  the user**, recorded as decision D3.
- **Status:** buildable now. Fix B needs research.

### C6. Signal registry with a backtest gate — value: high, but only once C1–C5 exist

- **Principle (binding):** a signal exists only if a **pre-registered**, out-of-sample, cost- and tax-aware backtest
  supports it. Otherwise the engine abstains with `NO_VALIDATED_SIGNAL`. "No suitable candidate" is valid.
- **Registry:** `signals/<id>@<version>.yaml` with:
  - rule (pure function of point-in-time NAVs);
  - universe;
  - rebalance frequency;
  - costs (exit load, stamp duty 0.005 % on MF purchases: **NOT VERIFIED** here, must be cited before use);
  - tax (STCG/LTCG via the engine, held lot by lot);
  - in-sample and out-of-sample split dates, fixed before the first run;
  - the acceptance criteria;
  - the backtest result hash.

  The engine evaluates only signals whose status is `ACCEPTED`. The promotion rule reuses
  `docs/forecasting/validation-methodology.md` §4 (walk-forward with purge and embargo) and §6 (model promotion
  rule).
- **Acceptance criteria (proposal, user decides):** out-of-sample after-tax terminal wealth ≥ buy-and-hold of the same
  fund, **and** max drawdown better by ≥ X pp, **and** stable across ≥ 3 start-month offsets, **and** ≥ N independent
  trades. Report the failures as prominently as the passes.
- **First candidates (all on AMFI index-fund NAVs, no exchange data):**
  1. **Trend filter** (e.g. NAV vs its 10-month moving average, checked monthly) to switch between an equity index
     fund and a liquid fund. Literature: Moskowitz, Ooi & Pedersen, *Time Series Momentum*, JFE 104(2) 2012,
     "We document significant 'time series momentum' in equity index, currency, commodity, and bond futures for each
     of the 58 liquid instruments we consider" (<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463>,
     accessed 2026-10-15). That evidence is for **futures, not Indian MF NAVs after STCG**. Whether it survives
     Indian tax (STCG on every switch out within 12 months) is **NOT VERIFIED** and is exactly what the gate must
     test. Expect it may fail.
  2. **Drawdown-triggered top-up** (deploy extra SIP when the index fund is ≥ X % below its high). This is a cash-flow
     rule with no selling, so it has no tax drag.
  3. **Valuation band**: BLOCKED. P/E data comes from NSE Indices, whose terms say "No material from the Site may be
     copied, modified, reproduced, republished … without prior written permission" and require a licence for index
     data use (<https://www.niftyindices.com/terms-of-use>, <https://www.niftyindices.com/disclaimer>, accessed
     2026-10-15).
- **Forward-only outcome ledger:** every emitted signal is stored with its engine version and later scored against
  realised NAVs. This adopts the idea already noted from `ZhuLinsen/daily_stock_analysis`
  (`docs/research/github-reference-review.md` §6.2). Drift triggers demotion.
- **History depth caveat:** Direct plans began in 2013 (from general knowledge; **NOT VERIFIED** here). Out-of-sample
  windows on Direct NAVs therefore contain few bear markets. The feasibility engine already banners "This history
  contains no major equity bear market". Signals must carry the same banner.
- **Fund-picking signals** ("switch to the top-quartile fund"): existing research shows active-fund persistence is
  weak (SPIVA India figures in `return-target-feasibility.md` §0.5). Expect the gate to reject them. Ship the gate, not
  the signal.

### C7. Equity stocks: when to buy and sell — value: high to the user, but BLOCKED on data

| Route | Terms / cost (accessed 2026-10-15) | Status |
|---|---|---|
| NSE website / JSON | ToU bans "systematic or automated data collection activities (including scraping…)" (source-registry §2.11) | **BLOCKED** |
| BSE | "Any reproduction, redistribution or transmission … is strictly prohibited" (source-registry §2.11) | **BLOCKED** |
| NSE Indices (TRI, P/E) | No copying "without prior written permission"; index data use "require[s] a license" (links above) | **BLOCKED** |
| Zerodha Kite Connect **Personal** (free) | "No historical or real-time data included" (<https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/what-are-the-charges-for-kite-apis>) | Gives holdings only; useful for **read-only holdings import**, not signals |
| Zerodha Kite Connect (Connect) | "₹500/month", adds "Historical candle data" (same URL) | **REQUIRES CONFIGURATION + user decision** (a paid data feed, though not an AI key) |
| yfinance `.NS` | Personal use only, non-authoritative, documented wrong Indian corporate-action adjustment (`github-reference-review.md` §6.6) | Context only; never decision-grade |

**Recommendation:** do not build stock signals until decision D2 is made. Until then, the honest answer to "when to
buy or sell stocks" is **ABSTAIN: no licensed price source**. The equity exposure that pursues the 20–25 % aim can be
served through index and equity funds (C5, C6), which AMFI covers. Regardless of the data source, any stock signal
must pass the same gate as C6, with brokerage, STT and stamp duty, which are not yet modelled.

### C8. Holdings that keep themselves up to date — value: medium-high

- CAS import exists but is NOT VERIFIED on a real statement and rejects Regular-plan ISINs (known-limitations, CAS gap
  1). Fix the matching by storing ISIN→AMFI code for **held** schemes on demand, not the whole universe.
- Optional: Kite Connect Personal (free) for **read-only** holdings of a Zerodha account. G1 forbids order APIs. The
  holdings API is read-only, but the G1 CI check bans broker SDK packages, so this is user decision D4.
- SIP auto-posting: a recurring transaction template (scheme, ₹, day of month) that the cron posts at that date's NAV,
  flagged `ASSUMED_SIP_EXECUTED` until CAS reconciliation confirms it.

### C9. Alerts that run and arrive by themselves — value: medium

- Move `/alerts/evaluate` into the cron (C1). Deliver via the digest (C4).
- New rule types:
  - goal off-track: funded % below its glide-path by X;
  - drift beyond band;
  - harvest window: FY-end within 30 days and exemption unused;
  - SIP missed: no CAS match within 7 days;
  - signal state changed (C6, accepted signals only);
  - fund category or name changed in NAVAll (merger watch);
  - NAV source conflict.

### C10. Performance and responsiveness — value: medium (felt on every click)

See §3. Effort is small, and it should be bundled with C1 because the snapshot table removes most read-path work.

### C11. Goal tracking and progress charts — value: medium

Per-goal value vs plan over time, XIRR per goal (the existing `_xirr_block`), contributions vs growth, and the
historical-frequency band from the feasibility engine. All derived; no new data.

### C12. Net-worth view outside MFs — value: medium-low

EPF/PPF/NPS/property/gold as user-entered balances with dates, labelled manual, for allocation and goal funding only.
No pricing, no ranking.

### C13. Tax year summary — value: medium-low

Realised STCG/LTCG per FY from FIFO, exemption used, set-off, and a CA-ready export. The engine pieces exist. Rules
still NV (8 of 65) must be shown as such.

### C14. Explanations in plain language — value: low-medium

The optional LLM adapter exists. Keep it narration-only over engine facts. Off by default.

---

## 5. External facts used (all accessed 2026-10-15)

| Fact | Quote | URL | Status |
|---|---|---|---|
| Vercel Hobby cron limits | "Hobby accounts are limited to cron jobs that run **once per day**"; precision "Per-hour (±59 min)"; "100 cron jobs" per project | <https://vercel.com/docs/cron-jobs/usage-and-pricing> | VERIFIED |
| Cron trigger and timezone | "Vercel makes an HTTP GET request to your project's production deployment URL"; "The timezone is always UTC"; UA `vercel-cron/1.0` | <https://vercel.com/docs/cron-jobs> | VERIFIED |
| Cron security, no retry, at-least-once | `CRON_SECRET` "automatically sent as an `Authorization` header"; "Vercel will not retry an invocation if a cron job fails"; "can also occasionally invoke the same scheduled run more than once" | <https://vercel.com/docs/cron-jobs/manage-cron-jobs> | VERIFIED |
| Cron host vs allowlist failure mode | "Vercel Cron calls the deployment's own host, which ALLOWED_HOSTS refuses, so neither job runs" | <https://github.com/namphuongtran/familyroots/issues/265> | VERIFIED as a third-party report; behaviour against this app NOT VERIFIED |
| ntfy | "send push notifications to your phone or desktop via scripts from any computer, using simple HTTP PUT or POST requests" | <https://docs.ntfy.sh/> | VERIFIED (public-server terms NOT VERIFIED) |
| Zerodha API data | Personal: "No historical or real-time data included"; Connect "₹500/month" with "Historical candle data" | <https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/what-are-the-charges-for-kite-apis> | VERIFIED |
| NSE Indices terms | "No material from the Site may be copied, modified, reproduced, republished … without prior written permission"; index data use requires "a license" | <https://www.niftyindices.com/terms-of-use>, <https://www.niftyindices.com/disclaimer> | VERIFIED via search excerpt (page text not fetched directly) |
| Time-series momentum | "significant 'time series momentum' in equity index, currency, commodity, and bond futures for each of the 58 liquid instruments" | <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463> | VERIFIED (abstract); applicability to Indian MFs after tax NOT VERIFIED |
| AMFI terms | "personal and non-commercial use only … shall not store electronically any significant portion" | <https://www.amfiindia.com/terms-of-use> (quoted in `docs/data/source-registry.md` §2.1) | VERIFIED in repo docs; not re-fetched today |

---

## 6. Decisions only the user can make

- **D1 – Action wording for the operator.** Should action cards say "Sell 120.4 units of X (rebalance rule R1)"
  instead of "Your rule R1 triggered"? Guard G2 already restricts directives only "to anyone other than the operator".
  Allowing operator-only directives means editing the compliance phrase list for a new `operator_actions` channel that
  can never be exported or shared.
- **D2 – Equity stock data.** Pay ₹500/month for Kite Connect historical data (or another licensed feed)? Or accept
  that stock buy/sell signals stay BLOCKED and pursue equity through index funds?
- **D3 – Auto-tracked growth universe size.** How many index and equity funds may keep full history without being held
  or watched, given AMFI's "significant portion" clause?
- **D4 – Read-only broker holdings import.** Allow a read-only broker SDK (Kite Personal) despite the G1 CI ban on
  broker packages?
- **D5 – Allocation policy table.** Which equity bands per horizon and loss budget should the user commit to? These
  values drive rebalancing and must be the user's, not the engine's.
- **D6 – Signal acceptance criteria.** Which out-of-sample thresholds (wealth, drawdown, number of trades,
  start-month stability) must a signal pass? These must be fixed **before** the first backtest is run.
- **D7 – Push channel.** Public ntfy.sh with a secret topic and no amounts in the body, a self-hosted ntfy, or
  in-app only?
- **D8 – Exit-load assumption.** Accept a researched, conservative upper-bound exit load (labelled) so equity funds
  enter Discovery? Or keep strict per-scheme entry?

---

## 7. Suggested build order (each step ships something the user can see)

1. **Week 1:** C10 query fixes + `series_stats`, C1 cron (NAVAll + continuation + tracked backfill) with the
   `CRON_SECRET` host exception, and the Today page with data-as-of.
2. **Week 2:** C5 tax-class fix A (measurable: the UNKNOWN count drops from 812), C2 goals + D5 policy table.
3. **Week 3:** C3 rebalance, SIP plan, LTCG harvest and maturity rollover cards; C4 digest + push (D1, D7).
4. **Week 4+:** C6 signal registry, backtest harness and outcome ledger. First run: the trend filter on 2–3 index
   funds, with a published pass/fail report and abstention as the default outcome.
5. **Gated on D2:** C7.

Success measure for the user's verdict: on a fresh install with only holdings imported, the Today page shows
something actionable or an explicit, reasoned abstention by the next morning, without a single manual data entry.
