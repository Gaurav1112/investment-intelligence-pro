# Wave 1: Open-source references for a deterministic Indian signals engine

Date: 2026-10-15. Scope: projects that could serve as **references** (ideas, specs, test oracles) for a signals and backtest layer. They are not runtime dependencies. Every number below comes from `gh api` or `gh search` calls made on 2026-10-15, or from a cited URL. Where a fact could not be checked, it says **NOT VERIFIED**.

The prior survey (`docs/research/github-reference-review.md`, `docs/research/reference-selection.md`) already covers portfolio trackers, fixed income and analytics libraries. This document adds the **signal and backtest** angle. Read it together with `docs/research/wave1/research-equity-data-nse.md`, which records that automated NSE collection is **BLOCKED** under NSE's Terms of Use.

## 0. Bottom line

1. **No surveyed project can be adopted as a signal source.** None ships a validated, out-of-sample, cost- and tax-aware Indian equity or MF signal. Most bundle US/China defaults, such as qlib's `trade_unit` "100 for China A market" and costs of 0.15%/0.25%. The engine must abstain until our own backtest (section 4) supports a signal. "No suitable candidate" applies to "a ready-made Indian signal".
2. **Borrow designs, not code, and write all money maths ourselves in `Decimal`.** Every Python backtester and metric library here is float64/pandas-based. NautilusTrader is the one project with fixed-point value types, and its licence is LGPL-3.0.
3. **Licence buckets (VERIFIED from LICENSE files or the GitHub SPDX field):**
   - **Permissive, code reuse allowed with notice:** OpenBB (Apache-2.0 text), zipline-reloaded, pyfolio-reloaded, empyrical-reloaded, alphalens-reloaded, quantstats, QuantConnect Lean (Apache-2.0); qlib, bt, ffn, PKScreener, pykiteconnect, pandas_market_calendars (MIT); skfolio (BSD-3); exchange_calendars (Apache-2.0); nselib (Apache-2.0); TA-Lib wrapper (BSD-2).
   - **Copyleft, ideas only:** backtrader (GPL-3.0), nsepython (GPL-3.0), eod2 and stock-pattern (GPL-3.0), nautilus_trader (LGPL-3.0), backtesting.py (AGPL-3.0), openalgo (AGPL-3.0).
   - **Not open source:** vectorbt (Apache-2.0 + Commons Clause, "no right to Sell"), mlfinlab (proprietary "Copyright Protection Notice and Licensing Agreement"), jugaad-data (no LICENSE; PyPI `license` = `'YOLO'`).
4. **Every India-specific data library surveyed scrapes NSE.** This applies to jugaad-data, nsepython, nselib, nsetools, eod2 and PKScreener. Their code may be correct, but their data path is **BLOCKED** for us by the NSE ToU: *"User is prohibited to conduct any systematic or automated data collection activities (including scraping…)"* (https://www.nseindia.com/static/nse-terms-of-use, accessed 2026-10-15, quoted in `research-equity-data-nse.md`).
5. **The most valuable things to borrow** are below. Each is detailed in section 2.
   - Validation and statistics gates: Deflated Sharpe Ratio, PBO/CSCV, purged and combinatorial cross-validation (skfolio BSD-3 as an oracle).
   - Event-driven, no-look-ahead fill semantics: zipline and Nautilus concepts.
   - The composable "algo stack" pattern: bt (MIT).
   - Factor-signal evaluation, meaning IC and quantile forward returns: alphalens-reloaded.
   - The point-in-time data concept: qlib.
   - India trading calendars as a test oracle: exchange_calendars XBOM, which lists holidays through 2026-12-25.

## 1. Method

- `gh api repos/<o>/<r>` gave stars, `pushed_at`, SPDX licence, archived flag and open issues (a count that includes PRs).
- `gh api repos/<o>/<r>/commits?per_page=1` gave the last commit date. `gh api repos/<o>/<r>/releases/latest` gave the latest release.
- LICENSE texts were read through the contents/licence API for vectorbt, OpenBB and mlfinlab.
- Code-level spot checks used the contents API. Files are named inline.
- `gh search repos` was run for India-specific repos with these queries, sorted by stars: "nse backtest", "indian stock backtesting", "nifty backtest", "nse bhavcopy", "india stock screener", "zerodha backtest", "nifty momentum strategy", "india quant", "nifty 50 trading strategy", "indian equity factor", "smallcase", "india momentum backtest", "nse eod data adjusted", "fama french india".
- WebSearch was used for the two statistical papers (section 3).
- Limits: issue trackers were sampled, not audited. Test suites were **not run**. Nothing was installed.

## 2. Per-project assessment

Stars and dates are as of 2026-10-15.

| Project | Licence (VERIFIED) | Stars | Last commit | Latest release | Open issues+PRs | Status for us |
|---|---|---|---|---|---|---|
| openbq-org/OpenBB (was OpenBB-finance/OpenBB) | LICENSE text: "All files in this repository are licensed under the Apache License, Version 2.0" (SPDX shows NOASSERTION) | 74,261 | 2026-10-12 | ODP (2026-09-30) | 101 | Reference only; no India provider |
| polakowo/vectorbt | Apache-2.0 **+ Commons Clause v1.0** (SPDX NOASSERTION) | 9,385 | 2026-10-14 | v1.1.2 (2026-10-09) | 130 | Ideas only; not open source |
| mementum/backtrader | GPL-3.0 | 23,486 | 2023-04-19 | none | 64 | Ideas only; unmaintained |
| stefan-jansen/zipline-reloaded | Apache-2.0 | 1,963 | 2025-11-13 | 3.1.1 (2025-07-23) | 39 | Design reference |
| microsoft/qlib | MIT | 49,381 | 2026-10-08 | v0.9.8 (2026-10-08) | 493 | Design reference (PIT, workflow) |
| pmorissette/bt (+ ffn) | MIT | 2,997 (ffn 2,683) | 2026-10-13 (ffn 2026-10-15) | v1.4.1 (2026-10-10) | 18 (ffn 10) | Design reference (algo stack) |
| stefan-jansen/pyfolio-reloaded | Apache-2.0 | 616 | 2026-10-15 | 0.9.9 (2025-07-23) | 16 | Report-layout reference |
| stefan-jansen/empyrical-reloaded | Apache-2.0 | 127 | 2026-10-15 | 0.5.12 (2025-06-01) | 47 | Metric-definition reference; dependency pitfall |
| ranaroussi/quantstats | Apache-2.0 | 7,712 | 2026-09-27 | v0.0.86 (2026-09-27) | 24 | Metric list reference; documented bugs |
| nautechsystems/nautilus_trader | LGPL-3.0 | 30,064 | 2026-10-15 | v1.231.0 (2026-08-02) | 122 | Architecture reference; ideas only |
| jugaad-py/jugaad-data | none (PyPI `'YOLO'`) | 585 | 2026-10-06 | none on GH (PyPI 0.35.10) | 27 | Rejected (no licence + NSE scraping) |
| aeron7/nsepython | GPL-3.0 | 370 | 2026-10-07 | v2.101 (2026-10-07) | 5 | Rejected (GPL + NSE scraping) |
| stefan-jansen/alphalens-reloaded | Apache-2.0 | 671 | 2026-10-15 | 0.4.5 (2025-07-23) | 17 | Signal-evaluation reference |
| skfolio/skfolio | BSD-3-Clause | 2,505 | 2026-10-14 | v1.8.6 (2026-10-14) | 35 | Test oracle for CV (dev-only) |
| QuantConnect/Lean | Apache-2.0 | 22,021 | 2026-10-15 | v2.4.0.1 (2017-08-08; releases not used) | 284 | Architecture reference; has `Market.India` |
| kernc/backtesting.py | AGPL-3.0 | 9,050 | push 2026-08-05 | none | 95 | Ideas only |
| hudson-and-thames/mlfinlab | Proprietary licence agreement | 4,943 | push 2023-10-02 | — | 49 | **Do not use or read code**; use the papers |
| gerrymanoim/exchange_calendars | Apache-2.0 | 680 | push 2026-10-12 | — | — | Calendar test oracle (XBOM) |
| rsheftel/pandas_market_calendars | MIT | 1,003 | push 2026-10-05 | — | — | Calendar cross-check (NSE/BSE) |

### 2.1 OpenBB

- **What it is.** A data-platform aggregator.
- **Providers.** `openbb_platform/providers` lists bls, cboe, cftc, deribit, ecb, eia, famafrench, federal_reserve, finra, fred, government_us, imf, jodi, nasdaq, oecd, sec and tmx. **None is India-specific.** (Checked via contents API, 2026-10-15.)
- **Borrow (Apache-2.0, so code is OK with NOTICE):**
  - The "provider → standard model → fetcher" split. Each provider maps raw fields onto one typed standard model. This matches our source-registry pattern: one adapter per source, a normalised schema, provenance attached.
  - `extensions/quantitative` and `technical` as a checklist of indicator names.
- **Pitfalls:**
  - The repo moved to the `openbq-org` organisation. The prior review found that org was created 2026-09-11, and the ownership change is **NOT VERIFIED**. Pin by commit if anything is ever vendored.
  - Many providers need keys or have terms we have not checked.
  - Indicators are float/pandas.
  - Useful for US macro (FRED, OECD, IMF) context only, and that is not core to an INR engine.

### 2.2 vectorbt

- **Licence text, verbatim:** *"the grant of rights under the License will not include, and the License does not grant to you, the right to Sell the Software"* ("Commons Clause" License Condition v1.0 in `LICENSE`, fetched via `gh api repos/polakowo/vectorbt/license`).
- **Change from the prior review.** The contents API now returns a file listing, so the earlier "HTTP 409 empty repository" anomaly did not reproduce on 2026-10-15.
- **Borrow (ideas only):**
  - Vectorised parameter sweeps, used to *measure* how many configurations were tried. That count feeds the Deflated Sharpe trial count N.
  - Separating entry/exit signal arrays from portfolio simulation.
- **Pitfalls:**
  - Not open source in the OSI sense.
  - Numba/float64.
  - Mass parameter sweeps are exactly the overfitting machine that PBO and DSR exist to penalise.

### 2.3 backtrader

- **Borrow (ideas only, GPL-3.0):**
  - Explicit broker flags that make look-ahead *opt-in and visible*. `backtrader/brokers/bbroker.py` defines `coc` ("Cheat-On-Close") and `coo` ("Cheat-On-Open"), both default `False`.
  - Our engine should go further: there is no cheat mode at all, and signals at close t fill at the open of t+1 or later.
  - The CommInfo concept: per-instrument commission schemes.
- **Pitfalls:**
  - Last commit 2023-04-19 and no releases, so unmaintained.
  - GPL.
  - Float prices.

### 2.4 zipline-reloaded

- **Borrow (Apache-2.0):**
  - **Pipeline API.** Factors are computed only on data available as of each session.
  - **Explicit slippage and commission models.** `src/zipline/finance/slippage.py` has `VolumeShareSlippage`, with fill price = `price * (1 + price_impact * (volume_share ** 2))` and a `volume_limit` cap that raises/limits on `LiquidityExceeded`.
  - Asset restrictions and a calendar-driven simulation clock (it depends on `exchange_calendars`).
- **Pitfalls:**
  - US-centric bundles.
  - The last release is 2025-07-23.
  - Float maths, and Cython extensions (`_finance_ext.pyx`).
  - The slippage constants are US-equity defaults. Indian costs must come from the cost model in section 4 (STT, exchange fees, stamp duty, GST, SEBI fee, DP charge). The rates are in `docs/research/indian-instruments-and-tax.md`; any rates not cited there are **NOT VERIFIED**.

### 2.5 qlib

- **Borrow (MIT):**
  - A **point-in-time database**. The README lists "Point-in-Time database | Released (PR #343) on Mar 10, 2022". We need the same concept for fundamentals and index membership: the "as-known-on" date is separate from the "as-of" date.
  - Workflow recording, so every experiment has a stored config and result.
  - The exchange abstraction (`qlib/backtest/exchange.py`) with `open_cost`, `close_cost`, `min_cost`, `impact_cost`, `limit_threshold` and `trade_unit` parameters. It is a good parameter checklist. NSE has price bands rather than China's ±10% limit, and a lot size of 1 for cash equity (**NOT VERIFIED** here).
- **Pitfalls:**
  - Supported regions are only `REG_CN`, `REG_US` and `REG_TW` (`qlib/constant.py`), so there is no India.
  - Its bundled data, per the README: *"the data is collected from Yahoo Finance, and the data might not be perfect"*. Yahoo's personal-use terms apply.
  - 493 open issues and PRs.
  - ML model zoo outputs are not deterministic across hardware.

### 2.6 bt / ffn

- **Borrow (MIT; code reuse allowed, but we will re-implement in Decimal):**
  - The **algo-stack** pattern from `bt/algos.py`. A strategy is a list of small composable steps:
    - `Run*` (scheduling: RunMonthly, RunQuarterly, RunIfOutOfBounds)
    - `Select*` (SelectAll, SelectHasData, SelectN, SelectMomentum, SelectWhere)
    - `Weigh*` (WeighEqually, WeighInvVol, WeighERC, WeighMeanVar, WeighTarget)
    - `Limit*`, `TargetVol`, `Rebalance`
  - The pattern maps cleanly onto a deterministic, auditable rule pipeline. Each step can emit a trace record.
  - `SelectMomentum` and `StatTotalReturn` take an explicit `lag`. The docstring says "Each total return ends at now - lag". This is a good guard against same-bar look-ahead, and our spec should require it.
- **Pitfalls:**
  - `SelectRandomly` and `WeighRandomly` exist. Our engine must not have randomness, or must seed it outside `engine/`.
  - pandas float.
  - No Indian cost or tax model.

### 2.7 pyfolio-reloaded / empyrical-reloaded / quantstats

- **Borrow (Apache-2.0):**
  - Metric *definitions* (Sharpe, Sortino, Calmar, max drawdown, tail ratio).
  - Tear-sheet *layout* ideas.
- **Pitfalls:**
  - Recent quantstats issues show real formula bugs, so use these libraries only as cross-check oracles after reconciling definitions:
    - #549 "rolling_sharpe / rolling_sortino de-annualize rf with the window length instead of periods_per_year" (closed 2026-09-24)
    - #550 "Probabilistic Sharpe ratio uses the wrong kurtosis and can return a probability above 1" (closed 2026-09-25)
    - #546 "_prepare_returns silently converts missing observations to 0.0 returns in every statistic" (closed 2026-09-12)
    - #556 "Discrepancies … between qs.stats.xx and qs.reports.metrics in qs 0.0.85" (closed 2026-09-27)
    - #514 "information_ratio() uses arithmetic mean instead of geometric" (open)
    - #571 "Can the price/returns auto-detection tell a sub-$1 price series from a return series?" (open)
  - Source: `gh issue list -R ranaroussi/quantstats`, 2026-10-15.
  - **Rule for us:** a missing observation is a gap, and the supervisor abstains on it. It is never a 0% return. The input type is declared and never auto-detected.
  - empyrical-reloaded: the prior review found that 0.5.12 pins an sdist-only `peewee`, and a wheel-only resolve falls back to 0.5.9, which pulls yfinance.

### 2.8 NautilusTrader

- **Borrow (ideas only; LGPL-3.0):**
  - A *"deterministic event-driven runtime for both research and live"*, where *"the same strategy and execution-algorithm code can run across backtest and live systems"* (README).
  - Fixed-point value types for `Price`, `Quantity` and `Money`: *"High-precision: 128-bit integers with up to 16 decimals of precision"* (README "Precision mode").
  - This validates our Decimal-only money path, and suggests storing prices as scaled integers in the DB (paise/tick multiples).
- **Pitfalls:**
  - Built for tick- and order-book-level trading, which is far beyond a monthly/weekly investor signal engine.
  - The Rust toolchain is heavy.
  - LGPL obligations if linked.
  - No Indian venue adapter was checked (**NOT VERIFIED**).

### 2.9 jugaad-data / nsepython (and other India data libraries)

- **jugaad-data** has no LICENSE, so it is all rights reserved, and PyPI says `'YOLO'`. **nsepython** is GPL-3.0.
- Both fetch from nseindia.com, which is **BLOCKED** under the NSE ToU.
- The prior review notes jugaad's RBI scraper labels the SDF rate as "Savings Deposit Rate", and returns silent previous-day data on holidays.
- **Borrow:**
  - Their *list of NSE report types* is a catalogue for manual-download options only (the user decision in `research-equity-data-nse.md`).
  - The holiday-data defect becomes a test case for us: a holiday must produce "no bar", never a copied bar.
- Same verdict for:
  - **RuchiTanmay/nselib**: Apache-2.0, 181 stars, scrapes NSE.
  - **vsjha18/nsetools**: MIT, 907 stars, last push 2025-03-18.
  - **BennyThadikaran/eod2**: GPL-3.0, 183 stars. Its description promises NSE EOD data "with added features" such as adjustment. Ideas only.
  - **pkjmesra/PKScreener**: MIT, 401 stars, an NSE screener. It is a catalogue of screening rules, but none of them is backtested to our standard.

### 2.10 Other relevant references

- **alphalens-reloaded (Apache-2.0).** The standard way to judge whether a *factor* has information: information coefficient (IC) by period, quantile forward returns, turnover and decay. **Borrow the evaluation report spec.** Every candidate signal must show positive, stable out-of-sample IC net of costs before it can exist.
- **skfolio (BSD-3).** `skfolio/model_selection` contains `_combinatorial.py` (combinatorial purged CV), `_walk_forward.py` and `_multiple_randomized_cv.py`. Use it as a **dev-only test oracle** to check our own Decimal/pure-Python walk-forward and purging implementation. It is not a runtime dependency.
- **QuantConnect Lean (Apache-2.0).** `Common/Market.cs` has `public const string India = "india"` with the comment "NSE - National Stock Exchange". Borrow its separation of the data, alpha, portfolio-construction, risk and execution models. Pitfalls: C#, cloud-oriented, and its India data path is **NOT VERIFIED**.
- **exchange_calendars XBOM (Apache-2.0).** Holidays are precomputed through `2026-12-25`. The file header cites the NSE and BSE holiday pages and Zerodha ("Although NSE/BSE provides only current year's dates, Zerodha provides holidays since 2013"). **pandas_market_calendars NSE (MIT)**: its docstring says "Coverage is 1996 through 2026".
  - **Use:** cross-check our own calendar table in tests.
  - **Pitfall:** both end in 2026. 2027 holidays must be entered manually from the official NSE circular, or the engine abstains for dates beyond its calendar.
- **backtesting.py (AGPL-3.0)** and **marketcalls/openalgo (AGPL-3.0, 2,860 stars, a broker-bridge platform):** ideas only. openalgo is an execution bridge, which is out of scope, because we never place orders.
- **zerodha/pykiteconnect (MIT, 1,318 stars, official client).** The only *licensed* Indian price path among these, through the user's own Kite Connect subscription. This is **REQUIRES CONFIGURATION**, and its storage and backtest terms are **NOT VERIFIED** (see `research-equity-data-nse.md`).
- **India-specific signal/backtest repos found by search.** The highest-starred results:
  - `85599/nifty-golden-pivot-strategy` (5 stars, MIT)
  - `marketcalls/opencase` (19 stars, AGPL)
  - `Pranav131111/NSE-Backtesting` (1 star, no licence)
  - All others have 0–4 stars, and most have no licence.
  - **No India-specific repo met a minimum bar** of a licence, tests, an out-of-sample method and a cost model. **No suitable candidate.**
- **mlfinlab.** The licence is a proprietary agreement: *"THE USER OF THIS CODEBASE IS SUBJECT TO ALL THE TERMS AND CONDITIONS IN THIS AGREEMENT"*, and acceptance happens by "ACCESSING, INSTALLING OR USING THE CODEBASE". **Do not read or copy its code.** Implement from the original papers in section 3 instead.

## 3. Statistical gates to borrow (papers, not code)

- **Deflated Sharpe Ratio.** Bailey & López de Prado (2014), JPM 40(5). https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551, accessed 2026-10-15: DSR *"corrects for two leading sources of performance inflation: Selection bias under multiple testing and non-Normally distributed returns."* A free PDF: https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf. A newer unified treatment: López de Prado & Porcu, https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7198158. Its contents are NOT VERIFIED beyond the search snippet.
- **Probability of Backtest Overfitting (CSCV).** Bailey, Borwein, López de Prado & Zhu. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253, accessed 2026-10-15. It proposes *"a framework that estimates the probability of backtest over-fitting (PBO)… through a numerical method that we call combinatorially symmetric cross-validation (CSCV)"*. Open copy: https://escholarship.org/uc/item/4w1110bb.
- **Implication.** The engine must record **every configuration tried**, which is the trial count N, in an append-only experiment log. DSR and PBO are computed from that log. A signal is published only if DSR passes and PBO is below a threshold the user chooses (see the user decisions). Note quantstats #550: PSR implementations are easy to get wrong. Implement from the paper and test against the paper's worked example.

## 4. Proposed reference-derived spec for our signal layer (for later ADR)

1. **Data contract.**
   - Point-in-time records (qlib idea), with an explicit exchange calendar (exchange_calendars idea).
   - Holidays and gaps produce no bar, and the supervisor abstains on them. Gaps are never filled with zero returns (quantstats #546) or with previous-day data (the jugaad defect).
2. **Signal timing.** A signal computed on close t, with an explicit `lag` ≥ 1 session (bt idea), fills at the next open or close plus slippage (zipline idea). There is no cheat mode (backtrader idea, made stricter).
3. **Strategy composition.** The Run → Select → Weigh → Limit → Rebalance stack (bt idea), with each step emitting a trace row.
4. **Money.**
   - Decimal or scaled-integer prices and quantities (Nautilus idea).
   - The Indian cost stack, and STCG/LTCG tax applied per lot (FIFO), using rates sourced in `indian-instruments-and-tax.md`.
   - Float is allowed only in statistics, behind a documented conversion boundary.
5. **Validation.**
   - Walk-forward with purge and embargo, plus CSCV/PBO and DSR (the papers, with skfolio as a dev-time oracle).
   - IC and quantile report (alphalens idea).
   - Benchmark: the relevant Nifty TRI or the category index fund, after costs and tax.
6. **Output.** Either a signal with a trace (data source, formula, backtest id, DSR, PBO, OOS period) or **"No suitable candidate / abstain"**. The LLM never produces numbers.

## 5. Status table

| ID | Claim | Status |
|---|---|---|
| R1 | Licences in the section 2 table | VERIFIED (gh API / LICENSE text, 2026-10-15) |
| R2 | vectorbt Commons Clause | VERIFIED |
| R3 | mlfinlab proprietary | VERIFIED |
| R4 | No surveyed project ships a validated Indian signal | VERIFIED for the repos inspected; India search, 14 queries |
| R5 | India data libraries scrape NSE, so they are BLOCKED for automation | BLOCKED (per NSE ToU quoted in `research-equity-data-nse.md`) |
| R6 | quantstats metric bugs | VERIFIED (issue titles) |
| R7 | XBOM/NSE calendars end in 2026 | VERIFIED |
| R8 | OpenBB ownership transfer to openbq-org legitimate | NOT VERIFIED |
| R9 | Lean / Nautilus India data paths | NOT VERIFIED |
| R10 | Kite Connect storage/backtest terms | REQUIRES CONFIGURATION / NOT VERIFIED |

## 6. Decisions only the user can make

1. **PBO and DSR thresholds** for publishing a signal. For example, PBO < 0.2 and DSR probability > 0.95; these numbers are illustrative only and are not recommendations.
2. **Licensed price data.** Will you pay for a licensed price path (Kite Connect ₹500/month per the prior research), or keep equity signals in abstain mode? Without lawful daily OHLC plus corporate actions, no equity buy/sell signal can be backtested.
3. **Dev-time oracles.** Is skfolio (BSD-3) acceptable as a dev-only test oracle dependency?
4. **Copyleft reading policy.** Is reading GPL/LGPL/AGPL source for ideas acceptable, or should we limit ourselves to their public docs (a clean-room policy)?
