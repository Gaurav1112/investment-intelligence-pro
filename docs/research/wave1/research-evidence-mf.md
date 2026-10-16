# Research: evidence for mutual fund signals (India)

- **Track:** wave1 / evidence-mf
- **Accessed:** 2026-10-15 (every external citation below was accessed on this date)
- **Scope:** which mutual fund "rules" have evidence strong enough to become an engine **signal**, and which are myths. Covers
  performance persistence, category/asset-class rotation, expense ratios, regular vs direct, rolling-return consistency, when to
  switch or exit, SIP vs lump sum, rebalancing bands, debt-fund duration vs the rate cycle, and the Indian tax and exit-load cost of
  switching.
- **Binding rule applied:** a signal may exist only if a documented, out-of-sample, cost- and tax-aware backtest supports it.
  Otherwise the engine abstains. "No suitable candidate" is a valid answer.

## Status labels used

| Label | Meaning in this report |
|---|---|
| **VERIFIED** | Primary document opened this session and quoted, or already marked VERIFIED-PRIMARY in a repo doc (cited). |
| **VERIFIED-SECONDARY** | Quote comes from a search-engine extract of the primary page, or from a reputable secondary source. The primary was blocked (HTTP 403) or not opened. |
| **NOT VERIFIED** | Claim seen but not confirmed. Must not drive any number in the app. |
| **REQUIRES CONFIGURATION** | Needs user- or scheme-specific input (tax slab, exit-load schedule, purchase lots). |
| **BLOCKED** | Source could not be accessed. |

Access notes. spglobal.com (SPIVA PDFs and pages), sciencedirect.com, morningstar.com articles, incometaxindia.gov.in, pib.gov.in
and the indexacapital.com Vanguard mirror all returned **HTTP 403** to the fetcher this session (**BLOCKED** for direct quoting). For
SPIVA India this report relies on `docs/research/return-target-feasibility.md` §2.6–2.8, where those figures were already verified
from the primary PDFs. The Morningstar 2016 persistence PDF, the Carhart abstract (EconPapers), the Vanguard NL cost-averaging page,
the ICI duration article and the Morningstar India "Mind the Gap" article were opened and quoted directly.

---

## 1. Bottom line (read this first)

| # | Rule people use | Verdict | Can it be an engine signal? |
|---|---|---|---|
| R1 | "Buy last year's / last 3 years' top performer" | **Myth over long horizons.** Short-term persistence exists but is explained by stock momentum, and it fades. | **No.** Abstain. |
| R2 | "Bad funds keep being bad" | **Robust (the one persistence result that survives).** | **Yes, as a *review flag* only**, not an automatic sell. Needs an India out-of-sample backtest before it may say "exit". |
| R3 | "Lower expense ratio → better future net return" | **Robust.** The most consistently supported predictor. | **Yes.** Cost is a deterministic input, no forecasting needed. |
| R4 | "Direct plan beats regular plan of the same scheme" | **Robust by construction** (same portfolio, lower cost). | **Yes.** Deterministic switch-break-even calculation including tax and exit load. |
| R5 | "Pick funds with consistent rolling returns" | **Weak / not established.** No study found that tests rolling-return consistency directly. Style consistency has some support. | **No** as a buy signal. Show as descriptive context only. |
| R6 | "Rotate into the hot category / sector" | **Not established for funds after costs and tax.** Stock-level momentum is documented in India; sector-level results are mixed and pre-2015. Investor timing in India destroys large amounts of return. | **No.** Abstain until a cost- and tax-aware out-of-sample backtest exists. |
| R7 | "SIP beats lump sum" | **Myth as a return claim.** Lump sum wins about two-thirds of the time on terminal wealth. SIP is a risk/behaviour tool. | **No return signal.** Can present both with the known base rate. |
| R8 | "Rebalance on a band (e.g. 5 %)" | **Robust as risk control**, not as a return booster. Exact band/frequency is not critical. | **Yes.** Deterministic drift check against the user's own target allocation; tax- and exit-load-aware. |
| R9 | "Go long duration before rate cuts, short before hikes" | **Mechanics robust; the timing call is not.** Forecasters generally fail to beat a random walk on long yields. | **No timing signal.** Duration-vs-horizon *matching* is allowed (deterministic). |
| R10 | "Exit when the fund manager changes / AUM gets big / star rating drops" | **Not established** in sources found this session. | **No.** At most an informational event. |

The net effect for the user's aim ("signals to grow my money"): for mutual funds, the evidence-backed actions are **cost control,
plan choice, allocation discipline, horizon matching and tax-aware execution**. They are not return predictions. The evidence
does **not** support a "buy this fund now, it will outperform" signal. The engine should say so plainly.

---

## 2. Performance persistence — do past winners keep winning?

### 2.1 Evidence

1. **Carhart (1997), *Journal of Finance* 52(1):57–82** — **VERIFIED** (abstract, EconPapers).
   URL: https://econpapers.repec.org/RePEc:bla:jfinan:v:52:y:1997:i:1:p:57-82
   > "common factors in stock returns and investment expenses almost completely explain persistence in equity mutual funds' mean
   > and risk-adjusted returns."
   > "The only significant persistence not explained is concentrated in strong underperformance by the worst-return mutual funds."
   > "The results do not support the existence of skilled or informed mutual fund portfolio managers."

2. **Morningstar, "Performance Persistence Among U.S. Mutual Funds" (Alex Bryan, James Li; January 2016)** — **VERIFIED** (PDF opened).
   URL: https://www.morningstar.com/content/dam/marketing/shared/research/foundational/735103-Performance-Persistence-Morningstar-2016.pdf
   > "There is some evidence that relative fund performance persists in the short term. In the equity categories, this appears to be
   > attributable to differences in exposure to momentum stocks, rather than differences in manager skill."
   > "Over the long term, there is no meaningful relationship between past and future fund performance."
   > "In most cases, the odds of picking a future long-term winner from the best-performing quintile in each category aren't
   > materially different than selecting from the bottom quintile."
   > "Survivorship rates are higher among previous winners than they are among previous losers."

3. **Fama & French (2010), "Luck versus Skill in the Cross-Section of Mutual Fund Returns", *Journal of Finance* 65(5):1915–1947** —
   **VERIFIED-SECONDARY** (abstract via search extract; Wiley/SSRN pages not opened).
   URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1356021
   Extract: "few funds produce benchmark-adjusted expected returns sufficient to cover their costs." Counterpoint: Harvey & Liu (2022,
   *JF*) argue the bootstrap under-detects skill (https://onlinelibrary.wiley.com/doi/10.1111/jofi.13123) — **VERIFIED-SECONDARY**.

4. **India — Deb (2019), "Persistence in performance of actively managed equity mutual funds: New Indian evidence", *IIMB
   Management Review* 31(2):145–156, DOI 10.1016/j.iimb.2019.03.014** — **VERIFIED-SECONDARY** (ScienceDirect returned 403; abstract
   via search extract). URL: https://www.sciencedirect.com/science/article/pii/S0970389619301648
   - Sample: 263 active equity funds "which existed continuously between January 2000 and December 2014"; Carhart 4-factor alpha.
   - Extract: "evidence of short-term persistence over a 12-month horizon which reduces over longer horizons" and "a considerable part
     of this persistence is attributable to relatively poor performers within the group."
   - **Caveat (this report's reading):** requiring funds to exist continuously for 15 years is a survivorship filter. Results
     apply to survivors only.

5. **India — Deb, Banerjee & Chakrabarti (2008), *IIMB Management Review* 20(2)** — **VERIFIED-SECONDARY**.
   URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2441547
   Extract: "no evidence of persistence for the ELSS funds, and some evidence of persistence for the Growth funds".

6. **Emerging markets — Otero González, Durán Santomil, Marouf & Vieito (2025)** — **VERIFIED-SECONDARY**.
   URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4981707
   Extract: "performance persistence is not consistently observed across methodologies", though top-rated funds beat the lowest-rated
   over three years. One cross-country study; not India-specific; not out-of-sample for India.

7. **S&P SPIVA India (active vs benchmark, survivorship)** — **VERIFIED** in `docs/research/return-target-feasibility.md` §2.6–2.8
   (primary PDFs). Key numbers carried over, data to 30-Jun-2026: over 10 years **74.03 %** of large-cap, **80.49 %** of ELSS and
   **81.67 %** of mid/small-cap active funds underperformed their S&P benchmark; **25.7 %** of funds across all categories did not
   survive 10 years. This session's direct fetch was **BLOCKED** (403).

8. **No SPIVA *Persistence* Scorecard for India was found** (searches 2026-10-15 returned only U.S., Europe, Australia, Latin
   America, Canada editions). **NOT VERIFIED** that one exists. US figures must not be presented as Indian figures.

### 2.2 Verdict

- **"Winners keep winning" — myth over horizons longer than about a year.** Where short-term persistence exists, it is explained
  by momentum exposure and cost differences, not skill (Carhart; Morningstar 2016). India-specific studies agree, with
  survivorship caveats.
- **"Losers keep losing" — the robust part.** Found by Carhart, Morningstar (survivorship of losers is lower) and Deb (2019).
- **For the engine:** a "top performer → buy" signal is **not allowed**. A "persistent bottom-quartile vs its own benchmark, net of
  cost" **review flag** is allowed descriptively. It may be upgraded to an exit signal only after an India walk-forward backtest
  (see §11) shows that exiting losers into the category index improved after-tax outcomes out of sample.

---

## 3. Expense ratio effect

### 3.1 Evidence

1. **Carhart (1997)** — expenses are one of the two things that "almost completely explain" persistence (quote above). **VERIFIED**.
2. **Morningstar 2016 (Bryan & Li)** — "Differences in expense ratios" are named alongside momentum as drivers (PDF text). **VERIFIED**.
3. **Morningstar, Russel Kinnel, "Predictive Power of Fees" (May 2016)** — **VERIFIED-SECONDARY** (morningstar.com returned 403;
   figures via search extracts of the article and of fa-mag/ThinkAdvisor coverage).
   URLs: https://www.morningstar.com/funds/fund-fees-predict-future-success-or-failure ;
   https://www.thinkadvisor.com/2016/05/09/low-mutual-fund-fees-predict-higher-returns-morningstar/
   Extract: "the expense ratio is the most proven predictor of future fund returns." US equity cheapest quintile success ratio 62 %
   vs 20 % for the most expensive quintile over five years to Dec-2015; success ratio counts merged/closed funds as failures.
4. **SEBI cost caps (India)** — from 1-Apr-2026 the Total Expense Ratio was renamed **Base Expense Ratio (BER)** and caps were cut;
   e.g. open-ended equity schemes up to ₹500 crore: 2.25 % → 2.10 %. **VERIFIED-SECONDARY** (Cafemutual coverage; SEBI circular not
   opened this session). URL: https://cafemutual.com/news/industry/37012-sebis-new-expense-ratio-framework-here-is-what-changes-after-april-1-2026
   Repo cross-reference: `docs/research/indian-instruments-and-tax.md` already treats BER as a scheme input.

### 3.2 Verdict

**Robust.** Cost is the only fund characteristic with consistent predictive evidence across markets and methods, and it is known
in advance (no forecasting). It belongs in the engine as a deterministic comparator: same category, same benchmark, cost
difference in basis points. It must not be converted into a return forecast.

---

## 4. Regular vs direct plan

### 4.1 Evidence

- Direct plans exist since 1-Jan-2013. Scheme documents state that a Direct Plan "shall have a lower expense ratio excluding
  distribution expenses, commission" and SEBI's Master Circular (27-Jun-2024) para 10.1.12 says direct-plan fees under each head
  "shall not exceed" regular-plan fees. **VERIFIED-SECONDARY** (via SID extracts on portal.amfiindia.com; circular not opened).
- Same portfolio, so the gross return is identical. The net return gap equals the expense gap, by construction. **VERIFIED** as
  arithmetic; no empirical study is needed for the sign.
- Empirical magnitude: an Economic Times (2023) analysis cited in a ResearchGate paper reports direct plans returning roughly 1–2 %
  p.a. more than regular plans over 10 years in equity categories. **NOT VERIFIED** (secondary of a secondary).
  URL: https://www.researchgate.net/publication/392652036_Risk-Adjusted_Performance_Comparison_of_Direct_and_Regular_Plan_Equity_Mutual_Funds_in_India
- **Switching regular → direct is a taxable redemption + fresh purchase.** See §10. **Exit load on a plan switch within the same
  scheme varies by AMC:** some SIDs say "no exit load ... between the Plans (i.e. Regular and Direct Plans)"; Nippon India says a
  switch "from Regular Plan to Direct Plan of a Scheme shall be subject to applicable exit load" where the investment carries an ARN
  code. **VERIFIED-SECONDARY** (SID extracts on portal.amfiindia.com). → **REQUIRES CONFIGURATION** per scheme.

### 4.2 Verdict and engine rule

**Robust.** The engine can emit a deterministic **"direct plan available — cost saving vs one-time switching cost"** signal:

```
annual_saving        = holding_value × (BER_regular − BER_direct)
one_time_switch_cost = exit_load(lots, schedule) + capital_gains_tax(lots, regime, exemption_remaining) + stamp_duty(0.005 % of switch-in)
breakeven_years      ≈ one_time_switch_cost / annual_saving   (first-order; ignores compounding of the saved tax)
```

Fictional example (not the user's numbers): holding ₹4,00,000, BER gap 0.80 % → saving ≈ ₹3,200/yr. If all lots are >12 months
old with ₹50,000 gain fully inside the unused ₹1.25 lakh exemption, tax = 0, exit load = 0, stamp duty ≈ ₹20 → break-even within
about a week. If the same gain were short-term equity, tax at 20 % = ₹10,000 → break-even ≈ 3.1 years, so **wait until lots turn
long-term** is the better action. Every input is either a scheme document value or a user lot; the engine abstains if any is
missing.

Fresh money should default to direct plans. This is a cost fact, not a forecast.

---

## 5. Rolling-return consistency

- **No study was found that tests "consistency of rolling returns" as a predictor of future fund returns.** **NOT VERIFIED** that
  such evidence exists.
- Closest evidence: persistence studies (§2) show long-horizon past returns are not predictive. Morningstar 2016: no meaningful
  long-term relationship. **VERIFIED**.
- Style/strategy consistency has some support in non-India working papers (e.g. Athena Invest 2022,
  https://athenainvest.com/wp-content/uploads/Strategy_Consistency_Mutual_Fund_Performance_2022_08.pdf). **NOT VERIFIED**
  (working paper, firm-hosted, not opened, not India).
- SEBI's 2017 categorisation mandates style boundaries per category (one scheme per category per AMC), which reduces style drift
  as a free variable in India. **VERIFIED-SECONDARY** (circular SEBI/HO/IMD/DF3/CIR/P/2017/114, 6-Oct-2017;
  https://sebi.gov.in/sebi_data/attachdocs/oct-2017/1509103633344.pdf not opened; via taxguru/cleartax extracts).

**Verdict:** rolling returns are a good *descriptive* tool for showing range of outcomes (already used in
`docs/forecasting/validation-methodology.md` B1). They are **not** a validated selection signal. The engine may show rolling-return
distributions with a "past range, not a forecast" label and must not rank funds on them.

---

## 6. Category / asset-class rotation and investor timing

### 6.1 Evidence

1. **Investor timing in India costs a lot.** Morningstar India "Mind the Gap" (Melvyn Santarita, Kaustubh Belapurkar; data as of
   30-Jun-2022) — **VERIFIED** (article opened).
   URL: https://www.morningstar.in/posts/70371/why-you-dont-like-your-return-of-a-well-performing-fund.aspx
   Investor-return gap vs fund total return: **"negative 2.68% per year"** (3 y), **"negative 2.54% per year"** (5 y),
   **"negative 5.79% per year"** (10 y). Scope note from the methodology page (via search extract): surviving schemes, regular share
   class. **VERIFIED-SECONDARY** for the scope note.
2. **Flows chase past returns.** Indian retail flows show "a non-linear flow to performance relationship with higher performance
   attracting more normalised flows" ("Do retail mutual fund investments represent 'dumb money'?", *IIMB Management Review*,
   https://www.sciencedirect.com/science/article/pii/S0970389621000197). **VERIFIED-SECONDARY** (403 on fetch).
3. **Stock/sector momentum in India.** Garg & Varshney (2015), *Global Business Review*: momentum "robust in Indian stock market
   over the period of 2000–2013" across industries (https://journals.sagepub.com/doi/abs/10.1177/0972150915569940). Aravind M
   (SSRN, NSE sectoral indices Apr-2009–Mar-2015): **mixed**, short-term **contrarian** effect in Metals, Auto, Banking, Energy
   (https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2797119). Both **VERIFIED-SECONDARY**. Neither applies fund-level costs,
   exit loads or Indian capital gains tax. Neither is recent (samples end 2013/2015).
4. **Regime dependence visible in SPIVA India.** Mid/small-cap active funds' 1-year underperformance swung from 12.07 % (CY2025) to
   67.19 % (H1-2026 YTD). **VERIFIED** (repo doc §2.6).

### 6.2 Verdict

**Not established for fund-level rotation after costs and tax.** Stock-level momentum is a documented anomaly (and is better
handled by the equity research track, not via switching active funds). Every rotation between mutual fund schemes is a taxable
redemption (§10) and may carry an exit load. The documented Indian behaviour gap shows how expensive timing has been in practice.
**The engine abstains** on rotation signals. A future rotation signal needs §11's backtest including tax per lot.

---

## 7. When to switch or exit a fund

| Trigger | Evidence | Engine treatment |
|---|---|---|
| Fund persistently trails its **own benchmark TRI** net of cost, multi-year | Loser persistence (Carhart; Morningstar 2016; Deb 2019) | **Review flag** (descriptive). Exit recommendation only after §11 backtest. |
| Cheaper equivalent exists (direct plan / index fund in same category) | Cost evidence (§3, §4) | **Signal allowed**, with switch-cost break-even (§4.2). |
| Allocation drifted beyond the user's band | Vanguard rebalancing research (§9) | **Signal allowed** (rebalance), tax-aware. |
| Goal horizon has shortened; fund's risk no longer matches | Duration mechanics (§8), horizon suitability in `indian-instruments-and-tax.md` | **Signal allowed** as suitability mismatch, not return forecast. |
| Scheme changes fundamental attributes / category / merges | Regulatory event; SEBI requires an exit option without load for fundamental attribute changes — **NOT VERIFIED** this session | **Event notice**; legal detail needs verification before use. |
| Credit event in a debt fund (downgrade/default, side-pocket, wind-up) | Franklin Templeton India wound up six credit-oriented debt schemes effective 23-Apr-2020; investors could not redeem; distributions later reached about 109 % of 23-Apr-2020 AUM (as of 30-Jun-2025) per AMC figures | **Risk notice.** Figures **VERIFIED-SECONDARY** (AMC page did not render; via search extracts of franklintempletonindia.com and Business Standard). |
| Fund manager change, AUM growth, star-rating downgrade | Star ratings: "limited predictive power" for future abnormal performance per literature summaries (Blake & Morey 2000; Del Guercio & Tkac 2008). Manager change: no evidence found. | **No signal.** Informational at most. **NOT VERIFIED** beyond secondary summaries. |
| Short-term loss / recent underperformance vs peers | Myth as an exit trigger (§2) | **No signal.** |

Exit timing within the year is dominated by **tax and exit load**: crossing 12 months for equity lots changes STCG 20 % to LTCG
12.5 % with a ₹1.25 lakh annual exemption; exit loads typically fall to nil after a scheme-specific window. These are deterministic
and should drive the **"when"** of any switch the user has already decided on.

---

## 8. Debt funds: duration vs the rate cycle

### 8.1 Mechanics (robust)

- ICI (Shelly Antoniewicz, James Duvall; 17-Dec-2018), **VERIFIED** (article opened):
  > "For a bond fund with a duration of four years, a 1 percentage point increase in interest rates alone would be expected to lower
  > the overall net asset value of the fund by 4 percent."
  URL: https://www.ici.org/viewpoints/view_18_bond_duration
- SEBI category bands (Macaulay duration): ultra-short 3–6 months, low 6–12 months, short 1–3 years, medium 3–4 years, medium-to-long
  4–7 years, long >7 years, gilt-constant-maturity 10 years. **VERIFIED-SECONDARY** (circular 6-Oct-2017 and Dec-2017 amendment via
  taxguru/cleartax extracts; https://taxguru.in/sebi/categorization-rationalization-mutual-fund-scheme.html).
- Approximate price change ≈ −modified duration × Δyield (+ convexity). Deterministic; usable in a scenario table.

### 8.2 Timing (not robust)

- Professional forecasters of long-term rates generally fail to beat a random walk: Mitchell & Pearce (2007, WSJ panel) found none
  "predicted directions of changes more accurately than chance". **VERIFIED-SECONDARY**
  (https://www.researchgate.net/publication/222655842). The CBO working paper reports private forecasters "consistently missed the
  decline in long-term nominal interest rates". **VERIFIED-SECONDARY**
  (https://cbo.gov/system/files/115th-congress-2017-2018/workingpaper/53153-interestrateswp.pdf). Not India-specific; no India
  study verified this session.
- SPIVA India: 10-year underperformance of composite bond funds 92.65 % and government bond funds 75.00 % (to 30-Jun-2026);
  YE-2025 noted 55 % of government bond funds merged/liquidated over 10 years (latter **VERIFIED-SECONDARY**). Active duration
  management has not reliably added value. **VERIFIED** (repo doc §2.6).

### 8.3 Verdict and engine rule

- **Allowed:** match fund duration to the goal horizon (e.g. a 1-year goal should not sit in a long-duration or gilt fund), and show
  a deterministic ±100 bp / ±200 bp NAV scenario from published modified duration and YTM. This is the B4 yield-carry approach in
  `docs/forecasting/validation-methodology.md`.
- **Not allowed:** "rates will fall, go long duration" signals. Abstain.
- **Tax note:** debt "specified mutual funds" bought on/after 1-Apr-2023 are taxed at slab regardless of holding period, so holding
  >3 years no longer earns indexation/LTCG. **VERIFIED** (repo `indian-instruments-and-tax.md`, MF-DEBT-SMF row).

---

## 9. SIP vs lump sum, and rebalancing bands

### 9.1 SIP vs lump sum

- **Vanguard (NL professional site; 2023 update)** — **VERIFIED** (page opened). URL: https://www.nl.vanguard/professional/vanguard-365/cost-averaging
  > "a lump-sum approach won between 61.6% and 73.7% of the time" (rolling one-year periods, markets incl. MSCI World 1976–2022,
  > MSCI Emerging Markets 1988–2022). The page also notes the lump-sum advantage grows as the averaging period lengthens.
- **India, Nifty 50:** a Zenodo preprint (2012–2022) reports lump sum ahead on terminal value in "97.8% of five-year and 100% of
  ten-year rolling windows" (https://zenodo.org/records/21308949) — **NOT VERIFIED** (unreviewed preprint, not opened). A
  practitioner backtest (backtestindia.com) reports roughly 50/50 when SIP XIRR is compared with lump-sum CAGR — **NOT VERIFIED**,
  and the two metrics are not comparable.
- **Verdict:** "SIP gives higher returns" is a **myth** when the money is already available. SIP's value is behavioural (avoids
  regret, matches monthly income) and lowers timing-dispersion. Most salaried investors invest from monthly income anyway, so SIP is
  the natural mechanism, not a signal. **Engine:** no SIP-vs-lump-sum *signal*; may show the documented base rate (Vanguard, global)
  and say no India-verified rate exists.

### 9.2 Rebalancing bands

- **Vanguard, "Best practices for portfolio rebalancing" (2010, updated; Zilbering, Jaconetti, Kinniry)** — **VERIFIED-SECONDARY**
  (mirrors returned 403; quote via search extract).
  URL: https://www.aaii.com/journal/article/best-practices-for-portfolio-rebalancing
  > "annual or semiannual monitoring, with rebalancing at 5% thresholds, is likely to produce a reasonable balance between risk
  > control and cost minimization for most investors."
  > "Annual rebalancing is likely to be preferred when taxes or substantial time/costs are involved."
  Key finding: no single optimal frequency or threshold; risk-adjusted returns did not differ meaningfully across strategies.
- **India:** no peer-reviewed India equity/debt rebalancing study was verified this session. **NOT VERIFIED**.
- **Verdict:** **robust as risk control.** **Engine rule (deterministic):** check drift vs the user's target allocation on a fixed
  review date; flag when an asset class is ≥5 percentage points off target (default, user-configurable → **REQUIRES
  CONFIGURATION**). Prefer, in order: (1) direct new SIP/lump money to the underweight class, (2) switch lots that are long-term and
  within the ₹1.25 lakh exemption, (3) lots past their exit-load window. Show the tax and load cost before the action.

---

## 10. Indian tax and exit loads on switching

| Item | Rule | Status / source |
|---|---|---|
| Switch = redemption + purchase | A switch between schemes, and between regular and direct plans, is treated as a transfer of the old units. Capital gains arise on the switch-out. | **VERIFIED-SECONDARY** — Kotak MF ("a mutual fund switch is treated as redemption for taxation purposes", https://www.kotakmf.com/Information/blogs/switch-in-mutual-fund); Business Standard citing AMFI investor material ("capital gains can arise on redemption/switch/sale"). Some blogs claim intra-AMC switches are tax-free: **contradicted**, do not use. |
| Equity-oriented fund STCG (≤12 months) | 20 % for transfers on/after 23-Jul-2024 (was 15 %) | **VERIFIED** (repo `indian-instruments-and-tax.md`, EQ rows, VERIFIED-PRIMARY; also CBDT FAQs https://www.pib.gov.in/PressReleasePage.aspx?PRID=2036604 via extract: "increased from 15 to 20%") |
| Equity-oriented fund LTCG (>12 months) | 12.5 % above ₹1,25,000 per year, a **single annual pool** across all listed equity / equity MF gains | **VERIFIED** (repo doc EQ-LTCG row; Budget memo https://www.indiabudget.gov.in/budget2024-25/doc/memo.pdf) |
| Debt "specified MF" (>65 % debt), units bought on/after 1-Apr-2023 | Gains deemed short-term, taxed at slab, regardless of holding | **VERIFIED** (repo doc MF-DEBT-SMF row) → slab is **REQUIRES CONFIGURATION** |
| Section numbering | Income-tax Act 2025: s.111A/112A/50AA map to s.196/198/76 | **VERIFIED** (repo doc) |
| SIP lots / FIFO | Each SIP instalment is a separate lot with its own holding clock; redemptions/switch-outs are FIFO | **VERIFIED-SECONDARY** (SID extract: "Redemptions / Switch outs of units will be done on First In First Out (FIFO) basis", Quantum SID https://portal.amfiindia.com/spages/13880.pdf) |
| Exit load | Scheme-specific; switch-out attracts exit load "like any Redemption"; cap 3 % (redemption price ≥ 97 % of NAV) | **VERIFIED** (cap: repo doc, 2026 Regulations) / **VERIFIED-SECONDARY** (switch wording, JPMorgan SID https://portal.amfiindia.com/spages/4370.pdf). Values per SID → **REQUIRES CONFIGURATION** |
| ELSS | 3-year lock-in per instalment; no switch-out before | **VERIFIED-SECONDARY** (multiple AMC explainers) |
| Stamp duty | 0.005 % on switch-in / purchase | **VERIFIED-SECONDARY** (repo doc STAMP-MF-01) |
| Loss set-off on switch | STCL against STCG/LTCG; LTCL only against LTCG; carry-forward | **NOT VERIFIED** under the 2025 Act (repo doc says not modelled) |
| Scheme mergers by the AMC | Not a transfer (s.47 exemption) | **NOT VERIFIED** this session — do not rely on it |

Practical consequence: **tax and exit load are usually the largest, most certain cost of any "signal" to switch funds.** Any
switch recommendation must be computed per lot, show the after-tax value, and compare against "do nothing" and "redirect future
SIPs only" (which costs zero tax).

---

## 11. What a valid MF signal backtest must look like (gate for promotion)

A rule from §1 marked "No" may only be promoted if all of these hold. Re-uses `docs/forecasting/validation-methodology.md`.

1. **Universe without survivorship bias:** include merged/closed schemes (SPIVA shows ~25.7 % non-survival over 10 years). If
   AMFI history for dead schemes is unavailable, the backtest is **BLOCKED** and the engine abstains.
2. **Point-in-time inputs:** rank on information available at the decision date (NAV, BER, category), no restated categories.
3. **Benchmark = category TRI or a low-cost index fund**, plus "do nothing".
4. **Costs:** exit load per lot, stamp duty, BER differences, and **Indian capital gains tax per lot** (20 % STCG / 12.5 % LTCG
   above ₹1.25 lakh shared pool / slab for debt), with the regime in force on each historical date.
5. **Walk-forward, out-of-sample**, with purge/embargo; report hit-rate, after-tax excess return and its interval, and turnover.
6. **Pre-registered rule** (no parameter search on the test window); multiple-testing disclosure.
7. **Pass bar:** after-tax excess vs index alternative positive with interval excluding zero, across at least two non-overlapping
   regimes. Otherwise: abstain.

No rule in R1, R5, R6, R7 (as return claim), R9 (timing) or R10 has such a backtest in any source found. They stay **abstain**.

---

## 12. Recommended engine outputs for mutual funds (evidence-backed only)

| Output | Type | Inputs | Evidence |
|---|---|---|---|
| Cost comparator (same category, BER bp gap) | Deterministic | Scheme BER (AMFI/SID) | §3 robust |
| Regular→direct switch break-even | Deterministic | Lots, BER both plans, exit load, tax regime, exemption used | §4 robust |
| Index-alternative comparator ("same exposure at lower cost") | Deterministic + SPIVA base rates | BER, category benchmark | §2, §3 |
| Persistent-underperformer review flag | Descriptive | Fund vs own benchmark TRI, 3/5 y, net | §2 (loser persistence) |
| Rebalance-drift alert | Deterministic | User target allocation, band, holdings | §9.2 |
| Horizon/duration mismatch | Deterministic | Goal date, fund Macaulay/modified duration | §8 |
| Tax-timing helper ("lot turns long-term on date X; ₹ exemption left") | Deterministic | Lots, FY gains | §10 |
| Buy/sell "this fund will outperform", category rotation, rate-cycle duration calls, SIP-vs-lump "better returns" | **Abstain** | — | §2, §6, §8, §9 |

These outputs move money toward the user's aim through cost, tax and discipline, which have evidence. They do not promise the
20–25 % aspiration; see `docs/research/return-target-feasibility.md` for why no fund category has a verified base rate at that level.

---

## 13. Open items / NOT VERIFIED list

1. SPIVA India primary PDFs could not be re-fetched this session (403). Figures rely on the repo doc.
2. No India SPIVA Persistence Scorecard found; existence **NOT VERIFIED**.
3. Direct-vs-regular empirical gap (1–2 % p.a.) — **NOT VERIFIED**; only the sign is certain.
4. India SIP-vs-lump-sum base rate — **NOT VERIFIED** (only unreviewed preprint / practitioner backtests).
5. India rebalancing study — none verified.
6. SEBI rule on exit-load-free window on fundamental-attribute change — **NOT VERIFIED**.
7. Section 47 scheme-merger exemption and loss set-off under the 2025 Act — **NOT VERIFIED**.
8. Fund-manager-change and AUM-size effects in India — no evidence located.
9. Survivorship-free AMFI history of merged/closed schemes — availability **NOT VERIFIED**; required for §11.

## Sources (all accessed 2026-10-15)

- Carhart 1997 abstract — https://econpapers.repec.org/RePEc:bla:jfinan:v:52:y:1997:i:1:p:57-82
- Morningstar 2016 persistence (Bryan & Li) — https://www.morningstar.com/content/dam/marketing/shared/research/foundational/735103-Performance-Persistence-Morningstar-2016.pdf
- Fama & French 2010 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1356021 ; Harvey & Liu 2022 — https://onlinelibrary.wiley.com/doi/10.1111/jofi.13123
- Deb 2019 — https://www.sciencedirect.com/science/article/pii/S0970389619301648
- Deb, Banerjee, Chakrabarti 2008 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2441547
- Otero González et al. 2025 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4981707
- Kinnel, Morningstar fees — https://www.morningstar.com/funds/fund-fees-predict-future-success-or-failure ; https://www.thinkadvisor.com/2016/05/09/low-mutual-fund-fees-predict-higher-returns-morningstar/
- SEBI BER 2026 coverage — https://cafemutual.com/news/industry/37012-sebis-new-expense-ratio-framework-here-is-what-changes-after-april-1-2026
- Direct vs regular paper — https://www.researchgate.net/publication/392652036_Risk-Adjusted_Performance_Comparison_of_Direct_and_Regular_Plan_Equity_Mutual_Funds_in_India
- Morningstar India Mind the Gap — https://www.morningstar.in/posts/70371/why-you-dont-like-your-return-of-a-well-performing-fund.aspx ; methodology https://www.morningstar.in/posts/70368/mind-the-gap-study-methodology.aspx
- Retail flows India — https://www.sciencedirect.com/science/article/pii/S0970389621000197
- Garg & Varshney 2015 — https://journals.sagepub.com/doi/abs/10.1177/0972150915569940 ; Aravind M — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2797119
- ICI duration — https://www.ici.org/viewpoints/view_18_bond_duration
- SEBI categorisation 2017 — https://sebi.gov.in/sebi_data/attachdocs/oct-2017/1509103633344.pdf ; https://taxguru.in/sebi/categorization-rationalization-mutual-fund-scheme.html
- Rate forecasts — https://www.researchgate.net/publication/222655842 ; https://cbo.gov/system/files/115th-congress-2017-2018/workingpaper/53153-interestrateswp.pdf
- Franklin Templeton wind-up — https://www.franklintempletonindia.com/market-insights/winding-up-of-specific-schemes ; https://www.business-standard.com/article/markets/recovery-in-nav-supports-winding-up-decision-says-franklin-templeton-121060901186_1.html
- Vanguard cost averaging — https://www.nl.vanguard/professional/vanguard-365/cost-averaging
- Vanguard rebalancing — https://www.aaii.com/journal/article/best-practices-for-portfolio-rebalancing
- India SIP vs lump sum (NOT VERIFIED) — https://zenodo.org/records/21308949
- Switch taxation — https://www.kotakmf.com/Information/blogs/switch-in-mutual-fund
- SIDs — https://portal.amfiindia.com/spages/13880.pdf ; https://portal.amfiindia.com/spages/4370.pdf
- Tax rates — https://www.indiabudget.gov.in/budget2024-25/doc/memo.pdf ; https://www.pib.gov.in/PressReleasePage.aspx?PRID=2036604
- Repo: `docs/research/return-target-feasibility.md` §2.6–2.8 ; `docs/research/indian-instruments-and-tax.md` ; `docs/forecasting/validation-methodology.md`
