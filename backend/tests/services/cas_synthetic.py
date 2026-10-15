"""A SYNTHETIC CAMS-style "Consolidated Account Statement" PDF, generated at test time.

No real statement is used anywhere: the investor is the fictional "Jane Doe" (PAN ``ABCDE1234F``), the AMC, schemes,
folios and ISINs are invented (the ISINs use the non-existent issuer prefix ``INFZZ`` with a valid check digit so
they pass format validation). The layout mimics the CAMS DETAILED template closely enough for casparser 1.4.1 to
parse it (column header, folio line, scheme header with inline ISIN, Opening/Closing Unit Balance, NAV footer), but
it is NOT a copy of a real CAMS or KFintech statement and proves nothing about real-statement compatibility.

The PDF is hand-written (Courier, PDF 1.4) and optionally encrypted with the PDF Standard security handler,
revision 3 (RC4, 128-bit), implemented here with ``hashlib`` only — no PDF-writing dependency is added.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field

from iip.data.validators import isin_checksum_ok

# PII planted in every synthetic statement; the privacy tests assert none of it escapes.
PII_NAME = "Jane Doe"
PII_PAN = "ABCDE1234F"
PII_EMAIL = "jane.doe.cas-sentinel@example.com"
PII_MOBILE = "+919812345678"
PII_ADDRESS = "42 Sentinel Lane Testville"
PII_FOLIO = "9876543210"
PASSWORD = "ABCDE1234F01011990"  # PAN + DOB-style, fictional

_PAD = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")
_FONT_SIZE = 8.0
_CHAR_W = 0.6 * _FONT_SIZE  # Courier advance width


def fictional_isin(body11: str) -> str:
    """Append the check digit that makes ``body11`` a valid (fictional) ISIN."""
    for d in "0123456789":
        if isin_checksum_ok(body11 + d):
            return body11 + d
    raise AssertionError("no check digit")  # pragma: no cover


ISIN_GROWTH = fictional_isin("INFZZ0001A0")
ISIN_IDCW = fictional_isin("INFZZ0002B0")
ISIN_UNKNOWN = fictional_isin("INFZZ0003C0")


@dataclass(frozen=True)
class Row:
    date: str  # DD-Mon-YYYY
    desc: str
    amount: str = ""
    units: str = ""
    price: str = ""
    balance: str = ""


@dataclass(frozen=True)
class SchemeBlock:
    code: str
    name: str
    isin: str
    opening: str
    closing: str
    rows: Sequence[Row]
    nav_date: str = "31-Mar-2025"
    nav: str = "12.0000"


@dataclass(frozen=True)
class Statement:
    schemes: Sequence[SchemeBlock]
    amc: str = "Zeta Example Mutual Fund"
    folio: str = PII_FOLIO
    period: str = "01-Jan-2024 To 31-Mar-2025"
    marker: str = "CAMSCASWS"
    heading: str = "Consolidated Account Statement"
    extra_lines: Sequence[str] = field(default_factory=tuple)


def default_statement() -> Statement:
    return Statement(
        schemes=(
            SchemeBlock(
                "Z1G",
                "Zeta Example Flexi Cap Fund - Direct Plan - Growth",
                ISIN_GROWTH,
                "0.000",
                "130.000",
                (
                    Row("10-Jan-2024", "Purchase", "1,000.00", "100.000", "10.0000", "100.000"),
                    Row("10-Jan-2024", "*** Stamp Duty ***", "0.05"),
                    Row(
                        "10-Feb-2024",
                        "Systematic Investment Purchase Instalment 1/12",
                        "500.00",
                        "45.000",
                        "11.1111",
                        "145.000",
                    ),
                    Row("12-Mar-2024", "Switch In - From Zeta Liquid Fund", "300.00", "25.000", "12.0000", "170.000"),
                    Row("15-Apr-2024", "Redemption", "330.00", "(30.000)", "11.0000", "140.000"),
                    Row("15-Apr-2024", "*** STT Paid ***", "0.01"),
                    Row("20-May-2024", "Switch Out - To Zeta Liquid Fund", "120.00", "(10.000)", "12.0000", "130.000"),
                ),
            ),
            SchemeBlock(
                "Z2D",
                "Zeta Example Balanced Fund - Direct Plan - IDCW",
                ISIN_IDCW,
                "0.000",
                "50.000",
                (
                    Row("05-Jan-2024", "Purchase", "1,000.00", "50.000", "20.0000", "50.000"),
                    Row("28-Jun-2024", "IDCW Paid @ Rs.0.50 per unit", "25.00"),
                ),
                nav="21.0000",
            ),
        )
    )


# ----------------------------------------------------------------------------- layout


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _left(x: float, y: float, text: str) -> str:
    return f"BT /F1 {_FONT_SIZE:g} Tf {x:.2f} {y:.2f} Td ({_esc(text)}) Tj ET\n"


def _right(x_end: float, y: float, text: str) -> str:
    return _left(x_end - len(text) * _CHAR_W, y, text) if text else ""


COL_DATE, COL_DESC, END_AMOUNT, END_UNITS, END_PRICE, END_BALANCE = 30.0, 90.0, 380.0, 450.0, 515.0, 585.0


def _pages(st: Statement) -> list[str]:
    page1: list[str] = []
    y = 770.0
    for text in (f"Email Id: {PII_EMAIL}", PII_NAME, PII_ADDRESS, f"Mobile: {PII_MOBILE}"):
        page1.append(_left(30, y, text))
        y -= 10
    page1.append(_left(330, 770, st.heading))
    page1.append(_left(330, 760, st.period))
    page1.append(_left(330, 750, st.marker))
    y = 715.0
    page1.append(_left(COL_DATE, y, "Date"))
    page1.append(_left(COL_DESC, y, "Transaction"))
    page1.append(_right(END_AMOUNT, y, "Amount"))
    page1.append(_right(END_UNITS, y, "Units"))
    page1.append(_right(END_PRICE, y, "Price"))
    page1.append(_right(END_BALANCE, y, "Unit"))
    page1.append(_right(END_AMOUNT, y - 8, "(INR)"))
    page1.append(_right(END_PRICE, y - 8, "(INR)"))
    page1.append(_right(END_BALANCE, y - 8, "Balance"))
    y = 690.0

    def line(text: str) -> None:
        nonlocal y
        page1.append(_left(30, y, text))
        y -= 12

    line(st.amc)
    for s in st.schemes:
        line(f"Folio No: {st.folio}  PAN: {PII_PAN}  KYC: OK  PAN: OK")
        line(PII_NAME.upper())
        line(f"{s.code}-{s.name} - ISIN: {s.isin} Registrar : CAMS")
        line(f"Opening Unit Balance: {s.opening}")
        for r in s.rows:
            page1.append(_left(COL_DATE, y, r.date))
            page1.append(_left(COL_DESC, y, r.desc))
            page1.append(_right(END_AMOUNT, y, r.amount))
            page1.append(_right(END_UNITS, y, r.units))
            page1.append(_right(END_PRICE, y, r.price))
            page1.append(_right(END_BALANCE, y, r.balance))
            y -= 12
        line(f"Closing Unit Balance: {s.closing}")
        line(f"NAV on {s.nav_date}: INR {s.nav}")
    for text in st.extra_lines:
        line(text)
    return ["".join(page1)]


# ----------------------------------------------------------------------------- PDF writing + RC4 encryption


def _rc4(key: bytes, data: bytes) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) % 256
        s[i], s[j] = s[j], s[i]
    out = bytearray()
    i = j = 0
    for b in data:
        i = (i + 1) % 256
        j = (j + s[i]) % 256
        s[i], s[j] = s[j], s[i]
        out.append(b ^ s[(s[i] + s[j]) % 256])
    return bytes(out)


def _padded(pw: str) -> bytes:
    return (pw.encode("latin-1") + _PAD)[:32]


def _r3_values(user_pw: str, owner_pw: str, perms: int, doc_id: bytes) -> tuple[bytes, bytes, bytes]:
    n = 16
    h = hashlib.md5(_padded(owner_pw)).digest()
    for _ in range(50):
        h = hashlib.md5(h).digest()
    okey = h[:n]
    o = _rc4(okey, _padded(user_pw))
    for i in range(1, 20):
        o = _rc4(bytes(b ^ i for b in okey), o)
    h = hashlib.md5(_padded(user_pw) + o + perms.to_bytes(4, "little", signed=True) + doc_id).digest()
    for _ in range(50):
        h = hashlib.md5(h[:n]).digest()
    key = h[:n]
    u = _rc4(key, hashlib.md5(_PAD + doc_id).digest())
    for i in range(1, 20):
        u = _rc4(bytes(b ^ i for b in key), u)
    return o, u + b"\x00" * 16, key


def build_pdf(st: Statement | None = None, password: str | None = PASSWORD) -> bytes:
    """Return the PDF bytes (encrypted with ``password`` unless it is None)."""
    st = st or default_statement()
    contents = [c.encode("latin-1") for c in _pages(st)]
    doc_id = hashlib.md5(b"iip synthetic cas").digest()
    perms = -3904
    key = b""
    enc_obj = b""
    if password is not None:
        o, u, key = _r3_values(password, "owner-" + password, perms, doc_id)
        enc_obj = b"<< /Filter /Standard /V 2 /R 3 /Length 128 /P %d /O <%s> /U <%s> >>" % (
            perms,
            o.hex().encode(),
            u.hex().encode(),
        )

    objs: list[bytes] = []
    n_pages = len(contents)
    font_num = 3
    first_page = 4
    kids = " ".join(f"{first_page + 2 * i} 0 R" for i in range(n_pages))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>")
    for i, content in enumerate(contents):
        page_num = first_page + 2 * i
        stream_num = page_num + 1
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font_num} 0 R >> >>"
            f" /Contents {stream_num} 0 R >>".encode()
        )
        data = content
        if key:
            obj_key = hashlib.md5(key + stream_num.to_bytes(3, "little") + b"\x00\x00").digest()[:16]
            data = _rc4(obj_key, content)
        objs.append(b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream")
    if enc_obj:
        objs.append(enc_obj)

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for num, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % num + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    trailer = b"<< /Size %d /Root 1 0 R /ID [<%s> <%s>]" % (len(objs) + 1, doc_id.hex().encode(), doc_id.hex().encode())
    if enc_obj:
        trailer += b" /Encrypt %d 0 R" % len(objs)
    out += b"trailer\n" + trailer + b" >>\nstartxref\n%d\n%%%%EOF\n" % xref
    return bytes(out)
