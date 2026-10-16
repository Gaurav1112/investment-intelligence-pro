import { useCallback, useEffect, useRef, useState } from "react";
import { acquireGet, api, peekCached, prefetch, subscribeGet } from "./api";

export interface ApiState<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => void;
}

/** GET a resource through the shared cache (one in-flight request per path, fresh responses reused for
 * CACHE_TTL_MS). Never shows data from a previous path as current; `reload()` always goes to the network. */
export function useApi<T>(path: string | null): ApiState<T> {
  const [data, setData] = useState<T | null>(() => (path === null ? null : (peekCached<T>(path) ?? null)));
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState<boolean>(() => path !== null && peekCached<T>(path) === undefined);
  const [tick, setTick] = useState(0);
  const force = useRef(false);
  const reload = useCallback(() => {
    force.current = true;
    setTick((t) => t + 1);
  }, []);
  useEffect(() => {
    if (path === null) return;
    const forced = force.current;
    force.current = false;
    const hit = forced ? undefined : peekCached<T>(path);
    if (hit !== undefined) {
      setData(hit);
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    setData(null);
    const entry = acquireGet(path, forced);
    const release = subscribeGet(entry);
    // Only the CURRENT subscription may touch state: a superseded one settles after the next request has started, and
    // its finally used to flip loading=false while data was still null (a false "nothing here" empty state).
    let live = true;
    (entry.promise as Promise<T>)
      .then((d) => {
        if (live) setData(d);
      })
      .catch((e: unknown) => {
        if (live && !(e instanceof DOMException && e.name === "AbortError")) setError(e);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
      release();
    };
  }, [path, tick]);
  return { data, error, loading, reload };
}

/** Start GETs before the component that needs them mounts (parallel landing requests); safe to call every render. */
export function usePrefetch(paths: readonly string[]): void {
  const key = paths.join("\n");
  useEffect(() => {
    for (const p of key ? key.split("\n") : []) prefetch(p);
  }, [key]);
}

/** Run a mutation (POST/PUT/DELETE) with pending/error state. */
export function useMutation<TIn, TOut>(method: string, path: string) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const mounted = useRef(true);
  // Set in the setup too: StrictMode runs setup → cleanup → setup on the same fiber, and a ref that only the cleanup
  // writes stays false forever (errors swallowed, pending stuck at true).
  useEffect(() => {
    mounted.current = true;
    return () => void (mounted.current = false);
  }, []);
  const run = useCallback(
    async (body?: TIn): Promise<TOut | null> => {
      setPending(true);
      setError(null);
      try {
        return await api<TOut>(path, { method, body });
      } catch (e) {
        if (mounted.current) setError(e);
        return null;
      } finally {
        if (mounted.current) setPending(false);
      }
    },
    [method, path],
  );
  return { run, pending, error };
}
