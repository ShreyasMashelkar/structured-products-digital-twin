"""yfinance EOD fallback source — declared but not implemented (scope contract: STUBBED).

A best-effort gap-filler for spot history when NSE bhavcopy is unavailable (README data
strategy §2.2). The project's REAL data path is NSE F&O/cash bhavcopy + FBIL rates
(:mod:`spdt.data.ingest.nse_bhavcopy`, :mod:`spdt.data.ingest.fbil`); this fallback is named
explicitly so the gap is visible rather than silent. Calling it fails loudly.
"""

from __future__ import annotations


def yfinance_spot_history(*args: object, **kwargs: object) -> object:
    """Placeholder — raises until the yfinance fallback is implemented."""
    raise NotImplementedError(
        "yfinance fallback source is a declared stub; use spdt.data.ingest.nse_bhavcopy "
        "(NSE bhavcopy) as the real EOD source."
    )
