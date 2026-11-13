"""Bizim SpikeDetector + v7.8 trade callback; yalnız gözlem, EMİR YOK.

Callback borsa olay zamanını/tekil ID'yi taşımıyor. Alım zamanı, gözlenen trade
miktarı ve local dakika ile hacim biriktirilir; eksik/tekrar veri engellenemez.
Bu nedenle üretilen gözlem gerçek eski botun candle akışına eşdeğer değildir,
stratejiye giriş, fiyat/risk kilidi veya performans kanıtı olarak KULLANILMAZ.
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import asdict
from scanner.ws_scanner import SpikeDetector


class SpikeShadow:
    def __init__(self, detector=None):
        self.detector = detector if detector is not None else SpikeDetector()
        self._minute = {}
        self._last_ts = {}
        self.seen = 0
        self.rejected = 0
        self.signals = 0
        self.recent = deque(maxlen=20)

    def observe_trade(self, exchange, symbol, price, qty, *, received_ms=None):
        try:
            price, qty = float(price), float(qty)
            ts = int(time.time() * 1000) if received_ms is None else int(received_ms)
            if exchange not in ('binance','okx') or not symbol or ts <= 0:
                raise ValueError('invalid source')
            if not math.isfinite(price) or not math.isfinite(qty) or price <= 0 or qty <= 0:
                raise ValueError('invalid trade')
            notional = price * qty
            if not math.isfinite(notional):
                raise ValueError('invalid notional')
            key = (exchange, symbol)
            if ts < self._last_ts.get(key, 0):
                raise ValueError('local clock moved backwards')
        except (TypeError, ValueError, OverflowError):
            self.rejected += 1
            return None
        self._last_ts[key] = ts
        minute = ts // 60_000
        old_minute, total = self._minute.get(key, (minute, 0.0))
        if minute != old_minute:
            total = 0.0
        total += notional
        self._minute[key] = (minute, total)
        self.seen += 1
        # Detector may emit at either input; it internally applies cooldown.
        first = self.detector.besle_hacim(exchange, symbol, total, minute, ts)
        second = self.detector.besle_fiyat(exchange, symbol, price, 0.0, ts)
        signal = first if first is not None else second
        if signal is not None:
            self.signals += 1
            self.recent.append(asdict(signal))
        return signal

    def status(self):
        return {'mode':'shadow_only', 'trade_route':False, 'seen':self.seen,
                'rejected':self.rejected, 'signals':self.signals,
                'source_limits':'local receipt time; no event ID; incomplete feed/reconnect not validated'}
