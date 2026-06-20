"""Broadie–Glasserman–Kou continuity correction reduces the discrete-monitoring bias.

A coarsely (e.g. monthly) monitored down-and-in put is breached less than a continuously
monitored one, so it is underpriced relative to the continuous limit. Applying the BGK barrier
shift to the coarse monitor should move its price markedly toward a finely (≈ continuous)
monitored reference.
"""

import numpy as np

from spdt.pricing import BlackScholes, price_mc
from spdt.pricing.analytic import BGK_BETA, continuity_corrected_barrier
from spdt.products import DownBarrierPut

MODEL = BlackScholes(spot=100.0, r=0.03, q=0.0, sigma=0.3)


def test_beta_constant_is_the_known_value():
    assert BGK_BETA == 0.5826414278686763


def test_correction_moves_coarse_price_toward_the_continuous_limit():
    barrier, strike, expiry = 90.0, 100.0, 1.0
    coarse = tuple(np.round(np.linspace(1 / 12, 1.0, 12), 6))  # monthly
    fine = tuple(np.round(np.linspace(1 / 250, 1.0, 250), 6))  # ≈ continuous (daily)
    dt = 1.0 / 12

    def di(b, monitoring):
        return price_mc(
            DownBarrierPut(strike=strike, barrier=b, expiry=expiry, monitoring=monitoring),
            MODEL,
            n_paths=200_000,
            seed=1,
        ).price

    reference = di(barrier, fine)
    raw_coarse = di(barrier, coarse)
    adj = continuity_corrected_barrier(barrier, MODEL.sigma, dt, direction="down")
    corrected_coarse = di(adj, coarse)

    # The correction raises the down barrier toward spot ⇒ more knock-ins ⇒ closer to continuous.
    assert adj > barrier
    assert abs(corrected_coarse - reference) < abs(raw_coarse - reference)


def test_zero_spacing_is_a_no_op():
    assert continuity_corrected_barrier(90.0, 0.3, 0.0, direction="down") == 90.0
