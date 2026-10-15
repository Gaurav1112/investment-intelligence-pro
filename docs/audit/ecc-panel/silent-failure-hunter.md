# Silent-failure-hunter review (ECC panel)

Date: 2026-10-15. Scope: `backend/src/iip`, `frontend/src`. Read-only review; no code changed.
Baseline: `docs/operations/known-limitations.md` and `docs/audit/final-red-team-report.md` were read first. Items already listed there are not repeated unless the code is worse than the document says.

## Overall

Exception handling is mostly disciplined. Every `except EngineError` in `engine/candidates.py` turns the failure into an `_ineligible(...)` ledger entry that carries its reason. Analysis refusals carry codes. The broad `except Exception` blocks (`supervisor/synthesis.py:100`, `services/cas.py:211`, `data/imports.py:306`, `api/routes_cas.py:72`, `api/security.py:119`) are deliberate, and each one maps to an explicit refusal. The frontend's bare `catch {}` blocks only reformat timestamps or hostnames for display. The real problems are fallbacks that hide missing data, and failures that are recorded in one place but not in another. They are listed below, most severe first.

---

## F1: HIGH. The FD deposit-insurance (DICGC) check in discovery and compare ignores your recorded FDs and treats missing "existing deposits" as ₹0

- `services/discovery.py:257-260`: `existing = ... if existing_row else D("0")`
- `services/analysis.py:343-345`: `_existing_deposits` returns `ZERO` when the setting is missing
- `services/instruments.py:60`: `existing_deposits_at_institution: Decimal = Field(default=Decimal(0), ge=0)`, and the UI form also defaults to `"0"` (`frontend/src/pages/FixedIncome.tsx:513`)
- `engine/candidates.py:300-302, 352`: `fully_insured = dicgc_eligible and exposure <= DICGC_LIMIT`, `credit_safe = ...`, `loss_frequency=ZERO if credit_safe else None`

**Issue:** For each FD candidate, the insurance check uses only the one number that was typed when that FD rate was entered. That number defaults to 0 and is never refreshed. The check never looks at the FDs the user actually records in their *actual* portfolios at the same institution. (`services/portfolio.py::_dicgc` does aggregate those, but only for the portfolio view.) A missing or zero value raises no flag. Each FD id (`fd:<type>:<slug>:<tenure>d`) also reads only its own `fd.existing:` key, so discovery never sums across FDs at the same bank. That contradicts `known-limitations.md` ("…are summed. … it never understates it"). The summing happens only in the allocation `_dicgc` at `analysis.py:1630`.

**Impact:** Suppose a user already holds ₹5 L at Bank X, recorded as transactions, and enters a new Bank X card rate without filling in the optional field. The FD is then evaluated as fully DICGC-insured, gets `loss_frequency = 0`, and can pass capital-preservation objectives with no `EXCEEDS_DICGC_LIMIT_AT_THIS_BANK` flag. This is real exposure to uninsured principal.

**Fix:**
- Compute other deposits at the same institution from the actual-portfolio FD positions (as `portfolio._dicgc` does), plus the manual figure.
- When neither source is present, flag `EXISTING_DEPOSITS_NOT_RECORDED` and do not set `loss_frequency = 0`.
- Correct the known-limitations row.

## F2: MEDIUM. The stale-data alert silently skips every holding of a portfolio whose ledger cannot be replayed

- `services/alerts.py:86-90`
  ```python
  try:
      positions = pf.fifo_positions(pf.load_txns(conn, p["portfolio_id"]))
  except pf.PortfolioError:
      continue
  ```

**Issue:** If an actual portfolio's transactions fail FIFO replay (oversell or an inconsistent book), its holdings drop out of the "stale data for held instruments" check with no record. The portfolio is added to `skipped_portfolios` only by the maturity/HHI path (`alerts.py:157-158`). That path returns early when both of those rules are off (`alerts.py:150-151`).

**Impact:** The user sees "N conditions met" and gets no warning that NAVs for real holdings are stale, which is exactly the case where the rule matters.

**Fix:** Return the skipped portfolio ids from `_held_and_watched` and merge them into `skipped_portfolios` (or emit a `critical` alert such as `INCONSISTENT_BOOK`).

## F3: MEDIUM. The CAS preview reports "no stored instrument has this ISIN" when the AMFI lookup actually failed

- `services/ingestion.py:230-233`: `except (FetchError, DataError): return {}`
- `services/cas.py:381-383`: `resolve_isins(unknown)`, return value ignored
- UI text: `frontend/src/pages/CasImport.tsx:16`: `"unmatched: no stored instrument has this ISIN"`

**Issue:** If the machine is offline, the circuit breaker is open, or AMFI returns an unparseable file, held Regular-plan and IDCW schemes come back as `UNKNOWN_ISIN`. That is the same code used when AMFI genuinely does not list the ISIN, and the preview carries no warning that the lookup never ran.

**Impact:** The user may apply the import with those schemes dropped, concluding the scheme is unsupported, when a retry would have matched it. The reconciliation then shows `UNMATCHED` with a misleading cause.

**Fix:** Have `register_schemes_by_isin` return or raise a lookup status. Add a preview warning ("AMFI lookup failed: <FetchError class>; unmatched ISINs were not checked") and use a distinct reason such as `ISIN_LOOKUP_FAILED`.

## F4: MEDIUM. Ingestion runs that crash after the fetch stay `running` forever and never trigger the "ingestion failed" alert

- `services/ingestion.py:192-211` (`ingest_navall`): only `fetch` and `parse_navall` are inside `try ... except (FetchError, DataError)`. These run outside it with no `_finish_run`: `_validated`, `_store_schemes`, `_store_observations` (row-by-row upserts with no surrounding transaction), `prune_untracked_history` and `tracked_scheme_codes`.
- `services/alerts.py:228-229`: the alert rule selects only `status='failed'`.

**Issue:** Anything unexpected after the fetch, such as a validator `ValueError`, `sqlite3.OperationalError: database is locked`, or a constraint error, goes to the generic 500 handler. The run row stays `running`, possibly with some observations already stored. No startup sweep marks abandoned runs. The DataHealth page shows "RUNNING (or interrupted)", but the user's "ingestion run failed" alert never fires.

**Impact:** A recurring post-fetch failure looks like "in progress" indefinitely, and NAV data quietly stops updating until a staleness alert eventually catches it.

**Fix:** Wrap the whole body after `_start_run` in `try/except BaseException`, record `failed` with the error class, then re-raise. Also mark `running` rows older than N minutes as `interrupted` at startup and include that status in the alert query.

## F5: LOW. Discovery silently drops T-bills with no usable yield; Compare reports them

- `services/discovery.py:214-215`: `if r is None: continue  # no usable yield observation at all ...`
- Contrast `services/analysis.py:313-315`: `MISSING_DATA: no yield observation stored`

**Issue:** A T-bill the user entered whose only quotes are `rejected`, `suspect` or `stale` (or that has none) is absent from the discovery universe and from the exclusion ledger. It is not counted in `skipped_no_history` either. The same instrument appears in Compare as `MISSING_DATA`.

**Impact:** The user cannot tell "not suitable" from "never evaluated". This goes against the ledger's purpose of showing every exclusion with its reason.

**Fix:** Append `cb._ineligible(iid, name, Tier.T1, ["MISSING_DATA: no usable yield observation"], amount)` instead of `continue`.

## F6: LOW. Every XIRR engine failure is labelled "not enough cash flows"

- `services/portfolio.py:935-936`
  ```python
  except EngineError as exc:
      base["explain"] = _unavailable("xirr", "XIRR", f"{type(exc).__name__}: not enough cash flows")
  ```

**Issue:** `engine/returns.py` raises `NumericalError` when brentq fails (line 469) or when a root fails the Decimal check (line 477), and `InvalidInput` for bad dates (line 329). All of them are reported as "not enough cash flows".

**Impact:** A solver or verification failure on a portfolio with plenty of cash flows is presented as a data shortage, which hides a real numerical problem.

**Fix:** Use `str(exc)` or map by `exc.code`, and keep "not enough cash flows" only for the fewer-than-2-flows `InvalidInput`.

## F7: LOW. A tax-rule load failure is swallowed with no reason, no log, and is cached for the life of the process

- `api/routes_core.py:26-31`
  ```python
  @lru_cache(maxsize=1)
  def tax_rules() -> tx.TaxRuleSet | None:
      try:
          return load_tax_rules()
      except Exception:  # a broken rule file must ABSTAIN, not crash the API
          return None
  ```

**Issue:** Abstaining is correct. However, the error class and message (YAML error, validation error on rule X, or an `OSError`) are discarded and never logged. `lru_cache` also keeps the `None` until restart. The UI only learns `tax_rules_loaded: false` (`routes_core.py:218`), and the alert says "could not be loaded" with no cause.

**Impact:** All after-tax analysis abstains, and neither the user nor the logs show why. A corrected rule file has no effect until restart, and nothing says so.

**Fix:** Log `error_class` and the loader's message (rule files contain no PII). Cache the error and expose it as `tax_rules_error`, and avoid caching `None` permanently (or document that a restart is required).

## F8: LOW. The generic 500 handler logs only the exception type: no traceback and no route

- `api/app.py:107-111`: `log.error("unhandled error request_id=%s type=%s", request_id, type(exc).__name__)`

**Issue:** SEC-21 requires only that the *response body* carry no traceback. The server log keeps no stack, route or method either, so a user who reports a `request_id` gives nothing that can be traced.

**Impact:** Any unexpected failure, including the F4 paths, cannot be diagnosed after the fact.

**Fix:** Log `request.method`, `request.url.path` and the stack frames (file:line:function only, with no locals or message if PII is a concern) at `ERROR`.

## F9: LOW. The Discovery page has no request ordering or abort, so an older response can overwrite a newer one

- `frontend/src/pages/Discovery.tsx:245-252`: `api(...).then(setData).catch(setError)`, with no `AbortController` or sequence check. It re-runs on each `status` or `includeFixtures` change, and old `data` stays rendered while loading.

**Issue:** If the profile changes while an earlier `/api/discover` request is still in flight, whichever response arrives last wins. `useApi` avoids this (`lib/useApi.ts`), but this page does not use it.

**Impact:** The page can show a ranking for previous constraints after the user changed them. This is partly mitigated because the header shows the response's own amount and date.

**Fix:** Use an `AbortController` (or a request counter) as `useApi` does.

---

## Checked and not reported (deliberate and recorded)

- `supervisor/synthesis.py:97-102`: LLM failure falls back to the template and is recorded in `rejected`.
- `services/cas.py:211`: parser errors are mapped to fixed refusal codes (no password leak).
- `api/security.py:119`: a malformed cookie becomes "no session", which then gets a 401.
- `engine/candidates.py`: every `except EngineError` yields an ineligible candidate with its reason.
- `services/discovery.py:467`: display-only fallback to the raw string.
- `services/ingestion.py:305`: probe misses are expected, because ids are discovered by probing.
- `store/db.py` / `store/encrypted_backup.py`: these roll back or clean up, then re-raise.
- Frontend `catch {}` blocks in `FundFactsPanel`, `MacroInputs`, `DataHealth`, `InstrumentDetail`, `Methodology`, `FixedIncome`, `Evidence`: display formatting only. `lib/api.ts::safeJson` falls back to `REQUEST_FAILED` with the HTTP status kept.
