"""US Treasury daily par-yield curve — the USD rates the flat placeholder stood in for (L1).

The CBOE path shipped with ``risk_free_rate = 0.042`` hardcoded, documented as "a defensible
placeholder, whereas the INR curve would be simply wrong". Defensible, but measurably off: the
actual curve runs ~3.8% at one month to ~4.7% at ten years, so a flat 4.2% mis-discounts the
front of every US note by ~40bp and the long end the other way — and it silently freezes rate
information as of the day the constant was typed.

Treasury publishes the daily par-yield curve as a keyless CSV. Par yields are coupon-bond
yields, not zeros; the bootstrap below converts them properly (semi-annual par coupons, the
standard recursion) rather than pretending a 10y par yield is a 10y zero rate, which would
overstate long-end discounting exactly where a 3-year note's funding leg lives.

Treasury yields are not SOFR OIS — they carry a small (usually negative, single-digit bps)
swap spread. That error is an order of magnitude smaller than the one being removed, and the
source is official, keyless and durable; the honest upgrade path is FRED's SOFR swap series,
which needs an API key.
"""

from __future__ import annotations

import ssl
import urllib.request
from datetime import date
from math import exp
from pathlib import Path

try:  # certifi's CA bundle — robust across machines (esp. macOS python.org builds)
    import certifi

    _SSL_CONTEXT: ssl.SSLContext | None = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover - falls back to the system trust store
    _SSL_CONTEXT = None

_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all?"
    "type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv"
)
_USER_AGENT = "Mozilla/5.0 (compatible; spdt-research/1.0)"
_CACHE_DIR = Path("data/ust_cache")

# CSV column header -> tenor in years. Missing columns on old vintages are simply skipped.
_TENORS: dict[str, float] = {
    "1 Mo": 1 / 12, "1.5 Month": 1.5 / 12, "2 Mo": 2 / 12, "3 Mo": 0.25, "4 Mo": 4 / 12,
    "6 Mo": 0.5, "1 Yr": 1.0, "2 Yr": 2.0, "3 Yr": 3.0, "5 Yr": 5.0, "7 Yr": 7.0,
    "10 Yr": 10.0, "20 Yr": 20.0, "30 Yr": 30.0,
}


def fetch_par_yields(as_of: date, *, timeout: float = 30.0, cache: bool = True) -> dict[float, float]:
    """Latest published par yields on or before ``as_of``, as ``{tenor_years: decimal_yield}``.

    Cached per fetch-date: the file is one year's history, so a single download serves every
    request for the rest of the session and the cache is inspectable CSV.
    """
    path = _CACHE_DIR / f"ust_{as_of.year}_{date.today():%Y%m%d}.csv"
    if cache and path.exists():
        text = path.read_text()
    else:
        url = _URL.format(year=as_of.year)
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(  # noqa: S310 (fixed official host)
            request, timeout=timeout, context=_SSL_CONTEXT
        ) as response:
            text = response.read().decode()
        if cache:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    header = [h.strip().strip('"') for h in lines[0].split(",")]
    best: tuple[date, dict[float, float]] | None = None
    for line in lines[1:]:
        cells = [c.strip().strip('"') for c in line.split(",")]
        try:
            month, day, year = cells[0].split("/")
            row_date = date(int(year), int(month), int(day))
        except (ValueError, IndexError):
            continue
        if row_date > as_of:
            continue
        yields: dict[float, float] = {}
        for name, value in zip(header[1:], cells[1:]):
            if name in _TENORS and value:
                try:
                    yields[_TENORS[name]] = float(value) / 100.0
                except ValueError:
                    continue
        if yields and (best is None or row_date > best[0]):
            best = (row_date, yields)
    if best is None:
        raise ValueError(f"no Treasury curve published on or before {as_of}")
    return best[1]


def bootstrap_zero_curve(par_yields: dict[float, float]) -> dict[float, float]:
    """Continuously-compounded zero rates from par yields, by the standard par-bond recursion.

    A T-year par bond pays coupon ``c = y·notional`` semi-annually and redeems at par, so::

        1 = (y/2)·Σ df(t_i) + df(T)

    solved tenor by tenor for ``df(T)`` with earlier discount factors log-linearly
    interpolated. Tenors up to one year are quoted on money-market-like instruments and are
    treated as zeros directly — the coupon correction inside a year is under a basis point,
    far below the par/zero gap this function exists to remove at the long end (~10bp at 10y
    on an upward-sloping curve).
    """
    from scipy.optimize import brentq

    zeros: dict[float, float] = {}
    for t in sorted(par_yields):
        y = par_yields[t]
        if t <= 1.0:
            zeros[t] = y
            continue
        pillars = sorted(zeros)
        coupon_times = [i / 2.0 for i in range(1, int(round(t * 2)))]

        # Coupons that fall BETWEEN the last solved pillar and the tenor being solved discount
        # at rates interpolated toward the unknown z(t) itself, so the pillar is found as the
        # root of the par equation rather than by the flat-extrapolation shortcut. The shortcut
        # prices, say, a 1.5y coupon at the 1y zero while solving the 2y — on a steep step
        # that biases the pillar by several basis points, and unlike a convention it is not a
        # choice anyone would defend, just an easier recursion.
        def price_error(z_t: float) -> float:
            def df(u: float) -> float:
                if u <= pillars[0]:
                    rate = zeros[pillars[0]]
                elif u <= pillars[-1]:
                    rate = _interp(u, pillars, [zeros[p] for p in pillars])
                else:  # between the last pillar and t: interpolate toward the candidate z_t
                    last = pillars[-1]
                    w = (u - last) / (t - last)
                    rate = zeros[last] * (1.0 - w) + z_t * w
                return exp(-rate * u)

            annuity = sum(df(u) for u in coupon_times)
            return (y / 2.0) * annuity + (1.0 + y / 2.0) * exp(-z_t * t) - 1.0

        lo, hi = -0.05, 1.5
        if price_error(lo) * price_error(hi) > 0:
            raise ValueError(f"par bootstrap produced a non-positive df at {t}y")
        zeros[t] = float(brentq(price_error, lo, hi, xtol=1e-12))
    return zeros


def _interp(u: float, xs: list[float], ys: list[float]) -> float:
    if u >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if u <= xs[i]:
            w = (u - xs[i - 1]) / (xs[i] - xs[i - 1])
            return ys[i - 1] * (1.0 - w) + ys[i] * w
    return ys[-1]


def usd_zero_curve(as_of: date, *, timeout: float = 30.0, cache: bool = True) -> dict[float, float]:
    """One call: fetch the latest Treasury curve and bootstrap it to zeros."""
    return bootstrap_zero_curve(fetch_par_yields(as_of, timeout=timeout, cache=cache))
