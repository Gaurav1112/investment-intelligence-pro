import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { clearApiCache } from "../lib/api";
import { RULE_SE_NO_GATE, SIGNALS } from "../test/signalsFixtures";
import Signals from "./Signals";

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
function stubFetch(handler: (url: string) => Response) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      return handler(url);
    }),
  );
  return calls;
}

const renderPage = () =>
  render(
    <MemoryRouter>
      <Signals />
    </MemoryRouter>,
  );

beforeEach(() => clearApiCache());
afterEach(() => vi.unstubAllGlobals());

const rowOf = (ruleId: string) => {
  const link = screen.getByRole("link", { name: new RegExp(`^${ruleId} v1`) });
  return within(link.closest("tr") as HTMLElement);
};

describe("Signals registry", () => {
  it("loads the registry in one request", async () => {
    const calls = stubFetch(() => json(SIGNALS));
    renderPage();
    await screen.findByRole("link", { name: /^S-E v1/ });
    expect(calls).toEqual(["/api/signals"]);
  });

  it("renders every row as ABSTAIN with its failing gate", async () => {
    stubFetch(() => json(SIGNALS));
    renderPage();
    await screen.findByRole("link", { name: /^S-E v1/ });
    const body = screen.getAllByRole("rowgroup")[1] as HTMLElement;
    expect(within(body).getAllByRole("row")).toHaveLength(SIGNALS.rules.length);
    for (const r of SIGNALS.rules) {
      const row = rowOf(r.rule_id);
      expect(row.getByText("ABSTAIN")).toBeInTheDocument();
      const g = r.failing_gate!;
      expect(row.getByText(new RegExp(`^${g.gate_id} `))).toBeInTheDocument();
      expect(row.getByText(new RegExp(g.reason_code!))).toBeInTheDocument();
    }
  });

  it("shows ABSTAIN even when the stored state is ACCEPTED but a gate still fails (fail closed)", async () => {
    stubFetch(() => json(SIGNALS));
    renderPage();
    const row = (await screen.findByRole("link", { name: /^S-G v1/ })).closest("tr") as HTMLElement;
    expect(within(row).getByText("ABSTAIN")).toBeInTheDocument();
    expect(within(row).getByText("Accepted")).toBeInTheDocument(); // the stored registry state is still visible
    expect(within(row).getByText(/G10 Robustness/)).toBeInTheDocument();
  });

  it("fails closed when a non-accepted rule reports no failing gate", async () => {
    stubFetch(() => json({ ...SIGNALS, rules: [RULE_SE_NO_GATE] }));
    renderPage();
    const row = (await screen.findByRole("link", { name: /^S-X v1/ })).closest("tr") as HTMLElement;
    expect(within(row).getByText("ABSTAIN")).toBeInTheDocument();
    expect(within(row).getByText(/Failing gate not reported/)).toBeInTheDocument();
  });

  it("shows trial count, shadow record and the earliest possible review as YYYY-MM", async () => {
    stubFetch(() => json(SIGNALS));
    renderPage();
    await screen.findByRole("link", { name: /^S-E v1/ });
    const se = rowOf("S-E");
    expect(se.getByText("1")).toBeInTheDocument();
    expect(se.getByText(/12 daily evaluations since 02-Oct-2026/)).toBeInTheDocument();
    expect(se.getByText("Earliest possible review: 2037-04")).toBeInTheDocument();
    const sd = rowOf("S-D");
    expect(sd.getByText("3")).toBeInTheDocument();
    expect(sd.getByText("No shadow evaluations yet")).toBeInTheDocument();
    expect(sd.getByText("Earliest possible review: not computed (no backtest run yet)")).toBeInTheDocument();
  });

  it("links each rule to its detail page", async () => {
    stubFetch(() => json(SIGNALS));
    renderPage();
    expect(await screen.findByRole("link", { name: /^S-E v1/ })).toHaveAttribute("href", "/signals/S-E/1");
  });

  it("lists stocks as ABSTAIN outside the registry (U-10) and carries the footer disclosure", async () => {
    stubFetch(() => json(SIGNALS));
    renderPage();
    await screen.findByRole("link", { name: /^S-E v1/ });
    expect(screen.getByText(/no_lawful_survivorship_free_data/)).toBeInTheDocument();
    expect(screen.getByText(/Not investment advice/)).toBeInTheDocument();
  });

  it("uses neutral wording: no BUY/SELL or forecast language anywhere on the page", async () => {
    stubFetch(() => json(SIGNALS));
    const { container } = renderPage();
    await screen.findByRole("link", { name: /^S-E v1/ });
    const text = container.textContent ?? "";
    for (const banned of [/\bbuy\b/i, /\bsell\b/i, /buy now/i, /sell now/i, /guarantee/i, /recommend/i, /you should/i])
      expect(text).not.toMatch(banned);
  });

  it("shows an empty state when nothing is registered", async () => {
    stubFetch(() => json({ as_of: null, vocabulary: "neutral", rules: [] }));
    renderPage();
    expect(await screen.findByText("No rules are registered yet")).toBeInTheDocument();
  });

  it("shows an error, not a stale or partial table, when the request fails", async () => {
    stubFetch(() => json({ code: "INTERNAL", message: "boom" }, 500));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(/No result is shown/);
    expect(screen.queryByRole("table")).toBeNull();
  });
});
