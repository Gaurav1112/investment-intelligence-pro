"""Shared helpers for data-layer tests. No network: every HTTP test uses httpx.MockTransport."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from iip.data.models import QualityStatus, RawPayload

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "data"
_SEPARATOR = b"# ---\n"

# Retrieval times of the probes the fixtures were cut from (see each fixture's header comment).
NAVALL_RETRIEVED = datetime(2026, 10, 15, 5, 34, 19, tzinfo=UTC)
NAVHISTORY_RETRIEVED = datetime(2026, 10, 15, 5, 34, 48, tzinfo=UTC)
SCHEMEDATA_RETRIEVED = datetime(2026, 10, 15, 5, 43, 36, tzinfo=UTC)
NAVALL_LAST_MODIFIED = datetime(2026, 10, 15, 5, 5, 3, tzinfo=UTC)  # HTTP last-modified in the probe notes

NAVALL_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"
NAVHISTORY_URL = (
    "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx?mf=9&tp=1&frmdt=13-Oct-2026&todt=14-Oct-2026"
)
SCHEMEDATA_URL = "https://portal.amfiindia.com/DownloadSchemeData_Po.aspx?mf=0"


def load_fixture(name: str) -> bytes:
    """Return the verbatim probe bytes below the fixture's '# ---' comment header."""
    raw = (FIXTURES / name).read_bytes()
    head, sep, body = raw.partition(_SEPARATOR)
    assert sep, f"fixture {name} has no '# ---' header terminator"
    assert all(line.startswith(b"#") for line in head.splitlines()), "header lines must be comments"
    return body


def make_payload(
    source_id: str,
    content: bytes,
    url: str,
    retrieved_at: datetime,
    last_modified: datetime | None = None,
    content_type: str = "text/plain",
) -> RawPayload:
    return RawPayload.from_bytes(
        source_id=source_id,
        final_url=url,
        retrieved_at=retrieved_at,
        content=content,
        content_type=content_type,
        last_modified=last_modified,
    )


@pytest.fixture
def navall_bytes() -> bytes:
    return load_fixture("amfi_navall_excerpt.txt")


@pytest.fixture
def navhistory_bytes() -> bytes:
    return load_fixture("amfi_navhistory_excerpt.txt")


@pytest.fixture
def schemedata_bytes() -> bytes:
    return load_fixture("amfi_schemedata_excerpt.csv")


FIXTURE_Q = QualityStatus.FIXTURE
