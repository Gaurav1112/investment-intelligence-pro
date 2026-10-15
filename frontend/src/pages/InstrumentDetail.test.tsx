import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { InstrumentDetailResponse, SeriesPoint } from "../lib/types";
import type { BondList } from "../lib/types-bonds";
import InstrumentDetail from "./InstrumentDetail";

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
const stub = (fn: (url: string) => Response) => {
  const urls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      urls.push(url);
      return fn(url);
    }),
  );
  return urls;
};

function navPoints(n: number, quality: SeriesPoint["quality_status"]): SeriesPoint[] {
  const out: SeriesPoint[] = [];
  for (let i = 0; i < n; i += 1) {
    const d = new Date(Date.UTC(2026, 7, 1 + i)).toISOString().slice(0, 10);
    out.push({
      observation_date: d,
      value: `${100 + i}.12345`,
      source_id: quality === "fixture" ? "fixture" : "amfi.navhistory",
      source_url: "https://portal.amfiindia.com/x",
      retrieved_at: "2026-10-15T05:34:19+00:00",
      quality_status: quality,
    });
  }
  // a dip in the middle so lowest/highest are not simply first/last
  if (n > 10) out[10] = { ...out[10]!, value: "99.5" };
  return out;
}

function mf(origin: "source" | "fixture", points: SeriesPoint[]): InstrumentDetailResponse {
  return {
    instrument: { instrument_id: "mf:119551", kind: "mf_scheme", name: origin === "fixture" ? "FIXTURE Liquid Fund" : "Example Liquid Fund — Direct · Growth", issuer_id: null, isin: "INF000000001", amfi_code: "119551", currency: "INR", origin, created_at: "2026-10-01T00:00:00+00:00" },
    mf_schemes: { instrument_id: "mf:119551", amc: "Example Mutual Fund", category_raw: "Debt Scheme - Liquid Fund", sebi_category: null, plan: "direct", option_type: "Growth", benchmark: null, riskometer: null, prc: null, exit_load_json: '{"days": 7, "rate": "0.00007", "citation": "https://amc.example.in/sid", "as_of": "2026-09-30"}', expense_ratio: null, expense_ratio_kind: null, expense_as_of: null },
    series: { series_id: "nav:119551", points },
    freshness: { badge: origin === "fixture" ? "FIXTURE" : "END_OF_DAY", observed: points.at(-1)?.observation_date ?? null },
  };
}

const renderAt = (id: string) =>
  render(
    <MemoryRouter initialEntries={[`/i/${encodeURIComponent(id)}`]}>
      <Routes>
        <Route path="/i/:id" element={<InstrumentDetail />} />
      </Routes>
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

describe("InstrumentDetail", () => {
  it("renders identity, terms, a text summary and at most 50 observations latest first", async () => {
    const urls = stub(() => json(mf("source", navPoints(60, "ok"))));
    renderAt("mf:119551");
    expect(await screen.findByRole("heading", { level: 1, name: /Example Liquid Fund/ })).toBeInTheDocument();
    expect(urls[0]).toBe("/api/instruments/mf%3A119551");
    expect(screen.getByText(/AMFI code 119551 · ISIN INF000000001/)).toBeInTheDocument();
    expect(screen.getByText("Official source feed")).toBeInTheDocument();
    expect(screen.getAllByText(/END-OF-DAY/).length).toBeGreaterThan(0);
    expect(screen.getByText("Example Mutual Fund")).toBeInTheDocument();
    expect(screen.getByText(/0\.007 % if redeemed within 7 days/)).toBeInTheDocument();
    expect(screen.getByText(/60 NAV observations from 01-Aug-2026 to 29-Sep-2026/)).toHaveTextContent(
      "Latest ₹159.1235 on 29-Sep-2026; lowest ₹99.5000 on 11-Aug-2026; highest ₹159.1235 on 29-Sep-2026.",
    );
    expect(screen.getByText("Showing 50 of 60 (latest first).")).toBeInTheDocument();
    const obs = screen.getByRole("table", { name: "Stored observations, latest first" });
    const firstRow = within(obs).getAllByRole("row")[1]!;
    expect(firstRow).toHaveTextContent("29-Sep-2026");
    expect(firstRow).toHaveTextContent("₹159.1235");
    expect(screen.getByRole("link", { name: "Add to comparison" })).toHaveAttribute("href", "/compare?ids=mf%3A119551");
    expect(screen.getByRole("link", { name: "Evidence viewer" })).toHaveAttribute("href", "/evidence");
    expect(screen.getByText(/Past performance may or may not be sustained/)).toBeInTheDocument();
  });

  it("offers the chart as a table", async () => {
    stub(() => json(mf("source", navPoints(12, "ok"))));
    renderAt("mf:119551");
    await userEvent.click(await screen.findByRole("button", { name: "View as table" }));
    const t = screen.getByRole("table", { name: /All NAV values in the chart/ });
    expect(within(t).getAllByRole("row")).toHaveLength(13);
    expect(screen.getByRole("button", { name: "View as chart" })).toHaveAttribute("aria-pressed", "true");
  });

  it("marks FIXTURE instruments and fixture observations loudly", async () => {
    stub(() => json(mf("fixture", navPoints(5, "fixture"))));
    renderAt("mf:119551");
    expect(await screen.findByText(/This instrument is synthetic development data/)).toBeInTheDocument();
    expect(screen.getAllByText(/FIXTURE — not market data/).length).toBeGreaterThan(3);
    expect(screen.getByRole("heading", { level: 1 }).closest("section")).toHaveClass("fixture-zone");
  });

  it("shows an empty series state for a scheme without history", async () => {
    stub(() => json(mf("source", [])));
    renderAt("mf:119551");
    expect(await screen.findByText("No NAV observations stored")).toBeInTheDocument();
  });

  it("renders a manual T-bill with its yield and manual badge", async () => {
    const d: InstrumentDetailResponse = {
      instrument: { instrument_id: "tbill:91d:2027-01-13", kind: "tbill", name: "91-day T-bill", issuer_id: "goi", isin: null, amfi_code: null, currency: "INR", origin: "manual", created_at: "2026-10-14T00:00:00+00:00" },
      bond_terms: { instrument_id: "tbill:91d:2027-01-13", face_value: "100", coupon_rate: "0", coupon_freq: 0, issue_date: null, maturity_date: "2027-01-13", daycount: "ACT/365F", listed: 1, call_schedule_json: null, credit_rating: "SOVEREIGN", rating_agency: null, rating_date: null },
      series: { series_id: "yield:tbill:91d:2027-01-13", points: [{ observation_date: "2026-10-14", value: "0.0654", source_id: "rbi.pr.tbill", source_url: "https://www.rbi.org.in/pr", retrieved_at: "2026-10-14T10:00:00+00:00", quality_status: "manual" }] },
    };
    stub(() => json(d));
    renderAt("tbill:91d:2027-01-13");
    expect(await screen.findByText("None (discount instrument)")).toBeInTheDocument();
    expect(screen.getByText("₹100.00")).toBeInTheDocument();
    expect(screen.getByText("13-Jan-2027")).toBeInTheDocument();
    expect(screen.getAllByText("6.54 %").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/MANUAL ENTRY/).length).toBeGreaterThan(0);
  });

  it("shows a corporate bond's latest quote, freshness, citation, rating and how to record a newer quote", async () => {
    // Fictional bond (fixture.invalid citations).
    const id = "corp_bond:INFIXCORP018";
    const d: InstrumentDetailResponse = {
      instrument: { instrument_id: id, kind: "corp_bond", name: "FIXTURE Finance Ltd 9 % 2029-10-15", issuer_id: "fixture-finance", isin: "INFIXCORP018", amfi_code: null, currency: "INR", origin: "manual", created_at: "2026-10-01T00:00:00+00:00" },
      bond_terms: { instrument_id: id, face_value: "10000", coupon_rate: "0.09", coupon_freq: 1, issue_date: "2024-10-15", maturity_date: "2029-10-15", daycount: "ACT/ACT-SEBI", listed: 1, call_schedule_json: null, credit_rating: "AA+", rating_agency: "ICRA", rating_date: "2025-09-01" },
      series: { series_id: `bondyield:${id}`, points: [] },
    };
    const list: BondList = {
      as_of: "2026-10-15", quote_stale_after_days: 7, rating_stale_after_days: 365,
      items: [{
        instrument_id: id, kind: "corp_bond", name: d.instrument.name, isin: "INFIXCORP018", origin: "manual", fixture: false,
        quote: { kind: "ytm", value: "0.0812", convention: "ytm; compounding=annual", quote_date: "2026-10-01", age_days: 14, freshness: "STALE", citation_url: "https://fixture.invalid/corp", source_id: "bond.quote" },
        quote_problem: null,
        terms: { issuer: "FIXTURE Finance Ltd", coupon_rate: "0.09", frequency: 1, issue_date: "2024-10-15", maturity: "2029-10-15", face_value: "10000", listed: true, secured: true, record_date_days: 15, calls: [{ call_date: "2027-10-15", call_price: "100" }], transaction_spread: "0.001", day_count: "ACT/ACT-SEBI" },
        rating: { rating: "AA+", agency: "ICRA", rating_date: "2025-09-01", age_days: 409, stale: true, citation_url: "https://fixture.invalid/rating" },
      }],
    }; // prettier-ignore
    const urls = stub((url) => (url === "/api/bonds" ? json(list) : json(d)));
    renderAt(id);
    const panel = await screen.findByRole("region", { name: "Latest price or yield" });
    expect(await within(panel).findByText("8.12 % YTM")).toBeInTheDocument();
    expect(within(panel).getByText(/older than 7 days: excluded/)).toBeInTheDocument();
    const hrefs = within(panel).getAllByRole("link", { name: "fixture.invalid" }).map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["https://fixture.invalid/corp", "https://fixture.invalid/rating"]); // quote source, rating rationale
    expect(within(panel).getByText("AA+")).toBeInTheDocument();
    expect(within(panel).getByText("15-Oct-2027 at 100 per ₹100")).toBeInTheDocument();
    expect(within(panel).getByText("0.10 %")).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Fixed income" })).toHaveAttribute("href", "/fi");
    expect(urls).toContain("/api/bonds");
  });

  it("does not load bond quotes for a mutual fund", async () => {
    const urls = stub(() => json(mf("source", navPoints(3, "ok"))));
    renderAt("mf:119551");
    await screen.findByText("Example Mutual Fund");
    expect(urls).not.toContain("/api/bonds");
    expect(screen.queryByRole("region", { name: "Latest price or yield" })).not.toBeInTheDocument();
  });

  it("shows a not-found state on 404 and an error state otherwise", async () => {
    stub(() => json({ detail: "not found" }, 404));
    const { unmount } = renderAt("mf:1");
    expect(await screen.findByText("No instrument with this id is stored")).toBeInTheDocument();
    unmount();
    stub(() => json({ code: "INTERNAL_ERROR" }, 500));
    renderAt("mf:1");
    expect(await screen.findByRole("alert")).toHaveTextContent("INTERNAL_ERROR");
  });
});
