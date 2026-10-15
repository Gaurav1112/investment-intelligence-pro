import { codeLabel, humanise, splitCode } from "./codes";

describe("engine code labels", () => {
  it("splits CODE: detail strings and leaves free text alone", () => {
    expect(splitCode("EXIT_LOAD_UNKNOWN: enter the scheme's exit load")).toEqual({ code: "EXIT_LOAD_UNKNOWN", detail: "enter the scheme's exit load" });
    expect(splitCode("HORIZON_MISMATCH")).toEqual({ code: "HORIZON_MISMATCH", detail: "" });
    expect(splitCode("You excluded this instrument.")).toEqual({ code: null, detail: "You excluded this instrument." });
  });

  it("maps known codes to plain English and falls back to a readable form", () => {
    expect(codeLabel("INSUFFICIENT_LOSS_EVIDENCE")).toBe("Too little history to show a low loss rate");
    expect(codeLabel("EXIT_LOAD_UNKNOWN")).toBe("Exit load not entered yet");
    expect(codeLabel("TAX_RULES_ASSUMED_UNCHANGED_AFTER_FY2026")).toMatch(/legislated year/);
    expect(codeLabel("SOMETHING_NEW")).toBeNull();
    expect(humanise("SOMETHING_NEW")).toBe("Something new");
  });

  it("never uses banned verdict words", () => {
    const all = ["EXCLUDED_BY_USER", "HORIZON_MISMATCH", "LOWER_BAND_BELOW_FLOOR", "LOSS_FREQUENCY_ABOVE_LIMIT", "UNINSURED_CREDIT_EXPOSURE"]
      .map((c) => codeLabel(c) ?? "")
      .join(" ")
      .toLowerCase();
    for (const w of ["best", "guaranteed", "risk-free", "you should", "recommend", "probability", "worst case"]) expect(all).not.toContain(w);
  });
});
