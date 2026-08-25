"""Load an NSE F&O bhavcopy into a point-in-time, tradedness-flagged option chain.

The screen defaults are deliberately strict. NSE publishes a settlement price for every
listed contract whether or not anyone traded it; measured on this codebase (commit
``14cee5c``), only about half a typical chain trades on the day and only ~60% carries open
interest. Treating those prints as markets is how options backtests invent alpha.

Every quote leaves here in ``mark_provenance="settlement"`` — the untradeable raw state.
``SurfaceMarker`` (the next stage) resolves each to ``"traded"`` or ``"surface"``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

import pandas as pd

from spdt.optbt.chain import OptionChainSnapshot, OptionKey, OptionQuoteView


@dataclass(frozen=True)
class LiquidityScreen:
    """What counts as *evidence of a market* when calibrating and filling.

    ``otm_only`` exists because exchange settlements do not enforce put-call parity: the ITM
    half of a strike routinely inverts to a vol several points from its OTM twin, and the
    ITM print is the unreliable one (its error is amplified by a small vega). Consumed by
    ``SurfaceMarker``; carried here so loader and marker share one screen object.
    """

    min_contracts: float = 1.0
    min_open_interest: float = 1.0
    otm_only: bool = True
    moneyness_band: float | None = 4.0  # |log(K/F)| ≤ band·√τ, as in invert_chain
    iv_bounds: tuple[float, float] | None = (0.01, 3.0)


class ChainLoader:
    """One bhavcopy date → one :class:`OptionChainSnapshot`."""

    def __init__(
        self,
        *,
        frame_provider: Callable[[date], pd.DataFrame] | None = None,
        screen: LiquidityScreen | None = None,
        dividend_yield: float = 0.012,
    ) -> None:
        self._frame_provider = frame_provider or self._download
        self.screen = screen or LiquidityScreen()
        self._dividend_yield = dividend_yield

    @staticmethod
    def _download(as_of: date) -> pd.DataFrame:
        from spdt.data.ingest.nse_bhavcopy import download_fo_bhavcopy

        return download_fo_bhavcopy(as_of)

    def load(self, as_of: date, underlying: str) -> OptionChainSnapshot:
        """Every listed option for ``underlying`` on ``as_of``, tradedness-flagged."""
        frame = self._frame_provider(as_of).rename(columns=lambda c: c.strip())
        rows = frame[
            (frame["TckrSymb"] == underlying) & frame["OptnTp"].isin(["CE", "PE"])
        ].copy()
        if rows.empty:
            raise ValueError(f"no option rows for {underlying!r} in the {as_of} bhavcopy")
        rows["XpryDt"] = pd.to_datetime(rows["XpryDt"]).dt.date

        quotes: dict[OptionKey, OptionQuoteView] = {}
        for r in rows.itertuples(index=False):
            volume = float(getattr(r, "TtlTradgVol", 0.0) or 0.0)
            oi = float(getattr(r, "OpnIntrst", 0.0) or 0.0)
            traded = (
                volume >= self.screen.min_contracts and oi >= self.screen.min_open_interest
            )
            key = OptionKey(underlying, r.XpryDt, float(r.StrkPric), r.OptnTp == "CE")
            quotes[key] = OptionQuoteView(
                key=key,
                settlement_price=float(r.SttlmPric),
                contracts_traded=volume,
                open_interest=oi,
                bid=None,
                ask=None,
                traded=traded,
                mark=float(r.SttlmPric),
                mark_provenance="settlement",  # untradeable until SurfaceMarker resolves it
                implied_vol=None,
            )

        return OptionChainSnapshot(
            as_of=as_of,
            underlying=underlying,
            spot=float(rows["UndrlygPric"].dropna().iloc[0]),
            quotes=quotes,
            surface=None,
            ois_curve=None,
            dividend_yield=self._dividend_yield,
        )
