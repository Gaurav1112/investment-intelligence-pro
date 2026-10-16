import { render, screen, within } from "@testing-library/react";
import { DETAIL_ACCEPTED, DETAIL_SE, gate, RULE_SE } from "../test/signalsFixtures";
import { conditionWords, earliestReviewText, GatePanel, isActionable, monthOf, reasonText } from "./GatePanel";

describe("GatePanel", () => {
  it("always lists G1–G14 and marks unreported gates as Not evaluated (fails closed)", () => {
    const { container } = render(<GatePanel gates={DETAIL_SE.gates} />);
    for (let i = 1; i <= 14; i++) expect(container.querySelector(`tr[data-gate="G${i}"]`)).not.toBeNull();
    expect(container.querySelector('tr[data-gate="G3"]')).toHaveAttribute("data-status", "missing");
    expect(within(container.querySelector('tr[data-gate="G3"]') as HTMLElement).getByText(/not reported by the engine; fails closed/)).toBeInTheDocument();
    // An extra gate reported by the backend (PBO) is appended.
    expect(container.querySelector('tr[data-gate="PBO"]')).toHaveAttribute("data-status", "abstain");
    expect(screen.getByText(/2 of 15 gates passed/)).toBeInTheDocument();
  });

  it("shows value against threshold and the reason code with its gloss", () => {
    const { container } = render(<GatePanel gates={DETAIL_SE.gates} />);
    const g5 = within(container.querySelector('tr[data-gate="G5"]') as HTMLElement);
    expect(g5.getByText("G5 Sample size")).toBeInTheDocument();
    expect(g5.getByText("(needs 30)")).toBeInTheDocument();
    expect(g5.getByText(/insufficient_evidence: not enough out-of-sample data yet \(has 0, needs 30\)/)).toBeInTheDocument();
    expect(g5.getByText("Abstain")).toBeInTheDocument();
    const g9 = within(container.querySelector('tr[data-gate="G9"]') as HTMLElement);
    expect(g9.getByText(/gate_not_implemented: this gate is not built yet, so it fails closed/)).toBeInTheDocument();
  });

  it("treats a row whose passed flag disagrees with its status as failed", () => {
    const { container } = render(<GatePanel gates={[{ ...gate("G1", "pass"), passed: false }]} />);
    expect(container.querySelector('tr[data-gate="G1"]')).toHaveAttribute("data-status", "fail");
    expect(screen.getByText(/0 of 14 gates passed/)).toBeInTheDocument();
  });

  it("uses a word next to every glyph (never colour or symbol alone)", () => {
    render(<GatePanel gates={DETAIL_ACCEPTED.gates} />);
    expect(screen.getAllByText("Pass")).toHaveLength(14);
    expect(screen.getAllByText("✓")[0]).toHaveAttribute("aria-hidden", "true");
  });
});

describe("signal display helpers", () => {
  it("formats the earliest possible review as YYYY-MM", () => {
    expect(monthOf("2037-04-01")).toBe("2037-04");
    expect(earliestReviewText("2037-04-01")).toBe("Earliest possible review: 2037-04");
    expect(earliestReviewText(null)).toBe("Earliest possible review: not computed (no backtest run yet)");
    expect(() => monthOf("April 2037")).toThrow();
  });

  it("shows unknown reason codes verbatim instead of guessing", () => {
    expect(reasonText("some_new_code")).toBe("some_new_code");
    expect(reasonText(null)).toBe("no reason code reported");
  });

  it("is actionable only for ACCEPTED rules with every gate G1–G14 passed", () => {
    expect(isActionable(RULE_SE)).toBe(false);
    expect(isActionable(DETAIL_ACCEPTED.rule, DETAIL_ACCEPTED.gates)).toBe(true);
    expect(isActionable(DETAIL_ACCEPTED.rule, DETAIL_ACCEPTED.gates.slice(1))).toBe(false); // G1 missing
    expect(isActionable(DETAIL_ACCEPTED.rule, [...DETAIL_ACCEPTED.gates, gate("SPA", "abstain", "gate_not_implemented")])).toBe(false);
    expect(isActionable({ state: "ACCEPTED", failing_gate: gate("G12", "fail", "decay") })).toBe(false);
  });

  it("uses neutral wording by default and a BUY/SELL badge only after the opt-in (U-11)", () => {
    expect(conditionWords(true, "entry", "neutral")).toEqual({ text: "Entry condition met", badge: null });
    expect(conditionWords(true, "exit", "neutral")).toEqual({ text: "Exit condition met", badge: null });
    expect(conditionWords(false, "exit", "neutral")).toEqual({ text: "No entry or exit condition met", badge: null });
    expect(conditionWords(true, "entry", "buy_sell")).toEqual({ text: "Entry condition met", badge: "BUY" });
    expect(conditionWords(true, "exit", "buy_sell")).toEqual({ text: "Exit condition met", badge: "SELL" });
    expect(conditionWords(null, null, "buy_sell")).toEqual({ text: "No entry or exit condition met", badge: null });
  });
});
