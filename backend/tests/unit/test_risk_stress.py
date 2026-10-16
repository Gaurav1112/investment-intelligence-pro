"""Stress combinator (design-risk-first.md §5.2, design-judgement.md §2.1 item 4; PLAN A12).

All values here are FICTIONAL fixtures. None is a real index or AMFI statistic.
"""

from __future__ import annotations

from datetime import date

import pytest

from iip.engine.errors import InvalidInput
from iip.engine.money import D
from iip.engine.risk import Outcome, RiskClass, Status
from iip.engine.risk.stress import (
    STOCK_STRESS,
    CitedStress,
    CreditBucket,
    DebtShock,
    RecomputedDrawdown,
    build_stress_table,
    combine_stress,
    debt_mtm_stress,
)

START = date(2001, 1, 31)  # fictional series start
END = date(2020, 12, 31)


def cited(value: str, recovery: str | None = None, status: Status = Status.VERIFIED) -> CitedStress:
    return CitedStress(
        value=D(value),
        citation="fictional-citation#row",
        status=status,
        recovery_years=None if recovery is None else D(recovery),
    )


def recomputed(value: str, recovery: str | None = None) -> RecomputedDrawdown:
    return RecomputedDrawdown(
        value=D(value),
        series_start=START,
        series_end=END,
        fact_id="fact:fictional-series",
        recovery_years=None if recovery is None else D(recovery),
    )


def test_max_of_cited_and_recomputed_returns_both_and_series_start() -> None:
    r = combine_stress(RiskClass.EQ_BROAD, cited("0.40", "3"), recomputed("0.45", "2"))
    assert r.outcome is Outcome.PASS
    assert r.value == D("0.45")
    assert r.chosen == "RECOMPUTED"
    assert r.cited_value == D("0.40")
    assert r.recomputed_value == D("0.45")
    assert r.series_start == START
    assert r.series_end == END
    assert r.recovery_years == D("3")  # the longer recovery is kept (conservative)
    assert r.formula_id == "risk.stress_combinator@1"


def test_cited_wins_when_larger() -> None:
    r = combine_stress(RiskClass.EQ_MID, cited("0.50"), recomputed("0.35"))
    assert r.value == D("0.50")
    assert r.chosen == "CITED"
    assert r.status is Status.VERIFIED
    assert r.series_start == START  # the series start is reported even when the cited value wins


def test_tie_prefers_cited_deterministically() -> None:
    r = combine_stress(RiskClass.EQ_MID, cited("0.50"), recomputed("0.50"))
    assert r.chosen == "CITED"


def test_recomputed_is_verified_as_computed_even_if_cited_is_not() -> None:
    r = combine_stress(RiskClass.GOLD, cited("0.20", status=Status.NOT_VERIFIED), recomputed("0.25"))
    assert r.value == D("0.25")
    assert r.status is Status.VERIFIED


def test_cited_only_is_used_but_not_verified() -> None:
    r = combine_stress(RiskClass.EQ_LARGE, cited("0.40"), None)
    assert r.outcome is Outcome.PASS
    assert r.value == D("0.40")
    assert r.status is Status.NOT_VERIFIED
    assert "RECOMPUTED_DRAWDOWN_MISSING" in r.flags
    assert r.series_start is None


def test_recomputed_only_is_used_but_not_verified() -> None:
    r = combine_stress(RiskClass.EQ_LARGE, None, recomputed("0.30"))
    assert r.value == D("0.30")
    assert r.status is Status.NOT_VERIFIED
    assert "CITED_STRESS_MISSING" in r.flags


def test_neither_value_abstains() -> None:
    r = combine_stress(RiskClass.EQ_SMALL, None, None)
    assert r.outcome is Outcome.ABSTAIN
    assert r.value is None
    assert r.status is Status.REQUIRES_CONFIGURATION
    assert r.abstentions[0].code == "stress_value_missing"


@pytest.mark.parametrize("bad", ["-0.1", "1.01"])
def test_out_of_range_stress_rejected(bad: str) -> None:
    with pytest.raises(InvalidInput):
        combine_stress(RiskClass.EQ_BROAD, cited(bad), None)
    with pytest.raises(InvalidInput):
        combine_stress(RiskClass.EQ_BROAD, None, recomputed(bad))


def test_series_end_before_start_rejected() -> None:
    bad = RecomputedDrawdown(value=D("0.3"), series_start=END, series_end=START, fact_id="f")
    with pytest.raises(InvalidInput):
        combine_stress(RiskClass.EQ_BROAD, None, bad)


def test_fixed_classes_are_not_combined() -> None:
    for rc in (RiskClass.HYBRID, RiskClass.STOCK, RiskClass.CASH_LIKE, RiskClass.DEBT_MTM):
        with pytest.raises(InvalidInput):
            combine_stress(rc, cited("0.3"), None)


def test_build_table_derives_fixed_rows() -> None:
    table = build_stress_table(
        cited={RiskClass.EQ_BROAD: cited("0.40", "5"), RiskClass.GOLD: cited("0.20")},
        recomputed={RiskClass.EQ_BROAD: recomputed("0.44")},
    )
    hybrid = table[RiskClass.HYBRID]
    assert hybrid.value == D("0.44")  # hybrids are 100 % EQ_BROAD
    assert hybrid.chosen == "DERIVED"
    assert "HYBRID_AS_EQ_BROAD" in hybrid.flags
    assert table[RiskClass.CASH_LIKE].value == D(0)
    assert table[RiskClass.STOCK].value == STOCK_STRESS == D("1.00")
    assert RiskClass.DEBT_MTM not in table  # debt is per holding, from the duration formula
    assert table[RiskClass.EQ_SMALL].outcome is Outcome.ABSTAIN  # every table class appears, missing ones abstain


def test_hybrid_abstains_when_broad_equity_missing() -> None:
    table = build_stress_table(cited={}, recomputed={})
    assert table[RiskClass.HYBRID].outcome is Outcome.ABSTAIN


def test_debt_mtm_formula_matches_design_fixture() -> None:
    # design §5.3: D_mod 1.0, AAA → 1.0 × 0.02 + 1.0 × 0.01 = 0.03
    r = debt_mtm_stress(D("1.0"), D("1.0"), CreditBucket.AAA)
    assert r.value == D("0.03")
    assert r.formula_id == "risk.debt_mtm_stress@1"
    below = debt_mtm_stress(D("1.0"), D("1.0"), CreditBucket.BELOW_AAA)
    assert below.value == D("0.05")
    custom = debt_mtm_stress(D("2"), D("0"), CreditBucket.AAA, DebtShock(delta_y=D("0.01")))
    assert custom.value == D("0.02")


def test_debt_mtm_abstains_on_missing_duration_or_rating() -> None:
    assert debt_mtm_stress(None, D("1"), CreditBucket.AAA).outcome is Outcome.ABSTAIN
    assert debt_mtm_stress(None, D("1"), CreditBucket.AAA).abstentions[0].code == "duration_missing"
    assert debt_mtm_stress(D("1"), None, CreditBucket.AAA).abstentions[0].code == "duration_missing"
    assert debt_mtm_stress(D("1"), D("1"), None).abstentions[0].code == "credit_rating_missing"


def test_debt_mtm_capped_at_total_loss_and_rejects_negative() -> None:
    assert debt_mtm_stress(D("40"), D("40"), CreditBucket.BELOW_AAA).value == D(1)
    with pytest.raises(InvalidInput):
        debt_mtm_stress(D("-1"), D("1"), CreditBucket.AAA)
