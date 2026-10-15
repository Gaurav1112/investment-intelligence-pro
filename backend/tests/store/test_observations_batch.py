"""Differential test: the batched observation upsert (ADR-0013 hosted NAVAll) must store EXACTLY what the per-row
`upsert_observation` stores — same rows, same ids, same superseded links, same outcomes — for any sequence of
new rows, identical repeats, same-source corrections and other-source rows, split into any batches."""

from __future__ import annotations

import itertools
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from iip.store.db import connect, connect_libsql, migrate, write_tx
from iip.store.observations import ObservationRow, upsert_observation, upsert_observations_batch

NOW = "2026-10-15T00:00:00+00:00"


def _row(s: str, d: str, src: str, v: str, q: str, c: str) -> ObservationRow:
    return ObservationRow(
        series_id=s, kind="nav", value=v, unit="INR_per_unit", currency="INR", observation_date=d, retrieved_at=NOW,
        source_id=src, source_url=f"https://example.test/{src}", quality_status=q, raw_sha256="0" * 64, convention=c,
    )  # fmt: skip


ROW = st.builds(
    _row,
    st.sampled_from(["nav:900001", "nav:900002"]),
    st.sampled_from(["2026-10-13", "2026-10-14"]),
    st.sampled_from(["amfi.navall", "amfi.navhistory"]),
    st.sampled_from(["10.5", "10.50", "11.0"]),
    st.sampled_from(["ok", "suspect"]),
    st.sampled_from(["NAV_PER_UNIT_AS_PUBLISHED", "OTHER"]),
)


def _open(path: Path, driver: str) -> Any:
    c = connect_libsql(str(path)) if driver == "libsql" else connect(path)
    migrate(c, NOW)
    return c


def _dump(c: Any) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    rows = [tuple(r) for r in c.execute("SELECT * FROM observations ORDER BY obs_id")]
    seq = [tuple(r) for r in c.execute("SELECT name, seq FROM sqlite_sequence WHERE name='observations'")]
    return rows, seq


@pytest.mark.parametrize("driver", ["sqlite", "libsql"])
@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    before=st.lists(ROW, max_size=6),
    after=st.lists(ROW, min_size=1, max_size=14),
    cuts=st.lists(st.integers(min_value=1, max_value=14), max_size=3),
    compare_convention=st.booleans(),
    deleted_top=st.booleans(),
)
def test_batched_upsert_equals_per_row_upsert(
    driver: str, before: list[ObservationRow], after: list[ObservationRow], cuts: list[int], compare_convention: bool,
    deleted_top: bool,
) -> None:  # fmt: skip
    with tempfile.TemporaryDirectory() as tmp:
        one, many = _open(Path(tmp) / "one.db", driver), _open(Path(tmp) / "many.db", driver)
        for c in (one, many):  # identical history, possibly with the highest id deleted (AUTOINCREMENT never reuses)
            for r in before:
                upsert_observation(c, r)
            if deleted_top and before:
                c.execute("DELETE FROM observations WHERE obs_id = (SELECT MAX(obs_id) FROM observations)"
                          " AND superseded_by IS NULL AND obs_id NOT IN (SELECT superseded_by FROM observations"
                          " WHERE superseded_by IS NOT NULL)")  # fmt: skip
        expected = [upsert_observation(one, r, compare_convention=compare_convention) for r in after]
        got = []
        bounds = sorted({0, len(after), *(min(c, len(after)) for c in cuts)})
        for lo, hi in itertools.pairwise(bounds):
            with write_tx(many):
                got += upsert_observations_batch(many, after[lo:hi], compare_convention=compare_convention)
        assert got == expected
        assert _dump(many) == _dump(one)
        assert many.execute("PRAGMA foreign_key_check").fetchall() == []
        one.close()
        many.close()


def test_batch_uses_a_bounded_number_of_statements(tmp_path: Path) -> None:
    """500 new rows across 500 series: a constant handful of statements, not ~4 per row. (Counted with sqlite3's
    trace callback, so this test always uses the sqlite3 driver; the equivalence test above covers libSQL.)"""
    c = sqlite3.connect(str(tmp_path / "x.db"), isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    migrate(c, NOW)
    seen: list[str] = []
    c.set_trace_callback(seen.append)
    rows = [ObservationRow(series_id=f"nav:{900000 + i}", kind="nav", value="10.5", unit="INR_per_unit",
                           currency="INR", observation_date="2026-10-14", retrieved_at=NOW, source_id="amfi.navall",
                           source_url="https://example.test/n", quality_status="ok", raw_sha256="0" * 64)
            for i in range(500)]  # fmt: skip
    with write_tx(c):
        assert set(upsert_observations_batch(c, rows)) == {"inserted"}
    statements = [s for s in seen if not s.startswith(("BEGIN", "COMMIT"))]
    # 2 current-row reads (400 series per read) + 1 id read + ceil(500 / 56) = 9 inserts
    assert len(statements) <= 12, statements[:3]
    assert c.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 500


def test_batch_rolls_back_with_its_transaction(tmp_path: Path) -> None:
    c = connect(tmp_path / "x.db")
    migrate(c, NOW)
    row = ObservationRow(series_id="nav:900001", kind="nav", value="1", unit="INR_per_unit", currency="INR",
                         observation_date="2026-10-14", retrieved_at=NOW, source_id="amfi.navall",
                         source_url="https://example.test/n", quality_status="ok", raw_sha256="0" * 64)  # fmt: skip
    with pytest.raises(sqlite3.IntegrityError), write_tx(c):
        upsert_observations_batch(c, [row])
        c.execute("INSERT INTO observations(obs_id) VALUES (NULL)")  # NOT NULL columns → IntegrityError
    assert c.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
