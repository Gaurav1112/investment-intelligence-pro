"""Facts: the ONLY way a number may reach user-facing text (ADR-0003 §3, §6).

A Fact is either an engine calculation (formula id + input hash + engine version) or a dated source observation.
Claims reference facts by id; text is rendered from the fact's display string.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from iip.engine.errors import InvalidInput


class FactOrigin(StrEnum):
    ENGINE = "engine"
    OBSERVATION = "observation"
    USER_INPUT = "user_input"  # the user's own stated constraint (e.g. amount) — displayed back, never invented


@dataclass(frozen=True)
class Fact:
    fact_id: str
    display: str  # exact string that may appear in text (e.g. "₹1,00,534.00", "6.50%", "2026-10-14")
    origin: FactOrigin
    value: Decimal | str | None = None
    unit: str | None = None
    # engine provenance
    formula_id: str | None = None
    input_hash: str | None = None
    engine_version: str | None = None
    # observation provenance
    source_id: str | None = None
    source_url: str | None = None
    observation_date: date | None = None
    retrieved_at: datetime | None = None
    quality_status: str | None = None

    def __post_init__(self) -> None:
        if not self.fact_id or not self.display:
            raise InvalidInput("fact requires id and display")
        if self.origin is FactOrigin.ENGINE and not (self.formula_id and self.input_hash and self.engine_version):
            raise InvalidInput(f"engine fact {self.fact_id} lacks formula/input-hash/engine-version provenance")
        if self.origin is FactOrigin.OBSERVATION:
            missing = [
                n for n in ("source_id", "source_url", "observation_date", "retrieved_at", "quality_status")
                if getattr(self, n) is None
            ]  # fmt: skip
            if missing:
                raise InvalidInput(f"observation fact {self.fact_id} lacks provenance: {missing}")
            if self.retrieved_at is not None and self.retrieved_at.tzinfo is None:
                raise InvalidInput(f"observation fact {self.fact_id}: retrieved_at must be timezone-aware")


@dataclass
class FactSheet:
    """Append-only registry of facts for one supervisor run."""

    facts: dict[str, Fact] = field(default_factory=dict)

    def add(self, fact: Fact) -> Fact:
        existing = self.facts.get(fact.fact_id)
        if existing is not None and existing != fact:
            raise InvalidInput(f"conflicting definitions for fact {fact.fact_id}")
        self.facts[fact.fact_id] = fact
        return fact

    def get(self, fact_id: str) -> Fact:
        try:
            return self.facts[fact_id]
        except KeyError as exc:
            raise InvalidInput(f"unknown fact {fact_id}") from exc

    def __contains__(self, fact_id: object) -> bool:
        return fact_id in self.facts

    def displays(self) -> frozenset[str]:
        return frozenset(f.display for f in self.facts.values())
