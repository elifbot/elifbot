# -*- coding: utf-8 -*-
"""
ACARBOT OMEGA — Ana Konfigürasyon & Değişmez Risk Kuralları (config.py)
=======================================================================
Kullanıcı Sabit Kuralları:
  - Başlangıç Kasası: $1,000.00
  - İşlem Girişi: $50.00 Teminat × 10x Kaldıraç = $500.00 Pozisyon Büyüklüğü
  - Marjin Modu: ÇAPRAZ MARJİN ('cross' — Kesinlikle İzole Değil!)
  - Pozisyon Limiti: SINIRSIZ (max_positions = 0; yapay adet sınırı yok)
  - Zarar Kes: Komisyon + kayma dahil kesin -$20.00 net zarar tavanı
  - Kâr Al: 5 Kademeli Otonom AI İvme + Tükeniş + Zaman Hasadı Motoru
  - Evren: Binance (USDⓈ-M + COIN-M) & OKX (SWAP + FUTURES) -> 1.200+ Kontrat
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal


@dataclass
class OmegaConfig:
    # 1. Kasa, Boyutlandırma ve Çapraz Marjin Kuralları
    initial_equity_usd: float = 1000.0
    margin_per_trade_usd: float = 50.0
    leverage: int = 10
    margin_mode: Literal["cross"] = "cross"  # İZOLE YASAK -> DAİMA ÇAPRAZ (CROSS)
    max_positions: int = 0                   # 0 = SINIRSIZ AÇIK POZİSYON (yapay adet sınırı YOK)
    # Sınırsız işlem açılır; ancak gerçek borsada çapraz marjinin fiziksel sınırı vardır:
    # $1,000 kasa ile $50 teminatlı işlemlerde aynı anda ~20 pozisyon taşınabilir. Bu bir
    # "adet sınırı" değil, borsanın marjin yeterlilik (free margin) kontrolüdür.
    enforce_margin_availability: bool = True
    margin_utilization_cap: float = 0.98
    deduplicate_base_asset_sec: float = 15.0  # Aynı baz coine aynı saniyede 3 farklı kontratla mükerrer girişi önler
    symbol_cooldown_sec: float = 25.0

    # 2. Kesin -$20.00 Net Zarar Kes & Gerçek Maliyet Modeli (v5.5 Zarar Analizi Dersi)
    hard_stop_loss_usd: float = 10.0
    taker_fee_bps: float = 5.0        # %0.05 (5 bps)
    maker_fee_bps: float = 2.0        # %0.02 (2 bps)
    default_spread_bps: float = 2.5   # Yarı-makas maliyeti tahmini
    entry_slippage_bps: float = 2.0   # Giriş kayma rezervi
    exit_slippage_bps: float = 3.0    # Stop çıkış kayma rezervi
    min_edge_to_cost_ratio: float = 2.4  # Beklenen brüt hareket >= 2.4x toplam sürtünme maliyeti!
    liquidation_safety_buffer_pct: float = 1.5  # -$20 SL likidasyondan en az %1.5 uzakta olmalı

    # 3. 5 Kademeli Otonom AI Kâr Motoru (Kârı Bot Kendisi Belirler)
    be_trigger_usd: float = 4.20         # +$4.20 zirvede zararı sıfırla (+$0.95 net kâr kilidi)
    be_lock_usd: float = 0.95
    trail_arm_usd: float = 7.50          # +$7.50 üstünde ivme-duyarlı AI trailing başlar
    parabolic_arm_usd: float = 22.00     # +$22.00 üstünde sıkı parabolik kâr kilidi (%86 koruma)
    exhaustion_tp_min_usd: float = 4.80  # +$4.80 üstündeyken hacim/CVD duvarı ters dönerse tepede çık!
    stagnation_hold_sec: float = 900.0   # 15dk+ yatay sönümlenen kârlı işlemi hasat et (V20 dersi)
    stagnation_min_pnl_usd: float = 2.20

    # 4. 1.200+ Tüm-Futures Evreni & Saliselik Hacim Patlaması / Çöküşü Eşikleri
    preset: Literal["fast", "balanced", "institutional"] = "balanced"
    min_24h_vol_usd: float = 25_000.0    # Düşük hacimli altcoin ve çeyreklik kontratları kapsar
    burst_window_sec: float = 12.0
    vol_explosion_mult: float = 2.6      # Baz saniyelik hacmin >= 2.6 katı patlama
    min_burst_usd: float = 8_000.0       # 12sn pencerede en az $8,000 gerçek işlem
    min_velocity_pct: float = 0.24       # En az %0.24 net fiyat ivmesi
    min_orderflow_bias: float = 0.16     # CVD / Alıcı-satıcı baskı üstünlüğü
    vol_collapse_ratio: float = 0.32     # Zirve patlama sonrası hacmin %68+ kuruması (Tükeniş dönüşü)
    max_choppiness_index: float = 64.0   # Testere piyasası (whipsaw) filtresi

    # 5. 20-Denetçili Yapay Zeka Konseyi & Öğrenme Ayarları
    council_min_approval_score: float = 0.56  # [0..1] konsey onay eşiği
    enable_live_llm_council: bool = False     # True ise API anahtarı varsa canlı LLM'lere de danışır
    fail_closed_on_llm_error: bool = False    # Sıkı canlı LLM modunda quorum yoksa reddeder

    # 6. Çalışma ve Güvenlik Kilidi
    paper_mode: bool = True
    live_confirm_env: str = "I_UNDERSTAND_RISK"
    sqlite_db_path: str = "omega_ledger.sqlite3"

    @property
    def notional_per_trade_usd(self) -> float:
        return self.margin_per_trade_usd * self.leverage  # $50 * 10 = $500.00

    def apply_preset(self, name: str) -> None:
        if name == "fast":
            self.preset = "fast"
            self.vol_explosion_mult = 2.1
            self.min_burst_usd = 5_000.0
            self.min_velocity_pct = 0.18
            self.min_orderflow_bias = 0.12
            self.min_edge_to_cost_ratio = 2.0
            self.council_min_approval_score = 0.52
        elif name == "institutional":
            self.preset = "institutional"
            self.vol_explosion_mult = 3.6
            self.min_burst_usd = 18_000.0
            self.min_velocity_pct = 0.36
            self.min_orderflow_bias = 0.24
            self.min_edge_to_cost_ratio = 3.0
            self.council_min_approval_score = 0.64
        else:
            self.preset = "balanced"
            self.vol_explosion_mult = 2.6
            self.min_burst_usd = 8_000.0
            self.min_velocity_pct = 0.24
            self.min_orderflow_bias = 0.16
            self.min_edge_to_cost_ratio = 2.4
            self.council_min_approval_score = 0.56

    def validate(self) -> None:
        if self.initial_equity_usd <= 0 or self.margin_per_trade_usd <= 0 or self.leverage < 1:
            raise ValueError("Başlangıç kasası, işlem teminatı ve kaldıraç pozitif olmalıdır.")
        if self.margin_mode != "cross":
            raise ValueError("Kullanıcı kuralı gereği marjin modu kesinlikle 'cross' (Çapraz) olmalıdır!")
        if self.max_positions != 0:
            raise ValueError("Kullanıcı kuralı gereği pozisyon adedi sınırı 0 (SINIRSIZ) olmalıdır!")
        if self.hard_stop_loss_usd <= 1.0 or self.hard_stop_loss_usd > self.margin_per_trade_usd:
            raise ValueError("hard_stop_loss_usd $1 ile işlem teminatı ($50) arasında olmalıdır.")
        if not self.paper_mode and os.getenv(self.live_confirm_env) != "YES":
            raise RuntimeError(f"Canlı işlem emniyet kilidi aktif: {self.live_confirm_env}=YES tanımlanmalıdır.")
