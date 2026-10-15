"""Red team RT-26: content_hash value-canonicalisation (policy in iip.engine.determinism, canonical_json@2)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from iip.engine.determinism import CANONICAL_VERSION, canonical_json, content_hash

IST = timezone(timedelta(hours=5, minutes=30))


def test_rt26_negative_zero_hashes_as_zero_keeping_its_precision() -> None:
    assert content_hash({"v": Decimal("-0")}) == content_hash({"v": Decimal("0")})
    assert canonical_json({"v": Decimal("-0.00")}) == '{"v":"0.00"}'
    assert canonical_json({"v": Decimal("-0E-4")}) == '{"v":"0.0000"}'


def test_rt26_same_instant_in_ist_and_utc_hashes_identically() -> None:
    utc = datetime(2026, 10, 15, 0, 30, tzinfo=UTC)
    ist = datetime(2026, 10, 15, 6, 0, tzinfo=IST)
    assert utc == ist
    assert content_hash({"t": ist}) == content_hash({"t": utc})
    assert canonical_json([ist]) == '["2026-10-15T00:30:00+00:00"]'


@pytest.mark.parametrize("bad", [0.1, 1.0, float("inf"), float("nan")])
def test_rt26_floats_are_rejected_anywhere(bad: float) -> None:
    for obj in ({"v": bad}, [bad], {"a": {"b": [1, bad]}}, (bad,)):
        with pytest.raises(ValueError):
            canonical_json(obj)


def test_rt26_floats_inside_dataclasses_are_rejected() -> None:
    @dataclass(frozen=True)
    class Row:
        v: object

    with pytest.raises(ValueError):
        content_hash(Row(v=0.5))
    assert canonical_json(Row(v=Decimal("-0.5"))) == '{"v":"-0.5"}'


def test_rt26_source_precision_is_still_provenance() -> None:
    """Decided policy: exact Decimal digits are kept (25.9504 vs 25.95040 differ). See the module docstring."""
    assert content_hash({"nav": Decimal("25.9504")}) != content_hash({"nav": Decimal("25.95040")})


def test_rt26_canonical_version_recorded_in_run_versions() -> None:
    from iip.services import analysis

    assert CANONICAL_VERSION == "canonical_json@2"
    assert analysis._VERSIONS["canonical"] == CANONICAL_VERSION
