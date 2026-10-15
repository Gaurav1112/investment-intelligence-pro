# Known Limitations and Unimplemented Integrations

Status labels: **VERIFIED** · **IMPLEMENTED, NOT VERIFIED** · **REQUIRES CONFIGURATION** · **BLOCKED**.
Living document, last updated 2026-10-15.

## Data and integrations

| Item | Status | Detail |
|---|---|---|
| AMFI NAVAll (latest NAV) | VERIFIED (live, 2026-10-15) | 14,376 rows parsed; 251 rejected with reasons (241 zero-NAV segregated portfolios, 10 bad ISINs). The first live run exposed two defects, both fixed: AMC lines missing in 4 sections, and a unit-string mismatch that marked every row rejected. |
| AMFI NAV history backfill | VERIFIED (live, 1 year, HDFC Liquid Direct Growth) | AMFI's fund-house ids are unpublished and are discovered by probing (1 request per id). Earliest available date and maximum range per request: NOT VERIFIED (≤ 90-day windows used). |
| Exit loads | REQUIRES CONFIGURATION | No public source. Each non-liquid fund needs a user-entered load with a citation; until then it is excluded (`EXIT_LOAD_UNKNOWN`). SEBI-defined loads (liquid graded, overnight none) are built in. |
| T-bill entered from an auction cut-off | Limitation | The cut-off yield is the primary-auction price on that date. You can only get it through a future non-competitive bid (RBI Retail Direct). A secondary-market purchase price will differ. Settlement is approximated as the next calendar day. |
| Same NAV date from two AMFI sources | Handled | NAVAll and the history report overlap on recent dates. Equal values are merged. Unequal values exclude the scheme with `SOURCE_CONFLICT` (found in the live run, 2026-10-15). |
| T-bill yields, FD rates | REQUIRES CONFIGURATION (manual entry with citation) | RBI blocks scripted access (HTTP 418) and prohibits caching. Banks publish no API. |
| G-secs, SDLs, corporate bonds | REQUIRES CONFIGURATION (manual entry with citation); IMPLEMENTED, NOT VERIFIED against live quotes | Entered on Fixed income → "G-secs & bonds" (ISIN check digit validated; clean price per ₹100 **or** YTM, with its date and page URL). Nothing is fetched: NSE/BSE/CCIL/FBIL terms restrict automated use. Discovery, compare, scenario and simulate evaluate them with the QuantLib-checked engine. **Held to maturity** (maturity ≤ withdrawal): contractual coupons + redemption; coupons are kept as cash at 0 % until withdrawal (flagged); a callable bond takes the worst of its maturity and call paths. **Early exit** (maturity > withdrawal): a band of stress scenarios at the entry yield +100 / 0 / −100 bp plus the exit spread (25 bp G-sec/SDL, 100 bp corporate; NOT VERIFIED), tier T3, loss frequency unknown, so it is excluded for capital preservation. Unlisted corporates are never sold early. Quotes older than 7 days → `STALE_DATA`. Settlement is the next calendar day (no holiday calendar). Whole bonds only; the remainder stays as idle cash. A transaction spread left empty is computed at 0 and flagged `TRANSACTION_COST_UNKNOWN` (exit cost then counts as 100 %). Purchased accrued interest is not deducted from taxable interest (overstates tax); capital losses are taxed at 0 with no set-off (flagged). Odd first coupons are refused unless already paid before settlement; FRBs, STRIPS, inflation-indexed bonds and step-up coupons are out of scope. |
| SDL certainty tier | Design decision (conservative) | ADR-0005 puts only Government of India paper in T1 ("contractual sovereign"); risk-methodology §7.2 calls SDLs quasi-sovereign state credit, "shown separately". SDLs held to maturity are therefore **T2**, and the credit floor sees them as **AAA** (never SOVEREIGN), so a SOVEREIGN-only floor excludes them. Flag `SDL_STATE_GOVERNMENT_CREDIT_NOT_SOVEREIGN`. |
| Credit ratings | REQUIRES CONFIGURATION (manual entry with citation) | Rating agencies prohibit reproduction without consent, so ratings are never fetched. A corporate bond requires rating, agency, rating-action date and the rationale URL. A rating older than 12 months → `STALE_RATING`; none → `MISSING_RATING`; both exclude the bond. Below AAA, a bond held to maturity is T3 and fails preservation objectives (`UNINSURED_CREDIT_EXPOSURE`). Default and downgrade losses are not modelled; corporate loss frequency is unknown, never 0. |
| CPI (MoSPI) | REQUIRES CONFIGURATION / NOT VERIFIED | The API needs user sign-up. Retrieval of the base-2024 series was not confirmed. No adapter is wired into the app. |
| mfapi.in | Disabled by design | Unofficial mirror. Off by default; never an authority. |
| AMFI category taxonomy | Limitation, handled conservatively | The live NAVAll mixes about 100 labels: legacy ("Income" with 4,555 rows, "Growth", "Gilt"), SEBI-style, and the 2026 renamed ones. Ambiguous labels (index/ETF/FoF/hybrid/life-cycle/legacy) get tax class UNKNOWN, so those funds are excluded rather than guessed. ELSS lock-in is detected from both the category and the scheme name. FMP and interval schemes are refused as close-ended. |
| Survivorship | Limitation | NAVAll lists live schemes only. Merged or wound-up schemes are missing, which biases category statistics upwards. A banner is shown on fund results. |
| Holiday calendars | Limitation | No curated RBI/NSE holiday calendar is loaded. Business-day counts treat weekdays as business days and carry the note `CALENDAR_UNVERIFIED`. T-bill settlement is approximated as the next calendar day. |

## Engine

| Item | Status | Detail |
|---|---|---|
| Tax engine | IMPLEMENTED, NOT VERIFIED | No independent tax oracle exists. 20 of 65 rules are NV (e.g. the T-bill income head, s.50AA mapping under ITA 2025). Results computed with NV rules are flagged. A Chartered Accountant review is required (13 open questions in `docs/research/indian-instruments-and-tax.md` §9). |
| Tax beyond 31-Mar-2027 | Assumption, flagged | FY2027-28 rates are not legislated yet. The transfer date is clamped to the coverage end, which never understates tax, and the result is flagged `TAX_RULES_ASSUMED_UNCHANGED_AFTER_2027-03-31`. |
| Old tax regime, non-residents, surcharge marginal relief | Not modelled | An illustrative 30 % slab is used and labelled. **Correction (red-team RT-13):** an earlier version of this document claimed every simplification can only overstate tax. That was false: surcharge was always zero, which understates tax above ₹50 lakh income. There is now an optional surcharge-band field; when it is left blank, results say tax may be understated. Surcharge marginal relief is still not modelled. |
| XIRR near −100 % over long spans | Known edge | The Decimal verification tolerance can reject a correct root. The engine raises `NumericalError` rather than return a number. |
| 30E/360 month-end variant (G-secs) | VERIFIED (secondary) only | Confirm against the FIMMDA handbook. Coupon periods that start on a February month-end raise `UnsupportedSchedule`. |
| SEBI ACT/ACT anchor (corporate bonds) | IMPLEMENTED, NOT VERIFIED | `dates.year_fraction(ACT_ACT_SEBI)` checks for 29-Feb only within a single interval. Coupon amounts use the fixed-income module's own SEBI implementation. |
| Bond pricing duplicated in `scenarios.py` | Tech debt | Built before `fixed_income.py` existed. Consolidate. |
| Block-length selection (bootstrap) | BLOCKED | Needs `arch` (Politis–White). Block length is a caller parameter. |
| FD premature-withdrawal penalty | REQUIRES CONFIGURATION | Bank-specific, so there is no default. If unknown, liquidity is treated as unavailable until maturity. |
| Monthly-SIP levers, Christoffersen test, PIT histogram, loss-ratio monitor | IMPLEMENTED, NOT VERIFIED | |

## Analysis endpoints (Stage D)

| Item | Status | Detail |
|---|---|---|
| Inflation shock / real return | BLOCKED | No CPI series has been ingested (MoSPI needs user configuration). Always returns `not_applicable`. |
| Sharpe ratio | BLOCKED | No stored 91-day T-bill yield series. Refused as `RISK_FREE_SERIES_UNAVAILABLE`, and as `REFUSED_SMOOTHED_NAV` for debt, liquid and hybrid funds. |
| Rate/spread shocks on debt funds | BLOCKED | Scheme duration is not stored (it needs factsheet data). |
| FD early-exit scenario | BLOCKED | The card rate for the shorter tenure is not stored. |
| Volatility for liquid/overnight/money-market funds | Refused by design | Their NAVs are smoothed. A weekly series is needed and has not been built. |
| Equity shock | Simplification, labelled | Applied to the fund's NAV with β = 1. Market beta is not estimated. |
| Scenario impacts | Before tax | Tax on the changed gain is not recomputed. |
| Forecast inputs | Note | NAVs are converted Decimal→float in the service layer before the forecasting engine, which is float-based by design. Outputs return to Decimal at the boundary. |
| DICGC aggregation | Conservative | "Existing deposits" entered against several FDs at one bank are summed. This can overstate exposure; it never understates it. |

## Open findings from the red-team audit (docs/audit/final-red-team-report.md)

| Id | Status | Detail |
|---|---|---|
| RT-17 | Accepted (conservative) | The tax-coverage clamp also shortens the holding period, so equity sold after 31-Mar-2027 is taxed as STCG. That overstates tax (about 4.3× in one probe) and biases growth comparisons against equity. Overstating is the safe direction; it resolves when the FY2027-28 rates are added. |
| RT-18 | Flagged | Each option assumes the ₹1.25 lakh LTCG exemption is unused. Results that rely on it carry `LTCG_EXEMPTION_ASSUMED_UNUSED`. |
| RT-19 | **Resolved by user decision** (policy 1.1.0) | Preservation objectives require ≥ 20 independent windows. Original issue: | "Loss frequency ≤ 1 %" can pass with 10–19 independent windows and zero losses; by the rule of three, that evidence only bounds the true rate at about 15–30 %. Such results carry `LOW_EVIDENCE`. Tightening the gate is a product decision. |
| RT-20 | **Resolved by user decision** (policy 1.1.0) | Growth objectives are refused for horizons under 12 months. |
| RT-21 | Fixed by final reviewer | Untracked schemes keep only their latest NAV; held, watched and backfilled schemes keep history. |
| RT-22 | Open | Fund windows ignore the settlement lag (slightly optimistic for very short horizons). T-bills have no minimum ticket or lot size. |
| RT-23 | Open | A credit floor applies to rated instruments and Credit Risk Funds only. Other debt funds' portfolio credit quality is not known, so it is not checked. |
| RT-24 | Open | Forecast windows that span a data gap are not gated. |
| RT-26–28 | Open (low) | `content_hash` is not value-canonical (`25.9504` vs `25.95040`); `include_fixtures` is accepted in prod (rows remain badged); XIRR with two roots in one grid cell reports "no root" (no number is shown either way). |

## Product

| Item | Status | Detail |
|---|---|---|
| Optional LLM explanations | Built, optional, off by default; IMPLEMENTED, NOT VERIFIED against a live model | One OpenAI-compatible adapter: a local loopback model, or an allowlisted free-tier cloud provider that receives a redacted packet. The model only rewords the deterministic claims; on any validation or connection failure the template is shown. Tested against a stub server only (no local model was running when it was built). Cloud providers' data-use terms are NOT VERIFIED. In cloud mode, sentences with personal values are held back and shown unreworded. |
| CAS (CAMS/KFintech) statement import | **IMPLEMENTED, NOT VERIFIED** against a real CAMS/KFintech PDF | Detailed CAS (PDF + password) → preview → confirm with SHA-256 → apply (backup first, one transaction). Parsed in memory with casparser 1.4.1; tested only on a SYNTHETIC CAMS-style PDF generated at test time (fictional investor, RC4-128 encrypted) plus mapping unit tests. Real statement layouts are unverified until you import one. Known gaps: (1) schemes match only by the exact ISIN printed on the statement against locally stored instruments, and AMFI ingestion stores only Direct-plan Growth schemes (plus held/watched ones), so Regular-plan, IDCW and reinvestment-option ISINs are rejected as unmatched; (2) stamp duty, STT and TDS are ignored (the ledger has no fee transaction used by FIFO), so cost basis excludes stamp duty; (3) gifts, reversals and segregated-portfolio allotments are rejected and show up as reconciliation mismatches; (4) a statement that starts with an opening balance cannot reconcile and later sells may be refused as OVERSELL; (5) summary CAS and NSDL/CDSL depository CAS are refused (no transaction ledger); (6) CAS rows are stored with `source = csv_import` because the schema CHECK allows only `manual`/`csv_import` (widening it needs a table-rebuild migration); the import ledger records `kind = cas_pdf`; (7) the request body cap is the global 5 MiB (`Settings.max_body_bytes`), so the service's 10 MiB CAS cap is not reachable; (8) a PDF with an unsupported security *revision* of the Standard handler is reported by PDFium as a wrong password, not as unsupported encryption (an unknown security *handler* is reported correctly). |
| Clean-machine setup | IMPLEMENTED, NOT VERIFIED | |
| UI polish pass | Done (2026-10-15) | See `docs/screenshots/ux/`. |

## Regulatory

Personal use only. Any sharing or hosting would need professional review first (`docs/security/regulatory-readiness.md`, 10 open
questions). AMFI's terms forbid redistribution.
