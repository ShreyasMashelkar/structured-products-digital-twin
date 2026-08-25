"""Invert the street's worst-of autocallable shelf for implied correlation (L8).

Run with::

    SPDT_SEC_USER_AGENT="you <you@example.com>" python3 -m spdt.validation.run_correlation

Worst-of notes are roughly two thirds of current US structured-note issuance, and their value
turns on a parameter with no liquid market: the correlation between the underlyings. Each name's
volatility *is* observable from listed options, so pinning those leaves correlation as the one
unknown, and the issuer's disclosed estimated value is one equation — exactly enough to solve
for it. The output is therefore a reading of what the street is marking, taken from notes that
actually priced.

Caveats that bound every number below, in order of severity:

1. **Vols are current, the notes are not.** The free CBOE feed serves only today's chain, so a
   note priced 100 days ago is inverted against today's volatilities. ``stale`` reports the gap
   per note; treat anything beyond a week as indicative.
2. **Flat ATM vol, no skew.** Each leg is a single ATM number, whereas the knock-in sits at
   50–70% of spot, deep in the put wing where the real surface is much higher. The dealer prices
   the whole surface.
3. **Equicorrelation.** One equation identifies one number, so a single pairwise correlation
   stands in for the whole matrix.

Consequently the implied correlations here are an **upper bound on what the street is marking**,
not a measurement of it — the omitted skew and the stale vols both push the solved correlation
up. They are reported because the direction and magnitude are informative even so.
"""

from datetime import date, timedelta
from functools import lru_cache

import numpy as np

from spdt.data import build_snapshot
from spdt.data.curate import invert_chain
from spdt.data.ingest.cboe import CboeSource
from spdt.data.ingest.edgar import fetch_filing_text, parse_filing, search_filings
from spdt.validation.edgar_benchmark import (
    implied_correlation,
    implied_correlation_scale,
    price_worst_of_filing,
    realised_correlation,
)
from spdt.vol.surface import VolSurface

R, Q, FUNDING = 0.042, 0.010, 0.012
TODAY = date.today()


@lru_cache(maxsize=None)
def surface_for(ticker: str) -> VolSurface | None:
    try:
        raw = CboeSource().fetch(TODAY, ticker)
        snap = build_snapshot(raw)
        pts = invert_chain(
            raw, snap.ois_curve, moneyness_band=1.0, iv_bounds=(0.05, 3.0),
            otm_only=True, min_open_interest=1.0,
        )
        surf = VolSurface.calibrate(pts, ticker, min_points_per_slice=8)
        return surf if surf.slices else None
    except Exception as exc:
        print(f"    [vol miss] {ticker}: {type(exc).__name__}")
        return None


def atm_vol(ticker: str, tau: float) -> float | None:
    s = surface_for(ticker)
    if s is None:
        return None
    try:
        return s.implied_vol_kt(0.0, tau)
    except Exception:
        return None


@lru_cache(maxsize=None)
def closes(ticker: str) -> tuple:
    """Six months of daily closes from Yahoo's chart endpoint — the realised-shape input.

    The bare endpoint rather than yfinance, whose session-level rate limiting blocks whole
    runs; one request per name with an lru_cache is comfortably inside the public allowance.
    """
    import json
    import ssl
    import urllib.request

    import certifi

    ctx = ssl.create_default_context(cafile=certifi.where())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=6mo&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
        payload = json.load(r)
    vals = payload["chart"]["result"][0]["indicators"]["quote"][0]["close"]
    return tuple(c for c in vals if c)


def main() -> None:
    refs = search_filings(start=TODAY - timedelta(days=120), end=TODAY, limit=600)
    print(f"filings scanned: {len(refs)}")

    rows = []
    scales: list[float] = []
    seen = set()
    for r in refs:
        try:
            f = parse_filing(fetch_filing_text(r), issuer=r.issuer, url=r.url, filed=r.filed)
        except Exception:
            continue
        if not (f.is_benchmarkable and f.is_worst_of and len(f.starting_values) >= 2):
            continue
        key = (f.cusip or "", tuple(sorted(t for t, _ in f.starting_values)),
               f.estimated_value, f.coupon_per_period, f.maturity_date)
        if key in seen:
            continue  # EDGAR returns the same supplement under several hits
        seen.add(key)

        tau = f.tenor_years
        ev = f.estimated_value_pct
        if tau is None or ev is None:
            continue  # is_benchmarkable implies both, but bind them so the guarantee is local
        vols = {}
        for ticker, _ in f.starting_values:
            v = atm_vol(ticker, tau)
            if v is not None:
                vols[ticker] = v
        if len(vols) < len(f.starting_values):
            continue  # need every leg's vol, or correlation is not identified

        rho = implied_correlation(
            f, vols=vols, r=R, q=Q, funding_spread=FUNDING, n_paths=40_000
        )
        # When no correlation reconciles the two, the *direction* is the finding: price the
        # note at the correlation that minimises its value (most dispersion, worst worst-of)
        # and see whether even that still exceeds the issuer's figure.
        floor_pv = price_worst_of_filing(
            f, vols=vols, rho=-0.20, r=R, q=Q, funding_spread=FUNDING, n_paths=40_000
        )
        direction = "" if rho is not None else (
            f" model>{floor_pv:.1f} vs EV {ev:.1f} (too HIGH at every rho)"
            if floor_pv > ev else " (too LOW at every rho)"
        )
        # The shaped pass: same one-parameter identification, but scaling the market's own
        # realised correlation structure instead of a flat matrix. scale < 1 reads directly as
        # "the issuer marked correlation above realised", which is the checkable claim.
        scale = None
        try:
            series = {t: np.array(closes(t)) for t in vols}
            base = realised_correlation(series)
        except Exception:
            base = None
        if base is not None:
            scale = implied_correlation_scale(
                f, vols=vols, base_corr=base, r=R, q=Q, funding_spread=FUNDING, n_paths=40_000
            )
        stale = (TODAY - f.pricing_date).days if f.pricing_date else None
        rows.append((f, vols, rho, stale, floor_pv))
        if scale is not None:
            scales.append(scale)
        names = "/".join(vols)
        rho_s = f"{rho:.3f}" if rho is not None else "unreachable"
        scale_s = f"{scale:.2f}" if scale is not None else "n/a"
        print(
            f"  {names:24s} T={tau:.2f}y ki={f.knock_in or 0:.2f} cpn/q={100 * (f.coupon_per_period or 0.0) / f.denomination:5.2f}% "
            f"EV={ev:6.2f} vols={[round(v,2) for v in vols.values()]} rho={rho_s} scale={scale_s:>5s} stale={stale}d{direction}"
        )

    solved = [(f, v, rho, s) for f, v, rho, s, _ in rows if rho is not None]
    too_high = sum(
        1 for f, _, rho, _, fl in rows
        if rho is None and f.estimated_value_pct is not None and fl > f.estimated_value_pct
    )
    print(f"\nworst-of notes priced: {len(rows)}   correlation solved: {len(solved)}")
    print(f"unreachable: {len(rows)-len(solved)}  of which model too HIGH at every rho: {too_high}")
    if scales:
        print(
            f"realised-shape scale: solved {len(scales)}, mean {np.mean(scales):.2f} "
            f"(< 1 means the street marks correlation above realised)"
        )
    if solved:
        rhos = np.array([rho for _, _, rho, _ in solved])
        print(f"implied correlation: mean={rhos.mean():.3f} median={np.median(rhos):.3f} "
              f"sd={rhos.std(ddof=1) if len(rhos)>1 else 0:.3f} min={rhos.min():.3f} max={rhos.max():.3f}")
        n2 = [r for f, _, r, _ in solved if len(f.starting_values) == 2]
        n3 = [r for f, _, r, _ in solved if len(f.starting_values) >= 3]
        if n2:
            print(f"  2 underlyings (n={len(n2)}): mean={np.mean(n2):.3f}")
        if n3:
            print(f"  3+ underlyings (n={len(n3)}): mean={np.mean(n3):.3f}")


if __name__ == "__main__":
    main()
