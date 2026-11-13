# ACARBOT v2.0 — Değişiklik Günlüğü (7 Kasım 2026)

Kullanıcı isteği: 9 maddelik geliştirme paketi + 5 uzman motor mimarisi +
"A. Zorunlu (risk)" ve "B. Ölçüm" listeleri — **mevcut sistemi bozmadan,
üstüne ilave ederek**.

Temel ilke korundu: **yama, sıfırdan yazım yok.** v1.2'nin 208 testi
hiçbiri değiştirilmeden AYNEN geçer; v2.0 için 91 yeni test eklendi
(**299/299**).

---

## 0. v2.0.1 ek düzeltme (7 Kasım 2026) — kara liste kaldırıldı

- Kullanıcı talebi üzerine **kara liste tamamen kaldırıldı**: `core/symbols.py`
  içindeki `BLACKLISTED_ASSETS` boşaltıldı, `is_blacklisted` artık her zaman
  `False` döner. Bot USDT-marjinli evrendeki **tüm coinleri** kara liste
  olmadan kabul eder; işlem gören liste yalnızca `--symbols` ile belirlenir.
- Dürüst not: bu modül v2.0'da zaten hiçbir yürütme/backtest akışına
  bağlanmamıştı (dead code); değişiklik davranışı etkilemez, kalıcı olarak
  etkisizleştirildi.
- Sürüüm `2.0.1-final` olarak güncellendi; test paketi değişmeden geçti.

---

## 1. Akıllı piyasa rejimi ve strateji seçimi (`core/regime.py` — YENİ)

- Sınıflandırma yalnızca ADX'e bırakılmaz; **EMA20/50 konumu + EMA20 eğimi,
  ATR değişimi (kısa/uzun ATR oranı), RVOL, piyasa yapısı (HH-HL / LH-LL
  swing analizi) ve BTC yönü** birlikte değerlendirilir.
- Şartnamedeki tablo birebir uygulanır:

  | Piyasa durumu     | Motor önerisi   |
  |-------------------|-----------------|
  | Güçlü yükseliş    | TREND_LONG      |
  | Güçlü düşüş       | TREND_SHORT     |
  | Yatay piyasa      | FADE            |
  | Ani volatilite    | SPIKE + teyit   |
  | Sahte kırılım     | İşlem engeli    |
  | Belirsiz piyasa   | Bekleme (WAIT)  |

- v1.2 `RegimeDetector` AYNEN korundu (mevcut testler/davranış).

## 2. Çoklu zaman dilimi analizi (`core/mtf.py` — YENİ)

- 1m (giriş zamanlaması, canlıda REST), 5m (ana sinyal), **15m (trend onayı),
  1h (ana yön), 4h (büyük yapı)**. Üst TF'ler canlıda REST'ten ayrı görevle
  çekilir (15m/1h/4h periyodik), backtest'te 5m'den TÜRETİLIR (resample).
- **Eksik mum koruması:** resample yalnızca TAMAMLANMIŞ üst TF barlarını
  üretir; canlıda REST listesinin son (forming) mumu atılır.
- Executor'daki v1.2 veri quirk'i (kapanan mumun forming mumun arkasına
  eklenmesi) düzeltildi: forming mum kapanan mumla DEĞİŞTİRİLİR.
- Kural: 5m LONG sinyalinde 15m+1h GÜÇLÜ ters (ADX ≥ 25 + eğim) → işlem
  engellenir (`mtf_uyumsuz`); hafif çelişki → MTF bileşeni puanı düşer.

## 3. Akıllı likidite ve order flow motoru (`core/orderflow.py` — YENİ)

Sweep Guard'ın gelişmiş hâli; yalnızca GERÇEK veri:
- Order book imbalance + bid/ask hacim farkı (±%0.5 bant)
- Büyük emir tespiti (medyan seviye nominalinin katı — mutlak sabit DEĞİL)
- Likidite kümeleri (en yoğun 3 bant)
- Absorption (duvar + durgun fiyat vekil ölçümü, defter geçmişinden)
- **CVD** — canlıda tick kuralı (ticker hacim deltası + fiyat yönü),
  backtest'te mum kuralı (close-open)
- **Open Interest değişimi** — yeni `fetch_open_interest` uçları
  (Binance fapi/openInterest, OKX public/open-interest). **Ayna (spot)
  modunda veya desteklenmeyen borsada "uygulanmadı"** döner; sabit sayı
  konulmaz (kullanıcı kuralı).
- Long/Short sıkışma riski (OI artışı + fiyat aşırılığı)
- Süpürme sonrası dönüş tespiti (aynı bar veya önceki bar süpürme + kapanış
  gerisi)

## 4. Akıllı giriş ve pozisyon yönetimi (`exec/paper.py`, executor)

- **Stop artık keyfî 100$ değil:** ATR + piyasa yapısı tabanlı (v1.2 modeli
  korunup genişletildi); pozisyon büyüklüğü NET parasal riske göre
  (25 USDT tavan, maliyetler dâhil) — v1.2'den korunur.
- **Break-even stopu (YENİ):** +1R'ye ulaşan pozisyonda stop, gidiş-dönüş
  maliyetleri karşılayan başa baş seviyesinin altına inemez (oran
  config'ten hesaplanır).
- Post-only maker emirleri korunur; kısmi dolum yaşam döngüsü aynen.
- **Funding-duyarlı çıkış (YENİ):** kâr bölgesinde bir sonraki funding
  ödemesi kârın %25'inden fazlasını yiyecekse erken çıkış
  (`funding_cost_exit`). Oran bilinmiyorsa "uygulanmadı".
- Emir dolmadığında sinyal bir sonraki mumda doğal olarak yeniden
  değerlendirilir (mevcut TTL akışı).
- ATR trailing, momentum çıkışı, zaman stopu aynen korunur.

## 5. Adaptif puanlama motoru (`core/scoring.py` — YENİ)

Şartnamedeki ağırlık tablosu birebir: **trend 20 + hacim 15 + order flow 20
+ likidite 15 + MTF 15 + BTC 10 + volatilite 5 = 100.**
- 90-100 çok güçlü, 80-89 güçlü, 70-79 normal, **<70 işlem yok**
  (`min_score_to_trade=70`).
- Verisi olmayan bileşen "uygulanmadı" işaretlenir ve **ağırlık paydadan
  düşülür** (yer tutucu puan yazılmaz); raporda `available_fraction`
  şeffaf yer alır.
- Ağırlıklar BAŞLANGIÇTA sabittir; **yapay zekâ canlıda kendi kendine
  işlem parametresi DEĞİŞTİRMEZ.** Optimizasyon yalnızca backtest/paper
  sonuçlarıyla yapılır (`backtest/optimization.py`).

## 6. Gelişmiş portföy yönetimi

- Sınırsız pozisyon tercihi (APEX `--max-positions 0`) korunur; **sınırsız
  pozisyon ≠ sınırsız risk**: pozisyon başı 25 USDT net risk tavanı,
  teminat yeterliliği ve **equity eşiği APEX'te bile her zaman aktif**.
- Korelasyon grupları, grup nominali, toplam açık risk, yönsel denge
  (v1.2'den) + **beta ayarlı yön tavanı (YENİ)**: beta'ları bilinen
  semboller Σ beta×işaretli nominal ile ölçülür; bilinmeyenler yüzey
  değeriyle sayılır.

## 7. Profesyonel backtest ve optimizasyon

- **Monte Carlo (`backtest/montecarlo.py` — YENİ):** bootstrap (iid veya
  blok), p5/p25/p50/p75/p95 final PnL, MaxDD dağılımı, zarar olasılığı,
  ruin olasılığı (varsayılan eşik: v2.0 equity eşiğiyle tutarlı -%15).
- **Parametre duyarlılığı + IS/OOS (`backtest/optimization.py` — YENİ):**
  yalnızca güvenli parametreler (stop/TP/RVOL eşikleri) taranabilir —
  risk tavanlarına dokunan parametre YASAK. En iyi parametreler IS'te
  seçilip OOS'ta doğrulanır; bozulma oranı raporlanır.
- **Kısmi dolum modeli (YENİ):** mum hacminin `bt_participant_cap` (%10)
  payı emre gelir; kalan düşer → ters seçilim gerçekçi.
- **Spread (YENİ):** ölçülmüş `spread_bps` verilirse limit fiyatı yarım
  spread ile kötüleştirilir; verilmezse raporda **"spread simülasyonu:
  uygulanmadı"** yazar.
- Funding geçmişi parametresi (v1.2'den) korunur.
- Metrik paketine **rejim kırılımı (`by_regime`) ve yön kırılımı raporu**
  eklendi; beklenti, ardışık kayıp, MaxDD, Sharpe (v1.2'den).

## 8. Gerçek zamanlı kontrol paneli (`monitor/dashboard.py` — YENİ)

9 bölüm birebir: Genel bakış / Açık pozisyonlar / Sinyal merkezi /
Piyasa tarayıcı / Risk merkezi / Emir merkezi / Strateji analizi
(motor + rejim) / Sistem sağlığı / Performans.
- **"Neden işlem açmadı"** her sembol için şeffaf: BTC yön filtresi,
  MTF uyumsuz, düşük skor (sayıyla), likidite, hız limiti, yeniden giriş
  beklemesi, haber/sweep...
- `--dashboard-seconds` ile periyodik log (varsayılan 60 sn; 0 = kapalı).

## 9. Borsa entegrasyonu güvenlik çatısı (`live/` — YENİ paket)

- **Binance Futures TESTNET** ve **OKX Demo** imzalı istemciler
  (`live/clients.py`, `live/broker_clients.py`); transport enjekte
  edilebilir (testlerde sahte transport, gerçek ağa çıkılmaz).
- **İdempotency:** deterministik clientOrderId (`ACB2-<hash>`), aynı
  sinyal → aynı kimlik; yerel kayıt mükerrer gönderimi engeller.
- **Mutabakat:** yerel pozisyonlar ↔ borsa positionRisk karşılaştırması
  (yön/miktar sapması raporu).
- **Restart kurtarma:** bayat giriş emirleri iptal (max_order_age_s),
  koruyucu stopu olmayan pozisyona sunucu tarafı STOP_MARKET
  (closePosition=true) kurulur.
- **Reduce-only çıkışlar** zorunlu; **acil durum** (`--emergency-flatten`):
  tüm emirler iptal + tüm pozisyonlar reduce-only kapat.
- **API anahtarı güvenlik listesi** başlangıçta loglanır: para çekme izni
  KAPALI olmalı, IP kısıtı, anahtar yalnız ortam değişkeninde.
- **Ayna/spot uyarısı işlendi:** canlı öncesi GERÇEK perp verisiyle test
  için `fetch_perp_candles` (testnet fapi) eklendi; veri kaynağı etiketi
  raporları ayırır (aşağıda).
- Varsayılan TAMAMEN KAPALI; `--live-testnet` + ortam değişkenleriyle
  açılır. Paper moduna dokunmaz.

## A. Zorunlu risk maddeleri (birebir uygulandı)

| # | Madde | Uygulama |
|---|-------|----------|
| 1 | **Cross margin** (`--margin-mode cross`, varsayılan isolated) | serbest teminat = bakiye + açık PnL − kullanılan marj; hesap bazlı likidasyon: equity ≤ Σ bakım marjı → HARD_HALT. İzole davranış ve testler AYNEN. |
| 2 | **Equity eşiği → hepsini kapat + HARD_HALT** | başlangıç bakiyesinin **-%15**'i (1.000$'da 850$). Eşik aşıldığında pozisyonlar KAPATILIR (yalnız "yeni giriş yok" değil); stoplar kapanana dek çalışmaya devam eder. APEX'te de geçerli. |
| 3 | **Beta ayarlı net yön tavanı + BTC şok testi** | betalar GERÇEK 5m kapanış getirilerinden (cov/var, min 50 getiri). Her girişten önce "BTC ∓%3" senaryosunda toplam kayıp, equity'nin **%15**'ini aşarsa giriş engellenir. Beta verisi yoksa test **"uygulanmadı"** sayılır — sabit beta KULLANILMAZ. |
| 4 | **Giriş hız limiti** | dakikada en fazla **3 GERÇEK giriş**; aynı anda gelen adaylar **skora göre** sıralanıp kuyruğa alınır (TTL 90 sn); sayaç yalnız gerçek girişleri sayar. |
| 5 | **Stop sonrası yeniden giriş beklemesi** | stop/likidasyon sonrası **15 dk**; trailing/momentum/zaman çıkışında **5 dk**. |

## B. Ölçüm maddeleri

| # | Madde | Uygulama |
|---|-------|----------|
| 6 | **Gölge sinyal sonucu** | haber/sweep'in engellediği girişler kaydedilir; sonraki **30/60/120 dk** getirisi yön-düzeltilmiş izlenir; "engellemeseydik ne olurdu" özeti oturum raporunda + `shadow_signals` SQLite tablosu. |
| 7 | **Veri kaynağı etiketi** | ayna modu otomatik algılanır; log + oturum raporu + backtest JSON'a **"veri: perp / spot ayna"** yazılır. Sonuçlar karışamaz. |
| 8 | **Oturum raporu eklentileri** | eşzamanlı en yüksek pozisyon, en yüksek marj kullanımı, en düşük serbest teminat, equity tepe ve dip. |
| 9 | **Walk-forward / duyarlılık / dolum kalibrasyonu** | v1.2 walk-forward + yeni IS/OOS grid + duyarlılık raporu + mum-bazlı kısmi dolum modeli. Kurallar: pencereler boğa/ayı/yatay ayrımı walk-forward ile, min işlem sayısı kullanıcı sürecine bağlı (araç hazır). |

## 5 uzman motor + Piyasa Hakemi (`core/experts.py` — YENİ)

1. **Trend Avcısı** — EMA20/50 yığını + MACD + rejim.
2. **Likidite Avcısı** — süpürme-dönüş + defter dengesizliği.
3. **Momentum Avcısı** — RVOL + 10dk bacak + MACD ivmesi.
4. **Reversal Avcısı** — RSI aşırılığı + dönüş mumu.
5. **Piyasa Hakemi** — oyları toplayıp SON KARARI verir.

- v1.2 FADE/TREND çözümleyicisi **"temel oy" (ağırlık 2.0)** olarak
  Hakeme girer; Hakem yalnızca uzmanların **≥%75 ağırlıkla ters** oy
  verdiği durumlarda veto eder → mevcut davranış/testler bozulmaz,
  uç durumlarda çok oyculu koruma devreye girer.
- **Her motorun performansı ayrı ölçülür** (kapanan işlemlerin R'leri);
  ağırlık `clamp(1 + avgR/2, 0.25, 1.5)` ile yalnızca ≥10 işlem sonra
  güncellenir — **kaynak yalnızca paper/backtest sonuçlarıdır**.

## Korunan mevcut kurallar (değişmedi)

1.000 USDT bakiye · 50 USDT teminat · 10x kaldıraç · 500 USDT nominal ·
pozisyon başına 25 USDT NET risk tavanı · maker öncelikli giriş ·
sınırsız pozisyon seçeneği (`--max-positions 0` / APEX) · dinamik stop
(sabit 100$ DEĞİL).

## Yeni CLI bayrakları

```
--no-v2                     v2.0 paketini kapat (v1.2 davranışı)
--margin-mode {isolated,cross}
--equity-floor-pct N        equity eşiği (vars. 15)
--entry-rate-limit N        dakikada gerçek giriş tavanı (vars. 3)
--reentry-cooldown-minutes N  stop sonrası bekleme (vars. 15)
--scoring-threshold N       minimum işlem puanı (vars. 70)
--no-mtf / --no-orderflow / --no-experts
--dashboard-seconds N       panel periyodu (vars. 60; 0 = kapalı)
--live-testnet [--live-exchange binance|okx]   testnet eşleme (kapalı gelir)
--emergency-flatten         acil durum (yalnız --live-testnet ile)
```

Backtest'e Monte Carlo ve spread uygulanır; `backtest_result.json` artık
`monte_carlo`, `shock_tests`, `betas`, `spread`, `data_source` alanlarını
da taşır.

## Testler

- **299/299 geçer** (208 v1.2 + 91 yeni):
  - `test_regime_mtf_orderflow.py` (16): rejim, resample eksik-mum
    koruması, güçlü MTF çelişki engeli, defter ölçümleri, CVD, OI
    "uygulanmadı", süpürme-dönüş.
  - `test_v2_gates_scoring.py` (29): ağırlık toplamı 100, eksik veri
    paydası, <70 engel, Hakem veto/ağırlık adaptasyonu, hız limiti
    (3/dk + skora göre kuyruk), yeniden giriş beklemesi, equity eşiği
    (APEX dahil), beta/şok testi, gölge sinyal.
  - `test_cross_margin_backtest_v2.py` (16): cross serbest teminat, hesap
    likidasyonu, izole korunur, kısmi dolum, rejim/skor etiketleri,
    spread, beta, Monte Carlo, duyarlılık, IS/OOS.
  - `test_v2_integration.py` (12): forming mum değişimi, MTF engeli,
    hız limiti kuyruğu, stop sonrası bekleme, pozisyonda skor/rejim,
    veri kaynağı etiketi, gölge SQLite kalıcılığı, panel bölümleri.
  - `test_live_sync.py` (18): imza doğrulaması (HMAC), anahtar yoksa
    fail-closed, koruyucu stop = STOP_MARKET+closePosition, reduce-only
    çıkış, idempotency, mutabakat, bayat emir iptali, stop kurtarma,
    acil durum, para çekme kontrol listesi.

## Bilinen sınırlar (şeffaf)

- Order flow'un CVD bileşeni canlıda tick-kuralı yaklaşıımıdır (aggTrade
  akışı istenirse `stream_trades` ile değiştirilebilir).
- OI: Binance ayna (spot) modunda ve desteklenmeyen borsalarda
  **uygulanmadı** — sabit sayı yerine konmadı.
- OKX demo'da otomatik emir eşlemesi **uygulanmadı** (mutabakat ve acil
  durum uçları hazırdır); Binance testnet eşlemesi tam çalışır.
- Backtest'te 4h TF, 5m veri uzunluğu yetersizse otomatik "uygulanmadı".
