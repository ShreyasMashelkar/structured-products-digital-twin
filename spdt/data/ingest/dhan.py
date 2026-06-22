"""DhanHQ option-chain source — reliable keyed live ingestion (DhanHQ v2 API).

An *official broker* alternative to scraping NSE: DhanHQ's Option Chain API returns the live chain
(spot + per-strike call/put last price, IV, OI, greeks) for an authenticated account, so — unlike the
public NSE endpoints — it works from any IP without an anti-bot block. Requires a Dhan account; the
``client-id`` / ``access-token`` are read from the environment (``DHAN_CLIENT_ID`` / ``DHAN_ACCESS_TOKEN``)
and never logged.

Dhan returns **one expiry per call**, so to build a surface this fetches the nearest few expiries
(respecting the 1-request-per-3-seconds limit) and unions their legs. Parse and network are split:
:func:`parse_chain_legs` / :func:`build_raw_market_data` are pure (unit-tested on a fixture), while
:meth:`DhanSource.fetch` adds the HTTP. Rates still come from FBIL (pair via ``rate_instruments``).
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import date, datetime

from spdt.core.types import SourceTag, Underlying
from spdt.data.curate.rate_bootstrap import RateInstrument, bootstrap_zero_rates
from spdt.data.ingest import RawMarketData, RawOptionQuote

_BASE = "https://api.dhan.co/v2"
_NIFTY_SCRIP = 13          # DhanHQ security id for the NIFTY index
_INDEX_SEG = "IDX_I"       # index-options segment


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def parse_chain_legs(oc: dict, expiry: date) -> list[RawOptionQuote]:
    """Map one expiry's ``data.oc`` block (strike → {ce, pe}) to priced option quotes."""
    quotes: list[RawOptionQuote] = []
    for strike_str, legs in oc.items():
        strike = float(strike_str)
        for key, is_call in (("ce", True), ("pe", False)):
            leg = legs.get(key)
            if leg and float(leg.get("last_price", 0.0)) > 0.0:
                quotes.append(RawOptionQuote(expiry, strike, is_call, float(leg["last_price"])))
    return quotes


def build_raw_market_data(
    spot: float,
    quotes: list[RawOptionQuote],
    as_of: date,
    *,
    risk_free_rate: float,
    funding_spread: float,
    dividend_yield: float,
    rate_instruments: list[RateInstrument] | None = None,
) -> RawMarketData:
    """Assemble :class:`RawMarketData` from a Dhan-sourced spot + option legs (+ FBIL rates)."""
    if spot <= 0.0:
        raise ValueError("Dhan returned a non-positive spot")
    if not quotes:
        raise ValueError("no priced option legs in the Dhan chain")
    if rate_instruments:
        ois_zero_rates = bootstrap_zero_rates(as_of, rate_instruments)
    else:
        ois_zero_rates = {e: risk_free_rate for e in sorted({q.expiry for q in quotes})}
    pillars = sorted(ois_zero_rates)
    funding_spread_knots = {pillars[0]: funding_spread, pillars[-1]: funding_spread}
    return RawMarketData(
        date=as_of,
        underlying="NIFTY",
        spot=spot,
        option_chain=tuple(quotes),
        ois_zero_rates=ois_zero_rates,
        funding_spread_knots=funding_spread_knots,
        dividend_yield=dividend_yield,
        source=SourceTag.OBSERVED,
    )


class DhanSource:
    """DhanHQ v2 option-chain source implementing the ``MarketDataSource`` interface."""

    def __init__(
        self,
        *,
        client_id: str | None = None,
        access_token: str | None = None,
        scrip: int = _NIFTY_SCRIP,
        segment: str = _INDEX_SEG,
        n_expiries: int = 4,
        rate_limit_s: float = 3.0,
        risk_free_rate: float = 0.065,
        funding_spread: float = 0.012,
        dividend_yield: float = 0.013,
        rate_instruments: list[RateInstrument] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.client_id = client_id or os.environ.get("DHAN_CLIENT_ID")
        self.access_token = access_token or os.environ.get("DHAN_ACCESS_TOKEN")
        self.scrip = scrip
        self.segment = segment
        self.n_expiries = n_expiries
        self.rate_limit_s = rate_limit_s
        self.risk_free_rate = risk_free_rate
        self.funding_spread = funding_spread
        self.dividend_yield = dividend_yield
        self.rate_instruments = rate_instruments
        self.timeout = timeout

    def _post(self, path: str, body: dict) -> dict:
        if not self.client_id or not self.access_token:
            raise RuntimeError(
                "Dhan credentials missing — set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN"
            )
        request = urllib.request.Request(
            f"{_BASE}{path}",
            data=json.dumps(body).encode(),
            headers={
                "access-token": self.access_token,
                "client-id": self.client_id,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 (fixed host)
            return json.loads(response.read())

    def _expiries_on_or_after(self, as_of: date) -> list[str]:
        body = {"UnderlyingScrip": self.scrip, "UnderlyingSeg": self.segment}
        listed = self._post("/optionchain/expirylist", body).get("data", [])
        future = sorted(e for e in listed if _parse_date(e) >= as_of)
        return future[: self.n_expiries]

    def fetch(self, as_of: date, underlying: Underlying = "NIFTY") -> RawMarketData:
        """Pull the nearest expiries' chains via DhanHQ and build a snapshot input (network I/O)."""
        spot = 0.0
        quotes: list[RawOptionQuote] = []
        for i, exp in enumerate(self._expiries_on_or_after(as_of)):
            if i:
                time.sleep(self.rate_limit_s)  # respect Dhan's 1-req/3s limit
            body = {"UnderlyingScrip": self.scrip, "UnderlyingSeg": self.segment, "Expiry": exp}
            data = self._post("/optionchain", body).get("data", {})
            spot = spot or float(data.get("last_price", 0.0))
            quotes.extend(parse_chain_legs(data.get("oc", {}), _parse_date(exp)))
        return build_raw_market_data(
            spot, quotes, as_of, risk_free_rate=self.risk_free_rate,
            funding_spread=self.funding_spread, dividend_yield=self.dividend_yield,
            rate_instruments=self.rate_instruments,
        )
