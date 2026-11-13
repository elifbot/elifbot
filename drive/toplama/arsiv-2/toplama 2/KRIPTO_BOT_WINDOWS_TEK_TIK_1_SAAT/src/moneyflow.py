"""Para Akışı, Emir Defteri Derinliği, CVD Divergence, Absorption, OI/Squeeze ve Tick VPVR.

Ölçülen gerçek veriler:
  - Agresif ALIŞ vs SATIŞ hacmi (taker tarafı) → para girişi/çıkışı
  - CVD (Kümülatif Hacim Deltası), eğimi ve fiyat/CVD divergence
  - Agresif hacim + fiyat tutunması + defter derinliğiyle absorption
  - Gerçek trade fiyatı/hacmiyle bounded tick VPVR (POC/VAH/VAL)
  - BALİNA işlemler: tek seferde >= eşik (örn. $100K) tutarındaki işlemler
  - Hacim patlaması: son akış / tarihsel ortalama
  - 20 KADEME EMİR DEFTERİ DERİNLİK ANALİZİ (Order Book 20-Level Depth Imbalance):
      * Bid/Ask Ratio, ağırlıklı OBI ve Alıcı/Satıcı Duvarı tespiti
  - Açık Faiz (Open Interest) + Likidasyon (Short/Long Squeeze) analizi
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass


@dataclass
class WhaleTrade:
    ts: float
    symbol: str
    side: str
    price: float
    qty: float
    notional_usdt: float


@dataclass
class LiquidationEvent:
    ts: float
    symbol: str
    side: str
    price: float
    qty: float
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
        divergence_min_price_pct: float = 0.05,
        absorption_min_usdt: float = 25_000,
        absorption_ratio: float = 1.5,
        vpvr_window_sec: int = 21_600,
        vpvr_bins: int = 48,
        compact_history: bool = False,
    ):
        self.symbol = symbol
        self.whale_usdt = float(whale_usdt)
        self.window_sec = int(window_sec)
        self.spike_mult = float(spike_mult)
        self.liq_squeeze_usdt = float(liq_squeeze_usdt)
        self.book_depth_levels = max(1, int(book_depth_levels))
        self.divergence_min_price_pct = float(divergence_min_price_pct)
        self.absorption_min_usdt = float(absorption_min_usdt)
        self.absorption_ratio = float(absorption_ratio)
        self.vpvr_window_sec = int(vpvr_window_sec)
        self.vpvr_bins = max(8, int(vpvr_bins))

        trade_limit = 2_000 if compact_history else 20_000
        vpvr_limit = 5_000 if compact_history else 100_000
        book_limit = 200 if compact_history else 1_000
        self._trades: deque[tuple[float, float, float]] = deque(maxlen=trade_limit)
        # (ts, signed_notional(+alış/-satış), notional)
        self._cvd = 0.0
        self._cvd_hist: deque[tuple[float, float, float]] = deque(maxlen=trade_limit)
        # (ts, cvd, gerçekleşme fiyatı)
        self._book_hist: deque[tuple[float, float, float]] = deque(maxlen=book_limit)
        self._vpvr_trades: deque[tuple[float, float, float]] = deque(maxlen=vpvr_limit)
        # (ts, gerçekleşme fiyatı, gerçekleşme notionalı) — OHLCV yaklaşımı değildir.
        self.whales: deque[WhaleTrade] = deque(maxlen=200)
        self._vol_hist: deque[tuple[float, float]] = deque(
            maxlen=500 if compact_history else 2_000
        )

        # 20 Kademe Emir Defteri Derinlik (Order Book Depth Imbalance) Durumu
        self.obi = 0.0                # -1..+1 ham 20 kademe dengesizliği
        self.weighted_obi = 0.0       # -1..+1 fiyata yakın kademe ağırlıklı dengesizlik
        self.bid_depth_usdt = 0.0
        self.ask_depth_usdt = 0.0
        self.bid_ask_ratio = 1.0
        self.book_levels = 0
        self.wall_signal = "DENGELI"  # ALICI_DUVARI | SATICI_DUVARI | DENGELI

        # Açık Faiz (Open Interest) ve Likidasyon geçmişi
        event_limit = 100 if compact_history else 500
        self._oi_hist: deque[tuple[float, float, float]] = deque(maxlen=event_limit)
        # (ts, oi_value, price)
        self.liquidations: deque[LiquidationEvent] = deque(maxlen=event_limit)
        self._last_price: float = 0.0

    # -- veri girişi ------------------------------------------------------
    def add_trade(
        self,
        price: float,
        qty: float,
        is_buyer_maker: bool,
        ts: float | None = None,
    ) -> WhaleTrade | None:
        ts = float(ts if ts is not None else time.time())
        price = float(price)
        qty = float(qty)
        if price <= 0 or qty <= 0:
            return None
        self._last_price = price
        notional = price * qty
        signed = -notional if is_buyer_maker else notional
        self._trades.append((ts, signed, notional))
        self._vol_hist.append((ts, notional))
        self._vpvr_trades.append((ts, float(price), float(notional)))
        self._cvd += signed
        self._cvd_hist.append((ts, self._cvd, float(price)))
        self._prune(ts)
        if notional >= self.whale_usdt:
            w = WhaleTrade(
                ts=ts,
                symbol=self.symbol,
                side="SATIŞ" if is_buyer_maker else "ALIŞ",
                price=price,
                qty=qty,
                notional_usdt=notional,
            )
            self.whales.append(w)
            return w
        return None

    def update_book(
        self, bids: list, asks: list, depth: int = 20, ts: float | None = None
    ) -> dict:
        """20 Kademe Emir Defteri Derinlik Analizi (Order Book Depth Imbalance).

        İlk 20 kademedeki alıcı (Bid) ve satıcı (Ask) duvarlarının toplam hacmini,
        Bid/Ask oranını ve kademe yakınlık ağırlıklı OBI skorunu hesaplar.
        """
        lvl = max(1, min(int(depth), self.book_depth_levels))
        try:
            bid_levels = [(float(p), float(q)) for p, q in (bids or [])[:lvl] if float(p) > 0 and float(q) >= 0]
            ask_levels = [(float(p), float(q)) for p, q in (asks or [])[:lvl] if float(p) > 0 and float(q) >= 0]
            bid_v = sum(p * q for p, q in bid_levels)
            ask_v = sum(p * q for p, q in ask_levels)
            tot_v = bid_v + ask_v

            w_bid = sum((p * q) / (i + 1) for i, (p, q) in enumerate(bid_levels))
            w_ask = sum((p * q) / (i + 1) for i, (p, q) in enumerate(ask_levels))
            w_tot = w_bid + w_ask

            self.bid_depth_usdt = bid_v
            self.ask_depth_usdt = ask_v
            self.book_levels = min(len(bid_levels), len(ask_levels))
            self.obi = (bid_v - ask_v) / tot_v if tot_v > 0 else 0.0
            self.weighted_obi = (w_bid - w_ask) / w_tot if w_tot > 0 else 0.0
            self.bid_ask_ratio = (bid_v / ask_v) if ask_v > 0 else (2.0 if bid_v > 0 else 1.0)

            if self.bid_ask_ratio >= 1.65:
                self.wall_signal = "ALICI_DUVARI"
            elif self.bid_ask_ratio <= 0.60:
                self.wall_signal = "SATICI_DUVARI"
            else:
                self.wall_signal = "DENGELI"
            self._book_hist.append((float(ts or time.time()), bid_v, ask_v))
        except Exception:
            pass
        return self.depth_snapshot()

    def depth_snapshot(self) -> dict:
        blend = 0.55 * self.weighted_obi + 0.45 * self.obi
        boost = max(-20.0, min(20.0, blend * 22.0))
        return {
            "obi": round(self.obi, 4),
            "weighted_obi": round(self.weighted_obi, 4),
            "bid_depth_usdt": round(self.bid_depth_usdt, 1),
            "ask_depth_usdt": round(self.ask_depth_usdt, 1),
            "bid_ask_ratio": round(self.bid_ask_ratio, 3),
            "book_levels": int(self.book_levels),
            "wall_signal": self.wall_signal,
            "depth_score_boost": round(boost, 2),
        }

    def update_open_interest(
        self, oi_value: float, price: float | None = None, ts: float | None = None
    ) -> None:
        if oi_value is None or float(oi_value) <= 0:
            return
        now = float(ts if ts is not None else time.time())
        px = float(price if price is not None and price > 0 else self._last_price)
        if px > 0:
            self._last_price = px
        self._oi_hist.append((now, float(oi_value), px))
        self._prune(now)

    def add_liquidation(
        self,
        side: str,
        price: float,
        qty: float,
        ts: float | None = None,
    ) -> LiquidationEvent:
        now = float(ts if ts is not None else time.time())
        px = float(price)
        q = float(qty)
        notional = max(0.0, px * q)
        s_norm = str(side).upper()
        # Borsa forceOrder 'BUY' ise short pozisyon zorla kapatılıyordur (SHORT_LIQ).
        if s_norm in ("BUY", "SHORT_LIQ", "SHORT"):
            norm_side = "SHORT_LIQ"
        else:
            norm_side = "LONG_LIQ"
        ev = LiquidationEvent(
            ts=now,
            symbol=self.symbol,
            side=norm_side,
            price=px,
            qty=q,
            notional_usdt=notional,
        )
        self.liquidations.append(ev)
        self._prune(now)
        return ev

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_sec
        hist_cutoff = now - max(self.window_sec * 6, 1800)
        while self._trades and self._trades[0][0] < cutoff:
            self._trades.popleft()
        while self._vol_hist and self._vol_hist[0][0] < hist_cutoff:
            self._vol_hist.popleft()
        while self._cvd_hist and self._cvd_hist[0][0] < cutoff:
            self._cvd_hist.popleft()
        while self._book_hist and self._book_hist[0][0] < cutoff:
            self._book_hist.popleft()
        vpvr_cutoff = now - self.vpvr_window_sec
        while self._vpvr_trades and self._vpvr_trades[0][0] < vpvr_cutoff:
            self._vpvr_trades.popleft()
        while self._oi_hist and self._oi_hist[0][0] < now - self.window_sec * 4 and len(self._oi_hist) > 2:
            self._oi_hist.popleft()
        while self.liquidations and self.liquidations[0].ts < cutoff:
            self.liquidations.popleft()

    # -- Açık Faiz & Squeeze Analizi -----------------------------------------
    def _oi_and_squeeze(self, now: float, delta_ratio: float, cvd_slope: float = 0.0) -> dict:
        cutoff = now - self.window_sec
        short_liq = sum(
            e.notional_usdt for e in self.liquidations if e.ts >= cutoff and e.side == "SHORT_LIQ"
        )
        long_liq = sum(
            e.notional_usdt for e in self.liquidations if e.ts >= cutoff and e.side == "LONG_LIQ"
        )

        oi_now = self._oi_hist[-1][1] if self._oi_hist else 0.0
        oi_change_pct = 0.0
        price_change_pct = 0.0
        if len(self._oi_hist) >= 2:
            oi_prev = self._oi_hist[0][1]
            px_prev = self._oi_hist[0][2]
            px_now = self._oi_hist[-1][2]
            if oi_prev > 0:
                oi_change_pct = (oi_now - oi_prev) / oi_prev * 100.0
            if px_prev > 0 and px_now > 0:
                price_change_pct = (px_now - px_prev) / px_prev * 100.0

        squeeze = "YOK"
        squeeze_boost = 0.0
        if short_liq >= self.liq_squeeze_usdt and short_liq > long_liq * 1.5:
            squeeze = "SHORT_SQUEEZE"
            intensity = min(1.0, short_liq / max(self.liq_squeeze_usdt * 3, 1.0))
            squeeze_boost = 15.0 + 10.0 * intensity  # +15 .. +25 puan
        elif long_liq >= self.liq_squeeze_usdt and long_liq > short_liq * 1.5:
            squeeze = "LONG_SQUEEZE"
            intensity = min(1.0, long_liq / max(self.liq_squeeze_usdt * 3, 1.0))
            squeeze_boost = -(15.0 + 10.0 * intensity)  # -15 .. -25 puan

        # OI + fiyat matrisi. Fiyat yönü belirleyicidir; taker delta yalnızca
        # fiyat yatayken yön vekili ve CVD ise ayrı bir onay/çelişki ölçüsüdür.
        oi_signal = "NOTR"
        oi_boost = 0.0
        price_direction = 0
        if price_change_pct > 0.05:
            price_direction = 1
        elif price_change_pct < -0.05:
            price_direction = -1
        elif delta_ratio > 0.15:
            price_direction = 1
        elif delta_ratio < -0.15:
            price_direction = -1

        if oi_change_pct > 0.5 and price_direction > 0:
            oi_signal = "YENI_LONG_GIRISI"
            oi_boost = min(10.0, oi_change_pct * 2.5)
        elif oi_change_pct > 0.5 and price_direction < 0:
            oi_signal = "YENI_SHORT_GIRISI"
            oi_boost = -min(10.0, oi_change_pct * 2.5)
        elif oi_change_pct < -1.0 and price_direction > 0:
            # Short covering yükselişi yeni long girişinden daha zayıf kabul edilir.
            oi_signal = "SHORT_KAPAMA_RALLISI"
            oi_boost = 3.0
        elif oi_change_pct < -1.0 and price_direction < 0:
            oi_signal = "LONG_TASFIYE_DUSUSU"
            oi_boost = -3.0

        signal_direction = 1 if oi_boost > 0 else (-1 if oi_boost < 0 else 0)
        if signal_direction and cvd_slope * signal_direction > 0:
            oi_flow_confirmation = "CVD_ONAYLI"
        elif signal_direction and cvd_slope * signal_direction < 0:
            oi_flow_confirmation = "CVD_CELISKILI"
            oi_boost *= 0.5
        else:
            oi_flow_confirmation = "CVD_VERI_YOK"

        return {
            "open_interest": round(oi_now, 2),
            "oi_change_pct": round(oi_change_pct, 2),
            "price_change_pct": round(price_change_pct, 3),
            "oi_signal": oi_signal,
            "oi_flow_confirmation": oi_flow_confirmation,
            "short_liq_usdt": round(short_liq, 1),
            "long_liq_usdt": round(long_liq, 1),
            "squeeze": squeeze,
            "oi_liq_boost": round(squeeze_boost + oi_boost, 1),
        }

    # -- CVD divergence + absorption ---------------------------------------
    def _orderflow_structure(self, now: float) -> dict:
        points = list(self._cvd_hist)
        divergence = "YOK"
        if len(points) >= 10:
            midpoint = (points[0][0] + points[-1][0]) / 2.0
            previous = [p for p in points if p[0] <= midpoint]
            recent = [p for p in points if p[0] > midpoint]
            if len(previous) >= 4 and len(recent) >= 4:
                window_notional = sum(n for _, _, n in self._trades)
                epsilon = max(1.0, window_notional * 0.005)
                prev_high = max(p[2] for p in previous)
                recent_high = max(p[2] for p in recent)
                prev_low = min(p[2] for p in previous)
                recent_low = min(p[2] for p in recent)
                min_move = self.divergence_min_price_pct / 100.0
                bearish = (
                    prev_high > 0
                    and recent_high > prev_high * (1.0 + min_move)
                    and max(p[1] for p in recent)
                    < max(p[1] for p in previous) - epsilon
                )
                bullish = (
                    prev_low > 0
                    and recent_low < prev_low * (1.0 - min_move)
                    and min(p[1] for p in recent)
                    > min(p[1] for p in previous) + epsilon
                )
                if bearish:
                    divergence = "BEARISH"
                elif bullish:
                    divergence = "BULLISH"

        cutoff = now - 60.0
        recent_trades = [t for t in self._trades if t[0] >= cutoff]
        buy_v = sum(n for _, signed, n in recent_trades if signed > 0)
        sell_v = sum(n for _, signed, n in recent_trades if signed < 0)
        total = buy_v + sell_v
        recent_points = [p for p in points if p[0] >= cutoff]
        recent_prices = [p[2] for p in recent_points if p[2] > 0]
        books = [b for b in self._book_hist if b[0] >= cutoff]
        cvd_60s = (
            recent_points[-1][1] - recent_points[0][1]
            if len(recent_points) >= 2
            else 0.0
        )
        price_change = 0.0
        bid_change = 0.0
        ask_change = 0.0
        if len(recent_prices) >= 2 and recent_prices[0] > 0:
            price_change = (recent_prices[-1] / recent_prices[0] - 1.0) * 100.0
        if len(books) >= 2:
            if books[0][1] > 0:
                bid_change = (books[-1][1] / books[0][1] - 1.0) * 100.0
            if books[0][2] > 0:
                ask_change = (books[-1][2] / books[0][2] - 1.0) * 100.0

        absorption = "YOK"
        depth_change = 0.0
        enough_structure = len(recent_prices) >= 2 and len(books) >= 2
        if enough_structure and total >= self.absorption_min_usdt:
            max_move = 0.10  # %0.10'dan fazla karşı hareket "emilim" değildir.
            if (
                sell_v >= buy_v * self.absorption_ratio
                and price_change >= -max_move
                and bid_change >= -10.0
            ):
                absorption = "SATIS_EMILIMI"  # agresif satış, bid derinliğinde emiliyor
                depth_change = bid_change
            elif (
                buy_v >= sell_v * self.absorption_ratio
                and price_change <= max_move
                and ask_change >= -10.0
            ):
                absorption = "ALIS_EMILIMI"  # agresif alış, ask derinliğinde emiliyor
                depth_change = ask_change

        return {
            "cvd_divergence": divergence,
            "absorption": absorption,
            "cvd_60s": round(cvd_60s, 1),
            "absorption_price_change_pct": round(price_change, 4),
            "absorption_depth_change_pct": round(depth_change, 3),
            "absorption_buy_usdt": round(buy_v, 1),
            "absorption_sell_usdt": round(sell_v, 1),
        }

    def tick_volume_profile(self) -> dict:
        """Gerçek trade fiyatı/hacmiyle bounded VPVR; mum typical-price kullanmaz."""
        trades = [t for t in self._vpvr_trades if t[1] > 0 and t[2] >= 0]
        if not trades:
            return {
                "vpvr_source": "TICK_VPVR",
                "vpvr_poc": 0.0,
                "vpvr_vah": 0.0,
                "vpvr_val": 0.0,
                "vpvr_trades": 0,
                "vpvr_total_usdt": 0.0,
                "vpvr_coverage_sec": 0.0,
                "vpvr_warm": False,
            }
        low = min(t[1] for t in trades)
        high = max(t[1] for t in trades)
        width = max((high - low) / self.vpvr_bins, 1e-12)
        volumes = [0.0] * self.vpvr_bins
        for _, price, notional in trades:
            idx = min(self.vpvr_bins - 1, max(0, int((price - low) / width)))
            volumes[idx] += notional
        poc_idx = max(range(self.vpvr_bins), key=volumes.__getitem__)
        total = sum(volumes)
        target = total * 0.70
        included = volumes[poc_idx]
        left = right = poc_idx
        while included < target and (left > 0 or right < self.vpvr_bins - 1):
            left_vol = volumes[left - 1] if left > 0 else -1.0
            right_vol = volumes[right + 1] if right < self.vpvr_bins - 1 else -1.0
            if right_vol > left_vol:
                right += 1
                included += volumes[right]
            else:
                left -= 1
                included += volumes[left]
        coverage = max(0.0, trades[-1][0] - trades[0][0])
        return {
            "vpvr_source": "TICK_VPVR",
            "vpvr_poc": round(low + (poc_idx + 0.5) * width, 8),
            "vpvr_vah": round(low + (right + 1) * width, 8),
            "vpvr_val": round(low + left * width, 8),
            "vpvr_trades": len(trades),
            "vpvr_total_usdt": round(total, 2),
            "vpvr_coverage_sec": round(coverage, 1),
            "vpvr_warm": len(trades) >= 100 and coverage >= 300,
        }

    # -- skor ---------------------------------------------------------------
    def snapshot(self, include_vpvr: bool = True) -> dict:
        now = time.time()
        self._prune(now)
        buy_v = sum(n for _, s, n in self._trades if s > 0)
        sell_v = sum(n for _, s, n in self._trades if s < 0)
        tot = buy_v + sell_v
        delta_ratio = (buy_v - sell_v) / tot if tot > 0 else 0.0

        cvd_slope = 0.0
        if len(self._cvd_hist) >= 2:
            cvd_slope = self._cvd_hist[-1][1] - self._cvd_hist[0][1]

        cutoff = now - self.window_sec
        w_buy = sum(w.notional_usdt for w in self.whales if w.ts >= cutoff and w.side == "ALIŞ")
        w_sell = sum(w.notional_usdt for w in self.whales if w.ts >= cutoff and w.side == "SATIŞ")
        w_tot = w_buy + w_sell
        whale_ratio = (w_buy - w_sell) / w_tot if w_tot > 0 else 0.0

        # Tarihsel ortalama akış hızına göre hacim patlaması
        spike = 1.0
        if len(self._vol_hist) >= 10:
            span = max(1.0, now - self._vol_hist[0][0])
            avg_per_win = (sum(n for _, n in self._vol_hist) / span) * self.window_sec
            if avg_per_win > 0:
                spike = tot / avg_per_win
        volume_spike = spike >= self.spike_mult

        # Açık Faiz (OI) ve Likidasyon Squeeze analizi
        oi_info = self._oi_and_squeeze(now, delta_ratio, cvd_slope)
        # 20 Kademe Emir Defteri Derinlik Analizi (Bid/Ask Ratio + Weighted OBI)
        depth_info = self.depth_snapshot()
        structure_info = self._orderflow_structure(now)
        vpvr_info = self.tick_volume_profile() if include_vpvr else {}
        window_coverage = (
            min(self.window_sec, max(0.0, now - self._trades[0][0]))
            if self._trades
            else 0.0
        )
        book_age = (now - self._book_hist[-1][0]) if self._book_hist else None

        # Skor birleşimi: Taker Delta + CVD + Balina + 20 Kademe Derinlik + OI/Squeeze
        score_components = {
            "taker_delta": delta_ratio * 42,
            "cvd_direction": (1 if cvd_slope > 0 else (-1 if cvd_slope < 0 else 0)) * 14,
            "whale_balance": whale_ratio * 24,
            "orderbook_depth": depth_info["depth_score_boost"],
            "oi_liquidation": oi_info["oi_liq_boost"],
            "volume_spike": 0.0,
        }
        # Hacim patlaması yönü güçlendirir
        if volume_spike and tot > 0:
            score_components["volume_spike"] = 8.0 if delta_ratio > 0 else -8.0
        score_unclipped = float(sum(score_components.values()))
        score = max(-100, min(100, score_unclipped))

        return {
            "score": round(score, 1),
            "score_unclipped": score_unclipped,
            "score_components": score_components,
            "buy_usdt": round(buy_v, 1),
            "sell_usdt": round(sell_v, 1),
            "net_usdt": round(buy_v - sell_v, 1),
            "cvd": round(self._cvd, 1),
            "cvd_slope": round(cvd_slope, 1),
            "trade_count": len(self._trades),
            "window_coverage_sec": round(window_coverage, 1),
            "book_age_sec": round(book_age, 3) if book_age is not None else None,
            "whale_buy_usdt": round(w_buy, 1),
            "whale_sell_usdt": round(w_sell, 1),
            "volume_spike": volume_spike,
            "spike_mult": round(spike, 2),
            **depth_info,
            **oi_info,
            **structure_info,
            **vpvr_info,
            "verdict": (
                "GÜÇLÜ GİRİŞ"
                if score >= 40
                else (
                    "GİRİŞ"
                    if score >= 15
                    else (
                        "GÜÇLÜ ÇIKIŞ"
                        if score <= -40
                        else ("ÇIKIŞ" if score <= -15 else "DENGELİ")
                    )
                )
            ),
        }
