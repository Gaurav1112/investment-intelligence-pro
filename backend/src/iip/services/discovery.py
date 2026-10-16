"""Discovery: "which instruments fit this amount, date and objective?" — run under the deterministic Supervisor.

    profile ─► manifest gate ─► universe (MF with history, T-bills, FDs) ─► candidates (engine) ─► ranking (engine)
            ─► workers (deterministic claims citing facts) ─► conflicts ─► synthesis ─► stored RunRecord

Decision-level gaps → ABSTAIN. Instrument-level gaps → that instrument is excluded with its reason.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import groupby
from typing import Any

from iip.engine import candidates as cb
from iip.engine import tax as tx
from iip.engine.determinism import CANONICAL_VERSION, canonical_json, content_hash
from iip.engine.money import ZERO, D, engine_context, format_inr, money, pct, quantize
from iip.engine.ranking import (
    MIN_PRESERVATION_INDEPENDENT_WINDOWS,
    POLICY_VERSION,
    Objective,
    RankingRequest,
    RankingResult,
    RankStatus,
    Tier,
    rank,
)
from iip.services import bonds
from iip.services import portfolio as pf
from iip.services.explain import badge, source_ref
from iip.services.instruments import FD_RATE_STALE_DAYS, TBILL_STALE_DAYS
from iip.services.profile import ILLUSTRATIVE_AMOUNT, ILLUSTRATIVE_HORIZON_DAYS, ProfileStatus
from iip.store.db import write_tx
from iip.supervisor.contracts import Claim, Stance, WorkerContract, WorkerStatus
from iip.supervisor.facts import Fact, FactOrigin, FactSheet
from iip.supervisor.manifest import ContextItem, ContextKind, ContextManifest, ContextValue
from iip.supervisor.supervisor import Outcome, SupervisorResult, run

SERVICE_VERSION = "discovery@1.0.0"
MIN_HISTORY_POINTS = 60  # schemes with fewer stored NAVs are not evaluated (counted as "history not backfilled")

MANIFEST = ContextManifest(
    question_type="discover",
    items=(
        ContextItem("user.amount", ContextKind.USER_INPUT, "Investable amount"),
        ContextItem("user.withdrawal_date", ContextKind.USER_INPUT, "Required withdrawal date (in the future)"),
        ContextItem("user.objective", ContextKind.USER_INPUT, "Objective A–E"),
        ContextItem("user.loss_acceptable", ContextKind.USER_INPUT, "Whether a principal loss is acceptable"),
        ContextItem("user.early_need", ContextKind.USER_INPUT, "Whether the money may be needed early"),
        ContextItem(
            "user.loss_budget", ContextKind.USER_INPUT, "Loss budget (required for growth objectives)", required=False
        ),
        ContextItem("rule.tax", ContextKind.RULE, "Tax rule set covering the analysis date"),
        ContextItem("universe", ContextKind.OBSERVATION, "At least one instrument with evaluable data"),
    ),
)


@dataclass(frozen=True)
class Universe:
    built: tuple[cb.BuiltCandidate, ...]
    sources: dict[str, dict[str, Any]]  # instrument_id → provenance summary
    skipped_no_history: int
    evaluated_mf: int
    # Time budget (A02): schemes with enough history that were NOT evaluated because the budget ran out, and the
    # instrument kinds whose evaluation was cut short. Both empty ⇔ the universe is complete.
    not_evaluated: int = 0
    incomplete_kinds: tuple[str, ...] = ()
    # FD institution types read in the same batched statement as the FD terms (None = never recorded).
    fd_institution_types: dict[str, str | None] = field(default_factory=dict)

    @property
    def partial(self) -> bool:
        return bool(self.incomplete_kinds)


# ----------------------------------------------------------------------------- universe

# A user-facing Discovery request must never run into the platform's 300 s wall (audit-perf-hosted RC-2): after this
# many seconds the universe build stops and the result is returned flagged as PARTIAL. PARAMETER.
DISCOVER_BUDGET_S = 60.0
TIME_BUDGET_EXCEEDED = "TIME_BUDGET_EXCEEDED"
_USABLE = "('ok','manual','fixture')"

# Official AMFI sources in precedence order when both report the same date (they must agree; see _nav_series).
_NAV_SOURCE_PRECEDENCE = ("amfi.navall", "amfi.navhistory", "fixture")
_NAV_COLUMNS = "series_id, observation_date, value, source_id, source_url, retrieved_at, quality_status"


def _nav_series(
    conn: sqlite3.Connection, code: str, as_of: date | None = None
) -> tuple[list[date], list[Decimal], dict[str, Any]]:
    """One NAV per date. The same date can arrive from NAVAll AND the history report (both official AMFI).

    Equal values (exact Decimal compare, so '25.9504' == '25.95040') are merged. Unequal values are a SOURCE CONFLICT:
    the date is recorded in prov['conflicts'] and callers must not evaluate the series — never pick one silently.
    """
    rows = conn.execute(
        f"SELECT {_NAV_COLUMNS} FROM observations"  # noqa: S608
        f" WHERE series_id=? AND superseded_by IS NULL AND quality_status IN {_USABLE}"
        " ORDER BY observation_date, source_id",
        (f"nav:{code}",),
    ).fetchall()
    return _nav_series_from_rows(rows, as_of)


def _nav_series_from_rows(
    rows: Sequence[sqlite3.Row], as_of: date | None
) -> tuple[list[date], list[Decimal], dict[str, Any]]:
    """The rule of :func:`_nav_series` applied to rows already fetched (the batched universe build uses it)."""

    def rank(r: sqlite3.Row) -> int:
        sid = r["source_id"]
        return _NAV_SOURCE_PRECEDENCE.index(sid) if sid in _NAV_SOURCE_PRECEDENCE else len(_NAV_SOURCE_PRECEDENCE)

    by_date: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        by_date.setdefault(r["observation_date"], []).append(r)
    chosen: list[sqlite3.Row] = []
    conflicts: list[str] = []
    for d in sorted(by_date):
        group = sorted(by_date[d], key=rank)
        if len({Decimal(r["value"]) for r in group}) > 1:
            conflicts.append(f"{d}: " + ", ".join(f"{r['source_id']}={r['value']}" for r in group))
        chosen.append(group[0])
    dates = [date.fromisoformat(r["observation_date"]) for r in chosen]
    navs = [Decimal(r["value"]) for r in chosen]
    prov: dict[str, Any] = {"conflicts": conflicts}
    if chosen:
        last = chosen[-1]
        prov.update({
            "source_id": last["source_id"],
            "url": last["source_url"],
            "retrieved_at": last["retrieved_at"],
            "observation_date": last["observation_date"],
            "quality_status": last["quality_status"],
            "first_date": chosen[0]["observation_date"],
            "count": len(chosen),
            "sources": sorted({r["source_id"] for r in chosen}),
            "fixture": any(r["quality_status"] == "fixture" for r in chosen),
        })  # fmt: skip
    prov["freshness"] = badge(prov, as_of) if chosen else "UNAVAILABLE"
    return dates, navs, prov


SURCHARGE_UNKNOWN = (
    "surcharge band not entered, so NO surcharge is applied — tax is understated if your total income exceeds ₹50 lakh"
)


def _tax_profile(status: ProfileStatus) -> tx.TaxProfile | None:
    p = status.profile
    if p.slab_rate is None or p.tax_regime != "new":
        return None  # illustrative 30 % profile is used and labelled (old regime is not modelled)
    if p.surcharge_rate is None:
        label = f"your profile (new regime, your marginal slab; {SURCHARGE_UNKNOWN})"
    else:
        label = f"your profile (new regime, your marginal slab, surcharge band {pct(p.surcharge_rate)})"
    return tx.TaxProfile(
        regime=tx.Regime.NEW,
        residential_status=tx.ResidentialStatus.RESIDENT,
        slab_rate=p.slab_rate,
        surcharge_rate=p.surcharge_rate if p.surcharge_rate is not None else D("0"),
        label=label,
    )


def _fund_credit_facts_batch(
    conn: sqlite3.Connection, instrument_ids: Sequence[str], as_of: date
) -> dict[str, cb.FundCreditFacts]:
    """:func:`inputs.fund_credit_facts` for many schemes in ONE statement (same filter and the same ordering: the
    latest portfolio date on or before ``as_of``, then the latest entry)."""
    if not instrument_ids:
        return {}
    out: dict[str, cb.FundCreditFacts] = {}
    for r in conn.execute(
        "SELECT instrument_id, lowest_rating, as_of_date FROM fund_facts"
        " WHERE instrument_id IN (SELECT value FROM json_each(?)) AND as_of_date <= ?"
        " ORDER BY instrument_id, as_of_date DESC, entered_at DESC, fact_id DESC",
        (json.dumps(sorted(instrument_ids)), as_of.isoformat()),
    ):
        if r["instrument_id"] not in out:  # first row per scheme = the latest
            out[r["instrument_id"]] = cb.FundCreditFacts(
                lowest_rating=r["lowest_rating"], as_of=date.fromisoformat(r["as_of_date"])
            )
    return out


def _existing_fd(
    raw_json: str | None, institution: str, dicgc_eligible: object, held: dict[pf.BankKey, Decimal] | None
) -> Decimal | None:
    """:func:`portfolio.existing_fd_deposits` on values already fetched (same rule; the parity test with
    ``analysis.build_one``, which calls the original, keeps them equal)."""
    raw = None if raw_json is None else json.loads(raw_json)
    manual = None if raw is None else Decimal(raw)
    if held is None:
        return None
    k = pf._bank_key(institution, dicgc_eligible)
    if manual is None and k not in held:
        return None
    with engine_context():
        return (manual or ZERO) + held.get(k, ZERO)


def build_universe(
    conn: sqlite3.Connection,
    *,
    amount: Decimal,
    as_of: date,
    withdrawal: date,
    ruleset: tx.TaxRuleSet,
    profile: tx.TaxProfile | None,
    excluded_kinds: Sequence[str],
    time_left: Callable[[], float] | None = None,
) -> Universe:
    """Every evaluable instrument, read with a CONSTANT number of statements per instrument kind (audit-perf-hosted
    RC-2: one statement per scheme took 1,791 statements and a 504). Statements: MF list with history counts, fund
    credit facts, one NAV stream; T-bills with their quotes; FD terms with their settings (+ the portfolio exposure
    read); bonds (services/bonds.py, per bond — user-entered rows).

    ``time_left`` (seconds remaining; None = no budget) is checked before every instrument: when it reaches 0 the
    build stops and the universe is flagged partial (``incomplete_kinds``) instead of running into a timeout."""
    built: list[cb.BuiltCandidate] = []
    sources: dict[str, dict[str, Any]] = {}
    skipped = evaluated = not_evaluated = 0
    incomplete: list[str] = []
    fd_types: dict[str, str | None] = {}

    def out_of_time() -> bool:
        return time_left is not None and time_left() <= 0

    if "mf_scheme" not in excluded_kinds:
        # RT-27: only usable rows count (not rejected/suspect, not superseded), one per date — the same filter
        # _nav_series applies, so the gate cannot admit a scheme on rows the evaluation will never see.
        mf_rows = conn.execute(
            "SELECT i.instrument_id, i.name, i.amfi_code, m.category_raw, m.exit_load_json,"  # noqa: S608
            " (SELECT COUNT(DISTINCT o.observation_date) FROM observations o WHERE o.series_id = 'nav:' || i.amfi_code"
            f"  AND o.superseded_by IS NULL AND o.quality_status IN {_USABLE}) AS nav_points"
            " FROM instruments i JOIN mf_schemes m USING(instrument_id) ORDER BY i.instrument_id"
        ).fetchall()
        eligible = {f"nav:{r['amfi_code']}": r for r in mf_rows if r["nav_points"] >= MIN_HISTORY_POINTS}
        skipped = len(mf_rows) - len(eligible)
        credit = _fund_credit_facts_batch(conn, [r["instrument_id"] for r in eligible.values()], as_of)
        mf_built: dict[str, tuple[cb.BuiltCandidate, dict[str, Any]]] = {}
        if eligible:
            cur = conn.execute(
                f"SELECT {_NAV_COLUMNS} FROM observations WHERE series_id IN (SELECT value FROM json_each(?))"  # noqa: S608
                f" AND superseded_by IS NULL AND quality_status IN {_USABLE}"
                " ORDER BY series_id, observation_date, source_id",
                (json.dumps(sorted(eligible)),),
            )
            for sid, group in groupby(cur, key=lambda x: str(x["series_id"])):
                if out_of_time():
                    incomplete.append("mf_scheme")
                    break
                r = eligible[sid]
                evaluated += 1
                mf_built[r["instrument_id"]] = _mf_built(
                    r, list(group), amount=amount, as_of=as_of, withdrawal=withdrawal, ruleset=ruleset,
                    profile=profile, credit=credit.get(r["instrument_id"]),
                )  # fmt: skip
            not_evaluated = len(eligible) - evaluated
        for r in mf_rows:  # instrument_id order, as before
            if r["instrument_id"] in mf_built:
                b, prov = mf_built[r["instrument_id"]]
                built.append(b)
                sources[r["instrument_id"]] = prov

    if "tbill" not in excluded_kinds:
        if out_of_time():
            incomplete.append("tbill")
        else:
            _tbills(conn, built, sources, amount=amount, as_of=as_of, withdrawal=withdrawal, ruleset=ruleset,
                    profile=profile, out_of_time=out_of_time, incomplete=incomplete)  # fmt: skip

    if "fd" not in excluded_kinds:
        if out_of_time():
            incomplete.append("fd")
        else:
            _fds(conn, built, sources, fd_types, amount=amount, as_of=as_of, withdrawal=withdrawal, ruleset=ruleset,
                 profile=profile, out_of_time=out_of_time, incomplete=incomplete)  # fmt: skip

    # G-secs, SDLs, corporate bonds: the same loader/builder as analysis.build_one (services/bonds.py).
    for inst in bonds.bond_rows(conn):
        if inst["kind"] in excluded_kinds:
            continue
        if out_of_time():
            if inst["kind"] not in incomplete:
                incomplete.append(str(inst["kind"]))
            continue
        b_or_none, prov, _ = bonds.build_bond(
            conn, inst, amount=amount, as_of=as_of, withdrawal=withdrawal, ruleset=ruleset, profile=profile
        )
        if b_or_none is None:
            continue  # no terms or no quote stored at all (as for T-bills: not in the universe)
        built.append(b_or_none)
        sources[str(inst["instrument_id"])] = prov
    return Universe(tuple(built), sources, skipped, evaluated, not_evaluated, tuple(incomplete), fd_types)


def _mf_built(
    r: sqlite3.Row,
    rows: list[sqlite3.Row],
    *,
    amount: Decimal,
    as_of: date,
    withdrawal: date,
    ruleset: tx.TaxRuleSet,
    profile: tx.TaxProfile | None,
    credit: cb.FundCreditFacts | None,
) -> tuple[cb.BuiltCandidate, dict[str, Any]]:
    dates, navs, prov = _nav_series_from_rows(rows, as_of)
    cat = r["category_raw"] or ""
    if prov["conflicts"]:
        tier = cb.mf_tier_from_category(cat)
        reason = [f"SOURCE_CONFLICT: official sources disagree on {prov['conflicts'][0]}"]
        return cb._ineligible(r["instrument_id"], r["name"], tier, reason, amount), {
            **prov, "kind": "mf_scheme", "category": cat,
        }  # fmt: skip
    load = None
    if r["exit_load_json"]:
        el = json.loads(r["exit_load_json"])
        load = cb.ExitLoadSpec(days=int(el["days"]), rate=Decimal(el["rate"]), citation=el["citation"])
    settle = 1 if cb.mf_tier_from_category(cat).name == "T3" else 3
    b = cb.mf_candidate(
        instrument_id=r["instrument_id"],
        name=r["name"],
        category=cat,
        amount=amount,
        as_of=as_of,
        withdrawal=withdrawal,
        nav_dates=dates,
        navs=navs,
        exit_load=load,
        ruleset=ruleset,
        profile=profile,
        settlement_days=settle,
        credit_facts=credit,
    )
    return b, {**prov, "kind": "mf_scheme", "category": cat}


def _tbills(
    conn: sqlite3.Connection,
    built: list[cb.BuiltCandidate],
    sources: dict[str, dict[str, Any]],
    *,
    amount: Decimal,
    as_of: date,
    withdrawal: date,
    ruleset: tx.TaxRuleSet,
    profile: tx.TaxProfile | None,
    out_of_time: Callable[[], bool],
    incomplete: list[str],
) -> None:
    """T-bills and all their usable yield quotes in ONE statement; the quote rule is :func:`tbill_quote`'s."""
    rows = conn.execute(
        "SELECT i.instrument_id, i.name, b.maturity_date, o.value, o.observation_date, o.source_id, o.source_url,"  # noqa: S608
        " o.retrieved_at, o.quality_status FROM instruments i JOIN bond_terms b USING(instrument_id)"
        " LEFT JOIN observations o ON o.series_id = 'yield:' || i.instrument_id AND o.superseded_by IS NULL"
        f" AND o.quality_status IN {_USABLE}"
        " WHERE i.kind='tbill' ORDER BY i.instrument_id, o.observation_date DESC, o.source_id"
    ).fetchall()
    for iid, group in groupby(rows, key=lambda x: str(x["instrument_id"])):
        if out_of_time():
            incomplete.append("tbill")
            return
        quotes = [g for g in group if g["observation_date"] is not None]
        first = quotes[0] if quotes else None
        r, problem = _pick_tbill_quote(quotes, as_of)
        if r is None or first is None:
            continue  # no usable yield observation at all (as before: the T-bill is not in the universe)
        name = first["name"]
        quote_date = date.fromisoformat(r["observation_date"])
        if problem is not None:
            b = cb._ineligible(iid, name, Tier.T1, [problem], amount)
        elif (as_of - quote_date).days > TBILL_STALE_DAYS:
            b = cb._ineligible(iid, name, Tier.T1, [f"STALE_DATA: yield quoted {quote_date}"], amount)
        else:
            b = cb.tbill_candidate(
                instrument_id=iid,
                name=name,
                amount=amount,
                quoted_yield=Decimal(r["value"]),
                settlement=as_of + timedelta(days=1),
                maturity=date.fromisoformat(first["maturity_date"]),
                withdrawal=withdrawal,
                ruleset=ruleset,
                profile=profile,
            )
        built.append(b)
        sources[iid] = {
            "kind": "tbill",
            "source_id": r["source_id"],  # as stored (a fixture is never labelled as an RBI release)
            "url": r["source_url"],
            "retrieved_at": r["retrieved_at"],
            "observation_date": r["observation_date"],
            "quality_status": r["quality_status"],
            "fixture": r["quality_status"] == "fixture",
        }
        sources[iid]["freshness"] = badge(sources[iid], as_of)


def _fds(
    conn: sqlite3.Connection,
    built: list[cb.BuiltCandidate],
    sources: dict[str, dict[str, Any]],
    fd_types: dict[str, str | None],
    *,
    amount: Decimal,
    as_of: date,
    withdrawal: date,
    ruleset: tx.TaxRuleSet,
    profile: tx.TaxProfile | None,
    out_of_time: Callable[[], bool],
    incomplete: list[str],
) -> None:
    """FD terms with their three settings keys in ONE statement (+ the actual-portfolio exposure read)."""
    held_at_bank = pf.fd_principal_by_bank(conn)  # ECC F1: FDs already in your actual portfolios count too
    for r in conn.execute(
        "SELECT i.instrument_id, i.name, i.origin, i.created_at, d.*,"
        " (SELECT value_json FROM settings WHERE key = 'fd.existing:' || i.instrument_id) AS fd_existing_json,"
        " (SELECT value_json FROM settings WHERE key = 'fd.institution_type:' || i.instrument_id) AS fd_type_json,"
        " (SELECT value_json FROM settings WHERE key = 'fd.entered_at:' || i.instrument_id) AS fd_entered_json"
        " FROM instruments i JOIN deposit_terms d USING(instrument_id)"
        " ORDER BY i.instrument_id"
    ).fetchall():
        if out_of_time():
            incomplete.append("fd")
            return
        iid, name = r["instrument_id"], r["name"]
        inst_type = None if r["fd_type_json"] is None else str(json.loads(r["fd_type_json"]))
        fd_types[iid] = inst_type
        rate_date = date.fromisoformat(r["rate_as_of"])
        existing = _existing_fd(r["fd_existing_json"], r["institution"], r["dicgc_eligible"], held_at_bank)
        if rate_date > as_of:
            b = cb._ineligible(iid, name, Tier.T2, [f"LOOK_AHEAD: rate dated {rate_date}, after the analysis date"],
                               amount)  # fmt: skip
        elif (as_of - rate_date).days > FD_RATE_STALE_DAYS:
            b = cb._ineligible(iid, name, Tier.T2, [f"STALE_DATA: rate as of {rate_date}"], amount)
        else:
            b = cb.fd_candidate(
                instrument_id=iid,
                name=name,
                amount=amount,
                rate=Decimal(r["rate"]),
                start=as_of,
                tenure_days=int(r["tenure_days"]),
                withdrawal=withdrawal,
                dicgc_eligible=bool(r["dicgc_eligible"]),
                premature_penalty=None if r["premature_penalty"] is None else Decimal(r["premature_penalty"]),
                other_deposits_same_bank=existing,
                ruleset=ruleset,
                profile=profile,
                sovereign_backed=inst_type == "post_office",
            )
        built.append(b)
        entered = r["created_at"] if r["fd_entered_json"] is None else str(json.loads(r["fd_entered_json"]))
        sources[iid] = {
            "kind": "fd",
            "source_id": "bank.fd",
            "url": r["citation_url"],
            "retrieved_at": entered,  # when the user entered the cited rate
            "observation_date": r["rate_as_of"],
            "quality_status": "fixture" if r["origin"] == "fixture" else "manual",
            "fixture": r["origin"] == "fixture",
        }
        sources[iid]["freshness"] = badge(sources[iid], as_of)


_YIELD_SOURCE_PRECEDENCE = ("rbi.pr.tbill", "fixture")


def tbill_quote(conn: sqlite3.Connection, iid: str, as_of: date) -> tuple[sqlite3.Row | None, str | None]:
    """The yield quote to evaluate a T-bill on ``as_of``: the latest usable observation dated on or before it.

    Returns (row, problem). A quote dated after ``as_of`` is never used (a mistyped future date must not win forever
    or dodge the staleness rule); if it is the only quote, the problem is LOOK_AHEAD. Two current quotes for the same
    date that disagree (e.g. a fixture and a manual entry for the same tenor/maturity) are a SOURCE_CONFLICT — one is
    never picked silently, and the instrument is evaluated once (duplicate ids used to crash the ranking).
    """
    rows = conn.execute(
        "SELECT value, observation_date, source_id, source_url, retrieved_at, quality_status FROM observations"  # noqa: S608
        f" WHERE series_id=? AND superseded_by IS NULL AND quality_status IN {_USABLE}"
        " ORDER BY observation_date DESC, source_id",
        (f"yield:{iid}",),
    ).fetchall()
    return _pick_tbill_quote(rows, as_of)


def _pick_tbill_quote(rows: Sequence[sqlite3.Row], as_of: date) -> tuple[sqlite3.Row | None, str | None]:
    """The rule of :func:`tbill_quote` on rows already fetched (latest first)."""
    if not rows:
        return None, None
    usable = [r for r in rows if date.fromisoformat(r["observation_date"]) <= as_of]
    if not usable:
        return rows[-1], f"LOOK_AHEAD: yield quoted {rows[-1]['observation_date']}, after the analysis date"
    same_day = [r for r in usable if r["observation_date"] == usable[0]["observation_date"]]

    def rank(r: sqlite3.Row) -> int:
        sid = r["source_id"]
        return _YIELD_SOURCE_PRECEDENCE.index(sid) if sid in _YIELD_SOURCE_PRECEDENCE else len(_YIELD_SOURCE_PRECEDENCE)

    same_day.sort(key=lambda r: (rank(r), r["source_id"]))
    if len({Decimal(r["value"]) for r in same_day}) > 1:
        detail = ", ".join(f"{r['source_id']}={r['value']}" for r in same_day)
        return same_day[0], f"SOURCE_CONFLICT: quotes disagree on {same_day[0]['observation_date']}: {detail}"
    return same_day[0], None


def fd_entered_at(conn: sqlite3.Connection, iid: str, created_at: str) -> str:
    """When the current FD rate was entered (falls back to the instrument's creation for rows entered before this
    was recorded)."""
    row = conn.execute("SELECT value_json FROM settings WHERE key=?", (f"fd.entered_at:{iid}",)).fetchone()
    return str(json.loads(row["value_json"])) if row else created_at


def fd_institution_type(conn: sqlite3.Connection, iid: str) -> str | None:
    row = conn.execute("SELECT value_json FROM settings WHERE key=?", (f"fd.institution_type:{iid}",)).fetchone()
    return str(json.loads(row["value_json"])) if row else None


# ----------------------------------------------------------------------------- facts & explanations


def _engine_fact(fid: str, display: str, value: Decimal | None, unit: str, formula: str, inputs: Any) -> Fact:
    return Fact(
        fid,
        display,
        FactOrigin.ENGINE,
        value=value,
        unit=unit,
        formula_id=formula,
        input_hash=content_hash(inputs),
        engine_version=cb.ENGINE_VERSION,
    )


def explained_outcome(
    b: cb.BuiltCandidate, which: str, value: Decimal, amount: Decimal, horizon_days: int, prov: dict[str, Any]
) -> dict[str, Any]:
    ev = b.evidence
    assert ev is not None
    c = b.candidate
    label = {"q05": "Low-end outcome", "q50": "Middle outcome", "q95": "High-end outcome"}[which]
    if c.outcome.is_contractual:
        label = "Contractual proceeds after tax"
    what = f"What {format_inr(amount)} becomes after {horizon_days} days, after costs and assumed tax. " + (
        "Contractual: fixed by the instrument's terms."
        if c.outcome.is_contractual
        else {
            "q05": f"Lower band — {ev.lower_band_method}.",
            "q50": "Median of historical windows of this length.",
            "q95": "Upper band of historical windows of this length.",
        }[which]
    )
    tax = {"q05": ev.tax_low, "q50": ev.tax_mid, "q95": ev.tax_high}[which]
    sources = [source_ref(prov)] if prov else []
    sensitivity = []
    if not c.outcome.is_contractual:
        sensitivity = [
            {"label": "Low-end (q05 / worst window)", "display": format_inr(c.outcome.q05)},
            {"label": "Median", "display": format_inr(c.outcome.q50)},
            {"label": "High-end", "display": format_inr(c.outcome.q95)},
        ]
    freshness = str(prov.get("freshness") or "UNKNOWN")  # computed from age at load time; never assumed fresh
    payload = {"id": c.instrument_id, "which": which, "value": str(value), "inputs": ev.inputs}
    return {
        "id": f"{c.instrument_id}.{which}",
        "label": label,
        "display": format_inr(value),
        "value": format(money(value), "f"),
        "unit": "INR",
        "what": what,
        "formula_id": ev.formula_id,
        "formula": {
            "CAND_TBILL@2": (
                "P = 100 / (1 + y·D/365);  lots = ⌊amount / (10,000·P/100)⌋;  face = 10,000·lots;  "
                "cost = face·P/100;  proceeds = face + (amount − cost) − tax(face − cost)"
            ),
            "CAND_FD@1": "A = P(1 + r/4)^q × (1 + r·b/365) (simple below the short-tenure cut-off); proceeds = A − tax",
            "CAND_MF_EMPIRICAL@2": (
                "R = NAV(t+H−s)/NAV(t) − 1 over every past window (s = settlement days); "
                "V = (amount − stamp)(1 + R)(1 − load) − tax"
            ),
            "CAND_BOND_HTM@1": (
                "n = ⌊amount / (face × dirty / 100)⌋ whole bonds; V = idle cash + n·face/100 × (Σ coupons + redemption)"
                " − tax(interest at slab + capital gain); callable → worst of maturity and call paths"
            ),
            "CAND_BOND_EARLY_EXIT@1": (
                "V = idle cash + n·face/100 × (coupons received + exit clean × (1 − spread) + exit accrued) − tax; "
                "exit price at entry yield +100 / 0 / −100 bp + exit spread (stress scenarios)"
            ),
        }[ev.formula_id],
        "substituted": f"gross {format_inr(value + tax)} − tax {format_inr(tax)} = {format_inr(value)}",
        "inputs": [_input_line(k, v) for k, v in ev.inputs]
        + [f"tax basis: {ev.tax_basis.value}"]
        + [_cost_line(k, v) for k, v in ev.costs],
        "sources": sources,
        "observed": prov.get("observation_date"),
        "freshness": freshness,
        "assumptions": list(ev.assumptions)
        + (
            ["Tax computed under an ILLUSTRATIVE 30 % slab profile (not yours)"]
            if ev.tax_basis is cb.TaxBasis.ILLUSTRATIVE
            else []
        ),
        "sensitivity": sensitivity,
        "limitations": list(ev.limitations) + [f"Flag: {f}" for f in c.flags],
        "engine_version": cb.ENGINE_VERSION,
        "hash": content_hash(payload),
    }


_MONEY_KEYS = {"amount", "dicgc_exposure_at_bank", "cash_left_idle", "face_value", "uninvested_cash"}
_RATE_KEYS = {"quoted_yield", "rate", "coupon_rate"}
_PER_100_KEYS = {"price_per_100", "clean_price_per_100", "accrued_per_100", "dirty_purchase_per_100"}


def _input_line(key: str, raw: str) -> str:
    """Display formatting only — internal precision never reaches the screen."""
    try:
        if key in _MONEY_KEYS:
            return f"{key}: {format_inr(Decimal(raw))}"
        if key in _RATE_KEYS:
            return f"{key}: {pct(Decimal(raw))}"
        if key.startswith("path_"):  # "gross X; tax Y; net Z" (bond paths/scenarios)
            parts = [p.split(" ", 1) for p in raw.split("; ")]
            return f"{key}: " + "; ".join(f"{k} {format_inr(Decimal(v))}" for k, v in parts)
        if key == "ytm" and " (" in raw:
            value, comp = raw.split(" (", 1)
            return f"{key}: {pct(Decimal(value))} ({comp}"
        if key in _PER_100_KEYS:
            return f"{key}: {quantize(Decimal(raw), Decimal('0.0001'))}"
    except (ArithmeticError, ValueError):
        pass
    return f"{key}: {raw}"


def _cost_line(key: str, value: Decimal) -> str:
    if key.endswith("_rate"):
        return f"cost {key}: {pct(value)}"
    return f"cost {key}: {format_inr(value)}"


# ----------------------------------------------------------------------------- workers (deterministic)


@dataclass
class _Worker:
    name: str
    required: bool
    contract: WorkerContract

    def run(self, facts: FactSheet, context: dict[str, ContextValue], payload: Any) -> WorkerContract:
        return self.contract


def _workers(result: RankingResult, universe: Universe, facts: FactSheet) -> list[_Worker]:
    by_id = {b.candidate.instrument_id: b for b in universe.built}
    quant_claims: list[Claim] = [
        Claim(
            "evaluated",
            "universe",
            "coverage",
            Stance.NEUTRAL,
            "Evaluated {fact:universe.evaluated} instruments; {fact:universe.ranked} passed every constraint.",
            cites=("universe.evaluated", "universe.ranked"),
        ),
    ]
    if universe.partial:
        quant_claims.append(
            Claim(
                "partial",
                "universe",
                "coverage",
                Stance.NEUTRAL,
                "Evaluation stopped at the time budget; {fact:universe.not_evaluated} schemes with history were not"
                " reached, and this ordering covers only the instruments shown.",
                cites=("universe.not_evaluated",),
            )
        )
    if universe.skipped_no_history:
        quant_claims.append(
            Claim(
                "skipped",
                "universe",
                "coverage",
                Stance.NEUTRAL,
                "{fact:universe.skipped} schemes were not evaluated because their NAV history has not been backfilled.",
                cites=("universe.skipped",),
            )
        )
    skeptic: list[Claim] = []
    risk: list[Claim] = []
    if result.ranked:
        top = result.ranked[0].instrument_id
        quant_claims.append(
            Claim(
                "top",
                top,
                "evidence",
                Stance.SUPPORTS,
                "Under your constraints the first-ordered option is {fact:top.name}, with a low-end outcome of "
                "{fact:top.q05} after costs and assumed tax.",
                cites=("top.name", "top.q05"),
            )
        )
        flags = by_id[top].candidate.flags
        for f in flags:
            if f in {"TAX_RULE_UNVERIFIED", "LOW_EVIDENCE"} or f.startswith("TAX_RULES_ASSUMED"):
                skeptic.append(
                    Claim(
                        f"flag.{f.split('_AFTER_')[0]}",
                        top,
                        "evidence",
                        Stance.CHALLENGES,
                        _SKEPTIC_TEXT[f.split("_AFTER_")[0]],
                    )
                )
        if by_id[top].candidate.tier.name in {"T3", "T4"} and universe.sources.get(top, {}).get("kind") == "mf_scheme":
            skeptic.append(
                Claim(
                    "survivorship",
                    top,
                    "evidence",
                    Stance.CHALLENGES,
                    "Funds that were merged or wound up are absent from the history, which flatters "
                    "category comparisons.",
                    material=False,
                )
            )
        for item in result.ranked:
            item_flags = by_id[item.instrument_id].candidate.flags
            if "EXCEEDS_DICGC_LIMIT_AT_THIS_BANK" in item_flags or "NOT_DICGC_INSURED" in item_flags:
                risk.append(
                    Claim(
                        f"dicgc.{item.instrument_id}",
                        item.instrument_id,
                        "credit",
                        Stance.CHALLENGES,
                        "Part or all of {fact:name." + item.instrument_id + "} is outside DICGC insurance; that "
                        "part carries the institution's credit risk.",
                        cites=(f"name.{item.instrument_id}",),
                    )
                )
    stale = sum(1 for e in result.excluded if any(c.startswith("STALE") for c in _codes(by_id, e.instrument_id)))
    if stale:
        risk.append(
            Claim(
                "stale",
                "universe",
                "data_quality",
                Stance.CHALLENGES,
                "{fact:universe.stale} instruments were excluded because their data is stale.",
                cites=("universe.stale",),
            )
        )
    if "universe.stale" not in facts:
        facts.add(
            Fact(
                "universe.stale",
                str(stale),
                FactOrigin.ENGINE,
                value=Decimal(stale),
                unit="count",
                formula_id="COUNT@1",
                input_hash=content_hash(stale),
                engine_version=SERVICE_VERSION,
            )
        )
    return [
        _Worker("quant", True, WorkerContract("quant", WorkerStatus.ANSWERED, claims=tuple(quant_claims))),
        _Worker(
            "portfolio_risk",
            False,
            WorkerContract(
                "portfolio_risk",
                WorkerStatus.ANSWERED if risk else WorkerStatus.ABSTAINED,
                claims=tuple(risk),
                abstain_reason=None if risk else "no portfolio-level risk findings for the ordered options",
            ),
        ),
        _Worker(
            "skeptic",
            False,
            WorkerContract(
                "skeptic",
                WorkerStatus.ANSWERED if skeptic else WorkerStatus.ABSTAINED,
                claims=tuple(skeptic),
                abstain_reason=None
                if skeptic
                else "no material counter-evidence found against the first-ordered option",
            ),
        ),
    ]


_SKEPTIC_TEXT = {
    "TAX_RULE_UNVERIFIED": "The tax rule used for this option is not verified against the primary text; the after-tax "
    "figure is an assumption pending review by a Chartered Accountant.",
    "LOW_EVIDENCE": "The history contains few independent windows of this length, so the band rests on thin evidence.",
    "TAX_RULES_ASSUMED_UNCHANGED": "Your withdrawal falls after the last legislated tax year; current tax rules are "
    "assumed to continue, and future changes could alter the after-tax result.",
}


def _name_fact(fid: str, iid: str, name: str, universe: Universe) -> Fact:
    """An instrument name as a cited fact, with the provenance of the data it came from (never a made-up time)."""
    prov = universe.sources[iid]
    retrieved = prov.get("retrieved_at")
    if not retrieved:
        raise ValueError(f"{iid}: no retrieval/entry timestamp recorded — refusing to invent one")
    return Fact(
        fid,
        name,
        FactOrigin.OBSERVATION,
        source_id=str(prov.get("source_id")),
        source_url=str(prov.get("url")),
        observation_date=date.fromisoformat(str(prov["observation_date"])),
        retrieved_at=datetime.fromisoformat(str(retrieved)),
        quality_status=str(prov.get("quality_status")),
    )


def _codes(by_id: dict[str, cb.BuiltCandidate], iid: str) -> tuple[str, ...]:
    return by_id[iid].ineligible_reasons if iid in by_id else ()


# ----------------------------------------------------------------------------- entry point


def _exclude_fixtures(universe: Universe, amount: Decimal) -> Universe:
    """ux-design §4.4: personalised mode refuses to rank FIXTURE data (it is never market data)."""
    built = []
    for b in universe.built:
        c = b.candidate
        if universe.sources.get(c.instrument_id, {}).get("fixture"):
            reason = ["FIXTURE_NOT_MARKET_DATA: development fixture"]
            built.append(cb._ineligible(c.instrument_id, c.name, c.tier, reason, amount))
        else:
            built.append(b)
    return replace(universe, built=tuple(built))


_NBFC_TYPES = frozenset({"nbfc", "hfc"})


def _exclude_nbfc_deposits(universe: Universe, amount: Decimal) -> Universe:
    """requirements.md §3.2 item 8: the profile's "exclude NBFC deposits" restriction (default on).

    NBFC/HFC deposits are excluded; so is an uninsured deposit whose institution type was never recorded (it cannot
    be shown NOT to be an NBFC deposit — never assumed)."""
    built = []
    for b in universe.built:
        c = b.candidate
        iid = c.instrument_id
        if universe.sources.get(iid, {}).get("kind") == "fd":
            kind = universe.fd_institution_types.get(iid)  # read with the FD terms (one batched statement)
            unknown_uninsured = kind is None and "NOT_DICGC_INSURED" in c.flags
            if kind in _NBFC_TYPES or unknown_uninsured:
                reason = ["EXCLUDED_BY_USER: your profile excludes NBFC/HFC deposits"]
                built.append(cb._ineligible(iid, c.name, c.tier, reason, amount))
                continue
        built.append(b)
    return replace(universe, built=tuple(built))


def discover(  # noqa: PLR0915 - one auditable orchestration sequence
    conn: sqlite3.Connection,
    status: ProfileStatus,
    *,
    as_of: date,
    ruleset: tx.TaxRuleSet | None,
    allow_fixtures: bool = False,
    llm_rephrase: Callable[[str], str] | None = None,
    time_left: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """``time_left`` (seconds remaining, None = unbounded): see :func:`build_universe`. A build cut short by the
    budget is returned with ``partial`` set and a coverage claim in the report — never presented as complete."""
    p = status.profile
    personalised = status.mode == "PERSONALISED"
    amount = p.amount if personalised and p.amount is not None else ILLUSTRATIVE_AMOUNT
    horizon = status.horizon_days if personalised and status.horizon_days else ILLUSTRATIVE_HORIZON_DAYS
    withdrawal = as_of + timedelta(days=horizon)
    tax_profile = _tax_profile(status)

    universe = Universe((), {}, 0, 0)
    if ruleset is not None and ruleset.coverage_to >= as_of:
        universe = build_universe(
            conn,
            amount=amount,
            as_of=as_of,
            withdrawal=withdrawal,
            ruleset=ruleset,
            profile=tax_profile,
            excluded_kinds=p.excluded_kinds,
            time_left=time_left,
        )
        if personalised and not allow_fixtures:
            universe = _exclude_fixtures(universe, amount)
        if personalised and p.exclude_nbfc_deposits:
            universe = _exclude_nbfc_deposits(universe, amount)

    def present(v: object) -> ContextValue:
        return ContextValue("", present=v is not None, valid=v is not None)

    context: dict[str, ContextValue] = {
        "user.amount": present(p.amount),
        "user.withdrawal_date": present(status.horizon_days),
        "user.objective": present(p.objective),
        "user.loss_acceptable": present(p.loss_acceptable),
        "user.early_need": present(p.early_need),
        "user.loss_budget": present(p.max_loss_fraction),
        "rule.tax": ContextValue(
            "rule.tax",
            present=ruleset is not None,
            provenance_complete=ruleset is not None,
            valid=ruleset is not None and ruleset.coverage_to >= as_of,
        ),
        "universe": ContextValue(
            "universe",
            present=bool(universe.built),
            provenance_complete=True,
            valid=bool(universe.built),
            observation_date=as_of,
            note=""
            if universe.built
            else "evaluation stopped at the time budget before any instrument was evaluated"
            if universe.partial
            else "no instruments with evaluable data",
        ),
    }
    if not personalised:
        for k in ("user.amount", "user.withdrawal_date", "user.objective", "user.loss_acceptable", "user.early_need"):
            context[k] = ContextValue(k, present=True, valid=True)  # exploration: illustrative values, labelled

    objective = p.objective if personalised and p.objective is not None else Objective.CAPITAL_PRESERVATION
    request = RankingRequest(
        objective=objective,
        amount=amount,
        horizon_days=horizon,
        max_days_to_cash=p.max_days_to_cash if personalised else None,
        credit_floor=p.credit_floor if personalised else None,
        loss_budget=p.max_loss_fraction if objective in (Objective.GROWTH, Objective.AGGRESSIVE_GROWTH) else None,
        max_exit_cost=None,
    )
    ranking: RankingResult | None = None
    if universe.built and (
        objective not in (Objective.GROWTH, Objective.AGGRESSIVE_GROWTH) or request.loss_budget is not None
    ):
        ranking = rank(request, [b.candidate for b in universe.built])

    facts = FactSheet()
    facts.add(Fact("amount", format_inr(amount), FactOrigin.USER_INPUT))
    n_ranked = len(ranking.ranked) if ranking else 0
    for fid, val in (
        ("universe.evaluated", len(universe.built)),
        ("universe.ranked", n_ranked),
        ("universe.skipped", universe.skipped_no_history),
        *((("universe.not_evaluated", universe.not_evaluated),) if universe.partial else ()),
    ):
        facts.add(
            Fact(
                fid,
                str(val),
                FactOrigin.ENGINE,
                value=Decimal(val),
                unit="count",
                formula_id="COUNT@1",
                input_hash=content_hash(val),
                engine_version=SERVICE_VERSION,
            )
        )
    by_id = {b.candidate.instrument_id: b for b in universe.built}
    if ranking and ranking.ranked:
        top = by_id[ranking.ranked[0].instrument_id]
        facts.add(_name_fact("top.name", top.candidate.instrument_id, top.candidate.name, universe))
        for item in ranking.ranked:
            facts.add(_name_fact(f"name.{item.instrument_id}", item.instrument_id, item.name, universe))
        facts.add(
            _engine_fact(
                "top.q05",
                format_inr(top.candidate.outcome.q05),
                top.candidate.outcome.q05,
                "INR",
                top.evidence.formula_id if top.evidence else "",
                top.evidence,
            )
        )

    workers = _workers(ranking, universe, facts) if ranking else []
    ordered = ranking is not None and ranking.status is RankStatus.RANKED and personalised
    disclosure_keys: tuple[str, ...] = (
        ("ranking", "projection", "past_performance")
        if ordered
        else ("projection", "past_performance")
        if ranking
        else ()
    )
    sup: SupervisorResult = run(
        manifest=MANIFEST,
        context=context,
        facts=facts,
        workers=workers,
        as_of=as_of,
        payload={"service": SERVICE_VERSION},
        disclosure_keys=disclosure_keys,
        engine_versions={"ranking": POLICY_VERSION, "candidates": cb.ENGINE_VERSION, "canonical": CANONICAL_VERSION},
        llm_rephrase=llm_rephrase,
    )

    def row(b: cb.BuiltCandidate, rank_no: int | None, reasons: Sequence[str], codes: Sequence[str]) -> dict[str, Any]:
        c = b.candidate
        prov = universe.sources.get(c.instrument_id, {})
        out: dict[str, Any] = {
            "instrument_id": c.instrument_id,
            "name": c.name,
            "kind": prov.get("kind"),
            "tier": c.tier.name,
            "rank": rank_no,
            "flags": list(c.flags),
            "reasons": list(reasons),
            "exclusion_codes": list(codes),
            "days_to_cash": c.days_to_cash,
            "contractual": c.outcome.is_contractual,
            "loss_frequency": _loss_display(b),
            "fixture": bool(prov.get("fixture")),
            "observed": prov.get("observation_date"),
            "outcome": None,
        }
        if b.evidence is not None:
            o = c.outcome
            out["outcome"] = {
                "q05": explained_outcome(b, "q05", o.q05, amount, horizon, prov),
                "q50": explained_outcome(b, "q50", o.q50, amount, horizon, prov),
                "q95": explained_outcome(b, "q95", o.q95, amount, horizon, prov),
                "gain_q50": {
                    "value": format(money(o.q50 - amount), "f"),
                    "display": format_inr(o.q50 - amount),
                    "pct": pct((o.q50 - amount) / amount),
                },
                "gain_q05": {
                    "value": format(money(o.q05 - amount), "f"),
                    "display": format_inr(o.q05 - amount),
                    "pct": pct((o.q05 - amount) / amount),
                },
            }
        return out

    ranked_rows: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []
    if ranking:
        for item in ranking.ranked:
            ranked_rows.append(row(by_id[item.instrument_id], item.rank if personalised else None, item.reasons, ()))
        for e in ranking.excluded:
            b = by_id[e.instrument_id]
            codes = list(b.ineligible_reasons) or list(e.reason_codes)
            excluded_rows.append(row(b, None, e.messages, codes))
    if not personalised:
        ranked_rows.sort(
            key=lambda r: (r["kind"] or "", r["name"])
        )  # exploration: grouped and alphabetical, NOT ranked

    status_text: str
    if sup.outcome is Outcome.ABSTAIN:
        status_text = "ABSTAIN"
    elif not personalised:
        status_text = "EXPLORATION"
    else:
        status_text = ranking.status.value if ranking else RankStatus.NO_SUITABLE_CANDIDATE.value

    budget_reason = [f"{TIME_BUDGET_EXCEEDED}: evaluation stopped at the time budget"] if universe.partial else []
    if universe.built:
        budget_reason = []  # with results, the flag is the `partial` field and the coverage claim instead
    output: dict[str, Any] = {
        "status": status_text,
        "mode": status.mode,
        "as_of": as_of.isoformat(),
        "context": {
            "amount": format_inr(amount),
            "amount_value": format(amount, "f"),
            "horizon_days": horizon,
            "withdrawal_date": withdrawal.isoformat(),
            "objective": objective.value,
            "illustrative": not personalised,
            "tax_basis": (
                tax_profile.label if tax_profile else "ILLUSTRATIVE 30 % slab, no surcharge (not your profile)"
            ),
        },
        "message": (ranking.message if ranking and ranking.message else None),
        "abstain_reasons": list(sup.abstain_reasons) + budget_reason,
        "policy": ranking.policy if ranking else None,
        "criteria": _criteria(request) if personalised else [],
        "ranked": ranked_rows,
        "excluded": excluded_rows,
        "skipped_no_history": universe.skipped_no_history,
        "partial": _partial(universe),
        "contains_fixtures": any(v.get("fixture") for v in universe.sources.values()),
        "report": None
        if sup.report is None
        else {
            "narrative": sup.report.narrative,
            "writer": sup.report.writer,
            "template_narrative": "\n".join(s.text for s in sup.report.sections),
            "rejected_llm_reasons": list(sup.report.rejected_llm_reasons),
            "sections": [
                {"worker": s.worker, "subject": s.subject, "topic": s.topic, "stance": s.stance, "text": s.text}
                for s in sup.report.sections
            ],
            "disclosures": list(sup.report.disclosures),
        },
        "conflicts": [
            {
                "subject": c.subject,
                "topic": c.topic,
                "supporting": list(c.supporting),
                "challenging": list(c.challenging),
                "material": c.material,
            }
            for c in sup.conflicts
        ],
        "run": {
            "input_hash": sup.record.input_hash,
            "output_hash": sup.record.output_hash,
            "versions": sup.record.versions,
        },
    }
    run_info: dict[str, Any] = output["run"]
    run_info["result_hash"] = content_hash({k: v for k, v in output.items() if k != "run"})
    # C-11 §3: the hash of everything the engine decided — ranking, numbers, exclusions and the TEMPLATE text — with
    # the optional LLM's wording, writer and AI disclosure left out. It is identical with and without the LLM.
    report = output["report"]
    run_info["ranking_hash"] = content_hash(
        {
            **{k: v for k, v in output.items() if k not in ("run", "report")},
            "report_sections": None if report is None else report["sections"],
            "template_narrative": None if report is None else report["template_narrative"],
        }
    )
    return output


def _partial(universe: Universe) -> dict[str, Any] | None:
    """The flag on a result whose universe build was cut short by the time budget (None = complete)."""
    if not universe.partial:
        return None
    return {
        "reason": TIME_BUDGET_EXCEEDED,
        "budget_s": int(DISCOVER_BUDGET_S),
        "incomplete_kinds": list(universe.incomplete_kinds),
        "mf_not_evaluated": universe.not_evaluated,
        "message": "Evaluation stopped at the time budget; instruments that were not reached are missing from this"
        " result, so it is not a complete comparison.",
    }


def _loss_display(b: cb.BuiltCandidate) -> dict[str, str] | None:
    c = b.candidate
    if b.evidence is None:
        return None
    if c.outcome.is_contractual:
        if c.loss_frequency is None and "CORPORATE_CREDIT_RISK" in c.flags:
            return {"value": "n/a", "display": "contractual; carries the issuer's default risk (rating only)"}
        if c.loss_frequency is None:
            return {"value": "n/a", "display": "contractual; uninsured part carries the institution's credit risk"}
        return {"value": "0", "display": "none (contractual)"}
    if c.loss_frequency is None:
        return None
    return {"value": str(c.loss_frequency), "display": f"{_count(b)} of {b.evidence.n_windows} historical windows"}


def _count(b: cb.BuiltCandidate) -> str:
    for k, v in b.evidence.inputs if b.evidence else ():
        if k == "loss_windows":
            return v.split(" of ")[0]
    return "0"


def _criteria(req: RankingRequest) -> list[str]:
    out = [f"Objective: {req.objective.value}", f"Amount {format_inr(req.amount)} for {req.horizon_days} days"]
    if req.objective in (Objective.CAPITAL_PRESERVATION, Objective.INCOME, Objective.LIQUIDITY):
        out.append(f"Historical frequency of loss at this horizon ≤ {pct(req.epsilon_loss_frequency)}")
        out.append("Low-end outcome must not fall below the amount invested")
        out.append(
            f"Market-linked options need at least {MIN_PRESERVATION_INDEPENDENT_WINDOWS} independent historical windows"
        )
    if req.loss_budget is not None:
        out.append(f"Low-end outcome within your loss budget of {pct(req.loss_budget)}")
    if req.max_days_to_cash is not None:
        out.append(f"Cash within {req.max_days_to_cash} days if needed early")
    if req.credit_floor:
        out.append(f"Credit rating at or above {req.credit_floor}")
    out.append(f"Ordering policy {POLICY_VERSION}")
    return out


def store_run(conn: sqlite3.Connection, output: dict[str, Any], at: datetime) -> str | None:
    """Store the run once per distinct result (content-addressed id). A repeat visit with unchanged inputs and data
    reads the existing row and writes nothing (A02: no DB write per Discovery visit). A PARTIAL result (time budget)
    is never stored: it depends on timing, not only on inputs, so it is not a reproducible run record."""
    if output.get("partial"):
        return None
    run_id = f"disc_{output['run']['result_hash'][:16]}"
    if conn.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone() is not None:
        return run_id
    with write_tx(conn):
        conn.execute(
            "INSERT INTO runs(run_id, kind, input_hash, versions_json, params_json, output_hash, output_json,"
            " created_at)"
            " VALUES (?, 'discover', ?, ?, ?, ?, ?, ?) ON CONFLICT(run_id) DO NOTHING",
            (
                run_id,
                output["run"]["input_hash"],
                canonical_json(output["run"]["versions"]),
                canonical_json(output["context"]),
                output["run"]["result_hash"],
                canonical_json(output),
                at.isoformat(),
            ),
        )
    return run_id
