# ADR-0001: Technology stack and runtime

## Context
- The engine needs exact decimals, mature scientific libraries for statistics, and independent oracles for testing (QuantLib, scipy, pyxirr).
- The machine runs Node 24 through Volta, but pnpm runs under Node 20, which makes native Node addons segfault. Only 17 GB of disk is free.
- The deployment is a single user on localhost.

## Decision
- **Backend:** Python 3.12, managed by uv with a lockfile.
  - FastAPI with Pydantic v2 for the API and schema validation.
  - `decimal` for money; numpy/scipy only inside the statistics modules.
  - SQLite through the stdlib `sqlite3` module (no ORM), with WAL mode.
- **Frontend:** React + TypeScript + Vite as a single-page app. In production, FastAPI serves it from the same origin.
  - `pnpm install` is used only to install packages. Scripts run with `node --run`, and no native addons are allowed.
- **Tests:** pytest + hypothesis (property tests) for the backend; vitest + Testing Library for the frontend; Playwright (already installed as an MCP plugin) for screenshots and end-to-end smoke tests.
- **Lint and types:** ruff and mypy (strict on `engine/`); tsc in strict mode.

## Consequences
- Two languages, but the split is clean: every number is computed in Python, and the frontend only renders.
- Python 3.12 is chosen over 3.13/3.14 because the oracle wheels (QuantLib, statsforecast) are verified for 3.12 on arm64 (reference-selection.md §4).

## Evidence
- github-reference-review.md (stack challenges: none major).
- reliability-design.md (SQLite settings).
- Memory: Volta/pnpm quirk.
