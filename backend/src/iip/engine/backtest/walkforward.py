"""Walk-forward backtest of a pre-registered signal against its benchmark (research-backtest-method.md §4-§5, WP B05).

Pure and deterministic: no clock, IO or unseeded randomness. Money, units and NAVs are ``Decimal``; only the OOS edge
statistics handed to the gates are floats (as ``stats_gates``).

Timeline per decision (research-backtest-method.md §4.1, design-evidence-first.md §4.3):

* Decisions are taken at the last NAV observation of a calendar month (every ``decision_every_months`` months). The
  final month of the panel is never a decision month (it may be incomplete).
* ``lag`` (observations): the decision at observation ``i`` may use only NAVs at index ``≤ i − lag``. The rule never
  receives the panel; it receives a month-end grid whose month ``j`` value is ``NAV[decision_j − lag]``.
* ``fill_rule.nav_offset`` (observations, ≥ 1): orders fill at ``NAV[i + nav_offset]``, strictly after the decision.
  When an order set contains a sale, every purchase in it waits ``fill_rule.switch_cash_gap`` further observations
  (MF switch T+3: the money is out of the market).
* ``purge`` and ``embargo`` (decision periods): at each OOS origin ``k`` the window available to any parameter
  estimation is ``[0, k − purge − embargo]``; the existing ``assert_no_leakage`` invariant is checked at every origin.
  Pre-registered rules have literature-fixed parameters, so that window is recorded, never fitted on.

``lag``, ``purge``, ``embargo`` and ``fill_rule`` are **mandatory with no default** (design-evidence-first.md §6.2:
library defaults such as lag 0 / purge 0 are banned).

Accounting: each portfolio (strategy and benchmark) is an A17 ``LedgerState`` (FIFO lots, Decimal). It is marked at
every decision observation with the true NAV of that day (a valuation, never an input to the decision). The period
return is time-weighted: ``r_k = V_{k+1} / (V_k + c_k) − 1`` where ``c_k`` is the contribution added at decision k.
The OOS edge of period k is ``r_k(strategy) − r_k(benchmark)`` after costs, before tax; tax enters the G6/G7 terminal
comparison through ``terminal_valuation`` (liquidated, exemption already used: the conservative bound).

The **vault** (the last max(fraction × periods, min_months) of the history) is cut off *before* the walk-forward runs,
so no vault NAV can reach a rule unless ``run_vault`` is called explicitly (G11, once).

Date windows (TA-2):

* Every window is evaluated half-open, ``start ≤ d < end_exclusive``. Spec files declare windows by their *last day*
  (``end: 2013-03-31`` then ``start: 2013-04-01``, the rules-file convention), so ``end_exclusive = end + 1 day``;
  windows of one kind may not overlap (regimes; cost rows of one component, side and tax class), else one date
  would be attributed twice or priced ambiguously.
* Panel dates are IST calendar dates. ``align_panel`` converts offset-aware timestamps to IST (never truncating them)
  and refuses naive ones; ``NavPanel`` refuses any ``datetime`` outright.
* Undated rows are excluded from a backtest and counted; a role, window or alignment left empty after filtering
  raises ``InsufficientHistory`` naming what removed the rows, never an empty panel.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from itertools import combinations, pairwise
from types import MappingProxyType

import numpy as np

from iip.engine.backtest.ledger import (
    CostBasisPolicy,
    LedgerState,
    TerminalValuation,
    TradeCost,
    buy,
    sell,
    terminal_valuation,
)
from iip.engine.backtest.stats_gates import NormalDist, hac_t_stat, newey_west_lag
from iip.engine.backtest.tax_lots import TaxRateTable
from iip.engine.errors import InsufficientHistory, InvalidInput, NumericalError
from iip.engine.forecasting.validation import LeakageError, assert_no_leakage
from iip.engine.money import ONE, UNITS_QUANTUM, ZERO, D, engine_context, from_float
from iip.engine.stats.series_grid import to_ist_date

__all__ = [
    "CANARY_MAX_MEAN_SCORE",
    "FORMULA_ID",
    "NO_STRESS",
    "R_COST_RULES_MISSING",
    "W_EXIT_LOAD_NOT_MODELLED",
    "AlignedPanel",
    "BacktestSetup",
    "CanaryResult",
    "CostRateRow",
    "CostStress",
    "FillRule",
    "LeakageError",
    "MfCostSchedule",
    "NavPanel",
    "PeriodRecord",
    "PortfolioView",
    "RegimeEdge",
    "RegimeSpec",
    "RuleFn",
    "RuleSpec",
    "SideResult",
    "VaultSpec",
    "WalkForwardConfig",
    "WalkForwardResult",
    "align_panel",
    "build_rule",
    "decision_indices",
    "max_drawdown",
    "month_end_indices",
    "run_vault",
    "run_walk_forward",
    "shuffle_canary",
    "split_vault",
]

FORMULA_ID = "BT-WALKFORWARD@1"
R_COST_RULES_MISSING = "cost_rules_missing"
W_EXIT_LOAD_NOT_MODELLED = "exit_load_not_modelled"

#: Shuffle canary (research-backtest-method.md §4.2): on permuted or pure-noise data the mean score Φ(HAC t) of the
#: OOS edge across replicates must stay below this design parameter. With zero skill the score is about
#: Uniform(0, 1) (mean 0.5); the HAC variance (Newey-West plug-in lag) keeps persistent edges, such as a reserve held
#: for years, from looking significant. A leaky pipeline scores near 1.
CANARY_MAX_MEAN_SCORE = 0.75
_WEIGHT_TOLERANCE = Decimal("1e-20")
_N = NormalDist()
_DAY = timedelta(days=1)


def _end_exclusive(last_day: date | None) -> date | None:
    """Half-open bound for a window declared by its last day (``None`` = open-ended)."""
    return None if last_day is None else last_day + _DAY


def _in_window(d: date, start: date | None, end_exclusive: date | None) -> bool:
    """``start ≤ d < end_exclusive`` (either bound may be open)."""
    return (start is None or d >= start) and (end_exclusive is None or d < end_exclusive)


def _overlap(a: tuple[date | None, date | None], b: tuple[date | None, date | None]) -> bool:
    """Do two half-open windows ``[start, end_exclusive)`` share a date?"""
    (a0, a1), (b0, b1) = a, b
    return (a1 is None or b0 is None or b0 < a1) and (b1 is None or a0 is None or a0 < b1)


def _check_bound(name: str, d: object) -> None:
    if d is not None and (isinstance(d, datetime) or not isinstance(d, date)):
        raise InvalidInput(f"{name} must be a calendar date, got {type(d).__name__}")


# ================================================================================================ configuration


def _strict_int(name: str, v: object, minimum: int) -> int:
    if type(v) is not int:
        raise InvalidInput(f"{name} must be an int (got {type(v).__name__})")
    if v < minimum:
        raise InvalidInput(f"{name} must be ≥ {minimum} (got {v})")
    return v


@dataclass(frozen=True, kw_only=True)
class FillRule:
    """How an order fills. No defaults: every field is pre-registered in the signal spec."""

    name: str
    nav_offset: int  # observations after the decision observation; ≥ 1 (fill strictly after the decision)
    switch_cash_gap: int  # extra observations a purchase waits when the order set contains a sale (MF T+3)

    def __post_init__(self) -> None:
        if not self.name:
            raise InvalidInput("fill_rule needs a name")
        _strict_int("fill_rule.nav_offset", self.nav_offset, 1)
        _strict_int("fill_rule.switch_cash_gap", self.switch_cash_gap, 0)


@dataclass(frozen=True, kw_only=True)
class WalkForwardConfig:
    """``lag``, ``purge``, ``embargo`` and ``fill_rule`` are mandatory arguments with no default (EF §6.2)."""

    lag: int
    purge: int
    embargo: int
    fill_rule: FillRule

    def __post_init__(self) -> None:
        _strict_int("lag", self.lag, 0)
        _strict_int("purge", self.purge, 1)
        _strict_int("embargo", self.embargo, 0)
        if not isinstance(self.fill_rule, FillRule):
            raise InvalidInput("fill_rule must be a FillRule")


@dataclass(frozen=True, kw_only=True)
class VaultSpec:
    fraction: Decimal  # e.g. 0.20
    min_months: int  # e.g. 36

    def __post_init__(self) -> None:
        if not (ZERO < D(self.fraction) < ONE):
            raise InvalidInput("vault fraction must be in (0, 1)")
        _strict_int("vault.min_months", self.min_months, 1)


@dataclass(frozen=True, kw_only=True)
class RegimeSpec:
    """A pre-declared sub-period. Edges are attributed by the period's start date; only pre-vault periods count.

    ``end`` is the regime's last day as declared in the spec; membership is the half-open ``[start, end + 1 day)``.
    """

    regime_id: str
    start: date | None
    end: date | None

    def __post_init__(self) -> None:
        _check_bound(f"regime {self.regime_id}: start", self.start)
        _check_bound(f"regime {self.regime_id}: end", self.end)
        if self.start is not None and self.end is not None and self.end < self.start:
            raise InvalidInput(f"regime {self.regime_id}: end {self.end} is before start {self.start}")

    @property
    def window(self) -> tuple[date | None, date | None]:
        """Half-open ``(start, end_exclusive)``."""
        return self.start, _end_exclusive(self.end)

    def contains(self, d: date) -> bool:
        return _in_window(d, *self.window)


@dataclass(frozen=True, kw_only=True)
class CostStress:
    cost_multiplier: Decimal
    slippage_multiplier: Decimal

    def __post_init__(self) -> None:
        if D(self.cost_multiplier) < ZERO or D(self.slippage_multiplier) < ZERO:
            raise InvalidInput("cost stress multipliers must be ≥ 0")


NO_STRESS = CostStress(cost_multiplier=ONE, slippage_multiplier=ONE)


# ================================================================================================ costs


@dataclass(frozen=True, kw_only=True)
class CostRateRow:
    """One point-in-time MF transaction charge (e.g. stamp duty on purchases, STT on equity-fund redemptions)."""

    rule_id: str
    component: str
    side: str  # 'buy' | 'sell'
    tax_classes: frozenset[str]  # the role tax classes it applies to
    rate: Decimal
    effective_from: date
    effective_to: date | None
    status: str

    def __post_init__(self) -> None:
        if self.side not in ("buy", "sell"):
            raise InvalidInput(f"{self.rule_id}: side must be buy or sell")
        if not (ZERO <= D(self.rate) < ONE):
            raise InvalidInput(f"{self.rule_id}: rate must be in [0, 1)")
        _check_bound(f"{self.rule_id}: effective_from", self.effective_from)
        _check_bound(f"{self.rule_id}: effective_to", self.effective_to)
        if self.effective_from is None:
            raise InvalidInput(f"{self.rule_id}: effective_from is required")
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise InvalidInput(f"{self.rule_id}: effective_to before effective_from")

    @property
    def window(self) -> tuple[date | None, date | None]:
        """Half-open ``[effective_from, effective_to + 1 day)``; ``effective_to`` is the last day the rate applies."""
        return self.effective_from, _end_exclusive(self.effective_to)

    def covers(self, on: date) -> bool:
        return _in_window(on, *self.window)


_VERIFIED = frozenset({"VERIFIED-PRIMARY", "VERIFIED-SECONDARY"})


@dataclass(frozen=True, kw_only=True)
class MfCostSchedule:
    """Point-in-time MF charges plus a per-side slippage rate (zero for NAV-priced funds).

    Coverage is fail-closed: a trade dated before the first row of a component that applies to its side and tax
    class is *uncovered* (the charge may or may not have existed then), and G6 abstains with ``cost_rules_missing``.
    Exit loads are scheme-specific and not modelled; that is flagged on every run.
    """

    rows: tuple[CostRateRow, ...]
    slippage_rate: Decimal

    def __post_init__(self) -> None:
        # Two rows of one component that can price the same trade (same side, a shared tax class) on the same day
        # would make the rate depend on row order: refuse them instead of silently taking the first.
        for a, b in combinations(self.rows, 2):
            if (
                a.component == b.component
                and a.side == b.side
                and a.tax_classes & b.tax_classes
                and _overlap(a.window, b.window)
            ):
                raise InvalidInput(
                    f"cost rows {a.rule_id} and {b.rule_id} both price {a.side} {a.component} for "
                    f"{sorted(a.tax_classes & b.tax_classes)} on overlapping dates"
                )

    def _components(self, side: str, tax_class: str) -> dict[str, list[CostRateRow]]:
        out: dict[str, list[CostRateRow]] = {}
        for r in self.rows:
            if r.side == side and tax_class in r.tax_classes:
                out.setdefault(r.component, []).append(r)
        return out

    def trade_cost(self, side: str, tax_class: str, on: date, value: Decimal, stress: CostStress) -> _Cost:
        comps: dict[str, Decimal] = {}
        estimated = False
        uncovered = False
        rule_ids: list[str] = []
        with engine_context():
            for name, rows in sorted(self._components(side, tax_class).items()):
                hit = [r for r in rows if r.covers(on)]
                if not hit:
                    uncovered = True
                    continue
                row = hit[0]
                rule_ids.append(row.rule_id)
                comps[name] = value * row.rate * stress.cost_multiplier
                if row.status not in _VERIFIED:
                    estimated = True
            if self.slippage_rate > ZERO:
                comps["slippage"] = value * self.slippage_rate * stress.slippage_multiplier
        return _Cost(components=comps, estimated=estimated, uncovered=uncovered, rule_ids=tuple(rule_ids))

    def rate(self, side: str, tax_class: str, on: date, stress: CostStress) -> Decimal:
        """Total proportional rate for a trade (used to size purchases so price + charges fit the cash)."""
        c = self.trade_cost(side, tax_class, on, ONE, stress)
        with engine_context():
            return sum(c.components.values(), ZERO)


@dataclass(frozen=True)
class _Cost:
    components: Mapping[str, Decimal]
    estimated: bool
    uncovered: bool
    rule_ids: tuple[str, ...]

    def as_trade_cost(self, rule_id: str) -> TradeCost:
        return TradeCost(
            components=self.components,
            rule_id=rule_id,
            costs_estimated=self.estimated,
            reasons=("cost_row_not_verified",) if self.estimated else (),
        )


# ================================================================================================ data


@dataclass(frozen=True)
class NavPanel:
    """Aligned NAV observations: one date axis, one Decimal NAV per date per role (slot name)."""

    dates: tuple[date, ...]
    navs: Mapping[str, tuple[Decimal, ...]]

    def __post_init__(self) -> None:
        for d in self.dates:
            if isinstance(d, datetime) or not isinstance(d, date):
                raise InvalidInput(
                    f"panel dates must be IST calendar dates, got {type(d).__name__} {d!r} (use align_panel to convert)"
                )
        if len(self.dates) < 2:
            raise InsufficientHistory("a NAV panel needs at least 2 observations")
        for a, b in zip(self.dates, self.dates[1:], strict=False):
            if not b > a:
                raise InvalidInput(f"panel dates must be strictly increasing ({a} then {b})")
        if not self.navs:
            raise InvalidInput("a NAV panel needs at least one role")
        frozen: dict[str, tuple[Decimal, ...]] = {}
        for role, xs in self.navs.items():
            if len(xs) != len(self.dates):
                raise InvalidInput(f"role {role}: {len(xs)} NAVs for {len(self.dates)} dates")
            vals = tuple(D(x) for x in xs)
            if any(v <= ZERO for v in vals):
                raise InvalidInput(f"role {role}: NAVs must be positive")
            frozen[role] = vals
        object.__setattr__(self, "navs", MappingProxyType(frozen))

    def truncate(self, n_obs: int) -> NavPanel:
        return NavPanel(self.dates[:n_obs], {r: v[:n_obs] for r, v in self.navs.items()})


@dataclass(frozen=True)
class AlignedPanel:
    """A backtest panel plus what was removed to build it (every exclusion is counted, never silent)."""

    panel: NavPanel
    undated_excluded: Mapping[str, int]  # role → rows with no date
    outside_window: Mapping[str, int]  # role → dated rows outside ``[start, end)``
    unaligned_dropped: int  # in-window dates missing for at least one role
    start: date | None
    end: date | None  # exclusive


def align_panel(
    series: Mapping[str, Sequence[tuple[object, Decimal | str | int]]],
    *,
    start: date | None = None,
    end: date | None = None,
) -> AlignedPanel:
    """Build a backtest panel from per-role ``(date, nav)`` rows, on the dates every role has, inside ``[start, end)``.

    * Undated rows (``None`` or empty date) are excluded and counted: a backtest never guesses when a NAV applied.
    * Dates are IST calendar dates (``to_ist_date``): offset-aware timestamps are converted, naive ones refused.
    * Two rows of one role on one IST date must agree, else ``InvalidInput``; identical repeats collapse.
    * ``end`` is exclusive. A role left with no rows, or fewer than 2 common dates, raises ``InsufficientHistory``
      saying which filter emptied it.
    """
    _check_bound("start", start)
    _check_bound("end", end)
    if start is not None and end is not None and not start < end:
        raise InvalidInput(f"empty window [{start}, {end})")
    if not series:
        raise InvalidInput("no roles supplied")
    by_role: dict[str, dict[date, Decimal]] = {}
    undated: dict[str, int] = {}
    outside: dict[str, int] = {}
    for role in sorted(series):
        kept: dict[date, Decimal] = {}
        n_undated = n_outside = 0
        for raw_d, raw_v in series[role]:
            if raw_d is None or (isinstance(raw_d, str) and not raw_d.strip()):
                n_undated += 1
                continue
            d = to_ist_date(raw_d, f"role {role}: observation date")
            if not _in_window(d, start, end):
                n_outside += 1
                continue
            v = D(raw_v)
            if d in kept and kept[d] != v:
                raise InvalidInput(f"role {role}: conflicting NAVs {kept[d]} and {v} on {d}")
            kept[d] = v
        undated[role], outside[role] = n_undated, n_outside
        if not kept:
            raise InsufficientHistory(
                f"role {role}: no observations left after excluding {n_undated} undated and {n_outside} "
                f"outside [{start or '-inf'}, {end or '+inf'})"
            )
        by_role[role] = kept
    all_dates = set().union(*(set(v) for v in by_role.values()))
    common = sorted(set.intersection(*(set(v) for v in by_role.values())))
    if len(common) < 2:
        raise InsufficientHistory(
            f"only {len(common)} date(s) common to all roles in [{start or '-inf'}, {end or '+inf'}) "
            f"(undated excluded: {undated})"
        )
    panel = NavPanel(tuple(common), {r: tuple(by_role[r][d] for d in common) for r in by_role})
    return AlignedPanel(
        panel=panel,
        undated_excluded=MappingProxyType(undated),
        outside_window=MappingProxyType(outside),
        unaligned_dropped=len(all_dates) - len(common),
        start=start,
        end=end,
    )


def month_end_indices(dates: Sequence[date]) -> tuple[int, ...]:
    """Index of the last observation of each calendar month; the panel's final month is excluded (it may be
    incomplete). This is the rules' monthly grid, whatever the decision frequency."""
    return tuple(
        i for i in range(len(dates) - 1) if (dates[i].year, dates[i].month) != (dates[i + 1].year, dates[i + 1].month)
    )


def _decision_positions(dates: Sequence[date], grid_idx: Sequence[int], every_months: int) -> tuple[int, ...]:
    _strict_int("decision_every_months", every_months, 1)
    if not grid_idx:
        return ()
    first = dates[grid_idx[0]]
    base = first.year * 12 + first.month - 1
    return tuple(
        k for k, i in enumerate(grid_idx) if (dates[i].year * 12 + dates[i].month - 1 - base) % every_months == 0
    )


def decision_indices(dates: Sequence[date], every_months: int) -> tuple[int, ...]:
    """Observation index of each decision: a month-end, every ``every_months`` months."""
    grid_idx = month_end_indices(dates)
    return tuple(grid_idx[k] for k in _decision_positions(dates, grid_idx, every_months))


# ================================================================================================ rules


@dataclass(frozen=True)
class PortfolioView:
    """What a rule may see about its own book at a decision: units, cash and the *known* (lagged) prices."""

    units: Mapping[str, Decimal]
    cash: Decimal
    known_prices: Mapping[str, Decimal]
    contribution: Decimal

    def value(self, role: str) -> Decimal:
        with engine_context():
            return self.units.get(role, ZERO) * self.known_prices[role]

    @property
    def total(self) -> Decimal:
        with engine_context():
            return self.cash + sum((self.value(r) for r in self.known_prices), ZERO)


#: A rule maps (month-end grid history per role, own book) to target weights (summing to 1), or None for "no trade".
RuleFn = Callable[[Mapping[str, Sequence[Decimal]], PortfolioView], Mapping[str, Decimal] | None]


@dataclass(frozen=True, kw_only=True)
class RuleSpec:
    kind: str
    params: Mapping[str, Decimal | int]
    slots: Mapping[str, str]  # the rule's slot name → panel role key

    @property
    def min_history(self) -> int:
        """Grid months a decision needs (so the first OOS origin is after warm-up)."""
        p = self.params
        if self.kind == "trend_sma":
            return int(p["lookback_months"])
        if self.kind in ("abs_momentum", "dual_momentum"):
            return int(p["lookback_months"]) + 1
        if self.kind == "drawdown_topup":
            return int(p["window_months"])
        return 1


def _ret(xs: Sequence[Decimal], back_to: int, back_from: int) -> Decimal:
    """``x[-1-back_from] / x[-1-back_to] − 1`` (months back from the latest grid value)."""
    with engine_context():
        return xs[-1 - back_from] / xs[-1 - back_to] - ONE


def _hold(role: str) -> dict[str, Decimal]:
    return {role: ONE}


def build_rule(spec: RuleSpec) -> RuleFn:
    """Turn a pre-registered rule spec into a pure decision function. Unknown kinds are refused."""
    if spec.kind in ("trend_sma", "abs_momentum", "dual_momentum"):
        return _timing_rule(spec)
    if spec.kind in ("drawdown_topup", "sip_schedule"):
        return _cashflow_rule(spec)
    if spec.kind in ("buy_and_hold", "equal_weight"):
        return _static_rule(spec)
    raise InvalidInput(f"unknown rule kind {spec.kind!r}")


def _timing_rule(spec: RuleSpec) -> RuleFn:
    p, s = spec.params, spec.slots
    kind = spec.kind
    need = spec.min_history

    def ready(hist: Mapping[str, Sequence[Decimal]]) -> bool:
        return all(len(v) >= need for v in hist.values())

    if kind == "trend_sma":
        n = int(p["lookback_months"])

        def trend(hist: Mapping[str, Sequence[Decimal]], view: PortfolioView) -> Mapping[str, Decimal] | None:
            if not ready(hist):
                return None
            xs = hist[s["risk"]]
            with engine_context():
                sma = sum(xs[-n:], ZERO) / Decimal(n)
            return _hold(s["risk"] if xs[-1] > sma else s["out"])

        return trend

    if kind == "abs_momentum":
        lb, skip = int(p["lookback_months"]), int(p["skip_months"])

        def absmom(hist: Mapping[str, Sequence[Decimal]], view: PortfolioView) -> Mapping[str, Decimal] | None:
            if not ready(hist):
                return None
            r_risk = _ret(hist[s["risk"]], lb, skip)
            r_hurdle = _ret(hist[s["hurdle"]], lb, skip)
            return _hold(s["risk"] if r_risk > r_hurdle else s["out"])

        return absmom

    if kind == "dual_momentum":
        lb = int(p["lookback_months"])
        cands = [s[k] for k in sorted(s) if k.startswith("candidate")]
        if not cands:
            raise InvalidInput("dual_momentum needs candidate slots")

        def dualmom(hist: Mapping[str, Sequence[Decimal]], view: PortfolioView) -> Mapping[str, Decimal] | None:
            if not ready(hist):
                return None
            scored = sorted(((_ret(hist[c], lb, 0), c) for c in cands), key=lambda t: (-t[0], t[1]))
            best_r, best = scored[0]
            return _hold(best if best_r > _ret(hist[s["hurdle"]], lb, 0) else s["out"])

        return dualmom

    raise InvalidInput(f"unknown timing rule kind {kind!r}")


def _cashflow_rule(spec: RuleSpec) -> RuleFn:
    p, s = spec.params, spec.slots
    kind = spec.kind
    need = spec.min_history

    def ready(hist: Mapping[str, Sequence[Decimal]]) -> bool:
        return all(len(v) >= need for v in hist.values())

    if kind in ("drawdown_topup", "sip_schedule"):
        multiple = D(p["topup_multiple"])
        threshold = D(p["threshold"]) if kind == "drawdown_topup" else ZERO
        window = int(p["window_months"]) if kind == "drawdown_topup" else 1

        def topup(hist: Mapping[str, Sequence[Decimal]], view: PortfolioView) -> Mapping[str, Decimal] | None:
            risk, reserve = s["risk"], s["reserve"]
            if kind == "drawdown_topup" and not ready(hist):
                return None
            with engine_context():
                total = view.total
                if total <= ZERO:
                    return None
                pool = view.value(reserve) + view.cash - view.contribution
                if kind == "drawdown_topup":
                    xs = hist[risk]
                    triggered = xs[-1] <= (ONE - threshold) * max(xs[-window:])
                else:
                    triggered = True
                move = min(pool, multiple * view.contribution) if triggered else ZERO
                move = max(move, ZERO)
                w_risk = (view.value(risk) + view.contribution + move) / total
                return {risk: w_risk, reserve: ONE - w_risk}

        return topup

    raise InvalidInput(f"unknown cash-flow rule kind {kind!r}")


def _static_rule(spec: RuleSpec) -> RuleFn:
    s = spec.slots
    if spec.kind == "buy_and_hold":
        role = s["risk"]

        def bnh(hist: Mapping[str, Sequence[Decimal]], view: PortfolioView) -> Mapping[str, Decimal] | None:
            # Buy once with the initial capital (and with each contribution, if any); otherwise never trade.
            if view.cash <= ZERO or (view.units.get(role, ZERO) > ZERO and view.contribution == ZERO):
                return None
            return _hold(role)

        return bnh

    if spec.kind == "equal_weight":
        roles = [s[k] for k in sorted(s)]

        def ew(hist: Mapping[str, Sequence[Decimal]], view: PortfolioView) -> Mapping[str, Decimal] | None:
            with engine_context():
                w = ONE / Decimal(len(roles))
                out = {r: w for r in roles[:-1]}
                out[roles[-1]] = ONE - w * Decimal(len(roles) - 1)
            return out

        return ew

    raise InvalidInput(f"unknown static rule kind {spec.kind!r}")


# ================================================================================================ simulation


@dataclass(frozen=True, kw_only=True)
class BacktestSetup:
    """Everything one walk-forward needs besides the data. Built by the service from a pre-registered spec."""

    strategy: RuleSpec
    benchmark: RuleSpec
    config: WalkForwardConfig
    decision_every_months: int
    initial_capital: Decimal
    contribution: Decimal
    tax_classes: Mapping[str, str]  # role key → tax-lot asset class
    costs: MfCostSchedule
    cost_policy: CostBasisPolicy
    tax_table: TaxRateTable
    vault: VaultSpec
    regimes: tuple[RegimeSpec, ...]
    stress: CostStress = field(default=NO_STRESS)

    def __post_init__(self) -> None:
        _strict_int("decision_every_months", self.decision_every_months, 1)
        if D(self.initial_capital) <= ZERO or D(self.contribution) < ZERO:
            raise InvalidInput("initial capital must be > 0 and contribution ≥ 0")
        ids = [rg.regime_id for rg in self.regimes]
        if len(set(ids)) != len(ids):
            raise InvalidInput(f"regime ids must be unique: {ids}")
        for a, b in combinations(self.regimes, 2):
            if _overlap(a.window, b.window):
                raise InvalidInput(f"regimes {a.regime_id} and {b.regime_id} overlap: a period would count in both")


@dataclass(frozen=True, kw_only=True)
class PeriodRecord:
    start: date
    end: date
    strategy_return: Decimal
    benchmark_return: Decimal
    edge: Decimal


@dataclass(frozen=True, kw_only=True)
class RegimeEdge:
    regime_id: str
    n_periods: int
    mean_edge: Decimal | None  # None (never 0) when the regime has no pre-vault period: reported, not blank


@dataclass(frozen=True, kw_only=True)
class SideResult:
    values: tuple[Decimal, ...]
    returns: tuple[Decimal, ...]
    terminal: TerminalValuation
    n_trades: int
    uncovered_cost_dates: tuple[date, ...]
    max_drawdown: Decimal


@dataclass(frozen=True, kw_only=True)
class WalkForwardResult:
    formula_id: str
    decision_dates: tuple[date, ...]  # OOS origins (one per period start) plus the final mark
    periods: tuple[PeriodRecord, ...]
    strategy: SideResult
    benchmark: SideResult
    vault_start: date | None
    n_vault_periods: int
    leakage_checks: int
    regimes: tuple[RegimeEdge, ...]
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def oos_edges(self) -> tuple[float, ...]:
        return tuple(float(p.edge) for p in self.periods)

    @property
    def edge_after_tax(self) -> Decimal | None:
        """Strategy minus benchmark terminal value: liquidated, exemption already used (the G6 conservative bound)."""
        a, b = self.strategy.terminal.gating_value_inr, self.benchmark.terminal.gating_value_inr
        if a is None or b is None:
            return None
        with engine_context():
            return a - b

    @property
    def tax_rules_missing(self) -> bool:
        return self.strategy.terminal.tax_rules_missing or self.benchmark.terminal.tax_rules_missing

    @property
    def cost_rules_missing(self) -> bool:
        return bool(self.strategy.uncovered_cost_dates or self.benchmark.uncovered_cost_dates)

    @property
    def costs_estimated(self) -> bool:
        return self.strategy.terminal.costs_estimated or self.benchmark.terminal.costs_estimated


def max_drawdown(returns: Sequence[Decimal]) -> Decimal:
    """Largest peak-to-trough fall of the time-weighted index built from period returns (a positive fraction)."""
    with engine_context():
        level, peak, worst = ONE, ONE, ZERO
        for r in returns:
            level = level * (ONE + r)
            peak = max(peak, level)
            worst = max(worst, (peak - level) / peak)
        return worst


def _floor_units(x: Decimal) -> Decimal:
    with engine_context():
        return x.quantize(UNITS_QUANTUM, rounding=ROUND_DOWN) if x > ZERO else ZERO


class _Book:
    """Mutable simulation wrapper around the immutable A17 ledger for one portfolio."""

    def __init__(self, panel: NavPanel, setup: BacktestSetup, start_obs: int) -> None:
        self.panel = panel
        self.setup = setup
        self.state = LedgerState.open(cash=D(setup.initial_capital), on=panel.dates[start_obs])
        self.n_trades = 0
        self.uncovered: list[date] = []
        self.warnings: list[str] = [W_EXIT_LOAD_NOT_MODELLED]

    def units(self) -> dict[str, Decimal]:
        return {r: self.state.units_held(r) for r in self.panel.navs}

    def mark(self, i: int) -> Decimal:
        with engine_context():
            return self.state.cash_inr + sum(
                (self.state.units_held(r) * self.panel.navs[r][i] for r in self.panel.navs), ZERO
            )

    def deposit(self, amount: Decimal) -> None:
        if amount > ZERO:
            with engine_context():
                self.state = replace(self.state, cash_inr=self.state.cash_inr + amount)

    def _cost(self, side: str, role: str, on: date, value: Decimal) -> TradeCost:
        c = self.setup.costs.trade_cost(side, self.setup.tax_classes[role], on, value, self.setup.stress)
        if c.uncovered:
            self.uncovered.append(on)
        return c.as_trade_cost(rule_id="+".join(c.rule_ids) or "no_cost_row")

    def execute(self, weights: Mapping[str, Decimal], known: Mapping[str, Decimal], i: int) -> None:
        cfg = self.setup.config.fill_rule
        f_sell = i + cfg.nav_offset
        panel = self.panel
        unknown = set(weights) - set(panel.navs)
        if unknown:
            raise InvalidInput(f"rule returned weights for unknown roles {sorted(unknown)}")
        if any(w < ZERO for w in weights.values()):
            raise InvalidInput("weights must be non-negative (long-only)")
        with engine_context():
            if abs(sum(weights.values(), ZERO) - ONE) > _WEIGHT_TOLERANCE:
                raise InvalidInput("weights must sum to 1")
            units = self.units()
            total = self.state.cash_inr + sum((units[r] * known[r] for r in panel.navs), ZERO)
            target = {r: weights.get(r, ZERO) * total for r in panel.navs}
            current = {r: units[r] * known[r] for r in panel.navs}
            sold = False
            for r in sorted(panel.navs):
                if units[r] <= ZERO or current[r] <= target[r]:
                    continue
                q = units[r] if weights.get(r, ZERO) == ZERO else _floor_units((current[r] - target[r]) / known[r])
                q = min(q, units[r])
                if q <= ZERO:
                    continue
                on, px = panel.dates[f_sell], panel.navs[r][f_sell]
                self.state = sell(self.state, r, on, q, px, self._cost("sell", r, on, q * px), self.setup.cost_policy)
                self.n_trades += 1
                sold = True
            f_buy = f_sell + (cfg.switch_cash_gap if sold else 0)
            deficits = {r: target[r] - current[r] for r in sorted(panel.navs) if target[r] > current[r]}
            pool = self.state.cash_inr
            need = sum(deficits.values(), ZERO)
            if need <= ZERO or pool <= ZERO:
                return
            on = panel.dates[f_buy]
            for r, deficit in deficits.items():
                amount = pool * deficit / need
                px = panel.navs[r][f_buy]
                rate = self.setup.costs.rate("buy", self.setup.tax_classes[r], on, self.setup.stress)
                q = _floor_units(amount / (px * (ONE + rate)))
                if q <= ZERO:
                    continue
                cost = self._cost("buy", r, on, q * px)
                if q * px + cost.total_inr > self.state.cash_inr:
                    q = _floor_units(self.state.cash_inr / (px * (ONE + rate))) - UNITS_QUANTUM
                    if q <= ZERO:
                        continue
                    cost = self._cost("buy", r, on, q * px)
                self.state = buy(self.state, r, self.setup.tax_classes[r], on, q, px, cost, self.setup.cost_policy)
                self.n_trades += 1

    def terminal(self, i: int) -> TerminalValuation:
        panel = self.panel
        on = panel.dates[i]
        prices = {r: panel.navs[r][i] for r in panel.navs}

        def sell_cost(inst: str, d: date, value: Decimal) -> TradeCost:
            return self._cost("sell", inst, d, value)

        return terminal_valuation(
            self.state, on, prices, sell_cost, self.setup.tax_table, policy=self.setup.cost_policy
        )


def _grid(panel: NavPanel, dec: Sequence[int], lag: int) -> dict[str, tuple[Decimal, ...]]:
    out: dict[str, tuple[Decimal, ...]] = {}
    for r, xs in panel.navs.items():
        vals: list[Decimal] = []
        for i in dec:
            j = i - lag
            if j < 0:
                raise InsufficientHistory(f"lag {lag} reaches before the first observation")
            vals.append(xs[j])
        out[r] = tuple(vals)
    return out


def _check_spacing(dec: Sequence[int], cfg: WalkForwardConfig) -> None:
    span = cfg.fill_rule.nav_offset + cfg.fill_rule.switch_cash_gap
    for a, b in pairwise(dec):
        if b - a <= span:
            raise InvalidInput(f"decisions {a} and {b} are closer than fill + switch gap ({span} observations)")


def _simulate(
    panel: NavPanel,
    setup: BacktestSetup,
    rule: RuleFn,
    lay: _Layout,
    grid: Mapping[str, Sequence[Decimal]],
    j0: int,
    j_end: int,
) -> SideResult:
    book = _Book(panel, setup, lay.obs(j0))
    cfg = setup.config
    values: list[Decimal] = []
    returns: list[Decimal] = []
    with engine_context():
        for j in range(j0, j_end + 1):
            k = lay.dpos[j]  # grid position (month) of decision j
            i = lay.obs(j)
            v = book.mark(i)
            if values:
                base = values[-1] + setup.contribution  # the contribution was deposited at the previous decision
                returns.append(v / base - ONE if base > ZERO else ZERO)
            values.append(v)
            if j == j_end:
                break
            book.deposit(setup.contribution)
            # Invariants (research §4.2 #1 and #3): the rule sees grid months 0..k only, each of which is
            # NAV[decision_j − lag] with decision_j ≤ i; every fill is strictly after the decision.
            hist = {r: grid[r][: k + 1] for r in grid}
            if any(len(h) != k + 1 for h in hist.values()) or cfg.fill_rule.nav_offset < 1:
                raise LeakageError(f"decision {k}: feature window or fill timing violates the timeline")
            known = {r: grid[r][k] for r in grid}
            view = PortfolioView(
                units=MappingProxyType(book.units()),
                cash=book.state.cash_inr,
                known_prices=known,
                contribution=setup.contribution,
            )
            w = rule(hist, view)
            if w is not None:
                book.execute(w, known, i)
    terminal = book.terminal(lay.obs(j_end))
    return SideResult(
        values=tuple(values),
        returns=tuple(returns),
        terminal=terminal,
        n_trades=book.n_trades,
        uncovered_cost_dates=tuple(dict.fromkeys(book.uncovered)),
        max_drawdown=max_drawdown(returns),
    )


def split_vault(n_periods: int, vault: VaultSpec, every_months: int) -> int:
    """Number of trailing decision periods sealed in the vault: max(⌈fraction × n⌉, ⌈min_months / every⌉)."""
    if n_periods < 1:
        raise InsufficientHistory("no decision periods")
    by_fraction = math.ceil(float(D(vault.fraction)) * n_periods)
    by_months = math.ceil(vault.min_months / every_months)
    return max(by_fraction, by_months)


@dataclass(frozen=True)
class _Layout:
    grid_idx: tuple[int, ...]  # observation index of every month-end (the rules' monthly grid)
    dpos: tuple[int, ...]  # grid positions of the decision months
    j0: int  # first OOS decision (after warm-up, purge and embargo)
    j_end: int  # the vault starts at decision j_end
    n_vault: int

    def obs(self, j: int) -> int:
        return self.grid_idx[self.dpos[j]]


def _layout(panel: NavPanel, setup: BacktestSetup) -> _Layout:
    cfg = setup.config
    grid_idx = month_end_indices(panel.dates)
    dpos = _decision_positions(panel.dates, grid_idx, setup.decision_every_months)
    _check_spacing([grid_idx[k] for k in dpos], cfg)
    if dpos and grid_idx[dpos[-1]] + cfg.fill_rule.nav_offset + cfg.fill_rule.switch_cash_gap >= len(panel.dates):
        dpos = dpos[:-1]
    n_periods = len(dpos) - 1
    if n_periods < 2:
        raise InsufficientHistory("fewer than 2 decision periods")
    n_vault = split_vault(n_periods, setup.vault, setup.decision_every_months)
    j_end = len(dpos) - 1 - n_vault
    warmup = max(setup.strategy.min_history, setup.benchmark.min_history)
    ready = next((j for j, k in enumerate(dpos) if k >= warmup - 1), len(dpos))
    j0 = ready + cfg.purge + cfg.embargo
    if j_end - j0 < 2:
        raise InsufficientHistory(
            f"no pre-vault OOS periods after warm-up {warmup}, purge {cfg.purge} and embargo {cfg.embargo}"
        )
    return _Layout(grid_idx=grid_idx, dpos=dpos, j0=j0, j_end=j_end, n_vault=n_vault)


def _leakage_checks(k0: int, k_end: int, cfg: WalkForwardConfig) -> int:
    """At every OOS origin the estimation window ``[0, k − purge − embargo]`` passes ``assert_no_leakage``."""
    n = 0
    for k in range(k0, k_end):
        hi = k - cfg.purge - cfg.embargo
        train = list(range(hi + 1)) if hi >= 0 else []
        assert_no_leakage(train, origin=k, horizon=cfg.purge, embargo=cfg.embargo)
        n += 1
    return n


def _regimes(periods: Sequence[PeriodRecord], regimes: Sequence[RegimeSpec]) -> tuple[RegimeEdge, ...]:
    out: list[RegimeEdge] = []
    with engine_context():
        for rg in regimes:
            edges = [p.edge for p in periods if rg.contains(p.start)]
            mean = sum(edges, ZERO) / Decimal(len(edges)) if edges else None
            out.append(RegimeEdge(regime_id=rg.regime_id, n_periods=len(edges), mean_edge=mean))
    return tuple(out)


def _run(panel: NavPanel, setup: BacktestSetup, lay: _Layout, j0: int, j_end: int) -> WalkForwardResult:
    grid = _grid(panel, lay.grid_idx, setup.config.lag)
    strat = _simulate(panel, setup, build_rule(setup.strategy), lay, grid, j0, j_end)
    bench = _simulate(panel, setup, build_rule(setup.benchmark), lay, grid, j0, j_end)
    with engine_context():
        periods = tuple(
            PeriodRecord(
                start=panel.dates[lay.obs(j0 + n)],
                end=panel.dates[lay.obs(j0 + n + 1)],
                strategy_return=rs,
                benchmark_return=rb,
                edge=rs - rb,
            )
            for n, (rs, rb) in enumerate(zip(strat.returns, bench.returns, strict=True))
        )
    reasons: list[str] = [*strat.terminal.reason_codes, *bench.terminal.reason_codes]
    if strat.uncovered_cost_dates or bench.uncovered_cost_dates:
        reasons.append(R_COST_RULES_MISSING)
    warnings = [W_EXIT_LOAD_NOT_MODELLED, *strat.terminal.warnings, *bench.terminal.warnings]
    return WalkForwardResult(
        formula_id=FORMULA_ID,
        decision_dates=tuple(panel.dates[lay.obs(j)] for j in range(j0, j_end + 1)),
        periods=periods,
        strategy=strat,
        benchmark=bench,
        vault_start=None,
        n_vault_periods=0,
        leakage_checks=0,
        regimes=_regimes(periods, setup.regimes),
        reason_codes=tuple(dict.fromkeys(reasons)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def run_walk_forward(panel: NavPanel, setup: BacktestSetup) -> WalkForwardResult:
    """Walk-forward over the pre-vault history only. The vault's NAVs are cut off before any rule runs."""
    lay = _layout(panel, setup)
    vault_start_obs = lay.obs(lay.j_end)
    # Seal the vault: no observation after the vault start exists for the rules or the books.
    sealed_panel = panel.truncate(vault_start_obs + 1)
    sealed = _Layout(
        grid_idx=tuple(i for i in lay.grid_idx if i <= vault_start_obs),
        dpos=lay.dpos[: lay.j_end + 1],
        j0=lay.j0,
        j_end=lay.j_end,
        n_vault=lay.n_vault,
    )
    checks = _leakage_checks(lay.j0, lay.j_end, setup.config)
    res = _run(sealed_panel, setup, sealed, lay.j0, lay.j_end)
    return replace(res, vault_start=panel.dates[vault_start_obs], n_vault_periods=lay.n_vault, leakage_checks=checks)


def run_vault(panel: NavPanel, setup: BacktestSetup) -> WalkForwardResult:
    """G11: the single evaluation of the sealed final period (history before it may feed the rule's lookback)."""
    lay = _layout(panel, setup)
    res = _run(panel, setup, lay, lay.j_end, len(lay.dpos) - 1)
    return replace(res, vault_start=panel.dates[lay.obs(lay.j_end)], n_vault_periods=lay.n_vault, regimes=())


# ================================================================================================ shuffle canary


@dataclass(frozen=True, kw_only=True)
class CanaryResult:
    """Pipeline test (research §4.2): permuted and pure-noise data must show no OOS edge (mean Φ(HAC t) ≤ bound)."""

    replicates: int
    seed: int
    permuted_scores: tuple[Decimal, ...]
    noise_scores: tuple[Decimal, ...]
    mean_permuted_score: Decimal
    mean_noise_score: Decimal
    threshold: Decimal
    passed: bool
    formula_id: str = "BT-CANARY@1"


def _score(edges: Sequence[float]) -> float:
    """``Φ(t)`` of the mean edge with a Newey-West HAC variance (plug-in lag); 0.5 when degenerate."""
    try:
        t = hac_t_stat(edges, lag=min(newey_west_lag(len(edges)), len(edges) - 1))
    except (InvalidInput, NumericalError):
        return 0.5  # degenerate series: no evidence either way
    return _N.cdf(t.t_stat)


def _rebuild(panel: NavPanel, rets: Mapping[str, Sequence[float]]) -> NavPanel:
    navs: dict[str, tuple[Decimal, ...]] = {}
    q = Decimal("0.0001")
    with engine_context():
        for r, xs in panel.navs.items():
            level = xs[0]
            out = [level]
            for x in rets[r]:
                level = (level * (ONE + from_float(x))).quantize(q)
                if level <= ZERO:
                    level = q
                out.append(level)
            navs[r] = tuple(out)
    return NavPanel(panel.dates, navs)


def shuffle_canary(
    panel: NavPanel,
    pipeline: Callable[[NavPanel], Sequence[float]],
    *,
    seed: int,
    replicates: int,
    threshold: float = CANARY_MAX_MEAN_SCORE,
) -> CanaryResult:
    """Rerun ``pipeline`` (panel → OOS edges) on (a) the same returns with dates permuted jointly across roles and
    (b) i.i.d. Gaussian noise with each role's s.d. Seeded generator only (``default_rng(seed)``).

    Both are **drift-neutralised**: every role's daily returns are re-centred on one common mean, so holding a
    different exposure than the benchmark cannot earn an expected edge (otherwise a rule that sits in the liquid fund
    would "win" whenever the sample's equity drift is below the liquid yield). On such data an edge can only come
    from look-ahead.
    """
    _strict_int("replicates", replicates, 1)
    rng = np.random.default_rng(seed)
    base: dict[str, np.ndarray] = {}
    for r in sorted(panel.navs):
        arr = np.array([float(x) for x in panel.navs[r]], dtype=np.float64)
        base[r] = arr[1:] / arr[:-1] - 1.0
    common = float(np.mean([np.mean(v) for v in base.values()]))
    centred = {r: v - float(np.mean(v)) + common for r, v in base.items()}
    n = len(panel.dates) - 1
    perm_sc: list[float] = []
    noise_scores: list[float] = []
    for _ in range(replicates):
        order = rng.permutation(n)
        perm_sc.append(_score(pipeline(_rebuild(panel, {r: centred[r][order].tolist() for r in centred}))))
        noise = {r: rng.normal(common, float(np.std(base[r])) or 1e-9, size=n).tolist() for r in sorted(base)}
        noise_scores.append(_score(pipeline(_rebuild(panel, noise))))
    mp = math.fsum(perm_sc) / replicates
    mn = math.fsum(noise_scores) / replicates
    q = Decimal("0.000001")
    return CanaryResult(
        replicates=replicates,
        seed=seed,
        permuted_scores=tuple(from_float(x).quantize(q) for x in perm_sc),
        noise_scores=tuple(from_float(x).quantize(q) for x in noise_scores),
        mean_permuted_score=from_float(mp).quantize(q),
        mean_noise_score=from_float(mn).quantize(q),
        threshold=from_float(threshold),
        passed=mp <= threshold and mn <= threshold,
    )
