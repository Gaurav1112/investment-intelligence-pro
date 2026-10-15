"""Development FIXTURES — synthetic, deterministic, and loudly labelled. NOT market data (brief Phase 13).

Every fixture instrument is named "FIXTURE …", stored with origin='fixture' / quality_status='fixture', and cites a
non-routable https://fixture.invalid/ URL. The UI renders them with a hatched FIXTURE badge; personalised ranking
refuses them unless a demo explicitly opts in.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

import numpy as np

from iip.store.db import write_tx
from iip.store.observations import ObservationRow, upsert_observation

FIXTURE_URL = "https://fixture.invalid/synthetic"
SEED = 20261015


def _nav_path(start: date, end: date, *, annual: float, vol: float, shock_every: int | None, shock: float,
              rng: np.random.Generator) -> list[tuple[date, Decimal]]:  # fmt: skip
    out: list[tuple[date, Decimal]] = []
    nav = 10.0
    d = start
    i = 0
    daily = (1 + annual) ** (1 / 252) - 1
    while d <= end:
        if d.weekday() < 5:
            out.append((d, Decimal(repr(nav)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)))
            nav *= 1 + daily + vol * float(rng.standard_normal())
            if shock_every and i % shock_every == shock_every - 1:
                nav *= 1 + shock
            i += 1
        d += timedelta(days=1)
    return out


FIXTURE_FUNDS = (
    # code, name, category, annual drift, daily vol, shock cadence, shock size, exit load (days, rate)
    (900001, "FIXTURE Liquid Fund A — Direct · Growth", "Debt Scheme - Liquid Fund", 0.065, 0.00003, None, 0.0, None),
    (900002, "FIXTURE Short Duration Fund B — Direct · Growth", "Debt Scheme - Short Duration Fund", 0.072, 0.0009,
     310, -0.012, (30, "0.0025")),
    (900003, "FIXTURE Large Cap Fund C — Direct · Growth", "Equity Scheme - Large Cap Fund", 0.12, 0.011, 400, -0.18,
     (365, "0.01")),
    (900004, "FIXTURE Arbitrage Fund D — Direct · Growth", "Hybrid Scheme - Arbitrage Fund", 0.066, 0.0004, None, 0.0,
     (30, "0.0025")),
)  # fmt: skip


def seed(conn: sqlite3.Connection, *, as_of: date, now: datetime) -> list[str]:
    rng = np.random.default_rng(SEED)
    created: list[str] = []
    start = as_of - timedelta(days=365 * 14)
    end = as_of - timedelta(days=1)
    for code, name, cat, drift, vol, every, shock, load in FIXTURE_FUNDS:
        iid = f"mf:{code}"
        with write_tx(conn):
            conn.execute(
                "INSERT INTO instruments(instrument_id, kind, name, amfi_code, origin, created_at)"
                " VALUES (?, 'mf_scheme', ?, ?, 'fixture', ?) ON CONFLICT(instrument_id) DO NOTHING",
                (iid, name, str(code), now.isoformat()),
            )
            exit_json = None
            if load is not None:
                exit_json = (
                    f'{{"days": {load[0]}, "rate": "{load[1]}", "citation": "{FIXTURE_URL}/sid",'
                    f' "as_of": "{as_of.isoformat()}"}}'
                )
            conn.execute(
                "INSERT INTO mf_schemes(instrument_id, amc, category_raw, sebi_category, plan, option_type,"
                " exit_load_json) VALUES (?, 'FIXTURE AMC', ?, ?, 'direct', 'Growth', ?)"
                " ON CONFLICT(instrument_id) DO NOTHING",
                (iid, cat, cat, exit_json),
            )
        for d, nav in _nav_path(start, end, annual=drift, vol=vol, shock_every=every, shock=shock, rng=rng):
            upsert_observation(conn, ObservationRow(
                series_id=f"nav:{code}", kind="nav", value=format(nav, "f"), unit="INR/unit", currency="INR",
                observation_date=d.isoformat(), retrieved_at=now.isoformat(), source_id="fixture",
                source_url=FIXTURE_URL, quality_status="fixture", raw_sha256="f" * 64, convention="synthetic NAV",
            ))  # fmt: skip
        created.append(iid)

    tb = f"tbill:182d:{(as_of + timedelta(days=180)).isoformat()}"
    with write_tx(conn):
        conn.execute(
            "INSERT INTO issuers(issuer_id, name, issuer_type) VALUES ('goi', 'Government of India', 'sovereign')"
            " ON CONFLICT(issuer_id) DO NOTHING"
        )
        conn.execute(
            "INSERT INTO instruments(instrument_id, kind, name, issuer_id, origin, created_at)"
            " VALUES (?, 'tbill', 'FIXTURE 182-day T-bill', 'goi', 'fixture', ?) ON CONFLICT DO NOTHING",
            (tb, now.isoformat()),
        )
        conn.execute(
            "INSERT INTO bond_terms(instrument_id, face_value, coupon_rate, coupon_freq, maturity_date, daycount,"
            " listed, credit_rating) VALUES (?, '100', '0', 0, ?, 'ACT/365F', 1, 'SOVEREIGN') ON CONFLICT DO NOTHING",
            (tb, (as_of + timedelta(days=180)).isoformat()),
        )
    upsert_observation(conn, ObservationRow(
        series_id=f"yield:{tb}", kind="yield", value="0.0650", unit="fraction", currency=None,
        observation_date=as_of.isoformat(), retrieved_at=now.isoformat(), source_id="fixture",
        source_url=FIXTURE_URL, quality_status="fixture", raw_sha256="f" * 64, convention="money-market, ACT/365",
    ))  # fmt: skip
    created.append(tb)

    fd = "fd:fixture-bank:180d"
    with write_tx(conn):
        conn.execute(
            "INSERT INTO instruments(instrument_id, kind, name, origin, created_at)"
            " VALUES (?, 'fd', 'FIXTURE Bank FD — 180 days', 'fixture', ?) ON CONFLICT DO NOTHING",
            (fd, now.isoformat()),
        )
        conn.execute(
            "INSERT INTO deposit_terms(instrument_id, institution, rate, compounding, tenure_days, premature_penalty,"
            " dicgc_eligible, rate_as_of, citation_url)"
            " VALUES (?, 'FIXTURE Bank', '0.0700', 'quarterly', 180, '0.0100', 1, ?, ?) ON CONFLICT DO NOTHING",
            (fd, as_of.isoformat(), FIXTURE_URL),
        )
        # The synthetic investor states ₹0 at this fictional bank (an unstated figure blocks the DICGC check).
        conn.execute(
            "INSERT INTO settings(key, value_json) VALUES (?, '\"0\"') ON CONFLICT DO NOTHING", (f"fd.existing:{fd}",)
        )
    created.append(fd)
    return created
