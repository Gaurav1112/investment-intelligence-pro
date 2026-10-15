"""Cross-instance coordination in the database (hosted mode, ADR-0013).

Serverless instances share no memory, so the per-source refresh limit (SEC-86 / C-16), the single-backfill lock and
the progress of resumable jobs live in tables created by migration 0003. Every claim is ONE conditional statement —
atomic in SQLite and libSQL — so two instances can never both win, and no interactive transaction is held open over
the network. Times are epoch seconds from the caller's clock (tests inject it).
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from collections.abc import Callable
from types import TracebackType
from typing import Any


def claim_refresh(conn: sqlite3.Connection, key: str, now: float, interval_s: float) -> int | None:
    """Reserve ``key``'s manual-refresh slot. None = granted; otherwise the whole seconds left to wait."""
    cur = conn.execute(
        "INSERT INTO refresh_claims(source_key, claimed_at) VALUES (?, ?)"
        " ON CONFLICT(source_key) DO UPDATE SET claimed_at=excluded.claimed_at"
        " WHERE refresh_claims.claimed_at <= ?",
        (key, now, now - interval_s),
    )
    if int(cur.rowcount) == 1:
        return None
    row = conn.execute("SELECT claimed_at FROM refresh_claims WHERE source_key=?", (key,)).fetchone()
    last = float(row["claimed_at"]) if row is not None else now
    return int(interval_s - (now - last)) + 1


class DbLease:
    """A named lock held in the database with an expiry, shaped like ``threading.Lock`` (``acquire(blocking=False)``,
    ``release()``, ``with``). A function killed at its time limit never releases, so the lease lapses after
    ``ttl_s`` instead. Only non-blocking acquisition is supported: the caller answers "busy" rather than waiting."""

    def __init__(self, conn: Callable[[], sqlite3.Connection], name: str, ttl_s: float, clock: Callable[[], float]):
        self._conn = conn
        self.name = name
        self.ttl_s = ttl_s
        self._clock = clock
        self._holder: str | None = None
        self._local = threading.Lock()

    def acquire(self, blocking: bool = False) -> bool:
        if blocking:
            raise ValueError("DbLease supports non-blocking acquisition only")
        holder = secrets.token_hex(16)
        now = self._clock()
        cur = self._conn().execute(
            "INSERT INTO leases(name, holder, expires_at) VALUES (?, ?, ?)"
            " ON CONFLICT(name) DO UPDATE SET holder=excluded.holder, expires_at=excluded.expires_at"
            " WHERE leases.expires_at <= ?",
            (self.name, holder, now + self.ttl_s, now),
        )
        if int(cur.rowcount) != 1:
            return False
        with self._local:
            self._holder = holder
        return True

    def release(self) -> None:
        with self._local:
            holder, self._holder = self._holder, None
        if holder is not None:
            self._conn().execute("DELETE FROM leases WHERE name=? AND holder=?", (self.name, holder))

    def __enter__(self) -> DbLease:
        if not self.acquire(blocking=False):
            raise RuntimeError(f"lease {self.name!r} is held elsewhere")
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.release()


def load_job(conn: sqlite3.Connection, job_key: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT state_json FROM job_progress WHERE job_key=?", (job_key,)).fetchone()
    return None if row is None else dict(json.loads(row["state_json"]))


def save_job(conn: sqlite3.Connection, job_key: str, state: dict[str, Any], now_iso: str) -> None:
    conn.execute(
        "INSERT INTO job_progress(job_key, state_json, updated_at) VALUES (?, ?, ?)"
        " ON CONFLICT(job_key) DO UPDATE SET state_json=excluded.state_json, updated_at=excluded.updated_at",
        (job_key, json.dumps(state, sort_keys=True), now_iso),
    )


def clear_job(conn: sqlite3.Connection, job_key: str) -> None:
    conn.execute("DELETE FROM job_progress WHERE job_key=?", (job_key,))


def clear_jobs(conn: sqlite3.Connection, job_key: str, prefix: str) -> None:
    """Delete a job row and every row whose key starts with ``prefix`` (its staged parts) in one statement."""
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    conn.execute("DELETE FROM job_progress WHERE job_key=? OR job_key LIKE ? ESCAPE '\\'", (job_key, escaped + "%"))
