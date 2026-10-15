import { api, readLoginFragment, UNAUTHORIZED_EVENT } from "./api";

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
