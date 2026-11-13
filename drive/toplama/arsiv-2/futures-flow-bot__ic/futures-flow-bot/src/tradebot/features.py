"""Her coin icin akis (para girisi/cikisi) ozellikleri.

Girdi: normalize islem akisi. Cikti: delta orani, hacim patlamasi, fiyat degisimi, RSI, MACD.
Bellek: saniyelik kovalar (deque) -> hizli ve sinirli. 800 coin icin uygundur.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .config import ScannerCfg
from .indicators import MACD, RSI


@dataclass(slots=True)
class Features:
    price: float
    delta_ratio: float     # (alim - satim) / toplam, son flow_window_sec, [-1, 1]
    flow_usd: float        # son flow_window_sec toplam islem hacmi
    vol_ratio: float       # son 60 sn hacmi / dakika-hacim ortalamasi
    change_pct: float      # son 60 sn fiyat degisimi (%)
    rsi: float
    rsi_prev: float
    macd_hist: float
    macd_hist_prev: float


class SymbolState:
    KEEP_SEC = 130

    def __init__(self, sc: ScannerCfg):
        self.sc = sc
        self.buckets: deque = deque()   # [sec, buy_usd, sell_usd, first_price, last_price]
        self.last_price = 0.0
        self.last_ts = 0.0
        self.min_idx: int | None = None
        self.min_vol = 0.0
        self.minute_vols: deque = deque(maxlen=sc.baseline_minutes)
        self.c_idx: int | None = None
        self.c_close = 0.0
        self.rsi = RSI(14)
        self.macd = MACD()
        self.rsi_prev: float | None = None

    def add_trade(self, ts: float, price: float, usd: float, taker_buy: bool) -> None:
        sec = int(ts)
        b = self.buckets
        if b and sec <= b[-1][0]:
            row = b[-1]
        else:
            row = [sec, 0.0, 0.0, price, price]
            b.append(row)
        if taker_buy:
            row[1] += usd
        else:
            row[2] += usd
        row[4] = price
        cutoff = sec - self.KEEP_SEC
        while b and b[0][0] < cutoff:
            b.popleft()

        # dakika izgarasi (hacim tabani)
        m = int(ts // 60)
        if self.min_idx is None:
            self.min_idx = m
        elif m > self.min_idx:
            self.minute_vols.append(self.min_vol)
            for _ in range(min(m - self.min_idx - 1, self.sc.baseline_minutes)):
                self.minute_vols.append(0.0)
            self.min_vol = 0.0
            self.min_idx = m
        self.min_vol += usd

        # gosterge mumu izgarasi
        c = int(ts // self.sc.indicator_candle_seconds)
        if self.c_idx is None:
            self.c_idx = c
        elif c > self.c_idx:
            self.rsi_prev = self.rsi.value
            self.rsi.update(self.c_close)
            self.macd.update(self.c_close)
            self.c_idx = c
        self.c_close = price
        self.last_price = price
        self.last_ts = ts

    def compute(self, now: float) -> Features | None:
        sc = self.sc
        if self.last_price <= 0 or now - self.last_ts > sc.max_idle_sec:
            return None
        if (self.rsi.value is None or self.rsi_prev is None or not self.macd.ready
                or len(self.minute_vols) < sc.min_baseline_minutes):
            return None
        now_sec = int(now)
        flow_cut = now_sec - sc.flow_window_sec
        vol_cut = now_sec - sc.volume_window_sec
        buy = sell = vol = 0.0
        first_price = None
        for row in reversed(self.buckets):
            if row[0] <= vol_cut:
                break
            vol += row[1] + row[2]
            first_price = row[3]
            if row[0] > flow_cut:
                buy += row[1]
                sell += row[2]
        flow = buy + sell
        delta = (buy - sell) / flow if flow > 0 else 0.0
        baseline = max(sum(self.minute_vols) / len(self.minute_vols), sc.baseline_floor_usd)
        change = (self.last_price - first_price) / first_price * 100.0 if first_price else 0.0
        return Features(
            price=self.last_price, delta_ratio=delta, flow_usd=flow, vol_ratio=vol / baseline,
            change_pct=change, rsi=self.rsi.value, rsi_prev=self.rsi_prev,
            macd_hist=self.macd.hist, macd_hist_prev=self.macd.prev_hist,
        )
