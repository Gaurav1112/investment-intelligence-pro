"""RBI T-bill cut-off adapter: RSS feed, release parser, yield self-check, registry rows, plain-text citations.

Every feed and release body here is SYNTHETIC: it copies the *layout* of the 2026-10-15/16 probes (RSS 2.0 with BOM
and CDATA, zone-less IST ``pubDate``, the cut-off table's "price (YTM: y%)" cells) with fictional dates in 2099,
fictional prices, and yields computed from those prices with the self-check formula. No RBI figure is committed.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from iip.data import rbi_tbill, registry
from iip.data.fetch import USER_AGENT, BreakerStatus, Fetcher, FetchFailed, RetryPolicy
from iip.data.models import FetchRefused, SchemaChanged
from iip.data.parsers import rbi_pr
from iip.data.registry import (
    ALLOWED_HOSTS,
    REGISTRY,
    LicenceClass,
    SourceMode,
    SourceStatus,
    citation_display,
    citation_link_allowed,
    get_source,
    rbi_press_release_request,
    rbi_press_releases_rss_request,
)

NOW = datetime(2099, 1, 7, 12, 0, tzinfo=UTC)
IST = timezone(timedelta(hours=5, minutes=30))
TITLE = "91-Day, 182-Day and 364-Day T-Bill Auction Result: Cut-off"
# Fictional prices; yields = (100 - P) / P * 365 / days, rounded half-up to 4 dp.
PRICES = ("98.6000", "97.1000", "94.2000")
YIELDS = ("5.6951", "5.9896", "6.1740")
PR_LINK = "https://www.rbi.org.in/scripts/BS_PressReleaseDisplay.aspx?prid={}"


def release_html(prices: tuple[str, ...] = PRICES, yields: tuple[str, ...] = YIELDS, *,
                 date_line: str = "Jan 07, 2099", ref: str = "2098-2099/9001") -> str:  # fmt: skip
    cells = "".join(f"<td>{p} (YTM: {y}%)</td>" for p, y in zip(prices, yields, strict=True))
    return (
        f'<table><tr><td align="right"><b>Date : {date_line}</b></td></tr><tr><td><b>{TITLE}</b></td></tr>'
        "<tr><td><table><tr><td></td><td>T-Bill</td><td>91-Day</td><td>182-Day</td><td>364-Day</td></tr>"
        "<tr><td>I.</td><td>Total Face Value Notified</td><td>&#8377;1,000 Crore</td><td>&#8377;1,000 Crore</td>"
        "<td>&#8377;1,000 Crore</td></tr>"
        f"<tr><td>II.</td><td>Cut-off Price (&#8377;) and Implicit Yield at Cut-Off Price</td>{cells}</tr>"
        "</table></td></tr></table>"
        f"<p>Press Release: {ref}</p>"
    )


def item(title: str, prid: int, description: str = "", pub: str = "Wed, 07 Jan 2099 17:00:00",
         host: str = "www.rbi.org.in") -> str:  # fmt: skip
    link = PR_LINK.format(prid).replace("www.rbi.org.in", host)
    return (f"<item><title><![CDATA[{title}]]></title><link>{link}</link><pubDate>{pub}</pubDate>"
            f"<description><![CDATA[{description}]]></description></item>")  # fmt: skip


def feed(*items: str) -> bytes:
    body = (
        '<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>SYNTHETIC FEED</title>'
        "<link>http://www.rbi.org.in</link><description>synthetic</description>" + "".join(items) + "</channel></rss>"
    )
    return b"\xef\xbb\xbf" + body.encode()


class Server:
    """MockTransport handler: the feed at /pressreleases_rss.xml, pages keyed by prid."""

    def __init__(self, feed_body: bytes, pages: dict[int, httpx.Response] | None = None,
                 feed_response: httpx.Response | None = None) -> None:  # fmt: skip
        self.feed_body = feed_body
        self.pages = pages or {}
        self.feed_response = feed_response
        self.requests: list[httpx.Request] = []

    def __call__(self, r: httpx.Request) -> httpx.Response:
        self.requests.append(r)
        if r.url.path == "/pressreleases_rss.xml":
            if self.feed_response is not None:
                return self.feed_response
            return httpx.Response(200, headers={"content-type": "text/xml",
                                                "last-modified": "Wed, 07 Jan 2099 11:30:00 GMT"},
                                  content=self.feed_body)  # fmt: skip
        return self.pages[int(r.url.params["prid"])]


def make_fetcher(handler: Callable[[httpx.Request], httpx.Response]) -> Fetcher:
    return Fetcher(transport=httpx.MockTransport(handler), resolver=lambda _h: ["23.0.0.1"], jitter_seed=1,
                   sleep=lambda _s: None, clock=lambda: NOW, retry=RetryPolicy(max_attempts=3))  # fmt: skip


def html_page(body: str) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"},
                          content=f"<html><body><nav>Home Press Releases</nav>{body}<footer>All Months January"
                                  "</footer></body></html>".encode())  # fmt: skip


# ------------------------------------------------------------------------------------------- self-check


@pytest.mark.parametrize(("price", "days", "expected"), list(zip(PRICES, (91, 182, 364), YIELDS, strict=True)))
def test_self_check_formula_reproduces_the_yields_to_4dp(price: str, days: int, expected: str) -> None:
    assert rbi_pr.implied_yield_pct(Decimal(price), days) == Decimal(expected)


def test_parses_a_release_with_matching_yields() -> None:
    rel = rbi_pr.parse_cutoff_text(rbi_pr.html_text(release_html()), prid=9001,
                                   pub_date=datetime(2099, 1, 7, 17, 0, tzinfo=IST))  # fmt: skip
    assert [y.tenor_days for y in rel.yields] == [91, 182, 364]
    assert [str(y.price) for y in rel.yields] == list(PRICES)
    assert [str(y.yield_pct) for y in rel.yields] == list(YIELDS)
    assert rel.yields[0].yield_fraction == Decimal("0.056951") and rel.yields[0].series_id == "riskfree:tbill91"
    assert rel.release_date == date(2099, 1, 7) and rel.date_basis == "release_text" and rel.auction_date is None
    assert rel.press_release_ref == "2098-2099/9001"
    assert rel.convention == "RBI_TBILL_IMPLICIT_YIELD_AS_PUBLISHED"


@pytest.mark.parametrize("tenor_index", [0, 1, 2])
def test_a_yield_off_by_one_basis_point_in_the_4th_dp_abstains(tenor_index: int) -> None:
    bad = list(YIELDS)
    bad[tenor_index] = str(Decimal(bad[tenor_index]) + Decimal("0.0001"))
    with pytest.raises(rbi_pr.TbillAbstain) as e:
        rbi_pr.parse_cutoff_text(rbi_pr.html_text(release_html(yields=tuple(bad))), prid=1, pub_date=None)
    assert e.value.code == "SELF_CHECK_MISMATCH"


def test_swapped_tenor_columns_abstain() -> None:
    swapped = (PRICES[1], PRICES[0], PRICES[2])
    with pytest.raises(rbi_pr.TbillAbstain) as e:
        rbi_pr.parse_cutoff_text(rbi_pr.html_text(release_html(swapped, (YIELDS[1], YIELDS[0], YIELDS[2]))),
                                 prid=1, pub_date=None)  # fmt: skip
    assert e.value.code == "SELF_CHECK_MISMATCH"


@pytest.mark.parametrize(
    ("text", "code"),
    [("T-Bill 91-Day 182-Day 364-Day 98.6000 (YTM: 5.6951%) 97.1000 (YTM: 5.9896%)", "SCHEMA_CHANGED"),
     ("Cut-off Price 98.6000 (YTM: 5.6951%)", "NO_CUTOFF_TABLE"),
     ("Unauthorised Access", "ACCESS_DENIED"),
     ("T-Bill 91-Day 182-Day 364-Day 100.5000 (YTM: 5.6951%) 97.1000 (YTM: 5.9896%) 94.2000 (YTM: 6.1740%)",
      "OUT_OF_RANGE"),
     ("T-Bill 91-Day 182-Day 364-Day 98.6000 (YTM: 5.6951%) 97.1000 (YTM: 5.9896%) 94.2000 (YTM: 6.1740%)",
      "NO_DATE")],
)  # fmt: skip
def test_unusable_text_abstains(text: str, code: str) -> None:
    with pytest.raises(rbi_pr.TbillAbstain) as e:
        rbi_pr.parse_cutoff_text(text, prid=1, pub_date=None)
    assert e.value.code == code


def test_release_date_must_agree_with_the_feed_pubdate() -> None:
    with pytest.raises(rbi_pr.TbillAbstain) as e:
        rbi_pr.parse_cutoff_text(rbi_pr.html_text(release_html()), prid=1,
                                 pub_date=datetime(2099, 1, 8, 17, 0, tzinfo=IST))  # fmt: skip
    assert e.value.code == "DATE_MISMATCH"


def test_feed_pubdate_is_used_only_when_the_text_has_no_date() -> None:
    text = rbi_pr.html_text(release_html()).replace("Date : Jan 07, 2099", "")
    rel = rbi_pr.parse_cutoff_text(text, prid=1, pub_date=datetime(2099, 1, 7, 17, 0, tzinfo=IST))
    assert rel.release_date == date(2099, 1, 7) and rel.date_basis == "feed_pubdate"


def test_a_stated_auction_date_is_kept_and_never_inferred() -> None:
    text = rbi_pr.html_text(release_html()).replace("Press Release:", "The auction was held on January 07, 2099. "
                                                    "Press Release:")  # fmt: skip
    rel = rbi_pr.parse_cutoff_text(text, prid=1, pub_date=None)
    assert rel.auction_date == date(2099, 1, 7)


# ------------------------------------------------------------------------------------------- feed parsing


def test_feed_parses_with_bom_cdata_and_zone_less_ist_pubdate() -> None:
    items = rbi_pr.parse_feed(feed(item("Money Market Operations as on January 06, 2099", 9000),
                                   item(TITLE, 9001, release_html())))  # fmt: skip
    assert [i.title for i in items] == ["Money Market Operations as on January 06, 2099", TITLE]
    assert items[1].pub_date == datetime(2099, 1, 7, 17, 0, tzinfo=IST)
    assert items[1].pub_date.utcoffset() == timedelta(hours=5, minutes=30)


def test_only_exact_titles_on_rbi_press_release_links_are_selected() -> None:
    items = rbi_pr.parse_feed(feed(
        item(TITLE, 9001), item(TITLE, 9001), item(TITLE + " (corrigendum)", 9002), item(TITLE, 9003, host="evil.test"),
        item(TITLE, 9004, host="rbi.org.in"), item("Treasury Bills: Full Auction Result", 9005), item(TITLE, 9006),
    ))  # fmt: skip
    assert [prid for _i, prid in rbi_pr.select_tbill_cutoffs(items)] == [9001, 9006]


@pytest.mark.parametrize(
    "link",
    ["http://www.rbi.org.in/scripts/BS_PressReleaseDisplay.aspx?prid=1",
     "https://www.rbi.org.in:8443/scripts/BS_PressReleaseDisplay.aspx?prid=1",
     "https://www.rbi.org.in/scripts/Other.aspx?prid=1", "https://www.rbi.org.in/scripts/BS_PressReleaseDisplay.aspx",
     "https://www.rbi.org.in/scripts/BS_PressReleaseDisplay.aspx?prid=1&prid=2",
     "https://www.rbi.org.in/scripts/BS_PressReleaseDisplay.aspx?prid=01"],
)  # fmt: skip
def test_press_release_id_is_strict(link: str) -> None:
    assert rbi_pr.press_release_id(link) is None


@pytest.mark.parametrize(
    "body",
    [b'<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY x "boom">]><rss><channel><item><title>&x;</title></item>'
     b"</channel></rss>",
     b"<rss><channel><item>", b"<feed><entry/></feed>", b"<rss></rss>", b"not xml"],
)  # fmt: skip
def test_hostile_or_unexpected_feeds_are_refused(body: bytes) -> None:
    with pytest.raises(SchemaChanged):
        rbi_pr.parse_feed(body)


def test_html_text_drops_scripts_and_decodes_entities() -> None:
    assert rbi_pr.html_text("<script>var a='YTM';</script><p>A&nbsp;&amp;&#8377;B</p>") == "A &₹B"


# ------------------------------------------------------------------------------------------- adapter (mocked IO)


def test_poll_uses_the_feed_description_without_fetching_the_page() -> None:
    server = Server(feed(item("Auction of State Government Securities", 9000), item(TITLE, 9001, release_html())))
    poll = rbi_tbill.poll_tbill_cutoffs(make_fetcher(server))
    assert poll.status == "OK" and poll.page_requests == 0 and not poll.abstentions
    (rel,) = poll.releases
    assert rel.prid == 9001 and [str(y.yield_pct) for y in rel.yields] == list(YIELDS)
    (req,) = server.requests
    assert str(req.url) == "https://www.rbi.org.in/pressreleases_rss.xml"
    assert req.headers["user-agent"] == USER_AGENT and "mozilla" not in USER_AGENT.lower()
    assert poll.feed_last_modified == datetime(2099, 1, 7, 11, 30, tzinfo=UTC)


def test_poll_fetches_the_release_page_once_when_the_description_lacks_the_table() -> None:
    server = Server(feed(item(TITLE, 9001, "<p>See the release.</p>")), pages={9001: html_page(release_html())})
    poll = rbi_tbill.poll_tbill_cutoffs(make_fetcher(server))
    assert poll.status == "OK" and poll.page_requests == 1
    assert [str(r.url) for r in server.requests][1] == PR_LINK.format(9001)
    assert poll.releases[0].press_release_ref == "2098-2099/9001"


def test_page_fetching_can_be_disabled() -> None:
    server = Server(feed(item(TITLE, 9001, "<p>See the release.</p>")))
    poll = rbi_tbill.poll_tbill_cutoffs(make_fetcher(server), fetch_pages=False)
    assert poll.status == "ABSTAINED" and poll.abstentions[0].code == "NO_CUTOFF_TABLE"
    assert len(server.requests) == 1


def test_a_self_check_mismatch_abstains_and_stores_nothing() -> None:
    bad = (YIELDS[0], YIELDS[1], "6.1741")
    server = Server(feed(item(TITLE, 9001, release_html(yields=bad))))
    poll = rbi_tbill.poll_tbill_cutoffs(make_fetcher(server))
    assert poll.status == "ABSTAINED" and poll.releases == ()
    assert [(a.prid, a.code) for a in poll.abstentions] == [(9001, "SELF_CHECK_MISMATCH")]


def test_access_denied_page_stops_page_fetching_and_opens_the_breaker() -> None:
    server = Server(
        feed(item(TITLE, 9001, "<p>x</p>"), item(TITLE, 9002, "<p>x</p>")),
        pages={9001: html_page("<h1>Unauthorised Access</h1>"), 9002: html_page(release_html())},
    )
    f = make_fetcher(server)
    poll = rbi_tbill.poll_tbill_cutoffs(f)
    assert [(a.prid, a.code) for a in poll.abstentions] == [(9001, "ACCESS_DENIED"), (9002, "NO_CUTOFF_TABLE")]
    assert poll.page_requests == 1 and len(server.requests) == 2
    assert f.breaker.state("rbi.pr.tbill").status is BreakerStatus.OPEN


def test_http_418_is_not_retried_and_opens_the_breaker() -> None:
    server = Server(feed(), feed_response=httpx.Response(418))
    f = make_fetcher(server)
    with pytest.raises(FetchFailed) as e:
        rbi_tbill.poll_tbill_cutoffs(f)
    assert e.value.status == 418 and len(server.requests) == 1
    assert f.breaker.state("rbi.rss.pressreleases").status is BreakerStatus.OPEN


def test_http_418_on_a_page_abstains_and_stops() -> None:
    server = Server(feed(item(TITLE, 9001, "<p>x</p>"), item(TITLE, 9002, "<p>x</p>")),
                    pages={9001: httpx.Response(418), 9002: html_page(release_html())})  # fmt: skip
    f = make_fetcher(server)
    poll = rbi_tbill.poll_tbill_cutoffs(f)
    assert [a.code for a in poll.abstentions] == ["PAGE_FETCH_FAILED", "NO_CUTOFF_TABLE"]
    assert len(server.requests) == 2 and f.breaker.state("rbi.pr.tbill").status is BreakerStatus.OPEN


def test_conditional_get_sends_if_modified_since_and_handles_304() -> None:
    server = Server(feed(), feed_response=httpx.Response(304))
    f = make_fetcher(server)
    poll = rbi_tbill.poll_tbill_cutoffs(f, if_modified_since=datetime(2099, 1, 7, 11, 30, tzinfo=UTC))
    assert poll.status == "NOT_MODIFIED"
    assert server.requests[0].headers["if-modified-since"] == "Wed, 07 Jan 2099 11:30:00 GMT"
    assert f.breaker.state("rbi.rss.pressreleases").status is BreakerStatus.CLOSED


def test_no_cutoff_item_in_the_feed_is_reported() -> None:
    server = Server(feed(item("Money Market Operations as on January 06, 2099", 9000)))
    poll = rbi_tbill.poll_tbill_cutoffs(make_fetcher(server))
    assert poll.status == "NO_CUTOFF_IN_FEED" and poll.feed_sha256 is not None


# ------------------------------------------------------------------------------------------- registry and citations


def test_every_registry_entry_carries_a_licence_class_and_a_status() -> None:
    for spec in REGISTRY.values():
        assert isinstance(spec.licence_class, LicenceClass) and spec.licence_note
        assert isinstance(spec.status, SourceStatus) and spec.status_ref, spec.id


def test_rbi_rows() -> None:
    feed_spec, page_spec = get_source("rbi.rss.pressreleases"), get_source("rbi.pr.tbill")
    for spec in (feed_spec, page_spec):
        assert spec.mode is SourceMode.LIVE and spec.allowed_hosts == {"www.rbi.org.in"}
        assert spec.licence_class is LicenceClass.PUBLIC_GOVT and spec.citation_links is False
        assert spec.requires_configuration is False
    assert feed_spec.status is SourceStatus.VERIFIED and page_spec.status is SourceStatus.NOT_VERIFIED
    assert get_source("mospi.cpi").status is SourceStatus.VERIFIED
    assert all(not s.citation_links for s in REGISTRY.values() if s.owner == "RBI")
    assert "www.rbi.org.in" in ALLOWED_HOSTS
    assert not {"rbi.org.in", "rbidocs.rbi.org.in", "m.rbi.org.in"} & ALLOWED_HOSTS


def test_rbi_request_builders_are_typed_and_anonymous() -> None:
    assert rbi_press_release_request(prid=9001).url == PR_LINK.format(9001)
    for bad in (0, -1, 10**9):
        with pytest.raises(ValueError):
            rbi_press_release_request(prid=bad)
    with pytest.raises(TypeError):
        rbi_press_release_request(prid="9001")  # type: ignore[arg-type]
    with pytest.raises(FetchRefused):
        rbi_press_releases_rss_request(if_modified_since=datetime(2099, 1, 1))  # naive datetime
    with pytest.raises(FetchRefused):
        registry.SourceRequest(get_source("rbi.rss.pressreleases"), "https://rbi.org.in/pressreleases_rss.xml")


@pytest.mark.parametrize(
    "url",
    ["https://www.rbi.org.in/scripts/BS_PressReleaseDisplay.aspx?prid=1", "https://rbi.org.in/x",
     "https://RBIDOCS.rbi.org.in/rdocs/x.pdf", "https://m.rbi.org.in/x", "https://www.rbi.org.in./x",
     "javascript:alert(1)", "not a url"],
)  # fmt: skip
def test_rbi_citations_render_as_plain_text(url: str) -> None:
    assert citation_link_allowed(url) is False
    shown = citation_display(url)
    assert shown.href is None and shown.text == url


def test_other_citations_keep_their_link() -> None:
    shown = citation_display("https://www.amfiindia.com/terms-of-use", "AMFI terms")
    assert shown.href == "https://www.amfiindia.com/terms-of-use" and shown.text == "AMFI terms"


def test_release_citation_text_is_plain_text_without_a_url() -> None:
    rel = rbi_pr.parse_cutoff_text(rbi_pr.html_text(release_html()), prid=9001, pub_date=None)
    assert "http" not in rel.citation_text and "rbi.org.in" not in rel.citation_text
    assert "2098-2099/9001" in rel.citation_text and "2099-01-07" in rel.citation_text


def test_abstentions_say_whether_the_release_must_be_retried() -> None:
    """POLL-2: fetch-side abstentions are transient (retry); a refusal of the release content is permanent."""
    server = Server(
        feed(item(TITLE, 9001, release_html(yields=(YIELDS[0], YIELDS[1], "6.1741"))),
             item(TITLE, 9002, "<p>x</p>"), item(TITLE, 9003, "<p>x</p>")),
        pages={9002: httpx.Response(418), 9003: html_page(release_html())},
    )  # fmt: skip
    poll = rbi_tbill.poll_tbill_cutoffs(make_fetcher(server))
    assert [(a.prid, a.code, a.retry) for a in poll.abstentions] == [
        (9001, "SELF_CHECK_MISMATCH", False),
        (9002, "PAGE_FETCH_FAILED", True),
        (9003, "NO_CUTOFF_TABLE", True),  # not fetched after the failure: the content was never seen
    ]


def test_access_denied_is_a_transient_abstention() -> None:
    server = Server(feed(item(TITLE, 9001, "<p>x</p>")), pages={9001: html_page("<h1>Unauthorised Access</h1>")})
    poll = rbi_tbill.poll_tbill_cutoffs(make_fetcher(server))
    assert [(a.code, a.retry) for a in poll.abstentions] == [("ACCESS_DENIED", True)]


def test_a_fetched_page_without_the_table_is_a_permanent_abstention() -> None:
    server = Server(feed(item(TITLE, 9001, "<p>x</p>")), pages={9001: html_page("<p>nothing here</p>")})
    poll = rbi_tbill.poll_tbill_cutoffs(make_fetcher(server))
    assert [(a.code, a.retry) for a in poll.abstentions] == [("NO_CUTOFF_TABLE", False)]
