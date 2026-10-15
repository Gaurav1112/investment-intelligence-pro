# Hidden-Gem Repository Scout (Agent A2)

Observation date: **2026-10-15**. Every star count below is "stars@2026-10-15" and was collected through the authenticated `gh` CLI (`gh api repos/O/R`). No repository was cloned. All source observations come from reading files through `gh api repos/O/R/contents/PATH`. Fetched content was treated as untrusted data. Anything not checked directly is marked **NOT VERIFIED**.

Scope excludes the well-known projects that Agent A is ranking (Ghostfolio, Portfolio Performance, Wealthfolio, QuantLib, rateslib, quantstats, empyrical, riskfolio, PyPortfolioOpt, skfolio, OpenBB, yfinance, vectorbt, backtrader, statsforecast, sktime, darts, lightweight-charts, casparser, mfapi.in, ai-hedge-fund, daily_stock_analysis, bulbea).

---

## 1. Discovery methodology

| # | Strategy | Queries / calls used | Yield |
|---|----------|----------------------|-------|
| S1 | `gh search repos` with India terms, sorted by **updated** | "AMFI NAV", "NAVAll", "mfapi", "xirr india", "CAS parser CAMS", "T-bill yield", "G-sec yield", "SEBI riskometer", "debt fund YTM", "fixed deposit calculator india", "capital gains india tax", "rolling returns mutual fund", "portfolio overlap mutual fund", "AMC portfolio disclosure", "RBI DBIE", "MOSPI", "FBIL", "nse holidays", "indian number format lakh crore" | High noise: mostly 0-star student ETL projects. Found: FBIL-based `india-merchant-data-api`, `rbi-forex-reference-rates`, the NSE holiday datasets |
| S2 | `gh search repos` sorted by **stars** | "AMFI mutual fund", "xirr", "CAS parser", "CAMS KFintech", "casparser", "mftool", "indian mutual fund", "riskometer", "india income tax calculator", "fixed deposit calculator", "mutual fund overlap", "NSE holidays", "lakh crore format", "nelson siegel", "bond pricing", "day count convention", "treasury bill", "diebold mariano test", "stationary bootstrap", "block bootstrap time series", "purged cross validation", "combinatorial purged", "conformal prediction time series", "properscoring", "jugaad-data" | Most of the shortlist |
| S3 | GitHub **topics** via `gh api search/repositories?q=topic:...` | `topic:mutual-funds+topic:india`, `topic:amfi`, `topic:xirr`, `topic:fixed-income`, `topic:yield-curve`, `topic:bond-pricing`, `topic:proper-scoring-rules`, `topic:conformal-prediction+topic:time-series`, `topic:forecast-evaluation`, `topic:indian-stock-market+topic:python`, `topic:isin`, `topic:india+topic:finance` | Found `nci/scores`, `scoringutils`, `tsbootstrap`, `india-isin-data`, `fund-disclosures`, `openreversefeed`, `Mutual_Fund_Data` |
| S4 | **Adjacency / dependents** (reading the READMEs and imports of found repos) | `bond_pricing` README points to `isda_daycounters`. `casparser-js` points to `casparser-isin`. `folioman` imports `captnemo` (india-isin-data) and `casparser_fmv`. `tarioch/xirr` cites `java-xirr`/`nodejs-xirr` | `isda_daycounters`, `casparser-isin`, `RayDeCampo/nodejs-xirr` |
| S5 | **Narrow-but-critical** areas (forecast evaluation, bootstrap, CV, conformal) | Same as the S2 and S3 rows above | `scores`, `scoringrules`, `properscoring`, `feval`, `purged-cross-validation`, `tsbootstrap`, conformal repos |

**Limitations (stated honestly):**
- The GitHub search API rate limit (30/min) was hit once. All affected queries were re-run with pacing.
- `gh search code` was **not** used, to stay inside the search budget. This is a coverage gap for repos that are only findable by file content, such as `NAVAll.txt` parsers buried in larger apps.
- Many multi-word India queries returned **zero** results. Examples: "SEBI riskometer" as repos, "debt fund YTM", "rolling returns mutual fund", "RBI DBIE". India-specific fixed-income open source is genuinely sparse.
- PyPI/npm registries were not searched directly. Small packages were reached only through GitHub.
- **Premium UI / accessible financial components were barely covered.** Only one candidate was found (`maharshi-me/investments`). Treat UI references as **NOT VERIFIED / gap**.
- Facts per repo:
  - metadata (`stargazers_count`, `pushed_at`, `license.spdx_id`, `archived`, `open_issues_count`);
  - the full git tree, used to count `.github/workflows/*` and test files;
  - the latest release and tag count;
  - the date of the last commit on the default branch.

---

## 2. Scoring rubric

Each criterion is scored from 0 to 5. The gem score is the sum, out of 30.

| Code | Criterion | 5 means | 0 means |
|------|-----------|---------|---------|
| C | Correctness evidence | tests plus fixtures plus cross-checks against an external oracle | no tests, bugs observed |
| Cl | Code clarity | small, typed, documented, explicit errors | opaque or generated |
| I | India/domain specificity | encodes Indian market conventions or sources | generic |
| M | Maintenance | active, CI, releases. A small, finished, correct repo can still score 2–3 | abandoned and buggy |
| L | License compatibility | MIT/Apache/BSD/Unlicense/CC0/public domain | no license, AGPL, or non-commercial |
| U | Usefulness to our layer | directly fills a planned module | tangential |

**Verdicts:**
- **ADOPT-IDEA**: copy the design or pattern, not the code.
- **ELIGIBLE-CODE-REUSE**: the license and quality allow vendoring or depending on it, after review.
- **TEST-ORACLE**: use it to generate or cross-check expected values or fixtures in our test suite. It is not shipped.
- **REJECT**: not worth adopting.

---

## 3. Evaluated gems (35 repos)

Legend: wf is the number of GitHub workflow files. "tests" is the count of test-like files in the tree; doctests are not counted.

| # | Repo | Stars@2026-10-15 | Last push / last commit | License | Tests / CI | Layer | C/Cl/I/M/L/U | Gem /30 | Verdict | Found by |
|---|------|-----|------|------|------|------|------|----|------|----|
| 1 | https://github.com/codereverser/casparser-isin | 11 | 2026-10-07 / 2026-06-29; rel v2026.6.9 | MIT | 15 tests, 3 wf (pytest, CodeQL, publish) | Instrument master (ISIN↔AMFI code↔RTA code, SEBI category) | 4/4/5/4/5/5 | **27** | ELIGIBLE-CODE-REUSE | S4 |
| 2 | https://github.com/captn3m0/india-isin-data | 51 | 2026-10-14; rel v2026.10.14 (100+ tags) | CC0-1.0 | 0 tests; daily update wf with sentinel-ISIN gate | Instrument master (bond coupon, maturity, status) | 3/4/5/5/5/4 | **26** | ELIGIBLE-CODE-REUSE (data) + fixture source | S3 |
| 3 | https://github.com/nci/scores | 236 | 2026-10-06; rel 2.7.0 (2026-09-05) | Apache-2.0 | 66 tests, 2 wf | Forecast validation (CRPS, PIT, quantile loss, DM-HLN, block bootstrap) | 5/5/0/5/5/5 | **25** | ELIGIBLE-CODE-REUSE + TEST-ORACLE | S3 |
| 4 | https://github.com/ShantanuAnant/mutualfund | 3 | 2026-06-14 | MIT | 3 tests + `navall_sample.txt` fixture, CI | AMFI NAVAll parser | 3/5/5/3/5/4 | **25** | ELIGIBLE-CODE-REUSE (after float→Decimal) | S1/S2 |
| 5 | https://github.com/codereverser/folioman | 64 | 2026-10-15 / 2026-08-30 | **AGPL-3.0** ⚠ | 133 tests, CI | Portfolio ledger, reconciliation, India tax (112A), XIRR, AMFI bulk feed | 4/5/5/5/1/5 | 25 | **ADOPT-IDEA only** (AGPL) | S2 |
| 6 | https://github.com/eslazarev/purged-cross-validation | 57 | 2026-10-01; rel v0.1.10 (23 tags) | MIT | 57 tests, 2 wf | Forecast validation (purged k-fold, CPCV, embargo, PBO) | 5/5/0/5/5/4 | **24** | ELIGIBLE-CODE-REUSE | S2 |
| 7 | https://github.com/the-solipsist/rbi-forex-reference-rates | 0 | 2026-10-14 | Public-domain statement (NOASSERTION in API) | 0 tests; daily update wf + Zenodo | Reference data: RBI/FBIL FX, **SGB tranches and redemption prices**, IBJA gold | 3/4/5/5/4/3 | 24 | TEST-ORACLE / fixture source | S1 |
| 8 | https://github.com/MohitGoyal09/india-merchant-data-api | 0 | 2026-10-02 | **none** ⚠ | 117 test-like files, CI, recorded fixtures with sha256 meta | Ingestion: FBIL FX/MIBOR, **RBI holiday matrix**, provenance | 4/5/5/3/0/5 | 22 | **ADOPT-IDEA only** (no license) | S1 |
| 9 | https://github.com/frazane/scoringrules | 105 | 2026-07-25; rel 0.11.0 | Apache-2.0 | 17 tests, 3 wf | Forecast validation (closed-form CRPS, fair ensemble CRPS, interval and quantile scores) | 5/4/0/4/5/5 | 23 | TEST-ORACLE (+ reuse eligible) | S2 |
| 10 | https://github.com/AngelOneWealth/openreversefeed | 16 | 2026-09-07 | Apache-2.0 | 27 tests, CI | Registrar (CAMS/KFintech reverse-feed) ingestion, FIFO, dedup, pair-removal | 3/4/5/3/5/3 | 23 | ADOPT-IDEA | S2/S3 |
| 11 | https://github.com/subscriptionmanager26-png/fund-disclosures | 6 | 2026-10-13 / 2026-10-11 | MIT (underlying AMC data: rights NOT VERIFIED) | 12 tests, 1 wf, QC scripts vs a third-party source | AMC monthly portfolio disclosure parsing | 3/3/5/4/4/4 | 23 | ADOPT-IDEA + fixture source | S3 |
| 12 | https://github.com/chikatina/casparser-js | 0 | 2026-10-14 / 2026-09-09; rel v1.1.0 | MIT | 16 tests, CI + CodeQL | CAS parsing in JS, BigInt Decimal, capital gains | 3/5/5/3/5/2 | 23 | ADOPT-IDEA (gains code has a bug, see §5) | S2 |
| 13 | https://github.com/astrogilda/tsbootstrap | 95 | 2026-10-14; rel v0.7.3 | MIT | 47 tests, 9 wf | Risk/scenario (stationary, circular, MBB, tapered, sieve bootstrap) | 4/4/0/5/5/4 | 22 | ELIGIBLE-CODE-REUSE (dependency footprint NOT VERIFIED) | S3 |
| 14 | https://github.com/Anexen/pyxirr | 223 | 2025-11-03; rel v0.10.8 | Unlicense | 72 test files, **66 sample CSVs**, 2 wf | XIRR/XNPV oracle | 5/3/1/3/5/5 | 22 | TEST-ORACLE | S2/S3 |
| 15 | https://github.com/jugaad-py/jugaad-data | 586 | 2026-10-06 | "YOLO" public-domain licence (non-OSI) ⚠ | 11 tests, 3 wf | AMFI NAV-history parser, NSE/BSE, RBI rates | 3/3/5/4/3/4 | 22 | ADOPT-IDEA (RBI scraper bug, see §5) | S2 |
| 16 | https://github.com/epiforecasts/scoringutils | 64 | 2026-09-27; rel v2.2.0 | MIT (R) | 54 tests, 6 wf | Forecast validation (R) | 5/4/0/5/5/3 | 22 | TEST-ORACLE (R cross-check) | S3 |
| 17 | https://github.com/luphord/nelson_siegel_svensson | 129 | 2023-11-02 / 2022-11-13 | MIT | 6 tests, CI | Yield curve (NS/NSS fit) | 3/5/2/2/5/4 | 21 | ELIGIBLE-CODE-REUSE (add tau bounds) | S2/S3 |
| 18 | https://github.com/jrvarma/bond_pricing | 37 | 2026-10-03 | **GPL-3.0** ⚠ | doctests only, no CI | Bond price/YTM/duration, zero-curve pricing | 4/4/3/4/1/4 | 20 | TEST-ORACLE (do not vendor) | S2 |
| 19 | https://github.com/InertExpert2911/Mutual_Fund_Data | 33 | 2026-10-06 | MIT | no code in repo (Kaggle notebook) | Bulk NAV history + AUM snapshot | 2/2/5/4/4/3 | 20 | TEST-ORACLE (cross-check only) | S3 |
| 20 | https://github.com/tarioch/xirr | 16 | 2026-10-12; rel v0.1.8 (2022) | MIT | 3 tests, 3 wf | XIRR | 3/4/0/4/5/3 | 19 | ADOPT-IDEA | S3 |
| 21 | https://github.com/GauravSh-7/nse-trading-holidays-2018-2026 | 0 | 2026-08-26 | MIT | data only (parquet, 169 rows) | Calendar (NSE F&O) | 2/3/5/2/5/2 | 19 | TEST-ORACLE (equity calendar only) | S1 |
| 22 | https://github.com/RayDeCampo/nodejs-xirr | 32 | 2022-12-06 / 2022-05-29 | MIT | 1 test file, ~20 named edge cases | XIRR | 4/4/0/1/5/3 | 17 | TEST-ORACLE (edge-case list) + ADOPT-IDEA | S4 |
| 23 | https://github.com/open-source-modelling/stationary_bootstrap_python | 4 | 2026-10-05, **archived** | MIT | 1 test | Stationary bootstrap (tiny) | 3/5/0/1/5/3 | 17 | ADOPT-IDEA | S2 |
| 24 | https://github.com/maharshi-me/investments | 9 | 2026-03-18; rel v1.1.0 | MIT | 0 tests, no CI | UI reference (CAMS/KFin tracker, tax-analysis page, shadcn) | 1/3/4/2/5/3 | 18 | ADOPT-IDEA (UI layout only; NOT VERIFIED in depth) | S2 |
| 25 | https://github.com/properscoring/properscoring | 188 | 2023-03-09, **archived** | Apache-2.0 | 3 tests | CRPS (Gaussian closed form vs quadrature) | 4/4/0/0/5/3 | 16 | TEST-ORACLE | S2 |
| 26 | https://github.com/simicd/smith-wilson-py | 23 | 2024-09-03 / 2022-01-30 | MIT | 2 tests, CI | Yield-curve extrapolation (EIOPA) | 3/4/0/2/5/2 | 16 | ADOPT-IDEA (low priority) | S3 |
| 27 | https://github.com/ogrnz/feval | 8 | 2023-11-07 | MIT | 3 tests, CI | Forecast comparison (multivariate DM, Giacomini-White, MCS) | 3/3/0/1/5/3 | 15 | ADOPT-IDEA | S3 |
| 28 | https://github.com/webcarrot/xirr | 9 | 2024-07-01; rel v3.0.1 | MIT | 0 tests | XIRR (LibreOffice algorithm port) | 3/4/0/1/5/2 | 15 | ADOPT-IDEA | S3 |
| 29 | https://github.com/aangelopoulos/conformal-time-series | 146 | 2023-11-30 | MIT | notebooks; no CI; unit tests NOT VERIFIED | Conformal intervals for time series (ACI, quantile tracking) | 3/3/0/1/5/3 | 15 | ADOPT-IDEA | S3 |
| 30 | https://github.com/miradulo/isda_daycounters | 27 | 2020-08-25 / 2018-10-03 | **none** ⚠ | 1 test file | Day count (30/360, ACT/ACT ISDA, ACT/365) | 4/5/0/1/0/3 | 13 | TEST-ORACLE (reference only, no copying) | S4 |
| 31 | https://github.com/mzaffran/AdaptiveConformalPredictionsTimeSeries | 73 | 2022-04-07 | MIT | none | Conformal (AgACI) | 3/2/0/0/5/3 | 13 | ADOPT-IDEA (paper code) | S3 |
| 32 | https://github.com/johntwk/Diebold-Mariano-Test | 128 | 2017-12-07 | MIT | 1 file | DM test | 2/2/0/0/5/2 | 11 | **REJECT** | S2 |
| 33 | https://github.com/iam-ansuman/bharatutils | 0 | 2026-06-11 | MIT | 0 tests | lakh/crore formatting | 1/3/5/2/5/1 | 17 | **REJECT** | S1 |
| 34 | https://github.com/shreysrins/bond-calculator | 30 | 2022-02-17 | MIT | 0 tests | Bond YTM/duration CLI | 1/2/0/0/5/1 | 9 | **REJECT** | S3 |
| 35 | https://github.com/as1605/mf-screener-ai | 14 | 2026-10-13 | MIT | 0 tests, 2 wf | MF screener | 1/2/4/4/5/1 | 17 | **REJECT** | S2 |
| 36 | https://github.com/aswinv90/indian-market-historical-data | 6 | 2026-10-14 | **Non-commercial** ⚠ | 9 wf, 0 tests | NSE/BSE dataset | — | — | **REJECT** (license) | S3 |

These were also looked at only as metadata or trees, and were not scored: `svoorakk/node-amfinav` (8★, last commit 2018, Apache-2.0), `mayurbhangale/amfibious` (8★, last commit 2019), `srijanshetty/mfparser` (7★, custom licence), `utkarshohm/mf-nav-data` (32★, frozen 2017 dump), `SunilVeeravalli/XIRR_in_Python` (15★, 2020, no tests), `open-source-modelling/Nelson_Siegel_Svensson_python` (19★, 1 test, MIT). All are stale or superseded by the entries above.

---

## 4. Detailed notes on the top 10

### 4.1 `codereverser/casparser-isin`: the ISIN ↔ AMFI-code master we need (27/30)
- **What:** a SQLite database (`casparser_isin/isin.db`) plus a lookup API that maps RTA scheme names and codes (CAMS, KFintech/Karvy, Franklin) to ISIN, AMFI code, scheme type and **SEBI category**. The builder lives in `tools/cptools/fetchers/{amfi,bse,nse,isin}.py` and is refreshed through tagged releases (`v2026.6.9`).
- **Correctness evidence:**
  - `tests/tools/test_invariants.py` locks down an **append-only contract**: "Every baseline row whose type is in scope MUST appear in the output." It runs end to end with stubbed fetchers.
  - It ships `tools/files/AMFI_NAV_31Jan2018.txt`, the grandfathering FMV date for 112A.
- **Source observations (`mf_isin.py`):**
  - Lookup is **ISIN-first**. The docstring cites an audit showing ISIN present on 100% of CAS holdings.
  - It falls back to RTA code, then to rapidfuzz `token_sort_ratio` with `min_score=60`.
  - All SQL is parameter-bound, with explicit "never string-interpolated" comments.
  - HDFC RTA codes are prefix-matched with `LIKE` because their suffix encodes plan/option.
  - It retries once with the last character trimmed, for "off-by-one suffixes seen in older CAMS statements".
- **Caveats:**
  - A fuzzy match at score 60 is too permissive for a provenance-first app. We should treat any non-ISIN match as *low-confidence* and surface it in the UI.
  - The off-by-one retry can silently map to a sibling plan.
- **Use:** depend on or vendor the DB, under MIT. Keep the append-only invariant test pattern for our own instrument master.

### 4.2 `captn3m0/india-isin-data`: CC0 NSDL ISIN dump with bond attributes (26/30)
- **What:** a daily (Mon–Fri, 18:00 IST) scrape of NSDL's ISIN search into CSV plus SQLite. The columns include `interest_rate`, `maturity_date`, `fisn`, `cfi`, `status`, `issuer_name`, `security_type_name`, `last_updated` and `source`. The data is citable through Zenodo DOI 10.5281/zenodo.6508187.
- **Correctness evidence:**
  - There are no unit tests. However, `src/main.py` defines **`SENTINEL_ISINS`**, a set of long-stable NIFTY large caps such as Reliance `INE002A01018` and HDFC Bank `INE040A01034`, whose *presence* gates the release ("If one goes missing, the load dropped rows and the release should be blocked").
  - It uses an `ON CONFLICT(isin) DO UPDATE` upsert.
- **Domain caveat (from its own README):**
  - NSDL allots ISINs for all securities **except Government Securities**, so G-secs, SDLs and T-bills will be missing or incomplete. We still need an RBI/CCIL source for sovereign instruments.
  - `INA`/`INB` prefixes are not tracked.
- **Use:** use it for corporate-bond and NCD static data (coupon, maturity) and as an ISIN validator fixture. CC0 means there is no attribution burden, but we cite it anyway for provenance.

### 4.3 `nci/scores`: the forecast-verification library to copy from (25/30)
- **What:** an Australian Bureau of Meteorology verification library with these modules:
  - `probability/crps_impl.py`
  - `probability/pit_impl.py`
  - `continuous/quantile_loss_impl.py`
  - `continuous/interval_impl.py`
  - `processing/block_bootstrap_impl.py`
  - `stats/statistical_tests/diebold_mariano_impl.py`
- **Correctness observations (DM test):**
  - Both the **HLN** (Harvey-Leybourne-Newbold 1997) and **HG** (Hering-Genton 2011) variance estimators are implemented.
  - `_dm_v_hat` returns **NaN when V̂ ≤ 0**, instead of producing a complex number. This is exactly the failure `johntwk/Diebold-Mariano-Test` has (§5).
  - It validates `0 < h < len(diffs)` after removing NaNs, warns on NaNs, and returns NaN when all differences are zero.
  - The HLN small-sample correction `(n+1-2h+h(h-1)/n)/n` matches the paper's eq. 9.
- **Caveat:** it is xarray-centric, which is a heavy dependency. Port the pure-numpy kernels, or use it only in a dev/test dependency group.
- **Use:** the TEST-ORACLE for our CRPS, pinball and PIT code and our DM test. Apache-2.0 also allows reuse.

### 4.4 `ShantanuAnant/mutualfund`: the cleanest NAVAll.txt parser found (25/30)
- **What:** a tiny (21 KB) typed client. `parser.py` does no I/O and is tested against `tests/fixtures/navall_sample.txt`.
- **Correctness observations:**
  - It skips the `Scheme Code;…` header and recognises category headers with `^(Open Ended|Close Ended|Interval)`.
  - It splits `"Open Ended Schemes(Equity Scheme - Large Cap Fund)"` into (structure, type, category), including the "Other Scheme" ETF/Index/FoF subtypes.
  - It treats any other non-data line as the AMC name, maps `-` ISINs to empty, and returns `None` for "N.A." NAVs and dates.
- **Bugs and risks:**
  1. **The NAV is parsed as `float`.** This must become `Decimal(str)` for our money engine.
  2. Any *malformed* data row (for example, fewer than 6 fields) falls into the `else` branch and silently becomes the current **AMC name**. That corrupts the AMC attribution for every following row. A strict parser should raise on a line that contains `;` but fails validation.
  3. There are no counters for skipped rows, so ingestion provenance cannot report drops.
- **Use:** vendor it (MIT) after making those three fixes. Pair it with jugaad-data's NAV-*history* parser (§4.10).

### 4.5 `codereverser/folioman` (AGPL): best reference design for ledger, reconciliation and India tax (ADOPT-IDEA only)
- **License flag:** **AGPL-3.0**. Do not copy code. Study the designs only.
- **Ideas worth adopting:**
  - **`SecurityIntegrityStatus`**, kept per investor, security and folio. It holds:
    - `units_from_transactions` vs `units_from_holdings`, as `DecimalField(24,8)`;
    - an `issues` list;
    - `ledger_through` vs `snapshot_as_of`;
    - a **`tax_safe`** flag that keeps unreconciled securities out of tax exports.
    This is exactly the "provenance-first" trust signal we want.
  - `tax/india.py`:
    - grandfathering uses `acquired_on <= date(2018,1,31)`, which is correct per s.112A;
    - the equity LTCG test uses **calendar months**, not a 365-day proxy (`_twelve_months_after` clamps the day);
    - it splits the 112A transfer regime at `date(2024,7,23)`;
    - it flags `grandfathering_unavailable` when FMV is missing.
  - `price_feeds/amfi_bulk.py`:
    - `Decimal` NAV;
    - the `portal.amfiindia.com` host, because the www host is "frequently unreachable";
    - retries only on 429/5xx;
    - keys each point by AMFI code **and** each ISIN.
    - Minor risk: when an ISIN is reused across codes, the last row silently wins.
  - `xirr.py`:
    - Newton, then a bracketed bisection in [-0.999999, 100];
    - returns `None` when there is no sign change, with no exception.
    - Weakness: the absolute `npv < 1e-7` tolerance on rupee amounts means convergence effectively relies on the step tolerance.

### 4.6 `eslazarev/purged-cross-validation`: permissive mlfinlab replacement (24/30)
- **What:** sklearn-compatible purged k-fold, CPCV, walk-forward, embargo (by duration, observation count, or fraction, mutually exclusive) and PBO. It has 57 test files and 23 tags.
- **Correctness observations (`_purge.py`):**
  - Purging uses **half-open intervals** `[pred - h, eval + h)`.
  - Test intervals are **merged before filtering**, so disjoint test blocks purge only their local zone and not the convex hull. This is a subtle point many implementations get wrong.
  - A negative or NaT `purge_horizon` raises an error.
  - The doctest shows the expected purge result.
  - `_embargo.py` rejects booleans passed as fractions and non-finite values.
- **Use:** MIT. Adopt it as the walk-forward and backtest validation dependency for forecast validation.

### 4.7 `the-solipsist/rbi-forex-reference-rates`: gap-free RBI/FBIL FX plus SGB data (24/30)
- **What:** RBI reference rates from 1998 to 2018, then FBIL from 2018 to the present, in long, wide and Parquet formats. Coverage notes are per currency (for example, AED and IDR start on 2026-01-22). It is updated daily at 06:00 IST and archived on Zenodo.
- **Bonus:** it includes `data/sgb_tranches.csv` and `sgb_redemption.csv`. Sovereign Gold Bonds are a sovereign instrument that is relevant to the G-sec layer. The derivation script is `scripts/derive_sgb_redemption.py`, whose logic is **NOT VERIFIED**.
- **Licence:** a public-domain "compilation of facts" statement. The GitHub API reports NOASSERTION.
- **Use:** fixture source for FX conversion tests and SGB redemption-price cross-checks.

### 4.8 `MohitGoyal09/india-merchant-data-api`: gold-standard ingestion provenance (ADOPT-IDEA; NO LICENSE)
- **License flag:** **no licence file**, so all rights are reserved. Read it, don't copy.
- **Ideas worth adopting:**
  - Every recorded fixture has a sidecar `*.meta.json` with `url`, `params`, `status_code`, `content_type`, `fetched_at` (UTC), **`sha256`** and `bytes`. Example: `tests/fixtures/fbil/fx_2021.meta.json`. This is the exact provenance envelope our ingestion layer should store.
  - FBIL adapter (`sources/fbil/common.py`):
    - base `https://www.fbil.org.in/wasdm`;
    - the comment "FBIL answers HTTP 500 to non-ISO dates";
    - 366-day request chunking;
    - `Decimal` parsing;
    - `displayTime` made IST-aware;
    - strict `ParseError` on non-list or non-dict rows or missing keys.
    - It could be extended to FBIL T-bill and G-sec valuation curves. Whether FBIL exposes those through the same API is **NOT VERIFIED**.
  - RBI holiday-matrix adapter (`sources/rbi/holidays.py`):
    - It parses both page layouts and classifies NI-Act holidays vs closing-of-accounts days.
    - It **fails loudly on unknown markers**.
    - It uses the hidden legend text as the authority, because glyphs change by year. This is the right source for a **G-sec/T-bill settlement calendar** (use the Mumbai office).
- **Domain caveat:** it deliberately treats RTGS-only holidays as non-holidays ("banks are open"). For **G-sec settlement through RBI/CCIL DvP, an RTGS closure matters**, so our calendar must keep RTGS-closed days as non-settlement days.

### 4.9 `frazane/scoringrules`: closed-form CRPS oracle (23/30)
- **What:** CRPS for parametric families (closed forms in `core/crps/_closed.py`), ensemble CRPS with several estimators including the *fair* one, documented in `docs/crps_estimators.md`, plus interval, quantile, energy and variogram scores.
- **Correctness evidence:** `tests/test_crps.py` asserts against literal reference values such as `0.4923673`, `0.6126602` and `0.883206751`. The provenance of those values (likely R `scoringRules`) is **NOT VERIFIED**. The tests also include a real-data file (`precip_Niamey_2016.csv`).
- **Use:** TEST-ORACLE for our CRPS and quantile score. Apache-2.0 allows reuse. The docs are the best explanation we found of when to use the fair vs the standard ensemble CRPS.

### 4.10 `jugaad-py/jugaad-data`: AMFI NAV-history parser (keep values as strings) (22/30)
- **License flag:** "YOLO LICENSE" ("jugaad-data is in public domain. Do whatever you want"). It is permissive but non-OSI, so get legal comfort before vendoring.
- **Good:**
  - `amfi/__init__.py:parse_nav_history` strips the BOM.
  - It recognises section headers with `^(Open Ended|Close Ended|Interval Fund)\s+Schemes?\s*\(...\)`, which tolerates the "Scheme/Schemes" inconsistency.
  - It resets `amc` on each section.
  - It **keeps every value as the original string**, which is ideal for `Decimal`.
  - It caches immutable past-date downloads.
- **Questionable:**
  - Its docstring describes an 8-column history layout: `Scheme Code;NAV Name;Plan;Option;ISIN…;ISIN…;NAV;Date`. Whether the live AMFI endpoint returns this column order is **NOT VERIFIED**. Our parser should validate the header row and refuse to run on an unknown layout.
  - Rows with fewer than 8 fields are dropped silently.
- **Bug (RBI scraper, `rbi/__init__.py`):**
  - `rate_mappings` maps **`'Standing Deposit Facility Rate'` → `'Savings Deposit Rate'`**, with the comment "Map to expected test key". The SDF rate is therefore published under the wrong name.
  - The 91-day T-bill rate is pulled with a loose regex over page text.
  - Do **not** use it for policy-rate or T-bill inputs.
- **Holidays:** `holidays.py` is a static BSE (XBOM-derived) equity list from 1997 to 2026. It is not a bond-market calendar.

---

## 5. Rejected despite looking good

| Repo | Why it looked good | Why rejected (concrete) |
|------|--------------------|--------------------------|
| `johntwk/Diebold-Mariano-Test` (128★) | Most-starred Python DM test; implements the HLN correction | (1) Numeric validation runs a regex on `str(abs(x))` (`^\d+?\.\d+?$` or `isdigit`), so values printed in scientific notation, such as `1e-05`, are **rejected as non-numeric**. (2) Errors are raised as `SyntaxError`. (3) When `V_d` is negative (possible for h>1), `V_d**(-0.5)` yields a **complex number** in Python 3 instead of NaN. (4) No activity since 2017. Use `nci/scores` instead (§4.3). |
| `chikatina/casparser-js` (0★, but very polished) | BigInt `Decimal` with Python semantics, 16 tests, CodeQL, gains and 112A reports | It is kept as ADOPT-IDEA, but its gains code must **not** be used as an oracle. (1) In `src/analysis/gains.js`, `coa` grandfathers when `purchase_date.lt(2018-01-31)`, while `taxable112a` uses `lte`. A lot bought **on** 31-Jan-2018 is therefore treated inconsistently; s.112A says "on or before". (2) `coa` applies CII indexation to **every** DEBT lot, and `gain_type` uses a flat 3-year debt threshold. This ignores s.50AA (debt MF units acquired on or after 1-Apr-2023 are always short-term) and the post-23-Jul-2024 no-indexation regime. This logic may be inherited from Python casparser (NOT VERIFIED). |
| `AngelOneWealth/openreversefeed` (Apache-2.0, 27 tests) | Only open-source parser for CAMS/KFintech *reverse feeds*; dedup, pair-removal, negative-fix pipeline | Kept as ADOPT-IDEA, not code reuse. (1) `core/fifo.py`'s `compute_fifo` **silently ignores oversells**: the `while remaining > 0 and lots` loop exits with units left over and raises no error. (2) It silently ignores unknown `action` values. (3) `Decimal(txn["units"])` built from a float input carries binary error. (4) `parse_utils.to_number` returns `float`. (5) `normalize_quoted_csv` reads without `utf-8-sig` while `peek_feed_headers` uses it, an inconsistent BOM handling. |
| `tarioch/xirr` (MIT, CI) | Clean, typed, cites java-xirr edge cases | Kept as ADOPT-IDEA only. (1) It returns `+inf` or `-inf` for all-positive or all-negative flows instead of "undefined". (2) Newton starts from 0, and a Brent fallback runs over [-0.999999999999999, 1e20]. `brentq` raises `ValueError` when there is no sign change, and `xirr()` does not catch it (only `cleanXirr` does). (3) It uses floats and 365-day years. Newton can also converge to one of several roots without any warning. |
| `iam-ansuman/bharatutils` (lakh/crore) | Exactly the Indian formatting utility we need | (1) `indian_commas` truncates the fraction through `int(number)`, so `1234.56` becomes `"1,234"`. (2) At the boundary, `format_inr(9_999_999.6)` returns `"₹100.0 L"` instead of crores, because `to_lakh` rounds after the threshold test. (3) Floats throughout. (4) No tests. Writing a 30-line Decimal formatter ourselves is safer. |
| `jrvarma/bond_pricing` (IIMA author) | Credible author; bond price, YTM, duration and zero-curve pricing with doctests; recently updated | **GPL-3.0**, which is incompatible with vendoring into a possibly closed product. It is also float/numpy only. Keep it as an external TEST-ORACLE run from a dev-only environment. (`bond_coupon_periods` uses `daycounter.year_fraction × freq` for the fractional period, which under 30/360 semi-annual gives days/180, consistent with the Indian G-sec convention; this was confirmed only by reading the code.) |
| `miradulo/isda_daycounters` | Tiny, correct-looking ISDA 2006 implementations. The 30/360 rule `d2 = min(d1, day2) if d1 == 30` is correct, and ACT/ACT ISDA splits by calendar year correctly | **No licence**, so all rights are reserved. Use it only to read as a reference for our own tests. |
| `aswinv90/indian-market-historical-data` | Large daily NSE/BSE dataset, 9 workflows | **Non-commercial research licence**. |
| `as1605/mf-screener-ai` | Active Indian MF screener with an XIRR compile step | The algorithms are per-LLM generated files (`Mid Cap_Claude.py`, `_GPT.py`, `_Gemini.py`, `_Grok.py`), with no tests. That contradicts our deterministic, provenance-first stance. |
| `shreysrins/bond-calculator` (30★) | Price, YTM, duration and convexity | Interactive `input()` CLI, whole-year maturities only, no settlement date or accrued interest, float Newton from 5%, no tests. |
| `open-source-modelling/stationary_bootstrap_python` | A correct Politis–Romano implementation, tiny, MIT | Kept as ADOPT-IDEA, not reuse. It draws from the **global `np.random`** with no seed or Generator parameter, which breaks our determinism requirement, and the repo is archived. Re-implement it in about 20 lines with `np.random.Generator`. |
| `GauravSh-7/nse-trading-holidays-2018-2026`, `jugaad-data/holidays.py` | Ready-made Indian holiday lists | These are **equity (NSE F&O / BSE) calendars**. G-sec, T-bill and SDL settlement follows RBI/NI-Act holidays for Mumbai, plus RTGS closures. The "cross-verified against NSE" claim is NOT VERIFIED. Use them for MF/equity NAV-date checks only. |
| `InertExpert2911/Mutual_Fund_Data` | 16k schemes, daily NAV history parquet | Kept only as a cross-check. The processing happens in an external Kaggle notebook that is not in the repo, so the provenance is opaque. |

---

## 6. Recommendations by layer

| Our layer | Use | As |
|-----------|-----|----|
| Instrument master (MF) | casparser-isin DB + append-only invariant test | ELIGIBLE-CODE-REUSE |
| Instrument master (bonds/NCDs) | india-isin-data (CC0) | data; does not cover G-secs |
| AMFI NAV ingest | ShantanuAnant parser (fixed: Decimal, strict rows, drop counters) + jugaad's history parser design + folioman's host and retry notes | reuse + idea |
| Ingestion provenance | MohitGoyal09 `*.meta.json` (sha256, fetched_at, params) envelope; captn3m0 sentinel-row release gate | ADOPT-IDEA |
| Bond calendar | RBI holiday matrix (Mumbai), including RTGS closures; idea from MohitGoyal09 | ADOPT-IDEA |
| XIRR | own Decimal-input solver (Newton → bracketed bisection; return "undefined" with a reason) | oracles: pyxirr `tests/samples/*.csv`; nodejs-xirr edge-case list (issues #1, #2, #7, #14, total loss, rate < -1) |
| Bond math | own implementation | oracles: jrvarma/bond_pricing (GPL, external), isda_daycounters (reference reading) |
| Yield curve | luphord NSS (add tau > 0 bounds and an `opt_res.success` check; replace `assert` validation) | ELIGIBLE-CODE-REUSE |
| Forecast validation | nci/scores (DM-HLN, CRPS, PIT, quantile), scoringrules (closed-form CRPS), purged-cross-validation (walk-forward/CPCV), tsbootstrap (stationary bootstrap) | reuse + TEST-ORACLE; scoringutils (R) for cross-language checks |
| Reconciliation / tax | folioman `SecurityIntegrityStatus` + `tax_safe` gate; calendar-month holding test; `<=` 31-Jan-2018 boundary | ADOPT-IDEA (AGPL) |
| Holdings / overlap | fund-disclosures: the four-way `%NAV` total rule (all / exclude_negatives / exclude_futures / exclude_short_futures, tolerance 0.10), ICICI fraction-of-1 scaling quirk, IRS/options handling per AMC | ADOPT-IDEA + fixtures |

**License flags summary:**
- AGPL-3.0: folioman.
- GPL-3.0: jrvarma/bond_pricing.
- No licence: india-merchant-data-api, isda_daycounters.
- Non-commercial: aswinv90 dataset.
- Non-OSI public-domain text: jugaad-data ("YOLO"), rbi-forex-reference-rates.
- Data-rights caveats: fund-disclosures (redistributed AMC files) and Mutual_Fund_Data (AMFI-derived) carry upstream terms that are NOT VERIFIED.
