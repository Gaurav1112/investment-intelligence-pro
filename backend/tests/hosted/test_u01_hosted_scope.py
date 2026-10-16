"""ECC security-reviewer-1 / decision U-01 (PLAN §8): the HOSTED NAVAll refresh (manual route and cron J1/J2/J4)
stores rows for held and watched schemes ONLY - never the Direct-Growth universe the local heuristic keeps. On SQLite
and libSQL, with the synthetic NAVAll fixture (fictional codes)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta
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


# ---- verifier finding (round close): U-01 residual — unwatched/sold schemes and pre-fix rows must leave hosted


def _run_hosted_navall_at(c: sqlite3.Connection, at: datetime) -> dict[str, object]:
    for _ in range(100):
        out = ing.ingest_navall_resumable(c, fetcher(amfi), lambda: at, lambda: 100.0)
        if out["done"]:
            return out
    raise AssertionError("the hosted NAVAll never finished")


def test_an_unwatched_scheme_is_removed_from_hosted_on_the_next_run(conn: sqlite3.Connection) -> None:
    watch_schemes(conn, [navall_codes()[0]])
    _run_hosted_navall(conn)
    assert _stored_codes(conn) == ({str(navall_codes()[0])}, {str(navall_codes()[0])})
    conn.execute("DELETE FROM watchlist")
    assert ing.tracked_scheme_codes(conn) == set()
    _run_hosted_navall_at(conn, NOW + timedelta(days=1))
    assert _stored_codes(conn) == (set(), set())  # was ({code}, {code}): the latest NAV and instrument row stayed


def test_rows_from_the_pre_fix_hosted_refresh_are_removed_on_the_next_hosted_run(conn: sqlite3.Connection) -> None:
    ing.ingest_navall(conn, fetcher(amfi), lambda: NOW)  # what the manual hosted refresh stored before the U-01 fix
    assert len(_stored_codes(conn)[0]) == len(navall_codes())
    watched = navall_codes()[1]
    watch_schemes(conn, [watched])
    _run_hosted_navall_at(conn, NOW + timedelta(days=1))
    assert _stored_codes(conn) == ({str(watched)}, {str(watched)})
    assert conn.execute("SELECT COUNT(*) FROM mf_schemes").fetchone()[0] == 1


def test_the_hosted_purge_never_deletes_user_entered_data(conn: sqlite3.Connection) -> None:
    ing.ingest_navall(conn, fetcher(amfi), lambda: NOW)
    code = navall_codes()[2]
    iid = ing.instrument_id(code)
    conn.execute(
        "INSERT INTO fund_facts(instrument_id, as_of_month, as_of_date, citation_url, verified_on, entered_at)"
        " VALUES (?, '2026-09', '2026-09-30', 'https://example.invalid/factsheet', '2026-10-01', ?)",
        (iid, NOW.isoformat()),
    )
    _run_hosted_navall_at(conn, NOW + timedelta(days=1))
    inst, obs = _stored_codes(conn)
    assert inst == {str(code)}  # the instrument row stays: the user's factsheet entry refers to it
    assert obs == set()  # but no AMFI NAV of an untracked scheme stays hosted
    assert conn.execute("SELECT COUNT(*) FROM fund_facts WHERE instrument_id=?", (iid,)).fetchone()[0] == 1


def test_the_purge_reference_lists_cover_every_table_tied_to_instruments(conn: sqlite3.Connection) -> None:
    """Schema-drift guard: a new table referencing instruments must be classified (user data kept / derived data)."""
    tables = [str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    tied = {
        t
        for t in tables
        if t != "instruments" and any(str(r[1]) == "instrument_id" for r in conn.execute(f"PRAGMA table_info({t})"))
    }
    assert tied == set(ing.HOSTED_PURGE_KEEPS_IF_REFERENCED) | set(ing.HOSTED_PURGE_DERIVED)


# ---- SOLD-1 (user decision 2026-10-16): a fully sold, unwatched fund keeps its NAV history but is not refreshed


def _txn(c: sqlite3.Connection, code: int, n: int, kind: str, units: str, on: str, portfolio: str = "pf_1") -> None:
    c.execute(
        "INSERT INTO instruments(instrument_id, kind, name, amfi_code, origin, created_at)"
        " VALUES (?, 'mf_scheme', ?, ?, 'source', ?) ON CONFLICT(instrument_id) DO NOTHING",
        (ing.instrument_id(code), f"Fictional scheme {code}", str(code), NOW.isoformat()),
    )
    c.execute(
        "INSERT INTO portfolios(portfolio_id, name, nature, created_at) VALUES (?, 'Fictional', 'actual', ?)"
        " ON CONFLICT(portfolio_id) DO NOTHING",
        (portfolio, NOW.isoformat()),
    )
    c.execute(
        "INSERT INTO transactions(txn_id, portfolio_id, instrument_id, txn_date, txn_type, units, amount, source,"
        " created_at) VALUES (?, ?, ?, ?, ?, ?, '1000.00', 'manual', ?)",
        (f"tx_{code}_{n}", portfolio, ing.instrument_id(code), on, kind, units, NOW.isoformat()),
    )


def _history(c: sqlite3.Connection, code: int, dates: list[str]) -> None:
    """Older NAV history of a scheme (synthetic values), as a NAV-history backfill stores it."""
    for k, d in enumerate(dates):
        c.execute(
            "INSERT INTO observations(series_id, kind, value, unit, currency, observation_date, retrieved_at,"
            " source_id, source_url, quality_status, raw_sha256) VALUES (?, 'nav', ?, 'INR', 'INR', ?, ?,"
            " 'amfi.navhistory', 'https://example.invalid/fixture', 'ok', ?)",
            (ing.series_id(code), f"{10 + k}.0000", d, NOW.isoformat(), "0" * 64),
        )


def _nav_dates(c: sqlite3.Connection, code: int) -> list[str]:
    return [str(r[0]) for r in c.execute(
        "SELECT observation_date FROM observations WHERE series_id=? ORDER BY observation_date",
        (ing.series_id(code),))]  # fmt: skip


OLD = ["2026-01-05", "2026-01-06"]


def test_refresh_scope_is_held_or_watched_and_sold_schemes_stay_in_the_keep_scope(conn: sqlite3.Connection) -> None:
    held, sold, split, watched_sold = navall_codes()[:4]
    _txn(conn, held, 1, "buy", "10.5", "2026-01-01")
    _txn(conn, sold, 1, "buy", "10.1", "2026-01-01")
    _txn(conn, sold, 2, "buy", "0.2", "2026-01-02")
    _txn(conn, sold, 3, "sell", "10.3", "2026-02-01")  # exactly zero units left (Decimal, not float)
    # held in one portfolio, sold out of another: units across ALL portfolios decide
    _txn(conn, split, 1, "buy", "5", "2026-01-01", "pf_1")
    _txn(conn, split, 2, "buy", "5", "2026-01-01", "pf_2")
    _txn(conn, split, 3, "sell", "5", "2026-02-01", "pf_2")
    _txn(conn, watched_sold, 1, "buy", "1", "2026-01-01")
    _txn(conn, watched_sold, 2, "sell", "1", "2026-02-01")
    watch_schemes(conn, [watched_sold])
    assert ing.refresh_scheme_codes(conn) == {held, split, watched_sold}
    assert ing.tracked_scheme_codes(conn) == {held, sold, split, watched_sold}  # prune/purge keep: held or sold


def test_a_fully_sold_scheme_keeps_its_history_but_is_not_refreshed_until_bought_again(
    conn: sqlite3.Connection,
) -> None:
    code = navall_codes()[0]
    _txn(conn, code, 1, "buy", "10", "2026-01-02")
    _history(conn, code, OLD)
    _txn(conn, code, 2, "sell", "10", "2026-02-02")  # fully sold, not watched
    out = _run_hosted_navall(conn)
    assert out["status"] == "ok"
    assert _nav_dates(conn, code) == OLD  # history kept (returns, tax records); no new NAVAll row stored
    # Bought again: the next hosted run refreshes it.
    _txn(conn, code, 3, "buy", "2", "2026-03-02")
    _run_hosted_navall_at(conn, NOW + timedelta(days=1))
    dates = _nav_dates(conn, code)
    assert dates[: len(OLD)] == OLD and len(dates) == len(OLD) + 1  # the NAVAll date was added


def test_a_sold_scheme_put_on_the_watchlist_is_refreshed_again(conn: sqlite3.Connection) -> None:
    code = navall_codes()[1]
    _txn(conn, code, 1, "buy", "10", "2026-01-02")
    _txn(conn, code, 2, "sell", "10", "2026-02-02")
    _history(conn, code, OLD)
    _run_hosted_navall(conn)
    assert _nav_dates(conn, code) == OLD
    watch_schemes(conn, [code])
    _run_hosted_navall_at(conn, NOW + timedelta(days=1))
    assert len(_nav_dates(conn, code)) == len(OLD) + 1


def test_j3_gap_fill_skips_fully_sold_unwatched_schemes(conn: sqlite3.Connection) -> None:
    held, sold = navall_codes()[:2]
    _txn(conn, held, 1, "buy", "10", "2026-01-02")
    _txn(conn, sold, 1, "buy", "10", "2026-01-02")
    _txn(conn, sold, 2, "sell", "10", "2026-02-02")
    _history(conn, held, OLD)
    _history(conn, sold, OLD)
    res = cron.run_job(ctx_for(conn, Amfi(), hooks()), "history")
    assert res.counts["schemes"] == 1  # the held scheme only; the sold one keeps its rows and is not gap-filled
    assert _nav_dates(conn, sold) == OLD
