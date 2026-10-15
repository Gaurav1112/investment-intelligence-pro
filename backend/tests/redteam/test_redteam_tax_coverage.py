"""Red team RT-17: the tax-coverage assumption must not shorten the holding period.

Transfers after the rule table's coverage end are priced under the law in force on the coverage end (assumed
unchanged), but the holding period is classified from the ACTUAL dates. Every value is a hand-computed TEST input.
"""

import dataclasses
import itertools
from datetime import date
from decimal import Decimal

import pytest

from iip.engine import candidates as cb
from iip.engine import tax as tx
from iip.engine.errors import InvalidInput, RuleNotFound
from iip.engine.money import D
from iip.rules.loader import load_tax_rules

RULES = load_tax_rules()
COVERAGE = RULES.coverage_to  # 2027-03-31
FLAG = f"TAX_RULES_ASSUMED_UNCHANGED_AFTER_{COVERAGE.isoformat()}"
PROFILE_30 = tx.TaxProfile(
    regime=tx.Regime.NEW, residential_status=tx.ResidentialStatus.RESIDENT, slab_rate=D("0.30"), surcharge_rate=D("0")
)
# "Actual dates under unchanged law": the same rule rows (all ITA2025 rows are open-ended) with coverage extended.
UNCHANGED_LAW = dataclasses.replace(RULES, coverage_to=date(2035, 3, 31))


def _tax(
    cls: str, acquired: date, transferred: date, gain: str, **kw: object
) -> tuple[Decimal, tx.TaxReport, str | None]:
    return cb._tax_on_gain(
        D(gain), lot_id="L", instrument_class=cls, acquired=acquired, transferred=transferred,
        ruleset=RULES, profile=PROFILE_30, **kw,  # type: ignore[arg-type]
    )  # fmt: skip


def test_rt17_equity_held_400_days_past_coverage_is_ltcg_at_12_5_percent() -> None:
    """The red-team probe: bought 15-Oct-2026, sold 19-Nov-2027 (400 days), ₹2,00,000 gain.

    Hand check: LTCG 12.5 % on (2,00,000 − 1,25,000 exemption) = 9,375; + 4 % cess = ₹9,750.
    The old clamp moved the sale to 31-Mar-2027 (167 days → STCG 20 %): 40,000 + cess = ₹41,600.
    """
    acquired, sold = date(2026, 10, 15), date(2027, 11, 19)
    assert (sold - acquired).days == 400
    total, report, flag = _tax("LISTED_EQUITY_SHARE", acquired, sold, "200000", listed=True)
    assert report.classifications[0].gain_type is tx.GainType.LTCG
    assert report.classifications[0].base_rate == D("0.125")
    assert report.classifications[0].exemption_applied_inr == D("125000")
    assert total == D("9750.00")
    assert flag == FLAG
    assert tx.W_RATES_ASSUMED_UNCHANGED in report.warnings


def test_rt17_equity_mf_candidate_past_coverage_gets_ltcg_and_exemption_flag() -> None:
    """End to end through mf_candidate with the SHIPPED table: RT-18's flag can now trigger (it needed a fake table)."""
    from tests.unit.test_candidates import FULL_SPAN, _liquid, _series

    ds, ns = _series(date(2012, 1, 2), FULL_SPAN, "0.0006")
    b = _liquid(category="Equity Scheme - Large Cap Fund", nav_dates=ds, navs=ns, amount=D("2000000"),
                withdrawal=date(2027, 11, 19), exit_load=cb.ExitLoadSpec(365, D("0.01"), "SID FIXTURE"))  # fmt: skip
    assert not b.ineligible_reasons, b.ineligible_reasons
    assert "LTCG_EXEMPTION_ASSUMED_UNUSED" in b.candidate.flags
    assert FLAG in b.candidate.flags
    assert b.evidence is not None and any("LTCG" in r for r in b.evidence.tax_rule_ids)


def test_rt17_debt_mf_bought_after_2023_is_slab_regardless_of_holding() -> None:
    """Specified debt MF acquired on/after 1-Apr-2023 is slab income however long it is held — the fix must not turn
    a long holding into a 12.5 % LTCG. 3 years past coverage: 30 % slab + 4 % cess on ₹1,00,000 = ₹31,200."""
    total, report, flag = _tax("MUTUAL_FUND", date(2026, 10, 15), date(2030, 1, 15), "100000",
                               equity_share=D("0"), debt_share=D("1"))  # fmt: skip
    assert report.classifications[0].rule_id == "MF-DEBT-SMF/ITA2025"
    assert report.classifications[0].rate_kind is tx.RateKind.SLAB
    assert total == D("31200.00")
    assert flag == FLAG


def test_rt17_pre_2023_debt_mf_keeps_its_acquisition_date() -> None:
    """A debt MF bought 1-Mar-2023 (before the 1-Apr-2023 cut) and sold after coverage: actual acquisition date is
    used for the condition (pre-2023 regime) and for the 24-month test (LTCG 12.5 %, no exemption): ₹13,000."""
    total, report, _ = _tax("MUTUAL_FUND", date(2023, 3, 1), date(2027, 6, 1), "100000",
                            equity_share=D("0"), debt_share=D("1"))  # fmt: skip
    assert report.classifications[0].rule_id == "MF-DEBT-PRE2023-LT/ITA2025"
    assert total == D("13000.00")


def test_rt17_grandfathered_equity_still_abstains() -> None:
    with pytest.raises(RuleNotFound):
        _tax("LISTED_EQUITY_SHARE", date(2018, 1, 15), date(2027, 6, 1), "100000", listed=True)


def test_rt17_rates_as_of_validation() -> None:
    d = tx.Disposal(lot_id="L", instrument_class="LISTED_EQUITY_SHARE", transfer_date=date(2026, 6, 1),
                    gain_inr=D("1000"), acquisition_date=date(2025, 1, 1), listed=True)  # fmt: skip
    with pytest.raises(InvalidInput):  # rates from after the transfer would apply law the transfer never saw
        tx.compute_tax([d], RULES, PROFILE_30, rates_as_of=date(2026, 7, 1))
    late = dataclasses.replace(d, transfer_date=date(2028, 6, 1))
    with pytest.raises(RuleNotFound):  # rates beyond coverage are still never invented
        tx.compute_tax([late], RULES, PROFILE_30, rates_as_of=date(2028, 1, 1))


CASES = [
    ("LISTED_EQUITY_SHARE", {"listed": True}),
    ("MUTUAL_FUND", {"equity_share": D("0.65"), "debt_share": D("0")}),
    ("MUTUAL_FUND", {"equity_share": D("0"), "debt_share": D("1")}),
    ("TBILL", {}),
    ("INTEREST", {}),
]
ACQUIRED = [date(2018, 2, 1), date(2023, 3, 31), date(2023, 4, 1), date(2024, 7, 23), date(2026, 3, 31),
            date(2026, 10, 15), date(2027, 3, 31)]  # fmt: skip
TRANSFERRED_AFTER = [date(2027, 4, 1), date(2027, 10, 15), date(2027, 10, 16), date(2028, 3, 31), date(2029, 4, 1)]


@pytest.mark.parametrize(("cls", "facts"), CASES)
def test_rt17_after_coverage_equals_actual_dates_under_unchanged_law(cls: str, facts: dict[str, object]) -> None:
    """Never understates (or overstates) tax relative to the stated assumption: for every class, acquisition date
    (incl. the 1-Apr-2023, 23-Jul-2024 and grandfathering boundaries) and post-coverage transfer, the result equals
    the engine applied to the actual dates with the same law simply extended in time."""
    checked = 0
    for acquired, sold in itertools.product(ACQUIRED, TRANSFERRED_AFTER):
        for gain in ("100000", "300000"):
            got, rep, flag = _tax(cls, acquired, sold, gain, **facts)
            d = tx.Disposal(lot_id="L", instrument_class=cls, transfer_date=sold, gain_inr=D(gain),
                            acquisition_date=acquired, listed=facts.get("listed"),  # type: ignore[arg-type]
                            domestic_equity_share=facts.get("equity_share"),  # type: ignore[arg-type]
                            debt_share=facts.get("debt_share"))  # type: ignore[arg-type]  # fmt: skip
            want = tx.compute_tax([d], UNCHANGED_LAW, PROFILE_30)
            assert got == want.scenarios[0].total_tax_inr, (cls, acquired, sold, gain)
            assert rep.classifications[0].rule_id == want.classifications[0].rule_id
            assert flag == FLAG
            checked += 1
    assert checked == len(ACQUIRED) * len(TRANSFERRED_AFTER) * 2


@pytest.mark.parametrize(("cls", "facts"), CASES)
def test_rt17_parity_within_coverage_nothing_changes(cls: str, facts: dict[str, object]) -> None:
    """Within coverage there is no flag and the result is exactly the plain engine's (no rates_as_of)."""
    for acquired, sold in [(date(2024, 7, 23), date(2026, 4, 1)), (date(2025, 4, 1), date(2026, 4, 2)),
                           (date(2026, 1, 1), date(2027, 3, 31)), (date(2023, 4, 1), date(2025, 6, 30))]:  # fmt: skip
        got, rep, flag = _tax(cls, acquired, sold, "250000", **facts)
        d = tx.Disposal(lot_id="L", instrument_class=cls, transfer_date=sold, gain_inr=D("250000"),
                        acquisition_date=acquired, listed=facts.get("listed"),  # type: ignore[arg-type]
                        domestic_equity_share=facts.get("equity_share"),  # type: ignore[arg-type]
                        debt_share=facts.get("debt_share"))  # type: ignore[arg-type]  # fmt: skip
        plain = tx.compute_tax([d], RULES, PROFILE_30)
        assert flag is None
        assert rep == plain and got == plain.scenarios[0].total_tax_inr
        assert tx.compute_tax([d], RULES, PROFILE_30, rates_as_of=sold).scenarios == plain.scenarios
