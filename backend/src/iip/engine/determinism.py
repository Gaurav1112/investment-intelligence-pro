"""Canonical serialisation and hashing — the basis of reproducible runs (system-design.md §5).

Value-canonicalisation policy (``CANONICAL_VERSION``, red-team RT-26):

* **Decimal: exact digits, including trailing zeros.** ``25.9504`` and ``25.95040`` hash differently on purpose. A
  published value's precision is provenance (AMFI publishes 4 decimals, a re-key with 5 is a different record), and
  engine-computed Decimals are produced by one deterministic engine under a fixed context, so identical inputs always
  give identical exponents — normalising would buy no reproducibility and would erase provenance for source values
  that share the type. Callers that want value-equality must quantize before hashing (e.g. ``money()``).
* **Signed zero → zero.** ``-0`` / ``-0.00`` carries no information and is written as ``0`` / ``0.00`` (exponent kept).
* **Datetimes → UTC.** Aware datetimes are converted to UTC before serialising, so the same instant written at
  +05:30 and at UTC hashes identically. Naive datetimes are rejected (ambiguous instant).
* **Floats are rejected** anywhere in the object (``ValueError``) — binary floats have no canonical decimal form at
  the precision that matters here; convert through ``iip.engine.money.from_float`` first. Non-finite Decimals too.
* Dict keys sorted; no whitespace; dataclasses as dicts; enums as values; sets sorted by ``str``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

CANONICAL_VERSION = "canonical_json@2"  # @2 (RT-26): −0 → 0, datetimes → UTC, floats rejected


def _decimal(d: Decimal) -> str:
    if not d.is_finite():
        raise ValueError("non-finite Decimal in canonical output")
    if d.is_zero() and d.is_signed():
        d = d.copy_abs()
    return format(d, "f")


def _canon(obj: Any) -> Any:
    """Convert to JSON-native types under the policy above (no floats survive)."""
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        raise ValueError(f"float {obj!r} in canonical output: use Decimal (money.from_float) instead")
    if isinstance(obj, Decimal):
        return _decimal(obj)
    if isinstance(obj, datetime):
        if obj.tzinfo is None or obj.tzinfo.utcoffset(obj) is None:
            raise ValueError("naive datetime in canonical output")
        return obj.astimezone(UTC).isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return _canon(obj.value)
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _canon(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for k, v in obj.items():
            key = _canon(k) if isinstance(k, (Decimal, date, Enum)) else k
            if isinstance(key, float):
                raise ValueError("float dict key in canonical output")
            out[key] = _canon(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [_canon(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return [_canon(v) for v in sorted(obj, key=str)]
    raise TypeError(f"not canonically serialisable: {type(obj).__name__}")


def canonical_json(obj: Any) -> str:
    """Sorted keys, no whitespace, Decimal as its exact plain string, datetimes in UTC, floats rejected."""
    return json.dumps(_canon(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_hex(data: str | bytes) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


def content_hash(obj: Any) -> str:
    return sha256_hex(canonical_json(obj))
