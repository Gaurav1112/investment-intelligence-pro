"""Data-layer value types and the provenance contract (ADR-0004, source-registry.md §3).

* ``Observation`` is one value at one date with full provenance. ``value`` is a ``Decimal`` parsed from the source
  string — never a float — and keeps the published precision (``Decimal("21.455")`` stays 3 dp).
* ``RawPayload`` is what the fetcher hands to a parser: bytes plus their SHA-256, the final URL and ``retrieved_at``.
* Parsers return a ``ParseResult``: records, observations and an ``IngestionReport`` with per-row rejection reasons.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum

IST = timezone(timedelta(hours=5, minutes=30), "IST")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class DataError(Exception):
    """Base class for data-layer errors. ``code`` is a stable machine-readable identifier."""

    code = "DATA_ERROR"


class SchemaChanged(DataError):
    """The payload does not match the exact expected layout. Fail closed: nothing from it may be staged."""

    code = "SCHEMA_CHANGED"


class FetchRefused(DataError):
    """A fetch was refused by policy (SSRF controls, disabled source). Never retried."""

    code = "FETCH_REFUSED"


class QualityStatus(StrEnum):
    OK = "ok"
    STALE = "stale"
    SUSPECT = "suspect"
    REJECTED = "rejected"
    FIXTURE = "fixture"
    MANUAL = "manual"


class Freshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"


# Higher rank wins when a validator downgrades an observation. FIXTURE is sticky (see Observation.downgrade).
_RANK = {
    QualityStatus.OK: 0,
    QualityStatus.MANUAL: 0,
    QualityStatus.FIXTURE: 0,
    QualityStatus.STALE: 1,
    QualityStatus.SUSPECT: 2,
    QualityStatus.REJECTED: 3,
}


def require_utc(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware (UTC)")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be in UTC, got offset {value.utcoffset()}")


def require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class RawPayload:
    """Raw bytes as received, with integrity hash and retrieval metadata."""

    source_id: str
    final_url: str
    retrieved_at: datetime
    content: bytes
    sha256: str
    content_type: str | None = None
    last_modified: datetime | None = None

    def __post_init__(self) -> None:
        require_utc("retrieved_at", self.retrieved_at)
        if self.last_modified is not None:
            require_aware("last_modified", self.last_modified)
        if not isinstance(self.content, bytes):
            raise TypeError("content must be bytes")
        if self.sha256 != sha256_hex(self.content):
            raise ValueError("sha256 does not match content")

    @classmethod
    def from_bytes(
        cls,
        *,
        source_id: str,
        final_url: str,
        retrieved_at: datetime,
        content: bytes,
        content_type: str | None = None,
        last_modified: datetime | None = None,
    ) -> RawPayload:
        return cls(
            source_id=source_id,
            final_url=final_url,
            retrieved_at=retrieved_at,
            content=content,
            sha256=sha256_hex(content),
            content_type=content_type,
            last_modified=last_modified,
        )


@dataclass(frozen=True, slots=True)
class Observation:
    """A single value at a single date, carrying the full provenance contract."""

    source_id: str
    source_url: str
    retrieved_at: datetime
    observation_date: date
    publication_time: datetime | None
    entity_key: str
    value: Decimal
    unit: str
    currency: str | None
    quality_status: QualityStatus
    convention: str
    raw_sha256: str
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_id or not self.source_url or not self.entity_key:
            raise ValueError("source_id, source_url and entity_key are required")
        require_utc("retrieved_at", self.retrieved_at)
        if self.publication_time is not None:
            require_aware("publication_time", self.publication_time)
        if isinstance(self.observation_date, datetime) or not isinstance(self.observation_date, date):
            raise TypeError("observation_date must be a date")
        if type(self.value) is not Decimal:
            raise TypeError(f"value must be Decimal, got {type(self.value).__name__}")
        if not self.value.is_finite():
            raise ValueError(f"value must be finite, got {self.value}")
        if not self.unit or not self.convention:
            raise ValueError("unit and convention are required")
        if not isinstance(self.quality_status, QualityStatus):
            raise TypeError("quality_status must be a QualityStatus")
        if not _SHA256_RE.fullmatch(self.raw_sha256):
            raise ValueError("raw_sha256 must be 64 lower-case hex characters")

    def downgrade(self, status: QualityStatus, note: str) -> Observation:
        """Return a copy with ``note`` added and the status lowered to ``status`` if that is worse.

        Statuses never improve. ``FIXTURE`` is sticky except against ``REJECTED``: a fixture must never lose its
        badge and be mistaken for (stale or suspect) market data; the finding is still recorded in ``notes``.
        """
        notes = self.notes if note in self.notes else (*self.notes, note)
        new_status = self.quality_status
        if self.quality_status is QualityStatus.FIXTURE:
            if status is QualityStatus.REJECTED:
                new_status = status
        elif _RANK[status] > _RANK[self.quality_status]:
            new_status = status
        return replace(self, quality_status=new_status, notes=notes)

    def add_note(self, note: str) -> Observation:
        if note in self.notes:
            return self
        return replace(self, notes=(*self.notes, note))


@dataclass(frozen=True, slots=True)
class SchemeRecord:
    """Scheme metadata as published (NAVAll context lines, NAV history, or the scheme master)."""

    scheme_code: int
    scheme_name: str
    amc: str | None = None
    scheme_type: str | None = None
    category: str | None = None
    plan: str | None = None
    option: str | None = None
    isin_growth: str | None = None
    isin_reinvest: str | None = None
    nav_name: str | None = None
    launch_date: date | None = None
    closure_date: date | None = None
    min_amount_text: str | None = None
    flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RowRejection:
    """A rejected row. The raw line itself is not kept (it is in the raw archive); only its hash."""

    line_no: int
    reason: str
    detail: str
    line_sha256: str


@dataclass(frozen=True, slots=True)
class IngestionReport:
    source_id: str
    raw_sha256: str
    rows_seen: int
    rows_ok: int
    rows_rejected: int
    rejections: tuple[RowRejection, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.rows_seen != self.rows_ok + self.rows_rejected:
            raise ValueError("rows_seen must equal rows_ok + rows_rejected")
        if len(self.rejections) != self.rows_rejected:
            raise ValueError("one RowRejection per rejected row is required")


@dataclass(frozen=True, slots=True)
class ParseResult:
    records: tuple[SchemeRecord, ...]
    observations: tuple[Observation, ...]
    report: IngestionReport
