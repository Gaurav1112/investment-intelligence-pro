"""L1 emergency-fund gate (design-risk-first.md §5.1).  All values are FICTIONAL."""

from __future__ import annotations

from datetime import date

import pytest

from iip.engine.deposits import DepositHolding, InstitutionType
from iip.engine.errors import InvalidInput
from iip.engine.money import D
from iip.engine.risk import REMEDY_REDIRECT_NEW_CONTRIBUTIONS, Outcome
from iip.engine.risk.emergency import LiquidityKind, ReserveHolding, emergency_gate

AS_OF = date(2026, 1, 15)


def h(hid: str, kind: LiquidityKind, mv: str, load: str = "0") -> ReserveHolding:
    return ReserveHolding(hid, kind, D(mv), D(load))


def test_shortfall_is_a_breach_with_redirect_remedy() -> None:
    r = emergency_gate(
        months=6,
        essential_monthly_expenses=D("40000"),
        holdings=[h("s", LiquidityKind.SAVINGS, "60000"), h("o", LiquidityKind.OVERNIGHT_MF, "60000")],
    )
    assert r.target_reserve == D("240000")
    assert r.liquid_reserves == D("120000")
    assert r.shortfall == D("120000")
    assert r.outcome is Outcome.BREACH
    assert r.remedy == REMEDY_REDIRECT_NEW_CONTRIBUTIONS
    assert r.rule_id == "risk.emergency_gate@1"


def test_funded_reserve_passes() -> None:
    r = emergency_gate(
        months=3,
        essential_monthly_expenses=D("40000"),
        holdings=[h("f", LiquidityKind.SWEEP_FD, "100000"), h("l", LiquidityKind.LIQUID_MF, "30000", "10")],
    )
    assert r.liquid_reserves == D("129990")  # exit load if redeemed today is deducted
    assert r.shortfall == D("0")
    assert r.outcome is Outcome.PASS
    assert r.remedy is None


def test_lock_ins_and_other_count_as_zero() -> None:
    r = emergency_gate(
        months=3,
        essential_monthly_expenses=D("10000"),
        holdings=[h("elss", LiquidityKind.LOCK_IN, "500000"), h("eq", LiquidityKind.OTHER, "500000")],
    )
    assert r.liquid_reserves == D("0")
    assert r.shortfall == D("30000")
    assert "LOCK_IN_COUNTED_AS_ZERO" in r.flags


@pytest.mark.parametrize(("months", "expenses"), [(None, "10000"), (6, None), (None, None)])
def test_missing_inputs_abstain(months: int | None, expenses: str | None) -> None:
    r = emergency_gate(
        months=months,
        essential_monthly_expenses=None if expenses is None else D(expenses),
        holdings=[h("s", LiquidityKind.SAVINGS, "1000")],
    )
    assert r.outcome is Outcome.ABSTAIN
    assert r.abstentions[0].code == "emergency_inputs_missing"
    assert r.shortfall is None
    assert r.liquid_reserves == D("1000")
    assert "SEBI_ATTRIBUTION_NOT_VERIFIED" in r.flags


def test_dicgc_flags_reuse_deposit_engine() -> None:
    deposits = [
        DepositHolding("bank-a", InstitutionType.BANK, "me", D("480000"), D("30000")),
        DepositHolding("nbfc-b", InstitutionType.NBFC, "me", D("100000"), D("0")),
    ]
    r = emergency_gate(months=1, essential_monthly_expenses=D("1"), holdings=[], deposits=deposits, as_of=AS_OF)
    assert "DEPOSIT_ABOVE_DICGC_LIMIT" in r.flags
    assert "DEPOSIT_NOT_DICGC_INSURED" in r.flags
    with pytest.raises(InvalidInput):
        emergency_gate(months=1, essential_monthly_expenses=D("1"), holdings=[], deposits=deposits)


@pytest.mark.parametrize(
    "bad",
    [
        {"months": 0},
        {"essential_monthly_expenses": D("-1")},
        {"holdings": [h("x", LiquidityKind.SAVINGS, "-1")]},
        {"holdings": [h("x", LiquidityKind.LIQUID_MF, "10", "11")]},
        {"holdings": [h("x", LiquidityKind.SAVINGS, "10", "1")]},
    ],
)
def test_invalid_inputs_rejected(bad: dict[str, object]) -> None:
    kw: dict[str, object] = {"months": 3, "essential_monthly_expenses": D("1"), "holdings": []}
    kw.update(bad)
    with pytest.raises(InvalidInput):
        emergency_gate(**kw)  # type: ignore[arg-type]
