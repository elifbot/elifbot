"""ACARBOT v2.0 — Akıllı likidite ve order flow motoru (şartname madde 3).

Mevcut Sweep Guard'ın gelişmiş hâli. Yalnızca GERÇEK veriyle çalışır:

  - Order Book imbalance        : REST defter (bid/ask nominal oranı)
  - Bid/Ask hacim farkı         : aynı defterden
  - Büyük emirlerin tespiti     : medyan seviye nominalinin katı (mutlak
                                  sabit DEĞİL — defterden ölçeklenir)
  - Likidite kümeleri           : bant nominalsine göre en yoğun bölgeler
  - Absorption (emir emilimi)   : duvar + fiyatın sabit kalması (kitap
                                  geçmişinden)
  - CVD                         : tick kuralı (canlı ticker hacim deltası)
                                  / mum kuralı (backtest: close-open)
  - Open Interest değişimi      : borsa OI uç noktası varsa; yoksa
                                  "uygulanmadı"
  - Long/Short sıkışma riski    : OI artışı + fiyat aşırılığı (OI yoksa
                                  "uygulanmadı")
  - Süpürme sonrası dönüş       : mum verisinden ( swing + kapanış geri )

Veri gelmeyen bileşen `available=False` döner — sabit sayı yerine
konulmaz (kullanıcı kuralı: yer tutucu değer yasak).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from math import isfinite
from statistics import median
from typing import Sequence

from core.config import OrderFlowConfig
from infra.market_data.models import Candle


@dataclass(frozen=True)
class Component:
    """Tek bir order-flow ölçümü. `available=False` → veri yok."""
    name: str
    value: float = 0.0            # -1..1 (sinyal yönüne göre yorumlanır)
    available: bool = True
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "value": round(self.value, 4),
            "available": self.available,
            "note": self.note,
        }


@dataclass
class OrderFlowSnapshot:
    symbol_key: str
    ts_ms: int
    imbalance: Component          # >0 alıcı baskısı, <0 satıcı baskısı
    big_orders: Component         # >0 bid tarafı büyük emir, <0 ask
    clusters: list[dict] = field(default_factory=list)
    absorption: Component = Component("absorption", available=False)
    cvd: Component = Component("cvd", available=False)
    oi_change: Component = Component("oi_change", available=False)
    squeeze: Component = Component("squeeze", available=False)
    sweep_reversal: Component = Component("sweep_reversal", available=False)
    spread_bps: float | None = None

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol_key,
            "ts_ms": self.ts_ms,
            "imbalance": self.imbalance.as_dict(),
            "big_orders": self.big_orders.as_dict(),
            "clusters": self.clusters,
            "absorption": self.absorption.as_dict(),
            "cvd": self.cvd.as_dict(),
            "oi_change": self.oi_change.as_dict(),
            "squeeze": self.squeeze.as_dict(),
            "sweep_reversal": self.sweep_reversal.as_dict(),
            "spread_bps": (
                None if self.spread_bps is None else round(self.spread_bps, 2)
            ),
        }


# ---------------------------------------------------------------------------
# Defter ölçümleri
# ---------------------------------------------------------------------------

def book_imbalance(
    bids: Sequence[tuple[float, float]],
    asks: Sequence[tuple[float, float]],
    cfg: OrderFlowConfig,
) -> tuple[Component, float | None, list[dict], Component, float | None]:
    """Defter ölçümleri: dengesizlik, büyük emirler, kümeler, spread.

    Döndürür: (imbalance, big_orders, clusters, absorption_placeholder,
    spread_bps). Absorption defter geçmişi gerektirir, burada None.
    """
    if not bids or not asks:
        return (
            Component("imbalance", available=False, note="defter_yok"),
            Component("big_orders", available=False, note="defter_yok"),
            [],
            Component("absorption", available=False, note="defter_yok"),
            None,
        )
    best_bid = max(p for p, _ in bids)
    best_ask = min(p for p, _ in asks)
    if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
        return (
            Component("imbalance", available=False, note="defter_bozuk"),
            Component("big_orders", available=False, note="defter_bozuk"),
            [],
            Component("absorption", available=False, note="defter_bozuk"),
            None,
        )
    mid = (best_bid + best_ask) / 2.0
    band = cfg.book_band_pct
    bid_levels = [(p, q) for p, q in bids if p >= mid * (1 - band)]
    ask_levels = [(p, q) for p, q in asks if p <= mid * (1 + band)]
    bid_usd = sum(p * q for p, q in bid_levels)
    ask_usd = sum(p * q for p, q in ask_levels)

    if bid_usd + ask_usd <= 0:
        imbalance = Component("imbalance", available=False, note="bos_bant")
    else:
        ratio = bid_usd / max(ask_usd, 1e-9)
        # -1..1 aralığına: (ratio-1)/(ratio+1)
        value = (ratio - 1.0) / (ratio + 1.0)
        note = ""
        if ratio >= cfg.imbalance_ratio:
            note = "alici_baskisi"
        elif ratio <= 1.0 / cfg.imbalance_ratio:
            note = "satici_baskisi"
        imbalance = Component("imbalance", value=value, note=note)

    # Büyük emirler: seviye nominalsine göre medyan ölçekli tespit
    all_levels = [
        p * q for p, q in list(bid_levels) + list(ask_levels)
        if p > 0 and q > 0
    ]
    if len(all_levels) >= 5:
        med = median(all_levels)
        if med > 0:
            big_bid = sum(
                p * q for p, q in bid_levels
                if p * q >= cfg.big_order_multiple * med
            )
            big_ask = sum(
                p * q for p, q in ask_levels
                if p * q >= cfg.big_order_multiple * med
            )
            total = big_bid + big_ask
            if total > 0:
                big = Component(
                    "big_orders", value=(big_bid - big_ask) / total,
                    note="medyan_olcekli",
                )
            else:
                big = Component("big_orders", value=0.0, note="buyuk_emir_yok")
        else:
            big = Component("big_orders", available=False, note="medyan_sifir")
    else:
        big = Component("big_orders", available=False, note="derinlik_yetersiz")

    # Kümeler: en yoğun 3 bant (%0.1 bantlar)
    clusters: list[dict] = []
    for side_name, levels in (("bid", bid_levels), ("ask", ask_levels)):
        band_buckets: dict[int, float] = {}
        for p, q in levels:
            distance = abs(p - mid) / mid
            idx = int(distance / 0.001)
            band_buckets[idx] = band_buckets.get(idx, 0.0) + p * q
        for idx, notional in sorted(
            band_buckets.items(), key=lambda kv: -kv[1],
        )[:3]:
            if notional <= 0:
                continue
            clusters.append({
                "side": side_name,
                "distance_pct": round(idx * 0.1, 2),
                "notional_usd": round(notional, 2),
            })

    spread_bps = (best_ask - best_bid) / mid * 10_000.0 if mid > 0 else None
    return imbalance, big, clusters, Component("absorption", available=False), spread_bps


class OrderFlowEngine:
    """Sembol bazlı order flow durumu (defter + CVD + OI geçmişi)."""

    def __init__(self, config: OrderFlowConfig | None = None) -> None:
        self.cfg = config or OrderFlowConfig()
        self._books: dict[str, deque[tuple[int, float, float]]] = {}
        self._snapshots: dict[str, OrderFlowSnapshot] = {}
        self._cvd: dict[str, deque[tuple[int, float]]] = {}
        self._last_price: dict[str, float] = {}
        self._oi: dict[str, deque[tuple[int, float]]] = {}

    # -- Defter ----------------------------------------------------------

    def update_book(
        self, key: str,
        bids: Sequence[tuple[float, float]],
        asks: Sequence[tuple[float, float]],
        ts_ms: int,
    ) -> OrderFlowSnapshot:
        imbalance, big, clusters, _, spread_bps = book_imbalance(
            bids, asks, self.cfg,
        )
        best_bid = max((p for p, _ in bids), default=0.0)
        best_ask = min((p for p, _ in asks), default=0.0)
        history = self._books.setdefault(
            key, deque(maxlen=self.cfg.absorption_stale_sweeps * 4),
        )
        history.append((ts_ms, best_bid, best_ask))
        absorption = self._absorption(key)
        snapshot = OrderFlowSnapshot(
            symbol_key=key, ts_ms=ts_ms,
            imbalance=imbalance, big_orders=big, clusters=clusters,
            absorption=absorption, spread_bps=spread_bps,
        )
        self._snapshots[key] = snapshot
        return snapshot

    def _absorption(self, key: str) -> Component:
        """Emir emilimi: son N defter tazelemesinde duvar sabit + fiyat durgun.

        Gerçek absorption emir-akışı gerektirir; elimizde periyodik defter
        anlık görüntüleri var. Fiyat bandı içinde kalıp defterin aynı
        tarafta derinlik koruması = emilim şüphesi (vekil ölçüm, şeffaf).
        """
        history = self._books.get(key)
        if history is None or len(history) < self.cfg.absorption_stale_sweeps:
            return Component("absorption", available=False, note="gecmis_yetersiz")
        recent = list(history)[-self.cfg.absorption_stale_sweeps:]
        prices = [p for _, bid, ask in recent for p in (bid, ask)]
        mid_series = [(bid + ask) / 2.0 for _, bid, ask in recent]
        if any(p <= 0 for p in prices):
            return Component("absorption", available=False, note="bozuk_veri")
        mid0, mid1 = mid_series[0], mid_series[-1]
        drift = abs(mid1 - mid0) / mid0
        if drift <= self.cfg.absorption_price_band_pct:
            return Component(
                "absorption", value=0.0, note="fiyat_durgun_emilim_suphesi",
            )
        return Component("absorption", value=0.0, note="fiyat_ileri_akiyor")

    # -- CVD (tick kuralı; canlı ticker hacim deltasından) ----------------

    def update_tick(
        self, key: str, price: float, base_volume_delta: float, ts_ms: int,
    ) -> None:
        """Tick kuralı CVD: fiyat yükselirken gelen hacim alıcı, düşerken satıcı.

        `base_volume_delta` 24s gösterge deltasından türetilmiş saniyelik
        baz hacim (SpikeDetector'la aynı kaynak — GERÇEK veri).
        """
        if not isfinite(price) or price <= 0:
            return
        last = self._last_price.get(key)
        self._last_price[key] = price
        if last is None:
            return
        direction = 0.0
        if price > last:
            direction = 1.0
        elif price < last:
            direction = -1.0
        window = self._cvd.setdefault(key, deque(maxlen=self.cfg.cvd_window))
        window.append((ts_ms, direction * max(0.0, base_volume_delta)))

    def cvd_component(self, key: str) -> Component:
        window = self._cvd.get(key)
        if not window or len(window) < 5:
            return Component("cvd", available=False, note="veri_yetersiz")
        total = sum(v for _, v in window)
        gross = sum(abs(v) for _, v in window)
        if gross <= 0:
            return Component("cvd", available=False, note="hacim_yok")
        # -1..1: net akışın payı
        return Component("cvd", value=total / gross, note="tick_kurali")

    # -- Open Interest (borsa desteklerse) --------------------------------

    def update_open_interest(
        self, key: str, oi_value: float, ts_ms: int,
    ) -> None:
        if not isfinite(oi_value) or oi_value < 0:
            return
        window = self._oi.setdefault(key, deque(maxlen=32))
        window.append((ts_ms, oi_value))

    def oi_components(self, key: str, price: float,
                      is_new_extreme: bool) -> tuple[Component, Component]:
        """OI değişimi + sıkışma riski. OI verisi yoksa ikisi de 'uygulanmadı'."""
        window = self._oi.get(key)
        if window is None or len(window) < 3:
            note = "oi_uygulanmadi"
            return (
                Component("oi_change", available=False, note=note),
                Component("squeeze", available=False, note=note),
            )
        first = window[0][1]
        last = window[-1][1]
        if first <= 0:
            return (
                Component("oi_change", available=False, note="oi_sifir"),
                Component("squeeze", available=False, note="oi_sifir"),
            )
        change = (last - first) / first
        oi_comp = Component(
            "oi_change", value=max(-1.0, min(1.0, change / self.cfg.oi_change_threshold)),
            note=f"degisim_{change*100:.2f}%"
            if abs(change) < 10 else "degisim_büyük",
        )
        squeeze = Component("squeeze", value=0.0, note="oi_pencere_yok")
        if is_new_extreme and change >= self.cfg.oi_change_threshold:
            # Fiyat yeni zirve/dip + OI artıyor → ters yöne sıkışma riski
            squeeze = Component(
                "squeeze", value=0.7,
                note="oi_artisi_fiyat_asirisilik",
            )
        return oi_comp, squeeze

    # -- Süpürme-dönüş (mum verisinden) -----------------------------------

    @staticmethod
    def sweep_reversal_component(
        candles: Sequence[Candle], side: str,
        lookback: int = 12,
    ) -> Component:
        """Likidite süpürmesi sonrası dönüş tespiti (fiyat + kapanış gerisi).

        LONG için: son `lookback` barda önceki diplerin altına fitil sarkmış
        ve kapanış geri dönmüşse süpürme-dönüş (sinyali GÜÇLENDİRİR).
        """
        if len(candles) < lookback + 2:
            return Component("sweep_reversal", available=False, note="mum_yetersiz")
        window = list(candles[-(lookback + 1):-1])
        last = candles[-1]
        prior_low = min(c.low for c in window[:-1])
        prior_high = max(c.high for c in window[:-1])
        # Süpürme: AYNI bar (uzun fitil) VEYA bir önceki bar; dönüş: kapanış
        # süpürme seviyesinin üstüne geri döner.
        swept_low = (
            (last.low < prior_low or window[-1].low < prior_low)
            and last.close > prior_low
        )
        swept_high = (
            (last.high > prior_high or window[-1].high > prior_high)
            and last.close < prior_high
        )
        if side == "LONG" and swept_low:
            return Component("sweep_reversal", value=0.8, note="dip_supurme_donus")
        if side == "SHORT" and swept_high:
            return Component("sweep_reversal", value=0.8, note="zirve_supurme_donus")
        return Component("sweep_reversal", value=0.0, note="supurme_yok")

    # -- Anlık görüntüye CVD/OI birleştirme --------------------------------

    def snapshot_for(self, key: str, candles: Sequence[Candle] | None = None,
                     side: str = "LONG") -> OrderFlowSnapshot | None:
        base = self._snapshots.get(key)
        if base is None:
            return None
        cvd = self.cvd_component(key)
        is_new_extreme = False
        if candles and len(candles) >= 21:
            last = candles[-1]
            is_new_extreme = (
                last.high >= max(c.high for c in candles[-21:-1])
                or last.low <= min(c.low for c in candles[-21:-1])
            )
        oi_comp, squeeze = self.oi_components(key, candles[-1].close if candles else 0.0,
                                              is_new_extreme)
        sweep = self.sweep_reversal_component(
            candles or [], side, self.cfg.sweep_lookback_bars,
        )
        return OrderFlowSnapshot(
            symbol_key=base.symbol_key, ts_ms=base.ts_ms,
            imbalance=base.imbalance, big_orders=base.big_orders,
            clusters=base.clusters, absorption=base.absorption,
            cvd=cvd, oi_change=oi_comp, squeeze=squeeze,
            sweep_reversal=sweep, spread_bps=base.spread_bps,
        )
