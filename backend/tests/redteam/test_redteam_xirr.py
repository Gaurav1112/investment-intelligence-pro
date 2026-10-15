"""Red team RT-28: two XIRR roots inside one grid cell must be "not determinable", never "no root" (or one root).

Flows are hand-built: −100, +a, −b one year apart have IRRs r where (1+r) solves −100y² + a·y − b = 0, so roots at
y₁, y₂ need a = 100(y₁ + y₂) and b = 100·y₁·y₂. ACT/365F: 2025-01-01 → 2026-01-01 → 2027-01-01 are 365 days each.
"""

from datetime import date
from decimal import Decimal

import pytest

from iip.engine.money import D
from iip.engine.returns import CashFlow, XirrOutcome, xirr

D0, D1, D2 = date(2025, 1, 1), date(2026, 1, 1), date(2027, 1, 1)


def _flows(a: str, b: str) -> list[CashFlow]:
    return [CashFlow(D0, D("-100")), CashFlow(D1, D(a)), CashFlow(D2, D("-" + b))]


def test_rt28_two_roots_inside_one_cell_are_not_determinable() -> None:
    """Roots 11 % and 19 % both lie inside the grid cell [10 %, 20 %]; XNPV is negative at both ends (no bracket).
    Before: NO_SOLUTION "no root". Now: NOT_DETERMINABLE, both roots found and verified, no rate, no headline."""
    res = xirr(_flows("230", "132.09"))
    assert res.outcome is XirrOutcome.NOT_DETERMINABLE
    assert res.rate is None and not res.headline_allowed
    assert "IRR_NOT_DETERMINABLE" in res.flags
    assert res.reason is not None and "not determinable" in res.reason
    assert len(res.roots) == 2
    assert res.roots[0] == pytest.approx(Decimal("0.11"), abs=Decimal("1e-8"))
    assert res.roots[1] == pytest.approx(Decimal("0.19"), abs=Decimal("1e-8"))


def test_rt28_double_root_inside_a_cell_is_not_determinable() -> None:
    """A tangent (double) root at 15 %: XNPV touches zero inside [10 %, 20 %] without changing sign."""
    res = xirr(_flows("230", "132.25"))
    assert res.outcome is XirrOutcome.NOT_DETERMINABLE
    assert res.rate is None
    assert all(r == pytest.approx(Decimal("0.15"), abs=Decimal("1e-5")) for r in res.roots)


def test_rt28_no_root_with_two_sign_changes_is_still_no_solution() -> None:
    """−100, +230, −133: the quadratic has no real root (discriminant < 0) → genuinely NO_SOLUTION."""
    res = xirr(_flows("230", "133"))
    assert res.outcome is XirrOutcome.NO_SOLUTION


def test_rt28_spec_x5_grid_roots_still_multiple_roots() -> None:
    """calculation-methodology §2.6 X-5 (roots exactly at grid points 10 % and 20 %) is unchanged."""
    res = xirr(_flows("230", "132"))
    assert res.outcome is XirrOutcome.MULTIPLE_ROOTS


def test_rt28_single_sign_change_unchanged() -> None:
    res = xirr([CashFlow(D0, D("-100")), CashFlow(D2, D("121"))])
    assert res.outcome is XirrOutcome.SOLVED
    assert res.rate == pytest.approx(Decimal("0.1"), abs=Decimal("1e-10"))
