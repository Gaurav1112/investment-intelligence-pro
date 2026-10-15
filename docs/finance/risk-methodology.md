# Risk Methodology (Agent C — Financial Mathematics)

Status: specification v1 · Date: 2026-10-15 · Companion to `calculation-methodology.md`

Risk statistics run at the **float boundary** (calculation-methodology §1.3). Inputs are Decimal
price/NAV series converted once to float64. Outputs leave the boundary through `Decimal(repr(x))` and
are quantized with HALF_EVEN. Every metric has a **minimum-data gate**. Below the gate the engine
returns `InsufficientData(metric, required, available)`. It never returns a number.

---

## 1. Return series construction

| Rule | Specification |
|---|---|
| Source | Growth-option NAV. IDCW options are converted to total-return series first (calc §2.7). Index benchmarks are **TRI** (total-return index), never price index. SEBI mandated TRI benchmarking for MFs from Feb 2018; that circular was not re-fetched here, so the date is **NOT VERIFIED in this session**. |
| Calendar | MF NAVs are published on **business days only** (see the AMFI probes in `docs/data/probes/`). There are no weekend rows. Do **not** forward-fill weekends or holidays into the return series. |
| Simple return | `r_t = P_t / P_{t−1} − 1` between **consecutive published observations** |
| Log return | `ℓ_t = ln(P_t / P_{t−1})` |
| Which to use | **Log** returns for volatility, correlation, beta and time-aggregation, because they are additive over time. **Simple** returns for VaR/CVaR in ₹, downside deviation, drawdown (from levels) and any cross-sectional (portfolio-weighted) aggregation, because they are additive across assets. |
| Gaps | A gap of more than 7 calendar days between observations (outside known holiday lists) makes the observation `suspect`. If gaps exceed 2 % of observations, the series is rejected for risk stats. |
| Weekend accrual effect | Debt/liquid fund NAVs accrue 3 days of carry on Monday (Fri→Mon). Monday returns are systematically larger, which inflates measured daily vol slightly for very-low-vol funds. For liquid/overnight/money-market funds, compute vol from **weekly** (Wednesday-to-Wednesday) returns instead. |
| Alignment for pairwise stats | Inner-join on dates. Never compare a fund's NAV date t with a benchmark close on a different date. International / FoF schemes whose NAV reflects the previous day's overseas close must use **weekly** returns (or a Dimson lead/lag beta). |

### 1.1 Annualisation factor

`A = number of return observations / (calendar span in days / 365.25)`, estimated from the series
itself and rounded to an integer. Indian exchange trading days and MF business days run about
245–250 per year. That range is **NOT VERIFIED** as a constant and varies with the holiday
calendar, which is why `A` is estimated. Fallback when the span is under 1 year: `A = 248`. Using
252 instead changes annualised vol by `√(248/252) = 0.992`, about 0.8 % relative. That is
immaterial, but `A` must be **consistent** across every instrument compared in the same view.

Frequency compatibility rules:
1. Every series in one comparison has the same frequency, the same end date and the same window.
2. A risk-free rate is converted to the series frequency **before** subtraction.
3. Daily and monthly statistics are never mixed (for example daily vol with monthly Sharpe).
4. `√A` scaling of volatility is allowed for display. `√t` scaling of VaR/quantiles is **not** the
   default; see §5.

---

## 2. Volatility

`σ_period = stdev(ℓ, ddof=1)`; `σ_ann = σ_period × √A`.

**Fixture set R** (used throughout). Ten daily simple returns:
`r = [+1, −1, +2, −1, −3, +1, +3, −1, +2, +1] %`.
NAV path from 100: `100, 101, 99.99, 101.9898, 100.969902, 97.940805, 98.920213, 101.887819, 100.868941, 102.88632, 103.915183`.

| Statistic | Value |
|---|---|
| mean(r) | 0.004000 |
| stdev(r), ddof=1 | 0.018379 |
| σ_ann (simple), A=252 | 29.1753 % |
| ℓ = ln(1+r) | [0.00995033, −0.01005034, 0.01980263, −0.01005034, −0.03045921, 0.00995033, 0.02955880, −0.01005034, 0.01980263, 0.00995033] |
| mean(ℓ) | 0.00384048 |
| stdev(ℓ), ddof=1 | 0.01837370 |
| σ_ann (log), A=252 | **29.1673 %** |

Fixture R uses 10 points to test the formula. In production it would be gated (§10).

---

## 3. Maximum drawdown and duration

`peak_t = max_{s≤t} P_s`; `DD_t = P_t / peak_t − 1`; `MDD = min_t DD_t`.
Durations, in observations and calendar days:
* peak → trough
* trough → recovery (first t with `P_t ≥ peak` at the trough; "not recovered" if none)
* total underwater = peak → recovery

Fixture R: DD = [0, 0, −1.00 %, 0, −1.00 %, **−3.97 %**, −3.0097 %, −0.10 %, −1.099 %, 0, 0].
* MDD = **−3.9700 %** (peak index 3 = 101.9898; trough index 5 = 97.940805; `0.99 × 0.97 − 1`)
* peak → trough = 2 observations; trough → recovery = 4 (index 9 = 102.88632); underwater = 6
  observations.

Edge cases:
* A series that starts in a drawdown has an unknown pre-sample peak. Label it "MDD within
  available history".
* An unrecovered drawdown at the end of the series reports the duration as "≥ n (ongoing)".
* Debt funds with credit events (side-pocketing) show a **one-day cliff**. Report the cliff
  separately as "largest 1-day loss".

---

## 4. Sharpe and Sortino

### 4.1 Sharpe

`SR_period = mean(r − r_f,t) / stdev(r − r_f,t)`, and `SR_ann = SR_period × √A` (valid only under
i.i.d. returns; see 4.3).

The risk-free rate is the **91-day T-bill yield**, point-in-time for each date. The preferred source
is the FBIL T-bill benchmark; the fallback is the RBI weekly auction cut-off. Conversion:
`y_eff = (1 + y × 91/365)^(365/91) − 1`, then `r_f,period = (1 + y_eff)^(1/A) − 1`.
FBIL publication cadence and licensing are **NOT VERIFIED**; Agent B / the data doc owns the
source decision.

Fixture R with a constant `y_eff = 6.50 %`, A = 252:
`r_f,d = 1.065^(1/252) − 1 = 0.00024993`; mean excess = 0.00375007; SR_d = **0.204044**;
SR_ann = **3.2391**.

### 4.2 Sortino and downside deviation

Target `τ` is the minimum acceptable return. It defaults to `r_f`, and the UI may offer 0. Use the
**full-sample denominator** (lower partial moment of order 2):
`DD_τ = sqrt( (1/N) Σ min(r_t − τ, 0)² )`; `Sortino = (mean(r) − τ) / DD_τ`, annualised
`× √A` (with τ per period).

Fixture R, τ = 0: the negative returns are −0.01 ×3 and −0.03. The sum of squares is
`3 × 1e−4 + 9e−4 = 1.2e−3`, divided by N = 10 gives 1.2e−4, so **DD = 0.0109545**.
Sortino_d = 0.004/0.0109545 = **0.365148**; annualised = **5.7966**.
A common bug divides by the count of negative observations (4) instead of N (10). A test must
catch it.

### 4.3 Autocorrelation adjustment (mandatory for debt / hybrid / illiquid holdings)

Debt-fund NAVs are **smoothed**: their holdings are valued by matrix pricing or with stale
valuations. This produces positive autocorrelation, so `√A` overstates the annualised Sharpe and
understates vol (Getmansky, Lo & Makarov 2004).

Lo (2002): `SR_q = η(q) × SR_period`, with `η(q) = q / sqrt(q + 2 Σ_{k=1}^{q−1} (q−k) ρ_k)`.

Fixture LO-1: q = 2, ρ₁ = 0.3 gives `η = 2 / sqrt(2 + 2·1·0.3) = 2/√2.6 = 1.2403`, versus the i.i.d.
`√2 = 1.4142`. That is a 12 % haircut.

Rule: if the Ljung-Box test on daily returns rejects at 5 % (lags 1–10), or the category is
debt/liquid/hybrid, compute the Sharpe from **monthly** returns (A = 12) with Lo's adjustment, and
flag "autocorrelation-adjusted".

---

## 5. Value-at-Risk and CVaR (historical)

Sign convention: VaR and CVaR are reported as **positive losses**, in % and in ₹ (₹ = Decimal
position × float-boundary fraction).

### 5.1 One-period historical VaR

Quantile method, which is **mandated and must be identical across the codebase**: lower empirical
quantile (Hyndman–Fan type 1, `numpy.quantile(method="inverted_cdf")`).
`k = ceil(N × (1−α))`; `VaR_α = −r_(k)` (the k-th smallest return).
`CVaR_α = −mean(r_(1..k))`.

Fixture R (N = 10), sorted: [−3, −1, −1, −1, +1, +1, +1, +2, +2, +3] %.

| α | k | VaR | CVaR | Note |
|---|---|---|---|---|
| 90 % | 1 | **3.00 %** | **3.00 %** | linear interpolation (numpy default) would give 1.20 %, so the method choice matters |
| 80 % | 2 | **1.00 %** | **2.00 %** | |

### 5.2 Horizon VaR (1/3/6/12 months)

**Preferred**: the empirical distribution of **overlapping h-period returns**,
`R_t^h = P_{t+h}/P_t − 1`, taken directly from the data.

Caveats that must be shown:
* Overlapping windows are heavily autocorrelated. The effective sample size is about
  `n_eff = floor(N / h)`. With 3 years of daily data (≈ 744 obs) and h = 21 there are 724
  overlapping windows but only **35** independent months.
* Confidence intervals must come from a block bootstrap (validation-methodology §2.2), not from the
  overlapping count.

**Not preferred**: `VaR_h = VaR_1 × √h`. This assumes i.i.d. returns and zero mean. With AR(1)
autocorrelation ρ the variance scales by `h × [1 + 2 Σ_{k=1}^{h−1} (1 − k/h) ρ^k]`.

Fixture SQ-1: 1-day VaR 1.50 %, h = 21. The √t rule gives 1.5 × 4.5826 = **6.87 %**. With ρ = 0.2,
the variance factor is 1.4702, so the VaR is 1.5 × √(21 × 1.4702) = **8.33 %**: √t understates by
about 18 %. √t is used only as a labelled fallback, and never for debt funds.

### 5.3 Gates

* "VaR" may be labelled as such only if `span ≥ 3 years` **and** `n_eff ≥ 20` for the chosen h.
  * 1 month: 3 years suffices.
  * 3 months: needs about 5 years.
  * 6 months: about 10 years.
  * 12 months: about 20 years. This usually fails, so present **scenario bands** from the
    validation baselines (yield-carry, bootstrap) instead.
* 1-day 95 %: at least 3 years daily (≈ 37 tail observations). 1-day 99 %: at least 10 years (≈ 25
  tail observations). With fewer observations show "worst observed loss in N years" instead.
* CVaR needs at least 10 tail observations (`ceil(N_eff(1−α)) ≥ 10`).

---

## 6. Beta, tracking error, correlation

Use aligned log returns at the same frequency (§1). For daily data require at least 250 common
dates; for monthly at least 36.

* `β = cov(r_p, r_b) / var(r_b)` (ddof=1 on both)
* `TE = stdev(r_p − r_b) × √A` (simple returns, ddof=1)
* Information ratio `IR = mean(r_p − r_b) × A / TE`
* Correlation: Pearson on log returns. Also report Spearman. If |Pearson − Spearman| > 0.2, flag
  "non-linear / outlier-driven".
* Rolling 1-year correlation: show its range. A single full-period correlation hides regime
  changes (correlations rise in crises).

Fixture R with benchmark `b = [0.8, −1.2, 1.5, −0.5, −2.5, 1.2, 2.0, −0.8, 1.8, 0.6] %`, simple returns:
mean(b) = 0.0029; var(b) = 2.185444e−4; cov(r, b) = 2.671111e−4; **β = 1.2222**; ρ = **0.9831**.
Active returns `r − b = [0.2, 0.2, 0.5, −0.5, −0.5, −0.2, 1.0, −0.2, 0.2, 0.4] %`; TE_d = 0.0047011;
**TE_ann = 7.4627 %** (A = 252).

Beta for debt funds against an equity index is meaningless. Compute it against the category's debt
TRI only.

---

## 7. Concentration, credit, liquidity

### 7.1 Concentration (HHI)

`HHI = Σ w_i²` on market-value weights, at each of these levels: instrument, issuer (look-through
into MF portfolios from monthly/fortnightly disclosures), AMC, bank (for FDs) and asset class.
`N_eff = 1/HHI`.

Fixture H-1: w = [0.4, 0.3, 0.2, 0.1] gives **HHI = 0.30**, N_eff = **3.33**.

Display bands (guidance, not regulation): HHI < 0.15 is diversified; 0.15–0.25 moderate; > 0.25
concentrated.

### 7.2 Credit exposure

* Buckets: Sovereign (T-bill, G-sec), Quasi-sovereign (SDL: state credit with an RBI-managed
  payment mechanism; treated as sovereign-like but shown separately), AAA, AA, A and below,
  unrated.
* FD exposure per bank versus the DICGC insurance cover. The cover is **₹5 lakh per depositor per
  bank**, principal plus interest, since Feb 2020. That figure was **not re-fetched in this
  session**: confirm it with Agent B's doc. The excess above the cover is shown as an unsecured
  bank-credit exposure.
* MF credit look-through: the share of the portfolio below AAA, the largest single non-sovereign
  issuer weight, and any side-pocket flag.

### 7.3 Liquidity indicators (per holding)

| Indicator | Example |
|---|---|
| Days-to-cash | Liquid/overnight fund T+1; equity funds within 3 working days (SEBI). Both are **NOT VERIFIED in this session**; see Agent B. FD: same day if premature; G-sec via secondary market T+1 |
| Exit cost % | Exit load + premature FD penalty + estimated bid-ask (`exit_spread_bp`) |
| Lock-in | Tax-saver FD 5 years (no premature withdrawal); ELSS 3 years |
| Market depth flag | Corporate bonds/SDLs with no trade in 30 days are flagged "illiquid — price is an estimate" |
| Gate/wind-up history | AMC/scheme-level event flags (e.g. the debt-scheme wind-ups of Apr 2020) |

### 7.4 Rate sensitivity (portfolio)

`D_port = Σ w_i D_mod,i` across MTM holdings. MF modified duration comes from the factsheet (as-of
dated). Bonds use calc §4.4. FDs and hold-to-maturity T-bills have **no MTM** but carry
reinvestment risk; show them separately.
`ΔV ≈ −D_port × V × Δy`, with full repricing for |Δy| > 100 bp.

### 7.5 Scenario loss

A deterministic scenario table, versioned:

| Scenario | Shock |
|---|---|
| Rates +100 / +200 bp, parallel | full repricing of bonds; MF via D_mod and convexity if disclosed |
| Rates −100 bp | gain, plus FD/T-bill reinvestment-rate drop |
| Credit spread +100 bp (AAA) / +300 bp (AA and below) | spread duration |
| Single-issuer default | exposure × (1 − recovery). Recovery is a parameter (default 25 %, **NOT VERIFIED**; illustrative) |
| Equity −10 / −20 / −35 % | β × shock on equity-oriented holdings |
| Liquidity freeze | MF wind-up style lock: value is unavailable for the horizon |

`Loss = Σ_i ΔV_i`. Always report it in ₹ and as % of the portfolio, and never probability-weight it
silently.

---

## 8. Minimum data requirements (gate table)

| Metric | Minimum | Below minimum |
|---|---|---|
| Volatility (display) | 252 daily obs (1 y); 60 obs → "low confidence" | refuse below 60 |
| Max drawdown | 3 years | label "in available history (N y)" |
| Sharpe / Sortino | 3 years daily (≈ 744) or 36 monthly; Sortino also needs ≥ 20 below-target obs | refuse |
| 1-day VaR 95 % / 99 % | 3 y / 10 y | worst observed loss |
| Horizon VaR (h) | 3 y **and** n_eff = N/h ≥ 20 | scenario bands |
| CVaR | ≥ 10 tail obs (effective) | refuse |
| Beta / TE / correlation | 250 aligned daily obs or 36 monthly | refuse |
| HHI | current holdings snapshot ≤ 45 days old | "stale" flag |
| Portfolio duration | factsheet ≤ 45 days old | "stale" flag |

---

## 9. Ranking heterogeneous instruments (normalisation without a single misleading score)

**Principle: never build a weighted composite** of Sharpe, yield, volatility and similar metrics
across FDs, T-bills, bonds and funds. These metrics are undefined or incomparable across classes.
An FD has zero measured volatility, so its Sharpe is infinite. A T-bill's "vol" is zero to maturity.
Debt-fund vol is smoothed. A composite score would rank on artefacts. Use this pipeline instead:

**Step 1 — Hard constraints (eligibility filter).** Each one is a boolean with a stated reason:
* Horizon fit. Maturity/lock-in ≤ H, or a modelled early-exit (penalty/price scenario) is
  available. Exit-load window versus H.
* Capital-preservation goal: `P(loss at H) ≤ ε`, with ε = 1 % by default, **and** the 5th percentile
  of the horizon outcome ≥ −x %, with x = 0 by default.
* Liquidity need (days-to-cash ≤ the user's need), credit floor (e.g. ≥ AA), DICGC limit, minimum
  ticket size, and data sufficiency (§8 gates pass).

**Step 2 — Horizon-matched ₹ outcome bands** (after costs and taxes, for the same ₹ amount and the
same H):
* Contractual (FD, or a T-bill/bond held to maturity = H): a point outcome. Credit risk is shown as
  a flag, not a band.
* Market-dependent: (q05, q50, q95) from the validation baselines. Use the empirical overlapping
  windows plus a block bootstrap for funds, yield-carry ± duration scenarios for bonds and debt
  funds, and early-exit repricing for bonds with maturity > H.

**Step 3 — Certainty class tiers:**
* T1 Contractual sovereign: T-bill, G-sec to maturity
* T2 Contractual non-sovereign: FD within DICGC, AAA bond to maturity
* T3 Market-dependent, bounded: liquid/overnight/money-market funds; bonds with an early exit
* T4 Market-dependent, unbounded: duration/credit funds, hybrid, equity

**Step 4 — Goal-specific lexicographic ordering:**
* Capital preservation: sort by tier, then by q05 (or the point outcome) descending, then by
  liquidity and cost. A higher median **never** compensates for a worse lower band.
* Growth (H ≥ 12 months, user accepted a loss tolerance L): require q05 ≥ −L, then sort by a
  certainty-equivalent `CE = q50 − λ (q50 − q05)`, with λ ∈ [0, 1] from the user's risk answer
  (default 0.5). Ties are broken by tier.
* Always show the band, the reasons for exclusion and the tier. Never show a single "score".

**Worked example — why equity must not outrank a T-bill for a 1-month capital-preservation goal.**
The amount is ₹1,00,000 and H = 30 days. All numbers are **illustrative, not data**.
* T-bill (secondary, 30 days to maturity, yield 6.50 %): +6.50 % × 30/365 = **+0.534 %**, i.e.
  ₹1,00,534 (contractual). P(loss) = 0.
* Equity index fund: illustrative empirical 1-month distribution q05 = −7 %, q50 = +1.0 %,
  q95 = +8 %, with P(loss) about 40 %.
* Step 1: equity fails `P(loss) ≤ 1 %` and `q05 ≥ 0`, so it is **excluded** (shown greyed out with
  the reason). Even without that filter, Step 4 sorts by q05: −7 % < +0.534 %.
* The equity median (+1.0 %) beats the T-bill, which is exactly why mean/median-based or
  Sharpe-composite scores mis-rank. Note also that the T-bill's Sharpe is undefined (zero vol).

---

## 10. Implementation notes and fixtures index

| Fixture | Section | Key outputs |
|---|---|---|
| R (returns) | 2 | σ_ann(log) 29.1673 % |
| R (MDD) | 3 | −3.97 %, 2/4/6 obs |
| R (Sharpe) | 4.1 | 0.204044 daily, 3.2391 ann |
| R (Sortino) | 4.2 | DD 0.0109545; 0.365148 / 5.7966 |
| LO-1 | 4.3 | η = 1.2403 |
| R (VaR) | 5.1 | 90 %: 3.00/3.00; 80 %: 1.00/2.00 |
| SQ-1 | 5.2 | 6.87 % vs 8.33 % |
| R+b (β, TE) | 6 | β 1.2222, ρ 0.9831, TE 7.4627 % |
| H-1 | 7.1 | HHI 0.30 |

Oracle: numpy 2.x / scipy 1.17. Computation script reproduced in the tests; tolerance 1e-6.

---

## 11. Red-team checklist — how risk metrics could mislead the user

1. **Sharpe on autocorrelated debt-fund NAVs overstates risk-adjusted return.** Smoothing makes vol
   look low (§4.3).
2. **Credit events cause jump losses invisible in historical vol.** A AA debt fund with 1 % vol can
   lose 5–10 % in a day on a default or side-pocket. Show the credit flags next to every vol number.
3. **Zero-vol instruments get infinite Sharpe.** Never rank FDs or T-bills with Sharpe.
4. **√t scaling understates horizon risk** when returns trend or are autocorrelated (SQ-1: −18 %).
5. **Overlapping-window VaR looks precise** (724 windows) while having only about 35 independent
   observations.
6. **The quantile method changes VaR** from 1.2 % to 3.0 % on small samples (§5.1).
7. **A short window that misses a crisis** (e.g. starting after Mar-2020) gives a benign MDD and VaR.
8. **Survivorship.** Wound-up or merged schemes disappear from AMFI NAVAll, so category risk
   statistics are biased low (validation-methodology §3.4).
9. **A price-index benchmark** instead of TRI inflates alpha by the dividend yield.
10. **Non-synchronous NAVs** (international FoFs) bias daily beta and correlation towards 0.
11. **A full-period correlation hides crisis correlation spikes.** Diversification fails exactly when
    needed.
12. **HHI at scheme level hides issuer overlap.** Three debt funds can all hold the same NBFC.
    Look through.
13. **A Sortino with the wrong denominator** inflates the ratio about √(N/N_neg)-fold.
14. **A composite score** across asset classes rewards artefacts. Use tiers, bands and lexicographic
    ordering (§9).
15. **The duration figure is as of the last factsheet.** Fund managers change duration actively, so
    stale duration misstates rate risk.
16. **The DICGC limit is per bank, not per FD.** Five FDs at one bank share one ₹5 lakh cover.

## Sources

* Lo, A. W. (2002). "The Statistics of Sharpe Ratios." *Financial Analysts Journal* 58(4).
* Getmansky, M., Lo, A. W., Makarov, I. (2004). "An econometric model of serial correlation and
  illiquidity in hedge fund returns." *J. Financial Economics* 74(3).
* Sortino, F., Price, L. (1994). "Performance measurement in a downside risk framework." *J. Investing*.
* Hyndman, R. J., Fan, Y. (1996). "Sample quantiles in statistical packages." *American Statistician* 50(4).
* Dimson, E. (1979). "Risk measurement when shares are subject to infrequent trading." *JFE* 7(2).
* Ljung, G. M., Box, G. E. P. (1978). *Biometrika* 65(2).
* RBI FAQ on G-Secs (T-bill yield convention, used for r_f). https://www.rbi.org.in/Scripts/FAQView.aspx?Id=79
* AMFI NAV probes in `docs/data/probes/` (business-day publication, Growth/IDCW split).
* Agent B, `docs/research/indian-instruments-and-tax.md` (liquidity, DICGC, scheme events).
