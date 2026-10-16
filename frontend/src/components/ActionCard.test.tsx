import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { clearApiCache } from "../lib/api";
import type { CardView } from "../lib/types-actions";
import { abstainCard, harvestCard, noActionCard, num, shortfallCard } from "../test/todayFixtures";
import { ActionCard, splitByNumbers } from "./ActionCard";

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
const SNAP = "s".repeat(64);

afterEach(() => {
  vi.unstubAllGlobals();
  clearApiCache();
});

function show(card: CardView, onExplain = vi.fn(), snapshotId: string | null = SNAP) {
  render(
    <MemoryRouter>
      <ActionCard card={card} snapshotId={snapshotId} onExplain={onExplain} />
    </MemoryRouter>,
  );
  return onExplain;
}

describe("splitByNumbers", () => {
  it("places every occurrence of a number's display, longest match first", () => {
    const a = num("a", "₹2", "f.x@1");
    const b = num("b", "₹22,222", "f.x@1");
    const parts = splitByNumbers("pay ₹22,222 then ₹2 and ₹22,222", [a, b]);
    expect(parts.map((p) => (typeof p === "string" ? p : `[${p.slot}]`))).toEqual([
      "pay ",
      "[b]",
      " then ",
      "[a]",
      " and ",
      "[b]",
    ]);
  });

  it("returns the text unchanged when no number appears", () => {
    expect(splitByNumbers("nothing here", [num("a", "₹9", "f.x@1")])).toEqual(["nothing here"]);
  });
});

describe("ActionCard", () => {
  it("labels the card by its kind and goal, with layer and status as text", () => {
    show(abstainCard);
    const card = screen.getByRole("article", { name: /Abstained · Synthetic goal/ });
    expect(within(card).getByText(/L3 · Loss limit/)).toBeInTheDocument();
    expect(within(card).getByText("REQUIRES CONFIGURATION")).toBeInTheDocument();
  });

  it("makes every number in the text a button that opens its explanation", async () => {
    const onExplain = show(shortfallCard);
    const card = screen.getByRole("article", { name: /Emergency reserve short/ });
    const text = within(card).getByTestId("card-text");
    const buttons = within(text).getAllByRole("button", { name: /shortfall: ₹1,11,111\. Press to explain\./ });
    expect(buttons).toHaveLength(2); // the number appears twice in the template text
    await userEvent.click(buttons[0]!);
    expect(onExplain).toHaveBeenCalledWith(expect.objectContaining({ formula_id: "risk.emergency_gate@1", display: "₹1,11,111" }));
  });

  it("lists every number with its formula, an Evidence link for stored facts and a Methodology link", () => {
    show(shortfallCard);
    const list = screen.getByRole("list", { name: "Numbers and sources" });
    expect(within(list).getAllByText(/risk\.emergency_gate@1/).length).toBeGreaterThan(0);
    expect(within(list).getByRole("link", { name: "Evidence #101" })).toHaveAttribute("href", "/evidence/101");
    expect(within(list).getAllByRole("link", { name: "Methodology" })[0]).toHaveAttribute("href", "/methodology");
  });

  it("shows steps with neutral verbs, instrument links and explainable step numbers", async () => {
    const onExplain = show(harvestCard);
    const steps = screen.getByRole("list", { name: "Steps" });
    expect(within(steps).getByText("Redeem")).toBeInTheDocument();
    expect(within(steps).getByRole("link", { name: "mf:synthetic-equity" })).toHaveAttribute("href", "/i/mf%3Asynthetic-equity");
    expect(within(steps).getByText(/folio SYN\/1/)).toBeInTheDocument();
    await userEvent.click(within(steps).getByRole("button", { name: /units: 12\.345 units/ }));
    expect(onExplain).toHaveBeenCalledWith(expect.objectContaining({ display: "12.345 units" }));
  });

  it("shows the rule, version and who set each parameter and when", () => {
    show(shortfallCard);
    expect(screen.getByRole("article").querySelector("summary")).toHaveTextContent("Why: Rule risk.emergency_gate@1");
    expect(screen.getByText(/emergency_months = 6 · set by you on 01-Oct-2026/)).toBeInTheDocument();
  });

  it("shows a deadline when the card has one", () => {
    show(harvestCard);
    expect(screen.getByText(/Deadline 31-Mar-2027/)).toBeInTheDocument();
  });

  it("ABSTAIN is a first-class card: it names the missing input and how to fix it, and has no 'I did this'", () => {
    show(abstainCard);
    const missing = screen.getByRole("list", { name: "Missing inputs" });
    expect(within(missing).getByText(/Loss limit/)).toBeInTheDocument();
    expect(within(missing).getByText(/Set a loss limit in ₹ on the Goals page\./)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "I did this" })).not.toBeInTheDocument();
  });

  it("NO_ACTION_NEEDED and BLOCKED cards have no 'I did this'", () => {
    show(noActionCard);
    expect(screen.queryByRole("button", { name: "I did this" })).not.toBeInTheDocument();
  });

  it("a BLOCKED action card has no 'I did this'", () => {
    show({ ...harvestCard, status: "BLOCKED", steps: [] });
    expect(screen.queryByRole("button", { name: "I did this" })).not.toBeInTheDocument();
  });

  it("'I did this' asks to confirm, then POSTs the card and snapshot once and shows the logged state", async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) =>
      json({ card_id: shortfallCard.card_id, decision: { decision_id: "dec-1", decided_at: "2026-10-16T04:00:00+00:00", cas_confirmed: null } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    show(shortfallCard);
    await userEvent.click(screen.getByRole("button", { name: "I did this" }));
    expect(fetchMock).not.toHaveBeenCalled();
    const confirm = screen.getByRole("button", { name: "Yes, I did the steps on this card" });
    expect(confirm).toHaveFocus();
    await userEvent.click(confirm);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/today/decisions");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ card_id: shortfallCard.card_id, snapshot_id: SNAP });
    expect(await screen.findByText(/You marked this done on 16-Oct-2026 04:00 UTC/)).toBeInTheDocument();
    expect(screen.getByText(/Not yet checked against a CAS/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "I did this" })).not.toBeInTheDocument();
  });

  it("cancelling the confirmation sends nothing and returns focus to the button", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    show(shortfallCard);
    await userEvent.click(screen.getByRole("button", { name: "I did this" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "I did this" })).toHaveFocus();
  });

  it("a failed POST is reported and nothing is shown as logged", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ code: "CSRF_INVALID" }, 403)));
    show(shortfallCard);
    await userEvent.click(screen.getByRole("button", { name: "I did this" }));
    await userEvent.click(screen.getByRole("button", { name: "Yes, I did the steps on this card" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/CSRF_INVALID/);
    expect(screen.queryByText(/You marked this done/)).not.toBeInTheDocument();
  });

  it("without a snapshot id there is nothing to log against, so no 'I did this'", () => {
    show(shortfallCard, vi.fn(), null);
    expect(screen.queryByRole("button", { name: "I did this" })).not.toBeInTheDocument();
  });

  it.each([
    [true, /A later CAS confirms it/],
    [false, /A later CAS does not show it/],
  ])("shows the CAS check result (cas_confirmed=%s)", (cas, text) => {
    show({ ...shortfallCard, decision: { decision_id: "d", decided_at: "2026-10-10T00:00:00+00:00", cas_confirmed: cas } });
    expect(screen.getByText(text)).toBeInTheDocument();
  });

  it("uses no BUY/SELL or forecast words of its own (U-11)", () => {
    for (const c of [shortfallCard, harvestCard, abstainCard, noActionCard]) {
      const { container, unmount } = render(
        <MemoryRouter>
          <ActionCard card={{ ...c, text: "" }} snapshotId={SNAP} onExplain={() => {}} />
        </MemoryRouter>,
      );
      expect(container.textContent).not.toMatch(/\b(buy|sell|forecast|expected return|guarantee)/i);
      unmount();
    }
  });
});
