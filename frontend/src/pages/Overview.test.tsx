import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type {
  ImportPreview,
  InstrumentList,
  PortfolioExplained,
  PortfolioListItem,
  PortfolioSummary,
  TransactionList,
} from "../lib/types";
import Overview, { toExplained, unitsLabel } from "./Overview";

// Shapes follow backend/src/iip/services/portfolio.py (portfolio_summary, preview_holdings_import, apply_holdings_import)
// and the synthetic TEST instruments in backend/tests/services/test_portfolio.py.

type Call = { url: string; method: string; body: unknown; headers: Record<string, string> };
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });

function stubFetch(handler: (url: string, method: string, body: unknown) => Response) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const raw = init?.body;
      const body = typeof raw === "string" ? JSON.parse(raw) : raw;
      calls.push({ url, method, body, headers: (init?.headers ?? {}) as Record<string, string> });
      return handler(url, method, body);
    }),
  );
  return calls;
}

function ex(id: string, label: string, value: string | null, display: string, freshness: PortfolioExplained["freshness"], extra: Partial<PortfolioExplained> = {}): PortfolioExplained {
  return {
    id, label, display, value, unit: "INR", what: `${label} explained.`, formula_id: "F@1", formula: "f", substituted: display,
    inputs: [], sources: [{ source_id: "user.transactions" }], observed: "2026-10-15", freshness, assumptions: [], sensitivity: [],
    limitations: [], engine_version: "portfolio@1.0.0", hash: "abcdef0123456789", ...extra,
  };
}

const NAV_SRC = {
  source_id: "fixture.nav", url: "https://example.invalid/nav", retrieved_at: "2026-10-14T18:00:00+00:00", observation_date: "2026-10-14",
  quality_status: "fixture", obs_id: 41, evidence: "/api/evidence/41",
};

const ACTUAL: PortfolioListItem = { portfolio_id: "pf_a1", name: "Core", nature: "actual", created_at: "2026-10-01T00:00:00+00:00", transactions: 3 };
const HYPO: PortfolioListItem = { portfolio_id: "pf_h1", name: "What-if ladder", nature: "hypothetical", created_at: "2026-10-02T00:00:00+00:00", transactions: 0 };

function summary(over: Partial<PortfolioSummary> = {}): PortfolioSummary {
  return {
    portfolio: { portfolio_id: "pf_a1", name: "Core", nature: "actual" },
    label: "ACTUAL holdings",
    as_of: "2026-10-15",
    flags: ["CONTAINS_FIXTURE_DATA", "HOLDINGS_EXCLUDED"],
    notes: ["TEST Debt Fund C: STALE — the latest NAV is STALE; excluded from totals until fresh data is stored (older NAVs are never used)"],
    holdings: [
      {
        instrument_id: "mf:990001", name: "TEST Liquid Fund A", kind: "mf_scheme", category: "Liquid Fund", units: "100", lots: 1,
        badge: "FIXTURE", included_in_totals: true, exclusion: null, nav: { ...NAV_SRC, value: "12.3456" },
        invested: ex("mf:990001.invested", "Invested (remaining cost, FIFO)", "1000.00", "₹1,000.00", "USER_DATA"),
        market_value: ex("mf:990001.market_value", "Market value", "1234.56", "₹1,234.56", "FIXTURE", { sources: [NAV_SRC] }),
        unrealised_pl: ex("mf:990001.unrealised_pl", "Unrealised P/L", "234.56", "₹234.56", "FIXTURE"),
      },
      {
        instrument_id: "mf:990003", name: "TEST Debt Fund C", kind: "mf_scheme", category: "Short Duration Fund", units: "10.500000", lots: 1,
        badge: "STALE", included_in_totals: false,
        exclusion: { code: "STALE_NAV", text: "the latest NAV is STALE; excluded from totals until fresh data is stored (older NAVs are never used)" },
        nav: { ...NAV_SRC, obs_id: 7, observation_date: "2026-09-01", value: "14.0000" },
        invested: ex("mf:990003.invested", "Invested (remaining cost, FIFO)", "140.00", "₹140.00", "USER_DATA"),
        market_value: null, unrealised_pl: null,
      },
    ],
    totals: {
      market_value: ex("total.market_value", "Market value (valued holdings)", "1234.56", "₹1,234.56", "FIXTURE", { sources: [NAV_SRC], observed: "2026-10-14 → 2026-10-14" }),
      invested: ex("total.invested", "Invested (valued holdings)", "1000.00", "₹1,000.00", "USER_DATA"),
      invested_all_holdings: "1140.00",
      unrealised_pl: ex("total.unrealised_pl", "Unrealised P/L (valued holdings)", "234.56", "₹234.56", "FIXTURE"),
      realised_pl: "0.00",
    },
    xirr: {
      scope: "1 valued holding(s) plus closed positions; 1 excluded", headline_allowed: true, annualised_detail: null,
      explain: ex("xirr", "XIRR", "0.1234567", "12.35%", "DERIVED"),
    },
    allocation: {
      by_kind: { by: "kind", items: [{ key: "mf_scheme", market_value: "1234.56", display: "₹1,234.56", weight: "1", share: "100.00%" }], total: "1234.56", sum_of_items: "1234.56" },
      by_category: { by: "category", items: [{ key: "Liquid Fund", market_value: "1234.56", display: "₹1,234.56", weight: "1", share: "100.00%" }], total: "1234.56", sum_of_items: "1234.56" },
    },
    concentration: { band: "highly concentrated", effective_count: "1.00", explain: ex("hhi", "Concentration (HHI)", "1.000000", "1.0000 (highly concentrated)", "FIXTURE") },
    liquidity_ladder: {
      buckets: [
        { bucket: "0-7 days", market_value: "1234.56", display: "₹1,234.56", share: "100.00%", at_cost_not_valued: "140.00", at_cost_display: "₹140.00" },
        { bucket: "8-30 days", market_value: "0", display: "₹0.00", share: "0.00%", at_cost_not_valued: "0", at_cost_display: "₹0.00" },
      ],
      explain: ex("liquidity_ladder", "Liquidity ladder", "1234.56", "₹1,234.56", "DERIVED"),
    },
    upcoming_maturities: {
      within_days: 365,
      items: [{ instrument_id: "fd:test-bank:180d", name: "TEST Bank FD — 180 days", kind: "fd", maturity_date: "2026-11-06", days_until: 22, invested_at_cost: "600000.00", display: "₹6,00,000.00", flags: [], source: "deposit_terms tenure + your purchase date" }],
    },
    dicgc: {
      scope: "all actual portfolios (DICGC cover is per depositor per bank)",
      banks: [{ institution: "TEST Bank", principal_at_cost: "600000.00", insured: "500000.00", uninsured: "100000.00", display_uninsured: "₹1,00,000.00", flags: [] }],
      explain: ex("dicgc_exposure", "Deposit-insurance exposure", "100000.00", "₹1,00,000.00", "DERIVED"),
    },
    engine_version: "portfolio@1.0.0",
    ...over,
  };
}

const TXNS: TransactionList = {
  portfolio_id: "pf_a1", nature: "actual",
  items: [{ txn_id: "tx_1", instrument_id: "mf:990001", instrument_name: "TEST Liquid Fund A", txn_date: "2025-01-10", txn_type: "buy", units: "100", amount: "1000.00", price: null, source: "csv_import", import_batch: "imp_1", created_at: "2026-10-15T06:00:00+00:00" }],
};

const SEARCH: InstrumentList = {
  items: [{ instrument_id: "mf:990001", kind: "mf_scheme", name: "TEST Liquid Fund A", origin: "fixture", amfi_code: "990001", category_raw: "Liquid Fund", plan: "direct", last_nav_date: "2026-10-14", last_nav: "12.3456", nav_points: 5, exit_load: null, fixture: true }],
  truncated: false,
};

const SHA = "a".repeat(64);
const PREVIEW: ImportPreview = {
  batch_id: "imp_0123456789abcdef", status: "previewed", applied: false, file_sha256: SHA, label: "holdings.csv", kind: "csv",
  header: ["instrument_name", "isin", "amfi_code", "units", "cost_basis_inr", "purchase_date"],
  will_store: [
    { row: 1, instrument_id: "mf:990001", instrument_name: "TEST Liquid Fund A", file_instrument_name: "TEST Liquid Fund A", txn_date: "2025-01-10", txn_type: "buy", units: "100", amount: "1000.00", flags: [] },
    { row: 2, instrument_id: "mf:990002", instrument_name: "TEST Gilt Fund B", file_instrument_name: '=HYPERLINK("http://x","y")', txn_date: "2025-03-03", txn_type: "buy", units: "50.5", amount: "900", flags: ["FORMULA_LIKE_TEXT"] },
  ],
  rejected: [
    { line: 6, reason: "BAD_NUMBER", stage: "parse" },
    { row: 3, reason: "UNKNOWN_AMFI_CODE", stage: "resolve" },
    { row: 4, reason: "MISSING_COST_BASIS", stage: "resolve" },
  ],
  warnings: [], already_applied: false, confirm_with: { sha256: SHA },
  note: "Nothing has been stored yet. Confirm with the file's SHA-256 to apply exactly the rows listed.",
};

function routes(over: { portfolios?: PortfolioListItem[]; summary?: (id: string) => Response } = {}) {
  return (url: string, method: string): Response => {
    if (url === "/api/portfolios" && method === "GET") return json({ items: over.portfolios ?? [ACTUAL, HYPO] });
    const m = /^\/api\/portfolios\/([^/]+)\/summary$/.exec(url);
    if (m && method === "GET") {
      if (over.summary) return over.summary(m[1]!);
      return m[1] === "pf_h1"
        ? json(summary({ portfolio: { portfolio_id: "pf_h1", name: "What-if ladder", nature: "hypothetical" }, label: "HYPOTHETICAL — not your actual holdings", holdings: [], notes: [], flags: [] }))
        : json(summary());
    }
    if (/\/transactions$/.test(url) && method === "GET") return json(TXNS);
    if (url.startsWith("/api/instruments?q=")) return json(SEARCH);
    return json({ code: "NOT_FOUND", message: "not found" }, 404);
  };
}

const renderPage = (path = "/") =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Overview />
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

describe("Overview helpers", () => {
  it("adapts derived freshness and partial sources without changing numbers", () => {
    const e = toExplained(summary().liquidity_ladder.explain);
    expect(e.freshness).toBe("MANUAL");
    expect(e.display).toBe("₹1,234.56");
    expect(e.sources[0]!.source_name).toMatch(/your own records/);
    expect(e.limitations[0]).toMatch(/DERIVED/);
    expect(toExplained(summary().totals.unrealised_pl, { plus: true }).display).toBe("+₹234.56");
    expect(toExplained(ex("x", "P/L", "-5.00", "-₹5.00", "FIXTURE"), { plus: true }).display).toBe("-₹5.00");
  });
  it("trims unit precision to at most 6 decimals", () => {
    expect(unitsLabel("10.500000")).toBe("10.5");
    expect(unitsLabel("100")).toBe("100");
    expect(unitsLabel("1.12345678")).toBe("1.123457");
  });
});

describe("Overview — summary", () => {
  it("renders the actual portfolio: totals, FIXTURE badge, allocation, HHI, ladder, maturities, DICGC", async () => {
    stubFetch(routes());
    renderPage();
    expect(await screen.findByText("ACTUAL holdings")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Market value \(valued holdings\): ₹1,234.56/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Unrealised P\/L \(valued holdings\): \+₹234.56/ })).toBeInTheDocument();
    expect(screen.getAllByText("gain").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /XIRR: 12.35%/ })).toBeInTheDocument();
    expect(screen.getAllByText(/FIXTURE — not market data/).length).toBeGreaterThan(0);
    expect(screen.getByRole("table", { name: "By instrument type" })).toHaveTextContent("100.00%");
    expect(screen.getByText(/1 when everything is in one holding/)).toBeInTheDocument();
    expect(screen.getByText("0-7 days")).toBeInTheDocument();
    expect(screen.getByText("06-Nov-2026")).toBeInTheDocument();
    const dicgc = screen.getByRole("table", { name: "DICGC exposure per bank" });
    expect(within(dicgc).getByText("₹1,00,000.00")).toBeInTheDocument();
    expect(within(dicgc).getByText("₹6,00,000.00")).toBeInTheDocument();
  });

  it("shows a STALE holding greyed with the API's exclusion note, outside the totals", async () => {
    stubFetch(routes());
    renderPage();
    const row = await screen.findByTestId("holding-mf:990003");
    expect(row).toHaveClass("is-excluded");
    expect(row.querySelector(".badge--stale")).toHaveTextContent("STALE");
    expect(within(row).getByText(/older NAVs are never used/)).toBeInTheDocument();
    expect(within(row).getByText("not valued")).toBeInTheDocument();
    expect(within(row).getByText("10.5")).toBeInTheDocument();
    expect(screen.getByTestId("holding-mf:990001")).not.toHaveClass("is-excluded");
    expect(screen.getByText("Excluded from totals")).toBeInTheDocument();
    expect(screen.getByText(/All holdings at cost, including excluded ones: ₹1,140.00/)).toBeInTheDocument();
  });

  it("opens the explain drawer for a derived value without crashing", async () => {
    stubFetch(routes());
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Liquidity ladder: ₹1,234.56/ }));
    expect(await screen.findByRole("heading", { name: /Explain: Liquidity ladder/ })).toBeInTheDocument();
    expect(screen.getByText(/user.transactions \(your own records\)/)).toBeInTheDocument();
  });

  it("labels actual and hypothetical portfolios distinctly", async () => {
    stubFetch(routes());
    renderPage("/?p=pf_h1");
    expect(await screen.findByText("HYPOTHETICAL — not your actual holdings")).toBeInTheDocument();
    const pick = screen.getByLabelText("Portfolio");
    expect(within(pick).getByRole("option", { name: /\[ACTUAL\] Core/ })).toBeInTheDocument();
    expect(within(pick).getByRole("option", { name: /\[HYPOTHETICAL\] What-if ladder/ })).toBeInTheDocument();
    expect(pick).toHaveValue("pf_h1");
    expect(document.querySelector(".portfolio-banner--hypothetical")).not.toBeNull();
    fireEvent.change(pick, { target: { value: "pf_a1" } });
    expect(await screen.findByText("ACTUAL holdings")).toBeInTheDocument();
    expect(document.querySelector(".portfolio-banner--actual")).not.toBeNull();
  });

  it("does not headline XIRR under 365 days: shows the absolute figure and the API caveat", async () => {
    const short = summary({
      xirr: {
        scope: "1 valued holding(s) plus closed positions; 0 excluded", headline_allowed: false,
        annualised_detail: { value: "0.4567", display: "45.67%", warning: "ANNUALISED_FROM_SHORT_PERIOD — not a headline figure" },
        explain: ex("xirr", "XIRR", null, "Not annualised: 120 days of cash flows (under 365)", "DERIVED"),
      },
    });
    stubFetch(routes({ summary: () => json(short) }));
    renderPage();
    expect(await screen.findByRole("button", { name: /XIRR: Not annualised: 120 days/ })).toBeInTheDocument();
    expect(screen.getByText(/ANNUALISED_FROM_SHORT_PERIOD — not a headline figure/)).toBeInTheDocument();
    expect(screen.getByText(/Absolute change instead/)).toBeInTheDocument();
    expect(screen.queryByText(/45.67/)).toBeNull();
  });

  it("teaches the next step when there are no portfolios", async () => {
    stubFetch(routes({ portfolios: [] }));
    renderPage();
    expect(await screen.findByText("No portfolio yet")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Create a portfolio" })).toBeInTheDocument();
  });

  it("teaches transactions and the CSV template when a portfolio has no holdings", async () => {
    stubFetch(routes({ summary: () => json(summary({ holdings: [], notes: [], flags: [] })) }));
    renderPage();
    expect(await screen.findByText("No holdings in this portfolio yet")).toBeInTheDocument();
    expect(screen.getAllByText("instrument_name, isin, amfi_code, units, cost_basis_inr, purchase_date").length).toBeGreaterThan(0);
  });

  it("shows an error state when the summary is refused", async () => {
    stubFetch(routes({ summary: () => json({ code: "INCONSISTENT_BOOK", message: "stored transactions are inconsistent" }, 409) }));
    renderPage();
    expect(await screen.findByText(/stored transactions are inconsistent \(INCONSISTENT_BOOK\)/)).toBeInTheDocument();
    expect(screen.queryByText("ACTUAL holdings")).toBeNull();
  });

  it("creates a portfolio with the chosen nature", async () => {
    const calls = stubFetch((url, method) =>
      url === "/api/portfolios" && method === "POST"
        ? json({ portfolio_id: "pf_new", name: "Trial", nature: "hypothetical", created_at: "2026-10-15T06:00:00+00:00" })
        : routes()(url, method),
    );
    renderPage();
    await screen.findByText("ACTUAL holdings");
    fireEvent.change(screen.getByLabelText("Portfolio name"), { target: { value: "Trial" } });
    await userEvent.click(screen.getByLabelText(/Hypothetical — a what-if/));
    await userEvent.click(screen.getByRole("button", { name: "Create portfolio" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ name: "Trial", nature: "hypothetical" });
    expect(await screen.findByText(/Created hypothetical portfolio “Trial”/)).toBeInTheDocument();
  });
});

describe("Overview — transactions", () => {
  async function fillSell() {
    fireEvent.change(await screen.findByLabelText("Find instrument by name"), { target: { value: "TEST" } });
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await userEvent.click(await screen.findByRole("button", { name: "Select TEST Liquid Fund A" }));
    fireEvent.change(screen.getByLabelText("Transaction type"), { target: { value: "sell" } });
    fireEvent.change(screen.getByLabelText("Date"), { target: { value: "2025-02-10" } });
    fireEvent.change(screen.getByLabelText("Units"), { target: { value: "10.5" } });
    fireEvent.change(screen.getByLabelText(/Amount \(₹/), { target: { value: "1,25,000.50" } });
  }

  it("posts a transaction with decimal strings", async () => {
    const calls = stubFetch((url, method) => (method === "POST" ? json({ txn_id: "tx_9", status: "stored" }) : routes()(url, method)));
    renderPage();
    await screen.findByText("ACTUAL holdings");
    await fillSell();
    await userEvent.click(screen.getByRole("button", { name: "Save transaction" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.url).toBe("/api/portfolios/pf_a1/transactions");
    expect(post.body).toEqual({ instrument_id: "mf:990001", txn_date: "2025-02-10", txn_type: "sell", units: "10.5", amount: "125000.50" });
    expect(await screen.findByText(/Stored: sell of 10.5 units of TEST Liquid Fund A on 10-Feb-2025 for ₹1,25,000.50/)).toBeInTheDocument();
  });

  it("explains an OVERSELL refusal in plain words", async () => {
    stubFetch((url, method) =>
      method === "POST"
        ? json({ code: "OVERSELL", message: "sell of 10.5 units of mf:990001 on 2025-02-10 exceeds the 10 units held on that date" }, 422)
        : routes()(url, method),
    );
    renderPage();
    await screen.findByText("ACTUAL holdings");
    await fillSell();
    await userEvent.click(screen.getByRole("button", { name: "Save transaction" }));
    const alert = await screen.findByText(/This sale is for more units than you held on that date/);
    expect(alert).toHaveAttribute("role", "alert");
    expect(alert).toHaveTextContent("Nothing was stored.");
    expect(alert).toHaveTextContent("exceeds the 10 units held on that date");
  });

  it("refuses bad decimals locally and sends nothing", async () => {
    const calls = stubFetch(routes());
    renderPage();
    await screen.findByText("ACTUAL holdings");
    fireEvent.change(screen.getByLabelText("Units"), { target: { value: "1e3" } });
    fireEvent.change(screen.getByLabelText(/Amount \(₹/), { target: { value: "10.555" } });
    await userEvent.click(screen.getByRole("button", { name: "Save transaction" }));
    expect(screen.getByText(/Enter units above zero/)).toBeInTheDocument();
    expect(screen.getByText(/Enter the amount in rupees above zero/)).toBeInTheDocument();
    expect(screen.getByText("Search for and select the instrument.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("explains WOULD_OVERSELL when deleting a purchase", async () => {
    const calls = stubFetch((url, method) =>
      method === "DELETE"
        ? json({ code: "WOULD_OVERSELL", message: "deleting this buy would leave a later sell exceeding the units held" }, 409)
        : routes()(url, method),
    );
    renderPage();
    await screen.findByText("ACTUAL holdings");
    await userEvent.click(screen.getByText("Transactions (1)"));
    await userEvent.click(await screen.findByRole("button", { name: /^Delete buy of TEST Liquid Fund A/ }));
    await userEvent.click(screen.getByRole("button", { name: /^Confirm delete buy/ }));
    expect(await screen.findByText(/a later sale depends on its units/)).toHaveAttribute("role", "alert");
    const del = calls.find((c) => c.method === "DELETE")!;
    expect(del.url).toBe("/api/portfolios/pf_a1/transactions/tx_1");
    expect(del.headers["Content-Type"]).toBe("application/json");
  });
});

describe("Overview — CSV import", () => {
  async function upload() {
    const file = new File(["instrument_name,units\r\n"], "holdings.csv", { type: "text/csv" });
    await userEvent.upload(await screen.findByLabelText("Holdings file (.csv or .xlsx)"), file);
    await userEvent.click(screen.getByRole("button", { name: "Preview import" }));
  }

  it("previews the exact rows, then applies with the file's SHA-256 and reports the result honestly", async () => {
    const calls = stubFetch((url, method) => {
      if (url === "/api/holdings/import") return json(PREVIEW);
      if (url === `/api/holdings/import/${PREVIEW.batch_id}/apply`)
        return json({ batch_id: PREVIEW.batch_id, status: "applied", applied: true, portfolio_id: "pf_a1", transactions_created: 2, rows_rejected: 3, applied_at: "2026-10-15T06:00:00+00:00" });
      return routes()(url, method);
    });
    renderPage();
    await screen.findByText("ACTUAL holdings");
    await upload();

    const up = calls.find((c) => c.url === "/api/holdings/import")!;
    expect(up.method).toBe("POST");
    expect(up.body).toBeInstanceOf(FormData);
    expect((up.body as FormData).get("portfolio_id")).toBe("pf_a1");
    expect(((up.body as FormData).get("file") as File).name).toBe("holdings.csv");
    expect(Object.keys(up.headers).map((h) => h.toLowerCase())).not.toContain("content-type");

    expect(await screen.findByText(/Preview of holdings.csv — nothing stored yet/)).toBeInTheDocument();
    const stored = screen.getByRole("table", { name: "Rows that will be stored" });
    expect(within(stored).getByText('=HYPERLINK("http://x","y")')).toBeInTheDocument();
    expect(within(stored).getByText("₹1,000.00")).toBeInTheDocument();
    expect(within(stored).getByText("FORMULA_LIKE_TEXT")).toBeInTheDocument();
    const rejected = screen.getByRole("list", { name: "Rejected rows" });
    expect(within(rejected).getByText(/File line 6: a number is not in an accepted format/)).toBeInTheDocument();
    expect(within(rejected).getByText(/Data row 3: no stored instrument has this AMFI code/)).toBeInTheDocument();
    expect(within(rejected).getByText(/Data row 4: cost_basis_inr is missing/)).toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith("/apply"))).toBe(false); // nothing applied before confirmation

    await userEvent.click(screen.getByRole("button", { name: "Confirm and store 2 row(s)" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/apply"))).toBe(true));
    expect(calls.find((c) => c.url.endsWith("/apply"))!.body).toEqual({ sha256: SHA });
    expect((await screen.findAllByText(/Import applied: 2 transaction\(s\) stored/)).length).toBeGreaterThan(0);
  });

  it("never claims success unless the API says applied: true", async () => {
    stubFetch((url, method) => {
      if (url === "/api/holdings/import") return json(PREVIEW);
      if (url.endsWith("/apply")) return json({ batch_id: PREVIEW.batch_id, status: "previewed", applied: false });
      return routes()(url, method);
    });
    renderPage();
    await screen.findByText("ACTUAL holdings");
    await upload();
    await userEvent.click(await screen.findByRole("button", { name: "Confirm and store 2 row(s)" }));
    expect(await screen.findByText(/did not confirm that the import was applied/)).toHaveAttribute("role", "alert");
    expect(screen.queryByText(/Import applied/)).toBeNull();
  });

  it("shows an apply refusal and does not report success", async () => {
    stubFetch((url, method) => {
      if (url === "/api/holdings/import") return json(PREVIEW);
      if (url.endsWith("/apply")) return json({ code: "PREVIEW_EXPIRED", message: "the preview is older than 24 hours; upload the file again" }, 410);
      return routes()(url, method);
    });
    renderPage();
    await screen.findByText("ACTUAL holdings");
    await upload();
    await userEvent.click(await screen.findByRole("button", { name: "Confirm and store 2 row(s)" }));
    expect(await screen.findByText(/Not applied; nothing was stored. the preview is older than 24 hours/)).toBeInTheDocument();
    expect(screen.queryByText(/Import applied/)).toBeNull();
  });

  it("shows a file-level refusal from the preview", async () => {
    stubFetch((url, method) =>
      url === "/api/holdings/import"
        ? json({ code: "ENCODING_NOT_UTF8", message: "The file is not valid UTF-8. Choose its encoding explicitly (cp1252 or utf-16) and preview again." }, 422)
        : routes()(url, method),
    );
    renderPage();
    await screen.findByText("ACTUAL holdings");
    await upload();
    expect(await screen.findByText(/The file was refused; nothing was stored. The file is not valid UTF-8/)).toHaveAttribute("role", "alert");
  });
});
