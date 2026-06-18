"""Assemble raw market data into the immutable, content-addressed MarketSnapshot (L1).

This is the join point of the data layer: it turns one source's :class:`RawMarketData` into
the single object every layer above consumes (ADR-0001). It bootstraps the two rate curves
(OIS/risk-free + issuer funding-as-spread, ADR-0002), records dividends, and tags every
field with the raw data's provenance.

``surfaces`` is intentionally left empty at this stage: turning the inverted IV points into a
calibrated, arbitrage-free SVI/SSVI surface is L2's job. The snapshot is still complete and
reproducible for everything that depends only on spot, rates and dividends; surfaces attach
in the next slice. The IV points themselves are produced by
:func:`spdt.data.curate.invert_chain` and stored alongside (see :mod:`spdt.data.store`).
"""

from __future__ import annotations

from math import exp

from spdt.core.provenance import Provenance
from spdt.core.snapshot import MarketSnapshot
from spdt.core.types import Curve, DividendSchedule, SourceTag, year_fraction
from spdt.data.ingest import RawMarketData


def _bootstrap_ois(raw: RawMarketData) -> Curve:
    """Discount factors from continuously-compounded zero rates: ``D(T) = exp(−z(T)·T)``.

    Real OIS bootstrapping solves traded FBIL/T-bill instruments maturity-by-maturity (W1);
    here the source supplies zeros directly, so the "bootstrap" is the exponential map.
    """
    pillars = tuple(sorted(raw.ois_zero_rates))
    dfs = {p: exp(-raw.ois_zero_rates[p] * year_fraction(raw.date, p)) for p in pillars}
    return Curve(anchor=raw.date, pillars=pillars, discount_factors=dfs)


def build_snapshot(raw: RawMarketData) -> MarketSnapshot:
    """Build the frozen :class:`MarketSnapshot` for one underlying on one business date."""
    ois = _bootstrap_ois(raw)
    funding = Curve(
        anchor=raw.date,
        spread_over=ois,
        spread_knots=dict(raw.funding_spread_knots),
    )

    tag: SourceTag = raw.source
    provenance = Provenance(
        {
            f"spot.{raw.underlying}": tag,
            f"dividends.{raw.underlying}": tag,
            **{f"ois.{p.isoformat()}": tag for p in raw.ois_zero_rates},
            **{f"funding_spread.{p.isoformat()}": tag for p in raw.funding_spread_knots},
        }
    )

    return MarketSnapshot(
        date=raw.date,
        spots={raw.underlying: raw.spot},
        ois_curve=ois,
        funding_curve=funding,
        surfaces={},  # populated by L2 (vol calibration) in the next slice
        dividends={raw.underlying: DividendSchedule(continuous_yield=raw.dividend_yield)},
        provenance=provenance,
        correlation=None,  # single underlying; multi-asset correlation arrives with worst-of
    )
