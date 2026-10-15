"""One OpenAI-compatible chat-completions client for the optional wording layer (ADR-0007, threat-model C-11).

Plain httpx; no vendor SDK. The LLM is an untrusted text generator:
- it never sees the ranking inputs, only the rendered claim lines (llm/prompt.py);
- no tools or function calling are offered, and any tool-call structure, markup or link in the reply is rejected;
- temperature 0, a seed where the provider documents one, a hard timeout and a max output length;
- one call at a time; replies are memoised by prompt hash in the settings table (`llm.cache:<sha256>`);
- every failure raises RephraseFailed, so synthesis falls back to the deterministic template (SEC-76).
The numeric-provenance and banned-phrase checks run afterwards in supervisor/synthesis.py.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from iip.llm.config import LLMConfig, LLMConfigError, Resolver, check_loopback, system_resolver, validate_config
from iip.llm.prompt import MalformedOutput, Packet, build_packet, reassemble
from iip.llm.providers import CloudProvider
from iip.store.db import write_tx
from iip.supervisor.synthesis import RephraseFailed

log = logging.getLogger("iip.llm")

CACHE_PREFIX = "llm.cache:"
TIMEOUT_S = 60.0
CONNECT_TIMEOUT_S = 5.0
PROBE_TIMEOUT_S = 5.0
MAX_TOKENS = 600
MAX_OUTPUT_CHARS = 4000
MAX_RESPONSE_BYTES = 256 * 1024
SEED = 7
LOCK_WAIT_S = 5.0

_MARKUP = re.compile(r"<\s*/?\s*[A-Za-z!?]|```|\]\(|https?://|\bwww\.|javascript:", re.IGNORECASE)
_TOOLISH = re.compile(r'"(?:tool_calls?|function(?:_call)?|arguments|name)"\s*:', re.IGNORECASE)
_NAME = re.compile(r"((?:[A-Z][\w&'.-]*\s+){0,6}(?:Fund|Scheme|ETF|Bond|Bank|Deposit|T-bill))\b")
_LEADING = {"the", "this", "that", "a", "an", "your", "its", "each", "every", "one", "such"}


@dataclass
class LLMRuntime:
    """Process-wide LLM state kept on the app: last error, counters, the single-call lock, and (tests) a transport."""

    transport: httpx.BaseTransport | None = None
    resolver: Resolver = system_resolver
    environ: Mapping[str, str] | None = None
    last_error: str | None = None
    rejected_count: int = 0
    calls: int = 0
    cache_hits: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def env(self) -> Mapping[str, str]:
        return os.environ if self.environ is None else self.environ

    def record_rejection(self, reasons: Iterable[str]) -> None:
        reasons = list(reasons)
        if reasons:
            self.rejected_count += 1
            self.last_error = reasons[-1]
            for r in reasons:  # reason code only — never the text
                log.warning("llm_output_rejected reason=%s", r.split(":", 1)[0])


def _unknown_names(output: str, source: str) -> list[str]:
    src = source.lower()
    bad: list[str] = []
    for m in _NAME.finditer(output):
        words = m.group(1).split()
        while len(words) > 1 and words[0].lower() in _LEADING:
            words = words[1:]
        phrase = " ".join(words)
        if phrase.lower() not in src:
            bad.append(phrase)
    return bad


def check_output(content: str, source: str) -> None:
    """SEC-72/73: plain prose only — no markup, links, tool-call structures, oversize output, or unknown names."""
    if len(content) > MAX_OUTPUT_CHARS:
        raise RephraseFailed("oversized_output")
    stripped = content.strip()
    if not stripped:
        raise RephraseFailed("empty_output")
    if stripped[0] in "{[" or _TOOLISH.search(content):
        raise RephraseFailed("tool_call_structure")
    if _MARKUP.search(content):
        raise RephraseFailed("markup_or_link")
    names = _unknown_names(content, source)
    if names:
        raise RephraseFailed("unknown_instrument_name")


def prompt_hash(cfg: LLMConfig, body: Mapping[str, Any]) -> str:
    material = json.dumps(
        {"mode": cfg.mode, "base_url": cfg.base_url.rstrip("/"), "body": body}, sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(material.encode()).hexdigest()


class LLMAdapter:
    def __init__(
        self,
        cfg: LLMConfig,
        conn: sqlite3.Connection,
        runtime: LLMRuntime,
        *,
        sensitive: Iterable[str] = (),
        local_personal: bool = False,
    ) -> None:
        self.cfg = cfg
        # threat-model C-11 §4: personal values (amounts, dates, holdings) are held back from the model by default,
        # in local mode too; local mode may opt in explicitly (IIP_LLM_LOCAL_PERSONAL=1). Cloud mode never sends them.
        self.redact_personal = cfg.mode == "cloud" or not local_personal
        self.conn = conn
        self.runtime = runtime
        self.sensitive = tuple(s for s in sensitive if s)
        try:
            self.provider: CloudProvider | None = validate_config(cfg, runtime.resolver)
        except LLMConfigError as exc:
            raise RephraseFailed(f"config_invalid: {exc}") from exc
        self.last_packet: Packet | None = None

    # ------------------------------------------------------------------ request
    def _key(self) -> str | None:
        if not self.cfg.api_key_env:
            return None
        key = self.runtime.env().get(self.cfg.api_key_env, "").strip()
        if not key:
            if self.cfg.mode == "cloud":
                raise RephraseFailed("api_key_missing")
            return None
        return key

    def _seed_param(self) -> str | None:
        if self.cfg.mode == "local":
            return "seed"
        return self.provider.seed_param if self.provider else None

    def _body(self, packet: Packet) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": [{"role": "system", "content": packet.system}, {"role": "user", "content": packet.user}],
            "temperature": 0,
            "max_tokens": MAX_TOKENS,
            "stream": False,
        }
        seed = self._seed_param()
        if seed:
            body[seed] = SEED
        return body

    def _client(self, timeout: httpx.Timeout) -> httpx.Client:
        # trust_env=False: proxy env vars must never route the "local" call elsewhere; redirects are not followed.
        return httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False, transport=self.runtime.transport)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        key = self._key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _guard(self, packet: Packet) -> None:
        """Defence in depth for SEC-74: the API key value must never be inside the prompt."""
        key = self.runtime.env().get(self.cfg.api_key_env, "") if self.cfg.api_key_env else ""
        if key and len(key) >= 8 and (key in packet.user or key in packet.system):
            raise RephraseFailed("prompt_guard")

    def _post(self, body: Mapping[str, Any]) -> str:
        if self.cfg.mode == "local":
            try:  # re-resolve before every call: a name that later resolves off-box is refused (SEC-75)
                check_loopback(self.cfg.base_url, self.runtime.resolver)
            except LLMConfigError as exc:
                raise RephraseFailed("endpoint_not_loopback") from exc
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        timeout = httpx.Timeout(TIMEOUT_S, connect=CONNECT_TIMEOUT_S)
        if not self.runtime.lock.acquire(timeout=LOCK_WAIT_S):
            raise RephraseFailed("busy")
        try:
            self.runtime.calls += 1
            with self._client(timeout) as client:
                resp = client.post(url, json=body, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise RephraseFailed("timeout") from exc
        except httpx.HTTPError as exc:
            raise RephraseFailed(f"connection_failed: {type(exc).__name__}") from exc
        finally:
            self.runtime.lock.release()
        if resp.status_code != 200:
            raise RephraseFailed(f"http_status: {resp.status_code}")
        if len(resp.content) > MAX_RESPONSE_BYTES:
            raise RephraseFailed("oversized_output")
        return _content(resp)

    # ------------------------------------------------------------------ cache
    def _cached(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value_json FROM settings WHERE key=?", (CACHE_PREFIX + key,)).fetchone()
        if row is None:
            return None
        value = json.loads(row[0]).get("text")
        return value if isinstance(value, str) else None

    def _store(self, key: str, text: str) -> None:
        with write_tx(self.conn):
            self.conn.execute(
                "INSERT INTO settings(key, value_json) VALUES (?, ?) ON CONFLICT(key) DO NOTHING",
                (CACHE_PREFIX + key, json.dumps({"text": text, "model": self.cfg.model}, ensure_ascii=False)),
            )

    # ------------------------------------------------------------------ public
    def rephrase(self, narrative: str) -> str:
        packet = build_packet(narrative, cloud=self.redact_personal, sensitive=self.sensitive)
        self.last_packet = packet
        if not packet.sent_numbers:
            raise RephraseFailed("nothing_to_send_after_redaction")
        self._guard(packet)
        body = self._body(packet)
        key = prompt_hash(self.cfg, body)
        content = self._cached(key)
        if content is not None:
            self.runtime.cache_hits += 1
        else:
            content = self._post(body)
        source = "\n".join(s.text for s in packet.segments)
        check_output(content, source)
        try:
            text = reassemble(packet, content)
        except MalformedOutput as exc:
            raise RephraseFailed(f"malformed_output: {exc}") from exc
        self._store(key, content)  # only output that passed the adapter's own checks is memoised
        return text

    def probe(self) -> dict[str, Any]:
        """'Test connection': GET <base>/models. Sends no prompt and no user data."""
        if self.cfg.mode == "local":
            check_loopback(self.cfg.base_url, self.runtime.resolver)
        try:
            with self._client(httpx.Timeout(PROBE_TIMEOUT_S)) as client:
                resp = client.get(self.cfg.base_url.rstrip("/") + "/models", headers=self._headers())
        except httpx.TimeoutException:
            return {"ok": False, "detail": "timeout"}
        except httpx.HTTPError as exc:
            return {"ok": False, "detail": f"connection failed ({type(exc).__name__})"}
        if resp.status_code != 200:
            return {"ok": False, "detail": f"HTTP {resp.status_code}"}
        try:
            data = resp.json().get("data", [])
            ids = {str(m.get("id")) for m in data if isinstance(m, dict)}
        except (ValueError, AttributeError):
            ids = set()
        listed = self.cfg.model in ids
        detail = "reachable; model listed" if listed else "reachable; model not in the server's list"
        return {"ok": True, "model_listed": listed, "detail": detail}


def _content(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except ValueError as exc:
        raise RephraseFailed("invalid_json") from exc
    try:
        choice = data["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RephraseFailed("invalid_schema") from exc
    if not isinstance(message, dict):
        raise RephraseFailed("invalid_schema")
    if message.get("tool_calls") or message.get("function_call"):
        raise RephraseFailed("tool_call_structure")
    finish = choice.get("finish_reason") if isinstance(choice, dict) else None
    if finish in ("length", "tool_calls", "function_call", "content_filter"):
        raise RephraseFailed(f"finish_reason: {finish}")
    content = message.get("content")
    if not isinstance(content, str):
        raise RephraseFailed("invalid_schema")
    return content
