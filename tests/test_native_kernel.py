"""The native C++ MC kernel agrees with the NumPy reference and the Python pricer.

Skipped when the optional kernel hasn't been compiled (``python cpp/build_kernel.py``), so CI
stays green on a machine without a compiler. When built, the kernel must price the autocallable
to within Monte-Carlo error of both the NumPy reference (same algorithm) and the high-level
:class:`Autocallable` pricer (the boundary is real, not a reimplementation that drifts).
"""

import pytest

from spdt.pricing import BlackScholes, price_mc
from spdt.pricing.native import (
    HAVE_NATIVE,
    price_autocallable,
    price_autocallable_reference,
)
from spdt.products import Autocallable

pytestmark = pytest.mark.skipif(not HAVE_NATIVE, reason="native kernel not built")

KW = dict(
    spot=100.0, r=0.06, q=0.0, sigma=0.2, obs_times=(0.25, 0.5, 0.75, 1.0),
    notional=100.0, coupon_rate=0.02, autocall_level=1.0, coupon_barrier=0.7,
    knock_in=0.6, n_paths=500_000, seed=0,
)


def test_native_matches_numpy_reference():
    nat = price_autocallable(backend="native", **KW)
    ref = price_autocallable_reference(**KW)
    # Different RNGs ⇒ compare within a few combined standard errors.
    assert nat.price == pytest.approx(ref.price, abs=5 * (nat.std_error + ref.std_error) + 1e-6)


def test_native_matches_high_level_pricer():
    nat = price_autocallable(backend="native", **KW)
    note = Autocallable(
        notional=100.0, observation_times=KW["obs_times"], coupon_rate=0.02,
        autocall_level=1.0, coupon_barrier=0.7, knock_in=0.6, initial_fixing=100.0,
    )
    model = BlackScholes(spot=100.0, r=0.06, q=0.0, sigma=0.2)
    hl = price_mc(note, model, n_paths=500_000, seed=1, antithetic=False)
    assert nat.price == pytest.approx(hl.price, abs=5 * (nat.std_error + hl.std_error) + 1e-6)
