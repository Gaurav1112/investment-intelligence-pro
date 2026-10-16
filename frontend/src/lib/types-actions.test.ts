import { snapshotIsStale } from "./types-actions";

// Mirrors backend engine/freshness.py nav_is_stale: stale when > 3 business days OR > 5 calendar days old.
describe("snapshotIsStale", () => {
  it.each([
    ["2026-10-14", "2026-10-15", false], // 1 weekday
    ["2026-10-09", "2026-10-12", false], // Fri → Mon: 1 weekday, 3 days
    ["2026-10-09", "2026-10-14", false], // Fri → Wed: 3 weekdays, 5 days
    ["2026-10-09", "2026-10-15", true], // Fri → Thu: 4 weekdays
    ["2026-10-10", "2026-10-16", true], // Sat → Fri: 5 weekdays, 6 days
    ["2026-09-01", "2026-10-16", true],
    ["2026-10-17", "2026-10-16", true], // a data date after today cannot be trusted
  ])("as_of %s, today %s → %s", (asOf, today, stale) => {
    expect(snapshotIsStale(asOf, today)).toBe(stale);
  });

  it("an unreadable date is treated as stale (fails closed)", () => {
    expect(snapshotIsStale("not-a-date", "2026-10-16")).toBe(true);
  });
});
