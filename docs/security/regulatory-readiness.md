# Regulatory Readiness: Investment Intelligence Pro

| Field | Value |
|---|---|
| Status | Research draft, v1 |
| Prepared | 2026-10-15 |
| Author | Agent K (Compliance & Regulatory Researcher), automated research |
| Jurisdiction | India (SEBI, AMFI, RBI, MeitY) |
| Review cadence | Re-check before any change of distribution model, and at least every 6 months |

> **This is not legal advice.** The author is not a lawyer or a SEBI-registered intermediary. This document records what public primary and secondary sources say, how the product team reads them, and which design controls follow. Every "risk level" here is an engineering judgment, not a legal opinion. Anything beyond personal self-use **must** be reviewed by a qualified Indian securities lawyer and/or a SEBI-registered Investment Adviser/Research Analyst compliance professional before launch.

Verification legend: **[P]** = checked against a primary source (sebi.gov.in, Gazette, India Code, AMFI, NSE); **[S]** = from reputable secondary sources only (law-firm notes, legal news) and the primary text was not extracted; **NOT VERIFIED** = from memory or a single unconfirmed source. Do not rely on it.

---

## 1. Intended scope statement

Investment Intelligence Pro (IIP) v1 is a **personal, self-hosted, single-user, deterministic research and decision-support tool**. It runs on `localhost`, and its developer is its only user.

It **does**:
- ingest public data (AMFI NAV files, RBI publications, and similar public datasets);
- compute historical returns, risk metrics, and after-tax outcomes under user-entered assumptions;
- filter and rank instruments **mechanically, against constraints the user has stated themselves** (for example "expense ratio < 1%, category = liquid, 3-year volatility < X");
- run user-defined scenarios ("what if returns were X%") and explain how each result was computed.

It **does not**:
- execute trades, place orders, move money, or link to brokers, RTAs, AMCs, or bank accounts;
- distribute mutual funds or any other product, or receive commissions;
- charge fees or carry advertising;
- serve any person other than the developer;
- publish outputs, rankings, or "picks" to anyone.

**Change triggers.** Any of the following changes the regulatory picture and requires a fresh review **before** it ships: a second user, a public URL, a hosted/SaaS deployment, any payment or monetisation (including ads or data monetisation), publishing outputs (blog, social media, Telegram, newsletter), white-labelling for an adviser or distributor, any order or transaction links, or ingesting exchange price feeds beyond what personal-use terms allow.

---

## 2. Regulatory landscape (research findings)

### 2.1 SEBI (Investment Advisers) Regulations, 2013 ("IA Regs")

- **Definition of investment advice, Reg. 2(1)(l).** As originally notified, investment advice is advice "relating to investing in, purchasing, selling or otherwise dealing in securities or investment products, and advice on investment portfolio containing securities or investment products ... for the benefit of the client and shall include financial planning". **[P]** for the 2013 Gazette text: <https://www.sebi.gov.in/sebi_data/attachdocs/1358779330956.pdf>
- **Public-media proviso.** The original Gazette text says: "Provided that investment advice given through newspaper, magazines, any electronic or broadcasting or telecommunications medium, which is widely available to the public shall not be considered as investment advice for the purpose of these regulations." **[P]** (same Gazette PDF). SEBI's IA FAQ (Aug 2025) still treats advice "widely available to the public" as outside the definition. **[P]** <https://www.sebi.gov.in/sebi_data/faqfiles/aug-2025/1755174193178.pdf>
  - **Caveat.** Commentators and SEBI's 2016 consultation say public-media recommendations are still subject to the **Research Analysts Regulations (Reg. 21/public appearance)**. The proviso therefore takes such content out of the *IA* regime only, not out of securities regulation generally. **[S]** (AZB Partners; SEBI 2016 consultation)
  - **Our reading (not a legal conclusion).** A web app that produces **personalised** output from a user's own inputs is unlikely to be "widely available to the public" advice in the sense of a newspaper column. Each user receives individual output. **Do not rely on this proviso** for any multi-user version.
- **Investment adviser, Reg. 2(1)(m).** "Any person, who for consideration, is engaged in the business of providing investment advice to clients or other persons or group of persons and includes any person who holds out himself as an investment adviser, by whatever name called." **[P]** (2013 Gazette). The key elements are **consideration**, **business**, and **clients/other persons**. "Holding out" can apply without any fee.
- **Dec-2024 overhaul.** The SEBI (Investment Advisers) (Second Amendment) Regulations, 2024 were notified 16/17 Dec 2024 as SEBI/LAD-NRO/GN/2024/219. **[S]** (taxguru, Mondaq, AZB). Main changes:
  - a new **part-time IA** category, which must use the label "part-time investment adviser" **[P]**, IA FAQ Q10–11;
  - revised qualification and certification requirements;
  - **trading calls** excluded from investment advice and IAs barred from giving them. SEBI defines trading calls as "intraday, ultra-short duration, non-delivery based (other than hedging) recommendation or any recommendation related to securities that are not personalized or investor specific". **[P]**, IA FAQ Q28;
  - "investment advice" narrowed to securities within SEBI's remit; advice on non-SEBI products is allowed with disclosures **[S]**;
  - fee cap: fixed fee raised to **₹1,51,000 per year per family**, or **2.5% of AUA** **[S]**;
  - a client-count-based deposit (₹1 lakh up to 150 clients, rising to ₹10 lakh above 1,000) **[P]**, IA FAQ Q4;
  - an individual IA must migrate to non-individual registration above 300 clients or ₹3 crore in fees **[S]**.
- **AI-use disclosure.** Reg. 18(9), as amended, requires an IA to disclose to clients the extent to which it uses AI tools. The IA remains **solely responsible** for data security, confidentiality, the advice itself, and legal compliance, whether the tools are in-house or third-party. Operationalised by SEBI Circular **SEBI/HO/MIRSD/MIRSD-PoD-1/P/CIR/2025/003 dated 08-Jan-2025**. **[S]** (taxmann, taxguru, JSA). SEBI's IA FAQ (Aug 2025) does not discuss this, so the regulation text is the authority.
- **Later instruments.** IA Master Circular dated 27-Jun-2025, superseded/updated by a Master Circular dated **06-Feb-2026** **[S]**, listed on sebi.gov.in. The IA Regs were "last amended on November 25, 2025", per SEBI's regulations index **[S]**. The content of the Nov-2025 amendment is **NOT VERIFIED**. A 2025 amendment to Reg. 8 (deposit lien, effective 05-Aug-2025, SEBI/LAD-NRO/GN/2025/253) is **[S]**.
- **Robo/automated advice.** Using software or algorithms does not take advice outside the IA Regs. Advice delivered through a tool is still advice. Explicit SEBI guidance on "automated tools" in the current Master Circular is **NOT VERIFIED**. The Jan-2025 AI rules show SEBI regulates the *person* and not the delivery medium.

### 2.2 SEBI (Research Analysts) Regulations, 2014 ("RA Regs")

- **Third Amendment.** The SEBI (Research Analysts) (Third Amendment) Regulations, 2024, SEBI/LAD-NRO/GN/2024/220, 16-Dec-2024. **[S]** (taxguru, taxtmi). Main changes:
  - "research analyst" redefined as a person who "**for consideration**, is engaged in the business of providing research services", including part-time RAs;
  - "research services" now expressly includes **trading calls**;
  - part-time RAs limited to 75 clients;
  - **Reg. 19(vii)**: RAs must disclose AI-tool use to clients;
  - **Reg. 24(7)**: an RA using AI tools is solely responsible for the security, confidentiality and integrity of client data.
- **Research report.** The pre-2024 definition covered written or electronic communication that includes research analysis or research recommendation, or an opinion on securities or public offers, providing a basis for an investment decision. The exact amended text is **NOT VERIFIED**. It must be checked against the consolidated RA Regs on sebi.gov.in. The RA Master Circular was also updated 06-Feb-2026 **[S]**.
- **Relevance.** A tool that publishes **ratings, targets, or "top-N" lists of specific listed securities** to third parties looks like research reports or recommendations. If it is offered for consideration, or by a person "holding out", RA registration is a live question.

### 2.3 "Finfluencer" / association restrictions and educational price-data rules

- **Aug-2024 amendments.** These amended the Intermediaries Regs 2008 (new **Reg. 16A**), the SECC Regs 2018 (Reg. 44B), and the D&P Regs 2018 (Reg. 82B), published 29-Aug-2024. SEBI-regulated persons and MIIs may not associate (money, referrals, IT interaction, client-data sharing, and similar links) with persons who (a) give securities advice or recommendations without registration, or (b) make return or performance claims without SEBI permission. **[S]**
- **Clarification circular.** **SEBI/HO/MIRSD/MIRSD-PoD-1/P/CIR/2025/11 dated 29-Jan-2025**: "Details/clarifications on provisions related to association of persons regulated by the Board, MIIs, and their agents with persons engaged in prohibited activities". **[S]**. Copies are hosted by NSDL and CSE; the sebi.gov.in page was not fetched. It includes the education carve-out: a person "engaged solely in education" must not be "using the market price data of the preceding three months to speak/talk/display the name of any security including using any code name of the security". **[S]** (direct quote reported by Business Standard and Legal500)
- **May-2026 change.** **Circular No. HO/47/17/12(11)2025-MRD-POD3/I/11107/2026 dated 08-May-2026**, "Norms for sharing and usage of price data for educational purposes". The circular's existence, title, number, and date are **[P]**: <https://www.sebi.gov.in/legal/circulars/may-2026/norms-for-sharing-and-usage-of-price-data-for-educational-purposes_101293.html>. Its content is **[S]** only, because the PDF body could not be extracted. Per LiveLaw and CorpLawUpdates, it amends FAQ Q.8 of the Jan-2025 circular, **reduces the educational lag from 3 months to 30 days**, is effective **01-Jul-2026**, and applies where data is used "in a manner indicating future prices, advice or recommendations". **Treat the 30-day figure as unconfirmed until the PDF is read.**
- **Applicability to IIP.**
  - These rules bind **SEBI-regulated entities** and their associations. They do not directly regulate an unregistered individual's private tool.
  - They become directly relevant if IIP is ever distributed as "education", partnered with a broker, AMC, or distributor, or monetised through any regulated entity.
  - For personal use: not applicable.
  - For public distribution: the "education" route requires (i) no advice or recommendations, (ii) no return or performance claims, and (iii) a price-data lag (30 days per [S], previously 3 months) whenever a named security is shown.

### 2.4 Mutual fund distribution (AMFI ARN/EUIN) and Execution-Only Platforms

- **Who needs an ARN.** Distribution (selling or arranging units for commission) requires AMFI registration (ARN) and an EUIN for the employees involved. Commission-based distribution is the trigger.
- **Distributor exemption from IA registration.** An AMFI-registered MFD giving advice "incidental to its distribution activity" is exempt from IA registration. "Incidental" means "basic advice pertaining to investment in mutual fund schemes", limited to the schemes it distributes. **[P]**, IA FAQ Q19.
- **Execution-Only Platforms.** SEBI Circular **SEBI/HO/IMD/IMD-PoD-1/P/CIR/2023/86 dated 13-Jun-2023**, effective 01-Sep-2023. **[S]**; a copy is hosted by CSE, and AMFI's EOP guidelines are at <https://www.amfiindia.com/eops/amfi-guidelines>. Key points:
  - any digital platform that **facilitates transactions** (subscription, redemption, switch) in direct plans must register as an EOP, either Category 1 with AMFI or Category 2 as a stock broker;
  - an EOP must be a body corporate;
  - EOPs may not give incidental advice.
- **Applicability to IIP.** Showing, comparing, or ranking funds **without facilitating transactions and without commission** is not distribution and not EOP activity, on our reading. **Adding "invest now" deep links, order placement, or referral or commission arrangements would cross into distribution or EOP territory.**

### 2.5 Stock broking and Online Bond Platform Providers (OBPP): out of scope

- Execution, order routing, and broking require registration under the SEBI (Stock Brokers) Regulations, 1992 (or any successor regulations; replacement is **NOT VERIFIED**).
- OBPPs selling listed debt online must register as stock brokers in the debt segment. The SEBI OBPP framework of Nov-2022 is cited here from memory and is **NOT VERIFIED**.
- IIP v1 executes nothing and **is not in scope** of either regime. This must stay a hard boundary (guardrail G1).

### 2.6 SEBI on AI/ML

- **Consultation paper.** "Guidelines for Responsible Usage of AI/ML in Indian Securities Markets", 20-Jun-2025, comments closed 11-Jul-2025. **[S]** (Lexology, IndiaCorpLaw, taxguru). It proposes:
  - model governance and senior-management accountability;
  - testing and monitoring;
  - fairness and bias controls;
  - data privacy;
  - **disclosure of AI use to clients**, including for advisory services;
  - a lighter regime for AI not used in client-facing operations.
- **Final guidelines.** As of 15-Oct-2026, final guidelines appear **not yet issued**. On 10-Oct-2026 the SEBI Chairman reportedly said they will come "shortly", with a tiered approach, kill switches, and human oversight. **[S]**, news reports only.
- **Existing reporting.** A 2019 framework requires regulated entities to report AI/ML systems to SEBI. **[S]**
- **Relevance.** IIP is deterministic and uses no LLM in its decision path, which is the simplest posture. If any AI/LLM explanation layer is ever added, IIP should copy the IA/RA rule now: disclose AI use and the extent of it, and keep a human (the user) accountable. AI must never be the source of a recommendation.

### 2.7 Data protection: DPDP Act 2023 and DPDP Rules 2025

- **Personal/domestic exemption.** Act s.3(c)(i): the Act does not apply to "personal data processed by an individual for any personal or domestic purpose". **[S]** (Indian Kanoon copy of s.3). Primary: Act No. 22 of 2023 on India Code / MeitY.
- **Rules notified.** DPDP Rules 2025 were notified **13-Nov-2025, G.S.R. 846(E)**, with commencement notifications G.S.R. 843(E)–845(E). **[S]** (Legal500, Mondaq; Gazette PDF not fetched). Phasing:
  - Board-related rules: immediate;
  - Consent Manager registration (Rule 4): +12 months, about **13/14-Nov-2026**;
  - substantive obligations (notice, consent, security safeguards, breach notification, rights, children's data, penalties): +18 months, about **13/14-May-2027**.
  - Sources differ by one day; confirm against the Gazette.
- **Posture by mode:**
  - **Personal self-use (v1).** The developer processing their own financial data is very likely exempt under s.3(c)(i). Good security hygiene is still adopted (see §6).
  - **Multi-user service, free or paid.** The operator becomes a **Data Fiduciary**. Financial holdings, income, tax status, and goals are personal data. The full obligations apply from May-2027: notice, consent, purpose limitation, reasonable security safeguards, breach notification to the Board and to affected users, erasure, and grievance redressal. Any processor (hosting, analytics) needs a contract. The exemption is lost the moment data of anyone other than the operator is processed.

### 2.8 Advertising, performance presentation, and claims

- **SEBI MF advertisement code** (MF Master Circular, advertisement chapter; 2017 "Review of advertisement guidelines" and later). **[S]**: the copy hosted by HDFC AMC, not the sebi.gov.in master circular. Requirements:
  - performance shown as **CAGR for 1, 3, and 5 years and since inception**, plus **point-to-point value of ₹10,000**;
  - computed to the **last day of the month preceding** the advertisement;
  - **regular vs direct plan** stated, with an expense-structure footnote;
  - fund-manager changes footnoted;
  - the line "past performance may or may not be sustained in future" placed next to the returns;
  - schemes under 6 months old: no performance shown.
- **AMFI.** AMFI best-practice circular **No. 109 dated 01-Nov-2023** covers SIP/SWP/STP calculators and illustrations. **[S]**: AMFI-hosted PDF <https://www.amfiindia.com/Themes/Theme1/downloads/circulars/SEBI/CU148-AMFI%20BP%20cir%20109%20dt.%2001-Nov-23.pdf>, not opened. Calculators must carry the standard warning and "past performance may or may not be sustained in future and is not a guarantee of any future returns".
- **Applicability.** These codes legally bind AMCs and MFDs, **not** a personal tool. IIP adopts them as a **design standard**: they are the conventions a regulator and a reader expect, and adopting them now avoids rework if IIP is ever offered to others.
- **Guaranteed returns.** Claims of guaranteed or assured returns on market-linked products are what SEBI's Reg. 16A framework ("claims regarding returns or performance") targets, along with general fraud rules. The SEBI (PFUTP) Regulations, 2003 prohibit misleading statements inducing dealing in securities; this is cited from memory and is **NOT VERIFIED** for exact clause.

### 2.9 Data licensing (exchange and NAV data)

- **NSE market data.** All NSE market data is licensed IP. NSE's **Data Usage and Data Sharing Policy** and **Non-Display Usage Policy** require written consent from NSE Data & Analytics for **providing EOD/previous-day data to vendors' clients**, and a separate agreement and fees for **external redistribution of derived data**. **[P]** for the policy documents' existence and summary:
  - <https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_Data_Sharing&Usage_Policy.pdf>
  - <https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Non_Display_Policy.pdf>
  - Detailed clause reading was not done.
- **AMFI NAV data.** AMFI publishes it publicly (`NAVAll.txt`). AMFI's website terms on reuse or redistribution have **NOT been reviewed** (NOT VERIFIED). Third-party mirrors such as mfapi.in are not official, and their terms and licensing provenance are unknown.
- **RBI data** (DBIE and others): RBI website terms were not reviewed (NOT VERIFIED).
- **Implication:**
  - **Personal use** of public data is low risk.
  - **Public redistribution** of exchange prices (even EOD), or of derived indicators computed from them, can require an exchange licence.
  - Scraping in breach of site terms is a contract and IT-law risk regardless of SEBI.
  - Record the licence and terms for every source in the data registry.

---

## 3. Feature-by-feature regulatory classification

Risk levels: **Low** = no plausible trigger on our reading. **Med** = plausible trigger depending on facts; needs design controls and review. **High** = likely regulated activity; do not ship without registration or legal sign-off. Columns (a)/(b)/(c) = (a) personal self-use, (b) free public distribution, (c) paid service.

| # | Feature | Potential regulated activity | (a) | (b) | (c) | Design control | Pro review? |
|---|---|---|---|---|---|---|---|
| F1 | Ingest AMFI NAVs / RBI data | Data licensing / site terms; exchange redistribution if prices are re-published | Low | Med | Med–High | Source registry records licence/terms; no redistribution of raw exchange data; show source and as-of date | Y for (b)/(c) |
| F2 | Historical return, risk, and drawdown calculators | Performance presentation (MF ad code as a standard); misleading-claims risk | Low | Low–Med | Med | SEBI-style standard periods (1/3/5y/SI CAGR, ₹10k P2P); direct/regular label; as-of date; past-performance line | N for (a); Y for (c) |
| F3 | After-tax outcome calculator | Tax advice is not SEBI-regulated, but it is part of "financial planning" inside the IA definition when combined with product advice | Low | Med | Med–High | Show the tax rules and dates used; label the result "illustration under stated assumptions"; no product recommendation attached | Y for (b)/(c); also a CA view |
| F4 | Screen/filter by user-stated constraints | Can become "investment advice" if output is personalised and presented as what to buy | Low | Med | **High** | Mechanical filter only; show the user's own criteria verbatim; never label output "recommended", "best", "pick" | Y for (b)/(c) |
| F5 | Rank/score options (composite score) | Personalised ranking of specific securities or schemes is the core IA trigger; a public "top-N" is RA-like | Low | **High** | **High** | User sets weights; default weights are neutral and disclosed; ranking says "ordered by your weights"; no "#1 buy"; no public leaderboard of named securities | **Y** |
| F6 | Scenario / Monte-Carlo / projections | Forward-looking return claims; "assured" or "expected" language | Low | Med | Med–High | Scenarios are user-input assumptions; always show ranges; label each "hypothetical"; never a single "expected return" headline | Y for (b)/(c) |
| F7 | Explanation / narrative layer (deterministic templates) | Wording can turn a filter into a recommendation | Low | Med | High | Compliance Guard copy rules (§7); template-only text; explanations describe *how* and never *what to do* | Y for (b)/(c) |
| F8 | Goal/portfolio planning ("allocate X% to equity") | **Financial planning is expressly part of investment advice** (Reg. 2(1)(l)) | Low | **High** | **High** | v1: personal only. If ever distributed, reduce to calculators the user drives, or operate under an RIA | **Y** |
| F9 | Optional AI/LLM explanation (future) | IA Reg. 18(9) / RA Reg. 19(vii) AI disclosure; SEBI AI/ML guidelines (pending) | Low | Med | High | Off by default; AI never generates rankings or recommendations; visible "AI-generated text" label; deterministic result shown alongside | Y |
| F10 | Educational content naming securities with recent prices | Jan-2025/May-2026 educational price-lag rules (if associated with REs); RA public-media rules | Low | Med–High | High | Education mode uses lagged data (≥ 30 days per [S]; configurable, default 3 months until verified) with no forward-looking statements | Y |
| F11 | "Invest now" / deep link to AMC, broker, or EOP | MF distribution (ARN), EOP registration, referral = association with REs | Med | **High** | **High** | **Not built.** Hard-blocked by guardrail G1 | Y before ever considered |
| F12 | Order placement / broker API / bond purchase | Stock broker / OBPP / EOP registration | High | High | High | **Out of scope permanently for v1.** No broker SDKs in the dependency tree | Y |
| F13 | Storing user holdings, income, goals | DPDP Act (Data Fiduciary) for any user other than the operator | Low (s.3(c)(i)) | High | High | Local-only storage; encryption at rest; no telemetry; multi-user needs a DPDP programme before launch | Y for (b)/(c) |
| F14 | Export/share report (PDF/CSV) | Sharing a personalised report with another person can be advice to that person; data redistribution | Low | Med | High | Watermark: "personal research, not advice, prepared by and for the user"; strip raw exchange data; include data dates | Y for (b)/(c) |
| F15 | Alerts ("NAV crossed X", "rebalance now") | Timing signals are close to recommendations or trading calls | Low | Med–High | High | Alerts are threshold notifications on the user's own rules; wording "your rule X triggered"; never "buy/sell now" | Y for (b)/(c) |

**Summary.** In mode (a), personal self-use, no feature as designed appears to trigger SEBI registration on our reading. The main residual risks are data-licence terms and wording discipline. In modes (b) and (c), features F4, F5, F8, F11, and F12 are the ones most likely to amount to investment advice, research, or distribution. Note that "free" does not end the analysis: consideration can be indirect (ads, data, lead generation), and "holding out" does not require a fee.

---

## 4. Disclaimers do not cure regulated activity

**A disclaimer does not change the nature of an activity.** Suppose a feature in substance gives personalised advice on securities to another person, for direct or indirect consideration, or publishes recommendations or ratings on named securities. Words like "for educational purposes only", "not investment advice", or "do your own research" do not make that activity unregulated. SEBI's Jan-2025 association circular reflects this: its education carve-out depends on *what the content does* (no advice, no performance claims, lagged prices), not on labels. **[S]**

IIP uses disclaimers only to **inform the user accurately**. They are never a compliance strategy. Controls must live in the **design**: what the system can compute, say, and send, and to whom.

---

## 5. Guardrails the product must implement

Each guardrail is intended to be enforced in code and tests, not only in documentation.

| ID | Guardrail | Enforcement idea |
|---|---|---|
| G1 | **No execution, no transaction facilitation.** No order placement, broker/RTA/AMC transaction APIs, "invest now" links, or referral/affiliate links | Dependency allowlist; CI check banning broker SDK packages and affiliate URL patterns; Compliance Guard blocks "invest now"/"buy now" CTAs |
| G2 | **No buy/sell/hold calls on specific securities to anyone other than the operator.** Outputs are filters and calculations, never directives | Output schema has no `recommendation` field; copy rules (§7); a sharing/export path requires the "personal research" watermark |
| G3 | **Ranking = mechanical filter of the user's own stated constraints.** Show the criteria and weights used, verbatim, next to every ranked list. Default weights are disclosed and neutral. No hidden editorial adjustments | Every ranking result object carries `criteria[]`, `weights[]`, `asOf`, `universe`; UI test asserts they render |
| G4 | **No guaranteed, assured, or risk-free language; no single-point forecasts.** Projections show ranges and are labelled hypothetical | Compliance Guard banned-phrase list; projection components require `low/high` bands |
| G5 | **Show data provenance and dates everywhere.** Source, NAV/price as-of date, computation date, plan type (direct/regular) | Render-time assertion: any number derived from market data must have `source` + `asOf` or the component throws |
| G6 | **SEBI-style performance presentation as house style.** 1/3/5y and since-inception CAGR; ₹10,000 point-to-point; month-end basis option; "Past performance may or may not be sustained in future and is not a guarantee of future returns" adjacent to returns; no returns for schemes < 6 months old | Shared `PerformanceTable` component; unit tests on period computation |
| G7 | **Separate education from personalised output.** "Education" views use generic examples or lagged data (configurable lag; default 3 months until the May-2026 30-day figure is verified from the PDF) and carry no forward-looking statements. "Personal analysis" views are clearly marked as the user's own private analysis | Two route groups with distinct banners; lag enforced in the data access layer for education routes |
| G8 | **AI-use disclosure (future-proofing).** If any AI/LLM text is introduced: labelled "AI-generated"; never the source of rankings, scores, or recommendations; deterministic result always shown; user remains the decision-maker | Feature flag off by default; provenance tag on every text block (`template` vs `ai`) |
| G9 | **Single-user enforcement in v1.** Bind to `127.0.0.1`; no account system; no public share links | Startup check refuses non-loopback bind unless an explicit, documented override is set |
| G10 | **Data-licence registry.** Each source records licence/terms URL, permitted use, redistribution allowed (Y/N), last reviewed | Ingestion refuses a source with no registry entry; export strips sources with `redistribution=N` |
| G11 | **Plan-type honesty.** Always distinguish direct vs regular plans; never imply one is "better" without showing the expense difference that drives it | Data model requires `planType`; copy rules |
| G12 | **Tax outputs are illustrations.** Show the rule set and effective dates used; flag when a rule is user-overridden | Tax engine returns `ruleSetVersion` + `effectiveFrom` rendered with every result |
| G13 | **Audit trail.** Each analysis records inputs, data snapshot IDs, code version, and output, so any result can be reproduced and explained | Append-only local log; deterministic replay test |

---

## 6. DPDP posture

| Mode | Posture |
|---|---|
| (a) Personal self-use, localhost (v1) | Very likely outside the DPDP Act under **s.3(c)(i)**, personal or domestic purpose. Still: data stays local; encryption at rest for holdings and income data; no telemetry or third-party analytics; no cloud sync by default; secrets in the OS keychain/env, not the repo |
| (b)/(c) Any other user | Operator = **Data Fiduciary**. Before launch: privacy notice in the DPDP-Rules format; consent capture and withdrawal; purpose limitation; data minimisation (avoid PAN and account numbers entirely if possible); reasonable security safeguards (Rule-level controls: encryption, access control, logging, one-year log retention per Rules, **NOT VERIFIED**); breach notification to the Board and affected users; erasure on request or when the purpose ends; grievance officer contact; processor contracts. The main obligations are enforceable from **about 13/14-May-2027**, but build to them from day one. Children's data: avoid, because verifiable parental consent rules apply |

---

## 7. Copy rules for the Compliance Guard (deterministic)

**Matching:** case-insensitive, on word boundaries; applied to every user-facing string (UI templates, explanation templates, exports, alerts). Two tiers:
- **BLOCK**: build or render fails;
- **WARN**: requires an allowlisted context, for example inside a quoted user criterion or a regulatory disclaimer.

### BLOCK: banned phrases and patterns

| Category | Phrases / regex |
|---|---|
| Guarantees | `guarantee(d\|s)?`, `assured return(s)?`, `sure[- ]shot`, `certain return(s)?`, `fixed return(s)?` (for market-linked products), `capital protection` / `capital protected` (unless the product's legal name contains it), `no[- ]loss`, `can(not\|'t) lose`, `zero risk` |
| Risk denial | `risk[- ]free`, `safe investment`, `100% safe`, `totally safe`, `no risk`, `without risk` |
| Superlatives / endorsement | `best (fund\|stock\|scheme\|investment\|pick)s?`, `top pick(s)?`, `must[- ]buy`, `must[- ]have`, `winner(s)?`, `star (fund\|stock)`, `hot (stock\|tip\|fund)` |
| Directives | `you should (buy\|sell\|invest\|switch\|exit\|hold)`, `(buy\|sell\|switch\|exit) now`, `invest now`, `book profit(s)?`, `recommended (fund\|stock\|for you)`, `we recommend`, `our recommendation`, `strong buy`, `strong sell`, `accumulate`, `target price`, `stop[- ]?loss` (as advice) |
| Forecast certainty | `will (return\|give\|earn\|double\|grow)`, `expected to (return\|double)`, `will beat`, `double your money`, `multibagger`, `(\d+)% returns? (assured\|guaranteed\|p\.a\. guaranteed)` |
| Urgency / FOMO | `don't miss`, `last chance`, `limited time`, `before it's too late`, `act now` |
| Status claims | `SEBI[- ]approved`, `SEBI[- ]registered`, `SEBI[- ]certified`, `AMFI[- ]approved`, `RBI[- ]approved`, `government[- ]backed` (unless literally true of the instrument, e.g. a G-Sec, and sourced) |
| Advisory self-description | `investment advi(ce\|ser\|sor)` used to describe IIP's own output, `financial advi(ce\|sor)`, `research analyst`, `portfolio manager`, `wealth manager` |

### WARN: allowed only with context

`outperform(ed)?`, `beat(s)? the (index|benchmark)` (allowed only as a historical statement with period + as-of date), `top N` / `rank #` (allowed only when the user's criteria are rendered alongside, G3), `low risk` (allowed only as a computed category with the metric shown, e.g. "lowest 3y std-dev in your filtered set"), `projected` / `estimated` (allowed only with range + "hypothetical"), `tax[- ]free` (allowed only citing the specific section and as-of date).

### REQUIRED: phrases that must appear

- Any past-return display: "Past performance may or may not be sustained in future and is not a guarantee of future returns."
- Any ranking: "Ordered by the criteria and weights you set" plus the criteria list.
- Any projection: "Hypothetical illustration based on your assumptions; not a forecast."
- Any market-derived number: source + as-of date.
- Footer, all views: "Personal research tool. Not investment advice. Not registered with SEBI as an Investment Adviser or Research Analyst." (Informational only; see §4.)

---

## 8. Things we must NOT claim

1. That IIP is SEBI-registered, SEBI-approved, AMFI-approved, or endorsed by any regulator, exchange, or AMC.
2. That IIP gives investment advice, research, recommendations, ratings, or "picks", or that it is an adviser, robo-adviser, or research analyst.
3. That any return is guaranteed, assured, fixed, protected, or risk-free (for market-linked products).
4. That a fund or security is "the best", "a must-buy", or "right for you".
5. That projections or scenarios are forecasts or expected outcomes.
6. That past performance indicates future results.
7. That IIP's outputs are suitable for anyone other than the user who set the criteria.
8. That a disclaimer makes any feature compliant.
9. That data is real-time, official, or error-free. Always state source and as-of date; AMFI/RBI data are reproduced as published, with no warranty.
10. That tax calculations are tax advice or reflect the user's final liability.
11. That AI or "intelligence" in the product name means automated decision-making. v1 is deterministic; say so.
12. That IIP is "DPDP-compliant" or "secure/bank-grade" without an assessment backing the claim.
13. That IIP is "compliant with SEBI regulations". The accurate statement is "designed to stay outside regulated activities for personal use; not reviewed by a regulator".

---

## 9. Open questions for a SEBI-registered professional / securities lawyer

1. **Free public tool.** If IIP were offered free, with no ads and no data monetisation, to the public as software the user drives (user-set criteria, mechanical filters), is that "investment advice ... for consideration ... to clients"? Does "holding out" or indirect consideration (lead generation, future upsell) change the answer?
2. **Public-media proviso.** Does the "widely available to the public ... electronic medium" proviso (Reg. 2(1)(l)) cover **interactive, personalised** software output? Or is it limited to broadcast-style content identical for all recipients? What does the Nov-2025 amendment change, if anything? (Content NOT VERIFIED.)
3. **Default weights.** Where is the line between a "mechanical filter of user constraints" and "advice", once the tool supplies default weights, default universes, or category labels such as "conservative"?
4. **Financial planning.** Do goal-based calculators (corpus needed, SIP required) amount to "financial planning" under the IA definition when no product is named? And when they are?
5. **Research reports.** Is a publicly shared ranked list of named MF schemes, computed mechanically from public NAVs, a "research report" under the amended RA Regs (exact current definition NOT VERIFIED)?
6. **Price-data lag.** Confirm the **May-2026 circular** (HO/47/17/12(11)2025-MRD-POD3/I/11107/2026): exact lag (30 days?), effective date (01-Jul-2026?), whether it covers MF NAVs or only exchange-traded securities, and whether it applies to an unregistered tool-maker who is not associated with any regulated entity.
7. **Paid service route.** Which is the cleanest structure: RIA (individual, part-time, or non-individual), RA, or white-label to an existing RIA/RA under its registration and AI-disclosure duties? What does Reg. 18(9)/RA Reg. 19(vii) AI disclosure require if the only "AI" is an optional LLM explanation layer?
8. **Data licensing.** Do AMFI's website terms permit redistribution of NAV history and derived metrics in a public app? What NSE/BSE licence would be needed to display EOD prices of ETFs or stocks publicly, including NSE's derived-data terms?
9. **DPDP.** For a hosted multi-user version, is the operator a Significant Data Fiduciary risk at any plausible scale? Is there any sectoral overlap (SEBI CSCRF does not apply to unregistered entities, but would it if registered)?
10. **Final AI/ML guidelines.** Once SEBI issues the final AI/ML guidelines (pending as of 15-Oct-2026 per [S]), do any obligations reach unregistered software vendors who supply tools to registered IAs/RAs?

---

## 10. Sources

Primary (sebi.gov.in, AMFI, NSE), opened or confirmed to exist:
- SEBI (Investment Advisers) Regulations, 2013, original Gazette: <https://www.sebi.gov.in/sebi_data/attachdocs/1358779330956.pdf>
- SEBI FAQs on Registered Investment Advisers (Aug 2025): <https://www.sebi.gov.in/sebi_data/faqfiles/aug-2025/1755174193178.pdf>. Text extracted; Q4, Q10–11, Q16, Q19, Q28 used.
- SEBI circular "Norms for sharing and usage of price data for educational purposes", 08-May-2026 (body not extracted): <https://www.sebi.gov.in/legal/circulars/may-2026/norms-for-sharing-and-usage-of-price-data-for-educational-purposes_101293.html>
- SEBI IA Master Circular 27-Jun-2025 (linked from the FAQ): <https://www.sebi.gov.in/legal/master-circulars/jun-2025/master-circular-forinvestment-advisers_94821.html>
- SEBI Guidelines for Advertisement by Mutual Funds (historic): <https://www.sebi.gov.in/sebi_data/commondocs/cirmf42000_h.html>
- AMFI EOP guidelines: <https://www.amfiindia.com/eops/amfi-guidelines>
- AMFI best-practice circular 109 (01-Nov-2023): <https://www.amfiindia.com/Themes/Theme1/downloads/circulars/SEBI/CU148-AMFI%20BP%20cir%20109%20dt.%2001-Nov-23.pdf>
- NSE Data Usage & Sharing Policy: <https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_Data_Sharing&Usage_Policy.pdf>; NSE Non-Display Usage Policy: <https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Non_Display_Policy.pdf>

Secondary (used where primary text was not extracted):
- IA/RA Dec-2024 amendments and Jan-2025 guidelines: <https://taxguru.in/sebi/sebi-investment-advisers-second-amendment-regulations-2024.html>, <https://www.azbpartners.com/bank/overhaul-of-the-regulatory-framework-for-investment-advisers-and-research-analysts/>, <https://www.taxmann.com/post/blog/sebi-mandates-ias-and-ras-to-disclose-use-of-ai-tools-in-providing-investment-advice-research-services-to-clients/>, <https://taxguru.in/sebi/sebi-research-analysts-third-amendment-regulations-2024.html>
- Association/finfluencer circular 29-Jan-2025: <https://nsdl.co.in/downloadables/pdf/2025-0016-Policy-SEBI_circular-Details_clarifications_on_provisions_related_to_association_of_persons_regulated_by_the_Board_MIIs_and_their_agents_with_persons_engaged_in_prohibited_activities.pdf>, <https://www.legal500.com/developments/thought-leadership/securities-law-update-sebi-imposes-restrictions-on-intermediaries-and-finfluencers/>, <https://www.business-standard.com/markets/news/sebi-finfluencer-circular-live-stock-data-market-education-rules-125013000571_1.html>
- 30-day lag (May-2026): <https://www.livelawbiz.com/securities-law/sebi/securities-and-exchange-board-of-india-revises-norms-sharing-and-usage-market-price-data-educational-purposes-533509>, <https://www.corplawupdates.in/updates/sebi-30-day-lag-educational-price-data-norms-2026>
- EOP framework (2023/86): <https://www.azbpartners.com/bank/sebi-introduces-comprehensive-framework-on-execution-only-platforms-for-transactions-in-direct-plans-of-mf-schemes/>
- SEBI AI/ML consultation (20-Jun-2025): <https://indiacorplaw.in/2025/07/16/from-algorithms-to-accountability-analysing-sebis-ai-ml-governance-framework/>, <https://taxguru.in/sebi/sebi-proposes-guidelines-responsible-usage-ai-ml-indian-securities-markets.html>
- MF advertisement code (Master Circular extract): <https://files.hdfcfund.com/s3fs-public/2025-07/SEBI's%20Master%20Circular%20on%20Advertisements%20for%20Mutual%20Funds.pdf>
- DPDP Act s.3: <https://indiankanoon.org/doc/84660522/>; DPDP Rules 2025 phasing: <https://www.legal500.com/intelligence/india/privacy/india's-digital-personal-data-protection-act-and-the-dpdp-rules-2025-phased-commencement-core-obligations-and-a-board-ready-compliance-strategy>, <https://www.mondaq.com/india/data-protection/1775140/from-draft-to-reality-key-changes-in-indias-dpdp-rules-2025>

**Verification backlog** (to clear before any non-personal release):
- read the May-2026 circular PDF;
- read the consolidated IA Regs (last amended 25-Nov-2025) and RA Regs on sebi.gov.in;
- read the Jan-2025 association circular on sebi.gov.in;
- read the DPDP Rules Gazette G.S.R. 846(E);
- read AMFI and RBI website terms of use;
- read the SEBI MF Master Circular advertisement chapter on sebi.gov.in;
- confirm OBPP and Stock Brokers Regulations status.
