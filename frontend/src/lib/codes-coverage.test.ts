import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { codeLabel } from "./codes";

// Every reason, flag or warning code the candidate/ranking/bond/input services can emit must have a plain-English
// label, so a new backend code cannot reach the screen as raw SNAKE_CASE unnoticed.
const FILES = ["engine/candidates.py", "engine/ranking.py", "services/bonds.py", "services/inputs.py"];

// Upper-case literals in those files that are NOT user-facing reasons: tax classes and a series convention id.
const NOT_USER_FACING = new Set(["MUTUAL_FUND", "RBI_TBILL_IMPLICIT_YIELD_AS_PUBLISHED"]);

function emittedCodes(src: string): string[] {
  const found = new Set<string>();
  // "CODE: detail" reason strings (plain or f-strings).
  for (const m of src.matchAll(/f?["']([A-Z][A-Z0-9_]{3,}): /g)) found.add(m[1]!);
  // Bare multi-word codes used as flags, warnings and error codes, e.g. "TAX_CLASS_UNKNOWN".
  for (const m of src.matchAll(/["']([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)["']/g)) found.add(m[1]!);
  return [...found].filter((c) => !NOT_USER_FACING.has(c)).sort();
}

describe("every user-facing backend code has a plain-English label", () => {
  for (const f of FILES) {
    it(`${f}`, () => {
      const src = readFileSync(resolve(__dirname, "../../../backend/src/iip", f), "utf8");
      const codes = emittedCodes(src);
      expect(codes.length).toBeGreaterThan(0);
      expect(codes.filter((c) => codeLabel(c) === null)).toEqual([]);
    });
  }

  it("labels avoid verdict words", () => {
    const all = FILES.flatMap((f) => emittedCodes(readFileSync(resolve(__dirname, "../../../backend/src/iip", f), "utf8")))
      .map((c) => codeLabel(c) ?? "")
      .join(" ")
      .toLowerCase();
    for (const w of ["best", "guaranteed", "risk-free", "you should", "recommend", "probability", "worst case"]) expect(all).not.toContain(w);
  });
});
