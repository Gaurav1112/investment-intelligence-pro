"""Bond manual entry → discovery / compare / scenario. Every bond here is a FIXTURE (synthetic ISINs, invented quotes
on https://fixture.invalid pages) — not market data."""

import json
import typing
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from iip.engine.ranking import CREDIT_SCALE
from iip.rules.loader import load_tax_rules
from iip.services import analysis as an
from iip.services import bonds, fixtures, instruments
from iip.services import discovery as disc
from iip.services.explain import contract_errors, iter_explained
from iip.store.db import connect, migrate

AS_OF = date(2026, 10, 15)
NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
RULES = load_tax_rules()
CITE = {"url": "https://fixture.invalid/bond-page", "as_of": "2026-10-14"}
GSEC_ISIN, SDL_ISIN, CORP_ISIN, CORP2_ISIN = "INFIXGSEC016", "INFIXSDL0013", "INFIXCORP018", "INFIXCORP026"


def gsec_body(**kw: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "gsec", "issuer": "Government of India", "isin": GSEC_ISIN, "coupon_rate": "0.071",
        "frequency": 2, "issue_date": "2022-04-15", "maturity": "2027-04-15", "face_value": "100",
        "clean_price": "99.80", "quote_date": "2026-10-14", "transaction_spread": "0", "citation": CITE,
    }  # fmt: skip
    body.update(kw)
    return body


def corp_body(**kw: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "issuer": "FIXTURE Finance Ltd", "isin": CORP_ISIN, "coupon_rate": "0.09", "frequency": 1,
        "issue_date": "2024-10-15", "maturity": "2029-10-15", "face_value": "10000", "clean_price": "102.50",
        "quote_date": "2026-10-14", "transaction_spread": "0.001", "citation": CITE, "rating": "AAA",
        "rating_agency": "CRISIL", "rating_date": "2026-06-01",
        "rating_citation": {"url": "https://fixture.invalid/rating-rationale", "as_of": "2026-06-01"},
        "listed": True, "secured": True, "record_date_days": 15,
        "call_schedule": [{"call_date": "2027-10-15", "call_price": "100"}],
    }  # fmt: skip
    body.update(kw)
    return body


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[Any]:
    c = connect(tmp_path / "x.db")
    migrate(c, NOW.isoformat())
    fixtures.seed(c, as_of=AS_OF, now=NOW)
    instruments.add_gsec(c, instruments.GsecIn.model_validate(gsec_body()), NOW)
    instruments.add_gsec(
        c,
        instruments.GsecIn.model_validate(
            gsec_body(kind="sdl", issuer="State of Fixtureland", isin=SDL_ISIN, coupon_rate="0.0745",
                      issue_date="2021-11-20", maturity="2031-11-20", clean_price=None, ytm="0.0712")
        ),
        NOW,
    )  # fmt: skip
    instruments.add_corporate_bond(c, instruments.CorporateBondIn.model_validate(corp_body()), NOW)
    yield c
    c.close()


GSEC, SDL, CORP = f"gsec:{GSEC_ISIN}", f"sdl:{SDL_ISIN}", f"corp_bond:{CORP_ISIN}"


# ------------------------------------------------------------------ manual entry


def test_entry_stores_terms_quote_and_citation(conn: Any) -> None:
    inst = conn.execute("SELECT * FROM instruments WHERE instrument_id=?", (CORP,)).fetchone()
    assert inst["kind"] == "corp_bond" and inst["origin"] == "manual" and inst["isin"] == CORP_ISIN
    terms = conn.execute("SELECT * FROM bond_terms WHERE instrument_id=?", (CORP,)).fetchone()
    assert terms["daycount"] == "ACT/ACT-SEBI" and terms["credit_rating"] == "AAA"
    assert terms["rating_agency"] == "CRISIL"
    assert json.loads(terms["call_schedule_json"]) == [{"call_date": "2027-10-15", "call_price": "100"}]
    obs = conn.execute("SELECT * FROM observations WHERE series_id=?", (f"bondprice:{CORP}",)).fetchone()
    assert obs["value"] == "102.50" and obs["source_url"] == CITE["url"] and obs["quality_status"] == "manual"
    assert obs["source_id"] == "bond.quote"
    sdl = conn.execute("SELECT * FROM observations WHERE series_id=?", (f"bondyield:{SDL}",)).fetchone()
    assert sdl["kind"] == "yield" and "semiannual" in sdl["convention"]
    assert conn.execute("SELECT daycount FROM bond_terms WHERE instrument_id=?", (GSEC,)).fetchone()[0] == "30E/360"


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"isin": "INFIXGSEC017"}, "ISIN_BAD_CHECKSUM"),
        ({"isin": "in-not-valid"}, "ISIN_BAD_FORMAT"),
        ({"ytm": "0.07"}, "exactly one"),
        ({"clean_price": None}, "exactly one"),
        ({"coupon_rate": 0.071}, "decimals as strings"),
        ({"frequency": 1}, "frequency"),
        ({"maturity": "2021-01-01"}, "maturity must be after"),
        ({"citation": {"url": "http://insecure.example", "as_of": "2026-10-14"}}, "url"),
    ],
)
def test_gsec_validation(change: dict[str, Any], fragment: str) -> None:
    with pytest.raises(ValidationError) as e:
        instruments.GsecIn.model_validate(gsec_body(**change))
    assert fragment in str(e.value)


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"rating": "SOVEREIGN"}, "rating"),
        ({"rating_citation": None}, "rating_citation"),
        ({"clean_price": None, "ytm": "0.08"}, "ytm_compounding is required"),
        ({"ytm_compounding": "annual"}, "applies only to a ytm"),
        ({"call_schedule": [{"call_date": "2030-01-01", "call_price": "100"}]}, "between issue_date and maturity"),
        ({"rating_agency": "Moody's"}, "rating_agency"),
        ({"record_date_days": None}, "record_date_days"),
    ],
)
def test_corporate_validation(change: dict[str, Any], fragment: str) -> None:
    with pytest.raises(ValidationError) as e:
        instruments.CorporateBondIn.model_validate(corp_body(**change))
    assert fragment in str(e.value)


def test_rating_literal_matches_the_ranking_scale() -> None:
    assert typing.get_args(instruments.CorporateRating) == instruments.CORPORATE_RATINGS
    assert set(instruments.CORPORATE_RATINGS) < set(CREDIT_SCALE)


def test_new_quote_for_the_same_date_replaces_the_other_measure(conn: Any) -> None:
    instruments.add_gsec(conn, instruments.GsecIn.model_validate(gsec_body(clean_price=None, ytm="0.0752")), NOW)
    rows = conn.execute(
        "SELECT series_id FROM observations WHERE series_id IN (?, ?) AND superseded_by IS NULL",
        (f"bondprice:{GSEC}", f"bondyield:{GSEC}"),
    ).fetchall()
    assert [r[0] for r in rows] == [f"bondyield:{GSEC}"]
    row, problem = bonds.bond_quote(conn, GSEC, AS_OF)
    assert problem is None and row is not None and row["value"] == "0.0752"


def test_delete_removes_quotes_and_meta(conn: Any) -> None:
    assert instruments.delete_instrument(conn, CORP)
    assert conn.execute("SELECT COUNT(*) FROM observations WHERE series_id LIKE ?", (f"%{CORP}",)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM settings WHERE key=?", (f"bond.meta:{CORP}",)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM bond_terms WHERE instrument_id=?", (CORP,)).fetchone()[0] == 0


def test_list_bonds_shows_quote_freshness_and_rating(conn: Any) -> None:
    items = {i["instrument_id"]: i for i in bonds.list_bonds(conn, AS_OF)}
    assert set(items) == {GSEC, SDL, CORP}
    c = items[CORP]
    assert c["quote"]["kind"] == "clean_price" and c["quote"]["value"] == "102.50"
    assert c["quote"]["age_days"] == 1 and c["quote"]["freshness"] == "MANUAL"
    assert c["rating"] == {"rating": "AAA", "agency": "CRISIL", "rating_date": "2026-06-01", "age_days": 136,
                           "stale": False, "citation_url": "https://fixture.invalid/rating-rationale"}  # fmt: skip
    assert items[GSEC]["rating"] is None and items[SDL]["quote"]["kind"] == "ytm"
    later = {i["instrument_id"]: i for i in bonds.list_bonds(conn, AS_OF + timedelta(days=10))}
    assert later[CORP]["quote"]["freshness"] == "STALE"


# ------------------------------------------------------------------ discovery / analysis parity


@pytest.mark.parametrize("withdrawal", [AS_OF + timedelta(days=182), date(2029, 11, 1), date(2032, 1, 1)])
def test_build_one_matches_build_universe_for_bonds(conn: Any, withdrawal: date) -> None:
    amount = Decimal("500000")
    uni = disc.build_universe(conn, amount=amount, as_of=AS_OF, withdrawal=withdrawal, ruleset=RULES, profile=None,
                              excluded_kinds=())  # fmt: skip
    ids = {b.candidate.instrument_id for b in uni.built}
    assert {GSEC, SDL, CORP} <= ids
    for b in uni.built:
        iid = b.candidate.instrument_id
        one = an.build_one(conn, iid, amount=amount, as_of=AS_OF, withdrawal=withdrawal, ruleset=RULES, profile=None)
        assert one.built == b, iid
        assert one.prov == {**uni.sources[iid], "kind": one.kind}


def test_universe_tiers_and_modes(conn: Any) -> None:
    uni = disc.build_universe(conn, amount=Decimal("500000"), as_of=AS_OF, withdrawal=date(2027, 4, 15),
                              ruleset=RULES, profile=None, excluded_kinds=())  # fmt: skip
    by = {b.candidate.instrument_id: b for b in uni.built}
    assert by[GSEC].candidate.tier.name == "T1" and by[GSEC].candidate.outcome.is_contractual
    assert by[SDL].candidate.tier.name == "T3" and not by[SDL].candidate.outcome.is_contractual  # sold early
    assert by[CORP].candidate.tier.name == "T3" and "EARLY_EXIT_STRESS_SCENARIOS" in by[CORP].candidate.flags
    assert uni.sources[GSEC]["source_id"] == "bond.quote" and uni.sources[GSEC]["freshness"] == "MANUAL"


def test_excluded_kinds_drop_bonds(conn: Any) -> None:
    uni = disc.build_universe(conn, amount=Decimal("500000"), as_of=AS_OF, withdrawal=date(2027, 4, 15),
                              ruleset=RULES, profile=None, excluded_kinds=("gsec", "corp_bond"))  # fmt: skip
    ids = {b.candidate.instrument_id for b in uni.built}
    assert SDL in ids and GSEC not in ids and CORP not in ids


def test_stale_quote_in_the_universe_is_excluded_with_reason(conn: Any) -> None:
    later = AS_OF + timedelta(days=9)
    uni = disc.build_universe(conn, amount=Decimal("500000"), as_of=later, withdrawal=date(2027, 4, 15),
                              ruleset=RULES, profile=None, excluded_kinds=())  # fmt: skip
    by = {b.candidate.instrument_id: b for b in uni.built}
    assert by[GSEC].ineligible_reasons[0].startswith("STALE_DATA")
    assert uni.sources[GSEC]["freshness"] == "STALE"


def test_stale_rating_in_the_universe_is_excluded_with_reason(conn: Any) -> None:
    instruments.add_corporate_bond(
        conn, instruments.CorporateBondIn.model_validate(corp_body(isin=CORP2_ISIN, rating_date="2025-09-30")), NOW
    )
    one = an.build_one(conn, f"corp_bond:{CORP2_ISIN}", amount=Decimal("500000"), as_of=AS_OF,
                       withdrawal=date(2029, 11, 1), ruleset=RULES, profile=None)  # fmt: skip
    assert one.built is not None and one.built.ineligible_reasons[0].startswith("STALE_RATING")


def test_future_dated_only_quote_is_look_ahead(conn: Any) -> None:
    one = an.build_one(conn, GSEC, amount=Decimal("100000"), as_of=date(2026, 10, 10),
                       withdrawal=date(2027, 4, 15), ruleset=RULES, profile=None)  # fmt: skip
    assert one.built is not None and one.built.ineligible_reasons[0].startswith("LOOK_AHEAD")


def test_bond_without_terms_is_not_evaluable(conn: Any) -> None:
    conn.execute("DELETE FROM bond_terms WHERE instrument_id=?", (GSEC,))
    one = an.build_one(conn, GSEC, amount=Decimal("100000"), as_of=AS_OF, withdrawal=date(2027, 4, 15),
                       ruleset=RULES, profile=None)  # fmt: skip
    assert one.built is None and one.not_evaluable[0].startswith("MISSING_DATA")


# ------------------------------------------------------------------ discovery and compare end to end


def test_discover_includes_bonds_with_explained_outcomes(conn: Any) -> None:
    from iip.services import profile as profile_svc

    status = profile_svc.evaluate(profile_svc.load(conn), AS_OF)
    out = disc.discover(conn, status, as_of=AS_OF, ruleset=RULES, allow_fixtures=True)
    rows = {r["instrument_id"]: r for r in out["ranked"] + out["excluded"]}
    assert {GSEC, SDL, CORP} <= set(rows)
    g = rows[GSEC]
    assert g["kind"] == "gsec" and g["tier"] == "T1" and g["contractual"]
    assert g["outcome"]["q50"]["formula_id"] == "CAND_BOND_HTM@1"
    for e in iter_explained(out):
        assert not contract_errors(e), e["id"]
    lines = " ".join(g["outcome"]["q50"]["inputs"])
    assert "ytm: 7.5" in lines and "path_maturity: gross ₹" in lines  # display-formatted, never raw precision


def test_compare_includes_bonds_and_reconciles(conn: Any) -> None:
    out = an.compare(conn, as_of=AS_OF, ruleset=RULES, instrument_ids=[GSEC, CORP, SDL, "fd:fixture-bank:180d"],
                     amount=Decimal("500000"), withdrawal=date(2029, 11, 1))  # fmt: skip
    rows = {r["instrument_id"]: r for r in out["rows"]}
    for iid in (GSEC, CORP, SDL):
        assert rows[iid]["evaluable"], (iid, rows[iid]["eligibility_reasons"])
        assert "UNSUPPORTED_KIND" not in " ".join(rows[iid]["eligibility_reasons"])
        assert rows[iid]["exit_cost"]["formula_id"] == f"EXIT_COST_{iid.split(':')[0].upper()}@1"
    corp = rows[CORP]
    assert corp["contractual"] and corp["tier"] == "T2" and "CALLABLE_WORST_PATH_USED" in corp["flags"]
    assert corp["costs"]["exit_load"]["q50"]["value"] == "0.00"  # gross is already after the purchase spread
    assert rows[SDL]["tier"] == "T3"  # matures 2031, after the 2029 withdrawal → early exit band
    assert set(out["order"]) >= {GSEC, CORP, SDL}


def test_scenario_on_a_bond_explains_inapplicable_shocks_and_reprices_an_early_exit(conn: Any) -> None:
    out = an.scenario(conn, as_of=AS_OF, ruleset=RULES, instrument_id=CORP, amount=Decimal("500000"),
                      withdrawal=date(2029, 11, 1), shocks={"rate_bp": 100, "exit_before_maturity_days": 400,
                                                            "reinvestment_rate": Decimal("0.06")})  # fmt: skip
    res = {r["shock"]: r for r in out["results"]}
    assert res["rate_bp"]["status"] == "not_applicable" and "contractual" in res["rate_bp"]["reason"]
    assert res["reinvestment_rate"]["status"] == "not_applicable"
    ex = res["exit_before_maturity_days"]
    assert ex["status"] == "applied" and ex["scenario_id"] == "SCN_BOND_EARLY_EXIT@1"
