"""SQLite connection, migrations and backup (ADR-0012, reliability-design.md).

Two drivers share one SQL dialect (SQLite):
* ``sqlite3`` (default, local mode): a file under the data directory.
* libSQL (hosted mode, ADR-0013): a remote Turso database (``libsql://…`` with an auth token), or a local file when
  ``IIP_DB_DRIVER=libsql`` (used by the tests to exercise the hosted driver without a network). libSQL returns plain
  tuples and has no ``row_factory``, so :class:`LibsqlConnection` adapts it to the ``sqlite3`` surface this codebase
  uses: ``row["col"]`` / ``row[0]`` / ``dict(row)``, ``execute``/``executemany``/``executescript``, ``rowcount``,
  ``lastrowid``, ``in_transaction``, ``rollback`` and ``close``. Errors are re-raised as ``sqlite3`` exceptions.
"""

from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Any, cast

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


DB_DRIVER_ENV = "IIP_DB_DRIVER"  # sqlite (default) | libsql — selects the driver for local FILES only
_REMOTE_PREFIXES = ("libsql://", "https://", "http://", "wss://", "ws://")


def connect(path: Path | str) -> sqlite3.Connection:
    if os.environ.get(DB_DRIVER_ENV, "sqlite") == "libsql":
        return connect_libsql(str(path))
    conn = sqlite3.connect(str(path), isolation_level=None, detect_types=0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    for pragma in PRAGMAS:
        conn.execute(pragma)
    return conn


def is_remote_url(database: str) -> bool:
    return database.startswith(_REMOTE_PREFIXES)


def connect_libsql(database: str, auth_token: str | None = None, *, hosted: bool = False) -> sqlite3.Connection:
    """A libSQL connection behind the ``sqlite3`` surface (typed as one: callers never see the difference).

    Remote (``libsql://``/``https://``): only ``foreign_keys`` is set — journal mode and fsync policy belong to the
    server. Local file: the same pragmas as the sqlite3 driver. ``isolation_level=None`` = autocommit, so the
    explicit ``BEGIN IMMEDIATE`` in :func:`write_tx` is the only transaction control (as with sqlite3).
    ``hosted=True`` marks the connection as the hosted store even when it is a local file (the hosted-mode tests and
    `make deploy-check`), so it gets exactly the hosted behaviour: no file backups, no VACUUM (:func:`is_remote`)."""
    import libsql  # noqa: PLC0415 - optional at import time; only hosted mode and its tests need it

    remote = is_remote_url(database)
    if remote:
        raw = libsql.connect(database, auth_token=auth_token or "", isolation_level=None)
    else:
        raw = libsql.connect(database, isolation_level=None)
    conn = LibsqlConnection(raw, remote=remote or hosted)
    for pragma in ("PRAGMA foreign_keys=ON",) if remote else PRAGMAS:
        conn.execute(pragma)
    return cast(sqlite3.Connection, conn)


def is_remote(conn: object) -> bool:
    """True for a hosted (remote libSQL) connection: no file backups, VACUUM or WAL pragmas there."""
    return bool(getattr(conn, "is_remote", False))


class Row:
    """``sqlite3.Row`` look-alike: index by position or (case-insensitive) column name; ``dict(row)`` works."""

    __slots__ = ("_index", "_keys", "_values")

    def __init__(self, keys: tuple[str, ...], index: dict[str, int], values: Sequence[Any]) -> None:
        self._keys = keys
        self._index = index
        self._values = tuple(values)

    def __getitem__(self, key: int | str | slice) -> Any:
        if isinstance(key, str):
            i = self._index.get(key)
            if i is None:
                i = self._index.get(key.lower())
            if i is None:
                raise IndexError(f"No item with that key: {key!r}")
            return self._values[i]
        return self._values[key]

    def keys(self) -> list[str]:
        return list(self._keys)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Row) and self._keys == other._keys and self._values == other._values

    __hash__ = None  # type: ignore[assignment]  # mutable-free but compared by value, like sqlite3.Row

    def __repr__(self) -> str:
        return f"Row({dict(zip(self._keys, self._values, strict=True))!r})"


def _translate(exc: Exception) -> sqlite3.Error:
    """libSQL raises its own error type; callers handle ``sqlite3`` errors. Messages are SQLite's (no bound values)."""
    msg = str(exc)
    if "constraint" in msg.lower():
        return sqlite3.IntegrityError(msg)
    return sqlite3.OperationalError(msg)


class _Cursor:
    def __init__(self, cur: Any) -> None:
        self._cur = cur
        desc = cur.description
        self.description = desc
        self._keys: tuple[str, ...] = tuple(d[0] for d in desc) if desc else ()
        index: dict[str, int] = {}
        for i, k in enumerate(self._keys):
            index.setdefault(k, i)
            index.setdefault(k.lower(), i)
        self._index = index

    def _row(self, values: Sequence[Any] | None) -> Row | None:
        return None if values is None else Row(self._keys, self._index, values)

    def fetchone(self) -> Row | None:
        return self._row(self._cur.fetchone())

    def fetchall(self) -> list[Row]:
        return [Row(self._keys, self._index, v) for v in self._cur.fetchall()]

    def fetchmany(self, size: int | None = None) -> list[Row]:
        rows = self._cur.fetchmany(size) if size is not None else self._cur.fetchmany()
        return [Row(self._keys, self._index, v) for v in rows]

    def __iter__(self) -> Iterator[Row]:
        return iter(self.fetchall())

    @property
    def rowcount(self) -> int:
        return int(self._cur.rowcount)

    @property
    def lastrowid(self) -> int | None:
        value = self._cur.lastrowid
        return None if value is None else int(value)

    def close(self) -> None:
        self._cur.close()


BUSY_RETRY_S = 10.0  # like sqlite3's busy_timeout: libSQL does not wait on a locked database, so we do


def _busy(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "database is locked" in msg or "busy" in msg


class LibsqlConnection:
    """The subset of ``sqlite3.Connection`` this codebase uses, over a libSQL connection (see module doc)."""

    def __init__(self, raw: Any, *, remote: bool) -> None:
        self._raw = raw
        self.is_remote = remote

    def _run(self, call: Callable[[], Any]) -> _Cursor:
        """Run one statement; a busy/locked database is retried with backoff for up to ``BUSY_RETRY_S`` (the
        sqlite3 driver gets the same behaviour from ``PRAGMA busy_timeout``). Other errors surface at once."""
        deadline = time.monotonic() + BUSY_RETRY_S
        delay = 0.005
        while True:
            try:
                return _Cursor(call())
            except Exception as exc:
                if isinstance(exc, sqlite3.Error):
                    raise
                if _busy(exc) and time.monotonic() < deadline:
                    time.sleep(delay)
                    delay = min(delay * 2, 0.2)
                    continue
                raise _translate(exc) from exc

    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> _Cursor:
        args = tuple(params) if isinstance(params, list) else params
        return self._run(lambda: self._raw.execute(sql, args))

    def executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> _Cursor:
        rows = [tuple(p) for p in seq]
        return self._run(lambda: self._raw.executemany(sql, rows))

    def __enter__(self) -> LibsqlConnection:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, *_: object) -> None:
        """As ``sqlite3.Connection``: commit an open transaction on success, roll it back on error."""
        if exc_type is None:
            self.commit()
        else:
            self.rollback()

    def executescript(self, script: str) -> _Cursor:
        try:
            return _Cursor(self._raw.executescript(script))
        except Exception as exc:
            raise _translate(exc) from exc

    @property
    def in_transaction(self) -> bool:
        return bool(self._raw.in_transaction)

    def commit(self) -> None:
        if self.in_transaction:
            self.execute("COMMIT")

    def rollback(self) -> None:
        if self.in_transaction:
            self.execute("ROLLBACK")

    def close(self) -> None:
        self._raw.close()

    def backup(self, *_args: object, **_kwargs: object) -> None:
        raise sqlite3.NotSupportedError("file backups are not available for a libSQL connection (ADR-0013)")


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
        if current_version(conn) >= version:  # another process (a parallel cold start) applied it first
            conn.execute("ROLLBACK")
            continue
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
