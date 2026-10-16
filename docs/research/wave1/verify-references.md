# Verification of `research-references.md` (topic: references)

Date: 2026-10-15. Role: adversarial skeptic. All checks were re-run independently on 2026-10-15 with `gh api`, `gh search`, `gh issue view`, one browser-equivalent GET of the NSE Terms of Use, and WebFetch/WebSearch. The report under review was not edited.

Limits: the WebSearch budget for this session ran out partway through. The Kite Connect developer terms (storage, redistribution, backtesting) could therefore not be searched for, and they stay **NOT VERIFIED**. No test suites were run, and nothing was installed.

## 0. Verdict summary

| ID | Claim | Verdict | One-line reason |
|---|---|---|---|
| R1 | No surveyed OSS project provides a validated Indian signal | **WEAKENED** | The conclusion holds, but "max 19 stars" is wrong. Broader queries return India strategy and scanner repos with 121–1,044 stars, and the report did not assess them. |
| R2 | India data libraries all scrape NSE, so BLOCKED | **WEAKENED** (core confirmed) | The NSE ToU quote was verified live. Five of the six libraries hit nseindia.com. PKScreener's main path is Zerodha Kite and Yahoo, not only NSE. |
| R3 | vectorbt Commons Clause; mlfinlab proprietary | **CONFIRMED** | Licence texts match verbatim. Caveat: the Commons Clause only restricts *selling*, so "ideas only" is a policy choice, not a legal requirement. |
| R4 | quantstats had real metric bugs | **WEAKENED** (core confirmed) | The maintainer confirmed and fixed the bugs, but all three close dates in the report are wrong. #514 and #571 are unconfirmed reports or questions, not established bugs. |
| R5 | The copyleft bucket | **CONFIRMED** | Every SPDX field matches. |
| R6 | XBOM and pandas_market_calendars NSE end in 2026 | **CONFIRMED** | Plus a useful nuance: XBOM *raises* past 2026-12-31 (it fails closed). |
| R7 | Borrowable permissive designs | **WEAKENED** | bt's default `lag` is **0 days**, the quoted docstring belongs to a different class, and skfolio's purge and embargo both default to 0. As written, the "guard" overstates what those defaults give you. |
| R8 | OpenBB moved to openbq-org; no India provider | **CONFIRMED** (as NOT VERIFIED) | NOT VERIFIED is the right status. New evidence is added below. |
| R9 | A licensed Indian price path exists *only* via Kite Connect | **REFUTED** | The project's own sibling reports document free Upstox and Angel One SmartAPI paths. Kite costs ₹500/month, which breaks the binding no-paid-API-keys rule. Kite candles are also not total-return. |

## 1. Per-finding checks

### R1. "No surveyed open-source project provides a validated Indian equity/MF signal": WEAKENED

**Confirmed parts:**
- `qlib/constant.py` lines 10–12 define only `REG_CN = "cn"`, `REG_US = "us"` and `REG_TW = "tw"`.
- `qlib/backtest/exchange.py`:
  - line 109: `trade_unit: trade unit, 100 for China A market.`
  - lines 48–49: `open_cost: float = 0.0015` and `close_cost: float = 0.0025`.
- Nautilus: I listed `crates/adapters/*` and `python/nautilus_trader/adapters/*` through the git tree API on 2026-10-15. Its venue adapters are architect_ax, betfair, binance, blockchain, bybit, coinapi, coinbase, databento, deribit, derive, dydx, hyperliquid, interactive_brokers, kraken, lighter, okx, polymarket, sandbox and tardis. None is an Indian venue. The report's "NOT VERIFIED" here can be upgraded to "verified absent".

**Contradicted part.** The evidence says India search queries "returned max 19 stars". That is true only for the report's narrow phrasings. On 2026-10-15, `gh search repos --sort stars` returned these repos, none of which the report assessed:

| Query | Repo | Stars | Licence | Description |
|---|---|---|---|---|
| "indian stock market" | `aakashlpin/kha-ching` | 121 | MIT | "Algotrading strategies for Indian Stock Markets" |
| "zerodha" | `srikar-kodakandla/fully-automated-nifty-options-trading` | 254 | MIT | — |
| "zerodha" | `deshwalmahesh/NSE-Stock-Scanner` | 348 | none | — |
| "zerodha" | `zerodha/kite-mcp-server` | 324 | MIT | official |
| "nse" | `maanavshah/stock-market-india` | 1,044 | MIT | "API for Indian Stock Market's NSE and BSE" |

None of these is likely to carry an out-of-sample, cost- and tax-aware validation. Even so:
- the conclusion rests on an incomplete search;
- the specific "max 19 stars" evidence is false as a description of the India repo landscape;
- a universal negative should be labelled "VERIFIED for the repos inspected", as the report's own section 5 table does, not "VERIFIED" outright.

**Consistency note.** The report's own section 5 status table numbers these claims differently from the finding IDs used here. For example, its R1 is "Licences" and its R4 is "No validated Indian signal". Any downstream ADR that cites "R-n" will be ambiguous.

### R2. "India data libraries all scrape NSE": WEAKENED (BLOCKED status confirmed)

**NSE ToU, re-fetched live.** The page is <https://www.nseindia.com/static/nse-terms-of-use>, fetched 2026-10-15 with one browser-equivalent GET; it shows "Updated on: 29/10/2025". It contains: *"…systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting) on or in relation to our Website / Mobile Application."* The quote matches the report.

**Code search** (`gh api search/code?q=nseindia+repo:…`, 2026-10-15):

| Library | Evidence that it hits nseindia.com |
|---|---|
| jugaad-data | 7 hits: `jugaad_data/nse/live.py`, `archives.py`, `history.py` |
| nsepython | 3 hits, including `nsepython/rahu.py` |
| nselib | 11 hits, including `nselib/libutil.py`, `debt/debt_data.py`, `indices/index_data.py` |
| nsetools | 10 hits, including `src/nsetools/urls.py`, `downloader.py` |
| eod2 | `src/defs/defs.py` imports `from nse import NSE` (the NseIndiaApi package); README: "download and update NSE stocks, indices, and delivery data" |

All five are confirmed.

**PKScreener is mischaracterised.** `pkscreener/classes/Fetcher.py` uses three sources:
- `PKNSETools.PKNSEStockDataFetcher` (NSE);
- a `PKDataProvider` described as *"Import high-performance data provider (replaces Yahoo Finance)"*;
- a yfinance fallback.

`docs/HIGH_PERFORMANCE_DATA.md` shows its primary source as the **"Zerodha Kite WebSocket API"**, fed through PKBrokers, plus "Local pickle files (cached)" and a "GitHub-based" scalable fetcher. Its data path is therefore a mix of:
- NSE scraping;
- Yahoo;
- broker data apparently redistributed through GitHub. That last point is my inference from the docs and is NOT VERIFIED.

PKScreener is still unusable for us, but for more reasons than "scrapes NSE". The blanket "all scrape NSE" statement is inaccurate.

### R3. vectorbt and mlfinlab licences: CONFIRMED

- **vectorbt.** `gh api repos/polakowo/vectorbt/license`, line 5: *"the grant of rights under the License will not include, and the License does not grant to you, the right to Sell the Software."* Line 11: "License: Apache 2.0 with Commons Clause". SPDX is NOASSERTION.
- **mlfinlab.** `LICENSE.txt` begins with "Copyright Protection Notice and Licensing Agreement", "LAST UPDATED November 2021". It states that acceptance happens by "ACCESSING, INSTALLING OR USING THE CODEBASE". The report quotes it accurately.

**Nuance the report omits.** Line 7 defines "Sell" as providing a product or service "for a fee or other consideration … whose value derives, entirely or substantially, from the functionality of the Software". This project is free and personal, so the Commons Clause would not bar non-commercial use. "Ideas only" is a conservative project policy (reasonable for an OSI-only rule), not a legal necessity, and the report should say so.

### R4. quantstats bugs: WEAKENED (core confirmed, citation dates wrong)

`gh issue view` and the issue timeline API, 2026-10-15:

| Issue | Actual state and close date | Report says | Maintainer comment (ranaroussi) |
|---|---|---|---|
| #549 | CLOSED/COMPLETED **2026-09-26** | closed 2026-09-24 | "Fixed in v0.0.83 … Confirmed exactly as you described" |
| #550 | CLOSED/COMPLETED **2026-09-26** | closed 2026-09-25 | "Fixed in v0.0.82 … Both parts were real. The raw-kurtosis formula was being fed excess kurtosis" |
| #546 | CLOSED/COMPLETED **2026-09-26** | closed 2026-09-12 | "Fixed in v0.0.83 … `_prepare_returns()` filled gaps with `0.0`" |
| #556 | CLOSED **2026-09-27** | 2026-09-27 | (correct) |
| #514 | OPEN | open | No maintainer confirmation checked. An arithmetic-mean information ratio is a common convention, so calling it a "bug" is a judgement. |
| #571 | OPEN | open | Phrased as a question, not a confirmed defect. |

The 2026-09-12 date for #546 is the date of a cross-reference (PR #547), not the closure. Three of the four close dates are therefore wrong. The substantive claim, that real metric bugs existed and were acknowledged, is well supported. The derived rules (no 0-fill, no auto-detection of input type) are sound.

### R5. Copyleft bucket: CONFIRMED

SPDX fields from `gh api repos/<o>/<r>`, 2026-10-15:
- backtrader: GPL-3.0
- nautilus_trader: LGPL-3.0
- backtesting.py: AGPL-3.0
- openalgo: AGPL-3.0
- nsepython: GPL-3.0
- eod2: GPL-3.0
- stock-pattern: GPL-3.0 (415 stars)

Omission: this project's own public repo (`Gaurav1112/investment-intelligence-pro`) has **no licence** (empty SPDX on 2026-10-15). It is all-rights-reserved but public. The copyleft "ideas only" policy should be stated against that fact.

### R6. Calendars end in 2026: CONFIRMED (plus a nuance)

- `exchange_calendars/exchange_calendar_xbom.py` ends with `"2026-12-25"` (line 472). The header cites NSE, BSE and Zerodha, with "Although NSE/BSE provides only current year's dates, Zerodha provides …".
- `pandas_market_calendars/calendars/nse.py` line 18: "Coverage is 1996 through 2026."
- **Nuance.** XBOM subclasses `PrecomputedExchangeCalendar`, whose `bound_max()` returns `{latest_precomputed_year}-12-31`. It has a `_bound_max_error_msg`: "The {name} holidays are only recorded to the year …". The XBOM oracle therefore **fails closed**: it raises rather than silently treating 2027 holidays as sessions. That matches the abstain principle.
- NOT VERIFIED: whether pandas_market_calendars' NSE calendar raises or silently treats unknown 2027 holidays as trading days.
- Practical point: the oracle expires in about 2.5 months from today.

### R7. Borrowable designs: WEAKENED

**Confirmed:**
- bt has the full Run/Select/Weigh stack, plus `SelectRandomly` (line 786) and `WeighRandomly` (line 1390).
- zipline `VolumeShareSlippage` uses `price * (1 + price_impact * (volume_share ** 2))` (line 246) and has `LiquidityExceeded` (line 44) and `volume_limit`.
- The qlib README line 76 reads "Point-in-Time database | Released (PR #343) on Mar 10, 2022". The Yahoo note is at line 274.
- skfolio `model_selection/` contains `_combinatorial.py`, `_walk_forward.py` and `_multiple_randomized_cv.py`, and is BSD-3-Clause.

**Overstated:**
- bt `algos.py` line 18 sets `_DEFAULT_LAG = pd.DateOffset(days=0)`. `SelectMomentum` and `StatTotalReturn` default to **zero lag**, so the same-bar look-ahead guard is opt-in, not built in.
- The quoted docstring "Each total return ends at now - lag" is at line 992, inside `StatMultiPeriodReturn` (class at line 983), not `StatTotalReturn`. `StatTotalReturn`'s own docstring reads "Total return is calculated in the inteval [now - lookback - lag, now - lag]".
- skfolio `CombinatorialPurgedCV` has `purged_size : int, default=0` and `embargo_size : int, default=0` (lines 105 and 110). An oracle comparison is meaningful only if these are set explicitly.

The design ideas remain valid. The spec should require `lag ≥ 1` session and a non-zero purge and embargo, rather than implying the reference libraries enforce them.

### R8. OpenBB transfer: CONFIRMED as NOT VERIFIED, with added evidence

- **Providers.** `openbb_platform/providers` lists bls, cboe, cftc, deribit, ecb, eia, famafrench, federal_reserve, finra, fred, government_us, imf, jodi, nasdaq, oecd, sec and tmx. There is no India provider. Confirmed.
- **Licence.** The LICENSE begins "Copyright (c) 2021-2026 OpenBB Inc. All files in this repository are licensed under the Apache License, Version 2.0." SPDX is NOASSERTION. Confirmed.
- **New evidence:**
  - `orgs/openbq-org` was created `2026-09-11T20:47:39Z`, has 8 public repos, no description, and is not verified.
  - The original `OpenBB-finance` org still exists (created 2021-03-04, 45 public repos), and `repos/OpenBB-finance/OpenBB` resolves to `openbq-org/OpenBB`.
  - Recent commits continue from the long-standing maintainer handle `deeleeramone` (2026-10-01 and 2026-10-02) and from `dlee-bq` (2026-10-12).
  - Continuity of a known maintainer points to a legitimate transfer, but it does not prove it.
  - "openbq" is one letter from "openbb", which is a typosquat-shaped name. **NOT VERIFIED stays correct**: pin by commit and never install from that org without an official announcement.

### R9. "Licensed Indian price path only via Kite Connect": REFUTED

- **Price confirmed.** Kite Connect costs ₹500/month and includes historical data. Zerodha support (<https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/historical-data-and-live-market-data-payment-plan>, accessed 2026-10-15) says: *"Both historical and live market data are included at no additional cost with your paid subscription."* The product page (<https://zerodha.com/products/api/>, accessed 2026-10-15) says: *"Full suite of APIs with realtime WebSocket streaming and historical candle data for ₹ 500 / month"*.
- **The "only" claim fails.** The project's own wave-1 reports, in the same directory, document free broker paths:
  - `research-equity-data-nse.md` line 17: "Upstox: the historical candle API is free, with daily candles 'Available from January, 2000'", citing <https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/>.
  - `research-equity-data-alt.md` line 21: "Angel One SmartAPI: free; Angel explicitly markets the data 'for backtesting purposes'".
  - `research-equity-data-alt.md` line 25: "Kite Connect (₹500/month) and Dhan (₹499 + taxes/month) fail the no-paid-keys rule."
- **Section 6.2 conflicts with the binding rules.** It asks the user to pay for Kite without noting that this violates "no paid API keys".
- **Kite data is not total-return, and it is mutable.** A Zerodha staff reply in forum thread 15250 (<https://kite.trade/forum/discussion/15250/adjusted-histroical-data>, July 2025, accessed 2026-10-15) says: *"Adjustments are made for bonuses, splits, rights issues, spin-offs, and extraordinary dividends."* Search summaries of other Zerodha forum posts say ordinary dividends (under 2%) are not adjusted, and that the API exposes no corporate-action flag or adjustment factor. Those two points are secondary and **NOT VERIFIED** by direct fetch. If they hold:
  - a Kite price series is a **price-return** series, so comparing it with a Nifty **TRI** benchmark, as section 4.5 proposes, is biased against the strategy;
  - re-downloads can change past values, so the deterministic engine must snapshot inputs with hashes.
- **Still NOT VERIFIED:** the Kite Connect developer terms on storage, redistribution and backtesting. The search budget was exhausted, and the product page links only the general <https://zerodha.com/terms-and-conditions/>.

## 2. Other spot checks

- **DSR quote: VERIFIED.** The PDF <https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf> (accessed 2026-10-15), page 2 abstract: *"The Deflated Sharpe Ratio (DSR) corrects for two leading sources of performance inflation: Selection bias under multiple testing and non-Normally distributed returns."* Page 1 reads "Journal of Portfolio Management, Forthcoming, 2014". The volume and issue "40(5)" were not seen in the PDF: **NOT VERIFIED** here.
- **PBO/CSCV quote: VERIFIED** through the SSRN abstract 2326253 listing (search result, 2026-10-15): *"We propose a framework that estimates the probability of backtest over-fitting (PBO) specifically in the context of investment simulations, through a numerical method that we call combinatorially symmetric cross-validation (CSCV)."* The SSRN listing says it is forthcoming in the Journal of Computational Finance.
- **SSRN 7198158** exists. It is López de Prado & Porcu, "The Deflated Sharpe Ratio: A Unified Framework for Search-Adjusted Performance Inference", posted 31 Jul 2026 (from the search snippet). The report correctly marks its contents NOT VERIFIED.
- **NautilusTrader README quotes: VERIFIED.** Line 80: "deterministic event-driven runtime for both research and live". Line 234: "128-bit integers with up to 16 decimals of precision".
- **Lean `Common/Market.cs`: VERIFIED.** Line 148 is `public const string India = "india";`, with the comment "NSE - National Stock Exchange".
- **backtrader: VERIFIED.** `bbroker.py` lines 236–237 set `('coc', False)` and `('coo', False)`. The last commit is 2023-04-19.
- **jugaad-data: VERIFIED.** There is no LICENSE (404), and PyPI shows `license = "YOLO"` with version 0.35.10.
- **Repo metadata: all match** (stars, SPDX, push dates) for the 22 repos re-queried. Minor drift only, for example nautilus 30,065 vs 30,064 stars.

## 3. Important omissions

1. **Free licensed broker paths (Upstox, Angel One SmartAPI) are missing**, even though sibling reports document them. The report steers toward a paid key that breaks the binding rules.
2. **Survivorship and point-in-time universe.** No surveyed reference supplies historical Indian index membership or delisted stocks, and qlib PIT is only a concept. Without them, any equity "signal" backtest is biased upward. This belongs among the bottom-line blockers.
3. **Total-return vs price-return mismatch** between broker candles and the TRI benchmark proposed in section 4.5.
4. **Mutable vendor history.** Corporate-action re-adjustment rewrites the past. The deterministic engine needs input snapshots with content hashes for each backtest id.
5. **No mutual-fund signal references.** The user's aim explicitly includes MFs, but this survey is equity and backtest only. It does not say whether *any* MF-selection signal (for example performance persistence) has a reference implementation or evidence. "No suitable candidate" should be stated explicitly for MFs too.
6. **`zerodha/kite-mcp-server`** (official, MIT, 324 stars) and the higher-starred India repos listed under R1 were not assessed.
7. **This project has no LICENSE file**, which affects how the permissive and copyleft buckets apply.
8. **Library defaults do not enforce safety.** bt lag = 0, and skfolio purge and embargo = 0. The spec must make these mandatory parameters with no defaults.
9. **The XBOM oracle fails closed after 2026-12-31.** That is good, but it expires in about 2.5 months, and no task is set to load the 2027 NSE holiday circular.

## 4. Sources (all accessed 2026-10-15)

- NSE Terms of Use: <https://www.nseindia.com/static/nse-terms-of-use>. "…systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting) on or in relation to our Website / Mobile Application."
- Zerodha Kite data pricing: <https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/historical-data-and-live-market-data-payment-plan>. "Both historical and live market data are included at no additional cost with your paid subscription."
- Zerodha API product page: <https://zerodha.com/products/api/>. "historical candle data for ₹ 500 / month"
- Kite forum thread 15250: <https://kite.trade/forum/discussion/15250/adjusted-histroical-data>. "Adjustments are made for bonuses, splits, rights issues, spin-offs, and extraordinary dividends."
- Bailey & López de Prado, DSR: <https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf>. "corrects for two leading sources of performance inflation"
- Bailey, Borwein, López de Prado & Zhu, PBO: <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253>. "combinatorially symmetric cross-validation (CSCV)"
- López de Prado & Porcu: <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7198158>. Title only (search snippet).
- GitHub (via `gh api`):
  - repos/{microsoft/qlib, polakowo/vectorbt, hudson-and-thames/mlfinlab, pmorissette/bt, stefan-jansen/zipline-reloaded, skfolio/skfolio, gerrymanoim/exchange_calendars, rsheftel/pandas_market_calendars, openbq-org/OpenBB, QuantConnect/Lean, mementum/backtrader, nautechsystems/nautilus_trader, pkjmesra/PKScreener, BennyThadikaran/eod2}
  - ranaroussi/quantstats issues #546, #549, #550, #556, #514, #571
  - orgs/openbq-org and orgs/OpenBB-finance
- Sibling reports: `docs/research/wave1/research-equity-data-nse.md` (lines 17, 44, 172, 190, 195) and `research-equity-data-alt.md` (lines 20–25, 41–48).
