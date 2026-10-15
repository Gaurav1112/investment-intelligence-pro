# Source probes (2026-10-15) — findings only, no raw data

On 2026-10-15 every source in [`../source-registry.md`](../source-registry.md) was probed live from the author's
machine, and the raw responses were saved to check formats. **Those raw responses are not published here.** AMFI's
terms allow personal, non-commercial use only and forbid redistribution. NSE's terms prohibit automated collection and
reuse. RBI says caching its pages is prohibited, and CRISIL and other publishers restrict reproduction. What this
repository keeps:

- **What each probe proved** (the table below and the source registry).
- **Synthetic "shape" samples.** Each one has the same byte layout, delimiters, line endings, keys and edge cases as
  the real response, but **every name, code, ISIN, NAV, rate and date-specific value is fictional**. They are enough
  to read and test the parsers without the real data.

| Source (registry id) | Probed (UTC) | What the probe proved | Synthetic shape sample |
|---|---|---|---|
| AMFI NAVAll (`amfi.navall`) | 2026-10-15T05:34:19Z | 302 → `portal.amfiindia.com`; `text/plain`, CRLF, `;`-separated 8-column header; section line → AMC line → rows; `-` and empty ISIN cells; `;;;` rows with empty plan/option; stale NAV dates kept (e.g. 2015, 2017); U+2019 in category names; some sections carry no AMC line (handled by brand-checked carry-forward) | `backend/tests/fixtures/data/amfi_navall_excerpt.txt` |
| AMFI NAV history (`amfi.navhistory`) | 2026-10-15T05:34:48Z | Different column order from NAVAll; one row per scheme per business day; no weekend rows; 3-dp NAVs | `backend/tests/fixtures/data/amfi_navhistory_excerpt.txt` |
| AMFI scheme master (`amfi.schememaster`) | 2026-10-15T05:43:36Z | CSV; the two ISIN columns are glued together with no delimiter; legacy categories next to SEBI-2017 ones; leading space in `" Closure Date"` | `backend/tests/fixtures/data/amfi_schemedata_excerpt.csv` |
| mfapi.in (`mfapi.in`, UNOFFICIAL) | 2026-10-15T05:34:35Z | JSON `meta` + `data[{date: dd-mm-yyyy, nav}]`; NAVs padded to 5 dp; full history ~3,000 rows for a 2013 scheme | `backend/tests/fixtures/data/mfapi_latest.json` |
| MoSPI CPI (`mospi.cpi`) | 2026-10-15T05:37:23Z | Without credentials the API returns only 10 of `totalRecords` (84) records → the adapter refuses with `UNAUTHENTICATED_CAP` | `backend/tests/fixtures/data/mospi_cpi_unauth10_synthetic.json` |
| NSE holiday master (`calendar.*`) | 2026-10-15T05:35:40Z | Undocumented JSON keyed by segment (`CM`, `MF`, `IRD`, …) with `tradingDate` dd-Mon-yyyy rows; ToU prohibits automated use → **manual curation only** | [`nse_holiday_master.shape.json`](./nse_holiday_master.shape.json) |
| RBI home page "Current Rates" (`rbi.rates`) | 2026-10-15T05:42:20Z | Policy rates, reserve ratios, FBIL reference rates and the latest T-bill cut-offs appear as plain text; a plain curl user agent gets HTTP 418 | [`rbi_current_rates.shape.txt`](./rbi_current_rates.shape.txt) |
| RBI T-bill press releases (`rbi.pr.tbill`) | 2026-10-15T05:40:05Z | Stable titles ("…T-Bill Auction Result: Cut-off", "Treasury Bills: Full Auction Result"); the cut-off table gives price per ₹100 and "YTM" per tenor | [`rbi_tbill_cutoff.shape.html`](./rbi_tbill_cutoff.shape.html) |
| India Post small-savings order (`dop.sb`) | 2026-10-15T05:43:05Z | Scanned PDF with OCR noise → not reliably machine-parseable → manual entry with citation | [`dop_sb_order.shape.txt`](./dop_sb_order.shape.txt) |

Public facts quoted elsewhere in the docs, such as one RBI cut-off yield used in a hand-checked test, are cited to their
official source URL rather than to a saved copy.
