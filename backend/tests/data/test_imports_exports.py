"""Holdings import hardening (threat-model C-07, SEC-30..41) and CSV export escaping (SEC-40).

Instrument names and ISINs below come from the AMFI probe fixtures; units and amounts are illustrative inputs, not
market data."""

from __future__ import annotations

import io
import zipfile
from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from openpyxl import Workbook

from iip.data import imports
from iip.data.export import TRIGGERS, export_holdings_csv, neutralise_cell
from iip.data.imports import (
    MAX_IMPORT_BYTES,
    ImportRejected,
    confirm_preview,
    parse_amount,
    preview_import,
    sanitise_label,
)

HEADER = "instrument_name,isin,amfi_code,units,cost_basis_inr,purchase_date"
GOOD_ROW = "HDFC Banking and PSU Debt Fund - Direct Plan - Growth Option,INFZ12KA1IZ1,128629,100.500,2500.00,2026-01-15"


def csv_bytes(*rows: str, header: str = HEADER) -> bytes:
    return ("\r\n".join([header, *rows]) + "\r\n").encode("utf-8")


# --- happy path ------------------------------------------------------------------------------------------


def test_csv_preview_parses_decimal_rows() -> None:
    preview = preview_import(csv_bytes(GOOD_ROW), "holdings.csv")
    assert preview.kind == "csv"
    assert len(preview.rows) == 1
    row = preview.rows[0]
    assert row.instrument_name.startswith("HDFC Banking")
    assert row.isin == "INFZ12KA1IZ1"
    assert row.amfi_code == 128629
    assert row.units == Decimal("100.500") and type(row.units) is Decimal
    assert row.cost_basis_inr == Decimal("2500.00")
    assert row.purchase_date == date(2026, 1, 15)
    assert preview.rejected == ()
    assert len(preview.file_sha256) == 64


def test_preview_must_be_confirmed_by_hash() -> None:
    preview = preview_import(csv_bytes(GOOD_ROW), "holdings.csv")
    assert confirm_preview(preview, preview.file_sha256) is preview
    with pytest.raises(ImportRejected):
        confirm_preview(preview, "0" * 64)


def test_bom_is_accepted() -> None:
    preview = preview_import(b"\xef\xbb\xbf" + csv_bytes(GOOD_ROW), "h.csv")
    assert len(preview.rows) == 1


# --- SEC-30 / SEC-31: size and shape caps ------------------------------------------------------------------


def test_size_cap_rejected_before_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []
    monkeypatch.setattr(imports, "_parse_csv_text", lambda *a, **k: called.append(True))
    data = csv_bytes(GOOD_ROW)
    data = data + b" " * (MAX_IMPORT_BYTES + 1 - len(data))
    assert len(data) == MAX_IMPORT_BYTES + 1
    with pytest.raises(ImportRejected) as exc:
        preview_import(data, "holdings.csv")
    assert exc.value.status == 413
    assert called == []


def test_too_many_rows() -> None:
    data = csv_bytes(*([GOOD_ROW] * 20_001))
    with pytest.raises(ImportRejected) as exc:
        preview_import(data, "h.csv")
    assert exc.value.status == 422 and exc.value.code == "TOO_MANY_ROWS"


def test_twenty_thousand_rows_is_allowed() -> None:
    assert len(preview_import(csv_bytes(*([GOOD_ROW] * 20_000)), "h.csv").rows) == 20_000


def test_cell_too_long() -> None:
    with pytest.raises(ImportRejected) as exc:
        preview_import(csv_bytes(GOOD_ROW.replace("HDFC", "H" * 513, 1)), "h.csv")
    assert exc.value.code == "CELL_TOO_LONG" and "row 2" in exc.value.message


def test_too_many_columns() -> None:
    wide = HEADER + "".join(f",extra{i}" for i in range(59))  # 65 columns
    with pytest.raises(ImportRejected) as exc:
        preview_import(csv_bytes(GOOD_ROW + "," * 59, header=wide), "h.csv")
    assert exc.value.code == "TOO_MANY_COLUMNS"


def test_missing_required_column() -> None:
    with pytest.raises(ImportRejected) as exc:
        preview_import(csv_bytes("x,1", header="instrument_name,isin"), "h.csv")
    assert exc.value.code == "MISSING_COLUMN"


# --- types / extensions -----------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["h.xlsm", "h.xls", "h.xlsb", "h.ods", "h.txt", "h.exe", "noext"])
def test_disallowed_extensions(name: str) -> None:
    with pytest.raises(ImportRejected) as exc:
        preview_import(csv_bytes(GOOD_ROW), name)
    assert exc.value.status == 415


def test_zip_named_csv_rejected() -> None:
    with pytest.raises(ImportRejected):
        preview_import(_xlsx_bytes([["instrument_name", "units"]]), "h.csv")


def test_nul_byte_rejected() -> None:
    with pytest.raises(ImportRejected):
        preview_import(csv_bytes(GOOD_ROW).replace(b"Direct", b"Dir\x00ct"), "h.csv", encoding="utf-8")


# --- SEC-36: encodings ------------------------------------------------------------------------------------


def test_utf16_without_choice_asks_for_encoding() -> None:
    data = ("\ufeff" + HEADER + "\r\n" + GOOD_ROW + "\r\n").encode("utf-16-le")
    data = b"\xff\xfe" + data[2:]
    with pytest.raises(ImportRejected) as exc:
        preview_import(data, "h.csv")
    assert exc.value.code == "ENCODING_NOT_UTF8"
    assert "encoding" in exc.value.message.lower()


def test_utf16_with_explicit_choice() -> None:
    data = (HEADER + "\r\n" + GOOD_ROW + "\r\n").encode("utf-16")
    assert len(preview_import(data, "h.csv", encoding="utf-16").rows) == 1


def test_cp1252_rejected_unless_chosen() -> None:
    data = csv_bytes(GOOD_ROW.replace("HDFC", "HDFC \u2019")).replace("\u2019".encode(), b"\x92")
    with pytest.raises(ImportRejected):
        preview_import(data, "h.csv")
    preview = preview_import(data, "h.csv", encoding="cp1252")
    assert "\u2019" in preview.rows[0].instrument_name


def test_unknown_encoding_refused() -> None:
    with pytest.raises(ImportRejected):
        preview_import(csv_bytes(GOOD_ROW), "h.csv", encoding="latin-1")


# --- SEC-37: normalisation ----------------------------------------------------------------------------------


def test_control_and_bidi_characters_stripped() -> None:
    name = "Axis\u202e Children's\u0007 Fund\u2066"
    row = GOOD_ROW.replace("HDFC Banking and PSU Debt Fund - Direct Plan - Growth Option", name)
    preview = preview_import(csv_bytes(row), "h.csv")
    assert preview.rows[0].instrument_name == "Axis Children's Fund"


def test_nfc_normalisation() -> None:
    decomposed = "Cafe\u0301 Fund"
    row = GOOD_ROW.replace("HDFC Banking and PSU Debt Fund - Direct Plan - Growth Option", decomposed)
    assert preview_import(csv_bytes(row), "h.csv").rows[0].instrument_name == "Caf\u00e9 Fund"


# --- SEC-38: numbers ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1,00,000.50", Decimal("100000.50")),
        ("100,000.50", Decimal("100000.50")),
        ("12,34,56,789", Decimal("123456789")),
        ("1,000", Decimal("1000")),
        ("2500", Decimal("2500")),
        ("0.001", Decimal("0.001")),
        ("-1250.50", Decimal("-1250.50")),
    ],
)
def test_parse_amount_accepts(text: str, expected: Decimal) -> None:
    assert parse_amount(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "1.000,50",
        "1e5",
        "1E5",
        "1,0,0",
        "1,00,0000",
        "10,00",
        "NaN",
        "Infinity",
        "",
        " ",
        "1 000",
        "₹100",
        "+5",
        "1.2.3",
        "0x10",
        "١٢٣",
    ],
)
def test_parse_amount_rejects(text: str) -> None:
    with pytest.raises(ValueError):
        parse_amount(text)


def test_negative_units_row_rejected() -> None:
    preview = preview_import(csv_bytes(GOOD_ROW, GOOD_ROW.replace(",100.500,", ",-5,")), "h.csv")
    assert len(preview.rows) == 1
    assert preview.rejected[0].reason == "UNITS_NOT_POSITIVE"
    assert preview.rejected[0].line_no == 3


@pytest.mark.parametrize(
    ("date_text", "ok"),
    [
        ("2026-01-15", True),
        ("15-01-2026", True),
        ("15-Jan-2026", True),
        ("01/15/2026", False),
        ("15/01/2026", False),
        ("2026-02-30", False),
    ],
)
def test_dates(date_text: str, ok: bool) -> None:
    preview = preview_import(csv_bytes(GOOD_ROW.replace("2026-01-15", date_text)), "h.csv")
    if ok:
        assert preview.rows[0].purchase_date == date(2026, 1, 15)
    else:
        assert preview.rejected[0].reason == "BAD_DATE"


def test_bad_isin_row_rejected() -> None:
    preview = preview_import(csv_bytes(GOOD_ROW.replace("INFZ12KA1IZ1", "INF179KA1IZ8")), "h.csv")
    assert preview.rejected[0].reason == "ISIN_BAD_CHECKSUM"


def test_unidentified_row_is_flagged_not_rejected() -> None:
    preview = preview_import(csv_bytes(GOOD_ROW.replace("INFZ12KA1IZ1,128629", ",")), "h.csv")
    assert len(preview.rows) == 1
    assert "UNIDENTIFIED" in preview.rows[0].flags


# --- formulas in CSV are text, never evaluated ------------------------------------------------------------


def test_csv_formula_text_is_kept_literal() -> None:
    row = GOOD_ROW.replace(
        "HDFC Banking and PSU Debt Fund - Direct Plan - Growth Option", '"=HYPERLINK(""http://x"",""y"")"'
    )
    preview = preview_import(csv_bytes(row), "h.csv")
    assert preview.rows[0].instrument_name == '=HYPERLINK("http://x","y")'
    assert "FORMULA_LIKE_TEXT" in preview.rows[0].flags


def test_formula_in_numeric_column_rejected() -> None:
    preview = preview_import(csv_bytes(GOOD_ROW.replace(",100.500,", ",=1+1,")), "h.csv")
    assert preview.rejected[0].reason == "BAD_NUMBER"


# --- SEC-39: labels ------------------------------------------------------------------------------------------


def test_filename_label_sanitised_and_truncated() -> None:
    assert sanitise_label("../../etc/passwd") == "passwd"
    assert len(sanitise_label("a" * 10_000 + ".csv")) <= 120
    assert sanitise_label("C:\\Users\\x\\h\u202e.csv") == "h.csv"


# --- XLSX ---------------------------------------------------------------------------------------------------


def _xlsx_bytes(rows: list[list[object]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _add_member(xlsx: bytes, name: str, data: bytes, compress: int = zipfile.ZIP_DEFLATED) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(xlsx)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            dst.writestr(item, src.read(item.filename))
        dst.writestr(zipfile.ZipInfo(name), data, compress_type=compress)
    return out.getvalue()


XLSX_ROWS: list[list[object]] = [
    HEADER.split(","),
    [
        "HDFC Banking and PSU Debt Fund - Direct Plan - Growth Option",
        "INFZ12KA1IZ1",
        "128629",
        "100.500",
        "2500.00",
        "2026-01-15",
    ],
]


def test_xlsx_happy_path() -> None:
    preview = preview_import(_xlsx_bytes(XLSX_ROWS), "holdings.xlsx")
    assert preview.kind == "xlsx"
    assert preview.rows[0].units == Decimal("100.500")


def test_xlsx_numeric_cells_parsed_without_float_noise() -> None:
    rows = [HEADER.split(","), ["Fund", "", 128629, 0.1, 2500, "2026-01-15"]]
    preview = preview_import(_xlsx_bytes(rows), "h.xlsx")
    assert preview.rows[0].units == Decimal("0.1")
    assert preview.rows[0].amfi_code == 128629


def test_xlsx_formula_without_cached_value_is_empty_with_warning() -> None:
    """SEC-35: '=1+1' must never become 2."""
    rows = [HEADER.split(","), ["Fund", "INFZ12KA1IZ1", "128629", "100", "=1+1", "2026-01-15"]]
    preview = preview_import(_xlsx_bytes(rows), "h.xlsx")
    assert preview.rows[0].cost_basis_inr is None
    assert any("FORMULA" in w for w in preview.warnings)


def test_xlsm_renamed_to_xlsx_rejected() -> None:
    data = _add_member(_xlsx_bytes(XLSX_ROWS), "xl/vbaProject.bin", b"\xd0\xcf\x11\xe0fake")
    with pytest.raises(ImportRejected) as exc:
        preview_import(data, "h.xlsx")
    assert exc.value.code == "XLSX_MACRO"


def test_external_links_rejected() -> None:
    data = _add_member(_xlsx_bytes(XLSX_ROWS), "xl/externalLinks/externalLink1.xml", b"<externalLink/>")
    with pytest.raises(ImportRejected):
        preview_import(data, "h.xlsx")


def test_ole_embedding_rejected() -> None:
    data = _add_member(_xlsx_bytes(XLSX_ROWS), "xl/embeddings/oleObject1.bin", b"x")
    with pytest.raises(ImportRejected):
        preview_import(data, "h.xlsx")


def test_zip_bomb_rejected_before_openpyxl(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []
    monkeypatch.setattr(imports, "_load_workbook", lambda *a, **k: called.append(True))
    data = _add_member(_xlsx_bytes(XLSX_ROWS), "xl/media/big.bin", b"\0" * (51 * 1024 * 1024))
    assert len(data) < MAX_IMPORT_BYTES
    with pytest.raises(ImportRejected) as exc:
        preview_import(data, "h.xlsx")
    assert exc.value.code in {"XLSX_RATIO", "XLSX_TOO_LARGE"}
    assert called == []


def test_high_ratio_member_rejected() -> None:
    data = _add_member(_xlsx_bytes(XLSX_ROWS), "xl/media/pad.bin", b"\0" * (2 * 1024 * 1024))
    with pytest.raises(ImportRejected) as exc:
        preview_import(data, "h.xlsx")
    assert exc.value.code == "XLSX_RATIO"


def test_path_traversal_member_rejected() -> None:
    data = _add_member(_xlsx_bytes(XLSX_ROWS), "../evil.xml", b"<x/>")
    with pytest.raises(ImportRejected):
        preview_import(data, "h.xlsx")


def test_too_many_members_rejected() -> None:
    data = _xlsx_bytes(XLSX_ROWS)
    for i in range(100):
        data = _add_member(data, f"xl/media/m{i}.txt", b"abc", compress=zipfile.ZIP_STORED)
    with pytest.raises(ImportRejected) as exc:
        preview_import(data, "h.xlsx")
    assert exc.value.code == "XLSX_TOO_MANY_MEMBERS"


def test_xxe_doctype_rejected() -> None:
    evil = b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]><sst>&lol;</sst>'
    data = _add_member(_xlsx_bytes(XLSX_ROWS), "xl/evil.xml", evil)
    with pytest.raises(ImportRejected) as exc:
        preview_import(data, "h.xlsx")
    assert exc.value.code == "XLSX_DTD"


def test_not_a_zip_named_xlsx_rejected() -> None:
    with pytest.raises(ImportRejected):
        preview_import(csv_bytes(GOOD_ROW), "h.xlsx")


# --- SEC-40: export escaping ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ['=HYPERLINK("http://x","y")', "+cmd", "-2+3", "@SUM(A1)", "\t=1", "\r=1", "＝1", "＋1", "－1", "＠x"],
)
def test_text_cells_with_triggers_are_prefixed(name: str) -> None:
    assert neutralise_cell(name) == "'" + name


def test_export_csv_escapes_text_but_not_numbers() -> None:
    out = export_holdings_csv(
        [{"instrument_name": "=1+1", "units": Decimal("-1250.50"), "purchase_date": date(2026, 1, 15)}],
        columns=("instrument_name", "units", "purchase_date"),
    )
    assert out.startswith(b"\xef\xbb\xbf")
    text = out.decode("utf-8-sig")
    assert text.splitlines()[0] == '"instrument_name","units","purchase_date"'
    assert text.splitlines()[1] == '"\'=1+1","-1250.50","2026-01-15"'


def test_export_refuses_float() -> None:
    with pytest.raises(TypeError):
        export_holdings_csv([{"units": 1.5}], columns=("units",))


@given(st.text(max_size=40))
def test_property_no_exported_text_cell_starts_with_trigger(text: str) -> None:
    out = neutralise_cell(text)
    assert out == "" or out[0] not in TRIGGERS


# --- SEC-41: round trip ------------------------------------------------------------------------------------


def test_import_export_reimport_round_trip() -> None:
    first = preview_import(
        csv_bytes(GOOD_ROW.replace("HDFC Banking and PSU Debt Fund - Direct Plan - Growth Option", "-2+3 Fund")),
        "h.csv",
    )
    exported = export_holdings_csv(
        [r.as_export_dict() for r in first.rows],
        columns=("instrument_name", "isin", "amfi_code", "units", "cost_basis_inr", "purchase_date"),
    )
    again = preview_import(exported, "export.csv")
    assert again.rows == first.rows
