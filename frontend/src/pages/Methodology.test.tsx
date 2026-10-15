import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { MethodologyResponse } from "../lib/types";
import Methodology from "./Methodology";

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
const stub = (body: unknown, status = 200) => vi.stubGlobal("fetch", vi.fn(async () => json(body, status)));
afterEach(() => vi.unstubAllGlobals());

const METHOD: MethodologyResponse = {
  versions: { ranking_policy: "ranking-0.3.0", candidates: "candidates-0.2.1", compliance: "2026.10.1", discovery: "discovery-0.1.0" },
  tax: {
    snapshot_date: "2026-10-01",
    coverage_to: "2027-03-31",
    rules: [
      { rule_id: "fd.interest.slab", instrument_class: "fd", effective_from: "2024-04-01", effective_to: null, verification: "P", source_url: "https://incometaxindia.gov.in/x" },
      { rule_id: "mf.debt.50aa", instrument_class: "mf_debt", effective_from: "2023-04-01", effective_to: "2027-03-31", verification: "S", source_url: "https://example.gov.in/y" },
      { rule_id: "tbill.discount", instrument_class: "tbill", effective_from: "2024-04-01", effective_to: null, verification: "NV", source_url: "https://example.gov.in/z" },
    ],
  },
  disclosures: {
    past_performance: "Past performance may or may not be sustained in future and is not a guarantee of future returns.",
    ranking: "Ordered by the criteria and weights you set.",
  },
};

const renderPage = () =>
  render(
    <MemoryRouter>
      <Methodology />
    </MemoryRouter>,
  );

describe("Methodology", () => {
  it("renders versions, tax rules with NV clearly flagged, disclosures and the ordering policy", async () => {
    stub(METHOD);
    renderPage();
    expect(await screen.findByText("ranking-0.3.0")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: /Tax rules/ });
    const nvRow = within(table).getByText("tbill.discount").closest("tr")!;
    expect(nvRow).toHaveTextContent("NV · not verified — pending professional review");
    expect(within(table).getByText("fd.interest.slab").closest("tr")!).toHaveTextContent("P · verified against a primary source");
    expect(within(table).getByText("01-Apr-2023")).toBeInTheDocument();
    expect(within(table).getAllByText("open-ended")).toHaveLength(2);
    expect(within(table).getByRole("link", { name: "incometaxindia.gov.in" })).toHaveAttribute("href", "https://incometaxindia.gov.in/x");
    expect(screen.getByRole("note")).toHaveTextContent("1 rule is not verified — pending professional review");
    expect(screen.getByText("Ordered by the criteria and weights you set.")).toBeInTheDocument();
    for (const h of ["Eligibility comes before any ordering", "Certainty tiers", "No composite score", "ABSTAIN when context is missing"])
      expect(screen.getByRole("heading", { name: new RegExp(h) })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /No suitable candidate/ })).toBeInTheDocument();
    expect(screen.getAllByText(/T1 · Contractual · sovereign/).length).toBe(1);
  });

  it("says plainly when tax rules failed to load and when nothing else was returned", async () => {
    stub({ versions: {}, tax: null, disclosures: {} });
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("tax rule file failed to load");
    expect(screen.getByText("No version information was returned.")).toBeInTheDocument();
    expect(screen.getByText("No disclosure texts were returned.")).toBeInTheDocument();
  });

  it("shows an error state", async () => {
    stub({ code: "INTERNAL_ERROR" }, 500);
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("INTERNAL_ERROR");
  });
});

describe("banned copy (ux-design §1.11, §6)", () => {
  const PAGES = ["MfExplorer", "FixedIncome", "InstrumentDetail", "DataHealth", "Methodology"];
  it.each(PAGES)("%s.tsx contains no banned words", (name) => {
    const src = readFileSync(resolve(__dirname, `${name}.tsx`), "utf8").toLowerCase();
    for (const word of ["best", "guaranteed", "risk-free", "you should", "recommend"]) expect(src).not.toContain(word);
    expect(src).not.toContain("dangerouslysetinnerhtml");
  });
});
