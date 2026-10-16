"""A17: backtest lot ledger, equity costs and tax lots (research-backtest-method.md §6, §7).

All instruments, dates and prices here are SYNTHETIC. The rate rows are the rule parameters recorded in
research-backtest-method.md §6.1 / §7.4 (fixtures C-1 and T-1); no market data is used.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from iip.engine.backtest import costs_equity as ce
from iip.engine.backtest import ledger as lg
from iip.engine.backtest import tax_lots as tl
from iip.engine.errors import InvalidInput
from iip.engine.money import ZERO

D = Decimal

# --- synthetic rule rows ------------------------------------------------------------------------

ROW = ce.EquityCostRow(
    rule_id="EQ-DELIVERY-COST@test",
    effective_from=date(2024, 10, 1),
    effective_to=None,
    brokerage_rate=ZERO,
    brokerage_cap_inr=None,
    stt_rate=D("0.001"),
    stt_rounding_quantum=D("1"),
    exchange_txn_rate=D("0.0000307"),
    sebi_fee_rate=D("0.000001"),  # ₹10 per crore
    stamp_rate_buy=D("0.00015"),
    gst_rate=D("0.18"),
    dp_charge_per_scrip_sell_day_inr=D("15.34"),
    status=ce.CostStatus.VERIFIED_SECONDARY,
    source="research-backtest-method.md §6.1 (synthetic test row)",
)
SCHEDULE = ce.EquityCostSchedule(rows=(ROW,), estimate_multiplier=D("1.5"))
ON = date(2025, 1, 15)

RATES = tl.TaxRateRow(
    rule_id="EQ-CG@test",
    asset_class=tl.EQUITY,
    effective_from=date(2024, 7, 23),
    effective_to=None,
    stcg_rate=D("0.20"),
    ltcg_rate=D("0.125"),
    ltcg_exemption_inr=D("125000"),
    long_term_after_months=12,
    surcharge_rate=ZERO,
    cess_rate=D("0.04"),
    grandfathering_on_or_before=date(2018, 1, 31),
    status="VERIFIED-PRIMARY",
)
TAX_TABLE = tl.TaxRateTable(rows=(RATES,))


def _round_trip(ticket: str) -> Decimal:
    buy = ce.equity_trade_cost(ce.Side.BUY, D(ticket), ON, SCHEDULE, ce.InstrumentKind.EQUITY_DELIVERY)
    sell = ce.equity_trade_cost(
        ce.Side.SELL, D(ticket), ON, SCHEDULE, ce.InstrumentKind.EQUITY_DELIVERY, first_sell_of_scrip_today=True
    )
    return buy.total_inr + sell.total_inr


# --- C-1 ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ticket", "expected"),
    [("10000", "37.58812"), ("100000", "237.8212"), ("500000", "1127.746")],
)
def test_c1_round_trip_cost(ticket: str, expected: str) -> None:
    assert _round_trip(ticket) == D(expected)


def test_c1_components_on_one_lakh() -> None:
    buy = ce.equity_trade_cost(ce.Side.BUY, D("100000"), ON, SCHEDULE, ce.InstrumentKind.EQUITY_DELIVERY)
    sell = ce.equity_trade_cost(
        ce.Side.SELL, D("100000"), ON, SCHEDULE, ce.InstrumentKind.EQUITY_DELIVERY, first_sell_of_scrip_today=True
    )
    assert buy.components["stt"] == D("100") and sell.components["stt"] == D("100")
    assert buy.components["exchange_txn"] + sell.components["exchange_txn"] == D("6.14")
    assert buy.components["sebi_fee"] + sell.components["sebi_fee"] == D("0.2")
    assert buy.components["stamp"] == D("15") and sell.components["stamp"] == ZERO
    assert buy.components["gst"] + sell.components["gst"] == D("1.1412")
    assert buy.components["dp_charge"] == ZERO and sell.components["dp_charge"] == D("15.34")
    assert not buy.costs_estimated and not sell.costs_estimated
    assert buy.rule_id == ROW.rule_id
    # display: ₹237.82, 0.238 % of the ticket
    total = buy.total_inr + sell.total_inr
    assert total.quantize(D("0.01")) == D("237.82")
    assert (total / D("100000") * 100).quantize(D("0.001")) == D("0.238")


def test_stt_rounds_to_whole_rupee_half_up() -> None:
    # 0.1 % of 12,345 = 12.345 → ₹12; of 12,350 = 12.35 → ₹12; of 12,500 = 12.5 → ₹13 (paise ≥ 50 rounds up)
    def stt(v: str) -> Decimal:
        c = ce.equity_trade_cost(ce.Side.BUY, D(v), ON, SCHEDULE, ce.InstrumentKind.EQUITY_DELIVERY)
        return c.components["stt"]

    assert stt("12345") == D("12")
    assert stt("12500") == D("13")
    assert stt("12499") == D("12")


def test_second_sell_of_same_scrip_same_day_has_no_dp_charge() -> None:
    c = ce.equity_trade_cost(
        ce.Side.SELL, D("1000"), ON, SCHEDULE, ce.InstrumentKind.EQUITY_DELIVERY, first_sell_of_scrip_today=False
    )
    assert c.components["dp_charge"] == ZERO


def test_sell_requires_dp_flag() -> None:
    with pytest.raises(InvalidInput):
        ce.equity_trade_cost(ce.Side.SELL, D("1000"), ON, SCHEDULE, ce.InstrumentKind.EQUITY_DELIVERY)


def test_brokerage_cap_and_gst_on_brokerage() -> None:
    row = ce.EquityCostRow(**{**ROW.__dict__, "brokerage_rate": D("0.001"), "brokerage_cap_inr": D("20")})
    sched = ce.EquityCostSchedule(rows=(row,), estimate_multiplier=D("1.5"))
    c = ce.equity_trade_cost(ce.Side.BUY, D("100000"), ON, sched, ce.InstrumentKind.EQUITY_DELIVERY)
    assert c.components["brokerage"] == D("20")
    assert c.components["gst"] == (D("20") + D("3.07") + D("0.1")) * D("0.18")


def test_date_without_cost_row_uses_latest_row_upper_bound_and_flags_estimated() -> None:
    old = date(2020, 6, 1)
    c = ce.equity_trade_cost(ce.Side.BUY, D("100000"), old, SCHEDULE, ce.InstrumentKind.EQUITY_DELIVERY)
    assert c.costs_estimated
    assert ce.R_NO_COST_ROW in c.reasons
    # every component is today's row × 1.5 (STT rounded after scaling)
    assert c.components["stt"] == D("150")
    assert c.components["stamp"] == D("22.5")
    assert c.multiplier == D("1.5")


def test_etf_costs_are_estimated_upper_bound() -> None:
    c = ce.equity_trade_cost(ce.Side.BUY, D("100000"), ON, SCHEDULE, ce.InstrumentKind.ETF)
    assert c.costs_estimated
    assert ce.R_ETF_STT_UNVERIFIED in c.reasons
    assert c.components["stt"] == D("150")


def test_not_verified_row_marks_estimated() -> None:
    row = ce.EquityCostRow(**{**ROW.__dict__, "status": ce.CostStatus.NOT_VERIFIED})
    sched = ce.EquityCostSchedule(rows=(row,), estimate_multiplier=D("1.5"))
    c = ce.equity_trade_cost(ce.Side.BUY, D("100000"), ON, sched, ce.InstrumentKind.EQUITY_DELIVERY)
    assert c.costs_estimated
    assert ce.R_ROW_NOT_VERIFIED in c.reasons


def test_overlapping_rows_rejected() -> None:
    with pytest.raises(InvalidInput):
        ce.EquityCostSchedule(rows=(ROW, ROW), estimate_multiplier=D("1.5"))


def test_multiplier_must_be_at_least_one() -> None:
    with pytest.raises(InvalidInput):
        ce.EquityCostSchedule(rows=(ROW,), estimate_multiplier=D("0.9"))


def test_float_rejected() -> None:
    with pytest.raises(InvalidInput):
        ce.equity_trade_cost(
            ce.Side.BUY,
            100000.0,  # type: ignore[arg-type]
            ON,
            SCHEDULE,
            ce.InstrumentKind.EQUITY_DELIVERY,
        )


# --- T-1 ----------------------------------------------------------------------------------------


def _realised(acq: date, xfer: date, gain: str = "20000", lot: str = "SYN#1") -> lg.Realisation:
    return lg.Realisation(
        lot_id=lot,
        instrument_id="SYN-EQ-A",
        asset_class=tl.EQUITY,
        acquired=acq,
        transferred=xfer,
        units=D("100"),
        cost_basis_inr=D("100000"),
        proceeds_inr=D("100000") + D(gain),
        sell_costs_deductible_inr=ZERO,
    )


@pytest.mark.parametrize(
    ("acq", "mode", "expected"),
    [
        (date(2024, 9, 1), tl.ExemptionMode.USED_ELSEWHERE, "4160.00"),  # 8 months, STCG
        (date(2024, 9, 1), tl.ExemptionMode.AVAILABLE, "4160.00"),  # STCG ignores the LTCG exemption
        (date(2024, 3, 20), tl.ExemptionMode.USED_ELSEWHERE, "2600.00"),  # 13 months, exemption used
        (date(2024, 3, 20), tl.ExemptionMode.AVAILABLE, "0.00"),  # 13 months, exemption available
    ],
)
def test_t1_tax_cost_of_turnover(acq: date, mode: tl.ExemptionMode, expected: str) -> None:
    r = _realised(acq, date(2025, 5, 1))
    result = tl.tax_on_realisations([r], TAX_TABLE, mode)
    assert result.tax_rules_missing is False
    assert result.total_tax_inr == D(expected)
    (fy,) = result.years
    assert fy.financial_year == "2025-26"


def test_t1_breakdown_before_cess() -> None:
    r = _realised(date(2024, 9, 1), date(2025, 5, 1))
    fy = tl.tax_on_realisations([r], TAX_TABLE, tl.ExemptionMode.USED_ELSEWHERE).years[0]
    assert fy.stcg_taxable_inr == D("20000") and fy.base_tax_inr == D("4000")
    assert fy.cess_inr == D("160")


def test_exactly_twelve_months_is_short_term() -> None:
    r = _realised(date(2024, 5, 1), date(2025, 5, 1))
    fy = tl.tax_on_realisations([r], TAX_TABLE, tl.ExemptionMode.USED_ELSEWHERE).years[0]
    assert fy.stcg_taxable_inr == D("20000")
    r2 = _realised(date(2024, 5, 1), date(2025, 5, 2))
    fy2 = tl.tax_on_realisations([r2], TAX_TABLE, tl.ExemptionMode.USED_ELSEWHERE).years[0]
    assert fy2.ltcg_taxable_inr == D("20000")


def test_exemption_shared_across_the_year_pool() -> None:
    rs = [
        _realised(date(2024, 3, 1), date(2025, 6, 1), "100000", "SYN#1"),
        _realised(date(2024, 3, 1), date(2025, 9, 1), "100000", "SYN#2"),
    ]
    fy = tl.tax_on_realisations(rs, TAX_TABLE, tl.ExemptionMode.AVAILABLE).years[0]
    assert fy.ltcg_taxable_inr == D("75000")  # 200,000 − 125,000 once per FY, not per lot
    assert fy.total_tax_inr == D("75000") * D("0.125") * D("1.04")


def test_losses_are_not_set_off_conservatively() -> None:
    rs = [
        _realised(date(2024, 9, 1), date(2025, 5, 1), "20000", "SYN#1"),
        _realised(date(2024, 9, 1), date(2025, 5, 2), "-20000", "SYN#2"),
    ]
    result = tl.tax_on_realisations(rs, TAX_TABLE, tl.ExemptionMode.USED_ELSEWHERE)
    assert result.total_tax_inr == D("4160.00")
    assert tl.W_LOSS_SET_OFF_NOT_MODELLED in result.warnings


def test_missing_tax_rows_abstain_pre_tax_only() -> None:
    r = _realised(date(2022, 1, 1), date(2023, 6, 1))  # no row before 23-Jul-2024
    result = tl.tax_on_realisations([r], TAX_TABLE, tl.ExemptionMode.USED_ELSEWHERE)
    assert result.tax_rules_missing is True
    assert result.total_tax_inr is None
    assert tl.R_TAX_RULES_MISSING in result.reasons


def test_grandfathered_lot_abstains() -> None:
    r = _realised(date(2018, 1, 31), date(2025, 6, 1))
    result = tl.tax_on_realisations([r], TAX_TABLE, tl.ExemptionMode.USED_ELSEWHERE)
    assert result.tax_rules_missing is True


def test_year_spanning_two_rate_rows_abstains() -> None:
    old = tl.TaxRateRow(
        **{
            **RATES.__dict__,
            "rule_id": "EQ-CG-OLD@test",
            "effective_from": date(2018, 4, 1),
            "effective_to": date(2024, 7, 22),
            "stcg_rate": D("0.15"),
            "ltcg_rate": D("0.10"),
            "ltcg_exemption_inr": D("100000"),
        }
    )
    table = tl.TaxRateTable(rows=(old, RATES))
    rs = [
        _realised(date(2024, 1, 1), date(2024, 6, 1), "1000", "SYN#1"),
        _realised(date(2024, 1, 1), date(2024, 9, 1), "1000", "SYN#2"),
    ]
    result = tl.tax_on_realisations(rs, table, tl.ExemptionMode.USED_ELSEWHERE)
    assert result.tax_rules_missing is True
    assert tl.R_MIXED_RATE_ROWS_IN_YEAR in result.reasons


def test_unknown_asset_class_abstains() -> None:
    r = lg.Realisation(**{**_realised(date(2024, 9, 1), date(2025, 5, 1)).__dict__, "asset_class": "DEBT_MF"})
    result = tl.tax_on_realisations([r], TAX_TABLE, tl.ExemptionMode.USED_ELSEWHERE)
    assert result.tax_rules_missing is True


# --- ledger: FIFO ---------------------------------------------------------------------------------


def _zero_cost(_side: ce.Side) -> lg.TradeCost:
    return lg.TradeCost(components={}, rule_id="ZERO@test", costs_estimated=False, reasons=())


POLICY = lg.CostBasisPolicy(deductible_components=frozenset(), status="NOT VERIFIED")


def _ledger(cash: str = "1000000") -> lg.LedgerState:
    return lg.LedgerState.open(cash=D(cash), on=date(2024, 1, 1))


def test_fifo_consumes_oldest_lots_first() -> None:
    s = _ledger()
    s = lg.buy(s, "SYN-EQ-A", tl.EQUITY, date(2024, 1, 10), D("10"), D("100"), _zero_cost(ce.Side.BUY), POLICY)
    s = lg.buy(s, "SYN-EQ-A", tl.EQUITY, date(2024, 2, 10), D("10"), D("200"), _zero_cost(ce.Side.BUY), POLICY)
    s = lg.sell(s, "SYN-EQ-A", date(2024, 3, 10), D("15"), D("300"), _zero_cost(ce.Side.SELL), POLICY)
    first, second = s.realisations
    assert first.acquired == date(2024, 1, 10) and first.units == D("10")
    assert first.cost_basis_inr == D("1000") and first.proceeds_inr == D("3000")
    assert second.acquired == date(2024, 2, 10) and second.units == D("5")
    assert second.cost_basis_inr == D("1000") and second.proceeds_inr == D("1500")
    (remaining,) = s.open_lots("SYN-EQ-A")
    assert remaining.units == D("5") and remaining.cost_basis_inr == D("1000")
    assert s.cash_inr == D("1000000") - D("3000") + D("4500")
    lg.assert_fifo(s.realisations)


def test_assert_fifo_rejects_out_of_order_consumption() -> None:
    a = _realised(date(2024, 2, 1), date(2025, 5, 1), lot="SYN#2")
    b = _realised(date(2024, 1, 1), date(2025, 5, 1), lot="SYN#1")
    with pytest.raises(InvalidInput):
        lg.assert_fifo([a, b])


def test_cannot_sell_more_than_held_or_short() -> None:
    s = _ledger()
    s = lg.buy(s, "SYN-EQ-A", tl.EQUITY, date(2024, 1, 10), D("10"), D("100"), _zero_cost(ce.Side.BUY), POLICY)
    with pytest.raises(InvalidInput):
        lg.sell(s, "SYN-EQ-A", date(2024, 3, 10), D("11"), D("100"), _zero_cost(ce.Side.SELL), POLICY)
    with pytest.raises(InvalidInput):
        lg.sell(s, "SYN-EQ-B", date(2024, 3, 10), D("1"), D("100"), _zero_cost(ce.Side.SELL), POLICY)


def test_no_leverage_and_chronological_trades() -> None:
    s = _ledger("1000")
    with pytest.raises(InvalidInput):
        lg.buy(s, "SYN-EQ-A", tl.EQUITY, date(2024, 1, 10), D("11"), D("100"), _zero_cost(ce.Side.BUY), POLICY)
    s = lg.buy(s, "SYN-EQ-A", tl.EQUITY, date(2024, 2, 10), D("1"), D("100"), _zero_cost(ce.Side.BUY), POLICY)
    with pytest.raises(InvalidInput):
        lg.buy(s, "SYN-EQ-A", tl.EQUITY, date(2024, 1, 10), D("1"), D("100"), _zero_cost(ce.Side.BUY), POLICY)


def test_ledger_is_immutable() -> None:
    s0 = _ledger()
    s1 = lg.buy(s0, "SYN-EQ-A", tl.EQUITY, date(2024, 1, 10), D("1"), D("100"), _zero_cost(ce.Side.BUY), POLICY)
    assert s0.lots == () and len(s1.lots) == 1
    with pytest.raises(AttributeError):
        s1.cash_inr = D("0")  # type: ignore[misc]


def test_costs_debit_cash_and_capitalise_only_policy_components() -> None:
    policy = lg.CostBasisPolicy(deductible_components=frozenset({"stamp"}), status="NOT VERIFIED")
    s = _ledger()
    buy_cost = ce.equity_trade_cost(ce.Side.BUY, D("100000"), ON, SCHEDULE, ce.InstrumentKind.EQUITY_DELIVERY)
    s = lg.buy(s, "SYN-EQ-A", tl.EQUITY, ON, D("100"), D("1000"), buy_cost, policy)
    assert s.cash_inr == D("1000000") - D("100000") - buy_cost.total_inr
    assert s.lots[0].cost_basis_inr == D("100015")  # stamp capitalised, STT etc. not
    assert lg.W_COST_TREATMENT_UNVERIFIED in s.warnings
    assert s.costs_paid_inr == buy_cost.total_inr


def test_costs_estimated_is_sticky() -> None:
    s = _ledger()
    est = ce.equity_trade_cost(ce.Side.BUY, D("1000"), ON, SCHEDULE, ce.InstrumentKind.ETF)
    s = lg.buy(s, "SYN-ETF-A", tl.EQUITY, ON, D("10"), D("100"), est, POLICY)
    s = lg.sell(s, "SYN-ETF-A", ON, D("10"), D("100"), _zero_cost(ce.Side.SELL), POLICY)
    assert s.costs_estimated is True
    assert ce.R_COSTS_ESTIMATED in s.reason_codes


# --- terminal liquidation -------------------------------------------------------------------------


def _sell_cost(_instrument_id: str, on: date, value: Decimal) -> lg.TradeCost:
    return ce.equity_trade_cost(
        ce.Side.SELL, value, on, SCHEDULE, ce.InstrumentKind.EQUITY_DELIVERY, first_sell_of_scrip_today=True
    )


def test_terminal_liquidation_both_modes_t1() -> None:
    s = lg.LedgerState.open(cash=D("100000"), on=date(2024, 3, 1))
    s = lg.buy(s, "SYN-EQ-A", tl.EQUITY, date(2024, 3, 20), D("100"), D("1000"), _zero_cost(ce.Side.BUY), POLICY)
    end = date(2025, 5, 1)  # 13 months later
    tv = lg.terminal_valuation(
        s, end, {"SYN-EQ-A": D("1200")}, lambda *_: _zero_cost(ce.Side.SELL), TAX_TABLE, policy=POLICY
    )
    assert tv.market_value_inr == D("120000")
    assert tv.deferred.value_before_tax_inr == D("120000")
    assert tv.deferred.value_after_tax_inr[tl.ExemptionMode.USED_ELSEWHERE] == D("120000")  # nothing realised
    assert tv.liquidated.value_before_tax_inr == D("120000")
    assert tv.liquidated.tax_inr[tl.ExemptionMode.USED_ELSEWHERE] == D("2600.00")
    assert tv.liquidated.tax_inr[tl.ExemptionMode.AVAILABLE] == D("0.00")
    assert tv.liquidated.value_after_tax_inr[tl.ExemptionMode.USED_ELSEWHERE] == D("117400.00")
    assert tv.gating_value_inr == D("117400.00")
    assert tv.tax_rules_missing is False
    assert lg.W_TAX_SETTLED_AT_TERMINAL in tv.warnings
    # liquidation does not mutate the input ledger
    assert len(s.lots) == 1 and s.realisations == ()


def test_terminal_liquidation_with_costs_and_prior_realised_tax() -> None:
    s = lg.LedgerState.open(cash=D("300000"), on=date(2024, 9, 1))
    s = lg.buy(s, "SYN-EQ-A", tl.EQUITY, date(2024, 9, 1), D("100"), D("1000"), _zero_cost(ce.Side.BUY), POLICY)
    s = lg.buy(s, "SYN-EQ-A", tl.EQUITY, date(2024, 9, 2), D("100"), D("1000"), _zero_cost(ce.Side.BUY), POLICY)
    s = lg.sell(s, "SYN-EQ-A", date(2025, 5, 1), D("100"), D("1200"), _zero_cost(ce.Side.SELL), POLICY)  # STCG 20k
    end = date(2025, 5, 2)
    tv = lg.terminal_valuation(s, end, {"SYN-EQ-A": D("1000")}, _sell_cost, TAX_TABLE, policy=POLICY)
    # deferred: realised STCG tax 4,160 is due either way
    assert tv.deferred.value_before_tax_inr == D("320000")
    assert tv.deferred.value_after_tax_inr[tl.ExemptionMode.USED_ELSEWHERE] == D("320000") - D("4160.00")
    # liquidated: selling 100 @ 1000 costs C-1 sell side on ₹1 lakh, the loss is not set off
    sell = _sell_cost("SYN-EQ-A", end, D("100000"))
    assert tv.liquidation_costs_inr == sell.total_inr
    assert tv.liquidated.value_before_tax_inr == D("320000") - sell.total_inr
    assert tv.liquidated.tax_inr[tl.ExemptionMode.USED_ELSEWHERE] == D("4160.00")
    assert tv.gating_value_inr == D("320000") - sell.total_inr - D("4160.00")


def test_terminal_liquidation_missing_price_raises() -> None:
    s = _ledger()
    s = lg.buy(s, "SYN-EQ-A", tl.EQUITY, date(2024, 1, 10), D("1"), D("100"), _zero_cost(ce.Side.BUY), POLICY)
    with pytest.raises(InvalidInput):
        lg.terminal_valuation(s, date(2025, 1, 1), {}, lambda *_: _zero_cost(ce.Side.SELL), TAX_TABLE, policy=POLICY)


def test_terminal_liquidation_tax_rules_missing_is_pre_tax_only() -> None:
    s = lg.LedgerState.open(cash=D("1000"), on=date(2021, 1, 1))
    s = lg.buy(s, "SYN-EQ-A", tl.EQUITY, date(2021, 1, 10), D("1"), D("100"), _zero_cost(ce.Side.BUY), POLICY)
    tv = lg.terminal_valuation(
        s, date(2022, 6, 1), {"SYN-EQ-A": D("150")}, lambda *_: _zero_cost(ce.Side.SELL), TAX_TABLE, policy=POLICY
    )
    assert tv.tax_rules_missing is True
    assert tv.gating_value_inr is None
    assert tv.liquidated.value_after_tax_inr == {}
    assert tl.R_TAX_RULES_MISSING in tv.reason_codes
    assert tv.liquidated.value_before_tax_inr == D("1050")
