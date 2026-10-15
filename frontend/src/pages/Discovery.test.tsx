import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { DiscoveryResult, DiscoveryRow, Explained } from "../lib/types";
import Discovery, { ledgerCounts } from "./Discovery";

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });

const ex = (id: string, label: string, display: string): Explained => ({
  id, label, display, value: "1", unit: "INR", what: `${label}.`, formula_id: "F@1", formula: "f", substituted: null, inputs: [], sources: [],
  observed: "2026-10-14", freshness: "END_OF_DAY", assumptions: [], sensitivity: [], limitations: [], engine_version: "e@1", hash: "abcdef0123456789",
});

const row = (over: Partial<DiscoveryRow>): DiscoveryRow => ({
  instrument_id: "mf:1", name: "TEST Liquid Fund — Direct · Growth", kind: "mf_scheme", tier: "T3", rank: null, flags: [], reasons: [],
  exclusion_codes: [], days_to_cash: 1, contractual: false, loss_frequency: { value: "0", display: "0 of 40 historical windows" },
  fixture: false, observed: "2026-10-14", outcome: null, ...over,
});

const OUTCOME = {
  q05: ex("q05", "Proceeds low end", "₹5,05,432.56"),
  q50: ex("q50", "Proceeds middle", "₹5,11,371.98"),
  q95: ex("q95", "Proceeds high end", "₹5,12,804.31"),
  gain_q50: { value: "11371.98", display: "₹11,371.98", pct: "2.27%" },
  gain_q05: { value: "5432.56", display: "₹5,432.56", pct: "1.09%" },
};

const EXCLUDED: DiscoveryRow[] = [
  row({ instrument_id: "mf:2", name: "TEST Debt A", exclusion_codes: ["INSUFFICIENT_LOSS_EVIDENCE"] }),
  row({ instrument_id: "mf:3", name: "TEST Debt B", exclusion_codes: ["INSUFFICIENT_LOSS_EVIDENCE", "EXIT_LOAD_UNKNOWN: enter the scheme's exit load from its SID/KIM"] }),
  row({ instrument_id: "mf:4", name: "TEST Debt C", exclusion_codes: [], reasons: ["You excluded this instrument."] }),
];

function result(over: Partial<DiscoveryResult> = {}): DiscoveryResult {
  return {
    status: "RANKED", mode: "PERSONALISED", as_of: "2026-10-15",
    context: { amount: "₹5,00,000.00", amount_value: "500000", horizon_days: 182, withdrawal_date: "2027-04-15", objective: "A_capital_preservation", illustrative: false, tax_basis: "your profile" },
    message: null, abstain_reasons: [], policy: null, criteria: ["Objective: A_capital_preservation"],
    ranked: [row({ instrument_id: "mf:1", rank: 1, outcome: OUTCOME, flags: ["TAX_RULE_UNVERIFIED", "LOW_EVIDENCE"] })],
    excluded: EXCLUDED, skipped_no_history: 12, contains_fixtures: false,
    report: { narrative: "", writer: "t", sections: [], disclosures: ["Ordered by the criteria and weights you set.", "Hypothetical illustration based on your assumptions; not a forecast."] },
    conflicts: [], run: { input_hash: "i", output_hash: "o", result_hash: "0123456789abcdef0123", run_id: "disc_1", versions: { supervisor: "supervisor@1.0.0" } },
    ...over,
  };
}

function stub(res: DiscoveryResult) {
  vi.stubGlobal("fetch", vi.fn(async () => json(res)));
}
const renderPage = () =>
  render(
    <MemoryRouter>
      <Discovery />
    </MemoryRouter>,
  );

afterEach(() => vi.unstubAllGlobals());

describe("Discovery", () => {
  it("leads with a scannable answer: counts, the first-ordered option and its low-end proceeds as an explainable number", async () => {
    stub(result());
    renderPage();
    expect(await screen.findByText("1 option passes every constraint; 3 did not.")).toBeInTheDocument();
    const card = screen.getByText("Result under your constraints").closest(".answer") as HTMLElement;
    expect(within(card).getByRole("link", { name: /TEST Liquid Fund/ })).toHaveAttribute("href", "/i/mf%3A1");
    await userEvent.click(within(card).getByRole("button", { name: /Proceeds low end: ₹5,05,432\.56/ }));
    expect(await screen.findByRole("heading", { name: /Explain: Proceeds low end/ })).toBeInTheDocument();
    expect(within(card).getByText("12")).toBeInTheDocument(); // not evaluated, no history
    // the required ranking disclosure stays visible in the page footer
    expect(screen.getByText("Ordered by the criteria and weights you set.", { selector: ".page-foot p" })).toBeInTheDocument();
    const text = document.body.textContent?.toLowerCase() ?? "";
    for (const w of ["best", "guaranteed", "risk-free", "you should", "recommend", "probability", "worst case"]) expect(text).not.toContain(w);
  });

  it("shows the band as low – mid – high and keeps row caveats one click away with their count", async () => {
    stub(result());
    renderPage();
    const table = await screen.findByRole("table", { name: /Options ordered by your criteria/ });
    expect(within(table).getByRole("button", { name: /Proceeds middle: ₹5,11,371\.98/ })).toBeInTheDocument();
    expect(within(table).getByText("2 caveats")).toBeInTheDocument();
    expect(within(table).getByText("tax rule unverified")).toBeInTheDocument();
  });

  it("collapses the exclusion ledger by default, with counts per reason and plain-English reasons that keep the code", async () => {
    stub(result());
    renderPage();
    const summary = (await screen.findByText("Exclusion ledger")).closest("summary")!;
    expect(summary.closest("details")).not.toHaveAttribute("open");
    expect(within(summary).getByText(/^2 ×/).textContent).toMatch(/Too little history to show a low loss rate\s*INSUFFICIENT_LOSS_EVIDENCE/);
    expect(within(summary).getByText(/^1 × Other reason/)).toBeInTheDocument();
    expect(screen.getByText("EXIT_LOAD_UNKNOWN: enter the scheme's exit load from its SID/KIM")).toBeInTheDocument();
    expect(screen.getAllByText(/Exit load not entered yet/).length).toBe(2); // ledger row + per-reason count
  });

  it("counts reason codes per instrument, most common first", () => {
    expect(ledgerCounts(EXCLUDED)).toEqual([
      ["INSUFFICIENT_LOSS_EVIDENCE", 2],
      ["EXIT_LOAD_UNKNOWN", 1],
      ["OTHER", 1],
    ]);
  });

  it("treats 'no suitable candidate' as a result: neutral copy, ledger open, clear next steps", async () => {
    stub(result({ status: "NO_SUITABLE_CANDIDATE", message: "No suitable candidate found under your current constraints.", ranked: [] }));
    renderPage();
    expect(await screen.findByRole("heading", { name: "No suitable candidate found under your current constraints." })).toBeInTheDocument();
    expect(screen.getByText(/This is a valid result, not an error/)).toBeInTheDocument();
    expect(screen.getByText("Exclusion ledger").closest("details")).toHaveAttribute("open");
    expect(screen.getByRole("link", { name: "Review your objectives and constraints" })).toHaveAttribute("href", "/onboarding");
    expect(screen.getByRole("link", { name: "Backfill history in Mutual funds" })).toHaveAttribute("href", "/mf");
    expect(screen.queryByText("Result under your constraints")).not.toBeInTheDocument();
  });

  it("ABSTAIN lists the reasons and the next actions", async () => {
    stub(result({ status: "ABSTAIN", abstain_reasons: ["MISSING: withdrawal date"], ranked: [], excluded: [], report: null }));
    renderPage();
    expect(await screen.findByRole("heading", { name: "Not enough verified context to answer" })).toBeInTheDocument();
    expect(screen.getByText("MISSING: withdrawal date")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review objectives" })).toHaveAttribute("href", "/onboarding");
    expect(screen.getByRole("link", { name: "Data health" })).toHaveAttribute("href", "/data-health");
  });
});

describe("Discovery stale responses (R-02)", () => {
  it("a slower, older response never overwrites the newer one (fixtures toggled on then off)", async () => {
    const named = (name: string) => result({ contains_fixtures: true, ranked: [row({ instrument_id: "mf:1", rank: 1, outcome: OUTCOME, name })] });
    const bodies: unknown[] = [];
    let releaseSlow: (() => void) | null = null;
    // The mock deliberately ignores the abort signal, so the page's own guard is what is tested.
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => {
        const body = JSON.parse(String(init?.body)) as { include_fixtures: boolean };
        bodies.push(body);
        if (bodies.length === 2) return new Promise<Response>((resolve) => (releaseSlow = () => resolve(json(named("STALE include=true result")))));
        return Promise.resolve(json(named(bodies.length === 1 ? "FIRST result" : "NEWEST include=false result")));
      }),
    );
    renderPage();
    expect((await screen.findAllByText("FIRST result")).length).toBeGreaterThan(0);
    const box = screen.getByRole("checkbox", { name: /Include fixtures/ });
    await userEvent.click(box); // request 2: include=true, slow
    await userEvent.click(box); // request 3: include=false, fast
    expect((await screen.findAllByText("NEWEST include=false result")).length).toBeGreaterThan(0);
    await act(async () => {
      releaseSlow?.();
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(bodies).toEqual([{ include_fixtures: false }, { include_fixtures: true }, { include_fixtures: false }]);
    expect(screen.getAllByText("NEWEST include=false result").length).toBeGreaterThan(0);
    expect(screen.queryByText("STALE include=true result")).not.toBeInTheDocument();
  });
});
