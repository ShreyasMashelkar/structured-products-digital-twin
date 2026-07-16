"""NSE corporate-bond trades → issuer spread-over-OIS (funding/credit curve proxy).

India has no liquid CDS market, so the standard fallback is bond-implied spreads: an
issuer's traded bond yield minus the OIS zero rate at matching tenor. The output dict
(maturity → spread) plugs directly into ``RawMarketData.funding_spread_knots`` (funding) or
a hazard-rate build (credit).

Parsing is fixture-tested; download the "corporate bonds traded" CSV from NSE manually and
reconcile the real header names on first use.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime

from spdt.core.types import Curve

# ponytail: column names per NSE's corporate-bond trade report — verify against a real
# download on first use (add a fetcher then; the public endpoint needs browser headers).
_COLUMNS = {"symbol": "SYMBOL", "issuer": "ISSUER", "maturity": "MATURITY", "yield": "WAY"}


@dataclass(frozen=True)
class BondTrade:
    """One traded corporate bond line: who, when it matures, and the traded yield."""

    symbol: str
    issuer: str
    maturity: date
    yield_pct: float  # weighted-average traded yield, % p.a.


def parse_bond_trades(csv_text: str) -> list[BondTrade]:
    """Parse the NSE corporate-bond trades CSV, dropping malformed rows."""
    trades: list[BondTrade] = []
    for row in csv.DictReader(io.StringIO(csv_text)):
        try:
            trades.append(BondTrade(
                symbol=row[_COLUMNS["symbol"]].strip(),
                issuer=row[_COLUMNS["issuer"]].strip(),
                maturity=datetime.strptime(row[_COLUMNS["maturity"]].strip(), "%d-%b-%Y").date(),
                yield_pct=float(row[_COLUMNS["yield"]]),
            ))
        except (KeyError, ValueError, AttributeError):
            continue  # blank/malformed line — real files carry footers and dashes
    return trades


def bond_implied_spreads(
    trades: list[BondTrade], ois_curve: Curve, *, issuer: str | None = None
) -> dict[date, float]:
    """Spread knots: traded yield (decimal) minus the OIS zero rate at the bond's maturity.

    Simple-vs-continuous compounding is ignored — a few bp, below bond-quote noise. When
    several bonds share a maturity the last one wins; pre-filter by ``issuer`` for a clean
    single-name curve.
    """
    return {
        t.maturity: t.yield_pct / 100.0 - ois_curve.zero_rate(t.maturity)
        for t in trades
        if issuer is None or t.issuer == issuer
    }
