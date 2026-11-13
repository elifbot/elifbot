"""Ortak veri modelleri."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Bar:
    ts_ms: int          # mum açılış zamanı (ms, UTC)
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Signal:
    side: int                     # +1 long, -1 short, 0 nötr
    score: float
    votes: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    vetoes: list[str] = field(default_factory=list)
    regime: str = "TREND"
    atr: float = 0.0
    price: float = 0.0
    ts: object = None
    stop_dist: float = 0.0


@dataclass
class Position:
    sym: str
    side: int
    entry: float
    qty: float
    qty0: float
    stop: float
    tp: float
    atr: float
    risk_usd: float
    r_unit: float                 # başlangıç stop mesafesi (fiyat)
    open_ts: object
    last_funding_k: int
    votes: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    bars_held: int = 0
    best: float = 0.0
    tp1_done: bool = False
    stop_kind: str = "STOP"       # STOP | BREAKEVEN | TRAIL
    entry_fee: float = 0.0
    funding: float = 0.0
    partial_realized: float = 0.0
    last_close: float = 0.0
    lev: int = 5

    @property
    def notional(self) -> float:
        return self.qty * self.entry


@dataclass
class Trade:
    sym: str
    side: int
    open_ts: str
    close_ts: str
    entry: float
    exit: float
    qty: float
    pnl: float                    # ücret + funding dahil net
    r_mult: float
    reason: str
    bars: int
    fees: float
    funding: float
    score: float
    votes: dict[str, float]
    lev: int = 5
