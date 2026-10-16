"""goals_repo (PLAN.md wave 2, A10): goals, the holding → goal map, risk profile, tax context and policy versions on
SQLite AND libSQL. Values round-trip as Decimal, unset values stay None (never defaulted), writes are batched, and
the snapshot's goal context is read in a fixed number of statements. All fixtures are synthetic."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from iip.store import goals_repo as gr
from iip.store.db import write_tx

from ._ledger_fixtures import DRIVERS, INSTRUMENTS, LATER, NOW, CountingConn, open_db


@pytest.fixture(params=DRIVERS)
def db(request: pytest.FixtureRequest, tmp_path: Path) -> Any:
    conn = open_db(tmp_path / "x.db", request.param)
    yield conn
    conn.close()


def _goal(gid: str, priority: int = 1, **kw: Any) -> gr.Goal:
    return gr.Goal(goal_id=gid, name=f"Fictional {gid}", priority=priority, **kw)


def test_goals_round_trip_and_keep_unset_values_none(db: Any) -> None:
    g = _goal("house", 1, target_amount=Decimal("2500000.00"), target_date="2031-03-31", objective="D",
              loss_budget_inr=Decimal("250000"), recovery_months=36, h_safe_years=Decimal("3"))  # fmt: skip
    assert gr.upsert_goals(db, [g, _goal("open", 2)], NOW) == 2
    got = gr.list_goals(db)
    assert got[0] == g and isinstance(got[0].target_amount, Decimal)
    assert got[1] == _goal("open", 2) and got[1].loss_budget_inr is None  # never defaulted


def test_goal_update_keeps_created_at(db: Any) -> None:
    gr.upsert_goals(db, [_goal("g1")], NOW)
    gr.upsert_goals(db, [_goal("g1", 3, loss_budget_inr=Decimal("100"))], LATER)
    row = db.execute("SELECT priority, loss_budget_inr, created_at, updated_at FROM goals").fetchone()
    assert tuple(row) == (3, "100", NOW, LATER)


def test_goals_order_by_priority_then_date(db: Any) -> None:
    gr.upsert_goals(db, [_goal("c", 2), _goal("b", 1, target_date="2030-01-01"), _goal("a", 1)], NOW)
    assert [g.goal_id for g in gr.list_goals(db)] == ["b", "a", "c"]


def test_negative_or_non_finite_money_is_refused(db: Any) -> None:
    with pytest.raises(ValueError):
        gr.upsert_goals(db, [_goal("g", loss_budget_inr=Decimal("-1"))], NOW)
    with pytest.raises(ValueError):
        gr.set_risk_profile(db, gr.RiskProfile(essential_monthly_expenses=Decimal("Infinity")), NOW)
    assert gr.list_goals(db) == [] and gr.get_risk_profile(db) is None


def test_goal_map_splits_a_holding_and_rejects_over_allocation(db: Any) -> None:
    gr.upsert_goals(db, [_goal("g1"), _goal("g2", 2)], NOW)
    links = [gr.GoalLink(INSTRUMENTS[0], "F1", "g1", Decimal("0.6")),
             gr.GoalLink(INSTRUMENTS[0], "F1", "g2", Decimal("0.4")),
             gr.GoalLink(INSTRUMENTS[1], "", "g2", Decimal("0.5"))]  # fmt: skip
    assert gr.replace_goal_map(db, links, NOW) == 3
    assert gr.goal_map(db) == sorted(links, key=lambda x: (x.instrument_id, x.folio, x.goal_id))
    with pytest.raises(ValueError, match="more than 1"):
        gr.replace_goal_map(db, [gr.GoalLink(INSTRUMENTS[0], "F1", "g1", Decimal("0.7")),
                                 gr.GoalLink(INSTRUMENTS[0], "F1", "g2", Decimal("0.4"))], LATER)  # fmt: skip
    for bad in (Decimal("0"), Decimal("1.01"), Decimal("NaN")):
        with pytest.raises(ValueError):
            gr.replace_goal_map(db, [gr.GoalLink(INSTRUMENTS[2], "", "g1", bad)], LATER)
    assert len(gr.goal_map(db)) == 3  # nothing written by the refused calls
    # replacing one holding's mapping leaves the others alone
    gr.replace_goal_map(db, [gr.GoalLink(INSTRUMENTS[0], "F1", "g2", Decimal("1"))], LATER)
    assert [(lk.instrument_id, lk.goal_id) for lk in gr.goal_map(db)] == [(INSTRUMENTS[0], "g2"),
                                                                         (INSTRUMENTS[1], "g2")]  # fmt: skip


def test_deleting_a_goal_unassigns_its_holdings(db: Any) -> None:
    gr.upsert_goals(db, [_goal("g1")], NOW)
    gr.replace_goal_map(db, [gr.GoalLink(INSTRUMENTS[0], "", "g1", Decimal("1"))], NOW)
    assert gr.delete_goal(db, "g1")
    assert gr.goal_map(db) == []


def test_map_to_an_unknown_goal_fails(db: Any) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        gr.replace_goal_map(db, [gr.GoalLink(INSTRUMENTS[0], "", "nope", Decimal("1"))], NOW)


def test_risk_profile_and_tax_context(db: Any) -> None:
    assert gr.get_risk_profile(db) is None and gr.get_tax_context(db, "2026-27") is None
    p = gr.RiskProfile(essential_monthly_expenses=Decimal("40000.50"), emergency_months=6)
    gr.set_risk_profile(db, p, NOW)
    assert gr.get_risk_profile(db) == p
    gr.set_risk_profile(db, gr.RiskProfile(emergency_months=3), LATER)  # one row, replaced
    assert gr.get_risk_profile(db) == gr.RiskProfile(emergency_months=3)
    assert gr.get_tax_context(db, "2026-27") is None
    default = gr.TaxContext("2026-27")
    gr.set_tax_context(db, default, NOW)
    assert gr.get_tax_context(db, "2026-27") == default and default.ltcg_used_assumed  # conservative default
    known = gr.TaxContext("2026-27", "new", Decimal("0.30"), "resident", Decimal("20000"), ltcg_used_assumed=False)
    gr.set_tax_context(db, known, LATER)
    assert gr.get_tax_context(db, "2026-27") == known
    with pytest.raises(sqlite3.IntegrityError):  # 'assume used' and a stated amount contradict each other
        gr.set_tax_context(db, gr.TaxContext("2027-28", ltcg_used_inr=Decimal("1")), NOW)


def test_policy_versions_are_content_addressed_and_refuse_floats(db: Any) -> None:
    pol = {"band_pp": Decimal("0.05"), "targets": {"g1": {"equity": "0.40"}}}
    v1, created = gr.append_policy_version(db, pol, "2026-10-16", NOW)
    assert created
    assert gr.append_policy_version(db, dict(reversed(pol.items())), "2026-10-17", LATER) == (v1, False)
    v2, created = gr.append_policy_version(db, {**pol, "band_pp": Decimal("0.04")}, "2026-10-18", LATER)
    assert created and v2 != v1
    latest = gr.latest_policy_version(db)
    assert latest is not None and latest.policy_version_id == v2 and latest.policy["band_pp"] == "0.04"
    with pytest.raises(ValueError, match="float"):
        gr.append_policy_version(db, {"band_pp": 0.05}, "2026-10-19", LATER)


@pytest.mark.parametrize("driver", DRIVERS)
def test_writes_are_batched_and_the_goal_context_is_a_fixed_number_of_reads(tmp_path: Path, driver: str) -> None:
    db = CountingConn(open_db(tmp_path / "x.db", driver))
    goals = [_goal(f"g{i:03d}", i + 1, loss_budget_inr=Decimal(1000 + i)) for i in range(150)]
    with write_tx(db):  # type: ignore[arg-type]
        gr.upsert_goals(db, goals, NOW)  # type: ignore[arg-type]
    assert len(db.seen) == 2  # ceil(150 / (900 // 12 = 75)) statements, not one per goal
    links = [gr.GoalLink(INSTRUMENTS[i % 3], f"F{i}", g.goal_id, Decimal("1")) for i, g in enumerate(goals)]
    db.seen.clear()
    with write_tx(db):  # type: ignore[arg-type]
        assert gr.replace_goal_map(db, links, NOW) == 150  # type: ignore[arg-type]
    assert len(db.seen) == 2  # one DELETE (150 holdings × 2 params) + one INSERT (150 × 5 params)
    db.seen.clear()
    ctx = gr.load_goal_context(db, "2026-27")  # type: ignore[arg-type]
    assert len(db.seen) == 5 and len(ctx.goals) == 150 and len(ctx.links) == 150
    assert ctx.risk_profile is None and ctx.tax_context is None and ctx.policy is None  # → supervisor abstains
