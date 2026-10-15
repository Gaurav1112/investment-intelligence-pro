"""The single "Explained number" contract shared by every service (ux-design §5.1, ADR-0003).

* One freshness vocabulary (also mirrored in frontend/src/lib/types.ts — a test checks they match).
* Freshness is computed from the observation's age against its source's SLO — never assumed.
* Source references are normalised from the code-defined registry (name, official flag).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import date
from typing import Any

from iip.data.registry import REGISTRY
from iip.engine.freshness import nav_is_stale

# Meaning of each badge (rendered with a glyph + word + date in the UI):
FRESHNESS: dict[str, str] = {
    "LIVE": "observed within the source's intraday cadence",
    "DELAYED": "intraday source, older than its cadence",
    "END_OF_DAY": "latest official daily publication, within the source's freshness SLO",
    "STALE": "older than the source's freshness SLO — dependent claims are disabled",
    "FIXTURE": "synthetic development fixture — not market data",
    "MANUAL": "entered by you with a citation, within its freshness window",
    "DERIVED": "computed only from your own records and versioned rules (no market observation)",
    "USER_INPUT": "a value you supplied (e.g. amount), shown back to you",
    "ILLUSTRATIVE": "an illustrative default used in exploration mode — not your data",
    "UNAVAILABLE": "no value can be shown (missing or refused data)",
    "UNKNOWN": "freshness could not be established — treated as not fresh",
}

# Age rules per source (source-registry.md §4); the NAV rule lives in the engine (shared with eligibility).
MANUAL_MAX_DAYS = {"rbi.pr.tbill": 7, "bank.fd": 30}
_NAV_SOURCES = frozenset({"amfi.navall", "amfi.navhistory"})
_REQUIRED_KEYS = (
    "id", "label", "display", "value", "unit", "what", "formula_id", "formula", "substituted", "inputs", "sources",
    "observed", "freshness", "assumptions", "sensitivity", "limitations", "engine_version", "hash",
)  # fmt: skip
_SOURCE_KEYS = ("source_id", "source_name", "url", "retrieved_at", "observation_date", "quality_status", "official")


def badge(prov: Mapping[str, Any] | None, as_of: date | None) -> str:
    """Freshness badge from provenance and the analysis date. Without enough information → UNKNOWN (never fresh)."""
    if not prov:
        return "DERIVED"
    if prov.get("fixture") or prov.get("quality_status") == "fixture":
        return "FIXTURE"
    obs = prov.get("observation_date")
    if as_of is None or not obs:
        return "UNKNOWN"
    observed = date.fromisoformat(str(obs))
    source = str(prov.get("source_id") or "")
    if prov.get("quality_status") == "manual" or source in MANUAL_MAX_DAYS:
        limit = MANUAL_MAX_DAYS.get(source)
        if limit is None:
            return "UNKNOWN"
        return "STALE" if observed > as_of or (as_of - observed).days > limit else "MANUAL"
    if source in _NAV_SOURCES:
        return "STALE" if nav_is_stale(observed, as_of) else "END_OF_DAY"
    return "UNKNOWN"


def source_ref(prov: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise provenance into the SourceRef shape; name and official status come from the registry."""
    sid = str(prov.get("source_id") or "")
    spec = REGISTRY.get(sid)
    if spec is not None:
        name, official = spec.name, spec.official and prov.get("quality_status") not in ("fixture",)
    elif sid in {"fixture"}:
        name, official = "Development fixture (synthetic)", False
    elif sid.startswith("user."):
        name, official = "Your own records", False
    else:
        name, official = sid or "unknown source", False
    return {
        "source_id": sid,
        "source_name": name,
        "url": str(prov.get("url") or prov.get("source_url") or ""),
        "retrieved_at": prov.get("retrieved_at"),
        "observation_date": prov.get("observation_date"),
        "quality_status": str(prov.get("quality_status") or ""),
        "official": bool(official),
        # The stored observation behind the number, when known (portfolio valuations link to /api/evidence/{id}).
        **{k: prov[k] for k in ("obs_id", "evidence") if k in prov},
    }


def iter_explained(obj: Any) -> Iterator[dict[str, Any]]:
    """Yield every Explained-shaped dict nested anywhere in an API response."""
    if isinstance(obj, dict):
        if {"id", "display", "formula_id", "freshness"} <= obj.keys():
            yield obj
        for v in obj.values():
            yield from iter_explained(v)
    elif isinstance(obj, list | tuple):
        for v in obj:
            yield from iter_explained(v)


def contract_errors(e: Mapping[str, Any]) -> list[str]:
    errs = [f"{e.get('id')}: missing {k}" for k in _REQUIRED_KEYS if k not in e]
    if e.get("freshness") not in FRESHNESS:
        errs.append(f"{e.get('id')}: unknown freshness {e.get('freshness')!r}")
    for s in e.get("sources") or []:
        errs.extend(f"{e.get('id')}: source missing {k}" for k in _SOURCE_KEYS if k not in s)
    return errs
