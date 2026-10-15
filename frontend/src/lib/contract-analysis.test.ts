import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { CompareRow, ForecastResponse, YieldCarryOk, YieldCarryRow } from "./types";

// TS-1: fields the backend sends must be typed here (and rendered), so a value cannot be silently dropped again.
const py = readFileSync(resolve(__dirname, "../../../backend/src/iip/services/analysis.py"), "utf8");

/** The string keys of the dict literal returned at the end of a Python function body. */
function returnedKeys(fn: string, marker: string): string[] {
  const start = py.indexOf(`def ${fn}(`);
  expect(start).toBeGreaterThan(-1);
  const body = py.slice(start, py.indexOf("\ndef ", start + 1));
  const at = body.lastIndexOf(marker);
  expect(at).toBeGreaterThan(-1);
  const indent = /^ */.exec(marker)![0]; // the dict closes at the indentation of its `return {`
  const block = body.slice(at, body.indexOf(`\n${indent}}`, at));
  const keyIndent = `${indent}    `;
  return [...block.matchAll(new RegExp(`^${keyIndent}"([a-z_]+)":`, "gm"))].map((m) => m[1]!);
}

// Compile-time: these objects must list exactly the keys of the TS types (an extra or missing key fails `tsc`).
const OK_KEYS: Record<keyof YieldCarryOk, true> = {
  status: true, label: true, model_id: true, factsheet_as_of: true, factsheet_freshness: true, carry: true,
  scenarios: true, stress_scenarios: true, context_amount: true,
}; // prettier-ignore
const ROW_KEYS: Record<keyof YieldCarryRow, true> = { delta_yield_bp: true, stress: true, return: true, value_inr: true };

describe("analysis.py ↔ types.ts contract (TS-1)", () => {
  it("YieldCarryOk has exactly the keys _yield_carry returns", () => {
    expect(returnedKeys("_yield_carry", "    return {\n        \"status\": \"OK\"").sort()).toEqual(Object.keys(OK_KEYS).sort());
  });

  it("YieldCarryRow has exactly the keys of each scenario row", () => {
    expect(returnedKeys("_yield_carry", "        return {\n            \"delta_yield_bp\"").sort()).toEqual(Object.keys(ROW_KEYS).sort());
  });

  it("compare rows carry real_return and forecasts carry yield_carry, and both are typed", () => {
    expect(py).toMatch(/"real_return": _real_returns\(/);
    expect(py).toMatch(/"yield_carry": carry,/);
    const row: Pick<CompareRow, "real_return"> = { real_return: undefined };
    const fc: Pick<ForecastResponse, "yield_carry"> = { yield_carry: undefined };
    expect(Object.keys(row)).toEqual(["real_return"]);
    expect(Object.keys(fc)).toEqual(["yield_carry"]);
  });
});
