# Verification: research-evidence-allocation.md (adversarial review)

Wave 1 · topic `evidence-allocation` · Reviewer role: adversarial skeptic · Date: 2026-10-15 · All URLs accessed 2026-10-15.
Report under review: `docs/research/wave1/research-evidence-allocation.md` (not edited).

## Method

- Downloaded and text-extracted (pdftotext) the cited primary PDFs: NSE Nifty 50 factsheet, NSE momentum whitepaper (Apr-2026),
  Cederburg et al. (2020) from the Lehigh copy, the Vanguard rebalancing mirror, MSE Working Paper 242, the DICGC FAQ page, and
  the NSE factsheets for Nifty200 Momentum 30 and Nifty Midcap150 Momentum 50.
- Fetched the abstract pages for Ibbotson & Kaplan (RePEc), DeMiguel et al. (EconPapers) and Trading Economics. Used web search
  for pages that returned HTTP 403 (SSRN, ScienceDirect, Investor.gov).
- Recomputed the Kelly arithmetic in Python.
- Did **not** recompute the companion rolling-window tables (`return-target-feasibility.md`). Those numbers are checked only for
  consistency with the companion document and are marked as such.

## Verdict table

| ID | Claim | Verdict | Main reason |
|---|---|---|---|
| EA-1 | 25 %/yr over 10+ y never achieved on broad Indian TRIs | **WEAKENED** | The numbers match the companion and the factsheet. "Never" holds only for 1995/2005+ TRI history, which has about 2 independent 10-year windows. Pre-1995 Sensex history contradicts a general "never". |
| EA-2 | Trailing returns are end-date sensitive (16.04 % vs 12.77 %) | **CONFIRMED** | 16.04 % is in the whitepaper, Exhibit 03, as Nifty 500 TR at 10 y, as on 27-Feb-2026. |
| EA-3 | Volatility targeting not admissible | **WEAKENED** (the verdict stands; the evidence is misdescribed) | The Cederburg quotes are verified. MSE WP-242 is **not** about Indian factors: it uses CBOE VIX and US Fama-French factors. "72 of 103" refers to combination strategies. |
| EA-4 | Stop-loss and trend timing lack India after-tax OOS evidence; momentum MDD 68–73 % | **CONFIRMED**, with one unsupported sub-claim | Drawdown quote verified verbatim. The Kaminski & Lo highlight is confirmed via a search copy. The body claim that excess return is "mostly in back-calculated history" is unquantified. The launch dates the report left open are verifiable. |
| EA-5 | Kelly input uncertainty makes it unusable | **CONFIRMED** | Recomputed 1.4994, SE 4.028 pp, band −0.108 to 3.106. The choice of σ makes it even less stable. |
| EA-6 | Vanguard 5 % bands, annual/semi-annual; cash flows first in India | **WEAKENED** | The quotes are real, but the mirror is the **November 2015** edition (Zilbering, Jaconetti, Kinniry; 1926–2014; global equity from 1994), not "July 2010, 1926–2009 US data". The "lowest-tax lot first" step ignores the FIFO redemption rule. |
| EA-7 | Strategic allocation dominates; optimisers fail OOS | **WEAKENED** (the sources are confirmed; the framing is overstated) | Ibbotson & Kaplan abstract confirmed verbatim. DeMiguel: 14 models, 1/N and about 3,000 months confirmed via the EconPapers abstract. But the 90 % is a time-series figure that mostly reflects market exposure. The cross-sectional figure is 40 %. |
| EA-8 | Emergency fund: SEBI month count unverified; DICGC ₹5 lakh verified | **CONFIRMED** | DICGC quote verified verbatim on the live page. The Investor.gov phrase was confirmed via a search copy (direct fetch: 403). |
| EA-9 | 10y G-sec 7.39 % (Trading Economics) | **CONFIRMED** as a quote; REQUIRES CONFIGURATION is the right status | The TE page says "eased to 7.39% on October 15, 2026". The report records no TE terms. The licence is personal and non-transferable, so TE must not be a data source. |

Nothing was refuted outright. Three findings are weakened by citation or attribution errors that the report presents as [P]
or as fact.

---

## EA-1 — 25 %/yr over 10+ years: WEAKENED

**What checks out**
- The NSE Nifty 50 factsheet dated "September 30, 2026" (https://www.niftyindices.com/Factsheet/ind_nifty50.pdf) shows:
  - "Base Date November 03, 1995" and "Launch Date April 22, 1996";
  - Total Return since inception "12.12" (QTD −4.91, YTD −12.61, 1 y −7.09, 5 y 6.38);
  - Std. Deviation since inception "22.39".
- The report's figures match.
- The rolling-window figures in the report (0.0 % of 10 y windows ≥ 25 %; best 10 y windows 22.1 / 23.4 / 23.2 / 21.6 %) match
  `return-target-feasibility.md` §2.2 lines 126–142. I did not recompute them from raw TRI data.

**Why it is weakened**
1. **"Never" is a statement about a short sample.**
   - The companion report itself lists about **2 independent** 10-year windows and **1** independent 15-year window for each index.
   - Mid and small-cap history before 2016 is back-calculated.
   - "0 % of 208 overlapping windows" carries the information of roughly two observations.
2. **"Broad Indian index" history did not start in 1995.**
   - BSE Sensex base: 100 on 1-Apr-1979. It closed at 4,091 on 30-Mar-1992 (https://en.wikipedia.org/wiki/BSE_SENSEX: "On 30 March 1992, the SENSEX crossed 4,000 and closed at 4,091").
   - That is a price-only CAGR of about 33 % over 13 years (computed: (4091/100)^(1/13) − 1 ≈ 33.0 %).
   - Some 10-year window ending in 1992 almost certainly exceeded 25 %. The exact 1982 level is **NOT VERIFIED**.
   - That era had high inflation and a closed economy, and is arguably not comparable. The report should say "in the NSE TRI history
     since 1995/2005", not "never happened".
3. The exec-summary wording ("25 % p.a. over 10+ years has never happened") is stronger than the table, which is correctly scoped to
   four TRIs.

**Fix:** scope every "never" to the series and start date, and show `n_eff` beside it.

## EA-2 — End-date sensitivity: CONFIRMED

- NSE whitepaper "The Science of Momentum", April 2026
  (https://www.niftyindices.com/docs/default-source/indices/nifty200-momentum-30/momentum-strategy-whitepaper_2026.pdf).
- Exhibit 03 "Annualised return as on February 27, 2026" gives these Nifty 500 figures: "10 years … 16.04%", "15 years … 13.23%".
  The footnote reads "Data based on TR index values as on February 27, 2026".
- 12.77 % (to 30-Sep-2026) is a companion **[C]** figure that I did not recompute.
- Two causes drive the gap:
  - **The start date moved** from Feb-2016, a market low, to Sep-2016.
  - **2026 losses:** the Nifty 50 TR YTD is −12.61 % on the factsheet.
- Both causes support the rule "always show the window and a distribution".
- Minor caveat: the comparison mixes NSE's published figure with an in-house computation, so method differences are not excluded.

## EA-3 — Volatility targeting: WEAKENED (the verdict stands)

**Verified [P]** in Cederburg, O'Doherty, Wang & Yan, JFE 138 (2020) 95–117 (https://www.lehigh.edu/~xuy219/research/COWY.pdf):
- Abstract: "Volatility-managed portfolios do not systematically outperform their corresponding unmanaged portfolios in direct
  comparisons"; "reasonable out-of-sample versions generally earn lower certainty equivalent returns and Sharpe ratios than do simple
  investments in the original, unmanaged portfolios".
- Introduction: "the real-time combination of volatility-managed and original portfolios earns a lower CER relative to the original
  portfolio in 72 of 103 cases".

**Problems**
1. **MSE WP-242 is misdescribed.**
   - The report's §5 table calls it "Volatility-managed Indian factors … strongest for momentum".
   - The paper is Subramanian & Kayal, "Application of Volatility-Managed Portfolios in the Context of a Volatility Index", August 2023
     (https://www.mse.ac.in/wp-content/uploads/2023/09/WORKING-PAPER-242.pdf).
   - It studies whether the strategy "provides a large utility gain for mean-variance investors for the CBOE Volatility Index (VIX)
     across multiple equity factors". Its factors are "the Fama and French (1993) three-factor model, profitability (RMW),
     investment (CMA) and momentum (MOM) from the Fama and French" library.
   - These are **US** factors. **REFUTED as an Indian study.** The project still has **no** Indian volatility-management evidence of
     any kind, in-sample or out-of-sample.
2. **"72 of 103" is narrower than stated.** It refers to the real-time *combination* strategy (managed plus original, with
   estimated weights). In direct comparisons the paper reports 53 of 103 positive Sharpe differences.
3. **A favourable exception is omitted.** Cederburg et al. note that volatility-managed momentum (MOM), ROE and BAB "contribute to
   large utility gains". This is the case most relevant to a momentum-heavy Indian universe. The report should mention it so a
   future test is pre-registered on it rather than discovered by data mining.
4. **"Single-asset version" is inaccurate.** Cederburg tests 103 equity *strategy* portfolios, not single assets.

## EA-4 — Stop-loss and trend timing: CONFIRMED, with notes

**NSE whitepaper drawdowns, verbatim [P]:** "The maximum drawdowns of Nifty200 Momentum 30, Nifty Midcap150 Momentum 50, and
Nifty500 Momentum 50 were 68%, 73%, and 70%, respectively, whereas their respective parent indices Nifty 200, Nifty Midcap 150,
and Nifty 500 had maximum drawdowns of 64%, 73%, and 64%". Inception is "April 01, 2005".

**Kaminski & Lo (2014):**
- The ScienceDirect page returned 403. Search results reproduce the highlight "If prices follow random walks, stop-loss rules always
  decrease expected returns. If prices exhibit momentum, such rules can add value by reducing losses."
- Open copy: https://dspace.mit.edu/bitstream/handle/1721.1/114876/Lo_When%20Do%20Stop-Loss.pdf. Not opened; status **[S]**, as
  the report says.
- **Omitted:** the 2014 empirical section, which applies stop-losses to index futures. Its abstract (per search copy) reports that
  "at longer sampling frequencies, certain stop-loss policies can increase expected return". Under the momentum branch the evidence
  is mixed, not one-sided.

**Launch dates (left open as NOT VERIFIED in the report):**
- Nifty200 Momentum 30: "Launch Date August 25, 2020", "Base Date April 01, 2005"
  (https://www.niftyindices.com/Factsheet/Factsheet_Nifty200_Momentum30.pdf, as of 30-Sep-2026).
- Nifty Midcap150 Momentum 50: "Launch Date August 16, 2022", "Base Date April 01, 2005"
  (https://www.niftyindices.com/Factsheet/Factsheet_NiftyMidcap150Momentum50.pdf).
- So about 15 and 17 of roughly 21 years are back-calculated.

**Unsupported sub-claim:**
- §6 says the momentum indices' "excess return is mostly in back-calculated history". The report gives no computation for it.
- The whitepaper's 5-year (Feb-2021→Feb-2026, mostly post-launch for Nifty200 Momentum 30) figures still show 18.15 % vs 14.42 %.
- Mark this claim **NOT VERIFIED** until the engine splits pre- and post-launch returns.
- The ABSTAIN verdict does not depend on it.

## EA-5 — Kelly: CONFIRMED

Python recomputation:
- μ = 0.1212 + 0.2239²/2 = 0.14627
- f* = (0.14627 − 0.0711)/0.2239² = **1.4994**
- SE = 0.2239/√30.9 = **4.028 pp**
- f* at μ ± 2 SE = **−0.108 to 3.106**

Additional point that strengthens the finding:
- The same factsheet gives a 5-year σ of **13.82 %**. With that σ, full Kelly is (0.1212 + 0.0095 − 0.0711)/0.0191 ≈ **3.1**.
- The output is as sensitive to the σ window as to μ.

Minor issues:
- The T-bill rate (since 1993) and the equity rate (since 1995) cover different periods.
- The band ignores uncertainty in σ and fat tails.

Neither changes the conclusion. Thorp quote verified on the cited page
(https://www.valueinvestingworld.com/2013/05/ed-thorp-jack-schwager-and-kelly.html): "if you bet half the Kelly amount, you get
about three-quarters of the return with half the volatility".

## EA-6 — Rebalancing: WEAKENED

**Citation error**
- The cited mirror (https://www.financieelonafhankelijkblog.nl/wp-content/uploads/2021/11/Vanguard-ISGPORE.pdf) is dated **"November
  2015"**, authors "Yan Zilbering; Colleen M. Jaconetti, CPA, CFP®; Francis M. Kinniry Jr., CFA".
- Its data run "1926 through 2014": stocks are S&P/US until 1994, then the "MSCI AC World IMI Index from June 1, 1994, through
  2014".
- The report describes it as "July 2010", "Jaconetti, Kinniry & Zilbering", "1926–2009 US data" and "US stock and bond data". All
  four attributes are wrong for the document actually read.
- The count of 1,068 monthly events equals 89 years × 12, which matches 1926–2014, not 1926–2009 (84 × 12 = 1,008).
- The quotes themselves are verbatim in the 2015 edition: "there is no optimal frequency or threshold for rebalancing";
  "annual or semiannual monitoring, with rebalancing at 5% thresholds…"; "Annual rebalancing is likely to be preferred when taxes
  or substantial time/costs are involved"; and 1,068 / 355 / 88 / 0 events.

**Substantive gap: FIFO**
- The report's order of operations, step (2), says "redeem from lots with the lowest tax and exit-load cost first".
- Indian MF redemptions within a scheme and folio are processed **first-in, first-out**. The investor cannot pick lots.
- CBDT Circular 768 (24-Jun-1998) on s.45(2A) applies FIFO to demat holdings, account-wise
  (https://incometaxindia.gov.in/communications/circular/910110000000000355.htm: "the FIFO method would apply"). For non-demat
  folios, FIFO is RTA practice (secondary sources only; **NOT VERIFIED** from a primary SEBI/AMFI document).
- Lot choice therefore exists only *across* schemes, folios or demat accounts. The engine must model FIFO, or it will display
  unattainable tax outcomes.

**Tax rates**
- STCG 20 % and LTCG 12.5 % above ₹1.25 lakh come from the companion doc and were not re-verified here.
- Missing: surcharge and 4 % cess.
- Missing: the **Income-tax Act, 2025** replaced the 1961 Act from 1-Apr-2026 (per search; **NOT VERIFIED** from the primary
  gazette). Rates and section references must be re-checked against the new Act before any rule table is coded.

## EA-7 — Allocation and optimisers: WEAKENED (sources confirmed, framing overstated)

**Ibbotson & Kaplan (2000), FAJ 56(1):26–33.** The abstract on RePEc
(https://ideas.repec.org/a/taf/ufajxx/v56y2000i1p26-33.html) confirms verbatim: "about 90 percent of the variability in returns of
a typical fund across time is explained by policy, about 40 percent of the variation of returns among funds is explained by policy,
and on average about 100 percent of the return level is explained by the policy return level."

**DeMiguel, Garlappi & Uppal (2009), RFS 22(5):1915–1953.** EconPapers
(https://econpapers.repec.org/RePEc:oup:rfinst:v:22:y:2009:i:5:p:1915-1953) gives the opening sentence verbatim. The page summary
says 14 models and seven datasets, none consistently better than 1/N, and that about 3,000 months (25 assets) to 6,000 months
(50 assets) of data are needed. The report marked "3,000 months" NOT VERIFIED. It is supported at **[S]** level.

**Overstatement**
- The exec summary says allocation "explains about 90 % of a fund's return variability" and calls it "the dominant lever".
- The 90 % is the *time-series* figure, which is mostly the effect of being in the market at all.
- For *choosing between* allocations, the relevant figure is the cross-sectional **40 %**.
- The 100 % level result says active management adds nothing on average. It does not say allocation choice determines outcomes.
- The design conclusion (compute consequences, do not optimise) is still well supported.

## EA-8 — Emergency fund: CONFIRMED

**DICGC**
- The live page (https://www.dicgc.org.in/FAQs) says: "Each depositor in a bank is insured upto a maximum of ₹ 5,00,000 (Rupees Five
  Lakhs) for both principal and interest amount held by him in the same right and same capacity".
- The report's engine rule "flag above ₹5,00,000 per bank" is a simplification. The same FAQ says:
  - accounts in a different capacity or right (for example joint accounts with names in a different order) are insured
    **separately**;
  - banks may **set off** the depositor's dues against deposits.
- The flag should say "may exceed", not "is outside" cover.
- Not covered by DICGC: deposits outside DICGC-insured banks, such as corporate/NBFC FDs. The report should state this scope.

**Investor.gov**
- The phrase "three to six months of living expenses" is confirmed by a search copy of the World Investor Week 2023 bulletin and a
  second Investor.gov page. Direct fetch returned 403, so **[S]**.
- The report correctly refuses the SEBI attribution.

## EA-9 — 10-year G-sec anchor: CONFIRMED (value); status REQUIRES CONFIGURATION is correct

- The Trading Economics page (https://tradingeconomics.com/india/government-bond-yield) says: "The yield on India 10Y Bond Yield
  eased to 7.39% on October 15, 2026".
- **Omission against the binding rules:** the report records no TE terms. Per search of https://tradingeconomics.com/terms.aspx, the
  free use is a "limited, personal, nontransferable, revocable license". The exact scraping clause was **NOT VERIFIED**: the direct
  fetch of the terms URL tried returned 404.
- TE must not be ingested by the app. The anchor should come from an official publisher, FBIL or RBI. The specific endpoint and its
  terms are **NOT VERIFIED** here.

---

## Important omissions in the report

1. **FIFO redemption** makes the "lowest-tax lot first" rebalancing step impossible within one scheme or folio (EA-6).
2. **Income-tax Act, 2025, in force from 1-Apr-2026** (per search, NOT VERIFIED): tax rule tables and section references need
   re-validation. Surcharge and 4 % cess are missing from the friction table.
3. **MSE WP-242 is a US study.** The project has zero Indian volatility-management evidence (EA-3).
4. **Vanguard edition misidentified:** 2015 global data, not 2010 US data (EA-6).
5. **Trading Economics terms not recorded.** The licence is personal and non-transferable, so TE must not be used as an app data
   source (EA-9).
6. **Momentum index launch dates are verifiable:** 25-Aug-2020 and 16-Aug-2022. The claim that excess return is "mostly
   back-calculated" is unquantified (EA-4).
7. **Pre-1995 Indian equity history (Sensex from 1979) is not mentioned.** "Never" claims need series and start-date scoping (EA-1).
8. **Favourable evidence is omitted:**
   - Cederburg's volatility-managed MOM/ROE/BAB utility gains;
   - Kaminski & Lo's empirical futures result that stop-losses can raise expected return at longer frequencies.
   Both should be pre-registered as hypotheses for any future Indian test, so the test is not tuned after the fact.
9. **DICGC nuances:** separate cover for different capacity or right; loan set-off; non-bank FDs not covered (EA-8).
10. **Gold returns come from an "unofficial mirror" of AMFI NAV.** That conflicts with the "officially sourced data with recorded
    rights" bar the report itself sets in §9. The gold row should be NOT VERIFIED or REQUIRES CONFIGURATION until it is sourced
    from AMFI directly.
