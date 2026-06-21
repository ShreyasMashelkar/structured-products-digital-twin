from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base


class Trade(Base):
    __tablename__ = "trades"
    id            = Column(Integer, primary_key=True, index=True)
    trade_id      = Column(String, unique=True, index=True)
    counterparty  = Column(String, index=True)
    notional_cr   = Column(Float)
    fixed_rate    = Column(Float)
    maturity_years = Column(Float)
    direction     = Column(String)


class XVAResult(Base):
    """One row per counterparty per EOD run."""
    __tablename__ = "xva_results"
    id            = Column(Integer, primary_key=True, index=True)
    run_date      = Column(String, index=True)        # YYYYMMDD
    counterparty  = Column(String, index=True)
    cds_bps       = Column(Float)
    epe_cr        = Column(Float)
    cva_cr        = Column(Float)
    dva_cr        = Column(Float)
    cs01_cr       = Column(Float, default=0.0)
    ir01_cr       = Column(Float, default=0.0)
    fva_cr        = Column(Float)
    mva_cr        = Column(Float)
    kva_cr        = Column(Float)
    ead_cr        = Column(Float)
    rwa_cr        = Column(Float)
    capital_cr    = Column(Float)
    xva_total_cr  = Column(Float)
    created_at    = Column(String, default=lambda: datetime.utcnow().isoformat())


class CurveSnapshot(Base):
    """One row per tenor node per EOD run — stores the full OIS curve."""
    __tablename__ = "curve_snapshots"
    id            = Column(Integer, primary_key=True, index=True)
    run_date      = Column(String, index=True)
    tenor_label   = Column(String)
    tenor_years   = Column(Float)
    ois_rate      = Column(Float)
    discount_factor = Column(Float)
    zero_rate     = Column(Float)


class MarketDataSnapshot(Base):
    """Key policy and market rates at EOD."""
    __tablename__ = "market_data_snapshots"
    id            = Column(Integer, primary_key=True, index=True)
    run_date      = Column(String, index=True)
    metric        = Column(String)   # e.g. 'repo_rate', 'mibor_on', 'ois_5y'
    value         = Column(Float)


class IncrementalXVAResult(Base):
    __tablename__ = "incremental_xva_results"
    id            = Column(Integer, primary_key=True, index=True)
    run_date      = Column(String, index=True)
    counterparty  = Column(String, index=True)
    proposed_trade_id = Column(String, index=True)
    incr_cva_cr   = Column(Float); incr_fva_cr = Column(Float)
    incr_mva_cr   = Column(Float); incr_kva_cr = Column(Float)
    incr_total_xva_cr = Column(Float); incr_ead_cr = Column(Float); incr_capital_cr = Column(Float)


class LegalEntity(Base):
    __tablename__ = "legal_entities"
    id            = Column(Integer, primary_key=True, index=True)
    entity_id     = Column(String, unique=True, index=True)
    entity_name   = Column(String)
    country       = Column(String)
    rating        = Column(String)


class NettingSetRef(Base):
    __tablename__ = "netting_sets"
    id            = Column(Integer, primary_key=True, index=True)
    netting_set_id= Column(String, unique=True, index=True)
    entity_id     = Column(String, ForeignKey("legal_entities.entity_id"))
    csa_id        = Column(String)
    margin_period_of_risk = Column(Integer)  # MPR in days


class CounterpartyLimit(Base):
    __tablename__ = "counterparty_limits"
    id            = Column(Integer, primary_key=True, index=True)
    entity_id     = Column(String, ForeignKey("legal_entities.entity_id"), index=True)
    metric        = Column(String)  # 'PFE_95', 'EAD', 'MTM', etc.
    limit_amount  = Column(Float)


class TradeApproval(Base):
    __tablename__ = "trade_approvals"
    id            = Column(Integer, primary_key=True, index=True)
    trade_id      = Column(String, index=True)
    decision      = Column(String)  # APPROVED, REJECTED, MANUAL_REVIEW
    reasons       = Column(String)
    incremental_xva = Column(Float)
    trade_raroc   = Column(Float)
    portfolio_raroc_impact = Column(Float)
    limit_status  = Column(String)
