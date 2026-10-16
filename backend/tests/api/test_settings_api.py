"""C04 over B04: notification and wording settings API (ECC typescript-reviewer-3, typescript-reviewer-4).

Before this router existed, ``/api/settings/notifications`` and ``/api/settings/vocabulary`` answered 404, so the
Settings opt-ins could never work. These tests pin:

* the routes exist, need a session, and the PUTs need CSRF, exactly like every other state-changing route;
* the vocabulary wire values are ONE set shared by the backend (:class:`compliance.Vocabulary`) and both frontend
  type files; ``neutral`` is the default (U-11) and ``badges`` needs the private-view acknowledgement;
* notifications are off by default (U-09) and the server never reports a channel as on when it cannot deliver.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from iip.api.app import create_app
from iip.api.routes import all_routers
from iip.api.settings import Settings
from iip.services import notify, settings_prefs
from iip.supervisor.compliance import Vocabulary

ORIGIN = "http://127.0.0.1:8741"
NOW = datetime(2026, 10, 16, 6, 0, tzinfo=UTC)
LIB = Path(__file__).resolve().parents[3] / "frontend" / "src" / "lib"


def _inner(app: Any) -> Any:
    while not hasattr(app, "state"):
        app = app.app
    return app


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, dict[str, str], Any]]:
    monkeypatch.delenv(notify.NOTIFY_ENV, raising=False)
    settings = Settings(env="prod", data_dir=tmp_path / "iip")
    app = create_app(settings, routers=all_routers(), clock=lambda: NOW)
    c = TestClient(app, base_url=ORIGIN)
    with c:
        token = settings.token_path.read_text().strip()
        csrf = c.post("/api/session", json={"token": token}, headers={"Origin": ORIGIN}).json()["csrf"]
        yield c, {"Origin": ORIGIN, "X-IIP-CSRF": csrf}, _inner(app).state.iip.conn


# ---------------------------------------------------------------------------------------------- one vocabulary


def _ts_union(path: Path, name: str) -> set[str]:
    m = re.search(r"export type " + name + r" = ([^;]+);", path.read_text(encoding="utf-8"))
    assert m is not None, (path.name, name)
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def test_frontend_and_backend_share_one_vocabulary() -> None:
    backend = {v.value for v in Vocabulary}
    assert backend == {"neutral", "badges"}
    assert _ts_union(LIB / "types-settings.ts", "VocabularyMode") == backend
    signals = (LIB / "types-signals.ts").read_text(encoding="utf-8")
    # types-signals re-exports the Settings type instead of declaring its own literal set.
    assert re.search(r"export type Vocabulary = VocabularyMode;", signals), "types-signals must alias VocabularyMode"
    assert "buy_sell" not in signals


# ---------------------------------------------------------------------------------------------- session + CSRF


def test_settings_routes_exist_for_a_logged_in_user(api: Any) -> None:
    c, _h, _conn = api
    assert c.get("/api/settings/vocabulary").status_code == 200  # was 404 before this router existed
    assert c.get("/api/settings/notifications").status_code == 200


def test_settings_routes_require_a_session(tmp_path: Path) -> None:
    settings = Settings(env="prod", data_dir=tmp_path / "iip")
    with TestClient(create_app(settings, routers=all_routers(), clock=lambda: NOW), base_url=ORIGIN) as c:
        for method, path in [
            ("GET", "/api/settings/vocabulary"),
            ("PUT", "/api/settings/vocabulary"),
            ("GET", "/api/settings/notifications"),
            ("PUT", "/api/settings/notifications"),
        ]:
            r = c.request(method, path, json={}, headers={"Origin": ORIGIN})
            assert r.status_code == 401, (method, path, r.status_code)


def test_puts_need_csrf(api: Any) -> None:
    c, h, conn = api
    no_csrf = {"Origin": ORIGIN}
    r = c.put("/api/settings/vocabulary", json={"mode": "badges", "acknowledge_private_only": True}, headers=no_csrf)
    assert r.status_code == 403 and r.json()["code"] == "CSRF_REJECTED"
    bad_origin = {**h, "Origin": "http://evil.example"}
    r = c.put("/api/settings/vocabulary", json={"mode": "badges", "acknowledge_private_only": True}, headers=bad_origin)
    assert r.status_code == 403
    r = c.put("/api/settings/notifications", json={"channel": "off"}, headers=no_csrf)
    assert r.status_code == 403
    assert settings_prefs.read_vocabulary(conn) is Vocabulary.NEUTRAL  # nothing was written


# ---------------------------------------------------------------------------------------------- vocabulary


def test_vocabulary_defaults_to_neutral(api: Any) -> None:
    c, _h, _conn = api
    assert c.get("/api/settings/vocabulary").json() == {"mode": "neutral"}


def test_badges_need_the_private_view_acknowledgement(api: Any) -> None:
    c, h, conn = api
    r = c.put("/api/settings/vocabulary", json={"mode": "badges", "acknowledge_private_only": False}, headers=h)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "ACK_REQUIRED"
    assert settings_prefs.read_vocabulary(conn) is Vocabulary.NEUTRAL
    r = c.put("/api/settings/vocabulary", json={"mode": "badges", "acknowledge_private_only": True}, headers=h)
    assert r.status_code == 200 and r.json() == {"mode": "badges"}
    assert c.get("/api/settings/vocabulary").json() == {"mode": "badges"}
    r = c.put("/api/settings/vocabulary", json={"mode": "neutral"}, headers=h)
    assert r.status_code == 200 and c.get("/api/settings/vocabulary").json() == {"mode": "neutral"}


def test_the_old_buy_sell_value_and_unknown_fields_are_refused(api: Any) -> None:
    c, h, _conn = api
    for body in (
        {"mode": "buy_sell", "acknowledge_private_only": True},
        {"mode": "BUY", "acknowledge_private_only": True},
        {"mode": "neutral", "extra": 1},
    ):
        assert c.put("/api/settings/vocabulary", json=body, headers=h).status_code == 422, body


@pytest.mark.parametrize("stored", ['{"mode":"buy_sell"}', '"badges"', "not json", '{"mode":3}'])
def test_an_unreadable_stored_vocabulary_reads_as_neutral(api: Any, stored: str) -> None:
    c, _h, conn = api
    conn.execute("INSERT INTO settings(key, value_json) VALUES (?, ?)", (settings_prefs.VOCABULARY_KEY, stored))
    conn.commit()
    assert c.get("/api/settings/vocabulary").json() == {"mode": "neutral"}


# ---------------------------------------------------------------------------------------------- notifications


def test_notifications_are_off_by_default_with_the_exact_ping(api: Any) -> None:
    c, _h, _conn = api
    body = c.get("/api/settings/notifications").json()
    assert body["channel"] == "off" and body["available"] == [] and body["status"] == "off"
    assert body["ping_template"] == "IIP: daily report ready (data as of DD-Mon). Open the app."


def test_a_configured_channel_without_a_transport_is_never_reported_on(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, _h, _conn = api
    monkeypatch.setenv(notify.NOTIFY_ENV, "telegram")
    body = c.get("/api/settings/notifications").json()
    assert body["channel"] == "off"
    assert body["configured"] == "telegram"
    assert body["status"] == "REQUIRES CONFIGURATION"


def test_switching_on_a_channel_that_cannot_deliver_is_refused(api: Any) -> None:
    c, h, _conn = api
    r = c.put("/api/settings/notifications", json={"channel": "webpush"}, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "CHANNEL_UNAVAILABLE"
    r = c.put("/api/settings/notifications", json={"channel": "telegram"}, headers=h)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "ACK_REQUIRED"
    r = c.put(
        "/api/settings/notifications", json={"channel": "telegram", "acknowledge_third_party_storage": True}, headers=h
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "CHANNEL_UNAVAILABLE"
    assert c.get("/api/settings/notifications").json()["channel"] == "off"


def test_off_is_accepted_and_rejected_channels_are_not_in_the_type(api: Any) -> None:
    c, h, _conn = api
    r = c.put("/api/settings/notifications", json={"channel": "off"}, headers=h)
    assert r.status_code == 200 and r.json()["channel"] == "off"
    for ch in ("ntfy", "email"):
        assert c.put("/api/settings/notifications", json={"channel": ch}, headers=h).status_code == 422
