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
import re
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
    pragmas = ("PRAGMA foreign_keys=ON",) if remote else PRAGMAS

    def open_raw() -> Any:
        if remote:
            raw = libsql.connect(database, auth_token=auth_token or "", isolation_level=None)
        else:
            raw = libsql.connect(database, isolation_level=None)
        for pragma in pragmas:
            raw.execute(pragma)
        return raw

    conn = LibsqlConnection(open_raw(), remote=remote or hosted, reopen=open_raw)
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
        desc = getattr(cur, "description", None)  # None for a script (libSQL returns no cursor for one)
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
        return None if self._cur is None else self._row(self._cur.fetchone())

    def fetchall(self) -> list[Row]:
        return [] if self._cur is None else [Row(self._keys, self._index, v) for v in self._cur.fetchall()]

    def fetchmany(self, size: int | None = None) -> list[Row]:
        rows = self._cur.fetchmany(size) if size is not None else self._cur.fetchmany()
        return [Row(self._keys, self._index, v) for v in rows]

    def __iter__(self) -> Iterator[Row]:
        return iter(self.fetchall())

    @property
    def rowcount(self) -> int:
        return -1 if self._cur is None else int(self._cur.rowcount)

    @property
    def lastrowid(self) -> int | None:
        value = None if self._cur is None else self._cur.lastrowid
        return None if value is None else int(value)

    def close(self) -> None:
        if self._cur is not None:
            self._cur.close()


BUSY_RETRY_S = 10.0  # like sqlite3's busy_timeout: libSQL does not wait on a locked database, so we do


def _dropped(exc: Exception) -> bool:
    """The remote stream is gone (Turso closes idle Hrana streams; a warm serverless instance reuses its connection
    after a pause). Seen live 2026-10-15: "Hrana: `http error: `connection closed before message completed``"."""
    msg = str(exc).lower()
    return any(m in msg for m in ("connection closed", "stream not found", "stream expired", "hrana: `http error"))


def _busy(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "database is locked" in msg or "busy" in msg


class LibsqlConnection:
    """The subset of ``sqlite3.Connection`` this codebase uses, over a libSQL connection (see module doc)."""

    def __init__(self, raw: Any, *, remote: bool, reopen: Callable[[], Any] | None = None) -> None:
        self._raw = raw
        self.is_remote = remote
        self._reopen = reopen
        self._in_tx = False  # our own view: after a dropped stream the driver's flag cannot be trusted

    def _run(self, call: Callable[[Any], Any]) -> _Cursor:
        """Run one statement; a busy/locked database is retried with backoff for up to ``BUSY_RETRY_S`` (the
        sqlite3 driver gets the same behaviour from ``PRAGMA busy_timeout``). A dropped remote stream is reopened:
        outside a transaction the statement is retried ONCE on the new connection; inside one the transaction is
        already lost on the server, so the error is raised (never half-applied) and the next statement starts clean.
        Other errors surface at once."""
        deadline = time.monotonic() + BUSY_RETRY_S
        delay = 0.005
        reopened = False
        while True:
            try:
                return _Cursor(call(self._raw))
            except Exception as exc:
                if isinstance(exc, sqlite3.Error):
                    raise
                if _busy(exc) and time.monotonic() < deadline:
                    time.sleep(delay)
                    delay = min(delay * 2, 0.2)
                    continue
                if _dropped(exc) and self._reopen is not None and not reopened:
                    was_in_tx = self._in_tx
                    self._raw = self._reopen()
                    self._in_tx = False
                    reopened = True
                    if not was_in_tx:
                        continue
                raise _translate(exc) from exc

    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> _Cursor:
        args = tuple(params) if isinstance(params, list) else params
        cur = self._run(lambda raw: raw.execute(sql, args))
        head = sql.lstrip()[:8].upper()
        if head.startswith("BEGIN"):
            self._in_tx = True
        elif head.startswith(("COMMIT", "ROLLBACK", "END")):
            self._in_tx = False
        return cur

    def executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> _Cursor:
        rows = [tuple(p) for p in seq]
        return self._run(lambda raw: raw.executemany(sql, rows))

    def __enter__(self) -> LibsqlConnection:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, *_: object) -> None:
        """As ``sqlite3.Connection``: commit an open transaction on success, roll it back on error."""
        if exc_type is None:
            self.commit()
        else:
            self.rollback()

    def executescript(self, script: str) -> _Cursor:
        """Run a multi-statement script in ONE round trip. NOTE: libSQL stops at the first failing statement
        WITHOUT raising, so a caller must verify the effect (see :func:`_apply_migration`). The driver returns no
        cursor for a script, so the result carries no rows (and costs no extra round trip)."""
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


def latest_version() -> int:
    """The newest migration this code ships (reads the package files, not the database)."""
    return len(_migration_files())


def read_schema_version(conn: sqlite3.Connection) -> int:
    """The applied schema version in ONE read-only statement (RC-5: every hosted statement is a round trip).

    A database that has never been migrated has no ``schema_version`` table: that is version 0. Any other error
    (I/O, a dropped connection) is raised, never read as "not migrated"."""
    try:
        row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return 0
        raise
    return int(row["v"] or 0) if row is not None else 0


MIGRATION_WAIT_S = 60.0  # how long a cold start waits for ANOTHER instance's migration before reporting the lock


def ensure_schema(conn: sqlite3.Connection, applied_at: str, *, wait_s: float = MIGRATION_WAIT_S) -> list[str]:
    """Startup path (A05): read-only when the database is current; runs :func:`migrate` only when a migration is
    pending (a fresh local database, or the first instance after a deploy that ships a migration). Returns the
    names applied, like :func:`migrate`.

    Two instances can cold-start together after a deploy. The one that takes the write lock migrates; the other's
    lock wait (``BUSY_RETRY_S`` / ``busy_timeout``) can run out first. A busy/locked error is therefore read as
    "another instance is migrating": re-read the version and retry (the retry re-checks the version under the
    lock, so nothing is applied twice) for up to ``wait_s`` seconds. A lock that never frees is still raised."""
    deadline = time.monotonic() + wait_s
    while True:
        if read_schema_version(conn) >= latest_version():
            return []
        try:
            return migrate(conn, applied_at)
        except sqlite3.OperationalError as exc:
            if not _busy(exc) or time.monotonic() >= deadline:
                raise
            if conn.in_transaction:  # never leave this connection holding a half-open transaction
                conn.execute("ROLLBACK")
            time.sleep(0.05)


def migrate(conn: sqlite3.Connection, applied_at: str) -> list[str]:
    """Apply pending migrations in order, each in its own transaction (BEGIN IMMEDIATE, the version re-checked
    under the lock, the statements, the ``schema_version`` row, COMMIT). Returns names applied."""
    applied: list[str] = []
    if read_schema_version(conn) == 0:  # DDL only when the table may be missing: it takes the write lock
        conn.execute(_SCHEMA_VERSION_DDL)
    have = read_schema_version(conn)
    for version, name, sql in _migration_files():
        if version <= have:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            if read_schema_version(conn) >= version:  # another process (a parallel cold start) applied it first
                conn.execute("ROLLBACK")
                continue
            _apply_migration(conn, version, name, sql, applied_at)
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        applied.append(name)
    return applied


def _sql_text(value: str) -> str:
    """A SQL string literal (quotes doubled). Used only for the package-file name and the service's timestamp."""
    return "'" + value.replace("'", "''") + "'"


def _apply_migration(conn: sqlite3.Connection, version: int, name: str, sql: str, applied_at: str) -> None:
    """Apply ONE migration inside the caller's open write transaction, including its ``schema_version`` row.

    On a libSQL connection (hosted: every statement is a round trip, ~0.4 s on Turso) the statements and the
    version row go as ONE script, then ONE read verifies it. libSQL's ``executescript`` stops at the first failing
    statement WITHOUT raising (checked against the installed driver), so the version row is the script's LAST
    statement: it exists only if every statement before it ran. When it is missing the transaction is rolled back
    and re-opened, and the statements are replayed one by one to raise the real error (nothing is half-applied).
    The sqlite3 driver (local, no round-trip cost; its ``executescript`` would COMMIT the open transaction) runs
    the statements one at a time."""
    statements = _split_sql(sql)
    insert = "INSERT INTO schema_version(version, name, applied_at) VALUES (?, ?, ?)"
    if isinstance(conn, LibsqlConnection):
        # Literals, not bound values (a script takes none): an int, the package file name and the service's
        # timestamp, each quoted by _sql_text.
        row = (
            f"INSERT INTO schema_version(version, name, applied_at) VALUES ({int(version)}, {_sql_text(name)},"  # noqa: S608
            f" {_sql_text(applied_at)})"
        )
        conn.executescript(";\n".join([*statements, row]) + ";")
        if read_schema_version(conn) >= version:
            return
        conn.execute("ROLLBACK")
        conn.execute("BEGIN IMMEDIATE")
        for statement in statements:
            conn.execute(statement)
        raise MigrationError(f"{name}: the batched script stopped early but every statement ran on replay")
    for statement in statements:
        conn.execute(statement)
    conn.execute(insert, (version, name, applied_at))


_TRIGGER_START = re.compile(r"CREATE\s+(?:TEMP\s+|TEMPORARY\s+)?TRIGGER\b", re.IGNORECASE)
_TRIGGER_END = re.compile(r"\bEND$", re.IGNORECASE)


def _split_sql(sql: str) -> list[str]:
    """Split a migration on ``;``. A ``CREATE TRIGGER … BEGIN …; END`` is kept whole: its pieces are joined until one
    ends in ``END`` (so a trigger body must not contain a CASE … END expression; migration 0004 documents this)."""
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    out: list[str] = []
    pending: list[str] = []
    for piece in "\n".join(lines).split(";"):
        pending.append(piece)
        statement = ";".join(pending).strip()
        if not statement:
            pending = []
            continue
        if _TRIGGER_START.match(statement) and not _TRIGGER_END.search(statement):
            continue
        out.append(statement)
        pending = []
    if pending and ";".join(pending).strip():
        out.append(";".join(pending).strip())  # an unterminated trigger: let SQLite report it
    return out


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
