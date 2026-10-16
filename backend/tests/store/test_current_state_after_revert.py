"""Regression tests from the wave-2 ECC review (database-reviewer-01/02/03/07, python-reviewer-1), on SQLite AND
libSQL. All fixtures are synthetic.

* A policy reverted to an earlier version (A -> B -> A) becomes the latest again.
* A snapshot recomputed with reverted inputs (A -> B -> A) becomes the current snapshot again.
* Today's decision lookup is served by an index (no full scan of the append-only decision log).
* The U-01 prune of untracked NAVAll history never fails on a month-end grid point that references it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from iip.services import cron
from iip.services import ingestion as ing
from iip.services import risk_snapshot as rs
from iip.store import goals_repo as gr
from iip.store import ledger as lg

from ._ledger_fixtures import DRIVERS, NOW, open_db


@pytest.fixture(params=DRIVERS)
def db(request: pytest.FixtureRequest, tmp_path: Path) -> Any:
    conn = open_db(tmp_path / "x.db", request.param)
    yield conn
    conn.close()


def test_policy_revert_becomes_latest_again(db: Any) -> None:
    a, b = {"limits": {"c_scheme": "0.2"}}, {"limits": {"c_scheme": "0.3"}}
    va, created_a = gr.append_policy_version(db, a, "2026-10-01", NOW)
    vb, created_b = gr.append_policy_version(db, b, "2026-10-10", NOW)
    vr, created_r = gr.append_policy_version(db, a, "2026-10-16", NOW)
    assert created_a and created_b and created_r
    assert len({va, vb, vr}) == 3
    latest = gr.latest_policy_version(db)
    assert latest is not None and latest.policy == a and latest.policy_version_id == vr
    # saving the policy that is already the latest is still a no-op
    assert gr.append_policy_version(db, a, "2026-10-17", NOW) == (vr, False)


def _snap(sid: str, at: str, as_of: str = "2026-10-15") -> lg.SignalSnapshot:
    return lg.SignalSnapshot(
        snapshot_id=sid, as_of_date=as_of, engine_version="e1", rules_version="r1", input_manifest_hash=f"m-{sid}",
        verdict="ACTIONS", card_set_hash=f"c-{sid}", payload_json=f'{{"id":"{sid}"}}', created_at=at,
    )  # fmt: skip


def test_snapshot_revert_is_current_again(db: Any) -> None:
    assert lg.put_snapshot(db, _snap("s1", "2026-10-16T09:00:00+00:00"))
    assert lg.put_snapshot(db, _snap("s2", "2026-10-16T10:00:00+00:00"))
    assert not lg.put_snapshot(db, _snap("s1", "2026-10-16T11:00:00+00:00"))  # same content: no second row
    latest = lg.latest_snapshot(db)
    assert latest is not None and latest["snapshot_id"] == "s1"
    assert latest["computed_at"] == "2026-10-16T11:00:00+00:00"
    assert db.execute("SELECT COUNT(*) FROM signal_snapshots").fetchone()[0] == 2
    row = db.execute(rs.TODAY_SQL).fetchone()
    assert row["snapshot_id"] == "s1"


def test_newer_data_date_still_wins_over_a_later_recompute_of_older_data(db: Any) -> None:
    lg.put_snapshot(db, _snap("new", "2026-10-16T09:00:00+00:00", as_of="2026-10-15"))
    lg.put_snapshot(db, _snap("old", "2026-10-16T10:00:00+00:00", as_of="2026-10-14"))
    latest = lg.latest_snapshot(db)
    assert latest is not None and latest["snapshot_id"] == "new"


def test_today_decision_lookup_uses_an_index(db: Any) -> None:
    plan = " | ".join(str(r[-1]) for r in db.execute("EXPLAIN QUERY PLAN " + rs.TODAY_SQL).fetchall())
    assert "ix_decisions_log_snapshot" in plan, plan
    assert "SCAN d" not in plan.replace("SCAN d USING", "")


def _obs(db: Any, code: int, on: str, value: str) -> None:
    db.execute(
        "INSERT INTO observations(series_id, kind, value, unit, observation_date, retrieved_at, source_id, source_url,"
        " quality_status, raw_sha256) VALUES (?, 'nav', ?, 'INR', ?, ?, 'amfi.navall', 'https://example.test/x',"
        " 'ok', 'x')",
        (ing.series_id(code), value, on, NOW),
    )


def test_prune_after_unwatch_keeps_working_with_grid_points(db: Any) -> None:
    code = 900001  # fictional
    db.execute(
        "INSERT INTO instruments(instrument_id, kind, name, amfi_code, origin, created_at)"
        " VALUES (?, 'mf_scheme', 'Fictional Grid Fund', ?, 'fixture', ?)",
        (ing.instrument_id(code), str(code), NOW),
    )
    for on, v in (("2020-01-31", "10"), ("2020-02-28", "11"), ("2020-03-02", "12")):
        _obs(db, code, on, v)
    written, _skipped = cron.refresh_series_grid(db, [code], NOW)
    assert written >= 1
    assert db.execute("SELECT COUNT(*) FROM series_grid WHERE source_obs_id IS NOT NULL").fetchone()[0] >= 1
    removed = ing.prune_untracked_history(db, set())  # the scheme is no longer held or watched
    assert removed == 2
    rows = db.execute("SELECT month, nav_date, nav, source_obs_id FROM series_grid ORDER BY month").fetchall()
    assert rows and all(r["source_obs_id"] is None for r in rows if r["month"] < "2020-03")
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
