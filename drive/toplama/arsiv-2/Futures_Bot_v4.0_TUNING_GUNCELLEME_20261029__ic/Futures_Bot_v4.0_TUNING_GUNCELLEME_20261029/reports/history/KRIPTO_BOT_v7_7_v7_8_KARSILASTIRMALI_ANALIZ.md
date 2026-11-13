# KRIPTO-BOT v7.7 ve v7.8 kod kitapları — karşılaştırmalı analiz

**Tarih:** 29 Ekim 2026  
**İncelenen ekler:**
- `KRIPTO_BOT_v7_7_TUM_KODLAMASYON.md` — 829.568 bayt; SHA-256 `bab6dd25195788f62e4a45752a43081abca356351989560ecbf9d597ad472933`
- `KRIPTO_BOT_v7_8_TUM_KODLAMASYON.md` — 840.100 bayt; SHA-256 `0283133c8a9175e02c084d658d42ba41b1917e078a6095cb5a5a683ecf82191c`

## 1. En net sonuç

**v7.8, strateji/risk yapılandırmasını baştan değiştiren yeni bir sürüm değil.** İki kod kitabındaki ortak bölümlerin büyük kısmı aynıdır: `config.yaml`, `requirements.txt` ve 34 ortak kod dosyası aynı metindir. v7.8’de beş mevcut modülde değişiklik ve bir yeni modül vardır:

1. Borsalar arası fiyat/ticker çakışmasına karşı ek filtre (`src/exchanges.py`, `src/executor.py`).
2. OKX kripto dışı/sentetik sözleşme sızıntısını azaltmaya yönelik ek katalog filtresi (`src/futures_catalog.py`).
3. İsteğe bağlı çekirdek sinyal filtresi ve paper oturumunun sonundaki yeni giriş yasağı (`src/trade_quality.py`, `src/main.py`).
4. Yeni dağıtım/backup üreticisi (`src/release_bundle.py`).

Bu değişiklikler **çakışan sembol adından yanlış borsada işlem açma riskini azaltmaya çalışıyor**, fakat tüm riskleri çözmüyor. İki borsanın ayrı hesap bakiyelerinin tek ortak cross-marj havuzu gibi hesaplanması, stopların yeniden başlatmada doğrulanmaması ve normal kapanışta canlı pozisyonların otomatik kapatılmaması gibi temel riskler iki sürümde de mevcut.

**İki kod kitabında da geçmişte gerçekten işlem yapıldığını kanıtlayan işlem veritabanı, borsa fill dökümü veya doğrulanabilir performans raporu yok.** v7.7 kapağındaki `+$95.60 / 30 kapanış` ve `28/28` gibi sayılar, ham işlem verisi ve tekrar üretilebilir test sonucu olmadan doğrulanmış performans sayılmaz.

## 2. Kapsam ve doğrulama yöntemi

Bu incelemede iki Markdown dosyasının başlıkları ve gömülü kod blokları statik olarak ayrıştırılıp karşılaştırıldı. **Bot, kurucu veya release üreticisi çalıştırılmadı; borsaya emir gönderilmedi.**

- v7.7 kod kitabında **39** dosya bölümü bulunuyor. Ayrıca başta hızlı kurulum ve modül haritası var.
- v7.8 kod kitabında **40** dosya bölümü bulunuyor; yeni bölüm `src/release_bundle.py`. v7.8 kitabında hızlı kurulum ve v7.7’deki ayrıntılı modül haritası yok.
- v7.8 kod kitabındaki 40 dosya bölümü, önceki v7.8 kurucusundan statik çıkarılmış gerçek kaynak dosyalarıyla **40/40 içerik olarak eşleşti** (son satırdaki newline farkı hariç).
- Ancak v7.8’in gerçek paketi 74 dosya içeriyor; kod kitabında olmayan **34 dosya** README, 10 profil/istek JSON’u, 5 GitHub workflow’u, 16 test ve iki kök test dosyasıdır. Yani dosyanın adı “tam kodlamasyon” olsa da **tam release paketinin bütün dosyalarını göstermez**.
- v7.7 için yalnızca Markdown kod kitabı verildi; ona karşılaştırılacak ayrı v7.7 ZIP/kurucu sağlanmadı. Bu nedenle v7.7’nin gerçek dağıtım paketinin bu kitapla birebir aynı olduğu doğrulanamıyor.

## 3. Sürüm farkı — dosya bazında

| Dosya | v7.7 → v7.8 değişikliği | Pratik etkisi |
|---|---|---|
| `config.yaml` | **Aynı** | Varsayılan mod, marj, kaldıraç, risk ve strateji parametreleri değişmemiş. |
| `requirements.txt` | **Aynı** | Bağımlılık listesinde değişiklik yok. |
| `src/exchanges.py` | 35 satır ekleme, 4 silme | Borsalar arası ticker fiyatı büyük ölçüde ayrışırsa ikincil venue’yu dışlama; `LONG/BUY` ve diğer yönler için fiyat seçimini açıklaştırma. |
| `src/executor.py` | 15 satır ekleme | Sinyal fiyatı ile birincil olmayan borsanın icra fiyatı arasında >%2,5 fark varsa girişi reddetme; küçük farkta varsayılan plan dışı miktar ve stopu fiyatla yeniden ölçekleme. |
| `src/futures_catalog.py` | 33 satır ekleme, 6 silme | Denylist genişlemesi ve Binance kök-varlığı/OKX native allowlist kontrolü. |
| `src/main.py` | 32 satır ekleme | İsteğe bağlı “kazanan çekirdek” filtresi ve paper seansının son dakikalarında yeni girişleri kesme. |
| `src/trade_quality.py` | 77 satır ekleme | Çekirdek teknik + taker/CVD uyum filtresinin fonksiyonu. |
| `src/release_bundle.py` | **142 satır yeni** | ZIP, Git patch’i, tek dosyalık kurucu ve kod kitabı üretmeye çalışır; varsa kalıcı hafıza DB’sini ZIP’e ekler. |
| Diğer **34** ortak kaynak bölümü | **Aynı metin** | Ana strateji ve temel risk yapılandırmasında geniş bir revizyon yok. |

## 4. v7.8’deki beş işlevsel değişiklik

### 4.1 Borsalar arası ticker uyuşmazlığı — yararlı ama mutlak güvenlik değil

`src/exchanges.py:725–776` yeni `best_price()` içinde birincil borsanın fiyatını referans alıyor. İkinci venue fiyatı **%1,5’ten fazla** farklıysa o fiyatı geçersiz sayıyor ve sembolün venue destek listesinden çıkarmaya çalışıyor; aksi halde LONG/BUY için düşük, SHORT/SELL için yüksek fiyatı seçiyor. Amaç, aynı ticker’ın farklı varlıkları göstermesi (kod yorumundaki BB/BlackBerry örneği gibi) nedeniyle yanlış kontrata yönelmeyi engellemek.

`src/executor.py:1055–1075` ayrıca seçilen borsa birincil değilken sinyal fiyatı ile icra fiyatı arasındaki fark **%2,5’i aşarsa** girişi reddediyor. Varsayılan işlem planı kapalıyken fark küçükse miktar fiyat oranına göre ayarlanıp stop yeni fiyata göre kuruluyor.

**Sınırlamalar:**
- %1,5 ve %2,5 sabit eşikler tüm coin/volatilite rejimleri için doğrulanmış evrensel eşikler değildir. Meşru fiyat ayrışması/likidite farkı yanlış ret doğurabilir.
- Varlık eşleşmesini fiyat benzerliğinden çıkarmak sadece bir anomali filtresidir; ticker’ın gerçekten aynı dayanağı temsil ettiğini kanıtlamaz.
- `trade_plan_enabled=True` iken yeni fiyat için miktar/stop yeniden hesaplayan blok uygulanmıyor; küçük venue farkı varsa risk planı sinyal fiyatına dayalı kalabilir.
- Bu değişiklik, Binance ve OKX’in hesap bakiyelerini tek havuz gibi kullanma sorununu **çözmez**.

### 4.2 Kontrat evreni — sızıntıyı azaltır, “%100 saf kripto” garantisi vermez

`src/futures_catalog.py` v7.8’de hisse/ETF/emtia/FX/sabit-coin denylist’ini genişletiyor. Ayrıca Binance’te en az 50 kabul edilmiş kontrat varsa, Binance dışındaki venue’larda kalan kök varlığın Binance kripto kök evreninde veya şu sabit listede olmasını şart koşuyor: `OKB, CRO, PI, CORE, FLR, CSPR, XDC, MX, BGB, GT, HTX` (`src/futures_catalog.py:190–249`).

Bu, OKX’te sonradan açılan sentetik hisse/pre-IPO kontratlarının sızmasını **azaltır**; fakat Binance’te olmayan meşru OKX kripto sözleşmelerini de dışlayabilir. Binance evreni boş/küçükse (`<50`) bu ek kök-varlık filtresi devreye girmez. Liste ticker/kök adı temellidir; şirket kökenini doğrulayan yetkili bir ABD-köken listesi değildir. Dolayısıyla “%100 saf kripto” veya “ABD kaynaklıların tamamı kesin dışarıda” iddiası koddan garanti edilemez.

### 4.3 Kazanan çekirdek ve seans-sonu kapısı — bazı profillerde açık, ana ayarda kapalı

`winning_core_guard()` (`src/trade_quality.py:617–693`) çağrılırsa:

- Taker delta ve CVD aynı yönü göstermiyorsa reddeder.
- Squeeze yokken hacim patlaması oluşmuş ve RSI LONG’da ≥67 / SHORT’ta ≤33 ise reddeder.
- Gösterge bileşenleri mevcutsa altı temel sütundan varsayılan en az üçünün yön uyumunu ve OBV/MACD/session VWAP/volume profile gruplarından en az birinin uyumunu ister.

`src/main.py:876–907` bu fonksiyonu `sinyal.kazanan_cekirdek_aktif` true ise çağırıyor. Temel `config.yaml` içinde bu alan yok; bu nedenle **ana varsayılan ayarda kapalı**. Ancak v7.8 gerçek paketindeki `configs/paper-60-v2-control.json` bu alanı açıyor, `min_cekirdek_onay=3` kullanıyor ve `risk.son_dakika_giris_engeli_dk=7` tanımlıyor. Aynı profil fırsat takasını da kapatıyor ve bekleme eşiğini 12 dakikaya çıkarıyor. Bu profil dosyaları kod kitabında bulunmadığı için yalnızca iki ekten okuyan biri bu etkinleştirmeyi göremez.

Seans-sonu koruması yalnız süreli `paper_session` varken ve `son_dakika_giris_engeli_dk > 0` olduğunda yeni girişleri kesiyor; temel YAML’da değer yoksa çalışmıyor. Bu, açık pozisyonları kapatan bir mekanizma değil.

### 4.4 Yeni release üreticisi — sürüm ve veri bütünlüğü sorunları

`src/release_bundle.py:19–142` dört çıktı üretmeyi amaçlıyor: mail ZIP’i, Git patch’i, tek dosyalık kurucu ve kod kitabı. Dosya desenleriyle `config.yaml`, `requirements.txt`, README, `src/*.py`, `configs/*.json`, testler ve `.github/workflows/*.yml` ekleniyor. Bu yüzden ZIP, kod kitabından daha fazla dosya içerebilir.

Önemli risk/uyumsuzluklar:

1. **Varsayılan sürüm yanlış:** `build_release_bundle()` ve CLI `--version` varsayılanı **`v7.7`**. v7.8 repo’sunda `--version v7.8` verilmezse oluşturulan dosyalar v7.7 diye adlandırılıp v7.7 klasör yolu taşıyabilir.
2. **Git bağımlılığı:** En başta `git diff 71ab07b..HEAD` çağrılıyor. Git deposu veya `71ab07b` referansı yoksa üretim hata verir. ZIP’ten çıkarılmış, `.git` içermeyen dağıtım içinde modül tek başına yeniden çalışmayabilir.
3. **Patch ile ZIP farklı içerik olabilir:** Patch yalnız `base_ref..HEAD` commit ağacı farkıdır; çalışma dizinindeki commit edilmemiş değişiklikleri içermez. ZIP/kurucu/kod kitabı ise o anki çalışma dizininden dosya okur. Böylece aynı sürüm paketindeki kaynak ile patch birebir aynı durumu anlatmayabilir. Patch pathspec’i README’yi de içermez; ZIP içerir.
4. **DB’nin dışarı gönderilmesi:** `backups/kriptobot_kalici_hafiza.db` varsa e-posta ZIP’ine otomatik ekleniyor (`:127–129`). Bu DB `sessions`, `trades`, `model_snapshots` tablolarında PnL, sembol, yön, borsa, fiyat, işlem büyüklüğü ve ayar anlık görüntüleri tutabiliyor. Hassas geçmiş, açık onay/temizleme olmadan mail paketine girebilir. ZIP’te şifreleme yok. DB, SQLite/WAL kullanıyorsa ham dosya kopyası SQLite backup/lock yöntemi kullanmadığından, aktif WAL verisinin paket dışında kalması veya tutarsız snapshot riski de değerlendirilmelidir.
5. **Sürüm girdisi doğrulanmıyor:** `--version` için biçim/karakter doğrulaması yok; raw değer çıktı dosya adlarında ve ZIP iç klasöründe kullanılıyor. Güvenilmeyen bir sürüm girdisi dosya yolu/ZIP yolu üretiminde path-traversal riski doğurabilir. Sabit izinli sürüm biçimiyle sınırlandırılmalı.
6. **Üstüne yazma:** Aynı sürümle tekrar çalıştırma `write_bytes`, `write_text` ve ZIP açma modu `w` ile eski çıktıları sessizce değiştirebilir.
7. **Kod kitabı tam proje değil:** `core_src` yalnız `config.yaml`, `requirements.txt` ve `src/*.py` alıyor. README, ayar profilleri, testler ve workflow’lar kod kitabına girmiyor; başlıktaki “tüm açık kaynak kod kitabı” ifadesi kapsamı olduğundan geniş gösteriyor.

### 4.5 Performans iddialarının kanıt seviyesi

v7.7 kapağında “2. deneme +$95.60 / 30 bot kapanışı” ve “28/28 Order-Flow/CVD” gibi ölçümler var; v7.7/v7.8 kaynak yorumlarında da deney sonucu gibi sunulan sayılar bulunuyor. İki ek dosyada bunları doğrulayacak ham işlem listesi, işlem zaman aralığı, fee/funding hesabı, test protokolü veya bağımsız tekrar sonucu yok. Bunları **kod yorumunda/kapakta yer alan, doğrulanmamış iddia** olarak değerlendirmek gerekir; gerçekleşmiş canlı işlem kanıtı sayılmaz.

## 5. İki sürümün ortak çalışması: bot neler yapabilir?

Bu ortak davranış, iki kod kitabında aynı kalan temel modüllerden ve ayrıca daha önce statik çözümlenmiş v7.8 paketinden doğrulandı.

### Modlar ve borsa emirleri

- Varsayılan YAML modu `paper`; sanal başlangıç bakiyesi 100.000 USDT. Paper yürütme gerçek borsaya emir göndermez.
- `MODE` ortam değişkeni YAML modunu ezebilir: `paper`, `testnet` veya `live`. Gerçek modda ilgili Binance/OKX API kimlik bilgileri ve `LIVE_TRADING_CONFIRM=YES_I_RISK_REAL_MONEY` onayı gerekir. Bu onay canlı emir yolunu açar; kullanıcıya gösterilen etkileşimli bir onay penceresi değildir.
- Gerçek/testnet akışında leverage/margin ayarı, limit/maker giriş, koşula göre chase-limit/market tamamlama, market/reduce-only kapanış ve native stop koruması bulunuyor. Kodda para çekme/transfer çağrısı görülmedi.
- Paper modunda tüm uygun perpetual kataloğu koşullu olarak keşfedilebilir; live/testnet varsayılan evreni daha sınırlı (BTC/ETH/SOL). Katalog filtresi borsanın sembol metadatasına ve statik listelere dayanıyor.

### Boyutlandırma ve risk

- Ortak varsayılan: cross marj, **50 USDT marj × 10x ≈ 500 USDT nominal**; `marj_zarar_orani=0.80` yaklaşık 40 USDT brüt fiyat zararına karşılık gelen stop hedefi oluşturur. Bu, azami zarar garantisi değildir.
- Normal live/testnet açık pozisyon tavanı 3, hard tavan 6; paper geniş limit profili çok daha yüksek olabilir. Günlük %5 ve haftalık %12 zarar limitleri yeni girişleri durdurur; mevcut pozisyonları otomatik kapatma garantisi vermez.
- Sabit take-profit varsayılan olarak kapalı. Stop/trailing, kâr kilidi, net başabaş, order-flow çıkışı ve koruma emirleri kullanılır. Komisyon, funding, spread, kayma, likidasyon ve ağ kopması hedeflenen stop zararını aşabilir.
- YAML’daki `toplam_marj_tavani_yuzde: 60` ile varsayılan cross akışındaki kod kontrolü uyumlu değil: cross yolunda ayrı `cross_pool_ok` hesabı ve %95’e kadar kullanım ayarı devreye giriyor. Bu, iki sürümde de netleştirilmesi gereken temel risk yapılandırmasıdır.

### Veri, dosya ve bildirim yan etkileri

- Borsa piyasa verisi REST/WebSocket, 1m/5m ve üst-zaman-dilimi mumları, ticker/order-book/flow, funding/open-interest ve türev verisi çekilebilir. CoinDesk/Cointelegraph RSS, opsiyonel CryptoPanic ve opsiyonel dış bildirim uçları da yapılandırmada bulunuyor.
- Bot çalışırsa `bot_state.db` SQLite WAL, Kelly/ayar dosyaları ve seans raporları yazabilir; Telegram komutları, dashboard eylemleri ve bildirimler açık yapılandırmaya göre etkinleşebilir.
- Health/metrics endpoint’leri ağda açılabilir. Telegram grup yetkisi ve health/metrics erişimi ayrıca sınırlandırılmalı.

## 6. İki sürümde de kalan yüksek önem dereceli sorunlar

1. **Ayrı venue hesapları ortak bakiye gibi ele alınıyor:** `fetch_balance_usdt()` ilk kullanılabilir borsanın bakiyesini döndürüyor; `best_price()` ise emri diğer borsaya yönlendirebilir. Cross-risk hesaplaması venue’lar arası pozisyonları topluyor. Binance ve OKX ayrı cüzdan olduğundan kullanılabilir marj yanlış hesaplanabilir. v7.8 ticker uyuşmazlığı filtresi bunu çözmez.
2. **Stop/pozisyon devamlılığı:** Yerel pozisyon restore edilebilirken native stop emir kimliklerinin kalıcı geri yüklenmesi/mutabakatı yeterli değil. Normal SIGINT kapanışında botun tüm canlı pozisyonları otomatik flatten ettiği garanti değil; yazılım stopu süreç kapalıyken çalışmaz.
3. **Emir sonucu belirsizliği:** Borsaya ulaşmış ancak yanıtı timeout olan giriş yerel pozisyon kaydına yansımayabilir; sahipsiz remote pozisyon otomatik benimsenmeyebilir. Timeout sonrası borsa hesabında pozisyon/emir kontrolü gerekir.
4. **İptal ve PnL hesabı:** Koruma emri iptal hatalarının yutulması eski remote stop bırakabilir. Bazı kayıp sınırı sayaçları net PnL yerine brüt fiyat PnL’i kullanabilir; fee/funding sonucu değiştirir.
5. **Uzaktan kontrol ve ağ yüzeyi:** Telegram’da grup chat ID yetkisi varsa tüm grup üyelerinin komut verebilme riski; health/metrics uçlarında auth eksikliği; dış ağda dashboard/port açılması riski.
6. **Sembol sınıflaması:** v7.8 filtresi daha güçlü ama otoritatif varlık-kökeni veri kaynağı değil; “tamamen saf kripto” garantisi vermez.

## 7. Sürüm/evrak tutarsızlıkları

- v7.7 kapağı `v7.7` ve `Commit: 3d19986` der; v7.8 kitapta commit kimliği yok.
- Her iki `config.yaml` başlığı hâlâ **v7.2** diyor. v7.8 paketindeki README ve `src/main.py` docstring’leri de eski v7.2 ibareleri taşıyor; uygulamanın başlangıç mesajı v7.7 olarak kalmış.
- Yeni `src/release_bundle.py` varsayılanı yine **v7.7**. Bu nedenle dosya adı, config başlığı ve çalışan bot etiketi aynı sürümü tutarlı biçimde göstermiyor.
- v7.7 kapağındaki kurulum örneği `python -m src.main` diyor; komutun gerçek modu ise yalnız dosya metninden değil, `MODE`/onay ortamından belirleniyor. “Paper” açıklaması live yolunu ortadan kaldırmıyor.

## 8. Karar ve önerilen sıra

**Hangisi tercih edilmeli?** Kod içeriği bakımından v7.8, v7.7’ye göre sınırlı fakat anlamlı bir ticker/kontrat eşleşme filtresi ve release üreticisi ekliyor; bu nedenle iki dosya arasında güncel temel olarak v7.8 daha tutarlı aday. Ancak **v7.8’i doğrulanmış güvenli/canlı kullanıma hazır sürüm saymak doğru olmaz**; eklenen release script’inde sürüm varsayılanı, Git/working-tree farkı, DB’nin ZIP’e girmesi ve yol girdisi doğrulaması sorunları var.

Canlıya geçmeden önce öncelik sırası:

1. Binance/OKX venue başına bakiye-marj muhasebesi veya tek venue kısıtı.
2. Emir ID/fill mutabakatı; native stopları restart’ta borsadan keşfetme ve cancel hatalarını görünür kılma.
3. Normal kapanış/kill-switch politikasını belirleme ve SIGTERM/yeniden başlatma testlerini açıkça doğrulama.
4. 60%–95% marj limiti çelişkisini çözme; net PnL bazlı günlük/haftalık koruma.
5. Sembol evreni için yetkili varlık/köken listesi ve olumlu/olumsuz testler.
6. Release generator’da sürüm değerini zorunlu/valid kılma, Git ref’i doğrulama, çalışma ağacını patch’e katma, DB için onay/redaksiyon ve SQLite güvenli yedekleme kullanma; çıktıların üzerine yazmayı engelleme.
7. Performans iddiaları için ham paper/live işlem dökümü, maliyet hesabı, test aralığı ve yeniden üretilebilir test raporu ekleme.
8. “Tam kod kitabı” isteniyorsa README, profile JSON’lar, testler ve workflow’ları da ayrı ek veya indeksli ek rapor olarak sunma.

## 9. İlgili kaynaklar

- Önceki ayrıntılı v7.8 statik denetim: `/home/user/KRIPTO_BOT_v7_8_STATIK_DENETIM_RAPORU.md`
- v7.8 kurucudan statik çıkarılan kaynak ağacı: `/home/user/kripto_bot_v7_8_audit_extract/`
- Kod kitabı karşılaştırmasında başlıca dosyalar: `src/exchanges.py`, `src/executor.py`, `src/futures_catalog.py`, `src/main.py`, `src/trade_quality.py`, `src/release_bundle.py`.
