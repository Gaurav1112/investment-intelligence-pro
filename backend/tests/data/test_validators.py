"""Validator tests. Values are taken from the probe fixtures (NAV history for HDFC Large Cap 119018, NAVAll and the
mfapi.in mirror for HDFC Banking & PSU 128629); variants are explicit mutations of those values."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from iip.data.models import Freshness, Observation, QualityStatus
from iip.data.registry import get_source
from iip.data.validators import (
    business_days_between,
    check_duplicates,
    check_jumps,
    check_non_positive,
    check_order,
    check_unit_currency,
    classify_freshness,
    cross_check_mirror,
    isin_checksum_ok,
    validate_isin,
)
from tests.data.conftest import NAVALL_RETRIEVED, load_fixture

SHA = "0" * 64


def obs(
    code: str,
    d: date,
    value: str,
    *,
    status: QualityStatus = QualityStatus.OK,
    unit: str = "INR_per_unit",
    currency: str | None = "INR",
    source_id: str = "amfi.navhistory",
    retrieved_at: datetime = NAVALL_RETRIEVED,
) -> Observation:
    return Observation(
        source_id=source_id,
        source_url="https://portal.amfiindia.com/x",
        retrieved_at=retrieved_at,
        observation_date=d,
        publication_time=None,
        entity_key=code,
        value=Decimal(value),
        unit=unit,
        currency=currency,
        quality_status=status,
        convention="NAV_PER_UNIT_AS_PUBLISHED",
        raw_sha256=SHA,
    )


D13, D14 = date(2026, 10, 13), date(2026, 10, 14)


# --- ISIN -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("isin", ["INFZ11K01WO4", "INFZ12KA1IZ1", "INFZ14X01867", "US0378331005", "INE002A01018"])
def test_valid_isins(isin: str) -> None:
    assert validate_isin(isin) is None
    assert isin_checksum_ok(isin)


@pytest.mark.parametrize(
    ("isin", "reason"),
    [
        ("INF846K01WO2", "ISIN_BAD_CHECKSUM"),
        ("US0378331006", "ISIN_BAD_CHECKSUM"),
        ("INF846K01WO", "ISIN_BAD_FORMAT"),
        ("INF846K01WOA", "ISIN_BAD_FORMAT"),  # check digit must be numeric
        ("1NF846K01WO1", "ISIN_BAD_FORMAT"),
        ("INFZ11K01W O4", "ISIN_BAD_FORMAT"),
        ("ＩNF846K01WO1", "ISIN_BAD_FORMAT"),  # full-width I
    ],
)
def test_invalid_isins(isin: str, reason: str) -> None:
    assert validate_isin(isin) == reason


# --- duplicates -----------------------------------------------------------------------------------


def test_duplicate_identical_collapses_with_finding() -> None:
    a = obs("119018", D14, "1385.402")
    result = check_duplicates([a, a])
    assert result.observations == (a,)
    assert [f.code for f in result.findings] == ["DUPLICATE_IDENTICAL"]


def test_duplicate_numerically_equal_is_identical() -> None:
    """mfapi 5-dp padding: 25.95040 and 25.9504 are the same NAV, not a conflict."""
    result = check_duplicates([obs("128629", D14, "25.9504"), obs("128629", D14, "25.95040")])
    assert len(result.observations) == 1
    assert result.observations[0].quality_status is QualityStatus.OK


def test_duplicate_conflict_marks_all_suspect() -> None:
    result = check_duplicates([obs("119018", D14, "1385.402"), obs("119018", D14, "1393.087")])
    assert len(result.observations) == 2
    assert all(o.quality_status is QualityStatus.SUSPECT for o in result.observations)
    assert all("DUPLICATE_CONFLICT" in o.notes for o in result.observations)
    assert [f.code for f in result.findings] == ["DUPLICATE_CONFLICT"]


def test_duplicates_on_other_keys_untouched() -> None:
    items = [obs("119018", D13, "1393.087"), obs("119018", D14, "1385.402"), obs("102000", D14, "865.499")]
    result = check_duplicates(items)
    assert result.observations == tuple(items)
    assert result.findings == ()


# --- order --------------------------------------------------------------------------------------------


def test_out_of_order_flagged_suspect() -> None:
    items = [obs("119018", D14, "1385.402"), obs("119018", D13, "1393.087")]
    result = check_order(items)
    assert result.observations[0].quality_status is QualityStatus.OK
    assert result.observations[1].quality_status is QualityStatus.SUSPECT
    assert [f.code for f in result.findings] == ["OUT_OF_ORDER"]


def test_descending_order_accepted_when_declared() -> None:
    items = [obs("128629", D14, "25.95040"), obs("128629", D13, "25.98250")]
    result = check_order(items, descending=True)
    assert result.findings == ()


def test_order_is_per_entity() -> None:
    items = [obs("119018", D14, "1385.402"), obs("102000", D13, "870.312")]
    assert check_order(items).findings == ()


# --- non-positive -------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["0", "0.0000", "-1.5"])
def test_non_positive_rejected(value: str) -> None:
    result = check_non_positive([obs("119018", D14, value)])
    assert result.observations[0].quality_status is QualityStatus.REJECTED
    assert result.findings[0].code == "NON_POSITIVE"


# --- jumps ----------------------------------------------------------------------------------------------


def test_small_move_is_ok() -> None:
    result = check_jumps([obs("119018", D13, "1393.087"), obs("119018", D14, "1385.402")])
    assert result.findings == ()


def test_jump_above_threshold_is_suspect_not_dropped() -> None:
    # 1393.087 → 1393.087 × 10 (a decimal-shift error) on the next day.
    items = [obs("119018", D13, "1393.087"), obs("119018", D14, "13930.87")]
    result = check_jumps(items, threshold=Decimal("0.20"))
    assert len(result.observations) == 2  # never silently dropped
    assert result.observations[0].quality_status is QualityStatus.OK
    assert result.observations[1].quality_status is QualityStatus.SUSPECT
    assert result.findings[0].code == "JUMP_ABOVE_THRESHOLD"


def test_jump_exactly_at_threshold_is_ok() -> None:
    result = check_jumps([obs("x", D13, "10"), obs("x", D14, "12")], threshold=Decimal("0.20"))
    assert result.findings == ()


def test_jump_against_last_published() -> None:
    last = {"119018": obs("119018", D13, "1393.087")}
    result = check_jumps([obs("119018", D14, "500")], last_published=last)
    assert result.observations[0].quality_status is QualityStatus.SUSPECT


def test_jump_with_known_event_is_ok() -> None:
    items = [obs("119018", D13, "1393.087"), obs("119018", D14, "13930.87")]
    result = check_jumps(items, known_events=frozenset({("119018", D14)}))
    assert result.findings == ()


def test_jump_skips_rejected_baseline() -> None:
    items = [
        obs("x", D13, "100"),
        obs("x", date(2026, 10, 14), "0", status=QualityStatus.REJECTED),
        obs("x", date(2026, 10, 15), "101"),
    ]
    assert check_jumps(items).findings == ()


# --- freshness (as_of injected; no clock) --------------------------------------------------------------


def _as_of(y: int, m: int, d: int, hh: int = 6) -> datetime:
    return datetime(y, m, d, hh, 0, tzinfo=UTC)


def test_business_days_weekdays_only_fallback() -> None:
    # Fri 9-Oct-2026 → Mon 12-Oct-2026 is one business day.
    assert business_days_between(date(2026, 10, 9), date(2026, 10, 12)) == 1
    assert business_days_between(date(2026, 10, 14), date(2026, 10, 14)) == 0


def test_business_days_with_holiday() -> None:
    assert business_days_between(date(2026, 10, 9), date(2026, 10, 13), holidays=frozenset({date(2026, 10, 12)})) == 1


def test_nav_from_previous_business_day_is_fresh() -> None:
    spec = get_source("amfi.navall")
    result = classify_freshness(obs("128629", D14, "25.9504"), spec.freshness, as_of=_as_of(2026, 10, 15))
    assert result.freshness is Freshness.FRESH
    assert result.observation.quality_status is QualityStatus.OK
    assert "CALENDAR_UNVERIFIED" in result.observation.notes  # no curated calendar passed


def test_nav_three_business_days_old_is_stale() -> None:
    spec = get_source("amfi.navall")
    result = classify_freshness(
        obs("128629", date(2026, 10, 9), "26.0175"), spec.freshness, as_of=_as_of(2026, 10, 14), holidays=frozenset()
    )
    assert result.freshness is Freshness.STALE
    assert result.observation.quality_status is QualityStatus.STALE


def test_nav_older_than_slo_is_expired_and_stale() -> None:
    spec = get_source("amfi.navall")
    result = classify_freshness(
        obs("128629", date(2026, 10, 6), "26.0302"), spec.freshness, as_of=_as_of(2026, 10, 14), holidays=frozenset()
    )
    assert result.freshness is Freshness.EXPIRED
    assert result.observation.quality_status is QualityStatus.STALE
    assert "EXPIRED" in result.observation.notes


def test_ancient_navall_date_is_dormant() -> None:
    spec = get_source("amfi.navall")
    result = classify_freshness(obs("123689", date(2017, 9, 15), "11.9827"), spec.freshness, as_of=_as_of(2026, 10, 15))
    assert result.freshness is Freshness.EXPIRED
    assert "DORMANT" in result.observation.notes


def test_future_dated_observation_is_suspect() -> None:
    spec = get_source("amfi.navall")
    result = classify_freshness(
        obs("128629", date(2026, 10, 16), "25.9504"), spec.freshness, as_of=_as_of(2026, 10, 15)
    )
    assert result.observation.quality_status is QualityStatus.SUSPECT
    assert "FUTURE_DATE" in result.observation.notes


def test_as_of_uses_ist_calendar_date() -> None:
    # 2026-10-14T20:00Z is already 15-Oct 01:30 IST; a 14-Oct NAV is T-1 → fresh either way, but a 13-Oct NAV is
    # one business day old in UTC and two in IST.
    spec = get_source("amfi.navall")
    result = classify_freshness(
        obs("x", D13, "1"), spec.freshness, as_of=datetime(2026, 10, 14, 20, 0, tzinfo=UTC), holidays=frozenset()
    )
    assert result.freshness is Freshness.STALE


def test_naive_as_of_refused() -> None:
    spec = get_source("amfi.navall")
    with pytest.raises(ValueError, match="aware"):
        classify_freshness(obs("x", D14, "1"), spec.freshness, as_of=datetime(2026, 10, 15, 6, 0))


def test_scheme_master_freshness_uses_retrieval_age() -> None:
    spec = get_source("amfi.schememaster")
    o = obs("x", date(2026, 9, 30), "1", source_id="amfi.schememaster", retrieved_at=datetime(2026, 10, 1, tzinfo=UTC))
    assert classify_freshness(o, spec.freshness, as_of=_as_of(2026, 10, 15)).freshness is Freshness.STALE
    assert classify_freshness(o, spec.freshness, as_of=_as_of(2026, 10, 5)).freshness is Freshness.FRESH
    assert classify_freshness(o, spec.freshness, as_of=_as_of(2026, 11, 5)).freshness is Freshness.EXPIRED


def test_fixture_label_is_sticky_under_staleness() -> None:
    spec = get_source("amfi.navall")
    o = obs("x", date(2026, 10, 1), "1", status=QualityStatus.FIXTURE)
    result = classify_freshness(o, spec.freshness, as_of=_as_of(2026, 10, 15))
    assert result.observation.quality_status is QualityStatus.FIXTURE
    assert "EXPIRED" in result.observation.notes


# --- unit / currency ------------------------------------------------------------------------------------


def test_unit_and_currency_ok() -> None:
    result = check_unit_currency([obs("x", D14, "1")], expected_unit="INR_per_unit", expected_currency="INR")
    assert result.findings == ()


@pytest.mark.parametrize(
    ("unit", "currency", "code"),
    [
        ("percent_pa", "INR", "UNIT_MISMATCH"),
        ("INR_per_unit", "USD", "CURRENCY_MISMATCH"),
        ("INR_per_unit", None, "CURRENCY_MISMATCH"),
    ],
)
def test_unit_currency_mismatch_rejected(unit: str, currency: str | None, code: str) -> None:
    result = check_unit_currency(
        [obs("x", D14, "1", unit=unit, currency=currency)], expected_unit="INR_per_unit", expected_currency="INR"
    )
    assert result.observations[0].quality_status is QualityStatus.REJECTED
    assert result.findings[0].code == code


# --- mfapi.in 5-dp padding regression -----------------------------------------------------------------


def test_regression_mfapi_padding_is_not_a_conflict() -> None:
    payload = json.loads(load_fixture("mfapi_128629_latest.json"))
    point = payload["data"][0]
    assert point["nav"] == "25.95040"  # mirror pads to 5 dp
    mirror = replace(
        obs("128629", D14, point["nav"], source_id="mfapi.in"), source_url="https://api.mfapi.in/mf/128629/latest"
    )
    official = obs("128629", D14, "25.9504", source_id="amfi.navall")
    checked = cross_check_mirror(official, mirror)
    assert checked.quality_status is QualityStatus.OK
    assert "UNOFFICIAL_MIRROR" in checked.notes
    # The official value keeps its own published precision.
    assert str(official.value) == "25.9504"


def test_mirror_disagreement_is_conflict() -> None:
    mirror = obs("128629", D14, "25.95060", source_id="mfapi.in")
    official = obs("128629", D14, "25.9504", source_id="amfi.navall")
    checked = cross_check_mirror(official, mirror)
    assert checked.quality_status is QualityStatus.SUSPECT
    assert "CONFLICT" in checked.notes


def test_cross_check_requires_same_key() -> None:
    with pytest.raises(ValueError):
        cross_check_mirror(obs("128629", D14, "1"), obs("128629", D13, "1", source_id="mfapi.in"))


# --- Observation contract -----------------------------------------------------------------------------


def test_observation_refuses_float() -> None:
    with pytest.raises(TypeError):
        replace(obs("x", D14, "1"), value=1.5)


def test_observation_refuses_naive_or_non_utc_retrieved_at() -> None:
    with pytest.raises(ValueError):
        obs("x", D14, "1", retrieved_at=datetime(2026, 10, 15, 5, 0))


def test_observation_refuses_non_finite() -> None:
    with pytest.raises(ValueError):
        obs("x", D14, "NaN")


def test_observation_is_frozen() -> None:
    o = obs("x", D14, "1")
    with pytest.raises(AttributeError):
        o.value = Decimal(2)  # type: ignore[misc]
