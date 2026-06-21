import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data_ingestion.market_data import get_ois_market_data
from src.curves.ois_curve import OISCurve
from src.montecarlo.hull_white import HullWhite1F
import numpy as np

data = get_ois_market_data()
curve = OISCurve(data['tenor_years'].values, data['ois_rate'].values)
model = HullWhite1F(curve, a=0.1, sigma=0.01)

_, rates_std = model.simulate_rates(n_paths=5000, seed=42, antithetic=False)
_, rates_anti = model.simulate_rates(n_paths=5000, seed=42, antithetic=True)

fwd = curve.instantaneous_forward(5.0)
err_std = abs(np.mean(rates_std[:, -1]) - fwd)
err_anti = abs(np.mean(rates_anti[:, -1]) - fwd)

print(f"err_std: {err_std}")
print(f"err_anti: {err_anti}")
print(f"fwd: {fwd}")
