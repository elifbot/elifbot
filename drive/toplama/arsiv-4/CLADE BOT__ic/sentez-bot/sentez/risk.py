"""Risk: boyutlandırma, yarım-Kelly, maliyet/hareket kapısı, devre kesici."""
from __future__ import annotations

from collections import deque
from typing import Optional

from .models import Config, Trade

DAY_MS = 86_400_000


def round_trip_cost_bps(cfg: Config) -> float:
    return cfg.taker_bps * 2 + cfg.slip_bps * 2 + cfg.spread_bps


def edge_ratio(price: float, atr: float, cfg: Config) -> float:
    """Hedefe kadar beklenen hareket (bps) / gidiş-dönüş maliyet (bps)."""
    cost = round_trip_cost_bps(cfg)
    if price <= 0 or cost <= 0:
        return 0.0
    return (cfg.tp_atr * atr / price) * 10_000 / cost


def edge_ok(price: float, atr: float, cfg: Config) -> bool:
    return cfg.min_edge_ratio <= 0 or edge_ratio(price, atr, cfg) >= cfg.min_edge_ratio


def size_position(equity: float, price: float, stop_dist: float, cfg: Config,
                  risk_pct: Optional[float] = None) -> tuple[float, float, str]:
    """Risk bazlı adet. Dönüş: (qty, risk_usd, red_nedeni).

    qty = risk_usd / stop_mesafesi; sonra max_notional ve kaldıraç marjına göre kırpılır.
    Kırpma riski düşürür, asla artırmaz.
    """
    if price <= 0 or stop_dist <= 0 or equity <= 0:
        return 0.0, 0.0, "BAD_INPUT"
    rp = cfg.risk_pct if risk_pct is None else risk_pct
    qty = (equity * rp / 100.0) / stop_dist
    cap = min(cfg.max_notional, equity * cfg.leverage)
    if qty * price > cap:
        qty = cap / price
    if qty * price < cfg.min_notional:
        return 0.0, 0.0, "BELOW_MIN_NOTIONAL"
    return qty, qty * stop_dist, ""


def liq_distance_pct(cfg: Config) -> float:
    """Yaklaşık tasfiye mesafesi (%): 1/kaldıraç - bakım marjı. Gerçek motor değildir."""
    return max(0.0, (1.0 / cfg.leverage - cfg.mmr) * 100.0)


class KellyTracker:
    """Son işlemlerin R çarpanlarından yarım-Kelly. Yetersiz veride None döner.

    UYARI: küçük örneklemde Kelly gürültülüdür; bu yüzden sonuç [0.25x, 1.5x] bandına kırpılır.
    """

    def __init__(self, maxlen: int = 200):
        self.r: deque[float] = deque(maxlen=maxlen)

    def add(self, r_mult: float) -> None:
        self.r.append(r_mult)

    def half_kelly(self, min_trades: int = 20) -> Optional[float]:
        if len(self.r) < min_trades:
            return None
        wins = [x for x in self.r if x > 0]
        losses = [-x for x in self.r if x < 0]
        if not wins or not losses:
            return None
        p = len(wins) / len(self.r)
        b = (sum(wins) / len(wins)) / (sum(losses) / len(losses))
        return (p - (1 - p) / b) / 2.0   # sermaye kesri

    def risk_pct(self, cfg: Config) -> float:
        """Taban riski çarpanla ölçekler: yarım-Kelly %5 ise 1x; band [0.25x, 1.5x].

        %5 referansı keyfidir ve ayardan açıkça değiştirilebilir hale getirilmedi:
        amaç Kelly'yi 'optimum' sanmak değil, kötüleşen seride riski kısmaktır.
        """
        hk = self.half_kelly(cfg.kelly_min_trades)
        if hk is None:
            return cfg.risk_pct
        return cfg.risk_pct * min(1.5, max(0.25, hk / 0.05))


class CircuitBreaker:
    """Günlük zarar, ardışık kayıp ve sermaye tabanı. allow() False ise yeni giriş yok."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.start_equity = cfg.equity
        self.day: Optional[int] = None
        self.day_start_equity = cfg.equity
        self.consec = 0
        self.paused_until = 0
        self.halted: Optional[str] = None
        self.trips: dict[str, int] = {}

    def _trip(self, why: str) -> None:
        self.trips[why] = self.trips.get(why, 0) + 1

    def on_trade(self, t: Trade) -> None:
        if t.pnl < 0:
            self.consec += 1
            if self.consec >= self.cfg.max_consec_losses:
                self.paused_until = t.close_ts + self.cfg.loss_pause_bars * self.cfg.bar_ms
                self.consec = 0
                self._trip("CONSEC_LOSSES")
        else:
            self.consec = 0

    def allow(self, ts: int, equity: float) -> tuple[bool, str]:
        if self.halted:
            return False, self.halted
        if equity <= self.start_equity * (1 - self.cfg.equity_halt_pct / 100.0):
            self.halted = "EQUITY_HALT"
            self._trip("EQUITY_HALT")
            return False, self.halted
        d = ts // DAY_MS
        if d != self.day:
            self.day, self.day_start_equity = d, equity
        if equity <= self.day_start_equity * (1 - self.cfg.daily_loss_pct / 100.0):
            self._trip("DAILY_LOSS")
            return False, "DAILY_LOSS"
        if ts < self.paused_until:
            return False, "LOSS_PAUSE"
        return True, ""
