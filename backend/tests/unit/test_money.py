from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal

import pytest

from iip.engine.errors import InvalidInput, NumericalError
from iip.engine.money import D, format_inr, from_float, money, pct, quantize, rate_display, units_allotment

# calculation-methodology.md §1.2 rounding fixtures (quantum 0.01)
ROUNDING = [
    ("2.345", "2.34", "2.35"),
    ("2.355", "2.36", "2.36"),
    ("10.005", "10.00", "10.01"),
    ("-2.345", "-2.34", "-2.35"),
    ("0.125", "0.12", "0.13"),
]


@pytest.mark.parametrize(("raw", "even", "up"), ROUNDING)
def test_rounding_fixtures(raw: str, even: str, up: str) -> None:
    assert quantize(D(raw), Decimal("0.01"), ROUND_HALF_EVEN) == Decimal(even)
    assert quantize(D(raw), Decimal("0.01"), ROUND_HALF_UP) == Decimal(up)
    assert money(D(raw)) == Decimal(up)


def test_floats_are_rejected() -> None:
    with pytest.raises(InvalidInput):
        D(0.1)  # type: ignore[arg-type]
    with pytest.raises(InvalidInput):
        D(True)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["", "abc", "NaN", "Infinity", "  "])
def test_invalid_strings(bad: str) -> None:
    with pytest.raises(InvalidInput):
        D(bad)


def test_strings_with_commas_parse() -> None:
    assert D("1,00,000.50") == Decimal("100000.50")


def test_from_float_uses_repr_and_rejects_nan() -> None:
    assert from_float(0.1) == Decimal("0.1")
    with pytest.raises(NumericalError):
        from_float(float("nan"))
    with pytest.raises(NumericalError):
        from_float(float("inf"))


@pytest.mark.parametrize(
    ("amount", "text"),
    [
        ("0", "₹0.00"),
        ("999", "₹999.00"),
        ("99999", "₹99,999.00"),
        ("100000", "₹1,00,000.00"),
        ("9999999", "₹99,99,999.00"),
        ("10000000", "₹1,00,00,000.00"),
        ("123456789.005", "₹12,34,56,789.01"),
        ("-150000.5", "-₹1,50,000.50"),
        ("1000000000000", "₹10,00,00,00,00,000.00"),
    ],
)
def test_indian_grouping_boundaries(amount: str, text: str) -> None:
    assert format_inr(D(amount)) == text


def test_pct_and_rate_display() -> None:
    assert pct(D("0.065")) == "6.50%"
    assert rate_display(D("0.0999855")) == Decimal("0.1000")


def test_units_truncate() -> None:
    assert units_allotment(D("12.34567")) == Decimal("12.345")


def test_extremely_large_amounts_keep_paise_precision() -> None:
    big = D("999999999999999.99")  # ~₹10^15
    assert money(big + D("0.01")) == D("1000000000000000.00")
