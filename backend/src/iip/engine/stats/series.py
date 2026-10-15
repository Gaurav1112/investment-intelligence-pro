"""Validated price/NAV series and return construction (risk-methodology.md §1).

Statistics boundary (calculation-methodology §1.3): prices are held as ``Decimal`` and converted to float64
once, on demand, for return computation.  Nothing is ever forward-filled: gaps are detected and flagged,
and a series with too many suspect gaps is marked ineligible for risk statistics.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from statistics import median
from typing import Literal

import numpy as np
import numpy.typing as npt

from iip.engine.dates import add_months
from iip.engine.errors import InsufficientHistory, InvalidInput
from iip.engine.money import D, engine_context

FloatArray = npt.NDArray[np.float64]


class Frequency(StrEnum):
    DAILY_BUSINESS = "daily-business"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


# §1: "a gap of more than 7 calendar days … makes the observation suspect".  The spec defines this for
# business-day series only; the weekly/monthly thresholds are this module's conservative choice (one
# missing period) and are overridable by the caller.
DEFAULT_MAX_GAP_DAYS: dict[Frequency, int] = {
    Frequency.DAILY_BUSINESS: 7,
    Frequency.WEEKLY: 14,
    Frequency.MONTHLY: 45,
}
# §1: "If gaps exceed 2 % of observations, the series is rejected for risk stats."
MAX_SUSPECT_FRACTION = Decimal("0.02")

# §1.1: fallback A when the span is under one year.  248 is the spec's daily value; 52/12 are the
# nominal weekly/monthly counts (the spec states no fallback for those frequencies).
FALLBACK_ANNUALISATION: dict[Frequency, int] = {
    Frequency.DAILY_BUSINESS: 248,
    Frequency.WEEKLY: 52,
    Frequency.MONTHLY: 12,
}

# Median spacing (calendar days) that is consistent with each declared frequency.  A series whose
# spacing falls outside its band has been mislabelled (e.g. monthly data declared daily) → InvalidInput.
_SPACING_BANDS: dict[Frequency, tuple[int, int]] = {
    Frequency.DAILY_BUSINESS: (1, 4),
    Frequency.WEEKLY: (5, 9),
    Frequency.MONTHLY: (26, 35),
}

DAYS_PER_YEAR = 365.25  # §1.1 annualisation estimate


@dataclass(frozen=True)
class Gap:
    """A suspect interval between two consecutive observations (never filled)."""

    start: date
    end: date
    calendar_days: int
    effective_days: int  # calendar days minus known (weekday) holidays strictly inside the interval


@dataclass(frozen=True)
class Annualisation:
    factor: int
    source: Literal["estimated", "fallback", "override"]


def _years_covered(start: date, end: date, years: int) -> bool:
    return years <= 0 or add_months(start, 12 * years) <= end


@dataclass(frozen=True)
class ReturnSeries:
    """Dated price/NAV observations with a declared frequency.

    Invariants (enforced in ``__post_init__``): at least two observations; ``date`` (not ``datetime``)
    keys; strictly increasing dates with no duplicates; strictly positive finite Decimal prices; spacing
    consistent with ``frequency``.
    """

    dates: tuple[date, ...]
    prices: tuple[Decimal, ...]
    frequency: Frequency
    max_gap_days: int
    holidays: frozenset[date] = frozenset()
    gaps: tuple[Gap, ...] = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.frequency, Frequency):
            raise InvalidInput(f"unknown frequency {self.frequency!r}")
        if len(self.dates) != len(self.prices):
            raise InvalidInput("dates and prices differ in length")
        if len(self.dates) < 2:
            raise InsufficientHistory(f"a return series needs ≥ 2 observations, got {len(self.dates)}")
        if self.max_gap_days < 1:
            raise InvalidInput("max_gap_days must be ≥ 1")
        for d in self.dates:
            if isinstance(d, datetime) or not isinstance(d, date):
                raise InvalidInput(f"observation keys must be datetime.date, got {type(d).__name__}")
        for p in self.prices:
            if not isinstance(p, Decimal) or not p.is_finite():
                raise InvalidInput(f"prices must be finite Decimal, got {p!r}")
            if p <= 0:
                raise InvalidInput(f"prices must be positive, got {p}")
        for prev, cur in zip(self.dates, self.dates[1:], strict=False):
            if cur == prev:
                raise InvalidInput(f"duplicate observation date {cur}")
            if cur < prev:
                raise InvalidInput(f"dates must be strictly increasing: {prev} then {cur}")
        spacing = [(b - a).days for a, b in zip(self.dates, self.dates[1:], strict=False)]
        lo, hi = _SPACING_BANDS[self.frequency]
        med = median(spacing)
        if not lo <= med <= hi:
            raise InvalidInput(
                f"declared frequency {self.frequency.value} inconsistent with median spacing of {med} days"
            )
        gaps: list[Gap] = []
        for a, b in zip(self.dates, self.dates[1:], strict=False):
            cal = (b - a).days
            excused = sum(
                1 for h in self.holidays if a < h < b and h.weekday() < 5
            )  # weekends already count as calendar days in the 7-day rule
            eff = cal - excused
            if eff > self.max_gap_days:
                gaps.append(Gap(start=a, end=b, calendar_days=cal, effective_days=eff))
        object.__setattr__(self, "gaps", tuple(gaps))

    @classmethod
    def from_observations(
        cls,
        observations: Iterable[tuple[date, Decimal | str | int]],
        frequency: Frequency,
        *,
        max_gap_days: int | None = None,
        holidays: frozenset[date] = frozenset(),
    ) -> ReturnSeries:
        """Build from ``(date, price)`` pairs in the given order.  The input is never sorted or deduplicated."""
        obs = list(observations)
        dates = tuple(d for d, _ in obs)
        prices = tuple(D(p) for _, p in obs)
        return cls(
            dates=dates,
            prices=prices,
            frequency=frequency,
            max_gap_days=DEFAULT_MAX_GAP_DAYS[frequency] if max_gap_days is None else max_gap_days,
            holidays=holidays,
        )

    # ------------------------------------------------------------------ descriptors
    @property
    def n_observations(self) -> int:
        return len(self.dates)

    @property
    def n_returns(self) -> int:
        return len(self.dates) - 1

    @property
    def start(self) -> date:
        return self.dates[0]

    @property
    def end(self) -> date:
        return self.dates[-1]

    @property
    def span_days(self) -> int:
        return (self.end - self.start).days

    @property
    def return_dates(self) -> tuple[date, ...]:
        """End date of each one-period return."""
        return self.dates[1:]

    @property
    def suspect_fraction(self) -> Decimal:
        with engine_context():
            return Decimal(len(self.gaps)) / Decimal(self.n_observations)

    @property
    def risk_eligible(self) -> bool:
        return self.suspect_fraction <= MAX_SUSPECT_FRACTION

    def covers_years(self, years: int) -> bool:
        """True when the calendar span is at least ``years`` (EDATE semantics)."""
        return _years_covered(self.start, self.end, years)

    # ------------------------------------------------------------------ float boundary
    def price_array(self) -> FloatArray:
        arr = np.array([float(p) for p in self.prices], dtype=np.float64)
        arr.setflags(write=False)
        return arr

    def simple_returns(self) -> FloatArray:
        p = self.price_array()
        out = p[1:] / p[:-1] - 1.0
        out.setflags(write=False)
        return out

    def log_returns(self) -> FloatArray:
        p = self.price_array()
        out = np.log(p[1:] / p[:-1])
        out.setflags(write=False)
        return out

    def horizon_returns(self, horizon: int) -> FloatArray:
        """Overlapping h-period simple returns ``P_{t+h}/P_t − 1`` (risk-methodology §5.2)."""
        if horizon < 1:
            raise InvalidInput("horizon must be ≥ 1 period")
        if horizon > self.n_returns:
            raise InsufficientHistory(f"horizon {horizon} exceeds the {self.n_returns} available periods")
        p = self.price_array()
        out = p[horizon:] / p[:-horizon] - 1.0
        out.setflags(write=False)
        return out

    def annualisation(self, override: int | None = None) -> Annualisation:
        """§1.1: ``A = round(n_returns / (span_days / 365.25))``; fallback when the span is under one year."""
        if override is not None:
            if override < 1:
                raise InvalidInput("annualisation factor must be ≥ 1")
            return Annualisation(override, "override")
        if not self.covers_years(1):
            return Annualisation(FALLBACK_ANNUALISATION[self.frequency], "fallback")
        with engine_context():
            years = Decimal(self.span_days) / Decimal(repr(DAYS_PER_YEAR))
            factor = int((Decimal(self.n_returns) / years).to_integral_value())
        return Annualisation(factor, "estimated")

    # ------------------------------------------------------------------ slicing
    def window(self, start: date, end: date) -> ReturnSeries:
        """Observations with ``start ≤ date ≤ end`` (no filling at either edge)."""
        if end < start:
            raise InvalidInput(f"window end {end} before start {start}")
        idx = [i for i, d in enumerate(self.dates) if start <= d <= end]
        return ReturnSeries(
            dates=tuple(self.dates[i] for i in idx),
            prices=tuple(self.prices[i] for i in idx),
            frequency=self.frequency,
            max_gap_days=self.max_gap_days,
            holidays=self.holidays,
        )


def ensure_comparable(series: Iterable[ReturnSeries]) -> list[ReturnSeries]:
    """§1.1 rule 1: same frequency, same start and same end date.  Otherwise InvalidInput."""
    items = list(series)
    if not items:
        raise InvalidInput("no series supplied")
    first = items[0]
    for s in items[1:]:
        if s.frequency is not first.frequency:
            raise InvalidInput(f"mixed frequencies: {first.frequency.value} vs {s.frequency.value}")
    for s in items[1:]:
        if (s.start, s.end) != (first.start, first.end):
            raise InvalidInput(
                f"mixed periods: {first.start}..{first.end} vs {s.start}..{s.end}; window the series first"
            )
    return items


@dataclass(frozen=True)
class AlignedPrices:
    dates: tuple[date, ...]
    prices: tuple[FloatArray, ...]
    dropped: tuple[int, ...]  # observations dropped from each input by the inner join
    frequency: Frequency

    @property
    def n_returns(self) -> int:
        return len(self.dates) - 1

    def simple_returns(self, i: int) -> FloatArray:
        p = self.prices[i]
        return p[1:] / p[:-1] - 1.0

    def log_returns(self, i: int) -> FloatArray:
        p = self.prices[i]
        return np.log(p[1:] / p[:-1])

    def annualisation(self, override: int | None) -> Annualisation:
        if override is not None:
            if override < 1:
                raise InvalidInput("annualisation factor must be ≥ 1")
            return Annualisation(override, "override")
        start, end = self.dates[0], self.dates[-1]
        if not _years_covered(start, end, 1):
            return Annualisation(FALLBACK_ANNUALISATION[self.frequency], "fallback")
        years = (end - start).days / DAYS_PER_YEAR
        return Annualisation(round(self.n_returns / years), "estimated")


def align(series: Iterable[ReturnSeries]) -> AlignedPrices:
    """Inner-join on dates only (§1: never pair a date t with a different date).  Prices, then returns."""
    items = ensure_comparable(series)
    common = set(items[0].dates)
    for s in items[1:]:
        common &= set(s.dates)
    dates = tuple(sorted(common))
    if len(dates) < 2:
        raise InsufficientHistory("fewer than 2 common observation dates after alignment")
    arrays: list[FloatArray] = []
    dropped: list[int] = []
    for s in items:
        lookup = dict(zip(s.dates, s.prices, strict=True))
        arrays.append(np.array([float(lookup[d]) for d in dates], dtype=np.float64))
        dropped.append(s.n_observations - len(dates))
    return AlignedPrices(dates=dates, prices=tuple(arrays), dropped=tuple(dropped), frequency=items[0].frequency)
