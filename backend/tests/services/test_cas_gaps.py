"""CAS gaps (PLAN.md row B06): Regular-plan ISINs accepted, exit loads charged recorded as observed facts, and a new
CAS confirming or contradicting "I did this" entries.

Every statement is SYNTHETIC (tests/services/cas_synthetic.py: fictional investor, AMC, schemes and ISINs with the
non-existent issuer prefix INFZZ); the AMFI file is synthetic AMFI-format bytes over MockTransport (no network)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from iip.data.fetch import CircuitBreaker, Fetcher
from iip.engine.actions.contracts import Step, Verb
from iip.services import cas
from iip.services import ingestion as ing
from iip.services import portfolio as pf
from iip.store.db import connect, migrate
from iip.store.ledger import Decision, append_decisions
from tests.data.test_fetch import PUBLIC_IP
from tests.services import cas_synthetic as syn
from tests.services.test_portfolio import NOW, make_pf, seed_market

GROWTH = "mf:990001"  # carries syn.ISIN_GROWTH
IDCW = "mf:990002"  # carries syn.ISIN_IDCW
ISIN_REGULAR = syn.fictional_isin("INFZZ0009R0")


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(tmp_path / "x.db")
    migrate(c, NOW.isoformat())
    seed_market(c)
    c.execute("UPDATE instruments SET isin=? WHERE instrument_id=?", (syn.ISIN_GROWTH, GROWTH))
    c.execute("UPDATE instruments SET isin=? WHERE instrument_id=?", (syn.ISIN_IDCW, IDCW))
    yield c
    c.close()


def preview(conn: sqlite3.Connection, pid: str, st: syn.Statement | None = None, **kw: Any) -> dict[str, Any]:
    return cas.preview_cas_import(conn, pid, syn.build_pdf(st), syn.PASSWORD, NOW, **kw)


def apply(conn: sqlite3.Connection, p: dict[str, Any], **kw: Any) -> dict[str, Any]:
    body = cas.CasApplyIn(sha256=str(p["file_sha256"]), accept_reconciliation_mismatches=True)
    return cas.apply_cas_import(conn, str(p["batch_id"]), body, NOW, **kw)


def T(kind: str, units: str | None, amount: str | None, nav: str | None = "11.0000") -> cas.CasTxn:
    return cas.CasTxn(date(2024, 4, 15), kind, None if amount is None else Decimal(amount),
                      None if units is None else Decimal(units), None if nav is None else Decimal(nav))  # fmt: skip


# ------------------------------------------------------------------------------------ observed exit loads


def test_exit_load_observation_rules() -> None:
    none = cas.observe_exit_load(T("REDEMPTION", "-30.000", "330.00"), None)
    assert none is not None and none["observation"] == "NO_LOAD_OBSERVED" and none["exit_load_inr"] == "0"
    one = cas.observe_exit_load(T("REDEMPTION", "-30.000", "326.70"), None)
    assert one is not None and (one["observation"], one["exit_load_inr"], one["implied_rate"]) == (
        "LOAD_OBSERVED",
        "3.30",
        "0.010000",
    )
    assert one["status"] == "NOT VERIFIED" and one["formula_id"] == "cas_exit_load_implied@1"
    assert one["flags"] == ["PRICE_ASSUMED_NAV_BEFORE_LOAD"]
    with_stt = cas.observe_exit_load(T("REDEMPTION", "-30.000", "326.70"), Decimal("0.01"))
    assert with_stt is not None and with_stt["exit_load_inr"] == "3.29"
    assert "STT_SEPARATION_NOT_VERIFIED" in with_stt["flags"]
    bad = cas.observe_exit_load(T("REDEMPTION", "-30.000", "340.00"), None)
    assert bad is not None and bad["observation"] == "INCONSISTENT" and bad["exit_load_inr"] is None
    assert cas.observe_exit_load(T("REDEMPTION", "-30.000", "330.00", nav=None), None) is None
    assert cas.observe_exit_load(T("REDEMPTION", None, "330.00"), None) is None


def _statement_with_load() -> syn.Statement:
    rows = (
        syn.Row("10-Jan-2024", "Purchase", "1,000.00", "100.000", "10.0000", "100.000"),
        syn.Row("15-Apr-2024", "Redemption", "326.70", "(30.000)", "11.0000", "70.000"),
        syn.Row("15-Apr-2024", "*** STT Paid ***", "0.01"),
    )
    return syn.Statement(schemes=(syn.SchemeBlock("Z1G", "Zeta Example Flexi Cap Fund - Direct Plan - Growth",
                                                  syn.ISIN_GROWTH, "0.000", "70.000", rows),))  # fmt: skip


def test_exit_load_charged_in_the_cas_is_recorded_as_an_observed_fact(conn: sqlite3.Connection) -> None:
    pid = make_pf(conn)
    p = preview(conn, pid, _statement_with_load())
    [obs] = p["observed_exit_loads"]
    assert (obs["instrument_id"], obs["txn_date"], obs["observation"]) == (GROWTH, "2024-04-15", "LOAD_OBSERVED")
    assert obs["exit_load_inr"] == "3.29" and obs["stt_same_day"] == "0.01"  # STT row subtracted, and flagged
    assert cas.observed_exit_loads(conn, GROWTH) == []  # a preview is not a fact yet
    out = apply(conn, p)
    assert out["observed_exit_loads"] == 1
    [kept] = cas.observed_exit_loads(conn, GROWTH)
    assert kept["batch_id"] == p["batch_id"] and kept["implied_rate"] == "0.009970" and kept["status"] == "NOT VERIFIED"
    assert cas.observed_exit_loads(conn, IDCW) == []


def test_default_statement_observes_no_load(conn: sqlite3.Connection) -> None:
    p = preview(conn, make_pf(conn))
    assert {o["observation"] for o in p["observed_exit_loads"]} == {"NO_LOAD_OBSERVED"}
    assert len(p["observed_exit_loads"]) == 2  # one redemption, one switch-out


# ------------------------------------------------------------------------------------ Regular-plan ISINs


def _navall_with_regular_plan() -> bytes:
    lines = [
        "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date",
        " ", "Open Ended Schemes(Equity Scheme - Flexi Cap Fund)", " ", "Zeta Example Mutual Fund", " ",
        f"990777;{ISIN_REGULAR};-;Zeta Example Flexi Cap Fund;Regular Plan;Growth Option;10.5000;14-Oct-2026", " ",
    ]  # fmt: skip
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def _amfi(request: httpx.Request) -> httpx.Response:
    if request.url.host == "www.amfiindia.com":
        return httpx.Response(302, headers={"location": "https://portal.amfiindia.com/spages/NAVAll.txt"})
    return httpx.Response(200, headers={"content-type": "text/plain"}, content=_navall_with_regular_plan())


def test_regular_plan_isin_is_accepted_by_exact_isin_lookup(conn: sqlite3.Connection) -> None:
    fetcher = Fetcher(transport=httpx.MockTransport(_amfi), resolver=lambda _h: [PUBLIC_IP], jitter_seed=1,
                      sleep=lambda _s: None, clock=lambda: NOW, breaker=CircuitBreaker(clock=lambda: NOW))  # fmt: skip
    ing.sync_sources(conn)
    rows = (syn.Row("10-Jan-2024", "Purchase", "1,000.00", "100.000", "10.0000", "100.000"),)
    st = syn.Statement(schemes=(syn.SchemeBlock("Z7R", "Zeta Example Flexi Cap Fund - Regular Plan - Growth",
                                                ISIN_REGULAR, "0.000", "100.000", rows),))  # fmt: skip
    pid = make_pf(conn)
    p = preview(conn, pid, st, resolve_isins=lambda isins: ing.register_schemes_by_isin(conn, fetcher, isins,
                                                                                       lambda: NOW))  # fmt: skip
    assert p["rejected"] == [] and [r["instrument_id"] for r in p["will_store"]] == ["mf:990777"]
    assert p["schemes"][0]["match"] == "EXACT_ISIN"
    plan = conn.execute("SELECT plan FROM mf_schemes WHERE instrument_id='mf:990777'").fetchone()[0]
    assert plan == "regular"
    assert apply(conn, p)["transactions_created"] == 1
    # Once held, the Regular plan stays in the minimised NAV scope (held schemes are tracked, U-01).
    assert 990777 in ing.tracked_scheme_codes(conn)


# ------------------------------------------------------------------------------------ "I did this" vs the CAS


def test_moves_from_steps_maps_only_what_a_statement_can_show() -> None:
    steps = [
        Step(Verb.INVEST, "mf:1", "next_rupee@1", amount_inr=Decimal("100")),
        Step(Verb.REDEEM, "mf:2", "rebalance@1", units=Decimal("1")),
        Step(Verb.SWITCH, "mf:3", "reg_to_direct@1"),
        Step(Verb.REDIRECT_SIP, "mf:4", "next_rupee@1"),
        Step(Verb.REVIEW, None, "review@1"),
        Step(Verb.INVEST, None, "next_rupee@1"),
    ]
    assert cas.moves_from_steps(steps) == (
        cas.ExpectedMove("mf:1", "in"),
        cas.ExpectedMove("mf:2", "out"),
        cas.ExpectedMove("mf:3", "out"),
    )


def test_judge_confirms_contradicts_or_abstains() -> None:
    seen = [["mf:1", "2024-04-15", "out"], ["mf:2", "2024-02-10", "in"]]
    checks = [
        cas.DecisionCheck(1, date(2024, 4, 14), (cas.ExpectedMove("mf:1", "out"),)),  # seen the next day
        cas.DecisionCheck(2, date(2024, 2, 15), (cas.ExpectedMove("mf:2", "in"),)),  # seen 5 days before the click
        cas.DecisionCheck(3, date(2024, 6, 1), (cas.ExpectedMove("mf:2", "in"),)),  # nothing in a covered window
        cas.DecisionCheck(4, date(2025, 3, 28), (cas.ExpectedMove("mf:2", "in"),)),  # window runs past the statement
        cas.DecisionCheck(5, date(2024, 6, 1), ()),  # nothing a statement can show
        cas.DecisionCheck(6, date(2024, 4, 14), (cas.ExpectedMove("mf:1", "in"),)),  # wrong direction
        cas.DecisionCheck(7, date(2024, 4, 14), (cas.ExpectedMove("mf:1", "out"), cas.ExpectedMove("mf:9", "in"))),
    ]
    out = cas.judge_decisions(checks, seen, date(2024, 1, 1), date(2025, 3, 31))
    assert out == {1: "CONFIRMED", 2: "CONFIRMED", 3: "CONTRADICTED", 4: "UNDETERMINED", 5: "UNDETERMINED",
                   6: "CONTRADICTED", 7: "CONTRADICTED"}  # fmt: skip
    assert set(cas.judge_decisions(checks, seen, None, None).values()) <= {"CONFIRMED", "UNDETERMINED"}


def _decide(conn: sqlite3.Connection, card: str, day: str) -> int:
    append_decisions(conn, [Decision(card, None, None, "done", None, f"{day}T10:00:00+05:30")])
    return int(conn.execute("SELECT MAX(decision_id) FROM decisions_log").fetchone()[0])


def test_a_new_cas_confirms_or_contradicts_i_did_this_once(conn: sqlite3.Connection) -> None:
    d_ok = _decide(conn, "card-redeem", "2024-04-14")
    d_no = _decide(conn, "card-invest", "2024-06-01")
    d_late = _decide(conn, "card-late", "2025-03-28")
    assert [r["decision_id"] for r in cas.pending_done_decisions(conn)] == [d_ok, d_no, d_late]
    checks = [
        cas.DecisionCheck(d_ok, date(2024, 4, 14), (cas.ExpectedMove(GROWTH, "out"),)),
        cas.DecisionCheck(d_no, date(2024, 6, 1), (cas.ExpectedMove(IDCW, "in"),)),
        cas.DecisionCheck(d_late, date(2025, 3, 28), (cas.ExpectedMove(GROWTH, "in"),)),
    ]
    p = preview(conn, make_pf(conn))  # default synthetic statement: 01-Jan-2024 to 31-Mar-2025
    out = apply(conn, p, decisions=checks)
    assert out["decisions"] == {"confirmed": [d_ok], "contradicted": [d_no], "undetermined": [d_late], "written": 2}
    rows = {r["decision_id"]: r for r in conn.execute("SELECT * FROM decisions_log")}
    assert (rows[d_ok]["cas_confirmed"], rows[d_ok]["cas_import_ref"]) == (1, p["batch_id"])
    assert rows[d_no]["cas_confirmed"] == 0 and rows[d_late]["cas_confirmed"] is None
    assert [r["decision_id"] for r in cas.pending_done_decisions(conn)] == [d_late]

    # Checking again against the same batch never changes a verdict already recorded (set once).
    again = cas.confirm_decisions_with_cas(conn, str(p["batch_id"]), checks, NOW)
    assert again["written"] == 0
    assert conn.execute("SELECT cas_confirmed FROM decisions_log WHERE decision_id=?", (d_no,)).fetchone()[0] == 0


def test_only_an_applied_cas_batch_can_confirm(conn: sqlite3.Connection) -> None:
    p = preview(conn, make_pf(conn))
    with pytest.raises(pf.PortfolioError) as e:
        cas.confirm_decisions_with_cas(conn, str(p["batch_id"]), [], NOW)
    assert e.value.code == "NOT_APPLIED"
    with pytest.raises(pf.PortfolioError) as e2:
        cas.confirm_decisions_with_cas(conn, "imp_missing", [], NOW)
    assert e2.value.code == "NOT_FOUND"


def test_idcw_reinvestment_is_not_taken_as_an_investment_decision() -> None:
    seen = cas._seen_moves([
        {"instrument_id": "mf:1", "txn_date": "2024-06-28", "txn_type": "buy", "flags": ["IDCW_REINVESTED_AS_BUY"]},
        {"instrument_id": "mf:1", "txn_date": "2024-06-29", "txn_type": "dividend", "flags": []},
        {"instrument_id": "mf:1", "txn_date": "2024-06-30", "txn_type": "sell", "flags": ["SWITCH"]},
    ])  # fmt: skip
    assert seen == [["mf:1", "2024-06-30", "out"]]
