import sqlite3
from pathlib import Path

import pytest

from iip.store.db import backup, connect, current_version, integrity_ok, migrate, restore, write_tx
from iip.store.observations import ObservationRow, UpsertOutcome, current_series, upsert_observation

T0 = "2026-10-15T00:00:00+00:00"


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(tmp_path / "iip.db")
    migrate(conn, T0)
    return conn


def _obs(conn: sqlite3.Connection, value: str, superseded_by: int | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO observations(series_id, kind, value, unit, currency, observation_date, retrieved_at, source_id,"
        " source_url, quality_status, raw_sha256, superseded_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "amfi:119551",
            "nav",
            value,
            "INR/unit",
            "INR",
            "2026-10-14",
            T0,
            "amfi_navall",
            "https://portal.amfiindia.com/spages/NAVAll.txt",
            "ok",
            "ab" * 32,
            superseded_by,
        ),
    )
    return int(cur.lastrowid or 0)


def test_migrations_apply_once_and_are_idempotent(tmp_path: Path) -> None:
    conn = connect(tmp_path / "x.db")
    assert migrate(conn, T0) == ["0001_initial.sql"]
    assert migrate(conn, T0) == []
    assert current_version(conn) == 1


def test_pragmas(db: sqlite3.Connection) -> None:
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert db.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL


def test_foreign_keys_enforced(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO watchlist(instrument_id, added_at) VALUES ('missing', ?)", (T0,))


def test_only_one_current_observation_per_series_date_source(db: sqlite3.Connection) -> None:
    _obs(db, "25.9504")
    with pytest.raises(sqlite3.IntegrityError):
        _obs(db, "25.4000")


def _row(value: str, source: str = "amfi_navall") -> ObservationRow:
    return ObservationRow(
        series_id="amfi:119551",
        kind="nav",
        value=value,
        unit="INR/unit",
        currency="INR",
        observation_date="2026-10-14",
        retrieved_at=T0,
        source_id=source,
        source_url="https://portal.amfiindia.com/spages/NAVAll.txt",
        quality_status="ok",
        raw_sha256="ab" * 32,
    )


def test_upsert_is_idempotent_and_corrections_keep_history(db: sqlite3.Connection) -> None:
    assert upsert_observation(db, _row("25.9504")) is UpsertOutcome.INSERTED
    assert upsert_observation(db, _row("25.9504")) is UpsertOutcome.UNCHANGED
    assert upsert_observation(db, _row("25.4000")) is UpsertOutcome.CORRECTED
    rows = db.execute("SELECT obs_id, value, superseded_by FROM observations ORDER BY obs_id").fetchall()
    assert [r["value"] for r in rows] == ["25.9504", "25.4000"]
    assert rows[0]["superseded_by"] == rows[1]["obs_id"] and rows[1]["superseded_by"] is None
    assert [r["value"] for r in current_series(db, "amfi:119551")] == ["25.4000"]


def test_different_sources_never_supersede_each_other(db: sqlite3.Connection) -> None:
    upsert_observation(db, _row("25.9504"))
    assert upsert_observation(db, _row("25.95040", source="mfapi")) is UpsertOutcome.INSERTED
    assert len(current_series(db, "amfi:119551")) == 2
    assert [r["value"] for r in current_series(db, "amfi:119551", source_id="amfi_navall")] == ["25.9504"]


def test_rejected_rows_excluded_from_current_series(db: sqlite3.Connection) -> None:
    bad = ObservationRow(**{**_row("0").__dict__, "quality_status": "rejected"})
    upsert_observation(db, bad)
    assert current_series(db, "amfi:119551") == []


def test_currency_is_inr_only(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO instruments(instrument_id, kind, name, currency, origin, created_at) VALUES"
            " ('x','fd','X','USD','manual',?)",
            (T0,),
        )


def test_write_tx_rolls_back_on_error(db: sqlite3.Connection) -> None:
    with pytest.raises(RuntimeError), write_tx(db):
        db.execute("INSERT INTO settings(key, value_json) VALUES ('k', '1')")
        raise RuntimeError("boom")
    assert db.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0


def test_backup_restore_drill(db: sqlite3.Connection, tmp_path: Path) -> None:
    """REL-40: a backup is only real if a restore from it reproduces the data."""
    _obs(db, "25.9504")
    bk = backup(db, tmp_path / "backups" / "iip-20261015.db")
    assert bk.exists() and not bk.with_suffix(".db.partial").exists()
    restored = tmp_path / "restored.db"
    restore(bk, restored)
    conn2 = connect(restored)
    assert integrity_ok(conn2)
    assert conn2.execute("SELECT value FROM observations").fetchone()[0] == "25.9504"
    assert current_version(conn2) == 1


def test_restore_refuses_corrupt_backup(tmp_path: Path) -> None:
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)
    with pytest.raises((RuntimeError, sqlite3.DatabaseError)):
        restore(bad, tmp_path / "out.db")
