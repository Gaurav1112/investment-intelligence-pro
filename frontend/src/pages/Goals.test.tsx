import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Goals from "./Goals";

// SYNTHETIC fixtures only (repo is public): invented stress values, TEST instruments, no real scheme codes or results.

type Call = { url: string; method: string; body: unknown };
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });

const STRESS = {
  table_version: "stress-drawdowns@test",
  caveat: "The worst observed fall is not the worst possible fall.",
  rows: [
    {
      risk_class: "EQ_BROAD", label: "Broad Indian equity (TEST)", outcome: "PASS", stress: "0.5", chosen: "RECOMPUTED",
      cited_value: "0.4", recomputed_value: "0.5", series_start: "2010-01-29", series_end: "2026-09-30",
      recovery_years: "4.0", episode: "TEST-EPISODE", back_calculated: false, citation: "doc:test#stress", fact_id: "fact.test.1",
      formula_id: "risk.stress_combinator@1", status: "NOT VERIFIED", flags: [], abstain_reason: null,
    },
  ],
};

const GOALS = {
  as_of: "2026-10-16",
  stress_history: STRESS,
  setup_complete: false,
  missing: ["loss limit for Home deposit"],
  goals: [
    {
      goal_id: "g1", name: "Long-term growth", priority: 1, target_amount: "1000000", target_date: "2036-03-31",
      loss_budget_inr: "250000", recovery_months: 60, objective: null, h_safe_years: null, outcome: "PASS", abstentions: [],
      holdings: [{ instrument_id: "mf:990001", folio: "", name: "TEST Index Fund A", fraction: "1" }],
    },
    {
      goal_id: "g2", name: "Home deposit", priority: 2, target_amount: "500000", target_date: "2029-06-30",
      loss_budget_inr: null, recovery_months: null, objective: null, h_safe_years: null, outcome: "ABSTAIN", abstentions: ["loss limit not set: no equity recommendation"],
      holdings: [],
    },
  ],
};

function feas(target: string, count: number) {
  return {
    as_of: "2026-10-16",
    request: { instrument_id: "mf:990001", target_annual: target, horizon_years: 5, mode: "CAGR", as_of: "2026-10-16" },
    instrument: { instrument_id: "mf:990001", name: "TEST Index Fund A", category: "Index" },
    fixture: false,
    frequency_label: "historical frequency (overlapping windows)",
    disclaimer: "Not a forecast.",
    status: "LOW_EVIDENCE",
    evidence_level: "LOW",
    low_evidence: true,
    low_evidence_note: "Few independent periods.",
    independent_periods: 2,
    windows: 100,
    reached_target: { count, of: 100, display: `${count} of 100 windows`, frequency: null },
    caveats: ["Overlapping windows share most of their months."],
  };
}

function stub(view: unknown = GOALS) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
      calls.push({ url, method, body });
      if (url === "/api/feasibility") return json(feas(body.target_annual, body.target_annual === "0.2" ? 7 : 0));
      if (url.startsWith("/api/goals/") && method === "PUT") return json({ ...GOALS.goals[0], ...body });
      if (url.startsWith("/api/goals/") && method === "DELETE") return json({ deleted: true });
      return json(view);
    }),
  );
  return calls;
}

function renderAt(path = "/goals") {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Goals />
    </MemoryRouter>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("Goals page (C02)", () => {
  it("lists goals with the loss limit in ₹ and the crash history first; an ABSTAIN goal names what is missing", async () => {
    stub();
    renderAt();
    const history = await screen.findByRole("table", { name: /Worst falls in the available history/ });
    const first = screen.getByRole("region", { name: "Long-term growth" });
    expect(history.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(first).getByText("₹2,50,000")).toBeInTheDocument();
    expect(within(first).getByText("60 months")).toBeInTheDocument();
    // Both stress values and the AMFI series start are shown (max(cited, recomputed)).
    expect(within(history).getByText(/AMFI-recomputed −50\.0\s% \(series from 29-Jan-2010\)/)).toBeInTheDocument();
    expect(within(history).getByText(/cited −40\.0\s%/)).toBeInTheDocument();
    const second = screen.getByRole("region", { name: "Home deposit" });
    expect(within(second).getByText("ABSTAIN")).toBeInTheDocument();
    expect(within(second).getByText(/loss limit not set: no equity recommendation/)).toBeInTheDocument();
    expect(document.title).toBe("Goals · Investment Intelligence Pro");
  });

  it("the default view shows no return aim or feasibility figure", async () => {
    stub();
    renderAt();
    await screen.findByRole("region", { name: "Long-term growth" });
    expect(document.body.textContent).not.toMatch(/20\s*[–-]\s*25|% a year|historical frequency/i);
  });

  it("editing a goal sends one PUT with decimal strings; the stress history stays above the loss input", async () => {
    const calls = stub();
    renderAt();
    const card = await screen.findByRole("region", { name: "Long-term growth" });
    await userEvent.click(within(card).getByRole("button", { name: "Edit" }));
    const loss = within(card).getByLabelText(/Largest fall in ₹/);
    const history = screen.getByRole("table", { name: /Worst falls/ });
    expect(history.compareDocumentPosition(loss) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await userEvent.clear(loss);
    await userEvent.type(loss, "3,00,000");
    await userEvent.click(within(card).getByRole("button", { name: "Save goal" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.url).toBe("/api/goals/g1");
    // The id travels in the path only (GoalPatchIn rejects unknown fields). The PUT is a merge (GOAL-1): only the fields
    // this editor shows are sent; priority, objective and safe-horizon years are not, so the server keeps them.
    expect(put.body).toEqual({
      name: "Long-term growth", target_amount: "1000000", target_date: "2036-03-31",
      loss_budget_inr: "300000", recovery_months: 60,
    });
  });

  it("deleting a goal asks for confirmation on the page first", async () => {
    const calls = stub();
    renderAt();
    const card = await screen.findByRole("region", { name: "Home deposit" });
    await userEvent.click(within(card).getByRole("button", { name: "Delete" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await userEvent.click(within(card).getByRole("button", { name: "Yes, delete “Home deposit”" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.url === "/api/goals/g2")).toBe(true));
  });

  it("the feasibility view shows a return aim only as a historical frequency, with caveats and no forecast words", async () => {
    const calls = stub();
    renderAt("/goals?view=feasibility");
    await screen.findByRole("heading", { name: "Return-target feasibility" });
    await userEvent.type(screen.getByLabelText("Aim from (% a year)"), "20");
    await userEvent.type(screen.getByLabelText("Aim to (% a year)"), "25");
    await userEvent.click(screen.getByRole("button", { name: "Check history" }));
    const posts = await waitFor(() => {
      const p = calls.filter((c) => c.url === "/api/feasibility");
      expect(p).toHaveLength(2);
      return p;
    });
    expect(posts.map((p) => p.body)).toEqual([
      { instrument_id: "mf:990001", target_annual: "0.2", horizon_years: 5, mode: "CAGR" },
      { instrument_id: "mf:990001", target_annual: "0.25", horizon_years: 5, mode: "CAGR" },
    ]);
    const out = await screen.findByRole("region", { name: "Historical frequency" });
    expect(within(out).getByText(/20 % a year/)).toBeInTheDocument();
    expect(within(out).getByText("7 of 100 windows")).toBeInTheDocument();
    expect(within(out).getByText("0 of 100 windows")).toBeInTheDocument();
    expect(within(out).getAllByText(/historical frequency \(overlapping windows\)/).length).toBeGreaterThan(0);
    expect(within(out).getAllByText(/Few independent periods/)).toHaveLength(2);
    expect(within(out).getAllByText(/Overlapping windows share most of their months/)).toHaveLength(2);
    expect(screen.getByText(/never raises equity/)).toBeInTheDocument();
    expect(out.textContent).not.toMatch(/probability|chance|likely to|expected return|on track/i);
  });

  it("the feasibility view abstains for a goal with no mapped holding", async () => {
    stub();
    renderAt("/goals?view=feasibility");
    await screen.findByRole("heading", { name: "Return-target feasibility" });
    await userEvent.selectOptions(screen.getByLabelText("Goal"), "g2");
    expect(screen.getByText(/ABSTAIN: no holding is mapped to “Home deposit”/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Check history" })).not.toBeInTheDocument();
  });

  it("with no goals, points to setup", async () => {
    stub({ ...GOALS, goals: [] });
    renderAt();
    expect(await screen.findByRole("link", { name: "Run setup" })).toHaveAttribute("href", "/onboarding");
  });

  it("editing a goal never sends objective, safe-horizon years or priority: the merge keeps them (FE-1, GOAL-1)", async () => {
    const withExtras = { ...GOALS, goals: [{ ...GOALS.goals[0]!, objective: "D_growth", h_safe_years: "3" }, GOALS.goals[1]!] };
    const calls = stub(withExtras);
    renderAt();
    const card = await screen.findByRole("region", { name: "Long-term growth" });
    await userEvent.click(within(card).getByRole("button", { name: "Edit" }));
    const name = within(card).getByLabelText("Goal name");
    await userEvent.clear(name);
    await userEvent.type(name, "Retirement");
    await userEvent.click(within(card).getByRole("button", { name: "Save goal" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")!.body).toEqual({
      name: "Retirement", target_amount: "1000000", target_date: "2036-03-31", loss_budget_inr: "250000", recovery_months: 60,
    });
  });

  it("emptying a field sends an explicit null, which clears it (FE-1, GOAL-1)", async () => {
    const calls = stub();
    renderAt();
    const card = await screen.findByRole("region", { name: "Long-term growth" });
    await userEvent.click(within(card).getByRole("button", { name: "Edit" }));
    await userEvent.clear(within(card).getByLabelText(/Largest fall in ₹/));
    await userEvent.clear(within(card).getByLabelText(/Longest you would wait/));
    await userEvent.click(within(card).getByRole("button", { name: "Save goal" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")!.body).toMatchObject({ loss_budget_inr: null, recovery_months: null });
  });
});

describe("Goals editor saves through the merge (FE-1; replaces the earlier save-refusal guard)", () => {
  it("a goal view without objective or h_safe_years still saves, and the body does not carry them", async () => {
    const { objective: _o, h_safe_years: _h, ...partial } = GOALS.goals[0]!;
    const calls = stub({ ...GOALS, goals: [partial, GOALS.goals[1]!] });
    renderAt();
    const card = await screen.findByRole("region", { name: "Long-term growth" });
    await userEvent.click(within(card).getByRole("button", { name: "Edit" }));
    await userEvent.click(within(card).getByRole("button", { name: "Save goal" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const body = calls.find((c) => c.method === "PUT")!.body as Record<string, unknown>;
    expect(body).not.toHaveProperty("objective");
    expect(body).not.toHaveProperty("h_safe_years");
    expect(within(card).queryByText(/Not saved/)).not.toBeInTheDocument();
  });
});

describe("Goals page focus and tabs (a11y-architect-2/5, react-reviewer-6)", () => {
  it("Edit focuses the goal name; Cancel returns focus to Edit", async () => {
    stub();
    renderAt();
    const card = await screen.findByRole("region", { name: "Long-term growth" });
    await userEvent.click(within(card).getByRole("button", { name: "Edit" }));
    expect(within(card).getByLabelText("Goal name")).toHaveFocus();
    await userEvent.click(within(card).getByRole("button", { name: "Cancel" }));
    expect(within(card).getByRole("button", { name: "Edit" })).toHaveFocus();
  });

  it("Delete focuses 'Yes, delete'; 'Keep it' returns focus to Delete", async () => {
    stub();
    renderAt();
    const card = await screen.findByRole("region", { name: "Long-term growth" });
    await userEvent.click(within(card).getByRole("button", { name: "Delete" }));
    expect(document.activeElement).not.toBe(document.body);
    expect(within(card).getByRole("button", { name: "Yes, delete “Long-term growth”" })).toHaveFocus();
    await userEvent.click(within(card).getByRole("button", { name: "Keep it" }));
    expect(within(card).getByRole("button", { name: "Delete" })).toHaveFocus();
  });

  it("after Save the card stays on screen through the reload and focus returns to its Edit button", async () => {
    const calls = stub();
    renderAt();
    const card = await screen.findByRole("region", { name: "Long-term growth" });
    await userEvent.click(within(card).getByRole("button", { name: "Edit" }));
    await userEvent.click(within(card).getByRole("button", { name: "Save goal" }));
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/goals" && c.method === "GET")).toHaveLength(2));
    const after = await screen.findByRole("region", { name: "Long-term growth" });
    await waitFor(() => expect(within(after).getByRole("button", { name: "Edit" })).toHaveFocus());
    expect(document.activeElement).not.toBe(document.body);
  });

  it("after a delete, focus moves to the next goal's heading", async () => {
    stub();
    renderAt();
    const card = await screen.findByRole("region", { name: "Long-term growth" });
    await userEvent.click(within(card).getByRole("button", { name: "Delete" }));
    await userEvent.click(within(card).getByRole("button", { name: "Yes, delete “Long-term growth”" }));
    await waitFor(() => expect(screen.getByRole("heading", { level: 3, name: "Home deposit" })).toHaveFocus());
  });

  it("the tab strip uses the shared .tabs style so the selected view is visible", async () => {
    stub();
    renderAt();
    await screen.findByRole("region", { name: "Long-term growth" });
    expect(screen.getByRole("tablist").classList.contains("tabs")).toBe(true);
  });

  it("aria-controls only names a panel that is rendered; arrow keys move between tabs", async () => {
    stub();
    renderAt();
    await screen.findByRole("region", { name: "Long-term growth" });
    for (const tab of screen.getAllByRole("tab")) {
      const id = tab.getAttribute("aria-controls");
      if (id !== null) expect(document.getElementById(id)).not.toBeNull();
    }
    const goalsTab = screen.getByRole("tab", { name: "Goals and loss limits" });
    const feasTab = screen.getByRole("tab", { name: "Return-target feasibility" });
    expect(goalsTab).toHaveAttribute("tabindex", "0");
    expect(feasTab).toHaveAttribute("tabindex", "-1");
    goalsTab.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(await screen.findByRole("heading", { name: "Return-target feasibility", level: 2 })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Return-target feasibility" })).toHaveFocus();
    expect(screen.getByRole("tab", { name: "Return-target feasibility" })).toHaveAttribute("aria-selected", "true");
  });
});
