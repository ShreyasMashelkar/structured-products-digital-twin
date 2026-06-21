"""Tests for the Incremental XVA engine (Phase 1)."""
import numpy as np
from src.workflow.portfolio_xva import PortfolioXVAContext
from src.workflow.incremental_xva import IncrementalXVAEngine


def _trade(tid, cpty='HDFC', notional=100.0, mat=5.0):
    return {'TradeID': tid, 'Counterparty': cpty, 'Notional': notional,
            'FixedRate': 7.0, 'Maturity': mat, 'Direction': 'Receive Fixed',
            'CSA_ID': 'UNCOLLATERALISED'}


def test_incremental_of_empty_book_equals_standalone():
    ctx = PortfolioXVAContext(n_paths=500, n_steps=24, horizon=5.0, seed=1)
    eng = IncrementalXVAEngine(ctx)
    t = _trade(1)
    res = eng.compute(t, existing_trades=[])
    # Incremental against an empty set == standalone netting-set XVA of the trade
    standalone = ctx.netting_set_xva([t], t['Counterparty'])
    assert abs(res['incremental']['EAD'] - standalone['EAD']) < 1e-6


def test_common_random_numbers_make_increment_deterministic():
    ctx = PortfolioXVAContext(n_paths=500, n_steps=24, horizon=5.0, seed=1)
    eng = IncrementalXVAEngine(ctx)
    a = eng.compute(_trade(2), existing_trades=[_trade(1)])['incremental']['Total_XVA']
    b = eng.compute(_trade(2), existing_trades=[_trade(1)])['incremental']['Total_XVA']
    assert abs(a - b) < 1e-9  # same context, same paths -> identical


def test_incremental_capital_nonnegative_for_added_risk():
    ctx = PortfolioXVAContext(n_paths=500, n_steps=24, horizon=5.0, seed=1)
    eng = IncrementalXVAEngine(ctx)
    incr = eng.compute(_trade(2, notional=300.0), existing_trades=[_trade(1)])['incremental']
    assert incr['EAD'] >= -1e-6
