"""SEC-16 (real browser): a page on a second local origin, opened while the user is logged in, cannot change state.

The attacker page runs on another port of 127.0.0.1 (same SITE, so the SameSite=Strict session cookie IS attached:
only the CSRF header + Origin/Sec-Fetch-Site + content-type checks and the absence of CORS stand in the way) and on
localhost (a different site). It tries credentialed fetches (JSON with preflight, a no-cors "simple" POST, a read of
private data) and an auto-submitting HTML form POST. Every attempt must fail and the store must be unchanged.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.browser.conftest import App, Attacker

pytestmark = pytest.mark.browser

TBILL = {
    "name": "CSRF-PLANTED T-bill", "tenor": "182", "maturity": "2027-04-15", "yield_fraction": "0.065",
    "citation": {"url": "https://attacker.test/x", "as_of": "2026-10-14"},
}  # fmt: skip

FETCH_PAGE = """<!doctype html><title>innocent</title><script>
const A = "%(target)s";
const body = %(body)s;
window.results = {};
async function attempt(name, fn) {
  try { const r = await fn(); window.results[name] = {ok: true, type: r.type, status: r.status}; }
  catch (e) { window.results[name] = {ok: false, error: String(e)}; }
}
(async () => {
  await attempt("json_post_with_preflight", () => fetch(A + "/api/instruments/tbill", {method: "POST",
      credentials: "include", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)}));
  await attempt("forged_csrf_header", () => fetch(A + "/api/instruments/tbill", {method: "POST",
      credentials: "include", headers: {"Content-Type": "application/json", "X-IIP-CSRF": "guess"},
      body: JSON.stringify(body)}));
  await attempt("no_cors_simple_post", () => fetch(A + "/api/instruments/tbill", {method: "POST", mode: "no-cors",
      credentials: "include", headers: {"Content-Type": "text/plain"}, body: JSON.stringify(body)}));
  await attempt("no_cors_profile_delete", () => fetch(A + "/api/profile", {method: "POST", mode: "no-cors",
      credentials: "include", body: "{}"}));
  await attempt("read_private_profile", async () => { const r = await fetch(A + "/api/profile",
      {credentials: "include"}); window.results.leaked = await r.text(); return r; });
  window.done = true;
})();
</script>"""

FORM_PAGE = """<!doctype html><title>innocent</title>
<form id="f" method="POST" action="%(target)s/api/instruments/tbill" enctype="text/plain">
<input name='%(name)s' value='%(value)s'></form>
<script>document.getElementById("f").submit();</script>"""


def _state(app: App) -> dict[str, Any]:
    c, _ = app.client()
    return {"instruments": c.get("/api/instruments").json(), "profile": c.get("/api/profile").json()}


@pytest.mark.parametrize("attacker_host", ["127.0.0.1", "localhost"])
def test_sec16_cross_origin_fetches_are_blocked_and_change_nothing(
    logged_in: Any, app: App, attacker: Attacker, attacker_host: str
) -> None:
    before = _state(app)
    name = f"fetch-{attacker_host}.html"
    attacker.page(name, FETCH_PAGE % {"target": app.origin, "body": json.dumps(TBILL)})
    page = logged_in.new_page()
    # Chromium hides responses it blocks (CORS / CORP) from page-level events, so watch the raw network via CDP.
    cdp = logged_in.new_cdp_session(page)
    cdp.send("Network.enable")
    sent: dict[str, str] = {}
    status: dict[str, int] = {}
    cdp.on(
        "Network.requestWillBeSent",
        lambda e: sent.__setitem__(e["requestId"], e["request"]["method"] + " " + e["request"]["url"]),
    )
    cdp.on("Network.responseReceivedExtraInfo", lambda e: status.__setitem__(e["requestId"], e["statusCode"]))
    page.goto(attacker.url(attacker_host, name))
    page.wait_for_function("() => window.done === true", timeout=15000)
    page.wait_for_timeout(300)
    results = page.evaluate("() => window.results")
    seen = [(sent[k], status.get(k)) for k in sent]

    # CORS: no Access-Control-* headers, so the preflighted and readable requests fail in the browser.
    assert results["json_post_with_preflight"]["ok"] is False, results
    assert results["forged_csrf_header"]["ok"] is False, results
    assert results["read_private_profile"]["ok"] is False, results
    assert "leaked" not in results
    # A no-cors "simple" request IS sent (no preflight). The page can learn nothing from it (Chromium even blocks the
    # opaque response: Cross-Origin-Resource-Policy: same-origin), and the server must have rejected it.
    for k in ("no_cors_simple_post", "no_cors_profile_delete"):
        assert results[k]["ok"] is False or results[k].get("type") == "opaque", results
    print("SEC-16 observed responses:", seen)
    # None = never sent (its preflight was refused: OPTIONS → 405, no CORS). 403 = CSRF/Origin check (same-site page,
    # cookie attached). 401 = no session (cross-site page: the SameSite=Strict cookie is withheld).
    mutations = [(u, s) for u, s in seen if u.split(" ")[0] in {"POST", "PUT", "DELETE"} and "/api/" in u]
    delivered = [s for _, s in mutations if s is not None]
    assert delivered, seen  # the no-cors "simple" requests really reached the app ...
    assert all(s in {401, 403} for s in delivered), seen  # ... and every one was rejected
    assert all(s == 405 for u, s in seen if u.startswith("OPTIONS ")), seen
    assert _state(app) == before


def test_sec16_cross_origin_form_post_is_blocked_and_changes_nothing(
    logged_in: Any, app: App, attacker: Attacker
) -> None:
    """Classic CSRF: text/plain form crafted so the body parses as JSON (`{"name": … , "x": "=…"}`)."""
    before = _state(app)
    blob = json.dumps(TBILL)[:-1] + ', "pad": "'
    attacker.page("form.html", FORM_PAGE % {"target": app.origin, "name": blob.replace("'", "&#39;"), "value": '"}'})
    page = logged_in.new_page()
    with page.expect_response(lambda r: r.url.endswith("/api/instruments/tbill")) as info:
        page.goto(attacker.url("127.0.0.1", "form.html"))
    resp = info.value
    assert resp.status == 403
    assert resp.json()["code"] == "CSRF_REJECTED"
    assert _state(app) == before


def test_sec16_same_origin_ui_still_works(logged_in: Any, app: App) -> None:
    """Control: the real UI, same origin, with the session's CSRF token, can call the API (the test is not vacuous)."""
    page = logged_in.new_page()
    page.goto(f"{app.origin}/fi")
    status = page.evaluate(
        """async () => { const me = await (await fetch('/api/me')).json();
           const r = await fetch('/api/instruments?kind=tbill', {headers: {'X-IIP-CSRF': me.csrf}});
           return r.status; }"""
    )
    assert status == 200
