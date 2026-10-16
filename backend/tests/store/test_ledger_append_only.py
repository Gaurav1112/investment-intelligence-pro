"""Append-only ledgers of migration 0004 (PLAN.md wave 2, A10), on SQLite AND libSQL: the triggers refuse UPDATE of
frozen columns and DELETE (backtest_trials: params or snapshot hash), the sanctioned erase is the only way out, the
repositories are idempotent where the cron needs it, refuse conflicting re-writes, and batch their writes. All
fixtures are synthetic."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from iip.store import ledger as lg
from iip.store.db import write_tx

from ._ledger_fixtures import DRIVERS, INSTRUMENTS, LATER, NOW, CountingConn, open_db

APPEND_ONLY = pytest.raises(sqlite3.IntegrityError, match="append-only")


@pytest.fixture(params=DRIVERS)
def db(request: pytest.FixtureRequest, tmp_path: Path) -> Any:
    conn = open_db(tmp_path / "x.db", request.param)
    yield conn
    conn.close()


def _trial(i: int = 1, family: str = "trend_timing") -> lg.BacktestTrial:
    return lg.BacktestTrial(
        trial_id=f"t{i}", rule_id="S-E", version=1, family=family, params_json='{"lookback":10}',
        universe_id="u1", horizon="1m", benchmark_id="bench", data_snapshot_hash="a" * 64, code_version="c1",
        rules_version="r1", seed="0", status="active", created_at=NOW,
    )  # fmt: skip


def _eval(scope: str = "goal:g1", date: str = "2026-10-15", h: str = "h1") -> lg.RuleEvaluation:
    return lg.RuleEvaluation(
        rule_id="S-E", version=1, as_of_date=date, scope_id=scope, state="PRE_REGISTERED", condition_met=None,
        payload_json="{}", input_hash=h, snapshot_id="snap1", evaluated_at=NOW,
    )  # fmt: skip


def _snap(sid: str = "snap1", payload: str = '{"cards":[]}', as_of: str = "2026-10-15") -> lg.SignalSnapshot:
    return lg.SignalSnapshot(
        snapshot_id=sid, as_of_date=as_of, engine_version="e1", rules_version="r1", input_manifest_hash="m",
        verdict="ABSTAIN", card_set_hash="c", payload_json=payload, created_at=NOW,
    )  # fmt: skip


def _rule(spec_hash: str = "h1") -> lg.SignalRule:
    return lg.SignalRule(
        rule_id="S-E", version=1, class_="S", family="trend_timing", spec_yaml="id: S-E", spec_hash=spec_hash,
        registered_at=NOW, state="PRE_REGISTERED", state_reason=None, state_changed_at=NOW,
    )  # fmt: skip


def _seed_everything(db: Any) -> None:
    from iip.store import goals_repo as gr

    lg.register_rules(db, [_rule()])
    lg.bind_roles(db, [lg.RoleBinding("index_fund.broad.direct", INSTRUMENTS[0], "longest_history", NOW)])
    lg.append_trials(db, [_trial(1)])
    lg.append_backtest_runs(db, [lg.BacktestRun("run1", "t1", "{}", "o", "{}", "{}", "ABSTAIN", 0, NOW)])
    lg.put_snapshot(db, _snap())
    lg.append_rule_evaluations(db, [_eval()])
    lg.append_outcomes(db, [lg.Outcome("S-E", 1, "2026-10-15", "goal:g1", "2026-11-15", "unscorable", None,
                                       "nav_missing", "i1", NOW)])  # fmt: skip
    lg.append_decisions(db, [lg.Decision("card1", "snap1", "g1", "done", None, NOW)])
    lg.append_restatements(db, [lg.Restatement("nav:990001", "src", "h1", "h2", None, 1, NOW)])
    lg.upsert_series_grid(db, [lg.GridPoint(INSTRUMENTS[0], "2026-09", "2026-09-30", Decimal("10.5"), None, NOW)])
    lg.claim_cron_run(db, "snapshot", "2026-10-15", NOW, NOW)
    lg.enqueue_ping(db, "snap1", "webpush", "report", "snap1", NOW)
    pv, _ = gr.append_policy_version(db, {"band": "0.05"}, "2026-10-16", NOW)
    gr.upsert_goals(db, [gr.Goal("g1", "Fictional goal", 1, policy_version_id=pv)], NOW)
    gr.replace_goal_map(db, [gr.GoalLink(INSTRUMENTS[0], "F1", "g1", Decimal("1"))], NOW)
    gr.set_risk_profile(db, gr.RiskProfile(emergency_months=6), NOW)
    gr.set_tax_context(db, gr.TaxContext("2026-27"), NOW)


# ----------------------------------------------------------------------------------------- backtest_trials


def test_trial_params_and_snapshot_hash_can_never_change(db: Any) -> None:
    lg.append_trials(db, [_trial()])
    with APPEND_ONLY:
        db.execute("UPDATE backtest_trials SET params_json='{\"lookback\":11}' WHERE trial_id='t1'")
    with APPEND_ONLY:
        db.execute("UPDATE backtest_trials SET data_snapshot_hash=? WHERE trial_id='t1'", ("b" * 64,))
    with APPEND_ONLY:
        db.execute("UPDATE backtest_trials SET family='other' WHERE trial_id='t1'")
    row = db.execute("SELECT params_json, data_snapshot_hash FROM backtest_trials").fetchone()
    assert (row[0], row[1]) == ('{"lookback":10}', "a" * 64)


def test_trials_can_never_be_deleted_or_overwritten(db: Any) -> None:
    lg.append_trials(db, [_trial()])
    with APPEND_ONLY:
        db.execute("DELETE FROM backtest_trials")
    with pytest.raises(sqlite3.IntegrityError):
        lg.append_trials(db, [_trial()])  # same trial id: the log never overwrites
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT OR REPLACE INTO backtest_trials SELECT * FROM backtest_trials")  # REPLACE = delete
    assert lg.count_trials(db, "trend_timing") == 1


def test_trial_results_are_filled_in_after_the_run(db: Any) -> None:
    lg.append_trials(db, [_trial()])
    assert lg.record_trial_result(
        db, "t1", oos_edge_hash="e", n_periods=12, sr_hat=Decimal("0.10"), skew=Decimal("-0.2"),
        kurt=Decimal("3.1"), status="retired",
    )  # fmt: skip
    row = db.execute("SELECT n_periods, sr_hat, status FROM backtest_trials").fetchone()
    assert (row[0], row[1], row[2]) == (12, "0.10", "retired")


def test_trial_count_per_family(db: Any) -> None:
    lg.append_trials(db, [_trial(1), _trial(2), _trial(3, family="dual_momentum")])
    assert lg.count_trials(db, "trend_timing") == 2 and lg.count_trials(db, "dual_momentum") == 1


# ----------------------------------------------------------------------------------------- other ledgers


@pytest.mark.parametrize(
    "table, update",
    [
        ("backtest_runs", "UPDATE backtest_runs SET verdict='ACCEPTED'"),
        ("rule_evaluations", "UPDATE rule_evaluations SET condition_met=1"),
        ("outcomes", "UPDATE outcomes SET status='scored', edge_after_cost_tax='1', unscorable_reason=NULL"),
        ("signal_snapshots", "UPDATE signal_snapshots SET verdict='REPORT'"),
        ("restatements", "UPDATE restatements SET rows_changed=0"),
        ("policy_versions", "UPDATE policy_versions SET decided_at='2020-01-01'"),
        ("decisions_log", "UPDATE decisions_log SET decision='disagree'"),
        ("decisions_log", "UPDATE decisions_log SET note='rewritten'"),
        ("signal_rules", "UPDATE signal_rules SET spec_hash='other'"),
        ("signal_rules", "UPDATE signal_rules SET spec_yaml='id: S-E2'"),
    ],
)
def test_ledgers_refuse_updates(db: Any, table: str, update: str) -> None:
    _seed_everything(db)
    before = [tuple(r) for r in db.execute(f"SELECT * FROM {table}")]
    with APPEND_ONLY:
        db.execute(update)
    assert [tuple(r) for r in db.execute(f"SELECT * FROM {table}")] == before


@pytest.mark.parametrize(
    "table",
    ["backtest_runs", "rule_evaluations", "outcomes", "signal_snapshots", "restatements", "policy_versions",
     "decisions_log", "signal_rules", "backtest_trials"],
)  # fmt: skip
def test_ledgers_refuse_deletes(db: Any, table: str) -> None:
    _seed_everything(db)
    n = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    assert n >= 1
    with APPEND_ONLY:
        db.execute(f"DELETE FROM {table}")
    assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == n


def test_rule_state_may_change_but_not_the_spec(db: Any) -> None:
    lg.register_rules(db, [_rule()])
    assert lg.set_rule_state(db, "S-E", 1, "ABSTAIN", "gate_not_implemented", LATER)
    assert db.execute("SELECT state FROM signal_rules").fetchone()[0] == "ABSTAIN"
    assert lg.register_rules(db, [_rule()]) == 0  # idempotent
    with pytest.raises(lg.LedgerConflict):
        lg.register_rules(db, [_rule(spec_hash="h2")])  # a changed spec must be a new version


def test_cas_confirmation_is_set_once(db: Any) -> None:
    lg.append_decisions(db, [lg.Decision("card1", "snap1", "g1", "done", "fictional note", NOW),
                             lg.Decision("card2", "snap1", "g1", "not_now", None, NOW)])  # fmt: skip
    ids = [int(r[0]) for r in db.execute("SELECT decision_id FROM decisions_log ORDER BY decision_id")]
    # only 'done' rows are confirmable; the not_now row is skipped
    assert lg.confirm_decisions_from_cas(db, [(ids[0], True), (ids[1], True)], LATER, "cas-import-1") == 1
    assert lg.confirm_decisions_from_cas(db, [(ids[0], False)], LATER, "cas-import-2") == 0  # already checked
    with APPEND_ONLY:
        db.execute("UPDATE decisions_log SET cas_confirmed=0 WHERE decision_id=?", (ids[0],))
    row = db.execute("SELECT cas_confirmed, cas_import_ref FROM decisions_log WHERE decision_id=?", (ids[0],))
    assert tuple(row.fetchone()) == (1, "cas-import-1")


# ----------------------------------------------------------------------------------------- erase (SEC-81)


def test_erase_is_the_only_way_out_and_closes_the_gate(db: Any) -> None:
    _seed_everything(db)
    with write_tx(db):
        counts = lg.erase_user_rows(db)
    assert counts["backtest_trials"] == 1 and counts["goals"] == 1 and counts["decisions_log"] == 1
    for t in lg.USER_TABLES_0004:
        assert db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0, t
    for t in lg.PUBLIC_TABLES_0004:
        assert db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] >= 1, t  # market-derived data and specs kept
    assert db.execute("SELECT COUNT(*) FROM ledger_erase_gate").fetchone()[0] == 0
    lg.append_trials(db, [_trial(9)])
    with APPEND_ONLY:  # the gate is closed again
        db.execute("DELETE FROM backtest_trials")


def test_erase_outside_a_transaction_is_refused(db: Any) -> None:
    _seed_everything(db)
    with pytest.raises(RuntimeError, match="write transaction"):
        lg.erase_user_rows(db)
    assert db.execute("SELECT COUNT(*) FROM backtest_trials").fetchone()[0] == 1


def test_a_failed_erase_rolls_back_the_gate_too(db: Any) -> None:
    _seed_everything(db)
    with pytest.raises(RuntimeError, match="boom"), write_tx(db):
        lg.erase_user_rows(db)
        raise RuntimeError("boom")
    assert db.execute("SELECT COUNT(*) FROM backtest_trials").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM ledger_erase_gate").fetchone()[0] == 0


def test_erase_lists_every_new_table(db: Any) -> None:
    from .test_migration_0004 import PLAN_TABLES

    assert set(lg.USER_TABLES_0004) | set(lg.PUBLIC_TABLES_0004) == PLAN_TABLES
    assert not set(lg.USER_TABLES_0004) & set(lg.PUBLIC_TABLES_0004)


# ----------------------------------------------------------------------------------------- shadow ledger


def test_rule_evaluations_are_idempotent_and_refuse_conflicting_rewrites(db: Any) -> None:
    rows = [_eval("goal:g1"), _eval("goal:g2")]
    assert lg.append_rule_evaluations(db, rows) == 2
    assert lg.append_rule_evaluations(db, rows) == 0  # a duplicate cron delivery writes nothing
    with pytest.raises(lg.LedgerConflict):
        lg.append_rule_evaluations(db, [_eval("goal:g3"), _eval("goal:g1", h="different")])
    assert db.execute("SELECT COUNT(*) FROM rule_evaluations").fetchone()[0] == 2  # nothing of the batch written
    with pytest.raises(lg.LedgerConflict):  # a conflict inside one batch
        lg.append_rule_evaluations(db, [_eval("goal:g4"), _eval("goal:g4", h="other")])


def test_outcomes_are_scored_once_against_their_evaluation(db: Any) -> None:
    lg.append_rule_evaluations(db, [_eval("goal:g1"), _eval("goal:g2")])
    assert [r["scope_id"] for r in lg.unscored_evaluations(db, "2026-10-16")] == ["goal:g1", "goal:g2"]
    out = lg.Outcome("S-E", 1, "2026-10-15", "goal:g1", "2026-11-15", "scored", Decimal("-0.0042"), None, "i1", NOW)
    assert lg.append_outcomes(db, [out]) == 1
    assert lg.append_outcomes(db, [out]) == 0
    with pytest.raises(lg.LedgerConflict):
        lg.append_outcomes(db, [lg.Outcome("S-E", 1, "2026-10-15", "goal:g1", "2026-11-15", "scored",
                                           Decimal("0.01"), None, "i2", NOW)])  # fmt: skip
    assert [r["scope_id"] for r in lg.unscored_evaluations(db, "2026-10-16")] == ["goal:g2"]
    assert db.execute("SELECT edge_after_cost_tax FROM outcomes").fetchone()[0] == "-0.0042"


@pytest.mark.parametrize("driver", DRIVERS)
def test_shadow_ledger_batches_its_writes(tmp_path: Path, driver: str) -> None:
    db = CountingConn(open_db(tmp_path / "x.db", driver))
    rows = [_eval(f"role:r{i}") for i in range(1000)]
    with write_tx(db):  # type: ignore[arg-type]
        assert lg.append_rule_evaluations(db, rows) == 1000  # type: ignore[arg-type]
    # reads: ceil(1000 / 225) = 5; inserts: ceil(1000 / 90) = 12 — not one or more per row
    assert len(db.seen) == 17, len(db.seen)
    db.seen.clear()
    with write_tx(db):  # type: ignore[arg-type]
        assert lg.append_rule_evaluations(db, rows) == 0  # type: ignore[arg-type]
    assert len(db.seen) == 5


def test_non_finite_decimals_are_refused(db: Any) -> None:
    with pytest.raises(ValueError, match="finite"):
        lg.upsert_series_grid(db, [lg.GridPoint(INSTRUMENTS[0], "2026-09", "2026-09-30", Decimal("NaN"), None, NOW)])


# ----------------------------------------------------------------------------------------- snapshots


def test_snapshots_are_content_addressed(db: Any) -> None:
    assert lg.put_snapshot(db, _snap("s1", as_of="2026-10-14"))
    assert not lg.put_snapshot(db, _snap("s1", as_of="2026-10-14"))  # duplicate J4 run: no-op
    with pytest.raises(lg.LedgerConflict):
        lg.put_snapshot(db, _snap("s1", payload='{"cards":["x"]}', as_of="2026-10-14"))
    assert lg.put_snapshot(db, _snap("s2", as_of="2026-10-15"))
    latest = lg.latest_snapshot(db)
    assert latest is not None and latest["snapshot_id"] == "s2"


def test_today_reads_the_snapshot_in_one_statement(db: Any) -> None:
    lg.put_snapshot(db, _snap())
    counting = CountingConn(db)
    assert lg.latest_snapshot(counting) is not None  # type: ignore[arg-type]
    assert len(counting.seen) == 1


# ----------------------------------------------------------------------------------------- series grid


def test_series_grid_upsert_skips_unchanged_points(db: Any) -> None:
    pts = [
        lg.GridPoint(i, m, f"{m}-28", Decimal("10.25"), None, NOW) for i in INSTRUMENTS for m in ("2026-08", "2026-09")
    ]
    assert lg.upsert_series_grid(db, pts) == 6
    assert lg.upsert_series_grid(db, pts) == 0  # nothing rewritten
    changed = lg.GridPoint(INSTRUMENTS[0], "2026-09", "2026-09-30", Decimal("10.30"), None, LATER)
    assert lg.upsert_series_grid(db, [changed]) == 1
    grid = lg.series_grid(db, [INSTRUMENTS[0], "mf:missing"])
    assert grid[INSTRUMENTS[0]] == [("2026-08", Decimal("10.25")), ("2026-09", Decimal("10.30"))]
    assert grid["mf:missing"] == []


# ----------------------------------------------------------------------------------------- cron and outbox


def test_cron_claim_duplicate_is_a_noop_and_stale_runs_are_taken_over(db: Any) -> None:
    t0, t1, t2 = "2026-10-16T05:00:00+00:00", "2026-10-16T05:02:00+00:00", "2026-10-16T05:20:00+00:00"
    assert lg.claim_cron_run(db, "snapshot", "2026-10-15", t0, "2026-10-16T04:54:30+00:00")
    assert not lg.claim_cron_run(db, "snapshot", "2026-10-15", t1, "2026-10-16T04:56:30+00:00")  # live: no-op
    assert lg.claim_cron_run(db, "snapshot", "2026-10-15", t2, "2026-10-16T05:14:30+00:00")  # killed run: takeover
    assert db.execute("SELECT attempts FROM cron_runs").fetchone()[0] == 2
    assert lg.finish_cron_run(db, "snapshot", "2026-10-15", "failed", t2, "E_FETCH")
    assert lg.claim_cron_run(db, "snapshot", "2026-10-15", t2, t0)  # failed: retried
    assert lg.finish_cron_run(db, "snapshot", "2026-10-15", "done", t2)
    assert not lg.claim_cron_run(db, "snapshot", "2026-10-15", LATER, LATER)  # done: never re-run
    with pytest.raises(ValueError, match="final state"):
        lg.finish_cron_run(db, "snapshot", "2026-10-15", "running", t2)


def test_outbox_sends_at_most_once(db: Any) -> None:
    lg.put_snapshot(db, _snap())
    assert lg.enqueue_ping(db, "snap1", "webpush", "report", "snap1", NOW)
    assert not lg.enqueue_ping(db, "snap1", "webpush", "report", "snap1", NOW)
    assert lg.claim_ping(db, "snap1", "webpush", NOW)
    assert not lg.claim_ping(db, "snap1", "webpush", NOW)  # a second worker never sends
    assert lg.reap_stale_pings(db, LATER, LATER) == 1  # lease expired → failed, never resent
    assert not lg.claim_ping(db, "snap1", "webpush", LATER)
    assert not lg.mark_ping_sent(db, "snap1", "webpush", LATER)
    assert db.execute("SELECT state FROM notification_outbox").fetchone()[0] == "failed"
