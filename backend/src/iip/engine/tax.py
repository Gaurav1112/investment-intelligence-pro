"""Versioned Indian tax rules applied to realised gains and income (ADR-0009, calculation-methodology.md §2.12).

Tax logic is data: ``rules/tax/india.yaml`` is parsed by ``iip.rules.loader`` into the frozen objects below,
and this module only applies them.  It reads no files and no clock.

Scope (indian-instruments-and-tax.md §10): resident individuals under the **new regime** only.  Anything
else abstains with ``RuleNotFound``.

Conventions:
* Rules are selected by the **transfer (income) date**; acquisition date and instrument facts are conditions.
  Zero matches → ``RuleNotFound``; more than one → ``AmbiguousRule``.  The engine never guesses.
* Holding period: long-term only if the transfer date is *after* acquisition + N calendar months (EDATE,
  month-end clamped).  Exactly N months is short-term ("not more than N months").
* One call covers one financial year, so the annual LTCG exemption is applied once to the aggregate pool.
* Not modelled (conservative — each overstates or leaves tax unchanged, never understates):
  loss set-off, the s.87A/s.156 rebate, surcharge marginal relief, s.112A grandfathering (abstains).
* Any rule with status NV marks the whole result ``unverified_assumption=True``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from iip.engine.dates import add_months
from iip.engine.errors import AmbiguousRule, InvalidInput, MissingData, RuleNotFound
from iip.engine.money import ONE, ZERO, engine_context, money

FORMULA_ID = "TAX-IN@1"
LEVY_FORMULA_ID = "LEVY-IN@1"

# s.112A grandfathering applies to equity acquired "on or before" 31-Jan-2018 (hidden-gems.md: `<=`).
# The FMV-based cost rule is not in the research rule table, so such lots abstain (see select_rule).
GRANDFATHERING_FMV_DATE = date(2018, 1, 31)
GRANDFATHERING_CLASSES = frozenset({"LISTED_EQUITY_SHARE", "MUTUAL_FUND", "LISTED_EQUITY_BUYBACK"})

W_ILLUSTRATIVE = "ILLUSTRATIVE_PROFILE"
W_UNVERIFIED = "UNVERIFIED_TAX_ASSUMPTION"
W_REBATE_NOT_APPLIED = "REBATE_NOT_APPLIED"
W_SURCHARGE_MARGINAL_RELIEF = "SURCHARGE_MARGINAL_RELIEF_NOT_MODELLED"
W_LOSS_SETOFF = "LOSS_SET_OFF_NOT_MODELLED"
W_RATES_ASSUMED_UNCHANGED = "RATES_ASSUMED_UNCHANGED"  # priced under the law of an earlier date (rates_as_of)


class Act(StrEnum):
    ITA1961 = "ITA1961"
    ITA2025 = "ITA2025"


class GainType(StrEnum):
    STCG = "STCG"
    LTCG = "LTCG"
    INCOME = "INCOME"


class RateKind(StrEnum):
    SPECIAL = "SPECIAL"  # flat statutory rate (e.g. s.111A/196)
    SLAB = "SLAB"  # investor's slab rate
    EXEMPT = "EXEMPT"


class Verification(StrEnum):
    P = "P"  # VERIFIED-PRIMARY
    S = "S"  # VERIFIED-SECONDARY
    NV = "NV"  # NOT VERIFIED — results are labelled "unverified tax assumption"


class Regime(StrEnum):
    NEW = "NEW"
    OLD = "OLD"


class ResidentialStatus(StrEnum):
    RESIDENT = "RESIDENT"
    NON_RESIDENT = "NON_RESIDENT"


# --- rule objects (parsed from YAML by iip.rules.loader) ----------------------------------------


@dataclass(frozen=True, kw_only=True)
class VersionedRule:
    rule_id: str
    effective_from: date
    effective_to: date | None
    source_url: str
    verification_status: Verification
    notes: str = ""

    def covers(self, on: date) -> bool:
        return self.effective_from <= on and (self.effective_to is None or on <= self.effective_to)


@dataclass(frozen=True, kw_only=True)
class StatutoryRule(VersionedRule):
    act: Act
    section_1961: str | None
    section_2025: str | None

    @property
    def section(self) -> str | None:
        """Section number under the Act this rule belongs to."""
        return self.section_1961 if self.act is Act.ITA1961 else self.section_2025


@dataclass(frozen=True, kw_only=True)
class ActPeriod:
    rule_id: str
    act: Act
    effective_from: date | None  # None: start not recorded in the research (before every rule here)
    effective_to: date | None
    source_url: str
    verification_status: Verification
    notes: str = ""

    def covers(self, on: date) -> bool:
        return (self.effective_from is None or self.effective_from <= on) and (
            self.effective_to is None or on <= self.effective_to
        )


@dataclass(frozen=True, kw_only=True)
class RuleConditions:
    """Optional facts a disposal must satisfy.  Thresholds are fractions (0.65 = 65 %)."""

    acquisition_date_from: date | None = None
    acquisition_date_to: date | None = None
    listed: bool | None = None
    domestic_equity_share_min: Decimal | None = None  # ≥
    domestic_equity_share_max: Decimal | None = None  # ≤
    domestic_equity_share_below: Decimal | None = None  # <
    debt_share_above: Decimal | None = None  # >
    debt_share_max: Decimal | None = None  # ≤
    redemption_at_maturity: bool | None = None
    original_subscriber_held_continuously: bool | None = None

    def matches(self, rule_id: str, d: Disposal) -> bool:
        """True/False if decidable.  A fact the disposal lacks raises MissingData only when every
        condition that *can* be evaluated passes — i.e. when the outcome really depends on it."""
        missing: list[str] = []
        for attr, value, test in self._checks(d):
            if value is None:
                missing.append(attr)
            elif not test(value):
                return False
        if missing:
            raise MissingData(f"rule {rule_id} needs {sorted(set(missing))} for lot {d.lot_id}")
        return True

    def _checks(self, d: Disposal) -> list[tuple[str, Any, Callable[[Any], bool]]]:
        checks: list[tuple[str, Any, Callable[[Any], bool]]] = []
        if (lo := self.acquisition_date_from) is not None:
            checks.append(("acquisition_date", d.acquisition_date, lambda v: v >= lo))
        if (hi := self.acquisition_date_to) is not None:
            checks.append(("acquisition_date", d.acquisition_date, lambda v: v <= hi))
        if (listed := self.listed) is not None:
            checks.append(("listed", d.listed, lambda v: v is listed))
        eq = d.domestic_equity_share
        if (eq_min := self.domestic_equity_share_min) is not None:
            checks.append(("domestic_equity_share", eq, lambda v: v >= eq_min))
        if (eq_max := self.domestic_equity_share_max) is not None:
            checks.append(("domestic_equity_share", eq, lambda v: v <= eq_max))
        if (eq_below := self.domestic_equity_share_below) is not None:
            checks.append(("domestic_equity_share", eq, lambda v: v < eq_below))
        if (debt_above := self.debt_share_above) is not None:
            checks.append(("debt_share", d.debt_share, lambda v: v > debt_above))
        if (debt_max := self.debt_share_max) is not None:
            checks.append(("debt_share", d.debt_share, lambda v: v <= debt_max))
        if (mat := self.redemption_at_maturity) is not None:
            checks.append(("redemption_at_maturity", d.redemption_at_maturity, lambda v: v is mat))
        if (orig := self.original_subscriber_held_continuously) is not None:
            checks.append(
                (
                    "original_subscriber_held_continuously",
                    d.original_subscriber_held_continuously,
                    lambda v: v is orig,
                )
            )
        return checks


@dataclass(frozen=True, kw_only=True)
class TaxRule(StatutoryRule):
    """One row of the capital-gains / income table (research §8)."""

    instrument_class: str
    conditions: RuleConditions
    holding_threshold_months: int | None  # None: no holding test (deemed STCG, income, or exempt)
    gain_type: GainType
    rate_kind: RateKind
    rate: Decimal | None  # set iff rate_kind is SPECIAL
    annual_exemption_inr: Decimal | None
    exemption_scope: str | None  # gains sharing a scope share one annual exemption per FY


@dataclass(frozen=True, kw_only=True)
class SlabBracket:
    lower: Decimal
    upper: Decimal | None  # None: no upper bound
    rate: Decimal


@dataclass(frozen=True, kw_only=True)
class SlabTable(StatutoryRule):
    regime: Regime
    brackets: tuple[SlabBracket, ...]


@dataclass(frozen=True, kw_only=True)
class SurchargeBand:
    above_inr: Decimal  # applies when total income exceeds this
    rate: Decimal


@dataclass(frozen=True, kw_only=True)
class SurchargeRule(StatutoryRule):
    regime: Regime
    bands: tuple[SurchargeBand, ...]
    special_rate_cap: Decimal
    capped_sections: tuple[str, ...]  # section numbers under this rule's Act


@dataclass(frozen=True, kw_only=True)
class CessRule(StatutoryRule):
    rate: Decimal


@dataclass(frozen=True, kw_only=True)
class RebateRule(StatutoryRule):
    regime: Regime
    max_rebate_inr: Decimal
    total_income_ceiling_inr: Decimal
    excluded_sections: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class WithholdingRule(StatutoryRule):
    payer_scope: str
    rate: Decimal
    threshold_inr: Decimal
    threshold_senior_inr: Decimal | None


@dataclass(frozen=True, kw_only=True)
class DeductionRule(StatutoryRule):
    item: str
    allowed: bool


@dataclass(frozen=True, kw_only=True)
class TransactionLevy(VersionedRule):
    statute: str
    applies_to: str
    base: str
    payer: str
    rate: Decimal


@dataclass(frozen=True, kw_only=True)
class TaxRuleSet:
    schema_version: int
    jurisdiction: str
    snapshot_date: date
    coverage_to: date  # transfers after this date abstain (rates beyond it are not researched)
    acts: tuple[ActPeriod, ...]
    rules: tuple[TaxRule, ...]
    slab_tables: tuple[SlabTable, ...]
    surcharges: tuple[SurchargeRule, ...]
    cess: tuple[CessRule, ...]
    rebates: tuple[RebateRule, ...]
    withholding: tuple[WithholdingRule, ...]
    deductions: tuple[DeductionRule, ...]
    levies: tuple[TransactionLevy, ...]
    table_version: str = ""  # bumped on every value/status change (india.yaml header)

    def _all(self) -> Iterable[ActPeriod | VersionedRule]:
        yield from self.acts
        yield from self.rules
        yield from self.slab_tables
        yield from self.surcharges
        yield from self.cess
        yield from self.rebates
        yield from self.withholding
        yield from self.deductions
        yield from self.levies

    def all_rule_ids(self) -> tuple[str, ...]:
        return tuple(r.rule_id for r in self._all())

    def status_by_rule_id(self) -> dict[str, Verification]:
        return {r.rule_id: r.verification_status for r in self._all()}


# --- inputs ------------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class Disposal:
    """A realised gain (transfer) or an income receipt.  ``gain_inr`` may be negative (a loss).

    For INCOME classes (interest, T-bill discount) ``transfer_date`` is the date the income arises.
    MUTUAL_FUND disposals must carry ``domestic_equity_share`` and ``debt_share`` as disclosed for tax.
    """

    lot_id: str
    instrument_class: str
    transfer_date: date
    gain_inr: Decimal
    acquisition_date: date | None = None
    listed: bool | None = None
    domestic_equity_share: Decimal | None = None
    debt_share: Decimal | None = None
    redemption_at_maturity: bool | None = None
    original_subscriber_held_continuously: bool | None = None

    def __post_init__(self) -> None:
        if self.acquisition_date is not None and self.acquisition_date > self.transfer_date:
            raise InvalidInput(f"lot {self.lot_id}: acquisition {self.acquisition_date} after transfer")
        for name in ("domestic_equity_share", "debt_share"):
            share = getattr(self, name)
            if share is not None and not ZERO <= share <= ONE:
                raise InvalidInput(f"lot {self.lot_id}: {name} must be a fraction in [0, 1], got {share}")
        if not isinstance(self.gain_inr, Decimal) or not self.gain_inr.is_finite():
            raise InvalidInput(f"lot {self.lot_id}: gain must be a finite Decimal")


@dataclass(frozen=True, kw_only=True)
class TaxProfile:
    """The user's tax facts.  Give exactly one of ``slab_rate`` (marginal) or ``taxable_income_inr``
    (other income of the same FY, excluding these disposals).  ``surcharge_rate`` is the user's band;
    if omitted it is derived from ``taxable_income_inr`` plus the gains."""

    regime: Regime
    residential_status: ResidentialStatus
    slab_rate: Decimal | None = None
    taxable_income_inr: Decimal | None = None
    surcharge_rate: Decimal | None = None
    label: str = "user profile"


ILLUSTRATIVE_PROFILES: tuple[TaxProfile, ...] = (
    TaxProfile(
        regime=Regime.NEW,
        residential_status=ResidentialStatus.RESIDENT,
        slab_rate=Decimal("0.30"),
        surcharge_rate=ZERO,
        label="ILLUSTRATIVE: 30 % slab, no surcharge (not your profile)",
    ),
    TaxProfile(
        regime=Regime.NEW,
        residential_status=ResidentialStatus.RESIDENT,
        slab_rate=Decimal("0.20"),
        surcharge_rate=ZERO,
        label="ILLUSTRATIVE: 20 % slab, no surcharge (not your profile)",
    ),
)


# --- results -----------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class LossInfo:
    """Information only: set-off and carry-forward are not computed (research §10)."""

    amount_inr: Decimal
    capital_loss_type: GainType | None  # STCG/LTCG for capital losses; None for income-type rules
    carry_forward_eligible: bool | None  # None: not determined
    information_only: bool
    note: str


@dataclass(frozen=True, kw_only=True)
class ClassifiedDisposal:
    lot_id: str
    rule_id: str
    act: Act
    section: str | None
    gain_type: GainType
    rate_kind: RateKind
    base_rate: Decimal | None
    gain_inr: Decimal
    exemption_applied_inr: Decimal
    taxable_gain_inr: Decimal
    loss: LossInfo | None


@dataclass(frozen=True, kw_only=True)
class LotTax:
    lot_id: str
    rule_id: str
    taxable_gain_inr: Decimal
    base_tax_inr: Decimal
    surcharge_rate: Decimal
    surcharge_inr: Decimal
    cess_inr: Decimal
    total_tax_inr: Decimal


@dataclass(frozen=True, kw_only=True)
class TaxScenario:
    label: str
    illustrative: bool
    profile: TaxProfile
    surcharge_band_rate: Decimal
    lots: tuple[LotTax, ...]
    total_tax_inr: Decimal
    rule_ids_used: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class TaxReport:
    formula_id: str
    financial_year: str
    act: Act
    inputs: tuple[Disposal, ...]
    classifications: tuple[ClassifiedDisposal, ...]
    scenarios: tuple[TaxScenario, ...]
    rule_ids_used: tuple[str, ...]
    unverified_assumption: bool
    unverified_rule_ids: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class LevyResult:
    formula_id: str
    rule_id: str
    amount_inr: Decimal
    rate: Decimal
    inclusive: bool
    value_inr: Decimal
    unverified_assumption: bool


# --- helpers -----------------------------------------------------------------------------------


def financial_year_start(d: date) -> date:
    return date(d.year if d.month >= 4 else d.year - 1, 4, 1)


def financial_year_label(d: date) -> str:
    start = financial_year_start(d).year
    return f"{start}-{(start + 1) % 100:02d}"


def act_on(acts: Sequence[ActPeriod], on: date) -> Act:
    hits = [a for a in acts if a.covers(on)]
    if not hits:
        raise RuleNotFound(f"no Income-tax Act period covers {on}")
    if len(hits) > 1:
        raise AmbiguousRule(f"several Act periods cover {on}: {[a.rule_id for a in hits]}")
    return hits[0].act


def select_dated[V: VersionedRule](items: Iterable[V], on: date, what: str) -> V:
    hits = [i for i in items if i.covers(on)]
    if not hits:
        raise RuleNotFound(f"no {what} rule in force on {on}")
    if len(hits) > 1:
        raise AmbiguousRule(f"several {what} rules in force on {on}: {[i.rule_id for i in hits]}")
    return hits[0]


def classify_holding(acquired: date, transferred: date, threshold_months: int) -> GainType:
    """LTCG only if held for MORE than ``threshold_months`` calendar months; exactly N months is STCG."""
    if threshold_months <= 0:
        raise InvalidInput("threshold_months must be positive")
    if transferred < acquired:
        raise InvalidInput(f"transfer {transferred} before acquisition {acquired}")
    return GainType.LTCG if transferred > add_months(acquired, threshold_months) else GainType.STCG


def select_rule(ruleset: TaxRuleSet, d: Disposal, *, rates_as_of: date | None = None) -> TaxRule:
    """The unique rule for this disposal on its transfer date, or RuleNotFound / AmbiguousRule.

    ``rates_as_of`` (RT-17): select the rule rows in force on that date instead of on the transfer date — i.e. "the
    law as it stands on ``rates_as_of``, assumed unchanged until the transfer".  Only the *rule-row selection* moves:
    the holding period is still classified from the ACTUAL acquisition and transfer dates, and acquisition-date
    conditions (debt-MF 1-Apr-2023 cut, grandfathering) still see the actual acquisition date, so no lot is moved
    across a boundary.  It must not be after the transfer date (that would apply law the transfer never saw).
    """
    on = d.transfer_date if rates_as_of is None else rates_as_of
    if rates_as_of is not None and rates_as_of > d.transfer_date:
        raise InvalidInput(f"lot {d.lot_id}: rates_as_of {rates_as_of} is after the transfer {d.transfer_date}")
    if on > ruleset.coverage_to:
        raise RuleNotFound(f"lot {d.lot_id}: transfer {on} is beyond the rule-table coverage ({ruleset.coverage_to})")
    hits: list[TaxRule] = []
    for rule in ruleset.rules:
        if rule.instrument_class != d.instrument_class or not rule.covers(on):
            continue
        if not rule.conditions.matches(rule.rule_id, d):
            continue
        if rule.holding_threshold_months is not None:
            acq = d.acquisition_date
            if acq is None:
                raise InvalidInput(f"lot {d.lot_id}: rule {rule.rule_id} needs an acquisition date")
            if classify_holding(acq, d.transfer_date, rule.holding_threshold_months) is not rule.gain_type:
                continue
        hits.append(rule)
    if len(hits) > 1:
        raise AmbiguousRule(f"lot {d.lot_id}: several rules match: {sorted(r.rule_id for r in hits)}")
    if not hits:
        if (
            d.instrument_class in GRANDFATHERING_CLASSES
            and d.acquisition_date is not None
            and d.acquisition_date <= GRANDFATHERING_FMV_DATE
        ):
            raise RuleNotFound(
                f"lot {d.lot_id}: acquired on or before 31-Jan-2018; s.112A grandfathering (FMV boundary) "
                "is not in the researched rule table — abstaining"
            )
        raise RuleNotFound(f"lot {d.lot_id}: no tax rule for {d.instrument_class} transferred {d.transfer_date}")
    return hits[0]


def slab_tax(table: SlabTable, income: Decimal) -> Decimal:
    if income < 0:
        raise InvalidInput("income must be ≥ 0")
    with engine_context():
        total = ZERO
        for b in table.brackets:
            top = income if b.upper is None else min(income, b.upper)
            if top > b.lower:
                total += (top - b.lower) * b.rate
        return total


def surcharge_band(rule: SurchargeRule, total_income: Decimal) -> Decimal:
    rate = ZERO
    for band in rule.bands:  # loader guarantees ascending thresholds
        if total_income > band.above_inr:
            rate = band.rate
    return rate


def compute_levy(levy: TransactionLevy, amount_inr: Decimal, on: date, *, inclusive: bool = False) -> LevyResult:
    """STT / stamp duty.  ``inclusive``: the amount already contains the levy (MF stamp duty, §2.10:
    duty = net × r / (1 + r), so it is charged on the amount that actually buys units)."""
    if not levy.covers(on):
        raise RuleNotFound(f"levy {levy.rule_id} not in force on {on}")
    if amount_inr < 0:
        raise InvalidInput("levy base must be ≥ 0")
    with engine_context():
        raw = amount_inr * levy.rate / (ONE + levy.rate) if inclusive else amount_inr * levy.rate
    return LevyResult(
        formula_id=LEVY_FORMULA_ID,
        rule_id=levy.rule_id,
        amount_inr=amount_inr,
        rate=levy.rate,
        inclusive=inclusive,
        value_inr=money(raw),
        unverified_assumption=levy.verification_status is Verification.NV,
    )


# --- computation -------------------------------------------------------------------------------


def _classify(
    ruleset: TaxRuleSet, disposals: Sequence[Disposal], rates_as_of: date | None = None
) -> tuple[list[ClassifiedDisposal], list[TaxRule]]:
    rules = [select_rule(ruleset, d, rates_as_of=rates_as_of) for d in disposals]
    exempt = _allocate_exemptions(disposals, rules)
    out: list[ClassifiedDisposal] = []
    with engine_context():
        for d, r, ex in zip(disposals, rules, exempt, strict=True):
            positive = max(d.gain_inr, ZERO)
            taxable = ZERO if r.rate_kind is RateKind.EXEMPT else positive - ex
            out.append(
                ClassifiedDisposal(
                    lot_id=d.lot_id,
                    rule_id=r.rule_id,
                    act=r.act,
                    section=r.section,
                    gain_type=r.gain_type,
                    rate_kind=r.rate_kind,
                    base_rate=r.rate,
                    gain_inr=d.gain_inr,
                    exemption_applied_inr=ex,
                    taxable_gain_inr=taxable,
                    loss=_loss_info(d, r),
                )
            )
    return out, rules


def _allocate_exemptions(disposals: Sequence[Disposal], rules: Sequence[TaxRule]) -> list[Decimal]:
    """One annual exemption per scope, shared by all positive gains in it (deterministic order)."""
    exempt = [ZERO] * len(disposals)
    scopes: dict[str, list[int]] = {}
    for i, r in enumerate(rules):
        if r.exemption_scope is not None and disposals[i].gain_inr > 0:
            scopes.setdefault(r.exemption_scope, []).append(i)
    with engine_context():
        for scope, idx in scopes.items():
            limits = {rules[i].annual_exemption_inr for i in idx}
            rates = {rules[i].rate for i in idx}
            if len(limits) > 1 or len(rates) > 1:
                raise AmbiguousRule(
                    f"exemption pool {scope} mixes rules with different limits/rates "
                    f"{sorted({rules[i].rule_id for i in idx})}; allocation is not specified"
                )
            remaining = limits.pop() or ZERO
            for i in sorted(idx, key=lambda k: (disposals[k].transfer_date, disposals[k].lot_id, k)):
                used = min(disposals[i].gain_inr, remaining)
                exempt[i] = used
                remaining -= used
    return exempt


def _loss_info(d: Disposal, r: TaxRule) -> LossInfo | None:
    if d.gain_inr >= 0:
        return None
    if r.gain_type is GainType.INCOME:
        return LossInfo(
            amount_inr=-d.gain_inr,
            capital_loss_type=None,
            carry_forward_eligible=None,
            information_only=True,
            note="negative amount under an income-type rule: loss treatment not determined (CA review)",
        )
    return LossInfo(
        amount_inr=-d.gain_inr,
        capital_loss_type=r.gain_type,
        carry_forward_eligible=True,
        information_only=True,
        note=(
            "capital loss: set-off and carry-forward are not modelled (8-year carry-forward under the 1961 Act; "
            "NOT VERIFIED under the 2025 Act). No tax credit is computed."
        ),
    )


def _check_profile(p: TaxProfile) -> None:
    if p.regime is not Regime.NEW or p.residential_status is not ResidentialStatus.RESIDENT:
        raise RuleNotFound("only resident individuals under the new regime are modelled (research §10)")
    if (p.slab_rate is None) == (p.taxable_income_inr is None):
        raise InvalidInput("profile needs exactly one of slab_rate or taxable_income_inr")
    if p.slab_rate is not None and not ZERO <= p.slab_rate <= ONE:
        raise InvalidInput("slab_rate must be a fraction in [0, 1]")
    if p.taxable_income_inr is not None and p.taxable_income_inr < 0:
        raise InvalidInput("taxable_income_inr must be ≥ 0")
    if p.surcharge_rate is None and p.taxable_income_inr is None:
        raise InvalidInput("surcharge band is required when taxable income is not given")
    if p.surcharge_rate is not None and not ZERO <= p.surcharge_rate <= ONE:
        raise InvalidInput("surcharge_rate must be a fraction in [0, 1]")


def _surcharge_band_for(
    ruleset: TaxRuleSet, fy_start: date, profile: TaxProfile, gross_positive: Decimal
) -> tuple[Decimal, SurchargeRule | None]:
    """The user's surcharge band, validated against the FY's table; derived from income if not given."""
    if profile.surcharge_rate is not None:
        band = profile.surcharge_rate
        if band == 0:
            return ZERO, None  # below every surcharge threshold: no table needed
        rule = select_dated(ruleset.surcharges, fy_start, "surcharge")
        if band not in {b.rate for b in rule.bands}:
            raise InvalidInput(f"surcharge band {band} is not in {rule.rule_id}")
        return band, rule
    if profile.taxable_income_inr is None:
        raise InvalidInput("surcharge band is required when taxable income is not given")
    rule = select_dated(ruleset.surcharges, fy_start, "surcharge")
    with engine_context():
        return surcharge_band(rule, profile.taxable_income_inr + gross_positive), rule


def _base_taxes(
    ruleset: TaxRuleSet, fy_start: date, classified: Sequence[ClassifiedDisposal], profile: TaxProfile, used: list[str]
) -> list[Decimal]:
    """Tax before surcharge and cess.  Slab income is stacked on the user's other income in lot order."""
    slab_table: SlabTable | None = None
    running = profile.taxable_income_inr
    out: list[Decimal] = []
    with engine_context():
        for c in classified:
            if c.rate_kind is RateKind.SPECIAL:
                if c.base_rate is None:
                    raise InvalidInput(f"rule {c.rule_id} has a special rate kind but no rate")
                out.append(c.taxable_gain_inr * c.base_rate)
            elif c.rate_kind is RateKind.EXEMPT:
                out.append(ZERO)
            elif profile.slab_rate is not None:
                out.append(c.taxable_gain_inr * profile.slab_rate)
            else:
                if running is None:
                    raise InvalidInput("profile needs exactly one of slab_rate or taxable_income_inr")
                if slab_table is None:
                    slab_table = select_dated(ruleset.slab_tables, fy_start, "slab table")
                    used.append(slab_table.rule_id)
                after = running + c.taxable_gain_inr
                out.append(slab_tax(slab_table, after) - slab_tax(slab_table, running))
                running = after
    return out


def _scenario(
    ruleset: TaxRuleSet,
    fy_start: date,
    classified: Sequence[ClassifiedDisposal],
    profile: TaxProfile,
    *,
    illustrative: bool,
    warnings: list[str],
) -> TaxScenario:
    _check_profile(profile)
    used: list[str] = []
    gross_positive = sum((max(c.gain_inr, ZERO) for c in classified), ZERO)
    band, surcharge_rule = _surcharge_band_for(ruleset, fy_start, profile, gross_positive)
    if surcharge_rule is not None:
        used.append(surcharge_rule.rule_id)
    if band > 0:
        warnings.append(W_SURCHARGE_MARGINAL_RELIEF)

    base_taxes = _base_taxes(ruleset, fy_start, classified, profile, used)
    lots: list[LotTax] = []
    cess_rule: CessRule | None = None
    with engine_context():
        for c, base_tax in zip(classified, base_taxes, strict=True):
            if c.rate_kind is RateKind.SLAB and base_tax > 0:
                warnings.append(W_REBATE_NOT_APPLIED)
            s_rate = band
            if (
                surcharge_rule is not None
                and c.rate_kind is RateKind.SPECIAL
                and c.section in surcharge_rule.capped_sections
            ):
                s_rate = min(band, surcharge_rule.special_rate_cap)
            surcharge = base_tax * s_rate
            cess = ZERO
            if base_tax + surcharge > 0:
                if cess_rule is None:
                    cess_rule = select_dated(ruleset.cess, fy_start, "cess")
                    used.append(cess_rule.rule_id)
                cess = (base_tax + surcharge) * cess_rule.rate
            lots.append(
                LotTax(
                    lot_id=c.lot_id,
                    rule_id=c.rule_id,
                    taxable_gain_inr=c.taxable_gain_inr,
                    base_tax_inr=money(base_tax),
                    surcharge_rate=s_rate,
                    surcharge_inr=money(surcharge),
                    cess_inr=money(cess),
                    total_tax_inr=money(base_tax + surcharge + cess),
                )
            )
        total = sum((lot.total_tax_inr for lot in lots), ZERO)
    return TaxScenario(
        label=profile.label,
        illustrative=illustrative,
        profile=profile,
        surcharge_band_rate=band,
        lots=tuple(lots),
        total_tax_inr=money(total),
        rule_ids_used=tuple(used),
    )


def compute_tax(
    disposals: Sequence[Disposal],
    ruleset: TaxRuleSet,
    profile: TaxProfile | None,
    *,
    rates_as_of: date | None = None,
) -> TaxReport:
    """Tax on one financial year's disposals.  ``profile=None`` → labelled illustrative profiles only.

    ``rates_as_of`` (RT-17): price the disposals under the law in force on that date (rule rows, Act, slab table,
    surcharge and cess of its financial year), assumed unchanged until the actual transfer dates.  Holding periods and
    acquisition-date conditions always use the actual dates (see ``select_rule``).  The report carries
    ``W_RATES_ASSUMED_UNCHANGED`` and ``financial_year`` is the rates' year.  ``None`` (default) = the transfer date's
    own law, exactly as before.
    """
    if not disposals:
        raise InvalidInput("no disposals")
    fy_starts = {financial_year_start(d.transfer_date) for d in disposals}
    if len(fy_starts) > 1:
        raise InvalidInput("disposals span more than one financial year; call once per financial year")
    fy_start = fy_starts.pop()
    if rates_as_of is not None:
        fy_start = financial_year_start(rates_as_of)
    act = act_on(ruleset.acts, fy_start)

    classified, rules = _classify(ruleset, disposals, rates_as_of)
    for r in rules:
        if r.act is not act:
            raise RuleNotFound(f"rule {r.rule_id} belongs to {r.act}, but {fy_start} falls under {act}")

    warnings: list[str] = []
    if rates_as_of is not None:
        warnings.append(W_RATES_ASSUMED_UNCHANGED)
    if any(c.loss is not None for c in classified):
        warnings.append(W_LOSS_SETOFF)
    illustrative = profile is None
    if illustrative:
        warnings.append(W_ILLUSTRATIVE)
    profiles = ILLUSTRATIVE_PROFILES if profile is None else (profile,)
    scenarios = tuple(
        _scenario(ruleset, fy_start, classified, p, illustrative=illustrative, warnings=warnings) for p in profiles
    )

    used = list(dict.fromkeys([*(r.rule_id for r in rules), *(rid for s in scenarios for rid in s.rule_ids_used)]))
    status = ruleset.status_by_rule_id()
    unverified = tuple(rid for rid in used if status[rid] is Verification.NV)
    if unverified:
        warnings.append(W_UNVERIFIED)
    return TaxReport(
        formula_id=FORMULA_ID,
        financial_year=financial_year_label(fy_start),
        act=act,
        inputs=tuple(disposals),
        classifications=tuple(classified),
        scenarios=scenarios,
        rule_ids_used=tuple(used),
        unverified_assumption=bool(unverified),
        unverified_rule_ids=unverified,
        warnings=tuple(dict.fromkeys(warnings)),
    )
