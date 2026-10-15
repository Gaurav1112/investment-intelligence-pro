"""Synthesis: render claims from facts, attach disclosures, and enforce the Compliance Guard.

Templates are the default writer. An optional LLM may rephrase (ADR-0007), but its text is accepted only if it
passes the numeric-provenance validator and the banned-phrase scan; otherwise the template text is used.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from iip.supervisor import compliance
from iip.supervisor.conflicts import Conflict
from iip.supervisor.contracts import PLACEHOLDER, Claim, WorkerContract, WorkerStatus
from iip.supervisor.facts import FactOrigin, FactSheet


class ComplianceViolation(RuntimeError):
    """A deterministic template produced banned text — a defect in our own copy, so fail loudly."""


@dataclass(frozen=True)
class RenderedClaim:
    worker: str
    claim_id: str
    subject: str
    topic: str
    stance: str
    text: str
    cites: tuple[str, ...]


@dataclass(frozen=True)
class Report:
    sections: tuple[RenderedClaim, ...]
    conflicts: tuple[Conflict, ...]
    disclosures: tuple[str, ...]
    writer: str  # "template" | "llm"
    narrative: str
    rejected_llm_reasons: tuple[str, ...] = field(default_factory=tuple)


def render_claim(claim: Claim, facts: FactSheet) -> str:
    return PLACEHOLDER.sub(lambda m: facts.get(m.group(1)).display, claim.template)


def _own_copy(claim: Claim, facts: FactSheet) -> str:
    """The text WE wrote: the template plus engine-computed displays. Observation and user-input displays (instrument
    names, an amount) are source or user DATA, so a name such as "… Capital Protection Oriented Fund" is shown
    verbatim but is not treated as a defect in our copy (it used to raise and fail every Discovery run)."""

    def sub(m: re.Match[str]) -> str:
        fact = facts.get(m.group(1))
        return fact.display if fact.origin is FactOrigin.ENGINE else " "

    return PLACEHOLDER.sub(sub, claim.template)


def build_report(
    contracts: list[WorkerContract],
    facts: FactSheet,
    conflicts: list[Conflict],
    disclosure_keys: tuple[str, ...],
    llm_rephrase: Callable[[str], str] | None = None,
) -> Report:
    rules = compliance.load_rules()
    rendered: list[RenderedClaim] = []
    for c in contracts:
        if c.status is not WorkerStatus.ANSWERED:
            continue
        for claim in c.claims:
            text = render_claim(claim, facts)
            hits = compliance.blocked(_own_copy(claim, facts))
            if hits:
                raise ComplianceViolation(f"{c.worker}:{claim.claim_id} rendered banned copy: {hits}")
            rendered.append(
                RenderedClaim(
                    c.worker, claim.claim_id, claim.subject, claim.topic, claim.stance.value, text, claim.cites
                )
            )
    disclosures = tuple(rules.required[k] for k in ("footer", *disclosure_keys))
    narrative = "\n".join(r.text for r in rendered)
    writer = "template"
    rejected: list[str] = []
    if llm_rephrase is not None and narrative:
        candidate = llm_rephrase(narrative)
        bad_numbers = compliance.unsupported_numbers(candidate, facts.displays())
        banned = compliance.blocked(candidate)
        if bad_numbers:
            rejected.append(f"unsupported numbers: {bad_numbers}")
        if banned:
            rejected.append(f"banned phrases: {[h.match for h in banned]}")
        if not rejected:
            narrative, writer = candidate, "llm"
            disclosures = (*disclosures, rules.required["ai_disclosure"])
    return Report(tuple(rendered), tuple(conflicts), disclosures, writer, narrative, tuple(rejected))
