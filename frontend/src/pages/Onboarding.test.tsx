import { render, screen, waitFor } from "@testing-library/react";
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

function setup() {
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
    <MemoryRouter>
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
      <MemoryRouter>
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
