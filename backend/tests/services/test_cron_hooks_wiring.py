"""Integration glue: the cron hooks B03 resolves by name now exist (B02 snapshot step, B04 notify channels/sender),
and the snapshot's card-set hash is B04's snapshot-independent key. All data is SYNTHETIC."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from iip.rules.loader import LOCAL_STRESS_ENV
from iip.services import cron, notify
from iip.services import risk_snapshot as rs
from tests.services import _snapshot_fixtures as fx

NOW = datetime(2026, 10, 16, 6, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path: Path) -> Any:
    c = fx.open_db(tmp_path / "iip.db")
    yield c
    c.close()


def _row(**cols: object) -> sqlite3.Row:
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    names = list(cols)
    row: sqlite3.Row = mem.execute("SELECT " + ", ".join("? AS " + n for n in names), list(cols.values())).fetchone()
    mem.close()
    return row


class _Transport:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, text: str) -> None:
        self.sent.append(text)


def test_default_hooks_resolve_the_snapshot_step_and_stay_silent_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(notify.NOTIFY_ENV, raising=False)
    hooks = cron.default_hooks()
    assert hooks.snapshot is rs.cron_snapshot_step
    assert hooks.channels == () and hooks.sender is None


def test_a_channel_without_a_transport_is_not_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    assert notify.enabled_channels({notify.NOTIFY_ENV: "webpush"}) == ()
    assert notify.enabled_channels({}) == ()
    monkeypatch.setitem(notify.TRANSPORTS, notify.Channel.WEBPUSH, _Transport())
    assert notify.enabled_channels({notify.NOTIFY_ENV: "webpush"}) == ("webpush",)
    assert notify.enabled_channels({notify.NOTIFY_ENV: "telegram"}) == ()


def test_send_ping_refuses_without_a_transport_and_sends_only_the_fixed_text(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(notify.PingContentRefused):
        notify.send_ping(_row(channel="webpush", kind="report", as_of_date="2026-10-15"))
    t = _Transport()
    monkeypatch.setitem(notify.TRANSPORTS, notify.Channel.WEBPUSH, t)
    notify.send_ping(_row(channel="webpush", kind="report", as_of_date="2026-10-15"))
    notify.send_ping(_row(channel="webpush", kind="watchdog", as_of_date=None))
    assert t.sent == [notify.REPORT_TEMPLATE.format(as_of="15-Oct"), notify.WATCHDOG_TEXT]
    with pytest.raises(notify.PingContentRefused):  # a report without a stored snapshot date is never sent
        notify.send_ping(_row(channel="webpush", kind="report", as_of_date=None))


def test_cron_snapshot_step_stores_once_and_reports_codes_only(conn: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LOCAL_STRESS_ENV, raising=False)
    fx.seed_two_goals(conn)
    first = rs.cron_snapshot_step(conn, NOW)
    assert isinstance(first, cron.SnapshotOutcome) and first.written
    # Without the hosted stress values (U-08) the loss-budget layer cannot run, so the snapshot abstains honestly.
    assert first.as_of_date == fx.AS_OF.isoformat() and first.verdict == rs.VERDICT_ABSTAIN
    stored = conn.execute("SELECT card_set_hash FROM signal_snapshots WHERE snapshot_id = ?",
                          (first.snapshot_id,)).fetchone()  # fmt: skip
    assert stored["card_set_hash"] == first.card_set_hash
    again = rs.cron_snapshot_step(conn, NOW)
    assert again.snapshot_id == first.snapshot_id and not again.written


def test_cron_snapshot_step_uses_the_hosted_private_stress_values(conn: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """U-08 on hosted: J4 must read the same private values the Today page uses, from the secret env var."""
    monkeypatch.setenv(LOCAL_STRESS_ENV, "schema_version: 1\nvalues:\n  - {risk_class: EQ_BROAD, stress: '0.500'}\n")
    seen: list[Any] = []
    real = rs.run_daily

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs["stress_table"])
        return real(*args, **kwargs)

    monkeypatch.setattr(rs, "run_daily", spy)
    fx.seed_two_goals(conn)
    rs.cron_snapshot_step(conn, NOW)
    assert seen and seen[0].local_values_loaded and str(seen[0].cited_stress("EQ_BROAD")) == "0.500"


def test_cron_snapshot_step_refuses_without_any_nav(conn: Any) -> None:
    with pytest.raises(ValueError, match="no NAV data"):
        rs.cron_snapshot_step(conn, NOW)


def test_card_set_hash_is_notify_key_over_action_cards(conn: Any) -> None:
    fx.seed_two_goals(conn)
    snap = rs.compute_snapshot(rs.load_inputs(conn, fx.AS_OF, fx.stress_table()), fx.TEMPLATES)
    assert snap.card_set_hash == notify.card_set_hash(c for c in snap.cards if c.is_action)
    assert snap.card_set_hash != notify.EMPTY_CARD_SET_HASH  # the fixture has a loss-budget breach


def _store_payload(conn: Any, sid: str, cards: list[dict[str, Any]]) -> None:
    import json

    from iip.store import ledger

    ledger.put_snapshot(conn, ledger.SignalSnapshot(
        snapshot_id=sid, as_of_date="2026-10-15", engine_version="synthetic", rules_version="synthetic",
        input_manifest_hash="0" * 64, verdict="ACTIONS", card_set_hash="1" * 64,
        payload_json=json.dumps({"cards": cards, "suppressed": []}), created_at=NOW.isoformat(),
    ))  # fmt: skip
    conn.commit()


def test_cas_decision_checks_read_the_moves_from_the_card_steps(conn: Any) -> None:
    from iip.services import cas

    sid = "a" * 64
    invest = {"card_id": "b" * 64, "is_action": True, "goal_id": None, "steps": [
        {"verb": "INVEST", "instrument_id": "mf:synthetic-1"},
        {"verb": "SWITCH", "instrument_id": "mf:synthetic-2"},
        {"verb": "REDIRECT_SIP", "instrument_id": None},
    ]}  # fmt: skip
    redirect = {"card_id": "c" * 64, "is_action": True, "goal_id": None,
                "steps": [{"verb": "REDIRECT_SIP", "instrument_id": None}]}  # fmt: skip
    _store_payload(conn, sid, [invest, redirect])
    for card in (invest, redirect):
        rs.record_decision(conn, snapshot_id=sid, card_id=str(card["card_id"]), decision="done", note=None,
                           now="2026-10-16T05:00:00+00:00")  # fmt: skip
    rs.record_decision(conn, snapshot_id=sid, card_id="c" * 64, decision="not_now", note=None,
                       now="2026-10-16T05:00:00+00:00")  # fmt: skip
    conn.commit()
    checks = {c.decision_id: c for c in rs.cas_decision_checks(conn)}
    assert len(checks) == 2  # only 'done' entries are checked
    by_moves = sorted(checks.values(), key=lambda c: len(c.moves))
    assert by_moves[0].moves == ()  # REDIRECT_SIP: nothing a CAS can show, so it stays UNDETERMINED
    assert by_moves[1].moves == (cas.ExpectedMove("mf:synthetic-1", "in"), cas.ExpectedMove("mf:synthetic-2", "out"))
    assert all(c.decided_on.isoformat() == "2026-10-16" for c in checks.values())


def test_cas_decision_checks_without_decisions_is_empty(conn: Any) -> None:
    assert rs.cas_decision_checks(conn) == []
