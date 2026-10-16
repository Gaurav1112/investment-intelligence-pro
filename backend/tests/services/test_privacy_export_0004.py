"""ECC security-reviewer-2 / database-reviewer-04 (SEC-80 "every user table"): the privacy export and the inventory
cover the migration-0004 user tables (goals, risk profile, tax context, decisions, snapshots, ...) and the pre-import
snapshots, on SQLite AND libSQL, so nothing is erased that the user could not first export. Synthetic data only."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from iip.services import portfolio as pf
from iip.store import ledger as lg
from tests.store._ledger_fixtures import DRIVERS, open_db
from tests.store.test_ledger_append_only import _seed_everything

NOW = datetime(2026, 10, 16, 5, 0, tzinfo=UTC)
# The export names the profiles table's section "profile" (one decoded object per row); every other user table is a
# section of the same name.
SECTION = {"profiles": "profile"}


@pytest.fixture(params=DRIVERS)
def db(request: pytest.FixtureRequest, tmp_path: Path) -> Any:
    conn = open_db(tmp_path / "x.db", request.param)
    yield conn
    conn.close()


def _seed(db: Any) -> None:
    _seed_everything(db)
    pf.snapshot_transactions(db, NOW, tag="synthetic")  # one import_snapshots row


def test_export_has_a_section_and_a_manifest_hash_for_every_user_table(db: Any) -> None:
    _seed(db)
    out = pf.export_all(db, NOW)
    for table in (*pf.USER_TABLES, *lg.USER_TABLES_0004):
        key = SECTION.get(table, table)
        assert key in out and key in out["manifest"], table
    for table in (*lg.USER_TABLES_0004, "import_snapshots"):
        count = int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        assert len(out[table]) == count, table
    assert out["goals"][0]["goal_id"] == "g1" and out["goals"][0]["name"] == "Fictional goal"
    assert len(out["risk_profile"]) == 1 and len(out["user_tax_context"]) == 1 and len(out["decisions_log"]) == 1


def test_export_is_deterministic(db: Any) -> None:
    _seed(db)
    assert pf.export_all(db, NOW)["manifest"] == pf.export_all(db, NOW)["manifest"]


def test_inventory_counts_every_user_table(db: Any, tmp_path: Path) -> None:
    _seed(db)
    tables = pf.inventory(db, tmp_path)["user_data"]["tables"]
    assert set(tables) == {*pf.USER_TABLES, *lg.USER_TABLES_0004}
    for table in lg.USER_TABLES_0004:
        assert tables[table] == int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]), table
    assert tables["goals"] == 1 and tables["risk_profile"] == 1 and tables["user_tax_context"] == 1


def test_public_0004_tables_stay_out_of_the_export(db: Any) -> None:
    _seed(db)
    out = pf.export_all(db, NOW)
    assert not set(lg.PUBLIC_TABLES_0004) & set(out)  # market data and the rule registry are not user data
