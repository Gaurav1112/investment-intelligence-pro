"""SEC-23 (real browser): instrument names containing HTML render as literal text — no element, no script, no CSP
violation. The names are entered through the real API (as an import or a manual entry would store them)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

import pytest

from tests.browser.conftest import App

pytestmark = pytest.mark.browser

PAYLOAD = "<img src=x onerror=alert(1)>"
FD_PAYLOAD = "<svg onload=alert(2)>Bank"

CSP_HOOK = """
window.__csp = [];
document.addEventListener("securitypolicyviolation", (e) =>
  window.__csp.push(e.violatedDirective + " " + e.blockedURI));
"""


def _create(app: App) -> tuple[str, str]:
    c, h = app.client()
    maturity = (date.today() + timedelta(days=180)).isoformat()
    tb = c.post("/api/instruments/tbill", headers=h, json={
        "name": PAYLOAD, "tenor": "182", "maturity": maturity, "yield_fraction": "0.065",
        "citation": {"url": "https://example.test/rbi", "as_of": date.today().isoformat()},
    })  # fmt: skip
    assert tb.status_code == 200, tb.text
    fd = c.post("/api/instruments/fd", headers=h, json={
        "institution": FD_PAYLOAD, "institution_type": "bank", "rate": "0.07", "tenure_days": 365,
        "citation": {"url": "https://example.test/bank", "as_of": date.today().isoformat()},
    })  # fmt: skip
    assert fd.status_code == 200, fd.text
    return tb.json()["instrument_id"], fd.json()["instrument_id"]


def test_sec23_html_in_names_renders_as_text(logged_in: Any, app: App) -> None:
    tbill_id, fd_id = _create(app)
    dialogs: list[str] = []
    console: list[str] = []
    page = logged_in.new_page()
    page.add_init_script(CSP_HOOK)
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    page.on("console", lambda m: console.append(f"{m.type}: {m.text}"))
    page.on("pageerror", lambda e: console.append(f"pageerror: {e}"))

    for path, tab, texts in [
        ("/fi", None, [PAYLOAD]),
        ("/fi", "Fixed deposits", [FD_PAYLOAD]),
        (f"/i/{quote(tbill_id, safe='')}", None, [PAYLOAD]),
        (f"/i/{quote(fd_id, safe='')}", None, [FD_PAYLOAD]),
    ]:
        page.goto(f"{app.origin}{path}")
        if tab is not None:
            page.get_by_text(tab, exact=True).first.click()
        for text in texts:
            page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=15000)
            assert page.get_by_text(text, exact=False).count() >= 1  # shown literally, characters intact
        page.wait_for_timeout(500)  # give any injected handler time to fire
        assert page.locator('img[src="x"]').count() == 0, path
        assert page.locator("svg[onload]").count() == 0, path
        assert page.evaluate("() => document.querySelectorAll('[onerror],[onload]').length") == 0, path
        assert page.evaluate("() => window.__csp") == [], path

    assert dialogs == []
    assert not [m for m in console if "Content Security Policy" in m or "Refused to" in m], console
    assert not [m for m in console if m.startswith(("error:", "pageerror:"))], console
