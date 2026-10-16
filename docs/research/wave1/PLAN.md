# Wave-2 build plan: from "a place where I enter things" to a daily money engine

- **Written:** 2026-10-16. **Inputs:** all 30 wave-1 files in this directory: 4 audits, 11 research reports, 11 verify files,
  3 designs and `design-judgement.md`.
- **Base design:** risk-first (`design-risk-first.md`, judged 51/60). It takes in the must-grafts and should-grafts from
  evidence-first and user-first listed in `design-judgement.md` §2.
- **External claims:** no new web research was done for this plan. Every external fact below comes from a wave-1 report,
  which records the URL, the access date **2026-10-15** and the quote. Where a source is named here, the URL and a short
  quote are repeated. Wave-1 verifiers weakened or refuted some claims; those are used here only in their corrected form.
- **Status labels:** VERIFIED / NOT VERIFIED / REQUIRES CONFIGURATION / BLOCKED. PARAMETER marks a design choice, which is
  not evidence.
- **Not investment, tax or legal advice.** All ₹ figures in examples are fictional. No other repo file was changed and
  nothing was committed.

---

## 1. One-page summary (for you)

**What you asked for:** something that doesn't just store what you type, but tells you what to do with your money. You
wanted signals, mutual funds, when to buy and sell, and growth of 20–25 % a year.

**What the app will become.** You open **Today**, a page the app prepares by itself every morning, before you look. It
answers one question: *what do my own rules say I should do with my money now?* Each answer is a card with rupee amounts,
the tax and cost involved, and a link to where every number came from. Examples:

- **Where this month's money goes.** "This month's ₹X SIP should go to fund A and fund B, because equity is below your
  target and the emergency fund is full." This is the honest, evidence-backed form of "when to buy".
- **How much equity your loss limit allows.** You say how many rupees you could watch disappear in a crash without
  selling. The app works out the most equity that limit permits, using the worst falls in Indian market history. It never
  raises equity to chase the 20–25 % aim.
- **When you have drifted.** "Equity is 8 points over target. Send the next three SIPs to debt instead of selling."
- **Free money left on the table.** For example, switching from a Regular plan to the Direct plan of the same fund. The
  app measures the cost gap from the NAVs of both plans and gives you the date to switch so the tax bill stays low. Another
  example is LTCG harvesting inside your ₹1.25 lakh yearly exemption.
- **Safety checks:** the emergency fund, the ₹5 lakh deposit-insurance limit per bank, FD maturities, and money due soon
  that sits in volatile funds.
- **"Nothing needs doing today."** This is a real answer, and on most days it will be the right one.

**What happens without you:** NAVs, inflation (MoSPI) and T-bill yields (RBI) refresh every day through scheduled jobs. A
content-free phone ping ("your report is ready") is optional. You only re-upload your CAS now and then. Setup is about six
answers plus one CAS upload. Any further input is requested only when it unlocks money, and the request says how many
rupees, at most.

**Signals.** The app keeps a **signal registry**: trend rules, momentum rules and so on, each written down and frozen
before it is tested. Each rule is run every day in **shadow mode**. Its result is recorded and scored later, but never shown
to you as an instruction. A rule becomes a real "act now" card only after it passes twelve-plus evidence gates on Indian
data, after costs and after tax. Honestly, that will take years for any rule, and most rules will never pass. So the
Signals page will show **ABSTAIN** with an "earliest possible review" date for each rule. That means the app is refusing to
make something up, not that it is broken.

**Stocks.** Automated stock prices are **BLOCKED**: NSE's terms forbid automated collection. A free broker API on your own
account (Upstox or Angel One) is a possible later route, in local mode only, but stock buy/sell signals would still
abstain, because no data source lets the app test them honestly.

**First, the app gets fast.** Today the hosted database is in Virginia and the code runs in Mumbai, so every query takes
about 0.4 s. Discovery times out at 300 s. Fixing that comes before anything else.

---

## 2. Honest expectations

### 2.1 What signals can and cannot do

| Question | Honest answer | Basis (wave-1 report) |
|---|---|---|
| Will I get "buy now / sell now" calls on day one? | **No.** Every timing rule starts in SHADOW/ABSTAIN. | `research-backtest-method.md` §9–10; `design-judgement.md` §0 |
| How long until a timing rule *could* pass? | A true 0.5-Sharpe edge needs about **132 months** of out-of-sample data to reach PSR 0.95, at roughly 50 % power. **About 298 months (~25 years)** gives 80 % power. With HAC t ≥ 3 required, about 12 years of history needs an annualised Sharpe of about 0.87. | `research-backtest-method.md` fixture MT-3; `verify-backtest-method.md` BT-9 |
| Couldn't I just test many rules and keep the best? | The best of 100 zero-skill variants over 10 years shows a Sharpe of about **0.80 by luck alone**. That is why every trial is logged and counted. | `research-backtest-method.md` fixture MT-1 |
| Does momentum work in India? | In gross, long-short paper portfolios, yes. The current IIMA library gives about 10.65–10.96 %/yr since 1994, with a 62 % worst drawdown. Live, investable evidence is weak: Nifty200 Momentum 30's live excess (2021–2025) was +2.79 pp/yr with t ≈ 0.64, statistically indistinguishable from zero. Max drawdowns were 68–73 %. | `research-evidence-momentum.md`; `verify-evidence-momentum.md` MOM-1, MOM-2 |
| Value, quality, low-vol, size? | No live, net-of-fee excess was significant. Factor ETF and index-fund excess ranged from −2.4 % to +2.9 %/yr, with every t between −1 and +1. Low-vol lowered volatility in one ETF over one window. | `research-evidence-value-quality.md`; verify EVQ-6 |
| Can I pick tomorrow's winning fund? | No robust evidence that past winners keep winning beyond about a year. Cost differences between plans of the *same* fund are certain. | `research-evidence-mf.md`; verify MF-2, MF-3 |
| Stop-losses, volatility targeting, "sell when it falls"? | **Refused.** Volatility targeting failed real-time out-of-sample tests on 103 strategies (Cederburg et al. 2020). No Indian after-tax test exists. | `research-evidence-allocation.md` §5–6; verify EA-3 |
| Single stocks? | **BLOCKED** for automation. Broker APIs are REQUIRES CONFIGURATION and NOT VERIFIED. Signals ABSTAIN: there are no delisted stocks, and dividends are not adjusted. | `research-equity-data-nse.md`; `research-equity-data-alt.md`; verify EQ-6 |

**What the app reliably gives you:** rupee actions that need no forecast. These are cost savings, tax timing, safety, and
sizing and rebalancing discipline. Their value is arithmetic on your own holdings, not a prediction.

### 2.2 The 20–25 % per year aspiration, against history

- **Nifty 50 TRI: 12.12 % a year since 03-Nov-1995, standard deviation 22.39 %.** Source: NSE Indices factsheet dated
  30-Sep-2026, https://www.niftyindices.com/Factsheet/ind_nifty50.pdf, accessed 2026-10-15: Total Return "Since Inception"
  "12.12", Std. Deviation "22.39" (`research-evidence-allocation.md` row 1, [P]).
- **Rolling 10-year windows that reached ≥ 20 %/yr:** 5.8 % (Nifty 50), 14.1 % (Nifty 500), 18.1 % (Midcap 150; Smallcap
  250 within the 5–18 % range). **None reached 25 %.** The best-ever 10-year windows were 22.1 % (Nifty 50), 23.4 % (Nifty
  500), 23.2 % (Midcap 150) and 21.6 % (Smallcap 250) (`research-evidence-allocation.md` §3 [C]).
- **Scope caveat (verify EA-1):** that history holds only about 2 independent 10-year windows. Pre-1992 Sensex did better
  (about 33 % price CAGR from 1979 to 1992). So "never" applies only to this sample.
- **Other asset classes:** government debt and T-bills about 7–7.5 %, gold about 11–15 %, inflation about 5–6 %
  (`research-evidence-allocation.md` §1). Factor tilts add at most a few points, none of them significant.
- **Trailing figures move with the end date.** The Nifty 500 10-year TRI return was 16.04 % at Feb-2026 and 12.77 % at
  Sep-2026 (same report).

**So:** 20–25 %/yr over a decade has happened only rarely in Indian broad-index history, and never at 25 %. The app shows
the aim as a **feasibility range with historical frequencies**. It is never a target that raises equity. Your loss limit
sets equity.

---

## 3. Decisions only you can make

Each decision lists options, trade-offs, a recommendation and the default the app uses until you decide. Decisions marked
**⚑** block the first backtest run or the first hosted cron run. Ids map to `design-judgement.md` §4 (J-n), where one
exists.

| Id | Decision | Options | Trade-offs | Recommendation | Default until decided |
|---|---|---|---|---|---|
| **U-01 ⚑** (J-1) | **AMFI data in hosted (Vercel/Turso) mode** | (a) local-only auto-tracking; (b) write to AMFI asking permission; (c) accept the risk in writing and track a capped universe hosted | The AMFI terms say "personal and non-commercial use only" and "You shall not store electronically any significant portion" (https://www.amfiindia.com/terms-of-use, via `source-registry.md` §2.1). The registry (line 91) already says to treat hosted use as "REQUIRES LICENCE / WRITTEN PERMISSION". Option (a) means the phone view shows only stored holdings data. | **(a) now, and (b) in parallel.** A01 drafts the letter. | Local-first; hosted stores only rows for held and watched schemes |
| **U-02 ⚑** (J-2) | **Loss limit per goal, in ₹, and recovery tolerance** | Your numbers | This single input sets the maximum equity. Fictional example: ₹10,00,000 with a ₹2,50,000 limit allows 34 % broad equity, because (0.25 − 0.03)/(0.67 − 0.03) = 0.344. | Decide it after viewing the worst-crash table the app shows, not after viewing returns | That goal gets no equity recommendation (ABSTAIN) |
| **U-03** (J-3) | **Emergency fund**: months and essential monthly expenses | 3 / 6 / other | The 3–6 months figure is US SEC guidance; a SEBI attribution is NOT VERIFIED. More months means less money growing. | 6 months if income is variable, else 3–6 | Banner; growth cards marked "after the emergency fund" |
| **U-04 ⚑** (J-4) | **Target allocation per goal, band, review cadence, and whether rebalancing may sell** | Band ±5 pp (Vanguard 2015 edition default) or custom; annual or semi-annual review; cash-flow-only vs selling allowed | Every sale is taxed (STCG 20 %, LTCG 12.5 % above ₹1.25 lakh) and lots are sold FIFO within a folio (CBDT Circular 768, verify EA-6). Selling restores the target faster. | ±5 pp, annual review, **cash-flow-first**; allow sales only for a L3 loss-budget breach | Cash-flow-only rebalancing |
| **U-05** (J-5) | **Tax context**: regime, slab, surcharge band, LTCG already realised elsewhere this FY | Enter them, or use the labelled conservative assumption | The conservative assumption (highest slab, exemption already used) understates the benefit of tax cards. "Needs from you" shows the ₹ each input unlocks, e.g. ≤ ₹15,625 = 1,25,000 × 12.5 %. | Enter the slab and regime (2 answers) | Conservative assumption, labelled |
| **U-06 ⚑** (J-6) | **Evidence gate thresholds** | Keep: DSR ≥ 0.95, HAC t ≥ 3, PBO ≤ 0.20, MinTRL + ≥ 30 OOS periods, vault max(20 %, 3 y), ×0.5 decay haircut, G13/G14; or lower them | They are near-unpassable on Indian Direct-plan history (§2.1). Lowering them produces signals that are more likely to be luck. The thresholds must be fixed **before** any run, or they mean nothing. | **Keep as written** | Keep as written |
| **U-07 ⚑** (J-7) | **Core universe (U1) and size** | ≤ 30 / ≤ 40 schemes (PARAMETER), one Direct-Growth scheme per broad exposure; you confirm the role → scheme bindings | Larger means more coverage and more AMFI storage (U-01). Smaller means faster jobs. Discovery today ranks only funds you backfilled by hand. | ≤ 30 schemes proposed by the deterministic rule (longest history, then lowest cost); you confirm | Proposal shown; nothing tracked until you confirm |
| **U-08** (J-8) | **Stress-table constants** (−59.5 / −67.0 / −72.9 / −75.6 %) computed from niftyindices series | Keep them in the public repo; move them to local config; ask NSE Indices | niftyindices terms: "No material from the Site may be copied … uploaded … without prior written permission" (verify MOM-8). Whether derived statistics fall under that clause is NOT VERIFIED. | **Move to local config.** The engine uses max(cited, AMFI-recomputed) anyway. | Local config |
| **U-09** (J-9) | **Notification channel** | Off; Web Push (end-to-end encrypted; on iOS it needs Home Screen install); Telegram bot (content stored on Telegram); email via Gmail app password (rejected) | Every channel sends only "report ready, open the app" (`research-automation-infra.md`). ntfy.sh public topics are rejected: anyone who knows the topic can read it and send fake alerts. | **Off in v1, Web Push in v2.** Telegram only if you accept that Telegram stores the ping. | Off |
| **U-10** (J-10) | **Equity (stock and ETF) data route** | (a) none, so stocks ABSTAIN; (b) Upstox free API on your account, local only; (c) Angel One SmartAPI, local only; (d) email NSE about manual bhavcopy; (e) Kite Connect ₹500/month | NSE ToU (https://www.nseindia.com/static/nse-terms-of-use, "Updated on: 29/10/2025"): "User is prohibited to conduct any systematic or automated data collection activities", and it bars use for "gaming, virtual trading or simulation activities". Whether a private backtest counts as "simulation" is NOT VERIFIED (verify NSE-2). Upstox: "All trading + data APIs are free of cost" (https://upstox.com/trading-api); its developer terms are **unread**. Upstox candles adjust only bonuses and splits, not dividends (community.upstox.com/t/3548, verify EQ-6), with no delisted stocks. Kite breaks the no-paid-keys rule, and its terms forbid "build databases, or otherwise create permanent copies" (https://kite.trade/terms/). | **(a) now.** Optionally (b) later for *risk views of stocks you hold*, after X-01 reads Upstox's terms. Never (e). | None; stocks ABSTAIN |
| **U-11** (J-11) | **Wording in the private view** | Neutral "entry/exit condition met" only, or opt-in BUY/SELL badges inside the logged-in view | The SEBI RA/IA regimes need "for consideration … business"; personal use falls outside them on a plain reading (`research-regulation.md`, not legal advice). Shared or public "trading calls" fall under RA. | Neutral wording. Exports and shares keep the BLOCK. | Neutral wording |
| **U-12** | **Execute the Turso move to `bom1`** | Do it now, or later | It needs your Turso account. It is the largest single speed fix (about 0.40 s per statement today). Post-move latency is NOT VERIFIED. | **Now**, following A01's runbook, after a dry run on a copy | Unchanged (`iad1`) |
| **U-13** | **Factor/momentum sleeve (U3)** | Hidden; shown as disclosed-risk candidates with a cap `c_factor` | Max drawdown 68–73 %. Quality funds have only 13–25 months of live NAV, so their statistics abstain. | Show as candidates with banners; cap ≤ 20 % of equity (PARAMETER) | Hidden |
| **U-14** | **TER source** (mostly moot after the grafts) | AMFI TER JSON (terms ban "reverse engineering"); factsheet upload; typed | Regular→Direct now uses the NAV-measured gap, so TER matters only for comparing *different* funds | Factsheet upload when needed; leave the JSON off | Off |
| **U-15** | **Who sees the app; public showcase** | Only you / family / public demo | There is no family exemption in the RA/IA regulations. Public return claims are the most realistic way to get into trouble (verify R-missing). | Only you. Any demo uses synthetic data and makes no return claims. | Only you |
| **U-16** | **MF fill timing in backtests** | Next-day NAV (conservative) or same-day NAV | Same-day is valid only if you pay before the 3 pm cut-off with funds realised | Next-day | Next-day |
| **U-17** | **Optional permission letters** | NSE (marketdata@nse.co.in), NSE Indices, AMFI, IIMA authors | Free to ask; the answer may be no or never come | Send the AMFI letter (U-01) now; the others only if you want stock signals | None sent |

**Shortest path to a useful app:** answer U-01, U-02, U-03, U-05 and U-07, run U-12, and accept the defaults for the rest.

---

## 4. Performance and bug fixes to do first (ranked)

All of these are VERIFIED in the audits, except where marked. They are the first packages in the build (wave A), and the
signal engine depends on them.

| Rank | Problem | Evidence | Fix (package) |
|---|---|---|---|
| 1 | **Discovery is broken.** `build_universe` runs one COUNT per scheme (1,791 statements). `POST /api/discover` returned 504 after 300.1 s and killed the instance. | `audit-perf-hosted.md` | Batch: one query per instrument kind, a 60 s time budget, partial results flagged, no DB write per visit (**A02**) |
| 2 | **Database and function on different continents.** Turso primary is `iad1`, function is `bom1`: about 0.40 s per statement. `/api/data-health` takes 10.5–11.3 s. | `audit-perf-hosted.md` | New Turso database in `bom1` (runbook **A01**, you execute it, U-12) |
| 3 | **The session lookup blocks the event loop.** 2 statements per authenticated request, synchronous in async middleware. | `audit-perf-hosted.md` | Threadpool, plus update `last_seen` at most every 5 minutes (**A03**) |
| 4 | **The UI is served by the Python function, uncached.** `max-age=0`, MISS on repeat, 9 cold starts in about 90 s. | `audit-perf-hosted.md`; `audit-perf-frontend.md`; Vercel FastAPI docs (https://vercel.com/docs/frameworks/backend/fastapi): "Place files in a `public/` directory" | Serve `public/` from the CDN, copy the security headers into `vercel.json`, immutable cache on hashed assets (**A04**) |
| 5 | **One query per row** in data-health (25 statements) and instrument detail (8 serial statements) | `audit-perf-hosted.md` | One batched query each; add `/summary` and `?grid=monthly` endpoints (**A02**) |
| 6 | **Cold start about 6 s.** Runtime install of 40 dependencies (bundle > 225 MB), eager scipy import, 4 startup statements including writes | `audit-perf-hosted.md` | Read-only startup, lazy scipy in 4 engine modules (**A05**). Bundle size after the change is NOT VERIFIED. |
| 7 | **Frontend over-fetching.** Full NAV history (about 0.73 MB, synthetic measurement) fetched just to show a name; N+1 on the Fixed income tables; no shared cache; about 5 serial round trips on the landing page | `audit-perf-frontend.md` | `/summary` use, shared `useApi` cache, parallel requests, no cross-page imports (**A06**) |
| 8 | **Bug: the MoSPI CPI adapter fails for base 2024.** It uses `getCPIIndex` with `state_code=99`, a wrong field name and a missing label, and asks for credentials it does not need. | `audit-automation.md` | Use `getCPIData` and the "CPI (General)" label; no credentials (**A07**) |
| 9 | **Bug: 812 of 1,779 schemes have tax class UNKNOWN.** That includes 74 "Index Funds - Equity Funds", a plain false negative in `engine/candidates.py:843`. | `audit-journey.md` §2.2 | Fix the label, add a cited name-pattern table flagged `TAX_CLASS_INFERRED_FROM_NAME` (**A08**) |
| 10 | **Blocker: the host allowlist would refuse Vercel cron calls,** which also carry no session cookie and are GETs (ADR-0008) | `audit-journey.md`; `research-automation-infra.md` | A narrow `/api/cron/{job}` exception with a separate `CRON_SECRET` (**A03** + **B03**) |
| 11 | **The 98 s NAV refresh runs in the browser;** nothing is scheduled | `audit-journey.md` | Cron jobs J1–J5 (**B03**) |
| 12 | **Bug in docs:** stale "₹1 lakh" LTCG threshold for 1-Apr to 22-Jul-2024 at `docs/research/indian-instruments-and-tax.md` line 485; the repo YAML says ₹1.25 lakh | `verify-backtest-method.md` BT-3 | Fix (**A11**) |
| 13 | **Compliance bug:** RBI citations render as deep links, which the RBI disclaimer says need permission | `audit-automation.md` | Render as plain text (**A07**) |
| 14 | **Time bomb:** the XBOM trading calendar oracle ends 2026-12-31 | `verify-references.md` | Record a task to load the 2027 NSE holiday circular by hand (**B06**) |

After ranks 1–7, every endpoint gets a **statement-count test** in CI, so N+1 regressions fail the build (graft 17).

---

## 5. Work packages (28, in parallel git worktrees)

### 5.1 Rules for every agent

1. **One git worktree per package.** Never check out a branch in the live checkout.
2. **Each file has exactly one owner across the whole plan,** not just within a wave. Shared hot files are given to one
   package that does all the edits to them:
   - `security.py` (session fix *and* cron host exception) → A03;
   - `vercel.json` (headers *and* the `crons` array, which ships **disabled**: an empty `CRON_SECRET` returns 404) → A04;
   - `api/routes.py` (switched to **autodiscovery** of `api/routes_*.py`) → A05, so later packages only *add* router files;
   - `data/fetch.py` allowlist and `data/registry.py` → A07;
   - all new tables → A10;
   - `App.tsx` → C01.
3. Engine code is pure: Decimal for money, no clock, IO or randomness, and it must pass
   `backend/tests/unit/test_engine_purity.py`.
4. Python runs as `backend/.venv/bin/...`. Frontend scripts run as `node --run <script>`, never `pnpm <script>`.
5. Tests are hermetic with **synthetic fixtures**. No real market data, no scheme-named results and no backtest outputs
   are committed: the repo is public.
6. The interfaces between packages are the frozen dataclasses in `design-risk-first.md` §5 and §7.1, amended by the grafts
   below. Wave-A packages code against those signatures.
7. A gate that is not built returns `gate_not_implemented`, which fails closed.

### 5.2 Wave A: performance, foundations and the pure engine (18 packages, no dependencies, all start together)

| WP | Goal | Files owned | Tests required | Acceptance checks |
|---|---|---|---|---|
| **A01** | ADRs, decisions register, methodology, Turso runbook | `docs/architecture/architecture-decision-records/0014-scheduled-jobs.md`, `0015-risk-budget-engine.md`, `0016-signal-registry-and-gates.md`, `0017-data-rights-equity-index-amfi-hosted.md`, `0018-private-wording-and-surfaces.md`, `0000-index.md`; `docs/product/decisions-register.md` (U-01…U-17); `docs/forecasting/backtest-methodology.md`; `docs/operations/turso-bom1-move.md`; `docs/operations/amfi-permission-letter-draft.md`; `scripts/turso_latency_probe.py` | Probe script has a unit test with a fake client | ADR-0017 records as NOT VERIFIED: AMFI hosted storage, the niftyindices stress-constant provenance, and the NSE "simulation" ambiguity. The probe prints per-statement latency before and after. The ADRs are accepted by you. |
| **A02** | Backend N+1 fixes (ranks 1 and 5) | `backend/src/iip/services/discovery.py`, `backend/src/iip/api/routes_core.py`, `backend/src/iip/services/instruments.py`; `backend/tests/services/test_discovery_batching.py`, `backend/tests/api/test_core_batched.py` | Statement count measured with a fake driver; time-budget abort test | Universe build uses ≤ 10 statements regardless of scheme count. Data-health ≤ 3. Instrument detail ≤ 2. `/instruments/{id}/summary` and `?from=&grid=monthly` exist. Budget overrun returns flagged partial results, not a 504. No DB write per Discovery visit. |
| **A03** | Security middleware | `backend/src/iip/api/security.py`; `backend/tests/security/test_session_offloop.py`, `test_cron_host_exception.py` | Concurrency test (a slow session lookup doesn't block a second request); throttle test | `last_seen` written at most once per 5 min (PARAMETER). `VERCEL_URL` host accepted **only** on `/api/cron/*` with a valid bearer; every other route still returns 400. Wrong secrets are rate-limited. |
| **A04** | CDN static assets and `vercel.json` | `vercel.json`, `scripts/vercel-build.sh`, `app.py` (repo root), `public/` build wiring; `backend/tests/hosted/test_static_headers.py` | Header-equality test against today's set | Hashed assets get `immutable` caching and x-vercel-cache HIT on repeat (checked after deploy). Security headers unchanged. `crons` J1–J5 present but return 404 until a secret is set. |
| **A05** | Startup, router autodiscovery, lazy scipy | `backend/src/iip/api/app.py`, `backend/src/iip/api/routes.py`, `backend/src/iip/store/db.py` (startup path only); import lines only in `engine/fixed_income.py`, `engine/returns.py`, `engine/forecasting/validation.py`, `engine/stats/metrics.py`; `backend/tests/unit/test_lazy_imports.py`, `backend/tests/api/test_router_autodiscovery.py` | `import iip.api.app` must not import scipy; a startup test asserts zero writes | Every existing route is still registered (a route-table snapshot test). Cold-start statements = 0 writes. |
| **A06** | Frontend fetch and cache | `frontend/src/lib/useApi.ts`, `frontend/src/lib/api.ts`, `frontend/src/pages/Risk.tsx`, `Scenarios.tsx`, `FixedIncome.tsx`, `Overview.tsx`, `Watchlist.tsx` and their `*.test.tsx` | Vitest: de-duplicated GETs, one request per table, parallel landing requests | No page fetches a full history to show a name. Fixed income tables make 1 request. No cross-page module imports. Build stays reproducible. |
| **A07** | Official automatic sources: MoSPI CPI and RBI T-bill RSS | `backend/src/iip/data/mospi.py`, `backend/src/iip/data/rbi_tbill.py` (new), `backend/src/iip/data/parsers/rbi_pr.py` (new), `backend/src/iip/data/registry.py`, `backend/src/iip/data/fetch.py`; `backend/tests/data/test_mospi_base2024.py`, `test_rbi_tbill.py` | Synthetic fixtures for base 2012 and 2024. The T-bill self-check `(100−P)/P × 365/days` reproduces published yields to 4 dp; a mismatch abstains. | No credentials needed. Honest user-agent, no `robots.txt`-sensitive paths. RBI citations rendered as plain text. Registry entries carry licence class and status. |
| **A08** | MF tax-class fix | `backend/src/iip/engine/candidates.py` (classification functions only; add keyword `name: str \| None = None` so callers in `services/analysis.py` stay unchanged), `backend/src/iip/rules/mf_categories.yaml`, `backend/src/iip/rules/index_name_patterns.yaml` (new, cited); `backend/tests/unit/test_mf_classification.py` | Table-driven fixtures for every pattern; inferred classes flagged | The 74 "Index Funds - Equity Funds" schemes classify as equity. Name-pattern inference carries `TAX_CLASS_INFERRED_FROM_NAME`. Unknown stays UNKNOWN (no guessing). Measured on today's AMFI file in memory, not stored. |
| **A09** | AMFI survivorship probe and history start dates | `backend/scripts/probe_amfi_closed.py` (new), `backend/src/iip/data/parsers/amfi_navhistory.py`, `backend/src/iip/data/parsers/amfi_scheme_master.py`; `docs/data/probes/amfi-closed-schemes.md`; `backend/tests/data/test_amfi_scheme_status.py` | Parser tests on synthetic closed-scheme rows | A VERIFIED or NOT VERIFIED answer on whether closed and merged schemes appear in AMFI history. Earliest NAV date per U1 role (needed for the stress recompute and test lengths). Regular-plan history before 2013 is labelled. |
| **A10** | Schema migration 0004 and repositories | `backend/src/iip/store/migrations/0004_risk_signals.sql`, `backend/src/iip/store/ledger.py` (new), `backend/src/iip/store/goals_repo.py` (new); `backend/tests/store/test_migration_0004.py`, `test_ledger_append_only.py` | Applies on SQLite **and** libSQL; append-only trigger tests | Tables: `goals`, `holding_goal_map`, `risk_profile`, `user_tax_context`, `policy_versions`, `decisions_log` (with `cas_confirmed`), `series_grid`, `cron_runs`, `signal_snapshots`, `notification_outbox`, `signal_rules`, `rule_role_bindings`, `backtest_trials` (UPDATE of params or snapshot hash and DELETE abort), `backtest_runs`, `rule_evaluations` (shadow ledger), `outcomes`, `restatements`. Repositories batch their writes. |
| **A11** | Rule tables, loader and historical tax rows | `backend/src/iip/rules/risk/stress_drawdowns.yaml` (schema plus a citation pointer; values loaded from local config per U-08), `backend/src/iip/rules/risk/allocation_policy.yaml` (structure only), `backend/src/iip/rules/costs/india_equity.yaml`, `backend/src/iip/rules/tax/india.yaml`, `backend/src/iip/rules/loader.py`; `docs/research/indian-instruments-and-tax.md` (line 485 fix only); `backend/tests/unit/test_rules_risk.py`, `test_tax_history_rows.py` | The loader rejects rows without source, status and `effective_from`; existing tax tests stay green | Pre-2024 rows cite primary sources and are NOT VERIFIED until a CA reviews them. ₹1.25 lakh applies for 1-Apr to 22-Jul-2024. Lots bought on or before 31-Jan-2018 abstain. The ETF STT row is NOT VERIFIED (verify BT-4). |
| **A12** | `engine/risk/`: emergency gate, goal-date safety, loss budget, limits, stress combinator | `backend/src/iip/engine/risk/__init__.py`, `emergency.py`, `goal_date.py`, `budget.py`, `limits.py`, `stress.py` (new); `backend/tests/unit/test_risk_budget.py`, `test_risk_limits.py`, `test_risk_stress.py` | Fixtures for `design-risk-first.md` §5.1–5.5, including the 34 % fictional example | `e_cap = (b − s_d)/(s_e − s_d)`, floor-rounded. All equity sleeves correlated at 1, hybrids treated as 100 % equity. ABSTAIN when even 0 % equity breaches the budget. **Stress per class = max(cited value, AMFI-recomputed drawdown)**, with both values and the series start date returned. No sale is ever triggered by a drawdown. |
| **A13** | `engine/stats/series_grid.py` | new file; `backend/tests/unit/test_series_grid.py` | Property tests: month-end selection, gaps, MDD and recovery durations | Blended path, MDD and recovery years computed in Decimal. Gold drawdown recomputable from AMFI NAVs. |
| **A14** | `engine/actions/`: rebalance and next-rupee planner | `backend/src/iip/engine/actions/rebalance.py`, `next_rupee.py` (new); `backend/tests/unit/test_rebalance.py`, `test_next_rupee.py` | Oracle tests (independent re-implementation per ADR-0011) | Cash-flow-first. FIFO per folio: the engine chooses only between schemes and folios, never between lots in a folio. The next-rupee result respects L1 → L5 order. |
| **A15** | `engine/actions/`: tax and cost actions | `backend/src/iip/engine/actions/tax_actions.py`, `regular_direct.py` (new); `backend/tests/unit/test_tax_actions.py`, `test_regular_direct.py` | Break-even fixtures from `research-evidence-mf.md` §4.2; NAV-gap fixtures | LTCG harvest stops at the first short-term FIFO lot. ELSS is excluded. Feb–Mar window is a PARAMETER. "Lot turns long-term within 45 days → wait" modifier. Regular→Direct: `g_12m` from both plans' NAVs, options (d) redirect SIP first, (b) LT lots inside the exemption, (c) argmin wait date, (a) all now. Abstains on an unknown exit load for lots under 365 days. Tax-loss harvesting stays off. |
| **A16** | ActionCard contract, templates, ranking, "Needs from you" | `backend/src/iip/engine/actions/contracts.py`, `cards.py`, `ranking.py`, `needs.py` (new); `backend/src/iip/rules/action_templates.yaml`; `backend/tests/unit/test_cards.py`, `test_card_linter.py`, `test_needs_ranking.py` | **A unit test asserts that ActionCard has no `expected_return` field.** A template linter rejects forecast language in policy-card text. | Every number slot carries a `fact_id` or `formula_id`. Ranking key: (layer, deadline, ₹ impact, card_id); ₹ is never added across different bases. "Nothing needs doing today" is a valid result. Needs ranked by the ₹ upper bound each input unlocks. |
| **A17** | `engine/backtest/`: lot ledger, equity costs, tax lots | `backend/src/iip/engine/backtest/__init__.py`, `ledger.py`, `costs_equity.py`, `tax_lots.py`; `backend/tests/unit/test_backtest_ledger.py` | Fixtures C-1 (₹237.8212 on ₹1 lakh) and T-1 (₹4,160 / ₹2,600 / ₹0) | Decimal only. FIFO enforced. Terminal liquidation in both modes. Costs marked `costs_estimated` where unverified, which caps the state. |
| **A18** | `engine/backtest/stats_gates.py`: DSR, multiple testing, power | new file (stdlib `statistics.NormalDist`, no scipy); `backend/tests/unit/test_stats_gates.py` | Fixtures DSR-1 (0.9004 / 0.9505), MT-1, MT-2, MT-3 and the 298-month power case | Holm, HAC t, MinTRL, the 80 %-power length and "earliest possible review = registration + max(30, MinTRL) months" are computed. **PBO/CSCV and Hansen SPA return `gate_not_implemented`** (deferred, fail closed). |

### 5.3 Wave B: services, API, jobs (6 packages; start after wave A merges)

| WP | Goal | Depends on | Files owned | Tests required | Acceptance checks |
|---|---|---|---|---|---|
| **B01** | Goals, risk profile, tax context, six-answer setup API | A05, A10, A12 | `backend/src/iip/services/goals.py` (new), `backend/src/iip/api/routes_goals.py` (new); `backend/tests/api/test_goals_api.py` | CRUD, mapping, CSRF and session behaviour identical to the other routes | Loss limit stored in ₹ per goal. The response shows the stress history *before* any return figure. Policy refuses to load without user-set values. |
| **B02** | Risk snapshot (J4 compute), shadow evaluation, outcomes, Today API | A10–A16, A13 | `backend/src/iip/services/risk_snapshot.py`, `backend/src/iip/services/shadow.py`, `backend/src/iip/services/outcomes.py` (new); `backend/src/iip/supervisor/manifest.py`; `backend/src/iip/api/routes_today.py` (new: GET today, GET needs, POST "I did this"); `backend/tests/services/test_risk_snapshot.py`, `test_shadow_ledger.py` | Byte-identical snapshot on re-run; per-goal abstention; ABSTAIN snapshots stored | Today is read in **1 statement**; the engine never runs on page load. Every registered S rule gets a daily `rule_evaluations` row and is **never** shown as an action. Outcomes are scored at the rule's horizon. Snapshots are content-addressed. |
| **B03** | Cron route and jobs J1–J5, claims, outbox | A03, A04, A07, A09, A10 | `backend/src/iip/api/routes_cron.py`, `backend/src/iip/services/cron.py` (new); `backend/tests/hosted/test_cron.py` | Stale-`running` takeover; outbox reaper never resends; duplicate delivery is a no-op; run_key derived after a cheap conditional fetch | Each job is one resumable step of at most 90 s that catches up since the last success. Production only. Live check recorded: Host header and Deployment Protection behaviour (NOT VERIFIED until tested). Vercel Hobby: "Hobby accounts are limited to daily cron jobs" (https://vercel.com/docs/cron-jobs/usage-and-pricing). |
| **B04** | Ping-only notifications and surface-aware compliance | A07, A10, A16 | `backend/src/iip/services/notify.py` (new); `backend/src/iip/rules/compliance_phrases.yaml`; `backend/src/iip/supervisor/compliance.py`; `backend/tests/security/test_notify_ping_only.py`, `test_compliance_surfaces.py` | A sentinel test: no ₹ amounts, scheme names or buy/sell words ever appear in a ping | `IIP_NOTIFY=off` by default. A ping fires only when the L1–L5 card set changes. BLOCK phrases kept on export and share surfaces. The neutral vocabulary is the default (U-11). |
| **B05** | Backtest runner, walk-forward, gates, pre-registered signals, local CLI | A11, A13, A17, A18, A10 | `backend/src/iip/engine/backtest/walkforward.py`, `gates.py` (new); `backend/src/iip/services/backtest_runner.py`; `backend/src/iip/backtest_cli.py`; `backend/src/iip/rules/signals/schema.yaml`, `S-E@1.yaml` (10-month trend), `S-D@1.yaml` (12-1 absolute momentum **vs a liquid-fund NAV hurdle**, not T-bills), `S-F@1.yaml`, `S-G@1.yaml` (role names only); `backend/tests/services/test_backtest_runner.py` | A synthetic zero-skill fixture ends in ABSTAIN/NO_SIGNAL; shuffle canary; re-running a manifest reproduces `output_hash` | `lag`, `purge`, `embargo` and `fill_rule` are **mandatory arguments with no default**. G1–G14 fail closed with reason codes. Regimes defined on pre-vault data only. Trials logged automatically. **Backtests run only in the local CLI.** Hosted mode imports evidence bundles that hold no raw NAVs. Results are never written into the repo. |
| **B06** | Core-universe tracking, CAS gaps, exit-load grammar | A08, A09, A10 | `backend/src/iip/services/ingestion.py`, `backend/src/iip/services/cas.py`, `backend/src/iip/data/parsers/sid_exit_load.py` (new); `backend/src/iip/rules/core_universe.yaml` (roles only, no scheme codes); `backend/tests/services/test_core_universe.py`, `backend/tests/data/test_sid_exit_load.py` | Grammar tests: documented phrasings parse, everything else abstains | U1 is auto-tracked without manual backfill, but only after U-07 is confirmed. Local-first per U-01. Regular-plan ISINs accepted. Exit loads charged in the CAS recorded as observed facts. A new CAS confirms or contradicts "I did this" entries. The 2027 holiday-calendar task is recorded. |

### 5.4 Wave C: frontend (4 packages; can start against typed stubs, merge after wave B)

| WP | Goal | Depends on | Files owned | Tests required | Acceptance checks |
|---|---|---|---|---|---|
| **C01** | **Today** page, ActionCard, Needs from you, routing | B02 | `frontend/src/App.tsx`, `frontend/src/pages/Today.tsx`, `frontend/src/components/ActionCard.tsx`, `frontend/src/components/NeedsList.tsx`, `frontend/src/lib/types-actions.ts`, plus tests | Vitest + a11y; "No action needed" and ABSTAIN render as first-class states | `/` is Today. Every number opens its formula and source in the ExplainDrawer. "I did this" button. Today loads in 1 API call. |
| **C02** | Goals and onboarding (one upload, about six answers) | B01 | `frontend/src/pages/Goals.tsx`, `frontend/src/pages/Onboarding.tsx`, `frontend/src/lib/types-goals.ts`, plus tests | The loss-limit step shows crash history before any return figure | Setup completes with a CAS and about six answers. The 20–25 % aim appears only on the feasibility view, as historical frequency. |
| **C03** | Signals registry and Rule detail | B02, B05 | `frontend/src/pages/Signals.tsx`, `frontend/src/pages/RuleDetail.tsx`, `frontend/src/components/GatePanel.tsx`, `frontend/src/lib/types-signals.ts`, plus tests | Every row renders ABSTAIN with its failing gate | Shows the shadow record, trial count, MinTRL next to the 80 %-power length, "earliest possible review: YYYY-MM", the post-publication tag and the ×0.5 decay haircut. No BUY/SELL badge unless U-11 opts in. |
| **C04** | Settings: notifications, vocabulary, data rights | B04 | `frontend/src/pages/Settings.tsx`, `frontend/src/components/DataRightsPanel.tsx`, plus tests | Default off; each source shows its licence and status label | Notification channel and vocabulary opt-in. A panel lists every source as VERIFIED, NOT VERIFIED, REQUIRES CONFIGURATION or BLOCKED, with the decision that unblocks it. |

**Totals:** 18 + 6 + 4 = **28 packages**.

**Critical path:** A10 + A11 + A12 + A16 → B02 → C01. Data feeding runs A07 + A09 → B03.

**Milestones you will see:**
- **M1** (wave A merged, U-12 executed): a fast app, and Discovery that returns.
- **M2** (B01, B02, B06): the Today page with ₹ cards from your CAS and your answers.
- **M3** (B03, B04): it refreshes itself every morning; an optional ping.
- **M4** (B05, C03): the signal registry with honest ABSTAIN statuses and a growing shadow record.

### 5.5 Optional packages, gated on your decisions (not counted in the 28)

| Id | Goal | Gate |
|---|---|---|
| X-01 | Read the Upstox and Angel One developer terms; then a local-only candle adapter with freeze-and-diff (split rescaling rewrites history, verify BT-7) | U-10 = (b) or (c) |
| X-02 | Local, read-only broker holdings sync. A static IP is needed only for orders (Zerodha FAQ, verify R12). | U-10 |
| X-03 | Web Push (VAPID) | U-09 |
| X-04 | Optional IIMA factor-evidence panel (manual import, release pinned by hash, HML sign asserted) | Your request |
| X-05 | PBO/CSCV and Hansen SPA implementation | A rule first reaches G9 |
| X-06 | Factsheet and portfolio-file parsers (duration, YTM, credit mix) | Debt-fund cards needed |

---

## 6. What is explicitly NOT built, and why

| Not built | Why | Source |
|---|---|---|
| Single-stock buy/sell signals, screeners | No lawful, survivorship-free, point-in-time, dividend-adjusted data on any free route; gates G2/G3 cannot pass | `research-equity-data-nse.md`; `research-equity-data-alt.md`; verify EQ-6 |
| Automated NSE/BSE/niftyindices downloads; jugaad-data, nsepython, nselib, nsetools, eod2, yfinance | Terms ban automated collection; Yahoo bans it "for any purpose" | NSE ToU (https://www.nseindia.com/static/nse-terms-of-use); `research-references.md` |
| Kite Connect, Dhan or any paid feed | Breaks the no-paid-keys rule; Kite terms forbid "build databases, or otherwise create permanent copies" (https://kite.trade/terms/) | `research-equity-data-alt.md` |
| Fundamentals scoring (F-score, accruals, PEAD), pledge-based signals | Weak or in-sample evidence; no point-in-time data. Regulatory-threshold disclosures only, worded as facts. | `research-fundamentals-data.md`; verify FD-3, FD-4 |
| Index P/E valuation bands | niftyindices copy clause | verify MOM-8 |
| Stop-losses, volatility targeting, drawdown-triggered selling | Failed out of sample; no Indian after-tax test; sizing ahead of a fall replaces them | `research-evidence-allocation.md`; verify EA-3 |
| Mean-variance optimiser | Loses to simple weights out of sample (DeMiguel et al. 2009) | `research-evidence-allocation.md`; verify EA-7 |
| Kelly sizing and the "over-betting warning" | Without leverage, f* ≈ 1.5 never fires; the range −0.11 to 3.11 is useless | `design-judgement.md` §2.4 |
| Factor timing, category rotation, "top fund" switching, rate-cycle duration calls | No robust evidence; persistence is weak | `research-evidence-mf.md`; verify MF-2, EVQ-9 |
| Dual momentum and loser-exit rules as day-one seeds | Extra trials, no expected value; revisit if the A09 probe passes | `design-judgement.md` §2.4 |
| Order placement or algo execution, any mode | Every API order needs a static IP whitelisted with the broker, and Vercel's static IPs are shared; exchange registration below the threshold is NOT VERIFIED (verify R5) | `research-regulation.md` |
| Exports or shares of named-security signals; public return claims | The RA "trading calls" definition and the prohibited-activity rules | `research-regulation.md` §8.1 |
| Tax-loss harvesting | Set-off rows under the Income-tax Act 2025 are not verified | `design-user-first.md` §4.3 |
| An LLM producing any number | Binding rule; optional wording is off by default | ADR-0007 |
| "Probability of profit" or expected-return fields on cards | ADR-0010. The ActionCard has no `expected_return` field, and a test enforces this. | A16 |
| ntfy.sh public topics, Gmail SMTP, GitHub Actions as the worker | Spoofable, a credential with a large blast radius, or unreliable with public logs | `research-automation-infra.md` |
| Backtests on Vercel | 300 s limit; raw NAVs must not be hosted; local CLI only | `design-evidence-first.md` §6.3 |
| Hosted AMFI tracking beyond your holdings, by default | AMFI storage clause; registry line 91 | U-01 |
| G-sec, SDL and CCIL quote automation; CRISIL ratings | BLOCKED sources | `audit-automation.md` |

---

## 7. Open items (NOT VERIFIED until tested)

- Turso latency after the move to `bom1`; Vercel bundle size after the lazy imports.
- The cron Host header and Vercel Deployment Protection behaviour on the first live run (B03).
- Whether the AMFI terms' "significant portion" and "derivative works" clauses reach hosted storage of a capped universe
  (U-01).
- Whether derived drawdown statistics fall under the niftyindices copy clause (U-08).
- Whether a private backtest is a "simulation activity" under NSE's ToU (verify NSE-2). This matters only if equity data
  is ever used.
- Upstox and Angel One developer terms on storage and backtesting (X-01).
- ETF STT treatment; pre-2024 tax rows (CA review); Income-tax Act 2025 section mapping (verify EVQ-7).
- The start date of AMFI NAV history for older index funds, and whether closed schemes appear (A09).
- Bounds for hybrid fund categories (treated as 100 % equity until they are cited).

---

## 8. Your decisions (recorded 2026-10-16)

| Id | Decision |
|---|---|
| U-01 | Local-first auto-tracking of the core universe. Hosted stores only held and watched schemes. A01 drafts the AMFI permission letter for you to send. |
| U-06 | Gates kept as written, frozen before any run. |
| U-10 | (a) No stock data. Stocks ABSTAIN. |
| U-11 | Neutral wording ("entry/exit condition met"). |
| U-12 | Move Turso to `bom1` now, via the A01 runbook after a dry run on a copy. You run the account steps. |
| All other U-ids | The "Default until decided" column in §3. |
