# Investment Intelligence Pro

A **local, single-user, deterministic** research workbench for an Indian investor deciding where to put a specific amount of
money for a specific period (1, 3, 6 or 12 months, or longer). It compares mutual funds, T-bills and fixed deposits **on the
same terms**: your amount, your withdrawal date, after costs and assumed tax. Every number shows its source, date and formula.

> Personal research tool. Not investment advice. Not registered with SEBI as an Investment Adviser or Research Analyst.

## What makes it different

- **Deterministic, supervised engine.** A deterministic supervisor checks that every required input is present and fresh before it
  answers. If anything is missing it **abstains** and lists exactly what is missing. Workers can only cite engine-computed or
  source-dated facts, so free-floating numbers are impossible by construction.
- **No composite score.** Options are filtered by your constraints, put into certainty tiers (T1 sovereign contract → T4 market
  risk) and ordered by your objective. Equity can never outrank a T-bill for a short capital-preservation goal because of past
  returns. **"No suitable candidate found"** is a valid answer.
- **Honest uncertainty.** Market-linked outcomes are ranges taken from historical windows ("k of N windows"), never probabilities.
  Under one year, returns are shown as absolute, never annualised.
- **Provenance everywhere.** The official sources are AMFI for NAVs, plus your own cited entries for RBI T-bills and bank FDs.
  Stale, conflicting or unofficial data is excluded with a reason, and development fixtures carry a loud FIXTURE badge.

## Quick start

```bash
make setup     # pinned dependencies
make run       # http://127.0.0.1:8741 (localhost only)
make open      # one-time login link
make check     # tests, lint, types, build, dependency audit
```

See [`docs/operations/deployment.md`](docs/operations/deployment.md) for getting real data, and
[`docs/operations/known-limitations.md`](docs/operations/known-limitations.md) for what is not verified or not built.

## Documentation map

| Area | Document |
|---|---|
| Requirements (including the supervisor principle) | `docs/product/requirements.md` |
| Research: GitHub references, hidden gems, selection | `docs/research/` |
| Data sources and licensing | `docs/data/source-registry.md` |
| Architecture and ADRs | `docs/architecture/` |
| Calculation, risk and forecasting methodology | `docs/finance/`, `docs/forecasting/` |
| Security, threat model, regulatory readiness | `docs/security/` |
| Operations | `docs/operations/` |
| Screenshots (FIXTURE data is labelled) | `docs/screenshots/` |

## Stack

Python 3.12 · FastAPI · SQLite (WAL) · `decimal` money · numpy/scipy (statistics only) · React 19 + TypeScript + Vite.
Independent test oracles (dev only): QuantLib, pyxirr, scipy, scoringrules.
