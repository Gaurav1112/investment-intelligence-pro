import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { DiscoveryResult } from "../lib/types";
import type { LlmReportFields } from "../lib/types-llm";
import Discovery from "./Discovery";

// Report shape follows backend/src/iip/services/discovery.py (writer, narrative, template_narrative, disclosures).
const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200, headers: { "Content-Type": "application/json" } });
const AI = "AI-generated wording. Every number comes from the deterministic engine or a dated source.";
const TEMPLATE = "Evaluated 6 instruments; 4 passed every constraint.";
const REWORDED = "Put simply: 6 instruments were checked and 4 passed every constraint.";

function result(report: DiscoveryResult["report"] & Partial<LlmReportFields>): DiscoveryResult {
  return {
    status: "EXPLORATION", mode: "EXPLORATION", as_of: "2026-10-15",
    context: { amount: "₹1,00,000.00", amount_value: "100000", horizon_days: 182, withdrawal_date: "2027-04-15", objective: "A_capital_preservation", illustrative: true, tax_basis: "illustrative" },
    message: null, abstain_reasons: [], policy: null, criteria: [], ranked: [], excluded: [], skipped_no_history: 0, contains_fixtures: false,
    report, conflicts: [], run: { input_hash: "i", output_hash: "o", result_hash: "0123456789abcdef0123", run_id: "disc_1", versions: {} },
  };
}
const SECTIONS = [{ worker: "quant", subject: "universe", topic: "coverage", stance: "supports", text: TEMPLATE }];

function show(res: DiscoveryResult) {
  vi.stubGlobal("fetch", vi.fn(async () => json(res)));
  render(
    <MemoryRouter>
      <Discovery />
    </MemoryRouter>,
  );
}
afterEach(() => vi.unstubAllGlobals());

describe("Discovery — optional AI wording", () => {
  it("labels LLM wording, shows the AI disclosure, and toggles to the deterministic template", async () => {
    show(result({ narrative: REWORDED, writer: "llm", template_narrative: TEMPLATE, sections: SECTIONS, disclosures: ["Personal research tool. Not investment advice.", AI] }));
    expect(await screen.findByText("AI-generated wording", { selector: ".ai-label" })).toBeInTheDocument();
    expect(screen.getByText(AI, { selector: ".ai-disclosure" })).toBeInTheDocument();
    expect(screen.getByTestId("ai-text")).toHaveTextContent(REWORDED);
    expect(screen.queryByTestId("template-text")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Show deterministic wording" }));
    expect(screen.getByTestId("template-text")).toHaveTextContent(TEMPLATE);
    expect(screen.queryByTestId("ai-text")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Show AI wording" }));
    expect(screen.getByTestId("ai-text")).toBeInTheDocument();
  });

  it("renders LLM text as inert plain text", async () => {
    show(result({ narrative: "<img src=x onerror=alert(1)>", writer: "llm", sections: SECTIONS, disclosures: [AI] }));
    expect(await screen.findByTestId("ai-text")).toHaveTextContent("<img src=x onerror=alert(1)>");
    expect(document.querySelector("img")).toBeNull();
  });

  it("shows no AI label for the deterministic writer", async () => {
    show(result({ narrative: TEMPLATE, writer: "template", template_narrative: TEMPLATE, sections: SECTIONS, disclosures: [] }));
    expect(await screen.findByText(TEMPLATE)).toBeInTheDocument();
    expect(screen.queryByText("AI-generated wording")).toBeNull();
    expect(screen.queryByRole("button", { name: /deterministic wording/ })).toBeNull();
  });
});
