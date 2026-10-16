"""A05: the router registry discovers every ``iip/api/routes_*.py`` module instead of listing them by hand.

Later packages only ADD a ``routes_<feature>.py`` file exposing ``router() -> APIRouter``; nobody edits ``routes.py``.
The snapshot below is the route table as it stood before the switch (commit 5efbc5e, ``env="test"``, no frontend
build). Every one of those routes must still be registered; new routes are allowed."""

from __future__ import annotations

import re
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from iip.api import routes
from iip.api.app import create_app
from iip.api.routes import all_routers, discover_routers
from iip.api.settings import Settings

API_DIR = Path(routes.__file__).resolve().parent

# (methods, path) as registered before autodiscovery. The SPA catch-all exists only with a frontend build: excluded.
SNAPSHOT_BEFORE_A05: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET,HEAD", "/api/openapi.json"),
        ("GET,HEAD", "/api/docs"),
        ("GET,HEAD", "/docs/oauth2-redirect"),
        ("GET", "/api/health"),
        ("GET", "/api/ready"),
        ("POST", "/api/session"),
        ("DELETE", "/api/session"),
        ("GET", "/api/me"),
        ("GET", "/api/profile"),
        ("PUT", "/api/profile"),
        ("DELETE", "/api/profile"),
        ("POST", "/api/discover"),
        ("GET", "/api/instruments"),
        ("GET", "/api/instruments/{instrument_id}"),
        ("POST", "/api/instruments/tbill"),
        ("POST", "/api/instruments/fd"),
        ("PUT", "/api/instruments/{instrument_id}/exit-load"),
        ("DELETE", "/api/instruments/{instrument_id}"),
        ("POST", "/api/ingestion/amfi-navall"),
        ("POST", "/api/ingestion/backfill/{amfi_code}"),
        ("POST", "/api/ingestion/backfill-batch"),
        ("GET", "/api/data-health"),
        ("POST", "/api/dev/seed-fixtures"),
        ("GET", "/api/runs/{run_id}"),
        ("GET", "/api/methodology"),
        ("POST", "/api/compare"),
        ("POST", "/api/scenario"),
        ("POST", "/api/simulate"),
        ("POST", "/api/feasibility"),
        ("GET", "/api/forecast/{instrument_id}"),
        ("GET", "/api/risk/{instrument_id}"),
        ("GET", "/api/portfolios"),
        ("POST", "/api/portfolios"),
        ("GET", "/api/portfolios/{portfolio_id}/transactions"),
        ("POST", "/api/portfolios/{portfolio_id}/transactions"),
        ("DELETE", "/api/portfolios/{portfolio_id}/transactions/{txn_id}"),
        ("GET", "/api/portfolios/{portfolio_id}/summary"),
        ("POST", "/api/holdings/import"),
        ("POST", "/api/holdings/import/{batch_id}/apply"),
        ("GET", "/api/watchlist"),
        ("POST", "/api/watchlist"),
        ("DELETE", "/api/watchlist/{instrument_id}"),
        ("GET", "/api/alerts"),
        ("GET", "/api/alerts/rules"),
        ("PUT", "/api/alerts/rules"),
        ("POST", "/api/alerts/evaluate"),
        ("POST", "/api/alerts/{alert_id}/ack"),
        ("GET", "/api/evidence/{obs_id}"),
        ("GET", "/api/privacy/inventory"),
        ("GET", "/api/privacy/export"),
        ("GET", "/api/privacy/export.csv"),
        ("POST", "/api/privacy/erase"),
        ("POST", "/api/backup"),
        ("GET", "/api/llm/status"),
        ("PUT", "/api/llm/config"),
        ("POST", "/api/holdings/import-cas"),
        ("POST", "/api/holdings/import-cas/{batch_id}/apply"),
        ("POST", "/api/instruments/gsec"),
        ("POST", "/api/instruments/corp-bond"),
        ("GET", "/api/bonds"),
        ("GET", "/api/inputs/cpi"),
        ("POST", "/api/inputs/cpi"),
        ("GET", "/api/inputs/mospi/status"),
        ("POST", "/api/inputs/mospi/fetch"),
        ("GET", "/api/inputs/riskfree"),
        ("POST", "/api/inputs/riskfree"),
        ("GET", "/api/inputs/fund-facts/{instrument_id}"),
        ("POST", "/api/inputs/fund-facts/{instrument_id}"),
        ("GET", "/api/inputs/fd-rates"),
        ("POST", "/api/inputs/fd-rates"),
    }
)
SPA = "/{full_path:path}"


def _flatten(app_routes: list[Any]) -> list[Any]:
    """Route objects in matching order (FastAPI >= 0.140 wraps included routers in ``_IncludedRouter``)."""
    out: list[Any] = []
    for r in app_routes:
        inner = getattr(r, "original_router", None)
        out.extend(_flatten(inner.routes) if inner is not None else [r])
    return out


@pytest.fixture
def registered(tmp_path: Path) -> Iterator[list[Any]]:
    asgi = create_app(Settings(env="test", auth=False, data_dir=tmp_path / "d"), routers=all_routers())
    try:
        yield _flatten(asgi.app.routes)  # type: ignore[attr-defined]
    finally:
        asgi.app.state.iip.close()  # type: ignore[attr-defined]


def _table(route_objs: list[Any]) -> list[tuple[str, str]]:
    return [(",".join(sorted(getattr(r, "methods", None) or [])), r.path) for r in route_objs if r.path != SPA]


def test_every_route_registered_before_autodiscovery_is_still_registered(registered: list[Any]) -> None:
    table = _table(registered)
    assert len(SNAPSHOT_BEFORE_A05) == 70
    assert sorted(SNAPSHOT_BEFORE_A05 - set(table)) == []


def test_no_route_is_registered_twice(registered: list[Any]) -> None:
    table = _table(registered)
    dupes = sorted({t for t in table if table.count(t) > 1})
    assert dupes == []


def test_every_routes_module_on_disk_is_discovered() -> None:
    on_disk = sorted(p.stem for p in API_DIR.glob("routes_*.py"))
    assert on_disk, "expected feature router modules"
    assert routes.router_module_names() == on_disk  # sorted: a deterministic registration order


def _sample_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "p1", path)


def test_no_route_is_shadowed_by_an_earlier_one(registered: list[Any]) -> None:
    """Autodiscovery registers routers in module-name order, not the old hand-written order. That is only safe while
    no earlier route captures a later route's URL with the same method (e.g. ``/x/{id}`` before ``/x/summary``)."""
    shadowed: list[str] = []
    objs = [r for r in registered if r.path != SPA and getattr(r, "methods", None)]
    for j, later in enumerate(objs):
        url = _sample_path(later.path)
        for earlier in objs[:j]:
            if earlier.methods & later.methods and earlier.path_regex.fullmatch(url) and earlier.path != later.path:
                shadowed.append(f"{sorted(later.methods)} {later.path} is captured by {earlier.path}")
    assert shadowed == []


def _make_pkg(root: Path, name: str, files: dict[str, str]) -> None:
    pkg = root / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    for fname, body in files.items():
        (pkg / fname).write_text(textwrap.dedent(body))


@pytest.fixture
def syspath(tmp_path: Path) -> Iterator[Path]:
    sys.path.insert(0, str(tmp_path))
    try:
        yield tmp_path
    finally:
        sys.path.remove(str(tmp_path))
        for mod in [m for m in sys.modules if m.startswith("a05_fake")]:
            del sys.modules[mod]


ROUTER_SRC = """
    from fastapi import APIRouter

    def router() -> APIRouter:
        r = APIRouter(prefix="/api/{name}")

        @r.get("/ping")
        def ping() -> dict[str, str]:
            return {{"ok": "{name}"}}

        return r
"""


def test_a_new_routes_file_is_picked_up_without_editing_the_registry(syspath: Path) -> None:
    _make_pkg(syspath, "a05_fake_ok", {
        "routes_zeta.py": ROUTER_SRC.format(name="zeta"),
        "routes_alpha.py": ROUTER_SRC.format(name="alpha"),
        "routes.py": "raise AssertionError('the registry module itself is not a feature router')\n",
        "helpers.py": "raise AssertionError('only routes_*.py modules are imported')\n",
    })  # fmt: skip
    import a05_fake_ok  # type: ignore[import-not-found]

    found = discover_routers(a05_fake_ok)
    assert [r.prefix for r in found] == ["/api/alpha", "/api/zeta"]


def test_a_routes_file_without_a_router_factory_fails_loudly(syspath: Path) -> None:
    """Silently skipping it would drop that file's routes from the app without anyone noticing."""
    _make_pkg(syspath, "a05_fake_bad", {"routes_broken.py": "router = None\n"})
    import a05_fake_bad  # type: ignore[import-not-found]

    with pytest.raises(TypeError, match="routes_broken"):
        discover_routers(a05_fake_bad)


def test_a_router_factory_returning_the_wrong_type_fails_loudly(syspath: Path) -> None:
    _make_pkg(syspath, "a05_fake_type", {"routes_odd.py": "def router():\n    return object()\n"})
    import a05_fake_type  # type: ignore[import-not-found]

    with pytest.raises(TypeError, match="routes_odd"):
        discover_routers(a05_fake_type)
