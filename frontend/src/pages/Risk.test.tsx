import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ERR_FEASIBILITY_NO_SERIES, FORECAST, FORECAST_REFUSED, RISK_EQUITY, RISK_LIQUID } from "../test/analysisFixtures";
import Risk from "./Risk";
import type { YieldCarry } from "../lib/types";

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

const renderAt = (url: string) =>
  render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/risk" element={<Risk />} />
      </Routes>
    </MemoryRouter>,
  );

afterEach(() => vi.unstubAllGlobals());

const metricsList = () => screen.getByText("Annualised volatility").closest("dl")!;

describe("Risk page", () => {
  it("asks for an instrument and sends nothing without one", () => {
    const calls = stubFetch(() => json({}));
    renderAt("/risk");
    expect(screen.getByText(/Pick a mutual fund scheme/)).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("reads ?id= and shows Explained metrics with drawdown dates, VaR/CVaR in % and ₹, and refusals in words", async () => {
    const calls = stubFetch((url) =>
      url.startsWith("/api/risk/")
        ? json(RISK_EQUITY)
        : url.startsWith("/api/instruments/")
          ? json({ instrument: { name: "FIXTURE Large Cap Fund C — Direct · Growth", origin: "fixture" } })
          : json(FORECAST),
    );
    renderAt("/risk?id=mf:900003");
    await screen.findByText("Annualised volatility");
    expect(calls.map((c) => c.url).sort()).toEqual([
      "/api/forecast/mf%3A900003",
      "/api/instruments/mf%3A900003/summary", // the name comes from the summary, never the full-history detail (A06)
      "/api/risk/mf%3A900003",
    ]);
    // An id from the URL is shown by its name, not as a bare internal id (live-browser finding).
    expect((await screen.findAllByText("FIXTURE Large Cap Fund C — Direct · Growth")).length).toBeGreaterThan(0);
    const dl = metricsList();
    expect(within(dl).getByRole("button", { name: /Annualised volatility: 24\.09%/ })).toBeInTheDocument();
    expect(within(dl).getByRole("button", { name: /Maximum drawdown: 80\.25%/ })).toBeInTheDocument();
    expect(within(dl).getByText(/peak 27-Mar-2013 · low 09-Sep-2026 · not yet recovered/)).toBeInTheDocument();
    expect(within(dl).getByText(/Not shown: insufficient data: no point-in-time 91-day T-bill yield series/)).toBeInTheDocument();
    const var95 = screen.getByRole("rowheader", { name: "1-day historical VaR at 95 %" }).closest("tr")!;
    expect(within(var95).getByRole("button", { name: /VaR at 95 %: 1\.79%/ })).toBeInTheDocument();
    expect(within(var95).getByRole("button", { name: /VaR at 95 % in ₹: ₹1,792\.18/ })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "1-day historical CVaR at 99 %" })).toBeInTheDocument();
    expect(screen.getAllByText(/FIXTURE — not market data\./).length).toBeGreaterThan(0);
    const text = document.body.textContent?.toLowerCase() ?? "";
    expect(text).not.toContain("probability");
    expect(text).not.toContain("worst case");
  });

  it("gated metrics appear as 'Not shown: <reason>', never as a number or 0", async () => {
    stubFetch((url) => (url.startsWith("/api/risk/") ? json(RISK_LIQUID) : json(FORECAST)));
    renderAt("/risk?id=mf:900001");
    await screen.findByText("Annualised volatility");
    const dl = metricsList();
    const vol = within(dl).getByText("Annualised volatility").nextElementSibling as HTMLElement;
    expect(vol).toHaveTextContent(/^Not shown: refused for smoothed NAV: liquid fund NAVs carry the weekend-accrual effect/);
    expect(vol).toHaveTextContent("REFUSED_SMOOTHED_NAV");
    expect(within(vol).queryByRole("button")).not.toBeInTheDocument();
    expect(vol).not.toHaveTextContent(/\d+\.\d+\s*%/);
    expect(within(dl).getByText(/Not shown: refused for smoothed NAV: Sharpe needs monthly returns/)).toBeInTheDocument();
  });

  it("shows the scenario range labelled as not a forecast, the baseline comparator, validation, unreliable_when and promotion", async () => {
    stubFetch((url) => (url.startsWith("/api/risk/") ? json(RISK_EQUITY) : json(FORECAST)));
    renderAt("/risk?id=mf:900002");
    expect(await screen.findByText("scenario range, not a forecast")).toBeInTheDocument();
    expect(screen.getByText(/Promotion:/)).toHaveTextContent("Promotion: baseline retained");
    expect(screen.getByRole("button", { name: /Scenario-range return at level 0\.05: 0\.90%/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Amount at level 0\.05 \(before costs, tax\): ₹1,00,903\.82/ })).toBeInTheDocument();
    expect(screen.getByText(/zero drift \(random walk\) point comparator \(B3_ZERO_DRIFT\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Empirical coverage of the 80 % band: 93\.75%/ })).toBeInTheDocument();
    expect(screen.getByText(/15 of 16 held-out outcomes inside the band/)).toBeInTheDocument();
    expect(screen.getByText(/Kupiec p-value 0\.1189/)).toBeInTheDocument(); // rounded for display, no raw precision
    expect(screen.queryByText(/0\.11889256546553112/)).not.toBeInTheDocument();
    expect(screen.getByText("Unreliable when")).toBeInTheDocument();
    expect(screen.getByText(/credit event affecting a holding/)).toBeInTheDocument();
  });

  it("a refused scenario range says why", async () => {
    stubFetch((url) => (url.startsWith("/api/risk/") ? json(RISK_EQUITY) : json(FORECAST_REFUSED)));
    renderAt("/risk?id=mf:900002&horizon_days=3650");
    expect(await screen.findByText(/Not shown: n_eff = 1 < 10: forecast suppressed/)).toBeInTheDocument();
    expect(screen.getByText(/Promotion:/)).toHaveTextContent("baseline retained");
  });

  it("applies a horizon to the forecast request via the URL", async () => {
    const calls = stubFetch((url) => (url.startsWith("/api/risk/") ? json(RISK_EQUITY) : json(FORECAST)));
    renderAt("/risk?id=mf:900002");
    await screen.findByText("scenario range, not a forecast");
    await userEvent.type(screen.getByLabelText(/Scenario-range horizon in days/), "91");
    await userEvent.click(screen.getByRole("button", { name: "Apply horizon" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/forecast/mf%3A900002?horizon_days=91")).toBe(true));
  });

  it("shows the API message when the instrument has no NAV series", async () => {
    stubFetch(() => json(ERR_FEASIBILITY_NO_SERIES, 422));
    renderAt("/risk?id=fd:fixture-bank:180d");
    const alerts = await screen.findAllByRole("alert");
    expect(alerts[0]).toHaveTextContent("this analysis needs a stored NAV series (mutual fund schemes only) (NO_SERIES)");
  });
});

describe("yield carry on the forecast (TS-1)", () => {
  const q = FORECAST.scenario_range!.quantiles[0]!;
  const ex = (id: string, label: string, display: string) => ({ ...q.return, id, label, display });
  const rowOf = (bp: number, stress: boolean, r: string, inr: string) => ({
    delta_yield_bp: bp,
    stress,
    return: ex(`yc.r.${bp}`, `Horizon return if yields move ${bp}bp`, r),
    value_inr: ex(`yc.inr.${bp}`, `Amount if yields move ${bp}bp (before exit load and tax)`, inr),
  });
  const withCarry = (yield_carry: unknown) => ({ ...FORECAST, yield_carry });

  it("renders the engine's carry and every scenario row as explainable numbers", async () => {
    const yc: YieldCarry = {
      status: "OK",
      label: "scenario range, not a forecast — APPROXIMATE (duration only; roll-down and credit ignored)",
      model_id: "B4_YIELD_CARRY",
      factsheet_as_of: "2026-09-30",
      factsheet_freshness: "STALE",
      carry: ex("yc.carry", "Carry net of expenses over the horizon", "3.40%"),
      scenarios: [rowOf(-50, false, "4.10%", "₹1,04,100.00"), rowOf(0, false, "3.40%", "₹1,03,400.00"), rowOf(50, false, "2.70%", "₹1,02,700.00")],
      stress_scenarios: [rowOf(200, true, "0.60%", "₹1,00,600.00")],
      context_amount: FORECAST.context_amount!,
    };
    stubFetch((url) => (url.startsWith("/api/risk/") ? json(RISK_EQUITY) : json(withCarry(yc))));
    renderAt("/risk?id=mf:900003");
    const section = await screen.findByRole("region", { name: "Yield carry (debt funds)" });
    expect(within(section).getByText(/APPROXIMATE \(duration only/)).toBeInTheDocument();
    expect(within(section).getByText("(STALE factsheet)")).toBeInTheDocument();
    expect(within(section).getByRole("button", { name: /^Carry net of expenses over the horizon: 3\.40%/ })).toBeInTheDocument();
    expect(within(section).getByRole("rowheader", { name: "−50 bp" })).toBeInTheDocument();
    expect(within(section).getByRole("rowheader", { name: "no change" })).toBeInTheDocument();
    expect(within(section).getByRole("rowheader", { name: /^\+200 bp ?\(stress\)$/ })).toBeInTheDocument();
    expect(within(section).getByRole("button", { name: /^Amount if yields move 200bp \(before exit load and tax\): ₹1,00,600\.00/ })).toBeInTheDocument();
  });

  it("a refusal (missing factsheet facts) is shown in words; not_applicable is a plain note", async () => {
    const refused = { id: "yc", label: "Yield-carry scenario range (debt fund)", status: "refused", code: "FUND_FACTS_UNAVAILABLE", reason: "needs the factsheet's portfolio YTM, modified duration and expense ratio (missing: ytm); none is assumed", value: null };
    stubFetch((url) => (url.startsWith("/api/risk/") ? json(RISK_EQUITY) : json(withCarry(refused))));
    const view = renderAt("/risk?id=mf:900003");
    const section = await screen.findByRole("region", { name: "Yield carry (debt funds)" });
    expect(section).toHaveTextContent(/Not shown: needs the factsheet's portfolio YTM.*\(FUND_FACTS_UNAVAILABLE\)/);
    expect(within(section).queryByRole("button")).not.toBeInTheDocument();
    view.unmount();

    stubFetch((url) => (url.startsWith("/api/risk/") ? json(RISK_EQUITY) : json(withCarry({ status: "not_applicable", reason: "Yield carry applies to debt-category funds only." }))));
    renderAt("/risk?id=mf:900002");
    const na = await screen.findByRole("region", { name: "Yield carry (debt funds)" });
    expect(na).toHaveTextContent("Yield carry applies to debt-category funds only.");
  });
});

describe("Risk — fetch (A06)", () => {
  it("when the summary is unavailable the id is shown and the full-history detail is still not fetched", async () => {
    const calls = stubFetch((url) =>
      url.startsWith("/api/risk/") ? json(RISK_EQUITY) : url.endsWith("/summary") ? json({ code: "NOT_FOUND" }, 404) : json(FORECAST),
    );
    renderAt("/risk?id=mf:900003");
    await screen.findByText("Annualised volatility");
    expect(screen.getAllByText("mf:900003").length).toBeGreaterThan(0);
    expect(calls.filter((c) => /^\/api\/instruments\/[^/?]+$/.test(c.url))).toEqual([]);
  });
});
