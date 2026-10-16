# Architecture Decision Records

Format: Context → Decision → Consequences → Evidence. Status: ADRs 0001–0013 Accepted (2026-10-15) unless noted.
ADRs 0014–0018 are **Proposed (2026-10-16)** and become Accepted only when the owner accepts them; owner decisions they
record are listed in `docs/product/decisions-register.md`.
Each ADR was decided only after the Phase 1–3 research documents were complete.

| ADR | Title |
|---|---|
| 0001 | Technology stack and runtime |
| 0002 | Money, precision and rounding policy |
| 0003 | Deterministic supervisor and evidence contracts (no LLM in the numeric path) |
| 0004 | Data sources, licensing posture and provenance |
| 0005 | Ranking: eligibility filters + certainty tiers, no composite score |
| 0006 | Frontend components and charting |
| 0007 | Optional LLM adapter (OpenAI-compatible, local-first, free-tier opt-in) |
| 0008 | Local security posture |
| 0009 | Versioned tax and regulatory rule tables |
| 0010 | Forecasting: baselines first, promotion gate |
| 0011 | Independent test oracles kept out of the runtime |
| 0012 | Storage, migrations and reproducible run records |
| 0013 | Hosted mode on Vercel: single user, Turso (libSQL), DB-backed sessions and limits, resumable jobs |
| 0014 | Scheduled jobs (daily refresh) and the narrow cron route — *Proposed* |
| 0015 | Risk-budget engine (risk-first spine) — *Proposed* |
| 0016 | Signal registry, shadow ledger and evidence gates — *Proposed* |
| 0017 | Data rights: AMFI in hosted mode, index-derived constants, equity data — *Proposed* |
| 0018 | Private wording, surfaces and notifications — *Proposed* |
