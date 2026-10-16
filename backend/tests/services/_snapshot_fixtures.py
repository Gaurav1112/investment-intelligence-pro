"""SYNTHETIC fixtures for the B02 snapshot, shadow-ledger and Today tests. Every id, name, NAV and stress value is
fictional (scheme codes in the 97xxxx range, origin 'fixture'); nothing here is market data or a real scheme."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from iip.rules.loader import STRESS_TABLE_PATH, StressTable, _read_yaml, load_action_templates, parse_stress_table
from iip.store import goals_repo, ledger
from iip.store.db import connect, migrate

NOW = "2026-10-16T05:00:00+00:00"
AS_OF = date(2026, 10, 15)
URL = "https://example.test/synthetic"

# Fictional stress values (NOT the cited table values; U-08 keeps those out of the repo).
LOCAL_STRESS: dict[str, Any] = {
    "schema_version": 1,
    "values": [
        {"risk_class": "EQ_LARGE", "stress": "0.40", "recovery_years": "2"},
        {"risk_class": "EQ_BROAD", "stress": "0.50", "recovery_years": "3"},
        {"risk_class": "EQ_MID", "stress": "0.60"},
        {"risk_class": "EQ_SMALL", "stress": "0.70"},
        {"risk_class": "EQ_FACTOR", "stress": "0.65"},
        {"risk_class": "EQ_SECTOR_THEMATIC", "stress": "0.80"},
        {"risk_class": "GOLD", "stress": "0.20"},
    ],
}

TEMPLATES = load_action_templates()


def stress_table(local: dict[str, Any] | None = LOCAL_STRESS) -> StressTable:
    return parse_stress_table(_read_yaml(STRESS_TABLE_PATH), local)


def open_db(path: Path) -> Any:
    conn = connect(path)
    migrate(conn, NOW)
    return conn


def add_scheme(conn: Any, iid: str, code: str, name: str, category: str, amc: str = "Fictional AMC") -> None:
    conn.execute(
        "INSERT INTO instruments(instrument_id, kind, name, amfi_code, origin, created_at)"
        " VALUES (?, 'mf_scheme', ?, ?, 'fixture', ?)",
        (iid, name, code, NOW),
    )
    conn.execute(
        "INSERT INTO mf_schemes(instrument_id, amc, category_raw, sebi_category) VALUES (?, ?, ?, ?)",
        (iid, amc, category, category),
    )


def add_nav(conn: Any, code: str, on: date, value: str) -> int:
    cur = conn.execute(
        "INSERT INTO observations(series_id, kind, value, unit, observation_date, retrieved_at, source_id, source_url,"
        " quality_status, raw_sha256) VALUES (?, 'nav', ?, 'INR', ?, ?, 'amfi_navall', ?, 'fixture', 'x')",
        (f"nav:{code}", value, on.isoformat(), NOW, URL),
    )
    return int(cur.lastrowid or 0)


def add_portfolio(conn: Any, pid: str = "p1", nature: str = "actual") -> None:
    conn.execute(
        "INSERT INTO portfolios(portfolio_id, name, nature, created_at) VALUES (?, 'Fictional', ?, ?)",
        (pid, nature, NOW),
    )


def buy(conn: Any, txn_id: str, iid: str, units: str, amount: str, on: str = "2025-01-10", pid: str = "p1") -> None:
    conn.execute(
        "INSERT INTO transactions(txn_id, portfolio_id, instrument_id, txn_date, txn_type, units, amount, source,"
        " created_at) VALUES (?, ?, ?, ?, 'buy', ?, ?, 'manual', ?)",
        (txn_id, pid, iid, on, units, amount, NOW),
    )


def seed_two_goals(conn: Any) -> None:
    """Household: one broad-equity fund (₹1,00,000 at NAV 100) and one overnight fund (₹50,000 at NAV 10).

    Goal "g-house": 80 % of the equity fund, loss limit ₹20,000 (stress 0.50 × ₹80,000 = ₹40,000 → BREACH).
    Goal "g-car": the other 20 % of the equity fund, NO loss limit (→ L3 abstains for g-car only).
    """
    add_portfolio(conn)
    add_scheme(conn, "mf:970001", "970001", "Fictional Flexi Fund", "Equity Scheme - Flexi Cap Fund")
    add_scheme(conn, "mf:970002", "970002", "Fictional Overnight Fund", "Debt Scheme - Overnight Fund")
    add_nav(conn, "970001", AS_OF, "100")
    add_nav(conn, "970002", AS_OF, "10")
    buy(conn, "t1", "mf:970001", "1000", "90000")
    buy(conn, "t2", "mf:970002", "5000", "50000")
    goals_repo.upsert_goals(
        conn,
        [
            goals_repo.Goal("g-house", "House", 1, target_amount=Decimal("500000"), target_date="2035-06-30",
                            loss_budget_inr=Decimal("20000"), recovery_months=60, h_safe_years=Decimal("3")),
            goals_repo.Goal("g-car", "Car", 2, target_date="2034-01-31", h_safe_years=Decimal("2")),
        ],
        NOW,
    )  # fmt: skip
    goals_repo.replace_goal_map(
        conn,
        [goals_repo.GoalLink("mf:970001", "", "g-house", Decimal("0.8")),
         goals_repo.GoalLink("mf:970001", "", "g-car", Decimal("0.2")),
         goals_repo.GoalLink("mf:970002", "", "g-house", Decimal("1"))],
        NOW,
    )  # fmt: skip
    goals_repo.set_risk_profile(
        conn,
        goals_repo.RiskProfile(essential_monthly_expenses=Decimal("10000"), emergency_months=3,
                               savings_balance=Decimal("0"), sweep_fd_balance=Decimal("0")),
        NOW,
    )  # fmt: skip


def register_s_rule(conn: Any, rule_id: str, spec: str, *, state: str = "PRE_REGISTERED", version: int = 1) -> None:
    from iip.engine.determinism import sha256_hex

    ledger.register_rules(
        conn,
        [ledger.SignalRule(rule_id, version, "S", _family(spec), spec, sha256_hex(spec), NOW, state, None, NOW)],
    )


def _family(spec: str) -> str:
    for line in spec.splitlines():
        if line.startswith("family:"):
            return line.split(":", 1)[1].strip()
    return "unknown"
