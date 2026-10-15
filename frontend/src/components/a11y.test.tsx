import { render, screen } from "@testing-library/react";
import { DotPlot } from "../charts/DotPlot";
import type { Explained, Freshness } from "../lib/types";
import { ExplainedNumber } from "./ExplainDrawer";

const item = (freshness: Freshness): Explained => ({
  id: "x.nav",
  label: "Market value",
  display: "₹1,23,456.00",
  value: "123456.00",
  unit: "INR",
  what: "Units × NAV",
  formula_id: "VAL@1",
  formula: "units × NAV",
  substituted: null,
  inputs: [],
  sources: [],
  observed: "2026-10-01",
  freshness,
  assumptions: [],
  sensitivity: [],
  limitations: [],
  engine_version: "test",
  hash: "0".repeat(64),
});

describe("ExplainedNumber accessible name (A11Y-5)", () => {
  it("announces STALE: the strike-through is not the only signal", () => {
    render(<ExplainedNumber item={item("STALE")} onExplain={() => {}} />);
    expect(screen.getByRole("button")).toHaveAccessibleName("Market value: ₹1,23,456.00 (STALE). Press to explain.");
  });

  it.each([
    ["UNKNOWN", "FRESHNESS UNKNOWN"],
    ["FIXTURE", "FIXTURE — not market data"],
    ["ILLUSTRATIVE", "ILLUSTRATIVE"],
  ] as const)("announces %s", (f, word) => {
    render(<ExplainedNumber item={item(f)} onExplain={() => {}} />);
    expect(screen.getByRole("button")).toHaveAccessibleName(`Market value: ₹1,23,456.00 (${word}). Press to explain.`);
  });

  it("adds nothing for a current value", () => {
    render(<ExplainedNumber item={item("END_OF_DAY")} onExplain={() => {}} />);
    expect(screen.getByRole("button")).toHaveAccessibleName("Market value: ₹1,23,456.00. Press to explain.");
  });
});

describe("DotPlot keyboard and screen-reader behaviour (A11Y-4)", () => {
  const quantiles = Array.from({ length: 20 }, (_, i) => `0.0${i < 10 ? "0" : ""}${i}`);
  const displays = quantiles.map((_, i) => `${i}.00%`);

  it("has no focusable dots: one labelled image, plus the table as the accessible equivalent", () => {
    const { container } = render(<DotPlot label="Past 1-year windows" quantiles={quantiles} displays={displays} />);
    const img = screen.getByRole("img", { name: /Past 1-year windows\. 20 equally likely historical outcomes from 0\.00% to 19\.00%/ });
    expect(img).toBeInTheDocument();
    expect(container.querySelectorAll("circle.dot")).toHaveLength(20);
    expect(container.querySelectorAll("[tabindex]")).toHaveLength(0);
    expect(container.querySelectorAll("circle[aria-label]")).toHaveLength(0);
    // Every outcome is still reachable as text in the table.
    expect(screen.getAllByRole("row")).toHaveLength(21);
    expect(screen.getByRole("cell", { name: "19.00%" })).toBeInTheDocument();
  });
});
