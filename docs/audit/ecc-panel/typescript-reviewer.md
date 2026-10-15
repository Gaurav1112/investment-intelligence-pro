# ECC panel: typescript-reviewer

Scope: `frontend/src`, covering TypeScript types, the API contracts in `lib/types*.ts`, and unsafe casts. This was a read-only review.

## Checks run
- `frontend/node_modules/.bin/tsc --noEmit -p frontend`: exit 0. `strict` and `noUncheckedIndexedAccess` are on. ESLint is not installed locally.
- Grep for `any`, `as unknown as`, non-null `!`, `dangerouslySetInnerHTML`/`innerHTML`, `@ts-` and `eslint-disable` in non-test sources. There is no `any`, no `@ts-ignore` and no raw HTML sink.
- Request and response types compared by hand against the backend (`services/analysis.py`, `services/instruments.py`, `services/cas.py`, `services/portfolio.py`). The bond input types, the CAS preview/apply shapes, TransactionIn, the Risk/Feasibility/Simulate/Scenario shapes and the Freshness union all match.

## Findings

### TS-1 (medium): the frontend never declares or renders the computed `real_return` and `yield_carry` results
- Backend: `backend/src/iip/services/analysis.py:798` adds `"real_return": _real_returns(...)` to every evaluable compare row. `analysis.py:1966` adds `"yield_carry": carry` to every OK forecast response. Both carry Explained values, or refusals such as `CPI_UNAVAILABLE`, `CPI_STALE`, `FUND_FACTS_UNAVAILABLE` and `STALE_DATA`.
- Frontend: `CompareRow` (`frontend/src/lib/types.ts:754-777`) has no `real_return`. `ForecastResponse` (`types.ts:1035-1065`) has no `yield_carry`. Because `api<T>()` is just `as T`, the extra keys are silently dropped. `grep -ri "real_return\|carry" frontend/src` finds no renderer.
- The UI still tells the user these results exist. `components/MacroInputs.tsx:354-355` says that without CPI, "real returns … are refused". `components/FundFactsPanel.tsx:285` says that without factsheet facts, "yield-carry ranges … are unavailable".
- Impact: a user who enters CPI or factsheet facts as told never sees the inflation-adjusted return or the debt-fund carry range. The refusals are not shown either (for example CPI_STALE, or a BER flag that says carry is overstated). For an Indian investor comparing FDs and debt funds, the real return is decision-relevant. known-limitations lists both as "IMPLEMENTED, NOT VERIFIED" at the API level and does not mention that the UI omits them.
- Fix: add `real_return?: Band<AnalysisExplained | Refusal>` to `CompareRow`. Add `yield_carry?: {status:"not_applicable";reason:string} | Refusal | {...}` to `ForecastResponse`. Render both through the existing `Metric` and `RefusalNote` components, and add a contract test.

### TS-2 (medium): `useApi` drops `loading` to false while a new request is still in flight, which shows a false empty state
- `frontend/src/lib/useApi.ts:21-30`. When `path` changes, or StrictMode re-runs the effect, while the earlier request is still pending:
  1. The cleanup calls `ctl.abort()`.
  2. The new effect calls `setLoading(true)` and `setData(null)` in the same commit.
  3. The aborted promise then settles in a later microtask, and its `.finally(() => setLoading(false))` runs.
  The result is `loading=false, data=null, error=null` until the new response arrives. There is no `if (!ctl.signal.aborted)` guard.
- Pages read that state as "nothing exists":
  - `pages/MfExplorer.tsx:243-255` shows "No stored scheme name contains …" or "No mutual fund schemes are stored yet" with a fetch button.
  - `pages/Alerts.tsx:335` shows "No alerts yet" or "No unacknowledged alerts". A critical alert can look absent if the toggle is flipped while the list is loading.
  - `pages/Risk.tsx:96-109` and `pages/InstrumentDetail.tsx:306` render nothing.
- The data shown is never stale, but the empty-state messages are false statements. The hook's own doc comment promises the opposite.
- Fix: guard all three callbacks with `if (ctl.signal.aborted) return;`, or set `loading=false` only for the current request.

### TS-3 (low): `as unknown as` makes the bond POST bodies type-unchecked
- `frontend/src/pages/FixedIncome.tsx:934` and `:1042`. The bodies are built as `Record<string, unknown>` (`commonBondFields`, `:774`), double-cast to `GsecIn`/`CorporateBondIn`, and passed to `send(body: unknown)` (`:897`). The cast is decorative: the compiler never checks a missing, misspelled or renamed field against `types-bonds.ts`.
- Today's keys match the backend `GsecIn`/`CorporateBondIn` (extra="forbid"), so the current failure would be a 422. A later rename on either side would compile cleanly, though. The only safety net is the server.
- Fix: type `commonBondFields` to return `Omit<BondQuoteFieldsIn, never>` (export the interface), build `GsecIn`/`CorporateBondIn` literals without a cast, and type `send` as `send<B>(body: B, …)`.

## Checked and not reported
- `api.ts`: the token comes from the fragment and the URL is cleaned up straight away. CSRF is in memory, a 401 locks the app, and errors map to `ApiError`. This looks correct.
- `format.ts`: money and percent formatting uses decimal strings and BigInt only, and the backend emits `format(x, "f")`.
- `FreshnessBadge` lookups are fed either by the backend-verified `FRESHNESS` union or by `safeFreshness`. The cast at `InstrumentDetail.tsx:286` widens a subset type and is safe.
- Analysis results in Simulator, Scenarios and Feasibility label themselves from the echoed `request`, so editing the inputs after a run does not mislabel the result.
- 422 handling (`validationErrors`) covers model-level errors through the `_` key.
