"""Registry of the committed signal specs (SIG-2; PLAN.md wave 2, B02/B05).

The committed pre-registrations (``rules/signals/S-*@*.yaml``) are registered in ``signal_rules`` at deterministic
points that already write, so a fresh install shows them in the Signals registry without anyone running a backtest:

* job J4's shadow step (:func:`iip.services.shadow.run_shadow`), inside the daily write transaction;
* the local backtest CLI (``python -m iip.backtest_cli run``), before it loads any NAV.

Never at cold start: application startup stays read-only (A05).

Registration is content-hashed (``spec_hash`` = SHA-256 of the committed text, exactly what is stored), append-only
and idempotent. A new row is ``ABSTAIN`` / "no backtest run yet" (nothing was evaluated, so nothing passed); a backtest
run later records its verdict state. A committed file whose text differs from the row already registered under the
same ``id@version`` is a CONFLICT: it is reported and the stored row stands (a changed spec must be a new version).
A file that fails the committed schema is REJECTED and reported. Neither stops the caller (the daily job continues
and evaluates what is registered); both are returned so the caller can surface them.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import yaml

from iip.services.backtest_runner import (
    NO_BACKTEST_RUN_YET,
    SIGNALS_DIR,
    SignalSpec,
    SpecError,
    load_signal_spec,
    registry_row,
)
from iip.store import ledger

__all__ = ["NO_BACKTEST_RUN_YET", "SIGNALS_DIR", "RegistryResult", "register_committed_specs"]


@dataclass(frozen=True)
class RegistryResult:
    registered: int  # rows newly appended
    already_registered: int  # same id@version and same spec hash already present
    conflicts: tuple[str, ...]  # id@version registered with a DIFFERENT spec hash (the stored row stands)
    rejected: tuple[str, ...]  # file names that fail the committed schema


def _committed(directory: Path) -> tuple[list[tuple[SignalSpec, str]], list[str]]:
    specs: list[tuple[SignalSpec, str]] = []
    rejected: list[str] = []
    for path in sorted(directory.glob("S-*@*.yaml")):
        try:
            specs.append(load_signal_spec(path))
        except (SpecError, yaml.YAMLError, UnicodeDecodeError):
            rejected.append(path.name)
    return specs, rejected


def register_committed_specs(conn: sqlite3.Connection, *, now: str, directory: Path = SIGNALS_DIR) -> RegistryResult:
    """Register every committed spec in ``directory`` not yet in ``signal_rules``. ``now`` (passed in, no clock)
    stamps ``registered_at`` of new rows only. Statements: one chunked key read, then one batched insert."""
    specs, rejected = _committed(directory)
    if not specs:
        return RegistryResult(0, 0, (), tuple(rejected))
    keys = [(s.id, s.version) for s, _ in specs]
    stored = {
        (r["rule_id"], int(r["version"])): r["spec_hash"]
        for r in ledger.select_by_keys(
            conn, "signal_rules", ("rule_id", "version"), keys, "rule_id, version, spec_hash"
        )
    }
    new: list[ledger.SignalRule] = []
    already = 0
    conflicts: list[str] = []
    for spec, text in specs:
        row = registry_row(spec, text, now)
        have = stored.get((spec.id, spec.version))
        if have is None:
            new.append(row)
        elif have == row.spec_hash:
            already += 1
        else:
            conflicts.append(f"{spec.id}@{spec.version}")
    registered = ledger.register_rules(conn, new)
    return RegistryResult(registered, already, tuple(sorted(conflicts)), tuple(rejected))
