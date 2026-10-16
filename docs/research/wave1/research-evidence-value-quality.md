# Research: Evidence for value, quality, low-volatility, size and multi-factor signals in India

Status: research note, wave 1 · Date: 2026-10-15 · Author: research agent "evidence-value-quality"
Companions: `docs/research/return-target-feasibility.md`, `docs/data/source-registry.md`,
`docs/forecasting/validation-methodology.md`, `docs/research/indian-instruments-and-tax.md`

Status labels: **VERIFIED** (read at a primary source or reproduced from a primary data file),
**NOT VERIFIED** (secondary or snippet only, or not checked), **REQUIRES CONFIGURATION** (works only
after the user does something, e.g. manual import), **BLOCKED** (terms or licence forbid it).

---

## 0. Bottom line (read this first)

1. **No stock-level value / quality / low-vol / size signal can be built from free, terms-compliant
   data today.** Each one needs per-stock prices and/or fundamentals. NSE, BSE, niftyindices.com and
   screener.in all forbid copying or automated collection (§5). Verdict: **BLOCKED**. The engine
   must answer "No suitable candidate" for stock-level factor signals.
2. **The long-run academic evidence in India is real but weaker than it looks.** In the IIM-A
   factor library, value (HML) earned **6.49 %/yr geometric** over 1994-01 to 2025-12, with
   **t = 2.31** and a **−58.8 % worst monthly drawdown**. Size (SMB) was **negative (−3.84 %/yr,
   t = −0.85)**. These are gross, long-short paper portfolios. Only momentum clears the t > 3.0
   multiple-testing hurdle: t = 3.03 over the full sample and 3.58 for 2010–2025, but only 1.50 for
   1994–2009 (§2).
   VERIFIED: reproduced from the published CSV.
3. **The investable, live (post-launch, net-of-fee) evidence for factor index products is close to
   zero.** Nifty factor ETFs and index funds, compared with a Nifty 50 index fund on AMFI NAVs,
   show annualised excess returns of **−2.4 % to +2.9 %** with **t-stats of −0.78 to 0.94** (§4).
   Low-vol and multi-factor funds did lower volatility and drawdown. That risk reduction is the
   one effect that held up live.
4. **Index-provider performance tables are mostly back-tests.** Every Nifty factor index has a base
   date years before its launch date. NSE's own 2017 white paper says the results are "Based on
   historical backtesting of over 12 years" (§3). Back-tested periods must not count as evidence.
5. **What the app *can* do deterministically:** (a) compute descriptive risk and return statistics
   for factor **index funds/ETFs** from AMFI NAV (already a LIVE adapter); (b) show the IIM-A factor
   history as a cited, release-pinned **evidence panel**, with a manual import that is REQUIRES
   CONFIGURATION; (c) **abstain** on all factor "buy/sell" and factor-timing signals. Factor tilts
   cannot bridge the gap to a 20–25 %/yr aspiration. The largest live excess return seen here was
   about 3 %/yr, and it was not significant.

---

## 1. Scope and method

- **Factors:** value, quality (profitability, safety), low volatility / low risk, size and
  multi-factor combinations. Momentum appears only as a comparator, because another wave-1 note
  covers it.
- **Evidence tiers, from strongest to weakest:**
  - **(A)** Live, investable, net-of-fee returns from real funds.
  - **(B)** Academic long-short factor returns built from survivorship-corrected data, split by
    period, including a post-publication window.
  - **(C)** Index-provider back-tests.
  - **(D)** Marketing material.

  Only (A) and (B) may support a signal under the project rule (out-of-sample, cost- and tax-aware).
- **Computation done for this note:** Python stdlib floats in a scratch directory, not engine code.
  The input files and their hashes are listed in §2.1 and §4.1, so anyone can recompute every
  number. When engine code is built, it must reimplement these calculations with `Decimal` and
  fixtures.

---

## 2. Academic long-short evidence: IIM Ahmedabad Fama-French + Momentum library (tier B)

### 2.1 Source

- **Library:** Agarwalla, Jacob & Varma, "Fama French and Momentum Factors: Data Library for
  Indian Market", New Series.
  - URL: https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/ (accessed 2026-10-15).
- **Data source.** Quote: "using data from CMIE Prowess". Also quoted: "We are now using CMIE's
  Prowess DX which provides three data releases every year (March, September and December)."
- **Investability filters.** Quote: "The market cap filter excludes all stocks with a market cap
  during the preceding year below 10% of the median market cap. The price filter excludes stocks
  whose median price during the preceding year is less than INR 1.00."
- **Important caveat on value.** Quote: "Some double-sort portfolios (especially the Large-Cap
  Value portfolio) have very few stocks in some months … If the Large-Cap Value portfolio is absent
  after applying this rule, the value factor is computed as the difference between Small Growth and
  Small Value."
  - So in many months **HML is a small-cap-only value spread**.
  - Large-cap value is missing in 154 of 387 monthly rows. It is missing for every month of
    2001–2006, 2009, 2010 and 2014 (counted from the CSV).
- **Vintage instability.** Quote: "The returns and the break-points are recalculated from the
  beginning of the period each time we update the results. The values may undergo a change if CMIE
  revises its database retrospectively." The FAQ also says CMIE "might add a company that was
  omitted in an earlier release, and it might also correct errors". **Consequence:** pin the release
  ID and hash the file. History is not point-in-time.
- **Risk-free rate.** FAQ quote: "The risk-free returns are taken from the annualized yields of new
  issuances of 91-day Treasury Bills, provided by the Reserve Bank of India (RBI)."
- **Terms of use.**
  - Citation required. Quote: "Agarwalla, S. K., Jacob, J. and Varma, J. R. (2013), Four factor
    model in Indian equities market, Working Paper W.P. No. 2013-09-05, Indian Institute of
    Management, Ahmedabad."
  - No licence text was found on the page, and `faculty.iima.ac.in/robots.txt` returns 404.
  - Licence: **NOT VERIFIED**. Treat as personal research use with citation. Do not redistribute
    the files.
- **Files downloaded once (release 2025-12, covering Oct-1993 to Dec-2025).** Kept in scratch only,
  not committed:
  - `2025-12_FourFactors_and_Market_Returns_Monthly_SurvivorshipBiasAdjusted.csv`
    sha256 `c07a12d1c04630c18a7f87a96c91db6a7c4ebfc1e37f888e41fe8469fe234c44`
  - `2025-12_FourFactors_and_Market_Returns_Yearly_SurvivorshipBiasAdjusted.csv`
    sha256 `e5bacdf5a70e9df9ab50ce164144bd87d274ca289ae2157a89bf34a16ccea060`
  - `2025-12_Size_Value_Portfolio_Returns_Monthly_SurvivorshipBiasAdjusted.csv`
    sha256 `8cd62adf3d8a14cd6accbf63e582f5b39dadb12dc94efbba80bed443bee15c46`

### 2.2 Published headline figures (VERIFIED, quoted from the site)

From the data page, "All returns are annualized geometric mean returns", since 1 Jan 1994:

| Factor | Annualised |
|---|---|
| Market premium | 4.93 % |
| SMB (size) | −3.71 % |
| HML (value) | 6.61 % |
| WML (momentum) | 10.65 % |

The drawdown page (https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/drawdown.php)
quotes, verbatim:

- "The Value Factor (HML) provided an annualized return of 6.86% with an annualized volatility of
  15.09%. The worst drawdown was 64.00% and the duration of this drawdown was 7.60 years"
- "The Size Factor (SMB) provided an annualized return of -4.01% with an annualized volatility of
  13.68%. The worst drawdown was 87.00% and the duration of this drawdown was 30.90 years"
- "The Momentum Factor (WML) provided an annualized return of 10.96% with an annualized volatility
  of 17.30%. The worst drawdown was 62.00% and the duration of this drawdown was 5.00 years"
- "The Equity Risk Premium (ERP) provided an annualized return of 5.63% with an annualized
  volatility of 21.44%. The worst drawdown was 77.00% and the duration of this drawdown was 11.30
  years"

The drawdown page covers Oct-1993 to Dec-2025 and uses daily data, so its figures differ slightly
from the data page's 1994-onwards figures. The value drawdown table lists a **−51.9 %** drawdown
from 2018-01-16 to a trough on 2020-03-30, recovered on 2022-01-28 (4.0 years).

### 2.3 Re-computed sub-period statistics (VERIFIED: computed from the monthly CSV above)

Method:

- Monthly factor returns in percent, from the monthly survivorship-adjusted file.
- arith = mean × 12. sd = sample SD × √12. t = mean / (sd_monthly / √n). geo = compounded
  growth^(12/n) − 1.
- Max DD is computed on month-end compounded wealth, so it is shallower than the daily figures
  in §2.2.
- "Post-pub" starts 2013-10, the month after the Sep-2013 working paper.
- "MF" is the market-excess factor.

| Window | Factor | n (months) | arith %/yr | geo %/yr | vol %/yr | t | max DD (monthly) |
|---|---|---|---|---|---|---|---|
| 1994–2025 | SMB | 383 | −2.52 | −3.84 | 16.68 | −0.85 | −86.1 % |
| 1994–2025 | **HML** | 383 | 8.33 | **6.49** | 20.36 | **2.31** | −58.8 % |
| 1994–2025 | WML | 383 | 13.13 | 10.62 | 24.48 | 3.03 | −53.5 % |
| 1994–2025 | MF | 384 | 7.84 | 4.93 | 24.41 | 1.82 | −75.1 % |
| 1994–2009 | HML | 191 | 9.73 | 7.27 | 23.57 | 1.65 | −58.8 % |
| 2010–2025 | HML | 192 | 6.93 | 5.73 | 16.63 | 1.67 | −49.7 % |
| 1994–2009 | SMB | 191 | −6.06 | −7.59 | 19.08 | −1.27 | −86.1 % |
| 2010–2025 | SMB | 192 | 1.00 | 0.04 | 13.86 | 0.29 | −46.5 % |
| 1994–2009 | WML | 191 | 11.47 | 7.06 | 30.50 | 1.50 | −53.5 % |
| 2010–2025 | WML | 192 | 14.78 | 14.27 | 16.51 | 3.58 | −33.3 % |
| post-pub 2013-10→2025-12 | HML | 147 | 9.88 | 8.95 | 16.15 | 2.14 | −49.7 % |
| post-pub | SMB | 147 | 3.15 | 2.13 | 14.45 | 0.76 | −46.5 % |
| post-pub | MF | 147 | 10.70 | 9.89 | 15.69 | 2.39 | −34.4 % |
| 2016–2025 | HML | 120 | 10.51 | 9.68 | 15.94 | 2.09 | −49.7 % |

Value by calendar year shows how volatile the premium is. HML yearly returns, quoted from the
yearly CSV:

| Year | HML |
|---|---|
| 2018 | −21.04 % |
| 2019 | −20.93 % |
| 2021 | +38.54 % |
| 2023 | +34.67 % |
| 2025 | +11.37 % |

**Large-cap value, long-only.** This is the only contiguous window. The "Big Value" (BV) portfolio
has no gaps only from 2016-01 to 2025-12 (n = 120). Over that window:

- BV geo **24.12 %/yr**, vol 30.12 %, monthly-close max DD **−63.4 %**.
- BG (big growth) geo 13.02 %/yr, vol 14.96 %, max DD −22.2 %.
- BV − BG spread: geo 10.64 %/yr, **t = 1.72**.

The library requires only five stocks in a double-sort portfolio. BV's weighting scheme is NOT
VERIFIED. All these returns are gross of costs and tax.

### 2.4 How to read this for signals

- **Size.** The premium is **negative over 32 years** and flat since 2010. **No size signal.**
  Abstain.
- **Value.** The point estimate is positive in both halves and after publication, but no window
  reaches t ≥ 3.0.
  - Harvey, Liu & Zhu (2016, *RFS* 29(1):5–68) argue that "a newly discovered factor today should
    have a t-ratio that exceeds 3.0". Source: https://academic.oup.com/rfs/article/29/1/5/1843824
    (accessed 2026-10-15, via search summary; full text NOT re-read).
  - The worst drawdowns run from −50 % to −64 % and last 4 to 7.6 years.
  - The factor is **long-short**, and in many months it is small-cap only, so a retail long-only
    investor cannot hold it directly.
  - Verdict: **evidence exists, but it is not strong enough for a "buy value now" signal.** At most
    it supports a fixed, non-timed strategic tilt that the user chooses knowingly.
- **Publication decay.** McLean & Pontiff (2016, *JF* 71:5–32) quote: "Portfolio returns are 26%
  lower out-of-sample and 58% lower post-publication."
  - Source: https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365 (accessed 2026-10-15, via
    search summary of the abstract).
  - Indian HML did *not* decay after 2013 (8.95 % post-pub against 6.49 % full sample). One
    12-year window cannot separate "robust" from "lucky".

---

## 3. Index-provider evidence (tier C: mostly back-tests)

### 3.1 Launch date vs base date (VERIFIED from NSE Indices factsheets dated 2026-09-30)

All factsheets are from `https://www.niftyindices.com/Factsheet/<file>.pdf`, accessed 2026-10-15
and read once for research.

| Index | Methodology (factsheet wording) | Base date | Launch date | Back-test years before launch | Rebalancing |
|---|---|---|---|---|---|
| Nifty Low Volatility 50 | Volatility based weighting | 2003-12-31 | 2012-11-19 | ~8.9 | Quarterly |
| Nifty50 Value 20 | Tilt weighted | 2009-01-01 | 2014-03-28 | ~5.2 | Semi-annual |
| Nifty100 Quality 30 | Tilt weighted | 2009-10-01 | 2015-03-19 | ~5.5 | Semi-annual |
| Nifty100 Low Volatility 30 | Volatility based weighting | 2005-04-01 | 2016-07-08 | ~11.3 | Quarterly |
| Nifty Quality Low-Volatility 30 | Factor weighted | 2005-04-01 | 2017-07-10 | ~12.3 | Semi-annual |
| Nifty200 Quality 30 | Tilt weighted | 2005-04-01 | 2018-04-17 | ~13.0 | Semi-annual |
| Nifty200 Value 30 | Tilt weighted | 2005-04-01 | 2024-06-12 | ~19.2 | Semi-annual |
| Nifty500 Multifactor MQVLv 50 | composite percentile score | since 2005-04-01 in white paper | NOT VERIFIED (white paper dated Feb-2025) | — | Semi-annual (June & December) |

Factor definitions, quoted from the factsheets and white papers:

- **Low volatility.** Quote: "Volatility of the securities is calculated as the standard deviation
  of daily price returns (log normal) for last one year." From the Nifty100 Low Volatility 30
  factsheet.
- **Quality.** Nifty200 Quality 30 scores ROE, debt-to-equity and the variability of EPS growth
  over the previous 5 years. This is from a search summary of the factsheet; the exact wording
  is NOT VERIFIED.
- **Value.** The 2017 white paper lists "High ROCE", "High Dividend Yield", "Low P/E" and
  "Low P/B", all from the "Annual Report".
  - Nifty200 Value 30 uses E/P, B/P, S/P and dividend yield. Partial quote: "… to Price ratio (S/P)
    and Dividend Yield. Stock weight is based on the combination of the stock's value score and its
    free-float market [cap]".
- **Multifactor MQVLv 50.** Quote: "[25%*(Momentum Percentile Score) + 25%*(Quality Percentile
  Score) + 25%*(Value Percentile Score) + 25%*(Low Volatility Percentile Score)]".
  - Exclusions include stocks where "percentage pledged promoter shares is greater than 20%" and
    "Non - F&O stocks". Source: NSE Indices white paper, Feb-2025,
    https://www.niftyindices.com/docs/default-source/indices/nifty500-multifactor-mqvlv-50/nifty500-multifactor-mqvlv-50-whitepaper_2024.pdf

**NSE's own statement that the history is a back-test.** From the 2017 white paper "NIFTY
Multi-Factor Indices", https://archives.nseindia.com/content/indices/NIFTY_Multi-Factor_Indices_whitepaper.pdf
(accessed 2026-10-15), quoted verbatim: "Based on historical backtesting of over 12 years over
multiple market cycles, it has been observed that NIFTY multi-factor indices counter cyclicality of
single factor based portfolio".

### 3.2 Back-tested claims (tier C: context only, not evidence)

- **MQVLv 50 white paper (Feb-2025, data to 2024-12-31).** Quote: "Since April 01, 2005, the
  Nifty500 Multifactor MQVLv 50 TR index has delivered an annualized return of 21.11% outperforming
  the Nifty 500 TR index which delivered an annualized return of 14.97%".
  - Volatility 17.42 % vs 20.56 %.
  - Worst calendar year **−46.56 % (2008)**, against −56.54 % for the Nifty 500.
  - Worst 1-year rolling CAGR **−48.58 %**.
  - Nearly all of this period precedes launch.
- **2017 multi-factor white paper.** Calendar-2008 returns: the Low-Volatility portfolio fell
  **−44.60 %**, Value **−52.64 %**, Quality **−50.75 %**, against **−51.79 %** for the Nifty 50.
  - Quote: "during the downturn of 2008, Alpha portfolio fell by 66.96% whereas NIFTY Alpha Quality
    Low-Volatility 30 fell only by 43.93%".
  - **All of this is back-tested** (launch 2017). It shows that low-vol and multi-factor products
    *still* fall about 40–50 % in a crash.

### 3.3 Most recent 5 years (2021-10 to 2026-09)

This window is live for every index except Nifty200 Value 30. Total-return index, gross of fund
fees. VERIFIED from factsheets dated 2026-09-30.

| Index | 5-yr TR %/yr | 1-yr TR % | Live for the full 5 years? |
|---|---|---|---|
| Nifty 50 (parent / reference) | 6.38 | −7.09 | yes |
| Nifty 200 (parent) | 8.30 | −3.23 | yes |
| Nifty100 Low Volatility 30 | 8.12 | −4.68 | yes |
| Nifty Low Volatility 50 | 8.30 | −4.96 | yes |
| Nifty100 Quality 30 | 7.25 | −3.17 | yes |
| Nifty200 Quality 30 | 6.40 | −5.42 | yes |
| Nifty Quality Low-Volatility 30 | 5.81 | −6.38 | yes |
| Nifty50 Value 20 | 6.20 | −9.51 | yes |
| Nifty200 Value 30 | 22.91 | 7.89 | **no** (launched 2024-06-12; about 2.7 of 5 years back-tested) |

Factsheet SD columns are "1 Year / 5 Years / Since inception", and the factsheets note "Based on
Price Return Index":

| Index | 5-yr SD % | Parent 5-yr SD % |
|---|---|---|
| Nifty100 Low Volatility 30 | 11.97 | Nifty 200: 14.39 |
| Nifty200 Quality 30 | 13.54 | Nifty 200: 14.39 |
| Nifty200 Value 30 | 20.09 | — |

The Nifty 100 TR parent figure was not retrieved: the factsheet URL tried returned HTML, not a
PDF (NOT VERIFIED).

**Reading.** Over the latest live 5 years, the quality and low-vol indices did **not beat the Nifty
200 parent** on return (6.40–8.30 against 8.30). Low-vol did deliver **lower volatility**. Value
diverged sharply between its two definitions: NV20 (live) returned 6.20, while Value 30 (half
back-test) returned 22.91.

---

## 4. Live, investable, net-of-fee evidence (tier A)

### 4.1 Method

- **Data.** Daily NAVs from `api.mfapi.in/mf/<code>`, the unofficial AMFI mirror that the source
  registry lists as FALLBACK / cross-check. Fetched once on 2026-10-15 for research and not stored
  in the repo.
- **Benchmark.** UTI Nifty 50 Index Fund – Direct – Growth (scheme 120716). Its NAV is net of fees,
  so this is a like-for-like "what you would actually have earned" comparison.
- **Start of each window.** Common dates only. The first 30 common dates are dropped to skip launch
  noise.
- **ETF unit splits.** These are detected heuristically: a day-on-day NAV ratio below 0.4 or above
  2.5 is treated as a split.
  - Split factors were about 9.95–9.96, applied on 2024-03-04 (schemes 141596, 139455) and on
    2024-05-13 (scheme 148456).
  - That these were 1:10 unit splits is **NOT VERIFIED** against AMC notices.
  - The engine must take corporate actions from a curated table, never from heuristics.
- **Excess return.** Month-end to month-end fund return minus benchmark return. t = mean /
  (SD / √n). Floats, scratch only.

### 4.2 Results (VERIFIED as computed; mfapi data fidelity vs AMFI NOT VERIFIED)

| Scheme (code) | Window | CAGR fund / Nifty 50 fund | Vol fund / bench | Max DD fund / bench | Excess (arith, ann.) | Tracking error | t |
|---|---|---|---|---|---|---|---|
| ICICI Pru Nifty100 Low Vol 30 ETF (141596) | 2018-08-14 → 2026-10-14 (8.17 y) | 10.67 % / 9.72 % | 14.5 % / 17.4 % | −30.5 % / −38.4 % | +0.35 % | 6.68 % | 0.15 |
| ICICI Pru Nifty50 Value 20 ETF (139455) | 2018-08-14 → 2026-10-14 (8.17 y) | 11.01 % / 9.72 % | 16.2 % / 17.4 % | −31.0 % / −38.4 % | +0.71 % | 7.79 % | 0.26 |
| Edelweiss ETF Nifty100 Quality 30 (139367) | 2016-07-11 → 2021-10-06 (5.24 y; data stops) | 13.84 % / 16.14 % | 16.0 % / 18.1 % | −32.7 % / −38.4 % | −2.40 % | 7.03 % | −0.78 |
| ICICI Pru Nifty Alpha Low-Vol 30 ETF (148456) | 2020-09-24 → 2026-10-14 (6.05 y) | 13.84 % / 14.07 % | 13.5 % / 14.2 % | −25.0 % / −16.6 % | +0.05 % | 7.67 % | 0.02 |
| Nippon India Nifty Alpha Low Vol 30 Index Fund Direct (150487) | 2022-10-04 → 2026-10-14 (4.03 y) | 10.24 % / 7.91 % | 12.3 % / 12.6 % | −24.9 % / −15.5 % | +2.88 % | 6.11 % | 0.94 |
| UTI Nifty 200 Quality 30 Index Fund Direct (152859) | 2024-11-07 → 2026-10-14 (1.93 y) | −4.24 % / −2.50 % | 13.8 % / 13.2 % | −16.5 % / −15.1 % | — | — | too short |

### 4.3 Reading

- **No live factor product shows a statistically distinguishable excess return.** All |t| < 1.
- **How long it would take to know.** With a tracking error around 7 %, a true +1 %/yr edge needs
  about **(2 × 7 / 1)² ≈ 196 years** of data to reach t = 2. A +3 %/yr edge needs about **22
  years**. This is arithmetic from the measured tracking errors, not a forecast.
- **Low-vol worked as advertised on risk.** The Nifty100 Low Vol 30 ETF had lower volatility
  (14.5 % vs 17.4 %) and a shallower max drawdown (−30.5 % vs −38.4 %) with similar return.
- **Alpha-low-vol funds had *deeper* drawdowns than the Nifty 50 in their windows** (−25 % vs
  −15.5 % to −16.6 %). So "low-vol" in a multi-factor name does not guarantee a defensive outcome.
- **Survivorship.** Only live schemes found through mfapi search were examined. The Edelweiss
  Quality 30 ETF series ends in 2021-10, and why it ends is NOT VERIFIED. Merged or closed schemes
  are missing, which biases this table **upward**.

---

## 5. Can each factor be computed deterministically from free, terms-compliant data?

| Input needed | Candidate source | Terms (quoted) | Status |
|---|---|---|---|
| Daily stock prices (low-vol, momentum, size) | NSE website / bhavcopy | Source registry §2.11: ToU bans "systematic or automated data collection activities (including scraping…)"; content shall not be "stored … without prior written permission of NSE" | **BLOCKED** |
| Daily stock prices | BSE | Source registry §2.11: "Any reproduction, redistribution or transmission … is strictly prohibited" | **BLOCKED** |
| Index TRI history (Nifty factor indices) | niftyindices.com | https://www.niftyindices.com/terms-of-use (accessed 2026-10-15): "You may not conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting) on or in relation to our website without our express written consent." Also: "No material from the Site may be copied, modified, reproduced, republished … without prior written permission" and "Aggregate, copy or duplicate in any manner any of the content or information available from the Site" (listed under prohibited uses) | **BLOCKED** for ingestion. Manual reading only, citing figures in docs as done here |
| Fundamentals (ROE, D/E, EPS, B/P, E/P) | screener.in | https://www.screener.in/guides/terms/ (accessed 2026-10-15): "Permission is granted to use the materials … for personal, non-commercial transitory viewing only" and "you may not: modify or copy the materials" | **BLOCKED** |
| Fundamentals | Company annual reports (company sites), exchange filings | Exchange sites BLOCKED (above). Company sites: per-company terms NOT VERIFIED. Manual per-company entry is possible but cannot rebuild a point-in-time cross-section of 200–500 firms | **BLOCKED** for a cross-sectional signal; manual single-company notes only |
| Factor returns (SMB, HML, WML, market) | IIM-A data library CSV | Citation required; no licence text found (NOT VERIFIED); robots.txt 404 | **REQUIRES CONFIGURATION**: user-initiated manual import of a pinned release with sha256, for evidence display only |
| Factor index fund / ETF NAV | AMFI NAVAll (LIVE adapter); mfapi fallback | AMFI ToU: "personal and non-commercial use only" (source registry §2.1) | **VERIFIED** (existing adapter). Live NAV history is the only automatable factor-performance data |
| Market-cap categories (size) | AMFI semi-annual large/mid/small-cap list | AMFI ToU applies; file format and URL NOT VERIFIED | NOT VERIFIED |

**Conclusion.**

- No free, terms-compliant data exists for a **stock-level** value, quality, low-vol or size
  signal. The engine must answer **"No suitable candidate"** (status BLOCKED) and name the licence
  it would need (a licensed vendor, already listed in source registry §6.5).
- What *is* deterministic and compliant:
  1. NAV-based metrics for factor index funds: CAGR, vol, max DD, tracking error vs a reference
     index fund, and t of excess. These are pure functions of the AMFI NAV series, an as-of date
     and a split table.
  2. Display of IIM-A factor history (pinned release) with the statistics in §2.3.

---

## 6. Costs and tax: what survives

### 6.1 DIY stock-level factor portfolio (hypothetical; data BLOCKED anyway)

**Statutory and broker costs.** From Zerodha's charges page, https://zerodha.com/charges/ (accessed
2026-10-15; broker page, VERIFIED-SECONDARY). Equity delivery rows:

- STT/CTT: "0.1% on buy & sell"
- Transaction charges (NSE): "0.00307%"
- Stamp: "0.015% or ₹1500 / crore on buy side"
- GST: "18% on (brokerage + SEBI charges + transaction charges)"
- SEBI: "₹10 / crore"
- DP charge on sale: ₹15.34 per scrip

**Formula (per ₹ of round-trip turnover).** Excluding the bid-ask spread and impact cost, which
are NOT VERIFIED:

`c_rt = 0.001 + 0.001 + 0.00015 + 2×0.0000307 + 0.18×2×0.0000307 + 2×0.000001 ≈ 0.2224 %`

Annual cost drag ≈ `one-way annual turnover × c_rt`, plus spread and impact. One-way turnover for
these strategies is NOT VERIFIED. Raju & Teli (2022) say low-vol and quality "show fairly low
turnover" (below).

**Tax.** Tax rules are in `indian-instruments-and-tax.md`, rows EQ-STCG and EQ-LTCG (VERIFIED-PRIMARY):

- STCG **20 %** if the holding is ≤ 12 months.
- LTCG **12.5 %** above ₹1.25 lakh/yr.

Semi-annual or quarterly rebalancing makes many sales short-term. A DIY factor portfolio therefore
pays tax *every year* on realised gains at up to 20 %. A buy-and-hold index fund defers tax until
redemption and then pays 12.5 %.

### 6.2 Factor index fund / ETF

- **Cost.** The fund's TER/BER is already inside NAV, so the §4 figures are net of it. Stamp duty
  0.005 % on purchase and STT 0.001 % on redemption both apply (`indian-instruments-and-tax.md`
  lines 85–86).
- **Internal rebalancing is not taxed at fund level.** Mutual-fund income is exempt under
  s.10(23D) of the Income-tax Act, 1961. The ICI Global letter of 23-Jan-2023
  (https://www.ici.org/system/files/2023-01/34830a.pdf, accessed 2026-10-15 via search summary)
  says Indian tax law "exempts all income earned by mutual funds in India from tax in the hands of
  the mutual fund."
  - Status: VERIFIED-SECONDARY.
  - The section number under the Income-tax Act 2025 is **NOT VERIFIED**. Needs CA review.
- **Consequence.** If a factor tilt is used at all, the **index fund wrapper dominates a DIY stock
  portfolio** on tax for an Indian resident. This also fits the project's data constraints.

### 6.3 Academic cost evidence (tier B/C; abstract-level only)

- **Raju & Teli (2022)**, "'Long' Factors, not 'Short' Change: Long Only Factor Portfolios in
  India", SSRN 4000418 (https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4000418; SSRN returned
  403, so this is the abstract via search, accessed 2026-10-15).
  - "we show that alpha for momentum, low volatility and quality strategies survives real-world
    implementation costs"
  - "strategies like low volatility and quality show fairly low turnover"
  - "there is not one factor-style that is a consistent winner"
  - "The market exposure is significant across all the style strategies"
  - The universe is the top 200 stocks, equal-weighted, rebalanced monthly. **Tax is not mentioned
    in the abstract** (NOT VERIFIED whether the paper covers it).
- **Raju & Krishnan (2022)**, "Factor Indices in India: Factor Exposures and Style Analysis",
  SSRN 4133389 (abstract via search). Quote: "multi-factor and complex factor indices show that
  the underlying factor exposures are generally uneven and occasionally nonexistent for one of the
  claimed factors."
- **Raju & Jacob (2024)**, SSRN 4874166 (abstract via search). They find "significant variation in
  the alignment of these [multifactor] funds with multifactor investing principles".
- **Raju (2025)**, "Timing Indian Equity Factors: Structural vs. Revaluation Signals", SSRN 5513940
  (abstract via search, NOT VERIFIED verbatim). It reports limited timing ability, with "only
  momentum at the 12-month horizon showing significance and forecast-error gains below economic
  thresholds". **This directly argues against factor-timing "buy value now" signals.**

---

## 7. Factor-specific evidence summary

| Factor | Best Indian evidence | Gross effect | After costs/tax, investable | Worst drawdown seen | Signal verdict |
|---|---|---|---|---|---|
| **Size (SMB)** | IIM-A library 1994–2025 | −3.84 %/yr geo, t = −0.85 | n/a | −86 % (monthly), −87 % (daily, 30.9 y duration) | **Abstain.** No premium |
| **Value (HML)** | IIM-A library; Agarwalla et al. Vikalpa 2017 | +6.49 %/yr geo, t = 2.31 (full); +8.95 %, t = 2.14 (post-pub) | NV20 ETF live: +0.71 %/yr vs Nifty 50 fund, t = 0.26 | HML −58.8 % monthly / −64 % daily; NV20 ETF −31 % | **Abstain** on timing. Strategic tilt only, if the user chooses it with drawdown disclosure |
| **Quality** | Mixed academic: Emerald *Managerial Finance* value & quality paper says "the quality-only strategy failed to produce substantial risk-adjusted returns in the Indian stock market" (via search summary, https://www.emerald.com/insight/content/doi/10.1108/mf-02-2023-0112/full/pdf, NOT VERIFIED verbatim). An Indian QMJ study for 2013–2023 reports a slightly negative QMJ average (ScienceDirect S0970389626000303, via search, NOT VERIFIED) | Unclear | Quality 30 ETF live 2016–21: −2.40 %/yr, t = −0.78. Nifty200 Q30 5-yr TR 6.40 vs Nifty 200 8.30 | 2008 back-test −50.75 % | **Abstain** |
| **Low volatility** | Joshipura & Joshipura (2016, *Applied Finance Letters* 5(1)): low-vol decile 11.40 % vs high-vol decile 1.30 % annualised excess return (via search summary; the full-text URL returned 404, so NOT VERIFIED verbatim). Tulsyan, Joshipura & Mishra (2025, *QREF*, doi 10.1016/j.qref.2025.102060) find the risk anomaly in Nifty 500 2003–2022 (via search). Raju (2023) SSRN 4398656 finds it "even after controlling for the standard academic factors" (via search). Pandey & Samanta (2016) find **no** anomaly in S&P CNX 100, 2001–2014 (via search, NOT VERIFIED) | Return premium contested; **risk reduction consistent** | LV30 ETF live: +0.35 %/yr (t = 0.15) with vol 14.5 % vs 17.4 % and max DD −30.5 % vs −38.4 % | 2008 back-test −44.6 % | **No return signal.** Risk-reduction property is descriptively supported. Usable as a *risk* characteristic, not a "buy" signal |
| **Multi-factor** | NSE back-tests only (tier C). Raju & Krishnan / Raju & Jacob find uneven factor exposures | Back-test MQVLv 21.11 % vs 14.97 % (pre-launch) | Alpha-LowVol funds live: +0.05 % (t = 0.02) and +2.88 % (t = 0.94); drawdowns deeper than Nifty 50 in their windows | 2008 back-test −46.56 % (MQVLv) | **Abstain** |
| *Momentum (comparator)* | IIM-A WML +10.62 %/yr, t = 3.03 full; 2010–2025 t = 3.58 | Strongest of the set | Not tested here (separate note) | −53.5 % monthly / −62 % daily | Out of scope here |

---

## 8. Recommendations for the engine (deterministic, abstaining)

1. **Do not implement any stock-level factor signal.** Return `BLOCKED: no licensed per-stock price
   or fundamentals source` together with the source-registry reference.
2. **Add a "factor fund evidence" calculator.** This is a pure function of AMFI NAV series, a
   curated split/merger table and an as-of date. Outputs:
   - CAGR, annualised vol, max DD;
   - monthly excess vs a user-selected reference index fund;
   - tracking error, t-stat of excess, and `years_to_t2 = (2·TE/|excess|)²`.

   Gates:
   - n < 36 months → `low_confidence`;
   - |t| < 2 → the label must read "no statistically distinguishable excess return".

   Never call this a buy signal.
3. **Optional evidence panel (REQUIRES CONFIGURATION).** The user imports an IIM-A release CSV by
   hand. The engine stores the release ID and sha256, recomputes §2.3 with `Decimal`, and shows
   drawdown tables. It always shows the "HML is small-cap-only in months without large-cap value"
   caveat and the citation.
4. **Never present index-provider back-tests as performance.** If a figure from a factsheet or
   white paper is shown at all, store `launch_date` and `base_date` with it, and render any period
   before launch as "back-test (provider)".
5. **Factor timing → abstain.** No documented out-of-sample, cost- and tax-aware Indian evidence
   was found that meets the project rule (Raju 2025 abstract, §6.3).
6. **Feasibility link.** Factor tilts add little to `return-target-feasibility.md`. The best live
   excess return seen was +2.88 %/yr (t = 0.94) over 4 years. Measured equity returns in these
   windows were 8–14 %/yr. No factor product here moves a portfolio into a 20–25 %/yr range with
   any statistical support.
7. **Survivorship banner.** Any fund-level factor table must carry "live schemes only".

---

## 9. Open items and NOT VERIFIED list

- IIM-A data licence: none found. Ask the authors before any non-personal use.
- How BV/BG portfolios are weighted (value- vs equal-weighted) in the IIM-A new series. Read the
  working paper PDF.
- ETF unit-split dates and ratios for schemes 141596, 139455 and 148456. Check against AMC notices.
- Why the Edelweiss Nifty100 Quality 30 ETF series ends in 2021-10 (merger, delisting or data gap).
- Nifty500 Multifactor MQVLv 50 launch date. Nifty 100 TR 5-yr figure.
- Full text of the Raju papers, Joshipura (2016), the Emerald value-quality paper and the QMJ
  India papers. Only abstracts or search summaries were read.
- s.10(23D) equivalent in the Income-tax Act 2025 (CA review).
- Bid-ask spread and impact costs for Nifty 200 stocks. No free primary source found.
- mfapi.in NAV fidelity vs AMFI for the schemes used. Cross-check a sample against AMFI NAVAll
  history.

## 10. Sources (all accessed 2026-10-15)

- IIM-A data library: https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/
  - FAQ: …/FAQ.php
  - Drawdowns: …/drawdown.php
- Agarwalla, Jacob & Varma (2017), "Size, Value, and Momentum in Indian Equities", *Vikalpa* 42(4):
  211–219, https://journals.sagepub.com/doi/pdf/10.1177/0256090917733848 (HTTP 403; cited via the
  library's citation text only).
- NSE Indices white paper: NIFTY Multi-Factor Indices (2017),
  https://archives.nseindia.com/content/indices/NIFTY_Multi-Factor_Indices_whitepaper.pdf
- NSE Indices white paper: Nifty500 Multifactor MQVLv 50 (Feb-2025),
  https://www.niftyindices.com/docs/default-source/indices/nifty500-multifactor-mqvlv-50/nifty500-multifactor-mqvlv-50-whitepaper_2024.pdf
- NSE Indices factsheets dated 2026-09-30, all at https://www.niftyindices.com/Factsheet/:
  - Nifty100_LowVolatility30.pdf
  - Factsheet_NIFTY200_Quality30.pdf
  - Nifty50_Value20.pdf
  - Factsheet_Nifty200_Value30.pdf
  - Factsheet_nifty_Low_Volatility50.pdf
  - Nifty100_Quality30.pdf
  - Factsheet_NIFTY_Quality_Low-Volatility_30.pdf
  - ind_nifty50.pdf
  - ind_nifty_200.pdf
- niftyindices.com terms: https://www.niftyindices.com/terms-of-use
- screener.in terms: https://www.screener.in/guides/terms/
- Zerodha charges: https://zerodha.com/charges/
- mfapi.in scheme NAV history: https://api.mfapi.in/mf/{141596,139455,139367,148456,150487,152859,120716}
- McLean & Pontiff (2016): https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365
- Harvey, Liu & Zhu (2016): https://academic.oup.com/rfs/article/29/1/5/1843824
- Raju & Teli (2022): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4000418
- Raju & Krishnan (2022): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4133389
- Raju & Jacob (2024): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4874166
- Raju (2023), Low-Risk Anomaly: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4398656
- Raju (2025), Timing Indian Equity Factors: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5513940
- Joshipura & Joshipura (2016), *Applied Finance Letters*:
  https://ojs.aut.ac.nz/applied-finance-letters/article/download/32/31/ (404 at access)
- Tulsyan, Joshipura & Mishra (2025), *QREF*: https://www.sciencedirect.com/science/article/pii/S1062976925001012
- Value and quality investing in India, *Managerial Finance*:
  https://www.emerald.com/insight/content/doi/10.1108/mf-02-2023-0112/full/pdf
- ICI Global letter (s.10(23D)): https://www.ici.org/system/files/2023-01/34830a.pdf
