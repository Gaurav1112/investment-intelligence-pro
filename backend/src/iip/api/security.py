"""ASGI security middleware (threat-model C-02, C-03, C-04, C-05, C-14, C-16).

Order of checks for every HTTP request:
  1. Host allowlist (exact host:port; missing/duplicate Host → 400). Health is NOT exempt.
  2. Body size cap (Content-Length and streamed).
  3. Authentication (session cookie) for every /api route except POST /api/session.
  4. CSRF for state-changing methods: X-IIP-CSRF + Origin/Sec-Fetch-Site + content type.
  5. Security headers on every response; Cache-Control: no-store on /api.
No CORS headers are ever emitted.
"""

from __future__ import annotations

import hmac
import json
import secrets
import time
from collections import deque
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from typing import Any

from iip.api.settings import Settings

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

    def revoke_all(self) -> None:
        self.sessions.clear()


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


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings, sessions: SessionStore) -> None:
        self.app = app
        self.settings = settings
        self.sessions = sessions

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":  # no websockets (C-01: no other listeners)
            return
        hosts = _header_values(scope, b"host")
        if len(hosts) != 1 or hosts[0].lower() not in self.settings.allowed_hosts:
            await _reject(send, 400, "BAD_HOST")
            return

        method: str = scope["method"]
        path: str = scope["path"]

        lengths = _header_values(scope, b"content-length")
        if lengths:
            try:
                if int(lengths[0]) > self.settings.max_body_bytes:
                    await _reject(send, 413, "PAYLOAD_TOO_LARGE")
                    return
            except ValueError:
                await _reject(send, 400, "BAD_CONTENT_LENGTH")
                return

        is_api = path.startswith("/api/") or path == "/api"
        session: Session | None = None
        if is_api and (method, path) not in PUBLIC_ROUTES and method != "OPTIONS":
            if self.settings.auth:
                session = self.sessions.get(_cookie(scope, SESSION_COOKIE))
                if session is None:
                    await _reject(send, 401, "UNAUTHENTICATED")
                    return
            if method in STATE_CHANGING and not self._csrf_ok(scope, session, path):
                await _reject(send, 403, "CSRF_REJECTED")
                return
        if method == "OPTIONS":
            # No CORS: a preflight gets no allow headers at all.
            await _reject(send, 405, "METHOD_NOT_ALLOWED")
            return
        if is_api and method == "POST" and (method, path) in PUBLIC_ROUTES and not self._origin_ok(scope):
            await _reject(send, 403, "CSRF_REJECTED")
            return

        scope.setdefault("state", {})["session"] = session
        receive = self._capped_receive(receive)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    h for h in message.get("headers", []) if h[0].lower() not in {k for k, _ in SECURITY_HEADERS}
                ]
                headers.extend(SECURITY_HEADERS)
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
            await _reject(send, 413, "PAYLOAD_TOO_LARGE")

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
