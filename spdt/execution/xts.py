"""XTS interactive (trading/account) client — read-only first, orders behind hard gates (Phase 7).

Speaks the XTS interactive REST API: session login, then read-only broker state — orders,
trades, positions, margins — normalized into small SPDT-side dataclasses. Order placement
exists but is fenced by :class:`ExecutionControls`: the default mode is ``paper`` (nothing
reaches the wire), ``read_only`` can fetch state but never trade, and ``live`` requires an
explicit ``SPDT_LIVE_TRADING=true`` opt-in *plus* per-order symbol-allowlist, max-notional,
and kill-switch checks. Allowlists bind to broker instrument IDs, not display symbols. Same
shape as the market-data adapter: one mockable ``_request``,
credentials from ``SPDT_XTS_INTERACTIVE_*`` env vars, never logged.
"""

from __future__ import annotations

import json
import math
import os
import urllib.request
from dataclasses import dataclass
from typing import Literal

# ponytail: field names per Symphony's published interactive API — reconcile the exact
# response keys against the live AC Agarwal deployment once credentials arrive.


@dataclass(frozen=True)
class OrderState:
    order_id: str
    symbol: str
    exchange_segment: str
    side: str
    order_type: str
    qty: float
    price: float
    status: str


@dataclass(frozen=True)
class TradeRecord:
    order_id: str
    symbol: str
    side: str
    qty: float
    avg_price: float


@dataclass(frozen=True)
class BrokerPosition:
    symbol: str
    exchange_instrument_id: int
    qty: float
    buy_avg_price: float
    sell_avg_price: float


@dataclass(frozen=True)
class MarginState:
    cash_available: float
    margin_utilized: float
    net_margin_available: float


@dataclass(frozen=True)
class ExecutionControls:
    """The safety gates every order must pass. Defaults are the safest possible."""

    mode: Literal["paper", "read_only", "live"] = "paper"
    live_trading: bool = False
    kill_switch: bool = False
    max_order_notional: float = 0.0
    allowed_instruments: tuple[tuple[str, int], ...] = ()

    @classmethod
    def from_env(cls) -> ExecutionControls:
        instruments: list[tuple[str, int]] = []
        for raw in os.environ.get("SPDT_ALLOWED_INSTRUMENTS", "").split(","):
            if not raw.strip():
                continue
            try:
                segment, instrument_id = raw.strip().split(":", 1)
                instruments.append((segment.upper(), int(instrument_id)))
            except ValueError as exc:
                raise ValueError(
                    "SPDT_ALLOWED_INSTRUMENTS must contain SEGMENT:INSTRUMENT_ID entries"
                ) from exc
        return cls(
            mode=os.environ.get("SPDT_EXECUTION_MODE", "paper"),  # type: ignore[arg-type]
            live_trading=os.environ.get("SPDT_LIVE_TRADING", "").lower() in ("1", "true", "yes"),
            kill_switch=os.environ.get("SPDT_KILL_SWITCH", "").lower() in ("1", "true", "yes"),
            max_order_notional=float(os.environ.get("SPDT_MAX_ORDER_NOTIONAL", "0")),
            allowed_instruments=tuple(instruments),
        )

    def check_order(
        self, *, exchange_segment: str, exchange_instrument_id: int, side: str,
        order_type: str, qty: float, price: float,
    ) -> None:
        """Raise unless this order is allowed to go live. Order of checks: broadest gate first."""
        if self.mode != "live" or not self.live_trading:
            raise RuntimeError(
                "live trading is disabled — set SPDT_EXECUTION_MODE=live and "
                "SPDT_LIVE_TRADING=true to enable (default is paper)"
            )
        if self.kill_switch:
            raise RuntimeError("kill switch is on (SPDT_KILL_SWITCH) — all live orders blocked")
        identity = (exchange_segment.upper(), exchange_instrument_id)
        if identity not in self.allowed_instruments:
            raise RuntimeError(
                f"instrument {identity!r} is not in the allowlist (SPDT_ALLOWED_INSTRUMENTS)"
            )
        if side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        if order_type not in ("LIMIT", "MARKET"):
            raise ValueError("order_type must be LIMIT or MARKET")
        if order_type == "MARKET":
            raise RuntimeError("market orders are disabled until a trusted reference-price check exists")
        if not math.isfinite(qty) or qty <= 0 or not float(qty).is_integer():
            raise ValueError("order quantity must be a positive finite integer")
        if not math.isfinite(self.max_order_notional) or self.max_order_notional <= 0:
            raise RuntimeError("SPDT_MAX_ORDER_NOTIONAL must be a positive finite number")
        notional_price = price
        if notional_price is None or not math.isfinite(notional_price) or notional_price <= 0:
            raise ValueError("order notional requires a positive finite trusted price")
        notional = qty * notional_price
        if notional > self.max_order_notional:
            raise RuntimeError(
                f"order notional {notional:,.0f} exceeds SPDT_MAX_ORDER_NOTIONAL "
                f"{self.max_order_notional:,.0f}"
            )


class XTSExecutionClient:
    """Authenticated client for the XTS interactive API. All HTTP through mockable ``_request``."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        app_key: str | None = None,
        secret: str | None = None,
        source: str = "WebAPI",
        controls: ExecutionControls | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get("SPDT_XTS_BASE_URL", "")).rstrip("/")
        self.app_key = app_key or os.environ.get("SPDT_XTS_INTERACTIVE_APP_KEY")
        self.secret = secret or os.environ.get("SPDT_XTS_INTERACTIVE_SECRET")
        self.source = source
        self.controls = controls or ExecutionControls.from_env()
        self.timeout = timeout
        self.token: str | None = None

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["authorization"] = self.token
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 (configured host)
            return json.loads(response.read())

    def _result(self, payload: dict):
        if payload.get("type") != "success":
            # description only — credentials must never appear in errors
            raise RuntimeError(f"XTS interactive API error: {payload.get('description', 'unknown error')}")
        return payload.get("result")

    def login(self) -> None:
        if not self.app_key or not self.secret:
            raise RuntimeError(
                "XTS interactive credentials missing — set SPDT_XTS_INTERACTIVE_APP_KEY and "
                "SPDT_XTS_INTERACTIVE_SECRET"
            )
        result = self._result(self._request("POST", "/interactive/user/session", {
            "appKey": self.app_key, "secretKey": self.secret, "source": self.source,
        }))
        self.token = result["token"]

    # --- read-only broker state ---------------------------------------------------

    def orders(self) -> list[OrderState]:
        rows = self._result(self._request("GET", "/interactive/orders")) or []
        return [OrderState(
            order_id=str(r.get("AppOrderID", "")),
            symbol=r.get("TradingSymbol", ""),
            exchange_segment=r.get("ExchangeSegment", ""),
            side=r.get("OrderSide", ""),
            order_type=r.get("OrderType", ""),
            qty=float(r.get("OrderQuantity", 0)),
            price=float(r.get("OrderPrice", 0)),
            status=r.get("OrderStatus", ""),
        ) for r in rows]

    def trades(self) -> list[TradeRecord]:
        rows = self._result(self._request("GET", "/interactive/orders/trades")) or []
        return [TradeRecord(
            order_id=str(r.get("AppOrderID", "")),
            symbol=r.get("TradingSymbol", ""),
            side=r.get("OrderSide", ""),
            qty=float(r.get("CumulativeQuantity", 0)),
            avg_price=float(r.get("OrderAverageTradedPrice", 0)),
        ) for r in rows]

    def positions(self, day_or_net: str = "NetWise") -> list[BrokerPosition]:
        result = self._result(self._request(
            "GET", f"/interactive/portfolio/positions?dayOrNet={day_or_net}"
        )) or {}
        return [BrokerPosition(
            symbol=r.get("TradingSymbol", ""),
            exchange_instrument_id=int(r.get("ExchangeInstrumentId", 0)),
            qty=float(r.get("Quantity", 0)),
            buy_avg_price=float(r.get("BuyAveragePrice", 0)),
            sell_avg_price=float(r.get("SellAveragePrice", 0)),
        ) for r in result.get("positionList", [])]

    def margins(self) -> MarginState:
        result = self._result(self._request("GET", "/interactive/user/balance")) or {}
        limits = (result.get("BalanceList") or [{}])[0].get("limitObject", {}).get("RMSSubLimits", {})
        return MarginState(
            cash_available=float(limits.get("cashAvailable", 0)),
            margin_utilized=float(limits.get("marginUtilized", 0)),
            net_margin_available=float(limits.get("netMarginAvailable", 0)),
        )

    # --- gated order entry ----------------------------------------------------------

    def place_order(
        self,
        *,
        symbol: str,
        exchange_instrument_id: int,
        side: str,
        qty: float,
        price: float,
        exchange_segment: str = "NSEFO",
        order_type: str = "LIMIT",
        product: str = "NRML",
    ) -> dict:
        """Place a live order. Refuses unless every :class:`ExecutionControls` gate passes."""
        self.controls.check_order(
            exchange_segment=exchange_segment,
            exchange_instrument_id=exchange_instrument_id,
            side=side,
            order_type=order_type,
            qty=qty,
            price=price,
        )
        return self._result(self._request("POST", "/interactive/orders", {
            "exchangeSegment": exchange_segment,
            "exchangeInstrumentID": exchange_instrument_id,
            "productType": product,
            "orderType": order_type,
            "orderSide": side,
            "timeInForce": "DAY",
            "disclosedQuantity": 0,
            "orderQuantity": int(qty),
            "limitPrice": price,
            "stopPrice": 0,
            "orderUniqueIdentifier": "spdt",
        }))

    def cancel_order(self, app_order_id: str) -> dict:
        """Cancel a live order — allowed in the same gated live mode only."""
        if self.controls.mode != "live" or not self.controls.live_trading:
            raise RuntimeError("live trading is disabled — cannot cancel broker orders")
        return self._result(self._request(
            "DELETE", f"/interactive/orders?appOrderID={app_order_id}"
        ))
