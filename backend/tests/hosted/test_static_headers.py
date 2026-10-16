"""WP A04: the UI is served from Vercel's CDN (`public/`), not by the Python function (PLAN §4 rank 4).

Checks, all hermetic (no network, no deploy):
- the CDN header set in ``vercel.json`` EQUALS the set the hosted app sends today (security headers + HSTS), and both
  equal a pinned literal snapshot, so neither side can drift alone;
- hashed assets (``/assets/*``) get a one-year ``immutable`` cache; the HTML shell is always revalidated;
- the five daily cron jobs J1–J5 are declared, and ``/api/cron/*`` answers 404 while ``CRON_SECRET`` is empty;
- ``scripts/vercel-build.sh --publish-only`` copies the built UI into ``public/``.

NOT VERIFIED here (needs a real deploy): ``x-vercel-cache: HIT`` on a repeat request, and how Vercel merges a
``vercel.json`` header with the same header sent by the function.
"""

from __future__ import annotations

import json
import os
import re
import runpy
import secrets
import subprocess
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

import iip.api.app as app_module
from iip.api.security import HSTS, SECURITY_HEADERS

ROOT = Path(__file__).resolve().parents[3]
ORIGIN = "https://iip-static.example.test"
VERCEL_HOST = "iip-abc123-user.vercel.app"

# Today's set (2026-10-16), pinned literally: a change to security.py OR vercel.json must update this on purpose.
TODAY_SECURITY_HEADERS = {
    "content-security-policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
        "connect-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; "
        "object-src 'none'"
    ),
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "strict-transport-security": "max-age=63072000; includeSubDomains",
}
IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "public, max-age=0, must-revalidate"
JOBS = {  # design-risk-first §9.1: job -> UTC hour
    "navall": 1,
    "navall-continue": 2,
    "history": 3,
    "snapshot": 5,
    "watchdog": 13,
}


def vercel() -> dict[str, Any]:
    cfg: dict[str, Any] = json.loads((ROOT / "vercel.json").read_text())
    return cfg


def _source_regex(source: str) -> re.Pattern[str]:
    """Vercel `source` patterns used here are plain regex groups after the leading slash (path-to-regexp subset)."""
    return re.compile("^" + source + "$")


def cdn_headers(path: str) -> dict[str, str]:
    """The headers vercel.json attaches to `path` (later rules win, as on Vercel)."""
    out: dict[str, str] = {}
    for rule in vercel().get("headers", []):
        if _source_regex(rule["source"]).match(path):
            for h in rule["headers"]:
                out[h["key"].lower()] = h["value"]
    return out


def security_only(headers: dict[str, str]) -> dict[str, str]:
    names = {k.decode() for k, _ in (*SECURITY_HEADERS, HSTS)}
    return {k: v for k, v in headers.items() if k in names}


@pytest.fixture
def fake_dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><html><body>synthetic</body></html>")
    (dist / "assets" / "index-AbCd1234.js").write_text("console.log('synthetic')")
    monkeypatch.setattr(app_module, "frontend_dist", lambda: dist)
    return dist


def load_entrypoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cron_secret: str | None) -> Any:
    env = {
        "IIP_DEPLOY": "vercel", "IIP_ENV": "test", "IIP_PUBLIC_ORIGIN": ORIGIN,
        "IIP_DB_URL": str(tmp_path / "hosted.db"), "IIP_ACCESS_TOKEN": secrets.token_urlsafe(32), "IIP_LLM": "off",
    }  # fmt: skip
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    for k in ("IIP_DB_AUTH_TOKEN", "TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    if cron_secret is None:
        monkeypatch.delenv("CRON_SECRET", raising=False)
    else:
        monkeypatch.setenv("CRON_SECRET", cron_secret)
    return runpy.run_path(str(ROOT / "app.py"))["app"]


# --- header equality ---------------------------------------------------------------------------------------------


def test_pinned_snapshot_matches_security_module() -> None:
    from_module = {k.decode(): v.decode() for k, v in (*SECURITY_HEADERS, HSTS)}
    assert from_module == TODAY_SECURITY_HEADERS


@pytest.mark.parametrize("path", ["/", "/index.html", "/assets/index-AbCd1234.js", "/holdings", "/favicon.svg"])
def test_cdn_security_headers_equal_todays_set(path: str) -> None:
    assert security_only(cdn_headers(path)) == TODAY_SECURITY_HEADERS


def test_cdn_headers_equal_what_the_hosted_app_sends(
    fake_dist: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = load_entrypoint(tmp_path, monkeypatch, cron_secret=None)
    with TestClient(app, base_url=ORIGIN) as c:
        for path in ("/", "/assets/index-AbCd1234.js"):
            r = c.get(path)
            assert r.status_code == 200
            served = security_only({k.lower(): v for k, v in r.headers.items()})
            assert served == security_only(cdn_headers(path)) == TODAY_SECURITY_HEADERS


def test_api_paths_get_no_cdn_headers() -> None:
    """The function already sends the security headers and `no-store` on /api; the CDN must not add or override."""
    for path in ("/api/health", "/api/cron/navall", "/api/holdings"):
        assert cdn_headers(path) == {}


# --- caching ----------------------------------------------------------------------------------------------------


def test_hashed_assets_are_immutable() -> None:
    assert cdn_headers("/assets/index-AbCd1234.js")["cache-control"] == IMMUTABLE
    assert cdn_headers("/assets/index-Zz9y8x7w.css")["cache-control"] == IMMUTABLE


@pytest.mark.parametrize("path", ["/", "/index.html", "/holdings"])
def test_html_shell_is_revalidated(path: str) -> None:
    assert cdn_headers(path)["cache-control"] == REVALIDATE


def test_vite_emits_hashed_assets_under_assets_dir() -> None:
    """`immutable` is safe only because every file under /assets/ carries a content hash (Vite's default)."""
    cfg = (ROOT / "frontend" / "vite.config.ts").read_text()
    assert "assetsDir" not in cfg and "entryFileNames" not in cfg and "assetFileNames" not in cfg
    assert not (ROOT / "frontend" / "public").exists(), "unhashed files would be copied to the asset root"


def test_ui_routes_rewrite_to_the_static_shell() -> None:
    rewrites = vercel().get("rewrites", [])
    assert rewrites == [{"source": "/((?!api/).*)", "destination": "/index.html"}]
    rx = _source_regex(rewrites[0]["source"])
    assert rx.match("/holdings") and rx.match("/")
    assert not rx.match("/api/health") and not rx.match("/api/cron/navall")


def test_function_bundle_excludes_public_and_keeps_tests_out() -> None:
    fn = vercel()["functions"]["app.py"]
    assert "public/**" in fn["excludeFiles"]
    assert "backend/tests/**" in fn["excludeFiles"]
    assert 0 < fn["maxDuration"] <= 300


# --- crons (ship disabled) --------------------------------------------------------------------------------------


def test_crons_j1_to_j5_declared_daily() -> None:
    crons = vercel()["crons"]
    assert {c["path"]: c["schedule"] for c in crons} == {f"/api/cron/{j}": f"0 {h} * * *" for j, h in JOBS.items()}
    assert len(crons) == 5  # Vercel Hobby: daily jobs only; each schedule fires once a day


@pytest.mark.parametrize("secret", [None, "", "   "])
@pytest.mark.parametrize("host", [None, VERCEL_HOST])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_cron_route_is_404_while_secret_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, secret: str | None, host: str | None, method: str
) -> None:
    app = load_entrypoint(tmp_path, monkeypatch, cron_secret=secret)
    headers = {"host": host} if host else {}
    with TestClient(app, base_url=ORIGIN) as c:
        for job in (*JOBS, "unknown", ""):
            r = c.request(method, f"/api/cron/{job}", headers={**headers, "Authorization": "Bearer " + "x" * 40})
            assert r.status_code == 404, (job, r.status_code)
            assert r.json() == {"code": "NOT_FOUND"}
            assert r.headers["cache-control"] == "no-store"
            assert security_only({k.lower(): v for k, v in r.headers.items()}) == TODAY_SECURITY_HEADERS
        assert c.get("/api/cron", headers=headers).status_code == 404


def test_cron_gate_leaves_other_routes_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = load_entrypoint(tmp_path, monkeypatch, cron_secret=None)
    with TestClient(app, base_url=ORIGIN) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/health", headers={"host": VERCEL_HOST}).status_code == 400
        assert c.get("/api/cronjobs").status_code == 401  # prefix match is on the path segment only


def test_cron_gate_opens_when_secret_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With a secret, the request reaches the app's own checks (the route itself is WP B03).

    The app's cron exception (A03, security.cron_auth_from_env) is on only for a production deployment with a
    deployment host, so the test sets VERCEL_ENV and VERCEL_URL as Vercel does in production."""
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("VERCEL_URL", VERCEL_HOST)
    app = load_entrypoint(tmp_path, monkeypatch, cron_secret=secrets.token_urlsafe(32))
    with TestClient(app, base_url=ORIGIN) as c:
        r = c.get("/api/cron/navall")
        assert r.status_code != 404
        assert r.status_code == 401  # no bearer: refused by the app's cron check, not hidden by the outer gate


# --- build wiring -----------------------------------------------------------------------------------------------


def test_build_script_publishes_dist_to_public(tmp_path: Path) -> None:
    dist = tmp_path / "frontend" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>synthetic</html>")
    (dist / "assets" / "index-AbCd1234.js").write_text("x")
    stale = tmp_path / "public" / "stale.txt"
    stale.parent.mkdir()
    stale.write_text("old")
    env = {**os.environ, "IIP_BUILD_ROOT": str(tmp_path)}
    res = subprocess.run(
        ["bash", str(ROOT / "scripts" / "vercel-build.sh"), "--publish-only"],
        env=env, capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert res.returncode == 0, res.stderr
    assert (tmp_path / "public" / "index.html").read_text() == "<html>synthetic</html>"
    assert (tmp_path / "public" / "assets" / "index-AbCd1234.js").exists()
    assert not stale.exists()


def test_build_script_fails_without_dist(tmp_path: Path) -> None:
    env = {**os.environ, "IIP_BUILD_ROOT": str(tmp_path)}
    res = subprocess.run(
        ["bash", str(ROOT / "scripts" / "vercel-build.sh"), "--publish-only"],
        env=env, capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert res.returncode != 0
    assert not (tmp_path / "public").exists()


def test_generated_public_is_never_committed_or_uploaded() -> None:
    assert "/public/" in (ROOT / ".gitignore").read_text().splitlines()
    assert "/public" in (ROOT / ".vercelignore").read_text().splitlines()
