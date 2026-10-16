"""B02: the Today API over HTTP — one statement per Today read, no engine on page load, "I did this", CSRF.

Statements are counted with a fake driver around the app's connection (local mode keeps sessions in memory, so every
counted statement belongs to the endpoint). All data is SYNTHETIC.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from starlette.testclient import TestClient

from iip.api.app import AppState, create_app
from iip.api.routes import all_routers
from iip.api.settings import Settings
from iip.rules.loader import local_stress_values_path
from iip.services import risk_snapshot as rs
from iip.services import signal_registry
from tests.services import _snapshot_fixtures as fx

ORIGIN = "http://127.0.0.1:8741"
NOW = datetime(2026, 10, 16, 6, 0, tzinfo=UTC)


class Counter:
    def __init__(self) -> None:
        self.statements: list[str] = []


class _Counting:
    def __init__(self, raw: Any, counter: Counter) -> None:
        self._raw = raw
        self._counter = counter

    def execute(self, sql: str, params: Any = ()) -> Any:
        self._counter.statements.append(sql)
        return self._raw.execute(sql, params)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._raw, name)


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, dict[str, str], Counter, Any]]:
    settings = Settings(env="dev", data_dir=tmp_path / "dev")
    local = local_stress_values_path(settings.data_dir)  # fictional stress values (U-08: local config only)
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(yaml.safe_dump(fx.LOCAL_STRESS))
    counter = Counter()
    real = AppState.conn
    assert isinstance(real, property) and real.fget is not None
    getter = real.fget
    monkeypatch.setattr(AppState, "conn", property(lambda self: _Counting(getter(self), counter)))
    application = create_app(settings, routers=all_routers(), clock=lambda: NOW)
    c = TestClient(application, base_url=ORIGIN)
    c.__enter__()
    inner: Any = application
    while not hasattr(inner, "state"):
        inner = inner.app
    raw = getter(inner.state.iip)
    token = settings.token_path.read_text().strip()
    csrf = c.post("/api/session", json={"token": token}, headers={"Origin": ORIGIN}).json()["csrf"]
    h = {"Origin": ORIGIN, "X-IIP-CSRF": csrf}
    counter.statements.clear()
    yield c, h, counter, raw
    c.__exit__(None, None, None)


def _seed(raw: Any) -> None:
    fx.seed_two_goals(raw)
    raw.commit()


def test_today_before_any_snapshot_is_one_statement(app: Any) -> None:
    c, _h, counter, _raw = app
    r = c.get("/api/today")
    assert r.status_code == 200 and r.json()["state"] == rs.NO_SNAPSHOT
    assert len(counter.statements) == 1


def test_snapshot_then_today_in_one_statement(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    c, h, counter, raw = app
    _seed(raw)
    r = c.post("/api/today/snapshot", json={"as_of": fx.AS_OF.isoformat()}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] and body["verdict"] == "ACTIONS"

    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("engine ran on page load")

    monkeypatch.setattr(rs, "compute_snapshot", boom)
    counter.statements.clear()
    today = c.get("/api/today")
    assert today.status_code == 200 and len(counter.statements) == 1
    t = today.json()
    assert t["snapshot_id"] == body["snapshot_id"] and t["cards"][0]["kind"] == "LOSS_BUDGET_BREACH"
    # C01 TodayResponse shape: string layers, top_n, and every number carries a display and an Explained.
    assert t["top_n"] >= 1 and t["computed_at"] and t["cards"][0]["layer"] == "L3"
    for card in t["cards"]:
        for n in [*card["numbers"], *(x for s in card["steps"] for x in s["numbers"])]:
            assert n["display"] and n["explain"]["display"] == n["display"]
            assert n["fact_ids"] or n["formula_id"]
    counter.statements.clear()
    needs = c.get("/api/today/needs")
    assert needs.status_code == 200 and len(counter.statements) == 1 and needs.json()["needs"]


def test_i_did_this(app: Any) -> None:
    c, h, _counter, raw = app
    _seed(raw)
    sid = c.post("/api/today/snapshot", json={"as_of": fx.AS_OF.isoformat()}, headers=h).json()["snapshot_id"]
    cards = c.get("/api/today").json()["cards"]
    action = next(x for x in cards if x["is_action"])
    abstain = next(x for x in cards if not x["is_action"])

    no_csrf = c.post("/api/today/decisions", json={"snapshot_id": sid, "card_id": action["card_id"]},
                     headers={"Origin": ORIGIN})  # fmt: skip
    assert no_csrf.status_code == 403

    ok = c.post("/api/today/decisions", json={"snapshot_id": sid, "card_id": action["card_id"]}, headers=h)
    assert ok.status_code == 200 and ok.json()["decision"]["decision"] == "done"
    logged = ok.json()["decision"]
    assert ok.json()["status"] == "recorded" and logged["decision_id"] and logged["cas_confirmed"] is None
    today = c.get("/api/today").json()
    assert today["decisions"][0]["card_id"] == action["card_id"]
    # The Today view puts the logged 'done' on its card (C01 DecisionView).
    card = next(x for x in today["cards"] if x["card_id"] == action["card_id"])
    assert card["decision"] == {"decision_id": logged["decision_id"], "decided_at": logged["decided_at"],
                                "cas_confirmed": None}  # fmt: skip

    # A retry (e.g. after a network error) does not log twice.
    again = c.post("/api/today/decisions", json={"snapshot_id": sid, "card_id": action["card_id"]}, headers=h)
    assert again.status_code == 200 and again.json()["status"] == "already_recorded"
    assert again.json()["decision"]["decision_id"] == logged["decision_id"]
    assert len(c.get("/api/today").json()["decisions"]) == 1

    bad = c.post("/api/today/decisions", json={"snapshot_id": sid, "card_id": abstain["card_id"]}, headers=h)
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "NOT_AN_ACTION"
    unknown = c.post("/api/today/decisions", json={"snapshot_id": sid, "card_id": "0" * 64}, headers=h)
    assert unknown.status_code == 404
    malformed = c.post("/api/today/decisions", json={"snapshot_id": "x", "card_id": "y"}, headers=h)
    assert malformed.status_code == 422


def test_snapshot_rejects_future_as_of(app: Any) -> None:
    c, h, _counter, _raw = app
    r = c.post("/api/today/snapshot", json={"as_of": "2027-01-01"}, headers=h)
    assert r.status_code == 422


def test_snapshot_route_returns_signal_registry_problems(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """REG-1: the J4 compute route returns registry conflicts / rejections (rule ids only), empty when none."""
    c, h, _counter, raw = app
    _seed(raw)
    first = c.post("/api/today/snapshot", json={"as_of": fx.AS_OF.isoformat()}, headers=h).json()
    assert first["shadow"]["registry_conflicts"] == [] and first["shadow"]["registry_rejected"] == []

    def problems(_c: Any, *, now: str, directory: Path) -> signal_registry.RegistryResult:
        return signal_registry.RegistryResult(0, 0, ("S-E@1",), ("S-Q@1.yaml",))

    monkeypatch.setattr(signal_registry, "register_committed_specs", problems)
    body = c.post("/api/today/snapshot", json={"as_of": fx.AS_OF.isoformat()}, headers=h).json()
    assert body["shadow"]["registry_conflicts"] == ["S-E@1"]
    assert body["shadow"]["registry_rejected"] == ["S-Q@1"]
