import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ProfileProvider } from "../lib/profile";
import type { FeasibilityResponse, ShockKey } from "../lib/types";
import {
  ERR_FEASIBILITY_NO_SERIES,
  FEASIBILITY_1Y,
  FEASIBILITY_5Y_LOW_EVIDENCE,
  SCENARIO_EQUITY_ZERO,
  SCENARIO_FD_NOT_APPLICABLE,
} from "../test/analysisFixtures";
import Scenarios, { quantityText, shocksFrom, targetFraction } from "./Scenarios";

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

const PROFILE = (aspiration: string | null) => ({
  profile: {
    amount: null,
    withdrawal_date: null,
    objective: null,
    loss_acceptable: null,
    max_loss_fraction: null,
    early_need: null,
    max_days_to_cash: null,
    credit_floor: null,
    excluded_kinds: [],
    tax_regime: null,
    slab_rate: null,
    return_aspiration: aspiration,
  },
  mode: "EXPLORATION",
  missing: [],
  horizon_days: null,
  conflicts: [],
});

const renderAt = (url: string) =>
  render(
    <MemoryRouter initialEntries={[url]}>
      <ProfileProvider>
        <Routes>
          <Route path="/scenarios" element={<Scenarios />} />
        </Routes>
      </ProfileProvider>
    </MemoryRouter>,
  );

afterEach(() => vi.unstubAllGlobals());

const posts = (calls: Call[]) => calls.filter((c) => c.method === "POST");
const text = () => document.body.textContent?.toLowerCase() ?? "";

// ------------------------------------------------------------------ scenario lab

describe("Scenario lab", () => {
  it("sends the shocks as decimal strings with the exact field names, and a zero shock shows the API's zero impact", async () => {
    const calls = stubFetch((url) => (url === "/api/profile" ? json(PROFILE(null)) : json(SCENARIO_EQUITY_ZERO)));
    renderAt("/scenarios?id=mf:900003");
    await userEvent.type(screen.getByLabelText("Equity fall (%)"), "0");
    await userEvent.click(screen.getByRole("button", { name: "Run scenario" }));
    await screen.findByText("Base (no shock)");
    expect(posts(calls)).toHaveLength(1);
    expect(posts(calls)[0]?.url).toBe("/api/scenario");
    expect(posts(calls)[0]?.body).toEqual({ instrument_id: "mf:900003", shocks: { equity_pct: "0" } });
    // impact column renders the engine's "₹0.00" three times (q05, q50, q95) — rendered, not computed
    const impacts = screen.getAllByRole("button", { name: /^Impact \(q\d\d\): ₹0\.00/ });
    expect(impacts).toHaveLength(3);
    expect(screen.getAllByText(/before tax/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Impacts are before tax\./)).toBeInTheDocument();
    // echoed inputs and the scenario label
    expect(within(screen.getByRole("list", { name: "Echoed shock inputs" })).getByText(/Equity fall \(%\)/)).toHaveTextContent("Equity fall (%): 0");
    expect(screen.getByText("Stress scenario")).toBeInTheDocument();
    expect(screen.getByText(/FIXTURE — not market data\./)).toBeInTheDocument();
    expect(text()).not.toContain("probability");
    expect(text()).not.toContain("worst case");
  });

  it("not_applicable shocks render as text with their reason, never as 0", async () => {
    const calls = stubFetch((url) => (url === "/api/profile" ? json(PROFILE(null)) : json(SCENARIO_FD_NOT_APPLICABLE)));
    renderAt("/scenarios?id=fd:fixture-bank:180d");
    await userEvent.type(screen.getByLabelText("Interest-rate change (basis points)"), "100");
    await userEvent.type(screen.getByLabelText("Equity fall (%)"), "-20");
    await userEvent.type(screen.getByLabelText("Withdrawal date (optional)"), "2027-04-15");
    await userEvent.click(screen.getByRole("button", { name: "Run scenario" }));
    await screen.findByText("Base (no shock)");
    expect(posts(calls)[0]?.body).toEqual({
      instrument_id: "fd:fixture-bank:180d",
      withdrawal_date: "2027-04-15",
      shocks: { rate_bp: "100", equity_pct: "-20" },
    });
    const notes = screen.getAllByRole("note").filter((n) => n.classList.contains("shock-na"));
    expect(notes).toHaveLength(2);
    expect(notes[0]).toHaveTextContent("Not applicable: A fixed deposit pays its booked contractual rate; later rate changes do not alter it.");
    expect(notes[1]).toHaveTextContent("Not applicable: Equity shocks apply only to equity-scheme funds");
    for (const n of notes) {
      expect(n).not.toHaveTextContent("₹");
      expect(n).not.toHaveTextContent(/\b0\.00\b/);
      expect(within(n).queryByRole("button")).not.toBeInTheDocument();
    }
  });

  it("validates shocks before sending: out-of-range, no shock, no instrument", async () => {
    const calls = stubFetch((url) => (url === "/api/profile" ? json(PROFILE(null)) : json(SCENARIO_EQUITY_ZERO)));
    renderAt("/scenarios?id=mf:900003");
    await userEvent.click(screen.getByRole("button", { name: "Run scenario" }));
    expect(screen.getByText("Enter at least one shock.")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Equity fall (%)"), "10");
    await userEvent.click(screen.getByRole("button", { name: "Run scenario" }));
    expect(screen.getByText(/Out of range: 0 or negative/)).toBeInTheDocument();
    expect(posts(calls)).toHaveLength(0);
  });

  it("shows the API's validation message on a 422", async () => {
    stubFetch((url) =>
      url === "/api/profile"
        ? json(PROFILE(null))
        : json({ detail: [{ type: "less_than_equal", loc: ["body", "shocks", "rate_bp"], msg: "Input should be less than or equal to 1000" }] }, 422),
    );
    renderAt("/scenarios?id=mf:900003");
    await userEvent.type(screen.getByLabelText("Interest-rate change (basis points)"), "999");
    await userEvent.click(screen.getByRole("button", { name: "Run scenario" }));
    expect(await screen.findByText(/shocks\.rate_bp: Input should be less than or equal to 1000/)).toBeInTheDocument();
  });

  it("shocksFrom: decimal strings, whole-number exit days, bounds", () => {
    const empty: Record<ShockKey, string> = {
      rate_bp: "",
      spread_bp: "",
      equity_pct: "",
      inflation_pct: "",
      exit_before_maturity_days: "",
      reinvestment_rate: "",
    };
    expect(shocksFrom({ ...empty, rate_bp: "50", exit_before_maturity_days: "60", reinvestment_rate: "0.05" })).toEqual({
      shocks: { rate_bp: "50", exit_before_maturity_days: 60, reinvestment_rate: "0.05" },
      problems: {},
    });
    expect(shocksFrom({ ...empty, equity_pct: "−12.5" }).shocks).toEqual({ equity_pct: "-12.5" });
    expect(Object.keys(shocksFrom({ ...empty, rate_bp: "1001", exit_before_maturity_days: "1.5", reinvestment_rate: "-1" }).problems).sort()).toEqual([
      "exit_before_maturity_days",
      "rate_bp",
      "reinvestment_rate",
    ]);
    expect(shocksFrom({ ...empty, rate_bp: "1e3" }).problems.rate_bp).toBeDefined();
  });

  it("quantityText never shows raw internal precision", () => {
    expect(quantityText({ name: "value", value: "74935.28662757419251938899773492924", unit: "INR" })).toBe("₹74,935.29");
    expect(quantityText({ name: "delta_yield", value: "0.0050", unit: "fraction" })).toBe("+0.50\u202f%");
    expect(quantityText({ name: "beta", value: "1", unit: "ratio" })).toBe("1.0000");
    expect(quantityText({ name: "exit_after_days", value: "60", unit: "days" })).toBe("60 days");
  });
});

// ------------------------------------------------------------------ return-target feasibility

const FEAS_URL = "/scenarios?tab=feasibility&id=mf:900003";

describe("Return-target feasibility", () => {
  it("pre-fills the target from the profile aspiration and sends target_annual as a fraction string", async () => {
    const calls = stubFetch((url) => (url === "/api/profile" ? json(PROFILE("0.22")) : json(FEASIBILITY_1Y)));
    renderAt(FEAS_URL);
    const input = screen.getByLabelText("Target annual return (%)");
    await waitFor(() => expect(input).toHaveValue("22"));
    expect(screen.getByText("Pre-filled from the aspiration in your profile.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show historical frequency" }));
    await screen.findByText(/20 historical outcomes/);
    expect(posts(calls)).toHaveLength(1);
    expect(posts(calls)[0]?.url).toBe("/api/feasibility");
    expect(posts(calls)[0]?.body).toEqual({ instrument_id: "mf:900003", target_annual: "0.22", horizon_years: 1 });
  });

  it("renders counts, frequencies, percentiles, drawdowns with dates, caveats and the FIXTURE flag — copy is neutral", async () => {
    stubFetch((url) => (url === "/api/profile" ? json(PROFILE(null)) : json(FEASIBILITY_1Y)));
    renderAt(FEAS_URL);
    await userEvent.type(screen.getByLabelText("Target annual return (%)"), "20");
    await userEvent.selectOptions(screen.getByLabelText("Horizon"), "3");
    await userEvent.click(screen.getByRole("button", { name: "Show historical frequency" }));
    await screen.findByText(/20 historical outcomes/);
    expect(screen.getByText("11 of 156 overlapping windows")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Historical frequency of reaching the target: 7\.05%/ })).toBeInTheDocument();
    expect(screen.getByText("112 of 156 overlapping windows")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Historical frequency of loss: 71\.79%/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /p5 of window CAGR: -26\.98%/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Worst drawdown inside a window that reached the target: -26\.59%/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Median in-window low point in ₹: ₹75,654\.63/ })).toBeInTheDocument();
    expect(screen.getByText(/peak 27-Mar-2013, low 09-Sep-2026, not yet recovered \(ongoing\)/)).toBeInTheDocument();
    expect(screen.getByText(/About/)).toHaveTextContent("About 13 independent 1-year periods behind 156 overlapping windows");
    expect(screen.getByText("History begins after the 2008–09 crash.")).toBeInTheDocument();
    expect(screen.getByText(/Overlapping windows share most of their months/)).toBeInTheDocument();
    expect(screen.getByText(/FIXTURE — not market data\./)).toBeInTheDocument();
    expect(text()).toContain("historical frequency, not a forecast");
    expect(text()).not.toContain("probability");
    expect(text()).not.toContain("worst case");
    expect(text()).not.toMatch(/more risk|increase (your )?risk|take on risk/);
  });

  it("the DotPlot shows the engine's hit count (not one the UI counted)", async () => {
    // 1 of the 20 dot values is ≥ 20 %, but the engine says 7: the page must show the engine's number.
    const engineSays: FeasibilityResponse = { ...FEASIBILITY_1Y, dots: { ...FEASIBILITY_1Y.dots!, reached_target: 7, reached_target_display: "7 of 20 dots reached 20.00% p.a." } };
    stubFetch((url) => (url === "/api/profile" ? json(PROFILE("0.20")) : json(engineSays)));
    renderAt(FEAS_URL);
    await waitFor(() => expect(screen.getByLabelText("Target annual return (%)")).toHaveValue("20"));
    await userEvent.click(screen.getByRole("button", { name: "Show historical frequency" }));
    const fig = (await screen.findByRole("img", { name: /Compound annual return of past 1-year windows/ })).closest("figure")!;
    expect(within(fig).getByText(/Reached or beat the target in 7 of 20\./)).toBeInTheDocument();
    expect(fig.querySelectorAll("circle.dot")).toHaveLength(20);
    expect(fig.querySelector(".target-line")).not.toBeNull();
    expect(screen.getByText(/7 of 20 dots reached 20\.00% p\.a\./)).toBeInTheDocument();
  });

  it("LOW EVIDENCE: banner, counts only, no frequencies and no dot plot", async () => {
    stubFetch((url) => (url === "/api/profile" ? json(PROFILE("0.20")) : json(FEASIBILITY_5Y_LOW_EVIDENCE)));
    renderAt(FEAS_URL);
    await waitFor(() => expect(screen.getByLabelText("Target annual return (%)")).toHaveValue("20"));
    await userEvent.click(screen.getByRole("button", { name: "Show historical frequency" }));
    expect(await screen.findByText(/fewer than 5 independent periods — counts only, no percentages\./)).toBeInTheDocument();
    expect(screen.getByText("0 of 108 overlapping windows")).toBeInTheDocument();
    expect(screen.getByText("104 of 108 overlapping windows")).toBeInTheDocument();
    expect(screen.getAllByText("counts only")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: /Historical frequency of/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /Compound annual return/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Dot plot not shown/)).toBeInTheDocument();
    expect(screen.getByText(/no window reached the target/)).toBeInTheDocument();
    expect(text()).not.toContain("probability");
  });

  it("a refusal says exactly why and what would be needed", async () => {
    const refused: FeasibilityResponse = {
      as_of: "2026-10-15",
      request: { instrument_id: "mf:990001", target_annual: "0.20", horizon_years: 1, mode: "CAGR", as_of: "2026-10-15" },
      instrument: { instrument_id: "mf:990001", name: "FIXTURE Short-History Equity Fund", category: "Equity Scheme - Large Cap Fund" },
      fixture: true,
      frequency_label: "historical frequency (overlapping windows), not a forecast",
      disclaimer: "Not a recommendation. Not a forecast. Past outcomes do not indicate future results.",
      status: "REFUSED",
      evidence_level: "REFUSED",
      low_evidence: false,
      refusal: {
        id: "mf:990001.feasibility",
        label: "Return-target feasibility",
        status: "refused",
        code: "INSUFFICIENT_HISTORY",
        reason: "series spans 1.2 years; need at least 2 years for a 1-year horizon",
        value: null,
      },
      run: { input_hash: "a".repeat(64), result_hash: "b".repeat(64), versions: {} },
    };
    stubFetch((url) => (url === "/api/profile" ? json(PROFILE("0.20")) : json(refused)));
    renderAt("/scenarios?tab=feasibility&id=mf:990001");
    await waitFor(() => expect(screen.getByLabelText("Target annual return (%)")).toHaveValue("20"));
    await userEvent.click(screen.getByRole("button", { name: "Show historical frequency" }));
    expect(await screen.findByText(/Not shown: series spans 1\.2 years; need at least 2 years for a 1-year horizon/)).toBeInTheDocument();
    expect(screen.getByText(/INSUFFICIENT_HISTORY/)).toBeInTheDocument();
    expect(screen.getByText(/Backfill longer history/)).toBeInTheDocument();
    expect(screen.queryByText(/overlapping windows$/)).not.toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("shows the API error for an instrument without a NAV series", async () => {
    stubFetch((url) => (url === "/api/profile" ? json(PROFILE("0.20")) : json(ERR_FEASIBILITY_NO_SERIES, 422)));
    renderAt("/scenarios?tab=feasibility&id=fd:fixture-bank:180d");
    await waitFor(() => expect(screen.getByLabelText("Target annual return (%)")).toHaveValue("20"));
    await userEvent.click(screen.getByRole("button", { name: "Show historical frequency" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("this analysis needs a stored NAV series (mutual fund schemes only) (NO_SERIES)");
  });

  it("validates the target before sending", async () => {
    const calls = stubFetch((url) => (url === "/api/profile" ? json(PROFILE(null)) : json(FEASIBILITY_1Y)));
    renderAt(FEAS_URL);
    await userEvent.type(screen.getByLabelText("Target annual return (%)"), "20%");
    await userEvent.click(screen.getByRole("button", { name: "Show historical frequency" }));
    expect(screen.getByText(/Enter a plain number of percent/)).toBeInTheDocument();
    expect(posts(calls)).toHaveLength(0);
  });

  it("targetFraction converts % to an exact fraction string", () => {
    expect(targetFraction("20")).toEqual({ fraction: "0.2", problem: null });
    expect(targetFraction("22.5")).toEqual({ fraction: "0.225", problem: null });
    expect(targetFraction("100").fraction).toBe("1");
    expect(targetFraction("100.01").problem).toMatch(/at most 100/);
    expect(targetFraction("").problem).toMatch(/Enter a target/);
  });
});
