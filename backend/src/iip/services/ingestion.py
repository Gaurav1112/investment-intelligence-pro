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

from iip.data.fetch import Fetcher, FetchError, NoData
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
from iip.store.coordination import clear_job, load_job, save_job
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


def mark_interrupted_runs(conn: sqlite3.Connection, now: datetime, *, started_before: datetime | None = None) -> int:
    """At startup no run can be in progress (one process), so any 'running' row was cut off by a crash or a stop.
    It becomes 'failed' with an explicit reason, which the 'ingestion run failed' alert picks up.

    Hosted (ADR-0013) passes ``started_before``: other instances may be running a job right now, so only runs that
    started before any live function could have are interrupted, and a resumable job's run is left alone while its
    progress row was touched within the last hour (its next call continues it and sets the final status)."""
    if started_before is None:
        cur = conn.execute(
            "UPDATE ingestion_runs SET status='failed', finished_at=?, error=? WHERE status='running'",
            (now.isoformat(), INTERRUPTED),
        )
    else:
        cur = conn.execute(
            "UPDATE ingestion_runs SET status='failed', finished_at=?, error=? WHERE status='running'"
            " AND started_at < ? AND run_id NOT IN (SELECT json_extract(state_json, '$.run_id') FROM job_progress"
            " WHERE updated_at >= ? AND json_extract(state_json, '$.run_id') IS NOT NULL)",
            (now.isoformat(), INTERRUPTED, started_before.isoformat(), (now - timedelta(hours=1)).isoformat()),
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


# AMFI fund-house ids are unpublished. A full probe on 2026-10-15 found 54 fund houses with ids up to 89 (PPFAS = 64);
# unused ids answer with AMFI's HTML form page, which the fetcher reports as NoData (no breaker failure).
MAX_FUND_HOUSE_ID = 120


def discover_fund_house_id(
    conn: sqlite3.Connection, fetcher: Fetcher, amc_name: str, probe_day: date, max_id: int = MAX_FUND_HOUSE_ID,
    pause: Callable[[float], object] | None = None,
) -> int | None:  # fmt: skip
    """Find AMFI's internal fund-house id for an AMC by probing one day per id (mapping is NOT published)."""
    cached = cached_fund_house_id(conn, amc_name)
    if cached is not None:
        return cached
    found, _next = probe_fund_house_ids(conn, fetcher, amc_name, probe_day, range(1, max_id + 1), pause=pause)
    return found


def cached_fund_house_id(conn: sqlite3.Connection, amc_name: str) -> int | None:
    row = conn.execute("SELECT value_json FROM settings WHERE key=?", (f"amfi.mf_id:{amc_name.strip().lower()}",))
    hit = row.fetchone()
    return int(hit["value_json"]) if hit else None


def probe_fund_house_ids(
    conn: sqlite3.Connection, fetcher: Fetcher, amc_name: str, probe_day: date, ids: range,
    pause: Callable[[float], object] | None = None, stop: Callable[[], bool] | None = None,
) -> tuple[int | None, int]:  # fmt: skip
    """Probe ``ids`` in order; every AMC seen is cached. Returns (the AMC's id or None, the next id to probe).
    ``stop`` (hosted, resumable) is checked AFTER each probe, so every call makes progress."""
    wanted = amc_name.strip().lower()
    for mf_id in ids:
        try:
            payload = fetcher.fetch(navhistory_request(mf_id=mf_id, tp=1, from_date=probe_day, to_date=probe_day))
            res = parse_navhistory(payload)
        except (FetchError, DataError):
            res = None
        finally:
            if pause is not None:
                pause(1.0)
        amcs = {(r.amc or "").strip().lower() for r in res.records} if res is not None else set()
        for name in amcs:
            if name:
                conn.execute(
                    "INSERT INTO settings(key, value_json) VALUES (?, ?) ON CONFLICT(key) DO NOTHING",
                    (f"amfi.mf_id:{name}", str(mf_id)),
                )
        if wanted in amcs:
            return mf_id, mf_id + 1
        if stop is not None and stop():
            return None, mf_id + 1
    return None, ids.stop


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
            w_ok, w_rej, w_stored, err = _fetch_window(
                conn, fetcher, scheme_code, mf_id, window_start, window_end, run_id
            )
            ok, rej, stored = ok + w_ok, rej + w_rej, stored + w_stored
            if err:
                errors.append(err)
            if pause is not None:
                pause(1.0)
            window_end = window_start - timedelta(days=1)
    return _finish_backfill(conn, run_id, now, ok, rej, stored, errors)


def _fetch_window(
    conn: sqlite3.Connection, fetcher: Fetcher, scheme_code: int, mf_id: int, window_start: date, window_end: date,
    run_id: str,
) -> tuple[int, int, int, str | None]:  # fmt: skip
    """One ≤ 90-day NAV-history request; keeps ONLY this scheme's rows. Returns (ok, rejected, stored, error)."""
    try:
        request = navhistory_request(mf_id=mf_id, tp=1, from_date=window_start, to_date=window_end)
        res = parse_navhistory(fetcher.fetch(request))
    except NoData:
        return 0, 0, 0, None  # AMFI has nothing in this window (e.g. before the scheme launched): empty, not an error
    except (FetchError, DataError) as exc:
        return 0, 0, 0, f"{window_start}..{window_end}: {type(exc).__name__}"
    mine = [o for o in res.observations if int(o.entity_key) == scheme_code]
    stored = _store_observations(conn, _validated_list(mine), run_id, lambda _c: True)
    return res.report.rows_ok, res.report.rows_rejected, stored, None


def _finish_backfill(
    conn: sqlite3.Connection, run_id: str, now: Callable[[], datetime], ok: int, rej: int, stored: int,
    errors: list[str],
) -> RunSummary:  # fmt: skip
    status = "ok" if not errors and rej == 0 else ("partial" if stored else "failed")
    _finish_run(conn, run_id, now(), status, ok, rej, None, "; ".join(errors[:5]))
    return RunSummary(run_id, "amfi.navhistory", status, ok, rej, stored, "; ".join(errors[:5]) or "complete")


# ----------------------------------------------------------------------------- hosted: resumable jobs (ADR-0013)
# A serverless function has a hard time limit (Vercel Hobby: 300 s). A job does a bounded amount of work per call,
# stores its progress in job_progress after every unit of work, and the client calls again until ``done``. Every call
# makes progress: the time budget is checked only AFTER at least one unit, so a stalled loop is impossible.


class FundHouseNotFound(Exception):
    """Every candidate id was probed and none lists the AMC (the job is cleared; nothing is guessed)."""


def backfill_job_key(scheme_code: int) -> str:
    return f"backfill:{scheme_code}"


def _window_count(start: date, end: date) -> int:
    n, window_end = 0, end
    while window_end >= start:
        window_end = max(start, window_end - timedelta(days=MAX_HISTORY_WINDOW_DAYS)) - timedelta(days=1)
        n += 1
    return n


def backfill_resumable(
    conn: sqlite3.Connection, fetcher: Fetcher, *, scheme_code: int, amc_name: str, start: date, end: date,
    now: Callable[[], datetime], pause: Callable[[float], object] | None, stop: Callable[[], bool],
    max_id: int = MAX_FUND_HOUSE_ID,
) -> dict[str, object]:  # fmt: skip
    """One bounded step of a NAV-history backfill (same windows, filtering and storage as :func:`backfill_history`).

    Phases: ``discovering`` (probe AMFI fund-house ids, unless cached) → ``fetching`` (newest window first) →
    ``complete`` (run finished, progress row cleared). Returns the progress, plus the run summary when complete."""
    key = backfill_job_key(scheme_code)
    state = load_job(conn, key)
    if state is None:
        state = {
            "run_id": _start_run(conn, "amfi.navhistory", now()), "scheme_code": scheme_code,
            "start": start.isoformat(), "next_end": end.isoformat(), "mf_id": cached_fund_house_id(conn, amc_name),
            "next_probe_id": 1, "probe_day": end.replace(day=1).isoformat(),
            "windows_total": _window_count(start, end), "windows_done": 0,
            "ok": 0, "rej": 0, "stored": 0, "errors": [],
        }  # fmt: skip
        save_job(conn, key, state, now().isoformat())
    run_id = str(state["run_id"])
    with _failing_run(conn, run_id, now):
        if state["mf_id"] is None:
            found, next_id = probe_fund_house_ids(
                conn, fetcher, amc_name, date.fromisoformat(str(state["probe_day"])),
                range(int(state["next_probe_id"]), max_id + 1), pause=pause, stop=stop,
            )  # fmt: skip
            state["mf_id"], state["next_probe_id"] = found, next_id
            save_job(conn, key, state, now().isoformat())
            if found is None and next_id > max_id:
                clear_job(conn, key)
                _finish_run(conn, run_id, now(), "failed", 0, 0, None, "fund-house id not found")
                raise FundHouseNotFound(amc_name)
            if found is None:
                return _progress(state, "discovering")
            if stop():
                return _progress(state, "fetching")
        first, start_d = True, date.fromisoformat(str(state["start"]))
        while (window_end := date.fromisoformat(str(state["next_end"]))) >= start_d and (first or not stop()):
            first = False
            window_start = max(start_d, window_end - timedelta(days=MAX_HISTORY_WINDOW_DAYS))
            w_ok, w_rej, w_stored, err = _fetch_window(
                conn, fetcher, scheme_code, int(str(state["mf_id"])), window_start, window_end, run_id
            )
            errors = list(state["errors"])
            if err:
                errors.append(err)
            state.update(
                ok=int(state["ok"]) + w_ok, rej=int(state["rej"]) + w_rej, stored=int(state["stored"]) + w_stored,
                errors=errors, windows_done=int(state["windows_done"]) + 1,
                next_end=(window_start - timedelta(days=1)).isoformat(),
            )  # fmt: skip
            save_job(conn, key, state, now().isoformat())
            if pause is not None:
                pause(1.0)
    if date.fromisoformat(str(state["next_end"])) >= start_d:
        return _progress(state, "fetching")
    clear_job(conn, key)
    summary = _finish_backfill(
        conn, run_id, now, int(state["ok"]), int(state["rej"]), int(state["stored"]),
        [str(e) for e in state["errors"]],
    )  # fmt: skip
    return {**_progress(state, "complete"), **summary.__dict__}


NAVALL_JOB = "navall"
NAVALL_CHUNK = 200  # schemes stored per transaction in hosted mode (each remote statement is a network round trip)


def ingest_navall_resumable(
    conn: sqlite3.Connection, fetcher: Fetcher, now: Callable[[], datetime], stop: Callable[[], bool],
    chunk: int = NAVALL_CHUNK,
) -> dict[str, object]:  # fmt: skip
    """Hosted NAVAll ingestion in bounded steps: the same scope, validation and storage as :func:`ingest_navall`,
    stored in scheme-code order, ``chunk`` schemes per transaction, progress saved after each chunk.

    The file is fetched again on each continuation (it cannot be kept between calls without storing AMFI data beyond
    the minimised scope). Storage is idempotent, so a scheme whose NAV changed between two fetches is simply
    corrected; the run records the SHA-256 of the last file read."""
    state = load_job(conn, NAVALL_JOB)
    if state is None:
        state = {"run_id": _start_run(conn, "amfi.navall", now()), "next_code": 0, "stored": 0}
        save_job(conn, NAVALL_JOB, state, now().isoformat())
    run_id = str(state["run_id"])
    try:
        payload = fetcher.fetch(navall_request())
        result = parse_navall(payload)
    except (FetchError, DataError) as exc:
        clear_job(conn, NAVALL_JOB)
        _finish_run(conn, run_id, now(), "failed", 0, 0, None, f"{type(exc).__name__}: {exc}")
        summary = RunSummary(run_id, "amfi.navall", "failed", 0, 0, 0, f"{type(exc).__name__}: {exc}")
        return {"done": True, "phase": "complete", "schemes_done": 0, "schemes_total": 0, **summary.__dict__}
    with _failing_run(conn, run_id, now):
        tracked = tracked_scheme_codes(conn)
        scope = sorted({r.scheme_code for r in result.records if in_minimised_scope(r, tracked)})
        by_code: dict[int, list[Observation]] = {}
        for o in _validated(result):
            by_code.setdefault(int(o.entity_key), []).append(o)
        records = {r.scheme_code: r for r in result.records}
        first = True
        while (todo := [c for c in scope if c > int(str(state["next_code"]))]) and (first or not stop()):
            first = False
            part = todo[:chunk]
            with write_tx(conn):
                _store_schemes(conn, (records[c] for c in part), payload.retrieved_at)
            wanted = set(part)
            obs = [o for c in part for o in by_code.get(c, [])]
            stored = _store_observations(conn, obs, run_id, wanted.__contains__)
            state.update(next_code=part[-1], stored=int(str(state["stored"])) + stored)
            save_job(conn, NAVALL_JOB, state, now().isoformat())
        done_count = len([c for c in scope if c <= int(str(state["next_code"]))])
        if done_count < len(scope):
            return {"done": False, "phase": "storing", "schemes_done": done_count, "schemes_total": len(scope)}
        pruned = prune_untracked_history(conn, tracked)
    clear_job(conn, NAVALL_JOB)
    rep = result.report
    status = "ok" if rep.rows_rejected == 0 else "partial"
    _finish_run(conn, run_id, now(), status, rep.rows_ok, rep.rows_rejected, payload.sha256, "")
    detail = f"{len(scope)} schemes in the minimised scope; {pruned} older NAVs of untracked schemes pruned"
    summary = RunSummary(run_id, "amfi.navall", status, rep.rows_ok, rep.rows_rejected, int(str(state["stored"])),
                         detail)  # fmt: skip
    return {"done": True, "phase": "complete", "schemes_done": len(scope), "schemes_total": len(scope),
            **summary.__dict__}  # fmt: skip


def _progress(state: dict[str, object], phase: str) -> dict[str, object]:
    return {
        "done": phase == "complete", "phase": phase,
        "windows_done": state["windows_done"], "windows_total": state["windows_total"],
    }  # fmt: skip


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
