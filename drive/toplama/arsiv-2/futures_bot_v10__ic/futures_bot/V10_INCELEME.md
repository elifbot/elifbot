# v10 — Yürütme Stresi, Funding Muhasebesi ve Kapsam İncelemesi

Tarih: 28 Ekim 2026  
Durum: **paper / araştırma**. Canlı emir gönderimi yoktur. Bu sürüm `ws_bot` strateji eşiklerini, pozisyon boyutunu, cascade davranışını veya zaman aşımını DEĞİŞTİRMEZ.

## 1. En kritik mimari bulgu

`run_backtest`, `backtests/ablation.py` ve `backtests/walk_forward.py` **canlı `ws_bot` spike/fade stratejisini çalıştırmaz**. Bu altyapı `StrategyBase` türevlerini (ör. `TrendFollowerStrategy`) test eder; canlı bot ise `scanner/spike.py` ve `ws_bot.py` içindeki ayrı karar yolunu kullanır.

Sonuç:

- Mevcut A/B/C/D ablasyonu, canlı spike/fade stratejisinin aile katkısını kanıtlamaz.
- Mevcut walk-forward metrikleri canlı bot için doğrudan OOS kanıtı değildir.
- Önce canlı sinyal/yürütme yolunu aynı kod üzerinden tekrar oynatılabilir hâle getiren bir adaptör gerekir. Bu yapılmadan canlı parametrelerde ablasyon kaynaklı ayıklama yapılmamalıdır.

## 2. v10'da fiilen eklenenler

### 2.1 Gecikme ve kayma stresi

Yeni dosyalar:

- `backtests/execution.py`: yön-aware sabit + ATR'ye bağlı kayma, isteğe bağlı bps tavanı.
- `backtests/stress.py`: aynı veri/strateji için tekrarlanabilir senaryo matrisi.
- `scripts/trade_slippage_stress.py`: mevcut kapanmış işlem CSV'lerinde aynı işlem yolunu sabit tutan maliyet duyarlılığı.

`BacktestConfig` alanları:

- `latency_ms` (varsayılan 0)
- `slippage_bps` (varsayılan 0)
- `slippage_atr_fraction` (varsayılan 0)
- `max_slippage_bps` (varsayılan sınırsız)

Gecikme açıkken sinyal anında doldurulmaz; bekleyen giriş, koşul sağlanan sonraki mumun açılışından açılır. Kayma LONG/SHORT giriş ve çıkışta daima aleyhtedir. Stop ve hedef fill'lerine de stres uygulanır. Açık pozisyonun backtest sonundaki kapanış fiyatı artık son işlenen mumdan alınır.

**Sınır:** Bu model emir defteri, kuyruk önceliği, kısmi dolum, maker fill olasılığı veya gerçek milisaniye fiyat yolu simülasyonu değildir. Mum tabanlı muhafazakâr bir stres varsayımıdır.

### 2.2 Olay bazlı funding muhasebesi

`PaperPortfolio.apply_funding(...)` eklendi:

- Pozitif oranda LONG öder, SHORT alır; negatif oranda tersidir.
- Tutar, olay anındaki mark fiyatı × miktar × oran üzerinden hesaplanır.
- Bakiye olay anında güncellenir; kapanışta funding ikinci kez bakiyeden düşülmez.
- Kapanan işlemin `realized_pnl` değeri funding'i bir kez içerir.
- Funding verisi yoksa CSV'de `bilinmiyor` yazılmaya devam eder; teyitsiz sıfır kullanılmaz.

**Sınır:** Funding/OI/mark-price public feed'leri hâlâ stub'dır. Geçmiş funding takviminin toplanması ve funding kaynaklı tasfiye bu pakette yoktur. Muhasebe hazır olmak, verinin mevcut olduğu anlamına gelmez.

### 2.3 Yürütme varsayımlarının OOS parmak izi

Walk-forward `params_hash` hesabına gecikme/kayma alanları ve basit public strateji parametreleri eklendi. İç içe feed/alt-strateji nesneleri için tam, kararlı canlı parametre manifestosu hâlâ gereklidir.

### 2.4 Testler

- v10 tam regresyon: **187 passed**.
- Yeni testler: kayma yönü/tavanı, gecikmeli dolum, stres matrisi izolasyonu, funding'in bir kez muhasebeleşmesi, bilinmeyen funding etiketi ve CSV stres betiği.

## 3. Ölçülen kayma duyarlılığı

Aşağıdaki CSV analizi yeni bir backtest değildir. Aynı işlemlerin miktarını/yolunu sabit tutar; giriş ve çıkış fill'lerinin **her birinde ayrı ayrı** belirtilen bps kadar aleyhte kayma varsayar ve ücretleri yeniden hesaplar. Funding **bilinmiyor**.

### 3.1 v8 — 36 kapanmış işlem

| İşlem başına kayma (giriş ve çıkış ayrı) | Net PnL (USDT) | Kazanan işlem |
|---:|---:|---:|
| 0 bps | -5,880931 | 20/36 |
| 5 bps | -14,906211 | 16/36 |
| 10 bps | -23,931492 | 12/36 |
| 20 bps (%0,20) | **-41,982053** | 10/36 |

Yorum: Bu örneklemde başlangıç net kenarı zaten negatiftir. Dolayısıyla “%0,20 kayma kenarı sıfırlıyor mu?” sorusunun yanıtı: **kenar varken sıfırlanmıyor; baştan negatif ve kaymayla çok daha kötüleşiyor.**

Çıktı: `V8_KAYMA_STRES.json`.

### 3.2 v9 ikinci 15 dakikalık paper testi

Durum dosyası: 903 saniye, `calisiyor=false`, 76 sinyal, 42 açılan ve 42 kapanan işlem, açık pozisyon 0, bakiye 985,7363 USDT, toplam PnL **−14,2637 USDT**.

Ancak `live_trades.csv` içinde yalnızca **41 işlem** vardır ve bu satırların toplamı **−17,751776 USDT**dir. Durum/bakiye ile CSV arasında yaklaşık **+3,4881 USDT** fark vardır. Log dosyası da 07:21'de donmuş görünürken durum dosyası 07:28:24'e kadar ilerlemiştir. Eksik işlemin ayrıntısı mevcut dosyalardan güvenilir biçimde geri kurulamaz; uydurulmamıştır. Bu nedenle aşağıdaki stres tablosu yalnızca CSV'deki 41 kayda aittir:

| İşlem başına kayma | Net PnL (USDT) | Kazanan işlem |
|---:|---:|---:|
| 0 bps | -17,751776 | 19/41 |
| 5 bps | -28,014943 | 16/41 |
| 10 bps | -38,278111 | 14/41 |
| 20 bps (%0,20) | **-58,804445** | 14/41 |

CSV'deki 41 kaydın kapanış nedenleri: 8 take-profit, 5 stop-loss, 28 session-end. Funding alanlarının tamamı `bilinmiyor`.

Çıktı: `V9_15DK_KAYMA_STRES.json`.

**Sonuç:** Kısa paper testi ve 20 bps stresi mevcut hâliyle pozitif, güvenilir bir kenar göstermiyor. 42/41 mutabakat sorunu giderilmeden bu CSV tek başına nihai denetim kaydı sayılmamalıdır.

Tekrar üretme:

```bash
python3 scripts/trade_slippage_stress.py live_trades.csv --bps 0 5 10 20
```

## 4. İstenen başlıkların incelemesi

### 4.1 300+ işlem örneklemi ve parametre dondurma

- Aynı kod/ayarla 300+ yeni, ardışık ve bağımsız dönemleri kapsayan işlem gerekir.
- Farklı sürüm veya parametrelerden gelen 36, 41/42 gibi kümeleri tek bir örneklem gibi birleştirmek yanıltıcıdır.
- Her koşuda kod sürümü, tam strateji parametre manifestosu, veri başlangıç/bitiş zamanı, borsa/evren listesi ve maliyet varsayımları saklanmalıdır.
- v10 çevrimdışı analiz ekler; v9 canlı/paper strateji eşiklerini değiştirmez. v10'un canlı koşuya alınması ise yeni bir koşu kimliği gerektirir.

### 4.2 Küçük hacimli coinler ve “büyük 25” evreni

Mevcut tarama top-25 ile sınırlı değildir: testte Binance için 523 USDT perpetual, OKX için 289 swap enstrümanı tabanı görüldü. Küçük coinler zaten kapsama girebiliyor.

Bundan sonrası körlemesine evren büyütmek değil, sonuçları şu likidite kovalarına ayırmaktır:

- 24 saatlik quote hacim,
- spread bps,
- top-of-book ve derinlik,
- tahmini piyasa etkisi,
- sembolün tarihsel evrende bulunma durumu (survivorship bias).

Spread/derinlik yokken küçük coin paper getirisi gerçekçi kabul edilmemelidir.

### 4.3 Dinamik cascade (≥10 sembol / 30 sn)

- Mevcut sayaç 60 saniyeliktir; `cascade_esik` varsayılanı 0'dır, yani filtre kapalıdır.
- ≥10/30 sn dinamik modu mevcut değildir.
- Cascade anında pozisyon boyutunu artırmak, korelasyonlu tasfiye hareketlerinde riski büyütür; ilk uygulama yalnızca **SHADOW ölçüm** olmalıdır.
- Pozisyon boyutu veya timeout değişikliği, ayrı OOS ve 300+ örneklem olmadan etkinleştirilmemelidir.

### 4.4 Ablasyon

Altyapıda `disabled_families`, `family_enabled`, `_req` ve BASE/A/B/C/D çalıştırıcısı vardır. Fakat:

- Tek veri seti karşılaştırması nedensellik kanıtı değildir.
- Leave-one-out yanında leave-one-in ve aile etkileşimleri de ölçülmelidir.
- Aynı walk-forward pencereleri ve aynı yürütme maliyetleri kullanılmalıdır.
- En önemlisi, canlı spike/fade stratejisi bu arayüze bağlanmadan sonuçlar canlı bota taşınmamalıdır.

### 4.5 Funding, OI, mark price ve CVD (F ailesi)

- F ailesi ağırlığı sıfırdır; veri yokluğu doğru biçimde işaretlenmektedir.
- Funding/OI/mark-price feed'leri `DataUnavailableError` fırlatan stub'lardır.
- CVD/orderbook veri katmanı yoktur.
- Funding muhasebesi v10'da eklendi ancak bu, F sinyalinin doğrulandığı anlamına gelmez.
- CVD için agresör tarafı ayrıştırılmış trade verisi gerekir; yalnızca mum hacmi CVD yerine kullanılmamalıdır.
- Veri gelene kadar F ailesi sinyal kanıtı gibi kullanılmamalıdır.

### 4.6 Walk-forward, rejimler ve tek güne bağımlılık

Mevcut walk-forward'da eğitim penceresi optimizasyon için değil ısınma/bağlam için kullanılır. Eksikler:

- Canlı strateji adaptörü,
- pozisyon taşınma süresi gözetilerek purge/embargo,
- yatay / sert düşüş / yüksek volatilite kovaları,
- pencere ve gün bazında katkı dağılımı,
- 24.10 gibi tek günün toplam PnL'ye katkısı ve leave-one-day-out duyarlılığı,
- birden çok dönem ve borsa üzerinde aynı maliyet varsayımları.

Mevcut kısa snapshot'lar ve 15 dakikalık koşu bu analizler için yeterli tarihsel kapsam sağlamaz. Bu nedenle rejim başarısı veya tek günden bağımsızlık bu pakette kanıtlanmış değildir.

## 5. Önerilen uygulama sırası

1. 42/41 kayıt mutabakatını ve koşu manifestosunu düzelt; tamamlanmamış/kopyalanmış loglarla ölçüm yapma.
2. Canlı spike/fade sinyalini backtest replay'e bağla; aynı kod yolunu kullan.
3. Likidite kovaları + gecikme/kayma + funding olaylarıyla OOS/stres matrisini çalıştır.
4. Rejim ve leave-one-day-out analizlerini ekle; sonra ablasyon kararı ver.
5. Funding/OI/mark/CVD feed'lerini ayrı ayrı doğrula; F ailesini SHADOW'da tut.
6. Dinamik cascade'i önce yalnızca logla; boyut/timeout değiştirme.
7. Aynı dondurulmuş yapılandırmayla 300+ işlem topla.

## 6. Teslim sınırı

v10, istenen bütün araştırma başlıklarını bitmiş saymaz. Bu paket **yürütme stresi ve funding muhasebesi altyapısını** ekler; canlı strateji adaptörü, gerçek F veri katmanı, tam rejim/OOS analizi ve 300+ örneklem hâlâ açık işlerdir.
