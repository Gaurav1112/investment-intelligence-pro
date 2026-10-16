"""Owner preferences behind the Settings page (PLAN.md wave 2, C04 over B04; design-risk-first.md §7.3, §9.4).

* **Vocabulary (U-11).** One wire vocabulary, shared with the Compliance Guard: :class:`iip.supervisor.compliance.
  Vocabulary` (``neutral`` | ``badges``). Stored in the ``settings`` key/value table under :data:`VOCABULARY_KEY`. A
  missing, unreadable or unknown stored value reads as ``neutral`` (the default; fails toward neutral). Opting in to
  ``badges`` needs the explicit private-view acknowledgement; badges are honoured on the PRIVATE surface only.
* **Notifications (U-09).** The channel is NOT a stored preference: it is ``IIP_NOTIFY`` plus a transport that can
  actually deliver (:func:`iip.services.notify.enabled_channels`). With no transport built (v1), every channel other
  than ``off`` is unavailable, so the effective channel is ``off`` and a request to switch one on is refused instead
  of being stored as a preference that nothing would honour. The page never claims a channel is on.

No clock here: nothing stored carries a timestamp.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass

from iip.services import notify
from iip.store.db import write_tx
from iip.supervisor.compliance import Vocabulary, parse_vocabulary

VOCABULARY_KEY = "prefs.vocabulary"


class PreferenceRejected(ValueError):
    """A preference change the server refuses. ``code`` is the API error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ------------------------------------------------------------------------------------------------- vocabulary


def read_vocabulary(conn: sqlite3.Connection) -> Vocabulary:
    """The owner's wording choice; anything but a stored ``badges`` is ``neutral`` (one statement)."""
    row = conn.execute("SELECT value_json FROM settings WHERE key=?", (VOCABULARY_KEY,)).fetchone()
    if row is None:
        return Vocabulary.NEUTRAL
    try:
        stored = json.loads(row["value_json"])
    except (TypeError, ValueError):
        return Vocabulary.NEUTRAL
    mode = stored.get("mode") if isinstance(stored, dict) else None
    return parse_vocabulary(mode) if isinstance(mode, str) else Vocabulary.NEUTRAL


def write_vocabulary(conn: sqlite3.Connection, mode: Vocabulary, *, acknowledge_private_only: bool) -> Vocabulary:
    """Store the wording choice. ``badges`` without the private-view acknowledgement is refused (nothing written)."""
    if mode is Vocabulary.BADGES and not acknowledge_private_only:
        raise PreferenceRejected(
            "ACK_REQUIRED", "BUY/SELL badges need the acknowledgement that they stay in your logged-in view"
        )
    with write_tx(conn):
        conn.execute(
            "INSERT INTO settings(key, value_json) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET"
            " value_json=excluded.value_json",
            (VOCABULARY_KEY, json.dumps({"mode": mode.value}, sort_keys=True, separators=(",", ":"))),
        )
    return mode


# ------------------------------------------------------------------------------------------------- notifications


@dataclass(frozen=True)
class NotificationView:
    channel: str  # the channel that can actually deliver now; "off" otherwise
    available: tuple[str, ...]  # channels this server can deliver on ("off" is implied and not listed)
    configured: str  # what IIP_NOTIFY asks for (may be unavailable)
    status: str  # "off" | "REQUIRES CONFIGURATION" | "on"
    problem: str | None
    ping_template: str

    def as_json(self) -> dict[str, object]:
        return {
            "channel": self.channel,
            "available": list(self.available),
            "configured": self.configured,
            "status": self.status,
            "problem": self.problem,
            "ping_template": self.ping_template,
        }


PING_TEMPLATE = notify.REPORT_TEMPLATE.format(as_of="DD-Mon")


def notification_view(env: Mapping[str, str]) -> NotificationView:
    config = notify.NotifyConfig.from_env(env)
    available = notify.enabled_channels(env)
    configured = str(config.channel)
    if not config.enabled:
        return NotificationView("off", available, configured, "off", config.problem, PING_TEMPLATE)
    if configured not in available:
        problem = f"{configured} has no delivery transport on this server, so nothing is sent"
        return NotificationView("off", available, configured, "REQUIRES CONFIGURATION", problem, PING_TEMPLATE)
    return NotificationView(configured, available, configured, "on", None, PING_TEMPLATE)


def check_notification_change(
    env: Mapping[str, str], channel: str, *, acknowledge_third_party_storage: bool
) -> NotificationView:
    """Validate a channel change against what the server can deliver. Nothing is stored: the channel is set by
    ``IIP_NOTIFY`` (U-09: off in v1). Returns the (unchanged) view when the request matches it."""
    view = notification_view(env)
    if channel == notify.Channel.TELEGRAM.value and not acknowledge_third_party_storage:
        raise PreferenceRejected("ACK_REQUIRED", "Telegram needs the acknowledgement that Telegram stores each ping")
    if channel == view.channel:
        return view
    if channel == notify.Channel.OFF.value:
        raise PreferenceRejected(
            "CHANNEL_SET_BY_ENVIRONMENT", "the channel is set by IIP_NOTIFY on this server; set it to off there"
        )
    raise PreferenceRejected(
        "CHANNEL_UNAVAILABLE", f"{channel} cannot deliver on this server (no transport configured), so it stays off"
    )
