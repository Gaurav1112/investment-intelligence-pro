"""A05 / RC-5: the cold-start import path must not pay for scipy.

scipy is imported only inside the engine functions that use it (XIRR, YTM, Ljung-Box, forecast validation), so
``/api/health``, ``/api/me`` and the other light routes never load it. Each check runs in a fresh interpreter: inside
the test process scipy is already imported by other tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"


def _modules_after(code: str) -> set[str]:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(SRC), os.environ.get("PYTHONPATH", "")])}
    out = subprocess.run(
        [sys.executable, "-c", f"{code}\nimport sys\nprint('\\n'.join(sorted(sys.modules)))"],
        capture_output=True, text=True, env=env, check=True, timeout=120,
    )  # fmt: skip
    return set(out.stdout.split())


def _scipy(mods: set[str]) -> list[str]:
    return sorted(m for m in mods if m == "scipy" or m.startswith("scipy."))


def test_importing_the_app_does_not_import_scipy() -> None:
    mods = _modules_after("import iip.api.app")
    assert "iip.api.app" in mods
    assert _scipy(mods) == []


def test_building_every_router_does_not_import_scipy() -> None:
    """The hosted entrypoint imports the router registry and calls it at cold start."""
    mods = _modules_after("from iip.api.routes import all_routers\nall_routers()")
    assert "iip.api.routes_core" in mods
    assert _scipy(mods) == []


def test_engine_modules_import_without_scipy() -> None:
    mods = _modules_after(
        "import iip.engine.returns, iip.engine.fixed_income, iip.engine.stats.metrics,"
        " iip.engine.forecasting.validation"
    )
    assert _scipy(mods) == []


def test_scipy_is_loaded_on_first_use() -> None:
    """The lazy shims still reach the real scipy functions (numerics are covered by the oracle tests)."""
    from iip.engine import fixed_income, returns
    from iip.engine.forecasting import validation
    from iip.engine.stats import metrics

    assert 0.0 < float(validation.stats.chi2.sf(1.0, 1)) < 1.0
    assert 0.0 < float(metrics.sps.chi2.sf(1.0, 1)) < 1.0
    assert abs(float(returns.brentq(lambda x: x - 0.25, 0.0, 1.0)) - 0.25) < 1e-9
    assert abs(float(fixed_income.brentq(lambda x: x - 0.5, 0.0, 1.0)) - 0.5) < 1e-9
    ext = returns.minimize_scalar(lambda x: (x - 0.5) ** 2, bounds=(0.0, 1.0), method="bounded")
    assert abs(float(ext.x) - 0.5) < 1e-4
