"""Return-Target Feasibility (docs/research/return-target-feasibility.md §4).

Reports the **historical frequency** with which a target return T p.a. was met over H-year windows of a single
total-return series, with losses, path drawdowns and honesty statistics (independent periods, start-month
sensitivity, back-calculated history). It is not a forecast and never uses probability language (§4.6).

All arithmetic is Decimal under ``engine_context`` (implementation-rules §5): this module lives outside
``engine/stats`` and ``engine/forecasting``, so floats are not used at all. The hit test is Decimal, inclusive (F-2).
"""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise

from iip.engine.errors import InsufficientHistory, InvalidInput
from iip.engine.money import ONE, ZERO, engine_context, format_inr, money

FORMULA_ID = "FEASIBILITY@1"
FREQUENCY_LABEL = "historical frequency (overlapping windows)"
PERCENTILE_KEYS: tuple[tuple[str, Decimal], ...] = (
    ("p5", Decimal("0.05")),
    ("p10", Decimal("0.10")),
    ("p25", Decimal("0.25")),
    ("p50", Decimal("0.50")),
    ("p75", Decimal("0.75")),
    ("p90", Decimal("0.90")),
    ("p95", Decimal("0.95")),
)
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "probability",
    "chance",
    "likely to",
    "expected return",
    "success rate",
    "guaranteed",
    "safe",
    "will achieve",
    "on track",
    "recommended",
    "best fund",
)
FIXED_CAVEATS: tuple[str, ...] = (
    "Overlapping windows share most of their months. N overlapping windows contain only about n_eff independent "
    "observations, and the frequency can swing widely with the start month (anchor range shown).",
    "The past regime may not repeat. Interest rates, valuations, inflation, market structure and taxes change. "
    "Evidence that returns can be predicted is weak (Goyal & Welch 2008).",
    "Survivorship and backfill. Indices launched after their base date contain back-calculated history. Funds "
    "that closed or merged are missing from fund histories.",
    "Small samples. Ten-year statistics in India rest on one or two independent decades.",
    "Index TRIs exclude fees, tracking error, taxes and your own timing.",
    "This is not investment advice and not a forecast.",
)
SUSPECT_MAX_SHARE = Decimal("0.02")
SUSPECT_TAIL_DAYS = 7
POST_CRASH_START = date(2009, 3, 31)
MAJOR_DRAWDOWN = Decimal("-0.20")
TARGET_CONFIRM_ABOVE = Decimal("0.30")
SPLIT_DOWN_JUMP = Decimal("0.30")  # one-day move ≤ −70 %
SPLIT_UP_JUMP = Decimal("3.30")  # one-day move ≥ +230 %
SPLIT_TOLERANCE = Decimal("0.01")


class InstrumentKind(StrEnum):
    INDEX_TRI = "index_tri"
    FUND_NAV = "fund_nav"
    ETF_NAV = "etf_nav"


class Mode(StrEnum):
    CAGR = "CAGR"  # R1: compound average over H ≥ T
    EVERY_YEAR = "EVERY_YEAR"  # R2: each consecutive 12-month return ≥ T


class YearBasis(StrEnum):
    NOMINAL = "nominal"
    ACT365 = "act365"


class EvidenceLevel(StrEnum):
    REFUSED = "REFUSED"  # n_eff < 2: no frequencies, no counts
    LOW_EVIDENCE = "LOW_EVIDENCE"  # 2 ≤ n_eff < 5: counts only
    SUFFICIENT = "SUFFICIENT"  # n_eff ≥ 5: percentages allowed


@dataclass(frozen=True)
class Observation:
    date: date
    value: Decimal


@dataclass(frozen=True)
class GridPoint:
    date: date
    value: Decimal
    suspect: bool = False


@dataclass(frozen=True)
class SplitAudit:
    effective_date: date
    ratio: int
    kind: str  # "split" | "consolidation"
    raw_previous: Decimal
    raw_value: Decimal


@dataclass(frozen=True)
class SeriesMeta:
    series_id: str
    instrument_kind: InstrumentKind
    inception_date: date
    launch_date: date | None
    net_of_fees: bool
    source: str
    currency: str = "INR"
    display_name: str | None = None  # human-readable instrument name for headlines (falls back to series_id)


@dataclass(frozen=True)
class FeasibilityRequest:
    target_rate: Decimal
    horizon_years: int
    as_of: date
    mode: Mode = Mode.CAGR
    amount_inr: Decimal | None = None
    loss_budget: Decimal | None = None
    include_backfilled: bool = True
    year_basis: YearBasis = YearBasis.NOMINAL


@dataclass(frozen=True)
class Window:
    start_index: int
    start_date: date
    end_date: date
    start_value: Decimal
    end_value: Decimal
    ratio: Decimal
    cagr: Decimal
    hit: bool
    loss: bool
    flat: bool
    backfilled: bool
    max_drawdown: Decimal
    longest_underwater_months: int
    below_inflation: bool | None


@dataclass(frozen=True)
class Counts:
    n_windows: int
    hit_count: int
    loss_count: int
    flat_count: int
    below_inflation_count: int | None = None


@dataclass(frozen=True)
class Frequencies:
    """Only populated when n_eff ≥ 5. Each value is a historical frequency, not a probability."""

    hit_freq: Decimal
    loss_freq: Decimal
    flat_freq: Decimal
    below_inflation_freq: Decimal | None
    label: str = FREQUENCY_LABEL


@dataclass(frozen=True)
class Percentiles:
    cagr: dict[str, Decimal]
    method: str = "Hyndman–Fan type 7 (Excel PERCENTILE.INC)"


@dataclass(frozen=True)
class PathRisk:
    mdd_all: dict[str, Decimal]
    mdd_hit: dict[str, Decimal] | None
    worst_mdd_in_hit_window: Decimal | None
    longest_underwater_in_hit_window_months: int | None
    median_mdd_all_inr: Decimal | None
    median_mdd_hit_inr: Decimal | None
    resolution: str  # "daily" | "grid"


@dataclass(frozen=True)
class Anchor:
    anchor: int
    hits: int
    blocks: int


@dataclass(frozen=True)
class EveryYear:
    count: int
    n_windows: int
    longest_calendar_year_streak: int
    label: str


@dataclass(frozen=True)
class ExtremeWindow:
    start_date: date
    end_date: date
    start_value: Decimal
    end_value: Decimal
    cagr: Decimal


@dataclass(frozen=True)
class FullHistoryDrawdown:
    depth: Decimal
    peak_date: date
    trough_date: date
    recovery_date: date | None
    ongoing: bool
    label: str


@dataclass(frozen=True)
class LeverLine:
    basis: str  # "target" | "historical p25" | "historical p50"
    rate: Decimal
    lump_sum_inr: Decimal
    monthly_sip_inr: Decimal
    label: str


@dataclass(frozen=True)
class FeasibilityReport:
    series_id: str
    target_rate: Decimal
    horizon_years: int
    mode: Mode
    year_basis: YearBasis
    steps_per_year: int
    grid_start: date
    grid_end: date
    n_grid_steps: int  # M
    n_eff: int
    evidence_level: EvidenceLevel
    windows: tuple[Window, ...]
    counts: Counts | None
    frequencies: Frequencies | None
    percentiles: Percentiles | None
    worst: ExtremeWindow | None
    best: ExtremeWindow | None
    path_risk: PathRisk | None
    anchors: tuple[Anchor, ...]
    anchor_range: tuple[Decimal, Decimal] | None
    anchor_block_range: tuple[int, int] | None
    backfilled_share: Decimal
    excluding_backfilled: Counts | None
    recency_rank: Decimal | None
    every_year: EveryYear | None
    full_history_drawdown: FullHistoryDrawdown
    loss_budget_exceeded_count: int | None
    realised_independent_cagrs: tuple[Decimal, ...]
    headline: str
    banners: tuple[str, ...]
    notes: tuple[str, ...]
    caveats: tuple[str, ...]
    flags: tuple[str, ...]
    frequency_label: str = FREQUENCY_LABEL
    formula_id: str = FORMULA_ID
    inputs: dict[str, str] = field(default_factory=dict)

    def all_labels(self) -> tuple[str, ...]:
        texts: list[str] = [self.headline, self.frequency_label, *self.banners, *self.notes, *self.caveats]
        texts.append(self.full_history_drawdown.label)
        if self.every_year is not None:
            texts.append(self.every_year.label)
        if self.frequencies is not None:
            texts.append(self.frequencies.label)
        return tuple(texts)


# =====================================================================================================
# helpers
# =====================================================================================================


def _guard_wording(texts: Sequence[str]) -> None:
    for text in texts:
        low = text.lower()
        for bad in FORBIDDEN_PHRASES:
            if bad in low:
                raise InvalidInput(f"forbidden wording {bad!r} in label: {text!r}")  # pragma: no cover


def percentile_type7(values: Sequence[Decimal], p: Decimal) -> Decimal:
    """Linear interpolation between order statistics (Hyndman–Fan type 7 = Excel PERCENTILE.INC).

    k = (N − 1)·p, x = s_⌊k⌋ + (k − ⌊k⌋)(s_⌈k⌉ − s_⌊k⌋).
    """
    if not values:
        raise InsufficientHistory("no values for a percentile")
    if not ZERO <= p <= ONE:
        raise InvalidInput(f"percentile outside [0, 1]: {p}")
    s = sorted(values)
    with engine_context():
        k = Decimal(len(s) - 1) * p
        lo = int(k)  # k ≥ 0 so int() is floor
        frac = k - Decimal(lo)
        if frac == 0 or lo + 1 >= len(s):
            return s[lo]
        return s[lo] + frac * (s[lo + 1] - s[lo])


def _percentiles(values: Sequence[Decimal]) -> dict[str, Decimal]:
    return {key: percentile_type7(values, p) for key, p in PERCENTILE_KEYS}


def _months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def _fmt_pct(x: Decimal, places: int = 0) -> str:
    """Whole-number percentages for frequencies (RT-14); signed with a real minus sign."""
    with engine_context():
        q = (x * 100).quantize(Decimal(1).scaleb(-places))
    text = f"{abs(q):f}"
    return f"−{text} %" if q < 0 else f"{text} %"


def _fmt_rate(x: Decimal) -> str:
    with engine_context():
        v = (x * 100).normalize()
    if v == v.to_integral_value():
        v = v.quantize(ONE)
    text = f"{abs(v):f}"
    return f"−{text} %" if v < 0 else f"{text} %"


def _years(h: int) -> str:
    return "1 year" if h == 1 else f"{h} years"


def _fmt_inr(x: Decimal) -> str:
    return format_inr(x, paise=False)


def _mdd_path(path: Sequence[tuple[date, Decimal]]) -> tuple[Decimal, int]:
    """Max drawdown within a path (relative to the running max from the path start) and the longest
    underwater spell in calendar months (peak date → first close ≥ peak, or path end)."""
    with engine_context():
        peak_v = path[0][1]
        peak_d = path[0][0]
        worst = ZERO
        longest = 0
        under = False
        for d, v in path[1:]:
            if v >= peak_v:
                if under:
                    longest = max(longest, _months_between(peak_d, d))
                    under = False
                peak_v, peak_d = v, d
                continue
            under = True
            dd = v / peak_v - ONE
            worst = min(worst, dd)
        if under:
            longest = max(longest, _months_between(peak_d, path[-1][0]))
    return worst, longest


def _validate_request(req: FeasibilityRequest) -> None:
    t = req.target_rate
    if not isinstance(t, Decimal) or not t.is_finite():
        raise InvalidInput("target_rate must be a finite Decimal")
    if t <= -ONE:
        raise InvalidInput("target_rate ≤ −100 % is rejected")
    if not (Decimal("-0.50") < t <= ONE):
        raise InvalidInput("target_rate must satisfy −0.50 < T ≤ 1.00")
    if isinstance(req.horizon_years, bool) or not isinstance(req.horizon_years, int):
        raise InvalidInput("horizon_years must be an integer")
    if not 1 <= req.horizon_years <= 20:
        raise InvalidInput("horizon_years must be in 1..20 (H < 1 y is refused for target testing, Rule A1)")
    if req.amount_inr is not None and not req.amount_inr > 0:
        raise InvalidInput("amount_inr must be > 0")
    if req.loss_budget is not None and not ZERO < req.loss_budget <= ONE:
        raise InvalidInput("loss_budget must be a fraction in (0, 1]")


def _validate_grid(grid: Sequence[GridPoint]) -> None:
    if len(grid) < 2:
        raise InsufficientHistory("need at least two grid points")
    for g in grid:
        if not isinstance(g.value, Decimal) or not g.value.is_finite() or g.value <= 0:
            raise InvalidInput(f"value at {g.date} must be a finite Decimal > 0 (TRI/NAV)")
    for a, b in pairwise(grid):
        if b.date < a.date:
            raise InvalidInput(f"grid dates out of order ({a.date} → {b.date})")
    with engine_context():
        share = Decimal(sum(1 for g in grid if g.suspect)) / Decimal(len(grid))
    if share > SUSPECT_MAX_SHARE:
        raise InvalidInput(f"suspect grid points {share:.4f} > 2 % — series rejected")


# =====================================================================================================
# data preparation
# =====================================================================================================


def adjust_splits(
    observations: Sequence[Observation], kind: InstrumentKind
) -> tuple[tuple[Observation, ...], tuple[SplitAudit, ...]]:
    """Detect one-day jumps ≤ −70 % or ≥ +230 %. For fund/ETF NAVs, adjust if the jump matches an integer
    split (or consolidation) ratio within 1 %, with an audit row; otherwise (and always for index TRI) reject."""
    out: list[Observation] = []
    audit: list[SplitAudit] = []
    factor = ONE
    with engine_context():
        for i, ob in enumerate(observations):
            if not ob.value.is_finite() or ob.value <= 0:
                raise InvalidInput(f"value at {ob.date} must be > 0")
            if i > 0:
                prev_raw = observations[i - 1].value
                jump = ob.value / prev_raw
                if jump <= SPLIT_DOWN_JUMP or jump >= SPLIT_UP_JUMP:
                    if kind is InstrumentKind.INDEX_TRI:
                        raise InvalidInput(f"one-day jump {jump:.4f} at {ob.date} in an index TRI — rejected")
                    is_split = jump <= SPLIT_DOWN_JUMP
                    raw_ratio = (prev_raw / ob.value) if is_split else jump
                    ratio = int(raw_ratio.to_integral_value())
                    if ratio < 2 or abs(raw_ratio / Decimal(ratio) - ONE) > SPLIT_TOLERANCE:
                        raise InvalidInput(
                            f"one-day jump {jump:.4f} at {ob.date} does not match an integer split ratio"
                        )
                    factor = factor * Decimal(ratio) if is_split else factor / Decimal(ratio)
                    audit.append(
                        SplitAudit(
                            effective_date=ob.date,
                            ratio=ratio,
                            kind="split" if is_split else "consolidation",
                            raw_previous=prev_raw,
                            raw_value=ob.value,
                        )
                    )
            out.append(Observation(ob.date, ob.value * factor))
    return tuple(out), tuple(audit)


def build_month_end_grid(observations: Sequence[Observation], *, as_of: date) -> tuple[GridPoint, ...]:
    """§4.4.1 month-end grid, point-in-time (observations dated > as_of are ignored).

    g_0 is the first observation (standing in for its own month); each later month k contributes the last
    observation on or before its last calendar day, marked ``suspect`` if no observation fell in the month's
    last 7 calendar days. The last grid point is the last *complete* month-end ≤ as_of. > 2 % suspect → reject.
    """
    obs = [o for o in observations if o.date <= as_of]
    if not obs:
        raise InsufficientHistory(f"no observations on or before {as_of}")
    for a, b in pairwise(obs):
        if not a.date < b.date:
            raise InvalidInput(f"observation dates must be strictly increasing ({a.date} → {b.date})")
    for o in obs:
        if not o.value.is_finite() or o.value <= 0:
            raise InvalidInput(f"value at {o.date} must be > 0")
    last_complete = as_of
    if as_of.day != calendar.monthrange(as_of.year, as_of.month)[1]:
        first_of_month = as_of.replace(day=1)
        last_complete = date.fromordinal(first_of_month.toordinal() - 1)
    grid: list[GridPoint] = [GridPoint(obs[0].date, obs[0].value)]
    y, m = obs[0].date.year, obs[0].date.month
    j = 0
    while True:
        m += 1
        if m > 12:
            y, m = y + 1, 1
        month_end = date(y, m, calendar.monthrange(y, m)[1])
        if month_end > last_complete:
            break
        while j + 1 < len(obs) and obs[j + 1].date <= month_end:
            j += 1
        ob = obs[j]
        suspect = (month_end - ob.date).days >= SUSPECT_TAIL_DAYS
        grid.append(GridPoint(ob.date, ob.value, suspect))
    _validate_grid(grid)
    return tuple(grid)


# =====================================================================================================
# core computation
# =====================================================================================================


def assess_feasibility(
    observations: Sequence[Observation],
    meta: SeriesMeta,
    request: FeasibilityRequest,
    *,
    inflation_index: Sequence[Decimal] | None = None,
) -> FeasibilityReport:
    """Full pipeline on a daily series: point-in-time cut → split adjustment → month-end grid → assessment."""
    obs = [o for o in observations if o.date <= request.as_of]
    adjusted, audit = adjust_splits(obs, meta.instrument_kind)
    grid = build_month_end_grid(adjusted, as_of=request.as_of)
    report = assess_on_grid(grid, meta, request, steps_per_year=12, daily=adjusted, inflation_index=inflation_index)
    if audit:
        extra = {f"split_{i}": f"{a.effective_date.isoformat()} {a.kind} 1:{a.ratio}" for i, a in enumerate(audit)}
        report = replace(report, inputs={**report.inputs, **extra}, flags=(*report.flags, "SPLIT_ADJUSTED"))
    return report


def assess_on_grid(
    grid: Sequence[GridPoint],
    meta: SeriesMeta,
    request: FeasibilityRequest,
    *,
    steps_per_year: int = 12,
    daily: Sequence[Observation] | None = None,
    inflation_index: Sequence[Decimal] | None = None,
) -> FeasibilityReport:
    """Assess on a prepared grid (``steps_per_year`` = 12 for month-end grids; 1 for the annual F-1 fixture).

    ``daily`` (optional) is the path used for in-window drawdowns; without it the grid itself is the path.
    ``inflation_index`` (optional) is a CPI level aligned one-to-one with ``grid``.
    """
    pts, cpi = _prepare_points(grid, meta, request, steps_per_year=steps_per_year, inflation_index=inflation_index)

    h = request.horizon_years
    t_rate = request.target_rate
    m = steps_per_year * h
    big_m = len(pts) - 1
    # Gate: series span < H + 1 years → no numbers (§4.5); also covers m > M (§4.8).
    if big_m < m + steps_per_year:
        raise InsufficientHistory(
            f"series spans {big_m} steps (< H + 1 = {h + 1} years at {steps_per_year}/year) — no numbers"
        )
    n_eff = big_m // m

    # path used for in-window drawdowns
    if daily is not None:
        path = [(o.date, o.value) for o in daily if pts[0].date <= o.date <= pts[-1].date]
        resolution = "daily"
    else:
        path = [(g.date, g.value) for g in pts]
        resolution = "grid"
    windows = _compute_windows(pts, meta, request, m=m, path=path)
    if cpi is not None:
        windows = _apply_inflation(windows, cpi, m=m)

    n = len(windows)
    counts = _counts(windows)
    cagrs = [w.cagr for w in windows]
    pct = _percentiles(cagrs)
    worst_w = min(windows, key=lambda w: (w.cagr, w.start_index))
    best_w = max(windows, key=lambda w: (w.cagr, -w.start_index))
    anchors, anchor_range, anchor_blocks = _anchors(windows, m=m, big_m=big_m)
    path_risk = _path_risk(windows, request.amount_inr, resolution)

    # back-calculated history and recency
    n_back = sum(1 for w in windows if w.backfilled)
    with engine_context():
        backfilled_share = Decimal(n_back) / Decimal(n)
        recency_rank = Decimal(sum(1 for c in cagrs if c <= windows[-1].cagr)) / Decimal(n)
    excl = _counts([w for w in windows if not w.backfilled]) if n_back else None

    every_year = _every_year(pts, h=h, steps_per_year=steps_per_year, n=n, t_rate=t_rate)
    full_dd = _full_history_drawdown(path)

    loss_budget_count: int | None = None
    if request.loss_budget is not None:
        with engine_context():
            limit = -request.loss_budget
        loss_budget_count = sum(1 for w in windows if w.max_drawdown < limit)

    level = _evidence_level(n_eff)
    realised = tuple(windows[i].cagr for i in range(0, big_m - m + 1, m))
    frequencies = _frequencies(counts) if level is EvidenceLevel.SUFFICIENT else None

    flags, banners, notes = _messages(
        meta=meta,
        request=request,
        level=level,
        pts=pts,
        n=n,
        n_back=n_back,
        full_dd=full_dd,
        recency_rank=recency_rank,
        mdd_p50=path_risk.mdd_all["p50"],
        loss_budget_count=loss_budget_count,
    )
    mdd_hit = path_risk.mdd_hit
    inr_hit = path_risk.median_mdd_hit_inr

    headline = _headline(
        meta=meta,
        request=request,
        level=level,
        pts=pts,
        counts=counts,
        n_eff=n_eff,
        anchor_range=anchor_range,
        every_year=every_year,
        mdd_hit=mdd_hit,
        inr_hit=inr_hit,
        realised=realised,
    )

    hide = level is EvidenceLevel.REFUSED
    report = FeasibilityReport(
        series_id=meta.series_id,
        target_rate=t_rate,
        horizon_years=h,
        mode=request.mode,
        year_basis=request.year_basis,
        steps_per_year=steps_per_year,
        grid_start=pts[0].date,
        grid_end=pts[-1].date,
        n_grid_steps=big_m,
        n_eff=n_eff,
        evidence_level=level,
        windows=() if hide else tuple(windows),
        counts=None if hide else counts,
        frequencies=frequencies,
        percentiles=None if hide else Percentiles(cagr=pct),
        worst=None if hide else _extreme(worst_w),
        best=None if hide else _extreme(best_w),
        path_risk=None if hide else path_risk,
        anchors=() if hide else tuple(anchors),
        anchor_range=None if hide else anchor_range,
        anchor_block_range=None if hide else anchor_blocks,
        backfilled_share=backfilled_share,
        excluding_backfilled=None if hide else excl,
        recency_rank=None if hide else recency_rank,
        every_year=None if hide else every_year,
        full_history_drawdown=full_dd,
        loss_budget_exceeded_count=None if hide else loss_budget_count,
        realised_independent_cagrs=realised,
        headline=headline,
        banners=tuple(banners),
        notes=tuple(notes),
        caveats=FIXED_CAVEATS,
        flags=tuple(flags),
        inputs={
            "target_rate": str(t_rate),
            "horizon_years": str(h),
            "as_of": request.as_of.isoformat(),
            "mode": request.mode.value,
            "year_basis": request.year_basis.value,
            "include_backfilled": str(request.include_backfilled),
            "source": meta.source,
            "instrument_kind": meta.instrument_kind.value,
            "path_resolution": resolution,
        },
    )
    _guard_wording(report.all_labels())
    return report


def _prepare_points(
    grid: Sequence[GridPoint],
    meta: SeriesMeta,
    request: FeasibilityRequest,
    *,
    steps_per_year: int,
    inflation_index: Sequence[Decimal] | None,
) -> tuple[list[GridPoint], list[Decimal] | None]:
    """Validate inputs, apply the point-in-time cut and (if requested) drop back-calculated history."""
    _validate_request(request)
    if steps_per_year < 1:
        raise InvalidInput("steps_per_year must be ≥ 1")
    keep = [i for i, g in enumerate(grid) if g.date <= request.as_of]  # point-in-time
    pts = [grid[i] for i in keep]
    cpi: list[Decimal] | None = None
    if inflation_index is not None:
        if len(inflation_index) != len(grid):
            raise InvalidInput("inflation_index must align one-to-one with the grid")
        cpi = [inflation_index[i] for i in keep]
        if any(not c.is_finite() or c <= 0 for c in cpi):
            raise InvalidInput("inflation index levels must be > 0")
    if not request.include_backfilled and meta.launch_date is not None:
        keep_from = next((i for i, g in enumerate(pts) if g.date >= meta.launch_date), len(pts))
        pts = pts[keep_from:]
        cpi = None if cpi is None else cpi[keep_from:]
    _validate_grid(pts)
    return pts, cpi


def _apply_inflation(windows: Sequence[Window], cpi: Sequence[Decimal], *, m: int) -> list[Window]:
    with engine_context():
        return [replace(w, below_inflation=w.ratio < cpi[w.start_index + m] / cpi[w.start_index]) for w in windows]


def _evidence_level(n_eff: int) -> EvidenceLevel:
    """§4.5 gate: < 2 independent periods → refuse; < 5 → LOW EVIDENCE (counts only); else percentages."""
    if n_eff < 2:
        return EvidenceLevel.REFUSED
    if n_eff < 5:
        return EvidenceLevel.LOW_EVIDENCE
    return EvidenceLevel.SUFFICIENT


def _frequencies(counts: Counts) -> Frequencies:
    n = Decimal(counts.n_windows)
    with engine_context():
        return Frequencies(
            hit_freq=Decimal(counts.hit_count) / n,
            loss_freq=Decimal(counts.loss_count) / n,
            flat_freq=Decimal(counts.flat_count) / n,
            below_inflation_freq=(
                Decimal(counts.below_inflation_count) / n if counts.below_inflation_count is not None else None
            ),
        )


def _compute_windows(
    pts: Sequence[GridPoint],
    meta: SeriesMeta,
    request: FeasibilityRequest,
    *,
    m: int,
    path: Sequence[tuple[date, Decimal]],
) -> list[Window]:
    """§4.4.2 overlapping windows i ∈ [0, M − m]; the hit test is Decimal and inclusive (F-2)."""
    h = request.horizon_years
    path_dates = [d for d, _ in path]

    def path_slice(a: date, b: date) -> Sequence[tuple[date, Decimal]]:
        lo = _bisect_left(path_dates, a)
        hi = _bisect_right(path_dates, b)
        seg = path[lo:hi]
        if not seg or seg[0][0] != a or seg[-1][0] != b:
            raise InvalidInput("daily path does not contain the grid dates")
        return seg

    windows: list[Window] = []
    with engine_context():
        one_plus_t = ONE + request.target_rate
        nominal_threshold = one_plus_t**h
        for i in range(0, len(pts) - m):
            g0, g1 = pts[i], pts[i + m]
            ratio = g1.value / g0.value
            if request.year_basis is YearBasis.NOMINAL:
                years = Decimal(h)
                threshold = nominal_threshold
            else:
                days = (g1.date - g0.date).days
                if days <= 0:
                    raise InvalidInput("non-positive window length under act365")
                years = Decimal(days) / Decimal(365)
                threshold = one_plus_t**years
            mdd, underwater = _mdd_path(path_slice(g0.date, g1.date))
            windows.append(
                Window(
                    start_index=i,
                    start_date=g0.date,
                    end_date=g1.date,
                    start_value=g0.value,
                    end_value=g1.value,
                    ratio=ratio,
                    cagr=ratio ** (ONE / years) - ONE,
                    hit=ratio >= threshold,
                    loss=ratio < ONE,
                    flat=ratio == ONE,
                    backfilled=meta.launch_date is not None and g0.date < meta.launch_date,
                    max_drawdown=mdd,
                    longest_underwater_months=underwater,
                    below_inflation=None,
                )
            )
    return windows


def _anchors(
    windows: Sequence[Window], *, m: int, big_m: int
) -> tuple[tuple[Anchor, ...], tuple[Decimal, Decimal], tuple[int, int]]:
    """§4.4.5 start-month sensitivity: non-overlapping windows from each anchor a ∈ [0, m − 1]."""
    anchors: list[Anchor] = []
    for a in range(m):
        idx = list(range(a, big_m - m + 1, m))
        if idx:
            anchors.append(Anchor(anchor=a, hits=sum(1 for i in idx if windows[i].hit), blocks=len(idx)))
    with engine_context():
        fracs = [Decimal(x.hits) / Decimal(x.blocks) for x in anchors]
    blocks = [x.blocks for x in anchors]
    return tuple(anchors), (min(fracs), max(fracs)), (min(blocks), max(blocks))


def _path_risk(windows: Sequence[Window], amount: Decimal | None, resolution: str) -> PathRisk:
    """§4.4.4 in-window drawdown percentiles (all windows and hit windows) with the ₹ translation."""
    mdds = [w.max_drawdown for w in windows]
    hit_mdds = [w.max_drawdown for w in windows if w.hit]
    mdd_all = _percentiles(mdds)
    mdd_hit = _percentiles(hit_mdds) if hit_mdds else None
    with engine_context():
        inr_all = money(amount * (ONE + mdd_all["p50"])) if amount is not None else None
        inr_hit = money(amount * (ONE + mdd_hit["p50"])) if (amount is not None and mdd_hit) else None
    return PathRisk(
        mdd_all=mdd_all,
        mdd_hit=mdd_hit,
        worst_mdd_in_hit_window=min(hit_mdds) if hit_mdds else None,
        longest_underwater_in_hit_window_months=(
            max(w.longest_underwater_months for w in windows if w.hit) if hit_mdds else None
        ),
        median_mdd_all_inr=inr_all,
        median_mdd_hit_inr=inr_hit,
        resolution=resolution,
    )


def _every_year(pts: Sequence[GridPoint], *, h: int, steps_per_year: int, n: int, t_rate: Decimal) -> EveryYear:
    """§4.4.6 R2: every one of the H consecutive 12-month returns ≥ T; plus the calendar-year streak."""
    count = 0
    with engine_context():
        one_plus_t = ONE + t_rate
        for i in range(n):
            if all(
                pts[i + steps_per_year * (k + 1)].value / pts[i + steps_per_year * k].value >= one_plus_t
                for k in range(h)
            ):
                count += 1
    return EveryYear(
        count=count,
        n_windows=n,
        longest_calendar_year_streak=_calendar_year_streak(pts, one_plus_t),
        label=(
            f"every one of the {h} consecutive 12-month periods met {_fmt_rate(t_rate)}: "
            f"{count} of {n} overlapping windows"
        ),
    )


def _messages(
    *,
    meta: SeriesMeta,
    request: FeasibilityRequest,
    level: EvidenceLevel,
    pts: Sequence[GridPoint],
    n: int,
    n_back: int,
    full_dd: FullHistoryDrawdown,
    recency_rank: Decimal,
    mdd_p50: Decimal,
    loss_budget_count: int | None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """§4.5 banners, RT-4/RT-8/RT-12 notes and flags."""
    h = request.horizon_years
    t_rate = request.target_rate
    flags: list[str] = []
    banners: list[str] = []
    notes: list[str] = []
    if level is EvidenceLevel.LOW_EVIDENCE:
        flags.append("LOW_EVIDENCE")
    if level is EvidenceLevel.REFUSED:
        flags.append("FREQUENCIES_REFUSED")
    if n_back:
        flags.append("BACKFILLED_HISTORY")
        banners.append(
            f"Back-calculated history: {n_back} of {n} windows start before the index launch date "
            f"({meta.launch_date.isoformat() if meta.launch_date else ''}). Figures are shown with and without them."
        )
    if any(g.suspect for g in pts):
        flags.append("SUSPECT_GRID_POINTS")
    if full_dd.depth > MAJOR_DRAWDOWN:
        banners.append("This history contains no major equity bear market; results may understate risk.")
    if pts[0].date > POST_CRASH_START:
        banners.append("History begins after the 2008–09 crash.")
    if not meta.net_of_fees:
        banners.append("Index TRI: gross of fees. Excludes TER, tracking error and taxes.")
    else:
        notes.append("Series is net of TER.")
    if t_rate > TARGET_CONFIRM_ABOVE:
        with engine_context():
            multiple = ((ONE + t_rate) ** h).quantize(Decimal("0.1"))
        notes.append(
            f"Please confirm the target: {_fmt_rate(t_rate)} p.a. for {_years(h)} means the amount must grow "
            f"about {multiple}-fold."
        )
    if recency_rank >= Decimal("0.9") and level is not EvidenceLevel.REFUSED:
        notes.append(f"The most recent {h}-year period was among the strongest 10 % in this history.")
    if (
        loss_budget_count is not None
        and request.loss_budget is not None
        and level is not EvidenceLevel.REFUSED
        and mdd_p50 < -request.loss_budget
    ):
        notes.append(
            f"History suggests this path exceeded your stated loss limit in {loss_budget_count} of {n} windows."
        )
    return tuple(flags), tuple(banners), tuple(notes)


def _counts(windows: Sequence[Window]) -> Counts:
    below = [w.below_inflation for w in windows]
    return Counts(
        n_windows=len(windows),
        hit_count=sum(1 for w in windows if w.hit),
        loss_count=sum(1 for w in windows if w.loss),
        flat_count=sum(1 for w in windows if w.flat),
        below_inflation_count=(sum(1 for b in below if b) if below and all(b is not None for b in below) else None),
    )


def _extreme(w: Window) -> ExtremeWindow:
    return ExtremeWindow(w.start_date, w.end_date, w.start_value, w.end_value, w.cagr)


def _bisect_left(xs: Sequence[date], x: date) -> int:
    lo, hi = 0, len(xs)
    while lo < hi:
        mid = (lo + hi) // 2
        if xs[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _bisect_right(xs: Sequence[date], x: date) -> int:
    lo, hi = 0, len(xs)
    while lo < hi:
        mid = (lo + hi) // 2
        if x < xs[mid]:
            hi = mid
        else:
            lo = mid + 1
    return lo


def _calendar_year_streak(pts: Sequence[GridPoint], one_plus_t: Decimal) -> int:
    """Longest run of consecutive calendar years whose Dec→Dec return ≥ T (December grid points only)."""
    year_end: dict[int, Decimal] = {}
    for g in pts:
        if g.date.month == 12:
            year_end[g.date.year] = g.value
    best = cur = 0
    with engine_context():
        for y in sorted(year_end):
            if y - 1 in year_end and year_end[y] / year_end[y - 1] >= one_plus_t:
                cur += 1
                best = max(best, cur)
            else:
                cur = 0
    return best


def _full_history_drawdown(path: Sequence[tuple[date, Decimal]]) -> FullHistoryDrawdown:
    """Deepest peak-to-trough fall; ties → earliest peak; recovery = first close ≥ the peak (risk §3)."""
    with engine_context():
        peak_i = 0
        best_depth = ZERO
        best_peak = best_trough = 0
        for i in range(1, len(path)):
            v = path[i][1]
            if v >= path[peak_i][1]:
                peak_i = i
                continue
            dd = v / path[peak_i][1] - ONE
            if dd < best_depth:
                best_depth, best_peak, best_trough = dd, peak_i, i
        recovery: date | None = None
        if best_depth < 0:
            peak_v = path[best_peak][1]
            for d, v in path[best_trough + 1 :]:
                if v >= peak_v:
                    recovery = d
                    break
    peak_d, trough_d = path[best_peak][0], path[best_trough][0]
    ongoing = best_depth < 0 and recovery is None
    if best_depth == 0:
        label = "No drawdown within available history."
    elif ongoing:
        months = _months_between(peak_d, path[-1][0])
        label = (
            f"Deepest fall within available history: {_fmt_pct(best_depth, 2)} from {peak_d.isoformat()} to "
            f"{trough_d.isoformat()}; underwater ≥ {months} months (ongoing)."
        )
    else:
        assert recovery is not None
        label = (
            f"Deepest fall within available history: {_fmt_pct(best_depth, 2)} from {peak_d.isoformat()} to "
            f"{trough_d.isoformat()}; back at the prior peak on {recovery.isoformat()}."
        )
    return FullHistoryDrawdown(
        depth=best_depth, peak_date=peak_d, trough_date=trough_d, recovery_date=recovery, ongoing=ongoing, label=label
    )


def _headline(
    *,
    meta: SeriesMeta,
    request: FeasibilityRequest,
    level: EvidenceLevel,
    pts: Sequence[GridPoint],
    counts: Counts,
    n_eff: int,
    anchor_range: tuple[Decimal, Decimal],
    every_year: EveryYear,
    mdd_hit: dict[str, Decimal] | None,
    inr_hit: Decimal | None,
    realised: Sequence[Decimal],
) -> str:
    h = request.horizon_years
    span = f"Over {meta.display_name or meta.series_id}, from {pts[0].date.isoformat()} to {pts[-1].date.isoformat()}"
    target = f"at least {_fmt_rate(request.target_rate)} p.a."
    if level is EvidenceLevel.REFUSED:
        periods = "period" if n_eff == 1 else "periods"
        verb = "is" if n_eff == 1 else "are"
        cagrs = ", ".join(_fmt_pct(c, 1) for c in realised)
        return (
            f"In this history there {verb} {n_eff} independent {h}-year {periods}; the realised CAGR was {cagrs}. "
            "Too few independent periods to report a historical frequency."
        )
    n = counts.n_windows
    if request.mode is Mode.EVERY_YEAR:
        met = (
            f"every one of the {h} consecutive 12-month periods met {_fmt_rate(request.target_rate)} "
            f"in {every_year.count} of {n}"
        )
    else:
        met = f"{target} over {_years(h)} was met in {counts.hit_count} of {n}"
    anchor = f"anchor range {_fmt_pct(anchor_range[0])}–{_fmt_pct(anchor_range[1])}"
    parts: list[str] = []
    if level is EvidenceLevel.LOW_EVIDENCE:
        parts.append("LOW EVIDENCE (counts only).")
        parts.append(f"{span}, {met} overlapping windows (about {n_eff} independent periods; {anchor}).")
    else:
        freq_count = every_year.count if request.mode is Mode.EVERY_YEAR else counts.hit_count
        with engine_context():
            freq = Decimal(freq_count) / Decimal(n)
        parts.append(
            f"{span}, {met} overlapping windows: {FREQUENCY_LABEL} {_fmt_pct(freq)} "
            f"(about {n_eff} independent periods; {anchor})."
        )
    parts.append(f"Money was lost in {counts.loss_count} of {n}.")
    if mdd_hit is not None and request.mode is Mode.CAGR:
        fall = f"In the windows that met it, the median fall along the way was {_fmt_pct(mdd_hit['p50'])}"
        if inr_hit is not None and request.amount_inr is not None:
            fall += f" ({_fmt_inr(request.amount_inr)} → {_fmt_inr(inr_hit)})"
        parts.append(fall + ".")
    return " ".join(parts)


# =====================================================================================================
# §4.4.7 Levers panel — deterministic arithmetic, no history claims
# =====================================================================================================


def levers(
    *,
    goal_inr: Decimal,
    horizon_years: int,
    target_rate: Decimal,
    cagr_p25: Decimal,
    cagr_p50: Decimal,
    cagr_p90: Decimal,
) -> tuple[LeverLine, ...]:
    """Lump sum PV = goal/(1+r)^H and monthly SIP = goal·i/((1+i)^n − 1), i = (1+r)^(1/12) − 1, n = 12H
    (end-of-month payments), at r = T, historical p25 and p50. A rate above the historical p90 is never shown."""
    if not goal_inr > 0:
        raise InvalidInput("goal_inr must be > 0")
    if not 1 <= horizon_years <= 20:
        raise InvalidInput("horizon_years must be in 1..20")
    lines: list[LeverLine] = []
    for basis, r in (("target", target_rate), ("historical p25", cagr_p25), ("historical p50", cagr_p50)):
        if r > cagr_p90:
            continue
        if r <= -ONE:
            raise InvalidInput("rate ≤ −100 %")
        with engine_context():
            growth = (ONE + r) ** horizon_years
            lump = goal_inr / growth
            n = 12 * horizon_years
            i = (ONE + r) ** (ONE / Decimal(12)) - ONE
            sip = goal_inr / Decimal(n) if i == 0 else goal_inr * i / ((ONE + i) ** n - ONE)
        lines.append(
            LeverLine(
                basis=basis,
                rate=r,
                lump_sum_inr=money(lump),
                monthly_sip_inr=money(sip),
                label=f"At {_fmt_rate(r)} p.a. ({basis}): lump sum {_fmt_inr(lump)} or monthly SIP {_fmt_inr(sip)}.",
            )
        )
    _guard_wording([x.label for x in lines])
    return tuple(lines)
