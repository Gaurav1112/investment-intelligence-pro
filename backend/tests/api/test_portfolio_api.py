"""Stage D API: portfolios, import (multipart preview → JSON apply), summary, watchlist, alerts, evidence, privacy.

Synthetic TEST instruments only (see tests/services/test_portfolio.py)."""

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from iip.api.app import create_app
from iip.api.routes import all_routers
from iip.api.settings import Settings
from iip.supervisor import compliance
from tests.services.test_portfolio import CSV_OK, FD, NOW, seed_market

ORIGIN = "http://127.0.0.1:8741"
Client = tuple[TestClient, dict[str, str], Settings]


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Client]:
    settings = Settings(env="prod", data_dir=tmp_path / "iip")
    c = TestClient(create_app(settings, routers=all_routers(), clock=lambda: NOW), base_url=ORIGIN,
                   raise_server_exceptions=False)  # fmt: skip
    with c:
        conn = c.app.app.state.iip.conn  # type: ignore[attr-defined]
        seed_market(conn)
        token = settings.token_path.read_text().strip()
        csrf = c.post("/api/session", json={"token": token}, headers={"Origin": ORIGIN}).json()["csrf"]
        yield c, {"Origin": ORIGIN, "X-IIP-CSRF": csrf}, settings


def JSON(h: dict[str, str]) -> dict[str, str]:
    return {**h, "Content-Type": "application/json"}


def new_pf(c: TestClient, h: dict[str, str], name: str = "Core", nature: str = "actual") -> str:
    r = c.post("/api/portfolios", json={"name": name, "nature": nature}, headers=h)
    assert r.status_code == 200, r.text
    return str(r.json()["portfolio_id"])


def upload(c: TestClient, h: dict[str, str], pid: str, data: bytes, name: str = "holdings.csv") -> Any:
    return c.post("/api/holdings/import", files={"file": (name, data, "text/csv")}, data={"portfolio_id": pid},
                  headers=h)  # fmt: skip


def test_portfolio_crud_and_oversell(api: Client) -> None:
    c, h, _ = api
    pid = new_pf(c, h)
    assert c.post("/api/portfolios", json={"name": "x", "nature": "both"}, headers=h).status_code == 422
    body = {
        "instrument_id": "mf:990001",
        "txn_date": "2025-01-10",
        "txn_type": "buy",
        "units": "10",
        "amount": "100.00",
    }
    assert c.post(f"/api/portfolios/{pid}/transactions", json=body, headers=h).status_code == 200
    assert c.post(f"/api/portfolios/{pid}/transactions", json={**body, "units": 10}, headers=h).status_code == 422
    sell = {**body, "txn_type": "sell", "txn_date": "2025-02-10", "units": "10.5"}
    r = c.post(f"/api/portfolios/{pid}/transactions", json=sell, headers=h)
    assert r.status_code == 422 and r.json()["code"] == "OVERSELL"
    items = c.get(f"/api/portfolios/{pid}/transactions").json()["items"]
    assert len(items) == 1
    url = f"/api/portfolios/{pid}/transactions/{items[0]['txn_id']}"
    assert c.delete(url, headers=h).status_code == 403  # the CSRF layer requires a JSON content type on DELETE
    assert c.delete(url, headers=JSON(h)).json()["status"] == "deleted"
    assert c.get("/api/portfolios/pf_missing/summary").status_code == 404
    assert [p["portfolio_id"] for p in c.get("/api/portfolios").json()["items"]] == [pid]


def test_import_preview_apply_round_trip_and_summary(api: Client) -> None:
    c, h, settings = api
    pid = new_pf(c, h)
    r = upload(c, h, pid, CSV_OK)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["applied"] is False and len(p["will_store"]) == 2 and len(p["rejected"]) == 3
    assert c.get(f"/api/portfolios/{pid}/transactions").json()["items"] == []  # preview stores nothing
    bad = c.post(f"/api/holdings/import/{p['batch_id']}/apply", json={"sha256": "f" * 64}, headers=h)
    assert bad.status_code == 409 and bad.json()["code"] == "PREVIEW_MISMATCH"
    ok = c.post(f"/api/holdings/import/{p['batch_id']}/apply", json={"sha256": p["file_sha256"]}, headers=h)
    assert ok.status_code == 200 and ok.json()["applied"] is True and ok.json()["transactions_created"] == 2
    assert list((settings.data_dir / "backups").glob("*pre-import*.sqlite3"))  # pre-change backup taken
    s = c.get(f"/api/portfolios/{pid}/summary").json()
    # 100 × 12.3456 + 50.5 × 20.0001 → 1234.56 + 1010.01
    assert s["totals"]["market_value"]["value"] == "2244.57"
    assert all(isinstance(x["share"], str) for x in s["allocation"]["by_kind"]["items"])
    again = c.post(f"/api/holdings/import/{p['batch_id']}/apply", json={"sha256": p["file_sha256"]}, headers=h)
    assert again.status_code == 409


@pytest.mark.parametrize(
    ("data", "name", "status", "code"),
    [
        ("instrument_name,units\r\nTEST,1\r\n".encode("utf-16"), "u16.csv", 422, "ENCODING_NOT_UTF8"),
        (b"PK\x03\x04junk", "x.csv", 415, "TYPE_MISMATCH"),
        (b"instrument_name,units\r\n" + b"a," * 70 + b"\r\n", "wide.csv", 422, "TOO_MANY_COLUMNS"),
        (b"a,b\r\n", "../../etc/macro.xlsm", 415, "UNSUPPORTED_TYPE"),
    ],
)
def test_malicious_uploads_rejected(api: Client, data: bytes, name: str, status: int, code: str) -> None:
    c, h, _ = api
    pid = new_pf(c, h)
    r = upload(c, h, pid, data, name)
    assert r.status_code == status and r.json()["code"] == code


def test_oversized_upload_is_413(api: Client) -> None:
    c, h, _ = api
    pid = new_pf(c, h)
    assert upload(c, h, pid, b"x" * (5 * 1024 * 1024 + 1)).status_code == 413


def test_import_and_privacy_routes_enforce_csrf(api: Client) -> None:
    c, h, _ = api
    pid = new_pf(c, h)
    no_csrf = {"Origin": ORIGIN}
    assert c.post("/api/holdings/import", files={"file": ("h.csv", CSV_OK, "text/csv")}, data={"portfolio_id": pid},
                  headers=no_csrf).status_code == 403  # fmt: skip
    hostile = {**h, "Origin": "https://evil.example"}
    assert upload(c, hostile, pid, CSV_OK).status_code == 403
    # multipart is only allow-listed for the upload route; JSON-only elsewhere
    assert c.post("/api/privacy/erase", files={"f": ("a", b"x")}, headers=h).status_code == 403
    assert c.post("/api/holdings/import", json={"portfolio_id": pid}, headers=h).status_code == 403
    assert c.post("/api/privacy/erase", json={"confirm": "ERASE ALL MY DATA"}, headers=no_csrf).status_code == 403
    assert c.post("/api/backup", json={}, headers=no_csrf).status_code == 403


def test_routes_require_a_session(tmp_path: Path) -> None:
    settings = Settings(env="prod", data_dir=tmp_path / "iip")
    with TestClient(create_app(settings, routers=all_routers()), base_url=ORIGIN) as c:
        for method, path in [("GET", "/api/portfolios/x/summary"), ("GET", "/api/evidence/1"),
                             ("POST", "/api/holdings/import/x/apply"), ("POST", "/api/alerts/x/ack"),
                             ("DELETE", "/api/watchlist/mf:1"), ("GET", "/api/privacy/export.csv")]:  # fmt: skip
            assert c.request(method, path, headers={"Origin": ORIGIN}).status_code == 401, path


def test_watchlist_alerts_and_evidence(api: Client) -> None:
    c, h, _ = api
    pid = new_pf(c, h)
    body = {
        "instrument_id": "mf:990003",
        "txn_date": "2025-06-02",
        "txn_type": "buy",
        "units": "10",
        "amount": "140.00",
    }
    c.post(f"/api/portfolios/{pid}/transactions", json=body, headers=h)
    fd = {"instrument_id": FD, "txn_date": "2026-05-10", "txn_type": "buy", "units": "1", "amount": "600000.00"}
    c.post(f"/api/portfolios/{pid}/transactions", json=fd, headers=h)
    assert c.post("/api/watchlist", json={"instrument_id": "mf:990004", "note": "later"}, headers=h).status_code == 200
    assert c.post("/api/watchlist", json={"instrument_id": "mf:990004"}, headers=h).status_code == 409
    w = c.get("/api/watchlist").json()["items"][0]
    assert w["change"]["to"] == {"date": "2026-10-14", "value": "85.0000"}  # base: NAV on/before the add date
    first = c.post("/api/alerts/evaluate", json={}, headers=h).json()
    assert first["created"], first
    for a in first["created"]:
        assert a["message"].startswith("Your rule") and compliance.blocked(a["message"]) == []
    second = c.post("/api/alerts/evaluate", json={}, headers=h).json()
    assert second["created"] == [] and second["already_present"] == first["triggered"]
    aid = first["created"][0]["alert_id"]
    assert c.post(f"/api/alerts/{aid}/ack", json={}, headers=h).json()["acknowledged_at"]
    assert c.post("/api/alerts/al_none/ack", json={}, headers=h).status_code == 404
    rules = c.get("/api/alerts/rules").json()
    assert c.put("/api/alerts/rules", json={**rules, "maturity_within_days": 5}, headers=h).status_code == 200
    assert c.put("/api/alerts/rules", json={**rules, "concentration_hhi_above": 0.3}, headers=h).status_code == 422
    obs = w["latest"]["obs_id"]
    e = c.get(f"/api/evidence/{obs}").json()
    assert e["observation"]["sha256"] and e["observation"]["url"].startswith("https://")
    assert c.get("/api/evidence/999999").status_code == 404
    assert c.delete("/api/watchlist/mf:990004", headers=JSON(h)).status_code == 200


def test_privacy_inventory_export_erase_backup(api: Client) -> None:
    c, h, settings = api
    pid = new_pf(c, h, '=HYPERLINK("http://x","y")')
    body = {"instrument_id": "mf:990001", "txn_date": "2025-01-10", "txn_type": "buy", "units": "100",
            "amount": "98765432.10"}  # fmt: skip
    c.post(f"/api/portfolios/{pid}/transactions", json=body, headers=h)
    inv = c.get("/api/privacy/inventory").json()
    assert inv["user_data"]["tables"]["transactions"] == 1 and "98765432" not in str(inv)
    ex = c.get("/api/privacy/export")
    assert "attachment" in ex.headers["content-disposition"]
    assert ex.json()["transactions"][0]["amount"] == "98765432.10"
    csv = c.get("/api/privacy/export.csv")
    assert csv.headers["content-type"].startswith("text/csv")
    assert csv.content.startswith(b"\xef\xbb\xbf") and b"\"'=HYPERLINK(" in csv.content
    b = c.post("/api/backup", json={}, headers=h).json()
    assert b["integrity"] == "ok" and Path(b["path"]).exists()
    assert c.post("/api/privacy/erase", json={"confirm": "erase all my data"}, headers=h).status_code == 422
    assert c.post("/api/privacy/erase", json={}, headers=h).status_code == 422
    out = c.post("/api/privacy/erase", json={"confirm": "ERASE ALL MY DATA", "delete_backups": True}, headers=h)
    assert out.status_code == 200 and out.json()["backups_remaining"] == 0
    after = c.get("/api/privacy/inventory").json()["user_data"]["tables"]
    assert all(v == 0 for v in after.values()), after
    raw = settings.db_path.read_bytes()
    wal = settings.db_path.with_name("iip.db-wal")
    raw += wal.read_bytes() if wal.exists() else b""
    assert b"98765432.10" not in raw and b"HYPERLINK" not in raw


def test_api_logs_redacted(api: Client, caplog: pytest.LogCaptureFixture) -> None:
    c, h, _ = api
    caplog.set_level(logging.DEBUG)
    pid = new_pf(c, h, "SENTINEL-PORTFOLIO-XYZ")
    data = (
        b"instrument_name,amfi_code,units,cost_basis_inr,purchase_date\r\n"
        b'SENTINEL-FUND-XYZ,990001,7654.321,"9,87,65,432.10",2025-01-10\r\n'
    )
    p = upload(c, h, pid, data, "SENTINEL-FILE.csv").json()
    c.post(f"/api/holdings/import/{p['batch_id']}/apply", json={"sha256": p["file_sha256"]}, headers=h)
    c.get(f"/api/portfolios/{pid}/summary")
    c.post("/api/alerts/evaluate", json={}, headers=h)
    assert caplog.records
    for s in ("SENTINEL", "98765432", "9,87,65,432", "7654.321"):
        assert s not in caplog.text, s
