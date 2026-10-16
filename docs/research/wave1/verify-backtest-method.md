# Verification: research-backtest-method.md (wave 1, adversarial check)

- **Report under review:** `docs/research/wave1/research-backtest-method.md`
- **Verifier role:** adversarial skeptic. I re-checked the repo claims, recomputed every fixture and reopened the citations I could reach.
- **Access date of every URL below:** 2026-10-15.
- **Tooling limits this session:** the shared WebSearch budget ran out partway through. Wiley returned HTTP 403 for White (2000), and RePEc shows no abstract for it. Claims I could not reopen are marked NOT VERIFIED (by this verifier). I did not guess any of them.
- Not tax, legal or investment advice.

## 1. Verdict summary

| Id | Claim | Verdict |
|---|---|---|
| BT-1 | Validation spec and code cover forecasts, not trading signals | **CONFIRMED** |
| BT-2 | Multiple-testing controls are "guidance only"; no trial registry; MT-1 = 0.80 | **CONFIRMED** |
| BT-3 | No tax rows before 2020–2024, so pre-2024 tax-aware backtests are impossible | **CONFIRMED, with a correction to §7.3** (see §2) |
| BT-4 | No equity/ETF cost table; Zerodha rates; C-1 = ₹237.82 | **CONFIRMED for the gap and the arithmetic. WEAKENED for ETFs** (STT row) |
| BT-5 | Single stocks cannot be backtested survivorship-free with compliant free data | **WEAKENED.** The label is BLOCKED, but it rests on a "probably" plus an open NSE manual-download question |
| BT-6 | MF execution timing (realisation of funds, switch drag) not modelled | **CONFIRMED and can be upgraded.** AMFI's own page settles the switch-in rule that the report left NOT VERIFIED |
| BT-7 | No corporate-action adjustment spec; broker-candle adjustment NOT VERIFIED | **WEAKENED / outdated.** The sibling verification already found evidence of partial adjustment, which breaks the report's detection method |
| BT-8 | No sealed final holdout | **CONFIRMED.** The White (2000) quote could not be reopened (NOT VERIFIED by me) |
| BT-9 | MinTRL for a 0.5 Sharpe edge is about 11 years | **CONFIRMED arithmetically, but it understates the requirement** (it is a floor, not a power-based length) |
| BT-10 | Shared ₹1.25L exemption and the user's slab are unknown to the backtest | **CONFIRMED.** Omits the basic-exemption shortfall and the 87A rebate question |

## 2. Finding-by-finding

### BT-1: CONFIRMED
- `backend/src/iip/engine/forecasting/validation.py` defines only split, scoring, DM, promotion and drift functions. These are `walk_forward_splits`, `purged_kfold`, `assert_no_leakage`, `pinball_loss`, `crps_*`, `kupiec_pof`, `christoffersen_independence`, `diebold_mariano`, `promotion_gate`, `rolling_*_monitor` and `psi`.
- It has no position, lot, cost or tax type.
- `engine/costs.py` holds MF stamp duty (`STAMP_DUTY_MF_PURCHASE_RATE = Decimal("0.00005")`), FIFO exit load and `expense_net_factor`. Nothing more.

### BT-2: CONFIRMED
- `validation-methodology.md` line 299 reads: "This is guidance only; it is not used in v1 product outputs."
- No trial-registry table or module exists in the repo.
- I recomputed MT-1 with scipy using the expected-maximum formula from Bailey & López de Prado: N = 10 gives 0.4979, N = 100 gives 0.8002 and N = 1000 gives 1.0294. All three match.
- **Caveat:** the formula is an approximation for *independent* trials. Correlated variants inflate the best SR less, so 0.80 is an upper-side illustration.

### BT-3: CONFIRMED, with a correction
- **The gap is real.** In `india.yaml`, the earliest equity and equity-MF capital-gains rows (`EQ-STCG-OLD`, `EQ-LTCG-OLD`, `MF-EQ-*-OLD`) start on `effective_from: 2024-04-01`. The 2020-07-01 row is `STAMP-MF-01`, a stamp-duty rule rather than a tax rule. The 2023-04-01 row is `MF-SMF-DEF-OLD`. So "rows start 2020–2024" is true only loosely. For equity, the start date is **2024-04-01**.
- **Correction to report §7.3.** The table says "1-Apr-2018 to 22-Jul-2024 | 10 % above ₹1 lakh". The repo's own primary-sourced row contradicts this. `EQ-LTCG-OLD` carries `annual_exemption_inr: "125000"`, with the note "CORRECTED in table r2 (was 100000)". It quotes Finance (No.2) Act 2024 s.31: the ₹1.25 lakh limit "shall apply on aggregate of the long-term capital gains under sub-clauses (a) and (b)". So transfers from 1-Apr-2024 to 22-Jul-2024 are 10 % above **₹1.25 lakh**, and the ₹1 lakh threshold applies only up to 31-Mar-2024. The research doc line 485 still shows ₹1,00,000, and the report copied that stale value.
- **The report understates the restriction.** The repo row also abstains on lots acquired on or before 31-Jan-2018 (grandfathering is not modelled), *even for transfers after 2024*. It also abstains on FY2024-25 years that mix 10 % and 12.5 % lots. So "pre-2024 is impossible" is incomplete. A buy-and-hold benchmark holding pre-2018 lots, or any FY2024-25 window, also abstains today.
- The pre-2018 s.10(38) exemption and the grandfathering formula in §7.3 rest on search extracts, because incometaxindia.gov.in returned 403. They stay VERIFIED-SECONDARY at best. I did not reopen them because the search budget was exhausted.

### BT-4: CONFIRMED (gap and arithmetic); WEAKENED (ETF row)
- **Repo:** there is no `rules/costs/` directory. `ls backend/src/iip/rules/` shows `compliance_phrases.yaml`, `loader.py`, `mf_categories.yaml` and `tax/`.
- **https://zerodha.com/charges/** (2026-10-15), equity delivery, reopened by me. It says: "Zero Brokerage"; "0.1% on buy & sell"; "NSE: 0.00307% BSE: 0.00375%"; "18% on (brokerage + SEBI charges + transaction charges)"; "₹10 / crore"; "0.015% or ₹1500 / crore on buy side"; "₹15.34 per scrip (₹3.5 CDSL fee + ₹9.5 Zerodha fee + ₹2.34 GST) is charged on the trading account ledger when stocks are sold, irrespective of quantity." All quotes match.
- **Zerodha STT support article** (URL as in the report, 2026-10-15): it gives "0.1% (₹100 per lakh)" on "Both buy and sell sides". Its rounding rule reads: "If the paise portion is 50 or more, STT rounds up … less than 50, STT rounds down". It also says "STT rates on futures and options (F&O) changed on 1 April 2026". All match.
- **C-1 recomputed by hand.** On ₹1 L the total is 200 + 6.14 + 0.20 + 15 + 1.1412 + 15.34 = **₹237.8212**. Correct.
- **ETF weakness.** The report's §6.1 is headed "Equity delivery **and ETF**" and G-b applies STT 0.1 % to ETFs. The Zerodha charges page does not mention ETFs at all. I asked for every sentence containing "ETF" and none came back. Units of equity-oriented funds sold on an exchange are, to my understanding, charged STT under a different row of Finance (No.2) Act 2004 s.98 (seller-side, much lower than 0.1 %). I could not verify this in this session, so it is **NOT VERIFIED**.
- **Consequence:** the report may overstate ETF round-trip costs, and ETFs are its own "most defensible" candidate. An ETF STT row needs a primary source before C-1 is applied to ETFs.
- **"12 × that per year".** This assumes 100 % turnover every month. That is an upper bound, not a typical figure.
- **The status label is wrong.** BT-4's own label (NOT VERIFIED) is inconsistent with the evidence. The gap is a repo fact (VERIFIED). The rates are VERIFIED-SECONDARY from the broker page, and are broker-specific (REQUIRES CONFIGURATION).

### BT-5: WEAKENED
- **The repo evidence exists.** `research-equity-data-alt.md` §0 says: "Delisted stocks are probably missing from broker instrument lists (NOT VERIFIED)".
- `verify-equity-data-alt.md` line 90 adds some support. Upstox's expired-instruments API "lists only expired option and future contracts … Nothing there covers delisted equities."
- **However**, that same verification (line 131) flags an "NSE ToU 'available for download' carve-out … for manually downloaded bhavcopy files". A manual, personal-use import path "may be arguable. It needs a written query to NSE, not a flat BLOCKED."
- Bhavcopies list every traded security on each date, including stocks that later delisted. So a manual route could make a survivorship-free *price* universe possible.
- **Better label:** BLOCKED for *automated* compliant data. For the manual route, the honest label is REQUIRES CONFIGURATION / NOT VERIFIED (pending NSE's written answer). The report's flat "BLOCKED … No compliant free source with delisted stocks was found" overstates the case.

### BT-6: CONFIRMED, and upgradeable
- **AMFI, "What is the new rule on Applicable NAV?"**, https://www.amfiindia.com/uploads/Uniformityin_NA_Vapplicability_b8ade2a39e.html (2026-10-15). It gives an effective date of 1-Feb-2021: "applicable NAV in respect of purchase of units...shall be subject to realization & availability of the funds in the bank account of mutual fund before the applicable cut off timings". On switch-in it says: "Business Day on which funds are received (in line with redemption pay out of Switch Out scheme) in Switch-in scheme before cut-off time." AMFI is the industry body, so this is VERIFIED-SECONDARY with respect to SEBI. The SEBI circular itself was not opened.
- **This resolves an open point in the report.** §4.1 says "Same-AMC 'switch' transactions may differ; NOT VERIFIED". AMFI's page says the switch-in is priced in line with the switch-out scheme's *redemption payout*, so a switch is not instantaneous. The report's conservative cash-drag rule is supported.
- **On T+3:** the repo source (`indian-instruments-and-tax.md` line 145) cites SEBI circular SEBI/HO/IMD/IMD-I DOF2/P/CIR/2022/161 (25-Nov-2022): 3 working days, or 5 for schemes with at least 80 % overseas assets. The report omits the **T+5 exception for overseas-heavy schemes**. A switch out of an international fund-of-funds would therefore carry up to 5 days of drag, not 3.
- I could not reopen the SEBI circular (search budget exhausted). It stays VERIFIED-SECONDARY via the repo.

### BT-7: WEAKENED (outdated evidence; the proposed method is flawed)
- **The gap is real:** the repo has no corporate-action table.
- **The report's basis is stale.** It says "Whether broker candles are adjusted is NOT VERIFIED". The sibling `verify-equity-data-alt.md` (lines 81–87) quotes an Upstox staff reply of 2023-12-28: "Yes, corporate actions are adjusted on the same day." It concludes that candles are "split- and bonus-adjusted, and are **not** adjusted for dividends or demergers". It also flags a "**retroactive-rescaling storage hazard**".
- **Why this matters for the method in §3.3.**
  1. A gap-detection adapter ("a split shows up as an unexplained gap") cannot detect splits that the vendor has *already* back-adjusted.
  2. "Store **raw** prices" cannot be satisfied from a source that only serves adjusted history.
  3. Re-downloading history after any new split silently rescales every stored past price. That breaks the `data_snapshot_hash` reproducibility and the "adjust as known at τ" rule. Prices fetched later embed post-τ actions.
- **Missing from the method:** a design rule to snapshot and freeze each download, and to diff it against the prior snapshot to detect retroactive rescaling. The report does not include one.

### BT-8: CONFIRMED (citation not reopened)
- `validation-methodology.md` has no vault, holdout or final-period rule. A grep for "vault|holdout|final" finds nothing relevant.
- The partial protection that does exist is line 285: promotion is judged "on walk-forward held-out origins that were never used for any tuning". It does not prevent repeated looks across development cycles.
- The White (2000) quote, "Data snooping occurs when a given set of data is used more than once for purposes of inference or model selection", is **NOT VERIFIED by me**. Wiley returned 403 at https://onlinelibrary.wiley.com/doi/abs/10.1111/1468-0262.00152, and RePEc (https://ideas.repec.org/a/ecm/emetrp/v68y2000i5p1097-1126.html) says "No abstract is available for this item."

### BT-9: CONFIRMED arithmetically; UNDERSTATED in interpretation
- I recomputed MT-3: 132.22, 152.99 and 34.82 months. All match.
- I also reproduced DSR-1: N = 100 gives SR₀ 0.113172 and DSR 0.9004; N = 46 gives 0.9505; N = 88 with normal returns gives 0.9505.
- **Source checked:** https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf (2026-10-15), downloaded and parsed with pdftotext. Verbatim:
  - "Essentially, DSR is a PSR where the rejection threshold is adjusted to reflect the multiplicity of"
  - "after running only N=46 independent trials, the investor may have allocated some funds, as … would have been 0.9505, above the 95% confidence level"
  - "after N=88 independent trials"
  - "(approx. 0.5772) is the Euler-Mascheroni constant"
  - "Appendix 3 shows how N can be determined when the"

  The paper text also says "only a 90% chance that the true SR … is greater than zero", which is consistent with 0.9004.
- **Interpretation problem.** MinTRL is the length at which an *observed* SR of 0.5 gives PSR = 0.95. If the *true* annualised SR is 0.5, a test at that length has only about 50 % power. For 80 % power at one-sided α = 0.05 under normality: T ≈ 1 + ((1.645 + 0.842)/0.1443)² ≈ **298 months (about 25 years)**. That is my own computation.
- So "about 11 years" is a *minimum*, not "enough". This strengthens the report's abstain conclusion, but the wording "needs about 11 years … to be distinguished" overstates what 11 years buys.

### BT-10: CONFIRMED (with omissions)
- **Repo:** `indian-instruments-and-tax.md` lines 484–486 contain the EQ-STCG 20 % and EQ-LTCG 12.5 % rows, the latter with "₹1,25,000/yr aggregate". They are VERIFIED-PRIMARY. The yaml `exemption_scope: EQUITY_LTCG_ANNUAL` makes the exemption a shared pool.
- **T-1 recomputed:** 20,000 × 0.20 × 1.04 = 4,160; 20,000 × 0.125 × 1.04 = 2,600. Correct.
- **Omissions** (both NOT VERIFIED in this session, and both should be rule rows rather than assumptions):
  - For resident individuals, any unexhausted basic exemption limit can usually absorb s.111A/112A gains. A low-income user could therefore owe less than the "highest slab" bound.
  - It is unsettled whether the s.87A rebate can be set against special-rate capital gains.
- The conservative bound in the report still stands for gating.

## 3. Other checks
- **Corporate-action factors (§3.3) are algebraically correct.** Split a→b gives a/b. Bonus b:a gives a/(a+b). Rights use TERP = (aP + rS)/(a + r). Dividends give (P−D)/P.
- **MT-2 Holm/Bonferroni:** recomputed by hand. Bonferroni rejects 1 and Holm rejects 2. Correct.
- **Harvey, Liu & Zhu:** the abstract wording "a newly discovered factor needs to clear a much higher hurdle, with a t-ratio greater than 3.0" is confirmed via search extracts of SSRN 2249314 and NBER w20592 (VERIFIED-SECONDARY).
  - The report omits a published counter-view: "Most claimed statistical findings in cross-sectional return predictability are likely true" (https://arxiv.org/pdf/2206.15365, title seen in search results only, NOT VERIFIED beyond the title).
  - t > 3 is a contested convention, not a settled standard.

## 4. Important omissions
1. **The ETF STT treatment differs from equity delivery (NOT VERIFIED)**, yet the report applies the 0.1 % stock STT to its preferred ETF candidates.
2. **No data source or terms are checked for the benchmark TRI series** (Nifty/BSE total-return indices) **or for 91-day T-bill history.** Both are *mandatory comparators* in §8. If the index provider's terms forbid automated download, comparator 2 is BLOCKED, and so is every G6 verdict.
3. **No joint power analysis of the stacked gates.** G5 (MinTRL), G9 (DSR ≥ 0.95 **and** Holm/SPA **and** HAC t ≥ 3) and G10 (PBO, regimes, neighbours) all apply together.
   - With monthly data, t ≥ 3 alone needs SR_ann ≥ 3/√years: about 0.87 over 12 years of OOS data.
   - The vault takes at least 20 % of the history and at least 3 years. AMFI NAV history (about 20 years at most) therefore leaves roughly 12 years or less of walk-forward OOS.
   - The report should state plainly that, for realistic edges, the gates are close to unpassable on Indian MF/ETF history. The user then knows "No suitable candidate" is the near-certain outcome, not an occasional one.
4. **The retroactive-rescaling hazard and the frozen-snapshot rule** for broker candles (see BT-7).
5. **The T+5 payout exception** for schemes with at least 80 % overseas assets (see BT-6).
6. **Stale ₹1 lakh threshold** for 1-Apr-2024 to 22-Jul-2024 (see BT-3). The repo yaml and the research-doc table disagree. The research doc line 485 should be reconciled; that is a separate follow-up, and this file does not edit it.
7. **The grandfathered-lot abstention also hits post-2024 transfers** (see BT-3).
8. **Regime split (§5.3) uses calendar periods** (pre-2020 / 2020–22 / 2023+). With a vault of at least 3 years taken from the end, the "2023+" regime falls largely or wholly inside the vault. Then "≥ 2 of 3 regimes" cannot be evaluated before the vault. This internal inconsistency is not addressed.
9. **Pre-2018 STT-paid s.10(38) and grandfathering facts** remain search-extract only. incometaxindia returned 403 again in the report's session, and I could not reopen them.

## 5. Sources (accessed 2026-10-15)
- https://zerodha.com/charges/ ("Zero Brokerage"; "0.1% on buy & sell"; "NSE: 0.00307% BSE: 0.00375%"; "₹15.34 per scrip …"). The page has no mention of ETFs.
- https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/how-is-the-securities-transaction-tax-stt-calculated ("0.1% (₹100 per lakh)"; "Both buy and sell sides"; "STT rates on futures and options (F&O) changed on 1 April 2026")
- https://www.amfiindia.com/uploads/Uniformityin_NA_Vapplicability_b8ade2a39e.html ("subject to realization & availability of the funds …"; "in line with redemption pay out of Switch Out scheme")
- https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf (worked example 0.9505 at N = 46; N = 88; "DSR is a PSR where the rejection threshold is adjusted …")
- https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2249314 and https://www.nber.org/papers/w20592 (search extract: "t-ratio greater than 3.0")
- https://onlinelibrary.wiley.com/doi/abs/10.1111/1468-0262.00152 (HTTP 403) and https://ideas.repec.org/a/ecm/emetrp/v68y2000i5p1097-1126.html ("No abstract is available for this item"). The White quote is NOT VERIFIED.
- Repo files:
  - `docs/forecasting/validation-methodology.md` (lines 285–300)
  - `backend/src/iip/engine/forecasting/validation.py`
  - `backend/src/iip/engine/costs.py`
  - `backend/src/iip/rules/tax/india.yaml` (EQ-*-OLD, STAMP-MF-01)
  - `docs/research/indian-instruments-and-tax.md` (lines 86, 138–147, 450, 484–486)
  - `docs/research/wave1/research-equity-data-alt.md` §0
  - `docs/research/wave1/verify-equity-data-alt.md` (lines 81–90, 131)
- Fixture recomputation: `backend/.venv/bin/python` with scipy.stats.norm, run in this session. It reproduced DSR-1, MT-1 and MT-3 exactly.
