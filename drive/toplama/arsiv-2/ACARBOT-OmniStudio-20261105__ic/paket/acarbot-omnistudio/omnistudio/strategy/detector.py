"""Sinyal dedektörü — v8→v9.4.5 hattının doğrulanmış mantığı, temiz çekirdek.

KORUNAN DAVRANIŞLAR (arşivden bilinçli devralınır)
  1. İki akış da taze olmalı; bayat fiyat/hacim fail-closed reddedilir.
  2. 2 saniyelik ani hareket + 1 dakikalık/3 dakikalık bağlam birlikte.
  3. hacim oranı vratio3 (3 tam mum / önceki 30 mum medyanı) — geri testle
     birebir eşleşen eşik. Yarım dakika oranı eşik için KULLANILMAZ.
  4. GENİŞLİK KAPISI bağlamdan BAĞIMSIZ ölçülür. (v20'de bulunan sistemsel
     hata: bağlam kapalıyken kapı sessizce devre dışı kalıyordu.)
  5. Dedektör PİYASANIN yönünü döndürür; fade çevirmesi stratejide yapılır.
  6. Isınma (warmup) süresince sinyal üretilmez.

YENİ: genişlik ve fiyat araması `PriceHistory` indeksiyle O(log n).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from ..core.clock import now_ms
from ..core.types import Side, Signal, Tick
from .price_history import PriceHistory


@dataclass
class SymbolState:
    exchange: str
    symbol: str
    prices: PriceHistory = field(default_factory=lambda: PriceHistory(4096))
    volumes: PriceHistory = field(default_factory=lambda: PriceHistory(2048))
    last_price: float = 0.0
    last_price_ms: int = 0
    last_volume_ms: int = 0
    vol_24h_usd: float = 0.0
    minute_id: int = 0
    minute_qv: float = 0.0
    minute_closes: PriceHistory = field(default_factory=lambda: PriceHistory(256))
    minute_volumes: PriceHistory = field(default_factory=lambda: PriceHistory(256))
    speed_short: float = 0.0
    speed_long: float = 0.0
    rvol: float = 0.0
    ret_window: float = 0.0
    ctx_ready: bool = False
    ctx_ret: float = 0.0
    ctx_vratio: float = 0.0
    ctx_vratio3: float = 0.0
    last_signal_ms: int = 0
    cvd: float = 0.0
    buy_quote: float = 0.0
    sell_quote: float = 0.0
    flow_score: float = 0.0
    max_rvol: float = 0.0
    max_ret: float = 0.0
    # Kayan pencere toplamları: O(1) hacim oranı (arşivin "sonraki hedef" işi).
    _vol_short_sum: float = 0.0
    _vol_long_sum: float = 0.0
    _vs_lo: int = 0
    _vs_hi: int = 0
    _vl_lo: int = 0
    _vl_hi: int = 0

    def add_flow(self, tick: Tick) -> None:
        q = tick.quote
        if tick.is_buyer_maker:
            self.sell_quote += q
            self.cvd -= q
        else:
            self.buy_quote += q
            self.cvd += q
        tot = self.buy_quote + self.sell_quote
        self.flow_score = ((self.buy_quote - self.sell_quote) / tot * 100.0) if tot > 0 else 0.0


@dataclass
class DetectorConfig:
    window_ms: int = 2_000
    ret_window_ms: int = 180_000      # 3 dakika
    short_ms: int = 5_000
    long_ms: int = 60_000
    freshness_ms: int = 8_000
    cooldown_ms: int = 60_000
    ret_min_pct: float = 0.35
    rvol_min: float = 2.5
    min_volume_usd: float = 25_000.0
    min_volume_24h_usd: float = 2_000_000.0
    # 1 dakikalık bağlam
    context_enabled: bool = True
    context_lookback_min: int = 3
    context_warmup_min: int = 30
    context_min_ret: float = 0.25
    context_max_ret: float = 6.0
    context_min_vratio: float = 0.0
    context_min_vratio3: float = 1.25
    context_same_direction: bool = True
    # genişlik
    min_breadth_ratio: float = 0.10
    breadth_threshold_pct: float = 0.5
    # eşikler test dışında GEVŞETİLMEZ
    warmup_minutes: int = 3


class SpikeDetector:
    """Ani hareket + bağlam + genişlik dedektörü."""

    def __init__(self, config: DetectorConfig | None = None) -> None:
        self.cfg = config or DetectorConfig()
        self.states: dict[tuple[str, str], SymbolState] = {}
        self.gates: dict[str, int] = {}
        self.breadth: int = 0
        self.breadth_ratio: float = 0.0
        self.breadth_total: int = 0
        self.ticks_seen: int = 0
        self.signals_emitted: int = 0
        self._breadth_cache_ms: int = 0
        self._breadth_cache_ttl_ms: int = 250
        self._eval_calls: int = 0

    # ---------- durum ----------
    def state(self, exchange: str, symbol: str) -> SymbolState:
        key = (exchange, symbol)
        st = self.states.get(key)
        if st is None:
            st = SymbolState(exchange, symbol)
            self.states[key] = st
        return st

    def _gate(self, code: str) -> None:
        self.gates[code] = self.gates.get(code, 0) + 1

    # ---------- besleme ----------
    def feed_tick(self, tick: Tick) -> Signal | None:
        if not (tick.price > 0) or not (tick.qty >= 0):
            self._gate("invalid_tick")
            return None
        self.ticks_seen += 1
        st = self.state(tick.exchange, tick.symbol)
        st.prices.append(tick.ts_ms, tick.price)
        st.volumes.append(tick.ts_ms, tick.quote)
        st.last_price = tick.price
        st.last_price_ms = tick.ts_ms
        # Tick'in kendisi hacim taşır: hacim akışı bu anda TAZEDİR.
        # (Hacimsiz REST-quote fallback tick'leri bunu güncellemez.)
        if tick.quote > 0:
            st.last_volume_ms = tick.ts_ms
        st.add_flow(tick)
        self._update_volume_rate(st, tick.ts_ms)
        return self._evaluate(st, tick.ts_ms)

    def feed_candle_volume(self, exchange: str, symbol: str,
                           quote_volume: float, ts_ms: int,
                           vol_24h_usd: float = 0.0) -> None:
        st = self.state(exchange, symbol)
        st.minute_volumes.append(ts_ms, quote_volume)
        st.last_volume_ms = ts_ms
        if vol_24h_usd > 0:
            st.vol_24h_usd = vol_24h_usd

    def seed_minute_candles(self, exchange: str, symbol: str,
                            candles: list[Any]) -> None:
        """REST ısınması: geçmiş kapanış/hacim yüklenir (canlı sinyal üretmez)."""
        st = self.state(exchange, symbol)
        for c in candles:
            if not getattr(c, "closed", True):
                continue
            st.minute_closes.append(c.open_ms, c.close)
            st.minute_volumes.append(c.open_ms, c.quote_volume)
            # Genişlik hesabının 3 dakikalık geçmişi olsun diye gerçek mum
            # kapanışları fiyat geçmişine de tohumlanır (kapanış anı ile).
            st.prices.append(c.open_ms + 59_999, c.close)
            st.last_price = c.close
            st.last_price_ms = max(st.last_price_ms, c.open_ms + 59_999)
            st.last_volume_ms = max(st.last_volume_ms, c.open_ms + 59_999)
        if candles:
            st.minute_id = candles[-1].open_ms // 60_000
            st.vol_24h_usd = st.vol_24h_usd or sum(
                c.quote_volume for c in candles[-60:]) * 24.0

    def _update_volume_rate(self, st: SymbolState, ts_ms: int) -> None:
        c = self.cfg
        minute = ts_ms // 60_000
        if minute != st.minute_id:
            if st.minute_id:
                st.minute_closes.append(st.minute_id * 60_000, st.last_price)
                st.minute_volumes.append(st.minute_id * 60_000, st.minute_qv)
            st.minute_id = minute
            st.minute_qv = 0.0
        # son tick'in quote hacmini dakikaya ekle
        if st.volumes:
            st.minute_qv += st.volumes[-1][1]

        # O(1) kayan pencere toplamı. Eski sürüm her tick'te tüm geçmişi
        # tarıyordu (arşivin "hacim oranı döngüsü" açık işi). Sırasız zaman
        # damgasında indeks geçersizse eski doğru yola düşer.
        (st._vol_short_sum, st._vs_lo, st._vs_hi) = self._roll_sum(
            st.volumes, ts_ms - c.short_ms, st._vol_short_sum, st._vs_lo, st._vs_hi)
        (st._vol_long_sum, st._vl_lo, st._vl_hi) = self._roll_sum(
            st.volumes, ts_ms - c.long_ms, st._vol_long_sum, st._vl_lo, st._vl_hi)
        if st.volumes.first_at_or_after(ts_ms - c.short_ms) is not None:
            st.speed_short = max(0.0, st._vol_short_sum) / max(1e-9, c.short_ms / 1000.0)
        if st.volumes.first_at_or_after(ts_ms - c.long_ms) is not None:
            st.speed_long = max(0.0, st._vol_long_sum) / max(1e-9, c.long_ms / 1000.0)
        st.rvol = (st.speed_short / st.speed_long) if st.speed_long > 0 else 0.0

        p = st.prices.first_at_or_after(ts_ms - c.ret_window_ms)
        if p is not None and p[1] > 0 and ts_ms - p[0] >= c.ret_window_ms * 0.8:
            st.ret_window = (st.last_price / p[1] - 1.0) * 100.0
        else:
            st.ret_window = 0.0

    @staticmethod
    def _roll_sum(hist: PriceHistory, cutoff: float, total: float,
                  lo: int, hi: int) -> tuple[float, int, int]:
        """Pencere hacim toplamını amortize O(1) kayan imleçle sürdürür.

        Mutlak ekleme koordinatı kullanılır; tampon kayması imleci bozmaz.
        İki ön koşul: azalmayan zaman damgası VE azalmayan cutoff. Cutoff
        geriye giderse (farklı pencere/geriye zaman) imleç yeniden hizalanır.
        Ön koşullar yoksa tam taramaya düşülür — doğruluk korunur.
        """
        if not hist.monotonic or not hist.stats()["index_valid"]:
            return sum(q for t, q in hist if t >= cutoff), 0, 0
        seq = hist.seq
        base = seq - len(hist)
        # lo, pencere içindeki ilk öğenin mutlak indexi. Yeni cutoff eski
        # pencere başından DAHA ESKİYİ işaret ediyorsa geriye gidemeyiz:
        # bu durumda baştan hesapla.
        needs_reset = (lo < base or hi < base or hi > seq or lo > hi)
        if not needs_reset and lo > base:
            # pencere başının bir öncesi hâlâ tamponda mı ve cutoff'a göre dışarıda mı?
            if hist[lo - base - 1][0] >= cutoff:
                needs_reset = True
        if needs_reset:
            total, lo, hi = 0.0, base, base
        while hi < seq:
            total += hist[hi - base][1]
            hi += 1
        while lo < hi and hist[lo - base][0] < cutoff:
            total -= hist[lo - base][1]
            lo += 1
        return total, lo, hi

    # ---------- bağlam ----------
    def _update_context(self, st: SymbolState, ts_ms: int) -> bool:
        c = self.cfg
        st.ctx_ready = False
        closes = st.minute_closes.items()
        vols = st.minute_volumes.items()
        if len(closes) < c.context_lookback_min + 1:
            return False
        if len(vols) < c.context_warmup_min:
            return False
        st.ctx_vratio3 = 0.0
        if c.context_min_vratio3 and len(vols) < 3 + c.context_warmup_min:
            return False
        past_close = closes[-c.context_lookback_min][1]
        if past_close <= 0 or st.last_price <= 0:
            return False
        st.ctx_ret = (st.last_price - past_close) / past_close * 100.0

        recent = [q for _, q in vols[-c.context_warmup_min:]]
        med = statistics.median(recent) if recent else 0.0
        if med <= 0:
            return False
        elapsed_min = (ts_ms - st.minute_id * 60_000) / 60_000.0
        elapsed_min = min(max(elapsed_min, 1.0 / 6.0), 1.0)
        st.ctx_vratio = (st.minute_qv / elapsed_min) / med

        if len(vols) >= 3 + c.context_warmup_min:
            last3 = sum(q for _, q in vols[-3:])
            base = [q for _, q in vols[-(3 + c.context_warmup_min):-3]]
            med3 = statistics.median(base) if base else 0.0
            if med3 > 0:
                st.ctx_vratio3 = last3 / (med3 * 3.0)
        st.ctx_ready = True
        return True

    # ---------- genişlik ----------
    def update_breadth(self, ts_ms: int | None = None, force: bool = False) -> float:
        """Piyasa genişliği — bağlamdan BAĞIMSIZ, indeksli arama ile.

        v20 düzeltmesi korunur: `ctx_ready` şartı YOK. Aksi halde bağlam
        kapalıyken kapı sessizce devre dışı kalır.
        """
        ts_ms = ts_ms if ts_ms is not None else now_ms()
        if (not force and self._breadth_cache_ms
                and ts_ms - self._breadth_cache_ms < self._breadth_cache_ttl_ms):
            return self.breadth_ratio
        c = self.cfg
        total = moving = 0
        for st in self.states.values():
            last = st.prices.last
            if last is None:
                continue
            ts_last, p_last = last
            old = st.prices.first_at_or_after(ts_last - c.ret_window_ms)
            if old is None:
                continue
            if ts_last - old[0] < c.ret_window_ms * 0.8:
                continue
            if old[1] <= 0:
                continue
            total += 1
            if abs((p_last / old[1] - 1.0) * 100.0) + 1e-9 >= c.breadth_threshold_pct:
                moving += 1
        self.breadth = moving
        self.breadth_total = total
        self.breadth_ratio = (moving / total) if total else 0.0
        self._breadth_cache_ms = ts_ms
        return self.breadth_ratio

    # ---------- karar ----------
    def _evaluate(self, st: SymbolState, ts_ms: int) -> Signal | None:
        c = self.cfg
        self._eval_calls += 1
        if ts_ms - st.last_price_ms > c.freshness_ms:
            self._gate("stale_price"); return None
        vol_fresh = max(c.freshness_ms, 15_000)
        if not st.last_volume_ms or ts_ms - st.last_volume_ms > vol_fresh:
            self._gate("stale_volume"); return None
        if not st.speed_long:
            self._gate("volume_rate_not_ready"); return None

        ret = st.ret_window
        rvol = st.rvol
        vol_usd = st.speed_short * (c.short_ms / 1000.0)
        st.max_rvol = max(st.max_rvol, rvol)
        st.max_ret = max(st.max_ret, abs(ret))

        if abs(ret) < c.ret_min_pct:
            self._gate("ret_threshold"); return None
        if rvol < c.rvol_min:
            self._gate("rvol_threshold"); return None
        if vol_usd < c.min_volume_usd:
            self._gate("volume_threshold"); return None
        if c.min_volume_24h_usd and st.vol_24h_usd < c.min_volume_24h_usd:
            self._gate("volume24h_threshold"); return None
        if ts_ms - st.last_signal_ms < c.cooldown_ms:
            self._gate("cooldown"); return None

        direction = 1.0 if ret > 0 else -1.0
        if c.context_enabled:
            if not self._update_context(st, ts_ms):
                self._gate("context_warmup"); return None
            if abs(st.ctx_ret) < c.context_min_ret:
                self._gate("context_ret_low"); return None
            if c.context_max_ret and abs(st.ctx_ret) > c.context_max_ret:
                self._gate("context_ret_high"); return None
            if c.context_min_vratio and st.ctx_vratio < c.context_min_vratio:
                self._gate("context_vratio"); return None
            if c.context_min_vratio3 and st.ctx_vratio3 < c.context_min_vratio3:
                self._gate("context_vratio3"); return None
            if c.context_same_direction and (st.ctx_ret > 0) != (direction > 0):
                self._gate("context_direction_conflict"); return None
            direction = 1.0 if st.ctx_ret > 0 else -1.0

        # GENİŞLİK: bağlam bloğunun DIŞINDA (v20 sistemsel hata düzeltmesi)
        if c.min_breadth_ratio > 0:
            ratio = self.update_breadth(ts_ms)
            if ratio < c.min_breadth_ratio:
                self._gate("breadth"); return None

        self._gate("signal_emitted")
        st.last_signal_ms = ts_ms
        self.signals_emitted += 1
        side = Side.LONG if direction > 0 else Side.SHORT
        return Signal(
            exchange=st.exchange, symbol=st.symbol, side=side,
            price=st.last_price, ts_ms=ts_ms, ret_pct=round(ret, 4),
            rvol=round(rvol, 3), volume_usd=round(vol_usd, 2),
            window_ms=c.ret_window_ms,
            ctx_ret=round(st.ctx_ret, 4), ctx_vratio=round(st.ctx_vratio, 3),
            ctx_vratio3=round(st.ctx_vratio3, 3),
            breadth_ratio=round(self.breadth_ratio, 4),
            flow_score=round(st.flow_score, 3),
            tag="ANI_YUKSELIS" if side is Side.LONG else "ANI_DUSUS",
            signal_id=f"{st.exchange}:{st.symbol}:{ts_ms}",
        )

    # ---------- özet ----------
    def summary(self) -> dict[str, Any]:
        return {
            "symbols": len(self.states), "ticks_seen": self.ticks_seen,
            "evaluation_calls": self._eval_calls,
            "signals_emitted": self.signals_emitted,
            "breadth_moving": self.breadth, "breadth_total": self.breadth_total,
            "breadth_ratio": round(self.breadth_ratio, 4),
            "gates": dict(sorted(self.gates.items(), key=lambda kv: -kv[1])),
            "index_stats": {
                "invalid_indexes": sum(1 for s in self.states.values()
                                       if not s.prices.stats()["index_valid"]),
                "total_rebuilds": sum(s.prices.stats()["rebuilds"]
                                      for s in self.states.values()),
            },
        }