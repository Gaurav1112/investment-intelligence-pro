"""Regression tests from the wave-2 ECC review, group F1 (store), on SQLite AND libSQL. All fixtures are synthetic.

* database-reviewer-05: a migration costs a handful of round trips (not one per statement), a failure inside the
  batched script is never half-applied, and a cold start that meets another instance mid-migration waits for it
  instead of failing.
* graft TA-1: a point-in-time read of outcomes sees only rows resolved on or before ``as_of``; rows without a
  resolution date are excluded.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from iip.store import db as dbm
from iip.store import ledger as lg

from ._ledger_fixtures import DRIVERS, NOW, open_db


def _connect(path: Path, driver: str) -> Any:
    return dbm.connect_libsql(str(path)) if driver == "libsql" else dbm.connect(path)


# ------------------------------------------------------------------------------------------ database-reviewer-05


def test_libsql_migration_is_a_few_round_trips_not_one_per_statement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    real_execute, real_script = dbm.LibsqlConnection.execute, dbm.LibsqlConnection.executescript

    def execute(self: Any, sql: str, params: Any = ()) -> Any:
        calls.append(sql)
        return real_execute(self, sql, params)

    def executescript(self: Any, script: str) -> Any:
        calls.append(script)
        return real_script(self, script)

    monkeypatch.setattr(dbm.LibsqlConnection, "execute", execute)
    monkeypatch.setattr(dbm.LibsqlConnection, "executescript", executescript)
    conn = dbm.connect_libsql(str(tmp_path / "x.db"))
    calls.clear()  # the connection pragmas are not part of the migration
    names = dbm.migrate(conn, NOW)
    statements = sum(len(dbm._split_sql(sql)) for _, _, sql in dbm._migration_files())
    assert len(names) == dbm.latest_version() and statements > 80
    # once: the version read, the schema_version DDL, the version read again; then per migration: BEGIN, the
    # version re-check under the lock, ONE script, the verify read, COMMIT (was ~58 round trips for 0004 alone)
    assert len(calls) <= 3 + 5 * len(names), len(calls)
    conn.close()


@pytest.mark.parametrize("driver", DRIVERS)
def test_a_failing_statement_inside_a_migration_is_never_half_applied(
    tmp_path: Path, driver: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = "CREATE TABLE fictional_a(x INTEGER);\nINSERT INTO no_such_table VALUES (1);\nCREATE TABLE fictional_b(x);"
    monkeypatch.setattr(dbm, "_migration_files", lambda: [(1, "0001_broken.sql", broken)])
    conn = _connect(tmp_path / "x.db", driver)
    with pytest.raises(sqlite3.OperationalError, match="no_such_table"):
        dbm.migrate(conn, NOW)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "fictional_a" not in names and "fictional_b" not in names
    assert dbm.read_schema_version(conn) == 0
    assert not conn.in_transaction
    conn.close()


@pytest.mark.parametrize("driver", DRIVERS)
def test_cold_start_waits_for_another_instance_that_is_migrating(
    tmp_path: Path, driver: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dbm, "BUSY_RETRY_S", 0.2)
    path = tmp_path / "x.db"
    first = _connect(path, driver)  # instance 1, mid-migration: holds the write lock
    second = _connect(path, driver)  # instance 2, cold-starting meanwhile
    if driver == "sqlite":
        second.execute("PRAGMA busy_timeout=200")
    first.execute("BEGIN IMMEDIATE")
    first.execute(dbm._SCHEMA_VERSION_DDL)
    result: dict[str, Any] = {}

    def cold_start() -> None:
        try:
            result["applied"] = dbm.ensure_schema(second, NOW, wait_s=20.0)
        except Exception as exc:  # the assertion below reports it
            result["error"] = exc

    t = threading.Thread(target=cold_start)
    t.start()
    time.sleep(0.8)  # instance 2 has met the lock at least once by now
    for version, name, sql in dbm._migration_files():
        dbm._apply_migration(first, version, name, sql, NOW)
    first.execute("COMMIT")
    t.join(30)
    assert "error" not in result, result.get("error")
    assert result["applied"] == []  # instance 1 applied everything; instance 2 applied nothing twice
    rows = second.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
    assert [r[0] for r in rows] == list(range(1, dbm.latest_version() + 1))
    first.close()
    second.close()


@pytest.mark.parametrize("driver", DRIVERS)
def test_cold_start_still_fails_when_the_lock_never_frees(
    tmp_path: Path, driver: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dbm, "BUSY_RETRY_S", 0.1)
    path = tmp_path / "x.db"
    first, second = _connect(path, driver), _connect(path, driver)
    if driver == "sqlite":
        second.execute("PRAGMA busy_timeout=100")
    first.execute("BEGIN IMMEDIATE")
    first.execute(dbm._SCHEMA_VERSION_DDL)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        dbm.ensure_schema(second, NOW, wait_s=0.5)  # bounded: a wedged lock is reported, never waited on forever
    first.execute("ROLLBACK")
    first.close()
    second.close()


# --------------------------------------------------------------------------------------------------- graft TA-1


@pytest.fixture(params=DRIVERS)
def db(request: pytest.FixtureRequest, tmp_path: Path) -> Any:
    conn = open_db(tmp_path / "x.db", request.param)
    yield conn
    conn.close()


def _eval(scope: str) -> lg.RuleEvaluation:
    return lg.RuleEvaluation(
        rule_id="S-E", version=1, as_of_date="2026-09-15", scope_id=scope, state="PRE_REGISTERED", condition_met=None,
        payload_json="{}", input_hash="h", snapshot_id="snap1", evaluated_at=NOW,
    )  # fmt: skip


def _outcome(scope: str, resolved_on: str | None) -> lg.Outcome:
    return lg.Outcome("S-E", 1, "2026-09-15", scope, "2026-10-15", "scored", Decimal("0.001"), None, f"i-{scope}",
                      NOW, resolved_on)  # fmt: skip


def test_point_in_time_outcomes_see_only_rows_resolved_by_as_of(db: Any) -> None:
    lg.append_rule_evaluations(db, [_eval("role:a"), _eval("role:b"), _eval("role:c")])
    lg.append_outcomes(
        db, [_outcome("role:a", "2026-10-16"), _outcome("role:b", "2026-10-20"), _outcome("role:c", None)]
    )
    assert lg.outcomes_as_of(db, "2026-10-15") == []
    assert [r["scope_id"] for r in lg.outcomes_as_of(db, "2026-10-16")] == ["role:a"]
    assert [r["scope_id"] for r in lg.outcomes_as_of(db, "2026-12-31")] == ["role:a", "role:b"]  # NULL never seen
    assert [r["scope_id"] for r in lg.outcomes_as_of(db, "2026-12-31", rule_id="S-E", version=1)] == [
        "role:a", "role:b",
    ]  # fmt: skip
    assert lg.outcomes_as_of(db, "2026-12-31", rule_id="S-OTHER") == []


def test_an_outcome_cannot_be_resolved_before_its_horizon(db: Any) -> None:
    lg.append_rule_evaluations(db, [_eval("role:a")])
    with pytest.raises(sqlite3.IntegrityError):
        lg.append_outcomes(db, [_outcome("role:a", "2026-10-14")])  # horizon_end is 2026-10-15
