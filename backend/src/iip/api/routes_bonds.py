"""G-sec, SDL and corporate-bond manual entry (citation required) and the stored-bond list."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from iip.services import bonds, instruments


def _state(request: Request) -> Any:
    return request.app.state.iip


def router() -> APIRouter:
    r = APIRouter(prefix="/api")

    @r.post("/instruments/gsec")
    def add_gsec(body: instruments.GsecIn, request: Request) -> dict[str, str]:
        st = _state(request)
        return {"instrument_id": instruments.add_gsec(st.conn, body, st.clock())}

    @r.post("/instruments/corp-bond")
    def add_corp_bond(body: instruments.CorporateBondIn, request: Request) -> dict[str, str]:
        st = _state(request)
        return {"instrument_id": instruments.add_corporate_bond(st.conn, body, st.clock())}

    @r.get("/bonds")
    def list_bonds(request: Request) -> dict[str, Any]:
        st = _state(request)
        as_of = st.clock().date()
        return {
            "as_of": as_of.isoformat(),
            "quote_stale_after_days": instruments.BOND_QUOTE_STALE_DAYS,
            "rating_stale_after_days": instruments.RATING_STALE_DAYS,
            "items": bonds.list_bonds(st.conn, as_of),
        }

    return r
