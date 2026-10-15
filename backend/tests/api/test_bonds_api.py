"""Bond entry endpoints. FIXTURE values only (synthetic ISINs, https://fixture.invalid citations)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from tests.api.test_core_api import make

CITE = {"url": "https://fixture.invalid/bond-page", "as_of": "2026-10-14"}
GSEC = {
    "kind": "gsec", "issuer": "Government of India", "isin": "INFIXGSEC016", "coupon_rate": "0.071", "frequency": 2,
    "issue_date": "2022-04-15", "maturity": "2027-04-15", "face_value": "100", "clean_price": "99.80",
    "quote_date": "2026-10-14", "citation": CITE,
}  # fmt: skip
CORP = {
    "issuer": "FIXTURE Finance Ltd", "isin": "INFIXCORP018", "coupon_rate": "0.09", "frequency": 1,
    "issue_date": "2024-10-15", "maturity": "2029-10-15", "face_value": "10000", "ytm": "0.0812",
    "ytm_compounding": "annual", "quote_date": "2026-10-14", "citation": CITE, "rating": "AA+",
    "rating_agency": "ICRA", "rating_date": "2026-06-01",
    "rating_citation": {"url": "https://fixture.invalid/rating", "as_of": "2026-06-01"}, "listed": True,
    "secured": False, "record_date_days": 15, "call_schedule": [],
}  # fmt: skip


@pytest.fixture
def dev(tmp_path: Path) -> Iterator[tuple[TestClient, dict[str, str]]]:
    c, h = make(tmp_path, "dev")
    yield c, h
    c.__exit__(None, None, None)


def test_bond_entry_list_and_delete(dev: tuple[TestClient, dict[str, str]]) -> None:
    c, h = dev
    r = c.post("/api/instruments/gsec", json=GSEC, headers=h)
    assert r.status_code == 200 and r.json()["instrument_id"] == "gsec:INFIXGSEC016"
    r = c.post("/api/instruments/corp-bond", json=CORP, headers=h)
    assert r.status_code == 200 and r.json()["instrument_id"] == "corp_bond:INFIXCORP018"
    listed = c.get("/api/bonds").json()
    assert listed["quote_stale_after_days"] == 7 and listed["rating_stale_after_days"] == 365
    items = {i["instrument_id"]: i for i in listed["items"]}
    assert items["corp_bond:INFIXCORP018"]["rating"]["rating"] == "AA+"
    assert items["corp_bond:INFIXCORP018"]["quote"]["kind"] == "ytm"
    assert items["gsec:INFIXGSEC016"]["quote"]["freshness"] == "MANUAL"
    assert c.get("/api/instruments?kind=gsec").json()["items"][0]["origin"] == "manual"
    json_h = {**h, "Content-Type": "application/json"}  # the CSRF layer requires a JSON content type on DELETE
    assert c.delete("/api/instruments/gsec:INFIXGSEC016", headers=json_h).status_code == 200
    assert {i["instrument_id"] for i in c.get("/api/bonds").json()["items"]} == {"corp_bond:INFIXCORP018"}


@pytest.mark.parametrize(
    ("path", "body", "loc"),
    [
        ("/api/instruments/gsec", {**GSEC, "isin": "INFIXGSEC017"}, ["body", "isin"]),
        ("/api/instruments/gsec", {**GSEC, "clean_price": 99.8}, ["body", "clean_price"]),
        ("/api/instruments/gsec", {**GSEC, "citation": {"url": "http://x.example", "as_of": "2026-10-14"}},
         ["body", "citation", "url"]),
        ("/api/instruments/corp-bond", {k: v for k, v in CORP.items() if k != "rating"}, ["body", "rating"]),
        ("/api/instruments/corp-bond", {**CORP, "rating_date": "not-a-date"}, ["body", "rating_date"]),
    ],
)  # fmt: skip
def test_bond_entry_rejections_are_422_with_field_paths(
    dev: tuple[TestClient, dict[str, str]], path: str, body: dict[str, Any], loc: list[str]
) -> None:
    c, h = dev
    r = c.post(path, json=body, headers=h)
    assert r.status_code == 422
    assert loc in [d["loc"] for d in r.json()["detail"]]


def test_junk_bodies_never_500(dev: tuple[TestClient, dict[str, str]]) -> None:
    c, h = dev
    for path in ("/api/instruments/gsec", "/api/instruments/corp-bond"):
        for junk in ({}, {"isin": 1}, {"call_schedule": "x"}, {**CORP, "call_schedule": [{"call_date": 3}]}):
            assert c.post(path, json=junk, headers=h).status_code == 422


def test_bond_endpoints_need_csrf(dev: tuple[TestClient, dict[str, str]]) -> None:
    c, h = dev
    r = c.post("/api/instruments/gsec", json=GSEC, headers={"Origin": h["Origin"]})
    assert r.status_code in (401, 403)
