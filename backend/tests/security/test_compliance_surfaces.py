"""B04: the surface-aware Compliance Guard (design-risk-first.md §7.3, §9.4; PLAN.md §5.3 B04, §8 U-11).

* The base BLOCK list applies on every surface (unchanged behaviour for every existing caller).
* Neutral "entry/exit condition met" wording is allowed in the owner's private view and BLOCKed on export, share,
  public and ping surfaces.
* BUY/SELL badges are BLOCKed by default everywhere (U-11 neutral default). The owner's opt-in lifts them on the
  PRIVATE surface only; export, share, public and ping keep the BLOCK.

All texts are synthetic.
"""

from __future__ import annotations

import pytest

from iip.supervisor import compliance as cg
from iip.supervisor.compliance import Surface, Vocabulary

NON_PRIVATE = (Surface.EXPORT, Surface.SHARE, Surface.PUBLIC, Surface.PING)
ALL = (Surface.PRIVATE, *NON_PRIVATE)
SIGNAL_TEXT = "Entry condition met: rule s.trend_timing@1, data as of 14-Mar-2031."
BADGE_TEXT = "SELL  Synthetic Index Fund"


def _cats(text: str, surface: Surface, vocabulary: Vocabulary = Vocabulary.NEUTRAL) -> set[str]:
    return {h.category for h in cg.blocked(text, surface=surface, vocabulary=vocabulary)}


def test_rules_file_is_versioned_and_carries_surface_rules() -> None:
    rules = cg.load_rules()
    assert rules.version == "compliance_phrases@1.1.0"
    assert {r.category for r in rules.surface_block} == {"trading_calls", "signal_wording", "ping_content"}


@pytest.mark.parametrize("surface", ALL)
def test_base_block_list_applies_on_every_surface(surface: Surface) -> None:
    assert "guarantees" in _cats("Guaranteed returns on this synthetic plan.", surface)
    assert "directives" in _cats("You should buy this today.", surface)


def test_default_call_is_private_and_unchanged_for_existing_callers() -> None:
    assert cg.blocked(SIGNAL_TEXT) == []
    assert cg.blocked("Your rule says: redirect the next SIP to the debt sleeve.") == []


def test_neutral_signal_wording_allowed_in_private_view() -> None:
    assert _cats(SIGNAL_TEXT, Surface.PRIVATE) == set()
    assert _cats("Exit condition met: rule s.trend_timing@1.", Surface.PRIVATE) == set()


@pytest.mark.parametrize("surface", NON_PRIVATE)
@pytest.mark.parametrize("vocabulary", list(Vocabulary))
def test_signal_wording_blocked_on_export_share_public_and_ping(surface: Surface, vocabulary: Vocabulary) -> None:
    assert "signal_wording" in _cats(SIGNAL_TEXT, surface, vocabulary)
    assert "signal_wording" in _cats("Exit signal for the synthetic fund", surface, vocabulary)


def test_buy_sell_badges_blocked_in_private_view_by_default() -> None:
    assert "trading_calls" in _cats(BADGE_TEXT, Surface.PRIVATE)
    assert "trading_calls" in _cats("BUY", Surface.PRIVATE)
    assert "trading_calls" in _cats("a sell signal fired", Surface.PRIVATE)


def test_owner_opt_in_lifts_badges_on_private_surface_only() -> None:
    assert "trading_calls" not in _cats(BADGE_TEXT, Surface.PRIVATE, Vocabulary.BADGES)


@pytest.mark.parametrize("surface", NON_PRIVATE)
def test_badges_stay_blocked_on_export_share_public_ping_even_with_opt_in(surface: Surface) -> None:
    assert "trading_calls" in _cats(BADGE_TEXT, surface, Vocabulary.BADGES)
    assert "trading_calls" in _cats(BADGE_TEXT, surface, Vocabulary.NEUTRAL)


def test_badge_check_survives_lookalike_characters() -> None:
    # A Cyrillic capital IE and a zero-width space inside the badge are normalised before scanning.
    assert "trading_calls" in _cats("S\u0415LL", Surface.SHARE, Vocabulary.BADGES)
    assert "trading_calls" in _cats("B\u200bUY", Surface.EXPORT)


def test_lowercase_ordinary_prose_is_not_a_badge_in_private_view() -> None:
    # Existing private copy (e.g. "buying back" in a harvest card) is not a trading call.
    assert "trading_calls" not in _cats("Redeeming the oldest lots and buying back resets the cost.", Surface.PRIVATE)


@pytest.mark.parametrize(
    "text",
    [
        "₹1,20,000 short",
        "Rs 500",
        "INR 9000",
        "2 lakh",
        "6.50%",
        "1,00,534",
        "12.5 units",
        "redeem now",
        "invest the next SIP",
        "Synthetic Bluechip Fund",
        "your tax",
    ],
)
def test_ping_content_rule_blocks_amounts_verbs_and_instrument_words(text: str) -> None:
    assert "ping_content" in _cats(text, Surface.PING)


def test_ping_content_rule_does_not_apply_elsewhere() -> None:
    assert "ping_content" not in _cats("₹1,20,000 short of 6 months", Surface.PRIVATE)


def test_disclosures_are_not_exempt_on_the_ping_surface() -> None:
    disclosure = cg.load_rules().required["past_performance"]
    assert cg.blocked(disclosure, surface=Surface.PRIVATE) == []
    assert cg.blocked(disclosure, surface=Surface.PING) != []


@pytest.mark.parametrize("raw", ["", "nonsense", None, "PRIVATE ", "ping"])
def test_parse_surface_fails_closed(raw: object) -> None:
    got = cg.parse_surface(raw)
    if raw == "PRIVATE ":
        assert got is Surface.PRIVATE
    elif raw == "ping":
        assert got is Surface.PING
    else:
        assert got is Surface.PUBLIC


@pytest.mark.parametrize(
    ("raw", "want"),
    [("badges", Vocabulary.BADGES), ("", Vocabulary.NEUTRAL), (None, Vocabulary.NEUTRAL), ("BUY", Vocabulary.NEUTRAL)],
)
def test_parse_vocabulary_defaults_to_neutral(raw: object, want: Vocabulary) -> None:
    assert cg.parse_vocabulary(raw) is want


def test_a_surface_rule_without_surfaces_or_patterns_is_refused() -> None:
    with pytest.raises(ValueError, match="needs surfaces and patterns"):
        cg._surface_rules({"surface_block": {"x": {"surfaces": [], "patterns": ["a"]}}})
    with pytest.raises(ValueError):
        cg._surface_rules({"surface_block": {"x": {"surfaces": ["nowhere"], "patterns": ["a"]}}})
