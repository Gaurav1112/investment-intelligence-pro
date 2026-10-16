# Verification: research-evidence-value-quality.md (adversarial review)

Status: verifier note, wave 1 · Date: 2026-10-15 · Reviewer: adversarial skeptic agent
Target: `docs/research/wave1/research-evidence-value-quality.md` (findings EVQ-1 to EVQ-10)
Status labels: VERIFIED / NOT VERIFIED / REQUIRES CONFIGURATION / BLOCKED. All access dates 2026-10-15.

## 0. Verdict summary

| ID | Claim | Verdict | One-line reason |
|---|---|---|---|
| EVQ-1 | No terms-compliant free source for stock-level factor signals (BLOCKED) | **WEAKENED** | Quotes are accurate, but the sibling wave-1 note documents free broker APIs (Upstox, Angel One) as a REQUIRES CONFIGURATION route for per-stock prices, so "BLOCKED" overstates it for price-only factors (low-vol, size proxy) |
| EVQ-2 | Size premium negative over 32 years | **CONFIRMED** | File hash matches; every statistic re-computed exactly; drawdown-page quote verbatim |
| EVQ-3 | Value positive, below t>3, long-short, often small-cap only, deep drawdowns | **CONFIRMED** | Re-computed exactly; I also confirmed empirically that HML = SV − SG in months without large-cap value |
| EVQ-4 | Nifty factor index histories are mostly back-tests | **CONFIRMED** | Base/launch dates verified on the 2026-09-30 factsheets; white-paper quote verbatim (minor scope caveat) |
| EVQ-5 | Live factor ETF/index fund excess returns indistinguishable from zero | **CONFIRMED (with caveats)** | Every row re-computed exactly from mfapi; the caveats are benchmark mismatch, low power, and trading costs |
| EVQ-6 | Low-vol reliably reduced risk live, not return | **WEAKENED** | Numbers reproduce, but "reliably" rests on one ETF, one 8-year window and a single crash (2020) |
| EVQ-7 | Fund wrapper beats DIY on tax **and cost** | **WEAKENED** | The tax half holds. The cost half is not shown: factor ETF TERs (about 0.36–0.5 %, secondary) may exceed DIY round-trip costs at plausible turnover. s.10(23D) is superseded by the Income-tax Act 2025 |
| EVQ-8 | IIM-A library usable only as a pinned, manually imported evidence panel | **CONFIRMED** | Recalculation quote verbatim; no licence text on the page; robots.txt 404 |
| EVQ-9 | Factor timing has no adequate Indian OOS support | **WEAKENED** | The Raju (2025) abstract wording is confirmed via search. But the absence claim is too broad: Raju himself finds 12-month momentum timing significant, and McLean & Pontiff is US evidence |
| EVQ-10 | Quality premium in India is contested | **WEAKENED** | "Contested" holds, but the evidence is cherry-picked: the same Emerald paper reports significant QMJ and value+quality alphas, and the QMJ-study description conflicts with search summaries |

No finding is refuted outright. The report's numeric work is unusually reproducible: every IIM-A and mfapi figure I checked matched to the last decimal shown.

---

## 1. Method

- **IIM-A CSVs.** I re-downloaded the three CSVs from `https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/DATA/2025-12_*.csv` into scratch and computed sha256:
  - `c07a12d1c04630c18a7f87a96c91db6a7c4ebfc1e37f888e41fe8469fe234c44` (monthly four-factor)
  - `e5bacdf5a70e9df9ab50ce164144bd87d274ca289ae2157a89bf34a16ccea060` (yearly)
  - `8cd62adf3d8a14cd6accbf63e582f5b39dadb12dc94efbba80bed443bee15c46` (size-value portfolios)

  All three are **identical** to the hashes in the report. I re-implemented the stated method independently (stdlib floats, scratch only).
- **mfapi NAVs.** I fetched `api.mfapi.in/mf/{141596,139455,139367,148456,150487,152859,120716}` and re-implemented the report's method: common dates, first 30 dropped, a split heuristic (ratio < 0.4 or > 2.5), month-end excess returns, and t = mean/(sd/√n).
- **Primary documents.** I downloaded the NSE Indices factsheets dated 2026-09-30 (five of them) and the 2017 NSE multi-factor white paper, then extracted the text with `pdftotext`.
- **Terms pages.** I fetched niftyindices.com terms (curl), screener.in terms, the Zerodha charges page, the IIM-A main page, the drawdown page and the FAQ.
- **Search limit.** The session's web-search budget ran out before I could re-check Harvey, Liu & Zhu (2016). That citation stays NOT VERIFIED (re-check pending), as the report already labels it.

---

## 2. Finding-by-finding

### EVQ-1: Stock-level factor signals have no terms-compliant free source. **WEAKENED**

**Quotes check out.**

- niftyindices.com/terms-of-use (curl, 2026-10-15), verbatim:
  - "You may not conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting) on or in relation to our website without our express written consent."
  - "No material from the Site may be copied, modified, reproduced, republished, uploaded, transmitted, posted or distributed in any form without prior written permission from the Company."
  - "Aggregate, copy or duplicate in any manner any of the content or information available from the Site".

  VERIFIED.
- screener.in/guides/terms/ (WebFetch, 2026-10-15): "Permission is granted to use the materials (information or software) on Site for personal, non-commercial transitory viewing only." Under prohibited uses: "modify or copy the materials". VERIFIED.
- NSE and BSE: `docs/data/source-registry.md` §2.11 matches what the report cites.

**Why the verdict is weakened.** The conclusion "No free, terms-compliant data exists for a stock-level … low-vol or size signal" ignores the companion note `docs/research/wave1/research-equity-data-alt.md` (§1, §3.2, §3.3). That note ranks **Upstox** and **Angel One SmartAPI** as free, user-account broker APIs with status REQUIRES CONFIGURATION. I independently re-checked two Upstox pages:

- https://upstox.com/trading-api/ (2026-10-15): "₹0 Free access to trading & market data APIs" and "All trading + data APIs are free of cost." VERIFIED.
- https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/ (2026-10-15): daily candles "Available from January, 2000". VERIFIED. The page does not say whether delisted instruments are covered (NOT VERIFIED).

**Consequences.**

- **Low-volatility** needs only per-stock daily prices, so it is computable under REQUIRES CONFIGURATION, not BLOCKED. A **size** proxy needs prices plus share counts; share counts are NOT VERIFIED from these APIs.
- Value and quality still lack a point-in-time fundamentals source. Upstox's fundamentals API exists but shows only a few periods and names no vendor, per the sibling note. "BLOCKED for a cross-sectional point-in-time backtest" remains defensible there.
- A signal would still abstain, but for a different reason: a broker API probably lacks delisted stocks. That makes a **survivorship-free, out-of-sample backtest** infeasible, and that is what the project rule demands. The correct label is "REQUIRES CONFIGURATION for data; abstain for lack of a survivorship-free backtest", not "BLOCKED by terms".

### EVQ-2: Size premium negative over 32 years. **CONFIRMED**

- **Re-computation (1994-01 to 2025-12).** SMB n = 383, arith −2.52, geo **−3.84**, vol 16.68, **t = −0.85**, max DD (monthly) **−86.1 %**. These are identical to the report.
- **Sub-periods.**
  - 1994–2009: −7.59 geo, t −1.27.
  - 2010–2025: +0.04 geo, t 0.29.

  Both identical.
- **Drawdown page** (https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/drawdown.php, verbatim): "The Size Factor (SMB) provided an annualized return of -4.01% with an annualized volatility of 13.68%. The worst drawdown was 87.00% and the duration of this drawdown was 30.90 years". VERIFIED.
- **Caveat 1.** n = 383, not 384, because **1994-11 is `NA`** for SMB/HML/WML. The report never mentions this. It also explains why the site headline (SMB −3.71 %, HML 6.61 %) differs from the recomputation (−3.84 %, 6.49 %): the report leaves that difference unexplained.
- **Caveat 2.** The report says the drawdown page "uses daily data". The page itself does not say so. The main page does say "The monthly and yearly return values of the factors are compounded values of daily returns", which makes the inference plausible, but it remains NOT VERIFIED.

### EVQ-3: Value positive, below t>3, long-short, often small-cap only. **CONFIRMED**

- **Re-computation.**
  - Full sample: HML geo **6.49**, t **2.31**, max DD **−58.8 %**.
  - Post-publication (2013-10 to 2025-12): geo **8.95**, t **2.14**.
  - Half-samples: 1994–2009 t 1.65; 2010–2025 t 1.67.

  All identical.
- **Drawdown page, verbatim:** "The Value Factor (HML) provided an annualized return of 6.86% with an annualized volatility of 15.09%. The worst drawdown was 64.00% and the duration of this drawdown was 7.60 years". The −51.9 % row (2018-01-16 → 2020-03-30 → 2022-01-28) is also present. VERIFIED.
- **Small-cap caveat, verbatim on the main page:** "If the Large-Cap Value portfolio is absent after applying this rule, the value factor is computed as the difference between Small Growth and Small Value." VERIFIED.
- **BV gaps.** BV is missing in 154 of 387 rows, including all 12 months of 2001–2006, 2009, 2010 and 2014. Re-counted; identical.
- **Sign check (new).** The site's wording literally reads as SG − SV, which would make HML a growth-minus-value spread. I checked the data in the 153 months where BV is missing and HML is present:
  - HML matches **SV − SG**, with median absolute gap 0.16 pp and correlation 0.996.
  - It does not match SG − SV (median gap 6.5 pp).

  So the report's reading ("small-cap-only value spread", long small value) is correct and the site's wording is loose. The engine's import should assert this sign empirically.
- **Yearly HML** values (2018 −21.04, 2019 −20.93, 2021 +38.54, 2023 +34.67, 2025 +11.37) match the yearly CSV.
- **Statistical caveat.** These t-stats assume i.i.d. monthly returns. No Newey-West or autocorrelation adjustment was applied, so t = 2.31 may be slightly overstated. This does not change the verdict.

### EVQ-4: Nifty factor index histories are mostly back-tests. **CONFIRMED**

Base and launch dates, from factsheets I downloaded (all "September 30, 2026"):

| Factsheet | Launch date | Base date |
|---|---|---|
| Nifty200 Quality 30 | April 17, 2018 | April 01, 2005 |
| Nifty100 Low Volatility 30 | July 08, 2016 | April 01, 2005 |
| Nifty200 Value 30 | June 12, 2024 | April 01, 2005 |
| Nifty50 Value 20 | March 28, 2014 | January 01, 2009 |

VERIFIED.

- **2017 white paper**, verbatim: "Based on historical backtesting of over 12 years over multiple market cycles, it has been observed that NIFTY multi-factor indices counter cyclicality of single factor based portfolio". VERIFIED.
  - Scope caveat: this sentence is about the **multi-factor** indices. The back-test status of the single-factor indices rests on the base/launch dates, not on this quote.
- **2008 figures in the paper**: −44.60 / −52.64 / −50.75 / −51.79, and "Alpha portfolio fell by 66.96% whereas NIFTY Alpha Quality Low-Volatility 30 fell only by 43.93%". All present. VERIFIED.
- **Correction in the report's favour.** The quality definition, which the report marks NOT VERIFIED, is verbatim on the Nifty200 Quality 30 factsheet: "quality score for each company is determined based on return on equity (ROE), financial leverage (Debt/Equity Ratio) and earning (EPS) growth variability analysed during the previous 5 years." It can be upgraded to VERIFIED.
- **Factsheet "Since inception" columns.** These are measured from the base date (e.g. Nifty200 Value 30 TR "Since" 16.12 %), so they mix back-test and live data. That supports the report's rule 4.

### EVQ-5: Live factor fund excess returns indistinguishable from zero. **CONFIRMED (with caveats)**

My independent re-run reproduced every number:

| Scheme | Excess (ann.) | TE | t | Splits detected |
|---|---|---|---|---|
| 141596 | +0.35 | 6.68 | 0.15 | 2024-03-04 ×9.96 |
| 139455 | +0.71 | 7.79 | 0.26 | 2024-03-04 ×9.954 |
| 139367 | −2.40 | 7.03 | −0.78 | none |
| 148456 | +0.05 | 7.67 | 0.02 | 2024-05-13 ×9.939 |
| 150487 | +2.88 | 6.11 | 0.94 | none |

The UTI Nifty 200 Quality 30 Index Fund (152859) gives −0.80 %, t −0.14, n = 23. The report correctly marks it too short.

Caveats the report understates:

1. **Benchmark mismatch.** Nifty100- and Nifty200-universe factor funds are compared with a **Nifty 50** fund. The excess return therefore mixes the factor with a universe/size effect. A Nifty 100 or Nifty 200 index fund would be the cleaner benchmark.
2. **Power.** |t| < 1 with TE of 6–8 % over 4–8 years is *absence of evidence*, not evidence of zero premium. The report's own "years to t = 2" arithmetic says the same, so the finding should not be read as "factor premia are zero".
3. **ETF NAV is not the investor's return.** ETF holders transact at market price. Spread, brokerage, STT on sale and premium/discount to NAV are not in NAV. "Net-of-fee" is true; "what you would actually have earned" (§4.1) is overstated for the ETF rows.
4. **Start-date truncation.** A third-party page (tickertape/search summary, NOT VERIFIED) gives the ICICI LowVol30 ETF launch as 04 Jul 2017. The mfapi series starts 2018-07-03, so about a year of live history may be missing.
5. **No multiple-testing control.** Six funds were tested. That doesn't change the conclusion, since none is significant.

### EVQ-6: Low-vol reliably reduced risk live, not return. **WEAKENED**

- **Numbers reproduce.**
  - 141596: daily vol 14.5 vs 17.4; max DD −30.5 vs −38.4; CAGR 10.67 vs 9.72.
  - Alpha-LowVol funds: DD −25.0 vs −16.6 (148456) and −24.9 vs −15.5 (150487).
  - Nifty100 LowVol30 factsheet: 5-year SD 11.97 vs Nifty 200's 14.39.

  All VERIFIED.
- **Why weakened.** "Reliably" rests on **one** ETF over **one** 8-year window. The max-DD comparison is dominated by **one** event (the March 2020 crash), so n = 1 for drawdowns.
- **Inconsistent benchmark.** The ETF's comparator is the Nifty 50 fund, while the factsheet comparison is against the Nifty 200.
- **Back-test contradiction.** The report's own tier-C evidence shows the low-vol portfolio fell −44.6 % in 2008 against −51.8 % for the Nifty 50. That is a smaller risk reduction than "reliable" implies.

Better wording: "Over one live 8-year window that contained one crash, the low-vol ETF showed lower volatility and drawdown."

### EVQ-7: Fund wrapper beats DIY on tax and cost. **WEAKENED**

- **Zerodha charges** (https://zerodha.com/charges/, 2026-10-15), equity delivery, verbatim:
  - STT: "0.1% on buy & sell"
  - Transaction charges: "NSE: 0.00307%"
  - Stamp: "0.015% or ₹1500 / crore on buy side"
  - GST: "18% on (brokerage + SEBI charges + transaction charges)"
  - SEBI charges: "₹10 / crore"
  - DP: "₹15.34 per scrip"

  VERIFIED-SECONDARY (broker page). The arithmetic c_rt ≈ 0.2224 % is correct.
- **Tax half: supported.** Annual realisation of short-term gains at 20 % (STCG) against deferral to 12.5 % (LTCG) is a real advantage for the fund, using the `indian-instruments-and-tax.md` rows EQ-STCG/EQ-LTCG (VERIFIED-PRIMARY there).
- **Cost half: not demonstrated.** Factor ETF TERs are about **0.36–0.50 %/yr** for ICICI LowVol30 (third-party sites via search: tickertape 0.36 % as of 15-Sep-2026, Anand Rathi 0.48 %; NOT VERIFIED against the AMC). DIY drag at an assumed one-way turnover of 50–100 %/yr is roughly 0.11–0.22 % plus spread. On cost alone, DIY could be cheaper. The finding title claims both; only tax is shown.
- **Legal citation out of date.** The Income-tax Act 2025 has been in force since 1-Apr-2026, per the repo's own `indian-instruments-and-tax.md` line 20. Two search summaries (incometaxindia.gov.in Schedule VII page, 403 on direct fetch; Infosys MF declaration template) say mutual-fund exemption now sits in **Schedule VII, Table Sl. No. 20** ("A Mutual Fund registered under the Securities and Exchange Board of India Act, 1992 … Nil" conditions) and **Sl. No. 21**, operated through section 11. Status NOT VERIFIED (primary page 403). Citing s.10(23D) of the 1961 Act as current law is outdated.

### EVQ-8: IIM-A library as a pinned, manually imported evidence panel. **CONFIRMED**

- **Main page, verbatim:** "The returns and the break-points are recalculated from the beginning of the period each time we update the results. The values may undergo a change if CMIE revises its database retrospectively." VERIFIED.
- **FAQ, verbatim:** "In a new release, CMIE might add a company that was omitted in an earlier release, and it might also correct errors (usually in market capitalization)". VERIFIED.
- **Licence.** The page contains no "licen", "copyright", "commercial", "permission" or "redistribut" text (grep of the fetched HTML). `faculty.iima.ac.in/robots.txt` returns **404** (re-probed). The citation text is present. VERIFIED.
- **Extra support for pinning.** A search summary of the original 2013 working paper (SSRN 2334482, NOT VERIFIED) reports, for 1993–2013, HML of about **15.3 %/yr** and SMB "nearly 0 %". The current release gives far lower numbers over overlapping years. This is consistent with the vintage drift the site warns about, and it strengthens the "pin release + sha256" rule.
- **Missing from the report.** The underlying data are CMIE Prowess, a commercial database. Redistribution limits on the derived files are therefore doubly uncertain.

### EVQ-9: Factor timing lacks Indian OOS support. **WEAKENED**

- **Raju (2025), SSRN 5513940.** Two independent search summaries return the same abstract wording: "Predictive regressions and out-of-sample tests indicate limited timing ability, with only momentum at the 12-month horizon showing significance and forecast-error gains below economic thresholds." The sample is 2004–2025 from the Invespar factor library, dated 21-Sep-2025. The wording is confirmed via search; SSRN was not opened directly, so it stays NOT VERIFIED primary.
- **McLean & Pontiff (2016, *JF* 71:5–32).** Search confirms the abstract phrase "Portfolio returns are 26% lower out-of-sample and 58% lower post-publication." The report omits that this is **US** data (97 predictors), gross of trading costs. It is not Indian evidence.
- **Why weakened.**
  - The finding is an absence claim built on one abstract.
  - Raju itself finds 12-month momentum timing *significant*, though below economic thresholds.
  - Search also surfaced Sahi, "Regime-Dependent Price Formation in Indian Equities" (SSRN 7017321, via search, NOT VERIFIED). It reports regime-conditional momentum ICs with an out-of-sample Newey-West t of 3.03.

  For value, quality, low-vol and size timing, "abstain" is well supported. For "factor timing" in general, the claim is broader than the evidence.

### EVQ-10: Quality premium in India is contested. **WEAKENED**

- **Emerald paper.** Kaur, Seth & Singh, *Managerial Finance* 50(9):1662–1680 (2024), https://emerald.com/insight/content/doi/10.1108/mf-02-2023-0112/full/html (WebFetch, 2026-10-15). The abstract supports "quality-only strategies showed limited effectiveness". It **also** says a "quality-minus-junk (QMJ) long/short strategy" produced significantly positive returns, and that "a strategy combining value and quality investing generated positive and significant alphas as well as a higher Sharpe ratio." The report quotes only the negative half.
- **QMJ study.** George & Kayal, *IIMB Management Review* 38(2), 2026, S0970389626000303 (403 on direct fetch; search summaries only). The summaries say QMJ had a **significant positive** effect over the full period and pre-COVID, and a negative effect post-COVID. The report says "a slightly negative QMJ average". That characterisation is not supported by what I could see: NOT VERIFIED, and probably mis-stated.
- **Omitted positive evidence.**
  - Lalwani (2018), "Quality investing in the Indian stock market", *Managerial Finance* 44(2):127–141, DOI 10.1108/MF-07-2017-0248 (via search). It found Grantham-quality and gross-profitability portfolios earned superior returns after controlling for market, size, value and momentum.
  - The report's own §6.3 Raju & Teli (2022) abstract says quality alpha "survives real-world implementation costs".
- **Factsheet comparison.** "Nifty200 Quality 30 5-yr TR 6.40 vs Nifty 200 8.30" is VERIFIED on the factsheets. It is one 5-year window.
- **Overall.** "Contested" is fair. The evidence presented leans negative more than the literature does.

---

## 3. Important omissions

1. **Free broker-API price route.** Upstox and Angel One (in the sibling wave-1 note) make price-only factors REQUIRES CONFIGURATION, not BLOCKED. The real blocker for a signal is survivorship-free, point-in-time backtest data.
2. **Benchmark choice.** Factor funds should be compared with their parent-universe index fund (Nifty 100/200), not the Nifty 50.
3. **ETF transaction costs and premium/discount.** These are absent from the "live, investable" tier-A evidence.
4. **Income-tax Act 2025.** s.10(23D) should be cited as Schedule VII Sl. No. 20/21 (NOT VERIFIED primary).
5. **Positive Indian quality and low-vol evidence underweighted.** Lalwani 2018; Kaur et al. 2024 (value+quality alphas); Raju & Teli 2022 (costs survived).
6. **1994-11 NA month.** It is unreported, and it explains the gap between the site headline and the recomputed figures (6.61 vs 6.49; −3.71 vs −3.84).
7. **i.i.d. t-statistics.** No HAC/Newey-West adjustment and no multiple-testing correction across factors or funds.
8. **Vintage drift evidence.** Original 2013 working-paper figures (HML about 15 %, SMB about 0 % for 1993–2013, via search) against the current release.
9. **mfapi series may start after fund launch.** The LowVol30 ETF reportedly launched Jul 2017 (NOT VERIFIED), but the data starts Jul 2018.
10. **S&P Dow Jones Indices research.** "An Index Approach to Factor Investing in India" (https://www.spglobal.com/spdji/en/documents/research/research-an-index-approach-to-factor-investing-in-india.pdf, surfaced by search, not read) is not considered.
11. **Harvey, Liu & Zhu t > 3.0 quote.** Not re-checked (search budget exhausted). It remains NOT VERIFIED, as the report labels it.

## 4. Sources (all accessed 2026-10-15)

- IIM-A library main page, data CSVs, drawdown.php and FAQ.php under https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/
- NSE Indices factsheets: https://www.niftyindices.com/Factsheet/ (Factsheet_NIFTY200_Quality30.pdf, Nifty100_LowVolatility30.pdf, Factsheet_Nifty200_Value30.pdf, Nifty50_Value20.pdf, ind_nifty_200.pdf)
- NSE 2017 white paper: https://archives.nseindia.com/content/indices/NIFTY_Multi-Factor_Indices_whitepaper.pdf
- https://www.niftyindices.com/terms-of-use · https://www.screener.in/guides/terms/ · https://zerodha.com/charges/
- https://upstox.com/trading-api/ · https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/
- https://api.mfapi.in/mf/{141596,139455,139367,148456,150487,152859,120716}
- Kaur, Seth & Singh (2024): https://emerald.com/insight/content/doi/10.1108/mf-02-2023-0112/full/html
- Lalwani (2018), via search: https://www.emerald.com/insight/content/doi/10.1108/MF-07-2017-0248/full/html
- George & Kayal (2026), via search: https://www.sciencedirect.com/science/article/pii/S0970389626000303 (403)
- Raju (2025), via search: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5513940
- Sahi, via search: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7017321
- McLean & Pontiff (2016), via search: https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365
- Income-tax Act 2025, Schedule VII, via search: https://www.incometaxindia.gov.in/w/schedule-vii-4 (403); https://www.infosys.com/investors/shareholder-services/documents/tax-forms/mutual-fund.pdf
- Repo: `docs/research/wave1/research-equity-data-alt.md`, `docs/data/source-registry.md` §2.11, `docs/research/indian-instruments-and-tax.md`
