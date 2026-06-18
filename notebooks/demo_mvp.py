"""End-to-end MVP demo: data → surface → price → Greeks → term sheet.

Run from the repo root:  python3 notebooks/demo_mvp.py

Walks the full SPDT spine on the synthetic (offline) data source so it runs without a network.
"""

from datetime import date

from spdt.data import build_snapshot
from spdt.data.curate import invert_chain
from spdt.data.ingest.synthetic import SyntheticSource
from spdt.greeks import bump_greeks
from spdt.pricing import BlackScholes, price_mc
from spdt.products import Autocallable, TermSheet
from spdt.reporting import PricingSummary, maturity_scenarios, render_term_sheet
from spdt.structurer import ClientBrief, par_target, propose_autocallable, solve_to_par
from spdt.vol import VolSurface

AS_OF = date(2024, 6, 17)


def main() -> None:
    # L1 — ingest a market snapshot and invert settlement prices to IV points.
    raw = SyntheticSource().fetch(AS_OF, "NIFTY")
    snap = build_snapshot(raw)
    iv_points = invert_chain(raw, snap.ois_curve)
    print(f"[L1] snapshot {snap.short_hash}  spot={snap.spots['NIFTY']:.0f}  {len(iv_points)} IV points")

    # L2 — calibrate an arbitrage-free SVI surface.
    surface = VolSurface.calibrate(iv_points, "NIFTY")
    taus = sorted(surface.taus.values())
    atm_vol = surface.implied_vol_kt(0.0, taus[-1])
    print(f"[L2] surface arb-clean={surface.arb_status.is_clean}  ATM vol={atm_vol:.4f}")

    # Pricing model sourced from the snapshot (not invented).
    spot = snap.spots["NIFTY"]
    expiry = max(surface.taus, key=lambda e: surface.taus[e])
    model = BlackScholes(spot=spot, r=snap.ois_curve.zero_rate(expiry), q=0.013, sigma=atm_vol)

    # L6 — propose a structure from a client brief, then solve its coupon to par.
    brief = ClientBrief(target_coupon=0.08, max_downside=0.30, maturity_years=taus[-1])
    ts = propose_autocallable(brief)
    ts = TermSheet(ts.product_type, ts.underlyings, ts.notional, tuple(taus), ts.params)

    def pv_for_coupon(c: float) -> float:
        note = Autocallable.from_termsheet(
            TermSheet(ts.product_type, ts.underlyings, ts.notional, ts.observation_times,
                      {**ts.params, "coupon_rate": c}),
            initial_fixing=spot,
        )
        return price_mc(note, model, n_paths=50_000, seed=5).price

    solved = solve_to_par(pv_for_coupon, target=par_target(100.0), bracket=(0.0, 0.2))
    ts.params["coupon_rate"] = round(solved.param, 6)
    print(f"[L6] solved coupon-to-par: {solved.param:.4%} per period  (PV={solved.achieved_pv:.4f})")

    # L4/L5 — price the solved note and compute its Greeks.
    note = Autocallable.from_termsheet(ts, initial_fixing=spot)
    result = price_mc(note, model, n_paths=50_000, seed=5)
    greeks = bump_greeks(note, model, n_paths=200_000, seed=5)
    print(f"[L4] PV={result.price:.4f} (± {result.std_error:.4f})")
    print(f"[L5] delta={greeks.delta:.4f}  gamma={greeks.gamma:.4f}  "
          f"vega={greeks.vega:.2f}  rho={greeks.rho:.2f}")

    # L13 — render the indicative term sheet with a scenario-at-maturity table.
    md = render_term_sheet(
        ts,
        PricingSummary(result.price, result.std_error),
        maturity_scenarios(note, (0.4, 0.6, 0.8, 1.0, 1.2)),
    )
    print("\n" + "=" * 70 + "\n[L13] RENDERED TERM SHEET\n" + "=" * 70)
    print(md)


if __name__ == "__main__":
    main()
