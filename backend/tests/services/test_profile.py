from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from iip.engine.ranking import Objective
from iip.services.profile import Profile, evaluate

AS_OF = date(2026, 10, 15)

FULL = {
    "amount": "500000",
    "withdrawal_date": "2027-04-15",
    "objective": Objective.CAPITAL_PRESERVATION,
    "loss_acceptable": False,
    "early_need": "possible",
}


def test_empty_profile_is_exploration_with_all_five_missing() -> None:
    st = evaluate(Profile(), AS_OF)
    assert st.mode == "EXPLORATION"
    assert len(st.missing) == 5


def test_complete_profile_is_personalised() -> None:
    st = evaluate(Profile.model_validate(FULL), AS_OF)
    assert st.mode == "PERSONALISED" and st.missing == [] and st.horizon_days == 182


@pytest.mark.parametrize("field", ["amount", "withdrawal_date", "objective", "loss_acceptable", "early_need"])
def test_any_single_missing_critical_input_forces_exploration(field: str) -> None:
    data = {**FULL, field: None}
    assert evaluate(Profile.model_validate(data), AS_OF).mode == "EXPLORATION"


def test_past_withdrawal_date_is_not_personalised() -> None:
    st = evaluate(Profile.model_validate({**FULL, "withdrawal_date": "2026-10-15"}), AS_OF)
    assert st.mode == "EXPLORATION" and st.horizon_days is None


def test_growth_requires_loss_budget() -> None:
    p = Profile.model_validate({**FULL, "objective": Objective.GROWTH, "loss_acceptable": True})
    st = evaluate(p, AS_OF)
    assert st.mode == "EXPLORATION"
    assert any("loss budget" in m for m in st.missing)


def test_growth_with_no_loss_acceptable_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Profile.model_validate({**FULL, "objective": Objective.AGGRESSIVE_GROWTH, "loss_acceptable": False})


def test_aspiration_conflicts_are_flagged_not_silently_accepted() -> None:
    # The user's stated 20–25 % aspiration with a 6-month capital-preservation goal.
    p = Profile.model_validate({**FULL, "return_aspiration": "0.20"})
    st = evaluate(p, AS_OF)
    assert st.mode == "PERSONALISED"  # aspiration never blocks; it is surfaced
    assert len(st.conflicts) == 2 and all(c.startswith("CONSTRAINT_CONFLICT") for c in st.conflicts)


def test_floats_rejected_and_bounds_enforced() -> None:
    with pytest.raises(ValidationError):
        Profile.model_validate({"amount": 500000.5})
    with pytest.raises(ValidationError):
        Profile.model_validate({"amount": "-1"})
    with pytest.raises(ValidationError):
        Profile.model_validate({"credit_floor": "AAAA"})
    with pytest.raises(ValidationError):
        Profile.model_validate({"unexpected": 1})
    assert Profile.model_validate({"amount": "1000000000000"}).amount == Decimal("1000000000000")
