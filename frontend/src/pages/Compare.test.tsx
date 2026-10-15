import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { COMPARE, COMPARE_INELIGIBLE, COMPARE_LONG, ERR_COMPARE_404, INSTRUMENTS } from "../test/analysisFixtures";
import Compare, { analysisError, parseIds } from "./Compare";
import { ApiError } from "../lib/api";

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

function Where() {
  const l = useLocation();
  return <output data-testid="where">{l.pathname + l.search}</output>;
}

const renderAt = (url: string) =>
  render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route
          path="/compare"
          element={
            <>
              <Compare />
              <Where />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );

const IDS = "tbill:182d:2027-04-13,fd:fixture-bank:180d,mf:900001";

afterEach(() => vi.unstubAllGlobals());

describe("Compare page", () => {
  it("shows an empty state and sends nothing with fewer than two instruments", () => {
    const calls = stubFetch(() => json({}));
    renderAt("/compare");
    expect(screen.getByText("Pick at least two instruments")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Compare" })).toBeDisabled();
    expect(calls).toHaveLength(0);
  });

  it("reads ids, amount and date from the URL and sends decimal strings with the exact field names", async () => {
    const calls = stubFetch(() => json(COMPARE));
    renderAt(`/compare?ids=${encodeURIComponent(IDS)}&amount=500000&date=2027-04-15`);
    await screen.findByText("Net proceeds on one axis");
    const post = calls.filter((c) => c.method === "POST");
    expect(post).toHaveLength(1);
    expect(post[0]?.url).toBe("/api/compare");
    expect(post[0]?.body).toEqual({
      instrument_ids: ["tbill:182d:2027-04-13", "fd:fixture-bank:180d", "mf:900001"],
      amount: "500000",
      withdrawal_date: "2027-04-15",
    });
    expect(typeof (post[0]?.body as { amount: unknown }).amount).toBe("string");
  });

  it("renders aligned rows from the API: q05 labelled as the illustrative downside scenario, FIXTURE shown, no forbidden words", async () => {
    stubFetch(() => json(COMPARE));
    renderAt(`/compare?ids=${encodeURIComponent(IDS)}`);
    const table = await screen.findByRole("table", { name: /comparison of 3 instruments/i });
    const q05Row = within(table).getByRole("row", { name: /^Illustrative downside scenario/ });
    // API display strings, verbatim, in request order
    expect(within(q05Row).getByRole("button", { name: /₹5,10,965\.59/ })).toBeInTheDocument();
    expect(within(q05Row).getByRole("button", { name: /₹5,11,875\.06/ })).toBeInTheDocument();
    expect(within(q05Row).getByRole("button", { name: /₹5,11,140\.45/ })).toBeInTheDocument();
    for (const header of ["Initial investment", "Middle outcome", "High-end outcome", "Liquidity", "Exit cost (ranking measure)", "Loss history", "Flags", "Eligibility"])
      expect(within(table).getByRole("rowheader", { name: new RegExp(`^${header.replace(/[()]/g, "\\$&")}`) })).toBeInTheDocument();
    expect(within(table).getAllByText("Not annualised: the horizon is shorter than 365 days.").length).toBe(3);
    expect(screen.queryByText(/Annualised equivalent/)).not.toBeInTheDocument();
    expect(screen.getByText(/FIXTURE — not market data\./)).toBeInTheDocument();
    // what would change the order: API text + gap value
    expect(screen.getByText(/would move above FIXTURE Bank FD — 180 days/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Gap in illustrative downside scenario: ₹734\.61/ })).toBeInTheDocument();
    // shared-axis band chart with direct labels
    expect(screen.getByRole("img", { name: /shared rupee axis/ })).toBeInTheDocument();
    const text = document.body.textContent?.toLowerCase() ?? "";
    expect(text).not.toContain("worst case");
    expect(text).not.toContain("probability");
  });

  it("opens the explanation drawer for a number", async () => {
    stubFetch(() => json(COMPARE));
    renderAt(`/compare?ids=${encodeURIComponent(IDS)}`);
    await screen.findByText("Net proceeds on one axis");
    await userEvent.click(screen.getAllByRole("button", { name: /Initial investment: ₹5,00,000\.00/ })[0]!);
    expect(await screen.findByRole("heading", { name: /Explain: Initial investment/ })).toBeInTheDocument();
  });

  it("shows the annualised figure only where the API marks it as a labelled secondary", async () => {
    stubFetch(() => json(COMPARE_LONG));
    renderAt("/compare?ids=mf:900001,mf:900003");
    const row = await screen.findByRole("row", { name: /^Annualised equivalent \(secondary\)/ });
    expect(within(row).getByRole("button", { name: /Annualised equivalent \(q50\) — secondary: 4\.65%/ })).toBeInTheDocument();
  });

  it("an instrument that cannot be evaluated shows its reasons and dashes, never 0", async () => {
    stubFetch(() => json(COMPARE_INELIGIBLE));
    renderAt("/compare?ids=tbill:182d:2027-04-13,mf:900001&date=2026-11-14");
    const table = await screen.findByRole("table", { name: /comparison of 2 instruments/i });
    expect(within(table).getByText("Not evaluated")).toBeInTheDocument();
    expect(within(table).getByText("HORIZON_MISMATCH: matures after your withdrawal date")).toBeInTheDocument();
    const q05Row = within(table).getByRole("row", { name: /^Illustrative downside scenario/ });
    const tbillCell = within(q05Row).getAllByRole("cell")[0]!;
    expect(tbillCell).toHaveTextContent("—");
    expect(tbillCell).not.toHaveTextContent(/₹/);
    expect(screen.getByText(/Not in the order \(not evaluated\): FIXTURE 182-day T-bill/)).toBeInTheDocument();
    expect(screen.getByText(/ILLUSTRATIVE — values not taken from your request or profile/)).toBeInTheDocument();
  });

  it("shows the API's refusal message on an error", async () => {
    stubFetch(() => json(ERR_COMPARE_404, 404));
    renderAt("/compare?ids=mf:900001,mf:nope");
    expect(await screen.findByRole("alert")).toHaveTextContent("instrument 'mf:nope' is not in the local store (NOT_FOUND)");
  });

  it("adding an instrument with the picker keeps ids in the URL and re-runs", async () => {
    const calls = stubFetch((url) => (url.startsWith("/api/instruments") ? json(INSTRUMENTS) : json(COMPARE)));
    renderAt("/compare?ids=mf:900001");
    await userEvent.type(screen.getByLabelText("Add an instrument"), "FIXTURE");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(calls[0]?.url).toBe("/api/instruments?q=FIXTURE");
    // the already-selected instrument is not offered again
    expect(screen.queryByRole("button", { name: /Select FIXTURE Liquid Fund A/ })).not.toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Select FIXTURE 182-day T-bill" }));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/compare?ids=mf%3A900001%2Ctbill%3A182d%3A2027-04-13"));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ instrument_ids: ["mf:900001", "tbill:182d:2027-04-13"] });
  });

  it("rejects an invalid amount without sending a request", async () => {
    const calls = stubFetch(() => json(COMPARE));
    renderAt(`/compare?ids=${encodeURIComponent(IDS)}`);
    await screen.findByText("Net proceeds on one axis");
    const before = calls.length;
    await userEvent.type(screen.getByLabelText("Amount in ₹ (optional)"), "5,00,000");
    await userEvent.click(screen.getByRole("button", { name: "Compare" }));
    expect(screen.getByText(/Enter a positive amount in rupees/)).toBeInTheDocument();
    expect(calls.length).toBe(before);
  });
});

describe("helpers", () => {
  it("parseIds keeps 2–4 distinct ids in order", () => {
    expect(parseIds("a, b,a,,c,d,e")).toEqual(["a", "b", "c", "d"]);
    expect(parseIds(null)).toEqual([]);
  });
  it("analysisError reads {detail: {code, message}} and FastAPI 422 lists", () => {
    expect(analysisError(new ApiError(404, "REQUEST_FAILED", ERR_COMPARE_404))).toBe("instrument 'mf:nope' is not in the local store (NOT_FOUND)");
    const v = new ApiError(422, "REQUEST_FAILED", { detail: [{ loc: ["body", "shocks", "equity_pct"], msg: "Input should be less than or equal to 0" }] });
    expect(analysisError(v)).toContain("shocks.equity_pct: Input should be less than or equal to 0");
  });
});

describe("Compare — eligibility row", () => {
  it("shows a neutral ✓ Evaluated chip, and a plain-English label beside each verbatim engine reason", async () => {
    stubFetch(() => json(COMPARE_INELIGIBLE));
    renderAt("/compare?ids=tbill:182d:2027-04-13,mf:900001&date=2026-11-14");
    const table = await screen.findByRole("table", { name: /comparison of 2 instruments/i });
    const row = within(table).getByRole("row", { name: /^Eligibility/ });
    expect(within(row).getByText("Evaluated")).toBeInTheDocument();
    expect(within(row).getByText(/Does not fit your withdrawal date/)).toBeInTheDocument();
    expect(within(row).getByText("HORIZON_MISMATCH: matures after your withdrawal date")).toHaveClass("code-suffix");
  });
});
