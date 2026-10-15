"""Manually-entered instruments (ADR-0004: RBI/bank/CRA data is entered by the user with a citation).

Every manual value is stored as an observation with quality_status='manual', its citation URL and the date the
user says the value applied ("as of"). Freshness of manual values is enforced at evaluation time.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from iip.store.db import write_tx
from iip.store.observations import ObservationRow, upsert_observation

TBILL_FRESH_DAYS = 7  # registry rbi.pr.tbill: fresh ≤ 7, stale ≤ 21 calendar days
TBILL_STALE_DAYS = 21
FD_RATE_STALE_DAYS = 30  # ux-design §4.4: FD rate > 30 days → STALE
_SLUG = re.compile(r"[^a-z0-9]+")


def _no_float(v: object) -> object:
    if isinstance(v, float):
        raise ValueError("send decimals as strings, not floats")
    return v


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(pattern=r"^https://[^\s]+$", max_length=500)
    as_of: date
    note: str = Field(default="", max_length=300)


class TBillIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=3, max_length=120)
    tenor: Literal["91", "182", "364"]
    maturity: date
    yield_fraction: Decimal = Field(gt=0, lt=Decimal("0.5"))
    citation: Citation
    _f = field_validator("yield_fraction", mode="before")(_no_float)


class FDIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    institution: str = Field(min_length=2, max_length=120)
    institution_type: Literal["bank", "small_finance_bank", "nbfc", "hfc", "post_office"]
    rate: Decimal = Field(ge=0, lt=Decimal("0.3"))
    tenure_days: int = Field(ge=7, le=3650)
    premature_penalty: Decimal | None = Field(default=None, ge=0, lt=Decimal("0.1"))
    existing_deposits_at_institution: Decimal = Field(default=Decimal(0), ge=0)
    citation: Citation
    _f = field_validator("rate", "premature_penalty", "existing_deposits_at_institution", mode="before")(_no_float)


class ExitLoadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int = Field(ge=0, le=3650)
    rate: Decimal = Field(ge=0, le=Decimal("0.05"))
    citation: Citation
    _f = field_validator("rate", mode="before")(_no_float)


def _slug(text: str) -> str:
    return _SLUG.sub("-", text.lower()).strip("-")[:40]


def _sha(payload: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def add_tbill(conn: sqlite3.Connection, body: TBillIn, now: datetime) -> str:
    iid = f"tbill:{body.tenor}d:{body.maturity.isoformat()}"
    with write_tx(conn):
        conn.execute(
            "INSERT INTO issuers(issuer_id, name, issuer_type) VALUES ('goi', 'Government of India', 'sovereign')"
            " ON CONFLICT(issuer_id) DO NOTHING"
        )
        conn.execute(
            "INSERT INTO instruments(instrument_id, kind, name, issuer_id, origin, created_at)"
            " VALUES (?, 'tbill', ?, 'goi', 'manual', ?) ON CONFLICT(instrument_id) DO UPDATE SET name=excluded.name",
            (iid, body.name, now.isoformat()),
        )
        conn.execute(
            "INSERT INTO bond_terms(instrument_id, face_value, coupon_rate, coupon_freq, maturity_date, daycount,"
            " listed, credit_rating) VALUES (?, '100', '0', 0, ?, 'ACT/365F', 1, 'SOVEREIGN')"
            " ON CONFLICT(instrument_id) DO UPDATE SET maturity_date=excluded.maturity_date",
            (iid, body.maturity.isoformat()),
        )
    upsert_observation(
        conn,
        ObservationRow(
            series_id=f"yield:{iid}",
            kind="yield",
            value=format(body.yield_fraction, "f"),
            unit="fraction",
            currency=None,
            observation_date=body.citation.as_of.isoformat(),
            retrieved_at=now.isoformat(),
            source_id="rbi.pr.tbill",
            source_url=body.citation.url,
            quality_status="manual",
            raw_sha256=_sha(body.model_dump()),
            convention="money-market yield, ACT/365 (RBI)",
        ),
    )
    return iid


def add_fd(conn: sqlite3.Connection, body: FDIn, now: datetime) -> str:
    iid = f"fd:{_slug(body.institution)}:{body.tenure_days}d"
    insured = body.institution_type in {"bank", "small_finance_bank"}
    with write_tx(conn):
        conn.execute(
            "INSERT INTO instruments(instrument_id, kind, name, origin, created_at) VALUES (?, 'fd', ?, 'manual', ?)"
            " ON CONFLICT(instrument_id) DO UPDATE SET name=excluded.name",
            (iid, f"{body.institution} FD — {body.tenure_days} days", now.isoformat()),
        )
        conn.execute(
            "INSERT INTO deposit_terms(instrument_id, institution, rate, compounding, tenure_days, premature_penalty,"
            " dicgc_eligible, rate_as_of, citation_url) VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(instrument_id) DO UPDATE SET rate=excluded.rate,"
            " premature_penalty=excluded.premature_penalty, dicgc_eligible=excluded.dicgc_eligible,"
            " rate_as_of=excluded.rate_as_of, citation_url=excluded.citation_url",
            (
                iid,
                body.institution,
                format(body.rate, "f"),
                "quarterly",
                body.tenure_days,
                None if body.premature_penalty is None else format(body.premature_penalty, "f"),
                int(insured),
                body.citation.as_of.isoformat(),
                body.citation.url,
            ),
        )
        conn.execute(
            "INSERT INTO settings(key, value_json) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (f"fd.existing:{iid}", json.dumps(format(body.existing_deposits_at_institution, "f"))),
        )
    return iid


def set_exit_load(conn: sqlite3.Connection, instrument_id: str, body: ExitLoadIn) -> None:
    data = {
        "days": body.days,
        "rate": format(body.rate, "f"),
        "citation": body.citation.url,
        "as_of": body.citation.as_of.isoformat(),
    }
    cur = conn.execute(
        "UPDATE mf_schemes SET exit_load_json = ? WHERE instrument_id = ?", (json.dumps(data), instrument_id)
    )
    if cur.rowcount != 1:
        raise KeyError(instrument_id)


def delete_instrument(conn: sqlite3.Connection, instrument_id: str) -> bool:
    with write_tx(conn):
        row = conn.execute("SELECT origin FROM instruments WHERE instrument_id=?", (instrument_id,)).fetchone()
        if row is None or row["origin"] != "manual":
            return False
        conn.execute(
            "DELETE FROM observations WHERE series_id = ? AND quality_status = 'manual'", (f"yield:{instrument_id}",)
        )
        conn.execute("DELETE FROM instruments WHERE instrument_id=?", (instrument_id,))
    return True
