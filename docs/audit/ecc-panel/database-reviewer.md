# ECC panel: database-reviewer

Scope: `backend/src/iip/store` (schema, migrations 0001/0002, `write_tx`, per-thread connections, backup/restore) and the SQL in `backend/src/iip/services`.
This was a read-only review. Both findings below were reproduced with scratch scripts against an in-memory or temporary SQLite database. No project file was changed apart from this report.

## Summary

The store layer is sound. It uses WAL, `synchronous=FULL`, `foreign_keys=ON`, and `BEGIN IMMEDIATE` for every write. Connections are per thread. All decimals are stored as TEXT. Every query found is parameterised. The partial unique index enforces one current observation per series/date/source.

Two real defects were found. Both are about how transactions are bounded, not about the schema itself:

| ID | Sev | Where | Problem |
|----|-----|-------|---------|
| DB-1 | High | `services/ingestion.py:280-288` | The prune step's `superseded_by = NULL` breaks `ux_obs_current`. After the first NAVAll correction for an untracked scheme, every later NAVAll run fails. The run row stays `running`, so no failure alert is raised. |
| DB-2 | High | `services/portfolio.py:571-604`, `services/cas.py:571-611` | The "already applied" checks run outside the write transaction. Two applies of the same import running at once both commit, and the holdings are duplicated. |
| DB-3 | Low | `services/instruments.py:414-423` | Deleting a manual instrument that has transactions causes a foreign-key `IntegrityError`, which the user sees as an opaque 500. Deleting an FD leaves its `fd.*` settings rows behind. |

## DB-1 (High): pruning untracked NAV history violates the partial unique index

`prune_untracked_history` runs this for each untracked scheme:

```sql
UPDATE observations SET superseded_by = NULL
 WHERE superseded_by IN (SELECT obs_id FROM observations
                          WHERE series_id=? AND source_id='amfi.navall' AND observation_date < ?)
```

A correction (`upsert_observation` → CORRECTED) always involves two rows with the same series, date and source: an old row A with `superseded_by = B`, and B, which is current. When the date is older than the latest one, both rows are in the delete set. The UPDATE sets A to NULL while B is still NULL. That makes two "current" rows for the same key, which breaks `ux_obs_current` (`0001_initial.sql:106`).

Reproduction: upsert `10.0`, then `10.1` (CORRECTED) for 2026-01-01, then a row for 2026-01-02, then call `prune_untracked_history(conn, set())`. The call fails with `IntegrityError: UNIQUE constraint failed: observations.series_id, observations.observation_date, observations.source_id`.

Impact:
- `ingest_navall` (`ingestion.py:206`) raises after the observations are stored. `_finish_run` is never reached, so the `ingestion_runs` row stays `status='running'` for good.
- The A/B pair stays in the table, so every later NAVAll refresh fails the same way and the API returns 500.
- The "ingestion failed" alert (`alerts.py:229`) only looks for `status='failed'`, so it never fires.
- The RT-21 data-minimisation pruning stops for every scheme.
- The trigger is ordinary: AMFI republishing a NAV for the same date, or the value or quality_status changing between two runs.

The UPDATE is also unnecessary. A row and the row it is superseded by share the same date, so they are always deleted together. SQLite checks immediate foreign keys at the end of each statement, so a single DELETE of both rows is valid.

The UPDATE is also slow. `superseded_by` has no index, so for each of the (many) untracked schemes this full-scans `observations` while holding the write lock.

Fix: drop the UPDATE and keep only the DELETE. Add a regression test that includes a corrected row. Optionally, make `ingest_navall` record `failed` from a `try/finally` so a crash cannot leave a run stuck in `running`.

## DB-2 (High): applying an import is check-then-act across a transaction boundary

`apply_holdings_import` (`portfolio.py:571-588`) and `apply_cas_import` (`cas.py:571-597`) do their checks before `with write_tx(conn)`:
- read the batch record;
- check `status == "previewed"`;
- check `_already_applied(...)`.

Then they run `pre_change()`, a full online backup, which is slow. Only after that do they `BEGIN IMMEDIATE`. Nothing is re-checked inside the transaction.

The routes are sync FastAPI handlers, so they run in a thread pool, each with its own connection. A double-click or a client retry therefore runs two applies at once. Both pass the checks, and the transactions then run one after the other. The result is two committed copies of every row.

Reproduction: two connections to one file database. The first call's `pre_change` runs the second apply. Both return `applied` and `transactions` holds 2 rows instead of 1. Two different previews of the same file (two batch ids) also both apply, because `_already_applied` has the same gap.

Impact: the holdings show twice the units and cost. Every later valuation, XIRR, tax and rebalancing figure is wrong for real money, and the oversell check cannot catch duplicated buys.

Fix: inside the `write_tx`, re-read the batch row and re-check both `status == 'previewed'` and `_already_applied`, and abort if either fails. Alternatively, make the status flip a guarded `UPDATE settings ... WHERE key=? AND json_extract(value_json,'$.status')='previewed'` and require `rowcount == 1`.

## DB-3 (Low): deleting a manual instrument that is still referenced

`delete_instrument` (`instruments.py:414-423`) deletes from `instruments`. `transactions.instrument_id` references it with no ON DELETE action, so if the instrument has transactions the DELETE fails with `sqlite3.IntegrityError`. Rollback is correct and no data is lost, but the error reaches the generic 500 handler (`routes_core.py:151`) instead of a clear 409.

For FDs, only `bond.meta:<iid>` is removed. `fd.existing:<iid>` (the user's existing deposit amount), `fd.institution_type:<iid>` and `fd.entered_at:<iid>` are left behind as orphans. If the same id is entered again, the old values are picked up.

Fix: inside the transaction, check for referencing transactions and return 409. Also delete the `fd.%:<iid>` settings keys.

## Checked and fine

- Migration runner: contiguous versions, one transaction per migration, and `current_version` is read-only (SEC-10).
- `write_tx` uses `BEGIN IMMEDIATE` and rolls back on `BaseException`. No nested `write_tx` calls were found.
- `upsert_observation`'s self-pointing supersede trick is valid with `foreign_keys=ON`.
- All dynamic SQL uses identifier-asserted constants or placeholder lists. No injection was found.
- Every reader of current observations filters `superseded_by IS NULL`. Readers that combine NAV and yield sources handle conflicts between sources explicitly.
- Backup and encrypted backup are checked with integrity_check before they replace the target. Encrypted restore never overwrites an existing file.
