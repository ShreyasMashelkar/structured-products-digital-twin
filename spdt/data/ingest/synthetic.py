"""Synthetic market-data source — the declared, bounded fallback (design doc §2.4).

Where real data is unavailable (offline, pre-listing history, a thin name) we generate a
self-consistent market deterministically and tag it ``SourceTag.SYNTHETIC`` so it can never
silently masquerade as observed. The option chain is priced from a *known* smile, so the
downstream BS inversion can be checked to recover that smile to numerical tolerance — which
is what makes the whole ingestion → snapshot pipeline testable without the network.

This is faithful, not fake: the shape and the consistency are real; only the *origin* of
the numbers is synthetic, and that is declared on every byte via the provenance tag.
"""

from __future__ import annotations

from datetime import date, timedelta
from math import exp, log

from spdt.core.types import SourceTag, Underlying, year_fraction
from spdt.data.curate.bs_inversion import bs_price
from spdt.data.ingest import RawMarketData, RawOptionQuote

# Pillars (calendar days from the as-of date) at which we quote zero rates; the first three
# also carry option expiries. The 365d pillar simply extends the curve past the last expiry.
_PILLAR_DAYS = (30, 91, 182, 365)
_EXPIRY_DAYS = (30, 91, 182)
_STRIKE_MULTIPLIERS = (0.85, 0.925, 1.0, 1.075, 1.15)


def _smile_vol(log_moneyness: float) -> float:
    """A simple, stable skewed smile σ(k); k = log(K/F). Recovered by inversion in tests."""
    return 0.20 - 0.05 * log_moneyness + 0.10 * log_moneyness * log_moneyness


class SyntheticSource:
    """Deterministic :class:`MarketDataSource` for offline runs and tests."""

    def __init__(
        self,
        *,
        spot: float = 24100.0,  # anchored near a realistic current NIFTY level (still synthetic)
        dividend_yield: float = 0.013,
        funding_spread: float = 0.012,
    ) -> None:
        self._spot = spot
        self._dividend_yield = dividend_yield
        self._funding_spread = funding_spread

    def fetch(self, as_of: date, underlying: Underlying = "NIFTY") -> RawMarketData:
        zeros = {as_of + timedelta(days=d): 0.064 + 0.000012 * d for d in _PILLAR_DAYS}
        spread_knots = {
            as_of + timedelta(days=_PILLAR_DAYS[0]): self._funding_spread,
            as_of + timedelta(days=_PILLAR_DAYS[-1]): self._funding_spread,
        }

        quotes: list[RawOptionQuote] = []
        for days in _EXPIRY_DAYS:
            expiry = as_of + timedelta(days=days)
            tau = year_fraction(as_of, expiry)
            rate = zeros[expiry]
            forward = self._spot * exp((rate - self._dividend_yield) * tau)
            discount = exp(-rate * tau)
            for mult in _STRIKE_MULTIPLIERS:
                strike = self._spot * mult
                sigma = _smile_vol(log(strike / forward))
                for is_call in (True, False):
                    price = bs_price(forward, strike, tau, sigma, discount, is_call)
                    quotes.append(RawOptionQuote(expiry, strike, is_call, price))

        return RawMarketData(
            date=as_of,
            underlying=underlying,
            spot=self._spot,
            option_chain=tuple(quotes),
            ois_zero_rates=zeros,
            funding_spread_knots=spread_knots,
            dividend_yield=self._dividend_yield,
            source=SourceTag.SYNTHETIC,
        )
