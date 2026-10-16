# Verification of "research-equity-data-alt.md" (wave 1, adversarial check)

- **Report checked:** `docs/research/wave1/research-equity-data-alt.md`
- **Checker role:** adversarial skeptic. Every source below was re-opened on **2026-10-15** (access date for all URLs).
- **Method:** NSE ToU, NSE Data Usage Policy PDF and Yahoo ToS were downloaded with `curl` and the clause text extracted locally (NSE ToU HTTP 200, 327,495 bytes; NSE policy PDF HTTP 200, 248,553 bytes, `pdftotext`; Yahoo ToS HTTP 200, 147,619 bytes). Broker pages were read with WebFetch. The BSE disclaimer page is a JS shell (HTTP 200, 14,287 bytes, no clause text), so it was checked through a web search only. data.gov.in returned HTTP 403 to WebFetch, so GODL was checked through a web search only.
- **Not legal advice.**

## Verdict summary

| ID | Claim | Verdict |
|---|---|---|
| EQ-1 | NSE site / bhavcopy / XBRL BLOCKED for automation, storage, simulation | **CONFIRMED.** Has one omitted nuance (see below) |
| EQ-2 | NSE "simulation" restriction flows down to brokers (residual risk) | **CONFIRMED** as a residual risk. Quotes are exact, and the Angel/ICICI offsets are now directly verified |
| EQ-3 | yfinance BLOCKED by Yahoo ToS | **CONFIRMED** |
| EQ-4 | Upstox rank 1: free, daily since 2000, fundamentals endpoints | **CONFIRMED** |
| EQ-5 | Kite Connect and Dhan fail no-paid-keys | **CONFIRMED** (minor omission) |
| EQ-6 | Survivorship and adjustment gaps block single-stock signals | **WEAKENED.** The conclusion stands, but the evidence is incomplete: public Upstox staff statements on adjustment were missed |
| EQ-7 | Broker data must never reach hosted mode / public repo | **WEAKENED.** The rule is prudent, but its evidence is Kite-specific, and the Upstox staff statement is more permissive than the report suggests |
| EQ-8 | Fundamentals: manual entry authoritative; Upstox vendor undisclosed | **CONFIRMED** |
| EQ-9 | BSE: redistribution/reproduction banned, no explicit anti-scraping clause seen | **CONFIRMED** (as NOT VERIFIED-directly; the search independently reproduces the quote) |
| EQ-10 | data.gov.in GODL permissive, no company-level prices | **CONFIRMED** (licence via search; absence claim remains NOT VERIFIED) |

No finding was refuted. Every quote I could open matches the cited page.

---

## Per-finding detail

### EQ-1: NSE BLOCKED. CONFIRMED

The text was extracted from https://www.nseindia.com/static/nse-terms-of-use (accessed 2026-10-15). All three quotes are verbatim:
- "User is prohibited to conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting) on or in relation to our Website / Mobile Application."
- "...shall not be copied, modified, reverse engineer, reproduced, uploaded, transmitted, posted, stored (either in hardcopy or in an electronic retrieval system), ... without prior written permission of NSE."
- "...shall not, in any form and manner, use or make the data or Content available on the Website / Mobile Application, for any gaming, virtual trading or simulation activities under any circumstances whatsoever."

**Omitted nuance.** The sentence right after the storage clause reads: "Unless the information or Content is available for download, not to aggregate, copy or duplicate in any manner any of the content or information which is available on Website / Mobile Application."
- This implies that content NSE offers *for download* (such as bhavcopy files) is treated differently for copying and aggregation.
- The unconditional "stored ... without prior written permission" clause still precedes it, so the text is internally ambiguous.
- The report states flatly that a manual download stored in SQLite "conflicts". It should instead record that the ToU is ambiguous for downloadable files.
- The automation ban is unambiguous, so BLOCKED for automation stands.

### EQ-2: NSE policy §7.4 "simulation". CONFIRMED (as residual risk)

The text was extracted from https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_Data_Sharing&Usage_Policy.pdf (accessed 2026-10-15). The quotes for §7.3, §7.4 and §7.1(a) are exact.

Two caveats that the report should state:
- **Who §7.4 targets.** §7.4 is about who Market Data "shall not be provided to": "individuals/entities/platforms/apps/websites etc., engaging in online gaming, virtual trading or simulation, fantasy games, an activity of similar nature". "Simulation" sits next to "fantasy games" and "online gaming", which points to virtual-trading games rather than private backtesting.
- **How the "flows down" link works.** The link to brokers comes through §7.1: Relevant Agreements "will include end user restrictions as maybe required ... by NSE/ NSE Data". The report's "flows down" is therefore a reasonable inference, not an explicit text. Calling it a residual risk is correct.

The offsets are now directly verified:
- **Angel One:** https://www.angelone.in/knowledge-center/smartapi/detailed-introduction-to-smartapi (accessed 2026-10-15): "We give you Historical Data for backtesting purposes, again completely FREE OF COST." The report labelled this "via search", but it is now VERIFIED. The same page says historical data covers the "NSE Equity & NFO Futures segment".
- **ICICI Breeze:** https://www.icicidirect.com/faqs/fno/are-there-any-charges-for-accessing-historical-data-and-using-other-features-of-breeze-api (accessed 2026-10-15): "with Breeze API you get access to all the features like backtesting historical data, fetching live data via websockets etc absolutely free of cost". VERIFIED.

### EQ-3: Yahoo / yfinance. CONFIRMED

https://legal.yahoo.com/xw/en/yahoo/terms/otos/index.html (accessed 2026-10-15) says you may not: "access or collect data, or attempt to access or collect data, from our Services using any automated means, devices, programs, algorithms or methodologies, including but not limited to robots, spiders, scrapers, data mining tools, or data gathering or extraction tools, for any purpose without our express, prior permission."

The next clause strengthens the case further: "use any material or content from, including without limitation any data, (a) to create any database, archive...". The report did not cite it.

### EQ-4: Upstox rank 1. CONFIRMED

- **Pricing:** https://upstox.com/trading-api/ (accessed 2026-10-15): "₹0", "Free access to trading & market data APIs", "Yes! All trading + data APIs are free of cost." The ₹10/order note says "Valid till 30th September 2026".
- **History depth:** https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/ (accessed 2026-10-15):
  - Days/Weeks/Months "Available from January, 2000";
  - Minutes/Hours "Available from January, 2022";
  - Days: "1 decade leading up to the to_date" per request.
- **Analytics Token:** https://upstox.com/developer/api-documentation/api-overview/ (accessed 2026-10-15): "Generated once, no daily re-authorization needed". It powers "Market Data and Realtime & Streaming APIs"; portfolio and account endpoints are read-only "when accessed from a registered static IP". So the report is right that market data does not need a static IP.
- **Fundamentals:** the announcement lists 8 endpoints, effective "May 11, 2026".

**Citation error (minor).** The report attributes "You are permitted to utilize the data provided by the Upstox API for analysis purposes" to both threads 3772 and 13250. It is in **3772** (staff member Pradeep Jaiswar), https://community.upstox.com/t/upstox-api-legal-or-not/3772. Thread 13250 says something different (see EQ-7).

### EQ-5: Kite and Dhan paid. CONFIRMED

- **Zerodha:** https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/historical-data-and-live-market-data-payment-plan (accessed 2026-10-15): Personal plan "does not include live market data or historical data"; paid plan "costs ₹500 per month per API key".
  - **Omission:** the same page says paid subscribers generating ₹2,000+ monthly brokerage get 500 Developer Credits (worth ₹500), which offsets the fee. This is irrelevant for a no-orders app, but the report should mention it for completeness.
- **Dhan:** https://dhan.co/support/platforms/dhanhq-api/is-the-dhanhq-data-api-subscription-free-if-i-execute-a-minimum-number-of-trades-every-month/ (accessed 2026-10-15): "The promotional offer ... has been discontinued. The Data API is currently available at ₹499 + applicable taxes per month." Exact.

### EQ-6: Survivorship / adjustment gaps. WEAKENED

The doc claim is correct: the v3 historical-candle page does not mention corporate-action adjustment (re-checked 2026-10-15). But the report labels the adjustment behaviour simply "NOT VERIFIED" and misses public Upstox staff statements:
- https://community.upstox.com/t/is-historical-price-adjusted-for-corporate-action/3548 (accessed 2026-10-15), staff member Pradeep Jaiswar:
  - 2023-12-28: "Yes, corporate actions are adjusted on the same day."
  - 2024-06-12: "Currently, we only adjust for bonuses and splits."
- A search summary of https://community.upstox.com/t/historical-stock-data-are-they-adjusted-for-dividends-splits/5942 and a third-party test repo (https://github.com/hariyaakshay-cpu/equity-intelligence-platform/pull/2) reports "daily history split-adjusted; demergers not adjusted". This is NOT VERIFIED directly.

**Consequences the report should carry:**
1. The best available evidence says candles are split- and bonus-adjusted, and are **not** adjusted for dividends or demergers. That means **total return cannot be had from candles alone**, which strengthens the abstain rule.
2. **Retroactive rescaling.** Split adjustment is applied "on the same day" to the whole history, so previously stored candles silently become inconsistent with new fetches. The adapter needs a full-history re-fetch, or a mismatch detector, after every corporate action. The report's `adjustment_basis` field is right in spirit, but it misses this storage hazard.

**Delisted coverage.** https://upstox.com/developer/api-documentation/expired-instruments/ (accessed 2026-10-15) lists only expired option and future contracts plus expired historical candles. Nothing there covers delisted equities. The report's survivorship concern stands.

The overall conclusion (abstain on single-stock signals) **survives**. The evidence is incomplete, so the finding is weakened, not refuted.

### EQ-7: Local-only for broker data. WEAKENED

- The Kite quotes are exact. https://kite.trade/terms/ (accessed 2026-10-15) says "live market data obtained via Kite Connect cannot be displayed to the public at large". The Zerodha support page says "you cannot display data from Kite Connect APIs on other platforms, as this violates the exchange's data vending policies."
- **However:**
  - These are **Kite** terms, and the report excludes Kite. They do not bind Upstox.
  - The Kite clause is about **live** market data.
  - Upstox's own staff answer at https://community.upstox.com/t/api-usage-clarification/13250 (accessed 2026-10-15) is more permissive. To the question about sharing "derived analytics, signals, and reports", the answer was: "Yes, you can distribute market data to Upstox users, as calling these data endpoints requires an Upstox API access token", and "As such no additional approval is required from our side."
  - The report cites this thread as if it said only "analysis purposes".
- **Assessment:** the binding-rule outcome is still correct and should be kept as a *policy choice*. The reasons:
  - the repo is public;
  - Vercel is internet-reachable;
  - forum replies are not binding terms;
  - NSE policy §7.3 bars redistribution.

  But the report presents it as **compelled by cited terms**, and for Upstox it is not. It is a conservative project decision. Label it that way.

### EQ-8: Fundamentals. CONFIRMED

- https://upstox.com/developer/api-documentation/announcements/company-fundamentals-api/ (accessed 2026-10-15) names no vendor, no plan and no history depth.
- https://upstox.com/developer/api-documentation/get-income-statement/ (accessed 2026-10-15): "All monetary values are in Indian Rupees (Crore)." The example has 4 periods (Mar 2023 to Mar 2026).
- **Addition:** a `time_period` parameter (`yearly` / `quarterly`, default `yearly`) exists. There are **no filing or publication-date fields**, which confirms the point-in-time (look-ahead) gap in §6.

### EQ-9: BSE. CONFIRMED (still NOT VERIFIED directly)

- The direct fetch of https://www.bseindia.com/static/about/disclaimer.htm again returned the 14,287-byte JS shell.
- An independent web search on 2026-10-15 reproduces "Any reproduction, redistribution or transmission, for consideration or otherwise, of any such information contained on the Website is strictly prohibited and would constitute a breach of the laws of India". The current page says "on", an older copy says "in". The proprietary-rights sentence is also reproduced.
- Treating BSE as BLOCKED for automation remains a cautious inference, **not** a textual ban. The report says this honestly.

### EQ-10: data.gov.in GODL. CONFIRMED (via search)

- The search on 2026-10-15 reproduces the licence grant: "use, adapt, publish ... for all lawful commercial and non-commercial purposes", with an attribution notice required (Section 5). Official pages: https://data.gov.in/government-open-data-license-india (HTTP 403 to WebFetch) and the gazette PDF https://data.gov.in/sites/default/files/Gazette_Notification_OGDL.pdf (not opened).
- "No company-level price data" is an absence claim. It is plausible, but remains NOT VERIFIED.

---

## Important omissions

1. **NSE ToU "available for download" carve-out.** The ToU has an unaddressed ambiguity for manually downloaded bhavcopy files (see EQ-1). A manual, personal-use import path may be arguable. It needs a written query to NSE, not a flat BLOCKED.
2. **Upstox adjustment behaviour.** The public staff statements (splits and bonuses adjusted; dividends and demergers not) and the resulting **retroactive-rescaling storage hazard** are missing (see EQ-6).
3. **Upstox redistribution statement.** Thread 13250 explicitly permits distribution to authenticated Upstox users. It is mis-summarised, and EQ-7 should be relabelled a project policy rather than a terms requirement.
4. **Unsupported premise.** "Brokers are exchange trading members that are licensed to give market data to their own clients" is stated without any citation. The broker statements imply it, but no exchange or SEBI text was cited.
5. **Upstox formal API terms.** The report's whole rank-1 choice rests on forum posts and a pricing page. Upstox's actual developer terms page, if public, was not searched for. Until it is read, rank 1's compliance posture is weaker than the shortlist table suggests.
6. **Kite fee offset.** The Kite ₹2,000-brokerage credit offset is not mentioned (minor; see EQ-5).
7. **Angel coverage inconsistency.** The release note lists NSE stocks plus many segments. The introduction page says history covers the "NSE Equity & NFO Futures segment". The coverage statements are inconsistent and should be reconciled at sign-up.
8. **SEBI algo circular.** The number "SEBI/HO/MIRSD/MIRSD-PoD/P/2025/0000013" is cited only through a Zerodha blog. It was not opened at sebi.gov.in by the report or by this check: NOT VERIFIED.

## Sources (all accessed 2026-10-15)

**Exchanges**
- NSE ToU: https://www.nseindia.com/static/nse-terms-of-use
- NSE Data Usage & Sharing Policy: https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_Data_Sharing&Usage_Policy.pdf
- BSE disclaimer (search only): https://www.bseindia.com/static/about/disclaimer.htm

**Yahoo**
- Yahoo ToS: https://legal.yahoo.com/xw/en/yahoo/terms/otos/index.html

**Upstox**
- Pricing: https://upstox.com/trading-api/
- Historical candles: https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/
- API overview: https://upstox.com/developer/api-documentation/api-overview/
- Fundamentals announcement: https://upstox.com/developer/api-documentation/announcements/company-fundamentals-api/
- Income statement: https://upstox.com/developer/api-documentation/get-income-statement/
- Expired instruments: https://upstox.com/developer/api-documentation/expired-instruments/
- Community threads: https://community.upstox.com/t/upstox-api-legal-or-not/3772 · https://community.upstox.com/t/api-usage-clarification/13250 · https://community.upstox.com/t/is-historical-price-adjusted-for-corporate-action/3548

**Zerodha**
- https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/historical-data-and-live-market-data-payment-plan
- https://kite.trade/terms/
- https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/can-i-use-historical-and-live-data-taken-from-kite-connect-api-on-other-platforms

**Dhan**
- https://dhan.co/support/platforms/dhanhq-api/is-the-dhanhq-data-api-subscription-free-if-i-execute-a-minimum-number-of-trades-every-month/

**Angel One**
- https://www.angelone.in/knowledge-center/smartapi/detailed-introduction-to-smartapi
- https://smartapi.angelone.in/smartapi/forum/topic/4012/release-note-free-historical-data-access-for-indices-nse-nfo-bse-bfo-mcx-and-cds-with-smartapi

**ICICI Breeze**
- https://www.icicidirect.com/faqs/fno/are-there-any-charges-for-accessing-historical-data-and-using-other-features-of-breeze-api

**Fyers**
- https://support.fyers.in/portal/en/kb/articles/what-are-the-fyers-api-rate-limits-for-standard-and-prime-plans

**data.gov.in (search only)**
- GODL: https://data.gov.in/government-open-data-license-india
