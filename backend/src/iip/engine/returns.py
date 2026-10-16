"""Return measures (calculation-methodology.md §2.1–§2.7, §2.11, §2.12).

* Day basis for every annualised figure: ACT/365F on actual calendar days.
* Rule A1: under 365 days the headline is the absolute return; annualised figures carry
  ``ANNUALISED_FROM_SHORT_PERIOD``.
* XIRR: deterministic grid scan + Brent in float64, then verified in Decimal (§2.6).
* NAV-based returns are already net of scheme expenses — nothing in this module may subtract an
  expense ratio (§2.8; enforced by ``tests/unit/test_returns.py``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from typing import Any

from iip.engine.dates import DayCount, days_between
from iip.engine.errors import InsufficientHistory, InvalidInput, MissingDistributionData, NumericalError
from iip.engine.money import ONE, ZERO, D, engine_context, from_float, rate_store


def brentq(*args: Any, **kwargs: Any) -> Any:  # lazy scipy (A05 / RC-5): loaded on first use, not at app start
    from scipy.optimize import brentq as solver  # noqa: PLC0415

    return solver(*args, **kwargs)


def minimize_scalar(*args: Any, **kwargs: Any) -> Any:  # lazy scipy (A05 / RC-5): loaded on first use, not at app start
    from scipy.optimize import minimize_scalar as solver  # noqa: PLC0415

    return solver(*args, **kwargs)


ANNUALISED_FROM_SHORT_PERIOD = "ANNUALISED_FROM_SHORT_PERIOD"
DAYS_PER_YEAR = 365

# §2.6 step 3: the fixed bracket-scan grid (rates as decimal fractions).
XIRR_GRID: tuple[Decimal, ...] = tuple(
    D(x)
    for x in (
        "-0.99", "-0.9", "-0.75", "-0.5", "-0.25", "-0.1", "0", "0.05", "0.1",
        "0.2", "0.35", "0.5", "0.75", "1", "2", "5", "10",
    )
)  # fmt: skip
XIRR_XTOL = 1e-12
XIRR_MAXITER = 200
XIRR_VERIFY_REL_TOL = Decimal("1e-9")


def _require_positive(name: str, value: Decimal) -> Decimal:
    v = D(value)
    if v <= 0:
        raise InvalidInput(f"{name} must be > 0, got {v}")
    return v


def _require_non_negative(name: str, value: Decimal) -> Decimal:
    v = D(value)
    if v < 0:
        raise InvalidInput(f"{name} must be ≥ 0, got {v}")
    return v


def _held_days(start: date, end: date) -> int:
    if end < start:
        raise InvalidInput(f"end {end} before start {start}")
    days = days_between(start, end)
    if days == 0:
        raise InvalidInput("holding period of 0 days cannot be annualised")
    return days


def _short_warnings(days: int) -> tuple[str, ...]:
    return (ANNUALISED_FROM_SHORT_PERIOD,) if days < DAYS_PER_YEAR else ()


# ---------------------------------------------------------------- §2.1 absolute return


@dataclass(frozen=True, slots=True)
class AbsoluteReturn:
    value: Decimal
    gain: Decimal
    v_start: Decimal
    v_end: Decimal
    formula_id: str = "ABS_RETURN@1"


def absolute_return(v_start: Decimal, v_end: Decimal) -> AbsoluteReturn:
    """``V_end / V_start − 1`` for one lump sum with no intermediate flows."""
    v0 = _require_positive("v_start", v_start)
    v1 = _require_non_negative("v_end", v_end)
    with engine_context():
        return AbsoluteReturn(value=v1 / v0 - ONE, gain=v1 - v0, v_start=v0, v_end=v1)


# ---------------------------------------------------------------- §2.2 simple annualised


@dataclass(frozen=True, slots=True)
class AnnualisedReturn:
    value: Decimal
    days: int
    start: date
    end: date
    v_start: Decimal
    v_end: Decimal
    formula_id: str
    day_count: DayCount = DayCount.ACT_365F
    warnings: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()


def simple_annualised_return(v_start: Decimal, v_end: Decimal, start: date, end: date) -> AnnualisedReturn:
    """``R_abs × 365 / d``. A labelled secondary figure only (money-market quoting convention)."""
    days = _held_days(start, end)
    absolute = absolute_return(v_start, v_end)
    with engine_context():
        value = absolute.value * Decimal(DAYS_PER_YEAR) / Decimal(days)
    return AnnualisedReturn(
        value=value,
        days=days,
        start=start,
        end=end,
        v_start=absolute.v_start,
        v_end=absolute.v_end,
        formula_id="SIMPLE_ANN@1",
        warnings=_short_warnings(days),
        flags=("SECONDARY_FIGURE",),
    )


# ---------------------------------------------------------------- §2.4 CAGR


def cagr(v_start: Decimal, v_end: Decimal, start: date, end: date) -> AnnualisedReturn:
    """``(V_end / V_start)^(365 / d) − 1`` on actual days (never whole years)."""
    days = _held_days(start, end)
    absolute = absolute_return(v_start, v_end)
    with engine_context():
        ratio = absolute.v_end / absolute.v_start
        value = ratio ** (Decimal(DAYS_PER_YEAR) / Decimal(days)) - ONE if ratio != 0 else -ONE
    return AnnualisedReturn(
        value=value,
        days=days,
        start=start,
        end=end,
        v_start=absolute.v_start,
        v_end=absolute.v_end,
        formula_id="CAGR@1",
        warnings=_short_warnings(days),
        flags=("NON_HEADLINE",) if days < DAYS_PER_YEAR else (),
    )


# ---------------------------------------------------------------- §2.3 Rule A1 guard


class HeadlineKind(StrEnum):
    ABSOLUTE = "ABSOLUTE"
    CAGR = "CAGR"


@dataclass(frozen=True, slots=True)
class HeadlineReturn:
    kind: HeadlineKind
    headline: Decimal
    absolute: Decimal
    gain: Decimal
    days: int
    start: date
    end: date
    cagr: Decimal | None
    simple_annualised: Decimal | None
    compound_annualised: Decimal | None
    formula_id: str = "HEADLINE_A1@1"
    day_count: DayCount = DayCount.ACT_365F
    warnings: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()


def headline_return(v_start: Decimal, v_end: Decimal, start: date, end: date) -> HeadlineReturn:
    """Rule A1: below 365 days headline the absolute return; from 365 days headline CAGR.

    Under 365 days the annualised numbers are still returned for a details panel, but only as
    ``simple_annualised`` / ``compound_annualised`` with ``ANNUALISED_FROM_SHORT_PERIOD``.
    """
    days = _held_days(start, end)
    absolute = absolute_return(v_start, v_end)
    compound = cagr(v_start, v_end, start, end)
    simple = simple_annualised_return(v_start, v_end, start, end)
    if days < DAYS_PER_YEAR:
        return HeadlineReturn(
            kind=HeadlineKind.ABSOLUTE,
            headline=absolute.value,
            absolute=absolute.value,
            gain=absolute.gain,
            days=days,
            start=start,
            end=end,
            cagr=None,
            simple_annualised=simple.value,
            compound_annualised=compound.value,
            warnings=(ANNUALISED_FROM_SHORT_PERIOD,),
            flags=("HEADLINE_NOT_ANNUALISED",),
        )
    return HeadlineReturn(
        kind=HeadlineKind.CAGR,
        headline=compound.value,
        absolute=absolute.value,
        gain=absolute.gain,
        days=days,
        start=start,
        end=end,
        cagr=compound.value,
        simple_annualised=simple.value,
        compound_annualised=compound.value,
    )


# ---------------------------------------------------------------- §2.5 TWR


@dataclass(frozen=True, slots=True)
class TwrObservation:
    """Valuation at end of ``on`` *before* the day's external flow; ``flow`` > 0 is a contribution."""

    on: date
    value_pre: Decimal
    flow: Decimal


@dataclass(frozen=True, slots=True)
class TwrResult:
    value: Decimal
    sub_period_returns: tuple[Decimal, ...]
    period_ends: tuple[date, ...]
    excluded_periods: tuple[date, ...]
    start: date
    end: date
    formula_id: str = "TWR@1"
    flags: tuple[str, ...] = ()


def twr(observations: Sequence[TwrObservation]) -> TwrResult:
    """Daily-linked TWR with flows at end of day: ``r_t = V_t^pre / V_{t−1}^post − 1``.

    A zero ``V_{t−1}^post`` (full exit then re-entry) restarts the chain: that period is excluded
    and flagged ``TWR_CHAIN_RESTARTED``.
    """
    obs = sorted(observations, key=lambda o: o.on)
    if len(obs) < 2:
        raise InsufficientHistory("TWR needs at least 2 valuations")
    for prev, cur in pairwise(obs):
        if prev.on == cur.on:
            raise InvalidInput(f"duplicate valuation date {cur.on}")
    returns: list[Decimal] = []
    ends: list[date] = []
    excluded: list[date] = []
    with engine_context():
        prev_post: Decimal | None = None
        for o in obs:
            pre = _require_non_negative(f"value_pre on {o.on}", o.value_pre)
            post = pre + D(o.flow)
            if post < 0:
                raise InvalidInput(f"negative post-flow value on {o.on}: long-only holdings cannot go below 0")
            if prev_post is not None:
                if prev_post == 0:
                    if pre != 0:
                        raise InvalidInput(f"value {pre} on {o.on} appeared from a zero balance without a flow")
                    excluded.append(o.on)
                else:
                    returns.append(pre / prev_post - ONE)
                    ends.append(o.on)
            prev_post = post
        if not returns:
            raise InsufficientHistory("no sub-period with a non-zero opening value")
        growth = ONE
        for r in returns:
            growth *= ONE + r
        value = growth - ONE
    return TwrResult(
        value=value,
        sub_period_returns=tuple(returns),
        period_ends=tuple(ends),
        excluded_periods=tuple(excluded),
        start=obs[0].on,
        end=obs[-1].on,
        flags=("TWR_CHAIN_RESTARTED",) if excluded else (),
    )


# ---------------------------------------------------------------- §2.6 XIRR


@dataclass(frozen=True, slots=True)
class CashFlow:
    """Sign convention (Excel XIRR): investment < 0, receipt / current value > 0."""

    on: date
    amount: Decimal


class XirrOutcome(StrEnum):
    SOLVED = "SOLVED"
    NO_SOLUTION = "NO_SOLUTION"
    MULTIPLE_ROOTS = "MULTIPLE_ROOTS"
    NOT_DETERMINABLE = "NOT_DETERMINABLE"  # RT-28: roots hidden inside one grid cell (no sign change at its ends)


@dataclass(frozen=True, slots=True)
class XirrResult:
    outcome: XirrOutcome
    rate: Decimal | None
    roots: tuple[Decimal, ...]
    flows: tuple[CashFlow, ...]
    span_days: int
    sign_changes: int
    xnpv_at_rate: Decimal | None
    headline_allowed: bool
    reason: str | None
    formula_id: str = "XIRR@1"
    day_count: DayCount = DayCount.ACT_365F
    warnings: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()

    @property
    def stored_rate(self) -> Decimal | None:
        """§2.6 step 6: storage quantum 0.0001 % (HALF_EVEN)."""
        return None if self.rate is None else rate_store(self.rate)


def _net_and_sort(flows: Sequence[CashFlow]) -> tuple[CashFlow, ...]:
    by_date: dict[date, list[Decimal]] = {}
    for f in flows:
        if not isinstance(f.on, date):
            raise InvalidInput(f"invalid cash-flow date {f.on!r}")
        by_date.setdefault(f.on, []).append(D(f.amount))
    netted: list[CashFlow] = []
    with engine_context():
        for on in sorted(by_date):
            total = sum(sorted(by_date[on]), ZERO)  # sorted → order-invariant summation
            if total != 0:
                netted.append(CashFlow(on, total))
    return tuple(netted)


def _xnpv_decimal(flows: Sequence[CashFlow], rate: Decimal) -> Decimal:
    d0 = flows[0].on
    with engine_context():
        base = ONE + rate
        total = ZERO
        for f in flows:
            t = Decimal(days_between(d0, f.on)) / Decimal(DAYS_PER_YEAR)
            total += f.amount / base**t
        return total


def _xnpv_float(flows: Sequence[CashFlow]) -> Callable[[float], float]:
    d0 = flows[0].on
    cfs = [float(f.amount) for f in flows]
    ts = [days_between(d0, f.on) / DAYS_PER_YEAR for f in flows]

    def f(r: float) -> float:
        return float(sum(cf * (1.0 + r) ** (-t) for cf, t in zip(cfs, ts, strict=True)))

    return f


def _sign_changes(flows: Sequence[CashFlow]) -> int:
    signs = [1 if f.amount > 0 else -1 for f in flows]
    return sum(1 for a, b in pairwise(signs) if a != b)


def _no_solution(
    flows: tuple[CashFlow, ...], span: int, changes: int, reason: str, warnings: tuple[str, ...] = ()
) -> XirrResult:
    return XirrResult(
        outcome=XirrOutcome.NO_SOLUTION,
        rate=None,
        roots=(),
        flows=flows,
        span_days=span,
        sign_changes=changes,
        xnpv_at_rate=None,
        headline_allowed=False,
        reason=reason,
        warnings=warnings,
        flags=("IRR_NOT_MEANINGFUL",),
    )


def _hidden_roots(
    f: Callable[[float], float], netted: Sequence[CashFlow], signs: Sequence[int], changes: int, tolerance: Decimal
) -> tuple[list[tuple[Decimal, Decimal]], list[Decimal], list[tuple[Decimal, Decimal]]]:
    """RT-28: roots inside one grid cell, where XNPV has the same sign at both ends (no bracket).

    Only possible with ≥ 2 sign changes (Descartes' rule of signs, exponential-sum form). For each such cell, find the
    interior extremum of XNPV; if XNPV crosses zero there, split the cell at it into two brackets; if it touches zero
    (a double root), that point is a root. Returns (new brackets, new roots, the cells where roots were hidden).
    """
    brackets: list[tuple[Decimal, Decimal]] = []
    roots: list[Decimal] = []
    hidden: list[tuple[Decimal, Decimal]] = []
    if changes < 2:
        return brackets, roots, hidden
    for i in range(len(XIRR_GRID) - 1):
        if signs[i] == 0 or signs[i] != signs[i + 1]:
            continue
        left, right, sgn = XIRR_GRID[i], XIRR_GRID[i + 1], signs[i]
        ext = minimize_scalar(lambda r, sgn=sgn: sgn * f(r), bounds=(float(left), float(right)), method="bounded",
                              options={"xatol": XIRR_XTOL, "maxiter": XIRR_MAXITER})  # fmt: skip
        x_star = float(ext.x)
        if sgn * f(x_star) < 0:
            brackets.extend([(left, from_float(x_star)), (from_float(x_star), right)])
            hidden.append((left, right))
        elif abs(_xnpv_decimal(netted, from_float(x_star))) <= tolerance:  # tangent (double) root
            roots.append(from_float(x_star))
            hidden.append((left, right))
    return brackets, roots, hidden


def xirr(flows: Sequence[CashFlow]) -> XirrResult:
    """Excel-semantics XIRR (ACT/365F from the earliest date), per the §2.6 algorithm.

    1. Validate (≥ 2 flows), net same-date flows, drop zero nets, sort by date. Without both an
       outflow and an inflow → ``NO_SOLUTION``.
    2. Count sign changes (Descartes: exactly one ⇒ at most one root above −100 %).
    3. Scan ``XIRR_GRID`` in Decimal. A grid point with ``|XNPV| ≤ 1e-9·Σ|CF|`` is itself a root;
       a strict sign change between adjacent non-root points is a bracket.
       0 candidates → ``NO_SOLUTION``; > 1 → ``MULTIPLE_ROOTS`` (all solved, none headlined).
    4. Solve each bracket with ``brentq`` (xtol 1e-12, maxiter 200) in float64.
    5. Verify every root in Decimal: ``|XNPV| ≤ 1e-9·Σ|CF|`` or raise ``NumericalError``.
    7. Span < 365 days → ``ANNUALISED_FROM_SHORT_PERIOD`` and no headline (Rule A1).
    """
    if len(flows) < 2:
        raise InvalidInput("XIRR needs at least 2 cash flows")
    netted = _net_and_sort(flows)
    span = days_between(netted[0].on, netted[-1].on) if netted else 0
    warnings = _short_warnings(span) if span > 0 else ()
    if len(netted) < 2 or not any(f.amount < 0 for f in netted) or not any(f.amount > 0 for f in netted):
        return _no_solution(
            netted, span, _sign_changes(netted), "need at least one outflow and one inflow after netting", warnings
        )
    changes = _sign_changes(netted)
    with engine_context():
        tolerance = XIRR_VERIFY_REL_TOL * sum((abs(f.amount) for f in netted), ZERO)

    grid_roots: list[Decimal] = []
    brackets: list[tuple[Decimal, Decimal]] = []
    signs: list[int] = []
    for g in XIRR_GRID:
        v = _xnpv_decimal(netted, g)
        if abs(v) <= tolerance:
            grid_roots.append(g)
            signs.append(0)
        else:
            signs.append(1 if v > 0 else -1)
    for i in range(len(XIRR_GRID) - 1):
        if signs[i] != 0 and signs[i + 1] != 0 and signs[i] != signs[i + 1]:
            brackets.append((XIRR_GRID[i], XIRR_GRID[i + 1]))

    f = _xnpv_float(netted)
    # RT-28: two roots can hide inside ONE grid cell (same sign at both ends) — see _hidden_roots.
    extra_brackets, extra_roots, hidden = _hidden_roots(f, netted, signs, changes, tolerance)
    brackets.extend(extra_brackets)
    grid_roots.extend(extra_roots)

    if not grid_roots and not brackets:
        return _no_solution(netted, span, changes, "no root in [-99 %, 1000 %]: IRR not meaningful", warnings)

    roots: list[Decimal] = list(grid_roots)
    for lo, hi in brackets:
        try:
            raw = float(brentq(f, float(lo), float(hi), xtol=XIRR_XTOL, maxiter=XIRR_MAXITER))
        except (ValueError, RuntimeError) as exc:
            raise NumericalError(f"brentq failed on bracket [{lo}, {hi}]: {exc}") from exc
        roots.append(from_float(raw))
    roots.sort()

    residuals: list[Decimal] = []
    for r in roots:
        residual = _xnpv_decimal(netted, r)
        if abs(residual) > tolerance:
            raise NumericalError(f"XIRR root {r} failed Decimal verification: |XNPV| = {abs(residual)}")
        residuals.append(residual)

    if hidden:
        cells = ", ".join(f"[{lo}, {hi}]" for lo, hi in hidden)
        return XirrResult(
            outcome=XirrOutcome.NOT_DETERMINABLE,
            rate=None,
            roots=tuple(roots),
            flows=netted,
            span_days=span,
            sign_changes=changes,
            xnpv_at_rate=None,
            headline_allowed=False,
            reason=f"IRR not determinable: more than one root inside the scan cell(s) {cells}; "
            "show TWR and absolute ₹ P&L instead",
            warnings=warnings,
            flags=("IRR_NOT_DETERMINABLE",),
        )
    if len(roots) > 1:
        return XirrResult(
            outcome=XirrOutcome.MULTIPLE_ROOTS,
            rate=None,
            roots=tuple(roots),
            flows=netted,
            span_days=span,
            sign_changes=changes,
            xnpv_at_rate=None,
            headline_allowed=False,
            reason="multiple IRRs: show TWR and absolute ₹ P&L instead",
            warnings=warnings,
            flags=("MULTIPLE_IRR",),
        )
    return XirrResult(
        outcome=XirrOutcome.SOLVED,
        rate=roots[0],
        roots=(roots[0],),
        flows=netted,
        span_days=span,
        sign_changes=changes,
        xnpv_at_rate=residuals[0],
        headline_allowed=not warnings,
        reason=None,
        warnings=warnings,
    )


# ---------------------------------------------------------------- §2.7 total return (IDCW)


class PlanOption(StrEnum):
    GROWTH = "GROWTH"
    IDCW = "IDCW"


@dataclass(frozen=True, slots=True)
class Distribution:
    ex_date: date
    amount_per_unit: Decimal
    ex_nav: Decimal


@dataclass(frozen=True, slots=True)
class TotalReturn:
    value: Decimal
    price_return: Decimal
    reinvestment_factor: Decimal
    option: PlanOption
    start: date
    end: date
    distributions: tuple[Distribution, ...]
    distribution_tax_rate: Decimal
    formula_id: str = "TR_IDCW@1"
    flags: tuple[str, ...] = ()


def total_return(
    *,
    nav_start: Decimal,
    nav_end: Decimal,
    start: date,
    end: date,
    option: PlanOption,
    distributions: Sequence[Distribution] | None,
    distribution_tax_rate: Decimal = ZERO,
) -> TotalReturn:
    """``(NAV_end / NAV_start) × Π(1 + D_t(1−τ) / NAV_ex,t) − 1``.

    ``distributions=None`` means the distribution feed is unavailable: for IDCW this raises
    ``MissingDistributionData`` — never a price-only fallback.  ``[]`` means "feed present, none paid".
    """
    n0 = _require_positive("nav_start", nav_start)
    n1 = _require_positive("nav_end", nav_end)
    if end < start:
        raise InvalidInput(f"end {end} before start {start}")
    tau = D(distribution_tax_rate)
    if not ZERO <= tau < ONE:
        raise InvalidInput(f"distribution_tax_rate must be in [0, 1), got {tau}")
    if option is PlanOption.IDCW and distributions is None:
        raise MissingDistributionData("IDCW option needs the distribution feed; price-only return is not a return")
    dists = tuple(sorted(distributions or (), key=lambda x: x.ex_date))
    if option is PlanOption.GROWTH and dists:
        raise InvalidInput("Growth option does not pay distributions")
    with engine_context():
        factor = ONE
        for dist in dists:
            if not start < dist.ex_date <= end:
                raise InvalidInput(f"ex-date {dist.ex_date} outside ({start}, {end}]")
            amount = _require_positive("amount_per_unit", dist.amount_per_unit)
            ex_nav = _require_positive("ex_nav", dist.ex_nav)
            factor *= ONE + amount * (ONE - tau) / ex_nav
        price_ratio = n1 / n0
        value = price_ratio * factor - ONE
        price_return = price_ratio - ONE
    return TotalReturn(
        value=value,
        price_return=price_return,
        reinvestment_factor=factor,
        option=option,
        start=start,
        end=end,
        distributions=dists,
        distribution_tax_rate=tau,
        flags=("AFTER_TAX_REINVESTMENT",) if tau > 0 else (),
    )


# ---------------------------------------------------------------- §2.11 Fisher


@dataclass(frozen=True, slots=True)
class RealReturn:
    value: Decimal
    nominal: Decimal
    inflation: Decimal
    approximation: Decimal
    formula_id: str = "FISHER@1"
    flags: tuple[str, ...] = ()


def real_return(nominal: Decimal, inflation: Decimal) -> RealReturn:
    """``(1 + r_nom) / (1 + π) − 1``. ``π`` must be horizon-matched with ``r_nom`` (caller's duty).

    ``approximation`` (``r_nom − π``) is a labelled approximation only — never the real return.
    """
    r = D(nominal)
    pi = D(inflation)
    if r < -ONE:
        raise InvalidInput(f"nominal return below −100 %: {r}")
    if pi <= -ONE:
        raise InvalidInput(f"inflation must be > −100 %: {pi}")
    with engine_context():
        value = (ONE + r) / (ONE + pi) - ONE
        approx = r - pi
    return RealReturn(
        value=value,
        nominal=r,
        inflation=pi,
        approximation=approx,
        flags=("REAL_LOSS",) if value < 0 else (),
    )


# ---------------------------------------------------------------- §2.12 after-tax (interface)


@dataclass(frozen=True, slots=True)
class AfterTaxReturn:
    cost: Decimal
    proceeds: Decimal
    tax_amount: Decimal
    gain_pre_tax: Decimal
    gain_after_tax: Decimal
    absolute_after_tax: Decimal
    cagr_after_tax: Decimal | None
    days: int | None
    formula_id: str = "AFTER_TAX@1"
    warnings: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()


def after_tax_return(
    cost: Decimal,
    proceeds: Decimal,
    *,
    tax_amount: Decimal,
    start: date | None = None,
    end: date | None = None,
) -> AfterTaxReturn:
    """After-tax return from an already-computed tax amount (the tax engine computes ``tax_amount``).

    With ``start``/``end`` the after-tax CAGR is added (Rule A1 warning under 365 days).  Dated,
    multi-year tax flows (e.g. FD tax on accrual) belong in ``xirr`` with the tax as outflows.
    """
    c = _require_positive("cost", cost)
    p = _require_non_negative("proceeds", proceeds)
    tax = _require_non_negative("tax_amount", tax_amount)
    if (start is None) != (end is None):
        raise InvalidInput("start and end must be given together")
    with engine_context():
        net = p - tax
        if net < 0:
            raise InvalidInput(f"tax {tax} exceeds proceeds {p}")
        gain = p - c
        gain_after = gain - tax
        absolute = net / c - ONE
    cagr_value: Decimal | None = None
    days: int | None = None
    warnings: tuple[str, ...] = ()
    if start is not None and end is not None:
        annual = cagr(c, net, start, end)
        cagr_value, days, warnings = annual.value, annual.days, annual.warnings
    return AfterTaxReturn(
        cost=c,
        proceeds=p,
        tax_amount=tax,
        gain_pre_tax=gain,
        gain_after_tax=gain_after,
        absolute_after_tax=absolute,
        cagr_after_tax=cagr_value,
        days=days,
        warnings=warnings,
    )
