"""Canonical serialisation and hashing — the basis of reproducible runs (system-design.md §5)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any


def _default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        if not obj.is_finite():
            raise ValueError("non-finite Decimal in canonical output")
        return format(obj, "f")
    if isinstance(obj, datetime):
        if obj.tzinfo is None:
            raise ValueError("naive datetime in canonical output")
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(obj, key=str)
    if isinstance(obj, float):  # pragma: no cover - json handles floats natively; guard is below
        return obj
    raise TypeError(f"not canonically serialisable: {type(obj).__name__}")


def canonical_json(obj: Any) -> str:
    """Sorted keys, no whitespace, Decimal as plain string, floats rejected unless finite."""
    return json.dumps(obj, default=_default, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_hex(data: str | bytes) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


def content_hash(obj: Any) -> str:
    return sha256_hex(canonical_json(obj))
