# fastapi-reviewer: backend/src/iip/api and backend/src/iip/services

Reviewer: ECC `fastapi-reviewer` (read-only). Date: 2026-10-15.
Scope: FastAPI routes, request models, dependency use and error handling in `backend/src/iip/api` and the service functions they call in `backend/src/iip/services`.
I checked every finding against `docs/operations/known-limitations.md` and `docs/audit/final-red-team-report.md`. None of them is listed in either document.

## Findings

### [HIGH] F1. Two concurrent applies of the same import batch store every transaction twice
Files: `backend/src/iip/services/portfolio.py:571-608` (CSV/XLSX), `backend/src/iip/services/cas.py:571-608` (CAS). Routes: `api/routes_portfolio.py:86-94` and `api/routes_cas.py:130-137`.

**Issue:** `apply_holdings_import` and `apply_cas_import` read the batch and run their single-use checks before any write transaction starts. Those checks are `status != "previewed"` and `_already_applied(...)`. The pre-change backup then runs, which takes time and widens the race window. Only after that does `write_tx` (BEGIN IMMEDIATE) begin.

Inside the transaction, neither function checks the batch status again. FastAPI runs these sync routes in a thread pool, and `AppState.conn` gives each thread its own connection. Two requests (a double click, a retry, or a second tab) can therefore both pass the checks. They then serialise on the write lock, and each one inserts every pending row.

The FIFO consistency check does not catch the duplicate. A buy-only CSV batch never oversells, and a CAS batch only fails if its sells happen to exceed the doubled holdings.

**Reproduced:** two threads applying one 2-row preview, each with its own connection, using the route's `pre_change` shape:
```
results: [2, 2]
transactions in portfolio: 4 expected 2
```
**Impact:** Holdings are silently doubled. Cost basis, XIRR, the maturity ladder, DICGC exposure and alerts are all wrong, and every later decision is built on them.

**Fix:** Inside `with write_tx(conn):`, re-read the batch row first. Then re-check `status == "previewed"` and `_already_applied`, and raise `ALREADY_APPLIED` if either check fails. A simpler alternative is an atomic claim: `UPDATE settings SET value_json=? WHERE key=? AND json_extract(value_json,'$.status')='previewed'`, then require `rowcount == 1`. Add a test that runs two concurrent applies.

### [MEDIUM] F2. Unhandled exceptions reach uvicorn, which logs the full traceback and message
Files: `backend/src/iip/api/app.py:107-111`, `backend/src/iip/api/security.py:205-208`, `backend/src/iip/api/__main__.py:21-29`.

**Issue:** The `@app.exception_handler(Exception)` handler sends a clean 500 response and logs only the exception class (SEC-21). However, Starlette's `ServerErrorMiddleware` always re-raises the exception after calling that handler. `SecurityMiddleware` catches only `_BodyTooLarge`, so the exception reaches uvicorn. Uvicorn logs `"Exception in ASGI application"` with `exc_info`, which includes the full traceback and the exception message.

No redaction filter or `log_config` exists anywhere in `src/iip`; a grep for `addFilter`, `dictConfig`, `basicConfig` and `log_config` returns nothing. This contradicts C-13: "Exception messages ... reduced to their class", plus the redaction processor.

**Reproduced:** a route that raises `ValueError("units=123.45 amount=₹9,87,654")` gives a 500 with only `code` and `request_id`. The exception still escapes `SecurityMiddleware` to the server, which logs its message.

**Impact:** Any service or parser exception whose message contains user values ends up in stderr or terminal logs in clear text. Those values could be amounts, ISIN/folio text from a CAS, or SQL fragments.

**Fix:** Inside `SecurityMiddleware.__call__`, catch `Exception` around `await self.app(...)`. If the response has already started, swallow it, because the app's handler has already logged the class and request_id. Also, or instead, pass a `log_config` to `uvicorn.run` that installs a filter on `uvicorn.error`, stripping `exc_info` and the message down to the class. Add a SEC-21 test that asserts nothing escapes the ASGI app.

### [MEDIUM] F3. NAV backfill makes up to about 160 unpaced AMFI requests per call, with no rate limit and a circuit breaker that never carries over
Files: `backend/src/iip/api/routes_core.py:172-190` (backfill) and `routes_core.py:157-170` (navall). Related: `backend/src/iip/services/ingestion.py:293-320`, `:323-353`.

**Issue:**
- `POST /api/ingestion/backfill/{amfi_code}` has no rate limit, unlike SEC-86 on the NAVAll route.
- `discover_fund_house_id` probes ids 1..80 one request at a time. `backfill_history` makes one request per 90-day window, so a 20-year backfill is about 81 windows.
- Both functions accept `pause=`, but no caller passes it (a grep for `pause=` finds nothing), so every request is sent back-to-back.
- Each route builds a fresh `Fetcher()`, which brings a fresh `CircuitBreaker`. Breaker state from failures therefore never carries over between requests, and the per-source breaker (reliability-design §4.4) cannot protect the upstream from repeated clicks.
- The NAVAll limit is check-then-set on `st.last_navall_refresh` with no lock (`routes_core.py:162-167`). Two concurrent requests can both pass it.

**Impact:** This breaks C-16, which says upstream politeness means "we must not hammer AMFI/RBI". A user who clicks repeatedly, or a looping SPA, can trigger hundreds of requests and risk the IP being blocked by the primary NAV source.

**Fix:**
- Apply the same per-source 15-minute limiter to backfill, keyed by the `amfi.navhistory` source.
- Pass `pause=time.sleep` from the route, or default it in the service.
- Keep one `Fetcher` or breaker on `AppState`, or persist the breaker state, and reuse it.
- Guard the limiter's check-and-set with a lock.

### [LOW] F4. The streamed body cap answers 500/400 instead of 413, and the per-route JSON cap is missing
Files: `backend/src/iip/api/security.py:205-208,229-242`, `backend/src/iip/api/routes_cas.py:95`.

**Issue:** `_BodyTooLarge` is raised inside `receive()`, so the app sees it first.
- **CAS route:** `await request.body()` is not wrapped, so `ServerErrorMiddleware` turns the exception into a 500 `INTERNAL_ERROR` and logs it as an unhandled error. `SecurityMiddleware` then calls `_reject` after a response has already started, which is an ASGI protocol violation.
- **JSON and `UploadFile` routes:** FastAPI wraps body parsing and returns 400 `"There was an error parsing the body"`.

The threat model at line 210 requires a 413. Line 312 also specifies 1 MiB for JSON bodies, but a single 5 MiB cap applies to every route.

**Reproduced:** with `max_body_bytes=1000` and a 2,500-byte chunked body (no Content-Length): `import-cas` returns 500 `INTERNAL_ERROR`, `holdings/import` returns 400, and `/api/portfolios` returns 400.

**Impact:** Oversized bodies are still refused, so no data is affected. The problems are spurious internal-error logs, a confusing error for the user, and a double `http.response.start`.

**Fix:** In the CAS route, catch the body-size condition, or make `_BodyTooLarge` a Starlette `HTTPException(413)` subclass that the handlers pass through. In `SecurityMiddleware`, track whether a response has started and send a 413 only if it has not. Add a lower cap for `application/json` routes.

### [LOW] F5. Deleting a manual instrument that a portfolio holds returns an opaque 500
Files: `backend/src/iip/api/routes_core.py:150-154`, `backend/src/iip/services/instruments.py:413-424`.

**Issue:** `transactions.instrument_id REFERENCES instruments(instrument_id)` has no ON DELETE action (`0001_initial.sql:124`), and `foreign_keys=ON` is set. Deleting a held FD, G-sec or T-bill therefore raises `sqlite3.IntegrityError`, which the route does not map.

**Reproduced:** `delete_instrument` on a held manual FD raises `IntegrityError FOREIGN KEY constraint failed`. The rollback works correctly, so no data is lost.

**Impact:** The user gets `INTERNAL_ERROR` instead of an actionable message, and per F2 the traceback reaches the logs.

**Fix:** In `delete_instrument`, check for referencing transactions inside the transaction and return a 409 `INSTRUMENT_HELD` (or `False` with a distinct reason).

## Checked and not reported
- **SQL:** parameterised throughout. The only dynamic identifiers are asserted constants (`_COUNT_SQL`, `_DELETE_SQL`), and the LIKE input is escaped.
- **Request models:** every write route uses a Pydantic model with `extra="forbid"`. Decimals are refused when sent as floats, and import confirmation requires the SHA-256.
- **Session and CSRF:** checked in the ASGI middleware before routing. The login uses `hmac.compare_digest` and is rate-limited. No CORS headers are sent. The cookie is `secure=False` on loopback by design.
- **Blocking I/O:** the async CAS route offloads its work with `run_in_threadpool`. Every other route is sync, so FastAPI runs it in the thread pool. The SQLite connections are per thread and use `check_same_thread=False`.
- **Docs:** `/api/docs` and OpenAPI are disabled outside dev/test.
- **LLM config route:** `api_key_env` is validated in `llm.config` (env-name regex, `IIP_` names refused). Cloud URLs are allowlisted.

## Tests checked
- `backend/.venv/bin/ruff check src/iip/api src/iip/services`: all checks passed.
- `backend/.venv/bin/mypy src/iip/api src/iip/services`: no issues in 27 files.
- `backend/.venv/bin/pytest -q tests/api`: all 81 passed.
- Throwaway repro scripts in the session scratchpad (not in the repo): the concurrent apply race (F1), exception escape (F2), chunked oversize bodies (F4) and the FK delete (F5).

## Residual risk
- I did not trace every service exception message in `analysis.py` (2,301 lines) or `discovery.py` for user values. F2's real-world severity depends on that.
- The frontend may debounce the apply button, but I did not verify this, and F1 is a backend integrity bug either way.
- I did not check whether uvicorn stderr is persisted anywhere in the documented run modes (`make run` or launchd).
