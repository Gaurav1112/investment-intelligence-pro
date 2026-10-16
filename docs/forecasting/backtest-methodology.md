# Backtest Methodology for Signals and Strategies

Status: specification v1 (Proposed, 2026-10-16) · Governing ADR: ADR-0016 · Sibling of
`docs/forecasting/validation-methodology.md` (which covers forecasts; this file covers trading signals) · Source:
`docs/research/wave1/research-backtest-method.md`, as corrected by `docs/research/wave1/verify-backtest-method.md`.

Scope: any rule that could tell the owner to change an allocation at a time of its choosing (trend, momentum,
switching, top-up rules). Policy arithmetic on the owner's holdings (ADR-0015) is not a signal and is not gated here.

Binding project rules restated: deterministic engine (Decimal for money; no clock, IO or randomness in `engine/`); no
LLM produces a number; tests use synthetic fixtures; **backtests run only in the local CLI and their results are never
committed** (public repo); stocks ABSTAIN (U-10). Status labels: VERIFIED / NOT VERIFIED / REQUIRES CONFIGURATION /
BLOCKED; PARAMETER marks a design choice.

---

## 1. Definitions

- **Decision time τ:** the moment a rule is evaluated. Only data with `known_time ≤ τ` may be used.
- **Edge:** per-period after-cost, after-tax return of the strategy minus its pre-registered benchmark.
- **Trial:** one evaluated configuration (rule, parameters, universe, horizon H, benchmark, data snapshot). Every trial
  is logged; changing any of these creates a new trial.
- **Family:** the trials of one rule idea; N is the family's row count in `backtest_trials`.
- **OOS:** out-of-sample, i.e. walk-forward segments whose parameters were frozen on earlier data.
- **Vault:** the sealed final period (§4.3), evaluated once.

## 2. Data

1. **Point-in-time:** every input row carries `known_time` (bitemporal). Universe membership, adjustment factors,
   normalisation statistics and tax and cost rules are all looked up as of τ.
2. **Permitted series:** AMFI NAVs of roles bound by the owner (role → scheme binding is DB config, never committed),
   MoSPI CPI, the RBI T-bill RSS, and the owner's own files (ADR-0017). Raw NAVs never leave local mode.
3. **Survivorship:** whether closed and merged schemes appear in AMFI history is measured by package A09. Until that
   answer is VERIFIED, only single-instrument rules (or role universes fixed in advance) are eligible; others fail G2.
4. **Regular-plan history before 2013** may extend a single-instrument test, labelled as such; TER cancels within the
   same plan.
5. **Corporate actions (equities):** not applicable while U-10 = none. If broker candles are ever used (X-01), each
   download is frozen and diffed against the prior snapshot, because vendors rescale history retroactively after a
   split (verify BT-7); gap detection cannot find an already back-adjusted split.

## 3. Execution timing

| Instrument | Rule | Basis |
|---|---|---|
| MF purchase or redemption (non-liquid) | Decide on NAVs known at τ; order on business day τ; **fill at NAV(τ + 1)** (U-16 default) | Same-day NAV needs the application **and funds** before the cut-off (AMFI applicable-NAV page, VERIFIED-SECONDARY, verify BT-6) |
| MF switch A → B | Redemption of A at NAV(τ + 1); purchase of B on the day proceeds are realised: **T + 3 working days**, or **T + 5** for schemes with ≥ 80 % overseas assets | AMFI: switch-in priced "in line with redemption pay out of Switch Out scheme"; SEBI circular SEBI/HO/IMD/IMD-I DOF2/P/CIR/2022/161 via the repo (verify BT-6) |
| Liquid / overnight MF | Next-day NAV | design rule (conservative) |
| ETF / stock | Not used (U-10). If ever enabled: fill at the next session, never at the close the signal used, plus slippage | design rule |

**Leakage invariants** (fail closed with `LeakageError`, gate G4): feature `known_time ≤ τ`; label purge
`t + H ≤ origin − embargo`; `fill_time > decision_time` strictly; universe and adjustments as of τ; normalisation on data
up to τ only; tax and cost rules by transfer date; every parameter traced to a trial chosen on data before the OOS
segment. A **shuffle canary** (block-permuted dates and a pure-noise series) must give OOS statistics consistent with
zero (for example DSR < 0.5); otherwise the pipeline leaks.

## 4. Walk-forward protocol

### 4.1 Mandatory arguments

`lag`, `purge`, `embargo` and `fill_rule` are **required arguments with no default** in the walk-forward code (B05,
graft 5). Purge equals the label horizon H; embargo `e = max(5 business days, 0.01 N)` unless the spec fixes another
value in advance.

### 4.2 Nested scheme

- **Outer loop:** `walk_forward_splits` (existing), origins spaced by the rebalance period, expanding window by default;
  a rolling window is the robustness check.
- **Inner loop:** `purged_kfold` (existing) on data ≤ `T_k − H − e`; choose parameters by inner score; freeze; trade
  `(T_k, T_{k+1}]`.
- The concatenated OOS edge series (one value per rebalance period) is what every statistic below uses. Overlapping
  holding periods are scored on non-overlapping periods, or with HAC variance with lag H − 1.

### 4.3 The vault

The last **max(20 % of the history, 3 years)** is sealed (U-06). It is evaluated **once**, after the design is frozen
and every gate except G11 has passed. A vault failure retires the rule; it is never retuned and re-vaulted, and it counts
as a trial forever.

### 4.4 Regimes (fixing an internal inconsistency)

The research report's calendar regimes (pre-2020 / 2020–22 / 2023+) put most of "2023+" inside the vault, so "≥ 2 of 3
regimes" could not be evaluated before it (verify BT-method omission 8). Therefore **regimes are defined on pre-vault
data only**, fixed in the rule spec before any run (graft 15). A drawdown-regime split (benchmark ≥ 20 % below its peak
versus not) is reported alongside.

## 5. Benchmarks and the null

- **H0:** expected after-cost, after-tax edge over the benchmark ≤ 0. The benchmark is fixed before any result is seen.
- **Mandatory comparators:** buy-and-hold of the same instrument (liquidated at the end, after tax); a broad index
  fund's **AMFI NAV** (not a TRI file: index-provider downloads are BLOCKED for automation and TRI-derived values carry
  the ADR-0017 copy question); a liquid-fund NAV hurdle (graft 2; a historical T-bill series is NOT VERIFIED because
  the RBI RSS keeps about 10 items); for switching rules, the static hold-both mix.
- Directional hit rate is compared with the base rate, not 50 %.

## 6. Costs and tax

- **MF costs:** stamp duty 0.005 % on purchase, STT 0.001 % on equity-fund redemption, exit load per FIFO lot (existing
  `engine/costs.py`). An exit load that cannot be parsed makes the trial abstain (B06 grammar).
- **Equity costs** (only if ever enabled): `rules/costs/india_equity.yaml` (A11). Fixture C-1: ₹237.8212 on a ₹1,00,000
  delivery round trip (verify BT-4). The ETF STT row is NOT VERIFIED; C-1 is not applied to ETFs until it has a primary
  source.
- **Tax:** lot-level FIFO per folio; rules looked up by transfer date; **conservative bound for gating**: highest slab,
  annual LTCG exemption already used, all positions liquidated at the end. Fixture T-1 (fictional ₹20,000 gain): STCG
  ₹4,160, LTCG ₹2,600, within an unused exemption ₹0.
- **Historical rows:** equity rows start 2024-04-01 in the repo; ₹1.25 lakh applies from 1-Apr-2024 (not ₹1 lakh, verify
  BT-3); lots bought on or before 31-Jan-2018 abstain; FY2024-25 mixed-rate years abstain. So **any window that needs
  pre-2024 rows ends in `ABSTAIN(tax_rules_missing)`** until A11's primary-sourced rows pass a CA review.
- **Not modelled (NOT VERIFIED, CA review):** basic-exemption shortfall absorbing s.111A/112A gains; s.87A rebate
  against special-rate gains (verify BT-10). The conservative bound is unaffected.
- Costs not verified mark the trial `costs_estimated`, which caps its status at NOT VERIFIED.

## 7. Multiple testing and power

All Sharpe ratios per period (non-annualised) unless stated. Statistics may use float64 (as `validation.py` does);
every float stored is rounded to a declared number of decimals so outputs stay byte-identical. stdlib
`statistics.NormalDist` is used; no scipy in the gate module (A18).

1. **Trial registry** (`backtest_trials`, append-only by SQL trigger): params (canonical JSON), universe, H, benchmark,
   data snapshot hash, code version, seed, OOS edge series hash, n, ŜR, skewness, kurtosis, status. Report N and, if
   computed, N_eff (clusters of correlated trials); gate on raw N unless N_eff is logged.
2. **Holm** on one-sided p-values for families with N ≤ 20. Fixture MT-2: p = [0.004, 0.011, 0.019, 0.030, 0.200],
   α = 0.05 → Bonferroni rejects 1, Holm rejects 2.
3. **Hansen SPA** (stationary bootstrap, deterministic seed, B ≥ 5,000) for larger families — `gate_not_implemented`
   until X-05.
4. **PSR / DSR** (Bailey & López de Prado 2014):
   `PSR(SR*) = Φ((ŜR − SR*)·√(T − 1) / √(1 − γ̂₃·ŜR + ((γ̂₄ − 1)/4)·ŜR²))`;
   `SR₀ = √V[ŜR_n]·((1 − γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e)))`, γ ≈ 0.5772; `DSR = PSR(SR₀)`.
   Fixture DSR-1 (the paper's example): ŜR = 0.158114, T = 1,250, V = 0.002, skew −3, kurtosis 10 → N = 100 gives
   SR₀ = 0.113172 and DSR = 0.9004 (rejected); N = 46 gives 0.9505; normal returns at N = 88 give 0.9505.
5. **MinTRL** `= 1 + (1 − γ̂₃·ŜR + ((γ̂₄ − 1)/4)·ŜR²)·(Φ⁻¹(0.95)/(ŜR − SR*))²`. Fixture MT-3 (monthly, SR* = 0):
   annualised 0.5 → 132.2 months; with skew −1, kurtosis 6 → 153.0; annualised 1.0 → 34.8.
6. **Power, not just MinTRL.** MinTRL gives about 50 % power at a true edge equal to the observed one. For 80 % power
   at one-sided α = 0.05: `T ≈ 1 + ((z₀.₉₅ + z₀.₈₀)/ŜR)²` ≈ **298 months** at annualised 0.5 (verify BT-9). Both lengths
   are shown side by side.
7. **Luck baseline.** Fixture MT-1 (T = 120 months, zero skill): expected best annualised SR is 0.50 / 0.80 / 1.03 for
   N = 10 / 100 / 1,000 (an upper-side illustration: it assumes independent trials).
8. **t ≥ 3 floor** on the HAC t-statistic of the mean edge (Harvey, Liu & Zhu 2016, VERIFIED-SECONDARY; a contested
   convention).
9. **PBO** via CSCV (S = 16 slices, C(16, 8) = 12,870 combinations, enumerable): gate PBO ≤ 0.20 (a design choice; no
   standard cutoff exists) — `gate_not_implemented` until X-05.
10. **Earliest possible review** = registration date + max(30, MinTRL) months, shown as YYYY-MM.

**Joint power, stated plainly:** with AMFI history of about 20 years and a vault of at least 20 % and 3 years, about 12
years or less of OOS data remain; t ≥ 3 then needs an annualised Sharpe of about 0.87. For realistic edges the gates are
close to unpassable on Indian MF history. ABSTAIN is the expected outcome, not an occasional one.

## 8. Gates (fail closed; thresholds frozen by U-06)

| Gate | Requirement | Failure output |
|---|---|---|
| G1 Data provenance | Every series has a source id, licence not BLOCKED, `known_time`, a snapshot hash | `ABSTAIN(data_unverified)` |
| G2 Survivorship | Survivorship-free universe, or a single-instrument rule | `ABSTAIN(survivorship_unverified)` |
| G3 Corporate actions | No unexplained gap > 25 % or < −20 % without a matching action (PARAMETERs) | `ABSTAIN(unadjusted_prices_suspected)` |
| G4 Leakage | All §3 invariants and the shuffle canary pass | `ABSTAIN(leakage)` |
| G5 Sample size | ≥ 30 non-overlapping OOS periods **and** OOS length ≥ MinTRL | `ABSTAIN(insufficient_evidence: has X, needs Y)` |
| G6 Costs and tax | Edge > 0 at the conservative bound; verified rows cover the whole window | `NO_SIGNAL(edge_not_positive_after_costs_tax)` / `ABSTAIN(tax_rules_missing)` |
| G7 Cost stress | Edge > 0 at slippage ×2 and total costs ×1.5 | `NO_SIGNAL(fragile_to_costs)` |
| G8 Trial registry | Family N known | `ABSTAIN(trials_unknown)` |
| G9 Multiple testing | DSR ≥ 0.95 **and** (Holm p < 0.05 if N ≤ 20, else SPA p < 0.05) **and** HAC t ≥ 3.0 | `NO_SIGNAL(not_significant_after_multiple_testing)` |
| G10 Robustness | Positive in ≥ 2 of 3 pre-vault regimes; rolling-window variant positive; PBO ≤ 0.20; ±1 grid step positive | `NO_SIGNAL(not_robust)` |
| G11 Vault | One evaluation: edge > 0 after costs and tax, inside the walk-forward 80 % range | `RETIRED(vault_fail)` |
| G12 Live decay | Rolling 24-period realised edge < 0 and below the lower 80 % bound | `SUSPENDED(decay)` |
| G13 Risk-budget compatibility | Strategy's worst drawdown at maximum tilt does not breach the goal's L3 loss budget (ADR-0015) | `NO_SIGNAL(exceeds_loss_budget)` |
| G14 Drawdown non-inferiority | Strategy max drawdown ≤ benchmark max drawdown + 0 pp over the OOS window | `NO_SIGNAL(drawdown_inferior)` |

Any gate not yet built returns `gate_not_implemented` and fails closed. A signal that passes G1–G11, G13 and G14 is
ACCEPTED with status VERIFIED only if every input and rule row is verified; otherwise it is shown as "evidence
incomplete", never as an instruction. The supervisor still abstains if the owner's own context (slab, exemption use,
lots, exit loads) is missing.

## 9. Reporting (engine numbers only, each with a formula id)

1. Median annualised after-tax edge with 80 % and 95 % stationary-bootstrap intervals and Monte Carlo error.
2. ŜR with PSR and DSR, N and N_eff, MinTRL and the 80 %-power length against the actual OOS length.
3. Drawdown: worst historical, and bootstrap 50th/90th/95th percentiles over the owner's horizon, strategy and
   benchmark.
4. Layered returns: gross, after costs, after costs and tax, under both exemption bounds and both terminal treatments.
5. Sensitivity grid: slippage ×0–×3, costs ×1.5, slab variants, parameters ±1 step.
6. Regime table (pre-vault regimes; drawdown/non-drawdown).
7. Turnover and STCG/LTCG mix.
8. Plain-language error rate ("an 80 % range is wrong 1 time in 5 by design") and a "past backtest, not a promise"
   line from `rules/compliance_phrases.yaml`.
9. Gate panel G1–G14 with the failing gate and what evidence would change the answer; the post-publication tag; the
   ×0.5 decay haircut on any expected excess shown.

Never "probability of profit"; never annualise a sub-year result without saying so. Wording follows ADR-0018.

## 10. Determinism and reproducibility

- Module `engine/backtest/` (A17, A18, B05). Money, units, costs and tax in Decimal under `engine_context`.
- As-of date, data snapshot and seed are passed in. Seed: `sha256(instrument|as_of|model_version|trial_id)`.
- **Run manifest:** code version, data snapshot hash, rule-table versions, trial id, seed, output hash. Re-running a
  manifest must reproduce `output_hash` (ADR-0011 oracle test).
- Results stay in the owner's local database. Hosted mode imports an evidence bundle (statistics, gate results,
  hashes) with **no raw NAVs** (ADR-0016, ADR-0017).

## 11. Red-team additions (how a backtest could still mislead)

1. Silent retuning after a vault look (blocked by §4.3 and the append-only log).
2. Unlogged exploratory trials before the registry existed (covered by the t ≥ 3 floor).
3. Benchmark switched after seeing results (benchmark is part of the trial key).
4. Today's tax or cost rates applied to past dates (lookup by transfer date; G6).
5. A survivor-only universe (G2; A09 probe).
6. Regimes that overlap the vault (§4.4).
7. A vendor's retroactive price rescaling (frozen snapshots; only relevant if U-10 changes).
8. A shown edge without the decay haircut, or an "expected return" on a card (A16 test forbids the field).
