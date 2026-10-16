"""B04: ping-only notifications (design-risk-first.md §9.4; PLAN.md §5.3 B04).

The sentinel test: cards and snapshots are filled with SENTINEL rupee amounts, a SENTINEL scheme name and buy/sell
words; every ping that leaves through the transport is captured and checked for all of them. All values are synthetic.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from iip.engine.actions import contracts as c
from iip.services import notify as nt
from iip.services.notify import Channel, NotifyConfig, PingContentRefused, PingKind
from iip.store import ledger as lg
from tests.store._ledger_fixtures import DRIVERS, NOW, open_db
from tests.unit.test_cards import emergency_card, num, why

SENTINEL_AMOUNTS = ("₹9,87,654.32", "987654.32", "9,87,654", "Rs 98765", "INR 98765", "98765")
SENTINEL_SCHEME = "Zyxwv Sentinel Bluechip Fund"
TRADE_WORDS = re.compile(r"\b(buy|buys|buying|bought|sell|sells|selling|sold|redeem|invest|switch|purchase)\b", re.I)
WEBPUSH = NotifyConfig(channel=Channel.WEBPUSH)
LATER = "2026-10-16T06:00:00+00:00"


class Capture:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[str] = []
        self.fail = fail

    def send(self, text: str) -> None:
        if self.fail:
            raise ConnectionError("synthetic transport outage")
        self.sent.append(text)


@pytest.fixture(params=DRIVERS)
def db(request: pytest.FixtureRequest, tmp_path: Path) -> Any:
    conn = open_db(tmp_path / "n.db", request.param)
    yield conn
    conn.close()


def _sentinel_card(**over: Any) -> c.ActionCard:
    amount = Decimal("987654.32")
    base: dict[str, Any] = {
        "impact": c.Impact(amount_inr=amount, basis=c.ImpactBasis.SHORTFALL, slot="shortfall"),
        "steps": (
            c.Step(
                verb=c.Verb.REDIRECT_SIP,
                instrument_id=SENTINEL_SCHEME,
                amount_inr=amount,
                formula_id="risk.emergency_gate@1",
            ),
        ),
        "numbers": (
            num("shortfall", "987654.32", c.NumberUnit.INR, formula_id="risk.emergency_gate@1"),
            num("months", "6", c.NumberUnit.MONTHS, fact_ids=("user:emergency_months",)),
        ),
    }
    base.update(over)
    return emergency_card(**base)


def _payload(cards: list[c.ActionCard]) -> str:
    body = {
        "cards": [{"card_id": k.card_id, "text": f"SELL {SENTINEL_SCHEME}: buy back ₹9,87,654.32"} for k in cards],
        "scheme": SENTINEL_SCHEME,
        "amounts": list(SENTINEL_AMOUNTS),
    }
    return json.dumps(body, ensure_ascii=False)


def _put(db: Any, sid: str, as_of: str, cards: list[c.ActionCard]) -> str:
    h = nt.card_set_hash(cards)
    lg.put_snapshot(
        db,
        lg.SignalSnapshot(
            snapshot_id=sid, as_of_date=as_of, engine_version="e1", rules_version="r1", input_manifest_hash="m",
            verdict="ACTIONS", card_set_hash=h, payload_json=_payload(cards), created_at=NOW,
        ),
    )  # fmt: skip
    return h


def _assert_content_free(text: str) -> None:
    for s in SENTINEL_AMOUNTS:
        assert s not in text
    assert "987654" not in text.replace(",", "")
    assert "₹" not in text
    assert not re.search(r"\b(rs|inr)\b", text, re.I)
    assert "sentinel" not in text.lower()
    assert "bluechip" not in text.lower()
    assert "fund" not in text.lower()
    assert not TRADE_WORDS.search(text)


# --- default off ------------------------------------------------------------------------------------------------


def test_notify_is_off_by_default() -> None:
    cfg = NotifyConfig.from_env({})
    assert cfg.channel is Channel.OFF and not cfg.enabled and cfg.problem is None
    assert NotifyConfig() == cfg
    assert NotifyConfig.from_env({"IIP_NOTIFY": "  "}).channel is Channel.OFF


@pytest.mark.parametrize("value", ["telegrm", "ntfy", "email", "on", "1"])
def test_unrecognised_channel_fails_closed_to_off_and_says_so(value: str) -> None:
    cfg = NotifyConfig.from_env({"IIP_NOTIFY": value})
    assert cfg.channel is Channel.OFF
    assert cfg.problem is not None and value not in cfg.problem  # the raw value is not echoed


@pytest.mark.parametrize(("value", "want"), [("webpush", Channel.WEBPUSH), (" Telegram ", Channel.TELEGRAM)])
def test_known_channels_parse(value: str, want: Channel) -> None:
    assert NotifyConfig.from_env({"IIP_NOTIFY": value}).channel is want


def test_off_queues_and_sends_nothing(db: Any) -> None:
    cards = [_sentinel_card(snapshot_id="s1")]
    h = _put(db, "s1", "2026-10-14", cards)
    off = NotifyConfig()
    assert nt.queue_report_ping(db, off, snapshot_id="s1", current_hash=h, previous_hash=None, now=NOW).reason == (
        "notify_off"
    )
    assert not nt.queue_watchdog_ping(db, off, run_key="2026-10-14", now=NOW).enqueue
    assert db.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0] == 0
    cap = Capture()
    assert nt.deliver_pending(db, off, cap, now=LATER).status == "off"
    assert cap.sent == []


def test_configured_channel_without_transport_requires_configuration(db: Any) -> None:
    h = _put(db, "s1", "2026-10-14", [_sentinel_card(snapshot_id="s1")])
    nt.queue_report_ping(db, WEBPUSH, snapshot_id="s1", current_hash=h, previous_hash=None, now=NOW)
    rep = nt.deliver_pending(db, WEBPUSH, None, now=LATER)
    assert rep.status == "REQUIRES CONFIGURATION" and rep.sent == 0
    assert db.execute("SELECT state FROM notification_outbox").fetchone()[0] == "pending"


# --- THE SENTINEL TEST --------------------------------------------------------------------------------------------


def test_sentinel_no_amounts_scheme_names_or_trade_words_ever_reach_a_ping(db: Any) -> None:
    day1 = [_sentinel_card(snapshot_id="s1")]
    day2 = [_sentinel_card(snapshot_id="s2", goal_id="goal-sentinel-house")]
    h1 = _put(db, "s1", "2026-10-14", day1)
    h2 = _put(db, "s2", "2026-10-15", day2)
    assert nt.queue_report_ping(db, WEBPUSH, snapshot_id="s1", current_hash=h1, previous_hash=None, now=NOW).enqueue
    assert nt.queue_report_ping(db, WEBPUSH, snapshot_id="s2", current_hash=h2, previous_hash=h1, now=NOW).enqueue
    assert nt.queue_watchdog_ping(db, WEBPUSH, run_key="2026-10-15", now=NOW).enqueue

    cap = Capture()
    rep = nt.deliver_pending(db, WEBPUSH, cap, now=LATER)
    assert rep.status == "ran" and rep.sent == 3 and rep.failed == rep.refused == 0
    assert sorted(cap.sent) == sorted(
        [
            "IIP: daily report ready (data as of 14-Oct). Open the app.",
            "IIP: daily report ready (data as of 15-Oct). Open the app.",
            "IIP: the daily refresh needs attention. Open the app.",
        ]
    )
    for text in cap.sent:
        _assert_content_free(text)
    assert {r[0] for r in db.execute("SELECT state FROM notification_outbox")} == {"sent"}


@settings(max_examples=200, deadline=None)
@given(st.text(min_size=1, max_size=80))
def test_no_text_other_than_the_fixed_shapes_passes_the_ping_check(text: str) -> None:
    allowed = re.fullmatch(r"IIP: daily report ready \(data as of \d\d-[A-Z][a-z]{2}\)\. Open the app\.", text)
    if allowed is None and text != nt.WATCHDOG_TEXT:
        with pytest.raises(PingContentRefused):
            nt.check_ping(text)


@pytest.mark.parametrize(
    "text",
    [
        f"IIP: daily report ready (data as of 14-Oct). Open the app. {SENTINEL_SCHEME}",
        "IIP: daily report ready (data as of ₹9,87,654.32). Open the app.",
        "IIP: daily report ready (data as of 14-Oct). SELL now.",
        "IIP: daily report ready (data as of 14-Oct).\nOpen the app.",
        "IIP: daily report ready (data as of 32-Oct). Open the app.",
        "",
    ],
)
def test_check_ping_refuses_anything_but_the_fixed_shapes(text: str) -> None:
    with pytest.raises(PingContentRefused):
        nt.check_ping(text)


@settings(max_examples=100, deadline=None)
@given(st.dates(min_value=date(2000, 1, 1), max_value=date(2099, 12, 31)))
def test_every_report_ping_is_content_free_for_any_date(d: date) -> None:
    text = nt.render_ping(PingKind.REPORT, d)
    assert nt.check_ping(text) == text
    _assert_content_free(text)


def test_report_ping_needs_a_real_date() -> None:
    with pytest.raises(PingContentRefused):
        nt.render_ping(PingKind.REPORT, None)
    with pytest.raises(PingContentRefused):
        nt.format_as_of("2026-10-14")  # type: ignore[arg-type]


# --- ping only when the L1–L5 card set changes --------------------------------------------------------------------


def test_card_set_hash_ignores_snapshot_id_order_and_layers_outside_l1_l5() -> None:
    a = _sentinel_card(snapshot_id="s1")
    b = _sentinel_card(snapshot_id="s2")
    assert a.card_id != b.card_id  # card_id includes the snapshot: a raw card_id set would change every day
    assert nt.card_set_hash([a]) == nt.card_set_hash([b]) == nt.card_set_hash([b, b])
    other = _sentinel_card(snapshot_id="s1", goal_id="goal-sentinel-2")
    assert nt.card_set_hash([a, other]) == nt.card_set_hash([other, a])
    assert nt.card_set_hash([a, other]) != nt.card_set_hash([a])


def test_cards_outside_l1_l5_do_not_change_the_set() -> None:
    base = _sentinel_card(snapshot_id="s1")
    l6 = replace(base, kind=c.CardKind.REVIEW_FLAG, layer=c.Layer.L6, why=why("info.review_flag"))
    assert nt.card_set_hash([base, l6]) == nt.card_set_hash([base])
    assert nt.card_set_hash([l6]) == nt.EMPTY_CARD_SET_HASH


def test_changing_only_amounts_does_not_ping() -> None:
    a = _sentinel_card(snapshot_id="s1")
    b = _sentinel_card(
        snapshot_id="s2",
        impact=c.Impact(amount_inr=Decimal("11"), basis=c.ImpactBasis.SHORTFALL, slot="shortfall"),
        steps=(c.Step(verb=c.Verb.REDIRECT_SIP, instrument_id=SENTINEL_SCHEME, amount_inr=Decimal("11"),
                      formula_id="risk.emergency_gate@1"),),
        numbers=(num("shortfall", "11", c.NumberUnit.INR, formula_id="risk.emergency_gate@1"),),
    )  # fmt: skip
    assert nt.decide_report_ping(WEBPUSH, nt.card_set_hash([b]), nt.card_set_hash([a])).reason == "card_set_unchanged"


@pytest.mark.parametrize(
    ("current", "previous", "enqueue", "reason"),
    [
        ("h", "h", False, "card_set_unchanged"),
        ("h2", "h", True, "card_set_changed"),
        (nt.EMPTY_CARD_SET_HASH, None, False, "first_snapshot_empty"),
        ("h", None, True, "first_snapshot_cards"),
        (nt.EMPTY_CARD_SET_HASH, "h", True, "card_set_changed"),  # every L1–L5 card resolved: also a change
    ],
)
def test_decide_report_ping(current: str, previous: str | None, enqueue: bool, reason: str) -> None:
    got = nt.decide_report_ping(WEBPUSH, current, previous)
    assert (got.enqueue, got.reason) == (enqueue, reason)


def test_quiet_day_sends_nothing(db: Any) -> None:
    h1 = _put(db, "s1", "2026-10-14", [_sentinel_card(snapshot_id="s1")])
    h2 = _put(db, "s2", "2026-10-15", [_sentinel_card(snapshot_id="s2")])
    assert h1 == h2
    d = nt.queue_report_ping(db, WEBPUSH, snapshot_id="s2", current_hash=h2, previous_hash=h1, now=NOW)
    assert d.reason == "card_set_unchanged"
    assert db.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0] == 0


# --- at most once; never resent ---------------------------------------------------------------------------------


def test_requeue_and_redelivery_are_no_ops(db: Any) -> None:
    h = _put(db, "s1", "2026-10-14", [_sentinel_card(snapshot_id="s1")])
    for _ in range(3):
        nt.queue_report_ping(db, WEBPUSH, snapshot_id="s1", current_hash=h, previous_hash=None, now=NOW)
    cap = Capture()
    assert nt.deliver_pending(db, WEBPUSH, cap, now=LATER).sent == 1
    assert nt.deliver_pending(db, WEBPUSH, cap, now=LATER).sent == 0
    assert len(cap.sent) == 1


def test_transport_failure_is_never_resent(db: Any) -> None:
    h = _put(db, "s1", "2026-10-14", [_sentinel_card(snapshot_id="s1")])
    nt.queue_report_ping(db, WEBPUSH, snapshot_id="s1", current_hash=h, previous_hash=None, now=NOW)
    rep = nt.deliver_pending(db, WEBPUSH, Capture(fail=True), now=LATER)
    assert rep.failed == 1 and rep.sent == 0
    assert all("987654" not in p and "Sentinel" not in p for p in rep.problems)
    assert db.execute("SELECT state FROM notification_outbox").fetchone()[0] == "sending"
    assert lg.reap_stale_pings(db, "2026-10-17T00:00:00+00:00", "2026-10-17T00:00:00+00:00") == 1
    ok = Capture()
    assert nt.deliver_pending(db, WEBPUSH, ok, now="2026-10-17T01:00:00+00:00").sent == 0
    assert ok.sent == []


def test_only_the_configured_channel_is_delivered(db: Any) -> None:
    h = _put(db, "s1", "2026-10-14", [_sentinel_card(snapshot_id="s1")])
    tg = NotifyConfig(channel=Channel.TELEGRAM)
    nt.queue_report_ping(db, tg, snapshot_id="s1", current_hash=h, previous_hash=None, now=NOW)
    cap = Capture()
    assert nt.deliver_pending(db, WEBPUSH, cap, now=LATER).sent == 0
    assert nt.deliver_pending(db, tg, cap, now=LATER).sent == 1
    assert cap.sent == ["IIP: daily report ready (data as of 14-Oct). Open the app."]


def test_transport_receives_only_text() -> None:
    import inspect

    sig = inspect.signature(nt.PingTransport.send)
    assert list(sig.parameters) == ["self", "text"]


def test_watchdog_ping_is_idempotent_per_run_key(db: Any) -> None:
    for _ in range(2):
        nt.queue_watchdog_ping(db, WEBPUSH, run_key="2026-10-15", now=NOW)
    assert db.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0] == 1
    assert db.execute("SELECT outbox_key, kind FROM notification_outbox").fetchone()[:] == (
        "watchdog:2026-10-15",
        "watchdog",
    )
