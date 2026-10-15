"""End-to-end Discovery under the Supervisor. All instrument data here is FIXTURE (synthetic), by design."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from iip.rules.loader import load_tax_rules
from iip.services import discovery as disc
from iip.services import fixtures
from iip.services.profile import Profile, evaluate
from iip.store.db import connect, migrate
from iip.supervisor import compliance

AS_OF = date(2026, 10, 15)
NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
RULES = load_tax_rules()


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[object]:
    c = connect(tmp_path / "x.db")
    migrate(c, NOW.isoformat())
    fixtures.seed(c, as_of=AS_OF, now=NOW)
    yield c
    c.close()


def profile(**kw: object) -> Profile:
    base = {
        "amount": "500000",
        "withdrawal_date": "2027-04-15",
        "objective": "A_capital_preservation",
        "loss_acceptable": False,
        "early_need": "possible",
        "max_days_to_cash": 7,
    }
    base.update(kw)
    return Profile.model_validate(base)


def go(conn, p: Profile, **kw: object) -> dict:  # type: ignore[no-untyped-def,type-arg]
    return disc.discover(conn, evaluate(p, AS_OF), as_of=AS_OF, ruleset=RULES, **kw)  # type: ignore[arg-type]


def test_personalised_mode_refuses_to_rank_fixtures_by_default(conn) -> None:  # type: ignore[no-untyped-def]
    out = go(conn, profile())
    assert out["mode"] == "PERSONALISED"
    assert out["status"] == "NO_SUITABLE_CANDIDATE"
    assert out["ranked"] == []
    assert all(any(c.startswith("FIXTURE_NOT_MARKET_DATA") for c in r["exclusion_codes"]) for r in out["excluded"])
    assert out["message"] == "No suitable candidate found under the current constraints."


def test_preservation_ranking_with_fixtures_opted_in(conn) -> None:  # type: ignore[no-untyped-def]
    out = go(conn, profile(), allow_fixtures=True)
    assert out["status"] == "RANKED" and out["contains_fixtures"]
    ranked = [r["instrument_id"] for r in out["ranked"]]
    excluded = {r["instrument_id"]: r for r in out["excluded"]}
    # Equity fund has a material frequency of loss at 6 months → excluded for capital preservation.
    assert "mf:900003" in excluded
    assert any("LOSS_FREQUENCY" in c or "LOWER_BAND" in c for c in excluded["mf:900003"]["exclusion_codes"])
    # The FD (180 days) matures before withdrawal; T-bill too. T1 ranks before T2/T3.
    tiers = [r["tier"] for r in out["ranked"]]
    assert tiers == sorted(tiers)
    assert ranked and out["ranked"][0]["tier"] == "T1"
    # Every displayed outcome number is explainable with formula, sources and version.
    for r in out["ranked"]:
        for k in ("q05", "q50", "q95"):
            e = r["outcome"][k]
            assert e["formula"] and e["engine_version"] and e["hash"] and e["display"].startswith("₹")
            assert e["freshness"] == "FIXTURE"


def test_report_cites_only_engine_facts_and_passes_compliance(conn) -> None:  # type: ignore[no-untyped-def]
    out = go(conn, profile(), allow_fixtures=True)
    report = out["report"]
    assert report and report["writer"] == "template"
    text = report["narrative"] + "\n".join(report["disclosures"])
    assert compliance.blocked(text) == []
    rules = compliance.load_rules()
    for key in ("footer", "ranking", "projection", "past_performance"):
        assert rules.required[key] in report["disclosures"]
    assert out["criteria"] and out["policy"]["version"] == "ranking_policy@1.0.0"


def test_disagreement_between_ranking_and_skeptic_is_surfaced(conn) -> None:  # type: ignore[no-untyped-def]
    out = go(conn, profile(), allow_fixtures=True)
    # The first-ordered T-bill uses an NV tax rule and a withdrawal beyond legislated coverage → skeptic challenges.
    assert out["conflicts"], out["report"]
    c = out["conflicts"][0]
    assert c["supporting"][0].startswith("quant:") and c["challenging"]


def test_missing_suitability_inputs_give_exploration_not_ranking(conn) -> None:  # type: ignore[no-untyped-def]
    out = go(conn, Profile(), allow_fixtures=True)
    assert out["mode"] == "EXPLORATION" and out["status"] == "EXPLORATION"
    assert all(r["rank"] is None for r in out["ranked"])
    assert out["context"]["illustrative"] is True and out["context"]["amount"] == "₹1,00,000.00"


def test_abstains_when_tax_rules_missing(conn) -> None:  # type: ignore[no-untyped-def]
    out = disc.discover(conn, evaluate(profile(), AS_OF), as_of=AS_OF, ruleset=None, allow_fixtures=True)
    assert out["status"] == "ABSTAIN"
    assert any("Tax rule set" in r for r in out["abstain_reasons"])
    assert out["ranked"] == [] and out["report"] is None


def test_abstains_when_universe_empty(tmp_path: Path) -> None:
    c = connect(tmp_path / "empty.db")
    migrate(c, NOW.isoformat())
    out = disc.discover(c, evaluate(profile(), AS_OF), as_of=AS_OF, ruleset=RULES)
    assert out["status"] == "ABSTAIN"
    assert any("evaluable data" in r for r in out["abstain_reasons"])


def test_growth_objective_with_loss_budget_admits_equity(conn) -> None:  # type: ignore[no-untyped-def]
    p = profile(objective="D_growth", loss_acceptable=True, max_loss_fraction="0.30", withdrawal_date="2028-10-15")
    out = go(conn, p, allow_fixtures=True)
    assert out["status"] in {"RANKED", "NO_SUITABLE_CANDIDATE"}
    names = {r["instrument_id"] for r in out["ranked"]} | {r["instrument_id"] for r in out["excluded"]}
    assert "mf:900003" in names


def test_identical_inputs_give_identical_result_hash(conn) -> None:  # type: ignore[no-untyped-def]
    a = go(conn, profile(), allow_fixtures=True)
    b = go(conn, profile(), allow_fixtures=True)
    assert a["run"]["result_hash"] == b["run"]["result_hash"]
    run_id = disc.store_run(conn, a, NOW)
    assert (
        conn.execute("SELECT output_hash FROM runs WHERE run_id=?", (run_id,)).fetchone()[0] == a["run"]["result_hash"]
    )


def test_explanations_never_leak_internal_precision(conn) -> None:  # type: ignore[no-untyped-def]
    import re

    out = go(conn, profile(), allow_fixtures=True)
    long_decimal = re.compile(r"\d+\.\d{9,}")
    for r in out["ranked"]:
        for k in ("q05", "q50", "q95"):
            e = r["outcome"][k]
            for line in [*e["inputs"], e["substituted"], e["display"]]:
                assert not long_decimal.search(line), line


def _add_nav(conn, code: str, d: str, value: str, source: str) -> None:  # type: ignore[no-untyped-def]
    from iip.store.observations import ObservationRow, upsert_observation

    upsert_observation(conn, ObservationRow(
        series_id=f"nav:{code}", kind="nav", value=value, unit="INR_per_unit", currency="INR", observation_date=d,
        retrieved_at=NOW.isoformat(), source_id=source, source_url="https://portal.amfiindia.com/x",
        quality_status="ok", raw_sha256="a" * 64))  # fmt: skip


def test_same_date_from_two_official_sources_is_merged_when_equal(conn) -> None:  # type: ignore[no-untyped-def]
    # Live finding 2026-10-15: NAVAll and the history report both carry 14-Oct; series must not have duplicate dates.
    _add_nav(conn, "777", "2026-10-13", "100.10", "amfi.navhistory")
    _add_nav(conn, "777", "2026-10-14", "100.2", "amfi.navhistory")
    _add_nav(conn, "777", "2026-10-14", "100.20", "amfi.navall")  # same value, different precision
    dates, navs, prov = disc._nav_series(conn, "777")
    assert navs[-1] == Decimal("100.2")
    assert [d.isoformat() for d in dates] == ["2026-10-13", "2026-10-14"]
    assert prov["conflicts"] == [] and prov["source_id"] == "amfi.navall"


def test_disagreeing_official_sources_are_a_conflict_not_a_choice(conn) -> None:  # type: ignore[no-untyped-def]
    _add_nav(conn, "778", "2026-10-14", "100.20", "amfi.navhistory")
    _add_nav(conn, "778", "2026-10-14", "100.25", "amfi.navall")
    _, _, prov = disc._nav_series(conn, "778")
    assert prov["conflicts"] and "amfi.navall=100.25" in prov["conflicts"][0]
