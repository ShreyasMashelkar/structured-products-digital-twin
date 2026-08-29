"""Building a participation note from contracts that actually quote (L6).

The price-to-par solve answers *what participation is this note worth?* A client needs the
different question answered: *what participation can I actually buy?* Those are not the same
number, and on the live NIFTY book they differ by 17%.

Three things separate the model answer from the executable one, and they do not all push the
same way:

* **The ask, not the model.** A solved note prices its option leg at fair value. A client pays
  the offer. Measured on the 123-day NIFTY call, the model implied 871 points where the screen
  asked 1,045 — the model is 17% cheap, so it hands out participation nobody can buy.
* **Whole lots.** Participation solves continuously; NIFTY trades in 65-unit lots. The budget
  buys a whole number of them and the remainder stays in cash, which is a real (small) drag and
  a real change to the floor.
* **The client's own deposit.** The floor is funded by the client's fixed deposit, not by the
  wholesale curve. At 7.5% against a 5.3% curve that discounts harder and leaves a *larger*
  option budget, which is why full-protection notes are better than the model says while
  buffered ones are worse.

Nothing here is a model. Given a chain and a deposit rate, every number below is arithmetic on
quoted prices, which is what makes a term sheet built from it defensible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date

from spdt.core.types import year_fraction


@dataclass(frozen=True)
class ListedCall:
    """One quoted call, with everything an order needs."""

    expiry: Date
    strike: float
    ask: float
    lot_size: int
    bid: float | None = None

    def __post_init__(self) -> None:
        if self.ask <= 0.0:
            raise ValueError("a listed call needs a positive ask to be buyable")
        if self.lot_size <= 0:
            raise ValueError("lot size unknown — refusing to size an order against it")

    @property
    def cost_per_lot(self) -> float:
        return self.ask * self.lot_size

    @property
    def relative_spread(self) -> float | None:
        if self.bid is None or self.bid <= 0.0:
            return None
        mid = 0.5 * (self.bid + self.ask)
        return (self.ask - self.bid) / mid if mid > 0.0 else None


@dataclass(frozen=True)
class ExecutableNote:
    """A floor plus a whole number of listed calls. Every field is orderable."""

    notional: float
    floor: float  # fraction of notional the deposit matures to
    fd_rate: float  # the client's own deposit rate, annually compounded
    fee: float  # fraction of notional, taken at inception
    tau: float  # years to the option's expiry
    leg: ListedCall
    lots: int
    fd_invested: float
    fd_matures: float
    option_cost: float
    residual: float
    residual_matures: float

    @property
    def units(self) -> int:
        return self.lots * self.leg.lot_size

    def participation(self, spot: float) -> float:
        """Rupees of index exposure per rupee of mandate, above the strike."""
        return self.units * spot / self.notional

    def value_at(self, level: float) -> float:
        """Mandate value at maturity if the index closes at ``level``."""
        return self.fd_matures + max(0.0, level - self.leg.strike) * self.units + self.residual_matures

    @property
    def worst_case(self) -> float:
        """Return in the worst case, which is any level at or below the strike."""
        return self.value_at(0.0) / self.notional - 1.0

    @property
    def capital_protected(self) -> bool:
        return self.value_at(0.0) >= self.notional

    def breakeven(self) -> float | None:
        """Index level at which the mandate is repaid in full, or None if it always is."""
        if self.capital_protected:
            return None
        shortfall = self.notional - self.fd_matures - self.residual_matures
        return self.leg.strike + shortfall / self.units


def build_participation_note(
    *,
    spot: float,
    as_of: Date,
    maturity_years: float,
    floor: float,
    chain: list[ListedCall],
    fd_rate: float = 0.075,
    notional: float = 1e7,
    fee: float = 0.01,
    max_tenor_mismatch: float = 0.25,
) -> ExecutableNote:
    """Build the largest note the budget affords from contracts that actually quote.

    Picks the listed expiry closest to ``maturity_years`` and, within it, the strike nearest
    spot. Raises rather than guessing in two cases, both of which would otherwise hand back a
    number the client can never transact at:

    * the budget cannot buy a single lot, so there is no note to build;
    * no listed expiry lands within ``max_tenor_mismatch`` of the maturity asked for. Quietly
      substituting a 1.3-year contract for a 2.3-year request is not an approximation, it is a
      different product, and the caller must widen the tolerance deliberately to accept one.
    """
    if not 0.0 < floor <= 1.0:
        raise ValueError("floor must be a fraction of notional in (0, 1]")
    if notional <= 0.0 or maturity_years <= 0.0:
        raise ValueError("notional and maturity must be positive")
    dated = [c for c in chain if year_fraction(as_of, c.expiry) > 0.0]
    if not dated:
        raise ValueError("no listed calls with a future expiry")

    target = min(
        {c.expiry for c in dated},
        key=lambda e: abs(year_fraction(as_of, e) - maturity_years),
    )
    tau = year_fraction(as_of, target)
    if abs(tau - maturity_years) > max_tenor_mismatch * maturity_years:
        raise ValueError(
            f"nearest listed expiry is {tau:.2f}y against {maturity_years:.2f}y requested — "
            f"no contract quotes at that tenor"
        )
    leg = min((c for c in dated if c.expiry == target), key=lambda c: abs(c.strike - spot))

    fd_matures = notional * floor
    fd_invested = fd_matures / ((1.0 + fd_rate) ** tau)
    budget = notional - fd_invested - notional * fee
    if budget < leg.cost_per_lot:
        raise ValueError(
            f"budget {budget:,.0f} cannot buy one lot at {leg.cost_per_lot:,.0f} — "
            f"raise the maturity, lower the floor, or cut the fee"
        )
    lots = int(budget // leg.cost_per_lot)
    option_cost = lots * leg.cost_per_lot
    residual = budget - option_cost
    return ExecutableNote(
        notional=notional, floor=floor, fd_rate=fd_rate, fee=fee, tau=tau, leg=leg, lots=lots,
        fd_invested=fd_invested, fd_matures=fd_matures, option_cost=option_cost,
        residual=residual, residual_matures=residual * ((1.0 + fd_rate) ** tau),
    )


def calls_from_chain(chain, *, min_lot_size: int = 0) -> list[ListedCall]:
    """Quoted calls from a :class:`RawMarketData` option chain, ask-side only.

    Drops anything without a real ask or a known lot size. Both are required to place an
    order, and a note priced off a contract that cannot be bought is worse than no note.
    """
    out: list[ListedCall] = []
    for q in chain:
        if not q.is_call or q.ask is None or q.ask <= 0.0:
            continue
        lot = q.lot_size or min_lot_size
        if lot <= 0:
            continue
        out.append(ListedCall(q.expiry, q.strike, float(q.ask), int(lot), q.bid))
    return out


def floor_for_participation(
    *,
    spot: float,
    as_of: Date,
    maturity_years: float,
    target_participation: float,
    chain: list[ListedCall],
    fd_rate: float = 0.075,
    notional: float = 1e7,
    fee: float = 0.01,
    max_tenor_mismatch: float = 0.25,
) -> ExecutableNote:
    """The inverse solve: the client names the upside, the floor is what it costs.

    Participation is normally the *output* of a protected note, which leaves the more natural
    client question unanswerable: "I want 1.5 times the index. How much capital is that?"

    No search is needed. Participation is a step function of the floor (whole lots), so invert
    it directly: the target implies a lot count, the lot count implies a cost, and the cost
    implies the largest floor the remaining budget can still fund. The result is exact rather
    than the nearest point on a grid.

    The floor is capped at 100%: if the target is cheap enough to leave more than full
    protection unspent, the client gets full protection and *more* participation than asked
    for, which is not a failure to hit the target.
    """
    if target_participation <= 0.0:
        raise ValueError("target participation must be positive")
    dated = [c for c in chain if year_fraction(as_of, c.expiry) > 0.0]
    if not dated:
        raise ValueError("no listed calls with a future expiry")
    target_expiry = min(
        {c.expiry for c in dated},
        key=lambda e: abs(year_fraction(as_of, e) - maturity_years),
    )
    tau = year_fraction(as_of, target_expiry)
    if abs(tau - maturity_years) > max_tenor_mismatch * maturity_years:
        raise ValueError(
            f"nearest listed expiry is {tau:.2f}y against {maturity_years:.2f}y requested — "
            f"no contract quotes at that tenor"
        )
    leg = min((c for c in dated if c.expiry == target_expiry),
              key=lambda c: abs(c.strike - spot))

    units_needed = target_participation * notional / spot
    lots = max(1, -(-units_needed // leg.lot_size))  # ceil, so the target is met not missed
    lots = int(lots)
    cost = lots * leg.cost_per_lot
    spare = notional - cost - notional * fee
    if spare <= 0.0:
        raise ValueError(
            f"{target_participation:.2f}x needs {lots} lots costing {cost:,.0f}, which is more "
            f"than the mandate after fees — lower the target or lengthen the maturity"
        )
    floor = min(1.0, spare * ((1.0 + fd_rate) ** tau) / notional)
    return build_participation_note(
        spot=spot, as_of=as_of, maturity_years=maturity_years, floor=floor, chain=chain,
        fd_rate=fd_rate, notional=notional, fee=fee, max_tenor_mismatch=max_tenor_mismatch,
    )
