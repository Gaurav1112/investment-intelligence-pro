# ADR-0012: Storage, migrations and run records

## Decision
- SQLite with WAL, `synchronous=FULL`, `foreign_keys=ON`, `busy_timeout`, and `BEGIN IMMEDIATE` for writes.
- Plain versioned SQL migrations (`migrations/NNNN_*.sql`) with a `schema_version` table.
- Backups use the online backup API, followed by `integrity_check`. A restore drill is part of the test suite.
- Observation tables are append-only with a `superseded_by` field, so source corrections are kept as new versions.
- `calculation_runs`, `ranking_runs` and `forecast_runs` store the input snapshot hash, engine and policy versions, parameters and the output hash.

## Evidence
reliability-design.md.
