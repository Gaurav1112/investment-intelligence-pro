# Audit: frontend performance (wave 1)

Date: 2026-10-15. Scope: `frontend/` (React 19 + Vite 8 + recharts 3 + d3-scale), plus the two backend behaviours that
shape frontend performance (how static assets are served, and what `GET /api/instruments/{id}` returns).
Nothing in the repository was changed; the build was run into a scratch `--outDir`, so `frontend/dist` is untouched.

Status labels: **VERIFIED** (measured or read in code during this audit), **NOT VERIFIED** (reasoned, not measured),
**REQUIRES CONFIGURATION** (needs a deploy-setting change to confirm or fix), **BLOCKED**.

## Why this matters for the "signals" goal

The aim is a tool that gives buy/sell/hold signals for mutual funds and equities. Signal screens are list-heavy: many
instruments, each with a long price history, a backtest and a freshness badge. The current frontend works fine at
today's sizes (a few portfolios, a few hundred schemes). It will slow down badly once it shows dozens of instruments,
each with 10+ years of history. Three patterns cause this, and every signal page would copy them: (1) the detail
endpoint sends the whole history every time, (2) one request per table row, and (3) no client cache. Fix these before
building signal pages, not after.

## Measurements

### Production build (VERIFIED)

Command: `node --run build -- --outDir <scratch>/dist --emptyOutDir` in `frontend/`. Type-check and build took 1.0 s
wall-clock. The build is deterministic: its hashes match what the live Vercel site serves (`index-BLecAd6p.js`).

| Chunk | Raw | gzip -9 | Loaded by |
|---|---:|---:|---|
| `InstrumentDetail-*.js` (contains recharts + its redux/immer deps) | 346.5 kB | 97.2 kB | `/i/:id` |
| `index-*.js` (React, react-dom, router, shell) | 277.2 kB | 87.9 kB | every page |
| `Overview-*.js` | 51.4 kB | 13.9 kB | `/` (landing) |
| `FixedIncome-*.js` | 49.1 kB | 13.2 kB | `/fi`, and also `/` and `/i/:id` (see F4) |
| `Scenarios-*.js` | 24.4 kB | 7.1 kB | `/scenarios` |
| `Compare-*.js` | 21.0 kB | 6.9 kB | `/compare`, also `/risk`, `/scenarios` |
| `DataHealth-*.js` | 20.4 kB | 5.8 kB | `/data-health` |
| `linear-*.js` (d3-scale) | 18.9 kB | 7.7 kB | Compare, DotPlot, InstrumentDetail |
| `index-*.css` | 29.2 kB | 7.0 kB | every page |
| Inter variable fonts (7 unicode-range subsets) | 218.5 kB total | (woff2) | browser fetches only the subsets it needs |

The whole `dist/assets` folder is 1,199,576 bytes. Route-level code splitting is already in place: all 16 pages use
`React.lazy` (`frontend/src/App.tsx:11-26`). recharts appears **only** in the InstrumentDetail chunk (the index chunk
has 0 matches for "recharts"). The baseline is good.

JS needed per route on a cold load (gzip, summed from the table above; NOT VERIFIED in a browser):
- `/` Overview: about 120 kB (index 87.9 + Overview 13.9 + FixedIncome 13.2 + Watchlist 3.5 + small shared chunks).
- `/i/:id` instrument page: about 212 kB (index 87.9 + InstrumentDetail 97.2 + FixedIncome 13.2 + MfExplorer 6.3 + linear 7.7).

### Hosted delivery (VERIFIED with curl against https://investment-intelligence-pro.vercel.app, 2026-10-15)

| Request | Status | cache-control | x-vercel-cache | encoding | time_total |
|---|---|---|---|---|---:|
| `/` | 200 | `public, max-age=0, must-revalidate` | MISS | — | — |
| `/assets/index-BLecAd6p.js` (3 repeats) | 200 | `public, max-age=0, must-revalidate` | MISS ×3 | br (90,359 B) | 0.148–0.159 s |
| `/assets/InstrumentDetail-DsViurW3.js` | 200 | same | MISS | br (98,527 B) | 0.152 s |
| `/assets/inter-latin-wght-normal-*.woff2` | 200 | same | MISS | br | 0.151 s |
| `/assets/index-*.js` with `If-None-Match` | 304 | — | — | — | 1.131 s |
| `/api/me` (no session) | 401 | `no-store` | MISS | — | 0.134 s |

### Instrument-detail payload (VERIFIED by construction; NOT VERIFIED against real stored data)

There is no local database on this machine (`~/.iip` holds no `.db`), so I could not measure a real response. Instead
I built a synthetic payload with the exact row shape that `get_instrument` returns
(`backend/src/iip/api/routes_core.py:216-238`): `observation_date, value, source_id, source_url, retrieved_at,
quality_status`. Each row uses the real AMFI history URL format (`backend/src/iip/data/registry.py:505-506`).

| Points (≈ business days) | Raw JSON | gzip |
|---:|---:|---:|
| 250 (1 year) | 72.8 kB | 1.9 kB |
| 2,500 (10 years, the backfill default `years=10`) | 727.6 kB | 15.4 kB |
| 5,000 (20 years, the backfill maximum `le=20`) | 1,455 kB | 30.2 kB |

Real data will compress worse than this, because each quarterly history chunk has its own `source_url`. Treat the
gzip column as a lower bound. The local FastAPI app has no compression middleware: a search for `GZip`/`gzip`
middleware in `backend/src/iip/api` found nothing. So in local mode the raw size is what the browser parses.

## Findings, ranked

### F1 (high): the full NAV history is downloaded wherever a name or one field is needed
`GET /api/instruments/{id}` always returns every non-superseded observation with provenance columns. The frontend
calls it in places that need only a name, a rate or a maturity date:
- `SinglePicker` (`frontend/src/pages/Compare.tsx:265-268`) fetches the full detail **only to show the instrument
  name** when a page opens from a `?id=` URL. Risk (`Risk.tsx:67`), Scenarios and Feasibility (`Scenarios.tsx:207,474`)
  all use it. The instrument page's own "Analyse: Risk / Return-target feasibility" links (`InstrumentDetail.tsx:396-399`)
  take this path. A 10-year fund means about 0.73 MB of raw JSON just to show a name.
- `TBillRow` / `FdRow` (`FixedIncome.tsx:274,325`) fetch the full detail per row (see F2).
- `InstrumentDetail` needs the history for the chart, but the "Stored observations" table shows only 50 rows
  (`MAX_ROWS = 50`, `InstrumentDetail.tsx:30,160`). The chart downsamples nothing: about 2,500 points are rendered as
  SVG.

**Fix:** add `?fields=summary` (or a separate `/api/instruments/{id}/summary`) that returns no `series`. Add
`?from=&limit=` paging for `series.points`. Give the chart a server-side downsampled series (for example, the last
point of each week once the history passes 2 years). Keep the full table behind "View as table", which already
exists. Every value stays a stored observation, so traceability is unaffected.
**Expected gain:** Risk/Scenarios deep links go from about 0.7 MB to about 1 kB. Detail page parse and render goes from
2,500 points to roughly 520. That is an estimate, NOT VERIFIED.

### F2 (high): N+1 requests on the Fixed income tables
`KindList` fetches `/api/instruments?kind=tbill|fd` (capped at 500 rows, `routes_core.py:209`). Then **each row**
component runs its own `useApi('/api/instruments/{id}')` (`FixedIncome.tsx:274,325`). That is one list request plus
one request per T-bill or FD, each carrying its full series (F1). On Vercel each request is a function invocation,
about 130–150 ms TTFB measured above. All requests start at once, but over HTTP/2 they still compete for the single
function instance and the Turso round trips. With 20 FDs that is 21 requests. A future signal list of 200 instruments
built the same way would make 201.
**Fix:** return the few fields these rows need (latest yield, maturity, deposit terms, citation URL) inside the list
endpoint, which already uses correlated subqueries for `last_nav`. Or add a batch endpoint
`POST /api/instruments/summary {ids:[…]}`. Then remove the per-row `useApi`.

### F3 (high on hosted, VERIFIED): hashed static assets are never cached and run through the Python function
The SPA catch-all route `spa()` (`backend/src/iip/api/app.py:250-257`) serves `/assets/*` with `FileResponse`, inside a
top-level `SecurityMiddleware`. The live site returns `cache-control: public, max-age=0, must-revalidate` and
`x-vercel-cache: MISS` on every repeat request for a content-hashed file. A revalidation (304) once took 1.13 s.
Vercel's FastAPI docs say static files are promoted to the CDN only for `app.mount(StaticFiles)` / `app.frontend()`,
and that "Top-level middleware: All static mounts and frontends stay in the function"
(https://vercel.com/docs/frameworks/backend/fastapi, accessed 2026-10-15). On top of that, "Promoted source
directories … CDN-served files bypass the function entirely, so middleware handlers … do not run for them" (same
page). So every page load re-requests about 7 JS, CSS and font files through the function, and none are cached.
**Fix (security trade-off, needs the owner's decision):** keep `index.html` in the function, because it carries the
CSP and security headers. Serve `/assets/*` with `Cache-Control: public, max-age=31536000, immutable`. There are two
ways to do it. (a) Lowest risk: add that header in `spa()` only when `full_path.startswith("assets/")`. This keeps the
function path but lets browsers skip revalidation. (b) Larger gain: promote `/assets` to the CDN
(`app.mount("/assets", StaticFiles(...))` plus `[tool.vercel.fastapi.static] cdn = true`). Then copy the security
headers into `vercel.json` `headers`, because the middleware would no longer run for those files.
REQUIRES CONFIGURATION to confirm (b) on a preview deploy.

### F4 (medium, VERIFIED): page modules import each other, so routes pull in other pages' code
Shared helpers are exported from page files, so Vite links the page chunks together:
- `Overview` (the landing page) imports `FixedIncome` (13.2 kB gz) and `Watchlist` (3.5 kB gz).
- `InstrumentDetail` imports `FixedIncome` and `MfExplorer` (`InstrumentDetail.tsx:13-28`).
- `Risk` and `Scenarios` import the whole `Compare` page for `SinglePicker`. `Discovery` imports `MfExplorer`.

**Fix:** move `CiteLink, ManualAge, QuoteCell, ratePct, navLabel, OriginBadge, errorText, exitLoadText,
SinglePicker, InstrumentPicker` into `src/components/` or `src/lib/`. That saves about 17 kB gz on the landing page and
about 19 kB gz on the instrument page. These are small savings, but they also stop more coupling as signal pages are
added.

### F5 (medium, VERIFIED): no client-side cache, so the same GETs repeat
`useApi` (`frontend/src/lib/useApi.ts:12-39`) has no shared cache. It also clears data on every path change
(`setData(null)`), so each mount and each reload shows a loading state again. Repeats seen in the code:
- `/api/data-health` runs twice on `/` (topbar `DataAsOf`, `App.tsx:160`, and `StartHere.tsx:56`). It also runs twice
  on `/data-health`.
- `/api/instruments?kind=tbill` and `?kind=fd` are fetched by `StartHere` on Overview, then fetched again on `/fi`.
- `/api/bonds` is fetched by both the Fixed income bonds tab and every bond `InstrumentDetail` (`InstrumentDetail.tsx:290`),
  which downloads the **whole bond list** to show one bond.
- `/api/me` runs at AuthGate and again on Settings (`Settings.tsx:227`).
- In development, `<StrictMode>` (`main.tsx`) double-invokes effects, so every GET is sent twice in dev only. This is
  expected and does not happen in production.

**Fix:** a small in-memory keyed cache with in-flight de-duplication inside `useApi`. Options: a hand-written
`Map<path, Promise>` with a time-to-live of about 30 s, or a vetted library such as TanStack Query. Invalidate it on
mutations, which already call `reload()`. Keep `no-store` on the HTTP side. The cache lives only in memory and is
cleared on logout, because `AuthGate` remounts on `epoch`, so the "never show stale data from another session" rule
still holds. Also add `GET /api/bonds/{id}`.

### F6 (medium, VERIFIED): request waterfall on the landing page
Cold load of `/`, in order:
1. `index.html`, then `index-*.js` + CSS (each through the function, see F3).
2. `GET /api/me` (AuthGate). Nothing else starts until it returns.
3. In parallel: `GET /api/profile`, `GET /api/data-health`, and the lazy Overview chunk plus its four dependency chunks.
   The chunk download cannot start before step 2, because `lazy()` resolves on render.
4. `GET /api/portfolios`. `StartHere` is held back until this finishes (`Overview.tsx:1101`, `firstLoad ? null`).
5. In parallel: `/summary`, `/transactions`, and StartHere's `/api/data-health` (repeat), `?kind=tbill`, `?kind=fd`.

That is about 5 network round trips in series, each about 130–150 ms TTFB on the hosted app. The realistic minimum is
about 0.7 s before function cold starts and Turso latency are added. These are NOT VERIFIED totals; measure with
Playwright tracing.
**Fixes:** (a) add `<link rel="modulepreload">` for the Overview chunk, or start `import("./pages/Overview")` at module
load, so step 3's chunk overlaps with step 2. (b) Render StartHere in parallel with the portfolio list instead of
gating it on `firstLoad`. (c) Have `/api/me` return the profile status too, which merges steps 2 and 3. (d) Combine
F5's de-duplication with all of these.

### F7 (medium, VERIFIED): Discovery recomputes and writes a DB row on every visit
`Discovery.tsx:255-275` sends `POST /api/discover` on every mount. It sends it again whenever the profile `status`
object changes. The backend runs the full engine and calls `discovery.store_run(...)` each time
(`routes_core.py:184`). Moving between tabs therefore costs a full engine run plus a write. On hosted Turso this also
adds rows to the database.
**Fix:** cache the last result per (profile hash, include_fixtures, data as-of), on the client for the session.
Better, also on the server: return the stored run when the inputs are unchanged. Offer an explicit "Re-run" button.

### F8 (low–medium, NOT VERIFIED magnitude): large tables re-render and re-sort on every keystroke
`MfExplorer` renders up to 500 rows through `DataTable`, which has no virtualization. `columns` is rebuilt on every
render (`MfExplorer.tsx:334+`), and it is a `useMemo` dependency in `DataTable.tsx:57-78`. So every keystroke in the
search box (`setQuery`) re-sorts and re-renders all 500 × about 7 cells. Search itself is correctly submit-based, not
per keystroke (`MfExplorer.tsx:502`), and so are Compare and Watchlist. The instrument "View as table" renders all
2,500+ rows at once (`InstrumentDetail.tsx:195-207`).
**Fix:** wrap `columns` in `useMemo`. Move the search `<form>` into its own component so typing does not re-render the
table. Window the table only if the row cap goes above 500. For a signals screener, plan on paged server queries, not
client sorting of thousands of rows.

### F9 (low, VERIFIED): recharts weight for one line chart
recharts 3 pulls in `@reduxjs/toolkit`, `immer`, `react-redux`, `reselect`, `victory-vendor`, `es-toolkit` and
`decimal.js-light` (from `node_modules/recharts/package.json`). The result is the 97 kB gz InstrumentDetail chunk, used
for one `LineChart`. `d3-scale` is already a dependency, and `DotPlot.tsx` shows the project can draw its own SVG.
A hand-written SVG line chart with `scaleLinear` plus a time scale would cut about 85–90 kB gz. That figure is an
estimate, NOT VERIFIED. It is lazy-loaded already, so it costs only on the instrument page. Do this only if charts
multiply, for example signal and backtest equity curves. Otherwise keep recharts and fix F1 downsampling first,
because render cost grows with point count.

### F10 (low, VERIFIED): fonts
Inter is imported as a variable font with 7 unicode-range subsets (`app.css:1`). Browsers fetch only the subsets they
need. `₹` (U+20B9) is probably in the latin-ext range, so most pages likely download latin (48 kB) **and** latin-ext
(85 kB), which is about 133 kB of woff2 before text renders in Inter. That is NOT VERIFIED in a browser.
**Fix:** import only `@fontsource-variable/inter/latin.css` and `latin-ext.css` (or the `wght` subsets actually used).
Add `font-display: swap` if it is not already set. Alternatively use the system font stack.

## What is already good (VERIFIED)
- Route-level `React.lazy` for every page. recharts is isolated to one route.
- Searches are explicit (submit or Enter), not per keystroke, and require at least 2 characters.
- `useApi` aborts in-flight requests on unmount and on path change. Discovery aborts superseded runs.
- The instrument list endpoint is capped at 500 rows with a `truncated` flag. The observations table shows 50 rows.
- The chart turns off animation (`isAnimationActive={false}`) and turns off dots above 40 points.
- Vercel serves assets Brotli-compressed (`content-encoding: br`).
- Builds are reproducible: local hashes match production.

## Recommended order
1. F1 + F2 together: a summary/batch endpoint and series paging and downsampling. This is the foundation for any
   signals list.
2. F3 option (a): immutable cache headers on `/assets/*`. A small, safe change.
3. F5: de-duplicating cache in `useApi`. F7: memoize Discovery.
4. F6 preload and parallelisation. F4 helper extraction.
5. F8, F10, then F9 only if more charts are added.

## Not done / limits
- No in-browser profiling (Lighthouse, React Profiler, Playwright trace). Render-time and total-waterfall figures are
  marked NOT VERIFIED.
- No real stored data was available locally, so the payload sizes are synthetic, built from the real schema and URL
  format.
- Whether Vercel compresses large `/api` JSON responses was not verified: the only unauthenticated API response is a
  27-byte 401.

## Sources
- Vercel, "Deploy a FastAPI app on Vercel", https://vercel.com/docs/frameworks/backend/fastapi (accessed 2026-10-15):
  "Top-level middleware: All static mounts and frontends stay in the function."; "When using `app.frontend()` or
  `app.mount()` with `StaticFiles`, files are promoted to the CDN at build time"; "CDN-served files bypass the function
  entirely, so middleware handlers … do not run for them."
- Live headers: `curl -D -` against https://investment-intelligence-pro.vercel.app, 2026-10-15 17:56 UTC (table above).
