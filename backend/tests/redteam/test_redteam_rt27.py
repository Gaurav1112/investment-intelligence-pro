"""Red team RT-27: fixtures in prod, the MF history gate, FD id collisions. All values are TEST inputs."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from iip.services import discovery as disc
from iip.services.instruments import Citation, FDIn, add_fd
from iip.services.profile import Profile, evaluate
from iip.store.db import connect, migrate, write_tx
from iip.store.observations import ObservationRow, upsert_observation
from tests.api.test_core_api import make
from tests.redteam.test_redteam_discovery import RULES

AS_OF = date(2026, 10, 15)
NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[Any]:
    c = connect(tmp_path / "rt27.db")
    migrate(c, NOW.isoformat())
    yield c
    c.close()


# --------------------------------------------------------------------------------------------- fixtures in prod


def test_rt27_include_fixtures_refused_in_prod_with_no_state_change(tmp_path: Path) -> None:
    c, h = make(tmp_path, "prod")
    try:
        conn = connect(tmp_path / "prod" / "iip.db")  # a separate read connection to the app's database
        runs_before = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        r = c.post("/api/discover", json={"include_fixtures": True}, headers=h)
        assert r.status_code == 400
        assert r.json()["code"] == "FIXTURES_NOT_ALLOWED"
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == runs_before
        assert c.post("/api/discover", json={"include_fixtures": False}, headers=h).status_code == 200
    finally:
        c.__exit__(None, None, None)


def test_rt27_include_fixtures_still_allowed_in_dev(tmp_path: Path) -> None:
    c, h = make(tmp_path, "dev")
    try:
        assert c.post("/api/discover", json={"include_fixtures": True}, headers=h).status_code == 200
    finally:
        c.__exit__(None, None, None)


# --------------------------------------------------------------------------------------------- MF history gate


def _scheme(conn: Any, code: str, usable: int, rejected: int) -> None:
    iid = f"mf:{code}"
    with write_tx(conn):
        conn.execute(
            "INSERT INTO instruments(instrument_id, kind, name, amfi_code, origin, created_at)"
            " VALUES (?, 'mf_scheme', 'TEST Liquid Fund', ?, 'source', ?)",
            (iid, code, NOW.isoformat()),
        )
        conn.execute(
            "INSERT INTO mf_schemes(instrument_id, amc, category_raw, plan, exit_load_json)"
            " VALUES (?, 'TEST AMC', 'Debt Scheme - Liquid Fund', 'direct', NULL)",
            (iid,),
        )
    d = AS_OF - timedelta(days=usable + rejected + 5)
    for i in range(usable + rejected):
        upsert_observation(conn, ObservationRow(
            series_id=f"nav:{code}", kind="nav", value=f"{100 + i * 0.01:.4f}", unit="INR/unit", currency="INR",
            observation_date=(d + timedelta(days=i)).isoformat(), retrieved_at=NOW.isoformat(),
            source_id="amfi.navall", source_url="https://portal.amfiindia.com/x",
            quality_status="ok" if i < usable else "rejected", raw_sha256="a" * 64,
        ))  # fmt: skip


def _go(conn: Any) -> dict[str, Any]:
    p = Profile.model_validate({"amount": "100000", "withdrawal_date": "2027-04-15",
                                "objective": "A_capital_preservation", "loss_acceptable": False,
                                "early_need": "possible"})  # fmt: skip
    return disc.discover(conn, evaluate(p, AS_OF), as_of=AS_OF, ruleset=RULES)


def test_rt27_history_gate_counts_only_usable_rows(conn: Any) -> None:
    """59 usable NAVs + 40 rejected ones: below the 60-NAV gate. The old COUNT(*) admitted it (99 rows)."""
    _scheme(conn, "880001", usable=disc.MIN_HISTORY_POINTS - 1, rejected=40)
    out = _go(conn)
    assert out["skipped_no_history"] == 1
    assert not [r for r in out["ranked"] + out["excluded"] if r["instrument_id"] == "mf:880001"]


def test_rt27_history_gate_admits_exactly_the_threshold(conn: Any) -> None:
    _scheme(conn, "880002", usable=disc.MIN_HISTORY_POINTS, rejected=0)
    out = _go(conn)
    assert out["skipped_no_history"] == 0


# --------------------------------------------------------------------------------------------- FD ids


def _fd(conn: Any, kind: str, rate: str) -> str:
    body = FDIn(institution="Acme Finance", institution_type=kind,  # type: ignore[arg-type]
                rate=Decimal(rate), tenure_days=365, premature_penalty=Decimal("0.01"),
                citation=Citation(url="https://example.test/rates", as_of=AS_OF))  # fmt: skip
    return add_fd(conn, body, NOW)


def test_rt27_fd_ids_include_institution_type_so_same_names_do_not_collide(conn: Any) -> None:
    bank = _fd(conn, "bank", "0.07")
    nbfc = _fd(conn, "nbfc", "0.09")
    assert bank == "fd:bank:acme-finance:365d"
    assert nbfc == "fd:nbfc:acme-finance:365d"
    terms = {r["instrument_id"]: r for r in conn.execute("SELECT * FROM deposit_terms")}
    assert terms[bank]["dicgc_eligible"] == 1 and terms[bank]["rate"] == "0.07"
    assert terms[nbfc]["dicgc_eligible"] == 0 and terms[nbfc]["rate"] == "0.09"  # the NBFC no longer overwrote the bank
    types = dict(conn.execute("SELECT key, value_json FROM settings WHERE key LIKE 'fd.institution_type:%'"))
    assert types == {f"fd.institution_type:{bank}": '"bank"', f"fd.institution_type:{nbfc}": '"nbfc"'}
