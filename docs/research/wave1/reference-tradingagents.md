# Reference review: TauricResearch/TradingAgents

- **Repo:** https://github.com/TauricResearch/TradingAgents (Apache-2.0, ~111k stars, last push 2026-10-03).
  Read via the GitHub API on 2026-10-16. The user suggested it.
- **Verdict:** ideas only. No code or dependency adopted.

## What it is

A LangGraph multi-agent framework. LLM agents reach a rating together:

1. Fundamentals, sentiment, news and technical analysts.
2. A bull/bear researcher debate.
3. A trader.
4. Risk debaters.
5. A portfolio manager.

The README says it is "designed for research purposes".

## Not adoptable

| Item | Why |
|---|---|
| LLM-made ratings | ADR-0007: no LLM-produced numbers or decisions. The same inputs must give the same output. |
| Yahoo Finance data (incl. `.NS`/`.BO` tickers) | Its terms ban automated collection. Already rejected in `research-references.md`. |
| Alpha Vantage, StockTwits, Reddit, LLM provider keys | Paid or keyed APIs; no-paid-keys rule. |
| SEC EDGAR fundamentals | US filers only. |
| `backtest.py` | It scores ratings, not a portfolio. Its own docstring: "It is not a portfolio simulator". It has no costs, tax or lot ledger. B05 keeps its own design. |

## Grafts (to apply after the wave-2 integration, as a follow-up)

| G | Idea | Where in IIP |
|---|---|---|
| TA-1 | **Resolution date on every outcome.** An `as_of` query sees an outcome only if its resolution date is on or before `as_of`. A row without a resolution date is excluded from point-in-time queries (conservative). Source: `tests/test_memory_pointintime.py`. | `outcomes` / `rule_evaluations` (A10). Gate evaluation and outcome scoring (B02, B05). |
| TA-2 | **Half-open date windows `[start, end)`.** Timestamps are converted to the right timezone (IST for AMFI), not truncated. Undated rows are dropped in backtests and kept only in live windows. An empty result after filtering is reported, not shown as blank. Source: `tests/test_news_lookahead.py`. | `engine/stats/series_grid.py` (A13), walk-forward (B05). Add regression tests. |
| TA-3 | **Record the run's settings in every report.** | Already covered by snapshot hashes and policy versions (B02). Check only. |

Status: TA-1 and TA-2 are NOT VERIFIED in IIP until the follow-up tests exist.
