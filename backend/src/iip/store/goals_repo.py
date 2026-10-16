"""Repository for goals, the holding → goal map, the risk profile, the tax context and policy versions (migration
0004, PLAN.md wave 2, package A10).

Writes are batched (multi-row statements, see :mod:`iip.store.ledger`); reads that the snapshot job needs come back
in a few statements regardless of the number of goals or holdings. Money and fractions are ``Decimal`` here and
``TEXT`` in the database. Nothing here reads a clock: every timestamp is passed in by the service layer. Values the
user has not set stay ``None`` (the supervisor abstains on them); this module never fills in a default number.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from iip.store.ledger import MAX_PARAMS, chunks, dec, insert_many

ONE = Decimal(1)


def _opt_dec(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _non_negative(name: str, value: Decimal | None) -> None:
    if value is not None and (not value.is_finite() or value < 0):
        raise ValueError(f"{name} must be a finite, non-negative Decimal")


# ------------------------------------------------------------------------------------------------- goals


@dataclass(frozen=True)
class Goal:
    goal_id: str
    name: str
    priority: int
    target_amount: Decimal | None = None
    target_date: str | None = None  # 'YYYY-MM-DD'
    objective: str | None = None  # 'A'..'E'
    loss_budget_inr: Decimal | None = None  # B_g
    recovery_months: int | None = None  # T_g
    h_safe_years: Decimal | None = None
    policy_version_id: int | None = None


_GOAL_COLS = (
    "goal_id", "name", "target_amount", "target_date", "priority", "objective", "loss_budget_inr", "recovery_months",
    "h_safe_years", "policy_version_id", "created_at", "updated_at",
)  # fmt: skip
_GOAL_UPDATABLE = [c for c in _GOAL_COLS if c not in ("goal_id", "created_at")]


def upsert_goals(conn: sqlite3.Connection, goals: Sequence[Goal], now: str) -> int:
    """Create or update goals in one statement per chunk. ``created_at`` is kept on update."""
    rows = []
    for g in goals:
        for name in ("target_amount", "loss_budget_inr", "h_safe_years"):
            _non_negative(name, getattr(g, name))
        rows.append((
            g.goal_id, g.name, dec(g.target_amount), g.target_date, g.priority, g.objective, dec(g.loss_budget_inr),
            g.recovery_months, dec(g.h_safe_years), g.policy_version_id, now, now,
        ))  # fmt: skip
    updates = ", ".join(f"{c}=excluded.{c}" for c in _GOAL_UPDATABLE)
    return insert_many(conn, "goals", _GOAL_COLS, rows, f"ON CONFLICT(goal_id) DO UPDATE SET {updates}")


def delete_goal(conn: sqlite3.Connection, goal_id: str) -> bool:
    """Deletes the goal and (cascade) its mappings: those holdings become Unassigned. The decision log keeps
    its rows."""
    return int(conn.execute("DELETE FROM goals WHERE goal_id=?", (goal_id,)).rowcount) == 1


def _goal(row: sqlite3.Row) -> Goal:
    return Goal(
        goal_id=row["goal_id"], name=row["name"], priority=int(row["priority"]),
        target_amount=_opt_dec(row["target_amount"]), target_date=row["target_date"], objective=row["objective"],
        loss_budget_inr=_opt_dec(row["loss_budget_inr"]), recovery_months=row["recovery_months"],
        h_safe_years=_opt_dec(row["h_safe_years"]), policy_version_id=row["policy_version_id"],
    )  # fmt: skip


def list_goals(conn: sqlite3.Connection) -> list[Goal]:
    """All goals in the user's priority order (ties: goal date, then id), in one statement."""
    rows = conn.execute("SELECT * FROM goals ORDER BY priority, target_date IS NULL, target_date, goal_id").fetchall()
    return [_goal(r) for r in rows]


# ------------------------------------------------------------------------------------------------- holding → goal map


@dataclass(frozen=True)
class GoalLink:
    instrument_id: str
    folio: str  # '' when the source has no folio
    goal_id: str
    fraction: Decimal  # (0, 1]


def replace_goal_map(conn: sqlite3.Connection, links: Sequence[GoalLink], now: str) -> int:
    """Replace the mapping of every holding named in ``links`` (other holdings are untouched). Each holding's
    fractions must be in (0, 1] and add up to at most 1 (the rest is Unassigned); otherwise nothing is written.
    Statements: one chunked DELETE of the touched holdings, then chunked multi-row INSERTs."""
    per_holding: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    seen: set[tuple[str, str, str]] = set()
    for link in links:
        if not isinstance(link.fraction, Decimal) or not link.fraction.is_finite():
            raise ValueError("fraction must be a finite Decimal")
        if not (0 < link.fraction <= ONE):
            raise ValueError(f"fraction for {link.instrument_id}/{link.folio} must be in (0, 1]")
        key = (link.instrument_id, link.folio, link.goal_id)
        if key in seen:
            raise ValueError(f"duplicate mapping {key}")
        seen.add(key)
        per_holding[(link.instrument_id, link.folio)] += link.fraction
    over = sorted(h for h, total in per_holding.items() if total > ONE)
    if over:
        raise ValueError(f"fractions add up to more than 1 for {over}")
    holdings = sorted(per_holding)
    for part in chunks(holdings, MAX_PARAMS // 2):
        groups = " OR ".join("(instrument_id=? AND folio=?)" for _ in part)
        sql = "DELETE FROM holding_goal_map WHERE " + groups  # noqa: S608 - placeholders only
        conn.execute(sql, [v for h in part for v in h])
    rows = [(lk.instrument_id, lk.folio, lk.goal_id, dec(lk.fraction), now) for lk in links]
    return insert_many(conn, "holding_goal_map", ("instrument_id", "folio", "goal_id", "fraction", "mapped_at"), rows)


def goal_map(conn: sqlite3.Connection) -> list[GoalLink]:
    rows = conn.execute(
        "SELECT instrument_id, folio, goal_id, fraction FROM holding_goal_map ORDER BY instrument_id, folio, goal_id"
    ).fetchall()
    return [GoalLink(r["instrument_id"], r["folio"], r["goal_id"], Decimal(r["fraction"])) for r in rows]


# ------------------------------------------------------------------------------------------------- risk profile


@dataclass(frozen=True)
class RiskProfile:
    essential_monthly_expenses: Decimal | None = None
    emergency_months: int | None = None
    savings_balance: Decimal | None = None
    sweep_fd_balance: Decimal | None = None


def set_risk_profile(conn: sqlite3.Connection, profile: RiskProfile, now: str) -> None:
    for name in ("essential_monthly_expenses", "savings_balance", "sweep_fd_balance"):
        _non_negative(name, getattr(profile, name))
    conn.execute(
        "INSERT INTO risk_profile(profile_id, essential_monthly_expenses, emergency_months, savings_balance,"
        " sweep_fd_balance, set_at) VALUES (1, ?, ?, ?, ?, ?) ON CONFLICT(profile_id) DO UPDATE SET"
        " essential_monthly_expenses=excluded.essential_monthly_expenses, emergency_months=excluded.emergency_months,"
        " savings_balance=excluded.savings_balance, sweep_fd_balance=excluded.sweep_fd_balance,"
        " set_at=excluded.set_at",
        (
            dec(profile.essential_monthly_expenses), profile.emergency_months, dec(profile.savings_balance),
            dec(profile.sweep_fd_balance), now,
        ),
    )  # fmt: skip


def get_risk_profile(conn: sqlite3.Connection) -> RiskProfile | None:
    r = conn.execute("SELECT * FROM risk_profile WHERE profile_id=1").fetchone()
    if r is None:
        return None
    return RiskProfile(
        essential_monthly_expenses=_opt_dec(r["essential_monthly_expenses"]), emergency_months=r["emergency_months"],
        savings_balance=_opt_dec(r["savings_balance"]), sweep_fd_balance=_opt_dec(r["sweep_fd_balance"]),
    )  # fmt: skip


# ------------------------------------------------------------------------------------------------- tax context


@dataclass(frozen=True)
class TaxContext:
    fy: str  # '2026-27'
    regime: str | None = None  # 'new' | 'old'
    slab_rate: Decimal | None = None
    residency: str | None = None  # 'resident' | 'non_resident'
    ltcg_used_inr: Decimal | None = None
    ltcg_used_assumed: bool = True  # the conservative, labelled default: the exemption is already used


def set_tax_context(conn: sqlite3.Connection, ctx: TaxContext, now: str) -> None:
    _non_negative("ltcg_used_inr", ctx.ltcg_used_inr)
    _non_negative("slab_rate", ctx.slab_rate)
    conn.execute(
        "INSERT INTO user_tax_context(fy, regime, slab_rate, residency, ltcg_used_inr, ltcg_used_assumed, set_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(fy) DO UPDATE SET regime=excluded.regime,"
        " slab_rate=excluded.slab_rate, residency=excluded.residency, ltcg_used_inr=excluded.ltcg_used_inr,"
        " ltcg_used_assumed=excluded.ltcg_used_assumed, set_at=excluded.set_at",
        (
            ctx.fy, ctx.regime, dec(ctx.slab_rate), ctx.residency, dec(ctx.ltcg_used_inr),
            1 if ctx.ltcg_used_assumed else 0, now,
        ),
    )  # fmt: skip


def get_tax_context(conn: sqlite3.Connection, fy: str) -> TaxContext | None:
    r = conn.execute("SELECT * FROM user_tax_context WHERE fy=?", (fy,)).fetchone()
    if r is None:
        return None
    return TaxContext(
        fy=r["fy"], regime=r["regime"], slab_rate=_opt_dec(r["slab_rate"]), residency=r["residency"],
        ltcg_used_inr=_opt_dec(r["ltcg_used_inr"]), ltcg_used_assumed=bool(r["ltcg_used_assumed"]),
    )  # fmt: skip


# ------------------------------------------------------------------------------------------------- policy versions


def _canonical(policy: dict[str, Any]) -> str:
    def default(o: object) -> str:
        if isinstance(o, Decimal):
            return str(dec(o))
        raise TypeError(f"policy values must be JSON types or Decimal, not {type(o).__name__}")

    return json.dumps(policy, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=default)


@dataclass(frozen=True)
class PolicyVersion:
    policy_version_id: int
    policy: dict[str, Any]  # Decimals come back as strings (the canonical JSON form)
    policy_hash: str
    decided_at: str


def append_policy_version(
    conn: sqlite3.Connection, policy: dict[str, Any], decided_at: str, now: str
) -> tuple[int, bool]:
    """Store the user's policy as a new version. Content-addressed: an identical policy returns the existing
    version. Returns ``(policy_version_id, created)``. Floats are refused (use Decimal or a string)."""

    def no_float(o: object) -> None:
        if isinstance(o, float):
            raise ValueError("policy values must not be floats (use Decimal)")
        if isinstance(o, dict):
            for v in o.values():
                no_float(v)
        elif isinstance(o, list | tuple):
            for v in o:
                no_float(v)

    no_float(policy)
    body = _canonical(policy)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    cur = conn.execute(
        "INSERT INTO policy_versions(policy_json, policy_hash, decided_at, created_at) SELECT ?, ?, ?, ?"
        " WHERE NOT EXISTS (SELECT 1 FROM policy_versions WHERE policy_hash = ?)",  # see migration 0004 header
        (body, digest, decided_at, now, digest),
    )
    created = int(cur.rowcount) == 1
    row = conn.execute("SELECT policy_version_id FROM policy_versions WHERE policy_hash=?", (digest,)).fetchone()
    return int(row["policy_version_id"]), created


def latest_policy_version(conn: sqlite3.Connection) -> PolicyVersion | None:
    r = conn.execute(
        "SELECT * FROM policy_versions ORDER BY decided_at DESC, policy_version_id DESC LIMIT 1"
    ).fetchone()
    if r is None:
        return None
    return PolicyVersion(int(r["policy_version_id"]), json.loads(r["policy_json"]), r["policy_hash"], r["decided_at"])


# ------------------------------------------------------------------------------------------------- one-shot read


@dataclass(frozen=True)
class GoalContext:
    goals: list[Goal]
    links: list[GoalLink]
    risk_profile: RiskProfile | None
    tax_context: TaxContext | None
    policy: PolicyVersion | None


def load_goal_context(conn: sqlite3.Connection, fy: str) -> GoalContext:
    """Everything the per-goal supervisor manifest needs, in five statements whatever the number of goals."""
    return GoalContext(
        goals=list_goals(conn),
        links=goal_map(conn),
        risk_profile=get_risk_profile(conn),
        tax_context=get_tax_context(conn, fy),
        policy=latest_policy_version(conn),
    )
