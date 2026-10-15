import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ProfileProvider } from "../lib/profile";
import { StartHere } from "./StartHere";

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });

const PROFILE = {
  profile: {
    amount: "500000", withdrawal_date: "2027-04-15", objective: "A_capital_preservation", loss_acceptable: false, max_loss_fraction: null,
    early_need: "possible", max_days_to_cash: 7, credit_floor: null, excluded_kinds: [], tax_regime: null, slab_rate: null, return_aspiration: null,
  },
  mode: "PERSONALISED",
  missing: [],
  horizon_days: 182,
  conflicts: [],
};

const source = (source_id: string, last_run: unknown) => ({
  source_id, name: source_id, owner: "AMFI", official: true, mode: "live", licence: "PERSONAL_USE_ONLY", licence_note: "", terms_url: null,
  freshness: "", requires_configuration: false, last_run,
});

const HEALTH = {
  sources: [
    source("amfi.navall", { status: "ok", finished_at: "2026-10-15T06:45:41+00:00", rows_ok: 14125, rows_rejected: 0, error: null }),
    source("amfi.navhistory", null),
  ],
  runs: [], observation_counts: {}, tax_rules_loaded: true, tax_rules_coverage_to: null,
};

const item = (id: string, kind: string, fixture: boolean) => ({
  instrument_id: id, kind, name: id, origin: fixture ? "fixture" : "manual", amfi_code: null, category_raw: null, plan: null,
  last_nav_date: null, last_nav: null, nav_points: 0, exit_load: null, fixture,
});

function stub(over: { profile?: unknown; health?: unknown; healthStatus?: number } = {}) {
  const calls: { url: string; method: string }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? "GET" });
      if (url === "/api/profile") return json(over.profile ?? PROFILE);
      if (url === "/api/data-health") return json(over.health ?? HEALTH, over.healthStatus ?? 200);
      if (url === "/api/instruments?kind=tbill") return json({ items: [item("tbill:fx", "tbill", true)], truncated: false });
      if (url === "/api/instruments?kind=fd") return json({ items: [], truncated: false });
      return json({ code: "NOT_FOUND" }, 404);
    }),
  );
  return calls;
}

const renderIt = (open = true) =>
  render(
    <MemoryRouter>
      <ProfileProvider>
        <StartHere defaultOpen={open} />
      </ProfileProvider>
    </MemoryRouter>,
  );

afterEach(() => vi.unstubAllGlobals());

describe("StartHere checklist", () => {
  it("shows five steps with live status, each linking to where it is done, and only reads data", async () => {
    const calls = stub();
    renderIt();
    const objectives = await screen.findByTestId("step-objectives");
    await waitFor(() => expect(objectives).toHaveAttribute("data-state", "done"));
    expect(within(objectives).getByText(/objective A · Capital preservation/)).toBeInTheDocument();
    expect(within(objectives).getByRole("link")).toHaveAttribute("href", "/onboarding");

    const nav = screen.getByTestId("step-nav");
    await waitFor(() => expect(nav).toHaveAttribute("data-state", "done"));
    expect(within(nav).getByText(/Last fetched 15-Oct-2026 06:45 UTC/)).toBeInTheDocument();
    expect(within(nav).getByRole("link")).toHaveAttribute("href", "/data-health");

    const history = screen.getByTestId("step-history");
    expect(history).toHaveAttribute("data-state", "todo");
    expect(within(history).getByRole("link")).toHaveAttribute("href", "/mf");

    // a FIXTURE T-bill is never counted as "added"
    const fixed = screen.getByTestId("step-fixed");
    await waitFor(() => expect(fixed).toHaveAttribute("data-state", "todo"));
    expect(within(fixed).getByText(/1 FIXTURE item\(s\) are not counted/)).toBeInTheDocument();
    expect(within(fixed).getByRole("link")).toHaveAttribute("href", "/fi");

    const discover = screen.getByTestId("step-discover");
    expect(discover).toHaveAttribute("data-state", "next");
    expect(within(discover).getByRole("link")).toHaveAttribute("href", "/discover");

    expect(screen.getByText("2 of 4 setup steps done")).toBeInTheDocument();
    expect(calls.every((c) => c.method === "GET")).toBe(true);
  });

  it("flags profile conflicts and exploration mode instead of marking the step done", async () => {
    stub({ profile: { ...PROFILE, conflicts: ["CONSTRAINT_CONFLICT: a", "CONSTRAINT_CONFLICT: b"] } });
    renderIt();
    const objectives = await screen.findByTestId("step-objectives");
    await waitFor(() => expect(objectives).toHaveAttribute("data-state", "attention"));
    expect(within(objectives).getByText(/2 setting conflicts to review/)).toBeInTheDocument();
  });

  it("says the status is unavailable when Data health cannot be read, never 'done'", async () => {
    stub({ healthStatus: 500, health: { code: "BOOM" } });
    renderIt();
    const nav = await screen.findByTestId("step-nav");
    await waitFor(() => expect(within(nav).getByText(/Could not read Data health/)).toBeInTheDocument());
    expect(nav).toHaveAttribute("data-state", "unknown");
    expect(screen.getByTestId("step-discover")).toHaveAttribute("data-state", "todo");
  });

  it("is a collapsible card, open on first run and closed otherwise", async () => {
    stub();
    const { unmount } = renderIt(true);
    expect(screen.getByText("Start here").closest("details")).toHaveAttribute("open");
    unmount();
    renderIt(false);
    expect(screen.getByText("Start here").closest("details")).not.toHaveAttribute("open");
  });
});
