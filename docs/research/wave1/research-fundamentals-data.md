# Research: fundamentals data for Indian listed companies (wave 1, "fundamentals-data")

- **Research ID:** `fundamentals-data` (wave 1)
- **Date:** 2026-10-15. Every web source below was accessed on 2026-10-15.
- **Question:** Which free sources of company fundamentals for Indian listed companies are permitted by their terms? This covers quarterly results, balance sheets (NSE/BSE XBRL), shareholding patterns, promoter pledges and corporate announcements. How can they be parsed deterministically? Which fundamental signals (earnings growth, ROE, debt, pledge rise, ...) can be computed, and which have evidence behind them?
- **Status labels:** VERIFIED / NOT VERIFIED / REQUIRES CONFIGURATION / BLOCKED. This is research, not legal or investment advice.
- **Companion reports (read alongside, not repeated here):** `research-equity-data-nse.md` (NSE terms of use quoted in full, bhavcopy, licensed NSE data prices) and `research-equity-data-alt.md` (broker APIs, Upstox fundamentals API, BSE disclaimer, MCA21). This report builds on them and does not re-quote the NSE ToU at length.
- **Method note:** One automated page summary (WebFetch on the IIMA quality-factor PDF) returned a fabricated summary that named the wrong authors and the wrong sample. The PDF was then converted to text locally (`pdftotext`), and **every claim about that paper below is quoted from the local text, not from the summary.** Other PDFs (the SEBI 2019 circular and the PEAD paper) were read the same way.

---

## 0. Bottom line

1. **No free, terms-permitted source supplies Indian fundamentals in bulk and automatically.** The canonical machine-readable source is the XBRL filing on NSE/BSE, and automating it is **BLOCKED**. NSE's ToU bans "systematic or automated data collection … (including scraping, data mining, data extraction and data harvesting)", storage "in an electronic retrieval system" without permission, and use "for any … simulation activities". BSE prohibits "reproduction, redistribution or transmission". Every open-source XBRL/NSE scraper inherits these limits: `india-xbrl-filings`, `nse-xbrl-parser`'s filing fetchers, jugaad-data and nsepython are all **BLOCKED** as data sources.
2. **The lawful path is narrow but real:**
   - **(a) Manual entry with citation, the primary path.** The user types figures from the company's own results or annual report and records a URL, the filing date and the page. SEBI LODR Reg. 46(2) obliges every listed company to publish its financial results and shareholding pattern on its own website, so a non-exchange official copy always exists. Whether each company's website terms allow storing those figures was **NOT VERIFIED**: the terms differ by company, and the two fetched (Infosys, BSE) returned HTTP 403.
   - **(b) A user-downloaded XBRL instance, parsed locally, as an optional path.** The user downloads one XBRL file by hand and the app parses it deterministically, using `lxml` or Arelle (Apache-2.0). Parsing is technically sound. The remaining open question is whether NSE's "stored … in an electronic retrieval system" clause covers a personal copy. That is **NOT VERIFIED** and needs a user decision; the companion report reached the same conclusion for bhavcopy.
   - **(c) The Upstox fundamentals API, as a cross-check only.** It is **REQUIRES CONFIGURATION** and must be tagged `UNOFFICIAL_MIRROR`: the upstream vendor is undisclosed and records carry no `published_on` date (companion report §2).
3. **Several fundamental metrics can be computed deterministically and have published Indian evidence.** These are profitability (ROE/ROA/gross profit over assets), payout, leverage, the promoter pledge ratio and its change, and year-on-year EPS surprise. The strongest Indian evidence:
   - **Quality (profitability + payout):** IIMA WP 2022-11-01 reports a four-factor alpha of **0.92%/month** for long-short QMJ and **0.69%/month** for the long-only top decile, over April 1995 to March 2021 on CMIE Prowess data.
   - **Promoter pledging:** linked to **higher risk** (volatility, crash/tail risk) and lower firm value (Chauhan, Mishra & Spahr, *Financial Management* 2021).
   - **PEAD:** mixed. Harshita, Singh & Yadav (2018) find about 6% over 64 days on the Nifty 500 for 2002–2017. A 2014–2018 study of 100 NSE firms finds no drift.
   - **Piotroski F-score and accruals:** weak, old or contrary Indian evidence.
4. **None of this meets the project's own bar for a signal.** That bar is a documented, out-of-sample, cost- and tax-aware backtest that **this project** can reproduce. Every published study above relies on CMIE Prowess or Ace Equity, which are paid and licensed databases. None reports net-of-cost, net-of-Indian-tax returns for a retail investor. The project has no point-in-time, survivorship-free fundamentals history and no licensed price history.
   - **Verdict: the engine must ABSTAIN on all stock-level fundamental buy/sell signals.** Use `NO_POINT_IN_TIME_FUNDAMENTALS_HISTORY` and/or `NO_LICENSED_EQUITY_PRICE_SOURCE`.
   - **"No suitable candidate" is the correct output today.**
5. **What can ship now without breaking a rule:**
   - **(i) Descriptive fundamentals cards** for stocks the user enters manually. These show ROE, D/E, pledge % and EPS YoY as formulas with sources, and are **not** signals.
   - **(ii) Regulatory-threshold disclosure flags.** One example: "promoter encumbrance ≥ 50% of promoter holding or ≥ 20% of share capital", which is SEBI's own threshold for a mandatory reasons disclosure. Each flag cites the regulation and makes no return claim.
   - **(iii) The most practical route to the user's aim: quality-factor *funds*.** The Indian evidence for a quality tilt can be acted on through **index funds or ETFs on NSE's quality indices**, for example the Nifty200 Quality 30 index, launched 17 April 2018 with base date 1 April 2005. Their NAVs come from **AMFI**, which the project already ingests lawfully. The index's live period since 2018-04-17 is genuinely out-of-sample relative to its design. The project can therefore evaluate a fund like this with its existing MF evaluation machinery, net of TER and with MF tax rules, and needs no stock-level fundamentals data.

---

## 1. What Indian listed companies must disclose, and when (the disclosure clock)

These deadlines matter for **point-in-time correctness**. A backtest or signal may only use a figure from the date it became public. The deadline gives the worst-case lag; the actual filing date must be recorded per figure.

| Data item | Legal basis | Deadline | Machine-readable form | Status |
|---|---|---|---|---|
| Quarterly financial results (Q1–Q3), standalone + consolidated, with limited review / audit report | SEBI LODR Reg. 33(3)(a) | **45 days** from quarter end | XBRL on exchange (Integrated Filing – Financials from the Mar-2025 quarter) | VERIFIED via secondary sources (taxguru, thefootnotes.in). SEBI's consolidated LODR text not opened |
| Annual audited results (Q4) | LODR Reg. 33(3)(d) | **60 days** from FY end | XBRL | VERIFIED via secondary sources |
| Half-yearly statement of assets & liabilities + cash flow statement | LODR Reg. 33 | With the half-year results | XBRL | VERIFIED via secondary source |
| Shareholding pattern (incl. promoter encumbrance columns) | LODR Reg. 31 | **21 days** from quarter end; also within 10 days of capital restructuring changing capital by > 2% | XBRL "wherever applicable" | VERIFIED via secondary sources |
| Website copy of results, annual report, shareholding pattern | LODR Reg. 46(2)(l), (m); 46(3) updates within 2 working days | On approval of results | Company website, usually PDF | VERIFIED via secondary sources and company pages (BHEL, NTPC, SBI "Disclosure under Regulation 46" pages exist) |
| Promoter encumbrance creation / invocation / release | SAST Reg. 31(1)–(3) | **7 working days** | Since 1 Apr 2022, depository-recorded encumbrances are system-driven (depositories report to exchanges); manual filing only otherwise | VERIFIED via secondary sources (ca2013.com, taxguru, SEBI adjudication orders) |
| Reasons for encumbrance when promoter+PAC encumbrance ≥ **50% of their holding** or ≥ **20% of total share capital** | SEBI circular SEBI/HO/CFD/DCR1/CIR/P/2019/90, 7 Aug 2019, effective 1 Oct 2019 | **2 working days** from creation, and again on every further increase | Annexure-II format, "to be given manually" | **VERIFIED** (circular text read locally) |
| Annual promoter declaration of no undisclosed encumbrance | SAST Reg. 31(4)–(5) | 7 working days after FY end | Exchange filing | VERIFIED via secondary source |
| Material events (Reg. 30 announcements) | LODR Reg. 30 | Event-based | Exchange announcement feeds (PDF + metadata) | Not researched in depth. Automated feed is BLOCKED (NSE/BSE terms) |

**Engine consequence:** every fundamental observation must carry `period_end` (the quarter end), `published_on` (the actual filing date) and `observation_date`. A fundamental may be used for a decision dated *d* only if `published_on ≤ d`. Where `published_on` is unknown, a conservative fallback of `period_end + 45` (or `+ 60` for Q4) days is **not** allowed for decision use. Such an observation is `INCOMPLETE_PROVENANCE`, because companies sometimes file late and some figures are later restated.

---

## 2. Sources and their terms

| # | Source | What it has | Terms (quoted) | Automated? | Status |
|---|---|---|---|---|---|
| 1 | NSE corporate filings (financial results, Integrated Filing, shareholding, announcements, XBRL) | Everything, in XBRL plus iXBRL renderings | "User is prohibited to conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting) on or in relation to our Website" and content shall not be "stored (either in hardcopy or in an electronic retrieval system) … without prior written permission of NSE". Full text in the companion report §2.1 | No | **BLOCKED** (automation). A personal manual download is **NOT VERIFIED** (ambiguous storage clause) |
| 2 | BSE corporate filings / XBRL | Same scope | "Any reproduction, redistribution or transmission, for consideration or otherwise, of any such information contained in the Website is strictly prohibited" (BSE disclaimer quoted in the source registry §2.11; `bseindia.com/disclaimer.html` returned **HTTP 403** to WebFetch today) | No | **BLOCKED** (automation). Manual private use **NOT VERIFIED** |
| 3 | NSE XBRL Filing Information page (taxonomies, templates) | Taxonomy `.xsd`, label/calc/presentation linkbases, per regulation | Same NSE ToU. WebFetch timed out today | One manual download of the taxonomy to build the parser | Taxonomy page existence VERIFIED via search only; contents **NOT VERIFIED** directly |
| 4 | Company websites (LODR Reg. 46) | Results PDFs, annual reports, shareholding pattern, earnings-call transcripts | Different per company. The two fetched (Infosys ToU, BSE disclaimer) returned **HTTP 403**. No general statement can be made | No (one company at a time, user-initiated) | **NOT VERIFIED** per company. The only official non-exchange source |
| 5 | SEBI website | Regulations, circulars (the *rules*, not company data) | "Material featured on this Website may be reproduced free of charge after taking proper permission by sending a mail to us." (companion report) | Not needed | VERIFIED. Not a fundamentals source |
| 6 | MCA21 public documents (AOC-4 XBRL) | Audited annual statements | Login plus a per-company fee (~₹100, secondary source) | No | **NOT VERIFIED** (fee). Optional, user-paid, manual |
| 7 | Upstox fundamentals API (user's own account) | Income statement, balance sheet, cash flow, shareholding, ratios, corporate actions by ISIN (launched 11 May 2026) | Forum moderator: "You are permitted to utilize the data provided by the Upstox API for analysis purposes". Formal terms NOT VERIFIED | Yes, with the user's own key | **REQUIRES CONFIGURATION**; must be tagged `UNOFFICIAL_MIRROR`; no `published_on` field, so it cannot be used for backtests |
| 8 | IIMA Fama-French & Momentum library | Monthly/daily **factor returns** (MKT, SMB, HML, WML), Oct 1993 – Dec 2025 (release 2025-12) | No terms or licence text on the page. Only a citation request: "Please cite the source of the data as follows: Agarwalla, S. K., Jacob, J. and Varma, J. R. (2013)…" | Yes (CSV downloads) | VERIFIED (page). Licence **NOT VERIFIED** (silent). Useful only for **factor attribution of funds**, not stock signals |
| 9 | Ashoka/SCDLDS Financial Factor Data Library | Factor returns incl. RMW (profitability), CMA (investment), accruals, sales growth; Oct 2003 – Sep 2026, monthly | "This library is free to use for academic purposes. If it contributes to your work, please cite us." | CSV | VERIFIED (page). Personal-investor use is **NOT VERIFIED**: the grant names academic purposes only. Treat as **BLOCKED** until the authors confirm |
| 10 | Paid databases (CMIE Prowess, Ace Equity, Refinitiv) | Point-in-time fundamentals history: what every Indian study uses | Licensed | — | **BLOCKED** (paid). Out of scope by the no-paid-keys rule |

---

## 3. Deterministic parsing design (for paths (a) and (b))

### 3.1 XBRL format facts that a parser must handle

- **Two generations of namespaces.** Filings from the Mar-2025 quarter onward use SEBI's Integrated Filing (Financials) and the `in-capmkt` taxonomy, in 2022 and 2024 versions. Older filings use a different prefix, e.g. `in-bse-fin`. One developer found 32 of 32 old-format filings used `in-bse-fin`, and noted the prefix contains a hyphen, so "a naive `[A-Za-z0-9_]+` regex silently matches nothing". This is a secondary source (tigzig.com VIGIL write-up, via search): **NOT VERIFIED** against an official taxonomy, but cheap to test with a fixture.
- **NSE says the XBRL is generated by its utility.** "Data is automatically converted into XBRL format by a utility built into NEAPS" (via search on NSE's XBRL information page; the page itself timed out, so **NOT VERIFIED** directly). Concept usage should therefore be consistent across companies within one taxonomy version.
- **Context handling is mandatory.** One instance file holds several periods (current quarter, previous quarter, the same quarter last year, YTD) and both standalone and consolidated results. The parser must select facts by `contextRef`, using period start/end and the consolidated/standalone dimension. It must never select by element name alone.
- **Units and scale.** Values carry a `unitRef` (INR) and `decimals`. Figures must be parsed to `Decimal` from the lexical value, never through `float`.

### 3.2 Recommended parser architecture (fits ADR 0002 money precision, ADR 0004 data sources, ADR 0011 test oracles)

1. **Adapter, outside `engine/`.** It reads a user-supplied file, keeps no network code in the engine, and validates the file against the taxonomy with **Arelle**. Arelle is "an end-to-end open source XBRL platform" under the **Apache License 2.0** (VERIFIED, github.com/Arelle/Arelle). A lighter path is `lxml` with an explicit concept map. Arelle is better for validation; `lxml` is enough for extraction from a known taxonomy version.
2. **Explicit concept map, versioned per taxonomy.** The map is a table: `{taxonomy_version, concept_qname} → canonical_field` (e.g. `revenue_from_operations`, `profit_after_tax`, `total_equity`, `total_borrowings`, `promoter_shares_encumbered`). An unknown taxonomy version produces `quality_status = SCHEMA_CHANGED`, with no guessing.
3. **Calculation-linkbase check as a determinism gate.** Re-add the components (e.g. total income = revenue + other income) with `Decimal`. If a stated total disagrees with the sum of its parts beyond the rounding implied by `decimals`, set `quality_status = CONFLICT` and stop the figure from reaching decisions.
4. **Provenance on every figure:** `source_id`, file SHA-256, taxonomy version, `contextRef`, `period_end`, `published_on` (entered by the user from the filing's timestamp), `consolidation` (standalone/consolidated), `licence_class = UNKNOWN` until the user resolves the NSE storage question.
5. **Fixtures:** synthetic XBRL instances with fictional values and the real layout, as the project already does for AMFI and RBI (source registry §0). Real filings are **not** committed to the public repo.
6. **Manual-entry path (a):** the same canonical fields and provenance, with `quality_status = OFFICIAL_MANUAL` and a required `citation_url` + `page`. Use a double-entry check: the user enters both components and the total, and the engine recomputes the total.

### 3.3 Restatements

Companies restate prior-period figures. They appear in the next filing's comparative column. Store each version as a new observation that references the old one, and never overwrite it (source registry rule 3). Point-in-time queries use the version with the latest `published_on ≤ d`.

---

## 4. Signals: computability and evidence

"Computable" means it can be computed deterministically from the canonical fields above. "Evidence" means published, peer-reviewed or working-paper results on **Indian** data. **Signal allowed?** applies the project rule: a documented out-of-sample, cost- and tax-aware backtest that **this project can reproduce**.

| Metric / candidate signal | Formula (canonical fields) | Computable from lawful data? | Indian evidence | Signal allowed? |
|---|---|---|---|---|
| **Profitability** (ROE, ROA, gross profit/assets, cash-flow ROA) | e.g. ROE = PAT / avg(total equity) | Yes, per stock, from manual or XBRL entry | **Strong.** IIMA WP 2022-11-01 (Jacob, K.P., Varma): "The key drivers of the alpha are profitability and payout". Sample: "April 1995 to March 2021", "top 1,000 firms by market capitalization", data from "CMIE Prowess" | **No: ABSTAIN.** The project cannot reproduce it (needs a point-in-time cross-section) |
| **Payout** (net equity issuance, net debt issuance, total net payout) | From cash-flow and equity statements | Yes | Strong (same paper: profitability and payout "appear to deliver significant alphas") | **No: ABSTAIN** (same reason) |
| **Composite quality (QMJ)** | Average of profitability, growth, safety, payout z-scores | Only cross-sectionally (needs the universe) | QMJ "earns a four factor alpha of 0.92% per month"; long-only "0.69% per month"; still significant in top-250; annual churn "about 87%" against "about 249%" for momentum | **No** at stock level. **Yes, indirectly, via quality index funds** (§5) |
| **Growth** (Δ ROE, Δ ROA, Δ gross profit/assets) | YoY changes | Yes | **Weak:** "It is somewhat surprising that higher growth does not in itself contributes positive alpha" (same paper) | No |
| **Leverage / safety** (D/E, low leverage) | total borrowings / total equity (not meaningful for banks/NBFCs) | Yes | Part of QMJ safety, but not singled out as an alpha driver in that paper. Used as a component of NSE quality indices (§5) | No (descriptive only) |
| **Promoter pledge level and rise** | encumbered promoter shares / promoter shares; and / total shares; Δ quarter on quarter | Yes, from shareholding-pattern figures | **Risk, not return:** Chauhan, Mishra & Spahr (2021), 1,452 firms: pledging "exacerbates stock volatility, fosters lower risk capital investments, adversely affects firm values, and impedes longer-term performance". Prime Database / Kalia (2024) / a 2009–2023 study link pledging to crash and tail risk (via search, NOT VERIFIED beyond abstracts) | **No as a buy/sell signal.** **Yes as a disclosure flag** tied to SEBI's 50%/20% thresholds (§6) |
| **Earnings surprise / PEAD** | SUE = (EPS_q − EPS_{q−4}) / price | Needs price on the announcement date (licensed price source) plus exact `published_on` | **Mixed.** Harshita, Singh & Yadav (2018): "statistically significant returns of 6 per cent during 64 days post the earnings announcement", Nifty 500, 2002–2017, Ace Equity. Caveats: the sample was fixed on "31 March 2014" (survivorship risk), long-short, no net-of-cost result. A 2014–2018 study of 100 NSE firms finds no drift (via search) | **No: ABSTAIN** (no licensed price source; short legs not available to a retail cash investor) |
| **Piotroski F-score** | 9 binary tests on ROA, CFO, ΔROA, accruals, Δleverage, Δliquidity, issuance, Δmargin, Δturnover | Yes (annual statements, 2 years) | **Weak/old:** Singh & Kaur (2015), BSE 1996–2010; Tripathy & Pani (2017), 2010–2015 (both via search, abstracts only). Negative replication in Poland 2012–2022 | No |
| **Accruals** | (PAT − CFO) / avg total assets | Yes | **Contrary/insignificant:** Pincus, Rajgopal & Venkatachalam (2007) found India's accrual-anomaly returns "negative but not statistically significant"; one Indian multi-anomaly study found the relationship reversed (via search) | No |
| **Valuation (P/E, P/B)** | price / EPS, price / book | Needs a licensed price | IIMA library HML; the value factor returned 9.08%/yr at 16.33% vol in the 2017 journal version (via search) | No (price source missing); attribution only |

**Why the project cannot reproduce any of the stock-level studies:**

1. **No point-in-time fundamentals history across a universe.** Manual entry covers a handful of companies, not the top 500–1,000 needed for a cross-sectional sort, and the paid databases are out of scope.
2. **No survivorship-free universe.** Historical index constituents are NOT VERIFIED as freely available (companion report, row 10).
3. **No licensed price history** for returns until Upstox is configured, and even then its storage and backtest terms are NOT VERIFIED.
4. **Costs and tax are missing.** No study reports returns net of STT, brokerage, stamp duty, impact cost and Indian STCG/LTCG for a retail investor. All the headline alphas are gross, and most are long-short; a retail cash-market investor cannot short-sell for months at a time.
5. **Decay risk.** A paper titled "Are Prominent Equity Market Anomalies in India Fading Away?" (Sharma, Subramaniam & Sehgal, 2021) exists. Its abstract could not be read (SAGE returned HTTP 403), so its conclusion is **NOT VERIFIED**, but the title alone argues for caution.

---

## 5. The route that is actually usable today: quality-factor funds

- **NSE runs quality-factor indices**, and AMCs run index funds on them:
  - **Nifty200 Quality 30:** launched 17 April 2018, base date 1 April 2005. Sources: the factsheet `niftyindices.com/Factsheet/Factsheet_NIFTY200_Quality30.pdf` and a Business Standard report (both via search).
  - **Selection:** stocks are scored on "return on equity (ROE), financial leverage (Debt/Equity Ratio) and earnings (EPS) growth variability over the previous 5 years", with D/E not used for financial-services companies.
  - **Exact weights:** an AMC presentation gives a quality score of 0.33·z(ROE) + 0.33·z(−D/E) + 0.33·z(−EGV) for the sister Nifty100 Quality 30. That is a secondary source, and the official methodology document was **NOT VERIFIED**.
  - **Funds:** examples include the SBI and UTI Nifty200 Quality 30 index funds and the HDFC Nifty100 Quality 30 index fund (via search).
- **Why this fits the binding rules:**
  1. NAV data comes from **AMFI**, already an approved source (source registry), so no exchange data is needed.
  2. **Out-of-sample by construction.** Index values before 17 April 2018 are a back-calculation; values after it are live. The engine must use **only the post-launch live period**, and only fund NAVs net of TER, as evidence.
  3. Costs are inside the NAV (TER), and MF taxation is already modelled (`indian-instruments-and-tax.md`).
  4. Factor attribution against the IIMA four-factor series can show whether a fund actually delivers quality exposure, subject to the IIMA licence caveat (§2 row 8).
- **What the engine may say:** fund-level metrics (rolling returns, drawdown, tracking error, TER) computed from AMFI NAVs, with the same abstention rules as any other fund. It must **not** claim that the fund "will" beat the market. The Indian QMJ alpha is a historical, gross, Prowess-based result.
- **Limitation:** NSE Indices' own pages are subject to its ToU (companion report: "You may not conduct any systematic or automated data collection activities … without our express written consent"). Index levels and constituents are entered **manually** with citations. Fund NAVs come from AMFI.

---

## 6. Recommended product behaviour (concrete, rule-compliant)

1. **Equity "signals" panel → ABSTAIN** for every stock-level fundamental signal, showing a reason code:
   - `NO_POINT_IN_TIME_FUNDAMENTALS_HISTORY`: no reproducible cross-sectional backtest.
   - `NO_LICENSED_EQUITY_PRICE_SOURCE`: Upstox not configured.
   - `EVIDENCE_GROSS_OF_COST_ONLY`: published alphas are gross, long-short, and from a licensed database.
2. **Fundamentals card (descriptive, not a signal)** for stocks the user enters:
   - **Shows:** ROE, ROA, D/E (hidden for banks/NBFCs), EPS YoY, payout ratio, promoter holding %, and promoter pledge % of holding and of total capital.
   - **Provenance:** each value shows its formula, `period_end`, `published_on`, citation and `quality_status`.
   - **Wording:** no colour coding that implies buy or sell.
3. **Regulatory flags** (deterministic, cited, no return claim):
   - `PLEDGE_THRESHOLD_SEBI_2019`: promoter+PAC encumbrance ≥ 50% of their holding, or ≥ 20% of total share capital. Cite SEBI/HO/CFD/DCR1/CIR/P/2019/90.
   - `PLEDGE_INCREASED_QOQ`: the pledge ratio rose against the previous quarter's shareholding pattern. Cite the published risk evidence (Chauhan et al. 2021), framed as "associated with higher volatility and crash risk in published Indian studies", never as a sell signal.
   - `RESULTS_OVERDUE`: today > `period_end` + 45 days (60 for Q4) and no results entered. Cite LODR Reg. 33. This is a data-freshness flag, not an inference about the company.
4. **Quality-tilt option in the MF module:** list quality-index funds as candidates and evaluate them on live post-launch AMFI NAV history, net of TER, with the normal MF ranking and abstention rules.

---

## 7. User decisions needed

1. **Personal storage of manually downloaded NSE/BSE XBRL files (path b):** accept the legal ambiguity of NSE's "stored … in an electronic retrieval system" clause, write to NSE for permission, or stay with manual typed entry only (path a)?
2. **Upstox fundamentals:** configure it as a cross-check source (local mode only, `UNOFFICIAL_MIRROR`)?
3. **IIMA factor data** (licence silent; citation requested) for fund factor attribution: is a cited personal use acceptable, or should the authors be emailed first? The **SCDLDS** library's "academic purposes" grant would need explicit permission.
4. **Quality-index funds:** add them as a first-class candidate category in the MF module (the evidence-backed way to act on fundamentals without stock-level data)?

---

## 8. Sources (all accessed 2026-10-15)

**Regulation and disclosure**
- SEBI circular SEBI/HO/CFD/DCR1/CIR/P/2019/90 (7 Aug 2019), copy at https://ca2013.com/wp-content/uploads/2019/08/Reason-for-encumbrance.pdf. Read locally: "a) 50% of their shareholding in the company; or b) 20% of the total share capital of the company". VERIFIED.
- LODR Reg. 33 / 31 deadlines: https://taxguru.in/sebi/compliances-sebi-lodr-2015.html, https://thefootnotes.in/articles/q2-fy27-results-regulation-33-disclosures. Via search: "within twenty one days from the end of each quarter" (Reg. 31); 45 days for quarterly results.
- LODR Reg. 46: https://ca2013.com/lodr-regulation-46/; examples https://www.bhel.com/disclosure-under-regulation-46-sebi-lodr-regulations, https://sbi.bank.in/web/investor-relations/disclosure-under-regulation-46. Via search: "Financial results, on conclusion of the meeting of the board of directors where the financial results were approved".
- SAST Reg. 31: https://ca2013.com/toc-regulation-31/, https://taxguru.in/sebi/disclosure-requirements-encumbrance-shares-promoters-listed-companies.html. Via search: "within seven working days from the creation or invocation or release of encumbrance".
- SEBI adjudication order on encumbrance disclosures: https://www.sebi.gov.in/sebi_data/attachdocs/sep-2018/1536244822899.pdf (via search).

**Data sources and tools**
- NSE XBRL Filing Information: https://www.nseindia.com/static/companies-listing/xbrl-information (WebFetch timed out; content via search only, NOT VERIFIED).
- NSE Integrated Filing: https://www.nseindia.com/companies-listing/corporate-integrated-filing (via search).
- Namespace notes: https://www.tigzig.com/vigil/india-xbrl-filings (secondary, via search).
- nse-xbrl-parser: https://pypi.org/project/nse-xbrl-parser/ (via search: "catalog of all 58 taxonomies").
- india-xbrl-filings: https://github.com/dhananjaym182/india-xbrl-filings ("Personal/educational use"; unofficial endpoints). BLOCKED as a source.
- Arelle: https://github.com/Arelle/Arelle ("Apache License 2.0").
- IIMA library: https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/ ("Please cite the source of the data as follows: Agarwalla, S. K., Jacob, J. and Varma, J. R. (2013)…"; release 2025-12).
- SCDLDS library: https://quantfin.scdlds.com/ ("This library is free to use for academic purposes.").
- BSE disclaimer: https://www.bseindia.com/disclaimer.html (HTTP 403 today; quote from the source registry).
- Infosys terms: https://www.infosys.com/terms-of-use.html (HTTP 403 today; NOT VERIFIED).
- Nifty200 Quality 30 factsheet: https://niftyindices.com/Factsheet/Factsheet_NIFTY200_Quality30.pdf (via search). HDFC Nifty100 Quality 30 NFO presentation: https://files.hdfcfund.com/s3fs-public/Others/2025-01/NFO%20Presentation%20-%20HDFC%20Nifty100%20Quality%2030%20Index%20Fund%20(January%202025).pdf (via search). Launch report: https://www.business-standard.com/article/pti-stories/nse-s-iisl-launches-nifty-200-quality-30-index-118041800521_1.html (via search).

**Evidence**
- Jacob, K.P. & Varma (2022), *Performance of quality factor in Indian Equity Market*, IIMA WP 2022-11-01: https://www.iima.ac.in/sites/default/files/2022-12/Wp-2022-11-01.pdf. Read locally: "The QMJ factor earns a four factor alpha of 0.92% per month"; "A long-only Quality factor earns an alpha of 0.69% per month"; "The key drivers of the alpha are profitability and payout"; "April 1995 to March 2021"; "CMIE Prowess database"; churn "about 249%" (momentum) vs "about 87%" (quality). VERIFIED.
- Chauhan, Mishra & Spahr (2021), *Stock pledging and firm risk: Evidence from India*, Financial Management 50(1): https://ideas.repec.org/a/bla/finmgt/v50y2021i1p261-280.html. Abstract quoted above. VERIFIED.
- Kalia (2024), JAMR, doi 10.1108/JAMR-01-2023-0003: https://www.researchgate.net/publication/378335023 (via search, NOT VERIFIED beyond the snippet).
- Prime Database study: http://www.primedatabasegroup.com/newsroom/SHARE_PLEDGING_&_ITs_CONSEQUENCES_A_STUDY_OF_INDIAN_FIRMS.pdf (via search: "1,492 NSE-listed firms from 2009 to 2019"). NOT VERIFIED directly.
- Harshita, Singh & Yadav (2018), *PEAD Anomaly in India*, Theoretical Economics Letters 8: https://www.scirp.org/pdf/tel_2018102515432009.pdf. Read locally: "statistically significant returns of 6 per cent during 64 days post the earnings announcement"; "The date of sample selection is 31 March 2014"; "Ace Equity®". VERIFIED.
- PEAD and value-glamour in NSE firms (2014–2018, 100 firms): https://www.econstor.eu/handle/10419/308924 (via search). NOT VERIFIED directly.
- Tripathy & Pani (2017), F-score India: https://www.researchgate.net/publication/312397957 (via search). NOT VERIFIED directly.
- Pincus, Rajgopal & Venkatachalam (2007), *The Accounting Review* 82(1): https://business.columbia.edu/sites/default/files-efs/pubfiles/12947/pincus%20rajgopal%20venkatachalam%20TAR.pdf (via search: India "negative but not statistically significant").
- Sharma, Subramaniam & Sehgal (2021), *Are Prominent Equity Market Anomalies in India Fading Away?*: https://doi.org/10.1177/0972150918811248 (SAGE returned HTTP 403; conclusion NOT VERIFIED).
- Agarwalla, Jacob & Varma (2017), *Size, Value, and Momentum in Indian Equities*: https://journals.sagepub.com/doi/full/10.1177/0256090917733848 (via search: HML "9.08% a year with 16.33% annual volatility").
