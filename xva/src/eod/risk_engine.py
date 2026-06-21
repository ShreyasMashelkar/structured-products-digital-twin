"""
End-of-Day Risk Batch Engine.

Runs the full XVA and regulatory capital calculation for all trades
in the portfolio. Outputs a comprehensive EOD report with:
  - Trade-level MTM
  - Counterparty-level EE, PFE, EPE
  - CVA, DVA, FVA, KVA per counterparty netting set
  - SA-CCR EAD, RWA, Capital per counterparty
  - Portfolio totals
"""
import os
import datetime
import pandas as pd
import numpy as np

from src.data_ingestion.market_data import get_ois_market_data
from src.curves.ois_curve import OISCurve
from src.curves.multi_curve import MultiCurveFramework
from src.montecarlo.hull_white import HullWhite1F, calibrate_hw1f
from src.data_ingestion.market_data import get_historical_mibor
from src.data_ingestion.portfolio_manager import PortfolioManager
from src.portfolio.netting_engine import NettingEngine
from src.portfolio.capital_optimizer import CapitalOptimizer
from src.xva.cva import CVAEngine, CreditCurve, build_credit_curve_from_cds
from src.xva.fva import FVAEngine
from src.xva.kva import KVAEngine
from src.xva.mva import MVAEngine
from src.sa_ccr.regulatory import SACCRCalculator, compute_rwa, compute_capital_requirement
from db.database import SessionLocal, engine as db_engine
from db.models import Base, XVAResult, CurveSnapshot, MarketDataSnapshot


class EODRiskEngine:
    """Runs end-of-day batch risk and XVA calculations for the full portfolio."""

    def __init__(self):
        self.portfolio_df = PortfolioManager.load_portfolio()
        self.cptys_df = PortfolioManager.load_counterparties()
        self.trades = self.portfolio_df.to_dict('records')

    def run_eod_batch(self, n_paths: int = 2000, n_steps: int = 60,
                      horizon: float = 10.0) -> pd.DataFrame:
        """
        Execute the full EOD batch.

        Steps:
            1. Build OIS curve
            2. Calibrate HW1F from historical MIBOR
            3. Run Monte Carlo
            4. Compute exposure per counterparty netting set
            5. Compute CVA, DVA, FVA, KVA, MVA per counterparty
            6. Compute SA-CCR EAD, RWA, Capital per counterparty
            7. Assemble and save report
        """
        # ── 1. Curves ──────────────────────────────────────────────────────────
        ois_data = get_ois_market_data()
        ois_curve = OISCurve(ois_data['tenor_years'].values,
                             ois_data['ois_rate'].values)
        mcf = MultiCurveFramework.build_from_market_data()

        # ── 2. Calibrate HW1F ─────────────────────────────────────────────────
        mibor_history = get_historical_mibor(n_days=504)
        hw_params = calibrate_hw1f(mibor_history['mibor_rate'])
        a = float(np.clip(hw_params['a'], 0.01, 0.50))
        sigma = float(np.clip(hw_params['sigma'], 0.001, 0.05))
        print(f"[EOD] HW1F calibrated: a={a:.4f}, sigma={sigma:.4f}")

        # ── 3. Monte Carlo ─────────────────────────────────────────────────────
        hw_model = HullWhite1F(ois_curve, a=a, sigma=sigma)
        time_grid, rate_paths = hw_model.simulate_rates(
            n_paths=n_paths, n_steps=n_steps, horizon=horizon, seed=42
        )

        # ── 4. Netting + Collateral ────────────────────────────────────────────
        netting = NettingEngine(time_grid, rate_paths, hw_model)
        trade_mtm_paths = netting.calculate_trade_mtm_paths(self.trades, projection_curve=mcf.mibor)
        current_mtms = {tid: float(paths[:, 0].mean())
                        for tid, paths in trade_mtm_paths.items()}

        csa_mtm = netting.aggregate_by_csa(self.trades, trade_paths=trade_mtm_paths)
        csa_exposures = netting.apply_collateral(csa_mtm)

        # Build a counterparty → CSA_ID lookup
        cpty_to_csa = {}
        for trade in self.trades:
            cpty = trade.get('Counterparty', trade.get('counterparty', ''))
            csa_id = trade.get('CSA_ID', 'UNCOLLATERALISED')
            cpty_to_csa.setdefault(cpty, []).append(csa_id)
        for c in cpty_to_csa:
            cpty_to_csa[c] = list(set(cpty_to_csa[c]))

        # ── 5. XVA per counterparty ────────────────────────────────────────────
        cva_engine = CVAEngine(ois_curve)
        own_cds_bps = 40.0      # Bank's own CDS spread for DVA

        counterparty_results = []

        for _, row in self.cptys_df.iterrows():
            cpty_name = row['Counterparty']
            cds_bps = float(row.get('CDS_Spread_BPS', 100))
            recovery = float(row.get('RecoveryRate', 0.40))
            funding_spread = float(row.get('FundingSpread', 0.005)) * 10000  # to bps
            risk_weight = float(row.get('RiskWeight', 0.50))

            # Find this counterparty's CSA exposure
            csa_ids = cpty_to_csa.get(cpty_name, ['UNCOLLATERALISED'])
            
            tg = None
            ee = None
            ene = None
            epe = 0.0
            pfe_1y = 0.0
            pfe_5y = 0.0
            
            for csa_id in csa_ids:
                if csa_id not in csa_exposures:
                    continue
                metrics = csa_exposures[csa_id]
                tg = metrics['time_grid']
                if ee is None:
                    ee = np.zeros_like(metrics['EE'])
                    ene = np.zeros_like(metrics['EE'])
                
                ee += metrics['EE']
                ene += metrics.get('ENE', np.zeros_like(metrics['EE']))
                epe += float(metrics.get('EPE', 0.0))
                
                t1y_idx = int(np.argmin(np.abs(tg - 1.0)))
                t5y_idx = int(np.argmin(np.abs(tg - 5.0)))
                pfe_1y += float(metrics['PFE'][t1y_idx])
                pfe_5y += float(metrics['PFE'][min(t5y_idx, len(metrics['PFE'])-1)])
            
            if ee is None:
                continue

            # Check if all exposures are CCP-cleared
            all_ccp = all(
                csa_exposures.get(csa_id, {}).get('is_ccp', False)
                for csa_id in csa_ids if csa_id in csa_exposures
            )

            # CVA / DVA
            cpty_curve = build_credit_curve_from_cds(
                tenors=[1.0, 2.0, 3.0, 5.0, 7.0],
                spreads_bps=[cds_bps] * 5,
                recovery_rate=recovery,
                ois_curve=ois_curve
            )
            own_curve = CreditCurve(own_cds_bps)
            bilateral = cva_engine.compute_bilateral_cva(
                ee, ene, tg, cpty_curve, own_curve
            )
            # Zero out CVA/DVA for CCP-cleared trades (CCP is default-remote)
            if all_ccp:
                bilateral['CVA'] = 0.0
                bilateral['DVA'] = 0.0
                bilateral['Bilateral_CVA'] = 0.0

            # XVA Greeks — CS01 and IR01
            # CS01: change in CVA for 1bp parallel CDS spread widening
            cs01 = cva_engine.cva_sensitivity(
                ee, tg, cpty_curve, shock_bps=1.0
            )
            # IR01: change in CVA for 1bp parallel OIS rate shift
            # Exposure unchanged; only discount factors move
            shocked_ois = ois_curve.shift(1.0)   # OISCurve.shift() already exists
            cva_engine_shocked = CVAEngine(shocked_ois)
            ir01 = (cva_engine_shocked.compute_cva(ee, tg, cpty_curve)
                    - bilateral['CVA'])

            # FVA
            bank_curve = CreditCurve(own_cds_bps)
            fva_engine = FVAEngine(
                ois_curve,
                funding_spread_bps=funding_spread,
                bank_credit_curve=bank_curve,
                cpty_credit_curve=cpty_curve,
            )
            fva_result = fva_engine.compute_fva(ee, ene, tg)

            # Get trades for this counterparty to compute DV01 (needed for MVA) and KVA trade metrics
            cpty_trades = [t for t in self.trades
                           if t.get('Counterparty', t.get('counterparty', '')) == cpty_name]
            total_dv01 = 0.0
            from src.pricing.swap_pricer import SwapPricer
            for t in cpty_trades:
                sp = SwapPricer(
                    notional=float(t['Notional']),
                    fixed_rate=float(t['FixedRate']) / 100.0
                          if float(t['FixedRate']) > 1.0 else float(t['FixedRate']),
                    maturity=float(t['Maturity']),
                    direction=t['Direction']
                )
                total_dv01 += abs(sp.dv01(ois_curve))

            # KVA — use SA-CCR term structure if trade data is available
            kva_engine = KVAEngine(ois_curve)
            if cpty_trades:
                # Aggregate notional and weighted average maturity across counterparty trades
                total_notional = sum(float(t['Notional']) for t in cpty_trades)
                avg_maturity = (
                    sum(float(t['Notional']) * float(t['Maturity']) for t in cpty_trades)
                    / total_notional if total_notional > 0 else 5.0
                )
                # Direction: use net direction (most common across trades)
                directions = [t['Direction'] for t in cpty_trades]
                net_direction = max(set(directions), key=directions.count)
                kva_result = kva_engine.compute_kva_from_saccr(
                    time_grid=tg,
                    notional=total_notional,
                    initial_maturity=avg_maturity,
                    direction=net_direction,
                    risk_weight=risk_weight,
                    mtm_profile=ee,
                )
            else:
                kva_result = kva_engine.compute_kva_from_exposure(ee, tg, risk_weight)

            # MVA (DV01-based IM proxy)
            mva_engine = MVAEngine(
                ois_curve=ois_curve,
                funding_spread_bps=funding_spread,
                dv01_cr=total_dv01
            )
            im_profile = mva_engine.compute_im_profile(ee)
            mva_val = mva_engine.compute_mva(im_profile, tg)

            # SA-CCR EAD
            cpty_portfolio = pd.DataFrame(cpty_trades) if cpty_trades else pd.DataFrame()
            if not cpty_portfolio.empty:
                cpty_portfolio = cpty_portfolio.rename(columns={
                    'Notional': 'notional_cr',
                    'Maturity': 'maturity_years',
                    'Direction': 'direction',
                })
                if 'notional_cr' in cpty_portfolio.columns:
                    total_mtm = sum(current_mtms.get(t['TradeID'], 0.0)
                                    for t in cpty_trades)
                    saccr = SACCRCalculator()
                    ead_result = saccr.compute_netting_set_ead(
                        trades=cpty_portfolio,
                        mtm_total=total_mtm
                    )
                    ead = ead_result['EAD']
                    rwa = compute_rwa(ead, risk_weight)
                    capital = compute_capital_requirement(rwa)
                else:
                    ead = rwa = capital = 0.0
            else:
                ead = rwa = capital = 0.0

            t1y_idx = int(np.argmin(np.abs(tg - 1.0)))
            t5y_idx = int(np.argmin(np.abs(tg - 5.0)))

            counterparty_results.append({
                'Counterparty': cpty_name,
                'Rating': row.get('Rating', 'N/A'),
                'CDS_BPS': cds_bps,
                'EPE_CR': round(epe, 4),
                'EE_1Y_CR': round(float(ee[t1y_idx]), 4),
                'PFE95_1Y_CR': round(pfe_1y, 4),
                'EE_5Y_CR': round(float(ee[min(t5y_idx, len(ee)-1)]), 4),
                'PFE95_5Y_CR': round(pfe_5y, 4),
                'CVA_CR': round(bilateral['CVA'], 4),
                'DVA_CR': round(bilateral['DVA'], 4),
                'CS01_CR': round(cs01, 6),
                'IR01_CR': round(ir01, 6),
                'FCA_CR': round(fva_result['FCA'], 4),
                'FBA_CR': round(fva_result['FBA'], 4),
                'FVA_CR': round(fva_result['FVA'], 4),
                'MVA_CR': round(mva_val, 4),
                'KVA_CR': round(kva_result['KVA'], 4),
                'EAD_CR': round(ead, 4),
                'RWA_CR': round(rwa, 4),
                'Capital_CR': round(capital, 4),
                'Basis_BPS': round(mcf.basis_bps, 2),
                'XVA_Total_CR': round(
                    bilateral['CVA'] + fva_result['FVA'] + kva_result['KVA'] + mva_val, 4
                ),
            })

        report_df = pd.DataFrame(counterparty_results)

        # ── 6. Save report ─────────────────────────────────────────────────────
        report_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'reports'
        )
        os.makedirs(report_dir, exist_ok=True)
        date_str = datetime.datetime.now().strftime("%Y%m%d")
        report_path = os.path.join(report_dir, f'EOD_Risk_Report_{date_str}.csv')
        report_df.to_csv(report_path, index=False)
        print(f"[EOD] Report saved: {report_path}")
        self._persist_to_db(report_df, ois_curve, date_str)

        return report_df

    def _persist_to_db(self, report_df: pd.DataFrame,
                        ois_curve: 'OISCurve',
                        date_str: str) -> None:
        """
        Persist EOD results to SQLite via SQLAlchemy.

        Creates tables if they don't exist, then upserts:
          - XVAResult rows for each counterparty
          - CurveSnapshot rows for each tenor node
          - MarketDataSnapshot rows for key rates
        """
        from src.data_ingestion.market_data import get_policy_rates

        Base.metadata.create_all(bind=db_engine)
        session = SessionLocal()
        try:
            # Delete today's existing rows to allow re-runs (idempotent)
            session.query(XVAResult).filter(
                XVAResult.run_date == date_str).delete()
            session.query(CurveSnapshot).filter(
                CurveSnapshot.run_date == date_str).delete()
            session.query(MarketDataSnapshot).filter(
                MarketDataSnapshot.run_date == date_str).delete()

            # Import Trade model (add to existing imports at top of method)
            from db.models import Trade

            # Delete and re-insert trades (idempotent — trades don't change day to day
            # but we upsert to keep the DB consistent with the current portfolio.csv)
            # Note: Trade table uses trade_id as unique key, so delete-all + reinsert
            # is safe for a single-instance deployment.
            existing_trade_ids = {
                r[0] for r in session.query(Trade.trade_id).all()
            }
            for trade in self.trades:
                tid = str(trade.get('TradeID', trade.get('trade_id', '')))
                if tid not in existing_trade_ids:
                    session.add(Trade(
                        trade_id=tid,
                        counterparty=str(trade.get('Counterparty',
                                                    trade.get('counterparty', ''))),
                        notional_cr=float(trade.get('Notional',
                                                     trade.get('notional_cr', 0.0))),
                        fixed_rate=float(trade.get('FixedRate',
                                                    trade.get('fixed_rate', 0.0))),
                        maturity_years=float(trade.get('Maturity',
                                                        trade.get('maturity_years', 0.0))),
                        direction=str(trade.get('Direction',
                                                 trade.get('direction', ''))),
                    ))

            # XVA results
            for _, row in report_df.iterrows():
                session.add(XVAResult(
                    run_date=date_str,
                    counterparty=row['Counterparty'],
                    cds_bps=row.get('CDS_BPS', 0.0),
                    epe_cr=row.get('EPE_CR', 0.0),
                    cva_cr=row.get('CVA_CR', 0.0),
                    dva_cr=row.get('DVA_CR', 0.0),
                    cs01_cr=row.get('CS01_CR', 0.0),
                    ir01_cr=row.get('IR01_CR', 0.0),
                    fva_cr=row.get('FVA_CR', 0.0),
                    mva_cr=row.get('MVA_CR', 0.0),
                    kva_cr=row.get('KVA_CR', 0.0),
                    ead_cr=row.get('EAD_CR', 0.0),
                    rwa_cr=row.get('RWA_CR', 0.0),
                    capital_cr=row.get('Capital_CR', 0.0),
                    xva_total_cr=row.get('XVA_Total_CR', 0.0),
                ))

            # Curve snapshot
            curve_df = ois_curve.to_dataframe()
            for _, row in curve_df.iterrows():
                session.add(CurveSnapshot(
                    run_date=date_str,
                    tenor_label=str(row.get('tenor_label', row['tenor_years'])),
                    tenor_years=float(row['tenor_years']),
                    ois_rate=float(row['market_rate']),
                    discount_factor=float(row['discount_factor']),
                    zero_rate=float(row['zero_rate']),
                ))

            # Market data snapshot
            policy = get_policy_rates()
            for metric, value in policy.items():
                session.add(MarketDataSnapshot(
                    run_date=date_str,
                    metric=metric,
                    value=float(value),
                ))

            session.commit()
            print(f"[EOD] Results persisted to DB for {date_str}")

        except Exception as e:
            session.rollback()
            print(f"[EOD] DB persist failed (non-fatal): {e}")
        finally:
            session.close()


if __name__ == "__main__":
    print("Starting EOD Risk Batch...")
    engine = EODRiskEngine()
    df = engine.run_eod_batch()
    print("\nEOD Run Complete — Summary:")
    print(df[['Counterparty', 'CVA_CR', 'FVA_CR', 'KVA_CR', 'EAD_CR', 'XVA_Total_CR']].to_string(index=False))
