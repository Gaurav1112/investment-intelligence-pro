"""Goals, mapping, risk profile, tax context, policy and the six-answer setup (PLAN.md wave 2, package B01).

Session, CSRF and origin checks are the security middleware's, exactly as for every other ``/api`` route. Static
paths are declared before ``/{goal_id}`` so no route captures another's URL (A05 autodiscovery shadow test).
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, HTTPException, Path, Query, Request

from iip.services import goals as svc

T = TypeVar("T")
GoalId = Annotated[str, Path(pattern=svc.GOAL_ID_PATTERN)]


def _guard[T](fn: Callable[[], T]) -> T:
    try:
        return fn()
    except svc.GoalsError as exc:
        raise HTTPException(exc.status, {"code": exc.code, "message": exc.message}) from exc


def _amount(raw: str | None) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise HTTPException(422, {"code": "INVALID_INPUT", "message": "amount must be a decimal number"}) from exc
    if not value.is_finite() or value <= 0 or value > svc.MAX_INR:
        raise HTTPException(422, {"code": "INVALID_INPUT", "message": "amount must be a positive ₹ amount"})
    return value


def router() -> APIRouter:
    r = APIRouter(prefix="/api/goals", tags=["goals"])

    def state(request: Request) -> Any:
        return request.app.state.iip

    def overview(request: Request) -> svc.GoalsOverview:
        st = state(request)
        return svc.overview(st.conn, svc.load_stress_rules(st.settings.data_dir), st.clock().date())

    def goal_view(request: Request, goal: Any) -> svc.GoalView:
        st = state(request)
        return svc.goal_view(goal, svc.stress_history(svc.load_stress_rules(st.settings.data_dir)))

    # ------------------------------------------------------------------------------------- overview and setup

    @r.get("")
    def get_overview(request: Request) -> svc.GoalsOverview:
        return overview(request)

    @r.post("/setup")
    def post_setup(body: svc.SetupIn, request: Request) -> svc.GoalsOverview:
        st = state(request)
        fy = svc.financial_year(st.clock().date())
        _guard(lambda: svc.setup(st.conn, body, fy, st.clock().isoformat()))
        return overview(request)

    @r.get("/stress-history")
    def get_stress_history(request: Request, amount: Annotated[str | None, Query(max_length=40)] = None
                           ) -> svc.StressHistory:  # fmt: skip
        st = state(request)
        return svc.stress_history(svc.load_stress_rules(st.settings.data_dir), _amount(amount))

    # ------------------------------------------------------------------------------------- mapping

    @r.put("/mapping")
    def put_mapping(body: svc.MappingIn, request: Request) -> svc.GoalsOverview:
        st = state(request)
        _guard(lambda: svc.replace_mapping(st.conn, body, st.clock().isoformat()))
        return overview(request)

    # ------------------------------------------------------------------------------------- risk profile

    @r.get("/risk-profile")
    def get_risk_profile(request: Request) -> svc.RiskProfileView:
        return overview(request).risk_profile

    @r.put("/risk-profile")
    def put_risk_profile(body: svc.RiskProfileIn, request: Request) -> svc.RiskProfileView:
        st = state(request)
        svc.save_risk_profile(st.conn, body, st.clock().isoformat())
        return overview(request).risk_profile

    # ------------------------------------------------------------------------------------- tax context

    @r.get("/tax-context")
    def get_tax_context(request: Request) -> svc.TaxContextView:
        return overview(request).tax_context

    @r.put("/tax-context")
    def put_tax_context(body: svc.TaxIn, request: Request) -> svc.TaxContextView:
        st = state(request)
        svc.save_tax(st.conn, svc.financial_year(st.clock().date()), body, st.clock().isoformat())
        return overview(request).tax_context

    # ------------------------------------------------------------------------------------- policy

    @r.get("/policy")
    def get_policy(request: Request) -> svc.PolicyView:
        st = state(request)
        return _guard(lambda: svc.load_policy(st.conn).view)

    @r.put("/policy")
    def put_policy(body: svc.PolicyIn, request: Request) -> svc.PolicyView:
        st = state(request)
        now = st.clock()
        return _guard(lambda: svc.save_policy(st.conn, body, now.date(), now.isoformat()))

    # ------------------------------------------------------------------------------------- goals (after static paths)

    @r.post("")
    def create_goal(body: svc.GoalIn, request: Request) -> svc.GoalView:
        st = state(request)
        goal = _guard(lambda: svc.save_goal(st.conn, None, body, st.clock().isoformat()))
        return goal_view(request, goal)

    @r.put("/{goal_id}")
    def update_goal(goal_id: GoalId, body: svc.GoalIn, request: Request) -> svc.GoalView:
        st = state(request)
        goal = _guard(lambda: svc.save_goal(st.conn, goal_id, body, st.clock().isoformat()))
        return goal_view(request, goal)

    @r.delete("/{goal_id}")
    def delete_goal(goal_id: GoalId, request: Request) -> dict[str, str]:
        st = state(request)
        _guard(lambda: svc.delete_goal(st.conn, goal_id, st.clock().isoformat()))
        return {"status": "deleted", "goal_id": goal_id}

    return r
