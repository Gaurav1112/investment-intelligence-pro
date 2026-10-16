# Research: a deterministic backtesting method for signals (wave 1, "backtest-method")

- **Track:** wave1 / backtest-method
- **Date of research, and access date of every URL below:** 2026-10-15
- **Question:** what must a backtest do before the engine may show a buy, sell, switch or hold **signal** for a mutual fund, ETF or
  stock? Covers point-in-time data, survivorship-free universes, corporate actions, look-ahead prevention, purged and embargoed
  walk-forward, Indian transaction costs, tax-aware returns, multiple-testing control, minimum evidence gates and uncertainty
  reporting. Ends with what to add to `docs/forecasting/validation-methodology.md`.
- **Binding rule that this document turns into a procedure:** *a signal may exist only if a documented, out-of-sample, cost- and
  tax-aware backtest supports it. Otherwise the engine abstains.* "No suitable candidate" is a valid and expected output.
- **Status labels:** VERIFIED (primary page opened today and quoted, or already VERIFIED-PRIMARY in a repo doc that is cited) ·
  VERIFIED-SECONDARY (the quote comes from a broker or other secondary page, or a search extract of the primary page) ·
  NOT VERIFIED (must not drive a number) · REQUIRES CONFIGURATION (needs the user's own input or account) · BLOCKED (cannot be
  used, because the terms forbid it or the data does not exist).
- **Fixture oracle:** numpy 2.5.4 and scipy 1.18.1 in `backend/.venv`. Every fixture number below was recomputed with the script
  described in §14. Money fixtures use `decimal.Decimal`.
- Not tax, legal or investment advice.

---

## 0. Answer in brief

1. **The repo already has most of the statistical spine.** `validation-methodology.md` and
   `backend/src/iip/engine/forecasting/validation.py` cover purging, embargo, walk-forward splits, purged k-fold, Diebold–Mariano
   with the HLN correction, coverage tests and PSI. Their unit of evaluation is a **forecast distribution**. A **signal** is a
   *decision rule that trades*, so it needs four things the current spec lacks:
   - a **trade ledger** with Indian costs and **lot-level tax**;
   - **execution-timing rules** (MF cut-off and realisation of funds, NAV publication lag, settlement gaps);
   - a **trial registry** feeding multiple-testing corrections (Deflated Sharpe, White's Reality Check / Hansen's SPA, Holm, PBO);
   - a **benchmark-relative** null: "does the rule beat simply holding the same asset (or an index fund) after costs and tax?"
2. **Costs are not small relative to plausible edges.** At today's broker-published rates, a ₹1,00,000 equity-delivery round trip
   costs **₹237.82 (0.238 %)**. At ₹10,000 it costs **₹37.59 (0.376 %)**, because the DP charge is fixed per scrip (fixture C-1).
   A monthly-rebalanced stock signal pays roughly 12 × that per year before tax. Selling within 12 months also triggers **STCG at
   20 %** instead of LTCG at 12.5 % above ₹1.25 lakh, so a high-turnover rule loses more to tax than a holder does.
3. **Multiple testing dominates small samples.** Suppose 100 zero-skill strategy variants each have 10 years of monthly returns.
   The best of them is expected to show an **annualised Sharpe ratio of about 0.80** by luck alone (fixture MT-1). A 0.5-Sharpe
   rule needs about **11 years** of monthly out-of-sample data to be distinguished from zero at 95 % confidence, even with no
   multiple testing at all (fixture MT-3).
4. **Data gaps decide what can be tested.**
   - **Single stocks: BLOCKED** for signal generation. No compliant free source with delisted stocks was found
     (`research-equity-data-alt.md` §0), so a survivorship-free universe cannot be built.
   - **Mutual funds:** testable for a scheme's own history. Category-level and cross-sectional MF signals stay
     survivorship-suspect until the AMFI history probe confirms that closed schemes are present (validation-methodology §3.4,
     rule S1).
   - **Index ETFs and index funds:** the most defensible candidates.
   - **Tax rules in the repo start in 2020–2024** (`rules/tax/india.yaml`), so a tax-aware backtest before about 2024 needs
     historical rule rows. These must cover pre-1-Apr-2018 LTCG exemption, the 10 %/15 % regime from 2018 to 22-Jul-2024 and the
     31-Jan-2018 grandfathering. Each row must cite its source.
5. **Expected outcome:** under the gates in §10, most candidate rules will end as `NO_SIGNAL (insufficient_evidence)`. That is the
   design working, not failing. The engine must say so plainly and show the evidence that is missing (for example "needs about
   11 years of out-of-sample data; has 4").

---

## 1. Definitions

| Term | Definition used here |
|---|---|
| **Signal** | A deterministic function `S(info_set_τ) → action ∈ {BUY, SELL, SWITCH(a→b), HOLD, ABSTAIN}` with a stated horizon, for one instrument or a stated universe. `info_set_τ` contains only facts **known** at decision time τ (§3). |
| **Strategy** | A signal plus sizing, execution and cost/tax rules. The thing that is backtested. |
| **Trial** | Any evaluated configuration: a parameter value, universe, lookback, threshold or rule variant, *including ones discarded by hand*. Every trial is logged (§9.1). |
| **Benchmark (null)** | The passive alternative the user would otherwise hold. Default: buy-and-hold of the same instrument. For a switching rule between A and B: a static 50/50 or the better of hold-A / hold-B chosen **ex ante**. For equity: an index fund on the relevant TRI. It is costed and taxed under identical rules. |
| **Edge** | Strategy after-tax, after-cost return minus benchmark after-tax, after-cost return, per evaluation period. All tests are run on edge series, not on raw returns. |
| **Out-of-sample (OOS)** | Periods whose data were never used to choose the signal's form, its parameters or the decision to keep it. A "final vault" period is touched once (§5.4). |

---

## 2. What exists today and what is missing

### 2.1 Existing spec and code (read 2026-10-15)

| Topic | `validation-methodology.md` | `engine/forecasting/validation.py` |
|---|---|---|
| Point-in-time rule, publication lags | §3.1 (NAV used from d+1; factsheet from `published_at`) | — (data layer) |
| Revisions (append-only, as-known-at-T) | §3.2 | — |
| Leakage assertions | §3.3 | `assert_no_leakage`, `LeakageError` |
| Survivorship | §3.4 S1–S3 (banner; NAV history by date; `scheme_status`) | — |
| Walk-forward + purging + embargo | §4 with toy fixture | `walk_forward_splits`, `purged_kfold`, `default_embargo` |
| Forecast scoring | §5 (pinball, CRPS, interval score, coverage, PIT) | all present |
| Model comparison | §6 DM + HLN; Holm/RC/SPA/DSR mentioned as "guidance only, not used in v1" | `diebold_mariano`, `promotion_gate` |
| Drift monitoring | §7 | rolling coverage / loss-ratio / PSI |
| User-level costs | MF stamp duty, exit load (calc-methodology §2.8–2.10) | `engine/costs.py` (MF stamp duty 0.005 %, FIFO exit load) |
| Tax | `rules/tax/india.yaml` with `effective_from`/`effective_to` | `engine/tax.py` |

### 2.2 Gaps for signals

| # | Gap | Why it matters | Section |
|---|---|---|---|
| G-a | No **trade/position ledger** with lots | Costs and tax depend on lots and holding periods, not on return series | §6, §7 |
| G-b | No **equity/ETF cost table** (STT 0.1 %, stamp duty 0.015 %, exchange charge, SEBI fee, GST, DP charge) | Costs of about 0.24–0.38 % per round trip are comparable to plausible monthly edges | §6 |
| G-c | No **execution-timing model** for MFs (3 pm cut-off, realisation of funds, redemption payout lag during a switch) | Same-day-NAV fills overstate switching strategies | §4 |
| G-d | **Tax rule rows start in 2020–2024** | A tax-aware backtest over 2010–2023 is impossible without historical rows | §7 |
| G-e | Multiple-testing tools are "guidance only"; **no trial registry** | Without N (number of trials), DSR, RC/SPA and PBO cannot be computed | §9 |
| G-f | No **corporate-action** adjustment spec (splits, bonuses, rights, dividends) | Unadjusted prices create fake crashes or jumps, and fake signals | §3.3 |
| G-g | No **benchmark-relative null** for trading rules | A rule that just "holds equity" looks skilful in a bull market | §1, §8 |
| G-h | No **minimum evidence gates** for signals (only for forecast promotion) | The engine needs a fail-closed checklist that ends in ABSTAIN | §10 |
| G-i | No **uncertainty report template** for strategy results (Sharpe CI, MinTRL, drawdown range, cost/tax sensitivity) | Point estimates of backtested CAGR mislead | §11 |
| G-j | No **final untouched holdout ("vault")** rule | Walk-forward reused many times becomes in-sample | §5.4 |

---

## 3. Data layer: point-in-time, survivorship, corporate actions

### 3.1 Bitemporal storage

Every fact carries two times:

- `valid_time`: the date the fact describes, such as a NAV date, factsheet month-end or ex-date.
- `known_time`: the earliest time the fact was publicly available. Use `published_at` where known, otherwise a conservative lag
  rule, recorded as an assumption.

A backtest at decision time τ reads `SELECT … WHERE known_time ≤ τ`, using the latest version known at τ. This extends
validation-methodology §3.1–3.2 from forecasts to every signal input. The conservative lags already adopted remain in force:

| Input | `known_time` rule | Status |
|---|---|---|
| MF NAV for day d | d + 1 business day (repo rule; exact AMFI publication time NOT VERIFIED) | repo rule, conservative |
| Factsheet metrics (YTM, duration, holdings) | `published_at`; if absent, month-end + 10 business days and flagged | publication lag NOT VERIFIED |
| Scheme metadata (category, benchmark, BER/TER, exit load) | `valid_from` of each version | repo rule |
| Equity/ETF daily candle for day d | after market close of d, so usable for decisions at d's close only if the rule is explicitly "close-to-next-open"; default is to act at d + 1 (§4) | design rule |
| Corporate action | **announcement / record-date known_time** for decisions, **ex-date** for price adjustment (§3.3) | design rule |
| Tax rule | the rule in force on the **transfer date** (`effective_from`/`effective_to`, as `india.yaml` already does) | repo rule |
| Index constituents | as of each rebalance effective date. Free compliant history NOT VERIFIED; NSE site automation is **BLOCKED** (`research-equity-data-alt.md`) | BLOCKED until a source is found |

### 3.2 Survivorship-free universes

| Universe | Status | Rule |
|---|---|---|
| One live MF scheme's own history | Usable | Unaffected for its own series (validation-methodology S2) |
| MF category or cross-section (for example "top-quartile funds") | **NOT VERIFIED** survivorship-free | Build only from AMFI NAV history **by date** (S1). Until the probe proves closed or merged schemes appear, every cross-sectional MF signal is gated to `ABSTAIN (survivorship_unverified)`. Merged schemes need a `merged_into` mapping so their history is not silently dropped (S3). |
| Index ETF / index fund on a published TRI | Usable for the instrument itself | The index is survivorship-free by construction for *index* returns. A *universe* of ETFs is subject to the same live-only issue. |
| Single stocks | **BLOCKED** | The broker instrument lists probably exclude delisted stocks (`research-equity-data-alt.md` §0, NOT VERIFIED). NSE/BSE archives cannot be automated under their terms. Without delistings, a stock-selection backtest is biased upward. Abstain. The existing RT-7 banner (return-target-feasibility §RT-7) stays. |

**Delisting return rule (for whenever a delisting-complete source exists).** A position in a security that disappears must be
closed at the last traded price **minus a conservative delisting haircut**, which is a parameter with sensitivity runs. It must not
be closed at the previous close or dropped. The haircut value for India is **NOT VERIFIED**; no published Indian delisting-return
study was opened in this session.

### 3.3 Corporate-action adjustment (equities and ETFs)

Store **raw** prices and a separate corporate-action table, never pre-adjusted prices of unknown provenance. Whether broker candles
are adjusted is NOT VERIFIED (`research-equity-data-alt.md` §0), so the adapter must detect it: a split shows up as an unexplained
gap equal to the ratio on the ex-date. Compute a **backward cumulative adjustment factor** `F(t) = Π_{ex-dates e > t} f_e` and use
`P_adj(t) = P_raw(t) × F(t)`, recomputed **as known at τ** (an action announced after τ must not adjust pre-τ prices in the τ-view).

| Action | Per-event factor `f_e` (applied to prices before the ex-date) | Notes |
|---|---|---|
| Split a:b (a old shares become b new) | `a / b` | The share count is multiplied by `b / a` in the ledger. |
| Bonus b:a (b new for every a held) | `a / (a + b)` | Count × `(a + b)/a`. |
| Rights r:a at subscription price S, cum-rights close P | `TERP / P`, with `TERP = (a·P + r·S)/(a + r)` | Only the price-continuity factor. The ledger must model whether the rights were taken up, renounced or lapsed. Default: lapse, which is conservative. |
| Cash dividend D, cum-dividend close P | `(P − D) / P` for a **total-return** series | The ledger instead books cash D on the **payment date**, taxed at slab under the dividend rules (repo tax tables). Do not do both. |
| Merger / demerger | instrument-specific mapping table | NOT VERIFIED data source. Gate to ABSTAIN if one occurs inside a test window without a mapping. |

Signals must be computed on the **total-return-consistent** series that a holder would have experienced. Fills in the ledger use
**raw** prices and actual share counts. That keeps costs (STT, stamp duty) on true traded value.

**MF specifics.**
- Growth-option NAV is already total-return net of expenses, so applying TER/BER again is a double count. `costs.py` already
  refuses this.
- IDCW-option NAVs drop on payout. Use growth-option series for signals.
- Segregated portfolios (side pockets): the 241 zero-NAV segregated rows in NAVAll (known-limitations) mean a credit event split
  the scheme. Any test window containing a segregation is gated (validation-methodology §8 already suppresses forecasts for this
  case).

---

## 4. Look-ahead prevention and execution timing

### 4.1 Timeline per decision

For each decision time τ the engine records `(τ, info_cutoff, order_time, fill_price_rule, settlement_date, cash_available_date)`:

| Instrument | Default rule | Basis |
|---|---|---|
| MF (non-liquid) purchase or redemption | Decision uses NAVs known at τ (NAV ≤ τ − 1 business day). The order is placed on business day τ. **Fill at the NAV of τ + 1** (conservative). Same-day NAV needs the application **and funds** before 3 pm, which a backtest cannot guarantee. | SEBI cut-off rules, VERIFIED-SECONDARY (§13 [S7]) |
| MF switch A → B | Redemption of A fills at NAV(τ + 1). The purchase of B fills at the NAV of the day **redemption proceeds are realised**. Use **T + 3 working days** (the repo's regulatory maximum; indian-instruments-and-tax §1, line 146), so the money sits **out of the market for 3 days**. Same-AMC "switch" transactions may differ; NOT VERIFIED, so stay conservative. | repo doc + design rule |
| Liquid/overnight MF | Purchase cut-off 1:30 pm (VERIFIED-SECONDARY). Use next-day NAV. | [S7] |
| ETF / stock | Signal at close of d. **Fill at the next session's open or close** (choose one per strategy and record it), plus slippage (§6.3). Never fill at the same close the signal used. | design rule |

### 4.2 Leakage taxonomy and automated invariants

The existing §3.3 tests become invariants on the backtest engine (fail closed with `LeakageError`):

1. **Feature timestamp:** every feature value used at τ has `known_time ≤ τ`.
2. **Label purge:** a training label covering `(t, t + H]` requires `t + H ≤ origin − embargo` (existing `assert_no_leakage`).
3. **Fill after decision:** `fill_time > decision_time`, strictly.
4. **Universe as of τ:** membership is evaluated with data known at τ (no "funds that exist today").
5. **Adjustment as of τ:** corporate-action factors are evaluated with actions announced by τ.
6. **Normalisation:** z-scores, ranks and percentiles are computed using only data up to τ, never full-sample statistics.
7. **Tax and cost rules as of transfer date:** looked up by date, never "today's rates" (a common silent error).
8. **Parameter provenance:** every parameter value cites the trial-registry entry chosen on data ≤ the start of the OOS segment.

A **shuffle canary** should be part of the test suite. Rerunning the full pipeline on (a) returns with dates permuted within blocks
and (b) a pure-noise series must give OOS edge statistics consistent with zero, for example DSR < 0.5. A pipeline that finds
"signals" in noise has a leak. This is a test of the *pipeline*, not of the signal.

---

## 5. Walk-forward protocol for strategies

### 5.1 Nested scheme

```
full history ─────────────────────────────────────────────────────────────────────────────►
│ outer walk-forward OOS segments (K origins, step = rebalance period)        │ VAULT │
│   at each outer origin T_k:                                                 │ (final│
│     inner tuning = purged k-fold (existing purged_kfold) on data ≤ T_k − H − e│ 20 %, │
│     choose params by inner score, freeze                                    │ ≥ 3 y)│
│     trade (T_k, T_{k+1}] with frozen params → edge_k                         │       │
```

- **Outer loop:** existing `walk_forward_splits`, with origins spaced by the rebalance period. The training window expands by
  default; a rolling window is the robustness check (as in §4.1 of the existing spec).
- **Inner loop:** existing `purged_kfold` with purge equal to the label horizon H and embargo `e = max(5 business days, 0.01 N)`
  (existing default).
- **Concatenated OOS edge series** (one value per rebalance period) is what every statistic in §9–§11 is computed on.
- **Combinatorial purged CV (CPCV)** (López de Prado 2018, ch. 12, already cited in the repo) may be added later to get a
  *distribution* of OOS paths for PBO (§9.5). It is not required for v1.

### 5.2 Label and horizon rules

- The signal horizon H is fixed in advance and logged. Changing H creates a new trial.
- Overlapping holding periods (for example a daily-evaluated 12-month rule) are scored on **non-overlapping** periods for
  significance, or with HAC variance with lag H−1 (as the existing DM rule does).

### 5.3 Sub-period robustness

As in existing §6 rule 4, the edge must be positive in at least 2 of 3 pre-declared regimes:
- pre-2020;
- 2020–22 (COVID crash, rate cycle);
- 2023+.

Also report a **drawdown-regime split**: periods when the benchmark was ≥ 20 % below its peak versus not. This uses the existing
"no drawdown ≥ 20 %" banner logic from return-target-feasibility.

### 5.4 The vault

The last max(20 % of the history, 3 years) is **sealed**. It is evaluated **once**, after the signal's design is frozen and every
gate in §10 except G11 has passed on the walk-forward. If the vault result fails, the signal is retired. It is **not** retuned and
re-vaulted. A retired design counts as a trial forever. This is the only defence against walk-forward segments slowly turning
in-sample through repeated looks (White 2000's "data snooping": using one data set "more than once for purposes of inference or
model selection", [S10]).

---

## 6. Transaction cost model (India, Decimal, point-in-time)

### 6.1 Equity delivery and ETF (cash market) — rates as published today

Store each row in a new rule table, `rules/costs/india_equity.yaml`, using the same `effective_from`/`effective_to`/source/status
convention as `india.yaml`. **Rates before the dates below are NOT VERIFIED here.** A backtest period without a verified cost row
must use a conservative *upper bound* (for example today's rates × 1.5), flagged `costs_estimated`, or abstain.

| Component | Rate (delivery) | Side | Effective / status | Source |
|---|---|---|---|---|
| Brokerage | broker-specific (Zerodha: "Zero Brokerage") | — | REQUIRES CONFIGURATION (user's broker) | [S1] |
| STT | **0.1 %** of traded value | buy **and** sell | Unchanged by the 1-Apr-2026 F&O change (VERIFIED-SECONDARY [S1][S2]). Rounded to the nearest rupee ([S2]). | [S1], [S2] |
| Exchange transaction charge | **NSE 0.00307 %** · BSE 0.00375 % | each side | Broker page today ([S1]). NSE's own circular of 27-Sep-2024 set 0.00297 % from 1-Oct-2024, plus IPFT ₹10/crore; a Feb-2026 circular re-split the same total (NOT VERIFIED: the NSE archive timed out) | [S1], [S3] |
| SEBI turnover fee | **₹10 per crore** | each side | VERIFIED-SECONDARY | [S1] |
| Stamp duty | **0.015 %** ("₹1500 / crore") | **buy only** | VERIFIED-SECONDARY (broker page; Indian Stamp Act schedule not opened) | [S1] |
| GST | **18 %** on (brokerage + SEBI fee + transaction charge) | — | VERIFIED-SECONDARY | [S1] |
| DP charge | **₹15.34 per scrip per sell day** (₹3.5 CDSL + ₹9.5 broker + ₹2.34 GST) | sell | Broker-specific; REQUIRES CONFIGURATION | [S1] |
| Slippage | model, §6.3 | each side | design assumption + sensitivity | [S6] |

### 6.2 Mutual funds (already in repo)

| Component | Rate | Source in repo |
|---|---|---|
| Stamp duty on unit issue | 0.005 % (from 1-Jul-2020) | `costs.py`, indian-instruments-and-tax §1 (VERIFIED-SECONDARY) |
| STT on redemption, equity-oriented schemes | 0.001 % | indian-instruments-and-tax line 86 |
| Exit load | scheme-specific, FIFO lots | `costs.py` (REQUIRES CONFIGURATION per scheme SID; versioned by `valid_from`) |
| Cash drag during a switch | 3 working days uninvested (§4.1) | design rule |
| Brokerage/STT inside the NAV | already in NAV | not added again |

### 6.3 Slippage and spread

The free broker APIs give OHLC candles, not historical quotes, so the effective spread must be **estimated**:

- **Corwin–Schultz (2012) high-low estimator** [S6] ("Daily high (low) prices are almost always buy (sell) trades … the high–low
  ratio reflects both the stock's variance and its bid-ask spread"). It is computed per instrument over a trailing window ≤ τ.
  Cost per side = half the estimated spread, floored at 0.
- **Floor and stress:** use the larger of the estimate and a configured floor. A floor value for Indian large-cap ETFs is **NOT
  VERIFIED**; there is no source, so it is a parameter. Report results at **×0, ×1, ×2, ×3** slippage multipliers. A signal must
  survive **×2** (gate G7).
- **ETF premium/discount to iNAV** adds cost that NAV-based tests miss. Historical iNAV data source: NOT VERIFIED. Until it exists,
  ETF signals use the ×2 stress as their base case.
- **Market impact:** for retail ticket sizes it is assumed negligible relative to spread, but ticket size must be ≤ 1 % of the
  instrument's median daily traded value. Otherwise abstain (`illiquid`).

### 6.4 Fixture C-1 — equity delivery round trip (Decimal; rates as in §6.1; zero brokerage; buy and sell at the same price)

| Ticket (buy = sell) | STT (2 sides, ₹-rounded) | Exch. txn | SEBI | Stamp | GST | DP | **Total** | **% of ticket** |
|---|---|---|---|---|---|---|---|---|
| ₹10,000 | 20.00 | 0.6140 | 0.0200 | 1.5000 | 0.1141 | 15.34 | **₹37.59** | **0.376 %** |
| ₹1,00,000 | 200.00 | 6.1400 | 0.2000 | 15.0000 | 1.1412 | 15.34 | **₹237.82** | **0.238 %** |
| ₹5,00,000 | 1,000.00 | 30.7000 | 1.0000 | 75.0000 | 5.7060 | 15.34 | **₹1,127.75** | **0.226 %** |

The ₹1,00,000 total matches the broker-calculator example quoted in search results (₹237.82; [S1] secondary). Exchange charges,
SEBI fees and GST are shown unrounded. The contract note rounds them per the broker's practice (NOT VERIFIED), so the engine must
store its rounding convention as a rule row.

---

## 7. Tax-aware returns

### 7.1 Principle

A backtest return is reported in three layers, always side by side:
1. **gross**;
2. **after costs**;
3. **after costs and tax**.

Signals are judged only on layer 3, against a benchmark taxed identically.

### 7.2 Mechanics

- **Lot ledger:** every buy creates a lot (date, units, cost incl. stamp duty where the tax rules allow it as cost; that treatment
  is NOT VERIFIED here and must be a rule row). Sells consume lots **FIFO**, matching AMC and depository practice already used for
  exit loads (calc-methodology line 315). The statutory basis for FIFO in demat equity is NOT VERIFIED in this session.
- **Classification on transfer date:** look up `rules/tax/india.yaml` by transfer date and asset class:
  - holding period > 12 months → LTCG (listed equity / equity-oriented MF);
  - otherwise STCG;
  - specified (debt) MFs → slab, always short-term.

  Repo rows `EQ-STCG` (20 %) and `EQ-LTCG` (12.5 % above ₹1,25,000/yr) are VERIFIED-PRIMARY for transfers on or after
  23-Jul-2024 (indian-instruments-and-tax lines 484–486).
- **Annual exemption:** the ₹1.25 lakh s.112A (now s.198) exemption is **shared across all of the user's equity gains in the
  year**. A backtest cannot know the user's other gains, so it reports two bounds: **(a)** the exemption fully available to this
  strategy, and **(b)** the exemption already used elsewhere. The *conservative* bound (b) is used for gates. Exact use of the
  exemption is REQUIRES CONFIGURATION.
- **Losses:** set-off and carry-forward rules are applied within the strategy only (an upper bound on the benefit). The rule
  details must come from the tax table, and are NOT VERIFIED here.
- **Surcharge and cess:** applied per the repo's tax engine (4 % health & education cess; surcharge capped at 15 % for these
  gains, indian-instruments-and-tax line 450). The user's slab is REQUIRES CONFIGURATION, and the default is the highest slab
  (conservative).
- **Terminal liquidation:** at the end of the test, report both "liquidated (tax paid)" and "unrealised (deferred)" values. The
  benchmark buy-and-hold defers almost all tax, which is a real advantage the strategy must overcome. The **liquidated** comparison
  is the gating one.
- **Dividends:** taxed at slab when received (repo rules). Total-return comparisons must use the same treatment for strategy and
  benchmark.

### 7.3 Historical tax regimes needed before about 2024 (gap G-d)

| Period (transfer date) | Listed equity / equity-oriented MF LTCG | STCG | Status |
|---|---|---|---|
| up to 31-Mar-2018 | exempt under s.10(38) (STT paid) | 15 % | VERIFIED-SECONDARY [S8] |
| 1-Apr-2018 to 22-Jul-2024 | 10 % above ₹1 lakh, s.112A; **grandfathering**: cost = max(actual cost, min(FMV on 31-Jan-2018, sale price)) for lots bought ≤ 31-Jan-2018 | 15 % | LTCG/grandfathering VERIFIED-SECONDARY [S8]. Repo `EQ-STCG-OLD`/`EQ-LTCG-OLD` rows start only 2024-04-01, so earlier rows must be added |
| from 23-Jul-2024 | 12.5 % above ₹1.25 lakh | 20 % | VERIFIED-PRIMARY (repo) |

Debt-MF taxation also changed (units acquired from 1-Apr-2023 are deemed STCG at slab; repo row `MF-DEBT-SMF`). Earlier
indexation-era rules are not in the repo and are NOT VERIFIED here. **Rule:** a backtest window that crosses any period without a
verified tax row is reported pre-tax only, and its signal verdict is `ABSTAIN (tax_rules_missing)`.

### 7.4 Fixture T-1 — the tax cost of turnover (fictional trade)

Buy ₹1,00,000 and sell at ₹1,20,000 (gain ₹20,000), transfer after 23-Jul-2024. Costs are ignored to isolate tax.

| Holding | Rule | Tax before cess | Tax incl. 4 % cess |
|---|---|---|---|
| 8 months | STCG 20 % | ₹4,000.00 | **₹4,160.00** |
| 13 months, exemption already used | LTCG 12.5 % | ₹2,500.00 | **₹2,600.00** |
| 13 months, exemption available | LTCG 12.5 % on gain above ₹1,25,000 | ₹0.00 | **₹0.00** |

A rule that exits at 8 months instead of 13 gives up between ₹1,560 and ₹4,160 per ₹20,000 of gain (7.8 to 20.8 percentage points
of the gain) before any cost. Switching signals must clear this.

---

## 8. Benchmarks and the null hypothesis

- **H0:** the strategy's expected after-cost, after-tax edge over the benchmark is ≤ 0.
- The benchmark is fixed **before** seeing results and recorded in the trial registry. Changing it creates a new trial.
- **Mandatory comparators** in every report:
  1. buy-and-hold of the same instrument;
  2. a broad index fund on the relevant TRI;
  3. the risk-free carry (91-day T-bill, existing B3);
  4. for MF switching rules: hold-both static mix.
- **Directional hit rate** is compared with the **base rate**, not 50 % (existing red-team item 11).

---

## 9. Multiple-testing control

### 9.1 Trial registry (prerequisite for everything below)

This is an append-only table, `backtest_trials`. Each row holds:
- `trial_id`, `signal_family`, `params` (canonical JSON), `universe_id`, `H`, `benchmark_id`;
- `data_snapshot_hash`, `code_version`, `seed`, `created_at`;
- the OOS edge series hash, `n_periods`, `SR_hat`, skewness and kurtosis;
- `status` (`active` / `retired` / `vaulted_pass` / `vaulted_fail`).

Every evaluated configuration is logged automatically by the engine, including configurations a developer tried and abandoned.
N is the count of rows in the **family**. A signal whose family cannot report N fails gate G8.

**Effective number of trials.** Correlated trials (for example lookback 11 vs 12 months) are not independent. Use
`N_eff = clusters` from hierarchical clustering of the trials' OOS return correlations, as Bailey & López de Prado suggest (their
Appendix 3 "shows how N can be determined when the trials are not independent" [S4]). Report N and N_eff, and use **N (raw)** in
the conservative gate unless N_eff is computed and logged.

### 9.2 Family-wise error: Bonferroni and Holm (small families, ≤ about 20 trials)

Use Holm's sequentially rejective procedure [S9] (it "has a prescribed level of significance protection against error of the first
kind for any combination of true hypotheses") on one-sided p-values of the edge tests (HAC t-test or DM vs benchmark).

**Fixture MT-2:** five trials with p = [0.004, 0.011, 0.019, 0.030, 0.200] and α = 0.05.
- Bonferroni threshold 0.01: rejects **1** (0.004).
- Holm thresholds 0.010, 0.0125, 0.0167, …: 0.004 ≤ 0.010 ✓, 0.011 ≤ 0.0125 ✓, 0.019 > 0.0167 ✗, stop. Holm rejects **2**.

### 9.3 Data-snooping tests: White's Reality Check and Hansen's SPA (larger families)

- **White (2000) RC** [S10] tests "the null hypothesis that the best model encountered in a specification search has no predictive
  superiority over a given benchmark model".
- **Hansen (2005) SPA** [S11] is preferred: "more powerful and less sensitive to poor and irrelevant alternatives", through "a
  studentized test statistic … and a sample-dependent null distribution".
- **Implementation:** the loss is the negative edge per period, for each trial. Bootstrap with the **existing stationary-bootstrap
  machinery** (B2: Politis–Romano, Politis–White block length, deterministic PCG64 seed), with B = 5,000 or more resamples. Report
  the SPA consistent p-value and its Monte Carlo standard error.
- **Gate:** p_SPA < 0.05 for the selected trial against the benchmark.

### 9.4 Deflated Sharpe Ratio (DSR) and Minimum Track Record Length (MinTRL)

From Bailey & López de Prado (2014) [S4], with all Sharpe ratios **non-annualised** (per period):

- `PSR(SR*) = Φ( (ŜR − SR*) · √(T − 1) / √(1 − γ̂₃·ŜR + ((γ̂₄ − 1)/4)·ŜR²) )`, where γ₃ is skewness and γ₄ is (non-excess)
  kurtosis.
- `SR₀ = √V[{ŜR_n}] · ( (1 − γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e)) )`, where γ ≈ 0.5772 (Euler–Mascheroni) and V is the variance of
  the Sharpe ratios across trials.
- `DSR = PSR(SR₀)`. Gate: **DSR ≥ 0.95**.
- `MinTRL = 1 + (1 − γ̂₃·ŜR + ((γ̂₄ − 1)/4)·ŜR²) · (Φ⁻¹(0.95) / (ŜR − SR*))²` periods.

**Fixture DSR-1 (reproduces the paper's worked example [S4]).** Annualised SR = 2.5 over T = 1,250 daily observations (250/yr), so
per-period ŜR = 0.158114. N = 100 trials, V[SR_annual] = 0.5, so per-period V = 0.002. Skewness −3, kurtosis 10.
- SR₀ = **0.113172**. DSR = **0.9004**, below 0.95, so **rejected**.
- With N = 46: SR₀ = 0.100362 and DSR = **0.9505**, matching the paper's "0.9505".
- With normal returns (skewness 0, kurtosis 3) at N = 88: DSR = **0.9505**, matching the paper's "after N=88".

**Fixture MT-1 (luck alone).** Under H0 with T = 120 monthly observations, V[ŜR] ≈ 1/T. The expected best annualised SR among N
zero-skill trials is:
- N = 10: **0.50**
- N = 100: **0.80**
- N = 1,000: **1.03**

A backtest Sharpe of 0.8 after trying 100 variants is what pure noise produces.

**Fixture MT-3 (how long is enough).** Monthly data, SR* = 0.
- Annualised SR 0.5 (per-month 0.1443), normal returns: MinTRL = **132.2 months (about 11.0 years)**.
- Same SR with skewness −1 and kurtosis 6: **153.0 months**.
- Annualised SR 1.0: **34.8 months**.

These are **out-of-sample** months.

### 9.5 Probability of Backtest Overfitting (PBO)

PBO (Bailey, Borwein, López de Prado & Zhu 2017) [S5] is "the probability that the model configuration selected as optimal IS will
underperform the median of the N model configurations OOS", estimated by combinatorially symmetric cross-validation (CSCV):
1. Split the T × N trial-return matrix into S even slices (S = 16 default, so C(16, 8) = 12,870 combinations, which is
   deterministic and enumerable).
2. For each combination, pick the in-sample best and record the OOS rank logit.
3. PBO is the share of combinations with logit ≤ 0.

Gate: **PBO ≤ 0.20**. The threshold is a design choice: the paper gives no universal cutoff (NOT VERIFIED that any standard
exists). CSCV needs **all** trials' return series, which is another reason for the registry.

### 9.6 The t > 3 hurdle

Harvey, Liu & Zhu (2016) [S12]: "a newly discovered factor needs to clear a much higher hurdle, with a t-ratio greater than 3.0."
Use this as a **floor** for the HAC t-statistic of the mean edge, whatever the corrections in §9.2–9.5 say. It is cheap and
conservative, and it covers trials that went unlogged before the registry existed.

---

## 10. Minimum evidence gates (fail closed; all must pass or the engine shows ABSTAIN with the failing gate)

| Gate | Requirement | Failure output |
|---|---|---|
| G1 Data provenance | Every input series has a source id, licence status not BLOCKED, `known_time` populated, a snapshot hash | `ABSTAIN (data_unverified)` |
| G2 Survivorship | The universe is survivorship-free, or the signal is single-instrument (§3.2) | `ABSTAIN (survivorship_unverified)` |
| G3 Corporate actions | No unexplained price gap > 25 % or < −20 % on any day without a matching action or a logged market event (thresholds are design parameters) | `ABSTAIN (unadjusted_prices_suspected)` |
| G4 Leakage | All §4.2 invariants pass, and the shuffle canary passes | `ABSTAIN (leakage)` |
| G5 Sample size | ≥ 30 non-overlapping OOS periods (consistent with existing §5.3) **and** OOS length ≥ MinTRL at 95 % | `ABSTAIN (insufficient_evidence: has X, needs Y)` |
| G6 Costs and tax | Edge > 0 after costs and tax under the conservative bounds (exemption already used, highest slab, liquidated at end); verified cost and tax rows cover the whole window | `NO_SIGNAL (edge_not_positive_after_costs_tax)` / `ABSTAIN (tax_rules_missing)` |
| G7 Cost stress | Edge > 0 at slippage ×2 **and** total costs ×1.5 | `NO_SIGNAL (fragile_to_costs)` |
| G8 Trial registry | Family N known (raw and, if available, N_eff) | `ABSTAIN (trials_unknown)` |
| G9 Multiple testing | DSR ≥ 0.95 **and** (Holm-adjusted p < 0.05 if N ≤ 20, else SPA p < 0.05) **and** HAC t ≥ 3.0 | `NO_SIGNAL (not_significant_after_multiple_testing)` |
| G10 Robustness | Positive edge in ≥ 2 of 3 regimes; rolling-window variant positive; PBO ≤ 0.20; neighbouring parameter values (±1 grid step) also positive (no knife-edge optimum) | `NO_SIGNAL (not_robust)` |
| G11 Vault | Single evaluation of the sealed final period: edge > 0 after costs and tax, and inside the walk-forward 80 % range | `RETIRED (vault_fail)` |
| G12 Live decay monitor | After going live, the realised OOS edge is tracked. If the rolling 24-period edge is below 0 and below the lower 80 % bound of the backtest distribution, auto-revert to ABSTAIN (mirrors existing §7) | `SUSPENDED (decay)` |

Only after G1–G11 pass may the engine emit `SIGNAL` with status **VERIFIED** (all inputs verified) or **NOT VERIFIED** (an input
or rule row is secondary-only). In the NOT VERIFIED case the UI must show the signal as "evidence incomplete", not as an
instruction. The supervisor (ADR-0003) must also abstain if the user's own context (slab, exemption use, lots held, exit-load
schedule) is missing, because the after-tax verdict depends on it.

---

## 11. Reporting uncertainty

Every signal card and backtest page shows the following. All numbers come from the engine, with formula ids; no LLM text contains
numbers.

1. **Edge with an interval, not a point:** median annualised after-tax edge and its 80 % and 95 % stationary-bootstrap intervals
   (B2 machinery, deterministic seed, Monte Carlo standard error shown).
2. **Sharpe with PSR and DSR**, N and N_eff, and **MinTRL vs actual OOS length**, for example "needs 132 months; has 60".
3. **Drawdown distribution:** worst historical drawdown, plus the bootstrap 50th, 90th and 95th percentiles of max drawdown over
   the user's horizon, for strategy and benchmark.
4. **Layered returns table:** gross, after costs, after costs and tax, for strategy vs benchmark, under both exemption bounds and
   both terminal treatments.
5. **Sensitivity grid:** slippage ×0, ×1, ×2, ×3; cost ×1.5; tax slab variants; parameter ±1 step.
6. **Regime table:** edge per pre-declared sub-period, and in drawdown and non-drawdown regimes.
7. **Turnover and holding-period mix:** share of gains taxed as STCG vs LTCG.
8. **Plain-language error rate:** for example "An 80 % range is wrong 1 time in 5 by design", reusing existing red-team item 1. A
   "past backtest, not a promise" line uses compliance phrases from `rules/compliance_phrases.yaml`.
9. **Gate panel:** G1–G12 with pass/fail and the reason. When abstaining, show *what evidence would change the answer*.

Language rules: never "probability of profit" unless a calibration gate on the strategy's own predicted-vs-realised edges has
passed (consistent with ADR-0010's "scenario ranges, never probabilities"). Never annualise a sub-year result without labelling it
(calc Rule A3).

---

## 12. Determinism and engine design

- **Module:** `engine/backtest/` with `ledger.py` (Decimal lots, cash, fills), `costs_equity.py` (rule-table driven),
  `tax_lots.py` (wraps `engine/tax.py`), `walkforward.py` (wraps the existing `validation.py` splits), `multiple_testing.py`
  (Holm, DSR, PSR, MinTRL, SPA/RC, PBO/CSCV) and `report.py`.
- **Number types:** money, units, costs and tax are `Decimal` under `engine_context` (as in `money.py`). Test statistics may use
  float64, as the existing `validation.py` already does. Every float output is rounded to a declared number of decimal places
  before storage, so outputs stay byte-identical.
- **No clock, IO or randomness in `engine/`:** the as-of date, the data snapshot and the seed are passed in. The seed follows the
  existing `sha256(instrument|as_of|model_version)` scheme, extended with `trial_id`.
- **Run manifest:** each backtest stores code version, data snapshot hash, rule-table versions (tax and costs), trial id, seed and
  output hash. Re-running a manifest must reproduce the output hash (a test oracle, ADR-0011).
- **Tooling:** `arch` (already referenced for block length) provides SPA and stepwise multiple-comparison classes in Python. Their
  exact API was **NOT VERIFIED** in this session. If used, pin the version and cross-check against an in-repo reference
  implementation with fixtures. An R `pbo` package exists [S5 search result], which can serve as an external oracle for CSCV.

---

## 13. What to extend in `docs/forecasting/validation-methodology.md`

Proposed edits (not applied; this report changes no other file):

1. **New §10 "Signals and strategies"**, or a sibling document `docs/forecasting/backtest-methodology.md` that §6 links to. It
   would carry §1 definitions, §4 execution timing, §5 nested walk-forward plus vault, §8 benchmark null and §10 gates from this
   report.
2. **§3.1** should add the bitemporal `known_time` column for *all* inputs, plus rows for equity candles, corporate actions, index
   constituents and tax/cost rules (§3.1 here).
3. **§3.4** should add the single-stock **BLOCKED** status and the delisting-return rule (§3.2 here).
4. **New §3.5 "Corporate actions"** with the factor table and the "adjust as known at τ" rule (§3.3 here).
5. **§4** should add the inner/outer nesting, the vault rule and an optional CPCV note (§5 here).
6. **§6 rule 5** should go from "guidance only, not used in v1" to **mandatory for signals**: trial registry, DSR ≥ 0.95, Holm or
   SPA, PBO ≤ 0.20 and the t ≥ 3 floor, with fixtures DSR-1, MT-1, MT-2 and MT-3.
7. **New §5.5 "Strategy metrics"**: after-tax edge, PSR/DSR, MinTRL, turnover, drawdown distribution (§11 here).
8. **§8 suppression list** should add `tax_rules_missing`, `costs_estimated`, `survivorship_unverified`, `trials_unknown` and
   `illiquid`.
9. **§9 red-team** should add items 15–20 from §15 below.
10. **Rule tables:** add `rules/costs/india_equity.yaml`, and pre-2024 rows to `rules/tax/india.yaml` (§7.3), each with a primary
    source before they are marked VERIFIED.
11. **ADR:** a new ADR, "Signals require backtest gates G1–G12". ADR-0010 covers forecasts only.

---

## 14. Fixtures (all recomputed 2026-10-15; script kept in the session scratchpad, not committed)

| Id | Inputs | Expected |
|---|---|---|
| C-1 | Delivery round trip at §6.1 rates; tickets ₹10k, ₹1L, ₹5L | ₹37.5881 · ₹237.8212 · ₹1,127.7460 (STT rounded per side to whole ₹) |
| T-1 | ₹20,000 gain; STCG 20 % vs LTCG 12.5 %; cess 4 % | ₹4,160.00 · ₹2,600.00 · ₹0.00 |
| DSR-1 | ŜR = 2.5/√250, T = 1250, V = 0.5/250, γ₃ = −3, γ₄ = 10 | N=100: SR₀ 0.113172, DSR 0.9004; N=46: DSR 0.9505; N=88 with normal returns: DSR 0.9505 |
| MT-1 | T = 120, V = 1/T, H0 | E[max annualised SR]: N=10 → 0.4979; 100 → 0.8002; 1000 → 1.0294 |
| MT-2 | p = [.004, .011, .019, .030, .200], α = .05 | Bonferroni rejects 1; Holm rejects 2 |
| MT-3 | Monthly SR_ann 0.5 (normal; skewness −1/kurtosis 6), SR_ann 1.0 | MinTRL 132.22 / 152.99 / 34.82 months |
| WF-1 | Existing §4.2 toy purge/embargo fixture | unchanged; reused for the inner loop |

---

## 15. Red-team: how a backtest could mislead the user (additions to the existing list)

15. **Same-close fills.** Using the close that generated the signal as the fill price. G4 invariant 3 catches this.
16. **Today's cost and tax rates applied to 2015.** Rules must be looked up by date. Missing rows mean abstain, not "use current".
17. **Untaxed benchmark vs taxed strategy (or the reverse).** Both must be costed and taxed identically, and compared liquidated.
18. **The forgotten trials.** A single headline Sharpe whose N is unknown. G8 blocks it.
19. **Vault peeking.** Re-tuning after a vault failure. A retired design is permanent.
20. **Switch cash drag ignored.** MF switches assumed to be instantaneous. Use the 3-working-day gap (§4.1).
21. **"Signal" in a single-stock universe built from today's listings.** BLOCKED (§3.2).
22. **Exemption double-counting.** Assuming the full ₹1.25 lakh LTCG exemption for every strategy. The conservative bound gates.

---

## 16. What this means for the user's aim

The user wants signals, mutual funds and "everything needed to grow my money", including when to buy and sell stocks, and aims
for 20–25 % a year. This method makes that answerable **honestly**:

- **Stocks:** BLOCKED for signals until survivorship-free data exists (§3.2).
- **Mutual funds:** single-scheme and asset-class rules can be tested now. Cross-sectional rules ("pick the top fund") wait for
  the survivorship probe.
- **Index ETFs:** the best near-term candidates.

Given MinTRL (about 11 years of OOS data for a 0.5-Sharpe edge) and the multiple-testing hurdle, the expected result for most
ideas is "No suitable candidate", shown with the missing evidence. Separately, return-target-feasibility.md already shows that
20–25 % a year sits far above the long-run record of Indian broad indices. A signal that passes these gates is far more likely to
add a modest after-tax edge than to close that gap. The UI should say so.

---

## 17. Sources (all accessed 2026-10-15)

| Id | Source | Short quote / fact used | Status |
|---|---|---|---|
| S1 | Zerodha charges page, <https://zerodha.com/charges/> | Equity delivery: "Zero Brokerage"; STT "0.1% on buy & sell"; "NSE: 0.00307%", "BSE: 0.00375%"; "18% on (brokerage + SEBI charges + transaction charges)"; "₹10 / crore"; stamp "0.015% or ₹1500 / crore on buy side"; DP "₹15.34 per scrip (₹3.5 CDSL fee + ₹9.5 Zerodha fee + ₹2.34 GST) is charged … when stocks are sold, irrespective of quantity." | VERIFIED-SECONDARY (broker's own page; regulator/statute not opened) |
| S2 | Zerodha support, STT, <https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/how-is-the-securities-transaction-tax-stt-calculated> | Equity delivery "0.1% (₹100 per lakh)" on "Both buy and sell sides"; "The F&O rate changes took effect from 1 April 2026 as per Budget 2026–27"; "STT is rounded to the nearest rupee based on the paise portion" | VERIFIED-SECONDARY |
| S3 | NSE circular NSE/FA/64232 (27-Sep-2024), <https://nsearchives.nseindia.com/content/circulars/FA64232.pdf>; NSE/FA/73061 (27-Feb-2026), <https://nsearchives.nseindia.com/content/circulars/FA73061.pdf> | Search extract: cash market "Rs. 2.97 each side per lakh of traded value", effective "October 1, 2024"; the Feb-2026 circular reduced IPFT "to Rs. 0.01 per crore" with "corresponding adjustments in transaction charges", effective "March 01, 2026" | NOT VERIFIED (both PDFs timed out to the fetcher; quotes are from search extracts) |
| S4 | Bailey & López de Prado (2014), "The Deflated Sharpe Ratio", *JPM* 40(5); PDF <https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf>; SSRN <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551> | "DSR is a PSR where the rejection threshold is adjusted to reflect the multiplicity of trials"; Euler–Mascheroni "(approx. 0.5772)"; worked example "would have been 0.9505, above the 95% confidence level"; "Appendix 3 shows how N can be determined when the trials are not independent". Fixture DSR-1 reproduces 0.9004 / 0.9505. | VERIFIED (PDF opened and parsed) |
| S5 | Bailey, Borwein, López de Prado, Zhu, "The Probability of Backtest Overfitting", *J. Computational Finance* 20(4); <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253>; <https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf> | PBO = "The probability that the model configuration selected as optimal IS will underperform the median of the N model configurations OOS"; method "combinatorially symmetric cross-validation (CSCV)". R package: <https://github.com/mrbcuda/pbo> | VERIFIED-SECONDARY (abstract via search extract; PDF not opened) |
| S6 | Corwin & Schultz (2012), *J. Finance* 67(2) 719–760, <https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2012.01729.x> | "Daily high (low) prices are almost always buy (sell) trades. Hence, the high–low ratio reflects both the stock's variance and its bid-ask spread." | VERIFIED-SECONDARY (abstract via search extract) |
| S7 | SEBI circulars SEBI/HO/IMD/DF2/CIR/P/2020/175 (17-Sep-2020) and /2020/253, effective 1-Feb-2021, as summarised by AMFI and secondary sites, e.g. <https://www.valueresearchonline.com/learn/mutual-funds/understanding-nav-cut-off-times-and-sebi-rules-when-your-money-gets-which-nav/> | "The applicable NAV in respect of purchase of units … shall be subject to realization and availability of the funds in the bank account of mutual fund before the applicable cut-off timings … irrespective of the amount of investment, under all mutual fund schemes." Cut-offs: 3 pm (1:30 pm purchase for liquid/overnight). | VERIFIED-SECONDARY (the SEBI URL tried returned 404) |
| S8 | Income Tax Dept, s.112A, <https://www.incometaxindia.gov.in/w/section-112a-60> and <https://www.incometaxindia.gov.in/w/tax-on-long-term-capital-gains%E2%80%8B>; secondary <https://taxguru.in/income-tax/grandfathering-provisions-capital-gains.html> | Finance Act 2018 withdrew s.10(38) and inserted s.112A from 1-Apr-2018 (10 % above ₹1 lakh); grandfathering of gains up to 31-Jan-2018 via cost = higher of actual cost and lower of (FMV on 31-Jan-2018, sale price). | VERIFIED-SECONDARY (incometaxindia returned HTTP 403; content from search extracts) |
| S9 | Holm, S. (1979), "A Simple Sequentially Rejective Multiple Test Procedure", *Scand. J. Statistics* 6(2) 65–70, <https://www.jstor.org/stable/4615733> | "the test has a prescribed level of significance protection against error of the first kind for any combination of true hypotheses" | VERIFIED-SECONDARY (abstract via search extract) |
| S10 | White, H. (2000), "A Reality Check for Data Snooping", *Econometrica* 68(5) 1097–1126, <https://onlinelibrary.wiley.com/doi/abs/10.1111/1468-0262.00152> | "Data snooping occurs when a given set of data is used more than once for purposes of inference or model selection"; tests "the null hypothesis that the best model encountered in a specification search has no predictive superiority over a given benchmark model" | VERIFIED-SECONDARY (abstract via search extract) |
| S11 | Hansen, P. R. (2005), "A Test for Superior Predictive Ability", *JBES* 23(4) 365–380, <https://www.tandfonline.com/doi/abs/10.1198/073500105000000063> | "more powerful and less sensitive to poor and irrelevant alternatives … We use a studentized test statistic … and invoke a sample-dependent null distribution." | VERIFIED-SECONDARY (abstract via search extract) |
| S12 | Harvey, Liu & Zhu (2016), "… and the Cross-Section of Expected Returns", *RFS* 29(1) 5–68, <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2249314> | "a newly discovered factor needs to clear a much higher hurdle, with a t-ratio greater than 3.0" | VERIFIED-SECONDARY (abstract via search extract) |
| R1 | Repo: `docs/forecasting/validation-methodology.md`, `backend/src/iip/engine/forecasting/validation.py`, `backend/src/iip/engine/costs.py`, `backend/src/iip/rules/tax/india.yaml`, `docs/research/indian-instruments-and-tax.md`, `docs/research/wave1/research-equity-data-alt.md`, `docs/research/return-target-feasibility.md`, `docs/finance/calculation-methodology.md`, ADR-0010 | Existing rules cited by section/line above | read 2026-10-15 |

López de Prado (2018), *Advances in Financial Machine Learning*, chapters 7 and 12 (purging, embargo, CPCV), and Politis–Romano
(1994) / Politis–White (2004) are already cited in validation-methodology.md and were not re-opened.
