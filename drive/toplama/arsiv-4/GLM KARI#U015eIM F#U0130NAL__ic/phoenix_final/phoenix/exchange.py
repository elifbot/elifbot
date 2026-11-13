"""Borsa bağlantısı (ccxt): dry / testnet / canlı.

Phoenix v2.0 temeli + FUSION_PRO'nun enstrüman limitleri (stepSize/minQty) + 3'lü
yeniden deneme + reduceOnly STOP_MARKET / TAKE_PROFIT_MARKET. dry modda hiçbir ağ
çağrısı yapılmaz; testnet gerçek emirleri sahte ortama gönderir.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

log = logging.getLogger("phoenix.exchange")


class Exchange:
    def __init__(self, cfg, dry: bool | None = None):
        import ccxt  # geç import: dry modda ccxt gerekmez

        self.cfg = cfg
        e = cfg.exec
        self.dry = (e.engine == "dry") if dry is None else dry
        self.ex = ccxt.binanceusdm({
            "apiKey": os.getenv("BINANCE_API_KEY", ""),
            "secret": os.getenv("BINANCE_API_SECRET", ""),
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })
        if e.engine in ("dry", "testnet"):
            self.ex.set_sandbox_mode(True)
        self._markets: dict[str, Any] = {}

    # ------------------------------------------------------------- yardımcılar
    def _retry(self, fn, *a, **k):
        last: Exception | None = None
        for i in range(3):
            try:
                return fn(*a, **k)
            except Exception as e:  # noqa: BLE001
                last = e
                code = getattr(e, "code", None) or getattr(getattr(e, "args", [None])[0] if e.args else None, "code", None)
                log.warning("borsa çağrısı %d/3 başarısız: %s", i + 1, e)
                if str(e).find("-4046") >= 0:  # kaldıraç zaten doğru
                    return None
                time.sleep(1.5 * (i + 1))
        raise last  # type: ignore[misc]

    def market(self, symbol: str):
        if symbol not in self._markets:
            mk = self.ex.load_markets()
            self._markets = mk
        return self._markets[symbol]

    # ------------------------------------------------------------- veri
    def ohlcv(self, symbol: str, timeframe: str, bars: int) -> list[list]:
        return self._retry(self.ex.fetch_ohlcv, symbol, timeframe, limit=bars)

    def balance_usdt(self) -> float:
        bal = self._retry(self.ex.fetch_balance)
        return float(bal["USDT"]["total"]) if "USDT" in bal else 0.0

    # ------------------------------------------------------------- emirler
    def ensure_leverage(self, symbol: str, leverage: int) -> None:
        m = self.market(symbol)
        try:
            self.ex.set_margin_mode(self.cfg.risk.margin_mode, symbol)
        except Exception as e:  # noqa: BLE001 — zaten doğru modda olabilir
            if "-4046" not in str(e):
                log.warning("margin mode: %s", e)
        self._retry(self.ex.set_leverage, max(1, min(leverage, int(m.get("limits", {}).get("leverage", {}).get("max", leverage) or leverage))), symbol)

    def normalize_qty(self, symbol: str, qty: float) -> float:
        m = self.market(symbol)
        q = self.ex.amount_to_precision(symbol, qty)
        q = float(q)
        lim = m.get("limits", {}).get("amount", {})
        mn = float(lim.get("min") or 0.0)
        if mn and q < mn:
            return 0.0
        return q

    def market_order(self, symbol: str, side: str, qty: float, reduce_only: bool = False) -> dict:
        params: dict = {"newOrderRespType": "RESULT"}
        if reduce_only:
            params["reduceOnly"] = True
        return self._retry(self.ex.create_order, symbol, "market", side, qty, None, None, params)

    def stop_orders(self, symbol: str, side_pos: str, qty: float, sl: float, tp: float) -> dict:
        """Pozisyon koruması: STOP_MARKET + TAKE_PROFIT_MARKET (reduceOnly, MARK_PRICE)."""
        exit_side = "sell" if side_pos == "long" else "buy"
        sl_o = self._retry(self.ex.create_order, symbol, "STOP_MARKET", exit_side, qty, None, None,
                           {"stopPrice": sl, "reduceOnly": True, "workingType": "MARK_PRICE"})
        tp_o = self._retry(self.ex.create_order, symbol, "TAKE_PROFIT_MARKET", exit_side, qty, None, None,
                           {"stopPrice": tp, "reduceOnly": True, "workingType": "MARK_PRICE"})
        return {"sl": sl_o, "tp": tp_o}

    def cancel_stops(self, symbol: str) -> None:
        try:
            orders = self._retry(self.ex.fetch_open_orders, symbol)
            for o in orders:
                if o.get("type") in ("STOP_MARKET", "TAKE_PROFIT_MARKET", "STOP", "TAKE_PROFIT"):
                    self._retry(self.ex.cancel_order, o["id"], symbol)
        except Exception as e:  # noqa: BLE001
            log.warning("stop iptali: %s", e)

    def positions(self) -> dict[str, dict]:
        ps = self._retry(self.ex.fetch_positions)
        out = {}
        for p in ps:
            amt = float(p.get("contracts") or 0)
            if amt:
                side = "long" if (p.get("side") or "long") == "long" else "short"
                out[p["symbol"]] = {"side": side, "qty": amt * (1 if side == "long" else -1),
                                    "entry": float(p.get("entryPrice") or 0)}
        return out
