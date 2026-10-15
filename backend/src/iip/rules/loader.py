"""Thin loader for the versioned rule tables (ADR-0009).

All file I/O for rule tables lives here; ``iip.engine.tax`` only receives the parsed, frozen objects.
Validation is strict: unknown fields are rejected, every rule must carry ``source_url`` (https, or
``doc:docs/...`` where the research fetched no official URL) and a
``verification_status`` (P | S | NV), decimals must be written as strings (floats are refused), and
every Act-bearing rule must sit inside its Act's period.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, BeforeValidator, ConfigDict, ValidationError, field_validator, model_validator

from iip.engine.errors import InvalidInput
from iip.engine.money import D
from iip.engine.tax import (
    Act,
    ActPeriod,
    CessRule,
    DeductionRule,
    GainType,
    RateKind,
    RebateRule,
    Regime,
    RuleConditions,
    SlabBracket,
    SlabTable,
    SurchargeBand,
    SurchargeRule,
    TaxRule,
    TaxRuleSet,
    TransactionLevy,
    Verification,
    WithholdingRule,
)

RULES_DIR = Path(__file__).resolve().parent
TAX_RULES_PATH = RULES_DIR / "tax" / "india.yaml"
MF_CATEGORIES_PATH = RULES_DIR / "mf_categories.yaml"
SUPPORTED_SCHEMA = 1


class RuleTableError(ValueError):
    """A rule table is missing, malformed, or internally inconsistent."""


def _strict_decimal(value: Any) -> Decimal:
    if isinstance(value, float):
        raise ValueError(f"float {value!r} not allowed; write decimals as quoted strings")
    if isinstance(value, bool) or not isinstance(value, str | int | Decimal):
        raise ValueError(f"expected a decimal string, got {type(value).__name__}")
    try:
        return D(value)
    except InvalidInput as exc:
        raise ValueError(str(exc)) from exc


Dec = Annotated[Decimal, BeforeValidator(_strict_decimal)]


def _fraction(value: Decimal | None, name: str) -> None:
    if value is not None and not Decimal(0) <= value <= Decimal(1):
        raise ValueError(f"{name} must be a fraction in [0, 1], got {value}")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=False)


class _Sourced(_Strict):
    rule_id: str
    source_url: str
    verification_status: Verification
    notes: str = ""

    @field_validator("source_url")
    @classmethod
    def _https(cls, v: str) -> str:
        if not (v.startswith("https://") or v.startswith("doc:docs/")):
            raise ValueError("source_url must be an https:// URL or a doc:docs/... research reference")
        return v


class _Versioned(_Sourced):
    effective_from: date
    effective_to: date | None = None

    @model_validator(mode="after")
    def _dates(self) -> _Versioned:
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError(f"{self.rule_id}: effective_to before effective_from")
        return self


class _Statutory(_Versioned):
    act: Act
    section_1961: str | None = None
    section_2025: str | None = None


class _ActPeriodM(_Sourced):
    act: Act
    effective_from: date | None = None
    effective_to: date | None = None


class _ConditionsM(_Strict):
    acquisition_date_from: date | None = None
    acquisition_date_to: date | None = None
    listed: bool | None = None
    domestic_equity_share_min: Dec | None = None
    domestic_equity_share_max: Dec | None = None
    domestic_equity_share_below: Dec | None = None
    debt_share_above: Dec | None = None
    debt_share_max: Dec | None = None
    redemption_at_maturity: bool | None = None
    original_subscriber_held_continuously: bool | None = None

    @model_validator(mode="after")
    def _check(self) -> _ConditionsM:
        for name in (
            "domestic_equity_share_min",
            "domestic_equity_share_max",
            "domestic_equity_share_below",
            "debt_share_above",
            "debt_share_max",
        ):
            _fraction(getattr(self, name), name)
        if (
            self.acquisition_date_from is not None
            and self.acquisition_date_to is not None
            and self.acquisition_date_to < self.acquisition_date_from
        ):
            raise ValueError("acquisition_date_to before acquisition_date_from")
        return self


class _TaxRuleM(_Statutory):
    instrument_class: str
    conditions: _ConditionsM = _ConditionsM()
    holding_threshold_months: int | None
    gain_type: GainType
    rate: str | Dec
    annual_exemption_inr: Dec | None = None
    exemption_scope: str | None = None

    @field_validator("rate", mode="before")
    @classmethod
    def _rate(cls, v: Any) -> str | Decimal:
        if v in ("SLAB", "EXEMPT"):
            return str(v)
        dec = _strict_decimal(v)
        _fraction(dec, "rate")
        return dec

    @model_validator(mode="after")
    def _consistency(self) -> _TaxRuleM:
        if self.holding_threshold_months is not None and self.holding_threshold_months <= 0:
            raise ValueError(f"{self.rule_id}: holding_threshold_months must be positive")
        if self.gain_type is GainType.INCOME and self.holding_threshold_months is not None:
            raise ValueError(f"{self.rule_id}: INCOME rules have no holding threshold")
        if self.gain_type is GainType.INCOME and self.rate == "EXEMPT":
            raise ValueError(f"{self.rule_id}: EXEMPT applies to capital gains only")
        if (self.annual_exemption_inr is None) != (self.exemption_scope is None):
            raise ValueError(f"{self.rule_id}: annual_exemption_inr and exemption_scope go together")
        if self.annual_exemption_inr is not None and self.annual_exemption_inr < 0:
            raise ValueError(f"{self.rule_id}: annual exemption must be ≥ 0")
        return self


class _BracketM(_Strict):
    lower: Dec
    upper: Dec | None = None
    rate: Dec


class _SlabTableM(_Statutory):
    regime: Regime
    brackets: list[_BracketM]

    @model_validator(mode="after")
    def _contiguous(self) -> _SlabTableM:
        if not self.brackets or self.brackets[0].lower != 0:
            raise ValueError(f"{self.rule_id}: brackets must start at 0")
        for prev, nxt in pairwise(self.brackets):
            if prev.upper is None or prev.upper != nxt.lower:
                raise ValueError(f"{self.rule_id}: brackets must be contiguous")
        if self.brackets[-1].upper is not None:
            raise ValueError(f"{self.rule_id}: last bracket must be open-ended")
        for b in self.brackets:
            _fraction(b.rate, "bracket rate")
        return self


class _BandM(_Strict):
    above_inr: Dec
    rate: Dec


class _SurchargeM(_Statutory):
    regime: Regime
    bands: list[_BandM]
    special_rate_cap: Dec
    capped_sections: list[str]

    @model_validator(mode="after")
    def _ascending(self) -> _SurchargeM:
        thresholds = [b.above_inr for b in self.bands]
        if thresholds != sorted(thresholds) or len(set(thresholds)) != len(thresholds):
            raise ValueError(f"{self.rule_id}: bands must be strictly ascending")
        for b in self.bands:
            _fraction(b.rate, "surcharge rate")
        _fraction(self.special_rate_cap, "special_rate_cap")
        return self


class _CessM(_Statutory):
    rate: Dec


class _RebateM(_Statutory):
    regime: Regime
    max_rebate_inr: Dec
    total_income_ceiling_inr: Dec
    excluded_sections: list[str]


class _WithholdingM(_Statutory):
    payer_scope: str
    rate: Dec
    threshold_inr: Dec
    threshold_senior_inr: Dec | None = None


class _DeductionM(_Statutory):
    item: str
    allowed: bool


class _LevyM(_Versioned):
    statute: str
    applies_to: str
    base: str
    payer: str
    rate: Dec


class _TaxFileM(_Strict):
    schema_version: Literal[1]
    table_version: str
    jurisdiction: Literal["IN"]
    snapshot_date: date
    coverage_to: date
    acts: list[_ActPeriodM]
    rules: list[_TaxRuleM]
    slab_tables: list[_SlabTableM]
    surcharges: list[_SurchargeM]
    cess: list[_CessM]
    rebates: list[_RebateM]
    withholding: list[_WithholdingM]
    deductions: list[_DeductionM]
    levies: list[_LevyM]


def _meta(m: _Versioned) -> dict[str, Any]:
    return {
        "rule_id": m.rule_id,
        "effective_from": m.effective_from,
        "effective_to": m.effective_to,
        "source_url": m.source_url,
        "verification_status": m.verification_status,
        "notes": m.notes.strip(),
    }


def _stat(m: _Statutory) -> dict[str, Any]:
    return {**_meta(m), "act": m.act, "section_1961": m.section_1961, "section_2025": m.section_2025}


def _rule(m: _TaxRuleM) -> TaxRule:
    if isinstance(m.rate, Decimal):
        kind, rate = RateKind.SPECIAL, m.rate
    else:
        kind, rate = RateKind(m.rate), None
    return TaxRule(
        **_stat(m),
        instrument_class=m.instrument_class,
        conditions=RuleConditions(**m.conditions.model_dump()),
        holding_threshold_months=m.holding_threshold_months,
        gain_type=m.gain_type,
        rate_kind=kind,
        rate=rate,
        annual_exemption_inr=m.annual_exemption_inr,
        exemption_scope=m.exemption_scope,
    )


def _check_cross(ruleset: TaxRuleSet) -> None:
    ids = ruleset.all_rule_ids()
    dups = sorted({i for i in ids if ids.count(i) > 1})
    if dups:
        raise RuleTableError(f"duplicate rule_id(s): {dups}")
    if ruleset.coverage_to < ruleset.snapshot_date:
        raise RuleTableError("coverage_to precedes snapshot_date")
    periods = {a.act: a for a in ruleset.acts}
    if len(periods) != len(ruleset.acts):
        raise RuleTableError("one period per act expected")
    statutory = [
        *ruleset.rules,
        *ruleset.slab_tables,
        *ruleset.surcharges,
        *ruleset.cess,
        *ruleset.rebates,
        *ruleset.withholding,
        *ruleset.deductions,
    ]
    for r in statutory:
        period = periods.get(r.act)
        if period is None:
            raise RuleTableError(f"{r.rule_id}: no period for act {r.act}")
        starts_ok = period.effective_from is None or r.effective_from >= period.effective_from
        ends_ok = period.effective_to is None or (r.effective_to is not None and r.effective_to <= period.effective_to)
        if not (starts_ok and ends_ok):
            raise RuleTableError(f"{r.rule_id}: effective dates fall outside its act period ({r.act})")


def parse_tax_rules(data: Mapping[str, Any]) -> TaxRuleSet:
    """Validate a parsed YAML mapping and build the engine's frozen rule objects."""
    try:
        f = _TaxFileM.model_validate(dict(data))
    except ValidationError as exc:
        raise RuleTableError(str(exc)) from exc
    ruleset = TaxRuleSet(
        schema_version=f.schema_version,
        table_version=f.table_version,
        jurisdiction=f.jurisdiction,
        snapshot_date=f.snapshot_date,
        coverage_to=f.coverage_to,
        acts=tuple(
            ActPeriod(
                rule_id=a.rule_id,
                act=a.act,
                effective_from=a.effective_from,
                effective_to=a.effective_to,
                source_url=a.source_url,
                verification_status=a.verification_status,
                notes=a.notes.strip(),
            )
            for a in f.acts
        ),
        rules=tuple(_rule(r) for r in f.rules),
        slab_tables=tuple(
            SlabTable(
                **_stat(t),
                regime=t.regime,
                brackets=tuple(SlabBracket(lower=b.lower, upper=b.upper, rate=b.rate) for b in t.brackets),
            )
            for t in f.slab_tables
        ),
        surcharges=tuple(
            SurchargeRule(
                **_stat(s),
                regime=s.regime,
                bands=tuple(SurchargeBand(above_inr=b.above_inr, rate=b.rate) for b in s.bands),
                special_rate_cap=s.special_rate_cap,
                capped_sections=tuple(s.capped_sections),
            )
            for s in f.surcharges
        ),
        cess=tuple(CessRule(**_stat(c), rate=c.rate) for c in f.cess),
        rebates=tuple(
            RebateRule(
                **_stat(r),
                regime=r.regime,
                max_rebate_inr=r.max_rebate_inr,
                total_income_ceiling_inr=r.total_income_ceiling_inr,
                excluded_sections=tuple(r.excluded_sections),
            )
            for r in f.rebates
        ),
        withholding=tuple(
            WithholdingRule(
                **_stat(w),
                payer_scope=w.payer_scope,
                rate=w.rate,
                threshold_inr=w.threshold_inr,
                threshold_senior_inr=w.threshold_senior_inr,
            )
            for w in f.withholding
        ),
        deductions=tuple(DeductionRule(**_stat(d), item=d.item, allowed=d.allowed) for d in f.deductions),
        levies=tuple(
            TransactionLevy(
                **_meta(lv), statute=lv.statute, applies_to=lv.applies_to, base=lv.base, payer=lv.payer, rate=lv.rate
            )
            for lv in f.levies
        ),
    )
    _check_cross(ruleset)
    return ruleset


def _read_yaml(path: Path) -> Mapping[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuleTableError(f"cannot read rule table {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RuleTableError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuleTableError(f"{path}: top level must be a mapping")
    return data


def load_tax_rules(path: Path | None = None) -> TaxRuleSet:
    return parse_tax_rules(_read_yaml(path or TAX_RULES_PATH))


# --- MF categories and expense regime -----------------------------------------------------------


def _category_key(name: str) -> str:
    """Case/space-insensitive key that ignores a trailing "Fund" ("Low Duration" == "Low Duration Fund")."""
    key = " ".join(name.split()).casefold()
    return key.removesuffix(" fund")


@dataclass(frozen=True, kw_only=True)
class CategoryRename:
    rule_id: str
    circular: str
    effective_from: date
    compliance_window_months: int
    source_url: str
    verification_status: Verification
    mappings: tuple[tuple[str, str], ...]  # (legacy name, current name)
    notes: str = ""


@dataclass(frozen=True, kw_only=True)
class ExpenseRegime:
    rule_id: str
    kind: Literal["TER", "BER"]
    effective_from: date | None
    effective_to: date | None
    regulation: str
    source_url: str
    verification_status: Verification
    notes: str = ""

    def covers(self, on: date) -> bool:
        return (self.effective_from is None or self.effective_from <= on) and (
            self.effective_to is None or on <= self.effective_to
        )


@dataclass(frozen=True, kw_only=True)
class MfCategoryTable:
    schema_version: int
    rename: CategoryRename
    expense_regimes: tuple[ExpenseRegime, ...]

    def canonical_category(self, name: str) -> str:
        """Map a legacy (2017) SEBI category name to its 26-Feb-2026 name; unchanged names pass through."""
        key = _category_key(name)
        for legacy, current in self.rename.mappings:
            if _category_key(legacy) == key:
                return current
        return " ".join(name.split())

    def expense_ratio_kind(self, on: date) -> Literal["TER", "BER"]:
        hits = [r for r in self.expense_regimes if r.covers(on)]
        if len(hits) != 1:
            raise RuleTableError(f"expected exactly one expense regime on {on}, found {len(hits)}")
        return hits[0].kind


class _MappingM(_Strict):
    legacy: str
    current: str


class _RenameM(_Sourced):
    circular: str
    effective_from: date
    compliance_window_months: int
    mappings: list[_MappingM]


class _ExpenseM(_Sourced):
    kind: Literal["TER", "BER"]
    effective_from: date | None = None
    effective_to: date | None = None
    regulation: str


class _MfFileM(_Strict):
    schema_version: Literal[1]
    rename: _RenameM
    expense_regimes: list[_ExpenseM]


def parse_mf_categories(data: Mapping[str, Any]) -> MfCategoryTable:
    try:
        f = _MfFileM.model_validate(dict(data))
    except ValidationError as exc:
        raise RuleTableError(str(exc)) from exc
    legacy = [_category_key(m.legacy) for m in f.rename.mappings]
    if len(set(legacy)) != len(legacy):
        raise RuleTableError("duplicate legacy category name")
    table = MfCategoryTable(
        schema_version=f.schema_version,
        rename=CategoryRename(
            rule_id=f.rename.rule_id,
            circular=f.rename.circular,
            effective_from=f.rename.effective_from,
            compliance_window_months=f.rename.compliance_window_months,
            source_url=f.rename.source_url,
            verification_status=f.rename.verification_status,
            mappings=tuple((m.legacy, m.current) for m in f.rename.mappings),
            notes=f.rename.notes.strip(),
        ),
        expense_regimes=tuple(
            ExpenseRegime(
                rule_id=e.rule_id,
                kind=e.kind,
                effective_from=e.effective_from,
                effective_to=e.effective_to,
                regulation=e.regulation,
                source_url=e.source_url,
                verification_status=e.verification_status,
                notes=e.notes.strip(),
            )
            for e in f.expense_regimes
        ),
    )
    regimes = sorted(table.expense_regimes, key=lambda e: e.effective_from or date.min)
    for prev, nxt in pairwise(regimes):
        if prev.effective_to is None or nxt.effective_from is None or prev.effective_to >= nxt.effective_from:
            raise RuleTableError("expense regimes overlap or are open-ended before a later regime")
    return table


def load_mf_categories(path: Path | None = None) -> MfCategoryTable:
    return parse_mf_categories(_read_yaml(path or MF_CATEGORIES_PATH))
