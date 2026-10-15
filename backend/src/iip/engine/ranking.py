"""Deterministic ranking policy (ADR-0005, risk-methodology.md §9).

There is no composite score. The pipeline is:
  1. hard eligibility (each failure → reason code)
  2. horizon-matched ₹ outcome bands (computed upstream, after costs and assumed tax)
  3. certainty tiers
  4. lexicographic ordering by objective, with final tiebreak on instrument_id (a total order).
An empty eligible set yields NO_SUITABLE_CANDIDATE — a winner is never forced.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import IntEnum, StrEnum
from typing import Any

from iip.engine.determinism import content_hash
from iip.engine.errors import InvalidInput
from iip.engine.money import D, engine_context, money

POLICY_VERSION = "ranking_policy@1.2.0"
# User decisions 2026-10-15 (red-team RT-19 / RT-20):
MIN_PRESERVATION_INDEPENDENT_WINDOWS = 20  # market-linked options need ≥ 20 independent windows for objectives A/B/C
MIN_GROWTH_HORIZON_DAYS = 365  # growth objectives D/E require a withdrawal date at least 12 months away
# ranking_policy@1.2.0 (red-team RT-23): a debt-holding fund whose portfolio credit quality is unknown fails any credit
# floor the user sets (CREDIT_QUALITY_UNKNOWN) — unknown is never assumed safe.
NO_CANDIDATE_MESSAGE = "No suitable candidate found under the current constraints."

# Higher index = stronger credit. None (not applicable, e.g. a fund) is handled separately.
CREDIT_SCALE: tuple[str, ...] = (
    "UNRATED", "D", "C", "B-", "B", "B+", "BB-", "BB", "BB+", "BBB-", "BBB", "BBB+",
    "A-", "A", "A+", "AA-", "AA", "AA+", "AAA", "SOVEREIGN",
)  # fmt: skip


class Objective(StrEnum):
    CAPITAL_PRESERVATION = "A_capital_preservation"
    INCOME = "B_income"
    LIQUIDITY = "C_liquidity"
    GROWTH = "D_growth"
    AGGRESSIVE_GROWTH = "E_aggressive_growth"


PRESERVING_OBJECTIVES = frozenset({Objective.CAPITAL_PRESERVATION, Objective.INCOME, Objective.LIQUIDITY})
GROWTH_OBJECTIVES = frozenset({Objective.GROWTH, Objective.AGGRESSIVE_GROWTH})


class Tier(IntEnum):
    T1 = 1  # contractual sovereign (T-bill, G-sec held to maturity)
    T2 = 2  # contractual non-sovereign (FD within DICGC, AAA bond held to maturity)
    T3 = 3  # market-dependent, bounded (overnight/liquid/money-market funds; bonds with early exit)
    T4 = 4  # market-dependent, unbounded (duration/credit funds, hybrid, equity, gold)


class RankStatus(StrEnum):
    RANKED = "RANKED"
    NO_SUITABLE_CANDIDATE = "NO_SUITABLE_CANDIDATE"


@dataclass(frozen=True)
class OutcomeBand:
    """₹ value at the horizon for the requested amount, after costs and assumed tax.

    Contractual instruments have a point outcome (q05 = q50 = q95)."""

    q05: Decimal
    q50: Decimal
    q95: Decimal
    is_contractual: bool = False

    def __post_init__(self) -> None:
        if not (self.q05 <= self.q50 <= self.q95):
            raise InvalidInput(f"outcome band must satisfy q05 ≤ q50 ≤ q95, got {self.q05}, {self.q50}, {self.q95}")

    @classmethod
    def contractual(cls, value: Decimal) -> OutcomeBand:
        return cls(q05=value, q50=value, q95=value, is_contractual=True)

    @property
    def width(self) -> Decimal:
        with engine_context():
            return self.q95 - self.q05


@dataclass(frozen=True)
class Candidate:
    instrument_id: str
    name: str
    tier: Tier
    outcome: OutcomeBand
    loss_frequency: Decimal | None  # historical frequency of a nominal loss at H (None = unknown)
    days_to_cash: int
    exit_cost: Decimal  # fraction of amount
    horizon_fit: bool
    credit_rating: str | None  # None = not applicable (e.g. a fund); "UNRATED" fails any floor
    data_ok: bool
    min_investment: Decimal | None = None
    flags: tuple[str, ...] = ()
    independent_windows: int | None = None  # evidence behind loss_frequency (None = not applicable / unknown)
    # True when the instrument carries credit risk whose quality is not established (e.g. a debt fund with no current
    # factsheet "lowest rating held"). Checked only when the user sets a credit floor.
    credit_quality_unknown: bool = False


@dataclass(frozen=True)
class RankingRequest:
    objective: Objective
    amount: Decimal
    horizon_days: int
    max_days_to_cash: int | None = None
    max_exit_cost: Decimal | None = None
    credit_floor: str | None = None
    loss_budget: Decimal | None = None  # fraction, required for growth objectives
    risk_lambda: Decimal = field(default_factory=lambda: D("0.5"))
    epsilon_loss_frequency: Decimal = field(default_factory=lambda: D("0.01"))
    preservation_floor: Decimal = field(default_factory=lambda: D("0"))  # x: q05 ≥ amount·(1 − x)
    excluded_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RankedItem:
    rank: int
    instrument_id: str
    name: str
    tier: Tier
    outcome: OutcomeBand
    reasons: tuple[str, ...]
    sort_key_display: dict[str, str]


@dataclass(frozen=True)
class ExcludedItem:
    instrument_id: str
    name: str
    reason_codes: tuple[str, ...]
    messages: tuple[str, ...]


@dataclass(frozen=True)
class RankingResult:
    status: RankStatus
    ranked: tuple[RankedItem, ...]
    excluded: tuple[ExcludedItem, ...]
    message: str | None
    policy_version: str
    policy: dict[str, str]
    input_hash: str
    output_hash: str


def _validate(request: RankingRequest, candidates: Sequence[Candidate]) -> None:
    if request.amount <= 0:
        raise InvalidInput("amount must be > 0")
    if request.horizon_days <= 0:
        raise InvalidInput("horizon_days must be > 0")
    if not (D("0") <= request.risk_lambda <= D("1")):
        raise InvalidInput("risk_lambda must be in [0, 1]")
    if request.objective in GROWTH_OBJECTIVES:
        if request.horizon_days < MIN_GROWTH_HORIZON_DAYS:
            raise InvalidInput("growth objectives require a withdrawal date at least 12 months away")
        if request.loss_budget is None:
            raise InvalidInput("growth objectives require an explicit, user-entered loss budget")
        if not (D("0") <= request.loss_budget <= D("1")):
            raise InvalidInput("loss_budget must be a fraction in [0, 1]")
    if request.credit_floor is not None and request.credit_floor not in CREDIT_SCALE:
        raise InvalidInput(f"unknown credit floor {request.credit_floor!r}")
    ids = [c.instrument_id for c in candidates]
    if len(ids) != len(set(ids)):
        raise InvalidInput("duplicate instrument ids in candidate set")
    for c in candidates:
        if c.credit_rating is not None and c.credit_rating not in CREDIT_SCALE:
            raise InvalidInput(f"{c.instrument_id}: unknown credit rating {c.credit_rating!r}")
        if c.days_to_cash < 0 or c.exit_cost < 0:
            raise InvalidInput(f"{c.instrument_id}: negative liquidity inputs")


def _eligibility(request: RankingRequest, c: Candidate) -> list[tuple[str, str]]:
    failures: list[tuple[str, str]] = []
    with engine_context():
        if c.instrument_id in request.excluded_ids:
            failures.append(("EXCLUDED_BY_USER", "You excluded this instrument."))
        if not c.horizon_fit:
            failures.append(("HORIZON_MISMATCH", "Maturity, lock-in or exit-load window does not fit the horizon."))
        if not c.data_ok:
            failures.append(("INSUFFICIENT_OR_STALE_DATA", "Required data is missing, stale or failed validation."))
        if request.max_days_to_cash is not None and c.days_to_cash > request.max_days_to_cash:
            failures.append(
                ("LIQUIDITY_TOO_SLOW", f"Needs {c.days_to_cash} days to cash; limit is {request.max_days_to_cash}.")
            )
        if request.max_exit_cost is not None and c.exit_cost > request.max_exit_cost:
            failures.append(("EXIT_COST_TOO_HIGH", "Exit cost exceeds your maximum."))
        if c.min_investment is not None and c.min_investment > request.amount:
            failures.append(("BELOW_MINIMUM_TICKET", "Amount is below the instrument's minimum investment."))
        if request.credit_floor is not None and c.credit_quality_unknown:
            failures.append(
                (
                    "CREDIT_QUALITY_UNKNOWN",
                    "Portfolio credit quality is not known from a current factsheet, so your credit floor cannot be "
                    "checked; it is not assumed safe.",
                )
            )
        elif request.credit_floor is not None and c.credit_rating is not None:
            if CREDIT_SCALE.index(c.credit_rating) < CREDIT_SCALE.index(request.credit_floor):
                failures.append(("BELOW_CREDIT_FLOOR", f"Rating {c.credit_rating} is below your floor."))

        if request.objective in PRESERVING_OBJECTIVES:
            floor = request.amount * (D("1") - request.preservation_floor)
            if c.outcome.is_contractual and c.tier > Tier.T2:
                # A contractual promise outside T1/T2 carries unquantified issuer credit risk (e.g. an uninsured
                # deposit, or one whose maturity value exceeds the DICGC cover). risk-methodology §9 Step 1 lists the
                # DICGC limit as a hard constraint; ADR-0005: what is unknown is never assumed safe.
                failures.append(
                    ("UNINSURED_CREDIT_EXPOSURE", "Part or all of the amount carries uninsured issuer credit risk.")
                )
            if not c.outcome.is_contractual and (
                c.independent_windows is None or c.independent_windows < MIN_PRESERVATION_INDEPENDENT_WINDOWS
            ):
                n = MIN_PRESERVATION_INDEPENDENT_WINDOWS
                msg = f"Fewer than {n} independent historical windows at this horizon to establish a low loss rate."
                failures.append(("INSUFFICIENT_LOSS_EVIDENCE", msg))
            if not c.outcome.is_contractual:
                if c.loss_frequency is None:
                    failures.append(
                        ("MISSING_LOSS_EVIDENCE", "No reliable loss history at this horizon; not assumed safe.")
                    )
                elif c.loss_frequency > request.epsilon_loss_frequency:
                    failures.append(
                        (
                            "LOSS_FREQUENCY_ABOVE_LIMIT",
                            "Historical frequency of loss at this horizon exceeds the limit.",
                        )
                    )
            if c.outcome.q05 < floor:
                failures.append(("LOWER_BAND_BELOW_FLOOR", "The 5th-percentile outcome is below your capital floor."))
        else:
            assert request.loss_budget is not None
            floor = request.amount * (D("1") - request.loss_budget)
            if c.outcome.q05 < floor:
                failures.append(
                    ("LOWER_BAND_BELOW_LOSS_BUDGET", "The 5th-percentile outcome exceeds your stated loss budget.")
                )
    return failures


def _certainty_equivalent(request: RankingRequest, c: Candidate) -> Decimal:
    with engine_context():
        return c.outcome.q50 - request.risk_lambda * (c.outcome.q50 - c.outcome.q05)


def _sort_key(request: RankingRequest, c: Candidate) -> tuple[Any, ...]:
    o = c.outcome
    match request.objective:
        case Objective.CAPITAL_PRESERVATION:
            return (int(c.tier), -o.q05, c.days_to_cash, c.exit_cost, c.instrument_id)
        case Objective.INCOME:
            return (int(c.tier), o.width, -o.q50, c.instrument_id)
        case Objective.LIQUIDITY:
            return (c.days_to_cash, c.exit_cost, -o.q05, c.instrument_id)
        case Objective.GROWTH | Objective.AGGRESSIVE_GROWTH:
            return (-_certainty_equivalent(request, c), int(c.tier), c.instrument_id)
    raise InvalidInput(f"unknown objective {request.objective}")  # pragma: no cover


def _reasons(request: RankingRequest, c: Candidate) -> tuple[tuple[str, ...], dict[str, str]]:
    o = c.outcome
    display = {
        "tier": c.tier.name,
        "q05": str(money(o.q05)),
        "q50": str(money(o.q50)),
        "q95": str(money(o.q95)),
        "days_to_cash": str(c.days_to_cash),
    }
    reasons = [
        "Passed every hard constraint for this objective.",
        f"Certainty tier {c.tier.name}.",
        "Contractual outcome."
        if o.is_contractual
        else "Market-dependent outcome band (scenario range, not a guarantee).",
    ]
    match request.objective:
        case Objective.CAPITAL_PRESERVATION:
            reasons.append("Ordered by tier, then 5th-percentile outcome, then liquidity and cost.")
        case Objective.INCOME:
            display["band_width"] = str(money(o.width))
            reasons.append("Ordered by tier, then narrowness of the outcome band, then median.")
        case Objective.LIQUIDITY:
            reasons.append("Ordered by days to cash, then exit cost, then 5th-percentile outcome.")
        case Objective.GROWTH | Objective.AGGRESSIVE_GROWTH:
            display["certainty_equivalent"] = str(money(_certainty_equivalent(request, c)))
            reasons.append(f"Ordered by certainty-equivalent q50 − λ(q50 − q05) with λ = {request.risk_lambda}.")
    if c.flags:
        reasons.append("Flags: " + ", ".join(c.flags))
    return tuple(reasons), display


def _policy(request: RankingRequest) -> dict[str, str]:
    return {
        "version": POLICY_VERSION,
        "objective": request.objective.value,
        "epsilon_loss_frequency": str(request.epsilon_loss_frequency),
        "preservation_floor": str(request.preservation_floor),
        "risk_lambda": str(request.risk_lambda),
        "loss_budget": "" if request.loss_budget is None else str(request.loss_budget),
        "credit_floor": request.credit_floor or "",
        "min_preservation_independent_windows": str(MIN_PRESERVATION_INDEPENDENT_WINDOWS),
        "min_growth_horizon_days": str(MIN_GROWTH_HORIZON_DAYS),
    }


def rank(request: RankingRequest, candidates: Sequence[Candidate]) -> RankingResult:
    _validate(request, candidates)
    ordered_input = sorted(candidates, key=lambda c: c.instrument_id)
    input_hash = content_hash({"request": request, "candidates": ordered_input, "policy": POLICY_VERSION})

    eligible: list[Candidate] = []
    excluded: list[ExcludedItem] = []
    for c in ordered_input:
        failures = _eligibility(request, c)
        if failures:
            excluded.append(
                ExcludedItem(c.instrument_id, c.name, tuple(f[0] for f in failures), tuple(f[1] for f in failures))
            )
        else:
            eligible.append(c)

    eligible.sort(key=lambda c: _sort_key(request, c))
    ranked: list[RankedItem] = []
    for i, c in enumerate(eligible, start=1):
        reasons, display = _reasons(request, c)
        ranked.append(RankedItem(i, c.instrument_id, c.name, c.tier, c.outcome, reasons, display))

    status = RankStatus.RANKED if ranked else RankStatus.NO_SUITABLE_CANDIDATE
    message = None if ranked else NO_CANDIDATE_MESSAGE
    policy = _policy(request)
    body = {"status": status, "ranked": ranked, "excluded": excluded, "message": message, "policy": policy}
    return RankingResult(
        status=status,
        ranked=tuple(ranked),
        excluded=tuple(excluded),
        message=message,
        policy_version=POLICY_VERSION,
        policy=policy,
        input_hash=input_hash,
        output_hash=content_hash(body),
    )
