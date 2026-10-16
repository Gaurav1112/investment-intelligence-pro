"""L3 stress values per risk class — ``risk.stress_combinator@1`` and ``risk.debt_mtm_stress@1``.

design-risk-first.md §5.2 as amended by design-judgement.md §2.1 item 4:

    s(class) = max(cited table value, drawdown recomputed in-app from AMFI index-fund NAVs)

Both values are returned together with the AMFI series start and end dates, because an AMFI series that starts after a
crash cannot see that crash.  The cited values are not in this module: per U-08 they come from local config through the
rule loader, and the recomputed drawdown comes from the series-grid engine.  This module only combines what it is given.

Stress values are positive magnitudes of the worst observed peak-to-trough fall (0.30 = a 30 % fall).  They describe
history, not a forecast, and the worst observed fall is not the worst possible fall.

Fixed rows that are never combined:

* HYBRID — 100 % of the EQ_BROAD value (conservative PARAMETER; no cited equity-share table yet).
* STOCK — 1.00 (total loss is possible for a single company; deliberately maximal PARAMETER).
* CASH_LIKE — 0 (no mark-to-market; default risk belongs to L4).
* DEBT_MTM — per holding, ``D_mod × Δy + D_spread × Δs`` (repo ``docs/finance/risk-methodology.md`` §7.5); shock sizes
  are PARAMETERs (Δy 0.02; Δs 0.01 for AAA, 0.03 for AA and below).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from iip.engine.errors import InvalidInput
from iip.engine.money import ONE, ZERO, D, engine_context
from iip.engine.risk import Abstention, Outcome, RiskClass, Status

COMBINATOR_ID = "risk.stress_combinator@1"
DEBT_MTM_ID = "risk.debt_mtm_stress@1"

STOCK_STRESS = D("1.00")
CASH_STRESS = ZERO

# Classes whose stress comes from the table via the max(cited, recomputed) rule.
TABLE_CLASSES: tuple[RiskClass, ...] = (
    RiskClass.EQ_LARGE,
    RiskClass.EQ_BROAD,
    RiskClass.EQ_MID,
    RiskClass.EQ_SMALL,
    RiskClass.EQ_FACTOR,
    RiskClass.EQ_SECTOR_THEMATIC,
    RiskClass.GOLD,
)

Chosen = Literal["CITED", "RECOMPUTED", "DERIVED", "FIXED", "NONE"]


class CreditBucket(StrEnum):
    AAA = "AAA"
    BELOW_AAA = "BELOW_AAA"  # AA and below


@dataclass(frozen=True)
class CitedStress:
    """A row of ``rules/risk/stress_drawdowns.yaml`` (values from local config per U-08)."""

    value: Decimal
    citation: str
    status: Status
    recovery_years: Decimal | None = None  # peak → recovery; None = not recovered or NOT VERIFIED


@dataclass(frozen=True)
class RecomputedDrawdown:
    """Maximum drawdown recomputed in-app from an AMFI NAV series (supplied by the series-grid engine)."""

    value: Decimal
    series_start: date
    series_end: date
    fact_id: str
    recovery_years: Decimal | None = None


@dataclass(frozen=True)
class ClassStress:
    risk_class: RiskClass
    outcome: Outcome  # PASS (a value is available) or ABSTAIN
    value: Decimal | None
    chosen: Chosen
    status: Status
    cited_value: Decimal | None = None
    recomputed_value: Decimal | None = None
    series_start: date | None = None
    series_end: date | None = None
    recovery_years: Decimal | None = None
    citation: str | None = None
    fact_id: str | None = None
    flags: tuple[str, ...] = ()
    abstentions: tuple[Abstention, ...] = ()
    formula_id: str = COMBINATOR_ID


@dataclass(frozen=True)
class DebtShock:
    """Rate-and-spread scenario sizes (PARAMETERs, risk-methodology §7.5)."""

    delta_y: Decimal = field(default_factory=lambda: D("0.02"))
    delta_s_aaa: Decimal = field(default_factory=lambda: D("0.01"))
    delta_s_below_aaa: Decimal = field(default_factory=lambda: D("0.03"))


@dataclass(frozen=True)
class DebtStress:
    outcome: Outcome
    value: Decimal | None
    abstentions: tuple[Abstention, ...] = ()
    flags: tuple[str, ...] = ()
    formula_id: str = DEBT_MTM_ID


def _check_fraction(value: Decimal, what: str) -> None:
    if not (ZERO <= value <= ONE):
        raise InvalidInput(f"{what} must be a fall magnitude in [0, 1], got {value}")


def _longest(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def combine_stress(
    risk_class: RiskClass, cited: CitedStress | None, recomputed: RecomputedDrawdown | None
) -> ClassStress:
    """``s = max(cited, recomputed)``; both values, the series dates and the choice are returned.

    With only one side available the value is used but marked NOT VERIFIED, because the max rule could not be applied.
    With neither side the class abstains (fails closed).  Ties choose the cited row (deterministic).
    """
    if risk_class not in TABLE_CLASSES:
        raise InvalidInput(f"{risk_class} has a fixed stress rule; it is not combined from the table")
    if cited is not None:
        _check_fraction(cited.value, "cited stress")
    if recomputed is not None:
        _check_fraction(recomputed.value, "recomputed drawdown")
        if recomputed.series_end < recomputed.series_start:
            raise InvalidInput("recomputed series ends before it starts")
    if cited is None and recomputed is None:
        return ClassStress(
            risk_class=risk_class,
            outcome=Outcome.ABSTAIN,
            value=None,
            chosen="NONE",
            status=Status.REQUIRES_CONFIGURATION,
            abstentions=(
                Abstention(
                    code="stress_value_missing",
                    missing_input=f"stress value for {risk_class}",
                    how_to_fix="add the cited row to local config or recompute the drawdown from AMFI NAV history",
                ),
            ),
        )
    flags: list[str] = []
    chosen: Chosen
    if cited is not None and recomputed is not None:
        if recomputed.value > cited.value:
            chosen, value, status = "RECOMPUTED", recomputed.value, Status.VERIFIED
        else:
            chosen, value, status = "CITED", cited.value, cited.status
    elif cited is not None:
        chosen, value, status = "CITED", cited.value, Status.NOT_VERIFIED
        flags.append("RECOMPUTED_DRAWDOWN_MISSING")
    else:
        assert recomputed is not None
        chosen, value, status = "RECOMPUTED", recomputed.value, Status.NOT_VERIFIED
        flags.append("CITED_STRESS_MISSING")
    return ClassStress(
        risk_class=risk_class,
        outcome=Outcome.PASS,
        value=value,
        chosen=chosen,
        status=status,
        cited_value=None if cited is None else cited.value,
        recomputed_value=None if recomputed is None else recomputed.value,
        series_start=None if recomputed is None else recomputed.series_start,
        series_end=None if recomputed is None else recomputed.series_end,
        recovery_years=_longest(
            None if cited is None else cited.recovery_years,
            None if recomputed is None else recomputed.recovery_years,
        ),
        citation=None if cited is None else cited.citation,
        fact_id=None if recomputed is None else recomputed.fact_id,
        flags=tuple(flags),
    )


def build_stress_table(
    *,
    cited: Mapping[RiskClass, CitedStress],
    recomputed: Mapping[RiskClass, RecomputedDrawdown],
) -> dict[RiskClass, ClassStress]:
    """Every table class (combined or abstaining) plus the fixed HYBRID, STOCK and CASH_LIKE rows.

    DEBT_MTM is absent on purpose: its stress is per holding (:func:`debt_mtm_stress`).
    """
    table: dict[RiskClass, ClassStress] = {
        rc: combine_stress(rc, cited.get(rc), recomputed.get(rc)) for rc in TABLE_CLASSES
    }
    broad = table[RiskClass.EQ_BROAD]
    table[RiskClass.HYBRID] = ClassStress(
        risk_class=RiskClass.HYBRID,
        outcome=broad.outcome,
        value=broad.value,
        chosen="DERIVED" if broad.value is not None else "NONE",
        status=broad.status,
        cited_value=broad.cited_value,
        recomputed_value=broad.recomputed_value,
        series_start=broad.series_start,
        series_end=broad.series_end,
        recovery_years=broad.recovery_years,
        citation=broad.citation,
        fact_id=broad.fact_id,
        flags=(*broad.flags, "HYBRID_AS_EQ_BROAD"),
        abstentions=broad.abstentions,
    )
    table[RiskClass.STOCK] = ClassStress(
        risk_class=RiskClass.STOCK,
        outcome=Outcome.PASS,
        value=STOCK_STRESS,
        chosen="FIXED",
        status=Status.VERIFIED,
        flags=("STOCK_STRESS_MAXIMAL_PARAMETER",),
    )
    table[RiskClass.CASH_LIKE] = ClassStress(
        risk_class=RiskClass.CASH_LIKE,
        outcome=Outcome.PASS,
        value=CASH_STRESS,
        chosen="FIXED",
        status=Status.VERIFIED,
        flags=("NO_MARK_TO_MARKET",),
    )
    return table


def debt_mtm_stress(
    modified_duration: Decimal | None,
    spread_duration: Decimal | None,
    credit: CreditBucket | None,
    shock: DebtShock | None = None,
) -> DebtStress:
    """``D_mod × Δy + D_spread × Δs``, capped at a total loss of 1.  Missing duration or rating abstains."""
    shock = shock or DebtShock()
    if modified_duration is None or spread_duration is None:
        return DebtStress(
            outcome=Outcome.ABSTAIN,
            value=None,
            abstentions=(
                Abstention(
                    code="duration_missing",
                    missing_input="modified and spread duration",
                    how_to_fix="enter the durations from the scheme's latest factsheet",
                ),
            ),
        )
    if credit is None:
        return DebtStress(
            outcome=Outcome.ABSTAIN,
            value=None,
            abstentions=(
                Abstention(
                    code="credit_rating_missing",
                    missing_input="credit bucket (AAA or below)",
                    how_to_fix="enter the lowest rating held from the scheme's latest factsheet",
                ),
            ),
        )
    if modified_duration < 0 or spread_duration < 0:
        raise InvalidInput("durations must be ≥ 0")
    delta_s = shock.delta_s_aaa if credit is CreditBucket.AAA else shock.delta_s_below_aaa
    flags: tuple[str, ...] = ()
    with engine_context():
        value = modified_duration * shock.delta_y + spread_duration * delta_s
        if value > ONE:
            value = ONE
            flags = ("CAPPED_AT_TOTAL_LOSS",)
    return DebtStress(outcome=Outcome.PASS, value=value, flags=flags)
