# PDF v2 indikatör analizi ve uygulama kapsamı

**Tarih:** 2026-10-24  
**Durum:** Teknik paket kodlandı; `pdf-confluence` yalnız opt-in Shadow varyantıdır. Yeni 120 dakikalık run sonucu henüz yok.

## Kaynaklar

Aşağıdaki üç kullanıcı PDF'si metne çıkarılarak karşılaştırıldı; metinler `references/` altında saklanır:

1. **Kripto Futures Bot Indikator Mimarisi** — 3 sayfa.
2. **Kripto Futures Botları Birleşik İndikatör Listesi** — 4 sayfa.
3. **Profesyonel Kripto Futures Botu Veriler ve İndikatörler** — 4 sayfa.

PDF'ler aday teknik/veri kataloğu olarak ele alındı; içlerindeki hiçbir kârlılık iddiası
performans kanıtı sayılmadı.

## Mevcut botta zaten bulunanlar

EMA/SMA ve EMA eğimi, RSI/StochRSI, MACD, ADX/+DI/−DI, ATR, Bollinger/Keltner,
Donchian, Supertrend, VWAP/anchored/session VWAP, OBV/MFI/CCI/Williams %R,
Volume Profile/VPVR, funding, OI, CVD/taker akışı, emir defteri dengesizliği,
likidasyon/squeeze ve MTF filtreleri mevcut akışta kullanılıyor. Bunlar PDF v2
paketinde tekrar skora eklenmedi; baseline ağırlıkları değiştirilmedi.

## v2'de gerçek OHLCV'den eklenenler

`src/pdf_indicators.py` içindeki `pdf_v2_snapshot()` yalnız kapanmış mumları kullanır.
Çıktı `entry_context.indicators.pdf_v2` altında saklanır ve JSON raporlarına girer.

| Aile | Eklenen hesaplar |
|---|---|
| Hareketli ortalamalar | KAMA, HMA, DEMA, TEMA, TRIX |
| Trend / yön | ADXR, DX, Vortex +/−, Ichimoku Tenkan/Kijun/Span A/Span B, Parabolic SAR, Alligator, Linear Regression Channel |
| Momentum | ROC, TSI, Awesome Oscillator, Fisher Transform, WaveTrend WT1/WT2 |
| Rejim / volatilite | Choppiness Index (CHOP), Hurst üssü, realized volatility, Parkinson, Garman–Klass |
| Hacim | Chaikin Money Flow (CMF), Accumulation/Distribution (A/D) ve eğimi, Bollinger %B |
| Çıkış / seviye | Chandelier Exit long/short, klasik pivot R1/R2/S1/S2, Fibonacci 0.382/0.500/0.618 |
| Divergence | RSI ve MACD histogram için onaylanmış swing noktalarına dayalı yön işareti |
| Market structure | BOS, CHoCH, swing high/low, liquidity sweep |
| Price action | Üç-mum FVG, deterministik order-block yaklaşımı, engulfing ve pin-bar |

**Hesaplama notları:**

- Swing noktaları ancak sağ tarafındaki mumlar da kapandıktan sonra kullanılır; oluşan mumdan
  gelecek bilgi alınmaz.
- Ichimoku ve Alligator'da geleceğe bakan grafik kaydırması sinyal hesabına taşınmaz.
- Order-block/FVG/liquidity-sweep tanımları araştırma amaçlı deterministik yaklaşıklardır;
  borsa emir defterinde gerçek likidite veya kurumsal emir kanıtı oldukları iddia edilmez.
- Volatilite değerleri yüzde ve seçilen mum penceresi ölçeğindedir; yıllıklandırılmış getiri
  tahmini değildir.

## Shadow ölçümü

`shadow_lab.pdf_confluence.aktif: true` olduğunda yedinci varyant **pdf-confluence** açılır.
Altı ayrı yön ailesi kullanılır: `trend`, `momentum`, `volume`, `structure`, `regime` ve
gerçek akış/defter gözlemi varsa `derivatives`. Varsayılan deneyde en az **4 uyumlu aile**
ve en fazla **2 karşıt aile** aranır.

Bu varyant kabul ettiği baseline pozisyonunun gerçekleşen aynı kapanış sonucunu eşler;
reddettiği adaylar da ret nedeni ve baseline sonucu ile raporlanır. Baseline giriş/çıkış,
50 USDT marj, sabit 10x, stop, trailing ve order-flow kuralları değiştirilmez. Tek run
sonucunda otomatik parametre optimizasyonu veya canlı kural promosyonu yapılmaz.

## Bilerek eklenmeyen / backlog'da kalanlar

| Madde | Neden bu pakette yok |
|---|---|
| On-chain aktif adres, exchange netflow, borsa rezervi, SOPR, MVRV, NUPL, realized cap, stablecoin supply | Gerçek on-chain sağlayıcı entegrasyonu ve sembol/zaman eşlemesi yok; uydurma seri üretilmedi. |
| Deribit opsiyon OI, 25-delta skew, IV/RV, DVOL, put/call, options funding | Opsiyon veri bağlantısı yok. |
| ETF akımları, makro DXY/NDX/VIX/rates, ekonomik takvim, token unlock | Kaynak/API ve zaman damgası entegrasyonu yok. |
| Reddit/X/Google Trends, geliştirici aktivitesi, duygu hızı | Sosyal/API kaynağı yok; mevcut RSS/Fear&Greed sonucu bu veriler gibi etiketlenmez. |
| Gerçek spoofing/iceberg/layering doğrulaması | 20 kademe anlık snapshot, emir bazlı yaşam döngüsü ve iptal/dolgu geçmişi değildir. |
| Cross-exchange funding/basis, long-short ratio, BTC dominance korelasyonu | Bu koşullarda doğrulanmış seri ve ortak zaman hizası henüz kurulmadı. |
| JMA, FRAMA, VIDYA, T3, HMM/KMeans rejim modeli | Tanım/versiyon veya model eğitim-OOS protokolü netleştirilmeden baseline'a eklenmedi. |
| PDF'lerdeki ATR×1.5 stop, 1.5R/3R kademeli TP ve yüzde-risk önerileri | Aktif kullanıcı kurallarıyla çelişiyor; 50 USDT marj, 10x, kademesiz yapı ve trailing/order-flow çıkışı korunuyor. |

## Kontrollü run

- Profil: `configs/paper-120-v2-control.json`
- Tetik isteği: `configs/paper-120-v2-request.json`
- Workflow profili: `controlled-v2-1000-no-cross-rescue`
- Plan: **1.000 USDT paper kasa, 50 USDT marj, sabit 10x, 120 dakika, Binance+OKX**;
  çapraz kurtarma kapalı, her Shadow varyantı için 1.000 USDT izole sanal kasa.
- **Run:** [40095304624](https://github.com/omeracar56/kripto-bot/actions/runs/40095304624), kod `a5b8d0e`; 2026-10-24 12:46 UTC'de başladı ve son kontrolde `in_progress`.
  Profil çözümü, iki-borsa preflight ve 120 dakika/v2 güvenlik assertleri PASS. Nihai işlem/Shadow
  sonuçları artifact geldikten sonra eklenecek. Başarı veya başarısızlık önceden varsayılmaz.

## Doğrulama

Yerel kontrol: **111 pytest**, Ruff ve compileall PASS. Testler JSON-güvenli çıktı,
sabit/kenar serileri, FVG, yön duyarlı aile oyu ve varyantın varsayılan kapalı/opt-in
olmasını kapsar. Bu sonuçlar yalnız kod/test doğrulamasıdır; canlı piyasa performansı değildir.
