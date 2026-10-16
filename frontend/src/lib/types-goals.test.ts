import { EMPTY_ANSWERS, fallLabel, rupeesTimesFraction, setupClearList, yearsToMonths } from "./types-goals";

describe("types-goals exact helpers (C02)", () => {
  it("fallLabel pads one-digit fractions (regression: format.pct shows 0.5 as 5.0 %)", () => {
    expect(fallLabel("0.5")).toBe("−50.0 %");
    expect(fallLabel("0.05")).toBe("−5.0 %");
    expect(fallLabel("0.1234")).toBe("−12.3 %");
    expect(fallLabel("1")).toBe("−100.0 %");
  });

  it("rupeesTimesFraction is exact and floors to whole rupees", () => {
    expect(rupeesTimesFraction("100000", "0.5")).toBe("50000");
    expect(rupeesTimesFraction("1000000", "0.333")).toBe("333000");
    expect(rupeesTimesFraction("999", "0.1")).toBe("99"); // 99.9 floored, never rounded up
    expect(rupeesTimesFraction("12345.67", "0.25")).toBe("3086");
    expect(() => rupeesTimesFraction("-1", "0.5")).toThrow();
    expect(() => rupeesTimesFraction("1e5", "0.5")).toThrow();
  });

  it("yearsToMonths floors exactly and passes null through", () => {
    expect(yearsToMonths("4.0")).toBe(48);
    expect(yearsToMonths("2.7")).toBe(32); // 32.4
    expect(yearsToMonths(null)).toBeNull();
    expect(yearsToMonths("n/a")).toBeNull();
  });
});

describe("setupClearList (FE-1, GOAL-2 clear list)", () => {
  const stored = {
    emergency: { essential_monthly_expenses: "40000", months: 6 },
    extras: { ltcg_used_inr: "1000", savings_balance: "200000", sweep_fd_balance: null },
  };

  it("names each stored answer the user emptied, and nothing else", () => {
    const sent = {
      emergency: { essential_monthly_expenses: null, months: 6 },
      extras: { ltcg_used_inr: null, savings_balance: null, sweep_fd_balance: null },
    };
    // LTCG is not clearable on the wire; sweep was never stored, so it is not named.
    expect(setupClearList(stored, sent)).toEqual(["emergency.essential_monthly_expenses", "extras.savings_balance"]);
  });

  it("an answer that is given (changed or not) is never also cleared", () => {
    const sent = {
      emergency: { essential_monthly_expenses: "45000", months: 3 },
      extras: { ltcg_used_inr: "1000", savings_balance: "200000", sweep_fd_balance: "5000" },
    };
    expect(setupClearList(stored, sent)).toEqual([]);
  });

  it("emptying the emergency months clears them", () => {
    const sent = { ...stored, emergency: { essential_monthly_expenses: "40000", months: null } };
    expect(setupClearList(stored, sent)).toEqual(["emergency.months"]);
  });

  it("with nothing stored, nothing is cleared", () => {
    expect(setupClearList(EMPTY_ANSWERS, EMPTY_ANSWERS)).toEqual([]);
  });
});
