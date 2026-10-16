# Verification: research-evidence-mf.md (adversarial review)

- **Reviewed file:** `docs/research/wave1/research-evidence-mf.md`
- **Reviewer stance:** adversarial skeptic. Default is to refute when a citation does not say what the report claims.
- **Accessed:** 2026-10-15 (every URL below was opened or searched on this date).
- **Method:** I re-opened the cited primary sources where I could, extracted PDF text locally (`pdftotext`) instead of trusting
  a summariser, and searched for India evidence the report may have missed.

## Summary verdict

| ID | Report status | Verdict | One-line reason |
|---|---|---|---|
| MF-1 | VERIFIED | **CONFIRMED** (with scope caveat) | Carhart abstract and Morningstar 2016 PDF quotes match word for word. Both use US data only. |
| MF-2 | VERIFIED | **WEAKENED** | Quotes are accurate, but "the *only* robust persistence effect" overstates them. Morningstar finds 1-year persistence among winners too ("and vice versa"), and an Indian study (Majumdar et al. 2024) reports top-decile manager persistence. |
| MF-3 | VERIFIED | **WEAKENED** | The Kinnel quote is now confirmed from the primary PDF. But the report leaves out Deb (2019, India): "high expense ratio funds are marginally better performers and more persistent". The claim "across markets and methods" is not supported for India. |
| MF-4 | VERIFIED | **CONFIRMED** | Kotak page contains the exact sentence. Tax rows match the repo doc (VERIFIED-PRIMARY). |
| MF-5 | VERIFIED | **WEAKENED** | The gap figures are quoted correctly. But "Indian investors lose 2.5–5.8 %/yr *to timing*" overstates what a dollar-weighted vs time-weighted gap measures. Scope: surviving funds, regular plans only, asset-weighted. |
| MF-6 | NOT VERIFIED | **CONFIRMED** (upgrade) | The AAII page loads and carries both quotes (Jaconetti, Zilbering, Kinniry, May 2011). The report's NOT VERIFIED label is too cautious. |
| MF-7 | VERIFIED | **CONFIRMED** (timing half secondary) | ICI sentence is exact. The Mitchell & Pearce "more accurately than chance" wording is in the ResearchGate abstract (search extract). The data is US only, 1982–2002. |
| MF-8 | VERIFIED | **CONFIRMED** | Vanguard NL page carries "61.6% and 73.7%" over rolling one-year periods (Finlay & Zorn, Feb 2023). No India market in the sample. |
| MF-9 | BLOCKED | **WEAKENED** | spglobal.com 403 reproduced. But two "blocked" items were reachable through other hosts: Kinnel PDF (contentstack) and the Vanguard rebalancing text (AAII). |
| MF-10 | NOT VERIFIED | **CONFIRMED** | My search also found no SPIVA India Persistence Scorecard. One adviser blog claims SPIVA India has a persistence section; that claim is NOT VERIFIED. |

---

## Detailed checks

### MF-1: Past-winner selection is not predictive beyond about 1 year

- **Carhart 1997 abstract** (https://econpapers.repec.org/RePEc:bla:jfinan:v:52:y:1997:i:1:p:57-82). Opened. Exact match:
  "common factors in stock returns and investment expenses almost completely explain persistence in equity mutual funds' mean
  and risk-adjusted returns." It also says the 'hot hands' result "is mostly driven by the one-year momentum effect … but
  individual funds do not earn higher returns from following the momentum strategy in stocks."
- **Morningstar 2016, Bryan & Li** (https://www.morningstar.com/content/dam/marketing/shared/research/foundational/735103-Performance-Persistence-Morningstar-2016.pdf).
  The PDF was downloaded and its text extracted. The title is "Performance Persistence Among U.S. Mutual Funds", January 2016,
  by Alex Bryan and James Li. All four quotes in the report appear word for word, for example "Over the long term, there is no
  meaningful relationship between past and future fund performance."
- **Caveats the finding should carry:**
  1. Both sources use US data only. For India, the report relies on Deb (2019), which uses a survivor-only sample.
  2. Morningstar says 1-year persistence is real but explained by momentum ("Funds that have outperformed over the past year
     often continue to do so over the next year"). The abstain verdict is sound, but the reason is "not skill, not
     cost-and-tax-robust". It is not "no relationship at 1 year".
- **Verdict: CONFIRMED.**

### MF-2: Loser persistence is the only robust persistence effect

- The Carhart quote is accurate. Carhart's claim concerns persistence that remains *unexplained after factor adjustment*. It
  does not say loser persistence is the only persistence.
- **Morningstar 2016** says the opposite of "losers only" for raw relative performance. Its conclusion reads: "Funds that have
  outperformed over the past year often continue to do so over the next year, **and vice versa**." Its evidence that losers
  fare worse is mainly about *survivorship* ("Survivorship rates are higher among previous winners"). Losers are merged away.
  That is a different result from return persistence.
- **Deb 2019** abstract (via search extract; ScienceDirect still 403): "a considerable part of this persistence is attributable
  to relatively poor performers". The report quotes this correctly. Note that "a considerable part" is not "only".
- **Counter-evidence the report misses:** Majumdar, Mishra & Chandra (2024), "Fund Characteristics, Managerial Skills and
  Performance Persistence: Evidence from India", *Asia-Pacific Financial Markets* 31(2):335–354
  (https://ideas.repec.org/a/kap/apfinm/v31y2024i2d10.1007_s10690-023-09417-8.html; abstract via search extract, NOT opened
  directly). The extract says it "indicates considerable persistence among the top decile fund managers" (Carhart 4-factor,
  Dec-2006 to Mar-2022). This is a manager-level study with its own biases, but it contradicts "only" for India.
- **Verdict: WEAKENED.** Better wording: "Loser persistence is the most consistently reported effect. Short-term winner
  persistence also exists, but it is mostly momentum and not shown to survive costs." The engine rule (review flag, no
  auto-exit) is unaffected.

### MF-3: Expense ratio is the most consistent predictor; direct beats regular by construction

- **Kinnel 2016, primary now verified.** The Morningstar PDF "Predictive Power of Fees" (May 2016) is reachable at
  https://assets.contentstack.io/v3/assets/blt4eb669caa7dc65b2/blt70866588660aea5a/60416664f9638443346d4e9b/predictive-power-of-fees.pdf
  and its text was extracted. Exact text: "The expense ratio is the most proven predictor of future fund returns." The US equity
  cheapest quintile scored 62 % and the priciest 20 %, matching the report.
- **Caveat 1, success ratio.** The success ratio counts merged or liquidated funds as failures. Expensive funds are merged more
  often, so part of the 62-vs-20 gap is survivorship, not return.
- **Caveat 2, India counter-evidence the report omits.** The Deb (2019) abstract, which the report itself cites, states:
  "Larger, older, and **high expense ratio funds are marginally better performers and more persistent**." (Search extract of the
  ScienceDirect abstract, https://www.sciencedirect.com/science/article/pii/S0970389619301648.) The report says cost is "the
  only fund characteristic with consistent predictive evidence across markets and methods". That is **not supported for
  India**: the one India study it relies on points the other way on gross risk-adjusted performance.
- **Direct vs regular.** "Lower net return by the expense gap, same portfolio" holds as arithmetic. The cost comparator stays a
  deterministic fact, not a forecast, and that part is sound.
- **Side check, SEBI BER.** Cafemutual (17-Feb-2026,
  https://cafemutual.com/news/industry/37012-sebis-new-expense-ratio-framework-here-is-what-changes-after-april-1-2026) describes
  "TER with clear break-up", with the Base Expense Ratio (BER) separated from statutory levies. The cap moved from "2.25%" to
  "2.10%". The report's "TER renamed BER" is loose: BER is a component of TER, not a rename. Old and new caps may also not be
  like-for-like. Treat this as **VERIFIED-SECONDARY**; the SEBI circular is still unopened.
- **Verdict: WEAKENED.** Keep the cost comparator, because net cost is a known, deterministic drag. Drop "most consistent
  predictor across markets" as a claim about India.

### MF-4: Switching is a taxable redemption

- Kotak MF (https://www.kotakmf.com/Information/blogs/switch-in-mutual-fund). Opened. It contains "A mutual fund switch is treated
  as redemption for taxation purposes" and "The holding period starts again for the new scheme after the switch." It also lists
  "Moving from Regular to Direct Plan" as a switch.
- Repo `docs/research/indian-instruments-and-tax.md` has EQ-STCG 20 % (from 2024-07-23), EQ-LTCG 12.5 % with ₹1,25,000/yr
  aggregate exemption, and MF-DEBT-SMF, all marked VERIFIED-PRIMARY. This matches the report.
- A caveat that should be explicit: Kotak is an AMC blog, a secondary source. The legal basis (transfer definition under the 2025
  Act) is not quoted from the statute. The report correctly labels the switch row VERIFIED-SECONDARY, while the finding summary
  says VERIFIED.
- **Verdict: CONFIRMED.**

### MF-5: Rotation and timing not supported; Indian investors lose 2.5–5.8 %/yr to timing

- Morningstar India article (https://www.morningstar.in/posts/70371/why-you-dont-like-your-return-of-a-well-performing-fund.aspx).
  Opened. Figures match: "negative 2.68% per year" (3 y), "negative 2.54% per year" (5 y), "negative 5.79% per year" (10 y),
  data to 30-Jun-2022. The article does attribute the gap to timing: "investors generally have been poor at timing the entry
  and exit from funds".
- Methodology page (https://www.morningstar.in/posts/70368/mind-the-gap-study-methodology.aspx). Opened. The universe is
  "surviving mutual funds schemes with regular share class". Several categories are excluded (liquid, overnight, arbitrage,
  ultra-short, and others). Investor return is a dollar-weighted IRR compared with "time-weighted total returns, weighted by
  asset size".
- **Why the finding is overstated:**
  1. A dollar-weighted vs time-weighted gap measures the effect of the *flow pattern*. It does not isolate discretionary timing.
     Steadily rising SIP inflows during a long rise put more money into later, lower-return windows and create a negative gap
     without any "timing decision". The −5.79 % 10-year number is especially sensitive to this.
  2. Regular share class and surviving funds only. Direct-plan investors, who are this app's target, are not measured.
  3. Asset-weighted across categories. This is not "Indian investors" as individuals.
  4. One snapshot (Jun-2022). No later Indian edition was checked in the report.
- The sector-momentum part (Garg & Varshney 2015; Aravind M) is labelled VERIFIED-SECONDARY in the body. I did not re-open
  these. The "mixed, pre-2015, no costs or taxes" description is fair as an absence-of-evidence statement.
- A small error in §6.1 item 4: it says mid/small-cap "1-year underperformance swung from 12.07 % (CY2025) to 67.19 % (H1-2026
  YTD)". Per the repo table, 67.19 % is the **YTD** figure. The mid-2026 **1-year** figure is 15.00 %. This compares a 1-year
  window with a 6-month window.
- **Verdict: WEAKENED.** Say "Morningstar India measured an asset-weighted investor-return gap of −2.5 % to −5.8 %/yr (surviving
  regular-plan funds, to Jun-2022), which Morningstar attributes mainly to entry/exit timing". Do not say "lose X %/yr to
  timing". The abstain verdict on rotation stands.

### MF-6: Rebalancing bands are robust as risk control, not as a return booster

- AAII (https://www.aaii.com/journal/article/best-practices-for-portfolio-rebalancing). **Opened this session, no 403.** Both
  quotes appear: "annual or semiannual monitoring—with rebalancing at 5% thresholds—is likely to produce a reasonable balance
  between risk control and cost minimization" and "Annual rebalancing is likely to be preferred when taxes or substantial
  time/costs are involved." The page credits Colleen M. Jaconetti, Yan Zilbering and Francis M. Kinniry, May 2011.
- The finding's "NOT VERIFIED" status is therefore too pessimistic. The body text's VERIFIED-SECONDARY is close. With the AAII
  reprint opened, it can be VERIFIED via that reprint.
- Scope caveat: the data is US, a 60/40 stock/bond portfolio, 1926–2009. No India study was found. The report says so.
- **Verdict: CONFIRMED** (status upgrade). The "risk control, not return" framing matches the paper's "risk-adjusted returns are
  not meaningfully different" finding.

### MF-7: Duration mechanics robust, rate timing not

- ICI (https://www.ici.org/viewpoints/view_18_bond_duration). Opened. Exact match: "For a bond fund with a duration of four
  years, a 1 percentage point increase in interest rates alone would be expected to lower the overall net asset value of the
  fund by 4 percent." Authors Antoniewicz and Duvall, 17-Dec-2018.
- Mitchell & Pearce (2007), *J. Macroeconomics* 29(4):840–854. The ResearchGate abstract (search extract) says "none predicted
  directions of changes more accurately than chance". The IDEAS abstract page I opened
  (https://ideas.repec.org/a/eee/jmacro/v29y2007i4p840-854.html) was summarised as "most cannot surpass a random walk". The
  direct "chance" wording was not confirmed on a page I opened. US WSJ panel, 1982–2002.
- **Verdict: CONFIRMED** for the mechanics. The timing half should stay VERIFIED-SECONDARY, not VERIFIED, and is not India
  evidence.

### MF-8: SIP vs lump sum

- Vanguard NL (https://www.nl.vanguard/professional/vanguard-365/cost-averaging). Opened. "a lump-sum approach won between 61.6%
  and 73.7% of the time", rolling one-year periods, markets from MSCI World 1976–2022 to MSCI EM 1988–2022. The study is "Cost
  averaging: Invest now or temporarily hold your cash?" by Finlay & Zorn, Feb 2023.
- Limits: there is no Indian index. The comparison is with cash held during the averaging period, which applies only when a lump
  sum actually exists. The report states both limits. I did not confirm the report's extra remark that the lump-sum advantage
  grows with longer averaging periods; treat it as NOT VERIFIED.
- **Verdict: CONFIRMED.**

### MF-9: Blocked sources

- spglobal.com SPIVA India PDF: 403 reproduced on 2026-10-15
  (https://www.spglobal.com/spdji/en/documents/spiva/spiva-india-scorecard-mid-year-2025.pdf).
- However:
  1. The Kinnel primary was reachable on Morningstar's asset CDN (above).
  2. The Vanguard rebalancing text was reachable on AAII.
  3. The Morningstar 2016 persistence PDF on morningstar.com loaded, so "morningstar.com returned 403" applies only to article
     pages.
- **Verdict: WEAKENED.** Some items labelled BLOCKED or secondary could have been primary-verified.

### MF-10: No India SPIVA Persistence Scorecard

- My search ("SPIVA India persistence scorecard", 2026-10-15) returned US, Europe and Latin America persistence reports and the
  SPIVA India scorecard. No India persistence report appeared.
- An adviser blog (https://www.akshaynayakria.com/post/spiva-india-reports-decoded, via search extract) asserts that SPIVA India
  reports check consistency of outperformers. **NOT VERIFIED.** The SPIVA India PDF returned 403, so I could not check it.
- **Verdict: CONFIRMED** as stated: existence NOT VERIFIED, and US figures must not be shown as Indian.

---

## Important omissions

1. **Deb (2019) on expense ratios.** The report's own India source finds high-expense funds "marginally better performers and
   more persistent". It should be reported and reconciled with the cost-is-king claim (gross alpha vs net investor return;
   survivor-only sample).
2. **Indian winner-persistence evidence.** Majumdar, Mishra & Chandra (2024, *APFM*) report top-decile manager persistence in
   India. Veeravel (2023, *CJFA*, https://apcz.umk.pl/CJFA/article/view/48754, 47 funds 2000–2019) also reports short-term
   persistence. Neither is cost- or tax-aware, and neither justifies a signal. But "losers only" should not be presented as
   settled for India.
3. **Mind the Gap is not a pure timing measure.** The flow-pattern artefact in dollar-weighted vs time-weighted gaps is
   unmentioned, and the study covers regular plans only.
4. **SPIVA India benchmark break (2024).** S&P switched from S&P BSE indices to the S&P India index family after the BSE
   partnership ended. Commentators note this breaks 10-year comparability. This affects the "74–82 % underperform" figures the
   report carries over. NOT VERIFIED from the primary source; flagged via a search extract
   (https://www.basunivesh.com/active-vs-passive-why-you-must-not-trust-spiva-india-report/).
5. **Kinnel success-ratio construction.** Merged funds count as failures, which inflates the cost effect through survivorship.
6. **SPIVA window mismatch** in §6.1(4): YTD shown as 1-year.
7. **SEBI BER wording.** It is a break-up of TER, not a rename. Cap comparability is unconfirmed.
8. **Direct-plan relevance of all behavioural/gap evidence.** Most Indian studies (Mind the Gap, Deb) measure regular plans or
   pre-2013 periods, before direct plans existed. The user invests in direct plans.

## Net effect on the engine rules

None of the refutations or weakenings create a signal. They make the report's abstain conclusions *stronger* (less evidence
for anything), and they weaken two of its "robust" headline claims: loser-only persistence, and expense ratio as the top
predictor for India. The deterministic outputs in §12 stay valid because they rest on arithmetic (cost gap, tax, exit load,
drift, duration), not on those empirical claims. The narrative should stop saying "cost is the best predictor of returns in
India". It should say "cost is a known, certain drag on net return".
