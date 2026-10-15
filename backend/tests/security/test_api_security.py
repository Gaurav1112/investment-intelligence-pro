"""Automated security tests mapped to docs/security/threat-model.md §7 (SEC-xx)."""

import os
import stat

import pytest
from starlette.testclient import TestClient

from iip.api.security import CSP
from iip.api.settings import Settings, StartupRefused, from_env, validate

from .conftest import ORIGIN


# SEC-01/02/03/04 — DNS rebinding: exact Host:port allowlist, health not exempt
@pytest.mark.parametrize(
    "host", ["evil.example:8741", "127.0.0.1:9999", "127.0.0.1.evil.example", "localhost", "127.0.0.1"]
)
def test_bad_host_rejected(authed: tuple[TestClient, str], host: str) -> None:
    client, _ = authed
    for path in ("/api/health", "/api/me"):
        r = client.get(path, headers={"Host": host})
        assert r.status_code == 400 and r.json() == {"code": "BAD_HOST"}


@pytest.mark.parametrize("host", ["127.0.0.1:8741", "localhost:8741", "[::1]:8741", "LOCALHOST:8741"])
def test_good_hosts_accepted(client: TestClient, host: str) -> None:
    assert client.get("/api/health", headers={"Host": host}).status_code == 200


# SEC-05 — no CORS, ever
def test_no_cors_headers_and_preflight_gets_nothing(authed: tuple[TestClient, str]) -> None:
    client, _ = authed
    r = client.get("/api/me", headers={"Origin": "https://evil.example"})
    assert not any(h.lower().startswith("access-control-") for h in r.headers)
    pre = client.options(
        "/api/echo", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}
    )
    assert not any(h.lower().startswith("access-control-") for h in pre.headers)


# SEC-06/07/08/09 — CSRF
def test_post_without_csrf_header_rejected(authed: tuple[TestClient, str]) -> None:
    client, _ = authed
    assert client.post("/api/echo", json={}, headers={"Origin": ORIGIN}).status_code == 403


def test_post_with_csrf_but_hostile_origin_rejected(authed: tuple[TestClient, str]) -> None:
    client, csrf = authed
    r = client.post("/api/echo", json={}, headers={"Origin": "https://evil.example", "X-IIP-CSRF": csrf})
    assert r.status_code == 403


def test_post_without_origin_cross_site_fetch_rejected(authed: tuple[TestClient, str]) -> None:
    client, csrf = authed
    r = client.post("/api/echo", json={}, headers={"Sec-Fetch-Site": "cross-site", "X-IIP-CSRF": csrf})
    assert r.status_code == 403


@pytest.mark.parametrize("ctype", ["application/x-www-form-urlencoded", "text/plain", "multipart/form-data"])
def test_simple_form_content_types_rejected(authed: tuple[TestClient, str], ctype: str) -> None:
    client, csrf = authed
    r = client.post("/api/echo", content=b"a=1", headers={"Origin": ORIGIN, "X-IIP-CSRF": csrf, "Content-Type": ctype})
    assert r.status_code == 403


def test_valid_post_accepted(authed: tuple[TestClient, str]) -> None:
    client, csrf = authed
    r = client.post("/api/echo", json={}, headers={"Origin": ORIGIN, "X-IIP-CSRF": csrf})
    assert r.status_code == 200


def test_wrong_csrf_value_rejected(authed: tuple[TestClient, str]) -> None:
    client, _ = authed
    r = client.post("/api/echo", json={}, headers={"Origin": ORIGIN, "X-IIP-CSRF": "x" * 43})
    assert r.status_code == 403


# SEC-11 — every non-public route requires a session (route list generated from the app)
def test_every_non_public_route_requires_session(client: TestClient) -> None:
    from iip.api.security import PUBLIC_ROUTES

    app = client.app.app  # type: ignore[attr-defined]
    checked = 0
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/") or "{" in path:
            continue
        for method in getattr(route, "methods", set()) - {"HEAD"}:
            if (method, path) in PUBLIC_ROUTES:
                continue
            r = client.request(method, path, headers={"Origin": ORIGIN})
            assert r.status_code == 401, (method, path, r.status_code)
            checked += 1
    assert checked >= 3


# SEC-12 — token compare + rate limit
def test_login_rate_limited_after_ten_failures(client: TestClient) -> None:
    codes = [
        client.post("/api/session", json={"token": "w" * 43}, headers={"Origin": ORIGIN}).status_code for _ in range(11)
    ]
    assert codes[:10] == [401] * 10 and codes[10] == 429


def test_login_requires_allowlisted_origin(client: TestClient, token: str) -> None:
    r = client.post("/api/session", json={"token": token}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_token_compared_in_constant_time() -> None:
    import inspect

    from iip.api import app as app_module

    assert "hmac.compare_digest" in inspect.getsource(app_module)


# SEC-13 — cookie attributes
def test_session_cookie_attributes(client: TestClient, token: str) -> None:
    r = client.post("/api/session", json={"token": token}, headers={"Origin": ORIGIN})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie and "domain" not in cookie


# SEC-14/15 — startup refusals
def test_refuses_non_loopback_bind() -> None:
    with pytest.raises(StartupRefused):
        from_env({"IIP_HOST": "0.0.0.0"})


def test_refuses_auth_off_outside_test() -> None:
    with pytest.raises(StartupRefused):
        from_env({"IIP_AUTH": "off", "IIP_ENV": "prod"})
    assert validate(Settings(env="test", auth=False)).auth is False


def test_refuses_dev_origins_outside_dev() -> None:
    with pytest.raises(StartupRefused):
        from_env({"IIP_DEV_ORIGINS": "http://localhost:5173"})


# SEC-20 — headers
def test_security_headers_and_csp(authed: tuple[TestClient, str]) -> None:
    client, _ = authed
    r = client.get("/api/me")
    assert r.headers["content-security-policy"] == CSP
    assert "unsafe-inline" not in CSP and "unsafe-eval" not in CSP
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"
    assert "server" not in {h.lower() for h in r.headers}


# SEC-21 — generic errors
def test_internal_errors_leak_nothing(authed: tuple[TestClient, str]) -> None:
    client, _ = authed
    r = client.get("/api/boom")
    assert r.status_code == 500
    body = r.json()
    assert set(body) == {"code", "request_id"}
    assert "SELECT" not in r.text and "/Users" not in r.text


# SEC-22 — no docs in prod
def test_no_openapi_in_prod(authed: tuple[TestClient, str]) -> None:
    client, _ = authed
    assert client.get("/api/openapi.json").status_code == 404
    assert client.get("/api/docs").status_code == 404


# SEC-30 — body cap before parsing
def test_oversized_body_rejected(authed: tuple[TestClient, str]) -> None:
    client, csrf = authed
    big = b"{" + b" " * (5 * 1024 * 1024) + b"}"
    r = client.post(
        "/api/echo", content=big, headers={"Origin": ORIGIN, "X-IIP-CSRF": csrf, "Content-Type": "application/json"}
    )
    assert r.status_code == 413


# C-02 — token file permissions
def test_token_file_is_private(settings: Settings, client: TestClient) -> None:
    mode = stat.S_IMODE(os.stat(settings.token_path).st_mode)
    assert mode == 0o600
    assert len(settings.token_path.read_text().strip()) >= 43  # 256-bit urlsafe
