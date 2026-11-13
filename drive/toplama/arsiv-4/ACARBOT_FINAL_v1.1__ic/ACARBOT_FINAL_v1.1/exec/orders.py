"""Emir yaşam döngüsü modeli (Yorum 1-A) ve gerçekçi maker dolumu (Yorum 2-5).

ESKİ DURUM:
  Giriş emri "post_only" etiketiyle anında ve her zaman dolduruluyordu;
  emir defteri VWAP'ından taker gibi kayma uygulanıyordu (kendi içinde
  tutarsız). Kuyruk, kısmi dolum, dolmama, TTL yoktu.

YENİ MODEL:
  - Emir durumları: NEW → PARTIALLY_FILLED → FILLED | CANCELED | EXPIRED
  - Post-only emir defterin BID tarafına girer (LONG). Kuyruk önünde
    bekleyen hacim tahmin edilir; fiyat seviyemize gelirse işlem gören
    hacim önce kuyruğu eritir, sonra bizim kalan miktarımızı doldurur.
  - Fiyat seviyemizin ALTINA sarkarsa (trade-through) kalan miktar dolar.
  - TTL dolarsa emir EXPIRED olur, en fazla `max_replacements` kez yeniden
    yerleştirilir; sonra sinyal düşer (dolmayan maker = iyi şey).
  - Ters seçilim (adverse selection) modelin doğal sonucudur: fiyat senin
    seviyene düşerek seni doldurduğunda, tam da fiyatın aleyhine döndüğü
    andır. Bu gerçekçilik backtest'e taşınır.
  - Post-only emre taker kayması UYGULANMAZ (maker). Kayma yalnızca
    MARKET/STOP emirlerinde uygulanır.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from uuid import uuid4


class OrderStatus(str, Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"


class OrderType(str, Enum):
    POST_ONLY_LIMIT = "POST_ONLY_LIMIT"
    MARKET = "MARKET"


class OrderSide(str, Enum):
    BUY = "BUY"      # LONG girişi / SHORT çıkışı
    SELL = "SELL"    # SHORT girişi / LONG çıkışı


@dataclass
class Fill:
    price: float
    quantity: float
    fee: float
    timestamp_ms: int
    is_maker: bool


@dataclass
class Order:
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    limit_price: float | None = None
    status: OrderStatus = OrderStatus.NEW
    filled_quantity: float = 0.0
    fills: list[Fill] = field(default_factory=list)
    created_ms: int = 0
    ttl_ms: int = 45_000
    maker_fee_rate: float = 0.0002
    taker_fee_rate: float = 0.0005
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    reduce_only: bool = False
    replacement_count: int = 0

    @property
    def leaves_quantity(self) -> float:
        return max(0.0, self.quantity - self.filled_quantity)

    @property
    def is_active(self) -> bool:
        return self.status in (OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED)

    @property
    def average_fill_price(self) -> float | None:
        if not self.fills:
            return None
        notional = sum(f.price * f.quantity for f in self.fills)
        qty = sum(f.quantity for f in self.fills)
        return notional / qty if qty > 0 else None

    @property
    def total_fee(self) -> float:
        return sum(f.fee for f in self.fills)

    def apply_fill(self, price: float, quantity: float, timestamp_ms: int,
                   is_maker: bool) -> Fill:
        if quantity <= 0:
            raise ValueError("dolum miktarı pozitif olmalı")
        fee_rate = self.maker_fee_rate if is_maker else self.taker_fee_rate
        fill = Fill(
            price=price,
            quantity=quantity,
            fee=price * quantity * fee_rate,
            timestamp_ms=timestamp_ms,
            is_maker=is_maker,
        )
        self.fills.append(fill)
        self.filled_quantity += quantity
        if self.filled_quantity >= self.quantity - 1e-12:
            self.status = OrderStatus.FILLED
            self.filled_quantity = self.quantity
        else:
            self.status = OrderStatus.PARTIALLY_FILLED
        return fill

    def cancel(self, status: OrderStatus = OrderStatus.CANCELED) -> None:
        if status not in (OrderStatus.CANCELED, OrderStatus.EXPIRED):
            raise ValueError("iptal durumu CANCELED veya EXPIRED olmalı")
        self.status = status


@dataclass
class _BookState:
    """Bir emrin dolum ilerlemesi için simülatör içi durum."""
    queue_ahead: float          # bizden önce bekleyen tahmini baz hacim
    baseline_per_second: float  # yerleştirme anındaki likidite tahmini


class MakerFillSimulator:
    """Tick bazlı maker dolum simülatörü.

    Kuyruk modeli (muhafazakâr):
      queue_ahead = depth_factor * baseline_per_second * queue_horizon_s
      - fiyat seviyemize DOKUNUYORSA (== limit): işlem gören hacim önce
        kuyruğu eritir; artan kısım bizi doldurur (kısmi dolum).
      - fiyat seviyemizin ÖTESİNE GEÇERSE (trade-through): kalan hep dolar.
      - TTL dolarsa EXPIRED.

    Böylece "her maker emri dolar" varsayımı ortadan kalkar; dolmama ve
    kısmi dolum gerçekçi biçimde modellenir.
    """

    def __init__(
        self,
        depth_factor: float = 8.0,
        queue_horizon_seconds: float = 10.0,
        min_fill_fraction: float = 0.05,
    ) -> None:
        if depth_factor <= 0 or queue_horizon_seconds <= 0:
            raise ValueError("derinlik parametreleri pozitif olmalı")
        self.depth_factor = depth_factor
        self.queue_horizon_seconds = queue_horizon_seconds
        self.min_fill_fraction = min_fill_fraction
        self._book_states: dict[str, _BookState] = {}

    def register(self, order: Order, baseline_per_second: float) -> None:
        """Emir yerleştirilirken kuyruk tahminini kurar."""
        if baseline_per_second < 0:
            raise ValueError("likidite tahmini negatif olamaz")
        queue_ahead = (
            self.depth_factor
            * baseline_per_second
            * self.queue_horizon_seconds
        )
        self._book_states[order.id] = _BookState(
            queue_ahead=queue_ahead,
            baseline_per_second=baseline_per_second,
        )

    def process_tick(
        self,
        order: Order,
        price: float,
        tick_base_volume: float,
        now_ms: int,
    ) -> Fill | None:
        """Bir fiyat güncellemesinde emrin dolumunu değerlendirir.

        Döndürür: oluşan (kısmi) Fill veya None.
        Yön semantiği: BUY limiti alt taraftan doldurulur, SELL üstten.
        """
        if not order.is_active or order.limit_price is None:
            return None
        if not isfinite(price) or price <= 0:
            raise ValueError("fiyat geçersiz")
        state = self._book_states.get(order.id)
        if state is None:
            state = _BookState(queue_ahead=0.0, baseline_per_second=0.0)
            self._book_states[order.id] = state

        is_buy = order.side == OrderSide.BUY
        limit = order.limit_price
        trade_through = price < limit if is_buy else price > limit
        touches = abs(price - limit) <= max(limit * 1e-9, 0.0) or (
            (price <= limit if is_buy else price >= limit)
        )

        filled = None
        if trade_through:
            # Seviyenin ötesinde işlem: kalanın tamamı dolar (muhafazakâr:
            # kuyruk bizden önce erimiş kabul edilir).
            filled = order.apply_fill(order.limit_price, order.leaves_quantity,
                                      now_ms, is_maker=True)
        elif touches:
            # Seviyede işlem gördü: hacim önce kuyruğu eritir.
            volume = max(0.0, tick_base_volume)
            if state.queue_ahead >= volume:
                state.queue_ahead -= volume
            else:
                available_for_us = volume - state.queue_ahead
                state.queue_ahead = 0.0
                take = min(order.leaves_quantity, available_for_us)
                # Çok küçük dolumları biriktirmemek için alt oran filtresi:
                if take / order.quantity >= self.min_fill_fraction:
                    filled = order.apply_fill(limit, take, now_ms, is_maker=True)

        # TTL kontrolü
        if order.is_active and now_ms - order.created_ms >= order.ttl_ms:
            order.cancel(OrderStatus.EXPIRED)
        return filled

    def release(self, order_id: str) -> None:
        self._book_states.pop(order_id, None)


def market_fill_price(
    trigger_price: float,
    side: OrderSide,
    slippage_rate: float,
) -> float:
    """MARKET/STOP emri için kaymalı dolum fiyatı (taker)."""
    if not isfinite(trigger_price) or trigger_price <= 0:
        raise ValueError("tetik fiyatı geçersiz")
    if slippage_rate < 0 or slippage_rate >= 1:
        raise ValueError("kayma oranı [0,1) aralığında olmalı")
    if side == OrderSide.BUY:
        return trigger_price * (1.0 + slippage_rate)
    return trigger_price * (1.0 - slippage_rate)
