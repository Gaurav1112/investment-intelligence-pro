import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FdRatesResponse } from "../lib/types-inputs";
import { FdCardRates } from "./FdCardRates";

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
afterEach(() => vi.unstubAllGlobals());

// Fictional bank and rates.
const RATES: FdRatesResponse = {
  as_of: "2026-10-15",
  stale_after_days: 30,
  tables: [
    {
      table_id: 2, institution: "FIXTURE Bank", institution_key: "fixture-bank", as_of: "2026-10-10", premature_rate_basis: "period_card",
      citation_url: "https://example.test/rates", citation_note: "", entered_at: "2026-10-15T06:00:00+00:00",
      buckets: [{ min_days: 7, max_days: 45, rate: "0.03" }, { min_days: 46, max_days: 179, rate: "0.055" }],
      age_days: 5, freshness: "MANUAL", current: true,
    },
    {
      table_id: 1, institution: "FIXTURE Bank", institution_key: "fixture-bank", as_of: "2026-09-01", premature_rate_basis: "min(booked,period_card)",
      citation_url: "https://example.test/old", citation_note: "old page", entered_at: "2026-10-15T06:00:00+00:00",
      buckets: [{ min_days: 7, max_days: 45, rate: "0.025" }],
      age_days: 44, freshness: "STALE", current: false,
    },
  ],
}; // prettier-ignore

type Call = { url: string; method: string; body: unknown };
function stub(post: (body: unknown) => Response = () => json({ table_id: 3, institution_key: "fixture-bank" })) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, method, body });
      if (url === "/api/inputs/fd-rates" && method === "POST") return post(body);
      if (url === "/api/inputs/fd-rates") return json(RATES);
      return json({ code: "NOT_FOUND" }, 404);
    }),
  );
  return calls;
}

describe("FD card-rate tables", () => {
  it("lists each table with the backend's freshness and marks the one analysis uses", async () => {
    stub();
    render(<FdCardRates />);
    const current = await screen.findByRole("table", { name: /FIXTURE Bank from 10-Oct-2026/ });
    expect(within(current).getByText("7 – 45")).toBeInTheDocument();
    expect(within(current).getByText("3.00 %")).toBeInTheDocument();
    expect(screen.getByText("used for analysis")).toBeInTheDocument();
    expect(screen.getByText(/superseded by a later table/)).toBeInTheDocument();
    expect(screen.getAllByText(/STALE/).length).toBeGreaterThan(0);
    expect(screen.getByText("Early withdrawal: Lower of the booked rate and the card rate for the period held")).toBeInTheDocument();
  });

  it("sends percent inputs as exact fraction strings with the citation", async () => {
    const calls = stub();
    const user = userEvent.setup();
    render(<FdCardRates />);
    await screen.findByText("used for analysis");
    await user.type(screen.getByLabelText("Bank"), "FIXTURE Bank");
    await user.type(screen.getByLabelText("From (days)"), "7");
    await user.type(screen.getByLabelText("To (days)"), "45");
    await user.type(screen.getByLabelText("Rate (% a year)"), "7.25");
    await user.click(screen.getByRole("button", { name: "Add tenure band" }));
    const band2 = screen.getByRole("group", { name: "Tenure band 2" });
    await user.type(within(band2).getByLabelText("From (days)"), "46");
    await user.type(within(band2).getByLabelText("To (days)"), "90");
    await user.type(within(band2).getByLabelText("Rate (% a year)"), "7.5");
    await user.type(screen.getByLabelText("Official page URL"), "https://example.test/rates");
    await user.type(screen.getByLabelText("Value applies as of"), "2026-10-10");
    await user.click(screen.getByRole("button", { name: "Save card-rate table" }));
    await screen.findByText("Saved card-rate table for FIXTURE Bank.");
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({
      institution: "FIXTURE Bank",
      buckets: [{ min_days: 7, max_days: 45, rate: "0.0725" }, { min_days: 46, max_days: 90, rate: "0.075" }],
      premature_rate_basis: "period_card",
      citation: { url: "https://example.test/rates", as_of: "2026-10-10" },
    });
  });

  it("blocks an incomplete table locally and shows the server's table-level error", async () => {
    const calls = stub(() => json({ detail: [{ loc: ["body"], msg: "Value error, card-rate buckets overlap", type: "value_error" }] }, 422));
    const user = userEvent.setup();
    render(<FdCardRates />);
    await screen.findByText("used for analysis");
    await user.click(screen.getByRole("button", { name: "Save card-rate table" }));
    expect(screen.getByLabelText("Bank")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Rate (% a year)")).toHaveAttribute("aria-invalid", "true");
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    await user.type(screen.getByLabelText("Bank"), "FIXTURE Bank");
    await user.type(screen.getByLabelText("From (days)"), "7");
    await user.type(screen.getByLabelText("To (days)"), "45");
    await user.type(screen.getByLabelText("Rate (% a year)"), "3");
    await user.type(screen.getByLabelText("Official page URL"), "https://example.test/rates");
    await user.type(screen.getByLabelText("Value applies as of"), "2026-10-10");
    await user.click(screen.getByRole("button", { name: "Save card-rate table" }));
    await waitFor(() => expect(screen.getByText(/Not saved: Value error, card-rate buckets overlap/)).toBeInTheDocument());
  });
});
