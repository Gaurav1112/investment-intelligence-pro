// API client: same-origin, cookie session + in-memory CSRF token (threat-model C-02).
// The access token arrives once in the URL fragment (#login=…), is removed immediately, and exchanged for a session.

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    public detail?: unknown,
  ) {
    super(`${status} ${code}`);
  }
}

let csrf: string | null = null;
export const UNAUTHORIZED_EVENT = "iip:unauthorized";

export function readLoginFragment(loc: Location = window.location, hist: History = window.history): string | null {
  const m = /(?:^#|&)login=([A-Za-z0-9_-]{20,256})/.exec(loc.hash);
  if (!m) return null;
  hist.replaceState(null, "", loc.pathname + loc.search); // never leave the token in the URL bar / history
  return m[1] ?? null;
}

export async function login(token: string): Promise<void> {
  const res = await fetch("/api/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
    credentials: "same-origin",
  });
  if (!res.ok) throw new ApiError(res.status, errorCode(await safeJson(res), "LOGIN_FAILED"));
  csrf = ((await res.json()) as { csrf: string }).csrf;
  clearApiCache(); // a new session never sees data cached under the previous one
}

export async function restoreSession(): Promise<boolean> {
  const res = await fetch("/api/me", { credentials: "same-origin" });
  if (res.status === 401) return false;
  if (!res.ok) throw new ApiError(res.status, "SESSION_CHECK_FAILED");
  csrf = ((await res.json()) as { csrf: string | null }).csrf;
  clearApiCache();
  return true;
}

async function safeJson(res: Response): Promise<unknown> {
  try {
    return (await res.json()) as unknown;
  } catch {
    return null;
  }
}

function stringCode(v: unknown): string | null {
  if (typeof v !== "object" || v === null || Array.isArray(v)) return null;
  const code = (v as { code?: unknown }).code;
  return typeof code === "string" && code !== "" ? code : null;
}

/** The server's error code: a top-level `{code}` or FastAPI's `{detail: {code, message}}` (HTTPException with a dict,
 * as routes_today / routes_signals / routes_settings raise). Anything else (a validation list, HTML) → `fallback`. */
export function errorCode(body: unknown, fallback: string): string {
  const top = stringCode(body);
  if (top !== null) return top;
  if (typeof body === "object" && body !== null) return stringCode((body as { detail?: unknown }).detail) ?? fallback;
  return fallback;
}

export async function api<T>(path: string, init: { method?: string; body?: unknown; signal?: AbortSignal } = {}): Promise<T> {
  const method = init.method ?? "GET";
  const headers: Record<string, string> = {};
  if (method !== "GET") {
    headers["Content-Type"] = "application/json";
    if (csrf) headers["X-IIP-CSRF"] = csrf;
  }
  const res = await fetch(path, {
    method,
    headers,
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
    credentials: "same-origin",
    signal: init.signal,
  });
  if (!res.ok) {
    const body = await safeJson(res);
    if (res.status === 401) {
      csrf = null;
      clearApiCache();
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT)); // session gone → lock the app; never show stale data
    }
    throw new ApiError(res.status, errorCode(body, "REQUEST_FAILED"), body);
  }
  const out = (await res.json()) as T;
  if (method !== "GET") clearApiCache(); // any write may change any cached read: drop them all (simple and safe)
  return out;
}

/** Multipart POST (file upload). The browser sets the multipart Content-Type with its boundary, so it is never set
 * here; the CSRF header and same-origin credentials are kept exactly as in `api()`. */
export async function apiUpload<T>(path: string, form: FormData, init: { signal?: AbortSignal } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (csrf) headers["X-IIP-CSRF"] = csrf;
  const res = await fetch(path, { method: "POST", headers, body: form, credentials: "same-origin", signal: init.signal });
  if (!res.ok) {
    const body = await safeJson(res);
    if (res.status === 401) {
      csrf = null;
      clearApiCache();
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    throw new ApiError(res.status, errorCode(body, "REQUEST_FAILED"), body);
  }
  const out = (await res.json()) as T;
  clearApiCache();
  return out;
}

// ------------------------------------------------------------------ shared GET cache (audit-perf-frontend F5)
// In memory only, per tab. One in-flight request per path (de-duplication), and a settled response is reused for
// CACHE_TTL_MS. HTTP stays `no-store`. Cleared on login, session restore, any 401, and after every successful write,
// so a mutation or a new session can never be answered from stale data.

export const CACHE_TTL_MS = 30_000;

export interface CacheEntry {
  promise: Promise<unknown>;
  ctl: AbortController;
  settled: boolean;
  data: unknown;
  at: number;
  subscribers: number;
  pinned: boolean; // started by prefetch(): nobody may abort it for lack of subscribers
}

const cache = new Map<string, CacheEntry>();
// Bound to the fetch in use: replacing it (as every test file's stub does) starts from an empty cache.
let cacheFetch: typeof fetch | undefined = globalThis.fetch;

function syncFetch(): void {
  if (globalThis.fetch !== cacheFetch) {
    cache.clear();
    cacheFetch = globalThis.fetch;
  }
}

/** Drop every cached and in-flight GET (in-flight ones still settle for whoever awaits them, but are not reused). */
export function clearApiCache(): void {
  cache.clear();
}

function isFresh(e: CacheEntry, now: number): boolean {
  return e.settled && now - e.at <= CACHE_TTL_MS;
}

function startGet(path: string): CacheEntry {
  const ctl = new AbortController();
  const entry: CacheEntry = { promise: Promise.resolve(), ctl, settled: false, data: undefined, at: 0, subscribers: 0, pinned: false };
  entry.promise = api<unknown>(path, { signal: ctl.signal }).then(
    (d) => {
      entry.settled = true;
      entry.data = d;
      entry.at = Date.now();
      return d;
    },
    (e: unknown) => {
      if (cache.get(path) === entry) cache.delete(path); // errors are never cached
      throw e;
    },
  );
  cache.set(path, entry);
  return entry;
}

/** The shared entry for a GET: the in-flight one, a fresh settled one, or a new request (always new when `force`). */
export function acquireGet(path: string, force = false): CacheEntry {
  syncFetch();
  const e = cache.get(path);
  if (e && !force && (!e.settled || isFresh(e, Date.now()))) return e;
  return startGet(path);
}

/** Fresh cached data for a GET, or undefined. Never starts a request. */
export function peekCached<T>(path: string): T | undefined {
  syncFetch();
  const e = cache.get(path);
  return e && isFresh(e, Date.now()) ? (e.data as T) : undefined;
}

/** Cached GET with in-flight de-duplication. Not abortable per caller: the request is shared. */
export function cachedGet<T>(path: string, force = false): Promise<T> {
  return acquireGet(path, force).promise as Promise<T>;
}

/** Start a GET now so a component that mounts later finds it in flight or cached. Failures are left for that caller. */
export function prefetch(path: string): void {
  const e = acquireGet(path);
  e.pinned = true;
  e.promise.catch(() => undefined);
}

/** Subscribe a consumer to an entry; the returned release aborts the request once nobody waits for it. */
export function subscribeGet(entry: CacheEntry): () => void {
  entry.subscribers += 1;
  let released = false;
  return () => {
    if (released) return;
    released = true;
    entry.subscribers -= 1;
    // Deferred: StrictMode (and a quick remount) releases and re-subscribes in the same tick; that must not abort.
    setTimeout(() => {
      if (entry.subscribers > 0 || entry.settled || entry.pinned) return;
      for (const [k, v] of cache) if (v === entry) cache.delete(k);
      entry.ctl.abort();
    }, 0);
  };
}

// ------------------------------------------------------------------ instrument summary (no observation series)

/** Path of the instrument summary: the detail response without its `series` (the endpoint is owned by the backend). */
export function instrumentSummaryPath(instrumentId: string): string {
  return `/api/instruments/${encodeURIComponent(instrumentId)}/summary`;
}

/** What callers may rely on from the summary: the instrument row and, when stored, its terms and freshness. Never a
 * series. Kept local to the fetch layer so pages need no full-history type to show a name. */
export interface InstrumentSummaryResponse {
  instrument: { instrument_id: string; name: string; kind: string; origin: string };
  freshness?: { badge: string; observed: string | null };
}
