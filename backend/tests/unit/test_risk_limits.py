"""L4 limits (design-risk-first.md §5.5).  All holdings, AMCs and issuers are FICTIONAL."""

from __future__ import annotations

from datetime import date

import pytest

from iip.engine.deposits import DepositHolding, InstitutionType
from iip.engine.errors import InvalidInput
from iip.engine.money import D
from iip.engine.risk import Outcome, RiskClass, Status
from iip.engine.risk.limits import LimitHolding, LimitKind, LimitParams, check_limits

ALL = LimitParams(c_scheme=D("0.30"), c_amc=D("0.40"), c_theme=D("0.10"), c_factor=D("0.20"), c_issuer=D("0.05"))


def mf(hid: str, mv: str, amc: str, **kw: object) -> LimitHolding:
    return LimitHolding(hid, kw.pop("rc", RiskClass.EQ_BROAD), D(mv), scheme_id=hid, amc=amc, **kw)  # type: ignore[arg-type]


def test_within_all_limits_passes() -> None:
    hs = [mf("s1", "25", "amc-a"), mf("s2", "25", "amc-b"), mf("s3", "25", "amc-c"), mf("s4", "25", "amc-d")]
    r = check_limits(hs, ALL)
    assert r.outcome is Outcome.PASS
    assert r.findings == ()
    assert r.status is Status.VERIFIED
    assert r.rule_id == "risk.limits@1"


def test_scheme_and_amc_breaches_are_actions() -> None:
    hs = [mf("s1", "35", "amc-a"), mf("s2", "10", "amc-a"), mf("s3", "30", "amc-b"), mf("s4", "25", "amc-c")]
    r = check_limits(hs, ALL)
    assert r.outcome is Outcome.ACTION
    got = {(f.kind, f.key, f.share) for f in r.findings}
    assert (LimitKind.SCHEME, "s1", D("0.35")) in got
    assert (LimitKind.AMC, "amc-a", D("0.45")) in got
    assert all(f.outcome is Outcome.ACTION for f in r.findings)


def test_share_exactly_at_cap_is_allowed() -> None:
    hs = [mf("s1", "30", "amc-a"), mf("s2", "30", "amc-b"), mf("s3", "40", "amc-c")]
    r = check_limits(hs, LimitParams(c_scheme=D("0.40")))
    assert not any(f.kind is LimitKind.SCHEME for f in r.findings)


def test_theme_factor_and_issuer_limits() -> None:
    hs = [
        mf("t", "15", "amc-a", rc=RiskClass.EQ_SECTOR_THEMATIC, theme="theme-x"),
        mf("f", "20", "amc-b", rc=RiskClass.EQ_FACTOR, is_factor=True),
        mf("e", "45", "amc-c"),
        LimitHolding("fd", RiskClass.CASH_LIKE, D("20"), uninsured_issuer="issuer-z"),
    ]
    r = check_limits(hs, ALL)
    kinds = {f.kind: f for f in r.findings}
    assert kinds[LimitKind.THEME].share == D("0.15")
    assert kinds[LimitKind.FACTOR].share == D("0.25")  # 20 / equity 80, not / total
    assert kinds[LimitKind.ISSUER].share == D("0.20")
    assert r.equity_value == D("80")


def test_unconfigured_limits_abstain_and_never_invent_a_default() -> None:
    hs = [mf("s1", "90", "amc-a"), mf("s2", "10", "amc-b")]
    r = check_limits(hs, LimitParams())
    assert r.outcome is Outcome.ABSTAIN
    assert r.findings == ()
    assert r.status is Status.REQUIRES_CONFIGURATION
    assert {a.missing_input for a in r.abstentions} == {"scheme limit", "amc limit"}


def test_breach_dominates_abstention() -> None:
    hs = [mf("s1", "90", "amc-a"), mf("s2", "10", "amc-b")]
    r = check_limits(hs, LimitParams(c_scheme=D("0.5")))
    assert r.outcome is Outcome.ACTION
    assert r.abstentions  # the AMC limit is still reported as not configured


def test_bank_deposit_above_dicgc_cover_is_an_action() -> None:
    deposits = [
        DepositHolding("bank-a", InstitutionType.BANK, "me", D("450000"), D("60000")),
        DepositHolding("bank-b", InstitutionType.BANK, "me", D("100000"), D("0")),
    ]
    r = check_limits([], LimitParams(), deposits=deposits, as_of=date(2026, 1, 1))
    assert r.outcome is Outcome.ACTION
    (f,) = r.findings
    assert f.kind is LimitKind.BANK_DEPOSIT
    assert f.key == "bank-a"
    assert f.exposure == D("510000")
    assert f.cap == D("500000")
    with pytest.raises(InvalidInput):
        check_limits([], LimitParams(), deposits=deposits)


def test_empty_portfolio_passes() -> None:
    assert check_limits([], ALL).outcome is Outcome.PASS


@pytest.mark.parametrize("cap", ["0", "-0.1", "1.1"])
def test_invalid_caps_rejected(cap: str) -> None:
    with pytest.raises(InvalidInput):
        check_limits([], LimitParams(c_scheme=D(cap)))


def test_negative_value_rejected() -> None:
    with pytest.raises(InvalidInput):
        check_limits([mf("s", "-1", "a")], ALL)
