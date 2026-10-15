"""Money and precision policy (ADR-0002, calculation-methodology.md §1).

Rules:
* All engine arithmetic runs in ``ENGINE_CTX`` (34 significant digits, HALF_EVEN, traps on invalid ops).
* Never quantize intermediates; quantize once at the output boundary.
* INR money for display → paise, ROUND_HALF_UP.  Rates/ratios/statistics → ROUND_HALF_EVEN.
* Decimals are built from ``str``/``int`` only.  ``D(float)`` raises.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)

from iip.engine.errors import InvalidInput, NumericalError

ENGINE_CTX = Context(prec=34, rounding=ROUND_HALF_EVEN, traps=[InvalidOperation, DivisionByZero, Overflow])

PAISA = Decimal("0.01")
RATE_STORE_QUANTUM = Decimal("0.000001")  # 0.0001 %
RATE_DISPLAY_QUANTUM = Decimal("0.0001")  # 0.01 %
PRICE_QUANTUM = Decimal("0.0001")
UNITS_QUANTUM = Decimal("0.001")

ZERO = Decimal(0)
ONE = Decimal(1)


@contextmanager
def engine_context() -> Iterator[Context]:
    """Run a block under the engine Decimal context without mutating the global context."""
    with localcontext(ENGINE_CTX) as ctx:
        yield ctx


def D(value: str | int | Decimal) -> Decimal:
    """Strict Decimal constructor. Floats are rejected (they carry binary rounding error)."""
    if isinstance(value, bool):
        raise InvalidInput("bool is not a number")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise InvalidInput(f"non-finite Decimal: {value}")
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if text == "":
            raise InvalidInput("empty numeric string")
        try:
            dec = Decimal(text)
        except InvalidOperation as exc:  # pragma: no cover - message path
            raise InvalidInput(f"not a decimal number: {value!r}") from exc
        if not dec.is_finite():
            raise InvalidInput(f"non-finite value: {value!r}")
        return dec
    raise InvalidInput(f"unsupported numeric type {type(value).__name__}; floats are forbidden")


def from_float(x: float) -> Decimal:
    """Cross the statistics boundary float→Decimal via the shortest round-trip repr (never Decimal(float))."""
    if not math.isfinite(x):
        raise NumericalError(f"non-finite float crossed the statistics boundary: {x!r}")
    return Decimal(repr(float(x)))


def money(value: Decimal) -> Decimal:
    """Quantize an INR amount for display: paise, HALF_UP (matches bank/AMC statements)."""
    with engine_context():
        return value.quantize(PAISA, rounding=ROUND_HALF_UP)


def rate_display(value: Decimal) -> Decimal:
    """Quantize a rate (fraction) for display to 0.01 %, HALF_EVEN."""
    with engine_context():
        return value.quantize(RATE_DISPLAY_QUANTUM, rounding=ROUND_HALF_EVEN)


def rate_store(value: Decimal) -> Decimal:
    with engine_context():
        return value.quantize(RATE_STORE_QUANTUM, rounding=ROUND_HALF_EVEN)


def quantize(value: Decimal, quantum: Decimal, rounding: str = ROUND_HALF_EVEN) -> Decimal:
    with engine_context():
        return value.quantize(quantum, rounding=rounding)


def units_allotment(value: Decimal) -> Decimal:
    """Replicate MF unit allotment truncation to 3 dp (practice varies by AMC — NOT VERIFIED)."""
    with engine_context():
        return value.quantize(UNITS_QUANTUM, rounding=ROUND_DOWN)


def pct(value: Decimal) -> str:
    """Human display of a fraction as a percentage string with 2 dp, HALF_EVEN, e.g. 0.065 → '6.50%'."""
    with engine_context():
        q = (value * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        if q.is_zero():
            q = abs(q)  # never display "-0.00%" for a tiny negative that rounds to zero
        return f"{q}%"


def format_inr(amount: Decimal, *, paise: bool = True) -> str:
    """Indian digit grouping (lakh/crore): 12345678.9 → '₹1,23,45,678.90'. HALF_UP to paise."""
    q = money(amount) if paise else quantize(amount, ONE, ROUND_HALF_UP)
    sign = "-" if q < 0 else ""
    q = abs(q)
    text = f"{q:f}"
    whole, _, frac = text.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join([*groups, tail])
    return f"{sign}₹{whole}" + (f".{frac}" if paise else "")
