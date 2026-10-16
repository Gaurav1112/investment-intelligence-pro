# Verification: research-fundamentals-data.md (wave 1, adversarial check)

- **Report checked:** `docs/research/wave1/research-fundamentals-data.md`
- **Date:** 2026-10-15. Every source below was accessed on 2026-10-15.
- **Method:**
  - Primary PDFs were downloaded with `curl` and converted locally with `pdftotext`: the IIMA WP 2022-11-01, the SEBI 2019 circular (ca2013.com mirror), Harshita et al. 2018, and Pincus et al. 2007.
  - The NSE Terms of Use page was downloaded with `curl` (HTTP 200), and its text was extracted locally.
  - The RePEc abstract was extracted from raw HTML.
  - The other pages were checked with WebFetch or WebSearch, and those claims are marked "via search".
  - This is research, not legal or investment advice.
- **Verdict labels:** CONFIRMED / WEAKENED (directionally right but overstated or missing a material caveat) / REFUTED.

## Summary

| ID | Claim | Verdict |
|---|---|---|
| FD-1 | NSE/BSE XBRL feeds cannot be automated; OSS scrapers inherit the ban | **WEAKENED** |
| FD-2 | Stock-level fundamental buy/sell signals must abstain | CONFIRMED |
| FD-3 | Quality factor has strong Indian evidence | **WEAKENED** |
| FD-4 | Pledging is a risk indicator; SEBI 50%/20% thresholds give a cited flag | **WEAKENED** |
| FD-5 | Point-in-time correctness requires `published_on` per figure | CONFIRMED |
| FD-6 | XBRL parsing feasible; namespace changed in 2025 | CONFIRMED (stays NOT VERIFIED officially) |
| FD-7 | PEAD / F-score / accruals evidence in India is mixed, old or contrary | CONFIRMED (with nuance) |
| FD-8 | Factor libraries have unclear or academic-only licences | CONFIRMED |
| FD-9 | Company-website terms are not verifiable in general | CONFIRMED |

No finding is refuted outright. Four claims are mostly right but overstated, and the report has several material omissions (see the end). The most consequential is §5, the report's main "usable today" recommendation: quality-index fund NAV histories on AMFI are only about 13–25 months long. The project's MF machinery therefore cannot yet produce a backtest-supported evaluation of these funds.

---

## FD-1: NSE/BSE automation ban (WEAKENED)

**What holds (NSE).** The NSE ToU text, extracted locally from https://www.nseindia.com/static/nse-terms-of-use on 2026-10-15, contains every quoted clause verbatim:
- "User is prohibited to conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting) on or in relation to our Website / Mobile Application."
- Content shall not be "stored (either in hardcopy or in an electronic retrieval system) … without prior written permission of NSE."
- "it shall not, in any form and manner, use or make the data or Content available on the Website / Mobile Application, for any gaming, virtual trading or simulation activities under any circumstances whatsoever."

The NSE automation ban is **CONFIRMED**.

**What is overstated or missing:**

1. **The report omits a download exception.** The same paragraph begins: "Unless the information or Content is available for download, not to aggregate, copy or duplicate in any manner any of the content or information which is available on Website". This sentence bears directly on path (b), a user-downloaded XBRL file. It suggests NSE treats downloadable content differently for copying and aggregation. It does not cancel the separate "stored … in an electronic retrieval system" clause, so path (b) stays ambiguous. Still, the report's §0.2(b) and §7.1 present the storage clause as the only relevant text, which is incomplete.
2. **The "simulation" clause is not applied to path (b).** The report quotes "simulation activities" in §0 but never applies it to path (b). Under the clause, NSE content may not be used for "simulation activities under any circumstances whatsoever", even when it was downloaded manually. A backtest is arguably a simulation. So NSE-sourced XBRL, even typed or downloaded by hand from nseindia.com, should never feed a backtest. Path (b) is therefore at most a source for descriptive cards, never for signal validation. The report does not say this.
3. **BSE is not an automation ban in the text.** The BSE disclaimer is at https://www.bseindia.com/static/about/disclaimer.htm (via search; the www.bseindia.com/disclaimer.html shell returned HTTP 200 but its content is loaded by JavaScript). It says: "Any reproduction, redistribution or transmission, for consideration or otherwise, of any such information contained on the Website is strictly prohibited". That is a reproduction and redistribution prohibition. A search found no BSE India clause that names scraping or automated access word for word. The BSE Plus terms (https://bseplus.bseindia.com/Terms_condition_Bseplus.htm, via search) say the site "is for your personal and non-commercial use" and forbid "copy, distribute … reproduce". Treating BSE automation as BLOCKED is a defensible conservative reading of "reproduction", but the report presents it as the same kind of ban as NSE's, and the text does not say that.
4. **The BSE quote was available.** The report says the BSE quote could only come from the source registry (HTTP 403). The text is in fact reachable at the `/static/about/disclaimer.htm` URL via search, so the registry quote can now be re-sourced.
5. **The OSS-scraper conclusion is confirmed.** The `india-xbrl-filings` README (https://github.com/dhananjaym182/india-xbrl-filings, WebFetch) says: "download behavior may violate the exchanges' terms of use — you use this tool entirely at your own risk" and "Personal / educational use only". It is MIT-licensed. The code licence does not grant data rights, so treating it as a BLOCKED data source is correct.

**Net:** BLOCKED for automated NSE collection is correct. BLOCKED for BSE should carry the rationale "reproduction prohibited (conservative reading)", not "automation prohibited". Path (b) needs the download exception and the simulation clause added.

## FD-2: Stock-level fundamental signals must abstain (CONFIRMED)

The project rule requires an out-of-sample, cost- and tax-aware backtest that this project can reproduce. Every paper re-read here uses a paid database:

| Paper | Database | Evidence (local text) |
|---|---|---|
| IIMA WP | CMIE Prowess | "firm-level financial data … drawn from the CMIE Prowess database" |
| Harshita et al. | Ace Equity | "The data sources employed are Ace Equity®" |
| Pincus et al. | Global Vantage | Also licensed |

None reports returns net of Indian costs and tax. The abstention verdict follows from the project's rules, independent of how strong the effects are.

Minor overstatement: "mostly long-short" is accurate for PEAD and QMJ, but the IIMA paper does report a long-only alpha (0.69%/month gross). Long-only does not rescue the signal, because the cost, tax and reproducibility gaps remain.

## FD-3: Quality factor has "strong" Indian evidence (WEAKENED)

**Quotes confirmed verbatim** in https://www.iima.ac.in/sites/default/files/2022-12/Wp-2022-11-01.pdf (local pdftotext):
- "The QMJ factor earns a four factor alpha of 0.92% per month". The table value is 0.917.
- "A long-only Quality factor earns an alpha of 0.69% per month". D10 is 0.694.
- "The key drivers of the alpha are profitability and payout".
- "26-year period from April 1995 to March 2021"; "top 1,000 firms by market capitalization"; "CMIE Prowess".
- "It is somewhat surprising that higher growth does not in itself contributes positive alpha".
- Churn: "about 249%" for momentum against "only about 87%" for quality.
- Top-250: "significant outperformance, albeit with marginally lower alpha".

**Why "strong" is overstated:**
1. **It is a single working paper.** The IIMA series exists "to help faculty … test their research findings at the pre-publication stage". This check found no peer-reviewed version (NOT VERIFIED either way).
2. **The results are in-sample and gross.** The paper argues low churn means costs matter less ("much of the alpha may be eaten away by transaction costs. Here also, the quality factor turns out to be quite attractive"). It does not compute net-of-cost or net-of-tax returns.
3. **The churn comparison is not like-for-like.** Footnote 4 defines momentum churn as a sum of monthly drop percentages, and quality churn as the annual percentage of dropped stocks. The report quotes 87% against 249% without this caveat.
4. **The author citation is wrong.** The authors are Joshy Jacob, Pradeep K.P. and Jayanth R. Varma. The report cites "Jacob, K.P. & Varma", which reads as two authors.
5. **The report missed decay evidence that is available.** It said the "Fading Away" paper could not be read. Its abstract is available via search: https://journals.sagepub.com/doi/abs/10.1177/0972150918811248, Sharma, Subramaniam & Sehgal, *Global Business Review* 22(1), 2021, NSE 500, July 2005–June 2016. It reports that value and momentum anomalies "are explained by risk models", and that size and volume "seem to have faded substantially". Quality was not tested, but the decay signal for Indian anomalies is now partly VERIFIED.

The direction is supported: quality has had positive historical Indian alpha. Calling it "strong" for a real-money tool is overstated.

## FD-4: Promoter pledging and the SEBI thresholds (WEAKENED)

**SEBI circular: CONFIRMED** from local text of the ca2013.com mirror:
- The combined encumbrance "equals or exceeds: a) 50% of their shareholding in the company; or b) 20% of the total share capital".
- "within two working days from the creation of such encumbrance".
- Repeat disclosure "on every occasion, when the extent of encumbrance … increases further".
- Effective "October 01, 2019".

Caveats on this source:
- The copy is a third-party mirror, not sebi.gov.in.
- The report's table says Annexure-II is "to be given manually". That wording is **not in the circular text** (NOT VERIFIED).
- Search results say the requirement was later consolidated in the SEBI SAST Master Circular of 16 Feb 2023 (via search, https://ca2013.com/toc-regulation-31/). The flag should cite the master circular as the current instrument.

**Chauhan, Mishra & Spahr abstract: CONFIRMED** verbatim from https://ideas.repec.org/a/bla/finmgt/v50y2021i1p261-280.html: "exacerbates stock volatility, fosters lower risk capital investments, adversely affects firm values, and impedes longer‐term performance", 1,452 firms.

**Overstated parts:**
1. **"Crash risk" is not in the cited paper.** The report's §6.3 `PLEDGE_INCREASED_QOQ` wording is "associated with higher volatility and crash risk in published Indian studies", and it cites Chauhan et al. Chauhan's abstract does not mention crash or tail risk. The crash-risk sources (Kalia 2024, Prime Database) are NOT VERIFIED by the report's own admission. The flag text must drop "crash risk" or cite a verified source.
2. **The paper studies the level of pledging, not its quarterly change.** The abstract concerns "pledging relatively large proportions". A QoQ-increase flag cited to this paper extrapolates beyond it.
3. **"Not a return signal" is a project choice, not the paper's finding.** The paper reports that pledging "impedes longer-term performance". Treating pledging as risk-only is the right abstention under project rules, but it should not be attributed to the paper.
4. **The encumbrance definitions changed in 2025, and the report omits it.** A SEBI circular dated 20 March 2025 changed the shareholding-pattern format to show NDUs, other encumbrances and total encumbered shares separately, from the quarter ending 30 June 2025 (via search, Business Standard https://www.business-standard.com/markets/news/sebi-tweaks-disclosure-norms-for-shareholding-patterns-to-improve-clarity-125032001282_1.html). The SEBI threshold covers all encumbrances (pledge, lien, NDU and so on), not pledges alone. A "pledge %" computed from the old columns is not comparable across that break and is not the same quantity as SEBI's threshold. The flag needs a definitions-version field.

## FD-5: Point-in-time correctness (CONFIRMED)

The deadlines are confirmed via secondary compliance summaries (taxguru.in, via search):
- **Reg 33(3)(a):** "within forty-five days of end of each quarter"; 60 days for annual results.
- **Reg 31:** "within twenty one days from the end of each quarter" and "within ten days of any capital restructuring … exceeding two per cent".

The report correctly labels these as secondary, since the SEBI consolidated text was not opened.

On SAST encumbrance: since 1 April 2022, depository-recorded encumbrances moved to System Driven Disclosures, and the physical obligation was scrapped (via search, ca2013.com TOC Reg 31; natlawreview). This is consistent with the report.

The design rule (`published_on ≤ d`; no inferred fallback date) is sound and matches project rules.

## FD-6: XBRL parsing and the 2025 namespace change (CONFIRMED as NOT VERIFIED)

- **Arelle licence:** "Apache License 2.0" is confirmed (https://github.com/Arelle/Arelle, WebFetch).
- **Namespace change:** confirmed by a second secondary source, the `india-xbrl-filings` repo summary via search:
  - Legacy taxonomy "in-bse-fin (published by BSE)".
  - New taxonomy "in-capmkt (published by SEBI) … coverage 2025 onward only".
  - "32 of 32 sampled old-format filings used in-bse-fin".
- **Status:** still not checked against an official SEBI or NSE taxonomy page, so the NOT VERIFIED label is correct.
- **New detail:** the same source mentions separate taxonomy packages for NBFC, banking, general insurance, life insurance and "other than banks". The concept map must therefore be versioned per industry template as well as per taxonomy version. The report only says "per taxonomy".

## FD-7: PEAD, F-score and accruals (CONFIRMED, with nuance)

**PEAD (Harshita et al. 2018),** https://www.scirp.org/pdf/tel_2018102515432009.pdf, local text:
- "going long on the stocks with the highest SUE codes and going short on the stocks with the lowest SUE codes generates statistically significant returns of 6 per cent during 64 days post the earnings announcement".
- "The date of sample selection is 31 March 2014".
- Data source: Ace Equity.

Missed detail: the paper finds the spread is "6 per cent higher in stocks with low coded size". The effect concentrates in smaller stocks, where costs are highest. This strengthens the abstain verdict.

**Accruals (Pincus et al. 2007),** local text: "Hong Kong, India, The Netherlands, Sweden, and Switzerland … abnormal returns … are negative but not statistically significant at the 10 percent level." The sample is 1994–2002 with n = 1,245 Indian firm-years, and the authors add: "One plausible explanation for the insignificant results is lack of power". This is "insignificant / low power", not "contrary". The "contrary" label rests only on an unverified multi-anomaly study.

## FD-8: Factor-library licences (CONFIRMED)

**IIMA** (https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/, WebFetch):
- Citation request only, for Agarwalla, Jacob & Varma (2013), W.P. 2013-09-05.
- No licence text.
- Data runs Oct 1993 – Dec 2025, release 2025-12.

**SCDLDS** (https://quantfin.scdlds.com/, WebFetch):
- "This library is free to use for academic purposes. If it contributes to your work, please cite us."
- Data runs Oct 2003 – Sep 2026.

**Missed detail:** the SCDLDS page says it screens stocks "from the CMIE Prowess database". Its factor series are derived from a licensed database, which adds a second licensing layer beyond the "academic purposes" grant.

## FD-9: Company-website terms (CONFIRMED)

`curl` to https://www.infosys.com/terms-of-use.html returned **HTTP 403** today, which reproduces the report's result. No general statement can be made, so NOT VERIFIED per company stands.

As noted under FD-1, the BSE disclaimer text is reachable through `/static/about/disclaimer.htm`.

---

## Material omissions

1. **The quality-fund route (§5) has almost no live fund history.** NFO and allotment dates for Nifty200 Quality 30 index funds (via search; e.g., UTI KIM https://d50le8fqeqn06.cloudfront.net/utimf-job/kim/KIM+UTI+Nifty200+Quality+30+Index+Fund+November+2024-779.pdf; https://dhan.co/nfo/sbi-nifty200-quality-30-index-fund-direct-growth/; https://groww.in/nfo/kotak-nifty-200-quality-30-index-fund-direct-growth):

   | Fund | Allotment | Status |
   |---|---|---|
   | UTI | 19 Sep 2024 | — |
   | SBI | 4 Jun 2025 | — |
   | ICICI Pru | 9 Jun 2025 | unconfirmed |
   | Kotak | 14 Jul 2025 | — |

   The HDFC Nifty100 Quality 30 fund's NFO presentation is dated January 2025. On 2026-10-15, the AMFI NAV histories for these funds are therefore about **13–25 months**. That is too short for rolling-return or drawdown evidence, so the project's MF machinery would have to abstain. The only longer live record is the index itself, which goes back to 17 Apr 2018. That record sits on NSE Indices pages, which can only be entered by hand, and it may fall under the NSE "simulation" clause. Whether any Indian quality index fund or ETF has more than 5 years of NAV history is **NOT VERIFIED**. The report presents §5 as usable "today" without noting this.
2. **The NSE ToU download exception and the simulation clause both affect path (b).** See FD-1. NSE-sourced figures should be barred from any backtest.
3. **The 2025 shareholding-pattern format change (NDUs and other encumbrances)** breaks series comparability for any pledge metric. See FD-4.
4. **The "Fading Away" abstract was obtainable** and shows value and momentum explained by risk models over 2005–2016 (NSE 500). See FD-3.
5. **XBRL templates differ by industry** (banking, NBFC, insurance). See FD-6.
6. **The PEAD effect concentrates in small caps.** See FD-7.
7. **The current SEBI instrument for the encumbrance threshold** is the 16 Feb 2023 SAST Master Circular, not only the 2019 circular. See FD-4.
