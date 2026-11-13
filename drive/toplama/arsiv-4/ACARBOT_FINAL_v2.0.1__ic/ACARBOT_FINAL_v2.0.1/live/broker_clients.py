"""ACARBOT v2.0 — Testnet/demo borsa istemcileri (emir + pozisyon + kurtarma).

Binance Futures Testnet:
  POST /fapi/v1/order          (MARKET / STOP_MARKET closePosition=true)
  DELETE /fapi/v1/allOpenOrders
  GET /fapi/v2/positionRisk
  GET /fapi/v1/openOrders
  POST /fapi/v1/leverage | marginType
  GET /fapi/v1/klines          (GERÇEK perpetual verisi — ayna/spot testinin
                                tersine, canlı emir öncesi buradan test edilir)

OKX Demo Trading:
  POST /api/v5/trade/order
  GET /api/v5/trade/orders-pending
  GET /api/v5/account/positions
  GET /api/v5/public/open-interest

Tüm çıkış emirleri reduceOnly / closePosition=true ile gönderilir
(şartname: reduce-only çıkışlar). Koruyucu stop BORSA TARAFINDA çalışır
(sunucu tarafı STOP_MARKET) — bot ölürse bile pozisyon korunur.
"""

from __future__ import annotations

from dataclasses import dataclass

from live.clients import LiveClientError, OkxSignedClient, SignedHttpClient


@dataclass(frozen=True)
class ExchangePosition:
    symbol: str
    side: str                     # "LONG" | "SHORT" | "BOTH" (Binance hedge yok)
    quantity: float               # mutlak pozisyon miktarı (baz varlık)
    entry_price: float
    unrealized_pnl: float


@dataclass(frozen=True)
class ExchangeOrder:
    order_id: str
    client_order_id: str
    symbol: str
    side: str
    status: str
    price: float
    quantity: float
    executed_quantity: float
    reduce_only: bool
    updated_ms: int


class BinanceFuturesTestnet:
    """Binance USDT-M Futures Testnet istemcisi."""

    def __init__(self, client: SignedHttpClient) -> None:
        self.client = client
        self.name = "binance-testnet"

    # -- Kurulum ----------------------------------------------------------

    def set_leverage(self, symbol: str, leverage: int) -> None:
        self.client.signed_request(
            "POST", "/fapi/v1/leverage",
            {"symbol": symbol, "leverage": leverage},
        )

    def set_margin_type(self, symbol: str, mode: str) -> None:
        """mode: ISOLATED | CROSSED. Zaten ayarlıysa hata yutulur."""
        try:
            self.client.signed_request(
                "POST", "/fapi/v1/marginType",
                {"symbol": symbol, "marginType": "CROSSED" if mode == "cross" else "ISOLATED"},
            )
        except LiveClientError as exc:
            if "-4046" not in str(exc):  # zaten bu modda
                raise

    # -- Emirler ------------------------------------------------------------

    def place_entry(
        self, symbol: str, side: str, quantity: float,
        client_order_id: str, market: bool = True, price: float | None = None,
    ) -> ExchangeOrder:
        params: dict[str, object] = {
            "symbol": symbol,
            "side": "BUY" if side == "LONG" else "SELL",
            "type": "MARKET" if market else "LIMIT",
            "quantity": f"{quantity:.8f}".rstrip("0").rstrip("."),
            "newClientOrderId": client_order_id,
        }
        if not market:
            params.update({
                "price": f"{price:.8f}".rstrip("0").rstrip("."),
                "timeInForce": "GTX",  # post-only
            })
        payload = self.client.signed_request("POST", "/fapi/v1/order", params).as_dict()
        return ExchangeOrder(
            order_id=str(payload.get("orderId", "")),
            client_order_id=str(payload.get("clientOrderId", client_order_id)),
            symbol=str(payload.get("symbol", symbol)),
            side=str(payload.get("side", "")),
            status=str(payload.get("status", "")),
            price=float(payload.get("price", 0.0) or 0.0),
            quantity=float(payload.get("origQty", 0.0) or 0.0),
            executed_quantity=float(payload.get("executedQty", 0.0) or 0.0),
            reduce_only=bool(payload.get("reduceOnly", False)),
            updated_ms=int(payload.get("updateTime", 0) or 0),
        )

    def place_protective_stop(
        self, symbol: str, side: str, stop_price: float, client_order_id: str,
    ) -> ExchangeOrder:
        """Sunucu tarafı koruyucu stop: STOP_MARKET + closePosition=true.

        LONG pozisyon → SELL stop; SHORT pozisyon → BUY stop.
        closePosition=true çıkmayı otomatik reduce-only yapar.
        """
        params = {
            "symbol": symbol,
            "side": "SELL" if side == "LONG" else "BUY",
            "type": "STOP_MARKET",
            "stopPrice": f"{stop_price:.8f}".rstrip("0").rstrip("."),
            "closePosition": "true",
            "newClientOrderId": client_order_id,
        }
        payload = self.client.signed_request("POST", "/fapi/v1/order", params).as_dict()
        return ExchangeOrder(
            order_id=str(payload.get("orderId", "")),
            client_order_id=str(payload.get("clientOrderId", client_order_id)),
            symbol=str(payload.get("symbol", symbol)),
            side=str(payload.get("side", "")),
            status=str(payload.get("status", "")),
            price=0.0,
            quantity=float(payload.get("origQty", 0.0) or 0.0),
            executed_quantity=0.0,
            reduce_only=True,
            updated_ms=int(payload.get("updateTime", 0) or 0),
        )

    def place_reduce_only_exit(
        self, symbol: str, side: str, quantity: float, client_order_id: str,
    ) -> ExchangeOrder:
        params = {
            "symbol": symbol,
            "side": "SELL" if side == "LONG" else "BUY",
            "type": "MARKET",
            "quantity": f"{quantity:.8f}".rstrip("0").rstrip("."),
            "reduceOnly": "true",
            "newClientOrderId": client_order_id,
        }
        payload = self.client.signed_request("POST", "/fapi/v1/order", params).as_dict()
        return ExchangeOrder(
            order_id=str(payload.get("orderId", "")),
            client_order_id=str(payload.get("clientOrderId", client_order_id)),
            symbol=str(payload.get("symbol", symbol)),
            side=str(payload.get("side", "")),
            status=str(payload.get("status", "")),
            price=float(payload.get("price", 0.0) or 0.0),
            quantity=float(payload.get("origQty", 0.0) or 0.0),
            executed_quantity=float(payload.get("executedQty", 0.0) or 0.0),
            reduce_only=True,
            updated_ms=int(payload.get("updateTime", 0) or 0),
        )

    def cancel_all_orders(self, symbol: str) -> None:
        self.client.signed_request(
            "DELETE", "/fapi/v1/allOpenOrders", {"symbol": symbol},
        )

    def cancel_all_orders_everywhere(self) -> None:
        for position in self.fetch_positions():
            self.cancel_all_orders(position.symbol)

    # -- Sorgular -------------------------------------------------------------

    def fetch_positions(self) -> list[ExchangePosition]:
        payload = self.client.signed_request(
            "GET", "/fapi/v2/positionRisk",
        ).as_list()
        out: list[ExchangePosition] = []
        for row in payload:
            amount = float(row.get("positionAmt", 0.0) or 0.0)
            if amount == 0:
                continue
            out.append(ExchangePosition(
                symbol=str(row.get("symbol", "")),
                side="LONG" if amount > 0 else "SHORT",
                quantity=abs(amount),
                entry_price=float(row.get("entryPrice", 0.0) or 0.0),
                unrealized_pnl=float(row.get("unRealizedProfit", 0.0) or 0.0),
            ))
        return out

    def fetch_open_orders(self, symbol: str | None = None) -> list[ExchangeOrder]:
        params = {"symbol": symbol} if symbol else {}
        payload = self.client.signed_request(
            "GET", "/fapi/v1/openOrders", params,
        ).as_list()
        out: list[ExchangeOrder] = []
        for row in payload:
            out.append(ExchangeOrder(
                order_id=str(row.get("orderId", "")),
                client_order_id=str(row.get("clientOrderId", "")),
                symbol=str(row.get("symbol", "")),
                side=str(row.get("side", "")),
                status=str(row.get("status", "")),
                price=float(row.get("price", 0.0) or 0.0),
                quantity=float(row.get("origQty", 0.0) or 0.0),
                executed_quantity=float(row.get("executedQty", 0.0) or 0.0),
                reduce_only=bool(row.get("reduceOnly", False)),
                updated_ms=int(row.get("updateTime", 0) or 0),
            ))
        return out

    def fetch_perp_candles(self, symbol: str, interval: str, limit: int = 100):
        """GERÇEK perpetual mum verisi (ayna/spot karışıklığını önler)."""
        from infra.market_data.models import Candle
        from infra.exchanges.base import PublicMarketDataError
        raw = self.client.signed_request(
            "GET", "/fapi/v1/klines",
            {"symbol": symbol, "interval": interval, "limit": limit},
        ).as_list()
        try:
            return [
                Candle(int(row[0]), float(row[1]), float(row[2]),
                       float(row[3]), float(row[4]), float(row[5]))
                for row in raw
            ]
        except (TypeError, ValueError, IndexError) as exc:
            raise PublicMarketDataError("testnet klines bozuk") from exc


class OkxDemoTrading:
    """OKX Demo Trading istemcisi (x-simulated-trading: 1)."""

    def __init__(self, client: OkxSignedClient) -> None:
        self.client = client
        self.name = "okx-demo"

    def place_market(
        self, inst_id: str, side: str, size_contracts: float,
        client_order_id: str, reduce_only: bool = False,
    ) -> ExchangeOrder:
        body = {
            "instId": inst_id,
            "tdMode": "isolated",
            "side": "buy" if side == "LONG" else "sell",
            "ordType": "market",
            "sz": f"{size_contracts:.8f}".rstrip("0").rstrip("."),
            "clOrdId": client_order_id,
            "reduceOnly": "true" if reduce_only else "false",
        }
        payload = self.client.signed_request(
            "POST", "/api/v5/trade/order", body=body,
        ).as_dict()
        rows = payload.get("data") or [{}]
        row = rows[0] if rows else {}
        return ExchangeOrder(
            order_id=str(row.get("ordId", "")),
            client_order_id=str(row.get("clOrdId", client_order_id)),
            symbol=str(row.get("instId", inst_id)),
            side=str(body["side"]),
            status=str(row.get("sCode", "")),
            price=0.0,
            quantity=size_contracts,
            executed_quantity=0.0,
            reduce_only=reduce_only,
            updated_ms=0,
        )

    def fetch_positions(self) -> list[ExchangePosition]:
        payload = self.client.signed_request(
            "GET", "/api/v5/account/positions",
        ).as_dict()
        out: list[ExchangePosition] = []
        for row in payload.get("data") or []:
            amount = float(row.get("pos", 0.0) or 0.0)
            if amount == 0:
                continue
            out.append(ExchangePosition(
                symbol=str(row.get("instId", "")),
                side="LONG" if amount > 0 else "SHORT",
                quantity=abs(amount),
                entry_price=float(row.get("avgPx", 0.0) or 0.0),
                unrealized_pnl=float(row.get("upl", 0.0) or 0.0),
            ))
        return out

    def cancel_all_orders(self, inst_id: str) -> None:
        self.client.signed_request(
            "POST", "/api/v5/trade/cancel-all-orders",
            body={"instId": inst_id, "instType": "SWAP"},
        )
