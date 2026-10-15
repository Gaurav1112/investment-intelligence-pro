"""ECC silent-failure F1: the DICGC check for a prospective FD must see deposits already recorded at the same bank.

Before the fix only the figure typed into the FD form counted, an omitted figure was read as ₹0, and FDs bought in
the user's own actual portfolios were ignored. A new FD at a bank already holding ₹4.9 L of the user's money ranked as
zero-loss insured credit. All values are TEST inputs."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from iip.rules.loader import load_tax_rules
from iip.services import analysis as an
from iip.services import discovery as disc
from iip.services import portfolio as pf
from iip.services.instruments import Citation, FDIn, add_fd
from iip.services.profile import Profile, evaluate
from iip.store.db import connect, migrate

AS_OF = date(2026, 10, 15)
NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
RULES = load_tax_rules()


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[Any]:
    c = connect(tmp_path / "x.db")
    migrate(c, NOW.isoformat())
    yield c
    c.close()


def fd(conn: Any, institution: str, tenure: int, existing: str | None = None, kind: str = "bank") -> str:
    extra = {} if existing is None else {"existing_deposits_at_institution": Decimal(existing)}
    body = FDIn(
        institution=institution, institution_type=kind, rate=Decimal("0.07"), tenure_days=tenure,  # type: ignore[arg-type]
        premature_penalty=Decimal("0.01"), citation=Citation(url="https://example.test/rates", as_of=AS_OF), **extra,
    )  # fmt: skip
    return add_fd(conn, body, NOW)


def buy(conn: Any, iid: str, amount: str, nature: str = "actual") -> None:
    pid = pf.create_portfolio(conn, pf.PortfolioIn(name=f"P {nature}", nature=nature), NOW)["portfolio_id"]  # type: ignore[arg-type]
    pf.add_transaction(conn, pid, pf.TransactionIn(instrument_id=iid, txn_date=date(2026, 10, 1), txn_type="buy",
                                                  units=amount, amount=amount), NOW)  # fmt: skip


def discover(conn: Any) -> dict[str, dict[str, Any]]:
    p = Profile.model_validate({"amount": "100000", "withdrawal_date": "2027-04-15",
                                "objective": "A_capital_preservation", "loss_acceptable": False,
                                "early_need": "possible"})  # fmt: skip
    out = disc.discover(conn, evaluate(p, AS_OF), as_of=AS_OF, ruleset=RULES)
    return {r["instrument_id"]: r for r in out["ranked"] + out["excluded"]}


def _flags(row: dict[str, Any]) -> list[str]:
    return list(row.get("flags") or []) + list(row.get("exclusion_codes") or [])


def test_portfolio_fd_at_the_same_bank_counts_towards_the_limit(conn: Any) -> None:
    held = fd(conn, "Same Bank", 365, existing="0")
    buy(conn, held, "490000.00")
    new = fd(conn, "Same Bank", 91, existing="0")  # the form figure is 0, but the book shows ₹4.9 L there
    row = discover(conn)[new]
    assert "EXCEEDS_DICGC_LIMIT_AT_THIS_BANK" in _flags(row), row
    assert new not in {r for r, v in discover(conn).items() if v.get("tier") == "T2"}


def test_hypothetical_portfolio_and_other_banks_do_not_count(conn: Any) -> None:
    other = fd(conn, "Other Bank", 365, existing="0")
    buy(conn, other, "490000.00")
    same = fd(conn, "Same Bank", 365, existing="0")
    buy(conn, same, "490000.00", nature="hypothetical")
    new = fd(conn, "Same Bank", 91, existing="0")
    row = discover(conn)[new]
    assert not any(f.startswith(("EXCEEDS_DICGC", "EXISTING_DEPOSITS")) for f in _flags(row)), row


def test_unrecorded_existing_deposits_are_flagged_not_assumed_zero(conn: Any) -> None:
    new = fd(conn, "Quiet Bank", 91)  # API call without the existing-deposits figure
    row = discover(conn)[new]
    assert "EXISTING_DEPOSITS_NOT_RECORDED" in _flags(row), row
    assert row.get("tier") != "T2"


def test_portfolio_position_counts_as_recorded(conn: Any) -> None:
    held = fd(conn, "Book Bank", 365)
    buy(conn, held, "100000.00")
    new = fd(conn, "Book Bank", 91)
    row = discover(conn)[new]
    assert not any(f.startswith(("EXCEEDS_DICGC", "EXISTING_DEPOSITS")) for f in _flags(row)), row


def test_analysis_compare_uses_the_same_exposure(conn: Any) -> None:
    held = fd(conn, "Same Bank", 365, existing="0")
    buy(conn, held, "490000.00")
    new = fd(conn, "Same Bank", 91, existing="0")
    out = an.compare(conn, as_of=AS_OF, ruleset=RULES, instrument_ids=[new, held], amount=Decimal("100000"),
                     withdrawal=date(2027, 4, 15))  # fmt: skip
    row = next(r for r in out["rows"] if r["instrument_id"] == new)
    assert "EXCEEDS_DICGC_LIMIT_AT_THIS_BANK" in row["flags"], row
