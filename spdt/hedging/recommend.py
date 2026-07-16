"""Hedge recommendation engine (Phase 8): size executable hedges from book Greeks.

Bridges risk to execution: takes the book's net delta/vega (from the portfolio aggregator or
a :class:`~spdt.decisions.engine.Decision`) plus tradable hedge instruments with live quotes,
and emits a :class:`HedgeRecommendation` — lot-rounded :class:`~spdt.execution.OrderIntent`\\ s
with estimated crossing cost/fees and an explicit approval state. The paper broker (or, later,
the gated live XTS client) executes the ``orders``; nothing here talks to a data source or
venue directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import count

from spdt.data.ingest.xts import Quote
from spdt.execution import CostModel, OrderIntent, Side

_ids = count(1)


@dataclass(frozen=True)
class HedgeInstrument:
    """A tradable hedge: its live quote and per-unit Greeks."""

    quote: Quote
    delta: float = 1.0  # futures ≈ 1
    vega: float = 0.0
    lot_size: int = 1


@dataclass(frozen=True)
class HedgeRecommendation:
    """A sized, costed, approval-stated hedge proposal — the desk's unit of review."""

    recommendation_id: str
    created_at: datetime
    objective: str
    current_greeks: dict[str, float]
    expected_greeks: dict[str, float]
    orders: tuple[OrderIntent, ...]
    estimated_cost: float
    approval_state: str  # PROPOSED | REJECTED_STALE_DATA | REJECTED_LIMIT
    reason_codes: tuple[str, ...]


def _lots(units: float, lot_size: int) -> float:
    """Round a signed unit quantity to the nearest whole lot."""
    return round(units / lot_size) * lot_size


def _touch_and_mid(quote: Quote, side: Side) -> tuple[float, float]:
    if quote.bid is not None and quote.ask is not None:
        return (quote.ask if side is Side.BUY else quote.bid), (quote.bid + quote.ask) / 2.0
    price = quote.ltp if quote.ltp is not None else 0.0
    return price, price


def _build(
    objective: str,
    current: dict[str, float],
    sized: list[tuple[HedgeInstrument, float]],  # (instrument, signed unit qty)
    reasons: list[str],
    *,
    max_notional: float | None,
    cost_model: CostModel,
    clock,
) -> HedgeRecommendation:
    expected = dict(current)
    orders: list[OrderIntent] = []
    cost = notional = 0.0
    state = "PROPOSED"
    for instrument, qty in sized:
        expected["delta"] = expected.get("delta", 0.0) + qty * instrument.delta
        expected["vega"] = expected.get("vega", 0.0) + qty * instrument.vega
        if qty == 0:
            continue
        side = Side.BUY if qty > 0 else Side.SELL
        orders.append(OrderIntent(instrument.quote.instrument, side, abs(qty)))
        touch, mid = _touch_and_mid(instrument.quote, side)
        cost += abs(qty) * abs(touch - mid) + cost_model.fees(abs(qty), touch)
        notional += abs(qty) * touch
        if instrument.quote.stale:
            state = "REJECTED_STALE_DATA"
            reasons.append("STALE_QUOTE")
    if state == "PROPOSED" and max_notional is not None and notional > max_notional:
        state = "REJECTED_LIMIT"
        reasons.append("MAX_NOTIONAL")
    return HedgeRecommendation(
        recommendation_id=f"HR{next(_ids)}",
        created_at=clock(),
        objective=objective,
        current_greeks=current,
        expected_greeks=expected,
        orders=tuple(orders),
        estimated_cost=cost,
        approval_state=state,
        reason_codes=tuple(dict.fromkeys(reasons)),  # de-dup, keep order
    )


def recommend_delta_hedge(
    book_delta: float,
    future: HedgeInstrument,
    *,
    tolerance: float = 0.0,
    max_notional: float | None = None,
    cost_model: CostModel | None = None,
    clock=datetime.now,
) -> HedgeRecommendation:
    """Neutralize the book's delta with the given future (lot-rounded)."""
    current = {"delta": book_delta, "vega": 0.0}
    reasons: list[str] = []
    if abs(book_delta) <= tolerance:
        sized: list[tuple[HedgeInstrument, float]] = []
        reasons.append("WITHIN_TOLERANCE")
    else:
        qty = _lots(-book_delta / future.delta, future.lot_size)
        sized = [(future, qty)]
        if not qty:
            reasons.append("WITHIN_TOLERANCE")
        elif book_delta + qty * future.delta != 0.0:
            reasons.append("LOT_ROUNDING")
    return _build("delta_neutral", current, sized, reasons,
                  max_notional=max_notional, cost_model=cost_model or CostModel(), clock=clock)


def recommend_delta_vega_hedge(
    book_delta: float,
    book_vega: float,
    future: HedgeInstrument,
    option: HedgeInstrument,
    *,
    max_notional: float | None = None,
    cost_model: CostModel | None = None,
    clock=datetime.now,
) -> HedgeRecommendation:
    """Neutralize vega with options first, then clean up the resulting delta with futures."""
    n_option = _lots(-book_vega / option.vega, option.lot_size)
    delta_after_options = book_delta + n_option * option.delta
    n_future = _lots(-delta_after_options / future.delta, future.lot_size)
    reasons: list[str] = []
    if (book_vega + n_option * option.vega != 0.0
            or delta_after_options + n_future * future.delta != 0.0):
        reasons.append("LOT_ROUNDING")
    return _build(
        "delta_vega_neutral",
        {"delta": book_delta, "vega": book_vega},
        [(option, n_option), (future, n_future)],
        reasons,
        max_notional=max_notional, cost_model=cost_model or CostModel(), clock=clock,
    )
