from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from iip.engine.determinism import canonical_json, content_hash


def test_canonical_is_key_order_independent() -> None:
    a = {"b": Decimal("1.10"), "a": [date(2026, 10, 15), "x"]}
    b = {"a": [date(2026, 10, 15), "x"], "b": Decimal("1.10")}
    assert canonical_json(a) == canonical_json(b) == '{"a":["2026-10-15","x"],"b":"1.10"}'
    assert content_hash(a) == content_hash(b)


def test_decimal_trailing_zeros_are_significant() -> None:
    # 1.10 and 1.1 are different published values (NAV precision is provenance) → different hashes.
    assert content_hash({"v": Decimal("1.10")}) != content_hash({"v": Decimal("1.1")})


def test_rejects_nan_and_naive_datetime() -> None:
    with pytest.raises(ValueError):
        canonical_json({"v": float("nan")})
    with pytest.raises(ValueError):
        canonical_json({"t": datetime(2026, 10, 15, 1, 2, 3)})
    assert canonical_json({"t": datetime(2026, 10, 15, tzinfo=UTC)}) == '{"t":"2026-10-15T00:00:00+00:00"}'
