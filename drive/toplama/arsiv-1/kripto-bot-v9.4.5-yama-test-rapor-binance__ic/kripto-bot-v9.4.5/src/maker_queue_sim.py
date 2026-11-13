"""src/maker_queue_sim.py — Gerçekçi Pasif Maker Kuyruk ve Ters Seçilim (Adverse Selection) Simülatörü.

Amaç (Denetim Madde 2.a & 3.1):
  Paper modda pasif limit (`post_only`) emirlerin anında 0 kayma ve %100 olasılıkla
  doldurulması yanılsamasını ortadan kaldırır.
  - Pasif AL (LONG giriş / SHORT çıkış) emri `best_bid` seviyesinde kuyruğa girer.
  - Pasif SAT (SHORT giriş / LONG çıkış) emri `best_ask` seviyesinde kuyruğa girer.
  - Önümüzde bekleyen kuyruk derinliği (`queue_ahead_qty`), paritenin dakikalık hacmi
    ve emir büyüklüğüne göre muhafazakâr biçimde tahmin edilir.
  - Emir YALNIZCA şu iki koşuldan biri süre aşımından (`timeout_sec`) önce gerçekleşirse dolar:
      1) Piyasa karşı fiyatı limit seviyemizi delip geçerse (`ask <= limit_px` veya `bid >= limit_px`
         ya da işlem fiyatı seviyemizin ötesine geçerse),
      2) Limit seviyemizden gerçekleşen agresif işlemler önümüzdeki kuyruğu eritip miktarımızı doldurursa.
  - Fiyat lehimize kaçıp emrimize hiç dokunmazsa süre sonunda emir İPTAL EDİLİR (`expired_unfilled`)
    ve dolmayan sinyal istatistiklere + karşı-olgu (counterfactual) izleyicisine kaydedilir.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RestingMakerOrder:
    order_id: str
    exchange: str
    symbol: str
    side: str  # "buy" | "sell"
    limit_price: float
    requested_qty: float
    queue_ahead_qty: float
    created_ts: float
    expires_ts: float
    initial_mid: float
    filled_qty: float = 0.0
    fill_reason: str = ""
    status: str = "open"  # "open" | "filled" | "partial_expired" | "expired_unfilled" | "rejected_post_only"
    done_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)


class RealisticMakerQueueSimulator:
    """Canlı BBO ve aggTrade/trades akışıyla beslenen pasif limit emir kuyruğu."""

    def __init__(
        self,
        *,
        queue_minute_vol_fraction: float = 0.004,
        min_queue_ahead_usdt: float = 120.0,
        max_queue_ahead_usdt: float = 2_500.0,
        max_history: int = 300,
    ) -> None:
        self.queue_minute_vol_fraction = max(0.0, float(queue_minute_vol_fraction))
        self.min_queue_ahead_usdt = max(0.0, float(min_queue_ahead_usdt))
        self.max_queue_ahead_usdt = max(self.min_queue_ahead_usdt, float(max_queue_ahead_usdt))
        self.max_history = max(20, int(max_history))

        self._orders: dict[str, RestingMakerOrder] = {}
        self._by_pair: dict[tuple[str, str], list[str]] = {}
        self.history: list[dict[str, Any]] = []
        self.stats: dict[str, Any] = {
            "submitted": 0,
            "filled": 0,
            "partial_filled": 0,
            "expired_unfilled": 0,
            "post_only_rejected": 0,
            "total_wait_ms": 0.0,
            "adverse_runaway_bps_sum": 0.0,
        }

    def estimate_queue_ahead_qty(
        self, limit_price: float, minute_qv_usdt: float = 200_000.0
    ) -> float:
        if limit_price <= 0:
            return 0.0
        est_usdt = max(
            self.min_queue_ahead_usdt,
            min(self.max_queue_ahead_usdt, float(minute_qv_usdt or 200_000.0) * self.queue_minute_vol_fraction),
        )
        return est_usdt / limit_price

    def register_order(
        self,
        *,
        exchange: str,
        symbol: str,
        side: str,
        qty: float,
        bid: float,
        ask: float,
        minute_qv_usdt: float = 200_000.0,
        timeout_sec: float = 3.5,
        now_ts: float | None = None,
    ) -> RestingMakerOrder:
        ex_k = str(exchange or "okx").strip().lower()
        side_k = str(side or "buy").strip().lower()
        now = float(now_ts if now_ts is not None else time.time())
        oid = f"mkq-{uuid.uuid4().hex[:12]}"
        self.stats["submitted"] += 1

        if bid <= 0 or ask <= 0 or ask < bid or qty <= 0:
            order = RestingMakerOrder(
                order_id=oid,
                exchange=ex_k,
                symbol=symbol,
                side=side_k,
                limit_price=max(bid, ask, 0.0),
                requested_qty=max(0.0, float(qty)),
                queue_ahead_qty=0.0,
                created_ts=now,
                expires_ts=now,
                initial_mid=0.0,
                status="rejected_post_only",
                fill_reason="invalid_bbo",
            )
            order.done_event.set()
            self.stats["post_only_rejected"] += 1
            return order

        limit_px = float(bid) if side_k == "buy" else float(ask)
        mid = (float(bid) + float(ask)) / 2.0
        q_ahead = self.estimate_queue_ahead_qty(limit_px, minute_qv_usdt)
        order = RestingMakerOrder(
            order_id=oid,
            exchange=ex_k,
            symbol=symbol,
            side=side_k,
            limit_price=limit_px,
            requested_qty=float(qty),
            queue_ahead_qty=q_ahead,
            created_ts=now,
            expires_ts=now + max(0.05, float(timeout_sec)),
            initial_mid=mid,
        )
        self._orders[oid] = order
        self._by_pair.setdefault((ex_k, symbol), []).append(oid)
        return order

    def on_bbo(
        self,
        exchange: str,
        symbol: str,
        bid: float,
        ask: float,
        now_ts: float | None = None,
    ) -> None:
        """Canlı BBO güncellemesinde fiyat limit emrimizi delip geçtiyse doldurur."""
        if bid <= 0 or ask <= 0:
            return
        ex_k = str(exchange or "").strip().lower()
        oids = list(self._by_pair.get((ex_k, symbol)) or ())
        if not oids:
            return
        now = float(now_ts if now_ts is not None else time.time())
        for oid in oids:
            order = self._orders.get(oid)
            if order is None or order.status != "open":
                continue
            if now > order.expires_ts:
                self._expire_order(order, current_mid=(bid + ask) / 2.0, now_ts=now)
                continue
            if order.side == "buy":
                if ask <= order.limit_price:
                    self._complete_fill(order, reason="bbo_ask_crossed_bid", now_ts=now)
                elif bid < order.limit_price:
                    # Fiyat seviyemizin altına sarktı -> kuyruk tamamen temizlendi
                    self._complete_fill(order, reason="bbo_bid_dropped_through_limit", now_ts=now)
            else:
                if bid >= order.limit_price:
                    self._complete_fill(order, reason="bbo_bid_crossed_ask", now_ts=now)
                elif ask > order.limit_price:
                    # Fiyat seviyemizin üstüne çıktı -> satış kuyruğu tamamen temizlendi
                    self._complete_fill(order, reason="bbo_ask_lifted_through_limit", now_ts=now)

    def on_trade(
        self,
        exchange: str,
        symbol: str,
        price: float,
        qty: float,
        *,
        is_buyer_maker: bool,
        now_ts: float | None = None,
    ) -> None:
        """Canlı işlem akışıyla kuyruk erimesini ve delip geçen işlemleri simüle eder."""
        if price <= 0 or qty <= 0:
            return
        ex_k = str(exchange or "").strip().lower()
        oids = list(self._by_pair.get((ex_k, symbol)) or ())
        if not oids:
            return
        now = float(now_ts if now_ts is not None else time.time())
        for oid in oids:
            order = self._orders.get(oid)
            if order is None or order.status != "open":
                continue
            if now > order.expires_ts:
                self._expire_order(order, current_mid=price, now_ts=now)
                continue

            eps = order.limit_price * 1e-6
            if order.side == "buy":
                if price < order.limit_price - eps:
                    self._complete_fill(order, reason="trade_through_buy_limit", now_ts=now)
                elif price <= order.limit_price + eps and is_buyer_maker:
                    # Satıcı agresif vurdu, pasif alıcı kuyruğunu eritti
                    self._consume_queue(order, qty, now_ts=now)
            else:
                if price > order.limit_price + eps:
                    self._complete_fill(order, reason="trade_through_sell_limit", now_ts=now)
                elif price >= order.limit_price - eps and (not is_buyer_maker):
                    # Alıcı agresif kaldırdı, pasif satıcı kuyruğunu eritti
                    self._consume_queue(order, qty, now_ts=now)

    def _consume_queue(self, order: RestingMakerOrder, trade_qty: float, *, now_ts: float) -> None:
        rem_trade = float(trade_qty)
        if order.queue_ahead_qty > 0:
            used_for_queue = min(order.queue_ahead_qty, rem_trade)
            order.queue_ahead_qty -= used_for_queue
            rem_trade -= used_for_queue
        if rem_trade > 0 and order.queue_ahead_qty <= 1e-12:
            needed = max(0.0, order.requested_qty - order.filled_qty)
            take = min(needed, rem_trade)
            order.filled_qty += take
            if order.filled_qty >= order.requested_qty * 0.999:
                order.filled_qty = order.requested_qty
                self._complete_fill(order, reason="queue_depleted_at_touch", now_ts=now_ts)

    def _complete_fill(self, order: RestingMakerOrder, *, reason: str, now_ts: float) -> None:
        if order.status != "open":
            return
        order.filled_qty = order.requested_qty
        order.status = "filled"
        order.fill_reason = reason
        wait_ms = max(0.0, (now_ts - order.created_ts) * 1000.0)
        self.stats["filled"] += 1
        self.stats["total_wait_ms"] += wait_ms
        self._cleanup_and_record(order, current_mid=order.limit_price, wait_ms=wait_ms)
        order.done_event.set()

    def _expire_order(
        self, order: RestingMakerOrder, *, current_mid: float, now_ts: float
    ) -> None:
        if order.status != "open":
            return
        wait_ms = max(0.0, (now_ts - order.created_ts) * 1000.0)
        if order.filled_qty > 0:
            order.status = "partial_expired"
            order.fill_reason = "partial_queue_timeout"
            self.stats["partial_filled"] += 1
        else:
            order.status = "expired_unfilled"
            order.fill_reason = "timeout_price_ran_away"
            self.stats["expired_unfilled"] += 1
            if order.initial_mid > 0 and current_mid > 0:
                move_bps = (
                    (current_mid - order.initial_mid) / order.initial_mid * 10_000.0
                    if order.side == "buy"
                    else (order.initial_mid - current_mid) / order.initial_mid * 10_000.0
                )
                self.stats["adverse_runaway_bps_sum"] += move_bps
        self.stats["total_wait_ms"] += wait_ms
        self._cleanup_and_record(order, current_mid=current_mid, wait_ms=wait_ms)
        order.done_event.set()

    def _cleanup_and_record(
        self, order: RestingMakerOrder, *, current_mid: float, wait_ms: float
    ) -> None:
        pair_list = self._by_pair.get((order.exchange, order.symbol))
        if pair_list and order.order_id in pair_list:
            pair_list.remove(order.order_id)
        self._orders.pop(order.order_id, None)
        self.history.append(
            {
                "order_id": order.order_id,
                "exchange": order.exchange,
                "symbol": order.symbol,
                "side": order.side,
                "limit_price": order.limit_price,
                "requested_qty": order.requested_qty,
                "filled_qty": order.filled_qty,
                "status": order.status,
                "reason": order.fill_reason,
                "wait_ms": round(wait_ms, 1),
                "end_mid": current_mid,
            }
        )
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history :]

    async def await_fill_or_expire(
        self,
        order: RestingMakerOrder,
        *,
        current_mid_fn=None,
    ) -> RestingMakerOrder:
        if order.status != "open":
            return order
        remaining = max(0.01, order.expires_ts - time.time())
        try:
            await asyncio.wait_for(order.done_event.wait(), timeout=remaining)
        except asyncio.TimeoutError:
            cur_mid = float(current_mid_fn()) if callable(current_mid_fn) else order.initial_mid
            self._expire_order(order, current_mid=cur_mid, now_ts=time.time())
        return order

    def summary(self) -> dict[str, Any]:
        sub = int(self.stats["submitted"])
        filled = int(self.stats["filled"])
        part = int(self.stats["partial_filled"])
        exp = int(self.stats["expired_unfilled"])
        fill_rate = ((filled + part) / sub * 100.0) if sub > 0 else 0.0
        avg_wait = (float(self.stats["total_wait_ms"]) / sub) if sub > 0 else 0.0
        avg_runaway = (float(self.stats["adverse_runaway_bps_sum"]) / exp) if exp > 0 else 0.0
        return {
            "submitted": sub,
            "filled": filled,
            "partial_filled": part,
            "expired_unfilled": exp,
            "post_only_rejected": int(self.stats["post_only_rejected"]),
            "open_resting": len(self._orders),
            "fill_rate_pct": round(fill_rate, 2),
            "avg_wait_ms": round(avg_wait, 1),
            "avg_unfilled_runaway_bps": round(avg_runaway, 2),
        }
