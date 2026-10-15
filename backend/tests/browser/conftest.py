"""Real-browser security tests (threat-model SEC-16, SEC-23). Opt-in: ``IIP_BROWSER_TESTS=1`` (``make test-browser``).

The fixtures start the REAL server (``python -m iip.api``, production mode, auth on) on a free loopback port with a
temporary data directory, serving the built ``frontend/dist``; and a separate "attacker" static server on another
port. Chromium comes from ``.venv/bin/playwright install chromium``.
"""

from __future__ import annotations

import functools
import http.server
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

ENABLED = os.environ.get("IIP_BROWSER_TESTS") == "1"
REPO = Path(__file__).resolve().parents[3]
DIST = REPO / "frontend" / "dist"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skip = pytest.mark.skip(reason="browser tests are opt-in: IIP_BROWSER_TESTS=1 (make test-browser)")
    for item in items:
        if "browser" in item.keywords and not ENABLED:
            item.add_marker(skip)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class App:
    port: int
    token: str
    data_dir: Path
    _client: tuple[httpx.Client, dict[str, str]] | None = None

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def client(self) -> tuple[httpx.Client, dict[str, str]]:
        """One authenticated API client per run (logins are rate-limited, SEC-13), with same-origin headers."""
        if self._client is None:
            c = httpx.Client(base_url=self.origin, timeout=30)
            r = c.post("/api/session", json={"token": self.token}, headers={"Origin": self.origin})
            r.raise_for_status()
            self._client = (c, {"Origin": self.origin, "X-IIP-CSRF": r.json()["csrf"]})
        return self._client


@pytest.fixture(scope="session")
def app(tmp_path_factory: pytest.TempPathFactory) -> Iterator[App]:
    if not (DIST / "index.html").exists():
        pytest.fail("frontend/dist is missing: run `make build` first (make test-browser does)")
    data_dir = tmp_path_factory.mktemp("iip-browser-data")
    port = free_port()
    env = {**os.environ, "IIP_ENV": "prod", "IIP_PORT": str(port), "IIP_HOST": "127.0.0.1",
           "IIP_DATA_DIR": str(data_dir)}  # fmt: skip
    env.pop("IIP_DEV_ORIGINS", None)
    log = data_dir / "server.log"
    with log.open("wb") as out:
        proc = subprocess.Popen([sys.executable, "-m", "iip.api"], env=env, stdout=out, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if proc.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(f"server did not start:\n{log.read_text()}")
            time.sleep(0.2)
        token = (data_dir / "secrets" / "access-token").read_text().strip()
        running = App(port=port, token=token, data_dir=data_dir)
        yield running
        if running._client is not None:
            running._client[0].close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@dataclass
class Attacker:
    port: int
    root: Path

    def url(self, host: str, name: str) -> str:
        return f"http://{host}:{self.port}/{name}"

    def page(self, name: str, html: str) -> None:
        (self.root / name).write_text(html, encoding="utf-8")


@pytest.fixture(scope="session")
def attacker(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Attacker]:
    """A second local origin (another port): a hostile page the user happens to open."""
    root = tmp_path_factory.mktemp("attacker")
    port = free_port()

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Quiet, directory=str(root)))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield Attacker(port=port, root=root)
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture(scope="session")
def browser() -> Iterator[Any]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            yield b
        finally:
            b.close()


@pytest.fixture
def logged_in(browser: Any, app: App) -> Iterator[Any]:
    """A browser context with a live session, obtained through the real one-time login link (#login=…)."""
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(f"{app.origin}/#login={app.token}")
    page.wait_for_function("() => !location.hash.includes('login=')")
    deadline = time.monotonic() + 15
    while not any(c["name"] for c in ctx.cookies(app.origin)):
        if time.monotonic() > deadline:
            raise RuntimeError("login did not create a session cookie")
        page.wait_for_timeout(100)
    try:
        yield ctx
    finally:
        ctx.close()
