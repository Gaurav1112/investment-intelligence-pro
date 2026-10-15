"""Hosted mode (ADR-0013): configuration refusals, HTTPS-only cookies and headers, exact host/origin, and sessions
and the login limiter shared through the database (serverless instances share no memory)."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import pytest

from iip.api.security import DbRateLimiter
from iip.api.settings import Settings, StartupRefused, from_env, validate
from iip.llm.config import LLMConfig
from iip.store.db import connect_libsql, migrate

from .conftest import NOW, ORIGIN, TOKEN, hosted_settings, login, make_client, state


def test_local_defaults_are_unchanged() -> None:
    s = from_env({})
    assert s.deploy == "local" and not s.hosted
    assert s.allowed_hosts == frozenset({"127.0.0.1:8741", "localhost:8741", "[::1]:8741"})


def test_valid_hosted_configuration_is_accepted(db: Path) -> None:
    s = validate(hosted_settings(db))
    assert s.hosted and s.allowed_hosts == frozenset({"iip.example.test"}) and s.allowed_origins == {ORIGIN}
    remote = validate(hosted_settings(db, env="prod", db_url="libsql://x-y.turso.io", db_auth_token="t"))
    assert remote.db_url.startswith("libsql://")
    assert TOKEN not in repr(remote) and "db_auth_token" not in repr(remote)  # secrets never in repr/logs


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"public_origin": "http://iip.example.test"}, "https origin"),
        ({"public_origin": "https://iip.example.test/app"}, "https origin"),
        ({"public_origin": "https://iip.example.test/"}, "https origin"),
        ({"public_origin": "https://u:p@iip.example.test"}, "https origin"),
        ({"access_token": "x" * 31}, "at least 32"),
        ({"env": "dev"}, "IIP_ENV=prod"),
        ({"auth": False}, "requires the access token"),
        ({"env": "prod"}, "libsql:// or https://"),  # a local file is a test-only stand-in
        ({"env": "prod", "db_url": "libsql://x.turso.io"}, "IIP_DB_AUTH_TOKEN"),
        ({"db_url": "http://x.turso.io"}, "libsql:// or https://"),
        ({"llm": LLMConfig(mode="local", base_url="http://127.0.0.1:11434/v1", model="m")}, "IIP_LLM=local"),
        ({"deploy": "heroku"}, "IIP_DEPLOY"),
    ],
)
def test_weak_hosted_configuration_refuses_startup(db: Path, overrides: dict[str, object], fragment: str) -> None:
    with pytest.raises(StartupRefused, match=fragment):
        validate(hosted_settings(db, **overrides))


def test_from_env_reads_the_hosted_variables(tmp_path: Path) -> None:
    s = from_env({
        "IIP_DEPLOY": "vercel", "IIP_ENV": "prod", "IIP_PUBLIC_ORIGIN": ORIGIN, "IIP_DB_URL": "libsql://a.turso.io",
        "IIP_DB_AUTH_TOKEN": "secret-db-token", "IIP_ACCESS_TOKEN": TOKEN,
    })  # fmt: skip
    assert s.hosted and s.db_auth_token == "secret-db-token" and s.access_token == TOKEN
    assert isinstance(s, Settings)


def test_from_env_accepts_the_turso_integration_names() -> None:
    """Vercel's Turso integration injects TURSO_DATABASE_URL / TURSO_AUTH_TOKEN as sensitive values that cannot be
    copied; IIP_DB_* still wins when both are set."""
    base = {"IIP_DEPLOY": "vercel", "IIP_ENV": "prod", "IIP_PUBLIC_ORIGIN": ORIGIN, "IIP_ACCESS_TOKEN": TOKEN}
    s = from_env({**base, "TURSO_DATABASE_URL": "libsql://x.turso.io", "TURSO_AUTH_TOKEN": "turso-token"})
    assert s.db_url == "libsql://x.turso.io" and s.db_auth_token == "turso-token"
    s = from_env({**base, "TURSO_DATABASE_URL": "libsql://x.turso.io", "TURSO_AUTH_TOKEN": "turso-token",
                  "IIP_DB_URL": "libsql://a.turso.io", "IIP_DB_AUTH_TOKEN": "iip-token"})  # fmt: skip
    assert s.db_url == "libsql://a.turso.io" and s.db_auth_token == "iip-token"


def test_login_sets_a_secure_strict_cookie_and_hsts(db: Path) -> None:
    with make_client(db) as c:
        r = c.post("/api/session", json={"token": TOKEN}, headers={"Origin": ORIGIN})
        cookie = r.headers["set-cookie"].lower()
        assert r.status_code == 200 and "secure" in cookie and "httponly" in cookie and "samesite=strict" in cookie
        assert r.headers["strict-transport-security"].startswith("max-age=")
        assert c.get("/api/me").json()["deploy"] == "vercel"
        denied = c.get("/api/me", cookies={})
        assert "strict-transport-security" in denied.headers  # on rejections too


@pytest.mark.parametrize("host", ["iip-abc123-user.vercel.app", "127.0.0.1:8741", "evil.example"])
def test_only_the_public_host_is_served(db: Path, host: str) -> None:
    with make_client(db) as c:
        assert c.get("/api/health", headers={"host": host}).status_code == 400


def test_a_foreign_origin_cannot_log_in_or_change_state(db: Path) -> None:
    with make_client(db) as c:
        bad = c.post("/api/session", json={"token": TOKEN}, headers={"Origin": "https://evil.example"})
        assert bad.status_code == 403
        h = login(c)
        r = c.post("/api/watchlist", json={"instrument_id": "mf:1"}, headers={**h, "Origin": "http://iip.example.test"})
        assert r.status_code == 403 and r.json()["code"] == "CSRF_REJECTED"


def test_sessions_live_in_the_database_and_work_across_instances(db: Path) -> None:
    """Two app instances = two serverless instances: a login on one is valid on the other; logout on either ends it."""
    with make_client(db) as a, make_client(db) as b:
        login(a)
        cookie = a.cookies.get("iip_session")
        assert cookie
        b.cookies.set("iip_session", cookie, domain="iip.example.test")
        assert b.get("/api/me").status_code == 200
        wal = db.with_name(db.name + "-wal")
        raw = db.read_bytes() + (wal.read_bytes() if wal.exists() else b"")
        assert cookie.encode() not in raw  # only the SHA-256 is stored, never the cookie value
        rows = [r["id_hash"] for r in state(a).conn.execute("SELECT id_hash FROM web_sessions")]
        assert rows == [hashlib.sha256(cookie.encode()).hexdigest()]
        b.delete("/api/session", headers={"Origin": ORIGIN, "X-IIP-CSRF": b.get("/api/me").json()["csrf"],
                                          "Content-Type": "application/json"})  # fmt: skip
        assert a.get("/api/me").status_code == 401


def test_expired_sessions_are_refused(db: Path) -> None:
    now = [NOW]
    with make_client(db, clock=lambda: now[0]) as c:
        login(c)
        assert c.get("/api/me").status_code == 200
        from datetime import timedelta

        now[0] = NOW + timedelta(hours=8, seconds=1)  # idle limit
        assert c.get("/api/me").status_code == 401


def test_login_limit_is_shared_between_instances(db: Path) -> None:
    with make_client(db) as a, make_client(db) as b:
        for _ in range(10):
            assert a.post("/api/session", json={"token": "w" * 40}, headers={"Origin": ORIGIN}).status_code == 401
        r = b.post("/api/session", json={"token": TOKEN}, headers={"Origin": ORIGIN})
        assert r.status_code == 429  # the 11th attempt in the window, made on the OTHER instance


def test_db_rate_limiter_is_atomic_across_threads(db: Path) -> None:
    setup = connect_libsql(str(db), hosted=True)
    migrate(setup, NOW.isoformat())
    local = threading.local()

    def conn():  # type: ignore[no-untyped-def]
        if not hasattr(local, "c"):
            local.c = connect_libsql(str(db), hosted=True)
        return local.c

    limiter = DbRateLimiter(conn, "login", limit=10, window_s=60, clock=NOW.timestamp)
    results: list[bool] = []
    barrier = threading.Barrier(20)

    def hit() -> None:
        barrier.wait(5)
        results.append(limiter.allow())

    threads = [threading.Thread(target=hit) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 10


def test_state_is_not_kept_on_local_disk(db: Path) -> None:
    with make_client(db) as c:
        login(c)
        st = state(c)
        assert not st.settings.data_dir.exists()  # no data dir, no token file, no backups directory
        assert st.token == TOKEN
