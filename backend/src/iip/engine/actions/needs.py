"""The "Needs from you" list: missing inputs ranked by the ₹ each one unlocks (design-user-first.md §5.3; graft 7).

Abstentions from the day's cards are grouped by ``missing_input``. Each card's abstention may carry an upper bound on
the ₹ the input unlocks, with its basis and the formula that computed it (e.g. ``1,25,000 × 12.5 % = ₹15,625`` of
deferred tax). Bounds are **never added**: not across bases (₹ on different bases is never summed) and not across
cards (two cards' bounds for one input may count the same rupees). A need ranks by its **largest single bound**, and
every contributing bound is listed so the user sees where the number came from. Needs without any bound rank last.

Order: ``(rank amount descending, unbounded last, missing_input)``, a total order. Pure: no clock, IO or randomness.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from iip.engine.actions.contracts import ActionCard, ImpactBasis

NEEDS_VERSION = "actions.needs@1"


@dataclass(frozen=True)
class NeedUnlock:
    card_id: str
    amount_inr: Decimal
    basis: ImpactBasis
    formula_id: str


@dataclass(frozen=True)
class Need:
    missing_input: str
    codes: tuple[str, ...]
    how_to_fix: tuple[str, ...]
    card_ids: tuple[str, ...]
    unlocks: tuple[NeedUnlock, ...]  # every per-card bound, largest first; never summed
    rank_amount_inr: Decimal | None  # the largest single bound, or None when no card could bound it
    rank_basis: ImpactBasis | None


def _unlock_key(u: NeedUnlock) -> tuple[Decimal, str, str]:
    return (-u.amount_inr, u.basis.value, u.card_id)


def collect_needs(cards: Iterable[ActionCard]) -> tuple[Need, ...]:
    codes: dict[str, set[str]] = {}
    fixes: dict[str, set[str]] = {}
    card_ids: dict[str, set[str]] = {}
    unlocks: dict[str, list[NeedUnlock]] = {}
    for card in cards:
        for a in card.abstentions:
            key = a.missing_input
            codes.setdefault(key, set()).add(a.code)
            fixes.setdefault(key, set()).add(a.how_to_fix)
            card_ids.setdefault(key, set()).add(card.card_id)
            bucket = unlocks.setdefault(key, [])
            if a.unlock_upper_bound_inr is not None and a.unlock_basis is not None and a.unlock_formula_id is not None:
                bucket.append(NeedUnlock(card.card_id, a.unlock_upper_bound_inr, a.unlock_basis, a.unlock_formula_id))
    needs: list[Need] = []
    for key, key_codes in codes.items():
        bounds = tuple(sorted(set(unlocks[key]), key=_unlock_key))
        top = bounds[0] if bounds else None
        needs.append(
            Need(
                missing_input=key,
                codes=tuple(sorted(key_codes)),
                how_to_fix=tuple(sorted(fixes[key])),
                card_ids=tuple(sorted(card_ids[key])),
                unlocks=bounds,
                rank_amount_inr=top.amount_inr if top else None,
                rank_basis=top.basis if top else None,
            )
        )
    needs.sort(
        key=lambda n: (
            n.rank_amount_inr is None,
            -n.rank_amount_inr if n.rank_amount_inr is not None else Decimal(0),
            n.missing_input,
        )
    )
    return tuple(needs)
