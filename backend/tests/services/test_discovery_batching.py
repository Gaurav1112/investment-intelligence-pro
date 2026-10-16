"""A02: Discovery's universe build reads a CONSTANT number of statements, whatever the number of schemes, stops at a
time budget with a flagged PARTIAL result, and a repeat visit writes nothing.

Statements are counted with a fake driver: a wrapper that counts every ``execute``/``executemany``/``executescript``
call, which is what one Hrana round trip costs on hosted libSQL. All data here is SYNTHETIC (fictional codes in the
9xxxxx range, origin 'fixture'); nothing is market data.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from iip.rules.loader import load_tax_rules
from iip.services import analysis as an
from iip.services import discovery as disc
from iip.services import instruments
from iip.services.profile import Profile, evaluate
from iip.store.db import connect, connect_libsql, migrate

AS_OF = date(2026, 10, 15)
NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
RULES = load_tax_rules()
URL = "https://example.test/synthetic"
_WRITE_HEADS = ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER")


class CountingConnection:
    """Fake driver: delegates to a real connection and records every statement sent to it."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw
        self.statements: list[str] = []

    def execute(self, sql: str, params: Any = ()) -> Any:
        self.statements.append(sql)
        return self._raw.execute(sql, params)

    def executemany(self, sql: str, seq: Any) -> Any:
        self.statements.append(sql)
        return self._raw.executemany(sql, seq)

    def executescript(self, script: str) -> Any:
        self.statements.append(script)
        return self._raw.executescript(script)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._raw, name)

    @property
    def writes(self) -> list[str]:
        return [s for s in self.statements if s.lstrip().upper().startswith(_WRITE_HEADS)]


def _seed(conn: sqlite3.Connection, n_with_history: int, n_without: int) -> None:
    """Synthetic schemes: ``n_with_history`` with 70 month-spaced NAVs, ``n_without`` with 5 (below the gate)."""
    instruments: list[tuple[Any, ...]] = []
    schemes: list[tuple[Any, ...]] = []
    obs: list[tuple[Any, ...]] = []
    cats = ("Debt Scheme - Liquid Fund", "Equity Scheme - Large Cap Fund", "Debt Scheme - Money Market Fund")
    for i in range(n_with_history + n_without):
        code = 910000 + i
        iid = f"mf:{code}"
        instruments.append((iid, f"SYNTHETIC FUND {i:04d}", str(code), NOW.isoformat()))
        schemes.append((iid, cats[i % 3], cats[i % 3]))
        points = 70 * 30 if i < n_with_history else 5
        start = AS_OF - timedelta(days=points + 1)
        for k in range(points):
            d = start + timedelta(days=k)
            nav = Decimal("10") + Decimal(k) / Decimal(400) + Decimal(i % 7) / Decimal(100)
            obs.append((f"nav:{code}", format(nav, "f"), d.isoformat()))
    conn.execute("BEGIN")
    conn.executemany(
        "INSERT INTO instruments(instrument_id, kind, name, amfi_code, origin, created_at)"
        " VALUES (?, 'mf_scheme', ?, ?, 'fixture', ?)",
        instruments,
    )
    conn.executemany(
        "INSERT INTO mf_schemes(instrument_id, amc, category_raw, sebi_category, plan, option_type)"
        " VALUES (?, 'SYNTHETIC AMC', ?, ?, 'direct', 'Growth')",
        schemes,
    )
    conn.executemany(
        "INSERT INTO observations(series_id, kind, value, unit, currency, observation_date, retrieved_at, source_id,"
        f" source_url, quality_status, raw_sha256) VALUES (?, 'nav', ?, 'INR/unit', 'INR', ?, '{NOW.isoformat()}',"
        f" 'fixture', '{URL}', 'fixture', '{'f' * 64}')",
        obs,
    )
    conn.execute("COMMIT")


def _seed_other_kinds(conn: sqlite3.Connection) -> None:
    """Two T-bills (one with a look-ahead-only quote), three FDs (bank with a typed existing deposit, NBFC, post
    office) — all synthetic."""
    conn.execute("BEGIN")
    conn.execute("INSERT INTO issuers(issuer_id, name, issuer_type) VALUES ('goi', 'Government of India', 'sovereign')")
    for iid, maturity, quotes in (
        ("tbill:182d:2027-04-13", "2027-04-13",
         [("2026-10-14", "0.0650", "fixture"), ("2026-10-01", "0.0640", "fixture")]),
        ("tbill:91d:2027-01-13", "2027-01-13", [("2026-10-20", "0.0600", "fixture")]),
    ):  # fmt: skip
        conn.execute(
            "INSERT INTO instruments(instrument_id, kind, name, issuer_id, origin, created_at)"
            " VALUES (?, 'tbill', ?, 'goi', 'fixture', ?)",
            (iid, f"SYNTHETIC {iid}", NOW.isoformat()),
        )
        conn.execute(
            "INSERT INTO bond_terms(instrument_id, face_value, coupon_rate, coupon_freq, maturity_date, daycount,"
            " listed, credit_rating) VALUES (?, '100', '0', 0, ?, 'ACT/365F', 1, 'SOVEREIGN')",
            (iid, maturity),
        )
        for d, v, src in quotes:
            conn.execute(
                "INSERT INTO observations(series_id, kind, value, unit, observation_date, retrieved_at, source_id,"
                " source_url, quality_status, raw_sha256) VALUES (?, 'yield', ?, 'fraction', ?, ?, ?, ?, 'fixture', ?)",
                (f"yield:{iid}", v, d, NOW.isoformat(), src, URL, "f" * 64),
            )
    for iid, inst, itype, insured, existing in (
        ("fd:bank:synthetic-bank:400d", "Synthetic Bank", "bank", 1, '"300000"'),
        ("fd:nbfc:synthetic-nbfc:400d", "Synthetic NBFC", "nbfc", 0, None),
        ("fd:post_office:synthetic-po:400d", "Synthetic PO", "post_office", 0, "null"),
    ):
        conn.execute(
            "INSERT INTO instruments(instrument_id, kind, name, origin, created_at) VALUES (?, 'fd', ?, 'fixture', ?)",
            (iid, f"{inst} FD", NOW.isoformat()),
        )
        conn.execute(
            "INSERT INTO deposit_terms(instrument_id, institution, rate, compounding, tenure_days, premature_penalty,"
            " dicgc_eligible, rate_as_of, citation_url) VALUES (?, ?, '0.07', 'quarterly', 400, '0.01', ?, ?, ?)",
            (iid, inst, insured, "2026-10-10", URL),
        )
        conn.execute(
            "INSERT INTO settings(key, value_json) VALUES (?, ?)", (f"fd.institution_type:{iid}", f'"{itype}"')
        )
        if existing is not None:
            conn.execute("INSERT INTO settings(key, value_json) VALUES (?, ?)", (f"fd.existing:{iid}", existing))
        if itype == "bank":
            conn.execute("INSERT INTO settings(key, value_json) VALUES (?, ?)",
                         (f"fd.entered_at:{iid}", '"2026-10-11T09:00:00+00:00"'))  # fmt: skip
    conn.execute("COMMIT")


def _db(tmp_path: Path, name: str, n_with: int, n_without: int) -> sqlite3.Connection:
    c = connect(tmp_path / f"{name}.db")
    migrate(c, NOW.isoformat())
    _seed(c, n_with, n_without)
    _seed_other_kinds(c)
    return c


@pytest.fixture
def small(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = _db(tmp_path, "small", 6, 4)
    yield c
    c.close()


def _universe(conn: Any, time_left: Callable[[], float] | None = None) -> disc.Universe:
    return disc.build_universe(conn, amount=Decimal("250000"), as_of=AS_OF, withdrawal=AS_OF + timedelta(days=182),
                               ruleset=RULES, profile=None, excluded_kinds=(), time_left=time_left)  # fmt: skip


def test_universe_statement_count_does_not_grow_with_schemes(tmp_path: Path) -> None:
    counts = []
    for name, n_with, n_without in (("a", 5, 5), ("b", 40, 60)):
        raw = _db(tmp_path, name, n_with, n_without)
        conn = CountingConnection(raw)
        uni = _universe(conn)
        assert uni.evaluated_mf == n_with and uni.skipped_no_history == n_without and not uni.partial
        assert conn.writes == []
        counts.append(len(conn.statements))
        raw.close()
    assert counts[0] == counts[1], counts
    assert counts[1] <= 10, counts


def test_batched_universe_equals_the_single_instrument_builder(small: sqlite3.Connection) -> None:
    """Oracle: analysis.build_one still reads one instrument at a time through the original per-item helpers
    (_nav_series, tbill_quote, fund_credit_facts, existing_fd_deposits, fd_institution_type, fd_entered_at)."""
    # A source conflict on one scheme and a factsheet on another exercise the batched branches.
    small.execute(
        "INSERT INTO observations(series_id, kind, value, unit, currency, observation_date, retrieved_at, source_id,"
        " source_url, quality_status, raw_sha256) SELECT series_id, kind, '99.9', unit, currency, observation_date,"
        " retrieved_at, 'amfi.navall', source_url, 'ok', raw_sha256 FROM observations WHERE series_id='nav:910001'"
        " ORDER BY observation_date DESC LIMIT 1"
    )
    small.execute(
        "INSERT INTO fund_facts(instrument_id, as_of_month, as_of_date, lowest_rating, citation_url, verified_on,"
        " entered_at) VALUES ('mf:910002', '2026-08', '2026-08-31', 'AA', ?, '2026-09-05', '2026-09-05T00:00:00')",
        (URL,),
    )
    uni = _universe(small)
    ids = {b.candidate.instrument_id for b in uni.built}
    assert {"mf:910001", "mf:910002", "tbill:182d:2027-04-13", "tbill:91d:2027-01-13"} <= ids
    assert any("SOURCE_CONFLICT" in c for b in uni.built for c in b.ineligible_reasons)
    for b in uni.built:
        iid = b.candidate.instrument_id
        one = an.build_one(small, iid, amount=Decimal("250000"), as_of=AS_OF, withdrawal=AS_OF + timedelta(days=182),
                           ruleset=RULES, profile=None)  # fmt: skip
        assert one.built == b, iid
        assert one.prov == {**uni.sources[iid], "kind": one.kind}, iid
    assert uni.fd_institution_types == {
        "fd:bank:synthetic-bank:400d": "bank",
        "fd:nbfc:synthetic-nbfc:400d": "nbfc",
        "fd:post_office:synthetic-po:400d": "post_office",
    }
    for iid, t in uni.fd_institution_types.items():
        assert disc.fd_institution_type(small, iid) == t


def _clock(ticks_before_timeout: int) -> Callable[[], float]:
    """A fake budget: positive for the first ``ticks_before_timeout`` checks, then exhausted."""
    calls = {"n": 0}

    def time_left() -> float:
        calls["n"] += 1
        return 1.0 if calls["n"] <= ticks_before_timeout else 0.0

    return time_left


def test_time_budget_overrun_returns_a_flagged_partial_universe(small: sqlite3.Connection) -> None:
    uni = _universe(small, _clock(3))
    assert uni.partial
    assert uni.evaluated_mf == 3 and uni.not_evaluated == 3
    assert uni.incomplete_kinds == ("mf_scheme", "tbill", "fd")
    assert len(uni.built) == 3


def _profile() -> Profile:
    return Profile.model_validate({
        "amount": "500000", "withdrawal_date": "2027-04-15", "objective": "A_capital_preservation",
        "loss_acceptable": False, "early_need": "possible", "max_days_to_cash": 7,
    })  # fmt: skip


def test_discover_partial_result_is_flagged_not_an_error(small: sqlite3.Connection) -> None:
    out = disc.discover(small, evaluate(_profile(), AS_OF), as_of=AS_OF, ruleset=RULES, allow_fixtures=True,
                        time_left=_clock(2))  # fmt: skip
    assert out["partial"] is not None
    assert out["partial"]["reason"] == "TIME_BUDGET_EXCEEDED" and out["partial"]["mf_not_evaluated"] == 4
    assert out["partial"]["incomplete_kinds"] == ["mf_scheme", "tbill", "fd"]
    sections = (out["report"] or {}).get("sections", [])
    assert any("time budget" in s["text"] for s in sections), sections
    assert disc.store_run(small, out, NOW) is None  # a timing-dependent result is not a reproducible run record
    assert small.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_budget_exhausted_before_anything_abstains_with_the_reason(small: sqlite3.Connection) -> None:
    out = disc.discover(small, evaluate(_profile(), AS_OF), as_of=AS_OF, ruleset=RULES, allow_fixtures=True,
                        time_left=lambda: 0.0)  # fmt: skip
    assert out["status"] == "ABSTAIN" and out["partial"] is not None
    assert any("time budget" in r for r in out["abstain_reasons"]), out["abstain_reasons"]


def test_complete_result_has_no_partial_flag(small: sqlite3.Connection) -> None:
    out = disc.discover(small, evaluate(_profile(), AS_OF), as_of=AS_OF, ruleset=RULES, allow_fixtures=True,
                        time_left=lambda: 30.0)  # fmt: skip
    assert out["partial"] is None


def test_repeat_visit_with_unchanged_inputs_writes_nothing(small: sqlite3.Connection) -> None:
    conn = CountingConnection(small)
    out = disc.discover(conn, evaluate(_profile(), AS_OF), as_of=AS_OF, ruleset=RULES, allow_fixtures=True)  # type: ignore[arg-type]
    first = disc.store_run(conn, out, NOW)  # type: ignore[arg-type]
    assert first is not None and len(conn.writes) == 1  # the first distinct result is recorded once
    conn.statements.clear()
    again = disc.discover(conn, evaluate(_profile(), AS_OF), as_of=AS_OF, ruleset=RULES, allow_fixtures=True)  # type: ignore[arg-type]
    assert disc.store_run(conn, again, NOW) == first  # type: ignore[arg-type]
    assert conn.writes == [], conn.writes


def test_batched_reads_give_the_same_result_on_the_libsql_driver(tmp_path: Path) -> None:
    """The hosted driver (libSQL, here on a local file) must accept the batched SQL — json_each, json_object, window
    functions, the marker-split instrument row — and return what sqlite3 returns."""
    raw = _db(tmp_path, "parity", 4, 2)
    raw.close()
    a = connect(tmp_path / "parity.db")
    b = connect_libsql(str(tmp_path / "parity.db"))
    try:
        ua, ub = _universe(a), _universe(b)
        assert ua.built == ub.built and ua.sources == ub.sources and ua.fd_institution_types == ub.fd_institution_types
        for iid in ("mf:910000", "tbill:182d:2027-04-13", "fd:bank:synthetic-bank:400d"):
            ha = instruments.instrument_head(a, iid, summary=True)
            hb = instruments.instrument_head(b, iid, summary=True)
            assert ha == hb and ha is not None, iid
            for grid in (None, "monthly"):
                pa = instruments.series_points(a, ha["series_id"], start=date(2026, 1, 1), grid=grid)
                assert pa == instruments.series_points(b, ha["series_id"], start=date(2026, 1, 1), grid=grid)
    finally:
        a.close()
        b.close()
