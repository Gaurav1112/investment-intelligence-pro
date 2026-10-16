"""Outcomes of the shadow ledger, scored once at each rule's horizon (design-risk-first.md §6.4; design-judgement.md
§2.1 graft 1; PLAN.md wave 2, package B02).

An evaluation dated ``d`` that observed completed month ``m`` with horizon ``h`` months is due once the month-end NAV
of month ``m + h`` is in ``series_grid`` and ``horizon_end`` (the last day of ``m + h``) is on or before the scoring
date. It is scored exactly once (``outcomes`` is append-only); until then nothing is written.

Edge formula ``shadow.outcome_edge@1`` (after cost and tax, per rupee, a notional fresh lot):

    units          = (1 − stamp) / C_start                          stamp duty on the purchase
    gross          = units × C_end
    proceeds       = gross × (1 − exit_load − stt)                  STT only for equity-oriented schemes
    gain           = proceeds − 1
    tax            = max(0, gain) × rate × (1 + cess)                short- or long-term rate by holding period;
                                                                     losses earn no tax credit (conservative)
    net(x)         = proceeds − tax − 1
    edge           = net(position the rule held) − net(benchmark: buy-and-hold the ``in`` role)

so an evaluation whose condition kept the ``in`` asset scores exactly 0. Prices are month-end NAVs; the rule's
execution lag of about one business day is not modelled (flagged in ``inputs_hash`` input as ``entry_basis``).

The rates come from a :class:`CostTaxBasis` supplied by the caller with its sources. Without one nothing is scored
(no default rate is ever invented); evaluations wait. An evaluation that abstained, or whose NAVs are missing more
than :data:`GRACE_DAYS` after the horizon, is recorded as ``unscorable`` with the reason.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from iip.engine.determinism import content_hash
from iip.engine.money import ONE, ZERO, engine_context
from iip.engine.risk import EQUITY_CLASSES
from iip.services.risk_snapshot import classify_category
from iip.services.shadow import add_months
from iip.store import ledger

EDGE_FORMULA = "shadow.outcome_edge@1"
GRACE_DAYS = 45  # PARAMETER: how long after the horizon a missing month-end NAV is awaited before "unscorable"
LONG_TERM_MONTHS = 12  # equity-oriented holding period threshold (rules/tax/india.yaml, MF-EQ-LTCG rows)
ENTRY_BASIS = "month_end_nav; execution lag not modelled"


@dataclass(frozen=True)
class CostTaxBasis:
    """Every rate used by the edge formula, as fractions, with where each came from. Supplied by the caller (from
    the rule tables and the user's tax context); never defaulted here."""

    stamp_duty: Decimal
    stt_equity_redemption: Decimal
    exit_load: Decimal
    equity_short_rate: Decimal
    equity_long_rate: Decimal
    other_rate: Decimal  # debt and other schemes: slab rate (conservative: the highest slab) whatever the period
    cess: Decimal
    sources: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("stamp_duty", "stt_equity_redemption", "exit_load", "equity_short_rate", "equity_long_rate",
                     "other_rate", "cess"):  # fmt: skip
            v = getattr(self, name)
            if not isinstance(v, Decimal) or not v.is_finite() or not ZERO <= v < ONE:
                raise ValueError(f"{name} must be a Decimal fraction in [0, 1)")
        if not self.sources:
            raise ValueError("a cost/tax basis needs its sources")


def net_return(start: Decimal, end: Decimal, *, equity: bool, months: int, basis: CostTaxBasis) -> Decimal:
    """``net(x)`` of the module formula for a notional ₹1 lot."""
    if start <= 0 or end < 0:
        raise ValueError("NAVs must be positive")
    with engine_context():
        units = (ONE - basis.stamp_duty) / start
        gross = units * end
        drag = basis.exit_load + (basis.stt_equity_redemption if equity else ZERO)
        proceeds = gross * (ONE - drag)
        gain = proceeds - ONE
        if equity:
            rate = basis.equity_long_rate if months >= LONG_TERM_MONTHS else basis.equity_short_rate
        else:
            rate = basis.other_rate
        tax = max(ZERO, gain) * rate * (ONE + basis.cess)
        return proceeds - tax - ONE


@dataclass(frozen=True)
class OutcomeRun:
    considered: int
    scored: int
    unscorable: int
    not_yet_due: int
    waiting_for_basis: int
    waiting_for_data: int


def _equity_flags(conn: sqlite3.Connection, instrument_ids: list[str]) -> dict[str, bool | None]:
    """Whether each instrument is equity-oriented (None = category unknown). One statement per chunk."""
    out: dict[str, bool | None] = dict.fromkeys(instrument_ids)
    for part in ledger.chunks(sorted(set(instrument_ids)), ledger.MAX_PARAMS):
        rows = conn.execute(
            "SELECT instrument_id, category_raw, sebi_category FROM mf_schemes"  # noqa: S608 - placeholders only
            f" WHERE instrument_id IN ({','.join('?' * len(part))})",
            list(part),
        ).fetchall()
        for r in rows:
            rc = classify_category(r["sebi_category"] or r["category_raw"])
            out[r["instrument_id"]] = None if rc is None else rc in EQUITY_CLASSES
    return out


@dataclass(frozen=True)
class _Due:
    """Shared read state for one scoring pass."""

    as_of: date
    now: str
    basis: CostTaxBasis | None
    grid: dict[str, dict[str, Decimal]]
    equity: dict[str, bool | None]


def _unscorable(key: dict[str, Any], end: str, reason: str, inputs_hash: str, due: _Due) -> ledger.Outcome:
    return ledger.Outcome(**key, horizon_end=end, status="unscorable", edge_after_cost_tax=None,
                          unscorable_reason=reason, inputs_hash=inputs_hash, scored_at=due.now,
                          resolved_on=due.as_of.isoformat())  # fmt: skip


def _score_one(r: Any, p: dict[str, Any], due: _Due) -> ledger.Outcome | str:
    """An outcome row, or the reason it is not written yet: 'not_yet_due', 'waiting_for_basis', 'waiting_for_data'."""
    key: dict[str, Any] = {
        "rule_id": r["rule_id"], "version": int(r["version"]), "as_of_date": r["as_of_date"], "scope_id": r["scope_id"],
    }  # fmt: skip
    horizon_end_s = p.get("horizon_end")
    if r["condition_met"] is None or horizon_end_s is None:
        # An abstained evaluation can never be scored; it is recorded at its horizon (or at once when it has none,
        # with the evaluation date as the horizon end).
        end = horizon_end_s or r["as_of_date"]
        if date.fromisoformat(end) > due.as_of:
            return "not_yet_due"
        reason = f"evaluation_abstained:{p.get('reason')}"
        return _unscorable(key, end, reason, content_hash({"reason": reason}), due)
    horizon_end = date.fromisoformat(horizon_end_s)
    if horizon_end > due.as_of:
        return "not_yet_due"
    if due.basis is None:
        return "waiting_for_basis"
    m0 = p["observation_month"]
    m1 = add_months(m0, int(p["horizon_months"]))
    inst = p["instruments"]
    held_key = p["position_if_met"] if int(r["condition_met"]) == 1 else p["position_if_not_met"]
    legs = {"held": inst[held_key], "benchmark": inst["in"]}
    navs: dict[str, tuple[Decimal, Decimal]] = {}
    for leg, iid in legs.items():
        series = due.grid.get(iid, {})
        if m0 in series and m1 in series:
            navs[leg] = (series[m0], series[m1])
    eq = {leg: due.equity.get(iid) for leg, iid in legs.items()}
    reason_or_none: str | None = None
    if len(navs) < len(legs):
        if due.as_of <= horizon_end + timedelta(days=GRACE_DAYS):
            return "waiting_for_data"
        reason_or_none = "nav_missing"
    elif any(v is None for v in eq.values()):
        reason_or_none = "tax_class_unknown"
    inputs_hash = content_hash({
        "formula": EDGE_FORMULA, "entry_basis": ENTRY_BASIS, "legs": legs, "months": [m0, m1],
        "navs": {k: [str(a), str(b)] for k, (a, b) in sorted(navs.items())}, "equity": eq, "basis": due.basis,
    })  # fmt: skip
    if reason_or_none is not None:
        return _unscorable(key, horizon_end_s, reason_or_none, inputs_hash, due)
    months = int(p["horizon_months"])
    held = net_return(*navs["held"], equity=bool(eq["held"]), months=months, basis=due.basis)
    bench = net_return(*navs["benchmark"], equity=bool(eq["benchmark"]), months=months, basis=due.basis)
    with engine_context():
        edge = ZERO if legs["held"] == legs["benchmark"] else held - bench
    return ledger.Outcome(**key, horizon_end=horizon_end_s, status="scored", edge_after_cost_tax=edge,
                          unscorable_reason=None, inputs_hash=inputs_hash, scored_at=due.now,
                          resolved_on=due.as_of.isoformat())  # fmt: skip


def score_outcomes(
    conn: sqlite3.Connection,
    *,
    as_of: date,
    now: str,
    basis: CostTaxBasis | None,
    limit: int = 2000,
) -> OutcomeRun:
    """Score every due evaluation once. Statements: the due read (rows that can progress, plus the counts of those
    that cannot), the grid, the category read and one batched insert (the append is a no-op for anything already
    scored). Every outcome written records ``resolved_on`` = ``as_of``, the DATA date it became known (graft TA-1;
    the first pass that resolves it stands, a later re-run does not move the date)."""
    due_read = ledger.due_evaluations(conn, as_of.isoformat(), has_basis=basis is not None, limit=limit)
    rows = due_read.rows
    payloads = [json.loads(r["payload_json"]) for r in rows]
    instruments = sorted({i for p in payloads for i in (p.get("instruments") or {}).values()})
    grid = {k: dict(v) for k, v in ledger.series_grid(conn, instruments).items()} if instruments else {}
    equity = _equity_flags(conn, instruments) if instruments and basis is not None else {}
    due = _Due(as_of, now, basis, grid, equity)
    out: list[ledger.Outcome] = []
    counts = {"not_yet_due": due_read.not_yet_due, "waiting_for_basis": due_read.waiting_for_basis,
              "waiting_for_data": 0}  # fmt: skip
    for r, p in zip(rows, payloads, strict=True):
        result = _score_one(r, p, due)
        if isinstance(result, str):
            counts[result] += 1
        else:
            out.append(result)
    ledger.append_outcomes(conn, out)
    scored = sum(1 for o in out if o.status == "scored")
    return OutcomeRun(
        considered=len(rows) + due_read.not_yet_due + due_read.waiting_for_basis, scored=scored,
        unscorable=len(out) - scored, not_yet_due=counts["not_yet_due"],
        waiting_for_basis=counts["waiting_for_basis"], waiting_for_data=counts["waiting_for_data"],
    )  # fmt: skip
