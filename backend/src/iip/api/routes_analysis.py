"""Feature routes (analysis): compare, scenario, simulate, feasibility, forecast, risk. Registered in routes.py.

Decimals are accepted only as JSON strings (or integers where a whole number is natural); floats are rejected with
422 so that binary rounding never enters a money calculation. Responses carry no floats.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from iip.api.routes_core import tax_rules
from iip.engine.errors import EngineError, InvalidInput
from iip.services import analysis

MAX_AMOUNT = Decimal("1000000000000")  # ≤ ₹1 lakh crore (same bound as the profile)


def _no_float(v: object) -> object:
    if isinstance(v, float):
        raise ValueError("send decimals as strings, not floats")
    return v


def _string_only(v: object) -> object:
    if not isinstance(v, str):
        raise ValueError('must be a decimal string, e.g. "0.25"')
    return v


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Horizon(_In):
    amount: Decimal | None = Field(default=None, gt=0, le=MAX_AMOUNT, decimal_places=2)
    withdrawal_date: date | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, v: object) -> object:
        return _no_float(v)


class CompareIn(_Horizon):
    instrument_ids: list[str] = Field(min_length=2, max_length=4)

    @field_validator("instrument_ids")
    @classmethod
    def _distinct(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v) or any(not x or len(x) > 200 for x in v):
            raise ValueError("instrument_ids must be 2–4 distinct, non-empty ids")
        return v


class ShocksIn(_In):
    rate_bp: Decimal | None = Field(default=None, ge=-1000, le=1000)
    spread_bp: Decimal | None = Field(default=None, ge=-1000, le=2000)
    equity_pct: Decimal | None = Field(default=None, ge=-100, le=0)
    inflation_pct: Decimal | None = Field(default=None, ge=-20, le=50)
    exit_before_maturity_days: int | None = Field(default=None, ge=1, le=3650)
    reinvestment_rate: Decimal | None = Field(default=None, gt=-1, le=1)

    @field_validator("rate_bp", "spread_bp", "equity_pct", "inflation_pct", "reinvestment_rate", mode="before")
    @classmethod
    def _dec(cls, v: object) -> object:
        return _no_float(v)


class ScenarioIn(_Horizon):
    instrument_id: str = Field(min_length=1, max_length=200)
    shocks: ShocksIn

    @model_validator(mode="after")
    def _some_shock(self) -> ScenarioIn:
        if all(v is None for v in self.shocks.model_dump().values()):
            raise ValueError("supply at least one shock")
        return self


class AllocationIn(_In):
    instrument_id: str = Field(min_length=1, max_length=200)
    weight: Decimal = Field(gt=0, le=1)

    @field_validator("weight", mode="before")
    @classmethod
    def _w(cls, v: object) -> object:
        return _string_only(v)


class SimulateIn(_Horizon):
    allocations: list[AllocationIn] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _weights(self) -> SimulateIn:
        ids = [a.instrument_id for a in self.allocations]
        if len(set(ids)) != len(ids):
            raise ValueError("allocations must name distinct instruments")
        total = sum((a.weight for a in self.allocations), Decimal(0))
        if total != Decimal(1):
            raise ValueError(f"weights must sum to exactly 1 (got {total})")
        return self


class FeasibilityIn(_In):
    instrument_id: str = Field(min_length=1, max_length=200)
    target_annual: Decimal = Field(gt=Decimal("-0.5"), le=1)
    horizon_years: Literal[1, 3, 5]
    mode: Literal["CAGR", "EVERY_YEAR"] = "CAGR"

    @field_validator("target_annual", mode="before")
    @classmethod
    def _t(cls, v: object) -> object:
        return _string_only(v)


def _state(request: Request) -> Any:
    return request.app.state.iip


def _call(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return fn()
    except analysis.AnalysisError as exc:
        raise HTTPException(exc.status, {"code": exc.code, "message": exc.message}) from exc
    except InvalidInput as exc:
        raise HTTPException(422, {"code": exc.code, "message": str(exc)}) from exc
    except EngineError as exc:
        raise HTTPException(409, {"code": exc.code, "message": str(exc)}) from exc


def router() -> APIRouter:
    r = APIRouter(prefix="/api")

    @r.post("/compare")
    def compare(body: CompareIn, request: Request) -> dict[str, Any]:
        st = _state(request)
        return _call(lambda: analysis.compare(
            st.conn, as_of=st.clock().date(), ruleset=tax_rules(), instrument_ids=body.instrument_ids,
            amount=body.amount, withdrawal=body.withdrawal_date,
        ))  # fmt: skip

    @r.post("/scenario")
    def scenario(body: ScenarioIn, request: Request) -> dict[str, Any]:
        st = _state(request)
        return _call(lambda: analysis.scenario(
            st.conn, as_of=st.clock().date(), ruleset=tax_rules(), instrument_id=body.instrument_id,
            amount=body.amount, withdrawal=body.withdrawal_date, shocks=body.shocks.model_dump(),
        ))  # fmt: skip

    @r.post("/simulate")
    def simulate(body: SimulateIn, request: Request) -> dict[str, Any]:
        st = _state(request)
        return _call(lambda: analysis.simulate(
            st.conn, as_of=st.clock().date(), ruleset=tax_rules(),
            allocations=[(a.instrument_id, a.weight) for a in body.allocations],
            amount=body.amount, withdrawal=body.withdrawal_date,
        ))  # fmt: skip

    @r.post("/feasibility")
    def feasibility(body: FeasibilityIn, request: Request) -> dict[str, Any]:
        st = _state(request)
        return _call(lambda: analysis.feasibility(
            st.conn, as_of=st.clock().date(), instrument_id=body.instrument_id, target_annual=body.target_annual,
            horizon_years=body.horizon_years, mode=body.mode,
        ))  # fmt: skip

    @r.get("/forecast/{instrument_id}")
    def forecast(
        instrument_id: str, request: Request, horizon_days: int | None = Query(default=None, ge=1, le=3650)
    ) -> dict[str, Any]:
        st = _state(request)
        return _call(lambda: analysis.forecast(
            st.conn, as_of=st.clock().date(), instrument_id=instrument_id, horizon_days=horizon_days,
        ))  # fmt: skip

    @r.get("/risk/{instrument_id}")
    def risk(instrument_id: str, request: Request) -> dict[str, Any]:
        st = _state(request)
        return _call(lambda: analysis.risk(st.conn, as_of=st.clock().date(), instrument_id=instrument_id))

    return r
