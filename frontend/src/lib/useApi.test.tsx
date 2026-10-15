import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode, useState } from "react";
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
