import { dateLabel, groupIndian, inr, inrCompact, pct, roundHalfUp, utcStamp } from "./format";

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
  ])("%s → %s", (v, out) => expect(pct(v)).toBe(out));
});

describe("dates", () => {
  it("formats unambiguous dates and UTC stamps", () => {
    expect(dateLabel("2027-04-15")).toBe("15-Apr-2027");
    expect(utcStamp("2026-10-15T05:34:19Z")).toBe("15-Oct-2026 05:34 UTC");
    expect(() => dateLabel("15/04/2027")).toThrow();
  });
});
