"""ACARBOT v3.0 — Testnet/demo borsa istemcileri (emir + pozisyon + kurtarma).

Binance Futures Testnet:
  POST /fapi/v1/order          (MARKET / STOP_MARKET closePosition=true)
  DELETE /fapi/v1/allOpenOrders
  DELETE /fapi/v1/order        (clientOrderId ile tek emir iptali — v3.0)
  POST /fapi/v1/countdownCancelAll  (dead-man's switch — v3.0, opt-in)
  GET /fapi/v2/positionRisk
  GET /fapi/v1/openOrders
  POST /fapi/v1/leverage | marginType
  GET /fapi/v1/exchangeInfo    (PUBLIC: tickSize/stepSize/minNotional — v3.0)
  GET /fapi/v1/klines          (GERÇEK perpetual verisi — ayna/spot testinin
                                tersine, canlı emir öncesi buradan test edilir)

OKX Demo Trading:
  POST /api/v5/trade/order               (market; sCode≠0 → HATA — v3.0)
  POST /api/v5/trade/order-algo          (conditional stop — v3.0)
  POST /api/v5/trade/cancel-batch-orders (geçerli toplu iptal — v3.0;
        ESKİ KODDAKİ /trade/cancel-all-orders OKX v5'te YOKTUR)
  POST /api/v5/trade/cancel-algos        (algo emir iptali — v3.0)
  POST /api/v5/trade/cancel-all-after    (dead-man's switch — v3.0, opt-in)
  GET  /api/v5/trade/orders-pending | orders-algo-pending
  GET  /api/v5/account/positions
  GET  /api/v5/public/instruments        (ctVal/lotSz/minSz/tickSz — v3.0)

v3.0 düzeltmeleri (dış inceleme bulguları):
  - OKX HTTP 200 + sCode≠0 artık HATA olarak yükselir (sessiz başarı yok).
  - Çıkış emirleri YÖN DÜZGÜN gönderilir: LONG kapatmak için SELL.
  - Miktar/fiyat borsa filtrelerine yuvarlanır (tickSize/stepSize/minNotional
    /lotSz/minSz); dönüştürme yapılamazsa emir GÖNDERİLMEZ (fail-closed).
  - OKX pozisyon büyüklüğü kontrata çevrilir (ctVal) — baz birim karışmaz.
  - Her çıkış (mirror_close) sonrası artık koruyucu stop da iptal edilir.

Tüm çıkış emirleri reduceOnly / closePosition=true ile gönderilir
(şartname: reduce-only çıkışlar). Koruyucu stop BORSA TARAFINDA çalışır
(sunucu tarafı STOP_MARKET / conditional algo) — bot ölürse bile pozisyon
korunur. Bu yüzden dead-man's switch VARSAYILAN KAPALIDIR: countdown
temizliği koruyucu stopları DA İPTAL EDER ve pozisyonu korumasız bırakır.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from live.clients import LiveClientError, OkxSignedClient, SignedHttpClient

logger = logging.getLogger(__name__)

OKX_ORDER_TAG = "ACARBOT"

_OKX_SUCCESS_CODES = frozenset({"0", "1"})  # 0=success, 1=partial? yalnız 0 kabul


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


@dataclass(frozen=True)
class SymbolFilters:
    """Borsa emir filtreleri (v3.0: yuvarlama ve doğrulama için)."""

    tick_size: float = 0.0
    step_size: float = 0.0
    min_qty: float = 0.0
    min_notional: float = 0.0


def _round_to_step(value: float, step: float) -> float:
    """Adıma AŞAĞI yuvarlar (risk taşmaması için miktar büyütülmez)."""
    if step <= 0:
        return value
    steps = int(value / step + 1e-9)
    return round(steps * step, 10)


def _round_to_tick(value: float, tick: float) -> float:
    if tick <= 0:
        return value
    return round(round(value / tick) * tick, 10)


class BinanceFuturesTestnet:
    """Binance USDT-M Futures Testnet istemcisi."""

    def __init__(self, client: SignedHttpClient) -> None:
        self.client = client
        self.name = "binance-testnet"
        self._filters: dict[str, SymbolFilters] = {}

    # -- Kurulum ----------------------------------------------------------

    def set_leverage(self, symbol: str, leverage: int) -> None:
        self.client.signed_request(
            "POST", "/fapi/v1/leverage",
            {"symbol": symbol, "leverage": leverage},
        )

    def set_margin_type(self, symbol: str, mode: str) -> None:
        """mode: ISOLATED | CROSSED. Zaten ayarlıysa (-4046) sessiz geçer.

        v3.0: transport artık HTTP 400 gövdesini mesaja eklediği için bu
        kontrol GERÇEK ağda da çalışır (eski sürümde gövde kayboluyordu).
        """
        try:
            self.client.signed_request(
                "POST", "/fapi/v1/marginType",
                {"symbol": symbol, "marginType": "CROSSED" if mode == "cross" else "ISOLATED"},
            )
        except LiveClientError as exc:
            if "-4046" not in str(exc):  # zaten bu modda
                raise

    # -- Filtreler (v3.0) ---------------------------------------------------

    def fetch_symbol_filters(self, symbol: str) -> SymbolFilters:
        """exchangeInfo'dan tickSize/stepSize/minQty/minNotional (önbellekli).

        Public uçtur; API anahtarı gerekmez. Okunamazsa filtreler bilinmez
        ve yuvarlama yapılmaz — çağıran taraf ham değeri gönderir (davranış
        v2.0 ile aynı), ancak minNotional kontrolü atlanır.
        """
        cached = self._filters.get(symbol)
        if cached is not None:
            return cached
        filters = SymbolFilters()
        try:
            info = self.client.public_request(
                "/fapi/v1/exchangeInfo", {"symbol": symbol},
            ).as_dict()
            rows = info.get("symbols") or []
            row = next(
                (r for r in rows if isinstance(r, dict) and r.get("symbol") == symbol),
                None,
            )
            if row:
                def _flt(ftype: str) -> dict:
                    return next(
                        (f for f in row.get("filters", [])
                         if isinstance(f, dict) and f.get("filterType") == ftype),
                        {},
                    )
                price_f = _flt("PRICE_FILTER")
                lot_f = _flt("LOT_SIZE")
                notional_f = _flt("MIN_NOTIONAL")
                filters = SymbolFilters(
                    tick_size=float(price_f.get("tickSize", 0.0) or 0.0),
                    step_size=float(lot_f.get("stepSize", 0.0) or 0.0),
                    min_qty=float(lot_f.get("minQty", 0.0) or 0.0),
                    min_notional=float(notional_f.get("notional", 0.0) or 0.0),
                )
        except LiveClientError as exc:
            logger.warning("Filtre okunamadı (%s): %s — yuvarlama atlanıyor", symbol, exc)
            return SymbolFilters()
        self._filters[symbol] = filters
        return filters

    def round_price(self, symbol: str, price: float) -> float:
        return _round_to_tick(price, self.fetch_symbol_filters(symbol).tick_size)

    def round_quantity(self, symbol: str, quantity: float) -> float:
        filters = self.fetch_symbol_filters(symbol)
        qty = _round_to_step(quantity, filters.step_size)
        if filters.min_qty > 0 and 0 < qty < filters.min_qty:
            raise LiveClientError(
                f"{symbol}: miktar minQty altına düştü ({qty} < {filters.min_qty})"
            )
        return qty

    def check_min_notional(self, symbol: str, price: float, quantity: float) -> None:
        filters = self.fetch_symbol_filters(symbol)
        if filters.min_notional > 0 and price * quantity < filters.min_notional:
            raise LiveClientError(
                f"{symbol}: nominal minNotional altı "
                f"({price * quantity:.2f} < {filters.min_notional:.2f})"
            )

    # -- Dead-man's switch (v3.0, opt-in) ------------------------------------

    def countdown_cancel_all(self, symbol: str, countdown_ms: int) -> None:
        """Belirtilen sürenin sonunda sembolün TÜM açık emirlerini iptal eder.

        DİKKAT: koruyucu stopları DA iptal eder → bot kalbi kesilirse
        pozisyon borsada korumasız kalır. Yalnızca --deadman-seconds ile
        iki kez onaylanarak kullanılmalıdır (varsayılan KAPALI).
        """
        self.client.signed_request(
            "POST", "/fapi/v1/countdownCancelAll",
            {"symbol": symbol, "countdownTime": str(int(countdown_ms))},
        )

    # -- Emirler ------------------------------------------------------------

    def place_entry(
        self, symbol: str, side: str, quantity: float,
        client_order_id: str, market: bool = True, price: float | None = None,
    ) -> ExchangeOrder:
        quantity = self.round_quantity(symbol, quantity)
        params: dict[str, object] = {
            "symbol": symbol,
            "side": "BUY" if side == "LONG" else "SELL",
            "type": "MARKET" if market else "LIMIT",
            "quantity": f"{quantity:.8f}".rstrip("0").rstrip("."),
            "newClientOrderId": client_order_id,
        }
        if not market:
            if price is None:
                raise LiveClientError("limit emir için fiyat gerekli")
            price = self.round_price(symbol, price)
            self.check_min_notional(symbol, price, quantity)
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
        stop_price = self.round_price(symbol, stop_price)
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
        """Pozisyonu kapatır: LONG → SELL, SHORT → BUY (reduce-only)."""
        quantity = self.round_quantity(symbol, quantity)
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

    def cancel_order_by_client_id(self, symbol: str, client_order_id: str) -> None:
        """v3.0: tek emri clientOrderId ile iptal eder (stop güncelleme için)."""
        self.client.signed_request(
            "DELETE", "/fapi/v1/order",
            {"symbol": symbol, "origClientOrderId": client_order_id},
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
    """OKX Demo Trading istemcisi (x-simulated-trading: 1).

    v3.0:
      - sCode≠0 → LiveClientError (sessiz başarı kaldırıldı)
      - Koruyucu stop: sunucu tarafı conditional algo (order-algo)
      - Toplu iptal: cancel-batch-orders + cancel-algos (cancel-all-orders
        ucu OKX v5'te yoktur — eski sürüm yanlış ucu çağırıyordu)
      - Baz miktar → kontrat dönüşümü (ctVal/lotSz/minSz)
    """

    def __init__(self, client: OkxSignedClient, td_mode: str = "isolated") -> None:
        self.client = client
        self.name = "okx-demo"
        self.td_mode = td_mode  # "isolated" | "cross"
        self._instruments: dict[str, dict[str, float]] = {}

    # -- Enstrüman meta (v3.0) ----------------------------------------------

    def fetch_instrument(self, inst_id: str) -> dict[str, float]:
        cached = self._instruments.get(inst_id)
        if cached is not None:
            return cached
        payload = self.client.public_request(
            "/api/v5/public/instruments",
            {"instType": "SWAP", "instId": inst_id},
        ).as_dict()
        rows = payload.get("data") or []
        row = rows[0] if rows else {}
        if not row:
            raise LiveClientError(f"{inst_id}: enstrüman bulunamadı")
        meta = {
            "ctVal": float(row.get("ctVal", 1.0) or 1.0),
            "lotSz": float(row.get("lotSz", 1.0) or 1.0),
            "minSz": float(row.get("minSz", 1.0) or 1.0),
            "tickSz": float(row.get("tickSz", 0.1) or 0.1),
        }
        self._instruments[inst_id] = meta
        return meta

    def base_to_contracts(self, inst_id: str, quantity_base: float) -> float:
        """Baz varlık miktarını kontrat sayısına (lotSz adımına) çevirir."""
        meta = self.fetch_instrument(inst_id)
        ct_val = meta["ctVal"]
        if ct_val <= 0:
            raise LiveClientError(f"{inst_id}: geçersiz ctVal={ct_val}")
        contracts_raw = quantity_base / ct_val
        contracts = _round_to_step(contracts_raw, meta["lotSz"])
        if contracts < meta["minSz"]:
            raise LiveClientError(
                f"{inst_id}: miktar minSz altına düştü "
                f"({contracts} kontrat < {meta['minSz']}; "
                f"{quantity_base} baz / ctVal={ct_val})"
            )
        return contracts

    def _round_trigger(self, inst_id: str, price: float) -> float:
        return _round_to_tick(price, self.fetch_instrument(inst_id)["tickSz"])

    # -- Emirler --------------------------------------------------------------

    @staticmethod
    def _check_scode(row: dict, context: str) -> None:
        """v3.0: OKX HTTP-200-içi hata kontrolü (sCode≠0 → hata)."""
        s_code = str(row.get("sCode", "0"))
        if s_code not in ("0", ""):
            raise LiveClientError(
                f"OKX {context} reddedildi: sCode={s_code} sMsg={row.get('sMsg', '')}"
            )

    def place_market(
        self, inst_id: str, side: str, size_base: float,
        client_order_id: str, reduce_only: bool = False,
    ) -> ExchangeOrder:
        """Market emri. `size_base` BAZ varlık birimidir → kontrata çevrilir.

        side: "LONG" (al) | "SHORT" (sat). Çıkış için doğru ters yönü
        göndermek place_reduce_only_exit kullanın.
        """
        contracts = self.base_to_contracts(inst_id, size_base)
        body = {
            "instId": inst_id,
            "tdMode": self.td_mode,
            "side": "buy" if side == "LONG" else "sell",
            "ordType": "market",
            "sz": f"{contracts:.8f}".rstrip("0").rstrip("."),
            "clOrdId": client_order_id,
            "reduceOnly": "true" if reduce_only else "false",
            "tag": OKX_ORDER_TAG,
        }
        payload = self.client.signed_request(
            "POST", "/api/v5/trade/order", body=body,
        ).as_dict()
        rows = payload.get("data") or [{}]
        row = rows[0] if rows else {}
        self._check_scode(row, f"market emri ({inst_id})")
        return ExchangeOrder(
            order_id=str(row.get("ordId", "")),
            client_order_id=str(row.get("clOrdId", client_order_id)),
            symbol=str(row.get("instId", inst_id)),
            side=str(body["side"]),
            status="PLACED" if str(row.get("sCode", "0")) == "0" else "REJECTED",
            price=0.0,
            quantity=size_base,
            executed_quantity=0.0,
            reduce_only=reduce_only,
            updated_ms=0,
        )

    def place_reduce_only_exit(
        self, inst_id: str, side: str, quantity: float, client_order_id: str,
    ) -> ExchangeOrder:
        """Pozisyonu kapatır: LONG → sell, SHORT → buy (reduce-only market).

        v3.0 DÜZELTMESİ: eski acil durum akışı LONG için buy gönderiyordu —
        reduce-only buy LONG'u kapatmaz, emir reddedilir ve pozisyon açık
        kalırdı. Yön artık burada düzgün çevrilir.
        """
        close_side = "SHORT" if side == "LONG" else "LONG"
        return self.place_market(
            inst_id, close_side, quantity, client_order_id, reduce_only=True,
        )

    def place_protective_stop(
        self, inst_id: str, side: str, stop_price: float, client_order_id: str,
    ) -> ExchangeOrder:
        """Sunucu tarafı koruyucu stop: conditional algo (market tetiklenir).

        orderPx=-1 → tetiklenince MARKET yürütür (Binance STOP_MARKET
        closePosition=true eşdeğeri, reduce-only).
        """
        # enstrüman meta önbelleği/tik boyutu doğrulaması (hata varsa burada patlar)
        self.fetch_instrument(inst_id)
        trigger = self._round_trigger(inst_id, stop_price)
        close_side = "SHORT" if side == "LONG" else "LONG"
        body = {
            "instId": inst_id,
            "tdMode": self.td_mode,
            "side": "buy" if close_side == "LONG" else "sell",
            "ordType": "conditional",
            # closeFraction="1" → tetiklenince POZİSYONUN TAMAMI kapanır
            # (Binance closePosition=true eşdeğeri). OKX kuralı: conditional
            # + reduceOnly + NET modda geçerli; bu durumda sz gönderilmez
            # (ccxt teyidi: hata kodları 51327-51330).
            "closeFraction": "1",
            "reduceOnly": "true",
            "triggerPx": f"{trigger}",
            "orderPx": "-1",
            "clOrdId": client_order_id,
            "tag": OKX_ORDER_TAG,
        }
        payload = self.client.signed_request(
            "POST", "/api/v5/trade/order-algo", body=body,
        ).as_dict()
        rows = payload.get("data") or [{}]
        row = rows[0] if rows else {}
        self._check_scode(row, f"koruyucu stop ({inst_id})")
        return ExchangeOrder(
            order_id=str(row.get("algoId", "")),
            client_order_id=str(row.get("clOrdId", client_order_id)),
            symbol=str(row.get("instId", inst_id)),
            side=str(body["side"]),
            status="CONDITIONAL",
            price=trigger,
            quantity=0.0,
            executed_quantity=0.0,
            reduce_only=True,
            updated_ms=0,
        )

    def cancel_algo_stop(self, inst_id: str, algo_id: str) -> None:
        self.client.signed_request(
            "POST", "/api/v5/trade/cancel-algos",
            body=[{"instId": inst_id, "algoId": algo_id}],
        )

    def cancel_all_orders(self, inst_id: str) -> None:
        """v3.0: GERÇEK OKX uçlarıyla toplu iptal.

        Eski sürümün çağırdığı POST /api/v5/trade/cancel-all-orders OKX v5
        dokümanında YOKTUR (ccxt ucu listesi teyitli). Doğrusu:
          - sıradan emirler → POST /api/v5/trade/cancel-batch-orders
          - algo (conditional) emirler → POST /api/v5/trade/cancel-algos
        """
        try:
            pending = self.client.signed_request(
                "GET", "/api/v5/trade/orders-pending",
                params={"instId": inst_id, "instType": "SWAP"},
            ).as_dict().get("data") or []
            if pending:
                batch = [
                    {"instId": o["instId"], "ordId": o["ordId"]}
                    for o in pending if isinstance(o, dict) and o.get("ordId")
                ]
                if batch:
                    self.client.signed_request(
                        "POST", "/api/v5/trade/cancel-batch-orders", body=batch,
                    )
        except LiveClientError:
            raise
        try:
            algos = self.client.signed_request(
                "GET", "/api/v5/trade/orders-algo-pending",
                params={"instId": inst_id, "ordType": "conditional"},
            ).as_dict().get("data") or []
            algo_batch = [
                {"instId": o["instId"], "algoId": o["algoId"]}
                for o in algos if isinstance(o, dict) and o.get("algoId")
            ]
            if algo_batch:
                self.client.signed_request(
                    "POST", "/api/v5/trade/cancel-algos", body=algo_batch,
                )
        except LiveClientError:
            raise

    def cancel_all_after(self, timeout_seconds: int) -> None:
        """Dead-man's switch (opt-in): timeout sn içinde kalp gelmezse
        tag=ACARBOT olan tüm emirler iptal edilir. 0 = geri sayımı durdurur.
        DİKKAT: koruyucu stopları da kapsar."""
        self.client.signed_request(
            "POST", "/api/v5/trade/cancel-all-after",
            body={"tag": OKX_ORDER_TAG, "timeout": str(int(timeout_seconds))},
        )

    # -- Sorgular ---------------------------------------------------------------

    def fetch_positions(self) -> list[ExchangePosition]:
        payload = self.client.signed_request(
            "GET", "/api/v5/account/positions",
        ).as_dict()
        out: list[ExchangePosition] = []
        for row in payload.get("data") or []:
            amount = float(row.get("pos", 0.0) or 0.0)
            if amount == 0:
                continue
            # v3.0 DÜZELTMESİ: OKX `pos` alanı KONTRAT cinsindendir; acil
            # durum flatten'ı doğru miktarda göndermek için baz varlığa
            # çevrilir (eski sürüm kontratı baz sanıyordu → 100x emir!).
            inst_id = str(row.get("instId", ""))
            try:
                ct_val = self.fetch_instrument(inst_id)["ctVal"]
            except LiveClientError as exc:
                logger.warning(
                    "%s ctVal okunamadı (%s) — miktar kontrat sayısı kabul edildi",
                    inst_id, exc,
                )
                ct_val = 1.0
            out.append(ExchangePosition(
                symbol=inst_id,
                side="LONG" if amount > 0 else "SHORT",
                quantity=abs(amount) * ct_val,
                entry_price=float(row.get("avgPx", 0.0) or 0.0),
                unrealized_pnl=float(row.get("upl", 0.0) or 0.0),
            ))
        return out

    def fetch_open_orders(self, symbol: str | None = None) -> list[ExchangeOrder]:
        """Sıradan + algo (conditional stop) emirleri birleştirir."""
        out: list[ExchangeOrder] = []
        params: dict[str, object] = {"instType": "SWAP"}
        if symbol:
            params["instId"] = symbol
        pending = self.client.signed_request(
            "GET", "/api/v5/trade/orders-pending", params=params,
        ).as_dict().get("data") or []
        for row in pending:
            out.append(ExchangeOrder(
                order_id=str(row.get("ordId", "")),
                client_order_id=str(row.get("clOrdId", "")),
                symbol=str(row.get("instId", "")),
                side=str(row.get("side", "")),
                status=str(row.get("state", "")),
                price=float(row.get("px", 0.0) or 0.0),
                quantity=float(row.get("accFillSz", 0.0) or 0.0),
                executed_quantity=float(row.get("accFillSz", 0.0) or 0.0),
                reduce_only=str(row.get("reduceOnly", "false")).lower() == "true",
                updated_ms=int(row.get("cTime", 0) or 0),
            ))
        algo_params: dict[str, object] = {"instType": "SWAP", "ordType": "conditional"}
        if symbol:
            algo_params["instId"] = symbol
        algos = self.client.signed_request(
            "GET", "/api/v5/trade/orders-algo-pending", params=algo_params,
        ).as_dict().get("data") or []
        for row in algos:
            out.append(ExchangeOrder(
                order_id=str(row.get("algoId", "")),
                client_order_id=str(row.get("clOrdId", "")),
                symbol=str(row.get("instId", "")),
                side=str(row.get("side", "")),
                status="CONDITIONAL",
                price=float(row.get("triggerPx", 0.0) or 0.0),
                quantity=0.0,
                executed_quantity=0.0,
                reduce_only=True,
                updated_ms=int(row.get("cTime", 0) or 0),
            ))
        return out

    def fetch_perp_candles(self, inst_id: str, bar: str, limit: int = 100):
        """GERÇEK OKX SWAP mum verisi (public uç)."""
        from infra.market_data.models import Candle
        from infra.exchanges.base import PublicMarketDataError
        raw = self.client.public_request(
            "/api/v5/market/candles",
            {"instId": inst_id, "bar": bar, "limit": min(limit, 300)},
        ).as_dict().get("data") or []
        try:
            return [
                Candle(int(row[0]), float(row[1]), float(row[2]),
                       float(row[3]), float(row[4]), float(row[5]))
                for row in reversed(raw)
            ]
        except (TypeError, ValueError, IndexError) as exc:
            raise PublicMarketDataError("OKX klines bozuk") from exc
