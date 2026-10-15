"""Ingestion pipeline: registry → fetch → parse → validate → normalised store, with a run ledger (ADR-0004).

Data minimisation (AMFI ToU: personal use; do not store a "significant portion"):
* latest NAV is kept only for Direct-plan Growth-option open-ended schemes, plus anything held or watched;
* NAV history is backfilled only on explicit request for individual schemes, keeping just that scheme's rows;
* raw payloads are hashed and recorded in the run ledger, not archived.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from iip.data.fetch import Fetcher, FetchError
from iip.data.models import DataError, Observation, ParseResult, SchemeRecord
from iip.data.parsers._amfi import CURRENCY as NAV_CURRENCY
from iip.data.parsers._amfi import UNIT as NAV_UNIT
from iip.data.parsers.amfi_navall import parse_navall
from iip.data.parsers.amfi_navhistory import parse_navhistory
from iip.data.registry import (
    MAX_HISTORY_WINDOW_DAYS,
    REGISTRY,
    SourceMode,
    navall_request,
    navhistory_request,
)
from iip.data.validators import run_all
from iip.engine.freshness import nav_is_stale
from iip.store.db import write_tx
from iip.store.observations import ObservationRow, upsert_observation


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    source_id: str
    status: str
    rows_ok: int
    rows_rejected: int
    stored: int
    detail: str


def series_id(scheme_code: int) -> str:
    return f"nav:{scheme_code}"


def instrument_id(scheme_code: int) -> str:
    return f"mf:{scheme_code}"


_UPSERT_SOURCE = """
INSERT INTO sources(source_id, owner, official, url, terms_url, licence_note, mode, freshness_slo_days)
VALUES (?,?,?,?,?,?,?,?)
ON CONFLICT(source_id) DO UPDATE SET owner=excluded.owner, official=excluded.official, url=excluded.url,
    terms_url=excluded.terms_url, licence_note=excluded.licence_note, mode=excluded.mode,
    freshness_slo_days=excluded.freshness_slo_days
"""


def sync_sources(conn: sqlite3.Connection) -> None:
    """Mirror the code-defined registry into the DB (the registry in code stays the source of truth)."""
    with write_tx(conn):
        for spec in REGISTRY.values():
            conn.execute(
                _UPSERT_SOURCE,
                (
                    spec.id,
                    spec.owner,
                    int(spec.official),
                    ",".join(sorted(spec.allowed_hosts)) or "manual",
                    spec.terms_url,
                    spec.licence_note,
                    spec.mode.value if spec.mode is not SourceMode.LIVE else "live",
                    spec.freshness.stale_max,
                ),
            )


def _start_run(conn: sqlite3.Connection, source_id: str, now: datetime) -> str:
    run_id = f"run_{now.strftime('%Y%m%dT%H%M%SZ')}_{secrets.token_hex(4)}"
    conn.execute(
        "INSERT INTO ingestion_runs(run_id, source_id, started_at, status) VALUES (?,?,?, 'running')",
        (run_id, source_id, now.isoformat()),
    )
    return run_id


def _finish_run(
    conn: sqlite3.Connection, run_id: str, now: datetime, status: str, ok: int, rej: int, sha: str | None, err: str
) -> None:
    conn.execute(
        "UPDATE ingestion_runs SET finished_at=?, status=?, rows_ok=?, rows_rejected=?, raw_sha256=?, error=?"
        " WHERE run_id=?",
        (now.isoformat(), status, ok, rej, sha, err or None, run_id),
    )


@contextmanager
def _failing_run(conn: sqlite3.Connection, run_id: str, now: Callable[[], datetime]) -> Iterator[None]:
    """Any unexpected error after ``_start_run`` records the run as 'failed' (so the ingestion alert fires) and
    re-raises. Only the exception CLASS is stored: a message can carry values (threat-model C-13)."""
    try:
        yield
    except BaseException as exc:
        if conn.in_transaction:
            conn.rollback()
        _finish_run(conn, run_id, now(), "failed", 0, 0, None, type(exc).__name__)
        raise


INTERRUPTED = "INTERRUPTED: the app stopped while this run was in progress"


def mark_interrupted_runs(conn: sqlite3.Connection, now: datetime) -> int:
    """At startup no run can be in progress (one process), so any 'running' row was cut off by a crash or a stop.
    It becomes 'failed' with an explicit reason, which the 'ingestion run failed' alert picks up."""
    cur = conn.execute(
        "UPDATE ingestion_runs SET status='failed', finished_at=?, error=? WHERE status='running'",
        (now.isoformat(), INTERRUPTED),
    )
    return cur.rowcount


def tracked_scheme_codes(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute(
        "SELECT i.amfi_code FROM instruments i WHERE i.amfi_code IS NOT NULL AND ("
        " i.instrument_id IN (SELECT instrument_id FROM watchlist) OR"
        " i.instrument_id IN (SELECT instrument_id FROM transactions))"
    ).fetchall()
    return {int(r["amfi_code"]) for r in rows}


def in_minimised_scope(rec: SchemeRecord, tracked: set[int]) -> bool:
    if rec.scheme_code in tracked:
        return True
    text = " ".join(x for x in (rec.plan, rec.option, rec.scheme_name) if x).lower()
    open_ended = (rec.scheme_type or "").lower().startswith("open")
    return open_ended and "direct" in text and "growth" in text and "idcw" not in text


def display_name(rec: SchemeRecord) -> str:
    """AMFI reuses one scheme name for several codes (e.g. lock-in variants): always qualify with plan/option/code."""
    parts = [p for p in (rec.plan, rec.option) if p]
    qual = " · ".join(parts)
    return (
        f"{rec.scheme_name} — {qual} (AMFI {rec.scheme_code})"
        if qual
        else f"{rec.scheme_name} (AMFI {rec.scheme_code})"
    )


def _store_schemes(conn: sqlite3.Connection, records: Iterable[SchemeRecord], now: datetime) -> None:
    for rec in records:
        iid = instrument_id(rec.scheme_code)
        conn.execute(
            "INSERT INTO instruments(instrument_id, kind, name, isin, amfi_code, origin, created_at)"
            " VALUES (?, 'mf_scheme', ?, ?, ?, 'source', ?) ON CONFLICT(instrument_id) DO UPDATE SET"
            " name=excluded.name, isin=COALESCE(excluded.isin, instruments.isin)",
            (iid, display_name(rec), rec.isin_growth, str(rec.scheme_code), now.isoformat()),
        )
        plan = None
        text = " ".join(x for x in (rec.plan, rec.scheme_name) if x).lower()
        if "direct" in text:
            plan = "direct"
        elif "regular" in text:
            plan = "regular"
        conn.execute(
            "INSERT INTO mf_schemes(instrument_id, amc, category_raw, sebi_category, plan, option_type)"
            " VALUES (?,?,?,?,?,?) ON CONFLICT(instrument_id) DO UPDATE SET amc=excluded.amc,"
            " category_raw=excluded.category_raw, sebi_category=excluded.sebi_category, plan=excluded.plan,"
            " option_type=excluded.option_type",
            (iid, rec.amc or "", rec.category or "", rec.category, plan, rec.option),
        )


def _store_observations(
    conn: sqlite3.Connection, observations: Iterable[Observation], run_id: str, keep: Callable[[int], bool]
) -> int:
    stored = 0
    for o in observations:
        code = int(o.entity_key)
        if not keep(code):
            continue
        upsert_observation(
            conn,
            ObservationRow(
                series_id=series_id(code),
                kind="nav",
                value=format(o.value, "f"),
                unit=o.unit,
                currency=o.currency,
                observation_date=o.observation_date.isoformat(),
                retrieved_at=o.retrieved_at.isoformat(),
                source_id=o.source_id,
                source_url=o.source_url,
                quality_status=o.quality_status.value,
                raw_sha256=o.raw_sha256,
                convention=o.convention,
                publication_time=o.publication_time.isoformat() if o.publication_time else None,
                ingestion_run_id=run_id,
            ),
        )
        stored += 1
    return stored


def _validated(result: ParseResult) -> list[Observation]:
    checked = run_all(list(result.observations), expected_unit=NAV_UNIT, expected_currency=NAV_CURRENCY)
    return list(checked.observations)


def ingest_navall(conn: sqlite3.Connection, fetcher: Fetcher, now: Callable[[], datetime]) -> RunSummary:
    source = "amfi.navall"
    run_id = _start_run(conn, source, now())
    try:
        payload = fetcher.fetch(navall_request())
        result = parse_navall(payload)
    except (FetchError, DataError) as exc:
        _finish_run(conn, run_id, now(), "failed", 0, 0, None, f"{type(exc).__name__}: {exc}")
        return RunSummary(run_id, source, "failed", 0, 0, 0, f"{type(exc).__name__}: {exc}")
    with _failing_run(conn, run_id, now):
        tracked = tracked_scheme_codes(conn)
        scope = {r.scheme_code for r in result.records if in_minimised_scope(r, tracked)}
        observations = _validated(result)
        with write_tx(conn):
            _store_schemes(conn, (r for r in result.records if r.scheme_code in scope), payload.retrieved_at)
        stored = _store_observations(conn, observations, run_id, lambda c: c in scope)
        pruned = prune_untracked_history(conn, tracked)
    rep = result.report
    status = "ok" if rep.rows_rejected == 0 else "partial"
    _finish_run(conn, run_id, now(), status, rep.rows_ok, rep.rows_rejected, payload.sha256, "")
    detail = f"{len(scope)} schemes in the minimised scope; {pruned} older NAVs of untracked schemes pruned"
    return RunSummary(run_id, source, status, rep.rows_ok, rep.rows_rejected, stored, detail)


ISIN_ALIAS_PREFIX = "isin.alias:"


class IsinLookupFailed(Exception):
    """AMFI's file could not be fetched or parsed, so it is UNKNOWN whether the ISINs exist (not "no match")."""


def register_schemes_by_isin(
    conn: sqlite3.Connection, fetcher: Fetcher, isins: set[str], now: Callable[[], datetime]
) -> dict[str, str]:
    """Look up ISINs the user HOLDS (e.g. from a CAS) in AMFI's current NAVAll and register those schemes.

    Exact ISIN only (payout/growth or reinvestment column) — never names. A reinvestment-option ISIN maps to the same
    AMFI scheme code as its payout ISIN, so it is recorded as an alias of that instrument. Held schemes are within the
    data-minimisation scope (AMFI ToU: keep held/watched schemes). Returns {isin: instrument_id} for those found.
    A fetch or parse failure raises :class:`IsinLookupFailed` (message: the error class only), so callers can tell
    "lookup failed, retry" apart from "no such ISIN" — nothing is guessed or registered either way."""
    wanted = {i for i in isins if i}
    if not wanted:
        return {}
    try:
        payload = fetcher.fetch(navall_request())
        result = parse_navall(payload)
    except (FetchError, DataError) as exc:
        raise IsinLookupFailed(type(exc).__name__) from exc
    found: dict[str, str] = {}
    records = []
    for rec in result.records:
        hits = {i for i in (rec.isin_growth, rec.isin_reinvest) if i and i in wanted}
        if hits:
            records.append(rec)
            for isin in hits:
                found[isin] = instrument_id(rec.scheme_code)
    if not records:
        return {}
    codes = {r.scheme_code for r in records}
    with write_tx(conn):
        _store_schemes(conn, records, payload.retrieved_at)
        for isin, iid in found.items():
            row = conn.execute("SELECT isin FROM instruments WHERE instrument_id=?", (iid,)).fetchone()
            if row is not None and row["isin"] != isin:
                conn.execute(
                    "INSERT INTO settings(key, value_json) VALUES (?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                    (ISIN_ALIAS_PREFIX + isin, json.dumps(iid)),
                )
    run_id = _start_run(conn, "amfi.navall", now())
    with _failing_run(conn, run_id, now):
        observations = _validated(result)
        stored = _store_observations(conn, observations, run_id, lambda c: c in codes)
    _finish_run(conn, run_id, now(), "ok", stored, 0, payload.sha256, "registered held schemes by ISIN")
    return found


def prune_untracked_history(conn: sqlite3.Connection, tracked: set[int]) -> int:
    """Data minimisation (AMFI ToU; source-registry §2.1; red-team RT-21): for schemes that are neither held,
    watched nor deliberately backfilled, keep ONLY the latest NAVAll observation — no growing daily archive."""
    backfilled = {
        int(r["series_id"].split(":")[1])
        for r in conn.execute("SELECT DISTINCT series_id FROM observations WHERE source_id='amfi.navhistory'")
    }
    keep = tracked | backfilled
    candidates = conn.execute(
        "SELECT o.series_id, MAX(o.observation_date) AS latest FROM observations o"
        " WHERE o.source_id='amfi.navall' AND o.series_id LIKE 'nav:%' GROUP BY o.series_id"
    ).fetchall()
    removed = 0
    with write_tx(conn):
        for r in candidates:
            if int(r["series_id"].split(":")[1]) in keep:
                continue
            # Drop older NAVAll rows for this scheme. A correction pair (old row superseded_by new row) always shares
            # one date, so this single DELETE removes both and the self-referencing FK holds at statement end. Never
            # clear superseded_by first: that re-marked the old row current beside the new one (ux_obs_current
            # breach, ECC PR-1/DB-1) and the rollback made every later prune fail the same way.
            cur = conn.execute(
                "DELETE FROM observations WHERE series_id=? AND source_id='amfi.navall' AND observation_date < ?",
                (r["series_id"], r["latest"]),
            )
            removed += cur.rowcount
    return removed


def discover_fund_house_id(
    conn: sqlite3.Connection, fetcher: Fetcher, amc_name: str, probe_day: date, max_id: int = 80,
    pause: Callable[[float], object] | None = None,
) -> int | None:  # fmt: skip
    """Find AMFI's internal fund-house id for an AMC by probing one day per id (mapping is NOT published)."""
    key = f"amfi.mf_id:{amc_name.strip().lower()}"
    row = conn.execute("SELECT value_json FROM settings WHERE key=?", (key,)).fetchone()
    if row:
        return int(row["value_json"])
    for mf_id in range(1, max_id + 1):
        try:
            payload = fetcher.fetch(navhistory_request(mf_id=mf_id, tp=1, from_date=probe_day, to_date=probe_day))
            res = parse_navhistory(payload)
        except (FetchError, DataError):
            continue
        finally:
            if pause is not None:
                pause(1.0)
        amcs = {(r.amc or "").strip().lower() for r in res.records}
        for name in amcs:
            if name:
                conn.execute(
                    "INSERT INTO settings(key, value_json) VALUES (?, ?) ON CONFLICT(key) DO NOTHING",
                    (f"amfi.mf_id:{name}", str(mf_id)),
                )
        if amc_name.strip().lower() in amcs:
            return mf_id
    return None


def backfill_history(
    conn: sqlite3.Connection,
    fetcher: Fetcher,
    *,
    scheme_code: int,
    mf_id: int,
    start: date,
    end: date,
    now: Callable[[], datetime],
    pause: Callable[[float], object] | None = None,
) -> RunSummary:
    """Fetch NAV history in ≤ 90-day windows (newest first) and keep ONLY this scheme's rows."""
    source = "amfi.navhistory"
    run_id = _start_run(conn, source, now())
    stored = ok = rej = 0
    errors: list[str] = []
    window_end = end
    with _failing_run(conn, run_id, now):
        while window_end >= start:
            window_start = max(start, window_end - timedelta(days=MAX_HISTORY_WINDOW_DAYS))
            try:
                request = navhistory_request(mf_id=mf_id, tp=1, from_date=window_start, to_date=window_end)
                res = parse_navhistory(fetcher.fetch(request))
                ok += res.report.rows_ok
                rej += res.report.rows_rejected
                mine = [o for o in res.observations if int(o.entity_key) == scheme_code]
                stored += _store_observations(conn, _validated_list(mine), run_id, lambda _c: True)
            except (FetchError, DataError) as exc:
                errors.append(f"{window_start}..{window_end}: {type(exc).__name__}")
            if pause is not None:
                pause(1.0)
            window_end = window_start - timedelta(days=1)
    status = "ok" if not errors and rej == 0 else ("partial" if stored else "failed")
    _finish_run(conn, run_id, now(), status, ok, rej, None, "; ".join(errors[:5]))
    return RunSummary(run_id, source, status, ok, rej, stored, "; ".join(errors[:5]) or "complete")


def _validated_list(observations: list[Observation]) -> list[Observation]:
    if not observations:
        return []
    observations = sorted(observations, key=lambda o: o.observation_date)
    return list(run_all(observations, expected_unit=NAV_UNIT, expected_currency=NAV_CURRENCY).observations)


def latest_freshness(conn: sqlite3.Connection, code: int, as_of: datetime) -> tuple[str, str | None]:
    """Badge of a scheme's latest NAV using the ONE shared rule (engine.freshness.nav_is_stale) → (badge, date)."""
    row = conn.execute(
        "SELECT observation_date, quality_status FROM observations WHERE series_id=? AND superseded_by IS NULL"
        " AND quality_status != 'rejected' ORDER BY observation_date DESC LIMIT 1",
        (series_id(code),),
    ).fetchone()
    if row is None:
        return "UNKNOWN", None
    if row["quality_status"] == "fixture":
        return "FIXTURE", row["observation_date"]
    observed = date.fromisoformat(row["observation_date"])
    return ("STALE" if nav_is_stale(observed, as_of.date()) else "END_OF_DAY"), row["observation_date"]
