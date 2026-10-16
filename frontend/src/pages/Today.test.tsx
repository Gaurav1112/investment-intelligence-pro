import { render, screen, within } from "@testing-library/react";
import { onTestFinished } from "vitest";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { clearApiCache } from "../lib/api";
import type { CardView, TodayResponse } from "../lib/types-actions";
import { harvestCard, shortfallCard, todayAbstained, todayActions, todayNoSnapshot, todayNothing } from "../test/todayFixtures";
import Today from "./Today";

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });

// Pin the calendar date so the staleness check is deterministic (only Date is faked; timers stay real).
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-15T06:30:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  clearApiCache();
});

function mount(body: TodayResponse | null, status = 200) {
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => json(body ?? { code: "INTERNAL" }, status));
  vi.stubGlobal("fetch", fetchMock);
  render(
    <MemoryRouter>
      <Today />
    </MemoryRouter>,
  );
  return fetchMock;
}

describe("Today page", () => {
  it("loads in exactly one API call: GET /api/today", async () => {
    const fetchMock = mount(todayActions);
    await screen.findByRole("article", { name: /Emergency reserve short/ });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]![0]).toBe("/api/today");
    expect(fetchMock.mock.calls[0]![1]?.method ?? "GET").toBe("GET");
  });

  it("shows cards in the server's rank order, then Needs from you", async () => {
    mount(todayActions);
    const actions = await screen.findByRole("region", { name: "What your rules say today" });
    const titles = within(actions)
      .getAllByRole("article")
      .map((a) => within(a).getAllByRole("heading")[0]!.textContent);
    expect(titles[0]).toMatch(/Emergency reserve short/);
    expect(titles[1]).toMatch(/Long-term gains allowance unused/);
    expect(titles[2]).toMatch(/Abstained/);
    const needs = screen.getByRole("region", { name: "Needs from you" });
    expect(within(needs).getByText("Loss limit")).toBeInTheDocument();
  });

  it("shows the data date, compute time and snapshot", async () => {
    mount(todayActions);
    expect(await screen.findByText(/Data as of 14-Oct-2026/)).toBeInTheDocument();
    expect(screen.getByText(/computed 15-Oct-2026 01:30 UTC/)).toBeInTheDocument();
    expect(screen.getByText(/Data as of/).closest("span")).toHaveTextContent("snapshot ssssssssssss");
  });

  it("every number opens its formula and source in the ExplainDrawer", async () => {
    // jsdom has no HTMLDialogElement.close(); emulate it so the drawer's close path runs.
    const proto = HTMLDialogElement.prototype as { close?: () => void };
    const had = "close" in proto;
    if (!had)
      proto.close = function (this: HTMLDialogElement) {
        this.removeAttribute("open");
      };
    onTestFinished(() => {
      if (!had) delete proto.close;
    });
    mount(todayActions);
    const card = await screen.findByRole("article", { name: /Emergency reserve short/ });
    await userEvent.click(within(within(card).getByTestId("card-text")).getAllByRole("button")[0]!);
    const dialog = screen.getByRole("dialog", { name: /Explain: shortfall/ });
    expect(within(dialog).getByText("risk.emergency_gate@1", { exact: false })).toBeInTheDocument();
    expect(within(dialog).getByText(/Synthetic source 0/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Close explanation" }));
    expect(screen.queryByText(/Explain: shortfall/)).not.toBeInTheDocument();
  });

  it("every number on the page is explainable: each rendered card number is a button", async () => {
    mount(todayActions);
    await screen.findByRole("article", { name: /Emergency reserve short/ });
    const all: CardView[] = todayActions.cards;
    const displays = all.flatMap((c) => [...c.numbers, ...c.steps.flatMap((s) => s.numbers)].map((n) => n.display));
    for (const d of new Set(displays)) {
      expect(screen.getAllByRole("button", { name: new RegExp(`${d.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\. Press to explain`) }).length).toBeGreaterThan(0);
    }
  });

  it("'No action needed' is a first-class state", async () => {
    mount(todayNothing);
    expect(await screen.findByRole("heading", { level: 2, name: "No action needed" })).toBeInTheDocument();
    expect(screen.getByText(/All your rules are within limits today/)).toBeInTheDocument();
    expect(screen.getByText("Nothing is needed from you today.")).toBeInTheDocument();
  });

  it("ABSTAIN-only is a first-class state, not an error", async () => {
    mount(todayAbstained);
    expect(await screen.findByRole("heading", { level: 2, name: "No action today: the engine abstained" })).toBeInTheDocument();
    expect(screen.getAllByRole("status")[0]).toHaveTextContent(/expected result, not an error/);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Needs from you" })).toHaveTextContent("Loss limit");
  });

  it("no snapshot yet: says the daily job computes it and shows no cards", async () => {
    mount(todayNoSnapshot);
    expect(await screen.findByRole("heading", { level: 2, name: "No snapshot yet" })).toBeInTheDocument();
    expect(screen.getByText(/never on page load/)).toBeInTheDocument();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
  });

  it("an API failure shows the error state, never stale or invented cards", async () => {
    mount(null, 500);
    expect(await screen.findByRole("alert")).toHaveTextContent(/No result is shown/);
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
  });

  it("shows top_n cards and reveals the rest on request", async () => {
    mount({ ...todayActions, top_n: 1 });
    const region = await screen.findByRole("region", { name: "What your rules say today" });
    expect(within(region).getAllByRole("article")).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "Show 2 more" }));
    expect(within(region).getAllByRole("article")).toHaveLength(3);
  });

  it("says how many lower-layer cards a breach suppressed, never dropping them silently", async () => {
    mount(todayActions);
    expect(await screen.findByText(/1 lower-layer card is held back/)).toBeInTheDocument();
    expect(screen.getByText(/Rebalance due/)).toBeInTheDocument();
  });

  it("'I did this' posts once and does not reload Today", async () => {
    const fetchMock = vi.fn(async (url: string, _init?: RequestInit) =>
      url === "/api/today"
        ? json({ ...todayActions, cards: [shortfallCard, harvestCard] })
        : json({ status: "recorded", snapshot_id: "s".repeat(64), card_id: shortfallCard.card_id, decision: { decision: "done", decision_id: "d1", decided_at: "2026-10-16T04:00:00+00:00", cas_confirmed: null } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter>
        <Today />
      </MemoryRouter>,
    );
    const card = await screen.findByRole("article", { name: /Emergency reserve short/ });
    await userEvent.click(within(card).getByRole("button", { name: "I did this" }));
    await userEvent.click(within(card).getByRole("button", { name: "Yes, I did the steps on this card" }));
    await within(card).findByText(/You marked this done/);
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual(["/api/today", "/api/today/decisions"]);
  });

  it("has one h1, a labelled cards region and carries the 'rules you configured' note", async () => {
    mount(todayActions);
    await screen.findByRole("article", { name: /Emergency reserve short/ });
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Today");
    expect(screen.getByText(/Output of rules you configured/)).toBeInTheDocument();
  });

  it("uses no BUY/SELL words (U-11)", async () => {
    mount(todayActions);
    await screen.findByRole("article", { name: /Emergency reserve short/ });
    expect(document.body.textContent).not.toMatch(/\b(buy|sell)\b/i);
  });

  it("'Show N more' moves focus to the first revealed card instead of dropping it to <body> (a11y-architect-4)", async () => {
    mount({ ...todayActions, top_n: 1 });
    await screen.findByRole("region", { name: "What your rules say today" });
    await userEvent.click(screen.getByRole("button", { name: "Show 2 more" }));
    expect(document.activeElement).not.toBe(document.body);
    expect(screen.getByRole("heading", { level: 3, name: /Long-term gains allowance unused/ })).toHaveFocus();
  });

  it("after 'Yes, I did the steps on this card' focus stays in the card (a11y-architect-1)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url === "/api/today"
          ? json({ ...todayActions, cards: [shortfallCard, harvestCard] })
          : json({ status: "recorded", snapshot_id: "s".repeat(64), card_id: shortfallCard.card_id, decision: { decision: "done", decision_id: "d1", decided_at: "2026-10-16T04:00:00+00:00", cas_confirmed: null } }),
      ),
    );
    render(
      <MemoryRouter>
        <Today />
      </MemoryRouter>,
    );
    const card = await screen.findByRole("article", { name: /Emergency reserve short/ });
    await userEvent.click(within(card).getByRole("button", { name: "I did this" }));
    await userEvent.click(within(card).getByRole("button", { name: "Yes, I did the steps on this card" }));
    await within(card).findByText(/You marked this done/);
    expect(document.activeElement).not.toBe(document.body);
    expect(card.contains(document.activeElement)).toBe(true);
  });
});

describe("Today: getting a report in local mode, and stale data (silent-failure-hunter-03/05)", () => {
  function server(opts: { first: TodayResponse; after?: TodayResponse; post?: { status: number; body: unknown } }) {
    let computed = false;
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (url === "/api/today/snapshot" && method === "POST") {
        const p = opts.post ?? { status: 200, body: { snapshot_id: "s".repeat(64), as_of: "2026-10-14", verdict: "ACTIONS", created: true } };
        if (p.status < 300) computed = true;
        return json(p.body, p.status);
      }
      if (url === "/api/today") return json(computed && opts.after ? opts.after : opts.first);
      return json({ code: "NOT_FOUND" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter>
        <Today />
      </MemoryRouter>,
    );
    return fetchMock;
  }

  it("with no snapshot, the page offers to compute one via POST /api/today/snapshot, then shows the cards", async () => {
    const fetchMock = server({ first: todayNoSnapshot, after: todayActions });
    expect(await screen.findByRole("heading", { level: 2, name: "No snapshot yet" })).toBeInTheDocument();
    // The empty state names an action that actually produces a snapshot (not "run make run", which never does).
    expect(screen.queryByText(/make run/)).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1); // nothing is computed on page load
    const compute = screen.getByRole("button", { name: "Compute today's cards" });
    await userEvent.click(compute);
    await screen.findByRole("article", { name: /Emergency reserve short/ });
    const calls = fetchMock.mock.calls.map((c) => `${c[1]?.method ?? "GET"} ${c[0]}`);
    expect(calls).toEqual(["GET /api/today", "POST /api/today/snapshot", "GET /api/today"]);
    expect(JSON.parse(String(fetchMock.mock.calls[1]![1]?.body))).toEqual({});
    expect(screen.getByRole("button", { name: "Compute today's cards" })).toHaveFocus();
    expect(screen.getByText(/Computed from data as of 14-Oct-2026/)).toBeInTheDocument();
  });

  it("a failed compute is reported with its code and no cards are invented", async () => {
    server({ first: todayNoSnapshot, post: { status: 422, body: { detail: { code: "AS_OF_IN_FUTURE", message: "x" } } } });
    await screen.findByRole("heading", { level: 2, name: "No snapshot yet" });
    await userEvent.click(screen.getByRole("button", { name: "Compute today's cards" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Not computed/);
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
  });

  it("an old 'No action needed' is flagged as out of date with its dates, never shown as today's result", async () => {
    server({ first: { ...todayNothing, as_of: "2026-09-01", computed_at: "2026-09-01T13:00:00+00:00" } });
    expect(await screen.findByRole("heading", { level: 2, name: "These cards may be out of date" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 2, name: "No action needed" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: /No action needed on data as of 01-Sep-2026/ })).toBeInTheDocument();
    expect(screen.queryByText(/on the latest data/)).not.toBeInTheDocument();
    expect(screen.getByText(/computed 01-Sep-2026 13:00 UTC from data as of 01-Sep-2026/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Compute today's cards" })).toBeInTheDocument();
  });

  it("a fresh snapshot shows its data date in the result and no stale warning", async () => {
    server({ first: todayNothing });
    expect(await screen.findByRole("heading", { level: 2, name: "No action needed" })).toBeInTheDocument();
    expect(screen.getByText(/on data as of 14-Oct-2026/)).toBeInTheDocument();
    expect(screen.queryByText(/may be out of date/)).not.toBeInTheDocument();
  });
});
