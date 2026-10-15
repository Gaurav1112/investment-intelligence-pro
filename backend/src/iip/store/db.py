"""SQLite connection, migrations and backup (ADR-0012, reliability-design.md)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=FULL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000",
)


_SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL, name TEXT NOT NULL, applied_at TEXT NOT NULL
)"""


class MigrationError(RuntimeError):
    pass


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None, detect_types=0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    for pragma in PRAGMAS:
        conn.execute(pragma)
    return conn


@contextmanager
def write_tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE transaction: takes the write lock up front (no mid-transaction upgrade deadlocks)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _migration_files() -> list[tuple[int, str, str]]:
    pkg = resources.files("iip.store") / "migrations"
    found: list[tuple[int, str, str]] = []
    for entry in pkg.iterdir():
        name = entry.name
        if name.endswith(".sql"):
            version = int(name.split("_", 1)[0])
            found.append((version, name, entry.read_text(encoding="utf-8")))
    found.sort()
    versions = [v for v, _, _ in found]
    if versions != list(range(1, len(versions) + 1)):
        raise MigrationError(f"migration versions must be contiguous from 1: {versions}")
    return found


def current_version(conn: sqlite3.Connection) -> int:
    """Read-only (SEC-10: GET routes must never write, not even DDL). migrate() creates the table."""
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'").fetchone()
    if exists is None:
        return 0
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    return int(row["v"] or 0)


def migrate(conn: sqlite3.Connection, applied_at: str) -> list[str]:
    """Apply pending migrations in order, each in its own transaction. Returns names applied."""
    applied: list[str] = []
    conn.execute(_SCHEMA_VERSION_DDL)
    have = current_version(conn)
    for version, name, sql in _migration_files():
        if version <= have:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in _split_sql(sql):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_version(version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, applied_at),
            )
        except Exception:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        applied.append(name)
    return applied


def _split_sql(sql: str) -> list[str]:
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def integrity_ok(conn: sqlite3.Connection) -> bool:
    row = conn.execute("PRAGMA integrity_check").fetchone()
    return bool(row and row[0] == "ok")


def backup(conn: sqlite3.Connection, dest: Path) -> Path:
    """Online backup API, then verify the copy before declaring success."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    if tmp.exists():
        tmp.unlink()
    target = sqlite3.connect(str(tmp))
    try:
        conn.backup(target)
    finally:
        target.close()
    check = sqlite3.connect(str(tmp))
    try:
        ok = check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        check.close()
    if not ok:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("backup failed integrity_check")
    tmp.replace(dest)
    return dest


def restore(backup_path: Path, dest: Path) -> None:
    """Restore by copying a verified backup into place via the backup API (never a raw file copy of a live DB)."""
    src = sqlite3.connect(str(backup_path))
    try:
        if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("refusing to restore: backup fails integrity_check")
        target = sqlite3.connect(str(dest))
        try:
            src.backup(target)
        finally:
            target.close()
    finally:
        src.close()
