from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from iip.services import profile as svc


def router() -> APIRouter:
    r = APIRouter(prefix="/api/profile", tags=["profile"])

    @r.get("")
    def get_profile(request: Request) -> svc.ProfileStatus:
        st = request.app.state.iip
        return svc.evaluate(svc.load(st.conn), st.clock().date())

    @r.put("")
    def put_profile(body: svc.Profile, request: Request) -> svc.ProfileStatus:
        st = request.app.state.iip
        svc.save(st.conn, body, st.clock().isoformat())
        return svc.evaluate(body, st.clock().date())

    @r.delete("")
    def delete_profile(request: Request) -> dict[str, Any]:
        st = request.app.state.iip
        st.conn.execute("DELETE FROM profiles WHERE profile_id = ?", (svc.PROFILE_ID,))
        return {"status": "deleted"}

    return r
