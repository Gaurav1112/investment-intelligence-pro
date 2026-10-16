"""ASGI security middleware (threat-model C-02, C-03, C-04, C-05, C-14, C-16).

Order of checks for every HTTP request:
  1. Host allowlist (exact host:port; missing/duplicate Host → 400). Health is NOT exempt.
  2. Body size cap (Content-Length and streamed).
  3. Authentication (session cookie) for every /api route except POST /api/session.
  4. CSRF for state-changing methods: X-IIP-CSRF + Origin/Sec-Fetch-Site + content type.
  5. Security headers on every response; Cache-Control: no-store on /api.
No CORS headers are ever emitted.

Scheduled jobs (research-automation-infra.md §3, PLAN rank 10): ``GET|POST /api/cron/{job}`` is the ONE route that
also accepts the generated deployment host (``$VERCEL_URL``), authenticates with ``Authorization: Bearer
<CRON_SECRET>`` instead of a session, and skips CSRF (no cookie, no ambient credential). Every other route keeps the
exact host allowlist. Wrong secrets are rate-limited; while the limit is exhausted every cron call is refused, the
correct secret included, so the limiter actually slows guessing. With no secret configured the route answers 404.

Session lookups (database statements when hosted) run in the thread pool, never on the event loop, and a hosted
session's ``last_seen`` is written at most once per ``LAST_SEEN_THROTTLE_S``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from typing import Any, Protocol
from urllib.parse import urlsplit

from starlette.concurrency import run_in_threadpool

from iip.api.settings import MIN_HOSTED_TOKEN_CHARS, Settings, StartupRefused

log = logging.getLogger("iip.api")

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
    "connect-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; "
    "object-src 'none'"
)
SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"content-security-policy", CSP.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
)
STATE_CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
SESSION_COOKIE = "iip_session"
PUBLIC_ROUTES = frozenset({("POST", "/api/session"), ("GET", "/api/health")})
MULTIPART_ROUTES = frozenset({"/api/holdings/import", "/api/holdings/import-cas"})
IDLE_TIMEOUT_S = 8 * 3600
ABSOLUTE_TIMEOUT_S = 24 * 3600
# PARAMETER (PLAN A03): a hosted session's last_seen is written at most once per this many seconds. The idle timeout
# is measured from the stored value, so it can end up to this much earlier than 8 h after the true last request.
LAST_SEEN_THROTTLE_S = 5 * 60
# The cron exception matches exactly one lower-case path segment; anything else is an ordinary route.
CRON_PATH = re.compile(r"/api/cron/[a-z][a-z0-9-]{0,39}")
CRON_METHODS = frozenset({"GET", "POST"})
CRON_RATE_KEY = "cron"
CRON_RATE_LIMIT = 10  # wrong secrets per window, like login (research-automation-infra.md §3 "Rate limits")
CRON_RATE_WINDOW_S = 60.0


@dataclass
class Session:
    session_id: str
    csrf: str
    created: float
    last_seen: float


@dataclass
class SessionStore:
    clock: Callable[[], float] = time.monotonic
    sessions: dict[str, Session] = field(default_factory=dict)

    def create(self) -> Session:
        now = self.clock()
        s = Session(secrets.token_urlsafe(32), secrets.token_urlsafe(32), now, now)
        self.sessions[s.session_id] = s
        return s

    def get(self, session_id: str | None) -> Session | None:
        if not session_id:
            return None
        s = self.sessions.get(session_id)
        if s is None:
            return None
        now = self.clock()
        if now - s.last_seen > IDLE_TIMEOUT_S or now - s.created > ABSOLUTE_TIMEOUT_S:
            self.sessions.pop(session_id, None)
            return None
        s.last_seen = now
        return s

    def revoke(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)

    def revoke_all(self) -> None:
        self.sessions.clear()


class SessionBackend(Protocol):
    def create(self) -> Session: ...
    def get(self, session_id: str | None) -> Session | None: ...
    def revoke(self, session_id: str) -> None: ...
    def revoke_all(self) -> None: ...


class LoginLimiter(Protocol):
    def allow(self) -> bool: ...


class FailureLimiter(Protocol):
    """Counts failures only: ``exhausted`` looks without recording, ``allow`` records one hit."""

    def allow(self) -> bool: ...
    def exhausted(self) -> bool: ...


def _id_hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()


@dataclass
class DbSessionStore:
    """Hosted mode (ADR-0013): sessions in the database, because serverless instances share no memory.

    Only a SHA-256 of the cookie value is stored, so a copy of the database holds no usable session. The same idle
    (8 h) and absolute (24 h) limits apply; expired rows are deleted when a new session is created."""

    conn: Callable[[], Any]
    clock: Callable[[], float] = time.time

    def create(self) -> Session:
        now = self.clock()
        s = Session(secrets.token_urlsafe(32), secrets.token_urlsafe(32), now, now)
        c = self.conn()
        c.execute(
            "DELETE FROM web_sessions WHERE last_seen < ? OR created < ?",
            (now - IDLE_TIMEOUT_S, now - ABSOLUTE_TIMEOUT_S),
        )
        c.execute(
            "INSERT INTO web_sessions(id_hash, csrf, created, last_seen) VALUES (?,?,?,?)",
            (_id_hash(s.session_id), s.csrf, now, now),
        )
        return s

    def get(self, session_id: str | None) -> Session | None:
        if not session_id:
            return None
        key = _id_hash(session_id)
        c = self.conn()
        row = c.execute("SELECT csrf, created, last_seen FROM web_sessions WHERE id_hash=?", (key,)).fetchone()
        if row is None:
            return None
        now = self.clock()
        created, last_seen = float(row["created"]), float(row["last_seen"])
        if now - last_seen > IDLE_TIMEOUT_S or now - created > ABSOLUTE_TIMEOUT_S:
            c.execute("DELETE FROM web_sessions WHERE id_hash=?", (key,))
            return None
        if now - last_seen < LAST_SEEN_THROTTLE_S:
            return Session(session_id, str(row["csrf"]), created, last_seen)
        c.execute("UPDATE web_sessions SET last_seen=? WHERE id_hash=?", (now, key))
        return Session(session_id, str(row["csrf"]), created, now)

    def revoke(self, session_id: str) -> None:
        self.conn().execute("DELETE FROM web_sessions WHERE id_hash=?", (_id_hash(session_id),))

    def revoke_all(self) -> None:
        self.conn().execute("DELETE FROM web_sessions")


@dataclass
class DbRateLimiter:
    """Hosted login limiter: at most ``limit`` hits per ``window_s`` per key, across all instances. The check and the
    insert are ONE conditional statement, so concurrent attempts cannot both take the last slot."""

    conn: Callable[[], Any]
    key: str
    limit: int
    window_s: float
    clock: Callable[[], float] = time.time

    def allow(self) -> bool:
        now = self.clock()
        c = self.conn()
        c.execute("DELETE FROM rate_hits WHERE key=? AND at <= ?", (self.key, now - self.window_s))
        cur = c.execute(
            "INSERT INTO rate_hits(key, at) SELECT ?, ?"
            " WHERE (SELECT COUNT(*) FROM rate_hits WHERE key=? AND at > ?) < ?",
            (self.key, now, self.key, now - self.window_s, self.limit),
        )
        return int(cur.rowcount) == 1

    def exhausted(self) -> bool:
        now = self.clock()
        row = (
            self.conn()
            .execute("SELECT COUNT(*) FROM rate_hits WHERE key=? AND at > ?", (self.key, now - self.window_s))
            .fetchone()
        )
        return int(row[0]) >= self.limit


@dataclass
class RateLimiter:
    limit: int
    window_s: float
    clock: Callable[[], float] = time.monotonic
    hits: deque[float] = field(default_factory=deque)

    def allow(self) -> bool:
        now = self.clock()
        while self.hits and now - self.hits[0] > self.window_s:
            self.hits.popleft()
        if len(self.hits) >= self.limit:
            return False
        self.hits.append(now)
        return True

    def exhausted(self) -> bool:
        now = self.clock()
        return sum(1 for t in self.hits if now - t <= self.window_s) >= self.limit


@dataclass(frozen=True)
class CronAuth:
    """The narrow scheduled-job exception. ``deployment_host`` is the bare ``$VERCEL_URL`` host (no scheme/port)."""

    secret: str = field(repr=False)
    deployment_host: str
    limiter: FailureLimiter = field(repr=False)


_HOST_RE = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+")


def cron_auth_from_env(settings: Settings, environ: Mapping[str, str], limiter: FailureLimiter) -> CronAuth | None:
    """Build the cron exception from ``CRON_SECRET``, ``VERCEL_URL`` and ``VERCEL_ENV``; None means the route is off.

    Off (404) when: not hosted, no secret, no ``VERCEL_URL``, or ``VERCEL_ENV`` is not ``production`` (Vercel runs
    crons only against production). A secret that is set but too short, equal to the access token, or a malformed
    ``VERCEL_URL`` refuses startup instead of silently weakening the boundary."""
    secret = environ.get("CRON_SECRET", "")
    if not settings.hosted or not secret.strip():  # blank = unset, as the outer gate in root app.py (A04) reads it
        return None
    if len(secret) < MIN_HOSTED_TOKEN_CHARS:
        raise StartupRefused(f"CRON_SECRET must be at least {MIN_HOSTED_TOKEN_CHARS} characters")
    if hmac.compare_digest(secret.encode(), settings.access_token.encode()):
        raise StartupRefused("CRON_SECRET must differ from IIP_ACCESS_TOKEN")
    host = environ.get("VERCEL_URL", "").strip().lower()
    if not host or environ.get("VERCEL_ENV", "") != "production":
        return None
    if not _HOST_RE.fullmatch(host) or urlsplit(f"//{host}").netloc != host:
        raise StartupRefused("VERCEL_URL must be a bare host name such as <project>-<hash>.vercel.app")
    return CronAuth(secret=secret, deployment_host=host, limiter=limiter)


def _headers(scope: Scope) -> list[tuple[bytes, bytes]]:
    return list(scope.get("headers", []))


def _header_values(scope: Scope, name: bytes) -> list[str]:
    return [v.decode("latin-1") for k, v in _headers(scope) if k.lower() == name]


def _cookie(scope: Scope, name: str) -> str | None:
    for raw in _header_values(scope, b"cookie"):
        jar: SimpleCookie = SimpleCookie()
        try:
            jar.load(raw)
        except Exception:
            return None
        if name in jar:
            return jar[name].value
    return None


async def _reject(send: Send, status: int, code: str, extra_headers: tuple[tuple[bytes, bytes], ...] = ()) -> None:
    body = json.dumps({"code": code}).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        (b"cache-control", b"no-store"),
        *SECURITY_HEADERS,
        *extra_headers,
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


HSTS = (b"strict-transport-security", b"max-age=63072000; includeSubDomains")


class SecurityMiddleware:
    def __init__(
        self, app: ASGIApp, settings: Settings, sessions: SessionBackend, *, cron: CronAuth | None = None
    ) -> None:
        self.app = app
        self.settings = settings
        self.sessions = sessions
        self.cron = cron
        # Hosted (HTTPS only, ADR-0013): browsers must never fall back to plain HTTP for this origin.
        self.extra_headers: tuple[tuple[bytes, bytes], ...] = (HSTS,) if settings.hosted else ()

    async def _deny(self, send: Send, status: int, code: str) -> None:
        await _reject(send, status, code, self.extra_headers)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":  # no websockets (C-01: no other listeners)
            return
        method: str = scope["method"]
        path: str = scope["path"]
        is_cron = CRON_PATH.fullmatch(path) is not None
        allowed_hosts = self.settings.allowed_hosts
        if is_cron and self.cron is not None:  # SEC-cron-2: the deployment host is accepted on this path ONLY
            allowed_hosts = allowed_hosts | {self.cron.deployment_host}
        hosts = _header_values(scope, b"host")
        if len(hosts) != 1 or hosts[0].lower() not in allowed_hosts:
            await self._deny(send, 400, "BAD_HOST")
            return

        lengths = _header_values(scope, b"content-length")
        if lengths:
            try:
                if int(lengths[0]) > self.settings.max_body_bytes:
                    await self._deny(send, 413, "PAYLOAD_TOO_LARGE")
                    return
            except ValueError:
                await self._deny(send, 400, "BAD_CONTENT_LENGTH")
                return

        if is_cron:
            await self._cron(scope, receive, send, method)
            return

        is_api = path.startswith("/api/") or path == "/api"
        session: Session | None = None
        if is_api and (method, path) not in PUBLIC_ROUTES and method != "OPTIONS":
            if self.settings.auth:
                # Hosted lookups are database statements: run them in the thread pool so a slow lookup never stalls
                # other requests on the event loop (PLAN rank 3).
                session = await run_in_threadpool(self.sessions.get, _cookie(scope, SESSION_COOKIE))
                if session is None:
                    await self._deny(send, 401, "UNAUTHENTICATED")
                    return
            if method in STATE_CHANGING and not self._csrf_ok(scope, session, path):
                await self._deny(send, 403, "CSRF_REJECTED")
                return
        if method == "OPTIONS":
            # No CORS: a preflight gets no allow headers at all.
            await self._deny(send, 405, "METHOD_NOT_ALLOWED")
            return
        if is_api and method == "POST" and (method, path) in PUBLIC_ROUTES and not self._origin_ok(scope):
            await self._deny(send, 403, "CSRF_REJECTED")
            return

        state = scope.setdefault("state", {})
        state["session"] = session
        state["cron"] = False
        await self._dispatch(scope, self._capped_receive(receive), send, is_api=is_api)

    async def _cron(self, scope: Scope, receive: Receive, send: Send, method: str) -> None:
        """Bearer-only, cookie-free path for scheduled jobs. The handler decides the work from database state."""
        cron = self.cron
        if cron is None:
            await self._deny(send, 404, "NOT_FOUND")
            return
        if method not in CRON_METHODS:
            await self._deny(send, 405, "METHOD_NOT_ALLOWED")
            return
        # The bearer is checked FIRST (constant time) and a correct secret always passes: only wrong attempts count
        # toward the shared limit and only they get 429. Locking out the correct secret would let anyone with no
        # secret suppress every scheduled job (the schedule is public in vercel.json; Vercel does not retry a cron
        # call), and it adds nothing against guessing: the secret has at least MIN_HOSTED_TOKEN_CHARS of entropy.
        auth = _header_values(scope, b"authorization")
        scheme, _, presented = (auth[0] if len(auth) == 1 else "").partition(" ")
        if not (scheme.lower() == "bearer" and hmac.compare_digest(presented.encode(), cron.secret.encode())):
            allowed = await run_in_threadpool(cron.limiter.allow)
            await self._deny(send, 401 if allowed else 429, "UNAUTHENTICATED" if allowed else "RATE_LIMITED")
            return
        state = scope.setdefault("state", {})
        state["session"] = None
        state["cron"] = True
        await self._dispatch(scope, self._capped_receive(receive), send, is_api=True)

    async def _dispatch(self, scope: Scope, receive: Receive, send: Send, *, is_api: bool) -> None:
        """Run the app with the security headers added to its response; no exception escapes (see below)."""
        started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = [
                    h for h in message.get("headers", []) if h[0].lower() not in {k for k, _ in SECURITY_HEADERS}
                ]
                headers.extend(SECURITY_HEADERS)
                headers.extend(self.extra_headers)
                if is_api:
                    headers = [h for h in headers if h[0].lower() != b"cache-control"]
                    headers.append((b"cache-control", b"no-store"))
                headers = [h for h in headers if not h[0].lower().startswith(b"access-control-")]
                headers = [h for h in headers if h[0].lower() != b"server"]
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except _BodyTooLarge:
            await self._deny(send, 413, "PAYLOAD_TOO_LARGE")
        except Exception as exc:
            # SEC-21 / C-13 (ECC F2): Starlette re-raises after its 500 handler, and uvicorn would then log the full
            # traceback including the exception MESSAGE, which can carry user values. Nothing leaves this layer:
            # log the class only, and answer 500 if no response has started yet.
            log.error("unhandled error escaped the app type=%s", type(exc).__name__)
            if not started:
                await self._deny(send, 500, "INTERNAL_ERROR")

    def _origin_ok(self, scope: Scope) -> bool:
        origins = _header_values(scope, b"origin")
        if origins:
            return len(origins) == 1 and origins[0] in self.settings.allowed_origins
        fetch_site = _header_values(scope, b"sec-fetch-site")
        return fetch_site == ["same-origin"] or (not fetch_site and self.settings.env == "test")

    def _csrf_ok(self, scope: Scope, session: Session | None, path: str) -> bool:
        if not self._origin_ok(scope):
            return False
        ctype = (_header_values(scope, b"content-type") or [""])[0].split(";")[0].strip().lower()
        allowed_ctype = "multipart/form-data" if path in MULTIPART_ROUTES else "application/json"
        if ctype != allowed_ctype:
            return False
        if not self.settings.auth:
            return True
        presented = (_header_values(scope, b"x-iip-csrf") or [""])[0]
        return session is not None and bool(presented) and hmac.compare_digest(presented, session.csrf)

    def _capped_receive(self, receive: Receive) -> Receive:
        limit = self.settings.max_body_bytes
        seen = 0

        async def wrapped() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise _BodyTooLarge
            return message

        return wrapped


class _BodyTooLarge(Exception):
    pass
