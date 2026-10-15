"""Freshness rules shared by eligibility (engine) and badges (services). Pure: the analysis date is passed in."""

from __future__ import annotations

from datetime import date, timedelta

# source-registry.md §4: an AMFI NAV is expired when > 3 business days OR > 5 calendar days old.
NAV_MAX_BUSINESS_DAYS = 3
NAV_MAX_CALENDAR_DAYS = 5


def weekdays_between(start: date, end: date) -> int:
    """Weekdays in (start, end]. No holiday calendar is loaded (known limitation): holidays count as business days,
    which can only make data look OLDER, never fresher."""
    if end <= start:
        return 0
    n, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def nav_is_stale(observation_date: date, as_of: date) -> bool:
    return (
        observation_date > as_of
        or weekdays_between(observation_date, as_of) > NAV_MAX_BUSINESS_DAYS
        or (as_of - observation_date).days > NAV_MAX_CALENDAR_DAYS
    )
