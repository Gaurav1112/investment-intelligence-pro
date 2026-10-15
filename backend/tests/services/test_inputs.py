"""services.inputs: cited CPI points, the 91-day T-bill series, factsheet facts and FD card-rate tables.

Every number here is a hand-made TEST value with a test citation URL — not market data.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from iip.services import fixtures
from iip.services import inputs as inp
from iip.services.instruments import Citation
from iip.store.db import connect, migrate

AS_OF = date(2026, 10, 15)
NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
CITE = "https://example.test/citation"
SHORT_DUR, EQUITY, TBILL = "mf:900002", "mf:900003", "tbill:182d:2027-04-13"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[Any]:
    c = connect(tmp_path / "x.db")
    migrate(c, NOW.isoformat())
    fixtures.seed(c, as_of=AS_OF, now=NOW)
    yield c
    c.close()


def cite(d: date, note: str = "") -> Citation:
    return Citation(url=CITE, as_of=d, note=note)


def cpi(base: str, month: str, index: str, *, yoy: str | None = None, released: date = date(2026, 10, 12),
        provisional: bool = False) -> inp.CPIPointIn:  # fmt: skip
    return inp.CPIPointIn(base_year=base, month=month, index=Decimal(index), provisional=provisional,  # type: ignore[arg-type]
                          yoy_inflation_pct=None if yoy is None else Decimal(yoy), citation=cite(released))  # fmt: skip


# ----------------------------------------------------------------------------------------- CPI


def test_cpi_points_are_stored_per_base_and_never_mixed(conn: Any) -> None:
    assert inp.add_cpi_point(conn, cpi("2012", "2025-12", "195.0", released=date(2026, 1, 12)), NOW) == {
        "series_id": "cpi:all-india:base2012", "outcome": "inserted"}  # fmt: skip
    inp.add_cpi_point(conn, cpi("2024", "2026-09", "104.2", yoy="1.54"), NOW)
    out = inp.list_cpi(conn)
    by_base = {s["base_year"]: s for s in out["series"]}
    assert [p["month"] for p in by_base["2012"]["points"]] == ["2025-12"]
    assert [p["month"] for p in by_base["2024"]["points"]] == ["2026-09"]
    assert by_base["2024"]["points"][0]["yoy_inflation_pct"] == "1.54"  # stored exactly as published (percent)
    assert by_base["2012"]["points"][0]["yoy_inflation_pct"] is None
    assert "never chained" in out["note"]
    points, prov = inp.cpi_points(conn)
    assert {(p.base_year, p.month) for p in points} == {("2012", date(2025, 12, 1)), ("2024", date(2026, 9, 1))}
    p24 = next(p for p in points if p.base_year == "2024")
    assert p24.yoy == Decimal("0.0154") and prov[("2024", date(2026, 9, 1))]["url"] == CITE


def test_cpi_provisional_to_final_keeps_history(conn: Any) -> None:
    assert inp.add_cpi_point(conn, cpi("2024", "2026-09", "104.2", provisional=True), NOW)["outcome"] == "inserted"
    assert inp.add_cpi_point(conn, cpi("2024", "2026-09", "104.2", provisional=True), NOW)["outcome"] == "unchanged"
    assert inp.add_cpi_point(conn, cpi("2024", "2026-09", "104.2"), NOW)["outcome"] == "corrected"
    rows = conn.execute("SELECT convention, superseded_by FROM observations WHERE series_id='cpi:all-india:base2024'"
                        " ORDER BY obs_id").fetchall()  # fmt: skip
    assert [r["convention"] for r in rows] == ["CPI_COMBINED_GENERAL_INDEX_BASE2024|PROVISIONAL",
                                               "CPI_COMBINED_GENERAL_INDEX_BASE2024"]  # fmt: skip
    assert rows[0]["superseded_by"] is not None and rows[1]["superseded_by"] is None
    assert inp.list_cpi(conn)["series"][1]["points"][0]["provisional"] is False


@pytest.mark.parametrize(
    "bad",
    [
        {"month": "2026-13"},
        {"month": "2026-09", "citation": {"url": CITE, "as_of": "2026-09-30"}},  # released before the month ended
        {"index": 101.5},  # float
        {"index": "0"},
        {"base_year": "2019"},
        {"citation": {"url": "http://insecure.test", "as_of": "2026-10-12"}},
    ],
)
def test_cpi_validation(bad: dict[str, Any]) -> None:
    body = {"base_year": "2024", "month": "2026-09", "index": "104.2", "citation": {"url": CITE, "as_of": "2026-10-12"}}
    with pytest.raises(ValidationError):
        inp.CPIPointIn.model_validate({**body, **bad})


def test_cpi_release_date_in_the_future_is_refused(conn: Any) -> None:
    with pytest.raises(inp.InputError):
        inp.add_cpi_point(conn, cpi("2024", "2026-09", "104.2", released=date(2026, 10, 20)), NOW)


# ----------------------------------------------------------------------------------------- risk-free


def test_risk_free_series_and_freshness(conn: Any) -> None:
    assert inp.list_risk_free(conn, AS_OF)["freshness"] == "UNAVAILABLE"
    body = inp.RiskFreeIn(yield_fraction=Decimal("0.057281"), citation=cite(date(2026, 10, 14)))
    assert inp.add_risk_free(conn, body, NOW)["outcome"] == "inserted"
    out = inp.list_risk_free(conn, AS_OF)
    assert out["freshness"] == "FRESH" and out["latest"]["yield_fraction"] == "0.057281"
    assert out["latest"]["auction_date"] == "2026-10-14" and out["latest"]["source_url"] == CITE
    assert inp.risk_free_freshness(date(2026, 10, 1), AS_OF) == "STALE"
    assert inp.risk_free_freshness(date(2026, 9, 1), AS_OF) == "EXPIRED"
    with pytest.raises(inp.InputError):
        inp.add_risk_free(conn, inp.RiskFreeIn(yield_fraction=Decimal("0.05"), citation=cite(date(2026, 10, 21))), NOW)
    with pytest.raises(ValidationError):
        inp.RiskFreeIn.model_validate({"yield_fraction": 0.05, "citation": {"url": CITE, "as_of": "2026-10-14"}})


# ----------------------------------------------------------------------------------------- fund facts


def facts(month: str = "2026-09", read: date = date(2026, 10, 10), **kw: Any) -> inp.FundFactsIn:
    base: dict[str, Any] = {"as_of_month": month, "modified_duration": "2.5", "ytm": "0.0712",
                            "expense_ratio": "0.0035", "expense_ratio_kind": "TER", "lowest_rating": "AA+",
                            "citation": {"url": CITE, "as_of": read.isoformat()}}  # fmt: skip
    base.update(kw)
    return inp.FundFactsIn.model_validate(base)


def test_fund_facts_history_latest_and_staleness(conn: Any) -> None:
    assert inp.list_fund_facts(conn, SHORT_DUR, AS_OF)["latest"] is None
    inp.add_fund_facts(conn, SHORT_DUR, facts("2026-07", date(2026, 8, 10)), NOW)
    out = inp.list_fund_facts(conn, SHORT_DUR, AS_OF)
    assert out["latest"]["freshness"] == "STALE" and out["latest"]["age_days"] == 76  # Jul-31 → Oct-15
    inp.add_fund_facts(conn, SHORT_DUR, facts(), NOW)
    out = inp.list_fund_facts(conn, SHORT_DUR, AS_OF)
    latest = out["latest"]
    assert latest["as_of_month"] == "2026-09" and latest["as_of_date"] == "2026-09-30"
    assert latest["freshness"] == "FRESH" and latest["age_days"] == 15 and latest["modified_duration"] == "2.5"
    assert latest["citation_url"] == CITE and latest["verified_on"] == "2026-10-10"
    assert len(out["history"]) == 2 and out["stale_after_days"] == 45
    # a correction for the same month appends; the latest entry is used
    inp.add_fund_facts(conn, SHORT_DUR, facts(modified_duration="2.6"), NOW)
    assert inp.list_fund_facts(conn, SHORT_DUR, AS_OF)["latest"]["modified_duration"] == "2.6"
    assert len(inp.list_fund_facts(conn, SHORT_DUR, AS_OF)["history"]) == 3
    # exactly 45 days old is still fresh; 46 is stale
    assert inp.list_fund_facts(conn, SHORT_DUR, date(2026, 11, 14))["latest"]["freshness"] == "FRESH"
    assert inp.list_fund_facts(conn, SHORT_DUR, date(2026, 11, 15))["latest"]["freshness"] == "STALE"
    # point-in-time: an analysis dated before the factsheet month ended does not see it
    assert inp.latest_fund_facts(conn, SHORT_DUR, date(2026, 9, 29))["as_of_month"] == "2026-07"  # type: ignore[index]


def test_fund_credit_facts_feed_the_ranking(conn: Any) -> None:
    assert inp.fund_credit_facts(conn, SHORT_DUR, AS_OF) is None
    inp.add_fund_facts(conn, SHORT_DUR, facts(), NOW)
    cf = inp.fund_credit_facts(conn, SHORT_DUR, AS_OF)
    assert cf is not None and cf.lowest_rating == "AA+" and cf.as_of == date(2026, 9, 30)


@pytest.mark.parametrize(
    "bad",
    [
        {"modified_duration": None, "ytm": None, "expense_ratio": None, "expense_ratio_kind": None,
         "lowest_rating": None},  # no figure at all
        {"expense_ratio_kind": None},  # ratio without TER/BER
        {"lowest_rating": "AAA+"},
        {"ytm": 7.12},  # float
        {"ytm": "7.12"},  # percent instead of fraction
        {"share_below_aaa": "1.5"},
        {"citation": {"url": CITE, "as_of": "2026-09-15"}},  # read before the month ended
        {"as_of_month": "2026-9"},
    ],
)  # fmt: skip
def test_fund_facts_validation(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        facts(**bad)


def test_fund_facts_only_for_funds(conn: Any) -> None:
    with pytest.raises(inp.InputError) as e:
        inp.add_fund_facts(conn, TBILL, facts(), NOW)
    assert e.value.status == 422
    with pytest.raises(inp.InputError) as e:
        inp.add_fund_facts(conn, "mf:nope", facts(), NOW)
    assert e.value.status == 404


def test_short_term_rating_is_accepted_but_recorded_as_published(conn: Any) -> None:
    inp.add_fund_facts(conn, "mf:900001", facts(lowest_rating="A1+"), NOW)
    assert inp.list_fund_facts(conn, "mf:900001", AS_OF)["latest"]["lowest_rating"] == "A1+"


# ----------------------------------------------------------------------------------------- FD card rates


def table(as_of: date = date(2026, 10, 10), **kw: Any) -> inp.FDRateTableIn:
    base: dict[str, Any] = {
        "institution": "FIXTURE Bank",
        "buckets": [{"min_days": 7, "max_days": 45, "rate": "0.03"}, {"min_days": 46, "max_days": 90, "rate": "0.055"},
                    {"min_days": 91, "max_days": 364, "rate": "0.065"}],
        "citation": {"url": CITE, "as_of": as_of.isoformat()},
    }  # fmt: skip
    base.update(kw)
    return inp.FDRateTableIn.model_validate(base)


def test_fd_rate_tables(conn: Any) -> None:
    assert inp.latest_fd_rate_table(conn, "FIXTURE Bank", AS_OF) is None
    r = inp.add_fd_rate_table(conn, table(date(2026, 9, 1)), NOW)
    assert r["institution_key"] == "fixture-bank"
    inp.add_fd_rate_table(conn, table(), NOW)
    t = inp.latest_fd_rate_table(conn, "fixture bank", AS_OF)
    assert t is not None and t["as_of"] == "2026-10-10" and len(t["engine_buckets"]) == 3
    assert t["premature_rate_basis"] == "period_card"
    early = inp.latest_fd_rate_table(conn, "FIXTURE Bank", date(2026, 9, 15))  # no look-ahead
    assert early is not None and early["as_of"] == "2026-09-01"
    assert len(inp.list_fd_rate_tables(conn)["tables"]) == 2


def test_fd_rate_table_list_reports_freshness_and_the_current_table(conn: Any) -> None:
    """The UI shows a freshness badge per table; it comes from the backend (bank.fd: 30 days), never computed there."""
    inp.add_fd_rate_table(conn, table(date(2026, 9, 1)), NOW)
    inp.add_fd_rate_table(conn, table(), NOW)
    out = inp.list_fd_rate_tables(conn, AS_OF)
    assert out["as_of"] == "2026-10-15" and out["stale_after_days"] == 30
    by_date = {t["as_of"]: t for t in out["tables"]}
    assert by_date["2026-10-10"]["freshness"] == "MANUAL" and by_date["2026-10-10"]["age_days"] == 5
    assert by_date["2026-10-10"]["current"] is True
    assert by_date["2026-09-01"]["freshness"] == "STALE" and by_date["2026-09-01"]["age_days"] == 44
    assert by_date["2026-09-01"]["current"] is False  # superseded by the later table for the same bank


@pytest.mark.parametrize(
    "bad",
    [
        {"buckets": []},
        {
            "buckets": [
                {"min_days": 7, "max_days": 45, "rate": "0.03"},
                {"min_days": 40, "max_days": 90, "rate": "0.05"},
            ]
        },
        {"buckets": [{"min_days": 7, "max_days": 45, "rate": 0.03}]},
        {"premature_rate_basis": "booked"},
    ],
)
def test_fd_rate_table_validation(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        table(**bad)
