"""Verifier finding (round close): migration 0004 was edited in place during wave 2, and ``migrate()`` skips a version
already recorded. A database migrated with an earlier 0004 then lacks snapshot_runs, outcomes.resolved_on,
decisions_log.card_key and the ix_decisions_log_* indexes, and fails only later at runtime. ``ensure_schema`` (every
startup) now compares the database's tables, indexes, triggers and columns with the shipped migrations and refuses a
drifted database with a clear error, in the SAME single read as the version check (startup budget unchanged)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from iip.store import db as dbm

NOW = "2026-10-15T06:00:00+00:00"


@pytest.fixture(params=("sqlite", "libsql"))
def conn(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[sqlite3.Connection]:
    path = tmp_path / "drift.db"
    c = dbm.connect_libsql(str(path), hosted=True) if request.param == "libsql" else dbm.connect(path)
    yield c
    c.close()


def test_a_current_database_passes_and_nothing_is_reapplied(conn: sqlite3.Connection) -> None:
    assert dbm.ensure_schema(conn, NOW)  # fresh: applies every migration, then verifies
    assert dbm.ensure_schema(conn, NOW) == []


def test_a_missing_table_from_an_earlier_0004_is_refused(conn: sqlite3.Connection) -> None:
    dbm.ensure_schema(conn, NOW)
    conn.execute("DROP TABLE snapshot_runs")
    with pytest.raises(dbm.MigrationError, match="snapshot_runs"):
        dbm.ensure_schema(conn, NOW)


def test_missing_indexes_from_an_earlier_0004_are_refused(conn: sqlite3.Connection) -> None:
    dbm.ensure_schema(conn, NOW)
    names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'ix_decisions_log_%'")]
    assert names
    for n in names:
        conn.execute(f"DROP INDEX {n}")
    with pytest.raises(dbm.MigrationError, match="ix_decisions_log_"):
        dbm.ensure_schema(conn, NOW)


def test_a_missing_column_is_refused(conn: sqlite3.Connection) -> None:
    dbm.ensure_schema(conn, NOW)
    # The schema an earlier 0004 left: rebuild decisions_log WITHOUT card_key (DROP COLUMN is refused while an index
    # uses it, so the index goes first, as it did not exist then either).
    for (n,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='decisions_log'"
    ).fetchall():
        if not str(n).startswith("sqlite_"):
            conn.execute(f"DROP INDEX {n}")
    for (n,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='decisions_log'"
    ).fetchall():
        conn.execute(f"DROP TRIGGER {n}")
    conn.execute("ALTER TABLE decisions_log DROP COLUMN card_key")
    with pytest.raises(dbm.MigrationError, match=r"decisions_log\.card_key"):
        dbm.ensure_schema(conn, NOW)


def test_the_expected_schema_covers_every_migration_object() -> None:
    exp = dbm.expected_schema()
    assert "table:snapshot_runs" in exp and "column:outcomes.resolved_on" in exp
    assert "column:decisions_log.card_key" in exp
    assert any(e.startswith("index:ix_decisions_log_") for e in exp)


def test_the_column_parser_agrees_with_sqlite_for_every_shipped_table(conn: sqlite3.Connection) -> None:
    """The single startup read parses columns from the stored CREATE text; SQLite's own table_info is the oracle."""
    dbm.ensure_schema(conn, NOW)
    tables = conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    rows = tables.fetchall()
    assert len(rows) > 20
    for name, sql in rows:
        oracle = [str(r[1]) for r in conn.execute(f"PRAGMA table_info({name})").fetchall()]
        assert dbm._table_columns(str(sql)) == oracle, name
