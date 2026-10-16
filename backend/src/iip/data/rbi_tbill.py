"""RBI T-bill cut-off adapter: press-release RSS feed → self-checked 91/182/364-day yields (audit-automation.md §3.2).

Flow, per poll:

1. Conditional GET of the RSS feed (``If-Modified-Since`` from the previous poll). 304 → ``NOT_MODIFIED``.
2. Select the "91-Day, 182-Day and 364-Day T-Bill Auction Result: Cut-off" items (``parsers.rbi_pr``).
3. Use the item's ``description`` when it carries the cut-off table. Otherwise fetch the linked release page
   **once** (an honest user-agent; ``rbi_press_release_request``). HTTP 418 or RBI's "Unauthorised Access" page stops
   all further page requests in this poll and opens the source's breaker: no evasion, no retry with another identity.
4. Every yield is re-derived from its price; a mismatch abstains for that release (``TbillAbstain``).

The feed keeps only about 10 items, so a release can drop out between polls: ``NO_CUTOFF_IN_FEED`` lets Data health
say so. Only figures and a plain-text citation are returned — never HTML, never a link to render.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

from iip.data.fetch import Fetcher, FetchError, NotModified
from iip.data.models import DataError, FetchRefused
from iip.data.parsers.rbi_pr import (
    TbillAbstain,
    TbillCutoffRelease,
    html_text,
    is_access_denied,
    parse_cutoff_text,
    parse_feed,
    select_tbill_cutoffs,
)
from iip.data.registry import rbi_press_release_request, rbi_press_releases_rss_request

ADAPTER_ID = "rbi.tbill@0.1.0"
PAGE_SOURCE_ID = "rbi.pr.tbill"

PollStatus = Literal["OK", "NOT_MODIFIED", "NO_CUTOFF_IN_FEED", "ABSTAINED"]


@dataclass(frozen=True, slots=True)
class TbillAbstention:
    """One release the poll did not store.

    ``retry`` is True when the reason is transient (the release page was not fetched, the fetch failed, or RBI
    answered with its access-denied page): the content was never seen, so the release must be tried again on a
    later poll. False means the content itself was refused (self-check, schema, dates): a permanent outcome.
    """

    prid: int
    code: str
    message: str
    retry: bool = False


@dataclass(frozen=True, slots=True)
class TbillPoll:
    status: PollStatus
    releases: tuple[TbillCutoffRelease, ...] = ()
    abstentions: tuple[TbillAbstention, ...] = ()
    feed_sha256: str | None = None
    feed_retrieved_at: datetime | None = None
    feed_last_modified: datetime | None = None  # pass back as ``if_modified_since`` on the next poll
    page_requests: int = 0
    skipped_known: int = 0  # cut-off items in the feed that ``known_prids`` skipped


def poll_tbill_cutoffs(
    fetcher: Fetcher,
    *,
    if_modified_since: datetime | None = None,
    fetch_pages: bool = True,
    known_prids: frozenset[int] = frozenset(),
) -> TbillPoll:
    """One poll of RBI's feed. Raises only on feed-level failures (fetch errors, an unparseable feed).

    ``known_prids``: releases an earlier poll already handled (stored, or abstained for a permanent content reason).
    They are skipped without any page request, so a release page is fetched at most once however often the feed
    changes around it. A release abstained with ``retry`` set must not be added to ``known_prids``.
    """
    try:
        feed = fetcher.fetch(rbi_press_releases_rss_request(if_modified_since=if_modified_since))
    except NotModified:
        return TbillPoll(status="NOT_MODIFIED")
    in_feed = select_tbill_cutoffs(parse_feed(feed.content))
    candidates = [(item, prid) for item, prid in in_feed if prid not in known_prids]
    base = TbillPoll(
        status="NO_CUTOFF_IN_FEED",
        feed_sha256=feed.sha256,
        feed_retrieved_at=feed.retrieved_at,
        feed_last_modified=feed.last_modified,
        skipped_known=len(in_feed) - len(candidates),
    )
    if not candidates:
        return base

    releases: list[TbillCutoffRelease] = []
    abstentions: list[TbillAbstention] = []
    page_requests = 0
    stopped = False
    for item, prid in candidates:
        text = html_text(item.description)
        retry = False
        try:
            if "YTM" not in text and not is_access_denied(text):
                retry = True  # until the page text is in hand, any abstention is about the fetch, not the content
                if stopped or not fetch_pages:
                    raise TbillAbstain(
                        "NO_CUTOFF_TABLE", "the feed item has no cut-off table; the page was not fetched"
                    )
                page_requests += 1
                try:
                    page = fetcher.fetch(rbi_press_release_request(prid=prid))
                except (FetchError, FetchRefused, DataError) as exc:
                    stopped = True  # one failed page request ends page fetching for this poll
                    raise TbillAbstain("PAGE_FETCH_FAILED", f"release page not fetched: {exc}") from None
                text = html_text(page.content.decode("utf-8", errors="replace"))
                retry = False
            if is_access_denied(text):
                retry = True
                stopped = True
                fetcher.breaker.trip(PAGE_SOURCE_ID)
                raise TbillAbstain("ACCESS_DENIED", "RBI answered with its access-denied page; stopping")
            releases.append(parse_cutoff_text(text, prid=prid, pub_date=item.pub_date))
        except TbillAbstain as abstain:
            abstentions.append(TbillAbstention(prid, abstain.code, abstain.message, retry))
    return replace(
        base,
        status="OK" if releases else "ABSTAINED",
        releases=tuple(releases),
        abstentions=tuple(abstentions),
        page_requests=page_requests,
    )
