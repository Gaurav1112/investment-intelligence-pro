"""Track 1: the formerly BLOCKED analysis outputs now return Explained values from cited inputs — and refuse, with a
typed reason, when those inputs are missing, short or stale.

Instrument data is FIXTURE (synthetic, services/fixtures.py). CPI, T-bill yields, factsheet facts and card rates are
hand-made TEST values with a test citation URL — not market data.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from iip.engine.dates import add_months
from iip.engine.deposits import fd_premature_withdrawal
from iip.engine.money import engine_context
from iip.rules.loader import load_tax_rules
from iip.services import analysis as an
from iip.services import discovery as disc
from iip.services import fixtures
from iip.services import inputs as inp
from iip.services.explain import contract_errors, iter_explained
from iip.services.profile import Profile, evaluate
from iip.store.db import connect, migrate

AS_OF = date(2026, 10, 15)
NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
RULES = load_tax_rules()
LIQUID, SHORT_DUR, EQUITY, ARB = "mf:900001", "mf:900002", "mf:900003", "mf:900004"
TBILL = f"tbill:182d:{(AS_OF + timedelta(days=180)).isoformat()}"
FD = "fd:fixture-bank:180d"
APR = date(2027, 4, 15)
CITE = "https://example.test/citation"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[Any]:
    c = connect(tmp_path / "x.db")
    migrate(c, NOW.isoformat())
    fixtures.seed(c, as_of=AS_OF, now=NOW)
    yield c
    c.close()


def _contract_ok(out: Any) -> int:
    items = list(iter_explained(out))
    assert [e for i in items for e in contract_errors(i)] == []
    return len(items)


def _facts(conn: Any, iid: str, month: str = "2026-09", **kw: Any) -> None:
    body = {"as_of_month": month, "modified_duration": "2.5", "ytm": "0.0712", "expense_ratio": "0.0035",
            "expense_ratio_kind": "TER", "lowest_rating": "AAA", "share_sovereign_cash": "0.4",
            "citation": {"url": CITE, "as_of": "2026-10-10"}}  # fmt: skip
    body.update(kw)
    inp.add_fund_facts(conn, iid, inp.FundFactsIn.model_validate(body), NOW)


def _cpi(conn: Any, base: str = "2024", month: str = "2026-09", yoy: str | None = "1.54", index: str = "104.2",
         released: str = "2026-10-12") -> None:  # fmt: skip
    inp.add_cpi_point(conn, inp.CPIPointIn.model_validate({
        "base_year": base, "month": month, "index": index, "yoy_inflation_pct": yoy,
        "citation": {"url": CITE, "as_of": released}}), NOW)  # fmt: skip


def _riskfree(conn: Any, start: date, end: date, y: str = "0.065") -> None:
    d = start
    while d <= end:
        inp.add_risk_free(conn, inp.RiskFreeIn.model_validate({"yield_fraction": y,
                                                               "citation": {"url": CITE, "as_of": d.isoformat()}}),
                          NOW)  # fmt: skip
        d += timedelta(days=7)


def _scenario(conn: Any, iid: str, shocks: dict[str, Any], **kw: Any) -> dict[str, Any]:
    return an.scenario(conn, as_of=AS_OF, ruleset=RULES, instrument_id=iid, amount=kw.get("amount"),
                       withdrawal=kw.get("withdrawal", APR), shocks=shocks)  # fmt: skip


# ----------------------------------------------------------------------------------------- inflation / real return


def test_inflation_shock_and_real_return_are_explained_when_cpi_exists(conn: Any) -> None:
    before = _scenario(conn, LIQUID, {"inflation_pct": Decimal("2")})["results"][0]
    assert before["status"] == "not_applicable" and "CPI_UNAVAILABLE" in before["reason"]
    _cpi(conn)
    out = _scenario(conn, LIQUID, {"inflation_pct": Decimal("2")})
    entry = out["results"][0]
    assert entry["status"] == "applied" and entry["scenario_id"] == "SCN_INFLATION_FISHER@1"
    assert "today's rupees" in entry["measure"] and "base 2024" in entry["measure"]
    assert entry["sources"][0]["source_id"] == "mospi.cpi" and entry["sources"][0]["url"] == CITE
    assert "INFLATION_PROJECTION_TRAILING_12M_NOT_A_FORECAST" in entry["caveats"]
    assert _contract_ok(out) > 10
    days = out["context"]["horizon_days"]
    with engine_context():
        pi_base = Decimal("1.0154") ** (Decimal(days) / Decimal(365)) - 1
        pi_shock = Decimal("1.0354") ** (Decimal(days) / Decimal(365)) - 1
    for v, w in zip(entry["values"], an.WHICH, strict=True):
        pre = Decimal(out["base"]["proceeds_before_tax"][w]["value"])
        amount = Decimal(out["context"]["amount_value"])
        with engine_context():
            nominal = pre / amount - 1
            base_real = amount * ((1 + nominal) / (1 + pi_base))
            shocked_real = amount * ((1 + nominal) / (1 + pi_shock))
        assert abs(Decimal(v["before"]["value"]) - base_real) <= Decimal("0.02")  # pre-tax ₹ is shown to paise
        assert abs(Decimal(v["after"]["value"]) - shocked_real) <= Decimal("0.02")
        assert Decimal(v["impact"]["value"]) < 0  # more inflation → less real value
        assert {s["source_id"] for s in v["impact"]["sources"]} >= {"fixture", "mospi.cpi"}


def test_compare_shows_real_return_or_a_typed_refusal(conn: Any) -> None:
    out = an.compare(conn, as_of=AS_OF, ruleset=RULES, instrument_ids=[FD, LIQUID], amount=None, withdrawal=APR)
    for r in out["rows"]:
        for w in an.WHICH:
            assert r["real_return"][w]["status"] == "refused" and r["real_return"][w]["code"] == "CPI_UNAVAILABLE"
            assert r["real_return"][w]["value"] is None
    _cpi(conn)
    out = an.compare(conn, as_of=AS_OF, ruleset=RULES, instrument_ids=[FD, LIQUID], amount=None, withdrawal=APR)
    _contract_ok(out)
    fd = out["rows"][0]
    real = fd["real_return"]["q50"]
    nominal = Decimal(fd["returns"]["q50"]["absolute"]["value"])
    days = out["context"]["horizon_days"]
    with engine_context():
        pi = Decimal("1.0154") ** (Decimal(days) / Decimal(365)) - 1
        expected = (1 + nominal) / (1 + pi) - 1
    assert real["formula_id"] == "FISHER@1" and Decimal(real["value"]) == expected
    assert any(s["source_id"] == "mospi.cpi" for s in real["sources"])


def test_expired_old_base_cpi_is_refused_not_used(conn: Any) -> None:
    _cpi(conn, base="2012", month="2024-12", yoy=None, index="190.0", released="2025-01-13")
    _cpi(conn, base="2012", month="2025-12", yoy=None, index="195.0", released="2026-01-12")
    entry = _scenario(conn, LIQUID, {"inflation_pct": Decimal("1")})["results"][0]
    assert entry["status"] == "not_applicable" and entry["reason"].startswith("CPI_STALE")


# ----------------------------------------------------------------------------------------- Sharpe


def _window_start() -> date:
    return add_months(AS_OF - timedelta(days=1), -36) - timedelta(days=10)


def test_sharpe_is_explained_when_the_risk_free_series_covers_the_window(conn: Any) -> None:
    _riskfree(conn, _window_start(), AS_OF - timedelta(days=1))
    out = an.risk(conn, as_of=AS_OF, instrument_id=EQUITY)
    sh = out["metrics"]["sharpe"]
    assert "status" not in sh, sh
    assert sh["formula_id"] in ("SHARPE@1", "SHARPE_LO2002@1") and sh["unit"] == "ratio"
    assert {s["source_id"] for s in sh["sources"]} == {"fixture", "rbi.pr.tbill"}
    assert any("trailing 3 years" in i for i in sh["inputs"])
    _contract_ok(out)


def test_sharpe_refused_when_risk_free_coverage_is_short(conn: Any) -> None:
    _riskfree(conn, AS_OF - timedelta(days=365), AS_OF - timedelta(days=1))  # one year only
    sh = an.risk(conn, as_of=AS_OF, instrument_id=EQUITY)["metrics"]["sharpe"]
    assert sh["status"] == "refused" and sh["code"] == "RISK_FREE_SERIES_INSUFFICIENT" and sh["value"] is None
    assert "first uncovered" in sh["reason"]


def test_sharpe_refused_on_a_hole_in_the_series(conn: Any) -> None:
    _riskfree(conn, _window_start(), date(2025, 6, 1))
    _riskfree(conn, date(2025, 7, 1), AS_OF - timedelta(days=1))  # ~30-day hole
    sh = an.risk(conn, as_of=AS_OF, instrument_id=EQUITY)["metrics"]["sharpe"]
    assert sh["code"] == "RISK_FREE_SERIES_INSUFFICIENT"


def test_sharpe_without_any_series_and_for_smoothed_navs(conn: Any) -> None:
    assert (
        an.risk(conn, as_of=AS_OF, instrument_id=EQUITY)["metrics"]["sharpe"]["code"] == "RISK_FREE_SERIES_UNAVAILABLE"
    )
    _riskfree(conn, _window_start(), AS_OF - timedelta(days=1))
    liquid = an.risk(conn, as_of=AS_OF, instrument_id=LIQUID)["metrics"]["sharpe"]
    assert liquid["code"] == "REFUSED_SMOOTHED_NAV"  # still refused per the spec (§4.3)


# ----------------------------------------------------------------------------------------- rate / spread shocks


def test_rate_and_spread_shocks_on_a_debt_fund_use_factsheet_duration(conn: Any) -> None:
    _facts(conn, SHORT_DUR)
    out = _scenario(conn, SHORT_DUR, {"rate_bp": Decimal("100"), "spread_bp": Decimal("50")})
    rate, spread = out["results"]
    for entry in (rate, spread):
        assert entry["status"] == "applied" and entry["approximate"] is True
        assert "APPROXIMATE" in entry["measure"] and "2026-09-30" in entry["measure"]
        assert "FACTSHEET_AS_OF_2026-09-30" in entry["caveats"]
        assert entry["sources"][0]["source_id"] == "amc.factsheet"
    assert rate["scenario_id"] == "SCN_RATE_DURATION_CONVEXITY@1"
    assert spread["scenario_id"] == "SCN_SPREAD_DURATION@1"
    for entry, dy in ((rate, Decimal("0.01")), (spread, Decimal("0.005"))):
        for v in entry["values"]:
            before = Decimal(v["before"]["value"])
            assert abs(Decimal(v["impact"]["value"]) - (-Decimal("2.5") * dy * before)) <= Decimal("0.02")
            assert any(s["source_id"] == "amc.factsheet" for s in v["impact"]["sources"])
    _contract_ok(out)


def test_stale_factsheet_is_labelled_stale(conn: Any) -> None:
    _facts(conn, SHORT_DUR, month="2026-07", citation={"url": CITE, "as_of": "2026-08-10"})
    rate = _scenario(conn, SHORT_DUR, {"rate_bp": Decimal("50")})["results"][0]
    assert rate["status"] == "applied" and "STALE_DURATION" in rate["caveats"] and "STALE" in rate["measure"]
    assert any("STALE" in c for c in rate["caveats"] if c.startswith("FACTSHEET_AS_OF"))


def test_shocks_stay_not_applicable_without_facts_or_for_non_debt(conn: Any) -> None:
    assert "duration" in _scenario(conn, SHORT_DUR, {"rate_bp": Decimal("100")})["results"][0]["reason"]
    _facts(conn, ARB)
    arb = _scenario(conn, ARB, {"rate_bp": Decimal("100")})["results"][0]
    assert arb["status"] == "not_applicable" and "hybrid" in arb["reason"]
    _facts(conn, SHORT_DUR)
    tight = _scenario(conn, SHORT_DUR, {"spread_bp": Decimal("-50")})["results"][0]
    assert tight["status"] == "not_applicable" and "tightening" in tight["reason"]
    _facts(conn, LIQUID, share_sovereign_cash="1")
    gilt_like = _scenario(conn, LIQUID, {"spread_bp": Decimal("50")})["results"][0]
    assert gilt_like["status"] == "not_applicable" and "100 % sovereign" in gilt_like["reason"]


# ----------------------------------------------------------------------------------------- yield carry


def test_forecast_yield_carry_for_a_debt_fund(conn: Any) -> None:
    out = an.forecast(conn, as_of=AS_OF, instrument_id=SHORT_DUR, horizon_days=91)
    yc = out["yield_carry"]
    assert yc["status"] == "refused" and yc["code"] == "FUND_FACTS_UNAVAILABLE"
    _facts(conn, SHORT_DUR)
    out = an.forecast(conn, as_of=AS_OF, instrument_id=SHORT_DUR, horizon_days=91)
    yc = out["yield_carry"]
    assert yc["status"] == "OK" and yc["factsheet_as_of"] == "2026-09-30" and yc["factsheet_freshness"] == "FRESH"
    with engine_context():
        carry = (Decimal("0.0712") - Decimal("0.0035")) * Decimal(91) / Decimal(365)
        up_100 = carry - Decimal("2.5") * Decimal("0.01")
    assert Decimal(yc["carry"]["value"]) == carry
    grid = {row["delta_yield_bp"]: Decimal(row["return"]["value"]) for row in yc["scenarios"]}
    assert grid[0] == carry and grid[100] == up_100
    assert [r["delta_yield_bp"] for r in yc["stress_scenarios"]] and all(r["stress"] for r in yc["stress_scenarios"])
    assert "not a forecast" in yc["label"]
    _contract_ok(out)


def test_yield_carry_refused_when_stale_and_not_applicable_for_equity(conn: Any) -> None:
    _facts(conn, SHORT_DUR, month="2026-07", citation={"url": CITE, "as_of": "2026-08-10"})
    yc = an.forecast(conn, as_of=AS_OF, instrument_id=SHORT_DUR, horizon_days=91)["yield_carry"]
    assert yc["status"] == "refused" and yc["code"] == "STALE_DATA"
    eq = an.forecast(conn, as_of=AS_OF, instrument_id=EQUITY, horizon_days=91)["yield_carry"]
    assert eq["status"] == "not_applicable"


# ----------------------------------------------------------------------------------------- FD early exit


def _card_table(conn: Any, as_of: str = "2026-10-10") -> None:
    inp.add_fd_rate_table(conn, inp.FDRateTableIn.model_validate({
        "institution": "FIXTURE Bank",
        "buckets": [{"min_days": 7, "max_days": 45, "rate": "0.03"}, {"min_days": 46, "max_days": 90, "rate": "0.055"},
                    {"min_days": 91, "max_days": 179, "rate": "0.06"}],
        "citation": {"url": CITE, "as_of": as_of}}), NOW)  # fmt: skip


def test_fd_early_exit_uses_the_card_rate_for_the_tenure_run(conn: Any) -> None:
    before = _scenario(conn, FD, {"exit_before_maturity_days": 60})["results"][0]
    assert before["status"] == "not_applicable" and "card-rate table" in before["reason"]
    _card_table(conn)
    out = _scenario(conn, FD, {"exit_before_maturity_days": 60})
    entry = out["results"][0]
    assert entry["status"] == "applied" and entry["scenario_id"] == "SCN_FD_PREMATURE@1"
    expected = fd_premature_withdrawal(Decimal("100000"), Decimal("0.0700"), AS_OF, AS_OF + timedelta(days=180),
                                       AS_OF + timedelta(days=60), period_card_rate=Decimal("0.055"),
                                       penalty=Decimal("0.0100"))  # fmt: skip
    v = entry["values"][0]
    assert Decimal(v["after"]["value"]) == expected.payout_display
    assert Decimal(v["impact"]["value"]) < 0
    outputs = {q["name"]: q["value"] for q in entry["outputs"]["value"]}
    assert Decimal(outputs["effective_rate"]) == Decimal("0.0450")
    assert {s["url"] for s in v["after"]["sources"]} == {fixtures.FIXTURE_URL, CITE}  # deposit terms + card table
    _contract_ok(out)


def test_fd_early_exit_refuses_uncovered_tenure_and_stale_table(conn: Any) -> None:
    _card_table(conn)
    gap = _scenario(conn, FD, {"exit_before_maturity_days": 5})["results"][0]
    assert gap["status"] == "not_applicable" and "no bucket" in gap["reason"]
    late = _scenario(conn, FD, {"exit_before_maturity_days": 200})["results"][0]
    assert late["status"] == "not_applicable"


def test_fd_early_exit_ignores_an_old_card_table(conn: Any) -> None:
    _card_table(conn, as_of="2026-08-01")
    old = _scenario(conn, FD, {"exit_before_maturity_days": 60})["results"][0]
    assert old["status"] == "not_applicable" and "older than 30 days" in old["reason"]


# ----------------------------------------------------------------------------------------- RT-23 credit floor


def _discover(conn: Any, **kw: Any) -> dict[str, Any]:
    p = Profile.model_validate({"amount": "500000", "withdrawal_date": "2027-04-15",
                                "objective": "A_capital_preservation", "loss_acceptable": False,
                                "early_need": "possible", "max_days_to_cash": 7, **kw})  # fmt: skip
    return disc.discover(conn, evaluate(p, AS_OF), as_of=AS_OF, ruleset=RULES, allow_fixtures=True)


def _codes(out: dict[str, Any], iid: str) -> list[str]:
    for r in out["excluded"]:
        if r["instrument_id"] == iid:
            return list(r["exclusion_codes"])
    return []


def test_debt_fund_without_facts_is_excluded_only_when_a_credit_floor_is_set(conn: Any) -> None:
    no_floor = _discover(conn)
    assert LIQUID in [r["instrument_id"] for r in no_floor["ranked"]]
    assert all("CREDIT_QUALITY_UNKNOWN" not in c for r in no_floor["excluded"] for c in r["exclusion_codes"])
    floor = _discover(conn, credit_floor="AA")
    assert LIQUID not in [r["instrument_id"] for r in floor["ranked"]]
    assert "CREDIT_QUALITY_UNKNOWN" in _codes(floor, LIQUID)
    assert "CREDIT_QUALITY_UNKNOWN" not in _codes(floor, EQUITY)  # equity unaffected
    _facts(conn, LIQUID, lowest_rating="AAA")
    known = _discover(conn, credit_floor="AA")
    assert LIQUID in [r["instrument_id"] for r in known["ranked"]]
    _facts(conn, LIQUID, lowest_rating="A")  # a later entry for the same month: the latest is used
    below = _discover(conn, credit_floor="AA")
    assert "BELOW_CREDIT_FLOOR" in _codes(below, LIQUID)


def test_build_one_still_matches_build_universe_with_facts(conn: Any) -> None:
    _facts(conn, SHORT_DUR, lowest_rating="AA")
    uni = disc.build_universe(conn, amount=Decimal("250000"), as_of=AS_OF, withdrawal=APR, ruleset=RULES,
                              profile=None, excluded_kinds=())  # fmt: skip
    for b in uni.built:
        iid = b.candidate.instrument_id
        one = an.build_one(conn, iid, amount=Decimal("250000"), as_of=AS_OF, withdrawal=APR, ruleset=RULES,
                           profile=None)  # fmt: skip
        assert one.built == b, iid
    by_id = {b.candidate.instrument_id: b.candidate for b in uni.built}
    assert by_id[SHORT_DUR].credit_rating == "AA" and not by_id[SHORT_DUR].credit_quality_unknown
    assert by_id[LIQUID].credit_quality_unknown and by_id[EQUITY].credit_rating is None
    assert not by_id[EQUITY].credit_quality_unknown
