"""MoSPI CPI adapter (no credentials). No real network: httpx.MockTransport + a stubbed resolver.

The 10-record payload is SYNTHETIC: it copies the shape of the real unfiltered probe of 2026-10-15 (10 records,
``meta_data.totalRecords`` 84, last record with null index; see docs/data/probes/README.md) with fictional index
values. The other payloads are hand-made TEST bodies in the documented base-2024 record shape (not CPI data).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from iip.data import mospi
from iip.data.fetch import Fetcher, RetryPolicy
from iip.data.models import FetchRefused, RawPayload
from iip.data.registry import SourceRequest, get_source, mospi_cpi_request, navall_request

NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
PROBE = Path(__file__).resolve().parents[1] / "fixtures/data/mospi_cpi_unauth10_synthetic.json"
GENERAL = {"base_year": "2024", "series": "Current", "year": "2026", "month": "September", "state": "All India",
           "sector": "Combined", "division": "CPI (General)", "index": "123.4", "inflation": "1.11"}  # fmt: skip


def fetcher(handler: Callable[[httpx.Request], httpx.Response]) -> Fetcher:
    return Fetcher(transport=httpx.MockTransport(handler), resolver=lambda _h: ["23.0.0.1"], jitter_seed=1,
                   sleep=lambda _s: None, clock=lambda: NOW, retry=RetryPolicy(max_attempts=1))  # fmt: skip


def payload(body: object) -> RawPayload:
    return RawPayload.from_bytes(source_id="mospi.cpi", final_url="https://api.mospi.gov.in/api/cpi/getCPIIndex",
                                 retrieved_at=NOW, content=json.dumps(body).encode(),
                                 content_type="application/json", last_modified=None)  # fmt: skip


# ----------------------------------------------------------------------------------------- truncation and policy
# Base-2024/2012 parsing, request building and the no-credentials contract: tests/data/test_mospi_base2024.py.


def test_unfiltered_ten_record_page_is_refused_using_the_probe_shape() -> None:
    body = json.loads(PROBE.read_text())
    assert len(body["data"]) == 10
    with pytest.raises(mospi.MospiError) as e:
        mospi.parse_cpi_month(payload(body), base_year=2012, year=2025, month=12)
    assert e.value.code == "TRUNCATED_RESPONSE"


def test_parses_exactly_one_all_india_combined_general_record() -> None:
    body = {"data": [GENERAL], "meta_data": {"totalRecords": 1}, "statusCode": True}
    rec = mospi.parse_cpi_month(payload(body), base_year=2024, year=2026, month=9)
    assert (rec.base_year, rec.year, rec.month, str(rec.index), str(rec.yoy_pct), rec.provisional) == (
        "2024", 2026, 9, "123.4", "1.11", True)  # fmt: skip


def test_no_request_is_ever_authenticated() -> None:
    seen: list[httpx.Request] = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        body = {"data": [GENERAL], "meta_data": {"totalRecords": 1}, "statusCode": True}
        return httpx.Response(200, headers={"content-type": "application/json"}, json=body)

    mospi.fetch_cpi_month(mospi.config_from_env({"IIP_MOSPI_TOKEN": "tok-123"}), fetcher(handler), base_year=2024,
                          year=2026, month=9)  # fmt: skip
    (req,) = seen
    assert req.url.host == "api.mospi.gov.in" and "authorization" not in req.headers
    assert req.url.path == "/api/cpi/getCPIData" and "state_code=99" not in str(req.url)


def test_only_sources_that_require_configuration_may_authenticate() -> None:
    with pytest.raises(FetchRefused):
        SourceRequest(get_source("amfi.navall"), navall_request().url, bearer_token="tok")
    with pytest.raises(FetchRefused):
        SourceRequest(get_source("amfi.navall"), navall_request().url, method="POST", body=b"{}")
    with pytest.raises(FetchRefused):
        SourceRequest(get_source("mospi.cpi"), mospi_cpi_request(base_year=2024, year=2026, month=9).url,
                      bearer_token="tok")  # fmt: skip
    with pytest.raises(ValueError):
        mospi_cpi_request(base_year=2019, year=2026, month=9)
