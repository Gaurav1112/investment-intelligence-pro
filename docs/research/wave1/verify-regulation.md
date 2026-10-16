# Verification: wave-1 "regulation" research report

| Field | Value |
|---|---|
| Report checked | `docs/research/wave1/research-regulation.md` |
| Verifier role | Adversarial skeptic (independent re-check of primary texts) |
| Date | 2026-10-15 (all sources accessed 2026-10-15) |
| Method | Every cited SEBI/NSE PDF was downloaded again and its text extracted with `pdftotext`. The Kite terms page and the NSE Terms of Use page were fetched over HTTP and searched. Zerodha FAQ, Vercel docs, Indian Kanoon and news sources were fetched with WebFetch. Nothing was taken from the report without being re-read in the source. |
| Status | Research, not legal advice |

**ID note.** The finding IDs below follow the orchestrator's list (R1–R15). They do **not** match the report's own §9 table. For example, the report's R5 is "consideration", and the orchestrator's R5 is the algo framework.

---

## 1. Verdict summary

| ID | Claim (short) | Verdict | Main reason |
|---|---|---|---|
| R1 | RA definitions | **CONFIRMED** | Verbatim in the consolidated RA Regs |
| R2 | Trading calls = non-personalised; excluded from IA advice | **CONFIRMED** (one side remark overstated) | Verbatim. But the report's §1 line "IAs are barred from it" has no support in the IA Regs text |
| R3 | Methodology-agnostic (FAQ 5) | **CONFIRMED** | Verbatim |
| R4 | RA Reg 21(2), "any person", public media | **CONFIRMED** (text) | Verbatim. Whether it can be enforced against a non-registrant is untested |
| R5 | Retail algo: ≤10 OPS no registration, static IP, family, 01-Apr-2026 | **WEAKENED** | Dates and static-IP rules are verbatim. "No registration" conflicts with NSE B.3 as printed. The hosting rule (I.h) is unknown |
| R6 | Hosted auto-orders BLOCKED (Vercel) | **CONFIRMED and strengthened** | Vercel docs read directly. The static IPs are **shared** between customers, so paying for them would still not meet NSE's one-client-per-IP rule |
| R7 | Black-box → RA; providers empanelled | **CONFIRMED** | Verbatim (paras III(a), V) |
| R8 | 30-day education lag from 01-Jul-2026 | **CONFIRMED** (with an inconsistency inside SEBI's own documents) | Lag circular para 7 says 01-Jul-2026. The updated association circular footnote says "with effect from May 8, 2026" |
| R9 | Association rules, IT-systems interaction, own account fine | **CONFIRMED** | FAQ 4, 5, 9 verbatim |
| R10 | NSE data ownership, redistribution, index licence | **WEAKENED** | Text is verbatim. But the policy binds Trading Members, Subsidiaries and Subscribers through "Relevant Agreements", not individuals directly. The index clause is limited to those parties |
| R11 | Non-display policy; applicability unclear | **CONFIRMED** (as stated) | Text verbatim. "NOT VERIFIED" for applicability is the right label |
| R12 | Kite: personal use OK; no public display; Personal plan has no data | **WEAKENED** | The report misreads the "build databases" clause and leaves out the "derivative work" and "virtual/mock trading" restrictions. It also labels the order-only static-IP scope as unverified when the primary broker page states it |
| R13 | NSE ToU bans automated collection | **CONFIRMED; upgrade to VERIFIED** | The page loaded this session and the clause is verbatim. The ToU also bans "simulation" use, which the report missed |
| R14 | Wording/UX rules | **WEAKENED** | Design advice, not a legal finding. By the report's own account, wording does not change legality. It also contradicts itself on exports |
| R15 | SEBI Act s.12(1); Avadhut Sathe | **WEAKENED** | s.12(1) wording confirmed on Indian Kanoon (still secondary). The Business Standard citation returns 403. "₹546 cr impounded" is out of date: SAT cut it to a ₹100 cr deposit and the Supreme Court declined to interfere |

Nothing was fully refuted. The report's quotations of primary texts are accurate. The problems are in the consequences it draws, in material it left out, and in two places where it understates what is known.

---

## 2. Finding-by-finding evidence

### R1 — RA definitions: CONFIRMED
Consolidated RA Regs, "(Amended upto November 25, 2025)", <https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1785912002778.pdf>, accessed 2026-10-15:
- 2(1)(u): "“research analyst” means a person who, for consideration, is engaged in the business of providing research services and includes a part-time research analyst;"
- 2(1)(fa): "any form of economic benefit including non-cash benefit, received or receivable, directly or indirectly, in any form whether from client or otherwise for providing research services;"
- 2(1)(wa) items i–viii, ending "with respect to securities that are listed or proposed to be listed in a stock exchange, whether or not any such person has the job title of 'research analyst' to the clients or other persons or group of persons or general public;"

Caveat the report did not raise: (wa) defines research services as services "provided by research analyst", and (u) defines a research analyst as someone providing research services. The definitions are circular, so "for consideration" plus "business" carry all the weight. That supports the report's personal-use reading, but no SEBI order tests it.

### R2 — Trading calls: CONFIRMED, with one overstatement
- RA 2(1)(zc): "intraday, ultra-short duration, non-delivery based (other than hedging) recommendation or any recommendation related to securities that are not personalized or investor specific." Verbatim.
- Consolidated IA Regs (<https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1785912187595.pdf>) 2(1)(l): "Provided further that trading calls shall not be considered as investment advice for purpose of these regulations." 2(1)(u) cross-refers to RA (zc). Verbatim.
- **Overstated:** report §1 item 3 and §3 say "IAs are barred from it". In the consolidated IA Regs, "trading call" appears only at lines 2(1)(l) and 2(1)(u). The regulation excludes trading calls from the definition of investment advice. It does **not** prohibit IAs from giving them. Any outright bar would have to come from a separate IA guidelines circular, which the report did not cite. **NOT VERIFIED.**

### R3 — Methodology-agnostic: CONFIRMED
RA FAQ circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/105, July 23, 2025, <https://www.sebi.gov.in/sebi_data/faqfiles/jul-2025/1753269723942.pdf>, FAQ 5: "agnostic to the methodology used to provide research services. Providing research services (including buy/sell/hold recommendation) on a security or securities based on any methodology (including the technical analysis) is not exempted". FAQ 7 ("cover all securities as defined under clause (h) of section 2 of the Securities Contracts (Regulation) Act") and FAQ 36 (technical chart with time stamp) are also accurate. The report paraphrases FAQ 36 as "not enough"; the FAQ answers indirectly by requiring "adequate documentary basis".

### R4 — Reg 21(2): CONFIRMED (text)
Verbatim: "If any person including a director or employee of an investment adviser or credit rating agency or asset management company or fund manager, makes public appearance or makes a recommendation or offers an opinion concerning securities or public offers through public media, all the provisions of regulations 16 and 17 shall apply mutatis mutandis to him and he shall disclose his name, registration status and details of financial interest in the subject company".
Caveat: Regs 16 and 17 deal with personal trading by RA employees and RA compensation. How they would apply "mutatis mutandis" to an unregistered private individual, and whether SEBI enforces that, is **NOT VERIFIED**. The practical rule (do not post named-security calls publicly) still stands.

### R5 — Retail algo framework: WEAKENED
Verified verbatim:
- SEBI circ SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013 (Feb 4, 2025), <https://www.sebi.gov.in/sebi_data/attachdocs/feb-2025/1738665456458.pdf>, para I(c): "shall also be registered with the Exchange, through their broker, only if they cross the specified order per second threshold … ‘Family’ for this purpose would mean self, spouse, dependent children and dependent parents." Para I(d) covers static IP, OAuth and 2FA.
- SEBI circ 2025/132 (Sep 30, 2025), <https://www.sebi.gov.in/sebi_data/attachdocs/sep-2025/1759232056254.pdf>, para 8: "W.e.f. April 01, 2026, algo framework specified in circular dated February 04, 2025 along with implementation standards and detailed operational modalities (issued by exchanges) will be applicable for all stock brokers."
- NSE/INVG/67858 (May 05, 2025), <https://nsearchives.nseindia.com/content/circulars/INVG67858.pdf>: A.1, A.5 and B.2 ("10 OPS per exchange, the client will not be required to register for algorithmic trading") are verbatim.

Why weakened:
1. **NSE B.3 as printed contradicts B.2.** Both `-layout` and `-raw` extraction give: "All such algo orders via API which are below the defined Threshold Order Per Second (TOPS), require registration with the Exchange and a generic algo ID shall be provided by the Exchange for such Algos." Whatever words are missing, below-threshold algos still receive an exchange-issued generic algo ID and must be tagged (G). "Needs no registration" is therefore too strong. The defensible version is "no algo-specific registration below the threshold, but orders run under an exchange generic algo ID and tag through the broker". The report flagged B.3 as garbled but still marked the headline VERIFIED.
2. **I.h (hosting) is unknown**: "All Retail Algorithms, including those provided by empanelled Algo providers should be hosted [gap] servers." If it means broker or exchange-approved servers, then even **local mode** automation (report §4.3, "REQUIRES CONFIGURATION") may not be lawful as described. The exchanges' operational modalities (Jul-2025) were not read. Local-mode auto-ordering should therefore be **NOT VERIFIED**, not "REQUIRES CONFIGURATION".
3. Minor: NSE A.7's family definition for static-IP sharing points to a different circular (SEBI/HO/MIRSD/MIRSD-PoD1/P/CIR/2024/169), not to the algo circular.

### R6 — Vercel hosted auto-orders: CONFIRMED and strengthened
Vercel docs, <https://vercel.com/docs/networking/static-ips> (page metadata last_updated 2026-06-30), read directly this session rather than through a search summary: "Static IPs are available on Enterprise and Pro plans"; "Static IPs are priced at $100/month per project for Pro plus Private Data Transfer". **New point:** "Static IP addresses are shared across a small group of customers in the same region." NSE A.7 says "A static IP can only be mapped to one client at a time" (sharing is allowed only within one family). A Vercel shared-pool static IP is therefore probably unusable **even on a paid plan**, not only because of the no-paid-services rule. The BLOCKED verdict stands on two independent grounds. Using a shared IP this way is our reading; no broker or NSE text that addresses cloud shared-egress IPs was found (NOT VERIFIED).

### R7 — Black box and empanelment: CONFIRMED
Feb-2025 circular para III(a): "While algo providers shall not be regulated by SEBI, for better oversight, any algo provider, providing the facility to place algo orders with Brokers through API, shall require to be empaneled with Exchanges". Para V(a)(ii) and footnote 6 (Black box) say: "Register as a Research Analyst and maintain a detailed research report for each such algo". Verbatim.

### R8 — 30-day lag: CONFIRMED, with an inconsistency inside SEBI's documents
Circular HO/47/17/12(11)2025-MRD-POD3/I/11107/2026, May 08, 2026, <https://www.sebi.gov.in/sebi_data/attachdocs/may-2026/1778242522289.pdf>: para 4 "a time lag of 30 days for both sharing and usage of price data for educational purposes"; para 7 "applicable with effect from July 01, 2026". Verbatim.
Two points the report missed:
- The updated association circular (<https://www.sebi.gov.in/sebi_data/attachdocs/jul-2026/1784884437684.pdf>), footnote 1 to FAQ 8, says: "Response modified with effect from May 8, 2026 vide SEBI Circular No HO/47/17/12(11)2025-MRD-POD3/I/11107/2026". That disagrees with para 7's 01-Jul-2026. It does not matter after 01-Jul-2026, but citing a single date as unambiguous is overstated.
- Para 6.1 also **lengthens** the MII sharing lag from **one day to thirty days**. "Supersedes the 3-month rule" is only half the change.

### R9 — Association rules: CONFIRMED
Association circular SEBI/HO/MIRSD/MIRSD-PoD-1/P/CIR/2025/11 (Jan 29, 2025, "Updated on May 8, 2026"): FAQ 4 lists the two prohibited activities; FAQ 5 "interaction of information technology systems"; FAQ 9 "There is no restriction on any person in availing the professional services … such as demat account or trading account services provided that such services/accounts are not used for any of the abovementioned two prohibited activities". Verbatim. The Reg 16A quote with "unless the person is registered…" also appears verbatim (lines 44–48 of the extracted text).
Emphasis the report understates: prohibited activity (ii), "making any claim, of returns or performance expressly or impliedly", has **no audience or consideration element**. A public post such as "my rule made X% on stock Y" could make the owner a person engaged in a prohibited activity. His own broker or AMC relationship would then depend on FAQ 9's proviso. Given the owner's LinkedIn activity, this is the most realistic way the project could cause trouble.

### R10 — NSE Data Usage & Sharing Policy: WEAKENED
<https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_Data_Sharing&Usage_Policy.pdf>: 6.1 "NSE is the sole owner of the Market Data"; 7.1(a); 7.3; 13(d) "delayed data, end of day data, historical data". Verbatim.
Why weakened:
- 7.1 restrictions are things "The Relevant Agreements shall clearly set out", and 7.1(a)/7.3 apply to "Trading Members and Subscribers" and "Trading Members, Subsidiaries and Subscribers". A "Subscriber" is "any person who has entered into the Relevant Agreement". An individual retail investor who has signed no agreement with NSE is not directly bound. Restrictions reach him only through end-user terms passed down by a vendor or broker. The report's table states "Custom composite indices built from NSE data need a separate licence" as a general rule. It is a rule for licensees.
- The PDF carries a "Confidential" footer. Whether it is meant as a binding public policy is unclear.
- Missed clause: **7.4** bars providing Market Data to anyone "engaging in online gaming, virtual trading or simulation". See omission O2.

### R11 — Non-display policy: CONFIRMED (as stated)
<https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Non_Display_Policy.pdf>: 1.3 and 3.1 are verbatim. 1.4 "Subscriber" covers "(b) Clients who subscribe to and receive the Market Data from Data Vendors of NSE Data & Analytics Ltd." Whether a broker supplying data to a client counts as a "Data Vendor" under 1.1 is not stated. NOT VERIFIED for individuals is the correct label.

### R12 — Kite Connect: WEAKENED
Kite terms <https://kite.trade/terms/> (fetched; verbatim): "personal use, where You, a Client, develops a private interface exclusively for customising personal trading and investment experience"; "live market data obtained via Kite Connect cannot be displayed to the public at large". Confirmed.
Problems:
1. **Misreading of the database clause.** The full sentence is: "you will not … do the following with content returned from the APIs. Scrape, build databases, or otherwise create permanent copies of such content, or keep cached copies with the intent of redistributing. Copy, translate, modify, create a derivative work of, sell, lease, lend, convey, distribute, publicly display, or sublicense to any third party." On a plain reading, "with the intent of redistributing" attaches to "keep cached copies". "Build databases, or otherwise create permanent copies" may be prohibited **outright**. The report's §6 table summarises it as "no permanent copies 'with the intent of redistributing'", which drops the more restrictive reading. Storing Kite historical candles in IIP's SQLite/Turso to backtest is therefore **NOT VERIFIED as permitted**, and "create a derivative work of" may reach derived signals.
2. **Missed:** "You are not permitted to use the APIs and/or live market data for virtual/mock trading apps". See O2.
3. **Understated:** the Zerodha FAQ (<https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/kite-connect-api-faqs>), which is the primary broker page, says: "You must configure a static IP address to place orders via the Kite API from 1 April 2025. All other API endpoints (WebSocket data, order book, positions, etc.) remain accessible from any IP." The report labelled the order-only scope "NOT VERIFIED on a primary broker page". It is verified for Zerodha. Read-only holdings and positions from the hosted app need no static IP.
4. "Personal (Free) … No live market data or historical data" and "₹500/month per API key" are confirmed on the FAQ page.

### R13 — NSE website ToU: CONFIRMED, upgrade to VERIFIED
<https://www.nseindia.com/static/nse-terms-of-use> was fetched successfully this session (HTTP 200, about 327 KB). Verbatim: "User is prohibited to conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting) on or in relation to our Website / Mobile Application." Also verbatim: "shall not be copied, … stored (either in hardcopy or in an electronic retrieval system) … without prior written permission of NSE."
Two clauses on the same page that the report missed and that bear on Q4 and on backtesting:
- "Unless the information or Content is available for download, not to aggregate, copy or duplicate in any manner any of the content". This partly supports manual bhavcopy download, because those files are "available for download". The broad "stored … without prior written permission" clause still applies, so storage stays **NOT VERIFIED**.
- "User … shall not, in any form and manner, use or make the data or Content available on the Website / Mobile Application, for any gaming, virtual trading or simulation activities under any circumstances whatsoever." See O2.

### R14 — Wording/UX rules: WEAKENED
These are design recommendations, not legal facts. The report says itself that "The legal line is audience, consideration and holding out, not vocabulary". The wording rules reduce the damage if output leaks; they do not make anything lawful. The task summary says "no share/export", but report §8.1.4 **allows** exports with a watermark. That inconsistency needs to be resolved. Point 8.1.6 (noindex/robots) is labelled NOT VERIFIED in the code, which is correct.

### R15 — SEBI Act s.12(1) and Avadhut Sathe: WEAKENED
- Indian Kanoon <https://indiankanoon.org/doc/507649/> (fetched): "No stock broker, sub-broker, … investment adviser and such other intermediary who may be associated with securities market shall buy, sell or deal in securities except under, and in accordance with, the conditions of a certificate of registration". It matches the report but is still a secondary copy. The direct prohibition on acting as an RA without registration is RA Reg 3(1), which is primary and verified. s.12(1) adds little.
- The Business Standard URL cited by the report returned **HTTP 403** this session, so its quotes cannot be re-checked: **NOT VERIFIED**.
- **Out of date:** the report says "the outcome of any appeal is unknown". Later sources:
  - LiveLaw (<https://www.livelawbiz.com/amp/securities-law/sat/sat-upholds-sebi-order-against-avadhut-sathe-academy-cuts-deposit-to-100-crore-520554>): SAT order dated January 23, 2026, "SEBI has made out a prima facie case of violation of IA and RA Regulations", and "the ends of justice would be met by directing a deposit of Rs 100 crore".
  - Moneylife (<https://www.moneylife.in/article/supreme-court-refuses-relief-to-avadhut-sathe-trading-academy-permits-225-crore-monthly-expenses/80028.html>, 24-Mar-2026) quotes the Supreme Court: "We are not inclined to interfere with the judgment and order passed by the SAT dated 22 January 2026". The SAT date (22 vs 23 Jan) differs between the two sources: NOT VERIFIED.
  - The lesson still holds, more strongly: the "education" defence failed at prima facie level before SAT and SC. But "₹546 cr impounded" should now read "₹546 cr impounding ordered ex parte; reduced on appeal to a ₹100 cr deposit".

---

## 3. Important omissions

- **O1. Kite "build databases" ambiguity (R12).** If the clause is read strictly, IIP may not keep a permanent Kite-sourced price history, even privately. That would remove the paid Kite option for backtest data, not just the free plan.
- **O2. "Simulation" and "virtual trading" prohibitions versus backtesting.** All three equity data channels the report discusses contain such a ban:
  - NSE ToU: "gaming, virtual trading or simulation activities under any circumstances whatsoever";
  - NSE Data Policy 7.4: "virtual trading or simulation";
  - Kite: "virtual/mock trading apps".

  The project's binding rule requires an out-of-sample backtest before any signal may exist. A historical backtest or paper-trading log could be argued to be "simulation". The terms do not define the word, so this is NOT VERIFIED either way. It is a critical licence risk for the equity-signal roadmap and should be an open question for a lawyer, alongside Q3 and Q4.
- **O3. Vercel static IPs are shared (R6).** Paying for Pro does not fix order placement from the hosted app.
- **O4. NSE I.h hosting requirement and the B.3 contradiction (R5).** Local-mode automation is not established as lawful. Reading the exchanges' Jul-2025 operational modalities is a precondition for any automation work.
- **O5. Zerodha confirms read-only endpoints work from any IP.** Read-only portfolio sync from hosted mode is possible without a static IP. The report should say this; it is a positive finding it left out.
- **O6. Return-claim exposure has no audience or consideration test (R9).** It deserves a direct guardrail: no CAGR or performance numbers on named securities in LinkedIn posts, the resume or the README. The report mentions this only in §5 and §7.
- **O7. AMFI terms were not re-read.** The report relies on the repo registry for AMFI ("personal and non-commercial use only"; "shall not store electronically any significant portion"). MF signals are the first product, and they need a stored NAV history for backtests. The "significant portion" storage clause collides directly with that, and the report does not analyse it. Re-verify the clause at <https://www.amfiindia.com/terms-of-use> and decide whether a MF NAV history store is permitted. NOT VERIFIED here.
- **O8. Mutual-fund-specific regulation is thin.** The report treats open-ended MF units as falling under the IA regime "generally", but cites no SEBI text for that. It does not cover the MF distributor and execution-only platform (EOP) rules that would apply if the app ever adds transaction or redirect links. Low risk for personal use, but unverified.
- **O9. Internal date inconsistency for the 30-day lag (R8).**

---

## 4. Net effect on the project

- **Personal-use conclusion holds:** RA/IA registration is not triggered without consideration, a business or another recipient. That rests on verified text; how it applies is still a reading, not a ruling.
- **Equity signals now have one more blocker than the report states:** the data channels' "simulation" and "build databases" clauses (O1, O2). Until a lawyer or the vendor clarifies them, equity backtesting on NSE- or Kite-sourced history should be **NOT VERIFIED (licence)**. Under the project's rule (no backtest → no signal), the engine should abstain on equity signals.
- **Hosted auto-trading stays BLOCKED** on two grounds (O3). **Local auto-trading** moves from REQUIRES CONFIGURATION to **NOT VERIFIED** until NSE I.h and the operational modalities are read (O4).

## 5. Sources (all accessed 2026-10-15)
1. SEBI RA Regs consolidated: <https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1785912002778.pdf>. "for consideration, is engaged in the business of providing research services"
2. SEBI IA Regs consolidated: <https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1785912187595.pdf>. "trading calls shall not be considered as investment advice"
3. SEBI RA FAQs 2025/105: <https://www.sebi.gov.in/sebi_data/faqfiles/jul-2025/1753269723942.pdf>. "agnostic to the methodology used"
4. SEBI algo circular 2025/0000013: <https://www.sebi.gov.in/sebi_data/attachdocs/feb-2025/1738665456458.pdf>. "only if they cross the specified order per second threshold"
5. SEBI circular 2025/132: <https://www.sebi.gov.in/sebi_data/attachdocs/sep-2025/1759232056254.pdf>. "W.e.f. April 01, 2026"
6. NSE/INVG/67858: <https://nsearchives.nseindia.com/content/circulars/INVG67858.pdf>. "A static IP can only be mapped to one client at a time"
7. SEBI association circular 2025/11 (updated 08-May-2026): <https://www.sebi.gov.in/sebi_data/attachdocs/jul-2026/1784884437684.pdf>. "Response modified with effect from May 8, 2026"
8. SEBI price-data circular 08-May-2026: <https://www.sebi.gov.in/sebi_data/attachdocs/may-2026/1778242522289.pdf>. "applicable with effect from July 01, 2026"
9. NSE Data Usage & Sharing Policy: <https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_Data_Sharing&Usage_Policy.pdf>. "virtual trading or simulation"
10. NSE Non-Display Policy: <https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Non_Display_Policy.pdf>. "Clients who subscribe to and receive the Market Data from Data Vendors"
11. NSE Terms of Use: <https://www.nseindia.com/static/nse-terms-of-use>. "gaming, virtual trading or simulation activities under any circumstances whatsoever"
12. Kite Connect terms: <https://kite.trade/terms/>. "Scrape, build databases, or otherwise create permanent copies of such content"
13. Zerodha Kite Connect FAQ: <https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/kite-connect-api-faqs>. "All other API endpoints (WebSocket data, order book, positions, etc.) remain accessible from any IP."
14. Vercel Static IPs: <https://vercel.com/docs/networking/static-ips>. "Static IP addresses are shared across a small group of customers in the same region"
15. Indian Kanoon, SEBI Act s.12(1): <https://indiankanoon.org/doc/507649/>
16. LiveLaw on SAT order: <https://www.livelawbiz.com/amp/securities-law/sat/sat-upholds-sebi-order-against-avadhut-sathe-academy-cuts-deposit-to-100-crore-520554>. "directing a deposit of Rs 100 crore"
17. Moneylife on Supreme Court: <https://www.moneylife.in/article/supreme-court-refuses-relief-to-avadhut-sathe-trading-academy-permits-225-crore-monthly-expenses/80028.html>. "We are not inclined to interfere"
18. Business Standard (cited by report): HTTP 403 this session, NOT VERIFIED.
