"""Context manifests and the completeness gate (ADR-0003 §1–§4; requirements.md §3.6a)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

MANIFEST_VERSION = "context_manifest@1.0.0"


class ContextKind(StrEnum):
    USER_INPUT = "user_input"
    OBSERVATION = "observation"
    RULE = "rule"
    TERMS = "terms"


@dataclass(frozen=True)
class ContextItem:
    item_id: str
    kind: ContextKind
    description: str
    required: bool = True
    max_age_days: int | None = None  # freshness rule, measured from observation_date to as_of
    acceptable_sources: frozenset[str] | None = None  # None = any registered source


@dataclass(frozen=True)
class ContextValue:
    """What a context provider found for one manifest item."""

    item_id: str
    present: bool
    observation_date: date | None = None
    source_id: str | None = None
    provenance_complete: bool = False
    valid: bool = False
    fact_ids: tuple[str, ...] = ()
    note: str = ""


class GapReason(StrEnum):
    MISSING = "MISSING"
    STALE = "STALE"
    UNACCEPTABLE_SOURCE = "UNACCEPTABLE_SOURCE"
    PROVENANCE_INCOMPLETE = "PROVENANCE_INCOMPLETE"
    INVALID = "INVALID"


@dataclass(frozen=True)
class Gap:
    item_id: str
    reason: GapReason
    required: bool
    description: str
    detail: str = ""


@dataclass(frozen=True)
class ContextManifest:
    question_type: str
    items: tuple[ContextItem, ...]
    version: str = MANIFEST_VERSION

    def item(self, item_id: str) -> ContextItem:
        for it in self.items:
            if it.item_id == item_id:
                return it
        raise KeyError(item_id)


@dataclass(frozen=True)
class GateResult:
    complete: bool
    gaps: tuple[Gap, ...]
    checked: tuple[str, ...] = field(default_factory=tuple)

    @property
    def blocking(self) -> tuple[Gap, ...]:
        return tuple(g for g in self.gaps if g.required)


def evaluate_gate(manifest: ContextManifest, values: dict[str, ContextValue], as_of: date) -> GateResult:
    """Deterministic completeness check. Never fills a gap; only reports it."""
    gaps: list[Gap] = []
    for item in manifest.items:
        v = values.get(item.item_id)
        if v is None or not v.present:
            gaps.append(Gap(item.item_id, GapReason.MISSING, item.required, item.description))
            continue
        if item.kind is not ContextKind.USER_INPUT and not v.provenance_complete:
            gaps.append(Gap(item.item_id, GapReason.PROVENANCE_INCOMPLETE, item.required, item.description))
            continue
        if not v.valid:
            gaps.append(Gap(item.item_id, GapReason.INVALID, item.required, item.description, v.note))
            continue
        if item.acceptable_sources is not None and v.source_id not in item.acceptable_sources:
            gaps.append(
                Gap(item.item_id, GapReason.UNACCEPTABLE_SOURCE, item.required, item.description, str(v.source_id))
            )
            continue
        if item.max_age_days is not None:
            if v.observation_date is None:
                gaps.append(Gap(item.item_id, GapReason.PROVENANCE_INCOMPLETE, item.required, item.description))
                continue
            age = (as_of - v.observation_date).days
            if age > item.max_age_days or age < 0:
                detail = f"observed {v.observation_date.isoformat()}, {age} days before {as_of.isoformat()}"
                if age < 0:
                    detail = f"observation date {v.observation_date.isoformat()} is after as-of {as_of.isoformat()}"
                gaps.append(Gap(item.item_id, GapReason.STALE, item.required, item.description, detail))
    complete = not any(g.required for g in gaps)
    return GateResult(complete=complete, gaps=tuple(gaps), checked=tuple(i.item_id for i in manifest.items))
