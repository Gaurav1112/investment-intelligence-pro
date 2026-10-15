"""MoSPI CPI adapter (source ``mospi.cpi``; source-registry.md §2.12). REQUIRES CONFIGURATION.

The API needs the user's own MoSPI account. Configuration comes from the environment, never from a request:

* ``IIP_MOSPI_TOKEN`` — a bearer token the user obtained (tokens expire after about 15 minutes), or
* ``IIP_MOSPI_USER`` + ``IIP_MOSPI_PASSWORD`` — the adapter logs in (``POST /api/login``) for a token.

Unconfigured, the adapter returns ``REQUIRES_CONFIGURATION`` and makes no request. It never fabricates data: an
unauthenticated response capped at 10 records, an unrecognised login response, a payload without exactly one
All-India Combined general-index record, or any schema surprise is refused. Status: IMPLEMENTED, NOT VERIFIED — no
authenticated call has been made (the login body field names and the general-index labels are taken from the public
manual/Swagger and could not be confirmed; base-2024 retrieval is unverified, registry §2.12).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from iip.data.fetch import Fetcher
from iip.data.models import RawPayload, SchemaChanged
from iip.data.registry import mospi_cpi_request, mospi_login_request

ENV_TOKEN = "IIP_MOSPI_TOKEN"  # noqa: S105 - the NAME of an environment variable, not a secret
ENV_USER = "IIP_MOSPI_USER"
ENV_PASSWORD = "IIP_MOSPI_PASSWORD"  # noqa: S105 - the NAME of an environment variable, not a secret
ADAPTER_ID = "mospi.cpi@0.1.0"
UNAUTH_RECORD_CAP = 10
_GENERAL_LABELS = frozenset({"general", "general index", "all groups", "general index (all groups)"})


@dataclass(frozen=True)
class MospiConfig:
    method: Literal["token", "password"] | None
    token: str | None = field(default=None, repr=False)
    user: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)


def config_from_env(environ: Mapping[str, str] | None = None) -> MospiConfig:
    env = os.environ if environ is None else environ
    token = env.get(ENV_TOKEN, "").strip()
    user = env.get(ENV_USER, "").strip()
    password = env.get(ENV_PASSWORD, "")
    if token:
        return MospiConfig("token", token=token)
    if user and password:
        return MospiConfig("password", user=user, password=password)
    return MospiConfig(None)


def status(config: MospiConfig) -> dict[str, Any]:
    """Configuration status for the UI. Never includes a credential."""
    common = {"source_id": "mospi.cpi", "env_vars": [ENV_TOKEN, ENV_USER, ENV_PASSWORD], "verified": False}
    if config.method is None:
        return {
            **common,
            "status": "REQUIRES_CONFIGURATION",
            "method": None,
            "message": (
                f"MoSPI's CPI API needs your own account. Set {ENV_TOKEN}, or {ENV_USER} and {ENV_PASSWORD}, in the "
                "environment that starts the app. Until then, enter CPI values by hand with a citation."
            ),
        }
    return {
        **common,
        "status": "CONFIGURED",
        "method": config.method,
        "message": (
            "Credentials found in the environment. The adapter is NOT VERIFIED against an authenticated call; "
            "check fetched values against the MoSPI release before relying on them."
        ),
    }


class MospiError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CpiRecord:
    base_year: str
    year: int
    month: int
    index: Decimal
    yoy_pct: Decimal | None  # as published (percent)
    provisional: bool
    raw: RawPayload


def _token_from_login(payload: RawPayload) -> str:
    try:
        doc = json.loads(payload.content)
    except ValueError as exc:
        raise MospiError("LOGIN_RESPONSE_UNRECOGNISED", "login response is not JSON") from exc
    candidates: list[Any] = []
    if isinstance(doc, dict):
        candidates += [doc.get(k) for k in ("access_token", "accessToken", "token")]
        data = doc.get("data")
        if isinstance(data, dict):
            candidates += [data.get(k) for k in ("access_token", "accessToken", "token")]
    for c in candidates:
        if isinstance(c, str) and c.strip():
            return c.strip()
    raise MospiError("LOGIN_RESPONSE_UNRECOGNISED", "no access token found in the login response")


def _token(config: MospiConfig, fetcher: Fetcher) -> str:
    if config.method == "token" and config.token:
        return config.token
    if config.method == "password" and config.user and config.password:
        body = json.dumps({"username": config.user, "password": config.password}).encode()
        return _token_from_login(fetcher.fetch(mospi_login_request(body)))
    raise MospiError("REQUIRES_CONFIGURATION", "MoSPI credentials are not configured")


def _month_name(month: int) -> str:
    return (
        "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
        "November", "December",
    )[month - 1]  # fmt: skip


def parse_cpi_month(payload: RawPayload, *, base_year: int, year: int, month: int) -> CpiRecord:
    """Exactly one All-India / Combined general-index record for the requested month, or refuse."""
    try:
        doc = json.loads(payload.content)
    except ValueError as exc:
        raise SchemaChanged("MoSPI CPI response is not JSON") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("data"), list):
        raise SchemaChanged("MoSPI CPI response has no 'data' list")
    rows = [r for r in doc["data"] if isinstance(r, dict)]
    if len(rows) == UNAUTH_RECORD_CAP:
        raise MospiError(
            "UNAUTHENTICATED_CAP",
            "exactly 10 records returned — the unauthenticated cap; the token was not accepted, so nothing is stored",
        )
    matches = []
    for r in rows:
        label = str(r.get("group") or r.get("division") or "").strip().lower()
        sub = str(r.get("subgroup") or "").strip().lower()
        if (
            str(r.get("state", "")).strip().lower() == "all india"
            and str(r.get("sector", "")).strip().lower() == "combined"
            and (label in _GENERAL_LABELS or sub in _GENERAL_LABELS)
            and str(r.get("baseyear", "")) == str(base_year)
            and str(r.get("year", "")) == str(year)
            and str(r.get("month", "")).strip().lower() == _month_name(month).lower()
        ):
            matches.append(r)
    if len(matches) != 1:
        raise MospiError(
            "NO_MATCHING_RECORD",
            f"expected exactly one All-India Combined general-index record, found {len(matches)}; nothing stored",
        )
    r = matches[0]
    try:
        index = Decimal(str(r["index"]))
        yoy = None if r.get("inflation") in (None, "") else Decimal(str(r["inflation"]))
    except (KeyError, InvalidOperation) as exc:
        raise SchemaChanged("index/inflation is not a decimal") from exc
    if not index.is_finite() or index <= 0:
        raise SchemaChanged("index must be positive")
    status_flag = str(r.get("status", "")).strip().upper()
    return CpiRecord(str(base_year), year, month, index, yoy, status_flag == "P", payload)


def fetch_cpi_month(config: MospiConfig, fetcher: Fetcher, *, base_year: int, year: int, month: int) -> CpiRecord:
    if config.method is None:
        raise MospiError("REQUIRES_CONFIGURATION", "MoSPI credentials are not configured")
    token = _token(config, fetcher)
    payload = fetcher.fetch(mospi_cpi_request(base_year=base_year, year=year, month=month, bearer_token=token))
    return parse_cpi_month(payload, base_year=base_year, year=year, month=month)
