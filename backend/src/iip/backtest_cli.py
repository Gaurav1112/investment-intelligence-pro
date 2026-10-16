"""Local-only backtest CLI (WP B05): ``python -m iip.backtest_cli {list,run,verify} ...``.

* Runs **only in local mode**: it refuses to start when ``IIP_DEPLOY=vercel`` or a ``VERCEL`` environment is detected
  (backtests need the full NAV history and must never be bounded by a serverless step; design-evidence-first.md §6.3).
* Reads NAVs for the roles the user has bound in ``rule_role_bindings`` (user config; role → scheme never lives in the
  repo) from the local database, aligned on common dates.
* Writes an evidence bundle (statistics, gates, hashes; **no raw NAVs**) to a path that must be outside any git
  working tree, so results never land in the repository. The trial log and run rows go to the local database.

Cost rows come from the tax rule table's MF levies (stamp duty on purchases, STT on equity-fund redemptions); trades
before a levy's first row are uncovered and G6 abstains (``cost_rules_missing``). No adapter from ``rules/tax`` to the
backtest tax-lot table exists yet, so the backtest tax table is empty and G6 abstains with ``tax_rules_missing``
(fail closed; see the WP B05 open items).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from iip.data.registry import REGISTRY
from iip.engine.backtest.gates import SeriesProvenance
from iip.engine.backtest.ledger import CostBasisPolicy
from iip.engine.backtest.tax_lots import TaxRateTable
from iip.engine.backtest.walkforward import CostRateRow, MfCostSchedule, NavPanel
from iip.engine.determinism import content_hash
from iip.engine.tax import Verification
from iip.rules.loader import load_tax_rules
from iip.services.backtest_runner import RunContext, load_registered_specs, run_backtest, verify_bundle
from iip.store.db import connect, ensure_schema
from iip.store.ledger import role_bindings
from iip.store.observations import current_series

__all__ = ["code_version", "inside_git_worktree", "load_panel", "main", "mf_cost_schedule", "refuse_hosted"]

EXIT_REFUSED = 2
_STATUS = {Verification.P: "VERIFIED-PRIMARY", Verification.S: "VERIFIED-SECONDARY", Verification.NV: "NOT VERIFIED"}
_LEVY_MAP: Mapping[str, tuple[str, str, frozenset[str]]] = {
    "STAMP-MF-01": ("stamp_duty", "buy", frozenset({"EQUITY", "DEBT", "OTHER"})),
    "STT-MF-01": ("stt", "sell", frozenset({"EQUITY"})),
}
_CODE_FILES = (
    "engine/backtest/walkforward.py",
    "engine/backtest/gates.py",
    "engine/backtest/stats_gates.py",
    "engine/backtest/ledger.py",
    "engine/backtest/tax_lots.py",
    "services/backtest_runner.py",
)


class Refused(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(EXIT_REFUSED)
        self.message = message

    def __str__(self) -> str:
        return self.message


def refuse_hosted(environ: Mapping[str, str]) -> None:
    if environ.get("IIP_DEPLOY", "local") != "local" or environ.get("VERCEL"):
        raise Refused("backtests run only in the local CLI; hosted mode imports evidence bundles instead")


def inside_git_worktree(path: Path) -> bool:
    p = path.resolve()
    return any((d / ".git").exists() for d in (p, *p.parents))


def code_version() -> str:
    root = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for rel in _CODE_FILES:
        h.update(rel.encode())
        h.update((root / rel).read_bytes())
    return "src-sha256:" + h.hexdigest()[:16]


def mf_cost_schedule() -> MfCostSchedule:

    rows = []
    for lv in load_tax_rules(include_historical=True).levies:
        if lv.rule_id in _LEVY_MAP:
            comp, side, classes = _LEVY_MAP[lv.rule_id]
            rows.append(
                CostRateRow(
                    rule_id=lv.rule_id,
                    component=comp,
                    side=side,
                    tax_classes=classes,
                    rate=lv.rate,
                    effective_from=lv.effective_from,
                    effective_to=lv.effective_to,
                    status=_STATUS[lv.verification_status],
                )
            )
    return MfCostSchedule(rows=tuple(rows), slippage_rate=Decimal(0))


def load_panel(conn: sqlite3.Connection, roles: Sequence[str]) -> tuple[NavPanel, tuple[SeriesProvenance, ...]]:
    """NAVs for each bound role, aligned on dates present for every role. Raises Refused on a missing binding."""

    bindings = role_bindings(conn)
    missing = [r for r in roles if r not in bindings]
    if missing:
        raise Refused(f"REQUIRES CONFIGURATION: bind these roles to schemes first: {missing}")
    by_role: dict[str, dict[date, Decimal]] = {}
    prov: list[SeriesProvenance] = []
    for role in roles:
        row = conn.execute("SELECT amfi_code FROM instruments WHERE instrument_id=?", (bindings[role],)).fetchone()
        if row is None or not row["amfi_code"]:
            raise Refused(f"role {role}: the bound instrument has no AMFI code")
        obs = current_series(conn, f"nav:{row['amfi_code']}")
        if not obs:
            raise Refused(f"role {role}: no NAV history stored locally")
        by_role[role] = {date.fromisoformat(o["observation_date"]): Decimal(o["value"]) for o in obs}
        sources = sorted({o["source_id"] for o in obs})
        spec = REGISTRY.get(sources[0]) if len(sources) == 1 else None
        prov.append(
            SeriesProvenance(
                role=role,
                source_id=sources[0] if len(sources) == 1 else "+".join(sources),
                licence_status=spec.status.value if spec else "UNKNOWN",
                known_time_populated=all(o["publication_time"] or o["retrieved_at"] for o in obs),
                snapshot_hash=content_hash([[o["observation_date"], o["value"], o["raw_sha256"]] for o in obs]),
            )
        )
    common = sorted(set.intersection(*(set(v) for v in by_role.values())))
    panel = NavPanel(tuple(common), {r: tuple(by_role[r][d] for d in common) for r in roles})
    return panel, tuple(prov)


def _cmd_list() -> int:

    for key, (spec, _text) in load_registered_specs().items():
        print(f"{key}\t{spec.family}\t{spec.title}\n\texpected: {spec.expected_outcome}")
    return 0


def _cmd_run(args: argparse.Namespace, environ: Mapping[str, str]) -> int:

    out = Path(args.out)
    if inside_git_worktree(out.parent if not out.exists() or out.is_file() else out):
        raise Refused(f"refusing to write results inside a git working tree: {out}")
    specs = load_registered_specs()
    key = args.rule if "@" in args.rule else max((k for k in specs if k.split("@")[0] == args.rule), default="")
    if key not in specs:
        raise Refused(f"unknown signal {args.rule!r}; see `list`")
    spec, text = specs[key]
    created_at = args.created_at or datetime.now(UTC).isoformat(timespec="seconds")
    data_dir = Path(environ.get("IIP_DATA_DIR", str(Path.home() / ".iip")))
    db_path = data_dir / "iip.db"
    if not db_path.is_file():
        raise Refused(f"REQUIRES CONFIGURATION: no local database at {db_path} (store NAV history and role bindings)")
    conn = connect(db_path)
    try:
        ensure_schema(conn, created_at)
        panel, prov = load_panel(conn, spec.role_keys())
        ctx = RunContext(
            panel=panel,
            provenance=prov,
            costs=mf_cost_schedule(),
            cost_policy=CostBasisPolicy(deductible_components=frozenset({"stamp_duty"}), status="NOT VERIFIED"),
            tax_table=TaxRateTable(rows=()),
            code_version=code_version(),
            created_at=created_at,
            canary_replicates=args.canary_replicates,
        )
        # Autocommit on purpose: each trial row is committed before its run starts, so a crash still counts it (G8).
        bundle = run_backtest(conn, spec, text, ctx)
    finally:
        conn.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(bundle.to_json(), encoding="utf-8")
    print(f"{key}: {bundle.verdict}({bundle.reason_code}) output_hash={bundle.output_hash} bundle={out}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:

    b = verify_bundle(Path(args.bundle).read_text(encoding="utf-8"))
    print(f"OK {b['trial']['rule_id']}@{b['trial']['version']}: {b['verdict']} output_hash={b['output_hash']}")
    return 0


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    env = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(prog="iip.backtest_cli", description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list the pre-registered signals")
    run = sub.add_parser("run", help="run one signal's walk-forward and gates (local only)")
    run.add_argument("rule", help="S-E, S-D, S-F, S-G or an explicit id@version")
    run.add_argument("--out", required=True, help="evidence bundle path (outside any git working tree)")
    run.add_argument("--canary-replicates", type=int, default=20)
    run.add_argument("--created-at", default=None, help="ISO-8601 timestamp to record (default: now, UTC)")
    ver = sub.add_parser("verify", help="verify an evidence bundle's hashes and that it holds no raw data")
    ver.add_argument("bundle")
    args = parser.parse_args(argv)
    try:
        refuse_hosted(env)
        if args.cmd == "list":
            return _cmd_list()
        if args.cmd == "run":
            return _cmd_run(args, env)
        return _cmd_verify(args)
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
