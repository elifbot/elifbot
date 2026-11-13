# KRIPTO-BOT v7.8 — Statik işlem ve yan etki denetimi

**Tarih:** 29 Ekim 2026  
**İncelenen dosya:** `/home/user/uploads/KRIPTO_BOT_v7_8_TEK_DOSYA_KURUCU.py`  
**SHA-256:** `8ddc240c531f7b347b68381482403c4ef4b622a277bf2ecfa2fe64651be65d22`

## 1. Kısa sonuç

**Bu paket yalnızca paper bot değildir.** YAML ayarının varsayılanı `paper` olsa da, ortam değişkeniyle `testnet` veya `live` seçilebiliyor. `live` modunda uygun Binance/OKX API kimlik bilgileri ve canlı işlem onayı varsa kaynak kodu gerçek USDT perpetual emirleri gönderebiliyor; ayrıca hesapta marj türü ve kaldıraç ayarlamaya çalışıyor.

Öte yandan, pakete dahil GitHub Actions’taki `paper-live.yml` **gerçek emir çalıştırmıyor**: `MODE=paper` olarak sabitlenmiş ve Binance/OKX işlem API anahtarlarını ortama koymuyor. Buradaki “live”, gerçek piyasa verisini anlatıyor.

**Bu denetimde hiçbir bot, kurucu, test veya workflow çalıştırılmadı.** Gömülü içerik statik olarak çözümlendi. Paketin içinde gerçek işlem veritabanı, borsa emir/fill kaydı, `live_trades.csv` veya çalışma günlüğü bulunmadığından, geçmişte işlem gerçekleştiğini söylemek ya da işlem adedi/PnL raporlamak mümkün değil. Aşağıdaki liste kodun *yapabileceği* işlemleri ve yan etkileri anlatır; gerçekleşmiş işlem kanıtı değildir.

## 2. Kapsam ve kurucu dosyanın yaptığı

Kurucu 21 satır ve 407.254 bayt. İçindeki `FILES` sözlüğü güvenli statik çözümleme ile açıldı; 74 dosya ve toplam 1.082.646 bayt `/home/user/kripto_bot_v7_8_audit_extract/` altına çıkarıldı. Dosya hash’leri `MANIFEST.sha256` içinde.

Kurucunun kendisi `argparse`, `base64`, `zlib`, `pathlib` kullanıyor; `--hedef` ile hedef dizini seçip gömülü dosyaları yazıyor (varsayılan `kripto-bot-v7.8`). **Botu başlatmıyor, bağımlılık kurmuyor ve ağ/emir çağrısı yapmıyor.** Aynı adla var olan dosyaların üzerine yazabilir; kurulum öncesi hedef dizini kontrol edilmeli. Mevcut gömülü yolları ayrıca doğruladım; bu denetimde paket dışına çıkan bir yol görülmedi. Kurucu kodu: ekli dosya, satır 7–21.

## 3. Varsayılan çalışma ve strateji

### Varsayılan ayarlar

`config.yaml` ve `src/main.py` birlikte değerlendirildiğinde:

- Borsalar: **Binance + OKX**; varsayılan sembol listesi BTC/USDT, ETH/USDT, SOL/USDT.
- YAML modu: **paper**; başlangıç sanal bakiyesi **100.000 USDT**.
- Kaldıraç: **10x sabit** (`dinamik_kaldirac: false`). Pozisyon boyutu `sabit_usdt`: **50 USDT marj × 10x ≈ 500 USDT nominal**; bakiye 50 USDT’nin altındaysa giriş reddedilir.
- Marj türü: **cross**. Çapraz kapasite ayarı %95, asgari serbest bakiye 50 USDT. Bu, 50 USDT’nin canlı hesaptaki azami kayıp olduğu anlamına gelmez.
- Sinyal ağırlıkları: teknik %40, para akışı %30, haber/duygu %15, ML %15. Ana skor eşikleri LONG `+55`, SHORT `−55`; güçlü para akışı ayrıca daha düşük toplam skorla tetikleyebilir. Short işlemlere izin var.
- 1h/4h trend filtresi, order-flow onayı, exhaustion/range/teknik-uyum ve likidasyon-mıknatısı giriş filtreleri etkin. PDF v3 ve türev kalabalık verisi de yapılandırmada açık; PDF v2 ve Shadow Lab temel YAML’da kapalı.
- 5 dakikalık mumlar; gerçek zamanlı trade, order book ve tasfiye akışı; haberler yaklaşık 60 saniyede bir yenileniyor.

### Sembol evreni

`futures.tum_pariteler: true` olmasına rağmen bütün katalog **yalnızca `MODE=paper` iken** açılıyor. Paper’da Binance/OKX’in aktif, USDT uzlaşmalı perpetual katalogları keşfediliyor; 10x desteklemeyenler analizde tutulup yeni emirden çıkarılıyor. Kripto dışı ürünleri ayıklamak için sabit sembol denylist’i, borsa enstrüman etiketleri ve Binance kök-varlık karşılaştırması kullanılıyor. Bu, faydalı bir filtre olsa da kod yorumundaki “%100 dışla” iddiası kadar otoritatif/garantili değildir; yeni veya ticker’ı çakışan enstrümanlarda yanlış sınıflama ihtimali vardır.

`testnet`/`live` modunda tam katalog keşfi devreye girmiyor; varsayılan üç sembol kullanılıyor. Kullanıcı daha geniş bir canlı liste tanımlarsa her sembolün iki borsadaki dayanak eşleşmesi ayrıca doğrulanmalı.

### Açılış, stop ve kapanış

- Canlı/testnet girişten önce `set_margin_mode(...)` ve `set_leverage(...)` çağrıları yapılır. Varsayılan cross marj ayarını borsada değiştirmeye çalışır; kaldıraç ayarı başarısız olursa emir açılışı durur.
- Varsayılan giriş tipi `maker`. Canlıda `postOnly` limit emri denenir; yaklaşık 3 saniye dolum beklenir. Kalan miktar iptal edildikten ve durumu okunabildikten sonra, kayma sınırına göre chase-limit veya market emirle tamamlanabilir. Fiyat farkı %0,30’u aşarsa chase-limit akışı kullanılır; chase en fazla üç adım dener.
- Paper’da `gercekci_yurutme: true` olduğundan aynı `maker` ayarı gerçek maker kuyruğu gibi simüle edilmiyor: market alışta ask/satışta bid üzerinden sanal dolum, taker komisyonu ve kayma kaydı kullanılıyor. Paper dolumları borsa emri değildir.
- Varsayılan stop modeli `marj`; 10x’te yaklaşık %8 fiyat mesafesi, 500 USDT nominal pozisyonda yaklaşık **40 USDT brüt fiyat zararı** hedefler. Komisyon, funding, ani fiyat boşluğu, slippage ve likidasyon koşulları bu tutarı aşabilir.
- Borsa koruması açık. Girişten sonra native stop (tercihen `STOP_MARKET`, desteklenmezse alternatif stop türleri) kurulmaya çalışılır. Kurulum olmazsa “yazılım stopu”na düşer; o durumda stopun çalışması botun ve fiyat akışının ayakta kalmasına bağlıdır.
- Sabit take-profit kapalıdır: `islem_plani.aktif: false` ve giriş korumasına `tp_price=None` veriliyor. Dolayısıyla varsayılan olarak borsaya TP emri gönderilmez. Kâr; stop/trailing, Supertrend, order-flow dönüşü ve net başabaş korumasıyla yönetilir. ATR/swing 1R–2R ve TP1’de kısmi kapama ancak işlem planı ayrıca açılırsa devreye girer.
- Tam veya kısmi kapanışlar market emirle yapılır; canlı/testnet kapanışında `reduceOnly=True` kullanılır. Stop/koruma emirleri iptal edilip gerekirse yenilenir.
- `sinirsiz_ekleme: false`, `max_kademe: 1`: varsayılan profilde pozisyona kademe eklenmez. Çapraz kurtarma kapalıdır.
- Ana YAML’da `firsat_takasi_aktif: true`: cross havuz kapasitesi dolduğunda, en az 8 dakika açık kalmış ve fiyat PnL’i yaklaşık −%1,50 ile +%0,25 arasında olan daha zayıf pozisyon yeni sinyale yer açmak için kapatılabilir. Bu, kapanışın mutlaka kârla olacağı anlamına gelmez. Kontrollü GitHub paper profili bunu kapatıyor.

## 4. Canlı emir için gerekenler

`src/config.py` içindeki `MODE` ortam değişkeni, YAML’daki modu **ezer**. Canlı mod için:

1. `MODE=live` olmalı.
2. Etkin her borsa için API kimlik bilgileri bulunmalı: Binance `BINANCE_API_KEY`/`BINANCE_API_SECRET`; OKX `OKX_API_KEY`/`OKX_API_SECRET`/`OKX_API_PASSPHRASE`.
3. `LIVE_TRADING_CONFIRM=YES_I_RISK_REAL_MONEY` olmalı.

Onay eksikse yapılandırma yüklenmez. Onay varsa uygulama canlı uyarısından sonra beş saniye bekler ve devam eder; **bu bekleme bir insan onayı/prompt’u değildir**. `MODE=testnet` CCXT sandbox moduna geçer; testnet de gerçek borsa hesabı yerine test ortamıdır.

Paper modda bakiye sanaldır; emir, bakiye ve pozisyon yolları `PaperBroker`’a ayrılmış. Paper ayarında API anahtarları olsa bile incelenen akışta gerçek emir/bakiye çağrısı yapılmıyor. Ancak `.env`/ortam içeriği bu pakette yok; kurulu ortamın gerçekten paper mı olduğu buradan doğrulanamaz.

Kodda Binance/OKX’e emir, iptal, kaldıraç ve marj ayarı çağrıları var. **Para çekme, yatırma veya hesaplar arası transfer çağrısı bulmadım.** Bu, API anahtarının yetkilerini sınırlandırma gereğini ortadan kaldırmaz.

## 5. Risk ve otomatik durdurma davranışı

- `live`/`testnet` için normal açık-pozisyon sınırı **3**; paper’da geniş-limit bayrağı nedeniyle temel YAML’ın kontrol sınırı **1.000** (aynı yönde 25). Kağıt üzerindeki bu limitler gerçek marj kapasitesini garanti etmez.
- Günlük zarar eşiği %5, haftalık %12. Bunlar yeni girişleri engeller; günlük Circuit Breaker tetiklendiğinde kod diğer açık pozisyonları otomatik olarak mutlaka kapatmıyor, açık pozisyonların stop/izleme akışı devam ediyor.
- Varsayılan `risk.marj_modu: cross` iken giriş kodu `cross_pool_ok` yolunu kullanıyor. Bu yol, `toplam_marj_tavani_yuzde: 60` ayarındaki `margin_cap_ok` kontrolünü kullanmıyor; cross havuzu için %95 eşiği ve asgari serbest bakiye kullanılıyor. Yani YAML’da görünen %60 tavanı bu varsayılan cross akışında etkin sert tavan değil.
- Üç ardışık emir hatası sigortayı tetikleyebilir; üç ardışık kimlik/yetki hatası sistem kilidi oluşturabilir. WebSocket 10 saniyeden uzun sessiz kalırsa acil kapama; BTC/ETH’de 60 saniyelik pencerede yaklaşık %8 şokta tüm yerel pozisyonları kapama; tekil altcoin şokunda ilgili pozisyonu kapatıp 15 dakika yeni girişe ara verme yolu var.
- Manuel Telegram `/kill` ve panel kill-switch tüm yerel açık pozisyonları kapatmaya çalışır ve kilitler. `/durdur` yalnız yeni girişleri duraklatır; pozisyonları kapatmaz. `/baslat`/`/sigorta` botu yeniden etkinleştirebilir.

## 6. Önemli teknik risk bulguları

### Yüksek — Binance ve OKX hesapları tek bir ortak cross havuzuymuş gibi hesaplanıyor

`fetch_balance_usdt()` ilk başarılı borsanın USDT bakiyesini döndürüyor. Girişte ise `best_price()` sembol için başka borsayı seçebilir. Sonra `Executor` iki borsadaki pozisyonların marj/notional değerlerini tek havuzda toplayıp ilk borsanın bakiyesiyle karşılaştırıyor. Binance ve OKX ayrı hesap/cross-margin cüzdanları olduğundan, bu hesap gerçek kullanılabilir marjı temsil etmeyebilir; yanlış boyut, emir reddi veya bir borsada beklenenden büyük kullanım riski doğurur. **Canlı kullanım öncesi borsa başına bakiye/marj muhasebesi veya tek borsa kısıtı gerekli.** Kaynak: `src/exchanges.py:816–833, 725–776`; `src/executor.py:981–1050`.

### Yüksek — Sonucu belirsiz/iptal edilemeyen girişte gerçek fill yerel kayda girmeyebilir

Giriş emri borsaya ulaşmış olsa da timeout, `fetch_order` hatası veya maker iptalinin doğrulanamaması durumunda `execute_entry()` hata fırlatabilir. `Executor._open()` bu hatayı yakalayıp yeni yerel pozisyon kaydı oluşturmaz. Böylece kısmen/tamamen dolmuş gerçek pozisyon botun yerel durumunda görünmeyebilir. Kod çift emir riskini azaltmak için otomatik tekrar yapmıyor; bu iyi bir koruma, ancak belirsiz emir ID’sini takip edip fill’i mutabakatla benimsemiyor. Daha sonra borsa mutabakatı sahipsiz pozisyonu yalnız alarm olarak bildiriyor; otomatik devralmıyor veya kapatmıyor. **Belirsiz girişten sonra borsa arayüzünde pozisyon/emir kontrolü şart.** Kaynak: `src/exchanges.py:925–975, 1131–1182`; `src/executor.py:973–1168, 212–260`.

### Yüksek — Stop koruması yeniden başlatmada geri yüklenmiyor; normal durdurma canlı pozisyonu kapatmıyor

SQLite’tan pozisyonlar geri yükleniyor, fakat native koruma emirlerinin ID’leri `_prot` olarak kalıcılaştırılmıyor ve `restore_state()` bunları borsadan geri okumuyor/yeniden kurmuyor. Mutabakat da pozisyon farklılığını alarm ediyor, korumayı otomatik benimsemiyor. Ayrıca normal Ctrl-C/iptal kapanış bloğu market/websocket’i durdurup CCXT istemcisini kapatıyor; **live pozisyonları otomatik kapatmıyor**. Native stop borsada kalmış olabilir; yazılım stopu ise süreç kapalıyken çalışmaz. Kaynak: `src/executor.py:142–260`; `src/main.py:1554–1587`.

### Orta-yüksek — Native stop iptal hataları görünmez kalabilir

`cancel_protection()` her `cancel_order()` hatasını yutuyor ve borsa erişilebiliyorsa başarılı gibi `True` döndürüyor. Sonuçta eski stop iptal edilmeden yenisi kurulabilir veya pozisyon kapandıktan sonra eski reduce-only emir kalabilir; üst katman iptal başarısızlığı uyarısı üretemeyebilir. Ayrıca native stop kurulamazsa yazılım-stop fallback’i sessizce devam edebiliyor. Kaynak: `src/exchanges.py:1220–1356`.

### Orta — Günlük/haftalık zarar sayacı net değil, brüt PnL kullanıyor

İşlem geçmişinde `net_pnl_usdt` ücret ve funding’i içeriyor; ancak risk limiti/Circuit Breaker’a aktarılan `eq_pct`, `pnl_usdt` yani **brüt fiyat PnL’i** üzerinden hesaplanıyor. Komisyon/funding yüzünden gerçek net zarar eşik aşmış olsa bile koruma sayacı daha düşük zarar görebilir. Kaynak: `src/executor.py:1570–1638`.

### Orta — Sağlık uçları kimlik doğrulamasız

Ana botun `/health`, `/healthz`, `/metrics` sunucusu varsayılan `0.0.0.0:8502` üzerinde auth olmadan çalışıyor; health payload’ı bakiye, özsermaye, açık pozisyon sayısı, mod ve sigorta durumunu içeriyor. Ayrı dashboard’da `/api/state` ve `/api/action` token/loopback korumalı olsa da `/health` ve `/metrics` korumasız. Ağdan erişilebilen ortamlarda portu firewall ile sınırlandırın veya auth ekleyin. Kaynak: `src/health.py:141–170`; `src/dashboard.py:1043–1120`; `config.yaml:58–61`.

### Orta — Telegram grup kimliği kullanılırsa tüm grup üyeleri komut gönderebilir

Telegram komut yetkisi `message.chat.id` ile doğrulanıyor; gönderen kişinin `from.id` alanı kontrol edilmiyor. `TELEGRAM_CHAT_ID` özel bir grup/süpergrup ID’siyse gruptaki her üye `/kill`, `/baslat` veya `/sigorta` gönderebilir. Yalnız özel birebir sohbet kullanın ya da gönderen kullanıcı ID’sini de doğrulayın. Kaynak: `src/telegram.py:189–199, 811–853`.

## 7. Dış ağ ve yerel yan etkiler

### Dış ağ

- Binance/OKX public REST ve WebSocket: mum, ticker, trades, order book, funding, open interest ve tasfiye verileri.
- PDF v3/türev kalabalık kontrolü açıkken Binance/OKX ve Deribit public uçlarına istekler.
- CoinDesk ve Cointelegraph RSS; `CRYPTOPANIC_KEY` varsa CryptoPanic haber API’si.
- Telegram token/chat ID varsa 5 dakikada bir rapor ve olay mesajları; bot ayrıca `/getUpdates` ile komut dinliyor. WhatsApp, Discord webhook ve PagerDuty yalnız ilgili sırlar tanımlıysa kullanılıyor. Rapor/uyarılar bakiye, açık pozisyon ve PnL gibi operasyonel verileri içerebilir; Discord kritik alarmında `@everyone` yayınlanabiliyor.
- `LLM_API_URL`/`LLM_API_KEY` için kodda LLM istemcisi var; fakat statik aramada ana `src.main` akışından `score_async()` çağrısı bulmadım. Mevcut ana döngünün haber puanı yerel sözlükle çalışıyor; bu yüzden LLM’ye otomatik haber gönderimi bu kod yolunda doğrulanmadı.

### Dosyalar/veritabanı

Bot çalıştırılırsa `bot_state.db` (SQLite WAL) oluşturup açık pozisyon, trade geçmişi, equity, metadata ve panel komut kuyruğunu yazar. Kelly geçmişi `kelly_stats.json`’a kaydedilir. Zamanlı paper oturumunda `reports/` altına günlük TXT, oturum JSON’u ve işlem geçmişi JSON’u yazılır; erken durdurmada `partial_` raporları oluşturulur. Günlük bakım eski DB satırlarını `.jsonl.gz` arşivine taşıyıp DB’den siler ve `VACUUM` çalıştırır. Başka oturumdan kalan paper kasa/pozisyonu aynı DB’den geri yüklenebilir; GitHub paper workflow’u her oturum başında DB’yi siler.

### Uzaktan kontrol

- Telegram: `/durum`, `/guncel`, `/karzar`, `/rapor`, `/gunluk`, `/piyasa`; `/kill` tüm pozisyonları kapatmaya çalışır ve kilitler; `/durdur` yeni girişleri durdurur; `/baslat` devam ettirir; `/sigorta` Circuit Breaker’ı sıfırlar.
- Dashboard’ı ayrı olarak `python -m src.dashboard` başlatır (ana `src.main` kendisi panel sunucusunu başlatmıyor). Panel kill-switch, duraklat/devam, sigorta sıfırlama, SQLite GC ve sembol bazlı kapama eylemleri SQLite komut kuyruğuna yazılıyor.
- Ana botun `HealthCheckServer`’ı `src.main` tarafından ayrıca başlatılır.

## 8. GitHub Actions ve paket tutarlılığı

- `.github/workflows/paper-live.yml`: push ile belirli paper istek JSON’ları veya manuel çalıştırma; `MODE=paper`, borsa API anahtarı yok. Gerçek verili sanal seans, başlangıç doğrulamaları, Telegram/WhatsApp mesajları, 7 gün saklanan artifact’lar ve `analysis/` kanıtlarını dala commit/push etme var.
- `.github/workflows/paper-control.yml`: belirtilen GitHub Actions paper run’ını iptal eder.
- `.github/workflows/exchange-connectivity.yml`: public borsa endpoint/WebSocket erişim testi; emir gönderme kodu yok.
- `.github/workflows/whatsapp-verify.yml`: yalnız bağlantı kontrolü değil; yapılandırılmışsa gerçek bir WhatsApp test mesajı gönderiyor ve durum JSON’unu dala yazıyor.
- **Süre eşleşmezliği:** `paper-60-shadow-request.json` 60 dakika ister; workflow bu dosyayı `controlled-no-cross-rescue` profiline eşliyor, bu profil ise `paper-120-control.json` kullanıyor ve `paper_session_minutes: 120` içeriyor. Push sırasında manuel süre girdisi olmadığından profil adımı `PAPER_MINUTES`’ı 120’ye çevirebilir. Bu tetik yolunu çalıştırmadan düzeltip doğrulayın. Kaynak: `.github/workflows/paper-live.yml:247–309`; `configs/paper-120-control.json`; `configs/paper-60-shadow-request.json`.
- `.github/workflows/test.yml` `requirements-dev.txt` kurmaya çalışıyor; çıkarılmış 74 dosya içinde bu dosya yok. Bu nedenle test workflow’u bu paketten tek başına kurulurken başarısız olabilir. `requirements.txt` içinde de pytest/ruff yok.
- Sürüm etiketi tutarsız: kurucu adı v7.8; README, `config.yaml`, `src/main.py` docstring’i ve dashboard v7.2; ana bot başlık çıktısı v7.7. Bu, paketin sürüm/provenansını doğrulamayı zorlaştırıyor. README içinde belirtilen performans/geçmiş iddiaları ekli işlem günlüğüyle desteklenmiyor.

## 9. Genel değerlendirme ve kullanmadan önce öneriler

1. **Canlı kullanmayacaksanız** `MODE=paper` değerini çalıştırma ortamında açıkça sabitleyin; `LIVE_TRADING_CONFIRM` tanımlamayın ve borsa API anahtarlarını ortamdan kaldırın. Anahtar gerekiyorsa çekim yetkisini kapatıp IP kısıtı uygulayın.
2. **Canlı kullanımdan önce** Binance/OKX’i tek cross havuzu gibi ele alan bakiye/marj mantığını düzeltin veya tek borsa ile sınırlandırın.
3. Belirsiz emir sonucu için client-order-ID ile emri/fill’i borsadan takip edip yerel pozisyonu mutabakata alan bir kurtarma ekleyin; sahipsiz pozisyonları yalnız alarmda bırakmayın.
4. Stop emir ID’lerini kalıcılaştırın, yeniden başlatmada borsadaki açık emirleri okuyup miktar/stop ile mutabakat yapın; iptal başarısızlığını başarı saymayın.
5. Normal shutdown davranışını açıkça belirleyin: açık pozisyonları kapatmak mı, yoksa native stopu borsada bırakıp operatöre alarm vermek mi? Mevcut kodda live pozisyon otomatik flatten edilmiyor.
6. Cross modda %60 yorumuyla %95 cross limitinin hangisinin amaçlandığını netleştirin; günlük/haftalık kayıp ölçümünü net PnL ve ücret/funding ile uyumlu hale getirin.
7. Health/metrics erişimini firewall veya kimlik doğrulamasıyla sınırlandırın; Telegram’da grup ID yerine kişisel sohbet/sender ID kullanın.
8. 60→120 dakika workflow eşleşmesini, sürüm etiketlerini ve eksik `requirements-dev.txt` dosyasını düzeltin.

## 10. Sonuç sınırı

Bu rapor **statik kaynak kodu denetimidir**, finansal performans doğrulaması veya gerçekleşmiş işlem dökümü değildir. Gömülü bot/kurucu çalıştırılmadı; yeni botun testleri de bu denetimde çalıştırılmadı. Gerçek işlemleri raporlamak için çalışma ortamının `.env`/gizli değişkenlerini paylaşmadan, borsa hesaplarından indirilmiş emir/fill geçmişi veya ilgili `bot_state.db`/log dosyaları ayrıca incelenmelidir.
