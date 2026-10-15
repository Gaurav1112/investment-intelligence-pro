import { describe, expect, it } from "vitest";
import { ApiError } from "../lib/api";
import { errorText } from "./FixedIncome";

describe("errorText for rate-limit refusals", () => {
  it("explains a backfill already in progress", () => {
    const e = new ApiError(429, "BACKFILL_IN_PROGRESS", { code: "BACKFILL_IN_PROGRESS", retry_after_s: 60 });
    expect(errorText(e)).toBe("Another history backfill is still running. Try this one in about 1 minute.");
  });
  it("explains the per-scheme 15-minute limit in minutes", () => {
    const e = new ApiError(429, "RATE_LIMITED", { code: "RATE_LIMITED", retry_after_s: 601 });
    expect(errorText(e)).toBe("This was fetched recently; to be polite to the source, try again in about 11 minutes.");
  });
  it("falls back to 'later' without a wait", () => {
    expect(errorText(new ApiError(429, "RATE_LIMITED"))).toContain("try again later");
  });
});
