"""Local-only backtest CLI (WP B05): ``python -m iip.backtest_cli {list,run,verify} ...``.

* Runs **only in local mode**: it refuses to start when ``IIP_DEPLOY=vercel`` or a ``VERCEL`` environment is detected
  (backtests need the full NAV history and must never be bounded by a serverless step; design-evidence-first.md §6.3).
* Reads NAVs for the roles the user has bound in ``rule_role_bindings`` (user config; role → scheme never lives in the
  repo) from the local database, aligned on common dates by the TA-2 helper ``align_panel``: undated rows are
  excluded and counted, two different NAVs on one date abstain with ``duplicate_nav_date`` (never last-wins).
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
from iip.engine.backtest.walkforward import CostRateRow, MfCostSchedule, NavPanel, align_panel
from iip.engine.determinism import content_hash
from iip.engine.errors import EngineError, InsufficientHistory
from iip.engine.money import D
from iip.engine.stats.series_grid import to_ist_date
from iip.engine.tax import Verification
from iip.rules.loader import load_tax_rules
from iip.services.backtest_runner import RunContext, load_registered_specs, run_backtest, verify_bundle
from iip.services.signal_registry import register_committed_specs
from iip.store.db import connect, ensure_schema
from iip.store.ledger import role_bindings
from iip.store.observations import current_series

__all__ = [
    "Abstained",
    "Refused",
    "code_version",
    "inside_git_worktree",
    "load_panel",
    "main",
    "mf_cost_schedule",
    "refuse_hosted",
]

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


class Abstained(Refused):
    """The data cannot support a run: the CLI abstains with a reason code instead of guessing."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"ABSTAIN({code}): {detail}")
        self.code = code


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


def _conflicting_dates(rows: Sequence[tuple[object, str]]) -> list[date]:
    """IST dates that carry two different NAVs (identical repeats are not a conflict; the TA-2 helper collapses
    them). Undated or unparseable dates are left to ``align_panel``, which excludes or refuses them."""
    seen: dict[date, Decimal] = {}
    bad: set[date] = set()
    for raw_d, raw_v in rows:
        if raw_d is None or (isinstance(raw_d, str) and not raw_d.strip()):
            continue
        try:
            d, v = to_ist_date(raw_d), D(raw_v)
        except EngineError:
            continue
        if d in seen and seen[d] != v:
            bad.add(d)
        seen.setdefault(d, v)
    return sorted(bad)


def load_panel(
    conn: sqlite3.Connection, roles: Sequence[str]
) -> tuple[NavPanel, tuple[SeriesProvenance, ...], Mapping[str, int]]:
    """NAVs for each bound role, aligned on dates present for every role, built by the TA-2 helper
    (:func:`iip.engine.backtest.walkforward.align_panel`). Returns (panel, provenance, undated rows excluded per role).

    Raises Refused on a missing binding or history; :class:`Abstained` (a code, never a guess) when a role has two
    different NAVs on one date (``duplicate_nav_date``), when a row is malformed (``invalid_nav_row``) or when too
    little aligned history remains (``insufficient_history``)."""

    bindings = role_bindings(conn)
    missing = [r for r in roles if r not in bindings]
    if missing:
        raise Refused(f"REQUIRES CONFIGURATION: bind these roles to schemes first: {missing}")
    series: dict[str, list[tuple[object, str]]] = {}
    prov: list[SeriesProvenance] = []
    for role in roles:
        row = conn.execute("SELECT amfi_code FROM instruments WHERE instrument_id=?", (bindings[role],)).fetchone()
        if row is None or not row["amfi_code"]:
            raise Refused(f"role {role}: the bound instrument has no AMFI code")
        obs = current_series(conn, f"nav:{row['amfi_code']}")
        if not obs:
            raise Refused(f"role {role}: no NAV history stored locally")
        series[role] = [(o["observation_date"], o["value"]) for o in obs]
        clash = _conflicting_dates(series[role])
        if clash:
            shown = ", ".join(d.isoformat() for d in clash[:5]) + (" …" if len(clash) > 5 else "")
            raise Abstained(
                "duplicate_nav_date", f"role {role}: {len(clash)} date(s) carry two different NAVs ({shown})"
            )
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
    try:
        aligned = align_panel(series)
    except InsufficientHistory as exc:
        raise Abstained("insufficient_history", str(exc)) from exc
    except EngineError as exc:
        raise Abstained("invalid_nav_row", str(exc)) from exc
    panel = aligned.panel
    # align_panel keys the panel in sorted role order; keep the caller's role order.
    panel = NavPanel(panel.dates, {r: panel.navs[r] for r in roles})
    return panel, tuple(prov), {r: int(aligned.undated_excluded[r]) for r in roles}


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
        # Every committed spec is registered (idempotent, append-only), so the registry is complete even when this
        # run is refused below for missing configuration (SIG-2).
        register_committed_specs(conn, now=created_at)
        panel, prov, undated = load_panel(conn, spec.role_keys())
        if any(undated.values()):
            print(f"excluded undated NAV rows per role: {dict(sorted(undated.items()))}", file=sys.stderr)
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
