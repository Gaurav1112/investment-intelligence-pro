"""Independent cross-checks: XIRR vs pyxirr and a separate scipy brentq; CAGR vs plain arithmetic."""

import math
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pytest
import pyxirr
from scipy.optimize import brentq

from iip.engine.money import D, engine_context
from iip.engine.returns import CashFlow, TwrObservation, XirrOutcome, cagr, twr, xirr

pytestmark = pytest.mark.oracle

RATE_TOL = 1e-8  # §5: XIRR vs brentq / Excel, 1e-8 rate
PYXIRR_TOL = 1e-8  # §5 tolerance; pyxirr stops its own Newton loosely (X-4: 0.0499999995), observed ≤ 1e-9


def _cf(y: int, m: int, d: int, amount: str) -> CashFlow:
    return CashFlow(date(y, m, d), D(amount))


FIXTURES = {
    "X-1": [_cf(2025, 1, 1, "-10000"), _cf(2026, 1, 1, "11000")],
    "X-2": [_cf(2024, 1, 1, "-10000"), _cf(2025, 1, 1, "11000")],
    "X-3": [
        _cf(2025, 1, 10, "-5000"),
        _cf(2025, 2, 10, "-5000"),
        _cf(2025, 3, 10, "-5000"),
        _cf(2025, 4, 10, "-5000"),
        _cf(2025, 10, 10, "21500"),
    ],
    "X-4": [_cf(2024, 2, 29, "-10000"), _cf(2025, 2, 28, "500"), _cf(2026, 2, 28, "10500")],
    "X-7": [_cf(2024, 1, 1, "-10000"), _cf(2025, 1, 1, "-30000"), _cf(2026, 1, 1, "36000")],
}


def _independent_brentq(flows: list[CashFlow]) -> float:
    d0 = min(f.on for f in flows)
    t = np.array([(f.on - d0).days / 365.0 for f in flows])
    cf = np.array([float(f.amount) for f in flows])

    def npv(r: float) -> float:
        return float(np.sum(cf / np.power(1.0 + r, t)))

    return float(brentq(npv, -0.95, 9.0, xtol=1e-14, maxiter=500))


def _pyxirr(flows: list[CashFlow]) -> float:
    return float(pyxirr.xirr([f.on for f in flows], [float(f.amount) for f in flows]))


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_xirr_fixtures_vs_oracles(name: str) -> None:
    flows = FIXTURES[name]
    r = xirr(flows)
    assert r.rate is not None
    ours = float(r.rate)
    assert abs(ours - _independent_brentq(flows)) <= RATE_TOL
    assert abs(ours - _pyxirr(flows)) <= PYXIRR_TOL


def test_x5_both_roots_vs_brentq() -> None:
    flows = [_cf(2025, 1, 1, "-100"), _cf(2026, 1, 1, "230"), _cf(2027, 1, 1, "-132")]

    def npv(r: float) -> float:
        return -100 + 230 / (1 + r) - 132 / (1 + r) ** 2

    expected = [brentq(npv, 0.05, 0.15, xtol=1e-14), brentq(npv, 0.15, 0.3, xtol=1e-14)]
    r = xirr(flows)
    assert r.outcome is XirrOutcome.MULTIPLE_ROOTS
    assert [abs(float(a) - b) <= RATE_TOL for a, b in zip(r.roots, expected, strict=True)] == [True, True]


def _random_well_posed(rng: np.random.Generator) -> tuple[list[CashFlow], float]:
    """Outflows first, one terminal inflow priced at a known rate → one sign change, one root."""
    rate = float(rng.uniform(-0.5, 2.0))
    n_out = int(rng.integers(1, 8))
    offsets = sorted({int(x) for x in rng.integers(0, 2000, size=n_out)} | {0})
    end = offsets[-1] + int(rng.integers(30, 2000))
    outs = [round(float(rng.uniform(100, 100000)), 2) for _ in offsets]
    fv = sum(a * (1 + rate) ** ((end - o) / 365) for a, o in zip(outs, offsets, strict=True))
    base = date(2015, 1, 1)
    flows = [CashFlow(base + timedelta(days=o), D(f"{-a:.2f}")) for a, o in zip(outs, offsets, strict=True)]
    flows.append(CashFlow(base + timedelta(days=end), D(f"{fv:.2f}")))
    return flows, rate


def test_xirr_random_well_posed_vs_oracles() -> None:
    rng = np.random.default_rng(20261015)
    checked = 0
    for _ in range(300):
        flows, rate = _random_well_posed(rng)
        r = xirr(flows)
        assert r.outcome is XirrOutcome.SOLVED, (flows, rate)
        assert r.rate is not None
        ours = float(r.rate)
        assert abs(ours - _independent_brentq(flows)) <= RATE_TOL
        assert abs(ours - _pyxirr(flows)) <= PYXIRR_TOL
        # The generating rate is recovered up to paise rounding of the cash flows.
        assert abs(ours - rate) <= 1e-3
        checked += 1
    assert checked == 300


@pytest.mark.parametrize(
    ("v0", "v1", "start", "end"),
    [
        ("100", "112", date(2025, 1, 1), date(2026, 1, 1)),
        ("100", "121", date(2024, 1, 1), date(2026, 1, 1)),
        ("10.0000", "13.3100", date(2023, 10, 13), date(2026, 10, 13)),
        ("1000", "1001", date(2026, 1, 1), date(2026, 1, 8)),
        ("5000", "3100", date(2019, 3, 15), date(2026, 3, 15)),
    ],
)
def test_cagr_vs_arithmetic(v0: str, v1: str, start: date, end: date) -> None:
    ours = float(cagr(D(v0), D(v1), start, end).value)
    expected = (float(v1) / float(v0)) ** (365 / (end - start).days) - 1
    assert math.isclose(ours, expected, rel_tol=0, abs_tol=1e-10)


def test_cagr_vs_xirr_oracle() -> None:
    ours = float(cagr(D(100), D(121), date(2024, 1, 1), date(2026, 1, 1)).value)
    assert abs(ours - pyxirr.xirr([date(2024, 1, 1), date(2026, 1, 1)], [-100.0, 121.0])) <= PYXIRR_TOL


def test_twr_vs_modified_dietz_small_flows() -> None:
    # §2.5 oracle: Modified Dietz agrees within 1 bp when flows are small.
    values = ["100000", "100400", "100900", "101100", "101700"]
    flows = ["0", "100", "0", "-50", "0"]
    obs = [
        TwrObservation(date(2026, 1, 1) + timedelta(days=i), D(v), D(f))
        for i, (v, f) in enumerate(zip(values, flows, strict=True))
    ]
    ours = twr(obs).value
    with engine_context():
        total_days = Decimal(4)
        net_flows = sum((D(f) for f in flows[1:-1]), Decimal(0))
        weighted = sum(
            (D(f) * (total_days - Decimal(i)) / total_days for i, f in enumerate(flows) if 0 < i < 4),
            Decimal(0),
        )
        dietz = (D(values[-1]) - D(values[0]) - net_flows) / (D(values[0]) + weighted)
        assert abs(ours - dietz) <= Decimal("0.0001")
