"""A02: statement counts per endpoint (data-health ≤ 3, instrument detail ≤ 2, summary ≤ 2), the new
``/instruments/{id}/summary`` and ``?from=&grid=monthly``, and Discovery's time budget and write behaviour over HTTP.

Statements are counted with a fake driver wrapped around the app's connection (local mode: sessions are in memory,
so every counted statement belongs to the endpoint). All data is SYNTHETIC (``/api/dev/seed-fixtures``).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from iip.api.app import AppState, create_app
from iip.api.routes import all_routers
from iip.api.settings import Settings
from iip.data.registry import REGISTRY
from iip.services import discovery, ingestion
from iip.store.db import connect

ORIGIN = "http://127.0.0.1:8741"
NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
MF = "mf:900001"  # synthetic fixture scheme created by fixtures.seed
TBILL = "tbill:182d:2027-04-13"
_WRITE_HEADS = ("INSERT", "UPDATE", "DELETE", "REPLACE")


class Counter:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.state: Any = None  # the app's AppState (set by the fixture)

    @property
    def writes(self) -> list[str]:
        return [s for s in self.statements if s.lstrip().upper().startswith(_WRITE_HEADS)]


class _Counting:
    def __init__(self, raw: Any, counter: Counter) -> None:
        self._raw = raw
        self._counter = counter

    def execute(self, sql: str, params: Any = ()) -> Any:
        self._counter.statements.append(sql)
        return self._raw.execute(sql, params)

    def executemany(self, sql: str, seq: Any) -> Any:
        self._counter.statements.append(sql)
        return self._raw.executemany(sql, seq)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._raw, name)


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, dict[str, str], Counter]]:
    settings = Settings(env="dev", data_dir=tmp_path / "dev")
    counter = Counter()
    real = AppState.conn
    assert isinstance(real, property) and real.fget is not None
    getter = real.fget
    monkeypatch.setattr(AppState, "conn", property(lambda self: _Counting(getter(self), counter)))
    application = create_app(settings, routers=all_routers(), clock=lambda: NOW)
    c = TestClient(application, base_url=ORIGIN)
    c.__enter__()
    inner: Any = application
    while not hasattr(inner, "state"):  # unwrap the ASGI middleware around the FastAPI app
        inner = inner.app
    counter.state = inner.state.iip
    token = settings.token_path.read_text().strip()
    csrf = c.post("/api/session", json={"token": token}, headers={"Origin": ORIGIN}).json()["csrf"]
    h = {"Origin": ORIGIN, "X-IIP-CSRF": csrf}
    assert c.post("/api/dev/seed-fixtures", json={}, headers=h).status_code == 200
    counter.statements.clear()
    yield c, h, counter
    c.__exit__(None, None, None)


def _raw(tmp_path: Path) -> Any:
    return connect(Settings(env="dev", data_dir=tmp_path / "dev").db_path)


# ------------------------------------------------------------------ data health


def test_data_health_uses_at_most_three_statements(app: tuple[TestClient, dict[str, str], Counter]) -> None:
    c, _, counter = app
    body = c.get("/api/data-health").json()
    assert len(counter.statements) <= 3, counter.statements
    assert counter.writes == []
    assert {s["source_id"] for s in body["sources"]} == set(REGISTRY)
    # The registry's own status label and its evidence reference travel with each source (C04 DataRightsPanel).
    assert all(s["status"] == REGISTRY[s["source_id"]].status.value for s in body["sources"])
    assert all(s["status_ref"] == REGISTRY[s["source_id"]].status_ref for s in body["sources"])


def test_data_health_last_run_matches_one_query_per_source(
    app: tuple[TestClient, dict[str, str], Counter], tmp_path: Path
) -> None:
    """Oracle: the original per-source query (latest started_at) for every registry source."""
    c, _, _ = app
    raw = _raw(tmp_path)
    ids = sorted(REGISTRY)[:2]
    ingestion.sync_sources(raw)  # the run rows reference the source registry
    raw.execute("BEGIN")
    for i, (sid, started, status) in enumerate([(ids[0], "2026-10-01T00:00:00", "ok"),
                                                (ids[0], "2026-10-03T00:00:00", "failed"),
                                                (ids[1], "2026-10-02T00:00:00", "partial")]):  # fmt: skip
        raw.execute(
            "INSERT INTO ingestion_runs(run_id, source_id, started_at, finished_at, status, rows_ok, rows_rejected,"
            " error) VALUES (?,?,?,?,?,?,?,?)",
            (f"r{i}", sid, started, started, status, i, 0, None if status == "ok" else "synthetic"),
        )
    raw.execute("COMMIT")
    body = c.get("/api/data-health").json()
    for s in body["sources"]:
        last = raw.execute(
            "SELECT status, finished_at, rows_ok, rows_rejected, error FROM ingestion_runs WHERE source_id=?"
            " ORDER BY started_at DESC LIMIT 1",
            (s["source_id"],),
        ).fetchone()
        assert s["last_run"] == (dict(last) if last else None), s["source_id"]
    assert {s["source_id"]: s["last_run"]["status"] for s in body["sources"] if s["last_run"]} == {
        ids[0]: "failed",
        ids[1]: "partial",
    }
    raw.close()


# ------------------------------------------------------------------ instrument detail and summary


@pytest.mark.parametrize("iid", [MF, TBILL, "fd:fixture-bank:180d"])
def test_instrument_detail_uses_at_most_two_statements(
    app: tuple[TestClient, dict[str, str], Counter], iid: str
) -> None:
    c, _, counter = app
    body = c.get(f"/api/instruments/{iid}").json()
    assert len(counter.statements) <= 2, counter.statements
    assert body["instrument"]["instrument_id"] == iid
    terms = {"mf_scheme": "mf_schemes", "tbill": "bond_terms", "fd": "deposit_terms"}[body["instrument"]["kind"]]
    assert set(body) - {"instrument", "series", "freshness"} == {terms}  # only the table that has a row
    assert body[terms]["instrument_id"] == iid
    if iid != "fd:fixture-bank:180d":  # an FD has no observation series (its rate is in deposit_terms)
        assert body["series"]["points"], body["series"]


def test_instrument_detail_matches_the_previous_reads(
    app: tuple[TestClient, dict[str, str], Counter], tmp_path: Path
) -> None:
    c, _, _ = app
    raw = _raw(tmp_path)
    body = c.get(f"/api/instruments/{MF}").json()
    assert body["instrument"] == dict(raw.execute("SELECT * FROM instruments WHERE instrument_id=?", (MF,)).fetchone())
    assert body["mf_schemes"] == dict(raw.execute("SELECT * FROM mf_schemes WHERE instrument_id=?", (MF,)).fetchone())
    points = raw.execute(
        "SELECT observation_date, value, source_id, source_url, retrieved_at, quality_status FROM observations"
        " WHERE series_id=? AND superseded_by IS NULL ORDER BY observation_date",
        ("nav:900001",),
    ).fetchall()
    assert body["series"] == {"series_id": "nav:900001", "points": [dict(p) for p in points]}
    badge, observed = ingestion.latest_freshness(raw, 900001, NOW)
    assert body["freshness"] == {"badge": badge, "observed": observed}
    raw.close()


def test_unknown_instrument_is_404(app: tuple[TestClient, dict[str, str], Counter]) -> None:
    c, _, _ = app
    assert c.get("/api/instruments/mf:nope").status_code == 404
    assert c.get("/api/instruments/mf:nope/summary").status_code == 404


def test_summary_has_no_history_and_uses_at_most_two_statements(
    app: tuple[TestClient, dict[str, str], Counter], tmp_path: Path
) -> None:
    c, _, counter = app
    body = c.get(f"/api/instruments/{MF}/summary").json()
    assert len(counter.statements) <= 2, counter.statements
    raw = _raw(tmp_path)
    n, first, last = raw.execute(
        "SELECT COUNT(*), MIN(observation_date), MAX(observation_date) FROM observations"
        " WHERE series_id='nav:900001' AND superseded_by IS NULL"
    ).fetchone()
    assert body["series"]["points"] == n and n > 60
    assert body["series"]["first_date"] == first and body["series"]["latest"]["observation_date"] == last
    assert set(body["series"]["latest"]) == {"observation_date", "value", "source_id", "source_url", "retrieved_at",
                                             "quality_status"}  # fmt: skip
    assert body["instrument"]["name"] and body["mf_schemes"]["instrument_id"] == MF
    assert body["freshness"] == dict(zip(("badge", "observed"), ingestion.latest_freshness(raw, 900001, NOW),
                                         strict=True))  # fmt: skip
    raw.close()


def test_series_from_and_monthly_grid(app: tuple[TestClient, dict[str, str], Counter]) -> None:
    c, _, counter = app
    full = c.get(f"/api/instruments/{MF}").json()["series"]["points"]
    dates = [p["observation_date"] for p in full]
    start = "2025-01-01"
    counter.statements.clear()
    since = c.get(f"/api/instruments/{MF}", params={"from": start}).json()["series"]
    assert len(counter.statements) <= 2
    assert since["filter"] == {"from": start, "grid": None}
    assert [p["observation_date"] for p in since["points"]] == [d for d in dates if d >= start]

    monthly = c.get(f"/api/instruments/{MF}", params={"from": start, "grid": "monthly"}).json()["series"]
    expected: dict[str, str] = {}
    for d in dates:
        if d >= start:
            expected[d[:7]] = max(expected.get(d[:7], d), d)
    got = [p["observation_date"] for p in monthly["points"]]
    assert got == sorted(expected.values())
    assert got[-1] == dates[-1]  # the latest point is always kept
    by_date = {p["observation_date"]: p for p in full}
    assert all(p == by_date[p["observation_date"]] for p in monthly["points"])  # sub-sampled, never changed
    assert monthly["filter"] == {"from": start, "grid": "monthly"}


def test_bad_grid_or_date_is_422(app: tuple[TestClient, dict[str, str], Counter]) -> None:
    c, _, _ = app
    assert c.get(f"/api/instruments/{MF}", params={"grid": "weekly"}).status_code == 422
    assert c.get(f"/api/instruments/{MF}", params={"from": "15-10-2026"}).status_code == 422


# ------------------------------------------------------------------ discovery over HTTP


def test_discover_repeat_visit_writes_nothing(app: tuple[TestClient, dict[str, str], Counter]) -> None:
    c, h, counter = app
    first = c.post("/api/discover", json={}, headers=h).json()
    assert len(counter.writes) <= 1
    counter.statements.clear()
    again = c.post("/api/discover", json={}, headers=h).json()
    assert counter.writes == [], counter.writes
    assert again["run"]["run_id"] == first["run"]["run_id"] is not None
    assert c.get(f"/api/runs/{again['run']['run_id']}").status_code == 200


def test_discover_budget_overrun_returns_flagged_partial_not_504(
    app: tuple[TestClient, dict[str, str], Counter],
) -> None:
    c, h, counter = app
    state = counter.state
    ticks = {"t": 0.0}

    def fake_monotonic() -> float:  # every reading advances 25 s: the 60 s budget runs out mid-build
        ticks["t"] += 25.0
        return ticks["t"]

    state.monotonic = fake_monotonic
    r = c.post("/api/discover", json={}, headers=h)
    assert r.status_code == 200
    out = r.json()
    assert out["partial"] is not None and out["partial"]["reason"] == discovery.TIME_BUDGET_EXCEEDED
    assert out["partial"]["budget_s"] == 60
    assert out["run"]["run_id"] is None  # a partial result is never stored
    assert counter.writes == []


def test_discover_universe_is_bounded_in_statements(app: tuple[TestClient, dict[str, str], Counter]) -> None:
    c, h, counter = app
    c.post("/api/discover", json={}, headers=h)
    # Universe ≤ 10 (services test) + profile read + LLM-settings read + run lookup + one INSERT transaction.
    assert len(counter.statements) <= 16, counter.statements
