# GitHub Reference Review: Investment Intelligence Pro

**Agent:** A (GitHub research and repository forensics)
**Observation date for every metric:** 2026-10-15. Star counts are given as `N@2026-10-15`.
**Status:** research input only. Nothing here is investment advice.

---

## 1. Methodology

1. **Discovery.** I ran `gh search repos` with these queries, sorted by stars: mfapi, amfi nav, casparser, mutual fund india, mftool, jugaad-data, nsepython, nsetools, historical mutual fund nav, india isin, xirr, portfolio tracker self-hosted, kite portfolio, ccil, government securities india, indian bonds, fixed income india, bond calculator ytm, rbi data, and mutual fund portfolio analyzer. I added well-known category leaders (portfolio trackers, quant libraries, charting, forecasting) from prior knowledge, then verified each one with the API. The user suggested 5 more repos (section 6).
2. **Facts.** Every fact below comes from the authenticated `gh` CLI:
   - `gh api repos/O/R`: stars, push date, SPDX licence, archived flag, open issues (GitHub's count includes open PRs), default branch, language.
   - `repos/O/R/releases?per_page=1`, `repos/O/R/commits?per_page=1`, and `contents/.github/workflows` (workflow count = "CI").
   - The git tree API for test directories and file counts.
   - The PyPI JSON API (`https://pypi.org/pypi/<pkg>/json`) for wheels and licences.
   - `uv pip compile --python-version 3.12 --python-platform aarch64-apple-darwin --only-binary :all:` as a dry-run dependency resolution. Nothing was installed and no repos were cloned.
3. **Code-level inspection.** For the top candidates and all user-suggested repos, I read the relevant source files through the contents API: signal and confidence generation, backtest fill logic, data clients, licence texts, and dependency manifests.
4. **Untrusted content.** All fetched README and source text was treated as data. Any instructions inside it were ignored.
5. **Limits.** "CI present" means at least one workflow file exists. It does not mean CI passes; I did not check pass rates. "Tests present" means test files exist. I did not measure coverage. Anything not checked is marked **NOT VERIFIED**.

---

## 2. Candidate list and evidence table

Column key:
- **CI** = number of `.github/workflows` files.
- **Tests** = test directory or test-file count from the git tree.
- **Rel** = latest GitHub release.
- **Issues** = open issues plus PRs.

### 2.1 India mutual-fund and market data

| Repo (URL) | Identity | Stars@2026-10-15 | Last push / last commit | Latest release | Issues | CI | Tests | License | Instruments / data source | Production vs demo |
|---|---|---|---|---|---|---|---|---|---|---|
| https://github.com/codereverser/casparser | CAMS/KFintech/CDSL/NSDL CAS PDF parser (Python) | 233 | 2026-09-23 / 2026-09-23 | v1.4.1 (2026-08-30) | 12 | 3 | `tests/` (CAMS, KFin, CDSL, NSDL, gains, e2e); fixtures are encrypted (`tests/files.enc`) | MIT | Indian MF and demat holdings and transactions from the user's own CAS PDF | Production library (on PyPI, py>=3.11) |
| https://github.com/codereverser/casparser-isin | ISIN and AMFI-code lookup database for casparser | 11 | 2026-10-07 / 2026-06-29 | v2026.6.9 | 2 | 3 | `tests/` | MIT | ISIN to scheme mapping | Production support lib |
| https://github.com/codereverser/folioman | MF portfolio manager built on casparser (Django + Vue) | 64 | 2026-10-15 / 2026-08-30 | none | 10 | 1 | ~136 test-like files | **AGPL-3.0** | Indian MF | Hobby app |
| https://github.com/NayakwadiS/mftool | AMFI and mfapi.in NAV client | 256 | 2026-10-05 / 2026-09-21 | GH v2.5 (2022-04-07); PyPI 3.4 (2026-09-21) | 6 | 1 | `tests/` (2 files) | MIT | AMFI `NAVAll.txt`, AMFI gateway endpoints, `api.mfapi.in` (third-party mirror) | Library; GitHub releases lag PyPI |
| https://github.com/captn3m0/historical-mf-data | Daily archive of AMFI NAV history as SQLite (`funds.db.zst`) | 46 | 2026-10-15 / 2026-10-15 | v2026.10.15 | 3 | 1 | none (0 test files) | **none (no LICENSE)** | AMFI exports, deliberately unmodified | Data pipeline (CalVer, "no schema stability guarantees") |
| https://github.com/captn3m0/india-isin-data | NSDL ISIN master data | 51 | 2026-10-14 / 2026-10-14 | v2026.10.14 | 4 | 1 | none found | CC0-1.0 | ISINs incl. MF, G-sec, bonds | Data pipeline |
| https://github.com/jugaad-py/jugaad-data | NSE/BSE/RBI scrapers | 586 | 2026-10-06 / 2026-10-06 | none (PyPI 0.35.10) | 27 | 3 | `tests/` | **none on GitHub; PyPI says "YOLO"** | NSE bhavcopy, equity/derivatives, some RBI | Fragile scraper |
| https://github.com/aeron7/nsepython | NSE website scraper | 370 | 2026-10-07 / 2026-10-07 | v2.101 | 5 | 1 | none found | **GPL-3.0** | NSE equity/F&O | Fragile scraper |
| https://github.com/vsjha18/nsetools | NSE live quotes | 907 | 2025-03-18 / 2025-03-18 | none | 2 | 0 | `tests/` | MIT | NSE equity | Stale (no push for 19 months) |
| https://github.com/ranaroussi/yfinance | Yahoo Finance unofficial client | 25,525 | 2026-10-12 / 2026-09-30 | 1.7.0 (2026-08-26) | 110 | 7 | `tests/` | Apache-2.0 (code); **data under Yahoo ToS, "personal use only"** | Global incl. `.NS`/`.BO` equities | Widely used, unofficial |
| https://github.com/openbq-org/OpenBB (was OpenBB-finance/OpenBB) | Open data platform / provider aggregator | 74,242 | 2026-10-15 / 2026-10-12 | openbb-v5.0.0 (2026-09-30) | 101 | 78 | ~1,642 test files | Apache-2.0 (LICENSE text; GitHub SPDX shows NOASSERTION) | Multi-provider, mostly US/global, many need keys | Production platform |

### 2.2 Portfolio trackers and personal-finance apps

| Repo | Identity | Stars@2026-10-15 | Push / commit | Release | Issues | CI | Tests | License | Notes |
|---|---|---|---|---|---|---|---|---|---|
| https://github.com/ghostfolio/ghostfolio | Wealth tracker (NestJS + Angular + Prisma/Postgres + Redis/Bull) | 9,448 | 2026-10-14 / 2026-10-14 | 3.86.0 (2026-10-13) | 318 | 3 | 77 `*.spec.ts`; calculators for `twr`, `mwr`, `roi`, `roai` | **AGPL-3.0** | Uses `big.js` for money; `yahoo-finance2` data |
| https://github.com/portfolio-performance/portfolio | Desktop portfolio performance (Java / Eclipse RCP) | 4,100 | 2026-10-14 / 2026-10-14 | 0.89.0 (2026-10-11) | 527 | 1 | ~374 Java test files incl. `IRRTest`, `ClientPerformanceSnapshotTest`, `PerformanceIndexTest` | **EPL-1.0** (weak copyleft) | Gold standard for TTWROR/IRR semantics |
| https://github.com/wealthfolio/wealthfolio (was afadil/wealthfolio) | Local-first desktop tracker (Tauri + Rust + React + SQLite) | 9,185 | 2026-10-15 / 2026-10-15 | v3.10.0 (2026-10-14) | 474 | 11 | `tests/`, `e2e/` (Playwright), ~950 test-ish paths | **AGPL-3.0 + CLA** (CLA lets maintainer relicense as proprietary) | `rust_decimal`, diesel/rusqlite, crates split `core`/`market-data`/`ai` |
| https://github.com/maybe-finance/maybe | Personal finance (Rails) | 54,222 | 2025-07-24 | v0.6.0 | 0 | 3 | `test/` | **AGPL-3.0, ARCHIVED** | Abandoned; do not depend on it |
| https://github.com/actualbudget/actual | Local-first budgeting (TS) | 29,496 | 2026-10-14 | v26.10.0 | 222 | 39 | ~336 test files | MIT | Budgeting, not investing. UX and local-first sync reference only |
| https://github.com/firefly-iii/firefly-iii | Personal finance manager (PHP/Laravel) | 24,897 | 2026-10-15 / 2026-10-11 | develop-20261014 | 160 | 9 | `tests/` | **AGPL-3.0** | Ledger and budgeting; low relevance |
| https://github.com/itskovacs/stonks | Small self-hosted tracker | 38 | 2026-06-14 | 1.3.0 | 0 | 1 | none found | **AGPL-3.0** | Low relevance |

### 2.3 Performance attribution, risk, and portfolio construction

| Repo | Stars@2026-10-15 | Push / commit | Release | Issues | CI | Tests | License | Notes |
|---|---|---|---|---|---|---|---|---|
| https://github.com/stefan-jansen/empyrical-reloaded | 127 | 2026-10-14 / 2025-07-29 | 0.5.12 (2025-06-01) | 45 | 6 | `tests/` | Apache-2.0 | 0.5.12 pins `peewee<3.17.4`, which is **sdist-only**. A wheel-only py3.12 resolve falls back to 0.5.9, which pulls **yfinance + curl-cffi** (network deps in a math lib) |
| https://github.com/quantopian/empyrical | 1,514 | 2024-07-26 / 2020-10-14 | 0.5.5 (2020) | 38 | 0 | NOT VERIFIED | Apache-2.0 | Dead upstream; use the -reloaded fork or reimplement |
| https://github.com/ranaroussi/quantstats | 7,708 | 2026-09-27 | v0.0.86 | 24 | 2 | `tests/` | Apache-2.0 | Pulls yfinance, matplotlib, seaborn. Report generator; metrics are float-based |
| https://github.com/stefan-jansen/pyfolio-reloaded | 616 | 2026-10-14 | 0.9.9 (2025-07-23) | 33 | 4 | `tests/` | Apache-2.0 | Tear sheets; notebook-oriented |
| https://github.com/skfolio/skfolio | 2,502 | 2026-10-14 | v1.8.6 (2026-10-14) | 35 | 6 | `tests/` | BSD-3-Clause | scikit-learn API, walk-forward and combinatorial purged CV, risk measures. Pure wheel |
| https://github.com/PyPortfolio/PyPortfolioOpt (was robertmartin8) | 6,098 | 2026-07-07 | v1.6.0 (2026-02-26) | 118 | 2 | `tests/` | MIT | Mean-variance, Black-Litterman, HRP |
| https://github.com/dcajasn/Riskfolio-Lib | 4,543 | 2026-10-04 | none on GH (PyPI 7.4.0) | 11 | 2 | `tests/` | BSD-3-Clause | Broad risk measures; C++ ext, universal2 wheel |
| https://github.com/pmorissette/ffn and /bt | 2,683 / 2,997 | 2026-10-14 / 2026-10-13 | v1.4.1 / v1.4.1 | 11 / 18 | 3 / 3 | `tests/` | MIT | Performance stats and simple backtests |

### 2.4 Fixed-income math and XIRR

| Repo | Stars@2026-10-15 | Push | Release | Issues | CI | Tests | License | Notes |
|---|---|---|---|---|---|---|---|---|
| https://github.com/lballabio/QuantLib | 7,670 | 2026-10-14 | v1.44 (2026-10-13) | 85 | 36 | `test-suite/` | QuantLib licence (modified BSD; PyPI says BSD-3-Clause; GitHub SPDX NOASSERTION) | Industry reference for day counts, schedules, YTM, duration, convexity |
| https://github.com/lballabio/QuantLib-SWIG | 403 | 2026-10-14 | v1.44 | 9 | 16 | ~40 test files | same | Python wheel `quantlib-1.44-cp39-abi3-macosx_11_0_arm64` exists |
| https://github.com/attack68/rateslib | 366 | 2026-05-20 / 2026-04-09 | none on GH (PyPI 2.7.1, 2026-04-04) | 24 | 12 | ~50 | **Source-available NON-COMMERCIAL + commercial subscription (Siffrorna Technology Ltd)** | Excellent fixed-income maths, but licence-incompatible with any commercial use |
| https://github.com/Anexen/pyxirr | 223 | 2025-11-03 | v0.10.8 (2025-11-03) | 14 | 2 | `tests/` | Unlicense | Rust-backed XIRR/XNPV/IRR. cp312 arm64 wheel exists. No push in ~11 months, but the scope is small and stable |

### 2.5 Charting (frontend)

| Repo | Stars@2026-10-15 | Push | Release | Issues | CI | Tests | License | Notes |
|---|---|---|---|---|---|---|---|---|
| https://github.com/tradingview/lightweight-charts | 17,577 | 2026-10-13 | plugins-2026-09-16 | 125 | 6 | `tests/` | Apache-2.0 **plus mandatory attribution**: README requires the NOTICE attribution and a link to tradingview.com (satisfiable via `attributionLogo`) | Best for NAV/price time series |
| https://github.com/recharts/recharts | 27,628 | 2026-10-15 | v3.11.0-canary.6 | 478 | 6 | `test/` | MIT | Idiomatic React; good for allocation, bars, small multiples |
| https://github.com/apache/echarts | 67,512 | 2026-10-13 | 6.1.0 (2026-05-19) | 1,487 | 7 | `test/` | Apache-2.0 | Most capable (heatmaps, large data, a11y "aria" decal) |
| https://github.com/airbnb/visx | 21,077 | 2026-06-22 | v4.0.0 (2026-06-11) | 156 | 2 | ~325 test files | MIT | Low-level primitives; most effort |

### 2.6 Backtesting, forecasting, and forecast evaluation

| Repo | Stars@2026-10-15 | Push | Release | Issues | CI | Tests | License | Notes |
|---|---|---|---|---|---|---|---|---|
| https://github.com/polakowo/vectorbt | 9,380 | 2026-10-14 | v1.1.2 (2026-10-09) | 130 | 4 | **INACCESSIBLE**: commits/tree API returned HTTP 409 "Git Repository is empty" on 2026-10-15 despite size > 0 and a recent release (provenance anomaly) | **Apache-2.0 + Commons Clause** (no right to "Sell") | Not usable in a paid product |
| https://github.com/mementum/backtrader | 23,484 | 2024-08-19 / 2023-04-19 | none | 64 | 0 | `tests/` | **GPL-3.0** | Unmaintained |
| https://github.com/Nixtla/statsforecast | 4,931 | 2026-10-14 | v2.1.1 (2026-07-16) | 166 | 8 | `tests/` | Apache-2.0 | Fast classical models (ETS, ARIMA, Theta), conformal intervals, `cross_validation`. Arm64 cp312 wheel. **v2.1.1 constrains pandas<3** (resolver picked pandas 2.3.3) |
| https://github.com/sktime/sktime | 10,067 | 2026-10-14 | v1.2.0 (2026-09-22) | 2,625 | 14 | ~577 test files (in-package) | BSD-3-Clause | Rigorous evaluation API (temporal splitters, `evaluate`) |
| https://github.com/unit8co/darts | 9,546 | 2026-10-14 | 0.47.0 | 219 | 5 | ~184 | Apache-2.0 | Heavier (torch optional) |
| https://github.com/frazane/scoringrules | 105 | 2026-07-25 | 0.11.0 (2026-06-06) | 22 | 3 | `tests/` | Apache-2.0 | CRPS, energy, log, interval/quantile scores. Pure wheel, py>=3.12 |
| https://github.com/properscoring/properscoring | 188 | 2023-03-09 | v0.1 (2015) | 10 | 0 | NOT VERIFIED | Apache-2.0 | **ARCHIVED**. Use only as a historical cross-check |

**Total candidates evaluated: 44.** That is 39 well-known or discovered repos plus 5 user-suggested ones.

---

## 3. India fixed-income: no open-source tooling found

GitHub searches for "ccil", "government securities india", "indian bonds", "fixed income india", "bond calculator ytm", and "rbi data" found **no maintained open-source project** with a credible implementation of Indian G-sec, SDL, T-bill, or corporate-bond conventions. Every hit had 0 to 1 stars or was unrelated. This means:

- We must implement Indian conventions ourselves from primary sources:
  - G-sec semi-annual coupons on 30/360.
  - T-bill discount and yield conventions on 364-day / Actual-365 bases.
  - SDL conventions.
  - CCIL/FBIL published methodologies.
- Each convention must be documented with its source.
- **QuantLib** is the independent cross-check oracle (see reference-selection.md sections 3.5 and 4).
- The NSDL ISIN data in **captn3m0/india-isin-data** (CC0) is the only reusable India-specific fixed-income artifact found. It covers instrument identity, not pricing.

---

## 4. Forensic notes on the top candidates

### 4.1 casparser (codereverser): India MF ingestion
- **Correctness signals:**
  - `casparser/types.py` uses `Decimal` for `amount`, `units`, `nav`, and `balance`, with a validator that coerces string-to-Decimal.
  - Separate parsers exist for CAMS detailed, CAMS summary, CDSL, and NSDL.
  - `analysis/gains.py` computes capital gains and has tests (`test_gains.py`, `test_gains_e2e.py`).
- **Dependency change:** The PDF backend is now `pypdfium2` (Apache/BSD, vendored C library). The README pins it with an ABI-bump guard. The older PyMuPDF dependency, which was AGPL, is gone, so the licence risk is removed.
- **Test caveat:** Test fixtures are encrypted (`tests/files.enc`) because real CAS PDFs contain PII. Contributors cannot reproduce the full test suite without the key. Treat its test claims as **partly unverifiable**.
- **Verdict:** Use it as a dependency (MIT) behind an adapter. Add our own synthetic CAS fixtures. Never upload user CAS files anywhere.

### 4.2 mftool (NayakwadiS): AMFI NAV client
- `mftool/const.json` points at:
  - `https://www.amfiindia.com/spages/NAVAll.txt` (authoritative AMFI daily NAV)
  - AMFI gateway endpoints for fund performance and AUM
  - `https://api.mfapi.in/mf/` (**third-party mirror, not AMFI**; server source and SLA NOT VERIFIED)
- Tests are thin: 2 files. GitHub releases stopped at v2.5 (2022), while PyPI is at 3.4 (2026-09-21), so release provenance is weak.
- **Verdict:** Use it as an idea only. Reimplement a ~150-line AMFI `NAVAll.txt` parser that:
  - stores every snapshot with its source URL, fetch timestamp, and content hash;
  - treats mfapi.in as an optional, labelled secondary source.

### 4.3 captn3m0/historical-mf-data: AMFI history backfill
- The README documents AMFI data defects kept verbatim:
  - invalid ISINs (`NOTAPP`, `NA`, `IINF…`, lowercase);
  - invalid NAVs (`#N/A`, `#DIV/0!`, `N.A.`, `B.C.`).
- **This is the most valuable data-quality evidence in the review.** Our ingestion validator must reject or quarantine exactly these cases.
- There is **no LICENSE** file. The scripts are therefore all-rights-reserved, and the data is AMFI's (AMFI terms NOT VERIFIED here).
- **Verdict:** Adopt the defect list as test cases. Download the SQLite dump only for personal backfill, after a licence and terms check. Do not redistribute it.

### 4.4 Portfolio Performance: performance-calculation correctness reference
- It has dedicated `math/IRR.java`, `IRRTest`, `ClientPerformanceSnapshotTest`, `PerformanceIndexTest`, and issue-regression tests (e.g. `Issue1898TradeIRRwithPortfolioTransfersTest`).
- It has ~374 test files and a release 4 days before observation.
- The licence is EPL-1.0. Code is weak copyleft, so **do not copy code**. The methodology (TTWROR vs IRR, handling of transfers and fees) is documented publicly and can be followed independently.

### 4.5 Ghostfolio: architectural and UX reference (ideas only)
- Clear layering: `apps/api` (NestJS) and `apps/client` (Angular), Prisma schema, Bull queues for data gathering.
- Pluggable data providers.
- Separate calculators for `twr`, `mwr`, `roi`, and `roai`, each with test utilities.
- `big.js` for decimal arithmetic.
- **AGPL-3.0:** no code reuse in a potentially proprietary or network-served product.

### 4.6 Wealthfolio: local-first architecture and UX reference (ideas only)
- Rust workspace with crates `core`, `market-data`, `ai`, `connect`, `device-sync`, and `http`.
- `rust_decimal` for money, diesel/rusqlite (SQLite), Tauri desktop shell, and React frontend with Playwright e2e.
- Its `crates/core/src/portfolio/` covers allocation, drift, rebalance, and validation. This module map is a strong template for our domain boundaries.
- **AGPL-3.0 plus a CLA** that lets the maintainer (Teymz Inc.) relicense contributions as proprietary. Ideas only.

### 4.7 skfolio: quant and portfolio-analytics reference
- BSD-3-Clause, released the day before observation, 6 CI workflows, pure-Python wheel.
- scikit-learn-compatible estimators.
- Built-in `WalkForward` and `CombinatorialPurgedCV`, which directly address look-ahead and overfitting in any allocation backtest.
- Many risk measures: CVaR, CDaR, drawdowns.
- Float64-based, like all of these libraries. Usable as an **offline analytics oracle**, never as the money-of-record path.

### 4.8 QuantLib: fixed-income oracle
- 36 CI workflows, `test-suite/`, v1.44 released 2026-10-13.
- The Python wheel is `abi3` arm64, so it installs on py3.12 (verified by resolution, section 7).
- Licence is permissive (modified BSD).
- Use only in tests to cross-check our own Decimal implementation of YTM, accrued interest, Macaulay/modified duration, and convexity under explicitly matched conventions.

### 4.9 statsforecast, scoringrules, and sktime: forecasting and evaluation
- **statsforecast** (Apache-2.0):
  - provides naive, seasonal-naive, ETS, and ARIMA baselines with `cross_validation` (rolling-origin);
  - has a cp312 arm64 wheel;
  - its latest version keeps pandas below 3, which affects our dependency pin.
- **scoringrules** (Apache-2.0, py>=3.12, pure wheel): CRPS and interval scores for probabilistic forecast evaluation.
- **sktime** (BSD-3): the best-documented evaluation protocol (temporal splitters). Use it as a reference for methodology.

### 4.10 Market-data scrapers: fragility evidence
- **yfinance:**
  - Its README states that Yahoo's API "is intended for **personal use only**" and that the project is not affiliated with Yahoo.
  - Issue (2025-05-28): "Incorrect historical data for RAYMOND.NS: abrupt drop from ₹1564 to ₹551 ... with no corporate action". This is a demerger handled incorrectly.
  - Issue (2026-03-17): HTTP 500/429 on some tickers.
  - It depends on `curl_cffi` browser impersonation to avoid blocking.
- **jugaad-data:**
  - Open issue (2026-08-18): "full_bhavcopy ... **silently return the previous trading day's data for a holiday**, with no way to detect it".
  - Open issue (2026-03-21): "FNO Bhavcopy download is broken".
  - No licence on GitHub ("YOLO" on PyPI).
- **nsepython:** GPL-3.0 scraper.
- **Conclusion:** none of these is an authoritative source for MF or fixed-income data.
  - For MFs, AMFI is authoritative.
  - For G-sec, T-bill, and SDL data, RBI, CCIL, and FBIL are authoritative.
  - Equity scrapers are out of scope, or optional and labelled.

### 4.11 Provenance anomalies (record and monitor)
- **OpenBB:** `OpenBB-finance/OpenBB` now redirects to `openbq-org/OpenBB`. The repo's `created_at` is 2020-12-20, so this is the same repo transferred, not a fork. But the `openbq-org` org was created 2026-09-11 and has no blog URL set. Its repos include `openbb-brightquery`. The `LICENSE` reads "Copyright (c) 2021-2026 OpenBB Inc. ... Apache License 2.0". I could not verify the ownership change through official announcements. Treat it as **NOT VERIFIED** and pin by commit if ever used.
- **vectorbt:** the git API reports the repo empty (HTTP 409) while metadata shows size 715,870 KB and a release on 2026-10-09. Code provenance cannot be audited through the API. This is another reason, beyond Commons Clause, to exclude it.
- **Renamed or transferred repos** (all redirect cleanly): `afadil/wealthfolio` → `wealthfolio/wealthfolio`, and `robertmartin8/PyPortfolioOpt` → `PyPortfolio/PyPortfolioOpt`.

---

## 5. Challenges to the planned stack

The planned stack is Python 3.12 + FastAPI + Decimal + SQLite + React/TS (Vite). The evidence mostly **supports** it, with five adjustments:

1. **Python 3.12 pin vs ecosystem drift.**
   - `numpy-financial` 1.1.0 (latest) requires **py>=3.13**. The resolver picks 1.0.0 on 3.12.
   - `scoringrules` and `scipy` 1.18 require **py>=3.12**.
   - `statsforecast` 2.1.1 forces **pandas<3**, while `quantstats` and `empyrical` resolve with pandas 3.0.6.
   - **Recommendation:**
     - Keep 3.12, but isolate heavy analytics and oracle libraries in a separate optional dependency group (`[oracles]`, `[forecast]`) so the core engine depends on neither pandas major version.
     - Lock with `uv` and resolve wheels-only in CI to catch sdist-only regressions. Example: empyrical-reloaded 0.5.12 → `peewee<3.17.4` is sdist-only → silent downgrade to 0.5.9, which pulls yfinance.
2. **Avoid pandas/NumPy in the money path.** Every analytics library reviewed (skfolio, empyrical, quantstats, PyPortfolioOpt, statsforecast) is float64. The reference trackers all use exact decimals for money: Ghostfolio uses `big.js` and Wealthfolio uses `rust_decimal`. Keep `Decimal` for cash flows, units, NAV×units, and accrued interest. Allow float only in clearly separated analytics (volatility, forecasts), converting at a documented boundary with explicit rounding.
3. **SQLite is validated.**
   - Wealthfolio (rusqlite/diesel) and historical-mf-data (a full AMFI NAV history distributed as SQLite) show SQLite is sufficient for single-user scale.
   - Ghostfolio's Postgres + Redis is overkill for a personal tool.
   - Store snapshots append-only with `source_url`, `fetched_at`, and `sha256`.
4. **Consider a local-first desktop shell later.** Wealthfolio's Tauri model (local SQLite, no server) fits "no paid keys, privacy of CAS data" better than a hosted web app. FastAPI on localhost plus a Vite SPA is fine for v1. Keep the API boundary clean so a Tauri shell can wrap it later. This is not a reason to switch to Rust now.
5. **Charting.**
   - lightweight-charts is the best fit for NAV and price series, but its licence *requires* a visible TradingView attribution link.
   - If attribution is unacceptable, use ECharts (Apache-2.0, no attribution UI requirement) for time series.
   - Use Recharts for simple React-native charts.

---

## 6. User-suggested repositories

All facts were observed 2026-10-15 through `gh api` and source reads via the contents API.

### 6.1 achillesrasquinha/bulbea
| Field | Evidence |
|---|---|
| URL / identity | https://github.com/achillesrasquinha/bulbea: "Deep Learning based Python Library for Stock Market Prediction and Modelling" |
| Stars@2026-10-15 | 2,340 |
| Activity | created 2017-03-09; last commit **2017-03-19**; last push 2021-01-17; no releases; 37 open issues |
| CI / tests | no `.github/workflows` (404); 2 small test files (`_util/tests`, `entity/tests/test_share.py`) |
| License | LICENSE file text is **Apache-2.0** (GitHub SPDX shows NOASSERTION) |
| Architecture | `Share` entity pulls prices from **Quandl** (the `WIKI` example dataset is long discontinued; current functionality NOT VERIFIED, very likely broken). Keras RNN in `learn/models/ann.py`; Twitter sentiment via `tweepy` + `textblob`; Flask app stub |
| Code-level finding | `learn/evaluation/split.py` builds overlapping sliding windows, then splits train/test by index with **no gap or embargo**, so the boundary windows share observations. The target is the next point of a per-window cumulative-return normalisation. The README's "prediction vs actual" plot is the classic one-step-ahead illusion: a persistence/naive forecast would look the same, and no naive baseline is reported. `i is 0` identity comparison (a Python SyntaxWarning, i.e. a latent bug) |
| Principles | Deterministic: no (NN training is stochastic, no seeds). Needs a paid key: Quandl API key. Provenance: none. India MF/FI relevance: **none** |
| **Decision** | **Rejected.** Adopt only the *anti-pattern* as a test: every forecast we show must beat a naive or seasonal-naive baseline under rolling-origin evaluation, with an embargo between train and test windows |

### 6.2 ZhuLinsen/daily_stock_analysis
| Field | Evidence |
|---|---|
| URL / identity | https://github.com/ZhuLinsen/daily_stock_analysis: LLM-driven daily stock "decision dashboard" for A-share, HK, US, JP, KR, and TW markets, pushed to WeCom/Feishu/Telegram/Slack/email |
| Stars@2026-10-15 | **66,369**. Repo created **2026-01-10**, so about 66k stars in 9 months. Treat that popularity with caution; it is not evidence of correctness |
| Activity | last push 2026-10-14; release v3.32.0 (2026-09-06); 34 open issues; 1,338 files |
| CI / tests | 10 workflows (ci, docker-publish, network-smoke, desktop-release, a *scheduled* `00-daily-analysis.yml`, …); **313 files under `tests/`** |
| License | MIT |
| Architecture | `data_provider/` with ordered fallback (efinance → AkShare → Tushare/pytdx → Baostock → yfinance → Longbridge/TickFlow); LiteLLM multi-provider client (Ollama supported, but README recommends cloud keys); FastAPI-style `api/v1`, React web app (`apps/dsa-web`), bots; `src/core/backtest_engine.py` |
| Code-level finding | `backtest_engine.py` is a "pure logic" evaluator. It scores **stored LLM advice** against later daily bars (`direction_correct`, `hit_stop_loss`, `first_hit`, `neutral_band_pct`, `engine_version`). Forward-only scoring of past recommendations is sound, but the recommendation itself, including its numbers, comes from the LLM. Prices are floats. README contains **affiliate and referral links** (`aff=`, `ref=`, `share_code=`) for LLM, data, and search vendors. `requirements.txt` explicitly excludes quarantined `litellm` 1.82.7/1.82.8 (a supply-chain incident), which is good hygiene but also confirms the dependency risk |
| Principles | LLM is the numeric/decision source: **violation**. Paid keys: the default path needs at least one LLM key; search APIs are optional. India: **no NSE/BSE/AMFI coverage**. No MFs or bonds |
| **Decision** | **Rejected as code and architecture reference.** **Ideas adopted:** (a) ordered data-source fallback with per-source capability boundaries, *but* each value must be stamped with its source, and we must never silently mix sources; (b) a forward-only "recommendation outcome ledger" with an `engine_version` field, used for our own deterministic signals; (c) scheduled-run plus notification UX. **Rejected:** LLM-generated advice and numbers, vendor referral dependencies, float money |

### 6.3 virattt/ai-hedge-fund
| Field | Evidence |
|---|---|
| URL / identity | https://github.com/virattt/ai-hedge-fund: "LLM investor agents and quant alpha models you can build, backtest, and run from your terminal" (pyproject v2.5.0) |
| Stars@2026-10-15 | 63,997 |
| Activity | created 2024-11-29; last push / commit **2026-10-02**; release v2.5.0 (2026-10-02); 177 open issues |
| CI / tests | **no `.github/workflows`** (404). Co-located `test_*.py` in most modules (backtesting, brokers, data incl. `test_client_contract.py`, llm, pipeline, risk, portfolio, features) |
| License | MIT |
| Architecture (current) | The repo has been **restructured**. There is no LangGraph dependency in `pyproject.toml` any more (deps: langchain-anthropic/openai/deepseek/google-genai/xai, pandas, scipy, textual). Package `hedge_fund/` contains: `signals/` (persona `AlphaModel`s: buffett, munger, graham, lynch, druckenmiller…, plus `QuantModel` base), `pipeline/stages.py`, `risk/limits.py`, `portfolio/construction.py`, `backtesting/engine.py`, `paper/ledger.py` (hash-chained), and `brokers/` (paper/sim) |
| Do LLMs produce numbers? | **Yes.** `signals/llm_agent.py::_parse` extracts `{signal, confidence, reasoning}` with `confidence` 0–100 from the LLM. `llm/contract.py` (v1 "Jev" contract) asks the model for a direction choice plus 0–4 "strength" scores and maps them to conviction in [-1, +1]. That conviction drives trades (`abs(signal.value) > threshold`). **This is a direct violation of our principle.** |
| Paid keys / vendor | README: requires a **financialdatasets.ai** key (`FINANCIAL_DATASETS_API_KEY`, `BASE_URL = https://api.financialdatasets.ai`) **and** one LLM provider key (Anthropic, OpenAI, DeepSeek, Google, xAI, Kimi, Jev). No Ollama in the dependency list |
| Market | **US-only** (SEC filings, `filing_date`, US tickers). No India, no MFs, no bonds |
| Look-ahead handling | *Good:* `data/client.py` filters fundamentals on **`filing_date_lte`**, not `report_period`, and excludes rows without a filing date. `features/snapshot.py` is point-in-time and hash-keyed. *Weaknesses:* (1) `backtesting/engine.py::_trade_ticker` enters at the **close of the signal date** (`price_map[d]`). If the signal uses day-d prices, this is a same-bar fill bias; the engine should fill at the next open or close. (2) **LLM training-data leakage**: a model trained after the backtest period "knows" the outcome, so no point-in-time data filter can remove that look-ahead. (3) Transaction costs NOT VERIFIED in the engine excerpt read. The README states "educational purposes only" |
| What the orchestration teaches (Phase 8) | (a) **Typed evidence contract:** a versioned request (`JEV_CONTRACT_VERSION`), "use only the supplied financial evidence", point-in-time snapshot as the only input, and a hashed snapshot as cache key. (b) **Abstention is first-class:** `Signal(value=0.0, metadata.abstained=True)` on data shortfall, call failure, or parse failure, distinct from a valid neutral. (c) **Exact prompt and response persisted** (PromptCache) for audit and replay. (d) Persona agents are independent and see the same evidence, and disagreement is preserved per agent rather than averaged away early. (e) Deterministic `risk/limits.py` and `portfolio/construction.py` sit *after* the agents |
| **Decision** | **Ideas adopted:** versioned evidence contract, abstain-vs-neutral distinction, prompt/response persistence keyed by evidence hash, filing-date point-in-time discipline, and hash-chained ledger. **Code reused:** none (MIT would allow it, but the design premise conflicts with ours). **Rejected:** LLM-produced conviction or confidence numbers, financialdatasets.ai and paid-LLM dependency, same-close fills, US-only data model. In our Phase 8, agents may only *cite and explain* engine-computed numbers and must abstain when evidence is missing |

### 6.4 ashutoshsinghpr7/ai-hedge-fund-india
| Field | Evidence |
|---|---|
| URL / identity | https://github.com/ashutoshsinghpr7/ai-hedge-fund-india: NSE/BSE adaptation of virattt/ai-hedge-fund (not a GitHub fork: `fork=false`) |
| Stars@2026-10-15 | 1 (0 forks) |
| Activity | created 2026-06-30; last push 2026-07-06; **11 commits**; release v0.1.1 (2026-07-06); 0 open issues |
| CI / tests | 2 workflows (`ci.yml`, `python-publish.yml`). `tests/test_basic.py` has **3 trivial tests** (`test_imports`, `test_ticker_stripping`, `test_universe`) |
| License | GitHub says NOASSERTION, but the **LICENSE text is MIT**: "Copyright (c) 2026 ace / Original work Copyright (c) 2024 virattt/ai-hedge-fund (MIT License)". The code is reusable under MIT if both notices are kept. Practically there is nothing worth reusing |
| "22-agent LangGraph" claim | **Real in structure.** `src/graph/workflow.py` uses `langgraph.graph.StateGraph`: `start_node` fans out to every analyst node, then `risk_management_agent`, then `portfolio_manager`, then END. `src/agents/` has 25 agent modules: 23 analysts/helpers including India personas (Jhunjhunwala, Damani, Pabrai), `fii_dii_flow`, `rbi_policy`, plus risk manager and portfolio manager. Roughly 22 analysts is plausible |
| Data layer | `src/data/providers/yfinance_provider.py` resolves bare tickers to `.NS`, then falls back to `.BO`. `src/data/scrapers/screener.py` **scrapes screener.in** with `httpx` + BeautifulSoup and a custom User-Agent (site terms NOT VERIFIED, scraping risk). `pyproject`: `yfinance ^0.2.40`, `langgraph ^0.2.0`, langchain-openai/anthropic |
| How numbers are produced | `rbi_policy.py` computes a deterministic point score from **company debt/equity and other metrics**. It does **not** ingest any RBI repo-rate or yield data despite the name. It then calls `call_llm`, which returns `confidence: float 0–100`. `portfolio_manager.py`: the LLM outputs **`quantity: int`** and **`confidence: int`**, bounded by deterministic `max_shares` = `remaining_position_limit // price`. `risk_manager.py`: deterministic volatility-adjusted limit, but **silently substitutes `daily_volatility 0.05`** when price data is missing (a fabricated fallback). `src/backtesting/__init__.py` is **empty (0 lines)**, so there is no backtester |
| India MF/FI relevance | None. Equities only; the "RBI policy" label is misleading |
| **Decision** | **Rejected.** Idea noted: deterministic hard caps computed *before* any agent output (`max_shares`), so an agent can never exceed a computed bound. Anti-patterns logged as tests we must have: no silent default for missing volatility, and agent names must not claim data sources they do not use |

### 6.5 hopit-ai/india-trade-cli (the user wrote "hopit-ai/india-trade", which 404s)
| Field | Evidence |
|---|---|
| URL / identity | https://github.com/hopit-ai/india-trade-cli: Indian trading CLI with multi-agent analysis, brokers, options, macOS app |
| Stars@2026-10-15 | 120 (46 forks) |
| Activity | created 2026-03-17; last push 2026-09-03; last commit 2026-08-27; no releases; 71 open issues; 413 files |
| CI / tests | 2 workflows (`ci.yml`, `build-mac.yml`). ~100 test files in `tests/`, incl. `test_persona_debate.py`, `test_risk_debate.py`, `test_risk_gate.py`, `test_dag_orchestrator.py`, `test_backtest*.py`, `test_position_sizer.py`, `test_data_fallback.py`. A `network` pytest marker exists for yfinance/NSE tests |
| License | MIT |
| Agent design (`agent/multi_agent.py`) | Phase 1: analyst team, **"pure Python, no LLM"**, run in parallel, producing `AnalystReport{verdict, confidence 0–100, score}`. A deterministic `compute_scorecard` builds a weighted total and an **agreement %** and lists conflicts ("Technical BULLISH vs Fundamental BEARISH"). Phase 2: bull and bear researchers **debate** for 2 rounds plus a facilitator summary (LLM). Phase 3: fund-manager synthesis (LLM) produces `SynthesisOutput{confidence: int 0–100, rationale, risks}`. Exception: the news analyst uses 1 LLM call for sentiment |
| How numbers are produced | Analyst scores and confidences are deterministic Python. **The final verdict confidence and trade recommendation come from the LLM** (`SynthesisOutput.confidence`), which is a violation for us. Persona outputs (`PersonaSignal.confidence`) are also LLM-produced |
| LLM abstraction (`agent/core.py`) | Providers: anthropic, openai, gemini, **ollama** (default `llama3.1`, via `OPENAI_BASE_URL=http://localhost:11434/v1`), plus OpenAI-compatible (Groq/Together/OpenRouter). Also `claude_subscription` (shells out to the Claude Code CLI) and **`openai_subscription` using an "unofficial" `OPENAI_SESSION_TOKEN`**, a ToS and credential-handling red flag |
| Broker boundary (`brokers/base.py`) | `BrokerAPI(ABC)` with typed dataclasses (`UserProfile`, `Funds`, `Holding`, `Position`, `Quote`, `OptionsContract`, `OrderRequest/Response`, `Order`) and abstract `get_login_url/complete_login/get_holdings/get_positions/get_quote…`. Implementations: Zerodha, Fyers, Upstox, Dhan, AngelOne, Groww, plus a `mock` |
| Data / backtest | `market/` has an `nse_scraper`, `yfinance_provider`, and `source_tracker.py`, which **records which source served each request and emits fallback warnings** (good idea, but stored in a process-global dict). `engine/backtest.py` enters and exits at **the same bar's close as the signal** (`price = df.iloc[i]["close"]`, signal from `signals.iloc[i]`), giving same-bar look-ahead in the simple engine. Indicator code correctly uses `.shift(1)` for breakouts. Silent `except Exception: hold_days = 0` |
| Scope conflict | Live order execution (Zerodha/Fyers…), NFO options, Greeks, and pairs trading are **explicitly out of scope** for us |
| **Decision** | **Ideas adopted:** (1) deterministic analyst phase, then a structured disagreement summary (agreement %, named conflicts), then LLM *narration* only, which maps directly onto our Phase 8 if the synthesis step is limited to explaining engine numbers and the LLM confidence is removed; (2) bull/bear debate as an optional, local-LLM "steelman both sides" explainer with no numeric output; (3) provider abstraction with an Ollama / OpenAI-compatible local base URL as default; (4) per-request source tracking, made persistent and per-record; (5) a broker-style **read-only holdings import interface** (holdings and positions only, never orders). **Code reused:** none (MIT permits it, but the quality issues above argue against it). **Rejected:** live trading, derivatives, the unofficial session-token provider, LLM confidence scores, and same-bar fills |

### 6.6 On the yfinance `.NS` / `.BO` suggestion
- **Terms:** yfinance's own README says it is not affiliated with Yahoo, is "intended for research and educational purposes", and that "the Yahoo! finance API is intended for **personal use only**". Users are told to read Yahoo's terms. A personal, local, non-redistributed tool may be acceptable. A product that redistributes or sells derived data is not. I did not do a legal review.
- **Fragility:**
  - Unofficial endpoints.
  - Dependence on `curl_cffi` browser impersonation.
  - 429/500 errors (issue 2026-03-17).
  - Documented wrong Indian corporate-action adjustment (RAYMOND.NS, issue 2025-05-28).
- **Authority:** Yahoo is **not authoritative** for our scope.
  - Mutual fund NAVs: AMFI (`NAVAll.txt` and NAV history).
  - G-sec, T-bill, and SDL prices and yields: RBI, CCIL, and FBIL.
  - Fixed deposits: the issuing bank's published rate card.
  - Yahoo has no Indian MF NAV or bond-yield coverage that we should rely on.
- **Verdict:** optional, clearly labelled, *non-authoritative* source for equity index context only (e.g. benchmark display), cached with provenance. Never used for MF NAVs, fixed-income pricing, or any number shown as fact.
