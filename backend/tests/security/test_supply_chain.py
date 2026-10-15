"""SEC-85: supply-chain policy — pnpm builds nothing, fresh releases are refused, `make check` checks lockfiles."""

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
WORKSPACE = REPO / "frontend" / "pnpm-workspace.yaml"
MAKEFILE = REPO / "Makefile"


def _recipe(target: str) -> tuple[str, str]:
    """(prerequisites, recipe body) of a Makefile target."""
    text = MAKEFILE.read_text()
    m = re.search(rf"^{re.escape(target)}:([^\n#]*)(?:##[^\n]*)?\n((?:\t[^\n]*\n)*)", text, re.M)
    assert m, f"Makefile has no {target} target"
    return m.group(1), m.group(2)


def test_sec85_pnpm_runs_no_dependency_build_scripts() -> None:
    cfg = yaml.safe_load(WORKSPACE.read_text())
    assert cfg["onlyBuiltDependencies"] == []


def test_sec85_minimum_release_age_is_set() -> None:
    cfg = yaml.safe_load(WORKSPACE.read_text())
    assert isinstance(cfg["minimumReleaseAge"], int) and cfg["minimumReleaseAge"] >= 1440  # ≥ 1 day (7 days set)


def test_sec85_no_locked_package_needs_a_build_step() -> None:
    lock = (REPO / "frontend" / "pnpm-lock.yaml").read_text()
    assert "requiresBuild: true" not in lock


def test_sec85_make_check_verifies_both_lockfiles() -> None:
    prereq, _ = _recipe("check")
    assert "lockcheck" in prereq.split()
    _, body = _recipe("lockcheck")
    assert "uv lock --check" in body
    assert "pnpm install --frozen-lockfile" in body
    assert "onlyBuiltDependencies" in body and "minimumReleaseAge" in body
    _, setup = _recipe("setup")
    assert "uv sync --frozen" in setup and "pnpm install --frozen-lockfile" in setup


def test_sec85_package_scripts_never_run_through_pnpm() -> None:
    """reliability-design §9: scripts run with `node --run` (pnpm only installs, adds and audits)."""
    bad = re.findall(r"\bpnpm (?:run |exec )?(?:build|test|dev|typecheck)\b", MAKEFILE.read_text())
    assert bad == []
