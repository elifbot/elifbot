# -*- coding: utf-8 -*-
"""
ACARBOT OMEGA — Saliselik Mikro-Tape, Hacim Şoku & 10-İndikatörlü Konfluans Motoru (microstructure.py)
======================================================================================================
Birleştirilen Miras:
  - TURBO v3.1: Saliselik O(1) SymbolMicroTape, Hacim Patlaması ve Hacim Çöküşü algılayıcısı
  - APEX v1.1: EMA, RSI, ATR%, ADX, Bollinger, Supertrend, OBV ve piyasa rejimi sınıflandırıcısı
  - FUTURES_BOT v37: Canlı hacim ağırlıklı VWAP ve standart sapma (Z-Score) sapması
  - PHOENIX V4: Opsiyonel türev verileri (Funding, OI, Spread, Book Imbalance) yoksa paydadan düşen adil skor
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional

from .contracts import ContractSpec, parse_contract_spec


@dataclass
class MicroTick:
    ts: float
    price: float
    delta_usd: float
    buy_usd: float


@dataclass
class MinuteCandle:
    minute_ts: int
    o: float
    h: float
    l: float
    c: float
    v_usd: float
    buy_usd: float


@dataclass
class OmegaFeatureSnapshot:
    key: str
    exchange: str
    symbol: str
    base_asset: str
    price: float
    quote_vol_24h: float
    pct_24h: float
    # Anlık Hacim Patlaması / Çöküşü Metrikleri
    vol_mult: float
    burst_usd: float
    ret_burst_pct: float
    ret_30s_pct: float
    orderflow_bias: float      # [-1.0 .. +1.0] CVD / Taker Alıcı-Satıcı Baskısı
    range_pos: float           # [0.0 .. 1.0] Fitil / Tuzak konumu
    peak_burst_mult_60s: float
    peak_burst_move_60s: float
    secs_since_peak_burst: float
    # 1dk Mum Tabanlı 10-İndikatör & Rejim Metrikleri
    regime: str                # WARMUP | TREND_UP | TREND_DOWN | RANGE | EXTREME_VOL | BREAKOUT
    vwap_price: float
    vwap_dev_pct: float
    rsi_14: float
    atr_pct: float
    ema_fast_vs_slow_pct: float
    choppiness_index: float    # [0..100] >62 ise testere (whipsaw) bölgesi
    technical_confluence: float  # [-1.0 .. +1.0] 10-oylu teknik uyum skoru
    # Opsiyonel Türev Verileri (PHOENIX V4 adil payda yöntemiyle)
    spread_bps: Optional[float] = None
    funding_rate: Optional[float] = None
    oi_change_pct: Optional[float] = None
    book_imbalance: Optional[float] = None
    liquidation_pressure: Optional[float] = None
    derivatives_composite: Optional[float] = None


class OmegaSymbolTape:
    """Tek vadeli işlem kontratı için saliselik mikro-akış + 1dk teknik bar belleği."""

    def __init__(self, exchange: str, symbol: str, ref_price: float = 100.0) -> None:
        self.spec: ContractSpec = parse_contract_spec(exchange, symbol, ref_price=ref_price)
        self.exchange = self.spec.exchange
        self.symbol = self.spec.symbol
        self.last_price: float = 0.0
        self.pct_24h: float = 0.0
        self.quote_vol_24h: float = 0.0
        self.prev_q24: float = 0.0
        self.last_ts: float = 0.0

        self.prev_kline_ts: int = 0
        self.prev_kline_q: float = 0.0
        self.prev_kline_buy_q: float = 0.0

        self.ticks: Deque[MicroTick] = deque(maxlen=260)
        self.candles_1m: Deque[MinuteCandle] = deque(maxlen=96)
        self.rolling_sec_rates: Deque[float] = deque(maxlen=60)

        # Hacim Çöküşü (Volume Collapse) dönüş hafızası
        self.peak_burst_mult_60s: float = 1.0
        self.peak_burst_move_60s: float = 0.0
        self.peak_burst_ts: float = 0.0

        # Opsiyonel gerçek zamanlı türev beslemeleri
        self.spread_bps: Optional[float] = None
        self.funding_rate: Optional[float] = None
        self.oi_change_pct: Optional[float] = None
        self.book_imbalance: Optional[float] = None
        self.liquidation_pressure: Optional[float] = None

    @property
    def key(self) -> str:
        return f"{self.exchange}:{self.symbol}"

    def ingest(
        self,
        ts: float,
        price: float,
        quote_vol_24h: float = 0.0,
        pct_24h: float = 0.0,
        kline_ts: int = 0,
        kline_q_usd: float = -1.0,
        kline_buy_usd: float = -1.0,
        explicit_delta_usd: float = -1.0,
        explicit_buy_usd: float = -1.0,
        spread_bps: Optional[float] = None,
        funding_rate: Optional[float] = None,
        oi_change_pct: Optional[float] = None,
        book_imbalance: Optional[float] = None,
        liquidation_pressure: Optional[float] = None,
    ) -> None:
        if price <= 0 or not math.isfinite(price):
            return
        if self.last_price == 0.0:
            self.spec = parse_contract_spec(self.exchange, self.symbol, ref_price=price)

        prev_px = self.last_price or price
        self.last_price = price
        self.last_ts = ts

        old_q24 = self.prev_q24
        if quote_vol_24h > 0:
            self.quote_vol_24h = quote_vol_24h
            self.prev_q24 = quote_vol_24h
        if pct_24h != 0.0 or self.pct_24h == 0.0:
            self.pct_24h = pct_24h

        if spread_bps is not None:
            self.spread_bps = spread_bps
        if funding_rate is not None:
            self.funding_rate = funding_rate
        if oi_change_pct is not None:
            self.oi_change_pct = oi_change_pct
        if book_imbalance is not None:
            self.book_imbalance = book_imbalance
        if liquidation_pressure is not None:
            self.liquidation_pressure = liquidation_pressure

        # Anlık gerçek işlem hacmi (delta_usd) ve alıcı baskısı (buy_usd) çıkarımı
        delta_usd = 0.0
        buy_usd = 0.0
        if explicit_delta_usd >= 0.0:
            delta_usd = explicit_delta_usd
            if explicit_buy_usd >= 0.0:
                buy_usd = max(0.0, min(delta_usd, explicit_buy_usd))
            else:
                buy_usd = delta_usd * (0.74 if price > prev_px else (0.26 if price < prev_px else 0.50))
        elif kline_q_usd >= 0.0 and kline_ts > 0:
            if self.prev_kline_ts == 0:
                delta_usd = 0.0
            elif kline_ts == self.prev_kline_ts:
                delta_usd = max(0.0, kline_q_usd - self.prev_kline_q)
                if kline_buy_usd >= 0.0:
                    buy_usd = max(0.0, min(delta_usd, kline_buy_usd - self.prev_kline_buy_q))
                else:
                    buy_usd = delta_usd * (0.75 if price > prev_px else (0.25 if price < prev_px else 0.50))
            else:
                delta_usd = max(0.0, kline_q_usd)
                buy_usd = (
                    max(0.0, min(delta_usd, kline_buy_usd))
                    if kline_buy_usd >= 0.0
                    else delta_usd * (0.75 if price > prev_px else (0.25 if price < prev_px else 0.50))
                )
            self.prev_kline_ts = kline_ts
            self.prev_kline_q = kline_q_usd
            if kline_buy_usd >= 0.0:
                self.prev_kline_buy_q = kline_buy_usd
        elif self.prev_kline_ts == 0 and quote_vol_24h > 0 and old_q24 > 0:
            diff_24 = quote_vol_24h - old_q24
            if 0.0 < diff_24 < quote_vol_24h * 0.12:
                delta_usd = diff_24
                buy_usd = delta_usd * (0.75 if price > prev_px else (0.25 if price < prev_px else 0.50))

        self.ticks.append(MicroTick(ts=ts, price=price, delta_usd=delta_usd, buy_usd=buy_usd))
        cutoff = ts - 120.0
        while len(self.ticks) > 2 and self.ticks[0].ts < cutoff:
            self.ticks.popleft()

        # 1dk Mum güncellemesi
        min_bucket = int(ts // 60) * 60_000
        if not self.candles_1m or self.candles_1m[-1].minute_ts != min_bucket:
            if self.candles_1m and self.candles_1m[-1].v_usd > 0:
                self.rolling_sec_rates.append(self.candles_1m[-1].v_usd / 60.0)
            self.candles_1m.append(
                MinuteCandle(
                    minute_ts=min_bucket,
                    o=price,
                    h=price,
                    l=price,
                    c=price,
                    v_usd=max(0.0, delta_usd),
                    buy_usd=max(0.0, buy_usd),
                )
            )
        else:
            c = self.candles_1m[-1]
            if price > c.h:
                c.h = price
            if price < c.l:
                c.l = price
            c.c = price
            c.v_usd += max(0.0, delta_usd)
            c.buy_usd += max(0.0, buy_usd)

    def baseline_usd_per_sec(self) -> float:
        rate_24h = (self.quote_vol_24h / 86_400.0) if self.quote_vol_24h > 0 else 200.0
        if len(self.rolling_sec_rates) >= 3:
            sorted_r = sorted(self.rolling_sec_rates)
            med = sorted_r[len(sorted_r) // 2]
            return max(75.0, 0.55 * med + 0.45 * rate_24h)
        return max(75.0, rate_24h)

    def _compute_candle_indicators(self) -> Dict[str, float | str]:
        bars = list(self.candles_1m)
        px = self.last_price
        if len(bars) < 5:
            # Erken ısınma aşamasında son 2dk tick'lerden mikro-VWAP ve esneklik hesapla
            tot_v = sum(t.delta_usd for t in self.ticks)
            vwap_px = (sum(t.price * t.delta_usd for t in self.ticks) / tot_v) if tot_v > 0 else px
            dev_pct = ((px - vwap_px) / vwap_px * 100.0) if vwap_px > 0 else 0.0
            return {
                "regime": "WARMUP",
                "vwap": vwap_px,
                "vwap_dev_pct": dev_pct,
                "rsi": 50.0,
                "atr_pct": 0.35,
                "ema_spread_pct": dev_pct,
                "chop": 48.0,
                "confluence": max(-1.0, min(1.0, dev_pct * 1.6)),
            }

        closes = [b.c for b in bars]
        highs = [b.h for b in bars]
        lows = [b.l for b in bars]
        vols = [b.v_usd for b in bars]

        # 1) Hacim Ağırlıklı VWAP
        v_sum = sum(vols)
        if v_sum > 0:
            vwap_px = sum(((b.h + b.l + b.c) / 3.0) * b.v_usd for b in bars) / v_sum
        else:
            vwap_px = sum(closes) / len(closes)
        vwap_dev_pct = ((px - vwap_px) / vwap_px * 100.0) if vwap_px > 0 else 0.0

        # 2) EMA Hızlı (9) vs Yavaş (21)
        def _ema(vals: list[float], span: int) -> float:
            k = 2.0 / (span + 1.0)
            e = vals[0]
            for v in vals[1:]:
                e = v * k + e * (1.0 - k)
            return e

        ema9 = _ema(closes, min(9, len(closes)))
        ema21 = _ema(closes, min(21, len(closes)))
        ema_spread_pct = ((ema9 / ema21) - 1.0) * 100.0 if ema21 > 0 else 0.0

        # 3) RSI(14)
        look_rsi = min(14, len(closes) - 1)
        gains, losses = 0.0, 0.0
        for i in range(-look_rsi, 0):
            diff = closes[i] - closes[i - 1]
            if diff > 0:
                gains += diff
            else:
                losses -= diff
        if gains + losses == 0:
            rsi = 50.0
        elif losses == 0:
            rsi = 85.0
        else:
            rs = (gains / look_rsi) / (losses / look_rsi)
            rsi = 100.0 - (100.0 / (1.0 + rs))

        # 4) ATR% ve Choppiness Index (14 bar)
        look_tr = min(14, len(bars) - 1)
        trs: list[float] = []
        for i in range(-look_tr, 0):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            trs.append(tr)
        atr_val = (sum(trs) / len(trs)) if trs else (px * 0.003)
        atr_pct = (atr_val / px * 100.0) if px > 0 else 0.35

        hh = max(highs[-look_tr:])
        ll = min(lows[-look_tr:])
        span_hl = max(1e-12, hh - ll)
        sum_tr = sum(trs)
        if look_tr >= 4 and sum_tr > 0 and span_hl > 1e-12:
            chop = 100.0 * math.log10(max(1.0, sum_tr / span_hl)) / math.log10(look_tr)
            chop = max(15.0, min(90.0, chop))
        else:
            chop = 48.0

        # 5) OBV / Mum İçi Alıcı Akışı Eğimi
        net_bar_flow = sum((2.0 * b.buy_usd - b.v_usd) for b in bars[-min(8, len(bars)):])
        recent_vol = sum(b.v_usd for b in bars[-min(8, len(bars)):])
        obv_bias = (net_bar_flow / recent_vol) if recent_vol > 0 else 0.0

        # 6) 10-Oylu Konfluans Skoru [-1.0 .. +1.0]
        votes = 0.0
        votes += 1.0 if px > vwap_px else -1.0
        votes += 1.0 if ema9 > ema21 else -1.0
        votes += 1.0 if closes[-1] > closes[-min(4, len(closes))] else -1.0
        votes += 1.0 if 52.0 <= rsi <= 78.0 else (-1.0 if 22.0 <= rsi <= 48.0 else 0.0)
        votes += 1.0 if obv_bias > 0.08 else (-1.0 if obv_bias < -0.08 else 0.0)
        mid_hl = 0.5 * (hh + ll)
        votes += 1.0 if px > mid_hl else -1.0
        confluence = max(-1.0, min(1.0, votes / 6.0))

        if atr_pct >= 4.5:
            regime = "EXTREME_VOL"
        elif chop >= 62.0:
            regime = "RANGE"
        elif ema_spread_pct >= 0.08 and px >= vwap_px:
            regime = "TREND_UP"
        elif ema_spread_pct <= -0.08 and px <= vwap_px:
            regime = "TREND_DOWN"
        else:
            regime = "BREAKOUT"

        return {
            "regime": regime,
            "vwap": vwap_px,
            "vwap_dev_pct": vwap_dev_pct,
            "rsi": rsi,
            "atr_pct": atr_pct,
            "ema_spread_pct": ema_spread_pct,
            "chop": chop,
            "confluence": confluence,
        }

    def _compute_derivatives_composite(self) -> Optional[float]:
        """PHOENIX V4 prensibi: eksik türev beslemelerini 0 sayıp sinyali sulandırma, paydadan çıkar!"""
        parts: list[tuple[float, float]] = []
        if self.oi_change_pct is not None:
            parts.append((0.35, max(-1.0, min(1.0, self.oi_change_pct / 2.0))))
        if self.book_imbalance is not None:
            parts.append((0.35, max(-1.0, min(1.0, self.book_imbalance))))
        if self.funding_rate is not None:
            # Aşırı kalabalık fonlama ters yönlü risk taşır
            parts.append((0.15, max(-1.0, min(1.0, -self.funding_rate * 120.0))))
        if self.liquidation_pressure is not None:
            parts.append((0.15, max(-1.0, min(1.0, self.liquidation_pressure))))
        if not parts:
            return None
        w_sum = sum(w for w, _ in parts)
        return round(sum(w * v for w, v in parts) / w_sum, 4)

    def snapshot(self, burst_window_sec: float = 12.0) -> OmegaFeatureSnapshot:
        now = self.last_ts
        burst_cut = now - burst_window_sec
        cut_30s = now - 30.0

        burst_usd = 0.0
        burst_buy = 0.0
        px_burst_start = self.last_price
        px_30s_start = self.last_price
        found_burst = False
        found_30s = False
        hi_b = self.last_price
        lo_b = self.last_price

        for t in self.ticks:
            if not found_30s and t.ts >= cut_30s:
                px_30s_start = t.price
                found_30s = True
            if t.ts >= burst_cut:
                if not found_burst:
                    px_burst_start = t.price
                    found_burst = True
                burst_usd += t.delta_usd
                burst_buy += t.buy_usd
                if t.price > hi_b:
                    hi_b = t.price
                if t.price < lo_b:
                    lo_b = t.price

        first_ts = self.ticks[0].ts if self.ticks else now
        elapsed = max(3.0, min(burst_window_sec, now - first_ts))
        live_rate = burst_usd / elapsed
        base_rate = self.baseline_usd_per_sec()
        vol_mult = (live_rate / base_rate) if base_rate > 0 else 0.0

        ret_burst_pct = ((self.last_price - px_burst_start) / px_burst_start * 100.0) if px_burst_start > 0 else 0.0
        ret_30s_pct = ((self.last_price - px_30s_start) / px_30s_start * 100.0) if px_30s_start > 0 else 0.0

        if burst_usd > 0:
            orderflow_bias = (2.0 * burst_buy - burst_usd) / burst_usd
        else:
            orderflow_bias = max(-1.0, min(1.0, ret_burst_pct * 1.5))

        # Fitil / Tuzak konumu 60 saniyelik geniş pencere üzerinden ölçülür: böylece
        # patlama sonrası zirveden kopup geri çekilen (chase) girişler doğru yakalanır.
        cut_60s = now - 60.0
        hi_60 = self.last_price
        lo_60 = self.last_price
        for t in self.ticks:
            if t.ts < cut_60s:
                continue
            if t.price > hi_60:
                hi_60 = t.price
            if t.price < lo_60:
                lo_60 = t.price
        for bar in self.candles_1m:
            if bar.minute_ts // 1000 < cut_60s:
                continue
            hi_60 = max(hi_60, bar.h)
            lo_60 = min(lo_60, bar.l)

        span = hi_60 - lo_60
        range_pos = ((self.last_price - lo_60) / span) if span > 1e-12 else 0.5
        hi_b, lo_b = hi_60, lo_60

        prev_peak_mult = self.peak_burst_mult_60s
        prev_peak_move = self.peak_burst_move_60s
        prev_peak_ts = self.peak_burst_ts

        if (now - self.peak_burst_ts) > 75.0 or vol_mult >= self.peak_burst_mult_60s:
            self.peak_burst_mult_60s = vol_mult
            self.peak_burst_move_60s = ret_30s_pct if abs(ret_30s_pct) >= abs(ret_burst_pct) else ret_burst_pct
            self.peak_burst_ts = now
            prev_peak_mult = self.peak_burst_mult_60s
            prev_peak_move = self.peak_burst_move_60s
            prev_peak_ts = self.peak_burst_ts

        ind = self._compute_candle_indicators()
        deriv = self._compute_derivatives_composite()

        return OmegaFeatureSnapshot(
            key=self.key,
            exchange=self.exchange,
            symbol=self.symbol,
            base_asset=self.spec.base_asset,
            price=self.last_price,
            quote_vol_24h=self.quote_vol_24h,
            pct_24h=self.pct_24h,
            vol_mult=round(vol_mult, 2),
            burst_usd=round(burst_usd, 2),
            ret_burst_pct=round(ret_burst_pct, 4),
            ret_30s_pct=round(ret_30s_pct, 4),
            orderflow_bias=round(max(-1.0, min(1.0, orderflow_bias)), 3),
            range_pos=round(range_pos, 3),
            peak_burst_mult_60s=round(prev_peak_mult, 2),
            peak_burst_move_60s=round(prev_peak_move, 4),
            secs_since_peak_burst=round(max(0.0, now - prev_peak_ts), 2),
            regime=str(ind["regime"]),
            vwap_price=float(ind["vwap"]),
            vwap_dev_pct=round(float(ind["vwap_dev_pct"]), 4),
            rsi_14=round(float(ind["rsi"]), 2),
            atr_pct=round(float(ind["atr_pct"]), 4),
            ema_fast_vs_slow_pct=round(float(ind["ema_spread_pct"]), 4),
            choppiness_index=round(float(ind["chop"]), 2),
            technical_confluence=round(float(ind["confluence"]), 3),
            spread_bps=self.spread_bps,
            funding_rate=self.funding_rate,
            oi_change_pct=self.oi_change_pct,
            book_imbalance=self.book_imbalance,
            liquidation_pressure=self.liquidation_pressure,
            derivatives_composite=deriv,
        )
