"""SIG-1: the shadow evaluator reads the COMMITTED spec schema (``rules/signals/schema.yaml``), one contract.

Every committed spec is registered as it is in the repository; every role it names is bound to a SYNTHETIC instrument
with SYNTHETIC month-end NAVs (fictional codes 9720xx, origin 'fixture'). Shadow evaluation must then never abstain
for a spec-field reason; a family the shadow evaluator does not implement yet abstains with ``family_not_implemented``.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from iip.services import shadow
from iip.services.backtest_runner import load_registered_specs
from iip.store import ledger
from tests.services import _snapshot_fixtures as fx

IMPLEMENTED = {"trend_sma", "abs_momentum"}
MONTHS = [f"{y:04d}-{m:02d}" for y in (2024, 2025, 2026) for m in range(1, 13) if f"{y:04d}-{m:02d}" <= "2026-09"]


@pytest.fixture
def conn(tmp_path: Path) -> Any:
    c = fx.open_db(tmp_path / "iip.db")
    yield c
    c.close()


def _bind_every_committed_role(conn: Any) -> None:
    roles = sorted({r.role for spec, _ in load_registered_specs().values() for r in spec.roles.values()})
    binds = []
    for i, role in enumerate(roles):
        iid, code = f"mf:9720{i:02d}", f"9720{i:02d}"
        fx.add_scheme(conn, iid, code, f"Fictional Fund {i}", "Synthetic Category")
        binds.append(ledger.RoleBinding(role, iid, "fixture", fx.NOW))
        # synthetic, strictly rising NAVs, a different slope per role
        ledger.upsert_series_grid(
            conn,
            [
                ledger.GridPoint(iid, m, f"{m}-28", Decimal(100 + (i + 1) * k), None, fx.NOW)
                for k, m in enumerate(MONTHS)
            ],
        )
    ledger.bind_roles(conn, binds)


def _register_committed(conn: Any) -> dict[str, Any]:
    """Explicit registration of the committed text (run_shadow's own J4 registration then finds them present)."""
    specs = load_registered_specs()
    for spec, text in specs.values():
        fx.register_s_rule(conn, spec.id, text, version=spec.version)
    return specs


def test_every_committed_spec_is_evaluated_without_a_spec_field_abstention(conn: Any) -> None:
    specs = _register_committed(conn)
    assert specs, "no committed specs found"
    _bind_every_committed_role(conn)
    run = shadow.run_shadow(conn, as_of=fx.AS_OF, snapshot_id="a" * 64, now=fx.NOW)
    assert run.rules == len(specs)
    rows = {f"{r['rule_id']}@{r['version']}": r for r in conn.execute("SELECT * FROM rule_evaluations")}
    assert set(rows) == set(specs)
    for key, (spec, _text) in specs.items():
        p = json.loads(rows[key]["payload_json"])
        reason = p["reason"] or ""
        assert not reason.startswith("spec_"), (key, reason)
        if spec.rule.kind in IMPLEMENTED:
            assert rows[key]["condition_met"] in (0, 1), (key, reason)
            assert p["evaluation"] == shadow.EVALUATED
            assert p["instruments"]["in"] and p["position_if_met"] == "in" and p["position_if_not_met"] == "out"
            assert rows[key]["scope_id"] == f"role:{spec.roles['risk'].role}"
        else:
            assert rows[key]["condition_met"] is None
            assert reason == "family_not_implemented", (key, reason)


def test_unbound_committed_roles_abstain_with_role_unbound_not_a_spec_field(conn: Any) -> None:
    _register_committed(conn)
    shadow.run_shadow(conn, as_of=fx.AS_OF, snapshot_id="a" * 64, now=fx.NOW)
    for r in conn.execute("SELECT payload_json FROM rule_evaluations"):
        reason = json.loads(r["payload_json"])["reason"]
        assert reason == "family_not_implemented" or reason.startswith("role_unbound:"), reason


def test_a_spec_that_fails_the_committed_schema_abstains_with_spec_invalid(conn: Any) -> None:
    fx.register_s_rule(conn, "S-Z", "id: S-Z\nversion: 1\nfamily: trend_timing\nroles: {in: x.y, out: x.z}\n")
    shadow.run_shadow(conn, specs_dir=None, as_of=fx.AS_OF, snapshot_id="a" * 64, now=fx.NOW)
    row = conn.execute("SELECT condition_met, payload_json FROM rule_evaluations").fetchone()
    assert row["condition_met"] is None and json.loads(row["payload_json"])["reason"] == "spec_invalid"
