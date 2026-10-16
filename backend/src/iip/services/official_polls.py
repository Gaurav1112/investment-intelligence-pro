"""The J2 official-source polls (PLAN B03; the A07 adapters; audit-automation.md §3.1-3.2): RBI T-bill cut-offs from
RBI's press-release RSS feed and MoSPI's CPI (base 2024, All India, Combined, general index).

Both sources are official and the registry rows say automated fetching is permitted for personal use. Each poll:

* is **conditional**: the T-bill feed is fetched with ``If-Modified-Since`` from the last feed seen, an unchanged feed
  (same SHA-256) is a no-op, and a release already handled (stored or abstained) is never parsed or fetched again.
  The fetch layer sends no ``If-None-Match`` (it has no ETag support), so the payload hash stands in for the ETag.
  The CPI poll asks for one month at a time and only when that month is due (audit-automation.md §3.1 step 6);
  a payload identical to the last one seen for the month is a no-op;
* stores releases as observations with their provenance (source, URL, retrieval time, payload hash, release date,
  convention). The T-bill press-release reference, date basis and plain-text citation are kept per release in the
  poll's state (:func:`tbill_provenance`);
* **abstains** rather than guesses: the T-bill self-check ``(100 − P) / P × 365 / days`` must reproduce every
  published yield (``parsers.rbi_pr``), and a CPI response must hold exactly one All-India / Combined / general-index
  record (``data.mospi``). Nothing from a refused release is stored;
* sends the fetch layer's honest user-agent and no credentials;
* returns an honest :class:`PollOutcome` (``done`` when something was stored, ``noop`` when there was nothing new,
  ``failed`` when a fetch failed or a release was refused) carrying codes and counts only (C-13), and writes an
  ``ingestion_runs`` row for Data health whenever it stored or failed.

The clock is the caller's (``now``); nothing here runs in the engine.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal

from pydantic import ValidationError

from iip.data import mospi
from iip.data.fetch import Fetcher, FetchError
from iip.data.models import DataError, FetchRefused, RawPayload
from iip.data.parsers.rbi_pr import TbillCutoffRelease
from iip.data.rbi_tbill import PAGE_SOURCE_ID, TbillPoll, poll_tbill_cutoffs
from iip.data.registry import mospi_cpi_request, rbi_press_release_request
from iip.services import ingestion, inputs
from iip.store import coordination
from iip.store.db import write_tx
from iip.store.observations import ObservationRow, UpsertOutcome, upsert_observation

IST = timezone(timedelta(hours=5, minutes=30), "IST")
TBILL_STATE = "poll:rbi.tbill"  # {"last_modified", "sha256", "releases": {prid: provenance}}
CPI_STATE = "poll:mospi.cpi"  # {"months": {"YYYY-MM": sha256}}
TBILL_SOURCE = PAGE_SOURCE_ID  # "rbi.pr.tbill": the source the yields are stored under (cron.POLL_SOURCES)
CPI_SOURCE = "mospi.cpi"
# PARAMETER: the CPI base polled. Base 2024 is MoSPI's current series (data.mospi; base 2012 is not spliced onto it).
CPI_BASE_YEAR = 2024
# PARAMETER: MoSPI releases month M-1 on the 12th of month M at 16:00 IST (source-registry §2.12).
CPI_RELEASE_DAY = 12
CPI_RELEASE_TIME_IST = time(16, 0)
# How many releases / months of poll state are kept (enough to cover the feed's ~10 items and a few CPI revisions).
KEEP_RELEASES = 60
KEEP_MONTHS = 6

PollState = Literal["done", "noop", "failed"]


@dataclass(frozen=True)
class PollOutcome:
    """What one poll did. Codes and integer counts only; never a value, a name or a URL (C-13)."""

    state: PollState
    code: str
    counts: dict[str, int] = field(default_factory=dict)

    def as_counts(self) -> dict[str, int]:
        return dict(self.counts)


# ----------------------------------------------------------------------------------------------------- shared


def _record_run(
    conn: sqlite3.Connection, source_id: str, now: datetime, status: str, ok: int, rejected: int,
    sha: str | None, error: str | None,
) -> None:  # fmt: skip
    """One finished ``ingestion_runs`` row, so Data health's last run and the ingestion-failure alert show the poll."""
    run_id = f"run_{now.strftime('%Y%m%dT%H%M%SZ')}_{secrets.token_hex(4)}"
    with write_tx(conn):
        conn.execute(
            "INSERT INTO ingestion_runs(run_id, source_id, started_at, finished_at, status, rows_ok, rows_rejected,"
            " raw_sha256, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, source_id, now.isoformat(), now.isoformat(), status, ok, rejected, sha,
             None if error is None else error[:200]),
        )  # fmt: skip


def _fetch_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    return str(code) if isinstance(code, str) and code else type(exc).__name__


def _save_state(conn: sqlite3.Connection, key: str, state: dict[str, Any], now: datetime) -> None:
    with write_tx(conn):
        coordination.save_job(conn, key, state, now.isoformat())


# ----------------------------------------------------------------------------------------------------- RBI T-bill


def tbill_provenance(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """Per release id: what the poll did with it, the press-release reference, the date basis and the citation."""
    state = coordination.load_job(conn, TBILL_STATE) or {}
    return dict(state.get("releases") or {})


def _store_release(conn: sqlite3.Connection, rel: TbillCutoffRelease, poll: TbillPoll) -> tuple[int, int]:
    """The three yields of one self-checked release as observations. Returns (stored, unchanged)."""
    assert poll.feed_sha256 is not None and poll.feed_retrieved_at is not None
    observed = (rel.auction_date or rel.release_date).isoformat()
    url = rbi_press_release_request(prid=rel.prid).url  # stored for traceability; shown as plain text (no deep link)
    stored = unchanged = 0
    for y in rel.yields:
        outcome = upsert_observation(conn, ObservationRow(
            series_id=y.series_id, kind="yield", value=format(y.yield_fraction, "f"), unit="fraction", currency=None,
            observation_date=observed, retrieved_at=poll.feed_retrieved_at.isoformat(), source_id=TBILL_SOURCE,
            source_url=url, quality_status="ok", raw_sha256=poll.feed_sha256, convention=rel.convention,
            publication_time=rel.release_date.isoformat(),
        ))  # fmt: skip
        if outcome is UpsertOutcome.UNCHANGED:
            unchanged += 1
        else:
            stored += 1
    return stored, unchanged


def _provenance(rel: TbillCutoffRelease) -> dict[str, Any]:
    auction = None if rel.auction_date is None else rel.auction_date.isoformat()
    return {
        "outcome": "stored", "press_release_ref": rel.press_release_ref, "release_date": rel.release_date.isoformat(),
        "date_basis": rel.date_basis, "auction_date": auction, "citation_text": rel.citation_text, "self_check": "PASS",
    }  # fmt: skip


def _trim(releases: Mapping[str, Any]) -> dict[str, Any]:
    keep = sorted(releases, key=int)[-KEEP_RELEASES:]
    return {k: releases[k] for k in keep}


def poll_rbi_tbill(conn: sqlite3.Connection, fetcher: Fetcher, now: Callable[[], datetime]) -> PollOutcome:
    """One conditional poll of RBI's press-release feed for T-bill cut-off results (J2 step ``rbi.tbill``)."""
    ingestion.sync_sources(conn)  # observations and runs reference the stored registry
    state = coordination.load_job(conn, TBILL_STATE) or {}
    releases: dict[str, Any] = dict(state.get("releases") or {})
    last_modified = datetime.fromisoformat(str(state["last_modified"])) if state.get("last_modified") else None
    try:
        poll = poll_tbill_cutoffs(
            fetcher, if_modified_since=last_modified, known_prids=frozenset(int(p) for p in releases)
        )
    except FetchError as exc:
        code = f"FETCH_FAILED:{_fetch_code(exc)}"
        _record_run(conn, TBILL_SOURCE, now(), "failed", 0, 0, None, code)
        return PollOutcome("failed", code)
    except (DataError, FetchRefused) as exc:
        code = f"FEED_REFUSED:{_fetch_code(exc)}"
        _record_run(conn, TBILL_SOURCE, now(), "failed", 0, 0, None, code)
        return PollOutcome("failed", code)

    if poll.status == "NOT_MODIFIED":
        return PollOutcome("noop", "NOT_MODIFIED")
    if poll.feed_sha256 is not None and poll.feed_sha256 == state.get("sha256"):
        return PollOutcome("noop", "UNCHANGED")

    stored = unchanged = 0
    for rel in poll.releases:
        s, u = _store_release(conn, rel, poll)
        stored, unchanged = stored + s, unchanged + u
        releases[str(rel.prid)] = _provenance(rel)
    for ab in poll.abstentions:
        releases[str(ab.prid)] = {"outcome": f"abstained:{ab.code}"}
    _save_state(conn, TBILL_STATE, {
        "last_modified": None if poll.feed_last_modified is None else poll.feed_last_modified.isoformat(),
        "sha256": poll.feed_sha256, "releases": _trim(releases),
    }, now())  # fmt: skip

    counts = {"releases": len(poll.releases), "stored": stored, "unchanged": unchanged,
              "abstained": len(poll.abstentions), "page_requests": poll.page_requests}  # fmt: skip
    if poll.abstentions:
        first = sorted(ab.code for ab in poll.abstentions)[0]
        if stored == 0:
            code = f"ABSTAINED:{first}"
            _record_run(conn, TBILL_SOURCE, now(), "failed", 0, len(poll.abstentions), poll.feed_sha256, code)
            return PollOutcome("failed", code, counts)
        _record_run(conn, TBILL_SOURCE, now(), "partial", stored, len(poll.abstentions), poll.feed_sha256,
                    f"ABSTAINED:{first}")  # fmt: skip
        return PollOutcome("done", "STORED_WITH_ABSTENTIONS", counts)
    if stored:
        _record_run(conn, TBILL_SOURCE, now(), "ok", stored, 0, poll.feed_sha256, None)
        return PollOutcome("done", "STORED", counts)
    if poll.releases:
        return PollOutcome("noop", "UNCHANGED", counts)
    return PollOutcome("noop", "NO_NEW_CUTOFF" if poll.skipped_known else "NO_CUTOFF_IN_FEED", counts)


# ----------------------------------------------------------------------------------------------------- MoSPI CPI


def _month_before(d: date) -> date:
    first = d.replace(day=1)
    return (first - timedelta(days=1)).replace(day=1)


def cpi_targets(now: datetime, stored: Callable[[date], bool]) -> list[date]:
    """The months to ask MoSPI for now (first day of each), newest first (audit-automation.md §3.1 step 6).

    From the 12th at 16:00 IST month M-1 is due: ask for it until it is stored, and while it has not appeared re-check
    M-2 for revisions. Before that, re-check M-2 only. Once M-1 is stored nothing is asked until next month.
    """
    local = now.astimezone(IST)
    m1 = _month_before(local.date())
    m2 = _month_before(m1)
    release = datetime.combine(local.date().replace(day=CPI_RELEASE_DAY), CPI_RELEASE_TIME_IST, IST)
    if local >= release:
        return [] if stored(m1) else [m1, m2]
    return [m2]


def _cpi_stored(conn: sqlite3.Connection, month: date) -> bool:
    row = conn.execute(
        "SELECT 1 FROM observations WHERE series_id=? AND observation_date=? AND source_id=? AND superseded_by IS NULL"
        " LIMIT 1",
        (inputs.cpi_series_id(str(CPI_BASE_YEAR)), month.isoformat(), CPI_SOURCE),
    ).fetchone()
    return row is not None


def _no_rows(payload: RawPayload) -> bool:
    """MoSPI answers a month it has not published with an empty ``data`` list (and no usable meta_data)."""
    try:
        doc = json.loads(payload.content)
    except ValueError:
        return False
    return isinstance(doc, dict) and doc.get("data") == []


@dataclass
class _CpiTally:
    requests: int = 0
    stored: int = 0
    unchanged: int = 0
    codes: list[str] = field(default_factory=list)
    stored_sha: str | None = None  # payload hash of the newest stored month (the run row's raw_sha256)


def _cpi_month(
    conn: sqlite3.Connection, fetcher: Fetcher, now: datetime, month: date, seen: dict[str, str], tally: _CpiTally
) -> PollOutcome | None:
    """Fetch and store one month. Returns a failed outcome to stop, or None (the tally carries what happened)."""
    key = month.strftime("%Y-%m")
    tally.requests += 1
    try:
        payload = fetcher.fetch(mospi_cpi_request(base_year=CPI_BASE_YEAR, year=month.year, month=month.month))
    except (FetchError, FetchRefused, DataError) as exc:
        return PollOutcome("failed", f"FETCH_FAILED:{_fetch_code(exc)}")
    if _no_rows(payload):
        tally.codes.append("NOT_PUBLISHED")
        return None
    if seen.get(key) == payload.sha256:
        tally.unchanged += 1
        tally.codes.append("UNCHANGED")
        return None
    try:
        rec = mospi.parse_cpi_month(payload, base_year=CPI_BASE_YEAR, year=month.year, month=month.month)
        out = inputs.store_mospi_record(conn, rec, now)
    except mospi.MospiError as exc:
        return PollOutcome("failed", f"REFUSED:{exc.code}")
    except DataError as exc:  # SchemaChanged and kin: nothing stored
        return PollOutcome("failed", f"REFUSED:{_fetch_code(exc)}")
    except (ValidationError, inputs.InputError):
        return PollOutcome("failed", "REFUSED:INVALID_RECORD")
    seen[key] = payload.sha256
    if out["outcome"] == UpsertOutcome.UNCHANGED.value:
        tally.unchanged += 1
        tally.codes.append("UNCHANGED")
    else:
        tally.stored += 1
        tally.codes.append("STORED")
        tally.stored_sha = tally.stored_sha or payload.sha256
    return None


def poll_mospi_cpi(conn: sqlite3.Connection, fetcher: Fetcher, now: Callable[[], datetime]) -> PollOutcome:
    """Ask MoSPI for the CPI months that are due (J2 step ``mospi.cpi``). No credentials are ever sent."""
    ingestion.sync_sources(conn)
    at = now()
    targets = cpi_targets(at, lambda m: _cpi_stored(conn, m))
    if not targets:
        return PollOutcome("noop", "UP_TO_DATE", {"requests": 0, "stored": 0, "unchanged": 0})
    state = coordination.load_job(conn, CPI_STATE) or {}
    seen: dict[str, str] = {str(k): str(v) for k, v in dict(state.get("months") or {}).items()}
    tally = _CpiTally()
    failure: PollOutcome | None = None
    for i, month in enumerate(targets):
        failure = _cpi_month(conn, fetcher, at, month, seen, tally)
        if failure is not None:
            break
        if i == 0 and tally.codes[-1] == "STORED":
            break  # the due month arrived: the month before needs no re-check today
    keep = sorted(seen)[-KEEP_MONTHS:]
    _save_state(conn, CPI_STATE, {"months": {k: seen[k] for k in keep}}, at)
    counts = {"requests": tally.requests, "stored": tally.stored, "unchanged": tally.unchanged}
    if failure is not None:
        _record_run(conn, CPI_SOURCE, at, "failed", tally.stored, 1, None, failure.code)
        return PollOutcome("failed", failure.code, counts)
    if tally.stored:
        _record_run(conn, CPI_SOURCE, at, "ok", tally.stored, 0, tally.stored_sha, None)
        return PollOutcome("done", "STORED", counts)
    return PollOutcome("noop", tally.codes[0], counts)


__all__ = [
    "CPI_BASE_YEAR",
    "PollOutcome",
    "cpi_targets",
    "poll_mospi_cpi",
    "poll_rbi_tbill",
    "tbill_provenance",
]
