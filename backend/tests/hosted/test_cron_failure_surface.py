"""silent-failure-hunter-02 (d), verifier round close: a J3/J4 failure and a J5 ATTENTION finding must reach an API and
UI surface even when no notification channel is configured (default_hooks: channels=(), sender=None). They are listed
by ``GET /api/data-health/jobs`` and raised by the alert rule that already covers failed ingestion runs. Synthetic
fixtures only (fictional scheme codes); on SQLite and libSQL."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from iip.services import alerts, cron
from iip.store import ledger
from iip.supervisor import compliance

from .test_cron import J1_TIME, Amfi, Clock, ctx_for, hooks, open_conn

QUIET = {"channels": (), "sender": None}  # the default hooks when notify is not configured


@pytest.fixture(params=("sqlite", "libsql"))
def conn(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = open_conn(tmp_path / "surface.db", request.param)
    yield c
    c.close()


def _crashing_snapshot(_c: sqlite3.Connection, _now: datetime) -> cron.SnapshotOutcome:
    raise RuntimeError("synthetic snapshot crash")


def _evaluate(conn: sqlite3.Connection, at: datetime) -> list[dict[str, object]]:
    out = alerts.evaluate(conn, at, tax_coverage_to=None, tax_rules_loaded=True)
    return [a for a in out["created"] if a["kind"] == "scheduled_job_failed"]


def test_a_j4_snapshot_failure_with_no_channel_is_listed_and_alerted(conn: sqlite3.Connection) -> None:
    amfi = Amfi()
    cron.run_job(ctx_for(conn, amfi, hooks(**QUIET)), "navall")
    at = J1_TIME + timedelta(hours=4)
    res = cron.run_job(ctx_for(conn, amfi, hooks(snapshot=_crashing_snapshot, **QUIET), clock=Clock(at)), "snapshot")
    assert (res.state, res.code) == ("failed", "SNAPSHOT_FAILED")

    problems = ledger.recent_cron_problems(conn, (at - timedelta(days=14)).isoformat())
    assert [(p["job"], p["state"], p["detail_code"]) for p in problems] == [("snapshot", "failed", "SNAPSHOT_FAILED")]

    found = _evaluate(conn, at)
    assert len(found) == 1
    msg = str(found[0]["message"])
    assert msg.startswith("Your rule “ingestion run failed” triggered:") and "snapshot" in msg
    assert "SNAPSHOT_FAILED" in msg and "synthetic snapshot crash" not in msg  # codes only, never the message
    assert compliance.blocked(msg) == []
    assert _evaluate(conn, at) == []  # re-evaluating never duplicates


def test_a_j5_attention_with_no_channel_is_listed_and_alerted(conn: sqlite3.Connection) -> None:
    at = J1_TIME + timedelta(hours=14)  # no snapshot stored: J5 finds SNAPSHOT_MISSING
    res = cron.run_job(ctx_for(conn, Amfi(), hooks(**QUIET), clock=Clock(at)), "watchdog")
    assert res.code == "ATTENTION" and res.counts["pings_queued"] == 0  # nothing is sent anywhere

    problems = ledger.recent_cron_problems(conn, (at - timedelta(days=14)).isoformat())
    assert [p["job"] for p in problems] == ["watchdog"]
    assert str(problems[0]["detail_code"]).startswith("ATTENTION;")

    found = _evaluate(conn, at)
    assert len(found) == 1 and "SNAPSHOT_MISSING" in str(found[0]["message"])


def test_healthy_and_old_runs_are_not_listed(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO cron_runs(job, run_key, state, started_at, detail_code) VALUES"
        " ('navall', '2026-10-14', 'done', ?, 'STORED'),"
        " ('watchdog', '2026-10-14', 'done', ?, 'HEALTHY'),"
        " ('history', 'attempt:2026-09-01', 'failed', '2026-09-01T00:00:00+00:00', 'INTERNAL_ERROR')",
        (J1_TIME.isoformat(), J1_TIME.isoformat()),
    )
    assert ledger.recent_cron_problems(conn, (J1_TIME - timedelta(days=14)).isoformat()) == []
