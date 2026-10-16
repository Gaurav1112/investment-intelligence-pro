"""SIG-2: the committed signal specs are registered at deterministic WRITE points (job J4's shadow step and the local
backtest CLI), never at cold start. Registration is content-hashed, append-only and idempotent; a rule with no backtest
run shows ``ABSTAIN`` / "no backtest run yet".

All ids, NAVs and bindings here are SYNTHETIC and fictional.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from iip import backtest_cli
from iip.services import risk_snapshot as rs
from iip.services import shadow, signal_registry
from iip.services.backtest_runner import SIGNALS_DIR, load_registered_specs
from iip.services.signals_view import signals_response
from iip.store import ledger
from iip.store.db import connect, migrate
from tests.services import _snapshot_fixtures as fx

LATER = "2026-10-17T05:00:00+00:00"


@pytest.fixture
def conn(tmp_path: Path) -> Any:
    c = fx.open_db(tmp_path / "iip.db")
    yield c
    c.close()


def _registry(conn: Any) -> dict[str, Any]:
    return {f"{r['rule_id']}@{r['version']}": dict(r) for r in conn.execute("SELECT * FROM signal_rules")}


def test_committed_specs_register_content_hashed_with_no_backtest_run_yet(conn: Any) -> None:
    specs = load_registered_specs()
    res = signal_registry.register_committed_specs(conn, now=fx.NOW)
    assert (res.registered, res.already_registered, res.conflicts, res.rejected) == (len(specs), 0, (), ())
    reg = _registry(conn)
    assert set(reg) == set(specs)
    for key, (spec, text) in specs.items():
        row = reg[key]
        assert row["spec_yaml"] == text
        assert row["spec_hash"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert (row["class"], row["family"]) == ("S", spec.family)
        assert (row["state"], row["state_reason"]) == ("ABSTAIN", signal_registry.NO_BACKTEST_RUN_YET)
        assert row["registered_at"] == fx.NOW == row["state_changed_at"]


def test_registration_is_idempotent_and_append_only(conn: Any) -> None:
    signal_registry.register_committed_specs(conn, now=fx.NOW)
    before = _registry(conn)
    again = signal_registry.register_committed_specs(conn, now=LATER)
    assert (again.registered, again.already_registered) == (0, len(before))
    assert _registry(conn) == before  # registered_at keeps the first registration


def test_a_changed_spec_under_the_same_version_is_reported_not_overwritten(conn: Any, tmp_path: Path) -> None:
    signal_registry.register_committed_specs(conn, now=fx.NOW)
    before = _registry(conn)
    edited = tmp_path / "signals"
    edited.mkdir()
    text = (SIGNALS_DIR / "S-E@1.yaml").read_text(encoding="utf-8")
    (edited / "S-E@1.yaml").write_text(text.replace("10-month trend filter", "10 month trend filter"), "utf-8")
    (edited / "S-Q@1.yaml").write_text("id: S-Q\nversion: 1\n", "utf-8")  # fails the committed schema
    res = signal_registry.register_committed_specs(conn, now=LATER, directory=edited)
    assert res.registered == 0 and res.conflicts == ("S-E@1",) and res.rejected == ("S-Q@1.yaml",)
    assert _registry(conn) == before


def test_j4_daily_step_registers_the_committed_specs_on_a_fresh_install(conn: Any) -> None:
    assert _registry(conn) == {}  # migrations alone (cold start) register nothing
    fx.seed_two_goals(conn)
    daily = rs.run_daily(conn, as_of=fx.AS_OF, now=fx.NOW, stress_table=fx.stress_table(), templates=fx.TEMPLATES)
    specs = load_registered_specs()
    assert set(_registry(conn)) == set(specs)
    assert daily.shadow.rules == len(specs) and daily.shadow.registered == len(specs)
    view = {f"{r['rule_id']}@{r['version']}": r for r in signals_response(conn)["rules"]}
    assert set(view) == set(specs)
    for r in view.values():
        assert (r["state"], r["state_reason"]) == ("ABSTAIN", "no backtest run yet")
        assert r["failing_gate"]["reason_code"] == "no_backtest_run"
        assert r["shadow"]["evaluations"] == 1  # evidence accrues from the first daily run
    today = rs.read_today(conn)
    assert all(c["kind"] != "SIGNAL_TILT" for c in today["cards"])


def test_shadow_without_a_spec_directory_registers_nothing(conn: Any) -> None:
    run = shadow.run_shadow(conn, as_of=fx.AS_OF, snapshot_id="a" * 64, now=fx.NOW, specs_dir=None)
    assert run.rules == 0 and _registry(conn) == {}


def test_local_cli_run_registers_every_committed_spec(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = tmp_path / "data"
    data.mkdir()
    c = connect(data / "iip.db")
    migrate(c, fx.NOW)
    c.close()
    rc = backtest_cli.main(
        ["run", "S-E", "--out", str(tmp_path / "out" / "b.json"), "--created-at", fx.NOW], {"IIP_DATA_DIR": str(data)}
    )
    assert rc == backtest_cli.EXIT_REFUSED  # no role bindings yet
    assert "REQUIRES CONFIGURATION" in capsys.readouterr().err
    c = connect(data / "iip.db")
    try:
        assert set(_registry(c)) == set(load_registered_specs())
        assert ledger.role_bindings(c) == {}
    finally:
        c.close()
