"""Pure validators for ingested observations (reliability-design §4.5, source-registry §4–§5).

Rules:
* No clock calls: freshness is evaluated against an injected, timezone-aware ``as_of``.
* Nothing is dropped silently. Validators return every observation (status lowered, note added) plus findings.
  The only collapse is an exact duplicate, which is reported as a ``DUPLICATE_IDENTICAL`` finding.
* Values are compared numerically as Decimals, so ``25.95040`` (mfapi.in padding) equals ``25.9504`` (AMFI).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from iip.data.models import IST, Freshness, Observation, QualityStatus, require_aware
from iip.data.registry import FreshnessBasis, FreshnessSLO
from iip.engine.money import engine_context

DEFAULT_JUMP_THRESHOLD = Decimal("0.20")  # reliability-design §4.5: |day-over-day NAV change| > 20 %
MIRROR_TOLERANCE = Decimal("0.0001")  # source-registry §5: abs diff > 0.0001 after normalisation ⇒ CONFLICT

_ISIN_RE = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")


# --- ISIN -----------------------------------------------------------------------------------------------------


def isin_checksum_ok(isin: str) -> bool:
    """ISO 6166 check digit: letters → two digits (A=10 … Z=35), then Luhn over the digit string."""
    digits = "".join(str(int(c, 36)) for c in isin[:-1])
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10 == int(isin[-1])


def validate_isin(isin: str) -> str | None:
    """Return ``None`` for a valid ISIN, else a reason code (``ISIN_BAD_FORMAT`` / ``ISIN_BAD_CHECKSUM``)."""
    if not isinstance(isin, str) or not isin.isascii() or not _ISIN_RE.fullmatch(isin):
        return "ISIN_BAD_FORMAT"
    if not isin_checksum_ok(isin):
        return "ISIN_BAD_CHECKSUM"
    return None


# --- results -------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Finding:
    entity_key: str
    observation_date: date
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    observations: tuple[Observation, ...]
    findings: tuple[Finding, ...]


@dataclass(frozen=True, slots=True)
class FreshnessResult:
    observation: Observation
    freshness: Freshness
    age: int  # in the SLO's unit (business or calendar days)


def _key(o: Observation) -> tuple[str, str, date]:
    return (o.source_id, o.entity_key, o.observation_date)


# --- duplicates / order / sign / unit ---------------------------------------------------------------------------


def check_duplicates(observations: Iterable[Observation]) -> ValidationResult:
    """Detect duplicate (source, entity, date) keys.

    Numerically equal duplicates collapse to the first occurrence (finding ``DUPLICATE_IDENTICAL``). Conflicting
    values keep every copy and mark all of them ``suspect`` (finding ``DUPLICATE_CONFLICT``).
    """
    items = list(observations)
    groups: dict[tuple[str, str, date], list[int]] = {}
    for i, o in enumerate(items):
        groups.setdefault(_key(o), []).append(i)
    out: list[Observation | None] = list(items)
    findings: list[Finding] = []
    for (_, entity, d), idx in groups.items():
        if len(idx) < 2:
            continue
        values = {items[i].value for i in idx}  # Decimal hashing is numeric: 25.9504 == 25.95040
        if len(values) == 1:
            for i in idx[1:]:
                out[i] = None
            findings.append(Finding(entity, d, "DUPLICATE_IDENTICAL", f"{len(idx)} identical rows collapsed"))
        else:
            for i in idx:
                out[i] = items[i].downgrade(QualityStatus.SUSPECT, "DUPLICATE_CONFLICT")
            shown = ", ".join(sorted(str(v) for v in values))
            findings.append(Finding(entity, d, "DUPLICATE_CONFLICT", f"conflicting values: {shown}"))
    return ValidationResult(tuple(o for o in out if o is not None), tuple(findings))


def check_order(observations: Iterable[Observation], *, descending: bool = False) -> ValidationResult:
    """Per entity, dates must be strictly ascending in input order (or descending, e.g. mfapi.in)."""
    last: dict[tuple[str, str], date] = {}
    out: list[Observation] = []
    findings: list[Finding] = []
    for o in observations:
        k = (o.source_id, o.entity_key)
        prev = last.get(k)
        bad = prev is not None and (o.observation_date >= prev if descending else o.observation_date <= prev)
        if bad:
            out.append(o.downgrade(QualityStatus.SUSPECT, "OUT_OF_ORDER"))
            findings.append(Finding(o.entity_key, o.observation_date, "OUT_OF_ORDER", f"after {prev}"))
        else:
            out.append(o)
            last[k] = o.observation_date
    return ValidationResult(tuple(out), tuple(findings))


def check_non_positive(observations: Iterable[Observation]) -> ValidationResult:
    out: list[Observation] = []
    findings: list[Finding] = []
    for o in observations:
        if o.value <= 0:
            out.append(o.downgrade(QualityStatus.REJECTED, "NON_POSITIVE"))
            findings.append(Finding(o.entity_key, o.observation_date, "NON_POSITIVE", str(o.value)))
        else:
            out.append(o)
    return ValidationResult(tuple(out), tuple(findings))


def check_unit_currency(
    observations: Iterable[Observation], *, expected_unit: str, expected_currency: str | None
) -> ValidationResult:
    out: list[Observation] = []
    findings: list[Finding] = []
    for o in observations:
        if o.unit != expected_unit:
            out.append(o.downgrade(QualityStatus.REJECTED, "UNIT_MISMATCH"))
            findings.append(Finding(o.entity_key, o.observation_date, "UNIT_MISMATCH", f"{o.unit} != {expected_unit}"))
        elif o.currency != expected_currency:
            out.append(o.downgrade(QualityStatus.REJECTED, "CURRENCY_MISMATCH"))
            findings.append(
                Finding(o.entity_key, o.observation_date, "CURRENCY_MISMATCH", f"{o.currency} != {expected_currency}")
            )
        else:
            out.append(o)
    return ValidationResult(tuple(out), tuple(findings))


# --- jumps ------------------------------------------------------------------------------------------------------


def check_jumps(
    observations: Iterable[Observation],
    *,
    threshold: Decimal = DEFAULT_JUMP_THRESHOLD,
    last_published: Mapping[str, Observation] | None = None,
    known_events: frozenset[tuple[str, date]] = frozenset(),
) -> ValidationResult:
    """Flag |v_t / v_{t-1} − 1| > ``threshold`` as ``suspect`` (kept, never dropped).

    The baseline is the previous non-rejected observation of the same entity in date order, seeded from
    ``last_published`` when given. ``known_events`` (entity, date) pairs (e.g. a split or merger) are exempt.
    """
    if threshold <= 0:
        raise ValueError("threshold must be positive")
    items = list(observations)
    order = sorted(range(len(items)), key=lambda i: (items[i].entity_key, items[i].observation_date))
    baseline: dict[str, Decimal] = {}
    if last_published:
        baseline = {k: v.value for k, v in last_published.items() if v.value > 0}
    out = list(items)
    findings: list[Finding] = []
    for i in order:
        o = items[i]
        if o.quality_status is QualityStatus.REJECTED or o.value <= 0:
            continue
        prev = baseline.get(o.entity_key)
        if prev is not None and (o.entity_key, o.observation_date) not in known_events:
            with engine_context():
                change = abs(o.value / prev - 1)
            if change > threshold:
                out[i] = o.downgrade(QualityStatus.SUSPECT, "JUMP_ABOVE_THRESHOLD")
                findings.append(
                    Finding(o.entity_key, o.observation_date, "JUMP_ABOVE_THRESHOLD", f"{prev} -> {o.value}")
                )
        baseline[o.entity_key] = o.value
    return ValidationResult(tuple(out), tuple(findings))


# --- freshness ---------------------------------------------------------------------------------------------------


def ist_date(moment: datetime) -> date:
    require_aware("as_of", moment)
    return moment.astimezone(IST).date()


def business_days_between(start: date, end: date, *, holidays: frozenset[date] = frozenset()) -> int:
    """Number of business days in (start, end]. Weekends and ``holidays`` are skipped. Negative if end < start."""
    if end < start:
        return -business_days_between(end, start, holidays=holidays)
    count = 0
    d = start
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in holidays:
            count += 1
    return count


def classify_freshness(
    observation: Observation,
    slo: FreshnessSLO,
    *,
    as_of: datetime,
    holidays: frozenset[date] | None = None,
) -> FreshnessResult:
    """Classify against ``slo`` relative to the injected ``as_of``. Stale/expired rows are marked ``stale``.

    ``holidays=None`` means no curated calendar is available: weekdays-only, with a ``CALENDAR_UNVERIFIED`` note.
    A future-dated observation is ``suspect``. Ages use IST calendar dates.
    """
    today = ist_date(as_of)
    o = observation
    if slo.basis is FreshnessBasis.CUSTOM:
        raise ValueError(f"custom SLO cannot be evaluated generically: {slo.description}")
    if o.observation_date > today:
        o = o.downgrade(QualityStatus.SUSPECT, "FUTURE_DATE")
        return FreshnessResult(o, Freshness.EXPIRED, -1)

    calendar_age = (today - o.observation_date).days
    if slo.basis is FreshnessBasis.OBSERVATION_BUSINESS_DAYS:
        if holidays is None:
            o = o.add_note("CALENDAR_UNVERIFIED")
        age = business_days_between(o.observation_date, today, holidays=holidays or frozenset())
    elif slo.basis is FreshnessBasis.OBSERVATION_CALENDAR_DAYS:
        age = calendar_age
    else:  # RETRIEVAL_CALENDAR_DAYS
        age = (today - ist_date(o.retrieved_at)).days
        calendar_age = age

    if age <= slo.fresh_max and not (slo.calendar_cap_days is not None and calendar_age > slo.calendar_cap_days):
        freshness = Freshness.FRESH
    elif age <= slo.stale_max and not (slo.calendar_cap_days is not None and calendar_age > slo.calendar_cap_days):
        freshness = Freshness.STALE
        o = o.downgrade(QualityStatus.STALE, "STALE")
    else:
        freshness = Freshness.EXPIRED
        o = o.downgrade(QualityStatus.STALE, "EXPIRED")
    if slo.dormant_after_days is not None and (today - o.observation_date).days > slo.dormant_after_days:
        o = o.add_note("DORMANT")
    return FreshnessResult(o, freshness, age)


# --- mirror cross-check ------------------------------------------------------------------------------------------


def cross_check_mirror(
    official: Observation, mirror: Observation, *, tolerance: Decimal = MIRROR_TOLERANCE
) -> Observation:
    """Compare an UNOFFICIAL mirror value to the official one for the same entity and date.

    Values are compared as Decimals, so mfapi.in's right-padding to 5 dp is not a difference. The official
    observation is never modified ("AMFI wins"); the mirror copy is returned noted ``UNOFFICIAL_MIRROR`` and, if
    the difference exceeds ``tolerance``, ``suspect`` with ``CONFLICT``.
    """
    if (official.entity_key, official.observation_date) != (mirror.entity_key, mirror.observation_date):
        raise ValueError("cross-check requires the same entity and observation date")
    checked = mirror.add_note("UNOFFICIAL_MIRROR")
    if abs(official.value - mirror.value) > tolerance:
        checked = checked.downgrade(QualityStatus.SUSPECT, "CONFLICT")
    return checked


def run_all(
    observations: Sequence[Observation],
    *,
    expected_unit: str,
    expected_currency: str | None,
    descending: bool = False,
    threshold: Decimal = DEFAULT_JUMP_THRESHOLD,
    last_published: Mapping[str, Observation] | None = None,
) -> ValidationResult:
    """Convenience pipeline: unit/currency → sign → duplicates → order → jumps. Findings are concatenated."""
    findings: list[Finding] = []
    current: Sequence[Observation] = observations
    for step in (
        lambda xs: check_unit_currency(xs, expected_unit=expected_unit, expected_currency=expected_currency),
        check_non_positive,
        check_duplicates,
        lambda xs: check_order(xs, descending=descending),
        lambda xs: check_jumps(xs, threshold=threshold, last_published=last_published),
    ):
        result = step(current)
        current = result.observations
        findings.extend(result.findings)
    return ValidationResult(tuple(current), tuple(findings))
