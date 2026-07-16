"""Tests for the hedge recommendation engine — Greeks + quotes in, sized OrderIntents out.

Pure sizing/costing logic: no network, no broker. The end-to-end test paper-executes a
recommendation and checks the position actually neutralizes the book delta.
"""

from datetime import datetime

from spdt.data.ingest.xts import InstrumentRef, Quote
from spdt.execution import CostModel, PaperBroker, Side
from spdt.hedging.recommend import (
    HedgeInstrument,
    recommend_delta_hedge,
    recommend_delta_vega_hedge,
)

_NOW = datetime(2026, 7, 10, 11, 30, 0)
_FUT_REF = InstrumentRef(exchange_segment=2, exchange_instrument_id=101, symbol="NIFTY-FUT")
_OPT_REF = InstrumentRef(exchange_segment=2, exchange_instrument_id=202, symbol="NIFTY-OPT")


def _fut(bid=100.0, ask=101.0, lot_size=1, stale=False):
    quote = Quote(instrument=_FUT_REF, ltp=100.5, bid=bid, ask=ask, bid_qty=10_000.0,
                  ask_qty=10_000.0, timestamp=_NOW, stale=stale)
    return HedgeInstrument(quote=quote, delta=1.0, lot_size=lot_size)


def _opt(delta=0.5, vega=20.0):
    quote = Quote(instrument=_OPT_REF, ltp=5.0, bid=4.9, ask=5.1, bid_qty=10_000.0,
                  ask_qty=10_000.0, timestamp=_NOW, stale=False)
    return HedgeInstrument(quote=quote, delta=delta, vega=vega, lot_size=1)


_NO_COSTS = CostModel(brokerage_per_order=0.0, taxes_bps=0.0, slippage_bps=0.0)


def test_delta_hedge_sells_futures_against_long_delta():
    rec = recommend_delta_hedge(150.0, _fut(), cost_model=_NO_COSTS)
    (order,) = rec.orders
    assert order.side is Side.SELL and order.qty == 150
    assert rec.approval_state == "PROPOSED"
    assert rec.current_greeks["delta"] == 150.0 and rec.expected_greeks["delta"] == 0.0
    assert rec.estimated_cost == 150 * 0.5  # half-spread crossing cost, mid 100.5 → ask/bid ±0.5


def test_delta_hedge_rounds_to_lots_and_reports_residual():
    rec = recommend_delta_hedge(100.0, _fut(lot_size=75), cost_model=_NO_COSTS)
    (order,) = rec.orders
    assert order.qty == 75  # nearest whole lot
    assert rec.expected_greeks["delta"] == 25.0
    assert "LOT_ROUNDING" in rec.reason_codes


def test_delta_within_tolerance_recommends_nothing():
    rec = recommend_delta_hedge(10.0, _fut(lot_size=75), tolerance=40.0, cost_model=_NO_COSTS)
    assert not rec.orders and "WITHIN_TOLERANCE" in rec.reason_codes


def test_delta_vega_hedge_sizes_option_then_cleans_up_delta():
    rec = recommend_delta_vega_hedge(0.0, -1000.0, _fut(), _opt(delta=0.5, vega=20.0),
                                     cost_model=_NO_COSTS)
    by_id = {o.instrument.exchange_instrument_id: o for o in rec.orders}
    opt, fut = by_id[202], by_id[101]
    assert opt.side is Side.BUY and opt.qty == 50      # +50 × 20 vega = +1000
    assert fut.side is Side.SELL and fut.qty == 25     # cancels 50 × 0.5 delta from the options
    assert rec.expected_greeks["delta"] == 0.0 and rec.expected_greeks["vega"] == 0.0


def test_stale_quote_rejects_recommendation():
    rec = recommend_delta_hedge(150.0, _fut(stale=True), cost_model=_NO_COSTS)
    assert rec.approval_state == "REJECTED_STALE_DATA"


def test_notional_limit_rejects_recommendation():
    rec = recommend_delta_hedge(150.0, _fut(), max_notional=1000.0, cost_model=_NO_COSTS)
    assert rec.approval_state == "REJECTED_LIMIT"
    assert "MAX_NOTIONAL" in rec.reason_codes


def test_recommendation_paper_executes_to_a_delta_neutral_position():
    fut = _fut()
    rec = recommend_delta_hedge(150.0, fut, cost_model=_NO_COSTS)
    broker = PaperBroker(cost_model=_NO_COSTS)
    for order in rec.orders:
        assert broker.submit(order, fut.quote).status.value == "FILLED"
    assert broker.positions[(2, 101)].qty == -150  # book +150 delta + hedge −150 → flat
