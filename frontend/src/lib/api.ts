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
  if (!res.ok) throw new ApiError(res.status, (await safeJson(res))?.code ?? "LOGIN_FAILED");
  csrf = ((await res.json()) as { csrf: string }).csrf;
}

export async function restoreSession(): Promise<boolean> {
  const res = await fetch("/api/me", { credentials: "same-origin" });
  if (res.status === 401) return false;
  if (!res.ok) throw new ApiError(res.status, "SESSION_CHECK_FAILED");
  csrf = ((await res.json()) as { csrf: string | null }).csrf;
  return true;
}

async function safeJson(res: Response): Promise<{ code?: string } | null> {
  try {
    return (await res.json()) as { code?: string };
  } catch {
    return null;
  }
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
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT)); // session gone → lock the app; never show stale data
    }
    throw new ApiError(res.status, body?.code ?? "REQUEST_FAILED", body);
  }
  return (await res.json()) as T;
}
