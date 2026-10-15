"""Property-based tests for returns and costs (calculation-methodology.md §5)."""

from datetime import date, timedelta
from decimal import Decimal

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from iip.engine.costs import LoadTier, Lot, exit_load, stamp_duty
from iip.engine.determinism import canonical_json
from iip.engine.errors import NumericalError
from iip.engine.money import D, engine_context
from iip.engine.returns import CashFlow, TwrObservation, XirrOutcome, cagr, twr, xirr

BASE = date(2020, 1, 1)

amounts = st.decimals(min_value=Decimal("1.00"), max_value=Decimal("10000000.00"), places=2)
ratios = st.decimals(min_value=Decimal("0.20"), max_value=Decimal("5.00"), places=4)
day_offsets = st.integers(min_value=0, max_value=3650)


@settings(max_examples=150, deadline=None)
@given(v0=amounts, ratio=ratios, days=st.integers(min_value=180, max_value=5000))
def test_cagr_equals_xirr_for_single_out_and_in(v0: Decimal, ratio: Decimal, days: int) -> None:
    with engine_context():
        v1 = v0 * ratio
    end = BASE + timedelta(days=days)
    c = cagr(v0, v1, BASE, end).value
    assume(Decimal("-0.98") < c < Decimal("9.9"))
    x = xirr([CashFlow(BASE, -v0), CashFlow(end, v1)])
    assert x.outcome is XirrOutcome.SOLVED
    assert x.rate is not None
    with engine_context():
        assert abs(x.rate - c) <= Decimal("1e-8")


flow_lists = st.lists(
    st.tuples(day_offsets, st.decimals(min_value=Decimal("-50000"), max_value=Decimal("50000"), places=2)),
    min_size=2,
    max_size=8,
)


def _xirr_outcome(flows: list[CashFlow]) -> str:
    """Canonical result, or the typed error (spec §2.6 step 5 may refuse a root: still deterministic)."""
    try:
        return canonical_json(xirr(flows))
    except NumericalError as exc:
        return f"NumericalError:{exc}"


@settings(max_examples=150, deadline=None)
@given(raw=flow_lists, data=st.data())
def test_xirr_invariant_to_flow_order(raw: list[tuple[int, Decimal]], data: st.DataObject) -> None:
    flows = [CashFlow(BASE + timedelta(days=d), a) for d, a in raw]
    shuffled = data.draw(st.permutations(flows))
    assert _xirr_outcome(flows) == _xirr_outcome(list(shuffled))


@settings(max_examples=150, deadline=None)
@given(gross=amounts)
def test_zero_stamp_rate_never_reduces_amount(gross: Decimal) -> None:
    r = stamp_duty(gross, trade_date=date(2026, 1, 1), rate=D(0))
    assert r.invested == gross
    assert r.stamp_duty == 0


@settings(max_examples=150, deadline=None)
@given(gross=amounts)
def test_stamp_duty_never_increases_amount(gross: Decimal) -> None:
    r = stamp_duty(gross, trade_date=date(2026, 1, 1))
    assert r.invested <= gross
    assert r.stamp_duty >= 0


@settings(max_examples=150, deadline=None)
@given(
    units=st.decimals(min_value=Decimal("0.001"), max_value=Decimal("1000000"), places=3),
    nav=st.decimals(min_value=Decimal("1.0000"), max_value=Decimal("5000.0000"), places=4),
    rate=st.decimals(min_value=Decimal("0.0001"), max_value=Decimal("0.05"), places=4),
    held=st.integers(min_value=0, max_value=800),
)
def test_positive_exit_load_never_increases_proceeds(units: Decimal, nav: Decimal, rate: Decimal, held: int) -> None:
    redeem = date(2026, 10, 15)
    lots = [Lot(redeem - timedelta(days=held), units)]
    loaded = exit_load(lots, units, redeem, nav, (LoadTier(365, rate),))
    free = exit_load(lots, units, redeem, nav, ())
    assert loaded.net <= free.net
    assert loaded.load >= 0


@settings(max_examples=100, deadline=None)
@given(raw=flow_lists)
def test_xirr_deterministic(raw: list[tuple[int, Decimal]]) -> None:
    flows = [CashFlow(BASE + timedelta(days=d), a) for d, a in raw]
    assert _xirr_outcome(flows) == _xirr_outcome(flows)


@settings(max_examples=100, deadline=None)
@given(v0=amounts, ratio=ratios, days=st.integers(min_value=1, max_value=5000))
def test_cagr_deterministic(v0: Decimal, ratio: Decimal, days: int) -> None:
    with engine_context():
        v1 = v0 * ratio
    end = BASE + timedelta(days=days)
    assert canonical_json(cagr(v0, v1, BASE, end)) == canonical_json(cagr(v0, v1, BASE, end))


@settings(max_examples=100, deadline=None)
@given(
    values=st.lists(st.decimals(min_value=Decimal("1"), max_value=Decimal("100000"), places=2), min_size=2, max_size=10)
)
def test_twr_deterministic_and_flow_free_equals_price_ratio(values: list[Decimal]) -> None:
    obs = [TwrObservation(BASE + timedelta(days=i), v, D(0)) for i, v in enumerate(values)]
    a = twr(obs)
    assert canonical_json(a) == canonical_json(twr(obs))
    with engine_context():
        expected = values[-1] / values[0] - 1
        assert abs(a.value - expected) <= Decimal("1e-26") * max(Decimal(1), abs(expected))
