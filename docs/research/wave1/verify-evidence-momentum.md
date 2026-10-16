# Adversarial verification: research-evidence-momentum.md

- **Wave:** 1 · **Topic:** evidence-momentum (verification) · **Date:** 2026-10-15 · **Role:** adversarial skeptic. No repo file other than this one was changed.
- **Report checked:** `docs/research/wave1/research-evidence-momentum.md`
- **Method:**
  - The primary PDFs were downloaded once to the session scratchpad (not the repo) and read with `pdftotext`:
    - NSE 2026 white paper
    - NSE 2020 white paper
    - IIMA W.P. 2013-09-05
    - NBER w20439 (Daniel & Moskowitz)
    - NBER w20721 (Novy-Marx & Velikov)
    - Zakamulin 2013 working-paper version of the JAM 2014 paper
  - Abstract pages and terms pages were fetched directly.
  - Every computation was re-run with `python3 -I` (Decimal where the report used Decimal).
  - All URLs were accessed on 2026-10-15.
- **Labels:**
  - **CONFIRMED** means the citation says what the report claims.
  - **WEAKENED** means the citation is real but the claim is overstated, misattributed or incomplete.
  - **REFUTED** means the citation does not support the claim.

---

## 0. Verdict summary

| ID | Report status | Verdict | One-line reason |
|---|---|---|---|
| MOM-1 | VERIFIED | **WEAKENED** | IIMA Table 4, footnote 11 and the SEBI circular all check out. But the *current* IIMA library (release 2025-12) shows WML at only **10.65–10.96 %/yr since 1994**, with a 62 % worst drawdown lasting 5 years. The report quotes only the 2013/2017 vintages (17.0 % / 17.3 %), so "large" is overstated. |
| MOM-2 | VERIFIED | **WEAKENED** | The arithmetic reproduces exactly (+5.59 vs +2.79 pp). But the "~50 % decay" is a point estimate: live-period t ≈ 0.64 on 5 observations. The live excess is statistically indistinguishable from both the backtest and zero. Even the backfilled excess has t ≈ 2.0, below the report's own t > 3 gate. |
| MOM-3 | VERIFIED | **CONFIRMED** (one caveat) | −67.7/−63.7, −70.2/−63.7, −19.47 pp (2009), −14.13 pp (2025) and the "163 %" quote all match. Caveat: Midcap150 Mom 50's max drawdown (−72.5 %) is *shallower* than its parent's (−72.9 %), so "deeper drawdowns" holds for 2 of 3 indices. |
| MOM-4 | NOT VERIFIED | **CONFIRMED** | Mitra 2011 and Huang et al. 2020 quotes match. The Zakamulin wording is a paraphrase: the source says "only marginally better than that of the passive counterparts". The substance holds. |
| MOM-5 | NOT VERIFIED | **WEAKENED** | The venue and citation are correct. But "no India evidence / only a practitioner source" is wrong for stock-level dual momentum: Singh, Walia, Jain & Garg (2022, *J. Public Affairs*) is peer-reviewed India work **[S]**. The claim holds only for the multi-asset GEM variant. |
| MOM-6 | VERIFIED | **WEAKENED** | All five CAGRs reproduce to 0.01 pp. The inputs and model are biased: (a) the gross inputs are NSE since-inception figures that are internally inconsistent (see MOM-9); (b) the fund leg deducts TER only and ignores in-fund trading costs and tracking difference; (c) a constant-return path ignores sequence and loss years. The direction (wrapper beats DIY) survives; the magnitudes do not. |
| MOM-7 | BLOCKED | **CONFIRMED** (one nuance) | The NSE ToU clause and the IIMA figure of 3,184 vanished firms are accurate. Nuance: IIMA now states its algorithm found **no vanishing companies after the mid-1990s**, so the binding blocker is point-in-time constituents plus the data licence, not delisting returns per se. |
| MOM-8 | REQUIRES CONFIGURATION | **WEAKENED** | The niftyindices.com ToU *was* retrievable. It contains **no** "simulation" clause. It does say "personal, non-commercial use only", and "No material from the Site may be copied, modified, reproduced, republished, **uploaded**, transmitted … without prior written permission". So the report's open item is resolved differently: the two ToUs are not equivalent, and the operative risk is copying and uploading, not "simulation". |
| MOM-9 | NOT VERIFIED | **WEAKENED (misattributed)** | The ~22 %/yr back-out reproduces (22.04 %). The deeper cause is *inside the 2026 WP itself*: its since-inception parent CAGRs do not reconcile with its own calendar-year table. Nifty 500's 18.85 % would require +212 % in Apr–Dec 2005. The report flags a cross-paper splice, yet still uses 15.08 % (§0, §3.4 and §4.3) and 18.85 % (§3.4 table) uncritically. |
| MOM-10 | VERIFIED | **WEAKENED** | The Novy-Marx & Velikov quote and numbers match exactly. The NSE quarterly-vs-semi-annual comparison is in-sample, provider-run and **mixed**: Midcap150 quarterly beat semi-annual (23.26 % vs 23.00 %, 12/20 years). The report's "enter ≤30 / exit >45" buffer has no source. |

Nothing was outright refuted: every cited source exists and says roughly what is claimed. The problems are overstatement, stale data vintages and one misattributed root cause.

---

## 1. Claim-by-claim checks

### MOM-1: IIMA WML and shorting

**Checked against the IIMA W.P. PDF**
(<https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/four-factors-India-90s-onwards-IIM-WP-Version.pdf>)

What matches:
- **Table 4 (with adjustment):** "Mean … 17.0", "SD … 24.1", "2009 … -24.8", "Cumulative … 340.8", "Skewness … 0.0". The table note reads "annualised logarithmic … returns … January 1994 to December 2013".
- **Footnote 11 (quoted correctly):** "would involve a higher trading cost. This would happen as the momentum returns are estimated with monthly portfolio re-balancing".
- **Construction:** "11- month returns from the end of month t − 12 to t − 1"; "top 30% by the momentum return"; "assuming 100% capital loss for the firms vanishing due to distress"; "3,184 firms that stopped trading … 439 firms had stopped trading due to mergers". All confirmed.

Problems the report did not flag:
1. **Stale vintage.** The current IIMA library page (release 2025-12, "New Series") gives "WML % … Since 01-Jan-1994 … 10.65", with all returns stated as "annualized geometric mean returns".
   (<https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/>)
2. **Current drawdown page.** The drawdown page says: "The Momentum Factor (WML) provided an annualized return of 10.96% with an annualized volatility of 17.30%. The worst drawdown was 62.00% and the duration of this drawdown was 5.00 years". It lists −62.2 % (2000-03 → 2005-03) and −53.1 % (2008-12 → 2011-12).
   (<https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/drawdown.php>)
   The report cites this library for its coverage dates but omits these headline numbers. The best current estimate of Indian gross long–short momentum is **about 11 %/yr, not 17 %/yr**, with a far deeper drawdown than "worst year −24.8 %" suggests.
3. **New series differs from the working paper.** The library says: "The data in the new series does not therefore exactly match the data in the Legacy Releases and in our Working Paper".
4. **Abstract period mismatch.** The abstract's "January 1994 to December 2014 … 21.9%" conflicts with the paper's own coverage, "October 1993 - December 2013". The report repeats 21.9 % as a quote (§9) without noting the inconsistency.
5. **"Investible" is weak.** The liquidity filter is only "traded on less than 50 days in a 12-month period … were excluded". The median size–momentum portfolio counts are 669 small-cap winners against 105 big-cap winners. The paper's own "investible" language should not be read as implementable at retail scale.

**SEBI circular.** SEBI/HO/MRD/MRD-PoD-3/P/CIR/2024/1 (05-Jan-2024), as reproduced by CSE India
(<https://www.cse-india.com/upload/upload/Jan_052024.pdf>, via search summary **[S]**):
- "Naked short selling shall not be permitted in the Indian securities market";
- "The securities traded in F&O segment shall be eligible for short selling".

Confirmed (secondary).

**Verdict: WEAKENED.** The quoted evidence is accurate, but the magnitude claim relies on outdated vintages.

### MOM-2: backfill vs live decay

Recomputed from the 2026 WP Exhibit 07 (Decimal products):

| Window | Mom CAGR | Parent CAGR | Excess | Positive | Arith. mean excess | SD | t (n−1 SD) |
|---|---|---|---|---|---|---|---|
| CY2006–19 | 17.53 % | 11.94 % | +5.59 | 11/14 | 6.77 | 12.56 | **2.02** |
| CY2021–25 | 19.00 % | 16.21 % | +2.79 | 3/5 | 4.81 | 16.93 | **0.64** |
| CY2006–25 | 18.01 % | 13.23 % | +4.78 | 15/20 | 6.10 | 13.02 | 2.09 |

- The numbers match the report exactly.
- The launch date of 25-Aug-2020 is confirmed. NSE press release: "NSE Indices launches Nifty200 Momentum 30 Index", dated August 25, 2020 (<https://www.niftyindices.com/Press_Release/ind_prs25082020.pdf>, via search **[S]**).

Problems:
- A ratio of two noisy estimates (2.79 / 5.59) is not a measured "decay". With SD ≈ 17 pp and n = 5, the live excess is consistent with anything from roughly −18 pp to +24 pp a year (±2 SE). The report's own text admits that "5 years is far too short". The finding's title, "decayed ~50 %", should not be presented as VERIFIED.
- "Consistent with McLean & Pontiff" is an analogy, not evidence.
- The backfilled excess itself has t ≈ 2.0, which fails the report's own gate 4 (t > 3).
- The live split exists only for N200 Mom 30. The report also recommends the Midcap150 and Nifty500 momentum variants, whose launch dates and live records were not given (NOT VERIFIED here).

**Verdict: WEAKENED.**

### MOM-3: drawdowns and rebound years

From the 2026 WP:
- Exhibit 06: "Nifty200 Momentum 30: -67.7% / Nifty 200: -63.7%"; "Nifty500 Momentum 50: -70.2% / Nifty 500: -63.7%"; "Nifty Midcap150 Momentum 50: -72.5% / Nifty Midcap 150: -72.9%".
- Exhibit 07: 2009 −19.47 %; 2025 −14.13 %.

From Daniel & Moskowitz, NBER w20439 (<https://www.nber.org/system/files/working_papers/w20439/w20439.pdf>): "March to May of 2009, the past-loser decile rose by 163%"; "the crash performance is mostly attributable to the short side".

All confirmed. The caveat is the Midcap150 drawdown noted in §0. NSE's own prose ("the Nifty200 Momentum 30 has followed a steadier path with moderate drawdowns") conflicts with its exhibit; the exhibit should govern.

**Verdict: CONFIRMED.**

### MOM-4: MA and TSM timing

- **Mitra (2011), IJBM 6(7):199** (<https://www.ccsenet.org/journal/index.php/ijbm/article/view/11198>): "many trading rules offer profit opportunity without trading costs, but the profit vanishes when trading costs are accounted". Data run "December 2000 to November 2010". Confirmed.
- **Zakamulin (2014), JAM 15(4):261–278:**
  - The RePEc abstract (<https://ideas.repec.org/a/pal/assmgt/v15y2014i4d10.1057_jam.2014.25.html>) says "the performance of market timing strategies is highly overstated, to say the least".
  - The working-paper version says "at best the real-life performance of the market timing strategies is only marginally better than that of the passive counterparts". It also says such a strategy "delivers only marginally better risk-adjusted returns than the buy-and-hold strategy, yet with a substantially lower long-term capital growth".
  - The report's phrase "only marginally better than buying and holding" matches the wording of Zakamulin's 2018 *IRF* paper, not the 2014 one. It is a minor misquote; the substance is supported.
  - The report omits the "substantially lower long-term capital growth" point, which matters directly to a user aiming for 20–25 %.
- **Huang, Li, Wang & Zhou (2020), JFE 135(3):774–794:** "asset-by-asset time series regressions reveal little evidence of TSM, both in- and out-of-sample" (abstract, via search of <https://ink.library.smu.edu.sg/lkcsb_research/6521/> **[S]**; the page itself returned empty to direct fetch). Confirmed.
- **Absence claim.** My own searches also found no peer-reviewed, out-of-sample, after-cost 200-DMA test on Nifty. A 2014 *Indian Journal of Finance* trend-following study states that "no transaction costs or dividends" were assumed **[S]**.

**Verdict: CONFIRMED**, and the abstain status is correct.

### MOM-5: dual momentum

- The citation is correct. SSRN 2042750 lists "Journal of Management & Entrepreneurship, vol.2, no.1 (Mar 2017), 27-55" **[S]**. The SSRN page returned 403 to direct fetch.
- **Omission:** Singh, Walia, Jain & Garg (2022), "Taming momentum crashes through triple momentum investing", *Journal of Public Affairs* 22(3) e2525 (<https://onlinelibrary.wiley.com/doi/10.1002/pa.2525>) **[S]**. Per the search summary, it finds that absolute, relative and dual momentum make significant profits in Indian stocks, with severe periodic losses.
- A 2025 *International Journal of Emerging Markets* paper, "Relative, absolute or combined strength momentum strategies: what works for India?" **[S]**, is also missing. Neither full text was read, so their out-of-sample and cost treatment is NOT VERIFIED.
- The report's claim stands only for the **multi-asset GEM** variant (Nifty/gold/G-sec). For that variant, only practitioner blogs were found, such as Zerodha's "In the Money" Substack and Samasthiti **[S]**.

**Verdict: WEAKENED.**

### MOM-6: tax-wrapper computation

Re-run (`python3 -I`, Decimal, ₹10 L, 10 years):

| Route | Result |
|---|---|
| Fund, TER 0.3 % | 17.64 % |
| Fund, TER 1.0 % | 16.97 % |
| Nifty 200 fund | 13.71 % |
| DIY, costs 0.24 % | 15.16 % |
| DIY, costs 0.74 % | 14.76 % |

All five reproduce. Using CY2021–25 live CAGRs instead (19.00 % / 16.21 %): fund 17.46 % vs Nifty 200 fund 14.79 % vs DIY 15.01 %. The ordering holds.

Biases:
1. **Inputs.** The gross inputs 19.19 % and 15.08 % come from since-inception figures that are internally inconsistent (see MOM-9).
2. **Fund costs.** The fund leg subtracts TER only. The fund itself pays STT of 0.1 % on each side and impact cost on ~110 % churn; these show up as tracking difference, not TER. The DIY leg is charged these costs, so the comparison is tilted toward the fund. Tracking *difference* (as opposed to tracking error, 0.17–0.52 % per Exhibit 12) is NOT VERIFIED.
3. **Return path.** A constant return removes loss years and the sequence risk that matter with −68 % drawdowns.
4. **Tax rules.** STCG 20 % and LTCG 12.5 % match repo rows EQ-STCG and EQ-LTCG (`docs/research/indian-instruments-and-tax.md` L484–486, VERIFIED-PRIMARY). s.10(23D) remains secondary.

**Verdict: WEAKENED.** The direction is defensible; the precise 17.64 vs 15.16 vs 13.71 should not be shown to the user as evidence.

### MOM-7: data licensing and survivorship

- `source-registry.md` §2.11 quotes the NSE ToU: "User is prohibited to conduct any systematic or automated data collection activities …". Confirmed in the repo.
- The niftyindices.com ToU has the same ban: "You may not conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting) on or in relation to our website without our express written consent" (<https://www.niftyindices.com/terms-of-use>).
- IIMA's 3,184 figure is confirmed. But the IIMA library also says: "We found that our survivorship bias algorithm has not identified any 'vanishing companies' after the mid 1990s … We have therefore discontinued the ongoing running of this algorithm". For a post-2000 backtest, the survivorship risk lies mainly in point-in-time index membership and corporate actions, not mass vanishing.

**Verdict: CONFIRMED.**

### MOM-8: manual import and the "simulation" clause

The niftyindices ToU (<https://www.niftyindices.com/terms-of-use>, fetched 2026-10-15):
- searches for "simulat", "virtual" and "gaming" return nothing;
- it says: "The Site may be used only for lawful purposes by individuals for personal, non-commercial use only";
- it says: "No material from the Site may be copied, modified, reproduced, republished, uploaded, transmitted, posted or distributed in any form without prior written permission from the Company".

Implications:
- The report's open item ("whether niftyindices ToU match NSE ToU") is now answered: they do **not** match.
- The real constraint is the **no-copy / no-upload** clause. Importing a manually downloaded TRI CSV into a database is arguably "copied … uploaded". That is especially so in the hosted mode, which is a public repo plus Vercel/Turso; that deployment fact comes from the task brief.
- The personal, non-commercial scope helps local single-user use, but does not grant a copy right.

**Verdict: WEAKENED.** The status should stay REQUIRES CONFIGURATION, but cite the correct clause. Recommendation: local-only storage of user-imported files, never committed or deployed, and the user's explicit acknowledgement of the copy clause.

### MOM-9: inconsistent NSE since-inception figures

- **Reproduction.** The 2020 WP says "Since Inception 18.6% … 12.7%" ("Data as of August 31, 2020"). The 2026 WP says 19.19 % / 15.08 % to 27-Feb-2026. The implied Sep-2020 → Feb-2026 CAGR is **20.9 %** (Mom 30) and **22.0 %** (Nifty 200). This reproduces the report.
- **Internal check (new).** Compounding the 2026 WP's *own* CY2006–2025 table and its YTD figure, then solving for the Apr–Dec 2005 return implied by its own since-inception CAGR over 20.91 years, gives:

  | Index | Implied Apr–Dec 2005 return |
  |---|---|
  | Nifty200 Mom 30 | +42 % |
  | Nifty 200 | +62 % |
  | Nifty500 Mom 50 | +71 % |
  | **Nifty 500** | **+212 %** (impossible) |

- **Price reference.** The Nifty 50 price rose about 39 % over that window (2,035.65 → 2,836.55, via secondary aggregator search **[S]**; exact TRI NOT VERIFIED).
- **Second symptom.** Exhibit 03 shows Nifty 500 since inception at 18.85 % against Nifty 200 at 15.08 %, while their 15-year figures are almost equal (13.23 % vs 12.99 %).
- **Conclusion.** The 2026 WP's since-inception parent figures, certainly Nifty 500's and probably Nifty 200's, are unreliable *within one publication*. The report's own rule ("never splice … compute from one imported TRI series") is right, but the report breaks it in spirit by using 15.08 % as a headline and in §4.3.

**Verdict: WEAKENED.** The anomaly is real; the attribution is incomplete.

### MOM-10: cost mitigations

- **Novy-Marx & Velikov, NBER w20721** (<https://www.nber.org/system/files/working_papers/w20721/w20721.pdf>):
  - Abstract: "introducing a buy/hold spread … is the single most effective simple cost mitigation strategy".
  - Table 3, Momentum row: "1.33 [4.80], 0.35 [3.04], 34.52, 0.65, 0.68 [2.45], 0.40 [3.12]". All confirmed.
- **NSE 2026 WP, Exhibit 08:**
  - N200 Mom 30: quarterly 17.12 % vs semi-annual 19.19 % (confirmed).
  - Midcap150 Mom 50: quarterly **23.26 %** vs semi-annual 23.00 %, and the quarterly version won in 12 of 20 calendar years (Exhibit 10).
  - So the result is index-dependent.
- **Churn wording.** Exhibit 11 says "around 20% - 70% extra annual churn"; the executive summary says "around 20-50% more churn". Computed FY22–25 differences range from +20 pp to **+79 pp** (Nifty500 Mom 50, FY25: 218 vs 139).
- **Unsourced spec.** The report's spec "enter ≤30, exit >45" has no source, and the NSE buffer thresholds remain NOT VERIFIED.

**Verdict: WEAKENED.**

---

## 2. Important omissions

1. The current IIMA library: WML 10.65 % geometric since Jan-1994 (release 2025-12), worst drawdown 62 % over 5 years, −53.1 % in 2008–11.
2. The internal inconsistency of the 2026 WP's since-inception parent figures. Nifty 500's 18.85 % is reproduced unflagged in the report's §3.4 table.
3. The actual text of the niftyindices.com ToU: personal, non-commercial use only; no copy or upload without written permission; no "simulation" clause.
4. Peer-reviewed Indian dual or absolute momentum work: Singh et al. 2022 *J. Public Affairs*; the 2025 *IJEM* paper; Nigam & Pandey 2023 *Algorithmic Finance* (long-only Indian momentum) **[S]**.
5. Even the backfilled N200 Mom 30 excess (t ≈ 2.0) fails the report's own t > 3 gate. Exempting S-C from gate 4 while ranking it as a candidate deserves explicit justification.
6. In-fund trading costs and tracking *difference*, which the fund-wrapper comparison omits. ₹17,667 cr of AUM rebalances on public dates, so front-running costs land inside NAV.
7. Zakamulin's "substantially lower long-term capital growth" for MA timing, which bears directly on the user's growth target.
8. Live-record dates for Midcap150 Mom 50 and Nifty500 Mom 50, which are shorter than N200 Mom 30's. NOT VERIFIED here.

---

## 3. Sources (accessed 2026-10-15)

- IIMA W.P. 2013-09-05 (revised): <https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/four-factors-India-90s-onwards-IIM-WP-Version.pdf>
- IIMA data library: <https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/>. Drawdowns: <https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/drawdown.php>
- NSE 2026 WP: <https://www.niftyindices.com/docs/default-source/indices/nifty200-momentum-30/momentum-strategy-whitepaper_2026.pdf>
- NSE 2020 WP: <https://www.niftyindices.com/docs/default-source/indices/nifty200-momentum-30/nifty200_momentum_30_index_whitepaper_sep_20.pdf>
- NSE launch press release: <https://www.niftyindices.com/Press_Release/ind_prs25082020.pdf> [S]
- niftyindices ToU: <https://www.niftyindices.com/terms-of-use>
- Daniel & Moskowitz: <https://www.nber.org/system/files/working_papers/w20439/w20439.pdf>
- Novy-Marx & Velikov: <https://www.nber.org/system/files/working_papers/w20721/w20721.pdf>
- Mitra 2011: <https://www.ccsenet.org/journal/index.php/ijbm/article/view/11198>
- Zakamulin 2014: <https://ideas.repec.org/a/pal/assmgt/v15y2014i4d10.1057_jam.2014.25.html>. Working paper: <https://foro.masdividendos.com/uploads/default/original/2X/a/a1bd5ae7e323496b5072adf8c2e126e31764e306.pdf>
- Huang et al. 2020: <https://ink.library.smu.edu.sg/lkcsb_research/6521/> [S]
- SEBI circular (CSE copy): <https://www.cse-india.com/upload/upload/Jan_052024.pdf> [S]
- Antonacci SSRN: <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2042750> [S, 403 on direct fetch]
- Singh et al. 2022: <https://onlinelibrary.wiley.com/doi/10.1002/pa.2525> [S]
- Nifty 50 2005 levels: search summary of aggregator sites (finco panda, stockpricearchive) [S, NOT VERIFIED against NSE]
