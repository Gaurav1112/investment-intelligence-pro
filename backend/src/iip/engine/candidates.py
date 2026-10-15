"""Build ranking candidates from instrument facts (pure; ADR-0005 Step 2: horizon-matched ₹ outcome bands).

Every candidate is evaluated for the SAME amount and the SAME withdrawal date, after costs and assumed tax.
Anything that cannot be established from supplied facts makes the candidate ineligible with a reason —
it is never filled with a default (requirements.md §3.6a).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise

from iip.engine import tax as tx
from iip.engine.deposits import fd_maturity
from iip.engine.errors import EngineError, InvalidInput
from iip.engine.feasibility import percentile_type7
from iip.engine.fixed_income import tbill_days, tbill_price
from iip.engine.freshness import nav_is_stale
from iip.engine.money import ONE, ZERO, D, engine_context
from iip.engine.ranking import Candidate, OutcomeBand, Tier

ENGINE_VERSION = "candidates@1.0.0"
MIN_INDEPENDENT_WINDOWS = 10  # validation-methodology §8: below this the empirical distribution is refused
FULL_BAND_INDEPENDENT_WINDOWS = 20  # q05/q95 need ≥ 20 independent windows; otherwise worst observed window
MAX_NAV_STALENESS_DAYS = 7  # calculation-methodology §0: last price on or before t within 7 calendar days
MIN_HISTORY_DAYS = 365  # validation-methodology §8: newly launched (< 1 year of history) → suppressed


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
    financial-year end, the transfer date is clamped to the coverage end and the result is FLAGGED. Clamping can only
    shorten the holding period, which never yields a more favourable classification (LTCG → STCG at worst), so tax is
    never understated by the assumption.
    """
    flag: str | None = None
    if transferred > ruleset.coverage_to:
        flag = f"TAX_RULES_ASSUMED_UNCHANGED_AFTER_{ruleset.coverage_to.isoformat()}"
        transferred = ruleset.coverage_to
        acquired = min(acquired, transferred)
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
    report = tx.compute_tax([disposal], ruleset, use)
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
    """Buy at the quoted money-market yield, hold to maturity, keep the cash until the withdrawal date (0 %)."""
    if maturity > withdrawal:
        return _ineligible(
            instrument_id, name, Tier.T1, ["HORIZON_MISMATCH: matures after your withdrawal date"], amount
        )
    try:
        days = tbill_days(settlement, maturity)
        priced = tbill_price(quoted_yield, days)
        with engine_context():
            face = amount * D(100) / priced.price
            gain = face - amount
        tax_amt, report, tax_flag = _tax_on_gain(
            gain, lot_id=instrument_id, instrument_class="TBILL", acquired=settlement, transferred=maturity,
            ruleset=ruleset, profile=profile,
        )  # fmt: skip
    except EngineError as exc:
        return _ineligible(instrument_id, name, Tier.T1, [f"{exc.code}: {exc}"], amount)
    with engine_context():
        net = face - tax_amt
    evidence = CandidateEvidence(
        formula_id="CAND_TBILL@1",
        gross_end_value=face,
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
        ),
        assumptions=(
            "Held to maturity; face value repaid by the Government of India on the maturity date",
            "Cash from maturity to your withdrawal date earns nothing (conservative)",
            "Fractional face value — T-bill lot sizes and bid/ask spreads are not modelled",
        ),
        limitations=(
            "The quoted yield is the one you entered with its citation; the price you obtain may differ",
            "Selling before maturity exposes you to price risk (not modelled for this candidate)",
        ),
    )
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
        flags=tuple(
            f for f in ("TAX_RULE_UNVERIFIED" if report.unverified_assumption else None, tax_flag) if f is not None
        ),
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
    other_deposits_same_bank: Decimal,
    ruleset: tx.TaxRuleSet,
    profile: tx.TaxProfile | None,
    short_tenure_cutoff_months: int = 6,
    sovereign_backed: bool = False,
) -> BuiltCandidate:
    """Cumulative deposit held to maturity. ``sovereign_backed`` = a Post Office Time Deposit (Government of India
    obligation, not DICGC-insured): contractual sovereign credit, so T1 rather than uninsured bank credit."""
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
        exposure = other_deposits_same_bank + res.maturity_amount
        fully_insured = dicgc_eligible and exposure <= DICGC_LIMIT
        credit_safe = sovereign_backed or fully_insured
        net = res.maturity_amount - tax_amt
    flags: list[str] = []
    if sovereign_backed:
        flags.append("SOVEREIGN_BACKED_NOT_DICGC")
    elif not dicgc_eligible:
        flags.append("NOT_DICGC_INSURED")
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
            ("dicgc_exposure_at_bank", str(exposure)),
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


def mf_tax_class_from_category(category: str) -> MfTaxClass:
    """Infer the tax class from the SEBI category text (documented inference, flagged on every result)."""
    c = category.lower()
    if "fund of funds" in c or "fof" in c or "overseas" in c or "international" in c or "gold" in c:
        return MfTaxClass.UNKNOWN
    if any(k in c for k in ("solution oriented", "children", "retirement", "other scheme")):
        # e.g. "Other Scheme - Index Funds" holds both equity AND debt index funds: cannot be inferred.
        return MfTaxClass.UNKNOWN
    if "arbitrage" in c or c.startswith("equity scheme") or "elss" in c:
        return MfTaxClass.EQUITY_ORIENTED
    if c.startswith("debt scheme") or "income/debt" in c or "liquid" in c or "overnight" in c or "money market" in c:
        return MfTaxClass.SPECIFIED_DEBT
    return MfTaxClass.UNKNOWN


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
    if lock_in > horizon_days:
        reasons.append(f"HORIZON_MISMATCH: {lock_in}-day lock-in exceeds your {horizon_days}-day horizon")
    if horizon_days <= settlement_days:
        # Units bought on as_of can be redeemed at the earliest the next day; proceeds then settle T+settlement_days.
        reasons.append(
            f"HORIZON_MISMATCH: redemption proceeds settle T+{settlement_days}, after your {horizon_days}-day horizon"
        )
    load = exit_load if exit_load is not None else sebi_default_exit_load(category)
    if load is None:
        reasons.append("EXIT_LOAD_UNKNOWN: enter the scheme's exit load from its SID/KIM")
    tax_class = mf_tax_class_from_category(category)
    if tax_class is MfTaxClass.UNKNOWN:
        reasons.append("TAX_CLASS_UNKNOWN: equity/debt share for tax cannot be inferred from the category")
    if reasons:
        return _ineligible(instrument_id, name, tier, reasons, amount)
    assert load is not None

    try:
        dated = _horizon_windows(nav_dates, navs, horizon_days)
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
    n_ind = independent_window_count([d for d, _ in dated], horizon_days)
    if n_ind < MIN_INDEPENDENT_WINDOWS or not windows:
        return _ineligible(
            instrument_id, name, tier,
            [f"INSUFFICIENT_HISTORY: {n_ind} independent windows of {horizon_days} days (need ≥ "
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
        load_applies = horizon_days <= load.days
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
                transferred=withdrawal, ruleset=ruleset, profile=profile,
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
    flags = ["TAX_CLASS_INFERRED_FROM_CATEGORY"]
    if unverified:
        flags.append("TAX_RULE_UNVERIFIED")
    if n_ind < FULL_BAND_INDEPENDENT_WINDOWS:
        flags.append("LOW_EVIDENCE")
    flags.extend(sorted(tax_flags))
    evidence = CandidateEvidence(
        formula_id="CAND_MF_EMPIRICAL@1",
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
            ("nav_observations", str(len(navs))),
            ("history", f"{nav_dates[0].isoformat()} → {nav_dates[-1].isoformat()}"),
            ("exit_load", f"{(load.rate * 100).normalize()} % if redeemed within {load.days} days ({load.citation})"),
            ("loss_windows", f"{losses} of {len(windows)}"),
        ),
        assumptions=(
            "The distribution of past windows of this length is representative (strong assumption)",
            "NAV is net of scheme expenses; no expense ratio is deducted again",
            f"Tax class inferred from SEBI category '{category}'",
        ),
        limitations=(
            f"{len(windows)} overlapping windows contain only about {n_ind} independent observations",
            "Credit events, side-pocketing or regime changes absent from this history are not represented",
            "Scheme survivorship: merged or wound-up schemes are not in the comparison set",
        ),
    )
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
        # A fund has no single rating (None = n/a), except where SEBI's category mandates mostly sub-AA paper: a Credit
        # Risk Fund must invest ≥ 65 % in instruments rated AA and below, so it fails any credit floor the user sets.
        credit_rating="UNRATED" if "credit risk" in category.lower() else None,
        data_ok=True,
        flags=tuple(flags),
    )
    return BuiltCandidate(cand, evidence, (), ())
