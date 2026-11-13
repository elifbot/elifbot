"""Yapılandırma: YAML yükleme, veri sınıfları ve doğrulama.

sentez-bot'un katı doğrulama fikri: bilinmeyen anahtar = hata; aralık dışı değer = hata.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml


@dataclass
class MarketCfg:
    symbols: list[str] = field(default_factory=lambda: ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"])
    timeframe: str = "15m"
    htf_timeframes: list[str] = field(default_factory=lambda: ["1h", "4h"])
    warmup: int = 400                 # sinyal için gereken minimum kapalı mum
    data_failover: list[str] = field(default_factory=lambda: ["binance", "okx", "bybit"])
    max_spread_bps: float = 8.0       # canlıda yayılma koruması
    funding_guard_sec: int = 600      # funding saatinden kaç saniye önce giriş yasak
    stale_sec: int = 120              # son mumdan bu kadar geçtiyse veri bayat


@dataclass
class StrategyCfg:
    score_threshold: float = 4.5      # ± puan eşiği (maks ±10.5)
    side_gap: float = 2.0             # karşı yöne en az bu fark (kontra-sinyal filtresi)
    # faktör ağırlıkları (toplam = 10.5 puan)
    w_ema: float = 1.5
    w_macd: float = 1.0
    w_rsi: float = 0.75
    w_adx: float = 1.0
    w_volume: float = 0.75
    w_vwap: float = 0.5
    w_supertrend: float = 0.75
    w_boll: float = 0.5
    # rejim eşikleri (FUSION_PRO)
    adx_trend: float = 20.0
    atrp_high: float = 1.8            # ATR/fiyat (YÜZDE) — yüksek oynaklık
    atrp_low: float = 0.12            # aşırı sakinlik (YÜZDE)
    th_high_vol: float = 0.5          # HIGH_VOL'da eşiğe eklenir
    th_range: float = 1.0             # RANGE'de eşiğe eklenir
    # vetolar
    max_chop: float = 62.0            # choppiness üst sınırı (sentez)
    volume_z_min: float = -0.5        # trend rejiminde hacim z-skoru vetosu
    min_bb_width_pct: float = 0.15    # bant sıkışması vetosu (%)
    min_edge_ratio: float = 2.0       # hedef hareket / gidiş-dönüş maliyet (sentez)
    rsi_len: int = 14
    adx_len: int = 14
    ema_fast: int = 20
    ema_mid: int = 50
    ema_slow: int = 200
    allow_short: bool = True


@dataclass
class RiskCfg:
    paper_equity: float = 10000.0
    risk_per_trade_pct: float = 0.5   # sermayenin %'si (işlem başına)
    leverage_base: int = 5            # taban kaldıraç (notional tavanı için)
    leverage_min: int = 2             # aşırı oynaklıkta düşen alt sınır (AcarBot fikri, güvenli sürüm)
    atrp_lev_high: float = 1.5        # ATR% (YÜZDE) üstünde kaldıraç düşer
    atrp_lev_extreme: float = 3.0     # ATR% (YÜZDE) üstünde alt kaldıraç
    max_notional_per_trade: float = 1000.0
    max_positions: int = 3
    max_same_side: int = 2
    max_gross_pct: float = 120.0      # toplam notional / sermaye
    min_liq_pct: float = 10.0         # tasfiye mesafesi alt sınırı (%)
    mmr: float = 0.005                # bakım marjı oranı (yaklaşım)
    margin_mode: str = "isolated"
    # devre kesici (sentez + AcarBot)
    daily_loss_pct: float = 3.0
    max_consec_losses: int = 4
    loss_pause_bars: int = 60
    equity_halt_pct: float = 25.0     # taban sermayeden %25 zarar = tam duruş
    cooldown_bars: int = 5
    # maliyet modeli (kötümser)
    taker_bps: float = 5.0
    slip_bps: float = 2.0
    spread_bps: float = 2.0
    funding_bps_8h: float = 1.0       # long öder varsayımı


@dataclass
class ExitCfg:
    stop_atr: float = 1.5
    tp_r: float = 2.0                 # hedef = risk mesafesinin katı
    tp1_r: float = 1.0                # kısmi kâr alma tetiği (FUSION_PRO)
    tp1_fraction: float = 0.35
    breakeven_r: float = 0.8
    trail_atr: float = 1.8
    max_hold_bars: int = 30


@dataclass
class ExecCfg:
    engine: str = "dry"               # dry | testnet | live
    testnet: bool = True
    leverage: int = 5
    loop_sec: int = 30
    state_file: str = "data/state.json"
    journal_file: str = "data/journal.jsonl"
    log_file: str = "data/bot.log"
    kill_file: str = "data/STOP"      # bu dosya varken yeni giriş yok (AcarBot /kill fikri)


@dataclass
class Config:
    market: MarketCfg = field(default_factory=MarketCfg)
    strategy: StrategyCfg = field(default_factory=StrategyCfg)
    risk: RiskCfg = field(default_factory=RiskCfg)
    exit: ExitCfg = field(default_factory=ExitCfg)
    exec: ExecCfg = field(default_factory=ExecCfg)

    def validate(self) -> "Config":
        s, r, x = self.strategy, self.risk, self.exit
        if not 1.0 <= s.score_threshold <= 10.5:
            raise ValueError("score_threshold 1..10.5 aralığında olmalı")
        if not 0 < r.risk_per_trade_pct <= 2.0:
            raise ValueError("risk_per_trade_pct (0, 2] olmalı")
        if x.stop_atr <= 0 or x.tp_r <= 0:
            raise ValueError("stop_atr ve tp_r pozitif olmalı")
        if not 1 <= r.leverage_base <= 10:
            raise ValueError("leverage_base 1..10 olmalı (güvenlik)")
        if x.tp1_fraction < 0 or x.tp1_fraction > 0.9:
            raise ValueError("tp1_fraction 0..0.9 olmalı")
        if self.exec.engine not in ("dry", "testnet", "live"):
            raise ValueError("exec.engine dry|testnet|live olmalı")
        if self.exec.engine == "live" and self.exec.testnet:
            raise ValueError("engine=live iken testnet=true olamaz")
        return self

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Config":
        top = {"market", "strategy", "risk", "exit", "exec"}
        unknown = set(d) - top
        if unknown:
            raise ValueError(f"bilinmeyen bölüm: {sorted(unknown)}")
        cfg = cls()
        for section in top:
            if section not in d:
                continue
            target = getattr(cfg, section)
            names = {f.name for f in fields(target)}
            bad = set(d[section]) - names
            if bad:
                raise ValueError(f"{section}: bilinmeyen anahtar {sorted(bad)}")
            for k, v in d[section].items():
                setattr(target, k, v)
        return cfg.validate()

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        with open(path, "r", encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
        return cls.from_dict(d)
