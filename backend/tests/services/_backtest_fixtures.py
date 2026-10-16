"""Synthetic fixtures for the B05 backtest tests. Every series, rate and id is FICTIONAL (seeded noise): no AMFI,
NSE, RBI or MoSPI value, no real scheme code and no backtest output is committed (the repo is public)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

import numpy as np

from iip.engine.backtest.gates import SeriesProvenance
from iip.engine.backtest.ledger import CostBasisPolicy
from iip.engine.backtest.tax_lots import TaxRateRow, TaxRateTable
from iip.engine.backtest.walkforward import CostRateRow, MfCostSchedule, NavPanel
from iip.services.backtest_runner import RunContext

NOW = "2026-10-16T05:00:00+00:00"
START = date(2006, 1, 2)
END = date(2024, 12, 31)


def business_days(start: date = START, end: date = END) -> tuple[date, ...]:
    out: list[date] = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return tuple(out)


def _path(rng: np.random.Generator, n: int, mu: float, sigma: float, start: str = "10.0000") -> tuple[Decimal, ...]:
    q = Decimal("0.0001")
    level = Decimal(start)
    out = [level]
    for x in rng.normal(mu, sigma, size=n - 1):
        level = (level * (Decimal(1) + Decimal(repr(float(x))))).quantize(q)
        out.append(level)
    return tuple(out)


def zero_skill_panel(roles: Sequence[str], *, seed: int = 7, liquid: str = "liquid_fund.direct") -> NavPanel:
    """Every risky role is i.i.d. Gaussian noise (no autocorrelation: no timing rule can have skill); the liquid
    role grows smoothly. Fictional."""
    dates = business_days()
    rng = np.random.default_rng(seed)
    navs: dict[str, tuple[Decimal, ...]] = {}
    for r in sorted(roles):
        if r == liquid:
            navs[r] = _path(rng, len(dates), 0.00025, 0.00002, "1000.0000")
        else:
            navs[r] = _path(rng, len(dates), 0.0003, 0.011)
    return NavPanel(dates, navs)


def synthetic_tax_table() -> TaxRateTable:
    """Fictional flat rates covering the whole fixture window, so G6 is evaluated rather than abstaining."""
    common = {
        "effective_from": date(2000, 1, 1),
        "effective_to": None,
        "ltcg_exemption_inr": Decimal(0),
        "surcharge_rate": Decimal(0),
        "cess_rate": Decimal("0.04"),
        "grandfathering_on_or_before": None,
        "status": "NOT VERIFIED",
    }
    return TaxRateTable(
        rows=(
            TaxRateRow(
                rule_id="FIC-EQ",
                asset_class="EQUITY",
                stcg_rate=Decimal("0.20"),
                ltcg_rate=Decimal("0.125"),
                long_term_after_months=12,
                **common,
            ),  # type: ignore[arg-type]
            TaxRateRow(
                rule_id="FIC-DEBT",
                asset_class="DEBT",
                stcg_rate=Decimal("0.30"),
                ltcg_rate=Decimal("0.30"),
                long_term_after_months=36,
                **common,
            ),  # type: ignore[arg-type]
            TaxRateRow(
                rule_id="FIC-OTHER",
                asset_class="OTHER",
                stcg_rate=Decimal("0.30"),
                ltcg_rate=Decimal("0.125"),
                long_term_after_months=24,
                **common,
            ),  # type: ignore[arg-type]
        )
    )


def synthetic_costs() -> MfCostSchedule:
    return MfCostSchedule(
        rows=(
            CostRateRow(
                rule_id="FIC-STAMP",
                component="stamp_duty",
                side="buy",
                tax_classes=frozenset({"EQUITY", "DEBT", "OTHER"}),
                rate=Decimal("0.00005"),
                effective_from=date(2000, 1, 1),
                effective_to=None,
                status="VERIFIED-SECONDARY",
            ),
        ),
        slippage_rate=Decimal(0),
    )


def provenance(roles: Sequence[str]) -> tuple[SeriesProvenance, ...]:
    return tuple(
        SeriesProvenance(
            role=r,
            source_id="fixture.synthetic",
            licence_status="VERIFIED",
            known_time_populated=True,
            snapshot_hash="f" * 64,
        )
        for r in sorted(roles)
    )


def context(panel: NavPanel, *, replicates: int = 2, **kw: object) -> RunContext:
    return RunContext(
        panel=panel,
        provenance=provenance(tuple(panel.navs)),
        costs=synthetic_costs(),
        cost_policy=CostBasisPolicy(deductible_components=frozenset({"stamp_duty"}), status="NOT VERIFIED"),
        tax_table=synthetic_tax_table(),
        code_version="test-code",
        created_at=NOW,
        canary_replicates=replicates,
        **kw,  # type: ignore[arg-type]
    )
