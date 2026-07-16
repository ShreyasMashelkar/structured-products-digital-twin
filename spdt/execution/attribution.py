"""Hedge execution attribution (Phase 9): why did the hedge book make or lose money?

Splits the paper book's P&L into the desk's standard buckets — realized, unrealized (needs
marks), fees, and spread+slippage cost (fill price vs the mid it crossed from). Spread cost
is already *inside* the realized/unrealized numbers (the fills happened at those prices);
it is reported alongside for visibility, not subtracted again.
"""

from __future__ import annotations

from collections.abc import Mapping

from spdt.execution import PaperBroker


def execution_attribution(
    broker: PaperBroker, *, marks: Mapping[tuple[int, int], float]
) -> dict:
    """Per-instrument P&L attribution for the paper book. ``marks`` keys are (segment, id)."""
    rows = []
    for key, position in broker.positions.items():
        instrument = broker.position_instruments[key]
        fills = [f for f in broker.fills
                 if (f.instrument.exchange_segment, f.instrument.exchange_instrument_id) == key]
        spread_cost = sum(
            (f.price - f.mid) * f.qty * f.side.value for f in fills if f.mid is not None
        )
        mark = marks.get(key)
        unrealized = position.unrealized_pnl(mark) if mark is not None else None
        if unrealized is None and position.qty == 0.0:
            unrealized = 0.0  # flat book: no mark needed to know there's nothing unrealized
        net = (position.realized_pnl + unrealized - position.fees_paid
               if unrealized is not None else None)
        rows.append({
            "segment": key[0],
            "instrument_id": key[1],
            "symbol": instrument.symbol,
            "qty": position.qty,
            "avg_price": position.avg_price,
            "realized_pnl": position.realized_pnl,
            "unrealized_pnl": unrealized,
            "fees": position.fees_paid,
            "spread_cost": spread_cost,
            "net_pnl": net,
        })
    marked_rows = [r for r in rows if r["net_pnl"] is not None]
    return {
        "rows": rows,
        "totals": {
            "realized_pnl": sum(r["realized_pnl"] for r in rows),
            "fees": sum(r["fees"] for r in rows),
            "spread_cost": sum(r["spread_cost"] for r in rows),
            "net_pnl": sum(r["net_pnl"] for r in marked_rows) if marked_rows else None,
            "unmarked_positions": len(rows) - len(marked_rows),
        },
    }
