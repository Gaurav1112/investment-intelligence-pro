"""G-secs, SDLs and corporate bonds: load the user's cited entries and build ranking candidates.

ONE loader + builder used by BOTH ``discovery.build_universe`` and ``analysis.build_one`` (the parity test holds them
equal). Every value comes from the user's manual entry with its citation (ADR-0004); nothing is defaulted. A bond with
no usable quote is not evaluable; a stale quote/rating is an ineligible candidate with its reason code.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from iip.engine import candidates as cb
from iip.engine import fixed_income as fi
from iip.engine import tax as tx
from iip.engine.ranking import Tier
from iip.services.explain import badge
from iip.services.instruments import BOND_QUOTE_SOURCE, RATING_STALE_DAYS

BOND_KINDS = ("gsec", "sdl", "corp_bond")
_ENGINE_KIND = {"gsec": fi.BondKind.GSEC, "sdl": fi.BondKind.SDL, "corp_bond": fi.BondKind.CORPORATE}
_COMPOUNDING = {c.value: c for c in fi.Compounding if c is not fi.Compounding.SIMPLE}


@dataclass(frozen=True)
class BondRecord:
    instrument_id: str
    name: str
    kind: str
    origin: str
    created_at: str
    terms: cb.BondTerms
    rating: cb.BondRating
    meta: dict[str, Any]
    transaction_spread: Decimal | None


def _meta(conn: sqlite3.Connection, iid: str) -> dict[str, Any]:
    row = conn.execute("SELECT value_json FROM settings WHERE key=?", (f"bond.meta:{iid}",)).fetchone()
    return dict(json.loads(row["value_json"])) if row else {}


def load_bond(conn: sqlite3.Connection, inst: sqlite3.Row) -> BondRecord | None:
    """Stored terms → engine inputs. ``None`` when the terms row is missing (not evaluable)."""
    iid, kind = str(inst["instrument_id"]), str(inst["kind"])
    t = conn.execute("SELECT * FROM bond_terms WHERE instrument_id=?", (iid,)).fetchone()
    if t is None or t["issue_date"] is None:
        return None
    meta = _meta(conn, iid)
    if "shut_days" not in meta:
        return None
    calls = tuple(
        fi.CallOption(date.fromisoformat(c["call_date"]), Decimal(c["call_price"]))
        for c in json.loads(t["call_schedule_json"] or "[]")
    )
    terms = cb.BondTerms(
        kind=_ENGINE_KIND[kind],
        coupon_rate=Decimal(t["coupon_rate"]),
        frequency=int(t["coupon_freq"]),
        issue_date=date.fromisoformat(t["issue_date"]),
        maturity=date.fromisoformat(t["maturity_date"]),
        face_value=Decimal(t["face_value"]),
        shut_days=int(meta["shut_days"]),
        listed=bool(t["listed"]),
        calls=calls,
        secured=meta.get("secured"),
    )
    rating = cb.BondRating(
        t["credit_rating"],
        t["rating_agency"],
        None if t["rating_date"] is None else date.fromisoformat(t["rating_date"]),
    )
    spread = meta.get("transaction_spread")
    return BondRecord(
        iid, str(inst["name"]), kind, str(inst["origin"]), str(inst["created_at"]), terms, rating, meta,
        None if spread is None else Decimal(str(spread)),
    )  # fmt: skip


def bond_quote(conn: sqlite3.Connection, iid: str, as_of: date) -> tuple[sqlite3.Row | None, str | None]:
    """The latest cited quote (price or yield) dated on or before ``as_of``.

    Returns (row, problem). A quote dated after ``as_of`` is never used; if it is the only one, the problem is
    LOOK_AHEAD. Entry replaces the other measure for the same date, so a date carries at most one manual quote; two
    current rows for one date (e.g. a fixture and a manual entry) are a SOURCE_CONFLICT — never picked silently.
    """
    rows = conn.execute(
        "SELECT obs_id, series_id, kind, value, observation_date, source_id, source_url, retrieved_at, quality_status,"
        " convention FROM observations WHERE series_id IN (?, ?) AND superseded_by IS NULL"
        " AND quality_status IN ('ok','manual','fixture') ORDER BY observation_date DESC, obs_id DESC",
        (f"bondprice:{iid}", f"bondyield:{iid}"),
    ).fetchall()
    if not rows:
        return None, None
    usable = [r for r in rows if date.fromisoformat(r["observation_date"]) <= as_of]
    if not usable:
        return rows[-1], f"LOOK_AHEAD: quote dated {rows[-1]['observation_date']}, after the analysis date"
    same_day = [r for r in usable if r["observation_date"] == usable[0]["observation_date"]]
    if len(same_day) > 1:
        detail = ", ".join(f"{r['series_id'].split(':')[0]}={r['value']} ({r['source_id']})" for r in same_day)
        return same_day[0], f"SOURCE_CONFLICT: two quotes on {same_day[0]['observation_date']}: {detail}"
    return same_day[0], None


def _quote_from_row(r: sqlite3.Row) -> cb.BondQuote:
    qd = date.fromisoformat(r["observation_date"])
    if r["kind"] == "price":
        return cb.BondQuote(qd, clean_price=Decimal(r["value"]))
    conv = str(r["convention"] or "")
    comp = None
    if "compounding=" in conv:
        comp = _COMPOUNDING.get(conv.split("compounding=")[1].split(maxsplit=1)[0])
    return cb.BondQuote(qd, ytm=Decimal(r["value"]), ytm_compounding=comp)


def provenance(rec: BondRecord, r: sqlite3.Row, as_of: date) -> dict[str, Any]:
    fixture = r["quality_status"] == "fixture" or rec.origin == "fixture"
    prov: dict[str, Any] = {
        "kind": rec.kind,
        "source_id": r["source_id"],
        "url": r["source_url"],
        "retrieved_at": r["retrieved_at"],
        "observation_date": r["observation_date"],
        "quality_status": r["quality_status"],
        "fixture": fixture,
    }
    prov["freshness"] = badge(prov, as_of)
    return prov


def build_bond(
    conn: sqlite3.Connection,
    inst: sqlite3.Row,
    *,
    amount: Decimal,
    as_of: date,
    withdrawal: date,
    ruleset: tx.TaxRuleSet,
    profile: tx.TaxProfile | None,
) -> tuple[cb.BuiltCandidate | None, dict[str, Any], tuple[str, ...]]:
    """(candidate or None, provenance, not-evaluable reasons). None ⇔ no terms or no quote stored at all."""
    kind = str(inst["kind"])
    rec = load_bond(conn, inst)
    if rec is None:
        prov = {"kind": kind, "fixture": inst["origin"] == "fixture"}
        return None, prov, ("MISSING_DATA: no bond terms stored",)
    r, problem = bond_quote(conn, rec.instrument_id, as_of)
    if r is None:
        return None, {"kind": kind, "fixture": rec.origin == "fixture"}, ("MISSING_DATA: no price or yield stored",)
    prov = provenance(rec, r, as_of)
    early = rec.terms.maturity > withdrawal
    tier, _, _ = cb.bond_tier_and_credit(rec.terms.kind, rec.rating.rating)
    quote = _quote_from_row(r)
    if problem is None and quote.ytm is not None and quote.ytm_compounding is None and rec.kind == "corp_bond":
        problem = "MISSING_DATA: the compounding of the quoted corporate yield is not recorded"
    if problem is not None:
        return cb._ineligible(rec.instrument_id, rec.name, Tier.T3 if early else tier, [problem], amount), prov, ()
    built = cb.bond_candidate(
        instrument_id=rec.instrument_id, name=rec.name, amount=amount, as_of=as_of, withdrawal=withdrawal,
        terms=rec.terms, quote=quote, rating=rec.rating, transaction_spread=rec.transaction_spread,
        ruleset=ruleset, profile=profile,
    )  # fmt: skip
    return built, prov, ()


def bond_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM instruments WHERE kind IN ('gsec','sdl','corp_bond') ORDER BY instrument_id"
    ).fetchall()


def list_bonds(conn: sqlite3.Connection, as_of: date) -> list[dict[str, Any]]:
    """Stored bonds with their latest quote, its freshness, the rating and its age (for the Fixed income page)."""
    out: list[dict[str, Any]] = []
    for inst in bond_rows(conn):
        rec = load_bond(conn, inst)
        r, problem = bond_quote(conn, str(inst["instrument_id"]), as_of)
        item: dict[str, Any] = {
            "instrument_id": inst["instrument_id"],
            "kind": inst["kind"],
            "name": inst["name"],
            "isin": inst["isin"],
            "origin": inst["origin"],
            "fixture": inst["origin"] == "fixture",
            "quote": None,
            "quote_problem": problem,
            "terms": None,
            "rating": None,
        }
        if r is not None and rec is not None:
            prov = provenance(rec, r, as_of)
            item["quote"] = {
                "kind": "clean_price" if r["kind"] == "price" else "ytm",
                "value": r["value"],
                "convention": r["convention"],
                "quote_date": r["observation_date"],
                "age_days": (as_of - date.fromisoformat(r["observation_date"])).days,
                "freshness": prov["freshness"],
                "citation_url": r["source_url"],
                "source_id": r["source_id"] or BOND_QUOTE_SOURCE,
            }
        if rec is not None:
            t = rec.terms
            item["terms"] = {
                "issuer": rec.meta.get("issuer"),
                "coupon_rate": format(t.coupon_rate, "f"),
                "frequency": t.frequency,
                "issue_date": t.issue_date.isoformat(),
                "maturity": t.maturity.isoformat(),
                "face_value": format(t.face_value, "f"),
                "listed": t.listed,
                "secured": t.secured,
                "record_date_days": t.shut_days,
                "calls": [{"call_date": c.call_date.isoformat(), "call_price": format(c.call_price, "f")}
                          for c in t.calls],
                "transaction_spread": None if rec.transaction_spread is None else format(rec.transaction_spread, "f"),
                "day_count": "30E/360" if t.kind is not fi.BondKind.CORPORATE else "ACT/ACT-SEBI",
            }  # fmt: skip
            if rec.rating.rating is not None and rec.rating.rating_date is not None:
                age = (as_of - rec.rating.rating_date).days
                cite = rec.meta.get("rating_citation") or {}
                item["rating"] = {
                    "rating": rec.rating.rating,
                    "agency": rec.rating.agency,
                    "rating_date": rec.rating.rating_date.isoformat(),
                    "age_days": age,
                    "stale": age > RATING_STALE_DAYS or age < 0,
                    "citation_url": cite.get("url"),
                }
        out.append(item)
    return out
