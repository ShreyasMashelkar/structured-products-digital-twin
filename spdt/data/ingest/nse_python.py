"""NSE live option-chain source via ``nsepython`` — intraday ingestion (alternative to the EOD bhavcopy).

The bhavcopy source (:mod:`spdt.data.ingest.nse_bhavcopy`) reads the **end-of-day** archive file, which
only exists after the close on a trading day. This source instead calls NSE's **live option-chain JSON**
through ``nsepython`` (``nse_optionchain_scrapper``), so it works *intraday* — spot + every strike/expiry
with a last-traded price — and emits the same :class:`RawMarketData`.

As with the bhavcopy source, parse and fetch are split: :func:`parse_option_chain` is a pure function over
the JSON ``nsepython`` returns (unit-tested on a fixture), while :meth:`NsePythonSource.fetch` adds the
network call. Rates are **not** provided by NSE — pair this with FBIL-bootstrapped ``rate_instruments`` (the
same ones the bhavcopy live path uses); without them a flat fallback rate is applied.

Caveats (deliberately honest): ``nsepython`` scrapes NSE's unofficial endpoints, which are rate-limited and
block non-browser / datacenter IPs, so this is best run from a normal machine during Indian market hours. It
is opt-in; the synthetic source remains the reproducible default.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from spdt.core.types import SourceTag, Underlying
from spdt.data.curate.rate_bootstrap import RateInstrument, bootstrap_zero_rates
from spdt.data.ingest import RawMarketData, RawOptionQuote


def _parse_expiry(raw: str) -> date:
    """NSE expiries come as ``'26-Jun-2026'`` — parse to a date."""
    return datetime.strptime(raw, "%d-%b-%Y").date()


def parse_option_chain(
    payload: dict[str, Any],
    as_of: date,
    underlying: Underlying,
    *,
    risk_free_rate: float,
    funding_spread: float,
    dividend_yield: float,
    rate_instruments: list[RateInstrument] | None = None,
) -> RawMarketData:
    """Turn the ``nse_optionchain_scrapper`` JSON into :class:`RawMarketData` for one underlying.

    Keeps CE/PE legs with a positive last-traded price; the spot is NSE's own ``underlyingValue``. If
    ``rate_instruments`` (FBIL) are supplied the OIS curve is bootstrapped from them, else a flat
    ``risk_free_rate`` is used. Tagged ``OBSERVED`` — it is real, if intraday, market data.
    """
    records = payload.get("records", {})
    spot = float(records["underlyingValue"])
    if spot <= 0.0:
        raise ValueError(f"nsepython returned a non-positive spot for {underlying!r}")

    quotes: list[RawOptionQuote] = []
    for row in records.get("data", []):
        strike = float(row["strikePrice"])
        expiry = _parse_expiry(row["expiryDate"])
        for tp, is_call in (("CE", True), ("PE", False)):
            leg = row.get(tp)
            if leg and float(leg.get("lastPrice", 0.0)) > 0.0:
                quotes.append(RawOptionQuote(expiry, strike, is_call, float(leg["lastPrice"])))
    if not quotes:
        raise ValueError(f"no priced option legs for {underlying!r} in the nsepython chain")

    if rate_instruments:
        ois_zero_rates = bootstrap_zero_rates(as_of, rate_instruments)
    else:
        ois_zero_rates = {e: risk_free_rate for e in sorted({q.expiry for q in quotes})}
    pillars = sorted(ois_zero_rates)
    funding_spread_knots = {pillars[0]: funding_spread, pillars[-1]: funding_spread}

    return RawMarketData(
        date=as_of,
        underlying=underlying,
        spot=spot,
        option_chain=tuple(quotes),
        ois_zero_rates=ois_zero_rates,
        funding_spread_knots=funding_spread_knots,
        dividend_yield=dividend_yield,
        source=SourceTag.OBSERVED,
    )


class NsePythonSource:
    """Live intraday option-chain source via ``nsepython``, implementing ``MarketDataSource``."""

    def __init__(
        self,
        *,
        risk_free_rate: float = 0.065,
        funding_spread: float = 0.012,
        dividend_yield: float = 0.013,
        rate_instruments: list[RateInstrument] | None = None,
    ) -> None:
        self.risk_free_rate = risk_free_rate
        self.funding_spread = funding_spread
        self.dividend_yield = dividend_yield
        self.rate_instruments = rate_instruments

    def fetch(self, as_of: date, underlying: Underlying = "NIFTY") -> RawMarketData:
        """Pull the live chain via ``nsepython`` and build a snapshot input (network I/O).

        ``nsepython`` is imported lazily so the dependency is only needed when the live path is used.
        The returned chain is *current* — ``as_of`` only tags the record and anchors the rate curve.
        """
        from nsepython import nse_optionchain_scrapper  # lazy: optional dependency

        payload = nse_optionchain_scrapper(underlying)
        return parse_option_chain(
            payload, as_of, underlying,
            risk_free_rate=self.risk_free_rate, funding_spread=self.funding_spread,
            dividend_yield=self.dividend_yield, rate_instruments=self.rate_instruments,
        )
