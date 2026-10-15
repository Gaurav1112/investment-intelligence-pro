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

describe("errorText for a NAVAll fetch already running", () => {
  it("explains it in words", () => {
    const e = new ApiError(429, "NAVALL_IN_PROGRESS", { code: "NAVALL_IN_PROGRESS", retry_after_s: 30 });
    expect(errorText(e)).toBe("The AMFI latest-NAV fetch is already running. Try again in about 1 minute.");
  });
});

describe("errorText for a structured refusal", () => {
  it("shows the server's message and the codes it lists", () => {
    const detail = { code: "UNKNOWN_SCHEMES", unknown: [123456], message: "not stored schemes; run the AMFI NAV ingestion first" };
    const e = new ApiError(404, "REQUEST_FAILED", { detail });
    expect(errorText(e)).toBe("not stored schemes; run the AMFI NAV ingestion first (123456) (HTTP 404)");
  });
});
