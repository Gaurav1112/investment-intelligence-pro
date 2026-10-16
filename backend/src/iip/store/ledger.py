"""Repositories for the append-only ledgers and automation tables of migration 0004 (PLAN.md wave 2, package A10).

Every write that can carry many rows is batched: one read of what already exists (when the write must be checked
against it) and multi-row ``INSERT … VALUES (…),(…)`` statements of at most ``MAX_PARAMS`` bound values each, so a
remote libSQL database costs a handful of round trips per batch instead of one or more per row (ADR-0013). Callers
own the transaction: wrap a batch in :func:`iip.store.db.write_tx` when it must be all-or-nothing.

Append-only is enforced by triggers in the migration. This module never updates or deletes ledger rows, except
:func:`erase_user_rows` (the user's own erase, SEC-81) and the once-only CAS confirmation of a decision.

Times are ISO-8601 strings passed in by the service layer: nothing here reads a clock. Money and other decimals are
``Decimal`` in the dataclasses and ``TEXT`` in the database (never a float).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, fields
from decimal import Decimal
from typing import Any

# Bound values per statement stay under SQLite's historic 999-variable limit, so every sqlite/libSQL build accepts
# them (as store/observations.py).
MAX_PARAMS = 900


class LedgerConflict(RuntimeError):
    """An append-only write met an existing row with the same key but different content. Nothing was written."""


# ------------------------------------------------------------------------------------------------- batching helpers


def chunks[T](seq: Sequence[T], size: int) -> list[Sequence[T]]:
    size = max(1, size)
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def insert_many(
    conn: sqlite3.Connection, table: str, columns: Sequence[str], rows: Sequence[Sequence[Any]], suffix: str = ""
) -> int:
    """Multi-row INSERT in as few statements as the parameter limit allows. ``table``/``columns``/``suffix`` are
    module constants, never user input (asserted). Returns the number of rows the database reports as changed."""
    if not rows:
        return 0
    assert table.isidentifier() and all(c.isidentifier() for c in columns)
    width = len(columns)
    marks = "(" + ",".join("?" * width) + ")"
    changed = 0
    for part in chunks(rows, MAX_PARAMS // width):
        sql = f"INSERT INTO {table}({','.join(columns)}) VALUES {','.join(marks for _ in part)} {suffix}"  # noqa: S608
        cur = conn.execute(sql.strip(), [v for row in part for v in row])
        changed += max(0, int(cur.rowcount))
    return changed


def select_by_keys(
    conn: sqlite3.Connection, table: str, key_cols: Sequence[str], keys: Sequence[tuple[Any, ...]], cols: str
) -> list[sqlite3.Row]:
    """Rows whose composite key is in ``keys``, read in chunks of OR-ed key groups (portable to every SQLite build,
    unlike row-value IN lists on old ones)."""
    if not keys:
        return []
    assert table.isidentifier() and all(c.isidentifier() for c in key_cols)
    group = "(" + " AND ".join(f"{c}=?" for c in key_cols) + ")"
    out: list[sqlite3.Row] = []
    for part in chunks(keys, MAX_PARAMS // len(key_cols)):
        sql = f"SELECT {cols} FROM {table} WHERE {' OR '.join(group for _ in part)}"  # noqa: S608 - constants
        out += conn.execute(sql, [v for k in part for v in k]).fetchall()
    return out


def dec(value: Decimal | None) -> str | None:
    """A Decimal as stored TEXT. Non-finite values are refused (they cannot be traced to a source)."""
    if value is None:
        return None
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"expected a finite Decimal, got {value!r}")
    return str(value)


def _values(row: object) -> tuple[Any, ...]:
    out: list[Any] = []
    for f in fields(row):  # type: ignore[arg-type]
        v = getattr(row, f.name)
        out.append(dec(v) if isinstance(v, Decimal) else v)
    return tuple(out)


def _columns(cls: type) -> tuple[str, ...]:
    return tuple(f.name for f in fields(cls))


# ------------------------------------------------------------------------------------------------- signal registry


@dataclass(frozen=True)
class SignalRule:
    rule_id: str
    version: int
    class_: str  # 'P' | 'D' | 'S' (column "class")
    family: str
    spec_yaml: str
    spec_hash: str
    registered_at: str
    state: str
    state_reason: str | None
    state_changed_at: str


_RULE_COLS = (
    "rule_id", "version", "class", "family", "spec_yaml", "spec_hash", "registered_at", "state", "state_reason",
    "state_changed_at",
)  # fmt: skip


def register_rules(conn: sqlite3.Connection, rules: Sequence[SignalRule]) -> int:
    """Register rules (idempotent). A rule already registered with a DIFFERENT spec hash is a conflict: a changed
    spec must be a new version. Returns the number of newly registered rules."""
    if not rules:
        return 0
    keys = [(r.rule_id, r.version) for r in rules]
    have = {
        (row["rule_id"], int(row["version"])): row["spec_hash"]
        for row in select_by_keys(conn, "signal_rules", ("rule_id", "version"), keys, "rule_id, version, spec_hash")
    }
    new: dict[tuple[str, int], SignalRule] = {}
    for r in rules:
        key = (r.rule_id, r.version)
        known = have.get(key, new[key].spec_hash if key in new else None)
        if known is not None and known != r.spec_hash:
            raise LedgerConflict(f"rule {r.rule_id}@{r.version} is registered with a different spec hash")
        if key not in have:
            new[key] = r
    return insert_many(conn, "signal_rules", _RULE_COLS, [_values(r) for r in new.values()])


def set_rule_state(
    conn: sqlite3.Connection, rule_id: str, version: int, state: str, reason: str | None, at: str
) -> bool:
    cur = conn.execute(
        "UPDATE signal_rules SET state=?, state_reason=?, state_changed_at=? WHERE rule_id=? AND version=?",
        (state, reason, at, rule_id, version),
    )
    return int(cur.rowcount) == 1


@dataclass(frozen=True)
class RoleBinding:
    role: str
    instrument_id: str
    rule_of_choice: str
    bound_at: str


def bind_roles(conn: sqlite3.Connection, bindings: Sequence[RoleBinding]) -> int:
    """Upsert role → instrument bindings (user config) in one statement per chunk."""
    return insert_many(
        conn, "rule_role_bindings", _columns(RoleBinding), [_values(b) for b in bindings],
        "ON CONFLICT(role) DO UPDATE SET instrument_id=excluded.instrument_id,"
        " rule_of_choice=excluded.rule_of_choice, bound_at=excluded.bound_at",
    )  # fmt: skip


def role_bindings(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["role"]: r["instrument_id"] for r in conn.execute("SELECT role, instrument_id FROM rule_role_bindings")}


# ------------------------------------------------------------------------------------------------- backtest ledger


@dataclass(frozen=True)
class BacktestTrial:
    trial_id: str
    rule_id: str
    version: int
    family: str
    params_json: str
    universe_id: str
    horizon: str
    benchmark_id: str
    data_snapshot_hash: str
    code_version: str
    rules_version: str
    seed: str
    status: str
    created_at: str
    oos_edge_hash: str | None = None
    n_periods: int | None = None
    sr_hat: Decimal | None = None
    skew: Decimal | None = None
    kurt: Decimal | None = None


def append_trials(conn: sqlite3.Connection, trials: Sequence[BacktestTrial]) -> int:
    """Log trials. A trial id that already exists is an IntegrityError: the log never overwrites."""
    return insert_many(conn, "backtest_trials", _columns(BacktestTrial), [_values(t) for t in trials])


def record_trial_result(
    conn: sqlite3.Connection,
    trial_id: str,
    *,
    oos_edge_hash: str,
    n_periods: int,
    sr_hat: Decimal,
    skew: Decimal,
    kurt: Decimal,
    status: str,
) -> bool:
    """Fill in a trial's result columns (the identity columns are frozen by trigger)."""
    cur = conn.execute(
        "UPDATE backtest_trials SET oos_edge_hash=?, n_periods=?, sr_hat=?, skew=?, kurt=?, status=? WHERE trial_id=?",
        (oos_edge_hash, n_periods, dec(sr_hat), dec(skew), dec(kurt), status, trial_id),
    )
    return int(cur.rowcount) == 1


def count_trials(conn: sqlite3.Connection, family: str) -> int:
    """N for gate G8: every configuration ever logged in the family."""
    return int(conn.execute("SELECT COUNT(*) FROM backtest_trials WHERE family=?", (family,)).fetchone()[0])


@dataclass(frozen=True)
class BacktestRun:
    run_id: str
    trial_id: str
    manifest_json: str
    output_hash: str
    gates_json: str
    stats_json: str
    verdict: str
    vault_opened: int
    created_at: str


def append_backtest_runs(conn: sqlite3.Connection, runs: Sequence[BacktestRun]) -> int:
    return insert_many(conn, "backtest_runs", _columns(BacktestRun), [_values(r) for r in runs])


# ------------------------------------------------------------------------------------------------- shadow ledger


@dataclass(frozen=True)
class RuleEvaluation:
    rule_id: str
    version: int
    as_of_date: str
    scope_id: str
    state: str
    condition_met: int | None
    payload_json: str
    input_hash: str
    snapshot_id: str
    evaluated_at: str


_EVAL_KEY = ("rule_id", "version", "as_of_date", "scope_id")


def _append_keyed(
    conn: sqlite3.Connection,
    table: str,
    rows: Sequence[Any],
    hash_col: str,
    columns: tuple[str, ...],
    *,
    keep_existing: bool = False,
) -> int:
    """Append rows keyed by (rule_id, version, as_of_date, scope_id). A re-run with the same content is a no-op
    (idempotent cron); the same key with a different content hash is a :class:`LedgerConflict` and nothing is
    written, unless ``keep_existing`` (then the row already recorded stands and the new one is skipped: "the first
    write for a data date stands"). Statements: one chunked read of the existing keys, then chunked multi-row
    inserts."""
    if not rows:
        return 0
    keys = [tuple(getattr(r, k) for k in _EVAL_KEY) for r in rows]
    existing = {
        (row["rule_id"], int(row["version"]), row["as_of_date"], row["scope_id"]): row[hash_col]
        for row in select_by_keys(conn, table, _EVAL_KEY, keys, f"rule_id, version, as_of_date, scope_id, {hash_col}")
    }
    new: dict[tuple[Any, ...], Any] = {}
    for key, r in zip(keys, rows, strict=True):
        if keep_existing and key in existing:
            continue
        known = existing.get(key)
        if known is None and key in new:
            known = getattr(new[key], hash_col)
        if known is not None:
            if known != getattr(r, hash_col):
                raise LedgerConflict(f"{table}: {key} already recorded with different content")
            continue
        new[key] = r
    return insert_many(conn, table, columns, [_values(r) for r in new.values()])


def append_rule_evaluations(
    conn: sqlite3.Connection, rows: Sequence[RuleEvaluation], *, keep_existing: bool = False
) -> int:
    """The daily shadow ledger (J4): returns the number of new rows. ``keep_existing``: a key already recorded is
    left as it is even when the new content differs (the J4 re-run semantics), instead of a conflict."""
    return _append_keyed(
        conn, "rule_evaluations", rows, "input_hash", _columns(RuleEvaluation), keep_existing=keep_existing
    )


@dataclass(frozen=True)
class Outcome:
    rule_id: str
    version: int
    as_of_date: str
    scope_id: str
    horizon_end: str
    status: str  # 'scored' | 'unscorable'
    edge_after_cost_tax: Decimal | None
    unscorable_reason: str | None
    inputs_hash: str
    scored_at: str
    # Graft TA-1: the DATA date on which this outcome became known (the scoring pass's as_of, never the wall clock).
    # None = unknown, and then no point-in-time read ever sees the row (outcomes_as_of).
    resolved_on: str | None = None


def append_outcomes(conn: sqlite3.Connection, rows: Sequence[Outcome]) -> int:
    """Outcomes are scored once: a re-score with identical inputs is a no-op, a different one a conflict."""
    return _append_keyed(conn, "outcomes", rows, "inputs_hash", _columns(Outcome))


# The first date an evaluation can be resolved: its horizon end, or its own date when it has none (an abstained
# evaluation is recorded as unscorable then). Same expression as ix_rule_evaluations_due (migration 0004).
_DUE_ON = "COALESCE(json_extract(e.payload_json, '$.horizon_end'), e.as_of_date)"
_UNSCORED = (
    "SELECT e.rule_id, e.version, e.as_of_date, e.scope_id, e.state, e.condition_met, e.payload_json,"  # noqa: S608
    f" {_DUE_ON} AS due_on FROM rule_evaluations e WHERE e.as_of_date < ? AND NOT EXISTS (SELECT 1 FROM outcomes o"
    " WHERE o.rule_id = e.rule_id AND o.version = e.version AND o.as_of_date = e.as_of_date"
    " AND o.scope_id = e.scope_id)"
)
_DUE_SQL = (
    f"WITH u AS ({_UNSCORED})"  # noqa: S608 - module constants only
    " SELECT * FROM (SELECT 'row' AS part, rule_id, version, as_of_date, scope_id, state, condition_met,"
    " payload_json, NULL AS n_not_due, NULL AS n_waiting_for_basis FROM u"
    " WHERE due_on <= ? AND (? OR condition_met IS NULL)"
    " ORDER BY due_on, as_of_date, rule_id, version, scope_id LIMIT ?)"
    " UNION ALL SELECT 'counts', NULL, NULL, NULL, NULL, NULL, NULL, NULL,"
    " COALESCE(SUM(due_on > ?), 0), COALESCE(SUM(due_on <= ? AND condition_met IS NOT NULL AND NOT ?), 0) FROM u"
)


@dataclass(frozen=True)
class DueEvaluations:
    rows: list[sqlite3.Row]  # due, unscored and able to progress, oldest due date first (at most ``limit``)
    not_yet_due: int  # unscored rows whose resolution date is after as_of (counted, not read)
    waiting_for_basis: int  # due rows with a condition result while no cost/tax basis is given (counted, not read)


def due_evaluations(conn: sqlite3.Connection, as_of: str, *, has_basis: bool, limit: int = 500) -> DueEvaluations:
    """Unscored evaluations dated before ``as_of`` that can progress today, in ONE statement (database-reviewer-06).

    Rows that cannot progress are counted but never read: those not due yet (resolution date after ``as_of``) and,
    while no cost/tax basis is given, those with a condition result. So the oldest stuck rows can never crowd the
    recordable ones (an abstained evaluation, recorded as unscorable) out of the ``limit`` window, and a daily run
    does not re-read the whole backlog's payloads."""
    basis = 1 if has_basis else 0
    rows = conn.execute(_DUE_SQL, (as_of, as_of, basis, limit, as_of, as_of, basis)).fetchall()
    data = [r for r in rows if r["part"] == "row"]
    counts = next(r for r in rows if r["part"] == "counts")
    return DueEvaluations(data, int(counts["n_not_due"]), int(counts["n_waiting_for_basis"]))


def unscored_evaluations(conn: sqlite3.Connection, as_of_before: str, limit: int = 500) -> list[sqlite3.Row]:
    """Evaluations dated before ``as_of_before`` without an outcome that are due by then, oldest due first (one
    statement; see :func:`due_evaluations`)."""
    return due_evaluations(conn, as_of_before, has_basis=True, limit=limit).rows


def outcomes_as_of(
    conn: sqlite3.Connection, as_of: str, *, rule_id: str | None = None, version: int | None = None
) -> list[sqlite3.Row]:
    """Point-in-time read of outcomes (graft TA-1): only rows whose outcome was KNOWN on ``as_of``
    (``resolved_on <= as_of``). A row without ``resolved_on`` is excluded (conservative: it cannot be placed in
    time). Every gate or score that asks "as of d" must read outcomes through this function. One statement."""
    sql = "SELECT * FROM outcomes WHERE resolved_on IS NOT NULL AND resolved_on <= ?"
    params: list[Any] = [as_of]
    if rule_id is not None:
        sql += " AND rule_id = ?"
        params.append(rule_id)
    if version is not None:
        sql += " AND version = ?"
        params.append(version)
    return list(conn.execute(sql + " ORDER BY resolved_on, rule_id, version, as_of_date, scope_id", params))


# ------------------------------------------------------------------------------------------------- snapshots


@dataclass(frozen=True)
class SignalSnapshot:
    snapshot_id: str
    as_of_date: str
    engine_version: str
    rules_version: str
    input_manifest_hash: str
    verdict: str
    card_set_hash: str
    payload_json: str
    created_at: str


def put_snapshot(conn: sqlite3.Connection, snap: SignalSnapshot) -> bool:
    """Content-addressed: the same id twice writes no second snapshot row (True only when a row was written). The
    same id with a different payload means the id was not derived from the content: refused.

    Every call ALSO appends a ``snapshot_runs`` row (computed_at = ``snap.created_at``), so the snapshot just
    computed becomes the current one even when its content was first stored earlier (inputs A -> B -> A)."""
    cur = conn.execute(  # not ON CONFLICT DO NOTHING: the no-replace trigger would fire first (migration 0004)
        f"INSERT INTO signal_snapshots({','.join(_columns(SignalSnapshot))}) SELECT {','.join('?' * 9)}"  # noqa: S608
        " WHERE NOT EXISTS (SELECT 1 FROM signal_snapshots WHERE snapshot_id = ?)",
        (*_values(snap), snap.snapshot_id),
    )
    created = int(cur.rowcount) == 1
    if not created:
        row = conn.execute(
            "SELECT payload_json FROM signal_snapshots WHERE snapshot_id=?", (snap.snapshot_id,)
        ).fetchone()
        if row is not None and row["payload_json"] != snap.payload_json:
            raise LedgerConflict(f"snapshot {snap.snapshot_id} already stored with a different payload")
    conn.execute(
        "INSERT INTO snapshot_runs(snapshot_id, as_of_date, computed_at) VALUES (?, ?, ?)",
        (snap.snapshot_id, snap.as_of_date, snap.created_at),
    )
    return created


# The current snapshot = the one of the newest computation (snapshot_runs), never the newest snapshot row: a
# content-addressed row keeps the created_at of its FIRST computation. Served by ix_snapshot_runs_latest.
LATEST_RUN_ORDER = "r.as_of_date DESC, r.computed_at DESC, r.run_id DESC"


def latest_snapshot(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Today's read: ONE statement. Columns of ``signal_snapshots`` plus ``computed_at`` of the newest run."""
    row: sqlite3.Row | None = conn.execute(
        "SELECT s.*, r.computed_at FROM snapshot_runs r JOIN signal_snapshots s ON s.snapshot_id = r.snapshot_id"  # noqa: S608
        f" ORDER BY {LATEST_RUN_ORDER} LIMIT 1"  # module constant
    ).fetchone()
    return row


# ------------------------------------------------------------------------------------------------- decisions


@dataclass(frozen=True)
class Decision:
    card_id: str
    snapshot_id: str | None
    goal_id: str | None
    decision: str  # 'done' | 'not_now' | 'disagree'
    note: str | None
    decided_at: str
    card_key: str | None = None  # notify.card_key of the card (snapshot-independent); None for legacy callers


def append_decisions(conn: sqlite3.Connection, rows: Sequence[Decision]) -> int:
    return insert_many(conn, "decisions_log", _columns(Decision), [_values(r) for r in rows])


def confirm_decisions_from_cas(
    conn: sqlite3.Connection, results: Sequence[tuple[int, bool]], checked_at: str, cas_import_ref: str
) -> int:
    """Record, once per decision, whether a later CAS confirmed (True) or contradicted (False) a 'done' entry. One
    statement per chunk. Decisions already checked are skipped (the trigger forbids changing them)."""
    changed = 0
    for part in chunks(list(results), (MAX_PARAMS - 2) // 3):
        cases = " ".join("WHEN ? THEN ?" for _ in part)
        cur = conn.execute(
            f"UPDATE decisions_log SET cas_confirmed = CASE decision_id {cases} END,"  # noqa: S608 - placeholders only
            " cas_checked_at = ?, cas_import_ref = ?"
            f" WHERE cas_confirmed IS NULL AND decision = 'done' AND decision_id IN ({','.join('?' * len(part))})",
            [*(v for d, ok in part for v in (d, 1 if ok else 0)), checked_at, cas_import_ref, *(d for d, _ in part)],
        )
        changed += int(cur.rowcount)
    return changed


# ------------------------------------------------------------------------------------------------- market-derived


@dataclass(frozen=True)
class GridPoint:
    instrument_id: str
    month: str  # 'YYYY-MM'
    nav_date: str
    nav: Decimal
    source_obs_id: int | None
    refreshed_at: str


def upsert_series_grid(conn: sqlite3.Connection, points: Sequence[GridPoint]) -> int:
    """Refresh month-end points (J3). An unchanged point is not rewritten (fewer billed row writes on Turso)."""
    return insert_many(
        conn, "series_grid", _columns(GridPoint), [_values(p) for p in points],
        "ON CONFLICT(instrument_id, month) DO UPDATE SET nav_date=excluded.nav_date, nav=excluded.nav,"
        " source_obs_id=excluded.source_obs_id, refreshed_at=excluded.refreshed_at"
        " WHERE series_grid.nav_date IS NOT excluded.nav_date OR series_grid.nav IS NOT excluded.nav"
        " OR series_grid.source_obs_id IS NOT excluded.source_obs_id",
    )  # fmt: skip


def series_grid(conn: sqlite3.Connection, instrument_ids: Iterable[str]) -> dict[str, list[tuple[str, Decimal]]]:
    """Month-end NAVs for many instruments in one statement per chunk: ``{instrument_id: [(month, nav), …]}``."""
    ids = sorted(set(instrument_ids))
    out: dict[str, list[tuple[str, Decimal]]] = {i: [] for i in ids}
    for part in chunks(ids, MAX_PARAMS):
        rows = conn.execute(
            f"SELECT instrument_id, month, nav FROM series_grid WHERE instrument_id IN ({','.join('?' * len(part))})"  # noqa: S608
            " ORDER BY instrument_id, month",
            list(part),
        ).fetchall()
        for r in rows:
            out[r["instrument_id"]].append((r["month"], Decimal(r["nav"])))
    return out


@dataclass(frozen=True)
class Restatement:
    series_id: str
    source_id: str
    frozen_snapshot_hash: str
    new_content_hash: str
    first_diff_date: str | None
    rows_changed: int
    detected_at: str


def append_restatements(conn: sqlite3.Connection, rows: Sequence[Restatement]) -> int:
    return insert_many(conn, "restatements", _columns(Restatement), [_values(r) for r in rows])


# ------------------------------------------------------------------------------------------------- cron and outbox


def claim_cron_run(conn: sqlite3.Connection, job: str, run_key: str, now: str, stale_before: str) -> bool:
    """Claim (job, run_key) in ONE conditional statement (design-risk-first.md 9.3). True = this caller owns the run.
    A 'failed' run, or a 'running' one started before ``stale_before`` (a killed function), can be taken over. A
    'done'/'noop' run, or a live 'running' one, cannot: a duplicate delivery is a no-op."""
    cur = conn.execute(
        "INSERT INTO cron_runs(job, run_key, state, attempts, started_at) VALUES (?, ?, 'running', 1, ?)"
        " ON CONFLICT(job, run_key) DO UPDATE SET attempts = cron_runs.attempts + 1, state = 'running',"
        " started_at = excluded.started_at, finished_at = NULL, detail_code = NULL"
        " WHERE cron_runs.state = 'failed' OR (cron_runs.state = 'running' AND cron_runs.started_at < ?)",
        (job, run_key, now, stale_before),
    )
    return int(cur.rowcount) == 1


def finish_cron_run(
    conn: sqlite3.Connection, job: str, run_key: str, state: str, now: str, detail_code: str | None = None
) -> bool:
    if state not in ("done", "noop", "failed"):
        raise ValueError(f"not a final state: {state!r}")
    cur = conn.execute(
        "UPDATE cron_runs SET state=?, finished_at=?, detail_code=? WHERE job=? AND run_key=? AND state='running'",
        (state, now, detail_code, job, run_key),
    )
    return int(cur.rowcount) == 1


def enqueue_ping(
    conn: sqlite3.Connection, outbox_key: str, channel: str, kind: str, snapshot_id: str | None, now: str
) -> bool:
    """Queue one ping; a second enqueue of the same (key, channel) is a no-op."""
    cur = conn.execute(
        "INSERT INTO notification_outbox(outbox_key, channel, kind, snapshot_id, state, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, 'pending', ?, ?) ON CONFLICT(outbox_key, channel) DO NOTHING",
        (outbox_key, channel, kind, snapshot_id, now, now),
    )
    return int(cur.rowcount) == 1


def claim_ping(conn: sqlite3.Connection, outbox_key: str, channel: str, now: str) -> bool:
    """pending → sending in one statement. Send only when this returns True."""
    cur = conn.execute(
        "UPDATE notification_outbox SET state='sending', claimed_at=?, updated_at=?"
        " WHERE outbox_key=? AND channel=? AND state='pending'",
        (now, now, outbox_key, channel),
    )
    return int(cur.rowcount) == 1


def mark_ping_sent(conn: sqlite3.Connection, outbox_key: str, channel: str, now: str) -> bool:
    cur = conn.execute(
        "UPDATE notification_outbox SET state='sent', updated_at=?"
        " WHERE outbox_key=? AND channel=? AND state='sending'",
        (now, outbox_key, channel),
    )
    return int(cur.rowcount) == 1


def reap_stale_pings(conn: sqlite3.Connection, claimed_before: str, now: str) -> int:
    """A 'sending' row whose claim is older than the lease is marked 'failed' and never resent (one statement)."""
    cur = conn.execute(
        "UPDATE notification_outbox SET state='failed', updated_at=? WHERE state='sending' AND claimed_at < ?",
        (now, claimed_before),
    )
    return int(cur.rowcount)


# ------------------------------------------------------------------------------------------------- erase (SEC-81)

# Children before parents (foreign keys). The user's data from migration 0004; the market-derived tables
# (series_grid, restatements) and the registry specs are public and kept, like observations.
USER_TABLES_0004: tuple[str, ...] = (
    "outcomes",
    "rule_evaluations",
    "backtest_runs",
    "backtest_trials",
    "notification_outbox",
    "snapshot_runs",
    "signal_snapshots",
    "decisions_log",
    "holding_goal_map",
    "goals",
    "policy_versions",
    "risk_profile",
    "user_tax_context",
    "rule_role_bindings",
    "cron_runs",
)
PUBLIC_TABLES_0004: tuple[str, ...] = ("series_grid", "restatements", "signal_rules")
assert all(t.isidentifier() for t in (*USER_TABLES_0004, *PUBLIC_TABLES_0004))
_ERASE_SQL = {t: "DELETE FROM " + t for t in USER_TABLES_0004}  # noqa: S608 - identifier-asserted constants


def erase_user_rows(conn: sqlite3.Connection) -> dict[str, int]:
    """Delete every user row of migration 0004, including the append-only ledgers, by opening the erase gate for
    the duration of this call only. MUST run inside the caller's write transaction (so a failure rolls back the
    gate with everything else). Returns rows deleted per table."""
    if not conn.in_transaction:
        raise RuntimeError("erase_user_rows must run inside a write transaction")
    conn.execute("INSERT INTO ledger_erase_gate(id) VALUES (1)")
    try:
        counts = {t: int(conn.execute(_ERASE_SQL[t]).rowcount) for t in USER_TABLES_0004}
    finally:
        conn.execute("DELETE FROM ledger_erase_gate")
    return counts
