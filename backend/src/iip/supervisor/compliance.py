"""Compliance Guard (regulatory-readiness.md §5 G1–G8, §7) and numeric-provenance validator (ADR-0003 §6)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

import yaml

from iip.supervisor.contracts import strip_allowed_literals

# Numbers as they appear in prose: ₹1,00,534.00 · 6.50% · 0.534 · 2026-10-14 · 91-day
_NUMBER = re.compile(r"\d{4}-\d{2}-\d{2}|₹?\s?\d[\d,]*(?:\.\d+)?%?")


@dataclass(frozen=True)
class PhraseHit:
    tier: str  # "block" | "warn"
    category: str
    pattern: str
    match: str


@dataclass(frozen=True)
class ComplianceRules:
    version: str
    block: tuple[tuple[str, re.Pattern[str]], ...]
    warn: tuple[re.Pattern[str], ...]
    required: dict[str, str]


@lru_cache(maxsize=1)
def load_rules() -> ComplianceRules:
    raw: dict[str, Any] = yaml.safe_load(
        (resources.files("iip.rules") / "compliance_phrases.yaml").read_text(encoding="utf-8")
    )
    block = tuple(
        (category, re.compile(pattern, re.IGNORECASE))
        for category, patterns in raw["block"].items()
        for pattern in patterns
    )
    warn = tuple(re.compile(p, re.IGNORECASE) for p in raw["warn"])
    return ComplianceRules(version=raw["version"], block=block, warn=warn, required=dict(raw["required"]))


def _strip_required(text: str, rules: ComplianceRules) -> str:
    """Required disclosures (e.g. 'Not investment advice') are exempt verbatim — and only verbatim."""
    for phrase in rules.required.values():
        text = text.replace(phrase, " ")
    return text


def scan(text: str, rules: ComplianceRules | None = None) -> list[PhraseHit]:
    rules = rules or load_rules()
    body = _strip_required(text, rules)
    hits: list[PhraseHit] = []
    for category, pattern in rules.block:
        for m in pattern.finditer(body):
            hits.append(PhraseHit("block", category, pattern.pattern, m.group(0)))
    for pattern in rules.warn:
        for m in pattern.finditer(body):
            hits.append(PhraseHit("warn", "context_required", pattern.pattern, m.group(0)))
    return hits


def blocked(text: str) -> list[PhraseHit]:
    return [h for h in scan(text) if h.tier == "block"]


def _norm(token: str) -> str:
    return token.replace("₹", "").replace(",", "").replace(" ", "").strip()


def unsupported_numbers(
    text: str, allowed_displays: frozenset[str], extra_allowed: frozenset[str] = frozenset()
) -> list[str]:
    """Every numeric token in text must occur inside some fact display (or an allowlisted constant).

    This is the guard that stops an LLM (or a careless template) from introducing an unsourced number.
    """
    rules = load_rules()
    body = strip_allowed_literals(_strip_required(text, rules))
    allowed_norm = {_norm(d) for d in allowed_displays} | {_norm(x) for x in extra_allowed}
    allowed_tokens: set[str] = set()
    for display in allowed_displays | extra_allowed:
        allowed_tokens.update(_norm(m.group(0)) for m in _NUMBER.finditer(display))
    bad: list[str] = []
    for m in _NUMBER.finditer(body):
        tok = _norm(m.group(0))
        if not tok:
            continue
        if tok in allowed_tokens or tok in allowed_norm:
            continue
        bad.append(m.group(0).strip())
    return bad
