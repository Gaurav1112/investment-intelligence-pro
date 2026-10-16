# Audit: why the hosted app is slow (perf-hosted)

Date: 2026-10-15 (measurements 17:54 to 18:16 UTC). Target: production deployment `dpl_8YUM6JomDVUEUcfEbq1BmiQ6BHsk`
at https://investment-intelligence-pro.vercel.app (git `8f56a8d`). Auditor: read-only. No repo file other than this
report was changed, and nothing was committed.

## TL;DR

The hosted app is slow mainly because **every SQL statement crosses from Mumbai to Virginia and back**. The function
runs in `bom1` (Mumbai). The Turso database's primary region is `iad1` (US East, Virginia). Each statement costs about
**0.40 s**, and most pages issue between 2 and 25 statements serially. **Discovery issues 1,791 statements, one per
mutual-fund scheme, and always times out at 300 s (HTTP 504).**

Secondary causes:

- The session check runs before every API call, adding 2 statements.
- Every JS/CSS asset is served through the Python function with `max-age=0` and no CDN. Parallel asset requests start
  many cold instances (9 cold starts in about 90 s in the logs).
- Each cold start installs all 40 dependencies at runtime (about 2.5 s), because the bundle is over Vercel's 225 MB
  threshold.

| # | Root cause | Measured impact | Status |
|---|---|---|---|
| 1 | Turso primary in `iad1`, function in `bom1` | ≈0.40 s per statement; `/api/data-health` (25 statements) takes 10.5–11.3 s | VERIFIED |
| 2 | N+1 in `discovery.build_universe`: 1 `COUNT` per scheme (1,779 schemes) | 1,791 statements → **504 after 300.1 s** | VERIFIED |
| 3 | Session lookup in the middleware: `SELECT` + `UPDATE` on **every** API request, run synchronously on the event loop | +2 statements (≈0.8–1.2 s) per request; it blocks other in-flight requests on the instance | VERIFIED (count), blocking: VERIFIED by code reading |
| 4 | SPA `index.html` and `/assets/*` go through the Python function: no CDN, `cache-control: public, max-age=0, must-revalidate`, `x-vercel-cache: MISS` | 44 asset and 62 `/` hits in 6 h, all `route:/fastapi`, `MISS`; parallel chunk loads start parallel cold instances | VERIFIED |
| 5 | Cold start: runtime dependency install (bundle > 225 MB) + eager scipy import + 4 startup statements + connect | Install 2.35–2.63 s (logged); a cold `/api/health` took 6.14 s against 0.13–0.17 s warm | VERIFIED (install and total), split of the remainder: estimate |
| 6 | N+1 in `/api/data-health` (one query per registry source, 21 sources) | 25 statements, about 10.8 s | VERIFIED |
| 7 | `/api/instruments/{id}`: 8 serial statements | about 4.1 s | VERIFIED |
| 8 | Thread-local libSQL connections plus reopening a dropped Hrana stream after idle | adds connect/PRAGMA round trips on new threads and after idle pauses | PLAUSIBLE, NOT VERIFIED |

---

## 1. Method

- **Timing.** `vercel curl <path> -- -s -o /dev/null -b <existing cookie jar> -w '...%{time_total} %{time_starttransfer}'`
  was run from the linked project directory. The cookie jar was still valid, so no login was needed and the token was
  never read. CSRF for the POST came from `GET /api/me`. The client was in India, and the edge was `bom1::bom1`.
- **POST `/api/discover`.** Sent exactly as `frontend/src/pages/Discovery.tsx:255-259` sends it: body
  `{"include_fixtures": false}`, plus `Content-Type: application/json`, `Origin` and `X-IIP-CSRF`.
- **Statement counts.** A local harness (scratchpad, not in the repo) ran the real app in **hosted mode**
  (`IIP_DEPLOY=vercel`, libSQL driver on a local file). It wrapped `LibsqlConnection.execute/executemany` to count
  statements per request.
  - The data was shaped like production: **1,779 MF schemes with 1 NAV each.** Production's `/api/data-health` reports
    `observation_counts: {"ok": 3291}`.
  - `/api/instruments?kind=mf_scheme` returns 500 rows (truncated), all with `nav_points = 1`.
  - The ADR-0013 NAVAll run stored 1,779 schemes.
- **Logs.** `vercel logs --environment production --since 30m --non-interactive` was run twice, at about 18:00 and
  about 18:07. Hobby keeps only about 30 minutes of runtime logs. `--since 1h` and `12h` were refused with "The hobby
  plan does not retain runtime logs for the requested time range". `vercel logs requests --since 6h` returned the CDN
  request records.
- **Platform facts.** `vercel api /v1/storage/stores` and `/v9/projects/<id>` were read, printing non-secret fields
  only.

## 2. Measurements (hosted, production)

All times are seconds, from curl `time_total`. Warm means the instance had answered recently.

| Endpoint | DB statements per request (harness) | Round 1 | Round 2 | Warm rounds w1–w5 |
|---|---:|---:|---:|---|
| `GET /api/health` | 0 | 0.14 | **6.14 (cold, after the 504 killed the instance)** | 0.165, 0.139, 0.134, 0.132, 0.135 |
| `GET /api/me` | 2 | 1.52 | 0.98 | 1.54, 1.50, 1.30, 1.37, 1.37 |
| `GET /api/profile` | 3 | 1.84 | 2.35 | n/a |
| `GET /api/instruments?kind=mf_scheme` | 3 (one big statement + 2 session) | 2.36 | 2.23 | 3.74 in a later single call |
| `GET /api/instruments/mf%3A<scheme>` | 8 | 4.08 | 4.10 | n/a |
| `GET /api/data-health` | 25 | 10.79 | 10.85 | 10.79, 11.33, 10.54, 11.13, 10.80 |
| `GET /api/portfolios` | 3 | 1.79 | 1.72 | n/a |
| `POST /api/discover` | **1,791** | **504 after 300.14 s** | not repeated (see §8) | n/a |

**Per-statement cost.**

- Data-health against instrument detail gives (10.82 − 4.09) / (25 − 8) ≈ **0.40 s per statement**.
- There is also a fixed overhead of about 0.5–0.9 s on any request that touches the DB, compared with `/api/health`.
- The runtime log for the discover request says: `Vercel Runtime Timeout Error: Task timed out after 300 seconds`
  (18:06:34Z).
- The model predicts 0.9 + 1,791 × 0.40 ≈ **717 s** for discovery, so it cannot finish inside `maxDuration: 300`.

Local hosted-driver timings for the same requests were all under 0.03 s (discover was 0.019 s with 1,791 statements).
So the compute is negligible and **the time is network round trips.**

## 3. Root causes, ranked

### RC-1. The database is on another continent (VERIFIED)

Evidence:

- `vercel api /v1/storage/stores` reports `stores[0].name = database-blue-flower`, `product.name = Turso`,
  `metadata.region = iad1`. The product schema labels that field "Primary Region" with options including
  `iad1` "US East (Virginia)" and `bom1` "AP South (Mumbai)". It also sets `ui:disabled = update`, so **the region
  cannot be changed on the existing store.**
- `vercel.json` pins `regions: ["bom1"]`. The deployment reports `regions = ["bom1"]`, and responses carry
  `x-vercel-id: bom1::bom1::…`.
- The project default is still `functionDefaultRegions: ["iad1"]` / `serverlessFunctionRegion = iad1`, but
  `vercel.json` overrides it for this deployment.
- ADR-0013 and `docs/operations/deployment.md:148` assumed "a database in an Indian region (Mumbai)". The marketplace
  integration created it in `iad1`, so **that assumption is false in production.**
- Inter-region RTT is about 190 ms. https://www.economize.cloud/resources/aws/latency/us-east-1-vs-ap-south-1/
  (accessed 2026-10-15): "AWS inter-region network latency from us-east-1 to ap-south-1 is 191.10 ms."
- The measured ≈0.40 s per statement is about 2 RTTs. That fits one Hrana HTTP request per statement plus
  stream/connection overhead. **The exact number of RTTs per statement is NOT VERIFIED.**

Fixes:

- **(a) Recommended. Create a new Turso database in `bom1`** through the same Vercel marketplace integration (Primary
  Region = AP South (Mumbai)).
  - Move the data. It is small (3,291 observations plus profile/portfolio rows). Use Settings → Export / re-import,
    `turso db shell … .dump`, or simply re-run NAVAll plus the backfills.
  - Then swap the `TURSO_*` env vars and redeploy.
  - Expected same-region statement latency is single-digit ms. **NOT VERIFIED: measure after the move** with the same
    script.
- **(b) Alternative.** Move the function to `iad1` instead.
  - This puts one ≈190 ms+ hop on each browser request rather than on each statement.
  - It also moves AMFI fetches to the US. ADR-0013 verified AMFI only from `bom1`.
  - Inferior to (a).
- (a) and (b) together do not remove the N+1 patterns below. 1,791 statements stay slow even at 5 ms (about 9 s), so
  RC-2 must be fixed regardless.

### RC-2. Discovery is O(schemes) round trips (VERIFIED)

Location: `backend/src/iip/services/discovery.py:164-176` (`build_universe`).

```python
for r in conn.execute("SELECT i.instrument_id, … FROM instruments i JOIN mf_schemes m …"):
    n = conn.execute("SELECT COUNT(DISTINCT observation_date) FROM observations WHERE series_id=? …",
                     (f"nav:{r['amfi_code']}",)).fetchone()[0]
```

- The harness counted **1,779 of these `COUNT` statements** for one discover call.
- For every scheme with at least `MIN_HISTORY_POINTS` (60) points, the loop also runs `_nav_series` (1 statement) and
  `inputs.fund_credit_facts` (≥1). Today that is almost none.
- Further per-row lookups:
  - FDs: `existing_fd_deposits`, `fd_institution_type`, `fd_entered_at`, at `discovery.py:249-290`.
  - T-bills: `tbill_quote`.
  - Bonds: `bonds.build_bond`.
- As history is backfilled, the number of eligible schemes grows, and so does the per-scheme cost (2–3 statements
  each).

Fixes (all keep identical results; verify with the existing differential/property tests):

1. **One aggregate for the gate:**
   `SELECT series_id, COUNT(DISTINCT observation_date) FROM observations WHERE series_id LIKE 'nav:%' AND superseded_by
   IS NULL AND quality_status IN ('ok','manual','fixture') GROUP BY series_id`.
   That is 1 statement instead of 1,779.
2. **One fetch for the NAV rows** of all eligible series:
   `… WHERE series_id IN (SELECT value FROM json_each(?)) ORDER BY series_id, observation_date`.
   The `json_each` pattern is already used in `routes_core.py:197`. Then group in Python and feed the unchanged
   `_nav_series` logic.
3. Batch `fund_credit_facts`, the FD `settings` keys (`key IN (…)`) and the T-bill quotes the same way.
4. Optional precomputation: maintain a `nav_points` count per series at ingestion time, so the gate is a column read.
5. **Never let a user-facing request run into the 300 s wall.**
   - Add a statement/time budget that **abstains** with an explicit `INCOMPLETE_CONTEXT`-style outcome instead of
     timing out.
   - A 504 also kills the instance. The next request in this audit was a 6.14 s cold start.

Expected result: about 10–15 statements per discover. That is about 4–6 s in `iad1` today, or well under 1 s in
`bom1` (estimate).

### RC-3. Two DB statements in the security middleware on every API request (VERIFIED)

`backend/src/iip/api/security.py:126-138`: `DbSessionStore.get` runs
`SELECT csrf, created, last_seen FROM web_sessions WHERE id_hash=?` and then
`UPDATE web_sessions SET last_seen=? …` for every authenticated `/api/*` call.

- That alone makes `/api/me` 1.3–1.5 s.
- `SecurityMiddleware.__call__` is `async`, and it calls this **synchronous, blocking** libSQL network I/O directly on
  the event loop. While one request waits about 0.8 s for its session, **every other request on that instance is
  stalled.** This matters with Fluid compute, where one instance serves concurrent requests.

Fixes:

- **(a)** Run the lookup with `await anyio.to_thread.run_sync(...)`. That is non-blocking and changes no behaviour.
- **(b)** Throttle the `last_seen` write, for example only when `now - last_seen > 300 s`. That saves 1 statement per
  request. The idle timeout of 8 h stays accurate to within 5 minutes.
- **(c)** Optionally, cache a verified session in-process for a short TTL (for example 30–60 s). That saves the
  `SELECT`.
  - Trade-off: a logout or revocation on another instance takes effect only after the TTL.
  - This is a security behaviour change, so it is a user decision (see the user decisions list).

### RC-4. The frontend is served by the Python function, uncached (VERIFIED)

- CDN request records for the last 6 h show every path on `"route":"/fastapi"`, `"pathType":"streaming_func"`,
  `"cacheResult":"MISS"`: 62 × `/`, 44 × `/assets/*`, 21 × `/favicon.ico`, 10 × `/robots.txt`.
- A live asset fetch (`/assets/index-BLecAd6p.js`, 277 KB) returned `cache-control: public, max-age=0,
  must-revalidate` and `x-vercel-cache: MISS`.
- The SPA catch-all in `backend/src/iip/api/app.py:241-248` serves these files with `FileResponse`.
- A missing asset (`/assets/does-not-exist.js`) answers **200 `text/html`**, the index fallback, instead of 404.
- Runtime logs at 17:54–17:56Z show **9 separate cold starts in about 90 s**. Each one logged "Installing runtime
  dependencies…", and they were triggered by `/onboarding`, `/favicon.ico` (twice), `/assets/index-B1mJ3xj6.css`,
  `/assets/Watchlist-moSCjtsv.js`, `/assets/kinds-wVEjnrvI.js`, `/api/data-health` (twice) and `/api/portfolios`.
  Loading a page starts parallel chunk requests. Each request that arrives while no instance is ready starts its own
  cold instance.
- Vercel's documented path is that files in a project-root `public/` directory are "serve[d] … from the CDN at the
  matching root URL paths".
  https://vercel.com/docs/frameworks/backend/fastapi (accessed 2026-10-15): "Place files in a `public/` directory at
  your project root. Vercel serves them from the CDN at the matching root URL paths."
- The same page says static mounts stay in the function when there is top-level middleware: "Top-level middleware:
  All static mounts and frontends stay in the function." That is this app's situation, because `SecurityMiddleware`
  wraps everything.

Fix:

1. In `scripts/vercel-build.sh`, copy `frontend/dist/*` into `public/` at the repo root.
2. Add `vercel.json` `rewrites` that send non-`/api` navigation paths to `/index.html`.
3. Add `headers` that reproduce the app's CSP, HSTS, nosniff, referrer, COOP/CORP and permissions-policy on CDN
   responses. **This step is required to keep threat-model parity. Verify it with the existing header tests against
   the live URL.**
4. Add `Cache-Control: public, max-age=31536000, immutable` for `/assets/*`, since the file names are content-hashed.

Assets are already served without authentication today (the SPA route is not `/api`), so moving them to the CDN does
not change exposure.

Expected result: zero function invocations for static files, and no parallel cold starts on page load.

### RC-5. Cold start costs about 6 s (install VERIFIED; split estimated)

- **Runtime dependency install.** Every new instance logged "Installing runtime dependencies…", "Prepared 40 packages
  in 1.82–2.03s", "Installed 40 packages in 53–71ms", "Runtime dependencies installed in 2.35–2.63s". Most of that is
  downloading scipy, numpy, casparser-isin (9.0 MiB), libsql (4.9 MiB), pypdfium2 (3.6 MiB) and rapidfuzz (3.0 MiB).
  - Vercel's Python builder externalises dependencies when the bundle exceeds 225 MB.
    `packages/python/src/dependency-externalizer.ts` in vercel/vercel (via `gh api`, accessed 2026-10-15) has:
    "AWS Lambda uncompressed size limit is 250MB, but we use 225MB to leave room …" and
    `LAMBDA_SIZE_THRESHOLD_BYTES = 225 * 1024 * 1024`, with the runtime directory `RUNTIME_DEPS_DIR = '/tmp/_vc_deps'`.
    That directory matches the log line "Creating virtual environment at: /tmp/_vc_deps".
  - Local (macOS arm64) installed sizes: scipy 82 MB, casparser_isin 48 MB, numpy 26 MB, cryptography 11 MB, libsql
    11 MB, pypdfium2_raw 8 MB. Linux wheels with `scipy.libs` / `numpy.libs` are larger. **Linux sizes NOT VERIFIED.**
  - Later cold starts can log "Using cached runtime dependencies" (18:06:42Z), and that cold `/api/health` still took
    **6.14 s**.
- **Imports.** `python -X importtime` (local) puts `iip.api.routes` at a cumulative 1.10 s, with an import-only rerun
  of 0.68 s.
  - scipy is imported eagerly through `iip.engine.stats.metrics` (`from scipy import stats as sps`, 0.16 s for
    `scipy.stats._stats_py`) and `engine/returns.py` / `engine/fixed_income.py` (`from scipy.optimize import brentq`).
  - casparser and pypdfium2 are already lazy, which is good.
  - Lambda first-import from `/tmp` is likely slower than this local figure. **NOT VERIFIED.**
- **Startup DB work at the iad1 distance.** On every instance start, `AppState.__init__` runs `migrate()`. On an
  already-migrated DB that is 4 statements:
  1. `CREATE TABLE IF NOT EXISTS schema_version`
  2. `SELECT … sqlite_master`
  3. `SELECT MAX(version)`
  4. `UPDATE ingestion_runs … mark_interrupted_runs`

  Add `libsql.connect` and `PRAGMA foreign_keys=ON`, and that is about 6 round trips, or **about 2.4 s at
  0.40 s/statement** (estimate). Statement 1 and the `UPDATE` are **writes on every cold start**.

Fixes:

1. **Get the bundle under 225 MB** so dependencies ship in the bundle. Options are user decisions:
   - Replace scipy's few uses with small, tested pure-Python routines: `brentq`, `minimize_scalar`, `chi2.sf`,
     `norm.cdf/pdf`, `t.sf`, `binomtest`. **This changes engine numerics, so it needs the existing oracle tests.**
   - Or check whether `casparser-isin` (48 MB) is really needed at runtime. `services/cas.py` replaces casparser's
     `isin_search` hook, but whether casparser imports `casparser_isin` unconditionally is **NOT VERIFIED.**
2. **Lazy-import scipy/numpy** inside the functions that use them, so `/api/me`, `/api/profile` and so on never pay
   for them.
3. **Make startup read-only.** Check `schema_version` with one `SELECT`, and run `migrate()` from a deploy step or an
   admin endpoint. Move `mark_interrupted_runs` to the job endpoints that need it.
4. Fluid compute is already on (`resourceConfig.fluid = true`). `defaultResourceConfig.elasticConcurrencyEnabled` is
   `false`. Whether Python in-function concurrency (beta per Vercel changelog title "Python support added to
   in-function concurrency beta") is available on Hobby is **NOT VERIFIED**. After RC-3a it would be safe to try.

### RC-6. Data-health has an N+1 over the source registry (VERIFIED)

`backend/src/iip/api/routes_core.py:331-347` runs one `SELECT … FROM ingestion_runs WHERE source_id=? ORDER BY
started_at DESC LIMIT 1` per `REGISTRY` entry. There are 21 entries, so the request is 25 statements and about
10.8 s.

Fixes:

- Use one window-function query:
  `SELECT * FROM (SELECT …, ROW_NUMBER() OVER (PARTITION BY source_id ORDER BY started_at DESC) rn FROM
  ingestion_runs) WHERE rn=1`.
- Alternatively, derive the per-source latest row from the 50 runs already fetched, plus one query for sources that
  are not in them.
- Add the index `CREATE INDEX ix_runs_source_started ON ingestion_runs(source_id, started_at)`. It is cheap now and
  matters as runs accumulate.
- The `observations GROUP BY quality_status` query scans all current observations. That is fine at 3,291 rows. A full
  5-year backfill of all schemes would make it millions of rows read per page view, so consider a maintained counter.
  Turso row-read billing effect: **NOT VERIFIED.**

### RC-7. Instrument detail makes 8 serial statements (VERIFIED)

`routes_core.py:216-237`:

- session ×2
- the instrument row
- 3 `_TERMS_QUERIES` (mf_schemes, bond_terms, deposit_terms), queried regardless of `kind`
- the observation series
- `latest_freshness`

Fixes:

- Query only the terms table that matches `kind` (saves 2 statements).
- Derive freshness from the series already fetched, if `latest_freshness` reads the same rows (check before changing).

Expected result: 4 statements, or 3 with the RC-3 throttle.

### RC-8. Connection handling (PLAUSIBLE, NOT VERIFIED)

- `AppState.conn` is **per thread** (`app.py:131-142`). FastAPI runs sync endpoints on a thread pool of up to 40
  threads, and each new thread opens its own remote libSQL connection: connect plus `PRAGMA foreign_keys=ON`.
- After an idle pause, `LibsqlConnection._run` (`db.py:226-253`) catches a dropped Hrana stream, reopens and retries.
  That is at least 2 extra round trips on the first statement after idle.
- Either effect would explain part of the 0.5–0.9 s fixed overhead seen in §2.
- Fix: a small bounded pool shared across threads, if libsql's connection objects allow it (**thread-safety NOT
  VERIFIED**). Also log `connect`/`reopen` counts and durations (no values) so the next audit can measure this
  directly.

## 4. Expected effect of the fixes (estimates, to be re-measured)

Model: `t ≈ 0.14 s + 0.6 s (fixed) + n × c`, where `n` is statements per request and `c` is the cost of one
statement. Today c ≈ 0.40 s. The bom1 value of c is a guess and is **NOT VERIFIED**; it is shown only for scale.

| Endpoint | n today | Today (measured) | n after RC-2/3/6/7 | iad1, c = 0.40 | bom1, assumed c ≈ 0.01 |
|---|---:|---:|---:|---:|---:|
| `/api/me` | 2 | 1.3–1.5 s | 1 (throttled write) or 0 (cached) | ≈0.6–1.1 s | ≈0.15 s |
| `/api/profile` | 3 | 1.8–2.3 s | 2 | ≈1.5 s | ≈0.2 s |
| `/api/data-health` | 25 | 10.5–11.3 s | 4 | ≈2.3 s | ≈0.2 s |
| `/api/instruments/{id}` | 8 | 4.1 s | 4 | ≈2.3 s | ≈0.2 s |
| `/api/discover` | 1,791 | 504 after 300 s | about 10–15 | ≈5–7 s | <1 s |
| Static assets | function, MISS | 0.17–0.23 s warm, plus a cold start if none is warm | CDN | CDN | CDN |
| Cold start | n/a | ≈6.1 s | n/a | ≈2–3 s | ≈1.5 s |

## 5. Suggested order of work

1. **RC-2 (discover batching + time budget).** Discovery is broken (504) in every region.
2. **RC-1 (Turso in `bom1`).** The biggest single multiplier. It needs a data move and env swap (user action in the
   Vercel/Turso dashboards).
3. **RC-3a/b (non-blocking, throttled session).**
4. **RC-4 (static files to CDN, with headers parity).**
5. **RC-6, RC-7 (small query fixes and index).**
6. **RC-5 (lazy scipy, read-only startup; bundle diet as a user decision).**
7. RC-8 instrumentation.

Each step should add or extend a test that **counts statements per endpoint**, using the same counting wrapper idea
on the libSQL local-file driver, so N+1 regressions fail CI.

## 6. Commands used (reproducible)

```bash
# timing (cookie jar reused; token never printed)
vercel curl /api/data-health -- -s -o /dev/null -b "$JAR" -w '%{http_code} %{time_total}\n'
vercel curl /api/discover -- -s -o /dev/null -b "$JAR" -X POST -H 'Content-Type: application/json' \
  -H 'Origin: https://investment-intelligence-pro.vercel.app' -H "X-IIP-CSRF: $CSRF" \
  --data '{"include_fixtures":false}' -w '%{http_code} %{time_total}\n'
# logs (Hobby keeps ~30 min of runtime logs)
vercel logs --environment production --since 30m --non-interactive
vercel logs requests --environment production --since 6h -n 3000 --non-interactive
# platform facts (non-secret fields only)
vercel api /v1/storage/stores            # -> metadata.region = iad1
vercel api /v9/projects/<projectId>      # -> resourceConfig.fluid = true
```

## 7. Sources (accessed 2026-10-15)

- Vercel, "Deploy a FastAPI app on Vercel", https://vercel.com/docs/frameworks/backend/fastapi
  - "Place files in a `public/` directory at your project root. Vercel serves them from the CDN at the matching root
    URL paths."
  - "Top-level middleware: All static mounts and frontends stay in the function."
- Vercel, "Using the Python Runtime with Vercel Functions", https://vercel.com/docs/functions/runtimes/python
  - "The standard Python bundle size limit is **500 MB** uncompressed."
  - "There is no automatic tree-shaking for Python."
- vercel/vercel source, `packages/python/src/dependency-externalizer.ts` (read via `gh api
  repos/vercel/vercel/contents/...`):
  - "AWS Lambda uncompressed size limit is 250MB, but we use 225MB to leave room for the Lambda layers"
  - `export const RUNTIME_DEPS_DIR = '/tmp/_vc_deps';`
- Economize, "AWS Latency: us-east-1 vs ap-south-1",
  https://www.economize.cloud/resources/aws/latency/us-east-1-vs-ap-south-1/
  - "AWS inter-region network latency from us-east-1 to ap-south-1 is 191.10 ms."
- Project facts: `vercel api /v1/storage/stores` (Turso store `database-blue-flower`, `metadata.region = iad1`) and
  production runtime/request logs (quoted above).

## 8. Side effects of this audit

- One `POST /api/discover` ran to the 300 s timeout on the server.
- A second `POST /api/discover` was started; its client was stopped after the first one hit the timeout. **The server
  side may have run up to 300 s.** Whether it completed and stored a `runs` row: **NOT VERIFIED.**
- No other writes beyond the normal session `last_seen` updates. No login was needed and no token was read.
