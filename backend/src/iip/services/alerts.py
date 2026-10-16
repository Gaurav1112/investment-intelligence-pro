"""Deterministic alert rules, evaluated on demand (ux-design page 12; regulatory-readiness F15).

Every alert is a threshold notification on one of *your* rules and reads "Your rule “…” triggered: …". Alerts never
say what to buy or sell. Each carries a source, an observation reference where one exists, a creation timestamp and
a ``dedupe_key`` (UNIQUE in the table), so re-evaluating the same condition never produces a duplicate.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from iip.engine.money import pct
from iip.services import portfolio as pf
from iip.services.instruments import FD_RATE_STALE_DAYS, TBILL_STALE_DAYS
from iip.store import ledger
from iip.store.db import write_tx
from iip.supervisor import compliance

log = logging.getLogger("iip.alerts")

RULES_KEY = "alerts.rules"
FRACTION = r"^0\.[0-9]{1,6}$"


class AlertRules(BaseModel):
    """Your alert rules. ``None`` disables a rule. Defaults are starting points you can change, not advice."""

    model_config = ConfigDict(extra="forbid")
    stale_data: bool = True
    maturity_within_days: int | None = Field(default=30, ge=1, le=3650)
    concentration_hhi_above: str | None = Field(default="0.25", pattern=FRACTION)  # risk-methodology §7.1 band edge
    decline_since_added_beyond: str | None = Field(default="0.10", pattern=FRACTION)
    tax_coverage_within_days: int | None = Field(default=90, ge=1, le=3650)
    ingestion_failed_lookback_days: int | None = Field(default=14, ge=1, le=365)


def load_rules(conn: sqlite3.Connection) -> AlertRules:
    row = conn.execute("SELECT value_json FROM settings WHERE key=?", (RULES_KEY,)).fetchone()
    return AlertRules.model_validate(json.loads(row["value_json"])) if row else AlertRules()


def save_rules(conn: sqlite3.Connection, rules: AlertRules) -> AlertRules:
    with write_tx(conn):
        conn.execute(
            "INSERT INTO settings(key, value_json) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET"
            " value_json=excluded.value_json",
            (RULES_KEY, rules.model_dump_json()),
        )
    return rules


@dataclass(frozen=True)
class Candidate:
    kind: str
    severity: str
    subject_id: str | None
    message: str
    source_id: str | None
    observation_ref: str | None
    dedupe_key: str


def _rule_text(rule: str, body: str) -> str:
    return f"Your rule “{rule}” triggered: {body}"


def _guarded(c: Candidate, rule: str) -> Candidate:
    """Belt and braces: if a stored name makes the text trip the Compliance Guard, drop the free text."""
    if compliance.blocked(c.message):
        neutral = _rule_text(rule, "open the alert's subject for details.")
        return Candidate(c.kind, c.severity, c.subject_id, neutral, c.source_id, c.observation_ref, c.dedupe_key)
    return c


def _held_and_watched(conn: sqlite3.Connection) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """instrument_id → why it is checked ('held' / 'watched'); actual portfolios only (hypothetical are excluded).

    Also returns (portfolio_id, error code) for every actual book that cannot be replayed: its holdings are unknown,
    so they cannot be checked, and that must be reported rather than skipped silently (ECC F2)."""
    out: dict[str, str] = {}
    unreadable: list[tuple[str, str]] = []
    for p in conn.execute("SELECT portfolio_id FROM portfolios WHERE nature='actual' ORDER BY portfolio_id"):
        try:
            positions = pf.fifo_positions(pf.load_txns(conn, p["portfolio_id"]))
        except pf.PortfolioError as exc:
            unreadable.append((p["portfolio_id"], exc.code))
            continue
        for iid, pos in positions.items():
            if pos.units > 0:
                out[iid] = "held"
    for w in conn.execute("SELECT instrument_id FROM watchlist ORDER BY instrument_id"):
        out.setdefault(w["instrument_id"], "watched")
    return out, unreadable


def _stale(conn: sqlite3.Connection, now: datetime) -> tuple[list[Candidate], list[str]]:
    rule = "stale data for held or watched instruments"
    out: list[Candidate] = []
    as_of = now.date()
    checked, unreadable = _held_and_watched(conn)
    for pid, code in unreadable:
        body = (
            f"the stored transactions of portfolio {pid} cannot be replayed ({code}), so its holdings could not be "
            "checked for stale data. Review or re-import that portfolio's transactions."
        )
        out.append(Candidate("inconsistent_book", "critical", pid, _rule_text(rule, body), "user.transactions", None,
                             f"inconsistent-book:{pid}:{code}"))  # fmt: skip
    for iid, why in sorted(checked.items()):
        inst = conn.execute("SELECT * FROM instruments WHERE instrument_id=?", (iid,)).fetchone()
        if inst is None:
            continue
        name = inst["name"]
        if inst["kind"] == "mf_scheme" and inst["amfi_code"]:
            point, badge, reason = pf.latest_nav(conn, inst["amfi_code"], now)
            if reason is None:
                continue
            when = point.observation_date if point else "none"
            body = (
                f"the latest NAV for {name} ({why}) is dated {when} and is {badge}; values depending on it are "
                "excluded until fresh data is stored."
                if point
                else f"no NAV is stored for {name} ({why})."
            )
            out.append(Candidate("stale_data", "warning", iid, _rule_text(rule, body),
                                 point.source_id if point else None,
                                 str(point.obs_id) if point else None, f"stale:{iid}:{when}"))  # fmt: skip
        elif inst["kind"] in {"tbill", "gsec", "sdl", "corp_bond"}:
            obs = conn.execute(
                "SELECT obs_id, observation_date, source_id FROM observations WHERE series_id=? AND"
                " superseded_by IS NULL AND quality_status != 'rejected' ORDER BY observation_date DESC, obs_id DESC"
                " LIMIT 1",
                (f"yield:{iid}",),
            ).fetchone()
            if obs is None or (as_of - date.fromisoformat(obs["observation_date"])).days > TBILL_STALE_DAYS:
                when = obs["observation_date"] if obs else "none"
                body = f"the latest yield for {name} ({why}) is dated {when}, older than {TBILL_STALE_DAYS} days."
                out.append(Candidate("stale_data", "warning", iid, _rule_text(rule, body),
                                     obs["source_id"] if obs else None, str(obs["obs_id"]) if obs else None,
                                     f"stale:{iid}:{when}"))  # fmt: skip
        elif inst["kind"] == "fd":
            t = conn.execute("SELECT rate_as_of FROM deposit_terms WHERE instrument_id=?", (iid,)).fetchone()
            if t and (as_of - date.fromisoformat(t["rate_as_of"])).days > FD_RATE_STALE_DAYS:
                body = (
                    f"the deposit rate for {name} ({why}) was cited as of {t['rate_as_of']}, older than "
                    f"{FD_RATE_STALE_DAYS} days."
                )
                out.append(Candidate("stale_data", "warning", iid, _rule_text(rule, body), "deposit_terms",
                                     t["rate_as_of"], f"stale:{iid}:{t['rate_as_of']}"))  # fmt: skip
    return [_guarded(c, rule) for c in out], [f"{pid}: {code}" for pid, code in unreadable]


def _portfolio_rules(conn: sqlite3.Connection, now: datetime, rules: AlertRules) -> tuple[list[Candidate], list[str]]:
    out: list[Candidate] = []
    skipped: list[str] = []
    if rules.maturity_within_days is None and rules.concentration_hhi_above is None:
        return out, skipped
    as_of = now.date()
    for p in conn.execute("SELECT portfolio_id, name FROM portfolios WHERE nature='actual' ORDER BY portfolio_id"):
        pid = p["portfolio_id"]
        try:
            s = pf.portfolio_summary(conn, pid, now, maturity_days=rules.maturity_within_days or 0)
        except pf.PortfolioError as exc:
            skipped.append(f"{pid}: {exc.code}")
            continue
        if rules.maturity_within_days is not None:
            rule = f"maturity within {rules.maturity_within_days} days"
            for m in s["upcoming_maturities"]["items"]:
                when = "is past its maturity date" if m["days_until"] < 0 else f"matures in {m['days_until']} days"
                body = (
                    f"{m['name']} in portfolio “{p['name']}” {when} ({m['maturity_date']}, as of {as_of.isoformat()})."
                )
                out.append(_guarded(Candidate(
                    "maturity", "info", m["instrument_id"], _rule_text(rule, body), m["source"], m["maturity_date"],
                    f"maturity:{pid}:{m['instrument_id']}:{m['maturity_date']}",
                ), rule))  # fmt: skip
        thr = rules.concentration_hhi_above
        value = s["concentration"]["explain"]["value"]
        if thr is not None and value is not None and Decimal(value) > Decimal(thr):
            rule = f"concentration (HHI) above {thr}"
            hhi2 = Decimal(value).quantize(Decimal("0.01"))
            body = (
                f"portfolio “{p['name']}” has an HHI of {Decimal(value).quantize(Decimal('0.0001'))} "
                f"({s['concentration']['band']}) across its valued holdings as of {as_of.isoformat()}."
            )
            out.append(_guarded(Candidate("concentration", "warning", pid, _rule_text(rule, body),
                                          "user.transactions+nav", as_of.isoformat(),
                                          f"concentration:{pid}:{thr}:{hhi2}"), rule))  # fmt: skip
    return out, skipped


def _decline(conn: sqlite3.Connection, now: datetime, beyond: str) -> list[Candidate]:
    rule = f"decline since added beyond {pct(Decimal(beyond))}"
    out: list[Candidate] = []
    for w in pf.watchlist(conn, now):
        ar = w.get("absolute_return")
        ch = w.get("change")
        if not ar or not ch or Decimal(ar["value"]) > -Decimal(beyond):
            continue
        body = (
            f"{w['name']} NAV moved from ₹{ch['from']['value']} on {ch['from']['date']} to ₹{ch['to']['value']} on "
            f"{ch['to']['date']} ({ar['display']}, absolute, since you added it on {w['added_at'][:10]})."
        )
        latest = w["latest"] or {}
        out.append(_guarded(Candidate(
            "decline_since_added", "warning", w["instrument_id"], _rule_text(rule, body), latest.get("source_id"),
            str(latest.get("obs_id")), f"decline:{w['instrument_id']}:{w['added_at']}:{beyond}",
        ), rule))  # fmt: skip
    return out


def _tax(as_of: date, coverage_to: date | None, loaded: bool, within: int) -> list[Candidate]:
    rule = f"tax rule set coverage ending within {within} days"
    if not loaded or coverage_to is None:
        body = "the tax rule set could not be loaded; tax-dependent analyses abstain until it is fixed."
        return [Candidate("tax_rules", "critical", None, _rule_text(rule, body), "rules.tax", None,
                          "tax-rules-unavailable")]  # fmt: skip
    days = (coverage_to - as_of).days
    if days > within:
        return []
    state = "has ended" if days < 0 else f"ends in {days} days"
    body = (
        f"the loaded tax rule set covers transfers up to {coverage_to.isoformat()} and {state}; analyses for later "
        "dates abstain until the rules are updated."
    )
    return [Candidate("tax_rules", "critical" if days < 0 else "warning", None, _rule_text(rule, body), "rules.tax",
                      coverage_to.isoformat(), f"tax-coverage:{coverage_to.isoformat()}:{within}")]  # fmt: skip


def _ingestion(conn: sqlite3.Connection, now: datetime, lookback: int) -> list[Candidate]:
    rule = "ingestion run failed"
    cutoff = (now - timedelta(days=lookback)).isoformat()
    out: list[Candidate] = []
    for r in conn.execute(
        "SELECT run_id, source_id, started_at, error FROM ingestion_runs WHERE status='failed' AND started_at >= ?"
        " ORDER BY started_at, run_id",
        (cutoff,),
    ):
        # Runs cut off by a stop or crash are marked failed at startup (ingestion.mark_interrupted_runs).
        how = "was interrupted" if (r["error"] or "").startswith("INTERRUPTED") else "finished with status failed"
        body = f"the run for source {r['source_id']} started {r['started_at']} {how}."
        out.append(Candidate("ingestion_failed", "warning", r["source_id"], _rule_text(rule, body), r["source_id"],
                             r["run_id"], f"ingestion-failed:{r['run_id']}"))  # fmt: skip
    return out


def _scheduled_jobs(conn: sqlite3.Connection, now: datetime, lookback: int) -> list[Candidate]:
    """Hosted scheduled-job problems (silent-failure-hunter-02 d) under the same look-back as failed ingestion runs:
    with no notification channel configured these reach the user only here and on Data health. Each failed attempt
    and each watchdog finding is one alert (the attempt count is part of the dedupe key)."""
    rule = "ingestion run failed"
    cutoff = (now - timedelta(days=lookback)).isoformat()
    out: list[Candidate] = []
    for r in reversed(ledger.recent_cron_problems(conn, cutoff)):
        job, key, code = str(r["job"]), str(r["run_key"]), str(r["detail_code"] or "NO_CODE")
        if job == "watchdog":
            found = ", ".join(code.split(";")[1:]) or "a problem"
            body = f"the daily check for {key} found: {found}."
        else:
            body = f"the scheduled job {job} (run {key}) started {r['started_at']} failed with code {code}."
        out.append(Candidate("scheduled_job_failed", "warning", None, _rule_text(rule, body), f"cron.{job}",
                             f"{job}:{key}", f"cron-problem:{job}:{key}:{r['attempts']}"))  # fmt: skip
    return out


def _alert_id(dedupe_key: str) -> str:
    return "al_" + hashlib.sha256(dedupe_key.encode()).hexdigest()[:20]


def evaluate(
    conn: sqlite3.Connection, now: datetime, *, tax_coverage_to: date | None, tax_rules_loaded: bool
) -> dict[str, Any]:
    rules = load_rules(conn)
    candidates: list[Candidate] = []
    skipped: list[str] = []
    if rules.stale_data:
        stale, skipped = _stale(conn, now)
        candidates += stale
    port, port_skipped = _portfolio_rules(conn, now, rules)
    candidates += port
    skipped = sorted({*skipped, *port_skipped})  # one entry per unreadable book, whichever check found it
    if rules.decline_since_added_beyond is not None:
        candidates += _decline(conn, now, rules.decline_since_added_beyond)
    if rules.tax_coverage_within_days is not None:
        candidates += _tax(now.date(), tax_coverage_to, tax_rules_loaded, rules.tax_coverage_within_days)
    if rules.ingestion_failed_lookback_days is not None:
        candidates += _ingestion(conn, now, rules.ingestion_failed_lookback_days)
        candidates += _scheduled_jobs(conn, now, rules.ingestion_failed_lookback_days)
    created: list[str] = []
    with write_tx(conn):
        for c in candidates:
            cur = conn.execute(
                "INSERT INTO alerts(alert_id, kind, severity, subject_id, message, source_id, observation_ref,"
                " created_at, dedupe_key, acknowledged_at) VALUES (?,?,?,?,?,?,?,?,?,NULL)"
                " ON CONFLICT(dedupe_key) DO NOTHING",
                (_alert_id(c.dedupe_key), c.kind, c.severity, c.subject_id, c.message, c.source_id,
                 c.observation_ref, now.isoformat(), c.dedupe_key),
            )  # fmt: skip
            if cur.rowcount == 1:
                created.append(_alert_id(c.dedupe_key))
    log.info("alerts evaluated triggered=%d created=%d", len(candidates), len(created))
    items = [a for a in list_alerts(conn) if a["alert_id"] in set(created)]
    return {
        "evaluated_at": now.isoformat(),
        "rules": rules.model_dump(),
        "triggered": len(candidates),
        "created": items,
        "already_present": len(candidates) - len(created),
        "skipped_portfolios": skipped,
        "delivery": "local only",
    }


def list_alerts(conn: sqlite3.Connection, *, include_acknowledged: bool = True) -> list[dict[str, Any]]:
    sql = "SELECT * FROM alerts"
    if not include_acknowledged:
        sql += " WHERE acknowledged_at IS NULL"
    sql += " ORDER BY created_at DESC, alert_id"
    return [dict(r) for r in conn.execute(sql)]


def acknowledge(conn: sqlite3.Connection, alert_id: str, now: datetime) -> dict[str, Any]:
    with write_tx(conn):
        row = conn.execute("SELECT acknowledged_at FROM alerts WHERE alert_id=?", (alert_id,)).fetchone()
        if row is None:
            raise pf.PortfolioError("NOT_FOUND", "alert not found", 404)
        if row["acknowledged_at"] is None:
            conn.execute("UPDATE alerts SET acknowledged_at=? WHERE alert_id=?", (now.isoformat(), alert_id))
    out = conn.execute("SELECT * FROM alerts WHERE alert_id=?", (alert_id,)).fetchone()
    return dict(out)
