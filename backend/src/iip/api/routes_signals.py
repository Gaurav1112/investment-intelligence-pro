"""Signals registry and rule detail API (PLAN.md wave 2, C03 over B02/B05).

* ``GET /api/signals`` — every registered rule with its registry state, first failing gate (ABSTAIN until every gate
  passes), G8 trial count, shadow-ledger summary and earliest possible review, plus the owner's vocabulary.
* ``GET /api/signals/{rule_id}/{version}`` — one rule: the gate panel, power, publication tag, the ×0.5 decay haircut
  and the newest shadow rows (recorded only; never an action).

Read-only. Same session middleware as every other route (no public route here). Shapes:
``frontend/src/lib/types-signals.ts``; reshaping in :mod:`iip.services.signals_view`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Path, Request

from iip.services import signals_view as view

RULE_ID = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"


def router() -> APIRouter:
    r = APIRouter(prefix="/api/signals", tags=["signals"])

    @r.get("")
    def get_signals(request: Request) -> dict[str, Any]:
        return view.signals_response(request.app.state.iip.conn)

    @r.get("/{rule_id}/{version}")
    def get_rule(
        request: Request,
        rule_id: str = Path(pattern=RULE_ID),
        version: int = Path(ge=1, le=1_000_000),
    ) -> dict[str, Any]:
        try:
            return view.rule_detail_response(request.app.state.iip.conn, rule_id, version)
        except view.RuleNotFound as exc:
            raise HTTPException(404, {"code": "UNKNOWN_RULE", "message": str(exc)}) from exc

    return r
