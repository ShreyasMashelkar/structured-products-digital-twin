"""Tests for the XTS interactive (trading/account) client — HTTP mocked, no credentials.

Read-only methods (orders/trades/positions/margins) parse fixtures shaped like the XTS
interactive API. Order placement is hard-gated: paper is the default mode, live requires
explicit env opt-in, and every live order passes symbol/notional/kill-switch checks.
"""

import pytest

from spdt.execution.xts import ExecutionControls, XTSExecutionClient

_LOGIN = {"type": "success", "result": {"token": "ITOK", "userID": "U1"}}


def _client(monkeypatch, responses, **controls):
    client = XTSExecutionClient(
        base_url="https://xts.example.com", app_key="IKEY", secret="ISEKRIT",
        controls=ExecutionControls(**controls) if controls else None,
    )
    calls = []

    def fake_request(method, path, body=None):
        calls.append((method, path, body))
        for suffix, payload in responses.items():
            if path.endswith(suffix):
                return payload
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(client, "_request", fake_request)
    client.calls = calls
    return client


def test_login_requires_credentials_and_stores_token(monkeypatch):
    monkeypatch.delenv("SPDT_XTS_INTERACTIVE_APP_KEY", raising=False)
    monkeypatch.delenv("SPDT_XTS_INTERACTIVE_SECRET", raising=False)
    bare = XTSExecutionClient(base_url="https://xts.example.com")
    with pytest.raises(RuntimeError, match="SPDT_XTS_INTERACTIVE_APP_KEY"):
        bare.login()

    client = _client(monkeypatch, {"/interactive/user/session": _LOGIN})
    client.login()
    assert client.token == "ITOK"


def test_read_only_state_is_normalized(monkeypatch):
    client = _client(monkeypatch, {
        "/interactive/orders": {"type": "success", "result": [{
            "AppOrderID": 111, "TradingSymbol": "NIFTY25JULFUT", "ExchangeSegment": "NSEFO",
            "OrderSide": "SELL", "OrderType": "MARKET", "OrderQuantity": 75,
            "OrderPrice": 0.0, "OrderStatus": "Filled",
        }]},
        "/interactive/orders/trades": {"type": "success", "result": [{
            "AppOrderID": 111, "TradingSymbol": "NIFTY25JULFUT",
            "OrderAverageTradedPrice": "24010.5", "CumulativeQuantity": 75, "OrderSide": "SELL",
        }]},
        "/interactive/portfolio/positions?dayOrNet=NetWise": {"type": "success", "result": {"positionList": [{
            "TradingSymbol": "NIFTY25JULFUT", "ExchangeInstrumentId": 101,
            "Quantity": -75, "BuyAveragePrice": "0", "SellAveragePrice": "24010.5",
        }]}},
        "/interactive/user/balance": {"type": "success", "result": {"BalanceList": [{
            "limitObject": {"RMSSubLimits": {
                "cashAvailable": "500000", "marginUtilized": "120000",
                "netMarginAvailable": "380000",
            }},
        }]}},
    })
    client.token = "ITOK"

    (order,) = client.orders()
    assert order.order_id == "111" and order.side == "SELL" and order.status == "Filled"

    (trade,) = client.trades()
    assert trade.order_id == "111" and trade.avg_price == 24010.5 and trade.qty == 75

    (position,) = client.positions()
    assert position.symbol == "NIFTY25JULFUT" and position.qty == -75

    margins = client.margins()
    assert margins.cash_available == 500000.0 and margins.margin_utilized == 120000.0


def test_place_order_refused_outside_live_mode(monkeypatch):
    client = _client(monkeypatch, {})  # default controls: paper mode
    client.token = "ITOK"
    with pytest.raises(RuntimeError, match="live trading is disabled"):
        client.place_order(symbol="NIFTY25JULFUT", exchange_instrument_id=101,
                           side="SELL", qty=75, price=24000.0)
    assert client.calls == []  # nothing ever reached the wire


def test_place_order_refused_when_kill_switch_on(monkeypatch):
    client = _client(monkeypatch, {}, mode="live", live_trading=True, kill_switch=True,
                     allowed_instruments=(("NSEFO", 101),), max_order_notional=1e9)
    client.token = "ITOK"
    with pytest.raises(RuntimeError, match="kill switch"):
        client.place_order(symbol="NIFTY25JULFUT", exchange_instrument_id=101,
                           side="SELL", qty=75, price=24000.0)


def test_place_order_enforces_allowlist_and_notional(monkeypatch):
    client = _client(monkeypatch, {"/interactive/orders": {"type": "success", "result": {"AppOrderID": 222}}},
                     mode="live", live_trading=True,
                     allowed_instruments=(("NSEFO", 101),), max_order_notional=2_000_000.0)
    client.token = "ITOK"
    with pytest.raises(RuntimeError, match="not in the allowlist"):
        client.place_order(symbol="BANKNIFTY25JULFUT", exchange_instrument_id=9,
                           side="BUY", qty=15, price=52000.0)
    with pytest.raises(RuntimeError, match="notional"):
        client.place_order(symbol="NIFTY25JULFUT", exchange_instrument_id=101,
                           side="BUY", qty=100, price=24000.0)  # 2.4mm > 2mm

    ack = client.place_order(symbol="NIFTY25JULFUT", exchange_instrument_id=101,
                             side="BUY", qty=75, price=24000.0)
    assert ack["AppOrderID"] == 222
    assert any(p.endswith("/interactive/orders") for _, p, _ in client.calls)


def test_allowlist_is_bound_to_instrument_id_not_symbol(monkeypatch):
    client = _client(monkeypatch, {}, mode="live", live_trading=True,
                     allowed_instruments=(("NSEFO", 101),), max_order_notional=2_000_000.0)
    with pytest.raises(RuntimeError, match="not in the allowlist"):
        client.place_order(symbol="NIFTY25JULFUT", exchange_instrument_id=999999,
                           side="BUY", qty=1, price=24000.0)
    assert client.calls == []


def test_market_order_cannot_bypass_notional_cap_with_zero_price(monkeypatch):
    client = _client(monkeypatch, {}, mode="live", live_trading=True,
                     allowed_instruments=(("NSEFO", 101),), max_order_notional=1.0)
    with pytest.raises(RuntimeError, match="market orders are disabled"):
        client.place_order(symbol="NIFTY25JULFUT", exchange_instrument_id=101,
                           side="BUY", qty=1_000_000, price=0.0, order_type="MARKET")
    assert client.calls == []


def test_errors_never_leak_secret(monkeypatch):
    client = _client(monkeypatch, {"/interactive/orders": {
        "type": "error", "description": "Session expired",
    }})
    client.token = "ITOK"
    with pytest.raises(RuntimeError) as excinfo:
        client.orders()
    assert "Session expired" in str(excinfo.value) and "ISEKRIT" not in str(excinfo.value)


def test_controls_read_from_environment(monkeypatch):
    monkeypatch.setenv("SPDT_EXECUTION_MODE", "read_only")
    monkeypatch.setenv("SPDT_LIVE_TRADING", "false")
    monkeypatch.setenv("SPDT_KILL_SWITCH", "true")
    monkeypatch.setenv("SPDT_MAX_ORDER_NOTIONAL", "1500000")
    monkeypatch.setenv("SPDT_ALLOWED_INSTRUMENTS", "NSEFO:101,NSEFO:202")
    controls = ExecutionControls.from_env()
    assert controls.mode == "read_only" and controls.live_trading is False
    assert controls.kill_switch is True
    assert controls.max_order_notional == 1_500_000.0
    assert controls.allowed_instruments == (("NSEFO", 101), ("NSEFO", 202))
