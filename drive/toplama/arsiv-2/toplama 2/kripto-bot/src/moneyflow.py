"""Gerçek para giriş/çıkış + 20 Kademe Emir Defteri Derinlik Analizi (Order Book Depth Imbalance)
+ Açık Faiz (OI) + Likidasyon (Squeeze) analizi.

Ölçülen gerçek veriler:
  - Agresif ALIŞ vs SATIŞ hacmi (taker tarafı) → para girişi/çıkışı
  - CVD (Kümülatif Hacim Deltası) ve eğimi
  - BALİNA işlemler: tek seferde >= eşik (örn. $100K) tutarındaki işlemler
  - Hacim patlaması: son akış / tarihsel ortalama
  - 20 KADEME EMİR DEFTERİ DERİNLİK ANALİZİ (Order Book 20-Level Depth Imbalance):
    • İlk 20 kademedeki toplam Alıcı (Bid) ve Satıcı (Ask) duvarlarının USDT hacmi
    • Alıcı / Satıcı Hacim Oranı (`bid_ask_ratio = Bid_20 / Ask_20`)
    • Mesafe Ağırlıklı Derinlik Dengesizliği (`weighted_obi`) ve Ham OBI (`obi`)
    • En büyük Alıcı Duvarı (`bid_wall_usdt`) ve Satıcı Duvarı (`ask_wall_usdt`) tespiti
  - AÇIK FAİZ (Open Interest - OI) değişimi: vadeli piyasadaki toplam kontrat artışı/azalışı
  - LİKİDASYON (Tasfiye) takibi: zorunlu kapanan Long/Short pozisyonlar ve
    LONG SQUEEZE / SHORT SQUEEZE patlama tespiti!

Çıktı: -100 (güçlü ÇIKIŞ/baskı) .. +100 (güçlü GİRİŞ/talep)
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class WhaleTrade:
    ts: float
    symbol: str
    side: str      # "BUY" (agresif alış = para girişi) / "SELL"
    price: float
    notional_usdt: float


@dataclass
class LiquidationEvent:
    ts: float
    symbol: str
    liq_type: str  # "SHORT_LIQ" (short tasfiyesi = zorunlu alış) | "LONG_LIQ" (long tasfiyesi = zorunlu satış)
    price: float
    notional_usdt: float


class MoneyFlow:
    def __init__(
        self,
        symbol: str,
        whale_usdt: float = 100_000,
        window_sec: int = 300,
        spike_mult: float = 2.5,
        liq_squeeze_usdt: float = 50_000,
        book_depth_levels: int = 20,
    ):
        self.symbol = symbol
        self.whale_usdt = whale_usdt
        self.window_sec = window_sec
        self.spike_mult = spike_mult
        self.liq_squeeze_usdt = liq_squeeze_usdt
        self.book_depth_levels = book_depth_levels

        self._trades: deque[tuple[float, float, float]] = deque(maxlen=20000)
        # (ts, signed_notional(+alış/-satış), notional)
        self._cvd = 0.0
        self._cvd_hist: deque[tuple[float, float]] = deque(maxlen=2000)
        self.whales: deque[WhaleTrade] = deque(maxlen=200)
        self._vol_hist: deque[tuple[float, float]] = deque(maxlen=2000)

        # 20 Kademe Emir Defteri Derinlik (Order Book Depth Imbalance) Durumu
        self.obi = 0.0                # -1..+1 ham 20 kademe dengesizliği
        self.weighted_obi = 0.0       # -1..+1 kademe mesafesi ağırlıklı dengesizlik
        self.bid_ask_ratio = 1.0      # Alıcı / Satıcı duvarı hacim oranı (Bid/Ask Ratio)
        self.bid_depth_usdt = 0.0     # İlk 20 kademe toplam Alıcı (Bid) hacmi ($)
        self.ask_depth_usdt = 0.0     # İlk 20 kademe toplam Satıcı (Ask) hacmi ($)
        self.bid_wall_price = 0.0     # En büyük Alıcı duvarı fiyatı
        self.bid_wall_usdt = 0.0      # En büyük Alıcı duvarı büyüklüğü ($)
        self.ask_wall_price = 0.0     # En büyük Satıcı duvarı fiyatı
        self.ask_wall_usdt = 0.0      # En büyük Satıcı duvarı büyüklüğü ($)
        self.book_levels_count = 0    # Analiz edilen kademe sayısı (maks 20)
        self.wall_signal = "DENGELI"  # ALICI_DUVARI | SATICI_DUVARI | DENGELI

        # Açık Faiz (Open Interest) ve Likidasyon geçmişi
        self._oi_hist: deque[tuple[float, float, float]] = deque(maxlen=500)
        # (ts, oi_value, price)
        self.liquidations: deque[LiquidationEvent] = deque(maxlen=500)
        self._last_price: float = 0.0

    # -- veri girişi ------------------------------------------------------
    def add_trade(
        self, price: float, qty: float, is_buyer_maker: bool, ts: float | None = None
    ) -> WhaleTrade | None:
        """Binance aggTrade / OKX trade akışından çağrılır.

        is_buyer_maker=True → satıcı agresifti (para ÇIKIŞI), aksi halde giriş.
        """
        ts = ts or time.time()
        self._last_price = price
        notional = price * qty
        signed = -notional if is_buyer_maker else notional
        self._trades.append((ts, signed, notional))
        self._vol_hist.append((ts, notional))
        self._cvd += signed
        self._cvd_hist.append((ts, self._cvd))
        self._prune(ts)
        if notional >= self.whale_usdt:
            w = WhaleTrade(
                ts, self.symbol, "SELL" if is_buyer_maker else "BUY", price, notional
            )
            self.whales.append(w)
            return w
        return None

    def update_book(self, bids: list, asks: list, depth: int = 20) -> dict:
        """20 Kademe Emir Defteri Derinlik Analizi (Order Book Depth Imbalance).

        İlk 20 kademedeki alıcı (Bid) ve satıcı (Ask) duvarlarının toplam hacmini,
        `Bid/Ask Ratio` oranını, kademe ağırlıklı dengesizliği (`weighted_obi`) ve
        en güçlü alım/satım duvarlarını hesaplar.
        """
        try:
            max_lvl = max(1, int(depth or self.book_depth_levels or 20))
            b_slice = bids[:max_lvl] if bids else []
            a_slice = asks[:max_lvl] if asks else []

            bid_v = 0.0
            ask_v = 0.0
            w_bid_v = 0.0
            w_ask_v = 0.0
            max_bid_usdt = 0.0
            max_bid_px = 0.0
            max_ask_usdt = 0.0
            max_ask_px = 0.0

            for idx, row in enumerate(b_slice):
                p, q = float(row[0]), float(row[1])
                usdt = p * q
                w = math.exp(-0.12 * idx)  # Fiyata yakın kademeler daha yüksek ağırlıklı
                bid_v += usdt
                w_bid_v += usdt * w
                if usdt > max_bid_usdt:
                    max_bid_usdt = usdt
                    max_bid_px = p

            for idx, row in enumerate(a_slice):
                p, q = float(row[0]), float(row[1])
                usdt = p * q
                w = math.exp(-0.12 * idx)
                ask_v += usdt
                w_ask_v += usdt * w
                if usdt > max_ask_usdt:
                    max_ask_usdt = usdt
                    max_ask_px = p

            tot = bid_v + ask_v
            w_tot = w_bid_v + w_ask_v

            self.bid_depth_usdt = round(bid_v, 2)
            self.ask_depth_usdt = round(ask_v, 2)
            self.obi = (bid_v - ask_v) / tot if tot > 0 else 0.0
            self.weighted_obi = (w_bid_v - w_ask_v) / w_tot if w_tot > 0 else 0.0
            if ask_v > 0:
                self.bid_ask_ratio = round(bid_v / ask_v, 3)
            elif bid_v > 0:
                self.bid_ask_ratio = 10.0
            else:
                self.bid_ask_ratio = 1.0

            self.bid_wall_price = round(max_bid_px, 4)
            self.bid_wall_usdt = round(max_bid_usdt, 2)
            self.ask_wall_price = round(max_ask_px, 4)
            self.ask_wall_usdt = round(max_ask_usdt, 2)
            self.book_levels_count = max(len(b_slice), len(a_slice))

            if self.bid_ask_ratio >= 1.45 or self.weighted_obi >= 0.18:
                self.wall_signal = "ALICI_DUVARI"
            elif self.bid_ask_ratio <= 0.69 or self.weighted_obi <= -0.18:
                self.wall_signal = "SATICI_DUVARI"
            else:
                self.wall_signal = "DENGELI"
        except Exception:
            pass
        return self.depth_snapshot()

    def depth_snapshot(self) -> dict:
        """20 kademe emir defteri derinlik metriklerini ve skor katkısını döner."""
        # Bid/Ask Ratio logaritmik katkısı (-1 .. +1 aralığına normalize)
        ratio_clamped = max(0.2, min(5.0, self.bid_ask_ratio))
        ratio_norm = math.log(ratio_clamped) / math.log(5.0)  # 5x oranda +1.0, 0.2x oranda -1.0
        # 20 kademe derinlik skor katkısı (-25 .. +25 puan)
        depth_boost = (
            self.weighted_obi * 14.0
            + self.obi * 5.0
            + ratio_norm * 6.0
        )
        depth_boost = max(-25.0, min(25.0, depth_boost))
        return {
            "obi": round(self.obi, 3),
            "weighted_obi": round(self.weighted_obi, 3),
            "bid_ask_ratio": round(self.bid_ask_ratio, 3),
            "bid_depth_usdt": round(self.bid_depth_usdt, 2),
            "ask_depth_usdt": round(self.ask_depth_usdt, 2),
            "bid_wall_price": self.bid_wall_price,
            "bid_wall_usdt": self.bid_wall_usdt,
            "ask_wall_price": self.ask_wall_price,
            "ask_wall_usdt": self.ask_wall_usdt,
            "book_levels": self.book_levels_count,
            "wall_signal": self.wall_signal,
            "depth_score_boost": round(depth_boost, 2),
        }

    def update_open_interest(
        self, oi_value: float, price: float | None = None, ts: float | None = None
    ):
        """Vadeli işlemler Açık Faiz (Open Interest) verisini günceller."""
        ts = ts or time.time()
        px = price if price is not None else self._last_price
        if oi_value > 0:
            self._oi_hist.append((ts, float(oi_value), float(px or 0.0)))
            self._prune(ts)

    def add_liquidation(
        self, side: str, price: float, qty: float, ts: float | None = None
    ) -> LiquidationEvent:
        """Vadeli işlem tasfiye (likidasyon) akışından çağrılır.

        side:
          - 'BUY' veya 'SHORT_LIQ' → Short pozisyon tasfiye oldu (zorunlu piyasa alışı = SHORT SQUEEZE yakıtı)
          - 'SELL' veya 'LONG_LIQ' → Long pozisyon tasfiye oldu (zorunlu piyasa satışı = LONG SQUEEZE yakıtı)
        """
        ts = ts or time.time()
        notional = float(price) * float(qty)
        s_up = side.upper()
        if s_up in ("BUY", "SHORT_LIQ", "SHORT"):
            liq_type = "SHORT_LIQ"
        else:
            liq_type = "LONG_LIQ"
        ev = LiquidationEvent(ts, self.symbol, liq_type, float(price), notional)
        self.liquidations.append(ev)
        self._prune(ts)
        return ev

    def _prune(self, now: float):
        cutoff = now - self.window_sec
        while self._trades and self._trades[0][0] < cutoff:
            self._trades.popleft()
        while self._vol_hist and self._vol_hist[0][0] < cutoff * 4:
            self._vol_hist.popleft()
        while self._cvd_hist and self._cvd_hist[0][0] < cutoff:
            self._cvd_hist.popleft()
        while self._oi_hist and self._oi_hist[0][0] < cutoff * 2 and len(self._oi_hist) > 2:
            self._oi_hist.popleft()
        while self.liquidations and self.liquidations[0].ts < cutoff:
            self.liquidations.popleft()

    # -- Açık Faiz & Squeeze Analizi -----------------------------------------
    def _oi_and_squeeze(self, now: float, delta_ratio: float) -> dict:
        cutoff = now - self.window_sec
        short_liq = sum(
            e.notional_usdt
            for e in self.liquidations
            if e.ts >= cutoff and e.liq_type == "SHORT_LIQ"
        )
        long_liq = sum(
            e.notional_usdt
            for e in self.liquidations
            if e.ts >= cutoff and e.liq_type == "LONG_LIQ"
        )

        oi_now = self._oi_hist[-1][1] if self._oi_hist else 0.0
        oi_change_pct = 0.0
        price_change_pct = 0.0
        if len(self._oi_hist) >= 2:
            oi_start = self._oi_hist[0][1]
            px_start = self._oi_hist[0][2]
            px_end = self._oi_hist[-1][2]
            if oi_start > 0:
                oi_change_pct = (oi_now - oi_start) / oi_start * 100.0
            if px_start > 0 and px_end > 0:
                price_change_pct = (px_end - px_start) / px_start * 100.0

        # Squeeze tespiti
        squeeze = "YOK"
        squeeze_boost = 0.0

        # 1) SHORT SQUEEZE: Yüklü short tasfiyesi + pozitif fiyat/alış baskısı
        if short_liq >= self.liq_squeeze_usdt and short_liq > long_liq * 1.5:
            if delta_ratio >= -0.1 or price_change_pct >= 0:
                squeeze = "SHORT_SQUEEZE"
                intensity = min(1.0, short_liq / max(self.liq_squeeze_usdt * 3, 1.0))
                squeeze_boost = 15.0 + 10.0 * intensity  # +15 .. +25 puan
        # 2) LONG SQUEEZE: Yüklü long tasfiyesi + negatif fiyat/satış baskısı
        elif long_liq >= self.liq_squeeze_usdt and long_liq > short_liq * 1.5:
            if delta_ratio <= 0.1 or price_change_pct <= 0:
                squeeze = "LONG_SQUEEZE"
                intensity = min(1.0, long_liq / max(self.liq_squeeze_usdt * 3, 1.0))
                squeeze_boost = -(15.0 + 10.0 * intensity)  # -15 .. -25 puan

        # OI + Fiyat uyum sinyali
        oi_signal = "NOTR"
        oi_boost = 0.0
        if abs(oi_change_pct) >= 0.5:
            bullish_flow = price_change_pct > 0 or delta_ratio > 0.15
            bearish_flow = price_change_pct < 0 or delta_ratio < -0.15
            if oi_change_pct > 0.5 and bullish_flow:
                oi_signal = "YENI_LONG_GIRISI"
                oi_boost = min(10.0, oi_change_pct * 2.5)
            elif oi_change_pct > 0.5 and bearish_flow:
                oi_signal = "YENI_SHORT_GIRISI"
                oi_boost = -min(10.0, oi_change_pct * 2.5)
            elif oi_change_pct < -1.0 and bullish_flow and squeeze == "YOK":
                oi_signal = "SHORT_KAPAMA_RALLISI"
                if squeeze == "YOK" and abs(oi_change_pct) >= 2.0:
                    squeeze = "SHORT_SQUEEZE"
                oi_boost = 8.0
            elif oi_change_pct < -1.0 and bearish_flow and squeeze == "YOK":
                oi_signal = "LONG_TASFIYE_DUSUSU"
                if squeeze == "YOK" and abs(oi_change_pct) >= 2.0:
                    squeeze = "LONG_SQUEEZE"
                oi_boost = -8.0

        return {
            "open_interest": round(oi_now, 2),
            "oi_change_pct": round(oi_change_pct, 2),
            "oi_signal": oi_signal,
            "short_liq_usdt": round(short_liq, 1),
            "long_liq_usdt": round(long_liq, 1),
            "squeeze": squeeze,
            "oi_liq_boost": round(squeeze_boost + oi_boost, 1),
        }

    # -- skor ---------------------------------------------------------------
    def snapshot(self) -> dict:
        now = time.time()
        self._prune(now)
        buy_v = sum(n for _, s, n in self._trades if s > 0)
        sell_v = sum(n for _, s, n in self._trades if s < 0)
        tot = buy_v + sell_v
        delta_ratio = (buy_v - sell_v) / tot if tot > 0 else 0.0

        # CVD eğimi (pencere başı vs sonu)
        cvd_slope = 0.0
        if len(self._cvd_hist) >= 2:
            cvd_slope = self._cvd_hist[-1][1] - self._cvd_hist[0][1]

        # Balina dengesi (son pencerede)
        cutoff = now - self.window_sec
        w_buy = sum(
            w.notional_usdt for w in self.whales if w.ts >= cutoff and w.side == "BUY"
        )
        w_sell = sum(
            w.notional_usdt for w in self.whales if w.ts >= cutoff and w.side == "SELL"
        )
        w_tot = w_buy + w_sell
        whale_ratio = (w_buy - w_sell) / w_tot if w_tot > 0 else 0.0

        # Hacim patlaması: son 60 sn hızı vs 20 dk ortalaması
        recent = sum(n for t, n in self._vol_hist if t >= now - 60)
        older = [n for t, n in self._vol_hist if t < now - 60]
        avg_rate = (sum(older) / max(1, len(older))) if older else 0.0
        spike = (recent / max(1, avg_rate * 60)) if avg_rate > 0 else 0.0
        spike = min(spike, 10.0)
        volume_spike = spike >= self.spike_mult

        # Açık Faiz (OI) ve Likidasyon Squeeze analizi
        oi_info = self._oi_and_squeeze(now, delta_ratio)
        # 20 Kademe Emir Defteri Derinlik Analizi (Bid/Ask Ratio + Weighted OBI)
        depth_info = self.depth_snapshot()

        # Skor birleşimi: Taker Delta + CVD + Balina + 20 Kademe Derinlik (Bid/Ask Ratio) + OI/Squeeze
        score = (
            delta_ratio * 42
            + (1 if cvd_slope > 0 else (-1 if cvd_slope < 0 else 0)) * 14
            + whale_ratio * 24
            + depth_info["depth_score_boost"]
            + oi_info["oi_liq_boost"]
        )
        # Hacim patlaması yönü güçlendirir
        if volume_spike and tot > 0:
            score += 8 if delta_ratio > 0 else -8
        score = max(-100, min(100, score))

        return {
            "score": round(score, 1),
            "buy_usdt": round(buy_v, 1),
            "sell_usdt": round(sell_v, 1),
            "net_usdt": round(buy_v - sell_v, 1),
            "cvd": round(self._cvd, 1),
            "cvd_slope": round(cvd_slope, 1),
            "whale_buy_usdt": round(w_buy, 1),
            "whale_sell_usdt": round(w_sell, 1),
            "volume_spike": volume_spike,
            "spike_mult": round(spike, 2),
            **depth_info,
            **oi_info,
            "verdict": (
                "GÜÇLÜ GİRİŞ"
                if score >= 40
                else "GİRİŞ"
                if score >= 15
                else "GÜÇLÜ ÇIKIŞ"
                if score <= -40
                else "ÇIKIŞ"
                if score <= -15
                else "DENGELİ"
            ),
        }
