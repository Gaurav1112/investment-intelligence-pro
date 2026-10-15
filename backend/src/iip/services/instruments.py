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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from iip.data.validators import validate_isin
from iip.engine.ranking import CREDIT_SCALE
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


# ------------------------------------------------------------------ G-secs, SDLs, corporate bonds

BOND_QUOTE_SOURCE = "bond.quote"  # registry: user-entered price/yield with citation
RATING_SOURCE = "cra.ratings"
BOND_QUOTE_STALE_DAYS = 7  # engine/candidates.MAX_BOND_QUOTE_STALENESS_DAYS
RATING_STALE_DAYS = 365  # engine/candidates.MAX_RATING_AGE_DAYS
GSEC_SHUT_DAYS = 1  # RBI FAQ: 1-day shut period for SGL accounts (record-date position NOT VERIFIED)
CORPORATE_RATINGS = tuple(r for r in CREDIT_SCALE if r not in ("SOVEREIGN", "UNRATED"))
RATING_AGENCIES = ("CRISIL", "ICRA", "CARE", "India Ratings", "Acuite", "Brickwork", "Infomerics")
CorporateRating = Literal[
    "D", "C", "B-", "B", "B+", "BB-", "BB", "BB+", "BBB-", "BBB", "BBB+", "A-", "A", "A+", "AA-", "AA", "AA+", "AAA"
]  # fmt: skip
RatingAgency = Literal["CRISIL", "ICRA", "CARE", "India Ratings", "Acuite", "Brickwork", "Infomerics"]


def _isin(v: str) -> str:
    problem = validate_isin(v)
    if problem is not None:
        raise ValueError(f"{problem}: enter the 12-character ISIN exactly as on the official page")
    return v


class _BondQuoteFields(BaseModel):
    """Shared fields. Exactly one of clean_price (per ₹100 face) or ytm (fraction) is given; which one is recorded."""

    model_config = ConfigDict(extra="forbid")
    issuer: str = Field(min_length=2, max_length=120)
    isin: str = Field(min_length=12, max_length=12)
    coupon_rate: Decimal = Field(ge=0, lt=Decimal("0.3"))
    issue_date: date
    maturity: date
    face_value: Decimal = Field(gt=0, le=Decimal("10000000"))
    clean_price: Decimal | None = Field(default=None, gt=0, lt=Decimal("300"))
    ytm: Decimal | None = Field(default=None, gt=Decimal("-0.05"), lt=Decimal("0.5"))
    quote_date: date
    transaction_spread: Decimal | None = Field(default=None, ge=0, lt=Decimal("0.1"))
    citation: Citation
    _f = field_validator("coupon_rate", "face_value", "clean_price", "ytm", "transaction_spread", mode="before")(
        _no_float
    )
    _i = field_validator("isin")(_isin)

    @model_validator(mode="after")
    def _quote_and_dates(self) -> _BondQuoteFields:
        if (self.clean_price is None) == (self.ytm is None):
            raise ValueError("enter exactly one of clean_price or ytm")
        if self.maturity <= self.issue_date:
            raise ValueError("maturity must be after issue_date")
        if self.quote_date < self.issue_date:
            raise ValueError("quote_date must not be before issue_date")
        return self

    @property
    def quote_kind(self) -> Literal["clean_price", "ytm"]:
        return "clean_price" if self.clean_price is not None else "ytm"


class GsecIn(_BondQuoteFields):
    """Dated G-sec or SDL: semi-annual, 30E/360 (RBI FAQ). The YTM, if given, is the semi-annual bond-equivalent."""

    kind: Literal["gsec", "sdl"]
    frequency: Literal[2] = 2


class CallIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    call_date: date
    call_price: Decimal = Field(gt=0, lt=Decimal("300"))  # per ₹100 face
    _f = field_validator("call_price", mode="before")(_no_float)


class CorporateBondIn(_BondQuoteFields):
    """Listed or unlisted corporate bond/NCD (SEBI ACT/ACT). Rating, agency, rating date and citation are required."""

    frequency: Literal[1, 2, 4, 12]
    ytm_compounding: Literal["annual", "semiannual", "quarterly", "monthly"] | None = None
    rating: CorporateRating
    rating_agency: RatingAgency
    rating_date: date
    rating_citation: Citation
    listed: bool
    secured: bool
    record_date_days: int = Field(ge=0, le=30)  # shut period before each coupon, from the term sheet
    call_schedule: list[CallIn] = Field(default_factory=list, max_length=40)

    @model_validator(mode="after")
    def _corporate(self) -> CorporateBondIn:
        if self.ytm is not None and self.ytm_compounding is None:
            raise ValueError("ytm_compounding is required with a ytm (Indian corporate yield quoting varies)")
        if self.ytm is None and self.ytm_compounding is not None:
            raise ValueError("ytm_compounding applies only to a ytm quote")
        dates = [c.call_date for c in self.call_schedule]
        if len(set(dates)) != len(dates):
            raise ValueError("call dates must be distinct")
        if any(not self.issue_date < d < self.maturity for d in dates):
            raise ValueError("every call date must fall between issue_date and maturity")
        return self


def _coupon_text(rate: Decimal) -> str:
    return format((rate * 100).normalize(), "f")


def _bond_issuer(conn: sqlite3.Connection, kind: str, issuer: str) -> str:
    if kind == "gsec":
        conn.execute(
            "INSERT INTO issuers(issuer_id, name, issuer_type) VALUES ('goi', 'Government of India', 'sovereign')"
            " ON CONFLICT(issuer_id) DO NOTHING"
        )
        return "goi"
    issuer_type = "state" if kind == "sdl" else "corporate"
    iid = f"{issuer_type}:{_slug(issuer)}"
    conn.execute(
        "INSERT INTO issuers(issuer_id, name, issuer_type) VALUES (?, ?, ?)"
        " ON CONFLICT(issuer_id) DO UPDATE SET name=excluded.name",
        (iid, issuer, issuer_type),
    )
    return iid


def _store_bond(
    conn: sqlite3.Connection,
    *,
    iid: str,
    kind: str,
    name: str,
    body: _BondQuoteFields,
    daycount: str,
    frequency: int,
    listed: bool,
    calls: list[dict[str, str]] | None,
    rating: tuple[str, str, str] | None,
    meta: dict[str, object],
    convention: str,
    now: datetime,
) -> None:
    with write_tx(conn):
        issuer_id = _bond_issuer(conn, kind, body.issuer)
        conn.execute(
            "INSERT INTO instruments(instrument_id, kind, name, issuer_id, isin, origin, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'manual', ?) ON CONFLICT(instrument_id) DO UPDATE SET name=excluded.name,"
            " issuer_id=excluded.issuer_id",
            (iid, kind, name, issuer_id, body.isin, now.isoformat()),
        )
        conn.execute(
            "INSERT INTO bond_terms(instrument_id, face_value, coupon_rate, coupon_freq, issue_date, maturity_date,"
            " daycount, listed, call_schedule_json, credit_rating, rating_agency, rating_date)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(instrument_id) DO UPDATE SET"
            " face_value=excluded.face_value, coupon_rate=excluded.coupon_rate, coupon_freq=excluded.coupon_freq,"
            " issue_date=excluded.issue_date, maturity_date=excluded.maturity_date, daycount=excluded.daycount,"
            " listed=excluded.listed, call_schedule_json=excluded.call_schedule_json,"
            " credit_rating=excluded.credit_rating, rating_agency=excluded.rating_agency,"
            " rating_date=excluded.rating_date",
            (
                iid, format(body.face_value, "f"), format(body.coupon_rate, "f"), frequency,
                body.issue_date.isoformat(), body.maturity.isoformat(), daycount, int(listed),
                None if calls is None else json.dumps(calls), *(rating or (None, None, None)),
            ),
        )  # fmt: skip
        conn.execute(
            "INSERT INTO settings(key, value_json) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (f"bond.meta:{iid}", json.dumps({**meta, "entered_at": now.isoformat()}, sort_keys=True)),
        )
        # One quote per date: a new entry for the same date replaces the other measure (price ↔ yield).
        other = "bondyield" if body.clean_price is not None else "bondprice"
        conn.execute(
            "DELETE FROM observations WHERE series_id=? AND observation_date=? AND quality_status='manual'",
            (f"{other}:{iid}", body.quote_date.isoformat()),
        )
    is_price = body.clean_price is not None
    value = body.clean_price if body.clean_price is not None else body.ytm
    assert value is not None
    upsert_observation(
        conn,
        ObservationRow(
            series_id=f"{'bondprice' if is_price else 'bondyield'}:{iid}",
            kind="price" if is_price else "yield",
            value=format(value, "f"),
            unit="per_100_face_clean" if is_price else "fraction",
            currency="INR" if is_price else None,
            observation_date=body.quote_date.isoformat(),
            retrieved_at=now.isoformat(),
            source_id=BOND_QUOTE_SOURCE,
            source_url=body.citation.url,
            quality_status="manual",
            raw_sha256=_sha(body.model_dump()),
            convention=convention,
        ),
    )


def add_gsec(conn: sqlite3.Connection, body: GsecIn, now: datetime) -> str:
    iid = f"{body.kind}:{body.isin}"
    label = "GS" if body.kind == "gsec" else "SDL"
    name = f"{_coupon_text(body.coupon_rate)} % {body.issuer} {label} {body.maturity.isoformat()} ({body.isin})"
    _store_bond(
        conn, iid=iid, kind=body.kind, name=name, body=body, daycount="30E/360", frequency=2, listed=True, calls=None,
        rating=None,
        meta={"quote_kind": body.quote_kind, "shut_days": GSEC_SHUT_DAYS, "issuer": body.issuer,
              "transaction_spread": None if body.transaction_spread is None else format(body.transaction_spread, "f"),
              "secured": None, "rating_citation": None},
        convention="clean price per ₹100, 30E/360" if body.clean_price is not None
        else "ytm; compounding=semiannual (bond-equivalent)",
        now=now,
    )  # fmt: skip
    return iid


def add_corporate_bond(conn: sqlite3.Connection, body: CorporateBondIn, now: datetime) -> str:
    iid = f"corp_bond:{body.isin}"
    name = f"{body.issuer} {_coupon_text(body.coupon_rate)} % {body.maturity.isoformat()} ({body.isin})"
    calls = [
        {"call_date": c.call_date.isoformat(), "call_price": format(c.call_price, "f")}
        for c in sorted(body.call_schedule, key=lambda c: c.call_date)
    ]
    _store_bond(
        conn, iid=iid, kind="corp_bond", name=name, body=body, daycount="ACT/ACT-SEBI", frequency=body.frequency,
        listed=body.listed, calls=calls, rating=(body.rating, body.rating_agency, body.rating_date.isoformat()),
        meta={"quote_kind": body.quote_kind, "shut_days": body.record_date_days, "issuer": body.issuer,
              "transaction_spread": None if body.transaction_spread is None else format(body.transaction_spread, "f"),
              "secured": body.secured, "rating_citation": body.rating_citation.model_dump(mode="json")},
        convention="clean price per ₹100, ACT/ACT-SEBI" if body.clean_price is not None
        else f"ytm; compounding={body.ytm_compounding}",
        now=now,
    )  # fmt: skip
    return iid


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
    # RT-27: the institution TYPE is part of the id, so e.g. "Shriram" the NBFC and a bank of the same name/slug can
    # never overwrite each other's terms (insurance, NBFC exclusion and sovereign backing all depend on the type).
    iid = f"fd:{body.institution_type}:{_slug(body.institution)}:{body.tenure_days}d"
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
        # Needed by the profile's "exclude NBFC deposits" restriction and to recognise sovereign-backed post-office
        # deposits (dicgc_eligible alone cannot tell an NBFC from a post office).
        conn.execute(
            "INSERT INTO settings(key, value_json) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (f"fd.institution_type:{iid}", json.dumps(body.institution_type)),
        )
        # When THIS rate was entered (instruments.created_at is the first entry only; provenance must not show a rate
        # as "retrieved" before the date it describes).
        conn.execute(
            "INSERT INTO settings(key, value_json) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (f"fd.entered_at:{iid}", json.dumps(now.isoformat())),
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
            "DELETE FROM observations WHERE series_id IN (?, ?, ?) AND quality_status = 'manual'",
            (f"yield:{instrument_id}", f"bondprice:{instrument_id}", f"bondyield:{instrument_id}"),
        )
        conn.execute("DELETE FROM settings WHERE key = ?", (f"bond.meta:{instrument_id}",))
        conn.execute("DELETE FROM instruments WHERE instrument_id=?", (instrument_id,))
    return True
