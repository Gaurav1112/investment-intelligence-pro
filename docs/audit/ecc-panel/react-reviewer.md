# ECC panel — react-reviewer

Scope: `frontend/src` (React 19.3, react-router 7, Vite 8). This was a read-only review. Nothing in the project was changed except this report.
Two findings were reproduced with throwaway vitest scripts. Those scripts lived in the session scratchpad, outside the repo.

## Summary

The React layer is in good shape:

- There is no `dangerouslySetInnerHTML`.
- Every `href` built from data is either `https://`-guarded or a static server constant (`registry.py`).
- `useApi` aborts its fetch on cleanup and clears data on a path change.
- Compare uses a sequence guard for its responses.
- The login token is stripped from the URL before any await.

The real defects are about the component lifecycle:

- Two of them appear only under `<StrictMode>`, which means during `make dev`. They were reproduced.
- One is a response-ordering race in Discovery that also affects the production build.

| ID | Sev | File:line | Title |
|---|---|---|---|
| R-01 | medium | frontend/src/lib/useApi.ts:39-40 | `useMutation` mounted-ref is never reset, so under StrictMode errors are swallowed and `pending` stays true forever |
| R-02 | medium | frontend/src/pages/Discovery.tsx:245-253 | Discovery POSTs have no abort or sequence guard, so a stale response can overwrite a newer one (fixtures toggle) |
| R-03 | low | frontend/src/App.tsx:34-41 | The AuthGate login effect has no cancellation, so under StrictMode a late `/api/me` 401 locks a successfully logged-in app |
| R-04 | low | frontend/src/pages/Risk.tsx:28-29, Compare.tsx:614-615 | URL-derived state is copied into `useState` once, so Back/Forward leaves the picker and form out of sync with the URL |
| R-05 | low | frontend/package.json | No ESLint or `eslint-plugin-react-hooks` in the toolchain, so hook-rule and dependency mistakes are not caught by `make check` |

---

## R-01 (medium): the `useMutation` mounted guard breaks under StrictMode

`frontend/src/lib/useApi.ts:39-40`

```ts
const mounted = useRef(true);
useEffect(() => () => void (mounted.current = false), []);
```

React 18 and 19 StrictMode (`main.tsx:10`) run each effect as setup, then cleanup, then setup again in development, and they keep refs across that cycle. The cleanup sets `mounted.current = false`. The second setup does not set it back to `true`. So in every component that uses `useMutation`, the ref stays `false` for the component's whole life.

`run()` then calls `setPending(true)` (`useApi.ts:43`) unconditionally. After that it skips both `setError(e)` (`:48`) and `setPending(false)` (`:51`).

**Reproduced** with a StrictMode render and a mocked 422 from `fetch`. The output was `pending= true error= none`. The same component without StrictMode printed `pending= false error= ERR`.

**Impact under `make dev`:**

- **Onboarding** (`pages/Onboarding.tsx:233-267`): a rejected profile save shows no error, because `save.error` is never set. The Save button stays disabled on "Saving…" until reload. A successful save also leaves the button stuck.
- **Fund facts** (`components/FundFactsPanel.tsx:187,251-257`) and the **CPI / T-bill inputs** (`components/MacroInputs.tsx:93,150-156,242,272-278`) behave the same way. A validation failure on a value that drives credit-floor and rate-shock analysis gives no feedback.

The production build does not double-invoke effects, so `make run` is not affected. The unit tests render without StrictMode, so they cannot catch this.

**Fix:** set `mounted.current = true` in the setup:

```ts
useEffect(() => {
  mounted.current = true;
  return () => { mounted.current = false; };
}, []);
```

Alternatively, drop the guard. React 18+ no longer warns on setState after unmount. Add one StrictMode test.

## R-02 (medium): Discovery has a request race

`frontend/src/pages/Discovery.tsx:245-253`

```ts
const run = useCallback(() => {
  setLoading(true); setError(null);
  api<DiscoveryResult>("/api/discover", { method: "POST", body: { include_fixtures: includeFixtures } })
    .then(setData).catch(setError).finally(() => setLoading(false));
}, [includeFixtures]);
useEffect(run, [run, status]);
```

This code has no `AbortController`, no sequence counter and no cleanup. The page keeps rendering the previous `data` while a request is in flight (`:255` only shows the spinner when `!data`). So the "Include fixtures" checkbox (`:284`) can be clicked again while the first POST is still running.

**Scenario:**

1. The user ticks the checkbox, which sends POST A with `include_fixtures: true`.
2. The user quickly unticks it, which sends POST B with `false`.
3. A is slower, because it orders more instruments, and resolves last.

The page then shows the ordering that includes fixtures while the checkbox reads "off". `DiscoveryResult` does not echo `include_fixtures` (`lib/types.ts:132` only has `contains_fixtures`), so nothing on screen reveals the mismatch.

The same race fires on every change of the profile context. `ProfileProvider.reload()` makes `status` go non-null, then null, then non-null, so two POSTs race after each save. This race affects the production build too.

The `finally` from the older request also clears `loading` while the newer request is still pending.

**Fix:** use the same `seq` ref pattern Compare already uses (`Compare.tsx:622-655`), or an `AbortController` that the effect cleanup aborts. Consider echoing `include_fixtures` in the response.

## R-03 (low): the AuthGate login effect can lose to its StrictMode twin

`frontend/src/App.tsx:34-41`

The effect has no cleanup or ignore flag. Under StrictMode the first run reads the `#login=` fragment, removes it and calls `login(token)`. The second run finds no fragment and calls `restoreSession()`. That `/api/me` request was sent before the session cookie existed, so it returns 401 and calls `setState("locked")`.

Whichever promise settles last wins.

**Reproduced** with StrictMode, a login response delayed 20 ms and an `/api/me` 401 delayed 60 ms. The app ended on the locked screen even though login succeeded. The token is single-use, so the user has to restart to get a new link.

This happens only in dev and depends on timing. The production build is not affected. The `epoch`-driven re-login path (`:42-48`) has the same unguarded pattern if two hash changes overlap.

**Fix:** keep a `let cancelled = false` flag in the effect, return `() => { cancelled = true; }`, and skip `setState` and `setError` when the flag is set.

## R-04 (low): URL state copied into local state does not follow Back/Forward

- `frontend/src/pages/Risk.tsx:28-29`: `useState(id ? {...} : null)` and `useState(horizon)`.
- `frontend/src/pages/Compare.tsx:614-615`: `useState(urlAmount)` and `useState(urlDate)`.

Both pages push a history entry on every change (`setParams(p)` with no `replace`). After Back, the fetch follows the URL but the picker or form fields still show the old values.

- On Risk, the picker says "Selected: B" above metrics for fund A. The result header does name the fund (`Risk.tsx:147`), which limits the harm.
- On Compare, the amount and date inputs no longer match the request in the URL, and pressing Compare re-pushes the edited values.

**Fix:** derive these values from `params` during render, or sync them with a key on the URL value.

## R-05 (low): no hooks linting

`frontend/package.json` has no ESLint and no `eslint-plugin-react-hooks`, and `make check` runs only `tsc` and `vite build`.

There is one intentional deviation: `Compare.tsx:656` uses `[key]` instead of `ids/urlAmount/urlDate`. It is correct because `key` encodes all three, but it is unverified.

The lint rules would not have caught R-01 or R-03, which are StrictMode lifecycle bugs. Adding `react-hooks/rules-of-hooks` and `exhaustive-deps`, plus one StrictMode render in the test setup, would cover both classes of bug.

## Checked and clean

- `dangerouslySetInnerHTML`: not used anywhere.
- External links (`FundFactsPanel.tsx:45`, `FixedIncome.tsx:200`, `Methodology.tsx:36`, `Evidence.tsx:15`) all check `startsWith("https://")` and use `rel="noreferrer noopener"`.
- `DataHealth.tsx:76` `terms_url` comes from static constants in `backend/src/iip/data/registry.py`.
- No tokens are kept in `localStorage`. The CSRF token is held in module memory. The CAS password is cleared from state before the upload await (`CasImport.tsx:102`).
- `useApi` cancels with `AbortController`, clears data on a path change, and its 401 handling is correct. The `AuthGate` `key={epoch}` remount is correct.
- Compare is protected against races by its `seq` ref. CasImport and Overview import are protected by remounting under `key={portfolio_id}`.
- Index keys: `FixedIncome.tsx:1155` call rows are controlled inputs, and their server errors are keyed by the same index. `DotPlot` and `AiWording` lists are static.
