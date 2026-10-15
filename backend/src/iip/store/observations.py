"""Observation repository: idempotent upserts and source corrections that keep history (reliability-design.md)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from iip.store.db import write_tx


class UpsertOutcome(StrEnum):
    INSERTED = "inserted"
    UNCHANGED = "unchanged"  # identical value already current → idempotent no-op
    CORRECTED = "corrected"  # source published a different value for the same date → old row superseded


@dataclass(frozen=True)
class ObservationRow:
    series_id: str
    kind: str
    value: str  # Decimal string exactly as published
    unit: str
    currency: str | None
    observation_date: str
    retrieved_at: str
    source_id: str
    source_url: str
    quality_status: str
    raw_sha256: str
    convention: str | None = None
    publication_time: str | None = None
    ingestion_run_id: str | None = None


_COLUMNS = (
    "series_id, kind, value, unit, currency, observation_date, publication_time, retrieved_at, source_id,"
    " source_url, quality_status, convention, raw_sha256, ingestion_run_id"
)


def _insert(conn: sqlite3.Connection, row: ObservationRow) -> int:
    cur = conn.execute(
        f"INSERT INTO observations({_COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",  # noqa: S608 - constant columns
        (
            row.series_id,
            row.kind,
            row.value,
            row.unit,
            row.currency,
            row.observation_date,
            row.publication_time,
            row.retrieved_at,
            row.source_id,
            row.source_url,
            row.quality_status,
            row.convention,
            row.raw_sha256,
            row.ingestion_run_id,
        ),
    )
    return int(cur.lastrowid or 0)


def upsert_observation(conn: sqlite3.Connection, row: ObservationRow) -> UpsertOutcome:
    """Idempotent: re-ingesting the same file is a no-op; a changed value supersedes (never overwrites) the old row.

    Note: value comparison is on the exact published string, so '25.9504' vs '25.95040' (mfapi padding) is a
    correction only within the same source — different sources never supersede each other.
    """
    with write_tx(conn):
        current = conn.execute(
            "SELECT obs_id, value, quality_status FROM observations WHERE series_id=? AND observation_date=?"
            " AND source_id=? AND superseded_by IS NULL",
            (row.series_id, row.observation_date, row.source_id),
        ).fetchone()
        if current is None:
            _insert(conn, row)
            return UpsertOutcome.INSERTED
        if current["value"] == row.value and current["quality_status"] == row.quality_status:
            return UpsertOutcome.UNCHANGED
        old_id = int(current["obs_id"])
        # Temporarily point the old row at itself (a valid FK) so the partial unique index frees the slot.
        conn.execute("UPDATE observations SET superseded_by = obs_id WHERE obs_id = ?", (old_id,))
        new_id = _insert(conn, row)
        conn.execute("UPDATE observations SET superseded_by = ? WHERE obs_id = ?", (new_id, old_id))
        return UpsertOutcome.CORRECTED


def current_series(
    conn: sqlite3.Connection,
    series_id: str,
    source_id: str | None = None,
    statuses: tuple[str, ...] = ("ok", "manual", "fixture"),
) -> list[sqlite3.Row]:
    """Current (non-superseded) observations ordered by date. Rejected/suspect/stale rows are excluded by default."""
    placeholders = ",".join("?" for _ in statuses)
    sql = (
        f"SELECT * FROM observations WHERE series_id=? AND superseded_by IS NULL"  # noqa: S608
        f" AND quality_status IN ({placeholders})"
    )
    params: list[str] = [series_id, *statuses]
    if source_id is not None:
        sql += " AND source_id=?"
        params.append(source_id)
    sql += " ORDER BY observation_date"
    return list(conn.execute(sql, params).fetchall())
