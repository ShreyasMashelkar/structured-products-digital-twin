"""Tests for XVA Backtesting Engine."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from src.xva.backtest import XVABacktester

def test_backtester_no_breach():
    backtester = XVABacktester(confidence_interval=0.99)
    # 100 paths, 10 steps. PFE is 10.0 everywhere
    realized = np.random.uniform(0, 5, (100, 10))
    pfe = np.full(10, 10.0)
    
    result = backtester.backtest_exceptions(realized, pfe)
    assert result['total_exceptions'] == 0
    assert not result['is_breach']

def test_backtester_with_breach():
    backtester = XVABacktester(confidence_interval=0.95)
    # 100 paths, 10 steps. Realized is 20.0, PFE is 10.0
    realized = np.full((100, 10), 20.0)
    pfe = np.full(10, 10.0)
    
    result = backtester.backtest_exceptions(realized, pfe)
    assert result['total_exceptions'] == 1000
    assert result['max_exception_rate'] == 1.0
    assert result['is_breach']
