# ADR-0003: Deterministic supervisor and evidence contracts

## Context
User directive (2026-10-15): "supervisor approach to make sure every context is gathered … deterministic … no hallucination as there is real money."
The repositories the user suggested (ai-hedge-fund, ai-hedge-fund-india, india-trade-cli, daily_stock_analysis) all let an LLM emit numeric signals, confidence values or quantities. This is rejected (github-reference-review.md §5).

## Decision
1. The **Supervisor** is ordinary Python code. It has a registry of `QuestionType → ContextManifest`.
2. A **ContextManifest** lists `ContextItem`s: `{id, kind, required, freshness_rule, acceptable_sources, validator}`.
3. **Workers** are deterministic Python modules: MarketData, MutualFund, FixedIncome, Macro, Quant, PortfolioRisk, ForecastValidation, Skeptic and Compliance. Each returns a versioned **WorkerContract**:
   - `status ∈ {answered, abstained}`, plus `abstain_reason`;
   - `claims[]`, each with `{text_template, cites[metric_id|observation_id]}`;
   - `evidence[]`, each with `{source_id, url, observation_date, retrieved_at}`;
   - `gaps[]`, `conflicts[]`, `limitations[]` and `requested_calculations[]`.
   Claims carry **no free numeric fields**. Numbers are referenced by ID only.
4. **Completeness gate:** if any required item is missing, stale, provenance-incomplete or fails validation, the result is `ABSTAIN` with an itemised list of what is missing. The gate never fills gaps with defaults or interpolation.
5. **Conflict detection** is deterministic: rules compare worker claims, for example a rating downgrade against an "AAA" category assumption. Conflicts are displayed and never resolved into a score.
6. **Synthesis** renders templates from the claims. The optional LLM (ADR-0007) may only rephrase. Its output passes a numeric validator: every digit sequence in it must equal a cited value's display string, otherwise the template is used.
7. **RunRecord** stores the manifest version, contracts, engine versions, input-snapshot hash, output hash and timestamps. Replaying the run must reproduce the output hash.

## Consequences
- More code than an LLM agent graph, but every output is auditable and reproducible.
- "ABSTAIN" and "No suitable candidate found" are first-class UI states.

## Evidence
reference-selection.md §5.1; requirements.md §3.6a; threat-model.md (SEC-70, SEC-71).
