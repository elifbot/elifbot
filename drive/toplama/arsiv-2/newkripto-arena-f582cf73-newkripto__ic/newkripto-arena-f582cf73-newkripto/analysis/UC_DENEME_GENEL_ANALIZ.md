# Üç denemenin genel değerlendirmesi — Paper Lab

**Kapsam:** 39969507314 → 40077757773 → 40090692312
**Hazırlama tarihi:** 2026-10-24
**Durum:** Üçüncü run 2026-10-24 12:39 UTC'ye kadar `completed/success`; nihai artifact, closeout ve Shadow raporu doğrulandı. İlk iki run'a ait sayılar ilgili maskeli kanıtlardan alınmıştır.

> **Ana kural:** Bu üç run'ın K/Z'sini tek bir toplam gibi toplamak doğru değildir. Kod sürümü, süre, borsa kapsamı, kapanış bütünlüğü, kasa ve deney amacı farklıdır. Burada ortak mekanizmalar ve kanıt kalitesi karşılaştırılır.

## 1. Kısa hüküm

- **İlk deneme:** Önce mühendislik ve pozisyon-kapama bütünlüğü sorunu vardı. Çapraz kurtarma da ölçülebilen en zayıf çıkış modülüydü. Bu run'dan “hangi indikatör kötü?” sonucu çıkmaz.
- **İkinci deneme:** Kapama bütünlüğü, çapraz kurtarmayı kapatma, planlı closeout ve işlem bazlı maliyet/attribüsyon iyileştirmeleriyle çok daha temiz ve umut verici sonuç verdi. Ancak genel sonuç ile botun doğal kapanış kohortu aynı şey değil; sonuç birkaç büyük kazanca yoğunlaşıyor.
- **Üçüncü deneme:** 1.000 USDT kasa ve altı Shadow varyantıyla 9 giriş/9 kapanış ölçüldü; genel net **−3,05 USDT**, PF **0,26**. Dokuz kapanışın tamamı `FLASH CRASH SİGORTASI`; doğal trailing/order-flow çıkış performansı bu run'da gözlemlenmedi. Bu, küçük ve sigorta-domine bir kesittir; v2 veya başka bir kuralın kanıtı değildir.

## 2. Deneylerin karşılaştırılabilirlik tablosu

| Özellik | 1 — 39969507314 | 2 — 40077757773 | 3 — 40090692312 |
|---|---|---|---|
| Başlangıç kasası | 100.000 USDT | 100.000 USDT | 1.000 USDT |
| Planlanan süre | 5,9167 saat | 2 saat | 60 dakika |
| Çapraz kurtarma | Açık | Kapalı | Kapalı |
| Kod | `de4f137` | `1d7099b` | `1804883` |
| Borsa kanıtı | Fiilen OKX-only | Binance + OKX | Preflight'te iki borsa zorunlu |
| Kapanış bütünlüğü | 160 primary, 872 duplicate | 85/85, duplicate yok | 9/9, duplicate yok, açık 0 |
| Closeout | Eski raporlama; açık K/Z ayrıntısı sınırlı | Planlı, açık 0 | Planlı closeout + partial checkpoint |
| Ana amaç | İlk canlı-veri paper denemesi | Kontrollü baseline ve maliyet analizi | Altı izole Shadow varyantı |

## 3. Finansal sonuçlar — aynı türden olmayan sayıları karıştırmadan

| Run | Ham/raporlanan sonuç | Temiz okuma |
|---|---:|---|
| 1 | Kasa **−796,20 USDT** | 1.032 kapanışın 872'si duplicate; bu sayı bağımsız işlem performansı değil. Primary-only hassasiyet hesabı yaklaşık **−113,36 USDT**, fakat temiz backtest değil. |
| 2 | Genel net **+43,3096 USDT** | 85 kapanışın tamamı ve 55 süre-sonu kapanışı dahil. Botun doğal 30 kapanışı ayrı olarak **+95,60 USDT**; iki sayı birbirinin yerine kullanılmaz. |
| 3 | Genel net **−3,0478 USDT** | 9 giriş/9 kapanış; brüt +0,1027, ücret 3,1505, funding 0. Tüm kapanışlar sigorta; doğal çıkış kohortu yok. |

**Yüzde karşılaştırması da dikkat ister:** 50 USDT marj, 100.000 USDT kasanın %0,05'i iken 1.000 USDT kasanın %5'idir. Aynı 0,35 USDT round-trip maliyet ve aynı 40 USDT stop, iki kasada aynı göreli riski temsil etmez. Bu yüzden 1.000 USDT run'ı 100.000 USDT run ile yalnız USDT veya yüzde getiriyle sıralamak yanıltıcı olur.

## 4. Birinci deneme — sorun yalnız çaprazlama değildi

**Kanıt:** `analysis/run_39969507314/GENEL_ANALIZ.md` ve `INDIKATOR_KYAS.md`.

### 4.1 Mühasebe/kapama sorunu

- 160 bağımsız primary açılış/kapanışa karşı 1.032 kapanış kaydı vardı; 872 kayıt duplicate'di.
- Raporlanan −796,20 USDT'nin yaklaşık %86'sı duplicate brüt K/Z ve tahmini duplicate ücret etkisiyle açıklanıyordu.
- Bu nedenle 1.032 işlem, %49,8 kazanma oranı ve raporlanan kasa sonucu bağımsız strateji örneklemi olarak kullanılamaz.

### 4.2 Çapraz kurtarmanın gerçek rolü

- 119 primary pozisyonda iki bacak toplamı **−75,67 USDT brüt**, yaklaşık **−117,32 USDT ücret sonrası**.
- Artı bacak +139,85 USDT görünse de tersteki bacak −215,52 USDT idi. Tek bacağa bakmak modülü yanlış olumlu gösterir.
- Çapraz kurtarma bir giriş indikatörü değil, pozisyonların çıkış zamanını ve fiyatını değiştiren ayrı bir mekanizmadır. Bu yüzden giriş sinyali başarısızlığıyla karıştırılmamalıdır.

### 4.3 Olumlu görünen ama küçük örnekli kısım

- Order-flow/CVD kâr çıkışı 7/7 pozitif, +49,29 USDT brüt.
- Bunun +29,69 USDT'si tek IRYS işleminden geldi; “her koşulda kazandıran indikatör” sonucu çıkmaz.
- Eski run'da RSI/MACD/ADX/MA/Supertrend/MTF/ML giriş snapshot'ları pozisyon kimliğiyle yoktu. Bu bileşenler hakkında kesin kazanan/kaybeden sıralaması yapılmadı.

## 5. İkinci deneme — neden daha iyi görünüyordu?

**Kanıt:** `analysis/run_40077757773/sonuc-ozeti.md`, `cohort-report.md`, `islem_gecmisi.json`.

### 5.1 Önce ölçüm kalitesi düzeldi

- 85 giriş/85 kapanış, açık pozisyon 0 ve maliyet özdeşliği doğrulandı.
- Binance 47, OKX 38 kapanışla iki borsa birlikte ölçüldü.
- Her işlemde UUID, borsa, giriş attribüsyonu, gerçekleşen ücret ve funding bulundu.

Bu, birinci run'daki “sonucu mu, muhasebe hatasını mı izliyoruz?” belirsizliğini azalttı. Pozitif sonucun tamamını strateji iyileşmesine bağlamak doğru olmaz; ölçümün temizlenmesi de farkın önemli parçasıdır.

### 5.2 Genel kasa ve bot kohortu

| Kohort | N | Net | PF / not |
|---|---:|---:|---|
| Tüm kapanışlar | 85 | **+43,31 USDT** | PF 1,62; 39 kazanan / 46 kaybeden |
| Botun doğal kapanışları | 30 | **+95,60 USDT** | PF 36,07; 22 kazanan / 8 kaybeden |
| Süre-sonu/erken kapanışlar | 55 | Ayrı kohort | Çıkış performansına dahil edilmedi |

Bot kohortundaki iki ORDER/USDT işlemi netin yaklaşık **%50,3'ü**ydü. Genel 85 işlemin medyan neti **−0,14 USDT**, doğal bot kohortunun medyanı **+2,24 USDT** oldu; ortalama/net toplam ile tipik işlem aynı resmi vermiyor. Dolayısıyla PF 36,07 bile tek başına istikrar kanıtı değildir; yoğunlaşma, medyan ve örneklem büyüklüğü birlikte okunmalıdır.

### 5.3 Çıkış ve giriş bulguları

- Order-flow kâr-koşusu: 20 işlem, **+98,01 USDT net**.
- Trailing stop: 10 işlem, **−2,41 USDT net**; küçük brüt kazançlar ücretle silindi.
- Kazananlar 19 TREND + 3 BREAKOUT; kaybedenler 5 TREND + 2 RANGE + 1 BREAKOUT.
- 30/30 bot girişi `raw_signal=BEKLE` iken para-akışı tetikiyle açıldı. Bu, ana toplam-skor eşiğinden çok alternatif akış yolunun test edildiğini gösterir.
- Taker/CVD skorunun büyüklüğü tek başına kazananı ayırmadı. Veri kapsamı, teknik çelişki ve çıkış maliyeti birlikte araştırılmalı.

## 6. Üçüncü deneme — 1.000 USDT ve Shadow Lab

**Run:** [40090692312](https://github.com/omeracar56/kripto-bot/actions/runs/40090692312)
**Profil:** 1.000 USDT paper kasa; her Shadow varyantında 1.000 USDT izole kasa; 50 USDT marj; sabit 10x; 60 dakika; gerçek emir yok.

Binance+OKX preflight ve güvenlik assertleri geçti; katalog kanıtı Binance 741, OKX 507 ve oturum evreni 808 semboldü. Planlı closeout tamamlandı, açık pozisyon 0 ve 9/9 kayıt eşleşti. `paper_job_result=success` olması stratejinin kârlı olduğu anlamına gelmez; yalnız işin ve kanıt üretiminin tamamlandığını gösterir.

### 6.1 Finansal ve çıkış sonucu

| Ölçüm | Sonuç |
|---|---:|
| Giriş / kapanış | 9 / 9 |
| Kazanan / kaybeden | 2 / 7 |
| Brüt fiyat K/Z | +0,1027 USDT |
| Giriş + çıkış ücreti | 3,1505 USDT |
| Funding | 0,0000 USDT |
| Net | **−3,0478 USDT** |
| PF / medyan net | 0,26 / −0,13 USDT |
| Kapanış nedeni | 9/9 `FLASH CRASH SİGORTASI` |

Dolayısıyla bu run'da “botun doğal trailing/order-flow ile kaç işlem kapattığı” sorusunun yanıtı **0**; 9 kayıt koruyucu sigorta kohortunda ayrı okunmalıdır. Cohort raporundaki geniş “bot kapanışı” etiketi bu ayrımı ortadan kaldırmaz. Net zararın ana mekanik açıklaması brüt hareketin ücretleri karşılayamaması ve sigorta çıkışlarının dağılımıdır; 1.000 USDT kasa için sonuç yaklaşık −%0,305'tir, ancak tek kesit genellenemez.

### 6.2 Shadow ve veri-hazır-olma sonucu

- `net-exit`, `volatility-gate`, `range-confirmation` ve `portfolio-guard`: 9/9 kabul, baseline ile aynı **−3,05 USDT**.
- `technical-harmony`: 8 kabul/1 ret, **−3,33 USDT**; reddedilen CYBER işlemi baseline'da +0,28 USDT idi. Bu küçük örnekte filtre iyileşme göstermedi.
- `flow-confidence`: 0 kabul/9 ret, işlem açmadı; +3,05 USDT'lik baseline zararından kaçınma matematiksel olarak görülür ama **2 kazanan da kaçırıldı** ve hiçbir gerçek varyant çıkışı ölçülmedi. Retlerde düşük trade/kapsama, bayat defter ve güven ayarlı skor yetersizliği vardı. Bu, “akış filtresi kanıtlandı” sonucu değildir.
- Altı varyantın hiçbiri bu sigorta-domine kesitte doğal çıkış kalitesini test etmedi. Yeni PDF v2 varyantı da aynı sınırla, ayrı run'da okunmalıdır.

Az işlem gözlemi üç nedenden ayrıldı: baseline 9 sinyal üretti; Shadow retleri ayrıca kaydedildi; kapanışlar güvenlik sigortasındaydı. Daha fazla işlem için eşik düşürme kararı bu kanıttan çıkarılmaz.

## 7. Üç denemenin ortak ve farklı bulguları

### 7.1 En güçlü ortak ders: önce işlem/maliyet bütünlüğü

Birinci run'da duplicate-close, ikinci run'da süre-sonu kohortu, erken kesitte ise ücretin brüt kârı silmesi görüldü. Bu nedenle yeni yeniliklerin ilk testi yalnız sinyal skoru değil:

`net = brüt fiyat K/Z − giriş ücreti − çıkış ücreti + funding`.

### 7.2 Order-flow çıkışı umut verici, giriş akışı aynı kanıt değil

Birinci ve ikinci run'da order-flow/CVD kâr çıkışları olumlu göründü. Fakat bunlar kâra geçmiş pozisyonların çıkışlarıdır; girişteki güçlü para-akışı skorunun her işlemde avantaj sağladığını kanıtlamaz. Girişte veri kapsamı ve teknik uyum ayrıca ölçülmelidir.

### 7.3 Çapraz kurtarma ile basit giriş filtresi aynı problem değil

İlk run'daki en belirgin negatif modül çapraz kurtarmaydı. İkinci run'da kapatılması ve kapanış bütünlüğünün düzelmesiyle sonuç iyileşti; ancak bu, her piyasada kurtarmanın mutlaka kötü olduğunu veya her giriş filtresinin iyi olduğunu kanıtlamaz. Kurtarma ancak ayrı, korumalı A/B deneyiyle yeniden ele alınmalı.

### 7.4 Kasanın küçültülmesi yeni bir risk sorusu getirir

1.000 USDT profilinde aynı 50 USDT marj göreli olarak daha büyük, aynı maliyet ve stop daha anlamlıdır. Buna karşılık az işlem sayısını yalnız kasaya bağlamak doğru değildir; sinyal, ret ve sigorta kayıtları gerekir.

### 7.5 Veri kapsamı performansın parçasıdır

İlk run OKX-only idi; ikinci run iki borsayı kanıtladı. Eski run'da indikatör snapshot'ları eksikti; yeni mimari bunları UUID ile saklıyor. Üçüncü run'daki Data Readiness bu nedenle bir “filtre”den önce ölçüm kalitesi kontrolüdür.

## 8. Şu an savunulabilecek genel sonuç

**Botun ana problemi yalnız indikatör seçimi değil.** Sıralama kabaca şöyle:

1. Kapama/muhasebe bütünlüğü ve veri kanıtı.
2. Çapraz kurtarmanın iki-bacaklı net etkisi.
3. Girişte para-akışı verisinin kapsamı ve teknik uyum.
4. Ücret sonrası çıkış kalitesi ve trailing'in küçük kârları koruması.
5. Yeterli bağımsız örnek ve farklı piyasa dönemleri.

**En olumlu yön:** İkinci run, temiz ölçüm ve kontrollü kapanışla order-flow çıkışının araştırmaya değer olduğunu gösterdi.

**En büyük risk:** Pozitif bir run'ı veya birkaç büyük kazancı genel kârlılık kanıtı sanmak; az işlemi de otomatik olarak eşik düşürme nedeni yapmak.

## 9. Sonraki ölçüm sırası

1. PDF v2 teknik paketini ve `pdf-confluence` varyantını aynı baseline ile 120 dakikalık,
   1.000 USDT / 50 USDT marj / sabit 10x çift-borsa paper run'ında ölç.
2. V2 kabul/retlerini, elenen ve kaçırılan kazananları, ücret/funding, PF, medyan net,
   drawdown ve borsa/rejim kırılımıyla karşılaştır; sigorta kapanışlarını ayrı tut.
3. Aynı anda bütün eşikleri değiştirme; yeni indikatörleri canlı baseline'a otomatik taşıma.
4. Çoklu dönem ve yeterli bağımsız kapanış olmadan canlı kullanım veya otomatik parametre kararı verme.

## 10. Kanıt dosyaları

- İlk run: `analysis/run_39969507314/GENEL_ANALIZ.md`, `INDIKATOR_KYAS.md`, `paper-session.txt`.
- İkinci run: `analysis/run_40077757773/sonuc-ozeti.md`, `cohort-report.md`, `cohort-report.json`, ham JSON/log.
- Üçüncü run: `analysis/run_40090692312/` — `run.json`, `oturum_analizi.json`, `islem_gecmisi.json`, `shadow-analysis.json`, `shadow-report.md`, `shadow-review.md` ve preflight kanıtı.
- Yardımcı kontrol: `analysis/run_40065026239/GENEL_ANALIZ.md`.
- Erken kesit: `analysis/run_40088524013/20-dakika-inceleme.md` ve `.json`.
- Proje hafızası: `PROJECT_MEMORY.md`; arşiv projesi: `paper-lab/`.

**Sınır:** Bu belge paper araştırmasıdır; gerçek para kullanımı, gelecek kâr veya zararsızlık garantisi değildir.
