"""Feature routes (Stage D): portfolios, holdings import, summary, watchlist, alerts, evidence, privacy, backup."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from iip.data.imports import MAX_IMPORT_BYTES, ImportRejected
from iip.services import alerts as alerts_svc
from iip.services import portfolio as pf


def _state(request: Request) -> Any:
    return request.app.state.iip


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"code": code, "message": message}, status_code=status)


def _guard(fn: Callable[[], Any]) -> Any:
    """Map domain refusals to JSON errors with a code; anything else falls through to the generic 500 handler."""
    try:
        return fn()
    except pf.PortfolioError as exc:
        return _error(exc.code, exc.message, exc.status)
    except ImportRejected as exc:
        return _error(exc.code, exc.message, exc.status)


def _tax_coverage() -> tuple[Any, bool]:
    from iip.api.routes_core import tax_rules  # noqa: PLC0415 - shared cached loader; avoids an import cycle

    rules = tax_rules()
    return (rules.coverage_to if rules is not None else None), rules is not None


def router() -> APIRouter:
    r = APIRouter(prefix="/api")

    # ------------------------------------------------------------------ portfolios & transactions
    @r.get("/portfolios")
    def list_portfolios(request: Request, nature: str | None = None) -> Any:
        return _guard(lambda: {"items": pf.list_portfolios(_state(request).conn, nature)})

    @r.post("/portfolios")
    def create_portfolio(body: pf.PortfolioIn, request: Request) -> Any:
        st = _state(request)
        return _guard(lambda: pf.create_portfolio(st.conn, body, st.clock()))

    @r.get("/portfolios/{portfolio_id}/transactions")
    def list_transactions(portfolio_id: str, request: Request) -> Any:
        return _guard(lambda: pf.list_transactions(_state(request).conn, portfolio_id))

    @r.post("/portfolios/{portfolio_id}/transactions")
    def add_transaction(portfolio_id: str, body: pf.TransactionIn, request: Request) -> Any:
        st = _state(request)
        return _guard(lambda: pf.add_transaction(st.conn, portfolio_id, body, st.clock()))

    @r.delete("/portfolios/{portfolio_id}/transactions/{txn_id}")
    def delete_transaction(portfolio_id: str, txn_id: str, request: Request) -> Any:
        st = _state(request)
        return _guard(lambda: pf.delete_transaction(st.conn, portfolio_id, txn_id, st.clock()))

    @r.get("/portfolios/{portfolio_id}/summary")
    def summary(portfolio_id: str, request: Request, maturity_days: Annotated[int, Query(ge=1, le=3650)] = 365) -> Any:
        st = _state(request)
        return _guard(lambda: pf.portfolio_summary(st.conn, portfolio_id, st.clock(), maturity_days=maturity_days))

    # ------------------------------------------------------------------ holdings import (preview → apply)
    @r.post("/holdings/import")
    def import_preview(
        request: Request,
        file: Annotated[UploadFile, File()],
        portfolio_id: Annotated[str, Form(min_length=1, max_length=64)],
        encoding: Annotated[str | None, Form(max_length=16)] = None,
    ) -> Any:
        st = _state(request)
        data = file.file.read(MAX_IMPORT_BYTES + 1)
        filename = file.filename or "upload"
        return _guard(lambda: pf.preview_holdings_import(st.conn, portfolio_id, data, filename, encoding, st.clock()))

    @r.post("/holdings/import/{batch_id}/apply")
    def import_apply(batch_id: str, body: pf.ApplyIn, request: Request) -> Any:
        st = _state(request)

        def pre_change() -> object:  # reliability-design §7.1: pre-change backup before every import apply
            return pf.make_backup(st.conn, st.settings.data_dir, st.clock(), tag="pre-import")

        return _guard(lambda: pf.apply_holdings_import(st.conn, batch_id, body.sha256, st.clock(),
                                                       pre_change=pre_change))  # fmt: skip

    # ------------------------------------------------------------------ watchlist
    @r.get("/watchlist")
    def get_watchlist(request: Request) -> Any:
        st = _state(request)
        return _guard(lambda: {"as_of": st.clock().isoformat(), "items": pf.watchlist(st.conn, st.clock())})

    @r.post("/watchlist")
    def add_watch(body: pf.WatchIn, request: Request) -> Any:
        st = _state(request)
        return _guard(lambda: pf.watch_add(st.conn, body, st.clock()))

    @r.delete("/watchlist/{instrument_id}")
    def delete_watch(instrument_id: str, request: Request) -> Any:
        st = _state(request)
        return _guard(lambda: pf.watch_delete(st.conn, instrument_id, st.clock()))

    # ------------------------------------------------------------------ alerts
    @r.get("/alerts")
    def get_alerts(request: Request, include_acknowledged: bool = True) -> Any:
        conn = _state(request).conn
        return {"items": alerts_svc.list_alerts(conn, include_acknowledged=include_acknowledged)}

    @r.get("/alerts/rules")
    def get_alert_rules(request: Request) -> Any:
        return alerts_svc.load_rules(_state(request).conn).model_dump()

    @r.put("/alerts/rules")
    def put_alert_rules(body: alerts_svc.AlertRules, request: Request) -> Any:
        return alerts_svc.save_rules(_state(request).conn, body).model_dump()

    @r.post("/alerts/evaluate")
    def evaluate_alerts(request: Request) -> Any:
        st = _state(request)
        coverage_to, loaded = _tax_coverage()
        return _guard(lambda: alerts_svc.evaluate(st.conn, st.clock(), tax_coverage_to=coverage_to,
                                                  tax_rules_loaded=loaded))  # fmt: skip

    @r.post("/alerts/{alert_id}/ack")
    def ack_alert(alert_id: str, request: Request) -> Any:
        st = _state(request)
        return _guard(lambda: alerts_svc.acknowledge(st.conn, alert_id, st.clock()))

    # ------------------------------------------------------------------ evidence
    @r.get("/evidence/{obs_id}")
    def get_evidence(obs_id: int, request: Request) -> Any:
        return _guard(lambda: pf.evidence(_state(request).conn, obs_id))

    # ------------------------------------------------------------------ privacy & backup
    @r.get("/privacy/inventory")
    def privacy_inventory(request: Request) -> Any:
        st = _state(request)
        return pf.inventory(st.conn, st.settings.data_dir)

    @r.get("/privacy/export")
    def privacy_export(request: Request) -> Any:
        st = _state(request)
        now = st.clock()
        name = f"iip-export-{now.date().isoformat()}.json"
        headers = {"Content-Disposition": f'attachment; filename="{name}"'}
        return JSONResponse(pf.export_all(st.conn, now), headers=headers)

    @r.get("/privacy/export.csv")
    def privacy_export_csv(request: Request) -> Any:
        st = _state(request)
        name = f"iip-transactions-{st.clock().date().isoformat()}.csv"
        return Response(
            pf.export_transactions_csv(st.conn),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @r.post("/privacy/erase")
    def privacy_erase(body: pf.EraseIn, request: Request) -> Any:
        st = _state(request)
        return _guard(lambda: pf.erase(st.conn, st.settings.data_dir, delete_backups=body.delete_backups))

    @r.post("/backup")
    def make_backup(request: Request) -> Any:
        st = _state(request)
        return _guard(lambda: pf.make_backup(st.conn, st.settings.data_dir, st.clock()))

    return r
