"""Determinism guard (system-design.md §5): the engine must be pure, and oracles never reach runtime."""

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "iip"
ENGINE = ROOT / "engine"

FORBIDDEN_MODULES = {"random", "requests", "httpx", "urllib", "socket", "sqlite3", "time", "os", "subprocess"}
FORBIDDEN_CALLS = {("datetime", "now"), ("datetime", "today"), ("date", "today"), ("datetime", "utcnow")}
ORACLES = {"QuantLib", "pyxirr", "scoringrules", "scores"}


def _imports(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_engine_has_no_io_clock_or_unseeded_randomness() -> None:
    offenders: list[str] = []
    for path in ENGINE.rglob("*.py"):
        tree = ast.parse(path.read_text())
        bad = _imports(tree) & FORBIDDEN_MODULES
        if bad:
            offenders.append(f"{path.name}: imports {sorted(bad)}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if (node.value.id, node.attr) in FORBIDDEN_CALLS:
                    offenders.append(f"{path.name}:{node.lineno} uses {node.value.id}.{node.attr}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Decimal":
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, float):
                    offenders.append(f"{path.name}:{node.lineno} Decimal(float literal)")
    assert not offenders, offenders


def test_numpy_random_only_with_explicit_generator() -> None:
    for path in ENGINE.rglob("*.py"):
        src = path.read_text()
        assert "np.random.seed" not in src and "numpy.random.seed" not in src, path
        assert "np.random.rand" not in src, f"{path}: use np.random.default_rng(seed)"


def test_runtime_never_imports_test_oracles() -> None:
    for path in ROOT.rglob("*.py"):
        assert not (_imports(ast.parse(path.read_text())) & ORACLES), f"{path} imports an oracle library"
