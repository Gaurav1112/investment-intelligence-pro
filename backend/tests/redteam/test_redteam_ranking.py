"""Red team (Phase 14): risk tiers, credit and evidence gates in candidate building and ranking.

Every instrument value here is a hand-built TEST input, not market data.
"""

from datetime import date, timedelta
from decimal import Decimal

from iip.engine import candidates as cb
from iip.engine.money import D, engine_context
from iip.engine.ranking import Objective, RankingRequest, RankStatus, Tier, rank
from iip.rules.loader import load_tax_rules

RULES = load_tax_rules()
AS_OF = date(2026, 10, 15)
WITHDRAW = date(2027, 4, 15)
AMOUNT = D("100000")
PRESERVING = (Objective.CAPITAL_PRESERVATION, Objective.INCOME, Objective.LIQUIDITY)


def _fd(**kw: object) -> cb.BuiltCandidate:
    args: dict[str, object] = dict(
        instrument_id="fd:test",
        name="TEST deposit",
        amount=AMOUNT,
        rate=D("0.09"),
        start=AS_OF,
        tenure_days=180,
        withdrawal=WITHDRAW,
        dicgc_eligible=False,
        premature_penalty=D("0.01"),
        other_deposits_same_bank=D("0"),
        ruleset=RULES,
        profile=None,
    )
    args.update(kw)
    return cb.fd_candidate(**args)  # type: ignore[arg-type]


def _weekday_series(start: date, end: date, daily: str) -> tuple[list[date], list[Decimal]]:
    ds: list[date] = []
    ns: list[Decimal] = []
    nav = D("10")
    d = start
    with engine_context():
        while d <= end:
            if d.weekday() < 5:
                ds.append(d)
                ns.append(nav)
                nav = nav * (D("1") + D(daily))
            d += timedelta(days=1)
    return ds, ns


# --------------------------------------------------------------------------------------------- RT-01
def test_rt01_uninsured_deposit_is_not_capital_preserving() -> None:
    """An NBFC deposit (no DICGC cover, unquantified credit risk) must not pass a preservation objective."""
    nbfc = _fd(dicgc_eligible=False)
    for objective in PRESERVING:
        result = rank(RankingRequest(objective=objective, amount=AMOUNT, horizon_days=182), [nbfc.candidate])
        assert result.status is RankStatus.NO_SUITABLE_CANDIDATE, objective
        assert "UNINSURED_CREDIT_EXPOSURE" in result.excluded[0].reason_codes


def test_rt01_deposit_above_dicgc_cover_including_interest_is_not_capital_preserving() -> None:
    """₹5,00,000 principal at a bank: principal + interest exceeds the ₹5 lakh cover → part is bank credit risk."""
    big = _fd(amount=D("500000"), rate=D("0.07"), dicgc_eligible=True)
    assert "EXCEEDS_DICGC_LIMIT_AT_THIS_BANK" in big.candidate.flags
    result = rank(
        RankingRequest(objective=Objective.CAPITAL_PRESERVATION, amount=D("500000"), horizon_days=182), [big.candidate]
    )
    assert result.status is RankStatus.NO_SUITABLE_CANDIDATE


def test_rt01_dicgc_boundary_exactly_at_cover_is_insured() -> None:
    """Exposure exactly ₹5,00,000 (existing deposits + maturity value) is fully covered — boundary is inclusive."""
    probe = _fd(dicgc_eligible=True, rate=D("0.07"))
    assert probe.evidence is not None and probe.evidence.gross_end_value is not None
    with engine_context():
        existing = D("500000") - probe.evidence.gross_end_value
    at = _fd(dicgc_eligible=True, rate=D("0.07"), other_deposits_same_bank=existing)
    assert at.candidate.tier is Tier.T2 and at.candidate.loss_frequency == 0
    with engine_context():
        over = _fd(dicgc_eligible=True, rate=D("0.07"), other_deposits_same_bank=existing + D("0.01"))
    assert over.candidate.tier is Tier.T3 and "EXCEEDS_DICGC_LIMIT_AT_THIS_BANK" in over.candidate.flags
    result = rank(RankingRequest(objective=Objective.CAPITAL_PRESERVATION, amount=AMOUNT, horizon_days=182),
                  [at.candidate])  # fmt: skip
    assert result.status is RankStatus.RANKED


def test_rt01_credit_floor_applies_to_uninsured_deposit() -> None:
    """A user's credit floor must exclude an unrated, uninsured deposit even for a growth objective."""
    nbfc = _fd(dicgc_eligible=False)
    result = rank(
        RankingRequest(objective=Objective.GROWTH, amount=AMOUNT, horizon_days=400, loss_budget=D("0.1"),
                       credit_floor="AA"),
        [nbfc.candidate],
    )  # fmt: skip
    assert result.status is RankStatus.NO_SUITABLE_CANDIDATE
    assert "BELOW_CREDIT_FLOOR" in result.excluded[0].reason_codes


def test_rt01_insured_deposit_still_ranks_for_preservation() -> None:
    ok = _fd(dicgc_eligible=True, rate=D("0.07"))
    result = rank(RankingRequest(objective=Objective.CAPITAL_PRESERVATION, amount=AMOUNT, horizon_days=182,
                                 credit_floor="AAA"), [ok.candidate])  # fmt: skip
    assert result.status is RankStatus.RANKED


def test_rt01_credit_risk_fund_fails_any_credit_floor() -> None:
    """SEBI 'Credit Risk Fund': ≥ 65 % in paper rated AA and below by mandate; a smooth NAV must not pass a floor."""
    ds, ns = _weekday_series(date(2012, 1, 2), AS_OF - timedelta(days=1), "0.0003")
    b = cb.mf_candidate(
        instrument_id="mf:credit", name="TEST Credit Risk Fund", category="Debt Scheme - Credit Risk Fund",
        amount=AMOUNT, as_of=AS_OF, withdrawal=WITHDRAW, nav_dates=ds, navs=ns,
        exit_load=cb.ExitLoadSpec(days=365, rate=D("0.01"), citation="TEST"), ruleset=RULES, profile=None,
        settlement_days=3,
    )  # fmt: skip
    assert b.evidence is not None
    result = rank(RankingRequest(objective=Objective.CAPITAL_PRESERVATION, amount=AMOUNT, horizon_days=182,
                                 credit_floor="AA"), [b.candidate])  # fmt: skip
    assert result.status is RankStatus.NO_SUITABLE_CANDIDATE
    assert "BELOW_CREDIT_FLOOR" in result.excluded[0].reason_codes


# --------------------------------------------------------------------------------------------- RT-03
def test_rt03_equity_fund_with_short_lucky_history_is_suppressed() -> None:
    """100 days of a steadily rising equity NAV and a 7-day horizon: 14 'independent' windows, zero losses.

    validation-methodology §8: a newly launched instrument (< 1 year of history) is SUPPRESSED. Before the fix this
    fund was ranked first for CAPITAL PRESERVATION.
    """
    ds, ns = _weekday_series(AS_OF - timedelta(days=100), AS_OF - timedelta(days=1), "0.001")
    b = cb.mf_candidate(
        instrument_id="mf:new", name="TEST New Equity Fund", category="Equity Scheme - Large Cap Fund",
        amount=AMOUNT, as_of=AS_OF, withdrawal=AS_OF + timedelta(days=7), nav_dates=ds, navs=ns,
        exit_load=cb.ExitLoadSpec(days=0, rate=D("0"), citation="TEST"), ruleset=RULES, profile=None,
        settlement_days=3,
    )  # fmt: skip
    assert b.evidence is None
    assert any(r.startswith("INSUFFICIENT_HISTORY") for r in b.ineligible_reasons)
    result = rank(RankingRequest(objective=Objective.CAPITAL_PRESERVATION, amount=AMOUNT, horizon_days=7),
                  [b.candidate])  # fmt: skip
    assert result.status is RankStatus.NO_SUITABLE_CANDIDATE


def test_rt03_one_ancient_nav_does_not_manufacture_independent_windows() -> None:
    """A single 2012 NAV followed by ~4 months of recent NAVs spans 14 years, but holds ~3 independent 30-day windows.

    Counting independence as span // H claimed > 160 windows and produced a full '5th percentile' band.
    """
    ds, ns = _weekday_series(AS_OF - timedelta(days=130), AS_OF - timedelta(days=1), "0.0002")
    ds = [date(2012, 1, 2), *ds]
    ns = [D("5"), *ns]
    b = cb.mf_candidate(
        instrument_id="mf:gappy", name="TEST Liquid Fund", category="Debt Scheme - Liquid Fund",
        amount=AMOUNT, as_of=AS_OF, withdrawal=AS_OF + timedelta(days=30), nav_dates=ds, navs=ns,
        exit_load=None, ruleset=RULES, profile=None, settlement_days=1,
    )  # fmt: skip
    assert b.evidence is None, b.evidence and b.evidence.n_independent
    assert any(r.startswith("INSUFFICIENT_HISTORY") for r in b.ineligible_reasons)


def test_rt03_long_continuous_history_still_evaluated_with_full_band() -> None:
    ds, ns = _weekday_series(date(2012, 1, 2), AS_OF - timedelta(days=1), "0.0002")
    b = cb.mf_candidate(
        instrument_id="mf:liq", name="TEST Liquid Fund", category="Debt Scheme - Liquid Fund",
        amount=AMOUNT, as_of=AS_OF, withdrawal=WITHDRAW, nav_dates=ds, navs=ns,
        exit_load=None, ruleset=RULES, profile=None, settlement_days=1,
    )  # fmt: skip
    assert b.evidence is not None and b.evidence.n_independent is not None
    assert b.evidence.n_independent == (ds[-1] - ds[0]).days // 182
    assert b.evidence.lower_band_method == "5th percentile of overlapping windows"


# --------------------------------------------------------------------------------------------- RT-08
def test_rt08_liquid_fund_graded_exit_load_is_0_0070_percent_not_0_70_percent() -> None:
    """SEBI 20-Sep-2019: day-1 liquid-fund exit load is 0.0070 % of proceeds (research doc §1.2), i.e. 0.000070."""
    load = cb.sebi_default_exit_load("Debt Scheme - Liquid Fund")
    assert load is not None and load.days == 6
    assert load.rate == D("0.000070")


# --------------------------------------------------------------------------------------------- RT-14
def test_rt14_fund_cannot_deliver_cash_by_a_withdrawal_inside_its_settlement_cycle() -> None:
    """Withdrawal tomorrow: a liquid fund redeemed tomorrow pays out T+1 — after the date the cash is needed.

    Before the fix it was ranked first for a 1-day capital-preservation goal."""
    ds, ns = _weekday_series(date(2012, 1, 2), AS_OF - timedelta(days=1), "0.0002")
    for horizon, settle in ((1, 1), (3, 3), (2, 3)):
        b = cb.mf_candidate(
            instrument_id="mf:liq", name="TEST Liquid Fund", category="Debt Scheme - Liquid Fund",
            amount=AMOUNT, as_of=AS_OF, withdrawal=AS_OF + timedelta(days=horizon), nav_dates=ds, navs=ns,
            exit_load=None, ruleset=RULES, profile=None, settlement_days=settle,
        )  # fmt: skip
        assert b.evidence is None, (horizon, settle)
        assert any(r.startswith("HORIZON_MISMATCH") and "settle" in r for r in b.ineligible_reasons)
    ok = cb.mf_candidate(
        instrument_id="mf:liq", name="TEST Liquid Fund", category="Debt Scheme - Liquid Fund",
        amount=AMOUNT, as_of=AS_OF, withdrawal=AS_OF + timedelta(days=2), nav_dates=ds, navs=ns,
        exit_load=None, ruleset=RULES, profile=None, settlement_days=1,
    )  # fmt: skip
    assert ok.evidence is not None
