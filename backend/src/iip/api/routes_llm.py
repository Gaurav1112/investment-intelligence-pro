"""Optional AI wording (ADR-0007): status, configuration, and the rephraser used by /api/discover.

Effective configuration = the config saved from Settings (settings key `llm.config`) when present, else the env
(`IIP_LLM`, `IIP_LLM_BASE_URL`, `IIP_LLM_MODEL`, `IIP_LLM_API_KEY_ENV`). Off by default.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from iip.engine.money import format_inr
from iip.llm import config as llm_config
from iip.llm.adapter import LLMAdapter, LLMRuntime
from iip.llm.config import LLMConfig, LLMConfigError
from iip.llm.providers import PROVIDERS
from iip.services.profile import Profile
from iip.supervisor.synthesis import RephraseFailed

_INIT_LOCK = threading.Lock()

PRIVACY = {
    "off": "Off. No text is sent anywhere; every sentence comes from the deterministic writer.",
    "local": (
        "Local model on this computer (127.0.0.1 only). The rendered sentences — which can include your amount — are "
        "sent to the model on this machine and never leave it. Numbers are never taken from the model."
    ),
    "cloud": (
        "Free-tier cloud provider. Only a redacted packet is sent: sentences that contain a rupee amount, a date, your "
        "amount or tax details are held back and shown unchanged. Free tiers may train on prompts. No holdings, tax "
        "profile, token or file path is ever sent."
    ),
}


class LLMConfigIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["off", "local", "cloud"]
    base_url: str = Field(default="", max_length=300)
    model: str = Field(default="", max_length=128)
    api_key_env: str = Field(default="", max_length=64)


def runtime(state: Any) -> LLMRuntime:
    rt: LLMRuntime | None = getattr(state, "llm_runtime", None)
    if rt is None:
        with _INIT_LOCK:
            rt = getattr(state, "llm_runtime", None)
            if rt is None:
                rt = LLMRuntime()
                state.llm_runtime = rt
    return rt


def effective(state: Any) -> tuple[LLMConfig, str]:
    saved = llm_config.load_saved(state.conn)
    if saved is not None:
        return saved, "saved"
    return state.settings.llm, "env"


def sensitive_values(profile: Profile) -> list[str]:
    out: list[str] = []
    if profile.amount is not None:
        out += [format(profile.amount, "f"), format_inr(profile.amount), format_inr(profile.amount, paise=False)]
    if profile.withdrawal_date is not None:
        out.append(profile.withdrawal_date.isoformat())
    return out


def rephraser(state: Any, profile: Profile) -> tuple[Callable[[str], str] | None, LLMAdapter | None]:
    """The callable passed to discovery, or None when the LLM is off. A bad config degrades to the template."""
    cfg, _ = effective(state)
    if cfg.mode == "off":
        return None, None
    rt = runtime(state)
    try:
        adapter = LLMAdapter(
            cfg,
            state.conn,
            rt,
            sensitive=sensitive_values(profile),
            local_personal=os.environ.get("IIP_LLM_LOCAL_PERSONAL", "") == "1",
        )
    except RephraseFailed as exc:
        reason = exc.reason

        def failing(_: str) -> str:
            raise RephraseFailed(reason)

        return failing, None
    return adapter.rephrase, adapter


def router() -> APIRouter:
    r = APIRouter(prefix="/api/llm")

    @r.get("/status")
    def status(request: Request, probe: bool = False) -> dict[str, Any]:
        st = request.app.state.iip
        rt = runtime(st)
        cfg, source = effective(st)
        provider = None
        config_error = None
        try:
            prov = llm_config.validate_config(cfg, rt.resolver)
            if prov is not None:
                provider = {"id": prov.provider_id, "name": prov.name, "data_use_note": prov.data_use_note,
                            "data_use_status": prov.data_use_status, "url_verification": prov.url_verification,
                            "docs_url": prov.docs_url}  # fmt: skip
        except LLMConfigError as exc:
            config_error = str(exc)
        out: dict[str, Any] = {
            **cfg.public(),
            "config_source": source,
            "api_key_present": bool(cfg.api_key_env and rt.env().get(cfg.api_key_env, "").strip()),
            "provider": provider,
            "privacy_note": PRIVACY[cfg.mode] if cfg.mode in PRIVACY else "",
            "config_error": config_error,
            "last_error": rt.last_error,
            "rejected_count": rt.rejected_count,
            "calls": rt.calls,
            "cache_hits": rt.cache_hits,
            "default_local_url": llm_config.DEFAULT_LOCAL_URL,
            "providers": [
                {
                    "id": p.provider_id,
                    "name": p.name,
                    "base_url": p.base_url,
                    "data_use_note": p.data_use_note,
                    "data_use_status": p.data_use_status,
                    "url_verification": p.url_verification,
                }
                for p in PROVIDERS.values()
            ],
            "probe": None,
        }
        if probe and cfg.mode != "off" and config_error is None:
            try:
                out["probe"] = LLMAdapter(cfg, st.conn, rt).probe()
            except (RephraseFailed, LLMConfigError) as exc:
                out["probe"] = {"ok": False, "detail": str(exc)}
        return out

    @r.put("/config")
    def put_config(body: LLMConfigIn, request: Request) -> Any:
        st = request.app.state.iip
        rt = runtime(st)
        cfg = LLMConfig(body.mode, body.base_url.strip(), body.model.strip(), body.api_key_env.strip())
        if cfg.mode == "local" and not cfg.base_url:
            cfg = LLMConfig("local", llm_config.DEFAULT_LOCAL_URL, cfg.model, cfg.api_key_env)
        try:
            llm_config.validate_config(cfg, rt.resolver)
        except LLMConfigError as exc:
            return JSONResponse({"code": "LLM_CONFIG_INVALID", "message": str(exc)}, status_code=422)
        llm_config.save(st.conn, cfg)
        rt.last_error = None
        return {"status": "saved", **cfg.public()}

    return r
