import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { InstrumentList, WatchItem, WatchlistResponse } from "../lib/types";
import Watchlist, { reasonText } from "./Watchlist";

// Shapes follow backend/src/iip/services/portfolio.py watchlist() / watch_change().
type Call = { url: string; method: string; body: unknown; headers: Record<string, string> };
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
function stubFetch(handler: (url: string, method: string, body: unknown) => Response) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
      calls.push({ url, method, body, headers: (init?.headers ?? {}) as Record<string, string> });
      return handler(url, method, body);
    }),
  );
  return calls;
}

const obs = (obs_id: number, value: string, d: string) => ({
  obs_id, value, unit: "INR", observation_date: d, source_id: "fixture.nav", url: "https://example.invalid/nav",
  retrieved_at: `${d}T18:00:00+00:00`, quality_status: "fixture", evidence: `/api/evidence/${obs_id}`,
});

const FALLING: WatchItem = {
  instrument_id: "mf:990004", name: "TEST Equity Fund D", kind: "mf_scheme", note: "later", added_at: "2026-09-01T06:00:00+00:00",
  series_id: "nav:990004", base: obs(11, "100.0000", "2026-09-01"), latest: obs(12, "85.0000", "2026-10-14"),
  change: { value: "-15.0000", unit: "INR", from: { date: "2026-09-01", value: "100.0000" }, to: { date: "2026-10-14", value: "85.0000" } },
  absolute_return: { value: "-0.15", display: "-15.00%", formula_id: "ABS_RETURN@1", note: "absolute (not annualised)" },
  badge: "FIXTURE", reason: null,
};
const STALE: WatchItem = {
  instrument_id: "mf:990003", name: "TEST Debt Fund C", kind: "mf_scheme", note: null, added_at: "2026-10-01T06:00:00+00:00",
  series_id: "nav:990003", base: obs(5, "14.0000", "2026-09-01"), latest: obs(5, "14.0000", "2026-09-01"),
  change: null, absolute_return: null, badge: "STALE", reason: "STALE_NAV",
};
const LIST: WatchlistResponse = { as_of: "2026-10-15T06:00:00+00:00", items: [FALLING, STALE] };
const SEARCH: InstrumentList = {
  items: [{ instrument_id: "mf:990001", kind: "mf_scheme", name: "TEST Liquid Fund A", origin: "fixture", amfi_code: "990001", category_raw: "Liquid Fund", plan: "direct", last_nav_date: "2026-10-14", last_nav: "12.3456", nav_points: 5, exit_load: null, fixture: true }],
  truncated: false,
};

function realistic(url: string, method: string): Response {
  if (url === "/api/watchlist" && method === "GET") return json(LIST);
  if (url.startsWith("/api/instruments?q=")) return json(SEARCH);
  if (method === "POST") return json({ instrument_id: "mf:990001", added_at: "2026-10-15T06:00:00+00:00", status: "watching" });
  if (method === "DELETE") return json({ status: "deleted" });
  return json({ code: "NOT_FOUND", message: "not found" }, 404);
}

const renderPage = () =>
  render(
    <MemoryRouter>
      <Watchlist />
    </MemoryRouter>,
  );

afterEach(() => vi.unstubAllGlobals());

describe("Watchlist", () => {
  it("shows change since added as absolute, with both dates, and never annualised", async () => {
    stubFetch(realistic);
    renderPage();
    const row = (await screen.findByRole("link", { name: "TEST Equity Fund D" })).closest("tr")!;
    expect(within(row).getByText(/₹100.0000 on 01-Sep-2026 → ₹85.0000 on 14-Oct-2026/)).toBeInTheDocument();
    expect(within(row).getByText(/−₹15.0000/)).toHaveClass("down");
    expect(within(row).getByText(/-15.00% absolute, not annualised/)).toBeInTheDocument();
    expect(within(row).getByText("later")).toBeInTheDocument();
    expect(within(row).getByText(/FIXTURE — not market data/)).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "Evidence for latest value" })).toHaveAttribute("href", "/evidence/12");
    expect(within(row).getByText("01-Sep-2026 06:00 UTC")).toBeInTheDocument();
    expect(screen.queryByText(/a year|p\.a\./)).toBeNull();
  });

  it("shows a STALE entry without a change and says why", async () => {
    stubFetch(realistic);
    renderPage();
    const row = (await screen.findByRole("link", { name: "TEST Debt Fund C" })).closest("tr")!;
    expect(row).toHaveClass("is-excluded");
    expect(within(row).getByText(/Not shown: the latest NAV is STALE/)).toBeInTheDocument();
    expect(reasonText("NO_SERIES: no stored price series")).toMatch(/no stored price series/);
  });

  it("shows the empty and error states", async () => {
    stubFetch(() => json({ as_of: "2026-10-15T06:00:00+00:00", items: [] }));
    const { unmount } = renderPage();
    expect(await screen.findByText("Your watchlist is empty")).toBeInTheDocument();
    unmount();
    vi.unstubAllGlobals();
    stubFetch(() => json({ code: "INTERNAL_ERROR" }, 500));
    renderPage();
    expect(await screen.findByText(/The request failed \(INTERNAL_ERROR\)/)).toBeInTheDocument();
  });

  it("adds an instrument found by search, with a note", async () => {
    const calls = stubFetch(realistic);
    renderPage();
    await screen.findByRole("table");
    fireEvent.change(screen.getByLabelText("Find instrument by name"), { target: { value: "Liquid" } });
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(calls.some((c) => c.url === "/api/instruments?q=Liquid")).toBe(true);
    await userEvent.click(await screen.findByRole("button", { name: "Select TEST Liquid Fund A" }));
    fireEvent.change(screen.getByLabelText("Note (optional)"), { target: { value: "  compare with FD  " } });
    await userEvent.click(screen.getByRole("button", { name: "Add to watchlist" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ instrument_id: "mf:990001", note: "compare with FD" });
    expect(await screen.findByText("Added TEST Liquid Fund A to the watchlist.")).toHaveAttribute("role", "status");
  });

  it("explains ALREADY_WATCHED in words", async () => {
    stubFetch((url, method) =>
      method === "POST" ? json({ code: "ALREADY_WATCHED", message: "instrument is already on the watchlist" }, 409) : realistic(url, method),
    );
    renderPage();
    await screen.findByRole("table");
    fireEvent.change(screen.getByLabelText("Find instrument by name"), { target: { value: "Liquid" } });
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await userEvent.click(await screen.findByRole("button", { name: "Select TEST Liquid Fund A" }));
    await userEvent.click(screen.getByRole("button", { name: "Add to watchlist" }));
    expect(await screen.findByText("TEST Liquid Fund A is already on your watchlist.")).toBeInTheDocument();
  });

  it("removes only after confirmation, with a JSON DELETE", async () => {
    const calls = stubFetch(realistic);
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Remove TEST Equity Fund D" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Confirm remove TEST Equity Fund D" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
    const del = calls.find((c) => c.method === "DELETE")!;
    expect(del.url).toBe("/api/watchlist/mf%3A990004");
    expect(del.headers["Content-Type"]).toBe("application/json");
  });
});
