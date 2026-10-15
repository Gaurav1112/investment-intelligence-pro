import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FundFacts, FundFactsResponse } from "../lib/types-inputs";
import { FundFactsPanel } from "./FundFactsPanel";

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
afterEach(() => vi.unstubAllGlobals());

const URL_ = "/api/inputs/fund-facts/mf%3A119551";

const FACTS: FundFacts = {
  fact_id: 3, as_of_month: "2026-08", as_of_date: "2026-08-31", modified_duration: "2.35", macaulay_duration: "2.48", ytm: "0.0712",
  average_maturity_years: null, expense_ratio: "0.0035", expense_ratio_kind: "TER", lowest_rating: "AA", share_below_aaa: "0.18",
  share_sovereign_cash: "0.32", citation_url: "https://amc.example.in/factsheet-aug-2026.pdf", citation_note: "page 14",
  verified_on: "2026-09-12", entered_at: "2026-09-12T05:00:00+00:00", age_days: 45 + 1, freshness: "STALE",
};
const resp = (latest: FundFacts | null): FundFactsResponse => ({ instrument_id: "mf:119551", stale_after_days: 45, latest, history: latest ? [latest] : [] });

type Call = { url: string; method: string; body: unknown };
function stub(get: () => FundFactsResponse, post?: (b: unknown) => Response) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, method, body });
      if (method === "POST") return post ? post(body) : json({ fact_id: 9, instrument_id: "mf:119551" });
      return json(get());
    }),
  );
  return calls;
}

describe("FundFactsPanel", () => {
  it("renders the latest facts with units, as-of date, citation and a STALE badge", async () => {
    stub(() => resp(FACTS));
    render(<FundFactsPanel instrumentId="mf:119551" />);
    expect(await screen.findByText("2026-08")).toBeInTheDocument();
    expect(screen.getByText(/portfolio date 31-Aug-2026/)).toBeInTheDocument();
    expect(screen.getByText("STALE")).toBeInTheDocument();
    expect(screen.getByText(/older than 45 days/)).toBeInTheDocument();
    const dl = screen.getByText("Modified duration").closest("dl")!;
    expect(within(dl).getByText("2.35 years")).toBeInTheDocument();
    expect(within(dl).getByText(/7\.12/)).toBeInTheDocument();
    expect(within(dl).getByText(/\(TER\)/)).toBeInTheDocument();
    expect(within(dl).getByText("AA")).toBeInTheDocument();
    expect(within(dl).getAllByText("not disclosed / not entered")).toHaveLength(1); // average maturity
    expect(screen.getByRole("link", { name: "amc.example.in" })).toHaveAttribute("href", FACTS.citation_url);
  });

  it("shows a fresh entry without the STALE badge", async () => {
    stub(() => resp({ ...FACTS, freshness: "FRESH", age_days: 12 }));
    render(<FundFactsPanel instrumentId="mf:119551" />);
    expect(await screen.findByText("MANUAL ENTRY")).toBeInTheDocument();
    expect(screen.queryByText("STALE")).not.toBeInTheDocument();
  });

  it("shows an explicit empty state when no facts are entered", async () => {
    stub(() => resp(null));
    render(<FundFactsPanel instrumentId="mf:119551" />);
    expect(
      await screen.findByText(/No factsheet facts entered — rate\/spread shocks, yield-carry ranges and the credit-floor check are unavailable/),
    ).toBeInTheDocument();
  });

  it("posts the exact body with blank optional fields omitted and refreshes after save", async () => {
    let latest: FundFacts | null = null;
    const calls = stub(() => resp(latest), () => {
      latest = { ...FACTS, freshness: "FRESH", age_days: 5 };
      return json({ fact_id: 9, instrument_id: "mf:119551" });
    });
    const user = userEvent.setup();
    render(<FundFactsPanel instrumentId="mf:119551" />);
    await user.click(await screen.findByRole("button", { name: "Enter factsheet facts" }));
    const form = screen.getByRole("form", { name: "Enter factsheet facts" });
    // no number is prefilled
    for (const input of within(form).getAllByRole("textbox")) expect(input).toHaveValue("");
    await user.type(within(form).getByLabelText(/Factsheet month/), "2026-09");
    await user.type(within(form).getByLabelText("Modified duration (years)"), "2.35");
    await user.type(within(form).getByLabelText("Portfolio YTM (%)"), "7.12");
    await user.selectOptions(within(form).getByLabelText("Lowest credit rating held"), "AA");
    await user.type(within(form).getByLabelText("Official page URL"), "https://amc.example.in/fs.pdf");
    await user.type(within(form).getByLabelText("Value applies as of"), "2026-10-12");
    await user.click(within(form).getByRole("button", { name: "Save factsheet facts" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Saved");
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.url).toBe(URL_);
    expect(post.body).toEqual({
      as_of_month: "2026-09",
      modified_duration: "2.35",
      ytm: "0.0712",
      lowest_rating: "AA",
      citation: { url: "https://amc.example.in/fs.pdf", as_of: "2026-10-12" },
    });
    expect(calls.filter((c) => c.method === "GET").length).toBe(2); // reloaded after save
  });

  it("refuses to post without any metric, and shows backend validation errors", async () => {
    const calls = stub(() => resp(null), () =>
      json({ detail: [{ loc: ["body", "as_of_month"], msg: "factsheet month has not ended yet", type: "value_error" }] }, 422),
    );
    const user = userEvent.setup();
    render(<FundFactsPanel instrumentId="mf:119551" />);
    await user.click(await screen.findByRole("button", { name: "Enter factsheet facts" }));
    const form = screen.getByRole("form", { name: "Enter factsheet facts" });
    await user.type(within(form).getByLabelText(/Factsheet month/), "2026-10");
    await user.type(within(form).getByLabelText("Official page URL"), "https://amc.example.in/fs.pdf");
    await user.type(within(form).getByLabelText("Value applies as of"), "2026-10-12");
    await user.click(within(form).getByRole("button", { name: "Save factsheet facts" }));
    expect(await screen.findByText("Enter at least one figure from the factsheet.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    await user.type(within(form).getByLabelText("Modified duration (years)"), "1.1");
    await user.click(within(form).getByRole("button", { name: "Save factsheet facts" }));
    expect(await screen.findByText("factsheet month has not ended yet")).toBeInTheDocument();
  });
});
