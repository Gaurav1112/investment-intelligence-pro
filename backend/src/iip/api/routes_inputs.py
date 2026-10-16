"""Feature routes (data inputs): CPI points, the 91-day T-bill risk-free series, scheme factsheet facts, bank FD
card-rate tables and the MoSPI adapter. Registered in routes.py.

Every write carries an https citation (``services.instruments.Citation``); decimals are JSON strings (floats → 422).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from iip.data import mospi
from iip.data.fetch import FetchError
from iip.data.models import DataError
from iip.services import inputs


class MospiFetchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_year: int = Field(ge=2012, le=2024)
    year: int = Field(ge=2013, le=2100)
    month: int = Field(ge=1, le=12)


def _state(request: Request) -> Any:
    return request.app.state.iip


def _call(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return fn()
    except inputs.InputError as exc:
        raise HTTPException(exc.status, {"code": exc.code, "message": exc.message}) from exc


def router() -> APIRouter:
    r = APIRouter(prefix="/api/inputs")

    # ------------------------------------------------------------------ CPI
    @r.get("/cpi")
    def list_cpi(request: Request) -> dict[str, Any]:
        return inputs.list_cpi(_state(request).conn)

    @r.post("/cpi")
    def add_cpi(body: inputs.CPIPointIn, request: Request) -> dict[str, Any]:
        st = _state(request)
        return _call(lambda: inputs.add_cpi_point(st.conn, body, st.clock()))

    @r.get("/mospi/status")
    def mospi_status() -> dict[str, Any]:
        return mospi.status(mospi.config_from_env())

    @r.post("/mospi/fetch")
    def mospi_fetch(body: MospiFetchIn, request: Request) -> dict[str, Any]:
        st = _state(request)
        if body.base_year not in (2012, 2024):
            raise HTTPException(422, {"code": "INVALID_INPUT", "message": "base_year must be 2012 or 2024"})
        config = mospi.config_from_env()  # always anonymous (A07): no configuration gate
        try:
            rec = mospi.fetch_cpi_month(
                config, st.fetcher(), base_year=body.base_year, year=body.year,
                month=body.month,
            )  # fmt: skip
        except mospi.MospiError as exc:
            raise HTTPException(409, {"code": exc.code, "message": exc.message}) from exc
        except (FetchError, DataError) as exc:
            raise HTTPException(502, {"code": exc.code, "message": "MoSPI fetch failed; nothing stored"}) from exc
        stored = inputs.store_mospi_record(st.conn, rec, st.clock())
        return {"status": "stored", **stored, "month": f"{rec.year:04d}-{rec.month:02d}", "verified": False}

    # ------------------------------------------------------------------ risk-free
    @r.get("/riskfree")
    def list_riskfree(request: Request) -> dict[str, Any]:
        st = _state(request)
        return inputs.list_risk_free(st.conn, st.clock().date())

    @r.post("/riskfree")
    def add_riskfree(body: inputs.RiskFreeIn, request: Request) -> dict[str, Any]:
        st = _state(request)
        return _call(lambda: inputs.add_risk_free(st.conn, body, st.clock()))

    # ------------------------------------------------------------------ fund facts
    @r.get("/fund-facts/{instrument_id}")
    def list_facts(instrument_id: str, request: Request) -> dict[str, Any]:
        st = _state(request)
        return _call(lambda: inputs.list_fund_facts(st.conn, instrument_id, st.clock().date()))

    @r.post("/fund-facts/{instrument_id}")
    def add_facts(instrument_id: str, body: inputs.FundFactsIn, request: Request) -> dict[str, Any]:
        st = _state(request)
        return _call(lambda: inputs.add_fund_facts(st.conn, instrument_id, body, st.clock()))

    # ------------------------------------------------------------------ FD card-rate tables
    @r.get("/fd-rates")
    def list_fd_rates(request: Request) -> dict[str, Any]:
        st = _state(request)
        return inputs.list_fd_rate_tables(st.conn, st.clock().date())

    @r.post("/fd-rates")
    def add_fd_rates(body: inputs.FDRateTableIn, request: Request) -> dict[str, Any]:
        st = _state(request)
        return _call(lambda: inputs.add_fd_rate_table(st.conn, body, st.clock()))

    return r
