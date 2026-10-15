"""CAS (CAMS/KFintech PDF) import service.

Fixtures are SYNTHETIC (tests/services/cas_synthetic.py): a CAMS-style PDF generated at test time for a fictional
investor, encrypted with the PDF Standard handler (RC4-128), parsed by the real casparser 1.4.1 + pypdfium2. Mapping
unit tests use the PII-free ``CasTxn`` model directly. No real statement is used anywhere."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from iip.data.imports import ImportRejected
from iip.services import cas
from iip.services import portfolio as pf
from iip.store.db import connect, migrate
from tests.services import cas_synthetic as syn
from tests.services.test_portfolio import CSV_OK, NOW, make_pf, seed_market, tx

GROWTH = "mf:990001"  # carries syn.ISIN_GROWTH
IDCW = "mf:990002"  # carries syn.ISIN_IDCW
PII = (syn.PII_NAME, syn.PII_NAME.upper(), syn.PII_PAN, syn.PII_EMAIL, syn.PII_MOBILE, syn.PII_ADDRESS, syn.PII_FOLIO)


def seed_isins(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE instruments SET isin=? WHERE instrument_id=?", (syn.ISIN_GROWTH, GROWTH))
    conn.execute("UPDATE instruments SET isin=? WHERE instrument_id=?", (syn.ISIN_IDCW, IDCW))


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(tmp_path / "x.db")
    migrate(c, NOW.isoformat())
    seed_market(c)
    seed_isins(c)
    yield c
    c.close()


def preview(conn: sqlite3.Connection, pid: str, st: syn.Statement | None = None) -> dict[str, object]:
    return cas.preview_cas_import(conn, pid, syn.build_pdf(st), syn.PASSWORD, NOW)


def apply(conn: sqlite3.Connection, p: dict[str, object], accept: bool = False) -> dict[str, object]:
    body = cas.CasApplyIn(sha256=str(p["file_sha256"]), accept_reconciliation_mismatches=accept)
    return cas.apply_cas_import(conn, str(p["batch_id"]), body, NOW)


def T(kind: str, units: str | None = None, amount: str | None = "100.00", d: str = "2025-01-10") -> cas.CasTxn:
    return cas.CasTxn(
        date.fromisoformat(d), kind, None if amount is None else Decimal(amount),
        None if units is None else Decimal(units), Decimal("10.0000"),
    )  # fmt: skip


# ----------------------------------------------------------------------------- mapping of every transaction type

TODAY = NOW.date()


@pytest.mark.parametrize(
    ("kind", "units", "amount", "expected"),
    [
        ("PURCHASE", "10.000", "100.00", ("store", "buy", "10.000", "100.00")),
        ("PURCHASE_SIP", "4.5", "50.00", ("store", "buy", "4.5", "50.00")),
        ("SWITCH_IN", "2", "20.00", ("store", "buy", "2", "20.00")),
        ("SWITCH_IN_MERGER", "2", "20.00", ("store", "buy", "2", "20.00")),
        ("DIVIDEND_REINVEST", "1.25", "12.50", ("store", "buy", "1.25", "12.50")),
        ("REDEMPTION", "-3.000", "-33.00", ("store", "sell", "3.000", "33.00")),
        ("REDEMPTION", "-3.000", "33.00", ("store", "sell", "3.000", "33.00")),
        ("SWITCH_OUT", "-1", "10.00", ("store", "sell", "1", "10.00")),
        ("SWITCH_OUT_MERGER", "-1", "10.00", ("store", "sell", "1", "10.00")),
        ("DIVIDEND_PAYOUT", None, "25.00", ("store", "dividend", None, "25.00")),
        ("STAMP_DUTY_TAX", None, "0.05", ("ignore", "STAMP_DUTY_NOT_MODELLED")),
        ("STT_TAX", None, "0.01", ("ignore", "STT_NOT_MODELLED")),
        ("TDS_TAX", None, "1.00", ("ignore", "TDS_NOT_MODELLED")),
        ("MISC", None, None, ("ignore", "INFORMATIONAL_ROW")),
        ("MISC", "1", "10.00", ("reject", "UNCLASSIFIED_UNIT_MOVEMENT")),
        ("SEGREGATION", "5", None, ("reject", "SEGREGATED_PORTFOLIO")),
        ("GIFT_IN", "5", None, ("reject", "GIFT_NOT_MODELLED")),
        ("GIFT_OUT", "-5", None, ("reject", "GIFT_NOT_MODELLED")),
        ("REVERSAL", "-10", "-100.00", ("reject", "REVERSAL_NOT_MODELLED")),
        ("UNKNOWN", "0", None, ("reject", "UNKNOWN_TRANSACTION_TYPE")),
        ("PURCHASE", "-1", "10.00", ("reject", "UNITS_SIGN_UNEXPECTED")),
        ("REDEMPTION", "1", "10.00", ("reject", "UNITS_SIGN_UNEXPECTED")),
        ("PURCHASE", None, "10.00", ("reject", "MISSING_UNITS")),
        ("PURCHASE", "1", None, ("reject", "MISSING_AMOUNT")),
        ("PURCHASE", "1", "-10.00", ("reject", "AMOUNT_SIGN_UNEXPECTED")),
        ("PURCHASE", "1.1234567", "10.00", ("reject", "UNITS_PRECISION")),
        ("PURCHASE", "1", "10.001", ("reject", "AMOUNT_PRECISION")),
        ("DIVIDEND_PAYOUT", None, None, ("reject", "MISSING_AMOUNT")),
    ],
)
def test_every_transaction_type_maps(
    kind: str, units: str | None, amount: str | None, expected: tuple[str, ...]
) -> None:
    m = cas.map_txn(T(kind, units, amount), TODAY)
    if expected[0] == "store":
        assert (m.action, m.txn_type, cas._s(m.units), cas._s(m.amount)) == expected
    else:
        assert (m.action, m.reason) == expected


def test_future_and_undated_rows_rejected() -> None:
    assert cas.map_txn(T("PURCHASE", "1", d="2026-10-16"), TODAY).reason == "FUTURE_DATE"
    undated = cas.CasTxn(None, "PURCHASE", Decimal(1), Decimal(1), None)
    assert cas.map_txn(undated, TODAY).reason == "BAD_DATE"


# ----------------------------------------------------------------------------- synthetic PDF end-to-end


def test_preview_maps_synthetic_statement_and_stores_nothing(conn: sqlite3.Connection) -> None:
    pid = make_pf(conn)
    p = preview(conn, pid)
    assert p["applied"] is False and p["issuer"] == "CAMS" and p["kind"] == "cas_pdf"
    stored = [(r["instrument_id"], r["txn_type"], r["units"], r["amount"], r["nav"]) for r in p["will_store"]]  # type: ignore[index]
    assert stored == [
        (GROWTH, "buy", "100.000", "1000.00", "10.0000"),
        (GROWTH, "buy", "45.000", "500.00", "11.1111"),
        (GROWTH, "buy", "25.000", "300.00", "12.0000"),
        (GROWTH, "sell", "30.000", "330.00", "11.0000"),
        (GROWTH, "sell", "10.000", "120.00", "12.0000"),
        (IDCW, "buy", "50.000", "1000.00", "20.0000"),
        (IDCW, "dividend", None, "25.00", None),
    ]
    assert [r["cas_type"] for r in p["will_store"]] == [  # type: ignore[attr-defined]
        "PURCHASE", "PURCHASE_SIP", "SWITCH_IN", "REDEMPTION", "SWITCH_OUT", "PURCHASE", "DIVIDEND_PAYOUT",
    ]  # fmt: skip
    assert {r["reason"] for r in p["ignored"]} == {"STAMP_DUTY_NOT_MODELLED", "STT_NOT_MODELLED"}  # type: ignore[attr-defined]
    assert p["rejected"] == []
    assert p["reconciliation_ok"] is True and p["blocking"] == []
    assert all(s["match"] == "EXACT_ISIN" for s in p["schemes"])  # type: ignore[attr-defined]
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0  # preview stores nothing


def test_apply_round_trip_with_dividend_and_summary(conn: sqlite3.Connection) -> None:
    pid = make_pf(conn)
    p = preview(conn, pid)
    out = apply(conn, p)
    assert out["applied"] is True and out["transactions_created"] == 7
    rows = conn.execute("SELECT txn_type, units, amount, price, source, import_batch FROM transactions").fetchall()
    assert {r["source"] for r in rows} == {cas.TXN_SOURCE} and {r["import_batch"] for r in rows} == {p["batch_id"]}
    div = [r for r in rows if r["txn_type"] == "dividend"]
    assert len(div) == 1 and div[0]["units"] is None and div[0]["amount"] == "25.00"
    pos = pf.fifo_positions(pf.load_txns(conn, pid))
    assert pos[GROWTH].units == Decimal("130.000") and pos[IDCW].units == Decimal("50.000")
    s = pf.portfolio_summary(conn, pid, NOW)  # dividends do not break valuation or FIFO
    assert {h["instrument_id"] for h in s["holdings"]} == {GROWTH, IDCW}
    ledger = json.loads(conn.execute("SELECT value_json FROM settings WHERE key=?",
                                     (pf.IMPORT_KEY + str(p["batch_id"]),)).fetchone()[0])  # fmt: skip
    assert ledger["status"] == "applied" and ledger["kind"] == "cas_pdf" and ledger["pending"] is None


# ----------------------------------------------------------------------------- exact ISIN matching


def test_unknown_isin_is_unmatched_and_rejected_never_fuzzy(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    import casparser_isin

    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("casparser-isin lookup must never run (fuzzy matching)")

    monkeypatch.setattr(casparser_isin.MFISINDb, "isin_lookup", boom)
    monkeypatch.setattr(casparser_isin.MFISINDb, "direct_isin_lookup", boom)
    # Same scheme NAME as a known instrument, but an ISIN that is not in the local store.
    st = syn.Statement(schemes=(syn.SchemeBlock("Z9X", "TEST Liquid Fund A", syn.ISIN_UNKNOWN, "0.000", "10.000",
                                                (syn.Row("10-Jan-2024", "Purchase", "100.00", "10.000", "10.0000",
                                                         "10.000"),)),))  # fmt: skip
    pid = make_pf(conn)
    p = preview(conn, pid, st)
    assert p["will_store"] == []
    assert [r["reason"] for r in p["rejected"]] == ["UNKNOWN_ISIN"]  # type: ignore[attr-defined]
    assert p["schemes"][0]["match"] == "UNKNOWN_ISIN" and p["schemes"][0]["instrument_id"] is None  # type: ignore[index]
    assert p["reconciliation"][0]["status"] == "UNMATCHED"  # type: ignore[index]
    with pytest.raises(pf.PortfolioError) as e:
        apply(conn, p, accept=True)
    assert e.value.code == "NOTHING_TO_APPLY"


def test_ambiguous_isin_rejected(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE instruments SET isin=? WHERE instrument_id='mf:990003'", (syn.ISIN_GROWTH,))
    p = preview(conn, make_pf(conn))
    assert {r["reason"] for r in p["rejected"]} == {"AMBIGUOUS_ISIN"}  # type: ignore[attr-defined]


def test_exact_isin_match_is_case_and_checksum_strict(conn: sqlite3.Connection) -> None:
    s = cas.CasScheme(1, syn.ISIN_GROWTH.lower(), None, "CAMS", Decimal(0), Decimal(0), False, ())
    assert cas._match(conn, s)[2] == "UNKNOWN_ISIN"  # no case-folding, no LIKE
    bad = syn.ISIN_GROWTH[:-1] + str((int(syn.ISIN_GROWTH[-1]) + 1) % 10)
    st = syn.Statement(schemes=(syn.SchemeBlock("Z1G", "x", bad, "0", "1", (syn.Row("10-Jan-2024", "Purchase",
                                                "10.00", "1.000", "10.0000", "1.000"),)),))  # fmt: skip
    p = preview(conn, make_pf(conn), st)
    assert p["schemes"][0]["isin_problem"] == "ISIN_BAD_CHECKSUM"  # type: ignore[index]
    assert [r["reason"] for r in p["rejected"]] == ["ISIN_BAD_CHECKSUM"]  # type: ignore[attr-defined]


# ----------------------------------------------------------------------------- reconciliation


def mismatch_statement() -> syn.Statement:
    """Closing balance says 120 units; the rows only add up to 100 (e.g. a row dropped from the statement)."""
    return syn.Statement(schemes=(syn.SchemeBlock("Z1G", "x", syn.ISIN_GROWTH, "0.000", "120.000", (
        syn.Row("10-Jan-2024", "Purchase", "1,000.00", "100.000", "10.0000", "100.000"),
    )),))  # fmt: skip


def test_reconciliation_mismatch_reported_and_must_be_acknowledged(conn: sqlite3.Connection) -> None:
    pid = make_pf(conn)
    p = preview(conn, pid, mismatch_statement())
    rec = p["reconciliation"][0]  # type: ignore[index]
    assert p["reconciliation_ok"] is False
    assert (rec["status"], rec["cas_closing_units"], rec["imported_net_units"], rec["difference"]) == (
        "MISMATCH", "120", "100.000", "20.000")  # fmt: skip
    assert rec["causes"] == ["TRANSACTIONS_DO_NOT_SUM_TO_CLOSING_BALANCE"]
    assert p["confirm_with"] == {"sha256": p["file_sha256"], "accept_reconciliation_mismatches": True}
    with pytest.raises(pf.PortfolioError) as e:
        apply(conn, p)
    assert e.value.code == "RECONCILIATION_NOT_ACKNOWLEDGED"
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    assert apply(conn, p, accept=True)["reconciliation_mismatches_accepted"] == 1


def test_opening_balance_is_a_mismatch_cause(conn: sqlite3.Connection) -> None:
    st = syn.Statement(schemes=(syn.SchemeBlock("Z1G", "x", syn.ISIN_GROWTH, "50.000", "60.000", (
        syn.Row("10-Jan-2024", "Purchase", "100.00", "10.000", "10.0000", "60.000"),
    )),))  # fmt: skip
    rec = preview(conn, make_pf(conn), st)["reconciliation"][0]  # type: ignore[index]
    assert rec["status"] == "MISMATCH" and rec["causes"] == ["OPENING_BALANCE_NOT_IMPORTED"]


# ----------------------------------------------------------------------------- oversell, sha256, wrong endpoint


def test_oversell_from_bad_cas_data_refused(conn: sqlite3.Connection) -> None:
    """The statement redeems 80 units of which only 50 were bought (opening balance not imported)."""
    st = syn.Statement(schemes=(syn.SchemeBlock("Z1G", "x", syn.ISIN_GROWTH, "30.000", "0.000", (
        syn.Row("10-Jan-2024", "Purchase", "500.00", "50.000", "10.0000", "80.000"),
        syn.Row("10-Feb-2024", "Redemption", "880.00", "(80.000)", "11.0000", "0.000"),
    )),))  # fmt: skip
    pid = make_pf(conn)
    p = preview(conn, pid, st)
    assert [b["code"] for b in p["blocking"]] == ["OVERSELL"]  # type: ignore[attr-defined]
    with pytest.raises(pf.Oversell):
        apply(conn, p, accept=True)
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0  # rolled back
    status = json.loads(conn.execute("SELECT value_json FROM settings WHERE key=?",
                                     (pf.IMPORT_KEY + str(p["batch_id"]),)).fetchone()[0])["status"]  # fmt: skip
    assert status == "previewed"


def test_apply_requires_the_files_sha256_and_applies_once(conn: sqlite3.Connection) -> None:
    pid = make_pf(conn)
    p = preview(conn, pid)
    with pytest.raises(pf.PortfolioError) as e:
        cas.apply_cas_import(conn, str(p["batch_id"]), cas.CasApplyIn(sha256="0" * 64), NOW)
    assert e.value.code == "PREVIEW_MISMATCH"
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    apply(conn, p)
    with pytest.raises(pf.PortfolioError) as e:
        apply(conn, p)
    assert e.value.code == "ALREADY_APPLIED"
    assert preview(conn, pid)["already_applied"] is True


def test_apply_runs_pre_change_backup_first_and_failure_writes_nothing(conn: sqlite3.Connection) -> None:
    p = preview(conn, make_pf(conn))

    def failing_backup() -> object:
        raise pf.PortfolioError("BACKUP_FAILED", "x", 500)

    body = cas.CasApplyIn(sha256=str(p["file_sha256"]))
    with pytest.raises(pf.PortfolioError):
        cas.apply_cas_import(conn, str(p["batch_id"]), body, NOW, pre_change=failing_backup)
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_cas_and_csv_batches_cannot_cross_apply(conn: sqlite3.Connection) -> None:
    pid = make_pf(conn)
    p = preview(conn, pid)
    with pytest.raises(pf.PortfolioError) as e:
        pf.apply_holdings_import(conn, str(p["batch_id"]), str(p["file_sha256"]), NOW)
    assert e.value.code == "WRONG_APPLY_ENDPOINT"
    csv = pf.preview_holdings_import(conn, pid, CSV_OK, "h.csv", None, NOW)
    with pytest.raises(pf.PortfolioError) as e:
        cas.apply_cas_import(conn, csv["batch_id"], cas.CasApplyIn(sha256=csv["file_sha256"]), NOW)
    assert e.value.code == "WRONG_APPLY_ENDPOINT"


def test_existing_holdings_warned_as_possible_double_count(conn: sqlite3.Connection) -> None:
    pid = make_pf(conn)
    tx(conn, pid, GROWTH, "2025-01-10", "buy", "1", "10.00")
    assert any("double-count" in w for w in preview(conn, pid)["warnings"])  # type: ignore[attr-defined]


def test_segregated_portfolio_flagged(conn: sqlite3.Connection) -> None:
    st = syn.Statement(schemes=(syn.SchemeBlock("Z1G", "Zeta Credit Risk Fund Segregated Portfolio 1", syn.ISIN_GROWTH,
                                                "0.000", "10.000", (syn.Row("10-Jan-2024", "Purchase", "100.00",
                                                "10.000", "10.0000", "10.000"),)),))  # fmt: skip
    p = preview(conn, make_pf(conn), st)
    assert p["schemes"][0]["segregated_portfolio"] is True  # type: ignore[index]
    assert p["will_store"][0]["flags"] == ["SEGREGATED_PORTFOLIO"]  # type: ignore[index]


# ----------------------------------------------------------------------------- file-level rejections


@pytest.mark.parametrize(
    ("data", "password", "code", "status"),
    [
        (b"%PDF-" + b"x" * cas.MAX_CAS_BYTES, "", "TOO_LARGE", 413),
        (b"PK\x03\x04 not a pdf", "", "NOT_A_PDF", 415),
        (b"\x00%PDF-1.4", "", "NOT_A_PDF", 415),
        (b"%PDF-1.4\ngarbage", "", "PDF_DAMAGED", 422),
        (b"%PDF-1.4", "x" * 129, "BAD_PASSWORD_FIELD", 422),
    ],
)
def test_file_level_rejections(conn: sqlite3.Connection, data: bytes, password: str, code: str, status: int) -> None:
    with pytest.raises(ImportRejected) as e:
        cas.preview_cas_import(conn, make_pf(conn), data, password, NOW)
    assert (e.value.code, e.value.status) == (code, status)


def test_size_and_magic_checked_before_parser(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    def spy(*_a: object) -> None:
        raise AssertionError("parser must not run")

    monkeypatch.setattr(cas, "read_statement", spy)
    for data in (b"%PDF-" + b"x" * cas.MAX_CAS_BYTES, b"GIF89a"):
        with pytest.raises(ImportRejected):
            cas.preview_cas_import(conn, make_pf(conn), data, "", NOW)


def test_wrong_password_and_unknown_encryption_rejected_cleanly(conn: sqlite3.Connection) -> None:
    pid = make_pf(conn)
    good = syn.build_pdf()
    with pytest.raises(ImportRejected) as e:
        cas.preview_cas_import(conn, pid, good, "WRONG-PASSWORD", NOW)
    assert e.value.code == "WRONG_PASSWORD" and "WRONG-PASSWORD" not in e.value.message
    assert e.value.__cause__ is None and e.value.__suppress_context__  # no parser exception chained
    unknown = good.replace(b"/Filter /Standard", b"/Filter /AcmeLock")
    with pytest.raises(ImportRejected) as e:
        cas.preview_cas_import(conn, pid, unknown, syn.PASSWORD, NOW)
    assert e.value.code == "UNSUPPORTED_ENCRYPTION"
    with pytest.raises(ImportRejected) as e:
        cas.preview_cas_import(conn, pid, syn.build_pdf(syn.Statement(schemes=(), marker="OTHERWS")), syn.PASSWORD,
                               NOW)  # fmt: skip
    assert e.value.code == "NOT_A_CAS"
    assert conn.execute("SELECT COUNT(*) FROM settings WHERE key LIKE 'import.batch:%'").fetchone()[0] == 0


def test_unencrypted_statement_with_empty_password(conn: sqlite3.Connection) -> None:
    p = cas.preview_cas_import(conn, make_pf(conn), syn.build_pdf(password=None), "", NOW)
    assert len(p["will_store"]) == 7


# ----------------------------------------------------------------------------- privacy


def _db_text(conn: sqlite3.Connection) -> str:
    return "\n".join(conn.iterdump())


def test_pii_never_reaches_db_logs_or_response(
    conn: sqlite3.Connection, tmp_path: Path, caplog: pytest.LogCaptureFixture, capfd: pytest.CaptureFixture[str]
) -> None:
    caplog.set_level(logging.DEBUG)
    pid = make_pf(conn)
    p = preview(conn, pid)
    response = json.dumps(p)
    out = apply(conn, p)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    haystacks = {
        "preview response": response,
        "apply response": json.dumps(out),
        "database dump": _db_text(conn),
        "logs": caplog.text,
        "stdout/stderr": "".join(capfd.readouterr()),
        "database file bytes": b"".join(f.read_bytes() for f in tmp_path.glob("x.db*")).decode("latin-1"),
    }
    for where, text in haystacks.items():
        for marker in (*PII, syn.PASSWORD):
            assert marker not in text, f"{marker!r} leaked into {where}"
    assert caplog.records  # the import did log (ids and counts only)


def test_pii_test_is_not_vacuous_the_parser_does_see_the_planted_pii() -> None:
    """Negative control: casparser really extracts the planted PII from the synthetic PDF, so the test above
    proves it is discarded rather than never read."""
    import io

    from casparser import read_cas_pdf

    raw = read_cas_pdf(io.BytesIO(syn.build_pdf()), syn.PASSWORD)
    assert raw.investor_info.name == syn.PII_NAME and raw.investor_info.email == syn.PII_EMAIL
    assert raw.investor_info.mobile == syn.PII_MOBILE and syn.PII_ADDRESS in raw.investor_info.address
    assert raw.folios[0].folio == syn.PII_FOLIO and raw.folios[0].PAN == syn.PII_PAN
