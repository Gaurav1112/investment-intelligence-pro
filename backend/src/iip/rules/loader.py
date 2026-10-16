"""Thin loader for the versioned rule tables (ADR-0009).

All file I/O for rule tables lives here; ``iip.engine.tax`` only receives the parsed, frozen objects.
Validation is strict: unknown fields are rejected, every rule must carry ``source_url`` (https, or
``doc:docs/...`` where the research fetched no official URL) and a
``verification_status`` (P | S | NV), decimals must be written as strings (floats are refused), and
every Act-bearing rule must sit inside its Act's period.

Package A11 adds: opt-in historical tax rows (pre-FY2024-25, always NV, for backtests only), the L3 stress table
(public schema + citation pointers; index-derived values only from the user's local config, decision U-08), the L5
allocation-policy structure (targets are dated user decisions, never shipped), and the cash-market equity cost
table.  Every row of those tables must carry ``source_url``, ``verification_status`` and ``effective_from``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, field_validator, model_validator

from iip.engine.actions.cards import TemplateSet, parse_templates
from iip.engine.errors import InvalidInput
from iip.engine.money import D
from iip.engine.ranking import Objective
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
STRESS_TABLE_PATH = RULES_DIR / "risk" / "stress_drawdowns.yaml"
ALLOCATION_POLICY_PATH = RULES_DIR / "risk" / "allocation_policy.yaml"
EQUITY_COSTS_PATH = RULES_DIR / "costs" / "india_equity.yaml"
ACTION_TEMPLATES_PATH = RULES_DIR / "action_templates.yaml"
LOCAL_STRESS_FILENAME = "stress_drawdowns.local.yaml"
LOCAL_STRESS_ENV = "IIP_STRESS_DRAWDOWNS_LOCAL"  # hosted twin of the local file (U-08): YAML text, same schema
SUPPORTED_SCHEMA = 1
# Historical tax rows must close before the main table starts (FY2024-25); see india.yaml "HISTORICAL ROWS".
HISTORICAL_TAX_END = date(2024, 3, 31)


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


def _check_source_url(v: str) -> str:
    if not (v.startswith("https://") or v.startswith("doc:docs/")):
        raise ValueError("source_url must be an https:// URL or a doc:docs/... research reference")
    return v


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
        return _check_source_url(v)


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


class _HistTaxRuleM(_TaxRuleM):
    """A pre-FY2024-25 row (opt-in, backtests only): NOT VERIFIED until CA review, closed by 31-Mar-2024."""

    @model_validator(mode="after")
    def _historical(self) -> _HistTaxRuleM:
        if self.verification_status is not Verification.NV:
            raise ValueError(f"{self.rule_id}: historical rows stay NV until a CA reviews them")
        if self.effective_to is None:
            raise ValueError(f"{self.rule_id}: historical rows need an effective_to")
        if self.effective_to > HISTORICAL_TAX_END:
            raise ValueError(f"{self.rule_id}: historical rows must end on or before {HISTORICAL_TAX_END.isoformat()}")
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
    historical_table_version: str | None = None
    historical_rules: list[_HistTaxRuleM] = Field(default_factory=list)

    @model_validator(mode="after")
    def _hist_version(self) -> _TaxFileM:
        if self.historical_rules and not self.historical_table_version:
            raise ValueError("historical_rules need a historical_table_version")
        return self


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


def parse_tax_rules(data: Mapping[str, Any], *, include_historical: bool = False) -> TaxRuleSet:
    """Validate a parsed YAML mapping and build the engine's frozen rule objects.

    ``include_historical`` merges the opt-in pre-FY2024-25 rows (backtests only); the table version then carries the
    historical version as a ``+`` suffix.  The historical rows are validated either way.
    """
    try:
        f = _TaxFileM.model_validate(dict(data))
    except ValidationError as exc:
        raise RuleTableError(str(exc)) from exc
    main_ids = {r.rule_id for r in f.rules}
    shadowed = sorted(main_ids & {r.rule_id for r in f.historical_rules})
    if shadowed:
        raise RuleTableError(f"duplicate rule_id(s) between rules and historical_rules: {shadowed}")
    merge = include_historical and bool(f.historical_rules)
    version = f"{f.table_version}+{f.historical_table_version}" if merge else f.table_version
    ruleset = TaxRuleSet(
        schema_version=f.schema_version,
        table_version=version,
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
        rules=tuple(_rule(r) for r in [*f.rules, *(f.historical_rules if merge else [])]),
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


def load_tax_rules(path: Path | None = None, *, include_historical: bool = False) -> TaxRuleSet:
    return parse_tax_rules(_read_yaml(path or TAX_RULES_PATH), include_historical=include_historical)


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


# --- Risk and cost tables (package A11) ----------------------------------------------------------------------


class RowStatus(StrEnum):
    """Status of a risk/cost row.  P/S/NV as in the tax table; PARAMETER is a fixed design choice (not a
    measurement); REQUIRES_CONFIGURATION means the user must supply the value."""

    P = "P"
    S = "S"
    NV = "NV"
    PARAMETER = "PARAMETER"
    REQUIRES_CONFIGURATION = "REQUIRES_CONFIGURATION"


class _Row(_Strict):
    """Every row of a risk/cost table: no row loads without source, status and effective_from."""

    rule_id: str
    effective_from: date
    effective_to: date | None = None
    source_url: str
    verification_status: RowStatus
    notes: str = ""

    @field_validator("source_url")
    @classmethod
    def _https(cls, v: str) -> str:
        return _check_source_url(v)

    @model_validator(mode="after")
    def _dates(self) -> _Row:
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError(f"{self.rule_id}: effective_to before effective_from")
        return self


@dataclass(frozen=True, kw_only=True)
class RowMeta:
    rule_id: str
    effective_from: date
    effective_to: date | None
    source_url: str
    verification_status: RowStatus
    notes: str

    def covers(self, on: date) -> bool:
        return self.effective_from <= on and (self.effective_to is None or on <= self.effective_to)


def _row_meta(m: _Row) -> dict[str, Any]:
    return {
        "rule_id": m.rule_id,
        "effective_from": m.effective_from,
        "effective_to": m.effective_to,
        "source_url": m.source_url,
        "verification_status": m.verification_status,
        "notes": m.notes.strip(),
    }


def _validate(model: type[BaseModel], data: Mapping[str, Any]) -> Any:
    try:
        return model.model_validate(dict(data))
    except ValidationError as exc:
        raise RuleTableError(str(exc)) from exc


def _unique(ids: Iterable[str], what: str) -> None:
    seen: set[str] = set()
    dups: set[str] = set()
    for i in ids:
        (dups if i in seen else seen).add(i)
    if dups:
        raise RuleTableError(f"duplicate {what}: {sorted(dups)}")


# ---- L3 stress table (U-08: index-derived values come from local config only) ----


class ValueSource(StrEnum):
    LOCAL_CONFIG = "LOCAL_CONFIG"  # the number lives in the user's local file, never in the repo
    TABLE = "TABLE"  # a PARAMETER value stored in the public table
    ALIAS = "ALIAS"  # another class's stress × multiplier
    FORMULA = "FORMULA"  # holding-specific (needs e.g. the fund's duration)


@dataclass(frozen=True, kw_only=True)
class DebtShockFormula:
    formula_id: str
    expression: str
    dy: Decimal
    ds_aaa: Decimal
    ds_below_aaa: Decimal


@dataclass(frozen=True, kw_only=True)
class StressRow(RowMeta):
    risk_class: str
    description: str
    value_source: ValueSource
    stress: Decimal | None  # fraction of value lost; None = not configured (or ALIAS/FORMULA)
    recovery_years: Decimal | None
    alias_of: str | None
    multiplier: Decimal | None
    formula: DebtShockFormula | None
    episode: str | None
    back_calculated: bool


@dataclass(frozen=True, kw_only=True)
class StressTable:
    schema_version: int
    table_version: str
    rows: tuple[StressRow, ...]
    local_values_loaded: bool

    def row(self, risk_class: str) -> StressRow:
        for r in self.rows:
            if r.risk_class == risk_class:
                return r
        raise RuleTableError(f"unknown risk class {risk_class!r}")

    def cited_stress(self, risk_class: str) -> Decimal | None:
        """The cited stress for a class, or None when it is not configured (the caller abstains or uses the
        AMFI-recomputed value alone) or is holding-specific (FORMULA)."""
        r = self.row(risk_class)
        if r.value_source is ValueSource.ALIAS:
            assert r.alias_of is not None and r.multiplier is not None  # loader invariant
            base = self.cited_stress(r.alias_of)
            return None if base is None else min(Decimal(1), base * r.multiplier)
        return r.stress

    def requires_configuration(self) -> tuple[str, ...]:
        return tuple(r.risk_class for r in self.rows if r.value_source is ValueSource.LOCAL_CONFIG and r.stress is None)


class _FormulaM(_Strict):
    formula_id: str
    expression: str
    dy: Dec
    ds_aaa: Dec
    ds_below_aaa: Dec

    @model_validator(mode="after")
    def _check(self) -> _FormulaM:
        for name in ("dy", "ds_aaa", "ds_below_aaa"):
            _fraction(getattr(self, name), name)
        return self


class _StressRowM(_Row):
    risk_class: str
    description: str = ""
    value_source: ValueSource
    stress: Dec | None = None
    recovery_years: Dec | None = None
    alias_of: str | None = None
    multiplier: Dec | None = None
    formula: _FormulaM | None = None
    episode: str | None = None
    back_calculated: bool = False

    @model_validator(mode="after")
    def _by_source(self) -> _StressRowM:
        src, rid = self.value_source, self.rule_id
        if src is ValueSource.LOCAL_CONFIG and (self.stress is not None or self.recovery_years is not None):
            raise ValueError(f"{rid}: a LOCAL_CONFIG value belongs in the user's local config, not the repo (U-08)")
        if src is ValueSource.TABLE:
            if self.stress is None or not Decimal(0) <= self.stress <= Decimal(1):
                raise ValueError(f"{rid}: TABLE rows need a stress in [0, 1]")
        elif src is not ValueSource.LOCAL_CONFIG and self.stress is not None:
            raise ValueError(f"{rid}: {src} rows carry no stress value")
        if (src is ValueSource.ALIAS) != (self.alias_of is not None and self.multiplier is not None):
            raise ValueError(f"{rid}: alias_of and multiplier are required for ALIAS rows only")
        if self.multiplier is not None and self.multiplier <= 0:
            raise ValueError(f"{rid}: alias multiplier must be > 0")
        if (src is ValueSource.FORMULA) != (self.formula is not None):
            raise ValueError(f"{rid}: a formula is required for FORMULA rows only")
        return self


class _StressFileM(_Strict):
    schema_version: Literal[1]
    table_version: str
    values_source_decision: str
    classes: list[_StressRowM]


class _LocalStressValueM(_Strict):
    risk_class: str
    stress: Dec
    recovery_years: Dec | None = None
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> _LocalStressValueM:
        if not Decimal(0) < self.stress <= Decimal(1):
            raise ValueError(f"{self.risk_class}: stress must be in (0, 1]")
        if self.recovery_years is not None and self.recovery_years < 0:
            raise ValueError(f"{self.risk_class}: recovery_years must be >= 0")
        return self


class _LocalStressFileM(_Strict):
    schema_version: Literal[1]
    values: list[_LocalStressValueM]


def local_stress_values_path(data_dir: Path) -> Path:
    """Where the user's private stress constants live (U-08): ``<data_dir>/config/stress_drawdowns.local.yaml``."""
    return data_dir / "config" / LOCAL_STRESS_FILENAME


def parse_stress_table(data: Mapping[str, Any], local: Mapping[str, Any] | None = None) -> StressTable:
    f: _StressFileM = _validate(_StressFileM, data)
    _unique((c.rule_id for c in f.classes), "rule_id")
    _unique((c.risk_class for c in f.classes), "risk_class")
    by_class = {c.risk_class: c for c in f.classes}
    for c in f.classes:
        if c.alias_of is not None:
            target = by_class.get(c.alias_of)
            if target is None or target.value_source is ValueSource.ALIAS:
                raise RuleTableError(f"{c.rule_id}: alias_of {c.alias_of!r} must name a non-alias class")
    values: dict[str, _LocalStressValueM] = {}
    if local is not None:
        lf: _LocalStressFileM = _validate(_LocalStressFileM, local)
        _unique((v.risk_class for v in lf.values), "risk_class in the local stress file")
        for v in lf.values:
            row = by_class.get(v.risk_class)
            if row is None:
                raise RuleTableError(f"local stress file: unknown risk class {v.risk_class!r}")
            if row.value_source is not ValueSource.LOCAL_CONFIG:
                raise RuleTableError(f"local stress file: {v.risk_class} is not LOCAL_CONFIG; its value is public")
            values[v.risk_class] = v
    rows = tuple(
        StressRow(
            **_row_meta(c),
            risk_class=c.risk_class,
            description=c.description,
            value_source=c.value_source,
            stress=values[c.risk_class].stress if c.risk_class in values else c.stress,
            recovery_years=values[c.risk_class].recovery_years if c.risk_class in values else c.recovery_years,
            alias_of=c.alias_of,
            multiplier=c.multiplier,
            formula=None if c.formula is None else DebtShockFormula(**c.formula.model_dump()),
            episode=c.episode,
            back_calculated=c.back_calculated,
        )
        for c in f.classes
    )
    return StressTable(
        schema_version=f.schema_version, table_version=f.table_version, rows=rows, local_values_loaded=bool(values)
    )


def load_stress_table(path: Path | None = None, *, local_values_path: Path | None = None) -> StressTable:
    """Public table plus, if the file exists, the user's local values.  A missing local file is not an error:
    the LOCAL_CONFIG classes are then REQUIRES CONFIGURATION."""
    local = _read_yaml(local_values_path) if local_values_path is not None and local_values_path.exists() else None
    return parse_stress_table(_read_yaml(path or STRESS_TABLE_PATH), local)


def _parse_local_stress_env(text: str) -> Mapping[str, Any]:
    # Error messages name the variable only: the value is private (U-08) and must never reach a log or a response.
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        raise RuleTableError(f"invalid YAML in {LOCAL_STRESS_ENV}") from None
    if not isinstance(data, dict):
        raise RuleTableError(f"{LOCAL_STRESS_ENV}: top level must be a mapping")
    return data


def load_user_stress_table(data_dir: Path | None, environ: Mapping[str, str]) -> StressTable:
    """The stress table every caller should use: public rows plus the user's private values (U-08).

    The values come from the secret env var :data:`LOCAL_STRESS_ENV` when it is set and non-blank (the hosted case:
    a serverless deployment has no data dir to hold the local file), else from the local file under ``data_dir``.
    Both use the same schema; a malformed env value is an error, never silently ignored."""
    text = environ.get(LOCAL_STRESS_ENV, "")
    if text.strip():
        return parse_stress_table(_read_yaml(STRESS_TABLE_PATH), _parse_local_stress_env(text))
    return load_stress_table(local_values_path=None if data_dir is None else local_stress_values_path(data_dir))


# ---- L5 allocation policy (structure only; targets are dated user decisions) ----

_OBJECTIVES = frozenset(o.value for o in Objective)
_PARAMETER_VALUES: dict[str, frozenset[str] | None] = {
    "band_abs": None,  # decimal fraction
    "review_cadence": frozenset({"ANNUAL", "SEMI_ANNUAL"}),
    "rebalance_mode": frozenset({"CASH_FLOW_ONLY", "SALES_ALLOWED"}),
}


@dataclass(frozen=True, kw_only=True)
class HorizonBand(RowMeta):
    band_id: str
    min_years: Decimal  # inclusive
    max_years: Decimal | None  # exclusive; None = open-ended

    def contains(self, years: Decimal) -> bool:
        return self.min_years <= years and (self.max_years is None or years < self.max_years)


@dataclass(frozen=True, kw_only=True)
class PolicyParameter(RowMeta):
    parameter: str
    value: Decimal | str


@dataclass(frozen=True, kw_only=True)
class AllocationPolicy:
    schema_version: int
    table_version: str
    sleeves: tuple[str, ...]
    objectives: tuple[str, ...]
    horizon_bands: tuple[HorizonBand, ...]
    parameters: tuple[PolicyParameter, ...]

    def band_for(self, years_to_goal: Decimal) -> HorizonBand:
        for b in self.horizon_bands:
            if b.contains(years_to_goal):
                return b
        raise RuleTableError(f"no horizon band for {years_to_goal} years")

    def parameter(self, name: str) -> Decimal | str:
        for p in self.parameters:
            if p.parameter == name:
                return p.value
        raise RuleTableError(f"unknown policy parameter {name!r}")


@dataclass(frozen=True, kw_only=True)
class UserTarget:
    """One user-decided target cell (band × objective), validated against the policy structure."""

    policy_version: str
    band_id: str
    objective: str
    weights: tuple[tuple[str, Decimal], ...]  # (sleeve, fraction), sums to exactly 1
    decided_on: date

    def weight(self, sleeve: str) -> Decimal:
        return dict(self.weights).get(sleeve, Decimal(0))


class _BandRowM(_Row):
    band_id: str
    min_years: Dec
    max_years: Dec | None = None


class _PolicyParamM(_Row):
    parameter: str
    value: str

    @model_validator(mode="after")
    def _check(self) -> _PolicyParamM:
        if self.parameter not in _PARAMETER_VALUES:
            raise ValueError(f"{self.rule_id}: unknown parameter {self.parameter!r}")
        allowed = _PARAMETER_VALUES[self.parameter]
        if allowed is None:
            dec = _strict_decimal(self.value)
            if not Decimal(0) < dec < Decimal(1):
                raise ValueError(f"{self.rule_id}: band_abs must be a fraction in (0, 1)")
        elif self.value not in allowed:
            raise ValueError(f"{self.rule_id}: {self.parameter} must be one of {sorted(allowed)}")
        return self


class _PolicyFileM(_Strict):
    schema_version: Literal[1]
    table_version: str
    targets_source: Literal["USER_DECISION"]
    sleeves: list[str]
    objectives: list[str]
    horizon_bands: list[_BandRowM]
    parameters: list[_PolicyParamM]
    targets: list[Any]

    @model_validator(mode="after")
    def _check(self) -> _PolicyFileM:
        if self.targets:
            raise ValueError("targets must be empty: every target is a dated user decision, not a shipped value")
        unknown = sorted(set(self.objectives) - _OBJECTIVES)
        if unknown:
            raise ValueError(f"unknown objective(s) {unknown}")
        return self


def parse_allocation_policy(data: Mapping[str, Any]) -> AllocationPolicy:
    f: _PolicyFileM = _validate(_PolicyFileM, data)
    _unique([*(b.rule_id for b in f.horizon_bands), *(p.rule_id for p in f.parameters)], "rule_id")
    _unique((b.band_id for b in f.horizon_bands), "band_id")
    _unique(f.sleeves, "sleeve")
    _unique(f.objectives, "objective")
    _unique((p.parameter for p in f.parameters), "parameter")
    bands = sorted(f.horizon_bands, key=lambda b: b.min_years)
    if not bands or bands[0].min_years != 0 or bands[-1].max_years is not None:
        raise RuleTableError("horizon bands must start at 0 and end open-ended")
    for prev, nxt in pairwise(bands):
        if prev.max_years is None or prev.max_years != nxt.min_years:
            raise RuleTableError("horizon bands must be contiguous")
    return AllocationPolicy(
        schema_version=f.schema_version,
        table_version=f.table_version,
        sleeves=tuple(f.sleeves),
        objectives=tuple(f.objectives),
        horizon_bands=tuple(
            HorizonBand(**_row_meta(b), band_id=b.band_id, min_years=b.min_years, max_years=b.max_years) for b in bands
        ),
        parameters=tuple(
            PolicyParameter(
                **_row_meta(p),
                parameter=p.parameter,
                value=_strict_decimal(p.value) if _PARAMETER_VALUES[p.parameter] is None else p.value,
            )
            for p in f.parameters
        ),
    )


def load_allocation_policy(path: Path | None = None) -> AllocationPolicy:
    return parse_allocation_policy(_read_yaml(path or ALLOCATION_POLICY_PATH))


class _UserTargetM(_Strict):
    band_id: str
    objective: str
    weights: dict[str, Dec]
    decided_on: date
    set_by: Literal["user"]


def parse_user_targets(policy: AllocationPolicy, rows: Iterable[Mapping[str, Any]]) -> tuple[UserTarget, ...]:
    """Validate user-decided targets (from the policy_versions store) against the shipped structure."""
    bands = {b.band_id for b in policy.horizon_bands}
    out: list[UserTarget] = []
    for raw in rows:
        m: _UserTargetM = _validate(_UserTargetM, raw)
        if m.band_id not in bands:
            raise RuleTableError(f"unknown horizon band {m.band_id!r}")
        if m.objective not in policy.objectives:
            raise RuleTableError(f"unknown objective {m.objective!r}")
        bad = sorted(set(m.weights) - set(policy.sleeves))
        if bad:
            raise RuleTableError(f"unknown sleeve(s) {bad}")
        for sleeve, w in m.weights.items():
            if not Decimal(0) <= w <= Decimal(1):
                raise RuleTableError(f"weight for {sleeve} must be a fraction in [0, 1]")
        if sum(m.weights.values(), Decimal(0)) != Decimal(1):
            raise RuleTableError(f"{m.band_id}/{m.objective}: weights must sum to exactly 1")
        out.append(
            UserTarget(
                policy_version=policy.table_version,
                band_id=m.band_id,
                objective=m.objective,
                weights=tuple((s, m.weights[s]) for s in policy.sleeves if s in m.weights),
                decided_on=m.decided_on,
            )
        )
    _unique((f"{t.band_id}/{t.objective}" for t in out), "target cell")
    return tuple(out)


# ---- Cash-market equity / ETF costs ----

CostComponent = Literal[
    "BROKERAGE", "STT", "EXCHANGE_TRANSACTION", "SEBI_TURNOVER_FEE", "STAMP_DUTY", "GST", "DP_CHARGE"
]


@dataclass(frozen=True, kw_only=True)
class CostRow(RowMeta):
    component: str
    applies_to: str
    venue: str | None
    side: str
    basis: str
    rate: Decimal | None
    amount_inr: Decimal | None
    rounding: str | None
    broker_specific: bool


@dataclass(frozen=True, kw_only=True)
class CostParameter(RowMeta):
    parameter: str
    value: Decimal


@dataclass(frozen=True, kw_only=True)
class EquityCostTable:
    schema_version: int
    table_version: str
    snapshot_date: date
    rows: tuple[CostRow, ...]
    parameters: tuple[CostParameter, ...]

    def rows_on(self, on: date, applies_to: str) -> tuple[CostRow, ...]:
        """Rows in force on ``on``.  Empty before the observation date: the caller uses the upper-bound rule
        (flagged costs_estimated) or abstains."""
        return tuple(r for r in self.rows if r.applies_to == applies_to and r.covers(on))

    def parameter(self, name: str) -> Decimal:
        for p in self.parameters:
            if p.parameter == name:
                return p.value
        raise RuleTableError(f"unknown cost parameter {name!r}")


class _CostRowM(_Row):
    component: CostComponent
    applies_to: Literal["EQUITY_DELIVERY", "ETF"]
    venue: Literal["NSE", "BSE"] | None = None
    side: Literal["BUY", "SELL", "BOTH"]
    basis: Literal["TRADED_VALUE", "BROKERAGE_SEBI_FEE_AND_TRANSACTION", "PER_SCRIP_PER_SELL_DAY"]
    rate: Dec | None = None
    amount_inr: Dec | None = None
    rounding: Literal["NEAREST_RUPEE"] | None = None
    broker_specific: bool = False

    @model_validator(mode="after")
    def _value(self) -> _CostRowM:
        rid = self.rule_id
        if self.rate is not None and self.amount_inr is not None:
            raise ValueError(f"{rid}: give a rate or amount_inr, not both")
        if self.rate is None and self.amount_inr is None:
            if self.verification_status not in (RowStatus.NV, RowStatus.REQUIRES_CONFIGURATION):
                raise ValueError(f"{rid}: a {self.verification_status} row needs a rate or amount_inr")
        if self.rate is not None and not Decimal(0) <= self.rate <= Decimal(1):
            raise ValueError(f"{rid}: rate must be a fraction in [0, 1]")
        if self.amount_inr is not None and self.amount_inr < 0:
            raise ValueError(f"{rid}: amount_inr must be >= 0")
        return self


class _CostParamM(_Row):
    parameter: Literal["unverified_period_multiplier"]
    value: Dec

    @model_validator(mode="after")
    def _check(self) -> _CostParamM:
        if self.value < 1:
            raise ValueError(f"{self.rule_id}: an upper-bound multiplier must be >= 1")
        return self


class _CostFileM(_Strict):
    schema_version: Literal[1]
    table_version: str
    snapshot_date: date
    rows: list[_CostRowM]
    parameters: list[_CostParamM]


def parse_equity_costs(data: Mapping[str, Any]) -> EquityCostTable:
    f: _CostFileM = _validate(_CostFileM, data)
    _unique([*(r.rule_id for r in f.rows), *(p.rule_id for p in f.parameters)], "rule_id")
    _unique((p.parameter for p in f.parameters), "parameter")
    rows = tuple(
        CostRow(
            **_row_meta(r),
            component=r.component,
            applies_to=r.applies_to,
            venue=r.venue,
            side=r.side,
            basis=r.basis,
            rate=r.rate,
            amount_inr=r.amount_inr,
            rounding=r.rounding,
            broker_specific=r.broker_specific,
        )
        for r in f.rows
    )
    groups: dict[tuple[str, str, str | None], list[CostRow]] = {}
    for r in rows:
        groups.setdefault((r.component, r.applies_to, r.venue), []).append(r)
    for key, members in groups.items():
        members.sort(key=lambda r: r.effective_from)
        for prev, nxt in pairwise(members):
            if prev.effective_to is None or prev.effective_to >= nxt.effective_from:
                raise RuleTableError(f"cost rows overlap for {key}: {prev.rule_id}, {nxt.rule_id}")
    return EquityCostTable(
        schema_version=f.schema_version,
        table_version=f.table_version,
        snapshot_date=f.snapshot_date,
        rows=rows,
        parameters=tuple(CostParameter(**_row_meta(p), parameter=p.parameter, value=p.value) for p in f.parameters),
    )


def load_equity_costs(path: Path | None = None) -> EquityCostTable:
    return parse_equity_costs(_read_yaml(path or EQUITY_COSTS_PATH))


def load_action_templates(path: Path | None = None) -> TemplateSet:
    """Read ``action_templates.yaml`` (A16). The engine does no IO, so the file is read here and validated (every
    template linted; one failure rejects the set) by :func:`iip.engine.actions.cards.parse_templates`."""
    return parse_templates(_read_yaml(path or ACTION_TEMPLATES_PATH))
