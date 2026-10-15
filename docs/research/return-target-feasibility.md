# Return-Target Feasibility: Evidence Review and Feature Spec

Agents F (Portfolio & Risk Manager) and J (Quant Red Team) · Status: research complete, spec v1 · Date: 2026-10-15
Companion to `docs/product/requirements.md` §3.6, `docs/finance/calculation-methodology.md` and `docs/finance/risk-methodology.md`.

> **What this document is.** It sets the user's stated aim, "at least 20–25 % gain every year or even more", against Indian
> historical evidence. It then specifies a deterministic feature that lets the user run the same test on their own data. It
> neither endorses nor rejects the aim. Everything below is **historical frequency, not probability**. Nothing here is a forecast or
> investment advice.

## Verification legend

| Tag | Meaning |
|---|---|
| **[P]** | Read in this session from the primary source (official factsheet, regulator PDF, S&P report PDF). |
| **[C]** | Computed in this session from an official downloadable series. The method is in §2.2 and Appendix A. Cross-checked against the publisher's own factsheet figures where possible. |
| **[S]** | Secondary source (abstract page, bibliographic database, reputable news). The original was not opened in this session. |
| **NOT VERIFIED** | Could not be confirmed in this session. Must not be used as a number in the app. |

"Today" means 2026-10-15. The equity statistics use daily TRI closes up to **2026-09-30**, the latest factsheet date. Drawdown
episodes use closes up to 2026-10-14.

---

## 0. Executive summary

1. **"20 % p.a." sits far above the long-run record of Indian broad equity indices. The best stretches have exceeded it, but not for long.**
   Nifty 50 TRI has returned 12.12 % p.a. since its 1995 base **[P]** and 11.48 % over the last 10 years **[C]**. For Nifty 500 TRI the
   10-year figure is 12.77 %. For Midcap 150 TRI it is 16.56 %. For Smallcap 250 TRI it is 14.64 % (all **[C]**, to 30-Sep-2026).
   CPI inflation averaged about 4.7 % (10 y) to 5.8 % (15 y) **[S, World Bank]**.
2. **Over short windows, 20 %+ is common. It becomes rare as the horizon grows, and 25 % p.a. disappears.** Rolling month-end
   windows **[C]**:

   | Hit ≥ 20 % p.a. | 1 y | 3 y | 5 y | 10 y | 15 y |
   |---|---|---|---|---|---|
   | Nifty 50 TRI | 34.5 % | 22.3 % | 19.0 % | 5.8 % | 0.0 % |
   | Nifty 500 TRI | 39.6 % | 27.9 % | 22.7 % | 14.1 % | 5.2 % |
   | Nifty Midcap 150 TRI | 43.1 % | 45.5 % | 36.9 % | 18.1 % | 9.0 % |
   | Nifty Smallcap 250 TRI | 42.7 % | 41.0 % | 27.8 % | 5.1 % | 2.6 % |

   **No 10-year or 15-year window of any of these four indices reached 25 % p.a.** The best 10-year window was 23.4 % (Nifty 500).
   The best 15-year window was 23.0 % (Midcap 150).
3. **"Every year" is a much stricter test than "on average".** The share of start months from which **each of the next five
   12-month periods** returned ≥ 20 % was: Nifty 50 1.5 %, Nifty 500 2.9 %, Midcap 150 0.0 %, Smallcap 250 0.0 % **[C]**. The longest
   run of consecutive calendar years ≥ 20 % was 3 (Nifty 50), 5 (Nifty 500), 2 (Midcap 150) and 2 (Smallcap 250) **[C]**.
4. **The windows that did reach the target still had deep drops inside them.** Among 5-year windows that delivered ≥ 20 % p.a., the
   median peak-to-trough fall *inside the window* was −29.8 % (Nifty 50), −24.0 % (Midcap 150) and −31.5 % (Smallcap 250). The worst
   was −59.5 % to −75.6 % **[C]**. Maximum drawdowns: Nifty 50 TRI −59.5 % (2008), Nifty 500 TRI −67.0 % (2000–01), Midcap 150 TRI −72.9 %
   and Smallcap 250 TRI −75.6 % (2008–09, both about **6.4 years** from peak back to that peak) **[C]**.
5. **Active funds have not reliably made up the gap.** SPIVA India Mid-Year 2026 (data to 30-Jun-2026) **[P]**: over 10 years,
   74.0 % of large-cap, 80.5 % of ELSS and 81.7 % of mid/small-cap active funds underperformed their S&P benchmark. No India persistence
   scorecard was found. US and academic evidence says top-quartile status rarely persists.
6. **The popular shortcuts have documented failure rates.** SEBI found that 89 % of individual equity F&O traders lost money in FY22
   **[P]**, 92.8 % over FY22–FY24 with aggregate net losses of ₹1,81,383 crore **[P]**, and 90.9 % in FY25 and 87.7 % in FY26 **[P]**. A sector
   example: Nifty Realty TRI returned **−0.29 % p.a. over 19.8 years** and remains 51 % below its January 2008 peak **[C]**.
7. **Arithmetic, not a forecast.** At 20 % p.a., money multiplies 6.19× in 10 years and 38.3× in 20. At 25 % p.a. it multiplies 9.31× and
   86.7×. At the historical 10-year median of about 14–17 % p.a., the 10-year multiples are about 3.7–4.8×.

**Balanced reading.** A 20 % year is ordinary. One equity year in three, or slightly more, has delivered it. A 20 % *decade* has
been rare and confined to particular start dates. A 25 % decade has not happened on any broad Indian index in the available history.
The highest hit rates came from mid and small caps over 3–5 years. Those same segments carried 70 %+ drawdowns and multi-year recovery
periods. Lower targets, longer horizons and higher contributions are the levers with historical support. Raising risk is the lever with
the worst documented outcomes.

---

## 1. Two readings of "20–25 % every year"

| Reading | Test on a series | Why it matters |
|---|---|---|
| **R1: compound average** | CAGR over horizon H ≥ T | This is what most people mean in practice. Individual years can be negative. |
| **R2: literally every year** | Each consecutive 12-month return within H is ≥ T | This is the literal wording. Its base rate is far lower (§2.3). |

The feature computes both and labels them separately (§4.4.6).

---

## 2. Evidence

### 2.1 Long-run returns by asset class (INR)

**Equity TRIs.** Factsheet figures are **[P]**, read from the NSE Indices monthly factsheets dated 30-Sep-2026. The 10-, 15- and 20-year
figures are **[C]** from daily TRI closes ending 30-Sep-2026. The computed 1-year and 5-year figures match the factsheet to 0.01 pp in
all four indices (Appendix A).

| Index (TRI) | 1 y | 3 y [C] | 5 y | 10 y [C] | 15 y [C] | 20 y [C] | Since inception [P] | Base date [P] | Std dev SI [P] |
|---|---|---|---|---|---|---|---|---|---|
| Nifty 50 | −7.09 % | 6.06 % | 6.38 % | 11.48 % | 12.02 % | 10.97 % | 12.12 % | 03-Nov-1995 | 22.39 % |
| Nifty 500 | −2.03 % | 9.52 % | 9.04 % | 12.77 % | 13.33 % | 11.77 % | 11.89 % | 01-Jan-1995 | 21.91 % |
| Nifty Midcap 150 | 4.57 % | 13.69 % | 14.76 % | 16.56 % | 17.86 % | 15.18 % | 16.75 % | 01-Apr-2005 | 20.77 % |
| Nifty Smallcap 250 | 7.23 % | 13.99 % | 14.51 % | 14.64 % | 15.44 % | 13.31 % | 15.63 % | 01-Apr-2005 | 21.45 % |

- **Backfill caveat [P].** Midcap 150 and Smallcap 250 were **launched on 01-Apr-2016** but have a **base date of 01-Apr-2005**. The
  first 11 years are back-calculated, and nobody could have bought those exact indices then. The feature must flag this (§4.3).
- The "since inception" figures run from each index's own base date. Price-return since-inception figures are lower: Nifty 50 10.61 %,
  Nifty 500 10.23 %, Midcap 150 15.42 %, Smallcap 250 14.32 % **[P]**. The gap is dividends, which is why TRI is mandatory.

**Gold, debt, cash and inflation.**

| Series | 1 y | 3 y | 5 y | 10 y | 15 y | Long run | Source / status |
|---|---|---|---|---|---|---|---|
| Gold, INR (Kotak Gold ETF NAV, split-adjusted) | 27.50 % | 35.41 % | 25.16 % | 15.57 % | 11.21 % | 14.73 % since 30-Jul-2007 | **[C]** from AMFI NAVs through the `mfapi.in` mirror (UNOFFICIAL, see source-registry §2.5). Net of TER. Cross-checked with Quantum Gold ETF: 10 y 15.51 %, 15 y 11.15 %. |
| Nifty Composite G-Sec Index (total return) | 2.81 % | — | 5.66 % | — | — | 7.45 % since 03-Jan-2011 | **[P]** factsheet, 30-Sep-2026 ("Methodology: Total Returns") |
| Nifty 91 Day T-Bill Index | 5.35 % | 6.24 % | — | — | — | 7.11 % since 08-Jan-1993 | **[P]** factsheet, returns as on 30-Sep-2026 |
| CPI inflation, India (annual average, compounded) | 2.40 % (CY2025) | — | 4.96 % (2021–25) | 4.73 % (2016–25) | 5.80 % (2011–25) | 6.51 % (2006–25); 5.92 % (2000–25) | **[S]** World Bank `FP.CPI.TOTL.ZG` (last updated 2026-10-08). This is not the MoSPI series. For in-app use, MoSPI CPI is the source of record (source-registry §2.12). |
| Liquid-fund category returns | — | — | — | — | — | — | **NOT VERIFIED**. No category series was computed. The T-bill index serves as the cash proxy. |

Gold's recent five years (25.2 % p.a.) are a clear **recency trap**. Its 10-year rolling median is 8.1 % and no 10-year window reached
20 % (§2.2). The ETF's maximum drawdown in its own history was −29.8 % (2013–2015) **[C]**.

### 2.2 Rolling-window base rates

**Method [C].**
- **Source.** Daily TRI closes from NSE Indices' historical-data page (`niftyindices.com/reports/historical-data`, "Total Returns
  Index"), retrieved one calendar year at a time on 2026-10-15. The research run was manual and one-off. See §4.3 on data rights; the
  raw data is **not** committed to this repository.
- **Grid.** The last close of each calendar month, through 30-Sep-2026. The series start date serves as the first anchor.
- **Window.** H years = 12·H month-end steps. Return = (V_end/V_start)^(1/H) − 1.
- **Overlap.** All start months are used, so windows overlap. The "independent" figure is ⌊months/(12·H)⌋.

| Index | H | n windows (≈ independent) | ≥ 20 % | ≥ 25 % | < 0 | p10 | Median | p90 | Worst (start → end) | Best |
|---|---|---|---|---|---|---|---|---|---|---|
| **Nifty 50** (from Jun-1999) | 1 | 316 (27) | 34.5 % | 29.4 % | 25.6 % | −11.7 % | 12.2 % | 49.3 % | −51.7 % (Nov-07→Nov-08) | 97.3 % |
| | 3 | 292 (9) | 22.3 % | 16.1 % | 6.5 % | 2.7 % | 13.1 % | 34.4 % | −12.6 % (Mar-00→Mar-03) | 59.5 % |
| | 5 | 268 (5) | 19.0 % | 12.7 % | 0.0 % | 6.5 % | 13.6 % | 26.5 % | 0.2 % (Oct-07→Oct-12) | 46.7 % |
| | 10 | 208 (2) | 5.8 % | 0.0 % | 0.0 % | 9.5 % | 14.0 % | 19.0 % | 6.4 % (Mar-10→Mar-20) | 22.1 % |
| | 15 | 148 (1) | 0.0 % | 0.0 % | 0.0 % | 11.2 % | 13.5 % | 17.6 % | 8.8 % (Dec-07→Dec-22) | 19.3 % |
| **Nifty 500** (from Jan-1999) | 1 | 321 (27) | 39.6 % | 34.0 % | 22.7 % | −11.6 % | 12.6 % | 56.3 % | −56.5 % (Dec-07→Dec-08) | 122.8 % |
| | 3 | 297 (9) | 27.9 % | 18.5 % | 7.7 % | 0.8 % | 14.5 % | 38.6 % | −18.1 % (Feb-00→Feb-03) | 67.9 % |
| | 5 | 273 (5) | 22.7 % | 12.8 % | 0.7 % | 7.3 % | 14.6 % | 31.4 % | −1.2 % (Dec-07→Dec-12) | 50.5 % |
| | 10 | 213 (2) | 14.1 % | 0.0 % | 0.0 % | 9.7 % | 14.8 % | 20.8 % | 6.2 % (Mar-10→Mar-20) | 23.4 % |
| | 15 | 153 (1) | 5.2 % | 0.0 % | 0.0 % | 11.3 % | 14.1 % | 19.0 % | 8.6 % (Dec-07→Dec-22) | 20.8 % |
| **Midcap 150** (from Apr-2005; pre-2016 backfilled) | 1 | 246 (21) | 43.1 % | 35.8 % | 23.2 % | −11.5 % | 13.9 % | 61.9 % | −64.9 % (Dec-07→Dec-08) | 136.6 % |
| | 3 | 222 (7) | 45.5 % | 23.9 % | 9.9 % | 0.6 % | 17.8 % | 30.4 % | −14.8 % (Mar-06→Mar-09) | 37.3 % |
| | 5 | 198 (4) | 36.9 % | 12.1 % | 0.5 % | 5.9 % | 16.9 % | 25.5 % | −1.8 % (Dec-07→Dec-12) | 34.6 % |
| | 10 | 138 (2) | 18.1 % | 0.0 % | 0.0 % | 11.8 % | 16.9 % | 21.1 % | 8.0 % (Mar-10→Mar-20) | 23.2 % |
| | 15 | 78 (1) | 9.0 % | 0.0 % | 0.0 % | 12.7 % | 15.8 % | 19.2 % | 10.6 % (Dec-07→Dec-22) | 23.0 % |
| **Smallcap 250** (from Apr-2005; pre-2016 backfilled) | 1 | 246 (21) | 42.7 % | 39.4 % | 34.6 % | −19.2 % | 9.6 % | 76.0 % | −68.6 % (Dec-07→Dec-08) | 146.4 % |
| | 3 | 222 (7) | 41.0 % | 23.9 % | 17.1 % | −5.1 % | 17.0 % | 30.7 % | −16.1 % (Mar-17→Mar-20) | 42.8 % |
| | 5 | 198 (4) | 27.8 % | 12.1 % | 7.6 % | 1.0 % | 13.8 % | 25.6 % | −6.0 % (Dec-07→Dec-12) | 37.7 % |
| | 10 | 138 (2) | 5.1 % | 0.0 % | 0.0 % | 8.5 % | 14.6 % | 18.1 % | 3.2 % (Mar-10→Mar-20) | 21.6 % |
| | 15 | 78 (1) | 2.6 % | 0.0 % | 0.0 % | 9.8 % | 13.0 % | 16.9 % | 7.3 % (Dec-07→Dec-22) | 20.9 % |
| **Gold** (Kotak Gold ETF NAV, from Jul-2007) | 1 | 219 | 37.9 % | — | 21.9 % | — | 13.9 % | — | −16.8 % | 97.7 % |
| | 3 | 195 | 24.1 % | — | 12.8 % | — | 11.7 % | — | −8.4 % | 40.5 % |
| | 5 | 171 | 10.5 % | — | 11.7 % | — | 10.9 % | — | −2.9 % | 27.0 % |
| | 10 | 111 | 0.0 % | — | 0.0 % | — | 8.1 % | — | 3.8 % | 18.6 % |

Other base rates **[C]**:
- **Below about 6 % nominal**, roughly the long-run CPI, over **5 years**: Nifty 50 7.8 %, Nifty 500 8.1 %, Midcap 150 10.1 %,
  Smallcap 250 20.2 % of windows. Over **10 years**, Smallcap 250 still had 4.3 % of windows below 6 %. The other three had none.
- **Calendar years ≥ 20 %**: Nifty 50 10 of 26 (2000–2025), Nifty 500 11 of 26, Midcap 150 11 of 20, Smallcap 250 10 of 20.
  **Negative calendar years**: 5 of 26, 5 of 26, 4 of 20 and 7 of 20 respectively.
- **Published rolling-return studies** from NSE or AMFI giving ≥ 20 % frequencies were not found in this session. NSE's "25 Years
  Journey of Nifty 50" (Jan 2022) was located by search but not opened (**NOT VERIFIED**). The figures above are therefore computed.

### 2.3 "Every year" (reading R2) and anchor sensitivity [C]

| Index | Every 12 m in 2 consecutive yrs ≥ 20 % | … 3 yrs | … 5 yrs | Longest calendar-year streak ≥ 20 % |
|---|---|---|---|---|
| Nifty 50 | 11.2 % | 6.8 % | 1.5 % | 3 (2005–2007) |
| Nifty 500 | 15.2 % | 9.8 % | 2.9 % | 5 |
| Midcap 150 | 12.4 % | 0.0 % | 0.0 % | 2 |
| Smallcap 250 | 12.8 % | 0.0 % | 0.0 % | 2 |

**How fragile these frequencies are.** The windows can instead be cut into **non-overlapping** blocks. With 5-year blocks, the hit
rate for ≥ 20 % depends on which start month is chosen. Across the 60 possible anchors it ranges from **0 % to 40 %** (Nifty 50),
**0 % to 60 %** (Nifty 500), **0 % to 100 %** (Midcap 150) and **0 % to 67 %** (Smallcap 250), with only 3–5 blocks each. For 10-year
blocks it ranges from 0 % to 50–100 %, with only 1–2 blocks. **A single headline percentage overstates how much is known.** The feature
must show this range (§4.4.5).

### 2.4 Drawdowns and recovery [C]

Daily TRI closes. Episodes with a peak-to-trough fall of 20 % or more. "Recovery" means the first close at or above the prior peak.

| Index | Peak | Trough | Fall | Recovered | Peak→recovery | Trough→recovery |
|---|---|---|---|---|---|---|
| Nifty 50 | 11-Feb-2000 | 21-Sep-2001 | −50.2 % | 01-Dec-2003 | 3.8 y | 2.2 y |
| | 08-Jan-2008 | 27-Oct-2008 | **−59.5 %** | 01-Oct-2010 | 2.7 y | 1.9 y |
| | 05-Nov-2010 | 20-Dec-2011 | −27.2 % | 15-May-2013 | 2.5 y | 1.4 y |
| | 03-Mar-2015 | 25-Feb-2016 | −21.7 % | 02-Sep-2016 | 1.5 y | 0.5 y |
| | 14-Jan-2020 | 23-Mar-2020 | −38.3 % | 06-Nov-2020 | 0.8 y | 0.6 y |
| Nifty 500 | 21-Feb-2000 | 21-Sep-2001 | **−67.0 %** | 01-Jan-2004 | 3.9 y | 2.3 y |
| | 04-Jan-2008 | 27-Oct-2008 | −63.7 % | 27-Mar-2014 | **6.2 y** | 5.4 y |
| | 17-Jan-2020 | 23-Mar-2020 | −38.1 % | 06-Nov-2020 | 0.8 y | 0.6 y |
| Midcap 150 | 07-Jan-2008 | 09-Mar-2009 | **−72.9 %** | 16-May-2014 | **6.4 y** | 5.2 y |
| | 08-Jan-2018 | 23-Mar-2020 | −43.1 % | 23-Nov-2020 | 2.9 y | 0.7 y |
| | 24-Sep-2024 | 28-Feb-2025 | −20.9 % | 12-Nov-2025 | 1.1 y | 0.7 y |
| Smallcap 250 | 02-Jan-2008 | 09-Mar-2009 | **−75.6 %** | 05-Jun-2014 | **6.4 y** | 5.2 y |
| | 15-Jan-2018 | 24-Mar-2020 | −59.8 % | 03-May-2021 | 3.3 y | 1.1 y |
| | 17-Jan-2022 | 20-Jun-2022 | −26.6 % | 15-Jun-2023 | 1.4 y | 1.0 y |
| | 23-Sep-2024 | 03-Mar-2025 | −26.0 % | 26-Aug-2026 | 1.9 y | 1.5 y |

Omitted for brevity: the other episodes of −20 % to −38 % (2004, 2006, 2015–16 and Midcap 2021–22). Each recovered within 1.4 years of
its peak.

**Drawdowns inside windows that met the target [C].** Peak-to-trough on daily data within each rolling window:

| Index | H, T | Median in-window MDD (all windows) | Median in-window MDD (windows that hit T) | Worst in a window that hit T |
|---|---|---|---|---|
| Nifty 50 | 5 y, 20 % | −38.3 % | −29.8 % | −59.5 % |
| Nifty 500 | 5 y, 20 % | −38.1 % | −32.4 % | −63.7 % |
| Midcap 150 | 5 y, 20 % | −39.1 % | −24.0 % | −72.9 % |
| Smallcap 250 | 5 y, 20 % | −43.5 % | −31.5 % | −75.6 % |
| Nifty 50 | 1 y, 20 % | −15.1 % | −13.0 % | −36.1 % |

**Hitting 20 % has historically meant sitting through a fall of a quarter to a third of the portfolio, at minimum.**

### 2.5 Concentrated sector bets [C]

| Index (TRI) | Since start | 10 y | 5 y | Max drawdown | Recovery |
|---|---|---|---|---|---|
| Nifty Realty (from 29-Dec-2006) | **−0.29 % p.a. over 19.8 y** | 15.85 % | 10.91 % | **−92.8 %** (14-Jan-2008 → 25-Feb-2016) | **Not recovered**; still −51.3 % from the 2008 peak |
| Nifty PSU Bank (from Jan-2005) | 9.77 % | 10.54 % | 27.73 % | −77.5 % (05-Nov-2010 → 19-May-2020) | 12.8 y peak→recovery (05-Sep-2023) |
| Nifty IT (from Jan-2005) | 12.56 % | 12.65 % | −2.63 % | −65.2 % (2007–09) | Currently −42.0 % from Dec-2024 (ongoing) |

Over 1-year windows, PSU Bank hit ≥ 20 % in 45.6 % of windows yet was negative in 39.6 % of them. Realty was negative in 53.7 % of
1-year windows and 37.4 % of 5-year windows. **A high hit rate and a high loss rate often belong to the same series.** The feature must
always show both together.

### 2.6 Active funds versus index: SPIVA India [P]

**Latest: SPIVA India Mid-Year 2026, data as of 30-Jun-2026** (published 17-Sep-2026 per the S&P library listing **[S]**).
Report 1a, percentage of funds that underperformed their benchmark:

| Category (benchmark) | YTD | 1 y | 3 y | 5 y | 10 y |
|---|---|---|---|---|---|
| Large-cap (S&P India LargeMidCap) | 84.85 % | 78.79 % | 80.00 % | 84.85 % | 74.03 % |
| ELSS (S&P India BMI) | 55.26 % | 60.00 % | 64.10 % | 70.73 % | 80.49 % |
| Mid/small-cap (S&P India SmallCap) | 67.19 % | 15.00 % | 52.83 % | 54.90 % | 81.67 % |
| Composite bond (iBoxx ALBI India) | 67.63 % | 29.29 % | 75.36 % | 75.54 % | 92.65 % |
| Government bond (iBoxx ALBI India) | 59.26 % | 77.78 % | 80.00 % | 91.30 % | 75.00 % |

**Previous: SPIVA India Year-End 2025, data as of 31-Dec-2025:**

| Category | 1 y | 3 y | 5 y | 10 y | 10 y risk-adjusted (Report 1b) |
|---|---|---|---|---|---|
| Large-cap | 75.00 % | 74.19 % | 84.38 % | 76.29 % | 78.35 % |
| ELSS | 69.23 % | 55.00 % | 58.54 % | 82.93 % | 85.37 % |
| Mid/small-cap | 12.07 % | 41.51 % | 46.00 % | 79.03 % | 35.48 % |

Notes:
- The YE-2025 scorecard notes that active mid/small-cap funds had "their best relative results since 2014" in 2025. That result
  reversed in H1 2026, when 67 % underperformed. S&P links this to small caps beating large caps. **Short-horizon outperformance is
  regime-dependent.**
- 10-year quartile breakpoints, YE-2025 Report 5 (annualised, net of fees): the top-quartile threshold was 14.87 % for large-cap,
  14.79 % for ELSS and 16.35 % for mid/small-cap. **Even top-quartile active funds compounded at about 15–16 % over 2016–2025, not 20 %.**
- Benchmarks changed at Mid-Year 2024, from S&P BSE to S&P India indices. Older third-party SPIVA figures are therefore not comparable.

### 2.7 Persistence of fund performance

- **India: no S&P Persistence Scorecard for India was found** in this session. It may not exist (**NOT VERIFIED**). No India-specific
  persistence number is used.
- **Carhart (1997), *Journal of Finance* 52(1):57–82 [S, abstract].** In a survivor-bias-free sample, common factors and expenses
  "almost completely explain" persistence. The only significant persistence left is "strong underperformance by the worst-return
  mutual funds".
- **S&P U.S. Persistence Scorecard Year-End 2025.** Search summaries said that only 0.46 % of US domestic equity funds in the top quartile
  in 2021 stayed there through 2025. **NOT VERIFIED** (the PDF was not opened). Treat it as directional only.
- **Implication for the app.** Past top-quartile rank must not be presented as evidence that a fund can deliver the target.

### 2.8 Survivorship

- **SPIVA survivorship, Report 2 [P].** Over the 10 years to 30-Jun-2026, **19.5 % of large-cap, 29.3 % of ELSS and 10.0 % of
  mid/small-cap** active funds were merged or liquidated (survivorship 80.52 %, 70.73 %, 90.00 %). Across all categories, 25.7 % failed
  to survive (74.29 % survived). The YE-2025 figure was 27 % failing across all categories.
- **Effect on apparent category returns.** A "category average" computed only from schemes alive today drops the merged losers, which
  biases it upward. **Elton, Gruber & Blake (1996), *RFS* 9(4):1097–1120 [S]** is widely cited as estimating about 0.9 % p.a. for US
  funds. That figure is quoted from secondary sources (**NOT VERIFIED** against Table 2). No India-specific estimate was verified.
  A 2026 arXiv preprint on survivorship in Nifty Smallcap 250 (arXiv:2603.19380) exists. It is unreviewed and **NOT VERIFIED**, and is
  not used.
- **Index-level analogue.** Back-calculated index history (§2.1) is a form of survivorship and look-back construction.
- **Single stocks: Bessembinder (2018), *JFE* 129(3) [S, abstract].** Four of every seven US common stocks since 1926 had lifetime
  buy-and-hold returns below one-month T-bills. About 4 % of firms accounted for all net wealth creation. Studying today's winners
  ("what if I had bought X") is pure survivorship.

### 2.9 Common ways people chase 20 %+, and the evidence

| Route | Evidence | Status |
|---|---|---|
| **Small and mid caps** | Highest 3–5 y hit rates (§2.2), but max drawdowns of −72.9 % and −75.6 %, 6.4-year recoveries, and Smallcap 5 y negative in 7.6 % of windows. | **[C]** |
| **Sector / thematic** | Realty −0.29 % p.a. over 19.8 y. PSU Bank needed 12.8 y to recover. IT 5 y −2.63 % (§2.5). | **[C]** |
| **Concentrated stocks** | Skewness: most stocks underperform T-bills, and a few create all the wealth (Bessembinder). | **[S]** |
| **F&O / leverage** | **FY22** (SEBI, 25-Jan-2023): 89 % of individual traders lost money, with an average loss of ₹1.1 lakh. Active traders' average loss was over 15× the average profit of profit-makers (excluding outliers). **FY22–FY24** (SEBI PR No. 22/2024, 23-Sep-2024, and study): 1.13 crore unique individuals had a combined net loss of **₹1,81,383 crore**. **92.8 %** were net loss-makers and only 7.2 % profited. Only 1 % earned over ₹1 lakh after costs. FY24 net loss was ₹74,812 crore. More than 75 % of loss-makers kept trading. **FY25–FY26** (SEBI study, 20-Aug-2026): **90.9 %** loss-makers in FY25, with a net loss revised to about ₹1.12 lakh crore. **87.7 %** in FY26, net loss ₹91,685 crore, average loss per loss-maker ₹1.47 lakh. Options were 92 % of losses. 99 % of FPI and proprietary profits came from algo entities. | **[P]** |
| | SEBI July-2025 study (FY25 ₹1,05,603 crore, "over 91 %") is known only via Business Standard. It was later revised by the Aug-2026 study. | **[S]** |
| **PMS / AIF** | APMI publishes strategy returns. No survivorship-adjusted systematic study was reviewed. PMS minimum ticket ₹50 lakh: not checked this session. | **NOT VERIFIED** |
| **Crypto** | No authoritative INR return series or regulator outcome study was reviewed. Regulatory and tax status is outside this document. | **NOT VERIFIED** |
| **Recency / momentum chasing** | Gold 5 y = 25.2 % p.a. vs 10 y rolling median 8.1 %. Midcap's best 5 y window (34.6 %) started at the Mar-2020 crash low. | **[C]** |
| **Market timing to "boost" returns** | Goyal & Welch (2008, *RFS* 21(4):1455–1508): commonly proposed predictors "predicted poorly both in-sample and out-of-sample"; most models are "unstable or even spurious". The follow-up (Goyal, Welch & Zafirov) remains "disappointing". | **[S]** |

### 2.10 What compounding at 20–25 % implies (arithmetic, not forecast)

Wealth multiple = (1 + r)^n.

| Rate p.a. | 5 y | 10 y | 15 y | 20 y |
|---|---|---|---|---|
| 12 % | 1.76× | 3.11× | 5.47× | 9.65× |
| 15 % | 2.01× | 4.05× | 8.14× | 16.37× |
| 20 % | 2.49× | 6.19× | 15.41× | 38.34× |
| 25 % | 3.05× | 9.31× | 28.42× | 86.74× |

Against history **[C]**: the best realised 10-year windows were 22.1 % (Nifty 50), 23.4 % (Nifty 500), 23.2 % (Midcap 150) and 21.6 %
(Smallcap 250). The best 15-year windows were 19.3 %, 20.8 %, 23.0 % and 20.9 %. A 25 % p.a. plan over 10+ years therefore assumes an
outcome **better than the best window ever observed** on these indices. At 20 % over 15 years it assumes the top 0–9 % of overlapping
windows, which amounts to about one independent period.

---

## 3. Red team: how this app could accidentally encourage reckless risk-taking

| # | Failure mode | How it happens in *this* app | Guardrail (normative) |
|---|---|---|---|
| RT-1 | **Target anchoring** | The user enters 20 %. The UI then shows "options that meet your target". | The target is an *aspiration* (requirements §3.6). No screen filters, sorts or ranks instruments by hit rate. The feasibility view shows one instrument or category at a time, or a fixed-order comparison table. |
| RT-2 | **Hit-rate shopping** | The user tries categories until one shows 45 % (Midcap, 3 y). | Every hit rate is shown **beside** the loss rate, worst window, median in-window drawdown and `n_eff`. None of these can be hidden. There are no "best" badges and no colour ranking. |
| RT-3 | **Horizon shopping** | The user shortens H until the hit rate looks good. | The horizon comes from the user's withdrawal date (requirements §3.2) and is locked for the headline. Other horizons appear only in a secondary "how it varies with horizon" table that always shows 1, 3, 5, 10 and 15 y together. |
| RT-4 | **Recency bias** | The trailing 5 y (gold 25 %, midcap 2020–25) looks like the norm. | Show the latest trailing-window percentile rank within its own history. If it is ≥ p90, show: "The most recent H-year period was among the strongest 10 % in this history." |
| RT-5 | **Short-window extrapolation** | A 6-month return is annualised to 40 %. | Rule A1 (calc §2.3): H < 1 y is refused for target testing. |
| RT-6 | **Leverage and derivatives** | The user asks how to reach 25 % with options. | F&O, leveraged and inverse products are **not accepted** as instruments. If selected, the view shows the SEBI study figures (§2.9) with citations. No option backtests. |
| RT-7 | **Single-stock survivorship** | The user tests a stock that has already multiplied. | Single stocks are excluded in v1. If added later, a mandatory banner says: "You are analysing a survivor chosen after the fact. Most stocks underperformed T-bills over their lifetime (Bessembinder 2018)." |
| RT-8 | **Backfilled history** | Midcap 150 pre-2016 looks investable. | Each window is tagged `backfilled` if its start falls before the index launch date. The view shows statistics both with and without backfilled windows. |
| RT-9 | **Fund survivorship** | A category average built from today's schemes. | The engine refuses to build category series from surviving schemes. Category = benchmark TRI only. Fund-level views carry a "survivor" banner and the SPIVA survivorship figures. |
| RT-10 | **Probability language** | "72 % chance of success". | Banned vocabulary (§4.6). The label is always "historical frequency (overlapping windows)". |
| RT-11 | **Ignoring the path** | A 20 % CAGR hides a −60 % trough. | Show in-window drawdown percentiles in % **and in ₹ on the user's amount**, e.g. "In the median window that met 20 %, ₹10,00,000 would have fallen to ₹7,02,000 at its worst." |
| RT-12 | **Objective mismatch** | 20 % aim combined with a 3-month horizon or capital preservation. | Constraint conflict (requirements §3.6). Objective E requires an entered loss budget. If the median in-window MDD exceeds the loss budget, show "History suggests this path exceeded your stated loss limit in X of N windows." |
| RT-13 | **Gamification** | Progress bars, green ticks, "on track!". | None of these in this view. Neutral typography. No celebratory states. |
| RT-14 | **Precision theatre** | "Historical frequency: 36.87 %". | Percentages are rounded to whole numbers and accompanied by counts ("73 of 198 windows"). |
| RT-15 | **Gross vs net** | Index TRI ignores TER, tracking error and tax. | A fixed caveat. When an index-fund NAV series is used, the label says "net of TER". The after-tax view comes from calc §2.12. |
| RT-16 | **Raising risk as the only lever** | The user infers "I need more risk". | A **Levers panel** with deterministic arithmetic (§4.4.7): the SIP or amount, horizon or target corpus needed at the user-selected historical percentile. No product suggestions. |
| RT-17 | **Data-rights breach** | Automating NSE Indices downloads. | §4.3: user-imported files or permitted sources only. |

---

## 4. Feature spec: "Return-Target Feasibility"

### 4.1 Purpose and non-goals

**Purpose.** For a given target return T (p.a.), horizon H and a single return series, report the **historical frequency** with which
T was met, the distribution of outcomes, the losses and drawdowns along the way, and how uncertain those frequencies are.

**Non-goals.**
- No probability of success.
- No forecast or Monte Carlo in v1.
- No ranking or screening by hit rate.
- No portfolio optimisation toward T.
- No leveraged or derivative instruments.

### 4.2 Inputs

| Field | Type | Validation |
|---|---|---|
| `target_rate` | Decimal p.a. (e.g. `0.20`) | −0.50 < T ≤ 1.00. Above 0.30, show a confirmation note quoting the §2.10 table. |
| `horizon_years` | integer H ∈ {1,…,20} | H ≥ 1 (Rule A1). The default comes from the withdrawal date, rounded down to whole years. |
| `series_id` | an eligible series (§4.3) | Must pass the gates in §4.5. |
| `mode` | `CAGR` (R1) or `EVERY_YEAR` (R2) | Default `CAGR`. Both are shown when space permits. |
| `amount_inr` | Decimal, optional | For ₹ translation of drawdowns and outcomes. |
| `loss_budget` | Decimal fraction, optional | Required for objective E (requirements §3.6). |
| `as_of` | date | Defaults to the last complete month-end of the series. Every computation uses data ≤ `as_of` only (point-in-time). |
| `include_backfilled` | bool | Default `true`, with both variants displayed (RT-8). |

### 4.3 Eligible series and data provenance

1. **Total-return series only.** Index TRI, or the growth-option NAV of an index fund or ETF. IDCW NAVs are converted per calc §2.7.
   Price indices are rejected.
2. **Sources.**
   - (a) AMFI NAV history (v1 live source) for index funds and ETFs. These are net of TER and carry tracking error.
   - (b) **A user-imported CSV of TRI closes** that the user downloaded manually from NSE Indices.
   - (c) MoSPI CPI and RBI or index T-bill data, for comparison lines.

   **The app must not automate NSE or NSE Indices retrieval.** Source-registry §2.11 records NSE's Terms of Use, which prohibit automated
   collection, storage without permission, and use "for any gaming, virtual trading or simulation activities". Whether the
   niftyindices.com terms are identical is **NOT VERIFIED**; treat them the same until checked. Imported files are stored only in the
   user's local database, with `source`, `retrieved_at` and a file hash.
3. **Metadata per series.**
   - `instrument_kind` ∈ {index_tri, fund_nav, etf_nav}
   - `inception_date`
   - `launch_date`, for backfill tagging
   - `net_of_fees` (bool)
   - `currency = INR`
   - `source`, `retrieved_at`
4. **Point-in-time.** Observations are used only if `obs_date ≤ as_of`. Revisions are stored as new versions, not overwrites.
5. **Excluded.** F&O, leveraged and inverse products, single stocks (v1), crypto, PMS and AIF (no verifiable series), and "category
   averages" assembled from surviving schemes (RT-9).

### 4.4 Computation (exact)

All arithmetic on index levels runs at the float boundary (risk-methodology preamble). The hit test (§4.4.2) is done in `Decimal`.

**4.4.1 Month-end grid.**
- `G = [g_0, …, g_{M}]`, where `g_k` is the last observation on or before the last calendar day of month k.
- `g_0` is the series' first observation, which may fall mid-month.
- A month with no observation in its last 7 calendar days marks the grid point `suspect`. If more than 2 % of grid points are suspect,
  the series is rejected (consistent with risk §1).
- The last grid point is the last *complete* month-end ≤ `as_of`.

**4.4.2 Rolling windows (overlapping).** For H years, `m = 12H` steps.

For each `i ∈ [0, M − m]`:

```
ratio_i  = V(g_{i+m}) / V(g_i)
cagr_i   = ratio_i^(1/H) − 1                                  # nominal-H exponent (see note)
hit_i    = ratio_i ≥ (1 + T)^H                                 # evaluated in Decimal, ≥ inclusive
loss_i   = ratio_i < 1                                          # strictly; ratio = 1 is "flat", not loss
below_i  = ratio_i < Π_{months in window}(1 + cpi_monthly)      # optional, when CPI is aligned
```

`N = M − m + 1` windows.

Note on the exponent: the nominal-H exponent is used because the question asked is "T p.a. over H years". Calc §2.4 (Actual/365) differs
by under 0.01 pp for month-end grids. The engine exposes `year_basis ∈ {nominal, act365}` (default `nominal`) and records it in the
output.

**4.4.3 Outputs per (series, H, T).**
- `hit_count`, `N`, and `hit_freq = hit_count / N`
- `loss_count` and `loss_freq`
- `flat_count`
- `below_inflation_freq`, if computed
- Percentiles of `cagr_i` at p5, p10, p25, p50, p75, p90 and p95. Use **linear interpolation between order statistics (Hyndman–Fan
  type 7 = Excel `PERCENTILE.INC`)**: `k = (N − 1)·p`, `x = s_⌊k⌋ + (k − ⌊k⌋)(s_⌈k⌉ − s_⌊k⌋)`.
- `worst` and `best`, each with start and end dates.

**4.4.4 Path risk inside each window** (on the daily series between `g_i` and `g_{i+m}`, inclusive):
- `mdd_i = min_t (V_t / max_{s≤t, s≥g_i} V_s − 1)`
- Output the percentiles of `mdd_i` over all windows and over the hit windows only, plus `min(mdd_i | hit_i)`.
- Output the longest underwater spell inside a hit window, in months.
- For ₹ display: `amount × (1 + mdd)`.
- The full-history MDD and recovery dates follow risk-methodology §3. Ties are resolved by the earliest peak. Recovery is the first
  close **≥** the peak.

**4.4.5 Honesty statistics (mandatory, displayed).**
- `n_eff = ⌊M / m⌋`, the number of non-overlapping windows.
- **Anchor range.** For each anchor `a ∈ [0, m − 1]`, take non-overlapping windows starting at `a, a + m, a + 2m, …` with
  `start + m ≤ M`, and compute their hit fraction `f_a`. Report `[min_a f_a, max_a f_a]` and the block count range.
- `backfilled_share`: the share of windows whose start is before `launch_date`. Show statistics with and without those windows.
- `recency_rank`: the percentile of the latest window's CAGR among all `cagr_i` (RT-4).

**4.4.6 Every-year mode (R2).** For each i with `i + m ≤ M`, set `all_years_i = ∧_{k=0}^{H−1} [V(g_{i+12(k+1)}) / V(g_{i+12k}) ≥ 1 + T]`.
Report the count and the frequency. It is labelled "every one of the H consecutive 12-month periods met T". Also report the longest
calendar-year streak ≥ T.

**4.4.7 Levers panel (deterministic arithmetic, no history claims).**
- Required lump sum for a goal: `PV = goal / (1 + r)^H`.
- Required monthly SIP: `goal × i / ((1 + i)^n − 1)` with `i = (1 + r)^(1/12) − 1` and n = 12H, payment at end of month.
- The panel shows r at **T** and at the series' historical **p25 and p50** of `cagr_i`, each labelled with its percentile.
- It never shows r above the historical p90.

### 4.5 Minimum data requirements (gates)

| Condition | Behaviour |
|---|---|
| Series span < H + 1 years | `InsufficientData`. No numbers. |
| `n_eff` < 2 | Refuse frequencies. Show only "In this history there is ⌊M/m⌋ independent H-year period(s); the realised CAGR was x %." |
| 2 ≤ `n_eff` < 5 | Show **counts only** ("hit in 73 of 198 overlapping windows ≈ 4 independent periods"), the anchor range, and a **LOW EVIDENCE** label. No percentage headline. |
| `n_eff` ≥ 5 | Percentages allowed. The count and the anchor range are still shown. |
| The series contains no drawdown ≥ 20 % | Banner: "This history contains no major equity bear market; results may understate risk." |
| The series starts after 2009-03-31 | Banner: "History begins after the 2008–09 crash." |
| `net_of_fees = false` (index TRI) | Caveat RT-15. |
| Suspect grid points > 2 % | Reject the series. |
| `amount_inr` missing | ₹ lines are omitted. % figures are still shown. |

### 4.6 Labels and wording

- **Allowed:** "historical frequency", "in X of N overlapping H-year windows", "worst/best observed window", "median observed", "about
  k independent periods", "met / did not meet the target".
- **Forbidden** (lint-tested string list): "probability", "chance", "likely to", "expected return", "success rate", "guaranteed",
  "safe", "will achieve", "on track", "recommended", "best fund".
- **Fixed caveats** (always shown, collapsed only after first view):
  1. Overlapping windows share most of their months. N overlapping windows contain only about `n_eff` independent observations, and
     the frequency can swing widely with the start month (anchor range shown).
  2. The past regime may not repeat. Interest rates, valuations, inflation, market structure and taxes change. Return predictability
     evidence is weak (Goyal & Welch 2008).
  3. Survivorship and backfill. Indices launched after their base date contain back-calculated history. Funds that closed or merged are
     missing from fund histories.
  4. Small samples. Ten-year statistics in India rest on one or two independent decades.
  5. Index TRIs exclude fees, tracking error, taxes and your own timing.
  6. This is not investment advice and not a forecast.

### 4.7 Output layout (summary)

1. **Headline**, at the user's H.

   > "Over [series], from [start] to [as_of], [T] p.a. or more over [H] years was met in **73 of 198** overlapping windows (≈ 4
   > independent periods; anchor range 0–100 %). Money was lost in 1 of 198. In the windows that met it, the median fall along the
   > way was −24 % (₹10,00,000 → ₹7,60,000)."

2. **Distribution strip:** p5 to p95 of CAGR with markers at T, CPI and the T-bill index.
3. **Horizon table:** fixed H = 1, 3, 5, 10 and 15. Columns are hit, loss, median, worst and `n_eff`.
4. **Every-year (R2) line.**
5. **Path-risk panel:** MDD episodes table and the ₹ translation.
6. **Levers panel** (§4.4.7).
7. **Evidence footer:** source, retrieval timestamp, `year_basis`, grid, and backfill share.

### 4.8 Edge cases

| Case | Handling |
|---|---|
| `V_start ≤ 0` or a missing value | Series rejected. TRI and NAV must be > 0. |
| `ratio = (1+T)^H` exactly | Hit (inclusive ≥), evaluated in Decimal. See fixture F-2. |
| `ratio = 1` | Counts as `flat`, neither loss nor gain. |
| T ≤ −1 | Rejected. |
| T negative (e.g. "lose no more than 5 % p.a.") | Allowed. The wording becomes "at least −5 % p.a.". |
| H such that m > M | `InsufficientData`. |
| Unit splits or consolidations in an ETF NAV | Detect a jump of ≤ −70 % or ≥ +230 % in one day. If it matches an integer split ratio within 1 %, apply a split adjustment with an audit record. Otherwise reject. (The research run found 1:10 splits in Kotak Gold ETF on 2015-04-15 and 2021-07-23, and a 1:50 split in Quantum Gold ETF on 2021-12-20.) |
| Regular to Direct plan (Direct exists only from 2013) | Do not splice plans. Use one plan's full history and label it. |
| A series that starts in a drawdown | MDD is labelled "within available history" (risk §3). |
| An ongoing drawdown at `as_of` | "≥ n months (ongoing)". |
| CPI base change (2012 → 2024) | Do not splice silently (source-registry §2.12). The inflation comparison is unavailable across a break unless a published linking factor is stored. |
| A daily series with gaps over 7 days | Marked `suspect` (risk §1). |
| `as_of` mid-month | The last grid point is the previous complete month-end. |
| Leap years and 29-Feb | Irrelevant under `nominal` year basis. Under `act365`, use calc §2.4. |

### 4.9 Hand-computable fixtures

**F-1: toy 10-point series, annual spacing (so m = H).** `V = [100, 130, 150, 120, 150, 190, 200, 160, 210, 260]` at t = 0…9, with T = 20 %.

*H = 1 (N = 9).*
- Returns: 30.0000, 15.3846, −20.0000, 25.0000, 26.6667, 5.2632, −20.0000, 31.2500, 23.8095 %.
- Hit (≥ 1.20): t = 0→1, 3→4, 4→5, 7→8, 8→9, giving **5/9**.
- Loss: **2/9**.
- Percentiles (type 7): p10 = −20.0000 %, p50 = 23.8095 %, p90 = 30.2500 %.

*H = 2 (N = 8, threshold ratio 1.44).*

| i | window | ratio | CAGR | hit | loss | in-window MDD |
|---|---|---|---|---|---|---|
| 0 | 100→130→150 | 1.5000 | 22.4745 % | ✔ | | 0 % |
| 1 | 130→150→120 | 0.9231 | −3.9231 % | | ✔ | −20 % |
| 2 | 150→120→150 | 1.0000 | 0.0000 % | | flat | −20 % |
| 3 | 120→150→190 | 1.5833 | 25.8306 % | ✔ | | 0 % |
| 4 | 150→190→200 | 1.3333 | 15.4701 % | | | 0 % |
| 5 | 190→200→160 | 0.8421 | −8.2337 % | | ✔ | −20 % |
| 6 | 200→160→210 | 1.0500 | 2.4695 % | | | −20 % |
| 7 | 160→210→260 | 1.6250 | 27.4755 % | ✔ | | 0 % |

- **Hit 3/8 = 37.5 %, loss 2/8 = 25 %, flat 1/8.**
- Percentiles: p10 = −5.2163 %, p25 = −0.9808 %, p50 = 8.9698 %, p75 = 23.3135 %, p90 = 26.3240 %.
  Worked p50: k = 7 × 0.5 = 3.5, so (2.4695 + 15.4701)/2 = 8.9698 %.
- In-window MDD, all windows: p50 = −10.0000 %. Hit windows: p50 = 0 %.
- `n_eff = ⌊9/2⌋ = 4`. **Anchor 0:** windows 0, 2, 4, 6 give hits 1/4. **Anchor 1:** windows 1, 3, 5, 7 give hits 2/4.
  **Anchor range 25 %–50 %**, which illustrates caveat 1.
- Gate: `n_eff` = 4, so the output is **counts only + LOW EVIDENCE**.

*H = 3 (N = 7, threshold ratio 1.728).*
- Ratios: 1.2000, 1.1538, 1.2667, 1.6667, 1.0667, 1.1053, 1.3000.
- **Hit 0/7**, loss 0/7, median CAGR 6.2659 %, best 18.5631 % (120→200).
- `n_eff = 3`. Anchors 0, 1 and 2 give 0/3, 0/2 and 0/2.

*Every-year mode, H = 2.* Both consecutive 1-year returns must be ≥ 20 %. This holds only at i = 3 (25.0 %, 26.67 %) and i = 7
(31.25 %, 23.81 %), so **2/8**.

*Full-history MDD.*
- −20.0000 %, first episode: peak t = 2 (150), trough t = 3 (120), recovered t = 4 (150 ≥ 150, inclusive).
- The second −20 % episode (t = 6 → 7, recovered t = 8) ties on depth. The earliest peak is reported.

**F-2: inclusive boundary.** `V = [100, 120, 144]`, H = 1, T = 0.20. Both windows give ratio = 1.2 exactly in Decimal, so **hit 2/2**.
A float implementation computing `cagr ≥ 0.2` may fail this test. The test asserts the Decimal ratio path.

**F-3: flat versus loss.** `V = [100, 100, 99]`, H = 1. Window 0 is flat (not a loss). Window 1 is a loss. Expected loss 1/2, flat 1/2.

**F-4: gates.** A series spanning 4 years 11 months with H = 5 gives `InsufficientData`. A 6-year span with H = 5 gives n_eff = 1, so
frequencies are refused.

**F-5: split adjustment.** `[1000, 1010, 101.5, 102]` with a split flag ratio of 10. Adjusted: `[1000, 1010, 1015, 1020]`, with an
audit row.

**F-6: real-data regression (only if the user imports the same NSE Indices file).** For Nifty 50 TRI, grid Jun-1999 to Sep-2026,
H = 5, T = 0.20, the expected result is 51/268 windows hit, loss 0/268, and worst 0.2 % (Oct-2007 → Oct-2012). Tolerance is ±1 window,
to allow for vendor revisions. Do not bundle the data (§4.3).

### 4.10 Tests required

- Unit tests: F-1 to F-5, the percentile method against Excel `PERCENTILE.INC`, and ₹ translation rounding (HALF_EVEN, calc §1.2).
- A property test: the hit frequency is monotone non-increasing in T.
- A property test: an R2 hit implies an R1 hit for the same i and T, so `every_year_count ≤ hit_count`.
- A lint test: the forbidden-word list (§4.6) does not appear in templates.
- A UI contract test: no hit-rate value renders without its loss rate, `n_eff` and anchor range (RT-2).
- A point-in-time test: appending future observations does not change results for a fixed `as_of`.

---

## Appendix A: Reproducibility of the computed evidence

- **Retrieval (2026-10-15).**
  - TRI: `POST https://www.niftyindices.com/BackPage/getTotalReturnIndexString` with body
    `{"cinfo":"{'name':'NIFTY 50','startDate':'01-Jan-YYYY','endDate':'31-Dec-YYYY','indexName':'NIFTY 50'}"}`, one request per calendar
    year. This is the endpoint behind the public historical-data page.
  - Index names: NIFTY 50 (from 30-Jun-1999), NIFTY 500 (from 01-Jan-1999), NIFTY MIDCAP 150 and NIFTY SMALLCAP 250 (from
    01-Apr-2005), NIFTY REALTY (from 29-Dec-2006), NIFTY PSU BANK and NIFTY IT (from 03-Jan-2005).
  - Daily observations up to 14-Oct-2026: Nifty 50 6,789, Nifty 500 6,914, Midcap 150 5,342, Smallcap 250 5,342.
  - This was a single manual research retrieval. It must not be turned into an app adapter (§4.3).
  - Raw files were kept in the session scratchpad only.
- **Cross-check against factsheets (30-Sep-2026) [P vs C].**

  | Index | Factsheet 1 y / 5 y | Computed 1 y / 5 y |
  |---|---|---|
  | Nifty 50 TRI | −7.09 / 6.38 | −7.09 / 6.38 |
  | Nifty 500 TRI | −2.03 / 9.04 | −2.03 / 9.04 |
  | Midcap 150 TRI | 4.57 / 14.76 | 4.57 / 14.76 |
  | Smallcap 250 TRI | 7.23 / 14.51 | 7.23 / 14.51 |

  All four match exactly.
- **Sanity checks.** No conflicting duplicate dates. The largest daily moves are real events: Nifty 50 +17.74 % on 18-May-2009
  (election result), PSU Bank +29.63 % on 25-Oct-2017 (bank recapitalisation announcement), Realty −23.71 % on 24-Oct-2008.
- **Gold.** `https://api.mfapi.in/mf/106193` (Kotak Gold ETF) and `/mf/107693` (Quantum Gold ETF), mirroring AMFI NAVs. Splits were
  detected per §4.8.
- **CPI.** `https://api.worldbank.org/v2/country/IND/indicator/FP.CPI.TOTL.ZG?format=json`. Annual rates were compounded geometrically.

## Sources

Primary, read this session **[P]**:
- NSE Indices factsheets, 30-Sep-2026:
  - Nifty 50: <https://www.niftyindices.com/Factsheet/ind_nifty50.pdf>
  - Nifty 500: <https://www.niftyindices.com/Factsheet/ind_nifty_500.pdf>
  - Nifty Midcap 150: <https://www.niftyindices.com/Factsheet/ind_Nifty_Midcap_150.pdf>
  - Nifty Smallcap 250: <https://www.niftyindices.com/Factsheet/ind_Nifty_Smallcap_250.pdf>
  - T-Bills series: <https://www.niftyindices.com/Factsheet/Factsheet_NIFTY_T-Bills_Indices.pdf>
  - Composite G-Sec: <https://www.niftyindices.com/Factsheet/ind_debt_Nifty_Composite.pdf>
- NSE Indices historical data (TRI): <https://www.niftyindices.com/reports/historical-data>
- S&P DJI, SPIVA India Mid-Year 2026: <https://www.spglobal.com/spdji/en/documents/spiva/spiva-india-scorecard-mid-year-2026.pdf>
- S&P DJI, SPIVA India Year-End 2025: <https://www.spglobal.com/spdji/en/documents/spiva/spiva-india-scorecard-year-end-2025.pdf>
- SEBI study, F&O P&L FY22 (25-Jan-2023): <https://www.sebi.gov.in/reports-and-statistics/research/jan-2023/study-analysis-of-profit-and-loss-of-individual-traders-dealing-in-equity-fando-segment_67525.html> (PDF `sebi_data/attachdocs/jan-2023/1674645296493.pdf`)
- SEBI PR No. 22/2024 (23-Sep-2024): <https://www.sebi.gov.in/media-and-notifications/press-releases/sep-2024/updated-sebi-study-reveals-93-of-individual-traders-incurred-losses-in-equity-fando-between-fy22-and-fy24-aggregate-losses-exceed-1-8-lakh-crores-over-three-years_86906.html>
- SEBI study, FY22–FY24: <https://www.sebi.gov.in/reports-and-statistics/research/sep-2024/study-analysis-of-profits-and-losses-in-the-equity-derivatives-segment-fy22-fy24-_86905.html>
- SEBI study, FY25–FY26 (20-Aug-2026): <https://www.sebi.gov.in/reports-and-statistics/research/aug-2026/study-profitability-of-individual-traders-in-the-equity-derivatives-segment-fy25-fy26-_103835.html>

Computation inputs **[C]**: the NSE Indices TRI series above. AMFI NAVs via `mfapi.in` (unofficial mirror).

Secondary **[S]**:
- World Bank CPI inflation, India: <https://api.worldbank.org/v2/country/IND/indicator/FP.CPI.TOTL.ZG>
- Business Standard on the SEBI July-2025 study: <https://www.business-standard.com/markets/news/net-losses-of-traders-in-fo-widens-in-fy25-sebi-study-125070701221_1.html>
- Carhart (1997): <https://onlinelibrary.wiley.com/doi/full/10.1111/j.1540-6261.1997.tb03808.x>
- Goyal & Welch (2008): <https://econpapers.repec.org/RePEc:oup:rfinst:v:21:y:2008:i:4:p:1455-1508>
- Elton, Gruber & Blake (1996): <https://econpapers.repec.org/RePEc:oup:rfinst:v:9:y:1996:i:4:p:1097-1120>
- Bessembinder (2018): <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2900447>

NOT VERIFIED:
- S&P US Persistence Scorecard YE-2025 figures.
- Any India persistence scorecard.
- PMS and crypto outcome data.
- The NSE "25 Years Journey of Nifty 50" figures.
- arXiv:2603.19380.
- niftyindices.com terms of use.
