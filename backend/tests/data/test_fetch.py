"""Fetcher tests (threat-model SEC-50..53, SEC-55, SEC-56; reliability REL-50..52). No real network: every test uses
httpx.MockTransport and a stubbed resolver, and an autouse guard makes any real socket connect fail loudly."""

from __future__ import annotations

import gzip
import os
import socket
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from iip.data.fetch import (
    USER_AGENT,
    BreakerStatus,
    CircuitBreaker,
    CircuitOpen,
    ContentTypeMismatch,
    Fetcher,
    FetchFailed,
    FetchOffline,
    FetchSizeCapExceeded,
    PinnedNetworkBackend,
    RetryPolicy,
    is_public_ip,
)
from iip.data.models import FetchRefused
from iip.data.registry import (
    ALLOWED_HOSTS,
    SourceRequest,
    get_source,
    navall_request,
    navhistory_request,
    schememaster_request,
)
from tests.data.conftest import load_fixture

PUBLIC_IP = "23.0.0.1"  # never connected to: the transport is mocked
NOW = datetime(2026, 10, 15, 5, 34, 19, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("network") is not None:
        return

    def refuse(*_a: object, **_k: object) -> None:
        raise AssertionError("real network access attempted in a unit test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


class Clock:
    def __init__(self, start: datetime = NOW) -> None:
        self.now = start
        self.mono = 0.0

    def __call__(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return self.mono

    def advance(self, td: timedelta) -> None:
        self.now += td


class Recorder:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def wrap(self, fn: Callable[[httpx.Request], httpx.Response]) -> Callable[[httpx.Request], httpx.Response]:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return fn(request)

        return handler


def make_fetcher(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    resolver: Callable[[str], list[str]] | None = None,
    clock: Clock | None = None,
    sleeps: list[float] | None = None,
    breaker: CircuitBreaker | None = None,
    seed: int = 7,
) -> Fetcher:
    clock = clock or Clock()
    sleep_log = sleeps if sleeps is not None else []
    return Fetcher(
        transport=httpx.MockTransport(handler),
        resolver=resolver or (lambda _host: [PUBLIC_IP]),
        jitter_seed=seed,
        sleep=sleep_log.append,
        clock=clock,
        monotonic=clock.monotonic,
        breaker=breaker or CircuitBreaker(clock=clock),
    )


NAVALL_BODY = load_fixture("amfi_navall_excerpt.txt")


def amfi_ok(request: httpx.Request) -> httpx.Response:
    if request.url.host == "www.amfiindia.com":
        return httpx.Response(302, headers={"location": "https://portal.amfiindia.com/spages/NAVAll.txt"})
    return httpx.Response(
        200,
        headers={"content-type": "text/plain", "last-modified": "Thu, 15 Oct 2026 05:05:03 GMT"},
        content=NAVALL_BODY,
    )


# --- happy path ---------------------------------------------------------------------------------------


def test_navall_follows_exactly_the_portal_redirect() -> None:
    rec = Recorder()
    payload = make_fetcher(rec.wrap(amfi_ok)).fetch(navall_request())
    assert [str(r.url) for r in rec.requests] == [
        "https://www.amfiindia.com/spages/NAVAll.txt",
        "https://portal.amfiindia.com/spages/NAVAll.txt",
    ]
    assert payload.final_url == "https://portal.amfiindia.com/spages/NAVAll.txt"
    assert payload.content == NAVALL_BODY
    assert len(payload.sha256) == 64
    assert payload.retrieved_at == NOW
    assert payload.last_modified == datetime(2026, 10, 15, 5, 5, 3, tzinfo=UTC)
    assert payload.source_id == "amfi.navall"


def test_request_headers_are_generic() -> None:
    rec = Recorder()
    make_fetcher(rec.wrap(amfi_ok)).fetch(navall_request())
    for r in rec.requests:
        assert r.headers["user-agent"] == USER_AGENT
        assert "cookie" not in r.headers
        assert "authorization" not in r.headers


def test_cookies_are_not_replayed_across_hops() -> None:
    rec = Recorder()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.amfiindia.com":
            return httpx.Response(
                302,
                headers={"location": "https://portal.amfiindia.com/spages/NAVAll.txt", "set-cookie": "sid=abc; Path=/"},
            )
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"x")

    make_fetcher(rec.wrap(handler)).fetch(navall_request())
    assert "cookie" not in rec.requests[1].headers


# --- SEC-50 / SEC-53: URL policy ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "http://www.amfiindia.com/spages/NAVAll.txt",
        "https://www.amfiindia.com:8443/spages/NAVAll.txt",
        "file:///etc/passwd",
        "gopher://www.amfiindia.com/",
        "https://user@www.amfiindia.com/spages/NAVAll.txt",
        "https://www.amfiindia.com.evil.example/",
        "https://www.amfiindia.com./spages/NAVAll.txt",
        "https://api.mospi.gov.in/",  # allowlisted globally, but not for this source
    ],
)
def test_registry_misuse_urls_refused_at_construction(url: str) -> None:
    with pytest.raises(FetchRefused):
        SourceRequest(source=get_source("amfi.navall"), url=url)


def test_forged_request_refused_before_any_call() -> None:
    """Even if a SourceRequest is forged past its constructor, the fetcher re-checks before opening anything."""
    rec = Recorder()
    forged = object.__new__(SourceRequest)
    object.__setattr__(forged, "source", get_source("amfi.navall"))
    object.__setattr__(forged, "url", "https://example.com/")
    with pytest.raises(FetchRefused):
        make_fetcher(rec.wrap(amfi_ok)).fetch(forged)
    assert rec.requests == []


def test_disabled_source_is_refused() -> None:
    spec = get_source("mfapi.in")
    rec = Recorder()
    forged = object.__new__(SourceRequest)
    object.__setattr__(forged, "source", spec)
    object.__setattr__(forged, "url", "https://api.mfapi.in/mf/934256")
    with pytest.raises(FetchRefused, match="disabled"):
        make_fetcher(rec.wrap(amfi_ok)).fetch(forged)
    assert rec.requests == []


def test_fetcher_has_no_url_accepting_api() -> None:
    import inspect

    sig = inspect.signature(Fetcher.fetch)
    assert list(sig.parameters) == ["self", "request", "force"]


# --- SEC-52: redirects -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example/NAVAll.txt",
        "http://portal.amfiindia.com/spages/NAVAll.txt",
        "http://127.0.0.1:11434/api/generate",
        "https://api.mospi.gov.in/x",  # allowlisted for another source only
        "https://portal.amfiindia.com:8443/spages/NAVAll.txt",
    ],
)
def test_redirect_to_disallowed_target_refused_at_hop(location: str) -> None:
    rec = Recorder()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": location})

    with pytest.raises(FetchRefused):
        make_fetcher(rec.wrap(handler)).fetch(navall_request())
    assert len(rec.requests) == 1  # refused at the hop, never retried


def test_redirect_hop_limit() -> None:
    rec = Recorder()

    def handler(request: httpx.Request) -> httpx.Response:
        nxt = "portal" if request.url.host == "www.amfiindia.com" else "www"
        return httpx.Response(302, headers={"location": f"https://{nxt}.amfiindia.com/spages/NAVAll.txt"})

    with pytest.raises(FetchRefused, match="redirect"):
        make_fetcher(rec.wrap(handler)).fetch(navall_request())
    assert len(rec.requests) == 4  # original + 3 hops


def test_relative_redirect_resolved_and_checked() -> None:
    rec = Recorder()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/spages/NAVAll.txt":
            return httpx.Response(302, headers={"location": "/spages/NAVAll2.txt"})
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok")

    payload = make_fetcher(rec.wrap(handler)).fetch(navall_request())
    assert payload.final_url == "https://www.amfiindia.com/spages/NAVAll2.txt"


# --- SEC-51: resolved IPs ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.5",
        "169.254.169.254",
        "::1",
        "fd00::1",
        "192.168.1.1",
        "100.64.0.1",
        "0.0.0.0",
        "::ffff:127.0.0.1",
        "224.0.0.1",
        "fe80::1",
    ],
)
def test_private_resolution_refused(ip: str) -> None:
    rec = Recorder()
    with pytest.raises(FetchRefused):
        make_fetcher(rec.wrap(amfi_ok), resolver=lambda _h: [ip]).fetch(navall_request())
    assert rec.requests == []


def test_any_private_address_in_the_set_refuses() -> None:
    with pytest.raises(FetchRefused):
        make_fetcher(amfi_ok, resolver=lambda _h: [PUBLIC_IP, "10.1.2.3"]).fetch(navall_request())


def test_redirect_target_is_resolved_and_checked_too() -> None:
    rec = Recorder()

    def resolver(host: str) -> list[str]:
        return ["127.0.0.1"] if host == "portal.amfiindia.com" else [PUBLIC_IP]

    with pytest.raises(FetchRefused):
        make_fetcher(rec.wrap(amfi_ok), resolver=resolver).fetch(navall_request())
    assert len(rec.requests) == 1


def test_is_public_ip() -> None:
    assert is_public_ip("23.0.0.1")
    assert is_public_ip("2606:4700::1")
    assert not is_public_ip("not-an-ip")


class _FakeStream:
    pass


class _InnerBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: object = None,
    ) -> _FakeStream:
        self.calls.append((host, port))
        return _FakeStream()


def test_pinned_backend_connects_to_vetted_ip_only() -> None:
    inner = _InnerBackend()
    backend = PinnedNetworkBackend(resolver=lambda _h: [PUBLIC_IP], inner=inner)  # type: ignore[arg-type]
    backend.connect_tcp("portal.amfiindia.com", 443)
    assert inner.calls == [(PUBLIC_IP, 443)]


def test_pinned_backend_refuses_private_without_connecting() -> None:
    inner = _InnerBackend()
    backend = PinnedNetworkBackend(resolver=lambda _h: ["127.0.0.1"], inner=inner)  # type: ignore[arg-type]
    with pytest.raises(FetchRefused):
        backend.connect_tcp("portal.amfiindia.com", 443)
    with pytest.raises(FetchRefused):
        PinnedNetworkBackend(resolver=lambda _h: [PUBLIC_IP], inner=inner).connect_tcp("example.com", 443)  # type: ignore[arg-type]
    assert inner.calls == []


# --- SEC-55: byte caps ------------------------------------------------------------------------------------


def _small_cap_request(cap: int) -> SourceRequest:
    spec = replace(get_source("amfi.navall"), max_bytes=cap)
    return SourceRequest(source=spec, url="https://portal.amfiindia.com/spages/NAVAll.txt")


def test_streamed_body_over_cap_aborted_without_retry() -> None:
    rec = Recorder()

    def handler(request: httpx.Request) -> httpx.Response:
        def chunks() -> Iterator[bytes]:
            for _ in range(10):
                yield b"x" * 200

        return httpx.Response(200, headers={"content-type": "text/plain"}, content=chunks())

    with pytest.raises(FetchSizeCapExceeded):
        make_fetcher(rec.wrap(handler)).fetch(_small_cap_request(1000))
    assert len(rec.requests) == 1


def test_declared_content_length_over_cap_aborted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/plain", "content-length": "5000"}, content=b"x" * 5000
        )

    with pytest.raises(FetchSizeCapExceeded):
        make_fetcher(handler).fetch(_small_cap_request(1000))


def test_gzip_expansion_past_cap_aborted() -> None:
    bomb = gzip.compress(b"\0" * 50_000)
    assert len(bomb) < 1000

    def handler(request: httpx.Request) -> httpx.Response:
        # Streamed (not pre-read) so the fetcher's own bounded decompressor handles the raw gzip bytes.
        return httpx.Response(
            200, headers={"content-type": "text/plain", "content-encoding": "gzip"}, content=iter([bomb])
        )

    with pytest.raises(FetchSizeCapExceeded):
        make_fetcher(handler).fetch(_small_cap_request(1000))


def test_streamed_gzip_within_cap_is_decoded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/plain", "content-encoding": "gzip"},
            content=iter([gzip.compress(NAVALL_BODY)]),
        )

    assert make_fetcher(handler).fetch(navall_request()).content == NAVALL_BODY


def test_unsupported_encoding_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/plain", "content-encoding": "br"}, content=iter([b"x"])
        )

    with pytest.raises(FetchFailed) as exc:
        make_fetcher(handler).fetch(navall_request())
    assert exc.value.code == "UNSUPPORTED_ENCODING"


def test_body_at_cap_is_accepted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"x" * 1000)

    assert len(make_fetcher(handler).fetch(_small_cap_request(1000)).content) == 1000


# --- content type ------------------------------------------------------------------------------------------


def test_content_type_mismatch_not_retried() -> None:
    rec = Recorder()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=b"<html>")

    with pytest.raises(ContentTypeMismatch):
        make_fetcher(rec.wrap(handler)).fetch(schememaster_request())
    assert len(rec.requests) == 1


def test_amfi_no_data_page_is_no_data_and_never_opens_the_breaker() -> None:
    """Walkthrough 2026-10-15: AMFI answers an unused fund-house id with its HTML form page (HTTP 200). That used to
    be a ContentTypeMismatch FAILURE, so three unused ids in a row opened the breaker for 6 h and blocked every
    backfill."""
    from datetime import date

    from iip.data.fetch import NoData
    from iip.data.registry import navhistory_request

    page = b"\r\n<!DOCTYPE html><html><head><title>\r\n\tView/Download NAV History\r\n</title></head></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=page)

    clock = Clock()
    breaker = CircuitBreaker(clock=clock)
    f = make_fetcher(handler, clock=clock, breaker=breaker)
    for mf_id in range(10, 16):  # six unused ids in a row
        with pytest.raises(NoData):
            f.fetch(navhistory_request(mf_id=mf_id, tp=1, from_date=date(2026, 10, 1), to_date=date(2026, 10, 1)))
    assert breaker.allow("amfi.navhistory") is BreakerStatus.CLOSED


def test_html_without_the_no_data_marker_is_still_a_failure() -> None:
    from datetime import date

    from iip.data.registry import navhistory_request

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>Service unavailable</html>")

    with pytest.raises(ContentTypeMismatch):
        make_fetcher(handler).fetch(
            navhistory_request(mf_id=3, tp=1, from_date=date(2026, 10, 1), to_date=date(2026, 10, 1))
        )


# --- REL-50/51: retries ------------------------------------------------------------------------------------


def test_503_503_200_succeeds_with_jittered_backoff() -> None:
    rec = Recorder()
    statuses = iter([503, 503, 200])
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        s = next(statuses)
        return httpx.Response(s, headers={"content-type": "text/plain"}, content=b"ok")

    payload = make_fetcher(rec.wrap(handler), sleeps=sleeps).fetch(schememaster_request_text())
    assert payload.content == b"ok"
    assert len(rec.requests) == 3
    assert len(sleeps) == 2
    policy = RetryPolicy()
    for attempt, s in enumerate(sleeps):
        assert 0 <= s <= min(policy.cap_seconds, policy.base_seconds * 2**attempt)


def schememaster_request_text() -> SourceRequest:
    return SourceRequest(
        source=replace(get_source("amfi.schememaster"), content_types=frozenset({"text/plain"})),
        url=schememaster_request().url,
    )


def test_jitter_is_deterministic_with_seed() -> None:
    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    runs = []
    for _ in range(2):
        sleeps: list[float] = []
        with pytest.raises(FetchFailed):
            make_fetcher(failing, sleeps=sleeps, seed=42).fetch(navall_request())
        runs.append(sleeps)
    assert runs[0] == runs[1]
    assert len(runs[0]) == 3  # 4 attempts → 3 sleeps


def test_retry_after_is_honoured_and_capped() -> None:
    statuses = iter([(429, "1000"), (503, "5"), (200, None)])
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        s, ra = next(statuses)
        headers = {"content-type": "text/plain"}
        if ra:
            headers["retry-after"] = ra
        return httpx.Response(s, headers=headers, content=b"ok")

    make_fetcher(handler, sleeps=sleeps).fetch(navall_request())
    assert sleeps == [300.0, 5.0]


@pytest.mark.parametrize("status", [400, 403, 404, 418])
def test_deterministic_4xx_not_retried(status: int) -> None:
    rec = Recorder()
    with pytest.raises(FetchFailed) as exc:
        make_fetcher(rec.wrap(lambda _r: httpx.Response(status))).fetch(navall_request())
    assert len(rec.requests) == 1
    assert exc.value.retryable is False


def test_trickling_server_times_out_then_retries() -> None:
    clock = Clock()
    rec = Recorder()

    def handler(request: httpx.Request) -> httpx.Response:
        def trickle() -> Iterator[bytes]:
            for _ in range(1000):
                clock.mono += 1.0  # one byte per second
                yield b"x"

        return httpx.Response(200, headers={"content-type": "text/plain"}, content=trickle())

    with pytest.raises(FetchFailed) as exc:
        make_fetcher(rec.wrap(handler), clock=clock).fetch(navall_request())
    assert exc.value.code == "TIMEOUT"
    assert len(rec.requests) == 4


# --- REL-52: circuit breaker ------------------------------------------------------------------------------


def test_timeouts_retry_then_circuit_opens() -> None:
    clock = Clock()
    rec = Recorder()
    breaker = CircuitBreaker(clock=clock)

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated", request=request)

    fetcher = make_fetcher(rec.wrap(timeout), clock=clock, breaker=breaker)
    for run in range(3):
        with pytest.raises(FetchFailed):
            fetcher.fetch(navall_request())
        assert len(rec.requests) == 4 * (run + 1)  # 4 attempts per run
    assert breaker.state("amfi.navall").status is BreakerStatus.OPEN
    with pytest.raises(CircuitOpen):
        fetcher.fetch(navall_request())
    assert len(rec.requests) == 12  # open breaker → no network


def test_half_open_single_probe_then_close_or_reopen_with_doubled_cooldown() -> None:
    clock = Clock()
    breaker = CircuitBreaker(clock=clock)
    for _ in range(3):
        breaker.record_failure("amfi.navall")
    st = breaker.state("amfi.navall")
    assert st.status is BreakerStatus.OPEN
    assert st.next_probe_at == NOW + timedelta(hours=6)

    rec = Recorder()
    fetcher = make_fetcher(rec.wrap(lambda _r: httpx.Response(503)), clock=clock, breaker=breaker)
    clock.advance(timedelta(hours=6))
    with pytest.raises(FetchFailed):
        fetcher.fetch(navall_request())
    assert len(rec.requests) == 1  # half-open: one attempt, no retries
    st = breaker.state("amfi.navall")
    assert st.status is BreakerStatus.OPEN
    assert st.next_probe_at == clock.now + timedelta(hours=12)

    clock.advance(timedelta(hours=12))
    make_fetcher(amfi_ok, clock=clock, breaker=breaker).fetch(navall_request())
    assert breaker.state("amfi.navall").status is BreakerStatus.CLOSED


def test_cooldown_capped_at_48h() -> None:
    clock = Clock()
    breaker = CircuitBreaker(clock=clock)
    for _ in range(3):
        breaker.record_failure("s")
    for _ in range(6):
        clock.now = breaker.state("s").next_probe_at  # type: ignore[assignment]
        breaker.allow("s")
        breaker.record_failure("s")
    st = breaker.state("s")
    assert st.next_probe_at - clock.now == timedelta(hours=48)  # type: ignore[operator]


def test_trip_opens_immediately_for_schema_drift() -> None:
    breaker = CircuitBreaker(clock=Clock())
    breaker.trip("amfi.navall")
    with pytest.raises(CircuitOpen):
        breaker.allow("amfi.navall")


def test_force_bypasses_open_breaker() -> None:
    clock = Clock()
    breaker = CircuitBreaker(clock=clock)
    breaker.trip("amfi.navall")
    payload = make_fetcher(amfi_ok, clock=clock, breaker=breaker).fetch(navall_request(), force=True)
    assert payload.content == NAVALL_BODY


def test_offline_does_not_count_toward_breaker() -> None:
    clock = Clock()
    breaker = CircuitBreaker(clock=clock)

    def offline(_host: str) -> list[str]:
        raise socket.gaierror("nodename nor servname provided")

    fetcher = make_fetcher(amfi_ok, resolver=offline, clock=clock, breaker=breaker)
    for _ in range(5):
        with pytest.raises(FetchOffline):
            fetcher.fetch(navall_request())
    assert breaker.state("amfi.navall").status is BreakerStatus.CLOSED
    assert breaker.state("amfi.navall").consecutive_failures == 0


def test_ssrf_refusal_counts_as_failed_run() -> None:
    clock = Clock()
    breaker = CircuitBreaker(clock=clock)
    with pytest.raises(FetchRefused):
        make_fetcher(amfi_ok, resolver=lambda _h: ["10.0.0.1"], clock=clock, breaker=breaker).fetch(navall_request())
    assert breaker.state("amfi.navall").consecutive_failures == 1


# --- request builders ------------------------------------------------------------------------------------


def test_navhistory_request_builds_registry_url() -> None:
    req = navhistory_request(mf_id=9, tp=1, from_date=date(2026, 10, 13), to_date=date(2026, 10, 14))
    assert req.url == (
        "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx?mf=9&tp=1&frmdt=13-Oct-2026&todt=14-Oct-2026"
    )


@pytest.mark.parametrize(
    ("mf_id", "tp", "frm", "to"),
    [
        (0, 1, date(2026, 10, 13), date(2026, 10, 14)),
        (9, 4, date(2026, 10, 13), date(2026, 10, 14)),
        (9, 1, date(2026, 10, 14), date(2026, 10, 13)),
        (9, 1, date(2026, 1, 1), date(2026, 10, 14)),  # > 90-day window
    ],
)
def test_navhistory_request_rejects_bad_params(mf_id: int, tp: int, frm: date, to: date) -> None:
    with pytest.raises(ValueError):
        navhistory_request(mf_id=mf_id, tp=tp, from_date=frm, to_date=to)


def test_navhistory_request_rejects_bool_and_str() -> None:
    with pytest.raises(TypeError):
        navhistory_request(mf_id="9&x=1", tp=1, from_date=date(2026, 10, 13), to_date=date(2026, 10, 14))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        navhistory_request(mf_id=True, tp=1, from_date=date(2026, 10, 13), to_date=date(2026, 10, 14))


def test_allowed_hosts_exact() -> None:
    assert "portal.amfiindia.com" in ALLOWED_HOSTS
    assert "www.amfiindia.com" in ALLOWED_HOSTS
    assert "api.mfapi.in" not in ALLOWED_HOSTS  # disabled source
    assert not any("nseindia" in h for h in ALLOWED_HOSTS)


# --- optional live probe (skipped by default) -------------------------------------------------------------


@pytest.mark.network
@pytest.mark.skipif(os.environ.get("IIP_NETWORK_TESTS") != "1", reason="network tests are opt-in: IIP_NETWORK_TESTS=1")
def test_live_navall_fetch() -> None:  # pragma: no cover - opt-in only
    from iip.data.parsers.amfi_navall import parse_navall

    payload = Fetcher().fetch(navall_request())
    result = parse_navall(payload)
    assert result.report.rows_ok > 1000
