"""Allowlisted HTTPS fetcher (threat-model C-08, SEC-50..57; reliability-design §4.3–§4.4).

Controls, applied on every request and on every redirect hop:
* only ``https``, port 443, and a host that is an exact member of the source's allowlist (``registry.hosts_for``);
* DNS is resolved and every address must be public — loopback, private, link-local (169.254.169.254), CGNAT,
  multicast, reserved, unspecified, IPv6 ULA/link-local and IPv4-mapped private addresses are refused. The real
  transport pins the TCP connection to the vetted address (``PinnedNetworkBackend``) while TLS SNI/Host keep the
  hostname, so DNS cannot be rebound between check and connect;
* redirects are never followed automatically: at most 3 hops, each re-checked;
* the body is streamed under a per-source byte cap; gzip/deflate are decoded here with a bounded decompressor so a
  compression bomb cannot expand past the cap; other encodings are refused;
* timeouts (connect 5 s, read 30 s, total 90 s per attempt), retries with exponential backoff and full jitter from an
  injectable seed, and a per-source circuit breaker;
* no cookies, a fixed generic User-Agent, no proxy/netrc from the environment, and no Authorization header — except a
  bearer token on a request to a source that REQUIRES CONFIGURATION (``SourceRequest.authenticated``, MoSPI only).
  Authenticated requests never follow a redirect, so neither the token nor a credential body can leave the host.

The public API takes a ``registry.SourceRequest`` (built only by typed builders), never a URL string.
"""

from __future__ import annotations

import email.utils
import ipaddress
import random
import socket
import time
import zlib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import httpcore
import httpx

from iip.data.models import DataError, FetchRefused, RawPayload
from iip.data.registry import (
    ADAPTER_VERSION,
    ALLOWED_HOSTS,
    SourceMode,
    SourceRequest,
    check_url,
    hosts_for,
)

USER_AGENT = f"InvestmentIntelligencePro/{ADAPTER_VERSION} (personal research; contact: none)"
MAX_REDIRECTS = 3
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_RETRYABLE_STATUSES = frozenset({408, 429})

Resolver = Callable[[str], Sequence[str]]
Clock = Callable[[], datetime]


# --- errors ------------------------------------------------------------------------------------------------------


class FetchError(DataError):
    code = "FETCH_ERROR"
    retryable = False


class FetchFailed(FetchError):
    """A fetch attempt or run failed. ``retryable`` tells the retry loop whether trying again can help."""

    def __init__(
        self, message: str, *, code: str, retryable: bool, status: int | None = None, retry_after: float | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status = status
        self.retry_after = retry_after


class FetchSizeCapExceeded(FetchError):
    code = "SIZE_CAP"


class ContentTypeMismatch(FetchError):
    code = "CONTENT_TYPE_MISMATCH"


class NoData(FetchError):
    """The source answered normally but has nothing for this query (e.g. AMFI's NAV-history form page for an unused
    fund-house id). A successful exchange: it counts as a success for the circuit breaker, never a failure."""

    code = "NO_DATA"


_NO_DATA_SNIFF_BYTES = 64 * 1024


class CircuitOpen(FetchError):
    code = "BREAKER_OPEN"


class FetchOffline(FetchError):
    """DNS resolution failed: the machine looks offline. Not counted toward the circuit breaker."""

    code = "OFFLINE"
    retryable = True


# --- IP policy -----------------------------------------------------------------------------------------------------


def is_public_ip(text: str) -> bool:
    """True only for globally routable unicast addresses."""
    try:
        ip = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped or ip.sixtofour
        if mapped is not None:
            return is_public_ip(str(mapped))
        if ip.is_site_local:
            return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


def default_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def vet_host(host: str, allowed: frozenset[str], resolver: Resolver) -> list[str]:
    """Resolve an allowlisted host and require every address to be public. Returns the vetted addresses."""
    if host not in allowed:
        raise FetchRefused(f"host {host!r} is not allowlisted")
    try:
        addrs = list(resolver(host))
    except OSError as exc:
        raise FetchOffline(f"DNS resolution failed for {host}: {exc.__class__.__name__}") from None
    if not addrs:
        raise FetchOffline(f"DNS returned no addresses for {host}")
    bad = [a for a in addrs if not is_public_ip(a)]
    if bad:
        raise FetchRefused(f"host {host!r} resolves to a non-public address")
    return addrs


class PinnedNetworkBackend(httpcore.NetworkBackend):
    """httpcore backend that resolves, vets and connects to the vetted IP itself (no rebinding window)."""

    def __init__(
        self,
        resolver: Resolver,
        inner: httpcore.NetworkBackend | None = None,
        allowed_hosts: frozenset[str] = ALLOWED_HOSTS,
    ) -> None:
        self._resolver = resolver
        self._inner = inner if inner is not None else httpcore.SyncBackend()
        self._allowed = allowed_hosts

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        if port != 443:
            raise FetchRefused(f"port {port} refused")
        addrs = vet_host(host, self._allowed, self._resolver)
        last: Exception | None = None
        for ip in addrs:
            try:
                return self._inner.connect_tcp(
                    ip, port, timeout=timeout, local_address=local_address, socket_options=socket_options
                )
            except httpcore.ConnectError as exc:
                last = exc
        assert last is not None
        raise last

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        raise FetchRefused("unix sockets are refused")

    def sleep(self, seconds: float) -> None:
        self._inner.sleep(seconds)


class PinnedHTTPTransport(httpx.HTTPTransport):
    """The production transport: TLS verified, HTTP/1.1, no transport-level retries, IP-pinned connections."""

    def __init__(self, resolver: Resolver) -> None:
        super().__init__(verify=True, trust_env=False, http1=True, http2=False, retries=0)
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(trust_env=False),
            max_connections=4,
            http1=True,
            http2=False,
            retries=0,
            network_backend=PinnedNetworkBackend(resolver),
        )


# --- retry policy and circuit breaker ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 4
    base_seconds: float = 2.0
    cap_seconds: float = 60.0
    retry_after_cap_seconds: float = 300.0
    budget_seconds: float = 600.0
    total_timeout_seconds: float = 90.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")


class BreakerStatus(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True, slots=True)
class BreakerState:
    source_id: str
    status: BreakerStatus = BreakerStatus.CLOSED
    consecutive_failures: int = 0
    opened_at: datetime | None = None
    next_probe_at: datetime | None = None
    cooldown: timedelta = timedelta(hours=6)


class CircuitBreaker:
    """Per-source breaker. Counts *runs*, not attempts. State is exportable via ``state``/``restore`` so the store
    can persist it between processes (reliability-design §4.4)."""

    def __init__(
        self,
        *,
        clock: Clock,
        threshold: int = 3,
        base_cooldown: timedelta = timedelta(hours=6),
        max_cooldown: timedelta = timedelta(hours=48),
    ) -> None:
        self._clock = clock
        self._threshold = threshold
        self._base = base_cooldown
        self._max = max_cooldown
        self._states: dict[str, BreakerState] = {}

    def state(self, source_id: str) -> BreakerState:
        return self._states.get(source_id, BreakerState(source_id, cooldown=self._base))

    def restore(self, state: BreakerState) -> None:
        self._states[state.source_id] = state

    def allow(self, source_id: str) -> BreakerStatus:
        """CLOSED or HALF_OPEN if a run may proceed; raises ``CircuitOpen`` during the cooldown."""
        st = self.state(source_id)
        if st.status is BreakerStatus.OPEN:
            assert st.next_probe_at is not None
            if self._clock() < st.next_probe_at:
                raise CircuitOpen(f"breaker open for {source_id} until {st.next_probe_at.isoformat()}")
            st = replace(st, status=BreakerStatus.HALF_OPEN)
            self._states[source_id] = st
        return st.status

    def record_success(self, source_id: str) -> None:
        self._states[source_id] = BreakerState(source_id, cooldown=self._base)

    def record_failure(self, source_id: str) -> None:
        st = self.state(source_id)
        failures = st.consecutive_failures + 1
        if st.status is BreakerStatus.HALF_OPEN:
            self._open(source_id, failures, min(st.cooldown * 2, self._max))
        elif st.status is BreakerStatus.OPEN:
            self._states[source_id] = replace(st, consecutive_failures=failures)
        elif failures >= self._threshold:
            self._open(source_id, failures, self._base)
        else:
            self._states[source_id] = replace(st, consecutive_failures=failures)

    def trip(self, source_id: str) -> None:
        """Open immediately (schema drift: refetching cannot help until the parser changes)."""
        st = self.state(source_id)
        self._open(source_id, st.consecutive_failures + 1, self._base)

    def _open(self, source_id: str, failures: int, cooldown: timedelta) -> None:
        now = self._clock()
        self._states[source_id] = BreakerState(
            source_id, BreakerStatus.OPEN, failures, opened_at=now, next_probe_at=now + cooldown, cooldown=cooldown
        )


# --- bounded body decoding -----------------------------------------------------------------------------------------


class _BoundedBody:
    def __init__(self, encoding: str, cap: int) -> None:
        self._cap = cap
        self._buf = bytearray()
        enc = encoding.strip().lower()
        if enc in ("", "identity"):
            self._dobj: zlib._Decompress | None = None
        elif enc in ("gzip", "x-gzip"):
            self._dobj = zlib.decompressobj(16 + zlib.MAX_WBITS)
        elif enc == "deflate":
            self._dobj = zlib.decompressobj(zlib.MAX_WBITS)
        else:
            raise FetchFailed(
                f"unsupported content-encoding {encoding!r}", code="UNSUPPORTED_ENCODING", retryable=False
            )

    def _add(self, data: bytes) -> None:
        self._buf += data
        if len(self._buf) > self._cap:
            raise FetchSizeCapExceeded(f"body exceeds {self._cap} bytes")

    def feed(self, raw: bytes) -> None:
        if self._dobj is None:
            self._add(raw)
            return
        data = raw
        try:
            while data:
                self._add(self._dobj.decompress(data, self._cap + 1 - len(self._buf)))
                data = self._dobj.unconsumed_tail
        except zlib.error as exc:
            raise FetchFailed(f"corrupt compressed body: {exc}", code="DECODE_ERROR", retryable=False) from None

    def finish(self) -> bytes:
        if self._dobj is not None:
            try:
                self._add(self._dobj.flush(self._cap + 1 - len(self._buf)))
            except zlib.error as exc:
                raise FetchFailed(f"corrupt compressed body: {exc}", code="DECODE_ERROR", retryable=False) from None
        return bytes(self._buf)


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    return float(value) if value.isdigit() else None


def _parse_last_modified(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _utc_now() -> datetime:
    return datetime.now(UTC)


# --- fetcher --------------------------------------------------------------------------------------------------------


class Fetcher:
    """Fetches registered sources. Construct once per run; inject transport/resolver/clock/sleep/seed in tests."""

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: Resolver = default_resolver,
        retry: RetryPolicy | None = None,
        jitter_seed: int | None = None,
        sleep: Callable[[float], object] = time.sleep,
        clock: Clock = _utc_now,
        monotonic: Callable[[], float] = time.monotonic,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self._resolver = resolver
        self._transport = transport if transport is not None else PinnedHTTPTransport(resolver)
        self._retry = retry or RetryPolicy()
        self._rng = random.Random(jitter_seed)  # noqa: S311 - jitter only, not security-sensitive
        self._sleep = sleep
        self._clock = clock
        self._monotonic = monotonic
        self.breaker = breaker or CircuitBreaker(clock=clock)
        self._timeout = httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)

    def fetch(self, request: SourceRequest, force: bool = False) -> RawPayload:
        """Fetch one registered source. ``force`` bypasses an open breaker for this run only."""
        spec = request.source
        # Defence in depth: re-validate even though SourceRequest validated itself on construction.
        if spec.mode is not SourceMode.LIVE:
            raise FetchRefused(f"source {spec.id!r} is {spec.mode.value}; it is never fetched")
        check_url(request.url, hosts_for(spec))

        status = BreakerStatus.CLOSED if force else self.breaker.allow(spec.id)
        attempts = 1 if status is BreakerStatus.HALF_OPEN else self._retry.max_attempts
        try:
            payload = self._run(request, attempts)
        except FetchOffline:
            raise  # an offline machine is not the source's fault
        except NoData:
            self.breaker.record_success(spec.id)  # the source is healthy; it just has nothing for this query
            raise
        except (FetchError, FetchRefused):
            self.breaker.record_failure(spec.id)
            raise
        self.breaker.record_success(spec.id)
        return payload

    def _run(self, request: SourceRequest, max_attempts: int) -> RawPayload:
        start = self._monotonic()
        attempt = 0
        while True:
            try:
                return self._attempt(request)
            except (FetchFailed, FetchOffline) as exc:
                if not exc.retryable:
                    raise
                attempt += 1
                if attempt >= max_attempts:
                    raise
                retry_after = exc.retry_after if isinstance(exc, FetchFailed) else None
                if retry_after is not None:
                    delay = min(retry_after, self._retry.retry_after_cap_seconds)
                else:
                    ceiling = min(self._retry.cap_seconds, self._retry.base_seconds * 2 ** (attempt - 1))
                    delay = self._rng.uniform(0, ceiling)
                if self._monotonic() - start + delay > self._retry.budget_seconds:
                    raise FetchFailed("run budget exhausted", code="BUDGET", retryable=False) from exc
                self._sleep(delay)

    def _attempt(self, request: SourceRequest) -> RawPayload:
        spec = request.source
        allowed = hosts_for(spec)
        url = request.url
        started = self._monotonic()
        extra: dict[str, str] = {}
        if request.bearer_token is not None:
            extra["Authorization"] = f"Bearer {request.bearer_token}"
        if request.body is not None:
            extra["Content-Type"] = "application/json"
        with httpx.Client(
            transport=self._transport,
            follow_redirects=False,
            trust_env=False,
            timeout=self._timeout,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, identity"},
        ) as client:
            for hop in range(MAX_REDIRECTS + 1):
                host = check_url(url, allowed)
                vet_host(host, allowed, self._resolver)
                client.cookies.clear()
                try:
                    with client.stream(request.method, url, content=request.body, headers=extra) as resp:
                        if resp.status_code in _REDIRECT_STATUSES:
                            if request.authenticated:
                                raise FetchRefused("redirect on an authenticated request refused")
                            location = resp.headers.get("location")
                            if not location:
                                raise FetchFailed("redirect without Location", code="BAD_REDIRECT", retryable=False)
                            if hop == MAX_REDIRECTS:
                                raise FetchRefused(f"too many redirects (> {MAX_REDIRECTS})")
                            url = str(resp.url.join(location))
                            continue
                        self._raise_for_status(resp)
                        self._raise_if_no_data(resp, spec.no_data_marker)
                        body = self._read_body(resp, spec.max_bytes, spec.content_types, started)
                        return RawPayload.from_bytes(
                            source_id=spec.id,
                            final_url=url,
                            retrieved_at=self._clock(),
                            content=body,
                            content_type=resp.headers.get("content-type"),
                            last_modified=_parse_last_modified(resp.headers.get("last-modified")),
                        )
                except httpx.TimeoutException as exc:
                    raise FetchFailed(f"timeout: {exc.__class__.__name__}", code="TIMEOUT", retryable=True) from None
                except httpx.TransportError as exc:
                    raise FetchFailed(
                        f"transport: {exc.__class__.__name__}", code="TRANSPORT", retryable=True
                    ) from None
        raise FetchRefused("redirect loop")  # pragma: no cover - loop always returns or raises

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        s = resp.status_code
        if s == 200:
            return
        if s >= 500 or s in _RETRYABLE_STATUSES:
            retry_after = _parse_retry_after(resp.headers.get("retry-after")) if s in (429, 503) else None
            raise FetchFailed(f"HTTP {s}", code=f"HTTP_{s}", retryable=True, status=s, retry_after=retry_after)
        raise FetchFailed(f"HTTP {s}", code=f"HTTP_{s}", retryable=False, status=s)

    @staticmethod
    def _raise_if_no_data(resp: httpx.Response, marker: bytes | None) -> None:
        """An HTML answer carrying the source's declared "no data" marker is NoData, not a content-type failure."""
        if marker is None:
            return
        ctype = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if ctype != "text/html":
            return
        head = b""
        for chunk in resp.iter_bytes():
            head += chunk
            if len(head) >= _NO_DATA_SNIFF_BYTES:
                break
        if marker in head[:_NO_DATA_SNIFF_BYTES]:
            raise NoData("the source has no data for this query")
        raise ContentTypeMismatch(f"content-type {ctype!r} without the source's no-data marker")

    def _read_body(self, resp: httpx.Response, cap: int, content_types: frozenset[str], started: float) -> bytes:
        ctype = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_types and ctype not in content_types:
            raise ContentTypeMismatch(f"content-type {ctype!r} not in {sorted(content_types)}")
        declared = resp.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > cap:
            raise FetchSizeCapExceeded(f"declared content-length {declared} exceeds {cap}")
        if resp.is_stream_consumed:
            # In-memory response (e.g. httpx.MockTransport with bytes content): httpx already decoded it.
            mem = _BoundedBody("identity", cap)
            mem.feed(resp.content)
            return mem.finish()
        body = _BoundedBody(resp.headers.get("content-encoding", ""), cap)
        for chunk in resp.iter_raw():
            body.feed(chunk)
            if self._monotonic() - started > self._retry.total_timeout_seconds:
                raise FetchFailed("total request time exceeded", code="TIMEOUT", retryable=True)
        return body.finish()
