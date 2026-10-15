# Forecast Validation Methodology (Agent D — Quantitative Research)

Status: specification v1 · Date: 2026-10-15 · Companions: `docs/finance/calculation-methodology.md`,
`docs/finance/risk-methodology.md`

Scope: horizon-outcome **distributions** (not point predictions) for mutual funds (daily NAV),
T-bills, G-secs/SDLs, corporate bonds and FDs over horizons H ∈ {1, 3, 6, 12} months, with longer
horizons for comparison only. The app is **deterministic**: identical inputs, as-of date and model
version must give byte-identical outputs. All randomness uses `numpy.random.Generator(PCG64(seed))`
with
`seed = int.from_bytes(sha256(f"{instrument_id}|{as_of}|{model_version}").digest()[:8], "big")`.

Core stance: **a forecast is a calibrated range of plausible ₹ outcomes plus its reliability
status.** Simple baselines are the default product. A complex model is promoted only by the rule in
§6.

---

## 1. Prediction interval vs confidence interval

* **Prediction interval (PI):** a range that should contain the *future realised outcome*
  `y_{T+H}` with nominal probability (1−α). This is what users see ("₹ 98,500 – ₹ 1,07,200 in
  12 months, 80 % range").
* **Confidence interval (CI):** uncertainty about a *parameter*, such as the mean annual return.
  It is far narrower. Never present a CI as an outcome range.

Fixture PI-1: annual σ = 15 %, n = 10 years of i.i.d. annual returns.
* 95 % CI for the mean: ±1.96 × 15/√10 = **±9.30 %**
* 95 % PI for next year's return: ±1.96 × 15 × √(1 + 1/10) = **±30.83 %**

---

## 2. Baselines (the default models)

Every baseline outputs quantiles `q ∈ {0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95}` of the horizon
return `R_H` (simple, net of scheme expenses because NAV is net), then converts to ₹ after
user-level costs (exit load, stamp duty) and tax via the calculation-methodology rules.

### 2.1 B1 — Empirical horizon-return distribution (overlapping windows)

`R_t^H = P_{t+H}/P_t − 1` for every business day t with `t + H ≤ as_of` (H in business days:
21/63/126/252). Quantiles use Hyndman–Fan type 7 (linear) for **forecast** bands (smooth). Risk VaR
uses type 1 (risk-methodology §5.1); keep the two separate.
* Effective sample `n_eff = floor(N/H)`. Gate: n_eff ≥ 20 for the 5/95 % quantiles and ≥ 10 for
  the 10/90 % quantiles. Otherwise emit only the 25/50/75 % quantiles with `low_confidence`, or
  refuse.
* Optional recency weighting is **off by default**. Weighting adds a tunable parameter, which then
  needs validation.

### 2.2 B2 — Stationary block bootstrap (Politis & Romano 1994)

This builds scenario intervals that keep short-range dependence:
1. Daily log returns `ℓ_1..ℓ_N`.
2. Mean block length `L`. Use the automatic selection of Politis & White (2004) with the
   Patton–Politis–White (2009) correction (`arch.bootstrap.optimal_block_length`), clipped to
   `[5, 63]`.
3. Each path: start at a uniform random index; at each step continue the block with probability
   `1 − 1/L`, or jump to a new uniform random index with probability `1/L`. Wrap circularly.
   Generate H steps and sum the log returns. `R_H = exp(Σ) − 1`.
4. Use B = 5,000 paths with the deterministic seed. Report the quantiles plus a Monte Carlo
   standard error for each quantile, from a bootstrap-of-bootstrap or the binomial approximation.

Caveat: B2 cannot generate events absent from history, such as a never-seen credit event, and it
assumes stationarity.

### 2.3 B3 — Naive point baselines (for point-metric comparisons)

* **Zero drift / random walk:** `E[R_H] = 0`.
* **Historical mean:** `E[R_H] = (1 + CAGR_hist)^(H/12) − 1`, computed on the training window only.
* **Risk-free carry:** `E[R_H] = 91-day T-bill yield × days/365`.

These anchor MAE/RMSE and directional accuracy. A model that cannot beat zero drift on direction is
not shown as "directional".

### 2.4 B4 — Yield-carry model (debt funds, bonds, T-bills)

`E[R_H] ≈ (YTM − ER) × H_years − D_mod × Δy + ½ C (Δy)²`, with scenario Δy over a grid
(default −100, −50, 0, +50, +100 bp; +200 bp as stress). Here ER is the expense ratio
(TER/BER + levies; calc §2.8). Use the portfolio YTM, modified duration and (if disclosed)
convexity from the latest factsheet (≤ 45 days old). For individual bonds, use full repricing
instead (calc §4.9).

Known simplifications, which must be stated in the UI: roll-down is ignored, duration drift over H
is ignored, credit spread moves are separate scenarios, and fund flows/turnover are ignored.

Fixture YC-1 (illustrative debt fund): YTM 7.40 %, ER 0.40 %, D_mod 3.0, H = 3 months:
* carry = (7.40 − 0.40) × 0.25 = **1.75 %**
* Δy = +50 bp: 1.75 − 3.0 × 0.50 = **0.25 %**
* Δy = −50 bp: **3.25 %**
* Δy = +100 bp: **−1.25 %** (a loss is possible over 3 months even in a "safe" fund)

Fixture YC-2: the same fund, H = 12 months: carry **7.00 %**; at ±100 bp the band is
**[4.00 %, 10.00 %]**.

Calibration requirement: B4's bands are scenarios, not probabilities. Their *empirical* coverage
against history is measured and reported (§5.3).

### 2.5 B5 — GBM Monte Carlo (allowed only with explicit caveats)

`S_H = S_0 exp((μ − σ²/2) H + σ √H Z)`, with Z ~ N(0,1).

Shown only as a teaching or comparison view, never as the primary band. These caveats must be
displayed:
* It has normal log-returns: no fat tails, no volatility clustering, no jumps (credit events),
  constant μ and σ.
* **μ is estimated with large error.** SE(μ̂) ≈ σ/√T_years. With σ = 15 % and 10 years that is
  **4.74 % per year**, larger than most fund-to-fund differences.
* It is inappropriate for debt funds and bonds, whose returns are bounded by carry and duration;
  use B4.

---

## 3. Data hygiene: point-in-time, survivorship, leakage

### 3.1 Point-in-time (PIT) rule

Every input to a forecast with origin T must have been **publicly available at T**:
* NAV for date d is usually published the evening of d. The engine uses NAV(d) only for origins
  `T ≥ d + 1 business day`. That is conservative; exact AMFI publication timing is **NOT VERIFIED**.
* Factsheet metrics (YTM, duration, holdings) are available from their **publication** date, not
  their as-of date. Monthly factsheets typically appear about 10 days after month-end;
  **NOT VERIFIED**, so store `published_at`.
* Benchmark TRI and T-bill yields: the auction result date or FBIL publication date.
* Scheme metadata (category, benchmark, expense ratio) is versioned with `valid_from`. Do not apply
  today's category to 2015 data. SEBI's scheme categorisation (Oct 2017) relabelled many schemes.

### 3.2 Revision/restatement

AMFI NAVs are occasionally corrected. The raw store is append-only with `ingested_at`, and a
backtest reads "as known at T" by default.

### 3.3 Leakage tests (automated)

* For every training sample t with label horizon H, assert `t + H ≤ T_origin`.
* No feature uses data with timestamp > t.
* Normalisation and scaling parameters are fit on the training window only.

### 3.4 Survivorship bias — documented limitation

**AMFI `NAVAll.txt` lists only schemes that currently publish a NAV.** The probe
`docs/data/probes/amfi_navall_head_20261015T053419Z.txt` is a live-scheme snapshot. Merged,
wound-up and matured schemes **vanish** from it. Examples include FMPs at maturity, mergers after
the 2017–18 SEBI categorisation, and the six debt schemes wound up in April 2020.
Consequences:
* A category universe built from today's NAVAll **excludes the failures**. Category-average
  returns are biased **upward** and risk measures **downward**.
* Rule S1: point-in-time universes must be built from historical NAV reports **by date**
  (AMFI NAV history download, probe `amfi_navhistory_*`). Whether those reports include
  since-closed schemes is **NOT VERIFIED** and is a required data probe. Until verified, every
  category-level statistic carries the banner "survivorship-biased (live schemes only)".
* Rule S2: a single-scheme forecast for a live scheme is unaffected for its own history. However,
  priors or peer comparisons from the category are affected.
* Rule S3: store a `scheme_status` history (`active`/`merged_into:X`/`wound_up`/`matured`) as soon
  as the data agent can source it.

---

## 4. Walk-forward (rolling-origin) protocol with purging and embargo

### 4.1 Protocol

1. Choose origins `T_1 < T_2 < … < T_K`, spaced by **≥ H** so that test labels do not overlap. For
   H = 1 month use monthly origins; for H = 12 months use annual origins, which gives few test
   points. For long H, report the count honestly; with fewer than 10 non-overlapping test points
   the validation verdict is `insufficient_evidence`.
2. At each origin T_k, the training set is every sample t with `t ≤ T_k − H − e`, where e is the
   embargo. The window is expanding (default) or rolling (sensitivity check).
3. Fit or estimate the model, forecast `y_{T_k}^H`, and store the full quantile vector with the
   seed and the data snapshot hash.
4. After `T_k + H`, score the forecast (§5). Aggregate over k.

**Purging** (López de Prado 2018, ch. 7). A label at t covers returns `(t, t+H]`. Any training
sample whose label window overlaps the test period, or is not fully observed at the origin, is
dropped. **Embargo** (`e`, default `max(5 business days, 0.01 × N)`) additionally removes the
samples just before the origin (and, in k-fold CV, just after each test fold). This guards against
serial correlation leaking through features.

### 4.2 Toy fixture — no leakage

Daily index t = 0..29. The label is `y_t = Σ r_{t+1..t+5}` (H = 5). The origin is T = 20 and the
test samples are t = 20..24, whose labels use r_21..r_29.

| Rule | Training samples kept | Dropped |
|---|---|---|
| Naive (t < T) | 0..19 | — |
| Purged (t + H ≤ T) | **0..15** | 16, 17, 18, 19 (labels use r_17..r_24, overlapping the test labels or unobserved at T) |
| Purged + embargo e = 2 (t ≤ T − H − e) | **0..13** | 14..19 |

Checks the test must assert:
* `max(train) + H ≤ T`: 15 + 5 = 20 ≤ 20 ✓ (purged).
* Naive fails: 19 + 5 = 24 > 20, so the label of t = 19 uses r_20..r_24, i.e. **future data
  r_21..r_24**. The test must detect this as leakage.
* The next origin T' = 25 may include t = 20 (its label r_21..r_25 is fully observed at 25), but
  only up to t ≤ 25 − 5 − 2 = 18 under the embargo. The earlier test samples 20..24 are therefore
  **not** reused at T' = 25. They enter training progressively: t = 20 at T' = 27, through t = 24
  at T' = 31 (condition t ≤ T' − 7).

k-fold CV variant (only for hyper-parameter search inside a training window): for each test fold
`[a, b]`, drop training t ∈ `[a − H, a − 1]` (purge) and t ∈ `[b + 1, b + H + e]` (purge plus
embargo).

---

## 5. Metrics

### 5.1 Point metrics (median forecast vs outcome)

* MAE = mean|y − ŷ|; RMSE = sqrt(mean (y − ŷ)²). Report both against B3.
* **Directional accuracy** = share of origins where sign(ŷ − r_f·H) = sign(y − r_f·H). Compare it
  with the base rate (the share of positive excess outcomes), not with 50 %.

### 5.2 Quantile / distribution metrics

**Pinball (quantile) loss** for quantile level τ:
`L_τ(y, q) = τ (y − q)` if y ≥ q, else `(1 − τ)(q − y)`.

Fixture PB-1: quantiles q₀.₁ = 2, q₀.₅ = 4, q₀.₉ = 7 (in %).

| Outcome y | L₀.₁ | L₀.₅ | L₀.₉ | Mean |
|---|---|---|---|---|
| 5 | 0.1 × 3 = **0.30** | 0.5 × 1 = **0.50** | 0.1 × 2 = **0.20** | **0.3333** |
| 1 | 0.9 × 1 = **0.90** | 0.5 × 3 = **1.50** | 0.1 × 6 = **0.60** | **1.0000** |
| 8 | 0.1 × 6 = **0.60** | 0.5 × 4 = **2.00** | 0.9 × 1 = **0.90** | **1.1667** |

**CRPS** (Gneiting & Raftery 2007), a proper score for the full distribution:
* Ensemble/empirical form: `CRPS = mean|X − y| − ½ mean|X − X'|`.
  * Fixture CR-1: ensemble {1, 3}, y = 2 gives 1 − ½ × (0 + 2 + 2 + 0)/4 = **0.5**.
  * Fixture CR-2: ensemble {0, 2, 4, 6}, y = 5 gives mean|X−y| = (5+3+1+1)/4 = 2.5 and
    mean|X−X'| = 40/16 = 2.5, so CRPS = 2.5 − 1.25 = **1.25**.
* Gaussian closed form: `σ[z(2Φ(z) − 1) + 2φ(z) − 1/√π]`, with z = (y−μ)/σ.
  * Fixture CR-3: N(0,1), y = 0 gives **0.233695**.
  * Fixture CR-4: N(0,1), y = 1 gives **0.602441**.
* For quantile-vector forecasts, approximate CRPS as 2 × the mean pinball loss over a dense τ grid.

**Interval score** (Gneiting & Raftery 2007) for a central (1−α) interval [l, u]:
`IS = (u − l) + (2/α)(l − y)·1{y<l} + (2/α)(y − u)·1{y>u}`.

### 5.3 Calibration: interval coverage and PIT

**Empirical coverage** = the share of non-overlapping test outcomes inside the nominal (1−α) PI.

Fixture COV-1, nominal 80 % (α = 0.2):

| k | l | u | y | inside? | IS |
|---|---|---|---|---|---|
| 1 | −2 | 3 | 1 | ✓ | 5 |
| 2 | −1 | 4 | 5 | ✗ | 5 + 10×1 = 15 |
| 3 | −3 | 2 | 0 | ✓ | 5 |
| 4 | 0 | 5 | 2 | ✓ | 5 |
| 5 | −2 | 3 | −3 | ✗ | 5 + 10×1 = 15 |
| 6 | −1 | 4 | 2 | ✓ | 5 |
| 7 | −2 | 3 | 1 | ✓ | 5 |
| 8 | −4 | 1 | 2 | ✗ | 5 + 10×1 = 15 |
| 9 | −1 | 4 | 3 | ✓ | 5 |
| 10 | −2 | 3 | 0 | ✓ | 5 |

* Coverage = **7/10 = 70 %** against nominal 80 %. Mean IS = **8.0**.
* Exact binomial two-sided p = **0.4296**. Kupiec POF: `LR = −2 ln[(0.8^7 0.2^3)/(0.7^7 0.3^3)] = 0.5634`,
  p = **0.4529** (χ²₁).
* Conclusion: **no evidence of miscalibration, and also no power.** With n = 10, coverage between
  50 % and 100 % is all statistically compatible. Rule: a calibration verdict needs ≥ 30
  non-overlapping outcomes. Below that the status is `calibration_unknown`.
* Also run the Christoffersen (1998) independence test on the hit sequence. Clustered misses mean
  the band is too static.

**PIT histogram:** `u_k = F_k(y_k)`, interpolated from the quantile vector, with u clipped to the
outer quantiles. If the model is calibrated, the u_k are Uniform(0,1). Show a 10-bin histogram.
* U-shape: the bands are too narrow (over-confident).
* Hump: the bands are too wide.
* Slope: a biased median.

### 5.4 Coverage gate (product rule)

A model's 80 % band is publishable only if the empirical coverage over ≥ 30 non-overlapping test
points lies in **[70 %, 90 %]** and the Kupiec p ≥ 0.05. Otherwise:
* widen the band by the empirical quantile-of-residuals adjustment (conformal-style recalibration on
  the walk-forward residuals), re-run validation and mark it "recalibrated"; or
* fall back to B1/B2.

---

## 6. Model promotion rule

A candidate model M replaces baseline B for an (instrument class, horizon) only if **all** of these
hold, on walk-forward held-out origins that were never used for any tuning:
1. **Proper-score improvement.** Mean CRPS (or mean pinball across the τ grid) of M is lower than
   B's by ≥ 5 % relative.
2. **Statistical significance.** Diebold–Mariano test on the loss differential `d_k = L_M,k − L_B,k`
   with HAC variance (lag H−1 for overlapping, 0 for non-overlapping) and the Harvey–Leybourne–Newbold
   (1997) small-sample correction. Require a **two-sided p < 0.05**. Two-sided is deliberately
   conservative.
3. **Calibration** is no worse: the §5.4 gate passes.
4. **Robustness.** The improvement holds in ≥ 2 of 3 sub-periods (for example pre-2020, 2020–22,
   2023+) and on the rolling-window variant.
5. **Multiple testing.** If more than one candidate or specification was tried, control the
   family-wise error. Use Holm–Bonferroni on the DM p-values, or White's (2000) Reality Check /
   Hansen's (2005) SPA test against the baseline. For any strategy-like output ranked by Sharpe,
   report the **Deflated Sharpe Ratio** (Bailey & López de Prado 2014), which adjusts for the
   number of trials, skewness and kurtosis. This is guidance only; it is not used in v1 product
   outputs.
6. **Simplicity tie-break.** If 1–5 are borderline, keep the baseline.

Fixture DM-1: ten non-overlapping origins.
* Model losses: [1.0, 0.8, 1.2, 0.9, 1.1, 0.7, 1.0, 0.9, 1.3, 0.8], mean **0.97**.
* Baseline losses: [1.1, 1.0, 1.1, 1.2, 1.0, 0.9, 1.2, 1.0, 1.2, 1.1], mean **1.08**.
* d = [−0.1, −0.2, 0.1, −0.3, 0.1, −0.2, −0.2, −0.1, 0.1, −0.3]; mean(d) = −0.11; relative
  improvement 10.2 %.
* γ̂₀ = (1/T) Σ (d − d̄)² = 0.0229. DM = d̄ / sqrt(γ̂₀/T) = −0.11/√0.00229 = **−2.2987**, giving
  p (t₉, two-sided) = **0.0471**.
* HLN factor sqrt((T + 1 − 2h + h(h−1)/T)/T) = sqrt(9/10) = 0.9487, so DM* = **−2.1807** and
  p = **0.0571**.
* **Verdict: NOT promoted.** The raw DM passes at 5 %, but the small-sample-corrected test does
  not. The baseline stays. Note also that T = 10 is below the 30-origin minimum for the calibration
  verdict (§5.3).

---

## 7. Drift monitoring (in production)

| Monitor | Computation | Alarm |
|---|---|---|
| Rolling coverage | Coverage of the 80 % band over the last 24 non-overlapping matured forecasts (36 for H ≥ 6 m) | outside [65 %, 95 %], or Kupiec p < 0.05 |
| Rolling pinball/CRPS | Ratio of M to baseline over the last 24 matured forecasts | ratio > 1.0 for 2 consecutive reviews: auto-revert to the baseline |
| Input PSI | `PSI = Σ (a_i − e_i) ln(a_i/e_i)` over deciles of key inputs (daily return, vol, YTM), recent 63 days vs training | < 0.10 stable; 0.10–0.25 watch; > 0.25 alarm (industry rule of thumb, not a statistical test) |
| Volatility regime | 21-day realised vol / 3-year median vol | > 2.0: mark the forecast `regime_stress` |
| Data freshness | Last NAV age; factsheet age | > 3 business days NAV / > 45 days factsheet: `stale` |

Fixture PSI-1: expected bin shares [0.25, 0.25, 0.25, 0.25], actual [0.10, 0.20, 0.30, 0.40]:
* bin 1: (−0.15) ln(0.4) = 0.13744
* bin 2: (−0.05) ln(0.8) = 0.01116
* bin 3: (0.05) ln(1.2) = 0.00912
* bin 4: (0.15) ln(1.6) = 0.07050
* **PSI = 0.2282**, which falls in "watch".

Zero-share bins: add ε = 1e−4 to both shares before computing, and record that in the output.

---

## 8. Conditions under which a forecast is unreliable (must suppress or downgrade)

The forecast is **suppressed** (no band shown, with the reason displayed) when:
* the history is too short for H (n_eff < 10), or the data gaps exceed the gate;
* a scheme event falls inside the training window or is announced: a merger, a fundamental
  attribute change, a category change, a benchmark change, side-pocketing, a wind-up, or
  suspension of subscriptions or redemptions;
* a credit event affects a holding (rating downgrade below investment grade, default);
* the factsheet inputs needed for B4 are older than 45 days;
* the instrument is newly launched (< 1 year).

The forecast is **downgraded** (shown with an amber banner, bands from B2 widened by the
recalibration factor) when:
* the regime stress flag is raised (vol ratio > 2), a policy-rate cycle turns (the RBI MPC changed
  the repo rate within the last 60 days, which debt-fund B1/B2 distributions do not reflect), or
  PSI > 0.25;
* the fund manager changed within 12 months;
* the calibration status is `calibration_unknown`;
* H ≥ 12 months for B1, which has few independent observations.

---

## 9. Red-team checklist — how forecasts could mislead the user

1. **A band presented as a guarantee.** An 80 % band is wrong 1 time in 5 *by design*. Always state
   "1 in 5 outcomes falls outside".
2. **CI shown as PI** shrinks the range about 3× (PI-1: ±9.3 % vs ±30.8 %).
3. **Overlapping windows inflate apparent evidence.** 2,000 overlapping 12-month windows equal
   about 8 independent years.
4. **Survivorship bias.** Category priors built from live schemes only look safer and better than
   reality (§3.4).
5. **Look-ahead via factsheet as-of dates.** Using the month-end YTM before its publication date
   leaks information.
6. **Leakage via unpurged overlapping labels** makes backtests look skilful (§4.2).
7. **Quoted YTM ≠ the expected return of a debt fund.** Carry minus expenses ± duration shocks,
   plus credit and roll-down, all matter (YC-1: a 3-month loss is possible at +100 bp).
8. **GBM normality hides fat tails and jumps.** μ estimation error (±4.7 %/yr) swamps the
   differences between funds.
9. **Bootstrap/history cannot produce unseen events**, such as a first-ever credit event in a fund.
10. **Small-sample "wins"** (DM-1) are noise until corrected for sample size and multiple testing.
11. **Directional accuracy compared with 50 %** instead of the base rate (markets rise more often
    than not) overstates skill.
12. **Regime change** (a rate-cycle turn, Mar-2020-type stress) breaks stationarity. Monitors must
    downgrade quickly.
13. **Deterministic seeds reproduce the same sampling error every time.** Report the Monte Carlo
    standard error so stability is not mistaken for precision.
14. **Annualising horizon forecasts.** A 1-month band must be shown as a 1-month ₹ range (calc
    Rule A3).

## Sources

* Politis, D. N., Romano, J. P. (1994). "The Stationary Bootstrap." *JASA* 89(428).
* Politis, D. N., White, H. (2004). "Automatic Block-Length Selection for the Dependent Bootstrap."
  *Econometric Reviews* 23(1). Correction: Patton, Politis, White (2009), *Econometric Reviews* 28(4).
* López de Prado, M. (2018). *Advances in Financial Machine Learning*, Wiley, ch. 7 (purged
  k-fold, embargo) and ch. 12.
* Bailey, D. H., López de Prado, M. (2014). "The Deflated Sharpe Ratio." *J. Portfolio Management* 40(5).
* White, H. (2000). "A Reality Check for Data Snooping." *Econometrica* 68(5).
* Hansen, P. R. (2005). "A Test for Superior Predictive Ability." *J. Business & Economic Statistics* 23(4).
* Diebold, F. X., Mariano, R. S. (1995). "Comparing Predictive Accuracy." *JBES* 13(3).
* Harvey, D., Leybourne, S., Newbold, P. (1997). "Testing the equality of prediction mean squared
  errors." *Int. J. Forecasting* 13(2).
* Gneiting, T., Raftery, A. E. (2007). "Strictly Proper Scoring Rules, Prediction, and Estimation."
  *JASA* 102(477).
* Kupiec, P. (1995). "Techniques for verifying the accuracy of risk measurement models."
  *J. Derivatives* 3(2). Christoffersen, P. (1998). "Evaluating Interval Forecasts." *Int. Economic Review* 39(4).
* Hyndman, R. J., Athanasopoulos, G. *Forecasting: Principles and Practice* (3e), §5.10 time-series
  cross-validation.
* Siddiqi, N. (2006). *Credit Risk Scorecards* (PSI rule-of-thumb thresholds).
* AMFI NAV probes, `docs/data/probes/` (live-scheme-only NAVAll; NAV history by date).

Fixture oracle: numpy 2.4 / scipy 1.17 (`stats.binomtest`, `stats.chi2`, `stats.t`, `stats.norm`).
All fixtures above were reproduced to ≥ 4 significant figures.
