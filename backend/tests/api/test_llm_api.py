"""GET /api/llm/status and PUT /api/llm/config (ADR-0007). Uses a stub transport; no provider is contacted."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from iip.api.app import create_app
from iip.api.routes import all_routers
from iip.api.settings import Settings
from iip.llm.adapter import LLMRuntime
from iip.llm.config import LLMConfig
from iip.llm.prompt import MalformedOutput, build_packet, reassemble
from iip.llm.providers import PROVIDERS, provider_for

ORIGIN = "http://127.0.0.1:8741"
NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[tuple[TestClient, dict[str, str], object]]:
    settings = Settings(env="test", data_dir=tmp_path / "iip")
    asgi = create_app(settings, routers=all_routers(), clock=lambda: NOW)
    c = TestClient(asgi, base_url=ORIGIN)
    c.__enter__()
    token = settings.token_path.read_text().strip()
    csrf = c.post("/api/session", json={"token": token}, headers={"Origin": ORIGIN}).json()["csrf"]
    yield c, {"Origin": ORIGIN, "X-IIP-CSRF": csrf}, asgi.app.state.iip
    c.__exit__(None, None, None)


def test_status_defaults_to_off_and_lists_allowlist(client: tuple[TestClient, dict[str, str], object]) -> None:
    c, _, _ = client
    s = c.get("/api/llm/status").json()
    assert s["mode"] == "off" and s["config_source"] == "env" and s["provider"] is None and s["probe"] is None
    assert {p["id"] for p in s["providers"]} == {"groq", "gemini", "mistral", "cerebras", "openrouter", "nvidia"}
    assert all(p["data_use_status"] == "NOT VERIFIED — check provider terms" for p in s["providers"])
    assert "No text is sent" in s["privacy_note"]


def test_put_config_validates_and_persists(client: tuple[TestClient, dict[str, str], object]) -> None:
    c, h, _ = client
    bad = c.put("/api/llm/config", json={"mode": "local", "base_url": "http://192.168.1.10:11434/v1", "model": "m"},
                headers=h)  # fmt: skip
    assert bad.status_code == 422 and bad.json()["code"] == "LLM_CONFIG_INVALID"
    assert c.put("/api/llm/config", json={"mode": "cloud", "base_url": "https://evil.example/v1", "model": "m",
                                          "api_key_env": "K_X"}, headers=h).status_code == 422  # fmt: skip
    assert c.put("/api/llm/config", json={"mode": "cloud", "base_url": "https://api.groq.com/openai/v1", "model": "m",
                                          "api_key_env": "gsk_live_value"}, headers=h).status_code == 422  # fmt: skip
    assert (
        c.put("/api/llm/config", json={"mode": "local", "api_key": "x"}, headers=h).status_code == 422
    )  # no key field
    ok = c.put("/api/llm/config", json={"mode": "local", "model": "llama3.2:3b"}, headers=h)
    assert ok.status_code == 200 and ok.json()["base_url"] == "http://127.0.0.1:11434/v1"  # local-first default URL
    s = c.get("/api/llm/status").json()
    assert s["mode"] == "local" and s["config_source"] == "saved" and "never leave" in s["privacy_note"]
    ok = c.put("/api/llm/config", json={"mode": "cloud", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                                        "model": "gemini-free", "api_key_env": "GEMINI_KEY"}, headers=h)  # fmt: skip
    assert ok.status_code == 200
    s = c.get("/api/llm/status").json()
    assert s["provider"]["id"] == "gemini" and s["provider"]["data_use_note"].startswith("May train on prompts")
    assert s["api_key_present"] is False and "redacted packet" in s["privacy_note"]


def test_config_put_requires_csrf(client: tuple[TestClient, dict[str, str], object]) -> None:
    c, _, _ = client
    assert c.put("/api/llm/config", json={"mode": "off"}, headers={"Origin": ORIGIN}).status_code == 403


def test_probe_sends_no_prompt(client: tuple[TestClient, dict[str, str], object]) -> None:
    c, h, state = client
    seen: list[httpx.Request] = []

    def models(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"object": "list", "data": [{"id": "llama3.2:3b"}]})

    state.llm_runtime = LLMRuntime(transport=httpx.MockTransport(models), environ={})  # type: ignore[attr-defined]
    c.put("/api/llm/config", json={"mode": "local", "model": "llama3.2:3b"}, headers=h)
    s = c.get("/api/llm/status", params={"probe": "true"}).json()
    assert s["probe"] == {"ok": True, "model_listed": True, "detail": "reachable; model listed"}
    assert len(seen) == 1 and seen[0].method == "GET" and seen[0].url.path == "/v1/models" and seen[0].content == b""

    def down(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    state.llm_runtime = LLMRuntime(transport=httpx.MockTransport(down), environ={})  # type: ignore[attr-defined]
    assert c.get("/api/llm/status?probe=1").json()["probe"]["ok"] is False


def test_erase_removes_llm_config_and_cache(client: tuple[TestClient, dict[str, str], object]) -> None:
    c, h, _ = client
    c.put("/api/llm/config", json={"mode": "local", "model": "m"}, headers=h)
    c.post("/api/privacy/erase", json={"confirm": "ERASE ALL MY DATA"}, headers=h)
    assert c.get("/api/llm/status").json()["mode"] == "off"


# ---------------------------------------------------------------------------------------------- prompt unit tests
NARRATIVE = (
    "Evaluated 6 instruments; 4 passed every constraint.\n"
    "Under your constraints the first option is FIXTURE 182-day T-bill, with a low-end outcome of ₹5,10,965.59.\n"
    "Your withdrawal on 2027-04-15 falls after the last legislated tax year."
)


def test_cloud_packet_holds_back_personal_lines() -> None:
    p = build_packet(NARRATIVE, cloud=True)
    assert p.sent_numbers == (1,)
    assert "₹" not in p.user and "2027" not in p.user and "Evaluated 6 instruments" in p.user
    assert reassemble(p, "1. Six instruments were checked; 4 passed.") == "\n".join(
        ["Six instruments were checked; 4 passed.", *NARRATIVE.split("\n")[1:]]
    )
    local = build_packet(NARRATIVE, cloud=False)
    assert local.sent_numbers == (1, 2, 3)
    assert build_packet("Evaluated 6 for Asha.", cloud=True, sensitive=["asha"]).sent_numbers == ()


@pytest.mark.parametrize("out", ["", "1. a\n1. b", "1. a\n2. b", "One. a", "1. a\nstray text"])
def test_reassemble_rejects_malformed(out: str) -> None:
    with pytest.raises(MalformedOutput):
        reassemble(build_packet(NARRATIVE, cloud=True), out)


def test_provider_registry_matches_exact_urls() -> None:
    for p in PROVIDERS.values():
        assert provider_for(p.base_url) is p and provider_for(p.base_url + "/") is p
        assert p.base_url.startswith("https://")
    assert provider_for("https://openrouter.ai/api/v1?x=1") is None
    assert LLMConfig().mode == "off"
