"""Build ranking candidates from instrument facts (pure; ADR-0005 Step 2: horizon-matched ₹ outcome bands).

Every candidate is evaluated for the SAME amount and the SAME withdrawal date, after costs and assumed tax.
Anything that cannot be established from supplied facts makes the candidate ineligible with a reason —
it is never filled with a default (requirements.md §3.6a).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise

from iip.engine import fixed_income as fi
from iip.engine import tax as tx
from iip.engine.deposits import fd_maturity
from iip.engine.errors import EngineError, InvalidInput
from iip.engine.feasibility import percentile_type7
from iip.engine.fixed_income import tbill_days, tbill_price
from iip.engine.freshness import nav_is_stale
from iip.engine.money import ONE, ZERO, D, engine_context
from iip.engine.ranking import CREDIT_SCALE, Candidate, OutcomeBand, Tier

ENGINE_VERSION = "candidates@1.1.0"
MIN_INDEPENDENT_WINDOWS = 10  # validation-methodology §8: below this the empirical distribution is refused
FULL_BAND_INDEPENDENT_WINDOWS = 20  # q05/q95 need ≥ 20 independent windows; otherwise worst observed window
MAX_NAV_STALENESS_DAYS = 7  # calculation-methodology §0: last price on or before t within 7 calendar days
MIN_HISTORY_DAYS = 365  # validation-methodology §8: newly launched (< 1 year of history) → suppressed
FACTSHEET_MAX_AGE_DAYS = 45  # risk-methodology §8: factsheet / holdings snapshot ≤ 45 days old


class TaxBasis(StrEnum):
    USER_PROFILE = "user_profile"
    ILLUSTRATIVE = "illustrative_30_percent_slab"


@dataclass(frozen=True)
class CandidateEvidence:
    """Everything needed to explain a candidate's outcome band (rendered by the API as Explained values)."""

    formula_id: str
    gross_end_value: Decimal | None  # contractual proceeds before tax (None for distributional)
    band_gross: tuple[Decimal, Decimal, Decimal] | None  # (low, mid, high) before tax
    tax_low: Decimal
    tax_mid: Decimal
    tax_high: Decimal
    tax_basis: TaxBasis
    tax_rule_ids: tuple[str, ...]
    tax_unverified: bool
    costs: tuple[tuple[str, Decimal], ...]
    n_windows: int | None = None
    n_independent: int | None = None
    lower_band_method: str | None = None
    window_span: tuple[date, date] | None = None
    inputs: tuple[tuple[str, str], ...] = ()
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class BuiltCandidate:
    candidate: Candidate
    evidence: CandidateEvidence | None
    ineligible_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------------------------- tax helper


def _tax_on_gain(
    gain: Decimal,
    *,
    lot_id: str,
    instrument_class: str,
    acquired: date,
    transferred: date,
    ruleset: tx.TaxRuleSet,
    profile: tx.TaxProfile | None,
    listed: bool | None = None,
    equity_share: Decimal | None = None,
    debt_share: Decimal | None = None,
) -> tuple[Decimal, tx.TaxReport, str | None]:
    """Tax payable on a single gain under the user's profile, or the conservative illustrative 30 % profile.

    Rates beyond ``ruleset.coverage_to`` are not yet legislated. Rather than refuse every horizon that crosses the
    financial-year end, the gain is priced under the law in force on the coverage end (``rates_as_of``), assumed
    unchanged, and the result is FLAGGED. The holding period is classified from the ACTUAL acquisition and transfer
    dates (RT-17: clamping the transfer date used to turn a 400-day equity holding into STCG), and acquisition-date
    conditions see the actual acquisition date, so no lot crosses a rule boundary. The result therefore equals "actual
    dates under unchanged law" — the stated assumption — and never understates it.
    """
    flag: str | None = None
    rates_as_of: date | None = None
    if transferred > ruleset.coverage_to:
        flag = f"TAX_RULES_ASSUMED_UNCHANGED_AFTER_{ruleset.coverage_to.isoformat()}"
        rates_as_of = ruleset.coverage_to
    disposal = tx.Disposal(
        lot_id=lot_id,
        instrument_class=instrument_class,
        transfer_date=transferred,
        gain_inr=gain,
        acquisition_date=acquired,
        listed=listed,
        domestic_equity_share=equity_share,
        debt_share=debt_share,
    )
    use = profile if profile is not None else tx.ILLUSTRATIVE_PROFILES[0]
    report = tx.compute_tax([disposal], ruleset, use, rates_as_of=rates_as_of)
    return report.scenarios[0].total_tax_inr, report, flag


def _basis(profile: tx.TaxProfile | None) -> TaxBasis:
    return TaxBasis.USER_PROFILE if profile is not None else TaxBasis.ILLUSTRATIVE


def _ineligible(
    instrument_id: str, name: str, tier: Tier, reasons: Sequence[str], amount: Decimal, *, warnings: Sequence[str] = ()
) -> BuiltCandidate:
    cand = Candidate(
        instrument_id=instrument_id,
        name=name,
        tier=tier,
        outcome=OutcomeBand.contractual(amount),
        loss_frequency=None,
        days_to_cash=0,
        exit_cost=ZERO,
        horizon_fit=False,
        credit_rating=None,
        data_ok=False,
    )
    return BuiltCandidate(cand, None, tuple(reasons), tuple(warnings))


# --------------------------------------------------------------------------------------------- T-bill

# RBI: "The minimum amount for bidding will be ₹10,000 (face value) and thereafter in multiples in ₹10,000"
# (RBI/2021-2022/124, 12-Nov-2021, non-competitive bidding incl. Retail Direct; RBI Retail Direct FAQ, T-bills ₹10,000).
TBILL_MIN_FACE_INR = D(10000)
TBILL_LOT_FACE_INR = D(10000)
TBILL_MIN_TICKET_SOURCE = "RBI/2021-2022/124 (12-Nov-2021): minimum ₹10,000 face, multiples of ₹10,000"


def tbill_candidate(
    *,
    instrument_id: str,
    name: str,
    amount: Decimal,
    quoted_yield: Decimal,
    settlement: date,
    maturity: date,
    withdrawal: date,
    ruleset: tx.TaxRuleSet,
    profile: tx.TaxProfile | None,
) -> BuiltCandidate:
    """Buy at the quoted money-market yield, hold to maturity, keep the cash until the withdrawal date (0 %).

    RT-22: face value is bought in whole ₹10,000 lots (RBI minimum bid and multiple); the cash that does not fill a
    whole lot is held at 0 % (flagged ``UNINVESTED_REMAINDER_AT_ZERO``). Below the cost of one lot the candidate is
    ``BELOW_MINIMUM_TICKET``.
    """
    if maturity > withdrawal:
        return _ineligible(
            instrument_id, name, Tier.T1, ["HORIZON_MISMATCH: matures after your withdrawal date"], amount
        )
    try:
        days = tbill_days(settlement, maturity)
        priced = tbill_price(quoted_yield, days)
        with engine_context():
            lot_cost = TBILL_LOT_FACE_INR * priced.price / D(100)
            lots = int(amount / lot_cost)
            while lots > 0 and lot_cost * lots > amount:  # guard the last-digit rounding of the division
                lots -= 1
            while lot_cost * (lots + 1) <= amount:
                lots += 1
        if lots * TBILL_LOT_FACE_INR < TBILL_MIN_FACE_INR:
            reason = (
                f"BELOW_MINIMUM_TICKET: the minimum T-bill bid is ₹{TBILL_MIN_FACE_INR:,} face value (costs "
                f"₹{lot_cost.quantize(D('0.01'))} at this yield); {TBILL_MIN_TICKET_SOURCE}"
            )
            cand = Candidate(
                instrument_id=instrument_id, name=name, tier=Tier.T1, outcome=OutcomeBand.contractual(amount),
                loss_frequency=None, days_to_cash=0, exit_cost=ZERO, horizon_fit=False, credit_rating=None,
                data_ok=False, min_investment=lot_cost,
            )  # fmt: skip
            return BuiltCandidate(cand, None, (reason,), priced.warnings)
        with engine_context():
            face = TBILL_LOT_FACE_INR * lots
            cost = lot_cost * lots
            leftover = amount - cost
            gain = face - cost
        tax_amt, report, tax_flag = _tax_on_gain(
            gain, lot_id=instrument_id, instrument_class="TBILL", acquired=settlement, transferred=maturity,
            ruleset=ruleset, profile=profile,
        )  # fmt: skip
    except EngineError as exc:
        return _ineligible(instrument_id, name, Tier.T1, [f"{exc.code}: {exc}"], amount)
    with engine_context():
        gross = face + leftover
        net = gross - tax_amt
    evidence = CandidateEvidence(
        formula_id="CAND_TBILL@2",
        gross_end_value=gross,
        band_gross=None,
        tax_low=tax_amt,
        tax_mid=tax_amt,
        tax_high=tax_amt,
        tax_basis=_basis(profile),
        tax_rule_ids=report.rule_ids_used,
        tax_unverified=report.unverified_assumption,
        costs=(),
        inputs=(
            ("amount", str(amount)),
            ("quoted_yield", str(quoted_yield)),
            ("settlement", settlement.isoformat()),
            ("maturity", maturity.isoformat()),
            ("days", str(days)),
            ("price_per_100", str(priced.price)),
            ("lots", str(lots)),
            ("face_value", str(face)),
            ("uninvested_cash", str(leftover)),
        ),
        assumptions=(
            "Held to maturity; face value repaid by the Government of India on the maturity date",
            "Cash from maturity to your withdrawal date earns nothing (conservative)",
            f"Face value bought in whole ₹{TBILL_LOT_FACE_INR:,} lots ({TBILL_MIN_TICKET_SOURCE}); the remainder "
            "is held as cash at 0 % (conservative)",
        ),
        limitations=(
            "The quoted yield is the one you entered with its citation; the price you obtain may differ",
            "Selling before maturity exposes you to price risk (not modelled for this candidate)",
            "Bid/ask spreads are not modelled",
        ),
    )
    flags_tb: list[str] = []
    if report.unverified_assumption:
        flags_tb.append("TAX_RULE_UNVERIFIED")
    if tax_flag is not None:
        flags_tb.append(tax_flag)
    if leftover > 0:
        flags_tb.append("UNINVESTED_REMAINDER_AT_ZERO")
    cand = Candidate(
        instrument_id=instrument_id,
        name=name,
        tier=Tier.T1,
        outcome=OutcomeBand.contractual(net),
        loss_frequency=ZERO,
        days_to_cash=1,
        exit_cost=ZERO,
        horizon_fit=True,
        credit_rating="SOVEREIGN",
        data_ok=True,
        min_investment=lot_cost,
        flags=tuple(flags_tb),
    )
    return BuiltCandidate(cand, evidence, (), priced.warnings)


# --------------------------------------------------------------------------------------------- fixed deposit

DICGC_LIMIT = D(500000)  # per depositor per bank, principal + interest (research: VERIFIED-PRIMARY)


def fd_candidate(
    *,
    instrument_id: str,
    name: str,
    amount: Decimal,
    rate: Decimal,
    start: date,
    tenure_days: int,
    withdrawal: date,
    dicgc_eligible: bool,
    premature_penalty: Decimal | None,
    other_deposits_same_bank: Decimal | None,
    ruleset: tx.TaxRuleSet,
    profile: tx.TaxProfile | None,
    short_tenure_cutoff_months: int = 6,
    sovereign_backed: bool = False,
) -> BuiltCandidate:
    """Cumulative deposit held to maturity. ``sovereign_backed`` = a Post Office Time Deposit (Government of India
    obligation, not DICGC-insured): contractual sovereign credit, so T1 rather than uninsured bank credit.

    ``other_deposits_same_bank`` = None means nothing is recorded about the user's other deposits at this bank. DICGC
    cover then cannot be established, so the deposit is never treated as zero-loss insured credit (ECC F1)."""
    maturity = start + timedelta(days=tenure_days)
    if maturity > withdrawal:
        return _ineligible(
            instrument_id, name, Tier.T2, ["HORIZON_MISMATCH: matures after your withdrawal date"], amount
        )
    try:
        res = fd_maturity(amount, rate, start, maturity, short_tenure_cutoff_months=short_tenure_cutoff_months)
        tax_amt, report, tax_flag = _tax_on_gain(
            res.interest, lot_id=instrument_id, instrument_class="INTEREST", acquired=start, transferred=maturity,
            ruleset=ruleset, profile=profile,
        )  # fmt: skip
    except EngineError as exc:
        return _ineligible(instrument_id, name, Tier.T2, [f"{exc.code}: {exc}"], amount)
    with engine_context():
        exposure = None if other_deposits_same_bank is None else other_deposits_same_bank + res.maturity_amount
        fully_insured = dicgc_eligible and exposure is not None and exposure <= DICGC_LIMIT
        credit_safe = sovereign_backed or fully_insured
        net = res.maturity_amount - tax_amt
    flags: list[str] = []
    if sovereign_backed:
        flags.append("SOVEREIGN_BACKED_NOT_DICGC")
    elif not dicgc_eligible:
        flags.append("NOT_DICGC_INSURED")
    elif exposure is None:
        flags.append("EXISTING_DEPOSITS_NOT_RECORDED")
    elif not fully_insured:
        flags.append("EXCEEDS_DICGC_LIMIT_AT_THIS_BANK")
    if report.unverified_assumption:
        flags.append("TAX_RULE_UNVERIFIED")
    if premature_penalty is None:
        flags.append("PREMATURE_PENALTY_UNKNOWN")
    if tax_flag is not None:
        flags.append(tax_flag)
    evidence = CandidateEvidence(
        formula_id="CAND_FD@1",
        gross_end_value=res.maturity_amount,
        band_gross=None,
        tax_low=tax_amt,
        tax_mid=tax_amt,
        tax_high=tax_amt,
        tax_basis=_basis(profile),
        tax_rule_ids=report.rule_ids_used,
        tax_unverified=report.unverified_assumption,
        costs=(),
        inputs=(
            ("amount", str(amount)),
            ("rate", str(rate)),
            ("start", start.isoformat()),
            ("maturity", maturity.isoformat()),
            ("method", res.method.value),
            ("dicgc_exposure_at_bank", str(exposure))
            if exposure is not None
            else ("dicgc_existing_deposits", "not recorded"),
        ),
        assumptions=(*res.conventions, "Interest is taxed in the year of maturity (cumulative FD; TDS ignored)"),
        limitations=(
            "Card rate entered by you with its citation; banks change rates without notice",
            "DICGC cover is per depositor per bank across all branches, principal plus interest",
        ),
    )
    # Only a fully insured deposit is T2 (contractual non-sovereign). Uninsured exposure is bank credit risk.
    tier = Tier.T1 if sovereign_backed else Tier.T2 if fully_insured else Tier.T3
    with engine_context():
        years = Decimal(tenure_days) / Decimal(365)
        exit_cost = premature_penalty * years if premature_penalty is not None else ONE
    cand = Candidate(
        instrument_id=instrument_id,
        name=name,
        tier=tier,
        outcome=OutcomeBand.contractual(net),
        loss_frequency=ZERO if credit_safe else None,
        days_to_cash=1 if premature_penalty is not None else tenure_days,
        exit_cost=exit_cost,
        horizon_fit=True,
        # Insured: credit is not the binding risk (None = n/a). Uninsured exposure has no rating in the system, so it
        # is UNRATED and fails any credit floor the user sets (it is never silently skipped).
        credit_rating="SOVEREIGN" if sovereign_backed else None if fully_insured else "UNRATED",
        data_ok=True,
        flags=tuple(flags),
    )
    return BuiltCandidate(cand, evidence, (), res.warnings)


# --------------------------------------------------------------------------------------------- G-secs, SDLs, bonds

MAX_BOND_QUOTE_STALENESS_DAYS = 7  # a cited price/yield older than 7 calendar days is STALE_DATA
MAX_RATING_AGE_DAYS = 365  # a rating action older than 12 months is STALE_RATING
EARLY_EXIT_SHOCKS_BP: tuple[int, int, int] = (100, 0, -100)  # explicit stress scenarios (low, mid, high)
BOND_SETTLEMENT_DAYS = 1  # T+1 (calendar-day approximation; no holiday calendar is loaded)


@dataclass(frozen=True)
class BondTerms:
    """Contractual terms the user entered with a citation. Nothing here is defaulted."""

    kind: fi.BondKind
    coupon_rate: Decimal  # fraction
    frequency: int
    issue_date: date
    maturity: date
    face_value: Decimal  # ₹ per bond (minimum tradeable unit)
    shut_days: int  # record-date shut period (G-sec: 1 day per RBI FAQ; corporates: from the term sheet)
    listed: bool
    calls: tuple[fi.CallOption, ...] = ()
    secured: bool | None = None  # corporates only (informational)


@dataclass(frozen=True)
class BondQuote:
    """Exactly one of a clean price per ₹100 or a YTM, with the date it applied."""

    quote_date: date
    clean_price: Decimal | None = None
    ytm: Decimal | None = None
    ytm_compounding: fi.Compounding | None = None  # None → the bond's coupon frequency

    def __post_init__(self) -> None:
        if (self.clean_price is None) == (self.ytm is None):
            raise InvalidInput("a bond quote needs exactly one of clean_price or ytm")


@dataclass(frozen=True)
class BondRating:
    rating: str | None  # CREDIT_SCALE symbol, e.g. "AAA", "AA+"
    agency: str | None
    rating_date: date | None


NO_RATING = BondRating(None, None, None)


def bond_tier_and_credit(kind: fi.BondKind, rating: str | None) -> tuple[Tier, str | None, list[str]]:
    """Held-to-maturity tier, the credit symbol the ranking floor sees, and credit flags.

    SDLs: risk-methodology §7.2 calls SDLs quasi-sovereign ("state credit … shown separately"), and ADR-0005 lists
    only Government of India paper in T1. State credit is therefore T2 (contractual non-sovereign), and it is shown
    to the credit floor as AAA — never as SOVEREIGN, so a SOVEREIGN-only floor excludes it.
    """
    if kind is fi.BondKind.GSEC:
        return Tier.T1, "SOVEREIGN", []
    if kind is fi.BondKind.SDL:
        return Tier.T2, "AAA", ["SDL_STATE_GOVERNMENT_CREDIT_NOT_SOVEREIGN"]
    if rating == "AAA":
        return Tier.T2, rating, ["CORPORATE_CREDIT_RISK"]
    return Tier.T3, rating, ["CORPORATE_CREDIT_RISK", "BELOW_AAA_CREDIT_RISK"]


def _bond_checks(
    terms: BondTerms, quote: BondQuote, rating: BondRating, *, as_of: date, withdrawal: date, settlement: date
) -> list[str]:
    reasons: list[str] = []
    if quote.quote_date > as_of:
        reasons.append(f"LOOK_AHEAD: quote dated {quote.quote_date.isoformat()}, after the analysis date")
    elif (as_of - quote.quote_date).days > MAX_BOND_QUOTE_STALENESS_DAYS:
        reasons.append(
            f"STALE_DATA: price/yield quoted {quote.quote_date.isoformat()} (older than "
            f"{MAX_BOND_QUOTE_STALENESS_DAYS} days)"
        )
    if terms.kind is fi.BondKind.CORPORATE:
        if rating.rating is None or rating.agency is None or rating.rating_date is None:
            reasons.append("MISSING_RATING: a corporate bond needs a rating, agency and rating date with a citation")
        elif rating.rating not in CREDIT_SCALE or rating.rating in ("SOVEREIGN", "UNRATED"):
            reasons.append(f"INVALID_RATING: {rating.rating!r} is not a corporate rating symbol")
        elif rating.rating_date > as_of:
            reasons.append(f"LOOK_AHEAD: rating dated {rating.rating_date.isoformat()}, after the analysis date")
        elif (as_of - rating.rating_date).days > MAX_RATING_AGE_DAYS:
            reasons.append(
                f"STALE_RATING: rating action dated {rating.rating_date.isoformat()} is older than 12 months"
            )
    if terms.maturity <= settlement:
        reasons.append("HORIZON_MISMATCH: the bond matures on or before the T+1 settlement date")
    elif withdrawal <= settlement:
        reasons.append("HORIZON_MISMATCH: your withdrawal date is on or before the T+1 settlement date")
    return reasons


def _engine_bond(terms: BondTerms, settlement: date) -> tuple[fi.Bond, list[str]]:
    """The engine bond. An odd first coupon is out of scope (UnsupportedSchedule) — unless it was already paid before
    settlement, in which case it does not affect anything the buyer receives and the bond is priced without it."""
    notes: list[str] = []

    def make(issue: date | None) -> fi.Bond:
        if terms.kind is fi.BondKind.CORPORATE:
            return fi.corporate_bond(
                terms.coupon_rate, terms.maturity, terms.frequency, shut_days=terms.shut_days, issue_date=issue
            )
        if terms.frequency != 2:
            raise InvalidInput("G-secs/SDLs pay semi-annual coupons (frequency 2)")
        return fi.gsec(terms.coupon_rate, terms.maturity, issue_date=issue, shut_days=terms.shut_days, kind=terms.kind)

    try:
        return make(terms.issue_date), notes
    except fi.UnsupportedSchedule:
        bare = make(None)
        first = fi.coupon_schedule(bare, from_date=terms.issue_date).periods[0].end
        if settlement < first:
            raise
        notes.append("ODD_FIRST_COUPON_ALREADY_PAID")
        return bare, notes


@dataclass(frozen=True)
class _BondScenario:
    label: str
    gross: Decimal  # ₹ before tax (includes cash left idle)
    tax: Decimal
    net: Decimal


@dataclass
class _TaxAcc:
    rule_ids: set[str] = field(default_factory=set)
    flags: set[str] = field(default_factory=set)
    unverified: bool = False


def _bond_tax(
    acc: _TaxAcc,
    *,
    lot: str,
    interest: Decimal,
    gain: Decimal,
    tax_class: str,
    listed: bool | None,
    acquired: date,
    end: date,
    ruleset: tx.TaxRuleSet,
    profile: tx.TaxProfile | None,
) -> Decimal:
    """Interest at slab (INTEREST) plus capital gain under the GSEC/BOND rules. A capital loss is taxed at 0 and its
    set-off is NOT modelled (conservative: the benefit is never counted)."""
    total = ZERO
    parts: list[tuple[str, Decimal, str, bool | None]] = []
    if interest > 0:
        parts.append(("interest", interest, "INTEREST", None))
    if gain > 0:
        parts.append(("gain", gain, tax_class, listed))
    elif gain < 0:
        acc.flags.add("CAPITAL_LOSS_SET_OFF_NOT_MODELLED")
    for part, value, klass, lst in parts:
        t, rep, flag = _tax_on_gain(
            value, lot_id=f"{lot}#{part}", instrument_class=klass, acquired=acquired, transferred=end,
            ruleset=ruleset, profile=profile, listed=lst,
        )  # fmt: skip
        with engine_context():
            total += t
        acc.rule_ids.update(rep.rule_ids_used)
        acc.unverified = acc.unverified or rep.unverified_assumption
        if flag is not None:
            acc.flags.add(flag)
    return total


@dataclass(frozen=True)
class _Position:
    """Whole bonds bought at T+1 for the amount."""

    units: int
    factor: Decimal  # ₹ per "per-₹100" amount (units × face / 100)
    clean: Decimal
    accrued: Decimal
    buy_per_100: Decimal  # dirty, including the transaction spread on the clean price
    unit_cost: Decimal
    idle: Decimal  # cash that does not buy a whole bond
    cost_paid: Decimal  # transaction spread paid at purchase, ₹
    cost_basis: Decimal  # per ₹100 for capital gains: clean × (1 + spread); purchased accrued is not cost


def _scenario(
    acc: _TaxAcc,
    pos: _Position,
    *,
    label: str,
    lot: str,
    coupons: Decimal,
    principal_clean: Decimal,
    accrued_received: Decimal,
    end: date,
    tax_class: str,
    listed: bool | None,
    settlement: date,
    ruleset: tx.TaxRuleSet,
    profile: tx.TaxProfile | None,
) -> _BondScenario:
    """One path: per-₹100 coupons received + principal (redemption or sale, clean) + accrued interest received."""
    with engine_context():
        gross = pos.idle + pos.factor * (coupons + principal_clean + accrued_received)
        interest = pos.factor * (coupons + accrued_received)
        gain = pos.factor * (principal_clean - pos.cost_basis)
    tax_amt = _bond_tax(
        acc, lot=f"{lot}#{label}", interest=interest, gain=gain, tax_class=tax_class, listed=listed,
        acquired=settlement, end=end, ruleset=ruleset, profile=profile,
    )  # fmt: skip
    with engine_context():
        return _BondScenario(label, gross, tax_amt, gross - tax_amt)


def bond_candidate(  # noqa: PLR0915 - one linear, auditable pipeline; splitting hides the order of steps
    *,
    instrument_id: str,
    name: str,
    amount: Decimal,
    as_of: date,
    withdrawal: date,
    terms: BondTerms,
    quote: BondQuote,
    rating: BondRating,
    transaction_spread: Decimal | None,
    ruleset: tx.TaxRuleSet,
    profile: tx.TaxProfile | None,
    exit_spread_bp: int | None = None,
) -> BuiltCandidate:
    """A G-sec, SDL or corporate bond bought at T+1, in whole bonds of ``face_value``.

    * maturity ≤ withdrawal: HELD TO MATURITY — contractual proceeds = coupons received (kept as cash at 0 % until the
      withdrawal date; conservative, flagged) + redemption, after tax. A callable bond takes the WORST of the maturity
      path and every call path (the issuer decides).
    * maturity > withdrawal: EARLY EXIT — a market-dependent band from the engine's exit-price scenarios at explicit
      yield shocks of +100 / 0 / −100 bp plus the exit spread. Labelled stress scenarios; loss_frequency is unknown,
      so preservation objectives exclude it (ranking policy).

    Purchase uses the dirty price (accrued interest included). ``transaction_spread`` is a fraction of the clean price
    paid on purchase and given up on an early sale; ``None`` = unknown → computed at 0 and FLAGGED, never silently.
    """
    settlement = as_of + timedelta(days=BOND_SETTLEMENT_DAYS)
    htm_tier, credit, credit_flags = bond_tier_and_credit(terms.kind, rating.rating)
    early = terms.maturity > withdrawal
    tier = Tier.T3 if early else htm_tier
    reasons = _bond_checks(terms, quote, rating, as_of=as_of, withdrawal=withdrawal, settlement=settlement)
    if early and terms.kind is fi.BondKind.CORPORATE and not terms.listed:
        reasons.append("HORIZON_MISMATCH: unlisted bond matures after your withdrawal date and has no exchange exit")
    if transaction_spread is not None and not ZERO <= transaction_spread < D("0.1"):
        reasons.append("INVALID_INPUT: transaction spread must be a fraction in [0, 0.1)")
    if reasons:
        return _ineligible(instrument_id, name, tier, reasons, amount)
    tax_class = "BOND" if terms.kind is fi.BondKind.CORPORATE else "GSEC"
    listed: bool | None = terms.listed if terms.kind is fi.BondKind.CORPORATE else None
    acc = _TaxAcc(flags=set(credit_flags))
    warnings: list[str] = []
    spread = ZERO if transaction_spread is None else transaction_spread
    if transaction_spread is None:
        acc.flags.add("TRANSACTION_COST_UNKNOWN")
    try:
        bond, notes = _engine_bond(terms, settlement)
        acc.flags.update(notes)
        if quote.clean_price is not None:
            yr = fi.yield_from_price(bond, settlement, quote.clean_price)
            clean, accrued, entry_ytm = quote.clean_price, yr.accrued, yr.ytm
            warnings.extend(yr.warnings)
        else:
            assert quote.ytm is not None
            comp = quote.ytm_compounding or bond.compounding
            pr = fi.price_from_yield(bond, settlement, fi.Yield(quote.ytm, comp))
            clean, accrued, entry_ytm = pr.clean, pr.accrued, pr.ytm
            warnings.extend(pr.warnings)
        calls = tuple(c for c in sorted(terms.calls, key=lambda c: c.call_date) if c.call_date > settlement)
        flows = fi.bond_cashflows(bond, settlement).flows
        bad = [c.call_date for c in calls if c.call_date not in {cf.pay_date for cf in flows}]
        if bad:
            raise fi.UnsupportedSchedule(f"call date {bad[0].isoformat()} is not a coupon date of the bond")
        ytw = fi.yield_to_worst(bond, settlement, clean, calls) if calls else None
    except EngineError as exc:
        return _ineligible(instrument_id, name, tier, [f"{exc.code}: {exc}"], amount)

    with engine_context():
        buy_per_100 = clean * (ONE + spread) + accrued
        unit_cost = terms.face_value * buy_per_100 / D(100)
        units = int(amount / unit_cost)
    if units < 1:
        reason = f"BELOW_MINIMUM_TICKET: one bond of face ₹{terms.face_value} costs ₹{unit_cost:.2f} at this quote"
        return _ineligible(instrument_id, name, tier, [reason], amount)
    with engine_context():
        factor = Decimal(units) * terms.face_value / D(100)
        pos = _Position(
            units=units, factor=factor, clean=clean, accrued=accrued, buy_per_100=buy_per_100, unit_cost=unit_cost,
            idle=amount - factor * buy_per_100, cost_paid=factor * clean * spread, cost_basis=clean * (ONE + spread),
        )  # fmt: skip

    scenarios: list[_BondScenario] = []
    early_result: fi.EarlyExitResult | None = None

    def coupons_until(day: date) -> Decimal:
        with engine_context():
            return sum((cf.amount for cf in flows if cf.kind == "coupon" and cf.pay_date <= day), ZERO)

    def path(label: str, coupons: Decimal, principal_clean: Decimal, accrued_received: Decimal, end: date) -> None:
        scenarios.append(
            _scenario(acc, pos, label=label, lot=instrument_id, coupons=coupons, principal_clean=principal_clean,
                      accrued_received=accrued_received, end=end, tax_class=tax_class, listed=listed,
                      settlement=settlement, ruleset=ruleset, profile=profile)
        )  # fmt: skip

    try:
        if not early:
            path("maturity", coupons_until(terms.maturity), bond.redemption, ZERO, terms.maturity)
            for c in calls:
                path(f"call_{c.call_date.isoformat()}", coupons_until(c.call_date), c.call_price, ZERO, c.call_date)
            if calls:
                acc.flags.add("CALLABLE_WORST_PATH_USED")
        else:
            early_result = fi.early_exit_scenarios(
                bond, settlement, entry_ytm, withdrawal, shocks_bp=EARLY_EXIT_SHOCKS_BP, exit_spread_bp=exit_spread_bp
            )
            later = [c for c in calls if c.call_date > withdrawal]
            cap = later[0].call_price if later else None
            for bp, sc in zip(EARLY_EXIT_SHOCKS_BP, early_result.scenarios, strict=True):
                with engine_context():
                    exit_accrued = sc.exit_dirty - sc.exit_clean
                    exit_clean = sc.exit_clean
                    if cap is not None and exit_clean > cap:
                        exit_clean = cap
                        acc.flags.add("CALLABLE_EXIT_PRICE_CAPPED_AT_CALL_PRICE")
                    sale_clean = exit_clean * (ONE - spread)
                path(f"shock_{bp:+d}bp", sc.coupons_received, sale_clean, exit_accrued, withdrawal)
            for c in calls:
                if c.call_date <= withdrawal:  # the issuer may call before you sell: that path is in the band too
                    path(f"call_{c.call_date.isoformat()}", coupons_until(c.call_date), c.call_price, ZERO, c.call_date)
                    acc.flags.add("CALL_BEFORE_WITHDRAWAL_IN_BAND")
            acc.flags.update(("EARLY_EXIT_STRESS_SCENARIOS", "EXIT_PRICE_MARKET_DEPENDENT"))
            acc.flags.update(w for w in early_result.warnings if w == fi.EXIT_SPREAD_ASSUMED)
    except EngineError as exc:
        return _ineligible(instrument_id, name, tier, [f"{exc.code}: {exc}"], amount)

    acc.flags.update(("COUPONS_HELD_AT_ZERO_PERCENT", "PURCHASED_ACCRUED_INTEREST_NOT_DEDUCTED"))
    if acc.unverified:
        acc.flags.add("TAX_RULE_UNVERIFIED")

    if not early:
        worst = min(scenarios, key=lambda s: (s.net, s.label))
        outcome = OutcomeBand.contractual(worst.net)
        gross_end: Decimal | None = worst.gross
        band_gross: tuple[Decimal, Decimal, Decimal] | None = None
        taxes = (worst.tax, worst.tax, worst.tax)
        formula = "CAND_BOND_HTM@1"
    else:
        mid = next(s for s in scenarios if s.label == "shock_+0bp")
        lo = min(scenarios, key=lambda s: (s.net, s.label))
        hi = max(scenarios, key=lambda s: (s.net, s.label))
        outcome = OutcomeBand(q05=lo.net, q50=mid.net, q95=hi.net)
        gross_end = None
        band_gross = (lo.gross, mid.gross, hi.gross)
        taxes = (lo.tax, mid.tax, hi.tax)
        formula = "CAND_BOND_EARLY_EXIT@1"

    inputs: list[tuple[str, str]] = [
        ("amount", str(amount)),
        ("bond_kind", terms.kind.value),
        ("settlement", settlement.isoformat()),
        ("maturity", terms.maturity.isoformat()),
        ("coupon_rate", str(terms.coupon_rate)),
        ("coupon_frequency", str(terms.frequency)),
        ("day_count", bond.day_count.value),
        ("quote", "clean price" if quote.clean_price is not None else "yield to maturity"),
        ("quote_date", quote.quote_date.isoformat()),
        ("clean_price_per_100", str(clean)),
        ("accrued_per_100", str(accrued)),
        ("dirty_purchase_per_100", str(buy_per_100)),
        ("ytm", f"{entry_ytm.value} ({entry_ytm.compounding.value})"),
        ("face_value", str(terms.face_value)),
        ("units", str(units)),
        ("cash_left_idle", str(pos.idle)),
        ("transaction_spread", "unknown (0 used, flagged)" if transaction_spread is None else str(transaction_spread)),
        ("listed", str(terms.listed)),
    ]
    if ytw is not None:
        inputs.append(("yield_to_worst", f"{ytw.yield_to_worst.value} to {ytw.worst_date.isoformat()}"))
    if terms.kind is fi.BondKind.CORPORATE:
        inputs.append(("rating", f"{rating.rating} ({rating.agency}, {rating.rating_date})"))
        if terms.secured is not None:
            inputs.append(("secured", str(terms.secured)))
    inputs.extend((f"path_{s.label}", f"gross {s.gross}; tax {s.tax}; net {s.net}") for s in scenarios)
    assumptions = [
        f"Bought at T+{BOND_SETTLEMENT_DAYS} ({settlement.isoformat()}) at the quote you cited for "
        f"{quote.quote_date.isoformat()}; the price you obtain may differ",
        "Whole bonds only; cash that does not buy a whole bond is kept and earns nothing",
        "Coupons received are kept as cash at 0 % until your withdrawal date (conservative)",
        "Interest (coupons and accrued interest received) is taxed at your slab; the capital gain on the clean price "
        f"under the {tax_class} rules; purchased accrued interest is not deducted (overstates tax)",
    ]
    limitations = [
        "Price/yield, rating and terms are the ones you entered with their citations",
        "No holiday calendar: settlement is the next calendar day",
    ]
    if early:
        assert early_result is not None
        spread_bp = int(early_result.exit_spread / fi.BASIS_POINT)
        shocks = ", ".join(f"{b:+d}" for b in EARLY_EXIT_SHOCKS_BP)
        assumptions.append(
            f"Sold on {withdrawal.isoformat()} at the entry yield {shocks} bp plus an exit spread of {spread_bp} bp "
            "(stress scenarios, not probabilities)"
        )
        limitations.append("The exit price is unknown today: the band is a set of stress scenarios, not a forecast")
    else:
        assumptions.append("Held to maturity: the issuer repays the face value on the maturity date")
    if calls:
        limitations.append("Callable: the worst of the maturity and call paths is used (the issuer decides)")
    if terms.kind is fi.BondKind.CORPORATE:
        limitations.append(
            "Default or downgrade losses are not in these numbers; the rating is the only credit evidence"
        )

    evidence = CandidateEvidence(
        formula_id=formula,
        gross_end_value=gross_end,
        band_gross=band_gross,
        tax_low=taxes[0],
        tax_mid=taxes[1],
        tax_high=taxes[2],
        tax_basis=_basis(profile),
        tax_rule_ids=tuple(sorted(acc.rule_ids)),
        tax_unverified=acc.unverified,
        costs=() if transaction_spread is None else (("transaction_cost_at_purchase", pos.cost_paid),),
        inputs=tuple(inputs),
        assumptions=tuple(assumptions),
        limitations=tuple(limitations),
    )
    exchange_exit = terms.listed or terms.kind is not fi.BondKind.CORPORATE
    cand = Candidate(
        instrument_id=instrument_id,
        name=name,
        tier=tier,
        outcome=outcome,
        # Sovereign/state paper held to maturity: no loss at H. Corporates: default probability is unknown (None).
        loss_frequency=ZERO if (not early and terms.kind is not fi.BondKind.CORPORATE) else None,
        days_to_cash=BOND_SETTLEMENT_DAYS if exchange_exit else (terms.maturity - as_of).days,
        # Exit cost = the transaction spread when known and an exchange exit exists; unknown → 100 % (fails any max).
        exit_cost=spread if transaction_spread is not None and exchange_exit else ONE,
        horizon_fit=True,
        credit_rating=credit,
        data_ok=True,
        min_investment=unit_cost,
        flags=tuple(sorted(acc.flags)),
    )
    return BuiltCandidate(cand, evidence, (), tuple(dict.fromkeys(warnings)))


# --------------------------------------------------------------------------------------------- mutual fund


@dataclass(frozen=True)
class ExitLoadSpec:
    """Exit load as published in the scheme documents: charge `rate` if redeemed within `days` days."""

    days: int
    rate: Decimal
    citation: str


class MfTaxClass(StrEnum):
    EQUITY_ORIENTED = "equity_oriented"  # ≥ 65 % domestic equity (incl. arbitrage)
    SPECIFIED_DEBT = "specified_debt"  # > 65 % debt → slab regardless of holding period
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class IndexNameTable:
    """Name patterns for index funds whose category does not decide the tax class.

    The cited source of truth is ``rules/index_name_patterns.yaml`` (rule set ``IDX-NAME-2026-10``); this module keeps
    an identical copy because the engine performs no file I/O. ``tests/unit/test_mf_classification.py`` fails if the
    two ever differ.
    """

    rule_set: str
    flag: str
    applies_to_categories: tuple[str, ...]
    patterns: tuple[tuple[str, MfTaxClass, str], ...]  # (rule_id, tax class, regex)
    exclusions: tuple[tuple[str, str], ...]  # (rule_id, regex): any match -> UNKNOWN


INDEX_NAME_TABLE = IndexNameTable(
    rule_set="IDX-NAME-2026-10",
    flag="TAX_CLASS_INFERRED_FROM_NAME",
    applies_to_categories=("Other Scheme - Index Funds",),
    patterns=(
        ("IDX-EQ-NIFTY50", MfTaxClass.EQUITY_ORIENTED, r"\bnifty ?50\b"),
        ("IDX-EQ-NIFTY-NEXT50", MfTaxClass.EQUITY_ORIENTED, r"\bnifty next ?50\b"),
        ("IDX-EQ-NIFTY-BROAD", MfTaxClass.EQUITY_ORIENTED, r"\bnifty ?(?:100|200|500)\b"),
        ("IDX-EQ-NIFTY-TOTAL-MARKET", MfTaxClass.EQUITY_ORIENTED, r"\bnifty total market\b"),
        ("IDX-EQ-MIDCAP", MfTaxClass.EQUITY_ORIENTED, r"mid ?cap"),
        ("IDX-EQ-SMALLCAP", MfTaxClass.EQUITY_ORIENTED, r"small ?cap"),
        ("IDX-EQ-SENSEX", MfTaxClass.EQUITY_ORIENTED, r"\bsensex\b"),
        ("IDX-DEBT-GILT", MfTaxClass.SPECIFIED_DEBT, r"\bgilt\b"),
        ("IDX-DEBT-GSEC", MfTaxClass.SPECIFIED_DEBT, r"\bg ?sec\b"),
        ("IDX-DEBT-SDL", MfTaxClass.SPECIFIED_DEBT, r"\bsdl\b|\bstate development loans?\b"),
        ("IDX-DEBT-BHARAT-BOND", MfTaxClass.SPECIFIED_DEBT, r"\bbharat bond\b"),
        ("IDX-DEBT-CRISIL-IBX", MfTaxClass.SPECIFIED_DEBT, r"\bcrisil ?ibx\b"),
    ),
    exclusions=(
        (
            "IDX-X-OVERSEAS",
            r"\b(?:nasdaq|s ?& ?p ?500|hang seng|nyse|fang|msci|global|international|overseas|world|us|usa|china|japan"
            r"|taiwan|europe|emerging)\b",
        ),
        ("IDX-X-COMMODITY", r"\b(?:gold|silver|commodit(?:y|ies))\b"),
        ("IDX-X-FOF", r"\b(?:fund of funds?|fof)\b"),
        ("IDX-X-MULTI-ASSET", r"\b(?:multi asset|hybrid|balanced|equity savings|arbitrage)\b"),
    ),
)
_EQUITY_INDEX_LABEL = re.compile(r"^index funds? ?- ?equity\b")


@dataclass(frozen=True)
class MfTaxClassification:
    """A tax class with how it was reached. ``flag`` is None exactly when the class is UNKNOWN."""

    tax_class: MfTaxClass
    flag: str | None  # TAX_CLASS_INFERRED_FROM_CATEGORY | TAX_CLASS_INFERRED_FROM_NAME | None
    rule_id: str | None = None  # matched name rule(s) joined by "+", or the exclusion that forced UNKNOWN
    basis: str = ""  # one sentence for the evidence trail


def _norm_label(text: str) -> str:
    return " ".join(text.casefold().split())


def _norm_name(name: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9&]+", " ", name.casefold()).split())


def _tax_class_from_category_text(category: str) -> MfTaxClass:
    c = _norm_label(category)
    if "fund of funds" in c or "fof" in c or "overseas" in c or "international" in c or "gold" in c:
        return MfTaxClass.UNKNOWN
    if _EQUITY_INDEX_LABEL.match(c):
        # AMFI "Index Funds - Equity Funds": the label itself says equity; an index fund holds >= 95 % in its index.
        return MfTaxClass.EQUITY_ORIENTED
    if any(k in c for k in ("solution oriented", "children", "retirement", "other scheme")):
        # e.g. "Other Scheme - Index Funds" holds both equity AND debt index funds: the category alone cannot tell.
        return MfTaxClass.UNKNOWN
    if "arbitrage" in c or c.startswith("equity scheme") or "elss" in c:
        return MfTaxClass.EQUITY_ORIENTED
    if c.startswith("debt scheme") or "income/debt" in c or "liquid" in c or "overnight" in c or "money market" in c:
        return MfTaxClass.SPECIFIED_DEBT
    return MfTaxClass.UNKNOWN


def _first_exclusion(normalised_name: str, table: IndexNameTable) -> str | None:
    for rule_id, rx in table.exclusions:
        if re.search(rx, normalised_name):
            return rule_id
    return None


def mf_tax_classification(
    category: str, *, name: str | None = None, table: IndexNameTable = INDEX_NAME_TABLE
) -> MfTaxClassification:
    """Tax class from the SEBI/AMFI category, else from a cited index-name pattern (documented inference, flagged).

    1. The category decides whenever it can (flag TAX_CLASS_INFERRED_FROM_CATEGORY). For "Index Funds - Equity Funds"
       a supplied name can only demote the answer to UNKNOWN (an overseas/commodity/FoF/multi-asset name), never
       change the class.
    2. Only for the categories listed in the table, and only when a name is supplied: an exclusion match, a match
       of both equity and debt patterns, or no match at all gives UNKNOWN. Exactly one class gives that class with
       flag TAX_CLASS_INFERRED_FROM_NAME and the matched rule_id(s). Nothing is guessed.
    """
    by_category = _tax_class_from_category_text(category)
    norm = _norm_name(name) if name else ""
    if by_category is not MfTaxClass.UNKNOWN:
        if norm and _EQUITY_INDEX_LABEL.match(_norm_label(category)):
            excluded = _first_exclusion(norm, table)
            if excluded is not None:
                return MfTaxClassification(MfTaxClass.UNKNOWN, None, excluded, f"name matches exclusion {excluded}")
        return MfTaxClassification(
            by_category, "TAX_CLASS_INFERRED_FROM_CATEGORY", None, f"Tax class inferred from SEBI category '{category}'"
        )
    if not norm or _norm_label(category) not in {_norm_label(c) for c in table.applies_to_categories}:
        return MfTaxClassification(MfTaxClass.UNKNOWN, None)
    excluded = _first_exclusion(norm, table)
    if excluded is not None:
        return MfTaxClassification(MfTaxClass.UNKNOWN, None, excluded, f"name matches exclusion {excluded}")
    hits = [(rule_id, cls) for rule_id, cls, rx in table.patterns if re.search(rx, norm)]
    classes = {cls for _, cls in hits}
    if len(classes) != 1:
        return MfTaxClassification(MfTaxClass.UNKNOWN, None)
    rule_ids = "+".join(rule_id for rule_id, _ in hits)
    (cls,) = classes
    return MfTaxClassification(
        cls,
        table.flag,
        rule_ids,
        f"Tax class inferred from the scheme name: index-name rule {rule_ids} ({table.rule_set}, "
        f"rules/index_name_patterns.yaml) under category '{category}'",
    )


def mf_tax_class_from_category(category: str, *, name: str | None = None) -> MfTaxClass:
    """Infer the tax class from the SEBI category text, and from the scheme name where the table allows it."""
    return mf_tax_classification(category, name=name).tax_class


def mf_lock_in_days(category: str, name: str = "") -> int:
    """Statutory/regulatory lock-ins (ELSS 3 years; solution-oriented 5 years).

    Checks the scheme NAME too: live AMFI data (2026-10-15) files some ELSS index funds under
    "Index Funds - Equity Funds", with "ELSS" / "Tax Saver" only in the name. A false positive merely excludes.
    """
    c = category.lower()
    n = name.lower()
    if "elss" in c or "elss" in n or "tax saver" in n or "tax saving" in n:
        return 3 * 365
    if any(k in c for k in ("solution oriented", "children", "retirement")):
        # SEBI: solution-oriented schemes lock in for 5 years (or until retirement / the child's majority).
        # AMFI's NAVAll labels these "Children's Fund" / "Retirement Fund" without the SEBI prefix.
        return 5 * 365
    return 0


def is_close_ended(category: str, name: str = "") -> bool:
    """Fixed Term Plans (FMPs) and interval schemes are close-ended / periodically redeemable (live AMFI categories)."""
    text = f"{category} {name}".lower()
    return any(
        k in text for k in ("fixed term plan", "fixed maturity plan", "interval fund", "close ended", "close-ended")
    )


@dataclass(frozen=True)
class FundCreditFacts:
    """Credit facts from the scheme's latest factsheet (user-entered with a citation)."""

    lowest_rating: str | None  # lowest rating held, as published (long-term scale, SOVEREIGN, or a short-term rating)
    as_of: date  # the factsheet's portfolio date


def fund_has_credit_exposure(category: str, *, name: str | None = None) -> bool:
    """Debt-holding schemes (debt, liquid, money-market, overnight, gilt, and every hybrid) carry portfolio credit risk
    that a credit floor must check (red-team RT-23). Equity schemes do not. With a name, a debt index fund recognised
    by the index-name table counts as debt-holding too."""
    c = category.lower()
    if c.startswith("equity scheme") or "elss" in c:
        return False
    return mf_tax_class_from_category(category, name=name) is MfTaxClass.SPECIFIED_DEBT or c.startswith("hybrid scheme")


def fund_credit_status(
    category: str, facts: FundCreditFacts | None, as_of: date, *, name: str | None = None
) -> tuple[str | None, bool, str | None]:
    """(credit_rating for the ranking policy, credit_quality_unknown, why unknown).

    ranking_policy@1.2.0 (RT-23): a debt-holding fund is checked against the user's credit floor by the LOWEST rating
    it holds, from a factsheet no more than 45 days old. With no such factsheet — or a lowest rating that is not on the
    long-term scale (short-term ratings such as A1+ have no agreed long-term equivalent here) — its credit quality is
    unknown and it fails any floor (never assumed safe). Equity schemes are unaffected.
    """
    if not fund_has_credit_exposure(category, name=name):
        return None, False, None
    why: str
    if facts is None or facts.lowest_rating is None:
        why = "no factsheet with the lowest rating held has been entered"
    elif facts.as_of > as_of:
        why = f"the factsheet is dated {facts.as_of}, after the analysis date"
    elif (as_of - facts.as_of).days > FACTSHEET_MAX_AGE_DAYS:
        why = f"the factsheet ({facts.as_of}) is more than {FACTSHEET_MAX_AGE_DAYS} days old"
    elif facts.lowest_rating not in CREDIT_SCALE:
        why = f"the lowest rating held ({facts.lowest_rating}) is not on the long-term rating scale"
    else:
        return facts.lowest_rating, False, None
    if "credit risk" in category.lower():
        # SEBI: a Credit Risk Fund must hold ≥ 65 % in instruments rated AA and below — it fails any floor as UNRATED.
        return "UNRATED", False, None
    return None, True, why


def mf_tier_from_category(category: str) -> Tier:
    c = category.lower()
    if any(k in c for k in ("overnight", "liquid", "money market")):
        return Tier.T3
    return Tier.T4


def sebi_default_exit_load(category: str) -> ExitLoadSpec | None:
    """Loads fixed by regulation (not by the AMC): liquid funds' graded load applies to redemptions within 6 days
    (max 0.0070 % = 0.000070 on day 1 — the conservative bound is used); overnight funds carry none."""
    c = category.lower()
    if "overnight" in c:
        return ExitLoadSpec(days=0, rate=ZERO, citation="SEBI categorisation: overnight funds carry no exit load")
    if "liquid" in c:
        return ExitLoadSpec(
            days=6, rate=D("0.000070"), citation="SEBI graded exit load for liquid funds (day 1–6, max 0.0070 %)"
        )
    return None


def _nav_on_or_before(dates: Sequence[date], navs: Sequence[Decimal], target: date, start_idx: int) -> int | None:
    """Index of the last NAV on or before `target` (searching forward from start_idx), within the staleness bound."""
    lo, hi = start_idx, len(dates) - 1
    if dates[hi] < target:
        return None
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if dates[mid] <= target:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None or (target - dates[best]).days > MAX_NAV_STALENESS_DAYS:
        return None
    return best


def horizon_window_returns(dates: Sequence[date], navs: Sequence[Decimal], horizon_days: int) -> list[Decimal]:
    """All overlapping calendar-day windows: R = NAV(t + H, last on/before) / NAV(t) − 1 (no look-ahead)."""
    return [r for _, r in _horizon_windows(dates, navs, horizon_days)]


def independent_window_count(starts: Sequence[date], horizon_days: int) -> int:
    """Non-overlapping evidence actually present: the number of distinct H-day buckets that contain a window start.

    For a gap-free series this equals span // H. Gaps reduce it, so a history with holes (or one ancient NAV before a
    short recent run) cannot claim independent windows it does not have.
    """
    if not starts:
        return 0
    return len({(s - starts[0]).days // horizon_days for s in starts})


def _horizon_windows(dates: Sequence[date], navs: Sequence[Decimal], horizon_days: int) -> list[tuple[date, Decimal]]:
    if len(dates) != len(navs):
        raise InvalidInput("dates and navs differ in length")
    if any(b <= a for a, b in pairwise(dates)):
        raise InvalidInput("NAV dates must be strictly increasing")
    if any(n <= 0 for n in navs):
        raise InvalidInput("NAVs must be positive")
    out: list[tuple[date, Decimal]] = []
    with engine_context():
        for i, d in enumerate(dates):
            j = _nav_on_or_before(dates, navs, d + timedelta(days=horizon_days), i)
            if j is None:
                if d + timedelta(days=horizon_days) > dates[-1]:
                    break
                continue
            if j <= i:
                continue
            out.append((d, navs[j] / navs[i] - ONE))
    return out


def mf_candidate(  # noqa: PLR0915 - one linear, auditable pipeline; splitting hides the order of steps
    *,
    instrument_id: str,
    name: str,
    category: str,
    amount: Decimal,
    as_of: date,
    withdrawal: date,
    nav_dates: Sequence[date],
    navs: Sequence[Decimal],
    exit_load: ExitLoadSpec | None,
    ruleset: tx.TaxRuleSet,
    profile: tx.TaxProfile | None,
    settlement_days: int,
    credit_facts: FundCreditFacts | None = None,
) -> BuiltCandidate:
    """Empirical horizon distribution of NAV returns, scaled to the amount, after stamp duty, exit load and tax."""
    tier = mf_tier_from_category(category)
    horizon_days = (withdrawal - as_of).days
    reasons: list[str] = []
    if horizon_days <= 0:
        raise InvalidInput("withdrawal must be after as_of")
    if not nav_dates:
        return _ineligible(instrument_id, name, tier, ["INSUFFICIENT_OR_STALE_DATA: no NAV history"], amount)
    if nav_is_stale(nav_dates[-1], as_of) and nav_dates[-1] <= as_of:
        reasons.append(f"STALE_DATA: latest NAV is dated {nav_dates[-1].isoformat()}")
    if nav_dates[-1] > as_of:
        reasons.append("LOOK_AHEAD: NAV dated after the analysis date")
    lock_in = mf_lock_in_days(category, name)
    if is_close_ended(category, name):
        reasons.append("CLOSE_ENDED_OR_INTERVAL: units cannot be redeemed with the fund on demand before maturity")
    # RT-22: units are redeemed `settlement_days` before the withdrawal date so the proceeds arrive by then. The NAV
    # window, exit-load test, lock-in test and the tax transfer date all use that redemption day (conservative).
    nav_window_days = horizon_days - settlement_days
    redemption = as_of + timedelta(days=nav_window_days)
    if lock_in > horizon_days:
        reasons.append(f"HORIZON_MISMATCH: {lock_in}-day lock-in exceeds your {horizon_days}-day horizon")
    elif lock_in > nav_window_days:
        reasons.append(
            f"HORIZON_MISMATCH: {lock_in}-day lock-in ends too late for T+{settlement_days} proceeds by your date"
        )
    if horizon_days <= settlement_days:
        # Units bought on as_of can be redeemed at the earliest the next day; proceeds then settle T+settlement_days.
        reasons.append(
            f"HORIZON_MISMATCH: redemption proceeds settle T+{settlement_days}, after your {horizon_days}-day horizon"
        )
    load = exit_load if exit_load is not None else sebi_default_exit_load(category)
    if load is None:
        reasons.append("EXIT_LOAD_UNKNOWN: enter the scheme's exit load from its SID/KIM")
    classified = mf_tax_classification(category, name=name)
    tax_class = classified.tax_class
    if tax_class is MfTaxClass.UNKNOWN:
        reasons.append("TAX_CLASS_UNKNOWN: equity/debt share for tax cannot be inferred from the category or name")
    if reasons:
        return _ineligible(instrument_id, name, tier, reasons, amount)
    assert load is not None

    try:
        dated = _horizon_windows(nav_dates, navs, nav_window_days)
    except EngineError as exc:
        return _ineligible(instrument_id, name, tier, [f"{exc.code}: {exc}"], amount)
    windows = [r for _, r in dated]
    span = (nav_dates[-1] - nav_dates[0]).days
    if span < MIN_HISTORY_DAYS:
        return _ineligible(
            instrument_id, name, tier,
            [f"INSUFFICIENT_HISTORY: {span} days of NAV history (need ≥ {MIN_HISTORY_DAYS}; newly launched or not "
             "backfilled)"],
            amount,
        )  # fmt: skip
    n_ind = independent_window_count([d for d, _ in dated], nav_window_days)
    if n_ind < MIN_INDEPENDENT_WINDOWS or not windows:
        return _ineligible(
            instrument_id, name, tier,
            [f"INSUFFICIENT_HISTORY: {n_ind} independent windows of {nav_window_days} days (need ≥ "
             f"{MIN_INDEPENDENT_WINDOWS})"],
            amount,
        )  # fmt: skip

    with engine_context():
        if n_ind >= FULL_BAND_INDEPENDENT_WINDOWS:
            low_r = percentile_type7(windows, D("0.05"))
            lower_method = "5th percentile of overlapping windows"
        else:
            low_r = min(windows)
            lower_method = f"worst observed window (only {n_ind} independent windows; more conservative than q05)"
        mid_r = percentile_type7(windows, D("0.50"))
        high_r = percentile_type7(windows, D("0.95")) if n_ind >= FULL_BAND_INDEPENDENT_WINDOWS else max(windows)
        losses = sum(1 for r in windows if r < 0)
        loss_freq = Decimal(losses) / Decimal(len(windows))
        stamp = amount * D("0.00005") / D("1.00005")  # 0.005 % stamp duty on the net amount (calc-methodology §2.10)
        invested = amount - stamp
        load_applies = nav_window_days <= load.days
        load_rate = load.rate if load_applies else ZERO

        def end_value(r: Decimal) -> tuple[Decimal, Decimal]:
            gross = invested * (ONE + r)
            after_load = gross * (ONE - load_rate)
            return gross, after_load

        values = [end_value(r) for r in (low_r, mid_r, high_r)]
    equity = tax_class is MfTaxClass.EQUITY_ORIENTED
    taxes: list[Decimal] = []
    rule_ids: set[str] = set()
    unverified = False
    tax_flags: set[str] = set()
    try:
        for k, (_, after_load) in enumerate(values):
            with engine_context():
                gain = after_load - amount
            if gain <= 0:
                taxes.append(ZERO)
                continue
            t, rep, tflag = _tax_on_gain(
                gain, lot_id=f"{instrument_id}#{k}", instrument_class="MUTUAL_FUND", acquired=as_of,
                transferred=redemption, ruleset=ruleset, profile=profile,
                equity_share=D("0.65") if equity else ZERO, debt_share=ZERO if equity else ONE,
            )  # fmt: skip
            taxes.append(t)
            rule_ids.update(rep.rule_ids_used)
            unverified = unverified or rep.unverified_assumption
            if any(cl.exemption_applied_inr > 0 for cl in rep.classifications):
                # RT-18: the annual LTCG exemption is assumed unused by your other gains this year.
                tax_flags.add("LTCG_EXEMPTION_ASSUMED_UNUSED")
            if tflag is not None:
                tax_flags.add(tflag)
    except EngineError as exc:
        return _ineligible(instrument_id, name, tier, [f"{exc.code}: {exc}"], amount)
    with engine_context():
        nets = [after - t for (_, after), t in zip(values, taxes, strict=True)]
        band = OutcomeBand(q05=min(nets), q50=nets[1], q95=max(nets))
    assert classified.flag is not None
    flags = [classified.flag]
    if unverified:
        flags.append("TAX_RULE_UNVERIFIED")
    if n_ind < FULL_BAND_INDEPENDENT_WINDOWS:
        flags.append("LOW_EVIDENCE")
    flags.extend(sorted(tax_flags))
    evidence = CandidateEvidence(
        formula_id="CAND_MF_EMPIRICAL@2",
        gross_end_value=None,
        band_gross=(values[0][0], values[1][0], values[2][0]),
        tax_low=taxes[0],
        tax_mid=taxes[1],
        tax_high=taxes[2],
        tax_basis=_basis(profile),
        tax_rule_ids=tuple(sorted(rule_ids)),
        tax_unverified=unverified,
        costs=(("stamp_duty", stamp), ("exit_load_rate", load_rate)),
        n_windows=len(windows),
        n_independent=n_ind,
        lower_band_method=lower_method,
        window_span=(nav_dates[0], nav_dates[-1]),
        inputs=(
            ("amount", str(amount)),
            ("horizon_days", str(horizon_days)),
            ("nav_window_days", str(nav_window_days)),
            ("redemption_date", redemption.isoformat()),
            ("nav_observations", str(len(navs))),
            ("history", f"{nav_dates[0].isoformat()} → {nav_dates[-1].isoformat()}"),
            ("exit_load", f"{(load.rate * 100).normalize()} % if redeemed within {load.days} days ({load.citation})"),
            ("loss_windows", f"{losses} of {len(windows)}"),
        ),
        assumptions=(
            "The distribution of past windows of this length is representative (strong assumption)",
            f"Redeemed {settlement_days} day(s) before your withdrawal date so the T+{settlement_days} proceeds "
            f"arrive in time: the NAV windows are {nav_window_days} days, not {horizon_days}",
            "NAV is net of scheme expenses; no expense ratio is deducted again",
            classified.basis,
        ),
        limitations=(
            f"{len(windows)} overlapping windows contain only about {n_ind} independent observations",
            "Credit events, side-pocketing or regime changes absent from this history are not represented",
            "Scheme survivorship: merged or wound-up schemes are not in the comparison set",
        ),
    )
    credit_rating, credit_unknown, _ = fund_credit_status(category, credit_facts, as_of, name=name)
    cand = Candidate(
        instrument_id=instrument_id,
        name=name,
        tier=tier,
        outcome=band,
        loss_frequency=loss_freq,
        independent_windows=n_ind,
        days_to_cash=settlement_days,
        exit_cost=load_rate,
        horizon_fit=True,
        # Equity schemes: no credit rating applies (None). Debt-holding schemes: the lowest rating held from a current
        # factsheet, otherwise credit quality is unknown and any credit floor fails (fund_credit_status, RT-23).
        credit_rating=credit_rating,
        credit_quality_unknown=credit_unknown,
        data_ok=True,
        flags=tuple(flags),
    )
    return BuiltCandidate(cand, evidence, (), ())
