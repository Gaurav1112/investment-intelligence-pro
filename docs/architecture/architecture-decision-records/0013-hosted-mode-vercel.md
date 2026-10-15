# ADR-0013: Hosted mode on Vercel (single user, personal use)

Status: **DEPLOYED and VERIFIED on Vercel (2026-10-15)** at the project's production URL, with a Turso database from
the Vercel marketplace. Verified on the live deployment: the UI is served from the function bundle; the build image
runs pnpm and `node --run`; region `bom1` (Mumbai) is accepted on Hobby (`x-vercel-id: bom1::bom1`); login over the
token gives a Secure, HttpOnly, SameSite=Strict cookie; HSTS, CSP, nosniff and no-referrer are sent; a raw deployment
URL is refused (400); `/api/ready` reports schema version 3 against Turso; AMFI answers Vercel; the NAVAll fetch stores
all 1,779 minimised-scope schemes in one 98 s call (0.038 s per scheme) after the batching fix. Items 4, 5 and 8 below
remain NOT VERIFIED.

## Context

The user decided (2026-10-15) to host the full app on Vercel. Before this, the app was built for one machine:
- It binds to loopback only.
- Its data is a SQLite file under `~/.iip`, with backups as files beside it.
- Sessions, rate limits and the backfill lock live in process memory.
- A NAV-history backfill can run for minutes.

None of that holds on Vercel:
- Functions have no persistent disk; only `/tmp`, which is lost between instances.
- Instances share no memory and can run concurrently.
- Every invocation has a hard time limit.
- Traffic arrives over HTTPS at a public hostname.

Local mode stays the default and is unchanged.

## Decision

`IIP_DEPLOY=vercel` turns on hosted mode. `IIP_DEPLOY=local` is the default. Hosted mode differs from local mode in
these ways:

| Concern | Local (unchanged) | Hosted |
|---|---|---|
| Database | sqlite3 file `~/.iip/iip.db` | **Turso (libSQL)**, remote, via `libsql==0.1.11`, with the same SQLite dialect and migrations |
| DB access | `sqlite3.Row` | `iip.store.db.LibsqlConnection` adapter: `row["col"]`, `row[0]`, `dict(row)`, `rowcount`, `lastrowid`, `in_transaction`, `with conn:`, busy/locked retried ≤ 10 s, errors re-raised as `sqlite3` errors |
| Access token | generated file `secrets/access-token` (0600) | env `IIP_ACCESS_TOKEN` (≥ 32 chars, else startup refused) |
| Host / Origin allowlist | `127.0.0.1:8741` etc. | exactly the host of `IIP_PUBLIC_ORIGIN` (https only). Vercel deployment and preview URLs are refused with 400 |
| Session cookie | HttpOnly, SameSite=Strict | the same plus **Secure**. HSTS (`max-age=63072000; includeSubDomains`) on every response |
| Sessions | in memory | table `web_sessions`, which stores the SHA-256 of the cookie, never the value. Same idle (8 h) and absolute (24 h) limits |
| Login limiter (10/min) | in memory | table `rate_hits`, one conditional `INSERT … SELECT … WHERE count < limit`, so it is atomic across instances |
| Refresh limit (SEC-86, per source; backfill per scheme) | in memory under a lock | table `refresh_claims`, one conditional upsert |
| One backfill at a time | `threading.Lock` | table `leases` (`DbLease`), one conditional upsert; the lease lapses after 330 s if its function is killed |
| NAVAll ingest | one call | **resumable**: 200 schemes per transaction, progress in `job_progress`, the client calls again while `done` is false |
| NAV-history backfill | one call | **resumable**: AMFI fund-house probe, then one 90-day window per unit, progress saved after each unit |
| Pre-import safeguard (reliability-design §7.1) | verified file backup | in-database snapshot of all transactions (`import_snapshots`, newest 20 kept, erased as user data) |
| File backups, restore drill, encrypted backups | yes | **refused** (`BACKUP_NOT_AVAILABLE_HOSTED`, 409). Use Turso's point-in-time restore or Settings → Export |
| Privacy erase | rows deleted, `secure_delete`, `VACUUM`, WAL truncate, backups optional | rows deleted in one transaction (same tables plus `job_progress`). The response states that the provider's own backups keep deleted rows until they expire |
| Local LLM (`IIP_LLM=local`) | allowed | refused at startup and in Settings (`LLM_LOCAL_NOT_AVAILABLE_HOSTED`); a saved local config is ignored |
| Dev fixtures, API docs | dev/test only | never (`IIP_ENV=prod`; the seed route refuses) |

**Resumable jobs.** Each call does at least one unit of work, then stops starting new upstream requests after
`HOSTED_JOB_BUDGET_S = 200` s. That leaves room inside Vercel's 300 s limit for one slow request and its writes.
- The time budget is checked only after a unit, so a call always makes progress and the loop cannot stall.
- The MF page loops until `done` (at most 200 calls) and shows the server's progress counts.
- A new run is rate-limited, but a continuation of the run in progress is not.
- On a cold start, only runs older than any live function could be are marked interrupted. A run whose job progress
  was touched in the last hour is left alone.
- Parity is tested: the resumable jobs store exactly what the local single-call versions store
  (`test_resumable_navall_stores_exactly_what_the_local_ingest_stores`,
  `test_resumable_backfill_discovers_then_fetches_and_matches_local`).

**Why each claim is one statement.** An interactive transaction held open over HTTP is the least certain part of
the libSQL remote protocol (see "Not verified"). Every cross-instance claim is therefore a single conditional
statement, which SQLite and libSQL execute atomically.

**Why the pre-import safeguard is a snapshot.** The import already applies in one transaction, so a failed import
changes nothing. The backup guards against a *wrong* import that succeeded, and an in-database copy of the
transactions taken just before covers that without a disk.

**Migrations.** Migrations run at cold start. `migrate()` now re-checks the version after `BEGIN IMMEDIATE`, so two
instances cold-starting at once cannot both apply the same migration.

## Files

- `app.py` (repo root): the Vercel entrypoint. It puts `backend/src` on the path, sets `IIP_DEPLOY=vercel` and builds
  the app from the environment.
- `requirements.txt` (generated, `make requirements`): runtime dependencies only, without the dev and oracle groups.
  QuantLib, pyxirr and scoringrules are test oracles and are not bundled.
- `.python-version`: 3.12.
- `vercel.json`: `buildCommand` (`scripts/vercel-build.sh` builds the frontend from the pinned lockfile),
  `functions.app.py.maxDuration = 300`, `excludeFiles` (tests, docs, node_modules, frontend sources) and
  `regions: ["bom1"]` (Mumbai, near AMFI and an Indian Turso region).
- `.vercelignore`: keeps `.git`, `.env*`, the `.venv`s, `node_modules`, `docs`, `backend/tests`, data and any `*.db` out
  of the upload.
- `make deploy-check`, run with no network:
  - `vercel.json` sanity;
  - `requirements.txt` in sync with `uv.lock`;
  - the root entrypoint served in hosted mode on a temporary libSQL file. It checks health, the UI at `/`, refusal of
    a non-public host, HSTS, and the Secure/Strict cookie.

## Research findings

| Finding | Status | Source |
|---|---|---|
| Vercel runs FastAPI and other ASGI apps from a top-level `app` in `app.py`/`index.py`/`main.py`… or `tool.vercel.entrypoint`; it detects the framework from `requirements.txt`/`pyproject.toml` | VERIFIED (docs, 2026-10-15) | vercel.com/docs/functions/runtimes/python; /docs/frameworks/backend/fastapi |
| Python 3.12 is the default (3.13 and 3.14 also available) | VERIFIED (docs) | same |
| Bundle limit is 500 MB uncompressed (5 GB "Large Functions" beta) | VERIFIED (docs) | same |
| Our runtime dependencies for manylinux x86_64 / CPython 3.12 total **286 MB** (scipy 110 MB with its libs, casparser_isin 47 MB, numpy 56 MB with its libs) | VERIFIED (measured locally with `uv pip install --python-platform x86_64-manylinux_2_28`) | this ADR |
| Hobby with Fluid compute: default and maximum duration 300 s; set with `functions.<entry>.maxDuration` in `vercel.json` | VERIFIED (docs) | vercel.com/docs/functions/configuring-functions/duration |
| A build command for FastAPI comes from `vercel.json` `buildCommand` (it takes precedence over `[tool.vercel.scripts]`) | VERIFIED (docs) | /docs/frameworks/backend/fastapi |
| Files reachable at build time are bundled; no tree-shaking; `excludeFiles` prunes | VERIFIED (docs) | /docs/functions/runtimes/python |
| Shutdown cleanup is limited to 500 ms after SIGTERM | VERIFIED (docs) | /docs/frameworks/backend/fastapi |
| `libsql` 0.1.11 (Rust, maturin; wheels for manylinux x86_64, CPython 3.8–3.14) connects remotely with `libsql.connect("libsql://…", auth_token=…)` | VERIFIED (docs + PyPI); remote connection NOT VERIFIED (no Turso account used) | docs.turso.tech/sdk/python/quickstart; pypi.org/project/libsql |
| `libsql` has no `row_factory`; rows are tuples; `cursor.description` is present; `executescript`, `json_extract`, `BEGIN IMMEDIATE`/`ROLLBACK`, `ON CONFLICT … DO UPDATE … WHERE` with `rowcount` 0/1, and `in_transaction` all work | VERIFIED (local probe and the test suite on a local libSQL file) | `tests/hosted/` |
| On a local file, libSQL does **not** wait on a locked database (`busy_timeout` has no effect): concurrent `BEGIN IMMEDIATE` fails at once | VERIFIED (locally); handled by the adapter's 10 s retry | `test_import_concurrency.py` under `IIP_DB_DRIVER=libsql` |
| The whole existing suite on the libSQL driver (`IIP_DB_DRIVER=libsql`, local files, 2026-10-15). Everything passes except **17** tests, all of which need sqlite3-only file features:<br>• the online backup API: 9 encrypted-backup tests, 2 backup/restore tests, and 5 API import tests whose LOCAL-mode apply takes a file backup first;<br>• `iterdump`: 1 test.<br>Hosted mode never uses either: it refuses backups and takes a snapshot instead | VERIFIED locally | — |

## Not verified (needs a real deployment; do these at first deploy)

1. **Static UI in the function bundle:** that `frontend/dist`, built by `buildCommand`, ends up in the function bundle,
   and that `GET /` serves it. Check: open the URL; an API-only deploy answers `{"code":"NOT_FOUND"}` at `/`.
2. **Build image tooling:** that the build image's Node can run `npx pnpm@10.28.2` and `node --run` (Node ≥ 22).
3. **Region on Hobby:** that `regions: ["bom1"]` is accepted on the Hobby plan.
4. **Remote transactions:** behaviour of the libSQL **remote** protocol for `write_tx` (interactive `BEGIN IMMEDIATE`
   … `COMMIT` over HTTP). In particular, how long a transaction may stay open and what a second concurrent writer sees.
   The import apply and erase use such transactions. Cross-instance claims do not.
5. **Remote foreign keys:** whether `PRAGMA foreign_keys=ON` holds for every statement on a remote connection.
6. **NAVAll timing:** the first real deploy (2026-10-15) **timed out**. The first call downloaded NAVAll in under a
   second, then ran 305 s and hit the 300 s limit (504). Cause: the step stored one full 200-scheme chunk before
   checking the clock, and storage cost about 6 round trips per scheme (2 scheme upserts plus BEGIN, SELECT, INSERT
   and COMMIT per NAV). That came to about 1,200 remote statements per chunk, and about 12,500 for the ~1,780
   schemes in scope. Every continuation also downloaded NAVAll again.
   **Fixed:**
   - **Batched storage:** `store.observations.upsert_observations_batch`, one transaction per block. It gives the
     same rows, ids and superseded links as the per-row path (a differential property test runs on both drivers).
     A 100-scheme block went from 602 statements to 8, about 12 per step with the progress row.
   - **Single-statement prune.**
   - **Clock check before every block,** the first included. A block runs only if 1.5 × its measured
     seconds-per-scheme fits in the time left. When it doesn't fit, a partial block is stored (at least one scheme
     per call), so the job never stalls.
   - **One download per run:** the first call stages only the minimised scope, about 1 MiB in 18 rows of about
     58 KiB for 1,780 schemes. Continuations read that and never fetch.
   Timing against Turso after the fix: **VERIFIED (2026-10-15)** — one call stored all 1,779 schemes in 98 s
   (`seconds_per_scheme` 0.0379), well inside the 300 s limit.
7. **AMFI from Vercel: VERIFIED (2026-10-15).** From `bom1`, `www.amfiindia.com` answered 302 to
   `portal.amfiindia.com/spages/NAVAll.txt`, which answered 200 in under a second.
8. **Hermetic tests:** the hermetic test guard blocks Python sockets only. libSQL's Rust client would bypass it, so the
   hosted tests use only local files and never a `libsql://` URL.

## Conditions of use (personal use only)

These follow from AMFI's terms, the regulatory analysis and the threat model. They are repeated in deployment.md.
- **One user:** you. Do not share the URL together with the token, and do not add other users. The app has no
  multi-user model.
- **No public offering:** do not offer the hosted app to anyone else. Ranking funds for other people moves toward SEBI
  investment adviser / research analyst territory (`docs/security/regulatory-readiness.md`), and AMFI data is for
  personal, non-commercial use with no redistribution.
- **Third parties hold your data:** your financial data is held by **Vercel** (function logs; the app logs no amounts
  or personal values, C-13) and by **Turso** (the database, plus its point-in-time backups). Local mode keeps it on
  your machine only.

## Consequences

- Local mode is unchanged (all existing tests pass unmodified, apart from the migration count, 2 → 3).
- One more runtime dependency (`libsql`, pinned).
- Six new tables (migration 0003), which local mode creates but leaves unused, apart from `import_snapshots` in USER_TABLES.
- Hosted mode loses file backups, the local LLM and byte-level erase. It gains availability anywhere, at the cost of
  third-party custody.
