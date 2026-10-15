"""LLM configuration: mode, endpoint, model and the NAME of the env var holding a key (threat-model C-11, SEC-75).

Validation rules:
- `off` (default): nothing else is checked or used.
- `local`: http(s) URL whose host is a loopback literal, `localhost`, or a name that resolves ONLY to loopback
  addresses. Anything else is refused — at startup (StartupRefused) and again before every call.
- `cloud`: the base URL must exactly match an entry in the code-defined allowlist (llm/providers.py).
The key itself is never stored in configuration or the database; only the env var name is.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import Literal, cast
from urllib.parse import urlsplit

from iip.llm.providers import CloudProvider, provider_for
from iip.store.db import write_tx

Mode = Literal["off", "local", "cloud"]
MODES: tuple[Mode, ...] = ("off", "local", "cloud")
CONFIG_KEY = "llm.config"
DEFAULT_LOCAL_URL = "http://127.0.0.1:11434/v1"  # Ollama's OpenAI-compatible endpoint

MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}$")
ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")

Resolver = Callable[[str], list[str]]


class LLMConfigError(ValueError):
    """The LLM configuration violates a security invariant."""


def system_resolver(host: str) -> list[str]:
    return sorted({str(info[4][0]) for info in socket.getaddrinfo(host, None)})


@dataclass(frozen=True)
class LLMConfig:
    mode: Mode = "off"
    base_url: str = ""
    model: str = ""
    api_key_env: str = ""

    def public(self) -> dict[str, str]:
        return asdict(self)


def _loopback_ip(text: str) -> bool:
    try:
        return ipaddress.ip_address(text.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def check_loopback(base_url: str, resolver: Resolver = system_resolver) -> None:
    parts = urlsplit(base_url.strip())
    if parts.scheme not in ("http", "https"):
        raise LLMConfigError("local LLM base URL must be http:// or https://")
    if parts.username or parts.password:
        raise LLMConfigError("local LLM base URL must not carry credentials")
    host = (parts.hostname or "").strip("[]")
    if not host:
        raise LLMConfigError("local LLM base URL has no host")
    if _loopback_ip(host):
        return
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise LLMConfigError(f"local LLM host {host!r} is not a loopback address (127.0.0.1 or ::1)")
    try:
        addresses = resolver(host)
    except OSError as exc:
        raise LLMConfigError(f"local LLM host {host!r} does not resolve") from exc
    if not addresses or not all(_loopback_ip(a) for a in addresses):
        raise LLMConfigError(f"local LLM host {host!r} resolves to a non-loopback address; refusing")


def validate_config(cfg: LLMConfig, resolver: Resolver = system_resolver) -> CloudProvider | None:
    """Raise LLMConfigError when `cfg` is unsafe; return the cloud provider entry for cloud mode."""
    if cfg.mode not in MODES:
        raise LLMConfigError(f"IIP_LLM must be one of {MODES} (got {cfg.mode!r})")
    if cfg.api_key_env and (not ENV_NAME_RE.match(cfg.api_key_env) or cfg.api_key_env.startswith("IIP_")):
        raise LLMConfigError("the API-key setting must be the NAME of an env var (A-Z, 0-9, _), not IIP_*, not a key")
    if cfg.mode == "off":
        return None
    if not MODEL_RE.match(cfg.model):
        raise LLMConfigError("a model name is required (letters, digits and . _ : / @ + -)")
    if cfg.mode == "local":
        check_loopback(cfg.base_url, resolver)
        return None
    provider = provider_for(cfg.base_url)
    if provider is None:
        raise LLMConfigError("cloud base URL is not in the allowlist of known free-tier providers")
    if not cfg.api_key_env:
        raise LLMConfigError("cloud mode needs the name of the env var that holds the provider's API key")
    return provider


def from_env(env: Mapping[str, str]) -> LLMConfig:
    raw = env.get("IIP_LLM", "off").strip().lower()
    mode = cast(Mode, raw)
    base = env.get("IIP_LLM_BASE_URL", DEFAULT_LOCAL_URL if mode == "local" else "").strip()
    return LLMConfig(mode, base, env.get("IIP_LLM_MODEL", "").strip(), env.get("IIP_LLM_API_KEY_ENV", "").strip())


def load_saved(conn: sqlite3.Connection) -> LLMConfig | None:
    row = conn.execute("SELECT value_json FROM settings WHERE key=?", (CONFIG_KEY,)).fetchone()
    if row is None:
        return None
    data = json.loads(row[0])
    return LLMConfig(
        cast(Mode, str(data.get("mode", "off"))),
        str(data.get("base_url", "")),
        str(data.get("model", "")),
        str(data.get("api_key_env", "")),
    )


def save(conn: sqlite3.Connection, cfg: LLMConfig) -> None:
    with write_tx(conn):
        conn.execute(
            "INSERT INTO settings(key, value_json) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET"
            " value_json=excluded.value_json",
            (CONFIG_KEY, json.dumps(cfg.public(), sort_keys=True)),
        )
