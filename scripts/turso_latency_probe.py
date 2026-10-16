"""Per-statement latency probe for the hosted (Turso / libSQL) database.

Used by the runbook `docs/operations/turso-bom1-move.md` (decision U-12, PLAN package A01): measure BEFORE the move
(today's `iad1` database), measure AFTER (the new `bom1` database), then compare. The post-move latency is NOT
VERIFIED until this script has been run against the new database and the numbers are recorded.

Usage (run from the repo root, with the backend venv that has `libsql` installed):

    IIP_DB_URL=libsql://... IIP_DB_AUTH_TOKEN=... \\
        backend/.venv/bin/python scripts/turso_latency_probe.py run --label before --out before.json
    ... (same, against the new database) run --label after --out after.json
    backend/.venv/bin/python scripts/turso_latency_probe.py compare before.json after.json

Properties:
- Read-only: only single `SELECT` statements are sent; anything else is refused before connecting.
- Never prints or stores the auth token. The database name in the URL is redacted in all output.
- `IIP_DB_URL` / `IIP_DB_AUTH_TOKEN`, falling back to `TURSO_DATABASE_URL` / `TURSO_AUTH_TOKEN` (as the app does).
- A local file (for example the dry-run copy) is accepted only with `--allow-local`.
- Latency is wall-clock time measured where the script runs. Run it from the same place before and after, and read
  it as "client → database", not as "Vercel function → database" (that path is checked on the deployed app).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol, TextIO

# (name, SQL). Read-only, cheap, and valid on the app's schema (migration 0001 creates `instruments`).
STATEMENTS: tuple[tuple[str, str], ...] = (
    ("noop", "SELECT 1"),
    ("catalog", "SELECT COUNT(*) FROM sqlite_master"),
    ("app_read", "SELECT COUNT(*) FROM instruments"),
)

_REMOTE_PREFIXES = ("libsql://", "https://", "http://", "wss://", "ws://")
_WRITE_WORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|REPLACE|UPSERT|CREATE|DROP|ALTER|ATTACH|DETACH|VACUUM|REINDEX|PRAGMA|BEGIN|COMMIT)\b",
    re.IGNORECASE,
)


class Client(Protocol):
    def execute(self, sql: str) -> Any: ...


Connect = Callable[[str, str], Client]
Clock = Callable[[], float]


@dataclass(frozen=True)
class Sample:
    statement: str
    ms: float


def assert_read_only(sql: str) -> None:
    """Refuse anything that is not one plain SELECT. The probe must never change the database."""
    text = sql.strip().rstrip(";").strip()
    if not text.upper().startswith("SELECT") or ";" in text or _WRITE_WORDS.search(text):
        raise ValueError(f"probe statements must be a single read-only SELECT: {sql!r}")


def probe(
    client: Client, statements: Sequence[tuple[str, str]], repeats: int, clock: Clock, warmup: int = 1
) -> list[Sample]:
    """Run each statement `warmup` times unrecorded, then `repeats` times recorded, round-robin."""
    for _, sql in statements:
        assert_read_only(sql)
    samples: list[Sample] = []
    for round_no in range(warmup + repeats):
        for name, sql in statements:
            start = clock()
            cursor = client.execute(sql)
            fetch = getattr(cursor, "fetchall", None)
            if callable(fetch):
                fetch()  # include the result transfer, as the app does
            elapsed_ms = (clock() - start) * 1000.0
            if round_no >= warmup:
                samples.append(Sample(name, elapsed_ms))
    return samples


def _nearest_rank(sorted_values: Sequence[float], q: float) -> float:
    rank = max(1, -(-int(q * 100) * len(sorted_values) // 100))  # ceil(q × n), at least 1
    return sorted_values[rank - 1]


def summarise(samples: Sequence[Sample]) -> dict[str, dict[str, float]]:
    """Per statement: n, min, median, p90 (nearest rank), max — in milliseconds."""
    out: dict[str, dict[str, float]] = {}
    names = list(dict.fromkeys(s.statement for s in samples))
    for name in names:
        values = sorted(s.ms for s in samples if s.statement == name)
        n = len(values)
        mid = n // 2
        median = values[mid] if n % 2 else (values[mid - 1] + values[mid]) / 2
        out[name] = {"n": n, "min": values[0], "median": median, "p90": _nearest_rank(values, 0.90), "max": values[-1]}
    return out


def redact(url: str) -> str:
    """Keep the scheme and the provider domain; hide the database and organisation names."""
    m = re.match(r"^([a-z]+://)([^/?#]+)", url)
    if not m:
        return "<local file>"
    host = m.group(2).split("@")[-1]
    labels = host.split(".")
    suffix = ".".join(labels[-2:]) if len(labels) >= 2 else ""
    return f"{m.group(1)}***.{suffix}" if suffix else f"{m.group(1)}***"


def _real_connect(url: str, token: str) -> Client:
    import libsql  # noqa: PLC0415 - only needed for a real run

    if url.startswith(_REMOTE_PREFIXES):
        conn: Client = libsql.connect(url, auth_token=token, isolation_level=None)
    else:
        conn = libsql.connect(url, isolation_level=None)
    return conn


def _resolve(env: Mapping[str, str]) -> tuple[str, str]:
    url = env.get("IIP_DB_URL") or env.get("TURSO_DATABASE_URL") or ""
    token = env.get("IIP_DB_AUTH_TOKEN") or env.get("TURSO_AUTH_TOKEN") or ""
    return url, token


def _run(args: argparse.Namespace, env: Mapping[str, str], connect: Connect, clock: Clock, stdout: TextIO) -> int:
    url, token = _resolve(env)
    if not url:
        print("probe: set IIP_DB_URL (or TURSO_DATABASE_URL) and IIP_DB_AUTH_TOKEN (or TURSO_AUTH_TOKEN)", file=stdout)
        return 2
    remote = url.startswith(_REMOTE_PREFIXES)
    if not remote and not args.allow_local:
        print("probe: the URL is a local file; pass --allow-local to probe a local copy (dry run)", file=stdout)
        return 2
    if remote and not token:
        print("probe: a remote database needs IIP_DB_AUTH_TOKEN (or TURSO_AUTH_TOKEN)", file=stdout)
        return 2
    if args.repeats < 1:
        print("probe: --repeats must be at least 1", file=stdout)
        return 2

    where = redact(url) if remote else "<local file>"
    t0 = clock()
    client = connect(url, token)
    connect_ms = (clock() - t0) * 1000.0
    samples = probe(client, STATEMENTS, repeats=args.repeats, clock=clock, warmup=args.warmup)

    print(f"probe: label={args.label} database={where} repeats={args.repeats} warmup={args.warmup}", file=stdout)
    print(f"{args.label} connect {connect_ms:.1f} ms (the driver may connect lazily on the first statement)",
          file=stdout)  # fmt: skip
    counters: dict[str, int] = {}
    for s in samples:
        counters[s.statement] = counters.get(s.statement, 0) + 1
        print(f"{args.label} {s.statement} #{counters[s.statement]} {s.ms:.1f} ms", file=stdout)
    print(_format_summary(args.label, summarise(samples)), file=stdout)

    if args.out:
        record = {
            "label": args.label,
            "database": where,
            "connect_ms": connect_ms,
            "repeats": args.repeats,
            "warmup": args.warmup,
            "statements": [{"name": n, "sql": q} for n, q in STATEMENTS],
            "samples": [asdict(s) for s in samples],
        }
        Path(args.out).write_text(json.dumps(record, indent=2) + "\n")
        print(f"probe: wrote {args.out}", file=stdout)
    return 0


def _format_summary(label: str, summary: Mapping[str, Mapping[str, float]]) -> str:
    lines = [f"summary ({label}), milliseconds:", f"{'statement':<10} {'n':>3} {'min':>9} {'median':>9} {'p90':>9}"]
    for name, s in summary.items():
        lines.append(f"{name:<10} {int(s['n']):>3} {s['min']:>9.1f} {s['median']:>9.1f} {s['p90']:>9.1f}")
    return "\n".join(lines)


def _load(path: str) -> tuple[str, dict[str, dict[str, float]]]:
    data = json.loads(Path(path).read_text())
    samples = [Sample(str(s["statement"]), float(s["ms"])) for s in data["samples"]]
    return str(data.get("label", path)), summarise(samples)


def _compare(args: argparse.Namespace, stdout: TextIO) -> int:
    before_label, before = _load(args.before)
    after_label, after = _load(args.after)
    print(f"per-statement median latency, measured: {before_label} → {after_label}", file=stdout)
    print(f"{'statement':<10} {before_label + ' ms':>14} {after_label + ' ms':>14} {'change':>10}", file=stdout)
    for name in dict.fromkeys([*before, *after]):
        b = before.get(name, {}).get("median")
        a = after.get(name, {}).get("median")
        if b is None or a is None:
            print(f"{name:<10} {'-' if b is None else f'{b:.1f}':>14} {'-' if a is None else f'{a:.1f}':>14} "
                  f"{'n/a':>10}", file=stdout)  # fmt: skip
            continue
        change = f"{(a - b) / b * 100.0:+.1f} %" if b else "n/a"
        print(f"{name:<10} {b:>14.1f} {a:>14.1f} {change:>10}", file=stdout)
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Read-only per-statement latency probe for the hosted database.")
    sub = p.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="measure one database")
    run.add_argument("--label", required=True, help="for example: before, after, dry-run")
    run.add_argument("--repeats", type=int, default=20)
    run.add_argument("--warmup", type=int, default=1)
    run.add_argument("--out", help="write the raw samples as JSON (no token, database name redacted)")
    run.add_argument("--allow-local", action="store_true", help="accept a local file path (dry run on a copy)")
    cmp_ = sub.add_parser("compare", help="print per-statement medians of two runs side by side")
    cmp_.add_argument("before")
    cmp_.add_argument("after")
    return p


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    connect: Connect = _real_connect,
    clock: Clock = time.perf_counter,
    stdout: TextIO | None = None,
) -> int:
    import os  # noqa: PLC0415

    args = _parser().parse_args(argv)
    out = stdout if stdout is not None else sys.stdout
    if args.cmd == "compare":
        return _compare(args, out)
    return _run(args, os.environ if env is None else env, connect, clock, out)


if __name__ == "__main__":
    raise SystemExit(main())
