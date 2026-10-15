"""Stage D services: portfolios, FIFO, import, summary, watchlist, alerts, evidence, privacy.

All instruments and NAVs here are SYNTHETIC test values (named "TEST …", cited to https://fixture.invalid/), chosen so
every expected figure can be computed by hand in the comments. They are not market data.
"""

import logging
import sqlite3
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from iip.data.imports import ImportRejected
from iip.services import alerts as al
from iip.services import portfolio as pf
from iip.store.db import connect, current_version, migrate
from iip.store.observations import ObservationRow, upsert_observation
from iip.supervisor import compliance

NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)  # Thursday; IST 11:30
URL = "https://fixture.invalid/test"
FUNDS = (
    # code, name, category, [(date, nav)]
    (990001, "TEST Liquid Fund A", "Debt Scheme - Liquid Fund", [("2026-10-14", "12.3456")]),
    (990002, "TEST Large Cap Fund B", "Equity Scheme - Large Cap Fund", [("2026-10-14", "20.0001")]),
    (990003, "TEST Short Duration Fund C", "Debt Scheme - Short Duration Fund", [("2026-09-01", "15.0000")]),
    (990004, "TEST Flexi Cap Fund D", "Equity Scheme - Flexi Cap Fund", [("2026-01-05", "100.0000"),
                                                                       ("2026-10-14", "85.0000")]),
)  # fmt: skip
FD = "fd:test-bank:180d"


def nav(conn: sqlite3.Connection, code: int, d: str, value: str, quality: str = "ok") -> None:
    upsert_observation(conn, ObservationRow(
        series_id=f"nav:{code}", kind="nav", value=value, unit="INR/unit", currency="INR", observation_date=d,
        retrieved_at=NOW.isoformat(), source_id="test.synthetic", source_url=URL, quality_status=quality,
        raw_sha256="a" * 64, convention="synthetic NAV",
    ))  # fmt: skip


def seed_market(conn: sqlite3.Connection) -> None:
    for code, name, cat, navs in FUNDS:
        conn.execute(
            "INSERT INTO instruments(instrument_id, kind, name, amfi_code, origin, created_at)"
            " VALUES (?, 'mf_scheme', ?, ?, 'fixture', ?)",
            (f"mf:{code}", name, str(code), NOW.isoformat()),
        )
        conn.execute(
            "INSERT INTO mf_schemes(instrument_id, amc, category_raw, sebi_category, plan) VALUES (?,?,?,?,'direct')",
            (f"mf:{code}", "TEST AMC", cat, cat),
        )
        for d, v in navs:
            nav(conn, code, d, v)
    conn.execute(
        "INSERT INTO instruments(instrument_id, kind, name, origin, created_at) VALUES (?, 'fd', ?, 'manual', ?)",
        (FD, "TEST Bank FD — 180 days", NOW.isoformat()),
    )
    conn.execute(
        "INSERT INTO deposit_terms(instrument_id, institution, rate, compounding, tenure_days, dicgc_eligible,"
        " rate_as_of, citation_url) VALUES (?, 'TEST Bank', '0.0700', 'quarterly', 180, 1, '2026-10-01', ?)",
        (FD, URL),
    )


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(tmp_path / "x.db")
    migrate(c, NOW.isoformat())
    seed_market(c)
    yield c
    c.close()


def make_pf(conn: sqlite3.Connection, name: str = "Core", nature: str = "actual") -> str:
    return str(pf.create_portfolio(conn, pf.PortfolioIn(name=name, nature=nature), NOW)["portfolio_id"])  # type: ignore[arg-type]


def tx(conn: sqlite3.Connection, pid: str, iid: str, d: str, kind: str, units: str, amount: str) -> dict[str, object]:
    body = pf.TransactionIn.model_validate(
        {"instrument_id": iid, "txn_date": d, "txn_type": kind, "units": units, "amount": amount}
    )
    return pf.add_transaction(conn, pid, body, NOW)


def standard_book(conn: sqlite3.Connection) -> str:
    pid = make_pf(conn)
    tx(conn, pid, "mf:990001", "2025-01-10", "buy", "100", "1000.00")
    tx(conn, pid, "mf:990002", "2025-03-03", "buy", "50.5", "900.00")
    tx(conn, pid, "mf:990003", "2025-06-02", "buy", "10", "140.00")
    tx(conn, pid, FD, "2026-05-10", "buy", "1", "600000.00")  # matures 2026-11-06 (180 days)
    return pid


# ----------------------------------------------------------------------------- FIFO


def T(i: str, d: str, kind: str, units: str, amount: str) -> pf.Txn:
    return pf.Txn(i, "mf:1", date.fromisoformat(d), kind, Decimal(units), Decimal(amount), f"2026-01-01T00:00:0{i}")


def test_fifo_consumes_oldest_lots_first() -> None:
    pos = pf.fifo_positions([
        T("1", "2025-01-01", "buy", "10", "1000"),
        T("2", "2025-02-01", "buy", "10", "1200"),
        T("3", "2025-03-01", "sell", "15", "1800"),
    ])["mf:1"]  # fmt: skip
    # lot 1 fully (cost 1000) + half of lot 2 (cost 600) consumed → 5 units left at cost 600; realised 1800 − 1600
    assert pos.units == Decimal(5) and pos.cost == Decimal(600)
    assert pos.realised_proceeds - pos.realised_cost == Decimal(200)
    assert [lot.txn_id for lot in pos.lots] == ["2"]


def test_fifo_oversell_is_rejected_never_truncated() -> None:
    """Regression: a FIFO library found in the hidden-gems research silently ignored the excess of an oversell and
    returned a truncated position. Ours must refuse."""
    with pytest.raises(pf.Oversell) as exc:
        pf.fifo_positions([T("1", "2025-01-01", "buy", "10", "1000"), T("2", "2025-02-01", "sell", "10.000001", "1")])
    assert exc.value.held == Decimal(10) and exc.value.requested == Decimal("10.000001")
    # back-dated sell before any buy is also an oversell at that date
    with pytest.raises(pf.Oversell):
        pf.fifo_positions([T("1", "2025-02-01", "buy", "10", "1000"), T("2", "2025-01-01", "sell", "1", "100")])
    # selling exactly what is held is fine and closes the position
    pos = pf.fifo_positions([T("1", "2025-01-01", "buy", "10", "1000"), T("2", "2025-02-01", "sell", "10", "1100")])
    assert pos["mf:1"].units == 0 and pos["mf:1"].lots == ()


def test_api_level_oversell_writes_nothing(conn: sqlite3.Connection) -> None:
    pid = make_pf(conn)
    tx(conn, pid, "mf:990001", "2025-01-10", "buy", "10", "100.00")
    with pytest.raises(pf.Oversell):
        tx(conn, pid, "mf:990001", "2025-02-10", "sell", "11", "150.00")
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
    tx(conn, pid, "mf:990001", "2025-02-10", "sell", "4", "60.00")
    buy = conn.execute("SELECT txn_id FROM transactions WHERE txn_type='buy'").fetchone()[0]
    with pytest.raises(pf.PortfolioError) as exc:  # deleting the buy would leave the sell uncovered
        pf.delete_transaction(conn, pid, buy, NOW)
    assert exc.value.code == "WOULD_OVERSELL"


def test_transaction_input_requires_decimal_strings(conn: sqlite3.Connection) -> None:
    base = {"instrument_id": "mf:990001", "txn_date": "2025-01-10", "txn_type": "buy"}
    for units, amount in [(10.5, "100"), ("10", 100.0), ("1e3", "100"), ("10", "1,000"), ("-1", "5"), ("0", "5"),
                          ("10", "100.001"), ("1.1234567", "100")]:  # fmt: skip
        with pytest.raises(ValueError):
            pf.TransactionIn.model_validate({**base, "units": units, "amount": amount})
    pid = make_pf(conn)
    with pytest.raises(pf.PortfolioError) as exc:
        tx(conn, pid, "mf:990001", "2026-10-16", "buy", "1", "1.00")
    assert exc.value.code == "FUTURE_DATE"
    with pytest.raises(pf.PortfolioError) as exc:
        tx(conn, pid, "mf:nope", "2026-10-01", "buy", "1", "1.00")
    assert exc.value.code == "UNKNOWN_INSTRUMENT"


# ----------------------------------------------------------------------------- summary


def test_summary_reconciles_and_excludes_stale(conn: sqlite3.Connection) -> None:
    pid = standard_book(conn)
    s = pf.portfolio_summary(conn, pid, NOW)
    t = s["totals"]
    # A: 100 × 12.3456 = 1234.56;  B: 50.5 × 20.0001 = 1010.00505 → 1010.01 (paise, HALF_UP)
    assert t["market_value"]["value"] == "2244.57"
    assert t["invested"]["value"] == "1900.00"
    assert t["unrealised_pl"]["value"] == "344.57"
    assert t["invested_all_holdings"] == "602040.00"  # 1000 + 900 + 140 + 600000
    by_id = {h["instrument_id"]: h for h in s["holdings"]}
    assert by_id["mf:990001"]["badge"] == "END_OF_DAY" and by_id["mf:990001"]["included_in_totals"]
    # C's latest NAV (2026-09-01) is STALE: excluded with a note, and NOT forward-filled
    c = by_id["mf:990003"]
    assert c["badge"] == "STALE" and not c["included_in_totals"] and c["market_value"] is None
    assert c["exclusion"]["code"] == "STALE_NAV"
    assert any("TEST Short Duration Fund C" in n and "STALE" in n for n in s["notes"])
    assert by_id[FD]["exclusion"]["code"] == "NOT_VALUED"
    assert "HOLDINGS_EXCLUDED" in s["flags"]
    # Every value is Explained with sources/as-of
    mv = t["market_value"]
    assert mv["observed"] == "2026-10-14 → 2026-10-14" and {x["obs_id"] for x in mv["sources"]}
    assert mv["formula_id"] and mv["hash"] and len(mv["sensitivity"]) >= 2


def test_allocation_sums_to_total_exactly(conn: sqlite3.Connection) -> None:
    pid = standard_book(conn)
    s = pf.portfolio_summary(conn, pid, NOW)
    total = Decimal(s["totals"]["market_value"]["value"])
    for key in ("by_kind", "by_category"):
        items = s["allocation"][key]["items"]
        assert sum(Decimal(i["market_value"]) for i in items) == total
        assert sum(Decimal(i["share"].rstrip("%")) for i in items) == Decimal("100.00")
    cat = {i["key"]: i["share"] for i in s["allocation"]["by_category"]["items"]}
    # 1234.56/2244.57 = 55.00207 % ; 1010.01/2244.57 = 44.99793 % → largest remainder gives 55.00 / 45.00
    assert cat == {"Debt Scheme - Liquid Fund": "55.00%", "Equity Scheme - Large Cap Fund": "45.00%"}
    ladder = s["liquidity_ladder"]["buckets"]
    assert sum(Decimal(b["market_value"]) for b in ladder) == total
    b = {x["bucket"]: x for x in ladder}
    assert b["0-7 days"]["market_value"] == "2244.57"  # liquid T+1, large cap T+3
    assert b["0-7 days"]["at_cost_not_valued"] == "140.00"  # stale fund C, at cost
    assert b["8-30 days"]["at_cost_not_valued"] == "600000.00"  # FD matures 2026-11-06 (22 days)


def test_concentration_xirr_maturities_dicgc(conn: sqlite3.Connection) -> None:
    import pyxirr

    pid = standard_book(conn)
    s = pf.portfolio_summary(conn, pid, NOW)
    w1, w2 = Decimal("1234.56") / Decimal("2244.57"), Decimal("1010.01") / Decimal("2244.57")
    assert Decimal(s["concentration"]["explain"]["value"]) == (w1 * w1 + w2 * w2).quantize(Decimal("0.000001"))
    assert s["concentration"]["band"] == "concentrated"
    x = s["xirr"]
    assert x["headline_allowed"] is True and "1 excluded" not in x["scope"]
    oracle = pyxirr.xirr([date(2025, 1, 10), date(2025, 3, 3), date(2026, 10, 15)], [-1000.0, -900.0, 2244.57])
    assert abs(Decimal(x["explain"]["value"]) - Decimal(repr(oracle))) < Decimal("0.000001")
    m = s["upcoming_maturities"]["items"]
    assert [(i["instrument_id"], i["maturity_date"], i["days_until"]) for i in m] == [(FD, "2026-11-06", 22)]
    banks = s["dicgc"]["banks"]
    assert banks == [{"institution": "TEST Bank", "principal_at_cost": "600000.00", "insured": "500000",
                      "uninsured": "100000.00", "display_uninsured": "₹1,00,000.00",
                      "flags": ["EXCEEDS_DICGC_LIMIT"]}]  # fmt: skip


def test_short_span_xirr_is_not_annualised(conn: sqlite3.Connection) -> None:
    pid = make_pf(conn)
    tx(conn, pid, "mf:990001", "2026-06-01", "buy", "100", "1200.00")
    x = pf.portfolio_summary(conn, pid, NOW)["xirr"]
    assert x["headline_allowed"] is False and x["explain"]["value"] is None
    assert "Not annualised" in x["explain"]["display"]
    assert "ANNUALISED_FROM_SHORT_PERIOD" in x["annualised_detail"]["warning"]


def test_actual_and_hypothetical_are_separate(conn: sqlite3.Connection) -> None:
    real = standard_book(conn)
    hypo = make_pf(conn, "What if", "hypothetical")
    tx(conn, hypo, "mf:990002", "2025-03-03", "buy", "10", "100.00")
    s = pf.portfolio_summary(conn, hypo, NOW)
    assert s["label"].startswith("HYPOTHETICAL") and s["totals"]["market_value"]["value"] == "200.00"
    assert pf.portfolio_summary(conn, real, NOW)["totals"]["market_value"]["value"] == "2244.57"
    assert [p["nature"] for p in pf.list_portfolios(conn, "hypothetical")] == ["hypothetical"]


def test_nav_of_unusable_quality_is_not_replaced_by_an_older_one(conn: sqlite3.Connection) -> None:
    pid = make_pf(conn)
    tx(conn, pid, "mf:990001", "2025-01-10", "buy", "100", "1000.00")
    nav(conn, 990001, "2026-10-15", "99.0000", quality="suspect")
    h = pf.portfolio_summary(conn, pid, NOW)["holdings"][0]
    assert h["market_value"] is None and h["exclusion"]["code"] == "LATEST_NAV_QUALITY_SUSPECT"


# ----------------------------------------------------------------------------- import


CSV_OK = (
    b"instrument_name,isin,amfi_code,units,cost_basis_inr,purchase_date\r\n"
    b'TEST Liquid Fund A,,990001,100,"1,000.00",10-01-2025\r\n'
    b'"=HYPERLINK(""http://x"",""y"")",,990002,50.5,900,2025-03-03\r\n'
    b"Unknown,,123456,1,1,2025-01-01\r\n"
    b"No cost,,990001,1,,2025-01-01\r\n"
    b"Formula units,,990001,=1+1,10,2025-01-01\r\n"
)


def test_import_preview_then_apply_round_trip(conn: sqlite3.Connection) -> None:
    pid = make_pf(conn)
    p = pf.preview_holdings_import(conn, pid, CSV_OK, "holdings.csv", None, NOW)
    assert p["applied"] is False and conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    stored = [(r["instrument_id"], r["units"], r["amount"], r["txn_date"]) for r in p["will_store"]]
    assert stored == [("mf:990001", "100", "1000.00", "2025-01-10"), ("mf:990002", "50.5", "900", "2025-03-03")]
    assert "FORMULA_LIKE_TEXT" in p["will_store"][1]["flags"]  # name is shown, never stored or evaluated
    reasons = sorted(r["reason"] for r in p["rejected"])
    assert reasons == ["BAD_NUMBER", "MISSING_COST_BASIS", "UNKNOWN_AMFI_CODE"]
    with pytest.raises(pf.PortfolioError) as exc:
        pf.apply_holdings_import(conn, p["batch_id"], "0" * 64, NOW)
    assert exc.value.code == "PREVIEW_MISMATCH" and conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    out = pf.apply_holdings_import(conn, p["batch_id"], p["file_sha256"], NOW)
    assert out["applied"] is True and out["transactions_created"] == 2
    rows = conn.execute("SELECT units, amount, source, import_batch FROM transactions ORDER BY txn_date").fetchall()
    assert [tuple(r) for r in rows] == [("100", "1000.00", "csv_import", p["batch_id"]),
                                        ("50.5", "900", "csv_import", p["batch_id"])]  # fmt: skip
    with pytest.raises(pf.PortfolioError) as exc:
        pf.apply_holdings_import(conn, p["batch_id"], p["file_sha256"], NOW)
    assert exc.value.code == "ALREADY_APPLIED"
    again = pf.preview_holdings_import(conn, pid, CSV_OK, "holdings.csv", None, NOW)
    assert again["already_applied"] is True
    with pytest.raises(pf.PortfolioError):
        pf.apply_holdings_import(conn, again["batch_id"], again["file_sha256"], NOW)
    # the ledger keeps reasons and counts, never values
    ledger = conn.execute("SELECT value_json FROM settings WHERE key=?", ("import.batch:" + p["batch_id"],)).fetchone()
    assert '"pending":null' in ledger[0] and "Unknown" not in ledger[0]


def test_import_apply_failure_writes_nothing(conn: sqlite3.Connection) -> None:
    pid = make_pf(conn)
    p = pf.preview_holdings_import(conn, pid, CSV_OK, "holdings.csv", None, NOW)

    def boom() -> None:
        raise RuntimeError("pre-change backup failed")

    with pytest.raises(RuntimeError):
        pf.apply_holdings_import(conn, p["batch_id"], p["file_sha256"], NOW, pre_change=boom)
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("data", "name", "code"),
    [
        (b"x" * (5 * 1024 * 1024 + 1), "big.csv", "TOO_LARGE"),
        ("instrument_name,units\r\nTEST,1\r\n".encode("utf-16"), "u16.csv", "ENCODING_NOT_UTF8"),
        (b"PK\x03\x04junk", "zip.csv", "TYPE_MISMATCH"),
        (b"a,b\r\n", "macro.xlsm", "UNSUPPORTED_TYPE"),
    ],
)
def test_malicious_files_are_refused_before_anything_is_stored(
    conn: sqlite3.Connection, data: bytes, name: str, code: str
) -> None:
    pid = make_pf(conn)
    with pytest.raises(ImportRejected) as exc:
        pf.preview_holdings_import(conn, pid, data, name, None, NOW)
    assert exc.value.code == code
    assert conn.execute("SELECT COUNT(*) FROM settings WHERE key LIKE 'import.batch:%'").fetchone()[0] == 0


# ----------------------------------------------------------------------------- watchlist & alerts


ADDED = datetime(2026, 2, 1, 9, 0, tzinfo=UTC)


def test_watchlist_change_since_added(conn: sqlite3.Connection) -> None:
    pf.watch_add(conn, pf.WatchIn(instrument_id="mf:990004", note="  compare later \u202e"), ADDED)
    with pytest.raises(pf.PortfolioError):
        pf.watch_add(conn, pf.WatchIn(instrument_id="mf:990004"), ADDED)
    [w] = pf.watchlist(conn, NOW)
    assert w["note"] == "compare later"
    # base: last NAV on/before 2026-02-01 = 100.0000 (2026-01-05); latest 85.0000 (2026-10-14)
    assert w["change"]["from"] == {"date": "2026-01-05", "value": "100.0000"}
    assert w["change"]["to"] == {"date": "2026-10-14", "value": "85.0000"}
    assert w["change"]["value"] == "-15.0000" and w["absolute_return"]["display"] == "-15.00%"
    assert w["badge"] == "END_OF_DAY"
    pf.watch_delete(conn, "mf:990004", NOW)
    assert pf.watchlist(conn, NOW) == []


def _alert_world(conn: sqlite3.Connection) -> None:
    standard_book(conn)
    pf.watch_add(conn, pf.WatchIn(instrument_id="mf:990004"), ADDED)
    conn.execute(
        "INSERT INTO sources(source_id, owner, official, url, licence_note, mode, freshness_slo_days)"
        " VALUES ('amfi.navall', 'AMFI', 1, 'https://www.amfiindia.com/spages/NAVAll.txt', 'x', 'live', 1)"
    )
    conn.execute(
        "INSERT INTO ingestion_runs(run_id, source_id, started_at, status) VALUES"
        " ('run-1', 'amfi.navall', '2026-10-14T00:30:00+00:00', 'failed')"
    )


def test_alert_rules_fire_once_with_rule_wording(conn: sqlite3.Connection) -> None:
    _alert_world(conn)
    out = al.evaluate(conn, NOW, tax_coverage_to=date(2026, 11, 1), tax_rules_loaded=True)
    kinds = sorted(a["kind"] for a in out["created"])
    assert kinds == ["concentration", "decline_since_added", "ingestion_failed", "maturity", "stale_data",
                     "tax_rules"]  # fmt: skip
    for a in out["created"]:
        assert a["message"].startswith("Your rule “"), a["message"]
        assert compliance.blocked(a["message"]) == [], a["message"]
        assert a["created_at"] == NOW.isoformat() and a["dedupe_key"]
        assert a["source_id"]
    stale = next(a for a in out["created"] if a["kind"] == "stale_data")
    assert stale["subject_id"] == "mf:990003" and "2026-09-01" in stale["message"]
    # Re-evaluation: same conditions → no duplicates
    again = al.evaluate(conn, NOW, tax_coverage_to=date(2026, 11, 1), tax_rules_loaded=True)
    assert again["created"] == [] and again["already_present"] == 6
    assert conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 6
    # Ack is idempotent and acknowledged alerts do not come back
    aid = stale["alert_id"]
    first = al.acknowledge(conn, aid, NOW)["acknowledged_at"]
    assert al.acknowledge(conn, aid, datetime(2026, 10, 16, tzinfo=UTC))["acknowledged_at"] == first
    al.evaluate(conn, NOW, tax_coverage_to=date(2026, 11, 1), tax_rules_loaded=True)
    assert len(al.list_alerts(conn, include_acknowledged=False)) == 5
    with pytest.raises(pf.PortfolioError):
        al.acknowledge(conn, "al_missing", NOW)


def test_alert_rules_can_be_changed_and_disabled(conn: sqlite3.Connection) -> None:
    _alert_world(conn)
    al.save_rules(conn, al.AlertRules(stale_data=False, maturity_within_days=None, concentration_hhi_above="0.9",
                                      decline_since_added_beyond="0.2", tax_coverage_within_days=None,
                                      ingestion_failed_lookback_days=None))  # fmt: skip
    assert al.evaluate(conn, NOW, tax_coverage_to=None, tax_rules_loaded=False)["created"] == []
    with pytest.raises(ValueError):
        al.AlertRules.model_validate({"concentration_hhi_above": 0.3})


def test_unloadable_tax_rules_alert(conn: sqlite3.Connection) -> None:
    out = al.evaluate(conn, NOW, tax_coverage_to=None, tax_rules_loaded=False)
    [a] = out["created"]
    assert a["kind"] == "tax_rules" and a["severity"] == "critical" and compliance.blocked(a["message"]) == []


# ----------------------------------------------------------------------------- evidence


def test_evidence_shows_provenance_and_supersession_chain(conn: sqlite3.Connection) -> None:
    nav(conn, 990001, "2026-10-13", "12.0000")
    nav(conn, 990001, "2026-10-13", "12.0100")  # source correction → old row superseded, kept
    old, new = (r[0] for r in conn.execute(
        "SELECT obs_id FROM observations WHERE series_id='nav:990001' AND observation_date='2026-10-13'"
        " ORDER BY obs_id"
    ))  # fmt: skip
    e_old = pf.evidence(conn, old)
    assert e_old["is_current"] is False and [x["obs_id"] for x in e_old["superseded_chain"]["newer"]] == [new]
    e_new = pf.evidence(conn, new)
    o = e_new["observation"]
    assert o["url"] == URL and o["sha256"] == "a" * 64 and o["quality"] == "ok" and o["convention"] == "synthetic NAV"
    assert o["observation_date"] == "2026-10-13" and o["retrieved_at"] == NOW.isoformat()
    assert [x["obs_id"] for x in e_new["superseded_chain"]["older"]] == [old]
    with pytest.raises(pf.PortfolioError):
        pf.evidence(conn, 10**9)


# ----------------------------------------------------------------------------- privacy & backup


SENTINELS = ("SENTINEL-PORTFOLIO-XYZ", "SENTINEL-NOTE-XYZ", "98765432.10", "SENTINEL-FILE")


def test_inventory_counts_without_amounts(conn: sqlite3.Connection, tmp_path: Path) -> None:
    standard_book(conn)
    inv = pf.inventory(conn, tmp_path)
    assert inv["user_data"]["tables"]["transactions"] == 4 and inv["user_data"]["tables"]["portfolios"] == 1
    assert "600000" not in str(inv) and "1000.00" not in str(inv)


def test_export_contains_every_user_table_and_csv_is_formula_safe(conn: sqlite3.Connection) -> None:
    pid = make_pf(conn, '=HYPERLINK("http://x","y")')
    tx(conn, pid, "mf:990001", "2025-01-10", "buy", "100", "1000.00")
    pf.watch_add(conn, pf.WatchIn(instrument_id="mf:990004", note="+cmd"), ADDED)
    ex = pf.export_all(conn, NOW)
    for k in ("profile", "portfolios", "transactions", "watchlist", "alerts", "runs", "audit_events", "settings"):
        assert k in ex and k in ex["manifest"]
    assert ex["transactions"][0]["amount"] == "1000.00"
    csv = pf.export_transactions_csv(conn).decode("utf-8-sig")
    assert '"\'=HYPERLINK(""http://x"",""y"")"' in csv
    assert '"1000.00"' in csv and '"100"' in csv


def test_erase_removes_user_data_from_the_database_files(conn: sqlite3.Connection, tmp_path: Path) -> None:
    db = tmp_path / "x.db"
    pid = make_pf(conn, SENTINELS[0])
    tx(conn, pid, "mf:990001", "2025-01-10", "buy", "100", SENTINELS[2])
    pf.watch_add(conn, pf.WatchIn(instrument_id="mf:990004", note=SENTINELS[1]), ADDED)
    pf.preview_holdings_import(conn, pid, CSV_OK, SENTINELS[3] + ".csv", None, NOW)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    raw = db.read_bytes()
    assert all(s.encode() in raw for s in SENTINELS)  # the probe can see them before erase
    obs_before = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    out = pf.erase(conn, tmp_path, delete_backups=False)
    assert out["status"] == "erased" and out["deleted_rows"]["transactions"] == 1
    for t in pf.USER_TABLES:
        assert conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0, t
    blobs = db.read_bytes() + (db.with_name("x.db-wal").read_bytes() if db.with_name("x.db-wal").exists() else b"")
    for s in SENTINELS:
        assert s.encode() not in blobs, s
    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == obs_before  # public data kept
    assert current_version(conn) >= 1  # schema kept


def test_backup_writes_verified_copy(conn: sqlite3.Connection, tmp_path: Path) -> None:
    standard_book(conn)
    a = pf.make_backup(conn, tmp_path, NOW)
    b = pf.make_backup(conn, tmp_path, NOW)  # same second → distinct file
    assert a["integrity"] == "ok" and a["path"] != b["path"] and Path(a["path"]).parent == tmp_path / "backups"
    copy = sqlite3.connect(a["path"])
    assert copy.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 4
    copy.close()
    out = pf.erase(conn, tmp_path, delete_backups=True)
    assert out["backups_deleted"] == 2 and out["backups_remaining"] == 0


# ----------------------------------------------------------------------------- SEC-62 log redaction


def test_logs_never_contain_amounts_holdings_or_names(
    conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    conn.execute("UPDATE instruments SET name='SENTINEL-SCHEME-NAME' WHERE instrument_id='mf:990001'")
    caplog.set_level(logging.DEBUG)
    pid = make_pf(conn, "SENTINEL-PORTFOLIO-XYZ")
    csv = (
        b"instrument_name,amfi_code,units,cost_basis_inr,purchase_date\r\n"
        b'SENTINEL-FUND-XYZ,990001,7654.321,"9,87,65,432.10",2025-01-10\r\n'
        b"SENTINEL-REJECT,990001,=1+1,5,2025-01-10\r\n"
    )
    p = pf.preview_holdings_import(conn, pid, csv, "SENTINEL-FILE.csv", None, NOW)
    pf.apply_holdings_import(conn, p["batch_id"], p["file_sha256"], NOW)
    pf.portfolio_summary(conn, pid, NOW)
    pf.watch_add(conn, pf.WatchIn(instrument_id="mf:990004", note="SENTINEL-NOTE-XYZ"), ADDED)
    al.evaluate(conn, NOW, tax_coverage_to=date(2026, 11, 1), tax_rules_loaded=True)
    pf.erase(conn, Path(str(conn.execute("PRAGMA database_list").fetchone()[2])).parent, delete_backups=False)
    assert caplog.records, "expected some (redacted) log records"
    text = caplog.text
    for s in ("SENTINEL", "98765432", "9,87,65,432", "7654.321", "TEST Liquid", "12.3456", "1234.56"):
        assert s not in text, s
