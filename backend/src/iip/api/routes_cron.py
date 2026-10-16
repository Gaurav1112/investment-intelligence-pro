"""Scheduled jobs route (PLAN B03, ADR-0014 draft in research-automation-infra.md §3): ``GET|POST /api/cron/{job}``.

Reachable only through the SecurityMiddleware cron exception (A03): hosted, ``VERCEL_ENV=production``, a valid
``Authorization: Bearer <CRON_SECRET>``; the root ``app.py`` answers 404 while the secret is empty. This handler adds
defence in depth: it answers 404 unless the middleware marked the request as a cron call, the app is hosted and the
job is one of the fixed five. There are no parameters: the job decides its work from the database, never from the
request. The response carries codes and counts only.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from iip.services import cron

_NOT_FOUND = {"code": "NOT_FOUND"}


def _context(request: Request) -> cron.CronContext:
    st = request.app.state.iip
    hooks = getattr(request.app.state, "cron_hooks", None) or cron.default_hooks()
    return cron.CronContext(
        conn=st.conn, fetcher=st.fetcher, now=st.clock, monotonic=st.monotonic, budget_s=st.job_budget_s,
        navall_lock=st.navall_lock, backfill_lock=st.backfill_lock, pause=st.pause, hooks=hooks,
    )  # fmt: skip


def router() -> APIRouter:
    r = APIRouter(prefix="/api/cron")

    @r.api_route("/{job}", methods=["GET", "POST"], include_in_schema=False)
    def run(job: str, request: Request) -> Any:
        if request.scope.get("state", {}).get("cron") is not True or not request.app.state.iip.hosted:
            return JSONResponse(_NOT_FOUND, status_code=404)
        if job not in cron.JOBS:
            return JSONResponse(_NOT_FOUND, status_code=404)
        if request.url.query:
            return JSONResponse({"code": "NO_PARAMETERS"}, status_code=400)
        result = cron.run_job(_context(request), job)
        return JSONResponse(result.as_dict(), status_code=500 if result.state == "failed" else 200)

    return r
