# Design: the user-first signal engine, a daily "what to do" digest across all your money

Wave 1 · design "user-first" · written 2026-10-15 · repo state `8f56a8d` (main) · no repo file other than this one was changed

Status labels: **VERIFIED** (code read, measured, or primary source read on 2026-10-15) · **VERIFIED-SECONDARY** (quoted from a
secondary page or from a wave-1 report that cites its source) · **NOT VERIFIED** · **REQUIRES CONFIGURATION** · **BLOCKED**.

Unless a URL is given here, every external fact below comes from the wave-1 report named next to it, which holds the URL, the access
date (2026-10-15) and the quote. Where a wave-1 verifier **weakened** a claim, this design uses the weakened version. §14 lists each
one and how it was applied. No wave-1 claim used here was refuted, apart from R9 in `research-references.md`, which this design does
not use.

---

## 0. The answer in one page

**What you asked for:** something that tells you, without data entry, what to do with your money: signals, mutual funds, and when to
buy and sell, aiming at 20–25 %/yr.

**What the evidence allows**, from `research-evidence-mf.md`, `research-evidence-allocation.md`, `research-backtest-method.md`,
`research-evidence-momentum.md` and `research-evidence-value-quality.md`:

1. **Most of the rupees you can actually gain come from actions that need no forecast.** These are cost (Regular→Direct, the cheaper
   plan of the same scheme), tax timing (LTCG harvesting, waiting until a lot turns long-term), safety (emergency fund, deposit-insurance
   limits, maturities) and discipline (rebalancing bands, cash-flow-first rebalancing, matching duration to horizon). All of these are
   deterministic arithmetic on your own holdings and your own rules. This design calls them **rule actions**. They are built first.
2. **Market-timing "signals" (buy now, sell now) have no out-of-sample, after-cost, after-tax support for India in any source found.**
   This covers trend filters, momentum timing, volatility targeting, stop-losses, category rotation, rate-cycle duration calls, fund
   "winners" and every single-stock rule. The engine therefore keeps a **signal registry with twelve evidence gates** and runs every
   candidate in **shadow mode**. It shows you "ABSTAIN: needs X more months of evidence, earliest possible date Y" instead of a made-up
   call. If a rule ever passes, it appears automatically.
3. **Single stocks: BLOCKED for automated data, ABSTAIN for signals.** NSE's terms forbid automated collection. The free broker
   route (Upstox) is **REQUIRES CONFIGURATION**, must stay local-only, has no delisted stocks and does not adjust for dividends
   (`research-equity-data-alt.md`, verifier EQ-6). For stocks you hold, the app still does tax lots, the shared ₹1.25 lakh LTCG pool
   and concentration checks, but it gives no buy/sell timing.
4. **Your inputs drop to about six answers plus one CAS upload.** Everything else is fetched automatically from sources whose terms
   allow it: AMFI NAVs, MoSPI CPI and RBI T-bill cut-offs. A daily Vercel cron precomputes everything. The landing page becomes
   **Today**, a single stored row that loads in one statement, plus a content-free phone ping.
5. **The 20–25 % aim is shown as a feasibility range, never as a target the engine optimises.** On Nifty TRI history since
   1995/2005, 5–18 % of rolling 10-year windows reached 20 %/yr and none reached 25 %. That history holds only about 2 independent
   10-year windows, and the scope matters: pre-1992 Sensex was higher (verifier EA-1).

**The success test, from `audit-journey.md` §7:** on a fresh install, with only a CAS imported and the six setup answers given, by the
next morning Today shows either ranked actions with ₹ effects or a reasoned abstention, with no other manual data entry.

---

## 1. Vocabulary: rule actions, signals and notices

The binding rule says "a signal may only exist if a documented, out-of-sample, cost- and tax-aware backtest supports it". This
design keeps that rule exactly, and draws one line that you need to accept (decision **D1**, §13):

| Output class | Definition | Needs a backtest? | Example | Shown as |
|---|---|---|---|---|
| **Rule action** | The arithmetic consequence of a rule *you* adopted (target allocation, band, emergency months), or a cost/tax fact that holds by construction. **It makes no claim about future returns.** | No. It must make no return claim, it must show its cost and tax, and it abstains when context is missing | "Equity is 8.2 pp above your 60 % target (your band: 5 pp)"; "Same scheme, Direct plan: ₹3,140/yr lower cost on the last 12 months of NAVs" | Action card |
| **Signal** | Any output that implies a timing or selection edge ("now is a good time", "this fund will do better") | **Yes: G1–G12 (§6)** | "Trend rule T-1: exit condition met" | Signal card, only if `ACCEPTED`; otherwise an evidence-status line |
| **Notice** | Descriptive fact, no instruction | No | "Scheme renamed / category changed in AMFI file"; "Fund trailed its index-fund proxy 3 years running (review flag)" | Notice line |

The engine is built so that a rule action **cannot** carry return-forecast fields. The `ActionCard` type has no `expected_return`
field, and a unit test enforces this. A rule that needs one must be a signal.

---

## 2. Data layer: only sources whose terms permit the use

### 2.1 Automatic sources (no typing)

| Source | What it gives | Terms posture | Automation | Status |
|---|---|---|---|---|
| AMFI `NAVAll.txt` | Latest NAV for every scheme, incl. ETFs, Regular and Direct plans, IDCW | "personal and non-commercial use only"; "shall not store electronically any significant portion" (source-registry line 88) | Daily cron J1/J2 | **VERIFIED** adapter exists. **Hosted storage tension:** source-registry line 91 says to treat any hosted deployment as "REQUIRES LICENCE / WRITTEN PERMISSION", and the verifier of `research-automation-infra.md` flagged that this was never reconciled. This is decision **D2** |
| AMFI NAV history | Backfill for **tracked** schemes only (held, watched, siblings of held, core index set ≤ 40) | as above; minimisation keeps it far below a "significant portion" | Cron J3, gap fill only | **VERIFIED** adapter; the size of the core set is decision **D3** |
| MoSPI eSankhyiki CPI | CPI index + YoY, base 2012 and base 2024 | API intended for programs; reproduction to others needs permission | Cron J3 (monthly; data published the 12th) | **VERIFIED** by probe. The existing adapter is **broken for base 2024** (`audit-automation.md` §3.1, defects 1–5) and is fixed in WP-08 |
| RBI Press Releases RSS | 91/182/364-day T-bill cut-off yields (the risk-free series) | RBI offers RSS for "automatic site updates"; store only extracted figures, never HTML; render citations as text, not deep links (`audit-automation.md` §2.3) | Polled in J1 and J5 (the feed keeps only about 10 items, so one daily poll can miss a Wednesday). On a miss, a Data-health line offers a user-triggered listing fetch | **VERIFIED** feed + formula self-check `(100−P)/P × 365/days` reproduces 3/3 published yields |
| User CAS PDF (CAMS/KFintech) | Holdings, every purchase lot, SIP pattern, Regular/Direct plan, folio | Your own data | Upload; a monthly reminder in the digest | Implemented, **NOT VERIFIED** on a real statement; Regular/IDCW ISIN gap fixed in WP-11 |

### 2.2 User-supplied documents (one upload replaces typing; no crawling)

This follows the pattern in `audit-automation.md` §2.2: you download the file in your browser, drop it in, a deterministic parser
extracts values with page/cell references and SHA-256, and you confirm with one tap. No LLM is involved.

| Document | Replaces | Status |
|---|---|---|
| AMC monthly portfolio file | Lowest rating, share below AAA, share sovereign+cash (computed from holdings rows) | REQUIRES CONFIGURATION per AMC layout (P1 in the audit) |
| SID "Load Structure" (for **held** schemes only) | Exit load (strict grammar; abstain on anything unrecognised) | WP-12 |
| AMC factsheet PDF | Modified/Macaulay duration, YTM | P2; optional, because §4.6 uses SEBI category bands first |

### 2.3 Sources this design does **not** use

| Source | Why | Status |
|---|---|---|
| NSE website, bhavcopy automation, JSON APIs, nsepy/jugaad/nsetools/nselib/eod2 | NSE ToU: "prohibited to conduct any systematic or automated data collection activities" (`research-equity-data-nse.md`) | **BLOCKED** |
| Manual NSE bhavcopy import | The ToU download carve-out ("Unless the information or Content is available for download…") makes this ambiguous, not banned. But "stored … in an electronic retrieval system" and "simulation activities" may still apply (verifiers NSE-2, NSE-6, BT-5) | **NOT VERIFIED**. Not built; decision **D7** |
| niftyindices.com TRI / P/E | ToU: "personal, non-commercial use only"; no copying/uploading "without prior written permission" (verifier MOM-8) | Optional **local-mode-only** manual import for the evidence panel; never in hosted Turso |
| BSE | "reproduction, redistribution or transmission" prohibited (verifier FD-1 says this is a conservative reading, not an automation ban) | Not used |
| Yahoo / yfinance | ToU bans automated collection | **BLOCKED** |
| Upstox (free), Angel One SmartAPI (free) | The licensed route on your own account. Developer terms on storage/backtesting are unread. Upstox adjusts only splits/bonus, and it rescales history retroactively. No delisted equities | **REQUIRES CONFIGURATION**, local-only (a conservative policy choice; verifier EQ-7) |
| Kite Connect (₹500/month) | Breaks the no-paid-keys rule; terms forbid "build databases, or otherwise create permanent copies" (verifier R12) | Excluded |
| AMFI TER JSON endpoint | AMFI ToU says "No reverse engineering" | Off by default; decision D8. **Not needed**: §4.4 measures the cost gap from NAVs instead |
| CCIL / FBIL G-sec quotes, CRISIL ratings, bank FD card pages (SBI) | Terms forbid automation | **BLOCKED**; paste-assist only (existing) |
| Trading Economics | "limited, personal, nontransferable" licence (verifier EA) | Not used |

### 2.4 Storage rules (all modes)

- Observations are stored only for tracked series, with provenance (`source_id`, `retrieved_at`, `raw_sha256`, quality status).
  This is existing behaviour.
- Every engine run reads a **content-hashed snapshot manifest** (series ids + last observation date + hash). This answers verifier
  BT-7: vendor history can change, so a run must be reproducible from its manifest.
- No exchange-derived data in hosted Turso, the public repo or exports (`research-regulation.md` §8.1).

---

## 3. Universe: what the engine looks at

Today's measured gap (`audit-journey.md` §2.2, VERIFIED): of 1,779 in-scope schemes, 812 have tax class UNKNOWN, 93 have a known exit
load, and Discovery needs 60 stored NAVs, so it cannot discover anything.

| Tier | Members | How it gets data | Purpose |
|---|---|---|---|
| U1 Held | Every scheme/ETF/stock/FD/T-bill in your CAS or ledger | NAVAll daily + history backfill | All rule actions |
| U2 Siblings | For each held **Regular** plan, its **Direct-Growth** sibling (same AMC, same normalised scheme name, exactly one match, otherwise abstain) | NAVAll + 13-month backfill | Cost-gap measurement (§4.4) |
| U3 Core index set | One Direct-Growth index fund/ETF per broad index family (Nifty 50, Nifty Next 50, Nifty 500 or Total Market, Midcap 150, Smallcap 250, a gilt/G-sec index fund, a liquid and an overnight fund, a gold ETF), plus the momentum and quality factor trackers. Cap ≤ 40 schemes | NAVAll + full backfill | Benchmarks/proxies, allocation consequences, shadow signal evaluation |
| U4 Watched | Your watchlist | as U1 | Notices only |

Universe fixes (WP-10):
- `"Index Funds - Equity Funds"` → `EQUITY_ORIENTED`. This is a plain false negative today (74 schemes).
- A cited name-pattern table for `"Other Scheme - Index Funds"` (Nifty/Sensex/Midcap/Smallcap → equity; Gilt/SDL/G-Sec/Bharat
  Bond/CRISIL IBX → debt), flagged `TAX_CLASS_INFERRED_FROM_NAME`. Any name matching neither or both lists stays UNKNOWN.
  Coverage is NOT VERIFIED until it is measured after the build.
- `prune_untracked_history` keeps U1–U4.
- The 60-NAV gate stays for statistics, but rule actions on held schemes need only the latest NAV.

---

## 4. Rule actions: exact formulas (parameters fixed in rule tables, versioned)

All functions are pure. They live in `backend/src/iip/engine/actions/` so they inherit the engine's determinism checks: Decimal only,
no clock, no IO, `as_of` taken from data. Rounding follows ADR-0002. Each rule has a version; its parameters live in
`rules/actions/policy.yaml` (ADR-0009 convention: `effective_from`, source, status).

Notation: `V` = market value at `as_of` NAV. A **lot** is `(scheme, folio, buy_date, units, cost)`. Redemption within one
scheme+folio is **FIFO** (CBDT Circular 768 / RTA practice; verifier EA-6), so the engine never "picks lots" inside a folio. It
chooses only **which scheme/folio** to redeem from, and then takes that folio's FIFO prefix.

`fifo_prefix(folio, units)` gives the lots consumed. `gain(lot) = units × NAV − cost`. `LT(lot)` means held > 12 months for
equity-oriented schemes. Debt specified-MF units bought on/after 2023-04-01 are slab-taxed whatever the holding period (VERIFIED,
repo tax doc).

### 4.1 E-1 Emergency fund gate (priority class P1)

```
target      = months × essential_monthly_expenses        # both user inputs; months default range 3–6, labelled "US SEC Investor.gov guidance"
reserves    = Σ V(liquid, overnight, money-market funds tagged to the Emergency goal) + Σ user-entered bank/sweep balances (optional)
shortfall   = max(0, target − reserves)
```
- Card when `shortfall > 0`. The impact basis is `shortfall`. The options are: (a) direct the next N SIP instalments into
  the reserve; (b) a one-off amount. No product is named; the existing Discovery (objective C) lists eligible liquid/overnight funds
  as a separate tool.
- If balances were not entered, the card states "reserves counted from funds only".
- The SEBI attribution of "3–6 months" is NOT VERIFIED (`research-evidence-allocation.md` §8), so the card cites the SEC only.

### 4.2 E-2 Deposit insurance and maturities (P1)

- **DICGC:** for each bank, `excess = Σ deposits(bank, same right & capacity) − 5,00,000`. A card appears when `excess > 0`.
  VERIFIED primary (dicgc.org.in FAQ via the allocation report). NBFC/corporate FDs are not covered, and the card says so.
- **Maturity:** an FD/T-bill/bond with `maturity − as_of ≤ 7 days` is P1; ≤ 30 days is P4. The card links to Discovery
  prefilled with the amount and the goal's remaining horizon.

### 4.3 T-1 Tax-lot clock and LTCG harvesting (P2)

Inputs: lots (CAS), NAVs, the tax table `india-tax@…` (Income-tax Act 2025: s.198 / s.196 / slab), and your tax context: regime,
slab, surcharge band, and **realised listed-equity LTCG elsewhere this FY** (REQUIRES CONFIGURATION; default *unknown*).

```
pool_left   = max(0, 1,25,000 − realised_LTCG_this_FY_in_app − realised_LTCG_elsewhere)      # single annual pool across equity MFs and listed shares
for each equity-oriented folio f (ELSS excluded: re-purchase restarts a 3-year lock-in):
    prefix_f  = longest FIFO prefix whose lots are all LT, past their exit-load window, with Σ gain ≤ pool_left
harvest     = greedy over folios by (gain per ₹ redeemed, desc), then folio id; stop when pool_left is used
tax_deferred = Σ harvested gain × 12.5 % × (1 + surcharge) × (1 + cess)          # rates from the rule table, never literals
```
- **Basis label:** "tax deferred, not a gain". Re-buying resets the cost basis, so a later sale is taxed on less gain.
- **Costs shown:** exit load (normally 0 for eligible lots), stamp duty 0.005 % on the re-buy, STT 0.001 % on the redemption, and
  "1 day out of the market" with the rule that the re-buy NAV is the next cut-off NAV.
- **Abstain** when: `realised_LTCG_elsewhere` is unknown (the card shows the **upper bound** ₹15,625 = 1,25,000 × 12.5 %, before
  cess/surcharge, as "what this input could unlock"); the old regime or non-resident status applies (not modelled); or any lot's exit
  load is unknown and its age is below the longest known load window for its category.
- **Wash-sale-style rules:** none is modelled. Whether Indian law disallows a loss or gain on an immediate re-buy is NOT VERIFIED,
  so this needs CA review (ca-review-packet). Tax-**loss** harvesting stays off until set-off rows under the 2025 Act are verified.
- **Deadline:** active from 15 Feb to 31 Mar of each FY (parameter). Outside the window the card is a P5 notice ("₹X of pool
  unused").
- **Lot-turns-long-term modifier:** if any other card proposes selling a lot that turns LT within `≤ 45 days`, the card offers
  "wait until <date>" with `tax_avoided = gain × (20 % − 12.5 %)`, or `gain × 20 %` when the gain fits in `pool_left`.

### 4.4 C-1 Regular → Direct switch, with the cost gap measured from AMFI NAVs (P3)

`research-evidence-mf.md` §4 (robust by construction) gives the break-even rule. This design removes the TER input: the realised
cost gap is **measured from the two plans' NAVs**, both on AMFI and both permitted.

```
g_12m        = ln(NAV_dir(t)/NAV_dir(t−365d)) − ln(NAV_reg(t)/NAV_reg(t−365d))       # Decimal ln via engine helper; both NAVs must exist on both dates (± 3 business days, else abstain)
annual_saving = V_reg × (e^{g_12m} − 1)
switch_cost  = Σ over FIFO lots of the whole folio: exit_load + tax(gain, STCG/LTCG/slab, pool_left) + stamp(0.005 % of proceeds)
breakeven_m  = 12 × switch_cost / annual_saving
```
- **Wording:** "Realised cost difference over the last 12 months: x.xx %/yr (from AMFI NAVs of both plans)". It is a past cost
  fact, not a forecast.
- **Options computed:**
  - (a) switch all now;
  - (b) switch only lots that are LT and inside `pool_left` (tax ≈ 0);
  - (c) "wait until <date when the next block of lots turns LT>";
  - (d) **stop new SIP into Regular and start it in Direct.** This costs zero tax and is always shown first, because it is free.
- **Abstain** when the sibling match is not unique, `g_12m ≤ 0`, or the history covers fewer than 365 days.
- **Caveat (verifier MF-3):** Deb 2019 finds high-expense Indian funds "marginally better performers". That is about *different*
  funds. Regular vs Direct is the *same* portfolio, so the cost gap is a pure transfer. The card never cites general "low-cost
  funds win" evidence.

### 4.5 R-1 Rebalancing drift, cash-flow first (P4)

Inputs: goals with a target allocation per asset class (`equity, debt, gold, cash`), from §5, and a band `b` (default 5 pp absolute,
annual review plus a check on any daily breach; `research-evidence-allocation.md` §4, Vanguard).

```
w_i      = V_i / Σ V            (per goal; holdings mapped to goals)
drift_i  = w_i − w*_i
trigger  = any |drift_i| > b
need_i   = −drift_i × Σ V        (₹ to move into class i; positive = buy)
plan, in order:
  1. cash-flow: next k SIP/lump instalments redirected to underweight classes until |drift| ≤ b/2 (k ≤ 6; tax 0)
  2. if still beyond band: redemption from overweight schemes, choosing folios in order of
     (tax+load per ₹ redeemed asc, scheme id) and taking FIFO prefixes: LT within pool_left → other LT → past-load STCG last
  3. show ₹ tax + load of step 2 next to "drift if you do nothing"
```
- The impact basis is `amount_to_move`. Severity is `max |drift| − b`, and it ranks within P4.
- **No "rebalancing bonus" claim.** The evidence is about risk control only.
- Your choice (decision D5) whether step 2 is ever offered or rebalancing stays cash-flow only.

### 4.6 R-2 Horizon/duration fit for debt funds (P4)

- **Category bands** from SEBI circular SEBI/HO/IMD/DF3/CIR/P/2017/114 (6-Oct-2017). Examples: Ultra Short 3–6 months Macaulay;
  Low 6–12 months; Short 1–3 years; Medium 3–4 years. Status **VERIFIED-SECONDARY**: AMC SIDs and an HDFC MF explainer quote the
  wording "Macaulay duration of the portfolio is between 1 year –3 years"
  (<https://www.hdfcfund.com/learn/blog/sebi-mandated-mutual-fund-classifications>, accessed 2026-10-15). The primary page did not
  render, and these bands must be re-checked against the current SEBI master circular / 2026 Regulations before use.
- **Rule:** `mismatch` when the band's lower bound exceeds the goal's remaining years (e.g. a Medium Duration fund held for a goal 10
  months away). If an uploaded factsheet gives the actual duration, it overrides the band.
- **Scenario shown:** `ΔNAV ≈ −D_mod × Δy` for ±100/±200 bp. No rate-direction call (MF R9).

### 4.7 R-3 Concentration (P4)

- HHI over schemes and the share per AMC. Thresholds are user parameters (existing alert rule).
- For stocks, single-stock share of equity when stock values are known.
- The card shows which **new-money** flows would cut HHI below the limit.

### 4.8 N-1 Review flags and notices (P5, descriptive only)

- **Persistent-underperformer review flag:** an active equity fund versus its **index-fund proxy from U3**. The proxy table is
  `rules/actions/category_proxy.yaml` (e.g. Large Cap → Nifty 100 index fund Direct), user-confirmed and cited. The flag fires when
  the rolling 36-month annualised return difference, net of both funds' costs (both NAVs are net), is below 0 at each of the last 3
  year-ends.
  - It is **never** an exit instruction. Verifier MF-2 says loser persistence is not the "only robust" effect, and Indian winner
    persistence exists in some studies. Exit stays a signal (gated).
  - NSE/BSE benchmark TRIs are not used because of licensing, so the proxy carries a tracking-difference caveat.
- **Scheme-change watch:** the NAVAll scheme name, category or plan changes for a held scheme. The SEBI "exit without load on
  fundamental attribute change" rule is NOT VERIFIED, so it is not cited.
- **Goal off-track:** funded % below the glide path by more than a user parameter.
- **CAS stale:** last CAS more than 35 days old.
- **SIP missed:** an inferred SIP with no matching CAS purchase within 7 days.

### 4.9 G-1 Goal funding and SIP plan (strip, not a card)

```
funded_pct   = Σ V(goal holdings) / PV(goal_amount, goal_date, r_user)          # r_user is an assumption shown as such
sip_needed   = (goal_amount − FV(current, r_user, n)) × i / ((1+i)^n − 1)     # existing feasibility.py formula
```
Next to it, the **historical-frequency band** from the existing feasibility engine for the goal's actual allocation, on U3 proxy
NAVs, with the as-of date. A banner appears if the history contains no major equity bear market.

---

## 5. Policy and setup: the fewest inputs

### 5.1 The whole setup (about six answers + one upload)

| # | Input | Why | Default if skipped |
|---|---|---|---|
| 1 | CAS PDF + password | Holdings, lots, SIPs, plan type | Nothing personal can be computed; Today shows a single "import CAS" card |
| 2 | Tax: regime (new/old), slab band, surcharge band | Every tax figure | Cards needing tax abstain and show the unlock upper bound |
| 3 | Essential monthly expenses + months (3–6) | E-1 | E-1 abstains |
| 4 | **Loss budget**: "the largest fall of your long-term money you would sit through without selling": 10/20/30/40/50 % | Sets the equity share | Allocation-dependent cards abstain |
| 5 | Goals: up to 3 presets (Emergency, Medium-term with amount + date, Long-term growth with optional amount + date) | Horizon per rupee | One "Long-term growth" goal holding everything except liquid funds |
| 6 | Optional: realised equity LTCG outside the app this FY; bank/FD balances | T-1, E-1 | Upper bound shown; reserves from funds only |

### 5.2 From loss budget to target allocation (deterministic, user confirms)

```
MDD_eq   = maximum drawdown of the longest available U3 broad-equity series (Nifty 50 index fund; plan with the longest AMFI history)
w_eq     = min(1, L / |MDD_eq|)   rounded down to 5 pp;  w_debt = 1 − w_eq − w_gold (w_gold = 0 unless the user sets it)
```
- The result is shown as a proposal with its basis: the exact window, the drawdown dates and the as-of date.
- If the series does not include 2008, a banner says that a deeper fall is plausible. The history start date of AMFI NAVs for older
  index funds is NOT VERIFIED.
- The user accepts or edits it. The stored `allocation_policy@user-<date>` is a **user decision**, not an engine output
  (`audit-journey.md` C2).
- Kelly sizing appears only as an over-betting warning (`research-evidence-allocation.md` §7).

### 5.3 Inputs requested only when they unlock money

Abstentions are collected into **"Needs from you"**, sorted by the deterministic **upper bound of ₹ they unlock**. Examples:
- realised-LTCG-elsewhere unlocks ≤ ₹15,625 of deferred tax per FY;
- an SID upload unlocks the exit-load check for ₹V of holdings.

So you are only asked for what pays. Each request is one field or one file.

---

## 6. Signals: registry, shadow mode and the twelve gates

### 6.1 Registry

- Each candidate is a frozen file `backend/src/iip/rules/signals/<id>@<ver>.yaml`. It holds the rule (pure function of point-in-time
  NAVs), universe, execution timing, costs, tax, benchmark, split dates, hypothesised Sharpe for power, and gate thresholds.
- A hash of the file is stored when it is registered. Changing anything creates a new version **and** a new trial row
  (`research-backtest-method.md` §9.1).
- `backtest_trials` (append-only) counts every evaluated configuration per family. That count feeds G8/G9.

### 6.2 Initial candidates (pre-registration proposals; all on AMFI NAVs, so no NSE data is used)

| Id | Rule (frozen) | Data | Expected outcome |
|---|---|---|---|
| T-1 | `S_m = 1 if C_m > mean(C_{m−9..m}) else 0` on the month-end NAV of the U3 Nifty 50 index fund; switch to the U3 liquid fund at the **next** cut-off NAV; per-lot FIFO tax; one variant only | AMFI | Fails G5/G9 (`research-evidence-momentum.md` S-E: Zakamulin, Mitra) |
| T-2 | 12-1 absolute momentum vs the 12-month T-bill (S-D) | AMFI + RBI series | Fails G5/G9 |
| T-3 | Drawdown top-up: add an extra pre-set ₹ amount to equity SIP when the index-fund NAV is ≥ 20 % below its running max (cash-flow only, no sales) | AMFI | Low power; abstain |
| C-S1 | **Not a signal:** momentum-factor index fund (Nifty200 Momentum 30 / Midcap150 Momentum 50 trackers) as a *disclosed-risk candidate* in Discovery. Shown with live-vs-backfill split (index launch 25-Aug-2020), max drawdown 68–73 %, worst year −19.47 pp, churn and a tax note | AMFI | Shown as a candidate. The excess return is statistically indistinguishable from zero (live t ≈ 0.64; backfill t ≈ 2.0, verifier MOM-2), so the card says so |
| C-S2 | **Not a signal:** quality-factor index fund | AMFI | **ABSTAIN until 36 months of live NAV.** Funds launched Sep-2024 to Jul-2025 (verifier FD) |

Excluded outright: single-stock anything (BLOCKED data), category rotation (MF R6), fund "winners" (R1), duration timing (R9),
volatility targeting, stop-losses and dual momentum across gold/G-sec (about 19 annual decisions; `research-evidence-momentum.md`
S-F), valuation bands (P/E is niftyindices data, BLOCKED).

### 6.3 Gates (fail closed), from `research-backtest-method.md` §10

G1 provenance · G2 survivorship (single-instrument rules pass) · G3 corporate actions (n/a for NAVs) · G4 leakage + shuffle canary ·
G5 ≥ 30 OOS periods **and** ≥ MinTRL · G6 edge > 0 after costs and tax (highest slab, pool already used, liquidated at end) · G7
slippage ×2 and costs ×1.5 · G8 trial count known · G9 DSR ≥ 0.95, Holm/SPA p < 0.05 and HAC t ≥ 3 · G10 2-of-3 regimes, PBO ≤ 0.20,
neighbour parameters positive · G11 vault · G12 live decay.

**Plain statement of power (verifiers BT-9 and the "joint power" gap):** a true 0.5 annualised Sharpe needs about 132 OOS months just
to reach PSR 0.95 at roughly 50 % power. 80 % power needs about 298 months. With t ≥ 3 on top, the gates are close to unpassable
on Indian Direct-plan history (from 2013; that start date is NOT VERIFIED). This is intended. The UI says so and does not hide it.

Also:
- **Tax rows before 2024 are missing** (verifier BT-3: equity rows start 2024-04-01; lots bought on or before 31-Jan-2018 abstain).
  G6 therefore abstains on pre-2024 windows until WP-24 adds cited historical rows.
- **Regime vs vault overlap:** the 2023+ regime overlaps the vault (verifier). So G10 uses pre-2023 sub-periods only, and the vault
  is evaluated once.

### 6.4 Shadow mode and the forward-only ledger (how a signal could ever exist)

- From its registration date, each candidate is evaluated **daily by the cron**, and its state is written to `signal_outcomes`
  (append-only: `signal_id@ver, as_of, state, inputs_manifest_hash`). It is **never** shown as an action.
- Realised NAVs later score each state. This builds a genuine post-registration OOS record. It does not need exchange data, and it
  cannot be overfit after the fact.
- Today shows one line per candidate, for example:
  > **T-1 trend rule: ABSTAIN (G5).** Has 14 post-registration months; needs ≥ 132 for a 0.5-Sharpe edge (MinTRL). Earliest
  > possible review: 2037-08. Backfill test: failed G9 (HAC t = …).

  The numbers come from the engine. The "earliest possible review" date is `registration + max(30, MinTRL(SR_hyp)) months`.
- If all gates pass: status `ACCEPTED` and VERIFIED/NOT VERIFIED per inputs. The card wording is in §9. G12 auto-suspends it later
  if needed.

---

## 7. From numbers to plain-English actions, with provenance

### 7.1 ActionCard contract (`engine/actions/contracts.py`)

```
ActionCard {
  card_id        sha256(rule_id@ver, subject_ids, as_of, input_hash)          # stable → dedupe across days
  rule_id, rule_version, engine_version, input_hash, as_of (data date)
  kind           EMERGENCY | DICGC | MATURITY | LTCG_HARVEST | LOT_LT_WAIT | DIRECT_SWITCH | REBALANCE | DURATION_FIT | CONCENTRATION | NOTICE | SIGNAL
  priority_class P1_PROTECT | P2_DEADLINE | P3_SAVE | P4_RISK_FIT | P5_REVIEW
  deadline       date | null
  impact         { amount_inr: Decimal, basis: SHORTFALL | TAX_DEFERRED | TAX_AVOIDED | ANNUAL_COST_SAVED | AMOUNT_TO_MOVE | AMOUNT_AT_RISK }
  options[]      { option_id, steps[] {instrument_id, units|amount, side}, cost_inr, tax_inr, net_effect_inr, after_state }
  facts[]        { fact_id, value, unit, source_id | formula_id, observation_date, quality }   # every number on the card is one of these
  template_id, slots                                                            # deterministic text
  evidence_ref   docs path + section (e.g. research-evidence-mf.md §4)
  status         VERIFIED | NOT VERIFIED | REQUIRES CONFIGURATION | ABSTAIN(reason, needs[], unlock_upper_bound_inr)
}
```
There is no `expected_return` field (see §1).

### 7.2 Ranking (no composite score; consistent with ADR-0005)

Sort key: `(priority_class, deadline asc NULLS LAST, impact.amount_inr desc, card_id)`.

Impacts with different bases are never added together. P4 orders by severity first, then ₹. The digest shows the top 5 cards and
"n more"; "Needs from you" is a separate list (§5.3). An empty list is a valid result, and it reads "Nothing needs doing today. Your
rules: all within band. Data as of <date>."

### 7.3 Wording (deterministic templates; LLM optional, off, never numeric)

Template example (REBALANCE):

> **Your rebalancing band was crossed** · Long-term goal · data as of 14-Oct-2026 NAV
> Equity is **68.2 %** against your target **60 %** (band ±5 pp): ₹**1,84,500** above target.
> **Option A, no tax:** put the next **4** SIP instalments (₹**45,000**/month) into *<debt fund you hold>*. Drift after: **4.9 pp**.
> **Option B, now:** redeem ₹**1,84,500** from *<scheme>* (FIFO lots, all long-term, within your ₹1.25 lakh pool). Tax ₹**0**,
> exit load ₹**0**, stamp duty on re-investment ₹**9.23**.
> **Doing nothing:** drift stays 8.2 pp.
> Why this rule: you adopted a 5 pp band; rebalancing controls risk and is not a return booster (evidence: allocation report §4).
> Status: VERIFIED · rule REB-1 v1 · tap any number for its source.

(The figures are fictional and illustrate the layout only.)

- Each bold number is a `fact_id`. Tapping one opens the existing ExplainDrawer with its source or formula, observation date and
  quality.
- The LLM adapter (ADR-0007) may only rephrase non-numeric text. The output is rejected if it contains any digit, or any phrase in
  the compliance block list. It is labelled "AI-generated text" and is off by default.

---

## 8. Automation: cron, jobs and alerts

### 8.1 Schedule (Vercel Hobby: daily jobs, ±59 min, no retry, possible duplicates; `research-automation-infra.md` §1)

| Job | `vercel.json` (UTC) | IST window | Steps (each ≤ 90 s, resumable, idempotent, "everything since last success") |
|---|---|---|---|
| J1 | `0 1 * * *` | 06:30–07:29 | NAVAll for the newest missing date; RBI RSS poll #1 |
| J2 | `0 2 * * *` | 07:30–08:29 | NAVAll continuation; series_stats refresh |
| J3 | `0 3 * * *` | 08:30–09:29 | History gap fill (U1–U4 only); MoSPI CPI (from the 12th); sibling backfill for new Regular holdings |
| J4 | `0 5 * * *` | 10:30–11:29 | Late FoF/overseas NAVs; **snapshot** (build context → rules → shadow signals → rank → store); outbox enqueue |
| J5 | `0 13 * * *` | 18:30–19:29 | Watchdog (snapshot missing / stale data → one "needs attention" ping); RBI RSS poll #2 |

Local mode runs the same job functions from a launchd plist (one entry per job). The scheduler is only a trigger; the job code is
shared (`services/jobs/*.py`).

### 8.2 Security exception (new ADR-0014, from `research-automation-infra.md` §3)

- Only `GET|POST /api/cron/{job}` with `job ∈ {navall, navall-continue, history, snapshot, watchdog}`.
- On that route only, the Host may be `$VERCEL_URL`.
- `Authorization: Bearer $CRON_SECRET`: ≥ 32 chars, different from the access token, compared with `hmac.compare_digest`.
- `VERCEL_ENV == production`. A wrong secret is rate-limited. The response carries counts only.
- Tests check that every other route still refuses the `VERCEL_URL` host.
- **First live test** must also check how Deployment Protection interacts with the cron. This is NOT VERIFIED (verifier).

### 8.3 Idempotency, with the verifier's AUTO-3 defects fixed

```sql
CREATE TABLE cron_runs (job TEXT, run_key TEXT, state TEXT CHECK (state IN ('running','done','noop','failed')),
  attempts INTEGER NOT NULL DEFAULT 1, started_at TEXT NOT NULL, lease_until TEXT NOT NULL, finished_at TEXT, detail_code TEXT,
  PRIMARY KEY (job, run_key));
-- claim (one statement). Takes over failed rows AND stale running rows (fixes "a killed run blocks its key forever"):
INSERT INTO cron_runs (job, run_key, state, started_at, lease_until) VALUES (?, ?, 'running', ?, ?)
ON CONFLICT (job, run_key) DO UPDATE SET state='running', attempts=attempts+1,
  started_at=excluded.started_at, lease_until=excluded.lease_until
WHERE cron_runs.state='failed' OR (cron_runs.state='running' AND cron_runs.lease_until < excluded.started_at);
```
- `run_key` = the **IST scheduled date** for fetch jobs. This fixes the inconsistency where J1 cannot know the data date before it
  fetches. For the snapshot, uniqueness comes from `snapshot_id = sha256(engine_version ‖ rules_version ‖ manifest_hash)`.
- Timestamps are produced by the service layer only (ISO-8601 UTC, so they compare as strings).
- Outbox: `pending → sending → sent`. A **reaper** in J5 marks `sending` rows older than 15 minutes `failed`, and they are **not**
  resent. At most one ping is lost; there are never duplicates.
- ABSTAIN snapshots are stored too.

### 8.4 Notifications (ping only)

- The text is fixed, e.g. "IIP: today's report is ready (data as of 14-Oct). 3 actions." It contains counts only: no amounts, no
  scheme names, no buy/sell verbs.
- **Channel conflict to resolve (decision D6).** `research-regulation.md` §8.1 says "no push to third-party channels (Telegram…)",
  while `research-automation-infra.md` recommends Telegram v1.
  - The regulation concern is signal *content* reaching third parties; a content-free ping carries none.
  - **Recommendation:** Web Push (VAPID; end-to-end encrypted to your device) as the primary channel. Telegram only if you accept
    content-free pings stored on Telegram's servers. In-app only is the fallback.
  - ntfy.sh public topics and Gmail app passwords are rejected (spoofable, or a credential with too large a blast radius).

---

## 9. Regulatory wording (inside the private app)

Based on `research-regulation.md` §3, §8: personal use is outside RA/IA registration as a reading of the text, not legal advice.

- **One principal, behind login.** No share links, no second user. Exports are watermarked "private, not for distribution" and
  strip AMFI/exchange data. The README makes no return claims.
- `X-Robots-Tag: noindex` on the hosted origin. Whether it is present today is NOT VERIFIED; WP-05 adds a test.
- **Compliance guard v2** (`compliance_phrases@2`):
  - The existing BLOCK list stays on **all** export, share, notification and unauthenticated surfaces.
  - Inside the authenticated view, rule-state language is allowed: "your band was crossed", "entry/exit condition met (rule T-1
    v1)", "option computed".
  - "you should", "buy now", "target price" and "stop-loss" remain blocked everywhere.
  - BUY/SELL badges only if you opt in (D1).
- **Rule actions are worded as consequences of your own rule** ("your rule … triggered"), matching the existing F15 guard.
- **Signal cards** always carry the rule id and version, backtest card, as-of date and status, and follow the RA-style rationale
  record (§8.3 of the regulation report).
- **No order placement.** Hosted mode cannot place orders (static-IP rules; Vercel IPs are shared). This design is signal-only and
  orders are manual.

---

## 10. Performance fixes (from the two performance audits), folded into the build

| # | Fix | Source | Expected effect | WP |
|---|---|---|---|---|
| 1 | Discovery: one `GROUP BY … HAVING` instead of 1,791 COUNTs; time budget | perf-hosted RC-2 | 504 → seconds (re-measure) | WP-03 |
| 2 | Move Turso to `bom1` (user action in dashboards) | RC-1 | ~0.40 s per statement → NOT VERIFIED (measure) | WP-07 runbook |
| 3 | Session lookup off the event loop; `last_seen` throttled to ≥ 5 min | RC-3 | 2 → 0–1 statements per request | WP-05 |
| 4 | `/assets/*` immutable cache header (option a), CDN promotion (b) as a follow-up with headers copied | RC-4 / F3 | No repeat asset round trips | WP-07 |
| 5 | `series_stats` table, `/api/data-asof` (1 row), batched data-health, batched instrument detail | RC-6/7, journey S4 | 25 → about 4 statements | WP-04 |
| 6 | `/api/instruments/{id}/summary`, series paging + weekly downsampling, batch summary for the FD/T-bill tables | F1/F2 | 0.73 MB → about 1 kB for pickers | WP-04 / WP-06 |
| 7 | `useApi` keyed cache + in-flight de-dupe + stale-while-revalidate badge; helpers moved out of pages; Overview preload | F4/F5/F6 | Fewer round trips | WP-06 |
| 8 | Lazy scipy import; read-only startup | RC-5 | Shorter cold start | WP-07 |
| 9 | **Today = 1 statement** (`SELECT payload FROM signal_snapshots ORDER BY as_of DESC LIMIT 1`) | this design | Landing page independent of portfolio size | WP-21 |
| 10 | Statement-count test per endpoint in CI | RC-8 | N+1 regressions fail CI | WP-07 |

All latency effects stay NOT VERIFIED until they are re-measured on the hosted deployment after each change.

---

## 11. UX: Today replaces the workbench as the front door

```
┌ Today · data as of 14-Oct NAV · all sources fresh ───────────────────────────┐
│ 1 P1 Emergency reserve short by ₹62,000          [see options]              │
│ 2 P2 ₹1,02,300 of your LTCG pool unused (FY ends 31-Mar) [see options]      │
│ 3 P3 Regular→Direct: ₹3,140/yr realised cost gap [stop SIP in Regular first]│
│ 4 P4 Equity 8.2 pp over target                    [cash-flow option]        │
│ Needs from you: tax slab (unlocks ≤ ₹15,625) · CAS is 41 days old           │
│ Goals: Emergency 74 % · House 2029 51 % · Long-term (no amount)             │
│ Signals: T-1, T-2, T-3 ABSTAIN (evidence) · details                          │
│ Growth reality: your mix, historical 10-y range a–b %/yr (as of …)          │
└──────────────────────────────────────────────────────────────────────────────┘
(figures fictional)
```

- **Navigation shrinks to:** Today · Holdings (Overview) · Goals · Evidence · Settings. Everything else moves under "Tools":
  Discovery ("park a lump sum"), Compare, Scenarios, Risk, Simulator, Fixed income, Mutual funds, Watchlist, Data health.
- **"I did this" button on each card:** writes `action_log` (your decision; it is not an order). The card is suppressed until the
  next CAS confirms it, or it is re-raised if the CAS contradicts it after 10 days.
- **Setup wizard** (§5.1) replaces the current one-bucket Onboarding.
- **Manual-entry forms** (FD card rates, G-sec quotes, corporate bonds, factsheet facts) stay under Tools → Advanced and are no
  longer needed for any Today card, except own-FD details.

---

## 12. Phased build plan: 28 work packages for parallel worktrees

Rules for parallel work:
- **One owner per file.** Hot shared files are owned by WP-01 (scaffold) and frozen afterwards: `api/app.py` router registration,
  `frontend/src/App.tsx` navigation, `store/migrations/0004_user_first.sql` (the **only** new migration; it contains every table
  below), `data/registry.py` new source rows, `data/fetch.py` allowlist hosts.
- Later WPs that need a schema change add `0005_<wp>.sql` only after coordinating the next free number with WP-01's owner.
- Every WP adds its own test files. TDD is required, and on both drivers (SQLite and libSQL local file) where storage is touched.

### Phase A: foundation (serial, first)

| WP | Name | Files (exclusive) | Done when |
|---|---|---|---|
| WP-01 | Scaffold & schema | `backend/src/iip/engine/actions/{__init__,contracts,context_types}.py`; `backend/src/iip/store/migrations/0004_user_first.sql` (goals, goal_holdings, allocation_policies, tax_context, cron_runs, signal_snapshots, notification_outbox, series_stats, action_log, sip_templates, backtest_trials, signal_outcomes, push_subscriptions); `api/app.py` (include routers `routes_today`, `routes_goals`, `routes_cron` as stubs); `frontend/src/App.tsx` (nav + lazy routes to stub pages); `data/registry.py` (rows `rbi.rss.pressreleases`, MoSPI endpoint ids only); `data/fetch.py` (hosts: RBI RSS, push endpoints decided in D6) | Stubs compile; migration applies on both drivers; `ActionCard` has no forecast field (test) |
| WP-02 | ADRs | `docs/architecture/architecture-decision-records/0014-scheduled-jobs.md`, `0015-action-engine-and-signal-taxonomy.md`, `0016-signal-registry-and-gates.md`, `0017-notifications.md`, `0018-equity-data-posture.md`, `0000-index.md` | ADRs accepted by the user (they record decisions D1–D8) |

### Phase B: speed, plumbing, automatic data (parallel, 11 WPs)

| WP | Name | Files (exclusive) |
|---|---|---|
| WP-03 | Discovery batching + time budget | `services/discovery.py`, `tests/test_discovery_batching.py` |
| WP-04 | Read-path fixes: series_stats, data-asof, data-health batch, instrument summary/paging/downsample, batch summary | `api/routes_core.py`, `store/observations.py` (series_stats upkeep inside the batched upsert), `tests/test_read_paths.py` |
| WP-05 | Security middleware: non-blocking session, throttled last_seen, cron host+bearer exception, noindex header | `api/security.py`, `api/settings.py`, `tests/test_security_cron.py` |
| WP-06 | Frontend data layer: useApi cache/de-dupe/SWR, helper extraction, preload, FixedIncome N+1 removal | `frontend/src/lib/useApi.ts`, new `frontend/src/components/{CiteLink,SinglePicker,InstrumentPicker,…}.tsx`, edits to `pages/{Compare,Risk,Scenarios,FixedIncome,InstrumentDetail,Overview,Discovery,MfExplorer}.tsx` imports only |
| WP-07 | Hosting: asset cache header, lazy scipy, read-only startup, statement-count harness, Turso bom1 runbook | `api/app.py` (`spa()` body only, after WP-01), `api/__main__.py`, `engine/stats/*.py` (import placement only), `backend/tests/perf/statement_counter.py`, `docs/operations/deployment.md` |
| WP-08 | Macro feeds: MoSPI fix (defects 1–5) + RBI RSS T-bill adapter with price↔yield self-check | `data/mospi.py`, new `data/rbi_rss.py`, `data/parsers/rbi_tbill.py`, fixtures, `services/inputs.py` (risk-free writer only) |
| WP-09 | Job runner + cron route + claims/reaper + vercel crons + launchd plist | new `api/routes_cron.py`, `services/jobs/{runner,navall,history,macro,watchdog}.py`, `store/coordination.py` (claim helpers), `vercel.json`, `scripts/launchd/*.plist` |
| WP-10 | Universe: tax-class fix, name-pattern table, U2 sibling matcher, U3 core set, prune rule | `rules/mf_categories.yaml`, `rules/universe/core_index_set.yaml`, `engine/candidates.py` (tax-class function only), new `services/universe.py`, `services/ingestion.py` |
| WP-11 | CAS: Regular/IDCW ISIN on-demand matching, SIP template inference, stamp-duty lots | `services/cas.py`, `api/routes_cas.py`, new `engine/actions/sip_detect.py` |
| WP-12 | SID exit-load grammar parser (user-triggered, held schemes only) | new `data/parsers/sid_exit_load.py`, `services/instruments.py` (exit-load writer only), fixtures |
| WP-13 | Goals, tax context, allocation policy (loss budget → w_eq) services + API | new `services/goals.py`, `api/routes_goals.py`, `engine/actions/policy.py`, `rules/actions/policy.yaml` |

### Phase C: rule actions (parallel, 8 WPs; each pure rule module + fixtures)

| WP | Name | Files (exclusive) |
|---|---|---|
| WP-14 | Context builder (the IO side): one batched read → `PortfolioContext` | new `services/action_context.py` |
| WP-15 | E-1 emergency, E-2 DICGC + maturities | `engine/actions/rules/safety.py` |
| WP-16 | T-1 tax-lot clock, LTCG harvest, lot-LT modifier | `engine/actions/rules/tax_timing.py`, `engine/actions/fifo_select.py` |
| WP-17 | C-1 Regular→Direct with NAV-measured cost gap | `engine/actions/rules/direct_switch.py`, `engine/actions/cost_gap.py` |
| WP-18 | R-1 rebalancing, cash-flow first | `engine/actions/rules/rebalance.py` |
| WP-19 | R-2 duration fit (SEBI bands, re-verified), R-3 concentration | `engine/actions/rules/risk_fit.py`, `rules/actions/sebi_debt_bands.yaml` |
| WP-20 | N-1 review flags/notices, G-1 goal strip | `engine/actions/rules/notices.py`, `engine/actions/goals.py`, `rules/actions/category_proxy.yaml` |
| WP-21 | Ranker, digest assembler, supervisor manifests per kind, templates, compliance v2 | `engine/actions/{rank,digest,templates}.py`, `supervisor/manifest.py`, `supervisor/compliance.py`, `rules/compliance_phrases.yaml` |

### Phase D: delivery and evidence (parallel, 7 WPs)

| WP | Name | Files (exclusive) |
|---|---|---|
| WP-22 | Snapshot job + Today/action-log API | `services/jobs/snapshot.py`, `api/routes_today.py` |
| WP-23 | Today page, ActionCard, Setup wizard, Goals page, nav copy | new `frontend/src/pages/{Today,Setup,Goals}.tsx`, `frontend/src/components/{ActionCard,NeedsFromYou,EvidenceStrip}.tsx` |
| WP-24 | Backtest ledger: Decimal lots, MF timing (cut-off, next NAV, T+3 switch gap; T+5 for ≥ 80 % overseas), costs table, **historical tax rows** (pre-2024, with primary citations, CA review) | new `engine/backtest/{ledger,timing,costs}.py`, `rules/costs/india_mf.yaml`, `rules/tax/india.yaml` (historical rows only) |
| WP-25 | Evidence statistics: PSR/DSR/MinTRL, Holm, SPA (reuse the stationary bootstrap), HAC t, PBO/CSCV, with paper fixtures | new `engine/backtest/stats.py` |
| WP-26 | Registry + gates G1–G12 + trial registry + shadow evaluator + outcome ledger | new `engine/backtest/{registry,gates}.py`, `services/shadow.py`, `rules/signals/{T-1,T-2,T-3}@1.yaml` |
| WP-27 | Notifications: outbox sender, Web Push (service worker, manifest, subscription), optional Telegram adapter, ping-only template test | new `services/notify.py`, `frontend/public/{sw.js,manifest.webmanifest}`, `frontend/src/components/PushOptIn.tsx` |
| WP-28 | Evidence page: signal status, factor/momentum candidate disclosures (C-S1/C-S2), growth-reality range | `frontend/src/pages/Evidence.tsx`, `services/growth_reality.py` |

**Order and dependencies:**
1. WP-01 → (WP-02 in parallel).
2. Phase B (all parallel; WP-09 needs WP-05 for the route to be reachable).
3. Phase C (WP-14 first, or code against the WP-01 context types; the rule WPs only need `context_types.py`).
4. Phase D (WP-22 needs WP-21 and WP-09; WP-26 needs WP-24 and WP-25).

**Shippable milestones:**
- **M1** (end of B): fast app, data that refreshes itself, CPI and T-bill automatic.
- **M2** (end of C + WP-22/23): the daily digest exists.
- **M3**: push pings.
- **M4**: shadow signals with honest evidence status.

---

## 13. Decisions only you can make

| Id | Decision | Recommendation |
|---|---|---|
| D1 | Accept the rule-action / signal split (§1), and the vocabulary inside the private view: neutral "condition met" only, or opt-in BUY/SELL badges | Accept the split; neutral labels |
| D2 | Run the AMFI pipeline in **hosted** mode (phone access; the source-registry says hosted needs written AMFI permission) or **local** launchd only, or write to AMFI | Write to AMFI. Until it answers, run local-first; enable hosted cron only if you accept the risk in writing (ADR-0014) |
| D3 | Size of the U3 core index set (≤ 40 schemes of about 14,400) | ≤ 40 |
| D4 | Loss budget, emergency months, goals | Yours |
| D5 | Rebalance with sales (tax shown) or cash-flow only | Cash-flow first; sales offered, never default |
| D6 | Ping channel: Web Push / Telegram (content-free) / none | Web Push |
| D7 | Equities: stay ABSTAIN; or configure Upstox local-only (terms unread; dividends and delisted gaps); or email NSE about manual bhavcopy | Stay ABSTAIN; email NSE; reconsider after an answer |
| D8 | AMFI TER JSON (grey area) | Off. §4.4 makes it unnecessary |
| D9 | Approve the gate thresholds (DSR ≥ 0.95, PBO ≤ 0.20, t ≥ 3, MinTRL, vault 20 %/3 y) knowing they are close to unpassable | Approve |

---

## 14. How each weakened wave-1 claim was applied

- **EA-1:** "never 25 %" is scoped to TRI history since 1995/2005 with about 2 independent windows; the pre-1992 Sensex is mentioned.
- **EA-6:** FIFO within a folio; the engine chooses folios, not lots. Surcharge and cess come from the rule table. Income-tax Act 2025
  sections are used.
- **EA-3 / EA-7:** volatility targeting stays excluded; allocation is user-chosen, not optimised.
- **MF-2:** the underperformer output is a review flag only; it never claims to be the "only robust" effect.
- **MF-3:** the Regular→Direct rule rests on the same-portfolio identity, not on "low TER predicts returns".
- **MF-5:** the "investors lose 2.5–5.8 %" figure is not used in any card.
- **MOM-1/2/6/9/10:** the momentum fund is a disclosed-risk candidate; its excess return is stated as not significant; the
  inconsistent NSE since-inception CAGRs are not displayed.
- **MOM-8:** niftyindices data stays local-only, manual.
- **EVQ-1/6/7/9/10:** no factor timing; low-vol is shown only as a risk statistic; factor-fund costs include TER; s.10(23D) is not
  cited (2025 Act mapping NOT VERIFIED).
- **NSE-2/6/8/9/10, EQ-6/7, R12, BT-5/7:** equities are ABSTAIN. Broker data is local-only by policy. Manual bhavcopy is NOT
  VERIFIED, not BLOCKED. Snapshot hashing addresses retroactive rescaling.
- **BT-3/4/9:** historical tax rows must come before pre-2024 tests (WP-24). ETF STT is NOT VERIFIED, so ETFs use the ×2 cost stress.
  The power statement is shown.
- **AUTO-3 / AUTO-7:** the claim SQL takes over stale rows; run_key is defined; there is an outbox reaper. Equity broker routes
  are REQUIRES CONFIGURATION rather than BLOCKED.
- **R5 / R10 / R14 / R15:** no order automation; exports are watermarked (not banned); no reliance on exchange-policy reach to
  individuals.
- **FD-1/3/4:** no fundamentals signals. Pledge flags are deferred (see §15).

---

## 15. What to cut or defer

| Cut / defer | Reason |
|---|---|
| Stock buy/sell signals, stock screeners, fundamentals scores, pledge/PEAD/F-score signals | Data BLOCKED or REQUIRES CONFIGURATION; no survivorship-free history; evidence weak or contested |
| Category rotation, "top fund" picks, star ratings, manager-change exits, rate-cycle duration calls, SIP-vs-lump "better returns" | Evidence says abstain (MF R1, R5, R6, R7, R9, R10) |
| Volatility targeting, stop-losses, Kelly sizing, mean-variance optimiser | Abstain (allocation report §9); Kelly only as a warning |
| Valuation (P/E) bands | niftyindices licence |
| Order placement / broker SDKs | Static-IP rules; signal-only by design |
| Paid data (Kite ₹500/month, NSE licences) | No-paid-keys rule |
| GitHub Actions runner, ntfy.sh, Gmail SMTP | Reliability, spoofing, credential risk |
| Tax-loss harvesting | Set-off rows under the 2025 Act are NOT VERIFIED |
| Gold returns from unofficial NAV mirrors | Conflicts with the official-source bar (verifier EA) |
| Prominence of Compare/Simulator/Scenarios/Fixed-income manual forms | Moved under Tools; not deleted (tests and value stay) |
| LLM features near actions | Off by default; never numeric |

---

## 16. Open items (NOT VERIFIED until tested)

1. The Vercel cron Host value and the Deployment Protection interaction.
2. Turso `bom1` per-statement latency.
3. CAS import on a real statement.
4. Tax-class name-pattern coverage after the build.
5. SEBI duration bands against the current master circular.
6. AMFI history depth for older index funds and Direct-plan start dates.
7. Wash-sale treatment on harvest re-buys (CA).
8. Upstox/Angel One developer terms.
9. NSE's answer on manual bhavcopy.
10. Whether the RBI RSS item description carries the T-bill table.
11. ETF STT row.
12. The exact Turso write counting.
