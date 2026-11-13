# v9.4.4 — Phase 1 doğruluk ve telemetri yaması

Rapor UTC: 2026-11-03T10:32:37.766032+00:00

**Kapsam: raporlama/statü doğruluğu ve kontrollü HTTP testi. İşlem kuralları değiştirilmedi. Gerçek para/operasyonel hazırlık/kârlılık onayı yok.**

## 1. Uygulanan düzeltmeler

### Erken durdurma etiketleri

- Pozitif süre hedefinden önce SIGTERM/SIGINT/stop gelirse **INTERRUPTED**, başarı metni yerine **CANLI_TEST_KESILDI** yazılır. Aktif pencerenin tamamlanmadığı ayrı loglanır.
- Süresiz koşu stop ile biterse INTERRUPTED; drenaj sırasında stop gelirse INTERRUPTED. Önce aktif pencerenin hedefe ulaşıp ulaşmadığı kaydedilir.
- Süre ve drenaj protokolü doğal şekilde biterse COMPLETED. Drenaj sınırında açık pozisyon kalırsa neden `drain_limit_with_open_positions` olarak görünür; zorla kapanış eklenmedi.
- Görev iptali INTERRUPTED, ana süre döngüsündeki foreground istisna FAILED; istisnalar yutulmaz. Testi bitirdikten sonra yalnız açık panelin kapatılması COMPLETED sonucunu bozmaz.
- API `run_completion` alanı; panel KESİLDİ/HATA/ISINIYOR etiketleri eklendi. COMPLETED yalnız süre protokolüdür, tam emir yaşam döngüsü kabulü değildir.
- Mevcut döngü, sleep aralıkları, yeni girişin kapatıldığı nokta ve doğal drenaj koşulları korundu. Saat kaynağı hâlâ time.time; duvar saati/sandbox duraklaması sorunu bu yamayla çözülmüş sayılmaz.
### Sayaç ayrımı — yalnız okunur

- `evaluation_telemetry`: toplam çağrı; giriş tekrarı; pozisyon tekrarı; toplam tekrar; tekrar dışı çağrı; tutarlılık bayrağı ve tekrar dışı nedenler.
- 4.972 / 4.596 / 376 örneği test fixtureında yeniden kuruldu. Bunlar yeni piyasa koşusunda üretilmiş sayılar değildir. 376, benzersiz veya bağımsız sinyal anlamına gelmez; `unique_signal_count=null` kalır.
- `ONE_ATTEMPT_PER_CLOSED_BAR` ve `POSITION_WAIT_NEXT_CLOSED_BAR` ekonomik gate reddi gibi etiketlenmez. Eski ham `v94.entry_rejections` alanı uyumluluk için tutulur ve tekrarları içerdiği işaretlenir.
- Panel ve kapanış logu iki metriği açık ayırır. Karar veren engine/router değiştirilmedi; sayaçlar geriye dönük okunur.
### Testte bulunan ek raporlama 500 hatası

- Seed edilmiş pozisyon var, fakat ilk fiyat tick’i yokken Executor.last_venue_prices henüz oluşturulmamış olabiliyor. build_state_payload bu alana doğrudan erişince /health **500** verdi.
- Yalnız bu raporlama fallback’i `getattr(..., {})` ile güvenli okundu. Fiyatı değerlendiren/yürüten Executor değiştirilmedi. İlk hata `host_http_probe.log` içinde korundu; bu aynı zamanda fiyat tick’i öncesi raporlama yolunun regresyon testine eklenmesini sağladı.

## 2. Test sonuçları

| Test | Sonuç |
|---|---|
| Yeni statü testleri eski kodda (red) | 5 başarısız / 3 geçti |
| Nihai host tam regresyonu | **140 geçti / 14,46s** |
| İlk Docker tam regresyonu | 139 geçti / 1 AST-serileştirme testi başarısız |
| Temiz --no-cache Docker yeniden build + tam regresyon | **140 geçti / 14,49s** |
| Docker pip check | **No broken requirements found** |
| Docker imajı içindeki bütünlük kontrolü | **97 kaynak / 191 imaj-anı paket dosyası geçti** |
| Bağımsız kontrollü HTTP probe (host ve Docker) | **33 /health + 4 /api/state isteği, beklentiler geçti** |
| Docker kendi HEALTHCHECK komutu | **healthy, ExitCode=0 — sentetik fixture** |

140 test = önceki 121 + 19 yeni: 10 statü/temizlik senaryosu, 6 telemetri/panel kontrolü, 1 dört-tablolu HTTP senaryosu, 2 değişmezlik kontrolü. Host ve Docker sayıları birbirine eklenmez. İki eski testte yalnız sürüm beklentisi 9.4.3→9.4.4 güncellendi; güvenlik assertleri kaldırılmadı.
- Statü testleri gerçek run() metodunu, kontrol edilen saat ve dummy IO ile çalıştırır. SIGTERM/SIGINT testleri gerçek OS sinyallerini gerçek async_main sinyal kayıt yoluna gönderir; süreler hızlandırılmıştır. Bunlar gerçek 24 saat veya doğal piyasa koşusu değildir.
- İlk yeni panel testinde yanlış sabit adı (`HTML`) nedeniyle import hatası da oldu; gerçek sabit `DASHBOARD_HTML` olarak düzeltildi. `new_tests_initial.txt` çıktısı korundu.
- İlk Docker AST testi Python 3.13 host / 3.12 konteyner ast.dump serileştirmesine bağlıydı. Kanonik AST JSON hashine geçildi; bu düzeltmede runtime değişmedi. İlk 139/1 çıktı korundu; final kaynak donması r2 bu test düzeltmesinden sonra, son Docker testinden önce yapıldı.
- Haricî Docker HEALTHCHECK fixture ilk çağrıda /evidence konumundan src import edemedi. Test başlatma komutuna PYTHONPATH=/app eklendi; imaj runtime kaynakları değişmedi. İlk hata logu korundu.
- Docker ağ modu host; varsayılan bridge ve compose ağı denenmedi. Doğrudan bağımlılıklar önceki pinlerde korundu, otomatik “en güncel” sürüme geçilmedi. Çözülen transitif sürümler pip freeze çıktısındadır; tam taşınabilir lock veya %99,9 uptime iddiası yoktur.

## 3. Kontrollü PENDING HTTP kapsamı

- /health cevapları: `{"200": 17, "503": 16}`. Buradaki 503ler **bilerek enjekte edilen hata senaryolarının beklenen sonuçlarıdır**; doğal piyasa testinin hata oranı değildir.
- Dört tablo: paper_intents, paper_close_intents, paper_funding_intents, paper_layer_intents. Her birinde genç/sahipli niyet için HTTP200 + IN_FLIGHT + ledger_reconciled=false ve aynı operation_id gözlendi.
- Süre aşımı (token yaşı 16s), sahipsiz kayıt ve 1 USDT hesap bozukluğu için 503; bozukluğun sağlık toleransıyla gizlenmediği doğrulandı. Önceki 15s sınır testleri de tam regresyonda kaldı.
- Her sağlık sorgusu öncesi/sonrası kalıcı SQLite dumpı aynıydı. Sıkı recovery genç PENDINGde de ok=false kalır. Açılış niyetinin açıkça çağrılan dolmadan iptal yöntemi sonrasında RECONCILED/200 dönüşü ayrıca kontrol edildi.
- OKX trade-tape bayatlığı ve toparlanması da sentetik timestamp enjeksiyonuyla sınandı. Bu, eski canlı 503ün kök nedenini kanıtlamaz.
- Tüm seed pozisyonlar, hesaplar, fiyat/feed zamanları ve token yaşları **yalnız ayrı test defterlerinde sentetik**. Hiçbir doğal canlı PENDING, giriş dolumu veya tam kapanış kanıtı üretilmedi.

## 4. Değişmezlik kanıtı

- Önceki 90 dosyalık baseline’ın **85/90** dosyası byte-byte aynı. Değişenler: live_runner.py, config sürüm alanı, pyproject sürüm/description ve iki testte sürüm beklentisi.
- Canonical config version dışında JSON olarak aynı. UnifiedTradingEngine, V94LiveRouter, StateStore, strateji/indikatör/gate, AdaptivePolicy, risk, Executor, maker/kayma, portfolio ve backtest kaynakları aynı.
- Runner sınıfında yalnız run ve build_state_payload yöntemlerinin ASTsi değişti. Diğer yöntemler kanonik AST hashleriyle aynı; panel HTML/JS yalnız görünüm değişikliğidir.
- Yeni bağımsız salt-okunur telemetri modülü ve test/denetim araçları eklendi. Son test kaynak donması **97 dosya**; son ZIP ayrıca kendi manifestiyle kontrol edilir.
- Test edilen Docker imajı: `sha256:2a6ab2c2e700db6cdc225fb32e54c3468e3a2c8afb76415aadd0434b17c633a3`. İmaj test öncesi doküman anını içerir; test sonucu belgeleri sonradan ZIPe eklenmiştir. Kaynak97 hashleri aynıdır.

## 5. Bilerek uygulanmayan araştırma değişiklikleri

- 70 puanlı weighted scoring, 1.5×ATR stop/kademeli TP, intrabar tetikleme, gate gevşetme, parite bazlı risk/kalibrasyon ve basket davranışı değişiklikleri **YAPILMADI**.
- Gelecek araştırmada giriş ve çıkış adayları ayrı, maliyet/stres ve veri bölünmesi önceden kayıtlı değerlendirilmelidir. Önceki açılmış veri bağımsız doğrulama sayılmaz. Sharpe>1.8 ve DD<%12 tek başına gerçek para onayı değildir.
- 24 saatlik eski koşu kullanıcı isteğiyle kesilmiş durumdadır; yeniden başlatılmadı. Bu sürümde doğal 10dk/24s PAPER koşusu başlatılmadı. 35 saniyelik Docker fixture yalnız HTTP/HEALTHCHECK tesisat testidir, piyasa verileri simüledir ve sunucu kapanmıştır.

## 6. Kalan sınırlar

- Sandbox kesintisizliği/duvar saati boşlukları çözülmedi; doğal uzun ömürlü yürütme, gerçek exchange dolumu ve uçtan uca giriş–çıkış hâlâ doğrulanmadı.
- Ayrı-thread token görünürlüğü yarışı ve büyük gerçek defterde tam API/CPU/RAM yük testi yapılmadı. Önceki izole kopya benchmarkı genel performans onayı değildir.
- Foreground hata etiketleri düzeltildi; tüm background görevleri için yeni bir supervisor veya warmup/setup hata yönetimi eklenmedi.
- Sayaçlar örneklem/kârlılık kanıtı değildir. Daha fazla işlem açmak başarı ölçütü yapılmadı.

**Karar: Phase 1, belirtilen birim/kontrollü HTTP/Docker kontratları kapsamında geçti. Doğal canlı yürütme ve gerçek para kabulü YOK.**
