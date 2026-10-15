"""Code-defined source registry (docs/data/source-registry.md §1, §4; ADR-0004; threat-model C-08).

* Sources and their hosts are defined **in code**. Adding a host is a reviewed code change.
* No API, DB row or config value supplies a URL. Callers obtain a ``SourceRequest`` only through the typed builders
  below (``navall_request`` …), whose parameters are dates and integers.
* ``SourceRequest`` re-validates its URL on construction (https, port 443, exact host allowlist for that source).
* mfapi.in is registered but DISABLED. NSE, BSE and yfinance are deliberately absent; FBIL is absent (licence).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from types import MappingProxyType
from urllib.parse import urlsplit

from iip.data.models import FetchRefused

ADAPTER_VERSION = "0.1.0"
MAX_HISTORY_WINDOW_DAYS = 90
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
MiB = 1024 * 1024


class SourceMode(StrEnum):
    LIVE = "live"
    MANUAL = "manual"
    DISABLED = "disabled"


class LicenceClass(StrEnum):
    PERSONAL_USE_ONLY = "PERSONAL_USE_ONLY"
    PUBLIC_GOVT = "PUBLIC_GOVT"
    LICENSED = "LICENSED"
    UNKNOWN = "UNKNOWN"


class FreshnessBasis(StrEnum):
    OBSERVATION_BUSINESS_DAYS = "observation_date_business_days"
    OBSERVATION_CALENDAR_DAYS = "observation_date_calendar_days"
    RETRIEVAL_CALENDAR_DAYS = "retrieved_at_calendar_days"
    CUSTOM = "custom"  # month/quarter/event based; not evaluable by validators.classify_freshness


@dataclass(frozen=True, slots=True)
class FreshnessSLO:
    """FRESH while age ≤ ``fresh_max``; STALE while ≤ ``stale_max``; EXPIRED beyond (source-registry.md §4)."""

    basis: FreshnessBasis
    fresh_max: int
    stale_max: int
    calendar_cap_days: int | None = None  # EXPIRED if calendar age exceeds this, whatever the business-day age
    dormant_after_days: int | None = None  # observation older than this (calendar days) ⇒ DORMANT note
    description: str = ""

    def __post_init__(self) -> None:
        if self.basis is not FreshnessBasis.CUSTOM and not 0 <= self.fresh_max <= self.stale_max:
            raise ValueError("require 0 <= fresh_max <= stale_max")


def _custom(text: str) -> FreshnessSLO:
    return FreshnessSLO(FreshnessBasis.CUSTOM, 0, 0, description=text)


@dataclass(frozen=True, slots=True)
class SourceSpec:
    id: str
    name: str
    owner: str
    official: bool
    mode: SourceMode
    allowed_hosts: frozenset[str]
    terms_url: str | None
    licence_class: LicenceClass
    licence_note: str
    freshness: FreshnessSLO
    max_bytes: int = 0
    content_types: frozenset[str] = frozenset()
    unit: str | None = None
    currency: str | None = None
    convention: str | None = None
    requires_configuration: bool = False


_NAV_SLO = FreshnessSLO(
    FreshnessBasis.OBSERVATION_BUSINESS_DAYS,
    fresh_max=1,
    stale_max=3,
    calendar_cap_days=5,
    dormant_after_days=30,
    description="NAV for T by 23:00 IST on T; stale 2-3 business days; expired > 3 business days or > 5 calendar days",
)
_AMFI_TERMS = "https://www.amfiindia.com/terms-of-use"
_AMFI_LICENCE = (
    "AMFI ToU: personal, non-commercial use only; do not store a significant portion; no redistribution. "
    "Keep only held/watched schemes; any hosted/commercial use needs written permission."
)

_SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(
        id="amfi.navall",
        name="AMFI NAVAll.txt (latest NAV, all schemes)",
        owner="AMFI",
        official=True,
        mode=SourceMode.LIVE,
        # www redirects (302) to portal; exactly these two hosts.
        allowed_hosts=frozenset({"www.amfiindia.com", "portal.amfiindia.com"}),
        terms_url=_AMFI_TERMS,
        licence_class=LicenceClass.PERSONAL_USE_ONLY,
        licence_note=_AMFI_LICENCE,
        freshness=_NAV_SLO,
        max_bytes=32 * MiB,
        content_types=frozenset({"text/plain"}),
        unit="INR_per_unit",
        currency="INR",
        convention="NAV_PER_UNIT_AS_PUBLISHED",
    ),
    SourceSpec(
        id="amfi.navhistory",
        name="AMFI NAV history report",
        owner="AMFI",
        official=True,
        mode=SourceMode.LIVE,
        allowed_hosts=frozenset({"portal.amfiindia.com"}),
        terms_url=_AMFI_TERMS,
        licence_class=LicenceClass.PERSONAL_USE_ONLY,
        licence_note=_AMFI_LICENCE + " History only for held, watched or shortlisted schemes; windows <= 90 days.",
        freshness=_NAV_SLO,
        max_bytes=32 * MiB,
        content_types=frozenset({"text/plain"}),
        unit="INR_per_unit",
        currency="INR",
        convention="NAV_PER_UNIT_AS_PUBLISHED",
    ),
    SourceSpec(
        id="amfi.schememaster",
        name="AMFI scheme master CSV",
        owner="AMFI",
        official=True,
        mode=SourceMode.LIVE,
        allowed_hosts=frozenset({"portal.amfiindia.com"}),
        terms_url=_AMFI_TERMS,
        licence_class=LicenceClass.PERSONAL_USE_ONLY,
        licence_note=_AMFI_LICENCE,
        freshness=FreshnessSLO(FreshnessBasis.RETRIEVAL_CALENDAR_DAYS, fresh_max=7, stale_max=30),
        max_bytes=32 * MiB,
        content_types=frozenset({"text/csv"}),
    ),
    SourceSpec(
        id="mospi.cpi",
        name="MoSPI CPI API",
        owner="MoSPI / NSO",
        official=True,
        mode=SourceMode.LIVE,
        allowed_hosts=frozenset({"api.mospi.gov.in"}),
        terms_url=None,
        licence_class=LicenceClass.PUBLIC_GOVT,
        licence_note="No data-licence text found (NOT VERIFIED); personal use with citation. Base 2012 and 2024 "
        "series are stored separately and never spliced.",
        freshness=_custom("Monthly, 12th at 16:00 IST; latest month M-1 after the 12th, else M-2"),
        max_bytes=8 * MiB,
        content_types=frozenset({"application/json", "text/csv"}),
        unit="index_points",
        requires_configuration=True,
    ),
    SourceSpec(
        id="mfapi.in",
        name="mfapi.in (UNOFFICIAL mirror of AMFI)",
        owner="Independent operator",
        official=False,
        mode=SourceMode.DISABLED,
        allowed_hosts=frozenset({"api.mfapi.in"}),
        terms_url=None,
        licence_class=LicenceClass.UNKNOWN,
        licence_note="No terms page found; AMFI ToU applies downstream. Cross-check only; never the sole source.",
        freshness=_NAV_SLO,
        max_bytes=8 * MiB,
        content_types=frozenset({"application/json"}),
        unit="INR_per_unit",
        currency="INR",
        convention="NAV_PER_UNIT_MIRROR_5DP",
    ),
    # --- manual / curated sources: no hosts, never fetched -------------------------------------------------
    SourceSpec(
        id="amfi.ter",
        name="AMFI TER of MF schemes",
        owner="AMFI",
        official=True,
        mode=SourceMode.MANUAL,
        allowed_hosts=frozenset(),
        terms_url=_AMFI_TERMS,
        licence_class=LicenceClass.PERSONAL_USE_ONLY,
        licence_note=_AMFI_LICENCE,
        freshness=_custom("Current or previous month fresh; 2 months stale; > 3 months expired"),
        unit="percent_pa",
    ),
    SourceSpec(
        id="amfi.riskometer",
        name="Riskometer / PRC disclosures",
        owner="AMFI + each AMC",
        official=True,
        mode=SourceMode.MANUAL,
        allowed_hosts=frozenset(),
        terms_url=_AMFI_TERMS,
        licence_class=LicenceClass.PERSONAL_USE_ONLY,
        licence_note=_AMFI_LICENCE,
        freshness=FreshnessSLO(FreshnessBasis.OBSERVATION_CALENDAR_DAYS, fresh_max=45, stale_max=75),
    ),
    SourceSpec(
        id="rbi.home.rates",
        name="RBI home page current rates (policy rates)",
        owner="RBI",
        official=True,
        mode=SourceMode.MANUAL,
        allowed_hosts=frozenset(),
        terms_url="https://www.rbi.org.in/Scripts/Disclaimer.aspx",
        licence_class=LicenceClass.PUBLIC_GOVT,
        licence_note="RBI disclaimer prohibits caching/framing; WAF blocks scripts (HTTP 418). Manual entry only.",
        freshness=_custom("Verified after the last MPC date; expired > 70 days since verification"),
        unit="percent_pa",
    ),
    SourceSpec(
        id="rbi.pr.tbill",
        name="RBI T-bill auction result press releases",
        owner="RBI",
        official=True,
        mode=SourceMode.MANUAL,  # user-triggered single fetch is not implemented in v1 (manual entry)
        allowed_hosts=frozenset(),
        terms_url="https://www.rbi.org.in/Scripts/Disclaimer.aspx",
        licence_class=LicenceClass.PUBLIC_GOVT,
        licence_note="Store only extracted figures plus citation, never the HTML.",
        freshness=FreshnessSLO(FreshnessBasis.OBSERVATION_CALENDAR_DAYS, fresh_max=7, stale_max=21),
        unit="percent_pa",
        convention="RBI_TBILL_IMPLICIT_YIELD_AS_PUBLISHED",
    ),
    SourceSpec(
        id="rbi.dbie",
        name="RBI Database on Indian Economy",
        owner="RBI",
        official=True,
        mode=SourceMode.MANUAL,
        allowed_hosts=frozenset(),
        terms_url=None,
        licence_class=LicenceClass.PUBLIC_GOVT,
        licence_note="No documented API; manual downloads only; third-party mirrors not allowed.",
        freshness=_custom("Series-dependent"),
    ),
    SourceSpec(
        id="rbi.wadtdr",
        name="RBI weighted average domestic term deposit rate",
        owner="RBI",
        official=True,
        mode=SourceMode.MANUAL,
        allowed_hosts=frozenset(),
        terms_url="https://www.rbi.org.in/Scripts/Disclaimer.aspx",
        licence_class=LicenceClass.PUBLIC_GOVT,
        licence_note="Manual reference series with citation.",
        freshness=_custom("<= 2 months fresh; 3 months stale; > 4 months expired"),
        unit="percent_pa",
    ),
    SourceSpec(
        id="ccil.marketwatch",
        name="CCIL NDS-OM Market Watch (manual citation only)",
        owner="CCIL",
        official=True,
        mode=SourceMode.MANUAL,
        allowed_hosts=frozenset(),
        terms_url=None,
        licence_class=LicenceClass.PERSONAL_USE_ONLY,
        licence_note="Data Sharing Policy: non-commercial use; extraction discouraged. "
        "User enters values with citation.",
        freshness=_custom("Per entry"),
    ),
    SourceSpec(
        id="bond.quote",
        name="Bond price/yield (user-entered with citation)",
        owner="User (from RBI Retail Direct / exchange / CCIL pages)",
        official=False,  # the app cannot verify that the cited page is an official one
        mode=SourceMode.MANUAL,
        allowed_hosts=frozenset(),
        terms_url=None,
        licence_class=LicenceClass.PERSONAL_USE_ONLY,
        licence_note="NSE/BSE/CCIL/FBIL terms restrict automated use; user enters the quote, page URL and date.",
        freshness=_custom("<= 7 calendar days, else STALE_DATA (bond excluded)"),
    ),
    SourceSpec(
        id="cra.ratings",
        name="Credit rating agency rating actions",
        owner="CRISIL / ICRA / CARE / India Ratings",
        official=True,
        mode=SourceMode.MANUAL,
        allowed_hosts=frozenset(),
        terms_url="https://www.crisilratings.com/en/home/website-terms-of-use.html",
        licence_class=LicenceClass.UNKNOWN,
        licence_note="No scraping; user enters rating, agency, action date and rationale URL.",
        freshness=_custom("Per rating action"),
    ),
    SourceSpec(
        id="dicgc",
        name="DICGC deposit insurance limit",
        owner="DICGC",
        official=True,
        mode=SourceMode.MANUAL,
        allowed_hosts=frozenset(),
        terms_url=None,
        licence_class=LicenceClass.PUBLIC_GOVT,
        licence_note="Curated constant with citation.",
        freshness=FreshnessSLO(FreshnessBasis.RETRIEVAL_CALENDAR_DAYS, fresh_max=180, stale_max=365),
        unit="INR",
        currency="INR",
    ),
    SourceSpec(
        id="bank.fd",
        name="Bank FD terms (user-entered)",
        owner="Each bank",
        official=True,
        mode=SourceMode.MANUAL,
        allowed_hosts=frozenset(),
        terms_url=None,
        licence_class=LicenceClass.UNKNOWN,
        licence_note="User enters own FD terms; aggregator sites are not used.",
        freshness=_custom("Per deposit"),
        unit="percent_pa",
    ),
    SourceSpec(
        id="mof.smallsavings",
        name="Small-savings rates (DEA OM / DoP SB Order)",
        owner="MoF DEA",
        official=True,
        mode=SourceMode.MANUAL,
        allowed_hosts=frozenset(),
        terms_url=None,
        licence_class=LicenceClass.PUBLIC_GOVT,
        licence_note="Curated table with OM citation; scanned PDFs are never auto-parsed.",
        freshness=_custom("Fresh while valid_to >= today; expired once the quarter rolls over"),
        unit="percent_pa",
    ),
    SourceSpec(
        id="itd.tax",
        name="Income-tax rule sets",
        owner="CBDT",
        official=True,
        mode=SourceMode.MANUAL,
        allowed_hosts=frozenset(),
        terms_url=None,
        licence_class=LicenceClass.PUBLIC_GOVT,
        licence_note="Curated, versioned rule set with section citations.",
        freshness=_custom("A rule set must exist for the current tax year"),
    ),
    SourceSpec(
        id="sebi.regs",
        name="SEBI regulations and circulars",
        owner="SEBI",
        official=True,
        mode=SourceMode.MANUAL,
        allowed_hosts=frozenset(),
        terms_url=None,
        licence_class=LicenceClass.PUBLIC_GOVT,
        licence_note="Citations only; documents are not mirrored.",
        freshness=_custom("Ad hoc"),
    ),
    SourceSpec(
        id="calendar.trading",
        name="Trading and holiday calendars (curated)",
        owner="NSE / RBI",
        official=True,
        mode=SourceMode.MANUAL,
        allowed_hosts=frozenset(),
        terms_url=None,
        licence_class=LicenceClass.PUBLIC_GOVT,
        licence_note="Entered by hand from official circulars; NSE JSON is never automated.",
        freshness=_custom("Current calendar year curated"),
    ),
)

REGISTRY: MappingProxyType[str, SourceSpec] = MappingProxyType({s.id: s for s in _SOURCES})
if len(REGISTRY) != len(_SOURCES):  # pragma: no cover - guards against a duplicate id edit
    raise RuntimeError("duplicate source id in registry")

#: Global exact-host allowlist: hosts of LIVE sources only. Disabled and manual sources contribute nothing.
ALLOWED_HOSTS: frozenset[str] = frozenset(h for s in _SOURCES if s.mode is SourceMode.LIVE for h in s.allowed_hosts)


def get_source(source_id: str) -> SourceSpec:
    try:
        return REGISTRY[source_id]
    except KeyError:
        raise KeyError(f"unknown source id {source_id!r}") from None


def hosts_for(spec: SourceSpec) -> frozenset[str]:
    """The hosts a request for ``spec`` may touch: its own list intersected with the global allowlist."""
    return spec.allowed_hosts & ALLOWED_HOSTS


def check_url(url: str, allowed_hosts: frozenset[str]) -> str:
    """Validate a URL against the fetch policy and return its host. Raises ``FetchRefused``.

    https only; port absent or 443; no userinfo; host lower-case ASCII and an *exact* member of ``allowed_hosts``.
    """
    if not isinstance(url, str) or any(c.isspace() or ord(c) < 0x20 or c == "\\" for c in url):
        raise FetchRefused("URL contains whitespace, control characters or backslashes")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise FetchRefused(f"unparseable URL: {exc}") from None
    if parts.scheme != "https":
        raise FetchRefused(f"scheme {parts.scheme!r} refused: https only")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise FetchRefused("userinfo in URL refused")
    if port not in (None, 443):
        raise FetchRefused(f"port {port} refused: 443 only")
    host = parts.hostname or ""
    if host not in allowed_hosts:
        raise FetchRefused(f"host {host!r} is not allowlisted for this source")
    return host


@dataclass(frozen=True, slots=True)
class SourceRequest:
    """A validated request for one registered source. Build it with the typed builders below."""

    source: SourceSpec
    url: str

    def __post_init__(self) -> None:
        if self.source.mode is not SourceMode.LIVE:
            raise FetchRefused(f"source {self.source.id!r} is {self.source.mode.value}; it is never fetched")
        check_url(self.url, hosts_for(self.source))


def _amfi_date(d: date) -> str:
    return f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year:04d}"


def _strict_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be int")
    return value


def navall_request() -> SourceRequest:
    return SourceRequest(get_source("amfi.navall"), "https://www.amfiindia.com/spages/NAVAll.txt")


def schememaster_request() -> SourceRequest:
    return SourceRequest(
        get_source("amfi.schememaster"), "https://portal.amfiindia.com/DownloadSchemeData_Po.aspx?mf=0"
    )


def navhistory_request(*, mf_id: int, tp: int, from_date: date, to_date: date) -> SourceRequest:
    """NAV history for one AMFI fund house (``mf``) and scheme type (``tp`` 1|2|3) over ≤ 90 days."""
    mf_id = _strict_int("mf_id", mf_id)
    tp = _strict_int("tp", tp)
    if isinstance(from_date, date) is False or isinstance(to_date, date) is False:
        raise TypeError("from_date and to_date must be dates")
    if not 1 <= mf_id <= 99_999:
        raise ValueError("mf_id must be a positive AMFI fund-house id")
    if tp not in (1, 2, 3):
        raise ValueError("tp must be 1, 2 or 3")
    if from_date > to_date:
        raise ValueError("from_date must not be after to_date")
    if (to_date - from_date).days > MAX_HISTORY_WINDOW_DAYS:
        raise ValueError(f"window exceeds {MAX_HISTORY_WINDOW_DAYS} days")
    url = (
        "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx"
        f"?mf={mf_id}&tp={tp}&frmdt={_amfi_date(from_date)}&todt={_amfi_date(to_date)}"
    )
    return SourceRequest(get_source("amfi.navhistory"), url)
