"""Order the day's cards (design-judgement.md graft 8; design-user-first.md §7.2; design-risk-first.md §4).

Ranking key: ``(layer, deadline ascending with no deadline last, ₹ impact descending with no impact last, card_id)``.
There is no composite score (ADR-0005), and the key holds one card's own ₹ only: amounts are compared, never added,
so ₹ on different bases is never summed.

A BREACH card (L1 emergency, L2 goal date, L3 loss budget) or an L0 data-integrity card suppresses every lower-layer
card for its goal; a household-level breach (``goal_id is None``) suppresses lower layers for every goal. Suppressed
cards are returned with the id of the card that suppressed them, never silently dropped.

"Nothing needs doing today" is a valid, first-class result. It is claimed only when there is no action and no
abstention: abstentions alone give ``ABSTAINED_ONLY``, because "all your rules are within limits" would then be false.

Pure: no clock, IO or randomness.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from iip.engine.actions.contracts import ActionCard, CardKind
from iip.engine.errors import InvalidInput

RANKING_VERSION = "actions.ranking@1"
DEFAULT_TOP_N = 5


class TodayState(StrEnum):
    ACTIONS = "ACTIONS"
    NOTHING_NEEDED = "NOTHING_NEEDED"
    ABSTAINED_ONLY = "ABSTAINED_ONLY"


RankKey = tuple[int, bool, date, bool, Decimal, str]


def rank_key(card: ActionCard) -> RankKey:
    no_deadline = card.deadline is None
    no_impact = card.impact is None
    return (
        int(card.layer),
        no_deadline,
        card.deadline if card.deadline is not None else date.min,
        no_impact,
        -card.impact.amount_inr if card.impact is not None else Decimal(0),
        card.card_id,
    )


@dataclass(frozen=True)
class SuppressedCard:
    card: ActionCard
    suppressed_by: str  # card_id of the breach that suppressed it


@dataclass(frozen=True)
class RankedCards:
    state: TodayState
    ordered: tuple[ActionCard, ...]  # every visible card in rank order
    shown: tuple[ActionCard, ...]  # the first ``top_n`` of ``ordered``
    more_count: int  # "n more"
    suppressed: tuple[SuppressedCard, ...]


def _suppressor(card: ActionCard, breaches: list[ActionCard]) -> ActionCard | None:
    for b in breaches:  # breaches are in rank order, so the highest-priority suppressor wins
        if b.layer < card.layer and (b.goal_id is None or b.goal_id == card.goal_id):
            return b
    return None


def rank_cards(cards: Iterable[ActionCard], top_n: int = DEFAULT_TOP_N) -> RankedCards:
    if top_n < 0:
        raise InvalidInput("top_n must be ≥ 0")
    items = sorted(cards, key=rank_key)
    ids = [c.card_id for c in items]
    if len(ids) != len(set(ids)):
        raise InvalidInput("duplicate card_id in the day's cards")
    no_action = [c for c in items if c.kind is CardKind.NO_ACTION_NEEDED]
    others = [c for c in items if c.kind is not CardKind.NO_ACTION_NEEDED]
    if no_action and others:
        raise InvalidInput("NO_ACTION_NEEDED cannot appear alongside other cards")
    if len(no_action) > 1:
        raise InvalidInput("at most one NO_ACTION_NEEDED card")

    breaches = [c for c in items if c.suppresses_lower_layers]
    visible: list[ActionCard] = []
    suppressed: list[SuppressedCard] = []
    for c in items:
        by = _suppressor(c, breaches)
        if by is None:
            visible.append(c)
        else:
            suppressed.append(SuppressedCard(card=c, suppressed_by=by.card_id))

    if any(c.is_action for c in visible):
        state = TodayState.ACTIONS
    elif any(c.abstentions for c in visible):
        state = TodayState.ABSTAINED_ONLY
    else:
        state = TodayState.NOTHING_NEEDED
    ordered = tuple(visible)
    return RankedCards(
        state=state,
        ordered=ordered,
        shown=ordered[:top_n],
        more_count=max(0, len(ordered) - top_n),
        suppressed=tuple(suppressed),
    )
