# Research: alternative sources for Indian equity prices and fundamentals (wave 1, "equity-data-alt")

- **Date of research and access date for every URL:** 2026-10-15
- **Scope:** official exchange files (BSE bhavcopy, NSE/BSE XBRL), regulators and government (SEBI, MCA, data.gov.in), broker APIs (Zerodha Kite Connect, Upstox, Angel One SmartAPI, Dhan, Fyers, plus ICICI Breeze), and unofficial libraries (yfinance, jugaad-data, nsepy, nsetools).
- **Bar to clear:** no paid keys; compliant with each source's terms; personal, non-commercial, local use; every number traceable to a source; a signal exists only if a documented, out-of-sample, cost- and tax-aware backtest supports it.
- **Status labels:** VERIFIED (read from the primary page today), NOT VERIFIED (secondary source only, or not checked), REQUIRES CONFIGURATION (needs the user's own account or credentials), BLOCKED (the terms forbid the use).
- **Not legal advice.** This report records what the terms say. It does not say how a court would read them.

---

## 0. Answer in one paragraph

No equity dataset meets every requirement at zero cost. A fully compliant set would be authoritative (straight from the exchange), free, automatable, survivorship-free (includes delisted stocks) and total-return (dividends included). The exchanges' own websites rule out automation:
- **NSE** bans automated collection and storage, and bans use "for any gaming, virtual trading or simulation activities".
- **BSE** bans reproduction and redistribution.

**Yahoo** (behind yfinance) bans automated collection "for any purpose". The NSE-scraping libraries (jugaad-data, nsepy, nsetools) inherit NSE's prohibition.

**The least-bad compliant route** is a **free broker API on the user's own brokerage account**, used **locally and only by the user**. Brokers are exchange trading members that are licensed to give market data to their own clients. Ranked:
1. **Upstox**: free; daily candles since January 2000; also has a fundamentals API.
2. **Angel One SmartAPI**: free; Angel explicitly markets the data "for backtesting purposes".
3. **ICICI Breeze**: free; "backtesting historical data" is named in the FAQ.
4. **Fyers**: free tier, but only 5 years of daily data.

**Kite Connect (₹500/month) and Dhan (₹499 + taxes/month) fail the no-paid-keys rule.**

**For fundamentals, the best source is the user's own manual entry from company filings, with a citation for each figure.** Upstox's fundamentals API is a convenience cross-check: its upstream vendor is not disclosed, so it cannot be the authoritative source.

**Two gaps stay open even on the best route. Until they close, the engine must abstain on single-stock signals:**
1. **Survivorship.** Delisted stocks are probably missing from broker instrument lists (NOT VERIFIED).
2. **Dividends and total return.** Broker candles are price-only. Whether they are adjusted for corporate actions is NOT VERIFIED.

Index ETFs fed from the same broker API are the most defensible equity signal candidates.

---

## 1. Ranked shortlist

| Rank | Source | Cost | Terms posture for personal local use | Coverage for this app | Status |
|---|---|---|---|---|---|
| 1 | **Upstox API** (user's own account) | ₹0 for data ("All trading + data APIs are free of cost") | Moderator answer on the community forum: "You are permitted to utilize the data provided by the Upstox API for analysis purposes". The formal app terms are accepted at app creation and were NOT VERIFIED here | Daily/weekly/monthly candles since Jan 2000; minute and hour candles since Jan 2022. Fundamentals API (launched 2026-05-11) | REQUIRES CONFIGURATION |
| 2 | **Angel One SmartAPI** | ₹0 ("entirely free of cost, even for historical data") | Angel markets historical data "for backtesting purposes". The SmartAPI terms sit behind the sign-up flow and were NOT VERIFIED | NSE/BSE stocks and indices. History depth per request is NOT VERIFIED (8,000 candles per request is claimed in a secondary source) | REQUIRES CONFIGURATION |
| 3 | **ICICI Direct Breeze** | ₹0 (FAQ: "absolutely free of cost") | The FAQ names "backtesting historical data" as a feature. Formal terms NOT VERIFIED | NSE/BSE cash. Depth is disputed: 3 years on the ICICI page, 10 years in the SDK docs | REQUIRES CONFIGURATION |
| 4 | **Fyers API (Standard plan)** | ₹0 ("available to all our clients at absolutely zero fees") | Formal terms NOT VERIFIED | Standard plan: daily data for the last 5 years, intraday for the last 1 year. That is too short for robust out-of-sample daily tests, so use it only as a cross-check | REQUIRES CONFIGURATION |
| 5 | **Manual entry from company annual and quarterly reports** (fundamentals) | ₹0 | The user reads the company's published results and types in the figures with a citation. No automation, so no scraping issue | Fundamentals only; slow; complete provenance | VERIFIED as a pattern (the app already uses user-entered RBI figures) |
| — | MCA21 "View Public Documents" | about ₹100 per company (NOT VERIFIED; secondary source) | Government portal, login required, per-company fee | Audited statements of all companies, including unlisted ones | Optional and user-paid. Not an API key, but not free either |
| ✗ | Kite Connect (Zerodha) | **₹500/month per key** for data. The free Personal plan has **no** market data | Bars display "to the public at large" and "virtual/mock trading apps" | — | **Fails no-paid-keys** |
| ✗ | Dhan Data API | **₹499 + taxes/month**. The free-with-trades offer was "discontinued" | — | — | **Fails no-paid-keys** |
| ✗ | NSE website / NSE bhavcopy / NSE XBRL | ₹0 | ToU bans automated collection, storage, and simulation use | — | **BLOCKED** |
| ✗ | BSE website / BSE bhavcopy / BSE XBRL | ₹0 | Disclaimer bans "reproduction, redistribution or transmission" | — | **BLOCKED** for automation. Manual private use: NOT VERIFIED (see §2.2) |
| ✗ | yfinance (Yahoo) | ₹0 | Yahoo ToS bans automated collection "for any purpose without our express, prior permission" | — | **BLOCKED** |
| ✗ | jugaad-data, nsepy, nsetools, nsepython, india-xbrl-filings | ₹0 | All scrape NSE (and BSE) endpoints, so the NSE ToU applies | — | **BLOCKED** |
| ✗ | data.gov.in | ₹0, GODL licence (permissive) | Allowed | No company-level daily prices or fundamentals found. Only aggregate RBI market-cap tables (NOT VERIFIED that nothing more exists) | Not useful for this need |

**Recommendation:** adopt rank 1 (Upstox) as the single equity price adapter, with rank 2 or 3 as an optional cross-check source. Fundamentals come from rank 5 (manual entry). Upstox fundamentals may be shown as **UNOFFICIAL_MIRROR** quality and never used as the sole input to a decision. Everything runs **in local mode only**, never in the Vercel-hosted mode (see §5).

---

## 2. Official exchange sources

### 2.1 NSE: BLOCKED (re-confirmed today)

- **Source:** NSE Terms of Use, https://www.nseindia.com/static/nse-terms-of-use. Fetched directly 2026-10-15 (HTTP 200, 327,494 bytes) and the clauses extracted. **VERIFIED.**
  - "User is prohibited to conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting) on or in relation to our Website / Mobile Application."
  - Content "shall not be copied, modified, … stored (either in hardcopy or in an electronic retrieval system), … without prior written permission of NSE."
  - "shall not, in any form and manner, use or make the data or Content available on the Website / Mobile Application, for any gaming, virtual trading or simulation activities under any circumstances whatsoever."
- **Consequences:**
  - The free NSE bhavcopy CSVs (the "All Reports" page, https://www.nseindia.com/all-reports) and the XBRL financial-results pages (https://www.nseindia.com/companies-listing/corporate-filings-financial-results, https://www.nseindia.com/companies-listing/corporate-integrated-filing) are free to view.
  - They may **not** be automated or stored, and may not be used for simulation. A backtest is arguably a "simulation activity". Even a manual download that is then stored in SQLite conflicts with the "stored … in an electronic retrieval system" wording.
- **NSE Data & Analytics policy:** https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_Data_Sharing&Usage_Policy.pdf. Fetched 2026-10-15 (248,553 bytes). **VERIFIED.**
  - §7.3: "Trading Members, Subsidiaries and Subscribers shall not be permitted to redistribute any Market Data, except as agreed in the Relevant Agreement".
  - §7.4: "The Market Data shall not be provided to individuals/entities/platforms/apps/websites etc., engaging in online gaming, virtual trading or simulation, fantasy games, an activity of similar nature".
  - §7.1(a) bars using Market Data "to create any financial index, whether custom or otherwise … unless separately licensed".
  - **Two things follow:**
    - The "simulation" restriction flows **down to brokers** (trading members). So it is a residual interpretive risk even on the broker route (§3).
    - The engine should not build and publish a custom "index" from NSE data.
- **Paid NSE EOD data:** https://www.nseindia.com/static/market-data/eod-historical-data-subscription. The page fetch timed out. A secondary search summary says the files are per-site, per-medium annual licences, with requests to marketdata@nse.co.in. The March 2026 domestic pricing PDF (https://nsearchives.nseindia.com/web/mediaattachment/2026-03/NSE_Pricing_file_-_Domestic_clients_20260309171343.pdf) lists "EOD Corporate Data 5,00,000 (INR per year)". NOT VERIFIED from the PDF itself. The policy mentions possible "reduced fee arrangements or waivers for Non-Commercial Users", but defines those as academia, researchers and students. **An individual investor does not obviously qualify. This is paid, so it is out of scope.**
- **niftyindices.com** (index data, incl. TRI): terms read from a copy fetched 2026-10-15 at https://www.niftyindices.com/terms-of-use. VERIFIED from the fetched HTML:
  - "You may not conduct any systematic or automated data collection activities (including scraping…) … without our express written consent."
  - "The Site may be used only for lawful purposes by individuals for personal, non-commercial use only."
  - So index TRI may only be downloaded by hand for personal use. That is consistent with the existing registry's manual-entry pattern.

### 2.2 BSE: BLOCKED for automation; manual private use NOT VERIFIED

- **Bhavcopy page:** https://www.bseindia.com/markets/marketinfo/BhavCopy.aspx. The page is a JavaScript SPA; its text was read only via a search summary (NOT VERIFIED directly).
  - The current format is "Equity (UDiFF)". Older formats were discontinued from 08-Jul-2024 under Notice No 20240610-33 (NOT VERIFIED from the notice itself).
  - The file "will be made available for download after 4.45 p.m."
- **BSE disclaimer:** https://www.bseindia.com/static/about/disclaimer.htm. A direct fetch returned only the SPA shell (HTTP 200, 14,287 bytes, no clause text), and WebFetch got HTTP 403. The quotes below are via search summary, so **NOT VERIFIED directly**. They match the existing registry entry (§2.11 of `docs/data/source-registry.md`).
  - "Any reproduction, redistribution or transmission, for consideration or otherwise, of any such information contained in the Website is strictly prohibited and would constitute a breach of the laws of India."
  - "all proprietary rights, statutory or otherwise, in the information received by such person shall remain the exclusive property of BSE."
- **BSEPlus terms:** https://bseplus.bseindia.com/Terms_condition_Bseplus.htm, via search. "Unless otherwise specified, the Site is for your personal and non-commercial use." This is a subdomain, so whether it binds the main site is NOT VERIFIED.
- **No explicit anti-scraping clause was found for bseindia.com** (NOT VERIFIED; the full text was not retrieved). The robots.txt request returned the SPA HTML, not a robots file.
- **Assessment:**
  - Automated bhavcopy download plus local storage is not explicitly banned in the text seen, but "reproduction" is broad. Combined with the IT Act clause, it is **too uncertain for a real-money tool. Treat it as BLOCKED** until BSE's main-site terms are read in full or BSE gives written consent.
  - Ask BSE for written permission (contact NOT VERIFIED). Commercial licensing goes through BSE (international customers via Deutsche Börse, per https://www.mds.deutsche-boerse.com/mds-en/real-time-data/data-cooperations/corporate-data, via search).
- **BSE XBRL:** https://www.bseindia.com/corporates/Comp_Resultsnew.aspx and the XBRL listing (path via secondary source, NOT VERIFIED). Same terms as above.

### 2.3 Unofficial XBRL bulk tool

- **india-xbrl-filings:** https://github.com/dhananjaym182/india-xbrl-filings (via search). It describes itself as "Personal/educational use", "uses unofficial endpoints, isn't affiliated with NSE, BSE or SEBI".
- **BLOCKED for NSE** (ToU). BSE: as §2.2.

---

## 3. Broker APIs

**Common facts:**
- Every broker API requires the user to be that broker's **client**, which means KYC and a trading/demat account.
- Account-opening and annual maintenance charges were **NOT VERIFIED** for any broker. They are account costs, not API keys, but they are not zero by default.
- The SEBI retail-algo framework (circular SEBI/HO/MIRSD/MIRSD-PoD/P/2025/0000013, per secondary sources such as https://zerodha.com/z-connect/business-updates/explaining-the-latest-sebi-algo-trading-regulations) requires a **registered static IP for order placement**.
- This app places **no orders**, so the static-IP rule should not apply to read-only data. However:
  - one SmartAPI forum user reports that live data now needs a static IP (NOT VERIFIED);
  - Upstox's Analytics Token gives "read-only access to Portfolio and Account & Funds when used from a registered static IP" (https://upstox.com/developer/api-documentation/api-overview/, VERIFIED).

### 3.1 Zerodha Kite Connect: fails no-paid-keys

- https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/historical-data-and-live-market-data-payment-plan (**VERIFIED**):
  - Personal API: "It does not include live market data or historical data."
  - Paid: "access to live market data and historical data at no additional cost. This plan costs ₹500 per month per API key."
- Terms, https://kite.trade/terms/ (**VERIFIED**):
  - "live market data obtained via Kite Connect cannot be displayed to the public at large";
  - no use "for virtual/mock trading apps, trading related games";
  - no "Scrape, build databases, or otherwise create permanent copies of such content, or keep cached copies with the intent of redistributing".
  - Personal use is explicitly contemplated: "a private interface exclusively for customising personal trading and investment experience".
- https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/can-i-use-historical-and-live-data-taken-from-kite-connect-api-on-other-platforms (**VERIFIED**): "you cannot display data from Kite Connect APIs on other platforms, as this violates the exchange's data vending policies."
- **Verdict:** the terms fit personal local use well, but it costs ₹500/month. **Excluded** under the no-paid-keys rule. It becomes rank 1 if the user accepts the cost: the Personal API's explicit personal-use wording is the clearest terms language of any broker.

### 3.2 Upstox: rank 1

- **Pricing:** https://upstox.com/trading-api/ (**VERIFIED**): "₹0 Free access to trading & market data APIs" and "All trading + data APIs are free of cost."
  - The ₹10/order promotional note says "Valid till 30th September 2026". That is irrelevant here, because the app places no orders.
  - A secondary search summary says "Upstox Plus" gates expired-instrument history and an enhanced WebSocket tier (NOT VERIFIED). Neither is needed for daily equity candles.
- **History depth:** https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/ (**VERIFIED**):
  - Days/Weeks/Months "Available from January, 2000";
  - Minutes/Hours "Available from January, 2022";
  - one request covers at most "1 decade" for days;
  - "Authorization: Bearer {your_access_token}".
  - **Corporate-action adjustment is not documented (NOT VERIFIED).**
- **Use terms:**
  - Community moderator answer (via search, https://community.upstox.com/t/upstox-api-legal-or-not/3772 and https://community.upstox.com/t/api-usage-clarification/13250; NOT VERIFIED directly): "You are permitted to utilize the data provided by the Upstox API for analysis purposes".
  - Forum replies are not binding terms. The formal T&C ticked at app creation was **NOT VERIFIED**.
- **Fundamentals:** announcement https://upstox.com/developer/api-documentation/announcements/company-fundamentals-api/ (**VERIFIED**: "Effective Date: May 11, 2026"). It has 8 endpoints by ISIN (profile, balance sheet, cash flow, income statement, shareholding, key ratios, corporate actions, competitors).
  - The income statement page (https://upstox.com/developer/api-documentation/get-income-statement/, **VERIFIED**) says values are "in Indian Rupees (Crore)", and the example shows 4 periods.
  - **The data vendor, plan requirement and history depth are not disclosed** (VERIFIED as absent from the page).
  - **Consequence:** these values are not authoritative. Tag them `UNOFFICIAL_MIRROR` and use them only to cross-check manually entered figures.
  - **The corporate-actions endpoint is the most valuable part.** It could supply split and dividend events for total-return reconstruction, but its completeness is NOT VERIFIED.

### 3.3 Angel One SmartAPI: rank 2

- **FAQ:** https://smartapi.angelbroking.com/faq. A direct fetch returned an empty shell. Via search (NOT VERIFIED directly): "this service is entirely free of cost, even for historical data."
- **Release note:** https://smartapi.angelone.in/smartapi/forum/topic/4012/release-note-free-historical-data-access-for-indices-nse-nfo-bse-bfo-mcx-and-cds-with-smartapi (**VERIFIED**): historical data for "NSE indices, BSE indices, BSE stocks … It's all available for FREE!". The post date is not shown.
- **Introduction page:** https://www.angelone.in/knowledge-center/smartapi/detailed-introduction-to-smartapi (via search): "We give you Historical Data for backtesting purposes, again completely FREE OF COST."
  - **This is the most explicit broker statement that personal backtesting is a sanctioned use.** It directly mitigates the "simulation" interpretive risk in NSE policy §7.4.
- **Terms:** not publicly indexed (behind sign-up). NOT VERIFIED.
- **Rule change:** from 1 Apr 2026 there are static-IP rules for API order execution (https://www.angelone.in/news/market-updates/what-s-changing-in-angel-one-s-smartapi-access-from-april-1-2026, via search).

### 3.4 ICICI Direct Breeze: rank 3

- **Charges FAQ:** https://www.icicidirect.com/faqs/fno/are-there-any-charges-for-accessing-historical-data-and-using-other-features-of-breeze-api (**VERIFIED**): "with Breeze API you get access to all the features like backtesting historical data, fetching live data via websockets etc absolutely free of cost".
- **Depth:** 3 years on the ICICI page, 10 years in the SDK docs (https://github.com/Idirect-Tech/Breeze-Python-SDK). Via search, so **NOT VERIFIED**. Maximum 1,000 candles per request.

### 3.5 Fyers: rank 4 (cross-check only)

- **Cost:** https://support.fyers.in/portal/en/kb/articles/do-i-need-to-pay-for-datafeeds (**VERIFIED**): "This is available to all our clients at absolutely zero fees."
- **Plan limits:** https://support.fyers.in/portal/en/kb/articles/what-are-the-fyers-api-rate-limits-for-standard-and-prime-plans (**VERIFIED**):
  - Standard: daily "Last 5 years", intraday "Last 1 year"; limits of 5 req/s, 50/min, 5,000/day.
  - Prime: "Entire available history, 20+ years". The Prime price is not stated.

### 3.6 Dhan: fails no-paid-keys

- **Pricing:** https://dhanhq.co/trading-apis (**VERIFIED**): "₹499 Real-time Market Feed & Historical Data across exchanges".
- **Free-with-trades offer:** https://dhan.co/support/platforms/dhanhq-api/is-the-dhanhq-data-api-subscription-free-if-i-execute-a-minimum-number-of-trades-every-month/ (**VERIFIED**): "The promotional offer … has been discontinued. The Data API is currently available at ₹499 + applicable taxes per month."

---

## 4. Regulators, government and unofficial libraries

### 4.1 Regulators and government

| Source | Finding | Status |
|---|---|---|
| **SEBI** (https://www.sebi.gov.in/website-policy.html) | "Material featured on this Website may be reproduced free of charge after taking proper permission by sending a mail to us." Nothing on automated access. SEBI does not publish per-company prices or fundamentals; its corporate-filings index (https://www.sebi.gov.in/curation/corporate_filings.html) points to the exchanges | VERIFIED. Not a price or fundamentals source |
| **MCA21** View Public Documents | About ₹100 per company and login required (secondary: https://taxroutine.com/how-to-download-public-documents-in-mca21-portal/). The MCA page itself returned HTTP 403 to WebFetch. AOC-4 XBRL filings contain audited statements | NOT VERIFIED (fee). Optional and user-paid. Manual only |
| **data.gov.in** (GODL, https://jk.data.gov.in/godl) | Permissive: "use, adapt, publish … for all lawful commercial and non-commercial purposes", with attribution (via search). No company-level daily price or fundamentals dataset was found. RBI aggregate market-cap tables exist (seen via the third-party mirror https://dataful.in/datasets/17853/) | Licence via search, NOT VERIFIED directly. **Not useful** for single-stock or ETF signals |

### 4.2 Unofficial libraries

| Library | What it does | Terms risk | Status |
|---|---|---|---|
| **yfinance** (https://github.com/ranaroussi/yfinance) | Wraps Yahoo endpoints; README: "intended for research and educational purposes" and "the Yahoo! finance API is intended for personal use only" (VERIFIED) | **Yahoo ToS** (https://legal.yahoo.com/xw/en/yahoo/terms/otos/index.html, VERIFIED) bans attempts to "access or collect data … using any automated means … for any purpose without our express, prior permission". The README's "personal use" line does not override the ToS. Yahoo also re-licenses exchange data, so provenance cannot be traced to the publisher | **BLOCKED** |
| **jugaad-data** (https://github.com/jugaad-py/jugaad-data) | Scrapes NSE, niftyindices, RBI and AMFI. Licence "YOLO v2": "jugaad-data is in public domain" (VERIFIED) | Code licence is fine; **the data terms are not**: NSE and niftyindices ToU ban automated collection | **BLOCKED** (NSE parts) |
| **nsepy** (https://github.com/swapniljariwala/nsepy) | Unmaintained: "I am unable to maintain this library. NSE's old website is also getting deprecated…" (VERIFIED) | NSE ToU; also broken | **BLOCKED** |
| **nsetools** (https://github.com/vsjha18/nsetools) | Live NSE quotes; "intended only for educational and informational purposes"; "not affiliated with … the National Stock Exchange" (VERIFIED) | NSE ToU | **BLOCKED** |
| nsepython, NSEDownload, Getbhavcopy, bseindia (PyPI) | Same pattern of NSE/BSE scraping (not individually checked) | NSE ToU / BSE disclaimer | **BLOCKED** (NOT VERIFIED individually) |

---

## 5. Conditions that apply to any broker adapter (the binding rules applied to this source)

1. **Local mode only.**
   - Kite terms bar display "to the public at large". Zerodha says off-platform display "violates the exchange's data vending policies". NSE policy §7.3 bars redistribution.
   - The Vercel deployment is internet-reachable and the repo is public. **Broker-sourced prices must never be stored in Turso, rendered in the hosted mode, committed as fixtures, or exported**, and `licence_class=PERSONAL_USE_ONLY` must block export.
   - Synthetic fixtures only, as with AMFI.
2. **Credentials:**
   - The user's own API key and secret, referenced by environment-variable **name** (ADR-0007 pattern), never committed.
   - Upstox and Kite tokens expire daily. Upstox's Analytics Token is long-lived, so prefer it for read-only market data.
   - A missing or expired token makes the source status REQUIRES CONFIGURATION, and the supervisor **abstains**. It must never fall back to a blocked source.
3. **Provenance:**
   - Every candle carries `source_id=broker.upstox.hist_v3`, `publisher=Upstox (relaying NSE/BSE)`, `quality_status=BROKER_RELAY` (a proposed new enum value), the request URL template, `fetched_at`, and an `adjustment_basis` field.
   - `adjustment_basis` stays `UNKNOWN` until the adjustment behaviour is verified against a known split.
4. **No engine IO:** the adapter fetches and normalises to Decimal outside `engine/`. The engine sees only stored observations.
5. **Cross-check rule:** if a second broker (Angel or Breeze) is configured, close prices are compared on overlapping dates. A mismatch beyond a documented tolerance raises a data-quality flag. Even a split-adjusted versus unadjusted mismatch must flag, never be silently reconciled.

---

## 6. Gaps that block signals even on the best route (the supervisor must abstain)

| Gap | Why it matters for a backtest | What is known | Proposed engine rule |
|---|---|---|---|
| **Survivorship / delisted stocks** | Testing only today's listed stocks inflates returns (see RT-7 in `docs/research/return-target-feasibility.md`: Bessembinder 2018) | Whether Upstox, Angel or Breeze return history for **delisted** ISINs is NOT VERIFIED. Instrument masters normally list only active instruments | **Abstain on any cross-sectional single-stock signal** until delisted coverage is proven, or restrict the universe to index ETFs and the index itself |
| **Dividends / total return** | A price-only backtest understates buy-and-hold and mis-states the timing of signals | Broker candles are OHLCV. Corporate-action adjustment is undocumented (Upstox v3 doc, VERIFIED absent). The Upstox fundamentals corporate-actions endpoint exists, but completeness is NOT VERIFIED | Require an `adjustment_basis` of `SPLIT_ADJUSTED` plus a dividend series from a cited source, or abstain |
| **Benchmark TRI** | Out-of-sample comparison needs the Nifty TRI | niftyindices allows personal, non-commercial manual use only | Manual import with citation (the existing pattern) |
| **"Simulation" wording** | NSE ToU and NSE policy §7.4 mention simulation and virtual trading | Brokers explicitly market backtesting (Angel, ICICI), which suggests personal backtesting is within their licence. **No legal confirmation** | Record as an accepted residual risk in an ADR. Personal and local only. No paper-trading or "virtual portfolio" feature built on broker data |
| **Costs and tax in the backtest** | Required by the binding rules | Brokerage, STT and stamp-duty schedules are published by brokers and the government (not researched here) | Covered by a separate research task. Without a cost model, abstain |
| **Fundamentals point-in-time** | Using restated or later-published figures causes look-ahead bias | Upstox gives 4 example periods and no filing dates. Manual entry can record the filing date | A fundamental factor is only usable with a `published_on` date per figure |

**What this means for the user's aim (signals for equities):**
- Price-based **ETF / index** timing signals become testable once rank 1 is configured.
- **Single-stock buy/sell signals stay in "abstain" mode** until the survivorship and dividend gaps are closed. "No suitable candidate" is a valid output in the meantime.

---

## 7. Next verification steps (each is cheap and needs the user's account)

1. **Open the Upstox developer console, create an app, and record the exact T&C text** shown at the checkbox (store the quote and URL in the source registry). This turns Upstox's terms from NOT VERIFIED into VERIFIED.
2. **Run one probe** of `/v3/historical-candle/<NSE_EQ|ISIN>/days/1/...` around a known split date for a liquid stock and an ETF. This answers whether the data is split-adjusted. Record findings and a synthetic shape sample only.
3. **Probe one delisted ISIN** (known from a public delisting notice). This answers whether survivorship-free history is possible.
4. **Probe `/v2/fundamentals/{isin}/corporate-actions`** and compare it with the company's own dividend announcements for one stock. This tests completeness.
5. **Optional:** read Angel SmartAPI and Breeze terms at sign-up; email BSE about personal storage of the bhavcopy.

---

## 8. Sources (all accessed 2026-10-15)

**Exchanges and regulators**
- NSE ToU: https://www.nseindia.com/static/nse-terms-of-use (direct fetch)
- NSE Data Usage & Sharing Policy: https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_Data_Sharing&Usage_Policy.pdf (direct fetch)
- NSE paid EOD: https://www.nseindia.com/static/market-data/eod-historical-data-subscription (timed out; search summary)
- NSE pricing PDF: https://nsearchives.nseindia.com/web/mediaattachment/2026-03/NSE_Pricing_file_-_Domestic_clients_20260309171343.pdf (search summary)
- niftyindices ToU: https://www.niftyindices.com/terms-of-use (fetched copy)
- BSE disclaimer: https://www.bseindia.com/static/about/disclaimer.htm (SPA shell/403; search summary)
- BSEPlus terms: https://bseplus.bseindia.com/Terms_condition_Bseplus.htm (search summary)
- BSE bhavcopy: https://www.bseindia.com/markets/marketinfo/BhavCopy.aspx (search summary)
- SEBI website policy: https://www.sebi.gov.in/website-policy.html
- GODL: https://jk.data.gov.in/godl (search summary)
- MCA public documents fee: https://taxroutine.com/how-to-download-public-documents-in-mca21-portal/ (secondary)

**Brokers**
- Zerodha: https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/historical-data-and-live-market-data-payment-plan · https://kite.trade/terms/ · https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/can-i-use-historical-and-live-data-taken-from-kite-connect-api-on-other-platforms
- Upstox: https://upstox.com/trading-api/ · https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/ · https://upstox.com/developer/api-documentation/announcements/company-fundamentals-api/ · https://upstox.com/developer/api-documentation/get-income-statement/ · https://upstox.com/developer/api-documentation/api-overview/ · https://community.upstox.com/t/api-usage-clarification/13250
- Angel One: https://smartapi.angelbroking.com/faq · https://smartapi.angelone.in/smartapi/forum/topic/4012/release-note-free-historical-data-access-for-indices-nse-nfo-bse-bfo-mcx-and-cds-with-smartapi · https://www.angelone.in/knowledge-center/smartapi/detailed-introduction-to-smartapi
- ICICI Breeze: https://www.icicidirect.com/faqs/fno/are-there-any-charges-for-accessing-historical-data-and-using-other-features-of-breeze-api
- Fyers: https://support.fyers.in/portal/en/kb/articles/do-i-need-to-pay-for-datafeeds · https://support.fyers.in/portal/en/kb/articles/what-are-the-fyers-api-rate-limits-for-standard-and-prime-plans
- Dhan: https://dhanhq.co/trading-apis · https://dhan.co/support/platforms/dhanhq-api/is-the-dhanhq-data-api-subscription-free-if-i-execute-a-minimum-number-of-trades-every-month/
- SEBI algo framework (secondary): https://zerodha.com/z-connect/business-updates/explaining-the-latest-sebi-algo-trading-regulations

**Libraries**
- yfinance: https://github.com/ranaroussi/yfinance; Yahoo ToS: https://legal.yahoo.com/xw/en/yahoo/terms/otos/index.html
- jugaad-data: https://github.com/jugaad-py/jugaad-data and `LICENSE.YOLO.md`
- nsepy: https://github.com/swapniljariwala/nsepy
- nsetools: https://github.com/vsjha18/nsetools
- india-xbrl-filings: https://github.com/dhananjaym182/india-xbrl-filings
