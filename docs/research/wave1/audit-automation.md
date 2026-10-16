# Audit: replacing manual entry with official automatic sources

Wave 1 · audit "automation" · researched 2026-10-15 (probes 2026-10-15 17:58–18:07 UTC)
Scope: every value the app currently asks the user to type, and for each one an official, free source that its terms
allow us to fetch automatically, with a deterministic parser plan. Status labels: **VERIFIED** (probed or read
today), **NOT VERIFIED**, **REQUIRES CONFIGURATION**, **BLOCKED**.

Ground rules used here:

- Every external claim carries a URL, the access date (2026-10-15) and a short quote. A claim I could not check is
  marked NOT VERIFIED.
- "Automated fetching permitted" is judged from the source's own terms text. Where the terms are silent or ambiguous
  I say so and list it as a user decision. I do not treat silence as permission.
- No raw AMFI or RBI payloads are reproduced (AMFI ToU, RBI disclaimer). Shapes below use field names only, or
  synthetic values. CPI index values are published government statistics and are quoted as such.
- None of this is legal advice.

---

## 0. Bottom line

You asked for something that hands you signals and keeps itself up to date, not a form to fill in. For the
inputs the app needs today, three can switch from typing to automatic fetching right away. All three are official,
free and allowed by their terms. One of the three fixes a bug: the existing adapter cannot work as built.

| # | What you type today | Best official automatic source | Can we fetch it automatically? | Verdict |
|---|---|---|---|---|
| 1 | **CPI** index + YoY (base 2012 and base 2024) | MoSPI API `api.mospi.gov.in` — `/api/cpi/getCPIData` (base 2024), `/api/cpi/getCPIIndex` (base 2012) | **Yes.** The API is published for programmatic use, and filtered queries return the one needed record **without any login** | **VERIFIED (probe).** The existing adapter calls the wrong endpoint for base 2024 and asks for credentials it does not need (see §3.1) |
| 2 | **Risk-free rate**: the 91-day T-bill cut-off yield | RBI Press Releases **RSS feed** `https://rbi.org.in/pressreleases_rss.xml`, then the linked cut-off press release | **Yes, read as a feed.** RBI offers the RSS feed so readers get "automatic site updates". We store the extracted figures only, never the HTML | **VERIFIED (probe).** The feed and the press-release page both answer an honest, non-browser user-agent with HTTP 200. Only `robots.txt` returns 418 |
| 3 | **T-bill instrument** (tenor, cut-off yield) | Same RBI cut-off press release | Yes (same feed) | **VERIFIED** for yields. Price↔yield formula checked 3/3 (§3.2). Issue/maturity date needs the auction-announcement release (NOT VERIFIED that it is in the feed) |
| 4 | **TER / BER** (inside "factsheet facts") | AMFI TER page `amfiindia.com/ter-of-mf-schemes`. Its data loads from an undocumented JSON endpoint | **Grey area.** The AMFI ToU allows personal, non-commercial access but says "No reverse engineering". The endpoint is not published as a download | **USER DECISION.** Default: user-triggered, one AMC and one month, personal only. Shape VERIFIED by one probe |
| 5 | **Riskometer / PRC** | AMC monthly portfolio disclosure (SEBI-mandated, also posted to AMFI) | No central feed found. Each AMC site's terms forbid reproduction | **BLOCKED for crawling.** Instead: **user-supplied file import** (you download the AMC's file, the app parses it) |
| 6 | **Duration, YTM, average maturity** (factsheet) | AMC monthly factsheet (PDF). AMFI Best Practice Circular 88 standardises the fields | No machine format. AMC terms forbid reproduction | **BLOCKED for crawling.** User-supplied PDF, with a deterministic extract-and-confirm step |
| 7 | **Lowest rating, share below AAA, share sovereign+cash** (factsheet) | AMC monthly **portfolio** spreadsheet (SEBI format: ISIN, rating, yield of each instrument) | Same as #5 | **User-supplied file.** These three figures can be **computed** from the holdings rows (§3.5). Computed from the holdings, not copied from the factsheet |
| 8 | **Exit load** | Scheme Information Document / KIM ("Load Structure"), hosted as PDFs on `portal.amfiindia.com/spages/<id>.pdf` | Free text inside a PDF. AMFI ToU applies | **REQUIRES CONFIGURATION.** A user-triggered fetch of the one SID per held scheme, then a strict pattern parser that abstains on anything it does not recognise |
| 9 | **Bank FD card-rate tables** | Each bank's own rate page (e.g. SBI, HDFC Bank on the new `.bank.in` domains) | **Per bank.** SBI: "shall not be displayed or printed … without the prior written approval". HDFC Bank: personal, non-commercial download allowed | **BLOCKED by default**, with a per-bank allowlist after a terms review. Plus **paste-a-table** parsing (no fetch) |
| 10 | **Your own FD** (rate, tenure, penalty, existing deposits) | Your FD receipt or advice | Personal data; no public source | **Stays manual.** Can be pre-filled from the bank's card-rate table (#9) |
| 11 | **G-sec / SDL quote** (clean price or YTM) | CCIL NDS-OM Market Watch | Non-commercial use allowed, but CCIL "discouraged from extracting the Data … using data streaming methods". FBIL charges fees | **BLOCKED for automation.** Paste-assist only |
| 12 | **G-sec / SDL static terms** (ISIN, coupon, issue date, maturity) | RBI auction press releases (in the same RSS feed) | Yes, as #2 | **NOT VERIFIED.** The parser needs a fixture from a live auction-result item |
| 13 | **Corporate bond terms** (coupon, maturity, frequency, secured, calls) | NSDL India Bond Info (`indiabondinfo.nsdl.com`) | Its Terms and Conditions page could not be read (ECONNRESET). The disclaimer is about liability, not reuse | **NOT VERIFIED.** No automation until the T&C is read |
| 14 | **Corporate bond rating** (rating, agency, date, rationale URL) | Rating agencies' sites | CRISIL forbids copying without written consent. ICRA/CARE/India Ratings terms NOT VERIFIED | **BLOCKED** (CRISIL). Others NOT VERIFIED; stays manual |
| 15 | Profile, holdings and transactions | CAS PDF import (already built) | Personal data | Already automated from your CAS. No public source applies |

**What this means for "grow my money" signals:** #1 and #2 are the inputs behind real-return and Sharpe figures, so
automating them takes away the two biggest reasons the engine abstains today. Most per-fund facts (#5–#8) cannot be
pulled from any terms-permitted feed. The best we can do is a one-step "drop the AMC's file here" import. That
reduces typing to roughly one upload per AMC per month, but it does not remove the step entirely.

---

## 1. Inventory: every value the user is asked to type

| Area | Endpoint | Model (file:line) | Fields typed | Frontend |
|---|---|---|---|---|
| CPI | `POST /api/inputs/cpi` | `backend/src/iip/services/inputs.py:87` `CPIPointIn` | base_year, month, index, yoy_inflation_pct, provisional, citation{url, as_of} | `frontend/src/components/MacroInputs.tsx:198-225` |
| CPI (MoSPI fetch) | `POST /api/inputs/mospi/fetch` | `backend/src/iip/api/routes_inputs.py:21` | base_year, month (needs `IIP_MOSPI_TOKEN` / user+password) | `MacroInputs.tsx:89-100` |
| Risk-free | `POST /api/inputs/riskfree` | `inputs.py:193` `RiskFreeIn` | yield_fraction (91-day cut-off), citation | `MacroInputs.tsx:340-343` |
| Factsheet facts | `POST /api/inputs/fund-facts/{id}` | `inputs.py:253` `FundFactsIn` | as_of_month, modified_duration, macaulay_duration, ytm, average_maturity_years, expense_ratio, expense_ratio_kind (TER/BER), lowest_rating, share_below_aaa, share_sovereign_cash, citation | `frontend/src/components/FundFactsPanel.tsx:207-247` |
| FD card-rate table | `POST /api/inputs/fd-rates` | `inputs.py:400` `FDRateTableIn` | institution, buckets[min_days, max_days, rate], premature_rate_basis, citation | `frontend/src/components/FdCardRates.tsx:154-199` |
| T-bill | `POST /api/instruments/tbill` | `backend/src/iip/services/instruments.py:43` `TBillIn` | name, tenor, maturity, yield_fraction, citation | `frontend/src/pages/FixedIncome.tsx:471-492` |
| FD (own) | `POST /api/instruments/fd` | `instruments.py:53` `FDIn` | institution, type, rate, tenure_days, premature_penalty, existing_deposits_at_institution, citation | `FixedIncome.tsx:583-627` |
| Exit load | `PUT /api/instruments/{id}/exit-load` | `instruments.py:66` `ExitLoadIn` | days, rate, citation | MF Explorer → exit-load form (`frontend/src/pages/MfExplorer.tsx:30-195`) |
| G-sec / SDL | `POST /api/instruments/gsec` | `instruments.py:96,131` | issuer, isin, coupon_rate, issue_date, maturity, face_value, clean_price or ytm, quote_date, transaction_spread, citation | `FixedIncome.tsx:964…` |
| Corporate bond | `POST /api/instruments/corp-bond` | `instruments.py:145` | the above plus frequency, ytm_compounding, rating, rating_agency, rating_date, rating_citation, listed, secured, record_date_days, call_schedule | `FixedIncome.tsx:1075-1152` |
| Profile | `PUT /api/profile` | `services/profile.py:25` | amount, withdrawal date, objective, loss tolerance, liquidity, credit floor, tax regime, slab, surcharge, aspiration | `Onboarding.tsx:202-348` |
| Transactions / watchlist | `POST /api/portfolios/{id}/transactions`, `/api/watchlist` | `services/portfolio.py:125,144` | txn date/type/units/amount; watch note | Holdings / Watchlist |

Profile and transactions are the user's own facts, so no public source exists for them. CAS import
(`routes_cas.py:90`) already automates transactions. They are out of scope below. Policy rates, small-savings
rates, DICGC and tax rules are curated by the maintainer, not typed by the user (`docs/data/source-registry.md`
§6.3). §4 notes where the same feeds would help with them.

---

## 2. Cross-cutting findings

### 2.1 Scheduling constraint in hosted mode (VERIFIED)

The production deployment is Vercel Hobby (ADR-0013). Vercel docs, accessed 2026-10-15:
"Hobby accounts are limited to cron jobs that run **once per day**. Cron expressions that would run more frequently
will fail during deployment", with "Per-hour (±59 min)" precision and up to "100 cron jobs" per project
(https://vercel.com/docs/cron-jobs/usage-and-pricing).

Consequences:

- **Daily jobs fit:** NAVAll, MoSPI CPI check, RBI RSS poll.
- **The RBI feed holds only the latest 10 items** (probe at 18:02 UTC: 10 `<item>`s spanning 14-Oct 19:00 to
  15-Oct 17:50 IST). Wednesday's T-bill result (prid 63803) had already dropped out by Thursday evening.
  - A once-a-day poll can therefore miss a release.
  - The plan in §3.2 handles this two ways: several daily cron entries at different hours (each still "once per
    day"; whether Vercel accepts several entries pointing at one path is NOT VERIFIED), and a fallback lookup when the
    feed has no cut-off item for the latest Wednesday.
- **Lazy refresh on visit:** when the user opens Data health or Compare and a series is past its FRESH window, the
  page triggers the fetch. That makes it a user-triggered request, which is also the most defensible posture for
  RBI.
- **Local mode:** the same jobs via launchd, as jobpilot already does on this machine.

### 2.2 "User-supplied document import" pattern (recommended for AMC data)

Several sources (AMC factsheets, portfolio files, bank rate pages) let an individual download for personal use but
forbid reproduction or "enter into a database" by others. The pattern that fits those terms:

1. The app shows the official URL as text.
2. The user downloads the file in their own browser.
3. The user drops it into the app.
4. A **deterministic, per-format parser** extracts candidate values. Each value carries a page, sheet or cell
   reference and the file's SHA-256.
5. The user confirms in one click.
6. Values are stored with `quality_status=manual`, `source_id` set to the AMC, and the citation URL.

**No LLM is used** (binding rule). If a parser does not recognise the layout, it extracts nothing (`SCHEMA_CHANGED`).
This replaces about ten typed numbers per scheme per month with one upload.

### 2.3 RBI disclaimer: deep links need permission (finding)

RBI disclaimer (https://www.rbi.org.in/Scripts/Disclaimer.aspx, read 2026-10-15) says users must "secure permission
from RBI prior to hyper-linking to, or framing, this Web Site or any of the contents", and that only the home page
may be linked "upon notifying RBI in writing".

The app renders citation URLs as clickable `<a href>` links (`frontend/src/components/FundFactsPanel.tsx:49`,
`frontend/src/pages/FixedIncome.tsx:222`, `frontend/src/pages/Evidence.tsx:18`). An RBI press-release citation would
therefore become a deep link.

- **Low-cost fix:** render `rbi.org.in` and `rbidocs.rbi.org.in` citations as copyable text, not as anchors. The
  citation still traces the number.
- **Alternative:** write to RBI for permission.

Severity: low. It applies whether or not the input is automated.

### 2.4 Correction to `docs/operations/known-limitations.md`

That document says "RBI blocks scripted access (HTTP 418)". Today's probe refines this:

- `robots.txt` returns 418 to every user-agent tried.
- `https://www.rbi.org.in/pressreleases_rss.xml` returned 200 (86,876 bytes) to `curl/8.7.1` and to
  `investment-intelligence-pro/0.1 (personal feed reader)`.
- `BS_PressReleaseDisplay.aspx?prid=63803` returned 200 (111,497 bytes) to an honest non-browser user-agent.

The WAF can still block at any time, so the stop-on-418 rule in source-registry §5 stays as it is: no user-agent
spoofing and no evasion.

---

## 3. Per-input detail

### 3.1 CPI (index + YoY, base 2012 and base 2024): automate now

| Item | Finding |
|---|---|
| Source | MoSPI eSankhyiki API, `https://api.mospi.gov.in` (official; MoSPI's GitHub links it as "Official API documentation") |
| Base 2024 endpoint | `GET /api/cpi/getCPIData?base_year=2024&series=Current&year=YYYY&month_code=M&state_code=1&sector_code=3&division_code=0&Format=JSON` |
| Base 2024 back series | the same call with `series=Back` (e.g. year 2024, month 12 returned one record) |
| Base 2012 endpoint | `GET /api/cpi/getCPIIndex?base_year=2012&series=Current&year=YYYY&month_code=M&state_code=99&sector_code=3&group_code=0&Format=JSON` |
| Code lists | `GET /api/cpi/getCpiFilterByLevelAndBaseYear?base_year=2024&level=Group&series_code=Current` returns state (All India = **1** for base 2024), sector (Combined = 3), division (CPI (General) = 0) and month codes |
| Format | JSON `{"data":[…],"meta_data":{"totalRecords":1,…},"msg":"Data fetched successfully","statusCode":true}` |
| Cadence | Monthly, 12th at 16:00 IST (source-registry §2.12) |
| Auth | **Not needed for these filtered queries.** The unauthenticated cap is 10 records per page, and each query returns `totalRecords: 1` |
| Probe | 2026-10-15T18:04Z, base 2024 Combined General: Sep-2026 index 109.49, inflation 5.54. Aug-2026 108.74 / 4.83. Back series Dec-2024 102.90 / 5.22. Base 2012 Dec-2025 Combined General: 198.0 / 1.33, `status:"F"` |
| Terms | No data licence or terms page found on api.mospi.gov.in (homepage probed: 486 bytes, no terms link). The MoSPI copyright policy, quoted through a search result and NOT VERIFIED directly (the page did not render), says material "may be reproduced free of charge after taking proper permission by sending a mail to us", with the source "prominently acknowledged". The MCP/client code is MIT, which covers code, not data |
| Automated fetch permitted? | **Yes for personal use.** The API exists to be called by programs. Reproduction to others would need permission. Personal use is unaffected |
| Status | **VERIFIED** (endpoint, shape, no-auth single-record queries) |

**Defects in the current adapter (VERIFIED by reading the code and probing):**

1. `backend/src/iip/data/registry.py:529` builds `/api/cpi/getCPIIndex?...&state_code=99` for **both** bases. For
   `base_year=2024` that endpoint returns `{"data":[],"msg":"No Data Found"}` (re-probed today with three variants).
   Base 2024 is served by `/api/cpi/getCPIData`. The official client `nso-india/mospi-esankhyiki` 0.2.1
   (`esankhyiki/client.py`) routes it the same way: "CPI base_year 2024 uses unified endpoint … `/api/cpi/getCPIData`".
2. `backend/src/iip/data/mospi.py:153` matches `r.get("baseyear")`. Base-2024 rows use `base_year`.
3. `mospi.py:33` `_GENERAL_LABELS` lacks `"cpi (general)"`, the base-2024 division label.
4. Without `sector_code` and `group_code`/`division_code` filters, the query returns more than 10 rows. The parser then
   refuses at the unauthenticated cap, which is why it "needs" credentials. With the filters it does not.
5. Base-2024 rows carry **no `status` (P/F) field**. The provisional flag must not be invented. Store
   `provisional = unknown`, or derive it from a cited MoSPI rule that the latest month is provisional (that rule's
   current wording is NOT VERIFIED).

**Parser plan (deterministic):**

1. Build the filtered URL per (base, year, month).
2. Require `statusCode is True` and `meta_data.totalRecords == 1`.
3. Require exactly one row with `state == "All India"`, `sector == "Combined"`, and division or group equal to the
   general label for that base.
4. Read `index` and `inflation` as `Decimal(str)`. Reject non-finite or ≤ 0 values.
5. Store each base as its own series (never chained), with `raw_sha256`, `retrieved_at`, `publication_time` = the
   scheduled release time, and `convention=CPI_COMBINED_GENERAL_INDEX_BASE{b}`.
6. Schedule: daily cron. Fetch month M−1 from the 12th at 16:00 IST onward; until it appears, re-check M−2 for
   revisions. A revision appends and never overwrites.
7. Fixtures: synthetic single-record files for both shapes.

### 3.2 Risk-free (91-day T-bill cut-off) and T-bill instruments: automate via RSS

| Item | Finding |
|---|---|
| Source | RBI Press Releases RSS: `https://rbi.org.in/pressreleases_rss.xml` (listed on https://rbi.org.in/Scripts/rss.aspx). The page describes RSS as a way to "receive automatic site updates without having to check back to the site periodically" |
| Format | RSS 2.0, UTF-8 with BOM. `<item>` has `title`, `link` (`…BS_PressReleaseDisplay.aspx?prid=N`), `pubDate` (IST wall time), and `description` with the release's HTML table body (seen today on the SGS auction item) |
| Headers | `cache-control: public, max-age=20`, `last-modified`, `etag`, so conditional GET works |
| Target items | Title "91-Day, 182-Day and 364-Day T-Bill Auction Result: Cut-off" (the stable title per source-registry §2.8). Weekly, Wednesday |
| Page probe | `prid=63803` (PR 2026-2027/1325). The text contains "Cut-off Price (₹) and Implicit Yield at Cut-Off Price 98.5920 (YTM: 5.7281%) 96.9592 (YTM: 6.2896%) 93.9220 (YTM: 6.4891%)" |
| Yield convention | **Checked 3/3 on this release:** yield = (100 − P) / P × 365 / tenor_days, rounded to 4 dp, reproduces 5.7281 / 6.2896 / 6.4891 exactly (Decimal, prec 28). This is consistent with a simple-interest, 365-day convention. It is one release, not an official statement, so the stored convention stays `RBI_TBILL_IMPLICIT_YIELD_AS_PUBLISHED` |
| Terms | Disclaimer: "caching and links to, and the framing of this Web Site … are prohibited" except as set forth; RBI "reserves all right to deny or restrict access". Subscribing to an RSS feed RBI itself publishes, and storing only the extracted figures, is the intended use of a feed. Caching the HTML and deep-linking are not |
| Automated fetch permitted? | **Yes for the RSS feed** (offered for automatic updates). **Narrowly** for the single linked release page when the feed description lacks the table: one request per new item, with an honest user-agent, stopping on 418 or "Unauthorised Access" |
| Status | **VERIFIED** (feed and page reachable, cut-off text parsed, formula 3/3). NOT VERIFIED: that the T-bill cut-off item's `description` carries the full table (the item had already dropped out of the feed) |

**Parser plan:**

1. **Fetch.** Conditional GET on the feed (`If-None-Match`). Parse it with a defused XML parser (`defusedxml`: no
   entities, no DTD).
2. **Match.** Select items whose title matches `^91-Day, 182-Day and 364-Day T-Bill Auction Result: Cut-off$` and
   whose link host is `www.rbi.org.in`.
3. **Extract the text.** Strip tags from the `description`. If no "Implicit Yield" text is present, fetch the `link`
   once.
4. **Pull the numbers.** Use a strict regex: `(\d{2,3}\.\d{4}) \(YTM: (\d{1,2}\.\d{4})%\)`, requiring exactly three
   matches in the order 91, 182, 364.
5. **Cross-check.** Recompute each yield from its price with the formula above. Any mismatch is a refusal; the source
   is never silently trusted. This is a self-check, not a substitute value.
6. **Store.** Save the three yields (fraction = pct/100) as `riskfree:tbill91` and sibling series, with `source_document_ref` =
   "Press Release: 2026-2027/NNNN" (regex on the page) and `observation_date` = the auction date. The release date
   is in `pubDate`; the "auction held on" date must be parsed from the text, and if it is absent, abstain.
7. **Instruments.** For `TBillIn`, maturity = issue date + tenor days. The issue date comes from the preceding
   "Auction of … Treasury Bills" announcement, also in the feed (title pattern and fixture NOT VERIFIED). With no
   cited issue date, the instrument stays manual.
8. **Fallback when an item drops out.** Note "missing Wednesday cut-off" on Data health and offer a one-click fetch of
   the press-release listing page (user-triggered).

**Bonus from the same feed (not user inputs today):**

- "Money Market Operations as on …" (daily, 09:00 IST): an overnight-rate series.
- "Lending and Deposit Rates of Scheduled Commercial Banks" (monthly): WADTDR, a reference for FD comparisons. The
  Sep-2026 release reported fresh WADTDR 5.67% for Aug-2026 (via search results: Business Standard / RBI PDF index;
  NOT VERIFIED on rbi.org.in today).
- MPC resolutions: policy repo rate.

All three could replace curated entries. Each needs its own fixture.

### 3.3 TER / BER (inside factsheet facts): user decision

| Item | Finding |
|---|---|
| Official page | https://www.amfiindia.com/ter-of-mf-schemes (probed 200). Filters: financial year, month, fund type, category, mutual fund. **No Excel/CSV download link** found in the HTML |
| Data endpoint (undocumented) | `GET https://www.amfiindia.com/api/populate-te-rdata-revised?MF_ID=<n>&Month=MM-YYYY&strCat=-1&strType=1&page=1&pageSize=<k>`; AMC list at `/api/populate-mf`. Documented by a third party (github.com/satwikbasu/indian-market-data-endpoints, `endpoints/amfi-ter-api.md`, "discovered on 2026-05-21 via Playwright") |
| Probe | 2026-10-15T18:06Z, one call (`MF_ID=9`, `Month=09-2026`, `pageSize=50`): 200 `application/json`, `{"data":[…],"meta":{"page","pageSize","total","pageCount"}}`, total 3,189 rows for that AMC and month (**daily** rows: 30 distinct `TER_Date`s). Fields: `NSDLSchemeCode, Scheme_Name, SchemeType_Desc, SchemeCat_Desc, TER_Year, TER_Date, Month, MF_ID, R_/D_ × {BER, BrokerageCost, TransactionCost, StatutoryLevies, TER}`. **All numeric values are strings** (e.g. `"0.9000"`), so they are Decimal-safe |
| Key mismatch | `NSDLSchemeCode` (e.g. pattern `XXXX/O/H/ABC/18/03/0034`) is **not** the AMFI scheme code. Joining needs an exact scheme-name match, which is ambiguous by design → abstain on any non-unique match |
| Regulation | The page cites "Base Expense Ratio (BER) as per Regulation 66(7) of SEBI (Mutual Funds) Regulations, 2026". Brokerage is an "annualized, cumulative daily average … reset monthly" |
| robots.txt | Disallows only `/admin/`, `/login/`, `/search/`. `/api/` is not disallowed |
| Terms | AMFI ToU (https://www.amfiindia.com/terms-of-use, read 2026-10-15): "personal and non-commercial use only"; "No reverse engineering, linking, framing, or modification of any part of this Site is allowed"; "You shall not store electronically any significant portion of any part of the Site" |
| Automated fetch permitted? | **Ambiguous.** Personal access is granted and robots does not exclude `/api/`. But the endpoint is not a published download, and calling an endpoint found by inspecting the page's network traffic can fairly be read as the "reverse engineering" the ToU bars. The third-party note also says "AMFI rate-limits aggressively" and that errors come back as HTTP 200 with a truncated body |
| Status | **USER DECISION** (default OFF). Shape VERIFIED by one probe. No data from the probe is stored in the repo |

**If enabled (personal, user-triggered only):**

- One request per AMC the user holds, per month: `pageSize` = that AMC's `total`, at most one call per second, and
  `try json.loads` on the body, failing closed on a 200 that is not JSON.
- Keep only rows for held or watched schemes, and only the latest `TER_Date` of the month. That satisfies "no
  significant portion".
- Map to the scheme by exact normalised name plus plan (Regular → `R_*`, Direct → `D_*`). Two or more candidates →
  `AMBIGUOUS_SCHEME_MATCH`, nothing stored.
- Store `ter`, `ber`, brokerage, transaction cost and levies separately, plus `regulation_version="SEBI-MF-2026"`
  (pre-April-2026 rows are not comparable; source-registry §2.4).

**Safer alternative:** write to AMFI asking whether personal programmatic use of the TER data is acceptable. Until
then, use the per-AMC daily TER disclosure through the §2.2 file-import pattern.

### 3.4 Duration, YTM, average maturity, riskometer (factsheet)

| Item | Finding |
|---|---|
| Rule | AMFI Best Practices Guidelines Circular No. 88/2020-21 (30-Jul-2020): "Macaulay Duration, Modified Duration, Average Maturity and Yield to Maturity shall be disclosed separately" in monthly factsheets (https://www.amfiindia.com/Themes/Theme1/downloads/circulars/SEBI/CU115-AMFI%20BP%20Cir%20No.%2088%20dt.%2030-Jul-2020-Additional%20disclosures%20in%20monthly%20Fact%20Sheets.pdf, via search result). The SEBI 26-Feb-2026 categorisation circular makes portfolio-level Macaulay duration the category test (repo `rules/mf_categories.yaml`) |
| Riskometer | "Risk-o-meter shall be evaluated on a monthly basis and Mutual Funds/AMCs shall disclose the Risk-o-meter along with portfolio disclosure for all their schemes on their respective website and on AMFI website within 10 days from the close of each month" (SEBI circular of 5-Oct-2020 as quoted in search results; the clause in the 2026 Master Circular is NOT VERIFIED) |
| Central AMFI page | **Not found.** The AMFI sitemap (13 URLs) and the Research & Information page link only fund-performance, industry-data-analysis, tracking-error, amfi-data, commission-disclosure and group-companies. No riskometer or portfolio-disclosure URL was found → NOT VERIFIED that one exists today |
| Format | Factsheets are PDFs. Layouts differ by AMC and change between months |
| Terms (example) | HDFC Mutual Fund disclaimer (https://www.hdfcfund.com/disclaimer, via search): the site is "for the personal information of the User"; "the User may not reproduce, transmit, sell, display, distribute, publish … or commercially exploit such information/data/materials … Except as expressly permitted by HDFC AMC". Other AMCs' terms: NOT VERIFIED |
| Automated fetch permitted? | **No for crawling AMC sites.** Personal download by the user: yes |
| Status | **BLOCKED** (automated crawl). The §2.2 file-import pattern is **REQUIRES CONFIGURATION** (one parser per AMC the user holds) |

**Parser plan:**

1. Extract text with `pypdfium2` (already a dependency via CAS) from the user's PDF.
2. Locate the scheme's section by its exact scheme name.
3. Inside that section, match labelled patterns for each metric, for example `Modified Duration[:\s]+(\d+\.\d+)\s*(years|yrs)?`
   and the same for Macaulay Duration, Average Maturity and YTM. Each label must appear **exactly once** in the
   section, and a units check rejects days versus years mixups.
4. Any label found zero times or more than once leaves that metric empty. Nothing is guessed.
5. Show each value with its page number and the matched line, then confirm.
6. Riskometer: match one of the six SEBI level strings near "Risk-o-meter" in the section. Abstain if it is not
   unique.
7. Fixtures: synthetic PDFs per AMC layout.

### 3.5 Lowest rating, share below AAA, share in sovereign and cash: compute from the portfolio file

| Item | Finding |
|---|---|
| Source | AMC monthly (and fortnightly, for debt) portfolio disclosure. SEBI CIR/IMD/DF/21/2012: "disclose portfolio (along with ISIN) as on the last day of the month … on or before the tenth day of the succeeding month in a user-friendly and downloadable format (preferably in a spreadsheet)" (https://www.sebi.gov.in/sebi_data/attachdocs/1347547815927.pdf, via search). SID text: portfolio "along with ISIN and yield of the instruments … on the website of AMFI in a user-friendly and downloadable spreadsheet format" (HSBC MF periodic-disclosure PDF, via search) |
| Format | Excel, with one sheet per scheme and AMC-specific header rows. Columns typically include instrument name, ISIN, rating, quantity, market value and % of NAV (and yield for debt). Exact columns per AMC: NOT VERIFIED |
| Terms | As in §3.4 (per AMC) |
| Status | **REQUIRES CONFIGURATION** (file import) |

**Parser plan (deterministic, formula-traced):**

1. Use `openpyxl` in read-only mode on the user-supplied file.
2. Locate the header row by exact column labels from a per-AMC profile. An unknown layout → `SCHEMA_CHANGED`.
3. For each holding row, read ISIN, rating text and % NAV as `Decimal`.
4. Map rating strings to `CREDIT_SCALE` with an explicit table that includes short-term A1+ and SOVEREIGN. Any
   unmapped string → abstain for the whole scheme.
5. Compute:
   - `share_sovereign_cash` = Σ % NAV of (SOVEREIGN ∪ TREPS/cash/net receivables);
   - `share_below_aaa` = Σ % NAV of ratings < AAA;
   - `lowest_rating` = min over holdings.
6. Check that Σ % NAV is within ±0.5 pp of 100. Otherwise refuse.
7. Store as `derived` with the formula id and the file's SHA-256. This is **computed from the holdings**, so the UI
   must say "computed from the AMC portfolio file", not "factsheet".

### 3.6 Exit load: parse the SID "Load Structure" under a strict grammar

| Item | Finding |
|---|---|
| Source | Scheme Information Documents hosted on AMFI's portal as `https://portal.amfiindia.com/spages/<id>.pdf` (many examples in search results, e.g. `…/spages/8678.pdf` SBI MF SID), plus KIMs and factsheets |
| Format | Free text in a PDF. Examples quoted in search results: "Exit Load: 1%, if exited on or before 365 days^; Nil, if exited after 365 days^" and "0.15% if redeemed on or before 30 days from the date of allotment; Nil after 30 days" |
| Structured central source | **None found** (no exit-load column in the AMFI scheme master; source-registry §2.3 header) |
| Rules | SEBI cut the maximum exit load from 5% to 3% in Sep-2025 (via search; primary NOT VERIFIED). The liquid-fund graded load (SEBI letter of 15-Oct-2019) is already built in |
| Terms | AMFI ToU (as §3.3) for portal-hosted SIDs. The SID itself is a public offer document that SEBI requires |
| Automated fetch permitted? | **User-triggered, one document per held scheme:** consistent with personal use and with no significant portion stored. Bulk SID crawling: no |
| Mapping problem | The SID `spages/<id>` number is not keyed to the AMFI scheme code. The user supplies the SID link once, or drops the PDF |
| Status | **REQUIRES CONFIGURATION** |

**Parser plan:**

1. Locate the "Exit Load" or "Load Structure" block.
2. Accept only text that fully matches a small grammar:
   - `Nil` → none;
   - `(\d+(\.\d+)?)%\s*(if|for)\s*(redeemed|exited|switched out)\s*(on or before|within)\s*(\d+)\s*(days|months|year[s]?)\s*(from the date of allotment)?` followed by `; Nil (thereafter|after …)`;
   - multi-tier graded variants as repeated clauses.
3. Free-unit allowances ("10% of units … without load") get their own grammar branch. If that branch does not
   parse, the scheme stays `EXIT_LOAD_UNKNOWN`. A partially recognised schedule is never stored.
4. Months and years convert to days only by an explicit, cited rule. Otherwise abstain (calendar months ≠ 30 days).
5. Store with a `valid_from` equal to the SID date. A load change arrives by addendum, so mark the value STALE after
   the SID's next annual update (SID update cadence NOT VERIFIED).

### 3.7 Bank FD card rates: per-bank allowlist plus paste parsing

| Item | Finding |
|---|---|
| Central source | **None.** RBI publishes only ranges and WADTDR (§3.2) |
| SBI | https://sbi.bank.in/web/interest-rates/deposit-rates/retail-domestic-term-deposits: an HTML table of tenors ("7 days to 45 days", "46 days to 179 days", …) with "with effect from" 15/12/2025 (fetched 2026-10-15). Disclaimer (https://sbi.bank.in/web/customer-care/disclaimer, via search): "The content of this website shall not be displayed or printed in any form in part or whole without the prior written approval of SBI" → **BLOCKED** for automated fetch-and-display |
| HDFC Bank | Website Usage Terms (https://www.hdfc.bank.in/useful-links/website-usage-terms, via search): "I shall not copy, reproduce, … enter into a database, display … any part of any information … except that which I may download for my own personal, non-commercial use" → a personal download is permitted. An automated fetch into a database is arguably covered by the personal-use exception, but that reading is the user's call |
| Other banks | NOT VERIFIED. Each needs its terms read and recorded before any adapter exists |
| Domains | Banks have moved to `.bank.in` (both examples above). Any hard-coded `.co.in` / `.com` URL is stale |
| Status | **BLOCKED** by default. HDFC Bank: **USER DECISION**. Others: NOT VERIFIED |

**Plan (no fetch needed):**

- **Paste-a-table:** the user copies the rate table from the bank page into a textarea.
  - A deterministic tokenizer recognises tenor-range rows (`(\d+) days? to (\d+) days?`, `(\d+) years? to less than
    (\d+) years?`, `1 year`, …) and rate columns (`\d+\.\d{2}%`).
  - It proposes buckets, which the existing `validate_card_rate_table` checks.
  - Year-to-day conversion follows an explicit rule (e.g. 1 year = 365 days, cited per bank). Otherwise abstain.
  - Ambiguous columns (public vs senior, < ₹3 cr vs bulk) require the user to pick a column. The parser never picks.
- **Per-bank adapters**, only for banks whose terms permit personal automated download: HTML table parse on exact
  column headers, fail-closed.

### 3.8 Your own FD

This is a personal contract, so there is no public source. Make entry faster without guessing:

- Pre-fill the rate from the stored card-rate table for the chosen tenure and date. Show the source, and let the user
  confirm or override.
- `existing_deposits_at_institution` is already partly derived from recorded FDs.

Status: stays manual.

### 3.9 G-sec / SDL quotes and terms

| Item | Finding |
|---|---|
| Quotes | CCIL NDS-OM Market Watch (https://www.ccilindia.com/market-watch). CCIL Data Sharing Policy Oct-2025 (https://www.ccilindia.com/documents/d/ccil/ccil_datasharing_policy_oct25, via search): "Users of the Data on the CCIL website are allowed to use the Data for non-commercial purposes and discouraged from extracting the Data for any such arrangement using data streaming methods" |
| FBIL valuations | Fee-liable (source-registry §2.9) → BLOCKED |
| RBI home "Current Rates" | One benchmark G-sec yield only; not per-ISIN |
| Exchanges | NSE ToU bans "systematic or automated data collection" (source-registry §2.11) → BLOCKED |
| Static terms | RBI auction press releases (RSS, §3.2) state the security, coupon and dates for primary issues. Exact item titles and fixtures are NOT VERIFIED |
| Status | Quotes: **BLOCKED** (automation); paste-assist only (the user pastes a Market Watch row; a deterministic parse proposes price/yield/date). Terms: **NOT VERIFIED** (RSS route) |

### 3.10 Corporate bond terms and ratings

| Item | Finding |
|---|---|
| Terms | NSDL India Bond Info ISIN pages (`https://www.indiabondinfo.nsdl.com/bds-web/homePortal.do?action=searchDtls&isinno=<ISIN>`) show coupon, face value, maturity, secured status and day count (via search). The disclaimer (via search) says the data comes from "issuers, stock exchanges, credit rating agencies and debenture trustees", with no warranty. **The Terms and Conditions page could not be read** (WebFetch ECONNRESET) → NOT VERIFIED |
| Ratings | CRISIL Ratings: "None of the information … may be copied, reproduced … without the prior written consent" (source-registry §2.13) → **BLOCKED**. ICRA, CARE and India Ratings: NOT VERIFIED |
| Status | Terms: **NOT VERIFIED** (read the India Bond Info T&C first; if it permits, a user-triggered per-ISIN fetch with an exact-label HTML parse). Ratings: **BLOCKED** / manual |

---

## 4. Not user-typed, but the same feeds help

| Curated value | Source | Note |
|---|---|---|
| Policy repo rate | RBI RSS (MPC resolution press release) | Event-driven; parse "policy repo rate … at X per cent" with a strict regex. Fixture NOT VERIFIED |
| WADTDR | RBI RSS ("Lending and Deposit Rates of Scheduled Commercial Banks") | Monthly; values may be revised between releases (seen in search results). Append, never overwrite |
| Overnight rate | RBI RSS ("Money Market Operations as on …", daily) | A possible alternative short rate; not a T-bill substitute without a methodology change |
| Small-savings rates | DEA OM / DoP SB Order (scanned PDF) | Stays curated (source-registry §2.16: OCR noise) |
| RBI DBIE | `data.rbi.org.in` (SPA, no documented API) | A GitHub org named "Reserve-Bank-Innovation-Hub" publishes `dbie.rbihub.in` (MIT code, README: "plus the scraping and processing pipeline"). Its official status and data licence are NOT VERIFIED → not used (unchanged from source-registry §2.8) |
| data.gov.in | OGD platform, GODL-India ("use, adapt and publish", commercial use allowed) | The CPI resources found are old base-2012 files with "The API for this resource does not exist". No T-bill or CPI-2024 API found there → not useful for these inputs |

---

## 5. Equity signals (context for the stated aim)

This audit covers only the inputs that exist today. For "when to buy and sell stocks", every free official
exchange source found so far is closed to automation (NSE ToU; BSE disclaimer; source-registry §2.11). Any equity
signal therefore depends on a licensed data feed (REQUIRES CONFIGURATION, paid) or on user-supplied files (e.g. the
user's own broker contract notes). The project rule also requires a documented, out-of-sample, cost- and tax-aware
backtest before any signal is shown, and that needs historical prices the app is not licensed to collect. Until one
of those changes, the honest answer for equities is "No suitable candidate" or abstain. See the separate
`research-equity-data-*.md` reports in this folder.

---

## 6. Prioritised plan

| Priority | Change | Effect | Effort |
|---|---|---|---|
| P0 | Fix the MoSPI adapter (§3.1, defects 1–5). Drop the credential requirement for filtered queries. Add a daily cron (hosted) / launchd (local) job | CPI arrives automatically for both bases; real-return figures stop abstaining | S |
| P0 | RBI RSS adapter for T-bill cut-offs (§3.2) with the price↔yield self-check | The risk-free series fills itself weekly; Sharpe stops abstaining | M |
| P1 | Render RBI citations as text, not links (§2.3) | Terms hygiene | XS |
| P1 | Update `known-limitations.md` and `source-registry.md` for the RBI 418 nuance and the MoSPI no-auth path | Docs match reality | XS |
| P1 | AMC portfolio-file import that computes credit facts (§3.5) | About 3 typed fields per debt scheme per month → 1 upload | M per AMC layout |
| P2 | Factsheet PDF extract-and-confirm (§3.4) | Duration, YTM, average maturity, riskometer | M per AMC |
| P2 | Exit-load SID grammar parser (§3.6) | Removes `EXIT_LOAD_UNKNOWN` for common loads | M |
| P2 | FD paste-a-table parser (§3.7) | Card-rate tables without typing | S |
| P3 | TER via AMFI JSON, only if the user opts in (§3.3) | TER/BER monthly per held AMC | S, plus the user's decision |
| P3 | India Bond Info T&C read; per-ISIN corporate-bond terms if permitted | Fewer typed bond fields | S after terms |

---

## 7. Sources (all accessed 2026-10-15)

| URL | Used for | Quote / evidence |
|---|---|---|
| https://api.mospi.gov.in/api/cpi/getCPIData?base_year=2024&series=Current&year=2026&month_code=9&state_code=1&sector_code=3&division_code=0&Format=JSON | CPI base 2024, no auth | probe 18:04Z: `"index":"109.49","inflation":"5.54"`, `"totalRecords":1` |
| https://api.mospi.gov.in/api/cpi/getCPIIndex?base_year=2012&series=Current&year=2025&month_code=12&state_code=99&sector_code=3&group_code=0&Format=JSON | CPI base 2012, no auth | probe: `"index":"198.0","inflation":"1.33","status":"F"` |
| https://pypi.org/project/mospi-esankhyiki/ (0.2.1 wheel, `esankhyiki/client.py`) | base-2024 endpoint routing | "# CPI base_year 2024 uses unified endpoint" → `/api/cpi/getCPIData` |
| https://github.com/nso-india/mospi-esankhyiki | code licence | "MIT License" (code only) |
| http://www.mospi.nic.in/copyrights-policy (via search) | MoSPI reproduction terms | "may be reproduced free of charge after taking proper permission by sending a mail to us" (NOT VERIFIED directly) |
| https://rbi.org.in/Scripts/rss.aspx | RBI feeds | "receive automatic site updates without having to check back to the site periodically" |
| https://www.rbi.org.in/pressreleases_rss.xml | feed probe | 200, 10 items, `cache-control: public, max-age=20` |
| https://www.rbi.org.in/scripts/BS_PressReleaseDisplay.aspx?prid=63803 | T-bill cut-off | "98.5920 (YTM: 5.7281%) 96.9592 (YTM: 6.2896%) 93.9220 (YTM: 6.4891%)"; "Press Release: 2026-2027/1325" |
| https://www.rbi.org.in/Scripts/Disclaimer.aspx | RBI terms | "secure permission from RBI prior to hyper-linking to, or framing, this Web Site"; "reserves all right to deny or restrict access" |
| https://www.amfiindia.com/terms-of-use | AMFI terms | "personal and non-commercial use only"; "No reverse engineering, linking, framing, or modification"; "shall not store electronically any significant portion" |
| https://www.amfiindia.com/ter-of-mf-schemes | TER page | "Base Expense Ratio (BER) as per Regulation 66(7) of SEBI (Mutual Funds) Regulations, 2026"; no download link in HTML |
| https://www.amfiindia.com/api/populate-te-rdata-revised (one probe) | TER JSON shape | 200 JSON; `meta.total` 3,189; string decimals |
| https://github.com/satwikbasu/indian-market-data-endpoints/blob/main/endpoints/amfi-ter-api.md | TER endpoint documentation (third party) | "AMFI rate-limits aggressively"; "discovered on 2026-05-21 via Playwright" |
| https://www.amfiindia.com/robots.txt, https://www.amfiindia.com/sitemap.xml | crawl rules, page list | Disallow `/admin/ /login/ /search/`; 13 sitemap URLs, no riskometer page |
| https://www.amfiindia.com/Themes/Theme1/downloads/circulars/SEBI/CU115-AMFI%20BP%20Cir%20No.%2088%20dt.%2030-Jul-2020-Additional%20disclosures%20in%20monthly%20Fact%20Sheets.pdf (via search) | factsheet fields | "Macaulay Duration, Modified Duration, Average Maturity and Yield to Maturity shall be disclosed separately" |
| https://www.sebi.gov.in/sebi_data/attachdocs/1347547815927.pdf (via search) | monthly portfolio | "on or before the tenth day of the succeeding month in a user-friendly and downloadable format (preferably in a spreadsheet)" |
| https://www.sebi.gov.in/website-policy.html (via search) | SEBI reuse | "may be reproduced free of charge after taking proper permission by sending a mail to us" |
| https://www.hdfcfund.com/disclaimer (via search) | AMC terms example | "may not reproduce, transmit, sell, display, distribute, publish … or commercially exploit" |
| https://sbi.bank.in/web/interest-rates/deposit-rates/retail-domestic-term-deposits | SBI card rates | HTML table; "with effect from" 15/12/2025 |
| https://sbi.bank.in/web/customer-care/disclaimer (via search) | SBI terms | "shall not be displayed or printed in any form in part or whole without the prior written approval of SBI" |
| https://www.hdfc.bank.in/useful-links/website-usage-terms (via search) | HDFC Bank terms | "except that which I may download for my own personal, non-commercial use" |
| https://www.ccilindia.com/documents/d/ccil/ccil_datasharing_policy_oct25 (via search) | CCIL terms | "discouraged from extracting the Data for any such arrangement using data streaming methods" |
| https://www.indiabondinfo.nsdl.com/bds-web/jsps/home/disclaimer.jsp (via search; direct fetch ECONNRESET) | India Bond Info | data from "issuers, stock exchanges, credit rating agencies and debenture trustees"; T&C NOT VERIFIED |
| https://vercel.com/docs/cron-jobs/usage-and-pricing | hosted scheduling | "Hobby accounts are limited to cron jobs that run once per day" |
| https://www.data.gov.in/resource/all-india-consumer-price-index-ruralurban-upto-january-2024 (via search) | data.gov.in CPI | "The API for this resource does not exist." |
| https://github.com/Reserve-Bank-Innovation-Hub/dbie.rbihub.in | DBIE mirror | README: "plus the scraping and processing pipeline"; official status NOT VERIFIED |
