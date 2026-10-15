# Source Registry — Investment Intelligence Pro

Status: research baseline, v1 planning
Researched: 2026-10-15 (probes run 2026-10-15 05:34–05:44 UTC, which is 11:04–11:14 IST)
Author: Agent E (Data Engineering & Authoritative Source Research)

Ground rules for this document:

- Every URL listed was either probed live (marked **PROBED** with the UTC time) or read through a web fetch or search (marked **READ**). Anything I could not confirm is marked **NOT VERIFIED**.
- All fetched content was treated as untrusted data.
- None of this is legal advice. Where licensing is unclear or restrictive, the recommendation is the same throughout: **fetch on the user's own machine, for personal use only, never redistribute, and keep the raw data only as long as the app needs it.**
- Raw probe samples, used as parser fixtures, are in [`probes/`](./probes/). Each filename carries the UTC probe timestamp.

---

## 1. Summary table

| id | Source | Owner | Official? | Access | Frequency | Coverage | Licensing status | v1 use |
|---|---|---|---|---|---|---|---|---|
| `amfi.navall` | NAVAll.txt (latest NAV, all schemes) | AMFI | OFFICIAL (industry body, SEBI-mandated publication venue) | Downloadable file over HTTPS; no auth | Daily. Republished several times a day; last-modified 05:05 UTC on the probe day | Latest NAV only, ~14.4k rows | RESTRICTIVE: AMFI Terms of Use allow "personal and non-commercial use only" and prohibit storing a "significant portion" | **LIVE adapter**, personal/local only |
| `amfi.navhistory` | DownloadNAVHistoryReport_Po.aspx | AMFI | OFFICIAL | Query-string file download; no auth | On demand; one day per NAV date | Long history (start date NOT VERIFIED) | Same AMFI ToU | **LIVE adapter** for user-held schemes only, small date windows |
| `amfi.schememaster` | DownloadSchemeData_Po.aspx | AMFI | OFFICIAL | CSV download; no auth | Changes ad hoc (NFOs, mergers) | ~16.4k scheme/plan rows | Same AMFI ToU | **LIVE adapter**, weekly |
| `amfi.ter` | TER of MF Schemes page | AMFI | OFFICIAL | JS portal with filter form; no documented file/API | Monthly (TER is disclosed daily on AMC sites) | — | Same AMFI ToU | **MANUAL import** (curated, dated) |
| `amfi.riskometer` / portfolio / AAUM | Risk-parameter, portfolio and AAUM disclosures | AMFI + each AMC | OFFICIAL | Portal pages, plus per-AMC Excel files in mixed formats | Monthly, fortnightly for debt portfolios | — | AMFI ToU; each AMC's own terms (NOT VERIFIED) | **MANUAL / deferred** |
| `mfapi.in` | api.mfapi.in | Independent operator | UNOFFICIAL wrapper around AMFI | JSON REST; no auth | Site claims 6 refreshes a day | Full per-scheme history (sample back to 2014) | No terms page linked ("Terms of Service" text has no link); upstream AMFI ToU still applies | **FALLBACK / cross-check only**; OFF by default |
| `captn3m0.historical-mf-data` | GitHub release `funds.db.zst` | Independent | UNOFFICIAL mirror | GitHub release asset, ~379 MB | Daily release (v2026.10.15) | Full history | No repo licence (GitHub API `license: null`) | **NOT for v1** (bulk; unclear licence) |
| `sebi.regs` | MF Regulations 2026, Master Circular 2026-03-20, circulars | SEBI | OFFICIAL | HTML/PDF documents | Ad hoc | — | Public regulatory text | **CURATED rules** (cited) |
| `rbi.home.rates` | RBI home page "Current Rates" | RBI | OFFICIAL | HTML; blocks non-browser clients (HTTP 418) | Daily, or per auction or policy event | Snapshot only | RBI disclaimer prohibits "caching" and framing without permission | **MANUAL** (policy rates are event-driven) |
| `rbi.pr.tbill` | T-bill auction result press releases | RBI | OFFICIAL | HTML press release (+ PDF) | Weekly (Wednesday auction) | Archive of press releases | Same RBI disclaimer | **SEMI-LIVE**: user-triggered, single-page fetch, personal use; else manual |
| `rbi.dbie` | Database on Indian Economy | RBI | OFFICIAL | SPA portal; Excel/CSV/PDF download by hand; no documented public API | Series-dependent | Long history | No DBIE terms page found; third-party registry cites "use … for research work with courtesy to DBIE, RBI" (NOT VERIFIED on rbi.org.in) | **MANUAL import** |
| `rbi.retail_direct` | RBI Retail Direct | RBI (CCIL operated) | OFFICIAL | Login portal | — | — | Portal-only | **NOT used** |
| `fbil` | T-bill curve, MIBOR, G-sec valuation | FBIL | OFFICIAL benchmark administrator | Angular SPA with reCAPTCHA; no public API | Daily | — | **FEE-LIABLE**: usage fee for MIBOR, T-Bill curve and others; redistribution licence required | **BLOCKED** (needs a licence) |
| `ccil.marketwatch` | NDS-OM Market Watch | CCIL | OFFICIAL | HTML portal ("delayed time snapshot") | Intraday, delayed | Same-day | Data Sharing Policy (Oct-2025): non-commercial use allowed, "discouraged from extracting" the data; commercial use forbidden without a Data Agreement | **MANUAL / BLOCKED for automation** |
| `nse.*` | Holidays, debt segment, corporate actions | NSE | OFFICIAL | Undocumented JSON (`/api/...`) behind the website | Varies | — | **PROHIBITED**: ToU bans "systematic or automated data collection activities (including scraping…)" | **BLOCKED** for automation; holidays via **manual curation** |
| `bse.*` | Market data, corporate actions | BSE | OFFICIAL | Website | — | — | Disclaimer prohibits "reproduction, redistribution or transmission" | **BLOCKED** |
| `mospi.cpi` | CPI API (api.mospi.gov.in) | MoSPI / NSO | OFFICIAL | REST JSON/CSV; sign-up plus 15-minute bearer token; unauthenticated calls return the first 10 records only | Monthly, 12th at 16:00 IST | Base 2012 from Jan-2013; base 2024 from Jan-2026 | No data-licence text found (code repo is MIT) — NOT VERIFIED | **LIVE adapter (REQUIRES CONFIGURATION: `IIP_MOSPI_TOKEN`, or `IIP_MOSPI_USER` + `IIP_MOSPI_PASSWORD`)**; IMPLEMENTED, NOT VERIFIED (no authenticated call yet); base-2024 retrieval NOT VERIFIED |
| `cra.*` | CRISIL / ICRA / CARE / India Ratings rating actions | CRAs | OFFICIAL (SEBI-registered) | HTML/PDF press releases | Ad hoc | — | CRISIL: no copying, reproduction or redistribution without written consent. Others NOT VERIFIED | **MANUAL** (user enters rating + link) |
| `dicgc` | Deposit insurance limit | DICGC (RBI subsidiary) | OFFICIAL | HTML FAQ | Rare (statutory) | — | Public information | **CURATED constant** with citation |
| `bank.fd` | Bank FD card rates | Each bank | OFFICIAL per bank | Each bank's website; **no central API** | Ad hoc | — | Per-bank terms | **MANUAL** (user enters own FD terms, and card-rate tables by tenure bucket for premature-exit scenarios) |
| `amc.factsheet` | Scheme monthly factsheet (duration, YTM, TER/BER, credit profile) | Each AMC | OFFICIAL per AMC | PDF/HTML on each AMC's website; no central API | Monthly (portfolio as on month-end) | Per scheme | Per-AMC terms; NOT VERIFIED | **MANUAL** (user enters figures + factsheet URL; never scraped; stale after 45 days) |
| `rbi.wadtdr` | Weighted average domestic term deposit rate | RBI | OFFICIAL | Monthly press release + DBIE | Monthly (about the last working day) | — | RBI disclaimer | **MANUAL** reference series |
| `mof.smallsavings` | Small-savings rates (PPF, SCSS, NSC…) | MoF DEA (Budget Division); DoP order | OFFICIAL | PDF Office Memorandum + DoP SB Order (scanned PDF) | Quarterly (end of the preceding quarter) | — | Government notification | **CURATED table** with OM citation |
| `itd.tax` | Income-tax Act 2025, rates and rules | CBDT / Income Tax Department | OFFICIAL | HTML/PDF | Yearly (Finance Act) + amendments | — | Government text | **CURATED versioned rule set** |
| `calendar.*` | NSE trading holidays, RBI holidays | NSE / RBI | OFFICIAL | NSE: undocumented JSON; RBI: form-driven page | Yearly + ad hoc | — | NSE ToU (above); RBI disclaimer | **MANUAL curated calendar** |

---

## 2. Detailed source sections

### 2.1 AMFI — NAVAll.txt (`amfi.navall`)

- **URL:** `https://www.amfiindia.com/spages/NAVAll.txt` → **HTTP 302** → `https://portal.amfiindia.com/spages/NAVAll.txt`. The adapter must follow the redirect and should pin the final host.
- **PROBED 2026-10-15T05:34:19Z.** Response headers: `HTTP/2 200`, `content-type: text/plain`, `content-length: 1520901`, `last-modified: Thu, 15 Oct 2026 05:05:03 GMT`, `etag: "dbb2bbbc625cdd1:0"`. Conditional GET using `If-None-Match` / `If-Modified-Since` is possible; whether the server returns a 304 is NOT VERIFIED.
- **Encoding:** UTF-8 with CRLF line endings. Non-ASCII characters appear in group headers, e.g. `Children’s` (U+2019).
- **Header line (verbatim, 8 fields, `;`-delimited):**
  ```
  Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date
  ```
- **Sample rows (verbatim):**
  ```
  135762;INFZ11K01WO4;-;Axis Children's Fund;Direct Plan;Growth Option;20.2971;14-Oct-2026
  128629;INFZ12KA1IZ1;-;HDFC Banking and PSU Debt Fund;Direct Plan;Growth Option;25.9504;14-Oct-2026
  123689;INFZ15K01KI2;INFZ15K01KJ0;Kotak Banking and PSU Debt Fund;Direct Plan;Annual Dividend;11.9827;15-Sep-2017
  ```
- **Structure:** the file is not a flat CSV. Data rows sit under nested group-header lines:
  - a scheme-type and category line such as `Open Ended Schemes(Debt Scheme - Banking and PSU Fund)`;
  - then an AMC line such as `HDFC Mutual Fund`;
  - separator lines are a single space (`" \r\n"`).

  A data row is a line containing `;`. The other lines are headers that set the context.
- **Profile of the full file at probe time:**
  - 18,110 lines and 14,376 data rows; every row had exactly 7 semicolons.
  - 103 category lines. Top-level types: `Open Ended Schemes`, `Close Ended Schemes`, `Interval Fund Schemes`.
  - **Only 8,710 rows carried the latest date (14-Oct-2026). 5,397 rows carry dates before 2026, as old as 2017** (matured or dormant plans). The NAV date must never be taken to be "today".
  - `Plan` was empty in 5,707 rows. Option text is free-form (e.g. "Payout of Income Distribution cum capital withdrawal option- Direct").
  - Empty ISIN is written as `-`; 799 rows have `-` in ISIN-1.
  - NAV decimal places vary by scheme (4dp: 11,089; 2dp: 1,086; 3dp: 1,001; 0dp: 702; 8dp: 389; 7dp: 54). **Parse as a decimal string and never as a float.**
  - No non-numeric NAVs at probe time. Historically "N.A." values have been seen (NOT VERIFIED today), so the parser must reject non-numeric values row by row.
- **Format drift risk:** the two columns `Plan;Option` appear to be a later addition. My understanding is that the older format had six fields without them (NOT VERIFIED by probe). The parser must check the exact header and **fail closed** (status `SCHEMA_CHANGED`) if it differs.
- **Frequency and timing:** SEBI requires NAVs on the AMFI site by **11:00 PM IST on each business day (T)**. Fund-of-funds and schemes holding ≥80% overseas assets have until **10:00 AM IST on T+1** (SEBI investor FAQ; scheme documents cite Para 12.26 of the 2024 Master Circular and its 2026 successor; exact 2026 clause number NOT VERIFIED). The file is re-generated several times a day; `last-modified` was 10:35 IST on the probe day while still carrying T-1 (14-Oct) NAVs.
- **Freshness semantics:**
  - `observation_date` = the row's `Date`, which is the NAV date.
  - `publication_time` = the HTTP `last-modified` time, file level only.
  - The NAV for date D becomes available on the evening of D, or the morning of D+1 for FoF and overseas schemes.
- **Historical coverage:** latest NAV only. Use `amfi.navhistory` for history.
- **Access:** anonymous HTTPS. robots.txt (PROBED) disallows only `/admin/`, `/login/` and `/search/`.
- **Rate limits:** none documented. Policy: fetch at most once per run, at most a few runs a day, with `If-None-Match`.
- **Licensing — READ `https://www.amfiindia.com/terms-of-use`:** the terms grant a "non-exclusive, personal, non-transferable, non-sublicensable, limited and revocable right to access, use and display this Site … for your personal and non-commercial use only". They also say: "You may not publicly perform, publicly display, transmit, publish … or create derivative works … You shall not store electronically any significant portion of any part of the Site."
  - **Consequence:** personal, local use only, with no redistribution and no hosted multi-user service.
  - Keep only the rows for schemes the user holds or watches. Do not archive the whole daily file indefinitely.
  - Treat any hosted or commercial deployment as **REQUIRES LICENCE / WRITTEN PERMISSION**.
- **Reliability:** single host; the format has changed before; the host redirects; there are no checksums.
- **Fixture:** `probes/amfi_navall_head_20261015T053419Z.txt` (first ~8 KB, CRLF preserved).

### 2.2 AMFI — NAV history report (`amfi.navhistory`)

- **URL pattern** (PROBED 2026-10-15T05:34:48Z):
  `https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx?mf=<AMFI fund-house id>&tp=<1|2|3>&frmdt=DD-Mon-YYYY&todt=DD-Mon-YYYY`
  - With `mf=9&tp=1&frmdt=13-Oct-2026&todt=14-Oct-2026`: `HTTP/2 200`, `content-type: text/plain`, `content-disposition: inline; filename=NAVHistoryReport151026.txt`, 82,977 bytes, UTF-8, CRLF.
  - `mf=9` returned HDFC Mutual Fund. The `mf` ids are AMFI-internal, and the mapping table is NOT VERIFIED.
  - `tp=1` returned open-ended schemes. My understanding is that 2 = close-ended and 3 = interval (NOT VERIFIED).
- **Header line (verbatim). The column order differs from NAVAll:**
  ```
  Scheme Code;NAV Name;Plan;Option;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Net Asset Value;Date
  ```
- **Sample rows:**
  ```
  119018;HDFC Large Cap Fund - Growth Option - Direct Plan;Direct Plan;Growth Option;INFZ12K01YV3;;1393.087;13-Oct-2026
  119018;HDFC Large Cap Fund - Growth Option - Direct Plan;Direct Plan;Growth Option;INFZ12K01YV3;;1385.402;14-Oct-2026
  ```
- **Differences from NAVAll:**
  - An empty ISIN is an empty field here, not `-`.
  - Blank separator lines are truly empty.
  - Group headers have spaces inside the brackets: `Open Ended Schemes ( Equity Scheme - Multi Cap Fund )`.
  - The NAV value matched NAVAll for 119018 on 14-Oct-2026 (1385.402).
  - **Separate parsers are needed**, each keyed on its exact header.
- **Historical coverage:** multi-year. The earliest available date and the maximum date range per request are NOT VERIFIED. Keep requests to a small window (≤ 90 days) and only for fund houses the user holds.
- **Licensing:** same AMFI ToU. Backfill only what the user needs.
- **Fixture:** `probes/amfi_navhistory_mf9_tp1_13to14Oct2026_20261015T053448Z.txt`.

### 2.3 AMFI — Scheme master (`amfi.schememaster`)

- **URL:** `https://portal.amfiindia.com/DownloadSchemeData_Po.aspx?mf=0`. PROBED 2026-10-15T05:43:36Z: `HTTP/2 200`, `content-type: text/csv`, `content-disposition: attachment;filename=SchemeData1510261113SS.csv`, `content-length: 4108464`. The server **ignored the Range header** and sent the full 4.1 MB.
- **Header line (verbatim):**
  ```
  AMC,Code,Scheme Name,Scheme Type,Scheme Category,Scheme NAV Name,Scheme Minimum Amount,Launch Date, Closure Date,ISIN Div Payout/ ISIN GrowthISIN Div Reinvestment
  ```
- **Quirks:**
  - The two ISIN columns are **glued together with no delimiter**. Field length counts were 12 (10,970 rows), 24 (4,042), 0 (1,392), 13 (34) and 20 (9). The adapter must split on the ISIN pattern `IN[A-Z0-9]{9}[0-9]` and flag the malformed 13- and 20-character values.
  - `Closure Date` has a leading space.
  - `Scheme Minimum Amount` is free text in 9,462 of 16,452 rows (e.g. "Rs 5000 and in multiples of Re. 1 thereafter").
  - Legacy categories such as `Income` and `Growth` appear for old schemes alongside SEBI-2017-style categories.
- **Use:** join on `Code` = AMFI scheme code, to get scheme type, category, plan and ISIN mapping. Refresh weekly.
- **Fixture:** `probes/amfi_schemedata_mf0_head_20261015T054336Z.csv`.

### 2.4 AMFI — TER, riskometer, portfolio and AAUM disclosures

- **TER:** `https://www.amfiindia.com/ter-of-mf-schemes` (READ). This is a JS filter form (financial year, month, fund type, category, MF); no file or API endpoint was found. The page's disclaimer reflects the **SEBI (Mutual Funds) Regulations, 2026**, under which TER is split into:
  - Base Expense Ratio (Reg. 66(7));
  - brokerage (Reg. 66(9));
  - transaction cost (Reg. 66(10));
  - statutory levies including GST.

  The brokerage, transaction-cost and levy components are "annualized, cumulative daily average … during the reference period", reset monthly.

  **The data model must store TER as components plus a total, with the regulation version.** A pre-April-2026 TER and a post-April-2026 TER are not directly comparable.
- **Riskometer and Potential Risk Class:** SEBI requires the riskometer to be evaluated monthly and disclosed on the AMC and AMFI websites along with the portfolio. The rule sits in Para 17.4 of the 2024 Master Circular; its 2026 Master Circular location is NOT VERIFIED. There are six levels, Low → Very High. Debt schemes also carry a PRC matrix. AMFI has a "Disclosure of Risk Parameters" link; the endpoint format is NOT VERIFIED.
- **Portfolio disclosure:** monthly for all schemes and fortnightly for debt schemes, within 10 and 5 days respectively. Files are spreadsheets on each AMC's site with formats that vary by AMC. **Not suitable for v1 automation.**
- **AAUM / monthly data:** a SEBI circular dated 2026-05-19 changed the Monthly Cumulative Report format from June 2026 (clause 6.20 of the 2026 Master Circular, READ via search). Endpoints NOT VERIFIED.

### 2.5 mfapi.in (`mfapi.in`) — UNOFFICIAL

- **Endpoints** (READ from `https://www.mfapi.in/docs/`): `/mf/search?q=`, `/mf?limit=&offset=`, `/mf/{code}`, `/mf/{code}?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD`, `/mf/{code}/latest`.
- **PROBED 2026-10-15T05:34:35Z** `https://api.mfapi.in/mf/128629`: `HTTP/2 200`, `application/json`, 118,525 bytes, 3,031 data points (latest 14-10-2026, earliest 26-03-2014). Response shape:
  ```json
  {"meta":{"fund_house":"HDFC Mutual Fund","scheme_type":"Open Ended Schemes","scheme_category":"Debt Scheme - Banking and PSU Fund","scheme_code":128629,"scheme_name":"HDFC Banking and PSU Debt Fund - Direct Plan - Growth Option","isin_growth":"INFZ12KA1IZ1","isin_div_reinvestment":null},
   "data":[{"date":"14-10-2026","nav":"25.95040"}, ...],"status":"SUCCESS"}
  ```
- **Differences from AMFI:**
  - Dates are `DD-MM-YYYY`, not `DD-Mon-YYYY`.
  - NAV is **right-padded to 5 dp** (`25.95040` against AMFI `25.9504`).
  - Data is newest first.
  - Normalise both sides before any cross-check comparison.
- **Update cadence (site claim, not verified):** "Updated 6x daily (10:05 AM, 2:05 PM, 6:05 PM, 9:05 PM, 3:09 AM, 5:05 AM IST)".
- **Rate limits are contradictory:** the home page says "no rate limiting", while the docs say "The API implements rate limiting to ensure fair usage." Assume limits exist and cache.
- **Terms:** the footer mentions "Terms of Service" but no link was found. `api.mfapi.in/robots.txt` returned 404. Terms are **NOT VERIFIED**. The data originates from AMFI, so AMFI's ToU limits still apply downstream.
- **Fragility:** a single independent operator with no SLA. The response header `x-served-by-header: hl` hints at hosting details that are not documented.
- **Recommendation:** optional fallback and cross-check source, disabled by default. Every observation from it is tagged `quality_status=UNOFFICIAL_MIRROR`. It is never the sole source for a decision-critical value.
- **Fixtures:** `probes/mfapi_mf_128629_trimmed_20261015T053435Z.json` (trimmed; the note is inside the file), `probes/mfapi_mf_128629_latest_20261015T053435Z.json`.

### 2.6 captn3m0/historical-mf-data — UNOFFICIAL

- GitHub `captn3m0/historical-mf-data`, latest release `v2026.10.15` (2026-10-15T04:20:15Z) with one asset, `funds.db.zst` of 379,169,082 bytes (PROBED via GitHub API). Repo licence: `null`.
- Bulk download, no licence, and its origin is AMFI data, so AMFI ToU concerns apply. **Not for v1.**

### 2.7 SEBI (`sebi.regs`) — regulatory references to cite in curated rules

These are READ via sebi.gov.in search results; I fetched the listing pages but did not read the full PDFs.

- **SEBI (Mutual Funds) Regulations, 2026:** in force **1 April 2026**, replacing the 1996 Regulations; last amended 7 July 2026. Sources: `https://www.sebi.gov.in/legal/regulations/jan-2026/securities-and-exchange-board-of-india-mutual-funds-regulations-2026_99173.html` and the consolidated PDF `https://www.sebi.gov.in/sebi_data/attachdocs/jul-2026/1783933012694.pdf`.
- **Master Circular for Mutual Funds dated 20 March 2026:** supersedes the 27-Jun-2024 Master Circular.
- **Categorisation and Rationalisation circular dated 26 Feb 2026** (`https://www.sebi.gov.in/legal/circulars/feb-2026/categorization-and-rationalization-of-mutual-fund-schemes_99983.html`): consolidated as clause 3.7 of the 2026 Master Circular. This supersedes the 6-Oct-2017 circular SEBI/HO/IMD/DF3/CIR/P/2017/114. **The category taxonomy in v1 must be versioned**: pre-2026 and post-2026 category names may differ, and the specifics are NOT VERIFIED.
- **Fortnightly debt portfolio disclosure:** SEBI/HO/IMD/DF3/CIR/P/2020/130 (22-Jul-2020).
- **Riskometer:** the 2024 Master Circular Para 17.4 and SEBI/HO/IMD/PoD1/CIR/P/2024/150 (5-Nov-2024). Where these sit in the 2026 Master Circular is NOT VERIFIED.
- **robots.txt (PROBED):** disallows only js and css paths.
- SEBI text is public regulatory material. v1 stores citations (URL, circular number, date) in curated rule files and does not mirror the documents.

### 2.8 RBI — home page rates (`rbi.home.rates`), press releases (`rbi.pr.tbill`), DBIE (`rbi.dbie`)

- **Bot blocking:**
  - `https://www.rbi.org.in/robots.txt` with the default curl user agent returned **HTTP 418**; with a browser UA it returned an "Unauthorised Access" HTML page carrying a Support ID.
  - Pages load with a browser UA.
  - **This is a WAF that may block automated clients at any time. Treat any automated RBI fetch as fragile.**
- **Home page "Current Rates"** (PROBED 2026-10-15T05:42:20Z, browser UA), excerpt:
  - Policy Repo Rate 5.50%; SDF 5.25%; MSF 5.75%; Bank Rate 5.75%; Fixed Reverse Repo 3.35%; CRR 3.00%; SLR 18.00%.
  - T-bill cut-offs: 91d 5.7281%, 182d 6.2896%, 364d 6.4891% ("cut-off at the last auction").
  - G-sec yields "as on October 13, 2026".
  - FX reference rates "(As at 1.00pm of October 14, 2026) (Source : FBIL)".
  - **Note:** one secondary news source found during research claimed the repo rate was 5.25%. The official RBI page says 5.50%. This is exactly why v1 must use only official sources for policy values.
  - Fixture: `probes/rbi_homepage_current_rates_text_20261015T054220Z.txt`.
- **T-bill auction press releases** (PROBED 2026-10-15T05:40:05Z):
  - Listing: `https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx`. Titles are stable: "91-Day, 182-Day and 364-Day T-Bill Auction Result: Cut-off" (prid 63803) and "Treasury Bills: Full Auction Result" (prid 63804), both dated Oct 14, 2026.
  - Cut-off release (Press Release 2026-2027/1325): notified amount ₹8,000/8,000/7,000 crore; cut-off price and implied yield `98.5920 (YTM: 5.7281%)`, `96.9592 (YTM: 6.2896%)`, `93.9220 (YTM: 6.4891%)`.
  - Full release (2026-2027/1326): competitive bids (number and amount), weighted average price and yield (`WAY: 5.6964%` etc.), partial allotment %, and non-competitive bids.
  - Units: ₹ crore; prices per ₹100 face value. Yield convention: RBI labels the cut-off yield "YTM" and the weighted average "WAY". **The exact day-count / compounding convention is NOT VERIFIED.** Store the value with `convention="RBI_TBILL_IMPLICIT_YIELD_AS_PUBLISHED"` and do not recompute it.
  - Timing: auctions are on Wednesdays and results are released the same day (publication time NOT VERIFIED; capture `retrieved_at`).
  - Fixtures: `probes/rbi_pressrelease_tbill_{cutoff,full}_prid*_20261015T054005Z.html` (body-table excerpts).
- **Lending and deposit rates (WADTDR):** monthly press release "Lending and Deposit Rates of Scheduled Commercial Banks", usually on the last working day, covering the previous month. Per the release of 30-Sep-2026 (READ via search, not probed), WADTDR on fresh deposits was 5.67% for Aug-2026. Use as a manual reference series.
- **DBIE:** `https://data.rbi.org.in/DBIE/` (PROBED 200). It is an Angular SPA with no documented public API; downloads (Excel/CSV/PDF) are manual. The unofficial mirror `dbie.rbihub.in` (third-party scrape) is **not to be used**.
- **RBI disclaimer** (READ `https://www.rbi.org.in/Scripts/Disclaimer.aspx`): "Except as set forth below, caching and links to, and the framing of this Web Site or any of the contents are prohibited." Content is "as is". RBI "reserves all right to deny or restrict access … or to block access from a particular Internet address".
  - **Consequence:** no automated crawling. Fetch only on a user action, one page at a time, and store only the extracted figures with their citation.
- **RBI Retail Direct** (`https://rbiretaildirect.org.in/`, 301 PROBED): a login-gated investor portal. No public data API was found (NOT VERIFIED beyond the home page). Not used.
- **Weekly Statistical Supplement:** published weekly on rbi.org.in; format NOT VERIFIED and not probed. Deferred.

### 2.9 FBIL (`fbil`) — BLOCKED (licence)

- `https://www.fbil.org.in/` (PROBED 200): an Angular SPA that loads Google reCAPTCHA. robots.txt timed out (no response).
- **Licensing** (READ: FBIL Comprehensive Policy Document on Pricing of Benchmarks, 1-Jan-2020, and FBIL FAQ updated 30-Nov-2023):
  - "use of any of the following Benchmarks data will be subject to the payment of usage fee: a) MIBOR … h) T-Bills Curve …".
  - Redistribution requires a licence.
  - "Entities … displaying FBIL data will be charged" an annual fee per benchmark.
  - Fee amounts may have changed since 2020 (NOT VERIFIED).
- RBI has notified MIBOR and T-bill rates as "significant benchmarks".
- **v1: BLOCKED / REQUIRES LICENCE.** Use RBI T-bill auction cut-offs (`rbi.pr.tbill`) as the free official proxy and label them as auction yields, not curve values.

### 2.10 CCIL (`ccil.marketwatch`)

- `https://www.ccilindia.com/market-watch` has tabs for central G-secs, state G-secs, T-bills, when-issued and odd lot, labelled "Source: NDS-OM hosted at CCIL". robots.txt (PROBED) allows everything.
- **CCIL Data Sharing Policy (Oct-2025, READ, pdftotext):**
  - "Users of the Data on the CCIL website are allowed to use the Data for non-commercial purposes and discouraged from extracting the Data for any such arrangement using data streaming methods."
  - "Commercial usage of the Data is forbidden unless the same is specified under the terms of a Data Agreement".
  - Market Watch is a "Delayed time snapshot of all the trades reported on the Trade Repository".
  - Data used "shall be acknowledged and cited".
- The Trading Summary page says: "CCIL does not authorize commercial use of the data available in its website without written permission."
- **v1:** no automated extraction. A user may enter a G-sec price or yield manually with a CCIL citation.

### 2.11 NSE / BSE (`nse.*`, `bse.*`) — BLOCKED for automation

- **NSE Terms of Use** (READ via direct quote, `https://www.nseindia.com/static/nse-terms-of-use`):
  - "User is prohibited to conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting) on or in relation to our Website / Mobile Application."
  - Content shall not be "stored (either in hardcopy or in an electronic retrieval system) … without prior written permission of NSE."
  - Data may not be used "for any gaming, virtual trading or simulation activities". **This is directly relevant to any scenario or simulation feature.**
- NSE robots.txt (PROBED) says `Allow: /`, but the ToU governs.
- NSE commercial data is licensed through NSE Data & Analytics (Data Usage and Sharing Policy).
- **One-off reference probe:** `https://www.nseindia.com/api/holiday-master?type=trading` returned HTTP 200 JSON (34,022 bytes) at 2026-10-15T05:35:40Z.
  - Keys: `CBM, CD, CM, CMOT, COM, EGR, FO, IRD, MF, NDM, NTRP, SLBS`.
  - Row shape: `{"tradingDate":"26-Jan-2026","weekDay":"Monday","description":"Republic Day","morning_session":null,"evening_session":null,"Sr_no":2}`.
  - This undocumented endpoint is **not to be automated**. The trimmed fixture is kept only to document the shape.
- **BSE disclaimer** (READ via search, `bseindia.com/rgess/disclaimer.htm`; the main-site terms are NOT VERIFIED): "Any reproduction, redistribution or transmission, for consideration or otherwise, of any such information contained in the Website is strictly prohibited".
- **v1:** no exchange data adapters. Equity and ETF prices, if ever needed, require a licensed vendor (BLOCKED / REQUIRES CONFIGURATION). The trading calendar is curated by hand from the exchange's annual holiday circular, entering dates with a citation.

### 2.12 MoSPI CPI (`mospi.cpi`)

- **API platform:** `https://api.mospi.gov.in` (PROBED 200). User manual (READ): `https://api.mospi.gov.in/API/CPI%20API%20User%20Manual.pdf`.
  - Sign-up: `POST /api/users/usersignup`. The manual says "unique email which can be used only once".
  - Login: `POST /api/login` returns an "access token which is valid for 15 minutes". "Without access token the APIs will fetch only the first 10 records."
  - Endpoints in the manual are `getCPIIndex` (group and subgroup level, "from Jan 2013 onwards") and `getItemIndex` (from Jan 2014).
  - The current Swagger spec (`nso-india/esankhyiki-mcp`, `swagger/swagger_user_cpi.yaml`, server `https://api.mospi.gov.in/`) uses the paths **`/api/cpi/getCPIIndex`** and **`/api/cpi/getItemIndex`**, with `base_year` ∈ {2012, 2010, 2024}, `series` ∈ {Current, Back}, `year`, `month_code`, `state_code` (99 = All India), `sector_code`, `group_code`/`division_code`, `Format` ∈ {JSON, CSV}, `limit`, `page`, and `bearerAuth` in the `Authorization` header.
- **PROBED 2026-10-15T05:37:23Z (unauthenticated):** `GET /api/cpi/getCPIIndex?base_year=2012&series=Current&year=2025&month_code=12&state_code=99&Format=JSON` returned 10 records:
  ```json
  {"baseyear":"2012","year":2025,"month":"December","state":"All India","sector":"Rural","group":"Consumer Food Price","subgroup":"Consumer Food Price-Overall","index":"198.5","inflation":"-3.03","status":"F"}
  ```
  `status` "F" presumably means Final, against P for Provisional (NOT VERIFIED).
- **Base-2024 series:** CPI moved to base 2024=100 with the first release on **12-Feb-2026 at 16:00 IST** (Jan-2026 data; PIB). Every unauthenticated probe with `base_year=2024` (with and without month and state filters) and `base_year=2012, year=2026` returned `{"data":[],"msg":"No Data Found","statusCode":true}`.
  - **Retrieving base-2024 data through the API is NOT VERIFIED.** It may need auth, different filter codes (the 2024 base uses divisions under COICOP 2018) or it may not be populated yet.
  - The official human-facing source is `https://esankhyiki.mospi.gov.in/macroindicators?product=cpi` (PROBED 200, SPA).
- **Release calendar:** CPI is released on the 12th of each month at **16:00 IST**, or the next working day if the 12th is a holiday. The time moved from 17:30 in Nov-2024. The value is for the previous month; the latest month is provisional and is revised the following month.
- **Series break:** 2012=100 and 2024=100 are not comparable without a linking factor. **Store `base_year` on every observation and never splice series silently.**
- **Licence:** no data licence text found on the API site (NOT VERIFIED). The GitHub code is MIT-licensed, which covers code, not data. Treat as government open data for personal use, with citation.
- **Fixture:** `probes/mospi_cpi_getCPIIndex_base2012_2025-12_unauth10_20261015T053723Z.json`.

### 2.13 Credit rating agencies (`cra.*`)

- SEBI-registered CRAs (CRISIL Ratings, ICRA, CARE Ratings, India Ratings & Research, and others) publish rating rationales and press releases on their own websites. No central free API was found.
- **CRISIL Ratings** (READ via search: `https://www.crisilratings.com/en/home/website-terms-of-use.html` and `/disclaimer.html`): "None of the information available on the website may be copied, reproduced, presented, quoted, rearranged or further transmitted, disseminated, redistributed … without the prior written consent of Crisil Ratings". The disclaimer also covers extraction "by use of any generative artificial intelligence".
- **ICRA, CARE and India Ratings terms: NOT VERIFIED.** Assume similar restrictions.
- **v1:** the user manually enters an instrument's rating, the agency, the action date and the rationale URL. No scraping.

### 2.14 DICGC deposit insurance (`dicgc`)

- **READ** `https://www.dicgc.org.in/FAQs`:
  - "Each depositor in a bank is insured upto a maximum of ₹ 5,00,000 (Rupees Five Lakhs)".
  - "The DICGC insures principal and interest upto a maximum amount of ₹ 5 lakh."
  - Deposits held "in the same capacity and in the same right" are aggregated across all branches of the same bank. Deposits held in different capacities are insured separately.
- **Effective date:** not stated on the FAQ page. The ₹5 lakh limit is widely reported as effective 4-Feb-2020; that date is NOT VERIFIED on dicgc.org.in in this session.
- Secondary reports (2025–26) say an increase was under consideration. No change was found as of 2026-10-15.
- **v1:** a curated constant `DICGC_LIMIT_INR = 500000` with the citation and a `valid_from` that is NOT VERIFIED. Re-verify quarterly. Small finance banks, RRBs, cooperative banks and foreign banks in India are covered according to secondary sources; check DICGC's insured-bank list for coverage of a specific bank.

### 2.15 Bank FD rates (`bank.fd`)

- **There is no central API or official aggregated feed of bank FD card rates.** Each bank publishes its own rates on its website, with formats that change often and differ by tenor, amount slab and senior-citizen status.
- The RBI home page shows only a range ("Term Deposit Rate > 1 Year : 6.00% - 6.75%"), and RBI's WADTDR is a weighted average, not a card rate.
- **v1:** the user enters their own FD (bank, rate, compounding, tenor, start date) with an optional bank-page URL and retrieval date. Aggregator sites (UNOFFICIAL) are not used.

### 2.16 Small-savings rates (`mof.smallsavings`)

- **Issuer:** Ministry of Finance, DEA (Budget Division), by quarterly Office Memorandum F.No. 1/4/2019-NS. The Department of Posts implements it through an SB Order.
- **PROBED 2026-10-15T05:43:05Z:** `https://utilities.cept.gov.in/dop/pdfbind.ashx?id=15533` (Department of Posts server), `application/pdf`, 1,063,984 bytes. This is **SB Order No. 12/2026 dated 30.09.2026**: "rates of interest on various Small Savings Schemes … for the third quarter of FY 2026-27 (starting from 1st October, 2026 and ending on 31st December, 2026) shall remain unchanged from those notified for the second quarter".
- **The Q3 OM does not restate the rate table.** The rate values must be traced back to the last OM that stated them.
- Values consistently reported for Oct–Dec 2026 (secondary sources: TaxGuru, Business Standard): SB 4.0%, TD 1y/2y/3y/5y 6.9/7.0/7.1/7.5%, RD 6.7%, SCSS 8.2%, MIS 7.4%, NSC 7.7%, PPF 7.1%, KVP 7.5% (115 months), SSY 8.2%.
  - **These values are NOT VERIFIED against the primary OM in this session.** Before shipping, a curator must confirm them from the original DEA OM (dea.gov.in) or from the India Post / NSI page.
- The PDF is scanned with OCR noise (e.g. "11412019-NS", "3S.0S,*CI28"), so it is **not machine-parseable reliably → manual curation only.**
- Publication time: the last working day of the preceding quarter, typically the evening.
- **Fixture:** `probes/dop_sborder_12-2026_smallsavings_q3fy27_20261015T054305Z.txt`.

### 2.17 Income-tax (`itd.tax`)

- **VERIFIED (READ `https://www.incometax.gov.in/iec/foportal/help/all-topics/e-filing-services/objective-and-scope-new-act`):** the Income-tax Act, 2025 came into force on **1 April 2026**: "The 1961 Act stands repealed on the 01.04.2026."
  - "Tax year" (a 12-month financial year) replaces "previous year" and "assessment year".
  - Pending matters from before 1-Apr-2026 continue under the 1961 Act (repeal and savings). Returns for FY 2025-26 (AY 2026-27) are still under the 1961 Act.
- **Rules:** Income-tax Rules, 2026, issued under section 533 and in force from 1-Apr-2026. The latest amendment seen is Notification 134/2026 (8-Oct-2026, Sixth Amendment Rules). Read via search on incometax.gov.in pages; not probed directly.
- **Where rate tables live:**
  - Slabs and rates for each tax year are set by the Finance Act for that year and the Act's schedules. They are published on incometax.gov.in under Acts and Rules and in the Union Budget documents.
  - The exact URL of an official machine-readable rate table was **NOT VERIFIED**; none is known to exist.
  - Secondary sources report that the new-regime slabs for TY 2026-27 (nil up to ₹4 lakh … 30% above ₹24 lakh; ₹75,000 standard deduction) are unchanged from FY 2025-26. This is NOT VERIFIED from the primary source.
- **v1:** a curated, versioned rule set keyed by `(statute: "ITA1961" | "ITA2025", tax_year, regime)`. Each rule row carries its section reference and source URL. Capital-gains rules for MF and debt (holding periods, rates, post-2023 debt-fund treatment) must cite the specific section under each Act.
  - Transactions on or before 31-Mar-2026 are taxed under the 1961 Act. Tax year 2026-27 onwards falls under the 2025 Act.

### 2.18 Trading and settlement calendars (`calendar.*`)

- **NSE:** the holiday list exists as undocumented JSON (see 2.11) and as annual circulars. Automation is barred by the ToU, so dates are entered by hand from NSE's official annual holiday circular with a citation. The JSON probe shows that segments have different holiday sets (e.g. `IRD` and `CD` had 24 entries against 20 for `CM`), so **the calendar must be per segment**: MF NAV business days follow the CM/MF list, while money-market and G-sec days follow the RBI/FBIL calendars.
- **RBI holidays:** `https://www.rbi.org.in/Scripts/HolidayMatrixDisplay.aspx` (PROBED 200 with a browser UA) is a form-driven, state-wise matrix. Curated by hand: Mumbai holidays under the NI Act are what matter for money markets and auctions.
- Weekends are not listed in either calendar; the calendar logic adds them.

---

## 3. Provenance contract

Every stored observation (a single value at a single date) **must** carry the fields below. An adapter that cannot fill a required field must emit the observation with `quality_status = INCOMPLETE_PROVENANCE`, which the decision layer must not consume, or not emit it at all.

| Field | Type | Required | Semantics |
|---|---|---|---|
| `source_id` | enum (ids from §1, e.g. `amfi.navall`) | yes | Registry id; the adapter version is recorded separately |
| `source_url` | string (exact URL fetched, after redirects) | yes | For manual entries, the citation URL (OM, press release, FAQ) |
| `source_document_ref` | string | when applicable | e.g. `RBI PR 2026-2027/1325`, `DEA OM F.No.1/4/2019-NS dt 30.09.2026`, `SEBI Master Circular 2026-03-20 cl.3.7` |
| `retrieved_at` | RFC 3339 UTC timestamp | yes | When our client received the bytes. For manual entries, when the curator verified it |
| `observation_date` | ISO date (IST calendar date) | yes | The date the value is *for*: NAV date, auction date, CPI reference month (first day plus `period=month`), rate `valid_from` |
| `period` | enum `day \| month \| quarter \| point` | yes | CPI = month; small savings = quarter |
| `valid_from` / `valid_to` | ISO date | for rates and rules | e.g. small-savings quarter, DICGC limit, tax rule |
| `publication_time` | RFC 3339 with offset, or null | if known | HTTP `last-modified`, press-release date or time, or the scheduled release time (CPI 16:00 IST). Null if unknown; never invented |
| `currency` | ISO 4217 (`INR`) or null | yes for monetary values | |
| `unit` | enum, e.g. `INR_per_unit`, `percent_pa`, `index_points`, `INR_crore`, `price_per_100_face` | yes | |
| `value` | decimal string | yes | Exactly as published (`"25.9504"`); normalised separately in `value_normalised` |
| `convention` | string | yes for rates and yields | e.g. `RBI_TBILL_IMPLICIT_YIELD_AS_PUBLISHED`, `CPI_YOY_PCT_BASE2024`, `NAV_PER_UNIT_AS_PUBLISHED`, `SMALL_SAVINGS_RATE_PA_COMPOUNDING_PER_SCHEME` |
| `base_year` | string | for index series | `2012`, `2024` |
| `quality_status` | enum `OFFICIAL_LIVE \| OFFICIAL_MANUAL \| UNOFFICIAL_MIRROR \| STALE \| PROVISIONAL \| REVISED \| SCHEMA_CHANGED \| INCOMPLETE_PROVENANCE \| CONFLICT` | yes | Computed at ingest; `STALE` is recomputed at read time against the SLA |
| `entity_key` | string | yes | AMFI scheme code, ISIN, series id, etc. |
| `raw_sha256` | hex | yes for live fetches | Hash of the raw payload kept in the local cache, for audit and replay |
| `adapter_version` | semver | yes for live fetches | |
| `licence_class` | enum `PERSONAL_USE_ONLY \| PUBLIC_GOVT \| LICENSED \| UNKNOWN` | yes | Drives export and share blocking |
| `notes` | string | no | e.g. "NAV date older than 30 days; likely dormant plan" |

Rules:

1. `value` is never a float in storage.
2. Timestamps are UTC in storage. IST conversion happens only for display and for business-day logic.
3. Revisions (CPI provisional → final) create a new observation that references the old one. Nothing is overwritten.
4. Manual entries need `source_url`, `source_document_ref`, and the curator's `retrieved_at`.

---

## 4. Freshness SLAs

"Business day" means a business day on the relevant curated calendar (§2.18), evaluated in IST.

| Data type | Expected cadence | FRESH | STALE (warn) | EXPIRED (block decision use) |
|---|---|---|---|---|
| MF NAV (regular schemes) | NAV for T by 23:00 IST on T | `observation_date` ≥ previous business day | 2–3 business days old | > 3 business days old (or > 5 calendar days over long holidays) |
| MF NAV (FoF / ≥80% overseas) | by 10:00 IST on T+1 | ≥ T-2 business days | 3–4 business days | > 4 business days |
| NAVAll row with ancient date | — | — | — | NAV date > 30 days old means "dormant / matured", excluded from live valuation |
| AMFI scheme master | ad hoc | ≤ 7 days since retrieval | 8–30 days | > 30 days |
| TER (manual) | monthly | current or previous month | 2 months | > 3 months |
| Riskometer / PRC (manual) | monthly | ≤ 45 days | 46–75 days | > 75 days |
| T-bill auction cut-offs | weekly (Wednesday) | auction within 7 days | 8–14 days | > 21 days |
| Policy repo rate (manual) | per MPC meeting, about every 2 months | verified after the last MPC date | not re-verified after an MPC date | > 70 days since last verification |
| CPI | monthly, 12th at 16:00 IST | latest reference month = M-1 (after the 12th) or M-2 (before) | one month behind that | two or more months behind |
| WADTDR (manual) | monthly | ≤ 2 months | 3 months | > 4 months |
| Small-savings rates | quarterly | `valid_to` ≥ today | — | `valid_to` < today (the quarter rolled over without a new OM being curated) |
| DICGC limit | rare | verified within 180 days | 181–365 days | > 365 days |
| Tax rules | yearly / Finance Act | a rule set exists for the current tax year | — | no rule set for the current tax year means tax calculations are blocked |
| Trading calendars | yearly | current calendar year curated | — | not curated for the date being evaluated means freshness logic falls back to weekdays-only and flags `CALENDAR_UNVERIFIED` |

---

## 5. Known fragility and degraded-mode behaviour

| Risk | Detection | Degraded behaviour |
|---|---|---|
| AMFI header or format change (e.g. columns added, as with Plan/Option) | Exact header match fails, or the semicolon count per row ≠ 7 | Fail closed with `SCHEMA_CHANGED`. Keep serving the last good NAVs marked `STALE` once the SLA is crossed; surface a banner; never guess the column mapping |
| AMFI host or redirect change (`www` → `portal`) | Non-200 status or an unexpected final host | Retry with backoff (max 3); then stop and use the last good data. Log the final URL |
| Partial or truncated NAVAll download | `content-length` mismatch; row count < 80% of the last good run | Reject the whole file; keep the previous one |
| Rows with old dates in NAVAll | Per-row date check | Exclude from "latest"; never coerce to today |
| Non-numeric NAV ("N.A.") | Decimal parse fails | Drop that row with a warning; never zero-fill |
| NAVAll and history parsers diverge (different column order) | Separate parsers, each with a fixture test | — |
| Scheme master glued ISINs | Regex split; length ≠ 12 or 24 | Flag the row `INCOMPLETE`; keep the code→name mapping |
| mfapi.in unavailable or disagrees with AMFI | Cross-check on the overlapping date: abs diff > 0.0001 after normalisation | AMFI wins; mark the mirror value `CONFLICT`; never use the mirror alone for valuation |
| RBI WAF (418 or "Unauthorised Access") | HTTP 418, or a body containing "Unauthorised Access" | Stop immediately (no UA rotation or evasion); switch to manual entry with a prompt that shows the official URL |
| MoSPI token expiry (15 minutes) or the 10-record unauthenticated cap | 401, or exactly 10 records with `limit` > 10 | Re-login once; if there are no credentials, mark `REQUIRES CONFIGURATION` and use manually entered CPI |
| MoSPI base-2024 query returns "No Data Found" | Empty `data` | Do not fall back to base 2012 for post-Dec-2025 months; show the "CPI unavailable" state |
| Scanned government PDFs (DoP / DEA) | — | Never auto-parse; curator-only |
| Regulatory regime change (SEBI MF Regs 2026, ITA 2025, CPI base 2024) | Curated `valid_from` on rule sets | Version every rule; refuse to compare across versions without an explicit adapter (e.g. TER pre/post Apr-2026) |
| Secondary-source contamination (e.g. the news repo rate 5.25% against the official 5.50%) | — | Only OFFICIAL sources may populate decision-critical fields; secondary sources may only open a "please verify" task |

The app must always show data age and `quality_status` next to any number used in a recommendation, and must refuse to produce a recommendation that depends on EXPIRED inputs.

---

## 6. Recommended v1 ingestion plan

### 6.1 LIVE adapters (implement)

These run on the user's machine, are personal-use only, and have no redistribution or export of raw data.

1. **`amfi.navall`** — daily, run at 23:30 IST and 10:30 IST; conditional GET; exact-header parser; keep only watched schemes. Fixture: `amfi_navall_head_*.txt`.
2. **`amfi.schememaster`** — weekly; ISIN-split logic. Fixture: `amfi_schemedata_mf0_head_*.csv`.
3. **`amfi.navhistory`** — on demand, for a new holding's backfill only; ≤ 90-day windows; throttled to 1 request every few seconds. Fixture: `amfi_navhistory_*.txt`.
4. **`mospi.cpi`** — **REQUIRES CONFIGURATION**: the user signs up and supplies credentials stored in the OS keychain. Monthly, after the 12th at 16:00 IST. Base-2024 retrieval must be verified with an authenticated call before this adapter is marked production-ready. Fixture: `mospi_cpi_*.json`.

### 6.2 SEMI-LIVE (user-triggered single fetch, else manual)

5. **`rbi.pr.tbill`** — on user action, fetch the latest "T-Bill Auction Result: Cut-off" press release page and extract the three cut-off price/yield pairs. Stop on the WAF response. Given RBI's "caching … prohibited" wording, store only the extracted figures plus the citation, not the HTML. Fixtures: `rbi_pressrelease_tbill_*.html`.

### 6.3 MANUAL import / curated, with dated citations

6. Policy rates (repo, SDF, MSF, CRR, SLR) from the RBI home page or the MPC statement.
7. Small-savings quarterly rate table, from the DEA OM and DoP SB Order chain.
8. DICGC limit and conditions.
9. TER (BER + components), riskometer and PRC for watched schemes, from the AMFI or AMC page.
10. Credit ratings for held debt instruments.
11. Bank FD terms, entered by the user.
12. WADTDR reference series (optional), from RBI.
13. Trading and holiday calendars (NSE CM/MF, RBI Mumbai), per year.
14. Tax rule sets (ITA 1961 up to FY 2025-26; ITA 2025 from TY 2026-27), with section citations.
15. SEBI regulatory references (MF Regs 2026, Master Circular 2026-03-20, categorisation circular 2026-02-26) for rule metadata.

### 6.4 OPTIONAL (off by default)

16. **`mfapi.in`** — cross-check and fallback only, tagged `UNOFFICIAL_MIRROR`.

### 6.5 BLOCKED / REQUIRES LICENCE or CONFIGURATION

17. **FBIL** benchmarks (MIBOR, T-bill curve, G-sec valuation): usage and display fees apply.
18. **NSE / BSE** data of any kind by automation: the ToU prohibits it. Equity and ETF prices need a licensed vendor.
19. **CCIL** NDS-OM automated extraction: non-commercial manual viewing only.
20. **CRA** website scraping: prohibited by the terms.
21. **RBI DBIE** automation: no documented API, and the third-party mirror is not allowed.
22. **captn3m0 bulk mirror**: no licence, and bulk.

### 6.6 Open verification tasks before release

- [ ] Confirm the small-savings rate table from the primary DEA OM (Q2 FY27 OM dated 30-06-2026 or the last OM that states the table).
- [ ] Confirm the effective date of the DICGC ₹5 lakh limit on dicgc.org.in.
- [ ] Authenticated MoSPI probe for `base_year=2024`; record the response shape as a fixture.
- [ ] Confirm the AMFI `mf` id list and the `tp` code meanings for the NAV history endpoint.
- [ ] Locate the 2026 Master Circular clauses for NAV timing, riskometer and portfolio disclosure, and replace the 2024 paragraph references.
- [ ] Confirm the post-2026 SEBI category taxonomy (Feb-2026 circular) for the category enum.
- [ ] Confirm the ITA 2025 section numbers for capital-gains rules used by the tax engine.
- [ ] Obtain written clarification from AMFI if the app is ever distributed beyond a single personal user.
