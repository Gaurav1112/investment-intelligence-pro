"""Worker contracts (ADR-0003 §3). Workers return structured, validated contracts — never free numeric text."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from iip.supervisor.facts import FactSheet

CONTRACT_VERSION = "worker_contract@1.0.0"
_DIGIT = re.compile(r"\d")
PLACEHOLDER = re.compile(r"\{fact:([A-Za-z0-9_.:\-]+)\}")
_BRACE = re.compile(r"[{}]")

# Methodology vocabulary that contains digits but carries no data (shared with the numeric validator).
ALLOWED_LITERALS = re.compile(
    r"\b\d{1,2}(?:st|nd|rd|th)[- ]percentile\b|\bT\+\d\b|\b30E?/360\b|\bACT/36[05]F?\b|\bq(?:05|50|95)\b",
    re.IGNORECASE,
)


def strip_allowed_literals(text: str) -> str:
    return ALLOWED_LITERALS.sub(" ", text)


class WorkerStatus(StrEnum):
    ANSWERED = "answered"
    ABSTAINED = "abstained"


class Stance(StrEnum):
    """Direction of a claim about a subject — used for deterministic disagreement detection."""

    SUPPORTS = "supports"
    CHALLENGES = "challenges"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class Evidence:
    source_id: str
    url: str
    observation_date: date
    retrieved_at: datetime
    note: str = ""


@dataclass(frozen=True)
class Claim:
    """A templated statement. Placeholders like {fact:tbill.yield} are filled only from the FactSheet.

    The literal template text may not contain digits — every number must come through a cited fact."""

    claim_id: str
    subject: str  # e.g. instrument id or "portfolio"
    topic: str  # e.g. "credit", "liquidity", "return", "data_quality"
    stance: Stance
    template: str
    cites: tuple[str, ...] = ()
    material: bool = True


@dataclass(frozen=True)
class WorkerContract:
    worker: str
    status: WorkerStatus
    claims: tuple[Claim, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    gaps: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    requested_calculations: tuple[str, ...] = ()
    abstain_reason: str | None = None
    version: str = CONTRACT_VERSION


@dataclass(frozen=True)
class ContractViolation:
    worker: str
    code: str
    detail: str


@dataclass
class ValidationReport:
    violations: list[ContractViolation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations


def template_fields(template: str) -> list[str]:
    """Fact ids referenced as {fact:<id>} placeholders, in order."""
    return PLACEHOLDER.findall(template)


def template_literal(template: str) -> str:
    """Template text with placeholders removed."""
    return PLACEHOLDER.sub(" ", template)


def validate_contract(contract: WorkerContract, facts: FactSheet) -> ValidationReport:
    report = ValidationReport()

    def bad(code: str, detail: str) -> None:
        report.violations.append(ContractViolation(contract.worker, code, detail))

    if contract.version != CONTRACT_VERSION:
        bad("VERSION", f"unsupported contract version {contract.version}")
    if contract.status is WorkerStatus.ABSTAINED:
        if not contract.abstain_reason:
            bad("ABSTAIN_WITHOUT_REASON", "abstained contracts must say why")
        if contract.claims:
            bad("ABSTAIN_WITH_CLAIMS", "abstained contracts may not carry claims")
        return report
    if not contract.claims:
        bad("ANSWERED_WITHOUT_CLAIMS", "answered contracts must carry at least one claim")
    seen: set[str] = set()
    for claim in contract.claims:
        if claim.claim_id in seen:
            bad("DUPLICATE_CLAIM", claim.claim_id)
        seen.add(claim.claim_id)
        fields = template_fields(claim.template)
        literal = template_literal(claim.template)
        if _BRACE.search(literal):
            bad("BAD_PLACEHOLDER", f"{claim.claim_id}: only {{fact:<id>}} placeholders are allowed")
        if _DIGIT.search(strip_allowed_literals(literal)):
            bad("FREE_NUMBER", f"{claim.claim_id}: template contains a literal digit; numbers must be cited facts")
        for fact_id in fields:
            if fact_id not in claim.cites:
                bad("UNCITED_PLACEHOLDER", f"{claim.claim_id}: {fact_id} used but not cited")
        for fact_id in claim.cites:
            if fact_id not in facts:
                bad("UNKNOWN_FACT", f"{claim.claim_id}: cites unknown fact {fact_id}")
    for ev in contract.evidence:
        if ev.retrieved_at.tzinfo is None:
            bad("NAIVE_TIMESTAMP", f"evidence {ev.source_id} retrieved_at is naive")
    return report
