# KRIPTO-BOT v7.7/v7.8 ile bizim v37 botumuz — artı/eksi karşılaştırması

**Tarih:** 29 Ekim 2026  
**v7.x kaynakları:** v7.7 ve v7.8 kod kitapları; ek olarak v7.8 kurucudan daha önce statik çıkarılmış 74 dosyalık kaynak ağacı.  
**v37 kaynağı:** `/home/user/Futures_Bot_v37_Deneysel_Paper_SON/futures_bot_v37/`; özellikle son paper çalışmasında kullanılan `ws_bot.py` sürekli tarayıcısı.  
**Yöntem:** Kaynak/kayıt incelemesi. Bu rapor hazırlanırken hiçbir bot veya emir çalıştırılmadı. v37’de aşağıda belirtilen 5 dakikalık paper koşusu daha önce tamamlanmış kanıttır.

## 1. Yönetici özeti

**Aynı tür ürün değiller.** v7.8, paper varsayılanı olsa da canlı/testnet borsa emirleri gönderebilen, çok modüllü bir işlem platformu. v37 ise kod ve CLI düzeyinde `paper/replay` ile sınırlı, public piyasa verisini kullanıp işlemleri kendi `PaperPortfolio` muhasebesinde simüle eden araştırma/test sistemidir.

- **Kontrollü araştırma ve güvenli paper denemesi için:** v37 daha uygun; gerçek API anahtarı/özel borsa emri yok, her borsa için ayrı hazır olma kapısı, stale/reset telemetrisi, CSV/JSON kanıtları ve 413 geçen regresyon testi var.
- **Canlı otomasyon işlevi bakımından:** v7.8 daha kapsamlı; borsada emir, leverage/margin ayarı, yerel/remote kontrol, veritabanı ve bildirim yetenekleri var. Ancak bu özellikler onu daha güvenli yapmıyor. Ayrı borsa bakiyelerini birleştiren risk hesabı, stop/yeniden başlatma ve belirsiz emir mutabakatı sorunları çözülmeden **canlı kullanıma hazır sayılmamalı**.
- **Kârlılık bakımından:** elimizde karşılaştırma yapmaya yetecek kanıt yok. v37’nin son testinde 5 dakikada sinyal/trade/PnL **0/0/0**; v7.7’deki `+$95.60 / 30 kapanış` ve benzeri kapak/kod yorumları bağımsız ham işlem günlüğüyle doğrulanmış değil.

## 2. Yan yana karşılaştırma

| Başlık | v7.7 / v7.8 | Bizim v37 |
|---|---|---|
| Temel amaç | Birden çok strateji modülü ve paper/testnet/live çalışma yolu olan futures botu | Public veri üzerinde paper/replay araştırma; son deneme sürekli tarayıcı (`ws_bot.py`) |
| Canlı emir | **Evet, kaynakta var.** `MODE=live`, API kimlikleri ve `LIVE_TRADING_CONFIRM=YES_I_RISK_REAL_MONEY` ile açılabilir | **Yok.** `SUPPORTED_MODES` paper/replay; live/testnet reddediliyor. Ana tarayıcı emirleri `PaperPortfolio` içine yazar |
| Güvenlik sınırı | Paper varsayılanı canlı yolu ortadan kaldırmıyor; ortam değişkeni modu değiştirebilir | Public GET/WebSocket; gizli anahtar veya imzalı emir yolu yok. Güvenli sınır kodda ve testlerde açık |
| Sinyal kapsamı | Kod/konfigürasyonda teknik + money-flow/CVD + haber/duygu + ML ve türev/market-data modülleri; MTF 1h/4h filtreleri. Her modülün her işlemde etkin olduğu varsayılmamalı | Daha odaklı ani hareket/RVOL/ret + 1m bağlam; testte `fade`, ayrıca 60 tam 1m mumdan VWAP/ATR giriş filtresi. Alternatif stratejiler/backtest/shadow araçları var |
| Hazır olma | v37’deki gibi her borsada ayrı `>%90` global başlatma kapısı yok; bazı stale/indikatör kontrolleri var | Her iki borsada da beklenen sembollerin ayrı ayrı `>%90` gösterge+taze-fiyat kapsamı olmadan 5 dk sayaç başlamaz |
| Evren | Paper’da tüm uygun futures kataloğu; live/testnet varsayılan BTC/ETH/SOL; statik filtre ve v7.8 çapraz fiyat kontrolü | Son koşu Binance 522 + filtre sonrası OKX 22 sembol. OKX’te Binance ortakları çıkarılır; public kategori/denylist filtresi var |
| Emir/fill | Maker-limit, fallback/chase/market, reduce-only kapanış, native stop; live’da gerçek venue icrası mümkün | Market veya limit girişi yalnız simüle edilir. Fee/kayma, TP/SL ve funding paper hesabında modellenir; gerçek fill/queue/partial-fill testi değildir |
| Risk muhasebesi | Varsayılan 50 USDT marj × 10x ≈ 500 USDT nominal; cross margin, normal/hard açık pozisyon tavanı 3/6, günlük %5 ve haftalık %12 sınırları. Borsa başına bakiye/pozisyon riskinde önemli açıklar var | 25 USDT paper marj × 10x ≈ 250 USDT nominal; tek sanal bakiye, `(exchange,symbol)` pozisyon anahtarı, config’te max 40 açık/aynı yön, %95 kullanım, günlük %5 sınırı ve simüle stop/TP; CLI ayrıca 10 dk’da max 20 açılış sınırı koyuyor |
| Çıkış | Varsayılan sabit TP kapalı; trailing, kâr kilidi, order-flow ve native/yazılım stop | Stop/TP, erken zarar çıkışı, başabaş/trailing ve azami süre; testte TP/SL ayrı ayrı %0,5 ayarlanmıştı |
| Gözlem/uzaktan yönetim | SQLite, dashboard, Telegram komutları, health/metrics ve opsiyonel WhatsApp/Discord/PagerDuty | CSV/JSON, durum/kapanış kayıtları, süreç tanısı, funding mutabakatı ve araştırma/shadow araçları; ana test bir web komuta merkezi değildi |
| Gerçekleşmiş test kanıtı | Kod kitapları tek başına performans/fill kanıtı değil; v7.8’te kaynak/ağ testleri ayrıca çalıştırılmadı | 413 otomatik test geçti; son 5 dk paper koşusu bitti ama sinyal/trade oluşmadı. Bu performans kanıtı değil |

## 3. Sürümleri ayrı ayrı v37’ye göre konumlandırma

| Karar noktası | v7.7 ile v37 farkı | v7.8’in v7.7’ye göre ek farkı | v37’nin karşılığı |
|---|---|---|---|
| Venue/ticker eşleşmesi | v7.7’de sonraki sürümdeki ilave fiyat uyuşmazlığı filtresi yok | Venue fiyatı/katalog/root kontrolleriyle yanlış ticker/kontrat riskini azaltmaya çalışıyor; kesin varlık-kökeni garantisi değil | OKX–Binance çakışan base’leri OKX evreninden çıkarıp Binance’te tutuyor; statik kategori/denylist ile tamamlıyor |
| Giriş kalitesi | Ortak temel strateji/risk kurgusu | İsteğe bağlı winning-core ve venue fiyat sapması kontrolü eklendi; bazı guard’lar varsayılan YAML’da kapalı, profile göre açılabiliyor | Başlangıçta per-venue >%90 kapsam kapısı, 1m VWAP/ATR ve giriş teyidi; ancak sinyal evreni daha dar |
| Canlı icra | Gerçek borsa emir yolu mevcut | Aynı live kabiliyeti sürüyor; ekstra symbol/fiyat guard’ları emri otomatik güvenli yapmıyor | Gerçek emir yok; paper/replay sınırı sert. Bu güvenlik artısı, canlı kullanım kapasitesi eksisi |
| Operasyon ve paketleme | Canlı/paper uygulaması ve uzaktan kontrol yetenekleri | Yeni release bundle/backup üreticisi geldi; varsayılan sürüm ve DB/paketleme güvenliği sorunları ayrıca denetlenmeli | Paper log/JSON ve test artefaktı var; v7.8’in canlı operasyona yönelik araç seti kadar kapsamlı değil |
| Kanıt | `$95.60 / 30 kapanış` gibi iddialar ham verisiz doğrulanmıyor | Kod değişikliği/kitap eşleşmesi kanıtı var; canlı performans doğrulaması yok | 413 otomatik test geçti; 5 dk koşu 0 trade verdi. Bu da kârlılık kanıtı değil |

**Kısa sürüm hükmü:** v7.8, v7.7’den venue/ticker filtresi ve isteğe bağlı giriş/seans guard’ları bakımından daha iyi bir kod tabanı; fakat ikisinin de canlı emir riskleri ortak. v37, canlı emir yapmama ve veri-hazırlık disiplini bakımından daha güvenli araştırma tabanı; v7.x’in strateji/operasyon kapsamını veya canlı emir yeteneğini sunmuyor.

## 4. v37’nin belirgin artıları

### A. Canlı para sınırı çok daha net

v37 ayar dosyası `paper` ve `replay` modlarını destekliyor; `live` ve `testnet` açıkça reddediliyor. Ana `ws_bot.py` çıktısı da “PAPER-ONLY / emir yok” diye başlıyor. Kaynak taramasında private API anahtarı, imzalı emir, `create_order`, leverage veya margin-setting çağrısı yok. v7.8’de ise paper yalnızca varsayılan; ortam değişkeniyle gerçek işlem yolu açılabiliyor.

**Anlamı:** v37, kullanıcı tarafından belirlenen “yalnız paper, gerçek emir yok” sınırına daha iyi uyuyor. Bunun karşılığında gerçek order-routing ve gerçek fill yeteneği yok.

### B. Hazırlık ve ölçüm disiplini daha belirgin

v37, son 60 tamamlanmış 1m mumdan VWAP ve Wilder ATR hesaplıyor; eksik mum, bayat fiyat veya hazırlıksız venue sinyali reddediyor. Girişte ATR(14) `0,10%` altında kalırsa sinyal eleniyor ve yön VWAP’a göre kontrol ediliyor. Binance ve OKX’in her birinde ayrı ayrı `>%90` kapsam görmeden asıl test süresi başlamıyor. Hazırlık öncesi sinyal sayacı/paper portföyü örnekleme dışı kalıyor.

Son koşu bu kurala uydu: kapı Binance’te **516/522 (%98,85)** ve OKX’te **22/22 (%100)** iken açıldı; warm-up dışındaki sayaç 300,35 saniye sürdü. v7.8’de böyle aynı tür, her venue’yu kapsayan başlatma kapısı yok.

### C. Stale/reset ayrımı ve kanıt izi daha görünür

v37, aggTrade stale paketlerini ayrı sayıyor, hatalı tek pakette gösterge geçmişini `reset()` ile silmiyor ve tam/kısmi resetleri ayrı telemetriye yazıyor. Son koşuda **0 stale**, **0 tam reset** vardı; 1.044 kısmi resetin 522’si başlangıç bağlantısı, 522’si normal kapanış bağlantı düşüşüydü. İşlem/sinyal/pozisyon kayıtları CSV ve JSON’da görülebiliyor.

v7.8’in kullanım yetenekleri daha geniş ama iç denetimde açığa çıkan, belirsiz borsa fill’i ve stopların restart’ta mutabakatı gibi konular v37’nin paper akışında yok; çünkü v37 gerçek fill veya native stop yönetmiyor.

### D. Araştırma araçları zengin ve otomatik test kapsamı çalıştırılmış

v37 repo’sunda backtest, walk-forward, ablation, stres, funding, slippage ve shadow modülleri; ayrıca geniş test paketi var. Güncel kaynakta `py_compile` başarılı ve tam test paketi **413 geçti**. v7.8 kod kitabı/release paketinde test dosyaları bulunsa da önceki statik denetimde v7.8 testleri çalıştırılmamıştı.

**Sınır:** Birim/regresyon testlerinin geçmesi canlı piyasa kârlılığını, fill kalitesini veya gerçek borsa mutabakatını kanıtlamaz.

## 5. v37’nin eksileri ve açık noktaları

### A. 5 dakikalık sonuç başarı/kârlılık ölçümü değil

Testte **0 sinyal, 0 açılış, 0 kapanış, 0 PnL** oldu; bakiye 1.000 USDT kaldı. Bu, yalnızca 5 dakikalık koşuda eşikleri geçen aday oluşmadığını söyler. Strateji iyi/kötü, v7.8’den daha kârlı veya daha güvenli performans veriyor sonucuna varılamaz.

### B. Kapsam test boyunca sabit kalmadı

Başlangıç kapısı doğru biçimde geçti; fakat örnekleme sırasında 18:47:10 UTC’de Binance gösterge+taze-fiyat kapsamı **424/522 (%81,23)** seviyesine indi, kapanış durumunda **508/522 (%97,32)** olarak toparlandı. Tasarım, başlangıçta eşiği aşmayı garanti ediyor; şu anki test akışı eşik altına düşüşte beş dakikalık sayacı otomatik durdurmuyor. Bu nedenle sonraki değerlendirmelerde **başlangıç ve tüm seans boyunca kapsam grafiği/alt-sınır davranışı** raporlanmalı; gerekirse kapsam uzun süre eşik altında kalırsa örnek geçersiz sayılmalı.

Yeni v37 kodunda eksik son 60 dakikalık Binance gösterge mumlarını public kapanmış klines verisiyle tamamlayan backfill eklendi; bu stale resetinden ayrıdır ve yalnız gösterge haritasını günceller. Son koşunun hazır olmasına katkı sağladı. Ancak intraseans kapsam düşüşünün ayrıca izlenmesi hâlâ önemli.

### C. Sinyal motoru v7.8’e göre daha dar ve daha az birleşik

Son koşuda `ws_bot.py` kullanıldı; `fade` varsayılanı, ret/RVOL/1m bağlam, ek VWAP/ATR filtresi, giriş teyidi ve paper risk/çıkış motoru çalışıyordu. Bu yol v7.8’in haber/ML/1h-4h/trend+money-flow/türev skor birleşimi kadar geniş değil. v37 repo’sunda başka strateji/backtest modülleri bulunması, bunların hepsinin `ws_bot.py` canlı tarama yolunda ana karara bağlandığı anlamına gelmez; README bazı adayları açıkça **SHADOW** olarak tanımlıyor.

Bu daha dar kapsam, araştırmayı daha açıklanabilir kılabilir; fakat farklı piyasa durumlarını yakalama kapasitesini ve v7.8 ile strateji eşitliğini düşürür.

### D. Sürüm etiketi/entrypoint karışıklığı

v37 klasöründeki README başlığı temel `main.py` uygulamasını **v18** diye etiketliyor; bu karşılaştırmada test edilen sürekli tarayıcı ise `ws_bot.py`. Repo aynı anda birden fazla uygulama yolu ve deneysel modül içeriyor. Dolayısıyla README’deki her strateji/CLI açıklamasını `ws_bot.py` koşusuna atfetmek doğru değil; rapor, v37 sonucu olarak yalnız test edilen `ws_bot.py` yolunu esas alıyor. Sonraki testlerde commit/hash, komut satırı ve giriş noktası beraber arşivlenmeli.

### E. Gerçek yürütme ve borsa risklerini test edemez

v37 simülasyonunda maker limitin gerçek emir kuyruğunda beklemesi, kısmi fill, borsa reddi, API timeout sonrası remote fill, reduce-only, native stop tetiklenmesi, leverage/margin değişimi ve iki venue’nun ayrı cüzdan marjı test edilmiyor. Örneğin 25 USDT × 10x paper nominali gerçek hesapta 250 USDT’lik gerçek pozisyon açıldığı anlamına gelmez.

v7.8 bu işlevleri kaynak seviyesinde sunuyor; bu onun fonksiyonel artısıdır, fakat yukarıda raporlanan cross-balance, emir mutabakatı ve restart-stop sorunları nedeniyle aynı zamanda büyük riskidir.

### F. Evrensel “saf kripto/ABD kökeni” garantisi yok

v37 OKX `instCategory=1`, overlap temizliği ve `is_stock_like` denylist’i kullanıyor; bu, v7.8’deki geniş statik/root filtresine benzer bir savunma. Yetkili ve tam bir şirket-kökeni listesi yok. v37 son koşusunda OKX’te 4 stock-like eşleşme ve 263 Binance ortak sembolü elenip 22 sözleşme kaldı. Bu pratik filtreleme kanıtıdır; %100 sınıflandırma garantisi değildir.

### G. Tek sanal kasa, iki ayrı venue simülasyonunu tam temsil etmez

v37 pozisyonları `(exchange,symbol)` ile ayırır ve aynı base varlığın iki borsada aynı anda açılmasını engeller. Fakat `PaperPortfolio` tek bir sanal bakiye/özsermaye üzerinden tüm paper pozisyonlarını yönetir. Paper deneyinde bu kabul edilebilir bir ortak kasa varsayımıdır; **iki ayrı Binance/OKX hesabının ayrı bakiyelerini** doğru simüle etmez.

## 6. v7.7/v7.8’in v37’ye göre artıları ve eksileri

### v7.x’in artıları

- v7.8’de gerçek Binance/OKX emir yürütme, order türü/fill denemeleri, native stop, leverage/margin ve venue seçimi var; v37’de bunlar yok.
- Daha geniş birleşik sinyal kaynakları: teknik, flow/CVD, haber/duygu, ML ve türev verisi. 1h/4h MTF ve çok sayıda filter/exit kuralı sunuyor.
- SQLite geçmişi, dashboard, Telegram uzak komutları ve çeşitli bildirim kanallarıyla operasyonel kumanda daha kapsamlı.
- v7.8, v7.7’ye kıyasla ticker/kontrat uyuşmazlığına yönelik ek fiyat ve katalog filtresi içeriyor.

### v7.x’in eksileri

- **Paper-only değil.** Bir ortam değişkeni ve onay anahtarıyla gerçek emir yoluna geçilebilir; v37’de bu yol reddediliyor.
- Binance ve OKX’in ayrı cüzdanları tek cross kasa gibi hesaplanabiliyor. Bu v7.8’in en kritik gerçek para riskidir; v37’de gerçek borsa cüzdanı olmadığı için aynı canlı risk yok.
- Native stop kayıtlarının restore edilmesi, iptal hataları, belirsiz fill mutabakatı ve normal shutdown sırasında açık live pozisyon davranışı sorunlu.
- Global `>%90` venue hazırlık kapısı yok; v37’nin örnekleme öncesi veri-kapsam disiplini v7.x’ten daha iyi tanımlı.
- Web/Telegram/health uçları ve DB/backup daha fazla saldırı yüzeyi ve veri mahremiyeti yükü getiriyor.
- Daha fazla bileşen, mod ve konfigürasyon karmaşıklığı; v7.8’de kod kitabı/README/startup/release varsayılanları arasında v7.2/v7.7/v7.8 etiket uyumsuzluğu var.

## 7. v37’deki gerçek test ve kanıt sınırı

Son tamamlanan paper koşusu (29 Ekim 2026):

- Hazırlık kapısı: Binance **516/522 (%98,85)**, OKX **22/22 (%100)**.
- Beş dakikalık sayaç warm-up hariç **300,35 saniye**.
- Sinyal/açılan/kapanan/PnL: **0 / 0 / 0 / 0,0000 USDT**; sanal bakiye **1.000 → 1.000 USDT**.
- AggTrade: **303.644 kabul**, 0 stale, 0 geçersiz, 0 tam reset; normal başlangıç/kapanış kaynaklı toplam 1.044 kısmi reset.
- Bu koşuda kullanılan temel ayarlar: `--pencere-ms=60000` (60 sn), `--ret=0.2%`, `--rvol=2.0`, `--baglam-ret=0.5%`, `fade`, giriş teyidi açık, paper `TP=0.5%` / `SL=0.5%` ve Binance `aggtrade` hacim kaynağı. Dolayısıyla bu sonuç varsayılan CLI eşiklerinin tamamını temsil etmez.
- Uygun yorum: “Bu kısa koşu teknik olarak tamamlandı ve başlangıçta kapsam şartını geçti; piyasa/filtre bu sürede trade üretmedi.” Uygun olmayan yorum: “v37 kârlı”, “v37 v7.8’den iyi”, “canlı performansı kanıtlandı”.

## 8. Kullanım kararı

### Şu anda hangisini seçmeli?

- **Paper araştırma, sembol evreni/akış/kapı testleri:** v37. Daha uygun ve canlı emir riski kod düzeyinde kapalı. Ancak sonuçları daha uzun, farklı piyasa rejimlerinde ve kapsam düşüşünü takip ederek toplamak gerekir.
- **Gerçek emir/operasyon otomasyonu:** v7.8 daha fazla işlev sunuyor ama şu anki bulgularla canlıya alınmasını önermiyorum. Özellikle venue başına bakiye/marj, belirsiz order fill, native stop restore ve shutdown davranışı düzeltilmeden gerçek API anahtarı verilmemeli.
- **Strateji performansı kıyaslaması:** İki botun aynı dönem, aynı sembol listesi, aynı fee/funding/slippage ve aynı giriş/çıkış tanımıyla eşleştirilmiş paper testleri yapılmalı. Mevcut v37 5 dk/0 trade sonucu ile v7.7 kapak iddiaları kıyaslanamaz.

### Önerilen sonraki adımlar

1. v37’de her borsa için hazır kapsamı sadece başlangıçta değil, testin tamamında kaydedin; örnekleme içi kapsam uzun süre eşik altına düşerse seansı “geçersiz/eksik kapsam” olarak işaretleyin.
2. En az birden çok saat/gün kapsayan paper örnekleri toplayın; işlem adedi, net ücret/funding sonrası PnL, MFE/MAE, stale/reset, drop/coverage ve venue bazında sonuçları birlikte raporlayın.
3. v7.8’i live’a taşımadan önce venue-bazlı risk hesabı, order reconciliation ve stop restore/shutdown için entegrasyon testleri ekleyin.
4. İki botun sürüm/entrypoint’ini sabitleyin: v37 `ws_bot.py` sürekli tarayıcısı ile v37 `main.py`/backtest/SHADOW stratejilerini birbirine karıştırmayın.
5. Her iki kod tabanındaki “7 gün”, “kazanan”, “28/28” gibi yorumları ham CSV ve tekrarlanabilir raporla desteklenmeden performans kanıtı saymayın.

## 9. Kaynaklar

- v7.7/v7.8 karşılaştırmalı statik analiz: `/home/user/KRIPTO_BOT_v7_7_v7_8_KARSILASTIRMALI_ANALIZ.md`
- v7.8 tam statik denetim: `/home/user/KRIPTO_BOT_v7_8_STATIK_DENETIM_RAPORU.md`
- v37 son paper koşusu: `/home/user/Futures_Bot_v37_Deneysel_Paper_SON/futures_bot_v37/run_artifacts/v37_paper_test_final_report_2026-10-29.md`
- v37 çalışma logu/durum: `run_artifacts/attempt4/v37_paper_test.log`, `logs/ws_durum.json`, `logs/ws_kapanis.json`.
