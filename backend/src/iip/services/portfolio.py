"""Portfolios, holdings, import, summary, watchlist, evidence and privacy (Stage D; ux-design pages 2, 11, 13, 15).

* ``actual`` and ``hypothetical`` portfolios are separate rows and are never aggregated together (the only cross-
  portfolio figure is DICGC exposure, which by law aggregates every *actual* deposit at one bank).
* Positions are FIFO lots built from the user's transactions. A sell beyond the units held at that date is refused
  (``Oversell``) — never silently truncated.
* Valuation uses the latest stored NAV only. A NAV that is STALE, missing or of unusable quality excludes the holding
  from every total, with an explicit note. Older NAVs are never forward-filled. Non-MF holdings have no market price
  source in v1 and are shown at cost, outside market-value totals.
* Logging carries ids and counts only — never amounts, units, names or file labels (threat-model C-13, SEC-62).
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from iip.data import imports
from iip.data.export import export_holdings_csv
from iip.engine import deposits as dep
from iip.engine.candidates import mf_lock_in_days, mf_tier_from_category
from iip.engine.determinism import canonical_json, content_hash, sha256_hex
from iip.engine.errors import EngineError
from iip.engine.money import ONE, ZERO, engine_context, format_inr, money, pct
from iip.engine.ranking import Tier
from iip.engine.returns import CashFlow, XirrOutcome, xirr
from iip.engine.stats.metrics import hhi_from_values
from iip.services import ingestion
from iip.services.explain import source_ref
from iip.services.instruments import TBILL_STALE_DAYS
from iip.store.db import backup as db_backup
from iip.store.db import current_version, write_tx

log = logging.getLogger("iip.portfolio")

SERVICE_VERSION = "portfolio@1.0.0"
USABLE_QUALITY = ("ok", "manual", "fixture")
UNITS_RE = re.compile(r"[0-9]{1,15}(?:\.[0-9]{1,6})?")
AMOUNT_RE = re.compile(r"[0-9]{1,15}(?:\.[0-9]{1,2})?")
MAX_UNITS_DP = 6
MAX_AMOUNT_DP = 2
IMPORT_PREVIEW_TTL = timedelta(hours=24)
IMPORT_KEY = "import.batch:"
LADDER_BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("0-7 days", 0, 7),
    ("8-30 days", 8, 30),
    ("31-90 days", 31, 90),
    ("91-365 days", 91, 365),
    ("over 365 days", 366, None),
)
LADDER_SPECIAL = ("matured or overdue", "unknown")
SENSITIVITY_SHOCK = Decimal("0.05")
USER_TABLES = ("transactions", "portfolios", "watchlist", "alerts", "runs", "audit_events", "settings", "profiles")
assert all(t.isidentifier() for t in USER_TABLES)
PUBLIC_TABLES = (
    "sources",
    "ingestion_runs",
    "issuers",
    "instruments",
    "mf_schemes",
    "bond_terms",
    "deposit_terms",
    "observations",
)
ERASE_PHRASE = "ERASE ALL MY DATA"


class PortfolioError(Exception):
    """A refused request. ``status`` is the HTTP status the API returns."""

    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class Oversell(PortfolioError):
    def __init__(self, instrument_id: str, on: date, requested: Decimal, held: Decimal) -> None:
        super().__init__(
            "OVERSELL",
            f"sell of {format(requested, 'f')} units of {instrument_id} on {on.isoformat()} exceeds the "
            f"{format(held, 'f')} units held on that date",
        )
        self.instrument_id = instrument_id
        self.on = on
        self.requested = requested
        self.held = held


# ----------------------------------------------------------------------------- request models


def _decimal_string(v: object, pattern: re.Pattern[str], what: str) -> str:
    if not isinstance(v, str):
        raise ValueError(f'{what} must be a decimal string such as "125.50" (floats and numbers are refused)')
    if not pattern.fullmatch(v):
        raise ValueError(f"{what} must be a plain positive decimal string with no grouping or exponent")
    if Decimal(v) <= 0:
        raise ValueError(f"{what} must be greater than zero")
    return v


class PortfolioIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    nature: Literal["actual", "hypothetical"]


class TransactionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instrument_id: str = Field(min_length=1, max_length=120)
    txn_date: date
    txn_type: Literal["buy", "sell"]
    units: str = Field(max_length=40)
    amount: str = Field(max_length=40)

    @field_validator("units", mode="before")
    @classmethod
    def _units(cls, v: object) -> str:
        return _decimal_string(v, UNITS_RE, "units")

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, v: object) -> str:
        return _decimal_string(v, AMOUNT_RE, "amount")


class WatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instrument_id: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=500)


class ApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EraseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: Literal["ERASE ALL MY DATA"]
    delete_backups: bool = False


# ----------------------------------------------------------------------------- helpers


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def _s(d: Decimal | None) -> str | None:
    return None if d is None else format(d, "f")


def _audit(conn: sqlite3.Connection, at: datetime, action: str, subject: str | None, detail: str | None) -> None:
    """Audit rows carry ids and counts only (never amounts or names)."""
    conn.execute(
        "INSERT INTO audit_events(at, action, subject, detail) VALUES (?, ?, ?, ?)",
        (at.isoformat(), action, subject, detail),
    )


def _explained(
    *,
    eid: str,
    label: str,
    value: Decimal | None,
    unit: str,
    display: str,
    what: str,
    formula_id: str,
    formula: str,
    substituted: str,
    inputs: Sequence[str],
    sources: Sequence[dict[str, Any]],
    observed: str | None,
    freshness: str,
    assumptions: Sequence[str] = (),
    sensitivity: Sequence[dict[str, str]] = (),
    limitations: Sequence[str] = (),
) -> dict[str, Any]:
    """The "Explain this number" payload (ux-design §5.1), same shape as ``discovery.explained_outcome``."""
    out: dict[str, Any] = {
        "id": eid,
        "label": label,
        "display": display,
        "value": _s(value),
        "unit": unit,
        "what": what,
        "formula_id": formula_id,
        "formula": formula,
        "substituted": substituted,
        "inputs": list(inputs),
        "sources": [source_ref(src) for src in sources],
        "observed": observed,
        "freshness": freshness,
        "assumptions": list(assumptions),
        "sensitivity": list(sensitivity),
        "limitations": list(limitations),
        "engine_version": SERVICE_VERSION,
    }
    out["hash"] = content_hash(out)
    return out


# ----------------------------------------------------------------------------- portfolios


def _portfolio(conn: sqlite3.Connection, portfolio_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM portfolios WHERE portfolio_id=?", (portfolio_id,)).fetchone()
    if row is None:
        raise PortfolioError("NOT_FOUND", "portfolio not found", 404)
    return row  # type: ignore[no-any-return]


def create_portfolio(conn: sqlite3.Connection, body: PortfolioIn, now: datetime) -> dict[str, Any]:
    name = imports.normalise_text(body.name)
    if not name:
        raise PortfolioError("BAD_NAME", "portfolio name is empty after normalisation")
    pid = _new_id("pf")
    with write_tx(conn):
        conn.execute(
            "INSERT INTO portfolios(portfolio_id, name, nature, created_at) VALUES (?, ?, ?, ?)",
            (pid, name, body.nature, now.isoformat()),
        )
        _audit(conn, now, "portfolio.create", pid, f"nature={body.nature}")
    log.info("portfolio created id=%s nature=%s", pid, body.nature)
    return {"portfolio_id": pid, "name": name, "nature": body.nature, "created_at": now.isoformat()}


def list_portfolios(conn: sqlite3.Connection, nature: str | None = None) -> list[dict[str, Any]]:
    sql = (
        "SELECT p.portfolio_id, p.name, p.nature, p.created_at,"
        " (SELECT COUNT(*) FROM transactions t WHERE t.portfolio_id = p.portfolio_id) AS transactions"
        " FROM portfolios p"
    )
    params: list[str] = []
    if nature is not None:
        if nature not in {"actual", "hypothetical"}:
            raise PortfolioError("BAD_NATURE", "nature must be actual or hypothetical")
        sql += " WHERE p.nature = ?"
        params.append(nature)
    sql += " ORDER BY p.nature, p.created_at, p.portfolio_id"
    return [dict(r) for r in conn.execute(sql, params)]


# ----------------------------------------------------------------------------- transactions & FIFO


@dataclass(frozen=True)
class Txn:
    txn_id: str
    instrument_id: str
    txn_date: date
    txn_type: str
    units: Decimal
    amount: Decimal
    created_at: str


@dataclass(frozen=True)
class Lot:
    txn_id: str
    acquired: date
    units: Decimal  # remaining
    cost: Decimal  # remaining cost basis (unrounded)


@dataclass(frozen=True)
class Position:
    instrument_id: str
    lots: tuple[Lot, ...]
    units: Decimal
    cost: Decimal
    realised_proceeds: Decimal
    realised_cost: Decimal


@dataclass
class _Book:
    lots: list[Lot] = field(default_factory=list)
    proceeds: Decimal = ZERO
    sold_cost: Decimal = ZERO


_TYPE_ORDER = {"buy": 0, "sell": 1}


def fifo_positions(txns: Iterable[Txn]) -> dict[str, Position]:
    """FIFO lots per instrument. Same-date buys are applied before sells. Raises ``Oversell`` (never truncates).
    ``dividend`` rows (IDCW payouts, e.g. from a CAS import) carry no units and are skipped here."""
    books: dict[str, _Book] = {}
    ordered = sorted(txns, key=lambda t: (t.txn_date, _TYPE_ORDER.get(t.txn_type, 2), t.created_at, t.txn_id))
    with engine_context():
        for t in ordered:
            if t.txn_type == "dividend":  # IDCW payout: a cash inflow (XIRR) that moves no units and no lots
                continue
            if t.txn_type not in _TYPE_ORDER:
                raise PortfolioError("UNSUPPORTED_TXN_TYPE", f"transaction type {t.txn_type!r} is not modelled", 409)
            if t.units <= 0:
                raise PortfolioError("BAD_UNITS", f"transaction {t.txn_id} has non-positive units", 409)
            book = books.setdefault(t.instrument_id, _Book())
            if t.txn_type == "buy":
                book.lots.append(Lot(t.txn_id, t.txn_date, t.units, t.amount))
                continue
            held = sum((lot.units for lot in book.lots), ZERO)
            if t.units > held:
                raise Oversell(t.instrument_id, t.txn_date, t.units, held)
            remaining = t.units
            consumed_cost = ZERO
            new_lots: list[Lot] = []
            for lot in book.lots:
                if remaining == 0:
                    new_lots.append(lot)
                    continue
                take = min(lot.units, remaining)
                if take == lot.units:
                    consumed_cost += lot.cost
                else:
                    part = lot.cost * take / lot.units
                    consumed_cost += part
                    new_lots.append(Lot(lot.txn_id, lot.acquired, lot.units - take, lot.cost - part))
                remaining -= take
            book.lots = new_lots
            book.proceeds += t.amount
            book.sold_cost += consumed_cost
        return {
            iid: Position(
                iid,
                tuple(b.lots),
                sum((lot.units for lot in b.lots), ZERO),
                sum((lot.cost for lot in b.lots), ZERO),
                b.proceeds,
                b.sold_cost,
            )
            for iid, b in sorted(books.items())
        }


def _txn(row: sqlite3.Row) -> Txn:
    return Txn(
        txn_id=row["txn_id"],
        instrument_id=row["instrument_id"],
        txn_date=date.fromisoformat(row["txn_date"]),
        txn_type=row["txn_type"],
        units=Decimal(row["units"]) if row["units"] is not None else ZERO,
        amount=Decimal(row["amount"]),
        created_at=row["created_at"],
    )


def load_txns(conn: sqlite3.Connection, portfolio_id: str) -> list[Txn]:
    rows = conn.execute(
        "SELECT * FROM transactions WHERE portfolio_id=? ORDER BY txn_date, created_at, txn_id", (portfolio_id,)
    ).fetchall()
    return [_txn(r) for r in rows]


def list_transactions(conn: sqlite3.Connection, portfolio_id: str) -> dict[str, Any]:
    p = _portfolio(conn, portfolio_id)
    rows = conn.execute(
        "SELECT t.txn_id, t.instrument_id, i.name AS instrument_name, t.txn_date, t.txn_type, t.units, t.amount,"
        " t.price, t.source, t.import_batch, t.created_at FROM transactions t"
        " JOIN instruments i USING(instrument_id) WHERE t.portfolio_id=? ORDER BY t.txn_date, t.created_at, t.txn_id",
        (portfolio_id,),
    ).fetchall()
    return {"portfolio_id": portfolio_id, "nature": p["nature"], "items": [dict(r) for r in rows]}


def _instrument(conn: sqlite3.Connection, instrument_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM instruments WHERE instrument_id=?", (instrument_id,)).fetchone()
    if row is None:
        raise PortfolioError("UNKNOWN_INSTRUMENT", "instrument is not in the local store", 422)
    return row  # type: ignore[no-any-return]


def add_transaction(conn: sqlite3.Connection, portfolio_id: str, body: TransactionIn, now: datetime) -> dict[str, Any]:
    _portfolio(conn, portfolio_id)
    _instrument(conn, body.instrument_id)
    if body.txn_date > now.date():
        raise PortfolioError("FUTURE_DATE", "transaction date is in the future")
    units, amount = Decimal(body.units), Decimal(body.amount)
    txn_id = _new_id("tx")
    with write_tx(conn):
        existing = [t for t in load_txns(conn, portfolio_id) if t.instrument_id == body.instrument_id]
        candidate = Txn(txn_id, body.instrument_id, body.txn_date, body.txn_type, units, amount, now.isoformat())
        fifo_positions([*existing, candidate])  # raises Oversell → rolled back, nothing written
        conn.execute(
            "INSERT INTO transactions(txn_id, portfolio_id, instrument_id, txn_date, txn_type, units, amount, price,"
            " source, import_batch, created_at) VALUES (?,?,?,?,?,?,?,NULL,'manual',NULL,?)",
            (txn_id, portfolio_id, body.instrument_id, body.txn_date.isoformat(), body.txn_type, body.units,
             body.amount, now.isoformat()),
        )  # fmt: skip
        _audit(conn, now, "transaction.add", portfolio_id, f"txn={txn_id} type={body.txn_type}")
    log.info("transaction added portfolio=%s txn=%s type=%s", portfolio_id, txn_id, body.txn_type)
    return {"txn_id": txn_id, "status": "stored"}


def delete_transaction(conn: sqlite3.Connection, portfolio_id: str, txn_id: str, now: datetime) -> dict[str, Any]:
    _portfolio(conn, portfolio_id)
    with write_tx(conn):
        txns = load_txns(conn, portfolio_id)
        target = next((t for t in txns if t.txn_id == txn_id), None)
        if target is None:
            raise PortfolioError("NOT_FOUND", "transaction not found", 404)
        try:
            fifo_positions([t for t in txns if t.txn_id != txn_id and t.instrument_id == target.instrument_id])
        except Oversell as exc:
            raise PortfolioError(
                "WOULD_OVERSELL", "deleting this buy would leave a later sell exceeding the units held", 409
            ) from exc
        conn.execute("DELETE FROM transactions WHERE txn_id=? AND portfolio_id=?", (txn_id, portfolio_id))
        _audit(conn, now, "transaction.delete", portfolio_id, f"txn={txn_id}")
    log.info("transaction deleted portfolio=%s txn=%s", portfolio_id, txn_id)
    return {"status": "deleted"}


# ----------------------------------------------------------------------------- holdings import (preview → apply)


def _resolve_instrument(conn: sqlite3.Connection, row: imports.HoldingRow) -> tuple[str | None, str | None, str]:
    """→ (instrument_id, instrument_name, reason). Matching is by identifier only; names are never matched."""
    by_code = by_isin = None
    if row.amfi_code is not None:
        by_code = conn.execute(
            "SELECT instrument_id, name FROM instruments WHERE amfi_code=?", (str(row.amfi_code),)
        ).fetchone()
        if by_code is None:
            return None, None, "UNKNOWN_AMFI_CODE"
    if row.isin is not None:
        found = conn.execute("SELECT instrument_id, name FROM instruments WHERE isin=?", (row.isin,)).fetchall()
        if len(found) > 1:
            return None, None, "AMBIGUOUS_ISIN"
        by_isin = found[0] if found else None
        if by_isin is None and by_code is None:
            return None, None, "UNKNOWN_ISIN"
    if by_code is not None and by_isin is not None and by_code["instrument_id"] != by_isin["instrument_id"]:
        return None, None, "CONFLICTING_IDENTIFIERS"
    hit = by_code or by_isin
    if hit is None:
        return None, None, "UNIDENTIFIED"
    return hit["instrument_id"], hit["name"], ""


def _dp(d: Decimal) -> int:
    exp = d.as_tuple().exponent
    return -exp if isinstance(exp, int) and exp < 0 else 0


def _row_to_txn(conn: sqlite3.Connection, row: imports.HoldingRow, today: date) -> dict[str, Any] | str:
    iid, iname, reason = _resolve_instrument(conn, row)
    if iid is None:
        return reason
    if row.cost_basis_inr is None:
        return "MISSING_COST_BASIS"
    if row.cost_basis_inr <= 0:
        return "COST_NOT_POSITIVE"
    if row.purchase_date is None:
        return "MISSING_PURCHASE_DATE"
    if row.purchase_date > today:
        return "FUTURE_DATE"
    if _dp(row.units) > MAX_UNITS_DP:
        return "UNITS_PRECISION"
    if _dp(row.cost_basis_inr) > MAX_AMOUNT_DP:
        return "AMOUNT_PRECISION"
    return {
        "instrument_id": iid,
        "instrument_name": iname,
        "file_instrument_name": row.instrument_name,
        "txn_date": row.purchase_date.isoformat(),
        "txn_type": "buy",
        "units": format(row.units, "f"),
        "amount": format(row.cost_basis_inr, "f"),
        "flags": list(row.flags),
    }


def _batches(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT key, value_json FROM settings WHERE key LIKE ?", (IMPORT_KEY + "%",)).fetchall()
    return [{"batch_id": r["key"][len(IMPORT_KEY) :], **json.loads(r["value_json"])} for r in rows]


def _already_applied(conn: sqlite3.Connection, portfolio_id: str, sha: str) -> bool:
    return any(
        b["status"] == "applied" and b["portfolio_id"] == portfolio_id and b["file_sha256"] == sha
        for b in _batches(conn)
    )


def preview_holdings_import(
    conn: sqlite3.Connection, portfolio_id: str, data: bytes, filename: str, encoding: str | None, now: datetime
) -> dict[str, Any]:
    """Parse and validate (``iip.data.imports``), resolve instruments, and store a *pending* batch. Nothing is
    written to ``transactions`` until ``apply_holdings_import`` commits."""
    _portfolio(conn, portfolio_id)
    preview = imports.preview_import(data, filename, encoding=encoding)
    will_store: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = [
        {"line": r.line_no, "reason": r.reason, "stage": "parse"} for r in preview.rejected
    ]
    for i, row in enumerate(preview.rows, start=1):
        out = _row_to_txn(conn, row, now.date())
        if isinstance(out, str):
            rejected.append({"row": i, "reason": out, "stage": "resolve"})
        else:
            will_store.append({"row": i, **out})
    batch_id = _new_id("imp")
    already = _already_applied(conn, portfolio_id, preview.file_sha256)
    record = {
        "portfolio_id": portfolio_id,
        "file_sha256": preview.file_sha256,
        "label": preview.label,
        "kind": preview.kind,
        "status": "previewed",
        "rows_accepted": len(will_store),
        "rows_rejected": len(rejected),
        "rejections": [{k: v for k, v in r.items() if k != "stage"} for r in rejected],  # reasons only, no values
        "created_at": now.isoformat(),
        "applied_at": None,
        "pending": will_store,
    }
    with write_tx(conn):
        conn.execute(
            "INSERT INTO settings(key, value_json) VALUES (?, ?)", (IMPORT_KEY + batch_id, canonical_json(record))
        )
    log.info(
        "import previewed batch=%s accepted=%d rejected=%d warnings=%d",
        batch_id, len(will_store), len(rejected), len(preview.warnings),
    )  # fmt: skip
    return {
        "batch_id": batch_id,
        "status": "previewed",
        "applied": False,
        "file_sha256": preview.file_sha256,
        "label": preview.label,
        "kind": preview.kind,
        "header": list(preview.header),
        "will_store": will_store,
        "rejected": rejected,
        "warnings": list(preview.warnings),
        "already_applied": already,
        "confirm_with": {"sha256": preview.file_sha256},
        "note": "Nothing has been stored yet. Confirm with the file's SHA-256 to apply exactly the rows listed.",
    }


def apply_holdings_import(
    conn: sqlite3.Connection,
    batch_id: str,
    sha256: str,
    now: datetime,
    *,
    pre_change: Callable[[], object] | None = None,
) -> dict[str, Any]:
    """Apply a confirmed preview in ONE transaction. ``pre_change`` (e.g. a pre-change backup) runs after every
    check has passed and before anything is written; if it raises, nothing is written."""
    key = IMPORT_KEY + batch_id
    row = conn.execute("SELECT value_json FROM settings WHERE key=?", (key,)).fetchone()
    if row is None:
        raise PortfolioError("NOT_FOUND", "import batch not found", 404)
    rec: dict[str, Any] = json.loads(row["value_json"])
    if rec.get("kind") not in {"csv", "xlsx"}:  # e.g. a CAS batch: it carries sells and dividends, not only buys
        raise PortfolioError("WRONG_APPLY_ENDPOINT", "this batch is not a CSV/XLSX import; use its own apply", 409)
    if rec["status"] != "previewed":
        raise PortfolioError("ALREADY_APPLIED", "this import batch has already been applied", 409)
    if sha256 != rec["file_sha256"]:
        raise PortfolioError("PREVIEW_MISMATCH", "confirmation does not match the previewed file", 409)
    if now - datetime.fromisoformat(rec["created_at"]) > IMPORT_PREVIEW_TTL:
        raise PortfolioError("PREVIEW_EXPIRED", "the preview is older than 24 hours; upload the file again", 410)
    pid = rec["portfolio_id"]
    if _already_applied(conn, pid, sha256):
        raise PortfolioError("ALREADY_APPLIED", "this file has already been imported into this portfolio", 409)
    pending: list[dict[str, Any]] = rec["pending"]
    if not pending:
        raise PortfolioError("NOTHING_TO_APPLY", "the preview has no accepted rows", 422)
    if pre_change is not None:
        pre_change()
    with write_tx(conn):
        _portfolio(conn, pid)
        for item in pending:
            conn.execute(
                "INSERT INTO transactions(txn_id, portfolio_id, instrument_id, txn_date, txn_type, units, amount,"
                " price, source, import_batch, created_at) VALUES (?,?,?,?,'buy',?,?,NULL,'csv_import',?,?)",
                (_new_id("tx"), pid, item["instrument_id"], item["txn_date"], item["units"], item["amount"],
                 batch_id, now.isoformat()),
            )  # fmt: skip
        fifo_positions(load_txns(conn, pid))  # whole-book consistency check inside the transaction
        rec.update(status="applied", applied_at=now.isoformat(), pending=None)
        conn.execute("UPDATE settings SET value_json=? WHERE key=?", (canonical_json(rec), key))
        _audit(conn, now, "import.apply", pid, f"batch={batch_id} rows={len(pending)}")
    # Reaching this line means COMMIT succeeded; only now is the import reported as applied.
    log.info("import applied batch=%s rows=%d", batch_id, len(pending))
    return {
        "batch_id": batch_id,
        "status": "applied",
        "applied": True,
        "portfolio_id": pid,
        "transactions_created": len(pending),
        "rows_rejected": rec["rows_rejected"],
        "applied_at": now.isoformat(),
    }


# ----------------------------------------------------------------------------- valuation


@dataclass(frozen=True)
class NavPoint:
    obs_id: int
    value: Decimal
    observation_date: str
    source_id: str
    source_url: str
    retrieved_at: str
    quality_status: str

    def source(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "url": self.source_url,
            "retrieved_at": self.retrieved_at,
            "observation_date": self.observation_date,
            "quality_status": self.quality_status,
            "obs_id": self.obs_id,
            "evidence": f"/api/evidence/{self.obs_id}",
        }


def latest_nav(conn: sqlite3.Connection, amfi_code: str, now: datetime) -> tuple[NavPoint | None, str, str | None]:
    """→ (latest point, freshness badge, exclusion reason or None). Never falls back to an older NAV."""
    row = conn.execute(
        "SELECT * FROM observations WHERE series_id=? AND superseded_by IS NULL AND quality_status != 'rejected'"
        " ORDER BY observation_date DESC, obs_id DESC LIMIT 1",
        (f"nav:{amfi_code}",),
    ).fetchone()
    if row is None:
        return None, "UNKNOWN", "NO_NAV_STORED"
    point = NavPoint(
        int(row["obs_id"]), Decimal(row["value"]), row["observation_date"], row["source_id"], row["source_url"],
        row["retrieved_at"], row["quality_status"],
    )  # fmt: skip
    badge, observed = ingestion.latest_freshness(conn, int(amfi_code), now)
    if observed != point.observation_date:
        badge = "STALE"
    if point.quality_status not in USABLE_QUALITY:
        return point, "STALE", f"LATEST_NAV_QUALITY_{point.quality_status.upper()}"
    if badge in {"STALE", "UNKNOWN"}:
        return point, "STALE", "STALE_NAV"
    return point, badge, None


@dataclass(frozen=True)
class Holding:
    instrument_id: str
    name: str
    kind: str
    category: str
    position: Position
    invested: Decimal  # paise
    nav: NavPoint | None
    badge: str
    market_value: Decimal | None  # paise; None = excluded
    exclusion: str | None
    maturity: date | None  # bonds (instrument level)
    tenure_days: int | None  # FDs (per lot)
    institution: str | None
    dicgc_eligible: bool | None


_EXCLUSION_TEXT = {
    "NO_NAV_STORED": "no NAV is stored for this scheme; run the AMFI NAV ingestion",
    "STALE_NAV": "the latest NAV is STALE; excluded from totals until fresh data is stored (older NAVs are never used)",
    "NOT_VALUED": "no market price source for this instrument type in v1; shown at cost and excluded from market value",
    "NO_AMFI_CODE": "mutual fund without an AMFI code; cannot be valued",
}


def _exclusion_text(reason: str) -> str:
    if reason.startswith("LATEST_NAV_QUALITY_"):
        return f"the latest NAV is marked {reason.removeprefix('LATEST_NAV_QUALITY_').lower()}; excluded from totals"
    return _EXCLUSION_TEXT.get(reason, reason)


def _holding(conn: sqlite3.Connection, pos: Position, now: datetime) -> Holding:
    inst = conn.execute(
        "SELECT i.instrument_id, i.kind, i.name, i.amfi_code, m.category_raw, m.sebi_category, b.maturity_date,"
        " d.tenure_days, d.institution, d.dicgc_eligible FROM instruments i"
        " LEFT JOIN mf_schemes m USING(instrument_id) LEFT JOIN bond_terms b USING(instrument_id)"
        " LEFT JOIN deposit_terms d USING(instrument_id) WHERE i.instrument_id=?",
        (pos.instrument_id,),
    ).fetchone()
    kind = inst["kind"]
    category = (inst["sebi_category"] or inst["category_raw"] or kind) if kind == "mf_scheme" else kind
    invested = money(pos.cost)
    nav: NavPoint | None = None
    badge = "NOT_VALUED"
    mv: Decimal | None = None
    reason: str | None
    if kind == "mf_scheme" and inst["amfi_code"]:
        nav, badge, reason = latest_nav(conn, inst["amfi_code"], now)
        if reason is None and nav is not None:
            with engine_context():
                mv = money(pos.units * nav.value)
    elif kind == "mf_scheme":
        reason = "NO_AMFI_CODE"
    else:
        reason = "NOT_VALUED"
    return Holding(
        pos.instrument_id, inst["name"], kind, category, pos, invested, nav, badge, mv, reason,
        date.fromisoformat(inst["maturity_date"]) if inst["maturity_date"] else None,
        inst["tenure_days"], inst["institution"],
        None if inst["dicgc_eligible"] is None else bool(inst["dicgc_eligible"]),
    )  # fmt: skip


def _largest_remainder_pct(values: dict[str, Decimal], total: Decimal) -> dict[str, str]:
    """Display percentages (2 dp) that sum to exactly 100.00 % (largest-remainder on basis points)."""
    if total == 0:
        return dict.fromkeys(values, "0.00%")
    with engine_context():
        raw = {k: v * Decimal(10000) / total for k, v in values.items()}
        floors = {k: int(r.to_integral_value(rounding=ROUND_DOWN)) for k, r in raw.items()}
        short = 10000 - sum(floors.values())
        order = sorted(raw, key=lambda k: (-(raw[k] - floors[k]), k))
        for k in order[:short]:
            floors[k] += 1
    return {k: f"{Decimal(bp) / Decimal(100):.2f}%" for k, bp in floors.items()}


def _bucket(days: int | None) -> str:
    if days is None:
        return "unknown"
    if days < 0:
        return "matured or overdue"
    for name, lo, hi in LADDER_BUCKETS:
        if days >= lo and (hi is None or days <= hi):
            return name
    return "unknown"  # pragma: no cover - buckets cover every non-negative day count


def _reconcile(parts: Decimal, total: Decimal, what: str) -> None:
    if parts != total:  # a bug, never a data condition: refuse to show numbers that do not add up
        raise PortfolioError("RECONCILIATION_FAILED", f"{what} does not sum to the total", 500)


def _split_by_lots(total: Decimal, lots: Sequence[Lot], weights: Sequence[Decimal]) -> list[Decimal]:
    """Split a paise total across lots in proportion to ``weights``; the last lot absorbs rounding so the parts
    sum exactly to ``total``."""
    with engine_context():
        wsum = sum(weights, ZERO)
        parts = [money(total * w / wsum) for w in weights[:-1]] if wsum else [ZERO for _ in weights[:-1]]
        parts.append(total - sum(parts, ZERO))
    return parts


def _lot_days(h: Holding, lot: Lot, as_of: date) -> int | None:
    if h.kind == "mf_scheme":
        settle = 1 if mf_tier_from_category(h.category) is Tier.T3 else 3
        lock = mf_lock_in_days(h.category)
        unlock_wait = max(0, (lot.acquired + timedelta(days=lock) - as_of).days) if lock else 0
        return unlock_wait + settle
    if h.kind == "fd" and h.tenure_days is not None:
        return (lot.acquired + timedelta(days=int(h.tenure_days)) - as_of).days
    if h.maturity is not None:
        return (h.maturity - as_of).days
    return None


def _ladder(holdings: Sequence[Holding], as_of: date, total_mv: Decimal) -> dict[str, Any]:
    names = [b[0] for b in LADDER_BUCKETS] + list(LADDER_SPECIAL)
    mv = dict.fromkeys(names, ZERO)
    at_cost = dict.fromkeys(names, ZERO)
    with engine_context():
        for h in holdings:
            lots = h.position.lots
            target = mv if h.market_value is not None else at_cost
            amount = h.market_value if h.market_value is not None else h.invested
            weights = [lot.units for lot in lots] if h.market_value is not None else [lot.cost for lot in lots]
            for lot, part in zip(lots, _split_by_lots(amount, lots, weights), strict=True):
                target[_bucket(_lot_days(h, lot, as_of))] += part
        _reconcile(sum(mv.values(), ZERO), total_mv, "liquidity ladder")
    displays = _largest_remainder_pct(mv, total_mv)
    return {
        "buckets": [
            {"bucket": n, "market_value": _s(mv[n]), "display": format_inr(mv[n]), "share": displays[n],
             "at_cost_not_valued": _s(at_cost[n]), "at_cost_display": format_inr(at_cost[n])}
            for n in names
        ],
        "explain": _explained(
            eid="liquidity_ladder", label="Liquidity ladder", value=total_mv, unit="INR", display=format_inr(total_mv),
            what="Market value grouped by calendar days until cash could be in your account.",
            formula_id="LIQUIDITY_LADDER@1",
            formula="days = lock-in remaining + settlement (MF: T+1 liquid/overnight/money-market, T+3 otherwise);"
            " FD: purchase date + tenure − today; bonds: maturity − today",
            substituted=" + ".join(format_inr(mv[n]) for n in names) + f" = {format_inr(total_mv)}",
            inputs=[f"as of {as_of.isoformat()}", "lots from your transactions (FIFO)"],
            sources=[{"source_id": "user.transactions"}], observed=as_of.isoformat(), freshness="DERIVED",
            assumptions=["Exit loads, penalties and market prices on early sale are not deducted",
                         "Lock-ins are inferred from the scheme category (ELSS 3 years; solution-oriented 5 years)"],
            limitations=["Holdings without a fresh market value appear only in the at-cost column"],
        ),
    }  # fmt: skip


def _allocation(holdings: Sequence[Holding], key: str, total: Decimal) -> dict[str, Any]:
    values: dict[str, Decimal] = {}
    with engine_context():
        for h in holdings:
            if h.market_value is not None:
                k = getattr(h, key)
                values[k] = values.get(k, ZERO) + h.market_value
        sum_values = sum(values.values(), ZERO)
    _reconcile(sum_values, total, f"allocation by {key}")
    shares = _largest_remainder_pct(values, total)
    with engine_context():
        items = [
            {"key": k, "market_value": _s(v), "display": format_inr(v),
             "weight": _s((v / total).quantize(Decimal("0.000001"))) if total else "0", "share": shares[k]}
            for k, v in sorted(values.items(), key=lambda kv: (-kv[1], kv[0]))
        ]  # fmt: skip
    return {"by": key, "items": items, "total": _s(total), "sum_of_items": _s(sum_values)}


def _positions_for(conn: sqlite3.Connection, portfolio_id: str) -> dict[str, Position]:
    try:
        return fifo_positions(load_txns(conn, portfolio_id))
    except Oversell as exc:  # cannot happen through the API; a hand-edited DB must not produce numbers
        raise PortfolioError("INCONSISTENT_BOOK", f"stored transactions are inconsistent: {exc.message}", 409) from exc


def _dicgc(conn: sqlite3.Connection, portfolio: sqlite3.Row, as_of: date) -> dict[str, Any]:
    if portfolio["nature"] == "actual":
        pids = [r["portfolio_id"] for r in conn.execute("SELECT portfolio_id FROM portfolios WHERE nature='actual'")]
        scope = "all actual portfolios (DICGC cover is per depositor per bank)"
    else:
        pids = [portfolio["portfolio_id"]]
        scope = "this hypothetical portfolio only"
    holdings: list[dep.DepositHolding] = []
    for pid in pids:
        for pos in _positions_for(conn, pid).values():
            if pos.units <= 0:
                continue
            t = conn.execute(
                "SELECT d.institution, d.dicgc_eligible FROM deposit_terms d JOIN instruments i USING(instrument_id)"
                " WHERE i.instrument_id=? AND i.kind='fd'",
                (pos.instrument_id,),
            ).fetchone()
            if t is None:
                continue
            itype = dep.InstitutionType.BANK if t["dicgc_eligible"] else dep.InstitutionType.NBFC
            holdings.append(dep.DepositHolding(t["institution"], itype, "self", money(pos.cost), ZERO))
    if not holdings:
        return {"scope": scope, "banks": [], "note": "no fixed deposits held"}
    res = dep.dicgc_coverage(holdings, as_of=as_of)
    return {
        "scope": scope,
        "banks": [
            {"institution": g.institution_id, "principal_at_cost": _s(g.principal), "insured": _s(g.insured),
             "uninsured": _s(g.uninsured), "display_uninsured": format_inr(g.uninsured), "flags": list(g.flags)}
            for g in res.groups
        ],
        "explain": _explained(
            eid="dicgc_exposure", label="Deposit-insurance exposure", value=res.uninsured, unit="INR",
            display=format_inr(res.uninsured),
            what="Deposit principal above the DICGC cover per bank (or at institutions DICGC does not insure).",
            formula_id=res.formula_id, formula="uninsured = Σ_bank max(0, principal + interest − limit)",
            substituted=f"total {format_inr(res.total)} − insured {format_inr(res.insured)} = "
            f"{format_inr(res.uninsured)}",
            inputs=[f"limit {format_inr(res.limit)} per bank", f"scope: {scope}"],
            sources=[{"source_id": "user.transactions"}, {"source_id": "deposit_terms (your cited entries)"}],
            observed=as_of.isoformat(), freshness="DERIVED", assumptions=list(res.conventions),
            limitations=["ACCRUED_INTEREST_NOT_INCLUDED: principal at cost only; accrued interest would raise "
                         "exposure", *res.warnings, "Deposits held outside this app are not included"],
        ),
    }  # fmt: skip


def _maturities(holdings: Sequence[Holding], as_of: date, within_days: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for h in holdings:
        if h.kind == "fd" and h.tenure_days is not None:
            dates = [(lot.acquired + timedelta(days=int(h.tenure_days)), money(lot.cost)) for lot in h.position.lots]
        elif h.maturity is not None:
            dates = [(h.maturity, h.invested)]
        else:
            continue
        for d, cost in dates:
            days = (d - as_of).days
            if days <= within_days:
                out.append({
                    "instrument_id": h.instrument_id, "name": h.name, "kind": h.kind, "maturity_date": d.isoformat(),
                    "days_until": days, "invested_at_cost": _s(cost), "display": format_inr(cost),
                    "flags": ["MATURED_NOT_RECORDED"] if days < 0 else [],
                    "source": "bond_terms" if h.kind != "fd" else "deposit_terms tenure + your purchase date",
                })  # fmt: skip
    return sorted(out, key=lambda m: (m["maturity_date"], m["instrument_id"]))


def _sensitivity(value: Decimal) -> list[dict[str, str]]:
    with engine_context():
        return [
            {"label": "If every NAV were 5% lower", "display": format_inr(money(value * (ONE - SENSITIVITY_SHOCK)))},
            {"label": "If every NAV were 5% higher", "display": format_inr(money(value * (ONE + SENSITIVITY_SHOCK)))},
        ]


def _xirr_block(
    txns: Sequence[Txn], included_ids: set[str], excluded_ids: set[str], total_mv: Decimal, as_of: date
) -> dict[str, Any]:
    flows = [
        CashFlow(t.txn_date, -t.amount if t.txn_type == "buy" else t.amount)
        for t in txns
        if t.instrument_id not in excluded_ids
    ]
    if total_mv > 0:
        flows.append(CashFlow(as_of, total_mv))
    scope = f"{len(included_ids)} valued holding(s) plus closed positions; {len(excluded_ids)} excluded"
    base: dict[str, Any] = {"scope": scope, "headline_allowed": False, "annualised_detail": None}
    try:
        res = xirr(flows)
    except EngineError as exc:
        base["explain"] = _unavailable("xirr", "XIRR", f"{type(exc).__name__}: not enough cash flows")
        return base
    limitations = [f"Excluded from XIRR: {len(excluded_ids)} holding(s) without a fresh market value"]
    if res.outcome is not XirrOutcome.SOLVED or res.rate is None:
        base["explain"] = _unavailable("xirr", "XIRR", res.reason or res.outcome.value)
        return base
    inputs = [f"{f.on.isoformat()}: {format_inr(f.amount)}" for f in res.flows]
    if not res.headline_allowed:
        base["annualised_detail"] = {"value": _s(res.stored_rate), "display": pct(res.rate),
                                     "warning": "ANNUALISED_FROM_SHORT_PERIOD — not a headline figure"}  # fmt: skip
        base["explain"] = _explained(
            eid="xirr", label="XIRR", value=None, unit="fraction/year",
            display=f"Not annualised: {res.span_days} days of cash flows (under 365)",
            what="Money-weighted annual return. Under 365 days it is not shown as a headline (Rule A1); see the "
            "unrealised P/L in rupees instead.",
            formula_id=res.formula_id, formula="Σ CF_i / (1 + r)^((d_i − d_0)/365) = 0",
            substituted=f"span {res.span_days} days < 365", inputs=inputs, sources=[{"source_id": "user.transactions"}],
            observed=as_of.isoformat(), freshness="DERIVED", limitations=[*limitations, *res.warnings],
        )  # fmt: skip
        return base
    base["headline_allowed"] = True
    base["explain"] = _explained(
        eid="xirr", label="XIRR", value=res.stored_rate, unit="fraction/year", display=pct(res.rate),
        what="Money-weighted annual return on your cash flows, with today's market value as the final inflow.",
        formula_id=res.formula_id, formula="Σ CF_i / (1 + r)^((d_i − d_0)/365) = 0",
        substituted=f"r = {pct(res.rate)} over {res.span_days} days; XNPV residual {_s(res.xnpv_at_rate)}",
        inputs=inputs, sources=[{"source_id": "user.transactions"}], observed=as_of.isoformat(), freshness="DERIVED",
        assumptions=["Final inflow dated today at the latest NAV of each valued holding"], limitations=limitations,
    )  # fmt: skip
    return base


def _unavailable(eid: str, label: str, reason: str) -> dict[str, Any]:
    return _explained(
        eid=eid, label=label, value=None, unit="", display="Not available", what=reason, formula_id="",
        formula="", substituted="", inputs=[], sources=[], observed=None, freshness="UNAVAILABLE",
        limitations=[reason],
    )  # fmt: skip


def portfolio_summary(
    conn: sqlite3.Connection, portfolio_id: str, now: datetime, *, maturity_days: int = 365
) -> dict[str, Any]:
    p = _portfolio(conn, portfolio_id)
    as_of = now.date()
    txns = load_txns(conn, portfolio_id)
    positions = _positions_for(conn, portfolio_id)
    holdings = [_holding(conn, pos, now) for pos in positions.values() if pos.units > 0]
    included = [h for h in holdings if h.market_value is not None]
    excluded = [h for h in holdings if h.market_value is None]
    with engine_context():
        total_mv = sum((h.market_value for h in included if h.market_value is not None), ZERO)
        invested_included = sum((h.invested for h in included), ZERO)
        invested_all = sum((h.invested for h in holdings), ZERO)
        unrealised = total_mv - invested_included
        realised = sum((money(pos.realised_proceeds - pos.realised_cost) for pos in positions.values()), ZERO)
    nav_sources = [h.nav.source() for h in included if h.nav is not None]
    nav_dates = sorted(h.nav.observation_date for h in included if h.nav is not None)
    observed = f"{nav_dates[0]} → {nav_dates[-1]}" if nav_dates else None
    fixture = any(h.badge == "FIXTURE" for h in included)
    freshness = "FIXTURE" if fixture else ("END_OF_DAY" if included else "UNAVAILABLE")
    notes = [f"{h.name}: {h.badge} — {_exclusion_text(h.exclusion)}" for h in excluded if h.exclusion is not None]
    excl_limit = [f"{len(excluded)} holding(s) excluded from totals (see notes)"] if excluded else []

    holding_rows: list[dict[str, Any]] = []
    for h in holdings:
        row: dict[str, Any] = {
            "instrument_id": h.instrument_id, "name": h.name, "kind": h.kind, "category": h.category,
            "units": _s(h.position.units), "lots": len(h.position.lots), "badge": h.badge,
            "included_in_totals": h.market_value is not None,
            "exclusion": None if h.exclusion is None else {"code": h.exclusion, "text": _exclusion_text(h.exclusion)},
            "nav": None if h.nav is None else {**h.nav.source(), "value": _s(h.nav.value)},
            "invested": _explained(
                eid=f"{h.instrument_id}.invested", label="Invested (remaining cost, FIFO)", value=h.invested,
                unit="INR", display=format_inr(h.invested), what="Cost of the units still held, by FIFO lots.",
                formula_id="FIFO_COST@1", formula="Σ remaining lot cost", substituted=format_inr(h.invested),
                inputs=[f"{len(h.position.lots)} open lot(s)"], sources=[{"source_id": "user.transactions"}],
                observed=as_of.isoformat(), freshness="USER_INPUT",
            ),
            "market_value": None, "unrealised_pl": None,
        }  # fmt: skip
        if h.market_value is not None and h.nav is not None:
            row["market_value"] = _explained(
                eid=f"{h.instrument_id}.market_value", label="Market value", value=h.market_value, unit="INR",
                display=format_inr(h.market_value), what="Units held × latest NAV.", formula_id="MV@1",
                formula="units × NAV", substituted=f"{_s(h.position.units)} × ₹{_s(h.nav.value)} = "
                f"{format_inr(h.market_value)}", inputs=[f"NAV dated {h.nav.observation_date}"],
                sources=[h.nav.source()], observed=h.nav.observation_date, freshness=h.badge,
                sensitivity=_sensitivity(h.market_value),
            )  # fmt: skip
            with engine_context():
                pl = h.market_value - h.invested
            row["unrealised_pl"] = _explained(
                eid=f"{h.instrument_id}.unrealised_pl", label="Unrealised P/L", value=pl, unit="INR",
                display=format_inr(pl), what="Market value minus FIFO cost of units held, before tax and exit load.",
                formula_id="UPL@1", formula="market value − invested",
                substituted=f"{format_inr(h.market_value)} − {format_inr(h.invested)} = {format_inr(pl)}",
                inputs=[f"NAV dated {h.nav.observation_date}"],
                sources=[h.nav.source(), {"source_id": "user.transactions"}],
                observed=h.nav.observation_date, freshness=h.badge, limitations=["Tax and exit load not deducted"],
            )  # fmt: skip
        holding_rows.append(row)

    concentration: dict[str, Any]
    if included and total_mv > 0:
        res = hhi_from_values(
            {h.instrument_id: h.market_value for h in included if h.market_value is not None},
            snapshot_date=as_of, as_of=as_of,
        )  # fmt: skip
        concentration = {
            "band": res.band, "effective_count": _s(res.effective_count.quantize(Decimal("0.01"))),
            "explain": _explained(
                eid="hhi", label="Concentration (HHI)", value=res.value.quantize(Decimal("0.000001")), unit="index",
                display=f"{res.value.quantize(Decimal('0.0001'))} ({res.band})",
                what="Herfindahl–Hirschman index of market-value weights across valued holdings (1 = one holding).",
                formula_id=res.method_id, formula="HHI = Σ w_i², w_i = MV_i / ΣMV",
                substituted=" + ".join(f"{_s(w.quantize(Decimal('0.0001')))}²" for _, w in res.weights)
                + f" = {_s(res.value.quantize(Decimal('0.0001')))}",
                inputs=[f"{res.observations} valued holding(s)"], sources=nav_sources, observed=observed,
                freshness=freshness, assumptions=["Scheme level: issuer overlap inside funds is not looked through"],
                limitations=[*res.caveats, *excl_limit],
            ),
        }  # fmt: skip
    else:
        concentration = {
            "band": None,
            "effective_count": None,
            "explain": _unavailable("hhi", "Concentration (HHI)", "no holding with a fresh value"),
        }

    summary = {
        "portfolio": {"portfolio_id": p["portfolio_id"], "name": p["name"], "nature": p["nature"]},
        "label": "HYPOTHETICAL — not your actual holdings" if p["nature"] == "hypothetical" else "ACTUAL holdings",
        "as_of": as_of.isoformat(),
        "flags": (["CONTAINS_FIXTURE_DATA"] if fixture else []) + (["HOLDINGS_EXCLUDED"] if excluded else []),
        "notes": notes,
        "holdings": holding_rows,
        "totals": {
            "market_value": _explained(
                eid="total.market_value", label="Market value (valued holdings)", value=total_mv, unit="INR",
                display=format_inr(total_mv), what="Sum of each valued holding's market value (units × latest NAV).",
                formula_id="MV_TOTAL@1", formula="Σ round_paise(units_i × NAV_i)",
                substituted=" + ".join(format_inr(h.market_value) for h in included if h.market_value is not None)
                + f" = {format_inr(total_mv)}",
                inputs=[f"{len(included)} valued holding(s)"], sources=nav_sources, observed=observed,
                freshness=freshness, sensitivity=_sensitivity(total_mv), limitations=excl_limit,
            ),
            "invested": _explained(
                eid="total.invested", label="Invested (valued holdings)", value=invested_included, unit="INR",
                display=format_inr(invested_included), what="FIFO cost of the units still held, valued holdings only.",
                formula_id="FIFO_COST@1", formula="Σ remaining lot cost",
                substituted=f"{format_inr(invested_included)} (all holdings at cost: {format_inr(invested_all)})",
                inputs=[f"{len(txns)} transaction(s)"], sources=[{"source_id": "user.transactions"}],
                observed=as_of.isoformat(), freshness="USER_INPUT", limitations=excl_limit,
            ),
            "invested_all_holdings": _s(invested_all),
            "unrealised_pl": _explained(
                eid="total.unrealised_pl", label="Unrealised P/L (valued holdings)", value=unrealised, unit="INR",
                display=format_inr(unrealised), what="Market value minus FIFO cost, before tax and exit loads.",
                formula_id="UPL@1", formula="Σ MV − Σ invested (same holdings)",
                substituted=f"{format_inr(total_mv)} − {format_inr(invested_included)} = {format_inr(unrealised)}",
                inputs=[f"{len(included)} valued holding(s)"],
                sources=[*nav_sources, {"source_id": "user.transactions"}],
                observed=observed, freshness=freshness, sensitivity=_sensitivity(unrealised) if unrealised else [],
                limitations=["Tax and exit load not deducted", *excl_limit],
            ),
            "realised_pl": _s(realised),
        },
        "xirr": _xirr_block(txns, {h.instrument_id for h in included}, {h.instrument_id for h in excluded},
                            total_mv, as_of),
        "allocation": {
            "by_kind": _allocation(included, "kind", total_mv),
            "by_category": _allocation(included, "category", total_mv),
        },
        "concentration": concentration,
        "liquidity_ladder": _ladder(holdings, as_of, total_mv),
        "upcoming_maturities": {"within_days": maturity_days, "items": _maturities(holdings, as_of, maturity_days)},
        "dicgc": _dicgc(conn, p, as_of),
        "engine_version": SERVICE_VERSION,
    }  # fmt: skip
    log.info("summary computed portfolio=%s holdings=%d excluded=%d", portfolio_id, len(holdings), len(excluded))
    return summary


# ----------------------------------------------------------------------------- watchlist


def _series_for(inst: sqlite3.Row) -> tuple[str | None, str]:
    if inst["kind"] == "mf_scheme" and inst["amfi_code"]:
        return f"nav:{inst['amfi_code']}", "nav"
    if inst["kind"] in {"tbill", "gsec", "sdl", "corp_bond"}:
        return f"yield:{inst['instrument_id']}", "yield"
    return None, "none"


def _obs_dict(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "obs_id": r["obs_id"], "value": r["value"], "unit": r["unit"], "observation_date": r["observation_date"],
        "source_id": r["source_id"], "url": r["source_url"], "retrieved_at": r["retrieved_at"],
        "quality_status": r["quality_status"], "evidence": f"/api/evidence/{r['obs_id']}",
    }  # fmt: skip


def watch_change(conn: sqlite3.Connection, inst: sqlite3.Row, added_at: str, now: datetime) -> dict[str, Any]:
    """Change since added, from stored observations only: base = last usable observation on/before the date added,
    latest = latest stored observation (must be usable and, for NAVs, not STALE)."""
    series, kind = _series_for(inst)
    out: dict[str, Any] = {"series_id": series, "base": None, "latest": None, "change": None,
                           "absolute_return": None, "badge": "UNKNOWN", "reason": None}  # fmt: skip
    if series is None:
        out["reason"] = "NO_SERIES: no stored price series for this instrument type"
        return out
    added = datetime.fromisoformat(added_at).date()
    ok = ",".join("?" for _ in USABLE_QUALITY)
    base = conn.execute(
        f"SELECT * FROM observations WHERE series_id=? AND superseded_by IS NULL AND quality_status IN ({ok})"  # noqa: S608
        " AND observation_date <= ? ORDER BY observation_date DESC, obs_id DESC LIMIT 1",
        (series, *USABLE_QUALITY, added.isoformat()),
    ).fetchone()
    latest = conn.execute(
        "SELECT * FROM observations WHERE series_id=? AND superseded_by IS NULL AND quality_status != 'rejected'"
        " ORDER BY observation_date DESC, obs_id DESC LIMIT 1",
        (series,),
    ).fetchone()
    out["base"] = _obs_dict(base) if base else None
    out["latest"] = _obs_dict(latest) if latest else None
    if kind == "nav":
        _, badge, reason = latest_nav(conn, inst["amfi_code"], now)
        out["badge"] = badge
        if reason is not None:
            out["reason"] = reason
            return out
    elif latest is not None:
        age = (now.date() - date.fromisoformat(latest["observation_date"])).days
        out["badge"] = "STALE" if age > TBILL_STALE_DAYS else ("FIXTURE" if latest["quality_status"] == "fixture"
                                                              else "MANUAL")  # fmt: skip
        if out["badge"] == "STALE" or latest["quality_status"] not in USABLE_QUALITY:
            out["reason"] = "STALE_DATA"
            return out
    if base is None or latest is None:
        out["reason"] = "NO_OBSERVATION_ON_OR_BEFORE_DATE_ADDED"
        return out
    v0, v1 = Decimal(base["value"]), Decimal(latest["value"])
    with engine_context():
        out["change"] = {"value": _s(v1 - v0), "unit": latest["unit"],
                         "from": {"date": base["observation_date"], "value": base["value"]},
                         "to": {"date": latest["observation_date"], "value": latest["value"]}}  # fmt: skip
        if kind == "nav" and v0 > 0:
            r = v1 / v0 - ONE
            out["absolute_return"] = {"value": _s(r), "display": pct(r), "formula_id": "ABS_RETURN@1",
                                      "note": "absolute (not annualised)"}  # fmt: skip
    return out


def watchlist(conn: sqlite3.Connection, now: datetime) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT w.instrument_id, w.note, w.added_at, i.* FROM watchlist w JOIN instruments i USING(instrument_id)"
        " ORDER BY w.added_at, w.instrument_id"
    ).fetchall()
    return [
        {"instrument_id": r["instrument_id"], "name": r["name"], "kind": r["kind"], "note": r["note"],
         "added_at": r["added_at"], **watch_change(conn, r, r["added_at"], now)}
        for r in rows
    ]  # fmt: skip


def watch_add(conn: sqlite3.Connection, body: WatchIn, now: datetime) -> dict[str, Any]:
    _instrument(conn, body.instrument_id)
    note = imports.normalise_text(body.note) or None
    with write_tx(conn):
        if conn.execute("SELECT 1 FROM watchlist WHERE instrument_id=?", (body.instrument_id,)).fetchone():
            raise PortfolioError("ALREADY_WATCHED", "instrument is already on the watchlist", 409)
        conn.execute(
            "INSERT INTO watchlist(instrument_id, note, added_at) VALUES (?, ?, ?)",
            (body.instrument_id, note, now.isoformat()),
        )
        _audit(conn, now, "watchlist.add", body.instrument_id, None)
    return {"instrument_id": body.instrument_id, "added_at": now.isoformat(), "status": "watching"}


def watch_delete(conn: sqlite3.Connection, instrument_id: str, now: datetime) -> dict[str, Any]:
    with write_tx(conn):
        cur = conn.execute("DELETE FROM watchlist WHERE instrument_id=?", (instrument_id,))
        if cur.rowcount == 0:
            raise PortfolioError("NOT_FOUND", "instrument is not on the watchlist", 404)
        _audit(conn, now, "watchlist.delete", instrument_id, None)
    return {"status": "deleted"}


# ----------------------------------------------------------------------------- evidence


_CHAIN_LIMIT = 1000


def evidence(conn: sqlite3.Connection, obs_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM observations WHERE obs_id=?", (obs_id,)).fetchone()
    if row is None:
        raise PortfolioError("NOT_FOUND", "observation not found", 404)

    def brief(r: sqlite3.Row) -> dict[str, Any]:
        return {"obs_id": r["obs_id"], "value": r["value"], "observation_date": r["observation_date"],
                "retrieved_at": r["retrieved_at"], "quality_status": r["quality_status"],
                "sha256": r["raw_sha256"], "superseded_by": r["superseded_by"]}  # fmt: skip

    newer: list[dict[str, Any]] = []
    seen = {obs_id}
    nxt = row["superseded_by"]
    while nxt is not None and nxt not in seen and len(newer) < _CHAIN_LIMIT:
        seen.add(nxt)
        r = conn.execute("SELECT * FROM observations WHERE obs_id=?", (nxt,)).fetchone()
        if r is None:
            break
        newer.append(brief(r))
        nxt = r["superseded_by"]
    older: list[dict[str, Any]] = []
    cur = obs_id
    while len(older) < _CHAIN_LIMIT:
        r = conn.execute(
            "SELECT * FROM observations WHERE superseded_by=? AND obs_id != ? ORDER BY obs_id DESC LIMIT 1",
            (cur, cur),
        ).fetchone()
        if r is None or r["obs_id"] in seen:
            break
        seen.add(r["obs_id"])
        older.append(brief(r))
        cur = r["obs_id"]
    src = conn.execute("SELECT * FROM sources WHERE source_id=?", (row["source_id"],)).fetchone()
    run = None
    if row["ingestion_run_id"]:
        r = conn.execute("SELECT * FROM ingestion_runs WHERE run_id=?", (row["ingestion_run_id"],)).fetchone()
        run = dict(r) if r else None
    return {
        "observation": {
            "obs_id": row["obs_id"], "series_id": row["series_id"], "kind": row["kind"], "value": row["value"],
            "unit": row["unit"], "currency": row["currency"], "source_id": row["source_id"], "url": row["source_url"],
            "retrieved_at": row["retrieved_at"], "observation_date": row["observation_date"],
            "publication_time": row["publication_time"], "sha256": row["raw_sha256"],
            "quality": row["quality_status"], "convention": row["convention"],
            "ingestion_run_id": row["ingestion_run_id"], "superseded_by": row["superseded_by"],
        },
        "is_current": row["superseded_by"] is None,
        "fixture": row["quality_status"] == "fixture",
        "superseded_chain": {"newer": newer, "older": older},
        "source": dict(src) if src else None,
        "ingestion_run": run,
    }  # fmt: skip


# ----------------------------------------------------------------------------- privacy & backup


def backups_dir(data_dir: Path) -> Path:
    return data_dir / "backups"


def _backup_files(data_dir: Path) -> list[Path]:
    d = backups_dir(data_dir)
    # Both naming schemes: the API writes iip-*.sqlite3, `make backup` writes iip-*.db. Erase must find every copy.
    return sorted([*d.glob("iip-*.sqlite3"), *d.glob("iip-*.db")]) if d.exists() else []


assert all(t.isidentifier() for t in PUBLIC_TABLES)
# Precomputed from identifier-checked constants: no SQL is ever built from runtime values (SEC-65).
_COUNT_SQL = {t: "SELECT COUNT(*) FROM " + t for t in (*USER_TABLES, *PUBLIC_TABLES)}  # noqa: S608 - identifier-asserted constants
_DELETE_SQL = {t: "DELETE FROM " + t for t in USER_TABLES}  # noqa: S608 - identifier-asserted constants


def inventory(conn: sqlite3.Connection, data_dir: Path) -> dict[str, Any]:
    user = {t: int(conn.execute(_COUNT_SQL[t]).fetchone()[0]) for t in USER_TABLES}
    public = {t: int(conn.execute(_COUNT_SQL[t]).fetchone()[0]) for t in PUBLIC_TABLES}
    pending = len([b for b in _batches(conn) if b["status"] == "previewed"])
    return {
        "user_data": {"tables": user, "pending_import_previews": pending},
        "public_market_data_kept_on_erase": {"tables": public},
        "backups": {"count": len(_backup_files(data_dir)), "note": "backups may contain user data"},
        "note": "Counts only; no amounts or names.",
    }


def export_all(conn: sqlite3.Connection, now: datetime) -> dict[str, Any]:
    prof = conn.execute("SELECT data_json, updated_at FROM profiles").fetchall()

    def rows(sql: str) -> list[dict[str, Any]]:
        return [dict(r) for r in conn.execute(sql)]

    sections: dict[str, Any] = {
        "profile": [{"data": json.loads(r["data_json"]), "updated_at": r["updated_at"]} for r in prof],
        "portfolios": rows("SELECT * FROM portfolios ORDER BY created_at, portfolio_id"),
        "transactions": rows("SELECT * FROM transactions ORDER BY portfolio_id, txn_date, created_at, txn_id"),
        "watchlist": rows("SELECT * FROM watchlist ORDER BY added_at, instrument_id"),
        "alerts": rows("SELECT * FROM alerts ORDER BY created_at, alert_id"),
        "runs": rows("SELECT * FROM runs ORDER BY created_at, run_id"),
        "audit_events": rows("SELECT * FROM audit_events ORDER BY event_id"),
        "settings": [
            {"key": r["key"], "value": json.loads(r["value_json"])}
            for r in conn.execute("SELECT * FROM settings ORDER BY key")
        ],
    }
    return {
        "format": "iip.privacy_export@1",
        "generated_at": now.isoformat(),
        **sections,
        "manifest": {k: sha256_hex(canonical_json(v)) for k, v in sections.items()},
    }


EXPORT_COLUMNS = ("txn_id", "portfolio_id", "portfolio_name", "nature", "instrument_id", "instrument_name",
                  "txn_date", "txn_type", "units", "amount", "source", "import_batch", "created_at")  # fmt: skip


def export_transactions_csv(conn: sqlite3.Connection) -> bytes:
    rows = conn.execute(
        "SELECT t.*, p.name AS portfolio_name, p.nature, i.name AS instrument_name FROM transactions t"
        " JOIN portfolios p USING(portfolio_id) JOIN instruments i USING(instrument_id)"
        " ORDER BY t.portfolio_id, t.txn_date, t.created_at, t.txn_id"
    ).fetchall()
    out: list[dict[str, object]] = []
    for r in rows:
        d: dict[str, object] = {c: r[c] for c in EXPORT_COLUMNS if c not in {"units", "amount", "txn_date"}}
        d["units"] = Decimal(r["units"]) if r["units"] is not None else None
        d["amount"] = Decimal(r["amount"])
        d["txn_date"] = date.fromisoformat(r["txn_date"])
        out.append(d)
    return export_holdings_csv(out, EXPORT_COLUMNS)


def erase(conn: sqlite3.Connection, data_dir: Path, *, delete_backups: bool) -> dict[str, Any]:
    """Delete every user row (SEC-81), with ``secure_delete`` on, then VACUUM and truncate the WAL so the bytes
    are gone from the database files. Public market data and the schema are kept."""
    counts = {t: int(conn.execute(_COUNT_SQL[t]).fetchone()[0]) for t in USER_TABLES}
    previous = int(conn.execute("PRAGMA secure_delete").fetchone()[0])
    conn.execute("PRAGMA secure_delete=ON")
    try:
        with write_tx(conn):
            for t in USER_TABLES:
                conn.execute(_DELETE_SQL[t])
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.execute("PRAGMA secure_delete=ON" if previous else "PRAGMA secure_delete=OFF")
    removed = 0
    if delete_backups:
        for f in _backup_files(data_dir):
            f.unlink(missing_ok=True)
            removed += 1
    log.info("user data erased tables=%d backups_removed=%d", len(counts), removed)
    return {
        "status": "erased",
        "deleted_rows": counts,
        "backups_deleted": removed,
        "backups_remaining": len(_backup_files(data_dir)),
        "kept": "public market data (instruments, observations, sources, ingestion runs) and the schema",
    }


def make_backup(conn: sqlite3.Connection, data_dir: Path, now: datetime, *, tag: str = "") -> dict[str, Any]:
    d = backups_dir(data_dir)
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    stem = f"iip-{now.strftime('%Y%m%dT%H%M%SZ')}-v{current_version(conn)}{'-' + tag if tag else ''}"
    dest = d / f"{stem}.sqlite3"
    n = 2
    while dest.exists():
        dest = d / f"{stem}-{n}.sqlite3"
        n += 1
    try:
        path = db_backup(conn, dest)
    except (RuntimeError, sqlite3.Error) as exc:
        log.error("backup failed error_class=%s", type(exc).__name__)
        raise PortfolioError("BACKUP_FAILED", "backup failed its integrity check; nothing was written", 500) from exc
    os.chmod(path, 0o600)
    data = path.read_bytes()
    log.info("backup written bytes=%d", len(data))
    return {"path": str(path), "integrity": "ok", "bytes": len(data), "sha256": sha256_hex(data),
            "schema_version": current_version(conn)}  # fmt: skip
