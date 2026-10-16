# Runbook: move the hosted database from Turso `iad1` to `bom1` (decision U-12)

- **Why:** the Vercel function runs in `bom1` (Mumbai) and the Turso primary is in `iad1` (Virginia). Each SQL
  statement costs about **0.40 s** (VERIFIED, `docs/research/wave1/audit-perf-hosted.md` RC-1); `/api/data-health`
  takes 10.5–11.3 s. The existing store's region cannot be changed (the store schema marks it `ui:disabled = update`),
  so a **new** database is created in `bom1` and the data is moved.
- **Decision:** U-12, decided 2026-10-16 — move now, via this runbook, **after a dry run on a copy**. **The owner runs
  every account step.** No agent, script or CI job in this repo logs in to Vercel or Turso, creates or deletes a
  database, or changes an environment variable.
- **Expected effect:** same-region statement latency in single-digit milliseconds is an estimate. **Post-move latency is
  NOT VERIFIED until Part C below is run and its numbers are recorded in Part E.**
- **Data sensitivity:** the dump contains your portfolio, transactions and profile. Work in a private folder **outside
  the repository** (this runbook uses `~/iip-move/`), never commit or upload it, and delete it in Part F.

Tools used: the Vercel dashboard, the Turso dashboard and/or the `turso` CLI (yours, logged in as you), the system
`sqlite3`, and `scripts/turso_latency_probe.py` (read-only; never prints the token; redacts the database name).

> **Command syntax status.** The `turso` CLI lines below are the commonly documented forms but were **NOT VERIFIED in
> this repo**. Run `turso db shell --help` and `turso db --help` first and adapt. It is also NOT VERIFIED that a
> database created through the Vercel marketplace integration is reachable from your own `turso` CLI login; if it is
> not, use the dashboard's shell/export features or the fallback in B3.

---

## Part A — Preparation (no changes anywhere)

1. Pick a quiet window. During the move do not import a CAS, edit holdings or run a refresh (single user, so a short
   write freeze is enough).
2. In the hosted app, **Settings → Export everything (JSON)** and **Export transactions (CSV)**. Save both in `~/iip-move/`. This is your
   human-readable record if anything goes wrong.
3. Note the row counts the app reports on the Settings page (data inventory, from `/api/privacy/inventory`). You will compare
   against them.
4. Record the app-level timing **before** the move from your own browser or terminal: the time of
   `GET /api/data-health` and `GET /api/me` while logged in (as in `audit-perf-hosted.md` §6). Write the numbers in
   Part E.

## Part B — Dry run on a copy (required by U-12)

1. **Dump the current database** into `~/iip-move/iip-dump.sql`:
   ```bash
   mkdir -p ~/iip-move && chmod 700 ~/iip-move
   turso db shell <current-db-name> .dump > ~/iip-move/iip-dump.sql      # syntax NOT VERIFIED: check --help
   ```
2. **Load it into a local copy** and check it:
   ```bash
   sqlite3 ~/iip-move/copy.db < ~/iip-move/iip-dump.sql
   sqlite3 ~/iip-move/copy.db "PRAGMA integrity_check;"                   # expect: ok
   sqlite3 ~/iip-move/copy.db "SELECT MAX(version) FROM schema_version;"  # expect the version /api/ready reports
   sqlite3 ~/iip-move/copy.db "SELECT COUNT(*) FROM transactions;"        # compare with the A.3 inventory
   ```
   If the dump contains libSQL-only statements that `sqlite3` rejects, note the line, stop, and do not proceed to Part D
   until the cause is understood (NOT VERIFIED either way).
3. **Probe the copy** (proves the probe and its statements against your real schema; local timings are meaningless):
   ```bash
   cd <repo>
   IIP_DB_URL=~/iip-move/copy.db backend/.venv/bin/python scripts/turso_latency_probe.py \
       run --label dry-run --allow-local --repeats 3
   ```
4. **Open the copy in local mode** to see your data rendered from it:
   ```bash
   mkdir -p ~/iip-move/data && cp ~/iip-move/copy.db ~/iip-move/data/iip.db
   IIP_DATA_DIR=~/iip-move/data make run       # then, in another terminal: IIP_DATA_DIR=~/iip-move/data make open
   ```
   Check holdings, transactions and goals look right. Stop the app. (Local mode may apply newer migrations to this copy;
   that is fine, it is a copy.)
5. **Rehearse the rollback:** delete `~/iip-move/data/` and `~/iip-move/copy.db`. Nothing outside `~/iip-move/` was
   touched.
6. **Fallback if no dump is possible (B3):** skip the dump. In Part D the new database starts empty; the app creates the
   schema at cold start; you then re-import your CAS, re-enter the profile answers and manual entries (use the A.2
   export as the reference), and re-run *Fetch latest AMFI NAVs* and the backfills. Under U-01 hosted mode stores only
   held and watched schemes, so this rebuild is small.

## Part C — Measure before (old database)

You need a URL and a read token for the **current** database. The Vercel integration's `TURSO_*` variables are
sensitive and cannot be read back (`docs/operations/deployment.md`), so create a read-only token for the database in
the Turso dashboard (or `turso db tokens create <db> --read-only`, syntax NOT VERIFIED).

```bash
IIP_DB_URL='libsql://<current-db>-<org>.turso.io' IIP_DB_AUTH_TOKEN='<read-only token>' \
    backend/.venv/bin/python scripts/turso_latency_probe.py run --label before --out ~/iip-move/before.json
```

Run it from the same machine and network you will use for the *after* run. It prints one line per statement per
repeat (for example `before noop #1 <ms>`), then a per-statement summary. The token is never printed; the database
name is shown as `libsql://***.turso.io`.

## Part D — The move (owner, in the dashboards)

1. **Create the new database:** Vercel dashboard → project → **Storage** → **Create Database** → **Turso** → Primary
   Region **AP South (Mumbai)** (`bom1`). Do **not** connect it to the Production environment yet. If the integration
   insists on connecting, choose a custom environment-variable prefix if one is offered (NOT VERIFIED that it is), so
   it does not overwrite the current `TURSO_*` variables.
2. **Take a fresh dump** (repeat B.1 now that writes are frozen) and **load it into the new database**:
   ```bash
   turso db shell <new-db-name> < ~/iip-move/iip-dump.sql                 # syntax NOT VERIFIED: check --help
   ```
   Or follow the B3 fallback.
3. **Check the new database:** `PRAGMA integrity_check`, `SELECT MAX(version) FROM schema_version`, and the
   transaction count, in the Turso shell. They must match B.2.
4. **Measure after** (same machine and network as Part C), with a read-only token for the **new** database:
   ```bash
   IIP_DB_URL='libsql://<new-db>-<org>.turso.io' IIP_DB_AUTH_TOKEN='<read-only token>' \
       backend/.venv/bin/python scripts/turso_latency_probe.py run --label after --out ~/iip-move/after.json
   backend/.venv/bin/python scripts/turso_latency_probe.py compare ~/iip-move/before.json ~/iip-move/after.json
   ```
   `compare` prints each statement's median before and after and the change. These are client-to-database numbers;
   the function-to-database number is checked in step 7.
5. **Create a read-write token for the new database** (the app writes sessions and data). Keep it in your password
   manager only.
6. **Switch production:** Vercel → project → Settings → Environment Variables → **Production**: set
   `IIP_DB_URL` = the new URL and `IIP_DB_AUTH_TOKEN` = the new token. The app reads `IIP_DB_URL` /
   `IIP_DB_AUTH_TOKEN` **before** `TURSO_DATABASE_URL` / `TURSO_AUTH_TOKEN` (`backend/src/iip/api/settings.py`,
   VERIFIED by reading the code), so the old integration variables can stay in place for rollback. Redeploy
   production.
7. **Verify the deployed app:**
   - `/api/ready` reports the same schema version as before;
   - log in; holdings, transactions and goals match the A.2 export;
   - responses still carry `x-vercel-id: bom1::…`;
   - time `GET /api/data-health` and `GET /api/me` as in A.4 and record them in Part E.

## Rollback

- **Before step D.6:** nothing in production changed. Delete the new database if you wish.
- **After step D.6:** delete the `IIP_DB_URL` and `IIP_DB_AUTH_TOKEN` Production variables (the app falls back to the
  old `TURSO_*` database) and redeploy. Anything written to the new database after the switch (sessions, imports,
  refreshes) is **not** in the old one; re-do it, or dump the new database back the same way.
- Keep the old database for at least **14 days** (PARAMETER) before deleting it. Deleting is your action in the Vercel
  dashboard; Turso's own backups keep deleted rows until they expire.

## Part E — Results (fill in; until then post-move latency is NOT VERIFIED)

| Measurement | Before (`iad1`) | After (`bom1`) | Measured on (date, by) |
|---|---|---|---|
| Probe `noop` median (client → DB) | | | |
| Probe `catalog` median | | | |
| Probe `app_read` median | | | |
| `GET /api/me` (app) | | | |
| `GET /api/data-health` (app) | | | |

Do not commit the probe JSON files: they contain only timings and a redacted host, but they are personal operational
data and the repository is public. Copy the medians into this table instead.

## Part F — Clean-up

```bash
rm -P ~/iip-move/iip-dump.sql 2>/dev/null || rm ~/iip-move/iip-dump.sql   # contains personal financial data
rm -rf ~/iip-move/copy.db ~/iip-move/data
```

Revoke the read-only tokens created for Parts C and D.4 in the Turso dashboard. Keep or delete the A.2 exports as you
prefer; they are your data.

## References

- `docs/research/wave1/audit-perf-hosted.md` RC-1 (cause, measurements, the region field, fix options).
- `docs/research/wave1/PLAN.md` §3 U-12, §4 rank 2, §7 (post-move latency NOT VERIFIED).
- ADR-0013 (hosted mode), ADR-0017 (what hosted mode may store).
- `scripts/turso_latency_probe.py` and its test `backend/tests/hosted/test_turso_latency_probe.py`.
