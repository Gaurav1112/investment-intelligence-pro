"""`scripts/turso_latency_probe.py` (PLAN A01, runbook `docs/operations/turso-bom1-move.md`, decision U-12).

Hermetic: a fake client and a fake clock stand in for Turso, so every latency below is exact and synthetic. One test
runs the probe's statements against a LOCAL libSQL file migrated to the real schema (no network), to prove the SQL
is valid for the app's tables."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "turso_latency_probe.py"
TOKEN = "synthetic-token-" + "x" * 40  # fictional; must never be printed
URL = "libsql://fictional-db-fictional-org.turso.io"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("turso_latency_probe", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["turso_latency_probe"] = module
    spec.loader.exec_module(module)
    return module


probe_mod = _load()


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class FakeCursor:
    def fetchall(self) -> list[tuple[int]]:
        return [(1,)]


class FakeClient:
    """Advances the shared clock by a fixed synthetic latency per statement."""

    def __init__(self, clock: FakeClock, latency_s: dict[str, float]) -> None:
        self.clock = clock
        self.latency_s = latency_s
        self.executed: list[str] = []

    def execute(self, sql: str) -> FakeCursor:
        self.executed.append(sql)
        self.clock.now += self.latency_s[sql]
        return FakeCursor()


def _latencies(scale: float) -> dict[str, float]:
    return {sql: scale * (i + 1) for i, (_, sql) in enumerate(probe_mod.STATEMENTS)}


def _env() -> dict[str, str]:
    return {"IIP_DB_URL": URL, "IIP_DB_AUTH_TOKEN": TOKEN}


def _run(argv: list[str], env: dict[str, str], latency_scale: float = 0.4) -> tuple[int, str, FakeClient | None]:
    clock = FakeClock()
    made: list[FakeClient] = []

    def connect(url: str, token: str) -> FakeClient:
        assert url == env.get("IIP_DB_URL") or url == env.get("TURSO_DATABASE_URL")
        clock.now += 0.25  # synthetic connect cost
        client = FakeClient(clock, _latencies(latency_scale))
        made.append(client)
        return client

    out = io.StringIO()
    code = probe_mod.main(argv, env=env, connect=connect, clock=clock, stdout=out)
    return code, out.getvalue(), (made[0] if made else None)


def test_probe_records_exact_per_statement_latency_and_skips_warmup() -> None:
    clock = FakeClock()
    client = FakeClient(clock, _latencies(0.4))
    samples = probe_mod.probe(client, probe_mod.STATEMENTS, repeats=3, clock=clock, warmup=1)
    n = len(probe_mod.STATEMENTS)
    assert len(client.executed) == 4 * n  # 1 warm-up round + 3 measured rounds
    assert len(samples) == 3 * n
    by_name = {name: [s.ms for s in samples if s.statement == name] for name, _ in probe_mod.STATEMENTS}
    for i, (name, _) in enumerate(probe_mod.STATEMENTS):
        assert by_name[name] == pytest.approx([400.0 * (i + 1)] * 3)


def test_summary_uses_median_and_nearest_rank_p90() -> None:
    samples = [probe_mod.Sample("noop", float(ms)) for ms in (5, 1, 4, 2, 3, 10, 9, 8, 7, 6)]
    summary = probe_mod.summarise(samples)["noop"]
    assert summary == {"n": 10, "min": 1.0, "median": 5.5, "p90": 9.0, "max": 10.0}


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO settings VALUES (1)",
        "UPDATE web_sessions SET last_seen = 1",
        "DELETE FROM instruments",
        "SELECT 1; DROP TABLE instruments",
        "PRAGMA foreign_keys=OFF",
        "  drop table x",
        "WITH x AS (SELECT 1) DELETE FROM instruments",
    ],
)
def test_only_single_read_only_selects_are_accepted(sql: str) -> None:
    with pytest.raises(ValueError, match="read-only"):
        probe_mod.assert_read_only(sql)


def test_builtin_statements_are_read_only() -> None:
    for _, sql in probe_mod.STATEMENTS:
        probe_mod.assert_read_only(sql)


def test_run_prints_every_statement_latency_writes_json_and_never_leaks_the_token(tmp_path: Path) -> None:
    out_file = tmp_path / "before.json"
    code, out, client = _run(["run", "--label", "before", "--repeats", "2", "--out", str(out_file)], _env())
    assert code == 0, out
    assert client is not None
    for i, (name, _) in enumerate(probe_mod.STATEMENTS):
        expected = f"{400.0 * (i + 1):.1f} ms"
        lines = [ln for ln in out.splitlines() if ln.startswith("before") and f" {name} " in ln and expected in ln]
        assert len(lines) >= 2, out  # one line per measured sample
    assert "connect" in out and "250.0 ms" in out
    assert TOKEN not in out
    assert "fictional-db-fictional-org" not in out  # the database name is redacted
    data = json.loads(out_file.read_text())
    assert TOKEN not in out_file.read_text()
    assert data["label"] == "before"
    assert data["connect_ms"] == pytest.approx(250.0)
    assert len(data["samples"]) == 2 * len(probe_mod.STATEMENTS)


def test_compare_prints_per_statement_before_and_after(tmp_path: Path) -> None:
    before, after = tmp_path / "before.json", tmp_path / "after.json"
    assert _run(["run", "--label", "before", "--repeats", "3", "--out", str(before)], _env(), 0.4)[0] == 0
    assert _run(["run", "--label", "after", "--repeats", "3", "--out", str(after)], _env(), 0.008)[0] == 0
    out = io.StringIO()
    code = probe_mod.main(["compare", str(before), str(after)], env={}, stdout=out)
    text = out.getvalue()
    assert code == 0, text
    for i, (name, _) in enumerate(probe_mod.STATEMENTS):
        row = next(ln for ln in text.splitlines() if ln.split() and ln.split()[0] == name)
        assert f"{400.0 * (i + 1):.1f}" in row and f"{8.0 * (i + 1):.1f}" in row
        assert "-98.0 %" in row
    assert "before" in text and "after" in text


def test_turso_env_names_are_accepted_as_fallback() -> None:
    env = {"TURSO_DATABASE_URL": URL, "TURSO_AUTH_TOKEN": TOKEN}
    code, out, _ = _run(["run", "--label", "before", "--repeats", "1"], env)
    assert code == 0, out


def test_missing_configuration_exits_2_without_connecting() -> None:
    code, out, client = _run(["run", "--label", "before"], {})
    assert code == 2
    assert client is None
    assert "IIP_DB_URL" in out


def test_local_file_needs_explicit_flag(tmp_path: Path) -> None:
    env = {"IIP_DB_URL": str(tmp_path / "copy.db")}
    code, out, client = _run(["run", "--label", "dry-run"], env)
    assert code == 2 and client is None
    assert "--allow-local" in out
    code, out, client = _run(["run", "--label", "dry-run", "--allow-local", "--repeats", "1"], env)
    assert code == 0, out


def test_statements_are_valid_against_the_real_schema_on_a_local_libsql_copy(tmp_path: Path) -> None:
    from iip.store.db import connect_libsql, migrate

    db = tmp_path / "copy.db"
    conn = connect_libsql(str(db))
    migrate(conn, "2026-10-16T00:00:00Z")
    conn.close()

    out = io.StringIO()
    code = probe_mod.main(
        ["run", "--label", "dry-run", "--allow-local", "--repeats", "1"], env={"IIP_DB_URL": str(db)}, stdout=out
    )
    assert code == 0, out.getvalue()
    for name, _ in probe_mod.STATEMENTS:
        assert f" {name} " in out.getvalue()


def test_default_connect_is_not_used_by_the_fakes() -> None:
    # Guard against a refactor that drops the injection seam: main() must accept connect/clock/stdout.
    import inspect

    params: dict[str, Any] = dict(inspect.signature(probe_mod.main).parameters)
    assert {"connect", "clock", "stdout", "env"} <= set(params)
