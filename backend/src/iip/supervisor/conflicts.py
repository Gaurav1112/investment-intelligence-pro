"""Deterministic conflict detection (ADR-0003 §5). Conflicts are surfaced, never resolved into a score."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from iip.supervisor.contracts import Stance, WorkerContract, WorkerStatus


@dataclass(frozen=True)
class Conflict:
    subject: str
    topic: str
    supporting: tuple[str, ...]  # "worker:claim_id"
    challenging: tuple[str, ...]
    material: bool
    declared: str = ""  # free-text conflict a worker declared itself


def detect_conflicts(contracts: list[WorkerContract]) -> list[Conflict]:
    by_key: dict[tuple[str, str], dict[Stance, list[tuple[str, bool]]]] = defaultdict(lambda: defaultdict(list))
    for c in contracts:
        if c.status is not WorkerStatus.ANSWERED:
            continue
        for claim in c.claims:
            by_key[(claim.subject, claim.topic)][claim.stance].append((f"{c.worker}:{claim.claim_id}", claim.material))
    found: list[Conflict] = []
    for (subject, topic), stances in sorted(by_key.items()):
        sup, cha = stances.get(Stance.SUPPORTS, []), stances.get(Stance.CHALLENGES, [])
        if sup and cha:
            material = any(m for _, m in sup) and any(m for _, m in cha)
            found.append(
                Conflict(subject, topic, tuple(sorted(s for s, _ in sup)), tuple(sorted(s for s, _ in cha)), material)
            )
    for c in contracts:
        for text in c.conflicts:
            found.append(
                Conflict(
                    subject="*", topic="declared", supporting=(), challenging=(c.worker,), material=True, declared=text
                )
            )
    return found
