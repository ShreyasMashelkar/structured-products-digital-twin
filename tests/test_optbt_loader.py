"""ChainLoader: bhavcopy → point-in-time chain, with tradedness flagged, never hidden."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from spdt.optbt.loader import ChainLoader, LiquidityScreen


def _bhavcopy_frame() -> pd.DataFrame:
    """Two traded contracts and one never-traded, in UDiFF column names."""
    return pd.DataFrame([
        {"TckrSymb": "NIFTY", "OptnTp": "CE", "StrkPric": 24000.0, "XpryDt": "2026-08-27",
         "SttlmPric": 250.0, "TtlTradgVol": 1200.0, "OpnIntrst": 50000.0,
         "UndrlygPric": 24000.0},
        {"TckrSymb": "NIFTY", "OptnTp": "PE", "StrkPric": 24000.0, "XpryDt": "2026-08-27",
         "SttlmPric": 240.0, "TtlTradgVol": 900.0, "OpnIntrst": 42000.0,
         "UndrlygPric": 24000.0},
        {"TckrSymb": "NIFTY", "OptnTp": "CE", "StrkPric": 32000.0, "XpryDt": "2026-08-27",
         "SttlmPric": 0.20, "TtlTradgVol": 0.0, "OpnIntrst": 0.0, "UndrlygPric": 24000.0},
        # a future row and a foreign underlying, both of which must be ignored
        {"TckrSymb": "NIFTY", "OptnTp": "XX", "StrkPric": 0.0, "XpryDt": "2026-08-27",
         "SttlmPric": 24010.0, "TtlTradgVol": 5000.0, "OpnIntrst": 100.0,
         "UndrlygPric": 24000.0},
        {"TckrSymb": "BANKNIFTY", "OptnTp": "CE", "StrkPric": 52000.0, "XpryDt": "2026-08-27",
         "SttlmPric": 400.0, "TtlTradgVol": 100.0, "OpnIntrst": 900.0,
         "UndrlygPric": 52000.0},
    ])


def _loader(**kw) -> ChainLoader:
    return ChainLoader(frame_provider=lambda d: _bhavcopy_frame(), **kw)


def test_only_the_underlyings_option_rows_are_loaded() -> None:
    snap = _loader().load(date(2026, 8, 25), "NIFTY")
    assert len(snap.quotes) == 3
    assert all(k.underlying == "NIFTY" for k in snap.quotes)


def test_untraded_contracts_are_kept_but_flagged_not_traded() -> None:
    """A listed strike can't be pretended away — but its print is not a market."""
    snap = _loader().load(date(2026, 8, 25), "NIFTY")
    untraded = [v for v in snap.quotes.values() if not v.traded]
    assert len(untraded) == 1
    assert untraded[0].key.strike == 32000.0


def test_open_interest_also_gates_tradedness() -> None:
    screen = LiquidityScreen(min_contracts=1.0, min_open_interest=100_000.0)
    snap = _loader(screen=screen).load(date(2026, 8, 25), "NIFTY")
    assert all(not v.traded for v in snap.quotes.values())


def test_every_loaded_quote_starts_in_settlement_provenance() -> None:
    snap = _loader().load(date(2026, 8, 25), "NIFTY")
    assert all(v.mark_provenance == "settlement" for v in snap.quotes.values())


def test_traded_fraction_and_spot_are_reported() -> None:
    snap = _loader().load(date(2026, 8, 25), "NIFTY")
    assert snap.traded_fraction == pytest.approx(2 / 3)
    assert snap.spot == pytest.approx(24000.0)


def test_missing_underlying_raises() -> None:
    with pytest.raises(ValueError, match="no option rows"):
        _loader().load(date(2026, 8, 25), "FINNIFTY")


def test_screen_defaults_are_strict() -> None:
    screen = LiquidityScreen()
    assert screen.min_contracts > 0.0
    assert screen.min_open_interest > 0.0
    assert screen.otm_only is True
