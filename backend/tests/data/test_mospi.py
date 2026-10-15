"""MoSPI CPI adapter (REQUIRES CONFIGURATION). No real network: httpx.MockTransport + a stubbed resolver.

The 10-record payload is SYNTHETIC: it copies the shape of the real unauthenticated probe of 2026-10-15 (10 records,
``meta_data.totalRecords`` 84, last record with null index; see docs/data/probes/README.md) with fictional index
values. The "authenticated" payloads are hand-made TEST bodies in the documented record shape (not CPI data).
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
from iip.data.models import FetchRefused, RawPayload, SchemaChanged
from iip.data.registry import SourceRequest, get_source, mospi_cpi_request, navall_request

NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
PROBE = Path(__file__).resolve().parents[1] / "fixtures/data/mospi_cpi_unauth10_synthetic.json"
GENERAL = {"baseyear": "2024", "year": 2026, "month": "September", "state": "All India", "sector": "Combined",
           "group": "General", "subgroup": "General", "index": "123.4", "inflation": "1.11", "status": "P"}  # fmt: skip


def fetcher(handler: Callable[[httpx.Request], httpx.Response]) -> Fetcher:
    return Fetcher(transport=httpx.MockTransport(handler), resolver=lambda _h: ["23.0.0.1"], jitter_seed=1,
                   sleep=lambda _s: None, clock=lambda: NOW, retry=RetryPolicy(max_attempts=1))  # fmt: skip


def payload(body: object) -> RawPayload:
    return RawPayload.from_bytes(source_id="mospi.cpi", final_url="https://api.mospi.gov.in/api/cpi/getCPIIndex",
                                 retrieved_at=NOW, content=json.dumps(body).encode(),
                                 content_type="application/json", last_modified=None)  # fmt: skip


# ----------------------------------------------------------------------------------------- configuration


def test_unconfigured_status_names_the_env_vars_and_makes_no_request() -> None:
    cfg = mospi.config_from_env({})
    st = mospi.status(cfg)
    assert st["status"] == "REQUIRES_CONFIGURATION" and st["method"] is None and st["verified"] is False
    assert set(st["env_vars"]) == {"IIP_MOSPI_TOKEN", "IIP_MOSPI_USER", "IIP_MOSPI_PASSWORD"}

    def boom(_r: httpx.Request) -> httpx.Response:
        raise AssertionError("no request may be made when unconfigured")

    with pytest.raises(mospi.MospiError) as e:
        mospi.fetch_cpi_month(cfg, fetcher(boom), base_year=2024, year=2026, month=9)
    assert e.value.code == "REQUIRES_CONFIGURATION"


def test_configured_status_never_reveals_credentials() -> None:
    cfg = mospi.config_from_env({"IIP_MOSPI_USER": "me@example.test", "IIP_MOSPI_PASSWORD": "s3cret-value"})
    st = mospi.status(cfg)
    assert st["status"] == "CONFIGURED" and st["method"] == "password"
    assert "s3cret-value" not in json.dumps(st) and "s3cret-value" not in repr(cfg)
    tok = mospi.config_from_env({"IIP_MOSPI_TOKEN": "tok-123", "IIP_MOSPI_USER": "u", "IIP_MOSPI_PASSWORD": "p"})
    assert tok.method == "token" and "tok-123" not in repr(tok)
    assert mospi.config_from_env({"IIP_MOSPI_USER": "only-user"}).method is None


# ----------------------------------------------------------------------------------------- parsing


def test_unauthenticated_ten_record_cap_is_refused_using_the_probe_shape() -> None:
    body = json.loads(PROBE.read_text())
    assert len(body["data"]) == 10
    with pytest.raises(mospi.MospiError) as e:
        mospi.parse_cpi_month(payload(body), base_year=2012, year=2025, month=12)
    assert e.value.code == "UNAUTHENTICATED_CAP"


def test_parses_exactly_one_all_india_combined_general_record() -> None:
    rec = mospi.parse_cpi_month(payload({"data": [GENERAL, {**GENERAL, "sector": "Rural", "index": "1"}]}),
                                base_year=2024, year=2026, month=9)  # fmt: skip
    assert (rec.base_year, rec.year, rec.month, str(rec.index), str(rec.yoy_pct), rec.provisional) == (
        "2024", 2026, 9, "123.4", "1.11", True)  # fmt: skip


@pytest.mark.parametrize(
    "rows",
    [[], [{**GENERAL, "sector": "Urban"}], [GENERAL, dict(GENERAL)], [{**GENERAL, "baseyear": "2012"}],
     [{**GENERAL, "month": "August"}]],
)  # fmt: skip
def test_no_or_ambiguous_match_stores_nothing(rows: list[dict[str, object]]) -> None:
    with pytest.raises(mospi.MospiError) as e:
        mospi.parse_cpi_month(payload({"data": rows}), base_year=2024, year=2026, month=9)
    assert e.value.code == "NO_MATCHING_RECORD"


def test_schema_surprises_fail_closed() -> None:
    with pytest.raises(SchemaChanged):
        mospi.parse_cpi_month(payload({"rows": []}), base_year=2024, year=2026, month=9)
    with pytest.raises(SchemaChanged):
        mospi.parse_cpi_month(payload({"data": [{**GENERAL, "index": "n/a"}]}), base_year=2024, year=2026, month=9)


# ----------------------------------------------------------------------------------------- fetch (mocked)


def test_token_is_sent_only_as_a_bearer_header_to_mospi() -> None:
    seen: list[httpx.Request] = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        return httpx.Response(200, headers={"content-type": "application/json"}, json={"data": [GENERAL]})

    rec = mospi.fetch_cpi_month(mospi.MospiConfig("token", token="tok-123"), fetcher(handler), base_year=2024,
                                year=2026, month=9)  # fmt: skip
    assert str(rec.index) == "123.4"
    (req,) = seen
    assert req.url.host == "api.mospi.gov.in" and req.headers["authorization"] == "Bearer tok-123"
    assert "base_year=2024" in str(req.url) and "state_code=99" in str(req.url)


def test_password_login_then_fetch() -> None:
    seen: list[httpx.Request] = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        if r.url.path == "/api/login":
            return httpx.Response(200, headers={"content-type": "application/json"}, json={"data": {"token": "t-9"}})
        return httpx.Response(200, headers={"content-type": "application/json"}, json={"data": [GENERAL]})

    cfg = mospi.MospiConfig("password", user="u@example.test", password="pw")
    mospi.fetch_cpi_month(cfg, fetcher(handler), base_year=2024, year=2026, month=9)
    login, data = seen
    assert login.method == "POST" and json.loads(login.content) == {"username": "u@example.test", "password": "pw"}
    assert "authorization" not in login.headers and data.headers["authorization"] == "Bearer t-9"


def test_unrecognised_login_response_is_refused() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/json"}, json={"ok": True})

    with pytest.raises(mospi.MospiError) as e:
        mospi.fetch_cpi_month(mospi.MospiConfig("password", user="u", password="p"), fetcher(handler),
                              base_year=2024, year=2026, month=9)  # fmt: skip
    assert e.value.code == "LOGIN_RESPONSE_UNRECOGNISED"


def test_authenticated_requests_never_follow_redirects() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://api.mospi.gov.in/elsewhere"})

    with pytest.raises(FetchRefused):
        fetcher(handler).fetch(mospi_cpi_request(base_year=2024, year=2026, month=9, bearer_token="tok"))


def test_only_sources_that_require_configuration_may_authenticate() -> None:
    with pytest.raises(FetchRefused):
        SourceRequest(get_source("amfi.navall"), navall_request().url, bearer_token="tok")
    with pytest.raises(FetchRefused):
        SourceRequest(get_source("amfi.navall"), navall_request().url, method="POST", body=b"{}")
    with pytest.raises(FetchRefused):
        mospi_cpi_request(base_year=2024, year=2026, month=9, bearer_token="bad token\r\nX: y")
    with pytest.raises(ValueError):
        mospi_cpi_request(base_year=2019, year=2026, month=9, bearer_token=None)
    assert "tok-secret" not in repr(mospi_cpi_request(base_year=2024, year=2026, month=9, bearer_token="tok-secret"))
