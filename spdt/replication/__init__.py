"""L16 Universal Replication Framework: translate risks into hedge portfolios.

Given a decomposed product (from L15 Risk Decomposition), this engine constructs a portfolio
of liquid hedge instruments (vanillas, digitals, forwards) that replicate the product's risks.

Quick start::

    from spdt.decomposition import decompose
    from spdt.replication import replicate
    from spdt.pricing.models.bs import BlackScholes
    from spdt.products.catalog import BarrierReverseConvertible

    model = BlackScholes(spot=100, sigma=0.2, r=0.05, q=0.0)
    note = BarrierReverseConvertible(notional=100, observation_times=(1.0,),
                                     coupon_rate=0.05, strike=1.0, knock_in=0.8)

    decomposition = decompose(note)
    portfolio = replicate(decomposition, model)

    for instr in portfolio.instruments:
        print(f"{instr.purpose:25s} {instr.instrument_type:15s} weight={instr.weight:.4f}")
"""

from spdt.replication.engine import ReplicationEngine, get_engine, replicate
from spdt.replication.portfolio import HedgeInstrument, ReplicationPortfolio
from spdt.replication.strategies.base import AbstractReplicationStrategy

__all__ = [
    "AbstractReplicationStrategy",
    "HedgeInstrument",
    "ReplicationEngine",
    "ReplicationPortfolio",
    "get_engine",
    "replicate",
]
