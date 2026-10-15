from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import APIRouter, Request
from starlette.testclient import TestClient

from iip.api.app import create_app
from iip.api.routes import all_routers
from iip.api.settings import Settings

BASE = "http://127.0.0.1:8741"
ORIGIN = "http://127.0.0.1:8741"


def _test_router() -> APIRouter:
    r = APIRouter()

    @r.post("/api/echo")
    def echo(request: Request) -> dict[str, str]:
        return {"ok": "yes"}

    @r.get("/api/boom")
    def boom() -> None:
        raise RuntimeError("secret path /Users/x/db.sqlite SELECT * FROM holdings")

    return r


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(env="prod", data_dir=tmp_path / "iip")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings, routers=[_test_router(), *all_routers()])
    with TestClient(app, base_url=BASE, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def token(settings: Settings) -> str:
    return settings.token_path.read_text().strip()


@pytest.fixture
def authed(client: TestClient, token: str) -> tuple[TestClient, str]:
    r = client.post("/api/session", json={"token": token}, headers={"Origin": ORIGIN})
    assert r.status_code == 200, r.text
    return client, r.json()["csrf"]
