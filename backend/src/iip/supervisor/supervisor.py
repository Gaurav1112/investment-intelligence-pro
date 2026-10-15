"""The Supervisor: deterministic orchestration with a completeness gate (requirements.md §3.6a, ADR-0003).

    manifest → gate → (ABSTAIN with itemised gaps) | workers → contract validation → conflicts → synthesis → RunRecord

The Supervisor never fills gaps, never invents numbers, and never resolves disagreement into a score.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, Protocol

from iip.engine.determinism import content_hash
from iip.supervisor.conflicts import Conflict, detect_conflicts
from iip.supervisor.contracts import ContractViolation, WorkerContract, WorkerStatus, validate_contract
from iip.supervisor.facts import FactSheet
from iip.supervisor.manifest import ContextManifest, ContextValue, Gap, GateResult, evaluate_gate
from iip.supervisor.synthesis import Report, build_report

SUPERVISOR_VERSION = "supervisor@1.0.0"


class Outcome(StrEnum):
    ANSWERED = "ANSWERED"
    ABSTAIN = "ABSTAIN"


class Worker(Protocol):
    name: str
    required: bool

    def run(self, facts: FactSheet, context: dict[str, ContextValue], payload: Any) -> WorkerContract: ...


@dataclass(frozen=True)
class RunRecord:
    question_type: str
    as_of: date
    versions: dict[str, str]
    input_hash: str
    output_hash: str


@dataclass(frozen=True)
class SupervisorResult:
    outcome: Outcome
    gate: GateResult
    contracts: tuple[WorkerContract, ...]
    violations: tuple[ContractViolation, ...]
    conflicts: tuple[Conflict, ...]
    report: Report | None
    abstain_reasons: tuple[str, ...]
    payload: Any
    record: RunRecord
    versions: dict[str, str] = field(default_factory=dict)


def _gap_text(g: Gap) -> str:
    suffix = f" ({g.detail})" if g.detail else ""
    return f"{g.reason.value}: {g.description}{suffix}"


def run(
    *,
    manifest: ContextManifest,
    context: dict[str, ContextValue],
    facts: FactSheet,
    workers: Sequence[Worker],
    as_of: date,
    payload: Any = None,
    disclosure_keys: tuple[str, ...] = (),
    engine_versions: dict[str, str] | None = None,
    llm_rephrase: Callable[[str], str] | None = None,
) -> SupervisorResult:
    versions = {"supervisor": SUPERVISOR_VERSION, "manifest": manifest.version, **(engine_versions or {})}
    input_hash = content_hash(
        {
            "manifest": manifest,
            "context": dict(sorted(context.items())),
            "facts": dict(sorted(facts.facts.items())),
            "as_of": as_of,
            "versions": versions,
            "payload": payload,
            "workers": [w.name for w in workers],
        }
    )
    gate = evaluate_gate(manifest, context, as_of)
    contracts: list[WorkerContract] = []
    violations: list[ContractViolation] = []
    abstain: list[str] = []
    report: Report | None = None
    conflicts: list[Conflict] = []

    if not gate.complete:
        abstain = [_gap_text(g) for g in gate.blocking]
    elif not any(w.required for w in workers):
        # An answer needs at least one required worker's contract; an empty or optional-only run cannot ANSWER.
        abstain = ["NO_REQUIRED_WORKER: no required worker was run for this question"]
    else:
        for worker in workers:  # fixed order → deterministic
            contract = worker.run(facts, context, payload)
            check = validate_contract(contract, facts)
            if not check.ok:
                violations.extend(check.violations)
                if worker.required:
                    abstain.append(f"INVALID_CONTRACT: required worker {worker.name} returned an invalid contract")
                continue
            contracts.append(contract)
            if worker.required and contract.status is WorkerStatus.ABSTAINED:
                abstain.append(f"WORKER_ABSTAINED: {worker.name}: {contract.abstain_reason}")
        if not abstain:
            conflicts = detect_conflicts(contracts)
            report = build_report(contracts, facts, conflicts, disclosure_keys, llm_rephrase)

    outcome = Outcome.ABSTAIN if abstain else Outcome.ANSWERED
    body = {
        "outcome": outcome, "gaps": gate.gaps, "contracts": contracts, "violations": violations,
        "conflicts": conflicts, "abstain": abstain,
        "report": None if report is None else {"sections": report.sections, "disclosures": report.disclosures,
                                              "writer": report.writer, "narrative": report.narrative},
        "payload": payload,
    }  # fmt: skip
    record = RunRecord(manifest.question_type, as_of, versions, input_hash, content_hash(body))
    return SupervisorResult(
        outcome,
        gate,
        tuple(contracts),
        tuple(violations),
        tuple(conflicts),
        report,
        tuple(abstain),
        payload,
        record,
        versions,
    )
