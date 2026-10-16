"""WP B05: backtest runner, walk-forward, gates G1-G14 (fail closed), pre-registered specs and the local CLI.

Acceptance checks (PLAN.md §5.3, row B05):
* a synthetic zero-skill fixture ends in ABSTAIN/NO_SIGNAL;
* shuffle canary (it flags a leaky pipeline and passes the honest one);
* re-running a manifest reproduces ``output_hash``;
* lag / purge / embargo / fill_rule are mandatory with no default; G1-G14 fail closed with reason codes; regimes use
  pre-vault data only; trials are logged automatically; backtests run only in the local CLI; hosted import holds no
  raw NAVs; results are never written into the repo.
All data is synthetic (``_backtest_fixtures``)."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import replace
from datetime import date
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
import yaml

from iip import backtest_cli
from iip.engine.backtest import walkforward as wf
from iip.engine.errors import InvalidInput
from iip.services import backtest_runner as br
from iip.store import ledger as lg
from iip.store.db import connect, migrate

from ._backtest_fixtures import NOW, context, zero_skill_panel


@pytest.fixture
def db(tmp_path: Path) -> Any:
    conn = connect(tmp_path / "iip.db")
    migrate(conn, NOW)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def specs() -> dict[str, tuple[br.SignalSpec, str]]:
    return br.load_registered_specs()


def _ctx(spec: br.SignalSpec, **kw: Any) -> br.RunContext:
    return context(zero_skill_panel(spec.role_keys()), **kw)


# ================================================================================================ specs


def test_four_pre_registered_specs_load(specs: dict[str, tuple[br.SignalSpec, str]]) -> None:
    assert sorted(specs) == ["S-D@1", "S-E@1", "S-F@1", "S-G@1"]
    for spec, _ in specs.values():
        assert spec.status == "PRE_REGISTERED"
        assert tuple(spec.gates) == tuple(f"G{i}" for i in range(1, 15))


def test_specs_name_roles_only_never_schemes_or_results() -> None:
    for p in br.SIGNALS_DIR.glob("S-*.yaml"):
        text = p.read_text()
        no_capital = "\n".join(line for line in text.splitlines() if not line.startswith("capital:"))
        assert not re.search(r"\b\d{6}\b", no_capital), f"{p.name}: looks like a scheme code"
        assert not re.search(r"\bIN[FE]\w{9}\b", text), f"{p.name}: looks like an ISIN"
        lowered = text.lower()
        for word in ("sharpe:", "cagr", "output_hash", "verdict:"):
            assert word not in lowered, f"{p.name}: carries a result ({word})"


def test_s_d_uses_a_liquid_fund_nav_hurdle_not_t_bills(specs: dict[str, tuple[br.SignalSpec, str]]) -> None:
    spec, text = specs["S-D@1"]
    assert spec.rule.kind == "abs_momentum"
    assert spec.roles["hurdle"].role == "liquid_fund.direct"
    assert "tbill" not in text.replace("T-bill", "")


def test_schema_yaml_matches_the_loader_model() -> None:
    schema = yaml.safe_load(br.SCHEMA_PATH.read_text())
    required = {f.alias or name for name, f in br.SignalSpec.model_fields.items() if f.is_required()}
    assert set(schema["required"]) == required


def _spec_dict(specs: dict[str, tuple[br.SignalSpec, str]], key: str = "S-E@1") -> dict[str, Any]:
    return yaml.safe_load(specs[key][1])


@pytest.mark.parametrize("field", ["lag", "purge", "embargo", "fill_rule"])
def test_walk_forward_arguments_are_mandatory_in_the_spec(
    specs: dict[str, tuple[br.SignalSpec, str]], field: str
) -> None:
    data = _spec_dict(specs)
    del data["walk_forward"][field]
    with pytest.raises(br.SpecError):
        br._spec_from_text(yaml.safe_dump(data), "x")


def test_walk_forward_arguments_have_no_default_in_the_engine() -> None:
    fill = wf.FillRule(name="f", nav_offset=1, switch_cash_gap=3)
    with pytest.raises(TypeError):
        wf.WalkForwardConfig(purge=1, embargo=1, fill_rule=fill)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        wf.WalkForwardConfig(lag=1, embargo=1, fill_rule=fill)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        wf.WalkForwardConfig(lag=1, purge=1, fill_rule=fill)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        wf.WalkForwardConfig(lag=1, purge=1, embargo=1)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        wf.FillRule(name="f", nav_offset=1)  # type: ignore[call-arg]
    with pytest.raises(InvalidInput):
        wf.FillRule(name="same_day", nav_offset=0, switch_cash_gap=0)  # fill must be strictly after the decision


def test_spec_refuses_equity_increasing_tilt(specs: dict[str, tuple[br.SignalSpec, str]]) -> None:
    data = _spec_dict(specs)
    data["tilt_bounds"]["max"] = "0.10"
    with pytest.raises(br.SpecError):
        br._spec_from_text(yaml.safe_dump(data), "x")


# ================================================================================================ zero skill


@pytest.mark.parametrize("key", ["S-E@1", "S-D@1", "S-F@1", "S-G@1"])
def test_zero_skill_fixture_ends_in_abstain_or_no_signal(
    db: sqlite3.Connection, specs: dict[str, tuple[br.SignalSpec, str]], key: str
) -> None:
    spec, text = specs[key]
    bundle = br.run_backtest(db, spec, text, _ctx(spec))
    assert bundle.verdict in ("ABSTAIN", "NO_SIGNAL")
    assert bundle.reason_code
    gates = json.loads(bundle.run["gates_json"])
    assert [g["gate_id"] for g in gates] == [f"G{i}" for i in range(1, 15)]
    by_id = {g["gate_id"]: g for g in gates}
    assert by_id["G10"]["status"] == "abstain" or by_id["G10"]["status"] == "fail"
    assert by_id["G11"]["reason_code"] == "vault_sealed"
    assert by_id["G13"]["reason_code"] == "loss_budget_missing"
    for g in gates:
        assert g["passed"] == (g["status"] == "pass")
        if not g["passed"]:
            assert g["reason_code"], g
    row = db.execute("SELECT state, state_reason FROM signal_rules WHERE rule_id=?", (spec.id,)).fetchone()
    assert row["state"] == bundle.verdict and row["state_reason"] == bundle.reason_code
    assert db.execute("SELECT vault_opened FROM backtest_runs").fetchone()[0] == 0


# ================================================================================================ canary


def test_shuffle_canary_passes_the_honest_pipeline_and_flags_a_leaky_one() -> None:
    panel = zero_skill_panel(["index_fund.nifty50.direct", "liquid_fund.direct"])
    risk = panel.navs["index_fund.nifty50.direct"]
    dates = panel.dates

    def leaky(p: wf.NavPanel) -> list[float]:
        # Peeks one month ahead: "hold" only when next month's return is positive. A leak by construction.
        xs = p.navs["index_fund.nifty50.direct"]
        dec = wf.decision_indices(p.dates, 1)
        out = []
        for a, b in pairwise(dec):
            r = float(xs[b] / xs[a] - 1)
            out.append(max(r, 0.0) + 0.0001)
        return out

    assert len(risk) == len(dates)
    bad = wf.shuffle_canary(panel, leaky, seed=11, replicates=3)
    assert not bad.passed
    spec, _ = br.load_registered_specs()["S-E@1"]
    setup = br._setup(spec, context(panel))
    good = wf.shuffle_canary(panel, lambda p: wf.run_walk_forward(p, setup).oos_edges, seed=11, replicates=3)
    assert good.passed
    again = wf.shuffle_canary(panel, lambda p: wf.run_walk_forward(p, setup).oos_edges, seed=11, replicates=3)
    assert again == good  # seeded: deterministic


# ================================================================================================ reproduce


def test_rerunning_a_manifest_reproduces_output_hash(
    db: sqlite3.Connection, specs: dict[str, tuple[br.SignalSpec, str]]
) -> None:
    spec, text = specs["S-E@1"]
    ctx = _ctx(spec)
    bundle = br.run_backtest(db, spec, text, ctx)
    assert br.rerun_manifest(bundle.run["manifest_json"], spec, text, ctx) == bundle.output_hash
    # A second logged run on the same data reproduces the same hash, and does not add trials.
    n = lg.count_trials(db, spec.family)
    again = br.run_backtest(db, spec, text, replace(ctx, created_at="2026-10-17T05:00:00+00:00"))
    assert again.output_hash == bundle.output_hash
    assert lg.count_trials(db, spec.family) == n
    # Different data → the manifest refuses (it never silently reproduces something else).
    other = replace(ctx, panel=zero_skill_panel(spec.role_keys(), seed=8))
    with pytest.raises(InvalidInput):
        br.rerun_manifest(bundle.run["manifest_json"], spec, text, other)


# ================================================================================================ trials


def test_trials_are_logged_before_the_run_even_if_it_crashes(
    db: sqlite3.Connection, specs: dict[str, tuple[br.SignalSpec, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec, text = specs["S-E@1"]

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("crash mid-run")

    monkeypatch.setattr(br, "_walk", boom)
    with pytest.raises(RuntimeError):
        br.run_backtest(db, spec, text, _ctx(spec))
    # main configuration + 2 pre-registered neighbours are all counted (G8).
    assert lg.count_trials(db, spec.family) == 1 + len(spec.neighbours)


def test_family_n_grows_with_every_new_configuration(
    db: sqlite3.Connection, specs: dict[str, tuple[br.SignalSpec, str]]
) -> None:
    spec, text = specs["S-E@1"]
    ctx = _ctx(spec)
    br.run_backtest(db, spec, text, ctx)
    n1 = lg.count_trials(db, spec.family)
    br.run_backtest(db, spec, text, replace(ctx, panel=zero_skill_panel(spec.role_keys(), seed=9)))
    assert lg.count_trials(db, spec.family) == 2 * n1  # new data snapshot = new trials
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("DELETE FROM backtest_trials")


# ================================================================================================ vault, regimes


def test_vault_navs_never_reach_the_walk_forward(specs: dict[str, tuple[br.SignalSpec, str]]) -> None:
    spec, _ = specs["S-E@1"]
    panel = zero_skill_panel(spec.role_keys())
    setup = br._setup(spec, context(panel))
    res = wf.run_walk_forward(panel, setup)
    assert res.vault_start is not None and res.n_vault_periods >= 36
    cut = panel.dates.index(res.vault_start)
    poisoned = wf.NavPanel(
        panel.dates,
        {r: v[: cut + 1] + tuple(x * 7 for x in v[cut + 1 :]) for r, v in panel.navs.items()},
    )
    again = wf.run_walk_forward(poisoned, setup)
    assert again.oos_edges == res.oos_edges
    assert all(p.end <= res.vault_start for p in res.periods)


def test_regimes_use_pre_vault_periods_only(specs: dict[str, tuple[br.SignalSpec, str]]) -> None:
    spec, _ = specs["S-E@1"]
    panel = zero_skill_panel(spec.role_keys())
    res = wf.run_walk_forward(panel, br._setup(spec, context(panel)))
    assert [r.regime_id for r in res.regimes] == [r.id for r in spec.regimes]
    assert sum(r.n_periods for r in res.regimes) == len(res.periods)
    assert res.vault_start is not None
    assert all(p.start < res.vault_start for p in res.periods)


# ================================================================================================ bundles / hosted


def _forbidden_keys(obj: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in br.FORBIDDEN_BUNDLE_KEYS:
                found.add(k)
            found |= _forbidden_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            found |= _forbidden_keys(v)
    elif isinstance(obj, str) and obj[:1] in "{[":
        found |= _forbidden_keys(json.loads(obj))
    return found


def test_bundle_holds_no_raw_navs_and_imports_into_a_hosted_db(
    db: sqlite3.Connection, specs: dict[str, tuple[br.SignalSpec, str]], tmp_path: Path
) -> None:
    spec, text = specs["S-E@1"]
    ctx = _ctx(spec)
    bundle = br.run_backtest(db, spec, text, ctx)
    payload = bundle.to_json()
    assert not _forbidden_keys(json.loads(payload))
    some_nav = str(ctx.panel.navs["index_fund.nifty50.direct"][500])
    assert some_nav not in payload
    hosted = connect(tmp_path / "hosted.db")
    migrate(hosted, NOW)
    assert br.import_evidence_bundle(hosted, payload) is True
    assert br.import_evidence_bundle(hosted, payload) is False  # idempotent
    row = hosted.execute("SELECT output_hash, verdict FROM backtest_runs").fetchone()
    assert row["output_hash"] == bundle.output_hash and row["verdict"] == bundle.verdict
    hosted.close()


def test_tampered_or_raw_data_bundles_are_rejected(
    db: sqlite3.Connection, specs: dict[str, tuple[br.SignalSpec, str]]
) -> None:
    spec, text = specs["S-E@1"]
    b = json.loads(br.run_backtest(db, spec, text, _ctx(spec)).to_json())
    tampered = dict(b, run=dict(b["run"], verdict="ACCEPTED"))
    with pytest.raises(br.BundleRejected, match="hash"):
        br.verify_bundle(json.dumps(tampered))
    raw = dict(b, trial=dict(b["trial"], navs=[1, 2, 3]))
    body = {"trial": raw["trial"], "run": raw["run"], "neighbour_trials": raw["neighbour_trials"]}
    raw["bundle_hash"] = br.content_hash(body)
    with pytest.raises(br.BundleRejected, match="raw market data"):
        br.verify_bundle(json.dumps(raw))


# ================================================================================================ CLI


def test_cli_refuses_hosted_mode(capsys: pytest.CaptureFixture[str]) -> None:
    assert backtest_cli.main(["list"], {"IIP_DEPLOY": "vercel"}) == backtest_cli.EXIT_REFUSED
    assert backtest_cli.main(["list"], {"VERCEL": "1"}) == backtest_cli.EXIT_REFUSED
    assert "local CLI" in capsys.readouterr().err


def test_cli_lists_specs(capsys: pytest.CaptureFixture[str]) -> None:
    assert backtest_cli.main(["list"], {}) == 0
    out = capsys.readouterr().out
    for key in ("S-D@1", "S-E@1", "S-F@1", "S-G@1"):
        assert key in out


def test_cli_refuses_to_write_results_into_a_git_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    out = repo / "results" / "bundle.json"
    rc = backtest_cli.main(["run", "S-E", "--out", str(out)], {"IIP_DATA_DIR": str(tmp_path / "data")})
    assert rc == backtest_cli.EXIT_REFUSED
    assert not out.exists()
    # The repository itself is a git working tree too.
    assert backtest_cli.inside_git_worktree(Path(br.__file__))


def test_cli_requires_role_bindings(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = backtest_cli.main(
        ["run", "S-E", "--out", str(tmp_path / "out" / "b.json")], {"IIP_DATA_DIR": str(tmp_path / "data")}
    )
    assert rc == backtest_cli.EXIT_REFUSED
    assert "REQUIRES CONFIGURATION" in capsys.readouterr().err


def _seed_local_db(path: Path, roles: tuple[str, ...]) -> wf.NavPanel:
    panel = zero_skill_panel(roles)
    conn = connect(path)
    migrate(conn, NOW)
    for n, role in enumerate(roles, 1):
        iid, code = f"mf:99000{n}", f"99000{n}"  # fictional
        conn.execute(
            "INSERT INTO instruments(instrument_id, kind, name, amfi_code, origin, created_at)"
            " VALUES (?, 'mf_scheme', ?, ?, 'fixture', ?)",
            (iid, f"Fictional Fund {n}", code, NOW),
        )
        conn.executemany(
            "INSERT INTO observations(series_id, kind, value, unit, currency, observation_date, retrieved_at,"
            " source_id, source_url, quality_status, raw_sha256) VALUES (?, 'nav', ?, 'INR', 'INR', ?, ?,"
            " 'amfi.navall', 'https://example.invalid/fixture', 'fixture', ?)",
            [
                (f"nav:{code}", str(v), d.isoformat(), NOW, "0" * 64)
                for d, v in zip(panel.dates, panel.navs[role], strict=True)
            ],
        )
        lg.bind_roles(conn, [lg.RoleBinding(role=role, instrument_id=iid, rule_of_choice="fixture", bound_at=NOW)])
    conn.close()
    return panel


def test_cli_end_to_end_on_a_synthetic_local_db(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    roles = ("index_fund.nifty50.direct", "liquid_fund.direct")
    data = tmp_path / "data"
    data.mkdir()
    _seed_local_db(data / "iip.db", roles)
    out = tmp_path / "bundles" / "s-e.json"
    rc = backtest_cli.main(
        ["run", "S-E", "--out", str(out), "--canary-replicates", "2", "--created-at", NOW],
        {"IIP_DATA_DIR": str(data)},
    )
    assert rc == 0, capsys.readouterr().err
    b = br.verify_bundle(out.read_text())
    assert b["verdict"] in ("ABSTAIN", "NO_SIGNAL")
    gates = {g["gate_id"]: g for g in json.loads(b["run"]["gates_json"])}
    # No adapter from rules/tax to the backtest tax table yet, and the real levy rows start in 2020/2024: fail closed.
    assert gates["G6"]["status"] == "abstain"
    assert gates["G6"]["reason_code"] in ("cost_rules_missing", "tax_rules_missing")
    assert backtest_cli.main(["verify", str(out)], {}) == 0


# ================================================================================================ misc


def test_spec_hash_is_of_the_registered_text(
    db: sqlite3.Connection, specs: dict[str, tuple[br.SignalSpec, str]]
) -> None:
    spec, text = specs["S-G@1"]
    br.run_backtest(db, spec, text, _ctx(spec))
    row = db.execute("SELECT spec_hash, spec_yaml, registered_at FROM signal_rules WHERE rule_id='S-G'").fetchone()
    assert row["spec_yaml"] == text and row["spec_hash"] == br.spec_hash(text)
    assert date.fromisoformat(row["registered_at"][:10]) == date(2026, 10, 16)


def test_stats_show_power_and_decay_haircut(
    db: sqlite3.Connection, specs: dict[str, tuple[br.SignalSpec, str]]
) -> None:
    spec, text = specs["S-E@1"]
    b = br.run_backtest(db, spec, text, _ctx(spec))
    stats = json.loads(b.run["stats_json"])["stats"]
    for key in (
        "n_trials",
        "min_trl_periods",
        "power_80_periods",
        "earliest_review",
        "post_publication",
        "expected_excess_after_decay_haircut",
        "regimes",
        "canary",
        "vault_start",
    ):
        assert key in stats
    if stats["mean_edge_per_period"] is not None:
        assert Decimal(stats["expected_excess_after_decay_haircut"]) == pytest.approx(
            Decimal(stats["mean_edge_per_period"]) * Decimal("0.5"), abs=Decimal("0.000002")
        )
