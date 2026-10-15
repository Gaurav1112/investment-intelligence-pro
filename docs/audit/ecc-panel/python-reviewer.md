# python-reviewer: backend/src/iip review

Scope: `backend/src/iip` (engine, data, store, supervisor, services, llm). The review was read-only. Checks run: `ruff check src/iip` (clean), `mypy src/iip` (clean, 83 files). Two findings were reproduced against a throw-away SQLite DB and in-process calls; the scripts lived in the session scratchpad, not in the repo.

Already-known items in `docs/operations/known-limitations.md` and `docs/audit/final-red-team-report.md` are not repeated here.

## Areas reviewed with no findings

- `engine/money.py`: `D()` rejects floats, bools and non-finite values; `from_float` uses `repr`.
- `engine/dates.py`: 30E/360, SEBI ACT/ACT, EDATE.
- `engine/deposits.py`: FD maturity, premature payout, DICGC aggregation.
- `engine/tax.py`: rule selection, `rates_as_of`, exemption pool, surcharge cap, cess.
- `engine/returns.py`: XIRR bracket scan with Decimal verification.
- `engine/candidates.py`: T-bill lots, FD, MF empirical band, exit load, tax.
- `services/portfolio.py`: FIFO, reconciliation, largest-remainder.
- `store/db.py`: per-thread connections, `BEGIN IMMEDIATE`, no nested `write_tx`.
- `services/cas.py`: `map_txn` sign checks.
- `data/imports.py`: XLSX float→Decimal via `repr`.
- `supervisor/synthesis.py` and `llm/adapter.py`: failure paths fall back to the template.

Exit-load rates and stored settings values are always written as strings, so `Decimal(json.loads(...))` never sees a float.

---

## PR-1 (HIGH): NAV pruning crashes after a same-day NAV correction, and every later NAVAll refresh then fails

`backend/src/iip/services/ingestion.py:269-284` (`prune_untracked_history`), called from `ingest_navall` at line 205.

To remove older NAVAll rows for an untracked scheme, the prune first runs:

```sql
UPDATE observations SET superseded_by = NULL
 WHERE superseded_by IN (SELECT obs_id FROM observations WHERE series_id=? AND source_id='amfi.navall' AND observation_date < ?)
```

`upsert_observation` (`store/observations.py:87-91`) only ever links a row to a newer row with the **same** series, date and source. So any row this UPDATE touches is a superseded row whose replacement is still current on that date. Clearing its `superseded_by` makes two rows current for one `(series_id, observation_date, source_id)`. That breaks the partial unique index `ux_obs_current` (`migrations/0001_initial.sql:106`), and the UPDATE raises before the DELETE can run.

**Reproduced** (temp DB, real functions):

1. Upsert nav:999 2026-10-13 = 10.0000 → inserted.
2. Upsert the same date = 10.0100 → corrected (row 1 now superseded by row 2).
3. Upsert 2026-10-14 → inserted.
4. `prune_untracked_history(conn, set())` → `IntegrityError: UNIQUE constraint failed: observations.series_id, observations.observation_date, observations.source_id`.

**Impact:**

- Same-day corrections happen in AMFI NAVAll. Once one exists for any untracked scheme, `ingest_navall` raises **after** `_store_observations` has run and **before** `_finish_run`.
- The run row is left `status='running'` and `POST /ingestion/navall` returns a 500.
- The poisoned pair stays in the DB, so every later refresh fails the same way.
- Pruning (the AMFI ToU data-minimisation control, RT-21) silently stops for good.

The same orphaned-run pattern applies to any unexpected exception between `_start_run` and `_finish_run`. Only `FetchError` and `DataError` are handled.

**Fix:**

- Delete the whole superseded chain together: drop the UPDATE, or limit it to rows that are themselves kept (`observation_date >= latest`). Deleting both rows of a pair in one statement does not breach the index.
- Wrap the post-fetch work in `try/except Exception` that calls `_finish_run(..., "failed", ...)` and re-raises.
- Add a regression test using the sequence above.

## PR-2 (MEDIUM): Liquidity ladder treats ELSS funds named only by scheme name as cash in T+3, ignoring the 3-year lock-in

`backend/src/iip/services/portfolio.py:773` calls `mf_lock_in_days(h.category)` without the scheme name. `engine/candidates.py:851-860` deliberately checks the **name** too ("ELSS", "Tax Saver", "Tax Saving"). The reason is documented: live AMFI data files some ELSS index funds under "Index Funds - Equity Funds", with ELSS appearing only in the name. `Holding.name` is available but not passed.

**Reproduced:** a holding named "XYZ ELSS Tax Saver Index Fund - Direct Growth" in category "Index Funds - Equity Funds", bought 2026-09-01:

- `_lot_days(...)` on 2026-10-15 returns `3`.
- `mf_lock_in_days(category, name)` returns `1095`.

**Impact:** the portfolio liquidity ladder (`_ladder`) puts locked-in ELSS units in the fastest bucket. That overstates how much money the user can raise for an emergency, which is a real-money decision input.

The same omission is at `services/analysis.py:795`: the compare row's `lock_in_days` shows 0 for these funds.

**Fix:** pass `h.name` at portfolio.py:773 and `b.name` at analysis.py:795. Add a test with a name-only ELSS holding.

## PR-3 (LOW): An MF candidate's `days_to_cash` ignores the lock-in

`backend/src/iip/engine/candidates.py:1179` sets `days_to_cash=settlement_days` even when `lock_in > 0`. The other kinds count the lock as time to cash: an FD with no penalty gets `tenure_days` (line 353), and a bond with no exchange exit gets time to maturity (line 806).

When the horizon is longer than the lock-in, an ELSS or solution-oriented fund passes the user's `max_days_to_cash` limit (`ranking.py:188`) as if it were redeemable in 3 days. It also ranks as highly liquid under the LIQUIDITY objective (`ranking.py:260`).

This is latent today: a 3-year-plus horizon needs ≥ 10 independent windows, which Direct-plan history (since 2013) cannot supply, so these candidates are refused with INSUFFICIENT_HISTORY first. It will surface when that gate or the data changes.

**Fix:** `days_to_cash = lock_in + settlement_days` (the lock-in runs from `as_of`, the purchase date).

## PR-4 (LOW): The ingestion `stored` count includes unchanged rows

`backend/src/iip/services/ingestion.py:163-181`: `_store_observations` increments `stored` for every row it passes to `upsert_observation`, whatever the result (`INSERTED` / `UNCHANGED` / `CORRECTED`). The count is shown in the `RunSummary` and in `register_schemes_by_isin`'s run row (`rows_ok=stored`). A re-run of an identical file reports thousands of rows "stored" when nothing was written, which misleads the Data health audit trail.

Each row is also its own `BEGIN IMMEDIATE`/`COMMIT` with `synchronous=FULL` (about 14k fsyncs per NAVAll run). That is slow, and a crash mid-run leaves a partial snapshot under one run id.

**Fix:** count `INSERTED`/`CORRECTED` separately, and batch the upserts in one `write_tx`.
