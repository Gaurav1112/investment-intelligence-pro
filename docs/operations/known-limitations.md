# Known Limitations and Unimplemented Integrations

Status labels: **VERIFIED** · **IMPLEMENTED, NOT VERIFIED** · **REQUIRES CONFIGURATION** · **BLOCKED**.
Living document, last updated 2026-10-15 (track 5: open findings resolved).

## Data and integrations

| Item | Status | Detail |
|---|---|---|
| AMFI NAVAll (latest NAV) | VERIFIED (live, 2026-10-15) | 14,376 rows parsed; 251 rejected with reasons (241 zero-NAV segregated portfolios, 10 bad ISINs). The first live run exposed two defects, both fixed: AMC lines missing in 4 sections, and a unit-string mismatch that marked every row rejected. |
| AMFI NAV history backfill | VERIFIED (live, 1 year, HDFC Liquid Direct Growth) | AMFI's fund-house ids are unpublished and are discovered by probing (1 request per id). Earliest available date and maximum range per request: NOT VERIFIED (≤ 90-day windows used). |
| Exit loads | REQUIRES CONFIGURATION | No public source. Each non-liquid fund needs a user-entered load with a citation; until then it is excluded (`EXIT_LOAD_UNKNOWN`). SEBI-defined loads (liquid graded, overnight none) are built in. |
| T-bill entered from an auction cut-off | Limitation | The cut-off yield is the primary-auction price on that date. You can only get it through a future non-competitive bid (RBI Retail Direct). A secondary-market purchase price will differ. Settlement is approximated as the next calendar day. Face value is bought in whole ₹10,000 lots (minimum ₹10,000, multiples of ₹10,000 — RBI/2021-2022/124 of 12-Nov-2021, VERIFIED-PRIMARY for that notification; no later amendment was found on 2026-10-15). The cash left over is held at 0 % and flagged `UNINVESTED_REMAINDER_AT_ZERO`; amounts below one lot's cost are `BELOW_MINIMUM_TICKET`. |
| Same NAV date from two AMFI sources | Handled | NAVAll and the history report overlap on recent dates. Equal values are merged. Unequal values exclude the scheme with `SOURCE_CONFLICT` (found in the live run, 2026-10-15). |
| T-bill yields, FD rates | REQUIRES CONFIGURATION (manual entry with citation) | RBI blocks scripted access (HTTP 418) and prohibits caching. Banks publish no API. |
| G-secs, SDLs, corporate bonds | BLOCKED (no data path in v1 UI) | The engine supports them (QuantLib-checked), but there is no manual-entry form yet. Market prices need licensed sources (NSE/BSE/CCIL/FBIL terms). |
| Credit ratings | BLOCKED | Rating agencies prohibit reproduction without consent. Manual entry is planned. |
| CPI (MoSPI) | REQUIRES CONFIGURATION / NOT VERIFIED | The API needs user sign-up. Retrieval of the base-2024 series was not confirmed. No adapter is wired into the app. |
| mfapi.in | Disabled by design | Unofficial mirror. Off by default; never an authority. |
| AMFI category taxonomy | Limitation, handled conservatively | The live NAVAll mixes about 100 labels: legacy ("Income" with 4,555 rows, "Growth", "Gilt"), SEBI-style, and the 2026 renamed ones. Ambiguous labels (index/ETF/FoF/hybrid/life-cycle/legacy) get tax class UNKNOWN, so those funds are excluded rather than guessed. ELSS lock-in is detected from both the category and the scheme name. FMP and interval schemes are refused as close-ended. |
| Survivorship | Limitation | NAVAll lists live schemes only. Merged or wound-up schemes are missing, which biases category statistics upwards. A banner is shown on fund results. |
| Holiday calendars | Limitation | No curated RBI/NSE holiday calendar is loaded. Business-day counts treat weekdays as business days and carry the note `CALENDAR_UNVERIFIED`. T-bill settlement is approximated as the next calendar day. |

## Engine

| Item | Status | Detail |
|---|---|---|
| Tax engine | IMPLEMENTED, NOT VERIFIED | No independent tax oracle exists. 20 of 65 rules are NV (e.g. the T-bill income head, s.50AA mapping under ITA 2025). Results computed with NV rules are flagged. A Chartered Accountant review is required (13 open questions in `docs/research/indian-instruments-and-tax.md` §9). |
| Tax beyond 31-Mar-2027 | Assumption, flagged | FY2027-28 rates are not legislated yet. The gain is priced under the law in force on the coverage end (`tax.compute_tax(rates_as_of=…)`), assumed unchanged, while the holding period and acquisition-date conditions use the ACTUAL dates. The result equals "actual dates under unchanged law" (tested over every class and rule boundary) and is flagged `TAX_RULES_ASSUMED_UNCHANGED_AFTER_2027-03-31`. Until 2026-10-15 the transfer date itself was clamped, which taxed long equity holdings as STCG (RT-17, resolved). |
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

## Findings from the red-team audit (docs/audit/final-red-team-report.md)

| Id | Status | Detail (and the test that pins it) |
|---|---|---|
| RT-17 | **Resolved 2026-10-15** | Post-coverage tax keeps the actual holding period: rates from the last legislated year (`rates_as_of`), classification from the real dates; equity held 400 days past coverage is LTCG at 12.5 % above the exemption (₹9,750, not ₹41,600). Tests: `tests/redteam/test_redteam_tax_coverage.py` — `test_rt17_equity_held_400_days_past_coverage_is_ltcg_at_12_5_percent`, `test_rt17_debt_mf_bought_after_2023_is_slab_regardless_of_holding`, `test_rt17_after_coverage_equals_actual_dates_under_unchanged_law` (never under- or overstates vs. that assumption, across the 1-Apr-2023, 23-Jul-2024 and grandfathering boundaries), `test_rt17_parity_within_coverage_nothing_changes`. |
| RT-18 | Flagged | Each option assumes the ₹1.25 lakh LTCG exemption is unused. Results that rely on it carry `LTCG_EXEMPTION_ASSUMED_UNUSED` — now reachable with the shipped table (`test_rt17_equity_mf_candidate_past_coverage_gets_ltcg_and_exemption_flag`). |
| RT-19 | **Resolved by user decision** (policy 1.1.0) | Preservation objectives require ≥ 20 independent windows. |
| RT-20 | **Resolved by user decision** (policy 1.1.0) | Growth objectives are refused for horizons under 12 months. |
| RT-21 | Fixed by final reviewer | Untracked schemes keep only their latest NAV; held, watched and backfilled schemes keep history. |
| RT-22 | **Resolved 2026-10-15** | (a) A fund is redeemed `settlement_days` before the withdrawal date, so the NAV window is H − settlement days and proceeds arrive in time (conservative); the redemption date also drives the exit-load test, the lock-in test and the tax transfer date. (b) T-bills: whole ₹10,000 lots, remainder at 0 %, `BELOW_MINIMUM_TICKET` below one lot (RBI/2021-2022/124). Tests: `tests/redteam/test_redteam_settlement_and_tickets.py` — `test_rt22a_nav_window_is_horizon_minus_settlement`, `test_rt22a_redemption_date_drives_holding_period_for_tax`, `test_rt22a_exit_load_judged_on_the_redemption_day`, `test_rt22b_tbill_below_minimum_ticket_is_ineligible`, `test_rt22b_exactly_one_lot_is_eligible`, `test_rt22b_tbill_face_in_whole_lots_and_leftover_cash_at_zero`. Formula ids `CAND_MF_EMPIRICAL@2`, `CAND_TBILL@2`; `candidates@1.1.0`. |
| RT-23 | Open | A credit floor applies to rated instruments and Credit Risk Funds only. Other debt funds' portfolio credit quality is not known, so it is not checked (needs licensed rating data). |
| RT-24 | **Resolved 2026-10-15** | Forecast (B1): a step longer than 7 calendar days is a gap; > 2 % of observations behind a gap → `DATA_GAPS_EXCEED_GATE` (suppressed, validation-methodology §8 with the risk-methodology §1 gate); otherwise every window spanning a gap is excluded (`GAP_WINDOWS_EXCLUDED`) and walk-forward origins whose outcome spans a gap are not scored. Feasibility keeps its own spec gate (§4.4.1: > 2 % suspect month-end points → reject); that rejection is now a REFUSED result instead of an error, and ≤ 2 % suspect points remain flagged `SUSPECT_GRID_POINTS` as the spec says. Tests: `tests/redteam/test_redteam_data_gaps.py` (8). |
| RT-26 | **Resolved 2026-10-15** (policy decided) | `canonical_json@2`: −0 → 0, aware datetimes → UTC, floats rejected anywhere, non-finite rejected. Exact Decimal digits are deliberately kept: published precision is provenance (`25.9504` ≠ `25.95040`), and computed Decimals are deterministic for identical inputs. Recorded as `canonical` in run versions (stored run hashes of earlier versions are not recomputed or compared anywhere). Tests: `tests/redteam/test_redteam_canonical.py`. |
| RT-27 | **Resolved 2026-10-15** | `include_fixtures` → 400 `FIXTURES_NOT_ALLOWED` in prod with no run stored; the MF history gate counts only usable rows (ok/manual/fixture, not superseded, one per date); FD ids are `fd:<institution_type>:<slug>:<tenure>d`. FDs entered under the old `fd:<slug>:<tenure>d` id keep working; re-entering one creates the new id (no user data existed at the change). Tests: `tests/redteam/test_redteam_rt27.py` (5). |
| RT-28 | **Resolved 2026-10-15** | XIRR with ≥ 2 sign changes searches each same-sign grid cell for an interior extremum; roots hidden there (crossing or double) give `NOT_DETERMINABLE` (`IRR_NOT_DETERMINABLE`), never "no root" or a single headline rate. Tests: `tests/redteam/test_redteam_xirr.py` (5). |

## Product

| Item | Status | Detail |
|---|---|---|
| Optional LLM explanations | Not built in v1 | The supervisor supports an `llm_rephrase` hook with numeric and banned-phrase validation (tested). No adapter or provider configuration UI exists yet. The deterministic template writer is complete on its own. |
| CAS (CAMS/KFintech) statement import | Not built | CSV/XLSX holdings import only. |
| Clean-machine setup | VERIFIED (clean checkout, 2026-10-15) | Fresh clone: `make setup`, `make check` and `make test-browser` all pass (`docs/operations/deployment.md`). Package caches and the toolchain were already present; a machine without uv/Node/pnpm, or offline, is NOT VERIFIED. |
| UI polish pass | Deferred by request | The user asked to prioritise functionality, so polish is a later stage. |

## Regulatory

Personal use only. Any sharing or hosting would need professional review first (`docs/security/regulatory-readiness.md`, 10 open
questions). AMFI's terms forbid redistribution.
