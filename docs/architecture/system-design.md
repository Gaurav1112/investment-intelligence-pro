# System Design — Investment Intelligence Pro

Status: v1.0 · 2026-10-15 · This design follows ADR-0001 … ADR-0012, which were written after the Phase 1–3 research.

## 1. Pipeline

```
Source registry ─► Adapters (allowlisted fetch / manual entry / CSV import)
                    │  raw bytes + sha256 + retrieved_at
                    ▼
                 Parsers (per-format, strict) ─► Validators (schema, ranges, dates, jumps, duplicates)
                    │  observations with provenance + quality_status
                    ▼
                 Normalised store (SQLite, append-only, superseded_by)
                    │
                    ▼
   ┌──────────── SUPERVISOR (deterministic) ─────────────┐
   │ QuestionType → ContextManifest                       │
   │ dispatch Workers → validate WorkerContracts          │
   │ completeness gate ─► ABSTAIN (itemised gaps)         │
   │ conflict rules ─► surfaced conflicts                 │
   └───────┬──────────────────────────────────────────────┘
           ▼
   Deterministic engine (pure functions, Decimal)
     returns · cashflows · fixed income · deposits · tax · risk · scenarios
     ranking policy · feasibility · forecasting baselines
           ▼
   Synthesis (templates; optional LLM rephrase → numeric validator → Compliance Guard)
           ▼
   RunRecord (input hash, versions, output hash) ─► API (FastAPI) ─► SPA (React)
```

## 2. Repository layout

```
investment-intelligence-pro/
├── backend/
│   ├── pyproject.toml, uv.lock
│   ├── src/iip/
│   │   ├── engine/            # PURE: no I/O, no clock, no randomness without an explicit seed
│   │   │   ├── money.py       # Decimal context, quantisation, INR formatting
│   │   │   ├── daycount.py    # ACT/365F, 30/360 (Indian G-sec), ACT/ACT (SEBI 2016)
│   │   │   ├── calendar.py    # business-day rules from injected holiday sets
│   │   │   ├── returns.py     # absolute, CAGR, annualisation guard, TWR, IRR, XIRR, real
│   │   │   ├── fixed_income.py# T-bill, coupon schedule, accrued, clean/dirty, YTM, YTC, duration, convexity
│   │   │   ├── deposits.py    # FD/RD maturity, premature withdrawal, effective yield, DICGC coverage
│   │   │   ├── costs.py       # stamp duty, exit load, STT, transaction costs
│   │   │   ├── tax.py         # rule selection by date, gain classification, tax computation
│   │   │   ├── stats/         # floats allowed: vol, drawdown, Sharpe/Sortino, VaR/CVaR, beta, TE, HHI
│   │   │   ├── scenarios.py   # rate shock, spread shock, equity shock, early exit, reinvestment
│   │   │   ├── ranking.py     # eligibility → outcome bands → tiers → ordering (ranking_policy)
│   │   │   ├── feasibility.py # return-target historical frequency analysis
│   │   │   └── forecasting/   # baselines, bootstrap, walk-forward, scoring, promotion gate
│   │   ├── data/              # adapters, parsers, validators, source registry, freshness
│   │   ├── store/             # sqlite connection, migrations, repositories, backup
│   │   ├── supervisor/        # manifests, contracts, workers, gate, conflicts, synthesis, compliance
│   │   ├── rules/             # tax/*.yaml, mf_categories.yaml, compliance_phrases.yaml, ranking_policy.yaml
│   │   ├── api/               # FastAPI app, security middleware, routers, schemas
│   │   └── llm/               # optional OpenAI-compatible adapter + validator (off by default)
│   └── tests/
│       ├── fixtures/          # hand-computed + probe-derived (FIXTURE-labelled)
│       ├── unit/ property/ oracle/ data/ security/ forecasting/ api/
├── frontend/                  # Vite + React + TS
│   └── src/{app,pages,components,charts,lib}
├── docs/ …
└── Makefile                   # setup, dev, test, check, build, run, backup, restore-drill
```

## 3. Core domain model (SQLite)

| Table | Purpose / key fields |
|---|---|
| `sources` | source_id, owner, official, url, terms_url, licence_note, freshness_slo |
| `ingestion_runs` | run_id, source_id, started_at, finished_at, status, rows_ok/rejected, raw_sha256, error |
| `instruments` | instrument_id, kind (mf_scheme / tbill / gsec / sdl / corp_bond / fd / …), name, issuer_id, isin, amfi_code, currency |
| `issuers` | issuer_id, name, type (sovereign / state / bank / nbfc / psu / corporate / amc) |
| `mf_schemes` | amfi_code, amc, sebi_category (current + legacy name), plan, option, benchmark, riskometer, prc, exit_load_rule_id |
| `bond_terms` | instrument_id, face_value, coupon_rate, coupon_freq, issue_date, maturity_date, daycount, call_schedule_json |
| `deposit_terms` | instrument_id, bank, rate, compounding, tenure_days, premature_penalty_bp, insured (bool) |
| `observations` | obs_id, instrument_id/series_id, kind (nav / price / yield / rate / cpi / rating / expense), value (TEXT decimal), unit, currency, observation_date, retrieved_at, source_id, source_url, quality_status, convention, raw_sha256, superseded_by |
| `holdings`, `transactions` | user-entered or imported; tagged `actual` vs `hypothetical` portfolio |
| `profiles` | investor objectives and constraints (local only) |
| `watchlist`, `alerts` | alert: kind, severity, source_id, observation ref, created_at, ack |
| `runs` | run_id, kind (calc / rank / forecast / supervisor), input_hash, versions_json, params_json, output_hash, output_json, created_at |
| `audit_events` | who/what/when for state changes (no amounts in the message text) |

All decimal values are stored as TEXT, which avoids float storage completely.

## 4. API surface (v1)

`/api/health`, `/api/ready`, `/api/session` (token exchange)
`/api/sources`, `/api/ingestion/runs`, `/api/ingestion/{source}/run` (POST)
`/api/instruments?kind=&q=`, `/api/instruments/{id}`, `/api/instruments/{id}/series`
`/api/calc/*` (returns, xirr, bond, tbill, deposit, tax) — explainable outputs
`/api/discover` (POST profile → supervisor run → ranked / ABSTAIN / NO_CANDIDATE)
`/api/compare` (POST instruments + amount + horizon)
`/api/scenario` (POST assumptions), `/api/simulate` (POST allocation)
`/api/feasibility` (POST target, horizon, series)
`/api/forecast/{instrument}` (baselines + validation report)
`/api/portfolio`, `/api/holdings` (CRUD + CSV import), `/api/watchlist`, `/api/alerts`
`/api/runs/{id}` (full run record; replay endpoint verifies the output hash)
`/api/methodology`, `/api/rules`

Every numeric response field is `{value: "string-decimal", unit, display, source_refs[], as_of}` or a reference to such an object.

## 5. Determinism guarantees (testable)

1. Engine functions are pure, which is enforced by an import-scan test (no `datetime.now`, `random` or network in `engine/`).
2. Canonical JSON (sorted keys, Decimal as string) gives `output_hash = sha256(canonical(output))`.
3. Replaying a stored run reproduces its `output_hash`.
4. Ranking is a total order: the final tiebreak is `instrument_id`.

## 6. Status of external capabilities

See `docs/operations/known-limitations.md`, which is maintained throughout implementation.
