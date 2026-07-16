"""Paper execution layer (Phase 6): simulate order fills against live/replayed quotes.

Turns hedge recommendations into a trackable trading workflow with **no broker**: orders
cross the quoted spread (plus configurable slippage and fees), can fill partially against
displayed depth, rest as limit orders, and accumulate into paper positions with realized /
unrealized P&L. Everything is deterministic given the quote stream, so hedge backtests and
demos replay exactly.

Instrument identity and market state reuse the data-layer models
(:class:`~spdt.data.ingest.xts.InstrumentRef` / :class:`~spdt.data.ingest.xts.Quote`) — the
simulator itself never talks to a data source; callers feed it quotes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from math import isfinite
from threading import RLock

from spdt.data.ingest.xts import InstrumentRef, Quote


class Side(Enum):
    BUY = 1
    SELL = -1


class OrderStatus(Enum):
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class OrderIntent:
    """What a hedge engine (or trader) wants done. ``limit_price=None`` → market order."""

    instrument: InstrumentRef
    side: Side
    qty: float
    limit_price: float | None = None


@dataclass(frozen=True)
class CostModel:
    """Execution costs: flat brokerage per fill, taxes on notional, slippage past the touch.

    Defaults approximate Indian F&O retail costs; calibrate to the real contract note.
    """

    brokerage_per_order: float = 20.0
    taxes_bps: float = 5.0
    slippage_bps: float = 0.0

    def fees(self, qty: float, price: float) -> float:
        return self.brokerage_per_order + qty * price * (self.taxes_bps / 1e4)


@dataclass(frozen=True)
class Fill:
    order_id: str
    instrument: InstrumentRef
    side: Side
    qty: float
    price: float
    fees: float
    timestamp: datetime
    mid: float | None = None  # quote mid at fill time — lets attribution separate spread cost


@dataclass
class Order:
    """A working order: immutable intent + mutable lifecycle state."""

    order_id: str
    intent: OrderIntent
    status: OrderStatus = OrderStatus.OPEN
    fills: list[Fill] = field(default_factory=list)

    @property
    def filled_qty(self) -> float:
        return sum(f.qty for f in self.fills)

    @property
    def remaining_qty(self) -> float:
        return self.intent.qty - self.filled_qty

    @property
    def is_working(self) -> bool:
        return self.status in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED)


@dataclass
class Position:
    """Signed paper position with average-price netting and realized P&L."""

    qty: float = 0.0
    avg_price: float = 0.0
    realized_pnl: float = 0.0
    fees_paid: float = 0.0

    def apply(self, fill: Fill) -> None:
        signed = fill.qty * fill.side.value
        self.fees_paid += fill.fees
        if self.qty * signed < 0:  # reduces (or flips) the existing position
            closed = min(abs(signed), abs(self.qty))
            direction = 1.0 if self.qty > 0 else -1.0
            self.realized_pnl += closed * (fill.price - self.avg_price) * direction
            self.qty += signed
            if self.qty * direction < 0:  # flipped through flat: remainder opens fresh
                self.avg_price = fill.price
            elif self.qty == 0:
                self.avg_price = 0.0
        else:  # extends (or opens) — volume-weighted average price
            total = abs(self.qty) + fill.qty
            self.avg_price = (self.avg_price * abs(self.qty) + fill.price * fill.qty) / total
            self.qty += signed

    def unrealized_pnl(self, mark: float) -> float:
        return self.qty * (mark - self.avg_price)


def _key(ref: InstrumentRef) -> tuple[int, int]:
    return (ref.exchange_segment, ref.exchange_instrument_id)


class PaperBroker:
    """Simulated execution venue: submit orders against quotes, track fills and positions."""

    def __init__(self, *, cost_model: CostModel | None = None, clock=datetime.now) -> None:
        self.cost_model = cost_model or CostModel()
        self.clock = clock
        self.orders: list[Order] = []
        self.fills: list[Fill] = []
        self.positions: dict[tuple[int, int], Position] = {}
        self.position_instruments: dict[tuple[int, int], InstrumentRef] = {}
        self._seq = 0
        self._lock = RLock()

    def submit(self, intent: OrderIntent, quote: Quote) -> Order:
        """Submit an order against the current quote; market orders fill immediately."""
        with self._lock:
            self._seq += 1
            order = Order(order_id=f"P{self._seq}", intent=intent)
            self.orders.append(order)
            if not isfinite(intent.qty) or intent.qty <= 0 or quote.stale:
                order.status = OrderStatus.REJECTED
                return order
            self._try_fill(order, quote)
            return order

    def on_quote(self, quote: Quote) -> None:
        """Re-evaluate working orders on a fresh quote (resting limits, partial remainders)."""
        with self._lock:
            for order in self.orders:
                if order.is_working and _key(order.intent.instrument) == _key(quote.instrument):
                    self._try_fill(order, quote)

    def cancel(self, order_id: str) -> None:
        with self._lock:
            for order in self.orders:
                if order.order_id == order_id and order.is_working:
                    order.status = OrderStatus.CANCELLED

    def _try_fill(self, order: Order, quote: Quote) -> None:
        intent = order.intent
        if intent.side is Side.BUY:
            touch, depth = quote.ask, quote.ask_qty
        else:
            touch, depth = quote.bid, quote.bid_qty
        if touch is None:
            touch, depth = quote.ltp, None  # no displayed depth → assume liquid at last price
        if touch is None:
            return  # no price at all: order keeps resting
        if not isfinite(touch) or touch <= 0:
            order.status = OrderStatus.REJECTED
            return
        if intent.limit_price is not None:
            crosses = touch <= intent.limit_price if intent.side is Side.BUY else touch >= intent.limit_price
            if not crosses:
                return
        price = touch + touch * (self.cost_model.slippage_bps / 1e4) * intent.side.value
        if intent.limit_price is not None:
            price = min(price, intent.limit_price) if intent.side is Side.BUY else max(
                price, intent.limit_price
            )
        qty = order.remaining_qty if depth is None else min(order.remaining_qty, depth)
        if qty <= 0:
            return
        mid = (quote.bid + quote.ask) / 2.0 if quote.bid is not None and quote.ask is not None else quote.ltp
        fill = Fill(
            order_id=order.order_id,
            instrument=intent.instrument,
            side=intent.side,
            qty=qty,
            price=price,
            fees=self.cost_model.fees(qty, price),
            timestamp=self.clock(),
            mid=mid,
        )
        order.fills.append(fill)
        self.fills.append(fill)
        key = _key(intent.instrument)
        self.position_instruments.setdefault(key, intent.instrument)
        self.positions.setdefault(key, Position()).apply(fill)
        order.status = OrderStatus.FILLED if order.remaining_qty <= 0 else OrderStatus.PARTIALLY_FILLED


__all__ = [
    "CostModel", "Fill", "Order", "OrderIntent", "OrderStatus", "PaperBroker", "Position", "Side",
]
