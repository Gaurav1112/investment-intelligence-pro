"""Tax on a backtest's realised lots (research-backtest-method.md §7.2, fixture T-1).

Pure and deterministic: no clock, no IO. Rates are rule rows handed in by the caller (built from
``rules/tax/india.yaml`` by the runner); this module only applies them.

Conventions (each one conservative: it overstates tax or leaves it unchanged, never understates it):

* A rate row is selected by **asset class and transfer date**. No row, or a lot whose long-term gain would need
  s.112A grandfathering (acquired on or before the row's cut-off) → the whole result is pre-tax only and carries
  ``tax_rules_missing`` (the signal verdict is ``ABSTAIN (tax_rules_missing)``).
* One financial year must be covered by one rate row per asset class. A year that mixes rows (for example FY2024-25,
  10 % / 12.5 %) abstains with ``mixed_rate_rows_in_year``, as the repo tax engine does.
* Holding period: long-term only if transferred **after** acquisition + N calendar months (EDATE); exactly N months
  is short-term (``iip.engine.tax.classify_holding``).
* The annual LTCG exemption is a pool shared across all of the user's equity gains in the year. The backtest cannot
  know the user's other gains, so it reports two bounds: ``AVAILABLE`` (the whole exemption is this strategy's) and
  ``USED_ELSEWHERE`` (none of it is). Gates use ``USED_ELSEWHERE``.
* Losses are **not** set off or carried forward (``loss_set_off_not_modelled``); a loss is taxed at zero.
* Surcharge is a flat rate from the row (the user's band, REQUIRES CONFIGURATION; the runner passes the conservative
  one). Cess applies to base tax + surcharge.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from types import MappingProxyType

from iip.engine.errors import InvalidInput
from iip.engine.money import ONE, ZERO, engine_context, money
from iip.engine.tax import GainType, classify_holding, financial_year_label

FORMULA_ID = "BT-TAX-LOTS@1"

EQUITY = "EQUITY"  # listed equity shares and equity-oriented funds (STT-paid), s.111A / s.112A

R_TAX_RULES_MISSING = "tax_rules_missing"
R_GRANDFATHERING_NOT_MODELLED = "grandfathering_not_modelled"
R_MIXED_RATE_ROWS_IN_YEAR = "mixed_rate_rows_in_year"

W_LOSS_SET_OFF_NOT_MODELLED = "loss_set_off_not_modelled"
W_UNVERIFIED_TAX_ROW = "unverified_tax_row"

_VERIFIED = frozenset({"VERIFIED-PRIMARY", "VERIFIED-SECONDARY"})


class ExemptionMode(StrEnum):
    AVAILABLE = "AVAILABLE"  # bound (a): the whole annual exemption is available to this strategy
    USED_ELSEWHERE = "USED_ELSEWHERE"  # bound (b), conservative, used for gates


@dataclass(frozen=True, kw_only=True)
class Realisation:
    """One FIFO slice of a lot consumed by a sell (a tax lot). Money in ₹, unrounded."""

    lot_id: str
    instrument_id: str
    asset_class: str
    acquired: date
    transferred: date
    units: Decimal
    cost_basis_inr: Decimal
    proceeds_inr: Decimal
    sell_costs_deductible_inr: Decimal

    def __post_init__(self) -> None:
        if self.transferred < self.acquired:
            raise InvalidInput(f"lot {self.lot_id}: transferred {self.transferred} before acquired {self.acquired}")
        if self.units <= ZERO:
            raise InvalidInput(f"lot {self.lot_id}: units must be positive")
        for name in ("units", "cost_basis_inr", "proceeds_inr", "sell_costs_deductible_inr"):
            v = getattr(self, name)
            if not isinstance(v, Decimal) or not v.is_finite():
                raise InvalidInput(f"lot {self.lot_id}: {name} must be a finite Decimal")

    @property
    def gain_inr(self) -> Decimal:
        with engine_context():
            return self.proceeds_inr - self.sell_costs_deductible_inr - self.cost_basis_inr


@dataclass(frozen=True, kw_only=True)
class TaxRateRow:
    """A capital-gains rate row for one asset class, in force for transfers in [effective_from, effective_to]."""

    rule_id: str
    asset_class: str
    effective_from: date
    effective_to: date | None
    stcg_rate: Decimal
    ltcg_rate: Decimal
    ltcg_exemption_inr: Decimal
    long_term_after_months: int
    surcharge_rate: Decimal
    cess_rate: Decimal
    grandfathering_on_or_before: date | None
    status: str

    def __post_init__(self) -> None:
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise InvalidInput(f"{self.rule_id}: effective_to before effective_from")
        for name in ("stcg_rate", "ltcg_rate", "surcharge_rate", "cess_rate"):
            v = getattr(self, name)
            if not isinstance(v, Decimal) or not ZERO <= v <= ONE:
                raise InvalidInput(f"{self.rule_id}: {name} must be a Decimal fraction in [0, 1]")
        if not isinstance(self.ltcg_exemption_inr, Decimal) or self.ltcg_exemption_inr < ZERO:
            raise InvalidInput(f"{self.rule_id}: ltcg_exemption_inr must be a non-negative Decimal")
        if self.long_term_after_months <= 0:
            raise InvalidInput(f"{self.rule_id}: long_term_after_months must be positive")

    def covers(self, on: date) -> bool:
        return self.effective_from <= on and (self.effective_to is None or on <= self.effective_to)


@dataclass(frozen=True)
class TaxRateTable:
    rows: tuple[TaxRateRow, ...]

    def __post_init__(self) -> None:
        by_class: dict[str, list[TaxRateRow]] = {}
        for r in self.rows:
            by_class.setdefault(r.asset_class, []).append(r)
        for cls, rows in by_class.items():
            ordered = sorted(rows, key=lambda r: r.effective_from)
            for a, b in pairwise(ordered):
                if a.effective_to is None or a.effective_to >= b.effective_from:
                    raise InvalidInput(f"overlapping tax rows for {cls}: {a.rule_id}, {b.rule_id}")

    def row_for(self, asset_class: str, on: date) -> TaxRateRow | None:
        hits = [r for r in self.rows if r.asset_class == asset_class and r.covers(on)]
        return hits[0] if hits else None


@dataclass(frozen=True, kw_only=True)
class YearTax:
    financial_year: str
    rule_id: str
    stcg_taxable_inr: Decimal
    ltcg_gain_pool_inr: Decimal
    exemption_applied_inr: Decimal
    ltcg_taxable_inr: Decimal
    base_tax_inr: Decimal
    surcharge_inr: Decimal
    cess_inr: Decimal
    total_tax_inr: Decimal  # paise, HALF_UP


@dataclass(frozen=True, kw_only=True)
class TaxResult:
    formula_id: str
    mode: ExemptionMode
    years: tuple[YearTax, ...]
    total_tax_inr: Decimal | None  # None when tax_rules_missing: report pre-tax only
    tax_rules_missing: bool
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    rule_ids_used: tuple[str, ...]
    per_lot_gain_type: Mapping[str, GainType] = field(default_factory=lambda: MappingProxyType({}))


def _fy_key(d: date) -> date:
    return date(d.year if d.month >= 4 else d.year - 1, 4, 1)


def tax_on_realisations(realisations: Iterable[Realisation], table: TaxRateTable, mode: ExemptionMode) -> TaxResult:
    """Tax payable on every realised lot, financial year by financial year, under one exemption bound."""
    items = tuple(realisations)
    reasons: list[str] = []
    warnings: list[str] = []
    classified: dict[date, list[tuple[Realisation, TaxRateRow, GainType]]] = {}
    gain_types: dict[str, GainType] = {}

    for r in items:
        row = table.row_for(r.asset_class, r.transferred)
        if row is None:
            reasons.append(R_TAX_RULES_MISSING)
            continue
        gt = classify_holding(r.acquired, r.transferred, row.long_term_after_months)
        if (
            gt is GainType.LTCG
            and row.grandfathering_on_or_before is not None
            and r.acquired <= row.grandfathering_on_or_before
        ):
            reasons.extend((R_GRANDFATHERING_NOT_MODELLED, R_TAX_RULES_MISSING))
            continue
        if row.status not in _VERIFIED:
            warnings.append(W_UNVERIFIED_TAX_ROW)
        gain_types[f"{r.lot_id}@{r.transferred.isoformat()}"] = gt
        classified.setdefault(_fy_key(r.transferred), []).append((r, row, gt))

    years: list[YearTax] = []
    used: list[str] = []
    for fy in sorted(classified):
        entries = classified[fy]
        rows = {(row.asset_class, row.rule_id) for _, row, _ in entries}
        classes = {c for c, _ in rows}
        if len(rows) != len(classes):
            reasons.extend((R_MIXED_RATE_ROWS_IN_YEAR, R_TAX_RULES_MISSING))
            continue
        for cls in sorted(classes):
            cls_entries = [(r, row, gt) for r, row, gt in entries if row.asset_class == cls]
            row = cls_entries[0][1]
            years.append(_year_tax(fy, row, cls_entries, mode, warnings))
            if row.rule_id not in used:
                used.append(row.rule_id)

    missing = R_TAX_RULES_MISSING in reasons
    total: Decimal | None = None
    if not missing:
        with engine_context():
            total = money(sum((y.total_tax_inr for y in years), ZERO))
    return TaxResult(
        formula_id=FORMULA_ID,
        mode=mode,
        years=tuple(years),
        total_tax_inr=total,
        tax_rules_missing=missing,
        reasons=tuple(dict.fromkeys(reasons)),
        warnings=tuple(dict.fromkeys(warnings)),
        rule_ids_used=tuple(used),
        per_lot_gain_type=MappingProxyType(gain_types),
    )


def _year_tax(
    fy: date,
    row: TaxRateRow,
    entries: Sequence[tuple[Realisation, TaxRateRow, GainType]],
    mode: ExemptionMode,
    warnings: list[str],
) -> YearTax:
    with engine_context():
        stcg = ZERO
        ltcg_pool = ZERO
        for r, _, gt in entries:
            gain = r.gain_inr
            if gain < ZERO:
                warnings.append(W_LOSS_SET_OFF_NOT_MODELLED)
                continue
            if gt is GainType.LTCG:
                ltcg_pool += gain
            else:
                stcg += gain
        exemption_cap = row.ltcg_exemption_inr if mode is ExemptionMode.AVAILABLE else ZERO
        exemption = min(ltcg_pool, exemption_cap)
        ltcg_taxable = ltcg_pool - exemption
        base = stcg * row.stcg_rate + ltcg_taxable * row.ltcg_rate
        surcharge = base * row.surcharge_rate
        cess = (base + surcharge) * row.cess_rate
        total = money(base + surcharge + cess)
    return YearTax(
        financial_year=financial_year_label(fy),
        rule_id=row.rule_id,
        stcg_taxable_inr=stcg,
        ltcg_gain_pool_inr=ltcg_pool,
        exemption_applied_inr=exemption,
        ltcg_taxable_inr=ltcg_taxable,
        base_tax_inr=base,
        surcharge_inr=surcharge,
        cess_inr=cess,
        total_tax_inr=total,
    )
