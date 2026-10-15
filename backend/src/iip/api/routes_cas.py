"""CAS (CAMS/KFintech PDF) import routes: multipart preview → JSON apply.

The multipart body is parsed **in memory** here instead of through FastAPI ``File()``/``Form()``: Starlette spools
uploaded files larger than 1 MiB to a temporary file on disk, and the CAS PDF (personal data) must never touch
disk. The request body is already capped by the security middleware (``Settings.max_body_bytes``)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from python_multipart.multipart import MultipartParser, parse_options_header

from iip.api.routes_portfolio import _error, _guard, _state, pre_import_safeguard
from iip.services import cas, ingestion

MAX_PARTS = 8
MAX_FIELD_BYTES = 1024


class _FormError(Exception):
    pass


def parse_form_in_memory(content_type: str, body: bytes) -> dict[str, tuple[str | None, bytes]]:
    """multipart/form-data → {field name: (filename or None, bytes)}. Memory only; duplicate fields are refused."""
    ctype, params = parse_options_header(content_type)
    boundary = params.get(b"boundary")
    if ctype != b"multipart/form-data" or not boundary:
        raise _FormError("not multipart/form-data")
    parts: list[tuple[list[tuple[bytes, bytes]], bytearray]] = []
    field_name = bytearray()
    field_value = bytearray()

    def on_part_begin() -> None:
        if len(parts) >= MAX_PARTS:
            raise _FormError("too many parts")
        parts.append(([], bytearray()))

    def on_part_data(data: bytes, start: int, end: int) -> None:
        parts[-1][1].extend(data[start:end])

    def on_header_field(data: bytes, start: int, end: int) -> None:
        field_name.extend(data[start:end])

    def on_header_value(data: bytes, start: int, end: int) -> None:
        field_value.extend(data[start:end])

    def on_header_end() -> None:
        parts[-1][0].append((bytes(field_name).lower(), bytes(field_value)))
        field_name.clear()
        field_value.clear()

    parser = MultipartParser(
        boundary,
        {
            "on_part_begin": on_part_begin,
            "on_part_data": on_part_data,
            "on_header_field": on_header_field,
            "on_header_value": on_header_value,
            "on_header_end": on_header_end,
        },
    )
    try:
        parser.write(body)
        parser.finalize()
    except _FormError:
        raise
    except Exception as exc:
        raise _FormError("malformed multipart body") from exc
    out: dict[str, tuple[str | None, bytes]] = {}
    for headers, data in parts:
        disposition = next((v for k, v in headers if k == b"content-disposition"), None)
        _, opts = parse_options_header(disposition)
        name = opts.get(b"name")
        if not name:
            raise _FormError("part without a name")
        key = name.decode("utf-8", "replace")
        if key in out:
            raise _FormError("duplicate field")
        filename = opts.get(b"filename")
        out[key] = (None if filename is None else filename.decode("utf-8", "replace"), bytes(data))
    return out


def router() -> APIRouter:
    r = APIRouter(prefix="/api")

    @r.post("/holdings/import-cas")
    async def import_cas_preview(request: Request) -> Any:
        st = _state(request)
        body = await request.body()
        try:
            form = parse_form_in_memory(request.headers.get("content-type", ""), body)
        except _FormError:
            return _error("BAD_FORM", "expected multipart/form-data with file, password and portfolio_id", 422)
        del body
        file_part = form.get("file")
        pid_part = form.get("portfolio_id")
        pw_part = form.get("password", (None, b""))
        if file_part is None or file_part[0] is None or pid_part is None:
            return _error("BAD_FORM", "the file and portfolio_id fields are required", 422)
        if len(pid_part[1]) > 64 or len(pw_part[1]) > MAX_FIELD_BYTES:
            return _error("BAD_FORM", "a form field is too long", 422)
        try:
            portfolio_id = pid_part[1].decode("utf-8")
            password = pw_part[1].decode("utf-8")
        except UnicodeDecodeError:
            return _error("BAD_FORM", "form fields must be UTF-8 text", 422)
        data = file_part[1]
        del form, pw_part
        return await run_in_threadpool(
            lambda: _guard(
                lambda: cas.preview_cas_import(
                    st.conn,
                    portfolio_id,
                    data,
                    password,
                    st.clock(),
                    resolve_isins=lambda isins: ingestion.register_schemes_by_isin(
                        st.conn, st.fetcher(), isins, st.clock
                    ),
                )
            )
        )

    @r.post("/holdings/import-cas/{batch_id}/apply")
    def import_cas_apply(batch_id: str, body: cas.CasApplyIn, request: Request) -> Any:
        st = _state(request)
        pre_change = pre_import_safeguard(st)  # reliability-design §7.1 (file backup locally, snapshot hosted)
        return _guard(lambda: cas.apply_cas_import(st.conn, batch_id, body, st.clock(), pre_change=pre_change))

    return r
