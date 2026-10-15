# ADR-0005: Ranking without a composite score

## Decision
The pipeline has four steps, versioned as `ranking_policy@1.0.0`:
1. **Hard eligibility:**
   - Horizon fit: maturity, lock-in and exit load fit inside the horizon.
   - Capital-preservation constraint: for the preservation objective, the instrument's certainty tier must be ≤ T2, **or** its historical frequency of loss at this horizon must be within the user's loss budget, with sufficient data.
   - Liquidity: days-to-cash and exit cost.
   - Credit floor.
   - Data sufficiency and freshness.
   - Exclusions set by the user.
   Each rejection records its reason code.
2. **Comparable outcomes:** for the same amount and horizon, compute a rupee outcome band (p5 / p50 / p95 where it is defined, or a contractual amount) **after costs and assumed tax**.
3. **Certainty tiers:**
   - T1: contractual, sovereign, held to maturity.
   - T2: contractual, insured deposit within the DICGC limit.
   - T3: low-duration market-linked (overnight/liquid/money-market).
   - T4: other debt market-linked.
   - T5: equity, hybrid and gold.
4. **Ordering by objective:**
   - A (preservation): tier, then p5 outcome descending.
   - B (income): tier, then outcome dispersion, then median.
   - C (liquidity): days-to-cash, then exit cost, then p5.
   - D (growth): p5 subject to the loss budget, then median.
   - E (aggressive): median subject to the explicit loss budget, with drawdown shown.
- Ties are broken by data quality, then by instrument ID (deterministic).
- An empty eligible set returns **"No suitable candidate found under the current constraints."**
- Weights and policy are published in the Methodology page and attached to every result.

## Evidence
risk-methodology.md (ranking guidance; worked example excluding equity for a 1-month preservation goal).
