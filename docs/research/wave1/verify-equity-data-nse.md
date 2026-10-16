# Verification: research-equity-data-nse.md (adversarial review)

- **Report checked:** `docs/research/wave1/research-equity-data-nse.md`
- **Reviewer stance:** adversarial skeptic. A claim is refuted when the cited source does not say what the report claims. It is weakened when the source is accurate but the conclusion or status goes further than the source supports.
- **Date:** 2026-10-15. All sources were accessed on 2026-10-15.
- **Method:**
  - The NSE ToU, NSE Indices ToU and disclaimer, the UDiFF spec xlsx, the NSE pricing PDF and the NSE Data Usage and Sharing Policy PDF were each downloaded once, to a scratchpad outside the repo, and the quotes were checked against the extracted text.
  - Market-data files were probed with **HTTP HEAD only**: about 25 one-off requests, with no file bodies downloaded or stored.
  - Broker pages and terms were read with WebFetch.
  - This is research, not legal advice.

## Verdict summary

| ID | Claim | Verdict | One-line reason |
|---|---|---|---|
| NSE-1 | Automated bhavcopy download prohibited by NSE ToU | **CONFIRMED** | The quote is verbatim on the live page, and the page carries "Updated on: 29/10/2025" |
| NSE-2 | "Simulation activities" ban covers backtests → BLOCKED | **WEAKENED** | The quote is verbatim, but "backtest = simulation" is an interpretation. BLOCKED overstates it; the honest status is NOT VERIFIED (ambiguous) |
| NSE-3 | Storage restricted; download carve-out ambiguous | **CONFIRMED** | Both sentences are verbatim and adjacent; NOT VERIFIED is the right label |
| NSE-4 | UDiFF CM format, 34 fields, no CA/adjusted fields | **CONFIRMED** (minor nits) | Matches the spec sheet "Bhavcopy File Format" exactly; two small mislabels |
| NSE-5 | UDiFF archive starts 2024-01-01 | **CONFIRMED**, with a material omission | Re-probed, same result. But official `sec_bhavdata_full` daily files exist on nsearchives from at least 2019-09-30, which the report marks as unverified third-party claims |
| NSE-6 | NSE Indices bans automation; no point-in-time constituents | **WEAKENED** | The automation ban is verbatim. "Manual entry is allowed" is not supported by the terms, and official index-change press releases (which allow point-in-time reconstruction) were missed |
| NSE-7 | NSE licensed EOD data is cost-prohibitive | **CONFIRMED** (with nuance) | Prices are verbatim. The policy's own "Research Activity" definition makes a waiver for a profit-seeking investor even less likely than the report says |
| NSE-8 | Broker APIs are the realistic licensed route | **WEAKENED** | Kite Connect's terms (not read by the report) restrict building databases or permanent copies of API content and ban mock-trading use. The Upstox "free" claim was not supported by the cited page |
| NSE-9 | No official rate limit; Akamai filtering → VERIFIED | **WEAKENED** | An absence cannot be VERIFIED, and the report's own table row 12 says NOT VERIFIED. The curl behaviour differs from the report (instant HTTP/2 reset, not a 30 s silence) |
| NSE-10 | Corporate actions only from ToU-restricted pages or paid product | **WEAKENED** | "Only" is false: Zerodha documents that Kite historical candles are already corporate-action adjusted. PR.zip is an official file (HEAD 200), not only a forum rumour |

---

## Per-finding detail

### NSE-1: CONFIRMED

The live page <https://www.nseindia.com/static/nse-terms-of-use> (HTTP 200, 327,494 bytes) contains this sentence verbatim:

> "User is prohibited to conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting) on or in relation to our Website / Mobile Application."

The page also says "Updated on: 29/10/2025". The definition reads *"'Website' means https://www.nseindia.com/."* The report's treatment of the archive host is the conservative reading: it does not rely on `nsearchives` falling outside that definition. No personal-use exception exists anywhere on the page. A search of the page text for "personal" and "non-commercial" found no such grant. The only grant is *"a non-exclusive, non-transferable, limited right to access the Website / Mobile Application and avail the services provided by NSE"*.

### NSE-2: WEAKENED (status should be NOT VERIFIED, not BLOCKED)

The quote is verbatim:

> "User acknowledges, agrees and undertakes that it shall not, in any form and manner, use or make the data or Content available on the Website / Mobile Application, for any gaming, virtual trading or simulation activities under any circumstances whatsoever."

However:
- The clause groups "simulation" with "gaming" and "virtual trading". Read in that context, it most plausibly targets fantasy and paper-trading products. Whether a private historical backtest is a "simulation activity" is an **interpretation**, which the report itself concedes ("arguably counts").
- Policy §8.4 is the matching restriction in NSE's data licensing: *"The Market Data shall not be provided to individuals/entities engaging in gaming, virtual trading, an activity of similar nature…"*. It does **not** use the word "simulation". That weakly supports the gaming/virtual-trading reading.

The conservative engineering choice (do not backtest on website data) is reasonable. But labelling it **BLOCKED** presents an interpretation as a settled finding. The correct label is **NOT VERIFIED (ambiguous) — treated as blocked by project policy until NSE answers in writing**.

### NSE-3: CONFIRMED

Both sentences are verbatim and adjacent on the live page:
- *"…stored (either in hardcopy or in an electronic retrieval system), adapted, altered, … without prior written permission of NSE."*
- *"Unless the information or Content is available for download, not to aggregate, copy or duplicate in any manner any of the content or information which is available on Website / Mobile Application."*

The report correctly leaves the interaction between them as NOT VERIFIED.

### NSE-4: CONFIRMED (minor nits)

Spec xlsx downloaded: HTTP 200, 35,556 bytes. Sheets: "File Nomenclature", "Trade File Format", "Bhavcopy File Format", "Standard Value List_latest".

- **Nomenclature matches verbatim:** `BhavCopy_<code of the entity>_<segment code>_0_0_0_YYYYMMDD_<Flag>_<hhmm>.csv.gz`. The website path is "CM = https://www.nseindia.com/all-reports".
- **Fields:** all 34 rows match, including tags and `NUMERIC(25,6)` for prices. There is no corporate-action or adjusted-price field.
- **Nit 1:** field 30 `Rmks` is marked **"Blank"** in the CM column of the spec, so it is not a populated CM field as the report's table implies.
- **Nit 2:** the date fields are typed `Varchar (10) Format (YYYY-MM-DD)`. A parser must therefore validate them as strings.

### NSE-5: CONFIRMED, with a material omission

Re-probe (HEAD, Chrome UA) of `nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_<date>_F_0000.csv.zip`:

| Date | Result |
|---|---|
| 20261014 | 200, 205,416 bytes, last-modified Wed, 14 Oct 2026 11:03:02 GMT |
| 20240101 | 200, 151,548 bytes, last-modified Fri, 05 Jan 2024 14:39:01 GMT |
| 20231229 | 404 |
| 20230102 | 404 |
| Legacy `content/historical/EQUITIES/2024/JUL/cm05JUL2024bhav.csv.zip` | 503 |

All of this matches the report.

**Omission:** the report (§1 row 5) says pre-2024 history via `sec_bhavdata_full` is a third-party claim and "NOT VERIFIED (official)". A HEAD probe of the official host contradicts that framing.

Path: `https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv`

| Date | Result |
|---|---|
| 03012020 | **200**, last-modified Fri, 03 Jan 2020 18:25:26 GMT |
| 02012020, 31122019, 16122019, 02122019, 01102019 | **200** |
| 30092019 | **200** |
| 23092019, 16092019, 01092019, 01082019, 01072019, 01012019 | 404 |
| 04012010, 01062010, 03012011, 02012012, 01012013, 02012015, 01012018 | 404 |

So NSE officially hosts daily full bhavcopy files (with delivery data) from about **2019-09-30**. Only a handful of dates were probed, so the exact start date is NOT VERIFIED. The third-party claim of "June 2010" is **not** supported on this path.

This does not change the legal conclusion: the same ToU applies. It does change the "what exists" picture: about 7 years of official daily history exist, not 2.8 years.

### NSE-6: WEAKENED

**What is confirmed.** <https://www.niftyindices.com/terms-of-use> (HTTP 200) contains these sentences verbatim:
- *"You may not conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting) on or in relation to our website without our express written consent."*
- *"The Site may be used only for lawful purposes by individuals for personal, non-commercial use only."*

The CSV HEAD returns 200 with last-modified Thu, 15 Oct 2026 18:00:21 GMT.

**Overstated: "Manual entry with a citation is allowed."** No clause grants this.
- The ToU says *"No material from the Site may be copied, modified, reproduced, republished, uploaded, transmitted, posted or distributed in any form without prior written permission from the Company."*
- The disclaimer (<https://www.niftyindices.com/disclaimer>) says *"No part of this Site or information contained herein may be reproduced, stored in a retrieval system or transmitted in any form … without prior written permission"*.

Typing constituents into a database is arguably "reproduced" or "stored in a retrieval system". The honest status is **NOT VERIFIED (ambiguous)**, the same as NSE-3. The same caveat applies to the return-target-feasibility study's manual use of factsheets and TRI.

**Missed: an official point-in-time source.** NSE Indices publishes dated "Replacements in indices" press releases. Each names the stocks included and excluded, with the effective date. Examples:
- <https://www.niftyindices.com/Press_Release/ind_prs28082017.pdf> (2017)
- <https://www.niftyindices.com/Press_Release/ind_prs21022025.pdf> (2025)
- The archive index at <https://www.niftyindices.com/press-release>

These were found via web search on 2026-10-15; the PDFs were not opened by this reviewer, so the exact text is NOT VERIFIED. Point-in-time membership of the Nifty 50 could in principle be reconstructed backwards from the current list plus these releases, manually and under the same ToU caveat. "Not found" should read: **"no ready-made file; reconstructable manually from official press releases (NOT VERIFIED for completeness)"**.

### NSE-7: CONFIRMED (with nuance)

`NSE_Pricing_file_-_Domestic_clients_20260309171343.pdf` (13 pages) says "commercials for Domestic Customers effective 1st April 2026". Section 3.0 gives:
- "Capital Market … 1,00,000" (INR per annum/per site/*per medium)
- "EOD Corporate Data … 5,00,000" (INR per annum/per site)
- "Fees are exclusive of taxes/ levies as may be applicable"

The report's prices are verbatim. Two nuances it missed:
- **The EOD fee is a display licence.** The footnote says *"The above-mentioned commercials are per medium of data display i.e. website/mobile app being two different mediums"*. This tariff is aimed at vendors displaying data, so the right product for a single non-display user is NOT VERIFIED.
- **Historical Trade Data is trade-level data.** "Historical Trade Data … Capital Market 1,10,000" (and "Students / Researchers … 22,000") is listed separately from EOD in §4.0. It is not a daily OHLC history product.

The waiver route is weaker than the report says:
- The Data Usage and Sharing Policy defines *"(k) Research Activity means any research carried out by Non-Commercial Users, Research Entities and Analysts by subscribing to Market Data transmitted by NSE, for purposes other than trading or profit."*
- A personal app built to make buy/sell decisions is for trading and profit, so the §9.3 waiver is very unlikely to apply.

The quotes from §8.2, §8.3, §8.4, §9.3, (g) and §10.3 were all found verbatim.

### NSE-8: WEAKENED

**Upstox, cited page.** <https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/> confirms:
- "Days/Weeks/Months: Available from January 2000"
- daily max range "1 decade"
- `Authorization: Bearer {your_access_token}`

The page carries **no pricing statement** and does not say whether candles are adjusted. The report's "the historical candle API is free" is therefore uncited in its own source list.

**Upstox, pricing.** The claim is supported elsewhere: <https://upstox.com/trading-api/> says *"All trading + data APIs are free of cost."* Upstox's developer terms on storage and backtesting remain **NOT VERIFIED** by this reviewer as well.

**Zerodha, charges.** <https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/what-are-the-charges-for-kite-apis> confirms:
- Personal: "No historical or real-time data included"
- Connect: "Historical candle data", "Available for retail users at ₹500 per app each month"

**Zerodha, terms (not read by the report; material).** <https://kite.trade/terms/> (no date shown) says:
- *"Unless expressly permitted by Zerodha or by the applicable laws, you will not, and will not permit your end users or others acting on your behalf to, do the following with content returned from the APIs. Scrape, build databases, or otherwise create permanent copies of such content, or keep cached copies with the intent of redistributing."*

  This can be read in two ways:
  - "with the intent of redistributing" qualifies only "cached copies";
  - or it qualifies the whole list.

  On the first reading, a local price database built from Kite candles is prohibited without Zerodha's express permission.
- *"You are not permitted to use the APIs and/or live market data for virtual/mock trading apps, trading related games…"*

The broker route is therefore **not** clearly cleaner than NSE's website for a stored-history backtest engine. It has its own "permanent copies" restriction, and that blocks the project's core requirement (a stored, reproducible backtest dataset) until Zerodha confirms in writing. The headline "realistic lawful path" must be downgraded to "candidate path; storage terms restrictive (Kite) or unread (Upstox)".

### NSE-9: WEAKENED

"No published limit found" is a search result, not a verifiable fact. The report's own §1 row 12 labels it **NOT VERIFIED**, which contradicts the VERIFIED status in the findings list.

Re-probe of the bhavcopy URL:
- Chrome UA: 200.
- Default curl UA over HTTP/2: **failed in about 0.05 s with an HTTP/2 stream error (curl exit 92)**, twice.
- Default curl UA forced to HTTP/1.1: timed out at 30 s.

The report describes only "no response within 30 s". Both behaviours point to bot filtering, but the report's description is incomplete. That the filtering is specifically Akamai bot management is an inference from an `akamai-grn` header, not documented.

robots.txt checks match the report: www returns `Allow: /`, `Disallow: /market-data-test` and a sitemap line; nsearchives returns 404.

### NSE-10: WEAKENED

The status BLOCKED, for automated collection of NSE corporate-action pages, stands. The word "only" does not:
- **Kite candles are already adjusted.** Zerodha staff on the Kite forum (<https://kite.trade/forum/discussion/16280/historical-5-minute-api-data-corporate-action-price-and-volume-adjustments>) say historical data is *"adjusted for corporate actions, including bonuses, splits, rights issues, spin-offs, and extraordinary dividends (more than 2%)"*. They add that *"The volume data will also be adjusted for corporate actions such as Bonus, Split, Right issue, Demerger, etc., except dividends."* So an adjusted price series is available via a broker without separate corporate-action records.
- **Caveats on that series.** The same thread says *"Kite Connect does not provide an unadjusted historical price-and-volume series"* and there is *"currently no dedicated Corporate Actions API"*. Ordinary dividends are not adjusted, so the series is a price-return series, not total return. The adjustment methodology is Zerodha's and is undocumented in formula form. That conflicts with the project's "every number traceable to a formula" rule, so it is usable only as an UNVERIFIED-methodology input.
- **PR.zip is official.** HEAD `https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR141026.zip` returned **200**. The PR.zip is therefore an official NSE file, not just something a forum mentions. The `Bc` file's contents and layout remain NOT VERIFIED; the body was not downloaded.
- **The report contradicts itself.** §5.2 calls broker candles "not stated" for adjustment and §6 calls it NOT VERIFIED for Kite. Kite's adjustment is in fact documented by Zerodha staff, while Upstox's remains NOT VERIFIED.

---

## Important omissions

1. **Kite Connect terms restrict "build databases, or otherwise create permanent copies"** of API content and ban "virtual/mock trading apps" (<https://kite.trade/terms/>). The report recommends Option A without having read this, and it directly affects a backtest store.
2. **Official `sec_bhavdata_full` daily files exist on nsearchives from about 2019-09-30** (HEAD 200). The report treats pre-2024 official history as unverified.
3. **Kite historical candles are corporate-action adjusted** (splits, bonus, rights, spin-offs, dividends above 2%; volume adjusted too). There is no unadjusted series and no corporate-action API. The data is price-return, not total-return.
4. **Official NSE Indices "Replacements in indices" press releases** give dated inclusions and exclusions, so point-in-time constituents can be reconstructed manually. This weakens the "not found" conclusion on survivorship.
5. **Policy definition (k): "Research Activity … for purposes other than trading or profit".** This effectively rules out the §9.3 non-commercial waiver for this use case.
6. **The NSE EOD tariff is priced "per medium of data display"**, which makes it a vendor display licence. Whether a non-display, single-user licence exists or what it costs is NOT VERIFIED; ask `marketdata@nse.co.in`.
7. **NSE Indices terms do not support "manual entry with a citation is allowed".** Manual transcription faces the same "reproduced / stored in a retrieval system" ambiguity as NSE-3.
8. **Upstox's free-API claim needs its own citation:** <https://upstox.com/trading-api/>, *"All trading + data APIs are free of cost."* Its developer terms on storage and backtesting are still unread.
9. **Minor spec nits:** `Rmks` is Blank for CM, and the date fields are `Varchar(10)`.

## Sources (all accessed 2026-10-15)

| Source | URL | Quote / observation |
|---|---|---|
| NSE Terms of Use | https://www.nseindia.com/static/nse-terms-of-use | "systematic or automated data collection activities"; "stored (either in hardcopy or in an electronic retrieval system)"; "gaming, virtual trading or simulation activities"; "Updated on: 29/10/2025" |
| NSE robots.txt | https://www.nseindia.com/robots.txt | "Allow: /", "Disallow: /market-data-test" |
| UDiFF spec xlsx | https://nsearchives.nseindia.com//web/mediaattachment/2026-06/UDiFF_trade_and_Bhavcopy_file_formats_20260630115803.xlsx | 34 fields; `Rmks` Blank for CM |
| NSE pricing (domestic) | https://nsearchives.nseindia.com/web/mediaattachment/2026-03/NSE_Pricing_file_-_Domestic_clients_20260309171343.pdf | "effective 1st April 2026"; "Capital Market 1,00,000"; "EOD Corporate Data 5,00,000"; "per medium of data display" |
| NSE Data Usage and Sharing Policy | https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_DataUsageandSharingPolicy.pdf | §8.4; §9.3; (g); (k) "for purposes other than trading or profit" |
| NSE Indices ToU | https://www.niftyindices.com/terms-of-use | "without our express written consent"; "No material from the Site may be copied…" |
| NSE Indices disclaimer | https://www.niftyindices.com/disclaimer | "reproduced, stored in a retrieval system" |
| NSE Indices press releases | https://www.niftyindices.com/press-release | "Replacements in indices" (via search; PDFs not opened) |
| Upstox Historical Candle V3 | https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/ | "Available from January 2000"; no pricing; adjustment not stated |
| Upstox Trading API | https://upstox.com/trading-api/ | "All trading + data APIs are free of cost." |
| Zerodha Kite API charges | https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/what-are-the-charges-for-kite-apis | "No historical or real-time data included" (Personal); "Historical candle data" (Connect, ₹500/app/month) |
| Kite Connect terms | https://kite.trade/terms/ | "Scrape, build databases, or otherwise create permanent copies of such content…"; "virtual/mock trading apps, trading related games" |
| Kite forum: CA adjustment | https://kite.trade/forum/discussion/16280/historical-5-minute-api-data-corporate-action-price-and-volume-adjustments | "adjusted for corporate actions, including bonuses, splits, rights issues, spin-offs, and extraordinary dividends (more than 2%)"; "does not provide an unadjusted historical price-and-volume series" |
| HEAD probes (this review) | nsearchives `content/cm/…`, `products/content/sec_bhavdata_full_*.csv`, `archives/equities/bhavcopy/pr/PR141026.zip` | Results in NSE-5, NSE-9 and NSE-10 |
