"""Merkezi ayarlar — süper sürümün tek doğruluk kaynağı.

Tüm eşikler, limitler ve sabitler burada toplanır. Böylece canlı akış,
paper motoru ve backtest motoru AYNI sayılarla çalışır (Yorum 2 #6:
"backtest canlı sistemi test etmiyor" eleştirisine kökten çözüm).

Varsayılan parametreler kullanıcının şartnamesini korur:
1.000 USDT bakiye, 50 USDT teminat, 10x kaldıraç, 500 USDT nominal,
pozisyon başına 25 USDT zarar tavanı.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Hesap ve pozisyon boyutlandırma
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AccountConfig:
    initial_balance: float = 1_000.0
    margin_per_position: float = 50.0
    leverage: float = 10.0
    max_notional_per_position: float = 500.0
    max_loss_per_position: float = 25.0          # NET (ücret + kayma dâhil)
    maker_fee_rate: float = 0.0002               # Binance USDT-M standart
    taker_fee_rate: float = 0.0005
    stop_slippage_rate: float = 0.0005           # stop/emir kayma tahmini
    extra_slippage_rate: float = 0.0003          # gap/volatilite ek kayması


# ---------------------------------------------------------------------------
# Portföy düzeyi risk (Yorum 1 G, Yorum 2 #7)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PortfolioConfig:
    max_positions: int = 6                       # 20 değil: bu bakiyede gerçekçi tavan
    max_positions_per_group: int = 2             # korelasyon grubu başına
    max_group_notional: float = 1_000.0
    gross_notional_cap: float = 3_000.0
    net_directional_notional_cap: float = 1_000.0
    total_open_risk_cap: float = 150.0           # Σ pozisyon başı net risk (6 x 25)
    daily_soft_loss: float = 100.0               # yeni giriş yok (mevcut davranış)
    daily_hard_loss: float = 150.0               # KILL SWITCH: hepsi kapatılır
    portfolio_drawdown_pct: float = 8.0          # equity tepe-dipte güvenli mod
    kill_switch_reset_on_new_day: bool = False   # hard halt elle sıfırlanır


# Korelasyon grupları: benzer davranan coinler aynı kovada sınırlandırılır.
DEFAULT_CORRELATION_GROUPS: dict[str, frozenset[str]] = {
    "majors": frozenset({"BTC", "ETH", "BCH"}),
    "l1_alternatives": frozenset({
        "SOL", "AVAX", "DOT", "ATOM", "NEAR", "SUI", "APT", "SEI", "TIA",
    }),
    "l1_classic": frozenset({"ADA", "XRP", "TRX", "XLM", "HBAR", "ALGO"}),
    "meme": frozenset({
        "DOGE", "SHIB", "PEPE", "WIF", "BONK", "FLOKI", "1000PEPE",
        "1000SHIB", "1000FLOKI",
    }),
    "defi": frozenset({
        "UNI", "AAVE", "LINK", "CRV", "MKR", "LDO", "INJ", "DYDX", "GMX",
    }),
}


# ---------------------------------------------------------------------------
# Funding ve likidasyon (Yorum 1 C)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FundingConfig:
    enabled: bool = True
    default_rate_per_8h: float = 0.0001          # %0,01 / 8 saat (Binance varsayılan)
    interval_hours: float = 8.0
    # İzole teminat likidasyonu yaklaşımı:
    maintenance_margin_rate: float = 0.005       # ~%0,5 (alt seviye aralığı)
    liquidation_fee_rate: float = 0.0125         # borsa likidasyon cezası
    margin_warning_fraction: float = 0.8         # %80 teminat tüketimi uyarısı


# ---------------------------------------------------------------------------
# Sinyal eşikleri (birim-tutarlı RVOL, Yorum 2 #1)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SignalConfig:
    # Hacim patlaması: saniyelik baz-hacim, AYNI ölçekte tabanla kıyaslanır.
    spike_multiplier: float = 3.0
    spike_rvol_sanity_cap: float = 100.0         # üzerindeyse veri hatalı sayılır
    spike_window_seconds: int = 3                # patlama ölçüm penceresi (canlı)
    spike_direction_seconds: int = 5             # yön için fiyat değişim penceresi
    # 5m mum RVOL'u (backtest ve mum kapanışı yolu) — yine aynı ölçek.
    candle_rvol_lookback: int = 20
    min_rvol_for_entry: float = 1.5
    min_rvol_for_exit: float = 1.0
    min_impulse_pct: float = 0.30                # 10 dakikalık bacak için
    fade_impulse_pct: float = 0.35
    max_rvol_entry: float = 40.0                 # aşırı sapma = şüpheli veri
    # Rejim ve filtreler (Yorum 1 E)
    regime_adx_period: int = 14
    regime_adx_trend_threshold: float = 22.0
    regime_adx_strong_trend: float = 30.0        # FADE'i bıçak yakalamaktan korur
    btc_filter_enabled: bool = True
    btc_block_change_pct: float = 0.8            # BTC 15 dk'da bunu aşarsa ters sinyal engellenir
    fake_breakout_wick_ratio: float = 0.65       # fitil/gövde oranı eşiği
    fake_breakout_min_body_pct: float = 0.002    # önemsiz gövdede fitil testi yapılmaz
    trend_warmup_candles: int = 60


# ---------------------------------------------------------------------------
# Çıkış yönetimi (Yorum 2 #3: FADE'e gerçekçi kâr yolu)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExitConfig:
    tp1_r_multiple: float = 1.0                  # +1R'de %50 kısmi kâr alma
    tp1_close_fraction: float = 0.5
    trail_atr_multiple: float = 2.0              # TP1 sonrası ATR takip stopu
    trail_activation_r: float = 0.75             # trail erken aktivasyon (0.75R)
    fade_max_hold_minutes: float = 90.0          # FADE zaman stopu
    trend_max_hold_minutes: float = 24 * 60.0
    atr_period: int = 14
    stop_atr_multiple: float = 1.5
    min_stop_fraction: float = 0.003             # %0,3 alt sınır
    max_stop_fraction: float = 0.025             # %2,5 üst sınır
    # Yorum 2 #5'in tespitine karşı: post-only emir TTL
    order_ttl_seconds: float = 45.0
    max_order_replacements: int = 1


# ---------------------------------------------------------------------------
# Veri bütünlüğü (Yorum 1 F)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DataConfig:
    timeframe: str = "5m"
    timeframe_ms: int = 5 * 60_000
    candle_history: int = 300
    gap_backfill_enabled: bool = True
    stale_symbol_cooldown_s: float = 900.0       # backfill başarısızsa 15 dk giriş yok
    tick_freshness_s: float = 10.0               # giriş için taze tick şartı
    global_stale_s: float = 60.0                 #global bayatlık → güvenli mod
    global_stale_symbol_fraction: float = 0.5
    cross_exchange_divergence_pct: float = 0.5   # borsalar arası fiyat sapması
    warmup_seconds: float = 90.0                 # yeniden başlatma sonrası ısınma
    warmup_min_ticks: int = 5
    volume_unit_check: bool = True               # OKX kontrat / Binance baz doğrulaması


# ---------------------------------------------------------------------------
# Operasyon (Yorum 2 operasyonel, Yorum 3)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OpsConfig:
    state_save_min_interval_s: float = 1.0       # her tick'te fsync YOK
    equity_point_interval_s: float = 60.0
    backup_on_start: bool = True
    backup_keep: int = 5
    telegram_rate_limit_per_min: int = 20
    candle_refresh_margin_s: float = 3.0         # mum kapanışı sonrası yenileme


@dataclass
class SuperConfig:
    """Tüm alt yapılandırmaları birleştiren kök nesne."""
    account: AccountConfig = field(default_factory=AccountConfig)
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)
    funding: FundingConfig = field(default_factory=FundingConfig)
    signal: SignalConfig = field(default_factory=SignalConfig)
    exit: ExitConfig = field(default_factory=ExitConfig)
    data: DataConfig = field(default_factory=DataConfig)
    ops: OpsConfig = field(default_factory=OpsConfig)
    correlation_groups: dict[str, frozenset[str]] = field(
        default_factory=lambda: {k: v for k, v in DEFAULT_CORRELATION_GROUPS.items()}
    )

    def group_of(self, base_asset: str) -> str | None:
        """Verilen dayanak varlığın korelasyon grubunu döndürür."""
        upper = base_asset.upper()
        for group_name, members in self.correlation_groups.items():
            if upper in members:
                return group_name
        return None


DEFAULT_CONFIG = SuperConfig()
