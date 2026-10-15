import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

export interface ApiState<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => void;
}

/** GET a resource; aborts on unmount; never shows stale data from a previous request as current. */
export function useApi<T>(path: string | null): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState<boolean>(path !== null);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  useEffect(() => {
    if (path === null) return;
    const ctl = new AbortController();
    setLoading(true);
    setError(null);
    setData(null);
    api<T>(path, { signal: ctl.signal })
      .then((d) => setData(d))
      .catch((e: unknown) => {
        if (!(e instanceof DOMException && e.name === "AbortError")) setError(e);
      })
      .finally(() => setLoading(false));
    return () => ctl.abort();
  }, [path, tick]);
  return { data, error, loading, reload };
}

/** Run a mutation (POST/PUT/DELETE) with pending/error state. */
export function useMutation<TIn, TOut>(method: string, path: string) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const mounted = useRef(true);
  useEffect(() => () => void (mounted.current = false), []);
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
