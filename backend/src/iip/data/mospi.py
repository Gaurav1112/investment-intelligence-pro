"""MoSPI CPI adapter (source ``mospi.cpi``; source-registry.md §2.12; audit-automation.md §3.1). No credentials.

MoSPI's eSankhyiki API answers *filtered* queries without a login: one (base, year, month) query filtered to All
India, Combined and the general index returns exactly one record, under the unauthenticated 10-record page cap.

* Base 2024 uses ``/api/cpi/getCPIData`` (All India = state 1, division ``"CPI (General)"``); its rows carry
  ``base_year`` and **no** provisional/final ``status`` field.
* Base 2012 uses ``/api/cpi/getCPIIndex`` (All India = state 99, group ``"General"``); its rows carry ``baseyear``
  and ``status`` ``P``/``F``.

The parser never fabricates: a response that is not ``statusCode: true`` with ``meta_data.totalRecords == 1`` and
exactly one matching row, or any schema surprise, is refused and nothing is stored. The two bases are separate
series and are never spliced. A provisional flag is never invented: base-2024 rows have no status, so
``status_flag`` is ``None`` and ``provisional`` is ``True`` ("not confirmed final by the source"; a later revision
appends). Status: endpoints and record shapes VERIFIED by probe (audit-automation.md §3.1, re-probed 2026-10-16);
the adapter's own live run is NOT VERIFIED until the first scheduled fetch.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from iip.data.fetch import Fetcher
from iip.data.models import RawPayload, SchemaChanged
from iip.data.registry import mospi_cpi_request

ADAPTER_ID = "mospi.cpi@0.2.0"
UNAUTH_RECORD_CAP = 10
#: Environment variables the pre-0.2 adapter read. They are no longer used; ``status`` says so if they are set.
LEGACY_ENV_VARS = ("IIP_MOSPI_TOKEN", "IIP_MOSPI_USER", "IIP_MOSPI_PASSWORD")

#: The general-index label for each base, compared case-insensitively (probe 2026-10-16).
GENERAL_LABELS: Mapping[int, frozenset[str]] = {
    2012: frozenset({"general", "general index", "all groups", "general index (all groups)"}),
    2024: frozenset({"cpi (general)"}),
}
_LABEL_FIELD = {2012: "group", 2024: "division"}
_MONTHS = (
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
    "december",
)  # fmt: skip


@dataclass(frozen=True)
class MospiConfig:
    """Kept for API compatibility. The adapter is always anonymous; ``ignored_env`` lists legacy variables set."""

    method: Literal["anonymous"] = "anonymous"
    ignored_env: tuple[str, ...] = ()


def config_from_env(environ: Mapping[str, str] | None = None) -> MospiConfig:
    env = os.environ if environ is None else environ
    return MospiConfig(ignored_env=tuple(v for v in LEGACY_ENV_VARS if env.get(v, "").strip()))


def status(config: MospiConfig) -> dict[str, Any]:
    """Status for the UI. Never includes a credential value (only the names of ignored variables)."""
    message = (
        "MoSPI's CPI API answers filtered single-record queries without a login, so nothing needs configuring. "
        "The endpoints were checked by probe; check the first fetched values against the MoSPI release."
    )
    if config.ignored_env:
        message += f" Ignored (no longer used): {', '.join(config.ignored_env)}."
    return {
        "source_id": "mospi.cpi",
        # "CONFIGURED" keeps the existing UI contract (frontend MospiStatus): ready to fetch, nothing to set up.
        "status": "CONFIGURED",
        "method": config.method,
        "requires_configuration": False,
        "env_vars": [],
        "ignored_env_vars": list(config.ignored_env),
        "verified": False,
        "message": message,
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
    provisional: bool  # True unless the source marks the month final ("F")
    raw: RawPayload
    status_flag: Literal["P", "F"] | None = None  # as published; None when the source has no status field
    convention: str = ""


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def parse_cpi_month(payload: RawPayload, *, base_year: int, year: int, month: int) -> CpiRecord:
    """Exactly one All-India / Combined general-index record for the requested month, or refuse."""
    if base_year not in GENERAL_LABELS:
        raise ValueError("base_year must be 2012 or 2024")
    try:
        doc = json.loads(payload.content)
    except ValueError as exc:
        raise SchemaChanged("MoSPI CPI response is not JSON") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("data"), list):
        raise SchemaChanged("MoSPI CPI response has no 'data' list")
    meta = doc.get("meta_data")
    total = meta.get("totalRecords") if isinstance(meta, dict) else None
    if isinstance(total, bool) or not isinstance(total, int):
        raise SchemaChanged("MoSPI CPI response has no integer meta_data.totalRecords")
    rows = [r for r in doc["data"] if isinstance(r, dict)]
    if len(rows) != len(doc["data"]):
        raise SchemaChanged("MoSPI CPI 'data' holds a non-object row")
    if total > len(rows):
        raise MospiError(
            "TRUNCATED_RESPONSE",
            f"{len(rows)} of {total} records returned (page cap {UNAUTH_RECORD_CAP}); the query was not filtered "
            "to one record, so nothing is stored",
        )
    if doc.get("statusCode") is not True:
        raise MospiError("SOURCE_ERROR", f"MoSPI answered statusCode={doc.get('statusCode')!r}; nothing stored")
    if total != 1 or len(rows) != 1:
        raise MospiError("NO_MATCHING_RECORD", f"expected exactly one record, totalRecords={total}; nothing stored")
    r = rows[0]
    published_base = _text(r.get("base_year") if "base_year" in r else r.get("baseyear"))
    if not (
        published_base == str(base_year)
        and _text(r.get("state")).lower() == "all india"
        and _text(r.get("sector")).lower() == "combined"
        and _text(r.get(_LABEL_FIELD[base_year])).lower() in GENERAL_LABELS[base_year]
        and _text(r.get("year")) == str(year)
        and _text(r.get("month")).lower() == _MONTHS[month - 1]
        and _text(r.get("series") or "Current").lower() == "current"
    ):
        raise MospiError(
            "NO_MATCHING_RECORD",
            "the record is not the All-India Combined general index for the requested base and month; nothing stored",
        )
    try:
        index = Decimal(_text(r.get("index")))
        raw_yoy = r.get("inflation")
        yoy = None if raw_yoy in (None, "") else Decimal(_text(raw_yoy))
    except InvalidOperation as exc:
        raise SchemaChanged("index/inflation is not a decimal") from exc
    if not index.is_finite() or index <= 0:
        raise SchemaChanged("index must be a positive finite number")
    if yoy is not None and not yoy.is_finite():
        raise SchemaChanged("inflation must be finite")
    flag_text = _text(r.get("status")).upper()
    if "status" in r and flag_text not in ("P", "F"):
        raise SchemaChanged(f"unrecognised status flag {flag_text!r}")
    flag: Literal["P", "F"] | None = "P" if flag_text == "P" else "F" if flag_text == "F" else None
    return CpiRecord(
        base_year=str(base_year),
        year=year,
        month=month,
        index=index,
        yoy_pct=yoy,
        provisional=flag != "F",
        raw=payload,
        status_flag=flag,
        convention=f"CPI_COMBINED_GENERAL_INDEX_BASE{base_year}",
    )


def fetch_cpi_month(
    config: MospiConfig | None, fetcher: Fetcher, *, base_year: int, year: int, month: int
) -> CpiRecord:
    """Anonymous filtered GET, then ``parse_cpi_month``. ``config`` is accepted for API compatibility only."""
    del config  # no credentials are ever sent
    payload = fetcher.fetch(mospi_cpi_request(base_year=base_year, year=year, month=month))
    return parse_cpi_month(payload, base_year=base_year, year=year, month=month)
