"""ECC security-reviewer-1 / decision U-01 (PLAN §8): the HOSTED NAVAll refresh (manual route and cron J1/J2/J4)
stores rows for held and watched schemes ONLY - never the Direct-Growth universe the local heuristic keeps. On SQLite
and libSQL, with the synthetic NAVAll fixture (fictional codes)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from iip.services import cron
from iip.services import ingestion as ing
from iip.store.db import connect, connect_libsql, migrate
from tests.services.test_ingestion import amfi, fetcher

from .conftest import NOW, navall_codes, watch_schemes
from .test_cron import Amfi, ctx_for, hooks


@pytest.fixture(params=("sqlite", "libsql"))
def conn(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect_libsql(str(tmp_path / "h.db"), hosted=True) if request.param == "libsql" else connect(tmp_path / "h.db")
    migrate(c, NOW.isoformat())
    ing.sync_sources(c)
    yield c
    c.close()


def _run_hosted_navall(c: sqlite3.Connection) -> dict[str, object]:
    for _ in range(100):
        out = ing.ingest_navall_resumable(c, fetcher(amfi), lambda: NOW, lambda: 100.0)
        if out["done"]:
            return out
    raise AssertionError("the hosted NAVAll never finished")


def _stored_codes(c: sqlite3.Connection) -> tuple[set[str], set[str]]:
    inst = {str(r[0]) for r in c.execute("SELECT amfi_code FROM instruments WHERE kind='mf_scheme'")}
    obs = {
        str(r[0]).removeprefix("nav:")
        for r in c.execute("SELECT DISTINCT series_id FROM observations WHERE kind='nav'")
    }
    return inst, obs


def test_nothing_held_or_watched_means_nothing_is_stored_hosted(conn: sqlite3.Connection) -> None:
    assert ing.tracked_scheme_codes(conn) == set()
    out = _run_hosted_navall(conn)
    assert out["status"] == "ok"
    assert _stored_codes(conn) == (set(), set())  # was 7 / 7: the whole Direct-Growth excerpt


def test_hosted_stores_exactly_the_held_and_watched_schemes(conn: sqlite3.Connection) -> None:
    direct_growth = navall_codes()
    others = sorted(set(navall_codes(direct_growth=False)) - set(direct_growth))
    watched = [direct_growth[0], others[0]]  # a watched Regular-plan scheme is stored too: tracking decides
    watch_schemes(conn, watched)
    _run_hosted_navall(conn)
    assert _stored_codes(conn) == ({str(c) for c in watched}, {str(c) for c in watched})


def test_the_ingestion_service_declares_the_u01_scope_and_the_cron_enforces_it() -> None:
    assert ing.HOSTED_NAVALL_SCOPE == "held_watched"
    assert cron.default_hooks().navall_scope_enforced is True


def test_cron_j1_with_the_default_hooks_stores_only_watched_schemes(conn: sqlite3.Connection) -> None:
    watched = navall_codes()[:2]
    watch_schemes(conn, watched)
    h = cron.default_hooks()
    res = cron.run_job(ctx_for(conn, Amfi(), hooks(navall_scope_enforced=h.navall_scope_enforced)), "navall")
    assert (res.state, res.code) == ("done", "STORED")
    assert _stored_codes(conn)[1] == {str(c) for c in watched}
