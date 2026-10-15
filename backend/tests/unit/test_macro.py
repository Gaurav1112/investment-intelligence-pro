"""engine.macro: CPI selection (bases never mixed, release lag, freshness) and point-in-time risk-free alignment.

Index values below are hand-made test numbers (not market data); the expected results are computed by hand.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from iip.engine import macro
from iip.engine.errors import InvalidInput, MissingData, StaleData
from iip.engine.macro import CpiFreshness, CpiPoint, InflationMethod
from iip.engine.money import D, engine_context
from iip.engine.stats.metrics import tbill_effective_annual

AS_OF = date(2026, 10, 15)  # after the 12th → latest released month is Sep-2026


def _p(base: str, y: int, m: int, index: str | None = None, yoy: str | None = None, prov: bool = False) -> CpiPoint:
    return CpiPoint(base, date(y, m, 1), None if index is None else D(index), None if yoy is None else D(yoy), prov)


# ----------------------------------------------------------------------------------------- release lag & freshness


@pytest.mark.parametrize(
    ("as_of", "expected"),
    [
        (date(2026, 10, 15), date(2026, 9, 1)),
        (date(2026, 10, 12), date(2026, 8, 1)),
        (date(2026, 1, 5), date(2025, 11, 1)),
    ],
)
def test_latest_released_month_respects_the_12th(as_of: date, expected: date) -> None:
    assert macro.latest_released_month(as_of) == expected


def test_cpi_freshness_bands_and_look_ahead() -> None:
    assert macro.cpi_freshness(date(2026, 9, 1), AS_OF) is CpiFreshness.FRESH
    assert macro.cpi_freshness(date(2026, 8, 1), AS_OF) is CpiFreshness.STALE
    assert macro.cpi_freshness(date(2026, 7, 1), AS_OF) is CpiFreshness.EXPIRED
    with pytest.raises(InvalidInput):
        macro.cpi_freshness(date(2026, 10, 1), AS_OF)  # October is released on 12-Nov


# ----------------------------------------------------------------------------------------- YoY


def test_cpi_yoy_hand_computed() -> None:
    assert macro.cpi_yoy(D("105.5"), D("100")) == D("0.055")
    with pytest.raises(InvalidInput):
        macro.cpi_yoy(D("0"), D("100"))


def test_published_yoy_is_used_with_its_own_base() -> None:
    b = macro.select_inflation([_p("2024", 2026, 9, "104.2", "0.0154")], AS_OF)
    assert (b.annual, b.base_year, b.month, b.method) == (D("0.0154"), "2024", date(2026, 9, 1),
                                                          InflationMethod.PUBLISHED_YOY)  # fmt: skip
    assert b.freshness is CpiFreshness.FRESH and b.formula_id == "CPI_YOY_PUBLISHED@1"


def test_index_ratio_only_within_the_same_base() -> None:
    pts = [_p("2024", 2025, 9, "100.0"), _p("2024", 2026, 9, "102.0")]
    b = macro.select_inflation(pts, AS_OF)
    assert b.method is InflationMethod.INDEX_RATIO and b.annual == D("0.02") and b.base_year == "2024"


def test_base_2012_and_base_2024_are_never_chained() -> None:
    """Sep-2025 exists only in base 2012 and Sep-2026 only in base 2024: no YoY can be formed → refused."""
    pts = [_p("2012", 2025, 9, "195.0"), _p("2024", 2026, 9, "102.0")]
    with pytest.raises(MissingData, match="never chained"):
        macro.select_inflation(pts, AS_OF)


def test_old_base_is_refused_when_expired_rather_than_silently_used() -> None:
    """Base 2012 has a full YoY for Dec-2025, but that is far behind the latest release (Sep-2026) → StaleData."""
    pts = [_p("2012", 2024, 12, "190.0"), _p("2012", 2025, 12, "195.0")]
    with pytest.raises(StaleData):
        macro.select_inflation(pts, AS_OF)


def test_most_recent_month_wins_and_ties_prefer_the_current_base() -> None:
    pts = [_p("2012", 2026, 9, yoy="0.03"), _p("2024", 2026, 9, yoy="0.02"), _p("2024", 2026, 8, yoy="0.01")]
    assert macro.select_inflation(pts, AS_OF).base_year == "2024"
    pts = [_p("2012", 2026, 9, yoy="0.03"), _p("2024", 2026, 8, yoy="0.01")]
    b = macro.select_inflation(pts, AS_OF)
    assert b.base_year == "2012" and b.annual == D("0.03")


def test_unreleased_month_is_never_used() -> None:
    pts = [_p("2024", 2026, 10, yoy="0.09"), _p("2024", 2026, 9, yoy="0.02")]
    assert macro.select_inflation(pts, AS_OF).annual == D("0.02")


def test_stale_and_provisional_are_flagged() -> None:
    b = macro.select_inflation([_p("2024", 2026, 8, yoy="0.02", prov=True)], AS_OF)
    assert b.freshness is CpiFreshness.STALE
    assert "CPI_STALE_ONE_MONTH_BEHIND" in b.caveats and "CPI_PROVISIONAL_SUBJECT_TO_REVISION" in b.caveats


def test_horizon_inflation() -> None:
    assert macro.horizon_inflation(D("0.05"), 365) == D("0.05")
    with engine_context():
        expected = D("1.05") ** (D(182) / D(365)) - 1
    assert macro.horizon_inflation(D("0.05"), 182) == expected
    with pytest.raises(InvalidInput):
        macro.horizon_inflation(D("-1"), 30)


# ----------------------------------------------------------------------------------------- risk-free alignment


def test_each_return_date_uses_the_latest_auction_on_or_before_it() -> None:
    auctions = {date(2026, 1, 7): D("0.0560"), date(2026, 1, 14): D("0.0570")}
    rd = [date(2026, 1, 8), date(2026, 1, 13), date(2026, 1, 14), date(2026, 1, 20)]
    al = macro.align_risk_free(rd, auctions)
    assert al.auction_dates == (date(2026, 1, 7), date(2026, 1, 7), date(2026, 1, 14), date(2026, 1, 14))
    assert al.yields == (D("0.0560"), D("0.0560"), D("0.0570"), D("0.0570"))
    assert al.effective_annual[0] == tbill_effective_annual(D("0.0560")) and al.auctions_used == 2


def test_no_auction_from_after_the_return_date_is_used() -> None:
    with pytest.raises(MissingData, match="first uncovered: 2026-01-06"):
        macro.align_risk_free([date(2026, 1, 6)], {date(2026, 1, 7): D("0.056")})


def test_a_hole_longer_than_two_auction_cycles_is_refused() -> None:
    auctions = {date(2026, 1, 7): D("0.056")}
    ok = macro.align_risk_free([date(2026, 1, 7) + timedelta(days=14)], auctions)
    assert ok.auctions_used == 1
    with pytest.raises(MissingData, match="1 of 1"):
        macro.align_risk_free([date(2026, 1, 7) + timedelta(days=15)], auctions)


def test_alignment_validates_inputs() -> None:
    with pytest.raises(InvalidInput):
        macro.align_risk_free([], {date(2026, 1, 7): D("0.056")})
    with pytest.raises(InvalidInput):
        macro.align_risk_free([date(2026, 1, 8)], {date(2026, 1, 7): Decimal("0")})
    with pytest.raises(InvalidInput):
        macro.align_risk_free([date(2026, 1, 9), date(2026, 1, 8)], {date(2026, 1, 7): D("0.056")})
