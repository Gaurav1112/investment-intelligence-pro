# Investment Intelligence Pro — Reliability and Operations Design

Status: DRAFT v0.1 · Written 2026-10-15 · Author role: Agent I (SRE / Reliability) · Applies to: v1 (single user, macOS, localhost)

Related: `docs/security/threat-model.md` (controls C-xx, tests SEC-xx), `docs/product/requirements.md` §3.5. That section's rule is "stale or missing data disables the claims that depend on it".

The reliability goal is **not** uptime. A personal localhost app being down is cheap. The goal is that **the app never presents a stale, partial or wrong number as current**, and that the user's own data is never lost. Every mechanism below serves one of those two goals.

---

## 1. Runtime layout

| Item | Default | Override |
|---|---|---|
| Data dir | `~/Library/Application Support/InvestmentIntelligencePro/` (0700) | `IIP_DATA_DIR` |
| DB | `$DATA/iip.sqlite3` (+ `-wal`, `-shm`) | — |
| Raw payload archive | `$DATA/raw/<source_id>/<yyyy>/<sha256>.zst` | — |
| Backups | `$DATA/backups/` plus optional `IIP_BACKUP_MIRROR_DIR` (e.g. an external disk) | `IIP_BACKUP_DIR` |
| Logs | `~/Library/Logs/InvestmentIntelligencePro/{app,ingest}.jsonl` | `IIP_LOG_DIR` |
| Run lock | `$DATA/run/ingest.lock` (`fcntl.flock`) | — |
| API | `127.0.0.1:8741` | `IIP_PORT` |

Processes:

- **API server.** uvicorn, single process, single worker. It serves the built SPA and `/api`.
- **Ingestion job.** `iip ingest run`, a CLI entry point in the same Python package. It is triggered by launchd daily, by `make ingest`, or by the UI's "refresh source" button, which enqueues the job in-process under the same lock.

Both processes use the same DB through the SQLite settings in §5. They never run two ingestions at once, because of the file lock.

## 2. Health, readiness and status endpoints

| Endpoint | Auth | Purpose | Checks | Response |
|---|---|---|---|---|
| `GET /healthz` | None (Host check still applies, C-03) | Liveness: is the process serving? | Event loop responds. **No DB access.** | `200 {"status":"ok"}` |
| `GET /readyz` | None for the status code; details need a session | Readiness: can it serve correct answers? | (1) DB opens and `SELECT 1`; (2) `schema_migrations` head == code's expected version; (3) DB writable (`BEGIN IMMEDIATE; ROLLBACK`); (4) disk free in the data dir ≥ 1 GiB; (5) last `quick_check` result (cached, ≤ 24 h old) == `ok`; (6) reference data present (holiday calendar covers today + 30 days, tax table covers the current FY) | `200` all ok; `503` with failing check ids when any fails. The body lists check ids only, never paths. |
| `GET /api/status` | Session | Operator dashboard data | Freshness per dataset (§3), last N ingestion runs, breaker states, last backup age and result, last restore drill, DB size and WAL size, disk free, security/LLM rejection counters, app version, build manifest | JSON, rendered on the SPA **System** page |
| `GET /api/status/freshness` | Session | Lightweight freshness feed polled by the SPA every 5 min to drive banners | §3 | JSON |
| `GET /metrics` | Session | Optional Prometheus text format, for users who run a local Prometheus | Counters and gauges from §8 | text/plain |

Startup sequence (fail fast):
1. Load settings, then the security preflight checks (loopback bind, secrets present, file modes).
2. Open the DB and apply PRAGMAs.
3. If `schema_migrations` is behind and `IIP_AUTO_MIGRATE=1` (the default for local use): take a pre-migration backup (§7), then migrate. Otherwise refuse to start with a clear message.
4. Run `PRAGMA quick_check` if the last check is older than 24 h, which takes seconds at our size. On failure, start in **read-only degraded mode** (§4.6) and show the restore runbook link.
5. Begin serving.

## 3. Data-freshness SLOs

Definitions:
- **Freshness** = (now, Asia/Kolkata) − *expected-available time* of the newest dataset period that should exist.
  - It is measured in **business days** for exchange/AMFI data, using the stored NSE/AMFI holiday calendar.
  - It is measured in calendar days for everything else.
- **States:** `fresh` → `warn` → `stale` → `critical`.
  - `stale` disables the dependent claims; the UI says why.
  - `critical` disables the dependent pages' personalised outputs entirely.
- **SLO target** = the fraction of days in a rolling 30-day window on which the dataset is `fresh` at 09:00 IST.
  - This is a personal-tool SLO. It tells us whether the pipeline is healthy enough to trust, and it is reported on the status page.
  - It is not a paging contract.

| Dataset | Source (pending Agent E) | Publication rhythm | Expected-available | `warn` | `stale` (claims disabled) | `critical` | SLO (30 d) | Dependent claims |
|---|---|---|---|---|---|---|---|---|
| MF daily NAV | AMFI `NAVAll.txt` | Each business day; AMFI requires NAVs by 23:00 IST | Next calendar day 07:00 IST | Latest NAV date < last business day (as of 09:00) | ≥ 2 business days behind | ≥ 5 business days behind | ≥ 95 % | MF current value, 1M returns, liquidity-tier valuations, rankings using MF NAV |
| MF NAV history (backfill) | AMFI NAV history report | On demand | — | Gaps > 0 in the requested window | Gap > 3 business days in a window used by a metric | Window < 80 % complete | n/a (completeness metric) | Rolling-return stats, feasibility analysis (per scheme) |
| T-bill / G-sec yields | RBI auction results / FBIL benchmarks | T-bill auctions weekly (Wed); FBIL daily | Auction day + 1 | > 8 calendar days | > 15 days | > 30 days | ≥ 90 % | T-bill / G-sec comparisons, risk-free reference in risk-adjusted metrics |
| Policy rates (repo, SDF, MSF) | RBI | Event-driven (MPC) | MPC decision day + 1 | Last verification > 30 days | Not verified after a scheduled MPC date + 3 days | > 90 days unverified | n/a (event) | Rate-regime notes, liquid-fund context |
| CPI inflation | MoSPI | Monthly, ~12th of the following month | 15th of the following month | Latest month older than expected by > 3 days | > 20 days late | > 45 days late | ≥ 90 % | Real-return figures (falls back to nominal-only with a label) |
| Market holiday calendar | NSE holiday master / AMFI | Yearly + amendments | Before 1 Dec for the next year | Coverage < today + 60 d | Coverage < today + 30 d | Today not covered | 100 % | Business-day arithmetic, settlement-day estimates, NAV freshness itself |
| Tax rule tables | Curated, versioned (Agent B) | Union Budget / Finance Act, effective FY | Before FY start (1 Apr) | `verified_at` > 180 days | Current FY not covered | Analysis date outside any table | 100 % | All after-tax figures (fall back to pre-tax plus a label) |
| FD rates | Manual entry with citation | Ad hoc | — | Citation > 30 days | > 90 days | > 180 days | n/a (manual) | FD comparisons (shown with "as of" date) |
| User holdings | User import/entry | User-driven | — | Snapshot > 90 days (nudge only) | — | — | n/a | Concentration analysis is labelled with the snapshot date. Never blocked. |

**Alerting** uses no SaaS and no email server:
1. **In-app banner.** It shows on every page whenever any dataset is `stale` or worse. A `critical` banner is red and can't be dismissed. The dependent widgets show "Disabled: <dataset> is N business days old (last update <date>, source <id>)".
2. **macOS notification.** At the end of every scheduled ingestion run, a run that worsens any dataset's state, fails a source, or opens a breaker posts a notification with `osascript -e 'display notification ...'`. The text never contains amounts or holdings, only dataset ids and states. One notification is sent per state change, so there is no daily repetition of the same alert.
3. **Status file.** `$DATA/run/status.json`, written atomically after each run, for anyone who wants to script around it.
4. **Exit codes** from `iip ingest run`: `0` all ok, `10` partial (some sources failed), `20` all failed, `30` precondition failed (lock held, DB not ready). launchd logs the exit codes.
5. **Error-budget view.** The status page shows each dataset's 30-day SLO attainment and the days that missed it.

Freshness is computed **at read time** from the DB, not cached from the last job. That way a dead scheduler cannot leave a "fresh" flag behind. A test freezes time (`time-machine`) and asserts the state transitions (REL-10).

## 4. Ingestion job design

### 4.1 Run model and ledger

Each invocation creates an **ingestion run** per source, with one row per attempt group:

```sql
CREATE TABLE ingestion_run (
  run_id           TEXT PRIMARY KEY,           -- ULID
  source_id        TEXT NOT NULL,              -- from the code SourceRegistry (C-08)
  trigger          TEXT NOT NULL CHECK (trigger IN ('schedule','manual','backfill','catchup')),
  target_period    TEXT NOT NULL,              -- e.g. '2026-10-14' for daily NAV, '2026-09' for CPI
  started_at       TEXT NOT NULL,              -- UTC ISO-8601
  finished_at      TEXT,
  status           TEXT NOT NULL CHECK (status IN
                     ('running','succeeded','unchanged','partial','suspect','failed','skipped_breaker_open')),
  attempts         INTEGER NOT NULL DEFAULT 0,
  http_status      INTEGER,
  bytes            INTEGER,
  payload_sha256   TEXT,                       -- links to raw archive
  rows_parsed      INTEGER, rows_inserted INTEGER, rows_updated INTEGER,
  rows_unchanged   INTEGER, rows_quarantined INTEGER,
  error_class      TEXT, error_code TEXT,       -- e.g. 'Timeout', 'schema_drift' (no free text with data)
  parser_version   TEXT NOT NULL,
  app_version      TEXT NOT NULL,
  published        INTEGER NOT NULL DEFAULT 0   -- 1 if this run's data became "current"
);
CREATE UNIQUE INDEX one_running_per_source ON ingestion_run(source_id) WHERE status = 'running';
```

The ledger is append-only. It is the audit trail behind every observation (`observation.run_id → ingestion_run`). This is the integrity control referenced by the threat model, T-14 and C-09.

### 4.2 Idempotency
- **Natural keys.** Observations are keyed by `(source_id, series_key, observation_date)`, for example `(amfi_nav_daily, scheme_code, nav_date)`. Writes are `INSERT ... ON CONFLICT DO UPDATE` only when the value differs. A differing value for an already-published date is recorded as a **revision**: the old value is kept in `observation_revision` and the event is counted. A revision usually means an upstream correction and is surfaced on the status page.
- **Payload dedupe.** If `payload_sha256` equals that of the last `succeeded` run for the same `source_id` and `target_period`, the run ends `unchanged` without parsing. This is cheap, and re-running is always safe.
- **Re-running any run** with the same inputs yields the same DB state. Tests assert this by running twice and comparing a logical dump (REL-20).
- **Catch-up.** On every run, the job reads the ledger to find target periods since the last published period that are missing. That covers a laptop asleep at 07:00, a weekend, or the machine being off. It backfills them in order, up to 30 business days. Older gaps go through `iip ingest backfill --from --to`. This makes a missed launchd firing harmless.
- **Concurrency.** An exclusive `fcntl.flock` on `run/ingest.lock` is taken with a non-blocking attempt. If it fails, the second invocation exits with code `30` and logs `lock_held`. The partial unique index is a second line of defence. A `running` row older than 2 h is recovered as `failed (abandoned)` on the next start.

### 4.3 Retries, backoff, jitter
Each attempt is one HTTP request plus a parse. Retry policy per request:

| Condition | Retry? |
|---|---|
| Connect error, DNS failure, read timeout, `5xx`, `408`, `429` | Yes |
| `429`/`503` with `Retry-After` | Yes, waiting `min(Retry-After, 300 s)` |
| Other `4xx`, TLS verification failure, SSRF refusal (C-08), size cap exceeded, schema drift | **No.** These are deterministic failures, and retrying hammers upstream for nothing. |

- Backoff is **exponential with full jitter**: `sleep = random.uniform(0, min(cap, base * 2**attempt))`, with `base = 2 s`, `cap = 60 s`, and **max 4 attempts** per run. The randomness comes from an injectable RNG/clock, so tests are deterministic.
- The total run budget per source is 10 min. If it runs out, the run is marked `failed (budget)`.
- The scheduled job also adds **0–10 min of start jitter**. That avoids hitting AMFI at an exact minute along with every other cron on the internet.

### 4.4 Circuit breaker (per source, persisted)
The breaker state lives in a `source_breaker(source_id, state, consecutive_failures, opened_at, next_probe_at)` table. It is persisted because each launchd run is a fresh process.

- **closed → open:** after **3 consecutive failed runs**. Runs, not attempts: the 4 retries inside a run count as one.
- **open:** scheduled runs for that source are recorded as `skipped_breaker_open`, and no network calls are made. A notification is sent once when the breaker opens.
- **open → half-open:** after a 6 h cooldown. The cooldown doubles on each re-open, capped at 48 h. The next run makes a **single** attempt with no retries.
- **half-open → closed:** on success. **half-open → open:** on failure.
- **Manual override.** `iip ingest run --source X --force` bypasses the breaker for one run, logs it, and still applies the rate limit (C-16).
- Schema-drift failures open the breaker **immediately**. A parser change is required, and repeated fetching is pointless.

### 4.5 Parse, validate, stage, publish (partial-failure handling)
Pipeline per source run:
1. **Fetch.** Stream the response into a temp file under the byte cap (C-08), compute its SHA-256, and move it into the raw archive (zstd-compressed). The archive keeps 400 days for daily sources; CPI/RBI files are kept forever because they are small.
2. **Contract check.** Exact header, delimiter, column count and section structure. For example, AMFI `NAVAll.txt` has a header line, then `Open Ended Schemes(...)` section lines, then AMC name lines, then data rows. On mismatch the run ends `failed (schema_drift)`, nothing is staged, and the breaker opens immediately.
3. **Row parse.** Each row is validated with Pydantic: `Decimal` NAV > 0, a valid date, a scheme code that is an int, and an ISIN format plus check digit when present. Bad rows go to the `quarantine` table with a reason code and the raw line hash, not the raw line, though the raw file is in the archive anyway.
4. **Plausibility.** These checks quarantine a row, they don't drop it:
   - a |day-over-day NAV change| > 20 %, unless the scheme is flagged with a known event;
   - a future date;
   - a date older than the last published date with a different value (which becomes a revision candidate).
5. **Run-level gates:**
   - `rows_quarantined / rows_parsed > 1 %` → status `suspect`;
   - `rows_parsed < 0.8 × trailing-20-run median` → `suspect`;
   - the expected period is missing from the file (e.g. every NAV is dated two days back) → `suspect`.
   
   A **`suspect` run is staged but not published.** The previous published data stays current, and the freshness clock keeps ticking, so the UI degrades honestly. The status page offers "review quarantine" and "publish anyway". Publishing anyway is an explicit, logged user action.
6. **Publish.** One write transaction (`BEGIN IMMEDIATE`) upserts the staged observations, sets `published=1` and records counts. Readers never see half a run. If 0 < quarantined ≤ 1 %, the run is `partial`: it is published, and the quarantined series are flagged individually, so a single bad scheme doesn't block the other ~10,000.
7. **Cross-source isolation.** The job processes sources independently. One source failing never aborts others, and the final exit code reflects the worst outcome (§3).

### 4.6 Degraded-mode behaviour

| Condition | Behaviour |
|---|---|
| A dataset is `stale` | Claims that depend on it are disabled with an explanation. Other pages work normally. Exploration mode shows the old data labelled "as of <date> — stale". |
| A dataset is `critical` | Personalised rankings that use it return the honest result *"No ranking produced: required data is out of date"*, never a ranking on old data. |
| Source breaker open | Same as stale, plus "Source unavailable since <time>; next automatic retry <time>". The manual refresh button respects the cooldown, but `--force` remains available from the CLI. |
| Run `suspect` | The previous data stays current. A banner reads "Latest <source> file failed validation; showing data as of <date>". |
| Network offline | The app is fully usable for everything that is fresh. Ingestion fails fast (DNS) without opening breakers: an offline-detected run is recorded as `failed (offline)` and **not** counted toward the breaker. |
| Local LLM unavailable | Deterministic template explanations (threat model C-11). No user-visible error beyond a small "AI wording unavailable" note when the user enabled the feature. |
| DB `quick_check` fails / disk full | **Read-only mode:** writes are refused with a clear message, reads continue (results are labelled), and `/readyz` returns `503`. The UI links to the restore runbook (§7.3). |
| Migration pending and auto-migrate off | The app refuses to start, printing the exact command. |
| Holiday calendar missing for today | Business-day arithmetic falls back to weekdays-only **with a label**. Freshness for exchange-calendar datasets is computed conservatively and may read as stale. |

## 5. SQLite operational settings

The connection factory applies these settings on **every** connection, as a single code path tested by REL-30:

```python
conn = sqlite3.connect(path, timeout=5.0, isolation_level=None, check_same_thread=False)  # we manage txns explicitly
conn.execute("PRAGMA journal_mode=WAL")        # persistent; readers don't block the writer
conn.execute("PRAGMA synchronous=FULL")        # durability over speed; our write rate is tiny
conn.execute("PRAGMA busy_timeout=5000")       # wait up to 5 s for the write lock
conn.execute("PRAGMA foreign_keys=ON")         # per-connection; OFF by default in SQLite
conn.execute("PRAGMA trusted_schema=OFF")      # security (C-10)
conn.execute("PRAGMA temp_store=MEMORY")
conn.execute("PRAGMA journal_size_limit=67108864")  # cap WAL file at 64 MiB after checkpoints
conn.enable_load_extension(False)
```

- **Write transactions use `BEGIN IMMEDIATE`.** It takes the write lock up front. That avoids the `SQLITE_BUSY` deadlock where a deferred read transaction cannot be upgraded to a write while another process writes. Writes are short. Ingestion stages rows in memory or a temp table and publishes in one short transaction.
- **Checkpointing.** WAL auto-checkpoint stays at its default (1000 pages). After each ingestion run the job runs `PRAGMA wal_checkpoint(TRUNCATE)`, and `PRAGMA optimize` runs on connection close of the long-lived API connection and after ingestion.
- **Version floor.** Python's bundled SQLite in the uv-managed 3.12 build is not the system 3.43. At startup the app asserts `sqlite3.sqlite_version >= 3.35`, the floor for `RETURNING`, `DROP COLUMN` and the partial-index features used, and logs the version.
- **Integrity:**
  - `PRAGMA quick_check` at startup if older than 24 h;
  - full `PRAGMA integrity_check` weekly (scheduled with the ingestion job on Sundays) and always on backup copies (§7);
  - `PRAGMA foreign_key_check` after every migration.
  
  Results are recorded in `maintenance_log`.
- **Money.** Stored as TEXT canonical decimals, never REAL, which preserves `Decimal` exactness (requirements A4). There is a `CHECK` on format.
- **Migrations.** *Decision for v1: plain versioned SQL files.* Alembic is used only if an ADR adopts the SQLAlchemy ORM.
  - Files: `backend/migrations/NNNN_<slug>.sql`, forward-only.
  - Table `schema_migrations(version INTEGER PRIMARY KEY, name TEXT, sha256 TEXT, applied_at TEXT)`.
  - The runner verifies that the checksums of already-applied files are unchanged and refuses to start on tamper or edit. It then applies the pending files in order, each in its own `BEGIN IMMEDIATE` transaction, and runs `foreign_key_check`.
  - Table rebuilds follow SQLite's documented 12-step procedure: `foreign_keys=OFF` outside the txn, create new, copy, drop, rename, `foreign_key_check`, `foreign_keys=ON`.
  - A **backup is taken automatically before any migration** (§7).
  - Rollback means restoring that backup. We don't write down-migrations for a single-user app; the backup is the down-migration.
  - Why not Alembic by default: there are few tables, there is no ORM need, and plain SQL keeps the schema reviewable and deterministic. If SQLAlchemy Core plus Alembic is chosen, use `render_as_batch=True` for SQLite ALTERs.

## 6. Structured logging

- Python `logging` with `structlog`, or a small JSON formatter if we want zero extra dependencies. Output is one JSON object per line.
- Common fields: `ts` (UTC ISO-8601, ms), `level`, `event` (snake_case constant), `logger`, `app_version`, `pid`.
  - API requests add `request_id` (ULID, also returned in the `X-Request-ID` header), `route` (the template, e.g. `/api/holdings/{id}`), `method`, `status` and `duration_ms`.
  - Ingestion adds `run_id`, `source_id`, `target_period`, `attempt`, `http_status`, `bytes`, `rows_*`, `error_class` and `error_code`.
- **Privacy:** threat model C-13 applies. There is a field allowlist and a redaction processor, and no bodies, amounts, holdings, tax data or tokens are logged. Test SEC-62 enforces this.
- Levels:
  - `INFO` for lifecycle and run summaries (one line per source run, not per row);
  - `WARNING` for degraded states, quarantines and security events;
  - `ERROR` for failed runs and unhandled exceptions;
  - `DEBUG` is off by default and is redaction-filtered just the same.
- Sinks: `RotatingFileHandler` 10 MiB × 5 per log file in `~/Library/Logs/InvestmentIntelligencePro/`, so Console.app can view them, plus stderr when interactive. launchd's `StandardOutPath`/`StandardErrorPath` point to separate files for crash capture.
- `iip logs tail [--event X] [--run RUN_ID]` is a small CLI wrapper around `jq`-free filtering for local diagnosis.

## 7. Backups and restore

### 7.1 Backup design
- **Mechanism:** Python's `sqlite3.Connection.backup()` (the SQLite Online Backup API). It copies a consistent snapshot while the app is running, including WAL content. `VACUUM INTO` is the acceptable alternative. Plain `cp` of the `.sqlite3` file is **never** used, because it can tear the WAL.
- **Procedure** (`iip backup create`):
  1. `src.backup(dst, pages=1024, sleep=0.05)` into `backups/.tmp-<ulid>.sqlite3`.
  2. On the copy: `PRAGMA integrity_check` must return `ok`, `PRAGMA foreign_key_check` must be empty, and the `schema_migrations` head is recorded.
  3. Optionally compress with zstd and encrypt (threat model C-12; AES-256-GCM, passphrase-derived key).
  4. `fsync`, then an atomic rename to `iip-<YYYYMMDDTHHMMSSZ>-v<schema>.sqlite3[.zst][.enc]`. Write a sidecar `.json` holding the SHA-256, size, schema version, app version, row counts per table and encryption flag. The sidecar contains no user values.
  5. If `IIP_BACKUP_MIRROR_DIR` is set, copy to it and verify the SHA-256.
  6. Record the result in `backup_log`.
- **When:**
  - daily, after the scheduled ingestion;
  - before every migration;
  - before every holdings import apply, erase or restore. These are "pre-change" backups, retained for 14 days.
- **Retention (GFS):** 7 daily, 4 weekly, 12 monthly, plus pre-change backups for 14 days. Pruning never deletes the newest verified backup.
- **SLO:** last verified backup ≤ 26 h old. Breaching it sets the status page to `warn` and sends a notification.
- The raw payload archive is **not** backed up by default, because it can be re-downloaded or is reproducible. User tables and published observations are in the DB backup.

### 7.2 Restore drill (automated)
- **`REL-40` in the test suite** (every `make check`, on fixtures):
  1. Create a DB with fixture data via migrations.
  2. Take a backup while a concurrent writer thread is inserting (it proves online consistency).
  3. Mutate the live DB.
  4. Restore to a new path.
  5. Assert that `integrity_check` is ok, that the schema version matches, and that a logical dump of every table equals the dump taken at backup time.
  6. Repeat with encryption on: a wrong passphrase fails, and a flipped byte fails authentication.
- **Real-data drill:** `make restore-drill`, run monthly by the launchd job on the 1st, or on demand.
  1. Pick the newest backup, verify its SHA-256 against the sidecar, and decrypt it into a `tempfile.mkdtemp()` dir (0700).
  2. Run `integrity_check`, compare row counts with the sidecar, and run the migration runner in check mode.
  3. Start the API **against the restored copy** on an ephemeral loopback port and call `/readyz`.
  4. Delete the temp dir.
  5. Record `restore_drill_log` (pass/fail, duration).
  
  The status page shows the last drill. More than 35 days without a drill is `warn`.

### 7.3 Restore runbook (manual)

> Use this when: `quick_check` fails, the DB is accidentally modified or erased, or a migration needs rolling back.

1. **Stop writers.** `make stop`, which stops the API. Then `launchctl bootout gui/$(id -u)/com.local.iip.ingest` if the ingestion agent is loaded, or wait for `run/ingest.lock` to be free.
2. **Preserve the evidence.** `make backup-broken` moves `iip.sqlite3`, `-wal` and `-shm` to `$DATA/broken-<timestamp>/`. **Never delete the broken files** until the restore is verified.
3. **Choose a backup.** `iip backup list` shows timestamp, schema version, verified flag and size. Pick the newest verified backup taken before the incident. For a migration rollback, take the `pre-migration` backup and check out the matching app version (`git checkout <tag>`).
4. **Restore.** `iip backup restore <file>`. It:
   - verifies the SHA-256 (and decrypts, prompting for the passphrase);
   - writes to `iip.sqlite3.restoring`;
   - runs `integrity_check`;
   - atomically renames into place;
   - removes stale `-wal`/`-shm` files.
5. **Verify.** `make doctor` (expect `/readyz` 200), then open the System page and confirm the schema version, the holdings count and the last import timestamp.
6. **Catch up public data.** `make ingest`. The catch-up logic (§4.2) refetches the market data periods missing since the backup.
7. **Re-apply user changes made after the backup.** Check the import ledger in the broken copy (`iip backup inspect broken-*/iip.sqlite3 --ledger`) and re-import those files if they are still available.
8. **Restart.** `make run`, then reload the launchd agent. Note the incident in `docs/operations/incidents.md` with the date, cause and data lost (if any).

Point-in-time objective: **RPO ≤ 24 h** for user data, and less in practice, because every import, erase and restore takes a pre-change backup. **RTO ≤ 15 min** following this runbook.

## 8. Observability without external SaaS

| Signal | Store | Surface |
|---|---|---|
| Ingestion runs, breaker states, quarantine counts, revisions | SQLite tables (§4) | System page; `iip status`; `status.json` |
| Freshness and SLO attainment | Computed from observations plus the calendar | Banners, System page, notifications |
| Backups, restore drills, integrity checks | `backup_log`, `restore_drill_log`, `maintenance_log` | System page, `make doctor` |
| Request metrics | In-process counters (requests by route and status, latency histogram buckets, rejections by reason: host/csrf/rate/ssrf/llm) | `/metrics` (optional local Prometheus/Grafana), System page |
| Logs | JSONL files | Console.app, `iip logs tail` |
| Environment health | `make doctor`: Python/SQLite versions, Node/pnpm versions (the Volta quirk), FileVault, data dir modes, disk free, port bound only on loopback, Ollama bind check, lockfile sync, launchd agent loaded, last run, last backup | Terminal |

There are no third-party telemetry, crash reporting or analytics SDKs, backend or frontend (CSP `connect-src 'self'` also enforces this).

## 9. Reproducible builds

- **Python:**
  - `pyproject.toml` with `requires-python = "==3.12.*"` and `.python-version` = `3.12`;
  - `uv.lock` committed;
  - all commands use `uv sync --frozen` / `uv run --frozen`;
  - `uv lock --check` runs in `make check` to fail on drift;
  - Python itself is the uv-managed build, pinned by `.python-version`.
- **Frontend:**
  - `package.json` has `"packageManager": "pnpm@10.28.x"` (exact), `"engines": {"node": ">=22.12"}` and a Volta pin of `"node": "24.15.x"`;
  - `pnpm-lock.yaml` committed;
  - installs run `pnpm install --frozen-lockfile`.
- **Environment quirk (this Mac).** Volta runs `pnpm` itself under Node 20, while `node` is 24. Therefore:
  - use pnpm **only for install, add and audit**;
  - run every package script with **`node --run <script>`**, which uses Node 24 and needs Node ≥ 22. For example `node --run build` or `node --run test`, **not** `pnpm build`. `node --run` does not execute `pre`/`post` hooks, so scripts must not depend on them;
  - allow **no native Node addons**: `onlyBuiltDependencies: []`, and prefer pure-JS packages. For example, no `better-sqlite3` and no native `esbuild` alternatives beyond what Vite ships prebuilt. If a native binary is unavoidable (esbuild/rollup ship platform binaries as optional deps, not install scripts, which is fine), it must not need a build step;
  - `make doctor` prints both Node versions and warns if `pnpm <script>` is used in any Makefile target (grep).
- **Pinned tooling:** ruff, mypy/pyright, pytest, pip-audit and osv-scanner are pinned as dev dependencies, or in the case of osv-scanner as a version recorded in `make doctor`.
- **Build manifest:** `make build` writes `backend/app/static/build-manifest.json` containing the git SHA (if any), the SHA-256 of `uv.lock` and `pnpm-lock.yaml`, the Python, Node and SQLite versions, and `SOURCE_DATE_EPOCH`. It is exposed at `/api/status`. The Vite build sets `build.sourcemap=false` for production and uses deterministic chunk names.
- **Engine determinism** is tested elsewhere (identical inputs give byte-identical outputs). The build reproducibility check here is that `make build` run twice gives an identical `dist/` hash (REL-60).

## 10. Local deployment

### 10.1 Make targets

| Target | Does |
|---|---|
| `make setup` | `uv sync --frozen`; `pnpm install --frozen-lockfile`; create the data dir (0700); generate the access token; run migrations |
| `make dev` | Backend `uv run --frozen uvicorn ... --reload --host 127.0.0.1` with `IIP_ENV=dev`, plus `node --run dev` (Vite on localhost, proxying `/api`) |
| `make build` | `node --run build` → copy `dist/` into backend static; write the build manifest |
| `make run` | Production mode on `127.0.0.1:8741` (single worker); writes a PID file |
| `make open` | Opens the browser with the token in the URL fragment (C-02) |
| `make stop` | Stops the server via the PID file |
| `make ingest` | `uv run --frozen iip ingest run` (all due sources, with catch-up) |
| `make backup` / `make restore FILE=…` / `make restore-drill` | §7 |
| `make doctor` | §8 environment health |
| `make test` / `make test-security` / `make check` | Unit + integration; SEC-xx; everything plus lint, type and audit |
| `make audit` | pip-audit, pnpm audit, osv-scanner (threat model C-17) |
| `make launchd-install` / `make launchd-uninstall` | Render and load or unload the LaunchAgents below |
| `make token-rotate` | New access token; invalidates sessions |

Scripts are plain POSIX shell and Python. Make is the single entry point, with no Docker requirement (disk space is tight: ~17 GB free).

### 10.2 launchd (optional, macOS)

`~/Library/LaunchAgents/com.local.iip.ingest.plist` (rendered from a template with absolute paths):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.local.iip.ingest</string>
  <key>ProgramArguments</key><array>
    <string>/Users/USER/.local/bin/uv</string><string>run</string><string>--frozen</string>
    <string>--project</string><string>/ABS/PATH/investment-intelligence-pro/backend</string>
    <string>iip</string><string>ingest</string><string>scheduled</string>  <!-- ingest + backup + weekly integrity + monthly drill -->
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>15</integer></dict>
  <key>RunAtLoad</key><false/>
  <key>ProcessType</key><string>Background</string>
  <key>LowPriorityIO</key><true/>
  <key>Nice</key><integer>10</integer>
  <key>EnvironmentVariables</key><dict><key>IIP_DATA_DIR</key><string>/Users/USER/Library/Application Support/InvestmentIntelligencePro</string></dict>
  <key>StandardOutPath</key><string>/Users/USER/Library/Logs/InvestmentIntelligencePro/launchd-ingest.out</string>
  <key>StandardErrorPath</key><string>/Users/USER/Library/Logs/InvestmentIntelligencePro/launchd-ingest.err</string>
</dict></plist>
```

- **07:15 IST** comes after AMFI's 23:00 NAV deadline, with a margin for late publishers. The job adds 0–10 min of jitter itself.
- **Missed runs.** launchd coalesces calendar intervals missed while the Mac was asleep into one run on wake. It does **not** run them if the Mac was powered off. That is why the job's own **catch-up logic** (§4.2) matters, and why `make run` also triggers an ingestion if the last scheduled run is older than 24 h.
- No secrets go in the plist. The job reads the data-dir `.env` (0600).
- An optional second agent, `com.local.iip.server`, runs the API with `KeepAlive` → `SuccessfulExit=false` and `RunAtLoad=true`, for users who want the app always available. It is off by default.
- Install with `launchctl bootstrap gui/$(id -u) <plist>`; uninstall with `launchctl bootout gui/$(id -u)/com.local.iip.ingest`. Check with `launchctl print gui/$(id -u)/com.local.iip.ingest` (last exit code).

## 11. Reliability test plan (automated)

| ID | Test | Expected |
|---|---|---|
| REL-01 | `/healthz` works with the DB file removed or locked | `200` (liveness has no DB dependency) |
| REL-02 | `/readyz` with a pending migration / read-only DB file / quick_check failure (stubbed) / missing holiday coverage / low disk (stubbed) | `503` with the correct check id each time |
| REL-10 | Freshness state machine with a frozen clock across weekends, NSE holidays, Diwali Muhurat sessions, and a late AMFI file | Correct `fresh/warn/stale/critical` per §3; dependent claims disabled at `stale` |
| REL-11 | Ranking request while MF NAV is `critical` | Returns "No ranking produced: required data is out of date", never a ranking |
| REL-20 | Ingest the same fixture payload twice | Second run `unchanged`; logical dump identical |
| REL-21 | Re-ingest a payload with one changed historical NAV | One `observation_revision` row; counter incremented |
| REL-22 | Two concurrent `iip ingest run` | The second exits `30` (`lock_held`); no duplicate rows |
| REL-23 | Stale `running` row from a killed process (> 2 h) | Recovered as `failed (abandoned)`; a new run proceeds |
| REL-24 | Catch-up: last published period is 4 business days ago | 4 periods fetched in order, `trigger='catchup'` |
| REL-30 | Every connection from the factory has the PRAGMAs (`journal_mode=wal`, `foreign_keys=1`, `busy_timeout=5000`, `synchronous=2`, `trusted_schema=0`) | Pass |
| REL-31 | A writer holds the lock for 2 s while the API writes | API write succeeds after waiting (busy_timeout), no `database is locked` error |
| REL-32 | FK violation insert | Raises |
| REL-33 | Migration runner: an applied file edited | Startup refused (checksum mismatch) |
| REL-34 | Migration runner: fresh DB → head; head → head is a no-op; pre-migration backup created | Pass |
| REL-40 | Backup during concurrent writes → restore → logical-dump equality; encrypted variant; wrong passphrase; tampered byte | Pass / clean failure / auth failure |
| REL-41 | Retention pruning with synthetic backup dates | Keeps 7/4/12 + pre-change 14 d; never deletes the newest verified |
| REL-42 | `make restore-drill` against the newest fixture backup | Starts the API on the copy, `/readyz` 200, drill logged |
| REL-50 | Retry policy (respx + injected clock/RNG): 503,503,200 | 3 attempts, delays within full-jitter bounds, `Retry-After` honoured and capped |
| REL-51 | 404 / schema drift / TLS error / SSRF refusal | No retry (1 attempt) |
| REL-52 | Breaker: 3 failed runs → open → skipped runs make no HTTP calls → after cooldown a single half-open probe → success closes / failure reopens with a doubled cooldown | Pass |
| REL-53 | Offline (DNS failure for all hosts) | `failed (offline)`, breaker counters unchanged |
| REL-54 | Schema drift fixture (AMFI header column renamed) | `failed (schema_drift)`, nothing published, breaker open, notification queued |
| REL-55 | 2 % of rows invalid | Run `suspect`, not published; previous data still current; banner state set |
| REL-56 | 0.5 % invalid | `partial`, published, quarantined series flagged |
| REL-57 | Row count 50 % of the trailing median | `suspect` |
| REL-58 | Source A fails, source B succeeds in the same invocation | B published; exit code `10` |
| REL-59 | Response exceeding the size cap mid-stream | Aborted; temp file removed; no raw archive entry |
| REL-60 | `make build` twice | Identical `dist/` tree hash |
| REL-61 | Lockfile sync (`uv lock --check`, frozen pnpm install) | Pass |
| REL-62 | Notifications: a state change triggers exactly one notification; an unchanged state triggers none; the text contains no sentinel amounts | Pass (notifier stubbed) |

## 12. Open items
1. Agent E: confirm exact source URLs and publication times; the §3 thresholds will be tuned to observed publication behaviour after 30 days of ledger data.
2. Decide whether `mfapi.in` serves as a fallback for NAV history. If yes, it gets its own breaker, is tagged lower-trust, and is cross-checked against AMFI for overlapping dates.
3. Confirm Diwali Muhurat trading and other special sessions are represented in the calendar model (affects REL-10).
