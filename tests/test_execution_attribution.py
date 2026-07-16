"""Tests for hedge execution attribution (Phase 9) — split paper P&L into its parts.

Every fill records the mid it crossed from, so realized/unrealized P&L, spread+slippage
cost, and fees are separable — the desk sees *why* the hedge book made or lost money.
"""

from datetime import datetime

import pytest

from spdt.data.ingest.xts import InstrumentRef, Quote
from spdt.execution import CostModel, OrderIntent, PaperBroker, Side
from spdt.execution.attribution import execution_attribution

_NOW = datetime(2026, 7, 10, 11, 30, 0)
_FUT = InstrumentRef(exchange_segment=2, exchange_instrument_id=101, symbol="NIFTY-FUT")


def _quote(bid, ask):
    return Quote(instrument=_FUT, ltp=(bid + ask) / 2, bid=bid, ask=ask,
                 bid_qty=1000.0, ask_qty=1000.0, timestamp=_NOW, stale=False)


def _broker():
    return PaperBroker(cost_model=CostModel(brokerage_per_order=0.0, taxes_bps=0.0,
                                            slippage_bps=0.0))


def test_fills_record_the_mid_they_crossed_from():
    broker = _broker()
    order = broker.submit(OrderIntent(_FUT, Side.BUY, 10), _quote(100.0, 101.0))
    assert order.fills[0].mid == 100.5


def test_round_trip_attribution_splits_spread_from_pnl():
    broker = _broker()
    broker.submit(OrderIntent(_FUT, Side.BUY, 10), _quote(100.0, 101.0))    # pay 101, mid 100.5
    broker.submit(OrderIntent(_FUT, Side.SELL, 10), _quote(110.0, 111.0))   # hit 110, mid 110.5
    report = execution_attribution(broker, marks={(2, 101): 110.0})
    (row,) = report["rows"]
    assert row["symbol"] == "NIFTY-FUT"
    assert row["realized_pnl"] == pytest.approx(90.0)       # 10 × (110 − 101)
    assert row["spread_cost"] == pytest.approx(10.0)        # 2 × half-spread × 10
    assert row["fees"] == 0.0
    assert row["unrealized_pnl"] == 0.0                     # flat
    assert row["net_pnl"] == pytest.approx(90.0)
    assert report["totals"]["net_pnl"] == pytest.approx(90.0)
    assert report["totals"]["spread_cost"] == pytest.approx(10.0)


def test_unmarked_position_reports_null_unrealized():
    broker = _broker()
    broker.submit(OrderIntent(_FUT, Side.BUY, 10), _quote(100.0, 101.0))
    (row,) = execution_attribution(broker, marks={})["rows"]
    assert row["unrealized_pnl"] is None
    assert row["net_pnl"] is None  # can't claim a net without a mark
