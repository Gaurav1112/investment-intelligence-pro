"""Calendar arithmetic and day-count conventions (calculation-methodology.md §0, §4).

* ACT/365F — returns, XIRR, CAGR, T-bills/money market (RBI FAQ: actual/365).
* 30E/360 — G-sec/SDL accrued interest (RBI FAQ: Excel basis 4; month-end variant secondary-verified).
* ACT/ACT (SEBI 2016) — listed corporate bonds: denominator 366 when 29-Feb falls in the period.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from iip.engine.errors import InvalidInput
from iip.engine.money import engine_context


class DayCount(StrEnum):
    ACT_365F = "ACT/365F"
    THIRTY_E_360 = "30E/360"
    THIRTY_US_360 = "30/360US"  # for contrast tests only; NOT the Indian G-sec convention
    ACT_ACT_SEBI = "ACT/ACT-SEBI"


def is_month_end(d: date) -> bool:
    return d.day == calendar.monthrange(d.year, d.month)[1]


def add_months(d: date, months: int) -> date:
    """Excel EDATE semantics: same day-of-month N months later, clamped to month-end."""
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    if year < 1:
        raise InvalidInput("date underflow")
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last))


def days_between(start: date, end: date) -> int:
    return (end - start).days


def days_30e_360(start: date, end: date) -> int:
    d1 = min(start.day, 30)
    d2 = min(end.day, 30)
    return 360 * (end.year - start.year) + 30 * (end.month - start.month) + (d2 - d1)


def days_30us_360(start: date, end: date) -> int:
    d1, d2 = start.day, end.day
    feb_end_1 = start.month == 2 and is_month_end(start)
    feb_end_2 = end.month == 2 and is_month_end(end)
    if feb_end_1 and feb_end_2:
        d2 = 30
    if feb_end_1:
        d1 = 30
    if d2 == 31 and d1 >= 30:
        d2 = 30
    if d1 == 31:
        d1 = 30
    return 360 * (end.year - start.year) + 30 * (end.month - start.month) + (d2 - d1)


def contains_feb29(start: date, end: date) -> bool:
    """True if 29-Feb lies in (start, end] — the SEBI ACT/ACT 366-day trigger for the period."""
    for year in range(start.year, end.year + 1):
        if calendar.isleap(year):
            feb29 = date(year, 2, 29)
            if start < feb29 <= end:
                return True
    return False


def year_fraction(start: date, end: date, convention: DayCount) -> Decimal:
    if end < start:
        raise InvalidInput(f"end {end} before start {start}")
    with engine_context():
        if convention is DayCount.ACT_365F:
            return Decimal(days_between(start, end)) / Decimal(365)
        if convention is DayCount.THIRTY_E_360:
            return Decimal(days_30e_360(start, end)) / Decimal(360)
        if convention is DayCount.THIRTY_US_360:
            return Decimal(days_30us_360(start, end)) / Decimal(360)
        if convention is DayCount.ACT_ACT_SEBI:
            denom = 366 if contains_feb29(start, end) else 365
            return Decimal(days_between(start, end)) / Decimal(denom)
    raise InvalidInput(f"unknown convention {convention}")  # pragma: no cover


class BusinessCalendar:
    """Business-day calendar built from an injected holiday set (pure — no network, no clock).

    Different markets need different calendars: NSE equity holidays are NOT the RBI/G-sec settlement
    calendar (hidden-gems.md: RTGS-holiday pitfall).  Callers must pass the right set.
    """

    def __init__(self, name: str, holidays: frozenset[date], weekend: frozenset[int] = frozenset({5, 6})):
        self.name = name
        self.holidays = holidays
        self.weekend = weekend

    def is_business_day(self, d: date) -> bool:
        return d.weekday() not in self.weekend and d not in self.holidays

    def add_business_days(self, d: date, n: int) -> date:
        if n < 0:
            raise InvalidInput("n must be ≥ 0")
        cur = d
        added = 0
        while added < n:
            cur += timedelta(days=1)
            if self.is_business_day(cur):
                added += 1
        return cur

    def following(self, d: date) -> date:
        cur = d
        while not self.is_business_day(cur):
            cur += timedelta(days=1)
        return cur
