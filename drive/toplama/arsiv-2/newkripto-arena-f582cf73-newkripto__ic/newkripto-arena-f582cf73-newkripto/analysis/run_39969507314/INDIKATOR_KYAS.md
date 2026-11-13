# Run 39969507314 — Kazandıran ve Kaybettiren Modül / İndikatör Ayrımı

**Oturum:** 5 saat 55 dakikalık paper oturumu  
**Çalışan kod:** `de4f137`  
**Esas örneklem:** 160 bağımsız primary kapanış  
**Dışlanan kayıtlar:** 872 duplicate kapanış  
**Veri:** `paper-session.txt`, `reports/run_39969507314/analysis.json` ve `summary_full.json`

## 1. Kısa cevap

Bu eski oturumdan **“RSI kazandırdı, MACD kaybettirdi”** sonucu çıkarılamaz. Giriş satırlarında RSI, MACD, ADX, MA/EMA, Supertrend, MTF ve ML değerleri pozisyon kimliğiyle saklanmamış; yalnızca toplam skor ve para-akışı tetiği var.

Buna karşılık aşağıdaki sonuçlar doğrudan ölçülebiliyor:

- **En olumlu çıkış modülü:** order-flow/CVD kâr çıkışı — 7/7 pozitif, **+49,29 USDT brüt**. Ancak 29,69 USDT'si tek IRYS işleminden geliyor.
- **En olumsuz modül:** çapraz kurtarma — 119 pozisyon, **−75,67 USDT brüt**. Bu bir giriş indikatörü değil, pozisyonları kapatan ayrı bir çıkış mekanizması.
- **Girişte para-akışı tetiği:** 160 işlemin tamamında kullanılmış, fakat iki yönün toplamı da ücret öncesi zararda. Dolayısıyla “para akışı girişi kazandırıyor” denemez.
- **RSI/MACD/ADX/MA/Supertrend/MTF/ML:** eski oturum için işlem bazlı kazanan/kaybeden sıralaması **veri yokluğu nedeniyle yapılamaz**.

## 2. Önemli ayrım: giriş sinyali ≠ çıkış sonucu

Logdaki `skor`, tek başına teknik indikatör skoru değildir. Stratejinin teknik + para akışı + haber + ML bileşenlerinden ürettiği **toplam skor**dur. Bir pozisyonun kâr etmesi, girişteki bütün indikatörlerin doğru olduğunu; zarar etmesi de hepsinin yanlış olduğunu göstermez.

Özellikle çapraz kurtarma ile kapatılan bir pozisyonun sonucu, giriş indikatörüne değil, iki pozisyonun birlikte netlenmesi kararına aittir. Bu nedenle aşağıda giriş ve çıkış tabloları bilinçli olarak ayrılmıştır.

## 3. Giriş tetiği kazandıranı veya kaybedeni ayırabiliyor mu?

| Giriş tetiği | Pozisyon | Kazanç / kayıp / başa baş | Kazanma | Brüt K/Z | Yaklaşık ücret sonrası* |
|---|---:|---:|---:|---:|---:|
| `PARA_GIRISI` → LONG | 73 | 35 / 38 / 0 | %47,9 | −5,87 | −31,42 |
| `PARA_CIKISI` → SHORT | 87 | 47 / 39 / 1 | %54,0 | −51,60 | −82,05 |

\* Pozisyon başına yaklaşık 0,35 USDT gidiş-dönüş ücret; funding dağıtılmamıştır.

**Yorum:** SHORT tarafında kazanma oranı daha yüksek olmasına rağmen ortalama kazanç +1,89, ortalama kayıp −3,60 USDT'dir. Yani tetikleyici, kayıpları sınırlayan bir avantaj üretmemiştir. LONG tarafı brüt olarak başa başa yakın olsa da ücretleri karşılamamaktadır.

Ayrıca 160 girişin tamamı alternatif para-akışı yoludur; standart ±55 toplam skor eşiğiyle açılan işlem yoktur. Bu oturum esas olarak “güçlü para akışı + sınırlı teknik onay” giriş kuralını test etmiştir.

## 4. Toplam skor ile sonuç ilişkisi

| Mutlak toplam skor | N | Kazanma | Brüt K/Z | Yaklaşık ücret sonrası |
|---|---:|---:|---:|---:|
| 0–19,9 | 24 | %41,7 | −15,54 | −23,94 |
| 20–29,9 | 55 | %54,5 | +5,22 | −14,03 |
| 30–39,9 | 54 | %51,9 | −52,95 | −71,85 |
| 40–49,9 | 26 | %50,0 | +2,94 | −6,16 |
| 50+ | 1 | %100,0 | +2,86 | +2,51 |

Skor arttıkça sonuç düzenli iyileşmemektedir. Bu tablo tek başına skor eşiğini yükseltmek için yeterli kanıt değildir; çıkış modülünün etkisini de içerir.

### Yön ve skor kesişimi — kritik kontrol

| Grup | Tüm işlemler | Kurtarma işlemleri | Kurtarmasız işlemler |
|---|---:|---:|---:|
| LONG, skor 0–19,9 | 19 / **−20,61** | 17 / **−20,56** | 2 / **−0,05** |
| SHORT, skor 30–39,9 | 36 / **−59,31** | 26 / **−65,84** | 10 / **+6,53** |

Bu iki örnek, “düşük skorlu LONG kötü” veya “orta skorlu SHORT kötü” demenin neden erken olduğunu gösterir. Gözlenen zararın büyük kısmı kurtarma alt kümesindedir; kurtarmasız alt küme küçüktür ve nedensel bir A/B sonucu değildir.

## 5. Kazandıran ve kaybettiren çıkış modülleri

| Çıkış modülü | N | Kazanç / kayıp / başa baş | Brüt K/Z | Yaklaşık ücret sonrası | Hüküm |
|---|---:|---:|---:|---:|---|
| **Order-flow / CVD kâr çıkışı** | 7 | 7 / 0 | **+49,29** | **+46,84** | Olumlu, küçük örneklem |
| Haber vetosu + kâr koruma | 2 | 2 / 0 | +9,74 | +9,04 | Olumlu, çok küçük örneklem |
| Trailing stop | 8 | 4 / 3 / 1 | +1,29 | −1,51 | Nötr; ücret sonrası zayıf |
| Flash-crash sigortası | 23 | 11 / 12 | −7,20 | −15,25 | Negatif; portföy kilidi ayrıca incelenmeli |
| **Çapraz kurtarma — artı bacak** | 61 | 58 / 3 | +139,85 | +118,50 | Tek başına yanıltıcı; diğer bacakla birlikte okunmalı |
| **Çapraz kurtarma — tersteki bacak** | 58 | 0 / 58 | **−215,52** | **−235,82** | Ana zarar havuzu |
| **Çapraz kurtarma — toplam** | **119** | **58 / 61** | **−75,67** | **−117,32** | En zayıf modül |
| Başlangıç marj stopu | 1 | 0 / 1 | −34,92 | −35,27 | Tek INIT işlemi; genel trend değil |

### Order-flow/CVD neden “kanıtlanmış en iyi indikatör” değil?

Order-flow/CVD burada **kârdaki pozisyonu kapatan çıkış motoru** olarak ölçülmüştür. 7 işlemin tamamı pozitiftir; IRYS çıkarıldığında kalan 6 işlem +19,60 USDT'dir. Bu umut vericidir ancak:

1. Örnek sayısı 7'dir.
2. Yalnız kâra geçmiş pozisyonlarda devreye girer; bütün girişlerin kalitesini ölçmez.
3. Girişte kullanılan para-akışı skoruyla aynı şey değildir.
4. Tek IRYS işlemi toplamın önemli kısmını oluşturur.

Bu nedenle raporlanabilir hüküm **“bu oturumda en iyi görünen çıkış modülü”**dür; “her koşulda kazandıran indikatör” değildir.

## 6. Kurtarmasız alt küme ve aykırı işlem kontrolü

Çapraz kurtarma dışında kalan 41 primary kapanış:

- 24 kazanç / 16 kayıp / 1 başa baş
- **+18,20 USDT brüt**
- PF **1,376**
- Yaklaşık 0,35 USDT/işlem ücret sonrası **+3,85 USDT**; funding dağıtılmamıştır

Ancak bu sonuç kurtarma kapalı bir stratejinin backtest'i değildir. Aynı pozisyonların kurtarma olmadan ne zaman ve hangi fiyatla kapanacağı bilinmez. Ayrıca sonuç aykırı işlemlere duyarlıdır:

- IRYS çıkarılırsa 40 işlem **−11,49 USDT brüt**.
- INIT çıkarılırsa 40 işlem **+53,12 USDT brüt**.

Dolayısıyla “kurtarmayı kapatırsak kesin kâr” sonucu da kurulamaz. Yeni kontrollü run'da kurtarmanın kapalı olması bu nedensel soruyu ölçmek için gereklidir.

## 7. Süre ve haber gözlemleri

Tutma süresi kırılımında en kötü grup **6–15 dakika** olmuştur: 40 işlem, **−46,56 USDT brüt**. 16–60 dakika grubu 65 işlemde −23,64 USDT'dir. 0–1 dakika grubunun +29,29 USDT'si ise IRYS aykırı kazancını içerir.

Haber ve Fear/Greed kırılımları da kurtarma ve aykırı işlem etkisiyle karışmaktadır. Bu nedenle haber skoru veya Fear/Greed için “kazandıran/kaybettiren indikatör” etiketi verilmemiştir.

## 8. İndikatör bazında verilebilen ve verilemeyen hükümler

| Bileşen | Eski run için hüküm | Gerekçe |
|---|---|---|
| RSI | **Ölçülemedi** | İşlem bazlı giriş değeri yok |
| MACD | **Ölçülemedi** | Histogram/sinyal snapshot'ı yok |
| ADX / +DI / −DI | **Ölçülemedi** | İşlem bazlı değer yok |
| MA / EMA | **Ölçülemedi** | Giriş snapshot'ı yok |
| Supertrend | **Ölçülemedi** | 28 trail güncellemesi sayacı fayda ölçmez |
| MTF | **Ölçülemedi** | 131 filtre sayacı, engellenen işlemlerin alternatif K/Z'si yok |
| ML | **Ölçülemedi** | Eski girişlerde ML skoru/yönü yok |
| Haber / Fear-Greed | **Kanıt yetersiz** | Küçük ve çıkış modülüyle karışık kırılımlar |
| Para akışı — giriş tetiği | **Tek başına başarılı değil** | Her iki yön de brüt zararda |
| Order-flow/CVD — çıkış | **Olumlu, n=7** | +49,29 brüt; IRYS etkisi yüksek |
| Çapraz kurtarma — çıkış | **En zayıf modül** | 119 işlemde −75,67 brüt |

Rejim bazlı kodda bütün bileşenlerin her rejimde skora girmediği de unutulmamalıdır. Örneğin TREND ve RANGE rejimlerinde aktif bileşenler farklıdır. Eski logda aktif bileşen katkıları bulunmadığından sonradan bileşen katkısı uydurulmamıştır.

## 9. Kod denetiminde bulunan ek veri sorunu

Güncel `src/market_data.py` OKX WebSocket aboneliğinde `books5` kullanıyor. `config.yaml` 20 kademe analiz belirtse de run **40065026239**'un 78 giriş bağlamının tamamında `book_levels=5` görüldü.

Bu, RSI/MACD sorunu değil, **order-book/para-akışı veri besleme farkı**dır. Depth skoru ve buna bağlı para-akışı tetiği 20 kademe varsayımıyla yorumlanmamalıdır. Eski run'ın kod sürümünde aynı davranışın etkisi ayrıca karşılaştırılmalı; bu bulgu tek başına geçmiş K/Z'yi açıklamaz ve henüz düzeltilmemiştir.

## 10. Sonuç ve bundan sonraki doğru ölçüm

**Bugün eski oturum için savunulabilir cevap:**

- Kazandıran tarafta en güçlü kanıt **order-flow/CVD kâr çıkışı**ndadır.
- Kaybettiren tarafta en güçlü kanıt **çapraz kurtarma**dadır; giriş indikatörü değildir.
- Para-akışı giriş tetiği ve toplam skor, ücretleri aşan güvenilir bir avantaj göstermemiştir.
- RSI/MACD/ADX/MA/Supertrend/MTF/ML için eski oturumdan kesin kazanan/kaybeden sıralaması yapılamaz; bu cevap veri eksikliğinden dolayı bilinçli olarak verilmez.

Kesin indikatör sıralaması için her pozisyonda **aktif bileşen katkıları + ham snapshot + pozisyon UUID'si + gerçekleşen çıkış** birlikte saklanmalı; ardından aynı piyasa döneminde bileşen çıkarma (ablation) ve walk-forward karşılaştırması yapılmalıdır. Tek oturumluk korelasyonla RSI/MACD eşiği değiştirilmemiştir.
