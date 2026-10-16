"""Month-end series grid, blended paths and drawdown episodes — all in Decimal (design-risk-first.md F9, §5.2–§5.3).

The risk snapshot never reads raw daily NAV history: each scheme is reduced once to a **month-end grid** (stored in the
``series_grid`` table) and the engine works on that.  This module is the pure reduction plus the statistics computed on
it.

Rules
* **Month-end selection.** For each calendar month the grid value is the *last* observation dated in that month, kept
  only if it lies within ``max_staleness_days`` of the calendar month-end (default 7 calendar days, the same threshold
  as the daily gap rule in risk-methodology §1).  Otherwise the month is a gap.
* **Never filled.** A month with no observation (``NO_OBSERVATION``) or only a stale one (``STALE``) is recorded as a
  gap with its reason; no value is carried forward or interpolated.  Invalid months at either edge of the series (for
  example the still-running current month) are *trimmed* and recorded separately from interior gaps.
* **Drawdown** (``MDD-GRID@1``) is computed from Decimal levels: depth ``1 − trough / peak`` as a positive magnitude.
  A new high is any level ``≥`` the running peak; recovery is the first month whose level is ``≥`` the episode's peak.
  Durations are **calendar months** between month-end keys, so a gap can never shorten them; recovery years are
  ``underwater_months / 12`` (unrounded).  Month-end sampling cannot see intra-month lows, so the grid MDD may
  understate the daily MDD; every result carries that caveat.
* **Blended path.** Fixed weights over the components' common window, either rebalanced monthly or held from the start
  (no rebalancing).  Any component gap inside the window fails closed (``MissingData``).

Pure: no clock, IO or randomness (test_engine_purity.py).
"""

from __future__ import annotations

import calendar
import itertools
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from iip.engine.errors import InsufficientHistory, InvalidInput, MissingData
from iip.engine.money import ONE, ZERO, D, engine_context

METHOD_ID = "MDD-GRID@1"
DEFAULT_MAX_STALENESS_DAYS = 7

# Caveat codes
MONTH_END_SAMPLING = "MONTH_END_SAMPLING_MAY_UNDERSTATE_INTRAMONTH_DRAWDOWN"
MDD_WITHIN_AVAILABLE_HISTORY = "MDD_WITHIN_AVAILABLE_HISTORY"
DRAWDOWN_ONGOING = "DRAWDOWN_ONGOING"
PEAK_AT_SERIES_START = "PEAK_AT_SERIES_START"
GAPS_PRESENT = "GAPS_PRESENT_DRAWDOWN_MAY_BE_UNDERSTATED"


class GapReason(StrEnum):
    NO_OBSERVATION = "no_observation"
    STALE = "stale_month_end"


class Rebalance(StrEnum):
    MONTHLY = "monthly"
    NONE = "none"  # buy-and-hold from the first common month


# ---------------------------------------------------------------------------------------------- calendar helpers


def month_end_of(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _next_month_end(d: date) -> date:
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(y, m, calendar.monthrange(y, m)[1])


def months_between(start: date, end: date) -> int:
    """Whole calendar months from ``start``'s month to ``end``'s month."""
    return (end.year - start.year) * 12 + (end.month - start.month)


def _is_month_end(d: date) -> bool:
    return d == month_end_of(d)


def _as_date(value: date | str, what: str) -> date:
    if isinstance(value, datetime):
        raise InvalidInput(f"{what} must be a date, not a datetime")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise InvalidInput(f"{what} is not an ISO date: {value!r}") from exc
    raise InvalidInput(f"{what} must be a date or ISO string, got {type(value).__name__}")


def _positive(value: Decimal | str | int, what: str) -> Decimal:
    v = D(value)
    if v <= 0:
        raise InvalidInput(f"{what} must be positive, got {v}")
    return v


def _check_staleness(days: int) -> None:
    if isinstance(days, bool) or not isinstance(days, int) or not 0 <= days <= 27:
        raise InvalidInput(f"max_staleness_days must be an int in 0..27, got {days!r}")


# ---------------------------------------------------------------------------------------------- grid


@dataclass(frozen=True)
class MonthCell:
    """The accepted month-end value: ``nav`` is the real observation dated ``obs_date``."""

    month_end: date
    obs_date: date
    nav: Decimal


@dataclass(frozen=True)
class MonthGap:
    month_end: date
    reason: GapReason
    last_obs_date: date | None  # the stale observation, when there was one


@dataclass(frozen=True)
class SeriesGrid:
    """Month-end grid of one series.  ``cells`` are the valid months (ascending); ``gaps`` are invalid months strictly
    between the first and last valid month; ``trimmed`` are invalid months at either edge."""

    cells: tuple[MonthCell, ...]
    gaps: tuple[MonthGap, ...]
    trimmed: tuple[MonthGap, ...]
    max_staleness_days: int

    @property
    def start_month(self) -> date:
        return self.cells[0].month_end

    @property
    def end_month(self) -> date:
        return self.cells[-1].month_end

    @property
    def is_contiguous(self) -> bool:
        return not self.gaps

    def path(self) -> list[tuple[date, Decimal]]:
        """``(month_end, nav)`` for the valid months only (gaps are absent, never filled)."""
        return [(c.month_end, c.nav) for c in self.cells]

    def to_rows(self) -> list[tuple[str, str, str]]:
        """Storage rows ``(month_end ISO, obs_date ISO, nav as Decimal string)`` for the ``series_grid`` table."""
        return [(c.month_end.isoformat(), c.obs_date.isoformat(), str(c.nav)) for c in self.cells]

    @classmethod
    def from_rows(
        cls,
        rows: Iterable[tuple[date | str, date | str, Decimal | str | int]],
        *,
        max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
    ) -> SeriesGrid:
        """Rebuild a grid from stored month-end rows (validated; interior missing months become gaps).

        Edge trimming information is not stored, so ``trimmed`` is empty.
        """
        _check_staleness(max_staleness_days)
        cells: list[MonthCell] = []
        for month_end_raw, obs_raw, nav_raw in rows:
            m = _as_date(month_end_raw, "month_end")
            o = _as_date(obs_raw, "obs_date")
            if not _is_month_end(m):
                raise InvalidInput(f"grid key {m} is not a calendar month-end")
            if (o.year, o.month) != (m.year, m.month):
                raise InvalidInput(f"observation {o} is not in month {m:%Y-%m}")
            if (m - o).days > max_staleness_days:
                raise InvalidInput(f"observation {o} is staler than {max_staleness_days} days for {m}")
            if cells and m <= cells[-1].month_end:
                raise InvalidInput(f"grid rows must be strictly increasing: {cells[-1].month_end} then {m}")
            cells.append(MonthCell(month_end=m, obs_date=o, nav=_positive(nav_raw, f"nav at {m}")))
        if not cells:
            raise InsufficientHistory("no grid rows")
        gaps: list[MonthGap] = []
        for a, b in itertools.pairwise(cells):
            m = _next_month_end(a.month_end)
            while m < b.month_end:
                gaps.append(MonthGap(month_end=m, reason=GapReason.NO_OBSERVATION, last_obs_date=None))
                m = _next_month_end(m)
        return cls(cells=tuple(cells), gaps=tuple(gaps), trimmed=(), max_staleness_days=max_staleness_days)


def month_end_grid(
    observations: Iterable[tuple[date, Decimal | str | int]],
    *,
    max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
) -> SeriesGrid:
    """Reduce dated NAV observations (strictly increasing dates, positive Decimal values) to a month-end grid.

    The input is never sorted or deduplicated: disorder or duplicates raise ``InvalidInput``.  Raises
    ``InsufficientHistory`` when no month has a valid month-end value.
    """
    _check_staleness(max_staleness_days)
    last_in_month: dict[date, tuple[date, Decimal]] = {}
    prev: date | None = None
    for raw_d, raw_v in observations:
        if isinstance(raw_d, datetime) or not isinstance(raw_d, date):
            raise InvalidInput(f"observation dates must be datetime.date, got {type(raw_d).__name__}")
        d = raw_d
        v = _positive(raw_v, f"nav at {d}")
        if prev is not None and d <= prev:
            raise InvalidInput(f"observation dates must be strictly increasing: {prev} then {d}")
        prev = d
        last_in_month[month_end_of(d)] = (d, v)
    if not last_in_month:
        raise InsufficientHistory("no observations")
    first, last = min(last_in_month), max(last_in_month)
    slots: list[MonthCell | MonthGap] = []
    m = first
    while m <= last:
        hit = last_in_month.get(m)
        if hit is None:
            slots.append(MonthGap(month_end=m, reason=GapReason.NO_OBSERVATION, last_obs_date=None))
        elif (m - hit[0]).days > max_staleness_days:
            slots.append(MonthGap(month_end=m, reason=GapReason.STALE, last_obs_date=hit[0]))
        else:
            slots.append(MonthCell(month_end=m, obs_date=hit[0], nav=hit[1]))
        m = _next_month_end(m)
    valid = [i for i, s in enumerate(slots) if isinstance(s, MonthCell)]
    if not valid:
        raise InsufficientHistory(f"no month has an observation within {max_staleness_days} days of its month-end")
    lo, hi = valid[0], valid[-1]
    trimmed = tuple(s for s in slots[:lo] + slots[hi + 1 :] if isinstance(s, MonthGap))
    inner = slots[lo : hi + 1]
    return SeriesGrid(
        cells=tuple(s for s in inner if isinstance(s, MonthCell)),
        gaps=tuple(s for s in inner if isinstance(s, MonthGap)),
        trimmed=trimmed,
        max_staleness_days=max_staleness_days,
    )


# ---------------------------------------------------------------------------------------------- drawdown


@dataclass(frozen=True)
class DrawdownEpisode:
    """One peak → trough → recovery episode on a month-end path.  ``depth`` is a positive magnitude."""

    peak_month: date
    peak_level: Decimal
    trough_month: date
    trough_level: Decimal
    depth: Decimal
    recovery_month: date | None
    peak_to_trough_months: int
    trough_to_recovery_months: int | None
    underwater_months: int  # peak → recovery; when ongoing, months underwater so far ("at least")
    recovered: bool

    @property
    def recovery_years(self) -> Decimal | None:
        """Peak → recovery in years (``underwater_months / 12``); ``None`` while the drawdown is ongoing."""
        if not self.recovered:
            return None
        with engine_context():
            return Decimal(self.underwater_months) / Decimal(12)


@dataclass(frozen=True)
class GridDrawdown:
    value: Decimal  # maximum depth; 0 when the path never falls
    episode: DrawdownEpisode | None  # the episode with the maximum depth (earliest on ties)
    episodes: tuple[DrawdownEpisode, ...]
    path_start: date
    path_end: date
    n_points: int
    caveats: tuple[str, ...]
    method_id: str = METHOD_ID


def _validate_path(path: Sequence[tuple[date, Decimal]]) -> list[tuple[date, Decimal]]:
    pts = list(path)
    if len(pts) < 2:
        raise InsufficientHistory(f"a drawdown needs ≥ 2 month-end points, got {len(pts)}")
    out: list[tuple[date, Decimal]] = []
    for d, v in pts:
        if isinstance(d, datetime) or not isinstance(d, date) or not _is_month_end(d):
            raise InvalidInput(f"path keys must be calendar month-end dates, got {d!r}")
        if out and d <= out[-1][0]:
            raise InvalidInput(f"path dates must be strictly increasing: {out[-1][0]} then {d}")
        if not isinstance(v, Decimal):
            raise InvalidInput(f"path levels must be Decimal, got {type(v).__name__}")
        out.append((d, _positive(v, f"level at {d}")))
    return out


def _episode(pts: list[tuple[date, Decimal]], pi: int, ti: int, ri: int | None) -> DrawdownEpisode:
    p_date, p_lv = pts[pi]
    t_date, t_lv = pts[ti]
    with engine_context():
        depth = ONE - t_lv / p_lv
    r_date = pts[ri][0] if ri is not None else None
    end_date = r_date if r_date is not None else pts[-1][0]
    return DrawdownEpisode(
        peak_month=p_date,
        peak_level=p_lv,
        trough_month=t_date,
        trough_level=t_lv,
        depth=depth,
        recovery_month=r_date,
        peak_to_trough_months=months_between(p_date, t_date),
        trough_to_recovery_months=months_between(t_date, r_date) if r_date is not None else None,
        underwater_months=months_between(p_date, end_date),
        recovered=r_date is not None,
    )


def drawdown_episodes(path: Sequence[tuple[date, Decimal]]) -> tuple[DrawdownEpisode, ...]:
    """Every peak → trough → recovery episode, in time order.  Only the last may be unrecovered."""
    pts = _validate_path(path)
    episodes: list[DrawdownEpisode] = []
    peak_i = 0
    trough_i: int | None = None
    for t in range(1, len(pts)):
        lv = pts[t][1]
        if lv >= pts[peak_i][1]:
            if trough_i is not None:
                episodes.append(_episode(pts, peak_i, trough_i, t))
                trough_i = None
            peak_i = t
        elif trough_i is None or lv < pts[trough_i][1]:
            trough_i = t
    if trough_i is not None:
        episodes.append(_episode(pts, peak_i, trough_i, None))
    return tuple(episodes)


def max_drawdown_of_path(path: Sequence[tuple[date, Decimal]], *, extra_caveats: Iterable[str] = ()) -> GridDrawdown:
    """Maximum drawdown of a month-end level path, with its episode and all episodes (``MDD-GRID@1``)."""
    pts = _validate_path(path)
    episodes = drawdown_episodes(pts)
    worst: DrawdownEpisode | None = None
    for ep in episodes:
        if worst is None or ep.depth > worst.depth:
            worst = ep
    caveats = [MONTH_END_SAMPLING, MDD_WITHIN_AVAILABLE_HISTORY, *extra_caveats]
    if worst is not None:
        if not worst.recovered:
            caveats.append(DRAWDOWN_ONGOING)
        if worst.peak_month == pts[0][0]:
            caveats.append(PEAK_AT_SERIES_START)
    return GridDrawdown(
        value=worst.depth if worst is not None else ZERO,
        episode=worst,
        episodes=episodes,
        path_start=pts[0][0],
        path_end=pts[-1][0],
        n_points=len(pts),
        caveats=tuple(caveats),
    )


def grid_max_drawdown(grid: SeriesGrid, *, allow_gaps: bool = False) -> GridDrawdown:
    """MDD of a grid.  Interior gaps fail closed (``MissingData``) unless ``allow_gaps``; then the result is computed
    on the valid months only and carries ``GAPS_PRESENT`` (a gap can hide the true trough)."""
    if grid.gaps and not allow_gaps:
        listed = ", ".join(f"{g.month_end:%Y-%m}({g.reason.value})" for g in grid.gaps)
        raise MissingData(f"series grid has interior gaps: {listed}")
    return max_drawdown_of_path(grid.path(), extra_caveats=(GAPS_PRESENT,) if grid.gaps else ())


# ---------------------------------------------------------------------------------------------- blended path


@dataclass(frozen=True)
class BlendedPath:
    months: tuple[date, ...]
    levels: tuple[Decimal, ...]  # starts at 1
    weights: tuple[tuple[str, Decimal], ...]  # sorted by key
    rebalance: Rebalance

    def path(self) -> list[tuple[date, Decimal]]:
        return list(zip(self.months, self.levels, strict=True))


def blended_path(
    grids: Mapping[str, SeriesGrid],
    weights: Mapping[str, Decimal],
    *,
    rebalance: Rebalance,
) -> BlendedPath:
    """Fixed-weight blend of month-end grids over their common window, starting at level 1.

    ``MONTHLY``: ``L_t = L_{t−1} × Σ w_i × NAV_i,t / NAV_i,t−1``.  ``NONE``: ``L_t = Σ w_i × NAV_i,t / NAV_i,start``.
    Weights must be non-negative Decimals summing exactly to 1.  A component gap in the window raises ``MissingData``.
    """
    if not isinstance(rebalance, Rebalance):
        raise InvalidInput(f"unknown rebalance mode {rebalance!r}")
    if not grids:
        raise InvalidInput("no components supplied")
    if set(grids) != set(weights):
        raise InvalidInput(f"weights keys {sorted(weights)} do not match grids keys {sorted(grids)}")
    keys = sorted(grids)
    w: dict[str, Decimal] = {}
    for k in keys:
        wk = D(weights[k])
        if wk < 0:
            raise InvalidInput(f"weight for {k!r} is negative: {wk}")
        w[k] = wk
    with engine_context():
        total = sum((w[k] for k in keys), ZERO)
    if total != ONE:
        raise InvalidInput(f"weights must sum to 1, got {total}")
    start = max(grids[k].start_month for k in keys)
    end = min(grids[k].end_month for k in keys)
    if start >= end:
        raise InsufficientHistory(f"components share fewer than 2 month-ends ({start} .. {end})")
    months: list[date] = []
    m = start
    while m <= end:
        months.append(m)
        m = _next_month_end(m)
    navs: dict[str, list[Decimal]] = {}
    missing: list[str] = []
    for k in keys:
        lookup = {c.month_end: c.nav for c in grids[k].cells}
        missing.extend(f"{k}@{mm:%Y-%m}" for mm in months if mm not in lookup)
        navs[k] = [lookup[mm] for mm in months if mm in lookup]
    if missing:
        raise MissingData(f"component gaps inside the blend window: {', '.join(missing)}")
    levels = [ONE]
    with engine_context():
        for t in range(1, len(months)):
            if rebalance is Rebalance.MONTHLY:
                growth = sum((w[k] * navs[k][t] / navs[k][t - 1] for k in keys), ZERO)
                levels.append(levels[-1] * growth)
            else:
                levels.append(sum((w[k] * navs[k][t] / navs[k][0] for k in keys), ZERO))
    return BlendedPath(
        months=tuple(months),
        levels=tuple(levels),
        weights=tuple((k, w[k]) for k in keys),
        rebalance=rebalance,
    )
