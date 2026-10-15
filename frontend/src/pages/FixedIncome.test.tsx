import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { InstrumentDetailResponse, InstrumentList, InstrumentListItem } from "../lib/types";
import FixedIncome, { navLabel, ratePct } from "./FixedIncome";

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

const base = { amfi_code: null, category_raw: null, plan: null, last_nav_date: null, last_nav: null, nav_points: 0, exit_load: null };
const TB_MANUAL: InstrumentListItem = {
  ...base,
  instrument_id: "tbill:182d:2027-04-15",
  kind: "tbill",
  name: "182-day T-bill, auction of 14-Oct-2026",
  origin: "manual",
  fixture: false,
};
const TB_FIXTURE: InstrumentListItem = {
  ...base,
  instrument_id: "tbill:182d:2027-04-13",
  kind: "tbill",
  name: "FIXTURE 182-day T-bill",
  origin: "fixture",
  fixture: true,
};
const FD_MANUAL: InstrumentListItem = {
  ...base,
  instrument_id: "fd:example-bank:365d",
  kind: "fd",
  name: "Example Bank FD — 365 days",
  origin: "manual",
  fixture: false,
};

function tbillDetail(item: InstrumentListItem, value: string, asOf: string, quality: "manual" | "fixture"): InstrumentDetailResponse {
  return {
    instrument: { instrument_id: item.instrument_id, kind: "tbill", name: item.name, issuer_id: "goi", isin: null, amfi_code: null, currency: "INR", origin: item.origin, created_at: "2026-10-14T10:00:00+00:00" },
    bond_terms: { instrument_id: item.instrument_id, face_value: "100", coupon_rate: "0", coupon_freq: 0, issue_date: null, maturity_date: item.instrument_id.slice(-10), daycount: "ACT/365F", listed: 1, call_schedule_json: null, credit_rating: "SOVEREIGN", rating_agency: null, rating_date: null },
    series: {
      series_id: `yield:${item.instrument_id}`,
      points: [{ observation_date: asOf, value, source_id: "rbi.pr.tbill", source_url: "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=1", retrieved_at: "2026-10-14T10:00:00+00:00", quality_status: quality }],
    },
  };
}

const FD_DETAIL: InstrumentDetailResponse = {
  instrument: { instrument_id: FD_MANUAL.instrument_id, kind: "fd", name: FD_MANUAL.name, issuer_id: null, isin: null, amfi_code: null, currency: "INR", origin: "manual", created_at: "2026-09-01T10:00:00+00:00" },
  deposit_terms: { instrument_id: FD_MANUAL.instrument_id, institution: "Example Bank", rate: "0.0725", compounding: "quarterly", tenure_days: 365, premature_penalty: null, dicgc_eligible: 1, rate_as_of: "2026-09-01", citation_url: "https://bank.example.in/rates" },
  series: { series_id: `yield:${FD_MANUAL.instrument_id}`, points: [] },
};

function realistic(url: string, method: string): Response {
  if (method !== "GET") return json({ instrument_id: "x" });
  if (url === "/api/instruments?kind=tbill") return json({ items: [TB_MANUAL, TB_FIXTURE], truncated: false } satisfies InstrumentList);
  if (url === "/api/instruments?kind=fd") return json({ items: [FD_MANUAL], truncated: false } satisfies InstrumentList);
  if (url.endsWith(encodeURIComponent(TB_MANUAL.instrument_id))) return json(tbillDetail(TB_MANUAL, "0.0654", "2026-10-14", "manual"));
  if (url.endsWith(encodeURIComponent(TB_FIXTURE.instrument_id))) return json(tbillDetail(TB_FIXTURE, "0.0650", "2026-10-15", "fixture"));
  if (url.endsWith(encodeURIComponent(FD_MANUAL.instrument_id))) return json(FD_DETAIL);
  return json({ detail: "not found" }, 404);
}

const renderPage = () =>
  render(
    <MemoryRouter>
      <FixedIncome />
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

describe("format helpers", () => {
  it("formats rates at the precision entered, without floats", () => {
    expect(ratePct("0.0650")).toBe("6.50 %");
    expect(ratePct("0.065432")).toBe("6.5432 %");
    expect(ratePct("0.0654321")).toBe("6.5432 %");
    expect(ratePct("0.07")).toBe("7.00 %");
    expect(navLabel("123456.78915")).toBe("₹1,23,456.7892");
  });
});

describe("FixedIncome — T-bills", () => {
  it("renders stored T-bills with yield, maturity, manual badge, citation and FIXTURE badge", async () => {
    stubFetch(realistic);
    renderPage();
    const manualRow = (await screen.findByRole("link", { name: TB_MANUAL.name })).closest("tr")!;
    await within(manualRow).findByText("6.54 %");
    expect(within(manualRow).getByText("15-Apr-2027")).toBeInTheDocument();
    expect(within(manualRow).getAllByText(/MANUAL ENTRY/).length).toBeGreaterThan(0);
    expect(within(manualRow).getByText("1 day old")).toBeInTheDocument();
    expect(within(manualRow).getByRole("link", { name: "www.rbi.org.in" })).toBeInTheDocument();
    expect(within(manualRow).getByRole("button", { name: `Delete ${TB_MANUAL.name}` })).toBeInTheDocument();

    const fixRow = screen.getByRole("link", { name: TB_FIXTURE.name }).closest("tr")!;
    expect(fixRow).toHaveClass("fixture-zone");
    expect(within(fixRow).getAllByText(/FIXTURE — not market data/).length).toBeGreaterThan(0);
    expect(within(fixRow).queryByRole("button", { name: /Delete/ })).toBeNull();
  });

  it("shows an empty state that explains nothing is fetched", async () => {
    stubFetch(() => json({ items: [], truncated: false }));
    renderPage();
    expect(await screen.findByText("No T-bills stored yet")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Add a T-bill" })).toBeInTheDocument();
  });

  it("shows an error state", async () => {
    stubFetch(() => json({ code: "INTERNAL_ERROR" }, 500));
    renderPage();
    expect(await screen.findByText(/The request failed \(INTERNAL_ERROR\)/)).toBeInTheDocument();
  });

  it("posts TBillIn with decimal strings and the exact field names", async () => {
    const calls = stubFetch(realistic);
    renderPage();
    await screen.findByRole("table");
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "91-day T-bill, auction of 14-Oct-2026" } });
    fireEvent.change(screen.getByLabelText("Tenor"), { target: { value: "91" } });
    fireEvent.change(screen.getByLabelText("Maturity date"), { target: { value: "2027-01-13" } });
    fireEvent.change(screen.getByLabelText("Cut-off yield (% a year)"), { target: { value: "6.5432" } });
    fireEvent.change(screen.getByLabelText("Official page URL"), { target: { value: "https://www.rbi.org.in/pr/1" } });
    fireEvent.change(screen.getByLabelText("Value applies as of"), { target: { value: "2026-10-14" } });
    await userEvent.click(screen.getByRole("button", { name: "Save T-bill" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.url).toBe("/api/instruments/tbill");
    expect(post.body).toEqual({
      name: "91-day T-bill, auction of 14-Oct-2026",
      tenor: "91",
      maturity: "2027-01-13",
      yield_fraction: "0.065432",
      citation: { url: "https://www.rbi.org.in/pr/1", as_of: "2026-10-14" },
    });
    expect(typeof (post.body as { yield_fraction: unknown }).yield_fraction).toBe("string");
    expect(await screen.findByText(/Saved as x/)).toBeInTheDocument();
  });

  it("refuses a non-https citation locally and sends nothing", async () => {
    const calls = stubFetch(realistic);
    renderPage();
    await screen.findByRole("table");
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "91-day T-bill" } });
    fireEvent.change(screen.getByLabelText("Maturity date"), { target: { value: "2027-01-13" } });
    fireEvent.change(screen.getByLabelText("Cut-off yield (% a year)"), { target: { value: "6.5" } });
    fireEvent.change(screen.getByLabelText("Official page URL"), { target: { value: "http://insecure.example" } });
    await userEvent.click(screen.getByRole("button", { name: "Save T-bill" }));
    expect(screen.getByText("Enter the https:// address of the official page.")).toBeInTheDocument();
    expect(screen.getByText("Enter the date the page says the value applies from.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("shows server 422 errors inline at the field", async () => {
    stubFetch((url, method) =>
      method === "POST"
        ? json({ detail: [{ loc: ["body", "yield_fraction"], msg: "Input should be less than 0.5", type: "less_than" }] }, 422)
        : realistic(url, method),
    );
    renderPage();
    await screen.findByRole("table");
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "91-day T-bill" } });
    fireEvent.change(screen.getByLabelText("Maturity date"), { target: { value: "2027-01-13" } });
    fireEvent.change(screen.getByLabelText("Cut-off yield (% a year)"), { target: { value: "65" } });
    fireEvent.change(screen.getByLabelText("Official page URL"), { target: { value: "https://www.rbi.org.in/pr/1" } });
    fireEvent.change(screen.getByLabelText("Value applies as of"), { target: { value: "2026-10-14" } });
    await userEvent.click(screen.getByRole("button", { name: "Save T-bill" }));
    expect(await screen.findByText("Input should be less than 0.5")).toBeInTheDocument();
    expect(screen.getByLabelText("Cut-off yield (% a year)")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(/the server rejected 1 field/)).toBeInTheDocument();
  });

  it("deletes a manual entry only after confirmation", async () => {
    const calls = stubFetch((url, method) => (method === "DELETE" ? json({ status: "deleted" }) : realistic(url, method)));
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: `Delete ${TB_MANUAL.name}` }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: `Confirm delete ${TB_MANUAL.name}` }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
    expect(calls.find((c) => c.method === "DELETE")!.url).toBe("/api/instruments/tbill%3A182d%3A2027-04-15");
  });
});

describe("FixedIncome — fixed deposits and bonds", () => {
  it("lists FDs with rate, tenure and a STALE badge for a rate older than 30 days", async () => {
    stubFetch(realistic);
    renderPage();
    await userEvent.click(await screen.findByRole("tab", { name: "Fixed deposits" }));
    const row = (await screen.findByRole("link", { name: FD_MANUAL.name })).closest("tr")!;
    await within(row).findByText("7.25 %");
    expect(within(row).getByText("365 days")).toBeInTheDocument();
    expect(within(row).getByText(/STALE/)).toBeInTheDocument();
    expect(within(row).getByText(/Early-exit penalty: not entered/)).toBeInTheDocument();
  });

  it("posts FDIn with decimal strings and the exact field names", async () => {
    const calls = stubFetch(realistic);
    renderPage();
    await userEvent.click(await screen.findByRole("tab", { name: "Fixed deposits" }));
    await screen.findByRole("link", { name: FD_MANUAL.name });
    fireEvent.change(screen.getByLabelText("Institution"), { target: { value: "Example Bank" } });
    fireEvent.change(screen.getByLabelText("Institution type"), { target: { value: "small_finance_bank" } });
    fireEvent.change(screen.getByLabelText("Interest rate (% a year)"), { target: { value: "7.25" } });
    fireEvent.change(screen.getByLabelText("Tenure (days)"), { target: { value: "365" } });
    fireEvent.change(screen.getByLabelText(/Premature-withdrawal penalty/), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText(/Deposits you already hold/), { target: { value: "2,50,000" } });
    fireEvent.change(screen.getByLabelText("Official page URL"), { target: { value: "https://bank.example.in/rates" } });
    fireEvent.change(screen.getByLabelText("Value applies as of"), { target: { value: "2026-10-10" } });
    await userEvent.click(screen.getByRole("button", { name: "Save fixed deposit" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.url).toBe("/api/instruments/fd");
    expect(post.body).toEqual({
      institution: "Example Bank",
      institution_type: "small_finance_bank",
      rate: "0.0725",
      tenure_days: 365,
      premature_penalty: "0.01",
      existing_deposits_at_institution: "250000",
      citation: { url: "https://bank.example.in/rates", as_of: "2026-10-10" },
    });
  });

  it("sends null for an empty penalty", async () => {
    const calls = stubFetch(realistic);
    renderPage();
    await userEvent.click(await screen.findByRole("tab", { name: "Fixed deposits" }));
    await screen.findByRole("link", { name: FD_MANUAL.name });
    fireEvent.change(screen.getByLabelText("Institution"), { target: { value: "Example Bank" } });
    fireEvent.change(screen.getByLabelText("Interest rate (% a year)"), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText("Tenure (days)"), { target: { value: "180" } });
    fireEvent.change(screen.getByLabelText("Official page URL"), { target: { value: "https://bank.example.in/rates" } });
    fireEvent.change(screen.getByLabelText("Value applies as of"), { target: { value: "2026-10-10" } });
    await userEvent.click(screen.getByRole("button", { name: "Save fixed deposit" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const body = calls.find((c) => c.method === "POST")!.body as Record<string, unknown>;
    expect(body["premature_penalty"]).toBeNull();
    expect(body["rate"]).toBe("0.07");
    expect(body["existing_deposits_at_institution"]).toBe("0");
  });

  it("states honestly that bond entry is not supported", async () => {
    stubFetch(realistic);
    renderPage();
    await userEvent.click(await screen.findByRole("tab", { name: "G-secs & bonds" }));
    expect(screen.getByText(/not yet supported/)).toBeInTheDocument();
  });
});
