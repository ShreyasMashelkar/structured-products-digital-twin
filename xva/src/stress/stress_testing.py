"""
Stress Testing Module.

Implements RBI rate shock scenarios and credit spread stress tests
for comprehensive risk analysis of the INR derivatives portfolio.

Scenarios:
    - Parallel rate shocks (+/-100, +200, +300 bps)
    - Credit spread widening
    - Combined macro stress (rate + credit)
    - NBFC-specific sectoral stress
    - Systemic crisis scenarios (2008-type, IL&FS-type)
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional

from src.curves.ois_curve import OISCurve
from src.pricing.swap_pricer import SwapPricer
from src.xva.cva import CVAEngine, CreditCurve, build_credit_curve_from_cds
from src.xva.fva import FVAEngine
from src.xva.kva import KVAEngine


def shock_curve(ois_curve: OISCurve, shock_bps: float) -> OISCurve:
    """
    Apply a parallel shift to the OIS zero curve.

    Args:
        ois_curve: Base OIS curve.
        shock_bps: Shock in basis points (positive = rates up).

    Returns:
        New OISCurve with shifted rates.
    """
    return ois_curve.shift(shock_bps)


def stress_test_swap(swap: SwapPricer, base_curve: OISCurve,
                     rate_shocks: List[float]) -> pd.DataFrame:
    """
    Stress test a single swap across rate shock scenarios.

    Args:
        swap: SwapPricer instance.
        base_curve: Base OIS curve.
        rate_shocks: List of rate shocks in bps.

    Returns:
        DataFrame with MTM under each scenario.
    """
    base_mtm = swap.mtm(base_curve)
    results = []

    for shock in rate_shocks:
        shocked_curve = shock_curve(base_curve, shock)
        shocked_mtm = swap.mtm(shocked_curve)

        results.append({
            'rate_shock_bps': shock,
            'MTM_cr': shocked_mtm,
            'MTM_change_cr': shocked_mtm - base_mtm,
            'MTM_change_pct': (shocked_mtm - base_mtm) / abs(base_mtm) * 100
            if abs(base_mtm) > 1e-10 else 0.0,
        })

    return pd.DataFrame(results)


def stress_test_cva(ee_profile: np.ndarray, time_grid: np.ndarray,
                    ois_curve: OISCurve,
                    base_cds_bps: float, recovery: float,
                    credit_shocks: List[float]) -> pd.DataFrame:
    """
    Stress test CVA across credit spread shock scenarios.

    Args:
        ee_profile: Expected Exposure profile.
        time_grid: Time grid.
        ois_curve: OIS curve.
        base_cds_bps: Base CDS spread in bps.
        recovery: Recovery rate.
        credit_shocks: List of credit spread shocks in bps.

    Returns:
        DataFrame with CVA under each scenario.
    """
    engine = CVAEngine(ois_curve)
    base_curve = build_credit_curve_from_cds(
        tenors=[1.0, 2.0, 3.0, 5.0, 7.0],
        spreads_bps=[base_cds_bps] * 5,
        recovery_rate=recovery,
        ois_curve=ois_curve,
    )
    base_cva = engine.compute_cva(ee_profile, time_grid, base_curve)

    results = []
    for shock in credit_shocks:
        shocked_cds = max(base_cds_bps + shock, 1.0)
        shocked_curve = build_credit_curve_from_cds(
            tenors=[1.0, 2.0, 3.0, 5.0, 7.0],
            spreads_bps=[shocked_cds] * 5,
            recovery_rate=recovery,
            ois_curve=ois_curve,
        )
        shocked_cva = engine.compute_cva(ee_profile, time_grid, shocked_curve)

        results.append({
            'credit_shock_bps': shock,
            'CDS_spread_bps': shocked_cds,
            'CVA_cr': shocked_cva,
            'CVA_change_cr': shocked_cva - base_cva,
        })

    return pd.DataFrame(results)


def run_full_stress_test(base_curve: OISCurve,
                         portfolio_df: pd.DataFrame,
                         counterparty_data: pd.DataFrame,
                         exposure_metrics: Dict,
                         scenarios: pd.DataFrame = None) -> pd.DataFrame:
    """
    Run the full stress test matrix across all scenarios.

    For each scenario:
    1. Shock the OIS curve
    2. Reprice all swaps
    3. Recompute CVA with shocked credit spreads
    4. Report changes in MTM, EE, CVA, KVA

    Args:
        base_curve: Base OIS curve.
        portfolio_df: Trade portfolio.
        counterparty_data: Counterparty credit data.
        exposure_metrics: Pre-computed exposure metrics.
        scenarios: Stress scenario definitions.

    Returns:
        DataFrame with comprehensive stress test results.
    """
    from src.data_ingestion.market_data import get_stress_scenarios

    if scenarios is None:
        scenarios = get_stress_scenarios()

    results = []

    # Base case values
    base_mtm_total = 0.0
    for _, trade in portfolio_df.iterrows():
        pricer = SwapPricer(
            notional=trade['notional_cr'],
            fixed_rate=trade['fixed_rate'],
            maturity=trade['maturity_years'],
            direction=trade['direction']
        )
        base_mtm_total += pricer.mtm(base_curve)

    # Compute base CVA
    cva_engine = CVAEngine(base_curve)
    base_cva_total = 0.0
    for _, cpty_row in counterparty_data.iterrows():
        cpty_name = cpty_row['counterparty']
        if cpty_name not in exposure_metrics:
            continue
        metrics = exposure_metrics[cpty_name]
        credit_curve = build_credit_curve_from_cds(
            tenors=[1.0, 2.0, 3.0, 5.0, 7.0],
            spreads_bps=[cpty_row['cds_spread_bps']] * 5,
            recovery_rate=cpty_row['recovery_rate'],
            ois_curve=base_curve,
        )
        base_cva_total += cva_engine.compute_cva(
            metrics['EE'], metrics['time_grid'], credit_curve
        )

    for _, scenario in scenarios.iterrows():
        rate_shock = scenario['rate_shock_bps']
        credit_shock = scenario['credit_spread_shock_bps']

        # Shock the curve
        shocked_curve = shock_curve(base_curve, rate_shock)

        # Reprice portfolio
        shocked_mtm = 0.0
        for _, trade in portfolio_df.iterrows():
            pricer = SwapPricer(
                notional=trade['notional_cr'],
                fixed_rate=trade['fixed_rate'],
                maturity=trade['maturity_years'],
                direction=trade['direction']
            )
            shocked_mtm += pricer.mtm(shocked_curve)

        # Recompute CVA with shocked credit spreads
        shocked_cva = 0.0
        for _, cpty_row in counterparty_data.iterrows():
            cpty_name = cpty_row['counterparty']
            if cpty_name not in exposure_metrics:
                continue
            metrics = exposure_metrics[cpty_name]
            shocked_cds = max(cpty_row['cds_spread_bps'] + credit_shock, 1.0)
            shocked_credit = build_credit_curve_from_cds(
                tenors=[1.0, 2.0, 3.0, 5.0, 7.0],
                spreads_bps=[shocked_cds] * 5,
                recovery_rate=cpty_row['recovery_rate'],
                ois_curve=base_curve,
            )
            shocked_cva += cva_engine.compute_cva(
                metrics['EE'], metrics['time_grid'], shocked_credit
            )

        results.append({
            'scenario': scenario['scenario'],
            'rate_shock_bps': rate_shock,
            'credit_shock_bps': credit_shock,
            'description': scenario['description'],
            'MTM_cr': shocked_mtm,
            'MTM_change_cr': shocked_mtm - base_mtm_total,
            'CVA_cr': shocked_cva,
            'CVA_change_cr': shocked_cva - base_cva_total,
        })

    return pd.DataFrame(results)

def run_historical_stress_test(base_curve: OISCurve,
                                portfolio_df: pd.DataFrame,
                                counterparty_data: pd.DataFrame,
                                exposure_metrics: Dict) -> pd.DataFrame:
    """
    Run historically-calibrated stress scenarios.

    Delegates to run_full_stress_test() using the historical scenario
    definitions from get_historical_stress_scenarios(). The result
    DataFrame has the same schema, making it directly comparable with
    forward-looking stress output.

    Args:
        base_curve: Current OIS curve.
        portfolio_df: Trade portfolio DataFrame.
        counterparty_data: Counterparty credit data.
        exposure_metrics: Pre-computed exposure metrics dict.

    Returns:
        DataFrame with MTM, CVA, and change columns for each
        historical scenario.
    """
    from src.data_ingestion.market_data import get_historical_stress_scenarios
    scenarios = get_historical_stress_scenarios()
    # Drop the extra reference_start/reference_end columns so that
    # run_full_stress_test() only sees the columns it knows about
    scenarios_slim = scenarios[
        ['scenario', 'rate_shock_bps', 'credit_spread_shock_bps', 'description']
    ].copy()
    result = run_full_stress_test(
        base_curve=base_curve,
        portfolio_df=portfolio_df,
        counterparty_data=counterparty_data,
        exposure_metrics=exposure_metrics,
        scenarios=scenarios_slim,
    )
    # Enrich with reference window for display
    result = result.merge(
        scenarios[['scenario', 'reference_start', 'reference_end']],
        on='scenario', how='left'
    )
    return result
