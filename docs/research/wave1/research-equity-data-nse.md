# Research: official NSE equity data (prices, corporate actions, index constituents)

- **Research ID:** `equity-data-nse` (wave 1)
- **Date:** 2026-10-15. All web sources were accessed on 2026-10-15.
- **Question:** Can a personal, single-user app legally and reliably get NSE end-of-day equity prices, corporate actions and index constituents from **official** sources, and specifically, can it download the daily bhavcopy automatically?
- **Status labels:** VERIFIED / NOT VERIFIED / REQUIRES CONFIGURATION / BLOCKED. This is research, not legal advice.

---

## 0. Bottom line

1. **Automatic daily bhavcopy download from NSE is BLOCKED.** NSE's Terms of Use (page dated "Updated on: 29/10/2025") say: *"User is prohibited to conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting) on or in relation to our Website / Mobile Application."* A scheduled job that fetches `nsearchives.nseindia.com/.../BhavCopy_NSE_CM_...zip` every evening is automated data collection "in relation to" the website. The ToU makes no exception for personal or single-user use. The files are technically reachable (HTTP 200 to a browser-like client), but that does not make automation permitted.
2. **Storing NSE data locally is also restricted.** The same ToU says content shall not be *"stored (either in hardcopy or in an electronic retrieval system) … without prior written permission of NSE"*. The next sentence carves out downloadable content only for "aggregate, copy or duplicate". Whether a user may keep a self-downloaded bhavcopy in a personal database is **ambiguous (NOT VERIFIED)**. Only NSE's written permission resolves it.
3. **The ToU bars "simulation activities".** *"…shall not, in any form and manner, use or make the data or Content available on the Website / Mobile Application, for any gaming, virtual trading or simulation activities under any circumstances whatsoever."* A backtest arguably counts as a simulation. That matters directly to the project's rule that a signal may only exist if a backtest supports it. **Backtesting signals on NSE-website data is BLOCKED until NSE confirms otherwise in writing.**
4. **NSE's own licensed route exists but costs too much for one person.** NSE Data & Analytics EOD Capital Market data costs **₹1,00,000 per year per site per medium**, and EOD Corporate Data costs **₹5,00,000 per year** (domestic tariff effective 1 April 2026). The Data Usage and Sharing Policy allows "reduced fee arrangements or waivers for Non-Commercial Users". However, its definition of a Non-Commercial User (academia, not-for-profits, researchers, students) does not obviously cover a private investor. Status: **REQUIRES CONFIGURATION** (a written request to NSE).
5. **The realistic lawful path for equity prices is a broker API the user already holds an account with.** Two options were found:
   - **Upstox:** the historical candle API is free, with daily candles "Available from January, 2000".
   - **Zerodha Kite Connect:** ₹500/month, which includes historical data. Kite Connect Personal is free but has no market data.
   Both are **REQUIRES CONFIGURATION**. The developer terms on storage, redistribution and backtesting were **NOT VERIFIED** in this session and must be read before adoption.
6. **NSE Indices (niftyindices.com) is no better.** Its ToU says *"You may not conduct any systematic or automated data collection activities … without our express written consent"*, and the site is for *"personal, non-commercial use only"*. Index constituent CSVs exist (probed HTTP 200), but automated fetching is **BLOCKED**. Manual entry with a citation is allowed.
7. **The existing project decision stands.** Source registry §2.11 and ADR 0004 already mark NSE and BSE as BLOCKED for automation. This research confirms that decision with the current ToU text, and adds the UDiFF format, the history-depth probe, the pricing and the broker alternatives.

**Consequence for the engine:** until a licensed source is configured, any equity buy/sell signal must abstain with the reason `NO_LICENSED_EQUITY_PRICE_SOURCE`. "No suitable candidate" remains the valid answer.

---

## 1. Status table

| # | Item | What exists (official) | Automated access in a personal app | Status |
|---|---|---|---|---|
| 1 | CM UDiFF Common Bhavcopy (daily EOD OHLC for all CM instruments) | `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip`, linked from `nseindia.com/all-reports` | Prohibited by NSE ToU (automated collection; storage) | **BLOCKED** (automation). File existence and headers: **VERIFIED** by probe |
| 2 | UDiFF bhavcopy format specification | Official spec xlsx on NSE "Forms & Formats" (v. 2026-06-30) | Not applicable (documentation) | **VERIFIED** (§3) |
| 3 | Legacy bhavcopy (`cmDDMONYYYYbhav.csv.zip`) | Discontinued w.e.f. 8 July 2024 (NSE circular 62424) | — | **VERIFIED** discontinued (via secondary sources quoting the circular; NSE's own copy of 62424 was not opened). Archive path returns 503 to the probe |
| 4 | History depth of UDiFF CM bhavcopy on nsearchives | Probe: 2024-01-01 → 200; 2023-12-29 → 404 | — | **VERIFIED** (by HEAD probe): starts 2024-01-01 |
| 5 | Pre-2024 daily history (legacy files; `sec_bhavdata_full`) | Third parties claim `sec_bhavdata_full` from June 2010 | — | **NOT VERIFIED** (official) |
| 6 | Full Bhavcopy + Security Deliverable data (`sec_bhavdata_full_DDMMYYYY.csv`) | Listed on `nseindia.com/all-reports` (per secondary sources) | Prohibited (same ToU) | **BLOCKED**; columns **NOT VERIFIED** officially |
| 7 | Corporate actions (dividend, split, bonus, rights; ex/record dates) | (a) web page `nseindia.com/companies-listing/corporate-filings-actions` with "Download (.csv)"; (b) `Bc` file inside CM PR.zip (secondary sources) | Prohibited for automation. The page is driven by an undocumented `/api/` endpoint | **BLOCKED** (automation); manual CSV download: user decision (§5.2) |
| 8 | Price adjustment for corporate actions | The UDiFF bhavcopy has **no** corporate-action field and **no** adjusted prices (spec, §3) | — | **VERIFIED** (spec) — adjustment must be computed by the engine from CA records |
| 9 | Index constituents (Nifty 50, Nifty 500, …) | NSE Indices CSV, e.g. `niftyindices.com/IndexConstituent/ind_nifty50list.csv` (probe 200, 3,344 bytes) | NSE Indices ToU prohibits automated collection without written consent | **BLOCKED** (automation); manual entry allowed |
| 10 | Historical index constituents (point-in-time, survivorship-free) | Not found as an official free file | — | **NOT VERIFIED** (likely a licensed product) |
| 11 | Securities master (`EQUITY_L.csv`) | `nsearchives.nseindia.com/content/equities/EQUITY_L.csv` (probe 200, `text/csv`, last-modified 2026-10-14 21:35 GMT) | Prohibited (same ToU) | **BLOCKED** (automation) |
| 12 | NSE published rate limits | None published | — | **NOT VERIFIED** (no official figure exists that could be found) |
| 13 | NSE licensed EOD data (NSE Data & Analytics) | EOD CM ₹1,00,000/yr/site/medium; EOD Corporate Data ₹5,00,000/yr | Licensed | **REQUIRES CONFIGURATION** (cost prohibitive) |
| 14 | Broker API: Upstox historical candles | Free; daily candles since Jan 2000 | Licensed via the user's own broker account | **REQUIRES CONFIGURATION**; storage/backtest terms **NOT VERIFIED** |
| 15 | Broker API: Zerodha Kite Connect | ₹500/month incl. historical candles; Personal (free) has no data | Licensed via the user's own broker account | **REQUIRES CONFIGURATION**; storage/backtest terms **NOT VERIFIED** |

---

## 2. Terms of use (quoted)

### 2.1 NSE Terms of Use

Source: <https://www.nseindia.com/static/nse-terms-of-use> (accessed 2026-10-15; the page says "Updated on: 29/10/2025"). Text was taken from the live page with one browser-equivalent GET.

- **Scope.** *"'Website' means https://www.nseindia.com/."* The archive host `nsearchives.nseindia.com` is not named. However, the anti-automation clause covers activity *"on or in relation to our Website"*, and the website's All Reports page links to the archive files. **Treat the archive host as covered.** That the archive host falls outside the clause is **NOT VERIFIED**, and the project does not rely on it.
- **Automated collection:** *"User is prohibited to conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting) on or in relation to our Website / Mobile Application."*
- **Copy/store/redistribute:** *"User agrees that any information or content or data on the Website / Mobile Application shall not be copied, modified, reverse engineer, reproduced, uploaded, transmitted, posted, stored (either in hardcopy or in an electronic retrieval system), adapted, altered, translated, disseminated, distributed, displayed, performed, broadcasted, published, hyperlinked, sold, marketed, licensed, rented, leased or distributed in any form, without prior written permission of NSE."*
- **Downloadable-content carve-out (narrow):** *"Unless the information or Content is available for download, not to aggregate, copy or duplicate in any manner any of the content or information which is available on Website / Mobile Application."* This relaxes "aggregate, copy or duplicate" for downloadable files. It does not lift the "stored … in an electronic retrieval system" restriction in the previous sentence, and it does not lift the automation ban. **The interpretation is NOT VERIFIED.**
- **Simulation ban:** *"User acknowledges, agrees and undertakes that it shall not, in any form and manner, use or make the data or Content available on the Website / Mobile Application, for any gaming, virtual trading or simulation activities under any circumstances whatsoever."*
- **Load:** *"Take any action that imposes an unreasonable or disproportionately large load on the Website / Mobile Application's infrastructure."* (listed as a prohibited use).
- **Enforcement:** *"NSE may, at its discretion, monitor User's access"*; *"NSE shall have the sole right to block / restrict User's access"*; and *"Access … may be restricted or terminated at any time if NSE determines that User is accessing Website / Mobile Application from outside India"*. The last point matters because a Vercel deployment runs outside India.
- **Rights reserved:** *"All rights not expressly granted herein are reserved."* The only grant is *"a non-exclusive, non-transferable, limited right to access the Website / Mobile Application and avail the services provided by NSE"*.
- **robots.txt** (`https://www.nseindia.com/robots.txt`, fetched 2026-10-15T18:01Z): `User-agent: * / Allow: / / Disallow: /market-data-test`. `nsearchives.nseindia.com/robots.txt` returns **404**. robots.txt does not override the ToU.

### 2.2 NSE Data Usage and Sharing Policy

Source: <https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_DataUsageandSharingPolicy.pdf> (accessed 2026-10-15; the PDF carries no date).

- §8.2: *"The ownership of all Market Data shall at all times lie with NSE/ NSE Data."*
- §8.3: *"Trading Members, Subsidiaries and Subscribers shall not be permitted to redistribute any Market Data, except as agreed in the Relevant Agreement between the parties."*
- §8.4: *"The Market Data shall not be provided to individuals/entities engaging in gaming, virtual trading, an activity of similar nature or any other activity which shall be prohibited…"*
- §9.3: *"The Board of NSE Data may also consider introducing reduced fee arrangements or waivers for Non-Commercial Users."*
- Definition (g): *"Non Commercial Users means accredited academic institutions, members of academia and not for profit institutions/entities, Researchers, Students etc."* Whether a private individual investor qualifies is **NOT VERIFIED**.
- §10.3: Non-commercial users *"shall sign a declaration of confidentiality"*.

### 2.3 NSE Indices Limited (niftyindices.com)

Source: <https://www.niftyindices.com/terms-of-use> and <https://www.niftyindices.com/disclaimer> (accessed 2026-10-15).

- *"You may not conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting) on or in relation to our website without our express written consent."*
- *"The Site may be used only for lawful purposes by individuals for personal, non-commercial use only."*
- *"No material from the Site may be copied, modified, reproduced, republished, uploaded, transmitted, posted or distributed in any form without prior written permission from the Company."*
- Disclaimer: *"No part of this Site or information contained herein may be reproduced, stored in a retrieval system or transmitted in any form or by any means … without prior written permission of the Company or its applicable group company. Use or distribution of the Company's or any of its group company's index data and the use of their index data to create financial products require a license from NSE Indices Limited…"*
- robots.txt (fetched 2026-10-15): `Allow: /` with a few page disallows. Again, robots.txt does not override the ToU.
- Note: the project's return-target-feasibility study already uses NSE Indices factsheets and TRI history that were **read manually**. That is consistent with these terms only as manual, personal reference use.

---

## 3. Formats (VERIFIED from official spec)

Source: NSE "Forms & Formats" page <https://www.nseindia.com/static/resources/forms-formats-members>, UDiFF tab. Spec file: <https://nsearchives.nseindia.com//web/mediaattachment/2026-06/UDiFF_trade_and_Bhavcopy_file_formats_20260630115803.xlsx> (accessed 2026-10-15). Guidance document: <https://nsearchives.nseindia.com/web/sites/default/files/inline-files/UDiFF%20guidance%20document_Ver1.0.pdf>.

**File nomenclature (spec sheet "File Nomenclature"):** `BhavCopy_<code of the entity>_<segment code>_0_0_0_YYYYMMDD_<Flag>_<hhmm>.csv.gz`. Flag is `P` (provisional) or `F` (final); hhmm is `0000` for final files. The spec's website path for CM is `https://www.nseindia.com/all-reports`. In practice the website serves `.csv.zip`: the probe got `content-type: application/zip` for `BhavCopy_NSE_CM_0_0_0_20261014_F_0000.csv.zip`.

**Bhavcopy fields (spec sheet "Bhavcopy File Format"; ISO tag in brackets).** These are the fields applicable to CM:

| # | Field | Tag | Type / notes |
|---|---|---|---|
| 1 | Trade Date | `TradDt` | YYYY-MM-DD |
| 2 | Business Date | `BizDt` | YYYY-MM-DD |
| 3 | Segment Indicator | `Sgmt` | per Standard Value List |
| 4 | Source | `Src` | |
| 5 | Instrument Type | `FinInstrmTp` | |
| 6 | Unique Instrument Identifier | `FinInstrmId` | NUMERIC(10), "Token Number" |
| 7 | ISIN | `ISIN` | VarChar(12) |
| 8 | Symbol | `TckrSymb` | Varchar(12) |
| 9 | Series | `SctySrs` | Varchar(4) (EQ, BE, …) |
| 14 | Instrument Name | `FinInstrmNm` | VarChar(50) |
| 15–19 | Open / High / Low / Close / LTP | `OpnPric` `HghPric` `LwPric` `ClsPric` `LastPric` | NUMERIC(25,6) |
| 20 | Previous Close | `PrvsClsgPric` | NUMERIC(25,6) |
| 22 | Settlement Price | `SttlmPric` | NUMERIC(25,6) |
| 25 | Total Traded Qty | `TtlTradgVol` | Numeric(25) |
| 26 | Total Traded Value | `TtlTrfVal` | NUMERIC(25,6) |
| 27 | Total Number of Trades | `TtlNbOfTxsExctd` | Numeric(25) |
| 28 | Session Id | `SsnId` | |
| 29 | Market Lot Size | `NewBrdLotQty` | Numeric(12) |
| 30 | Remarks | `Rmks` | VARCHAR(150) |
| 31–34 | Reserved | `Rsvd1..4` | "currently the values shall be blank" |

Fields 10–13, 21, 23 and 24 (expiry, strike, option type, underlying price, open interest) are blank for CM.

**Implications for the engine:**
- Prices are 6-decimal NUMERIC. Parse them as `Decimal` from the string and never as float. This fits ADR 0002.
- There is **no corporate-action flag and no adjusted close.** Total-return or adjusted series need separate corporate-action records plus a documented adjustment formula. The engine must not infer splits from price jumps.
- The guidance document says: "Amounts will always be in rupees and up to 6 places after the decimal" and dates are ISO 8601 (quoted via search summary of the guidance PDF). The PDF was downloaded and identified as 16 pages, but these lines were not re-read in full: **NOT VERIFIED** beyond the summary.

**Legacy and other files:**
- The legacy CM bhavcopy was discontinued. Search results quoting NSE circular NSE/MSD/62424 (12 June 2024) say: *"Exchange has now postponed the discontinuation dates for old Trade and Bhavcopy File to July 08, 2024. The existing Trade and Bhavcopy files shall continue to be available in parallel along with the new UDiFF format files till July 05, 2024."* The circular was seen via a third-party mirror (<https://www.ricago.com/assets/front/base/file/file_management/2065.pdf>) and the search summary. The NSE-hosted copy was not opened, so this is VERIFIED from secondary sources only.
- **NSE's older historical-data product description** (<https://nsearchives.nseindia.com/content/press/Data_details_CM.pdf>, undated) describes a bhavcopy with *"Corporate action flags — Ex-date indicators, e.g. XD for a dividend"* and data *"From late 1995 onwards"*. This is the paid historical product's legacy layout, not the current free file.
- **PR.zip and the `Bc` file.** A Zerodha forum user says the PR.zip *"contains the file Bc140825 which is for the date 14th august 2025 and contains corporate action information for each Symbol such has dividends, splits, Bonus etc."* (<https://tradingqna.com/t/nse-cm-bhavcopy-pr-zip/185583>). This is a secondary source; the official column layout is **NOT VERIFIED**.

---

## 4. Probes (what was actually done)

All probes ran on 2026-10-15 between 18:01:00Z and 18:02Z from a macOS workstation in India.
- They were **HTTP HEAD requests only** for market-data files. No bhavcopy, master file or constituent file body was downloaded or stored.
- Only public spec documents (format xlsx, policy and pricing PDFs, ToU HTML) were downloaded, once, to a session scratchpad outside the repo.
- These were one-off manual verification requests, not a collection job.

| URL (pattern) | Result |
|---|---|
| `nsearchives…/content/cm/BhavCopy_NSE_CM_0_0_0_20261014_F_0000.csv.zip` (Chrome UA) | `HTTP/2 200`, `application/zip`, `content-length: 205416`, `last-modified: Wed, 14 Oct 2026 11:03:02 GMT`, weak ETag, served via Akamai (`akamai-grn` header) |
| Same URL with `curl/8.7.1` UA | No HTTP response within 30 s. Non-browser clients are filtered (bot management) |
| `…_20240708_F_0000.csv.zip` | 200, 166,236 bytes, last-modified 2024-07-08 11:44 GMT |
| `…_20240105`, `…_20240102`, `…_20240101` | 200. The 2024-01-01/02 files have last-modified 2024-01-05, i.e. back-filled when UDiFF launched |
| `…_20231229`, `…_20231201`, `…_20231002`, `…_20230703`, `…_20230102`, `…_20200103`, `…_20100104` | 404 → **the UDiFF archive starts 2024-01-01** |
| Legacy `content/historical/EQUITIES/2010/JAN/cm04JAN2010bhav.csv.zip`, `…/2024/JUL/cm05JUL2024bhav.csv.zip`; `archives.nseindia.com/…/2020/JAN/…` | 503 (282 bytes). Whether this is retirement or bot-blocking is **NOT VERIFIED** |
| `nsearchives…/content/equities/EQUITY_L.csv` | 200, `text/csv`, last-modified 2026-10-14 21:35:02 GMT |
| `niftyindices.com/IndexConstituent/ind_nifty50list.csv` | 200, 3,344 bytes, last-modified 2026-10-15 18:00:21 GMT |

**Publication time.** The final file for 2026-10-14 shows `last-modified` 11:03 GMT, which is 16:33 IST on trade date T. One sample is not a schedule, so the publication time is **NOT VERIFIED** as a guarantee.

**Rate limits.** NSE publishes none. The only figures found are third-party library defaults, e.g. the `nse` package (<https://github.com/BennyThadikaran/NseIndiaApi>) throttles to about 3 requests/second and advises downloading "after-market hours". Those are not NSE limits. The observed behaviour is Akamai bot management: non-browser user agents get no response, and plain scripted requests are widely reported to get 403s. Defeating that filter (TLS impersonation, cookie harvesting) would itself be the "systematic or automated data collection" the ToU prohibits. **This project must never do it.**

---

## 5. Can a personal, single-user app download the daily bhavcopy automatically?

### 5.1 Answer: **No — BLOCKED**

- The ToU ban on "systematic or automated data collection" has no personal-use exception. A daily cron is systematic by construction.
- Working around bot protection would breach both the ToU and the project's "never scrape sites whose terms forbid it" rule.
- The ToU separately restricts storage in "an electronic retrieval system" without written permission. A local SQLite or Turso table is exactly that.
- The hosted mode (Vercel, likely non-Indian egress) also falls under the ToU line on access "from outside India".
- Using the data for backtests runs into the "simulation activities" ban.

### 5.2 Options that remain (in order of preference)

| Option | How it works | Status | Notes |
|---|---|---|---|
| **A. Broker API (user's own account)** | Upstox Historical Candle V3 or Kite Connect; daily OHLCV per instrument; the user supplies their own token | **REQUIRES CONFIGURATION** | Upstox: *"Days, Weeks, Months: Available from January, 2000"*, max range per request "1 decade" for daily, `Authorization: Bearer` token (<https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/>). Whether candles are corporate-action adjusted is not stated: **NOT VERIFIED**. Zerodha: Connect is "₹500 per app monthly" and includes "Historical candle data"; Personal (free) has no data (<https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/what-are-the-charges-for-kite-apis>). **The developer terms on storage, redistribution and backtesting must be read and quoted before an adapter is built (NOT VERIFIED).** Requires a token in local config, not in the public repo. Works in local mode; hosted mode needs a separate review |
| **B. Written permission from NSE** | Email NSE (Data: `marketdata@nse.co.in`; website: `nsewebmaster@nse.co.in`) asking whether a single individual may download the daily CM UDiFF bhavcopy for private, non-redistributed analysis, including backtesting | **REQUIRES CONFIGURATION** (user action) | The only way to resolve the storage and simulation clauses. Record the reply verbatim in the source registry |
| **C. User-initiated manual import** | The user downloads the file in a browser from `nseindia.com/all-reports`, and the app parses the local file the user selects. No network call by the app | **NOT VERIFIED** (legal ambiguity) | Avoids the automation ban. Does **not** clearly resolve the "stored … electronic retrieval system" and "simulation" clauses. The user must decide (see decisions). If adopted: tag `licence_class=PERSONAL_USE_ONLY` and never export or share |
| **D. NSE Data & Analytics licence** | EOD CM ₹1,00,000/yr/site/medium; EOD Corporate Data ₹5,00,000/yr; Historical Trade Data CM ₹1,10,000/yr (students/researchers ₹22,000) | **REQUIRES CONFIGURATION** (cost) | Source: <https://nsearchives.nseindia.com/web/mediaattachment/2026-03/NSE_Pricing_file_-_Domestic_clients_20260309171343.pdf> ("effective 1st April 2026"; "Fees are exclusive of taxes"). Out of proportion for one investor |
| **E. Third-party mirrors / yfinance / unofficial NSE APIs** | GitHub bhavcopy mirrors, `nse`/`jugaad-data` wrappers, Yahoo | **BLOCKED** | Derived from ToU-restricted data, or from scraping. Already excluded by ADR 0004 |

---

## 6. Corporate actions and index constituents — what a signal engine needs

**Corporate actions.**
- **Why they are needed:** raw bhavcopy closes are unadjusted, so splits, bonuses and dividends create false return jumps. A backtest built on them is wrong.
- **What exists officially:**
  - NSE's corporate-actions page (manual CSV download): <https://www.nseindia.com/companies-listing/corporate-filings-actions>.
  - The `Bc` file in PR.zip (secondary sources).
  - Company announcements.
  All are under the NSE ToU, so automation is **BLOCKED**.
- **Paid alternative:** "EOD Corporate Data" at ₹5,00,000/yr.
- **Broker candles:** whether broker candles are already adjusted is **NOT VERIFIED** for Upstox and Kite. This must be established (documented or tested against a known split) before any return series is trusted.
- **Engine rule:** adjustment factors must be computed by a documented formula from cited CA records. The engine must never infer them from price gaps. If a CA record is missing for a gap above a threshold, the series is marked `INCOMPLETE` and the supervisor abstains.

**Index constituents.**
- The current lists are on niftyindices.com as CSV. Automation is **BLOCKED**, but manual entry with a citation is fine.
- **Point-in-time history** (who was in the Nifty 500 on a past date) was **not found** as an official free file. Without it, any universe-based backtest has **survivorship bias**, which the project's own return-target-feasibility study (RT-7, Bessembinder) flags.
- Status: historical constituents **NOT VERIFIED / likely licensed**. Until this is resolved, the engine must not backtest a stock-selection signal on today's constituent list. It should abstain or restrict itself to index-level series, e.g. index TRI read manually from NSE Indices.

---

## 7. Recommendations

1. Keep `nse.*` and `niftyindices.*` **BLOCKED** for automation in `docs/data/source-registry.md`. Add the 29/10/2025 ToU date, the "simulation activities" clause, the UDiFF format and the 2024-01-01 archive start.
2. Make the equity signal path depend on a **licensed broker adapter** (Option A). Read and quote the Upstox and Zerodha developer terms first, as a separate research item. Until that is done, every equity buy/sell request returns an abstention with reason `NO_LICENSED_EQUITY_PRICE_SOURCE`.
3. Ask NSE in writing (Option B). Ask specifically about (a) automated daily download of the CM UDiFF bhavcopy by one individual, (b) local storage, and (c) whether private backtesting counts as "simulation activities". Store the reply verbatim.
4. Parse the UDiFF layout with `Decimal` and key instruments by **ISIN + series**, since symbols change. Keep a synthetic fixture with fictional values only, matching the existing probes policy.
5. Build corporate-action adjustment as a deterministic, cited, tested module before any equity backtest. Gaps lead to abstention.
6. Do not ship any equity feature in hosted (Vercel) mode until the licensing of the chosen source covers it.

---

## 8. Sources (all accessed 2026-10-15)

| Source | URL | Quote used |
|---|---|---|
| NSE Terms of Use (Updated on: 29/10/2025) | https://www.nseindia.com/static/nse-terms-of-use | "User is prohibited to conduct any systematic or automated data collection activities…"; "stored (either in hardcopy or in an electronic retrieval system)"; "gaming, virtual trading or simulation activities" |
| NSE robots.txt | https://www.nseindia.com/robots.txt | "Allow: /", "Disallow: /market-data-test" |
| NSE Forms & Formats (UDiFF) | https://www.nseindia.com/static/resources/forms-formats-members | Links to UDiFF guidance v1.0, catalogue v1–v4, trade & bhavcopy formats xlsx |
| UDiFF trade & bhavcopy formats (2026-06-30) | https://nsearchives.nseindia.com//web/mediaattachment/2026-06/UDiFF_trade_and_Bhavcopy_file_formats_20260630115803.xlsx | "BhavCopy_<code of the entity>_<segment code>_0_0_0_YYYYMMDD_<Flag>_<hhmm>.csv.gz"; field list §3 |
| UDiFF guidance document v1.0 | https://nsearchives.nseindia.com/web/sites/default/files/inline-files/UDiFF%20guidance%20document_Ver1.0.pdf | "Amounts will always be in rupees and up to 6 places after the decimal" (via search summary) |
| NSE historical data dissemination (CM), undated | https://nsearchives.nseindia.com/content/press/Data_details_CM.pdf | "From late 1995 onwards…"; "Corporate action flags — Ex-date indicators, e.g. XD for a dividend" |
| NSE Data Usage and Sharing Policy | https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_DataUsageandSharingPolicy.pdf | §8.3, §8.4, §9.3, definition (g) |
| NSE Market Data Pricing — Domestic (eff. 1 Apr 2026) | https://nsearchives.nseindia.com/web/mediaattachment/2026-03/NSE_Pricing_file_-_Domestic_clients_20260309171343.pdf | "Capital Market 1,00,000" (EOD, INR per annum/per site/per medium); "EOD Corporate Data 5,00,000" |
| NSE EOD/historical subscription page | https://www.nseindia.com/static/market-data/eod-historical-data-subscription | Contact `marketdata@nse.co.in` (via search summary) |
| NSE Indices Terms of Use | https://www.niftyindices.com/terms-of-use | "You may not conduct any systematic or automated data collection activities … without our express written consent" |
| NSE Indices Disclaimer | https://www.niftyindices.com/disclaimer | "…reproduced, stored in a retrieval system or transmitted … without prior written permission" |
| NSE circular 62424 (third-party mirror) | https://www.ricago.com/assets/front/base/file/file_management/2065.pdf | "postponed the discontinuation dates for old Trade and Bhavcopy File to July 08, 2024" (via search summary) |
| jugaad-data issue #79 (secondary) | https://github.com/jugaad-py/jugaad-data/issues/79 | UDiFF CM/FO URL pattern |
| Zerodha forum, PR.zip (secondary) | https://tradingqna.com/t/nse-cm-bhavcopy-pr-zip/185583 | "Bc140825 … contains corporate action information for each Symbol such has dividends, splits, Bonus etc." |
| NseIndiaApi (secondary) | https://github.com/BennyThadikaran/NseIndiaApi | Library throttle ~3 req/s; "after-market hours" advice (via search summary) |
| Upstox Historical Candle Data V3 | https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/ | "Days, Weeks, Months: Available from January, 2000"; "Authorization: Bearer {your_access_token}" |
| Zerodha Kite API charges | https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/what-are-the-charges-for-kite-apis | Connect "₹500 per app monthly", includes "Historical candle data"; Personal: no data |
| Kite Connect Personal announcement | https://kite.trade/forum/discussion/14868/introducing-kite-connect-personal-apis-free-apis-for-personal-use | "minus the market data (both real-time and historical)" (via search summary) |
