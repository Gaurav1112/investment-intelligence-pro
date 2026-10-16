"""Migration 0004 (PLAN.md wave 2, A10): applies on SQLite AND libSQL, upgrades a version-3 store without losing
data, creates every table the plan lists with its constraints, and the migration splitter keeps triggers whole."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from iip.store.db import (
    _SCHEMA_VERSION_DDL,
    _migration_files,
    _split_sql,
    connect,
    connect_libsql,
    current_version,
    migrate,
)

from ._ledger_fixtures import DRIVERS, NOW, open_db

PLAN_TABLES = {
    "goals", "holding_goal_map", "risk_profile", "user_tax_context", "policy_versions", "decisions_log",
    "series_grid", "cron_runs", "signal_snapshots", "notification_outbox", "signal_rules", "rule_role_bindings",
    "backtest_trials", "backtest_runs", "rule_evaluations", "outcomes", "restatements",
}  # fmt: skip

APPEND_ONLY_TRIGGERS = {
    "policy_versions_no_update", "policy_versions_no_delete",
    "decisions_log_no_update", "decisions_log_cas_once", "decisions_log_no_delete",
    "restatements_no_update", "restatements_no_delete",
    "signal_snapshots_no_update", "signal_snapshots_no_delete",
    "signal_rules_spec_frozen", "signal_rules_no_delete",
    "backtest_trials_no_update", "backtest_trials_no_delete",
    "backtest_runs_no_update", "backtest_runs_no_delete",
    "rule_evaluations_no_update", "rule_evaluations_no_delete",
    "outcomes_no_update", "outcomes_no_delete",
} | {
    f"{t}_no_replace" for t in (
        "policy_versions", "decisions_log", "restatements", "signal_snapshots", "signal_rules", "backtest_trials",
        "backtest_runs", "rule_evaluations", "outcomes",
    )
}  # fmt: skip


@pytest.fixture(params=DRIVERS)
def db(request: pytest.FixtureRequest, tmp_path: Path) -> Any:
    conn = open_db(tmp_path / "x.db", request.param)
    yield conn
    conn.close()


def _names(conn: Any, kind: str) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type=?", (kind,))}


def test_0004_is_the_latest_contiguous_migration() -> None:
    files = _migration_files()
    assert files[-1][0] == 4 and files[-1][1] == "0004_risk_signals.sql"


def test_every_planned_table_and_trigger_exists(db: Any) -> None:
    assert current_version(db) == 4
    assert PLAN_TABLES | {"ledger_erase_gate"} <= _names(db, "table")
    assert _names(db, "trigger") == APPEND_ONLY_TRIGGERS
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_data_health_runs_index_exists(db: Any) -> None:
    """RC-6 (A02 request): the per-source run window query is served by an index on (source_id, started_at)."""
    assert "ix_runs_source_started" in _names(db, "index")
    cols = [r["name"] for r in db.execute("PRAGMA index_info(ix_runs_source_started)")]
    assert cols == ["source_id", "started_at"]


def test_decisions_log_has_cas_confirmed(db: Any) -> None:
    cols = {r["name"] for r in db.execute("PRAGMA table_info(decisions_log)")}
    assert {"cas_confirmed", "cas_checked_at", "cas_import_ref"} <= cols


@pytest.mark.parametrize("driver", DRIVERS)
def test_0004_upgrades_a_version_3_store_without_losing_data(tmp_path: Path, driver: str) -> None:
    conn = connect_libsql(str(tmp_path / "v3.db")) if driver == "libsql" else connect(tmp_path / "v3.db")
    conn.execute(_SCHEMA_VERSION_DDL)
    for version, name, sql in _migration_files()[:3]:
        for stmt in _split_sql(sql):
            conn.execute(stmt)
        conn.execute("INSERT INTO schema_version VALUES (?, ?, ?)", (version, name, NOW))
    conn.execute("INSERT INTO settings(key, value_json) VALUES ('fictional', '1')")
    assert current_version(conn) == 3
    assert migrate(conn, NOW) == ["0004_risk_signals.sql"]
    assert migrate(conn, NOW) == []
    assert current_version(conn) == 4
    assert conn.execute("SELECT value_json FROM settings WHERE key='fictional'").fetchone()[0] == "1"
    assert PLAN_TABLES <= _names(conn, "table")
    conn.close()


# ----------------------------------------------------------------------------------------- splitter


def _old_split(sql: str) -> list[str]:  # the splitter before 0004, for the no-regression check
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def test_splitter_is_unchanged_for_migrations_without_triggers() -> None:
    for _, _, sql in _migration_files()[:3]:
        assert _split_sql(sql) == _old_split(sql)


def test_splitter_keeps_a_trigger_whole() -> None:
    sql = (
        "CREATE TABLE t (a INTEGER);\n"
        "create temp trigger t_no_delete before delete on t\nbegin select raise(abort, 'no'); end;\n"
        "CREATE TRIGGER t_two BEFORE UPDATE ON t BEGIN SELECT 1; SELECT RAISE(ABORT, 'x'); END;\n"
        "CREATE INDEX ix_t ON t(a);"
    )
    parts = _split_sql(sql)
    assert len(parts) == 4
    assert parts[1].lower().endswith("end") and "raise(abort, 'no');" in parts[1]
    assert parts[2].count(";") == 2 and parts[2].endswith("END")
    c = sqlite3.connect(":memory:")
    for p in parts:
        c.execute(p)
    c.execute("INSERT INTO t VALUES (1)")
    with pytest.raises(sqlite3.IntegrityError, match="no"):
        c.execute("DELETE FROM t")


def test_splitter_passes_an_unterminated_trigger_through_for_sqlite_to_reject() -> None:
    parts = _split_sql("CREATE TABLE t (a);\nCREATE TRIGGER broken BEFORE DELETE ON t BEGIN SELECT 1;")
    assert len(parts) == 2
    c = sqlite3.connect(":memory:")
    c.execute(parts[0])
    with pytest.raises(sqlite3.OperationalError):
        c.execute(parts[1])


# ----------------------------------------------------------------------------------------- constraints


@pytest.mark.parametrize(
    "sql, params",
    [
        ("INSERT INTO goals(goal_id, name, priority, objective, created_at, updated_at) VALUES (?,?,?,?,?,?)",
         ("g1", "House", 1, "Z", NOW, NOW)),
        ("INSERT INTO goals(goal_id, name, priority, created_at, updated_at) VALUES (?,?,?,?,?)",
         ("g1", "House", 0, NOW, NOW)),
        ("INSERT INTO goals(goal_id, name, priority, target_date, created_at, updated_at) VALUES (?,?,?,?,?,?)",
         ("g1", "House", 1, "31-12-2031", NOW, NOW)),
        ("INSERT INTO holding_goal_map(instrument_id, folio, goal_id, fraction, mapped_at) VALUES (?,?,?,?,?)",
         ("mf:990001", "", "no-such-goal", "1", NOW)),
        ("INSERT INTO user_tax_context(fy, ltcg_used_inr, ltcg_used_assumed, set_at) VALUES (?,?,?,?)",
         ("2026-27", "1000", 1, NOW)),
        ("INSERT INTO user_tax_context(fy, set_at) VALUES (?,?)", ("FY27", NOW)),
        ("INSERT INTO risk_profile(profile_id, set_at) VALUES (?,?)", (2, NOW)),
        ("INSERT INTO cron_runs(job, run_key, state, started_at) VALUES (?,?,?,?)",
         ("not-a-job", "2026-10-15", "running", NOW)),
        ("INSERT INTO notification_outbox(outbox_key, channel, kind, state, created_at, updated_at)"
         " VALUES (?,?,?,?,?,?)", ("k", "webpush", "report", "sending", NOW, NOW)),
        ("INSERT INTO signal_rules(rule_id, version, class, family, spec_yaml, spec_hash, registered_at, state,"
         " state_changed_at) VALUES (?,?,?,?,?,?,?,?,?)", ("S-X", 1, "S", "f", "y", "h", NOW, "BUY", NOW)),
        ("INSERT INTO series_grid(instrument_id, month, nav_date, nav, refreshed_at) VALUES (?,?,?,?,?)",
         ("mf:990001", "2026-09", "2026-08-31", "10.0", NOW)),
        ("INSERT INTO restatements(series_id, source_id, frozen_snapshot_hash, new_content_hash, rows_changed,"
         " detected_at) VALUES (?,?,?,?,?,?)", ("s", "src", "h1", "h1", 1, NOW)),
        ("INSERT INTO decisions_log(card_id, decision, decided_at) VALUES (?,?,?)", ("c1", "bought", NOW)),
        ("INSERT INTO decisions_log(card_id, decision, decided_at, cas_confirmed, cas_checked_at)"
         " VALUES (?,?,?,?,?)", ("c1", "not_now", NOW, 1, NOW)),
        ("INSERT INTO outcomes(rule_id, version, as_of_date, scope_id, horizon_end, status, inputs_hash, scored_at)"
         " VALUES (?,?,?,?,?,?,?,?)", ("S-X", 1, "2026-10-15", "goal:g1", "2027-10-15", "scored", "h", NOW)),
    ],
)  # fmt: skip
def test_constraints_reject_invalid_rows(db: Any, sql: str, params: tuple[Any, ...]) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, params)


def test_outcome_needs_its_evaluation(db: Any) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO outcomes(rule_id, version, as_of_date, scope_id, horizon_end, status, edge_after_cost_tax,"
            " inputs_hash, scored_at) VALUES ('S-X', 1, '2026-10-15', 'goal:g1', '2027-10-15', 'scored', '0.01',"
            " 'h', ?)",
            (NOW,),
        )
