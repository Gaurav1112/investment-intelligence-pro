"""Clean-machine setup finding: a backend started before `make build` must say why every page is missing."""

import logging
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from iip.api import app as app_module
from iip.api.routes import all_routers
from iip.api.settings import Settings

BASE = "http://127.0.0.1:8741"


def test_missing_frontend_build_is_logged_and_api_still_serves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(app_module, "frontend_dist", lambda: tmp_path / "no-dist")
    with caplog.at_level(logging.WARNING, logger="iip.api"):
        app = app_module.create_app(Settings(env="test", auth=False, data_dir=tmp_path / "d"), routers=all_routers())
    assert any("frontend build missing" in r.getMessage() for r in caplog.records)
    with TestClient(app, base_url=BASE) as c:
        assert c.get("/api/health").json() == {"status": "ok"}
        assert c.get("/").status_code == 404


def test_built_frontend_is_served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>IIP</title>")
    monkeypatch.setattr(app_module, "frontend_dist", lambda: dist)
    app = app_module.create_app(Settings(env="test", auth=False, data_dir=tmp_path / "d"), routers=all_routers())
    with TestClient(app, base_url=BASE) as c:
        r = c.get("/discover")
        assert r.status_code == 200 and "<title>IIP</title>" in r.text
