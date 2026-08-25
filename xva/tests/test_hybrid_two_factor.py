"""Two-factor rates in the hybrid XVA engine.

Three things must hold, in order of importance:

1. **Repricing.** The simulated stochastic discount factor must reproduce the initial OIS
   curve. If it does not, every exposure number is drawn from a market that does not exist
   and no amount of downstream sophistication rescues it.
2. **Curve shape actually moves.** The reason for a second factor is that a one-factor model
   freezes the slope. If the 2F simulation does not produce more short/long decorrelation than
   1F, the extra factor is costing runtime and buying nothing.
3. **It shows up in the risk number.** Curve-shape risk the model can generate must reach EE
   and therefore CVA, otherwise it has been captured and then discarded.
"""

import numpy as np
import pytest

from src.curves.ois_curve import OISCurve
from src.xva.cva import CreditCurve
from src.xva.hybrid_xva import HybridXVAEngine, nearest_correlation

# An upward-sloping INR-like curve — a flat curve would hide slope effects by construction.
TENORS = np.array([0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0])
RATES = np.array([0.0625, 0.0640, 0.0665, 0.0690, 0.0705, 0.0720, 0.0730, 0.0740])
GRID = np.linspace(0.0, 5.0, 41)
N_PATHS = 20_000


def _curve() -> OISCurve:
    return OISCurve(TENORS, RATES)


def _engine(two_factor: bool) -> HybridXVAEngine:
    return HybridXVAEngine(
        _curve(), equity_spot=22_000.0, equity_vol=0.16, div_yield=0.013,
        a=0.35, sigma_r=0.010, equity_rate_corr=-0.15,
        two_factor=two_factor, b=0.05, sigma2=0.007, rho_xy=0.70,
    )


@pytest.mark.parametrize("two_factor", [True, False])
def test_simulation_reprices_the_initial_curve(two_factor):
    """E[stochastic DF] must match the curve's own DF, or the model is off-market."""
    sim = _engine(two_factor).simulate_joint(GRID, N_PATHS, seed=7)
    curve = _curve()
    modelled = sim['disc'].mean(axis=0)
    for i in range(0, len(GRID), 8):
        t = GRID[i]
        if t == 0.0:
            continue
        assert modelled[i] == pytest.approx(curve.df(t), rel=2e-3), (
            f"discount factor mismatch at t={t}: model {modelled[i]}, curve {curve.df(t)}"
        )


def test_equity_is_a_martingale_under_the_stochastic_discount():
    """E[S(t)·D(t)] = S(0)·e^(−q·t): the drift and the discount must be consistent."""
    eng = _engine(True)
    sim = eng.simulate_joint(GRID, N_PATHS, seed=11)
    deflated = (sim['spot'] * sim['disc']).mean(axis=0)
    expected = eng.eq.spot * np.exp(-eng.eq.q * GRID)
    assert np.allclose(deflated, expected, rtol=1.5e-2)


def test_two_factor_decorrelates_the_short_and_long_end():
    """The point of the second factor: the curve can twist, not merely shift."""

    def short_long_corr(two_factor: bool) -> float:
        eng = _engine(two_factor)
        sim = eng.simulate_joint(GRID, N_PATHS, seed=3)
        x, y = sim['x'], sim['y']
        ti = len(GRID) // 2
        t = GRID[ti]
        # 1y and 10y zero rates implied at t, path by path.
        short = -np.log(eng._bond_price(t, t + 1.0, x[:, ti], y[:, ti])) / 1.0
        long_ = -np.log(eng._bond_price(t, t + 10.0, x[:, ti], y[:, ti])) / 10.0
        return float(np.corrcoef(short, long_)[0, 1])

    one_f = short_long_corr(False)
    two_f = short_long_corr(True)
    assert one_f == pytest.approx(1.0, abs=1e-6), "1F must move the curve in lockstep"
    assert two_f < 0.995, f"2F should decorrelate tenors, got corr={two_f}"


def test_curve_shape_risk_reaches_the_exposure_and_the_cva():
    """A swap's EE and CVA must respond to the extra factor, not just the path generator."""
    credit = CreditCurve(150.0)
    results = {}
    for two_factor in (False, True):
        eng = _engine(two_factor)
        sim = eng.simulate_joint(GRID, N_PATHS, seed=5)
        swap = eng.swap_mtm(sim, notional=100.0, fixed_rate=0.070,
                            maturity=5.0, payer=True, pay_freq=0.5)
        results[two_factor] = eng.compute_hybrid_xva(sim, [swap], credit)

    assert results[True]['CVA_hybrid'] > 0.0
    assert results[True]['CVA_hybrid'] != pytest.approx(results[False]['CVA_hybrid'], rel=1e-3)
    assert np.max(results[True]['PFE_netted']) > 0.0


def test_netting_still_beats_standalone_under_two_factors():
    """Cross-asset diversification must survive the model change, not be an artefact of 1F."""
    eng = _engine(True)
    sim = eng.simulate_joint(GRID, N_PATHS, seed=9)
    swap = eng.swap_mtm(sim, notional=100.0, fixed_rate=0.070, maturity=5.0, payer=True)
    option = eng.equity_option_mtm(sim, strike=22_000.0, maturity=5.0, units=1.0, call=True)
    out = eng.compute_hybrid_xva(sim, [swap, option], CreditCurve(150.0))

    assert out['sum_standalone_cva'] >= out['CVA_hybrid']
    assert out['diversification_benefit_cva'] >= 0.0


def test_degenerate_mean_reversion_is_separated_not_rejected():
    """a == b degenerates HW2F; the engine must nudge rather than blow up mid-run."""
    eng = HybridXVAEngine(_curve(), 22_000.0, 0.16, a=0.10, b=0.10, two_factor=True)
    assert eng.hw.a != eng.hw.b
    eng.simulate_joint(np.linspace(0, 1, 5), 100, seed=1)  # must not raise


def test_inconsistent_correlations_are_repaired_not_fatal():
    """ρ_xy and ρ_eq come from different estimates; their matrix can be indefinite."""
    bad = np.array([[1.0, 0.95, -0.95], [0.95, 1.0, 0.95], [-0.95, 0.95, 1.0]])
    assert np.linalg.eigvalsh(bad).min() < 0.0
    fixed = nearest_correlation(bad)
    assert np.linalg.eigvalsh(fixed).min() >= 0.0
    assert np.allclose(np.diag(fixed), 1.0)
