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

# v5.2: dinamik risk olcekleme (kullanici onerisi madde 6)
from core.risk_scaling import RiskScalingConfig


# ---------------------------------------------------------------------------
# Hesap ve pozisyon boyutlandırma
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AccountConfig:
    initial_balance: float = 1_000.0
    # v5.0 (v1.8 kuralı): teminat DINAMIK = notional / kaldıraç.
    # 0 = sabit teminat yok; nominal tavanı da KAPALI. Böylece işlem başı
    # 25 USDT hedef net risk dar stoplarda da gerçekten tutar (500 nominal
    # tavanı riski ~2-3 USDT'ye kırıyordu).
    margin_per_position: float = 0.0
    leverage: float = 10.0
    max_notional_per_position: float = 0.0
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
    # v5.0 (v1.9 kuralı): likidite tabanı. Saniyelik taban hacmi bu USDT
    # değerinin altındaysa enstrüman likiditesizdir; tek bir normal işlem
    # bile RVOL'u yüzlerce kat gösterir. Bu VERİ HATASI değil, LİKİDİTESİZLİK.
    spike_min_baseline_notional_per_second: float = 5.0
    # Aynı sembol için hacim filtresi log aralığı (sn) — log selini önler.
    rvol_log_interval_seconds: float = 60.0
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
    # v3.1: motor seçimi — ("fade","trend"), ("trend",) veya ("fade",).
    # Kapalı motor HiÇ DEĞERLENDİRİLMEZ (SignalPipeline tek kapı; canlı ve
    # backtest aynı kural — --motors CLI bayrağı buraya yazar).
    enabled_motors: tuple[str, ...] = ("fade", "trend")
    # v4.0: strateji seçimi — "classic" (v1.2 FADE/TREND, varsayılan) veya
    # "confluence" | "rsirev" | "macd" | "bollkir" | "bolldon" (--strategy).
    strategy: str = "classic"
    # v4.0: Confluence 10 filtre oylaması eşiği (0-1; toplam puan |x| ≥ eşik
    # ise yön verilir). --confluence-threshold ile ayarlanır.
    confluence_threshold: float = 0.6
    # v4.0: seans (saat) filtresi — "off" | "asia" (00-08 UTC) | "eu"
    # (07-16) | "us" (13-22) | "HH-HH" özel UTC aralığı. Kapalı pencerede
    # YENİ GİRİŞ yok; açık pozisyon yönetimi sürer. Canlı + backtest ortak.
    session_filter: str = "off"


# ---------------------------------------------------------------------------
# v4.0: DCA güvenlik emirleri (varsayılan KAPALI, yalnız LONG)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DcaConfig:
    """Ortalama düşürme (DCA) güvenlik emirleri.

    Varsayılan KAPALI (buna güvenlik kuralı: ek notional ek risk demektir).
    YALNIZCA LONG pozisyonlarda çalışır (SHORT'ta DCA yapılmaz — sonsuz
    riskli taraftır). Tetik: fiyat ortalama girişin altına adım kadar düşer;
    her DCA sonrası adım step_scale ile büyür, hacim volume_scale ile
    ölçeklenir. STOP FİYATI DEĞİŞMEZ (risk zemini korunur); toplam net risk
    pozisyon başı 25 USDT tavanını AŞACAKSA DCA YAPILMAZ (fail-closed).
    Canlı eşlemede DCA → borsaya market ek giriş + mevcut stop korunur.
    """
    enabled: bool = False
    max_safety_orders: int = 2               # en fazla ek giriş
    first_step_pct: float = 1.0              # ilk tetik: ort. girişin -%1'i
    step_scale: float = 1.5                  # her adım bir öncekinin katı
    volume_scale: float = 1.0                # DCA notionalı = ilk notional × scale^n


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
    # v5.0 (v1.10 kuralı): stop fiyatı borsa fiyat ızgarasına (tickSize)
    # DIŞA yuvarlanır, pozisyon GERÇEK stop mesafesinden boyutlanır.
    # Izgara stopu bu orandan fazla genişletiyorsa enstrüman işlem dışıdır.
    stop_tick_max_widen_ratio: float = 1.5
    # Yorum 2 #5'in tespitine karşı: post-only emir TTL
    order_ttl_seconds: float = 45.0
    # v5.2: DOLUM ANI STOP IHLALI POLITIKASI.
    # False (VARSAYILAN) = ters seçilim modellenir: fiyat stopu geçtiyse
    #   limit yine dolar ve aynı tick'te stop olur. Bu GERÇEKÇİDİR;
    #   v5.0'da bu davranış bilinçli olarak eklenmişti ("eski kod kaybı
    #   gizliyordu"). Kapatmak iyimserlik üretir.
    # True = emir iptal edilir. İYİMSER: gerçek borsada iptalin dolmadan
    #   önce yetişeceği garanti değildir. Yalnız bilinçli karşılaştırma
    #   için açılmalı ve rapor `optimistic_stale_cancel` diye etiketlenir.
    cancel_on_stop_breach_at_fill: bool = False
    max_order_replacements: int = 1
    # v2.0: başa baş (break-even) stopu — maliyetleri karşılayan zemin.
    # +1R'ye ulaşıldığında stop en az giriş + gidiş-dönüş maliyet oranına
    # çekilir (oran config'ten hesaplanır, sabit sayı değildir).
    breakeven_enabled: bool = True
    breakeven_activation_r: float = 1.0


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
    # v2.0 backtest: kısmi dolum modeli — bir mumdaki baz hacmin en fazla bu
    # payı limit emrimize gelir (mum hacmi GERÇEK veridir; pay model parametresi).
    bt_participant_cap: float = 0.10
    # v3.0: emir kayması (bps) — dolum fiyatını aleyhte kaydırır (0 = kapalı).
    bt_slippage_bps: float = 0.0
    # v3.0: sinyal → emir gecikmesi (ms) — dolum uygunluğunu erteler
    # (0 = kapalı; 5m mum ölçeğinde timeframe üstü değerler mum atlatır).
    bt_latency_ms: int = 0
    # v3.1: tam pazar modu (--scan-all, 1000+ sembol). Dar listede TÜM
    # feed'lerin ısınması aranır; tam pazarda düşük hacimli coinler bunu
    # imkânsız kılar → çoğunluk oranı + yerleşik feed bazlı bayatlık.
    full_market: bool = False
    full_market_warmup_fraction: float = 0.5     # tracked feed'lerin ≥%50'si ısınmalı
    full_market_stale_fraction: float = 0.8      # yerleşik feed'lerin ≥%80'i bayatsa güvenli mod


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


@dataclass(frozen=True)
class NewsGuardConfig:
    """Makro haber koruması (FINAL v1.1 — ultra_plus'taki taslağın gerçek hâli).

    Forex Factory haftalık takviminden yüksek etkili USD olaylarını çeker;
    olay ±buffer_minutes penceresinde YENİ GİRİŞ açılmaz (stoplar çalışır).
    """
    enabled: bool = True
    calendar_url: str = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    local_events_file: str = ""              # isteğe bağlı manuel olay JSON'u
    currencies: tuple[str, ...] = ("USD",)
    impacts: tuple[str, ...] = ("High",)
    buffer_minutes: float = 30.0
    refresh_seconds: float = 900.0           # 15 dk'da bir tazele
    fetch_timeout_seconds: float = 12.0
    fail_closed: bool = False                # veri alınamazsa: False=devam+uyar


@dataclass(frozen=True)
class SweepGuardConfig:
    """Stop-hunt / likidasyon duvarı tespiti (FINAL v1.1).

    REST orderbook anlık görüntüsünde fiyatın yakınındaki ANORMAL büyük
    emir duvarlarını bulur (likidasyon kümesi vekili). Duvar fiyatın
    block_distance_pct yakınındaysa yeni giriş engellenir: fiyatın duvara
    mıknatıs gibi çekilip stop avı yaşandığı senaryolardan kaçınır.
    Not: gerçek likidasyon ısı haritası değil, defter temelli sezgiseldir.
    """
    enabled: bool = True
    refresh_seconds: float = 25.0
    book_levels: int = 400
    band_pct: float = 0.001                  # %0.1'lik bantlar
    max_distance_pct: float = 0.005          # ±%0.5 tarama aralığı
    wall_min_usd: float = 500_000.0          # mutlak eşik
    wall_multiple: float = 8.0               # medyan banda göre çarpan
    block_distance_pct: float = 0.0035       # duvar ±%0.35 içindeyse giriş yok
    book_ttl_seconds: float = 60.0           # bayat defter yok sayılır


# ---------------------------------------------------------------------------
# ACARBOT v2.0 — akıllı sinyal puanlama (kullanıcı şartnamesi: 100 üzerinden)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScoringConfig:
    """Sinyal puanlama ağırlıkları (toplam 100) ve karar eşikleri.

    Kullanıcı şartnamesi:
      Trend uyumu 20, hacim 15, order flow 20, likidite 15, MTF 15,
      BTC korelasyonu 10, volatilite uygunluğu 5.
      90-100 çok güçlü, 80-89 güçlü, 70-79 normal, <70 işlem yok.
    Veri gelmeyen bileşen "uygulanmadı" işaretlenir, ağırlık paydadan
    düşülür (yer tutucu puan verilmez).
    """
    weight_trend: float = 20.0
    weight_volume: float = 15.0
    weight_orderflow: float = 20.0
    weight_liquidity: float = 15.0
    weight_mtf: float = 15.0
    weight_btc: float = 10.0
    weight_volatility: float = 5.0
    min_score_to_trade: float = 70.0
    strong_score: float = 80.0
    very_strong_score: float = 90.0

    @property
    def total_weight(self) -> float:
        return (
            self.weight_trend + self.weight_volume + self.weight_orderflow
            + self.weight_liquidity + self.weight_mtf + self.weight_btc
            + self.weight_volatility
        )


# ---------------------------------------------------------------------------
# ACARBOT v2.0 — zorunlu risk kapıları (kullanıcı "A. Zorunlu" listesi)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RiskGateConfig:
    """v2.0 zorunlu risk ayarları. Başlangıç değerleri kullanıcı şartnamesinden:

    - Equity eşiği: başlangıç bakiyesinin -%15'i → hepsi kapat + HARD_HALT.
      (Eşik aşıldığında stoplar çalışmaya devam eder, pozisyonlar kapatılır.)
    - BTC şok testi: her girişten önce "BTC ∓%3 giderse toplam kayıp" hesabı;
      equity'nin %15'ini aşarsa giriş engellenir. Beta GERÇEK 5 dakikalık
      getirilerden hesaplanır; yeterli veri yoksa test "uygulanmadı" olur.
    - Giriş hızı: dakikada en fazla 3 GERÇEK giriş (kapanan işlem değil).
    - Stop sonrası yeniden giriş beklemesi: 15 dk (trailing/kâr çıkışında 5 dk).
    """
    equity_floor_pct: float = 15.0           # -%15 equity → HARD_HALT
    btc_shock_pct: float = 3.0               # ∓%3 BTC senaryosu
    btc_shock_loss_cap_pct: float = 15.0     # equity'nin %15'i
    beta_min_returns: int = 50               # beta için en az 5m getirisi
    beta_max_returns: int = 200              # pencere (son N getiri)
    entry_rate_per_min: int = 3              # dakikada gerçek giriş tavanı
    reentry_cooldown_min: float = 15.0       # stop/likidasyon sonrası
    soft_exit_cooldown_min: float = 5.0      # trailing/momentum/zaman sonrası
    deferred_entry_ttl_s: float = 90.0       # hız limitine takılan aday ömrü
    reverse_signal_exit_score: float = 80.0  # ters sinyalde erken çıkış eşiği
    reverse_signal_exit_enabled: bool = True


# ---------------------------------------------------------------------------
# ACARBOT v2.0 — MTF (çoklu zaman dilimi) analizi
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MtfConfig:
    """Çoklu zaman dilimi kuralları (kullanıcı şartnamesi madde 2).

    1m giriş zamanlaması, 5m ana sinyal, 15m trend onayı, 1h ana yön,
    4h büyük yapı. EKSİK mumlar tamamlanmadan değerlendirmeye alınmaz
    (resample yalnızca KAPANMIŞ üst TF barlarını üretir).
    Güçlü çelişki (üst TF ADX >= strong_adx VE EMA eğimi belirgin ters VE
    4h nötr/değil) → işlem engellenir; hafif çelişki → MTF bileşeni 0.
    """
    enabled: bool = True
    timeframes: tuple[str, ...] = ("15m", "1h", "4h")
    refresh_seconds_15m: float = 60.0
    refresh_seconds_1h: float = 120.0
    refresh_seconds_4h: float = 300.0
    strong_adx: float = 25.0                 # üst TF'de "güçlü trend" eşiği
    slope_threshold_pct: float = 0.10        # EMA20 eğim eşiği (bar başına %)
    min_bars_for_bias: int = 20              # EMA20 için en az bar
    block_tfs_required: int = 2              # engel için ters TF sayısı (15m+1h)


# ---------------------------------------------------------------------------
# ACARBOT v2.0 — order flow ve likidite motoru
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OrderFlowConfig:
    """Order flow / likidite motoru (kullanıcı şartnamesi madde 3).

    Sadece GERÇEK veri kullanılır: order book (REST), ticker hacim deltası
    (CVD tick-kuralı), açık pozisyon (OI, borsa desteği varsa). Veri yoksa
    bileşen "uygulanmadı" döner; sabit sayı YERİNE KOYULMAZ.
    """
    enabled: bool = True
    book_band_pct: float = 0.005             # ±%0.5 derinlik penceresi
    imbalance_ratio: float = 1.5             # dengesizlik "belirgin" eşiği
    big_order_multiple: float = 6.0          # medyan seviyenin katı = büyük emir
    absorption_stale_sweeps: int = 3         # duvar + sabit fiyat tazeleme sayısı
    absorption_price_band_pct: float = 0.0005
    oi_refresh_seconds: float = 60.0
    oi_change_threshold: float = 0.01        # %1 OI değişimi = yön sinyali
    cvd_window: int = 120                    # CVD eğimi için tick sayısı
    sweep_lookback_bars: int = 12            # süpürme-dönüş tespiti (mum)
    # v4.0: para akışı verileri (gösterge/kayıt katmanı — skorlamaya DOKUNMAZ,
    # v2 testleri ve skorlar korunur)
    long_short_refresh_seconds: float = 60.0    # long/short oranı tazeleme
    liquidation_window_s: float = 300.0         # likidasyon akışı penceresi
    funding_refresh_seconds: float = 300.0      # gerçek funding oranı tazeleme
    moneyflow_max_age_s: float = 900.0          # bayat veri 'uygulanmadı' sayılır


# ---------------------------------------------------------------------------
# ACARBOT v2.0 — 5 uzman motor (Piyasa Hakemi mimarisi)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExpertConfig:
    """5 uzman motor + Piyasa Hakemi (kullanıcının son önerisi).

    1. Trend Avcısı  — güçlü trendleri yakalar.
    2. Likidite Avcısı — stop avı ve likidite süpürmelerini bulur.
    3. Momentum Avcısı — ani hacim ve fiyat hareketlerini değerlendirir.
    4. Reversal Avcısı — aşırı hareketlerden dönüşleri arar.
    5. Piyasa Hakemi — oyları, piyasa koşullarını ve riskleri değerlendirir.

    Mevcut FADE/TREND çözümleyicisi "temel oy" olarak yüksek ağırlıkla
    katılır; Hakem ancak UZMANLARIN BÜYÜK ÇOĞUNLUĞU ters yönde oy verirse
    veto eder (veto_fraction). Motor performansları kapanan işlemlerden
    ayrı ayrı ölçülür; ağırlıklar yalnızca paper/backtest sonuçlarından
    güncellenir (canlıda kendi kendine parametre değiştirme YOK).
    """
    enabled: bool = True
    base_vote_weight: float = 2.0            # mevcut resolver sinyali
    veto_fraction: float = 0.75              # ters oy oranı bu eşiği aşarsa HOLD
    min_weight: float = 0.25                 # başarısız motorun alt sınırı
    max_weight: float = 1.5                  # başarılı motorun üst sınırı
    perf_min_trades: int = 10                # ağırlık güncelleme için min işlem
    reversal_rsi_low: float = 30.0
    reversal_rsi_high: float = 70.0


# ---------------------------------------------------------------------------
# ACARBOT v2.0 — marj modu, canlı eşleme, veri kaynağı
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LiveSyncConfig:
    """Borsa entegrasyonu / canlı güvenlik çatısı (şartname madde 9).

    Varsayılan: tamamen KAPALI (yalnızca paper). Testnet/demo eşlemesi
    `--live-testnet` + API anahtarları ile açılır. API anahtarında para
    çekme izni OLMAMALI (manylı kontrol listesi başlangıçta yazdırılır).
    """
    enabled: bool = False
    exchange: str = "binance"                # "binance" (testnet) | "okx" (demo)
    poll_seconds: float = 15.0               # mutabakat yoklaması
    position_tolerance_qty: float = 1e-6     # miktar sapma toleransı
    adopt_exchange_on_drift: bool = False    # driftte borsa doğrusunu benimse
    max_order_age_s: float = 120.0           # bayat emir kurtarma sınırı
    # v4.0: canlı emir katmanı sertleştirme
    entry_style: str = "post_only_market_fallback"
    #   "post_only_market_fallback" (varsayılan): giriş post-only maker limit;
    #   dolum süresi aşılırsa/emir reddedilirse MARKET yedek (yüksek sesle log).
    #   "post_only": saf maker — dolum yoksa eşleme ATLANIR (borsada pozisyon
    #   oluşmaz, mutabakat local_only raporlar).
    #   "market": v3.0 davranışı (hep market).
    entry_fill_timeout_s: float = 60.0       # post-only dolum bekleme süresi
    position_mode: str = "auto"
    #   "auto": borsadan sorgulanır (Binance dualSidePosition / OKX posMode)
    #   ve emirlere positionSide/posSide o modda eklenir.
    #   "one_way" | "hedge": zorla (borsa farklıysa HATA loglanır).
    time_sync: bool = True                   # borsa saat ofseti senkronu
    rate_retries: int = 2                    # 429 Retry-After yeniden denemesi


@dataclass(frozen=True)
class MarginModeConfig:
    """Marj modu: varsayılan ISOLATED (mevcut davranış korunur).

    CROSS (--margin-mode cross): serbest teminat = bakiye + açık PnL -
    kullanılan marj; hesap bazlı likidasyon: equity <= toplam bakım marjı
    → tüm pozisyonlar kapatılır (HARD_HALT). İzole testler ve davranış
    aynen korunur.
    """
    mode: str = "isolated"                   # "isolated" | "cross"
    cross_maintenance_margin_rate: float = 0.004  # hesap bazlı bakım marjı


@dataclass(frozen=True)
class AgentsConfig:
    """v4.0: dış piyasalar/haber/analist ajanları.

    Modlar: "off" | "flag" (risk bayrağı ÜRETİR: log + rapor; işlem AÇMAZ,
    engellemez) | "block" (bayrak aktifken YENİ GİRİŞ engellenir).
    Ajanlar ASLA işlem kararı vermez (kullanıcı şartnamesi).
    """
    us_market_mode: str = "flag"             # SPX/Nasdaq/DXY/VIX risk-on/off
    us_market_refresh_seconds: float = 600.0
    rss_news_mode: str = "flag"              # RSS başlık risk taraması
    rss_news_refresh_seconds: float = 600.0
    analyst_enabled: bool = True             # oturum raporu yorumu (kurallı)
    analyst_llm: bool = False                # LLM yorumu (ortam değişkeni ister)


@dataclass(frozen=True)
class V2Config:
    """v2.0 geliştirme paketinin kök ayarı (tüm alt bloklar)."""
    enabled: bool = True
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    gates: RiskGateConfig = field(default_factory=RiskGateConfig)
    mtf: MtfConfig = field(default_factory=MtfConfig)
    orderflow: OrderFlowConfig = field(default_factory=OrderFlowConfig)
    experts: ExpertConfig = field(default_factory=ExpertConfig)
    margin: MarginModeConfig = field(default_factory=MarginModeConfig)
    live: LiveSyncConfig = field(default_factory=LiveSyncConfig)
    agents: AgentsConfig = field(default_factory=AgentsConfig)
    data_source: str = "perp"                # "perp" | "spot-mirror" (otomatik)
    dashboard_seconds: float = 60.0          # 0 = panel kapalı


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
    news: NewsGuardConfig = field(default_factory=NewsGuardConfig)
    sweep: SweepGuardConfig = field(default_factory=SweepGuardConfig)
    dca: DcaConfig = field(default_factory=DcaConfig)
    v2: V2Config = field(default_factory=V2Config)
    # v5.2: dinamik risk olcekleme (madde 6)
    risk_scaling: RiskScalingConfig = field(default_factory=RiskScalingConfig)
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
