"""CAMS / KFintech CAS (Consolidated Account Statement, PDF) import: preview → confirm → apply.

Same contract as the CSV/XLSX holdings import (``iip.services.portfolio``): the preview stores nothing in
``transactions``; apply requires the file's SHA-256, takes a backup first, writes in ONE transaction and is reported
as applied only after COMMIT. FIFO lots and the OVERSELL refusal are the portfolio service's.

Privacy (threat-model C-07, C-13, SEC-62):

* The PDF is parsed **from memory** (``casparser`` → ``pypdfium2`` reading a ``BytesIO``); its bytes are never
  written to disk by this module, and the route reads the multipart body in memory (no spooled temp file).
* The password is used only for that in-memory parse. It is never stored, logged, echoed or put in an error
  message. (Python strings cannot be zeroised; it lives only in the request's local variables.)
* Only what the ledger needs is extracted: per scheme the ISIN printed on the statement, the opening/closing unit
  balance, and per transaction its date, type, units, amount and NAV. The investor block (name, PAN, email,
  address, mobile), folio numbers, holder names, nominees, advisor codes, scheme names and free-text transaction
  descriptions are dropped inside :func:`read_statement` and never leave it.
* **Folio numbers are not stored at all**, not even hashed or truncated: nothing in the ledger needs them
  (re-import is detected by the file SHA-256 and instruments are matched by ISIN), and a stored folio — even its
  last 4 characters or a salted hash — would add re-identification risk for no functional gain.
* The uploaded filename is not stored either (CAS filenames can carry identifiers); the ledger label is fixed.
* ``casparser`` free-text ``parse_warnings`` can quote statement text, so only their COUNT is kept.

CAS gaps handled here (PLAN.md row B06):

* **Regular-plan, IDCW and reinvestment ISINs are accepted.** A held scheme outside the minimised NAV scope is looked
  up by its exact ISIN in AMFI's current file (``resolve_isins``) and registered; held schemes are in scope (U-01).
* **Exit loads charged are recorded as observed facts.** For a redemption or switch-out row the implied deduction is
  ``units x price - amount`` (minus a same-day STT row, if any). It is shown and stored with the batch as NOT VERIFIED:
  that the printed price is the NAV before load is an assumption no real statement has confirmed here.
* **A new CAS confirms or contradicts "I did this" entries** (``decisions_log.cas_confirmed``, set once): a matching
  transaction near the decision date confirms it; its absence contradicts it only when the statement covers the whole
  window; otherwise nothing is written.

Identification is by **exact ISIN** against the local ``instruments`` table (populated by AMFI ingestion). The
``isin_search`` hook casparser calls during parsing (casparser-isin: fuzzy scheme-name matching, scores ≥ 60) is
replaced for the duration of the parse by a function that returns only the ISIN printed on the statement, so no
fuzzy match can ever reach this module. An ISIN that is unknown locally makes every row of that scheme "unmatched"
and rejected with a reason; names are never matched.
"""

from __future__ import annotations

import io
import json
import logging
import sqlite3
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from iip.data.imports import ImportRejected
from iip.data.validators import validate_isin
from iip.engine.actions.contracts import Step, Verb
from iip.engine.determinism import canonical_json, sha256_hex
from iip.engine.money import ZERO, engine_context
from iip.services import portfolio as pf
from iip.services.ingestion import IsinLookupFailed
from iip.store.db import write_tx
from iip.store.ledger import confirm_decisions_from_cas

log = logging.getLogger("iip.cas")

SERVICE_VERSION = "cas_import@1.0.0"
MiB = 1024 * 1024
MAX_CAS_BYTES = 10 * MiB
MAX_PASSWORD_CHARS = 128
PDF_MAGIC = b"%PDF-"
BATCH_KIND = "cas_pdf"
LABEL = "CAS statement (PDF)"
# The transactions.source CHECK constraint (migration 0001) allows only 'manual' and 'csv_import'. CAS rows use the
# file-import channel value; the import ledger (settings "import.batch:<id>", kind "cas_pdf") records that the batch
# came from a CAS. See docs/operations/known-limitations.md.
TXN_SOURCE = "csv_import"

# casparser TransactionType values → ledger types.
BUY_TYPES = frozenset({"PURCHASE", "PURCHASE_SIP", "SWITCH_IN", "SWITCH_IN_MERGER", "DIVIDEND_REINVEST"})
SELL_TYPES = frozenset({"REDEMPTION", "SWITCH_OUT", "SWITCH_OUT_MERGER"})
DIVIDEND_TYPES = frozenset({"DIVIDEND_PAYOUT"})
IGNORED_TYPES = {
    "STAMP_DUTY_TAX": "STAMP_DUTY_NOT_MODELLED",
    "STT_TAX": "STT_NOT_MODELLED",
    "TDS_TAX": "TDS_NOT_MODELLED",
}
REJECTED_TYPES = {
    "SEGREGATION": "SEGREGATED_PORTFOLIO",
    "GIFT_IN": "GIFT_NOT_MODELLED",
    "GIFT_OUT": "GIFT_NOT_MODELLED",
    "REVERSAL": "REVERSAL_NOT_MODELLED",
    "UNKNOWN": "UNKNOWN_TRANSACTION_TYPE",
}
COST_NOTE = (
    "Stamp duty, STT and TDS rows are not stored: the ledger has no cost/fee transaction that FIFO uses, so they "
    "are listed as ignored and are not added to the cost basis."
)

_PARSE_LOCK = threading.Lock()  # pdfium is not thread-safe, and the casparser hook below is process-global


class CasApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accept_reconciliation_mismatches: bool = False


# ----------------------------------------------------------------------------- PII-free in-memory model


@dataclass(frozen=True)
class CasTxn:
    txn_date: date | None
    cas_type: str
    amount: Decimal | None
    units: Decimal | None
    nav: Decimal | None


@dataclass(frozen=True)
class CasScheme:
    block: int  # 1-based position in the statement
    isin: str | None
    isin_problem: str | None  # NO_ISIN / ISIN_BAD_FORMAT / ISIN_BAD_CHECKSUM
    rta: str
    opening_units: Decimal
    closing_units: Decimal
    segregated: bool
    txns: tuple[CasTxn, ...]


@dataclass(frozen=True)
class CasStatement:
    issuer: str  # CAMS | KFINTECH
    period_from: str
    period_to: str
    schemes: tuple[CasScheme, ...]
    parser_warnings: int


# ----------------------------------------------------------------------------- parsing (memory only)


def _exact_isin_only(
    scheme_name: str, rta: str, rta_code: str, isin: str | None = None
) -> tuple[str | None, None, None]:
    """Replacement for casparser's ``isin_search``: the ISIN printed on the statement, or nothing. Never fuzzy."""
    del scheme_name, rta, rta_code
    return (isin, None, None) if isin else (None, None, None)


@contextmanager
def _no_fuzzy_isin() -> Iterator[None]:
    from casparser.parsers import (  # type: ignore[import-untyped]  # noqa: PLC0415 - only when parsing
        cams_detailed,
        cams_summary,
    )

    saved = (cams_detailed.isin_search, cams_summary.isin_search)
    cams_detailed.isin_search = _exact_isin_only
    cams_summary.isin_search = _exact_isin_only
    try:
        yield
    finally:
        cams_detailed.isin_search, cams_summary.isin_search = saved


def _reject(code: str, message: str, status: int = 422) -> ImportRejected:
    log.warning("cas import rejected code=%s", code)  # security event: import rejection with reason (C-13)
    return ImportRejected(code, message, status)


def _pdfium_code(exc: BaseException) -> int | None:
    seen: BaseException | None = exc
    while seen is not None:
        code = getattr(seen, "err_code", None)
        if isinstance(code, int):
            return code
        seen = seen.__cause__ or seen.__context__
    return None


def check_upload(data: bytes, password: object) -> str:
    """File-level checks that run BEFORE any parser sees the bytes. Returns the password as ``str``."""
    if len(data) > MAX_CAS_BYTES:
        raise _reject("TOO_LARGE", f"the PDF exceeds {MAX_CAS_BYTES} bytes", 413)
    if not data.startswith(PDF_MAGIC):
        raise _reject("NOT_A_PDF", "the file is not a PDF (it does not start with %PDF-)", 415)
    if not isinstance(password, str) or len(password) > MAX_PASSWORD_CHARS:
        raise _reject("BAD_PASSWORD_FIELD", f"the password must be text of at most {MAX_PASSWORD_CHARS} characters")
    return password


def _dec(v: object) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return v
    if isinstance(v, int) and not isinstance(v, bool):
        return Decimal(v)
    if isinstance(v, str):
        try:
            return Decimal(v.replace(",", ""))
        except InvalidOperation:
            return None
    return None  # floats are never converted (implementation rule 5)


def _type_code(v: object) -> str:
    value = getattr(v, "value", v)
    return str(value).upper()


def read_statement(data: bytes, password: str) -> CasStatement:
    """Parse a CAMS/KFintech DETAILED CAS from memory and keep only the PII-free fields listed in the module doc."""
    import pypdfium2.raw as pdfium_c  # type: ignore[import-untyped]  # noqa: PLC0415
    from casparser import read_cas_pdf  # type: ignore[import-untyped]  # noqa: PLC0415

    with _PARSE_LOCK, _no_fuzzy_isin():
        try:
            parsed: Any = read_cas_pdf(io.BytesIO(data), password, output="dict", sort_transactions=True)
        except Exception as exc:  # every parser failure is mapped to a fixed message: no parser text, no password
            code = _pdfium_code(exc)
            name = type(exc).__name__
            if code == pdfium_c.FPDF_ERR_PASSWORD or name == "IncorrectPasswordError":
                raise _reject("WRONG_PASSWORD", "the password did not open this PDF; nothing was stored") from None
            if code == pdfium_c.FPDF_ERR_SECURITY:
                raise _reject(
                    "UNSUPPORTED_ENCRYPTION",
                    "the PDF uses an encryption method that cannot be opened here; nothing was stored",
                ) from None
            if code == pdfium_c.FPDF_ERR_FORMAT:
                raise _reject("PDF_DAMAGED", "the PDF is damaged or not a valid PDF; nothing was stored") from None
            raise _reject(
                "NOT_A_CAS",
                "this PDF could not be read as a CAMS/KFintech detailed CAS; nothing was stored",
            ) from None
    try:
        return _extract(parsed)
    finally:
        del parsed  # drop the only reference to the PII-bearing parse result


def _extract(parsed: Any) -> CasStatement:
    if not hasattr(parsed, "folios"):  # NSDL/CDSL depository CAS: holdings only, no MF transaction ledger
        raise _reject(
            "DEPOSITORY_CAS_NOT_SUPPORTED",
            "NSDL/CDSL depository statements carry no transaction history; use a CAMS/KFintech detailed CAS",
        )
    if _type_code(parsed.cas_type) != "DETAILED":
        raise _reject(
            "SUMMARY_CAS_NOT_SUPPORTED",
            "a summary CAS has no transactions; request the DETAILED statement from CAMS or KFintech",
        )
    schemes: list[CasScheme] = []
    block = 0
    for folio in parsed.folios:
        for s in folio.schemes:
            block += 1
            isin = s.isin if isinstance(s.isin, str) and s.isin else None
            problem = "NO_ISIN" if isin is None else validate_isin(isin)
            txns = tuple(
                CasTxn(
                    t.date if isinstance(t.date, date) else None,
                    _type_code(t.type),
                    _dec(t.amount),
                    _dec(t.units),
                    _dec(t.nav),
                )
                for t in s.transactions
            )
            schemes.append(
                CasScheme(
                    block=block,
                    isin=isin if problem is None else None,
                    isin_problem=problem,
                    rta=str(s.rta or "").upper()[:16],
                    opening_units=_dec(s.open) or ZERO,
                    closing_units=_dec(s.close) or ZERO,
                    segregated="segregat" in str(s.scheme or "").lower(),
                    txns=txns,
                )
            )
    period = parsed.statement_period
    return CasStatement(
        issuer=_type_code(parsed.file_type),
        period_from=str(getattr(period, "from_", "") or "")[:20],
        period_to=str(getattr(period, "to", "") or "")[:20],
        schemes=tuple(schemes),
        parser_warnings=len(parsed.parse_warnings or []),
    )


# ----------------------------------------------------------------------------- mapping


def _match(conn: sqlite3.Connection, s: CasScheme) -> tuple[str | None, str | None, str]:
    """Exact ISIN → (instrument_id, name, reason). Unknown ISINs are unmatched; names are never matched."""
    if s.isin is None:
        return None, None, s.isin_problem or "NO_ISIN"
    found = conn.execute("SELECT instrument_id, name FROM instruments WHERE isin=?", (s.isin,)).fetchall()
    if not found:
        alias = conn.execute("SELECT value_json FROM settings WHERE key=?", ("isin.alias:" + s.isin,)).fetchone()
        if alias is not None:
            found = conn.execute(
                "SELECT instrument_id, name FROM instruments WHERE instrument_id=?", (json.loads(alias[0]),)
            ).fetchall()
    if len(found) > 1:
        return None, None, "AMBIGUOUS_ISIN"
    if not found:
        return None, None, "UNKNOWN_ISIN"
    return found[0]["instrument_id"], found[0]["name"], ""


@dataclass(frozen=True)
class Mapped:
    action: str  # store | ignore | reject
    reason: str = ""
    txn_type: str = ""
    units: Decimal | None = None  # positive
    amount: Decimal | None = None  # positive


def map_txn(t: CasTxn, today: date) -> Mapped:
    """One CAS transaction → a ledger action. Pure; does not look at instruments."""
    if t.cas_type in IGNORED_TYPES:
        return Mapped("ignore", IGNORED_TYPES[t.cas_type])
    if t.cas_type == "MISC" and t.units is None:
        return Mapped("ignore", "INFORMATIONAL_ROW")
    if t.cas_type in REJECTED_TYPES:
        return Mapped("reject", REJECTED_TYPES[t.cas_type])
    if t.txn_date is None:
        return Mapped("reject", "BAD_DATE")
    if t.txn_date > today:
        return Mapped("reject", "FUTURE_DATE")
    if t.cas_type in DIVIDEND_TYPES:
        if t.amount is None or t.amount == 0:
            return Mapped("reject", "MISSING_AMOUNT")
        amount = abs(t.amount)
        if pf._dp(amount) > pf.MAX_AMOUNT_DP:
            return Mapped("reject", "AMOUNT_PRECISION")
        return Mapped("store", txn_type="dividend", amount=amount)
    if t.cas_type in BUY_TYPES:
        kind, sign = "buy", 1
    elif t.cas_type in SELL_TYPES:
        kind, sign = "sell", -1
    else:
        return Mapped("reject", "UNCLASSIFIED_UNIT_MOVEMENT")
    if t.units is None or t.units == 0:
        return Mapped("reject", "MISSING_UNITS")
    if (t.units > 0) != (sign > 0):
        return Mapped("reject", "UNITS_SIGN_UNEXPECTED")
    if t.amount is None or t.amount == 0:
        return Mapped("reject", "MISSING_AMOUNT")
    if kind == "buy" and t.amount < 0:
        return Mapped("reject", "AMOUNT_SIGN_UNEXPECTED")
    units, amount = abs(t.units), abs(t.amount)
    if pf._dp(units) > pf.MAX_UNITS_DP:
        return Mapped("reject", "UNITS_PRECISION")
    if pf._dp(amount) > pf.MAX_AMOUNT_DP:
        return Mapped("reject", "AMOUNT_PRECISION")
    return Mapped("store", txn_type=kind, units=units, amount=amount)


def _s(d: Decimal | None) -> str | None:
    return None if d is None else format(d, "f")


# ----------------------------------------------------------------------------- preview → apply


def preview_cas_import(
    conn: sqlite3.Connection,
    portfolio_id: str,
    data: bytes,
    password: object,
    now: datetime,
    resolve_isins: Callable[[set[str]], dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Validate, parse (memory only), map and reconcile; store a *pending* batch. Nothing reaches
    ``transactions`` until :func:`apply_cas_import` commits."""
    pf._portfolio(conn, portfolio_id)
    pw = check_upload(data, password)
    statement = read_statement(data, pw)
    del pw
    sha = sha256_hex(data)
    today = now.date()

    lookup_failed: frozenset[str] = frozenset()
    if resolve_isins is not None:
        # Held schemes outside the minimised scope (Regular plans, IDCW options) are looked up by exact ISIN in AMFI's
        # current file and registered; anything not found stays unmatched with its reason.
        unknown = {s.isin for s in statement.schemes if s.isin and _match(conn, s)[0] is None}
        if unknown:
            try:
                resolve_isins(unknown)
            except IsinLookupFailed:
                lookup_failed = frozenset(unknown)

    mapping = _map_statement(conn, statement, today, lookup_failed)
    will_store, rejected, ignored = mapping.will_store, mapping.rejected, mapping.ignored
    exit_loads = mapping.exit_loads
    reconciliation = mapping.reconciliation
    blocking = _oversell_check(conn, portfolio_id, mapping.candidates)
    warnings = _warnings(conn, portfolio_id, statement, mapping)
    if lookup_failed:
        warnings.append(
            f"{len(lookup_failed)} ISIN(s) could not be looked up because AMFI's file could not be fetched; their "
            "rows are rejected as ISIN_LOOKUP_FAILED, not as unknown. Preview the statement again later."
        )
    mismatches = [r for r in reconciliation if r["status"] != "OK"]
    batch_id = pf._new_id("imp")
    already = pf._already_applied(conn, portfolio_id, sha)
    record = {
        "portfolio_id": portfolio_id,
        "file_sha256": sha,
        "label": LABEL,
        "kind": BATCH_KIND,
        "status": "previewed",
        "rows_accepted": len(will_store),
        "rows_rejected": len(rejected),
        "rows_ignored": len(ignored),
        "rejections": [{"row": r["row"], "reason": r["reason"]} for r in rejected],  # reasons only, no values
        "reconciliation_mismatches": len(mismatches),
        "blocking": len(blocking),
        "created_at": now.isoformat(),
        "applied_at": None,
        "pending": [
            {k: item[k] for k in ("instrument_id", "txn_date", "txn_type", "units", "amount", "nav")}
            for item in will_store
        ],
        # Kept after apply: the statement's coverage and its unit movements, to check "I did this" entries later.
        "statement_period": {"from": statement.period_from, "to": statement.period_to},
        "seen_moves": _seen_moves(will_store),
        "observed_exit_loads": exit_loads,
    }
    with write_tx(conn):
        conn.execute(
            "INSERT INTO settings(key, value_json) VALUES (?, ?)", (pf.IMPORT_KEY + batch_id, canonical_json(record))
        )
    log.info(
        "cas import previewed batch=%s accepted=%d rejected=%d ignored=%d mismatches=%d blocking=%d",
        batch_id, len(will_store), len(rejected), len(ignored), len(mismatches), len(blocking),
    )  # fmt: skip
    return {
        "batch_id": batch_id,
        "status": "previewed",
        "applied": False,
        "kind": BATCH_KIND,
        "label": LABEL,
        "file_sha256": sha,
        "issuer": statement.issuer,
        "statement_period": {"from": statement.period_from, "to": statement.period_to},
        "schemes": mapping.schemes,
        "will_store": will_store,
        "rejected": rejected,
        "ignored": ignored,
        "reconciliation": reconciliation,
        "reconciliation_ok": not mismatches,
        "observed_exit_loads": exit_loads,
        "blocking": blocking,
        "warnings": warnings,
        "already_applied": already,
        "confirm_with": {"sha256": sha, "accept_reconciliation_mismatches": bool(mismatches)},
        "privacy": "The PDF and its password were used in memory for this preview only and were not stored. Your "
        "name, PAN, email, address, phone and folio numbers were discarded.",
        "note": "Nothing has been stored yet. Confirm with the file's SHA-256 to apply exactly the rows listed.",
        "engine_version": SERVICE_VERSION,
    }


@dataclass
class _Mapping:
    will_store: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    ignored: list[dict[str, Any]] = field(default_factory=list)
    schemes: list[dict[str, Any]] = field(default_factory=list)
    reconciliation: list[dict[str, Any]] = field(default_factory=list)
    candidates: dict[str, list[pf.Txn]] = field(default_factory=dict)
    exit_loads: list[dict[str, Any]] = field(default_factory=list)


_SWITCH_TYPES = frozenset({"SWITCH_IN", "SWITCH_IN_MERGER", "SWITCH_OUT", "SWITCH_OUT_MERGER"})


def _map_statement(
    conn: sqlite3.Connection, statement: CasStatement, today: date, lookup_failed: frozenset[str] = frozenset()
) -> _Mapping:
    out = _Mapping()
    row = 0
    with engine_context():
        for s in statement.schemes:
            iid, iname, why = _match(conn, s)
            if iid is None and why == "UNKNOWN_ISIN" and s.isin in lookup_failed:
                why = "ISIN_LOOKUP_FAILED"  # unknown because AMFI could not be reached, not because it is absent
            net_units = ZERO
            moved_rows_not_stored = 0
            stt = _stt_by_date(s)
            for t in s.txns:
                row += 1
                m = map_txn(t, today)
                base = {"row": row, "scheme": s.block, "cas_type": t.cas_type, "txn_date": _iso(t.txn_date)}
                if iid is not None and m.action == "store" and m.txn_type == "sell":
                    seen = observe_exit_load(t, stt.get(t.txn_date) if t.txn_date else None)
                    if seen is not None:
                        out.exit_loads.append({**base, "instrument_id": iid, **seen})
                if m.action == "ignore":
                    out.ignored.append({**base, "reason": m.reason})
                    continue
                if m.action == "reject" or iid is None:
                    out.rejected.append({**base, "reason": m.reason if m.action == "reject" else why})
                    moved_rows_not_stored += 1 if t.units else 0
                    continue
                flags = ["SEGREGATED_PORTFOLIO"] if s.segregated else []
                if t.cas_type == "DIVIDEND_REINVEST":
                    flags.append("IDCW_REINVESTED_AS_BUY")
                if t.cas_type in _SWITCH_TYPES:
                    flags.append("SWITCH")
                out.will_store.append(
                    {**base, "instrument_id": iid, "instrument_name": iname, "isin": s.isin, "txn_type": m.txn_type,
                     "units": _s(m.units), "amount": _s(m.amount), "nav": _s(t.nav), "flags": flags}
                )  # fmt: skip
                if m.txn_type in {"buy", "sell"} and m.units is not None and m.amount is not None:
                    net_units += m.units if m.txn_type == "buy" else -m.units
                    out.candidates.setdefault(iid, []).append(
                        pf.Txn(f"cas{row:06d}", iid, t.txn_date or today, m.txn_type, m.units, m.amount, "")
                    )
            out.schemes.append(
                {"scheme": s.block, "isin": s.isin, "isin_problem": s.isin_problem, "rta": s.rta,
                 "instrument_id": iid, "instrument_name": iname, "match": "EXACT_ISIN" if iid else why,
                 "segregated_portfolio": s.segregated, "transactions_in_statement": len(s.txns)}
            )  # fmt: skip
            out.reconciliation.append(_reconcile(s, iid, net_units, moved_rows_not_stored))
    return out


# ----------------------------------------------------------------------------- observed exit loads (CAS gap)

EXIT_LOAD_FORMULA = "cas_exit_load_implied@1"
EXIT_LOAD_TOLERANCE = Decimal("0.01")  # PARAMETER: the printed amount is rounded to paise
PAISE = Decimal("0.01")
RATE_DP = Decimal("0.000001")


def _stt_by_date(s: CasScheme) -> dict[date, Decimal]:
    out: dict[date, Decimal] = {}
    for t in s.txns:
        if t.cas_type == "STT_TAX" and t.txn_date is not None and t.amount is not None:
            out[t.txn_date] = out.get(t.txn_date, ZERO) + abs(t.amount)
    return out


def observe_exit_load(t: CasTxn, stt_same_day: Decimal | None) -> dict[str, Any] | None:
    """The exit load a redemption/switch-out row implies, as an OBSERVED fact (never an assumed one).

    ``deduction = |units| x price - |amount|``; minus a same-day STT row when the statement has one. Within the paise
    tolerance -> NO_LOAD_OBSERVED; a positive remainder -> LOAD_OBSERVED with its rate on the gross; an amount above
    units x price -> INCONSISTENT (nothing is inferred). ``None`` when units, price or amount is missing. Always NOT
    VERIFIED, flagged PRICE_ASSUMED_NAV_BEFORE_LOAD (and STT_SEPARATION_NOT_VERIFIED when an STT row was used)."""
    if t.units is None or t.nav is None or t.amount is None or t.nav <= 0 or t.units == 0:
        return None
    with engine_context():
        gross = abs(t.units) * t.nav
        deduction = gross - abs(t.amount)
        stt = stt_same_day or ZERO
        load = deduction - stt
        flags = ["PRICE_ASSUMED_NAV_BEFORE_LOAD"] + (["STT_SEPARATION_NOT_VERIFIED"] if stt_same_day else [])
        if deduction < -EXIT_LOAD_TOLERANCE or load < -EXIT_LOAD_TOLERANCE:
            observation, load_inr, rate = "INCONSISTENT", None, None
        elif load <= EXIT_LOAD_TOLERANCE:
            observation, load_inr, rate = "NO_LOAD_OBSERVED", ZERO, ZERO
        else:
            observation = "LOAD_OBSERVED"
            load_inr = load.quantize(PAISE, rounding=ROUND_HALF_UP)
            rate = (load / gross).quantize(RATE_DP, rounding=ROUND_HALF_UP)
    return {
        "units": _s(abs(t.units)), "price": _s(t.nav), "amount": _s(abs(t.amount)),
        "gross": _s(gross.quantize(PAISE, rounding=ROUND_HALF_UP)), "stt_same_day": _s(stt_same_day),
        "observation": observation, "exit_load_inr": _s(load_inr), "implied_rate": _s(rate),
        "formula_id": EXIT_LOAD_FORMULA, "status": "NOT VERIFIED", "flags": flags,
    }  # fmt: skip


def observed_exit_loads(conn: sqlite3.Connection, instrument_id: str | None = None) -> list[dict[str, Any]]:
    """Exit loads observed in APPLIED CAS imports (one statement), newest statement first."""
    out: list[dict[str, Any]] = []
    rows = conn.execute("SELECT key, value_json FROM settings WHERE key LIKE ?", (pf.IMPORT_KEY + "%",)).fetchall()
    for r in rows:
        rec = json.loads(r["value_json"])
        if rec.get("kind") != BATCH_KIND or rec.get("status") != "applied":
            continue
        for item in rec.get("observed_exit_loads") or []:
            if instrument_id is None or item["instrument_id"] == instrument_id:
                out.append({**item, "batch_id": r["key"].removeprefix(pf.IMPORT_KEY),
                            "applied_at": rec.get("applied_at")})  # fmt: skip
    return sorted(out, key=lambda x: (str(x["applied_at"]), str(x["txn_date"])), reverse=True)


# ----------------------------------------------------------------------------- "I did this" vs the next CAS

CONFIRM_WINDOW_DAYS = 10  # PARAMETER (design-user-first.md §11): absent 10 days after the click -> contradicted
CONFIRM_LOOKBACK_DAYS = 7  # PARAMETER: a transaction up to 7 days before the click still counts (allotment lag)


@dataclass(frozen=True)
class ExpectedMove:
    instrument_id: str
    direction: Literal["in", "out"]


@dataclass(frozen=True)
class DecisionCheck:
    decision_id: int
    decided_on: date
    moves: tuple[ExpectedMove, ...]


def moves_from_steps(steps: Sequence[Step]) -> tuple[ExpectedMove, ...]:
    """The unit movements a card's steps imply: INVEST -> in, REDEEM and SWITCH -> out of the step's scheme.
    REDIRECT_SIP, WAIT_UNTIL, REVIEW and an INVEST without a scheme cannot be seen in one statement (empty)."""
    out: list[ExpectedMove] = []
    for st in steps:
        if st.instrument_id is None:
            continue
        if st.verb is Verb.INVEST:
            out.append(ExpectedMove(st.instrument_id, "in"))
        elif st.verb in (Verb.REDEEM, Verb.SWITCH):
            out.append(ExpectedMove(st.instrument_id, "out"))
    return tuple(dict.fromkeys(out))


def _seen_moves(will_store: Sequence[dict[str, Any]]) -> list[list[str]]:
    """[instrument_id, date, in|out] per stored unit movement. IDCW reinvestment is not a decision: left out."""
    out = []
    for item in will_store:
        if item["txn_type"] not in ("buy", "sell") or "IDCW_REINVESTED_AS_BUY" in item.get("flags", []):
            continue
        out.append([item["instrument_id"], item["txn_date"], "in" if item["txn_type"] == "buy" else "out"])
    return out


def _period_date(text: str | None) -> date | None:
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%B-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(text or "").strip(), fmt).date()
        except ValueError:
            continue
    return None


def judge_decisions(
    checks: Sequence[DecisionCheck], seen: Sequence[Sequence[str]], period_from: date | None, period_to: date | None
) -> dict[int, str]:
    """CONFIRMED when every expected movement appears within [decided - lookback, decided + window]; CONTRADICTED when
    one does not and the statement covers that whole window; UNDETERMINED otherwise (no movement to look for, or a
    statement that does not cover the window). Pure."""
    moves = {(str(i), date.fromisoformat(str(d)), str(direction)) for i, d, direction in seen}
    out: dict[int, str] = {}
    for c in checks:
        lo = c.decided_on - timedelta(days=CONFIRM_LOOKBACK_DAYS)
        hi = c.decided_on + timedelta(days=CONFIRM_WINDOW_DAYS)
        if not c.moves:
            out[c.decision_id] = "UNDETERMINED"
            continue
        found = [any(i == m.instrument_id and dr == m.direction and lo <= d <= hi for i, d, dr in moves)
                 for m in c.moves]  # fmt: skip
        covered = period_from is not None and period_to is not None and period_from <= lo and period_to >= hi
        out[c.decision_id] = "CONFIRMED" if all(found) else ("CONTRADICTED" if covered else "UNDETERMINED")
    return out


def _apply_decision_checks(
    conn: sqlite3.Connection, batch_id: str, rec: dict[str, Any], checks: Sequence[DecisionCheck], now: datetime
) -> dict[str, Any]:
    period = rec.get("statement_period") or {}
    verdicts = judge_decisions(checks, rec.get("seen_moves") or [], _period_date(period.get("from")),
                               _period_date(period.get("to")))  # fmt: skip
    results = [(d, v == "CONFIRMED") for d, v in sorted(verdicts.items()) if v != "UNDETERMINED"]
    written = confirm_decisions_from_cas(conn, results, now.isoformat(), batch_id) if results else 0
    return {
        "confirmed": sorted(d for d, v in verdicts.items() if v == "CONFIRMED"),
        "contradicted": sorted(d for d, v in verdicts.items() if v == "CONTRADICTED"),
        "undetermined": sorted(d for d, v in verdicts.items() if v == "UNDETERMINED"),
        "written": written,
    }


def pending_done_decisions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """'done' decisions no CAS has checked yet (one statement): the input B02 maps to :class:`DecisionCheck`."""
    return conn.execute(
        "SELECT decision_id, card_id, snapshot_id, goal_id, decided_at FROM decisions_log"
        " WHERE decision = 'done' AND cas_confirmed IS NULL ORDER BY decision_id"
    ).fetchall()


def confirm_decisions_with_cas(
    conn: sqlite3.Connection, batch_id: str, checks: Sequence[DecisionCheck], now: datetime
) -> dict[str, Any]:
    """Check "I did this" entries against an APPLIED CAS batch and record the verdicts once (one transaction)."""
    row = conn.execute("SELECT value_json FROM settings WHERE key=?", (pf.IMPORT_KEY + batch_id,)).fetchone()
    if row is None:
        raise pf.PortfolioError("NOT_FOUND", "import batch not found", 404)
    rec: dict[str, Any] = json.loads(row["value_json"])
    if rec.get("kind") != BATCH_KIND or rec.get("status") != "applied":
        raise pf.PortfolioError("NOT_APPLIED", "only an applied CAS import can confirm decisions", 409)
    with write_tx(conn):
        return _apply_decision_checks(conn, batch_id, rec, checks, now)


def _warnings(conn: sqlite3.Connection, portfolio_id: str, statement: CasStatement, mapping: _Mapping) -> list[str]:
    warnings = [COST_NOTE]
    if statement.parser_warnings:
        warnings.append(
            f"The statement parser reported {statement.parser_warnings} data-quality warning(s): a row may have been "
            "dropped or misread. Check the reconciliation below against your statement."
        )
    held = {t.instrument_id for t in pf.load_txns(conn, portfolio_id)}
    for iid in sorted(set(mapping.candidates) & held):
        warnings.append(
            f"This portfolio already has transactions for {iid}; importing may double-count units already entered."
        )
    if any(s.segregated for s in statement.schemes):
        warnings.append("A segregated portfolio is present; its rows are flagged SEGREGATED_PORTFOLIO.")
    return warnings


def _iso(d: date | None) -> str | None:
    return None if d is None else d.isoformat()


def _reconcile(s: CasScheme, iid: str | None, net_units: Decimal, moved_rows_not_stored: int) -> dict[str, Any]:
    """Closing units printed on the CAS vs the net units this import would put in the book for the scheme."""
    causes: list[str] = []
    if iid is None:
        causes.append("SCHEME_UNMATCHED")
    if s.opening_units != 0:
        causes.append("OPENING_BALANCE_NOT_IMPORTED")
    if moved_rows_not_stored:
        causes.append("UNIT_ROWS_NOT_IMPORTED")
    diff = s.closing_units - net_units
    status = "OK" if diff == 0 and iid is not None else ("UNMATCHED" if iid is None else "MISMATCH")
    if status == "MISMATCH" and not causes:
        causes.append("TRANSACTIONS_DO_NOT_SUM_TO_CLOSING_BALANCE")
    return {
        "scheme": s.block,
        "isin": s.isin,
        "instrument_id": iid,
        "cas_opening_units": _s(s.opening_units),
        "cas_closing_units": _s(s.closing_units),
        "imported_net_units": _s(net_units),
        "difference": _s(diff),
        "status": status,
        "causes": causes,
    }


def _oversell_check(
    conn: sqlite3.Connection, portfolio_id: str, candidates: dict[str, list[pf.Txn]]
) -> list[dict[str, Any]]:
    existing = pf.load_txns(conn, portfolio_id)
    out: list[dict[str, Any]] = []
    for iid, txns in sorted(candidates.items()):
        try:
            pf.fifo_positions([*(t for t in existing if t.instrument_id == iid), *txns])
        except pf.Oversell as exc:
            out.append({"code": "OVERSELL", "instrument_id": iid, "message": exc.message})
    return out


def apply_cas_import(
    conn: sqlite3.Connection,
    batch_id: str,
    body: CasApplyIn,
    now: datetime,
    *,
    pre_change: Callable[[], object] | None = None,
    decisions: Sequence[DecisionCheck] | None = None,
) -> dict[str, Any]:
    """Apply a confirmed CAS preview in ONE transaction; ``pre_change`` (the backup) runs after every check and
    before any write. An oversell anywhere in the resulting book rolls everything back. ``decisions`` ("I did this"
    entries not yet checked) are confirmed or contradicted by this statement in the same transaction."""
    key = pf.IMPORT_KEY + batch_id
    row = conn.execute("SELECT value_json FROM settings WHERE key=?", (key,)).fetchone()
    if row is None:
        raise pf.PortfolioError("NOT_FOUND", "import batch not found", 404)
    rec: dict[str, Any] = json.loads(row["value_json"])
    if rec.get("kind") != BATCH_KIND:
        raise pf.PortfolioError("WRONG_APPLY_ENDPOINT", "this batch is not a CAS import; use the file import", 409)
    if rec["status"] != "previewed":
        raise pf.PortfolioError("ALREADY_APPLIED", "this import batch has already been applied", 409)
    if body.sha256 != rec["file_sha256"]:
        raise pf.PortfolioError("PREVIEW_MISMATCH", "confirmation does not match the previewed file", 409)
    if now - datetime.fromisoformat(rec["created_at"]) > pf.IMPORT_PREVIEW_TTL:
        raise pf.PortfolioError("PREVIEW_EXPIRED", "the preview is older than 24 hours; upload the file again", 410)
    pid = rec["portfolio_id"]
    if pf._already_applied(conn, pid, body.sha256):
        raise pf.PortfolioError("ALREADY_APPLIED", "this file has already been imported into this portfolio", 409)
    if rec["reconciliation_mismatches"] and not body.accept_reconciliation_mismatches:
        raise pf.PortfolioError(
            "RECONCILIATION_NOT_ACKNOWLEDGED",
            "closing units on the statement do not match the imported transactions for "
            f"{rec['reconciliation_mismatches']} scheme(s); review and acknowledge them to apply",
            409,
        )
    pending: list[dict[str, Any]] = rec["pending"]
    if not pending:
        raise pf.PortfolioError("NOTHING_TO_APPLY", "the preview has no accepted rows", 422)
    if pre_change is not None:
        pre_change()
    with write_tx(conn):
        pf.claim_previewed_batch(conn, key, pid, body.sha256)
        pf._portfolio(conn, pid)
        for item in pending:
            conn.execute(
                "INSERT INTO transactions(txn_id, portfolio_id, instrument_id, txn_date, txn_type, units, amount,"
                " price, source, import_batch, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (pf._new_id("tx"), pid, item["instrument_id"], item["txn_date"], item["txn_type"], item["units"],
                 item["amount"], item["nav"], TXN_SOURCE, batch_id, now.isoformat()),
            )  # fmt: skip
        pf.fifo_positions(pf.load_txns(conn, pid))  # raises Oversell → ROLLBACK, nothing written
        rec.update(status="applied", applied_at=now.isoformat(), pending=None)
        conn.execute("UPDATE settings SET value_json=? WHERE key=?", (canonical_json(rec), key))
        pf._audit(conn, now, "import.apply", pid, f"batch={batch_id} kind={BATCH_KIND} rows={len(pending)}")
        checked = _apply_decision_checks(conn, batch_id, rec, decisions, now) if decisions else None
    # Reaching this line means COMMIT succeeded; only now is the import reported as applied.
    log.info("cas import applied batch=%s rows=%d", batch_id, len(pending))
    return {
        "batch_id": batch_id,
        "status": "applied",
        "applied": True,
        "portfolio_id": pid,
        "transactions_created": len(pending),
        "rows_rejected": rec["rows_rejected"],
        "rows_ignored": rec.get("rows_ignored", 0),
        "reconciliation_mismatches_accepted": rec["reconciliation_mismatches"],
        "observed_exit_loads": len(rec.get("observed_exit_loads") or []),
        "decisions": checked,
        "applied_at": now.isoformat(),
    }
