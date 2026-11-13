# Run 40065026239 — 1 Saatlik Paper Genel Analiz

**Run:** [40065026239](https://github.com/omeracar56/kripto-bot/actions/runs/40065026239)  
**Sonuç:** `completed / success` — yaklaşık 60 dakika, job süresi 1 saat 49 saniye  
**Çalışan düzeltme kodu:** `44af949`  
**Başlangıç kasası:** 100.000 USDT sanal para — gerçek emir yok  
**Analiz kaynağı:** `paper-session.txt` (runner artifact'ından kurtarılan, sırları maskelenmiş log) ve `analyze.py`

## 1. Yönetici özeti

- **78 bağımsız giriş**, **4 bağımsız kapanış**, oturum sonunda **74 açık paper pozisyon** vardı.
- **Duplicate kapanış: 0.** Dört kapanışın dördü de farklı position UUID'sine bağlandı; aynı UUID'den ikinci dolgu/kapanış kaydı yok.
- Kapanan işlemlerin **brüt fiyat K/Z'si +9,07 USDT**: 3 kâr, 1 zarar. Örneklem yalnız 4 işlem olduğu için bu oran strateji başarısı olarak genellenemez.
- Kasa **100.000,00 → 100.000,25 USDT**. Funding **−0,0172295 USDT**, kasa mutabakatından çıkarılan toplam komisyon **8,8027705 USDT**. Bu komisyona hâlâ açık olan 74 pozisyonun giriş ücretleri de dahildir.
- **+0,25 USDT kasa değişimi, toplam/net özsermaye K/Z'si değildir.** Açık pozisyonların gerçekleşmemiş K/Z'si kurtarılan log gövdesinde bulunmadığından kesin net özsermaye sonucu bu raporda uydurulmamıştır.
- Çapraz kurtarma **0**, chase order **0**, kademe/kısmî TP **0**. Order-flow kâr çıkışı **3**, trailing stop çıkışı **1**.
- Binance katalog ve kontrat metaverisi istekleri **HTTP 451** verdi. Fiili fiyat evreni **507 OKX paritesi**; bu run iki borsanın başarılı birleşik testi olarak sunulmamalıdır.

## 2. Finansal mutabakat

| Kalem | Sonuç (USDT) | Açıklama |
|---|---:|---|
| Başlangıç kasası | 100.000,0000 | Temiz paper oturumu |
| Gerçekleşen brüt fiyat K/Z | **+9,0700** | 4 bağımsız kapanış |
| Funding | **−0,0172295** | Son istatistik sayacı |
| Toplam komisyon (kasadan türetilen) | **−8,8027705** | Giriş ve kapanış ücretleri; açık pozisyon girişleri dahil |
| Bitiş nakit kasası | **100.000,2500** | PaperBroker bakiyesi |
| Nakit kasa değişimi | **+0,2500** | Özsermaye K/Z'siyle karıştırılmamalı |
| Açık gerçekleşmemiş K/Z | **Logda yok** | 74 pozisyon; tahmin edilmedi |
| Net oturum özsermaye K/Z'si | **Bu logdan doğrulanamıyor** | Günlük rapor gövdesi artifact'a eklenmemişti |

Kullanılan mutabakat:

```text
bitiş kasası = başlangıç kasası + gerçekleşen brüt K/Z + funding − komisyon
100.000,25 = 100.000 + 9,07 − 0,0172295 − 8,8027705
```

Yapılandırmadaki maker %0,02 / taker %0,05 modeliyle yaklaşık ücret **8,79525 USDT**, kasadan türetilen değerden yalnız yaklaşık **0,00752 USDT** farklıdır. Bu, ücret muhasebesinin makul olduğunu destekler; kuruş düzeyindeki fark yuvarlama/fill büyüklüğü etkisidir.

Dört kapanışın yaklaşık round-trip ücreti **1,39525 USDT** (4 giriş + 4 çıkış) olarak hesaplanır. Buna göre yalnız kapanan dört işlemin funding dağıtımı yapılmadan önceki tahmini neti **+7,67475 USDT** olur; bu değer **oturum net K/Z'si değildir**, çünkü diğer 74 açık pozisyonun giriş ücretleri ve funding etkisi toplam kasada bulunur.

## 3. Bağımsız kapanan işlemler

| Sembol | Yön | Çıkış nedeni | Brüt fiyat K/Z (USDT) | Giriş skoru | Rejim |
|---|---|---|---:|---:|---|
| CRO/USDT | SHORT | Order-flow / CVD kâr çıkışı | +2,98 | −36,5 | TREND |
| LRCX/USDT | SHORT | Trailing stop | −0,15 | −28,6 | RANGE |
| A/USDT | SHORT | Order-flow / CVD kâr çıkışı | +2,91 | −30,9 | TREND |
| FARTCOIN/USDT | SHORT | Order-flow / CVD kâr çıkışı | +3,33 | −31,5 | BREAKOUT |
| **Toplam** | **4 SHORT** | **3 order-flow + 1 trailing** | **+9,07** | — | — |

- Kazanma oranı: **%75** (3/4); brüt kâr **+9,22**, brüt zarar **−0,15**, profit factor yaklaşık **61,47**. Bu oranlar **n=4** nedeniyle yalnız betimleyicidir.
- Order-flow çıkışları 3/3 pozitif ve toplam **+9,22 USDT**; trailing çıkışı tek işlemde **−0,15 USDT**. Trailing + order-flow birlikte korunmalı; bu küçük örneklemle eşik optimizasyonu yapılmamalı.
- Kapanan örneklemde LONG yok. Dolayısıyla LONG performansı, LONG/SHORT farkı ve düşük skorlu LONG filtresi bu run'dan değerlendirilemez.

## 4. Oturum sonundaki açık pozisyonlar

Oturum yeni girişleri durdurdu ancak açık pozisyonları zorla kapatmadı. Son heartbeat ile UUID bazlı çıkarım birebir aynı: **78 − 4 = 74 açık pozisyon**.

Yaklaşık kullanılan marj: **74 × 50 = 3.700 USDT**. Bu pozisyonlar gerçek borsada açık pozisyon değildir; GitHub runner'daki paper işlem kayıtlarıdır. Oturum process'i kapandığı için bunlar yeni temiz paper oturumuna taşınmaz.

Açık semboller (74):

```text
ANIME/USDT, NVDA/USDT, RAVE/USDT, CVX/USDT, O/USDT, RLS/USDT,
SMCI/USDT, ALAB/USDT, ARM/USDT, ASML/USDT, BOME/USDT, CIEN/USDT,
FLOW/USDT, GME/USDT, GPRO/USDT, HUT/USDT, LGELECTRONICS/USDT,
MERL/USDT, MSFT/USDT, NES/USDT, OPG/USDT, PENG/USDT, ROK/USDT,
VST/USDT, YGG/USDT, ETH/USDT, ANTHROPIC/USDT, ASTS/USDT,
CSOPSKHYNIX2L/USDT, EGLD/USDT, SECZ/USDT, SEI/USDT, TSLA/USDT,
YFI/USDT, 0G/USDT, APE/USDT, CRWD/USDT, EIGEN/USDT, FLY/USDT,
NFLX/USDT, OL/USDT, V/USDT, ABBV/USDT, ATOM/USDT, BAT/USDT,
COST/USDT, ICP/USDT, IMX/USDT, IREN/USDT, LDO/USDT, LITE/USDT,
MRNA/USDT, NEO/USDT, PNUT/USDT, WEN/USDT, AAVE/USDT, CRDO/USDT,
CRM/USDT, ETC/USDT, EWY/USDT, GOOGL/USDT, HOOD/USDT, KII/USDT,
META/USDT, METIS/USDT, MP/USDT, OUST/USDT, QNT/USDT, SNDK/USDT,
SQQQ/USDT, SUSHI/USDT, TRX/USDT, TWST/USDT, WOO/USDT
```

**Veri sınırlaması:** Oturum sonunda `_format_daily_report()` çalıştı ve rapor Telegram'a gönderildi; ancak workflow yalnız `paper-session.log` dosyasını artifact'a yükledi. Bu nedenle raporun içerdiği kesin açık K/Z ve net özsermaye değerleri GitHub'daki kurtarılmış logda yok. Bu eksiklik sonraki run'lar için düzeltildi; mevcut run için değer tahmin edilmemiştir.

## 5. Giriş ve modül gözlemleri

78 girişin dağılımı:

| Boyut | Dağılım |
|---|---|
| Yön | 63 SHORT / 15 LONG |
| Tetik | 63 PARA_CIKISI / 15 PARA_GIRISI |
| Rejim | 55 TREND / 14 BREAKOUT / 9 RANGE |
| Mutlak skor | 7 adet 0–19,9; 26 adet 20–29,9; 38 adet 30–39,9; 7 adet 40–49,9 |
| MTF | 57 BEARISH / 12 NEUTRAL / 9 BULLISH |
| ML yönü | 44 NOTR / 18 SHORT / 16 LONG |
| Haber vetosu | 0 |

- Giriş bağlamı artık UUID ile loglandığı için RSI/MACD/ADX/MA/Supertrend, MTF, ML, haber ve order-flow bileşenleri aynı pozisyonla eşleştirilebiliyor. Ayrıntılar `analysis.json` içindeki `closed_trade_contexts` bölümündedir.
- Dört kapanışın tamamında MTF **BEARISH**, giriş yönü SHORT ve para çıkışı tetikleyicisi vardı. Bu, kapanan küçük örneklemde MTF + order-flow uyumunu gösterir; tüm evren için kanıt değildir.
- 33/78 girişin mutlak skoru 30'un altındaydı. Bu gözlem düşük skor hipotezini izlemeye değer kılar, ancak yalnız 4 kapanışla skor eşiği değiştirilmemelidir.
- Haber vetosu oluşmadı; haber modülünün bu oturumdaki bağımsız katkısı ölçülemedi. `orderflow_filtered=2`, `mtf_filtered=29`, `regime_filtered=0` olarak raporlandı.

## 6. Borsa ve veri kapsamı

- Katalog: **OKX=507**, fiyat akışı olan parite: **507/507**.
- Binance: katalog ve kontrat metaverisi istekleri **HTTP 451 restricted location**; Binance kapsamı başarılı sayılmadı.
- Heartbeat'teki `borsa=BINANCE` ifadesi aktif primary etiketidir; katalog/veri kapsamının Binance olduğu anlamına gelmez. Bu run'ın sonuçları **OKX-only fiili evren** olarak yorumlanmalıdır.
- Gerçek borsa emri gönderilmedi; bütün dolgular PaperBroker simülasyonudur.

## 7. Risk ve yapılandırma kontrolü

- Her giriş **50 USDT marj / sabit 10x**; teknik notional yaklaşık 500 USDT.
- Başlangıç koruyucu stopu yaklaşık **40 USDT fiyat K/Z** hedefindedir; komisyon/funding/kayma nedeniyle net zarar garantisi değildir.
- Kademe yok, sabit/kısmî TP yok, çapraz kurtarma kapalı, arbitraj kapalı.
- Bu run'da başlangıç stop kapanışı, chase order, kademe ve pair-rescue görülmedi.
- 74 açık pozisyonun varlığı, yalnız kapanan 4 işleme bakarak oturumun toplam risk/performansını değerlendirmeyi yetersiz kılar.

## 8. Bu analizden sonra yapılan küçük gözlenebilirlik düzeltmesi

- `src/main.py`: oturum sonunda kasa, toplam komisyon, funding, açık K/Z, özsermaye, net oturum K/Z'si ve açık pozisyon sayısını ayrı satırda loglar.
- `.github/workflows/paper-live.yml`: `paper-session.log` ile birlikte `reports/gunluk_*.txt` dosyasını da artifact'a ekler.
- Bu değişiklik yeni bir paper run başlatmaz; mevcut run'ın sayıları değiştirilmemiştir.

## 9. Sonuç ve birlikte değerlendirme için öneri

**Teknik sonuç:** Duplicate-close düzeltmesi canlı-veri paper koşusunda doğrulandı; 4/4 kapanış bağımsız ve PaperBroker kasa/ücret mutabakatı tutarlı. Çapraz kurtarma kapalıyken bağımsız pozisyon ölçümü temiz çalıştı.

**Strateji sonucu:** Kapanan küçük örneklemde brüt sonuç pozitif, ancak 74 pozisyon açık kaldığı için bu oturumdan “bot kâr etti” veya “toplam net +9,07” sonucu çıkarılamaz. Kesin genel değerlendirme için açık K/Z'nin raporlandığı daha uzun bir örneklem ve daha fazla bağımsız kapanış gerekir. Mevcut kanıtla parametreleri tek oturuma uydurmak yerine trailing + order-flow yapılandırmasını koruyup sonraki ölçümde LONG/SHORT ve skor gruplarını ayrı izlemek daha sağlıklıdır.
