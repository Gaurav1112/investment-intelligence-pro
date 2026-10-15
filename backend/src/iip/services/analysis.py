"""Analysis services (Stage D): compare, scenario, simulate, feasibility, forecast and risk.

Every number returned here is either (a) computed by a deterministic engine function from stored, dated observations
or the user's own inputs, or (b) an echo of such an input. Each is returned as an "Explained" dict (same shape as
``discovery.explained_outcome``) carrying its formula, inputs, sources, observation date, version and hash.

Nothing is filled with a default. When an engine gate refuses, or a shock does not apply to an instrument, the
response carries a typed refusal or "not applicable" with its reason — never a number (requirements §3.6a).
Decimals travel as strings; no float leaves this module.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal
from itertools import pairwise
from typing import Any

from iip.engine import candidates as cb
from iip.engine import macro
from iip.engine import scenarios as scn
from iip.engine import tax as tx
from iip.engine.dates import add_months
from iip.engine.deposits import (
    DepositHolding,
    InstitutionType,
    card_rate_for_tenure,
    dicgc_coverage,
    fd_premature_withdrawal,
)
from iip.engine.determinism import CANONICAL_VERSION, content_hash
from iip.engine.errors import EngineError, InsufficientHistory, InvalidInput, MissingData, StaleData
from iip.engine.feasibility import (
    EvidenceLevel,
    FeasibilityReport,
    FeasibilityRequest,
    InstrumentKind,
    Mode,
    Observation,
    SeriesMeta,
    assess_feasibility,
    percentile_type7,
)
from iip.engine.fixed_income import tbill_days, tbill_price
from iip.engine.forecasting import baselines as fb
from iip.engine.forecasting import validation as fv
from iip.engine.freshness import nav_is_stale
from iip.engine.money import ONE, PAISA, ZERO, D, engine_context, format_inr, from_float, money, pct
from iip.engine.ranking import Tier
from iip.engine.stats import metrics as rm
from iip.engine.stats.series import Frequency, ReturnSeries
from iip.services import bonds, discovery, inputs
from iip.services import profile as profile_svc
from iip.services.explain import badge, source_ref
from iip.services.instruments import FD_RATE_STALE_DAYS, TBILL_STALE_DAYS
from iip.services.profile import ILLUSTRATIVE_AMOUNT, ILLUSTRATIVE_HORIZON_DAYS

SERVICE_VERSION = "analysis@1.0.0"
DOWNSIDE_LABEL = "Illustrative downside scenario"
DISCLAIMER = "Not a recommendation. Not a forecast. Past outcomes do not indicate future results."
SCENARIO_ORDER = (
    "rate_bp",
    "spread_bp",
    "equity_pct",
    "inflation_pct",
    "exit_before_maturity_days",
    "reinvestment_rate",
)
WHICH = ("q05", "q50", "q95")
DOT_COUNT = 20
FORECAST_LEVELS_VALIDATION: tuple[float, float, float] = (0.10, 0.50, 0.90)
FORECAST_NOMINAL = 0.80
VAR_CONFIDENCES = (D("0.95"), D("0.99"))


class AnalysisError(Exception):
    """A request the service cannot answer; mapped to an HTTP status by the route layer."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


# ============================================================================================ context


@dataclass(frozen=True)
class Context:
    as_of: date
    amount: Decimal
    withdrawal: date
    amount_basis: str  # "request" | "profile" | "illustrative"
    date_basis: str
    tax_profile: tx.TaxProfile | None

    @property
    def horizon_days(self) -> int:
        return (self.withdrawal - self.as_of).days

    @property
    def illustrative(self) -> bool:
        return "illustrative" in (self.amount_basis, self.date_basis)

    def describe(self) -> dict[str, Any]:
        return {
            "amount": format_inr(self.amount),
            "amount_value": format(self.amount, "f"),
            "amount_basis": self.amount_basis,
            "withdrawal_date": self.withdrawal.isoformat(),
            "date_basis": self.date_basis,
            "horizon_days": self.horizon_days,
            "illustrative": self.illustrative,
            "illustrative_label": (
                "ILLUSTRATIVE — values not taken from your request or profile are the illustrative "
                f"{format_inr(ILLUSTRATIVE_AMOUNT)} for {ILLUSTRATIVE_HORIZON_DAYS} days"
                if self.illustrative
                else None
            ),
            "tax_basis": (
                self.tax_profile.label
                if self.tax_profile
                else "ILLUSTRATIVE 30 % slab, no surcharge (not your profile)"
            ),
        }

    def user_prov(self, what: str) -> dict[str, Any]:
        basis = self.amount_basis if what == "amount" else self.date_basis
        return {
            "source_id": f"user.{basis}",
            "url": "",
            "retrieved_at": None,
            "observation_date": self.as_of.isoformat(),
            "quality_status": "illustrative" if basis == "illustrative" else "user_input",
            "fixture": False,
        }


def resolve_context(
    conn: sqlite3.Connection, *, as_of: date, amount: Decimal | None, withdrawal: date | None
) -> Context:
    """Request value → saved profile → the labelled illustrative ₹1,00,000 for 182 days (each field separately)."""
    status = profile_svc.evaluate(profile_svc.load(conn), as_of)
    p = status.profile
    if amount is not None:
        if amount <= 0 or money(amount) != amount:
            raise AnalysisError(422, "INVALID_INPUT", "amount must be positive with at most two decimal places")
        amt, amt_basis = amount, "request"
    elif p.amount is not None:
        amt, amt_basis = p.amount, "profile"
    else:
        amt, amt_basis = ILLUSTRATIVE_AMOUNT, "illustrative"
    if withdrawal is not None:
        if withdrawal <= as_of:
            raise AnalysisError(422, "INVALID_INPUT", "withdrawal_date must be after the analysis date")
        wd, wd_basis = withdrawal, "request"
    elif p.withdrawal_date is not None and p.withdrawal_date > as_of:
        wd, wd_basis = p.withdrawal_date, "profile"
    else:
        wd, wd_basis = as_of + timedelta(days=ILLUSTRATIVE_HORIZON_DAYS), "illustrative"
    return Context(as_of, amt, wd, amt_basis, wd_basis, discovery._tax_profile(status))


def _require_rules(ruleset: tx.TaxRuleSet | None, as_of: date) -> tx.TaxRuleSet:
    if ruleset is None or ruleset.coverage_to < as_of:
        raise AnalysisError(409, "ABSTAIN", "No tax rule set covers the analysis date; after-tax outcomes refused.")
    return ruleset


# ============================================================================================ instruments


@dataclass(frozen=True)
class Built:
    """One instrument evaluated with the SAME engine candidate builders as discovery (build_universe)."""

    instrument_id: str
    name: str
    kind: str
    built: cb.BuiltCandidate | None  # None → not evaluable at all (reason in ``not_evaluable``)
    not_evaluable: tuple[str, ...]
    prov: dict[str, Any]
    category: str | None = None
    maturity: date | None = None
    institution: str | None = None
    dicgc_eligible: bool | None = None
    existing_same_bank: Decimal = ZERO
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def evaluable(self) -> bool:
        return self.built is not None and self.built.evidence is not None

    @property
    def fixture(self) -> bool:
        return bool(self.prov.get("fixture"))


def _instrument_row(conn: sqlite3.Connection, iid: str) -> sqlite3.Row:
    row: sqlite3.Row | None = conn.execute("SELECT * FROM instruments WHERE instrument_id=?", (iid,)).fetchone()
    if row is None:
        raise AnalysisError(404, "NOT_FOUND", f"instrument {iid!r} is not in the local store")
    return row


def build_one(
    conn: sqlite3.Connection,
    iid: str,
    *,
    amount: Decimal,
    as_of: date,
    withdrawal: date,
    ruleset: tx.TaxRuleSet,
    profile: tx.TaxProfile | None,
) -> Built:
    """Single-instrument form of ``discovery.build_universe`` (same SQL inputs, same engine builders).

    Kept equal to build_universe by a parity test; build_universe evaluates every instrument of a kind, which is
    wasteful for 2–4 instruments with per-holding amounts.
    """
    inst = _instrument_row(conn, iid)
    kind, name = str(inst["kind"]), str(inst["name"])
    if kind == "mf_scheme":
        return _build_mf(conn, inst, amount=amount, as_of=as_of, withdrawal=withdrawal, ruleset=ruleset,
                         profile=profile)  # fmt: skip
    if kind == "tbill":
        return _build_tbill(conn, inst, amount=amount, as_of=as_of, withdrawal=withdrawal, ruleset=ruleset,
                            profile=profile)  # fmt: skip
    if kind == "fd":
        return _build_fd(conn, inst, amount=amount, as_of=as_of, withdrawal=withdrawal, ruleset=ruleset,
                         profile=profile)  # fmt: skip
    if kind in bonds.BOND_KINDS:
        return _build_bond(conn, inst, amount=amount, as_of=as_of, withdrawal=withdrawal, ruleset=ruleset,
                           profile=profile)  # fmt: skip
    prov = {"kind": kind, "fixture": inst["origin"] == "fixture"}
    return Built(iid, name, kind, None, (f"UNSUPPORTED_KIND: no candidate builder for '{kind}' in this version",), prov)


def _build_bond(
    conn: sqlite3.Connection,
    inst: sqlite3.Row,
    *,
    amount: Decimal,
    as_of: date,
    withdrawal: date,
    ruleset: tx.TaxRuleSet,
    profile: tx.TaxProfile | None,
) -> Built:
    """Same loader/builder as discovery.build_universe (services/bonds.build_bond)."""
    iid, name, kind = str(inst["instrument_id"]), str(inst["name"]), str(inst["kind"])
    b, prov, not_evaluable = bonds.build_bond(
        conn, inst, amount=amount, as_of=as_of, withdrawal=withdrawal, ruleset=ruleset, profile=profile
    )
    terms = conn.execute("SELECT maturity_date FROM bond_terms WHERE instrument_id=?", (iid,)).fetchone()
    maturity = date.fromisoformat(terms["maturity_date"]) if terms else None
    return Built(iid, name, kind, b, not_evaluable, prov, maturity=maturity)


def _build_mf(
    conn: sqlite3.Connection,
    inst: sqlite3.Row,
    *,
    amount: Decimal,
    as_of: date,
    withdrawal: date,
    ruleset: tx.TaxRuleSet,
    profile: tx.TaxProfile | None,
) -> Built:
    iid, name, code = str(inst["instrument_id"]), str(inst["name"]), str(inst["amfi_code"])
    m = conn.execute("SELECT category_raw, exit_load_json FROM mf_schemes WHERE instrument_id=?", (iid,)).fetchone()
    cat = (m["category_raw"] if m else "") or ""
    n = conn.execute(
        "SELECT COUNT(*) FROM observations WHERE series_id=? AND superseded_by IS NULL", (f"nav:{code}",)
    ).fetchone()[0]
    if n < discovery.MIN_HISTORY_POINTS:
        prov = {"kind": "mf_scheme", "category": cat, "fixture": inst["origin"] == "fixture", "count": n}
        reason = f"INSUFFICIENT_HISTORY: {n} stored NAVs (need ≥ {discovery.MIN_HISTORY_POINTS}; backfill history)"
        return Built(iid, name, "mf_scheme", None, (reason,), prov, category=cat)
    dates, navs, prov = discovery._nav_series(conn, code, as_of)
    if prov["conflicts"]:  # same rule as build_universe: never evaluate a series the official sources disagree on
        conflict = [f"SOURCE_CONFLICT: official sources disagree on {prov['conflicts'][0]}"]
        b = cb._ineligible(iid, name, cb.mf_tier_from_category(cat), conflict, amount)
        return Built(iid, name, "mf_scheme", b, (), {**prov, "kind": "mf_scheme", "category": cat}, category=cat)
    load = None
    if m and m["exit_load_json"]:
        el = json.loads(m["exit_load_json"])
        load = cb.ExitLoadSpec(days=int(el["days"]), rate=Decimal(el["rate"]), citation=el["citation"])
    settle = 1 if cb.mf_tier_from_category(cat).name == "T3" else 3
    b = cb.mf_candidate(
        instrument_id=iid, name=name, category=cat, amount=amount, as_of=as_of, withdrawal=withdrawal,
        nav_dates=dates, navs=navs, exit_load=load, ruleset=ruleset, profile=profile, settlement_days=settle,
        credit_facts=inputs.fund_credit_facts(conn, iid, as_of),
    )  # fmt: skip
    return Built(iid, name, "mf_scheme", b, (), {**prov, "kind": "mf_scheme", "category": cat}, category=cat)


def _build_tbill(
    conn: sqlite3.Connection,
    inst: sqlite3.Row,
    *,
    amount: Decimal,
    as_of: date,
    withdrawal: date,
    ruleset: tx.TaxRuleSet,
    profile: tx.TaxProfile | None,
) -> Built:
    iid, name = str(inst["instrument_id"]), str(inst["name"])
    terms = conn.execute("SELECT maturity_date FROM bond_terms WHERE instrument_id=?", (iid,)).fetchone()
    r, problem = discovery.tbill_quote(conn, iid, as_of)  # same quote selection as build_universe
    if r is None or terms is None:
        prov = {"kind": "tbill", "fixture": inst["origin"] == "fixture"}
        return Built(iid, name, "tbill", None, ("MISSING_DATA: no yield observation stored",), prov)
    quote_date = date.fromisoformat(r["observation_date"])
    maturity = date.fromisoformat(terms["maturity_date"])
    if problem is not None:
        b = cb._ineligible(iid, name, Tier.T1, [problem], amount)
    elif (as_of - quote_date).days > TBILL_STALE_DAYS:
        b = cb._ineligible(iid, name, Tier.T1, [f"STALE_DATA: yield quoted {quote_date}"], amount)
    else:
        b = cb.tbill_candidate(
            instrument_id=iid, name=name, amount=amount, quoted_yield=Decimal(r["value"]),
            settlement=as_of + timedelta(days=1), maturity=maturity, withdrawal=withdrawal, ruleset=ruleset,
            profile=profile,
        )  # fmt: skip
    prov = {
        "kind": "tbill",
        "source_id": r["source_id"],
        "url": r["source_url"],
        "retrieved_at": r["retrieved_at"],
        "observation_date": r["observation_date"],
        "quality_status": r["quality_status"],
        "fixture": r["quality_status"] == "fixture",
    }
    prov["freshness"] = badge(prov, as_of)  # same age-checked badge as discovery.build_universe
    return Built(iid, name, "tbill", b, (), prov, maturity=maturity)


def _existing_deposits(conn: sqlite3.Connection, iid: str) -> Decimal:
    row = conn.execute("SELECT value_json FROM settings WHERE key=?", (f"fd.existing:{iid}",)).fetchone()
    return Decimal(json.loads(row["value_json"])) if row else ZERO


def _build_fd(
    conn: sqlite3.Connection,
    inst: sqlite3.Row,
    *,
    amount: Decimal,
    as_of: date,
    withdrawal: date,
    ruleset: tx.TaxRuleSet,
    profile: tx.TaxProfile | None,
) -> Built:
    iid, name = str(inst["instrument_id"]), str(inst["name"])
    r = conn.execute("SELECT * FROM deposit_terms WHERE instrument_id=?", (iid,)).fetchone()
    fixture = inst["origin"] == "fixture"
    if r is None:
        return Built(iid, name, "fd", None, ("MISSING_DATA: no deposit terms stored",), {"kind": "fd",
                     "fixture": fixture})  # fmt: skip
    rate_date = date.fromisoformat(r["rate_as_of"])
    existing = _existing_deposits(conn, iid)
    if rate_date > as_of:
        b = cb._ineligible(iid, name, Tier.T2, [f"LOOK_AHEAD: rate dated {rate_date}, after the analysis date"],
                           amount)  # fmt: skip
    elif (as_of - rate_date).days > FD_RATE_STALE_DAYS:
        b = cb._ineligible(iid, name, Tier.T2, [f"STALE_DATA: rate as of {rate_date}"], amount)
    else:
        b = cb.fd_candidate(
            instrument_id=iid, name=name, amount=amount, rate=Decimal(r["rate"]), start=as_of,
            tenure_days=int(r["tenure_days"]), withdrawal=withdrawal, dicgc_eligible=bool(r["dicgc_eligible"]),
            premature_penalty=None if r["premature_penalty"] is None else Decimal(r["premature_penalty"]),
            other_deposits_same_bank=existing, ruleset=ruleset, profile=profile,
            sovereign_backed=discovery.fd_institution_type(conn, iid) == "post_office",
        )  # fmt: skip
    prov = {
        "kind": "fd",
        "source_id": "bank.fd",
        "url": r["citation_url"],
        "retrieved_at": discovery.fd_entered_at(conn, iid, str(inst["created_at"])),
        "observation_date": r["rate_as_of"],
        "quality_status": "fixture" if fixture else "manual",
        "fixture": fixture,
    }
    prov["freshness"] = badge(prov, as_of)  # same age-checked badge as discovery.build_universe
    return Built(
        iid, name, "fd", b, (), prov,
        maturity=as_of + timedelta(days=int(r["tenure_days"])), institution=str(r["institution"]),
        dicgc_eligible=bool(r["dicgc_eligible"]), existing_same_bank=existing,
        extra={"premature_penalty": r["premature_penalty"]},
    )  # fmt: skip


# ============================================================================================ explained values


def _sources(prov: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not prov or not prov.get("source_id"):
        return []
    return [source_ref(prov)]


def _freshness(prov: Mapping[str, Any] | None) -> str:
    """Use the age-checked badge computed at load time (explain.badge); never default to a fresh label."""
    if not prov:
        return "DERIVED"
    if prov.get("fixture"):
        return "FIXTURE"
    if prov.get("quality_status") in ("user_input", "illustrative"):
        return {"user_input": "USER_INPUT", "illustrative": "ILLUSTRATIVE"}[str(prov["quality_status"])]
    return str(prov.get("freshness") or "UNKNOWN")


_FRESHNESS_RANK = {"FIXTURE": 4, "STALE": 3, "UNKNOWN": 2}


def _worst_freshness(prov: Mapping[str, Any] | None, extra: Sequence[Mapping[str, Any]]) -> str:
    out = _freshness(prov)
    for p in extra:
        f = _freshness(p)
        if _FRESHNESS_RANK.get(f, 0) > _FRESHNESS_RANK.get(out, 0):
            out = f
    return out


def _display(value: Decimal, unit: str) -> str:
    if unit == "INR":
        return format_inr(value)
    if unit == "fraction":
        return pct(value)
    if unit in ("count", "days", "observations"):
        return f"{value:f}"
    with engine_context():
        return f"{value.quantize(Decimal('0.0001')):f}"


def _value_text(value: Decimal, unit: str) -> str:
    return format(money(value), "f") if unit == "INR" else format(value, "f")


def explained(
    eid: str,
    label: str,
    value: Decimal,
    unit: str,
    *,
    what: str,
    formula_id: str,
    formula: str,
    substituted: str,
    inputs: Sequence[str],
    prov: Mapping[str, Any] | None,
    engine_version: str,
    assumptions: Sequence[str] = (),
    sensitivity: Sequence[Mapping[str, str]] = (),
    limitations: Sequence[str] = (),
    extra_prov: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """The Explained shape of ``discovery.explained_outcome`` for any engine-computed number.

    ``extra_prov``: further dated sources the number depends on (e.g. CPI, a factsheet, the T-bill series). They are
    listed as sources, and the freshness shown is the least fresh of all of them (fixture > stale > unknown)."""
    text = _value_text(value, unit)
    payload = {
        "id": eid,
        "value": text,
        "unit": unit,
        "formula_id": formula_id,
        "inputs": list(inputs),
        "engine_version": engine_version,
    }
    return {
        "id": eid,
        "label": label,
        "display": _display(value, unit),
        "value": text,
        "unit": unit,
        "what": what,
        "formula_id": formula_id,
        "formula": formula,
        "substituted": substituted,
        "inputs": list(inputs),
        "sources": _sources(prov) + [x for p in extra_prov for x in _sources(p)],
        "observed": prov.get("observation_date") if prov else None,
        "freshness": _worst_freshness(prov, extra_prov),
        "assumptions": list(assumptions),
        "sensitivity": [dict(s) for s in sensitivity],
        "limitations": list(limitations),
        "engine_version": engine_version,
        "hash": content_hash(payload),
    }


def refusal(eid: str, label: str, code: str, reason: str) -> dict[str, Any]:
    """A typed refusal: the metric is gated and NO number is returned."""
    return {"id": eid, "label": label, "status": "refused", "code": code, "reason": reason, "value": None}


def _outcome(b: Built, which: str, ctx: Context, *, amount: Decimal | None = None) -> dict[str, Any]:
    """discovery.explained_outcome, relabelled: the low end is an illustrative downside scenario, never worst case."""
    assert b.built is not None
    c = b.built.candidate
    value = getattr(c.outcome, which)
    out = discovery.explained_outcome(
        b.built, which, value, ctx.amount if amount is None else amount, ctx.horizon_days, b.prov
    )
    if which == "q05" and not c.outcome.is_contractual:
        out["label"] = f"{DOWNSIDE_LABEL} (after costs and assumed tax)"
    return out


def _tax_for(ev: cb.CandidateEvidence, which: str) -> Decimal:
    return {"q05": ev.tax_low, "q50": ev.tax_mid, "q95": ev.tax_high}[which]


def _pretax(b: Built, which: str) -> Decimal:
    """Proceeds after costs, before tax: net outcome + its tax (exactly as the candidate builder subtracted it)."""
    assert b.built is not None and b.built.evidence is not None
    with engine_context():
        net: Decimal = getattr(b.built.candidate.outcome, which)
        return net + _tax_for(b.built.evidence, which)


# ============================================================================================ macro inputs


@dataclass(frozen=True)
class _Inflation:
    basis: macro.InflationBasis
    prov: dict[str, Any]

    def horizon(self, days: int, delta_annual: Decimal = ZERO) -> Decimal:
        with engine_context():
            annual = self.basis.annual + delta_annual
        return macro.horizon_inflation(annual, days)

    def describe(self) -> list[str]:
        b = self.basis
        return [
            f"CPI inflation (trailing 12 months to {b.month:%Y-%m}, base {b.base_year}, {b.method.value}): {b.annual}",
            *[f"{k}: {v}" for k, v in b.inputs],
        ]


def _inflation(conn: sqlite3.Connection, as_of: date) -> _Inflation | tuple[str, str]:
    """The CPI inflation basis at ``as_of``, or (refusal code, reason). Bases are never mixed (engine.macro)."""
    points, provs = inputs.cpi_points(conn)
    try:
        basis = macro.select_inflation(points, as_of)
    except StaleData as exc:
        return "CPI_STALE", str(exc)
    except MissingData as exc:
        return "CPI_UNAVAILABLE", str(exc)
    prov = dict(provs[(basis.base_year, basis.month)])
    if prov.get("fixture"):
        prov["freshness"] = "FIXTURE"
    elif basis.freshness is macro.CpiFreshness.STALE:
        prov["freshness"] = "STALE"
    else:
        prov["freshness"] = "MANUAL" if prov.get("quality_status") == "manual" else "END_OF_DAY"
    return _Inflation(basis, prov)


_PROJECTION = (
    "Inflation over the horizon is a labelled projection: the latest trailing 12-month CPI inflation compounded over "
    "the horizon, (1 + π_12m)^(days/365) − 1. It is not a forecast"
)


def _real_returns(b: Built, ctx: Context, infl: _Inflation | tuple[str, str]) -> dict[str, Any]:
    """Real (inflation-adjusted) net return per band point, Fisher (calc §2.11), or a typed refusal."""
    if isinstance(infl, tuple):
        code, reason = infl
        return {w: refusal(f"{b.instrument_id}.real_return.{w}", f"Real return ({w})", code, reason) for w in WHICH}
    assert b.built is not None
    pi_h = infl.horizon(ctx.horizon_days)
    out: dict[str, Any] = {}
    for w in WHICH:
        net = getattr(b.built.candidate.outcome, w)
        with engine_context():
            r = (net - ctx.amount) / ctx.amount
        rr = scn.real_return(r, pi_h)
        out[w] = explained(
            f"{b.instrument_id}.real_return.{w}", f"Real return over {ctx.horizon_days} days ({w})", rr.value,
            "fraction",
            what="Net return after costs and assumed tax, adjusted for CPI inflation over the same horizon (Fisher).",
            formula_id=rr.method_id, formula="r_real = (1 + r_nom) / (1 + π_H) − 1",
            substituted=f"(1 + {pct(r)}) / (1 + {pct(pi_h)}) − 1 = {pct(rr.value)}",
            inputs=[f"net return ({w}): {r}", f"π over {ctx.horizon_days} days: {pi_h}", *infl.describe()],
            prov=b.prov, engine_version=SERVICE_VERSION, extra_prov=[infl.prov],
            assumptions=[_PROJECTION, *infl.basis.caveats],
            limitations=[f"r − π approximation (labelled only): {pct(rr.approximation)}"],
        )  # fmt: skip
    return out


def _debt_fund(b: Built) -> bool:
    """Debt-category schemes whose factsheet duration describes the whole portfolio (not hybrids)."""
    cat = b.category or ""
    return b.kind == "mf_scheme" and cb.mf_tax_class_from_category(cat) is cb.MfTaxClass.SPECIFIED_DEBT


def _facts_caveat(facts: Mapping[str, Any]) -> str:
    stale = " — STALE (older than 45 days)" if facts["freshness"] == "STALE" else ""
    return f"FACTSHEET_AS_OF_{facts['as_of_date']}{stale}"


# ============================================================================================ compare


def _gross(b: Built, which: str) -> Decimal:
    assert b.built is not None and b.built.evidence is not None
    ev = b.built.evidence
    if ev.gross_end_value is not None:
        return ev.gross_end_value
    assert ev.band_gross is not None
    return ev.band_gross[WHICH.index(which)]


def _absolute_return(b: Built, which: str, ctx: Context, amount: Decimal) -> dict[str, Any]:
    assert b.built is not None
    net = getattr(b.built.candidate.outcome, which)
    with engine_context():
        r = (net - amount) / amount
    out: dict[str, Any] = {
        "absolute": explained(
            f"{b.instrument_id}.return_abs.{which}",
            f"Absolute return over {ctx.horizon_days} days ({which})",
            r,
            "fraction",
            what=f"Net proceeds versus the amount invested, over the whole {ctx.horizon_days}-day horizon "
            "(not annualised).",
            formula_id="ABS_RETURN@1",
            formula="r = (net proceeds − amount) / amount",
            substituted=f"({format_inr(net)} − {format_inr(amount)}) / {format_inr(amount)} = {pct(r)}",
            inputs=[f"net proceeds ({which}): {net}", f"amount: {amount}"],
            prov=b.prov,
            engine_version=SERVICE_VERSION,
        ),
        "annualised": None,
        "annualisation_note": "Not annualised: the horizon is shorter than 365 days.",
    }
    if ctx.horizon_days >= 365 and ONE + r > 0:
        with engine_context():
            ann = (ONE + r) ** (Decimal(365) / Decimal(ctx.horizon_days)) - ONE
        out["annualised"] = explained(
            f"{b.instrument_id}.return_ann.{which}",
            f"Annualised equivalent ({which}) — secondary",
            ann,
            "fraction",
            what="Compound annual rate that would give the same absolute return over this horizon. Secondary; "
            "the absolute figure is the headline.",
            formula_id="ANNUALISE_COMPOUND@1",
            formula="(1 + r)^(365 / days) − 1",
            substituted=f"(1 + {pct(r)})^(365 / {ctx.horizon_days}) − 1 = {pct(ann)}",
            inputs=[f"absolute return: {r}", f"days: {ctx.horizon_days}"],
            prov=b.prov,
            engine_version=SERVICE_VERSION,
        )
        out["annualisation_note"] = "Annualised figure is secondary (horizon ≥ 365 days)."
    return out


def _exit_cost(b: Built) -> dict[str, Any]:
    assert b.built is not None
    c = b.built.candidate
    if "PREMATURE_PENALTY_UNKNOWN" in c.flags:
        return refusal(f"{b.instrument_id}.exit_cost", "Exit cost", "UNKNOWN",
                       "The bank's premature-withdrawal penalty is not recorded.")  # fmt: skip
    formula = {
        "mf_scheme": "exit-load rate that applies if redeemed at your withdrawal date (scheme terms)",
        "tbill": "no early-exit cost modelled (held to maturity; secondary-market spread not modelled)",
        "fd": "premature penalty × tenure in years (ranking policy's exit-cost measure)",
        **dict.fromkeys(
            bonds.BOND_KINDS,
            "transaction spread you entered (fraction of the clean price); 100 % when unknown or no exchange exit",
        ),
    }[b.kind]
    return explained(
        f"{b.instrument_id}.exit_cost",
        "Exit cost (ranking measure)",
        c.exit_cost,
        "fraction",
        what="The early-exit cost measure the ranking policy uses for this instrument.",
        formula_id=f"EXIT_COST_{b.kind.upper()}@1",
        formula=formula,
        substituted=f"exit cost = {pct(c.exit_cost)}",
        inputs=[f"{k}: {v}" for k, v in (b.built.evidence.inputs if b.built.evidence else ())],
        prov=b.prov,
        engine_version=cb.ENGINE_VERSION,
        limitations=["Bid/ask spreads and market impact are not modelled"],
    )


def _compare_row(b: Built, ctx: Context, infl: _Inflation | tuple[str, str]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "instrument_id": b.instrument_id,
        "name": b.name,
        "kind": b.kind,
        "fixture": b.fixture,
        "observed": b.prov.get("observation_date"),
        "freshness": _freshness(b.prov),
        "evaluable": b.evaluable,
        "eligibility_reasons": list(b.not_evaluable),
        "tier": None,
        "flags": [],
    }
    if b.built is None:
        return row
    c = b.built.candidate
    row["tier"] = c.tier.name
    row["flags"] = list(c.flags)
    row["eligibility_reasons"] = list(b.built.ineligible_reasons) + list(b.built.warnings)
    if b.built.evidence is None:
        return row
    ev = b.built.evidence
    amount = ctx.amount
    row["initial_investment"] = explained(
        f"{b.instrument_id}.amount", "Initial investment", amount, "INR",
        what="The amount invested, as given in your request, your profile, or the labelled illustrative amount.",
        formula_id="INPUT@1", formula="user input", substituted=format_inr(amount),
        inputs=[f"amount basis: {ctx.amount_basis}"], prov=ctx.user_prov("amount"), engine_version=SERVICE_VERSION,
    )  # fmt: skip
    gross, costs, taxes, pnl, rets = {}, {}, {}, {}, {}
    for which in WHICH:
        g = _gross(b, which)
        pre = _pretax(b, which)
        t = _tax_for(ev, which)
        net = getattr(c.outcome, which)
        with engine_context():
            load_inr = g - pre
            if pre - t != net:  # decomposition must reconcile exactly; never paper over a mismatch
                raise AnalysisError(500, "RECONCILIATION_FAILED", f"{b.instrument_id}: gross/cost/tax do not reconcile")
            gain = net - amount
        gross[which] = explained(
            f"{b.instrument_id}.gross.{which}", f"Gross proceeds ({which})", g, "INR",
            what="Value at the withdrawal date before exit costs and tax (after purchase stamp duty for funds).",
            formula_id=ev.formula_id,
            formula="gross = units × NAV at exit (funds); face or maturity amount (contractual)",
            substituted=f"gross {format_inr(g)}", inputs=[f"{k}: {v}" for k, v in ev.inputs], prov=b.prov,
            engine_version=cb.ENGINE_VERSION, assumptions=list(ev.assumptions), limitations=list(ev.limitations),
        )  # fmt: skip
        costs[which] = explained(
            f"{b.instrument_id}.exit_load_inr.{which}", f"Exit load in ₹ ({which})", load_inr, "INR",
            what="Exit load deducted at redemption (zero when the horizon is beyond the load period).",
            formula_id="EXIT_LOAD_INR@1", formula="gross − proceeds after load",
            substituted=f"{format_inr(g)} − {format_inr(pre)} = {format_inr(load_inr)}",
            inputs=[f"cost {k}: {v}" for k, v in ev.costs], prov=b.prov, engine_version=cb.ENGINE_VERSION,
        )  # fmt: skip
        taxes[which] = explained(
            f"{b.instrument_id}.tax.{which}", f"Assumed tax ({which})", t, "INR",
            what=f"Tax on the gain under the {ev.tax_basis.value} basis.",
            formula_id="TAX_ON_GAIN@1", formula="tax(gain) under the versioned tax rule set",
            substituted=f"tax = {format_inr(t)}",
            inputs=[f"tax basis: {ev.tax_basis.value}", *[f"rule: {r}" for r in ev.tax_rule_ids]],
            prov=b.prov, engine_version=cb.ENGINE_VERSION,
            assumptions=(["Tax computed under an ILLUSTRATIVE 30 % slab profile (not yours)"]
                         if ev.tax_basis is cb.TaxBasis.ILLUSTRATIVE else []),
            limitations=["Tax rule pending CA review"] if ev.tax_unverified else [],
        )  # fmt: skip
        pnl[which] = explained(
            f"{b.instrument_id}.pnl.{which}", f"Net profit or loss ({which})", gain, "INR",
            what="Net proceeds minus the amount invested.", formula_id="NET_PNL@1",
            formula="net proceeds − amount",
            substituted=f"{format_inr(net)} − {format_inr(amount)} = {format_inr(gain)}",
            inputs=[f"net: {net}", f"amount: {amount}"], prov=b.prov, engine_version=SERVICE_VERSION,
        )  # fmt: skip
        rets[which] = _absolute_return(b, which, ctx, amount)
    stamp = dict(ev.costs).get("stamp_duty")
    row.update(
        {
            "contractual": c.outcome.is_contractual,
            "gross_proceeds": gross,
            "costs": {
                "exit_load": costs,
                "stamp_duty": None if stamp is None else explained(
                    f"{b.instrument_id}.stamp_duty", "Stamp duty at purchase", stamp, "INR",
                    what="0.005 % stamp duty on the purchase amount; already deducted before units are allotted.",
                    formula_id="STAMP_DUTY@1", formula="amount × 0.00005 / 1.00005",
                    substituted=f"{format_inr(amount)} × 0.00005 / 1.00005 = {format_inr(stamp)}",
                    inputs=[f"amount: {amount}"], prov=b.prov, engine_version=cb.ENGINE_VERSION,
                ),
                "note": None if ev.costs else "No transaction costs are modelled for this instrument (see limits).",
            },
            "tax": {"basis": ev.tax_basis.value, "rule_ids": list(ev.tax_rule_ids), "unverified": ev.tax_unverified,
                    "values": taxes},
            "net_proceeds": {w: _outcome(b, w, ctx) for w in WHICH},
            "net_pnl": pnl,
            "returns": rets,
            "liquidity": {
                "days_to_cash": c.days_to_cash,
                "lock_in_days": cb.mf_lock_in_days(b.category or "") if b.kind == "mf_scheme" else None,
            },
            "exit_cost": _exit_cost(b),
            "real_return": _real_returns(b, ctx, infl),
            "loss_frequency": discovery._loss_display(b.built),
        }
    )  # fmt: skip
    return row


def _run_block(request: Mapping[str, Any], output: Mapping[str, Any], versions: Mapping[str, str]) -> dict[str, Any]:
    return {
        "input_hash": content_hash(dict(request)),
        "result_hash": content_hash({k: v for k, v in output.items() if k != "run"}),
        "versions": dict(versions),
    }


_VERSIONS = {"analysis": SERVICE_VERSION, "candidates": cb.ENGINE_VERSION, "canonical": CANONICAL_VERSION}


def compare(
    conn: sqlite3.Connection,
    *,
    as_of: date,
    ruleset: tx.TaxRuleSet | None,
    instrument_ids: Sequence[str],
    amount: Decimal | None,
    withdrawal: date | None,
) -> dict[str, Any]:
    if not 2 <= len(instrument_ids) <= 4 or len(set(instrument_ids)) != len(instrument_ids):
        raise AnalysisError(422, "INVALID_INPUT", "compare needs 2–4 distinct instruments")
    rules = _require_rules(ruleset, as_of)
    ctx = resolve_context(conn, as_of=as_of, amount=amount, withdrawal=withdrawal)
    built = [
        build_one(conn, iid, amount=ctx.amount, as_of=as_of, withdrawal=ctx.withdrawal, ruleset=rules,
                  profile=ctx.tax_profile)
        for iid in instrument_ids
    ]  # fmt: skip
    infl = _inflation(conn, as_of)
    rows = [_compare_row(b, ctx, infl) for b in built]
    evaluable = sorted(
        (b for b in built if b.evaluable),
        key=lambda b: (-b.built.candidate.outcome.q05 if b.built else ZERO, b.instrument_id),
    )
    changes: list[dict[str, Any]] = []
    for a, b in pairwise(evaluable):
        assert a.built is not None and b.built is not None
        # Rounded to paise first, so the displayed subtraction reconciles exactly with the displayed q05 values.
        qa, qb = money(a.built.candidate.outcome.q05), money(b.built.candidate.outcome.q05)
        with engine_context():
            gap = qa - qb
        text = (
            f"{a.name} and {b.name} have the same {DOWNSIDE_LABEL.lower()}; their order is decided by instrument id."
            if gap == 0
            else f"{b.name} would move above {a.name} if its {DOWNSIDE_LABEL.lower()} rose by more than "
            f"{format_inr(gap)} (or {a.name}'s fell by that much)."
        )
        changes.append(
            {
                "above": a.instrument_id,
                "below": b.instrument_id,
                "text": text,
                "gap": explained(
                    f"order.{a.instrument_id}.{b.instrument_id}.q05_gap", "Gap in illustrative downside scenario",
                    gap, "INR", what="Difference between the two low-end (q05) net proceeds that sets this order.",
                    formula_id="ORDER_GAP_Q05@1", formula="gap = q05(above) − q05(below)",
                    substituted=f"{format_inr(qa)} − {format_inr(qb)} = {format_inr(gap)}",
                    inputs=[f"q05 {a.instrument_id}: {qa}", f"q05 {b.instrument_id}: {qb}"], prov=None,
                    engine_version=SERVICE_VERSION,
                ),
            }
        )  # fmt: skip
    request = {
        "instrument_ids": list(instrument_ids),
        "amount": None if amount is None else str(amount),
        "withdrawal_date": None if withdrawal is None else withdrawal.isoformat(),
        "as_of": as_of.isoformat(),
    }
    out: dict[str, Any] = {
        "status": "OK",
        "as_of": as_of.isoformat(),
        "context": ctx.describe(),
        "request": request,
        "rows": rows,
        "order_basis": (
            f"{DOWNSIDE_LABEL} (q05 net proceeds), highest first; ties by instrument id. "
            "Ordering reflects this one measure only."
        ),
        "order": [b.instrument_id for b in evaluable],
        "what_would_change_order": changes,
        "fixture": any(b.fixture for b in built),
        "disclaimer": DISCLAIMER,
    }
    out["run"] = _run_block(request, out, _VERSIONS)
    return out


# ============================================================================================ scenario


@dataclass(frozen=True)
class _Applied:
    results: tuple[tuple[str, scn.ScenarioResult], ...]  # (which, result)
    measure: str
    extra_prov: tuple[dict[str, Any], ...] = ()  # further dated sources (CPI, factsheet, card-rate table)


@dataclass(frozen=True)
class _Env:
    """Stored inputs a scenario may need, loaded once per request."""

    inflation: _Inflation | tuple[str, str]
    facts: dict[str, Any] | None  # latest factsheet facts (mutual funds), with provenance under "prov"
    card_rates: dict[str, Any] | None  # latest card-rate table for the FD's institution


@dataclass(frozen=True)
class _NotApplicable:
    reason: str


_Outcome = _Applied | _NotApplicable


def _is_equity_scheme(category: str | None) -> bool:
    return (category or "").lower().startswith("equity scheme")


def _tbill_exit(b: Built, exit_days: int) -> tuple[date, date, Decimal, Decimal] | _NotApplicable:
    """(exit date, maturity, quoted yield, face) for an early T-bill sale, or why it cannot be modelled."""
    assert b.built is not None and b.built.evidence is not None
    inputs = dict(b.built.evidence.inputs)
    settlement = date.fromisoformat(inputs["settlement"])
    maturity = date.fromisoformat(inputs["maturity"])
    exit_date = settlement + timedelta(days=exit_days)
    if not settlement < exit_date < maturity:
        return _NotApplicable(
            f"Exit after {exit_days} days falls on {exit_date}, not strictly between settlement ({settlement}) "
            f"and maturity ({maturity})."
        )
    face = b.built.evidence.gross_end_value
    assert face is not None
    return exit_date, maturity, Decimal(inputs["quoted_yield"]), face


def _tbill_sale_value(y: Decimal, exit_date: date, maturity: date, face: Decimal) -> Decimal:
    res = tbill_price(y, tbill_days(exit_date, maturity), face_amount=face)
    assert res.consideration is not None
    return res.consideration


def _shock_rate(b: Built, value: Decimal, shocks: Mapping[str, Any], ctx: Context, env: _Env) -> _Outcome:
    if b.kind == "tbill":
        exit_days = shocks.get("exit_before_maturity_days")
        if exit_days is None:
            return _NotApplicable(
                "Held to maturity, a T-bill repays its face value whatever rates do. A rate change affects only an "
                "early sale: set exit_before_maturity_days to see the sale price."
            )
        ex = _tbill_exit(b, int(exit_days))
        if isinstance(ex, _NotApplicable):
            return ex
        exit_date, maturity, y, face = ex
        with engine_context():
            dy = value * scn.BP
            y1 = y + dy
        base = _tbill_sale_value(y, exit_date, maturity, face)
        shocked = _tbill_sale_value(y1, exit_date, maturity, face)
        res = scn._build(
            scenario_id="SCN_TBILL_EARLY_SALE_RATE@1",
            label=scn.ScenarioLabel.STRESS,
            inputs=[
                scn.Quantity("face_amount", face, "INR"),
                scn.Quantity("base_yield", y, "fraction"),
                scn.Quantity("delta_yield", dy, "fraction"),
                scn.Quantity("days_to_maturity_at_exit", Decimal(tbill_days(exit_date, maturity)), "days"),
            ],
            outputs=[scn.Quantity("sale_value_base", base, "INR"), scn.Quantity("sale_value_shocked", shocked, "INR")],
            base_value=base,
            shocked_value=shocked,
            approximate=False,
            caveats=["FULL_REPRICING_TBILL_PRICE@1", "EXIT_PRICE_UNKNOWN_ILLUSTRATIVE_YIELD", "BID_ASK_NOT_MODELLED"],
        )
        return _Applied((("value", res),), f"sale proceeds on {exit_date}, before tax")
    if b.kind == "fd":
        return _NotApplicable("A fixed deposit pays its booked contractual rate; later rate changes do not alter it.")
    if b.kind in bonds.BOND_KINDS:
        return _NotApplicable(_BOND_RATE_TEXT)
    if _is_equity_scheme(b.category):
        return _NotApplicable("Interest-rate shocks apply to debt holdings; use equity_pct for an equity fund.")
    if not _debt_fund(b):
        return _NotApplicable(
            "A hybrid or other fund's factsheet duration covers only its debt portion, and the split is not modelled. "
            "No duration is assumed for the whole fund."
        )
    facts = env.facts
    if facts is None or facts["modified_duration"] is None:
        return _NotApplicable(
            "A rate shock on a debt fund needs its modified duration from the scheme's factsheet, which is not in the "
            "local store. Enter the factsheet facts; no duration is assumed."
        )
    d_mod = Decimal(facts["modified_duration"])
    as_of_date = date.fromisoformat(facts["as_of_date"])
    with engine_context():
        dy = value * scn.BP
    out = tuple(
        (w, _with_caveats(scn.rate_shock_duration(_pretax(b, w), d_mod, dy, duration_as_of=as_of_date, as_of=ctx.as_of,
                                                  label=scn.ScenarioLabel.STRESS),
                          ["FUND_DURATION_FROM_FACTSHEET", _facts_caveat(facts)]))
        for w in WHICH
    )  # fmt: skip
    return _Applied(
        out,
        f"proceeds at the withdrawal date, before tax — APPROXIMATE (modified duration {d_mod} from the factsheet "
        f"as of {facts['as_of_date']}{', STALE' if facts['freshness'] == 'STALE' else ''})",
        (facts["prov"],),
    )


_BOND_RATE_TEXT = (
    "Held to maturity, the bond pays its contractual coupons and face value whatever yields do. If your withdrawal "
    "date is before maturity, the outcome band already reprices the sale at +100 / 0 / −100 bp (plus the exit "
    "spread); use exit_before_maturity_days for an earlier sale."
)


def _with_caveats(res: scn.ScenarioResult, extra: Sequence[str]) -> scn.ScenarioResult:
    return replace(res, caveats=tuple(dict.fromkeys((*res.caveats, *extra))))


def _shock_spread(b: Built, value: Decimal, shocks: Mapping[str, Any], ctx: Context, env: _Env) -> _Outcome:
    if b.kind == "tbill":
        return _NotApplicable("A Government of India T-bill carries no credit spread.")
    if b.kind == "fd":
        return _NotApplicable("A bank deposit has no traded credit spread; its credit risk is shown as DICGC cover.")
    if b.kind in bonds.BOND_KINDS:
        return _NotApplicable(_BOND_RATE_TEXT)
    if _is_equity_scheme(b.category):
        return _NotApplicable("Credit-spread shocks apply to debt holdings, not to an equity fund.")
    if not _debt_fund(b):
        return _NotApplicable(
            "A hybrid or other fund's factsheet duration covers only its debt portion, and the split is not modelled. "
            "No spread duration is assumed."
        )
    facts = env.facts
    if facts is None or facts["modified_duration"] is None:
        return _NotApplicable(
            "A spread shock on a debt fund needs its duration from the scheme's factsheet, which is not in the local "
            "store. Enter the factsheet facts; no duration is assumed."
        )
    if facts["share_sovereign_cash"] is not None and Decimal(facts["share_sovereign_cash"]) == ONE:
        return _NotApplicable("The factsheet shows 100 % sovereign and cash holdings: no credit-spread exposure.")
    if value < 0:
        return _NotApplicable(
            "Spread tightening is not modelled for a fund: the duration proxy would overstate the gain (sovereign and "
            "cash holdings carry no spread)."
        )
    d_mod = Decimal(facts["modified_duration"])
    with engine_context():
        ds = value * scn.BP
    caveats = ["SPREAD_DURATION_PROXY_IS_PORTFOLIO_MODIFIED_DURATION",
               "LOSS_MAGNITUDE_OVERSTATED_SOVEREIGN_CASH_HAS_NO_SPREAD", _facts_caveat(facts)]  # fmt: skip
    if (ctx.as_of - date.fromisoformat(facts["as_of_date"])).days > scn.STALE_DURATION_DAYS:
        caveats.append("STALE_DURATION")
    out = tuple(
        (w, _with_caveats(scn.spread_shock_duration(_pretax(b, w), d_mod, ds, label=scn.ScenarioLabel.STRESS), caveats))
        for w in WHICH
    )  # fmt: skip
    return _Applied(
        out,
        f"proceeds at the withdrawal date, before tax — APPROXIMATE (spread duration taken as the portfolio modified "
        f"duration {d_mod}, factsheet as of {facts['as_of_date']}{', STALE' if facts['freshness'] == 'STALE' else ''})",
        (facts["prov"],),
    )


def _shock_equity(b: Built, value: Decimal, shocks: Mapping[str, Any], ctx: Context, env: _Env) -> _Outcome:
    if b.kind != "mf_scheme" or not _is_equity_scheme(b.category):
        return _NotApplicable("Equity shocks apply only to equity-scheme funds; this holding has no modelled equity "
                              "exposure.")  # fmt: skip
    with engine_context():
        shock = value / Decimal(100)
    out = tuple(
        (w, scn.equity_drawdown_shock(_pretax(b, w), shock, beta=ONE, label=scn.ScenarioLabel.STRESS)) for w in WHICH
    )
    return _Applied(out, "proceeds at the withdrawal date, before tax (shock applied to this fund's own NAV, β = 1)")


def _shock_inflation(b: Built, value: Decimal, shocks: Mapping[str, Any], ctx: Context, env: _Env) -> _Outcome:
    infl = env.inflation
    if isinstance(infl, tuple):
        return _NotApplicable(
            f"{infl[0]}: {infl[1]}. The base inflation rate that a real-return shock starts from is unknown; no "
            "inflation rate is assumed."
        )
    with engine_context():
        delta_annual = value / Decimal(100)
        shocked_annual = infl.basis.annual + delta_annual
    base_pi = infl.horizon(ctx.horizon_days)
    try:
        shocked_pi = infl.horizon(ctx.horizon_days, delta_annual)
    except InvalidInput:
        return _NotApplicable("The shocked inflation rate would be −100 % or lower.")
    with engine_context():
        delta_h = shocked_pi - base_pi
    out = []
    for w in WHICH:
        pre = _pretax(b, w)
        with engine_context():
            nominal = pre / ctx.amount - ONE
        res = scn.inflation_scenario(ctx.amount, nominal_return=nominal, base_inflation=base_pi,
                                     delta_inflation=delta_h, label=scn.ScenarioLabel.STRESS)  # fmt: skip
        caveats = [f"CPI_{infl.basis.method.value.upper()}_BASE{infl.basis.base_year}_{infl.basis.month:%Y-%m}",
                   "INFLATION_PROJECTION_TRAILING_12M_NOT_A_FORECAST", *infl.basis.caveats]  # fmt: skip
        out.append((w, _with_caveats(res, caveats)))
    return _Applied(
        tuple(out),
        f"value in today's rupees (real), before tax: trailing 12-month CPI inflation {pct(infl.basis.annual)} "
        f"(base {infl.basis.base_year}, {infl.basis.month:%Y-%m}) vs {pct(shocked_annual)} a year, each compounded "
        f"over {ctx.horizon_days} days",
        (infl.prov,),
    )


def _shock_exit(
    b: Built, value: Decimal, shocks: Mapping[str, Any], ctx: Context, env: _Env, rebuild: Callable[[date], Built]
) -> _Outcome:
    days = int(value)
    if b.kind == "tbill":
        ex = _tbill_exit(b, days)
        if isinstance(ex, _NotApplicable):
            return ex
        exit_date, maturity, y, face = ex
        sale = _tbill_sale_value(y, exit_date, maturity, face)
        res = scn._build(
            scenario_id="SCN_TBILL_EARLY_SALE@1",
            label=scn.ScenarioLabel.ILLUSTRATIVE_DOWNSIDE,
            inputs=[
                scn.Quantity("face_amount", face, "INR"),
                scn.Quantity("quoted_yield", y, "fraction"),
                scn.Quantity("exit_after_days", Decimal(days), "days"),
            ],
            outputs=[scn.Quantity("sale_value", sale, "INR")],
            base_value=face,
            shocked_value=sale,
            approximate=False,
            caveats=["SALE_AT_UNCHANGED_YIELD", "EARLIER_CASH_DATE", "BID_ASK_NOT_MODELLED"],
        )
        return _Applied((("value", res),), f"held-to-maturity value vs sale on {exit_date}, before tax")
    if b.kind == "fd":
        return _fd_early_exit(b, days, ctx, env)
    if days >= ctx.horizon_days:
        return _NotApplicable(f"Exit after {days} days is not before your {ctx.horizon_days}-day horizon.")
    early = rebuild(ctx.as_of + timedelta(days=days))
    if not early.evaluable:
        reasons = early.not_evaluable or (early.built.ineligible_reasons if early.built else ())
        what = "bond" if b.kind in bonds.BOND_KINDS else "fund"
        return _NotApplicable(f"The {what} cannot be evaluated at the earlier date: " + "; ".join(reasons))
    out = tuple(
        (
            w,
            scn._build(
                scenario_id="SCN_BOND_EARLY_EXIT@1" if b.kind in bonds.BOND_KINDS else "SCN_MF_EARLY_EXIT@1",
                label=scn.ScenarioLabel.ILLUSTRATIVE_DOWNSIDE,
                inputs=[scn.Quantity("exit_after_days", Decimal(days), "days"),
                        scn.Quantity("horizon_days", Decimal(ctx.horizon_days), "days")],
                outputs=[scn.Quantity("early_exit_value", _pretax(early, w), "INR")],
                base_value=_pretax(b, w),
                shocked_value=_pretax(early, w),
                approximate=False,
                caveats=(["SALE_PRICE_STRESS_SCENARIOS", "TRANSACTION_SPREAD_PER_ENTRY", "EARLIER_CASH_DATE"]
                         if b.kind in bonds.BOND_KINDS else
                         ["DISTRIBUTION_AT_SHORTER_HORIZON", "EXIT_LOAD_PER_SCHEME_TERMS", "EARLIER_CASH_DATE"]),
            ),
        )
        for w in WHICH
    )  # fmt: skip
    exit_on = ctx.as_of + timedelta(days=days)
    return _Applied(out, f"proceeds before tax: withdrawal on {ctx.withdrawal} vs exit on {exit_on}")


def _fd_early_exit(b: Built, days: int, ctx: Context, env: _Env) -> _Outcome:
    """calc §3.3: card rate for the tenure actually run (bank's table on the booking date) minus the bank's penalty."""
    assert b.built is not None and b.built.evidence is not None
    penalty_text = b.extra.get("premature_penalty")
    if penalty_text is None:
        return _NotApplicable(
            "The bank's premature-withdrawal penalty is not recorded for this deposit; none is assumed."
        )
    table = env.card_rates
    if table is None:
        return _NotApplicable(
            f"No card-rate table is stored for {b.institution} on or before {ctx.as_of}. A premature payout uses the "
            "card rate for the shorter tenure actually run; enter the bank's table with its citation. No rate is "
            "assumed."
        )
    table_date = date.fromisoformat(table["as_of"])
    if (ctx.as_of - table_date).days > FD_RATE_STALE_DAYS:
        return _NotApplicable(f"The card-rate table for {b.institution} is dated {table_date} (older than "
                              f"{FD_RATE_STALE_DAYS} days); it is not used.")  # fmt: skip
    assert b.maturity is not None
    exit_date = ctx.as_of + timedelta(days=days)
    if not ctx.as_of < exit_date < b.maturity:
        return _NotApplicable(f"Exit after {days} days falls on {exit_date}, not strictly before maturity "
                              f"({b.maturity}).")  # fmt: skip
    try:
        bucket = card_rate_for_tenure(table["engine_buckets"], days)
    except MissingData as exc:
        return _NotApplicable(f"{exc}; no rate is taken from a neighbouring tenure.")
    booked = Decimal(dict(b.built.evidence.inputs)["rate"])
    res = fd_premature_withdrawal(
        ctx.amount, booked, ctx.as_of, b.maturity, exit_date, period_card_rate=bucket.rate,
        penalty=Decimal(str(penalty_text)), rate_basis=table["engine_basis"],
    )  # fmt: skip
    gross = b.built.evidence.gross_end_value
    assert gross is not None
    scen = scn._build(
        scenario_id="SCN_FD_PREMATURE@1",
        label=scn.ScenarioLabel.ILLUSTRATIVE_DOWNSIDE,
        inputs=[
            scn.Quantity("principal", ctx.amount, "INR"),
            scn.Quantity("booked_rate", booked, "fraction"),
            scn.Quantity("period_card_rate", bucket.rate, "fraction"),
            scn.Quantity("card_rate_bucket_min_days", Decimal(bucket.min_days), "days"),
            scn.Quantity("card_rate_bucket_max_days", Decimal(bucket.max_days), "days"),
            scn.Quantity("penalty", res.penalty, "fraction"),
            scn.Quantity("exit_after_days", Decimal(days), "days"),
        ],
        outputs=[
            scn.Quantity("effective_rate", res.effective_rate, "fraction"),
            scn.Quantity("premature_payout", res.payout, "INR"),
            scn.Quantity("same_tenure_at_booked_rate", res.at_booked_rate, "INR"),
            scn.Quantity("cost_of_breaking", res.cost_of_breaking, "INR"),
        ],
        base_value=gross,
        shocked_value=res.payout,
        approximate=False,
        caveats=[res.formula_id, *res.conventions, *res.warnings, "EARLIER_CASH_DATE",
                 f"CARD_RATE_TABLE_AS_OF_{table['as_of']}"],
    )  # fmt: skip
    prov = {
        "source_id": "bank.fd", "url": table["citation_url"], "retrieved_at": table["entered_at"],
        "observation_date": table["as_of"], "quality_status": "manual", "fixture": False,
    }  # fmt: skip
    prov["freshness"] = badge(prov, ctx.as_of)
    return _Applied(
        (("value", scen),),
        f"maturity proceeds on {b.maturity} vs premature payout on {exit_date}, before tax",
        (prov,),
    )


def _shock_reinvest(b: Built, value: Decimal, shocks: Mapping[str, Any], ctx: Context, env: _Env) -> _Outcome:
    reason = {
        "tbill": "A T-bill pays no coupons; cash idle between maturity and your withdrawal is conservatively assumed "
        "to earn nothing, and the scenario engine has no idle-cash reinvestment model.",
        "fd": "A cumulative FD compounds at its booked rate; there are no payouts to reinvest.",
        "mf_scheme": "A growth-option fund reinvests inside the NAV; there are no payouts to reinvest.",
        **dict.fromkeys(
            bonds.BOND_KINDS,
            "Coupons are conservatively assumed to earn nothing until your withdrawal date; no reinvestment rate is "
            "assumed, so a reinvestment scenario is not computed in this version.",
        ),
    }.get(b.kind, "Reinvestment does not apply to this instrument.")
    return _NotApplicable(reason)


def _scn_quantities(qs: Sequence[scn.Quantity]) -> list[dict[str, str]]:
    return [{"name": q.name, "value": format(q.value, "f"), "unit": q.unit} for q in qs]


def _scenario_values(
    b: Built, shock: str, which: str, res: scn.ScenarioResult, extra_prov: Sequence[Mapping[str, Any]] = ()
) -> dict[str, Any]:
    eid = f"{b.instrument_id}.scenario.{shock}.{which}"
    inputs = [f"{q.name}: {q.value} {q.unit}" for q in res.inputs]
    common: dict[str, Any] = {
        "formula_id": res.scenario_id,
        "inputs": inputs,
        "prov": b.prov,
        "extra_prov": list(extra_prov),
        "engine_version": SERVICE_VERSION,
        "assumptions": list(res.caveats),
        "limitations": ["Hypothetical shock; not a forecast and not weighted by how likely it is"],
    }
    return {
        "which": which,
        "before": explained(f"{eid}.before", f"Before shock ({which})", res.base_value, "INR",
                            what="Value without the shock.", formula="base value", substituted=format_inr(
                                res.base_value), **common),
        "after": explained(f"{eid}.after", f"After shock ({which})", res.shocked_value, "INR",
                           what=f"Value under the {res.label.value}.", formula="engine scenario",
                           substituted=format_inr(res.shocked_value), **common),
        "impact": explained(f"{eid}.impact", f"Impact ({which})", res.impact, "INR",
                            what="Shocked value minus base value (negative = loss).", formula="shocked − base",
                            substituted=f"{format_inr(res.shocked_value)} − {format_inr(res.base_value)} = "
                            f"{format_inr(res.impact)}", **common),
        "impact_fraction": explained(f"{eid}.impact_fraction", f"Impact as a share of base ({which})",
                                     res.impact_fraction, "fraction", what="Impact divided by the base value.",
                                     formula="(shocked − base) / base",
                                     substituted=f"{format_inr(res.impact)} / {format_inr(res.base_value)}", **common),
    }  # fmt: skip


def scenario(
    conn: sqlite3.Connection,
    *,
    as_of: date,
    ruleset: tx.TaxRuleSet | None,
    instrument_id: str,
    amount: Decimal | None,
    withdrawal: date | None,
    shocks: Mapping[str, Decimal | int | None],
) -> dict[str, Any]:
    given = {k: v for k, v in shocks.items() if v is not None}
    if not given:
        raise AnalysisError(422, "INVALID_INPUT", "supply at least one shock")
    rules = _require_rules(ruleset, as_of)
    ctx = resolve_context(conn, as_of=as_of, amount=amount, withdrawal=withdrawal)

    def rebuild(wd: date) -> Built:
        return build_one(conn, instrument_id, amount=ctx.amount, as_of=as_of, withdrawal=wd, ruleset=rules,
                         profile=ctx.tax_profile)  # fmt: skip

    b = rebuild(ctx.withdrawal)
    request = {
        "instrument_id": instrument_id,
        "amount": None if amount is None else str(amount),
        "withdrawal_date": None if withdrawal is None else withdrawal.isoformat(),
        "shocks": {k: (None if shocks.get(k) is None else str(shocks.get(k))) for k in SCENARIO_ORDER},
        "as_of": as_of.isoformat(),
    }
    out: dict[str, Any] = {
        "status": "OK",
        "as_of": as_of.isoformat(),
        "context": ctx.describe(),
        "request": request,
        "instrument": {"instrument_id": b.instrument_id, "name": b.name, "kind": b.kind, "category": b.category},
        "fixture": b.fixture,
        "note": "Each shock is applied on its own (not combined). Shocks are hypothetical, not forecasts, and are not "
        "weighted by how likely they are.",
        "base": None,
        "results": [],
        "disclaimer": DISCLAIMER,
    }
    if not b.evaluable:
        out["status"] = "NOT_EVALUABLE"
        out["reasons"] = list(b.not_evaluable) or list(b.built.ineligible_reasons if b.built else ())
        out["run"] = _run_block(request, out, _VERSIONS)
        return out
    assert b.built is not None
    out["base"] = {
        "net_proceeds": {w: _outcome(b, w, ctx) for w in WHICH},
        "proceeds_before_tax": {
            w: explained(
                f"{b.instrument_id}.pretax.{w}", f"Proceeds before tax ({w})", _pretax(b, w), "INR",
                what="Net proceeds plus the assumed tax: the base that shocks are applied to.",
                formula_id="PRETAX@1", formula="net + tax", substituted=format_inr(_pretax(b, w)),
                inputs=[f"net: {getattr(b.built.candidate.outcome, w)}"], prov=b.prov, engine_version=SERVICE_VERSION,
            )
            for w in WHICH
        },
    }  # fmt: skip
    env = _Env(
        inflation=_inflation(conn, as_of) if "inflation_pct" in given else ("NOT_REQUESTED", ""),
        facts=inputs.latest_fund_facts(conn, b.instrument_id, as_of) if b.kind == "mf_scheme" else None,
        card_rates=(
            inputs.latest_fd_rate_table(conn, b.institution, as_of) if b.kind == "fd" and b.institution else None
        ),
    )
    handlers: dict[str, Callable[[Built, Decimal, Mapping[str, Any], Context, _Env], _Outcome]] = {
        "rate_bp": _shock_rate,
        "spread_bp": _shock_spread,
        "equity_pct": _shock_equity,
        "inflation_pct": _shock_inflation,
        "exit_before_maturity_days": lambda bb, v, s, c, e: _shock_exit(bb, v, s, c, e, rebuild),
        "reinvestment_rate": _shock_reinvest,
    }
    for key in SCENARIO_ORDER:
        if key not in given:
            continue
        val = Decimal(given[key])
        res = handlers[key](b, val, given, ctx, env)
        entry: dict[str, Any] = {"shock": key, "input": str(given[key])}
        if isinstance(res, _NotApplicable):
            entry.update({"status": "not_applicable", "reason": res.reason, "values": None})
        else:
            first = res.results[0][1]
            entry.update(
                {
                    "status": "applied",
                    "scenario_id": first.scenario_id,
                    "label": first.label.value,
                    "measure": res.measure,
                    "approximate": first.approximate,
                    "probability_weighted": first.probability_weighted,
                    "caveats": list(first.caveats),
                    "inputs": _scn_quantities(first.inputs),
                    "outputs": {w: _scn_quantities(r.outputs) for w, r in res.results},
                    "values": [_scenario_values(b, key, w, r, res.extra_prov) for w, r in res.results],
                    "sources": [x for p in res.extra_prov for x in _sources(p)],
                }
            )
        out["results"].append(entry)
    out["run"] = _run_block(request, out, {**_VERSIONS, "scenarios": "scenarios@1"})
    return out


# ============================================================================================ simulate


def allocate_exact(amount: Decimal, weights: Sequence[Decimal]) -> list[Decimal]:
    """₹ per holding in paise that sums EXACTLY to ``amount`` (largest-remainder, ties by position)."""
    if money(amount) != amount:
        raise AnalysisError(422, "INVALID_INPUT", "amount must have at most two decimal places")
    with engine_context():
        if sum(weights, ZERO) != ONE:
            raise AnalysisError(422, "INVALID_INPUT", "weights must sum to exactly 1")
        raw = [amount * w for w in weights]
        floors = [r.quantize(PAISA, rounding=ROUND_DOWN) for r in raw]
        left = int((amount - sum(floors, ZERO)) / PAISA)
        order = sorted(range(len(raw)), key=lambda i: (-(raw[i] - floors[i]), i))
        for i in order[:left]:
            floors[i] += PAISA
    if sum(floors, ZERO) != amount:  # pragma: no cover - guaranteed by construction
        raise AnalysisError(500, "RECONCILIATION_FAILED", "allocation does not reconcile")
    return floors


def _ladder_bucket(b: Built) -> int | None:
    return b.built.candidate.days_to_cash if b.evaluable and b.built is not None else None


def simulate(
    conn: sqlite3.Connection,
    *,
    as_of: date,
    ruleset: tx.TaxRuleSet | None,
    allocations: Sequence[tuple[str, Decimal]],
    amount: Decimal | None,
    withdrawal: date | None,
) -> dict[str, Any]:
    ids = [i for i, _ in allocations]
    if not allocations or len(set(ids)) != len(ids):
        raise AnalysisError(422, "INVALID_INPUT", "allocations must name distinct instruments")
    if any(w <= 0 or w > 1 for _, w in allocations):
        raise AnalysisError(422, "INVALID_INPUT", "each weight must be in (0, 1]")
    rules = _require_rules(ruleset, as_of)
    ctx = resolve_context(conn, as_of=as_of, amount=amount, withdrawal=withdrawal)
    weights = [w for _, w in allocations]
    alloc = allocate_exact(ctx.amount, weights)
    if any(a <= 0 for a in alloc):
        raise AnalysisError(422, "INVALID_INPUT", "an allocation rounds to ₹0; raise its weight or the amount")
    built = [
        build_one(conn, iid, amount=a, as_of=as_of, withdrawal=ctx.withdrawal, ruleset=rules, profile=ctx.tax_profile)
        for iid, a in zip(ids, alloc, strict=True)
    ]
    holdings: list[dict[str, Any]] = []
    for b, w, a in zip(built, weights, alloc, strict=True):
        h: dict[str, Any] = {
            "instrument_id": b.instrument_id,
            "name": b.name,
            "kind": b.kind,
            "fixture": b.fixture,
            "weight": format(w, "f"),
            "allocation": explained(
                f"sim.{b.instrument_id}.allocation", "Allocated amount", a, "INR",
                what="Amount × weight, rounded to paise so that the allocations sum exactly to the amount.",
                formula_id="ALLOC_LARGEST_REMAINDER@1",
                formula="floor_paise(amount × w); leftover paise to the largest remainders (ties by position)",
                substituted=f"{format_inr(ctx.amount)} × {w} → {format_inr(a)}",
                inputs=[f"amount: {ctx.amount}", f"weight: {w}"], prov=ctx.user_prov("amount"),
                engine_version=SERVICE_VERSION,
            ),
            "evaluable": b.evaluable,
            "tier": b.built.candidate.tier.name if b.built else None,
            "flags": list(b.built.candidate.flags) if b.built else [],
            "eligibility_reasons": list(b.not_evaluable) + list(b.built.ineligible_reasons if b.built else ()),
            "band": None,
        }  # fmt: skip
        if b.evaluable:
            h["band"] = {wh: _outcome(b, wh, ctx, amount=a) for wh in WHICH}
        holdings.append(h)

    # ---- portfolio band: conservative sum (no correlations are invented)
    portfolio: dict[str, Any]
    if all(b.evaluable for b in built):
        sums: dict[str, Decimal] = {}
        with engine_context():
            for wh in WHICH:
                sums[wh] = sum((getattr(b.built.candidate.outcome, wh) for b in built if b.built), ZERO)
        labels = {
            "q05": ("Conservative sum, ignores diversification", "Sum of each holding's illustrative downside "
                    "scenario (q05). Treats every holding as hitting its low end together."),
            "q50": ("Sum of holding medians (not the portfolio median)", "Sum of each holding's median outcome."),
            "q95": ("Sum of holding high ends, ignores diversification", "Sum of each holding's high-end (q95) "
                    "outcome."),
        }  # fmt: skip
        portfolio = {
            "status": "OK",
            "method": "conservative sum of per-holding bands; no correlations are estimated or assumed",
            "band": {
                wh: explained(
                    f"sim.portfolio.{wh}", labels[wh][0], sums[wh], "INR", what=labels[wh][1],
                    formula_id="PORTFOLIO_BAND_SUM@1", formula=f"Σ {wh}_i",
                    substituted=" + ".join(format_inr(getattr(b.built.candidate.outcome, wh)) for b in built if b.built)
                    + f" = {format_inr(sums[wh])}",
                    inputs=[f"{b.instrument_id} {wh}: {getattr(b.built.candidate.outcome, wh)}"
                            for b in built if b.built],
                    prov=None, engine_version=SERVICE_VERSION,
                    limitations=["Ignores diversification: the sum of quantiles is not a quantile of the sum unless "
                                 "holdings move together"],
                )
                for wh in WHICH
            },
        }  # fmt: skip
    else:
        portfolio = refusal(
            "sim.portfolio", "Portfolio band", "HOLDING_NOT_EVALUABLE",
            "Not every holding could be evaluated: " + ", ".join(b.instrument_id for b in built if not b.evaluable),
        )  # fmt: skip

    conc = rm.hhi(dict(zip(ids, weights, strict=True)), snapshot_date=as_of, as_of=as_of, level="instrument")
    concentration = {
        "hhi": explained(
            "sim.hhi", "Concentration (HHI)", conc.value, "ratio",
            what="Herfindahl–Hirschman index of the allocation weights.", formula_id=conc.method_id,
            formula="HHI = Σ w_i²", substituted=" + ".join(f"{w}²" for w in weights) + f" = {conc.value}",
            inputs=[f"{i}: {w}" for i, w in zip(ids, weights, strict=True)], prov=None, engine_version=SERVICE_VERSION,
            limitations=["Instrument level only: issuer overlap inside funds is not looked through"],
        ),
        "effective_count": explained(
            "sim.hhi_effective_count", "Effective number of holdings", conc.effective_count, "ratio",
            what="1 / HHI.", formula_id=conc.method_id, formula="N_eff = 1 / HHI",
            substituted=f"1 / {conc.value}", inputs=[f"HHI: {conc.value}"], prov=None, engine_version=SERVICE_VERSION,
        ),
        "band": conc.band,
    }  # fmt: skip

    # ---- liquidity ladder (₹ by days-to-cash)
    buckets: dict[int | None, list[tuple[Built, Decimal]]] = {}
    for b, a in zip(built, alloc, strict=True):
        buckets.setdefault(_ladder_bucket(b), []).append((b, a))
    ladder: list[dict[str, Any]] = []
    running = ZERO
    for key in sorted(buckets, key=lambda k: (k is None, k or 0)):
        with engine_context():
            total = sum((a for _, a in buckets[key]), ZERO)
            running = running + total if key is not None else running
        ladder.append(
            {
                "days_to_cash": key,
                "label": "unknown (holding not evaluable)" if key is None else f"cash within {key} day(s)",
                "holdings": [x.instrument_id for x, _ in buckets[key]],
                "amount": explained(
                    f"sim.ladder.{key}", "Allocated ₹ in this bucket", total, "INR",
                    what="Sum of allocations whose days-to-cash equals this bucket.", formula_id="LADDER@1",
                    formula="Σ allocation_i for days_to_cash_i = d", substituted=format_inr(total),
                    inputs=[f"{x.instrument_id}: {a}" for x, a in buckets[key]], prov=None,
                    engine_version=SERVICE_VERSION,
                ),
                "cumulative": None if key is None else explained(
                    f"sim.ladder.{key}.cum", "Cumulative ₹ available by this day", running, "INR",
                    what="Allocations reachable within this many days.", formula_id="LADDER_CUM@1",
                    formula="running sum over buckets", substituted=format_inr(running), inputs=[], prov=None,
                    engine_version=SERVICE_VERSION,
                ),
            }
        )  # fmt: skip

    # ---- maturity vs withdrawal
    maturity: list[dict[str, Any]] = []
    for b in built:
        if b.maturity is None:
            maturity.append({"instrument_id": b.instrument_id, "maturity_date": None, "status": "no_maturity",
                             "note": "Open-ended fund: redeemed on request (days-to-cash applies)."})  # fmt: skip
            continue
        diff = (ctx.withdrawal - b.maturity).days
        status = "matures_before_withdrawal" if diff > 0 else ("matures_on_withdrawal" if diff == 0 else
                                                               "MATURITY_MISMATCH_after_withdrawal")  # fmt: skip
        maturity.append({
            "instrument_id": b.instrument_id, "maturity_date": b.maturity.isoformat(), "status": status,
            "days_between": abs(diff),
            "note": (f"Cash idle {diff} days before withdrawal (assumed to earn nothing)" if diff > 0 else
                     ("" if diff == 0 else f"Matures {-diff} days AFTER your withdrawal date: an early exit would be "
                      "needed")),
        })  # fmt: skip

    out: dict[str, Any] = {
        "status": "OK",
        "as_of": as_of.isoformat(),
        "context": ctx.describe(),
        "request": {
            "allocations": [{"instrument_id": i, "weight": str(w)} for i, w in allocations],
            "amount": None if amount is None else str(amount),
            "withdrawal_date": None if withdrawal is None else withdrawal.isoformat(),
            "as_of": as_of.isoformat(),
        },
        "holdings": holdings,
        "reconciliation": {
            "sum_of_allocations": format(sum(alloc, ZERO), "f"),
            "amount": format(ctx.amount, "f"),
            "reconciles": sum(alloc, ZERO) == ctx.amount,
        },
        "portfolio": portfolio,
        "concentration": concentration,
        "liquidity_ladder": ladder,
        "maturity": maturity,
        "dicgc": _dicgc(built, alloc, as_of),
        "fixture": any(b.fixture for b in built),
        "disclaimer": DISCLAIMER,
    }
    out["run"] = _run_block(out["request"], out, _VERSIONS)
    return out


def _dicgc(built: Sequence[Built], alloc: Sequence[Decimal], as_of: date) -> dict[str, Any]:
    deps = [(b, a) for b, a in zip(built, alloc, strict=True) if b.kind == "fd" and b.institution]
    if not deps:
        return {"applicable": False, "reason": "No bank deposits in this allocation."}
    holdings: list[DepositHolding] = []
    notes: list[str] = []
    for b, a in deps:
        assert b.institution is not None
        itype = InstitutionType.BANK if b.dicgc_eligible else InstitutionType.NBFC
        if not b.dicgc_eligible:
            notes.append(f"{b.instrument_id}: recorded as not DICGC-eligible, so treated as uninsured")
        interest = ZERO
        if b.evaluable and b.built is not None and b.built.evidence is not None:
            gev = b.built.evidence.gross_end_value
            assert gev is not None
            with engine_context():
                interest = gev - a
        else:
            notes.append(f"{b.instrument_id}: interest not included (deposit not evaluable); exposure understated")
        holdings.append(DepositHolding(b.institution, itype, "you", a, interest))
        if b.existing_same_bank > 0:
            holdings.append(DepositHolding(b.institution, itype, "you", b.existing_same_bank, ZERO))
            notes.append(f"{b.instrument_id}: includes your recorded existing deposits at {b.institution} "
                         "(may double count if entered for several deposits at this institution)")  # fmt: skip
    res = dicgc_coverage(holdings, as_of=as_of)
    return {
        "applicable": True,
        "formula_id": res.formula_id,
        "conventions": list(res.conventions),
        "warnings": list(res.warnings),
        "notes": notes,
        "groups": [
            {
                "institution": g.institution_id,
                "institution_type": g.institution_type.value,
                "flags": list(g.flags),
                **{
                    k: explained(
                        f"sim.dicgc.{g.institution_id}.{k}", f"{k.capitalize()} at {g.institution_id}", v, "INR",
                        what="DICGC cover per depositor per bank: principal + interest up to ₹5,00,000.",
                        formula_id=res.formula_id, formula="insured = min(principal + interest, limit)",
                        substituted=f"total {format_inr(g.total)}, limit {format_inr(res.limit)}",
                        inputs=[f"principal: {g.principal}", f"interest at maturity: {g.interest}"], prov=None,
                        engine_version=SERVICE_VERSION, limitations=list(res.warnings),
                    )
                    for k, v in (("total", g.total), ("insured", g.insured), ("uninsured", g.uninsured))
                },
            }
            for g in res.groups
        ],
    }  # fmt: skip


# ============================================================================================ NAV-series endpoints


@dataclass(frozen=True)
class _Series:
    instrument_id: str
    series_id: str
    name: str
    category: str
    dates: list[date]
    navs: list[Decimal]
    prov: dict[str, Any]


def _nav_series_for(conn: sqlite3.Connection, iid: str, as_of: date) -> _Series:
    inst = _instrument_row(conn, iid)
    if inst["kind"] != "mf_scheme" or not inst["amfi_code"]:
        raise AnalysisError(422, "NO_SERIES", "this analysis needs a stored NAV series (mutual fund schemes only)")
    m = conn.execute("SELECT category_raw FROM mf_schemes WHERE instrument_id=?", (iid,)).fetchone()
    dates, navs, prov = discovery._nav_series(conn, str(inst["amfi_code"]), as_of)
    if prov["conflicts"]:
        raise AnalysisError(
            409, "SOURCE_CONFLICT", f"official sources disagree on {prov['conflicts'][0]}; the series is not evaluated"
        )
    if not dates:
        raise AnalysisError(422, "NO_SERIES", "no NAV observations are stored for this scheme")
    category = (m["category_raw"] if m else "") or ""
    series_id = f"nav:{inst['amfi_code']}"
    return _Series(iid, series_id, str(inst["name"]), category, dates, navs, {**prov, "kind": "mf_scheme"})


# ---------------------------------------------------------------------------------------------- feasibility


def _feas_ex(s: _Series, key: str, label: str, value: Decimal, unit: str, what: str, rep: FeasibilityReport,
             *, formula: str = "see FEASIBILITY@1") -> dict[str, Any]:  # fmt: skip
    return explained(
        f"{s.instrument_id}.feasibility.{key}", label, value, unit, what=what, formula_id=rep.formula_id,
        formula=formula, substituted=f"{label} = {_display(value, unit)}",
        inputs=[f"{k}: {v}" for k, v in sorted(rep.inputs.items())], prov=s.prov, engine_version=SERVICE_VERSION,
        assumptions=["Month-end grid; overlapping windows"], limitations=list(rep.caveats),
    )  # fmt: skip


def feasibility(
    conn: sqlite3.Connection,
    *,
    as_of: date,
    instrument_id: str,
    target_annual: Decimal,
    horizon_years: int,
    mode: str = "CAGR",
) -> dict[str, Any]:
    s = _nav_series_for(conn, instrument_id, as_of)
    ctx = resolve_context(conn, as_of=as_of, amount=None, withdrawal=None)
    request = {"instrument_id": instrument_id, "target_annual": str(target_annual), "horizon_years": horizon_years,
               "mode": mode, "as_of": as_of.isoformat()}  # fmt: skip
    base: dict[str, Any] = {
        "as_of": as_of.isoformat(),
        "request": request,
        "instrument": {"instrument_id": s.instrument_id, "name": s.name, "category": s.category},
        "fixture": bool(s.prov.get("fixture")),
        "frequency_label": "historical frequency (overlapping windows), not a forecast",
        "disclaimer": DISCLAIMER,
    }
    meta = SeriesMeta(series_id=s.series_id, display_name=s.name, instrument_kind=InstrumentKind.FUND_NAV,
                      inception_date=s.dates[0], launch_date=None, net_of_fees=True,
                      source=str(s.prov.get("source_id")))  # fmt: skip
    req = FeasibilityRequest(target_rate=target_annual, horizon_years=horizon_years, as_of=as_of, mode=Mode(mode),
                             amount_inr=ctx.amount)  # fmt: skip
    try:
        rep = assess_feasibility([Observation(d, v) for d, v in zip(s.dates, s.navs, strict=True)], meta, req)
    except InsufficientHistory as exc:
        out = {
            **base,
            "status": "REFUSED",
            "evidence_level": EvidenceLevel.REFUSED.value,
            "low_evidence": False,
            "refusal": refusal(f"{instrument_id}.feasibility", "Return-target feasibility", exc.code, str(exc)),
        }
        out["run"] = _run_block(request, out, _VERSIONS)
        return out
    level = rep.evidence_level
    out = {
        **base,
        "status": level.value,
        "evidence_level": level.value,
        "low_evidence": level is EvidenceLevel.LOW_EVIDENCE,
        "low_evidence_note": (
            "LOW EVIDENCE: fewer than 5 independent periods — counts only, no percentages."
            if level is EvidenceLevel.LOW_EVIDENCE
            else None
        ),
        "context_amount": ctx.describe(),
        "headline": rep.headline,
        "independent_periods": rep.n_eff,
        "grid": {"start": rep.grid_start.isoformat(), "end": rep.grid_end.isoformat(), "steps": rep.n_grid_steps},
        "banners": list(rep.banners),
        "notes": list(rep.notes),
        "caveats": list(rep.caveats),
        "flags": list(rep.flags),
    }
    if level is EvidenceLevel.REFUSED or rep.counts is None:
        out["refusal"] = refusal(
            f"{instrument_id}.feasibility", "Return-target feasibility", "REFUSED",
            f"only {rep.n_eff} independent period(s); no frequencies or counts are shown",
        )  # fmt: skip
        out["run"] = _run_block(request, out, _VERSIONS)
        return out
    counts = rep.counts
    out["windows"] = counts.n_windows
    out["reached_target"] = {"count": counts.hit_count, "of": counts.n_windows,
                             "display": f"{counts.hit_count} of {counts.n_windows} overlapping windows"}  # fmt: skip
    out["loss"] = {"count": counts.loss_count, "of": counts.n_windows,
                   "display": f"{counts.loss_count} of {counts.n_windows} overlapping windows"}  # fmt: skip
    if rep.frequencies is not None:
        f = rep.frequencies
        out["reached_target"]["frequency"] = _feas_ex(s, "hit_freq", "Historical frequency of reaching the target",
                                                      f.hit_freq, "fraction", f.label, rep,
                                                      formula="hits / windows")  # fmt: skip
        out["loss"]["frequency"] = _feas_ex(s, "loss_freq", "Historical frequency of loss", f.loss_freq, "fraction",
                                            f.label, rep, formula="losses / windows")  # fmt: skip
    else:
        out["reached_target"]["frequency"] = None
        out["loss"]["frequency"] = None
    # §4.5: percentages (percentiles, quantile dots, drawdown percentiles) only with SUFFICIENT evidence; a
    # LOW_EVIDENCE result is counts only.
    sufficient = level is EvidenceLevel.SUFFICIENT
    if rep.percentiles is not None and sufficient:
        out["percentiles"] = {
            k: _feas_ex(s, f"cagr_{k}", f"{k} of window CAGR", v, "fraction", rep.percentiles.method, rep)
            for k, v in rep.percentiles.cagr.items()
        }
    pr = rep.path_risk
    if pr is not None and sufficient:
        out["drawdown"] = {
            "in_window_mdd": {k: _feas_ex(s, f"mdd_{k}", f"{k} in-window max drawdown", v, "fraction",
                                          f"Drawdown within each window ({pr.resolution} path)", rep)
                              for k, v in pr.mdd_all.items()},
            "worst_in_window_that_reached_target": None if pr.worst_mdd_in_hit_window is None else _feas_ex(
                s, "mdd_hit_worst", "Worst drawdown inside a window that reached the target",
                pr.worst_mdd_in_hit_window, "fraction", "Deepest fall inside any window that reached the target", rep),
            "median_mdd_inr": None if pr.median_mdd_all_inr is None else _feas_ex(
                s, "mdd_inr", "Median in-window low point in ₹", pr.median_mdd_all_inr, "INR",
                "Your amount at the median window's lowest point", rep),
        }  # fmt: skip
    fh = rep.full_history_drawdown
    out["full_history_drawdown"] = {
        "depth": _feas_ex(s, "full_mdd", "Full-history max drawdown", fh.depth, "fraction", fh.label, rep),
        "peak_date": fh.peak_date.isoformat(),
        "trough_date": fh.trough_date.isoformat(),
        "recovery_date": fh.recovery_date.isoformat() if fh.recovery_date else None,
        "ongoing": fh.ongoing,
    }
    if not sufficient:
        out["run"] = _run_block(request, out, {**_VERSIONS, "feasibility": rep.formula_id})
        return out
    cagrs = [w.cagr for w in rep.windows]
    dots: list[dict[str, str]] = []
    with engine_context():
        levels = [Decimal(2 * i - 1) / Decimal(2 * DOT_COUNT) for i in range(1, DOT_COUNT + 1)]
    for lv in levels:
        v = percentile_type7(cagrs, lv)
        dots.append({"level": format(lv, "f"), "value": format(v, "f"), "display": pct(v)})
    reached = sum(1 for d in dots if Decimal(d["value"]) >= target_annual)
    out["dots"] = {
        "count": DOT_COUNT,
        "method": "quantile dot plot: dot i at level (2i − 1)/40 of the window CAGRs (Hyndman–Fan type 7)",
        "values": dots,
        "reached_target": reached,
        "reached_target_display": f"{reached} of {DOT_COUNT} dots reached {pct(target_annual)} p.a.",
        "target": {"value": format(target_annual, "f"), "display": pct(target_annual)},
    }
    out["run"] = _run_block(request, out, {**_VERSIONS, "feasibility": rep.formula_id})
    return out


# ---------------------------------------------------------------------------------------------- forecast


def _f(x: float) -> Decimal:
    return from_float(x)


def forecast(conn: sqlite3.Connection, *, as_of: date, instrument_id: str, horizon_days: int | None) -> dict[str, Any]:
    s = _nav_series_for(conn, instrument_id, as_of)
    # Point-in-time: nothing observed after as_of may enter the band OR its walk-forward validation (§3.1, §3.3).
    keep = [i for i, d in enumerate(s.dates) if d <= as_of]
    if not keep:
        raise AnalysisError(422, "NO_SERIES", "no NAV observations on or before the analysis date")
    s = replace(s, dates=[s.dates[i] for i in keep], navs=[s.navs[i] for i in keep])
    ctx = resolve_context(conn, as_of=as_of, amount=None, withdrawal=None)
    hd = horizon_days if horizon_days is not None else ctx.horizon_days
    request = {"instrument_id": instrument_id, "horizon_days": hd, "as_of": as_of.isoformat()}
    last = s.dates[-1]
    steps = sum(1 for d in s.dates if last - timedelta(days=hd) < d <= last)
    prices = [float(v) for v in s.navs]  # float boundary: forecasting engine API (implementation-rules §5)
    out: dict[str, Any] = {
        "as_of": as_of.isoformat(),
        "request": request,
        "instrument": {"instrument_id": s.instrument_id, "name": s.name, "category": s.category},
        "fixture": bool(s.prov.get("fixture")),
        "label": "scenario range, not a forecast",
        "horizon": {
            "days": hd,
            "steps": steps,
            "steps_rule": "observations in the most recent window of this many calendar days",
        },
        "promotion": {
            "status": fv.PromotionVerdict.BASELINE_RETAINED.value,
            "reason": "No candidate model is configured (v1 has no ML models); the empirical baseline B1 is the "
            "published model.",
        },
        "disclaimer": DISCLAIMER,
    }
    if steps < 1:
        out["status"] = "REFUSED"
        out["refusal"] = refusal(f"{instrument_id}.forecast", "Scenario range", "INSUFFICIENT_HISTORY",
                                 "no observations inside the requested horizon window")  # fmt: skip
        out["run"] = _run_block(request, out, _VERSIONS)
        return out
    history_days = (last - s.dates[0]).days
    if history_days < cb.MIN_HISTORY_DAYS:  # validation-methodology §8: newly launched (< 1 year) → suppressed
        out["status"] = "REFUSED"
        out["refusal"] = refusal(f"{instrument_id}.forecast", "Scenario range", "INSUFFICIENT_HISTORY",
                                 f"only {history_days} days of NAV history (need ≥ {cb.MIN_HISTORY_DAYS}; a newly "
                                 "launched or un-backfilled scheme is not given a scenario range)")  # fmt: skip
        out["run"] = _run_block(request, out, _VERSIONS)
        return out
    try:
        # RT-24 (§8): gaps beyond the gate refuse the band; windows spanning a > 7-day gap are excluded.
        rng = fb.empirical_horizon_distribution(
            s.dates, prices, horizon=steps, as_of=as_of, max_gap_days=fb.MAX_GAP_DAYS
        )
    except InsufficientHistory as exc:
        out["status"] = "REFUSED"
        out["refusal"] = refusal(f"{instrument_id}.forecast", "Scenario range", exc.code, str(exc))
        out["run"] = _run_block(request, out, _VERSIONS)
        return out
    meta = rng.meta
    quantiles = []
    for lv, val in rng.quantiles:
        r = _f(val)
        with engine_context():
            inr = ctx.amount * (ONE + r)
        common: dict[str, Any] = {
            "formula_id": meta.model_id + "@" + meta.model_version,
            "prov": s.prov,
            "engine_version": SERVICE_VERSION,
            "assumptions": list(meta.assumptions),
            "limitations": list(meta.limitations),
            "inputs": [f"horizon_steps: {steps}", f"n_windows: {rng.n_windows}", f"n_eff: {rng.n_eff}",
                       f"data_cutoff: {meta.data_cutoff}"],
        }  # fmt: skip
        quantiles.append({
            "level": format(_f(lv), "f"),
            "return": explained(f"{instrument_id}.forecast.r.{lv}", f"Scenario-range return at level {lv}", r,
                                "fraction", what="Historical horizon return at this quantile (scenario range).",
                                formula="R = P(t+H)/P(t) − 1; quantile type 7", substituted=pct(r), **common),
            "value_inr": explained(f"{instrument_id}.forecast.inr.{lv}", f"Amount at level {lv} (before costs, tax)",
                                   inr, "INR", what="Your amount × (1 + R), before exit load and tax.",
                                   formula="amount × (1 + R)", substituted=f"{format_inr(ctx.amount)} × (1 + {pct(r)})",
                                   **common),
        })  # fmt: skip
    zero = fb.zero_drift_baseline(horizon_months=max(1, (hd * 12 + 182) // 365), as_of=as_of)
    carry = _yield_carry(conn, s, as_of, hd, ctx)
    validation = _walk_forward(s, prices, steps)
    warnings = list(meta.warnings)
    if nav_is_stale(last, as_of):  # validation-methodology §7: data freshness → mark stale, never silently OK
        warnings.append(f"STALE_DATA: latest NAV is dated {last.isoformat()}")
    if validation.get("passes_coverage_gate") is not True:  # §8: calibration unknown/failed → downgrade
        warnings.append(
            "CALIBRATION_NOT_ESTABLISHED: the 80 % band did not pass the held-out coverage gate "
            f"({validation.get('calibration_status', validation.get('status'))}); treat it as indicative only"
        )
    out.update(
        {
            "status": "OK",
            "context_amount": ctx.describe(),
            "scenario_range": {
                "label": "scenario range, not a forecast",
                "model_id": meta.model_id,
                "model_version": meta.model_version,
                "data_cutoff": meta.data_cutoff.isoformat(),
                "interpolation": rng.interpolation,
                "n_obs": rng.n_obs,
                "n_windows": rng.n_windows,
                "n_eff": rng.n_eff,
                "warnings": warnings,
                "quantiles": quantiles,
            },
            "baseline_comparator": {
                "model_id": zero.meta.model_id,
                "point": format(_f(zero.point), "f"),
                "label": "zero drift (random walk) point comparator",
                "assumptions": list(zero.meta.assumptions),
            },
            "assumptions": list(meta.assumptions),
            "limitations": list(meta.limitations),
            "unreliable_when": list(meta.unreliable_when),
            "validation": validation,
            "yield_carry": carry,
        }
    )
    out["run"] = _run_block(request, out, {**_VERSIONS, "validation": fv.VALIDATION_VERSION})
    return out


def _yield_carry(conn: sqlite3.Connection, s: _Series, as_of: date, hd: int, ctx: Context) -> dict[str, Any]:
    """B4 yield-carry scenarios for a debt fund (validation-methodology §2.4) from its latest factsheet facts."""
    eid = f"{s.instrument_id}.forecast.yield_carry"
    label = "Yield-carry scenario range (debt fund)"
    cat = s.category or ""
    if cb.mf_tax_class_from_category(cat) is not cb.MfTaxClass.SPECIFIED_DEBT:
        return {"status": "not_applicable", "reason": "Yield carry applies to debt-category funds only."}
    facts = inputs.latest_fund_facts(conn, s.instrument_id, as_of)
    missing = [k for k in ("ytm", "modified_duration", "expense_ratio") if facts is None or facts[k] is None]
    if facts is None or missing:
        return refusal(eid, label, "FUND_FACTS_UNAVAILABLE",
                       "needs the factsheet's portfolio YTM, modified duration and expense ratio "
                       f"(missing: {', '.join(missing)}); none is assumed")  # fmt: skip
    as_of_date = date.fromisoformat(facts["as_of_date"])
    try:
        yc = fb.yield_carry_scenarios(
            ytm=Decimal(facts["ytm"]), expense_ratio=Decimal(facts["expense_ratio"]),
            modified_duration=Decimal(facts["modified_duration"]), horizon_days=hd, as_of=as_of,
            factsheet_published=as_of_date,
        )  # fmt: skip
    except StaleData as exc:
        return refusal(eid, label, "STALE_DATA", f"factsheet as of {as_of_date}: {exc}; refresh the facts")
    except InvalidInput as exc:
        return refusal(eid, label, exc.code, str(exc))
    prov = facts["prov"]
    caveats = list(yc.meta.warnings)
    if facts["expense_ratio_kind"] == "BER":
        caveats.append("EXPENSE_IS_BER_LEVIES_NOT_INCLUDED_CARRY_OVERSTATED")
    common: dict[str, Any] = {
        "formula_id": yc.formula_id,
        "prov": s.prov,
        "extra_prov": [prov],
        "engine_version": SERVICE_VERSION,
        "assumptions": [*yc.meta.assumptions, "factsheet age measured from its as-of (portfolio) date"],
        "limitations": [*yc.meta.limitations, *caveats],
        "inputs": [f"{k}: {v}" for k, v in yc.inputs] + [f"horizon_days: {hd}", f"expense kind: "
                                                          f"{facts['expense_ratio_kind']}"],
    }  # fmt: skip

    def row(bp: int, r: Decimal, stress: bool) -> dict[str, Any]:
        with engine_context():
            inr = ctx.amount * (ONE + r)
        tag = f"{'+' if bp > 0 else ''}{bp}bp"
        return {
            "delta_yield_bp": bp,
            "stress": stress,
            "return": explained(f"{eid}.r.{tag}", f"Horizon return if yields move {tag}", r, "fraction",
                                what="Carry net of expenses minus the duration effect of an immediate, held yield "
                                "change (approximate).",
                                formula="R ≈ (YTM − ER) × days/365 − D_mod × Δy", substituted=pct(r), **common),
            "value_inr": explained(f"{eid}.inr.{tag}", f"Amount if yields move {tag} (before exit load and tax)", inr,
                                   "INR", what="Your amount × (1 + R).", formula="amount × (1 + R)",
                                   substituted=f"{format_inr(ctx.amount)} × (1 + {pct(r)})", **common),
        }  # fmt: skip

    return {
        "status": "OK",
        "label": "scenario range, not a forecast — APPROXIMATE (duration only; roll-down and credit ignored)",
        "model_id": yc.meta.model_id,
        "factsheet_as_of": facts["as_of_date"],
        "factsheet_freshness": facts["freshness"],
        "carry": explained(f"{eid}.carry", "Carry net of expenses over the horizon", yc.carry, "fraction",
                           what="Portfolio YTM minus the expense ratio, for the horizon (no yield change).",
                           formula="(YTM − ER) × days/365", substituted=pct(yc.carry), **common),
        "scenarios": [row(bp, r, False) for bp, r in yc.scenarios],
        "stress_scenarios": [row(bp, r, True) for bp, r in yc.stress_scenarios],
        "context_amount": ctx.describe(),
    }  # fmt: skip


def _walk_forward(s: _Series, prices: list[float], h: int) -> dict[str, Any]:
    """Walk-forward validation of B1 (§4): purged + embargoed expanding windows, non-overlapping origins."""
    n = len(prices)
    e = fv.default_embargo(n)
    first = fb.N_EFF_MIN * h + e  # training must hold n_eff ≥ 10 at the first origin
    # RT-24: a held-out outcome that spans a gap of more than 7 calendar days is not an H-step return → skipped.
    gap_before = [0]
    for a, b in pairwise(s.dates):
        gap_before.append(gap_before[-1] + ((b - a).days > fb.MAX_GAP_DAYS))
    origins = [
        o
        for o in range(first, n - 2 * h + 1, h)  # every test label T..T+H−1 must itself be observed
        if gap_before[o + h] == gap_before[o]
    ]
    base = {"method_id": "WALK_FORWARD_PURGED@1", "horizon_steps": h, "embargo": e, "origins": len(origins),
            "nominal_band": "80 % (levels 0.10–0.90)"}  # fmt: skip
    if not origins:
        return {**base, "status": "insufficient_evidence",
                "refusal": refusal(f"{s.instrument_id}.validation", "Walk-forward validation", "INSUFFICIENT_HISTORY",
                                   "no held-out origin has enough training history before it")}  # fmt: skip
    plan = fv.walk_forward_splits(n_obs=n, horizon=h, origins=origins, embargo=e)
    lows: list[float] = []
    highs: list[float] = []
    meds: list[float] = []
    ys: list[float] = []
    pinballs: list[float] = []
    for sp in plan:
        cut = sp.train_max + h  # last price index whose label is fully observed (= origin − embargo)
        try:
            b1 = fb.empirical_horizon_distribution(
                s.dates[: cut + 1], prices[: cut + 1], horizon=h, as_of=s.dates[cut],
                levels=FORECAST_LEVELS_VALIDATION, max_gap_days=fb.MAX_GAP_DAYS,
            )  # fmt: skip
        except InsufficientHistory:
            continue  # this origin's training data does not pass the gap gate; it is not scored
        qs = [v for _, v in b1.quantiles]
        y = prices[sp.origin + h] / prices[sp.origin] - 1.0
        lows.append(qs[0])
        meds.append(qs[1])
        highs.append(qs[2])
        ys.append(y)
        pinballs.append(fv.mean_pinball_loss(y, qs, FORECAST_LEVELS_VALIDATION))
    if len(ys) < len(origins):
        base["origins_skipped_gap_gate"] = len(origins) - len(ys)
    if not ys:
        return {**base, "status": "insufficient_evidence",
                "refusal": refusal(f"{s.instrument_id}.validation", "Walk-forward validation", "INSUFFICIENT_HISTORY",
                                   "no held-out origin has gap-free training history before it")}  # fmt: skip
    cov = fv.interval_coverage(lows, highs, ys, nominal=FORECAST_NOMINAL)
    prov = s.prov

    def ex(key: str, label: str, value: Decimal, unit: str, what: str, formula: str) -> dict[str, Any]:
        return explained(f"{s.instrument_id}.validation.{key}", label, value, unit, what=what,
                         formula_id=fv.VALIDATION_VERSION, formula=formula, substituted=_display(value, unit),
                         inputs=[f"origins: {len(origins)}", f"horizon_steps: {h}", f"embargo: {e}"], prov=prov,
                         engine_version=SERVICE_VERSION)  # fmt: skip

    return {
        **base,
        "status": plan.verdict,
        "coverage": ex("coverage", "Empirical coverage of the 80 % band", _f(cov.coverage), "fraction",
                       "Share of held-out outcomes inside the band.", "inside / n"),
        "inside": cov.inside,
        "n": cov.n,
        "calibration_status": cov.status,
        "passes_coverage_gate": cov.passes_gate,
        "kupiec_p": format(_f(cov.kupiec_p), "f"),
        "mean_pinball": ex("pinball", "Mean pinball loss (levels 0.10/0.50/0.90)", _f(sum(pinballs) / len(pinballs)),
                           "ratio", "Average quantile loss over held-out origins (lower is better).",
                           "mean_k mean_τ L_τ(y_k, q_τ,k)"),
        "mae_b1_median": ex("mae_b1", "MAE of the B1 median", _f(fv.mae(ys, meds)), "ratio",
                            "Mean absolute error of the median scenario.", "mean |y − median|"),
        "mae_b3_zero_drift": ex("mae_b3", "MAE of the zero-drift comparator", _f(fv.mae(ys, [0.0] * len(ys))),
                                "ratio", "Mean absolute error of a zero-return point forecast.", "mean |y − 0|"),
    }  # fmt: skip


# ---------------------------------------------------------------------------------------------- risk


def _asset_category(category: str) -> rm.AssetCategory:
    c = category.lower()
    if "overnight" in c:
        return rm.AssetCategory.OVERNIGHT
    if "liquid" in c:
        return rm.AssetCategory.LIQUID
    if "money market" in c:
        return rm.AssetCategory.MONEY_MARKET
    if c.startswith("debt scheme"):
        return rm.AssetCategory.DEBT
    if c.startswith("equity scheme"):
        return rm.AssetCategory.EQUITY
    if c.startswith("hybrid scheme"):
        return rm.AssetCategory.HYBRID
    return rm.AssetCategory.OTHER


def _risk_refusal(eid: str, label: str, exc: EngineError, category: rm.AssetCategory) -> dict[str, Any]:
    if isinstance(exc, InsufficientHistory):
        return refusal(eid, label, "INSUFFICIENT_HISTORY", f"insufficient history: {exc}")
    if isinstance(exc, InvalidInput) and category in rm.SMOOTHED_CATEGORIES:
        return refusal(eid, label, "REFUSED_SMOOTHED_NAV", f"refused for smoothed NAV: {exc}")
    return refusal(eid, label, exc.code, str(exc))


SHARPE_WINDOW_YEARS = 3  # risk-methodology §8: Sharpe needs 3 years of daily history; the window is exactly that


def _sharpe(
    conn: sqlite3.Connection,
    instrument_id: str,
    obs: Sequence[tuple[date, Decimal]],
    cat: rm.AssetCategory,
    nav_prov: Mapping[str, Any],
    as_of: date,
) -> dict[str, Any]:
    """§4.1 Sharpe over the trailing 3-year window, excess over the point-in-time 91-day T-bill series."""
    eid, label = f"{instrument_id}.risk.sharpe", "Sharpe ratio"
    rows = [r for r in inputs.risk_free_rows(conn) if r["observation_date"] <= as_of.isoformat()]
    if not rows:
        return refusal(eid, label, "RISK_FREE_SERIES_UNAVAILABLE",
                       "insufficient data: no 91-day T-bill cut-off yields are stored; enter them from RBI's auction "
                       "press releases. No risk-free rate is assumed")  # fmt: skip
    if not obs:
        return refusal(eid, label, "INSUFFICIENT_HISTORY", "no NAV observations")
    boundary = add_months(obs[-1][0], -12 * SHARPE_WINDOW_YEARS)
    start = max((i for i, (d, _) in enumerate(obs) if d <= boundary), default=0)
    window = list(obs[start:])
    try:
        series = ReturnSeries.from_observations(window, Frequency.DAILY_BUSINESS)
        if not series.covers_years(SHARPE_WINDOW_YEARS):
            raise InsufficientHistory(f"Sharpe needs ≥ {SHARPE_WINDOW_YEARS} years of history")
        auctions = {date.fromisoformat(r["observation_date"]): Decimal(r["value"]) for r in rows}
        try:
            al = macro.align_risk_free(series.return_dates, auctions)
        except MissingData as exc:
            return refusal(eid, label, "RISK_FREE_SERIES_INSUFFICIENT",
                           f"insufficient risk-free coverage: {exc}. No rate is filled in")  # fmt: skip
        rfs = rm.RiskFreeSeries(al.return_dates, al.effective_annual, Frequency.DAILY_BUSINESS)
        sr = rm.sharpe(series, rfs, category=cat)
    except EngineError as exc:
        return _risk_refusal(eid, label, exc, cat)
    if not sr.defined or sr.value is None:
        return refusal(eid, label, "UNDEFINED", f"Sharpe is undefined: {sr.undefined_reason}")
    last = rows[-1]
    rf_prov = {
        "source_id": last["source_id"], "url": last["source_url"], "retrieved_at": last["retrieved_at"],
        "observation_date": last["observation_date"], "quality_status": last["quality_status"],
        "fixture": last["quality_status"] == "fixture",
    }  # fmt: skip
    rf_prov["freshness"] = badge(rf_prov, as_of)
    return explained(
        eid, label, sr.value, "ratio",
        what="Annualised mean excess return over the 91-day T-bill per unit of volatility of excess returns.",
        formula_id=sr.method_id, formula="SR = mean(r − r_f) / stdev(r − r_f) × √A",
        substituted=f"{sr.mean_excess} / {sr.stdev_excess} × √{sr.annualisation_factor} = {sr.value}",
        inputs=[f"window: {series.start} → {series.end} (trailing {SHARPE_WINDOW_YEARS} years)",
                f"returns: {series.n_returns}", f"A: {sr.annualisation_factor} ({sr.annualisation_source})",
                f"mean excess per period: {sr.mean_excess}", f"stdev excess per period: {sr.stdev_excess}",
                f"mean risk-free per period: {sr.risk_free_per_period}",
                f"risk-free: 91-day T-bill cut-off, {al.auctions_used} auctions, each return date uses the latest "
                f"auction on or before it (≤ {al.max_age_days} days old)",
                "y_eff = (1 + y × 91/365)^(365/91) − 1; r_f = (1 + y_eff)^(1/A) − 1"],
        prov=dict(nav_prov), engine_version=SERVICE_VERSION, extra_prov=[rf_prov],
        assumptions=["RBI auction cut-off yields as the risk-free rate (FBIL T-bill curve is licence-blocked)"],
        limitations=list(sr.caveats),
    )  # fmt: skip


def risk(conn: sqlite3.Connection, *, as_of: date, instrument_id: str) -> dict[str, Any]:
    s = _nav_series_for(conn, instrument_id, as_of)
    ctx = resolve_context(conn, as_of=as_of, amount=None, withdrawal=None)
    cat = _asset_category(s.category)
    request = {"instrument_id": instrument_id, "as_of": as_of.isoformat()}
    obs = [(d, v) for d, v in zip(s.dates, s.navs, strict=True) if d <= as_of]
    out: dict[str, Any] = {
        "as_of": as_of.isoformat(),
        "request": request,
        "instrument": {
            "instrument_id": s.instrument_id,
            "name": s.name,
            "category": s.category,
            "risk_category": cat.value,
        },
        "fixture": bool(s.prov.get("fixture")),
        "context_amount": ctx.describe(),
        "disclaimer": DISCLAIMER,
    }
    try:
        series = ReturnSeries.from_observations(obs, Frequency.DAILY_BUSINESS)
    except EngineError as exc:
        out["status"] = "REFUSED"
        out["refusal"] = refusal(f"{instrument_id}.risk", "Risk metrics", exc.code, str(exc))
        out["run"] = _run_block(request, out, _VERSIONS)
        return out

    def ex(key: str, label: str, value: Decimal, unit: str, *, what: str, formula_id: str, formula: str,
           caveats: Sequence[str], extra_inputs: Sequence[str] = ()) -> dict[str, Any]:  # fmt: skip
        return explained(
            f"{instrument_id}.risk.{key}", label, value, unit, what=what, formula_id=formula_id, formula=formula,
            substituted=f"{label} = {_display(value, unit)}",
            inputs=[f"observations: {series.n_observations}", f"period: {series.start} → {series.end}",
                    "frequency: daily-business", *extra_inputs],
            prov=s.prov, engine_version=SERVICE_VERSION, limitations=list(caveats),
        )  # fmt: skip

    metrics: dict[str, Any] = {}
    try:
        v = rm.volatility(series, category=cat)
        metrics["volatility"] = ex("volatility", "Annualised volatility", v.value, "fraction",
                                   what="Standard deviation of daily log returns, annualised.", formula_id=v.method_id,
                                   formula="σ_ann = stdev(ln returns, ddof = 1) × √A", caveats=v.caveats,
                                   extra_inputs=[f"A: {v.annualisation_factor} ({v.annualisation_source})"],
                                   )  # fmt: skip
    except EngineError as exc:
        metrics["volatility"] = _risk_refusal(f"{instrument_id}.risk.volatility", "Annualised volatility", exc, cat)
    try:
        dd = rm.max_drawdown(series)
        metrics["max_drawdown"] = {
            **ex("mdd", "Maximum drawdown", dd.value, "fraction",
                 what="Largest peak-to-trough fall in the stored NAV history (positive magnitude).",
                 formula_id=dd.method_id, formula="max_t (1 − P_t / max_{s≤t} P_s)", caveats=dd.caveats),
            "peak_date": dd.peak_date.isoformat() if dd.peak_date else None,
            "trough_date": dd.trough_date.isoformat() if dd.trough_date else None,
            "recovery_date": dd.recovery_date.isoformat() if dd.recovery_date else None,
            "recovered": dd.recovered,
        }  # fmt: skip
    except EngineError as exc:
        metrics["max_drawdown"] = _risk_refusal(f"{instrument_id}.risk.mdd", "Maximum drawdown", exc, cat)
    for conf in VAR_CONFIDENCES:
        tag = format(conf * 100, "f").rstrip("0").rstrip(".")
        for name, fn in (("var", rm.historical_var), ("cvar", rm.historical_cvar)):
            label = f"1-day historical {'VaR' if name == 'var' else 'CVaR'} at {tag} %"
            try:
                r = fn(series, conf, horizon=1, position=ctx.amount)
                metrics[f"{name}_{tag}"] = {
                    **ex(f"{name}_{tag}", label, r.value, "fraction",
                         what="Loss exceeded on the worst share of past days (positive loss fraction).",
                         formula_id=r.method_id,
                         formula="VaR = −r_(k), k = ceil(N(1 − α))" if name == "var" else "CVaR = −mean(r_(1..k))",
                         caveats=r.caveats, extra_inputs=[f"k: {r.k}", f"windows: {r.windows}"]),
                    "value_inr": None if r.value_inr is None else ex(
                        f"{name}_{tag}_inr", f"{label} in ₹", r.value_inr, "INR",
                        what="Loss fraction × your amount.", formula_id=r.method_id, formula="position × VaR",
                        caveats=r.caveats, extra_inputs=[f"position: {ctx.amount}"]),
                }  # fmt: skip
            except EngineError as exc:
                metrics[f"{name}_{tag}"] = _risk_refusal(f"{instrument_id}.risk.{name}_{tag}", label, exc, cat)
    if cat in rm.SMOOTHED_CATEGORIES:
        metrics["sharpe"] = refusal(
            f"{instrument_id}.risk.sharpe", "Sharpe ratio", "REFUSED_SMOOTHED_NAV",
            "refused for smoothed NAV: Sharpe needs monthly returns with Lo's adjustment (risk-methodology §4.3)",
        )  # fmt: skip
    else:
        metrics["sharpe"] = _sharpe(conn, instrument_id, obs, cat, s.prov, as_of)
    out["status"] = "OK"
    out["metrics"] = metrics
    out["run"] = _run_block(request, out, _VERSIONS)
    return out
