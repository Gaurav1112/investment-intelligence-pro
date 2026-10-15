import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { DataHealthResponse } from "../lib/types";
import type { CpiResponse, MospiStatus, RiskFreeResponse } from "../lib/types-inputs";
import DataHealth from "../pages/DataHealth";

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
afterEach(() => vi.unstubAllGlobals());

const HEALTH: DataHealthResponse = { sources: [], runs: [], observation_counts: {}, tax_rules_loaded: true, tax_rules_coverage_to: "2027-03-31" };
const MOSPI: MospiStatus = {
  source_id: "mospi.cpi", status: "REQUIRES_CONFIGURATION", method: null, env_vars: ["IIP_MOSPI_TOKEN", "IIP_MOSPI_USER", "IIP_MOSPI_PASSWORD"],
  message: "MoSPI API credentials are not configured; no CPI is fetched.", verified: false,
};
const CPI: CpiResponse = {
  note: "Each base is its own series.",
  series: [
    { series_id: "cpi:all-india:base2012", base_year: "2012", points: [
      { month: "2025-12", index: "197.1", yoy_inflation_pct: null, provisional: false, source_id: "manual", source_url: "https://mospi.gov.in/a", retrieved_at: "2026-10-01T00:00:00+00:00", published_on: "2026-01-12" },
    ] },
    { series_id: "cpi:all-india:base2024", base_year: "2024", points: [
      { month: "2026-09", index: "104.6", yoy_inflation_pct: "2.07", provisional: true, source_id: "manual", source_url: "https://mospi.gov.in/b", retrieved_at: "2026-10-13T00:00:00+00:00", published_on: "2026-10-12" },
    ] },
  ],
};
const RF: RiskFreeResponse = {
  series_id: "riskfree:tbill91", freshness: "FRESH",
  latest: { auction_date: "2026-10-14", yield_fraction: "0.057281", source_url: "https://www.rbi.org.in/pr", retrieved_at: "2026-10-14T12:00:00+00:00", quality_status: "manual" },
  points: [{ auction_date: "2026-10-14", yield_fraction: "0.057281", source_url: "https://www.rbi.org.in/pr", retrieved_at: "2026-10-14T12:00:00+00:00", quality_status: "manual" }],
};

type Call = { url: string; method: string; body: unknown };
function stub() {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (method === "POST") return json({ series_id: url.includes("cpi") ? "cpi:all-india:base2024" : "riskfree:tbill91", outcome: "inserted" });
      if (url === "/api/data-health") return json(HEALTH);
      if (url === "/api/inputs/mospi/status") return json(MOSPI);
      if (url === "/api/inputs/cpi") return json(CPI);
      if (url === "/api/inputs/riskfree") return json(RF);
      return json({ code: "NOT_FOUND" }, 404);
    }),
  );
  return calls;
}

const renderPage = () =>
  render(
    <MemoryRouter>
      <DataHealth />
    </MemoryRouter>,
  );

describe("Data health → Macro inputs", () => {
  it("shows the MoSPI configuration status, env vars and NOT VERIFIED", async () => {
    stub();
    renderPage();
    expect(await screen.findByRole("heading", { name: "Macro inputs" })).toBeInTheDocument();
    expect(await screen.findByText("REQUIRES CONFIGURATION")).toBeInTheDocument();
    expect(screen.getByText("NOT VERIFIED")).toBeInTheDocument();
    expect(screen.getByText(MOSPI.message)).toBeInTheDocument();
    expect(screen.getByText("IIP_MOSPI_TOKEN")).toBeInTheDocument();
  });

  it("lists CPI base 2012 and base 2024 as separate series and says they are never chained", async () => {
    stub();
    renderPage();
    const t2012 = await screen.findByRole("table", { name: /CPI base 2012 = 100/ });
    const t2024 = screen.getByRole("table", { name: /CPI base 2024 = 100/ });
    expect(within(t2012).getByText("197.1")).toBeInTheDocument();
    expect(within(t2012).queryByText("104.6")).not.toBeInTheDocument();
    expect(within(t2024).getByText("104.6")).toBeInTheDocument();
    expect(within(t2024).getByText("PROVISIONAL")).toBeInTheDocument();
    expect(screen.getByText(/separate series and are never chained/)).toBeInTheDocument();
  });

  it("posts a CPI point with the exact body", async () => {
    const calls = stub();
    const user = userEvent.setup();
    renderPage();
    const form = await screen.findByRole("form", { name: "Enter a CPI point" });
    await user.selectOptions(within(form).getByLabelText("Base year (series)"), "2024");
    await user.type(within(form).getByLabelText("Reference month"), "2026-09");
    await user.type(within(form).getByLabelText(/CPI \(Combined, General\) index/), "104.6");
    await user.click(within(form).getByLabelText(/Provisional/));
    await user.type(within(form).getByLabelText("Official page URL"), "https://mospi.gov.in/press");
    await user.type(within(form).getByLabelText("Value applies as of"), "2026-10-12");
    await user.click(within(form).getByRole("button", { name: "Save CPI point" }));
    expect(await within(form).findByRole("status")).toHaveTextContent("Saved.");
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.url).toBe("/api/inputs/cpi");
    expect(post.body).toEqual({
      base_year: "2024", month: "2026-09", index: "104.6", provisional: true,
      citation: { url: "https://mospi.gov.in/press", as_of: "2026-10-12" },
    });
  });

  it("lists the T-bill series with freshness and posts a yield", async () => {
    const calls = stub();
    const user = userEvent.setup();
    renderPage();
    const table = await screen.findByRole("table", { name: /91-day T-bill cut-off yields/ });
    expect(within(table).getByText("14-Oct-2026")).toBeInTheDocument();
    expect(screen.getByText("riskfree:tbill91")).toBeInTheDocument();
    const form = screen.getByRole("form", { name: "Enter a 91-day T-bill cut-off yield" });
    expect(within(form).getByText(/RBI press release/)).toBeInTheDocument();
    await user.type(within(form).getByLabelText("91-day cut-off yield (fraction)"), "0.057281");
    await user.type(within(form).getByLabelText("Official page URL"), "https://www.rbi.org.in/pr");
    await user.type(within(form).getByLabelText("Value applies as of"), "2026-10-14");
    await user.type(within(form).getByLabelText("Note (optional)"), "PR 2026-2027/1325");
    await user.click(within(form).getByRole("button", { name: "Save T-bill yield" }));
    expect(await within(form).findByRole("status")).toHaveTextContent("Saved.");
    expect(calls.find((c) => c.method === "POST")).toEqual({
      url: "/api/inputs/riskfree",
      method: "POST",
      body: { yield_fraction: "0.057281", citation: { url: "https://www.rbi.org.in/pr", as_of: "2026-10-14", note: "PR 2026-2027/1325" } },
    });
  });
});

describe("Data health → Fetch CPI from MoSPI", () => {
  function stubMospi(status: MospiStatus, fetchResult: () => Response) {
    const calls: Call[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? "GET";
        calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
        if (url === "/api/inputs/mospi/fetch") return fetchResult();
        if (url === "/api/data-health") return json(HEALTH);
        if (url === "/api/inputs/mospi/status") return json(status);
        if (url === "/api/inputs/cpi") return json(CPI);
        if (url === "/api/inputs/riskfree") return json(RF);
        return json({ code: "NOT_FOUND" }, 404);
      }),
    );
    return calls;
  }
  const CONFIGURED: MospiStatus = { ...MOSPI, status: "CONFIGURED", method: "token", message: "Credentials found in the environment." };

  it("offers no fetch button while MoSPI is not configured, and says why", async () => {
    stubMospi(MOSPI, () => json({}, 500));
    renderPage();
    expect(await screen.findByText(/Fetching from MoSPI is unavailable until it is configured \(REQUIRES CONFIGURATION\)/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Fetch CPI from MoSPI" })).not.toBeInTheDocument();
  });

  it("fetches a month when configured, says NOT VERIFIED and reloads the CPI list", async () => {
    const calls = stubMospi(CONFIGURED, () =>
      json({ status: "stored", series_id: "cpi:all-india:base2024", outcome: "inserted", month: "2026-09", verified: false }),
    );
    const user = userEvent.setup();
    renderPage();
    const form = await screen.findByRole("form", { name: "Fetch CPI from MoSPI" });
    await user.click(within(form).getByRole("button", { name: "Fetch CPI from MoSPI" }));
    expect(within(form).getByLabelText("Reference month")).toHaveAttribute("aria-invalid", "true");
    await user.type(within(form).getByLabelText("Reference month"), "2026-09");
    await user.click(within(form).getByRole("button", { name: "Fetch CPI from MoSPI" }));
    expect(await within(form).findByRole("status")).toHaveTextContent(/CPI for 2026-09 \(base 2024\) fetched from MoSPI\. NOT VERIFIED/);
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ base_year: 2024, year: 2026, month: 9 });
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/inputs/cpi" && c.method === "GET").length).toBeGreaterThanOrEqual(2));
  });

  it("shows the server's refusal in words and says nothing was stored", async () => {
    stubMospi(CONFIGURED, () => json({ detail: { code: "LOGIN_RESPONSE_UNRECOGNISED", message: "login response is not JSON" } }, 409));
    const user = userEvent.setup();
    renderPage();
    const form = await screen.findByRole("form", { name: "Fetch CPI from MoSPI" });
    await user.type(within(form).getByLabelText("Reference month"), "2026-09");
    await user.click(within(form).getByRole("button", { name: "Fetch CPI from MoSPI" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent("login response is not JSON (LOGIN_RESPONSE_UNRECOGNISED). Nothing was stored.");
  });
});
