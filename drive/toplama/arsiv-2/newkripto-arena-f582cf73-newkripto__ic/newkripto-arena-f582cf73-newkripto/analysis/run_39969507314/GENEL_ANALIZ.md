# 6 Saatlik Paper Oturumu — Genel Performans ve Modül Analizi

**Tarih:** 2026-10-24  
**Oturum:** [GitHub Actions run 39969507314](https://github.com/omeracar56/kripto-bot/actions/runs/39969507314)  
**Çalışan kod:** `de4f137`  
**Veri:** `analysis/run_39969507314/paper-session.txt` — 2.502 satır  
**Mod:** 100.000 USDT sanal kasa, 50 USDT marj, sabit 10x; gerçek para/emir yok.

> İşlem bazlı giriş/çıkış ve indikatör sınırlamalarının ayrıntılı karşılaştırması: [INDIKATOR_KYAS.md](INDIKATOR_KYAS.md)

## 1. Yönetici özeti

Bu oturumdan **“RSI iyi, MACD kötü”** şeklinde güvenilir bir sonuç çıkarılamaz; giriş anındaki indikatör bileşenleri işlem bazında kaydedilmemiştir. Buna karşılık log, daha temel iki sorunu açıkça göstermektedir:

1. **Kapanış yarışı ve mükerrer paper muhasebesi raporlanan zararın en büyük kaynağıdır.** 160 açılışa karşı 1.032 kapanış kaydı vardır. Her açılışı ilk kapanışıyla eşleştirince 160 bağımsız kapanış ve 872 mükerrer kapanış bulunur.
2. **Mükerrer kayıtlar çıkarıldığında bile strateji ücret sonrası zarardadır.** Özellikle çapraz kurtarma ve SHORT tarafındaki kazanç/kayıp asimetrisi zayıftır.

Dolayısıyla yeni uzun testten önce önce kapanış bütünlüğü düzeltilmeli, sonra çapraz kurtarmalı/kurtarmasız kontrollü karşılaştırma yapılmalıdır.

## 2. Raporlanan sonuç ve mükerrer kayıt analizi

| Kalem | Sonuç |
|---|---:|
| Başlangıç kasası | 100.000,00 USDT |
| Bitiş kasası | 99.203,80 USDT |
| **Raporlanan net K/Z** | **−796,20 USDT (%−0,796)** |
| Açılış satırı | 160 |
| İlk/gerçek kapanışla eşleşen pozisyon | 160 |
| Kaydedilen toplam kapanış | 1.032 |
| **Mükerrer kapanış** | **872 (%84,5)** |
| İlk kapanışların brüt fiyat K/Z’si | −57,47 USDT |
| Mükerrer kapanışların ek brüt K/Z’si | −464,92 USDT |
| Kayıtlardaki toplam brüt fiyat K/Z’si | −522,39 USDT |
| Kasa mutabakatından hesaplanan toplam komisyon | −273,92 USDT |
| Funding | +0,11 USDT |

Mutabakat:

```text
100.000 − 522,39 − 273,923 + 0,113 = 99.203,80 USDT
```

Ücret yapısı da mükerrer etkiyi doğrulamaktadır. 500 USDT yaklaşık notional ile:

- 160 giriş × yaklaşık 0,10 USDT maker ücreti ≈ **16 USDT**.
- 1.032 kapanış × yaklaşık 0,25 USDT taker ücreti ≈ **258 USDT**.
- 872 mükerrer kapanışın payı ≈ **218 USDT**.

Aynı ilk kapanışlar kullanılıp yalnız normal 160 giriş/160 kapanış ücreti uygulanırsa duyarlılık sonucu:

```text
−57,47 brüt K/Z − yaklaşık 56,00 ücret + 0,11 funding
= yaklaşık −113,36 USDT
```

Bu **−113,36 USDT temiz bir yeniden backtest değildir**. Yarış olmasaydı fiyatlar, işlem sırası ve sonraki kararlar değişebilirdi. Yalnızca mükerrer muhasebenin ölçeğini gösterir. Mükerrer brüt K/Z ve tahmini mükerrer ücretler birlikte raporlanan net zararın yaklaşık **%86’sını** açıklamaktadır.

## 3. Mükerrer kapanışın teknik nedeni

Çalışan `de4f137` koduyla dosya bütünlükleri karşılaştırılmıştır. Kod yolunda:

- `on_trade` ve `on_price`, `executor.on_price_tick()` çağrısını eşzamanlı yapabilmektedir.
- `_close()` önce pozisyonu okur, sonra kapama emrine `await` ile gider; pozisyonu listeden çıkarma işlemi emir dönüşünden sonradır.
- Birden fazla görev aynı pozisyonu listede görüp kapama emrine girebilmektedir.
- Paper broker her kapamayı dolu kabul etmekte, gerçek pozisyon miktarı/reduce-only bütünlüğünü doğrulamamaktadır.
- Her tekrar için ücret alınmakta, brüt K/Z kasaya yeniden yazılmakta ve işlem sayacı artırılmaktadır.

İlk dakikalardaki örnek bunu açık gösterir: CYPH ve ON pozisyonları için dakika 9 istatistiği, iki fiziksel pozisyon yerine **17 kapanış** saymıştır.

**Sonuç:** 1.032 işlem ve %49,8 raporlanan kazanma oranı bağımsız işlem örneği olarak kullanılamaz.

## 4. Temizlenmiş 160 ilk kapanışın genel görünümü

| Ölçüt | Sonuç |
|---|---:|
| Pozisyon | 160 |
| Kazanç / kayıp / başa baş | 82 / 77 / 1 |
| Kazanma oranı | %51,25 |
| Brüt K/Z | −57,47 USDT |
| Profit factor | 0,783 |
| Ortalama kazanç | +2,53 USDT |
| Ortalama kayıp | −3,44 USDT |
| Pozisyon başına ortalama brüt K/Z | −0,36 USDT |
| Yaklaşık normal ücret | 56,00 USDT |

Kazanma oranı tek başına yeterli değildir. Ortalama kayıp, ortalama kazançtan yaklaşık %36 daha büyüktür. Bu dağılımla brüt başa baş için yaklaşık %57,6 kazanma oranı gerekir; 0,35 USDT yaklaşık gidiş-dönüş ücreti eklenince gereken oran yaklaşık **%63,5** olur. Gerçekleşen %51,25 bunun altındadır.

### LONG / SHORT ayrımı

| Yön | N | Kazanma | Brüt K/Z | Profit factor | Yaklaşık ücret sonrası* |
|---|---:|---:|---:|---:|---:|
| LONG | 73 | %47,9 | −5,87 | 0,953 | −31,42 |
| SHORT | 87 | %54,0 | −51,60 | 0,632 | −82,05 |

\* Pozisyon başına yaklaşık 0,35 USDT; funding dağıtılmamıştır.

SHORT’ta kazanma oranı daha yüksek olmasına rağmen ortalama kazanç **+1,89**, ortalama kayıp **−3,60 USDT**dir. Kayıplar kazançların yaklaşık 1,9 katı olduğu için sonuç belirgin negatiftir. LONG brüt olarak başa başa yakındır ama ücretleri karşılayan bir avantaj göstermemektedir.

## 5. Çıkış modüllerinin sonucu

Aşağıdaki tablo 160 ilk kapanışı kullanır. Ücret sonrası sütun yaklaşık 0,35 USDT/pozisyon varsayımıdır.

| Çıkış modülü | N | Pay | Brüt K/Z | Yaklaşık ücret sonrası |
|---|---:|---:|---:|---:|
| **Çapraz kurtarma — iki bacak toplamı** | **119** | **%74,4** | **−75,67** | **−117,32** |
| Order-flow / CVD kâr koşusu | 7 | %4,4 | +49,29 | +46,84 |
| Trailing stop | 8 | %5,0 | +1,29 | −1,51 |
| Flash Crash sigortası | 23 | %14,4 | −7,20 | −15,25 |
| Haber vetosu + kâr koruma | 2 | %1,3 | +9,74 | +9,04 |
| Başlangıç marj stopu | 1 | %0,6 | −34,92 | −35,27 |

### 5.1 Çapraz kurtarma — bu oturumun en zayıf strateji modülü

- Artı bacak: 61 pozisyon, **+139,85 USDT**.
- Tersteki bacak: 58 pozisyon, **−215,52 USDT**.
- Toplam: **−75,67 USDT brüt**, yaklaşık **−117,32 USDT ücret sonrası**.
- Artı bacak ortalaması **+2,29**, tersteki bacak ortalaması **−3,72 USDT**dir.
- “Artı bacak” olarak kapatılan VICR, TEAM ve FLY pozisyonları da fiilen zarar yazmıştır.

Ayarlar kurtarmanın ikili bazda yaklaşık −2 USDT’ye kadar zararı kabul etmesine izin verir. Yaklaşık 60 ikili kurtarma tekrarlandığında küçük zararlar ve iki tarafın ücretleri birikmiştir. Modül büyük stopları sınırlamış olabilir; ancak bunun alternatif senaryosu bu logda yoktur. Ölçülebilen gerçekleşen sonuç negatiftir ve kurtarma kâr koşusunu çoğu pozisyonda order-flow/trailing yerine devralmıştır.

### 5.2 Order-flow / CVD — umut veren fakat küçük örnek

- 7 kapanışın 7’si pozitif, toplam **+49,29 USDT brüt**.
- IRYS tek başına **+29,69 USDT**dir.
- IRYS çıkarıldığında kalan 6 işlem **+19,60 USDT**dir ve tamamı pozitiftir.

Bu, oturumun en olumlu çıkış modülüdür; ancak yalnız kârdaki pozisyonları yönetir ve örnek sayısı küçüktür. Bir giriş indikatörünün başarısı olarak yorumlanmamalıdır.

### 5.3 Haber vetosu — olumlu, çok küçük örnek

KMNO ve RECALL kâr koruma çıkışları toplam **+9,74 USDT**dir. İki örnekle haber modelinin genel kalitesi hakkında karar verilemez.

### 5.4 Trailing/Supertrend — nötr/zayıf

8 trailing kapanışı toplamı yalnız **+1,29 USDT brüt**, yaklaşık ücret sonrası **−1,51 USDT**dir. 28 Supertrend trail güncellemesi sayacı vardır fakat bağımsız faydasını göstermez. Bu oturumda trailing ana sorun değildir; belirgin bir avantaj da kanıtlanmamıştır.

### 5.5 Başlangıç stopu — ana zarar kaynağı değil

Yalnız INIT pozisyonu başlangıç marj stopuyla **−34,92 USDT** kapanmıştır. Stop formülü veya %80 etiketi genel zararın kaynağı değildir; işlem başına kabul edilen risk gerçekleşmiştir.

### 5.6 Flash Crash sigortası

IRYS’teki %8,69 hareket sonrası 23 pozisyon kapanmış ve bot yaklaşık son **56 dakika** kilitli kalmıştır. Bu kapanışların brüt sonucu −7,20 USDT’dir. Tek semboldeki şokun bütün portföyü durdurması ve kalan sürede yeni sinyal üretilememesi ayrıca gözden geçirilmelidir; fırsat maliyeti bu logla ölçülemez.

## 6. Giriş sinyali ve skor analizi

160 girişin tamamı alternatif **PARA_GIRISI / PARA_CIKISI** tetik yolunu kullanmıştır; hiçbiri ana ±55 toplam skor eşiğiyle açılan standart sinyal değildir. Bu nedenle oturum esas olarak güçlü para akışı + en az 10 teknik onay + en az 15 toplam skor yolunu test etmiştir.

| Mutlak toplam skor | N | Kazanma | Brüt K/Z |
|---|---:|---:|---:|
| 0–19,9 | 24 | %41,7 | −15,54 |
| 20–29,9 | 55 | %54,5 | +5,22 |
| 30–39,9 | 54 | %51,9 | −52,95 |
| 40–49,9 | 26 | %50,0 | +2,94 |
| 50+ | 1 | %100,0 | +2,86 |

Skor arttıkça sonuç düzenli biçimde iyileşmemektedir. Ücretler eklendiğinde küçük pozitif gruplar da negatife dönmektedir. Dolayısıyla yalnız eşiği yükseltmek için yeterli kanıt yoktur.

İki izlenecek hipotez:

- **LONG |skor| 15–19,9:** 19 işlem, **−20,61 USDT brüt**.
- **SHORT |skor| 30–39,9:** 36 işlem, **−59,31 USDT brüt**.

Bunlar tek oturumluk gözlemlerdir; kalıcı kurala çevirmeden önce yeni veri ve A/B testi gerekir.

## 7. Hangi indikatörler hakkında karar verilemez?

Giriş kaydında yalnız toplam skor ve para akışı tetiği bulunur. RSI, MACD, MA/EMA, ADX, Supertrend, MTF, haber ve ML bileşenlerinin her girişteki ayrı değerleri işlem kimliğiyle saklanmamıştır. Bu yüzden aşağıdaki kesin etiketler **veriyle desteklenmez**:

- “RSI iyi/kötü”
- “MACD faydasız”
- “ML kazandırıyor/kaybettiriyor”
- “MTF zararı önlüyor”

Sayaçlarda MTF filtresi 131, order-flow filtresi 6, rejim filtresi 0 ve Supertrend trail güncellemesi 28 görülür. Bunlar yalnız aktivite sayacıdır; engellenen işlemlerin alternatif K/Z’si olmadan fayda ölçülemez. Rejim sayacının 0 olması da indikatörün faydasız olduğunu kanıtlamaz.

Bunları ayırmak için her pozisyona benzersiz kimlik ve giriş anındaki RSI/MACD/ADX/MA/Supertrend/MTF/ML/haber/order-flow değerleri kaydedilmeli; ardından aynı veri üzerinde bileşen çıkarma (ablation) ve walk-forward testleri yapılmalıdır.

## 8. Veri ve kapsam sınırlamaları

- Binance katalog isteği çalışma ortamında HTTP 451 bölge/uygunluk kısıtı vermiştir. Evren fiilen **508 OKX paritesi** olarak kurulmuştur; sonuç gerçek bir Binance+OKX birleşik testi değildir.
- 10x desteklemeyen 2 parite yalnız analiz edilmiştir.
- TEST002 için yeterli mum olmadığına dair tekrarlı veri hataları vardır.
- Tek 6 saatlik dönem ve değişen haber/rejim koşulları vardır; modül sonuçları başka dönemlerde farklılaşabilir.

## 9. Öncelikli aksiyon planı

### P0 — Yeni oturumdan önce zorunlu

1. Kapama akışını sembol bazında kilitli ve idempotent yap; kilit alındıktan sonra pozisyonu yeniden doğrula.
2. Çapraz kurtarma kararını tek sıraya al; aynı çift için eşzamanlı kurtarma denemelerini engelle.
3. Paper broker’da reduce-only ve kalan pozisyon miktarını doğrula; ikinci kapamaya ücret/KZ yazma.
4. Regresyon testi: aynı pozisyona 100 eşzamanlı kapama isteği → **1 dolgu, 1 ücret, 1 işlem kaydı**.

### P1 — Strateji karşılaştırması

5. İlk kontrollü ölçümde çapraz kurtarmayı kapat; aynı hataya karşı korumalı motorla kurtarmalı/kurtarmasız A/B testi yap.
6. Order-flow/CVD çıkışını koru fakat en az 100 bağımsız örnek toplamadan parametre optimizasyonu yapma.
7. SHORT ve düşük skorlu LONG gruplarını ayrı raporla; yalnız kazanma oranına değil, ücret sonrası beklenti ve profit factor’a bak.
8. İşlem başına beklenen brüt avantajın en az ücret + kaymayı karşılamasını iste; 0,35 USDT ücretin küçük kazançları sildiğini hesaba kat.

### P2 — Ölçüm ve evren

9. Girişte bütün indikatör bileşenlerini ve benzersiz pozisyon/kapama kimliklerini kaydet.
10. Flash Crash’ın tek sembolle tüm portföyü kilitleme kuralını gözden geçir.
11. Binance+OKX birleşik performans iddiası için Binance’e erişimin desteklendiği bir çalışma ortamında ayrı doğrulama yap.

## Sonuç

**Ana sorun yalnız “kötü indikatör” değildir.** Önce mükerrer kapama/muhasebe hatası, ardından çapraz kurtarmanın baskın ve negatif çıkış davranışı, işlem ücretleri ve SHORT tarafındaki kazanç/kayıp asimetrisi gelir.

Order-flow/CVD ve haber kâr koruma olumlu sinyal vermiştir ama örnekleri küçüktür. Trailing nötrdür. RSI/MACD/ML/MTF gibi bileşenler hakkında adil karar için daha ayrıntılı işlem bazlı kayıt ve kontrollü test gerekir. Mevcut haliyle bu oturum, botun canlı/gerçek para kullanımına hazır olduğunu göstermez.
