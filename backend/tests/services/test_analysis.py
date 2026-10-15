"""Stage D analysis services. All instrument data here is FIXTURE (synthetic), by design (services/fixtures.py)."""

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from iip.engine.money import engine_context
from iip.rules.loader import load_tax_rules
from iip.services import analysis as an
from iip.services import discovery as disc
from iip.services import fixtures
from iip.store.db import connect, migrate, write_tx
from iip.store.observations import ObservationRow, upsert_observation

AS_OF = date(2026, 10, 15)
NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
RULES = load_tax_rules()
LIQUID, SHORT_DUR, EQUITY, ARB = "mf:900001", "mf:900002", "mf:900003", "mf:900004"
TBILL = f"tbill:182d:{(AS_OF + timedelta(days=180)).isoformat()}"
FD = "fd:fixture-bank:180d"
APR = date(2027, 4, 15)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[Any]:
    c = connect(tmp_path / "x.db")
    migrate(c, NOW.isoformat())
    fixtures.seed(c, as_of=AS_OF, now=NOW)
    yield c
    c.close()


def _walk(obj: Any) -> Iterator[Any]:
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list | tuple):
        for v in obj:
            yield from _walk(v)


def _no_floats(out: dict[str, Any]) -> None:
    assert not any(isinstance(x, float) for x in _walk(out))
    json.loads(json.dumps(out), parse_float=lambda s: pytest.fail(f"float in output: {s}"))


def _compare(conn: Any, ids: list[str], **kw: Any) -> dict[str, Any]:
    return an.compare(conn, as_of=AS_OF, ruleset=RULES, instrument_ids=ids, amount=kw.get("amount"),
                      withdrawal=kw.get("withdrawal"))  # fmt: skip


# ----------------------------------------------------------------------------------------- shared builder


@pytest.mark.parametrize("withdrawal", [AS_OF + timedelta(days=182), date(2027, 11, 20)])
def test_build_one_matches_discovery_build_universe(conn: Any, withdrawal: date) -> None:
    """The single-instrument helper must produce exactly what discovery's universe builder produces."""
    amount = Decimal("250000")
    uni = disc.build_universe(conn, amount=amount, as_of=AS_OF, withdrawal=withdrawal, ruleset=RULES, profile=None,
                              excluded_kinds=())  # fmt: skip
    assert len(uni.built) == 6
    for b in uni.built:
        iid = b.candidate.instrument_id
        one = an.build_one(conn, iid, amount=amount, as_of=AS_OF, withdrawal=withdrawal, ruleset=RULES, profile=None)
        assert one.built == b, iid
        assert one.prov == {**uni.sources[iid], **({"kind": one.kind})}


def test_unknown_instrument_is_404(conn: Any) -> None:
    with pytest.raises(an.AnalysisError) as e:
        _compare(conn, [LIQUID, "mf:nope"])
    assert e.value.status == 404


# ----------------------------------------------------------------------------------------- compare


def test_compare_rows_reconcile_and_are_explained(conn: Any) -> None:
    out = _compare(conn, [TBILL, FD, LIQUID, EQUITY], amount=Decimal("500000"), withdrawal=APR)
    _no_floats(out)
    assert out["fixture"] is True and out["context"]["amount_basis"] == "request"
    assert [r["instrument_id"] for r in out["rows"]] == [TBILL, FD, LIQUID, EQUITY]
    for r in out["rows"]:
        assert r["fixture"] is True and r["evaluable"], r["eligibility_reasons"]
        for w in an.WHICH:
            gross = Decimal(r["gross_proceeds"][w]["value"])
            load = Decimal(r["costs"]["exit_load"][w]["value"])
            tax = Decimal(r["tax"]["values"][w]["value"])
            net = Decimal(r["net_proceeds"][w]["value"])
            assert abs(gross - load - tax - net) <= Decimal("0.02")  # each leg is rounded to paise for display
            assert Decimal(r["net_pnl"][w]["value"]) == net - Decimal("500000.00")
            for e in (r["gross_proceeds"][w], r["net_proceeds"][w], r["tax"]["values"][w]):
                assert e["formula"] and e["hash"] and e["engine_version"] and e["freshness"] == "FIXTURE"
                assert e["sources"] and e["sources"][0]["url"].startswith("https://fixture.invalid")
        assert r["tax"]["basis"] == "illustrative_30_percent_slab"
    eq = out["rows"][3]
    assert eq["net_proceeds"]["q05"]["label"].startswith("Illustrative downside scenario")
    assert "worst case" not in json.dumps(out).lower()


def test_compare_order_gaps_are_q05_differences(conn: Any) -> None:
    out = _compare(conn, [LIQUID, SHORT_DUR, EQUITY, ARB])
    q05 = {r["instrument_id"]: Decimal(r["net_proceeds"]["q05"]["value"]) for r in out["rows"]}
    assert out["order"] == sorted(q05, key=lambda i: (-q05[i], i))
    assert len(out["what_would_change_order"]) == 3
    for ch in out["what_would_change_order"]:
        assert Decimal(ch["gap"]["value"]) == q05[ch["above"]] - q05[ch["below"]]
        assert Decimal(ch["gap"]["value"]) >= 0


def test_compare_defaults_to_labelled_illustrative_context(conn: Any) -> None:
    out = _compare(conn, [LIQUID, ARB])
    ctx = out["context"]
    assert ctx["illustrative"] is True and ctx["amount_value"] == "100000" and ctx["horizon_days"] == 182
    assert "ILLUSTRATIVE" in ctx["illustrative_label"]


def test_no_annualisation_below_one_year(conn: Any) -> None:
    short = _compare(conn, [TBILL, LIQUID], withdrawal=APR)
    for r in short["rows"]:
        for w in an.WHICH:
            assert r["returns"][w]["annualised"] is None
            assert r["returns"][w]["absolute"]["unit"] == "fraction"
            assert "Not annualised" in r["returns"][w]["annualisation_note"]
    long = _compare(conn, [LIQUID, EQUITY], withdrawal=date(2027, 11, 20))
    for r in long["rows"]:
        ann = r["returns"]["q50"]["annualised"]
        assert ann is not None and "secondary" in ann["label"]
        assert r["returns"]["q50"]["absolute"] is not None  # absolute stays the headline


def test_compare_is_deterministic(conn: Any) -> None:
    a = _compare(conn, [TBILL, FD, LIQUID], amount=Decimal("300000"), withdrawal=APR)
    b = _compare(conn, [TBILL, FD, LIQUID], amount=Decimal("300000"), withdrawal=APR)
    assert a["run"] == b["run"]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_compare_rejects_bad_sets(conn: Any) -> None:
    for ids in ([LIQUID], [LIQUID, LIQUID], [LIQUID, SHORT_DUR, EQUITY, ARB, FD]):
        with pytest.raises(an.AnalysisError) as e:
            _compare(conn, ids)
        assert e.value.status == 422


def test_ineligible_instrument_returns_reasons_not_numbers(conn: Any) -> None:
    out = _compare(conn, [TBILL, LIQUID], withdrawal=AS_OF + timedelta(days=30))  # T-bill matures after
    tb = out["rows"][0]
    assert tb["evaluable"] is False and any("HORIZON_MISMATCH" in r for r in tb["eligibility_reasons"])
    assert "net_proceeds" not in tb and out["order"] == [LIQUID]


# ----------------------------------------------------------------------------------------- scenario


def _scenario(conn: Any, iid: str, shocks: dict[str, Any], **kw: Any) -> dict[str, Any]:
    return an.scenario(conn, as_of=AS_OF, ruleset=RULES, instrument_id=iid, amount=kw.get("amount"),
                       withdrawal=kw.get("withdrawal", APR), shocks=shocks)  # fmt: skip


def _impacts(entry: dict[str, Any]) -> list[Decimal]:
    return [Decimal(v["impact"]["value"]) for v in entry["values"]]


def test_zero_shock_gives_zero_impact(conn: Any) -> None:
    eq = _scenario(conn, EQUITY, {"equity_pct": Decimal("0")})
    (entry,) = eq["results"]
    assert entry["status"] == "applied" and _impacts(entry) == [Decimal("0.00")] * 3
    for v in entry["values"]:
        assert v["before"]["value"] == v["after"]["value"]
    tb = _scenario(conn, TBILL, {"rate_bp": Decimal("0"), "exit_before_maturity_days": 60})
    rate = tb["results"][0]
    assert rate["shock"] == "rate_bp" and rate["status"] == "applied" and _impacts(rate) == [Decimal("0.00")]


def test_larger_rate_shock_gives_larger_loss(conn: Any) -> None:
    def loss(bp: str) -> Decimal:
        out = _scenario(conn, TBILL, {"rate_bp": Decimal(bp), "exit_before_maturity_days": 60})
        return _impacts(out["results"][0])[0]

    small, large = loss("50"), loss("200")
    assert small < 0 and large < small
    assert loss("-50") > 0  # a fall in yields raises the sale price


def test_larger_equity_shock_gives_larger_loss(conn: Any) -> None:
    def impacts(pct: str) -> list[Decimal]:
        return _impacts(_scenario(conn, EQUITY, {"equity_pct": Decimal(pct)})["results"][0])

    assert all(b < a < 0 for a, b in zip(impacts("-10"), impacts("-30"), strict=True))


def test_inapplicable_shocks_say_why_and_never_return_zero(conn: Any) -> None:
    out = _scenario(conn, FD, {"rate_bp": Decimal("100"), "spread_bp": Decimal("50"), "inflation_pct": Decimal("2"),
                               "exit_before_maturity_days": 30, "reinvestment_rate": Decimal("0.05"),
                               "equity_pct": Decimal("-20")})  # fmt: skip
    assert len(out["results"]) == 6
    for entry in out["results"]:
        assert entry["status"] == "not_applicable", entry["shock"]
        assert entry["reason"] and entry["values"] is None
    tb = _scenario(conn, TBILL, {"rate_bp": Decimal("100")})  # held to maturity
    assert tb["results"][0]["status"] == "not_applicable" and "maturity" in tb["results"][0]["reason"]
    debt = _scenario(conn, SHORT_DUR, {"rate_bp": Decimal("100")})
    assert "duration" in debt["results"][0]["reason"]


def test_scenario_echoes_exact_inputs_and_is_deterministic(conn: Any) -> None:
    shocks = {"equity_pct": Decimal("-12.5"), "exit_before_maturity_days": 30}
    a = _scenario(conn, EQUITY, shocks, amount=Decimal("123456.78"))
    b = _scenario(conn, EQUITY, shocks, amount=Decimal("123456.78"))
    _no_floats(a)
    assert a["request"]["shocks"]["equity_pct"] == "-12.5"
    assert a["request"]["shocks"]["exit_before_maturity_days"] == "30"
    assert a["request"]["amount"] == "123456.78" and a["fixture"] is True
    assert a["run"] == b["run"]
    labels = {e["label"] for e in a["results"]}
    assert labels <= {"stress scenario", "illustrative downside"}
    for e in a["results"]:
        assert e["probability_weighted"] is False


def test_scenario_requires_a_shock(conn: Any) -> None:
    with pytest.raises(an.AnalysisError) as e:
        _scenario(conn, EQUITY, {"rate_bp": None})
    assert e.value.status == 422


# ----------------------------------------------------------------------------------------- simulate


@pytest.mark.parametrize(
    ("amount", "weights"),
    [
        ("100000.01", ["0.3333", "0.3333", "0.3334"]),
        ("99999.99", ["0.1", "0.2", "0.7"]),
        ("1000000", ["0.142857", "0.285714", "0.571429"]),
        ("7.03", ["0.5", "0.25", "0.25"]),
    ],
)
def test_allocations_reconcile_exactly(amount: str, weights: list[str]) -> None:
    alloc = an.allocate_exact(Decimal(amount), [Decimal(w) for w in weights])
    assert sum(alloc, Decimal(0)) == Decimal(amount)
    assert all(a == a.quantize(Decimal("0.01")) for a in alloc)


def test_allocate_rejects_weights_not_summing_to_one() -> None:
    with pytest.raises(an.AnalysisError) as e:
        an.allocate_exact(Decimal("1000"), [Decimal("0.5"), Decimal("0.49")])
    assert e.value.status == 422


def _simulate(conn: Any, allocs: list[tuple[str, str]], **kw: Any) -> dict[str, Any]:
    return an.simulate(conn, as_of=AS_OF, ruleset=RULES, allocations=[(i, Decimal(w)) for i, w in allocs],
                       amount=kw.get("amount"), withdrawal=kw.get("withdrawal", APR))  # fmt: skip


def test_simulate_portfolio(conn: Any) -> None:
    allocs = [(LIQUID, "0.3333"), (TBILL, "0.3333"), (FD, "0.3334")]
    out = _simulate(conn, allocs, amount=Decimal("600000.01"))
    _no_floats(out)
    assert out["fixture"] is True
    amounts = [Decimal(h["allocation"]["value"]) for h in out["holdings"]]
    assert sum(amounts, Decimal(0)) == Decimal("600000.01") and out["reconciliation"]["reconciles"] is True
    band = out["portfolio"]["band"]
    for w in an.WHICH:  # the sum is of unrounded engine values; each displayed holding is rounded to paise
        holding_sum = sum((Decimal(h["band"][w]["value"]) for h in out["holdings"]), Decimal(0))
        assert abs(Decimal(band[w]["value"]) - holding_sum) <= Decimal("0.02")
    assert band["q05"]["label"] == "Conservative sum, ignores diversification"
    hhi = Decimal(out["concentration"]["hhi"]["value"])
    assert hhi == Decimal("0.3333") ** 2 * 2 + Decimal("0.3334") ** 2
    ladder_total = sum((Decimal(x["amount"]["value"]) for x in out["liquidity_ladder"]), Decimal(0))
    assert ladder_total == Decimal("600000.01")
    mats = {m["instrument_id"]: m for m in out["maturity"]}
    assert mats[LIQUID]["status"] == "no_maturity"
    assert mats[TBILL]["status"] == "matures_before_withdrawal" and mats[TBILL]["days_between"] == 2
    dicgc = out["dicgc"]
    assert dicgc["applicable"] is True and dicgc["groups"][0]["institution"] == "FIXTURE Bank"
    total = Decimal(dicgc["groups"][0]["total"]["value"])
    assert total > Decimal("200000.01")  # principal + interest at maturity


def test_simulate_flags_maturity_mismatch_and_refuses_band(conn: Any) -> None:
    out = _simulate(conn, [(LIQUID, "0.5"), (FD, "0.5")], withdrawal=AS_OF + timedelta(days=90))
    mats = {m["instrument_id"]: m for m in out["maturity"]}
    assert mats[FD]["status"] == "MATURITY_MISMATCH_after_withdrawal"
    assert out["portfolio"]["status"] == "refused" and out["portfolio"]["value"] is None


def test_simulate_validation(conn: Any) -> None:
    with pytest.raises(an.AnalysisError):
        _simulate(conn, [(LIQUID, "0.5"), (LIQUID, "0.5")])
    with pytest.raises(an.AnalysisError):
        _simulate(conn, [(LIQUID, "0.6"), (FD, "0.5")])


# ----------------------------------------------------------------------------------------- feasibility


def _feas(conn: Any, h: int, target: str = "0.20", iid: str = EQUITY) -> dict[str, Any]:
    return an.feasibility(conn, as_of=AS_OF, instrument_id=iid, target_annual=Decimal(target), horizon_years=h)


def test_feasibility_sufficient_evidence(conn: Any) -> None:
    out = _feas(conn, 1)
    _no_floats(out)
    assert out["status"] == "SUFFICIENT" and out["low_evidence"] is False and out["fixture"] is True
    assert out["independent_periods"] >= 5
    rt = out["reached_target"]
    assert rt["frequency"] is not None and rt["frequency"]["unit"] == "fraction"
    with engine_context():
        assert Decimal(rt["frequency"]["value"]) == Decimal(rt["count"]) / Decimal(rt["of"])
    dots = out["dots"]
    vals = [Decimal(d["value"]) for d in dots["values"]]
    assert len(vals) == 20 and vals == sorted(vals)
    assert dots["reached_target"] == sum(1 for v in vals if v >= Decimal("0.20"))
    assert set(out["percentiles"]) == {"p5", "p10", "p25", "p50", "p75", "p90", "p95"}
    assert out["full_history_drawdown"]["trough_date"]
    text = json.dumps(out).lower()
    assert "probability" not in text and "chance" not in text


def test_feasibility_low_evidence_gate(conn: Any) -> None:
    out = _feas(conn, 5)
    assert out["status"] == "LOW_EVIDENCE" and out["low_evidence"] is True
    assert out["reached_target"]["frequency"] is None and out["loss"]["frequency"] is None  # counts only
    assert out["reached_target"]["display"].endswith("overlapping windows")
    assert "LOW EVIDENCE" in out["low_evidence_note"]


def test_feasibility_refuses_short_series(conn: Any) -> None:
    _short_scheme(conn)
    out = _feas(conn, 1, iid="mf:990001")
    assert out["status"] == "REFUSED" and out["refusal"]["value"] is None


def test_feasibility_needs_a_nav_series(conn: Any) -> None:
    with pytest.raises(an.AnalysisError) as e:
        _feas(conn, 1, iid=FD)
    assert e.value.status == 422


# ----------------------------------------------------------------------------------------- forecast


def test_forecast_baseline_and_validation(conn: Any) -> None:
    out = an.forecast(conn, as_of=AS_OF, instrument_id=SHORT_DUR, horizon_days=182)
    _no_floats(out)
    assert out["status"] == "OK" and out["fixture"] is True
    assert out["label"] == "scenario range, not a forecast"
    assert out["promotion"]["status"] == "baseline retained"
    sr = out["scenario_range"]
    assert sr["model_id"] == "B1_EMPIRICAL_OVERLAPPING" and len(sr["quantiles"]) == 7
    rets = [Decimal(q["return"]["value"]) for q in sr["quantiles"]]
    assert rets == sorted(rets)
    assert out["baseline_comparator"]["model_id"] == "B3_ZERO_DRIFT"
    assert out["unreliable_when"]
    v = out["validation"]
    assert v["origins"] >= 10 and v["status"] == "ok"
    assert v["calibration_status"] in {"calibration_unknown", "calibrated", "miscalibrated"}
    assert Decimal(v["coverage"]["value"]) == Decimal(v["inside"]) / Decimal(v["n"])
    assert Decimal(v["mean_pinball"]["value"]) > 0
    assert an.forecast(conn, as_of=AS_OF, instrument_id=SHORT_DUR, horizon_days=182)["run"] == out["run"]


def test_forecast_refuses_when_history_is_short_for_horizon(conn: Any) -> None:
    out = an.forecast(conn, as_of=AS_OF, instrument_id=SHORT_DUR, horizon_days=3650)
    assert out["status"] == "REFUSED" and out["refusal"]["code"] == "INSUFFICIENT_HISTORY"
    assert "scenario_range" not in out


# ----------------------------------------------------------------------------------------- risk


def _short_scheme(conn: Any) -> None:
    """A FIXTURE scheme with ~1.2 years of history, copied from FIXTURE fund C's last 300 NAVs."""
    with write_tx(conn):
        conn.execute(
            "INSERT INTO instruments(instrument_id, kind, name, amfi_code, origin, created_at)"
            " VALUES ('mf:990001', 'mf_scheme', 'FIXTURE Short-History Equity Fund', '990001', 'fixture', ?)",
            (NOW.isoformat(),),
        )
        conn.execute(
            "INSERT INTO mf_schemes(instrument_id, amc, category_raw, plan, exit_load_json)"
            " VALUES ('mf:990001', 'FIXTURE AMC', 'Equity Scheme - Large Cap Fund', 'direct', NULL)"
        )
    rows = conn.execute(
        "SELECT observation_date, value FROM observations WHERE series_id='nav:900003' ORDER BY observation_date"
    ).fetchall()[-300:]
    for r in rows:
        upsert_observation(conn, ObservationRow(
            series_id="nav:990001", kind="nav", value=r["value"], unit="INR/unit", currency="INR",
            observation_date=r["observation_date"], retrieved_at=NOW.isoformat(), source_id="fixture",
            source_url=fixtures.FIXTURE_URL, quality_status="fixture", raw_sha256="f" * 64, convention="synthetic NAV",
        ))  # fmt: skip


def test_risk_metrics_with_provenance(conn: Any) -> None:
    out = an.risk(conn, as_of=AS_OF, instrument_id=EQUITY)
    _no_floats(out)
    m = out["metrics"]
    assert out["fixture"] is True
    for key in ("volatility", "max_drawdown", "var_95", "cvar_95"):
        assert m[key]["formula_id"] and m[key]["hash"] and m[key]["freshness"] == "FIXTURE", key
    dd = m["max_drawdown"]
    assert dd["peak_date"] < dd["trough_date"]
    assert Decimal(m["var_95"]["value_inr"]["value"]) == (Decimal(m["var_95"]["value"]) * Decimal("100000")).quantize(
        Decimal("0.01")
    )
    assert m["sharpe"]["status"] == "refused" and m["sharpe"]["value"] is None


def test_gated_metrics_refuse_with_typed_reason(conn: Any) -> None:
    liquid = an.risk(conn, as_of=AS_OF, instrument_id=LIQUID)["metrics"]
    assert liquid["volatility"] == {**liquid["volatility"], "status": "refused", "code": "REFUSED_SMOOTHED_NAV",
                                    "value": None}  # fmt: skip
    assert liquid["sharpe"]["code"] == "REFUSED_SMOOTHED_NAV"
    _short_scheme(conn)
    short = an.risk(conn, as_of=AS_OF, instrument_id="mf:990001")["metrics"]
    for key in ("var_95", "cvar_95", "var_99", "cvar_99"):
        assert short[key]["status"] == "refused" and short[key]["code"] == "INSUFFICIENT_HISTORY", key
        assert short[key]["value"] is None and "insufficient history" in short[key]["reason"]
    assert short["volatility"]["value"] is not None  # 299 daily returns clear the 60-return gate
    assert "MDD_WITHIN_AVAILABLE_HISTORY" in short["max_drawdown"]["limitations"]


def test_risk_needs_a_nav_series(conn: Any) -> None:
    with pytest.raises(an.AnalysisError) as e:
        an.risk(conn, as_of=AS_OF, instrument_id=TBILL)
    assert e.value.status == 422


# ----------------------------------------------------------------------------------------- source conflicts


def _conflict(conn: Any, code: str = "900002") -> None:
    """A second FIXTURE source reporting a different NAV for a date the first source already covers."""
    d, v = conn.execute(
        "SELECT observation_date, value FROM observations WHERE series_id=? ORDER BY observation_date DESC LIMIT 1",
        (f"nav:{code}",),
    ).fetchone()
    upsert_observation(conn, ObservationRow(
        series_id=f"nav:{code}", kind="nav", value=str(Decimal(v) + Decimal("0.0100")), unit="INR/unit",
        currency="INR", observation_date=d, retrieved_at=NOW.isoformat(), source_id="fixture.second",
        source_url=fixtures.FIXTURE_URL, quality_status="fixture", raw_sha256="e" * 64, convention="synthetic NAV",
    ))  # fmt: skip


def test_conflicted_series_is_never_evaluated(conn: Any) -> None:
    _conflict(conn)
    out = _compare(conn, [SHORT_DUR, LIQUID])
    row = out["rows"][0]
    assert row["evaluable"] is False and row["eligibility_reasons"][0].startswith("SOURCE_CONFLICT")
    assert "net_proceeds" not in row and out["order"] == [LIQUID]
    uni = disc.build_universe(conn, amount=Decimal("100000"), as_of=AS_OF, withdrawal=AS_OF + timedelta(days=182),
                              ruleset=RULES, profile=None, excluded_kinds=())  # fmt: skip
    ref = next(b for b in uni.built if b.candidate.instrument_id == SHORT_DUR)
    one = an.build_one(conn, SHORT_DUR, amount=Decimal("100000"), as_of=AS_OF, withdrawal=AS_OF + timedelta(days=182),
                       ruleset=RULES, profile=None)  # fmt: skip
    assert one.built == ref
    for call in (
        lambda: an.risk(conn, as_of=AS_OF, instrument_id=SHORT_DUR),
        lambda: an.forecast(conn, as_of=AS_OF, instrument_id=SHORT_DUR, horizon_days=91),
        lambda: _feas(conn, 1, iid=SHORT_DUR),
    ):
        with pytest.raises(an.AnalysisError) as e:
            call()
        assert e.value.status == 409 and e.value.code == "SOURCE_CONFLICT"
