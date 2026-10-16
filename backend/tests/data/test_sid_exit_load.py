"""SID "Load Structure" exit-load grammar (PLAN.md row B06; audit-automation.md §3.6).

Documented phrasings parse; everything else abstains. A partially recognised schedule is never returned. The texts
below are phrasing templates written for this test (the two from audit-automation.md §3.6 are generic wording quoted
there); no scheme, AMC or SID is named and no real load is asserted for any fund."""

from __future__ import annotations

from decimal import Decimal

import pytest

from iip.data.parsers.sid_exit_load import (
    ExitLoadAbstain,
    ExitLoadSchedule,
    LoadPeriod,
    extract_exit_load_text,
    parse_exit_load,
)


def ok(text: str) -> ExitLoadSchedule:
    out = parse_exit_load(text)
    assert isinstance(out, ExitLoadSchedule), out
    return out


def tiers(s: ExitLoadSchedule) -> list[tuple[int, str, Decimal]]:
    return [(t.upto.n, t.upto.unit, t.rate) for t in s.tiers]


# ------------------------------------------------------------------------------------ documented phrasings


def test_nil_is_no_load() -> None:
    s = ok("Nil")
    assert s.tiers == () and s.free_fraction is None and s.branch == "NIL"
    assert s.window_days() == ()


def test_audit_example_one_percent_365_days_with_footnote_markers() -> None:
    s = ok("Exit Load: 1%, if exited on or before 365 days^; Nil, if exited after 365 days^")
    assert tiers(s) == [(365, "day", Decimal("0.01"))]
    assert "FOOTNOTE_MARKER_IGNORED" in s.flags
    assert s.window_days() == ((365, Decimal("0.01")),)


def test_audit_example_fifteen_bp_30_days_from_allotment() -> None:
    s = ok("0.15% if redeemed on or before 30 days from the date of allotment; Nil after 30 days")
    assert tiers(s) == [(30, "day", Decimal("0.0015"))]
    assert s.flags == ()


def test_within_is_read_as_on_or_before_and_flagged() -> None:
    s = ok("1% if redeemed or switched out within 7 days from the date of allotment; Nil thereafter")
    assert tiers(s) == [(7, "day", Decimal("0.01"))]
    assert "BOUNDARY_WITHIN_READ_AS_ON_OR_BEFORE" in s.flags


def test_months_and_years_parse_but_never_convert_to_days() -> None:
    m = ok("1% if redeemed within 12 months from the date of allotment; Nil thereafter")
    assert tiers(m) == [(12, "month", Decimal("0.01"))]
    assert m.window_days() is None and m.engine_abstain_reason() == "PERIOD_NOT_IN_DAYS"
    y = ok("For exit on or before 1 year from the date of allotment - 1%; For exit after 1 year from the date of "
           "allotment - Nil")  # fmt: skip
    assert tiers(y) == [(1, "year", Decimal("0.01"))]
    assert y.window_days() is None


def test_payable_wording() -> None:
    s = ok(
        "In respect of each purchase / switch-in of Units, an Exit Load of 1.00% is payable if Units are redeemed / "
        "switched-out within 30 days from the date of allotment. No Exit Load is payable if Units are redeemed / "
        "switched-out after 30 days from the date of allotment."
    )
    assert tiers(s) == [(30, "day", Decimal("0.01"))]


def test_graded_tiers_in_ascending_order() -> None:
    s = ok(
        "1% if redeemed on or before 30 days; 0.5% if redeemed after 30 days but on or before 90 days; "
        "Nil after 90 days"
    )
    assert tiers(s) == [(30, "day", Decimal("0.01")), (90, "day", Decimal("0.005"))]
    assert s.window_days() == ((30, Decimal("0.01")), (90, Decimal("0.005")))


def test_graded_tiers_as_repeated_upto_clauses() -> None:
    s = ok("1% if redeemed on or before 30 days; 0.25% if redeemed on or before 60 days; Nil after 60 days")
    assert tiers(s) == [(30, "day", Decimal("0.01")), (60, "day", Decimal("0.0025"))]


def test_free_units_branch_parses_but_is_not_modelled_by_the_engine() -> None:
    s = ok(
        "Nil for up to 10% of units if redeemed on or before 365 days from the date of allotment; for remaining "
        "units: 1% if redeemed on or before 365 days from the date of allotment; Nil after 365 days"
    )
    assert s.branch == "FREE_UNITS" and s.free_fraction == Decimal("0.10")
    assert tiers(s) == [(365, "day", Decimal("0.01"))]
    assert s.window_days() is None and s.engine_abstain_reason() == "FREE_UNITS_NOT_MODELLED"


def test_result_is_deterministic_and_carries_the_text_hash() -> None:
    text = "0.15% if redeemed on or before 30 days from the date of allotment; Nil after 30 days"
    a, b = ok(text), ok("  " + text.upper() + ". ")
    assert a == b and len(a.text_sha256) == 64


# ------------------------------------------------------------------------------------ everything else abstains


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", "EMPTY"),
        ("As per the Scheme Information Document", "UNRECOGNISED_PHRASING"),
        ("Please refer to the SID", "UNRECOGNISED_PHRASING"),
        ("1% if redeemed within 1 year", "NO_TERMINAL_NIL"),
        ("1% if redeemed on or before 30 days; Nil after 60 days", "GAP_OR_OVERLAP_BETWEEN_TIERS"),
        ("1% if redeemed on or before 30 days; Nil after 1 month", "MIXED_PERIOD_UNITS"),
        ("6% if redeemed on or before 30 days; Nil after 30 days", "RATE_OUT_OF_RANGE"),
        ("0% if redeemed on or before 30 days; Nil after 30 days", "RATE_OUT_OF_RANGE"),
        # A recognised schedule followed by anything unrecognised is never partially stored.
        (
            "1% if redeemed on or before 30 days; Nil after 30 days; switches between plans are exempt",
            "UNRECOGNISED_PHRASING",
        ),
        (
            "0.5% if redeemed on or before 30 days; 1% if redeemed on or before 30 days; Nil after 30 days",
            "TIERS_NOT_ASCENDING",
        ),
        (
            "1% if redeemed on or before 30 days; 0.5% if redeemed after 45 days but on or before 90 days; "
            "Nil after 90 days",
            "GAP_OR_OVERLAP_BETWEEN_TIERS",
        ),
        ("0.5% if redeemed after 30 days but on or before 90 days; Nil after 90 days", "GAP_OR_OVERLAP_BETWEEN_TIERS"),
        ("Nil after 30 days; 1% if redeemed on or before 30 days", "NIL_NOT_LAST"),
        ("Nil; Nil", "UNRECOGNISED_PHRASING"),
        ("for remaining units: 1% if redeemed on or before 30 days; Nil after 30 days", "UNRECOGNISED_PHRASING"),
        (
            "Nil for up to 110% of units; for remaining units: 1% if redeemed on or before 30 days; Nil after 30 days",
            "FREE_FRACTION_OUT_OF_RANGE",
        ),
        ("Rs. 10 per unit if redeemed on or before 30 days; Nil after 30 days", "UNRECOGNISED_PHRASING"),
        ("Day 1: 0.0070%; Day 2: 0.0065%; Day 7 onwards: Nil", "UNRECOGNISED_PHRASING"),
        ("1% if redeemed on or before 0 days; Nil after 0 days", "PERIOD_OUT_OF_RANGE"),
    ],
)
def test_unknown_or_inconsistent_phrasings_abstain(text: str, reason: str) -> None:
    out = parse_exit_load(text)
    assert isinstance(out, ExitLoadAbstain), out
    assert out.reason == reason


def test_abstain_carries_no_partial_schedule() -> None:
    out = parse_exit_load("1% if redeemed on or before 30 days; Nil after 30 days; something else")
    assert isinstance(out, ExitLoadAbstain)
    assert not hasattr(out, "tiers")


# ------------------------------------------------------------------------------------ locating the block


def test_extract_exit_load_text_from_a_load_structure_block() -> None:
    sid = (
        "LOAD STRUCTURE\n"
        "Entry Load: Not Applicable\n"
        "Exit Load: 1% if redeemed on or before 30 days from the date of allotment;\n"
        "Nil after 30 days\n"
        "\n"
        "MINIMUM APPLICATION AMOUNT\n"
    )
    text = extract_exit_load_text(sid)
    assert text is not None
    assert tiers(ok(text)) == [(30, "day", Decimal("0.01"))]


def test_extract_abstains_on_none_or_two_different_blocks() -> None:
    assert extract_exit_load_text("No load information here.") is None
    two = "Exit Load: Nil\n\nExit Load: 1% if redeemed on or before 30 days; Nil after 30 days\n"
    assert extract_exit_load_text(two) is None
    same_twice = "Exit Load: Nil\n\nExit Load: Nil\n"
    assert extract_exit_load_text(same_twice) == "Nil"


def test_load_period_rejects_unknown_units() -> None:
    with pytest.raises(ValueError):
        LoadPeriod(3, "week")
