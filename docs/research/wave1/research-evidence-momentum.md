# Evidence review: trend and momentum signals for Indian equities

- **Wave:** 1 · **Topic:** evidence-momentum · **Date:** 2026-10-15 · **Author:** research subagent (no code changed)
- **Question:** Is there documented, out-of-sample, cost-aware and tax-aware evidence for trend or momentum signals on Indian
  equities and indices that is strong enough for a deterministic engine to issue **buy or sell signals**? If so, which rule
  specifications are robust?
- **Binding rule applied:** a signal exists only if a documented, out-of-sample, cost-aware and tax-aware backtest supports it.
  Otherwise the engine abstains.

**Evidence tags:**
- **[P]** a primary source was read directly. A quote and URL are given.
- **[S]** secondary: search-engine summary, abstract page or third-party write-up. The primary was not opened.
- **[C]** computed here from [P] figures. The formula is shown.
- **NOT VERIFIED** means the fact could not be confirmed and must not be relied on.

All URLs were accessed on 2026-10-15.

---

## 0. Bottom line

1. **Cross-sectional (relative) momentum in Indian stocks is real, large in gross terms, and replicated.** This is the strongest
   result here. Evidence:
   - The IIMA four-factor data library: WML averaged **17.0 % per year** (log, 1994–2013) **[P]**.
   - Agarwalla, Jacob and Varma (2017, *Vikalpa*) report **17.3 % per year** for 1994–Mar 2017 **[S]**.
   - Chui et al. (2023, *Pacific-Basin Finance Journal*) find it on 3,956 BSE stocks, 2000–2021 **[S]**.
   - NSE's momentum indices beat their parents in most years **[P]**.

   But these are **gross, long–short, monthly-rebalanced** academic portfolios. A resident individual cannot replicate them:
   - There is no overnight naked shorting, and SLB is limited to F&O stocks **[S]**.
   - Delivery STT is 0.1 % on each side **[P]**.
   - Every gain held 12 months or less is STCG at 20 % (repo tax doc).
2. **The implementable form is a momentum index fund. The evidence shows decay, and the fund is not a timing signal.** Per the
   NSE April-2026 white paper **[P]**:
   - Since 2005, Nifty200 Momentum 30 TRI returned **19.19 %** a year against **15.08 %** for Nifty 200 TRI.
   - Its maximum drawdown was **−67.7 %**, against **−63.7 %** for Nifty 200 (27-Oct-2008).
   - It underperformed by **−14.13 pp** in CY2025 and by **−19.47 pp** in CY2009, the rebound year.

   The index was launched on **25-Aug-2020**, so everything before that is a backfilled backtest. Using NSE's own calendar-year
   table **[C]**:
   - Backfilled period, CY2006–2019: excess return **+5.59 pp/yr**.
   - Live period, CY2021–2025: excess return **+2.79 pp/yr**.

   That is a ~50 % decay, consistent with McLean & Pontiff's finding of 58 % lower returns after publication **[P-abstract]**.
   It is still positive, but rests on 5 live years: 3 positive and 2 sharply negative.
3. **Time-series momentum (TSM) and 200-day / 10-month moving-average timing on an index are NOT VERIFIED for India.**
   - Globally the evidence is contested:
     - Supportive: Moskowitz-Ooi-Pedersen 2012, and Hurst-Ooi-Pedersen 2017 (1880–2016).
     - Against: Huang et al. (2020, *JFE*), who find "little evidence of TSM, both in- and out-of-sample".
     - Zakamulin (2014, *J. Asset Mgmt*): out-of-sample, after costs, MA/TSM timing is "only marginally better than buying and
       holding".
   - India: Mitra (2011, *IJBM*), on Nifty and Junior Nifty 2000–2010, finds MA profits "vanish when trading costs are accounted"
     **[P-abstract]**.
   - No peer-reviewed India study of an out-of-sample 200-DMA or 12-1 TSM rule on Nifty that also models costs and tax was found.
     **Engine must abstain** on these until our own pre-registered out-of-sample test passes the gates in §7.
4. **Dual momentum (Antonacci) is NOT VERIFIED.**
   - The source is a practitioner paper in a low-tier venue, *J. Management & Entrepreneurship* 2017.
   - No India out-of-sample replication was found.
   - It is a candidate for our own test only.
5. **Tax dominates for a DIY strategy [C].** On the 2005–2026 gross numbers, assuming every year's gain is realised as STCG at 20 %
   (the worst case), DIY momentum compounds at about **15.2 %**. A momentum index fund (0.3 % TER, LTCG at 12.5 % at exit after
   10 years) compounds at about **17.6 %**, against **13.7 %** for a Nifty 200 fund. The fund wrapper defers tax because
   s.10(23D) exempts the fund's own income **[S]**. So **if the app ever expresses momentum, it should be as a fund allocation
   candidate, not as stock-level buy/sell trades.**
6. **Stock-level momentum is BLOCKED by data.**
   - NSE's Terms of Use prohibit automated collection and storage (source-registry §2.11).
   - A survivorship-free test needs point-in-time constituents and delisted stocks. No free, licence-clean source exists.
   - The "no paid API keys" rule rules out a vendor.

**Answer to "when to buy and sell equities":** no stock-level or index-timing rule currently meets the bar. "No suitable signal" is
the correct engine output today. The one evidence-backed, implementable exposure is the following:
- a **momentum factor sleeve held through an index fund**;
- with **semi-annual index rebalancing done inside the fund**;
- sized for a **~70 % worst-case drawdown**;
- and shown with its decay and live-period record.

That sleeve is a **ranked candidate**, not a signal.

---

## 1. Status summary per signal family

| # | Signal family | Global evidence | India evidence | Out-of-sample? | After costs? | After Indian tax? | Status for engine |
|---|---|---|---|---|---|---|---|
| A | Cross-sectional 12-1 stock momentum (long–short) | Strong: JT 1993, JT 2001 OOS 1990s, Rouwenhorst 1999 EM, Novy-Marx & Velikov 2016 net | Strong gross: IIMA WML, Chui 2023, Sehgal & Jain 2011 | Yes globally (JT 2001; McLean–Pontiff decay); India only by later-period replication | US: yes (net 0.68 %/mo, t = 2.45). India: **no published net-of-cost estimate found** | No | **BLOCKED** (shorting, data) |
| B | Long-only stock momentum (top-N, DIY) | As A, long leg only | NSE index backtests; non-peer-reviewed GitHub/blog backtests | Only the NSE index since Aug-2020 | Not in published India work | No; STCG drag ≈ entire edge [C] | **BLOCKED** (data licence) · NOT VERIFIED (net) |
| C | Momentum **index fund** (Nifty200 Mom 30, Midcap150 Mom 50, Nifty500 Mom 50) | n/a | NSE white papers 2020 and 2026 [P] | **Partly**: 5.5 years live since launch on 25-Aug-2020 | TRI is gross; fund TER and tracking error are extra (TE 0.17–0.51 % per NSE) | Yes, via fund wrapper (deferral) | **VERIFIED as evidence**; usable as a *ranked candidate* with drawdown warning; not a timing signal |
| D | Time-series momentum (12-m sign) on index | Contested: MOP 2012 / HOP 2017 vs Huang et al. 2020, Goyal & Jegadeesh 2018 | Singh & Walia 2020 (stock-level, in-sample) | Global: mixed. India: none | Not in India | No | **NOT VERIFIED → abstain** |
| E | 200-DMA / 10-month SMA trend filter on Nifty | Faber 2007 (practitioner); Zakamulin 2014: marginal OOS after costs | Mitra 2011: profits vanish after costs; older 1996–2003 study positive | No India OOS | India: negative | No | **NOT VERIFIED → abstain** |
| F | Dual momentum (relative + absolute, multi-asset) | Antonacci 2017 (low-tier venue) | None found | No | Not in India | No | **NOT VERIFIED → abstain** |
| G | Volatility-scaled (risk-managed) momentum | Barroso & Santa-Clara 2015; Daniel & Moskowitz 2016 | NSE score already scales by volatility; GitHub replication only | Partly (global) | Not in India | No | **NOT VERIFIED** (an overlay idea only) |

---

## 2. Global peer-reviewed evidence

### 2.1 Cross-sectional momentum: Jegadeesh & Titman

- **Jegadeesh & Titman (1993)**, *J. Finance* 48(1):65–91 **[S]**.
  - The abstract says strategies "which buy stocks that have performed well in the past and sell stocks that have performed poorly
    … generate significant positive returns over 3- to 12-month holding periods".
  - The body reports that the 6/6 strategy "realizes a compounded excess return of 12.01% per year" (NYSE/AMEX, 1965–1989).
  - <https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1993.tb04702.x>
- **Jegadeesh & Titman (2001)**, *J. Finance* 56:699–720 **[S]**.
  - "Momentum profits have continued in the 1990s, suggesting that the original results were not a product of data snooping bias."
  - This is the canonical out-of-sample test. The same paper documents **reversal in years 2–5**.
  - <https://onlinelibrary.wiley.com/doi/10.1111/0022-1082.00342>
- **Rouwenhorst (1999)**, *J. Finance* 54(4):1439–1464 **[S]**.
  - "Emerging market stocks exhibit momentum". The sample is 20 emerging markets.
  - A later review notes that very few **single-country** winner-minus-loser spreads are individually significant, and that the
    pattern is strong when countries are pooled.
  - India's own coefficient was NOT VERIFIED (the per-country table was not opened).
  - <https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00151>
- **Griffin, Ji & Martin (2003)**, *J. Finance* 58(6):2515–2547 **[S]**.
  - Momentum appears in about 80 % of 40 countries.
  - Macro risk "does not … explain momentum".
  - <https://onlinelibrary.wiley.com/doi/abs/10.1046/j.1540-6261.2003.00614.x>

### 2.2 Costs: Novy-Marx & Velikov

**Novy-Marx & Velikov (2016)**, *RFS* 29(1):104–147 **[S]**, numbers from NBER WP 20721, Table 3:

| UMD (US) | Mean excess return | FF4 alpha |
|---|---|---|
| Gross | 1.33 %/mo (t = 4.80) | 0.35 %/mo (t = 3.04) |
| Net of costs | **0.68 %/mo** (t = 2.45) | 0.40 %/mo (t = 3.12) |

- Costs come to **0.65 %/mo** on 34.5 % one-sided monthly turnover. **Costs roughly halve momentum.**
- The paper calls a buy/hold spread (a rank buffer) "the single most effective simple cost mitigation strategy". This matters
  directly for spec design (§6).
- <https://www.nber.org/system/files/working_papers/w20721/w20721.pdf>
- The published RFS tables may differ slightly; NOT VERIFIED.

### 2.3 Crash risk

- **Daniel & Moskowitz (2016)**, *JFE* 122(2):221–247 **[P]**, NBER WP 20439 text read.
  - "Over the three-month period from March to May of 2009, the past-loser decile rose by 163%, while the decile portfolio of past
    winners gained only 8%."
  - "The crash performance is mostly attributable to the short side".
  - Crashes occur "following market declines and when market volatility is high … contemporaneous with market rebounds".
  - A dynamic, volatility-aware version "approximately doubles the alpha and Sharpe Ratio".
  - <https://www.nber.org/system/files/working_papers/w20439/w20439.pdf>
  - **Implication:** long-only momentum avoids the worst of the short-side crash. It still lags in rebound years. NSE's own data
    show N200 Momentum 30 at **−19.47 pp** against Nifty 200 in CY2009 **[P]**.
- **Barroso & Santa-Clara (2015)**, *JFE* 116(1):111–120 **[S]**.
  - Momentum risk "is highly variable over time and predictable".
  - Managing it "virtually eliminates crashes and nearly doubles the Sharpe ratio". The method targets 12 % volatility using 6-month
    realised volatility.
  - This is a long–short US result. It has not been tested on Indian long-only funds.
  - <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2041429>

### 2.4 Time-series momentum and trend following

- **Moskowitz, Ooi & Pedersen (2012)**, *JFE* 104(2):228–250 **[S]**.
  - TSM is significant in all 58 liquid futures; returns "persist for 1 to 12 months and then partly reverse".
  - The sample is futures, not single Indian stocks.
  - <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463>
- **Hurst, Ooi & Pedersen (2017)**, *J. Portfolio Mgmt* 44(1):15–29 **[S]**.
  - 67 markets, 1880–2016.
  - Positive in every decade; performed well in 8 of 10 largest 60/40 drawdowns.
  - The authors are AQR principals, which is an interest to note.
  - <https://jpm.pm-research.com/content/44/1/15.abstract>
- **Huang, Li, Wang & Zhou (2020)**, *JFE* 135(3):774–794 **[S]**.
  - Asset-by-asset regressions find "little evidence of TSM, both in-sample and out-of-sample".
  - The pooled t-stat "is not statistically reliable" under bootstrap.
  - The TSM strategy "performs about the same" as one based on the historical sample mean.
  - <https://ink.library.smu.edu.sg/lkcsb_research/6521/>
- **Goyal & Jegadeesh (2018)**, *RFS* 31(5):1784–1824 **[S]**.
  - For individual stocks, the TS–CS performance difference "is largely due to this time-varying net long investment".
  - In other words, much of single-stock "TSM" is just being long the market.
  - <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2610288>

### 2.5 Moving-average timing

- **Faber (2007)**, *J. Wealth Management* 9(4) **[S]**.
  - Rule: buy when month-end price is above the 10-month SMA, otherwise hold cash. This is the monthly analogue of the 200-day.
  - He claims results hold across 3–12-month lengths.
  - This is practitioner research, US/global assets, and **not out-of-sample with costs**.
  - <https://www.researchgate.net/publication/228202718_A_Quantitative_Approach_to_Tactical_Asset_Allocation>
- **Zakamulin (2014)**, *J. Asset Management* 15(4) **[S]**.
  - Reported performance "contains a considerable data-mining bias and ignores important market frictions".
  - Out-of-sample with costs, it is "only marginally better than buying and holding".
  - <https://ideas.repec.org/a/pal/assmgt/v15y2014i4d10.1057_jam.2014.25.html>
- **Zakamulin, SSRN 2677212** **[S]** (working paper, not peer-reviewed).
  - 155 years of data: "no statistically significant evidence" of outperformance in the second half of the sample.
  - The rules tend to outperform in bear markets only.
  - <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2677212>

### 2.6 Dual momentum

**Antonacci, "Risk Premia Harvesting Through Dual Momentum"**, *J. Management & Entrepreneurship* 2(1), 2017:27–55 **[S]**.
- "Absolute momentum does far more to lessen volatility and drawdown". Combining it with relative momentum "gives the best results".
- Practitioner author. The venue is not a top finance journal. The test is in-sample on US/global indices.
- <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2042750>

### 2.7 Data mining and decay

- **McLean & Pontiff (2016)**, *J. Finance* 71(1):5–32 **[S]**.
  - Across 97 predictors, returns are "26% lower out-of-sample and 58% lower post-publication".
  - <https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365>
- **Harvey, Liu & Zhu (2016)**, *RFS* 29(1):5–68 **[S]**.
  - "A new factor needs to clear a much higher hurdle, with a t-statistic greater than 3.0".
  - <https://academic.oup.com/rfs/article-abstract/29/1/5/1843824>
- **Chen & Velikov** (as summarised in the search results) **[S]**.
  - Momentum is one of the few anomalies that "performed well post-publication net of trading costs".
  - The primary was NOT VERIFIED (not opened).

---

## 3. India-specific evidence

### 3.1 IIMA four-factor data library (Agarwalla, Jacob & Varma) [P]

**Source.** Working paper W.P. 2013-09-05, revised version, PDF read:
<https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/four-factors-India-90s-onwards-IIM-WP-Version.pdf>

**Construction.** Momentum is the "11-month returns from the end of month t − 12 to t − 1". This is the standard 12-1 with a skip
month. The breakpoints are top and bottom 30 %, built as 2×3 size–momentum portfolios. Portfolios are **rebalanced monthly**.

**Investability and survivorship.** Illiquid firms are excluded "to ensure that the portfolios are investible". The paper applies
a survivorship correction that assumes "100% capital loss for the firms vanishing due to distress". It found 3,184 firms that
stopped trading, of which 439 were mergers.

**Returns.** The abstract says: "During the period from January 1994 to December 2014, the average annual return of the momentum
factor was 21.9%". Table 4 (survivorship-adjusted, Jan-1994 to Dec-2013, log returns) gives:

| Statistic | Value |
|---|---|
| Mean WML per year | **17.0 %** |
| SD | 24.1 % |
| Skewness | 0.0 |
| Cumulative | 340.8 % (log) |
| Worst years | 2009 −24.8 % · 2000 −22.2 % · 2012 −8.6 % · 2008 −9.7 % |
| Best year | 1999 +66.5 % |

**Costs.** Footnote 11 says WML "would involve a higher trading cost … as the momentum returns are estimated with monthly
portfolio re-balancing". **No net-of-cost figure is given.**

**Data library.** Coverage runs Oct-1993 to Dec-2025 (release 2025-12) **[P]**.
- The authors recommend the survivorship-adjusted series "if the analysis includes the period between 1995-2000".
- **No licence text was found** on the page, so the licence is NOT VERIFIED.
- The page asks users to cite the working paper.
- <https://faculty.iima.ac.in/~iffm/Indian-Fama-French-Momentum/>

**Follow-up paper.** *Size, Value, and Momentum in Indian Equities*, *Vikalpa* 42(4), 2017, covering 1994–Mar 2017 **[S]**. The
journal page returned HTTP 403, so the figures come from a search summary:
- WML **17.3 % per year**, volatility 17.06 %;
- **10 drawdowns >20 %**;
- the worst was **49 %**, "during the rally after the global financial crisis".

<https://journals.sagepub.com/doi/full/10.1177/0256090917733848>

### 3.2 Other Indian peer-reviewed work [S]

- **Chui, Ranganathan, Rohit & Veeraraghavan (2023)**, "Momentum, reversals and liquidity: Indian evidence", *Pacific-Basin Finance
  Journal* 82:102193.
  - 3,956 BSE stocks, 2000–2021.
  - Significant intermediate and long-term momentum. It is "more significant for the most liquid portfolio".
  - Short-term reversals sit in illiquid stocks.
  - Robust to market, size, value and macro controls. No net-of-cost result was seen in the abstract.
  - <https://doi.org/10.1016/j.pacfin.2023.102193>
- **Singh & Walia (2020)**, "Time-series and cross-sectional momentum in Indian stock market", *Copernican J. Finance & Accounting*
  9(3):161–176.
  - Both TSM and CSM are significant after market, size and value adjustment.
  - TSM's edge over CSM comes from "net long investments", which echoes Goyal & Jegadeesh.
  - No costs in the abstract.
  - <https://apcz.umk.pl/czasopisma/index.php/CJFA/article/view/CJFA.2020.018>
- **Sehgal & Jain (2011)**, "Short-term momentum patterns in stock and sectoral returns: evidence from India".
  - Momentum is "stronger for 6-6 compared to 12-12 strategies".
  - The full text was not read; NOT VERIFIED beyond the search snippet.
- **Maheshwari & Dhankar (2017)**, *Vision* (SAGE).
  - Momentum is significant but "turned negative during the crisis period".
  - The journal page returned HTTP 403; only the search-result summary was seen.
  - <https://journals.sagepub.com/doi/10.1177/0972262916681118>

### 3.3 Moving-average rules on Nifty

- **Mitra, S. K. (2011)**, "Usefulness of Moving Average Based Trading Rules in India", *Int. J. Business and Management* 6(7):199
  **[P-abstract]**.
  - Nifty and Junior Nifty, Dec-2000 to Nov-2010.
  - "Many trading rules offer profit opportunity without trading costs, but the profit vanishes when trading costs are accounted …
    small investors need to keep an eye on trading cost".
  - <https://www.ccsenet.org/journal/index.php/ijbm/article/view/11198>
- **Mitra (2011)**, "How rewarding is technical analysis in the Indian stock market?" **[S]**.
  - 1998–2008, four indices; returns "cannot be exploited fully due to real world transaction costs".
  - Venue and pages were NOT VERIFIED (ResearchGate returned 403).
- **2005 Rutgers conference paper** (S&P CNX Nifty, 1996–2003) **[S]**.
  - Found MA rules beat buy-and-hold after 0.5–1 % costs, mostly for short MAs.
  - This is a **conference paper on an earlier, less efficient period**, and was superseded by the two later studies above.
  - <http://www.centerforpbbefr.rutgers.edu/2005/Paper%202005/PBFEA037.doc>
- **Not found:** any peer-reviewed India study of the **200-DMA** or the **10-month SMA** on Nifty TRI, out of sample, that models
  STT and capital-gains tax. This is NOT VERIFIED and is a gap we must fill ourselves.

### 3.4 NSE momentum indices: methodology and record [P]

#### Methodology

Sources:
- the 2020 launch white paper, read in full;
- the April-2026 white paper "The Science of Momentum", read in full.

Both were downloaded once to the session scratchpad for reading only and are not stored in the repo.
- <https://www.niftyindices.com/docs/default-source/indices/nifty200-momentum-30/nifty200_momentum_30_index_whitepaper_sep_20.pdf>
- <https://www.niftyindices.com/docs/default-source/indices/nifty200-momentum-30/momentum-strategy-whitepaper_2026.pdf>

**Score.** "The normalised momentum score is based on 6-month and 12-month price return, adjusted for its daily price return
volatility". The steps are below. The exact volatility definition (log vs simple returns, window alignment, whether the most recent
month is skipped) is NOT VERIFIED; it is in the methodology document, which was not opened.
1. Momentum ratio = return ÷ σ(daily returns, 1 year).
2. Cross-sectional z-score of each ratio.
3. 50/50 average of the 6-month and 12-month z-scores.
4. Normalised score = 1 + Z if Z ≥ 0, else 1/(1 − Z).

Steps 1–4 are confirmed by the white-paper text plus secondary summaries [S].

**Selection and weights.**
- Top 30 (Nifty 200) or top 50 (Midcap 150, Nifty 500).
- Weights = score × free-float market cap, capped at "the lower of 5% or 5 times the weight of the stock in the index based only
  on free float market capitalization".
- "A buffer based on normalised momentum score ranks is applied to reduce turnover". This is the Novy-Marx–Velikov buy/hold
  spread idea.
- Rebalancing is **semi-annual**.
- Eligibility: 1-year listing history. Nifty200 Mom 30 requires F&O stocks. The Midcap 150 and Nifty 500 versions exclude non-F&O
  stocks that hit circuit limits on ≥20 % of days, plus liquidity and pledge screens (2026 WP, Exhibit 01).

**Backfill.** Base date 01-Apr-2005. **Launched 25-Aug-2020** (press release). All results before launch are backtests built with
hindsight about which rule NSE chose to launch.

#### Headline results, April 2026 white paper (TRI, gross of any fund cost, to 27-Feb-2026)

| Index | Since Apr-2005 CAGR | Parent CAGR | Max drawdown (index / parent) |
|---|---|---|---|
| Nifty200 Momentum 30 | **19.19 %** | 15.08 % (Nifty 200) | **−67.7 %** / −63.7 % (27-Oct-2008) |
| Nifty Midcap150 Momentum 50 | 23.00 % | 17.24 % | −72.5 % / −72.9 % (09-Mar-2009) |
| Nifty500 Momentum 50 | 21.94 % | 18.85 % | −70.2 % / −63.7 % (27-Oct-2008) |

#### NSE's own caveats (2026 WP)

- "During downward market phases, the same momentum exposure can lead to sharper drawdowns, causing relative underperformance".
- Calendar-year excess for N200 Mom 30 vs Nifty 200:
  - 2009: **−19.47 pp**
  - 2022: −10.36 pp
  - 2025: **−14.13 pp**
  - 2008: −3.95 pp (index −60.04 %)
- It beat its parent in 15 of 20 calendar years.

#### Turnover (2026 WP, Exhibit 11)

"Churn represents the percentage of the index weight that is replaced during each rebalancing". For the semi-annual Nifty200 Mom 30:

| FY22 | FY23 | FY24 | FY25 |
|---|---|---|---|
| 101 % | 112 % | 115 % | 110 % |

- Quarterly rebalancing adds "around 20% - 70% extra annual churn" and did **not** improve long-run returns for N200 Mom 30
  (17.12 % vs 19.19 % since inception).
- **This was itself a specification search** (semi-annual vs quarterly) run by the index provider in-sample.

#### Live-period check [C]

The 2026 WP calendar-year table supplies index returns and excess returns. The parent's return is derived as index minus excess.

Formula: CAGR = (∏(1 + rᵢ))^(1/n) − 1, computed in Python `Decimal`.

| Window | N200 Mom 30 CAGR | Nifty 200 CAGR | Excess (pp/yr) | Years positive |
|---|---|---|---|---|
| CY2006–2019 (14 y, **backfilled backtest**) | 17.53 % | 11.94 % | **+5.59** | 11/14 |
| CY2021–2025 (5 y, **live, post-launch**) | 19.00 % | 16.21 % | **+2.79** | 3/5 |

- The live-period excess is about **50 % of the backtest excess**.
- NSE's 5-year figure to Feb-2026 (almost all post-launch) is 18.15 % vs 14.42 % (+3.73 pp) **[P]**.
- **Positive but decayed, and 5 years is far too short for statistical significance.** With annual excess SD on the order of 10–15 pp
  (from the table), the t-stat on 5 annual observations is well below 2. That t-stat is an estimate, NOT VERIFIED by a formal test.

**Data-quality finding.** We tried to back out the post-launch CAGR (Sep-2020 to Feb-2026) from the since-inception figures in the
2020 WP (18.6 % / 12.7 % to 31-Aug-2020) and the 2026 WP (19.19 % / 15.08 %). The Nifty 200 result, about 22 %/yr, is
implausibly high. The two papers' since-inception parent figures therefore **do not appear to be on a comparable basis**; the cause
is NOT VERIFIED. **The engine must never splice NSE white-paper numbers from different publications.** It must compute from one
imported TRI series.

### 3.5 Market and practitioner reports on the 2024–25 momentum drawdown [S] (non-peer-reviewed)

These are context only, not evidence.
- Mirae Asset presentation: peak-to-trough fall of about −31.6 % to −34.0 %, Sep-2024 to Apr-2025.
- Value Research: index fund turnover of "124.24 per annum" (May-2025).
- Business Standard: 19 of 30 constituents replaced in the Dec-2025 rebalance; about ₹16,000 cr expected churn.
  <https://www.business-standard.com/markets/news/nifty200-momentum30-a-flip-of-index-switch-jolts-16k-cr-across-the-grid-125121400388_1.html>
- Samco MF: the first major decline "where Momentum is underperforming the broad market in the decline phase".
- **Risk from predictable rebalances.** Rebalances are scheduled and the methodology is public. Large AUM (> ₹17,000 cr across 24
  passive funds, 2026 WP [P]) means the rebalance trades are predictable, so front-running and impact costs are a plausible drag.
  Its size is NOT VERIFIED.
- **Non-peer-reviewed backtests** (GitHub `pramodathani/jegadeesh-titman-momentum-india`; backtestindia.com) report long-only
  momentum CAGRs of about 14–19 % with maximum drawdowns of about −70 % to −73 %. **Not peer-reviewed; methodology not audited;
  NOT VERIFIED.** They are cited only because they agree with the drawdown magnitude in NSE's own data.

---

## 4. India costs and tax

### 4.1 Costs per trade for equity delivery

Sources: Zerodha charges page and STT support article **[P]**, plus the repo's tax document.
- <https://zerodha.com/charges/>
- <https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/how-is-the-securities-transaction-tax-stt-calculated>

| Item | Rate | Note |
|---|---|---|
| STT | **0.1 % buy + 0.1 % sell** | "Equity delivery and intraday rates remain unchanged" after the 1-Apr-2026 F&O change |
| Stamp duty | 0.015 % buy side | — |
| NSE transaction charge | 0.00307 % | Third-party sites quote 0.00297–0.00322 %; the rate drifts |
| SEBI fee | ₹10 / crore | — |
| GST | 18 % on (brokerage + SEBI + exchange charges) | — |
| DP charge | ₹15.34 per scrip per sell day | — |
| Brokerage | ₹0 (this broker) | Broker-specific |

**Round trip, statutory only [C]:** about 0.1 + 0.1 + 0.015 + 2 × 0.00307 ≈ **0.221 %**, plus DP and GST.

**Impact cost and spread for Nifty 200 / Midcap names are NOT VERIFIED.** The engine must take them as a user-visible parameter with
a stress range (for example 0.1–0.5 % one-way). It must not hard-code a number.

**Equity MF route** (repo `indian-instruments-and-tax.md`): STT 0.001 % on redemption, stamp duty 0.005 % on purchase. The fund's
internal trading costs and STT sit inside NAV.

### 4.2 Tax

Source: repo `indian-instruments-and-tax.md`, VERIFIED-PRIMARY rows EQ-STCG and EQ-LTCG.
- **STCG 20 %** (s.111A → s.196) on listed equity or equity-oriented MF held ≤12 months.
- **LTCG 12.5 %** above ₹1.25 lakh a year (s.112A → s.198).
- Surcharge and cess are as in that document.

A DIY momentum book with about 110 % annual churn and 6-month holds realises most gains short-term. A momentum **index fund** does
its churn inside the fund. Fund income is exempt under s.10(23D) **[S]**: the "exemption applies only to the income of the mutual
fund and not to the capital gains made by the unit holders", so tax is deferred to redemption. The section number under the Income-tax
Act 2025 is NOT VERIFIED.

### 4.3 Illustrative 10-year comparison [C]

**These are scenario assumptions, not forecasts.**

Inputs and assumptions:
- ₹10,00,000 invested.
- Gross returns are NSE's since-inception TRI: 19.19 % (momentum) and 15.08 % (Nifty 200).
- Fund: TER deducted yearly; LTCG 12.5 % on gain above ₹1.25 lakh at the end; surcharge and cess ignored.
- DIY: **worst case**, all of each year's gain realised as STCG at 20 %. Annual cost is churn 1.1 × 0.221 % ≈ 0.24 %, or 0.74 % with
  an assumed 0.5 %/yr impact cost.

| Route | Assumption | After-tax CAGR |
|---|---|---|
| Momentum index fund | TER 0.3 % | **17.64 %** |
| Momentum index fund | TER 1.0 % | 16.97 % |
| Nifty 200 index fund | TER 0.3 % | 13.71 % |
| DIY long-only momentum | costs 0.24 %/yr | **15.16 %** |
| DIY long-only momentum | costs 0.74 %/yr | 14.76 % |

The script was run with `python3 -I` (Decimal). Its logic:
`fund: V = P·(1+r−TER)^10 − 0.125·max(0, gain − 125000)`
`DIY: V ← V + g − 0.20·g with g = V·(r − cost)`

**Reading:**
- Even with **backtest** gross numbers, tax cuts the DIY edge from about +4.1 pp to about +1.5 pp.
- Apply the ~50 % live-period decay from §3.4 and the edge is plausibly zero or negative after tax for DIY.
- The fund wrapper keeps most of the gross edge. **Momentum, if used at all, belongs in the app as a fund-ranking candidate, not as
  stock trades.**
- Real TERs for specific momentum funds were not checked; they are NOT VERIFIED and must come from AMFI/SEBI disclosures at runtime.

### 4.4 Shorting

SEBI circular SEBI/HO/MRD/MRD-PoD-3/P/CIR/2024/1 (05-Jan-2024) **[S]** says:
- "Naked short selling shall not be permitted".
- Retail may short but must settle; in practice that means intraday or SLB.
- Short selling is limited to F&O securities.

The academic long–short WML is therefore **not implementable** for this user. Only the long leg is usable, and Daniel & Moskowitz
show the crash protection that the short leg would give is not the main benefit anyway.

---

## 5. Skeptical checks: data mining, survivorship, backfill

| Risk | Where it bites | Evidence / mitigation |
|---|---|---|
| **Backfill / selection bias** | NSE indices 2005–Aug-2020 | The rule was chosen and launched after seeing history. Live excess is about half the backfilled excess [C]. Always split "backtest" from "live" in UI and engine. |
| **Specification search** | 6- vs 12-month, z-score normalisation, 30 vs 50 names, semi-annual vs quarterly | NSE itself compared rebalance frequencies in-sample. Our engine must **freeze one spec before testing** and report the number of variants tried (Deflated Sharpe; HLZ t > 3). |
| **Survivorship** | Stock-level India 1995–2001 (3,184 vanished firms) | IIMA adjusts. Free stock data cannot. **Stock-level backtests are BLOCKED** without point-in-time constituents and delisting returns. |
| **Post-publication decay** | Everything | McLean–Pontiff: −58 %. NSE live data: about −50 %. Haircut any backtest excess by at least 50 % in the user-facing expectation, or show both. |
| **Crash / rebound risk** | 2009, 2025 | Show calendar-year excess, maximum drawdown and time-to-recover. Never show CAGR alone. |
| **Short sample** | 5 live years | Insufficient for significance. Status stays "evidence: partial". |
| **Costs omitted** | All index/TRI and academic gross numbers | Fund route: TER + tracking difference from AMFI NAVs. DIY: BLOCKED. |
| **Tax omitted** | All published studies | Model STCG/LTCG with the repo rule tables (ADR-0009). |
| **Lookahead** | Signal computed on day-t close and traded on day-t close | Faber's rule does exactly this. Our spec must execute at t+1 (§6). |

---

## 6. Rule specifications

Each spec below states what is robust enough to implement deterministically and under what condition it may be shown. All are pure
functions over a price or TRI series with `as_of`, using Decimal arithmetic. They read no clock and do no I/O, in line with repo
rules.

### S-C (recommended to build): momentum factor sleeve via index fund

**Status:** evidence VERIFIED (partial live record). Data REQUIRES CONFIGURATION.

**What it is.** It is **not a timing signal**. A momentum index fund (e.g. a Nifty200 Momentum 30 or Midcap150 Momentum 50
tracker) is shown as a *candidate* in the existing ranking (ADR-0005). The index provider does the semi-annual rebalancing inside
the fund.

**Inputs:**
- AMFI NAV history of the fund (live source; short history since about 2021);
- optionally, a user-imported TRI CSV from niftyindices.com for the long history. This follows the return-target-feasibility policy:
  manual import only, never automated, with `source`, `retrieved_at` and a hash.

**Mandatory outputs alongside it:**
- backtest vs live split at 25-Aug-2020;
- max drawdown (≈ −68 % to −73 %);
- worst calendar-year excess (−19.47 pp);
- churn (~110 %/yr);
- the decay statement;
- a tax note: STCG 20 % if held ≤12 months, so the minimum sensible horizon is >12 months.

**Supervisor rule:** abstain if the fund NAV history is shorter than the comparison window, or if TER or tracking data are missing.

### S-E (test only, do not ship): 10-month SMA / 200-DMA trend filter on Nifty 50 or Nifty 500 TRI

**Status:** NOT VERIFIED. The engine abstains until the gates in §7 pass.

**Frozen spec to pre-register:**
- **Observation:** month-end TRI close `C_m`.
- **Signal:** `S_m = 1 if C_m > SMA10_m else 0`, where `SMA10_m = mean(C_{m-9..m})`.
- **Execution:** the switch executes at the **first trading day close of month m+1** (no same-close execution).
- **Out asset:** a liquid or overnight fund NAV from AMFI, or an index T-bill series.
- **Costs:** fund route: exit load 0, stamp 0.005 %, STT 0.001 %. ETF route: §4.1 table plus an impact parameter.
- **Tax:** each exit realises STCG or LTCG by lot (FIFO). The ₹1.25 lakh exemption is tracked per financial year.
- **Benchmark:** buy-and-hold of the same TRI or fund, **after tax at the end of the horizon**.
- **Variants:** one only (10-month). A daily 200-DMA would be a **second trial** and must be counted.

### S-D (test only): 12-1 absolute momentum on index

**Status:** NOT VERIFIED.

`S_m = 1 if C_{m-1}/C_{m-12} − 1 > r_f(12m) else 0`. Execution, costs and tax are as in S-E. Huang et al. 2020 predict that this will
roughly match a sample-mean strategy. Expect abstention.

### S-F (test only): dual momentum across Nifty 500 TRI, a gold ETF NAV and a G-sec index

**Status:** NOT VERIFIED.

- Rule: pick the highest 12-month total return. Hold it only if its return beats the T-bill. Otherwise hold the liquid fund.
- Limitation: the history starts at gold ETF inception, 2007 (repo feasibility doc). That gives about 19 annual decisions, which is
  too few for a t > 3 claim, so it will almost surely abstain.

### S-A/B (blocked): stock-level 12-1 momentum and NSE-score replication

**Status:** BLOCKED. There is no licence-clean, survivorship-free stock data, and no paid APIs are allowed.

If data were ever licensed, the deterministic spec would be:
- **Score:** the NSE normalised score from §3.4, which also covers the Barroso–Santa-Clara volatility idea.
- **Universe:** point-in-time Nifty 200.
- **Rank buffer:** enter at rank ≤ 30, exit at rank > 45. This follows the Novy-Marx–Velikov buy/hold spread. The exact NSE buffer
  is NOT VERIFIED.
- **Rebalance:** semi-annual.
- **Costs and tax:** STT, stamp, impact and STCG modelled per lot.

---

## 7. Acceptance gates before any signal may be emitted

These extend `docs/forecasting/validation-methodology.md` §6. A signal must pass all of them:

1. **Pre-registration.** The spec, parameters and benchmark are committed before the test, with a hash in the run record. Every
   variant tried is counted.
2. **Walk-forward out-of-sample.** Signals are computed only from data ≤ `as_of`, with execution at t+1. Report the OOS segment
   separately. For NSE strategy indices, the OOS segment is post-launch only.
3. **After-cost, after-tax comparison** against buy-and-hold of the same exposure, using the repo tax rule tables, lot-level FIFO, and
   the ₹1.25 lakh LTCG exemption.
4. **Significance.** HAC t-stat on the monthly after-tax return difference must exceed **3.0** (Harvey–Liu–Zhu). Also report the
   Deflated Sharpe Ratio given the number of trials.
5. **Robustness.** Same sign in ≥ 2 of 3 sub-periods (e.g. pre-2010, 2010–2019, 2020+), and on both Nifty 50 and Nifty 500.
6. **Risk.** Max drawdown and worst 12-month relative return are disclosed. Whipsaw count per year is disclosed.
7. **Decay haircut.** User-facing expected excess = OOS estimate × 0.5 or less (McLean–Pontiff, NSE live), or the full distribution
   is shown.
8. **Abstain** if any input is missing or the gates fail. Output: "No suitable signal — evidence insufficient", with the failing
   gate named.

**Expected outcome today:**
- S-E, S-D and S-F will most likely **fail gate 4**, given the global out-of-sample record (Zakamulin, Huang et al.) and India's MA
  record (Mitra).
- S-C is not a signal and does not need gate 4. It is a disclosed-risk fund candidate.

---

## 8. Open items (NOT VERIFIED)

- The exact NSE volatility definition and buffer thresholds. Read the methodology document at
  <https://www.niftyindices.com/> → Strategy indices → methodology.
- Whether the niftyindices.com Terms of Use match the NSE ToU, which bans use "for any gaming, virtual trading or simulation
  activities". A backtest may count as "simulation". This needs the user's decision.
- Licence of the IIMA data library. No licence text was found.
- Current TERs and tracking differences of each momentum index fund (AMFI/SEBI disclosure).
- India's per-country coefficient in Rouwenhorst (1999) and Griffin-Ji-Martin (2003).
- Any peer-reviewed, out-of-sample, after-tax India study of 200-DMA or TSM on Nifty. None was found.
- Impact cost for Nifty 200 / Midcap 150 constituents at rebalance dates.
- The source of the inconsistency between the 2020 and 2026 NSE white-paper since-inception parent figures.

---

## 9. Sources

All accessed 2026-10-15.

**Primary, read directly:**
- NSE Indices, *Nifty200 Momentum 30 Index* white paper, Sep-2020:
  <https://www.niftyindices.com/docs/default-source/indices/nifty200-momentum-30/nifty200_momentum_30_index_whitepaper_sep_20.pdf>
  Quote: "A buffer based on normalised momentum score ranks is applied to reduce turnover".
- NSE Indices, *The Science of Momentum*, Apr-2026:
  <https://www.niftyindices.com/docs/default-source/indices/nifty200-momentum-30/momentum-strategy-whitepaper_2026.pdf>
  Quote: "during downward market phases, the same momentum exposure can lead to sharper drawdowns".
- Agarwalla, Jacob, Varma, IIMA W.P. 2013-09-05 (revised):
  <https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/four-factors-India-90s-onwards-IIM-WP-Version.pdf>
  Quote: "average annual return of the momentum factor was 21.9%".
- IIMA data library: <https://faculty.iima.ac.in/~iffm/Indian-Fama-French-Momentum/>
- Daniel & Moskowitz, NBER WP 20439: <https://www.nber.org/system/files/working_papers/w20439/w20439.pdf>
  Quote: "the crash performance is mostly attributable to the short side".
- Mitra (2011), IJBM abstract: <https://www.ccsenet.org/journal/index.php/ijbm/article/view/11198>
- Zerodha charges: <https://zerodha.com/charges/>; Zerodha STT article (URL in §4.1).

**Secondary (abstract pages or search summaries):**
- Jegadeesh & Titman 1993 and 2001; Rouwenhorst 1999; Griffin-Ji-Martin 2003
- Moskowitz-Ooi-Pedersen 2012; Hurst-Ooi-Pedersen 2017; Huang et al. 2020; Goyal & Jegadeesh 2018
- Novy-Marx & Velikov 2016; Barroso & Santa-Clara 2015; McLean & Pontiff 2016; Harvey-Liu-Zhu 2016
- Faber 2007; Zakamulin 2014; Antonacci 2017
- Chui et al. 2023; Singh & Walia 2020; Agarwalla et al. 2017 *Vikalpa*; Maheshwari & Dhankar 2017
- SEBI short-selling circular 2024 (via taxguru/CDSL)
- s.10(23D) summaries
- Value Research, Business Standard, Mirae, Samco items (context only)

URLs are inline above.

**Repo cross-references:**
- `docs/research/indian-instruments-and-tax.md`: EQ-STCG, EQ-LTCG, STT-MF-01, STAMP-MF-01.
- `docs/research/return-target-feasibility.md`: drawdowns; data-import policy §4.3; Appendix A.
- `docs/data/source-registry.md` §2.11: NSE ToU BLOCKED.
- `docs/forecasting/validation-methodology.md` §6: promotion rule, DSR, multiple testing.
