"""Red team (Phase 14): end-to-end Discovery attacks — misdated data, duplicate sources, name injection, preferences.

All instrument values are TEST inputs entered through the same service functions the API uses; none is market data.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from iip.rules.loader import load_tax_rules
from iip.services import discovery as disc
from iip.services import fixtures
from iip.services.instruments import Citation, FDIn, TBillIn, add_fd, add_tbill
from iip.services.profile import Profile, evaluate
from iip.store.db import connect, migrate

AS_OF = date(2026, 10, 15)
NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
RULES = load_tax_rules()
CITE_URL = "https://example.test/rates"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[Any]:
    c = connect(tmp_path / "rt.db")
    migrate(c, NOW.isoformat())
    yield c
    c.close()


def profile(**kw: object) -> Profile:
    base: dict[str, object] = {
        "amount": "100000",
        "withdrawal_date": "2027-04-15",
        "objective": "A_capital_preservation",
        "loss_acceptable": False,
        "early_need": "possible",
    }
    base.update(kw)
    return Profile.model_validate(base)


def go(conn: Any, p: Profile) -> dict[str, Any]:
    return disc.discover(conn, evaluate(p, AS_OF), as_of=AS_OF, ruleset=RULES)


def rows(out: dict[str, Any], prefix: str) -> list[dict[str, Any]]:
    return [r for r in out["ranked"] + out["excluded"] if r["instrument_id"].startswith(prefix)]


def fd(conn: Any, institution: str, kind: str = "bank", as_of: date = AS_OF, rate: str = "0.07") -> str:
    body = FDIn(
        institution=institution, institution_type=kind,  # type: ignore[arg-type]
        rate=Decimal(rate), tenure_days=90, premature_penalty=Decimal("0.01"),
        existing_deposits_at_institution=Decimal(0),  # stated, not assumed (ECC F1)
        citation=Citation(url=CITE_URL, as_of=as_of),
    )  # fmt: skip
    return add_fd(conn, body, NOW)


def tbill(conn: Any, as_of: date, y: str, maturity: date = date(2027, 1, 14)) -> str:
    body = TBillIn(
        name="91-day T-bill (TEST)", tenor="91", maturity=maturity, yield_fraction=Decimal(y),
        citation=Citation(url=CITE_URL, as_of=as_of),
    )  # fmt: skip
    return add_tbill(conn, body, NOW)


# --------------------------------------------------------------------------------------------- RT-04
def test_rt04_future_dated_fd_rate_never_reaches_ranking(conn: Any) -> None:
    """A rate 'as of' 2030 (a typo) has a negative age, so the > 30-day staleness test never fired."""
    fd(conn, "Typo Bank", as_of=date(2030, 1, 1))
    out = go(conn, profile())
    assert [r["instrument_id"] for r in out["ranked"]] == []
    (row,) = rows(out, "fd:")
    assert any(c.startswith("LOOK_AHEAD") for c in row["exclusion_codes"]), row


def test_rt04_future_dated_tbill_yield_never_reaches_ranking(conn: Any) -> None:
    tbill(conn, date(2026, 12, 1), "0.0900")
    out = go(conn, profile())
    assert out["ranked"] == []
    (row,) = rows(out, "tbill:")
    assert any(c.startswith("LOOK_AHEAD") for c in row["exclusion_codes"]), row


def test_rt04_mistyped_future_tbill_quote_can_be_corrected(conn: Any) -> None:
    """Re-entering the correct (earlier-dated) quote must take effect; the future-dated row must not win forever."""
    tbill(conn, date(2027, 10, 10), "0.0900")
    tbill(conn, date(2026, 10, 14), "0.0560")
    out = go(conn, profile())
    (row,) = rows(out, "tbill:")
    assert row["rank"] == 1 and row["observed"] == "2026-10-14"
    assert any("5.60" in line for line in row["outcome"]["q50"]["inputs"]), row["outcome"]["q50"]["inputs"]


# --------------------------------------------------------------------------------------------- RT-02
def test_rt02_exclude_nbfc_deposits_preference_is_honoured(conn: Any) -> None:
    """Profile default exclude_nbfc_deposits=True (requirements §3.2 item 8) was never read by Discovery."""
    fd(conn, "Some Finance Ltd", kind="nbfc", rate="0.09")
    p = profile(objective="D_growth", loss_acceptable=True, max_loss_fraction="0.10", withdrawal_date="2027-10-20")
    out = go(conn, p)
    assert out["ranked"] == []
    (row,) = rows(out, "fd:")
    assert any(c.startswith("EXCLUDED_BY_USER") for c in row["exclusion_codes"]), row


def test_rt02_nbfc_deposit_allowed_when_user_opts_in_but_flagged(conn: Any) -> None:
    fd(conn, "Some Finance Ltd", kind="nbfc", rate="0.09")
    p = profile(objective="D_growth", loss_acceptable=True, max_loss_fraction="0.10", withdrawal_date="2027-10-20",
                exclude_nbfc_deposits=False)  # fmt: skip
    out = go(conn, p)
    (row,) = rows(out, "fd:")
    assert row["rank"] == 1 and "NOT_DICGC_INSURED" in row["flags"]


def test_rt01_nbfc_deposit_not_ranked_for_capital_preservation_end_to_end(conn: Any) -> None:
    fd(conn, "Some Finance Ltd", kind="nbfc", rate="0.09")
    out = go(conn, profile(exclude_nbfc_deposits=False))
    assert out["ranked"] == []
    (row,) = rows(out, "fd:")
    assert "UNINSURED_CREDIT_EXPOSURE" in row["exclusion_codes"]


# --------------------------------------------------------------------------------------------- RT-05
@pytest.mark.parametrize("institution", ["Assured Returns Bank", "Guaranteed Growth Bank", "SEBI-approved Bank"])
def test_rt05_banned_phrase_in_instrument_name_does_not_crash_discovery(conn: Any, institution: str) -> None:
    """Names are user/source DATA. A banned phrase inside one raised ComplianceViolation → HTTP 500 for every run."""
    fd(conn, institution)
    out = go(conn, profile())
    assert out["status"] == "RANKED"
    assert out["report"] is not None and institution in out["report"]["narrative"]


def test_rt05_banned_phrase_in_our_own_template_copy_still_fails_loudly() -> None:
    from iip.supervisor.contracts import Claim, Stance, WorkerContract, WorkerStatus
    from iip.supervisor.facts import Fact, FactOrigin, FactSheet
    from iip.supervisor.synthesis import ComplianceViolation, build_report

    facts = FactSheet()
    facts.add(Fact("amount", "₹1,00,000.00", FactOrigin.USER_INPUT))
    claim = Claim("c", "x", "t", Stance.NEUTRAL, "{fact:amount} is risk-free.", cites=("amount",))
    with pytest.raises(ComplianceViolation):
        build_report([WorkerContract("w", WorkerStatus.ANSWERED, claims=(claim,))], facts, [], ())


# --------------------------------------------------------------------------------------------- RT-06
def test_rt06_same_tbill_from_fixture_and_manual_source_does_not_crash(conn: Any) -> None:
    """Fixture T-bill and a manual quote for the same tenor/maturity share an id; two same-date rows → duplicate ids
    → ranking raised InvalidInput (HTTP 500)."""
    fixtures.seed(conn, as_of=AS_OF, now=NOW)
    maturity = AS_OF + timedelta(days=180)
    body = TBillIn(
        name="182-day T-bill (TEST)", tenor="182", maturity=maturity, yield_fraction=Decimal("0.0580"),
        citation=Citation(url=CITE_URL, as_of=AS_OF),
    )  # fmt: skip
    add_tbill(conn, body, NOW)
    out = go(conn, profile())
    assert len(rows(out, "tbill:")) == 1


# --------------------------------------------------------------------------------------------- RT-15
def test_rt15_reentered_fd_rate_carries_its_own_entry_time(conn: Any) -> None:
    """Re-entering an FD 20 days later kept the first entry's timestamp: 'retrieved' before the date it describes."""
    first = FDIn(
        institution="Prov Bank", institution_type="bank", rate=Decimal("0.07"), tenure_days=90,
        premature_penalty=Decimal("0.01"), citation=Citation(url=CITE_URL, as_of=date(2026, 9, 25)),
    )  # fmt: skip
    add_fd(conn, first, datetime(2026, 9, 25, 6, 0, tzinfo=UTC))
    second = first.model_copy(update={"rate": Decimal("0.0725"), "citation": Citation(url=CITE_URL, as_of=AS_OF)})
    add_fd(conn, second, NOW)
    (row,) = rows(go(conn, profile()), "fd:")
    src = row["outcome"]["q50"]["sources"][0]
    assert src["observation_date"] == AS_OF.isoformat()
    assert src["retrieved_at"] == NOW.isoformat()
