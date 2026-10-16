"""Ping-only notifications (B04; design-risk-first.md §9.4; design-judgement.md §2.4; PLAN.md §5.3 B04, §8 U-11).

What a notification may say is fixed here, not by the caller:

* **Off by default.** ``IIP_NOTIFY`` is ``off`` unless set to ``webpush`` or ``telegram``. Anything else is treated as
  ``off`` and reported (fail closed: an unrecognised channel never sends).
* **A ping carries no content.** Exactly two texts exist: the daily-report ping, whose only slot is the data as-of date
  (rendered from a :class:`~datetime.date` as ``DD-Mon``), and the fixed watchdog ping. Nothing from a card, a scheme or
  a snapshot payload is ever interpolated. Before any send the text must (a) fully match one of those two shapes and
  (b) pass the Compliance Guard on the PING surface; otherwise :class:`PingContentRefused` is raised and nothing is
  sent.
* **Ping only on change.** A report ping is queued only when the set of L1–L5 cards differs from the previous
  snapshot's. The set is keyed by a *snapshot-independent* card key (kind, rule, goal, instruments): ``card_id``
  itself includes the ``snapshot_id`` (contracts §7.1), so a set of ``card_id`` values would change every day and
  every quiet day would ping.
* **At most once, never resent.** Queueing is idempotent per (key, channel) (``ledger.enqueue_ping``). A row is claimed
  (pending → sending, committed) before the transport is called; a send that fails or is interrupted leaves the row in
  ``sending`` for the cron reaper to mark ``failed``. Losing a ping is the safe direction.
* **No transport is built in.** Web Push (VAPID, RFC 8291) and Telegram need keys and an outbound host on the fetch
  allowlist, so a configured channel with no transport is REQUIRES CONFIGURATION and sends nothing.

Callers pass ``now`` (ISO-8601 text); this module reads no clock.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Protocol

from iip.engine.actions.contracts import ActionCard, Layer
from iip.engine.determinism import content_hash
from iip.store import ledger
from iip.supervisor import compliance
from iip.supervisor.compliance import Surface

NOTIFY_ENV = "IIP_NOTIFY"
SERVICE_VERSION = "notify@1"

PING_LAYERS = frozenset({Layer.L1, Layer.L2, Layer.L3, Layer.L4, Layer.L5})

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
REPORT_TEMPLATE = "IIP: daily report ready (data as of {as_of}). Open the app."
WATCHDOG_TEXT = "IIP: the daily refresh needs attention. Open the app."
_PING_SHAPES = (
    re.compile(
        r"IIP: daily report ready \(data as of (?:0[1-9]|[12]\d|3[01])-(?:"
        + "|".join(_MONTHS)
        + r")\)\. Open the app\."
    ),
    re.compile(re.escape(WATCHDOG_TEXT)),
)


class Channel(StrEnum):
    OFF = "off"
    WEBPUSH = "webpush"
    TELEGRAM = "telegram"


class PingKind(StrEnum):
    REPORT = "report"
    WATCHDOG = "watchdog"


class PingContentRefused(ValueError):
    """The text is not one of the fixed ping shapes, or it fails the Compliance Guard on the PING surface."""


@dataclass(frozen=True)
class NotifyConfig:
    channel: Channel = Channel.OFF
    problem: str | None = None  # set when the environment value was not recognised (and so treated as off)

    @property
    def enabled(self) -> bool:
        return self.channel is not Channel.OFF

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> NotifyConfig:
        raw = env.get(NOTIFY_ENV)
        if raw is None or not raw.strip():
            return cls()
        value = raw.strip().lower()
        try:
            return cls(channel=Channel(value))
        except ValueError:
            return cls(problem=f"{NOTIFY_ENV} must be off, webpush or telegram; unrecognised value treated as off")


# ------------------------------------------------------------------------------------------------- the ping text


def format_as_of(as_of: date) -> str:
    """``DD-Mon`` with a fixed English month table (no locale)."""
    if not isinstance(as_of, date):
        raise PingContentRefused("the as-of slot takes a date")
    return f"{as_of.day:02d}-{_MONTHS[as_of.month - 1]}"


def check_ping(text: str) -> str:
    """Return ``text`` if it is a content-free ping; raise :class:`PingContentRefused` otherwise."""
    if not isinstance(text, str) or not any(shape.fullmatch(text) for shape in _PING_SHAPES):
        raise PingContentRefused("not a fixed ping shape")
    hits = compliance.blocked(text, surface=Surface.PING)
    if hits:
        raise PingContentRefused(f"compliance guard refused the ping ({', '.join(sorted({h.category for h in hits}))})")
    return text


def render_ping(kind: PingKind, as_of: date | None = None) -> str:
    if kind is PingKind.REPORT:
        if as_of is None:
            raise PingContentRefused("a report ping needs the data as-of date")
        return check_ping(REPORT_TEMPLATE.format(as_of=format_as_of(as_of)))
    if kind is PingKind.WATCHDOG:
        return check_ping(WATCHDOG_TEXT)
    raise PingContentRefused(f"unknown ping kind {kind!r}")


# ------------------------------------------------------------------------------------------------- change detection


def card_key(card: ActionCard) -> str:
    """Snapshot-independent identity of a card: the §7.1 card-id key without ``snapshot_id``."""
    return content_hash(
        {
            "kind": str(card.kind),
            "rule_ref": card.why.rule_ref,
            "goal_id": card.goal_id,
            "instrument_ids": list(card.instrument_ids),
        }
    )


def card_set_hash(cards: Iterable[ActionCard]) -> str:
    """Hash of the set of L1–L5 card keys (``signal_snapshots.card_set_hash``). Order and duplicates do not matter."""
    keys = sorted({card_key(c) for c in cards if c.layer in PING_LAYERS})
    return content_hash({"v": SERVICE_VERSION, "l1_l5": keys})


EMPTY_CARD_SET_HASH = card_set_hash(())


@dataclass(frozen=True)
class PingDecision:
    enqueue: bool
    reason: str  # notify_off | card_set_unchanged | card_set_changed | first_snapshot_empty | first_snapshot_cards


def decide_report_ping(config: NotifyConfig, current_hash: str, previous_hash: str | None) -> PingDecision:
    if not config.enabled:
        return PingDecision(False, "notify_off")
    if previous_hash is None:
        if current_hash == EMPTY_CARD_SET_HASH:
            return PingDecision(False, "first_snapshot_empty")
        return PingDecision(True, "first_snapshot_cards")
    if current_hash == previous_hash:
        return PingDecision(False, "card_set_unchanged")
    return PingDecision(True, "card_set_changed")


def queue_report_ping(
    conn: sqlite3.Connection,
    config: NotifyConfig,
    *,
    snapshot_id: str,
    current_hash: str,
    previous_hash: str | None,
    now: str,
) -> PingDecision:
    """Queue at most one report ping for ``snapshot_id``. Re-running with the same snapshot is a no-op."""
    decision = decide_report_ping(config, current_hash, previous_hash)
    if decision.enqueue:
        ledger.enqueue_ping(conn, snapshot_id, str(config.channel), PingKind.REPORT.value, snapshot_id, now)
    return decision


def queue_watchdog_ping(conn: sqlite3.Connection, config: NotifyConfig, *, run_key: str, now: str) -> PingDecision:
    if not config.enabled:
        return PingDecision(False, "notify_off")
    ledger.enqueue_ping(conn, f"watchdog:{run_key}", str(config.channel), PingKind.WATCHDOG.value, None, now)
    return PingDecision(True, "watchdog")


# ------------------------------------------------------------------------------------------------- delivery


class PingTransport(Protocol):
    """Sends one ping body. It receives only the checked text: never a card, snapshot or payload."""

    def send(self, text: str) -> None: ...


@dataclass(frozen=True)
class DeliveryReport:
    status: str  # off | REQUIRES CONFIGURATION | ran
    sent: int = 0
    failed: int = 0  # claimed, then the transport raised: left in 'sending' for the reaper, never resent
    refused: int = 0  # claimed, then the text could not be rendered or checked: never sent
    skipped: int = 0  # another worker claimed it first
    problems: tuple[str, ...] = field(default=())


def deliver_pending(
    conn: sqlite3.Connection,
    config: NotifyConfig,
    transport: PingTransport | None,
    *,
    now: str,
    limit: int = 20,
) -> DeliveryReport:
    """Send pending pings for the configured channel. One SELECT reads the batch; each row is claimed before send."""
    if not config.enabled:
        return DeliveryReport(status="off", problems=(config.problem,) if config.problem else ())
    if transport is None:
        return DeliveryReport(status="REQUIRES CONFIGURATION", problems=(f"no transport for {config.channel}",))
    rows = conn.execute(
        "SELECT o.outbox_key, o.kind, s.as_of_date FROM notification_outbox o"
        " LEFT JOIN signal_snapshots s ON s.snapshot_id = o.snapshot_id"
        " WHERE o.channel = ? AND o.state = 'pending' ORDER BY o.created_at, o.outbox_key LIMIT ?",
        (str(config.channel), int(limit)),
    ).fetchall()
    sent = failed = refused = skipped = 0
    problems: list[str] = []
    for row in rows:
        key = str(row[0])
        if not ledger.claim_ping(conn, key, str(config.channel), now):
            skipped += 1
            continue
        try:
            text = _text_for(str(row[1]), row[2])
        except (PingContentRefused, ValueError) as exc:
            refused += 1
            problems.append(f"{key}: {exc}")
            continue
        try:
            transport.send(text)
        except Exception as exc:  # any transport failure: never resend (the reaper marks it failed)
            failed += 1
            problems.append(f"{key}: transport error {type(exc).__name__}")
            continue
        ledger.mark_ping_sent(conn, key, str(config.channel), now)
        sent += 1
    return DeliveryReport("ran", sent, failed, refused, skipped, tuple(problems))


def _text_for(kind: str, as_of_date: object) -> str:
    ping_kind = PingKind(kind)
    if ping_kind is PingKind.WATCHDOG:
        return render_ping(ping_kind)
    if not isinstance(as_of_date, str):
        raise PingContentRefused("report ping without a stored snapshot date")
    return render_ping(ping_kind, date.fromisoformat(as_of_date))
