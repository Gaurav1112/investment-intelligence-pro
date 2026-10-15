"""User-entered, cited data inputs that unblock analysis (Track 1): CPI, the 91-day T-bill risk-free series, scheme
factsheet facts and bank FD card-rate tables.

Every value is stored exactly as entered with its https citation and the time it was entered; nothing is defaulted,
interpolated or chained. Corrections append (history is kept) and readers use the latest. Base-2012 and base-2024 CPI
are separate series (``cpi:all-india:base2012`` / ``cpi:all-india:base2024``) and are never mixed.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import re
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from iip.data.models import RawPayload
from iip.engine.candidates import FACTSHEET_MAX_AGE_DAYS, FundCreditFacts
from iip.engine.deposits import CardRateBucket, PrematureRateBasis, validate_card_rate_table
from iip.engine.errors import InvalidInput
from iip.engine.macro import RISK_FREE_MAX_AGE_DAYS, CpiPoint
from iip.engine.ranking import CREDIT_SCALE
from iip.services.instruments import TBILL_FRESH_DAYS, TBILL_STALE_DAYS, Citation
from iip.store.db import write_tx
from iip.store.observations import ObservationRow, UpsertOutcome, upsert_observation

RISK_FREE_SERIES = "riskfree:tbill91"
RISK_FREE_CONVENTION = "RBI_TBILL_IMPLICIT_YIELD_AS_PUBLISHED"
SHORT_TERM_RATINGS: tuple[str, ...] = ("A1+", "A1", "A2+", "A2", "A3+", "A3", "A4+", "A4")
RATING_CHOICES: tuple[str, ...] = (*reversed(CREDIT_SCALE), *SHORT_TERM_RATINGS)
_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_SLUG = re.compile(r"[^a-z0-9]+")


class InputError(Exception):
    """A request the inputs service refuses; mapped to an HTTP status by the route layer."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _no_float(v: object) -> object:
    if isinstance(v, float):
        raise ValueError("send decimals as strings, not floats")
    return v


def _sha(payload: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _parse_month(text: str) -> date:
    m = _MONTH.match(text)
    if not m:
        raise ValueError("month must be YYYY-MM")
    return date(int(m.group(1)), int(m.group(2)), 1)


def _month_end(first: date) -> date:
    return first.replace(day=calendar.monthrange(first.year, first.month)[1])


def institution_key(name: str) -> str:
    return _SLUG.sub("-", name.lower()).strip("-")[:40]


def cpi_series_id(base_year: str) -> str:
    return f"cpi:all-india:base{base_year}"


def cpi_yoy_series_id(base_year: str) -> str:
    return f"cpi-yoy:all-india:base{base_year}"


# ============================================================================================ CPI


class CPIPointIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_year: Literal["2012", "2024"]
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    index: Decimal = Field(gt=0, lt=Decimal("100000"))
    yoy_inflation_pct: Decimal | None = Field(default=None, gt=Decimal("-50"), lt=Decimal("100"))
    provisional: bool = False
    citation: Citation  # url of the MoSPI release; as_of = the release date
    _f = field_validator("index", "yoy_inflation_pct", mode="before")(_no_float)

    @model_validator(mode="after")
    def _released_after_month(self) -> CPIPointIn:
        if self.citation.as_of <= _month_end(_parse_month(self.month)):
            raise ValueError("the release date must be after the reference month (CPI is released the next month)")
        return self


def _upsert_cited(conn: sqlite3.Connection, row: ObservationRow) -> UpsertOutcome:
    """A change of convention alone (provisional → final) is a correction too; history is kept."""
    return upsert_observation(conn, row, compare_convention=True)


def add_cpi_point(conn: sqlite3.Connection, body: CPIPointIn, now: datetime, *, source_id: str = "mospi.cpi",
                  quality_status: str = "manual", raw_sha256: str | None = None) -> dict[str, str]:  # fmt: skip
    if body.citation.as_of > now.date():
        raise InputError(422, "INVALID_INPUT", "the release date is in the future")
    month = _parse_month(body.month)
    flag = "|PROVISIONAL" if body.provisional else ""
    sha = raw_sha256 or _sha(body.model_dump())

    def row(series_id: str, value: Decimal, unit: str, convention: str) -> ObservationRow:
        return ObservationRow(
            series_id=series_id, kind="cpi", value=format(value, "f"), unit=unit, currency=None,
            observation_date=month.isoformat(), retrieved_at=now.isoformat(), source_id=source_id,
            source_url=body.citation.url, quality_status=quality_status, raw_sha256=sha, convention=convention,
            publication_time=body.citation.as_of.isoformat(),
        )  # fmt: skip

    outcome = _upsert_cited(conn, row(cpi_series_id(body.base_year), body.index, "index_points",
                                      f"CPI_COMBINED_GENERAL_INDEX_BASE{body.base_year}{flag}"))  # fmt: skip
    if body.yoy_inflation_pct is not None:
        _upsert_cited(conn, row(cpi_yoy_series_id(body.base_year), body.yoy_inflation_pct, "percent",
                                f"CPI_YOY_PCT_BASE{body.base_year}{flag}"))  # fmt: skip
    return {"series_id": cpi_series_id(body.base_year), "outcome": outcome.value}


def _cpi_rows(conn: sqlite3.Connection, series_id: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM observations WHERE series_id=? AND superseded_by IS NULL"
            " AND quality_status IN ('ok','manual','fixture') ORDER BY observation_date",
            (series_id,),
        )
    )


def list_cpi(conn: sqlite3.Connection) -> dict[str, Any]:
    series = []
    for base in ("2012", "2024"):
        yoy = {r["observation_date"]: r for r in _cpi_rows(conn, cpi_yoy_series_id(base))}
        points = []
        for r in _cpi_rows(conn, cpi_series_id(base)):
            y = yoy.get(r["observation_date"])
            points.append({
                "month": r["observation_date"][:7], "index": r["value"],
                "yoy_inflation_pct": None if y is None else y["value"],
                "provisional": str(r["convention"] or "").endswith("|PROVISIONAL"),
                "source_id": r["source_id"], "source_url": r["source_url"], "retrieved_at": r["retrieved_at"],
                "published_on": r["publication_time"], "quality_status": r["quality_status"],
            })  # fmt: skip
        series.append({"series_id": cpi_series_id(base), "base_year": base, "points": points})
    return {
        "note": "Base 2012 and base 2024 are separate series and are never chained or compared without a linking "
        "factor. Year-on-year rates are computed only inside one base.",
        "series": series,
    }


def cpi_points(conn: sqlite3.Connection) -> tuple[list[CpiPoint], dict[tuple[str, date], dict[str, Any]]]:
    """Engine CpiPoints (both bases, kept separate) and the provenance of each (base, month)."""
    points: list[CpiPoint] = []
    prov: dict[tuple[str, date], dict[str, Any]] = {}
    for base in ("2012", "2024"):
        idx = {r["observation_date"]: r for r in _cpi_rows(conn, cpi_series_id(base))}
        yoy = {r["observation_date"]: r for r in _cpi_rows(conn, cpi_yoy_series_id(base))}
        for d in sorted(set(idx) | set(yoy)):
            ri, ry = idx.get(d), yoy.get(d)
            r = ri if ri is not None else ry
            assert r is not None
            month = date.fromisoformat(d)
            provisional = any(str(x["convention"] or "").endswith("|PROVISIONAL") for x in (ri, ry) if x is not None)
            points.append(CpiPoint(
                base_year=base, month=month, index=None if ri is None else Decimal(ri["value"]),
                yoy=None if ry is None else Decimal(ry["value"]) / Decimal(100), provisional=provisional,
            ))  # fmt: skip
            prov[(base, month)] = {
                "source_id": r["source_id"], "url": r["source_url"], "retrieved_at": r["retrieved_at"],
                "observation_date": d, "quality_status": r["quality_status"],
                "fixture": r["quality_status"] == "fixture",
            }  # fmt: skip
    return points, prov


# ============================================================================================ risk-free


class RiskFreeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    yield_fraction: Decimal = Field(gt=0, lt=Decimal("0.5"))  # 91-day cut-off implicit yield, as published
    citation: Citation  # url of the RBI press release; as_of = the auction date
    _f = field_validator("yield_fraction", mode="before")(_no_float)


def add_risk_free(conn: sqlite3.Connection, body: RiskFreeIn, now: datetime) -> dict[str, str]:
    if body.citation.as_of > now.date():
        raise InputError(422, "INVALID_INPUT", "the auction date is in the future")
    outcome = upsert_observation(conn, ObservationRow(
        series_id=RISK_FREE_SERIES, kind="yield", value=format(body.yield_fraction, "f"), unit="fraction",
        currency=None, observation_date=body.citation.as_of.isoformat(), retrieved_at=now.isoformat(),
        source_id="rbi.pr.tbill", source_url=body.citation.url, quality_status="manual",
        raw_sha256=_sha(body.model_dump()), convention=RISK_FREE_CONVENTION,
    ))  # fmt: skip
    return {"series_id": RISK_FREE_SERIES, "outcome": outcome.value}


def risk_free_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM observations WHERE series_id=? AND superseded_by IS NULL"
            " AND quality_status IN ('ok','manual','fixture') ORDER BY observation_date",
            (RISK_FREE_SERIES,),
        )
    )


def risk_free_freshness(latest: date | None, as_of: date) -> str:
    """Registry rbi.pr.tbill: fresh ≤ 7 days, stale ≤ 21, expired beyond."""
    if latest is None:
        return "UNAVAILABLE"
    age = (as_of - latest).days
    if age <= TBILL_FRESH_DAYS:
        return "FRESH"
    return "STALE" if age <= TBILL_STALE_DAYS else "EXPIRED"


def list_risk_free(conn: sqlite3.Connection, as_of: date) -> dict[str, Any]:
    rows = [r for r in risk_free_rows(conn) if r["observation_date"] <= as_of.isoformat()]
    points = [
        {"auction_date": r["observation_date"], "yield_fraction": r["value"], "source_url": r["source_url"],
         "retrieved_at": r["retrieved_at"], "quality_status": r["quality_status"]}
        for r in rows
    ]  # fmt: skip
    latest = points[-1] if points else None
    return {
        "series_id": RISK_FREE_SERIES,
        "convention": RISK_FREE_CONVENTION,
        "coverage_rule": f"each return date needs an auction cut-off within the previous {RISK_FREE_MAX_AGE_DAYS} days",
        "freshness": risk_free_freshness(date.fromisoformat(latest["auction_date"]) if latest else None, as_of),
        "latest": latest,
        "points": points,
    }


# ============================================================================================ fund facts


class FundFactsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    modified_duration: Decimal | None = Field(default=None, ge=0, le=40)
    macaulay_duration: Decimal | None = Field(default=None, ge=0, le=40)
    ytm: Decimal | None = Field(default=None, gt=0, lt=Decimal("0.5"))
    average_maturity_years: Decimal | None = Field(default=None, ge=0, le=60)
    expense_ratio: Decimal | None = Field(default=None, ge=0, le=Decimal("0.05"))
    expense_ratio_kind: Literal["TER", "BER"] | None = None
    lowest_rating: str | None = None
    share_below_aaa: Decimal | None = Field(default=None, ge=0, le=1)
    share_sovereign_cash: Decimal | None = Field(default=None, ge=0, le=1)
    citation: Citation  # url of the factsheet; as_of = the date you read it
    _f = field_validator(
        "modified_duration", "macaulay_duration", "ytm", "average_maturity_years", "expense_ratio", "share_below_aaa",
        "share_sovereign_cash", mode="before",
    )(_no_float)  # fmt: skip

    @field_validator("lowest_rating")
    @classmethod
    def _rating(cls, v: str | None) -> str | None:
        if v is not None and v not in RATING_CHOICES:
            raise ValueError(f"lowest_rating must be one of {', '.join(RATING_CHOICES)}")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> FundFactsIn:
        metrics = ("modified_duration", "macaulay_duration", "ytm", "average_maturity_years", "expense_ratio",
                   "lowest_rating", "share_below_aaa", "share_sovereign_cash")  # fmt: skip
        if all(getattr(self, m) is None for m in metrics):
            raise ValueError("enter at least one factsheet figure")
        if (self.expense_ratio is None) != (self.expense_ratio_kind is None):
            raise ValueError("expense_ratio and expense_ratio_kind (TER or BER) go together")
        if self.citation.as_of < _month_end(_parse_month(self.as_of_month)):
            raise ValueError("a factsheet for a month cannot be read before that month ends (citation date)")
        return self


_FACT_FIELDS = ("modified_duration", "macaulay_duration", "ytm", "average_maturity_years", "expense_ratio",
                "expense_ratio_kind", "lowest_rating", "share_below_aaa", "share_sovereign_cash")  # fmt: skip


_FACTS_INSERT = (
    "INSERT INTO fund_facts(instrument_id, as_of_month, as_of_date, modified_duration, macaulay_duration, ytm,"
    " average_maturity_years, expense_ratio, expense_ratio_kind, lowest_rating, share_below_aaa, share_sovereign_cash,"
    " citation_url, citation_note, verified_on, entered_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


def _require_mf(conn: sqlite3.Connection, instrument_id: str) -> None:
    row = conn.execute("SELECT kind FROM instruments WHERE instrument_id=?", (instrument_id,)).fetchone()
    if row is None:
        raise InputError(404, "NOT_FOUND", f"instrument {instrument_id!r} is not in the local store")
    if row["kind"] != "mf_scheme":
        raise InputError(422, "NOT_A_FUND", "factsheet facts apply to mutual fund schemes only")


def add_fund_facts(conn: sqlite3.Connection, instrument_id: str, body: FundFactsIn, now: datetime) -> dict[str, Any]:
    _require_mf(conn, instrument_id)
    if body.citation.as_of > now.date():
        raise InputError(422, "INVALID_INPUT", "the citation date is in the future")
    as_of_date = _month_end(_parse_month(body.as_of_month))

    def text(name: str) -> str | None:
        v = getattr(body, name)
        return None if v is None else (format(v, "f") if isinstance(v, Decimal) else str(v))

    with write_tx(conn):
        cur = conn.execute(
            _FACTS_INSERT,
            (instrument_id, body.as_of_month, as_of_date.isoformat(), *(text(f) for f in _FACT_FIELDS),
             body.citation.url, body.citation.note, body.citation.as_of.isoformat(), now.isoformat()),
        )  # fmt: skip
    return {"fact_id": int(cur.lastrowid or 0), "instrument_id": instrument_id}


def _facts_out(r: sqlite3.Row, as_of: date) -> dict[str, Any]:
    age = (as_of - date.fromisoformat(r["as_of_date"])).days
    return {
        "fact_id": r["fact_id"], "as_of_month": r["as_of_month"], "as_of_date": r["as_of_date"],
        **{f: r[f] for f in _FACT_FIELDS},
        "citation_url": r["citation_url"], "citation_note": r["citation_note"], "verified_on": r["verified_on"],
        "entered_at": r["entered_at"], "age_days": age,
        "freshness": "STALE" if age > FACTSHEET_MAX_AGE_DAYS or age < 0 else "FRESH",
    }  # fmt: skip


def _facts_rows(conn: sqlite3.Connection, instrument_id: str, as_of: date) -> list[sqlite3.Row]:
    """Facts whose portfolio date is on or before the analysis date, latest first (as_of_date, then entry time)."""
    return list(
        conn.execute(
            "SELECT * FROM fund_facts WHERE instrument_id=? AND as_of_date <= ?"
            " ORDER BY as_of_date DESC, entered_at DESC, fact_id DESC",
            (instrument_id, as_of.isoformat()),
        )
    )


def list_fund_facts(conn: sqlite3.Connection, instrument_id: str, as_of: date) -> dict[str, Any]:
    _require_mf(conn, instrument_id)
    rows = _facts_rows(conn, instrument_id, as_of)
    history = [_facts_out(r, as_of) for r in rows]
    return {
        "instrument_id": instrument_id,
        "stale_after_days": FACTSHEET_MAX_AGE_DAYS,
        "latest": history[0] if history else None,
        "history": history,
    }


def latest_fund_facts(conn: sqlite3.Connection, instrument_id: str, as_of: date) -> dict[str, Any] | None:
    """Latest facts usable at ``as_of`` with their provenance (``prov``), or None."""
    rows = _facts_rows(conn, instrument_id, as_of)
    if not rows:
        return None
    out = _facts_out(rows[0], as_of)
    out["prov"] = {
        "source_id": "amc.factsheet",
        "url": rows[0]["citation_url"],
        "retrieved_at": rows[0]["entered_at"],
        "observation_date": rows[0]["as_of_date"],
        "quality_status": "manual",
        "fixture": False,
        "freshness": "STALE" if out["freshness"] == "STALE" else "MANUAL",
    }
    return out


def fund_credit_facts(conn: sqlite3.Connection, instrument_id: str, as_of: date) -> FundCreditFacts | None:
    """The latest factsheet's credit facts for the ranking credit floor (RT-23), or None when none is entered."""
    f = latest_fund_facts(conn, instrument_id, as_of)
    if f is None:
        return None
    return FundCreditFacts(lowest_rating=f["lowest_rating"], as_of=date.fromisoformat(f["as_of_date"]))


# ============================================================================================ FD card rates


class CardRateBucketIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_days: int = Field(ge=1, le=3650)
    max_days: int = Field(ge=1, le=3650)
    rate: Decimal = Field(ge=0, lt=Decimal("0.3"))
    _f = field_validator("rate", mode="before")(_no_float)


class FDRateTableIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    institution: str = Field(min_length=2, max_length=120)
    buckets: list[CardRateBucketIn] = Field(min_length=1, max_length=60)
    premature_rate_basis: Literal["period_card", "min(booked,period_card)"] = "period_card"
    citation: Citation  # url of the bank's card-rate page; as_of = the date the rates apply from

    @model_validator(mode="after")
    def _table(self) -> FDRateTableIn:
        try:
            validate_card_rate_table([CardRateBucket(b.min_days, b.max_days, b.rate) for b in self.buckets])
        except InvalidInput as exc:
            raise ValueError(str(exc)) from exc
        return self


def add_fd_rate_table(conn: sqlite3.Connection, body: FDRateTableIn, now: datetime) -> dict[str, Any]:
    if body.citation.as_of > now.date():
        raise InputError(422, "INVALID_INPUT", "the card-rate date is in the future")
    key = institution_key(body.institution)
    with write_tx(conn):
        cur = conn.execute(
            "INSERT INTO fd_card_rate_tables(institution_key, institution, as_of, premature_rate_basis, citation_url,"
            " citation_note, entered_at) VALUES (?,?,?,?,?,?,?)",
            (key, body.institution, body.citation.as_of.isoformat(), body.premature_rate_basis, body.citation.url,
             body.citation.note, now.isoformat()),
        )  # fmt: skip
        tid = int(cur.lastrowid or 0)
        conn.executemany(
            "INSERT INTO fd_card_rate_buckets(table_id, min_days, max_days, rate) VALUES (?,?,?,?)",
            [(tid, b.min_days, b.max_days, format(b.rate, "f")) for b in body.buckets],
        )
    return {"table_id": tid, "institution_key": key}


def _table_out(conn: sqlite3.Connection, t: sqlite3.Row) -> dict[str, Any]:
    buckets = conn.execute(
        "SELECT min_days, max_days, rate FROM fd_card_rate_buckets WHERE table_id=? ORDER BY min_days",
        (t["table_id"],),
    ).fetchall()
    return {
        "table_id": t["table_id"], "institution": t["institution"], "institution_key": t["institution_key"],
        "as_of": t["as_of"], "premature_rate_basis": t["premature_rate_basis"], "citation_url": t["citation_url"],
        "citation_note": t["citation_note"], "entered_at": t["entered_at"],
        "buckets": [dict(b) for b in buckets],
    }  # fmt: skip


def list_fd_rate_tables(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT * FROM fd_card_rate_tables ORDER BY institution_key, as_of DESC, entered_at DESC, table_id DESC"
    ).fetchall()
    return {"tables": [_table_out(conn, t) for t in rows]}


def latest_fd_rate_table(conn: sqlite3.Connection, institution: str, as_of: date) -> dict[str, Any] | None:
    """The latest card-rate table for this institution that applied on or before ``as_of`` (no look-ahead)."""
    t = conn.execute(
        "SELECT * FROM fd_card_rate_tables WHERE institution_key=? AND as_of <= ?"
        " ORDER BY as_of DESC, entered_at DESC, table_id DESC LIMIT 1",
        (institution_key(institution), as_of.isoformat()),
    ).fetchone()
    if t is None:
        return None
    out = _table_out(conn, t)
    out["engine_buckets"] = [CardRateBucket(b["min_days"], b["max_days"], Decimal(b["rate"])) for b in out["buckets"]]
    out["engine_basis"] = PrematureRateBasis(t["premature_rate_basis"])
    return out


# ============================================================================================ MoSPI


def store_mospi_record(conn: sqlite3.Connection, rec: Any, now: datetime) -> dict[str, str]:
    """Store one parsed MoSPI record (iip.data.mospi.CpiRecord) as live observations with the payload hash."""
    payload: RawPayload = rec.raw
    body = CPIPointIn(
        base_year=rec.base_year, month=f"{rec.year:04d}-{rec.month:02d}", index=rec.index,
        yoy_inflation_pct=rec.yoy_pct, provisional=rec.provisional,
        citation=Citation(url=payload.final_url, as_of=payload.retrieved_at.date(), note="MoSPI CPI API"),
    )  # fmt: skip
    return add_cpi_point(conn, body, now, source_id="mospi.cpi", quality_status="ok", raw_sha256=payload.sha256)
