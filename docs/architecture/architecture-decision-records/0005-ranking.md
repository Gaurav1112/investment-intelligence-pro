# ADR-0005: Ranking without a composite score

## Decision
The pipeline has four steps, versioned as `ranking_policy@1.0.0` (revised 2026-10-15 to match risk-methodology.md §9 exactly: four tiers, ε = 1 %, x = 0 %):
1. **Hard eligibility** (each check is a boolean with a reason code; risk-methodology.md §9 Step 1):
   - Horizon fit: maturity, lock-in and exit-load window fit inside H, or a modelled early exit is available.
   - Capital preservation (objectives A, B, C): historical loss frequency at H ≤ ε (default **1 %**) **and** q05 ≥ −x (default
     **0 %**). A market-dependent candidate whose loss frequency is unknown fails (`MISSING_LOSS_EVIDENCE`). It is never assumed safe.
   - Liquidity: days-to-cash ≤ the user's need; exit cost ≤ the user's maximum.
   - Credit floor, minimum ticket size, user exclusions, data sufficiency and freshness.
   - Objectives D and E require q05 ≥ −L, where L is the user-entered loss budget. Objective E **requires** L (otherwise ABSTAIN).
2. **Horizon-matched ₹ outcome bands** after costs and assumed tax (contractual = point; market = q05/q50/q95).
3. **Certainty tiers** (spec §9 Step 3):
   - T1 contractual sovereign (T-bill, G-sec held to maturity);
   - T2 contractual non-sovereign (FD within DICGC, AAA bond held to maturity);
   - T3 market-dependent, bounded (overnight/liquid/money-market funds; bonds with an early exit);
   - T4 market-dependent, unbounded (duration/credit funds, hybrid, equity, gold).
4. **Lexicographic ordering by objective:**
   - A (preservation): tier ↑, then q05 ↓, then days-to-cash ↑, then cost ↑. A higher median never compensates for a worse lower band.
   - B (income/maturity): tier ↑, then band width (q95 − q05) ↑, then q50 ↓.
   - C (liquidity): days-to-cash ↑, then exit cost ↑, then q05 ↓.
   - D/E (growth): certainty-equivalent `CE = q50 − λ(q50 − q05)` ↓ (λ from the user, default 0.5), then tier ↑.
- Ties are broken by data quality, then by instrument ID (deterministic).
- An empty eligible set returns **"No suitable candidate found under the current constraints."**
- Weights and policy are published in the Methodology page and attached to every result.

## Evidence
risk-methodology.md (ranking guidance; worked example excluding equity for a 1-month preservation goal).


## Amendment — ranking_policy@1.1.0 (2026-10-15, user decisions after the red-team audit)
- **Evidence gate for capital preservation (RT-19).** Under objectives A, B and C, a market-linked option needs at least **20 independent
  windows** at the horizon (`INSUFFICIENT_LOSS_EVIDENCE` otherwise). Zero losses in fewer windows cannot establish a low loss
  rate (rule of three). Contractual options are unaffected.
- **Growth objectives need H ≥ 12 months (RT-20).** D and E are refused below 365 days, in the engine (`InvalidInput`) and in the
  profile (stays in EXPLORATION with an explanation).
- **Uninsured credit exposure (red team RT-01).** Contractual options outside T1/T2 fail preservation objectives
  (`UNINSURED_CREDIT_EXPOSURE`), because the DICGC limit is a hard constraint (risk-methodology §9).

## Amendment — ranking_policy@1.2.0 (2026-10-15, red-team RT-23)
- **Credit floor for debt-holding funds.** A fund that holds debt (every debt, liquid, money-market, overnight and gilt
  scheme, and every hybrid) is checked against the user's credit floor by the **lowest rating it holds**, taken from its
  latest factsheet (user-entered with a citation, `fund_facts`), provided the factsheet is **no more than 45 days old**
  (risk-methodology §8) and not dated after the analysis date.
- **Unknown is never assumed safe.** When the user sets a credit floor and such a fund has no factsheet, a stale one,
  no "lowest rating held", or a lowest rating that is not on the long-term scale (short-term ratings such as A1+ have no
  agreed long-term equivalent in this app), it is excluded with the new reason code **`CREDIT_QUALITY_UNKNOWN`**. With
  no credit floor set, nothing changes.
- Credit Risk Funds without a usable factsheet keep the 1.1.0 rule (treated as `UNRATED`, so any floor excludes them);
  with one, their lowest rating held is used. Equity schemes are unaffected.
- Engine: `Candidate.credit_quality_unknown`, `candidates.fund_credit_status`; the unknown check runs before the rating
  comparison, so an unknown-quality fund fails even the lowest floor.
