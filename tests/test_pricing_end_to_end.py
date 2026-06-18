"""Full stack: L1 snapshot → L2 surface → L4 MC price of the flagship autocallable."""

from datetime import date

from spdt.data import build_snapshot
from spdt.data.curate import invert_chain
from spdt.data.ingest.synthetic import SyntheticSource
from spdt.pricing import BlackScholes, price_mc
from spdt.products import Autocallable
from spdt.vol import VolSurface

AS_OF = date(2024, 6, 17)


def test_autocallable_prices_off_a_calibrated_snapshot():
    # L1: synthetic market → snapshot + inverted IV points.
    raw = SyntheticSource().fetch(AS_OF, "NIFTY")
    snap = build_snapshot(raw)
    points = invert_chain(raw, snap.ois_curve)

    # L2: calibrate the surface; read an ATM vol at the longest calibrated tenor.
    surface = VolSurface.calibrate(points, "NIFTY")
    taus = sorted(surface.taus.values())
    atm_vol = surface.implied_vol_kt(0.0, taus[-1])

    # Pricing inputs sourced from the snapshot, not invented.
    expiry_dates = sorted(surface.taus, key=lambda e: surface.taus[e])
    r = snap.ois_curve.zero_rate(expiry_dates[-1])
    q = snap.dividends["NIFTY"].continuous_yield
    model = BlackScholes(spot=snap.spots["NIFTY"], r=r, q=q, sigma=atm_vol)

    note = Autocallable(
        notional=100.0,
        observation_times=tuple(taus),
        coupon_rate=0.03,
        autocall_level=1.0,
        coupon_barrier=0.8,
        knock_in=0.6,
        memory=True,
    )
    result = price_mc(note, model, n_paths=50_000, seed=5)

    assert 0.0 < result.price < 130.0
    assert result.std_error < 1.0
