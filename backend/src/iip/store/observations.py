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


def upsert_observation(
    conn: sqlite3.Connection, row: ObservationRow, *, compare_convention: bool = False
) -> UpsertOutcome:
    """Idempotent: re-ingesting the same file is a no-op; a changed value supersedes (never overwrites) the old row.

    Note: value comparison is on the exact published string, so '25.9504' vs '25.95040' (mfapi padding) is a
    correction only within the same source — different sources never supersede each other. With
    ``compare_convention`` a change of convention alone (e.g. a CPI value moving from provisional to final) is also a
    correction.
    """
    with write_tx(conn):
        current = conn.execute(
            "SELECT obs_id, value, quality_status, convention FROM observations WHERE series_id=?"
            " AND observation_date=? AND source_id=? AND superseded_by IS NULL",
            (row.series_id, row.observation_date, row.source_id),
        ).fetchone()
        if current is None:
            _insert(conn, row)
            return UpsertOutcome.INSERTED
        same_convention = not compare_convention or current["convention"] == row.convention
        if current["value"] == row.value and current["quality_status"] == row.quality_status and same_convention:
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


# Parameters per statement stay under SQLite's historic 999-variable limit, so every sqlite/libSQL build accepts them.
_MAX_PARAMS = 900
_INSERT_COLS = "obs_id, superseded_by, " + _COLUMNS
_INSERT_WIDTH = 16


def _row_values(obs_id: int, superseded_by: int | None, row: ObservationRow) -> tuple[object, ...]:
    return (
        obs_id, superseded_by, row.series_id, row.kind, row.value, row.unit, row.currency, row.observation_date,
        row.publication_time, row.retrieved_at, row.source_id, row.source_url, row.quality_status, row.convention,
        row.raw_sha256, row.ingestion_run_id,
    )  # fmt: skip


def _parts[T](seq: list[T], size: int) -> list[list[T]]:
    return [seq[i : i + size] for i in range(0, len(seq), max(1, size))]


def upsert_observations_batch(
    conn: sqlite3.Connection, rows: list[ObservationRow], *, compare_convention: bool = False
) -> list[UpsertOutcome]:
    """:func:`upsert_observation` for many rows in a FEW statements: same outcomes, same rows, same ids.

    Call inside an open :func:`write_tx`. Rows are decided in order exactly as the per-row path decides them (a later
    row sees an earlier row of the same batch), and ids are assigned as AUTOINCREMENT would assign them one at a time.
    Statements: one read of the current rows, one read of the next id, a self-point of the existing rows being
    corrected (a valid FK that frees the unique slot, as the per-row path does), multi-row inserts and one link
    update. On a remote database that is a handful of round trips per batch instead of four or five per row
    (ADR-0013).
    """
    if not rows:
        return []
    series = sorted({r.series_id for r in rows})
    dates = sorted({r.observation_date for r in rows})
    current: dict[tuple[str, str, str], tuple[int, str, str, str | None]] = {}
    for part in _parts(series, 400):
        sql = (
            "SELECT obs_id, series_id, observation_date, source_id, value, quality_status, convention"  # noqa: S608
            f" FROM observations WHERE superseded_by IS NULL AND series_id IN ({','.join('?' * len(part))})"
        )
        params: list[str] = list(part)
        if len(dates) <= 400:
            sql += f" AND observation_date IN ({','.join('?' * len(dates))})"
            params += dates
        for r in conn.execute(sql, params).fetchall():
            current[(r["series_id"], r["observation_date"], r["source_id"])] = (
                int(r["obs_id"]), r["value"], r["quality_status"], r["convention"],
            )  # fmt: skip
    top = conn.execute(
        "SELECT MAX(COALESCE((SELECT seq FROM sqlite_sequence WHERE name='observations'), 0),"
        " COALESCE((SELECT MAX(obs_id) FROM observations), 0)) AS top"
    ).fetchone()
    next_id = int(top["top"]) + 1
    outcomes: list[UpsertOutcome] = []
    new_rows: list[tuple[int, ObservationRow]] = []
    links: dict[int, int] = {}  # superseded obs_id -> the obs_id that replaced it
    for row in rows:
        key = (row.series_id, row.observation_date, row.source_id)
        cur = current.get(key)
        if cur is not None:
            same_convention = not compare_convention or cur[3] == row.convention
            if cur[1] == row.value and cur[2] == row.quality_status and same_convention:
                outcomes.append(UpsertOutcome.UNCHANGED)
                continue
            links[cur[0]] = next_id
        new_rows.append((next_id, row))
        current[key] = (next_id, row.value, row.quality_status, row.convention)
        outcomes.append(UpsertOutcome.INSERTED if cur is None else UpsertOutcome.CORRECTED)
        next_id += 1
    new_ids = {i for i, _ in new_rows}
    for ids in _parts(sorted(i for i in links if i not in new_ids), _MAX_PARAMS):
        conn.execute(
            f"UPDATE observations SET superseded_by = obs_id WHERE obs_id IN ({','.join('?' * len(ids))})",  # noqa: S608
            ids,
        )
    # Rows superseded within this batch are inserted pointing at themselves (a valid FK at statement end, and outside
    # the partial unique index), then linked below together with the pre-existing rows.
    values = [_row_values(i, i if i in links else None, r) for i, r in new_rows]
    row_marks = "(" + ",".join("?" * _INSERT_WIDTH) + ")"
    for chunk in _parts(values, _MAX_PARAMS // _INSERT_WIDTH):
        conn.execute(
            f"INSERT INTO observations({_INSERT_COLS}) VALUES {','.join(row_marks for _ in chunk)}",  # noqa: S608
            [v for t in chunk for v in t],
        )
    for pairs in _parts(sorted(links.items()), _MAX_PARAMS // 3):
        cases = " ".join("WHEN ? THEN ?" for _ in pairs)
        conn.execute(
            f"UPDATE observations SET superseded_by = CASE obs_id {cases} END"  # noqa: S608
            f" WHERE obs_id IN ({','.join('?' * len(pairs))})",
            [*(v for p in pairs for v in p), *(p[0] for p in pairs)],
        )
    return outcomes
