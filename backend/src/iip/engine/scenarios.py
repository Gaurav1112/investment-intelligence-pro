"""Deterministic scenario engine (Decimal only).  risk-methodology §7.4–7.5; calculation-methodology §2.11,
§4.4, §4.7, §4.8, §4.9.

Every scenario returns its **inputs** (assumption deltas and parameters) together with its **outputs**.
Scenarios are labelled "stress scenario" or "illustrative downside" — never "worst case" — and are never
probability-weighted.  Duration/convexity results are flagged ``approximate``; bond results are fully
repriced from cash flows.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from iip.engine.errors import InvalidInput
from iip.engine.money import ONE, ZERO, engine_context

BP = Decimal("0.0001")
HUNDRED = Decimal(100)
LARGE_SHOCK = Decimal("0.01")  # §4.4 / risk §7.4: |Δy| > 100 bp → full repricing required
STALE_DURATION_DAYS = 45  # risk §8: factsheet ≤ 45 days old
DEFAULT_EXIT_GRID_BP: tuple[int, ...] = (-100, -50, 0, 50, 100, 200)  # calc §4.9

Measure = Literal["nominal_inr", "real_inr"]


class ScenarioLabel(StrEnum):
    STRESS = "stress scenario"
    ILLUSTRATIVE_DOWNSIDE = "illustrative downside"


# ---------------------------------------------------------------------------------------------- results


@dataclass(frozen=True)
class Quantity:
    name: str
    value: Decimal
    unit: str  # "INR", "fraction", "years", "years^2", "periods", "bp", "per_100_face", "ratio"


@dataclass(frozen=True, kw_only=True)
class ScenarioResult:
    scenario_id: str
    label: ScenarioLabel
    inputs: tuple[Quantity, ...]
    outputs: tuple[Quantity, ...]
    base_value: Decimal
    shocked_value: Decimal
    impact: Decimal  # shocked − base, ₹ (negative = loss)
    impact_fraction: Decimal  # impact / base
    approximate: bool
    caveats: tuple[str, ...]
    measure: Measure = "nominal_inr"
    probability_weighted: bool = False

    def input(self, name: str) -> Decimal:
        for q in self.inputs:
            if q.name == name:
                return q.value
        raise KeyError(name)

    def output(self, name: str) -> Decimal:
        for q in self.outputs:
            if q.name == name:
                return q.value
        raise KeyError(name)


@dataclass(frozen=True)
class PortfolioScenarioResult:
    scenario_name: str
    label: ScenarioLabel
    portfolio_value: Decimal
    components: tuple[tuple[str, Decimal], ...]  # (holding id, ₹ impact)
    component_inputs: tuple[tuple[str, str, tuple[Quantity, ...]], ...]  # (holding id, scenario id, inputs)
    total_impact: Decimal
    impact_fraction: Decimal
    approximate: bool
    measure: Measure
    caveats: tuple[str, ...]
    probability_weighted: bool = False
    method_id: str = "SCN_PORTFOLIO_SUM@1"


# ---------------------------------------------------------------------------------------------- validation


def _dec(
    x: Decimal,
    name: str,
    *,
    lo: Decimal | None = None,
    hi: Decimal | None = None,
    lo_open: bool = False,
    hi_open: bool = False,
) -> Decimal:
    if isinstance(x, bool) or not isinstance(x, Decimal) or not x.is_finite():
        raise InvalidInput(f"{name} must be a finite Decimal, got {x!r}")
    if lo is not None and (x < lo or (lo_open and x == lo)):
        raise InvalidInput(f"{name} = {x} is below its allowed range")
    if hi is not None and (x > hi or (hi_open and x == hi)):
        raise InvalidInput(f"{name} = {x} is above its allowed range")
    return x


def _positive(x: Decimal, name: str) -> Decimal:
    return _dec(x, name, lo=ZERO, lo_open=True)


def _build(
    *,
    scenario_id: str,
    label: ScenarioLabel,
    inputs: Sequence[Quantity],
    outputs: Sequence[Quantity],
    base_value: Decimal,
    shocked_value: Decimal,
    approximate: bool,
    caveats: Sequence[str],
    measure: Measure = "nominal_inr",
) -> ScenarioResult:
    if not isinstance(label, ScenarioLabel):
        raise InvalidInput(f"label must be a ScenarioLabel, got {label!r}")
    with engine_context():
        impact = shocked_value - base_value
        fraction = impact / base_value
    return ScenarioResult(
        scenario_id=scenario_id,
        label=label,
        inputs=tuple(inputs),
        outputs=tuple(outputs),
        base_value=base_value,
        shocked_value=shocked_value,
        impact=impact,
        impact_fraction=fraction,
        approximate=approximate,
        caveats=tuple(dict.fromkeys(caveats)),
        measure=measure,
    )


# ---------------------------------------------------------------------------------------------- bonds (§4.3–4.4)


@dataclass(frozen=True)
class BulletBond:
    """Fixed-coupon bullet bond, priced per ``face`` on the RBI/Excel PRICE convention (calc §4.3).

    ``first_period_fraction`` is ``w = DSC/E`` (1 when settling on a coupon date).
    """

    coupon_rate: Decimal
    frequency: int
    periods_remaining: int
    first_period_fraction: Decimal = ONE
    face: Decimal = HUNDRED

    def __post_init__(self) -> None:
        _dec(self.coupon_rate, "coupon_rate", lo=ZERO)
        if self.frequency not in (1, 2, 4, 12):
            raise InvalidInput(f"coupon frequency must be 1, 2, 4 or 12, got {self.frequency}")
        if (
            isinstance(self.periods_remaining, bool)
            or not isinstance(self.periods_remaining, int)
            or self.periods_remaining < 1
        ):
            raise InvalidInput("periods_remaining must be an int ≥ 1")
        _dec(self.first_period_fraction, "first_period_fraction", lo=ZERO, hi=ONE, lo_open=True)
        _positive(self.face, "face")

    @property
    def coupon_amount(self) -> Decimal:
        with engine_context():
            return self.face * self.coupon_rate / Decimal(self.frequency)

    def cash_flows(self) -> list[tuple[Decimal, Decimal]]:
        """(n_k periods to cash flow, amount)."""
        with engine_context():
            w = self.first_period_fraction
            flows = [(Decimal(k - 1) + w, self.coupon_amount) for k in range(1, self.periods_remaining + 1)]
            n_last, c_last = flows[-1]
            flows[-1] = (n_last, c_last + self.face)
        return flows


@dataclass(frozen=True)
class BondAnalytics:
    yield_: Decimal
    dirty_price: Decimal
    clean_price: Decimal
    accrued_interest: Decimal
    macaulay_duration: Decimal
    modified_duration: Decimal
    convexity: Decimal
    dv01: Decimal  # per `face`, for 1 bp
    method_id: str = "BOND_ANALYTICS_SEMI_BEY@1"


def _growth(y: Decimal, f: int) -> Decimal:
    g = ONE + y / Decimal(f)
    if g <= 0:
        raise InvalidInput(f"yield {y} implies a non-positive discount base")
    return g


def bond_dirty_price(bond: BulletBond, y: Decimal) -> Decimal:
    _dec(y, "yield")
    with engine_context():
        g = _growth(y, bond.frequency)
        return sum((cf / g**n for n, cf in bond.cash_flows()), ZERO)


def bond_analytics(bond: BulletBond, y: Decimal) -> BondAnalytics:
    """calc §4.4: Macaulay, modified duration and convexity on the dirty price."""
    _dec(y, "yield")
    f = Decimal(bond.frequency)
    with engine_context():
        g = _growth(y, bond.frequency)
        dirty = ZERO
        t_pv = ZERO
        conv_sum = ZERO
        for n, cf in bond.cash_flows():
            pv = cf / g**n
            dirty += pv
            t_pv += (n / f) * pv
            conv_sum += cf * n * (n + ONE) / (f * f * g ** (n + 2))
        accrued = bond.coupon_amount * (ONE - bond.first_period_fraction)
        mac = t_pv / dirty
        mod = mac / g
        conv = conv_sum / dirty
        return BondAnalytics(
            yield_=y,
            dirty_price=dirty,
            clean_price=dirty - accrued,
            accrued_interest=accrued,
            macaulay_duration=mac,
            modified_duration=mod,
            convexity=conv,
            dv01=mod * dirty * BP,
        )


# ---------------------------------------------------------------------------------------------- rate shocks


def rate_shock_duration(
    value: Decimal,
    modified_duration: Decimal,
    delta_yield: Decimal,
    *,
    convexity: Decimal | None = None,
    duration_as_of: date | None = None,
    as_of: date | None = None,
    label: ScenarioLabel = ScenarioLabel.STRESS,
) -> ScenarioResult:
    """Parallel rate shock on a debt fund / holding from disclosed duration: ``ΔV/V ≈ −D Δy + ½ C Δy²``.

    Always ``approximate``.  For |Δy| > 100 bp the spec requires full repricing, which needs cash flows a
    fund does not disclose: the result is flagged ``FULL_REPRICING_UNAVAILABLE_LARGE_SHOCK``.
    """
    _positive(value, "value")
    _dec(modified_duration, "modified_duration", lo=ZERO)
    _dec(delta_yield, "delta_yield")
    caveats = ["APPROXIMATION_DURATION_CONVEXITY" if convexity is not None else "APPROXIMATION_DURATION_ONLY"]
    if convexity is None:
        caveats.append("CONVEXITY_NOT_PROVIDED")
    else:
        _dec(convexity, "convexity")
    if abs(delta_yield) > LARGE_SHOCK:
        caveats.append("FULL_REPRICING_UNAVAILABLE_LARGE_SHOCK")
    if (duration_as_of is None) != (as_of is None):
        raise InvalidInput("duration_as_of and as_of must be given together")
    if duration_as_of is not None and as_of is not None:
        if duration_as_of > as_of:
            raise InvalidInput("duration_as_of is after as_of")
        if (as_of - duration_as_of).days > STALE_DURATION_DAYS:
            caveats.append("STALE_DURATION")
    with engine_context():
        dur_part = -modified_duration * delta_yield
        conv_part = ZERO if convexity is None else convexity * delta_yield * delta_yield / 2
        frac = dur_part + conv_part
        shocked = value * (ONE + frac)
    inputs = [
        Quantity("value", value, "INR"),
        Quantity("modified_duration", modified_duration, "years"),
        Quantity("delta_yield", delta_yield, "fraction"),
    ]
    if convexity is not None:
        inputs.append(Quantity("convexity", convexity, "years^2"))
    return _build(
        scenario_id="SCN_RATE_DURATION_CONVEXITY@1",
        label=label,
        inputs=inputs,
        outputs=[
            Quantity("duration_component", dur_part, "fraction"),
            Quantity("convexity_component", conv_part, "fraction"),
            Quantity("price_change_fraction", frac, "fraction"),
        ],
        base_value=value,
        shocked_value=shocked,
        approximate=True,
        caveats=caveats,
    )


def _bond_reprice(
    bond: BulletBond, y0: Decimal, y1: Decimal, position_value: Decimal
) -> tuple[BondAnalytics, Decimal, Decimal, Decimal]:
    a0 = bond_analytics(bond, y0)
    p1 = bond_dirty_price(bond, y1)
    with engine_context():
        ratio = p1 / a0.dirty_price  # ratio first: an unchanged price gives exactly 1 → zero impact
        frac = ratio - ONE
        shocked = position_value * ratio
    return a0, p1, frac, shocked


def _bond_inputs(bond: BulletBond) -> list[Quantity]:
    return [
        Quantity("coupon_rate", bond.coupon_rate, "fraction"),
        Quantity("coupon_frequency", Decimal(bond.frequency), "per_year"),
        Quantity("periods_remaining", Decimal(bond.periods_remaining), "periods"),
        Quantity("first_period_fraction", bond.first_period_fraction, "ratio"),
        Quantity("face", bond.face, "INR"),
    ]


def bond_rate_shock(
    bond: BulletBond,
    base_yield: Decimal,
    delta_yield: Decimal,
    *,
    position_value: Decimal,
    label: ScenarioLabel = ScenarioLabel.STRESS,
) -> ScenarioResult:
    """Parallel rate shock on a bond: full repricing (headline) plus the duration(+convexity) explanation."""
    _positive(position_value, "position_value")
    _dec(delta_yield, "delta_yield")
    a0, p1, frac, shocked = _bond_reprice(bond, base_yield, base_yield + delta_yield, position_value)
    with engine_context():
        dur_only = -a0.modified_duration * delta_yield
        dur_conv = dur_only + a0.convexity * delta_yield * delta_yield / 2
    return _build(
        scenario_id="SCN_RATE_FULL_REPRICE@1",
        label=label,
        inputs=[
            *_bond_inputs(bond),
            Quantity("position_value", position_value, "INR"),
            Quantity("base_yield", base_yield, "fraction"),
            Quantity("delta_yield", delta_yield, "fraction"),
        ],
        outputs=[
            Quantity("base_dirty_price", a0.dirty_price, "per_face"),
            Quantity("shocked_dirty_price", p1, "per_face"),
            Quantity("price_change_fraction", frac, "fraction"),
            Quantity("modified_duration", a0.modified_duration, "years"),
            Quantity("convexity", a0.convexity, "years^2"),
            Quantity("approx_duration_only", dur_only, "fraction"),
            Quantity("approx_duration_convexity", dur_conv, "fraction"),
        ],
        base_value=position_value,
        shocked_value=shocked,
        approximate=False,
        caveats=["FULL_REPRICING", "APPROXIMATIONS_SHOWN_AS_EXPLANATION_ONLY"],
    )


# ---------------------------------------------------------------------------------------------- spread shocks


def spread_shock_duration(
    value: Decimal,
    spread_duration: Decimal,
    delta_spread: Decimal,
    *,
    label: ScenarioLabel = ScenarioLabel.STRESS,
) -> ScenarioResult:
    """calc §4.7: ``ΔV/V ≈ −D_spread × Δs`` (approximate)."""
    _positive(value, "value")
    _dec(spread_duration, "spread_duration", lo=ZERO)
    _dec(delta_spread, "delta_spread")
    with engine_context():
        frac = -spread_duration * delta_spread
        shocked = value * (ONE + frac)
    return _build(
        scenario_id="SCN_SPREAD_DURATION@1",
        label=label,
        inputs=[
            Quantity("value", value, "INR"),
            Quantity("spread_duration", spread_duration, "years"),
            Quantity("delta_spread", delta_spread, "fraction"),
        ],
        outputs=[Quantity("price_change_fraction", frac, "fraction")],
        base_value=value,
        shocked_value=shocked,
        approximate=True,
        caveats=["APPROXIMATION_SPREAD_DURATION"],
    )


def bond_spread_shock(
    bond: BulletBond,
    *,
    gsec_yield: Decimal,
    spread: Decimal,
    delta_spread: Decimal,
    delta_yield: Decimal = ZERO,
    position_value: Decimal,
    label: ScenarioLabel = ScenarioLabel.STRESS,
) -> ScenarioResult:
    """calc §4.7: ``y = y_gsec + s``; rate and spread shocks combine additively in Δy, then full repricing."""
    _positive(position_value, "position_value")
    for v, n in (
        (gsec_yield, "gsec_yield"),
        (spread, "spread"),
        (delta_spread, "delta_spread"),
        (delta_yield, "delta_yield"),
    ):
        _dec(v, n)
    with engine_context():
        y0 = gsec_yield + spread
        y1 = y0 + delta_yield + delta_spread
    a0, p1, frac, shocked = _bond_reprice(bond, y0, y1, position_value)
    with engine_context():
        approx = -a0.modified_duration * delta_spread
    return _build(
        scenario_id="SCN_SPREAD_FULL_REPRICE@1",
        label=label,
        inputs=[
            *_bond_inputs(bond),
            Quantity("position_value", position_value, "INR"),
            Quantity("gsec_yield", gsec_yield, "fraction"),
            Quantity("spread", spread, "fraction"),
            Quantity("delta_spread", delta_spread, "fraction"),
            Quantity("delta_yield", delta_yield, "fraction"),
        ],
        outputs=[
            Quantity("base_dirty_price", a0.dirty_price, "per_face"),
            Quantity("shocked_dirty_price", p1, "per_face"),
            Quantity("price_change_fraction", frac, "fraction"),
            Quantity("spread_duration", a0.modified_duration, "years"),
            Quantity("approx_spread_duration", approx, "fraction"),
        ],
        base_value=position_value,
        shocked_value=shocked,
        approximate=False,
        caveats=["FULL_REPRICING", "SPREAD_DURATION_EQUALS_MODIFIED_DURATION_FIXED_BULLET"],
    )


# ---------------------------------------------------------------------------------------------- equity


def equity_drawdown_shock(
    value: Decimal,
    shock: Decimal,
    *,
    beta: Decimal,
    label: ScenarioLabel = ScenarioLabel.STRESS,
) -> ScenarioResult:
    """risk §7.5: ``ΔV = V × β × shock`` on an equity-oriented holding (shock ∈ [−1, 0], β ≥ 0)."""
    _positive(value, "value")
    _dec(shock, "shock", lo=-ONE, hi=ZERO)
    _dec(beta, "beta", lo=ZERO)
    with engine_context():
        effective = beta * shock
        if effective < -ONE:
            raise InvalidInput(f"β × shock = {effective} implies a loss above 100 % of a long holding")
        shocked = value * (ONE + effective)
    return _build(
        scenario_id="SCN_EQUITY_BETA@1",
        label=label,
        inputs=[
            Quantity("value", value, "INR"),
            Quantity("shock", shock, "fraction"),
            Quantity("beta", beta, "ratio"),
        ],
        outputs=[Quantity("effective_shock", effective, "fraction")],
        base_value=value,
        shocked_value=shocked,
        approximate=False,
        caveats=["LINEAR_BETA_ASSUMPTION"],
    )


# ---------------------------------------------------------------------------------------------- inflation


@dataclass(frozen=True)
class RealReturnResult:
    value: Decimal
    approximation: Decimal  # r − π, labelled approximation only
    nominal: Decimal
    inflation: Decimal
    method_id: str = "FISHER@1"
    caveats: tuple[str, ...] = ("APPROXIMATION_R_MINUS_PI_IS_LABELLED", "HORIZON_MATCHED_INFLATION_REQUIRED")


def real_return(nominal: Decimal, inflation: Decimal) -> RealReturnResult:
    """calc §2.11 Fisher: ``r_real = (1 + r_nom)/(1 + π) − 1``."""
    _dec(nominal, "nominal", lo=-ONE)
    _dec(inflation, "inflation", lo=-ONE, lo_open=True)
    with engine_context():
        return RealReturnResult(
            value=(ONE + nominal) / (ONE + inflation) - ONE,
            approximation=nominal - inflation,
            nominal=nominal,
            inflation=inflation,
        )


def inflation_scenario(
    amount: Decimal,
    *,
    nominal_return: Decimal,
    base_inflation: Decimal,
    delta_inflation: Decimal,
    label: ScenarioLabel = ScenarioLabel.STRESS,
) -> ScenarioResult:
    """Inflation change → real return.  Values are in today's-rupee (real) terms: ``amount × (1 + r_real)``."""
    _positive(amount, "amount")
    _dec(delta_inflation, "delta_inflation")
    base = real_return(nominal_return, base_inflation)
    with engine_context():
        shocked_pi = base_inflation + delta_inflation
    shocked = real_return(nominal_return, shocked_pi)
    with engine_context():
        base_value = amount * (ONE + base.value)
        shocked_value = amount * (ONE + shocked.value)
        change = shocked.value - base.value
    return _build(
        scenario_id="SCN_INFLATION_FISHER@1",
        label=label,
        inputs=[
            Quantity("amount", amount, "INR"),
            Quantity("nominal_return", nominal_return, "fraction"),
            Quantity("base_inflation", base_inflation, "fraction"),
            Quantity("delta_inflation", delta_inflation, "fraction"),
        ],
        outputs=[
            Quantity("real_return_base", base.value, "fraction"),
            Quantity("real_return_shocked", shocked.value, "fraction"),
            Quantity("real_return_change", change, "fraction"),
            Quantity("approx_real_return_base", base.approximation, "fraction"),
            Quantity("approx_real_return_shocked", shocked.approximation, "fraction"),
        ],
        base_value=base_value,
        shocked_value=shocked_value,
        approximate=False,
        caveats=list(base.caveats),
        measure="real_inr",
    )


# ---------------------------------------------------------------------------------------------- liquidity


def liquidity_deterioration(
    value: Decimal,
    *,
    exit_cost: Decimal,
    haircut: Decimal,
    label: ScenarioLabel = ScenarioLabel.STRESS,
) -> ScenarioResult:
    """Forced exit: price haircut first, then exit cost on the haircut proceeds:
    ``proceeds = V × (1 − haircut) × (1 − exit_cost)``.  Both are assumption parameters in [0, 1)."""
    _positive(value, "value")
    _dec(exit_cost, "exit_cost", lo=ZERO, hi=ONE, hi_open=True)
    _dec(haircut, "haircut", lo=ZERO, hi=ONE, hi_open=True)
    with engine_context():
        after_haircut = value * (ONE - haircut)
        cost_amount = after_haircut * exit_cost
        proceeds = after_haircut - cost_amount
    return _build(
        scenario_id="SCN_LIQUIDITY_HAIRCUT_EXIT_COST@1",
        label=label,
        inputs=[
            Quantity("value", value, "INR"),
            Quantity("exit_cost", exit_cost, "fraction"),
            Quantity("haircut", haircut, "fraction"),
        ],
        outputs=[
            Quantity("haircut_amount", value - after_haircut, "INR"),
            Quantity("exit_cost_amount", cost_amount, "INR"),
            Quantity("net_proceeds", proceeds, "INR"),
        ],
        base_value=value,
        shocked_value=proceeds,
        approximate=False,
        caveats=["PARAMETERS_ARE_ASSUMPTIONS_NOT_VERIFIED"],
    )


# ------------------------------------------------------------------------------ early sale / reinvestment


def _require_coupon_date(bond: BulletBond, what: str) -> None:
    if bond.first_period_fraction != ONE:
        raise InvalidInput(f"{what} is supported only when settling on a coupon date (w = 1)")


def _coupons_with_reinvestment(coupon: Decimal, periods: int, rate: Decimal | None, f: int) -> Decimal:
    with engine_context():
        if rate is None:
            return coupon * Decimal(periods)
        g = _growth(rate, f)
        return sum((coupon * g ** (periods - k) for k in range(1, periods + 1)), ZERO)


def early_sale(
    bond: BulletBond,
    *,
    purchase_price: Decimal,
    exit_after_periods: int,
    exit_yield: Decimal,
    reinvest_rate: Decimal | None = None,
    exit_spread_bp: Decimal = ZERO,
    face_amount: Decimal = HUNDRED,
    label: ScenarioLabel = ScenarioLabel.ILLUSTRATIVE_DOWNSIDE,
) -> ScenarioResult:
    """calc §4.9: sell before maturity after ``m`` coupon periods at ``exit_yield``.

    ``HPR = (P_H × (1 − spread) + coupons received (+ reinvestment) − P_0) / P_0``.  Prices per ``bond.face``;
    ₹ values are scaled to ``face_amount``.
    """
    _require_coupon_date(bond, "early sale")
    _positive(purchase_price, "purchase_price")
    _dec(exit_spread_bp, "exit_spread_bp", lo=ZERO, hi=Decimal(10000), hi_open=True)
    _positive(face_amount, "face_amount")
    if (
        isinstance(exit_after_periods, bool)
        or not isinstance(exit_after_periods, int)
        or not 1 <= exit_after_periods < bond.periods_remaining
    ):
        raise InvalidInput("exit_after_periods must be an int in [1, periods_remaining − 1] (sale before maturity)")
    residual = BulletBond(
        coupon_rate=bond.coupon_rate,
        frequency=bond.frequency,
        periods_remaining=bond.periods_remaining - exit_after_periods,
        face=bond.face,
    )
    p_h = bond_dirty_price(residual, exit_yield)
    coupons = _coupons_with_reinvestment(bond.coupon_amount, exit_after_periods, reinvest_rate, bond.frequency)
    with engine_context():
        p_after = p_h * (ONE - exit_spread_bp * BP)
        proceeds = p_after + coupons
        hpr = (proceeds - purchase_price) / purchase_price
        scale = face_amount / bond.face
        base_value = purchase_price * scale
        shocked_value = proceeds * scale
    caveats = ["EXIT_PRICE_UNKNOWN_ILLUSTRATIVE_YIELD"]
    caveats.append("COUPONS_NOT_REINVESTED" if reinvest_rate is None else "COUPONS_REINVESTED_AT_ASSUMED_RATE")
    if exit_spread_bp > 0:
        caveats.append("EXIT_SPREAD_IS_ASSUMPTION_NOT_VERIFIED")
    inputs = [
        *_bond_inputs(bond),
        Quantity("purchase_price", purchase_price, "per_face"),
        Quantity("exit_after_periods", Decimal(exit_after_periods), "periods"),
        Quantity("exit_yield", exit_yield, "fraction"),
        Quantity("exit_spread_bp", exit_spread_bp, "bp"),
        Quantity("face_amount", face_amount, "INR"),
    ]
    if reinvest_rate is not None:
        inputs.append(Quantity("reinvest_rate", reinvest_rate, "fraction"))
    return _build(
        scenario_id="SCN_EARLY_SALE@1",
        label=label,
        inputs=inputs,
        outputs=[
            Quantity("exit_price", p_h, "per_face"),
            Quantity("exit_price_after_spread", p_after, "per_face"),
            Quantity("coupons_received", coupons, "per_face"),
            Quantity("holding_period_return", hpr, "fraction"),
        ],
        base_value=base_value,
        shocked_value=shocked_value,
        approximate=False,
        caveats=caveats,
    )


def early_sale_grid(
    bond: BulletBond,
    *,
    purchase_price: Decimal,
    exit_after_periods: int,
    base_yield: Decimal,
    shifts_bp: Sequence[int] = DEFAULT_EXIT_GRID_BP,
    reinvest_rate: Decimal | None = None,
    exit_spread_bp: Decimal = ZERO,
    face_amount: Decimal = HUNDRED,
) -> tuple[ScenarioResult, ...]:
    """calc §4.9 yield grid ``y_H ∈ {y_0 − 100, −50, 0, +50, +100, +200 bp}``."""
    _dec(base_yield, "base_yield")
    out: list[ScenarioResult] = []
    for s in shifts_bp:
        with engine_context():
            y = base_yield + Decimal(s) * BP
        out.append(
            early_sale(
                bond,
                purchase_price=purchase_price,
                exit_after_periods=exit_after_periods,
                exit_yield=y,
                reinvest_rate=reinvest_rate,
                exit_spread_bp=exit_spread_bp,
                face_amount=face_amount,
            )
        )
    return tuple(out)


def reinvestment_scenario(
    bond: BulletBond,
    *,
    purchase_price: Decimal,
    ytm: Decimal,
    reinvest_rate: Decimal,
    face_amount: Decimal = HUNDRED,
    label: ScenarioLabel = ScenarioLabel.ILLUSTRATIVE_DOWNSIDE,
) -> ScenarioResult:
    """calc §4.8: hold to maturity with coupons reinvested at ``reinvest_rate`` instead of the YTM.

    ``FV = Σ coupon × (1 + r/f)^(remaining periods) + redemption``.  Base = reinvestment at the YTM.
    """
    _require_coupon_date(bond, "reinvestment scenario")
    _positive(purchase_price, "purchase_price")
    _positive(face_amount, "face_amount")
    _dec(ytm, "ytm")
    _dec(reinvest_rate, "reinvest_rate")
    n, f = bond.periods_remaining, bond.frequency
    fv = _coupons_with_reinvestment(bond.coupon_amount, n, reinvest_rate, f) + bond.face
    fv_ytm = _coupons_with_reinvestment(bond.coupon_amount, n, ytm, f) + bond.face
    with engine_context():
        growth = fv / purchase_price
        years = Decimal(n) / Decimal(f)
        eff = growth ** (ONE / years) - ONE
        bey = Decimal(f) * (growth ** (ONE / Decimal(n)) - ONE)
        ytm_eff = _growth(ytm, f) ** f - ONE
        scale = face_amount / bond.face
    return _build(
        scenario_id="SCN_REINVESTMENT@1",
        label=label,
        inputs=[
            *_bond_inputs(bond),
            Quantity("purchase_price", purchase_price, "per_face"),
            Quantity("ytm", ytm, "fraction"),
            Quantity("reinvest_rate", reinvest_rate, "fraction"),
            Quantity("face_amount", face_amount, "INR"),
        ],
        outputs=[
            Quantity("future_value", fv, "per_face"),
            Quantity("future_value_at_ytm", fv_ytm, "per_face"),
            Quantity("realised_effective_annual", eff, "fraction"),
            Quantity("realised_bond_equivalent", bey, "fraction"),
            Quantity("ytm_effective_annual", ytm_eff, "fraction"),
        ],
        base_value=fv_ytm * scale,
        shocked_value=fv * scale,
        approximate=False,
        caveats=["HELD_TO_MATURITY_NO_DEFAULT", "REINVESTMENT_RATE_IS_ASSUMPTION"],
    )


# ---------------------------------------------------------------------------------------------- portfolio


def aggregate_portfolio(
    portfolio_value: Decimal,
    components: Sequence[tuple[str, ScenarioResult]],
    *,
    scenario_name: str,
) -> PortfolioScenarioResult:
    """risk §7.5: ``Loss = Σ_i ΔV_i`` in ₹ and as % of the portfolio.  Never probability-weighted."""
    _positive(portfolio_value, "portfolio_value")
    if not components:
        raise InvalidInput("no scenario components supplied")
    ids = [hid for hid, _ in components]
    if len(set(ids)) != len(ids):
        raise InvalidInput("duplicate holding ids in scenario aggregation")
    measures = {r.measure for _, r in components}
    if len(measures) != 1:
        raise InvalidInput(f"cannot add scenario impacts in different measures: {sorted(measures)}")
    if any(r.probability_weighted for _, r in components):
        raise InvalidInput("probability-weighted components cannot be aggregated silently")
    caveats: list[str] = []
    for _, r in components:
        caveats.extend(r.caveats)
    with engine_context():
        total = sum((r.impact for _, r in components), ZERO)
        fraction = total / portfolio_value
    return PortfolioScenarioResult(
        scenario_name=scenario_name,
        label=ScenarioLabel.STRESS,
        portfolio_value=portfolio_value,
        components=tuple((hid, r.impact) for hid, r in components),
        component_inputs=tuple((hid, r.scenario_id, r.inputs) for hid, r in components),
        total_impact=total,
        impact_fraction=fraction,
        approximate=any(r.approximate for _, r in components),
        measure=measures.pop(),
        caveats=tuple(dict.fromkeys(caveats)),
    )
