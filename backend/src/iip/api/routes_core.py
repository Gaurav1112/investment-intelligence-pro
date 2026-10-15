"""Feature routes: discovery, instruments, ingestion, data health, runs, methodology."""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from iip.api import routes_llm
from iip.data.registry import REGISTRY, SourceMode
from iip.engine import tax as tx
from iip.engine.candidates import ENGINE_VERSION
from iip.engine.ranking import POLICY_VERSION
from iip.rules.loader import load_tax_rules
from iip.services import discovery, fixtures, ingestion, instruments
from iip.services import profile as profile_svc
from iip.store import coordination
from iip.supervisor import compliance


@lru_cache(maxsize=1)
def tax_rules() -> tx.TaxRuleSet | None:
    try:
        return load_tax_rules()
    except Exception:  # a broken rule file must ABSTAIN, not crash the API
        return None


def _rate_limited(wait: int) -> JSONResponse:
    return JSONResponse({"code": "RATE_LIMITED", "retry_after_s": wait}, status_code=429,
                        headers={"Retry-After": str(wait)})  # fmt: skip


def _busy(code: str) -> JSONResponse:
    return JSONResponse({"code": code, "retry_after_s": 60}, status_code=429, headers={"Retry-After": "60"})


def _run_navall_hosted(st: Any) -> Any:
    """ADR-0013: NAVAll in bounded steps (the client calls again while ``done`` is false). The 15-minute limit is
    claimed only when a NEW run starts; continuations of the run in progress are not refused. One at a time."""
    if not st.navall_lock.acquire(blocking=False):
        return _busy("NAVALL_IN_PROGRESS")
    try:
        if coordination.load_job(st.conn, ingestion.NAVALL_JOB) is None:
            if (wait := st.claim_refresh("amfi.navall")) is not None:
                return _rate_limited(wait)
            ingestion.sync_sources(st.conn)
        deadline = st.monotonic() + st.job_budget_s
        return ingestion.ingest_navall_resumable(st.conn, st.fetcher(), st.clock, lambda: st.monotonic() >= deadline)
    finally:
        st.navall_lock.release()


def _backfill_hosted(st: Any, amfi_code: int, amc: str, years: int) -> Any:
    """ADR-0013: a backfill in bounded steps (the caller holds the backfill lease). Per-scheme 15-minute limit on
    NEW backfills only; a continuation of the one in progress is not refused."""
    if coordination.load_job(st.conn, ingestion.backfill_job_key(amfi_code)) is None:
        if (wait := st.claim_refresh(f"amfi.navhistory:{amfi_code}")) is not None:
            return _rate_limited(wait)
    today = st.clock().date()
    deadline = st.monotonic() + st.job_budget_s
    try:
        return ingestion.backfill_resumable(
            st.conn, st.fetcher(), scheme_code=amfi_code, amc_name=amc,
            start=date(today.year - years, today.month, 1), end=today, now=st.clock, pause=st.pause,
            stop=lambda: st.monotonic() >= deadline,
        )  # fmt: skip
    except ingestion.FundHouseNotFound as exc:
        raise HTTPException(424, "could not determine AMFI's fund-house id for this AMC") from exc


_TERMS_QUERIES = (
    ("mf_schemes", "SELECT * FROM mf_schemes WHERE instrument_id=?"),
    ("bond_terms", "SELECT * FROM bond_terms WHERE instrument_id=?"),
    ("deposit_terms", "SELECT * FROM deposit_terms WHERE instrument_id=?"),
)


class DiscoverIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    include_fixtures: bool = False


class BackfillIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    years: int = Field(default=10, ge=1, le=20)


def _state(request: Request) -> Any:
    return request.app.state.iip


def router() -> APIRouter:  # noqa: PLR0915 - route table
    r = APIRouter(prefix="/api")

    # ------------------------------------------------------------------ discovery
    @r.post("/discover")
    def discover(body: DiscoverIn, request: Request) -> Any:
        st = _state(request)
        if body.include_fixtures and st.settings.env not in {"dev", "test"}:
            # RT-27: synthetic fixtures may never enter a ranking in production, even badged.
            return JSONResponse(
                {"code": "FIXTURES_NOT_ALLOWED", "detail": "include_fixtures is only accepted in dev/test"},
                status_code=400,
            )
        as_of = st.clock().date()
        profile = profile_svc.load(st.conn)
        status = profile_svc.evaluate(profile, as_of)
        rephrase, _ = routes_llm.rephraser(st, profile)  # None unless the optional AI wording is enabled (ADR-0007)
        out = discovery.discover(st.conn, status, as_of=as_of, ruleset=tax_rules(),
                                 allow_fixtures=body.include_fixtures, llm_rephrase=rephrase)  # fmt: skip
        if rephrase is not None and out["report"] is not None:
            routes_llm.runtime(st).record_rejection(out["report"]["rejected_llm_reasons"])
        out["run"]["run_id"] = discovery.store_run(st.conn, out, st.clock())
        return out

    # ------------------------------------------------------------------ instruments
    @r.get("/instruments")
    def list_instruments(request: Request, kind: str | None = None, q: str | None = None) -> dict[str, Any]:
        st = _state(request)
        sql = (
            "SELECT i.instrument_id, i.kind, i.name, i.origin, i.amfi_code, m.category_raw, m.plan, m.exit_load_json,"
            " (SELECT observation_date FROM observations o WHERE o.series_id = 'nav:' || i.amfi_code AND"
            "  o.superseded_by IS NULL ORDER BY observation_date DESC LIMIT 1) AS last_nav_date,"
            " (SELECT value FROM observations o WHERE o.series_id = 'nav:' || i.amfi_code AND"
            "  o.superseded_by IS NULL ORDER BY observation_date DESC LIMIT 1) AS last_nav,"
            " (SELECT COUNT(*) FROM observations o WHERE o.series_id = 'nav:' || i.amfi_code AND"
            "  o.superseded_by IS NULL) AS nav_points"
            " FROM instruments i LEFT JOIN mf_schemes m USING(instrument_id) WHERE 1=1"
        )
        params: list[Any] = []
        if kind:
            sql += " AND i.kind = ?"
            params.append(kind)
        if q:
            sql += " AND i.name LIKE ? ESCAPE '\\'"
            params.append("%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        sql += " ORDER BY i.kind, i.name LIMIT 500"
        rows = [dict(x) for x in st.conn.execute(sql, params)]
        for row in rows:
            row["exit_load"] = json.loads(row.pop("exit_load_json")) if row.get("exit_load_json") else None
            row["fixture"] = row["origin"] == "fixture"
        return {"items": rows, "truncated": len(rows) == 500}

    @r.get("/instruments/{instrument_id}")
    def get_instrument(instrument_id: str, request: Request) -> dict[str, Any]:
        st = _state(request)
        row = st.conn.execute("SELECT * FROM instruments WHERE instrument_id=?", (instrument_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "not found")
        out: dict[str, Any] = {"instrument": dict(row)}
        for table, sql in _TERMS_QUERIES:
            extra = st.conn.execute(sql, (instrument_id,)).fetchone()
            if extra:
                out[table] = dict(extra)
        series = "nav:" + str(row["amfi_code"]) if row["amfi_code"] else "yield:" + instrument_id
        obs = st.conn.execute(
            "SELECT observation_date, value, source_id, source_url, retrieved_at, quality_status FROM observations"
            " WHERE series_id=? AND superseded_by IS NULL ORDER BY observation_date",
            (series,),
        ).fetchall()
        out["series"] = {"series_id": series, "points": [dict(o) for o in obs]}
        if row["amfi_code"]:
            badge, observed = ingestion.latest_freshness(st.conn, int(row["amfi_code"]), st.clock())
            out["freshness"] = {"badge": badge, "observed": observed}
        return out

    @r.post("/instruments/tbill")
    def add_tbill(body: instruments.TBillIn, request: Request) -> dict[str, str]:
        st = _state(request)
        return {"instrument_id": instruments.add_tbill(st.conn, body, st.clock())}

    @r.post("/instruments/fd")
    def add_fd(body: instruments.FDIn, request: Request) -> dict[str, str]:
        st = _state(request)
        return {"instrument_id": instruments.add_fd(st.conn, body, st.clock())}

    @r.put("/instruments/{instrument_id}/exit-load")
    def put_exit_load(instrument_id: str, body: instruments.ExitLoadIn, request: Request) -> dict[str, str]:
        try:
            instruments.set_exit_load(_state(request).conn, instrument_id, body)
        except KeyError as exc:
            raise HTTPException(404, "not a mutual fund scheme") from exc
        return {"status": "saved"}

    @r.delete("/instruments/{instrument_id}")
    def delete_instrument(instrument_id: str, request: Request) -> dict[str, str]:
        if not instruments.delete_instrument(_state(request).conn, instrument_id):
            raise HTTPException(409, "only manually entered instruments can be deleted")
        return {"status": "deleted"}

    # ------------------------------------------------------------------ ingestion & data health
    @r.post("/ingestion/amfi-navall")
    def run_navall(request: Request) -> Any:
        st = _state(request)
        if st.hosted:
            return _run_navall_hosted(st)
        # SEC-86: at most one manual refresh per source per 15 minutes; refused calls make no outbound request.
        if (wait := st.claim_refresh("amfi.navall")) is not None:
            return _rate_limited(wait)
        ingestion.sync_sources(st.conn)
        summary = ingestion.ingest_navall(st.conn, st.fetcher(), st.clock)
        return summary.__dict__

    @r.post("/ingestion/backfill/{amfi_code}")
    def backfill(amfi_code: int, body: BackfillIn, request: Request) -> Any:
        st = _state(request)
        row = st.conn.execute(
            "SELECT m.amc FROM instruments i JOIN mf_schemes m USING(instrument_id) WHERE i.amfi_code=?",
            (str(amfi_code),),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "scheme not in the local store; run the AMFI NAV ingestion first")
        # C-16 (ECC F3): a backfill can make ~160 requests (fund-house probe + 90-day windows). It pauses between
        # requests and uses the process-wide circuit breaker. Limit (user decision 2026-10-15): once per SCHEME per
        # 15 min, and only one backfill at a time, so several schemes can be filled back to back at the paced rate.
        if not st.backfill_lock.acquire(blocking=False):
            return JSONResponse({"code": "BACKFILL_IN_PROGRESS", "retry_after_s": 60}, status_code=429,
                                headers={"Retry-After": "60"})  # fmt: skip
        try:
            if st.hosted:
                return _backfill_hosted(st, amfi_code, str(row["amc"]), body.years)
            if (wait := st.claim_refresh(f"amfi.navhistory:{amfi_code}")) is not None:
                return _rate_limited(wait)
            fetcher = st.fetcher()
            today = st.clock().date()
            mf_id = ingestion.discover_fund_house_id(st.conn, fetcher, row["amc"], today.replace(day=1), pause=st.pause)
            if mf_id is None:
                raise HTTPException(424, "could not determine AMFI's fund-house id for this AMC")
            summary = ingestion.backfill_history(
                st.conn, fetcher, scheme_code=amfi_code, mf_id=mf_id,
                start=date(today.year - body.years, today.month, 1), end=today, now=st.clock, pause=st.pause,
            )  # fmt: skip
            return summary.__dict__
        finally:
            st.backfill_lock.release()

    @r.get("/data-health")
    def data_health(request: Request) -> dict[str, Any]:
        st = _state(request)
        runs = [dict(x) for x in st.conn.execute("SELECT * FROM ingestion_runs ORDER BY started_at DESC LIMIT 50")]
        sources = []
        for spec in REGISTRY.values():
            last = st.conn.execute(
                "SELECT status, finished_at, rows_ok, rows_rejected, error FROM ingestion_runs WHERE source_id=?"
                " ORDER BY started_at DESC LIMIT 1",
                (spec.id,),
            ).fetchone()
            sources.append({
                "source_id": spec.id, "name": spec.name, "owner": spec.owner, "official": spec.official,
                "mode": spec.mode.value, "licence": spec.licence_class.value, "licence_note": spec.licence_note,
                "terms_url": spec.terms_url, "freshness": spec.freshness.description,
                "requires_configuration": spec.requires_configuration or spec.mode is SourceMode.LIVE,
                "last_run": dict(last) if last else None,
            })  # fmt: skip
        counts = st.conn.execute(
            "SELECT quality_status, COUNT(*) AS n FROM observations WHERE superseded_by IS NULL GROUP BY quality_status"
        ).fetchall()
        rules = tax_rules()
        return {
            "sources": sources,
            "runs": runs,
            "observation_counts": {c["quality_status"]: c["n"] for c in counts},
            "tax_rules_loaded": rules is not None,
            "tax_rules_coverage_to": rules.coverage_to.isoformat() if rules is not None else None,
        }

    @r.post("/dev/seed-fixtures")
    def seed_fixtures(request: Request) -> dict[str, Any]:
        st = _state(request)
        if st.settings.env not in {"dev", "test"} or st.hosted:  # ADR-0013: never synthetic data in a hosted store
            raise HTTPException(403, "fixtures can only be seeded in a local dev/test instance")
        return {"created": fixtures.seed(st.conn, as_of=st.clock().date(), now=st.clock()),
                "warning": "FIXTURE — synthetic data, not market data"}  # fmt: skip

    # ------------------------------------------------------------------ runs & methodology
    @r.get("/runs/{run_id}")
    def get_run(run_id: str, request: Request) -> dict[str, Any]:
        row = _state(request).conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "not found")
        return {"run_id": row["run_id"], "kind": row["kind"], "created_at": row["created_at"],
                "input_hash": row["input_hash"], "output_hash": row["output_hash"],
                "output": json.loads(row["output_json"])}  # fmt: skip

    @r.get("/methodology")
    def methodology() -> dict[str, Any]:
        rules = compliance.load_rules()
        tr = tax_rules()
        return {
            "versions": {"ranking_policy": POLICY_VERSION, "candidates": ENGINE_VERSION,
                         "compliance": rules.version, "discovery": discovery.SERVICE_VERSION},
            "tax": None if tr is None else {
                "snapshot_date": tr.snapshot_date.isoformat(), "coverage_to": tr.coverage_to.isoformat(),
                "table_version": tr.table_version,
                "rules": [{"rule_id": x.rule_id, "instrument_class": x.instrument_class,
                           "effective_from": x.effective_from.isoformat(),
                           "effective_to": x.effective_to.isoformat() if x.effective_to else None,
                           "verification": x.verification_status.value, "source_url": x.source_url}
                          for x in tr.rules]},
            "disclosures": rules.required,
        }  # fmt: skip

    return r
