"""Red team RT-22: fund windows must end when the proceeds are actually available; T-bill tickets and lots.

Every instrument value here is a hand-built TEST input, not market data.
"""

from datetime import date, timedelta
from decimal import Decimal

from iip.engine import candidates as cb
from iip.engine.feasibility import percentile_type7
from iip.engine.money import D, engine_context
from iip.engine.ranking import Objective, RankingRequest, rank
from iip.rules.loader import load_tax_rules
from tests.unit.test_candidates import FULL_SPAN, PROFILE_30, _liquid, _series

RULES = load_tax_rules()
AS_OF = date(2026, 10, 15)


def _inputs(b: cb.BuiltCandidate) -> dict[str, str]:
    assert b.evidence is not None
    return dict(b.evidence.inputs)


# ---------------------------------------------------------------------------------------------- RT-22 (a)


def test_rt22a_nav_window_is_horizon_minus_settlement() -> None:
    """H = 30 days, T+3 settlement → the NAV window is 27 days, so proceeds arrive by the withdrawal date. With a
    strictly rising series a 27-day window earns less than a 30-day one; the band must equal the 27-day windows."""
    ds, ns = _series(date(2012, 1, 2), FULL_SPAN, "0.00025")
    b = _liquid(nav_dates=ds, navs=ns, withdrawal=AS_OF + timedelta(days=30), settlement_days=3)
    assert not b.ineligible_reasons, b.ineligible_reasons
    assert _inputs(b)["nav_window_days"] == "27"
    assert _inputs(b)["redemption_date"] == (AS_OF + timedelta(days=27)).isoformat()
    want = cb.horizon_window_returns(ds, ns, 27)
    full = cb.horizon_window_returns(ds, ns, 30)
    assert b.evidence is not None and b.evidence.band_gross is not None
    with engine_context():
        invested = D("100000") - D("100000") * D("0.00005") / D("1.00005")
        assert b.evidence.band_gross[1] == invested * (D(1) + percentile_type7(want, D("0.50")))
        assert percentile_type7(want, D("0.50")) < percentile_type7(full, D("0.50"))
    assert b.evidence.n_windows == len(want)


def test_rt22a_redemption_date_drives_holding_period_for_tax() -> None:
    """Equity fund, H = 366 days with T+1: units are redeemed on day 365 = exactly 12 months → STCG, even though the
    withdrawal date itself is past 12 months. Using the withdrawal date would understate tax (LTCG 12.5 %)."""
    ds, ns = _series(date(2012, 1, 2), FULL_SPAN, "0.0006")
    b = _liquid(category="Equity Scheme - Large Cap Fund", nav_dates=ds, navs=ns, amount=D("2000000"),
                withdrawal=AS_OF + timedelta(days=366), settlement_days=1,
                exit_load=cb.ExitLoadSpec(30, D("0.01"), "SID FIXTURE"))  # fmt: skip
    assert not b.ineligible_reasons, b.ineligible_reasons
    assert b.evidence is not None
    cg_rules = [r for r in b.evidence.tax_rule_ids if "CG" in r]
    assert cg_rules and all("STCG" in r for r in cg_rules), b.evidence.tax_rule_ids
    assert "LTCG_EXEMPTION_ASSUMED_UNUSED" not in b.candidate.flags


def test_rt22a_exit_load_judged_on_the_redemption_day() -> None:
    """Exit load for redemptions within 30 days; H = 31, T+2 → redeemed on day 29 → the load applies."""
    ds, ns = _series(date(2012, 1, 2), FULL_SPAN, "0.00025")
    b = _liquid(category="Debt Scheme - Money Market Fund", nav_dates=ds, navs=ns,
                withdrawal=AS_OF + timedelta(days=31), settlement_days=2,
                exit_load=cb.ExitLoadSpec(30, D("0.005"), "SID FIXTURE"))  # fmt: skip
    assert not b.ineligible_reasons, b.ineligible_reasons
    assert b.evidence is not None and dict(b.evidence.costs)["exit_load_rate"] == D("0.005")


# ---------------------------------------------------------------------------------------------- RT-22 (b)


def _tbill(amount: Decimal, **kw: object) -> cb.BuiltCandidate:
    args: dict[str, object] = dict(
        instrument_id="tb", name="182-day T-bill (TEST)", amount=amount, quoted_yield=D("0.065"),
        settlement=date(2026, 10, 16), maturity=date(2027, 4, 15), withdrawal=date(2027, 4, 15),
        ruleset=RULES, profile=PROFILE_30,
    )  # fmt: skip
    args.update(kw)
    return cb.tbill_candidate(**args)  # type: ignore[arg-type]


def _lot_cost() -> Decimal:
    with engine_context():
        price = D(100) / (D(1) + D("0.065") * D(181) / D(365))
        return D(10000) * price / D(100)


def test_rt22b_rbi_minimum_is_10000_face_in_multiples_of_10000() -> None:
    assert cb.TBILL_MIN_FACE_INR == D(10000) and cb.TBILL_LOT_FACE_INR == D(10000)
    assert "RBI/2021-2022/124" in cb.TBILL_MIN_TICKET_SOURCE


def test_rt22b_tbill_below_minimum_ticket_is_ineligible() -> None:
    """₹1 used to "buy" a fractional T-bill. Now: below the cost of one ₹10,000 lot → BELOW_MINIMUM_TICKET, both from
    the builder and from ranking's own min_investment check."""
    for amount in (D("1"), _lot_cost() - D("0.01")):
        b = _tbill(amount)
        assert b.ineligible_reasons and b.ineligible_reasons[0].startswith("BELOW_MINIMUM_TICKET"), amount
        assert b.candidate.min_investment == _lot_cost()
        res = rank(RankingRequest(objective=Objective.CAPITAL_PRESERVATION, amount=amount, horizon_days=181),
                   [b.candidate])  # fmt: skip
        assert not res.ranked
        assert "BELOW_MINIMUM_TICKET" in res.excluded[0].reason_codes


def test_rt22b_exactly_one_lot_is_eligible() -> None:
    b = _tbill(_lot_cost())
    assert not b.ineligible_reasons, b.ineligible_reasons
    assert _inputs(b)["lots"] == "1" and Decimal(_inputs(b)["face_value"]) == D(10000)
    assert "UNINVESTED_REMAINDER_AT_ZERO" not in b.candidate.flags


def test_rt22b_tbill_face_in_whole_lots_and_leftover_cash_at_zero() -> None:
    """₹1,00,000 at 6.5 % for 181 days: one ₹10,000 lot costs ₹9,687.7…, so 10 lots (face ₹1,00,000) are bought and the
    ₹3,122.… remainder is held as cash at 0 % and flagged. Tax is on the discount only (face − cost)."""
    b = _tbill(D("100000"))
    assert not b.ineligible_reasons, b.ineligible_reasons
    inp = _inputs(b)
    assert inp["lots"] == "10" and Decimal(inp["face_value"]) == D("100000")
    with engine_context():
        cost = _lot_cost() * 10
        leftover = D("100000") - cost
        assert Decimal(inp["uninvested_cash"]) == leftover
        assert b.evidence is not None and b.evidence.gross_end_value == D("100000") + leftover
    assert b.evidence.tax_mid == (b.evidence.tax_mid.quantize(D("0.01")))
    with engine_context():
        assert abs(b.evidence.tax_mid - (D("100000") - cost) * D("0.312")) <= D("0.01")
    assert "UNINVESTED_REMAINDER_AT_ZERO" in b.candidate.flags
    assert b.candidate.min_investment == _lot_cost()
