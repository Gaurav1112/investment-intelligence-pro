# Research: Indian regulation for a personal buy/sell signal app

| Field | Value |
|---|---|
| Wave / topic | Wave 1, "regulation" |
| Prepared | 2026-10-15 (all sources accessed 2026-10-15) |
| Scope | Investment Intelligence Pro (IIP) producing buy/sell **signals** (mutual funds and, later, listed equities) for the owner's **own** money; local mode and the single-user hosted mode on Vercel |
| Builds on | `docs/security/regulatory-readiness.md` (v1). This report **upgrades several items there from [S]/NOT VERIFIED to VERIFIED** (see §10) |
| Status | Research, not legal advice |

> **Not legal advice.** The author is an automated researcher, not a lawyer and not a SEBI-registered intermediary. Everything below is a reading of public texts. Anything that puts IIP output in front of another person (including family or a public demo) should be reviewed by an Indian securities lawyer first.

**Status labels used:** **VERIFIED** = read in the primary text in this session (text extracted from the official PDF and quoted). **NOT VERIFIED** = from secondary sources only, or not confirmed. **REQUIRES CONFIGURATION** = lawful only after a setup step the owner must make. **BLOCKED** = not permitted under the stated constraints.

---

## 1. Bottom line

1. **Personal use is outside the SEBI registration regimes on the plain text.** Both the Research Analyst (RA) and Investment Adviser (IA) definitions require a person who, **"for consideration, is engaged in the business of"** providing research services or advice **to clients / other persons / the public**. A signal engine the owner builds and uses only for his own account meets none of those elements. VERIFIED (definitions quoted in §2).
2. **The method does not matter; the audience does.** SEBI says research services are "agnostic to the methodology used", and buy/sell/hold calls from technical analysis are **not** exempt (RA FAQ 5, Jul-2025). So "it's only an algorithm / backtest" is **not** a defence the moment signals reach anyone else. VERIFIED.
3. **"Trading calls" now have a statutory definition** that covers **any recommendation that is "not personalized or investor specific"**. That is the RA regime's territory, and IAs are barred from it. A public or shared signal feed would be "trading calls". VERIFIED.
4. **Anyone, registered or not, who recommends a security "through public media" picks up RA trading-restriction and disclosure duties** (RA Reg. 21(2)). This matters if signals or screenshots of named securities are posted on LinkedIn, GitHub, a blog or Telegram. VERIFIED.
5. **Retail algo framework (in force for all brokers from 01-Apr-2026):** a self-written algo used for one's own account (and family) needs **no exchange registration below 10 orders/second**, but every API order now needs a **static IP** whitelisted with the broker, OAuth + 2FA, and an exchange algo tag. Vercel Hobby has no static IP, so **automated order placement from the hosted app is BLOCKED** under the "no paid services" rule. VERIFIED (SEBI + NSE texts) / Vercel docs.
6. **Exchange data is the tighter constraint for equity signals.** NSE's website terms ban automated collection; NSE's data policy bars redistribution without a licence; Kite Connect's terms allow personal use but "live market data ... cannot be displayed to the public at large". NSE's **non-display policy** expressly covers "algorithms to support trading decision making"; whether it reaches an individual using broker-supplied data is **NOT VERIFIED** (open question).
7. **To stay personal:** keep the signal surfaces behind the existing login, one user, no sharing, no public pages, no exported or posted signals on named securities, no return/performance claims in the public repo or README, and phrase every signal as **the output of the owner's own rule**, never as advice from IIP to a reader. Details in §8.

---

## 2. The definitions (quoted from the consolidated regulations)

Primary texts used:
- **SEBI (Research Analysts) Regulations, 2014, "Amended upto November 25, 2025"**, consolidated PDF linked from <https://www.sebi.gov.in/legal/regulations/nov-2025/securities-and-exchange-board-of-india-research-analysts-regulations-2014-last-amended-on-november-25-2025-_98248.html> (file: <https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1785912002778.pdf>). VERIFIED.
- **SEBI (Investment Advisers) Regulations, 2013, "Amended upto November 25, 2025"**, consolidated PDF linked from <https://www.sebi.gov.in/legal/regulations/nov-2025/securities-and-exchange-board-of-india-investment-advisers-regulations-2013-and-securities-last-amended-on-november-25-2025-_98246.html> (file: <https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1785912187595.pdf>). VERIFIED.

### 2.1 Research Analysts Regulations (as amended, incl. Third Amendment 2024, notification SEBI/LAD-NRO/GN/2024/220, w.e.f. 16-12-2024)

| Term | Text (verbatim) | Status |
|---|---|---|
| Reg. 2(1)(u) "research analyst" | "“research analyst” means a person who, for consideration, is engaged in the business of providing research services and includes a part-time research analyst;" | VERIFIED |
| Reg. 2(1)(fa) "consideration" | "“consideration” means any form of economic benefit including non-cash benefit, received or receivable, directly or indirectly, in any form whether from client or otherwise for providing research services;" | VERIFIED |
| Reg. 2(1)(wa) "research services" | "“research services” means the following services provided by research analyst: i. preparation or publication of the research report or content of the research report; or ii. providing or issuing research report or research analysis; or iii. making 'buy/sell/hold' recommendation; or iv. giving price target or stop loss target; or v. offering an opinion concerning public offer, or vi. recommending model portfolio; or vii. providing trading calls; or viii. any other service of similar nature or character, with respect to securities that are listed or proposed to be listed in a stock exchange, whether or not any such person has the job title of 'research analyst' to the clients or other persons or group of persons or general public;" | VERIFIED |
| Reg. 2(1)(zc) "trading calls" | "“trading calls” means intraday, ultra-short duration, non-delivery based (other than hedging) recommendation or any recommendation related to securities that are not personalized or investor specific." | VERIFIED |
| Reg. 2(1)(w) "research report" | "any written or electronic communication that includes research analysis or research recommendation or an opinion concerning securities or public offer, providing a basis for investment decision and does not include ... (i) comments on general trends in the securities market; (ii) discussions on the broad-based indices; (iii) commentaries on economic, political or market conditions; ... (v) internal communications that are not given to current or prospective clients; ... (vii) statistical summaries of financial data of the companies; (viii) technical analysis relating to the demand and supply in a sector or the index;" | VERIFIED |
| Reg. 2(1)(o) "price target" | "expectations of research analyst on the future performance of specific securities;" | VERIFIED |
| Reg. 2(1)(q) "public appearance" | "any participation in a conference call, seminar, forum (including interactive and non-interactive electronic forum), radio or television or internet or web or print media broadcast, authoring a print media article or other public speaking activity in public media in which a research analyst makes a recommendation or offers an opinion, concerning securities or public offer" | VERIFIED |
| Reg. 2(1)(r) "public media" | "any media source available to the general public and includes a radio, television, internet, web or print media;" | VERIFIED |
| Reg. 2(1)(fb) family of an individual RA | "shall include individual research analyst, spouse, children and parents;" | VERIFIED |
| Reg. 3(1) registration | "no person shall act as a research analyst or research entity or hold itself out as a research analyst unless he has obtained a certificate of registration from the Board" | VERIFIED |
| Reg. 21(2) public media, **any person** | "If any person including a director or employee of an investment adviser or credit rating agency or asset management company or fund manager, makes public appearance or makes a recommendation or offers an opinion concerning securities or public offers through public media, all the provisions of regulations 16 and 17 shall apply mutatis mutandis to him and he shall disclose his name, registration status and details of financial interest in the subject company at the time of,- (i) making such recommendation or offering such opinion in personal capacity; ..." | VERIFIED |
| Reg. 19(vii) AI disclosure | "A research analyst or research entity shall disclose to the client the extent of use of Artificial Intelligence tools in providing research services." | VERIFIED |
| Reg. 20(4) basis for calls | "Research analyst or research entity shall ensure that the recommendations in the research report are corroborated by relevant data and analysis forming the basis for such research service." | VERIFIED |

Later amendments shown in the consolidated text: RA (Amendment) Regulations 2025 (SEBI/LAD-NRO/GN/2025/252, 06-Aug-2025) and RA (Second Amendment) Regulations 2025 (SEBI/LAD-NRO/GN/2025/277, 25-Nov-2025; it rewrote the Reg. 7 qualification and certification rules). Neither changes the definitions above. VERIFIED (amendment list on p.37–38 of the consolidated PDF).

### 2.2 RA FAQs (SEBI circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/105, 23-Jul-2025)

Source: <https://www.sebi.gov.in/sebi_data/faqfiles/jul-2025/1753269723942.pdf>. VERIFIED.

- **FAQ 5, methodology is irrelevant:** "Research services provided under RA Regulations are specific to the securities under purview of SEBI and are agnostic to the methodology used to provide research services. Providing research services (including buy/sell/hold recommendation) on a security or securities based on any methodology (including the technical analysis) is not exempted from the purview of the RA Regulations. However, technical analyses relating to the demand and supply for a particular sector or index is exempted".
- **FAQ 7, all securities:** "RA Regulations cover all securities as defined under clause (h) of section 2 of the Securities Contracts (Regulation) Act, 1956." The Reg. 2(1)(wa) definition still limits "research services" to securities "listed or proposed to be listed in a stock exchange". Our reading: listed equities and ETFs are in scope; open-ended MF units are generally unlisted, so advice on them to others falls under the **IA** regime instead.
- **FAQ 29 / 34, indirect consideration counts:** research given "as value added services" is "for consideration ... even though no separate fee for research services is received".
- **FAQ 36, rationale required:** recommendations must be "corroborated by relevant data and analysis"; a time-stamped chart alone is not enough.

### 2.3 Investment Advisers Regulations (as amended, incl. Second Amendment 2024, w.e.f. 16-12-2024)

| Term | Text (verbatim) | Status |
|---|---|---|
| Reg. 2(1)(l) "investment advice" | "advice relating to investing in, purchasing, selling or otherwise dealing in securities and advice on investment portfolio containing securities whether written, oral or through any other means of communication for the benefit of the client and shall include financial planning: Provided that investment advice given through newspaper, magazines, any electronic or broadcasting or telecommunications medium, which is widely available to the public shall not be considered as investment advice for the purpose of these regulations; Provided further that trading calls shall not be considered as investment advice for purpose of these regulations." (The words "and investment products" were omitted w.e.f. 16-12-2024.) | VERIFIED |
| Reg. 2(1)(m) "investment adviser" | "any person, who for consideration, is engaged in the business of providing investment advice to clients or other persons or group of persons and includes a part-time investment adviser or any person who holds out himself as an investment adviser, by whatever name called;" | VERIFIED |
| Reg. 2(1)(g) "consideration" | "any form of economic benefit including non-cash benefit, received or receivable for providing investment advice;" | VERIFIED |
| Reg. 2(1)(h) "financial planning" | "shall include analysis of clients’ current financial situation, identification of their financial goals, and developing and recommending financial strategies to realise such goals;" | VERIFIED |
| Reg. 2(1)(u) "trading calls" | "shall have the same meaning as assigned to it under clause (zc) of sub-regulation (1) of regulation (2) of the [RA Regulations]" | VERIFIED |
| Reg. 2(1)(gb) "family of client" | "shall include individual client, dependent spouse, dependent children and dependent parents;" | VERIFIED |
| Reg. 4(a) exemption | "Any person who gives general comments in good faith in regard to trends in the financial or securities market or the economic situation where such comments do not specify any particular securities or investment product;" | VERIFIED |
| Reg. 15(14) AI | "An investment adviser who uses Artificial Intelligence tools ... shall be solely responsible for the security, confidentiality, integrity of the client data, ... investment advice based on output of Artificial Intelligence tools and compliance with any law" | VERIFIED |

### 2.4 SEBI Act s.12(1)

"No ... investment adviser and such other intermediary who may be associated with securities market shall buy, sell or deal in securities except under, and in accordance with, the conditions of a certificate of registration obtained from the Board". Source: Indian Kanoon copy, <https://indiankanoon.org/doc/507649/>. **NOT VERIFIED** against the sebi.gov.in Act PDF in this session. Penalty provisions (s.15HB, s.11B orders) are **NOT VERIFIED** here.

---

## 3. Applying the definitions to IIP's signal engine

Element test (both regimes need **all** of the elements):

| Element | RA (Reg. 2(1)(u), (wa)) | IA (Reg. 2(1)(m)) | IIP personal use (owner only) | Verdict |
|---|---|---|---|---|
| Consideration (incl. non-cash, indirect, "from client or otherwise") | required | required | None. No fee, ads, referral, data sale or lead generation | Not met |
| "engaged in the business of" | required | required | Building a tool for one's own portfolio is not a business | Not met |
| Recipient: "clients or other persons or group of persons or general public" | required | "clients or other persons or group of persons" | Only the owner sees output | Not met |
| "holds out" | Reg. 3(1): "hold itself out as a research analyst" | "holds out himself as an investment adviser" | Must not describe itself as adviser, research, "tips", etc. | Not met if wording rules in §8 hold |

**Conclusion (reading, not a legal opinion):** generating buy/sell signals on listed equities, ETFs or MF schemes **for one's own account** is not "research services" or "investment advice" within these definitions. The signal can be as specific as the owner likes (name, entry, exit, stop level), because nobody else receives it. **VERIFIED as to the text; the application is our reading.**

**What flips it.** Any one of these turns the same output into regulated activity, regardless of disclaimers:
- **another recipient**: a friend, colleague, family member, followers, a public page, a public repo containing outputs;
- **consideration**, even indirect: ads, affiliate or broker referral links, "premium" tiers, and possibly using live signal results to market oneself (see open question Q2);
- **holding out**: names, copy or a landing page that present IIP as advice, research, tips or calls.

When that happens, a non-personalised feed is "trading calls" (RA only; IAs are barred), personalised output to others is "investment advice" (IA), and model portfolios or price/stop targets are RA "research services". **Methodology does not exempt any of it** (RA FAQ 5).

---

## 4. Retail algo trading framework (2025) and broker APIs

### 4.1 Texts

- **SEBI circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013, 04-Feb-2025, "Safer participation of retail investors in Algorithmic trading"**: <https://www.sebi.gov.in/legal/circulars/feb-2025/safer-participation-of-retail-investors-in-algorithmic-trading_91614.html> (PDF <https://www.sebi.gov.in/sebi_data/attachdocs/feb-2025/1738665456458.pdf>). VERIFIED.
  - Para I(c): "Algos developed by tech-savvy retail investors themselves, using programming knowledge, shall also be registered with the Exchange, through their broker, only if they cross the specified order per second threshold. Further, the same registered Algo shall be permitted to be used by such retail investors for their family (but not for other investors). ‘Family’ for this purpose would mean self, spouse, dependent children and dependent parents."
  - Para I(d): brokers shall "not permit open APIs and allow access only through a unique vendor client specific API key and static IP whitelisted by the broker"; "have OAuth (Open Authentication) based authentication only"; "authenticate access to API through two factor authentication".
  - Para V: algos "where the logic is not known to the user and is not replicable, i.e. Black box" require the algo provider to "Register as a Research Analyst and maintain a detailed research report for each such algo".
  - Para III(a): algo providers "shall not be regulated by SEBI" but must be "empaneled with Exchanges".
- **SEBI circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/132, 30-Sep-2025**: <https://www.sebi.gov.in/sebi_data/attachdocs/sep-2025/1759232056254.pdf>. VERIFIED. Para 8: "W.e.f. April 01, 2026, algo framework specified in circular dated February 04, 2025 along with implementation standards and detailed operational modalities (issued by exchanges) will be applicable for all stock brokers."
- **NSE circular NSE/INVG/67858, 05-May-2025, Implementation Standards**: <https://nsearchives.nseindia.com/content/circulars/INVG67858.pdf>. VERIFIED (some lines are garbled in the PDF text layer and are flagged below).
  - A.1: "clients must mandatorily provide the stockbroker with a static IP address(es)".
  - A.5: "The need for static IP is mandatory for API access for client generated algos".
  - A.7: a static IP may be shared only between "clients [who] belong to one family as defined in SEBI circular".
  - B.2: "The Threshold Order Per Second (TOPS) is initially set at not exceeding 10 orders per second ... If the flow of algo orders from the client to the broker via API is below the defined Threshold Order Per Second (TOPS) i.e. 10 OPS per exchange, the client will not be required to register for algorithmic trading".
  - B.3: below-threshold orders get "a generic algo ID ... provided by the Exchange". The words before this are garbled in the PDF text layer: **NOT VERIFIED** verbatim.
  - G: "All algo orders (Below and above the threshold) shall be tagged with a unique identifier".
  - I.h: retail algos "should be hosted [...] servers". **The text is truncated in the PDF and the hosting location is NOT VERIFIED.**
- **The detailed operational modalities the exchanges issued on 22-Jul-2025** (referenced in the Sep-2025 circular): **NOT VERIFIED** (not read).

### 4.2 Broker side (example: Zerodha Kite Connect)

- **Kite Connect FAQ** (<https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/kite-connect-api-faqs>). VERIFIED, quoted via fetch:
  - "You can share a static IP only with immediate family members (spouse, dependent children, and dependent parents)."
  - "The maximum allowed limit is 10 orders per second (OPS) per client (trading) account."
  - The page says static IP is required "from 1 April 2025". The SEBI glide-path date is 01-Apr-2026, so the FAQ year looks inconsistent: **NOT VERIFIED which is meant**.
  - Plans: "Kite Connect Personal (Free)" has "No live market data or historical data". The paid plan is ₹500/month per API key. Price as shown on the page on 2026-10-15; it may change.
- **Kite Connect terms** (<https://kite.trade/terms/>). VERIFIED:
  - permitted use includes "personal use, where You, a Client, develops a private interface exclusively for customising personal trading and investment experience";
  - "live market data obtained via Kite Connect cannot be displayed to the public at large";
  - users may not "Scrape, build databases, or otherwise create permanent copies of such content, or keep cached copies with the intent of redistributing."
  - No last-updated date is shown.

### 4.3 What this means for IIP

| Capability | Status | Why |
|---|---|---|
| Signals only, the owner places orders manually in the broker app | **VERIFIED OK** (no API orders, so the algo framework is not engaged) | The circular regulates API/algo orders through brokers |
| Read-only broker API (holdings/positions) in local mode | REQUIRES CONFIGURATION | Personal API key; per the third-party summary, static IP is checked on order endpoints only (NOT VERIFIED on a primary broker page) |
| Automated order placement from **local** mode | REQUIRES CONFIGURATION | Static IP from the ISP or a VPS; ≤10 OPS; white-box own algo; own (and family) accounts only; broker OAuth + 2FA |
| Automated order placement from **hosted (Vercel Hobby)** mode | **BLOCKED** | Vercel static egress IPs are "available on Enterprise and Pro plans" at $100/month per project (<https://vercel.com/docs/networking/static-ips>), which conflicts with the no-paid-services rule; existing guardrail G1 also bans execution |
| Running the owner's algo for a friend's account | **BLOCKED** | "not for other investors"; the static IP may not be shared outside family |
| Offering IIP's strategies to others as an algo | **BLOCKED** without exchange empanelment; RA registration if the logic is not disclosed ("black box") | Feb-2025 circular paras III and V |
| Live equity prices via the free Kite Personal plan | Not available | The Personal plan has no market data; the paid data plan conflicts with the no-paid-API rule |

---

## 5. Finfluencer / "association" rules and educational price-data lag

- **The rule.** Regulation 16A of the SEBI (Intermediaries) Regulations 2008 (and SECC Reg. 44B, D&P Reg. 82B), published 29-Aug-2024. Persons regulated by SEBI "shall not have any direct or indirect association with another person who- (i) provides advice or any recommendation, directly or indirectly, in respect of or related to a security or securities, unless the person is registered with or otherwise permitted by the Board ...; or (ii) makes any claim, of returns or performance expressly or impliedly, in respect of or related to a security or securities, unless the person has been permitted by the Board to make such a claim." Quoted from SEBI circular **SEBI/HO/MIRSD/MIRSD-PoD-1/P/CIR/2025/11, 29-Jan-2025 (updated 08-May-2026)**, PDF linked from <https://www.sebi.gov.in/legal/circulars/jan-2025/details-clarifications-on-provisions-related-to-association-of-persons-regulated-by-the-board-miis-and-their-agents-with-persons-engaged-in-prohibited-activities_91356.html> (file <https://www.sebi.gov.in/sebi_data/attachdocs/jul-2026/1784884437684.pdf>). VERIFIED.
- **"Association" (FAQ 5):** "association in the nature of transaction involving money or money’s worth or referral of a client or interaction of information technology systems or any other association of similar nature or character". VERIFIED. A broker's API connecting to an app that gives unregistered recommendations to others could therefore be an "interaction of information technology systems", which puts the broker relationship at risk if IIP ever serves others. That last point is our reading.
- **Own account is fine (FAQ 9):** "There is no restriction on any person in availing the professional services offered by persons regulated by the Board ... such as demat account or trading account services provided that such services/accounts are not used for any of the abovementioned two prohibited activities". VERIFIED.
- **Education vs advice, 30-day lag (FAQ 8 as modified, effective 01-Jul-2026).** "A person engaged solely in education ... should not be using the market price data of the preceding thirty days to speak/talk/display the name of any security including using any code name of the security in his/her talk/speech, video, ticker, screen share etc. indicating the future price, advice or recommendation related to security or securities." Source: SEBI circular **HO/47/17/12(11)2025-MRD-POD3/I/11107/2026, 08-May-2026**, <https://www.sebi.gov.in/sebi_data/attachdocs/may-2026/1778242522289.pdf>. Para 7: "applicable with effect from July 01, 2026". **VERIFIED**; the existing doc had this as [S].
- **Enforcement example (shows that an "education" label does not protect advice).** SEBI ex-parte interim order of 04-Dec-2025 against Avadhut Sathe Trading Academy, impounding about ₹546 crore. Per Business Standard, SEBI found activity "aligned with investment advisory and research analysis without the required registration, while presenting its services as educational programs", with subscribers receiving "trading strategies, target levels, stop-loss instructions". <https://www.business-standard.com/amp/markets/news/avadhut-sathe-finfluencer-sebi-ban-disgorgement-unregistered-advisory-125120500178_1.html>. **NOT VERIFIED** (secondary; the SEBI order was not read; the outcome of any appeal is unknown).
- **Applicability to IIP.** These rules bind regulated entities and their associations. Personal use does not engage them. They bite if:
  - the owner posts named-security signals or **return/performance claims** (for example "my strategy did 24% CAGR") publicly; or
  - IIP is connected to a broker, AMC or distributor while serving others.

---

## 6. Exchange and data redistribution rules

| Source | Rule (quoted) | Status | Consequence for signals |
|---|---|---|---|
| **NSE Data Usage & Data Sharing Policy** (<https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_Data_Sharing&Usage_Policy.pdf>) | 6.1: "NSE is the sole owner of the Market Data". 7.3: "Trading Members, Subsidiaries and Subscribers shall not be permitted to redistribute any Market Data, except as agreed in the Relevant Agreement". 7.1(a): no use of Market Data "to create any financial index, whether custom or otherwise". 13(d): Market Data "includes ... delayed data, end of day data, historical data" | VERIFIED | No public display or redistribution of NSE prices, including EOD and history, without a licence. Custom composite indices built from NSE data need a separate licence |
| **NSE Non-Display Usage Policy** (<https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Non_Display_Policy.pdf>) | 1.3: "Non-Display Usage means use of Market Data as part of automated calculations or algorithms to support trading decision making processes ... If Market Data is used for deriving any value (Derived Data) for internal analysis, it will also fall under this Policy." 3.1: requires an "agreement/undertaking with/in favor of NSE Data & Analytics Ltd., upon the payment of applicable fees" | VERIFIED (text) / **NOT VERIFIED (applies to an individual retail user?)** | Literally describes a signal engine. Its "Subscriber" definition covers vendors' clients including "investors". Whether NSE expects individuals using broker-supplied data to sign is unknown, so this is an open question for the owner |
| **NSE website Terms of Use** (<https://www.nseindia.com/static/nse-terms-of-use>) | Prohibits "any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting)"; content not to be "stored (either in hardcopy or in an electronic retrieval system) ... without prior written permission of NSE" | NOT VERIFIED this session (the page timed out and is JS-rendered). Quoted via search excerpt and the repo's `docs/data/source-registry.md` §2.11 | **BLOCKED**: no automated NSE website or `/api` scraping (registry already says so) |
| **BSE** | Disclaimer: "Any reproduction, redistribution or transmission, for consideration or otherwise, of any such information contained in the Website is strictly prohibited" (registry, from `bseindia.com/rgess/disclaimer.htm`) | NOT VERIFIED (main-site terms returned 403/JS this session) | **BLOCKED** for automation |
| **Kite Connect** | "live market data ... cannot be displayed to the public at large"; no permanent copies "with the intent of redistributing" | VERIFIED | Personal-only display; no public charts or signal pages built on it |
| **AMFI** | "for your personal and non-commercial use only"; "shall not store electronically any significant portion" (registry §2 quoting <https://www.amfiindia.com/terms-of-use>) | Per registry; not re-read this session | MF signals are personal-only. A public MF signal page would breach both AMFI terms and SEBI rules |
| **SEBI price-data norms (MIIs/intermediaries)** | May-2026 circular para 6.1: price data may be shared "for investor education and awareness activities ... with a lag of thirty days" | VERIFIED | Binds exchanges and intermediaries when they share data. Sets the 30-day benchmark for any "education" display of named securities |

**Equity-signal data gap.** There is no free source of NSE/BSE equity price history that is clearly licensed and can be fetched automatically by an individual. The candidates are:
- **(a)** the user downloads bhavcopy files from NSE by hand and imports them. Manual use of published files appears to be outside the "automated collection" ban, but the storage clause makes even that **NOT VERIFIED**.
- **(b)** a paid broker data plan, which conflicts with the no-paid-keys rule.
- **(c)** a licensed vendor, also paid.

This is a data-research question for another wave-1 track, flagged here because it is a licence question as much as a technical one.

---

## 7. What changes if the hosted app is shown to others

| Scenario | Regulatory reading | Data-licence reading | Verdict |
|---|---|---|---|
| Owner alone, logged in (current hosted mode, ADR-0013) | No consideration, no business, no other recipient | Personal use under the AMFI, Kite and NSE terms | **OK** |
| Owner shows the screen to a spouse or parent once, informally | No consideration or business; the RA/IA tests are not met on the text. There is **no family exemption in the RA/IA regs**; "family" appears only in the algo circular and in "family of client" definitions for registered entities | AMFI "personal" use is arguably stretched; low risk | Low risk; do not make it routine |
| Family members use their own logins, or IIP runs signals on their accounts | Still no consideration, but "other persons" are now receiving signals. The algo circular permits a **registered** algo for "self, spouse, dependent children and dependent parents" only | AMFI "personal, non-transferable" terms are likely breached; DPDP s.3(c)(i) personal exemption weakens (see readiness doc §2.7) | **Lawyer review first** |
| Friend or colleague gets the URL and token | "other persons" + possible "holding out" | Licence breach (AMFI, Kite) | **BLOCKED** by policy |
| Public demo with live signals on named securities (portfolio, LinkedIn, GitHub README screenshots) | Reg. 21(2) public-media duties for "any person"; a non-personalised recommendation = "trading call"; return claims = prohibited activity (ii) under the association rules; marketing value may be indirect "non-cash benefit" consideration (Q2) | Public display of exchange/AMFI-derived data breaches terms | **BLOCKED**. Use synthetic data, or real data lagged ≥30 days with no forward-looking statements |
| Public GitHub repo with code only (no outputs) | Code is not a recommendation on a security. Publishing strategy logic is not "research services" on its own (our reading); avoid READMEs that claim performance on named securities | Do not commit any market-data files (registry already says this) | **OK with the rules in §8** |
| Free public app for others | IA/RA definitions in play: indirect consideration, holding out. Trading calls need RA registration. Personalised advice needs IA registration. Recommending MF schemes is IA (and possibly distribution or EOP if transaction links are added) | Exchange redistribution licence; AMFI terms prohibit it | **BLOCKED** without registration and licences |
| Paid or ad-supported | Clearly "for consideration ... business" | As above | **BLOCKED** without RA/IA registration |

---

## 8. Wording and UX that keep IIP within personal use

The legal line is **audience, consideration and holding out**, not vocabulary (§3, and readiness doc §4: disclaimers do not cure). The wording and UX rules below make sure that (i) the product never presents itself as advising anyone, and (ii) if anything leaks (a screenshot, an export, a repo file), it reads as one person's private rule output, not as a call to readers.

### 8.1 Surfaces and access (enforce in code)

1. **Signals exist only behind authentication**, in both local and hosted modes. There are no unauthenticated routes that render a signal, a ranked list of named securities, or a backtest result on a named security. Hosted mode already refuses non-production hosts and requires the access token (ADR-0013).
2. **One principal.** No invitations, no second user, no share links, no "public view" toggle. The existing hosted-mode conditions ("One user: you") remain binding.
3. **No push to third-party channels** (Telegram, WhatsApp, email lists, Slack, LinkedIn/Postiz). Alerts go only to the owner's own channel, if they are ever added.
4. **Exports carry the owner's name and a "private, not for distribution" watermark**, and strip raw exchange/AMFI data (guardrail G10 in the readiness doc). A one-click "share signal" or image export is not built.
5. **No order placement from hosted mode** (G1 plus the §4.3 static-IP block). If automation is ever added, it lives in local mode only, with the owner's own static IP, ≤10 OPS and own accounts only.
6. **Search-engine exclusion on the hosted origin**: `X-Robots-Tag: noindex` and a disallow-all `robots.txt`, so a leaked URL does not get indexed. The current hosted-mode code does not show this: NOT VERIFIED.
7. **Public repo hygiene:** no real signal outputs, backtest results on named securities, screenshots or market-data files are committed. Fixtures stay synthetic (registry already says so). The README makes **no performance or return claims**.

### 8.2 Signal wording (inside the private app)

Every signal is presented as **the result of the owner's own documented rule, with its evidence**, not as IIP telling a reader what to do:

| Use | Avoid (even privately; these read as advice or holding out if leaked) |
|---|---|
| "Rule `EQ-MOM-03` (your rule, v4): **entry condition met** for `<security>` on `<date>`" | "Buy `<security>` now", "Strong buy", "Recommended for you" |
| "Rule exit condition met: price ≤ your rule's exit level ₹X (computed from <formula>)" | "Target price ₹X", "Stop-loss target ₹X" (these are RA "research services" terms) |
| "Backtest evidence: out-of-sample <period>, after costs and tax, <metric> with <range>; method `<id>`" | "This strategy returns 24% a year", "proven", "sure-shot" |
| "Engine abstained: no rule has documented out-of-sample support for this instrument" | Making up a signal to fill the screen |
| "Decision recorded: you chose to act / not act" (owner's action log) | "IIP advises / our research / our calls" |
| "Personal decision-support tool. Output of rules you configured. Not investment advice or research; not registered with SEBI." | "SEBI-compliant", "AI advisor", "research analyst", "tips" |

**Reconciling with the existing Compliance Guard.** `regulatory-readiness.md` §7 currently BLOCKs `(buy|sell) now`, `target price` and `stop[- ]?loss`. A signal feature needs *some* action vocabulary. Recommendation:
- keep those BLOCKs on all export, share and unauthenticated surfaces;
- inside the authenticated personal view, allow the neutral rule-state labels **"entry condition met" / "exit condition met"** (plus a BUY/SELL badge only if the owner explicitly opts in), always next to the rule ID, version, backtest card and as-of date.

This is a **user decision** (see the decisions list).

### 8.3 Evidence standard, borrowed from RA rules

The project rule says "a signal may only exist if a documented, out-of-sample, cost- and tax-aware backtest supports it". This already exceeds the standard SEBI applies to registered RAs:
- RA Reg. 20(4): recommendations "corroborated by relevant data and analysis";
- RA FAQ 36: "a mere technical chart with a time stamp" is not enough.

Each signal should therefore persist:
- a rationale record (rule ID and version, data snapshot IDs, backtest run ID, cost/tax model version);
- any rating scale defined with "time horizon and benchmarks" (RA Reg. 20(2)).

The rules do not require any of this for personal use. It is the same design standard as guardrail G6.

### 8.4 LLM layer

If any LLM explanation text appears near a signal, label it "AI-generated text". The LLM must never produce or alter a signal or a number (project rule). This mirrors RA Reg. 19(vii) and IA Regs. 18(9) and 15(14), which apply only to registered entities.

---

## 9. Findings with status

| ID | Finding | Status |
|---|---|---|
| R1 | RA "research analyst" = "for consideration ... engaged in the business of providing research services"; "research services" includes buy/sell/hold, price/stop-loss targets, model portfolios, trading calls, to "clients or other persons or group of persons or general public" | VERIFIED |
| R2 | "Trading calls" includes "any recommendation related to securities that are not personalized or investor specific"; IA definition excludes trading calls | VERIFIED |
| R3 | Research services are methodology-agnostic; technical analysis on a security is not exempt (RA FAQ 5) | VERIFIED |
| R4 | RA Reg. 21(2): **any person** recommending securities through public media must disclose name, registration status and financial interest, and Regs. 16–17 apply | VERIFIED |
| R5 | Consideration includes non-cash and indirect benefit "whether from client or otherwise" (RA); IA: "any form of economic benefit including non-cash benefit" | VERIFIED |
| R6 | Retail self-built algos need no exchange registration ≤10 OPS/exchange; static IP mandatory for API orders; family = self, spouse, dependent children, dependent parents; framework applies to all brokers from 01-Apr-2026 | VERIFIED |
| R7 | Black-box algo providers must register as RA; algo providers must be exchange-empanelled | VERIFIED |
| R8 | Vercel Hobby has no static egress IP; Pro/Enterprise only at $100/month per project, so hosted auto-trading is blocked under the no-paid rule | VERIFIED (vendor docs via search summary) |
| R9 | Education lag for named-security price data is 30 days, effective 01-Jul-2026 | VERIFIED |
| R10 | Association rules ban regulated entities' links (incl. "interaction of information technology systems") with unregistered recommenders and return-claim makers; own trading/demat use is fine | VERIFIED |
| R11 | NSE: sole owner of Market Data incl. EOD and historical; no redistribution without agreement; custom index creation needs a licence | VERIFIED |
| R12 | NSE non-display policy covers algorithms supporting trading decisions; applicability to individual retail users is unclear | VERIFIED (text) / NOT VERIFIED (applicability) |
| R13 | Kite Connect: personal use allowed; no public display of live data; Personal plan has no market data | VERIFIED |
| R14 | NSE website ToU bans automated collection | NOT VERIFIED this session (page timed out); consistent with the repo registry |
| R15 | SEBI Act s.12(1) registration requirement | NOT VERIFIED (secondary copy) |
| R16 | Avadhut Sathe interim order (education label did not shield advice) | NOT VERIFIED (news only) |
| R17 | NSE operational modalities (22-Jul-2025) and the exact hosting requirement for retail algos (NSE std. I.h is truncated) | NOT VERIFIED |

---

## 10. Corrections to `docs/security/regulatory-readiness.md` (for whoever next edits it; not changed here)

- §2.2: the amended RA definitions ("research analyst", "research services", "trading calls") are now **VERIFIED** from the consolidated text (§2.1 above). The doc says the research-report text is NOT VERIFIED. It is unchanged from 2014 and quoted above.
- §2.3: the 30-day lag and the 01-Jul-2026 effective date are **VERIFIED**. The doc's G7 default of "3 months until verified" can move to 30 days.
- §2.1: the "Nov-2025 amendment content NOT VERIFIED" item is now partly resolved:
  - RA (Second Amendment) Regulations 2025 (GN/2025/277) rewrote Reg. 7 qualifications;
  - IA (Second Amendment) Regulations 2025 omitted words in IA Reg. 4(g) (footnote 24; the omitted words were not captured).
  - The definitions are unchanged.
- §2.1: the doc's "Reg. 18(9)" citation is **VERIFIED** for the IA AI-**disclosure** duty: "(9) An investment adviser shall disclose to the client the extent of use of Artificial Intelligence tools in providing investment advice." The separate "solely responsible" duty is **Reg. 15(14)**. Cite both.
- §7 Compliance Guard: needs the signal-vocabulary carve-out decided in §8.2.

---

## 11. Open questions (for a securities lawyer)

- **Q1.** Is a self-built, personal-only signal engine whose code is open-sourced on public GitHub (no outputs published) "research services ... to the general public" because anyone can run it and get named-security signals? Our reading is no: the software is not a recommendation, and each run is the runner's own. This is not settled.
- **Q2.** If the owner uses IIP (including its live track record) in a job search or on LinkedIn, could the career benefit be "non-cash benefit ... directly or indirectly ... from client or otherwise", that is, consideration?
- **Q3.** Does NSE's Non-Display Usage Policy require an individual retail investor to sign an undertaking and pay fees when computing signals from broker-supplied or bhavcopy data for personal trading?
- **Q4.** Does manually downloading NSE bhavcopy files and storing them locally for personal analysis breach the NSE ToU storage clause?
- **Q5.** Does running IIP signals for a dependent parent's or spouse's account (not via API, just advice at home) raise any IA issue, given there is no family carve-out in the IA regulations?

---

## 12. Sources (all accessed 2026-10-15)

Primary, text extracted and quoted:
1. SEBI (Research Analysts) Regulations 2014, amended up to 25-Nov-2025: <https://www.sebi.gov.in/legal/regulations/nov-2025/securities-and-exchange-board-of-india-research-analysts-regulations-2014-last-amended-on-november-25-2025-_98248.html>; PDF <https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1785912002778.pdf>. Quote: "“trading calls” means intraday, ultra-short duration, non-delivery based (other than hedging) recommendation or any recommendation related to securities that are not personalized or investor specific."
2. SEBI (Research Analysts) Regulations 2014, original Gazette (01-Sep-2014): <https://www.sebi.gov.in/sebi_data/commondocs/RESEARCHANALYSTS-regulations_p.pdf>. Quote (old 2(1)(u)): "“research analyst” means a person who is primarily responsible for ... making 'buy/sell/hold' recommendation".
3. SEBI (Investment Advisers) Regulations 2013, amended up to 25-Nov-2025: <https://www.sebi.gov.in/legal/regulations/nov-2025/securities-and-exchange-board-of-india-investment-advisers-regulations-2013-and-securities-last-amended-on-november-25-2025-_98246.html>; PDF <https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1785912187595.pdf>. Quote: "Provided further that trading calls shall not be considered as investment advice for purpose of these regulations."
4. SEBI RA FAQs, circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/105 (23-Jul-2025): <https://www.sebi.gov.in/sebi_data/faqfiles/jul-2025/1753269723942.pdf>. Quote: "agnostic to the methodology used to provide research services".
5. SEBI circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013 (04-Feb-2025): <https://www.sebi.gov.in/sebi_data/attachdocs/feb-2025/1738665456458.pdf>. Quote: "only if they cross the specified order per second threshold".
6. SEBI circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/132 (30-Sep-2025): <https://www.sebi.gov.in/sebi_data/attachdocs/sep-2025/1759232056254.pdf>. Quote: "W.e.f. April 01, 2026, algo framework ... will be applicable for all stock brokers."
7. NSE circular NSE/INVG/67858 (05-May-2025): <https://nsearchives.nseindia.com/content/circulars/INVG67858.pdf>. Quote: "below the defined Threshold Order Per Second (TOPS) i.e. 10 OPS per exchange, the client will not be required to register".
8. SEBI circular SEBI/HO/MIRSD/MIRSD-PoD-1/P/CIR/2025/11 (29-Jan-2025, updated 08-May-2026): <https://www.sebi.gov.in/sebi_data/attachdocs/jul-2026/1784884437684.pdf>. Quote: "interaction of information technology systems".
9. SEBI circular HO/47/17/12(11)2025-MRD-POD3/I/11107/2026 (08-May-2026): <https://www.sebi.gov.in/sebi_data/attachdocs/may-2026/1778242522289.pdf>. Quote: "it has been decided to prescribe a time lag of 30 days for both sharing and usage of price data for educational purposes."
10. NSE Data Usage & Data Sharing Policy: <https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_Data_Sharing&Usage_Policy.pdf>. Quote: "shall not be permitted to redistribute any Market Data, except as agreed in the Relevant Agreement".
11. NSE Non-Display Usage Policy: <https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Non_Display_Policy.pdf>. Quote: "use of Market Data as part of automated calculations or algorithms to support trading decision making processes".
12. Kite Connect terms: <https://kite.trade/terms/>. Quote: "live market data obtained via Kite Connect cannot be displayed to the public at large".
13. Zerodha Kite Connect API FAQs: <https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/kite-connect-api-faqs>. Quote: "You can share a static IP only with immediate family members (spouse, dependent children, and dependent parents)."
14. Vercel Static IPs docs: <https://vercel.com/docs/networking/static-ips>. Quote (search summary): "Static IPs are available on Enterprise and Pro plans".

Secondary (NOT VERIFIED against primary in this session):
15. SEBI Act s.12(1), Indian Kanoon: <https://indiankanoon.org/doc/507649/>. Quote: "shall buy, sell or deal in securities except under, and in accordance with, the conditions of a certificate of registration".
16. NSE Terms of Use (search excerpt): <https://www.nseindia.com/static/nse-terms-of-use>. Quote: "prohibited to conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting)".
17. Business Standard on the Avadhut Sathe interim order: <https://www.business-standard.com/amp/markets/news/avadhut-sathe-finfluencer-sebi-ban-disgorgement-unregistered-advisory-125120500178_1.html>. Quote: "presenting its services as educational programs".
18. Zerodha Z-Connect, "Explaining the latest SEBI algo trading regulations" (06-Feb-2025): <https://zerodha.com/z-connect/business-updates/explaining-the-latest-sebi-algo-trading-regulations>. Quote: "you can continue to do so as long as your order frequency is below an exchange-prescribed threshold."
19. Repo internal: `docs/data/source-registry.md` (AMFI, BSE and NSE terms entries); `docs/security/regulatory-readiness.md`; `docs/architecture/architecture-decision-records/0013-hosted-mode-vercel.md`.
