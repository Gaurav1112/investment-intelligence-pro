"""Red team (Phase 14): forecast / feasibility evidence gates, look-ahead in analysis, tax assumptions in discovery.

All instrument data is FIXTURE (services/fixtures.py) or derived from it; none is market data.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from iip.rules.loader import load_tax_rules
from iip.services import analysis as an
from iip.services import discovery as disc
from iip.services import fixtures
from iip.services.profile import Profile, evaluate
from iip.store.db import connect, migrate, write_tx
from iip.store.observations import ObservationRow, upsert_observation

AS_OF = date(2026, 10, 15)
NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
RULES = load_tax_rules()
SHORT_DUR, EQUITY = "mf:900002", "mf:900003"


def _db(path: Path) -> Any:
    c = connect(path)
    migrate(c, NOW.isoformat())
    fixtures.seed(c, as_of=AS_OF, now=NOW)
    return c


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[Any]:
    c = _db(tmp_path / "a.db")
    yield c
    c.close()


def _copy_scheme(conn: Any, code: str, source_code: str, last_n: int) -> str:
    iid = f"mf:{code}"
    with write_tx(conn):
        conn.execute(
            "INSERT INTO instruments(instrument_id, kind, name, amfi_code, origin, created_at)"
            " VALUES (?, 'mf_scheme', 'FIXTURE New Equity Fund', ?, 'fixture', ?)",
            (iid, code, NOW.isoformat()),
        )
        conn.execute(
            "INSERT INTO mf_schemes(instrument_id, amc, category_raw, plan, exit_load_json)"
            " VALUES (?, 'FIXTURE AMC', 'Equity Scheme - Large Cap Fund', 'direct', NULL)",
            (iid,),
        )
    rows = conn.execute(
        "SELECT observation_date, value FROM observations WHERE series_id=? ORDER BY observation_date",
        (f"nav:{source_code}",),
    ).fetchall()[-last_n:]
    for r in rows:
        upsert_observation(conn, ObservationRow(
            series_id=f"nav:{code}", kind="nav", value=r["value"], unit="INR/unit", currency="INR",
            observation_date=r["observation_date"], retrieved_at=NOW.isoformat(), source_id="fixture",
            source_url=fixtures.FIXTURE_URL, quality_status="fixture", raw_sha256="f" * 64, convention="synthetic NAV",
        ))  # fmt: skip
    return iid


# --------------------------------------------------------------------------------------------- RT-10
def test_rt10_forecast_refused_for_instrument_with_under_one_year_of_history(conn: Any) -> None:
    """validation-methodology §8: newly launched (< 1 year) → the forecast is SUPPRESSED, not shown with 7 levels."""
    iid = _copy_scheme(conn, "990077", "900003", 200)  # ~200 business days ≈ 9 months
    out = an.forecast(conn, as_of=AS_OF, instrument_id=iid, horizon_days=7)
    assert out["status"] == "REFUSED", out.get("scenario_range", {}).get("n_eff")
    assert out["refusal"]["code"] == "INSUFFICIENT_HISTORY"
    assert "scenario_range" not in out


# --------------------------------------------------------------------------------------------- RT-11
def test_rt11_low_evidence_feasibility_shows_counts_only(conn: Any) -> None:
    """return-target-feasibility §4.5: 2 ≤ n_eff < 5 → counts only, NO percentages (percentiles, dots, drawdowns)."""
    out = an.feasibility(conn, as_of=AS_OF, instrument_id=EQUITY, target_annual=Decimal("0.20"), horizon_years=5)
    assert out["status"] == "LOW_EVIDENCE"
    assert out["reached_target"]["count"] is not None  # counts stay
    assert "percentiles" not in out
    assert "dots" not in out
    assert "in_window_mdd" not in out.get("drawdown", {})


def test_rt11_sufficient_feasibility_still_shows_percentages(conn: Any) -> None:
    out = an.feasibility(conn, as_of=AS_OF, instrument_id=EQUITY, target_annual=Decimal("0.20"), horizon_years=1)
    assert out["status"] == "SUFFICIENT" and "percentiles" in out and "dots" in out


# --------------------------------------------------------------------------------------------- RT-12
def test_rt12_forecast_validation_uses_no_data_after_as_of(tmp_path: Path) -> None:
    """A forecast 'as of' 2018-01-01 must equal the same forecast on a store that holds only data up to that date.

    Before the fix the walk-forward validation (coverage, pinball, MAE) scored outcomes from 2018–2026."""
    past = date(2018, 1, 1)
    full = _db(tmp_path / "full.db")
    cut = _db(tmp_path / "cut.db")
    with write_tx(cut):
        cut.execute("DELETE FROM observations WHERE observation_date > ?", (past.isoformat(),))
    a = an.forecast(full, as_of=past, instrument_id=SHORT_DUR, horizon_days=182)
    b = an.forecast(cut, as_of=past, instrument_id=SHORT_DUR, horizon_days=182)
    assert a["status"] == b["status"] == "OK"
    assert a["scenario_range"]["data_cutoff"] <= past.isoformat()
    assert a["horizon"] == b["horizon"]
    assert a["validation"] == b["validation"]


# --------------------------------------------------------------------------------------------- RT-13
def _profile(**kw: object) -> Profile:
    base: dict[str, object] = {
        "amount": "500000", "withdrawal_date": "2027-04-15", "objective": "A_capital_preservation",
        "loss_acceptable": False, "early_need": "possible", "tax_regime": "new", "slab_rate": "0.30",
    }  # fmt: skip
    base.update(kw)
    return Profile.model_validate(base)


def _tbill_tax(out: dict[str, Any]) -> Decimal:
    row = next(r for r in out["ranked"] + out["excluded"] if r["instrument_id"].startswith("tbill:"))
    q50 = row["outcome"]["q50"]
    _, tax = q50["substituted"].split(" − tax ")
    return Decimal(tax.split(" = ")[0].replace("₹", "").replace(",", ""))


def test_rt13_user_surcharge_band_is_applied(conn: Any) -> None:
    """Discovery hard-coded surcharge 0 for every user profile: tax understated for income above ₹50 lakh."""
    base = disc.discover(conn, evaluate(_profile(), AS_OF), as_of=AS_OF, ruleset=RULES, allow_fixtures=True)
    high = disc.discover(conn, evaluate(_profile(surcharge_rate="0.25"), AS_OF), as_of=AS_OF, ruleset=RULES,
                         allow_fixtures=True)  # fmt: skip
    assert _tbill_tax(high) > _tbill_tax(base)


def test_rt13_unknown_surcharge_is_disclosed_not_silent(conn: Any) -> None:
    out = disc.discover(conn, evaluate(_profile(), AS_OF), as_of=AS_OF, ruleset=RULES, allow_fixtures=True)
    assert "surcharge" in out["context"]["tax_basis"].lower()
    assert "understate" in out["context"]["tax_basis"].lower()


def test_rt13_surcharge_band_must_be_a_legislated_band() -> None:
    with pytest.raises(ValueError, match="surcharge"):
        _profile(surcharge_rate="0.12")


# --------------------------------------------------------------------------------------------- RT-16
def test_rt16_forecast_on_stale_nav_and_unvalidated_band_is_flagged(conn: Any) -> None:
    """A series whose last NAV is a month old, and a band that failed its own coverage gate, were shown as plain OK."""
    out = an.forecast(conn, as_of=date(2026, 11, 15), instrument_id=EQUITY, horizon_days=182)
    assert out["status"] == "OK"
    warnings = out["scenario_range"]["warnings"]
    assert any(w.startswith("STALE_DATA") for w in warnings), warnings
    if out["validation"].get("passes_coverage_gate") is not True:
        assert any(w.startswith("CALIBRATION_NOT_ESTABLISHED") for w in warnings), warnings
