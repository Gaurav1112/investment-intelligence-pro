# Calculation Methodology (Agent C — Financial Mathematics)

Status: specification v1 · Date: 2026-10-15 · Engine: Python 3.12 · Owner: Agent C

This document is the implementation contract for every return, cash-flow and fixed-income
formula in Investment Intelligence Pro. Each formula lists **inputs, units, conventions, edge
cases, failure modes and an independent oracle**. Every fixture below was computed twice: once by
hand / `decimal.Decimal` and once with an independent oracle. The oracles were QuantLib 1.44 for
bonds and `scipy.optimize.brentq` for IRR. Tests MUST reproduce them to the stated tolerance.

Verification legend. **VERIFIED** means checked against a primary or regulator source, cited.
**VERIFIED (secondary)** means checked against at least two consistent industry sources but not
the primary text. **NOT VERIFIED** means a design assumption that must stay configurable.

---

## 0. Conventions used everywhere

| Item | Convention |
|---|---|
| Currency | INR. Money is `Decimal`; smallest unit is the paisa (0.01). |
| Rates | Stored as decimal fractions (`Decimal("0.0650")` = 6.50 %). Display multiplies by 100. Never store percent numbers. |
| Basis points | 1 bp = 0.0001. |
| Year fraction for returns / XIRR / CAGR | Actual/365 (fixed 365, including leap years). This is Excel `XIRR` semantics. |
| Year fraction for G-sec/SDL accrual | 30E/360 (Excel basis 4). **VERIFIED** that it is 30/360: RBI FAQ on G-Secs says "Basis … (4 for Government bonds in India which uses 30/360 basis)". The month-end *variant* is inferred from that Excel basis-4 (European) reference. RBI's worked example (25-Nov → 30-Jan) gives 65 days under both the US and the European variant, so it does not discriminate. Status of the variant: **VERIFIED (secondary, by Excel-basis reference)**. Before go-live, confirm it against the FIMMDA handbook (Agent B flags the same open point). |
| Year fraction for T-bills / money market | Actual/365. **VERIFIED**: RBI FAQ says "Money market: … actual/365 … in the case of T-Bills … money market convention is followed". |
| Year fraction for listed corporate bonds | Actual/Actual (366 when 29 Feb falls in the period). **VERIFIED (secondary)**: SEBI circular CIR/IMD/DF-1/122/2016 (11 Nov 2016), now folded into the NCS master circular. |
| Dates | `datetime.date`, IST calendar days. No timestamps in the financial core. |
| Horizon end date | `EDATE` semantics: same day-of-month N months later, clamped to month-end (31 Jan + 1M = 28/29 Feb). |
| Price lookup at a date | Last published NAV/price **on or before** the date (no look-ahead). If none exists within 7 calendar days, raise `StaleData`. |

---

## 1. Money and precision policy

### 1.1 Decimal context

```python
from decimal import Context, ROUND_HALF_EVEN, InvalidOperation, DivisionByZero, Overflow
ENGINE_CTX = Context(prec=34, rounding=ROUND_HALF_EVEN,
                     traps=[InvalidOperation, DivisionByZero, Overflow])
```

* `prec=34` matches IEEE 754 decimal128. It gives 34 significant digits: enough for ₹10^15 with
  18 decimal places of headroom, and for fractional powers in CAGR/discount factors without visible
  error.
* All engine functions run inside `decimal.localcontext(ENGINE_CTX)`. Never mutate the global
  context, because threads and tests would leak state.
* `Inexact` and `Rounded` are **not** trapped, since division is inherently inexact.
* Construct Decimals from **strings or ints only**. `Decimal(0.1)` from a float is forbidden; a lint
  rule or test should grep for `Decimal(` with float literals.
* Fractional powers (`(1+r) ** (Decimal(365)/days)`) are allowed. The Python `decimal` module
  computes them to context precision. Alternatively use `(x.ln() * e).exp()`.

### 1.2 Rounding — recommendation

**Rule R1: never quantize intermediates.** Quantize exactly once, at the output boundary (API DTO or
UI). Chained rounding causes drift. The exception is "replication" amounts that a counterparty
itself rounds before using them (stamp duty, allotted units). Those are quantized at the point where
the counterparty would quantize them (R4).

**Rule R2: INR money shown to the user is quantized to paise with `ROUND_HALF_UP`.**
Justification:
1. Users reconcile our figures against bank FD advices, AMC statements and CAS. Those use
   commercial "half rounds up" rounding. A ±1 paisa mismatch on an exact tie erodes trust in a
   decision tool for no benefit.
2. Indian statutory rounding (income-tax rounding of total income and tax to the nearest ₹10,
   s.288A/288B of the 1961 Act) rounds .5 upward. The section numbers under the Income-tax Act 2025
   are **NOT VERIFIED**.
3. Bias is immaterial at the scale of single user-facing figures.

**Rule R3: rates, percentages, ratios and statistical outputs use `ROUND_HALF_EVEN`.** This also
applies to any quantity that is summed after quantization. Banker's rounding is unbiased, so totals
of many quantized values do not drift upward. Display precision:

| Quantity | Display quantum | Rounding |
|---|---|---|
| INR amount | 0.01 | HALF_UP |
| INR amount, headline ("≈ ₹1.07 lakh") | presentation only | HALF_UP |
| Return / yield / rate (%) | 0.01 % (Decimal 0.0001) | HALF_EVEN |
| Bond price per ₹100 | 0.0001 | HALF_EVEN (RBI quotes 4 dp) |
| Accrued interest per ₹100 | 0.0001 | HALF_UP (replicates RBI FAQ example 1.5943) |
| Duration (years), convexity | 0.0001 / 0.01 | HALF_EVEN |
| MF units | 0.001 | **ROUND_DOWN** when replicating allotment (NOT VERIFIED; AMC practice varies; prefer the unit balance from the investor's CAS) |
| NAV | as published (3 or 4 dp; the AMFI files show both) | never re-quantize |

**Rule R4: replication mode.** When we recompute a figure a counterparty prints, we apply that
counterparty's rounding at the counterparty's step. Examples are stamp duty to paise, FD maturity
to paise, and units to 3 dp. Each such fixture records `rounding_mode` explicitly.

Rounding fixtures (quantum 0.01):

| Input | HALF_EVEN | HALF_UP |
|---|---|---|
| 2.345 | 2.34 | 2.35 |
| 2.355 | 2.36 | 2.36 |
| 10.005 | 10.00 | 10.01 |
| −2.345 | −2.34 | −2.35 (away from zero) |
| 0.125 | 0.12 | 0.13 |

### 1.3 Where floats are allowed (the "statistics boundary")

Floats (`numpy.float64`) are allowed **only** in these places:
1. Return-series statistics: volatility, drawdown series, VaR/CVaR, beta, correlation, bootstrap,
   Monte Carlo, forecast metrics. See risk-methodology.md and validation-methodology.md.
2. Root finding for XIRR/YTM. The root is then **verified in Decimal**; see §3.5.

Boundary rules:
* Converting into float: `float(decimal_value)`. This is done once per series, at module entry.
* Converting out of float: `Decimal(repr(x))` (the shortest round-trip string), then quantize per R3.
  `Decimal(x)` straight from a float is never allowed.
* Float results that are money (for example "VaR ₹ 1,234.56") are converted to Decimal **before**
  multiplying by the position size. That way the money multiplication happens in Decimal.
* Floats never flow back into the money ledger, the tax computation or the FD/bond cash-flow
  engines.
* NaN or Inf crossing the boundary raises `NumericalError`. It is never displayed.

---

## 2. Return measures

### 2.1 Absolute (holding-period) return

`R_abs = V_end / V_start − 1` for one lump sum with no intermediate flows.

Inputs: `V_start > 0` and `V_end ≥ 0` (Decimal INR or NAV). Output: a Decimal fraction.
Failure: `V_start ≤ 0` raises `InvalidInput`.
Oracle: arithmetic.

### 2.2 Simple annualised return

`R_simple_ann = R_abs × 365 / d`, where `d` is the calendar days held.

Use it **only** as a labelled secondary figure. It is acceptable for money-market quotes (T-bill
yield, liquid-fund "simple annualised 7-day" figures) because those markets quote that way.

### 2.3 When NOT to annualise (headline rule)

**Rule A1.** If the holding period or horizon is under 365 days, the headline is the **absolute**
return in % and ₹ over that period. The app never headline-annualises an under-1-year return.
At 365 days or more, the headline is CAGR, with absolute return as a secondary figure.

**Rule A2.** Quoted yields (T-bill yield, FD card rate, YTM, liquid-fund portfolio YTM) are
annualised **by market convention**. They must be labelled "annualised yield (quote)". They must
never be compared side-by-side with an absolute return. For comparisons the engine converts
everything to the **same horizon's absolute ₹ outcome**. For example, a 91-day T-bill at 6.50 %
becomes "₹ 1,00,000 → ₹ 1,01,620.55 in 91 days".

**Rule A3.** Forward-looking outcomes for the 1/3/6/12-month horizons are always shown as absolute
₹ and % for that horizon.

Regulatory alignment, **VERIFIED (secondary)**. The SEBI MF advertisement code (master circular)
requires CAGR for 1y, 3y, 5y and since inception. It forbids past performance for schemes under
6 months old. For schemes between 6 months and 1 year it allows a *simple annualised* 6-month
figure. The older SEBI 2000 guidelines said under-1-year returns "should not be annualised". The
widespread investor-education convention (AMFI/Zerodha Varsity) is "absolute below 1 year, CAGR
above". Rule A1 is deliberately **more conservative** than the current ad code. This app is not an
advertisement; its goal is to avoid extrapolating short windows.

Fixture A-1, annualising a 7-day return. 0.10 % in 7 days gives simple annualised
`0.001 × 365/7 = 5.2143 %` and compound annualised `1.001^(365/7) − 1 = 5.3499 %`. The headline per
A1 is "**0.10 % in 7 days**". Both annualised numbers are extrapolations.

### 2.4 CAGR

`CAGR = (V_end / V_start)^(365 / d) − 1`, with `d` = calendar days (Actual/365).

This equals XIRR for a single outflow and a single inflow. Use the actual days count, **not** a
whole number of years. Fixtures:

| # | V_start | V_end | Dates | d | CAGR | Note |
|---|---|---|---|---|---|---|
| CAGR-1 | 100 | 112 | 2025-01-01 → 2026-01-01 | 365 | 12.0000 % | base |
| CAGR-2 | 100 | 121 | 2024-01-01 → 2026-01-01 | 731 | **9.9857 %** | leap year inside; "2 years" would give 10.0000 % |
| CAGR-3 | 10.0000 | 13.3100 | 2023-10-13 → 2026-10-13 | 1096 | **9.9904 %** | contains 29-Feb-2024; integer-years shortcut gives 10.0000 % |

Worked CAGR-2: `1.21^(365/731) = exp(0.498632 × ln 1.21) = exp(0.498632 × 0.190620) = exp(0.095049) = 1.099857`.

Edge cases: `d < 365` makes CAGR a non-headline figure (Rule A1). `d = 0` raises `InvalidInput`.
If `V_end = 0`, CAGR is −100 %.
Oracle: Excel `=(B/A)^(365/(D2-D1))-1`; `XIRR({-A,B},{D1,D2})`.

### 2.5 Time-weighted return (TWR), daily-linked

Use TWR for **manager/instrument skill**, independent of when the investor added money. It is the
basis of GIPS-compliant performance (CFA Institute GIPS 2020 requires valuation at least monthly
and on the date of any large external cash flow; **VERIFIED (secondary)**). With daily NAVs we
value every business day, so external-flow timing is exact.

Sub-period return with flow `F_t` (positive = contribution) assumed at **end of day t** (after
valuation; MF units are allotted at the day's NAV):

`r_t = (V_t^pre) / V_{t−1}^post − 1`, where `V_t^post = V_t^pre + F_t`
`TWR = Π (1 + r_t) − 1`

For a single MF holding, TWR is `NAV_end/NAV_start × IDCW factor − 1`, independent of flows.

Fixture TWR-1:

| Day | V_pre | Flow | V_post | r_t |
|---|---|---|---|---|
| 0 | — | +10,000 | 10,000 | — |
| 1 | 10,500 | +5,000 | 15,500 | +5.0000 % |
| 2 | 14,725 | 0 | 14,725 | −5.0000 % |

`TWR = 1.05 × 0.95 − 1 = −0.2500 %`.

Fixture TWR-2 (contrast with MWR, see 2.6): invest 10,000 on 2024-01-01. The fund returns +50 %, so
the holding is 15,000. Add 30,000 on 2025-01-01, making 45,000. The fund then returns −20 %, ending
at 36,000 on 2026-01-01. `TWR = 1.5 × 0.8 − 1 = +20.0000 %`.

Edge cases: `V_{t−1}^post = 0` (full exit then re-entry) restarts the chain; the period is excluded
and flagged. A negative value is impossible for long-only holdings and raises `InvalidInput`.
Oracle: GIPS-style chain-linking. The Modified Dietz approximation must agree within 1 bp when
flows are small.

### 2.6 Money-weighted return (MWR) / IRR / XIRR

MWR is the **investor's own** experience, including the timing of their flows. Show MWR for "your
portfolio" and TWR for "the fund".

`XNPV(r) = Σ_i CF_i / (1 + r)^((d_i − d_0)/365) = 0`, where `d_0` is the **earliest** date.

Sign convention: an investment is negative and a receipt or current value is positive. This is
Excel `XIRR` semantics; the day basis is Actual/365.

**Algorithm (deterministic):**
1. Validate the flows. There must be at least 2. There must be at least one CF < 0 and one CF > 0;
   otherwise return `NO_SOLUTION`. All dates must be valid. Same-date flows are netted. Sort by date.
2. Count sign changes in the date-ordered CF sequence. If there is exactly 1 sign change, Descartes'
   rule guarantees at most one root with `r > −1`.
3. Scan the grid `[-0.99, -0.9, -0.75, -0.5, -0.25, -0.1, 0, 0.05, 0.1, 0.2, 0.35, 0.5, 0.75, 1, 2, 5, 10]`.
   Evaluate XNPV at each point and record the brackets where the sign changes.
   * 0 brackets: `NO_SOLUTION` (or the root is above 1000 %). Report "IRR not meaningful".
   * More than 1 bracket: `MULTIPLE_ROOTS`. Solve every bracket and return all the roots. **Do not
     headline an IRR**; fall back to TWR + absolute ₹ P&L.
   * Exactly 1 bracket: solve.
4. Solve with Brent's method (`scipy.optimize.brentq`, `xtol=1e-12`, `maxiter=200`) in float64.
   An acceptable alternative is safeguarded Newton (Newton step; bisect if the step leaves the
   bracket). Excel uses Newton from guess 0.1 and returns `#NUM!` after 100 iterations, so Excel
   can fail where we succeed.
5. **Decimal verification:** recompute XNPV in Decimal at the root. Accept if
   `|XNPV| ≤ 1e-9 × Σ|CF_i|`. Otherwise raise `NumericalError`.
6. Quantize the output to 0.0001 % for storage and to 0.01 % for display (HALF_EVEN).
7. If the total span is under 365 days, XIRR is an annualised extrapolation. Rule A1 applies:
   headline the absolute ₹ gain and show XIRR only in a details panel with the warning "annualised
   from N days".

Fixtures (oracle: brentq, cross-checked against Excel semantics):

| # | Cash flows | XIRR | Note |
|---|---|---|---|
| X-1 | 2025-01-01: −10,000; 2026-01-01: +11,000 | **10.0000 %** | 365 days |
| X-2 | 2024-01-01: −10,000; 2025-01-01: +11,000 | **9.9714 %** | 366 days (leap): `1.1^(365/366) − 1` |
| X-3 (SIP) | 2025-01-10 −5,000; 2025-02-10 −5,000; 2025-03-10 −5,000; 2025-04-10 −5,000; 2025-10-10 +21,500 | **12.2645 %** | t = 0, 31, 59, 90, 273 days. Span < 1 y, so it is a details-only figure |
| X-4 | 2024-02-29 −10,000; 2025-02-28 +500; 2026-02-28 +10,500 | **5.0000 %** | 29-Feb start: 365 and 730 days, so t = 1, 2 exactly |
| X-5 | 2025-01-01 −100; 2026-01-01 +230; 2027-01-01 −132 | roots **10 % and 20 %** | XNPV(0.15) = +0.189 > 0, while XNPV(0.05) and XNPV(0.25) < 0. Expect `MULTIPLE_ROOTS` |
| X-6 | +100, +200 (no outflow) | `NO_SOLUTION` | |
| X-7 (TWR-2 flows) | 2024-01-01 −10,000; 2025-01-01 −30,000; 2026-01-01 +36,000 | **−8.1282 %** | TWR was +20 %. Shows why both are shown |

Note on X-7: with annual periods, a plain IRR gives −8.1323 %. XIRR differs because 2024 has 366
days. Tests must use XIRR semantics.

### 2.7 Total return with distributions (IDCW)

AMFI publishes Growth and IDCW option NAVs separately; see `docs/data/probes/README.md` and the synthetic `backend/tests/fixtures/data/amfi_navall_excerpt.txt`. An
IDCW NAV **drops** by the distribution on the ex-date.
* Growth option: the price return is the total return.
* IDCW option: reinvest the distribution at the ex-date NAV:
  `factor_t = 1 + D_t / NAV_ex,t`, and `TR = (NAV_end / NAV_start) × Π factor_t − 1`.

Fixture TR-1: NAV_start 11.60; on the ex-date the distribution is ₹0.50/unit with ex-NAV 11.52;
NAV_end 11.80.
`factor = 1 + 0.50/11.52 = 1.0434028`. `TR = (11.80/11.60) × 1.0434028 − 1 = 1.0172414 × 1.0434028 − 1 = 6.1392 %`.
The price-only figure 1.7241 % is wrong and must never be shown as "return".

Data needed: an IDCW record-date and amount feed. AMFI's NAV files do not carry it. If the feed is
missing, IDCW-option returns are **not computed** (`MissingDistributionData`); never fall back to
price-only. Prefer the Growth option of the same scheme for analytics.

After-tax IDCW: distributions are taxed at slab in the investor's hands, and TDS applies above a
threshold. For after-tax TR, reinvest `D_t × (1 − τ)`.

### 2.8 Gross vs net; expense ratio (TER / Base Expense Ratio)

Terminology: from 1-Apr-2026 the SEBI (Mutual Funds) Regulations 2026 replace "TER" with the
**Base Expense Ratio (BER)**, reg. 66(7). BER **excludes** statutory levies (GST, STT, stamp duty)
and brokerage/transaction costs, which are charged separately within limits. BER therefore cannot be
compared like-for-like with historical TER. Source: Agent B, `docs/research/indian-instruments-and-tax.md`
(VERIFIED-PRIMARY there; not re-fetched by Agent C). The engine stores
`expense_ratio_kind ∈ {TER, BER}` together with an `as_of` date. In the forward model it uses
`BER + estimated levies/brokerage` (labelled as an estimate) whenever kind = BER. In the rest of this
section, "TER" means whichever expense ratio applies on the date.

**A published NAV is already net of all scheme expenses (TER/BER and the separately charged levies).**
Scheme expenses are accrued daily in the NAV. Therefore:
* Historical NAV-based returns are **net**. Subtracting TER again is a **double count bug**. Add a
  test that asserts no TER term appears in any NAV-return code path.
* TER is used only (a) to explain the Regular vs Direct plan gap, and (b) in **forward models** that
  start from a gross quantity, for example the yield-carry model where expected return ≈ portfolio
  YTM − TER.

The daily accrual approximation for the forward model, with a constant gross daily factor:
`net_factor = gross_factor × (1 − TER/365)^365`.

Fixture TER-1: gross 8.00 %, TER 1.00 %:
`(1 − 0.01/365)^365 = 0.9900497`, so `net = 1.08 × 0.9900497 − 1 = 6.9254 %`. This is *not*
7.00 %: the TER is charged on the grown asset base. The model uses this compounding form.
The exact accrual basis (calendar days vs business days, net assets of the previous day) is
**NOT VERIFIED**. The error is under 1 bp a year.

### 2.9 Exit load

`load = L × units_redeemed × NAV_redemption` for each lot still inside its load window. Lots are
consumed **FIFO**, as AMCs do. The load window is per the scheme's SID; store it as
`{days, rate}[]` (for example 1 % if redeemed ≤ 365 days). Loads go back to the scheme. They are
not a tax.

Fixture EL-1: 1,000 units at NAV 25.4321, inside a 1 % window.
Gross = 25,432.10; load = 254.321 → **₹254.32**; net = **₹25,177.78** (HALF_UP, replication).

Fixture EL-2: the same, redeemed on day 366 with a "≤ 365 days" window. Load = 0. The boundary
convention (whether the purchase day counts as day 0 or day 1) is scheme-specific and
**NOT VERIFIED**. Default: `days_held = redemption_date − allotment_date`, and the load applies if
`days_held ≤ window_days`. Test both sides of the boundary.

Fixture EL-3: two lots: 600 units bought 400 days ago and 400 units bought 100 days ago. Redeem
700 units at 25.4321. FIFO takes 600 (no load) and 100 (load). Load = 0.01 × 100 × 25.4321 =
25.4321, so **₹25.43**.

### 2.10 Stamp duty on MF purchases (0.005 %)

Since 1 July 2020, stamp duty of 0.005 % applies on unit creation: purchases, SIPs, switch-ins and
IDCW reinvestment. The rate is 0.015 % on transfers, and there is none on redemptions.
**VERIFIED (secondary)**: HDFC MF, LIC MF and ABSL MF FAQs, citing Finance Act 2019 / Ministry of
Finance notification of 30 Mar 2020.

The formula follows AMC practice, so duty is on the amount that actually buys units:
`net = gross − transaction_charge`
`stamp = net × 0.005 / 100.005` (quantize to paise, HALF_UP replication)
`invested = net − stamp`; `units = invested / NAV_allot` (3 dp)

| # | Net amount | Stamp duty | Invested | Source check |
|---|---|---|---|---|
| SD-1 | 50,000 | 2.4998750 → **2.50** | 49,997.50 | — |
| SD-2 | 49,900 (50,000 − ₹100 txn charge) | 2.4948753 → **2.49** | **49,897.51** | matches the ABSL MF worked example |
| SD-3 | 1,00,000 | 4.9997500 → **5.00** | 99,995.00 | matches HDFC MF FAQ (`(100100−100)×0.005/100.005 = 5.00`) |
| SD-4 | 1,00,00,000 | 499.97500 → **499.98** | 99,99,500.02 | matches FAQ "₹499.98" |

Units for SD-1 at NAV 25.4321: `49,997.50 / 25.4321 = 1965.921021…`, giving **1965.921** units.

### 2.11 Inflation-adjusted (real) return — Fisher

`r_real = (1 + r_nom) / (1 + π) − 1`. Never use `r_nom − π` except as a labelled approximation.
π must be **horizon-matched**: the CPI-Combined (MoSPI) change over the same dates for history, or a
labelled projection for forward views.

| # | r_nom | π | r_real | Approx (r − π) |
|---|---|---|---|---|
| F-1 | 7.00 % | 5.00 % | **1.9048 %** | 2.00 % |
| F-2 | 6.50 % | 5.40 % | **1.0436 %** | 1.10 % |
| F-3 | 4.00 % | 6.00 % | **−1.8868 %** | −2.00 % (the real loss is shown in red) |

For horizons under 1 year, use the period π (not the annual π) together with the absolute period
return.

### 2.12 After-tax return (rule tables)

Tax logic is **data, not code**. The engine reads a versioned rule table keyed by
`(asset_class, acquisition_date, sale_date, holding_days, investor_regime)`. It returns the
classification (STCG / LTCG / slab) and the rate components (base rate, exemption threshold,
surcharge, 4 % Health & Education cess).

Requirements:
* Every rule row carries `effective_from`, `effective_to`, `source_citation`, `verified_on`. The
  engine refuses to compute after-tax figures for dates no row covers.
* Known regime breaks that the table must model. Rates are **NOT VERIFIED** here; they belong in
  the rule table with citations:
  * "Specified mutual funds" (≤ 35 % domestic equity) acquired on or after 1-Apr-2023 are taxed at
    slab irrespective of holding period.
  * Equity rates changed for transfers on or after 23-Jul-2024 (Finance (No. 2) Act 2024).
  * **The Income-tax Act 2025 is in force from 1-Apr-2026** and replaces the 1961 Act for income
    arising on or after that date. Rule rows are keyed by `effective_from` (the income/transfer
    date), and each row cites **both** section numbers. Examples: 111A → **196** (equity STCG),
    112 → **197**, 112A → **198** (equity LTCG), 115BAC → 202 (new regime), 87A → 156 (rebate).
    The mapping and its verification status come from Agent B, `docs/research/indian-instruments-and-tax.md`
    (FB2026 memorandum cites ss. 196/197/198 as VERIFIED-PRIMARY there). Agent C did not
    independently re-verify it. A transfer on 31-Mar-2026 uses the 1961-Act row; one on
    1-Apr-2026 uses the 2025-Act row. Test both sides of that date.
  * The canonical rule table lives in the research doc above. This document only specifies how the
    engine applies it.
* FD interest, T-bill discount and G-sec coupons are taxed at slab. FD interest is taxed **on
  accrual every year**, even for cumulative FDs, which creates a tax drag on compounding.
* Users supply their marginal slab. The app never infers income.

Fixture TAX-1 uses a **fictional** rate (examples must never carry real user values): gain ₹10,000,
fictional base rate 20 %, cess 4 %. Effective rate = 20 % × 1.04 = 20.8 %. Tax = ₹2,080.00, so the
after-tax gain is ₹7,920.00.

Fixture TAX-2, FD tax drag (fictional 30 % + 4 % cess = 31.2 %): ₹1,00,000 at 7 % quarterly for 2
years. Pre-tax maturity is ₹1,14,888.18. Year-1 accrued interest of ₹7,185.90 is taxed at 31.2 %,
which is ₹2,242.00 paid out of pocket. Report post-tax as `maturity − Σ tax_on_accrual_y`. The
engine computes the post-tax CAGR from the dated tax flows by XIRR.

---

## 3. Fixed deposits (Indian banks)

### 3.1 Conventions

| Item | Convention | Status |
|---|---|---|
| Compounding | Quarterly rests for reinvestment (cumulative) deposits: `A = P(1 + r/4)^(4t)` | **VERIFIED (secondary)**: IBA publishes "Reinvestment Plan Deposits — Maturity Value (Quarterly Compounding)" tables; Indian Bank's FD terms |
| Short tenures | Simple interest at maturity below a bank-specific threshold. Indian Bank: < 6 months. AU SFB: < 3 months. IBA Code: "repayable in less than three months or where the terminal quarter is incomplete … actual number of days on the basis of 365 days" | **VERIFIED (secondary)**. Threshold is a **per-bank parameter**, `simple_below_months`, default **6** |
| Broken period | Compound complete quarters, then simple interest on the compounded balance for the remaining days, Actual/365 | **VERIFIED (secondary)** (AU SFB basis note; IBA rule). The quarter anchor (deposit-date quarters vs calendar quarters) is **NOT VERIFIED**. Default: 3-calendar-month steps from the deposit date (EDATE) |
| Leap years | Fixed 365 denominator | IBA text says 365. Some banks use 366 in leap years: **NOT VERIFIED**; parameter `leap_denominator` |
| Payout (non-cumulative) | Quarterly payout = `P × r/4`. Monthly = the quarterly amount **discounted** | **VERIFIED (secondary)** (IBA). Monthly discount formula **NOT VERIFIED**; use the bank table if available |
| Minimum tenure | 7 days | common practice; per-bank |

### 3.2 Formulas

* `months ≥ simple_below_months`: let `q` = number of complete quarters (EDATE steps not past
  maturity) and `b` = remaining days.
  `A = P(1 + r/4)^q × (1 + r × b/365)`.
* Otherwise: `A = P × (1 + r × days/365)`.
* Effective annual yield: `EAY = (1 + r/4)^4 − 1`.
* Quantize to paise, HALF_UP (replication), **only at maturity**. Interim quarters are not
  quantized. Some core-banking systems round each quarter's interest; this is **NOT VERIFIED**. The
  expected difference is under ₹0.05 per ₹1 lakh, and the test tolerance is ₹0.05.

| # | P | Rate | Dates / tenure | Computation | Maturity |
|---|---|---|---|---|---|
| FD-1 | 1,00,000 | 7.00 % | 1 year (4 quarters) | 1.0175^4 = 1.071859031 | **1,07,185.90**; EAY 7.1859 % |
| FD-2 | 1,00,000 | 7.00 % | 2 years | 1.0175^8 | **1,14,888.18** |
| FD-3 | 1,00,000 | 7.00 % | 90 days (< 6 m) | 1,00,000 × 0.07 × 90/365 = 1,726.03 | **1,01,726.03** |
| FD-4 | 1,00,000 | 7.00 % | 179 days (< 6 m) | ×179/365 = 3,432.88 | **1,03,432.88** |
| FD-5 | 1,00,000 | 7.00 % | 2025-10-15 → 2026-11-19 (400 days) | 4 quarters → 1,07,185.9031; + 1,07,185.9031 × 0.07 × 35/365 = 719.4670 | **1,07,905.37** |
| FD-6 (leap) | 1,00,000 | 7.00 % | 2027-10-15 → 2028-11-19 (401 days; contains 29-Feb-2028) | identical to FD-5 under the 365 convention | **1,07,905.37** |
| FD-7 | 1,00,000 | 7.50 % | 5 years (20 quarters) | 1.01875^20 | **1,44,994.80**; EAY 7.7136 % |

FD-6 is the leap-year edge case. Under a `leap_denominator=366` bank the broken-period interest
would be 717.50. The test asserts parameter sensitivity.

### 3.3 Premature withdrawal

Banks pay the rate applicable **for the period the deposit actually ran** (the card rate on the
booking date for that tenure) **minus a penalty**, typically 0.5–1.0 %. Penalty, waivers (for
example for senior citizens) and the "no interest if withdrawn before 7 days" rule are bank-board
policy under the RBI Master Direction on Interest Rate on Deposits. **NOT VERIFIED** per bank;
store as `premature_penalty_pct` per product.

`r_eff = max(0, card_rate(tenure_run) − penalty)`. Apply the §3.2 formula for the tenure actually
run. Some banks apply the lower of the booked rate and the period rate; parameter
`premature_rate_basis ∈ {period_card, min(booked, period_card)}`.

Fixture FD-P1: booked 2 years at 7.25 %, broken after exactly 1 year. The 1-year card rate on the
booking date is 6.80 % and the penalty is 1.00 %, so `r_eff = 5.80 %`.
`1,00,000 × 1.0145^4 = ₹1,05,927.37`. Had it been a 1-year deposit at the booked 7.25 % it would be
₹1,07,449.50. The ₹1,522.13 gap is the "cost of breaking" shown to the user.

### 3.4 Oracles

IBA Reinvestment Plan maturity tables; bank FD calculators (cross-check only; many web calculators
use annual compounding, so treat them with care); QuantLib `InterestRate(r, Actual365Fixed, Compounded, Quarterly)`.

---

## 4. Fixed income (T-bills, G-secs, SDLs, corporate bonds)

### 4.1 T-bills (91/182/364-day; discount instruments, face ₹100)

**VERIFIED**: RBI FAQ on G-Secs (FAQView Id=79), money-market convention Actual/365. The yield
formula `Y = (100 − P)/P × 365/D` is reproduced by Groww, Zerodha and Upstox examples.

* Price from yield: `P = 100 / (1 + y × D/365)`
* Yield from price: `y = (100 − P)/P × 365/D`
* D = days from **settlement** to maturity (T+1 settlement for auctions and secondary trades).
* Effective annual yield, for cross-instrument comparison only: `(100/P)^(365/D) − 1`.

Note: the project brief suggested `100/(1 + y·d/364)`. **That is incorrect for India.** 364 is a
tenor, not the day basis. Fixture TB-6 quantifies the error. Agent C verified this independently from
the RBI FAQ text ("Money market: … actual/365 … in the case of T-Bills … money market convention is
followed"), and Agent B's research doc reaches the same conclusion. **No source conflict.**

| # | Input | Computation | Result |
|---|---|---|---|
| TB-1 | 91 d, y = 6.50 % | 100 / (1 + 0.065 × 91/365) = 100/1.016205479 | **98.4053** |
| TB-2 | 182 d, y = 6.60 % | 100 / (1 + 0.066 × 182/365) | **96.8139** |
| TB-3 | 364 d, y = 6.70 % | 100 / (1 + 0.067 × 364/365) | **93.7368** |
| TB-4 | 182 d, P = 96.80 | (3.20/96.80) × 365/182 | **6.6297 %** |
| TB-5 | secondary: 41 d left, P = 99.25 | (0.75/99.25) × 365/41 | **6.7273 %** |
| TB-6 | TB-1 using a 364 basis (WRONG) | 100/(1 + 0.065 × 91/364) | 98.4010 (off by 0.0043 per ₹100) |
| TB-7 | Groww example: 91 d, P = 98 | (2/98) × 365/91 | 8.1857 % (Groww shows "8.19 %") |

Effective yield of TB-1 = 98.4053 → `(100/98.4053)^(365/91) − 1 = 6.6603 %`.
The ₹ outcome for ₹1,00,000 face is ₹98,405.30 invested and ₹1,00,000 received (gain ₹1,594.70
over 91 days, 1.6205 % absolute).

Edge: if the maturity date is a holiday, payment is made on the next business day without extra
discount. The holiday rule is **NOT VERIFIED**; use the RBI notification per issue.

### 4.2 G-secs and SDLs: coupon schedule and accrued interest

* Coupons are semi-annual at `C/2` per ₹100 on the fixed coupon dates stated in the issue
  notification. **VERIFIED**: RBI FAQ ("Frequency … 2 for Government bonds in India"). SDLs follow
  the same market conventions. **VERIFIED (secondary)**: FBIL SDL valuation methodology uses
  NDS-OM T+1 trades.
* Day count is **30E/360** (Excel basis 4). **VERIFIED**: RBI FAQ.
  `days30E(d1, d2) = 360(Y2−Y1) + 30(M2−M1) + (min(D2,30) − min(D1,30))`.
  February month-end is **not** adjusted (this differs from US 30/360 basis 0).
* Accrued interest runs from the last coupon date **up to the day prior to settlement**. Counted
  inclusively, this equals `days30E(last_coupon, settlement)`. **VERIFIED**: the RBI FAQ example
  below reconciles exactly.
  `AI = C × days30E(last_coupon, settlement) / 360` (per ₹100).
* Dirty price = clean price + AI. Consideration = face × dirty / 100.
* Settlement is **T+1**: NDS-OM and OTC since 24-May-2005, through CCIL as CCP. Friday trades settle
  Monday. **VERIFIED (secondary)**: NY Fed Staff Report 785; RBI primer.
* Shut period is **1 day** for securities in SGL accounts. No trading during the shut. **VERIFIED**:
  RBI FAQ. The record-date positioning relative to the coupon date is **NOT VERIFIED**. Default rule:
  the engine refuses trades whose settlement falls inside `[coupon_date − shut_days, coupon_date)`
  and treats the coupon as belonging to the holder at the start of the shut. There is no negative
  (ex-interest) accrued for G-secs in this model.

Fixtures:

| # | Case | Computation | Result |
|---|---|---|---|
| AI-1 (RBI FAQ) | 8.83 % 2023; last coupon 25-Nov-2013; settlement 30-Jan-2014; clean 100.50; face ₹5 crore | days30E = 360 + 30(1−11) + (30−25) = **65**; AI = 8.83 × 65/360 = **1.5943** | dirty **102.0943**; consideration **₹5,10,47,150** |
| AI-2 (month-end, non-leap) | last coupon 31-Aug-2025, settle 28-Feb-2026 | 360 + 30(2−8) + (28 − 30) = **178** (actual days 181) | AI@7.10 % = 3.5106 |
| AI-3 (month-end, leap) | 31-Aug-2027 → 29-Feb-2028 | 360 − 180 + (29 − 30) = **179** (actual 182) | |
| AI-4 (31st start) | 31-Jan-2028 → 01-Mar-2028 | 30(3−1) + (1 − 30) = **31** (actual 30!) | 30E can exceed actual |

Oracle: QuantLib `Thirty360(Thirty360.European)` (returns 65 / 178 / 179) and Excel
`ACCRINT(...,basis=4)`.

### 4.3 Price ↔ YTM (semi-annual, bond-equivalent)

The YTM is the nominal annual rate `y`, compounded semi-annually. It solves the RBI/Excel `PRICE`
formula with basis 4 and frequency 2. With `f = 2`, `E = 180` (days in the coupon period under 30E),
`A = days30E(prev, settle)`, `DSC = days30E(settle, next) = E − A`, `N` = remaining coupons and
`w = DSC/E`:

`Dirty = Σ_{k=1..N} (C/f) / (1+y/f)^(k−1+w) + 100 / (1+y/f)^(N−1+w)`
`Clean = Dirty − (C/f) × A/E`

* YTM from price: Brent's method on `Clean(y) − P_quote` with bracket `[−0.5, 1.0]`. There is a
  unique root for plain bullets because the function is monotone. Then verify in Decimal (tolerance
  1e-10 per ₹100).
* Effective annual yield: `(1 + y/2)^2 − 1`. 6.50 % gives 6.6056 %.
* Odd first/last coupons: out of scope for v1. Reject with `UnsupportedSchedule`.
* Floating-rate bonds (FRBs), STRIPS, inflation-indexed bonds: out of scope for v1.

| # | Bond | Input | Result | Oracle |
|---|---|---|---|---|
| Y-1 (RBI FAQ Box III) | 2-year, 8 % coupon, settle on coupon date | price 102.00 | **YTM 6.9121 %** | brentq |
| Y-2 (synthetic "7.10 % GS 2036") | coupon 15-Apr/15-Oct; maturity 15-Apr-2036; trade 15-Oct-2026, settle 16-Oct-2026 (T+1); N = 19, A = 1, DSC = 179 | YTM 6.50 % | clean **104.2024**, AI **0.0197**, dirty 104.2221 | QuantLib `FixedRateBond` + `BondFunctions.cleanPrice` (identical to 1e-12) |
| Y-3 (par check) | 3-year 8 %, settle on coupon date | YTM 8.00 % | price **100.0000** | identity |

### 4.4 Duration, convexity, price-change approximation

With `n_k = k − 1 + w` (periods to cash flow k), `t_k = n_k / f` (years) and `PV_k = CF_k / (1+y/f)^{n_k}`:
* Macaulay `D_mac = Σ t_k PV_k / Dirty` (years)
* Modified `D_mod = D_mac / (1 + y/f)`
* Convexity `Conv = (1/Dirty) × Σ CF_k × n_k (n_k+1) / (f² (1+y/f)^{n_k+2})` (years²)
* `ΔP/P ≈ −D_mod Δy + ½ Conv (Δy)²`. This uses the **dirty** price.
* DV01 per ₹100 = `D_mod × Dirty × 0.0001`.

Worked fixture D-1 (fully hand-computable): 3-year 8 % semi-annual bond at YTM 8 %, price 100,
period rate 4 %.

| k | t (yrs) | CF | DF = 1.04^−k | PV | t × PV |
|---|---|---|---|---|---|
| 1 | 0.5 | 4 | 0.961538 | 3.846154 | 1.923077 |
| 2 | 1.0 | 4 | 0.924556 | 3.698225 | 3.698225 |
| 3 | 1.5 | 4 | 0.888996 | 3.555985 | 5.333978 |
| 4 | 2.0 | 4 | 0.854804 | 3.419217 | 6.838434 |
| 5 | 2.5 | 4 | 0.821927 | 3.287708 | 8.219271 |
| 6 | 3.0 | 104 | 0.790315 | 82.192711 | 246.578132 |
| Σ | | | | **100.000000** | **272.591117** |

`D_mac = 2.7259` years; `D_mod = 2.7259/1.04 = 2.6211`; `Conv = 8.5329`.
At +100 bp the exact price at 9 % is 97.4211 (−2.5789 %). The approximation gives
`−2.6211 × 0.01 + ½ × 8.5329 × 0.0001 = −2.5784 %` (error 0.5 bp).

Fixture D-2 (Y-2 bond): `D_mac = 7.1215`, `D_mod = 6.8973`, `Conv = 60.0072`. These match QuantLib
`BondFunctions.duration/convexity` to 1e-12.

| Shock | Exact ΔP/P | Duration + convexity | Duration only |
|---|---|---|---|
| +50 bp | −3.3749 % | −3.3737 % | −3.4487 % |
| −50 bp | +3.5249 % | +3.5237 % | +3.4487 % |
| +200 bp | **−12.6678 %** | −12.5946 % | −13.7947 % |

Rule: for |Δy| > 100 bp, scenarios use **full repricing**, not the approximation. The approximation
is shown only as an explanation.

### 4.5 Corporate bonds (listed, SEBI)

* Day count Actual/Actual. When 29 Feb falls inside a one-year period, the denominator is 366 for
  every coupon period in that year. **VERIFIED (secondary)**: SEBI circular 11-Nov-2016 and its
  worked example. Coupon-date holidays: pay on the next working day, with interest computed only to
  the scheduled date.
* Coupon frequency is per the term sheet; annual is common.
* Yield quoting convention: Indian corporate bond yields are commonly quoted on an annualised
  (annual compounding / XIRR-like) basis. **NOT VERIFIED**. The engine stores every yield with an
  explicit `compounding ∈ {annual, semiannual, quarterly, monthly}` tag. Cross-instrument
  comparisons always convert to the effective annual yield.

Fixture CB-1 (SEBI example), 8 % semi-annual, issued 1-Jan-2016:
Jan 1 → Jul 1 2016 is 182 days, giving 8 × 182/366 = **3.9781**; Jul 1 2016 → Jan 1 2017 is 184
days, giving **4.0219**. The total is 8.0000.
Fixture CB-2 (non-leap 2025): 181/365 × 8 = **3.9671**; 184/365 × 8 = **4.0329**.

### 4.6 Yield-to-call and yield-to-worst

YTC solves the price equation with the call date as maturity and the call price as redemption.
YTW = min(YTM, YTC over all call dates). Show YTW as the headline for callable bonds.

Fixture YC-1: 9 % annual coupon, 5 years to maturity, callable at par in 2 years, price 102.50
(settle on a coupon date).
YTM = **8.3678 %**; YTC = **7.6057 %**; YTW = 7.6057 %. The issuer will call when rates fall, so YTM
overstates the likely return.

### 4.7 Credit spread sensitivity (spread duration)

`y_corp = y_gsec(T) + s`. For a fixed-rate bullet, spread duration ≈ modified duration:
`ΔP/P ≈ −D_spread × Δs`.

Fixture SP-1: 5-year 9 % annual-coupon bond at yield 8 % (G-sec 6.5 % + spread 1.5 %).
Price 103.9927; `D_mac = 4.2559`; `D_mod = 3.9406`. Spread +100 bp gives exact price 100.0000
(−3.8394 %) against the approximation −3.9406 %.
Spread scenarios are separate from rate scenarios. They are combined additively in Δy, and the
result is fully repriced.

### 4.8 Reinvestment assumption and realised return

YTM assumes coupons are reinvested at YTM. Realised (horizon) return is computed explicitly:
`FV = Σ coupon_k × (1 + r_reinv/f)^(remaining periods) + redemption`.

Fixture RR-1: 3-year 8 % semi-annual bought at par (YTM 8 %), coupons reinvested at 6 % (3 % per
half-year): FV = 125.8736. Realised effective annual return = **7.9721 %** (bond-equivalent 7.8193 %).
The YTM of 8 % is not achieved.

### 4.9 Maturity proceeds and early-exit price scenarios

Hold to maturity: proceeds = face + final coupon (G-sec/corporate), or face (T-bill). These are
known amounts. Credit risk is the only uncertainty for corporates.

Early exit at horizon H < maturity: the price at H is unknown. Reprice the residual bond on a yield
grid `y_H ∈ {y_0 − 100bp, −50, 0, +50, +100, +200}` (plus spread shocks for corporates).
`HPR = (P_H + coupons received (+ reinvestment) − P_0) / P_0`.

Fixture EE-1: 3-year 8 % bought at par. Exit after 1 year (2 coupons of 4 received, not reinvested):
* Yields → 9 %: P_H = 98.2062, so HPR = (98.2062 + 8 − 100)/100 = **6.2062 %**
* Yields → 7 %: P_H = 101.8365, so HPR = **9.8365 %**
* Yields unchanged: HPR = **8.00 %**

Liquidity haircut: retail exit via the stock-exchange odd-lot segment may cost a bid-ask spread.
This is **NOT VERIFIED**. Parameter `exit_spread_bp`, default 25 bp for G-secs and 100 bp for
corporates, shown as an assumption.

---

## 5. Implementation checklist per formula (summary)

| Formula | Module fn | Oracle | Tolerance |
|---|---|---|---|
| CAGR | `returns.cagr` | Excel / XIRR | 1e-10 |
| TWR | `returns.twr` | hand chain | exact (Decimal) |
| XIRR | `returns.xirr` | Excel XIRR, brentq | 1e-8 rate |
| IDCW TR | `returns.total_return` | hand | 1e-10 |
| Stamp duty | `costs.stamp_duty` | AMC FAQ examples | exact paise |
| Exit load | `costs.exit_load` | hand | exact paise |
| FD maturity | `fd.maturity` | IBA tables, QuantLib | ₹0.05 |
| T-bill | `fi.tbill_price/yield` | RBI formula | 1e-10 |
| AI 30E/360 | `fi.accrued` | RBI FAQ, QuantLib | 1e-4 |
| Price/YTM | `fi.price/ytm` | QuantLib, Excel PRICE/YIELD basis 4 | 1e-8 price |
| Duration/convexity | `fi.risk` | QuantLib BondFunctions | 1e-8 |
| YTC/YTW | `fi.ytc` | brentq | 1e-8 |

Property-based tests (Hypothesis): price(ytm(P)) == P; XIRR of the flows generated at rate r
returns r; CAGR of `V × (1+r)^(d/365)` returns r; duration > 0; Clean + AI == Dirty.

---

## 6. Red-team checklist — how these formulas could mislead the user

1. **Quoted YTM ≠ realised return.** YTM assumes hold-to-maturity, no default and reinvestment at
   YTM (RR-1: 8 % → 7.97 %). Debt-fund "portfolio YTM" also ignores TER, duration drift and
   portfolio turnover.
2. **Annualising a 7-day return** (A-1) turns 0.10 % into "5.35 %". This is forbidden as a headline.
3. **CAGR on integer years** (CAGR-2/3) overstates by about 1–2 bp per leap day. Always use days.
4. **XIRR for short spans** is extreme. A 10 % gain in 30 days reads as "219 %".
5. **XIRR with multiple roots** (X-5): any single number is arbitrary. Refuse it.
6. **TWR vs MWR divergence** (+20 % vs −8.13 %): the fund did well while the investor lost money.
   Show both, with labels.
7. **Double-counting TER** on NAV returns understates returns by about the TER every year. A related
   trap: comparing a post-2026 **BER** with a pre-2026 **TER** understates the new cost, because
   BER excludes levies.
8. **Price-only return on IDCW options** understates the total return (1.72 % vs 6.14 %).
9. **Comparing an FD card rate (nominal, quarterly) to a T-bill yield (Act/365 simple) to a G-sec
   YTM (semi-annual)** without converting to the effective annual rate or ₹ outcome misranks them by
   up to ~20 bp.
10. **Using 364 instead of 365 for T-bills** misprices them (TB-6).
11. **US 30/360 instead of 30E/360** gives wrong accrued interest around February month-ends.
12. **Duration-only approximation** for big shocks overstates the loss: +200 bp gives −13.79 % vs
    −12.67 % exact.
13. **YTM on a callable bond** overstates the yield (8.37 % vs YTW 7.61 %).
14. **Credit events** cause jump losses that no duration or spread-duration math captures. A downgrade
    or default is a scenario, not a sensitivity.
15. **Ignoring tax-on-accrual for FDs** overstates the cumulative-FD after-tax CAGR.
16. **Ignoring exit loads and early-exit price risk** when the user's horizon is shorter than the
    load window or the bond's maturity.
17. **Nominal vs real**: a 6.5 % FD with 6 % inflation is roughly 0.5 % real, and negative after tax.
18. **Premature FD penalty** applies to the *lower* period rate, not the booked rate. Users expect
    "booked rate − 1 %".
19. **Stale price lookup**: forward-filling the NAV across a long gap fakes zero volatility. `StaleData`
    guards this.

## Sources

* RBI, FAQs on Government Securities (FAQView Id=79): day count, T-bill convention, accrued interest
  example, shut period, Excel YIELD basis 4. https://www.rbi.org.in/Scripts/FAQView.aspx?Id=79
* RBI, Government Securities Market — A Primer (hosted by FIMMDA).
  https://fimmda.org/uploads/general/Government_Securities_Market_in_India_A_Primer.PDF
* NY Fed Staff Report 785, Trading Activity in the Indian Government Bond Market (T+1 since 2005).
  https://pages.stern.nyu.edu/~jcarpen0/Chinaluncheon/sr785.pdf
* FBIL SDL Valuation Methodology v4 (Oct 2024).
  https://www.fbil.org.in/uploads/FBIL_SDL_Valuation_Methodology_Version_4_29_Oct2024_56e37a0921.pdf
* SEBI circular CIR/IMD/DF-1/122/2016, day count convention for debt securities (summary).
  https://taxguru.in/sebi/day-count-convention-for-debt-securities-issued-sebi-listing-regulations-2008.html
* SEBI Master Circular on MF advertisements (via HDFC MF).
  https://files.hdfcfund.com/s3fs-public/2025-07/SEBI's%20Master%20Circular%20on%20Advertisements%20for%20Mutual%20Funds.pdf
* SEBI Guidelines for Advertisement by MFs (2000). https://www.sebi.gov.in/sebi_data/commondocs/cirmf42000_h.html
* Stamp duty FAQs: HDFC MF https://files.hdfcfund.com/s3fs-public/2020-07/FAQs%20on%20Stamp%20Duty.pdf ;
  LIC MF https://www.licmf.com/assets/pdfs/FAQs-on-Stamp-Duty-on-Mutual-Fund-Units.pdf ;
  ABSL MF https://mutualfund.adityabirlacapital.com/-/media/BSL/Files/Documents/Stamp-Duty-Charges
* IBA, Reinvestment Plan Deposits — Maturity Value (Quarterly Compounding). https://www.iba.org.in/others/chart-5.html
* AU SFB, Basis for interest calculation on term deposits.
  https://www.au.bank.in/notice-board-language/basis-for-interest-calculation-on-term-deposits/English.pdf
* IIT Bombay, Rate of interest on term deposits (summary of the IBA Code).
  http://www.math.iitb.ac.in/~ashish/workshop/interestf-r4(01-08-02).pdf
* T-bill yield examples: Zerodha Varsity https://zerodha.com/varsity/chapter/government-securities/ ;
  Groww https://groww.in/p/treasury-bills ; Upstox (article 179321).
* CFA Institute, GIPS 2020 (time-weighted returns, valuation at large cash flows). Not re-fetched
  in this session: **VERIFIED (secondary)** from prior knowledge.
* Oracles: QuantLib 1.44 (`FixedRateBond`, `Thirty360.European`, `BondFunctions`), SciPy 1.17
  `brentq`, Microsoft Excel `XIRR`/`PRICE`/`YIELD`/`ACCRINT`.
