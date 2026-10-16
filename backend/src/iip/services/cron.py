"""Scheduled jobs J1-J5 (PLAN B03; design-risk-first.md §9, design-evidence-first.md §8.2, research-automation-infra.md
§4). Hosted production only: the route that calls this module exists behind the cron bearer exception (A03), and the
crons in vercel.json stay disabled until the user sets ``CRON_SECRET``.

Every job is ONE resumable step of at most :data:`STEP_LIMIT_S` seconds that works out what is outstanding from the
database, so a missed or skipped day is caught up by the next call:

* **J1 ``navall``** - a cheap conditional fetch of NAVAll (``If-Modified-Since`` from the last success, and the payload
  hash), THEN the run key (the newest NAV date in the file, never the wall clock), THEN the claim, then one bounded
  storage step. Duplicate deliveries may both fetch (accepted: one extra GET); only one wins the claim.
* **J2 ``navall-continue``** - finishes an open NAVAll run, or catches up a missed J1; then the optional data polls
  (RBI T-bill RSS, MoSPI CPI) when their service steps exist.
* **J3 ``history``** - gap-fills NAV history for held and watched schemes (U-01: the hosted store keeps nothing else)
  in bounded windows since the last success, then refreshes ``series_grid`` for the schemes that changed.
* **J4 ``snapshot``** - a late-NAV re-run (FoF/overseas NAVs land by T+1 10:00 IST), then the risk snapshot step
  (WP B02), then a ping in the outbox only when the L1-L5 card set changed.
* **J5 ``watchdog``** - one "pipeline needs attention" ping when the expected snapshot is missing or NAVs are stale.

Idempotency (design-risk-first.md §9.3): ``cron_runs`` holds one row per (job, run_key); the claim is ONE conditional
statement that also takes over a ``failed`` row or a ``running`` row older than :data:`CLAIM_STALE_S` (a killed
function), so a duplicate delivery of finished or live work is a no-op. The outbox reaper marks ``sending`` rows older
than :data:`OUTBOX_LEASE_S` as ``failed`` and never resends them (losing a ping is the safe direction).

Steps owned by other packages are looked up by name (:func:`default_hooks`); a step that is not built yet fails closed
with a ``*_NOT_IMPLEMENTED`` code and never invents data. Results carry codes and counts only - never amounts, names
or holdings (C-13).
"""

from __future__ import annotations

import importlib
import logging
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, cast

from iip.data.fetch import Fetcher, FetchError, FetchFailed, NotModified
from iip.data.models import DataError, RawPayload
from iip.data.parsers.amfi_navall import parse_navall
from iip.data.registry import SourceRequest, navall_request
from iip.engine.errors import EngineError
from iip.engine.freshness import nav_is_stale, weekdays_between
from iip.engine.stats.series_grid import month_end_grid
from iip.services import ingestion
from iip.store import coordination, ledger

log = logging.getLogger("iip.cron")

JOBS: tuple[str, ...] = ("navall", "navall-continue", "history", "snapshot", "watchdog")
# Vercel Hobby: 300 s function limit; steps that answered reliably were <= 98 s (app.HOSTED_JOB_BUDGET_S history).
STEP_LIMIT_S = 90.0
# A 'running' claim older than this was killed with its function (300 s limit + margin; = the DbLease TTL).
CLAIM_STALE_S = 330.0
# A 'sending' outbox row older than this is reaped to 'failed' and never resent (design-evidence-first.md §8.2).
OUTBOX_LEASE_S = 600.0
# PARAMETER: the history gap fill never reaches further back than this (two 90-day AMFI windows per fund house).
# Older holes are a user-started backfill, not a daily job.
GAP_FILL_MAX_DAYS = 120
# J4 spends at most this share of its step on the late-NAV re-run, so the snapshot always gets time.
LATE_NAV_SHARE = 0.5
OUTBOX_DRAIN_LIMIT = 20
IST = timezone(timedelta(hours=5, minutes=30), "IST")

# job_progress keys owned by this module (never collide with ingestion's 'navall', 'navall:stage:*', 'backfill*').
NAVALL_OPEN = "cron:navall:open"  # {"run_key", "late", "sha256", "last_modified"} while a cron NAVAll run is open
NAVALL_LAST = "cron:navall:last"  # validator of the last stored NAVAll: {"run_key", "sha256", "last_modified"}
HISTORY_OPEN = "cron:history:open"  # {"run_key"} while a cron gap-fill batch is open
HISTORY_LAST = "cron:history:last"  # {"run_key"} of the last successful gap fill

_NAV_QUALITY = "quality_status NOT IN ('rejected', 'fixture')"


class Lock(Protocol):
    def acquire(self, blocking: bool = ...) -> bool: ...
    def release(self) -> None: ...


@dataclass(frozen=True)
class SnapshotOutcome:
    """What the risk-snapshot step (WP B02) reports back: identifiers and codes only."""

    snapshot_id: str
    as_of_date: str
    verdict: str
    card_set_hash: str
    written: bool


SnapshotStep = Callable[[sqlite3.Connection, datetime], SnapshotOutcome]
PollStep = Callable[[sqlite3.Connection, Fetcher, Callable[[], datetime]], Mapping[str, int]]
PingSender = Callable[[sqlite3.Row], None]


@dataclass(frozen=True)
class CronHooks:
    """Steps that other packages provide. ``None`` = not built yet: that step fails closed with a code.

    * ``navall_scope_enforced`` - U-01: the hosted NAVAll storage keeps held and watched schemes only. Until the
      ingestion service says so, J1/J2/J4 do not store NAVAll hosted at all (``U01_SCOPE_NOT_ENFORCED``).
    * ``channels`` - notification channels switched on (``IIP_NOTIFY=off`` → none: no outbox row is ever written).
    """

    snapshot: SnapshotStep | None = None
    polls: tuple[tuple[str, PollStep | None], ...] = ()
    channels: tuple[str, ...] = ()
    sender: PingSender | None = None
    navall_scope_enforced: bool = False


@dataclass
class CronResult:
    job: str
    state: str  # done | noop | partial | failed
    code: str
    run_key: str | None = None
    counts: dict[str, int] = field(default_factory=dict)
    steps: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "job": self.job, "state": self.state, "code": self.code, "run_key": self.run_key,
            "counts": dict(sorted(self.counts.items())), "steps": dict(sorted(self.steps.items())),
        }  # fmt: skip


@dataclass
class CronContext:
    conn: sqlite3.Connection
    fetcher: Callable[[], Fetcher]
    now: Callable[[], datetime]  # aware UTC; only this layer reads the clock
    monotonic: Callable[[], float]
    budget_s: float
    navall_lock: Lock
    backfill_lock: Lock
    pause: Callable[[float], object] | None
    hooks: CronHooks
    _deadline: float = 0.0

    def start(self) -> None:
        self._deadline = self.monotonic() + max(0.0, min(self.budget_s, STEP_LIMIT_S))

    def remaining(self) -> float:
        return self._deadline - self.monotonic()

    def now_iso(self) -> str:
        return self.now().isoformat()

    def stale_before(self) -> str:
        return (self.now() - timedelta(seconds=CLAIM_STALE_S)).isoformat()

    def ist_today(self) -> date:
        return self.now().astimezone(IST).date()


# ----------------------------------------------------------------------------------------------------- hooks


def _optional(module: str, attr: str) -> Any:
    """``module.attr`` if that package has landed, else None (a missing step is reported, never faked)."""
    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError as exc:
        if exc.name == module:
            return None
        raise
    return getattr(mod, attr, None)


def default_hooks() -> CronHooks:
    """Resolve the steps owned by other work packages by their agreed names (see the B03 hand-over notes)."""
    enabled = _optional("iip.services.notify", "enabled_channels")
    channels = tuple(str(c) for c in enabled()) if callable(enabled) else ()
    return CronHooks(
        snapshot=_optional("iip.services.risk_snapshot", "cron_snapshot_step"),
        polls=(
            ("rbi.tbill", _optional("iip.services.ingestion", "poll_rbi_tbill")),
            ("mospi.cpi", _optional("iip.services.ingestion", "check_mospi_cpi")),
        ),
        channels=channels,
        sender=_optional("iip.services.notify", "send_ping") if channels else None,
        navall_scope_enforced=getattr(ingestion, "HOSTED_NAVALL_SCOPE", None) == "held_watched",
    )


# ----------------------------------------------------------------------------------------------------- entry


def run_job(ctx: CronContext, job: str) -> CronResult:
    """Run one bounded step of ``job``. Raises ``ValueError`` for a job outside the fixed set."""
    if job not in JOBS:
        raise ValueError("unknown job")
    ctx.start()
    handler = _HANDLERS[job]
    try:
        return handler(ctx)
    except Exception as exc:  # the class only: messages can carry values (C-13)
        log.error("cron job failed job=%s type=%s", job, type(exc).__name__)
        _rollback(ctx.conn)
        return CronResult(job, "failed", "INTERNAL_ERROR")


def _rollback(conn: sqlite3.Connection) -> None:
    try:
        if conn.in_transaction:
            conn.rollback()
    except sqlite3.Error:  # best effort on a failure path
        pass


# ----------------------------------------------------------------------------------------------------- claims


def _claim(ctx: CronContext, job: str, run_key: str) -> bool:
    return ledger.claim_cron_run(ctx.conn, job, run_key, ctx.now_iso(), ctx.stale_before())


def _finish(ctx: CronContext, job: str, run_key: str, state: str, code: str) -> None:
    ledger.finish_cron_run(ctx.conn, job, run_key, state, ctx.now_iso(), code[:200])


def _run_state(conn: sqlite3.Connection, job: str, run_key: str) -> str | None:
    row = conn.execute("SELECT state FROM cron_runs WHERE job=? AND run_key=?", (job, run_key)).fetchone()
    return None if row is None else str(row["state"])


def newest_nav_date(conn: sqlite3.Connection) -> str | None:
    """The newest stored NAV date (the data's as-of, never the wall clock)."""
    row = conn.execute(
        "SELECT MAX(observation_date) AS d FROM observations"  # noqa: S608 - a module constant, no input
        f" WHERE kind='nav' AND superseded_by IS NULL AND {_NAV_QUALITY}"
    ).fetchone()
    return None if row is None or row["d"] is None else str(row["d"])


# ----------------------------------------------------------------------------------------------------- NAVAll


class _Prefetched:
    """Hands the payload fetched for the run key to the ingestion step, so a claimed run fetches NAVAll once.
    Without a payload (continuing a staged run) any fetch is refused: continuations never fetch."""

    def __init__(self, payload: RawPayload | None) -> None:
        self._payload = payload

    def fetch(self, request: SourceRequest, force: bool = False) -> RawPayload:
        if self._payload is None or request.source.id != self._payload.source_id:
            raise FetchFailed("continuation steps make no request", code="NO_REFETCH", retryable=False)
        return self._payload


def _data_date(payload: RawPayload, today: date) -> str | None:
    """Run key of a NAVAll payload: the newest NAV date in it that is not after today (IST)."""
    parsed = parse_navall(payload)
    dates = [o.observation_date for o in parsed.observations if o.observation_date <= today]
    return max(dates).isoformat() if dates else None


def _navall_pass(ctx: CronContext, owner: str, remaining: Callable[[], float]) -> CronResult:
    """One bounded NAVAll step for J1, J2 (catch-up/continue) or J4 (late NAVs). Codes and counts only."""
    if not ctx.hooks.navall_scope_enforced:
        return CronResult(owner, "failed", "U01_SCOPE_NOT_ENFORCED")
    if not ctx.navall_lock.acquire(blocking=False):
        return CronResult(owner, "noop", "NAVALL_BUSY")
    try:
        if coordination.load_job(ctx.conn, ingestion.NAVALL_JOB) is not None:
            return _store_navall(ctx, owner, None, remaining)  # an open run: continue it, no fetch, no new claim
        last = coordination.load_job(ctx.conn, NAVALL_LAST) or {}
        request = navall_request()
        if last.get("last_modified"):
            request = replace(request, if_modified_since=datetime.fromisoformat(str(last["last_modified"])))
        try:
            payload = ctx.fetcher().fetch(request)
        except NotModified:
            return CronResult(owner, "noop", "NOT_MODIFIED", last.get("run_key"))
        except (FetchError, DataError) as exc:
            return CronResult(owner, "failed", f"FETCH_FAILED:{getattr(exc, 'code', type(exc).__name__)}")
        if payload.sha256 == last.get("sha256"):
            return CronResult(owner, "noop", "UNCHANGED", last.get("run_key"))
        try:
            run_key = _data_date(payload, ctx.ist_today())
        except DataError:
            return CronResult(owner, "failed", "PARSE_FAILED")
        if run_key is None:
            return CronResult(owner, "failed", "NO_DATA")
        late = False
        if not _claim(ctx, "navall", run_key):
            # A finished run for this NAV date: only J4 re-stores it (late FoF/overseas NAVs; upserts are idempotent).
            if owner == "snapshot" and _run_state(ctx.conn, "navall", run_key) in ("done", "noop"):
                late = True
            else:
                return CronResult(owner, "noop", "DUPLICATE", run_key)
        ingestion.sync_sources(ctx.conn)  # the ingestion run row references the source registry
        modified = payload.last_modified.isoformat() if payload.last_modified else None
        coordination.save_job(ctx.conn, NAVALL_OPEN, {
            "run_key": run_key, "late": late, "sha256": payload.sha256, "last_modified": modified,
        }, ctx.now_iso())  # fmt: skip
        return _store_navall(ctx, owner, payload, remaining)
    finally:
        ctx.navall_lock.release()


def _store_navall(
    ctx: CronContext, owner: str, payload: RawPayload | None, remaining: Callable[[], float]
) -> CronResult:
    opened = coordination.load_job(ctx.conn, NAVALL_OPEN)
    run_key = str(opened["run_key"]) if opened else None
    try:
        out = ingestion.ingest_navall_resumable(
            ctx.conn, cast(Fetcher, _Prefetched(payload)), ctx.now, remaining, monotonic=ctx.monotonic
        )
    except BaseException:
        # ingestion cleared its staging; forget our marker too, so it never labels a later (e.g. manual) run. The
        # claim stays 'running' and is taken over once stale.
        _rollback(ctx.conn)
        coordination.clear_job(ctx.conn, NAVALL_OPEN)
        raise
    counts = {"schemes_done": int(str(out.get("schemes_done") or 0)),
              "schemes_total": int(str(out.get("schemes_total") or 0))}  # fmt: skip
    if not out.get("done"):
        return CronResult(owner, "partial", "NAVALL_STORING", run_key, counts)
    coordination.clear_job(ctx.conn, NAVALL_OPEN)
    status = str(out.get("status"))
    counts["rows_ok"] = int(str(out.get("rows_ok") or 0))
    counts["rows_rejected"] = int(str(out.get("rows_rejected") or 0))
    if status not in ("ok", "partial"):
        if run_key is not None:
            _finish(ctx, "navall", run_key, "failed", "INGEST_FAILED")
        return CronResult(owner, "failed", "INGEST_FAILED", run_key, counts)
    code = "STORED" if status == "ok" else "STORED_WITH_REJECTS"
    if opened is not None and run_key is not None:
        coordination.save_job(ctx.conn, NAVALL_LAST, {
            "run_key": run_key, "sha256": opened.get("sha256"), "last_modified": opened.get("last_modified"),
        }, ctx.now_iso())  # fmt: skip
        if not opened.get("late"):
            _finish(ctx, "navall", run_key, "done", code)
        else:
            code = "LATE_NAVS_STORED"
    return CronResult(owner, "done", code, run_key, counts)


def _j1_navall(ctx: CronContext) -> CronResult:
    return _navall_pass(ctx, "navall", ctx.remaining)


# ----------------------------------------------------------------------------------------------------- J2


def _j2_continue(ctx: CronContext) -> CronResult:
    """Finish an open NAVAll run or catch up a missed J1; then the optional polls, once per NAV date."""
    nav = _navall_pass(ctx, "navall-continue", ctx.remaining)
    result = CronResult("navall-continue", nav.state, nav.code, nav.run_key, dict(nav.counts), {"navall": nav.code})
    if nav.state == "partial":
        return result  # the step is spent on NAVAll; the polls run once it is complete
    run_key = newest_nav_date(ctx.conn)
    if run_key is None:
        return result
    result.run_key = run_key
    if not _claim(ctx, "navall-continue", run_key):
        result.steps["polls"] = "DUPLICATE"
        if nav.state != "failed":
            result.state, result.code = "noop", "DUPLICATE"
        return result
    failed = nav.state == "failed"
    for name, step in ctx.hooks.polls:
        if step is None:
            result.steps[name] = "NOT_IMPLEMENTED"
            continue
        try:
            for k, v in step(ctx.conn, ctx.fetcher(), ctx.now).items():
                result.counts[f"{name}.{k}"] = int(v)
            result.steps[name] = "OK"
        except Exception as exc:  # class only (C-13); the next day's J2 tries again
            log.warning("cron poll failed step=%s type=%s", name, type(exc).__name__)
            _rollback(ctx.conn)
            result.steps[name] = "FAILED"
            failed = True
    detail = ";".join(f"{k}={v}" for k, v in sorted(result.steps.items()))
    _finish(ctx, "navall-continue", run_key, "failed" if failed else "done", detail)
    if failed:
        result.state = "failed"
        if nav.state != "failed":
            result.code = "POLL_FAILED"
    elif nav.state == "noop":
        result.state = "done"
    return result


# ----------------------------------------------------------------------------------------------------- J3


def _latest_per_code(conn: sqlite3.Connection, codes: list[int]) -> dict[int, str]:
    out: dict[int, str] = {}
    for part in ledger.chunks(codes, ledger.MAX_PARAMS):
        rows = conn.execute(
            "SELECT series_id, MAX(observation_date) AS d FROM observations"  # noqa: S608 - placeholders only
            f" WHERE series_id IN ({','.join('?' * len(part))}) AND superseded_by IS NULL AND {_NAV_QUALITY}"
            " GROUP BY series_id",
            [ingestion.series_id(c) for c in part],
        ).fetchall()
        for r in rows:
            out[int(str(r["series_id"]).removeprefix("nav:"))] = str(r["d"])
    return out


def _amc_groups(conn: sqlite3.Connection, codes: list[int]) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = {}
    for part in ledger.chunks(codes, ledger.MAX_PARAMS):
        rows = conn.execute(
            "SELECT i.amfi_code, m.amc FROM instruments i JOIN mf_schemes m USING(instrument_id)"  # noqa: S608
            f" WHERE i.amfi_code IN ({','.join('?' * len(part))})",
            [str(c) for c in part],
        ).fetchall()
        for r in rows:
            if str(r["amc"]).strip():
                groups.setdefault(str(r["amc"]), []).append(int(r["amfi_code"]))
    return groups


def gap_window(latest: Mapping[int, str], last_success: str | None, run_key: str) -> tuple[date, date] | None:
    """The history window to fill, or None. It starts after the last successful gap fill (first run: after the
    oldest newest-NAV among the schemes), is capped at :data:`GAP_FILL_MAX_DAYS`, and exists only when at least one
    weekday lies strictly between that start and the run key (J1 stores the run key's own NAVs)."""
    end = date.fromisoformat(run_key)
    if last_success is not None:
        base = date.fromisoformat(last_success)
    elif latest:
        base = min(date.fromisoformat(d) for d in latest.values())
    else:
        return None
    if weekdays_between(base, end) <= 1:
        return None
    return max(base + timedelta(days=1), end - timedelta(days=GAP_FILL_MAX_DAYS)), end


def _j3_history(ctx: CronContext) -> CronResult:
    run_key = newest_nav_date(ctx.conn)
    if run_key is None:
        return CronResult("history", "noop", "NO_NAV_DATA")
    if not ctx.backfill_lock.acquire(blocking=False):
        return CronResult("history", "noop", "BACKFILL_BUSY", run_key)
    try:
        opened = coordination.load_job(ctx.conn, HISTORY_OPEN)
        batch_open = coordination.load_job(ctx.conn, ingestion.BATCH_JOB) is not None
        counts: dict[str, int] = {}
        if opened is not None and batch_open:
            run_key = str(opened["run_key"])  # continue our own open batch, no new claim
        elif ingestion.backfill_in_progress(ctx.conn):
            return CronResult("history", "noop", "USER_BACKFILL_OPEN", run_key)
        else:
            if opened is not None:  # our batch ended outside this module: forget the stale marker
                coordination.clear_job(ctx.conn, HISTORY_OPEN)
            if not _claim(ctx, "history", run_key):
                return CronResult("history", "noop", "DUPLICATE", run_key)
            codes = sorted(ingestion.tracked_scheme_codes(ctx.conn))  # U-01: held and watched only, hosted
            latest = _latest_per_code(ctx.conn, codes)
            counts.update(schemes=len(codes), schemes_without_history=len(codes) - len(latest))
            last = coordination.load_job(ctx.conn, HISTORY_LAST)
            window = gap_window(latest, str(last["run_key"]) if last else None, run_key)
            groups = _amc_groups(ctx.conn, sorted(latest)) if window else {}
            if window is None or not groups:
                return _finish_history(ctx, run_key, sorted(latest), counts, "NO_GAP", ok=True)
            ingestion.sync_sources(ctx.conn)
            ingestion.start_batch_backfill(
                ctx.conn, groups=groups, skipped=[], start=window[0], end=window[1], now=ctx.now
            )
            coordination.save_job(ctx.conn, HISTORY_OPEN, {"run_key": run_key}, ctx.now_iso())
        out = ingestion.backfill_batch_step(
            ctx.conn, ctx.fetcher(), now=ctx.now, pause=ctx.pause, stop=lambda: ctx.remaining() <= 0
        )
        counts.update(windows_done=int(out["windows_done"]), windows_total=int(out["windows_total"]))
        if not out["done"]:
            return CronResult("history", "partial", "GAP_FILLING", run_key, counts)
        coordination.clear_job(ctx.conn, HISTORY_OPEN)
        counts["stored"] = int(out.get("stored") or 0)
        ok = out.get("status") in ("ok", "partial")
        changed = sorted({int(s["amfi_code"]) for g in out.get("fund_houses", []) for s in g["schemes"]})
        return _finish_history(ctx, run_key, changed, counts, "GAP_FILLED" if ok else "GAP_FILL_FAILED", ok=ok)
    finally:
        ctx.backfill_lock.release()


def _finish_history(
    ctx: CronContext, run_key: str, codes: list[int], counts: dict[str, int], code: str, *, ok: bool
) -> CronResult:
    counts["grid_points"], counts["grid_skipped"] = refresh_series_grid(ctx.conn, codes, ctx.now_iso())
    if ok:
        coordination.save_job(ctx.conn, HISTORY_LAST, {"run_key": run_key}, ctx.now_iso())
    _finish(ctx, "history", run_key, "done" if ok else "failed", code)
    return CronResult("history", "done" if ok else "failed", code, run_key, counts)


def refresh_series_grid(conn: sqlite3.Connection, codes: list[int], now_iso: str) -> tuple[int, int]:
    """Recompute the month-end grid (F9) from the last stored grid month onwards for ``codes``. A scheme whose stored
    NAVs disagree on a date, or that has no valid month-end yet, is skipped (counted), never guessed.
    Returns (points written, schemes skipped)."""
    if not codes:
        return 0, 0
    iids = {ingestion.instrument_id(c): c for c in codes}
    since: dict[str, str] = {}
    for part in ledger.chunks(sorted(iids), ledger.MAX_PARAMS):
        for r in conn.execute(
            "SELECT instrument_id, MAX(month) AS m FROM series_grid"  # noqa: S608 - placeholders only
            f" WHERE instrument_id IN ({','.join('?' * len(part))}) GROUP BY instrument_id",
            list(part),
        ).fetchall():
            since[str(r["instrument_id"])] = f"{r['m']}-01"
    floor = min(since.values()) if len(since) == len(iids) else "0000-01-01"
    by_series: dict[str, dict[str, list[tuple[int, str]]]] = {}
    for part in ledger.chunks(sorted(iids), ledger.MAX_PARAMS):
        for r in conn.execute(
            "SELECT series_id, observation_date, value, obs_id FROM observations"  # noqa: S608
            f" WHERE series_id IN ({','.join('?' * len(part))}) AND observation_date >= ?"
            f" AND superseded_by IS NULL AND {_NAV_QUALITY} ORDER BY series_id, observation_date, obs_id",
            [*(ingestion.series_id(iids[i]) for i in part), floor],
        ).fetchall():
            by_series.setdefault(str(r["series_id"]), {}).setdefault(str(r["observation_date"]), []).append(
                (int(r["obs_id"]), str(r["value"]))
            )
    points: list[ledger.GridPoint] = []
    skipped = 0
    for iid, code in sorted(iids.items()):
        dated = by_series.get(ingestion.series_id(code), {})
        start = since.get(iid, "0000-01-01")
        pairs: list[tuple[date, Decimal]] = []
        ids: dict[str, int] = {}
        try:
            for d, obs in sorted(dated.items()):
                if d < start:
                    continue
                values = {Decimal(v) for _, v in obs}
                if len(values) != 1:
                    raise InvalidOperation("conflicting NAVs for one date")
                pairs.append((date.fromisoformat(d), values.pop()))
                ids[d] = min(i for i, _ in obs)
            grid = month_end_grid(pairs)
        except (EngineError, InvalidOperation, ValueError):
            skipped += 1
            continue
        points.extend(
            ledger.GridPoint(
                iid, c.month_end.strftime("%Y-%m"), c.obs_date.isoformat(), c.nav, ids[c.obs_date.isoformat()], now_iso
            )
            for c in grid.cells
        )
    return (ledger.upsert_series_grid(conn, points) if points else 0), skipped


# ----------------------------------------------------------------------------------------------------- outbox


def reap_and_drain(ctx: CronContext) -> dict[str, int]:
    """Reap stale 'sending' rows (never resent), then send pending pings once each through the configured sender."""
    claimed_before = (ctx.now() - timedelta(seconds=OUTBOX_LEASE_S)).isoformat()
    counts = {"pings_reaped": ledger.reap_stale_pings(ctx.conn, claimed_before, ctx.now_iso()), "pings_sent": 0}
    sender = ctx.hooks.sender
    if sender is None:
        return counts
    rows = ctx.conn.execute(
        "SELECT o.outbox_key, o.channel, o.kind, o.snapshot_id, s.as_of_date FROM notification_outbox o"
        " LEFT JOIN signal_snapshots s ON s.snapshot_id = o.snapshot_id WHERE o.state='pending'"
        " ORDER BY o.created_at, o.outbox_key, o.channel LIMIT ?",
        (OUTBOX_DRAIN_LIMIT,),
    ).fetchall()
    for row in rows:
        if not ledger.claim_ping(ctx.conn, str(row["outbox_key"]), str(row["channel"]), ctx.now_iso()):
            continue  # another delivery owns it
        try:
            sender(row)
        except Exception as exc:  # left 'sending': the reaper marks it failed later and it is never resent
            log.warning("ping send failed kind=%s type=%s", row["kind"], type(exc).__name__)
            continue
        if ledger.mark_ping_sent(ctx.conn, str(row["outbox_key"]), str(row["channel"]), ctx.now_iso()):
            counts["pings_sent"] += 1
    return counts


# ----------------------------------------------------------------------------------------------------- J4


def _j4_snapshot(ctx: CronContext) -> CronResult:
    late_deadline = ctx.monotonic() + max(0.0, ctx.remaining()) * LATE_NAV_SHARE
    late = _navall_pass(ctx, "snapshot", lambda: late_deadline - ctx.monotonic())
    steps = {"late_navs": late.code}
    counts = reap_and_drain(ctx)
    run_key = newest_nav_date(ctx.conn)
    if run_key is None:
        return CronResult("snapshot", "failed", "NO_NAV_DATA", None, dict(counts), steps)
    if not _claim(ctx, "snapshot", run_key):
        return CronResult("snapshot", "noop", "DUPLICATE", run_key, dict(counts), steps)
    step = ctx.hooks.snapshot
    if step is None:
        _finish(ctx, "snapshot", run_key, "failed", "SNAPSHOT_NOT_IMPLEMENTED")
        return CronResult("snapshot", "failed", "SNAPSHOT_NOT_IMPLEMENTED", run_key, dict(counts), steps)
    previous = ledger.latest_snapshot(ctx.conn)
    try:
        outcome = step(ctx.conn, ctx.now())
    except Exception as exc:
        log.error("snapshot step failed type=%s", type(exc).__name__)
        _rollback(ctx.conn)
        _finish(ctx, "snapshot", run_key, "failed", "SNAPSHOT_FAILED")
        return CronResult("snapshot", "failed", "SNAPSHOT_FAILED", run_key, dict(counts), steps)
    steps["verdict"] = outcome.verdict
    changed = previous is None or (
        str(previous["snapshot_id"]) != outcome.snapshot_id and str(previous["card_set_hash"]) != outcome.card_set_hash
    )
    queued = 0
    if changed:
        for channel in ctx.hooks.channels:
            queued += ledger.enqueue_ping(ctx.conn, outcome.snapshot_id, channel, "report", outcome.snapshot_id,
                                          ctx.now_iso())  # fmt: skip
    for k, v in reap_and_drain(ctx).items():
        counts[k] += v
    counts["pings_queued"] = queued
    counts["snapshot_written"] = int(outcome.written)
    code = "SNAPSHOT_STORED" if outcome.written else "SNAPSHOT_UNCHANGED"
    _finish(ctx, "snapshot", run_key, "done", code)
    return CronResult("snapshot", "done", code, run_key, counts, steps)


# ----------------------------------------------------------------------------------------------------- J5


def expected_nav_date(today: date) -> date:
    """The NAV date a healthy pipeline has by the watchdog hour: the last weekday before ``today`` (IST). No holiday
    calendar is loaded, so a weekday holiday can raise a false alarm - never hide a real one."""
    d = today - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _j5_watchdog(ctx: CronContext) -> CronResult:
    today = ctx.ist_today()
    run_key = expected_nav_date(today).isoformat()
    counts = reap_and_drain(ctx)
    if not _claim(ctx, "watchdog", run_key):
        return CronResult("watchdog", "noop", "DUPLICATE", run_key, counts)
    problems: list[str] = []
    snap = ledger.latest_snapshot(ctx.conn)
    if snap is None or str(snap["as_of_date"]) < run_key:
        problems.append("SNAPSHOT_MISSING")
    newest = newest_nav_date(ctx.conn)
    if newest is None or nav_is_stale(date.fromisoformat(newest), today):
        problems.append("NAV_STALE")
    since = (ctx.now() - timedelta(hours=24)).isoformat()
    if ctx.conn.execute(
        "SELECT 1 FROM cron_runs WHERE state='failed' AND started_at >= ? AND job <> 'watchdog' LIMIT 1", (since,)
    ).fetchone():
        problems.append("JOB_FAILED")
    queued = 0
    if problems:
        for channel in ctx.hooks.channels:
            queued += ledger.enqueue_ping(ctx.conn, f"watchdog:{run_key}", channel, "watchdog", None, ctx.now_iso())
        for k, v in reap_and_drain(ctx).items():
            counts[k] += v
    counts["pings_queued"] = queued
    code = "ATTENTION" if problems else "HEALTHY"
    _finish(ctx, "watchdog", run_key, "done", ";".join([code, *problems]))
    return CronResult("watchdog", "done", code, run_key, counts, {p: "FOUND" for p in problems})


_HANDLERS: dict[str, Callable[[CronContext], CronResult]] = {
    "navall": _j1_navall,
    "navall-continue": _j2_continue,
    "history": _j3_history,
    "snapshot": _j4_snapshot,
    "watchdog": _j5_watchdog,
}
