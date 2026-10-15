"""Code-defined allowlist of free-tier, OpenAI-compatible cloud providers (ADR-0007, requirements A6).

Cloud mode is an explicit opt-in and may only target a base URL listed here. Adding a provider is a code change and a
review, never a configuration value. Every entry records a data-use note: free tiers commonly allow the provider to use
prompts for training, so only the redacted packet (llm/prompt.py) is ever sent.

`url_verification` records whether the base URL was confirmed against the provider's official documentation, and when.
`data_use_status` is deliberately "NOT VERIFIED" for every provider: terms change, and the user must check them at
configuration time. Neither field is ever upgraded without reading the official source.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

DATA_USE_NOTE = "May train on prompts — redacted packet only."
DATA_USE_NOT_VERIFIED = "NOT VERIFIED — check provider terms"


@dataclass(frozen=True)
class CloudProvider:
    provider_id: str
    name: str
    base_url: str  # exact OpenAI-compatible base; /chat/completions is appended
    seed_param: str | None  # name of the determinism parameter, None when the provider does not document one
    url_verification: str
    docs_url: str
    data_use_note: str = DATA_USE_NOTE
    data_use_status: str = DATA_USE_NOT_VERIFIED

    @property
    def host(self) -> str:
        return urlsplit(self.base_url).hostname or ""

    @property
    def path(self) -> str:
        return urlsplit(self.base_url).path.rstrip("/")


_VERIFIED = "VERIFIED 2026-10-15 against the official docs"

PROVIDERS: dict[str, CloudProvider] = {
    p.provider_id: p
    for p in (
        CloudProvider(
            "groq", "Groq", "https://api.groq.com/openai/v1", "seed", _VERIFIED, "https://console.groq.com/docs/openai"
        ),
        CloudProvider(
            "gemini",
            "Google Gemini (OpenAI-compatible endpoint)",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            None,  # the compatibility page documents seed only for video generation
            _VERIFIED,
            "https://ai.google.dev/gemini-api/docs/openai",
        ),
        CloudProvider(
            "mistral", "Mistral", "https://api.mistral.ai/v1", "random_seed", _VERIFIED, "https://docs.mistral.ai/api/"
        ),
        CloudProvider(
            "cerebras",
            "Cerebras",
            "https://api.cerebras.ai/v1",
            "seed",
            _VERIFIED,
            "https://inference-docs.cerebras.ai/resources/openai",
        ),
        CloudProvider(
            "openrouter",
            "OpenRouter (free models)",
            "https://openrouter.ai/api/v1",
            "seed",
            _VERIFIED,
            "https://openrouter.ai/docs/quickstart",
        ),
        CloudProvider(
            "nvidia",
            "NVIDIA NIM (build.nvidia.com)",
            "https://integrate.api.nvidia.com/v1",
            None,  # seed support not confirmed from the docs read on 2026-10-15
            _VERIFIED,
            "https://docs.api.nvidia.com/nim/reference/llm-apis",
        ),
    )
}


def provider_for(base_url: str) -> CloudProvider | None:
    """The allowlisted provider whose scheme, host and path exactly match `base_url` (trailing slash ignored)."""
    parts = urlsplit(base_url.strip())
    if parts.scheme != "https" or parts.username or parts.password or parts.query or parts.fragment:
        return None
    if parts.port not in (None, 443):
        return None
    for p in PROVIDERS.values():
        if (parts.hostname or "").lower() == p.host and parts.path.rstrip("/") == p.path:
            return p
    return None
