"""Threat-model tests that were planned but not yet automated (SEC-10, 54, 57, 60, 61, 63, 64, 65, 82, 86)."""

import os
import re
import sqlite3
import stat
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from starlette.testclient import TestClient

from iip.api.settings import Settings

from .conftest import ORIGIN

SRC = Path(__file__).resolve().parents[2] / "src" / "iip"


def test_sec10_get_routes_never_write(authed: tuple[TestClient, str], settings: Settings) -> None:
    """Every registered GET route runs with a SQLite authorizer that refuses INSERT/UPDATE/DELETE."""
    client, _ = authed
    app = client.app.app  # type: ignore[attr-defined]
    state = app.state.iip
    denied: list[str] = []
    current: list[str] = [""]

    def authorizer(action: int, arg1: object, *_: object) -> int:
        if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
            denied.append(f"{current[0]} -> action {action} on {arg1}")
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    original = type(state).conn
    try:
        type(state).conn = property(lambda s: _with_auth(original.fget(s), authorizer))  # type: ignore[assignment,union-attr]
        for route in app.routes:
            path = getattr(route, "path", "")
            if path.startswith("/api/") and "GET" in getattr(route, "methods", set()) and "{" not in path:
                current[0] = path
                client.get(path)
    finally:
        type(state).conn = original
    assert denied == [], f"GET routes attempted writes: {denied}"


def _with_auth(conn: sqlite3.Connection, fn: object) -> sqlite3.Connection:
    conn.set_authorizer(fn)  # type: ignore[arg-type]
    return conn


def test_sec54_no_api_input_fetches_a_user_supplied_url(authed: tuple[TestClient, str]) -> None:
    """URL fields on input models are citations that are STORED, never fetched; new ones must be allowlisted here."""
    client, _ = authed
    allowed = {"Citation"}
    spec = client.app.app.openapi()  # type: ignore[attr-defined]
    offenders = []
    for name, schema in spec.get("components", {}).get("schemas", {}).items():
        for field, prop in schema.get("properties", {}).items():
            if (field in {"url", "uri", "href"} or prop.get("format") in {"uri", "url"}) and name not in allowed:
                offenders.append(f"{name}.{field}")
    assert offenders == []
    fetch_src = (SRC / "data" / "fetch.py").read_text()
    assert "def fetch(self, request: SourceRequest" in fetch_src  # typed request only, never a bare URL


def test_sec57_tls_verification_never_disabled() -> None:
    for p in SRC.rglob("*.py"):
        assert "verify=False" not in p.read_text(), p


def test_sec65_no_dangerous_calls() -> None:
    patterns = [r"\bpickle\b", r"yaml\.load\(", r"\beval\(", r"shell=True", r"execute\(f\""]
    for p in SRC.rglob("*.py"):
        text = p.read_text()
        for pat in patterns:
            assert not re.search(pat, text), f"{p}: {pat}"


@pytest.mark.parametrize("q", ["name; DROP TABLE holdings--", "1 OR 1=1", "%' OR '1'='1", "\x00"])
def test_sec60_search_params_are_inert(authed: tuple[TestClient, str], q: str) -> None:
    client, _ = authed
    r = client.get("/api/instruments", params={"q": q, "kind": q})
    assert r.status_code in (200, 422)
    assert client.get("/api/instruments").status_code == 200  # tables intact


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(junk=st.dictionaries(st.text(min_size=1, max_size=20), st.one_of(st.text(max_size=2000), st.integers()),
                            max_size=6))  # fmt: skip
def test_sec61_fuzzed_bodies_never_500(authed: tuple[TestClient, str], junk: dict[str, object]) -> None:
    client, csrf = authed
    h = {"Origin": ORIGIN, "X-IIP-CSRF": csrf}
    for path in ("/api/profile", "/api/instruments/tbill", "/api/instruments/fd", "/api/compare", "/api/simulate",
                 "/api/feasibility", "/api/scenario", "/api/portfolios"):  # fmt: skip
        method = "PUT" if path == "/api/profile" else "POST"
        r = client.request(method, path, json=junk, headers=h)
        assert r.status_code < 500, (path, junk, r.status_code)


def test_sec63_64_no_secrets_or_paths_in_status_errors_or_repr(
    authed: tuple[TestClient, str], settings: Settings
) -> None:
    client, _ = authed
    token = settings.token_path.read_text().strip()
    home = str(Path.home())
    for path in ("/api/ready", "/api/health", "/api/me", "/api/nonexistent"):
        body = client.get(path).text
        assert token not in body and home not in body
    assert token not in repr(settings) and str(settings.data_dir) not in repr(settings)


def test_sec82_data_dir_and_files_are_private(authed: tuple[TestClient, str], settings: Settings) -> None:
    mode = lambda p: stat.S_IMODE(os.stat(p).st_mode)  # noqa: E731
    assert mode(settings.data_dir) == 0o700
    assert mode(settings.db_path) == 0o600
    assert mode(settings.token_path) == 0o600


def test_sec86_manual_source_refresh_is_rate_limited(
    authed: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from iip.services import ingestion

    calls: list[int] = []
    monkeypatch.setattr(ingestion, "ingest_navall", lambda *a, **k: calls.append(1) or ingestion.RunSummary(
        "run_x", "amfi.navall", "ok", 0, 0, 0, "stub"))  # fmt: skip
    client, csrf = authed
    h = {"Origin": ORIGIN, "X-IIP-CSRF": csrf}
    assert client.post("/api/ingestion/amfi-navall", json={}, headers=h).status_code == 200
    second = client.post("/api/ingestion/amfi-navall", json={}, headers=h)
    assert second.status_code == 429 and "retry-after" in {k.lower() for k in second.headers}
    assert calls == [1]  # no outbound request on the refused call
