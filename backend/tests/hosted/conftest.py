"""Hosted mode (ADR-0013) under test: a LOCAL libSQL file stands in for the remote Turso database (no network —
the suite-wide guard still applies), with exactly the hosted behaviour (``connect_libsql(..., hosted=True)``)."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from iip.api.app import create_app
from iip.api.routes import all_routers
from iip.api.settings import Settings

ORIGIN = "https://iip.example.test"
TOKEN = secrets.token_urlsafe(32)
NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)


def hosted_settings(db: Path, **overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "env": "test", "deploy": "vercel", "public_origin": ORIGIN, "db_url": str(db), "access_token": TOKEN,
        "data_dir": db.parent / "must-not-be-used",
    }  # fmt: skip
    return Settings(**{**base, **overrides})


def make_client(db: Path, clock: Callable[[], datetime] = lambda: NOW) -> TestClient:
    app = create_app(hosted_settings(db), clock=clock, routers=all_routers())
    return TestClient(app, base_url=ORIGIN, raise_server_exceptions=False)


def login(c: TestClient) -> dict[str, str]:
    r = c.post("/api/session", json={"token": TOKEN}, headers={"Origin": ORIGIN})
    assert r.status_code == 200, r.text
    return {"Origin": ORIGIN, "X-IIP-CSRF": r.json()["csrf"]}


def state(c: TestClient) -> Any:
    return c.app.app.state.iip  # type: ignore[attr-defined]


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "hosted.db"


@pytest.fixture
def client(db: Path) -> Iterator[TestClient]:
    with make_client(db) as c:
        yield c
