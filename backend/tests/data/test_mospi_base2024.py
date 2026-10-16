"""MoSPI CPI adapter, base 2024 and base 2012, with no credentials (audit-automation.md §3.1, PLAN A07).

All payloads are SYNTHETIC: they copy the record *shape* of the 2026-10-15/16 probes (field names, types, the
single-record ``meta_data``) with fictional index values. No real CPI value is committed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

from iip.data import mospi, registry
from iip.data.fetch import Fetcher, RetryPolicy
from iip.data.models import FetchRefused, RawPayload, SchemaChanged
from iip.data.registry import SourceRequest, get_source, mospi_cpi_request

NOW = datetime(2099, 2, 20, 6, 0, tzinfo=UTC)

# Base 2024 (getCPIData) row shape: base_year, string year, division label, no status field. Fictional values.
ROW_2024: dict[str, Any] = {
    "base_year": "2024", "series": "Current", "year": "2099", "month": "January", "state": "All India",
    "sector": "Combined", "division": "CPI (General)", "group": None, "class": None, "sub_class": None,
    "item": None, "code": None, "index": "111.11", "inflation": "2.22", "imputation": None,
}  # fmt: skip
# Base 2012 (getCPIIndex) row shape: baseyear, integer year, group/subgroup labels, status P/F. Fictional values.
ROW_2012: dict[str, Any] = {
    "baseyear": "2012", "year": 2099, "month": "January", "state": "All India", "sector": "Combined",
    "group": "General", "subgroup": "General-Overall", "index": "333.3", "inflation": "4.44", "status": "F",
}  # fmt: skip


def doc(*rows: dict[str, Any], total: int | None = None, ok: bool = True) -> dict[str, Any]:
    n = len(rows) if total is None else total
    return {
        "data": list(rows),
        "meta_data": {"page": 1, "totalRecords": n, "totalPages": 1, "recordPerPage": 10},
        "msg": "Data fetched successfully" if ok else "No Data Found",
        "statusCode": ok,
    }


def payload(body: object) -> RawPayload:
    return RawPayload.from_bytes(source_id="mospi.cpi", final_url="https://api.mospi.gov.in/api/cpi/getCPIData",
                                 retrieved_at=NOW, content=json.dumps(body).encode(),
                                 content_type="application/json", last_modified=None)  # fmt: skip


def fetcher(handler: Callable[[httpx.Request], httpx.Response]) -> Fetcher:
    return Fetcher(transport=httpx.MockTransport(handler), resolver=lambda _h: ["23.0.0.1"], jitter_seed=1,
                   sleep=lambda _s: None, clock=lambda: NOW, retry=RetryPolicy(max_attempts=1))  # fmt: skip


# ------------------------------------------------------------------------------------------- request building


def test_base_2024_uses_getcpidata_with_the_all_india_filters() -> None:
    url = httpx.URL(mospi_cpi_request(base_year=2024, year=2099, month=1).url)
    assert url.host == "api.mospi.gov.in" and url.path == "/api/cpi/getCPIData"
    assert dict(url.params) == {
        "base_year": "2024", "series": "Current", "year": "2099", "month_code": "1", "state_code": "1",
        "sector_code": "3", "division_code": "0", "Format": "JSON",
    }  # fmt: skip
    back = httpx.URL(mospi_cpi_request(base_year=2024, year=2024, month=12, series="Back").url)
    assert back.params["series"] == "Back"


def test_base_2012_uses_getcpiindex_with_the_all_india_filters() -> None:
    url = httpx.URL(mospi_cpi_request(base_year=2012, year=2099, month=1).url)
    assert url.path == "/api/cpi/getCPIIndex"
    assert dict(url.params) == {
        "base_year": "2012", "series": "Current", "year": "2099", "month_code": "1", "state_code": "99",
        "sector_code": "3", "group_code": "0", "Format": "JSON",
    }  # fmt: skip


@pytest.mark.parametrize(
    "kwargs",
    [{"base_year": 2019, "year": 2099, "month": 1}, {"base_year": 2024, "year": 2099, "month": 13},
     {"base_year": 2012, "year": 2099, "month": 1, "series": "Back"},
     {"base_year": 2024, "year": 2099, "month": 1, "series": "Current&x=1"}],
)  # fmt: skip
def test_request_builder_rejects_bad_parameters(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        mospi_cpi_request(**kwargs)


def test_mospi_needs_no_credentials_and_refuses_them() -> None:
    spec = get_source("mospi.cpi")
    assert spec.requires_configuration is False
    assert not hasattr(registry, "mospi_login_request")
    req = mospi_cpi_request(base_year=2024, year=2099, month=1)
    assert req.method == "GET" and req.bearer_token is None and not req.authenticated
    with pytest.raises(FetchRefused):
        SourceRequest(spec, req.url, bearer_token="tok")
    with pytest.raises(FetchRefused):
        SourceRequest(spec, "https://api.mospi.gov.in/api/login", method="POST", body=b"{}")


# ------------------------------------------------------------------------------------------- configuration


def test_status_is_ready_to_fetch_without_any_environment() -> None:
    st = mospi.status(mospi.config_from_env({}))
    assert st["status"] == "CONFIGURED" and st["requires_configuration"] is False and st["env_vars"] == []
    assert st["verified"] is False and mospi.config_from_env({}).method == "anonymous"


def test_legacy_credentials_are_ignored_and_never_revealed() -> None:
    env = {"IIP_MOSPI_TOKEN": "tok-secret", "IIP_MOSPI_USER": "me@example.test", "IIP_MOSPI_PASSWORD": "pw-secret"}
    cfg = mospi.config_from_env(env)
    st = mospi.status(cfg)
    assert st["status"] == "CONFIGURED" and set(st["ignored_env_vars"]) == set(env)
    text = json.dumps(st) + repr(cfg)
    assert "tok-secret" not in text and "pw-secret" not in text and "me@example.test" not in text


# ------------------------------------------------------------------------------------------- parsing


def test_parses_a_base_2024_record_without_inventing_a_status() -> None:
    rec = mospi.parse_cpi_month(payload(doc(ROW_2024)), base_year=2024, year=2099, month=1)
    assert (rec.base_year, rec.year, rec.month) == ("2024", 2099, 1)
    assert rec.index == Decimal("111.11") and rec.yoy_pct == Decimal("2.22")
    assert rec.status_flag is None and rec.provisional is True  # not confirmed final; never invented as final
    assert rec.convention == "CPI_COMBINED_GENERAL_INDEX_BASE2024"


@pytest.mark.parametrize(("flag", "provisional"), [("F", False), ("P", True)])
def test_parses_a_base_2012_record_with_its_published_status(flag: str, provisional: bool) -> None:
    rec = mospi.parse_cpi_month(payload(doc({**ROW_2012, "status": flag})), base_year=2012, year=2099, month=1)
    assert rec.index == Decimal("333.3") and rec.yoy_pct == Decimal("4.44")
    assert rec.status_flag == flag and rec.provisional is provisional
    assert rec.convention == "CPI_COMBINED_GENERAL_INDEX_BASE2012"


@pytest.mark.parametrize(
    ("row", "base"),
    [({**ROW_2024, "division": "Food and beverages"}, 2024), ({**ROW_2024, "sector": "Urban"}, 2024),
     ({**ROW_2024, "state": "Kerala"}, 2024), ({**ROW_2024, "base_year": "2012"}, 2024),
     ({**ROW_2024, "month": "February"}, 2024), ({**ROW_2024, "year": "2098"}, 2024),
     ({**ROW_2024, "series": "Back"}, 2024),
     ({k: v for k, v in ROW_2024.items() if k != "division"} | {"group": "General"}, 2024),  # 2012 label, 2024 base
     (ROW_2024, 2012), ({**ROW_2012, "group": "CPI (General)"}, 2012)],
)  # fmt: skip
def test_any_mismatch_with_the_requested_record_stores_nothing(row: dict[str, Any], base: int) -> None:
    with pytest.raises(mospi.MospiError) as e:
        mospi.parse_cpi_month(payload(doc(row)), base_year=base, year=2099, month=1)
    assert e.value.code == "NO_MATCHING_RECORD"


def test_more_or_fewer_than_one_record_is_refused() -> None:
    with pytest.raises(mospi.MospiError) as e:
        mospi.parse_cpi_month(payload(doc(ROW_2024, ROW_2024)), base_year=2024, year=2099, month=1)
    assert e.value.code == "NO_MATCHING_RECORD"
    with pytest.raises(mospi.MospiError) as e:
        mospi.parse_cpi_month(payload(doc(ok=False)), base_year=2024, year=2099, month=1)
    assert e.value.code == "SOURCE_ERROR"


def test_a_truncated_page_is_refused() -> None:
    rows = [{**ROW_2024, "division": f"d{i}"} for i in range(10)]
    with pytest.raises(mospi.MospiError) as e:
        mospi.parse_cpi_month(payload(doc(*rows, total=84)), base_year=2024, year=2099, month=1)
    assert e.value.code == "TRUNCATED_RESPONSE"


@pytest.mark.parametrize(
    "body",
    [{"rows": []}, {"data": [ROW_2024]}, {"data": [ROW_2024], "meta_data": {"totalRecords": "1"}, "statusCode": True},
     doc({**ROW_2024, "index": "n/a"}), doc({**ROW_2024, "index": "0"}), doc({**ROW_2024, "index": "-1"}),
     doc({**ROW_2024, "index": "NaN"}), doc({**ROW_2024, "inflation": "Infinity"}), doc({**ROW_2012, "status": "X"}),
     {**doc(ROW_2024), "data": [ROW_2024, "x"]}],
)  # fmt: skip
def test_schema_surprises_fail_closed(body: dict[str, Any]) -> None:
    base = 2012 if body.get("data") and isinstance(body["data"][0], dict) and "baseyear" in body["data"][0] else 2024
    with pytest.raises((SchemaChanged, mospi.MospiError)):
        mospi.parse_cpi_month(payload(body), base_year=base, year=2099, month=1)


# ------------------------------------------------------------------------------------------- fetch (mocked)


@pytest.mark.parametrize(("base", "row", "path"), [(2024, ROW_2024, "/api/cpi/getCPIData"),
                                                   (2012, ROW_2012, "/api/cpi/getCPIIndex")])  # fmt: skip
def test_fetch_is_an_anonymous_get_even_with_legacy_env(base: int, row: dict[str, Any], path: str) -> None:
    seen: list[httpx.Request] = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        return httpx.Response(200, headers={"content-type": "application/json"}, json=doc(row))

    cfg = mospi.config_from_env({"IIP_MOSPI_TOKEN": "tok-secret"})
    rec = mospi.fetch_cpi_month(cfg, fetcher(handler), base_year=base, year=2099, month=1)
    assert rec.base_year == str(base)
    (req,) = seen
    assert req.method == "GET" and req.url.path == path and "authorization" not in req.headers
    assert "tok-secret" not in str(req.url) and req.content == b""
    assert "mozilla" not in req.headers["user-agent"].lower()
