"""``actions.rebalance@1`` (design-risk-first.md §5.6): cash-flow-first, FIFO per folio, never between lots.

All values are FICTIONAL and synthetic.  The oracle at the bottom is an independent re-implementation of the
spec in exact ``fractions.Fraction`` arithmetic with different data structures (ADR-0011).
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import date
from decimal import Decimal
from fractions import Fraction

import pytest

from iip.engine.actions.rebalance import (
    FORMULA_ID,
    HeldLot,
    RebalanceParams,
    SaleSource,
    SleeveState,
    TaxTreatment,
    plan_rebalance,
)
from iip.engine.costs import LoadTier
from iip.engine.dates import add_months
from iip.engine.errors import InvalidInput

AS_OF = date(2026, 10, 15)
EQ_TAX = TaxTreatment(
    st_rate=Decimal("0.20"), lt_rate=Decimal("0.125"), lt_threshold_months=12, exemption_eligible=True
)
LOAD_1Y = (LoadTier(365, Decimal("0.01")),)
STT = Decimal("0.00001")


def _params(**kw: object) -> RebalanceParams:
    base = RebalanceParams(
        band=Decimal("0.05"),
        is_review_date=True,
        allow_sales=False,
        allow_exit_load_sales=False,
        lt_wait_days=45,
        cess_rate=Decimal("0.04"),
        ltcg_exemption_remaining=Decimal("10000"),
    )
    return replace(base, **kw)  # type: ignore[arg-type]


SLEEVES = (
    SleeveState("EQ", Decimal("710000"), Decimal("0.60")),
    SleeveState("DEBT", Decimal("290000"), Decimal("0.40")),
)


def _src(iid: str, folio: str, nav: str, lots: tuple[HeldLot, ...], **kw: object) -> SaleSource:
    base = SaleSource(
        instrument_id=iid,
        folio=folio,
        sleeve_id="EQ",
        nav=Decimal(nav),
        lots=lots,
        exit_load=LOAD_1Y,
        tax=EQ_TAX,
        stt_rate=STT,
    )
    return replace(base, **kw)  # type: ignore[arg-type]


SRC_A = _src("A", "F1", "100", (HeldLot("a1", date(2020, 1, 1), Decimal("1000"), Decimal("50")),))
SRC_B = _src("B", "F2", "200", (HeldLot("b1", date(2021, 1, 1), Decimal("2000"), Decimal("190")),))


# ---------------------------------------------------------------- trigger and cash-flow-first


def test_drift_inside_band_passes() -> None:
    sleeves = (
        SleeveState("EQ", Decimal("620000"), Decimal("0.6")),
        SleeveState("D", Decimal("380000"), Decimal("0.4")),
    )
    plan = plan_rebalance(sleeves, as_of=AS_OF, params=_params())
    assert plan.status == "PASS"
    assert plan.steps == ()
    assert plan.formula_id == FORMULA_ID == "actions.rebalance@1"
    assert plan.drift_before[0].drift == Decimal("0.02")


def test_out_of_cycle_drift_is_shown_but_not_actioned() -> None:
    plan = plan_rebalance(SLEEVES, as_of=AS_OF, params=_params(is_review_date=False), contributions=(Decimal(10000),))
    assert plan.status == "PASS"
    assert plan.triggered is False
    assert "DRIFT_SHOWN_NOT_DUE" in plan.flags
    assert plan.drift_before[0].drift == Decimal("0.11")
    assert plan.steps == ()


def test_l3_breach_triggers_outside_review_date() -> None:
    plan = plan_rebalance(
        SLEEVES, as_of=AS_OF, params=_params(is_review_date=False, l3_breach=True), contributions=(Decimal(10000),)
    )
    assert plan.triggered is True
    assert plan.status == "ACTION"


def test_redirect_only_when_sales_not_allowed() -> None:
    plan = plan_rebalance(SLEEVES, as_of=AS_OF, params=_params(), contributions=(Decimal(10000),) * 4)
    assert plan.status == "ACTION"
    assert plan.contributions_used == 4
    assert [(s.verb, s.sleeve_id, s.amount) for s in plan.steps] == [("REDIRECT_SIP", "DEBT", Decimal("40000.00"))]
    # 710000 / 1040000 − 0.60 = 0.0826923… (still outside the band, reported honestly)
    assert plan.drift_after[0].drift.quantize(Decimal("0.0001")) == Decimal("0.0827")
    assert "SALES_NOT_ALLOWED" in plan.flags


def test_redirect_stops_once_drift_below_half_band() -> None:
    plan = plan_rebalance(SLEEVES, as_of=AS_OF, params=_params(allow_sales=True), contributions=(Decimal(50000),) * 10)
    # after 3 × ₹50,000 all to DEBT: 710000/1150000 = 0.6174 → drift 0.0174 < 0.025
    assert plan.contributions_used == 3
    assert [(s.verb, s.amount) for s in plan.steps] == [("REDIRECT_SIP", Decimal("150000.00"))]
    assert all(s.verb != "REDEEM" for s in plan.steps)  # cash flows closed it: no sale


# ---------------------------------------------------------------- sales: cost per rupee across schemes/folios


def test_sale_picks_cheapest_source_after_contributions() -> None:
    plan = plan_rebalance(
        SLEEVES,
        as_of=AS_OF,
        params=_params(allow_sales=True),
        contributions=(Decimal(10000),) * 4,
        sources=(SRC_A, SRC_B),
    )
    redeem = [s for s in plan.steps if s.verb == "REDEEM"]
    # excess = 710000 − 0.6 × 1040000 = 86000. A: gain 43000, ₹10,000 exempt → tax ₹4,290 (cpr ≈ 0.0499);
    # B: gain 4300 fully exempt → cpr = STT only. B wins.
    assert len(redeem) == 1
    step = redeem[0]
    assert (step.instrument_id, step.folio) == ("B", "F2")
    assert step.units == Decimal("430")
    assert step.amount == Decimal("86000.00")
    assert step.tax.stcg == step.tax.ltcg == step.tax.cess == Decimal("0.00")
    assert step.cost.stt == Decimal("0.86")
    assert step.cost.exit_load == Decimal("0.00")
    assert [lc.lot_id for lc in step.lots_consumed] == ["b1"]
    assert plan.exemption_used == Decimal("4300")
    invest = [s for s in plan.steps if s.verb == "INVEST"]
    assert len(invest) == 1 and invest[0].sleeve_id == "DEBT"
    assert invest[0].amount == Decimal("85999.14")
    assert invest[0].cost.stamp == Decimal("4.30")  # 85999.14 × 0.00005 / 1.00005 = 4.2997… → 4.30
    assert abs(plan.residual_max_drift) < Decimal("0.0001")


def test_exemption_is_used_first_when_it_covers_the_gain() -> None:
    plan = plan_rebalance(
        SLEEVES,
        as_of=AS_OF,
        params=_params(allow_sales=True, ltcg_exemption_remaining=Decimal("125000")),
        contributions=(Decimal(10000),) * 4,
        sources=(SRC_A, SRC_B),
    )
    redeem = [s for s in plan.steps if s.verb == "REDEEM"]
    # both sources are fully exempt → equal cost per rupee → tie broken by (instrument_id, folio)
    assert [(s.instrument_id, s.units) for s in redeem] == [("A", Decimal("860"))]
    assert plan.exemption_used == Decimal("43000")


def test_fifo_never_skips_an_expensive_oldest_lot_to_reach_a_cheap_one() -> None:
    a = _src(
        "A",
        "F1",
        "100",
        (
            HeldLot("a2", date(2023, 1, 1), Decimal("5000"), Decimal("100")),  # zero gain: cheapest lot anywhere
            HeldLot("a1", date(2019, 1, 1), Decimal("5000"), Decimal("10")),  # oldest: large gain, must go first
        ),
    )
    plan = plan_rebalance(
        SLEEVES,
        as_of=AS_OF,
        params=_params(allow_sales=True, ltcg_exemption_remaining=Decimal(0)),
        contributions=(Decimal(10000),) * 4,
        sources=(a, SRC_B),
    )
    redeem = [s for s in plan.steps if s.verb == "REDEEM"]
    # A's next FIFO lot is a1 (tax 90/unit × 12.5 % × 1.04 per ₹100) vs B's 10/unit per ₹200: B is cheaper.
    # A per-lot optimiser would have sold a2 (zero tax); FIFO forbids it.
    assert [(s.instrument_id, s.units) for s in redeem] == [("B", Decimal("430"))]
    assert redeem[0].tax.ltcg == Decimal("537.50")  # 4300 × 0.125
    assert redeem[0].tax.cess == Decimal("21.50")  # 537.50 × 0.04


def test_exit_load_window_blocks_unless_allowed() -> None:
    a = _src("A", "F1", "100", (HeldLot("a0", date(2026, 9, 1), Decimal("2000"), Decimal("100")),))
    plan = plan_rebalance(
        SLEEVES,
        as_of=AS_OF,
        params=_params(allow_sales=True),
        contributions=(Decimal(10000),) * 4,
        sources=(a,),
    )
    assert [(b.instrument_id, b.lot_id, b.reason) for b in plan.blocked] == [("A", "a0", "inside_exit_load_window")]
    assert not [s for s in plan.steps if s.verb == "REDEEM"]


def test_exit_load_lots_sold_only_when_allowed() -> None:
    a = _src("A", "F1", "100", (HeldLot("a0", date(2026, 9, 1), Decimal("2000"), Decimal("100")),))
    plan = plan_rebalance(
        SLEEVES,
        as_of=AS_OF,
        params=_params(allow_sales=True, allow_exit_load_sales=True, lt_wait_days=0),
        contributions=(Decimal(10000),) * 4,
        sources=(a,),
    )
    (step,) = [s for s in plan.steps if s.verb == "REDEEM"]
    assert step.units == Decimal("860")
    assert step.cost.exit_load == Decimal("860.00")  # 1 % of ₹86,000
    assert step.tax.stcg == Decimal("0.00")  # no gain (cost = NAV)
    assert step.lots_consumed[0].gain_type == "STCG"


def test_short_term_lot_turning_long_term_soon_waits() -> None:
    acquired = date(2025, 11, 1)  # turns long-term on 2026-11-02, 18 days after AS_OF
    a = _src("A", "F1", "100", (HeldLot("a0", acquired, Decimal("2000"), Decimal("60")),), exit_load=())
    plan = plan_rebalance(
        SLEEVES,
        as_of=AS_OF,
        params=_params(allow_sales=True),
        contributions=(Decimal(10000),) * 4,
        sources=(a,),
    )
    (blk,) = plan.blocked
    assert blk.reason == "turns_long_term_soon"
    assert blk.wait_until == date(2026, 11, 2)
    assert add_months(acquired, 12) == date(2026, 11, 1)
    assert "SALE_SOURCES_EXHAUSTED" in plan.flags


def test_locked_in_and_unknown_inputs_block_the_source() -> None:
    elss = _src("E", "F9", "100", (HeldLot("e1", date(2024, 1, 1), Decimal("5000"), Decimal("40")),), lock_in_days=1095)
    nobasis = _src("N", "F8", "100", (HeldLot("n1", date(2020, 1, 1), Decimal("5000"), None),))
    noload = _src("U", "F7", "100", (HeldLot("u1", date(2026, 1, 1), Decimal("5000"), Decimal("90")),), exit_load=None)
    notax = _src(
        "T",
        "F6",
        "100",
        (HeldLot("t1", date(2020, 1, 1), Decimal("5000"), Decimal("90")),),
        tax=replace(EQ_TAX, st_rate=None),
    )
    notax_st = replace(notax, lots=(HeldLot("t1", date(2026, 1, 1), Decimal("5000"), Decimal("90")),), exit_load=())
    plan = plan_rebalance(
        SLEEVES,
        as_of=AS_OF,
        params=_params(allow_sales=True),
        contributions=(Decimal(10000),) * 4,
        sources=(elss, nobasis, noload, notax_st),
    )
    assert {(b.instrument_id, b.reason) for b in plan.blocked} == {
        ("E", "locked_in"),
        ("N", "cost_basis_unknown"),
        ("U", "exit_load_unknown"),
        ("T", "tax_rate_unknown"),
    }
    assert not [s for s in plan.steps if s.verb == "REDEEM"]


def test_missing_tax_context_abstains_on_sales_only() -> None:
    plan = plan_rebalance(
        SLEEVES,
        as_of=AS_OF,
        params=_params(allow_sales=True, ltcg_exemption_remaining=None),
        contributions=(Decimal(10000),) * 4,
        sources=(SRC_A,),
    )
    assert [a.code for a in plan.abstentions] == ["tax_context_missing"]
    assert [s.verb for s in plan.steps] == ["REDIRECT_SIP"]


def test_missing_target_abstains() -> None:
    sleeves = (SleeveState("EQ", Decimal("1"), None), SleeveState("D", Decimal("1"), Decimal("1")))
    plan = plan_rebalance(sleeves, as_of=AS_OF, params=_params())
    assert plan.status == "ABSTAIN"
    assert plan.abstentions[0].code == "target_missing"


@pytest.mark.parametrize(
    "sleeves",
    [
        (SleeveState("EQ", Decimal("1"), Decimal("0.5")), SleeveState("D", Decimal("1"), Decimal("0.4"))),
        (SleeveState("EQ", Decimal("-1"), Decimal("0.5")), SleeveState("D", Decimal("1"), Decimal("0.5"))),
        (SleeveState("EQ", Decimal("1"), Decimal("0.5")), SleeveState("EQ", Decimal("1"), Decimal("0.5"))),
    ],
)
def test_invalid_sleeves_raise(sleeves: tuple[SleeveState, ...]) -> None:
    with pytest.raises(InvalidInput):
        plan_rebalance(sleeves, as_of=AS_OF, params=_params())


def test_plan_is_deterministic() -> None:
    kw = {"as_of": AS_OF, "params": _params(allow_sales=True), "contributions": (Decimal(10000),) * 4}
    assert plan_rebalance(SLEEVES, sources=(SRC_A, SRC_B), **kw) == plan_rebalance(  # type: ignore[arg-type]
        SLEEVES,
        sources=(SRC_B, SRC_A),
        **kw,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------- oracle (independent, exact Fractions)


def _F(x: Decimal | int) -> Fraction:
    return Fraction(str(x))


def _oracle_months_later(d: date, n: int) -> date:
    import calendar

    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def _oracle_sales(
    need: Fraction, sources: list[SaleSource], exemption: Fraction, cess: Fraction
) -> tuple[dict[tuple[str, str], list[tuple[str, Fraction]]], Fraction]:
    """Greedy over each source's next FIFO lot (sources never skip a lot), cheapest marginal cost per rupee first."""
    queues = {(s.instrument_id, s.folio): sorted(s.lots, key=lambda lot: lot.allotment_date) for s in sources}
    left = {k: [_F(lot.units) for lot in v] for k, v in queues.items()}
    by_key = {(s.instrument_id, s.folio): s for s in sources}
    sold: dict[tuple[str, str], list[tuple[str, Fraction]]] = {}
    milli = Fraction(1, 1000)
    while need > 0:
        best = None
        for key in sorted(queues):
            idx = next((i for i, u in enumerate(left[key]) if u > 0), None)
            if idx is None:
                continue
            src, lot = by_key[key], queues[key][idx]
            nav = _F(src.nav)
            raw = need / nav  # a partial lot is rounded UP to 0.001 unit so the need is always covered
            units = min(left[key][idx], Fraction(-((-raw) // milli)) * milli)
            gross = units * nav
            gain = units * (nav - _F(lot.cost_per_unit))  # type: ignore[arg-type]
            is_lt = AS_OF > _oracle_months_later(lot.allotment_date, 12)
            exempt = min(max(gain, Fraction(0)), exemption) if is_lt else Fraction(0)
            rate = _F(src.tax.lt_rate if is_lt else src.tax.st_rate)  # type: ignore[arg-type]
            tax = max(gain - exempt, Fraction(0)) * rate * (1 + cess)
            cpr = (tax + gross * _F(src.stt_rate)) / gross
            if best is None or cpr < best[0]:
                best = (cpr, key, idx, units, gross, exempt)
        if best is None:
            break
        _, key, idx, units, gross, exempt = best
        left[key][idx] -= units
        exemption -= exempt
        need -= gross
        sold.setdefault(key, []).append((queues[key][idx].lot_id, units))
    return sold, need


def _rand_case(rng: random.Random) -> tuple[list[SaleSource], int]:
    sources = []
    for i in range(rng.randint(1, 4)):
        lots = []
        for j in range(rng.randint(1, 3)):
            y = rng.choice([2019, 2020, 2022, 2024, 2026])
            lots.append(
                HeldLot(
                    f"s{i}l{j}",
                    date(y, rng.randint(1, 9), rng.randint(1, 28)),
                    Decimal(rng.randint(50, 3000)),
                    Decimal(rng.randint(20, 140)),
                )
            )
        sources.append(_src(f"I{i % 3}", f"F{i}", str(rng.randint(60, 160)), tuple(lots), exit_load=()))
    return sources, rng.randint(1000, 400000)


@pytest.mark.parametrize("seed", range(40))
def test_sales_match_independent_oracle(seed: int) -> None:
    rng = random.Random(seed)
    sources, eq_excess = _rand_case(rng)
    exemption = Decimal(rng.choice([0, 20000, 125000]))
    eq_mv = sum((s.nav * sum((lot.units for lot in s.lots), Decimal(0)) for s in sources), Decimal(0))
    # choose DEBT so that the EQ excess over a 50 % target equals eq_excess (capped by what is held)
    eq_excess = min(eq_excess, int(eq_mv / 2) - 1)
    debt = eq_mv - 2 * eq_excess
    if debt <= 0:
        pytest.skip("synthetic case has no feasible debt sleeve")
    sleeves = (SleeveState("EQ", eq_mv, Decimal("0.5")), SleeveState("DEBT", debt, Decimal("0.5")))
    params = _params(allow_sales=True, band=Decimal("0.0001"), ltcg_exemption_remaining=exemption, lt_wait_days=0)
    plan = plan_rebalance(sleeves, as_of=AS_OF, params=params, sources=sources)
    sold, _ = _oracle_sales(_F(eq_excess), sources, _F(exemption), Fraction(104, 100))
    got = {
        (s.instrument_id, s.folio): [(lc.lot_id, _F(lc.units)) for lc in s.lots_consumed]
        for s in plan.steps
        if s.verb == "REDEEM"
    }
    # The engine aggregates repeated picks of the same lot into one entry; merge the oracle the same way.
    merged: dict[tuple[str, str], list[tuple[str, Fraction]]] = {}
    for key, picks in sold.items():
        out: list[tuple[str, Fraction]] = []
        for lot_id, units in picks:
            if out and out[-1][0] == lot_id:
                out[-1] = (lot_id, out[-1][1] + units)
            else:
                out.append((lot_id, units))
        merged[key] = out
    assert got == merged
    # FIFO invariant: consumed lots form a prefix of each source's allotment order
    for s in plan.steps:
        if s.verb != "REDEEM":
            continue
        src = next(x for x in sources if (x.instrument_id, x.folio) == (s.instrument_id, s.folio))
        order = [lot.lot_id for lot in sorted(src.lots, key=lambda lot: lot.allotment_date)]
        ids = [lc.lot_id for lc in s.lots_consumed]
        assert ids == order[: len(ids)]
