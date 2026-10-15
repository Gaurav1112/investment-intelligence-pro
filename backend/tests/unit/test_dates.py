from datetime import date
from decimal import Decimal

import pytest

from iip.engine.dates import (
    BusinessCalendar,
    DayCount,
    add_months,
    contains_feb29,
    days_30e_360,
    days_30us_360,
    year_fraction,
)
from iip.engine.errors import InvalidInput
from iip.engine.money import engine_context


def _div(a: int, b: int) -> Decimal:
    with engine_context():
        return Decimal(a) / Decimal(b)


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),
        (date(2024, 1, 31), 1, date(2024, 2, 29)),
        (date(2026, 10, 15), 3, date(2027, 1, 15)),
        (date(2026, 8, 31), 6, date(2027, 2, 28)),
        (date(2026, 3, 31), -1, date(2026, 2, 28)),
        (date(2026, 10, 15), 12, date(2027, 10, 15)),
    ],
)
def test_edate(start: date, months: int, expected: date) -> None:
    assert add_months(start, months) == expected


def test_rbi_faq_accrued_example_days() -> None:
    # RBI FAQ worked example: 25-Nov → 30-Jan = 65 days under 30/360 (both variants).
    assert days_30e_360(date(2025, 11, 25), date(2026, 1, 30)) == 65
    assert days_30us_360(date(2025, 11, 25), date(2026, 1, 30)) == 65


def test_30e_vs_us_differ_at_month_end() -> None:
    # 30E: day 31 → 30 unconditionally. Feb end handling differs between variants.
    assert days_30e_360(date(2026, 1, 30), date(2026, 3, 31)) == 60
    assert days_30us_360(date(2026, 2, 28), date(2026, 3, 31)) == 30
    assert days_30e_360(date(2026, 2, 28), date(2026, 3, 31)) == 32


def test_act_act_sebi_leap() -> None:
    # calculation-methodology §4.5: Jan 1 → Jul 1 2016 = 182 days over 366.
    assert year_fraction(date(2016, 1, 1), date(2016, 7, 1), DayCount.ACT_ACT_SEBI) == _div(182, 366)
    assert year_fraction(date(2016, 7, 1), date(2017, 1, 1), DayCount.ACT_ACT_SEBI) == _div(184, 365)


def test_contains_feb29_boundaries() -> None:
    assert contains_feb29(date(2024, 2, 28), date(2024, 2, 29))
    assert not contains_feb29(date(2024, 2, 29), date(2024, 12, 31))  # (start, end]
    assert not contains_feb29(date(2025, 1, 1), date(2026, 1, 1))


def test_act365_leap_year_is_fixed_365() -> None:
    assert year_fraction(date(2024, 1, 1), date(2025, 1, 1), DayCount.ACT_365F) == _div(366, 365)


def test_negative_period_rejected() -> None:
    with pytest.raises(InvalidInput):
        year_fraction(date(2026, 1, 2), date(2026, 1, 1), DayCount.ACT_365F)


def test_business_calendar_uses_injected_holidays_only() -> None:
    cal = BusinessCalendar("TEST", frozenset({date(2026, 10, 20)}))
    assert cal.add_business_days(date(2026, 10, 16), 1) == date(2026, 10, 19)  # Fri → Mon
    assert cal.add_business_days(date(2026, 10, 19), 1) == date(2026, 10, 21)  # skips the holiday
    assert cal.following(date(2026, 10, 17)) == date(2026, 10, 19)
