"""Return-Target Feasibility — fixtures F-1 … F-5 from docs/research/return-target-feasibility.md §4.9.

All series here are the spec's hand-computable toy fixtures; the dates are arbitrary placeholders (not market data).
"""

from datetime import date
from decimal import Decimal

import pytest

from iip.engine.errors import InsufficientHistory, InvalidInput
from iip.engine.feasibility import (
    FORBIDDEN_PHRASES,
    EvidenceLevel,
    FeasibilityRequest,
    GridPoint,
    InstrumentKind,
    Mode,
    Observation,
    SeriesMeta,
    YearBasis,
    adjust_splits,
    assess_on_grid,
    build_month_end_grid,
    levers,
    percentile_type7,
)
from iip.engine.money import engine_context

F1 = [100, 130, 150, 120, 150, 190, 200, 160, 210, 260]


def _pct(text: str) -> Decimal:
    return Decimal(text) / 100


def _grid(values: list[int | str]) -> list[GridPoint]:
    # Annual spacing (m = H, steps_per_year = 1). Placeholder year-end dates.
    return [GridPoint(date(2010 + t, 12, 31), Decimal(str(v))) for t, v in enumerate(values)]


def _meta(**kw: object) -> SeriesMeta:
    base: dict[str, object] = {
        "series_id": "toy-f1",
        "instrument_kind": InstrumentKind.INDEX_TRI,
        "inception_date": date(2010, 12, 31),
        "launch_date": None,
        "net_of_fees": False,
        "source": "spec fixture F-1 (toy)",
    }
    base.update(kw)
    return SeriesMeta(**base)  # type: ignore[arg-type]


def _req(h: int, t: str = "0.20", **kw: object) -> FeasibilityRequest:
    base: dict[str, object] = {"target_rate": Decimal(t), "horizon_years": h, "as_of": date(2019, 12, 31)}
    base.update(kw)
    return FeasibilityRequest(**base)  # type: ignore[arg-type]


def _close(x: Decimal, pct_text: str, places: int = 4) -> None:
    with engine_context():
        assert abs(x * 100 - Decimal(pct_text)) <= Decimal(1).scaleb(-places) / 2, (x * 100, pct_text)


# ---------------------------------------------------------------- F-1, H = 1
def test_f1_h1() -> None:
    r = assess_on_grid(_grid(F1), _meta(), _req(1), steps_per_year=1)
    assert r.evidence_level is EvidenceLevel.SUFFICIENT
    assert r.counts is not None
    assert (r.counts.n_windows, r.counts.hit_count, r.counts.loss_count) == (9, 5, 2)
    assert r.frequencies is not None
    with engine_context():
        assert r.frequencies.hit_freq == Decimal(5) / Decimal(9)
        assert r.frequencies.loss_freq == Decimal(2) / Decimal(9)
    expected = ["30.0000", "15.3846", "-20.0000", "25.0000", "26.6667", "5.2632", "-20.0000", "31.2500", "23.8095"]
    for w, e in zip(r.windows, expected, strict=True):
        _close(w.cagr, e)
    hits = [w.start_index for w in r.windows if w.hit]
    assert hits == [0, 3, 4, 7, 8]
    assert r.percentiles is not None
    _close(r.percentiles.cagr["p10"], "-20.0000")
    _close(r.percentiles.cagr["p50"], "23.8095")
    _close(r.percentiles.cagr["p90"], "30.2500")
    assert r.n_eff == 9


# ---------------------------------------------------------------- F-1, H = 2
def test_f1_h2_table_and_low_evidence() -> None:
    r = assess_on_grid(_grid(F1), _meta(), _req(2), steps_per_year=1)
    exp = [
        ("1.5000", "22.4745", True, False, False, "0"),
        ("0.9231", "-3.9231", False, True, False, "-20"),
        ("1.0000", "0.0000", False, False, True, "-20"),
        ("1.5833", "25.8306", True, False, False, "0"),
        ("1.3333", "15.4701", False, False, False, "0"),
        ("0.8421", "-8.2337", False, True, False, "-20"),
        ("1.0500", "2.4695", False, False, False, "-20"),
        ("1.6250", "27.4755", True, False, False, "0"),
    ]
    assert len(r.windows) == 8
    for w, (ratio, cagr, hit, loss, flat, mdd) in zip(r.windows, exp, strict=True):
        with engine_context():
            assert abs(w.ratio - Decimal(ratio)) < Decimal("0.00005")
        _close(w.cagr, cagr)
        assert (w.hit, w.loss, w.flat) == (hit, loss, flat)
        _close(w.max_drawdown, mdd)
    assert r.counts is not None
    assert (r.counts.hit_count, r.counts.loss_count, r.counts.flat_count, r.counts.n_windows) == (3, 2, 1, 8)
    assert r.percentiles is not None
    for key, val in {
        "p10": "-5.2163",
        "p25": "-0.9808",
        "p50": "8.9698",
        "p75": "23.3135",
        "p90": "26.3240",
    }.items():
        _close(r.percentiles.cagr[key], val)
    assert r.path_risk is not None
    _close(r.path_risk.mdd_all["p50"], "-10.0000")
    assert r.path_risk.mdd_hit is not None
    _close(r.path_risk.mdd_hit["p50"], "0")
    assert r.path_risk.worst_mdd_in_hit_window == 0
    # honesty statistics
    assert r.n_eff == 4
    assert [(a.anchor, a.hits, a.blocks) for a in r.anchors] == [(0, 1, 4), (1, 2, 4)]
    with engine_context():
        assert r.anchor_range == (Decimal(1) / 4, Decimal(2) / 4)
    # gate: n_eff = 4 → counts only + LOW EVIDENCE; no percentage headline
    assert r.evidence_level is EvidenceLevel.LOW_EVIDENCE
    assert r.frequencies is None
    assert "LOW EVIDENCE" in r.headline
    assert "3 of 8" in r.headline
    assert "37.5" not in r.headline and "38 %" not in r.headline and "38%" not in r.headline
    # every-year mode (R2)
    assert r.every_year is not None
    assert (r.every_year.count, r.every_year.n_windows) == (2, 8)
    assert r.every_year.longest_calendar_year_streak == 2


# ---------------------------------------------------------------- F-1, H = 3
def test_f1_h3() -> None:
    r = assess_on_grid(_grid(F1), _meta(), _req(3), steps_per_year=1)
    ratios = ["1.2000", "1.1538", "1.2667", "1.6667", "1.0667", "1.1053", "1.3000"]
    for w, e in zip(r.windows, ratios, strict=True):
        with engine_context():
            assert abs(w.ratio - Decimal(e)) < Decimal("0.00005")
    assert r.counts is not None
    assert (r.counts.hit_count, r.counts.loss_count, r.counts.n_windows) == (0, 0, 7)
    assert r.percentiles is not None
    _close(r.percentiles.cagr["p50"], "6.2659")
    _close(r.best.cagr, "18.5631")
    assert (r.best.start_value, r.best.end_value) == (Decimal(120), Decimal(200))
    assert r.n_eff == 3
    assert [(a.hits, a.blocks) for a in r.anchors] == [(0, 3), (0, 2), (0, 2)]
    assert r.evidence_level is EvidenceLevel.LOW_EVIDENCE


def test_f1_full_history_mdd_earliest_peak_on_tie() -> None:
    r = assess_on_grid(_grid(F1), _meta(), _req(2), steps_per_year=1)
    dd = r.full_history_drawdown
    _close(dd.depth, "-20.0000")
    assert dd.peak_date == date(2012, 12, 31)  # t = 2
    assert dd.trough_date == date(2013, 12, 31)  # t = 3
    assert dd.recovery_date == date(2014, 12, 31)  # t = 4, 150 ≥ 150 inclusive


def test_every_year_implies_cagr_hit() -> None:
    for h in (1, 2, 3):
        r = assess_on_grid(_grid(F1), _meta(), _req(h), steps_per_year=1)
        assert r.every_year is not None and r.counts is not None
        assert r.every_year.count <= r.counts.hit_count


# ---------------------------------------------------------------- F-2 .. F-4
def test_f2_inclusive_boundary_in_decimal() -> None:
    r = assess_on_grid(_grid([100, 120, 144]), _meta(), _req(1), steps_per_year=1)
    assert r.counts is not None
    assert (r.counts.hit_count, r.counts.n_windows) == (2, 2)


def test_f3_flat_versus_loss() -> None:
    r = assess_on_grid(_grid([100, 100, 99]), _meta(), _req(1), steps_per_year=1)
    assert r.counts is not None
    assert (r.counts.loss_count, r.counts.flat_count, r.counts.n_windows) == (1, 1, 2)


def test_f4_gates() -> None:
    # 4 y 11 m of month-end steps (59 steps), H = 5 → InsufficientHistory.
    start = date(2010, 1, 31)
    from iip.engine.dates import add_months

    def monthly(n_steps: int) -> list[GridPoint]:
        return [GridPoint(add_months(start, k), Decimal(100 + k)) for k in range(n_steps + 1)]

    with pytest.raises(InsufficientHistory):
        assess_on_grid(monthly(59), _meta(), _req(5), steps_per_year=12)
    # 6-year span, H = 5 → n_eff = 1 → frequencies refused.
    r = assess_on_grid(monthly(72), _meta(), _req(5), steps_per_year=12)
    assert r.n_eff == 1
    assert r.evidence_level is EvidenceLevel.REFUSED
    assert r.counts is None and r.frequencies is None and r.percentiles is None
    assert "1 independent 5-year period" in r.headline


def test_low_evidence_boundary_five_periods_allows_percentages() -> None:
    # Boundary: 10 annual steps, H = 2 → n_eff = 5 (the 11th point needs as_of moved forward: point-in-time).
    r = assess_on_grid(_grid([*F1, 300]), _meta(), _req(2, as_of=date(2020, 12, 31)), steps_per_year=1)
    assert r.n_eff == 5
    assert r.evidence_level is EvidenceLevel.SUFFICIENT
    assert r.frequencies is not None


# ---------------------------------------------------------------- F-5 split adjustment
def test_f5_split_adjustment() -> None:
    obs = [
        Observation(date(2021, 7, 20), Decimal(1000)),
        Observation(date(2021, 7, 21), Decimal(1010)),
        Observation(date(2021, 7, 22), Decimal("101.5")),
        Observation(date(2021, 7, 23), Decimal(102)),
    ]
    adjusted, audit = adjust_splits(obs, InstrumentKind.ETF_NAV)
    assert [o.value for o in adjusted] == [Decimal(1000), Decimal(1010), Decimal(1015), Decimal(1020)]
    assert len(audit) == 1 and audit[0].ratio == 10 and audit[0].effective_date == date(2021, 7, 22)


def test_unexplained_jump_rejected() -> None:
    obs = [Observation(date(2021, 7, 20), Decimal(1000)), Observation(date(2021, 7, 21), Decimal(270))]
    with pytest.raises(InvalidInput):
        adjust_splits(obs, InstrumentKind.ETF_NAV)
    with pytest.raises(InvalidInput):
        adjust_splits(
            [Observation(date(2021, 7, 20), Decimal(1000)), Observation(date(2021, 7, 21), Decimal(100))],
            InstrumentKind.INDEX_TRI,
        )


# ---------------------------------------------------------------- backfill flag
def test_backfilled_windows_tagged_and_reported_both_ways() -> None:
    meta = _meta(launch_date=date(2013, 6, 30))  # windows starting before this are back-calculated
    r = assess_on_grid(_grid(F1), meta, _req(2), steps_per_year=1)
    flags = [w.backfilled for w in r.windows]
    assert flags == [True, True, True, False, False, False, False, False]
    with engine_context():
        assert r.backfilled_share == Decimal(3) / Decimal(8)
    assert r.excluding_backfilled is not None
    assert (r.excluding_backfilled.hit_count, r.excluding_backfilled.n_windows) == (2, 5)
    assert "BACKFILLED_HISTORY" in r.flags


# ---------------------------------------------------------------- start-month sensitivity on monthly grid
def test_anchor_range_on_monthly_grid() -> None:
    from iip.engine.dates import add_months

    start = date(2010, 1, 31)
    vals = [Decimal(100) * (Decimal("1.02") if k % 7 else Decimal("0.97")) ** k for k in range(61)]
    grid = [GridPoint(add_months(start, k), v) for k, v in enumerate(vals)]
    r = assess_on_grid(grid, _meta(), _req(1, "0.10"), steps_per_year=12)
    assert len(r.anchors) == 12
    assert all(a.blocks in (4, 5) for a in r.anchors)
    lo, hi = r.anchor_range
    assert lo <= hi


# ---------------------------------------------------------------- month-end grid builder
def test_month_end_grid_and_point_in_time() -> None:
    obs = [
        Observation(date(2020, 1, 15), Decimal(100)),
        Observation(date(2020, 1, 30), Decimal(101)),
        Observation(date(2020, 2, 27), Decimal(102)),
        Observation(date(2020, 3, 31), Decimal(103)),
        Observation(date(2020, 4, 10), Decimal(104)),  # month not complete at as_of
    ]
    grid = build_month_end_grid(obs, as_of=date(2020, 4, 20))
    # g_0 = first observation, standing in for its own month (this reproduces the spec's §2.2 window counts,
    # e.g. Nifty 500 from 01-Jan-1999 → 321 one-year windows to Sep-2026); then one month-end per later month.
    assert [g.date for g in grid] == [date(2020, 1, 15), date(2020, 2, 27), date(2020, 3, 31)]
    assert not any(g.suspect for g in grid)
    # appending future observations does not change the grid for a fixed as_of
    grid2 = build_month_end_grid([*obs, Observation(date(2020, 5, 29), Decimal(999))], as_of=date(2020, 4, 20))
    assert grid2 == grid


def test_suspect_grid_points_reject_series() -> None:
    obs = [Observation(date(2020, 1, 31), Decimal(100)), Observation(date(2020, 2, 10), Decimal(100))]
    obs += [Observation(date(2020, m, 28), Decimal(100)) for m in range(3, 13)]
    with pytest.raises(InvalidInput):
        build_month_end_grid(obs, as_of=date(2020, 12, 31))


# ---------------------------------------------------------------- input validation
@pytest.mark.parametrize("t", ["-0.50", "-1", "1.01"])
def test_target_rate_bounds(t: str) -> None:
    with pytest.raises(InvalidInput):
        assess_on_grid(_grid(F1), _meta(), _req(1, t), steps_per_year=1)


def test_horizon_bounds() -> None:
    for h in (0, 21):
        with pytest.raises(InvalidInput):
            assess_on_grid(_grid(F1), _meta(), _req(h), steps_per_year=1)


def test_non_positive_value_rejected() -> None:
    with pytest.raises(InvalidInput):
        assess_on_grid(_grid([100, 0, 120]), _meta(), _req(1), steps_per_year=1)


def test_percentile_type7_matches_excel_percentile_inc() -> None:
    xs = [Decimal(v) for v in (1, 2, 3, 4)]
    with engine_context():
        assert percentile_type7(xs, Decimal("0.25")) == Decimal("1.75")
        assert percentile_type7(xs, Decimal("0.5")) == Decimal("2.5")
        assert percentile_type7(xs, Decimal("1")) == Decimal(4)


def test_hit_frequency_monotone_in_target() -> None:
    prev = None
    for t in ("-0.20", "0.00", "0.10", "0.20", "0.30"):
        r = assess_on_grid(_grid(F1), _meta(), _req(1, t), steps_per_year=1)
        assert r.counts is not None
        if prev is not None:
            assert r.counts.hit_count <= prev
        prev = r.counts.hit_count


def test_rupee_translation_and_loss_budget() -> None:
    r = assess_on_grid(
        _grid(F1),
        _meta(),
        _req(2, amount_inr=Decimal(1000000), loss_budget=Decimal("0.10")),
        steps_per_year=1,
    )
    assert r.path_risk is not None
    assert r.path_risk.median_mdd_all_inr == Decimal("900000.00")
    assert r.loss_budget_exceeded_count == 4


def test_levers_never_above_p90() -> None:
    lv = levers(
        goal_inr=Decimal(1000000),
        horizon_years=2,
        target_rate=Decimal("0.40"),
        cagr_p25=Decimal("0.05"),
        cagr_p50=Decimal("0.10"),
        cagr_p90=Decimal("0.30"),
    )
    labels = {line.basis for line in lv}
    assert "target" not in labels  # 40 % > p90 → suppressed
    p50 = next(x for x in lv if x.basis == "historical p50")
    with engine_context():
        assert abs(p50.lump_sum_inr - Decimal(1000000) / Decimal("1.21")) < Decimal("0.01")


# ---------------------------------------------------------------- wording guardrails
@pytest.mark.parametrize("h", [1, 2, 3])
def test_no_forbidden_words_in_any_label(h: int) -> None:
    r = assess_on_grid(
        _grid(F1),
        _meta(launch_date=date(2013, 6, 30)),
        _req(h, "0.35", amount_inr=Decimal(1000000), loss_budget=Decimal("0.10")),
        steps_per_year=1,
    )
    texts = r.all_labels()
    assert texts, "report must carry labels"
    for text in texts:
        low = text.lower()
        for bad in (*FORBIDDEN_PHRASES, "probability", "on track"):
            assert bad not in low, (bad, text)
    assert any("historical frequency" in t.lower() for t in texts)


def test_point_in_time_future_points_ignored() -> None:
    base = assess_on_grid(_grid(F1), _meta(), _req(2), steps_per_year=1)
    more = assess_on_grid(_grid([*F1, 999, 5]), _meta(), _req(2), steps_per_year=1)
    assert base == more


def test_refused_level_hides_everything_but_realised_cagr() -> None:
    r = assess_on_grid(_grid(F1[:4]), _meta(), _req(2, as_of=date(2013, 12, 31)), steps_per_year=1)
    assert r.n_eff == 1 and r.evidence_level is EvidenceLevel.REFUSED
    assert r.windows == () and r.anchors == () and r.path_risk is None
    assert len(r.realised_independent_cagrs) == 1


def test_modes_and_year_basis_recorded() -> None:
    r = assess_on_grid(_grid(F1), _meta(), _req(2, mode=Mode.EVERY_YEAR), steps_per_year=1)
    assert r.year_basis is YearBasis.NOMINAL
    assert r.formula_id.startswith("FEASIBILITY@")


def test_daily_pipeline_with_split_and_inflation() -> None:
    from iip.engine.dates import add_months
    from iip.engine.feasibility import assess_feasibility

    # Month-end observations only (no suspect points), 2010-01 … 2016-12, a 1:10 split mid-way. Toy values.
    start = date(2010, 1, 31)
    raw: list[Observation] = []
    for k in range(84):
        v = Decimal(100) + Decimal(k)
        if k >= 40:
            v = v / 10  # post-split NAV
        raw.append(Observation(add_months(start, k), v))
    meta = _meta(instrument_kind=InstrumentKind.ETF_NAV, net_of_fees=True)
    req = FeasibilityRequest(target_rate=Decimal("0.05"), horizon_years=1, as_of=date(2016, 12, 31))
    r = assess_feasibility(raw, meta, req)
    assert "SPLIT_ADJUSTED" in r.flags
    assert r.counts is not None and r.counts.loss_count == 0  # adjusted series rises every month
    assert r.full_history_drawdown.depth == 0
    # CPI aligned with the grid: rising 20 %/yr; the series grows ≤ 12 %/yr ⇒ every window lags inflation
    adjusted = [Observation(o.date, o.value * (10 if k >= 40 else 1)) for k, o in enumerate(raw)]
    grid = build_month_end_grid(adjusted, as_of=req.as_of)
    cpi = [Decimal(100) * Decimal("1.2") ** (Decimal(k) / 12) for k in range(len(grid))]
    with engine_context():
        r2 = assess_on_grid(grid, meta, req, steps_per_year=12, inflation_index=cpi)
    assert r2.counts is not None and r2.counts.below_inflation_count == r2.counts.n_windows
    assert r2.frequencies is not None and r2.frequencies.below_inflation_freq == 1
