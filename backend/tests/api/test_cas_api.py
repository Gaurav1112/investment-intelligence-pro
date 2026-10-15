"""CAS import API: multipart preview (in memory) → JSON apply. SYNTHETIC statements only (see cas_synthetic.py)."""

from __future__ import annotations

import json
import logging
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import starlette.formparsers
from starlette.testclient import TestClient

from iip.api.app import create_app
from iip.api.routes import all_routers
from iip.api.routes_cas import parse_form_in_memory
from iip.api.settings import Settings
from tests.services import cas_synthetic as syn
from tests.services.test_cas import PII, seed_isins
from tests.services.test_portfolio import NOW, seed_market

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
        seed_isins(conn)
        token = settings.token_path.read_text().strip()
        csrf = c.post("/api/session", json={"token": token}, headers={"Origin": ORIGIN}).json()["csrf"]
        yield c, {"Origin": ORIGIN, "X-IIP-CSRF": csrf}, settings


def new_pf(c: TestClient, h: dict[str, str]) -> str:
    return str(c.post("/api/portfolios", json={"name": "Core", "nature": "actual"}, headers=h).json()["portfolio_id"])


def upload(c: TestClient, h: dict[str, str], pid: str, data: bytes, password: str = syn.PASSWORD) -> Any:
    return c.post("/api/holdings/import-cas", files={"file": ("statement.pdf", data, "application/pdf")},
                  data={"portfolio_id": pid, "password": password}, headers=h)  # fmt: skip


def test_preview_apply_round_trip(api: Client) -> None:
    c, h, settings = api
    pid = new_pf(c, h)
    r = upload(c, h, pid, syn.build_pdf())
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["applied"] is False and len(p["will_store"]) == 7 and p["reconciliation_ok"] is True
    assert c.get(f"/api/portfolios/{pid}/transactions").json()["items"] == []
    url = f"/api/holdings/import-cas/{p['batch_id']}/apply"
    bad = c.post(url, json={"sha256": "f" * 64}, headers=h)
    assert bad.status_code == 409 and bad.json()["code"] == "PREVIEW_MISMATCH"
    assert c.post(f"/api/holdings/import/{p['batch_id']}/apply", json={"sha256": p["file_sha256"]},
                  headers=h).json()["code"] == "WRONG_APPLY_ENDPOINT"  # fmt: skip
    ok = c.post(url, json=p["confirm_with"], headers=h)
    assert ok.status_code == 200 and ok.json()["applied"] is True and ok.json()["transactions_created"] == 7
    assert list((settings.data_dir / "backups").glob("*pre-import*.sqlite3"))  # backup before the change
    items = c.get(f"/api/portfolios/{pid}/transactions").json()["items"]
    assert sorted(i["txn_type"] for i in items) == ["buy", "buy", "buy", "buy", "dividend", "sell", "sell"]
    assert c.get(f"/api/portfolios/{pid}/summary").status_code == 200
    assert c.post(url, json=p["confirm_with"], headers=h).status_code == 409


def test_reconciliation_and_oversell_through_api(api: Client) -> None:
    c, h, _ = api
    pid = new_pf(c, h)
    st = syn.Statement(schemes=(syn.SchemeBlock("Z1G", "x", syn.ISIN_GROWTH, "30.000", "0.000", (
        syn.Row("10-Jan-2024", "Purchase", "500.00", "50.000", "10.0000", "80.000"),
        syn.Row("10-Feb-2024", "Redemption", "880.00", "(80.000)", "11.0000", "0.000"),
    )),))  # fmt: skip
    p = upload(c, h, pid, syn.build_pdf(st)).json()
    assert p["reconciliation"][0]["status"] == "MISMATCH" and p["blocking"][0]["code"] == "OVERSELL"
    url = f"/api/holdings/import-cas/{p['batch_id']}/apply"
    r = c.post(url, json={"sha256": p["file_sha256"]}, headers=h)
    assert r.status_code == 409 and r.json()["code"] == "RECONCILIATION_NOT_ACKNOWLEDGED"
    r = c.post(url, json={"sha256": p["file_sha256"], "accept_reconciliation_mismatches": True}, headers=h)
    assert r.status_code == 422 and r.json()["code"] == "OVERSELL"
    assert c.get(f"/api/portfolios/{pid}/transactions").json()["items"] == []


@pytest.mark.parametrize(
    ("data", "password", "status", "code"),
    [
        (b"GIF89a....", syn.PASSWORD, 415, "NOT_A_PDF"),
        (b"PK\x03\x04%PDF-", syn.PASSWORD, 415, "NOT_A_PDF"),
        (b"%PDF-1.4\n%%EOF", syn.PASSWORD, 422, "PDF_DAMAGED"),
    ],
)
def test_bad_files_rejected(api: Client, data: bytes, password: str, status: int, code: str) -> None:
    c, h, _ = api
    r = upload(c, h, new_pf(c, h), data, password)
    assert r.status_code == status and r.json()["code"] == code


def test_wrong_password_and_unknown_encryption(api: Client) -> None:
    c, h, _ = api
    pid = new_pf(c, h)
    r = upload(c, h, pid, syn.build_pdf(), "MARKER-WRONG-PW-7781")
    assert r.status_code == 422 and r.json()["code"] == "WRONG_PASSWORD"
    assert "MARKER-WRONG-PW-7781" not in r.text
    r = upload(c, h, pid, syn.build_pdf().replace(b"/Filter /Standard", b"/Filter /AcmeLock"))
    assert r.status_code == 422 and r.json()["code"] == "UNSUPPORTED_ENCRYPTION"


def test_body_cap_enforced_before_parsing(api: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    """The middleware's request cap (Settings.max_body_bytes, 5 MiB) applies before the service's 10 MiB cap."""
    from iip.services import cas

    def spy(*_a: object) -> None:
        raise AssertionError("parser must not run")

    monkeypatch.setattr(cas, "read_statement", spy)
    c, h, settings = api
    r = upload(c, h, new_pf(c, h), b"%PDF-" + b"0" * settings.max_body_bytes)
    assert r.status_code == 413


def test_form_and_csrf_rules(api: Client) -> None:
    c, h, _ = api
    pid = new_pf(c, h)
    no_csrf = {"Origin": ORIGIN}
    r = c.post("/api/holdings/import-cas", files={"file": ("s.pdf", syn.build_pdf(), "application/pdf")},
               data={"portfolio_id": pid, "password": syn.PASSWORD}, headers=no_csrf)  # fmt: skip
    assert r.status_code == 403
    assert c.post("/api/holdings/import-cas", json={"portfolio_id": pid}, headers=h).status_code == 403
    r = c.post("/api/holdings/import-cas", data={"portfolio_id": pid, "password": "x"},
               files={"other": ("a.txt", b"x", "text/plain")}, headers=h)  # fmt: skip
    assert r.status_code == 422 and r.json()["code"] == "BAD_FORM"
    r = c.post("/api/holdings/import-cas", files={"file": ("s.pdf", syn.build_pdf(), "application/pdf")},
               data={"portfolio_id": "pf_missing", "password": syn.PASSWORD}, headers=h)  # fmt: skip
    assert r.status_code == 404


def test_in_memory_form_parser() -> None:
    boundary = "XyZ"
    body = (
        b'--XyZ\r\nContent-Disposition: form-data; name="a"\r\n\r\n1\r\n'
        b'--XyZ\r\nContent-Disposition: form-data; name="f"; filename="s.pdf"\r\n'
        b"Content-Type: application/pdf\r\n\r\n%PDF-\x00\xff\r\n--XyZ--\r\n"
    )
    out = parse_form_in_memory(f"multipart/form-data; boundary={boundary}", body)
    assert out == {"a": (None, b"1"), "f": ("s.pdf", b"%PDF-\x00\xff")}
    dup = body.replace(b'name="f"', b'name="a"')
    with pytest.raises(Exception, match="duplicate"):
        parse_form_in_memory(f"multipart/form-data; boundary={boundary}", dup)


def test_privacy_pdf_never_on_disk_and_pii_password_never_logged_stored_or_returned(
    api: Client, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, capfd: pytest.CaptureFixture[str]
) -> None:
    """Planted-marker test (SEC-62 style): a synthetic statement full of recognisable PII and a recognisable
    password goes through preview + apply. None of it may appear in a response, a log record, stdout/stderr, the
    database or any file under the data directory, and no temporary file may be created for the upload."""
    caplog.set_level(logging.DEBUG)
    c, h, settings = api
    pid = new_pf(c, h)

    def no_temp_files(*_a: object, **_k: object) -> None:
        raise AssertionError("the CAS upload must not be spooled to a temporary file")

    for name in ("SpooledTemporaryFile", "NamedTemporaryFile", "TemporaryFile", "mkstemp", "mkdtemp"):
        monkeypatch.setattr(tempfile, name, no_temp_files)
    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", no_temp_files)  # imported by name there
    pdf = syn.build_pdf()
    big_pdf = pdf + b"\n%" + b"pad" * 400_000 + b"\n"  # > 1 MiB: Starlette would spool this to disk
    assert len(big_pdf) > 1024 * 1024
    responses: list[str] = []
    r = upload(c, h, pid, big_pdf, "MARKER-WRONG-PW-55")  # a failed attempt must not leak either
    responses.append(r.text)
    r = upload(c, h, pid, big_pdf)
    assert r.status_code == 200, r.text
    responses.append(r.text)
    p = r.json()
    a = c.post(f"/api/holdings/import-cas/{p['batch_id']}/apply", json=p["confirm_with"], headers=h)
    assert a.status_code == 200
    responses.append(a.text)
    monkeypatch.undo()
    responses.append(c.get(f"/api/portfolios/{pid}/transactions").text)
    responses.append(c.get("/api/privacy/export").text)
    conn = c.app.app.state.iip.conn  # type: ignore[attr-defined]
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    files = [f for f in settings.data_dir.rglob("*") if f.is_file()]
    assert any(f.suffix == ".sqlite3" for f in files)  # the backup is part of what is scanned
    file_bytes = b"".join(f.read_bytes() for f in files)
    assert b"%PDF-" not in file_bytes  # the PDF itself was never written under the data dir
    haystacks = {
        "responses": "\n".join(responses),
        "logs": caplog.text + "\n" + "\n".join(json.dumps(r.__dict__, default=str) for r in caplog.records),
        "stdout/stderr": "".join(capfd.readouterr()),
        "database": "\n".join(conn.iterdump()),
        "files": file_bytes.decode("latin-1"),
    }
    for where, text in haystacks.items():
        for marker in (*PII, syn.PASSWORD, "MARKER-WRONG-PW-55"):
            assert marker not in text, f"{marker!r} leaked into {where}"
    assert "not stored" in p["privacy"]


def test_temp_file_guard_is_effective_negative_control(api: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    """The same patch DOES trip on the CSV route (FastAPI ``File()`` spools uploads over 1 MiB to disk), so the
    privacy test above is not vacuous."""
    c, h, _ = api

    def no_temp_files(*_a: object, **_k: object) -> None:
        raise AssertionError("spooled")

    pid = new_pf(c, h)

    def post() -> int:
        return c.post("/api/holdings/import", files={"file": ("h.csv", b"x" * (1024 * 1024 + 10), "text/csv")},
                      data={"portfolio_id": pid}, headers=h).status_code  # fmt: skip

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", no_temp_files)
    assert post() == 400  # FastAPI reports the refused spool as a body-parse error
    monkeypatch.undo()
    assert post() != 400
