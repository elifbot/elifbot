"""Ortak veri modelleri ve ayarlar. Gerçek emir yolu yoktur; her şey sanal defterdir."""
from __future__ import annotations

from dataclasses import dataclass, field, fields, asdict


@dataclass(frozen=True)
class Bar:
    ts: int          # mumun açılış zamanı (ms, UTC)
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Signal:
    side: int                    # +1 long, -1 short
    score: int                   # oyların toplamı (işaretli)
    votes: dict[str, int]
    atr: float
    price: float                 # sinyal mumunun kapanışı
    ts: int                      # sinyal mumunun açılış zamanı


@dataclass
class Config:
    # --- sermaye ve boyutlandırma ---
    equity: float = 1000.0
    risk_pct: float = 0.5            # işlem başına risk (% sermaye)
    leverage: float = 5.0
    max_notional: float = 250.0      # işlem başına tavan
    min_notional: float = 10.0
    kelly: bool = False              # yarım-Kelly ile riski ölçekle (opsiyonel)
    kelly_min_trades: int = 20
    # --- portföy kapıları ---
    max_positions: int = 4
    max_same_side: int = 3
    max_gross_pct: float = 120.0     # toplam notional / sermaye (%)
    # --- maliyet modeli (iyimser değil) ---
    taker_bps: float = 5.0
    slip_bps: float = 2.0
    spread_bps: float = 2.0
    funding_bps_8h: float = 1.0      # sabit varsayım; long öder, short alır
    mmr: float = 0.005
    min_liq_pct: float = 10.0
    # --- zaman ---
    bar_ms: int = 900_000            # 15 dakika
    # --- sinyal ---
    conf_th: int = 4                 # 10 oydan eşik (2..8)
    max_chop: float = 62.0           # choppiness bu değerin üstündeyse işlem yok
    min_edge_ratio: float = 2.0      # hedef hareket / gidiş-dönüş maliyet; 0 = kapalı
    breadth_guard: float = 0.0       # 0 = kapalı; örn 0.35
    max_drift_atr: float = 0.5       # sinyal kapanışı ile dolum arası kaçak giriş sınırı
    # --- çıkış ---
    stop_atr: float = 1.2
    tp_atr: float = 2.4
    breakeven_r: float = 0.8
    trail_start_r: float = 1.0
    trail_atr: float = 1.0
    max_hold_bars: int = 30
    cooldown_bars: int = 5
    # --- devre kesici ---
    daily_loss_pct: float = 2.0
    max_consec_losses: int = 4
    loss_pause_bars: int = 60
    equity_halt_pct: float = 50.0

    def validate(self) -> "Config":
        if not 2 <= self.conf_th <= 8:
            self.conf_th = max(2, min(8, int(self.conf_th)))
        if self.equity <= 0 or self.risk_pct <= 0 or self.risk_pct > 5:
            raise ValueError("equity>0 ve 0<risk_pct<=5 olmalı")
        if self.stop_atr <= 0 or self.tp_atr <= 0:
            raise ValueError("stop_atr ve tp_atr pozitif olmalı")
        if self.leverage < 1:
            raise ValueError("leverage >= 1 olmalı")
        return self

    @classmethod
    def from_dict(cls, d: dict) -> "Config":
        names = {f.name for f in fields(cls)}
        unknown = set(d) - names
        if unknown:
            raise ValueError(f"bilinmeyen ayar: {sorted(unknown)}")
        return cls(**d).validate()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Position:
    sym: str
    side: int
    entry: float
    qty: float
    stop: float
    tp: float
    atr: float
    risk_usd: float
    r_unit: float                 # başlangıç stop mesafesi (fiyat)
    open_ts: int
    last_funding_k: int
    votes: dict[str, int] = field(default_factory=dict)
    score: int = 0
    bars_held: int = 0
    best: float = 0.0             # lehine en uç fiyat
    stop_kind: str = "STOP"       # STOP | BREAKEVEN | TRAIL
    entry_fee: float = 0.0
    funding: float = 0.0
    last_close: float = 0.0

    @property
    def notional(self) -> float:
        return self.qty * self.entry


@dataclass
class Trade:
    sym: str
    side: int
    open_ts: int
    close_ts: int
    entry: float
    exit: float
    qty: float
    pnl: float                    # ücret ve funding düşülmüş net
    r_mult: float
    reason: str
    bars: int
    fees: float
    funding: float
    score: int
    votes: dict[str, int]
