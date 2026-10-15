"""Macro inputs for analysis: CPI inflation and the 91-day T-bill risk-free series (pure; dates are passed in).

* CPI (calculation-methodology §2.11; source-registry §2.12). Base-2012 and base-2024 index series are NOT comparable
  without a linking factor, so every computation stays inside ONE base: a year-on-year change is only ever taken
  between two index values of the same base, and a published YoY rate is used only with its own base. Nothing is
  chained or spliced. A month is usable only once it has been released (the 12th of the following month, 16:00 IST;
  at date resolution we require the 13th, which can only delay, never anticipate, a release).
* Inflation over a forward horizon is a LABELLED PROJECTION (§2.11 "a labelled projection for forward views"): the
  latest trailing 12-month CPI inflation is compounded over the horizon, ``π_H = (1 + π_12m)^(days/365) − 1``. It is
  not a forecast.
* Risk-free (risk-methodology §4.1): the 91-day T-bill yield point-in-time for each return date is the cut-off of the
  latest auction held on or before that date (RBI auctions weekly). A date whose latest auction is more than
  ``RISK_FREE_MAX_AGE_DAYS`` old is NOT covered — the series has a hole there and the caller must refuse; nothing is
  interpolated or extended past the last auction.
"""

from __future__ import annotations

import bisect
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise

from iip.engine.errors import InvalidInput, MissingData, StaleData
from iip.engine.money import ONE, engine_context
from iip.engine.stats.metrics import tbill_effective_annual

ENGINE_VERSION = "macro@1.0.0"
CPI_RELEASE_DAY = 12  # MoSPI releases month M on the 12th of M+1 (16:00 IST); usable from the 13th at date resolution
RISK_FREE_MAX_AGE_DAYS = 14  # weekly auctions: more than two auction cycles without a cut-off is a hole in the series
BASE_YEARS = ("2012", "2024")


class CpiFreshness(StrEnum):
    FRESH = "FRESH"  # the latest month that can have been released
    STALE = "STALE"  # one month behind that
    EXPIRED = "EXPIRED"  # two or more months behind — refused


class InflationMethod(StrEnum):
    PUBLISHED_YOY = "published_yoy"  # MoSPI's own YoY inflation for the month, same base
    INDEX_RATIO = "index_ratio_same_base"  # index(M) / index(M − 12) − 1, both from the same base


@dataclass(frozen=True)
class CpiPoint:
    base_year: str
    month: date  # first day of the reference month
    index: Decimal | None
    yoy: Decimal | None  # published YoY inflation as a FRACTION (e.g. 0.0154), or None
    provisional: bool = False


@dataclass(frozen=True)
class InflationBasis:
    """The trailing 12-month CPI inflation chosen for a horizon, with everything needed to explain it."""

    annual: Decimal  # fraction
    base_year: str
    month: date
    method: InflationMethod
    freshness: CpiFreshness
    provisional: bool
    inputs: tuple[tuple[str, str], ...]
    formula_id: str
    caveats: tuple[str, ...]


def _month_add(m: date, k: int) -> date:
    idx = m.year * 12 + (m.month - 1) + k
    return date(idx // 12, idx % 12 + 1, 1)


def _months_between(a: date, b: date) -> int:
    return (b.year * 12 + b.month) - (a.year * 12 + a.month)


def latest_released_month(as_of: date) -> date:
    """The most recent CPI reference month that can have been released by ``as_of``."""
    first = as_of.replace(day=1)
    return _month_add(first, -1 if as_of.day > CPI_RELEASE_DAY else -2)


def cpi_freshness(month: date, as_of: date) -> CpiFreshness:
    """source-registry §4: latest released month = FRESH; one month behind = STALE; two or more = EXPIRED."""
    expected = latest_released_month(as_of)
    lag = _months_between(month.replace(day=1), expected)
    if lag < 0:
        raise InvalidInput(f"CPI month {month:%Y-%m} had not been released by {as_of} (look-ahead)")
    if lag == 0:
        return CpiFreshness.FRESH
    return CpiFreshness.STALE if lag == 1 else CpiFreshness.EXPIRED


def cpi_yoy(index_now: Decimal, index_year_ago: Decimal) -> Decimal:
    """Year-on-year inflation from two index values OF THE SAME BASE: ``I(M) / I(M − 12) − 1``."""
    for name, v in (("index_now", index_now), ("index_year_ago", index_year_ago)):
        if not isinstance(v, Decimal) or not v.is_finite() or v <= 0:
            raise InvalidInput(f"{name} must be a positive finite Decimal")
    with engine_context():
        return index_now / index_year_ago - ONE


def horizon_inflation(annual: Decimal, days: int) -> Decimal:
    """``π_H = (1 + π_annual)^(days/365) − 1`` (projection of a trailing annual rate over the horizon)."""
    if not isinstance(annual, Decimal) or not annual.is_finite() or annual <= -1:
        raise InvalidInput("annual inflation must be a finite Decimal > −1")
    if days < 1:
        raise InvalidInput("days must be ≥ 1")
    with engine_context():
        return (ONE + annual) ** (Decimal(days) / Decimal(365)) - ONE


def _candidate(points: Sequence[CpiPoint], base: str, as_of: date) -> InflationBasis | None:
    """Latest released month of ONE base for which a YoY rate can be established inside that base."""
    usable = latest_released_month(as_of)
    by_month = {p.month: p for p in points if p.base_year == base}
    for month in sorted((m for m in by_month if m <= usable), reverse=True):
        p = by_month[month]
        fresh = cpi_freshness(month, as_of)
        if p.yoy is not None:
            return InflationBasis(
                annual=p.yoy, base_year=base, month=month, method=InflationMethod.PUBLISHED_YOY, freshness=fresh,
                provisional=p.provisional, inputs=(("cpi_month", f"{month:%Y-%m}"), ("base_year", base),
                                                   ("published_yoy", str(p.yoy))),
                formula_id="CPI_YOY_PUBLISHED@1", caveats=("PUBLISHED_YOY_AS_RELEASED",),
            )  # fmt: skip
        prior = by_month.get(_month_add(month, -12))
        if p.index is not None and prior is not None and prior.index is not None:
            annual = cpi_yoy(p.index, prior.index)
            return InflationBasis(
                annual=annual, base_year=base, month=month, method=InflationMethod.INDEX_RATIO, freshness=fresh,
                provisional=p.provisional or prior.provisional,
                inputs=(("cpi_month", f"{month:%Y-%m}"), ("base_year", base), ("index", str(p.index)),
                        (f"index {prior.month:%Y-%m}", str(prior.index))),
                formula_id="CPI_YOY_INDEX_RATIO@1", caveats=("SAME_BASE_ONLY_NO_CHAINING",),
            )  # fmt: skip
    return None


def select_inflation(points: Sequence[CpiPoint], as_of: date) -> InflationBasis:
    """Trailing 12-month CPI inflation as of ``as_of``: the most recent released month for which a YoY rate exists
    within a single base (ties → base 2024, the current base). Expired data is refused (StaleData); no data or no
    same-base pair is refused (MissingData). Bases are never mixed."""
    for p in points:
        if p.base_year not in BASE_YEARS:
            raise InvalidInput(f"unknown CPI base year {p.base_year!r}")
        if p.month.day != 1:
            raise InvalidInput("CPI months must be given as the first day of the month")
    found = [c for c in (_candidate(points, b, as_of) for b in reversed(BASE_YEARS)) if c is not None]
    if not found:
        raise MissingData(
            "no released CPI month with a year-on-year rate inside a single base (enter MoSPI's published YoY "
            "inflation, or index values 12 months apart in the same base; base 2012 and base 2024 are never chained)"
        )
    best = max(found, key=lambda c: (c.month, c.base_year))
    if best.freshness is CpiFreshness.EXPIRED:
        raise StaleData(
            f"latest usable CPI month is {best.month:%Y-%m} (base {best.base_year}); data two or more months behind "
            f"the latest release ({latest_released_month(as_of):%Y-%m}) is not used"
        )
    caveats = list(best.caveats)
    if best.freshness is CpiFreshness.STALE:
        caveats.append("CPI_STALE_ONE_MONTH_BEHIND")
    if best.provisional:
        caveats.append("CPI_PROVISIONAL_SUBJECT_TO_REVISION")
    return replace(best, caveats=tuple(caveats))


# ---------------------------------------------------------------------------------------------- risk-free


@dataclass(frozen=True)
class RiskFreeAlignment:
    """Point-in-time 91-day T-bill yields aligned exactly to a series' return dates (risk-methodology §4.1)."""

    return_dates: tuple[date, ...]
    auction_dates: tuple[date, ...]  # the auction used for each return date
    yields: tuple[Decimal, ...]  # money-market yield as published, fraction
    effective_annual: tuple[Decimal, ...]  # y_eff = (1 + y × 91/365)^(365/91) − 1
    auctions_used: int
    max_age_days: int
    formula_id: str = "RISK_FREE_TBILL91_PIT@1"


def align_risk_free(
    return_dates: Sequence[date], auctions: Mapping[date, Decimal], *, max_age_days: int = RISK_FREE_MAX_AGE_DAYS
) -> RiskFreeAlignment:
    """For each return date the cut-off of the latest auction on or before it, no older than ``max_age_days``.

    Raises ``MissingData`` naming the first uncovered date when any return date is not covered (the caller refuses
    the metric). Nothing is interpolated, and no auction is used after a later one exists.
    """
    if not return_dates:
        raise InvalidInput("no return dates to align")
    if any(b <= a for a, b in pairwise(return_dates)):
        raise InvalidInput("return dates must be strictly increasing")
    for d, y in auctions.items():
        if not isinstance(y, Decimal) or not y.is_finite() or not Decimal(0) < y < ONE:
            raise InvalidInput(f"invalid T-bill yield {y!r} on {d}")
    days = sorted(auctions)
    used: list[date] = []
    uncovered: list[date] = []
    for rd in return_dates:
        i = bisect.bisect_right(days, rd) - 1
        if i < 0 or (rd - days[i]).days > max_age_days:
            uncovered.append(rd)
            continue
        used.append(days[i])
    if uncovered:
        raise MissingData(
            f"the 91-day T-bill series does not cover {len(uncovered)} of {len(return_dates)} return dates (first "
            f"uncovered: {uncovered[0]}; each date needs an auction cut-off within the previous {max_age_days} days)"
        )
    ys = tuple(auctions[d] for d in used)
    eff = {y: tbill_effective_annual(y) for y in set(ys)}
    return RiskFreeAlignment(
        return_dates=tuple(return_dates),
        auction_dates=tuple(used),
        yields=ys,
        effective_annual=tuple(eff[y] for y in ys),
        auctions_used=len(set(used)),
        max_age_days=max_age_days,
    )
