"""Delta-hedge the note along the path that actually happened (L8).

Pricing answers "what is this worth?". This answers the question a desk is actually judged on:
**"if we had sold it and hedged it, what would we have made?"** Those come apart, and the gap
between them is where structured-products desks lose money.

The theoretical argument says a sold option, delta-hedged continuously in a frictionless market
under the model's own dynamics, returns exactly the premium. Every word of that is false in
practice, and each failure is measured separately here:

* **Discrete rebalancing.** Hedging daily rather than continuously leaves a gamma-driven
  residual whose sign depends on whether realised vol came in under or over the vol sold.
* **Transaction costs.** Every rebalance crosses a spread. Cost scales with turnover, so it
  rises with rebalancing frequency exactly as discretisation error falls — the two effects
  trade off, and the optimum is an empirical question, not a theoretical one.
* **Gaps.** A barrier product's delta is discontinuous at the barrier. An overnight gap through
  it cannot be hedged at any rebalancing frequency, and produces a loss no amount of diligence
  prevents. This is the risk a desk reserves against rather than hedges.
* **The wrong model.** The hedge uses model deltas. If realised dynamics differ from the model's
  — and they do — the hedge is systematically mis-sized.

Run on a **realised** path, not simulated paths: simulating from the same model used to compute
the deltas assumes away the fourth failure entirely and would report a flattering number.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import date, timedelta
from math import exp

import numpy as np

from spdt.pricing.engine import price_mc
from spdt.pricing.models.bs import BlackScholes
from spdt.products.catalog import Autocallable

_DAYS_PER_YEAR = 365.0


@dataclass(frozen=True)
class HedgeStep:
    """One rebalance along the realised path."""

    t: float
    spot: float
    delta: float
    traded: float
    cost: float
    cash: float


@dataclass(frozen=True)
class HedgeBacktestResult:
    """Realised hedging performance of one sold, dynamically-hedged note."""

    premium: float  # what the note was sold for, in points of par
    hedge_pnl: float  # terminal cash minus what was paid out
    payout: float  # what the investor actually received
    total_cost: float  # cumulative transaction cost
    n_rebalances: int
    # Summed |Δdelta| × spot: the cash value traded, not a share count. On an index at 15,000
    # against a notional of 100, share counts are ~1e-4 and carry no intuition; cash traded is
    # directly comparable to the premium and to the transaction cost.
    turnover: float
    autocalled: bool
    steps: tuple[HedgeStep, ...]

    @property
    def pnl_pct_of_notional(self) -> float:
        return self.hedge_pnl

    @property
    def cost_share_of_pnl(self) -> float:
        """Transaction cost as a fraction of the premium — the fee the hedge itself consumed."""
        return self.total_cost / self.premium if self.premium else float("nan")


def _autocallable_delta(
    note: Autocallable,
    model: BlackScholes,
    t: float,
    *,
    n_paths: int = 20_000,
    seed: int = 0,
    rel_bump: float = 0.005,
) -> float:
    """Model delta of the remaining note at time ``t``, by central bump under common randoms.

    The note is *aged*: observations already passed are dropped and the remaining ones rebased
    to the current date, so what is hedged is the residual instrument rather than the original
    one. Hedging the original terms after an observation has passed would carry a delta for a
    cashflow that has already been decided.
    """
    remaining = tuple(round(obs - t, 6) for obs in note.observation_times if obs > t + 1e-9)
    if not remaining:
        return 0.0
    aged = dataclasses.replace(note, observation_times=remaining)

    def pv(spot: float) -> float:
        return price_mc(
            aged, dataclasses.replace(model, spot=spot), n_paths=n_paths, seed=seed
        ).price

    h = model.spot * rel_bump
    return (pv(model.spot + h) - pv(model.spot - h)) / (2 * h)


def backtest_hedge_on_path(
    note: Autocallable,
    path_times: np.ndarray,
    path_spots: np.ndarray,
    *,
    vol: float,
    r: float,
    q: float,
    premium: float | None = None,
    spread_bps: float = 2.0,
    n_paths: int = 20_000,
    seed: int = 0,
) -> HedgeBacktestResult:
    """Sell ``note`` at inception and delta-hedge it along a realised ``(times, spots)`` path.

    ``spread_bps`` is the half-spread crossed on each hedge trade, in basis points of spot. For
    a liquid index future this is genuinely 1–3bps; it is a parameter rather than a constant
    because it is the single assumption the result is most sensitive to, and a reader must be
    able to see and vary it.

    The note is struck at the path's first level. Cash accrues at ``r``. The hedge is a spot
    position, so financing is charged on the borrowed cash rather than modelled as a repo.
    """
    if len(path_times) != len(path_spots) or len(path_times) < 2:
        raise ValueError("path_times and path_spots must align and contain at least two points")

    s0 = float(path_spots[0])
    struck = dataclasses.replace(note, initial_fixing=s0)
    model0 = BlackScholes(spot=s0, r=r, q=q, sigma=vol)
    if premium is None:
        premium = price_mc(struck, model0, n_paths=n_paths, seed=seed).price

    cash = float(premium)
    shares = 0.0
    total_cost = 0.0
    turnover = 0.0
    half_spread = spread_bps * 1e-4
    steps: list[HedgeStep] = []

    # Track the note's life along the path: coupons paid out, and early redemption.
    missed = 0.0
    coupons_paid = 0.0
    autocalled = False
    autocall_index: int | None = None
    obs = list(note.observation_times)
    last_obs = obs[-1] if obs else 0.0

    for i in range(len(path_times) - 1):
        t = float(path_times[i])
        spot = float(path_spots[i])
        if autocalled:
            break

        model_t = BlackScholes(spot=spot, r=r, q=q, sigma=vol)
        delta = _autocallable_delta(struck, model_t, t, n_paths=n_paths, seed=seed)
        trade = delta - shares
        cost = half_spread * abs(trade) * spot
        cash -= trade * spot + cost
        total_cost += cost
        turnover += abs(trade) * spot
        shares = delta
        steps.append(HedgeStep(t, spot, delta, trade, cost, cash))

        dt = float(path_times[i + 1]) - t
        cash *= exp(r * dt)
        cash += shares * spot * (exp(q * dt) - 1.0)  # dividends received on the hedge

        # Any observation falling in (t, t+dt] settles at the next path point.
        nxt = float(path_times[i + 1])
        spot_next = float(path_spots[i + 1])
        for j, obs_t in enumerate(obs):
            if t < obs_t <= nxt + 1e-9:
                if spot_next >= note.coupon_barrier * s0:
                    pay = (missed + 1.0) * note.coupon_rate * note.notional if note.memory else (
                        note.coupon_rate * note.notional
                    )
                    coupons_paid += pay
                    cash -= pay
                    missed = 0.0
                elif note.memory:
                    missed += 1.0
                if obs_t < last_obs - 1e-9 and spot_next >= note.autocall_level * s0:
                    autocalled = True
                    autocall_index = j
                    break

    # Unwind the hedge and settle the note.
    s_final = float(path_spots[-1]) if not autocalled else float(
        path_spots[min(len(path_spots) - 1, len(steps))]
    )
    unwind_cost = half_spread * abs(shares) * s_final
    cash += shares * s_final - unwind_cost
    total_cost += unwind_cost

    if autocalled:
        redemption = note.notional
    elif s_final <= note.knock_in * s0:
        redemption = note.notional * s_final / s0
    else:
        redemption = note.notional
    cash -= redemption

    return HedgeBacktestResult(
        premium=float(premium),
        hedge_pnl=float(cash),
        payout=float(coupons_paid + redemption),
        total_cost=float(total_cost),
        n_rebalances=len(steps),
        turnover=float(turnover),
        autocalled=autocalled,
        steps=tuple(steps),
    )


def rebalance_frequency_sweep(
    note: Autocallable,
    path_times: np.ndarray,
    path_spots: np.ndarray,
    *,
    vol: float,
    r: float,
    q: float,
    every: tuple[int, ...] = (1, 2, 5, 10, 21),
    spread_bps: float = 2.0,
    n_paths: int = 20_000,
    seed: int = 0,
) -> dict[int, HedgeBacktestResult]:
    """Re-run the hedge taking every ``k``-th point of the path, for each ``k``.

    This is the trade-off the theory cannot resolve. Hedging more often shrinks the
    discretisation error and grows the transaction cost; where the total is minimised depends on
    the spread and on the realised path, so it must be measured. A desk that rebalances daily
    "because that is what you do" is choosing a point on this curve without looking at it.
    """
    out: dict[int, HedgeBacktestResult] = {}
    for k in every:
        idx = np.arange(0, len(path_times), k)
        if idx[-1] != len(path_times) - 1:
            idx = np.append(idx, len(path_times) - 1)
        out[k] = backtest_hedge_on_path(
            note, path_times[idx], path_spots[idx],
            vol=vol, r=r, q=q, spread_bps=spread_bps, n_paths=n_paths, seed=seed,
        )
    return out


def realised_path_from_archive(
    issue_date: date, tenor: float, underlying: str = "NIFTY", *, samples: int = 24
) -> tuple[np.ndarray, np.ndarray]:
    """Sample the realised index path from the exchange archive over the note's life.

    Sampled rather than daily because each point is an archive fetch. That is a real limitation
    and it biases the result *optimistically*: coarser sampling hides intra-period moves, so the
    measured discretisation cost understates a daily hedger's, and gap losses between samples go
    unseen. Daily granularity needs a bulk price history, not per-day archive reads.
    """
    from spdt.validation.realized import _spot_on

    times: list[float] = []
    spots: list[float] = []
    for i in range(samples + 1):
        t = tenor * i / samples
        target = issue_date + timedelta(days=round(t * _DAYS_PER_YEAR))
        try:
            _, spot = _spot_on(target, underlying)
        except Exception:  # noqa: BLE001 - a missing session shortens the sample, not fatal
            continue
        times.append(t)
        spots.append(spot)
    return np.array(times), np.array(spots)
