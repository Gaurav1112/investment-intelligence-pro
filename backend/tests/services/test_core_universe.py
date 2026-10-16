"""Core universe U1 (PLAN.md row B06; decisions U-07 and U-01).

* The role file holds roles only: no scheme names, codes or ISINs (public repo).
* The proposal is deterministic and stores nothing; nothing is tracked until the user confirms (U-07).
* Tracking is local-first: confirmation and the gap fill refuse hosted, and hosted scope never includes U1 (U-01).
* After confirmation, U1 is auto-tracked without a manual backfill: its daily NAVs are kept and its history is filled.
* The 2027 NSE holiday-calendar task is recorded.

Every AMC, scheme name, code, ISIN and NAV here is FICTIONAL (synthetic AMFI-format bytes over MockTransport)."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from iip.data.fetch import CircuitBreaker, Fetcher
from iip.data.models import SchemeRecord
from iip.services import ingestion as ing
from iip.store.db import connect, migrate
from iip.store.ledger import role_bindings
from iip.store.observations import ObservationRow, upsert_observations_batch
from tests.data.conftest import load_fixture
from tests.data.test_fetch import PUBLIC_IP

NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
HEADER = "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date"

# Fictional fund houses and schemes. Codes 99xxxx are not real AMFI codes; ISIN-like values are omitted ("-").
NAVALL_ROWS = [
    ("Open Ended Schemes(Other Scheme - Index Funds)", "Zephyr Mutual Fund", [
        "990101;-;-;Zephyr Nifty 50 Index Fund;Direct Plan;Growth Option;101.5000;14-Oct-2026",
        "990102;-;-;Zephyr Nifty 50 Index Fund;Regular Plan;Growth Option;99.1000;14-Oct-2026",
        "990103;-;-;Zephyr Nifty 50 Index Fund;Direct Plan;IDCW Option;50.2000;14-Oct-2026",
        "990104;-;-;Zephyr Nifty 500 Index Fund;Direct Plan;Growth Option;12.3000;14-Oct-2026",
        "990105;-;-;Zephyr Nifty Next 50 Index Fund;Direct Plan;Growth Option;20.0000;14-Oct-2026",
        "990106;-;-;Zephyr Nifty50 Equal Weight Index Fund;Direct Plan;Growth Option;15.0000;14-Oct-2026",
    ]),
    ("Open Ended Schemes(Other Scheme - Index Funds)", "Quorra Mutual Fund", [
        "990201;-;-;Quorra Nifty 50 Index Fund;Direct Plan;Growth;88.0000;14-Oct-2026",
        "990202;-;-;Quorra Nifty200 Momentum 30 Index Fund;Direct Plan;Growth;30.0000;14-Oct-2026",
    ]),
    ("Open Ended Schemes(Debt Scheme - Overnight Fund)", "Quorra Mutual Fund", [
        "990301;-;-;Quorra Overnight Fund;Direct Plan;Growth;1200.0000;14-Oct-2026",
    ]),
]  # fmt: skip


def navall_bytes() -> bytes:
    lines = [HEADER, " "]
    for section, amc, rows in NAVALL_ROWS:
        lines += [section, " ", amc, " ", *rows, " "]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def fetcher(handler: Any) -> Fetcher:
    return Fetcher(
        transport=httpx.MockTransport(handler), resolver=lambda _h: [PUBLIC_IP], jitter_seed=1, sleep=lambda _s: None,
        clock=lambda: NOW, breaker=CircuitBreaker(clock=lambda: NOW),
    )  # fmt: skip


def navall_handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "www.amfiindia.com":
        return httpx.Response(302, headers={"location": "https://portal.amfiindia.com/spages/NAVAll.txt"})
    return httpx.Response(200, headers={"content-type": "text/plain"}, content=navall_bytes())


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(tmp_path / "x.db")
    migrate(c, NOW.isoformat())
    ing.sync_sources(c)
    yield c
    c.close()


@pytest.fixture
def stored(conn: sqlite3.Connection) -> sqlite3.Connection:
    summary = ing.ingest_navall(conn, fetcher(navall_handler), lambda: NOW)
    assert summary.status == "ok", summary
    return conn


def _obs(code: int, day: str, source: str = "amfi.navhistory", value: str = "10.0000") -> ObservationRow:
    return ObservationRow(f"nav:{code}", "nav", value, "INR/unit", "INR", day, NOW.isoformat(), source,
                          "https://portal.amfiindia.com/synthetic", "ok", "0" * 64)  # fmt: skip


def _count(conn: sqlite3.Connection, sql: str, *params: object) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


# ------------------------------------------------------------------------------------ the role file


def test_role_file_has_roles_only_and_respects_the_cap() -> None:
    text = ing.CORE_UNIVERSE_FILE.read_text(encoding="utf-8")
    assert not re.search(r"(?<![\d-])\d{5,}(?![\d-])", text), "no scheme codes in the public role file"
    assert not re.search(r"\bIN[A-Z0-9]{9}\d\b", text), "no ISINs in the public role file"
    spec = ing.load_core_universe()
    assert 1 <= len(spec.roles) <= spec.max_schemes <= 30  # U-07 default
    assert len({r.role for r in spec.roles}) == len(spec.roles)
    assert all(r.role.endswith(".direct") for r in spec.roles)
    assert spec.history_floor == date(2013, 1, 1)
    assert spec.status == "NOT VERIFIED"


@pytest.mark.parametrize(
    "bad",
    [
        "schema_version: 1\nplan: direct\noption: growth\nmax_schemes: 30\nhistory_floor: '2013-01-01'\nroles:\n"
        "  - {role: index_fund.x.direct, category_any: ['index'], name_all: ['x'], code: 123456}\n",
        "schema_version: 1\nplan: regular\noption: growth\nmax_schemes: 30\nhistory_floor: '2013-01-01'\nroles:\n"
        "  - {role: index_fund.x.direct, category_any: ['index'], name_all: ['x']}\n",
        "schema_version: 1\nplan: direct\noption: growth\nmax_schemes: 1\nhistory_floor: '2013-01-01'\nroles:\n"
        "  - {role: index_fund.x.direct, category_any: ['index'], name_all: ['x']}\n"
        "  - {role: index_fund.y.direct, category_any: ['index'], name_all: ['y']}\n",
        "schema_version: 1\nplan: direct\noption: growth\nmax_schemes: 30\nhistory_floor: '2013-01-01'\nroles:\n"
        "  - {role: index_fund.x.direct, category_any: ['index'], name_all: ['x']}\n"
        "  - {role: index_fund.x.direct, category_any: ['index'], name_all: ['x']}\n",
        "schema_version: 1\nplan: direct\noption: growth\nmax_schemes: 30\nhistory_floor: '2013-01-01'\nroles:\n"
        "  - {role: index_fund.x.direct, category_any: ['('], name_all: ['x']}\n",
    ],
)
def test_role_file_validation_fails_closed(bad: str) -> None:
    with pytest.raises(ValueError):
        ing.parse_core_universe(bad)


# ------------------------------------------------------------------------------------ proposal (stores nothing)


def test_proposal_is_deterministic_direct_growth_only_and_stores_nothing(stored: sqlite3.Connection) -> None:
    before = (
        _count(stored, "SELECT COUNT(*) FROM rule_role_bindings"),
        _count(stored, "SELECT COUNT(*) FROM settings"),
    )
    props = {p.role: p for p in ing.propose_core_universe(stored)}
    assert props == {p.role: p for p in ing.propose_core_universe(stored)}  # deterministic
    n50 = props["index_fund.nifty50.direct"]
    # Two Direct-Growth Nifty 50 candidates; neither the Regular plan, the IDCW option, the Nifty 500, the Next 50 nor
    # the equal-weight variant qualifies. Equal stored history and no expense ratio -> the stable code tie-break.
    assert (n50.status, n50.amfi_code, n50.candidates, n50.decided_by) == ("PROPOSED", 990101, 2, "lowest_amfi_code")
    assert props["index_fund.nifty500.direct"].amfi_code == 990104
    assert props["index_fund.niftynext50.direct"].amfi_code == 990105
    assert props["index_fund.nifty200_momentum30.direct"].amfi_code == 990202
    assert props["debt.overnight.direct"].amfi_code == 990301
    assert props["index_fund.smallcap250.direct"].status == "NO_CANDIDATE"
    assert props["index_fund.smallcap250.direct"].instrument_id is None
    assert before == (_count(stored, "SELECT COUNT(*) FROM rule_role_bindings"),
                      _count(stored, "SELECT COUNT(*) FROM settings"))  # fmt: skip
    assert ing.core_universe_codes(stored, hosted=False) == set()  # nothing tracked until the user confirms


def test_longest_stored_history_wins_then_lower_cost(stored: sqlite3.Connection) -> None:
    upsert_observations_batch(stored, [_obs(990201, "2015-06-01")])  # the higher code now has the longer history
    n50 = {p.role: p for p in ing.propose_core_universe(stored)}["index_fund.nifty50.direct"]
    assert (n50.amfi_code, n50.first_nav_date, n50.decided_by) == (990201, "2015-06-01", "longest_stored_history")
    upsert_observations_batch(stored, [_obs(990101, "2015-06-01")])  # equal history again -> expense ratio decides
    stored.execute("UPDATE mf_schemes SET expense_ratio='0.0020' WHERE instrument_id='mf:990101'")
    stored.execute("UPDATE mf_schemes SET expense_ratio='0.0010' WHERE instrument_id='mf:990201'")
    n50 = {p.role: p for p in ing.propose_core_universe(stored)}["index_fund.nifty50.direct"]
    assert (n50.amfi_code, n50.decided_by) == (990201, "lowest_expense_ratio")


# ------------------------------------------------------------------------------------ confirmation (U-07, U-01)


def test_confirmation_is_refused_hosted(stored: sqlite3.Connection) -> None:
    with pytest.raises(ing.CoreUniverseError) as e:
        ing.confirm_core_universe(stored, {"index_fund.nifty50.direct": "mf:990101"}, hosted=True, now=NOW)
    assert e.value.code == "CORE_UNIVERSE_LOCAL_ONLY"
    assert role_bindings(stored) == {} and ing.core_universe_codes(stored, hosted=False) == set()


@pytest.mark.parametrize(
    ("bindings", "code"),
    [
        ({}, "NOTHING_TO_CONFIRM"),
        ({"index_fund.unknown.direct": "mf:990101"}, "UNKNOWN_ROLE"),
        ({"index_fund.nifty50.direct": "mf:990102"}, "NOT_DIRECT_PLAN"),
        ({"index_fund.nifty50.direct": "mf:990103"}, "NOT_GROWTH_OPTION"),
        ({"index_fund.nifty50.direct": "mf:123"}, "UNKNOWN_INSTRUMENT"),
        ({"index_fund.nifty50.direct": "mf:990101", "index_fund.nifty500.direct": "mf:990101"}, "DUPLICATE_INSTRUMENT"),
    ],
)
def test_confirmation_validates_every_binding(stored: sqlite3.Connection, bindings: dict[str, str], code: str) -> None:
    # A held Regular plan and an IDCW option are stored too (e.g. from a CAS); neither can be a U1 binding.
    stored.execute("BEGIN")
    ing._store_schemes(stored, [
        SchemeRecord(990102, "Zephyr Nifty 50 Index Fund", amc="Zephyr Mutual Fund", category="Other Scheme - Index "
                     "Funds", plan="Regular Plan", option="Growth Option"),
        SchemeRecord(990103, "Zephyr Nifty 50 Index Fund", amc="Zephyr Mutual Fund", category="Other Scheme - Index "
                     "Funds", plan="Direct Plan", option="IDCW Option"),
    ], NOW)  # fmt: skip
    stored.execute("COMMIT")
    with pytest.raises(ing.CoreUniverseError) as e:
        ing.confirm_core_universe(stored, bindings, hosted=False, now=NOW)
    assert e.value.code == code
    assert role_bindings(stored) == {}


def test_confirmation_respects_the_cap(stored: sqlite3.Connection) -> None:
    spec = ing.load_core_universe()
    small = ing.CoreUniverseSpec(spec.universe_id, spec.status, 1, spec.history_floor, spec.selection_rule, spec.roles)
    ing.confirm_core_universe(stored, {"index_fund.nifty50.direct": "mf:990101"}, hosted=False, now=NOW, spec=small)
    with pytest.raises(ing.CoreUniverseError) as e:
        ing.confirm_core_universe(stored, {"debt.overnight.direct": "mf:990301"}, hosted=False, now=NOW, spec=small)
    assert e.value.code == "TOO_MANY_SCHEMES"


def test_confirmed_universe_is_tracked_locally_only(stored: sqlite3.Connection) -> None:
    out = ing.confirm_core_universe(
        stored, {"index_fund.nifty50.direct": "mf:990101", "debt.overnight.direct": "mf:990301"}, hosted=False, now=NOW
    )
    assert out["roles"] == ["debt.overnight.direct", "index_fund.nifty50.direct"] and out["mode"] == "local"
    assert role_bindings(stored) == {"index_fund.nifty50.direct": "mf:990101", "debt.overnight.direct": "mf:990301"}
    assert ing.core_universe_codes(stored, hosted=False) == {990101, 990301}
    assert ing.core_universe_codes(stored, hosted=True) == set()  # U-01: never hosted
    # A later partial confirmation merges; withdrawing stops tracking.
    ing.confirm_core_universe(stored, {"index_fund.nifty500.direct": "mf:990104"}, hosted=False, now=NOW)
    assert ing.core_universe_codes(stored, hosted=False) == {990101, 990104, 990301}
    assert ing.withdraw_core_universe(stored) is True
    assert ing.core_universe_codes(stored, hosted=False) == set()


def test_a_confirmation_record_not_marked_local_is_ignored(stored: sqlite3.Connection) -> None:
    ing.confirm_core_universe(stored, {"index_fund.nifty50.direct": "mf:990101"}, hosted=False, now=NOW)
    rec = json.loads(stored.execute("SELECT value_json FROM settings WHERE key=?", (ing.CORE_CONFIRMED_KEY,))
                     .fetchone()[0])  # fmt: skip
    rec["mode"] = "hosted"
    stored.execute("UPDATE settings SET value_json=? WHERE key=?", (json.dumps(rec), ing.CORE_CONFIRMED_KEY))
    assert ing.core_universe_codes(stored, hosted=False) == set()


def test_confirmed_core_navs_are_kept_by_the_daily_ingest_unconfirmed_ones_pruned(stored: sqlite3.Connection) -> None:
    older = [_obs(990101, "2026-10-13", "amfi.navall"), _obs(990201, "2026-10-13", "amfi.navall")]
    upsert_observations_batch(stored, older)
    ing.confirm_core_universe(stored, {"index_fund.nifty50.direct": "mf:990101"}, hosted=False, now=NOW)
    ing.ingest_navall(stored, fetcher(navall_handler), lambda: NOW)
    dates = {
        (r["series_id"], r["observation_date"])
        for r in stored.execute("SELECT series_id, observation_date FROM observations WHERE source_id='amfi.navall'")
    }
    assert ("nav:990101", "2026-10-13") in dates  # confirmed U1: tracked like a holding, so not pruned
    assert ("nav:990201", "2026-10-13") not in dates  # not confirmed: latest NAV only (data minimisation)


# ------------------------------------------------------------------------------------ automatic gap fill

HALCYON = load_fixture("amfi_navhistory_excerpt.txt")  # fictional "Halcyon Mutual Fund", rows on 13/14-Oct-2026
NO_DATA = b"<!DOCTYPE html><html><head><title>\r\n\tView/Download NAV History\r\n</title></head></html>"


class History:
    def __init__(self) -> None:
        self.windows: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        q = parse_qs(request.url.query.decode())
        frm = datetime.strptime(q["frmdt"][0], "%d-%b-%Y").date()
        to = datetime.strptime(q["todt"][0], "%d-%b-%Y").date()
        self.windows.append((frm.isoformat(), to.isoformat()))
        if int(q["mf"][0]) == 9 and frm <= date(2026, 10, 13) <= to:
            return httpx.Response(200, headers={"content-type": "text/plain"}, content=HALCYON)
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=NO_DATA)


@pytest.fixture
def halcyon(conn: sqlite3.Connection) -> sqlite3.Connection:
    recs = [
        SchemeRecord(928470, "Halcyon Large Cap Fund - Growth Option - Direct Plan", amc="Halcyon Mutual Fund",
                     category="Equity Scheme - Large Cap Fund", plan="Direct Plan", option="Growth Option"),
        SchemeRecord(971181, "Halcyon Multi Cap Fund - Growth Option - Direct Plan", amc="Halcyon Mutual Fund",
                     category="Equity Scheme - Multi Cap Fund", plan="Direct Plan", option="Growth Option"),
    ]  # fmt: skip
    conn.execute("BEGIN")
    ing._store_schemes(conn, recs, NOW)
    conn.execute("INSERT INTO settings(key, value_json) VALUES ('amfi.mf_id:halcyon mutual fund', '9')")
    conn.execute("COMMIT")
    return conn


def test_nothing_is_fetched_before_confirmation(halcyon: sqlite3.Connection) -> None:
    amfi = History()
    out = ing.track_core_universe(halcyon, fetcher(amfi), now=lambda: NOW, pause=None, hosted=False)
    assert out["status"] == "NOT_CONFIRMED" and amfi.windows == []


def test_tracking_refuses_hosted(halcyon: sqlite3.Connection) -> None:
    with pytest.raises(ing.CoreUniverseError) as e:
        ing.track_core_universe(halcyon, fetcher(History()), now=lambda: NOW, pause=None, hosted=True)
    assert e.value.code == "CORE_UNIVERSE_LOCAL_ONLY"


def test_confirmed_universe_is_backfilled_then_gap_filled_without_manual_backfill(halcyon: sqlite3.Connection) -> None:
    ing.confirm_core_universe(
        halcyon, {"index_fund.nifty50.direct": "mf:928470", "index_fund.nifty500.direct": "mf:971181"},
        hosted=False, now=NOW,
    )  # fmt: skip
    gaps = ing.core_universe_gaps(halcyon, hosted=False, floor=date(2026, 6, 1))
    assert [(g.amfi_code, g.start) for g in gaps] == [(928470, date(2026, 6, 1)), (971181, date(2026, 6, 1))]

    amfi = History()
    out = ing.track_core_universe(halcyon, fetcher(amfi), now=lambda: NOW, pause=None, hosted=False,
                                  floor=date(2026, 6, 1))  # fmt: skip
    assert out["status"] == "ok" and out["schemes"] == 2 and len(out["batches"]) == 1
    assert out["batches"][0]["stored"] == 4  # 2 schemes x 2 days; the other schemes in the file are not kept
    series = {r[0] for r in halcyon.execute("SELECT DISTINCT series_id FROM observations")}
    assert series == {"nav:928470", "nav:971181"}
    assert len(amfi.windows) == 2  # one fund house, two 90-day windows, no fund-house probe (id cached)

    # Next run: a gap fill from the day after the newest stored history row, not a fresh backfill.
    gaps = ing.core_universe_gaps(halcyon, hosted=False, floor=date(2026, 6, 1))
    assert {g.start for g in gaps} == {date(2026, 10, 15)}
    amfi2 = History()
    out2 = ing.track_core_universe(halcyon, fetcher(amfi2), now=lambda: NOW, pause=None, hosted=False,
                                   floor=date(2026, 6, 1))  # fmt: skip
    assert amfi2.windows == [("2026-10-15", "2026-10-15")]
    assert out2["batches"][0]["schemes"] == [928470, 971181]


def test_up_to_date_universe_makes_no_request(halcyon: sqlite3.Connection) -> None:
    ing.confirm_core_universe(halcyon, {"index_fund.nifty50.direct": "mf:928470"}, hosted=False, now=NOW)
    upsert_observations_batch(halcyon, [_obs(928470, "2026-10-15")])
    amfi = History()
    out = ing.track_core_universe(halcyon, fetcher(amfi), now=lambda: NOW, pause=None, hosted=False)
    assert out["status"] == "up_to_date" and out["up_to_date"] == 1 and amfi.windows == []


def test_tracking_waits_for_a_running_backfill(halcyon: sqlite3.Connection) -> None:
    ing.confirm_core_universe(halcyon, {"index_fund.nifty50.direct": "mf:928470"}, hosted=False, now=NOW)
    ing.start_batch_backfill(halcyon, groups={"Halcyon Mutual Fund": [971181]}, skipped=[],
                             start=date(2026, 10, 1), end=date(2026, 10, 14), now=lambda: NOW)  # fmt: skip
    with pytest.raises(ing.CoreUniverseError) as e:
        ing.track_core_universe(halcyon, fetcher(History()), now=lambda: NOW, pause=None, hosted=False)
    assert e.value.code == "BACKFILL_IN_PROGRESS"


def test_command_line_refuses_hosted_configuration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IIP_DEPLOY", "vercel")
    assert ing.main(["track-core-universe", "--db", str(tmp_path / "x.db")]) == 2
    monkeypatch.setenv("IIP_DEPLOY", "local")
    assert ing.main(["track-core-universe", "--db", str(tmp_path / "missing.db")]) == 2


# ------------------------------------------------------------------------------------ 2027 holiday-calendar task


def test_the_2027_nse_holiday_calendar_task_is_recorded(conn: sqlite3.Connection) -> None:
    tasks = {t.task_id: t for t in ing.holiday_calendar_tasks(conn, date(2026, 10, 16))}
    t = tasks["NSE_HOLIDAY_CALENDAR_2027"]
    assert (t.status, t.due) == ("OPEN", "2026-12-31")
    assert "by hand" in t.title and "no automated fetch" in t.detail
    assert ing.nse_holidays(conn, 2027) is None

    # Typed from the circular (these dates are placeholders for the test, not NSE's 2027 holidays).
    n = ing.record_nse_holidays(conn, 2027, [date(2027, 1, 26), date(2027, 1, 26), date(2027, 8, 16)],
                                circular_ref="NSE circular (test placeholder)", now=NOW)  # fmt: skip
    assert n == 2
    assert ing.nse_holidays(conn, 2027) == frozenset({date(2027, 1, 26), date(2027, 8, 16)})
    done = {t.task_id: t for t in ing.holiday_calendar_tasks(conn, date(2026, 10, 16))}
    assert done["NSE_HOLIDAY_CALENDAR_2027"].status == "DONE"


def test_next_year_task_opens_in_october_and_bad_entries_are_refused(conn: sqlite3.Connection) -> None:
    assert [t.task_id for t in ing.holiday_calendar_tasks(conn, date(2026, 9, 30))] == ["NSE_HOLIDAY_CALENDAR_2026"]
    with pytest.raises(ValueError):
        ing.record_nse_holidays(conn, 2027, [date(2026, 12, 25)], circular_ref="ref", now=NOW)
    with pytest.raises(ValueError):
        ing.record_nse_holidays(conn, 2027, [date(2027, 1, 26)], circular_ref=" ", now=NOW)
    with pytest.raises(ValueError):
        ing.record_nse_holidays(conn, 2027, [], circular_ref="ref", now=NOW)
