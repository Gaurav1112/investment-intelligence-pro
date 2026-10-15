# Final Red-Team Report (Phase 14)

## Backend — independent quantitative red team (Agent J), 2026-10-15

**Scope:** `backend/src/iip` and `backend/tests`. The frontend is out of scope; its agents were editing `frontend/` at the same time.

**Stance:** the engine was treated as wrong until shown otherwise. Every finding below was reproduced by running code. Every high-severity finding has a failing test in `backend/tests/redteam/test_redteam_*.py`, and each of those tests passes after the fix. No existing test was weakened.

**How it was done:** I reviewed the engine, supervisor, discovery and services myself. Three read-only sub-audits ran in parallel: tax and fixed income; forecasting, feasibility and analysis; data, API and security. Their findings were re-checked and are folded in below.

### Verification (actual run, `backend/`, after the fixes)

| Command | Result |
|---|---|
| `.venv/bin/pytest -q -p no:warnings` | **1,210 passed, 1 skipped, 0 failed** |
| `.venv/bin/pytest -q -p no:warnings tests/redteam` | **53 passed** (new) |
| `.venv/bin/ruff check src tests` | All checks passed |
| `.venv/bin/mypy` (strict, `src/iip`) | Success: no issues in 69 source files |

During the audit, another agent added freshness/provenance work to the same backend files: `engine/freshness.py`, `services/explain.py`, and `freshness` badges in discovery. That left 4 tests failing that this audit did not cause:
- the analysis/discovery parity test (×2);
- `test_compare_rows_reconcile_and_are_explained`;
- `test_portfolio.py::test_summary_reconciles_and_excludes_stale`.

They were fixed with the smallest change consistent with those tests' intent:
- `services/analysis.py` T-bill/FD provenance now carries the same `badge(prov, as_of)` that discovery adds;
- `services/explain.py` `source_ref` keeps `obs_id`/`evidence`, so portfolio valuations again link to their stored observation. Losing that link was a provenance regression.

The full suite was green when this audit began.

### Findings

Severity means the potential to mislead a real decision. H = high, M = medium, L = low.

| ID | Sev | Finding | Reproduction (failing before → passing after) | Status |
|---|---|---|---|---|
| RT-01 | **H** | Uninsured or partly-insured deposits were ranked for capital preservation and slipped past a credit floor. Covers NBFC deposits and deposits above the DICGC cover. | `test_redteam_ranking.py::test_rt01_*` (6), `test_redteam_discovery.py::test_rt01_nbfc_deposit_not_ranked_for_capital_preservation_end_to_end` | Fixed |
| RT-02 | **H** | The profile restriction `exclude_nbfc_deposits` (default **on**) was never read. NBFC deposits ranked anyway. | `test_redteam_discovery.py::test_rt02_*` (2) | Fixed |
| RT-03 | **H** | An equity fund with a short, lucky history (100 days, 7-day horizon) ranked **#1 for capital preservation**. Separately, one ancient NAV could manufacture "independent windows" that do not exist. | `test_redteam_ranking.py::test_rt03_*` (3) | Fixed |
| RT-04 | **H** | Future-dated FD rates and T-bill yields, e.g. a citation dated 2030 by typo, bypassed the staleness rule and were ranked. A mistyped future T-bill quote could never be corrected. | `test_redteam_discovery.py::test_rt04_*` (3) | Fixed |
| RT-10 | **H** | Forecast bands were shown for schemes with under 1 year of history, which spec §8 says to suppress. | `test_redteam_analysis.py::test_rt10_*` | Fixed |
| RT-11 | **H** | LOW_EVIDENCE feasibility still published percentiles, quantile dots and drawdown percentiles, against spec §4.5 "counts only". | `test_redteam_analysis.py::test_rt11_*` (2) | Fixed |
| RT-13 | **H** | Discovery hard-coded surcharge = 0 for every user, so tax was understated for income above ₹50 lakh. This contradicts the docs' claim that simplifications "only overstate tax". | `test_redteam_analysis.py::test_rt13_*` (3) | Fixed (new optional input + disclosure) |
| RT-14 | **H** | For a withdrawal "tomorrow", a liquid fund ranked #1 even though redemption proceeds settle T+1, after the date the cash is needed. | `test_redteam_ranking.py::test_rt14_*` | Fixed |
| RT-05 | M | An instrument **name** containing a banned phrase raised `ComplianceViolation`, so every Discovery run returned HTTP 500. Examples: "Assured Returns Bank", "SEBI-approved …". | `test_redteam_discovery.py::test_rt05_*` (4) | Fixed |
| RT-06 | M | The same T-bill from a fixture and from a manual entry produced duplicate candidate ids. Ranking raised `InvalidInput` (HTTP 500). | `test_redteam_discovery.py::test_rt06_*` | Fixed |
| RT-07 | M | Supervisor numeric/phrase validator bypasses, relevant to the optional LLM path. Spelled-out numbers, sign flips, multipliers, zero-width/soft-hyphen/homoglyph/full-width obfuscation and double spaces all got through. Dates after a space were also wrongly split. | `test_redteam_supervisor.py::test_rt07_*` (21) | Fixed |
| RT-08 | M | The SEBI liquid-fund exit load was overstated 100×: 0.70 % instead of 0.0070 %. | `test_redteam_ranking.py::test_rt08_*` | Fixed |
| RT-09 | M | The Supervisor returned **ANSWERED** with no required worker run at all, i.e. with an empty worker list. | `test_redteam_supervisor.py::test_rt09_*` | Fixed |
| RT-12 | M | Forecast walk-forward validation used NAVs **after `as_of`** (look-ahead in coverage, pinball and MAE). | `test_redteam_analysis.py::test_rt12_*` | Fixed |
| RT-15 | M | A re-entered FD rate kept its first entry's timestamp, so provenance showed it "retrieved" before the date it describes. | `test_redteam_discovery.py::test_rt15_*` | Fixed |
| RT-16 | M | A forecast on a stale NAV, or with a band that failed its own coverage gate, was reported as plain `OK`. | `test_redteam_analysis.py::test_rt16_*` | Fixed (warnings) |
| RT-17 | M | The tax-coverage clamp shortens the *holding period*, not just the rate year. Any equity horizon past 31-Mar-2027 is taxed as STCG; in one example the overstatement was about 4.3×, which biases growth comparisons against equity. | sub-audit probe (see below) | **Not fixed** |
| RT-18 | M | Each candidate gets the full ₹1.25 lakh equity LTCG exemption, as if unused, with no warning. | sub-audit probe | **Not fixed** |
| RT-19 | M | The preservation gate "loss frequency ≤ 1 %" can be met with 10–19 independent windows and zero losses. That evidence cannot support 1 %; by the rule of three the upper bound is about 15–30 %. | analysis | **Not fixed** (spec-defined) |
| RT-20 | M | Growth objectives are accepted for horizons under 12 months, although risk-methodology §9 Step 4 says "Growth (H ≥ 12 months …)". | analysis | **Not fixed** (behaviour change) |
| RT-21 | M | AMFI data minimisation: every in-scope scheme accumulates a daily NAV archive. source-registry §2.1 says to keep only held or watched schemes. | sub-audit probe (`r3_minimise.py`) | **Not fixed** |
| RT-22 | M | A fund's empirical window uses the full horizon H, but proceeds arrive at H + settlement, a small optimism for short H. T-bills have no minimum ticket or lot size; ₹1 "buys" a T-bill. | `scratchpad edge.py` | **Not fixed** |
| RT-23 | M | Credit floors are silently skipped for every debt fund except Credit Risk Funds, because a fund has `credit_rating=None`. | analysis | Partly fixed (Credit Risk Funds only) |
| RT-24 | M | Forecast windows that span a data gap are not gated (spec §8 "gaps beyond the gate"). | sub-audit probe | **Not fixed** |
| RT-25 | L | T-bill yields ignored `quality_status`. The T-bill source was hard-coded as RBI, so a fixture showed as an RBI release. | covered by `test_rt04_*`/`test_rt06_*` code path | Fixed |
| RT-26 | L | `content_hash` is not value-canonical: `25.9504` ≠ `25.95040`, `-0` ≠ `0`, and UTC ≠ +05:30 for the same instant. Floats are accepted. | sub-audit probe | **Not fixed** |
| RT-27 | L | `include_fixtures` is accepted by `/api/discover` in prod (rows are still badged FIXTURE). The MF history gate counts rejected rows. FD ids are slugs, so different institution types can collide. | sub-audit probes | **Not fixed** |
| RT-28 | L | XIRR with two roots in one grid cell reports "no root" instead of "not determinable" (no number is shown either way). | sub-audit probe | **Not fixed** |

### High-severity details

**RT-01: uninsured deposits treated as capital-preserving**
- **Root cause:**
  - `fd_candidate` keeps every deposit `is_contractual=True`. An uninsured one gets `loss_frequency=None` and `credit_rating=None`.
  - `ranking._eligibility` applied the "unknown loss → never assumed safe" rule only to *non-contractual* candidates.
  - It skipped the credit floor whenever `credit_rating is None`.
  - So an NBFC FD passed objectives A/B/C, even with a floor of AAA. A ₹5,00,000 bank FD, whose maturity value exceeds the ₹5 lakh cover, also passed.
- **Spec:** risk-methodology §9 Step 1 lists the *DICGC limit* and the *credit floor* as hard constraints.
- **Fix:**
  - `engine/ranking.py:191`: for preserving objectives, a contractual candidate outside T1/T2 fails with `UNINSURED_CREDIT_EXPOSURE`. The existing `test_contractual_candidate_needs_no_loss_frequency` (a T1 T-bill) still passes.
  - `engine/candidates.py:311`: an uninsured deposit is `UNRATED`, so it fails any floor.
  - `engine/candidates.py:620`: SEBI "Credit Risk Fund" is `UNRATED` for floor purposes (≥ 65 % in paper rated AA and below, by mandate).
  - Post Office Time Deposits are Government of India obligations, not DICGC. They would otherwise be excluded as "uninsured". They are now T1/SOVEREIGN via `fd_candidate(sovereign_backed=…)` (`engine/candidates.py:235`). The institution type is recorded at entry (`services/instruments.py:154`).
- **Boundary verified:** exposure of exactly ₹5,00,000 (existing deposits + maturity value) is T2; ₹0.01 more is T3 (`test_rt01_dicgc_boundary_exactly_at_cover_is_insured`).
- **Residual risk:**
  - Debt funds other than Credit Risk Funds still bypass a credit floor, because portfolio ratings are not stored (BLOCKED: rating licences). The criteria text "Credit rating at or above X" should say it applies to rated instruments only.
  - FDs entered before this change have no recorded institution type. With "exclude NBFC deposits" on, they are excluded if uninsured, and a pre-existing post-office FD is treated as uninsured until re-entered.

**RT-02: NBFC exclusion ignored**
- **Root cause:** `Profile.exclude_nbfc_deposits` was never read. `deposit_terms` stores only `dicgc_eligible`, which cannot tell an NBFC from a post office.
- **Fix:**
  - The type is stored at entry (`services/instruments.py:154`).
  - `services/discovery.py:632` (`_exclude_nbfc_deposits`) excludes NBFC/HFC deposits, and uninsured deposits of unknown type, with `EXCLUDED_BY_USER`. This applies in personalised mode.
- **Residual:** `compare` (analysis) does not apply profile restrictions, by design: the user picked the instruments.

**RT-03: short or lucky histories**
- **Root cause:**
  - `mf_candidate` had no minimum history length.
  - It counted independent windows as `span // H`. Discovery admits a scheme at 60 NAVs, so about 3 months.
  - A 100-day rising equity series at H = 7 gave 14 "independent windows", zero losses and passed capital preservation.
  - A single 2012 NAV in front of 4 months of data gave a "5th percentile" band labelled with 160+ windows.
- **Fix:**
  - `engine/candidates.py:30,504`: `MIN_HISTORY_DAYS = 365` (validation-methodology §8, "newly launched (< 1 year)" → suppress).
  - `engine/candidates.py:419` (`independent_window_count`): counts the distinct H-day buckets that contain an actual window start. This equals `span // H` for gap-free series, verified by `test_rt03_long_continuous_history_still_evaluated_with_full_band`.
- **Residual:**
  - History length is measured on *stored* NAVs, so a fund older than its backfill is also refused (conservative).
  - See RT-19 for the evidence threshold itself.

**RT-04: future-dated manual data**
- **Root cause:** the staleness tests `(as_of − d).days > N` pass for negative ages. The T-bill SQL selected `MAX(observation_date)` with no `≤ as_of` bound.
- **Fix:**
  - `services/discovery.py:293` (`tbill_quote`) picks the latest usable quote on or before `as_of`, filtered to `ok/manual/fixture`. If only future quotes exist, the result is `LOOK_AHEAD`. Disagreeing same-date quotes are a `SOURCE_CONFLICT`. The real `source_id` is passed through.
  - `services/discovery.py:255`: FD `LOOK_AHEAD`.
  - Mirrored in `services/analysis.py:282,333` so compare and discovery stay identical.
- **Residual:** the API still accepts a future `citation.as_of` at entry. It is now inert, but the UI should warn when the value is entered.

**RT-10: forecast for funds under 1 year old**
- **Root cause:** `forecast()` gated only on n_eff.
- **Fix:** `services/analysis.py:1551` refuses with `INSUFFICIENT_HISTORY` when stored history is under 365 days.

**RT-11: LOW_EVIDENCE showing percentages**
- **Root cause:** the engine hid percentiles only on REFUSED, and the service emitted them whenever they were present.
- **Fix:** `services/analysis.py:1456`. Percentiles, dots and in-window drawdown percentiles are emitted only when SUFFICIENT. Counts and the full-history drawdown remain.

**RT-13: surcharge**
- **Root cause:** `services/discovery.py` `_tax_profile` passed `surcharge_rate=0`, and the profile had no way to supply a band.
  - Example: the tax on a ₹1 lakh T-bill gain is ₹31,200 with no surcharge, versus ₹39,000 at the 25 % band.
- **Fix:**
  - Optional `Profile.surcharge_rate`, validated to the new-regime bands 0 / 0.10 / 0.15 / 0.25 (`services/profile.py:20,53`).
  - When it is absent, the tax basis says so explicitly: "NO surcharge is applied — tax is understated if your total income exceeds ₹50 lakh" (`services/discovery.py:125`; mirrored in `analysis.Context.describe`).
- **Residual:**
  - Users who leave it blank still get understated tax above ₹50 L, now disclosed.
  - `docs/operations/known-limitations.md` ("Simplifications can only overstate tax") is **wrong** for surcharge and should be corrected by its owner.
  - The frontend has no field for the new input yet.

**RT-14: cash not available by the withdrawal date**
- **Root cause:** `mf_candidate` set `horizon_fit=True` regardless of settlement.
- **Fix:** `engine/candidates.py:483`. `horizon ≤ settlement_days` gives `HORIZON_MISMATCH` (redemption settles T+n).
- **Residual:** RT-22. The return window still uses H rather than H − settlement.

### Medium findings that were fixed

**RT-05: banned phrase in a name**
- **Fix:** `supervisor/synthesis.py:48,74`. The guard now scans *our* copy: the template plus engine-computed displays. Observation and user-input displays, such as names and the amount, are data and are rendered verbatim.
- `test_rt05_banned_phrase_in_our_own_template_copy_still_fails_loudly` and the existing `test_banned_template_copy_fails_loudly` still pass.

**RT-07: validator bypasses**
- **Fix:** `supervisor/compliance.py:19-49,134`.
  - A sign-, exponent- and multiplier-aware number token.
  - Rejection of spelled-out quantities. "one" is allowed; "percent" is still caught.
  - A `normalise()` step: NFKC, strip invisible characters, unify dashes, map common Cyrillic/Greek look-alikes, collapse whitespace.
  - The "date after a space was split into three numbers" defect is fixed.
- **Residual:**
  - The look-alike map is not the full Unicode confusables table.
  - Numbers inside a *name* fact still become allowed tokens for LLM text; for example a name containing "12%" makes "12%" acceptable. The LLM path is not wired in v1.

**Other medium fixes**
- **RT-08:** `engine/candidates.py:391` uses `D("0.000070")`, per SEBI 20-Sep-2019 (research doc §1.2: 0.0070 %).
- **RT-09:** `supervisor/supervisor.py:101`, `NO_REQUIRED_WORKER` → ABSTAIN.
- **RT-12:** `services/analysis.py:1516` cuts the series at `as_of` before both the band and its walk-forward.
- **RT-15:** `services/instruments.py:161` and `services/discovery.py:325` (`fd_entered_at`) record and use when the current rate was entered.
- **RT-16:** `services/analysis.py:1593`, `STALE_DATA` and `CALIBRATION_NOT_ESTABLISHED` warnings. Bands are *not* widened; widening would be a behaviour change.

### Not fixed — why

- **RT-17 (clamp truncates the holding period):** the fix means classifying the holding on the real dates while using the clamped date only for rate selection. That changes the tax engine's API and behaviour, and it is never in the user's favour, so it is report-only.
  - Probe: equity bought 2026-10-15 and sold 2027-11-19 with a ₹2,00,000 gain is taxed ₹41,600 (STCG) instead of ₹9,750 (LTCG at current rates).
  - Recommendation: add `HOLDING_PERIOD_TRUNCATED_BY_CLAMP` and fix it in the tax engine.
- **RT-18:** needs a profile input for the exemption already used. Latent today, because RT-17 forces STCG.
- **RT-19 and RT-20:** both are policy choices written into the spec (ε on historical frequency; the growth horizon). Changing them changes rankings, so the decision is the user's.
- **RT-21:** pruning changes what history Discovery can use; this is a licence and policy decision.
- **RT-22 to RT-28:** listed above, with low or no direct money impact.

### What I attacked and found SOUND

**Holding-period edges**
- Exactly 12 months is STCG and 12 months + 1 day is LTCG.
- A lot bought on 29 February crosses correctly.
- Evidence: existing `test_exactly_twelve_months_is_short_term`, `test_month_end_clamping_on_leap_day`, `test_twelve_month_boundary_end_to_end`, and a sub-audit probe.

**Rule boundaries**
- Equity 15 %/20 % switches at 23-Jul-2024.
- Specified-debt slab treatment starts 1-Apr-2023.
- ITA 1961 → 2025 switches at 1-Apr-2026 (probe).

**Cess and surcharge mechanics**
- Cess is 4 % of tax plus surcharge, and the 15 % cap applies on 111A/112/112A (`test_cess_is_four_percent_of_tax_plus_surcharge`, `test_surcharge_cap_on_special_rate_gains`).
- The clamp never *understates* tax (probe over every rule a candidate can hit).

**Bond cash flows, accrued interest and YTM**
- These agree with QuantLib (`tests/oracle/test_fixed_income_oracle.py`).
- A T-bill maturing 1 day after withdrawal is `HORIZON_MISMATCH` (probe and `test_tbill_maturing_after_withdrawal_is_horizon_mismatch`).

**FD**
- Leap-day start, the 181/182-day simple/compound cut-off and month-end clamping are correct (probe).
- The DICGC boundary includes interest (`test_rt01_dicgc_boundary_exactly_at_cover_is_insured`).

**Annualisation**
- Under 365 days the headline is the absolute return, and 1-day XIRR is refused (probe, `portfolio.py`/`analysis.py` Rule A1).

**Look-ahead in the engine**
- `horizon_window_returns` never uses a NAV after the window end, and a 20-day gap is skipped, never forward-filled (`test_window_returns_have_no_look_ahead_and_respect_staleness`).
- A NAV dated after `as_of` makes the fund ineligible (`LOOK_AHEAD`).
- The walk-forward splitter matches spec §4.2 exactly: T=20, H=5, e=2 → train 0..13; a naive split raises `LeakageError` (probe).
- `purged_kfold` drops [a−H, b+H+e].
- Feasibility grids end at the last month-end ≤ `as_of`.

**Growth objective with a 0 % loss budget**
- Equity is excluded (`LOWER_BAND_BELOW_LOSS_BUDGET`); only outcomes ≥ the amount rank (probe in `scratchpad/main/edge.py`).

**Amount boundaries**
- ₹10¹³ is rejected by the profile (≤ ₹10¹²), and floats are rejected.
- ₹10¹² formats without overflow.
- ₹1 runs, but see RT-22 on lot sizes.

**NAV parsing**
- 8-decimal NAVs survive exactly; parsing is regex → Decimal, never float (probe).
- Same-date AMFI source disagreement becomes `SOURCE_CONFLICT` (`test_disagreeing_official_sources_are_a_conflict_not_a_choice`).

**Fixtures**
- Personalised mode refuses fixtures by default (`test_personalised_mode_refuses_to_rank_fixtures_by_default`).
- A fixture quote can no longer be labelled as an RBI release (RT-25).

**Determinism**
- Identical inputs give identical discovery and forecast hashes (`test_identical_inputs_give_identical_result_hash`, `test_forecast_baseline_and_validation`).
- Seeds come only from `default_rng(seed)` (`test_engine_purity.py`).
- There are no floats in service outputs (`_no_floats`).

**API security**
- Covered by 22 tests in `tests/security/test_api_security.py`: host allowlist, CSRF/origin, no CORS, auth, rate limit, loopback bind, CSP, body cap and token-file mode.
- Fetch: an exact host allowlist, https:443 only, and a public-IP pin with re-vetted redirects (`tests/data/test_fetch.py`).
- Import: formula injection and zip-bomb limits are covered (`tests/data/test_imports_exports.py`).

**Prompt injection in evidence notes**
- This cannot change the answer (`test_prompt_injection_in_evidence_does_not_change_the_answer`).

### What I could not assess

- **Correctness of the tax law itself.** No independent oracle exists; 20 of 65 rules are NV. This needs Chartered Accountant review (already known).
- **Live AMFI names.** I could not check whether any real scheme name contains a banned phrase. That would have been a live HTTP 500 before RT-05; it is now harmless.
- **Raw-ASGI path-normalisation tricks.** TestClient normalises paths.
- **The MoSPI and mfapi adapters.** Disabled or unwired.
- **Real market behaviour of the ranking.** All data available here is fixture or test input. No conclusion in this report is about any real instrument.
- **Frontend rendering of the new outputs.** These are the `tax_basis` text, the warnings and the refusal codes. The frontend is out of scope.


---

## Independent final review (Agent L — coordinator), 2026-10-15

The red team's claims were **verified, not accepted on trust**:

1. **Every reproduction test fails without its fix.** With the red team's source changes stashed (tests kept), **40 of the 53**
   red-team tests failed on the previous code, covering RT-01 … RT-16. With the fixes restored, **53/53 pass**. So none of the tests
   passes trivially.
2. **Full gate after the fixes:** backend `pytest` 1,210 passed / 1 skipped (opt-in network test); `ruff check`, `ruff format
   --check` and `mypy --strict` clean.
3. **Ranking change reviewed** (`UNINSURED_CREDIT_EXPOSURE` for contractual instruments outside T1/T2 under preservation
   objectives). It is consistent with risk-methodology §9 Step 1, which makes the DICGC limit a hard constraint. Consequence: a ₹5,00,000
   FD at one bank exceeds the cover at maturity, because the cover includes interest, and is excluded from capital-preservation goals.
4. **Additional hardening by the reviewer** (standing approval for safety fixes that do not change intended behaviour):
   - RT-21: untracked schemes keep only their latest NAV (tests `test_untracked_schemes_keep_only_the_latest_nav`,
     `test_backfilled_schemes_keep_their_history`).
   - RT-18: `LTCG_EXEMPTION_ASSUMED_UNUSED` flag (test `test_equity_ltcg_exemption_assumption_is_flagged`). Under today's
     rule table it cannot trigger, because of RT-17; it is tested with a table of longer coverage.
   - RT-13 frontend: an optional surcharge-band field in onboarding.
5. **A false statement corrected:** `known-limitations.md` claimed tax simplifications "can only overstate tax". RT-13 disproved
   that, and the document now says so.
6. **Remaining open items** (RT-17, RT-19, RT-20, RT-22–24, RT-26–28) are listed in `docs/operations/known-limitations.md` with the
   reason each is not fixed. RT-19 (evidence behind the 1 % loss gate) and RT-20 (growth under 12 months) are product
   decisions that belong to the user.


---

## Resolution of open findings (track 5), 2026-10-15

Every fix below was written test-first: the new tests were run against the pre-fix source (the commit before this
work, restored into the working tree) and **22 failed and 3 test modules failed at import** (they use the new API:
`DataGapsExceedGate`, `CANONICAL_VERSION`, `iip.store.encrypted_backup`). For those three, the old behaviour was also
probed directly: `canonical_json` gave `"-0"`, kept `+05:30` and accepted `0.1`; a forecast over a series with a
3-month hole counted all 3,520 windows (65 of them across the hole) with no warning; feasibility on a series with
19 % suspect month-ends raised `InvalidInput` out of the service. All pass after the fixes. No existing test was
weakened; one existing hand-check (`test_tbill_contractual_after_tax`) was re-derived for whole T-bill lots, which
is the behaviour RT-22 changes, with the same strictness.

| ID | Resolution | Tests |
|---|---|---|
| RT-17 | `tax.compute_tax(..., rates_as_of=)` / `select_rule(..., rates_as_of=)`: rule rows, Act, slab, surcharge and cess come from the law in force on `rates_as_of` (the coverage end); the holding period is classified from the actual acquisition and transfer dates; acquisition-date conditions see the actual acquisition date, so no lot crosses the 1-Apr-2023, 23-Jul-2024 or 31-Jan-2018 boundary. `rates_as_of` after the transfer → `InvalidInput`; beyond coverage → `RuleNotFound`. The probe (bought 15-Oct-2026, sold 19-Nov-2027, ₹2,00,000) is now ₹9,750 LTCG, not ₹41,600 STCG. A grid test proves the result equals "actual dates under unchanged law" for listed equity, equity MF, debt MF, T-bill and interest across all boundaries — never lower. | `tests/redteam/test_redteam_tax_coverage.py` (16) |
| RT-22 | (a) `mf_candidate`: redemption on `as_of + (H − settlement)`; NAV windows, independent-window count, exit load, lock-in and the tax transfer date all use it. Found while fixing: with RT-17 fixed, using the withdrawal date for tax could classify a 365-day redemption as LTCG — the test pins STCG. (b) T-bills: RBI minimum ₹10,000 face in multiples of ₹10,000 (RBI/2021-2022/124, 12-Nov-2021; RBI Retail Direct FAQ — VERIFIED-PRIMARY for that notification, currency on 2026-10-15 not re-confirmed against a later master direction); whole lots only, remainder at 0 % (`UNINVESTED_REMAINDER_AT_ZERO`), `min_investment` = one lot's cost, below it `BELOW_MINIMUM_TICKET`. | `tests/redteam/test_redteam_settlement_and_tickets.py` (7) |
| RT-24 | B1 `max_gap_days` (service passes 7): > 2 % of observations behind a > 7-day gap → `DATA_GAPS_EXCEED_GATE` (forecast REFUSED); otherwise windows spanning a gap are excluded and n_eff is the largest set of non-overlapping gap-free windows; walk-forward skips origins whose outcome or training fails the gate. Feasibility: the spec gate (> 2 % suspect grid points) is now a REFUSED result. | `tests/redteam/test_redteam_data_gaps.py` (8) |
| RT-26 | Policy decided and documented in `iip.engine.determinism` (`canonical_json@2`): signed zero → zero, aware datetimes → UTC, floats rejected at any depth. Exact Decimal digits are kept on purpose (published precision is provenance; the existing `test_decimal_trailing_zeros_are_significant` encodes that decision). The version is recorded as `canonical` in discovery and analysis run versions. No code compares a recomputed hash with a stored one; the full suite passed unchanged. | `tests/redteam/test_redteam_canonical.py` (9) |
| RT-27 | `/api/discover` with `include_fixtures` in prod → 400 `FIXTURES_NOT_ALLOWED`, nothing stored. MF history gate: `COUNT(DISTINCT observation_date)` over usable, non-superseded rows. FD ids: `fd:<institution_type>:<slug>:<tenure>d`. | `tests/redteam/test_redteam_rt27.py` (5) |
| RT-28 | `XirrOutcome.NOT_DETERMINABLE`: with ≥ 2 sign changes each same-sign grid cell is searched for an interior extremum (bounded Brent); a crossing splits the cell into two solved, Decimal-verified brackets, a touch is a double root. Spec fixture X-5 stays `MULTIPLE_ROOTS`; a genuinely rootless case stays `NO_SOLUTION`. | `tests/redteam/test_redteam_xirr.py` (5) |
| RT-18 | Unchanged (flag); now reachable with the shipped rule table. | `test_rt17_equity_mf_candidate_past_coverage_gets_ltcg_and_exemption_flag` |
| RT-23 | **Resolved in track 1** (`ranking_policy@1.2.0`): the credit floor uses the lowest rating from a factsheet you enter with a citation; a stale or missing factsheet gives `CREDIT_QUALITY_UNKNOWN`, which is excluded whenever a floor is set. No licensed data feed is used. | `tests/unit/test_credit_floor_rt23.py` |

Version bumps: `candidates@1.1.0` (`CAND_TBILL@2`, `CAND_MF_EMPIRICAL@2`), `canonical_json@2`.

One pre-existing reconciliation defect surfaced while running the suite and was fixed: the compare "what would change
the order" gap was the difference of *unrounded* q05 values while the text showed rounded ones, so the displayed
subtraction could be off by ₹0.01 (`test_compare_order_gaps_are_q05_differences` failed once the numbers moved).
The gap is now computed from the paise-rounded values it displays.

Security items closed in the same track: SEC-16 and SEC-23 (real-browser Playwright tests, `make test-browser`),
SEC-83 (encrypted backups), SEC-85 (pnpm policy + `make lockcheck` in `make check`). See
`docs/testing/verification-report.md` §3.

## ECC specialist review panel, 2026-10-15

Eight vendored ECC reviewers (`.claude/agents/`, pinned; no installer, hooks or network) reviewed the merged
codebase: python, fastapi, database, security, silent-failure-hunter, react, typescript and a11y-architect. Each
finding was then checked adversarially by a separate agent with a reproduction. **21 reported, 21 confirmed, 21
fixed**, each with a regression test that fails on the pre-fix code. The full reports are in `docs/audit/ecc-panel/`.

| ID (reviewer) | Severity | Finding | Resolution |
|---|---|---|---|
| F1 (fastapi) / DB-2 (database) | High | Two concurrent applies of the same CSV/XLSX or CAS import batch both stored every row | The batch is claimed inside the write transaction (`previewed` → `applying`, exactly one row) and already-applied is re-checked under the lock (`pf.claim_previewed_batch`). Test: `tests/services/test_import_concurrency.py` (two-thread barrier race) |
| PR-1 (python) / DB-1 (database) | High | After a same-day NAV correction, pruning broke `ux_obs_current`, so every later NAVAll refresh failed | The `superseded_by = NULL` update was removed; one DELETE removes the correction pair. Test: `test_prune_survives_a_same_day_nav_correction` |
| F1 (silent-failure) | High | The DICGC check read missing "existing deposits" as ₹0 and ignored the user's own FDs at the same bank | Exposure is the entered figure plus open same-bank FD principal from your portfolios; with neither, `EXISTING_DEPOSITS_NOT_RECORDED` → T3, never zero-loss. Tests: `test_dicgc_existing.py` |
| A11Y-1 | High | Onboarding disabled Save with no error message | Validate on submit, focused error summary linking to each field, `aria-invalid` and `aria-describedby` |
| F2 (fastapi) | Medium | Unhandled exceptions reached uvicorn's traceback log with user values | Outermost middleware catches, logs only the class and request id, and sends a 500. Test: `test_f2_no_exception_escapes_the_asgi_app` |
| F3 (fastapi) | Medium | NAV-history backfill had no rate limit or pacing, and its circuit breaker reset on every request | Atomic, locked per-source limiter (429 with `Retry-After`), 1-second pacing, one shared breaker on `AppState` |
| PR-2 (python) | Medium | ELSS lock-in missed when ELSS appears only in the scheme name | The scheme name is passed to `mf_lock_in_days` in portfolio and compare |
| SR-01 (security) | Medium | Privacy erase missed `.db.enc`, `.partial` and `restored-*.db` files | Inventoried and erased; `restore-drill` cleans its temp copy |
| F3 (silent-failure) | Medium | A failed AMFI ISIN lookup was reported as "no stored instrument has this ISIN" | `IsinLookupFailed` → `ISIN_LOOKUP_FAILED` reason and a preview warning |
| F2, F4 (silent-failure) | Low | Unreadable portfolios were silently skipped by the stale alert; failed ingestion runs stayed `running` | Critical `inconsistent_book` alert; runs are marked failed on error, and interrupted runs are marked at startup |
| R-01, R-02, TS-1, TS-2 | Medium/Low | Frontend: StrictMode mutation state, stale responses, untyped `real_return` and `yield_carry`, aborted-request loading flag | Fixed with vitest coverage. Compare now shows the real return after inflation; Risk shows yield carry |
| A11Y-2..5 | Medium | Focus loss, silent route changes, focusable dots inside `role=img`, stale values announced as current | Focus management, page titles plus focus on `#main`, chart dots hidden from assistive tech in favour of the table, freshness word in labels |
