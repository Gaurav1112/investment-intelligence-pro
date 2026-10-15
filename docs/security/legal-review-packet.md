# Legal / Regulatory Review Packet: Investment Intelligence Pro

| Field | Value |
|---|---|
| Prepared | 2026-10-15 |
| For | A SEBI-registered Investment Adviser / Research Analyst compliance professional, or an Indian securities lawyer |
| Built from | `docs/security/regulatory-readiness.md` (research draft v1) and `docs/data/source-registry.md` |
| Asked of the reviewer | Answer questions Q1-Q10 and D1-D6 in section 6, and state which changes (if any) would need registration, a licence or other steps |

> This packet describes the software and lists questions. **It contains no legal conclusions.** Where it says how the
> team reads a provision, that is an engineering reading recorded so the reviewer can correct it. Citation status:
> **[P]** text read on the official site; **[S]** secondary sources only; **NOT VERIFIED** where neither was done.

---

## 1. Current scope (as of 15-Oct-2026)

- **Personal and local.** One user (the developer), on the developer's own computer. The server binds to `127.0.0.1`
  only and refuses a non-loopback bind unless an explicit override setting is used; it has no account system or share links.
- **No money flows.** No fees, no advertising, no commissions, no referral or affiliate links, no data monetisation.
- **No execution.** No orders, no broker/RTA/AMC/bank APIs, no "invest now" links. No broker SDKs in the dependencies.
- **No publication.** Outputs are not published, shared, or sent to anyone.
- **Deterministic.** No LLM or other AI decides anything. An optional LLM "rephrase" hook exists in code but has no
  provider and is off.
- **Data stays local.** Holdings and income are stored in a local SQLite file (not encrypted at rest in v1); no telemetry.

Any of the following would change the picture and would be reviewed **before** shipping: a second user, a public URL or
hosting, any payment or monetisation, publishing outputs, white-labelling for an adviser or distributor, transaction
links, or displaying exchange price feeds.

## 2. Exact features

| # | Feature (as built) | What the user supplies | What the app outputs |
|---|---|---|---|
| F1 | Data ingestion: AMFI NAVAll (latest NAV), AMFI NAV history (held schemes, small windows), AMFI scheme master; manual entry of RBI T-bill cut-offs and bank FD rates with a citation | Optional: a T-bill press-release URL; FD terms | Stored data with source, URL and as-of date |
| F2 | Historical return, risk and drawdown calculators (CAGR, XIRR, volatility, drawdown) | Scheme, dates | Figures with source, date and formula |
| F3 | After-tax outcome calculator (Indian tax rule table, CA review pending: `docs/finance/ca-review-packet.md`) | Optional slab/surcharge band | After-tax ranges, labelled "illustration under stated assumptions" |
| F4/F5 | **Discovery**: filters options (MFs, T-bills, FDs) by the user's own amount, withdrawal date and constraints, groups them into certainty tiers (T1 sovereign contract to T4 market risk), and orders them by the user's chosen objective. No composite score; "No suitable candidate found" is a valid result | Amount, date, objective, constraints | An ordered list with the criteria shown verbatim; never labelled "recommended", "best" or "pick" |
| F6 | Scenarios and historical-window ranges ("k of N windows"); simulator | Assumptions | Ranges labelled hypothetical; no single "expected return" |
| F7 | Explanations from deterministic templates, checked by a "Compliance Guard" (banned phrases, required disclosures) | — | Text describing how a figure was computed |
| F13 | Portfolio import (CSV/XLSX), watchlist | Own holdings | Local storage only |
| F14 | Export (CSV/report) | — | Watermarked "personal research, not advice, prepared by and for the user" |
| F15 | Alerts | Own thresholds | "Your rule X triggered"; never "buy/sell now" |

Not built: goal/financial-planning allocation (F8), AI explanations (F9), educational content with named securities
(F10), transaction links (F11), order placement (F12).

## 3. Guardrails in code today

G1 no execution or transaction links · G2 no buy/sell/hold calls to anyone else · G3 ranking shows the user's own
criteria and weights · G4 no guaranteed/assured/risk-free language, ranges not points · G5 source and as-of date on every
market number · G6 SEBI-style performance presentation as house style · G9 single-user loopback-only · G10 data-licence
registry · G12 tax outputs show the rule set version and dates · G13 audit trail (inputs, data snapshot, output hashes).
Full table: `docs/security/regulatory-readiness.md` §5.

## 4. Questions on securities regulation (Q1-Q10)

| # | Question | Relevant provision (citation status) | What the app does today |
|---|---|---|---|
| Q1 | **Free public tool.** If offered free (no ads, no data monetisation) as software the user drives, is it "investment advice … for consideration … to clients"? Do "holding out", lead generation or future upsell count as consideration? | SEBI (Investment Advisers) Regulations 2013, Reg. 2(1)(l) "investment advice" and 2(1)(m) "investment adviser" ("for consideration … includes any person who holds out himself") **[P]** 2013 Gazette text <https://www.sebi.gov.in/sebi_data/attachdocs/1358779330956.pdf>; amended by SEBI/LAD-NRO/GN/2024/219 (Dec-2024) **[S]** | Not offered to anyone; single user, loopback only |
| Q2 | **Public-media proviso.** Does "widely available to the public … electronic … medium" cover **interactive, personalised** software output, or only broadcast-style content identical for everyone? What did the Nov-2025 amendment change? | Reg. 2(1)(l) proviso **[P]** (2013 Gazette); SEBI IA FAQ Aug-2025 **[P]** <https://www.sebi.gov.in/sebi_data/faqfiles/aug-2025/1755174193178.pdf>; Nov-2025 amendment content **NOT VERIFIED** | Output is personalised to the user's inputs; the team does not rely on the proviso |
| Q3 | **Default weights.** Where does a "mechanical filter of user constraints" become "advice" once the tool supplies default weights, default universes or labels like "conservative"? | Reg. 2(1)(l) **[P]**; IA FAQ **[P]** | No composite score. Ordering is by the user-chosen objective; tiers are fixed by instrument type (sovereign contract → market risk); defaults are disclosed on the Methodology page |
| Q4 | **Financial planning.** Do goal calculators (corpus needed, SIP required) amount to "financial planning" within the IA definition when no product is named? When one is? | Reg. 2(1)(l) "shall include financial planning" **[P]** | Goal planning not built. Discovery names instruments for the user's own amount and date |
| Q5 | **Research report.** Is a publicly shared ranked list of named MF schemes, computed mechanically from public NAVs, a "research report" under the amended RA Regulations? | SEBI (Research Analysts) Regulations 2014 as amended by SEBI/LAD-NRO/GN/2024/220 (16-Dec-2024) **[S]**; current definition **NOT VERIFIED** | Nothing is shared or published |
| Q6 | **Price-data lag.** Confirm the 08-May-2026 circular: the lag (30 days?), effective date (01-Jul-2026?), whether it covers MF NAVs, and whether it reaches an unregistered tool-maker not associated with any regulated entity | Circular HO/47/17/12(11)2025-MRD-POD3/I/11107/2026, 08-May-2026: existence **[P]** <https://www.sebi.gov.in/legal/circulars/may-2026/norms-for-sharing-and-usage-of-price-data-for-educational-purposes_101293.html>, content **[S]**; Jan-2025 association circular SEBI/HO/MIRSD/MIRSD-PoD-1/P/CIR/2025/11 **[S]**; Intermediaries Regs Reg. 16A **[S]** | No education mode exists. Personal views use current data |
| Q7 | **Paid route.** Cleanest structure: RIA (individual, part-time, non-individual), RA, or white-label under an existing RIA/RA? What does AI disclosure require if the only AI is an optional explanation layer? | IA Regs Reg. 18(9) and RA Regs Reg. 19(vii), Reg. 24(7) (AI disclosure/responsibility) **[S]**; circular SEBI/HO/MIRSD/MIRSD-PoD-1/P/CIR/2025/003, 08-Jan-2025 **[S]** | No paid service. No AI in use |
| Q8 | **Data licensing.** (Detailed in section 5.) May NAV history and derived metrics be shown publicly? What NSE/BSE licence would public EOD prices need? | AMFI Terms of Use; NSE Data Usage & Sharing Policy and Non-Display Policy **[P]** (existence/summary) | Personal use only; no exchange prices ingested |
| Q9 | **DPDP.** For a hosted multi-user version: Significant Data Fiduciary risk at plausible scale? Any sectoral overlap (e.g. SEBI CSCRF) if the operator were later registered? | DPDP Act 2023 s.3(c)(i) personal/domestic exemption **[S]**; DPDP Rules 2025, G.S.R. 846(E), 13-Nov-2025 **[S]**, substantive duties from about 13/14-May-2027 **[S]** | Single user; local storage (not encrypted at rest in v1); no telemetry |
| Q10 | **AI/ML guidelines.** Once SEBI issues final AI/ML guidelines, do any obligations reach unregistered vendors supplying tools to registered IAs/RAs? | SEBI consultation paper 20-Jun-2025 **[S]**; final guidelines pending as of 15-Oct-2026 **[S]** | Deterministic; no AI in the decision path |

## 5. Data-licence questions

| # | Source | Terms as recorded (status) | What the app does today | Question |
|---|---|---|---|---|
| D1 | AMFI NAVAll, NAV history, scheme master, TER | AMFI Terms of Use: "personal and non-commercial use only"; prohibits storing a "significant portion" (recorded in the source registry; full clause reading NOT VERIFIED) | Live adapters, personal use; NAV history only for held/watched schemes in small windows; untracked schemes keep only the latest NAV | Is the current local storage within "personal and non-commercial use"? Would any multi-user or public version need AMFI's written permission? Does showing derived metrics (returns, volatility) count as redistribution? |
| D2 | mfapi.in (unofficial AMFI mirror) | No terms page; AMFI terms still apply upstream | Off by default; cross-check only | Any exposure from using an unofficial mirror at all? |
| D3 | RBI website (home rates, T-bill press releases, DBIE) | RBI disclaimer prohibits "caching" and framing without permission | Manual entry with citation; single-page user-triggered fetch of one press release | Is a user-triggered single fetch of a press release, stored as a dated figure, "caching"? |
| D4 | NSE / BSE | NSE ToU bans "systematic or automated data collection activities (including scraping…)"; BSE prohibits "reproduction, redistribution or transmission" | Blocked; holidays curated by hand | What licence would display of EOD ETF or bond prices need, for personal use and for a public version (incl. NSE derived-data terms)? |
| D5 | FBIL, CCIL | FBIL: fee-liable, redistribution licence required. CCIL: non-commercial use allowed, "discouraged from extracting"; commercial use needs a Data Agreement | Blocked / manual | Confirm a manual, personal reference to a published CCIL figure is acceptable |
| D6 | Credit rating agencies | CRISIL: no copying or redistribution without written consent; others NOT VERIFIED | Manual entry of a rating plus a link by the user | Is a user-entered rating, stored locally with a link, a "reproduction"? |

## 6. Answers (to be filled in by the reviewer)

| Item | Answer / opinion | Conditions or changes required | Reference relied on |
|---|---|---|---|
| Q1 | | | |
| Q2 | | | |
| Q3 | | | |
| Q4 | | | |
| Q5 | | | |
| Q6 | | | |
| Q7 | | | |
| Q8 | | | |
| Q9 | | | |
| Q10 | | | |
| D1 | | | |
| D2 | | | |
| D3 | | | |
| D4 | | | |
| D5 | | | |
| D6 | | | |
| Anything in the current personal, local use that needs to change now? | | | |

| Reviewer | |
|---|---|
| Name, registration / enrolment no. | |
| Firm | |
| Date | |
| Scope of review (documents seen) | |
