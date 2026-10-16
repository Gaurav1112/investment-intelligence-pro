import { api, apiUpload, errorCode, login, readLoginFragment, UNAUTHORIZED_EVENT } from "./api";

describe("session handling", () => {
  it("reads the login token from the fragment and removes it from the URL", () => {
    const replace = vi.fn();
    const loc = { hash: "#login=abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG", pathname: "/discover", search: "" } as Location;
    expect(readLoginFragment(loc, { replaceState: replace } as unknown as History)).toBe(
      "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG",
    );
    expect(replace).toHaveBeenCalledWith(null, "", "/discover");
  });

  it("ignores fragments without a plausible token", () => {
    const loc = { hash: "#login=short", pathname: "/", search: "" } as Location;
    expect(readLoginFragment(loc, { replaceState: vi.fn() } as unknown as History)).toBeNull();
  });

  it("broadcasts a lock event on 401 so stale data is never shown", async () => {
    const seen = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, seen);
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ code: "UNAUTHENTICATED" }), { status: 401 })));
    await expect(api("/api/me")).rejects.toMatchObject({ status: 401, code: "UNAUTHENTICATED" });
    expect(seen).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });
});

// API-1: routes_today / routes_signals / routes_settings (and goals) raise HTTPException(status, {code, message}),
// which FastAPI sends as {"detail": {"code", "message"}}. Other routes send a top-level {"code"}. Both must surface.
describe("error codes", () => {
  afterEach(() => vi.unstubAllGlobals());

  function respond(status: number, body: unknown): void {
    const text = typeof body === "string" ? body : JSON.stringify(body);
    vi.stubGlobal("fetch", vi.fn(async () => new Response(text, { status })));
  }

  it("reads a top-level code", async () => {
    respond(409, { code: "STALE_SNAPSHOT" });
    await expect(api("/api/x", { method: "POST", body: {} })).rejects.toMatchObject({ status: 409, code: "STALE_SNAPSHOT" });
  });

  it("reads detail.code from routes_today", async () => {
    respond(404, { detail: { code: "UNKNOWN_CARD", message: "no card c-1" } });
    await expect(api("/api/today/decisions", { method: "POST", body: {} })).rejects.toMatchObject({
      status: 404,
      code: "UNKNOWN_CARD",
      detail: { detail: { code: "UNKNOWN_CARD", message: "no card c-1" } },
    });
  });

  it("reads detail.code from routes_signals", async () => {
    respond(404, { detail: { code: "UNKNOWN_RULE", message: "no rule r-9" } });
    await expect(api("/api/signals/rules/r-9")).rejects.toMatchObject({ status: 404, code: "UNKNOWN_RULE" });
  });

  it("reads detail.code from routes_settings", async () => {
    respond(409, { detail: { code: "CHANNEL_UNAVAILABLE", message: "not configured" } });
    await expect(api("/api/settings/notify", { method: "PUT", body: {} })).rejects.toMatchObject({
      status: 409,
      code: "CHANNEL_UNAVAILABLE",
    });
  });

  it("prefers the top-level code when both are present", () => {
    expect(errorCode({ code: "TOP", detail: { code: "NESTED" } }, "REQUEST_FAILED")).toBe("TOP");
  });

  it("falls back when there is no usable code", async () => {
    // FastAPI request validation: detail is a list, not an object with a code.
    respond(422, { detail: [{ type: "missing", loc: ["body", "name"], msg: "Field required" }] });
    await expect(api("/api/goals", { method: "POST", body: {} })).rejects.toMatchObject({ status: 422, code: "REQUEST_FAILED" });
    respond(500, "<html>oops</html>");
    await expect(api("/api/x")).rejects.toMatchObject({ status: 500, code: "REQUEST_FAILED" });
    expect(errorCode({ code: 7, detail: { code: null } }, "FALLBACK")).toBe("FALLBACK");
    expect(errorCode({ detail: "plain text" }, "FALLBACK")).toBe("FALLBACK");
    expect(errorCode(null, "FALLBACK")).toBe("FALLBACK");
  });

  it("reads detail.code on uploads", async () => {
    respond(422, { detail: { code: "CAS_UNREADABLE", message: "bad pdf" } });
    await expect(apiUpload("/api/import/cas", new FormData())).rejects.toMatchObject({ status: 422, code: "CAS_UNREADABLE" });
  });

  it("reads detail.code on login", async () => {
    respond(401, { detail: { code: "BAD_TOKEN", message: "no" } });
    await expect(login("t")).rejects.toMatchObject({ status: 401, code: "BAD_TOKEN" });
  });
});
