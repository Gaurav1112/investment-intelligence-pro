import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { InstrumentList, RunSummary } from "../lib/types";
import MfExplorer, { batchResultLines, batchStepText, MAX_JOB_STEPS, runUntilDone, stepText, type JobStep } from "./MfExplorer";

type Call = { url: string; method: string; body: unknown };
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });

function stubFetch(handler: (url: string, method: string, body: unknown) => Response) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
      calls.push({ url, method, body });
      return handler(url, method, body);
    }),
  );
  return calls;
}

const LIST: InstrumentList = {
  truncated: false,
  items: [
    {
      instrument_id: "mf:900551",
      kind: "mf_scheme",
      name: "Example Liquid Fund — Direct Plan · Growth (AMFI 900551)",
      origin: "source",
      amfi_code: "900551",
      category_raw: "Debt Scheme - Liquid Fund",
      plan: "direct",
      last_nav_date: "2026-10-14",
      last_nav: "321.98765",
      nav_points: 2480,
      exit_load: { days: 7, rate: "0.00007", citation: "https://example.org/sid", as_of: "2026-09-30" },
      fixture: false,
    },
    {
      instrument_id: "mf:120000",
      kind: "mf_scheme",
      name: "Sample Flexi Cap Fund — Direct Plan · Growth (AMFI 120000)",
      origin: "source",
      amfi_code: "120000",
      category_raw: "Equity Scheme - Flexi Cap Fund",
      plan: "direct",
      last_nav_date: "2026-10-01",
      last_nav: "123456.7",
      nav_points: 1,
      exit_load: null,
      fixture: false,
    },
    {
      instrument_id: "mf:900001",
      kind: "mf_scheme",
      name: "FIXTURE Liquid Fund",
      origin: "fixture",
      amfi_code: "900001",
      category_raw: "Debt Scheme - Liquid Fund",
      plan: "direct",
      last_nav_date: "2026-10-14",
      last_nav: "1000.0000",
      nav_points: 3650,
      exit_load: null,
      fixture: true,
    },
  ],
};

const renderPage = () =>
  render(
    <MemoryRouter>
      <MfExplorer />
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-15T06:00:00Z"));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("MfExplorer", () => {
  it("renders schemes with exact NAV, freshness, exit load and an unranked label", async () => {
    stubFetch(() => json(LIST));
    renderPage();
    const table = await screen.findByRole("table");
    expect(within(table).getByText("₹321.9877")).toBeInTheDocument(); // 4 dp, half-up, no raw precision
    expect(within(table).getByText("₹1,23,456.7000")).toBeInTheDocument(); // Indian grouping
    expect(within(table).getByText(/0\.007 % if redeemed within 7 days/)).toBeInTheDocument();
    expect(within(table).getAllByText("not entered")).toHaveLength(2);
    expect(within(table).getByText("2480")).toBeInTheDocument();
    // 14-Oct NAV on 15-Oct → end-of-day; 01-Oct (14 days) → stale
    expect(within(table).getAllByText(/END-OF-DAY/).length).toBeGreaterThan(0);
    expect(within(table).getByText(/STALE/)).toBeInTheDocument();
    expect(screen.getAllByText(/not ranked for you/).length).toBeGreaterThan(0);
  });

  it("badges FIXTURE rows and disables network actions for them", async () => {
    stubFetch(() => json(LIST));
    renderPage();
    const link = await screen.findByRole("link", { name: "FIXTURE Liquid Fund" });
    const row = link.closest("tr")!;
    expect(within(row).getAllByText(/FIXTURE — not market data/).length).toBeGreaterThan(0);
    expect(within(row).getByRole("button", { name: /Backfill history/ })).toBeDisabled();
    expect(screen.getByRole("note")).toHaveTextContent("FIXTURE data present");
  });

  it("shows the empty state with a working fetch button and the run summary verbatim", async () => {
    const summary: RunSummary = {
      run_id: "run_20261015T060000Z_ab12cd34",
      source_id: "amfi.navall",
      status: "ok",
      rows_ok: 1534,
      rows_rejected: 0,
      stored: 1534,
      detail: "",
    };
    const calls = stubFetch((url, method) => (method === "POST" ? json(summary) : json({ items: [], truncated: false })));
    renderPage();
    expect(await screen.findByText("No mutual fund schemes are stored yet")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Fetch latest AMFI NAVs" }));
    expect(await screen.findByText(/status OK · rows ok 1534 · rows rejected 0 · stored 1534/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.url === "/api/ingestion/amfi-navall")).toBe(true);
  });

  it("shows an error state when the list fails", async () => {
    stubFetch(() => json({ code: "INTERNAL_ERROR" }, 500));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("INTERNAL_ERROR");
  });

  it("reports a non-ok backfill plainly", async () => {
    const partial: RunSummary = {
      run_id: "run_x",
      source_id: "amfi.navhistory",
      status: "partial",
      rows_ok: 900,
      rows_rejected: 3,
      stored: 897,
      detail: "window 2019-01 failed: timeout",
    };
    const calls = stubFetch((url, method) => (method === "POST" ? json(partial) : json(LIST)));
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Backfill history for Example Liquid/ }));
    const msg = await screen.findByText(/status PARTIAL/);
    expect(msg).toHaveTextContent("rows ok 900 · rows rejected 3 · stored 897 · window 2019-01 failed: timeout");
    expect(msg).toHaveTextContent("some requests failed, so part of the data is missing; running it again fills the gaps");
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.url).toBe("/api/ingestion/backfill/900551");
  });

  it("submits the exit load with the rate as an exact decimal STRING fraction", async () => {
    const calls = stubFetch((url, method) => (method === "PUT" ? json({ status: "saved" }) : json(LIST)));
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Enter exit load for Sample Flexi/ }));
    fireEvent.change(screen.getByLabelText("Applies if redeemed within (days)"), { target: { value: "365" } });
    fireEvent.change(screen.getByLabelText("Exit load (% of redemption value)"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Official page URL"), { target: { value: "https://amc.example.in/sid.pdf" } });
    fireEvent.change(screen.getByLabelText("Value applies as of"), { target: { value: "2026-10-01" } });
    await userEvent.click(screen.getByRole("button", { name: "Save exit load" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.url).toBe("/api/instruments/mf%3A120000/exit-load");
    expect(put.body).toEqual({ days: 365, rate: "0.01", citation: { url: "https://amc.example.in/sid.pdf", as_of: "2026-10-01" } });
    expect(typeof (put.body as { rate: unknown }).rate).toBe("string");
  });

  it("shows server 422 errors next to the field", async () => {
    stubFetch((url, method) =>
      method === "PUT"
        ? json({ detail: [{ loc: ["body", "rate"], msg: "Input should be less than or equal to 0.05", type: "less_than_equal" }] }, 422)
        : json(LIST),
    );
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Enter exit load for Sample Flexi/ }));
    fireEvent.change(screen.getByLabelText("Applies if redeemed within (days)"), { target: { value: "30" } });
    fireEvent.change(screen.getByLabelText("Exit load (% of redemption value)"), { target: { value: "9" } });
    fireEvent.change(screen.getByLabelText("Official page URL"), { target: { value: "https://amc.example.in/sid.pdf" } });
    fireEvent.change(screen.getByLabelText("Value applies as of"), { target: { value: "2026-10-01" } });
    await userEvent.click(screen.getByRole("button", { name: "Save exit load" }));
    expect(await screen.findByText("Input should be less than or equal to 0.05")).toBeInTheDocument();
    expect(screen.getByLabelText("Exit load (% of redemption value)")).toHaveAttribute("aria-invalid", "true");
  });
});

describe("MfExplorer in hosted mode (ADR-0013: long jobs answer in bounded steps)", () => {
  const FINAL: RunSummary = {
    run_id: "run_h", source_id: "amfi.navhistory", status: "ok", rows_ok: 40, rows_rejected: 0, stored: 40, detail: "complete",
  };

  it("keeps calling the backfill until the server says done, showing the server's progress", async () => {
    const steps = [
      { done: false, phase: "discovering", windows_done: 0, windows_total: 5 },
      { done: false, phase: "fetching", windows_done: 2, windows_total: 5 },
      { done: true, phase: "complete", windows_done: 5, windows_total: 5, ...FINAL },
    ];
    const calls = stubFetch((url, method) => (method === "POST" ? json(steps.shift()) : json(LIST)));
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Backfill history for Example Liquid/ }));
    const msg = await screen.findByText(/status OK/);
    expect(msg).toHaveTextContent("stored 40");
    const posts = calls.filter((c) => c.method === "POST");
    expect(posts).toHaveLength(3);
    expect(posts.every((c) => c.url === "/api/ingestion/backfill/900551")).toBe(true);
  });

  it("describes each step in plain words from the server's counts", () => {
    expect(stepText({ done: false, phase: "discovering" })).toBe("finding AMFI's fund-house id…");
    expect(stepText({ done: false, phase: "fetching", windows_done: 2, windows_total: 5 })).toBe("fetched 2 of 5 date windows…");
    expect(stepText({ done: false, phase: "storing", schemes_done: 200, schemes_total: 1779 })).toBe("stored 200 of 1779 schemes…");
  });

  it("never loops forever: a job that never finishes stops with a plain message", async () => {
    let n = 0;
    const step = async (): Promise<JobStep> => {
      n++;
      return { done: false, phase: "fetching" };
    };
    await expect(runUntilDone(step, () => undefined)).rejects.toThrow("JOB_DID_NOT_FINISH");
    expect(n).toBe(MAX_JOB_STEPS);
  });

  it("a local single-call answer (no done field) ends after one call", async () => {
    let n = 0;
    const s = await runUntilDone(async () => {
      n++;
      return FINAL;
    }, () => undefined);
    expect(n).toBe(1);
    expect(s.stored).toBe(40);
  });
});


describe("MfExplorer deep link (walkthrough 2026-10-15)", () => {
  it("opens the exit-load form for the scheme named in ?exit_load=, searching by ?q=", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        calls.push(url);
        return new Response(JSON.stringify(LIST), { status: 200, headers: { "Content-Type": "application/json" } });
      }),
    );
    const first = LIST.items[0]!;
    render(
      <MemoryRouter initialEntries={[`/mf?q=Example&exit_load=${encodeURIComponent(first.instrument_id)}`]}>
        <MfExplorer />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("heading", { name: `Exit load for ${first.name}` })).toBeInTheDocument();
    expect(calls.some((u) => u.includes("q=Example"))).toBe(true);
    vi.unstubAllGlobals();
  });
});

describe("MfExplorer batch backfill (walkthrough 2026-10-15)", () => {
  it("selects only real schemes, sends their codes once, and reports per fund house after hosted steps", async () => {
    let posts = 0;
    const calls = stubFetch((_url, method) => {
      if (method !== "POST") return json(LIST);
      posts += 1;
      if (posts === 1)
        return json({ done: false, phase: "fetching", amcs_done: 0, amcs_total: 2, windows_done: 1, windows_total: 6, stored: 2 });
      return json({
        done: true, phase: "complete", amcs_done: 2, amcs_total: 2, windows_done: 6, windows_total: 6, stored: 4,
        run_id: "run_b", source_id: "amfi.navhistory", status: "ok", rows_ok: 40, rows_rejected: 0,
        detail: "1 scheme(s) across 2 fund house(s), one pass per fund house",
        fund_houses: [{ amc: "Example Mutual Fund", status: "done", error: null, schemes: [{ amfi_code: 900551, stored: 4 }] }],
        skipped: [{ amfi_code: 120000, retry_after_s: 301 }],
      });
    });
    renderPage();
    await screen.findByRole("table");
    expect(screen.queryByRole("checkbox", { name: /Select FIXTURE/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Backfill history for 0 selected" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Select all shown" }));
    expect(screen.getByRole("checkbox", { name: /Select Example Liquid/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Select Sample Flexi/ })).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Backfill history for 2 selected" }));

    await screen.findByText(/Example Mutual Fund: Example Liquid Fund — Direct Plan · Growth \(AMFI 900551\): 4 NAVs stored\./);
    const batch = calls.filter((c) => c.url === "/api/ingestion/backfill-batch");
    expect(batch).toHaveLength(2); // one unfinished hosted step, then the final answer
    expect(batch[0]?.body).toEqual({ amfi_codes: [900551, 120000], years: 10 });
    expect(batch[1]?.body).toEqual(batch[0]?.body); // the same selection continues the job
    expect(screen.getByText(/Skipped, because they were backfilled in the last 15 minutes: Sample Flexi Cap Fund/)).toHaveTextContent(
      "Try them again in about 6 minutes.",
    );
    expect(screen.getByText(/History backfill for the selected schemes: status OK/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Backfill history for 0 selected" })).toBeDisabled(); // selection cleared
  });

  it("refuses an invalid number of years before sending anything", async () => {
    const calls = stubFetch(() => json(LIST));
    renderPage();
    await screen.findByRole("table");
    await userEvent.click(screen.getByRole("checkbox", { name: /Select Example Liquid/ }));
    const years = screen.getByLabelText("Years of history");
    await userEvent.clear(years);
    await userEvent.type(years, "25");
    expect(screen.getByRole("button", { name: "Backfill history for 1 selected" })).toBeDisabled();
    expect(years).toHaveAccessibleDescription("Years of history: a whole number from 1 to 20.");
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("describes batch progress only with the server's counts", () => {
    expect(batchStepText({ done: false, phase: "discovering", amc: "Example Mutual Fund" })).toBe(
      "finding AMFI's fund-house id for Example Mutual Fund…",
    );
    expect(
      batchStepText({ done: false, phase: "fetching", amcs_done: 1, amcs_total: 3, windows_done: 50, windows_total: 123, stored: 900 }),
    ).toBe("1 of 3 fund houses done · fetched 50 of 123 date windows · 900 NAVs stored…");
  });

  it("an all-skipped answer says so without a run summary", () => {
    const lines = batchResultLines(
      { done: true, status: "skipped", fund_houses: [], skipped: [{ amfi_code: 1, retry_after_s: 30 }] },
      (c) => `Scheme ${c}`,
    );
    expect(lines.map((l) => l.text)).toEqual([
      "Skipped, because they were backfilled in the last 15 minutes: Scheme 1. Try them again in about 1 minute.",
    ]);
  });
});
