import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ProfileProvider } from "../lib/profile";
import Onboarding from "./Onboarding";

type Call = { url: string; method: string; body: unknown };
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });

const STATUS = {
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
    return_aspiration: null,
  },
  mode: "EXPLORATION",
  missing: [],
  horizon_days: null,
  conflicts: [],
};

function setup(path = "/onboarding?tab=objectives") {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      calls.push({ url, method, body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined });
      return json(STATUS);
    }),
  );
  render(
    <MemoryRouter initialEntries={[path]}>
      <ProfileProvider>
        <Onboarding />
      </ProfileProvider>
    </MemoryRouter>,
  );
  return calls;
}

const puts = (calls: Call[]) => calls.filter((c) => c.method === "PUT");

afterEach(() => vi.unstubAllGlobals());

describe("Onboarding validation (A11Y-1)", () => {
  it("keeps Save enabled; an invalid slab gives a focused error summary that links to the field, and nothing is sent", async () => {
    const calls = setup();
    await waitFor(() => expect(calls.some((c) => c.url === "/api/profile")).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "5. Liquidity & extras" }));
    await userEvent.type(screen.getByLabelText(/marginal income-tax slab/), "30%");
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeEnabled();
    await userEvent.click(save);

    const summary = await screen.findByRole("alert");
    expect(summary).toHaveTextContent("Not saved yet");
    expect(summary).toHaveTextContent(/Income-tax slab: enter a number only/);
    await waitFor(() => expect(summary).toHaveFocus());
    expect(puts(calls)).toHaveLength(0);

    const slab = screen.getByLabelText(/marginal income-tax slab/);
    expect(slab).toHaveAttribute("aria-invalid", "true");
    expect(slab).toHaveAccessibleDescription(/Income-tax slab: enter a number only/);

    // The summary link takes the user to the right step and field.
    await userEvent.click(screen.getByRole("button", { name: "1. Amount" }));
    await userEvent.click(screen.getByRole("link", { name: /Income-tax slab/ }));
    expect(screen.getByLabelText(/marginal income-tax slab/)).toHaveFocus();
  });

  it("an invalid loss limit hidden behind 'No' no longer blocks saving", async () => {
    const calls = setup();
    await waitFor(() => expect(calls.some((c) => c.url === "/api/profile")).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "4. Loss & early need" }));
    await userEvent.click(screen.getByRole("radio", { name: /Yes, up/ }));
    await userEvent.type(screen.getByLabelText(/Largest loss you would accept/), "10%");
    await userEvent.click(screen.getByRole("radio", { name: "No" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0]!.body).toMatchObject({ loss_acceptable: false, max_loss_fraction: null });
    expect(screen.queryByText("Not saved yet", { exact: false })).not.toBeInTheDocument();
  });

  it("sets its own document title", async () => {
    setup();
    await waitFor(() => expect(document.title).toBe("Your objectives · Investment Intelligence Pro"));
  });
});

describe("Onboarding: growth objectives need a loss limit (user report 2026-10-15)", () => {
  it("growth + 'No' to loss is caught before saving and points at the loss question; nothing is sent", async () => {
    const calls = setup();
    await waitFor(() => expect(calls.some((c) => c.url === "/api/profile")).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "3. Objective" }));
    await userEvent.click(screen.getByRole("radio", { name: /Risk-adjusted growth/ }));
    expect(screen.getByText(/Growth objectives need a loss limit: the next step asks/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "4. Loss & early need" }));
    await userEvent.click(screen.getByRole("radio", { name: "No" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    const summary = await screen.findByRole("alert");
    expect(summary).toHaveTextContent(/growth objective \(D or E\), which needs a loss limit/);
    expect(puts(calls)).toHaveLength(0);
    await userEvent.click(screen.getByRole("link", { name: /growth objective/ }));
    expect(screen.getByRole("radio", { name: /Yes, up to a limit/ })).toHaveFocus();
  });

  it("growth + 'Yes' with an empty limit asks for the limit; with a limit it saves", async () => {
    const calls = setup();
    await waitFor(() => expect(calls.some((c) => c.url === "/api/profile")).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "3. Objective" }));
    await userEvent.click(screen.getByRole("radio", { name: /Aggressive growth/ }));
    await userEvent.click(screen.getByRole("button", { name: "4. Loss & early need" }));
    await userEvent.click(screen.getByRole("radio", { name: /Yes, up to a limit/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/required for growth objectives/);
    expect(puts(calls)).toHaveLength(0);

    await userEvent.type(screen.getByLabelText(/Largest loss you would accept/), "15");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0]?.body).toMatchObject({ objective: "E_aggressive_growth", loss_acceptable: true, max_loss_fraction: "0.15" });
  });

  it("a server refusal shows the server's own reason, not a guess", async () => {
    const calls: Call[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? "GET";
        calls.push({ url, method, body: undefined });
        if (method === "PUT")
          return json({ detail: [{ loc: ["body"], msg: "Value error, withdrawal date must be after today", type: "value_error" }] }, 422);
        return json(STATUS);
      }),
    );
    render(
      <MemoryRouter initialEntries={["/onboarding?tab=objectives"]}>
        <ProfileProvider>
          <Onboarding />
        </ProfileProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(calls.some((c) => c.url === "/api/profile")).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Not saved: withdrawal date must be after today\./)).toBeInTheDocument();
  });
});

describe("Onboarding: tax regime and slab (walkthrough 2026-10-15)", () => {
  it("a slab without the new regime ticked is flagged instead of being silently replaced by the illustrative slab", async () => {
    const calls = setup();
    await waitFor(() => expect(calls.some((c) => c.url === "/api/profile")).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "5. Liquidity & extras" }));
    await userEvent.type(screen.getByLabelText(/marginal income-tax slab/), "20");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/used only under the new tax regime/);
    expect(puts(calls)).toHaveLength(0);
    await userEvent.click(screen.getByRole("checkbox", { name: /new tax regime/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0]?.body).toMatchObject({ tax_regime: "new", slab_rate: "0.2" });
  });

  it("the growth/loss message is not shown before the loss question is answered", async () => {
    const calls = setup();
    await waitFor(() => expect(calls.some((c) => c.url === "/api/profile")).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "3. Objective" }));
    await userEvent.click(screen.getByRole("radio", { name: /Risk-adjusted growth/ }));
    await userEvent.click(screen.getByRole("button", { name: "4. Loss & early need" }));
    expect(screen.queryByText(/which needs a loss limit/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "No" }));
    expect(screen.getByText(/which needs a loss limit/)).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------ wave-2 setup: one CAS upload + about six answers (C02)
// SYNTHETIC fixtures only: the stress values below are invented round numbers, not index statistics (repo is public).

const STRESS = {
  table_version: "stress-drawdowns@test",
  caveat: "The worst observed fall is not the worst possible fall.",
  rows: [
    {
      risk_class: "EQ_BROAD", label: "Broad Indian equity (TEST)", outcome: "PASS", stress: "0.5", chosen: "CITED",
      cited_value: "0.5", recomputed_value: "0.4", series_start: "2010-01-29", series_end: "2026-09-30",
      recovery_years: "4.0", episode: "TEST-EPISODE", back_calculated: false, citation: "doc:test#stress", fact_id: "fact.test.1",
      formula_id: "risk.stress_combinator@1", status: "NOT VERIFIED", flags: [], abstain_reason: null,
    },
    {
      risk_class: "EQ_MID", label: "Mid-cap equity (TEST)", outcome: "ABSTAIN", stress: null, chosen: null, cited_value: null,
      recomputed_value: null, series_start: null, series_end: null, recovery_years: null, episode: null, back_calculated: true,
      citation: null, fact_id: null, formula_id: "risk.stress_combinator@1", status: "REQUIRES CONFIGURATION", flags: [],
      abstain_reason: "stress value for EQ_MID",
    },
  ],
};

const SETUP_EMPTY = {
  stress_history: STRESS,
  answers: {
    tax: { use_conservative: false, regime: null, slab_rate: null },
    emergency: { essential_monthly_expenses: null, months: null },
    goals: [],
    extras: { ltcg_used_inr: null, savings_balance: null, sweep_fd_balance: null },
  },
  cas_imported: false,
  missing: ["CAS", "tax", "emergency fund", "goals", "loss limit"],
  complete: false,
};

const ONE_GOAL = {
  ...SETUP_EMPTY,
  answers: {
    ...SETUP_EMPTY.answers,
    goals: [
      { goal_id: "g1", name: "Long-term growth", priority: 1, target_amount: "100000", target_date: "2036-03-31", loss_budget_inr: null, recovery_months: null },
    ],
  },
};

function setupWizard(state: unknown = SETUP_EMPTY, portfolios: unknown[] = [{ portfolio_id: "p1", name: "Mine", nature: "actual", created_at: "2026-01-01T00:00:00Z", transactions: 0 }]) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
      calls.push({ url, method, body });
      if (url === "/api/goals/setup" && method === "PUT") return json({ ...SETUP_EMPTY, answers: body, missing: [], complete: true });
      if (url === "/api/goals/setup") return json(state);
      if (url === "/api/portfolios" && method === "POST")
        return json({ portfolio_id: "p-new", name: body.name, nature: body.nature, created_at: "2026-01-01T00:00:00Z" });
      if (url === "/api/portfolios") return json({ items: portfolios });
      return json(STATUS);
    }),
  );
  render(
    <MemoryRouter initialEntries={["/onboarding"]}>
      <ProfileProvider>
        <Onboarding />
      </ProfileProvider>
    </MemoryRouter>,
  );
  return calls;
}

const step = (name: RegExp) => userEvent.click(screen.getByRole("button", { name }));

describe("Setup: one upload and about six answers (C02)", () => {
  it("is the default view, titled Setup, with one upload step and six answer steps before review", async () => {
    setupWizard();
    expect(await screen.findByRole("heading", { level: 1, name: "Setup" })).toBeInTheDocument();
    await waitFor(() => expect(document.title).toBe("Setup · Investment Intelligence Pro"));
    const progress = screen.getByRole("list", { name: "Setup progress" });
    const names = within(progress).getAllByRole("button").map((b) => b.textContent);
    expect(names).toEqual([
      "1. Upload CAS", "2. Tax", "3. Emergency fund", "4. Goals", "5. Loss limit", "6. Recovery time", "7. Optional extras", "8. Review",
    ]);
  });

  it("the CAS step mounts the CAS import for the actual portfolio", async () => {
    setupWizard();
    expect(await screen.findByLabelText("PDF password", {}, { timeout: 5000 })).toBeInTheDocument(); // lazy chunk
    expect(screen.getByText(/You can skip this step/)).toBeInTheDocument();
  });

  it("with no actual portfolio, the CAS step creates one on request", async () => {
    const calls = setupWizard(SETUP_EMPTY, []);
    await userEvent.click(await screen.findByRole("button", { name: /Create an actual portfolio/ }));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/portfolios" && c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ name: "My holdings", nature: "actual" });
  });

  it("the loss-limit step shows the crash history BEFORE any input, and no return figure at all", async () => {
    setupWizard(ONE_GOAL);
    await screen.findByRole("heading", { level: 1, name: "Setup" });
    await step(/5\. Loss limit/);
    const history = await screen.findByRole("table", { name: /Worst falls in the available history/ });
    const input = screen.getByLabelText(/Largest fall in ₹ you would sit through without selling.*Long-term growth/);
    // Document order: the history table comes before the loss input.
    expect(history.compareDocumentPosition(input) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(history).getByText(/^−50\.0\s%$/)).toBeInTheDocument();
    expect(within(history).getByText(/REQUIRES CONFIGURATION/)).toBeInTheDocument();
    // On the goal's ₹1,00,000 the synthetic −50 % fall is ₹50,000 (goal amount × worst fall).
    expect(screen.getByText(/₹50,000/)).toBeInTheDocument();
    expect(screen.getByText("The worst observed fall is not the worst possible fall.")).toBeInTheDocument();
    const panel = screen.getByRole("group", { name: "Loss limit" });
    expect(panel.textContent).not.toMatch(/a year|p\.a\.|CAGR|return|aspir|hoping/i);
  });

  it("the recovery step states the historical recovery when it is longer than the user's limit", async () => {
    setupWizard(ONE_GOAL);
    await screen.findByRole("heading", { level: 1, name: "Setup" });
    await step(/6\. Recovery time/);
    await userEvent.type(screen.getByLabelText(/Longest you would wait for a recovery.*Long-term growth/), "24");
    expect(screen.getByText(/recovery took 4\.0 years \(48 months\); your limit is 24 months/)).toBeInTheDocument();
  });

  it("no step asks for, or shows, a return aim (it lives only on the Goals feasibility view)", async () => {
    setupWizard(ONE_GOAL);
    await screen.findByRole("heading", { level: 1, name: "Setup" });
    for (const name of [/1\. Upload/, /2\. Tax/, /3\. Emergency/, /4\. Goals/, /5\. Loss/, /6\. Recovery/, /7\. Optional/, /8\. Review/]) {
      await step(name);
      const main = screen.getByRole("main");
      expect(main.textContent).not.toMatch(/20\s*[–-]\s*25|hoping for|aspiration|% a year/i);
    }
  });

  it("answers flow into one PUT /api/goals/setup with decimal strings, and the result links to Goals", async () => {
    const calls = setupWizard();
    await screen.findByRole("heading", { level: 1, name: "Setup" });
    await step(/2\. Tax/);
    await userEvent.click(screen.getByRole("radio", { name: "New regime" }));
    await userEvent.type(screen.getByLabelText(/Marginal income-tax slab/), "20");
    await step(/3\. Emergency/);
    await userEvent.type(screen.getByLabelText(/Essential monthly expenses/), "40,000");
    await userEvent.click(screen.getByRole("radio", { name: "6 months" }));
    await step(/4\. Goals/);
    await userEvent.click(screen.getByRole("button", { name: "Add “Long-term growth”" }));
    await userEvent.type(screen.getByLabelText("Goal amount (₹) — Long-term growth"), "1000000");
    await userEvent.type(screen.getByLabelText("Goal date — Long-term growth"), "2036-03-31");
    await step(/5\. Loss limit/);
    await userEvent.type(screen.getByLabelText(/Largest fall in ₹ .*Long-term growth/), "250000");
    await step(/6\. Recovery/);
    await userEvent.type(screen.getByLabelText(/Longest you would wait .*Long-term growth/), "60");
    await step(/8\. Review/);
    await userEvent.click(screen.getByRole("button", { name: "Save setup" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.url === "/api/goals/setup")).toBe(true));
    const body = calls.find((c) => c.method === "PUT")!.body;
    expect(body).toEqual({
      tax: { use_conservative: false, regime: "new", slab_rate: "0.2" },
      emergency: { essential_monthly_expenses: "40000", months: 6 },
      goals: [
        { goal_id: null, name: "Long-term growth", priority: 1, target_amount: "1000000", target_date: "2036-03-31", loss_budget_inr: "250000", recovery_months: 60 },
      ],
      extras: { ltcg_used_inr: null, savings_balance: null, sweep_fd_balance: null },
    });
    expect(await screen.findByText(/Setup saved/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open your goals" })).toHaveAttribute("href", "/goals");
  });

  it("the conservative tax assumption sends no regime or slab and is labelled", async () => {
    const calls = setupWizard();
    await screen.findByRole("heading", { level: 1, name: "Setup" });
    await step(/2\. Tax/);
    await userEvent.click(screen.getByRole("radio", { name: /Use the conservative assumption/ }));
    expect(screen.queryByLabelText(/Marginal income-tax slab/)).not.toBeInTheDocument();
    await step(/8\. Review/);
    await userEvent.click(screen.getByRole("button", { name: "Save setup" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect((calls.find((c) => c.method === "PUT")!.body as { tax: unknown }).tax).toEqual({ use_conservative: true, regime: null, slab_rate: null });
  });

  it("a loss limit above the goal amount and a non-numeric expense are caught before saving; nothing is sent", async () => {
    const calls = setupWizard(ONE_GOAL);
    await screen.findByRole("heading", { level: 1, name: "Setup" });
    await step(/3\. Emergency/);
    await userEvent.type(screen.getByLabelText(/Essential monthly expenses/), "abc");
    await step(/5\. Loss limit/);
    await userEvent.type(screen.getByLabelText(/Largest fall in ₹ .*Long-term growth/), "200000");
    await step(/8\. Review/);
    await userEvent.click(screen.getByRole("button", { name: "Save setup" }));
    const summary = await screen.findByRole("alert");
    expect(summary).toHaveTextContent(/Essential monthly expenses: digits only/);
    expect(summary).toHaveTextContent(/Loss limit for “Long-term growth” cannot be more than the goal amount/);
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
    await userEvent.click(screen.getByRole("link", { name: /Loss limit for/ }));
    expect(screen.getByLabelText(/Largest fall in ₹ .*Long-term growth/)).toHaveFocus();
  });

  it("the objectives tab keeps the Discovery details form, without the return-aim question", async () => {
    setup();
    await screen.findByRole("heading", { level: 1, name: "Your objectives" });
    await userEvent.click(screen.getByRole("button", { name: "5. Liquidity & extras" }));
    expect(screen.queryByLabelText(/Return you are hoping for/)).not.toBeInTheDocument();
  });
});
