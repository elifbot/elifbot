"""Risk: boyutlandırma, oynaklığa uyarlanmış kaldıraç, tasfiye mesafesi, devre kesici.

Sentez: sentez-bot'un kısıntı-mantığı (riski asla artırmayan kırpma); AcarBot'un
oynaklığa duyarlı kaldıraç fikri (GÜVENLİ sürüm: 20x değil 5x taban, oynaklık artınca
3x/2x'e iner); devre kesicide günlük zarar + ardışık zarar duraksaması + sermaye
tabanı + kill-switch dosyası (AcarBot /kill fikri).
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Optional

import pandas as pd

DAY_MS = 86_400_000


def round_trip_cost_bps(cfg) -> float:
    return cfg.risk.taker_bps * 2 + cfg.risk.slip_bps * 2 + cfg.risk.spread_bps


def edge_ratio(price: float, atr_val: float, cfg) -> float:
    """Hedefe kadar beklenen hareket (bps) / gidiş-dönüş maliyet (bps)."""
    cost = round_trip_cost_bps(cfg)
    if price <= 0 or atr_val <= 0 or cost <= 0:
        return 0.0
    target_move_bps = cfg.exit.tp_r * atr_val / price * 10_000
    return target_move_bps / cost


def edge_ok(price: float, atr_val: float, cfg) -> bool:
    """Sentez kapısı: hedef hareket, gidiş-dönüş maliyetin en az min_edge_ratio katı olmalı."""
    return cfg.strategy.min_edge_ratio <= 0 or edge_ratio(price, atr_val, cfg) >= cfg.strategy.min_edge_ratio


def adaptive_leverage(atrp: float, cfg) -> int:
    """Oynaklığa göre kaldıraç (AcarBot fikri, güvenli bant): sakin 5x → oynak 3x → aşırı 2x."""
    r = cfg.risk
    if atrp >= r.atrp_lev_extreme:
        return max(r.leverage_min, max(2, r.leverage_base // 2))
    if atrp >= r.atrp_lev_high:
        return max(r.leverage_min, max(3, int(r.leverage_base * 0.6)))
    return r.leverage_base


def liq_distance_pct(leverage: int, cfg) -> float:
    return max(0.0, (1.0 / max(leverage, 1) - cfg.risk.mmr) * 100.0)


def size_position(equity: float, price: float, stop_dist: float, atrp: float,
                  cfg) -> tuple[float, float, int, str]:
    """(qty, risk_usd, leverage, red_nedeni). Kırpma riski düşürür, asla artırmaz."""
    r = cfg.risk
    if price <= 0 or stop_dist <= 0 or equity <= 0:
        return 0.0, 0.0, r.leverage_base, "BAD_INPUT"
    lev = adaptive_leverage(atrp, cfg)
    qty = (equity * r.risk_per_trade_pct / 100.0) / stop_dist
    cap = min(r.max_notional_per_trade, equity * lev)
    if qty * price > cap:
        qty = cap / price
    if qty <= 0 or qty * price < 5.0:
        return 0.0, 0.0, lev, "BELOW_MIN_NOTIONAL"
    return qty, qty * stop_dist, lev, ""


class CircuitBreaker:
    """Günlük zarar + ardışık zarar duraksaması + sermaye tabanı + kill dosyası."""

    def __init__(self, cfg, base_equity: float):
        self.cfg = cfg
        self.base = base_equity
        self.day: Optional[int] = None
        self.day_start = base_equity
        self.consec = 0
        self.paused_until: Optional[pd.Timestamp] = None
        self.halted: Optional[str] = None
        self.trips: Counter[str] = Counter()

    def _trip(self, why: str) -> None:
        self.trips[why] += 1

    def on_close(self, ts: pd.Timestamp, pnl: float, bar_ms: float) -> None:
        if pnl < 0:
            self.consec += 1
            if self.consec >= self.cfg.risk.max_consec_losses:
                self.paused_until = pd.Timestamp(ts) + pd.Timedelta(
                    milliseconds=self.cfg.risk.loss_pause_bars * bar_ms)
                self.consec = 0
                self._trip("CONSEC_LOSSES")
        else:
            self.consec = 0

    def allow(self, ts: pd.Timestamp, equity: float) -> tuple[bool, str]:
        c = self.cfg
        if Path(c.exec.kill_file).exists():
            self._trip("KILL_FILE")
            return False, "KILL_FILE"
        if self.halted:
            return False, self.halted
        if equity <= self.base * (1 - c.risk.equity_halt_pct / 100.0):
            self.halted = "EQUITY_HALT"
            self._trip("EQUITY_HALT")
            return False, self.halted
        day = int(pd.Timestamp(ts).value // 1_000_000 // DAY_MS)
        if day != self.day:
            self.day, self.day_start = day, equity
        if equity <= self.day_start * (1 - c.risk.daily_loss_pct / 100.0):
            self._trip("DAILY_LOSS")
            return False, "DAILY_LOSS"
        if self.paused_until is not None and pd.Timestamp(ts) < self.paused_until:
            return False, "LOSS_PAUSE"
        return True, ""
