"""Futures-implied dividend yield — replace the flat assumption with an observed input.

Under cost-of-carry, ``F = S·exp((r − q)·T)``, so a traded index future implies the
market's own dividend expectation: ``q = r − ln(F/S)/T``. With a live futures quote (XTS)
and the FBIL rate this turns the snapshot's dividend yield from an assumption into a
derived market observable.

That single-contract inversion has one bad property: it divides by ``T``, so any error in
*spot* is amplified by ``1/T``. A stale index tick — the cash index printing a second behind
the futures — is exactly such an error, and on a 32-day contract a 0.2% spot lag becomes a
2.4% error in ``q``. Observed live on 2026-08-28: the NIFTY strip implied

    32d: q = −1.99%    60d: q = −0.87%    87d: q = −0.51%

A dividend yield does not have a term structure shaped like ``1/T``, and an *index* dividend
yield is never negative. The decay is the fingerprint of a fixed offset between the spot and
futures snapshots, not a dividend signal.

:func:`implied_dividend_yield_from_strip` removes it by never referencing spot. Fitting
``ln F = ln S* + (r − q)·T`` across the whole strip recovers the carry from the *slope*; spot
falls out into the intercept, where being wrong about it is harmless. On the same data the
strip's own adjacent-pair carries were 6.08% and 6.20% — flat, as a real carry curve should
be — giving q = +0.36% against the same 6.5% rate.
"""

from __future__ import annotations

from collections.abc import Sequence
from math import log

# Sane bounds for an implied *index* dividend yield. The floor is zero and not negotiable:
# the constituents of an equity index pay dividends or they pay none, so a negative implied
# yield is always an artefact and never an observation. It was −5%, loose enough to accept
# the −3.35% the live NIFTY feed produced on 2026-08-28 as if it were real.
#
# What a negative result actually means, and why falling back is right: cost-of-carry assumes
# the futures finance at ``r``. Indian index futures habitually do not — they carry a
# leverage/financing premium over the risk-free rate, so the strip prices at ``r + s − q``.
# Inverting for ``q`` while ignoring ``s`` charges the whole financing premium to dividends,
# and once ``s`` exceeds the true yield the answer goes negative. On the live feed the strip
# carried at 6.14% against a 5.26% risk-free rate: an 88bp financing premium, not a −0.88%
# dividend. When that happens the futures are informative about funding, not about dividends,
# so the honest move is to reject and keep the published yield.
_Q_MIN, _Q_MAX = 0.0, 0.10

# The strip's slope is only meaningful over a real lever arm; two contracts a week apart
# give a slope that is mostly quote noise.
_MIN_STRIP_SPAN_YEARS = 0.05


def _validated(q: float) -> float:
    if not _Q_MIN <= q <= _Q_MAX:
        raise ValueError(f"implausible implied dividend yield {q:.2%} — check the futures quote")
    return q


def implied_dividend_yield(spot: float, futures_price: float, t_years: float, r: float) -> float:
    """Invert cost-of-carry for ``q`` off a single contract. Prefer the strip form below.

    Kept for the one-contract case, where there is no slope to fit. Raises on degenerate
    inputs or implausible output.
    """
    if spot <= 0.0 or futures_price <= 0.0 or t_years <= 0.0:
        raise ValueError("implied dividend needs positive spot, futures price and maturity")
    return _validated(r - log(futures_price / spot) / t_years)


def implied_dividend_yield_from_strip(
    futures: Sequence[tuple[float, float]], r: float
) -> float:
    """Imply ``q`` from the slope of ``ln F`` against maturity across two or more contracts.

    ``futures`` is a sequence of ``(t_years, price)``. Spot is deliberately not a parameter:
    it is the input most likely to be stale relative to the futures, and the slope does not
    need it. Raises when the strip is too short, too narrow in maturity, or implies a yield
    outside :data:`_Q_MIN`–:data:`_Q_MAX`.
    """
    pts = sorted((t, f) for t, f in futures if t > 0.0 and f > 0.0)
    if len(pts) < 2:
        raise ValueError("implied dividend from a strip needs at least two dated futures")
    span = pts[-1][0] - pts[0][0]
    if span < _MIN_STRIP_SPAN_YEARS:
        raise ValueError(
            f"futures strip spans only {span:.3f}y — too short to fit a carry slope"
        )

    n = len(pts)
    sum_t = sum(t for t, _ in pts)
    sum_y = sum(log(f) for _, f in pts)
    sum_tt = sum(t * t for t, _ in pts)
    sum_ty = sum(t * log(f) for t, f in pts)
    denom = n * sum_tt - sum_t * sum_t
    if denom <= 0.0:
        raise ValueError("degenerate futures strip — maturities are not distinct")
    carry = (n * sum_ty - sum_t * sum_y) / denom
    return _validated(r - carry)
