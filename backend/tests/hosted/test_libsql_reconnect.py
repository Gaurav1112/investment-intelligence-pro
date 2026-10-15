"""A dropped remote stream (Turso closes idle Hrana streams) is reopened (live failure 2026-10-15)."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from iip.store.db import LibsqlConnection

DROPPED = "Hrana: `http error: `connection closed before message completed``"


class FakeCursor:
    description = (("x", None, None, None, None, None, None),)
    rowcount = 1
    lastrowid = None

    def fetchone(self) -> tuple[int]:
        return (1,)

    def fetchall(self) -> list[tuple[int]]:
        return [(1,)]


class FakeRaw:
    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.sql: list[str] = []
        self.in_transaction = False

    def execute(self, sql: str, _args: Any = ()) -> FakeCursor:
        if self.fail_times:
            self.fail_times -= 1
            raise ValueError(DROPPED)
        self.sql.append(sql)
        return FakeCursor()


def make(first: FakeRaw, *later: FakeRaw) -> tuple[LibsqlConnection, list[FakeRaw]]:
    pool = list(later)
    opened: list[FakeRaw] = []

    def reopen() -> FakeRaw:
        raw = pool.pop(0)
        opened.append(raw)
        return raw

    return LibsqlConnection(first, remote=True, reopen=reopen), opened


def test_outside_a_transaction_the_statement_is_retried_once_on_a_new_connection() -> None:
    conn, opened = make(FakeRaw(fail_times=1), FakeRaw())
    assert conn.execute("SELECT 1").fetchone()[0] == 1
    assert len(opened) == 1 and opened[0].sql == ["SELECT 1"]


def test_inside_a_transaction_the_error_is_raised_and_the_next_statement_runs_on_a_fresh_connection() -> None:
    first = FakeRaw()
    conn, opened = make(first, FakeRaw())
    conn.execute("BEGIN IMMEDIATE")
    first.fail_times = 1
    with pytest.raises(sqlite3.OperationalError, match="connection closed"):
        conn.execute("INSERT INTO t VALUES (1)")  # the server already lost the transaction: never half-applied
    assert opened and opened[0].sql == []  # nothing replayed on the new connection
    conn.execute("SELECT 1")
    assert opened[0].sql == ["SELECT 1"]


def test_a_second_drop_in_the_same_statement_is_raised() -> None:
    conn, _ = make(FakeRaw(fail_times=1), FakeRaw(fail_times=1), FakeRaw())
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("SELECT 1")


def test_other_errors_are_not_retried() -> None:
    class Boom(FakeRaw):
        def execute(self, sql: str, _args: Any = ()) -> FakeCursor:
            raise ValueError("no such table: t")

    conn, opened = make(Boom(), FakeRaw())
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        conn.execute("SELECT * FROM t")
    assert opened == []
