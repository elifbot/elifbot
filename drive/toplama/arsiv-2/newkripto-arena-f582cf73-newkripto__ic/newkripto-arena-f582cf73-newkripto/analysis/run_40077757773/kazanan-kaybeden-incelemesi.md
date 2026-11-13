# Kazanan / Kaybeden Bot İşlemleri — Giriş ve Çıkış İncelemesi

**Run:** 40077757773  
**Kapsam:** Yalnız botun kendi kapattığı 30 işlem; net K/Z > 0 olan 22 kazanan ve net K/Z < 0 olan 8 kaybeden.  
**Hariç:** 55 `SÜRELİ PAPER ÖLÇÜMÜ SONU` pozisyonu performans karşılaştırmasına katılmadı.  
**Yöntem sınırı:** Tek iki saatlik oturum; kohortlar örtüşür, ilişkiler nedensellik değildir. En büyük iki ORDER/USDT kazancı bot netinin yaklaşık %50,3'ünü oluşturur.

## 1. Kısa teşhis

1. **Kazanan giriş profili trend uyumunda toplanıyor:** EMA trend, ADX, session VWAP, Supertrend, MA trend, MACD, OBV ve yönle uyumlu volume profile.
2. **Hiçbir tek teknik indikatör tek başına belirleyici değil:** Kazananlarda leave-one-out bireysel teknik bileşen belirleyiciliği görülmedi; `technical_all` ve `orderflow_all` ise 30/30 işlemde belirleyici. Sonuç tek bir “sihirli indikatöre” değil, bileşenlerin birlikte çalışmasına bağlı.
3. **Kaybedenlerde teknik skor daha zayıf, teknik çelişki daha fazla:** Medyan yön-uyumlu teknik skor kazananlarda 53,4, kaybedenlerde 33,4. İşlem başına ortalama karşıt teknik katkı sayısı kazananlarda 0,50, kaybedenlerde 1,75.
4. **Toplam skor tek başına ayrıştırmıyor:** Medyan yön-uyumlu toplam skor iki grupta da 33,45. Güçlü order-flow, zayıf teknik görünümü toplam skorda telafi edebiliyor.
5. **8 kaybın tamamı trailing stop ile kapandı:** Toplam brüt K/Z yaklaşık +0,07 USDT iken ücretler sonrası net -2,73 USDT. Dört işlem brüt kârda, biri tam başa başta olduğu halde net zarar yazdı.
6. **Akış skorunun anlamlılık sorunu var:** Taker delta oranla 42 puan, CVD yönü yalnız işaretle 14 puan üretiyor. Küçük hacim/CVD değerleri de güçlü akış teteğini açabiliyor.
7. **Kaybedenlerde volatilite çok düşük:** Medyan Bollinger bant genişliği kazananlarda yaklaşık %1,66, kaybedenlerde %0,11. Dar piyasada fiyat hareketi, maliyet ve %0,5 order-flow kâr eşiği için yeterli alan sağlayamayabiliyor.

## 2. Kazananlarda öne çıkan indikatörler

Aşağıdaki “kohort”, ilgili bileşenin pozisyon yönüyle aynı işaretli aktif katkısı bulunan işlemleri kapsar. Aynı işlem birden çok satırda bulunabilir.

| Yönle uyumlu bileşen | İşlem | Kazanan / kaybeden | Net kazanma | Okuma |
|---|---:|---:|---:|---|
| OBV | 20 | 17 / 3 | %85,0 | Kazanan profilinde güçlü; tek başına belirleyici değil |
| Volume profile | 25 | 21 / 4 | %84,0 | Yönü önemli; karşıt katkısı kaybedenlerde belirgin |
| MA trend | 26 | 21 / 5 | %80,8 | Trend uyumu öne çıkıyor |
| MACD | 22 | 18 / 4 | %81,8 | Kazananların 18/22'sinde yönle uyumlu |
| ADX | 27 | 22 / 5 | %81,5 | Kazananların tamamında uyumlu; trend gücü medyanı da daha yüksek |
| Session VWAP | 27 | 22 / 5 | %81,5 | Kazananların tamamında uyumlu |
| EMA trend | 28 | 22 / 6 | %78,6 | Kazananların tamamında uyumlu |
| Supertrend | 28 | 22 / 6 | %78,6 | Kazananların tamamında uyumlu |
| Anchored VWAP | 27 | 21 / 6 | %77,8 | Kazananların 21/22'sinde uyumlu |
| Taker delta | 30 | 22 / 8 | %73,3 | Her iki grupta da zorunlu ortak profil; tek başına ayırt etmiyor |
| CVD yönü | 30 | 22 / 8 | %73,3 | İşaret her iki grupta da uyumlu; büyüklük önemli |
| Order-book depth | 21 | 15 / 6 | %71,4 | Genel bot oranının üzerinde ayrışma yok |
| Whale balance | 7 | 6 / 1 | %85,7 | Küçük örneklem |
| OI/liquidation | 4 | 4 / 0 | %100,0 | Yetersiz örnek; büyük ORDER sonuçlarıyla örtüşüyor |

Leave-one-out ile giriş kararı için belirleyici olan order-flow bileşenleri:

| Belirleyici bileşen | Kazananlarda | Kaybedenlerde | Yorum |
|---|---:|---:|---|
| CVD yönü | 21/22 | 5/8 | İki grupta da yaygın; yalnız yön değil büyüklük incelenmeli |
| Taker delta | 19/22 | 8/8 | Kaybedenlerin tamamında giriş için belirleyici; oran güveni kritik |
| Order-book depth | 9/22 | 1/8 | Kazananlarda daha sık belirleyici, ancak kohortlar örtüşür |
| OI/liquidation | 4/22 | 0/8 | Küçük ve sonuç yoğunlaşmalı kohort |
| Whale balance | 4/22 | 0/8 | Küçük kohort |

Buradaki “belirleyici”, bileşen çıkarıldığında mevcut kurallarla aynı yönde giriş kararı oluşmamasıdır; işlemin kâr/zararını o bileşenin nedensel olarak ürettiği anlamına gelmez.

Ek ölçümler:

- Kazananlarda medyan ADX **34,17**, kaybedenlerde **26,13**.
- RSI'ın 50'den pozisyon yönündeki uzaklığı kazananlarda medyan **17,68**, kaybedenlerde **9,51**. Bu, RSI bileşeninin giriş tetiklediği anlamına gelmez; momentum profilini karşılaştırır.
- Kazananların 19'u TREND, 3'ü BREAKOUT. Kaybedenlerin 5'i TREND, 1'i BREAKOUT, 2'si RANGE.
- MTF yönü 30/30 işlemde uyumlu olduğundan bu kohort içinde kazanan/kaybeden ayrıştırıcısı olarak ölçülemez.
- ML, kazananların 13/22'sinde pozisyon yönüne karşıydı. Bu run ML ağırlığını artırma veya ML'yi başarı göstergesi sayma kanıtı vermiyor.

## 3. Kaybedenlerde görülen indikatörler ve çelişkiler

### 3.1 Yön çelişkileri

| Ölçüm | Kazananlar | Kaybedenler |
|---|---:|---:|
| En az bir karşıt teknik katkı | 9/22 — %40,9 | 7/8 — %87,5 |
| Ortalama karşıt teknik katkı sayısı | 0,50 | 1,75 |
| Volume profile pozisyon yönüne karşıt | 1/22 — %4,5 | 4/8 — %50,0 |
| Session VWAP pozisyon yönüne karşıt | 0/22 | 3/8 — %37,5 |
| OBV pozisyon yönüne karşıt | 5/22 — %22,7 | 3/8 — %37,5 |
| MACD pozisyon yönüne karşıt | 4/22 — %18,2 | 2/8 — %25,0 |

**Önemli yorum:** Volume profile yalnız “var mı?” diye değil, katkısının yönüyle değerlendirilmelidir. Kazananların 21/22'sinde destekleyici, kaybedenlerin 4/8'inde karşıt katkı üretmiştir.

### 3.2 RANGE osilatörleri

- Stoch RSI, Williams %R ve MFI yön-uyumlu katkıları yalnız **iki RANGE kaybında** görüldü: SNOW/USDT ve NG/USDT.
- RSI, Bollinger ve CCI destek satırları da bu küçük RANGE grubuna bağlı.
- Bunlar bağımsız çok sayıda işlem değildir; aynı iki pozisyon tekrar sayılmamalıdır. Sonuç “bu indikatörler kötü” değil, **RANGE içinde para-akışı tetikli girişler ayrıca sınanmalı** sonucudur.

### 3.3 Sekiz kaybın ayrıntısı

Skorlar pozisyon yönüne çevrilmiş mutlak değerlerle gösterilmiştir. `|CVD|` beş dakikalık CVD eğiminin mutlak USDT büyüklüğüdür.

| Sembol | Rejim | Teknik | Akış | Mutlak CVD | BB genişliği | Brüt / net USDT | Ana teknik karşıt katkı |
|---|---|---:|---:|---:|---:|---:|---|
| QQQ/USDT SHORT | TREND | 37,4 | 58,9 | 33.236,9 | %0,127 | +0,198 / -0,152 | MACD |
| CSOPSAMSUNG2L/USDT SHORT | TREND | 33,4 | 69,1 | 14,0 | %0,663 | -0,504 / -0,855 | OBV, session VWAP, volume profile |
| SNOW/USDT LONG | RANGE | 14,0 | 57,8 | 42,2 | %0,654 | -0,046 / -0,396 | Bollinger, CCI |
| NG/USDT SHORT | RANGE | 18,0 | 54,8 | 2.402,6 | %0,168 | 0,000 / -0,350 | Session VWAP, volume profile |
| EWJ/USDT SHORT | BREAKOUT | 59,4 | 51,9 | 93,3 | %0,092 | +0,265 / -0,085 | Teknik karşıt katkı yok; order-book karşıt |
| WMT/USDT LONG | TREND | 33,4 | 59,2 | 6,0 | %0,056 | -0,208 / -0,558 | MACD, OBV, volume profile |
| XAU/USDT SHORT | TREND | 43,4 | 78,3 | 211.924,7 | %0,091 | +0,162 / -0,187 | OBV |
| PAXG/USDT SHORT | TREND | 31,8 | 65,8 | 36.970,4 | %0,092 | +0,202 / -0,144 | Session VWAP, volume profile |

EWJ örneği önemlidir: teknik skor yüksek olmasına rağmen çok dar volatilite ve maliyet nedeniyle net kayıp oluştu. Dolayısıyla bütün kayıpları “zayıf indikatör” ile açıklamak doğru değildir.

## 4. Kodda görülen iki yapısal sorun

### 4.1 Akış tetikleyicisi, akışın büyüklüğünden çok oranına güveniyor

`MoneyFlow.snapshot()` içinde:

- `taker_delta = delta_ratio × 42`
- `cvd_direction = sign(cvd_slope) × 14`

Tek taraflı çok küçük bir hacim bile taker delta için ±42, sıfırdan farklı çok küçük bir CVD eğimi de ±14 üretebilir. Toplam ±56, `para_akisi_esik: 50` seviyesini aşar.

Bu oturumdaki 30 bot girişinin tamamında normal toplam-skor sinyali **BEKLE** idi; girişler `PARA_GIRISI/PARA_CIKISI` tetikleriyle açıldı. Bu nedenle:

- Akış tetikleyicisini tamamen kapatmak bütün gözlenen kazananları da ortadan kaldırır; desteklenen çözüm değildir.
- Taker delta ve CVD aynı trade akışından türediği için iki bağımsız onay gibi değerlendirilmemelidir.
- CVD yönüne büyüklük/süreklilik güveni, taker oranına ise notional ve işlem sayısı güveni eklenmesi daha anlamlı bir denemedir.

Kanıt:

- Medyan mutlak CVD eğimi kazananlarda **28.216 USDT**, kaybedenlerde **1.248 USDT**.
- Mutlak CVD'si 100 USDT altındaki beş işlemde **1 kazanç / 4 kayıt**, toplam net yaklaşık **-1,70 USDT** görüldü.
- Buna karşılık HIMS/USDT gibi çok düşük akış hacmine rağmen kazanan da vardır. Global ve katı bir hacim yasağı yerine sembol bazında göreli güven katsayısı sınanmalıdır.

### 4.2 Trailing başabaşı brüt, gerçek sonuç ise net

Risk ve Supertrend trailing mantığı stopu brüt giriş fiyatına veya daha iyi seviyeye taşıyor. Yaklaşık maliyet:

- 50 USDT marj × 10x ≈ 500 USDT notional
- Maker giriş ≈ 0,10 USDT; taker çıkış ≈ 0,25 USDT
- Toplam ≈ **0,35 USDT**, notionalın yaklaşık **%0,07'si**

Buna karşılık kaybeden dört brüt-kâr işleminin pozisyon yönündeki fiyat hareketi yaklaşık %0,032–%0,053 aralığındaydı; maliyetin altında kaldı. Bir işlem de tam brüt başa başta kapandığı için net zarar yazdı.

Order-flow kâr çıkışındaki `%0,5` minimum brüt fiyat kârı ise bu oturumda maliyetin üzerinde kaldı ve 20/20 işlem net kâr yazdı. Ancak trailing için aynı net-kâr bilinci yoktur. Ayrıca üç kayıp zaten brüt zarardadır; maliyet tamponu tek başına bütün sorunu çözmez ve stop-market kaymasına karşı garanti vermez.

## 5. Nasıl düzeltebiliriz? — Kontrollü deney sırası

### Öncelik 1 — Net maliyet bilinçli trailing/başabaş

- Sabit TP eklemeden, trailing ve Supertrend stopuna tahmini giriş + çıkış ücreti ve gerekiyorsa kayma tamponunu fiyat birimine çeviren bir **net başabaş seviyesi** eklenmeli.
- Stop yalnız fiyat bu seviyeyi gerçekten gördükten sonra sıkılaştırılmalı; mevcut fiyatın üstünde/altında yapay stop yazılmamalı.
- LONG/SHORT, tam başa baş, küçük brüt kâr ve stop üzerinden gap senaryoları ayrı test edilmeli.
- Kapanış kaydına zirve/dip (MFE), kapanıştaki stop ve tahmini/gerçekleşen maliyet eklenerek “daha yüksek kâr varken kaçırıldı mı?” ölçülmeli.

### Öncelik 2 — CVD/taker akışına güven katsayısı

- CVD için yalnız işaret yerine büyüklük ve süreklilikle ölçeklenen katkı denenmeli.
- Taker delta için notional ve trade sayısı arttıkça güveni yükselen, sembolün kendi geçmişine göre normalize edilen bir katsayı denenmeli.
- Amaç akış tetikleyicisini kapatmak değil, küçük sayıda trade ile oluşan ±42/±14 puan şişmesini azaltmak.
- 100 USDT mutlak CVD bu run'da geriye dönük ayırıcı olsa da doğrudan evren geneline sabit eşik olarak kurulmamalı; önce bağımsız run'larda doğrulanmalı.

### Öncelik 3 — Volatilite / maliyet uygunluğu

- Bollinger bant genişliği ile birlikte ATR% kaydı da eklenmeli.
- Girişte beklenen hareket alanı; round-trip ücret, kayma ve `%0,5` order-flow kâr eşiğiyle karşılaştırılmalı.
- Çok dar piyasada akış tetikli girişi zorlaştıran tek değişkenli bir deney yapılmalı. Bu run'daki %0,20 BB eşiği geriye dönük olarak 22 kazananı koruyup 6 kaybı elese de aynı veriden seçilmiş eşiği canlı kural yapmak overfitting olur.

### Öncelik 4 — RANGE ve teknik çelişki ayrı deneyler

- RANGE rejiminde para-akışı tetikleyicisini ayrı tutan veya ek onay isteyen kontrollü bir kohort kurulmalı. Mevcut kanıt yalnız iki RANGE işlemidir.
- Teknik karşıt katkı sayısı ve volume-profile/session-VWAP yön çelişkisi giriş bağlamına ayrı alanlar olarak kaydedilmeli; farklı sınırlar sonraki run'larda karşılaştırılmalı.
- `tetik_indikator_min` değerini doğrudan 10'dan 40'a çıkarmak önerilmez: bu run'da 6 kaybı elese de 3 kazananı dışlayarak bot netini yaklaşık **95,60'dan 86,83 USDT'ye** düşürürdü.

## 6. Şimdilik değiştirilmemesi gerekenler

- **ML ağırlığı:** Kazananların çoğunda ML ters yönde; tek yönlü iyileştirme kanıtı yok.
- **OKX'in tamamı:** Kayıpların 7/8'i OKX'te olsa da OKX bot kohortu toplamı +40,63 USDT; sembol/rejim karışımı ve maliyet etkisi ayrılmadan borsa kapatılmamalı.
- **OI/funding ağırlıkları:** Az sayıda ve büyük ORDER kazançlarıyla yoğunlaşmış kohortlara dayanılarak artırılmamalı.
- **Tek bir teknik indikatörü silmek veya kutsamak:** Bireysel leave-one-out kanıtı yok; birlikte uyum ve yön çelişkisi ölçülmeli.

## 7. Deneyde izlenecek metrikler

Her değişiklik tek başına, temiz 100.000 USDT paper kasa, 50 USDT marj/10x, Binance + OKX ve aynı maliyet modeliyle birden fazla bağımsız oturumda sınanmalı:

- Net K/Z, PF ve medyan işlem neti
- Trailing çıkışlarında brüt kâr → net zarar sayısı
- Kazananları eleme oranı ve toplam giriş sayısındaki düşüş
- TREND / RANGE / BREAKOUT ve borsa bazlı sonuçlar
- Mutlak CVD, akış notionalı, BB/ATR volatilite kohortları
- En büyük iki işlemin toplam netteki payı ve sonuç yoğunlaşması
- Yeni veri / out-of-sample doğrulaması

**Bu inceleme sonrasında canlı strateji parametresi değiştirilmedi.** Mevcut bulgular yeni deney hipotezleridir; tek run'dan otomatik optimizasyon yapılmamıştır.
