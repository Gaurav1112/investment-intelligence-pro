from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from iip.api.app import create_app
from iip.api.routes import all_routers
from iip.api.settings import Settings

ORIGIN = "http://127.0.0.1:8741"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[tuple[TestClient, str]]:
    settings = Settings(env="prod", data_dir=tmp_path / "iip")
    app = create_app(settings, routers=all_routers(), clock=lambda: datetime(2026, 10, 15, 6, 0, tzinfo=UTC))
    with TestClient(app, base_url=ORIGIN) as c:
        token = settings.token_path.read_text().strip()
        csrf = c.post("/api/session", json={"token": token}, headers={"Origin": ORIGIN}).json()["csrf"]
        yield c, csrf


def test_profile_roundtrip_and_mode(client: tuple[TestClient, str]) -> None:
    c, csrf = client
    assert c.get("/api/profile").json()["mode"] == "EXPLORATION"
    body = {
        "amount": "500000",
        "withdrawal_date": "2027-04-15",
        "objective": "A_capital_preservation",
        "loss_acceptable": False,
        "early_need": "possible",
    }
    r = c.put("/api/profile", json=body, headers={"Origin": ORIGIN, "X-IIP-CSRF": csrf})
    assert r.status_code == 200, r.text
    got = c.get("/api/profile").json()
    assert got["mode"] == "PERSONALISED" and got["horizon_days"] == 182
    assert got["profile"]["amount"] == "500000"  # decimals travel as strings


def test_profile_rejects_floats_over_the_wire(client: tuple[TestClient, str]) -> None:
    c, csrf = client
    r = c.put("/api/profile", json={"amount": 500000.5}, headers={"Origin": ORIGIN, "X-IIP-CSRF": csrf})
    assert r.status_code == 422
