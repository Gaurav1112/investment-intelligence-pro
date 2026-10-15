"""Red team RT-24: forecast / feasibility windows that span a data gap beyond the gate.

Gate (validation-methodology §8 + risk-methodology §1): a gap of more than 7 calendar days makes an observation
suspect; more than 2 % suspect → the series is rejected (forecast SUPPRESSED). Below that, an H-step window across a
gap is not an H-step return, so it is excluded. Feasibility uses its own spec gate (§4.4.1: > 2 % suspect month-end
grid points → reject), now a clean refusal instead of an error. All data are hand-built TEST or FIXTURE values.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from iip.engine.errors import DataGapsExceedGate, InsufficientHistory, InvalidInput
from iip.engine.forecasting import baselines as fb
from iip.services import analysis as an
from iip.services import fixtures
from iip.store.db import connect, migrate, write_tx

AS_OF = date(2026, 10, 15)
NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
SHORT_DUR, EQUITY = "mf:900002", "mf:900003"


def _business_days(start: date, n: int) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _gapped_series() -> tuple[list[date], list[float], int]:
    """1,000 business days of +0.01 %/day, then a 90-calendar-day hole, then 1,000 more. Across the hole the price
    doubles (planted): any window that spans it would show ≈ +100 %."""
    a = _business_days(date(2015, 1, 1), 1000)
    b = _business_days(a[-1] + timedelta(days=91), 1000)
    dates = a + b
    prices = [100.0 * 1.0001**i for i in range(1000)] + [200.0 * 1.0001**i for i in range(1000)]
    return dates, prices, 1000  # index of the first observation after the hole


def test_rt24_b1_excludes_windows_spanning_a_gap() -> None:
    dates, prices, k = _gapped_series()
    h = 21
    gated = fb.empirical_horizon_distribution(dates, prices, horizon=h, as_of=dates[-1], max_gap_days=fb.MAX_GAP_DAYS)
    p = np.asarray(prices)
    all_windows = p[h:] / p[:-h] - 1.0
    keep = [t for t in range(all_windows.size) if not k - h <= t <= k - 1]  # window t uses prices t … t+h
    assert gated.n_windows == len(keep) == all_windows.size - h
    assert max(v for _, v in gated.quantiles) < 0.01  # the planted +100 % never enters the band
    assert any(w.startswith("GAP_WINDOWS_EXCLUDED") for w in gated.meta.warnings)
    # n_eff = largest set of non-overlapping gap-free windows: ⌊999/21⌋ + ⌊999/21⌋ = 47 + 47
    assert gated.n_eff == 94
    ungated = fb.empirical_horizon_distribution(dates, prices, horizon=h, as_of=dates[-1])
    # What the bug looked like: the 21 windows across the hole (each ≈ +100 %) were counted as 21-step returns.
    assert ungated.n_windows == all_windows.size
    assert sum(1 for r in all_windows if r > 0.5) == h


def test_rt24_b1_without_gaps_is_unchanged_by_the_gate() -> None:
    dates = _business_days(date(2015, 1, 1), 1500)
    rng = np.random.default_rng(7)
    prices = list(100.0 * np.cumprod(1 + 0.0003 + 0.005 * rng.standard_normal(1500)))
    a = fb.empirical_horizon_distribution(dates, prices, horizon=63, as_of=dates[-1])
    b = fb.empirical_horizon_distribution(dates, prices, horizon=63, as_of=dates[-1], max_gap_days=fb.MAX_GAP_DAYS)
    assert a == b


def test_rt24_b1_too_many_gaps_is_suppressed() -> None:
    """Every 40th step is a 10-day gap: 2.5 % of observations > 2 % → series rejected (suppressed)."""
    dates: list[date] = []
    d = date(2015, 1, 5)
    for i in range(2000):
        dates.append(d)
        d += timedelta(days=10 if i % 40 == 39 else 1)
    prices = [100.0 + i * 0.01 for i in range(2000)]
    with pytest.raises(DataGapsExceedGate) as exc:
        fb.empirical_horizon_distribution(dates, prices, horizon=21, as_of=dates[-1], max_gap_days=7)
    assert isinstance(exc.value, InsufficientHistory) and exc.value.code == "DATA_GAPS_EXCEED_GATE"


def test_rt24_b1_gaps_leaving_too_few_clean_windows_is_suppressed() -> None:
    """Gaps under 2 % but so frequent that fewer than 10 gap-free independent windows remain → suppressed."""
    dates: list[date] = []
    d = date(2015, 1, 5)
    for i in range(3000):
        dates.append(d)
        d += timedelta(days=9 if i % 60 == 59 else 1)  # 1.67 % gaps, one every 60 steps
    prices = [100.0 + i * 0.01 for i in range(3000)]
    with pytest.raises(InsufficientHistory):
        fb.empirical_horizon_distribution(dates, prices, horizon=63, as_of=dates[-1], max_gap_days=7)


# --------------------------------------------------------------------------------------------- service level


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[Any]:
    c = connect(tmp_path / "a.db")
    migrate(c, NOW.isoformat())
    fixtures.seed(c, as_of=AS_OF, now=NOW)
    yield c
    c.close()


def _delete(conn: Any, code: str, start: str, end: str) -> None:
    with write_tx(conn):
        conn.execute(
            "DELETE FROM observations WHERE series_id=? AND observation_date BETWEEN ? AND ?",
            (f"nav:{code}", start, end),
        )


def test_rt24_forecast_excludes_windows_across_a_hole(conn: Any) -> None:
    before = an.forecast(conn, as_of=AS_OF, instrument_id=SHORT_DUR, horizon_days=91)
    _delete(conn, "900002", "2020-03-01", "2020-05-31")  # a 3-month hole in the history
    after = an.forecast(conn, as_of=AS_OF, instrument_id=SHORT_DUR, horizon_days=91)
    assert before["status"] == after["status"] == "OK"
    assert not any(w.startswith("GAP_WINDOWS_EXCLUDED") for w in before["scenario_range"]["warnings"])
    assert any(w.startswith("GAP_WINDOWS_EXCLUDED") for w in after["scenario_range"]["warnings"])
    # Fewer windows than the plain overlap count: N − H + 1 minus the H windows across the hole.
    n_obs, h = after["scenario_range"]["n_obs"], after["horizon"]["steps"]
    assert after["scenario_range"]["n_windows"] == n_obs - h - h


def test_rt24_forecast_refused_when_gaps_exceed_the_gate(conn: Any) -> None:
    """Delete one full week out of every three since 2020: > 2 % of observations sit behind a > 7-day gap."""
    with write_tx(conn):
        rows = conn.execute(
            "SELECT observation_date FROM observations WHERE series_id='nav:900002'"
            " AND observation_date >= '2020-01-01'"
        ).fetchall()
        for r in rows:
            d = date.fromisoformat(r["observation_date"])
            if d.isocalendar().week % 3 == 0:
                conn.execute("DELETE FROM observations WHERE series_id='nav:900002' AND observation_date=?", (str(d),))
    out = an.forecast(conn, as_of=AS_OF, instrument_id=SHORT_DUR, horizon_days=91)
    assert out["status"] == "REFUSED"
    assert out["refusal"]["code"] == "DATA_GAPS_EXCEED_GATE"
    assert "scenario_range" not in out


def test_rt24_feasibility_refused_cleanly_when_suspect_month_ends_exceed_the_gate(conn: Any) -> None:
    """Feasibility §4.4.1: > 2 % suspect month-end grid points → reject. Before: an InvalidInput error escaped the
    service; now a REFUSED result with the gate's code. Remove the last 10 days of every 3rd month for 8 years."""
    with write_tx(conn):
        for y in range(2015, 2023):
            for m in (3, 6, 9, 12):
                conn.execute(
                    "DELETE FROM observations WHERE series_id='nav:900003' AND observation_date BETWEEN ? AND ?",
                    (f"{y}-{m:02d}-20", f"{y}-{m:02d}-31"),
                )
    out = an.feasibility(conn, as_of=AS_OF, instrument_id=EQUITY, target_annual=Decimal("0.10"), horizon_years=3)
    assert out["status"] == "REFUSED"
    assert out["refusal"]["code"] == "DATA_GAPS_EXCEED_GATE"
    assert "reached_target" not in out


def test_rt24_feasibility_gate_error_is_still_an_invalid_series_for_engine_callers() -> None:
    """The engine-level contract is unchanged (callers that reject InvalidInput still do)."""
    assert issubclass(DataGapsExceedGate, InvalidInput)
