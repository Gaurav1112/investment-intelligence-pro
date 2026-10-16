import { addDecimals, compareDecimals, dateLabel, fractionToPercent, groupIndian, inr, inrCompact, pct, percentToFraction, roundHalfUp, sumDecimals, utcStamp } from "./format";

describe("roundHalfUp (string arithmetic, mirrors backend money())", () => {
  it.each([
    ["2.345", 2, "2.35"],
    ["2.355", 2, "2.36"],
    ["10.005", 2, "10.01"],
    ["-2.345", 2, "-2.35"],
    ["0.125", 2, "0.13"],
    ["9.995", 2, "10.00"],
    ["999999.999", 2, "1000000.00"],
    ["-0.001", 2, "0.00"],
    ["1234", 0, "1234"],
  ])("%s → %s dp=%s", (v, dp, out) => expect(roundHalfUp(v, dp as number)).toBe(out));
});

describe("Indian grouping at lakh/crore boundaries", () => {
  it.each([
    ["999", "999"],
    ["99999", "99,999"],
    ["100000", "1,00,000"],
    ["9999999", "99,99,999"],
    ["10000000", "1,00,00,000"],
    ["1000000000000", "10,00,00,00,00,000"],
  ])("%s → %s", (v, out) => expect(groupIndian(v)).toBe(out));
});

describe("inr", () => {
  it("formats exact rupees with paise", () => {
    expect(inr("123456789.005")).toBe("₹12,34,56,789.01");
    expect(inr("-150000.5")).toBe("−₹1,50,000.50");
    expect(inr("0")).toBe("₹0.00");
    expect(inr("100534", { paise: false })).toBe("₹1,00,534");
  });
  it("rejects non-decimal input rather than guessing", () => {
    expect(() => inr("NaN")).toThrow();
    expect(() => inr("1e5")).toThrow();
    expect(() => inr("")).toThrow();
  });
  it("matches the backend format_inr fixtures", () => {
    // backend/tests/unit/test_money.py::test_indian_grouping_boundaries (minus sign differs by design: U+2212 in UI)
    expect(inr("9999999")).toBe("₹99,99,999.00");
    expect(inr("10000000")).toBe("₹1,00,00,000.00");
  });
});

describe("inrCompact", () => {
  it.each([
    ["99999", "₹99,999.00"],
    ["100000", "₹1.00 L"],
    ["1234567", "₹12.35 L"],
    ["12345678", "₹1.23 Cr"],
    ["9999999", "₹1.00 Cr"],
    ["9999499", "₹99.99 L"],
    ["-500000", "−₹5.00 L"],
  ])("%s → %s", (v, out) => expect(inrCompact(v)).toBe(out));
});

describe("pct", () => {
  it.each([
    ["0.0534", "+5.34 %"],
    ["-0.004", "−0.40 %"],
    ["0", "0.00 %"],
    ["0.00534", "+0.53 %"],
    ["0.12", "+12.00 %"],
    // Fewer than two fraction digits: the point moves past the last digit and must pad (was "5.00 %" for "0.5").
    ["0.5", "+50.00 %"],
    ["1", "+100.00 %"],
    ["-0.1", "−10.00 %"],
    ["2.5", "+250.00 %"],
  ])("%s → %s", (v, out) => expect(pct(v)).toBe(out));
});

describe("dates", () => {
  it("formats unambiguous dates and UTC stamps", () => {
    expect(dateLabel("2027-04-15")).toBe("15-Apr-2027");
    expect(utcStamp("2026-10-15T05:34:19Z")).toBe("15-Oct-2026 05:34 UTC");
    expect(() => dateLabel("15/04/2027")).toThrow();
  });
});

describe("percent ↔ fraction (exact)", () => {
  it.each([
    ["20", "0.2"],
    ["12.5", "0.125"],
    ["5", "0.05"],
    ["0.5", "0.005"],
    ["100", "1"],
    ["0", "0"],
    ["007.50", "0.075"],
  ])("%s %% → %s", (p, f) => expect(percentToFraction(p)).toBe(f));
  it("rejects garbage and keeps empty as null", () => {
    expect(percentToFraction("1e2")).toBe("invalid");
    expect(percentToFraction("-5")).toBe("invalid");
    expect(percentToFraction("  ")).toBeNull();
  });
  it.each([
    ["0.2", "20"],
    ["0.125", "12.5"],
    ["0.0001", "0.01"],
    ["1", "100"],
  ])("%s → %s %%", (f, p) => expect(fractionToPercent(f)).toBe(p));
  it("round-trips", () => {
    for (const p of ["0", "1", "12.5", "33.333", "250"]) expect(fractionToPercent(percentToFraction(p))).toBe(p);
  });
});

describe("exact decimal-string adder (no floats)", () => {
  it.each([
    ["0.1", "0.2", "0.3"],
    ["33.33", "33.34", "66.67"],
    ["0.10", "0.20", "0.3"],
    ["1", "0", "1"],
    ["0", "0", "0"],
    ["99.99", "0.01", "100"],
    ["12345678901234567890.5", "0.5", "12345678901234567891"],
    ["-1.5", "0.5", "-1"],
    ["-0.5", "0.5", "0"],
  ])("%s + %s = %s", (a, b, out) => expect(addDecimals(a, b)).toBe(out));

  it("sums allocation weights exactly", () => {
    expect(sumDecimals(["33.33", "33.33", "33.34"])).toBe("100");
    expect(sumDecimals(["33.33", "33.33", "33.33"])).toBe("99.99");
    expect(sumDecimals(["0.3333", "0.3333", "0.3334"])).toBe("1");
    expect(sumDecimals([])).toBe("0");
    // the float trap: 0.1 + 0.2 !== 0.3 in binary floating point
    expect(sumDecimals(["0.1", "0.2"])).toBe("0.3");
  });

  it("compares exactly, ignoring trailing zeros", () => {
    expect(compareDecimals("100", "100.00")).toBe(0);
    expect(compareDecimals("99.99", "100")).toBe(-1);
    expect(compareDecimals("100.0000001", "100")).toBe(1);
    expect(compareDecimals("-0.2", "0.1")).toBe(-1);
  });

  it("rejects non-decimal text", () => {
    expect(() => addDecimals("1e3", "1")).toThrow();
    expect(() => addDecimals("", "1")).toThrow();
    expect(() => compareDecimals("abc", "1")).toThrow();
  });
});
