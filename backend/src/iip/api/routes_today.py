"""Today API (PLAN.md wave 2, package B02).

* ``GET /api/today`` — the newest stored snapshot with the decisions already recorded against it, in ONE database
  statement. The engine never runs on page load: with no snapshot yet the response is the ``NO_SNAPSHOT`` state.
* ``GET /api/today/needs`` — "Needs from you" from the same snapshot (one statement).
* ``POST /api/today/decisions`` — "I did this" (``done``), "not now" or "disagree" for one action card.
* ``POST /api/today/snapshot`` — an explicit, user-initiated recompute (local mode has no cron). Hosted mode
  normally gets its snapshot from job J4.

State-changing routes go through the same session and CSRF middleware as every other route.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from iip.rules.loader import load_action_templates, load_stress_table, local_stress_values_path
from iip.services import risk_snapshot as svc
from iip.store.db import write_tx


class DecisionIn(BaseModel):
    snapshot_id: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    card_id: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    decision: Literal["done", "not_now", "disagree"] = "done"
    note: str | None = Field(default=None, max_length=2000)


class SnapshotIn(BaseModel):
    as_of: date | None = None  # the data date; default = the newest NAV date among your holdings


_STATUS = {"BAD_DECISION": 422, "UNKNOWN_SNAPSHOT": 404, "UNKNOWN_CARD": 404, "NOT_AN_ACTION": 422}


def router() -> APIRouter:
    r = APIRouter(prefix="/api/today", tags=["today"])

    @r.get("")
    def get_today(request: Request) -> dict[str, Any]:
        return svc.read_today(request.app.state.iip.conn)

    @r.get("/needs")
    def get_needs(request: Request) -> dict[str, Any]:
        return svc.read_needs(request.app.state.iip.conn)

    @r.post("/decisions")
    def post_decision(body: DecisionIn, request: Request) -> dict[str, Any]:
        st = request.app.state.iip
        try:
            with write_tx(st.conn) as conn:
                return svc.record_decision(
                    conn, snapshot_id=body.snapshot_id, card_id=body.card_id, decision=body.decision,
                    note=body.note, now=st.clock().isoformat(),
                )  # fmt: skip
        except svc.DecisionRejected as exc:
            raise HTTPException(_STATUS.get(exc.code, 422), {"code": exc.code, "message": str(exc)}) from exc

    @r.post("/snapshot")
    def post_snapshot(body: SnapshotIn, request: Request) -> dict[str, Any]:
        st = request.app.state.iip
        conn = st.conn
        now = st.clock()
        as_of = body.as_of or svc.latest_data_date(conn) or now.date()
        if as_of > now.date():
            raise HTTPException(422, {"code": "AS_OF_IN_FUTURE", "message": "as_of cannot be after today"})
        stress = load_stress_table(local_values_path=local_stress_values_path(st.settings.data_dir))
        templates = load_action_templates()
        daily = svc.run_daily(conn, as_of=as_of, now=now.isoformat(), stress_table=stress, templates=templates)
        return {
            "snapshot_id": daily.snapshot.snapshot_id,
            "as_of": daily.snapshot.as_of.isoformat(),
            "verdict": daily.snapshot.verdict,
            "created": daily.snapshot.created,
            "card_set_changed": daily.snapshot.card_set_changed,
            "shadow": {"rules": daily.shadow.rules, "written": daily.shadow.written},
            "outcomes": {"scored": daily.outcomes.scored, "unscorable": daily.outcomes.unscorable},
        }

    return r
