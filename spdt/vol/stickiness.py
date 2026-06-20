"""Smile stickiness regimes — which one your delta assumes (L2).

When spot moves, what happens to the ATM vol depends on how the smile "sticks":

* **Sticky-strike** — the vol *per fixed strike* σ(K) is unchanged. The at-the-money point
  therefore rides along the *existing skew*: when spot falls, the new ATM strike sits at a lower
  moneyness where (for an equity put-skew) vol is higher, so realised ATM vol *rises*. This adds
  a skew term to delta: ∂V/∂S picks up ∂V/∂σ · ∂σ_atm/∂S.
* **Sticky-moneyness / sticky-delta** — the vol *per fixed moneyness* σ(k) is unchanged, so the
  ATM vol does not move with spot and the Black-Scholes delta is the whole story.

A desk must say which regime its hedges assume — getting it wrong mis-states delta on every
skewed name. These helpers take an ``iv(k, T)`` surface callable so they're model-agnostic.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable

IvKT = Callable[[float, float], float]


class StickyRegime(str, Enum):
    STRIKE = "sticky_strike"
    MONEYNESS = "sticky_moneyness"  # ≈ sticky-delta for these purposes


def atm_vol_under_move(iv_kt: IvKT, t: float, log_return: float, regime: StickyRegime) -> float:
    """ATM vol *after* a spot move of ``log_return = ln(S'/S)``, under the chosen regime.

    Sticky-moneyness leaves ATM vol at ``σ(0, t)``; sticky-strike rides the existing skew, so the
    new ATM vol is the old surface read at the moneyness the move opened up, ``σ(log_return, t)``
    (spot down ⇒ negative log-return ⇒ vol read at negative k ⇒ higher on an equity put-skew).
    """
    if regime is StickyRegime.MONEYNESS:
        return iv_kt(0.0, t)
    return iv_kt(log_return, t)


def skew_delta_adjustment(
    iv_kt: IvKT, t: float, spot: float, vega: float, *, dk: float = 1e-3
) -> float:
    """The extra delta a **sticky-strike** regime implies vs the Black-Scholes (sticky-money) delta.

    ``∂V/∂S |_skew = vega · ∂σ_atm/∂S``, and under sticky-strike ``∂σ_atm/∂S = (∂σ/∂k)/S`` (the ATM
    point rides the skew as spot moves). For an equity put-skew (∂σ/∂k < 0) this is *negative* for
    a long-vega option — spot up lowers ATM vol, so the realised delta is below the BS delta.
    """
    dsig_dk = (iv_kt(dk, t) - iv_kt(-dk, t)) / (2.0 * dk)
    return vega * dsig_dk / spot
