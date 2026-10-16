"""A05 / RC-5: a cold start on an already-migrated database issues ZERO write statements.

Before A05 every instance start ran ``CREATE TABLE IF NOT EXISTS schema_version`` and an ``UPDATE ingestion_runs``
(writes on every cold start, about 6 round trips to the hosted database). Now startup reads the schema version with
one ``SELECT``, migrates only when a migration is pending, and marks interrupted runs only when a read finds one.

Statements are recorded on the connection the app opens, AFTER the driver's connect-time pragmas (connection setup,
not data writes)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from iip.api import app as app_module
from iip.api.app import create_app
from iip.api.routes import all_routers
from iip.api.settings import Settings
from iip.services import ingestion
from iip.store import db as db_module

NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
WRITE_HEADS = ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER", "BEGIN", "COMMIT", "VACUUM")
TOKEN = "t" * 43


def _is_write(sql: str) -> bool:
    head = sql.lstrip().upper()
    if head.startswith("PRAGMA"):
        return "=" in head  # a pragma assignment changes state; a pragma read does not
    return head.startswith(WRITE_HEADS)


class Recorder:
    def __init__(self) -> None:
        self.statements: list[str] = []

    @property
    def writes(self) -> list[str]:
        return [s for s in self.statements if _is_write(s)]


def _record_sqlite(monkeypatch: pytest.MonkeyPatch, rec: Recorder) -> None:
    real = db_module.connect

    def connect(path: Path | str) -> sqlite3.Connection:
        conn = real(path)
        conn.set_trace_callback(rec.statements.append)
        return conn

    monkeypatch.setattr(app_module, "connect", connect)


def _record_libsql(monkeypatch: pytest.MonkeyPatch, rec: Recorder) -> None:
    real = db_module.connect_libsql

    def connect_libsql(database: str, auth_token: str | None = None, *, hosted: bool = False) -> sqlite3.Connection:
        conn: Any = real(database, auth_token, hosted=hosted)
        execute, executemany, executescript = conn.execute, conn.executemany, conn.executescript

        def rec_execute(sql: str, params: Any = ()) -> Any:
            rec.statements.append(sql)
            return execute(sql, params)

        def rec_executemany(sql: str, seq: Any) -> Any:
            rec.statements.append(sql)
            return executemany(sql, seq)

        def rec_executescript(script: str) -> Any:
            rec.statements.append(script)
            return executescript(script)

        conn.execute, conn.executemany, conn.executescript = rec_execute, rec_executemany, rec_executescript
        return conn  # type: ignore[no-any-return]

    monkeypatch.setattr(app_module, "connect_libsql", connect_libsql)


def _local(tmp_path: Path) -> Settings:
    return Settings(env="test", auth=False, data_dir=tmp_path / "iip")


def _hosted(tmp_path: Path) -> Settings:
    return Settings(
        env="test", deploy="vercel", public_origin="https://iip.example.test", db_url=str(tmp_path / "hosted.db"),
        access_token=TOKEN, data_dir=tmp_path / "must-not-be-used",
    )  # fmt: skip


def _start(settings: Settings, clock: Callable[[], datetime] = lambda: NOW) -> Any:
    return create_app(settings, clock=clock, routers=all_routers())


def _close(asgi: Any) -> None:
    asgi.app.state.iip.close()


@pytest.fixture(params=["local", "hosted"])
def mode(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture
def settings(mode: str, tmp_path: Path) -> Settings:
    return _local(tmp_path) if mode == "local" else _hosted(tmp_path)


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


def _arm(mode: str, monkeypatch: pytest.MonkeyPatch, rec: Recorder) -> None:
    (_record_sqlite if mode == "local" else _record_libsql)(monkeypatch, rec)


def test_cold_start_on_a_migrated_database_writes_nothing(
    mode: str, settings: Settings, monkeypatch: pytest.MonkeyPatch, recorder: Recorder
) -> None:
    _close(_start(settings))  # first start: migrates a fresh database (writes expected here)
    _arm(mode, monkeypatch, recorder)
    asgi = _start(settings)
    _close(asgi)
    assert recorder.statements, "the recorder saw no statements: it is not wired to the app's connection"
    assert recorder.writes == []
    assert len(recorder.statements) <= 2  # schema-version read + interrupted-run probe (was 4, two of them writes)


def test_cold_start_still_migrates_a_fresh_database(
    mode: str, settings: Settings, monkeypatch: pytest.MonkeyPatch, recorder: Recorder
) -> None:
    _arm(mode, monkeypatch, recorder)
    asgi = _start(settings)
    conn = asgi.app.state.iip.conn
    assert db_module.current_version(conn) == db_module.latest_version() >= 1
    _close(asgi)
    assert any(s.lstrip().upper().startswith("CREATE TABLE") for s in recorder.statements)


def test_a_pending_migration_is_applied_at_startup(
    mode: str, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the code ships a migration the database lacks, startup runs migrate() (and only then)."""
    _close(_start(settings))
    latest = db_module.latest_version()
    calls: list[str] = []
    real = db_module.migrate

    def spy(c: sqlite3.Connection, applied_at: str) -> list[str]:
        calls.append(applied_at)
        return real(c, applied_at)

    monkeypatch.setattr(db_module, "migrate", spy)
    _close(_start(settings))
    assert calls == []  # current: no migrate() call at all
    monkeypatch.setattr(db_module, "latest_version", lambda: latest + 1)  # a newer build with one more migration
    _close(_start(settings))
    assert calls == [NOW.isoformat()]


def test_read_schema_version_on_an_empty_database_is_zero_and_read_only(tmp_path: Path) -> None:
    conn = db_module.connect(tmp_path / "empty.db")
    seen: list[str] = []
    conn.set_trace_callback(seen.append)
    assert db_module.read_schema_version(conn) == 0
    assert [s for s in seen if _is_write(s)] == []
    conn.close()


def test_read_schema_version_does_not_hide_other_errors() -> None:
    class Broken:
        def execute(self, *_a: object) -> Any:
            raise sqlite3.OperationalError("disk I/O error")

    with pytest.raises(sqlite3.OperationalError, match="disk I/O"):
        db_module.read_schema_version(Broken())  # type: ignore[arg-type]


def _insert_running(conn: sqlite3.Connection, run_id: str, started_at: datetime) -> None:
    ingestion.sync_sources(conn)
    conn.execute(
        "INSERT INTO ingestion_runs(run_id, source_id, started_at, status) VALUES (?, 'amfi.navall', ?, 'running')",
        (run_id, started_at.isoformat()),
    )


def _status(conn: sqlite3.Connection, run_id: str) -> tuple[str, str | None]:
    row = conn.execute("SELECT status, error FROM ingestion_runs WHERE run_id = ?", (run_id,)).fetchone()
    return row["status"], row["error"]


def test_local_start_still_marks_runs_left_running_as_interrupted(tmp_path: Path) -> None:
    settings = _local(tmp_path)
    first = _start(settings)
    _insert_running(first.app.state.iip.conn, "run_old", NOW - timedelta(minutes=1))
    _close(first)
    second = _start(settings)
    assert _status(second.app.state.iip.conn, "run_old") == ("failed", ingestion.INTERRUPTED)
    _close(second)


def test_hosted_start_marks_only_stale_runs_and_writes_nothing_for_a_live_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hosted: a run of a resumable job whose progress was touched within the hour belongs to a job another instance
    is still driving. The read-only probe must agree with ``mark_interrupted_runs`` exactly, so such a run causes no
    write at all, while a stale run is still marked."""
    settings = _hosted(tmp_path)
    first = _start(settings)
    conn = first.app.state.iip.conn
    _insert_running(conn, "run_live", NOW - timedelta(hours=2))
    conn.execute(
        "INSERT INTO job_progress(job_key, state_json, updated_at) VALUES ('navall', ?, ?)",
        ('{"run_id": "run_live"}', (NOW - timedelta(minutes=5)).isoformat()),
    )
    _insert_running(conn, "run_recent", NOW - timedelta(seconds=30))  # may still be running on another instance
    _close(first)

    rec = Recorder()
    _record_libsql(monkeypatch, rec)
    second = _start(settings)
    assert rec.writes == []
    conn = second.app.state.iip.conn
    assert _status(conn, "run_live") == ("running", None)
    assert _status(conn, "run_recent") == ("running", None)
    _insert_running(conn, "run_stale", NOW - timedelta(hours=3))
    _close(second)

    third = _start(settings)
    conn = third.app.state.iip.conn
    assert _status(conn, "run_stale") == ("failed", ingestion.INTERRUPTED)
    assert _status(conn, "run_live") == ("running", None)
    _close(third)
