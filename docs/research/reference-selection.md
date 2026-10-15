# Reference Selection: Investment Intelligence Pro

**Agent:** A (GitHub research and repository forensics)
**Observation date:** 2026-10-15. All evidence is in `github-reference-review.md`.

---

## 1. Scoring rubric

Each criterion is scored 0–5. The weighted total is `Σ(score × weight) / 5`, giving a value out of 100.

| Code | Criterion | Weight | Why this weight |
|---|---|---|---|
| C | Correctness (financial math, explicit conventions, regression tests on known values) | **15** | The product is decision support. A wrong XIRR, YTM, or NAV is worse than no answer |
| L | License compatibility (permissive = 5; weak copyleft / attribution-required = 2–4; AGPL/GPL/no-licence/Commons-Clause/non-commercial = 0–1) | **12** | The product may become proprietary. One bad dependency can block that |
| D | Data-source transparency (authoritative source, provenance, documented defects) | **10** | Every number must trace to AMFI, RBI, CCIL, FBIL, a bank, or the user's CAS |
| T | Test quality (presence, breadth, golden-value tests, reproducibility) | **10** | We will use references as oracles. Their own testing bounds our trust |
| M | Maintainability (recent commits and releases, issue load, bus factor) | 8 | Dead dependencies become security debt |
| S | Security (dependency hygiene, network side-effects, credential handling) | 8 | CAS PDFs hold PII. Analytics libraries must not phone home |
| P | Portfolio analytics depth (TWR/MWR/XIRR, risk measures, attribution) | 8 | A core feature, but we can implement much of it ourselves |
| U | UX / UI quality (for UI references) | 8 | Matters only for the UI role |
| F | Forecasting methodology (baselines, rolling-origin CV, proper scoring) | 8 | Forecasts must be honest. Methodology matters more than models |
| R | Production readiness (packaging, wheels, releases, docs) | 7 | Needed for dependencies, less so for idea-only references |
| E | Extensibility (plugin/provider boundaries, clean APIs) | 6 | Useful but secondary |

Weights sum to 100. **The composite is role-agnostic.** For example, a charting library scores 0 on F by design. Selections in section 3 are made **per role**, using the criteria relevant to that role. "[U]" marks a user-suggested repo.

## 2. Ranked matrix

| Rank | Candidate | C (15) | L (12) | D (10) | T (10) | M (8) | S (8) | P (8) | U (8) | F (8) | R (7) | E (6) | Weighted /100 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | skfolio | 5 | 5 | 4 | 5 | 5 | 4 | 5 | 1 | 2 | 4 | 5 | **83.8** |
| 2 | statsforecast | 5 | 5 | 4 | 5 | 5 | 4 | 0 | 0 | 5 | 5 | 4 | **79.2** |
| 3 | QuantLib (+SWIG) | 5 | 5 | 5 | 5 | 5 | 4 | 2 | 0 | 0 | 5 | 5 | **77.6** |
| 4 | ECharts | 4 | 5 | 5 | 4 | 5 | 4 | 0 | 4 | 0 | 5 | 5 | **75.8** |
| 5 | Recharts | 4 | 5 | 5 | 4 | 5 | 4 | 0 | 4 | 0 | 5 | 4 | **74.6** |
| 6 | sktime | 4 | 5 | 4 | 5 | 4 | 4 | 0 | 0 | 5 | 4 | 5 | **74.4** |
| 7 | Actual Budget | 4 | 5 | 4 | 4 | 5 | 4 | 0 | 5 | 0 | 5 | 4 | **74.2** |
| 8 | Portfolio Performance | 5 | 2 | 4 | 5 | 4 | 4 | 5 | 3 | 0 | 5 | 3 | **74.0** |
| 9 | lightweight-charts | 4 | 4 | 5 | 4 | 5 | 4 | 0 | 5 | 0 | 5 | 4 | **73.8** |
| 10 | scoringrules | 5 | 5 | 5 | 4 | 4 | 4 | 0 | 0 | 5 | 3 | 3 | **73.6** |
| 11 | Ghostfolio | 4 | 1 | 3 | 4 | 5 | 4 | 4 | 5 | 0 | 5 | 4 | **69.0** |
| 12 | casparser | 4 | 5 | 5 | 4 | 4 | 4 | 2 | 1 | 0 | 4 | 3 | **68.8** |
| 13 | PyPortfolioOpt | 4 | 5 | 4 | 4 | 3 | 4 | 4 | 0 | 1 | 3 | 4 | **68.2** |
| 14 | darts | 4 | 5 | 4 | 4 | 4 | 3 | 0 | 0 | 4 | 4 | 4 | **68.0** |
| 15 | visx | 4 | 5 | 5 | 3 | 3 | 4 | 0 | 3 | 0 | 4 | 5 | **67.6** |
| 16 | Wealthfolio | 4 | 1 | 3 | 4 | 4 | 4 | 4 | 5 | 1 | 4 | 4 | **67.6** |
| 17 | Riskfolio-Lib | 4 | 5 | 4 | 3 | 3 | 3 | 5 | 1 | 1 | 3 | 3 | **66.6** |
| 18 | pyxirr | 4 | 5 | 5 | 4 | 3 | 4 | 2 | 0 | 0 | 4 | 2 | **64.4** |
| 19 | empyrical-reloaded | 4 | 5 | 4 | 4 | 3 | 3 | 4 | 0 | 0 | 3 | 3 | **63.8** |
| 20 | OpenBB | 3 | 4 | 3 | 3 | 4 | 3 | 2 | 3 | 1 | 4 | 5 | **63.0** |
| 21 | pyfolio-reloaded | 4 | 5 | 3 | 3 | 3 | 3 | 4 | 2 | 0 | 3 | 2 | **61.8** |
| 22 | Firefly III | 4 | 1 | 4 | 4 | 4 | 4 | 1 | 3 | 0 | 5 | 4 | **61.4** |
| 23 | rateslib | 5 | 0 | 5 | 4 | 4 | 4 | 2 | 0 | 0 | 4 | 4 | **59.4** |
| 24 | [U] ai-hedge-fund | 2 | 5 | 2 | 4 | 4 | 3 | 2 | 3 | 1 | 2 | 4 | **58.4** |
| 25 | [U] daily_stock_analysis | 2 | 5 | 2 | 4 | 4 | 2 | 1 | 4 | 1 | 3 | 4 | **58.2** |
| 26 | captn3m0/india-isin-data | 4 | 5 | 5 | 1 | 4 | 4 | 0 | 0 | 0 | 4 | 3 | **58.0** |
| 27 | vectorbt | 4 | 1 | 3 | 3 | 4 | 3 | 3 | 2 | 1 | 4 | 4 | **57.6** |
| 28 | ffn / bt | 3 | 5 | 3 | 3 | 4 | 3 | 3 | 0 | 0 | 3 | 3 | **56.8** |
| 29 | quantstats | 3 | 5 | 2 | 2 | 3 | 3 | 4 | 2 | 0 | 3 | 3 | **56.0** |
| 30 | [U] india-trade-cli | 2 | 5 | 2 | 4 | 3 | 2 | 2 | 3 | 1 | 2 | 3 | **54.0** |
| 31 | properscoring | 4 | 5 | 5 | 3 | 0 | 3 | 0 | 0 | 4 | 1 | 1 | **53.8** |
| 32 | mftool | 3 | 5 | 4 | 2 | 3 | 3 | 1 | 0 | 0 | 3 | 3 | **52.0** |
| 33 | captn3m0/historical-mf-data | 3 | 2 | 5 | 1 | 4 | 4 | 0 | 0 | 0 | 3 | 3 | **46.4** |
| 34 | yfinance | 2 | 2 | 2 | 3 | 4 | 3 | 0 | 0 | 0 | 2 | 3 | **38.4** |
| 35 | backtrader | 3 | 1 | 3 | 2 | 1 | 2 | 2 | 1 | 0 | 2 | 3 | **37.4** |
| 36 | jugaad-data | 2 | 1 | 3 | 3 | 3 | 3 | 0 | 0 | 0 | 2 | 2 | **35.2** |
| 37 | nsepython | 2 | 1 | 3 | 1 | 3 | 2 | 0 | 0 | 0 | 2 | 2 | **29.6** |
| 38 | [U] ai-hedge-fund-india | 1 | 4 | 1 | 1 | 1 | 2 | 1 | 1 | 0 | 0 | 2 | **27.0** |
| 39 | [U] bulbea | 1 | 4 | 1 | 1 | 0 | 1 | 0 | 1 | 0 | 0 | 1 | **21.0** |

Not scored, because they are low relevance or superseded: maybe-finance/maybe (archived, AGPL), quantopian/empyrical (dead upstream, superseded by -reloaded), nsetools (stale since 2025-03), folioman (AGPL, small), stonks (AGPL, small), casparser-isin (folded into casparser).

### 2.1 Justification of the main scores
- **skfolio:**
  - C5: sklearn-style estimators with purged/walk-forward CV built in.
  - T5: `tests/` plus 6 workflows.
  - L5: BSD-3.
  - M5: released 2026-10-14.
  - U1: no UI.
  - F2: it is not a forecasting library, but its CV tooling is methodologically relevant.
- **statsforecast:**
  - C5 and F5: classical baselines plus rolling-origin `cross_validation`.
  - R5: arm64 cp312 wheel.
  - P0: no portfolio analytics.
  - S4: the pandas<3 pin is a dependency friction point, not a security issue.
- **QuantLib:**
  - C5 and T5: decades-old `test-suite`, 36 CI workflows, release 2026-10-13.
  - D5: conventions are explicit (day counters, calendars).
  - P2: not a portfolio tool.
  - U0: no UI.
- **Portfolio Performance:**
  - C5: dedicated `IRRTest`, performance-snapshot tests, and issue-regression tests.
  - L2: EPL-1.0 weak copyleft. Ideas are fine, code is not.
- **Ghostfolio and Wealthfolio:**
  - U5 and P4: mature dashboards with TWR/MWR calculators.
  - **L1**: AGPL-3.0. Wealthfolio additionally has a CLA that permits maintainer relicensing.
- **casparser:**
  - C4: Decimal types, per-RTA parsers.
  - D5: the user's own CAS is the most authoritative holdings source.
  - T4 rather than 5, because the fixtures are encrypted and contributors cannot reproduce them.
- **rateslib:** top-tier maths (C5), but L0 because its licence is non-commercial source-available.
- **vectorbt:** L1 for Commons Clause. The git API was inaccessible (HTTP 409), so T3 is **NOT VERIFIED**.
- **yfinance, jugaad-data, nsepython:**
  - C2: documented wrong corporate-action data (RAYMOND.NS) and silent previous-day holiday data in jugaad.
  - L1–2: Yahoo ToS says "personal use only"; jugaad has no licence; nsepython is GPL.
- **historical-mf-data:**
  - D5: AMFI data verbatim, with defects documented.
  - L2: no LICENSE on the scripts.
  - T1: no tests.
- **User-suggested repos:** see section 5. They all have low C and D because LLMs produce the numeric outputs (or a stale NN does, in bulbea's case).

---

## 3. Selections

### 3.1 Best overall architectural reference: **Wealthfolio** (ideas only)
- **Why:**
  - Local-first, single-user, SQLite-backed.
  - Decimal money (`rust_decimal`).
  - Clean domain crates (`core/portfolio/{allocation, allocation_targets: drift, rebalance, validation}`, `market-data`, `quotes`, `fx`, `goals`, `planning`, `limits`).
  - Separate `ai` crate (AI optional and isolated).
  - Playwright e2e, 11 workflows, release 2026-10-14.
  - This is closer to our "personal, deterministic, private" scope than Ghostfolio's server stack (NestJS + Postgres + Redis).
- **Runner-up:** Ghostfolio, for the calculator separation `twr | mwr | roi | roai` and the data-provider plugin pattern.
- **Reused as idea:**
  - Module boundaries.
  - Append-only activities, with derived holdings and valuations.
  - Market-data provider trait.
  - AI isolated in its own optional module.
  - Local SQLite with migrations.
- **Code eligible for reuse:** **none** (AGPL-3.0).
- **Must be rewritten:** everything, in Python with FastAPI and Decimal.
- **Incompatible:** Rust/Tauri runtime (not our stack), AGPL licence, global-equity data model (no AMFI/RBI instruments).
- **Residual risk:** accidental copying. Do not paste or translate its source line by line, and keep a clean-room note in PRs.

### 3.2 Best UI reference: **Ghostfolio** (UX ideas) + **ECharts / lightweight-charts** (components)
- **Ghostfolio UX ideas:**
  - Holdings table with allocation donut.
  - Performance chart with selectable range.
  - "X-ray" rule-based portfolio checks. These are deterministic, explainable findings, which maps directly to our evidence-first philosophy.
  - Its AGPL licence means ideas and screenshots only. Wealthfolio's UI is an equally good secondary inspiration and carries the same AGPL restriction.
- **Components to use as dependencies:**
  - **ECharts** (Apache-2.0, 67.5k@2026-10-15, release 6.1.0): main charting engine, with heatmaps, large series, and ARIA support.
  - **lightweight-charts** (Apache-2.0 + **mandatory TradingView attribution link/NOTICE**): optional, for NAV time series if the attribution is acceptable.
  - **Recharts** (MIT): simple React charts.
- **Residual risk:** the lightweight-charts attribution obligation must be implemented (`attributionLogo`) or the library avoided.

### 3.3 Best quant / portfolio-analytics reference: **skfolio**, with **Portfolio Performance** as the methodology reference for returns
- **skfolio** (BSD-3):
  - risk measures (CVaR, CDaR, max drawdown);
  - optimisation;
  - **WalkForward / CombinatorialPurgedCV**, which prevents look-ahead and overfitting in allocation backtests.
  - It is a permissive, maintained dependency. Use it as an **offline analytics engine and oracle**, not in the Decimal money path.
- **Portfolio Performance** (EPL-1.0): the authority on TTWROR vs IRR semantics and on the effect of transfers, fees, and taxes on returns. Its test cases (e.g. `Issue1898TradeIRRwithPortfolioTransfersTest`) are a checklist of edge cases to reproduce *as our own tests*. Ideas only.
- **Reused as idea:** metric definitions, CV protocols, and edge-case lists.
- **Code eligible:** skfolio as a pip dependency (BSD-3, attribution in NOTICE). No code from PP.
- **Must be rewritten:** money-weighted and time-weighted returns, drawdown, and volatility over Decimal NAV series, in our engine, with documented conventions (annualisation basis, calendar vs trading days).
- **Incompatible:** float64 internals for money-of-record.
- **Residual risk:** skfolio pulls `cvxpy-base`, which is a heavy transitive tree. Keep it in an optional `[analytics]` extra.

### 3.4 Best data-ingestion reference: **casparser** (dependency) + an **AMFI-direct** ingester we write, informed by **mftool** and **historical-mf-data**
- **casparser** (MIT, Decimal, pypdfium2): use it as a dependency for user CAS import (CAMS/KFintech/CDSL/NSDL), behind an adapter that maps to our domain model and validates totals, i.e. that the sum of transactions reconciles to the closing balance.
- **mftool:** confirms AMFI `NAVAll.txt` and the AMFI gateway endpoints. We reimplement a small, provenance-stamped AMFI client instead of depending on mftool:
  - mftool's tests are thin;
  - GitHub and PyPI release provenance diverge;
  - it mixes in the third-party mfapi.in.
- **historical-mf-data:** its documented AMFI defects (invalid ISINs `NOTAPP`/`NA`/`IINF…`/lowercase; NAV strings `#N/A`, `#DIV/0!`, `N.A.`, `B.C.`) become **mandatory validator test cases**.
- **Ideas from the [U] repos:** per-request source tracking (india-trade-cli `source_tracker.py`) and ordered fallback with capability boundaries (daily_stock_analysis). Both become persistent, per-record provenance.
- **Incompatible / rejected:**
  - jugaad-data (no licence; silent wrong-day holiday data);
  - nsepython (GPL);
  - yfinance (personal-use ToS, non-authoritative for MF/FI);
  - mfapi.in as a primary source (third-party mirror, SLA NOT VERIFIED).
- **Residual risk:** AMFI and RBI terms of use NOT VERIFIED in this review. casparser test fixtures are unverifiable.

### 3.5 Specialized references

| Role | Selection | Use | Licence | Evidence |
|---|---|---|---|---|
| Fixed-income math cross-check | **QuantLib-Python 1.44** | Test-only oracle for YTM, accrued interest, clean/dirty price, Macaulay/modified duration, and convexity for G-sec/SDL/corporate bonds with explicitly matched day count, frequency, and settlement. T-bill discount yield is simple enough to verify by hand-computed golden values | Modified BSD (QuantLib licence) | v1.44 (2026-10-13), 36 CI workflows, `test-suite/`, wheel `cp39-abi3-macosx_11_0_arm64` |
| *Rejected* for FI | rateslib | Better ergonomics, but **non-commercial source-available licence**. Must not be installed even as a test dependency if the product could become commercial | Non-commercial | LICENCE text read 2026-10-15 |
| Forecast evaluation | **statsforecast** (naive/seasonal-naive/ETS/ARIMA baselines + rolling-origin `cross_validation`) + **scoringrules** (CRPS, interval/quantile scores) | Every forecast must beat a naive baseline out of sample under rolling-origin evaluation, with an embargo gap, and be scored with a proper scoring rule. sktime is the methodology reference (temporal splitters) | Apache-2.0 / Apache-2.0 / BSD-3 | statsforecast v2.1.1 arm64 cp312 wheel (forces pandas<3); scoringrules 0.11.0 pure, py>=3.12 |
| XIRR | **pyxirr** primary oracle, **scipy.optimize.brentq** on our own XNPV as a second, independent oracle | Our engine implements XIRR in Decimal (bracketed Newton/bisection with a documented tolerance). Both oracles must agree within tolerance on golden cases: SIP series, redemptions, no-sign-change (must return "undefined", not a number), multiple roots | Unlicense / BSD-3 | pyxirr 0.10.8 cp312 arm64 wheel; scipy 1.18.1 cp312 arm64 wheel |
| Return-methodology checklist | Portfolio Performance tests | Reproduce its scenarios as our own fixtures | EPL (ideas only) | ~374 test files |
| Instrument identity | captn3m0/india-isin-data | ISIN master (CC0) | CC0-1.0 | release 2026-10-14 |

---

## 4. Independent test oracles: install check (macOS arm64, Python 3.12)

**Method:** PyPI JSON wheel tags, plus
`uv pip compile oracles.in --python-version 3.12 --python-platform aarch64-apple-darwin --only-binary :all:`
This is resolution only; nothing was installed into system Python.

| Library | Resolved (wheel-only, py3.12 arm64) | Wheel | Safe as oracle? | Notes |
|---|---|---|---|---|
| QuantLib | 1.44 | `quantlib-1.44-cp39-abi3-macosx_11_0_arm64.whl` | **Yes**: bonds, YTM, duration, day counts | Must match conventions explicitly, or the oracle "disagrees" for the wrong reason |
| pyxirr | 0.10.8 | `pyxirr-0.10.8-cp312-cp312-macosx_11_0_arm64.whl` | **Yes**: XIRR/XNPV | Last release 2025-11-03; stable scope |
| scipy | 1.18.1 | `cp312 macosx_12_0_arm64` | **Yes**: root-finding for an independent XIRR/YTM, stats | py>=3.12 |
| numpy-financial | **1.0.0** (latest 1.1.0 requires py>=3.13) | pure | Secondary only (IRR without dates, PMT/FV for FD and RD checks) | Version cap on 3.12 |
| scoringrules | 0.11.0 | pure | **Yes**: CRPS and interval scores | py>=3.12 |
| statsforecast | 2.1.1 (alone) / 2.0.1 (with pandas-3 co-deps) | arm64 cp312 | **Yes**: baselines and CV | **pins pandas<3**, so isolate it in a `[forecast]` extra |
| skfolio | 1.8.6 | pure (+ cvxpy-base) | Yes, for risk measures (float) | Heavy deps |
| empyrical-reloaded | **0.5.9** (0.5.12 needs sdist-only `peewee<3.17.4`) | pure | **Not recommended** | Wheel-only resolution pulls yfinance + curl-cffi (network libraries in a test oracle). Compute Sharpe/Sortino/max drawdown ourselves and cross-check with skfolio |
| quantstats | 0.0.86 | pure | Not recommended | Pulls yfinance, matplotlib, seaborn |
| casparser | 1.4.1 | pure, py>=3.11 | Dependency, not oracle | — |
| rateslib | 2.7.1 (abi3 arm64 wheel exists) | — | **No: licence** | Non-commercial |

**Recommended oracle set** (dev/test only, never imported by the runtime engine): `QuantLib`, `pyxirr`, `scipy`, `scoringrules`, `statsforecast` (in its own extra), and optionally `skfolio`.

Each oracle test must:
- record the oracle version;
- state the convention mapping;
- use a tolerance derived from Decimal rounding policy, not a magic epsilon.

---

## 5. User-suggested repositories: verdicts

| Repo | Weighted /100 | Idea adopted | Code reused | Rejected and why |
|---|---|---|---|---|
| achillesrasquinha/bulbea (2,340@2026-10-15; last commit 2017-03-19) | 21.0 | Anti-pattern converted into a rule: forecasts must beat naive baselines under rolling-origin CV with an embargo | None | Stale for 9 years; Quandl key and dead dataset; no baseline; overlapping-window train/test leakage at the split boundary; stochastic NN with no seeds; no India MF/FI relevance |
| ZhuLinsen/daily_stock_analysis (66,369@2026-10-15; created 2026-01-10) | 58.2 | Ordered data-source fallback with capability boundaries (made provenance-stamped); forward-only recommendation-outcome ledger with `engine_version`; scheduled run plus notification | None | LLM produces the advice and numbers; default needs a paid LLM key; affiliate/referral vendor links; float prices; no India coverage; star velocity is not evidence of correctness |
| virattt/ai-hedge-fund (63,997@2026-10-15) | 58.4 | **Phase 8 contract patterns:** versioned evidence contract; evidence-only prompt; abstain ≠ neutral; persisted prompt/response keyed by evidence hash; filing-date point-in-time discipline; hash-chained ledger; deterministic risk/portfolio after agents | None | LLMs emit `confidence` 0–100 and conviction in [-1, 1] that drive trades; needs financialdatasets.ai + paid LLM keys; US-only; same-close fills; LLM training-data look-ahead in backtests; no CI workflows |
| ashutoshsinghpr7/ai-hedge-fund-india (1@2026-10-15; 11 commits) | 27.0 | Deterministic caps computed before agent output (`max_shares`) | None (LICENSE is MIT with upstream notice, so legally reusable, but quality is too low) | LLM emits trade `quantity` and `confidence`; "RBI policy" agent uses no RBI data; silent 0.05 volatility default; empty backtester; screener.in scraping; 3 trivial tests |
| hopit-ai/india-trade-cli (120@2026-10-15) | 54.0 | Deterministic analyst phase, then an **agreement % plus named-conflict scorecard**, then LLM narration only; optional bull/bear "steelman" explainer with no numbers; LLM provider abstraction with local Ollama / OpenAI-compatible base URL; per-request source tracking (made persistent); **read-only** broker-style holdings-import interface | None | LLM `SynthesisOutput.confidence`; live trading and NFO options out of scope; unofficial `OPENAI_SESSION_TOKEN` provider; same-bar close fills; silent exception swallowing |

### 5.1 Phase 8 agent contract, distilled from the evidence
1. Agents receive **only** an immutable, hashed evidence bundle produced by the deterministic engine. Each number in the bundle carries its source, as-of date, and engine version.
2. Agent output schema contains **no free numeric fields**. Agents may reference engine numbers by ID (e.g. `{"cite": "metric:xirr:portfolio:2026-10-15"}`). A validator rejects any digit sequence in the narrative that does not match a cited value.
3. `status ∈ {answered, abstained}` with `abstain_reason`. Data gaps and parse failures abstain (ai-hedge-fund pattern). "Neutral" is a valid answered state, distinct from abstention.
4. Disagreement is computed **deterministically** (agreement %, named conflicts; india-trade-cli pattern) and displayed as is. The LLM may explain the disagreement but may not resolve it into a score.
5. The exact prompt, model id, contract version, and response are persisted for replay. The LLM is optional and local (Ollama / OpenAI-compatible localhost). If no LLM is configured, the deterministic report is complete on its own.

---

## 6. Hidden gems: merged verdicts (coordinator, 2026-10-15)

Source: `docs/research/hidden-gems.md` (36 repositories; source code read for the top 10). The verdicts below are merged into the
selection. Star counts are as observed on 2026-10-15 in that document.

| Gem | Licence | Role in this project | Notes and fixes we must make |
|---|---|---|---|
| codereverser/casparser-isin | MIT | **Eligible dependency** (deferred to CAS-import stage) for RTA/ISIN→AMFI code mapping | Its fuzzy name match accepts scores ≥ 60. We require an exact ISIN match and never use the fuzzy fallback in the ranking path. |
| captn3m0/india-isin-data | CC0 | **Fixture/reference data** for corporate-bond ISIN, coupon and maturity | No G-secs (an NSDL limitation). G-sec data is entered manually. |
| nci/scores | Apache-2.0 | **Test oracle** for Diebold–Mariano, CRPS, PIT and quantile loss | Dev-only dependency group; not in the runtime path. |
| frazane/scoringrules | Apache-2.0 | **Test oracle** for CRPS (closed form and fair ensemble) | Same as above. |
| eslazarev/purged-cross-validation | MIT | **Idea + oracle** for purged k-fold and embargo | We implement the purged walk-forward splitter ourselves (small, spec in validation-methodology.md) and test it against this library. |
| ShantanuAnant/mutualfund | MIT | **Idea**: cleanest `NAVAll.txt` parsing | Its bugs (NAV parsed as float; a malformed row becomes the AMC name) become **regression tests** for our parser. |
| codereverser/folioman | AGPL | **Ideas only**: reconciliation, `tax_safe` flag, ≤ 31-Jan-2018 grandfathering boundary | No code reuse (AGPL). |
| MohitGoyal09/india-merchant-data-api | none | **Pattern only**: fixture sidecar with sha256 + fetch time | No licence, so no code. Its RTGS-holiday error is a known pitfall: our G-sec settlement calendar must use RBI holidays, not NSE equity holidays. |
| the-solipsist/rbi-forex-reference-rates | public-domain-like | **Reference data** (SGB tranches/redemptions) | Not needed in v1. |
| jugaad-py/jugaad-data | none ("YOLO") | **Rejected** for runtime | Its RBI scraper labels the SDF rate as "Savings Deposit Rate", a cautionary example of a semantic mislabel. |
| pyxirr sample cash-flow CSVs | MIT/Unlicense | **Fixture source** for XIRR | Copied into tests with attribution. |
| jrvarma/bond_pricing | GPL-3.0 | **Out-of-tree oracle only** (never imported or vendored) | QuantLib is the primary bond oracle. |

### 6.1 Coordinator resolution of conflicting recommendations

| Topic | Agent A said | Agent G said | Decision (see ADR-006) |
|---|---|---|---|
| Charting | ECharts as the main engine | visx/d3-scale + Recharts; defer ECharts (368 kB) | **Recharts** for standard time series, plus **hand-built SVG components with `d3-scale`** for quantile dot plots and fan charts. ECharts deferred; lightweight-charts excluded (attribution obligation, trading orientation). Reason: smaller bundle, strict CSP friendliness, full control over uncertainty encodings. |
| Portfolio UI reference | Ghostfolio | Value Research density, Koyfin, Portfolio Visualizer | Both used as idea sources. No code from AGPL projects. |

## 7. Licence red flags (summary)

| Risk | Repos |
|---|---|
| AGPL-3.0 (no code reuse in a networked or proprietary product) | Ghostfolio, Wealthfolio (+CLA), Firefly III, maybe (archived), folioman, stonks |
| GPL-3.0 | nsepython, backtrader |
| Non-commercial / source-available | **rateslib** |
| Commons Clause ("no Sell") | **vectorbt** |
| No licence (all rights reserved) | jugaad-data (PyPI "YOLO"), captn3m0/historical-mf-data |
| Weak copyleft | Portfolio Performance (EPL-1.0) |
| Attribution required in UI | lightweight-charts (TradingView link/NOTICE) |
| Data terms rather than code licence | yfinance (Yahoo: "personal use only"), screener.in scraping (ai-hedge-fund-india), mfapi.in (third-party; terms NOT VERIFIED), AMFI/RBI terms (NOT VERIFIED) |
| Provenance anomalies | OpenBB transferred to `openbq-org` (org created 2026-09-11; NOT VERIFIED); vectorbt git API returns "empty repository" |
