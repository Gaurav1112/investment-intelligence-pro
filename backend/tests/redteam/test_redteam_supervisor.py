"""Red team (Phase 14): supervisor bypasses — numeric-provenance validator, banned-phrase obfuscation, empty runs."""

from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest

from iip.supervisor import compliance
from iip.supervisor.facts import FactSheet
from iip.supervisor.manifest import ContextItem, ContextKind, ContextManifest, ContextValue
from iip.supervisor.supervisor import Outcome, run

DISPLAYS = frozenset({"₹1,00,000.00", "6.50%", "2026-10-14", "12"})


@pytest.mark.parametrize(
    "text",
    [
        "Invest 1e5 today.",  # scientific notation
        "Put 5 lakh in it.",  # Indian scale words
        "₹5L is enough.",
        "Aim for five percent.",  # spelled-out numbers
        "It could double in a year.",
        "1,00,000/- is the minimum.",
        "A loss of -6.50% is possible.",  # sign flip of an allowed display
        "A loss of −6.50% is possible.",  # U+2212 minus
        "It returned 12x.",  # multiplier on an allowed bare number
        "About 12k units.",
        "Expect 12 lakh.",
    ],
)
def test_rt07_numeric_validator_rejects_disguised_numbers(text: str) -> None:
    assert compliance.unsupported_numbers(text, DISPLAYS), text


@pytest.mark.parametrize(
    "text",
    [
        "With ₹1,00,000.00 the low-end scenario is 6.50%.",
        "Observed on 2026-10-14; settles T+1; band q05 to q95.",
        "One option passed every constraint.",
    ],
)
def test_rt07_numeric_validator_still_accepts_cited_numbers(text: str) -> None:
    assert compliance.unsupported_numbers(text, DISPLAYS) == []


@pytest.mark.parametrize(
    "text",
    [
        "guar\u00adanteed",  # soft hyphen
        "g\u200buaranteed",  # zero-width space
        "risk\u2011free",  # non-breaking hyphen
        "assured  returns",  # double space
        "assured\nreturns",
        "ｇｕａｒａｎｔｅｅｄ",  # fullwidth
        "gu\u0430ranteed returns",  # Cyrillic a
    ],
)
def test_rt07_banned_phrase_obfuscation_is_caught(text: str) -> None:
    assert compliance.blocked(text), text


@dataclass
class _NoWorker:
    pass


def test_rt09_run_without_any_required_worker_cannot_answer() -> None:
    """With an empty worker list the gate passed and the Supervisor returned ANSWERED with an empty report."""
    manifest = ContextManifest("q", (ContextItem("user.amount", ContextKind.USER_INPUT, "Amount"),))
    ctx = {"user.amount": ContextValue("user.amount", present=True, valid=True)}
    workers: list[Any] = []
    result = run(manifest=manifest, context=ctx, facts=FactSheet(), workers=workers, as_of=date(2026, 10, 15))
    assert result.outcome is Outcome.ABSTAIN
    assert result.report is None
