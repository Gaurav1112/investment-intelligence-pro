"""Compliance Guard (regulatory-readiness.md §5 G1–G8, §7) and numeric-provenance validator (ADR-0003 §6).

Surface-aware (B04; design-risk-first.md §7.3, §9.4; PLAN.md §8 U-11): the ``block`` list applies everywhere; each
``surface_block`` category applies only on the surfaces it names. The owner's vocabulary opt-in can lift a category on
the PRIVATE surface only — export, share, public and ping surfaces keep the BLOCK. Neutral wording is the default.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from importlib import resources
from typing import Any

import yaml

from iip.supervisor.contracts import strip_allowed_literals

# Numbers as they appear in prose: ₹1,00,534.00 · 6.50% · 0.534 · 2026-10-14 · 91-day.
# A leading sign (not glued to a word, so "COVID-19" is not negative), scientific notation and a trailing scale or
# multiplier ("12x", "5 lakh", "₹5L", "12k") are PART of the token: "-6.50%" or "12x" is not the cited "6.50%" or "12".
_NUMBER = re.compile(
    r"(?:(?<!\w)[-+])?"
    r"(?:\d{4}-\d{2}-\d{2}|₹\s?\d[\d,]*(?:\.\d+)?%?|\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?%?)"
    r"(?:\s?(?:x|X|k|K|L|lakhs?|lacs?|crores?|cr|Cr|mn|bn|million|billion|thousand|hundred)\b)?"
)
# Spelled-out quantities carry no citation, so the validator cannot trace them: rejected outright ("one" is allowed —
# it is ordinary prose, and "one percent" is still caught by "percent").
_NUMBER_WORDS = re.compile(
    r"\b(?:zero|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
    r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundreds?|thousands?|"
    r"lakhs?|lacs?|crores?|millions?|billions?|trillions?|percent|per\s?cent|percentage points?|bps|basis points?|"
    r"double[ds]?|doubling|triple[ds]?|tripling|twice|thrice|half|halve[ds]?|dozens?)\b",
    re.IGNORECASE,
)
# Invisible or look-alike characters that would let banned copy slip past a regex (SEC: supervisor bypass).
_INVISIBLE = dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\u2060\ufeff\u180e"), None)
_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe63\uff0d"), "-")
_CONFUSABLES = str.maketrans(
    "\u0430\u0435\u043e\u0440\u0441\u0443\u0445\u0456\u0458\u0455\u0501\u0261\u03bf\u03b1\u03b5\u03c1"
    "\u0410\u0412\u0415\u041a\u041c\u041d\u041e\u0420\u0421\u0422\u0425\u0391\u0392\u0395\u0397\u0399"
    "\u039a\u039c\u039d\u039f\u03a1\u03a4\u03a7",
    "aeopcyxijsdgoaepABEKMHOPCTXABEHIKMNOPTX",
)


def normalise(text: str) -> str:
    """Canonical form for scanning: NFKC (fullwidth → ASCII), invisible characters removed, dash variants → '-',
    common Cyrillic/Greek look-alikes → Latin, and every whitespace run → one space."""
    t = unicodedata.normalize("NFKC", text).translate(_INVISIBLE).translate(_DASHES).translate(_CONFUSABLES)
    return re.sub(r"\s+", " ", t)


class Surface(StrEnum):
    """Where a text is shown. PRIVATE is the owner's logged-in view; every other surface can leave the owner's hands."""

    PRIVATE = "private"
    EXPORT = "export"
    SHARE = "share"
    PUBLIC = "public"  # any unauthenticated page
    PING = "ping"  # a push-notification body


class Vocabulary(StrEnum):
    """The owner's wording choice (U-11). NEUTRAL ("entry/exit condition met") is the default; BADGES is the opt-in
    for BUY/SELL badges, honoured on the PRIVATE surface only."""

    NEUTRAL = "neutral"
    BADGES = "badges"


def parse_surface(value: object) -> Surface:
    """Unknown or missing → PUBLIC (fail closed: the strictest surface a human reads)."""
    try:
        return Surface(str(value).strip().lower())
    except ValueError:
        return Surface.PUBLIC


def parse_vocabulary(value: object) -> Vocabulary:
    """Unknown or missing → NEUTRAL (the U-11 default)."""
    try:
        return Vocabulary(str(value).strip().lower())
    except ValueError:
        return Vocabulary.NEUTRAL


@dataclass(frozen=True)
class SurfaceRule:
    category: str
    surfaces: frozenset[Surface]
    opt_in: Vocabulary | None  # lifts this category on PRIVATE only
    patterns: tuple[re.Pattern[str], ...]

    def applies(self, surface: Surface, vocabulary: Vocabulary) -> bool:
        if surface not in self.surfaces:
            return False
        return not (surface is Surface.PRIVATE and self.opt_in is not None and vocabulary is self.opt_in)


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
    surface_block: tuple[SurfaceRule, ...] = field(default=())


def _surface_rules(raw: dict[str, Any]) -> tuple[SurfaceRule, ...]:
    out: list[SurfaceRule] = []
    for category, spec in (raw.get("surface_block") or {}).items():
        surfaces = frozenset(Surface(s) for s in spec["surfaces"])  # an unknown surface name is a broken rule file
        opt_in = Vocabulary(spec["opt_in"]) if spec.get("opt_in") else None
        patterns = tuple(re.compile(p, re.IGNORECASE) for p in spec["patterns"])
        if not surfaces or not patterns:
            raise ValueError(f"compliance surface rule {category!r} needs surfaces and patterns")
        out.append(SurfaceRule(category, surfaces, opt_in, patterns))
    return tuple(out)


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
    return ComplianceRules(
        version=raw["version"],
        block=block,
        warn=warn,
        required=dict(raw["required"]),
        surface_block=_surface_rules(raw),
    )


def _strip_required(text: str, rules: ComplianceRules) -> str:
    """Required disclosures (e.g. 'Not investment advice') are exempt verbatim — and only verbatim."""
    for phrase in rules.required.values():
        text = text.replace(phrase, " ")
    return text


def scan(
    text: str,
    rules: ComplianceRules | None = None,
    *,
    surface: Surface = Surface.PRIVATE,
    vocabulary: Vocabulary = Vocabulary.NEUTRAL,
) -> list[PhraseHit]:
    rules = rules or load_rules()
    # A ping carries no disclosure, so nothing is exempt there: a disclosure smuggled into a ping is scanned in full.
    body = normalise(text) if surface is Surface.PING else _strip_required(normalise(text), rules)
    hits: list[PhraseHit] = []
    for category, pattern in rules.block:
        for m in pattern.finditer(body):
            hits.append(PhraseHit("block", category, pattern.pattern, m.group(0)))
    for rule in rules.surface_block:
        if not rule.applies(surface, vocabulary):
            continue
        for pattern in rule.patterns:
            for m in pattern.finditer(body):
                hits.append(PhraseHit("block", rule.category, pattern.pattern, m.group(0)))
    for pattern in rules.warn:
        for m in pattern.finditer(body):
            hits.append(PhraseHit("warn", "context_required", pattern.pattern, m.group(0)))
    return hits


def blocked(
    text: str, *, surface: Surface = Surface.PRIVATE, vocabulary: Vocabulary = Vocabulary.NEUTRAL
) -> list[PhraseHit]:
    return [h for h in scan(text, surface=surface, vocabulary=vocabulary) if h.tier == "block"]


def _norm(token: str) -> str:
    return token.replace("₹", "").replace(",", "").replace(" ", "").strip()


def _tokens(text: str) -> list[str]:
    return [m.group(0).strip() for m in _NUMBER.finditer(text)]


def unsupported_numbers(
    text: str, allowed_displays: frozenset[str], extra_allowed: frozenset[str] = frozenset()
) -> list[str]:
    """Every numeric token in text must occur inside some fact display (or an allowlisted constant).

    This is the guard that stops an LLM (or a careless template) from introducing an unsourced number.
    """
    rules = load_rules()
    body = strip_allowed_literals(_strip_required(normalise(text), rules))
    allowed_norm = {_norm(normalise(d)) for d in allowed_displays} | {_norm(normalise(x)) for x in extra_allowed}
    allowed_tokens: set[str] = set()
    for display in allowed_displays | extra_allowed:
        allowed_tokens.update(_norm(t) for t in _tokens(normalise(display)))
    bad: list[str] = []
    for raw in _tokens(body):
        tok = _norm(raw)
        if not tok:
            continue
        if tok in allowed_tokens or tok in allowed_norm:
            continue
        bad.append(raw)
    bad.extend(m.group(0) for m in _NUMBER_WORDS.finditer(body))
    return bad
