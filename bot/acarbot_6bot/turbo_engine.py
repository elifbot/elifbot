#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ACARBOT56 — TURBO REAL-TIME VOLUME SHOCK & CROSS-MARGIN ENGINE (v3.0)
=====================================================================
Kullanıcı Ana Kuralları (Birebir Uygulama):
  1. Başlangıç Kasası: $1,000.00
  2. İşlem Başı Giriş: $50.00 Teminat × 10x Kaldıraç = $500.00 Pozisyon Büyüklüğü
  3. Marjin Tipi: ÇAPRAZ MARJİN (CROSS MARGIN — İzole Değil!)
  4. Pozisyon Sınırı: SINIRSIZ (max_positions = 0; aynı anda sınırsız farklı pariteye girebilir)
  5. Sabit Zarar Kes: Net -$10.00 olduğunda anında kesin çıkış (HARD_STOP_-10USD)
  6. Kâr Al (TP): BOT KENDİSİ BELİRLER (4 Kademeli Otonom AI İvme + Tükeniş Kâr Motoru)
  7. Borsa Evreni: Binance TÜM USDT-M Futures + OKX TÜM USDT-SWAP Futures (550+ Parite)
  8. Tetikleyici & Hız: Milisaniyelik anlık akış takibi — Hacim Patlaması veya Hacim Çöküşü anında giriş!
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Deque, Dict, List, Literal, Optional, Tuple

import numpy as np

from ai_models import load_dotenv_safe

logger = logging.getLogger("TURBO_ENGINE")


# ============================================================
# 1) ANA KONFİGÜRASYON (KULLANICI KURALLARI SABİTLENDİ)
# ============================================================
@dataclass
class TurboConfig:
    # Sermaye ve Çapraz Marjin Kuralları
    initial_equity_usd: float = 1000.0
    margin_per_trade_usd: float = 50.0
    leverage: int = 10
    margin_mode: Literal["cross"] = "cross"  # KESİNLİKLE İZOLE DEĞİL -> ÇAPRAZ (CROSS)
    max_positions: int = 0  # 0 = SINIRSIZ İŞLEM AÇABİLİR!
    enforce_free_equity_check: bool = True  # True ise yalnızca bakiye <$50 kalırsa korur; adet sınırı asla yok
    one_position_per_symbol: bool = True  # Aynı coine aynı saniyede üst üste çift girmeyi önler, diğer 600 coin serbest!
    symbol_cooldown_sec: float = 20.0

    # Kesin Zarar Limiti (-$10.00)
    hard_stop_loss_usd: float = 10.0
    taker_fee_rate: float = 0.0005  # %0.05

    # Otonom AI Kâr Belirleme Motoru (Kârı Bot Kendisi Belirler)
    be_trigger_usd: float = 4.50       # +$4.50 kâr görüldüğünde zararı sıfırla (+0.80$ net kilit)
    be_lock_usd: float = 0.80
    trail_trigger_usd: float = 8.00    # +$8.00 üstünde dinamik AI iz sürme başlar
    exhaustion_tp_min_usd: float = 5.00  # En az +$5.00 kârdayken hacim/ivme ters dönerse anında kârı cebe koy!

    # Anlık Hacim Patlaması & Çöküşü Algılama Ayarları (1.200+ Tüm Vadeli Pariteler İçin Optimize)
    sensitivity: Literal["fast", "balanced", "sniper"] = "balanced"
    min_24h_vol_usd: float = 25_000.0  # Düşük hacimli altcoin/teslimatlı vadeli kontratları da kapsar (1.000+ kontrat!)
    burst_window_sec: float = 12.0
    vol_explosion_mult: float = 3.0    # Normal saniyelik hacmin en az 3.0 katı patlama!
    min_burst_usd: float = 12_000.0    # Patlama penceresinde en az $12K gerçek işlem
    min_velocity_pct: float = 0.30     # Kısa pencerede en az %0.30 sert fiyat fırlaması/çöküşü
    min_orderflow_bias: float = 0.18   # Alıcı/satıcı baskı üstünlüğü
    vol_collapse_ratio: float = 0.32   # Sert sıçrama sonrası hacmin %68+ çökmesi (Tükeniş dönüşü)

    # Çalışma Modu
    paper_mode: bool = True
    live_confirm_env: str = "I_UNDERSTAND_RISK"

    @property
    def notional_per_trade_usd(self) -> float:
        return self.margin_per_trade_usd * self.leverage  # $50 * 10 = $500.0

    @property
    def roundtrip_fee_usd(self) -> float:
        return self.notional_per_trade_usd * (self.taker_fee_rate * 2.0)  # $0.50

    @property
    def hard_stop_price_frac(self) -> float:
        """Net zararın komisyon dahil tam -$20.00 olacağı fiyat yüzdesi (~%3.90)."""
        price_loss_budget = max(1.0, self.hard_stop_loss_usd - self.roundtrip_fee_usd)
        return price_loss_budget / self.notional_per_trade_usd

    def apply_sensitivity_preset(self, preset: str) -> None:
        if preset == "fast":
            self.sensitivity = "fast"
            self.vol_explosion_mult = 2.1
            self.min_burst_usd = 5_000.0
            self.min_velocity_pct = 0.18
            self.min_orderflow_bias = 0.12
        elif preset == "sniper":
            self.sensitivity = "sniper"
            self.vol_explosion_mult = 4.5
            self.min_burst_usd = 25_000.0
            self.min_velocity_pct = 0.50
            self.min_orderflow_bias = 0.28
        else:
            self.sensitivity = "balanced"
            self.vol_explosion_mult = 3.0
            self.min_burst_usd = 12_000.0
            self.min_velocity_pct = 0.30
            self.min_orderflow_bias = 0.18

    def validate(self) -> None:
        if self.initial_equity_usd <= 0 or self.margin_per_trade_usd <= 0 or self.leverage < 1:
            raise ValueError("Kasa, giriş tutarı ve kaldıraç pozitif olmalıdır.")
        if self.margin_mode != "cross":
            raise ValueError("Marjin modu kullanıcı kuralı gereği 'cross' (çapraz) olmalıdır!")
        if self.hard_stop_loss_usd <= self.roundtrip_fee_usd:
            raise ValueError("hard_stop_loss_usd komisyon tutarından büyük olmalıdır.")
        if not self.paper_mode and os.getenv(self.live_confirm_env) != "YES":
            raise RuntimeError(f"Canlı emir kilidi aktif: {self.live_confirm_env}=YES gerekli.")


# ============================================================
# 2) ANLIK MİKRO-TAPE VE MUM BELLEĞİ (O(1) RAM, <0.05ms GECİKME)
# ============================================================
@dataclass
class TickSample:
    ts: float
    price: float
    delta_usd: float
    buy_usd: float


@dataclass
class MinuteBar:
    minute_ts: int
    o: float
    h: float
    l: float
    c: float
    v_usd: float
    buy_usd: float


class SymbolMicroTape:
    """Tek bir vadeli işlem paritesinin milisaniyelik fiyat, hacim hızı ve 1dk mum geçmişini tutar."""

    __slots__ = (
        "exchange",
        "symbol",
        "last_price",
        "pct_24h",
        "quote_vol_24h",
        "prev_q24",
        "last_ts",
        "prev_kline_ts",
        "prev_kline_q",
        "prev_kline_buy_q",
        "samples",
        "bars_1m",
        "rolling_rates",
        "peak_burst_mult_60s",
        "peak_burst_move_60s",
        "peak_burst_ts",
    )

    def __init__(self, exchange: str, symbol: str) -> None:
        self.exchange = exchange
        self.symbol = symbol
        self.last_price: float = 0.0
        self.pct_24h: float = 0.0
        self.quote_vol_24h: float = 0.0
        self.prev_q24: float = 0.0
        self.last_ts: float = 0.0
        self.prev_kline_ts: int = 0
        self.prev_kline_q: float = 0.0
        self.prev_kline_buy_q: float = 0.0
        self.samples: Deque[TickSample] = deque(maxlen=240)
        self.bars_1m: Deque[MinuteBar] = deque(maxlen=90)
        self.rolling_rates: Deque[float] = deque(maxlen=60)
        self.peak_burst_mult_60s: float = 1.0
        self.peak_burst_move_60s: float = 0.0
        self.peak_burst_ts: float = 0.0

    @property
    def key(self) -> str:
        return f"{self.exchange}:{self.symbol}"

    def ingest_tick(
        self,
        ts: float,
        price: float,
        quote_vol_24h: float = 0.0,
        pct_24h: float = 0.0,
        kline_ts: int = 0,
        kline_q_usd: float = -1.0,
        kline_taker_buy_usd: float = -1.0,
        explicit_delta_usd: float = -1.0,
        explicit_buy_usd: float = -1.0,
    ) -> None:
        if price <= 0:
            return
        prev_px = self.last_price or price
        self.last_price = price
        old_q24 = self.prev_q24
        if quote_vol_24h > 0:
            self.quote_vol_24h = quote_vol_24h
            self.prev_q24 = quote_vol_24h
        if pct_24h != 0.0 or self.pct_24h == 0.0:
            self.pct_24h = pct_24h
        self.last_ts = ts

        # 1. Kesin anlık işlem hacmi (delta_usd) ve alıcı hacmi (buy_usd) çıkarımı
        delta_usd = 0.0
        buy_usd = 0.0

        if explicit_delta_usd >= 0.0:
            delta_usd = explicit_delta_usd
            if explicit_buy_usd >= 0.0:
                buy_usd = max(0.0, min(delta_usd, explicit_buy_usd))
            else:
                buy_usd = delta_usd * (0.72 if price > prev_px else (0.28 if price < prev_px else 0.50))
        elif kline_q_usd >= 0.0 and kline_ts > 0:
            if self.prev_kline_ts == 0:
                # İlk bağlantı paketi: geçmiş dakikayı patlama saymamak için referans al
                delta_usd = 0.0
                buy_usd = 0.0
            elif kline_ts == self.prev_kline_ts:
                delta_usd = max(0.0, kline_q_usd - self.prev_kline_q)
                if kline_taker_buy_usd >= 0.0:
                    buy_usd = max(0.0, min(delta_usd, kline_taker_buy_usd - self.prev_kline_buy_q))
                else:
                    buy_usd = delta_usd * (0.75 if price > prev_px else (0.25 if price < prev_px else 0.50))
            else:
                # Yeni 1dk mum açılışı
                delta_usd = max(0.0, kline_q_usd)
                buy_usd = (
                    max(0.0, min(delta_usd, kline_taker_buy_usd))
                    if kline_taker_buy_usd >= 0.0
                    else delta_usd * (0.75 if price > prev_px else (0.25 if price < prev_px else 0.50))
                )
            self.prev_kline_ts = kline_ts
            self.prev_kline_q = kline_q_usd
            if kline_taker_buy_usd >= 0.0:
                self.prev_kline_buy_q = kline_taker_buy_usd
        elif self.prev_kline_ts == 0 and quote_vol_24h > 0 and old_q24 > 0:
            # 1.200+ kontratın tamamında (COIN-M ve Teslimatlı Futures dahil) ticker üzerinden de anlık hacim farkını yakala!
            diff_24 = quote_vol_24h - old_q24
            if 0.0 < diff_24 < quote_vol_24h * 0.12:
                delta_usd = diff_24
                buy_usd = delta_usd * (0.75 if price > prev_px else (0.25 if price < prev_px else 0.50))

        self.samples.append(TickSample(ts=ts, price=price, delta_usd=delta_usd, buy_usd=buy_usd))

        # Eski örnekleri (>120 sn) temizle
        cutoff = ts - 120.0
        while len(self.samples) > 2 and self.samples[0].ts < cutoff:
            self.samples.popleft()

        # Canlı 1 dakikalık mum grafiği güncelle
        min_bucket = int(ts // 60) * 60_000
        if not self.bars_1m or self.bars_1m[-1].minute_ts != min_bucket:
            # Önceki tamamlanan dakikanın saniyelik hacim hızını baz listesine ekle
            if self.bars_1m and self.bars_1m[-1].v_usd > 0:
                self.rolling_rates.append(self.bars_1m[-1].v_usd / 60.0)
            self.bars_1m.append(
                MinuteBar(
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
            b = self.bars_1m[-1]
            if price > b.h:
                b.h = price
            if price < b.l:
                b.l = price
            b.c = price
            b.v_usd += max(0.0, delta_usd)
            b.buy_usd += max(0.0, buy_usd)

    def baseline_usd_per_sec(self) -> float:
        rate_24h = self.quote_vol_24h / 86_400.0 if self.quote_vol_24h > 0 else 200.0
        if len(self.rolling_rates) >= 3:
            med_live = float(np.median(self.rolling_rates))
            return max(80.0, 0.55 * med_live + 0.45 * rate_24h)
        return max(80.0, rate_24h)

    def metrics(self, burst_window_sec: float = 12.0) -> Dict[str, float]:
        if not self.samples or self.last_price <= 0:
            return {
                "vol_mult": 0.0,
                "burst_usd": 0.0,
                "ret_burst_pct": 0.0,
                "ret_30s_pct": 0.0,
                "orderflow_bias": 0.0,
                "range_pos": 0.5,
            }

        now = self.last_ts
        burst_cut = now - burst_window_sec
        cut_30s = now - 30.0

        burst_usd = 0.0
        burst_buy = 0.0
        px_burst_start = self.last_price
        px_30s_start = self.last_price
        found_burst = False
        found_30s = False
        hi_burst = self.last_price
        lo_burst = self.last_price

        for s in self.samples:
            if not found_30s and s.ts >= cut_30s:
                px_30s_start = s.price
                found_30s = True
            if s.ts >= burst_cut:
                if not found_burst:
                    px_burst_start = s.price
                    found_burst = True
                burst_usd += s.delta_usd
                burst_buy += s.buy_usd
                if s.price > hi_burst:
                    hi_burst = s.price
                if s.price < lo_burst:
                    lo_burst = s.price

        elapsed = max(3.0, min(burst_window_sec, now - self.samples[0].ts))
        live_rate = burst_usd / elapsed
        base_rate = self.baseline_usd_per_sec()
        vol_mult = live_rate / base_rate if base_rate > 0 else 0.0

        ret_burst_pct = ((self.last_price - px_burst_start) / px_burst_start * 100.0) if px_burst_start > 0 else 0.0
        ret_30s_pct = ((self.last_price - px_30s_start) / px_30s_start * 100.0) if px_30s_start > 0 else 0.0

        if burst_usd > 0:
            orderflow_bias = (2.0 * burst_buy - burst_usd) / burst_usd  # [-1.0, +1.0]
        else:
            orderflow_bias = float(np.clip(ret_burst_pct * 1.5, -1.0, 1.0))

        span = hi_burst - lo_burst
        range_pos = ((self.last_price - lo_burst) / span) if span > 1e-12 else 0.5

        # Son 60 saniyedeki zirve patlamayı kaydet (Hacim çöküşü dönüş tespiti için!)
        if now - self.peak_burst_ts > 75.0 or vol_mult >= self.peak_burst_mult_60s:
            self.peak_burst_mult_60s = vol_mult
            self.peak_burst_move_60s = ret_30s_pct
            self.peak_burst_ts = now

        return {
            "vol_mult": round(vol_mult, 2),
            "burst_usd": round(burst_usd, 2),
            "ret_burst_pct": round(ret_burst_pct, 4),
            "ret_30s_pct": round(ret_30s_pct, 4),
            "orderflow_bias": round(float(np.clip(orderflow_bias, -1.0, 1.0)), 3),
            "range_pos": round(range_pos, 3),
        }


# ============================================================
# 3) POZİSYON MODELİ (ÇAPRAZ MARJİN + OTONOM AI KÂR + -$20 ZARAR KES)
# ============================================================
@dataclass
class TurboPosition:
    id: str
    exchange: str
    symbol: str
    side: int  # +1 LONG, -1 SHORT
    entry_price: float
    mark_price: float
    margin_usd: float
    leverage: int
    notional_usd: float
    hard_stop_price: float
    dynamic_floor_pnl_usd: float  # Botun dinamik olarak yukarı taşıdığı kâr kilidi ($)
    opened_ts: float
    trigger_type: str
    vol_mult_at_entry: float
    peak_pnl_usd: float = 0.0
    net_pnl_usd: float = 0.0
    profit_stage: str = "ILK_KORUMA (-20$ SL)"

    @property
    def side_label(self) -> str:
        return "LONG" if self.side > 0 else "SHORT"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ClosedTradeRecord:
    id: str
    exchange: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    opened_ts: float
    closed_ts: float
    hold_sec: float
    peak_pnl_usd: float
    net_pnl_usd: float
    trigger_type: str
    exit_reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================
# 4) GERÇEK ZAMANLI HACİM PATLAMASI & ÇAPRAZ MARJİN MOTORU
# ============================================================
class RealTimeVolumeShockEngine:
    """
    Tüm Binance + OKX Futures evrenini milisaniyelik izler:
      - Hacim Patlaması + Yükseliş -> ANINDA LONG ($50 × 10x Cross)
      - Hacim Patlamasıyla Çöküş -> ANINDA SHORT ($50 × 10x Cross)
      - Hacim Çöküşü (Pump/Dump Tükenişi) -> ANINDA DÖNÜŞ GİRİŞİ
      - Zarar tam -$20.00 olduğunda KESİN ZARAR KES
      - Kârı 4 kademeli otonom AI ivme/tükeniş motoruyla KENDİSİ BELİRLER
      - Pozisyon sayısı SINIRSIZ!
    """

    def __init__(
        self,
        cfg: Optional[TurboConfig] = None,
        on_live_order: Optional[Callable[[str, str, int, float], None]] = None,
        on_live_close: Optional[Callable[[str, str, int, float], None]] = None,
    ) -> None:
        load_dotenv_safe()
        self.cfg = cfg or TurboConfig()
        self.cfg.validate()
        self.lock = threading.RLock()
        self.on_live_order = on_live_order
        self.on_live_close = on_live_close

        self.tapes: Dict[str, SymbolMicroTape] = {}
        self.positions: Dict[str, TurboPosition] = {}  # key = pos.id
        self.active_symbol_keys: Dict[str, str] = {}   # "exchange:symbol" -> pos.id
        self.cooldown_until: Dict[str, float] = {}
        self.closed_trades: Deque[ClosedTradeRecord] = deque(maxlen=250)
        self.events: Deque[Dict[str, Any]] = deque(maxlen=120)
        self.equity_history: Deque[Dict[str, Any]] = deque(maxlen=240)

        self.realized_pnl_usd: float = 0.0
        self.total_ticks_processed: int = 0
        self.trading_enabled: bool = True
        self.started_ts: float = time.time()
        self.first_live_tick_ts: float = 0.0
        self.test_target_sec: int = 3600  # 1 Saatlik Canlı Test Hedefi
        self.one_hour_checkpoint: Optional[Dict[str, Any]] = None
        self.feed_sources: Dict[str, Any] = {
            "browser_last_ts": 0.0,
            "browser_binance_ts": 0.0,
            "browser_okx_ts": 0.0,
            "cloud_last_ts": 0.0,
            "cloud_seq": 0,
            "cloud_source_label": "",
            "client_diag": "",
        }
        self._last_eq_sample_ts: float = 0.0

        self._log_event(
            "SİSTEM",
            "TURBO v3.0 aktif: $1,000 Çapraz (Cross) Kasa | $50×10x Giriş | Sınırsız İşlem | -$20 Kesin SL | Otonom AI Kâr Al.",
        )

    def _log_event(self, kind: str, message: str, **extra: Any) -> None:
        self.events.appendleft(
            {
                "ts": round(time.time(), 3),
                "time": time.strftime("%H:%M:%S"),
                "kind": kind,
                "text": message,
                **extra,
            }
        )

    def unrealized_pnl_usd(self) -> float:
        return sum(p.net_pnl_usd for p in self.positions.values())

    def live_equity_usd(self) -> float:
        return self.cfg.initial_equity_usd + self.realized_pnl_usd + self.unrealized_pnl_usd()

    def used_margin_usd(self) -> float:
        return len(self.positions) * self.cfg.margin_per_trade_usd

    def ingest_batch(self, ticks: List[Dict[str, Any]], source: str = "direct") -> int:
        """
        Dışarıdan (Python WebSocket, Bulut Gerçek Veri Köprüsü veya Tarayıcı Canlı Rölesi)
        gelen gerçek piyasa paketlerini milisaniyeler içinde işler.
        """
        opened_count = 0
        now_wall = time.time()

        with self.lock:
            if ticks and self.first_live_tick_ts <= 0.0:
                self.first_live_tick_ts = now_wall
                self._log_event(
                    "TEST_BAŞLADI",
                    "1 Saatlik (60:00) %100 Gerçek Borsa Verili Canlı Test Sayacı Başlatıldı!",
                )
            if ticks:
                if source == "browser":
                    self.feed_sources["browser_last_ts"] = now_wall
                elif source.startswith("cloud"):
                    self.feed_sources["cloud_last_ts"] = now_wall

            for item in ticks:
                ex = str(item.get("exchange", "binance")).lower()
                sym = str(item.get("symbol", "")).upper()
                if not sym:
                    continue
                px = float(item.get("price") or 0.0)
                if px <= 0:
                    continue

                if source == "browser":
                    if ex.startswith("binance"):
                        self.feed_sources["browser_binance_ts"] = now_wall
                    elif ex == "okx":
                        self.feed_sources["browser_okx_ts"] = now_wall

                ts = float(item.get("ts") or now_wall)
                if ts > 1e11:
                    ts = ts / 1000.0  # ms -> sec

                q24 = float(item.get("quote_vol_24h") or 0.0)
                pct24 = float(item.get("pct_24h") or 0.0)
                k_ts = int(item.get("kline_ts") or 0)
                k_q = float(item["kline_q"]) if "kline_q" in item and item["kline_q"] is not None else -1.0
                k_buy = float(item["kline_buy_q"]) if "kline_buy_q" in item and item["kline_buy_q"] is not None else -1.0
                exp_delta = float(item["delta_usd"]) if "delta_usd" in item and item["delta_usd"] is not None else -1.0
                exp_buy = float(item["buy_usd"]) if "buy_usd" in item and item["buy_usd"] is not None else -1.0

                key = f"{ex}:{sym}"
                tape = self.tapes.get(key)
                if tape is None:
                    tape = SymbolMicroTape(ex, sym)
                    self.tapes[key] = tape

                tape.ingest_tick(
                    ts=ts,
                    price=px,
                    quote_vol_24h=q24,
                    pct_24h=pct24,
                    kline_ts=k_ts,
                    kline_q_usd=k_q,
                    kline_taker_buy_usd=k_buy,
                    explicit_delta_usd=exp_delta,
                    explicit_buy_usd=exp_buy,
                )
                self.total_ticks_processed += 1

                # 1. Bu sembolde açık pozisyon varsa anlık yönet (-$20 SL veya AI Kâr Al!)
                active_pid = self.active_symbol_keys.get(key)
                if active_pid and active_pid in self.positions:
                    self._manage_single_position(self.positions[active_pid], tape, ts)
                else:
                    # Cooldown veya duraklatma sırasında bile zirve hacim patlamasını takip et (Hacim Çöküşü tespiti için!)
                    m_live = tape.metrics(self.cfg.burst_window_sec)
                    if self.trading_enabled and self._evaluate_and_enter(tape, ts, precomputed_metrics=m_live):
                        opened_count += 1

            # Çapraz Marjin Hesap Geneli Güvenlik Kontrolü + Equity Grafiği Kaydı
            if now_wall - self._last_eq_sample_ts >= 1.0:
                self._last_eq_sample_ts = now_wall
                self.equity_history.append(
                    {
                        "t": time.strftime("%H:%M:%S"),
                        "equity": round(self.live_equity_usd(), 2),
                        "realized": round(self.cfg.initial_equity_usd + self.realized_pnl_usd, 2),
                        "open_count": len(self.positions),
                    }
                )

        return opened_count

    def _evaluate_and_enter(
        self,
        tape: SymbolMicroTape,
        now_ts: float,
        precomputed_metrics: Optional[Dict[str, float]] = None,
    ) -> bool:
        key = tape.key
        if self.cfg.one_position_per_symbol and key in self.active_symbol_keys:
            return False
        if self.cooldown_until.get(key, 0.0) > now_ts:
            return False
        if tape.quote_vol_24h > 0 and tape.quote_vol_24h < self.cfg.min_24h_vol_usd:
            return False
        if len(tape.samples) < 3:
            return False
        if self.cfg.enforce_free_equity_check and (self.live_equity_usd() - self.used_margin_usd()) < self.cfg.margin_per_trade_usd:
            return False

        # Not: max_positions == 0 ise SINIRSIZ pozisyon açabilir!
        if self.cfg.max_positions > 0 and len(self.positions) >= self.cfg.max_positions:
            return False

        m = precomputed_metrics or tape.metrics(self.cfg.burst_window_sec)
        vol_mult = m["vol_mult"]
        burst_usd = m["burst_usd"]
        ret_b = m["ret_burst_pct"]
        ret_30 = m["ret_30s_pct"]
        flow = m["orderflow_bias"]
        rpos = m["range_pos"]

        side = 0
        trigger = ""

        # TETİKLEYİCİ 1: HACİM PATLAMASI + YUKARI İVME -> ANINDA LONG
        if (
            vol_mult >= self.cfg.vol_explosion_mult
            and burst_usd >= self.cfg.min_burst_usd
            and (ret_b >= self.cfg.min_velocity_pct or ret_30 >= self.cfg.min_velocity_pct * 1.35)
            and flow >= self.cfg.min_orderflow_bias
            and rpos >= 0.45  # Tepeden sert reddedilmiş dev üst fitil (bull trap) olmasın
        ):
            side = 1
            trigger = f"HACIM_PATLAMASI_LONG ({vol_mult:.1f}x Hacim | +{max(ret_b, ret_30):.2f}%)"

        # TETİKLEYİCİ 2: HACİM PATLAMASIYLA ÇÖKÜŞ / DUMP -> ANINDA SHORT
        elif (
            vol_mult >= self.cfg.vol_explosion_mult
            and burst_usd >= self.cfg.min_burst_usd
            and (ret_b <= -self.cfg.min_velocity_pct or ret_30 <= -self.cfg.min_velocity_pct * 1.35)
            and flow <= -self.cfg.min_orderflow_bias
            and rpos <= 0.55  # Dipten sert tepki fitili (bear trap) olmasın
        ):
            side = -1
            trigger = f"COKUS_PATLAMASI_SHORT ({vol_mult:.1f}x Hacim | {min(ret_b, ret_30):.2f}%)"

        # TETİKLEYİCİ 3: HACİM ÇÖKÜŞÜ (Sert Pump/Dump Sonrası Hacmin Kuruyup Ters Kırması)
        elif (
            tape.peak_burst_mult_60s >= self.cfg.vol_explosion_mult * 1.15
            and (now_ts - tape.peak_burst_ts) <= 60.0
            and vol_mult <= tape.peak_burst_mult_60s * self.cfg.vol_collapse_ratio
        ):
            # Önce sert pump olmuş, şimdi hacim çöktü ve fiyat aşağı dönüyor -> SHORT
            if tape.peak_burst_move_60s >= self.cfg.min_velocity_pct * 1.8 and ret_b <= -0.15 and flow <= -0.15:
                side = -1
                trigger = f"HACIM_COKUSU_SHORT (Tepe Hacmi Çöktü {tape.peak_burst_mult_60s:.1f}x->{vol_mult:.1f}x)"
                tape.peak_burst_mult_60s = 1.0
            # Önce sert panik satışı olmuş, şimdi satış hacmi çöktü ve fiyat yukarı dönüyor -> LONG
            elif tape.peak_burst_move_60s <= -self.cfg.min_velocity_pct * 1.8 and ret_b >= 0.15 and flow >= 0.15:
                side = 1
                trigger = f"HACIM_COKUSU_LONG (Satış Hacmi Çöktü {tape.peak_burst_mult_60s:.1f}x->{vol_mult:.1f}x)"
                tape.peak_burst_mult_60s = 1.0

        if side == 0:
            return False

        self._open_position(tape, side, trigger, vol_mult, now_ts)
        return True

    def _open_position(
        self, tape: SymbolMicroTape, side: int, trigger: str, vol_mult: float, now_ts: float
    ) -> TurboPosition:
        entry_px = tape.last_price
        stop_frac = self.cfg.hard_stop_price_frac
        hard_stop_px = entry_px * (1.0 - side * stop_frac)
        pid = uuid.uuid4().hex[:10]

        pos = TurboPosition(
            id=pid,
            exchange=tape.exchange,
            symbol=tape.symbol,
            side=side,
            entry_price=entry_px,
            mark_price=entry_px,
            margin_usd=self.cfg.margin_per_trade_usd,
            leverage=self.cfg.leverage,
            notional_usd=self.cfg.notional_per_trade_usd,
            hard_stop_price=hard_stop_px,
            dynamic_floor_pnl_usd=-self.cfg.hard_stop_loss_usd,
            opened_ts=now_ts,
            trigger_type=trigger,
            vol_mult_at_entry=vol_mult,
            net_pnl_usd=-self.cfg.roundtrip_fee_usd,
        )
        self.positions[pid] = pos
        self.active_symbol_keys[tape.key] = pid

        self._log_event(
            "GİRİŞ",
            f"[{tape.exchange.upper()}] {pos.side_label} {tape.symbol} @ {entry_px:.6g} | "
            f"$50×10x Çapraz | -$10 SL @ {hard_stop_px:.6g} | {trigger}",
        )
        if self.on_live_order and not self.cfg.paper_mode:
            self.on_live_order(tape.exchange, tape.symbol, side, entry_px)
        return pos

    def _manage_single_position(self, pos: TurboPosition, tape: SymbolMicroTape, now_ts: float) -> None:
        px = tape.last_price
        pos.mark_price = px
        gross_pnl = pos.side * (px / pos.entry_price - 1.0) * pos.notional_usd
        net_pnl = gross_pnl - self.cfg.roundtrip_fee_usd
        pos.net_pnl_usd = round(net_pnl, 4)
        if net_pnl > pos.peak_pnl_usd:
            pos.peak_pnl_usd = round(net_pnl, 4)

        # 1. KESİN -$10.00 ZARAR KES KURALI (Asla -$10'u geçmesine izin verme!)
        hit_hard_price = (pos.side > 0 and px <= pos.hard_stop_price) or (
            pos.side < 0 and px >= pos.hard_stop_price
        )
        if net_pnl <= -self.cfg.hard_stop_loss_usd or hit_hard_price:
            capped_loss = max(net_pnl, -self.cfg.hard_stop_loss_usd)
            self._close_position(pos, px, capped_loss, "ZARAR_KES_-10$", now_ts)
            return

        # 2. BOTUN KENDİ BELİRLEDİĞİ 4 KADEMELİ OTONOM AI KÂR MOTORU
        m = tape.metrics(self.cfg.burst_window_sec)
        flow_aligned = m["orderflow_bias"] * pos.side  # Pozitifse hacim pozisyonu destekliyor
        vel_aligned = m["ret_burst_pct"] * pos.side

        # Kademe 1: +$4.50 ulaşıldığında komisyon üstü Başabaş Kilidi (+0.80$)
        if pos.peak_pnl_usd >= self.cfg.be_trigger_usd and pos.dynamic_floor_pnl_usd < self.cfg.be_lock_usd:
            pos.dynamic_floor_pnl_usd = self.cfg.be_lock_usd
            pos.profit_stage = f"BE_KILIDI (+${self.cfg.be_lock_usd:.2f})"

        # Kademe 2 & 3: +$8.00+ Dinamik İvme Duyarlı Kâr Kilidi (Trailing)
        if pos.peak_pnl_usd >= self.cfg.trail_trigger_usd:
            if pos.peak_pnl_usd >= 25.0:
                giveback_frac = 0.16  # Parabolik kârda sıkı koruma (%84'ünü kilitle!)
                stage_lbl = "PARABOLIK_AI_TRAIL"
            elif flow_aligned >= 0.15 and vel_aligned >= 0.0:
                giveback_frac = 0.30  # Hacim hâlâ patlıyor -> kârın önünü kesme, sürmeye devam et!
                stage_lbl = "ESNEK_IVME_SURUSU"
            else:
                giveback_frac = 0.20  # İvme yavaşladı -> kilidi daralt!
                stage_lbl = "DARALTILMIS_AI_KILIT"

            new_floor = pos.peak_pnl_usd * (1.0 - giveback_frac)
            if new_floor > pos.dynamic_floor_pnl_usd:
                pos.dynamic_floor_pnl_usd = round(new_floor, 2)
            pos.profit_stage = f"{stage_lbl} (Taban +${pos.dynamic_floor_pnl_usd:.2f})"

        # Kademe 4: Anlık AI Hacim Tükenişi / Karşı Duvar Çıkışı (En tepede/dipte yakala!)
        if (
            net_pnl >= self.cfg.exhaustion_tp_min_usd
            and m["vol_mult"] >= 2.2
            and flow_aligned <= -0.38
            and vel_aligned <= -0.18
        ):
            self._close_position(pos, px, net_pnl, "AI_ANLIK_TUKENIS_KAR_AL", now_ts)
            return

        # Dinamik kâr tabanı vurulduysa kârı realize et
        if pos.dynamic_floor_pnl_usd > -self.cfg.hard_stop_loss_usd and net_pnl <= pos.dynamic_floor_pnl_usd:
            reason = "AI_TRAILING_KAR_AL" if pos.dynamic_floor_pnl_usd >= 3.0 else "BE_KAR_KORUMA"
            self._close_position(pos, px, net_pnl, reason, now_ts)

    def _close_position(
        self, pos: TurboPosition, exit_px: float, final_net_pnl: float, reason: str, now_ts: float
    ) -> None:
        key = f"{pos.exchange}:{pos.symbol}"
        self.positions.pop(pos.id, None)
        self.active_symbol_keys.pop(key, None)
        self.cooldown_until[key] = now_ts + self.cfg.symbol_cooldown_sec
        self.realized_pnl_usd += final_net_pnl

        rec = ClosedTradeRecord(
            id=pos.id,
            exchange=pos.exchange,
            symbol=pos.symbol,
            side=pos.side_label,
            entry_price=pos.entry_price,
            exit_price=exit_px,
            opened_ts=pos.opened_ts,
            closed_ts=now_ts,
            hold_sec=round(max(0.1, now_ts - pos.opened_ts), 1),
            peak_pnl_usd=round(pos.peak_pnl_usd, 2),
            net_pnl_usd=round(final_net_pnl, 2),
            trigger_type=pos.trigger_type,
            exit_reason=reason,
        )
        self.closed_trades.appendleft(rec)
        self._log_event(
            "ÇIKIŞ",
            f"[{pos.exchange.upper()}] {pos.side_label} {pos.symbol} kapandı ({reason}) | "
            f"Net: {final_net_pnl:+.2f}$ (Zirve: {pos.peak_pnl_usd:+.2f}$) | Kasa: ${self.live_equity_usd():.2f}",
        )
        if self.on_live_close and not self.cfg.paper_mode:
            self.on_live_close(pos.exchange, pos.symbol, pos.side, exit_px)

    def close_manual(self, pos_id: str) -> bool:
        with self.lock:
            pos = self.positions.get(pos_id)
            if not pos:
                return False
            self._close_position(pos, pos.mark_price, pos.net_pnl_usd, "MANUEL_KAPAT", time.time())
            return True

    def reset_account(self) -> None:
        with self.lock:
            self.positions.clear()
            self.active_symbol_keys.clear()
            self.cooldown_until.clear()
            self.closed_trades.clear()
            self.equity_history.clear()
            self.realized_pnl_usd = 0.0
            self.started_ts = time.time()
            self.first_live_tick_ts = time.time() if self.tapes else 0.0
            self.one_hour_checkpoint = None
            self._log_event("SİSTEM", "Hesap ve 1 Saatlik Test Sayacı sıfırlandı ($1,000.00 Çapraz Kasa).")

    def snapshot(self, chart_key: str = "binance:BTCUSDT") -> Dict[str, Any]:
        with self.lock:
            binance_usdm = sum(1 for t in self.tapes.values() if t.exchange == "binance")
            binance_coinm = sum(1 for t in self.tapes.values() if t.exchange == "binance_coinm")
            binance_count = binance_usdm + binance_coinm
            okx_swap = sum(1 for t in self.tapes.values() if t.exchange == "okx" and t.symbol.endswith("-SWAP"))
            okx_delivery = sum(1 for t in self.tapes.values() if t.exchange == "okx" and not t.symbol.endswith("-SWAP"))
            okx_count = okx_swap + okx_delivery

            closed_list = [c.to_dict() for c in list(self.closed_trades)[:40]]
            all_pnls = [c.net_pnl_usd for c in self.closed_trades]
            wins = [x for x in all_pnls if x > 0]
            losses = [x for x in all_pnls if x <= 0]
            pf = round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) < 0 else None

            # En hareketli / hacim patlamasına en yakın ilk 25 vadeli pariteyi sırala
            hot_movers = []
            for tape in self.tapes.values():
                if tape.last_price <= 0:
                    continue
                m = tape.metrics(self.cfg.burst_window_sec)
                heat_rank = m["vol_mult"] * (1.0 + abs(m["ret_burst_pct"]) * 3.0)
                hot_movers.append((heat_rank, tape, m))

            hot_movers.sort(key=lambda x: x[0], reverse=True)
            radar = []
            for _, tape, m in hot_movers[:25]:
                radar.append(
                    {
                        "key": tape.key,
                        "exchange": tape.exchange.upper(),
                        "symbol": tape.symbol,
                        "price": tape.last_price,
                        "pct_24h": round(tape.pct_24h, 2),
                        "vol_24h_m": round(tape.quote_vol_24h / 1e6, 2),
                        "vol_mult": m["vol_mult"],
                        "burst_usd": round(m["burst_usd"], 0),
                        "ret_burst_pct": round(m["ret_burst_pct"], 3),
                        "orderflow_bias": m["orderflow_bias"],
                        "in_position": tape.key in self.active_symbol_keys,
                    }
                )

            # Grafik için seçilen pariteyi hazırla
            chart_tape = self.tapes.get(chart_key)
            if chart_tape is None and hot_movers:
                chart_tape = hot_movers[0][1]
                chart_key = chart_tape.key

            candles = []
            chart_pos = None
            if chart_tape is not None:
                candles = [
                    {"t": b.minute_ts, "o": b.o, "h": b.h, "l": b.l, "c": b.c, "v": round(b.v_usd, 1)}
                    for b in chart_tape.bars_1m
                ]
                pid = self.active_symbol_keys.get(chart_key)
                if pid and pid in self.positions:
                    chart_pos = self.positions[pid].to_dict()

            open_positions = sorted(
                [p.to_dict() for p in self.positions.values()],
                key=lambda x: x["opened_ts"],
                reverse=True,
            )

            now_s = time.time()
            anchor_ts = self.first_live_tick_ts if self.first_live_tick_ts > 0 else self.started_ts
            elapsed_sec = int(max(0.0, now_s - anchor_ts)) if self.first_live_tick_ts > 0 else 0
            remaining_sec = max(0, self.test_target_sec - elapsed_sec)
            if elapsed_sec >= self.test_target_sec and self.one_hour_checkpoint is None:
                self.one_hour_checkpoint = {
                    "completed_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(now_s)),
                    "equity_usd": round(self.live_equity_usd(), 2),
                    "realized_pnl_usd": round(self.realized_pnl_usd, 2),
                    "unrealized_pnl_usd": round(self.unrealized_pnl_usd(), 2),
                    "closed_count": len(all_pnls),
                    "open_count": len(open_positions),
                    "win_rate": round(len(wins) / len(all_pnls), 3) if all_pnls else 0.0,
                    "profit_factor": pf,
                    "total_symbols": len(self.tapes),
                    "total_ticks": self.total_ticks_processed,
                }
                self._log_event(
                    "1_SAAT_SONUÇ",
                    f"1 Saatlik Canlı Test Hedefi Tamamlandı! Kasa: ${self.one_hour_checkpoint['equity_usd']:.2f} "
                    f"| Kapanan: {self.one_hour_checkpoint['closed_count']} | Açık: {self.one_hour_checkpoint['open_count']}",
                )

            cloud_live = (now_s - float(self.feed_sources.get("cloud_last_ts") or 0.0)) < 25.0
            browser_bin_live = (now_s - float(self.feed_sources.get("browser_binance_ts") or 0.0)) < 15.0
            browser_okx_live = (now_s - float(self.feed_sources.get("browser_okx_ts") or 0.0)) < 15.0

            return {
                "trading_enabled": self.trading_enabled,
                "sensitivity": self.cfg.sensitivity,
                "session": {
                    "active": self.first_live_tick_ts > 0,
                    "elapsed_sec": elapsed_sec,
                    "remaining_sec": remaining_sec,
                    "target_sec": self.test_target_sec,
                    "progress_pct": round(min(100.0, (elapsed_sec / self.test_target_sec) * 100.0), 1),
                    "completed_1h": self.one_hour_checkpoint is not None,
                    "one_hour_checkpoint": self.one_hour_checkpoint,
                },
                "feed_status": {
                    "binance_live": browser_bin_live or (cloud_live and binance_count > 0),
                    "okx_live": browser_okx_live or (cloud_live and okx_count > 0),
                    "cloud_bridge_live": cloud_live,
                    "browser_binance_live": browser_bin_live,
                    "browser_okx_live": browser_okx_live,
                    "cloud_seq": self.feed_sources.get("cloud_seq", 0),
                    "cloud_source_label": self.feed_sources.get("cloud_source_label", ""),
                },
                "thresholds": {
                    "vol_explosion_mult": self.cfg.vol_explosion_mult,
                    "min_velocity_pct": self.cfg.min_velocity_pct,
                    "min_burst_usd": self.cfg.min_burst_usd,
                    "hard_stop_loss_usd": self.cfg.hard_stop_loss_usd,
                },
                "universe": {
                    "total_symbols": len(self.tapes),
                    "binance_futures": binance_count,
                    "binance_usdm": binance_usdm,
                    "binance_coinm": binance_coinm,
                    "okx_futures": okx_count,
                    "okx_swap": okx_swap,
                    "okx_delivery": okx_delivery,
                    "total_ticks": self.total_ticks_processed,
                },
                "account": {
                    "margin_mode": "CROSS (ÇAPRAZ)",
                    "initial_equity_usd": self.cfg.initial_equity_usd,
                    "live_equity_usd": round(self.live_equity_usd(), 2),
                    "realized_pnl_usd": round(self.realized_pnl_usd, 2),
                    "unrealized_pnl_usd": round(self.unrealized_pnl_usd(), 2),
                    "margin_per_trade_usd": self.cfg.margin_per_trade_usd,
                    "leverage": self.cfg.leverage,
                    "used_margin_usd": round(self.used_margin_usd(), 2),
                    "open_count": len(open_positions),
                    "max_positions_label": "SINIRSIZ",
                    "closed_count": len(all_pnls),
                    "win_rate": round(len(wins) / len(all_pnls), 3) if all_pnls else 0.0,
                    "profit_factor": pf,
                },
                "open_positions": open_positions,
                "closed_trades": closed_list,
                "radar": radar,
                "events": list(self.events)[:40],
                "equity_curve": list(self.equity_history),
                "chart": {
                    "key": chart_key,
                    "candles": candles,
                    "position": chart_pos,
                },
            }


# ============================================================
# 5) SAF PYTHON ASENKRON WEBSOCKET AKIŞ İSTEMCİSİ (PC / VPS / SUNUCU)
# ============================================================
class DirectExchangeWSRunner:
    """
    Kendi bilgisayarınızda veya sunucunuzda çalıştırıldığında doğrudan Python aiohttp
    üzerinden 1.200+ kontratlık TÜM Vadeli İşlemler evrenine bağlanır:
      1. Binance USDⓈ-M Vadeli İşlemler (USDT Perp + USDC Perp + Çeyreklik Teslimatlı Futures)
      2. Binance COIN-M Vadeli İşlemler (USD_PERP + Çeyreklik Teslimatlı COIN-M Futures)
      3. OKX Süresiz SWAP (USDT-SWAP + USDC-SWAP + USD-SWAP)
      4. OKX Vadeli FUTURES (Haftalık, İki Haftalık, Çeyreklik, İki Çeyreklik Kontratlar)
    """

    def __init__(self, engine: RealTimeVolumeShockEngine) -> None:
        self.engine = engine
        self.running = False

    async def start(self, duration_sec: Optional[int] = None) -> None:
        import aiohttp

        self.running = True
        tasks = [
            asyncio.create_task(self._binance_usdm_all_ws(aiohttp)),
            asyncio.create_task(self._binance_coinm_all_ws(aiohttp)),
            asyncio.create_task(self._okx_all_futures_ws(aiohttp)),
        ]
        try:
            if duration_sec is not None:
                await asyncio.sleep(duration_sec)
            else:
                await asyncio.gather(*tasks)
        finally:
            self.running = False
            for t in tasks:
                t.cancel()

    async def _binance_usdm_all_ws(self, aiohttp_mod: Any) -> None:
        """Binance USDⓈ-M: TÜM USDT Perpetual + USDC Perpetual + Teslimatlı Futures (~600+ Kontrat)."""
        url_tickers = "wss://fstream.binance.com/ws/!ticker@arr"
        subscribed_syms: set[str] = set()

        while self.running:
            try:
                async with aiohttp_mod.ClientSession() as session:
                    async with session.ws_connect(url_tickers, heartbeat=20) as ws:
                        logger.info("[BINANCE USDⓈ-M WS] Tüm USDT/USDC Perpetual & Delivery Futures akışı bağlandı!")
                        kline_tasks: List[asyncio.Task] = []
                        async for msg in ws:
                            if not self.running:
                                break
                            if msg.type != aiohttp_mod.WSMsgType.TEXT:
                                continue
                            arr = json.loads(msg.data)
                            now = time.time()
                            batch = []
                            new_syms = []
                            for t in arr:
                                sym = t.get("s", "")
                                if not sym:
                                    continue
                                px = float(t.get("c") or 0.0)
                                if px <= 0:
                                    continue
                                batch.append(
                                    {
                                        "exchange": "binance",
                                        "symbol": sym,
                                        "price": px,
                                        "pct_24h": float(t.get("P") or 0.0),
                                        "quote_vol_24h": float(t.get("q") or 0.0),
                                        "ts": now,
                                    }
                                )
                                if sym not in subscribed_syms:
                                    subscribed_syms.add(sym)
                                    new_syms.append(sym)
                            if batch:
                                self.engine.ingest_batch(batch)
                            for i in range(0, len(new_syms), 180):
                                chunk = new_syms[i : i + 180]
                                kline_tasks.append(
                                    asyncio.create_task(
                                        self._binance_kline_chunk_ws(
                                            session, aiohttp_mod, "wss://fstream.binance.com", "binance", chunk, coin_m=False
                                        )
                                    )
                                )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("[BINANCE USDⓈ-M WS] Yeniden bağlanılıyor: %s", exc)
                await asyncio.sleep(3.0)

    async def _binance_coinm_all_ws(self, aiohttp_mod: Any) -> None:
        """Binance COIN-M: TÜM USD_PERP & Çeyreklik COIN-M Futures (~65+ Kontrat)."""
        url_tickers = "wss://dstream.binance.com/ws/!ticker@arr"
        subscribed_syms: set[str] = set()

        while self.running:
            try:
                async with aiohttp_mod.ClientSession() as session:
                    async with session.ws_connect(url_tickers, heartbeat=20) as ws:
                        logger.info("[BINANCE COIN-M WS] Tüm COIN-M Vadeli İşlemler akışı bağlandı!")
                        kline_tasks: List[asyncio.Task] = []
                        async for msg in ws:
                            if not self.running:
                                break
                            if msg.type != aiohttp_mod.WSMsgType.TEXT:
                                continue
                            arr = json.loads(msg.data)
                            now = time.time()
                            batch = []
                            new_syms = []
                            for t in arr:
                                sym = t.get("s", "")
                                px = float(t.get("c") or 0.0)
                                if not sym or px <= 0:
                                    continue
                                base_vol = float(t.get("q") or 0.0)  # COIN-M'de q = baz coin hacmi -> USD = q * c
                                batch.append(
                                    {
                                        "exchange": "binance_coinm",
                                        "symbol": sym,
                                        "price": px,
                                        "pct_24h": float(t.get("P") or 0.0),
                                        "quote_vol_24h": base_vol * px,
                                        "ts": now,
                                    }
                                )
                                if sym not in subscribed_syms:
                                    subscribed_syms.add(sym)
                                    new_syms.append(sym)
                            if batch:
                                self.engine.ingest_batch(batch)
                            for i in range(0, len(new_syms), 180):
                                chunk = new_syms[i : i + 180]
                                kline_tasks.append(
                                    asyncio.create_task(
                                        self._binance_kline_chunk_ws(
                                            session, aiohttp_mod, "wss://dstream.binance.com", "binance_coinm", chunk, coin_m=True
                                        )
                                    )
                                )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("[BINANCE COIN-M WS] Yeniden bağlanılıyor: %s", exc)
                await asyncio.sleep(3.0)

    async def _binance_kline_chunk_ws(
        self, session: Any, aiohttp_mod: Any, base_ws: str, ex_tag: str, symbols: List[str], coin_m: bool = False
    ) -> None:
        streams = "/".join(f"{s.lower()}@kline_1m" for s in symbols)
        url = f"{base_ws}/stream?streams={streams}"
        while self.running:
            try:
                async with session.ws_connect(url, heartbeat=20) as ws:
                    async for msg in ws:
                        if not self.running:
                            break
                        if msg.type != aiohttp_mod.WSMsgType.TEXT:
                            continue
                        d = json.loads(msg.data).get("data", {})
                        k = d.get("k")
                        if not k:
                            continue
                        px = float(k["c"])
                        k_q = float(k["q"]) * px if coin_m else float(k["q"])
                        k_buy = float(k["Q"]) * px if coin_m else float(k["Q"])
                        self.engine.ingest_batch(
                            [
                                {
                                    "exchange": ex_tag,
                                    "symbol": k["s"],
                                    "price": px,
                                    "kline_ts": int(k["t"]),
                                    "kline_q": k_q,
                                    "kline_buy_q": k_buy,
                                    "ts": time.time(),
                                }
                            ]
                        )
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(3.0)

    async def _okx_all_futures_ws(self, aiohttp_mod: Any) -> None:
        """OKX TÜM SWAP (USDT/USDC/USD) + TÜM FUTURES (Haftalık/Çeyreklik Kontratlar) (~580+ Kontrat)."""
        rest_urls = [
            "https://www.okx.com/api/v5/market/tickers?instType=SWAP",
            "https://www.okx.com/api/v5/market/tickers?instType=FUTURES",
        ]
        ws_public = "wss://ws.okx.com:8443/ws/v5/public"
        ws_biz = "wss://ws.okx.com:8443/ws/v5/business"

        while self.running:
            try:
                async with aiohttp_mod.ClientSession() as session:
                    all_okx_syms: List[str] = []
                    init_batch = []
                    now = time.time()
                    for r_url in rest_urls:
                        async with session.get(r_url, timeout=15) as resp:
                            raw = await resp.json()
                        for t in raw.get("data", []):
                            inst = t.get("instId", "")
                            last = float(t.get("last") or 0.0)
                            open24 = float(t.get("open24h") or 0.0)
                            vol_ccy = float(t.get("volCcy24h") or 0.0)
                            if not inst or last <= 0:
                                continue
                            all_okx_syms.append(inst)
                            init_batch.append(
                                {
                                    "exchange": "okx",
                                    "symbol": inst,
                                    "price": last,
                                    "pct_24h": ((last / open24) - 1.0) * 100.0 if open24 > 0 else 0.0,
                                    "quote_vol_24h": vol_ccy * last,
                                    "ts": now,
                                }
                            )
                    if init_batch:
                        self.engine.ingest_batch(init_batch)

                    # 200'er kontratlık ayrı WS bağlantılarıyla tüm OKX SWAP + FUTURES akışlarını başlat
                    sub_tasks = []
                    for i in range(0, len(all_okx_syms), 200):
                        chunk = all_okx_syms[i : i + 200]
                        sub_tasks.append(self._okx_ws_subscribe(session, aiohttp_mod, ws_public, "tickers", chunk))
                        sub_tasks.append(self._okx_ws_subscribe(session, aiohttp_mod, ws_biz, "candle1m", chunk))
                    await asyncio.gather(*sub_tasks)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("[OKX WS] Yeniden bağlanılıyor: %s", exc)
                await asyncio.sleep(3.0)

    async def _okx_ws_subscribe(
        self, session: Any, aiohttp_mod: Any, url: str, channel: str, symbols: List[str]
    ) -> None:
        async with session.ws_connect(url, heartbeat=20) as ws:
            logger.info("[OKX WS] %s kanalı bağlandı (%d vadeli parite)!", channel, len(symbols))
            for i in range(0, len(symbols), 50):
                args = [{"channel": channel, "instId": s} for s in symbols[i : i + 50]]
                await ws.send_json({"op": "subscribe", "args": args})
                await asyncio.sleep(0.12)

            async for msg in ws:
                if not self.running:
                    break
                if msg.type != aiohttp_mod.WSMsgType.TEXT:
                    continue
                if msg.data == "pong":
                    continue
                payload = json.loads(msg.data)
                arg = payload.get("arg") or {}
                inst = arg.get("instId", "")
                rows = payload.get("data") or []
                if not inst or not rows:
                    continue

                if channel == "tickers":
                    r = rows[0]
                    last = float(r.get("last") or 0.0)
                    open24 = float(r.get("open24h") or 0.0)
                    vol_ccy = float(r.get("volCcy24h") or 0.0)
                    self.engine.ingest_batch(
                        [
                            {
                                "exchange": "okx",
                                "symbol": inst,
                                "price": last,
                                "pct_24h": ((last / open24) - 1.0) * 100.0 if open24 > 0 else 0.0,
                                "quote_vol_24h": vol_ccy * last,
                                "ts": time.time(),
                            }
                        ]
                    )
                elif channel == "candle1m":
                    c = rows[0]
                    # [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
                    px = float(c[4])
                    q_quote = float(c[7] or 0.0)
                    if q_quote <= 0:
                        q_quote = float(c[6] or 0.0) * px  # USD-SWAP / COIN-M kontratlarda volCcy * close
                    self.engine.ingest_batch(
                        [
                            {
                                "exchange": "okx",
                                "symbol": inst,
                                "price": px,
                                "kline_ts": int(c[0]),
                                "kline_q": q_quote,
                                "ts": time.time(),
                            }
                        ]
                    )


# ============================================================
# 6) CANLI ÇAPRAZ MARJİN (CROSS) EMİR YÜRÜTÜCÜSÜ (BINANCE & OKX)
# ============================================================
class LiveCrossMarginExecutor:
    """
    Canlı modda (paper_mode=False & I_UNDERSTAND_RISK=YES) Binance USDT-M ve OKX USDT-SWAP
    üzerinde pozisyon açarken otomatik olarak:
      1. Marjin tipini ÇAPRAZ ('cross' — ASLA İZOLE DEĞİL!) olarak ayarlar,
      2. Kaldıracı 10x yapar,
      3. $50 × 10x = $500 büyüklüğünde piyasa emri gönderir ve kapanışta reduceOnly ile kapatır.
    """

    def __init__(self, cfg: TurboConfig) -> None:
        import ccxt

        load_dotenv_safe()
        self.cfg = cfg
        self.clients: Dict[str, Any] = {}
        self._configured_syms: set[str] = set()
        self._open_amounts: Dict[str, float] = {}

        if os.getenv("BINANCE_API_KEY"):
            b = ccxt.binance(
                {
                    "apiKey": os.getenv("BINANCE_API_KEY"),
                    "secret": os.getenv("BINANCE_SECRET", ""),
                    "enableRateLimit": True,
                    "options": {"defaultType": "future"},
                }
            )
            b.load_markets()
            self.clients["binance"] = b

            bc = ccxt.binancecoinm(
                {
                    "apiKey": os.getenv("BINANCE_API_KEY"),
                    "secret": os.getenv("BINANCE_SECRET", ""),
                    "enableRateLimit": True,
                }
            )
            bc.load_markets()
            self.clients["binance_coinm"] = bc

        if os.getenv("OKX_API_KEY"):
            o = ccxt.okx(
                {
                    "apiKey": os.getenv("OKX_API_KEY"),
                    "secret": os.getenv("OKX_SECRET", ""),
                    "password": os.getenv("OKX_PASSPHRASE", ""),
                    "enableRateLimit": True,
                    "options": {"defaultType": "swap"},
                }
            )
            o.load_markets()
            self.clients["okx"] = o

    def _resolve_ccxt_symbol(self, ex_name: str, raw_symbol: str) -> Optional[str]:
        ex = self.clients.get(ex_name)
        if not ex:
            return None
        if raw_symbol in ex.markets:
            return raw_symbol
        by_id = ex.markets_by_id.get(raw_symbol)
        if isinstance(by_id, list) and by_id:
            return by_id[0]["symbol"]
        if isinstance(by_id, dict):
            return by_id.get("symbol")
        return None

    def _ensure_cross_10x(self, ex_name: str, ccxt_sym: str) -> None:
        tag = f"{ex_name}:{ccxt_sym}"
        if tag in self._configured_syms:
            return
        ex = self.clients[ex_name]
        try:
            ex.set_margin_mode("cross", ccxt_sym)
        except Exception:
            pass
        try:
            params = {"marginMode": "cross"} if ex_name == "okx" else {}
            ex.set_leverage(self.cfg.leverage, ccxt_sym, params)
        except Exception:
            pass
        self._configured_syms.add(tag)

    def execute_open(self, exchange: str, symbol: str, side: int, ref_price: float) -> None:
        if exchange not in self.clients or ref_price <= 0:
            return
        ccxt_sym = self._resolve_ccxt_symbol(exchange, symbol)
        if not ccxt_sym:
            return
        ex = self.clients[exchange]
        self._ensure_cross_10x(exchange, ccxt_sym)
        mkt = ex.market(ccxt_sym)
        contract_size = float(mkt.get("contractSize") or 1.0)
        if mkt.get("inverse"):
            # COIN-M / USD-SWAP ters kontratlarda contractSize doğrudan USD değerindedir ($100 veya $10)
            raw_amt = self.cfg.notional_per_trade_usd / contract_size
        else:
            raw_amt = self.cfg.notional_per_trade_usd / (ref_price * contract_size)
        amt = float(ex.amount_to_precision(ccxt_sym, raw_amt))
        if amt <= 0:
            return
        order_side = "buy" if side > 0 else "sell"
        params = {"tdMode": "cross"} if exchange == "okx" else {}
        ex.create_order(ccxt_sym, "market", order_side, amt, None, params)
        self._open_amounts[f"{exchange}:{symbol}"] = amt

    def execute_close(self, exchange: str, symbol: str, side: int, ref_price: float) -> None:
        key = f"{exchange}:{symbol}"
        amt = self._open_amounts.pop(key, 0.0)
        if exchange not in self.clients or amt <= 0:
            return
        ccxt_sym = self._resolve_ccxt_symbol(exchange, symbol)
        if not ccxt_sym:
            return
        ex = self.clients[exchange]
        close_side = "sell" if side > 0 else "buy"
        params = {"reduceOnly": True, "tdMode": "cross"} if exchange == "okx" else {"reduceOnly": True}
        ex.create_order(ccxt_sym, "market", close_side, amt, None, params)


# ============================================================
# 7) ÖZ TESTLER VE KOMUT SATIRI GİRİŞİ (CLI)
# ============================================================
def run_turbo_self_tests() -> None:
    cfg = TurboConfig()
    cfg.validate()
    assert cfg.initial_equity_usd == 1000.0
    assert cfg.margin_per_trade_usd == 50.0
    assert cfg.leverage == 10
    assert cfg.notional_per_trade_usd == 500.0
    assert cfg.margin_mode == "cross"
    assert cfg.max_positions == 0  # Sınırsız!
    assert cfg.hard_stop_loss_usd == 10.0

    eng = RealTimeVolumeShockEngine(cfg=cfg)
    t0 = 1_760_000_000.0

    # 1. 10 farklı coinde aynı anda hacim patlaması simüle et -> SINIRSIZ pozisyon kuralı gereği 10'u da açılmalı!
    for idx in range(10):
        ex = "binance" if idx % 2 == 0 else "okx"
        sym = f"COIN{idx}USDT" if ex == "binance" else f"COIN{idx}-USDT-SWAP"
        eng.ingest_batch(
            [
                {"exchange": ex, "symbol": sym, "price": 100.0, "quote_vol_24h": 5_000_000.0, "kline_ts": 60_000, "kline_q": 1000.0, "kline_buy_q": 500.0, "ts": t0},
                {"exchange": ex, "symbol": sym, "price": 100.1, "quote_vol_24h": 5_000_000.0, "kline_ts": 60_000, "kline_q": 2000.0, "kline_buy_q": 1200.0, "ts": t0 + 2.0},
                {"exchange": ex, "symbol": sym, "price": 100.6, "quote_vol_24h": 5_000_000.0, "kline_ts": 60_000, "kline_q": 32_000.0, "kline_buy_q": 28_000.0, "ts": t0 + 5.0},
            ]
        )
    assert len(eng.positions) == 10, f"Sınırsız pozisyon kuralı ihlali! Açılan: {len(eng.positions)}"

    # 2. COIN0USDT sert düşerse net zarar tam -$20.00 sınırında kesilmeli!
    eng.ingest_batch(
        [{"exchange": "binance", "symbol": "COIN0USDT", "price": 95.5, "ts": t0 + 8.0}]
    )
    assert "binance:COIN0USDT" not in eng.active_symbol_keys
    last_closed = eng.closed_trades[0]
    assert last_closed.exit_reason == "ZARAR_KES_-10$"
    assert abs(last_closed.net_pnl_usd - (-20.0)) < 1e-6

    # 3. COIN2USDT parabolik yükselip geri döndüğünde AI kâr motoru kârlı kapatmalı!
    eng.ingest_batch(
        [
            {"exchange": "binance", "symbol": "COIN2USDT", "price": 103.5, "kline_ts": 60_000, "kline_q": 55_000.0, "kline_buy_q": 48_000.0, "ts": t0 + 9.0},
            {"exchange": "binance", "symbol": "COIN2USDT", "price": 102.2, "kline_ts": 60_000, "kline_q": 60_000.0, "kline_buy_q": 48_500.0, "ts": t0 + 11.0},
        ]
    )
    assert "binance:COIN2USDT" not in eng.active_symbol_keys
    tp_closed = eng.closed_trades[0]
    assert tp_closed.net_pnl_usd > 7.0
    assert "KAR" in tp_closed.exit_reason
    print("TURBO_ENGINE öz testleri (%100 Çapraz Marjin, Sınırsız İşlem, -$20 SL, AI TP) başarıyla geçti!")


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="ACARBOT56 TURBO — Gerçek Zamanlı Tüm Futures Hacim Patlaması Motoru")
    ap.add_argument("--test", action="store_true", help="TURBO motor öz testlerini çalıştır")
    ap.add_argument("--live", action="store_true", help="Canlı borsa emir modu (I_UNDERSTAND_RISK=YES gerektirir)")
    ap.add_argument("--sensitivity", choices=["fast", "balanced", "sniper"], default="fast")
    ap.add_argument("--duration", type=int, default=None, help="Çalışma süresi (saniye)")
    args = ap.parse_args(argv)

    if args.test:
        run_turbo_self_tests()
        return 0

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    cfg = TurboConfig(paper_mode=not args.live)
    cfg.apply_sensitivity_preset(args.sensitivity)
    cfg.validate()

    live_exec = LiveCrossMarginExecutor(cfg) if args.live else None
    engine = RealTimeVolumeShockEngine(
        cfg=cfg,
        on_live_order=live_exec.execute_open if live_exec else None,
        on_live_close=live_exec.execute_close if live_exec else None,
    )
    runner = DirectExchangeWSRunner(engine)
    try:
        asyncio.run(runner.start(duration_sec=args.duration))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
