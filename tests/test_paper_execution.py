"""Tests for the paper execution layer — pure simulation, no broker, no network.

Fills are simulated against :class:`~spdt.data.ingest.xts.Quote` marks (bid/ask crossing,
partial fills, slippage, fees), and paper positions/P&L accumulate from the fills.
"""

from datetime import datetime

from spdt.data.ingest.xts import InstrumentRef, Quote
from spdt.execution import CostModel, OrderIntent, OrderStatus, PaperBroker, Side

_NOW = datetime(2026, 7, 10, 11, 30, 0)
_FUT = InstrumentRef(exchange_segment=2, exchange_instrument_id=101, symbol="NIFTY-FUT")


def _quote(bid=100.0, ask=101.0, ltp=100.5, bid_qty=1000.0, ask_qty=1000.0, stale=False):
    return Quote(instrument=_FUT, ltp=ltp, bid=bid, ask=ask,
                 bid_qty=bid_qty, ask_qty=ask_qty, timestamp=_NOW, stale=stale)


def _broker(**costs):
    params = {"brokerage_per_order": 0.0, "taxes_bps": 0.0, "slippage_bps": 0.0, **costs}
    return PaperBroker(cost_model=CostModel(**params))


def test_market_buy_crosses_spread_and_opens_position():
    broker = _broker()
    order = broker.submit(OrderIntent(_FUT, Side.BUY, 10), _quote())
    assert order.status is OrderStatus.FILLED
    (fill,) = order.fills
    assert fill.price == 101.0 and fill.qty == 10  # taker pays the ask
    position = broker.positions[(2, 101)]
    assert position.qty == 10 and position.avg_price == 101.0


def test_market_sell_hits_bid_and_falls_back_to_ltp():
    broker = _broker()
    order = broker.submit(OrderIntent(_FUT, Side.SELL, 5), _quote())
    assert order.fills[0].price == 100.0  # taker hits the bid
    order2 = broker.submit(OrderIntent(_FUT, Side.SELL, 5), _quote(bid=None, ask=None))
    assert order2.fills[0].price == 100.5  # no depth → last traded price


def test_slippage_and_fees_are_charged():
    broker = PaperBroker(cost_model=CostModel(brokerage_per_order=20.0, taxes_bps=10.0,
                                              slippage_bps=100.0))
    order = broker.submit(OrderIntent(_FUT, Side.BUY, 10), _quote(ask=100.0))
    (fill,) = order.fills
    assert fill.price == 101.0  # 100 bps slippage on top of the ask
    assert fill.fees == 20.0 + 10 * 101.0 * 0.0010  # brokerage + taxes on notional
    assert broker.positions[(2, 101)].fees_paid == fill.fees


def test_limit_buy_rests_then_fills_when_market_comes_in():
    broker = _broker()
    order = broker.submit(OrderIntent(_FUT, Side.BUY, 10, limit_price=100.0), _quote(ask=101.0))
    assert order.status is OrderStatus.OPEN and not order.fills
    broker.on_quote(_quote(ask=99.5))
    assert order.status is OrderStatus.FILLED
    assert order.fills[0].price == 99.5  # fills at the touch, not the limit


def test_partial_fill_completes_on_later_quote():
    broker = _broker()
    order = broker.submit(OrderIntent(_FUT, Side.BUY, 100), _quote(ask_qty=60.0))
    assert order.status is OrderStatus.PARTIALLY_FILLED
    assert order.filled_qty == 60
    broker.on_quote(_quote(ask_qty=60.0))
    assert order.status is OrderStatus.FILLED and order.filled_qty == 100
    assert broker.positions[(2, 101)].qty == 100


def test_round_trip_realizes_pnl_and_flattens_position():
    broker = _broker()
    broker.submit(OrderIntent(_FUT, Side.BUY, 10), _quote(ask=100.0))
    broker.submit(OrderIntent(_FUT, Side.SELL, 10), _quote(bid=110.0))
    position = broker.positions[(2, 101)]
    assert position.qty == 0
    assert position.realized_pnl == 10 * (110.0 - 100.0)


def test_unrealized_pnl_from_mark():
    broker = _broker()
    broker.submit(OrderIntent(_FUT, Side.BUY, 10), _quote(ask=100.0))
    assert broker.positions[(2, 101)].unrealized_pnl(105.0) == 50.0


def test_stale_quote_rejects_order():
    broker = _broker()
    order = broker.submit(OrderIntent(_FUT, Side.BUY, 10), _quote(stale=True))
    assert order.status is OrderStatus.REJECTED and not order.fills
    assert (2, 101) not in broker.positions


def test_cancel_resting_order():
    broker = _broker()
    order = broker.submit(OrderIntent(_FUT, Side.BUY, 10, limit_price=90.0), _quote())
    broker.cancel(order.order_id)
    assert order.status is OrderStatus.CANCELLED
    broker.on_quote(_quote(ask=89.0))  # would have filled — must not
    assert not order.fills


def test_blotter_records_orders_and_fills():
    broker = _broker()
    broker.submit(OrderIntent(_FUT, Side.BUY, 10), _quote())
    broker.submit(OrderIntent(_FUT, Side.SELL, 4), _quote())
    assert len(broker.orders) == 2 and len(broker.fills) == 2


def test_position_identity_ignores_descriptive_metadata():
    broker = _broker()
    alias = InstrumentRef(exchange_segment=2, exchange_instrument_id=101, symbol="NIFTY25JULFUT")
    broker.submit(OrderIntent(_FUT, Side.BUY, 10), _quote(ask=100.0))
    alias_quote = Quote(alias, 110.0, 110.0, 111.0, 1000.0, 1000.0, _NOW, False)
    broker.submit(OrderIntent(alias, Side.SELL, 10), alias_quote)
    assert len(broker.positions) == 1
    assert broker.positions[(2, 101)].qty == 0
    assert broker.positions[(2, 101)].realized_pnl == 100.0


def test_slippage_never_violates_limit_price():
    broker = _broker(slippage_bps=100.0)
    buy = broker.submit(OrderIntent(_FUT, Side.BUY, 1, limit_price=100.0), _quote(ask=99.5))
    sell = broker.submit(OrderIntent(_FUT, Side.SELL, 1, limit_price=100.0), _quote(bid=100.5))
    assert buy.fills[0].price == 100.0
    assert sell.fills[0].price == 100.0
