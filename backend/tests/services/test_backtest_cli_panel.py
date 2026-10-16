"""SIG-3: the local backtest CLI builds its NAV panel through the TA-2 date-window helper (``align_panel``).

Undated rows are excluded and COUNTED (never a crash, never guessed); two rows of one role on one date with different
NAVs make the CLI abstain with a code (never a silent last-wins). All codes, NAVs and sources are SYNTHETIC.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from iip import backtest_cli
from iip.store import ledger
from iip.store.db import connect, migrate

NOW = "2026-10-16T05:00:00+00:00"
ROLES = ("index_fund.fictional.direct", "liquid_fund.fictional.direct")


@pytest.fixture
def conn(tmp_path: Path) -> Any:
    c = connect(tmp_path / "iip.db")
    migrate(c, NOW)
    for n, role in enumerate(ROLES, 1):
        iid, code = f"mf:97300{n}", f"97300{n}"
        c.execute(
            "INSERT INTO instruments(instrument_id, kind, name, amfi_code, origin, created_at)"
            " VALUES (?, 'mf_scheme', ?, ?, 'fixture', ?)",
            (iid, f"Fictional Fund {n}", code, NOW),
        )
        ledger.bind_roles(c, [ledger.RoleBinding(role=role, instrument_id=iid, rule_of_choice="fixture", bound_at=NOW)])
        for k in range(5):
            _nav(c, code, (date(2026, 1, 1) + timedelta(days=k)).isoformat(), str(100 + n + k))
    yield c
    c.close()


def _nav(c: Any, code: str, on: str, value: str, source: str = "amfi.navall") -> None:
    c.execute(
        "INSERT INTO observations(series_id, kind, value, unit, currency, observation_date, retrieved_at, source_id,"
        " source_url, quality_status, raw_sha256) VALUES (?, 'nav', ?, 'INR', 'INR', ?, ?, ?,"
        " 'https://example.invalid/fixture', 'fixture', ?)",
        (f"nav:{code}", value, on, NOW, source, "0" * 64),
    )


def test_clean_rows_build_the_aligned_panel(conn: Any) -> None:
    panel, prov, excluded = backtest_cli.load_panel(conn, ROLES)
    assert len(panel.dates) == 5 and panel.dates[0] == date(2026, 1, 1)
    assert [p.role for p in prov] == list(ROLES)
    assert excluded == {r: 0 for r in ROLES}


def test_an_undated_row_is_excluded_and_counted_not_a_crash(conn: Any) -> None:
    _nav(conn, "973001", "", "999")
    panel, _prov, excluded = backtest_cli.load_panel(conn, ROLES)
    assert len(panel.dates) == 5
    assert excluded == {ROLES[0]: 1, ROLES[1]: 0}
    assert all(v != 999 for v in panel.navs[ROLES[0]])


def test_conflicting_navs_on_one_date_abstain_with_a_code(conn: Any) -> None:
    _nav(conn, "973002", "2026-01-03", "555", source="mfapi")  # same date, different NAV, another source
    with pytest.raises(backtest_cli.Abstained) as exc:
        backtest_cli.load_panel(conn, ROLES)
    assert exc.value.code == "duplicate_nav_date"
    assert ROLES[1] in str(exc.value) and "2026-01-03" in str(exc.value)


def test_identical_repeats_from_two_sources_collapse(conn: Any) -> None:
    _nav(conn, "973002", "2026-01-03", "104", source="mfapi")  # 100 + 2 + 2: the same NAV as amfi.navall
    panel, _prov, _excluded = backtest_cli.load_panel(conn, ROLES)
    assert len(panel.dates) == 5


def test_cli_run_reports_the_abstention_code(tmp_path: Path, conn: Any, capsys: pytest.CaptureFixture[str]) -> None:
    _nav(conn, "973002", "2026-01-03", "555", source="mfapi")
    conn.commit()
    data = tmp_path  # the fixture's database is tmp_path / "iip.db"
    ledger.bind_roles(
        conn,
        [
            ledger.RoleBinding(role="index_fund.nifty50.direct", instrument_id="mf:973001", rule_of_choice="fixture",
                               bound_at=NOW),
            ledger.RoleBinding(role="liquid_fund.direct", instrument_id="mf:973002", rule_of_choice="fixture",
                               bound_at=NOW),
        ],
    )  # fmt: skip
    conn.commit()
    rc = backtest_cli.main(
        ["run", "S-E", "--out", str(tmp_path / "out" / "b.json"), "--created-at", NOW], {"IIP_DATA_DIR": str(data)}
    )
    assert rc == backtest_cli.EXIT_REFUSED
    assert "ABSTAIN(duplicate_nav_date)" in capsys.readouterr().err


def test_cli_run_on_a_clean_but_short_panel_abstains_with_a_code_not_a_traceback(
    tmp_path: Path, conn: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI-1: an EngineError from the run (InsufficientHistory on 5 clean dates) is an ABSTAIN with the engine's
    reason code and its own exit code, distinct from success, a refusal and an uncaught crash."""
    ledger.bind_roles(
        conn,
        [
            ledger.RoleBinding(role="index_fund.nifty50.direct", instrument_id="mf:973001", rule_of_choice="fixture",
                               bound_at=NOW),
            ledger.RoleBinding(role="liquid_fund.direct", instrument_id="mf:973002", rule_of_choice="fixture",
                               bound_at=NOW),
        ],
    )  # fmt: skip
    conn.commit()
    out = tmp_path / "out" / "b.json"
    rc = backtest_cli.main(
        ["run", "S-E", "--out", str(out), "--canary-replicates", "2", "--created-at", NOW],
        {"IIP_DATA_DIR": str(tmp_path)},
    )
    assert rc == backtest_cli.EXIT_ABSTAINED
    assert rc not in (0, 1, backtest_cli.EXIT_REFUSED)
    err = capsys.readouterr().err
    assert "ABSTAIN(INSUFFICIENT_HISTORY)" in err and "Traceback" not in err
    assert not out.exists()


def test_cli_maps_every_engine_error_to_an_abstain(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                   capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    from iip.engine.errors import EngineError, MissingData

    def boom() -> int:
        raise MissingData("synthetic: a required input is absent")

    monkeypatch.setattr(backtest_cli, "_cmd_list", boom)
    assert backtest_cli.main(["list"], {}) == backtest_cli.EXIT_ABSTAINED
    assert f"ABSTAIN({MissingData.code})" in capsys.readouterr().err
    assert issubclass(MissingData, EngineError)
