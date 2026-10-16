import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode, useState } from "react";
import { api, ApiError, CACHE_TTL_MS, cachedGet, clearApiCache, peekCached, prefetch } from "./api";
import { useApi, useMutation } from "./useApi";

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => vi.unstubAllGlobals());

function MutationProbe() {
  const m = useMutation<{ x: number }, { ok: boolean }>("POST", "/api/thing");
  return (
    <div>
      <button type="button" onClick={() => void m.run({ x: 1 })}>
        go
      </button>
      <output data-testid="pending">{String(m.pending)}</output>
      <output data-testid="error">{m.error ? "has-error" : "no-error"}</output>
    </div>
  );
}

describe("useMutation (R-01)", () => {
  it("under StrictMode a failed mutation still reports its error and clears pending", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ code: "BOOM" }, 500)));
    render(
      <StrictMode>
        <MutationProbe />
      </StrictMode>,
    );
    await userEvent.click(screen.getByRole("button", { name: "go" }));
    await waitFor(() => expect(screen.getByTestId("error")).toHaveTextContent("has-error"));
    expect(screen.getByTestId("pending")).toHaveTextContent("false");
  });

  it("under StrictMode a successful mutation clears pending", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ ok: true })));
    render(
      <StrictMode>
        <MutationProbe />
      </StrictMode>,
    );
    await userEvent.click(screen.getByRole("button", { name: "go" }));
    await waitFor(() => expect(screen.getByTestId("pending")).toHaveTextContent("false"));
    expect(screen.getByTestId("error")).toHaveTextContent("no-error");
  });
});

function QueryProbe() {
  const [path, setPath] = useState("/api/a");
  const q = useApi<{ v: string }>(path);
  return (
    <div>
      <button type="button" onClick={() => setPath("/api/b")}>
        switch
      </button>
      <output data-testid="state">{q.loading ? "loading" : q.data ? `data:${q.data.v}` : "empty"}</output>
    </div>
  );
}

describe("useApi (TS-2)", () => {
  it("an aborted request never flips loading off while the new request is in flight (no false empty state)", async () => {
    // /api/a never resolves on its own: it only rejects when aborted. /api/b resolves when we say so.
    let releaseB: (() => void) | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (url: string, init?: RequestInit) =>
          new Promise<Response>((resolve, reject) => {
            if (url === "/api/a") {
              init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
            } else {
              releaseB = () => resolve(json({ v: "b" }));
            }
          }),
      ),
    );
    render(<QueryProbe />);
    expect(screen.getByTestId("state")).toHaveTextContent("loading");
    await userEvent.click(screen.getByRole("button", { name: "switch" }));
    // Let the aborted /api/a promise settle (its catch/finally run) while /api/b is still pending.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(screen.getByTestId("state")).toHaveTextContent("loading");
    expect(screen.getByTestId("state")).not.toHaveTextContent("empty");
    await act(async () => {
      releaseB?.();
    });
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("data:b"));
  });
});

// ------------------------------------------------------------------ shared cache (A06, audit-perf-frontend F5)

function Reader({ path, label }: { path: string; label: string }) {
  const q = useApi<{ v: string }>(path);
  return (
    <div>
      <output data-testid={label}>{q.loading ? "loading" : q.data ? `data:${q.data.v}` : q.error ? "error" : "empty"}</output>
      <button type="button" onClick={q.reload}>
        reload-{label}
      </button>
    </div>
  );
}

function countingFetch(body: (url: string) => unknown = (url) => ({ v: url })) {
  const calls: { url: string; method: string }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? "GET" });
      return json(body(url));
    }),
  );
  return calls;
}

describe("useApi shared cache (A06)", () => {
  afterEach(() => {
    clearApiCache();
    vi.useRealTimers();
  });

  it("de-duplicates concurrent GETs of the same path across components", async () => {
    const calls = countingFetch();
    render(
      <>
        <Reader path="/api/data-health" label="a" />
        <Reader path="/api/data-health" label="b" />
        <Reader path="/api/other" label="c" />
      </>,
    );
    await waitFor(() => expect(screen.getByTestId("a")).toHaveTextContent("data:/api/data-health"));
    expect(screen.getByTestId("b")).toHaveTextContent("data:/api/data-health");
    await waitFor(() => expect(screen.getByTestId("c")).toHaveTextContent("data:/api/other"));
    expect(calls.filter((c) => c.url === "/api/data-health")).toHaveLength(1);
    expect(calls).toHaveLength(2);
  });

  it("sends one request under StrictMode (double-invoked effects share the in-flight GET)", async () => {
    const calls = countingFetch();
    render(
      <StrictMode>
        <Reader path="/api/me" label="a" />
      </StrictMode>,
    );
    await waitFor(() => expect(screen.getByTestId("a")).toHaveTextContent("data:/api/me"));
    expect(calls).toHaveLength(1);
  });

  it("a remount within the TTL renders cached data at once, without a request or a loading state", async () => {
    const calls = countingFetch();
    const first = render(<Reader path="/api/instruments?kind=fd" label="a" />);
    await waitFor(() => expect(screen.getByTestId("a")).toHaveTextContent("data:"));
    first.unmount();
    render(<Reader path="/api/instruments?kind=fd" label="a" />);
    expect(screen.getByTestId("a")).toHaveTextContent("data:/api/instruments?kind=fd");
    expect(calls).toHaveLength(1);
  });

  it("refetches once the TTL has passed", async () => {
    const calls = countingFetch();
    const t0 = 1_000_000;
    const now = vi.spyOn(Date, "now").mockReturnValue(t0);
    const first = render(<Reader path="/api/x" label="a" />);
    await waitFor(() => expect(screen.getByTestId("a")).toHaveTextContent("data:"));
    first.unmount();
    now.mockReturnValue(t0 + CACHE_TTL_MS + 1);
    render(<Reader path="/api/x" label="a" />);
    await waitFor(() => expect(calls).toHaveLength(2));
    now.mockRestore();
  });

  it("reload() always goes to the network", async () => {
    const calls = countingFetch();
    render(<Reader path="/api/x" label="a" />);
    await waitFor(() => expect(screen.getByTestId("a")).toHaveTextContent("data:"));
    await userEvent.click(screen.getByRole("button", { name: "reload-a" }));
    await waitFor(() => expect(calls).toHaveLength(2));
    await waitFor(() => expect(screen.getByTestId("a")).toHaveTextContent("data:/api/x"));
  });

  it("a successful write clears the cache, so the next read is fresh", async () => {
    const calls = countingFetch();
    const first = render(<Reader path="/api/portfolios" label="a" />);
    await waitFor(() => expect(screen.getByTestId("a")).toHaveTextContent("data:"));
    first.unmount();
    await api("/api/portfolios", { method: "POST", body: { name: "x" } });
    expect(peekCached("/api/portfolios")).toBeUndefined();
    render(<Reader path="/api/portfolios" label="a" />);
    await waitFor(() => expect(screen.getByTestId("a")).toHaveTextContent("data:"));
    expect(calls.filter((c) => c.url === "/api/portfolios" && c.method === "GET")).toHaveLength(2);
  });

  it("errors are not cached and a 401 empties the cache", async () => {
    let fail = true;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => (fail ? json({ code: "BOOM" }, 500) : json({ v: url }))),
    );
    const first = render(<Reader path="/api/y" label="a" />);
    await waitFor(() => expect(screen.getByTestId("a")).toHaveTextContent("error"));
    first.unmount();
    fail = false;
    const second = render(<Reader path="/api/y" label="a" />);
    await waitFor(() => expect(screen.getByTestId("a")).toHaveTextContent("data:/api/y"));
    second.unmount();
    expect(peekCached("/api/y")).toEqual({ v: "/api/y" });
    let hit = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        hit += 1;
        return hit === 1 ? json({ v: url }) : json({ code: "UNAUTHORIZED" }, 401);
      }),
    );
    await cachedGet("/api/z");
    expect(peekCached("/api/z")).toEqual({ v: "/api/z" });
    await expect(api("/api/other")).rejects.toBeInstanceOf(ApiError);
    expect(peekCached("/api/z")).toBeUndefined();
  });

  it("prefetch starts a GET that a later mount reuses", async () => {
    const calls = countingFetch();
    prefetch("/api/data-health");
    expect(calls).toHaveLength(1);
    render(<Reader path="/api/data-health" label="a" />);
    await waitFor(() => expect(screen.getByTestId("a")).toHaveTextContent("data:/api/data-health"));
    expect(calls).toHaveLength(1);
  });
});
