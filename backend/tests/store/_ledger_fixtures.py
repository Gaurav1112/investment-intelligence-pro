"""Shared synthetic fixtures for the migration-0004 store tests. Every id, name and value is fictional."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from iip.store.db import connect, connect_libsql, migrate

NOW = "2026-10-16T05:00:00+00:00"
LATER = "2026-10-17T05:00:00+00:00"
INSTRUMENTS = ("mf:990001", "mf:990002", "mf:990003")  # fictional scheme ids (no real AMFI code)
DRIVERS = ("sqlite", "libsql")


def open_db(path: Path, driver: str) -> Any:
    conn = connect_libsql(str(path)) if driver == "libsql" else connect(path)
    migrate(conn, NOW)
    conn.executemany(
        "INSERT INTO instruments(instrument_id, kind, name, origin, created_at)"
        " VALUES (?, 'mf_scheme', ?, 'fixture', ?)",
        [(i, f"Fictional Fund {n}", NOW) for n, i in enumerate(INSTRUMENTS, 1)],
    )
    return conn


class CountingConn:
    """Wraps a connection and records every statement the CALLER sends (each one is a round trip on a remote
    database). Trigger work inside the database is not counted. BEGIN/COMMIT/ROLLBACK are excluded."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self.seen: list[str] = []

    def execute(self, sql: str, params: Any = ()) -> Any:
        if not sql.lstrip().upper().startswith(("BEGIN", "COMMIT", "ROLLBACK")):
            self.seen.append(sql)
        return self._conn.execute(sql, params)

    @property
    def in_transaction(self) -> bool:
        return bool(self._conn.in_transaction)
