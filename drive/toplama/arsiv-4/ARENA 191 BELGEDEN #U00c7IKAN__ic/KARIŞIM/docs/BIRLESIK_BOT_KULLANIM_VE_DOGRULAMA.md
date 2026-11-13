> **Tarihsel belge:** Aşağıdaki ifadeler yazıldıkları aşamanın durumunu anlatır. Güncel kullanım ve funding sınırları için `README.md` ve `docs/OKX_SON_SURUM_KILAVUZ.md` önceliklidir.

# ACAR birleşik bot — çevrimdışı aday sürüm

## Bu sürüm nedir?

`unified_cli.py`, `acar/unified_bot.py` ve `acar/unified_simulator.py` kullanıcı tarafından verilen zaman damgalı verileri işleyen, **gerçek emir yeteneği olmayan**, ayrı SQLite defterli birleşik simülatördür. Opsiyonel public OKX adaptörü ve worker daha sonra kullanılmak üzere hazırlanmıştır; toplu OKX metadata/ticker bu tur okundu; PAPER worker gerçek veriyle çalıştırılmadı. Önceki `app.py` OKX tek piyasa PAPER uygulaması ayrı kalır; bu yeni çekirdek ona bağlanmamış ve eski `data/paper.sqlite` dosyasına göç ettirilmemiştir. Kullanıcı canlı PAPER istemeden burada yalnız çevrimdışı senaryolar denenmiştir. Bu sürüm tüm 191 dosyadaki özelliklerin eksiksiz paritesi veya üretim onayı değildir.

## Entegre çalışanlar

- BTC, ETH gibi birden çok *kullanıcı tanımlı* simge, tek kasa ve her simgede en fazla tek pozisyon. Aynı yönde kontrollü DCA/piramitleme isteği `add` ile yapılabilir; toplam pozisyonun riskleri yeniden kontrol edilir; otomatik DCA sinyali yoktur.
- Kapanmış, sıralı ve kesintisiz mumlar üzerinden 10 göstergeli araştırma confluence sinyali, isteğe bağlı breakout uyumu. En az 220 mum ve tam UTC gün VWAP gerekir; mum kapanışı gelecekten veya bayatsa giriş yoktur. Bu yaklaşım eski kaynak sürümleriyle birebir gösterge paritesi değildir.
- Tek snapshot ile lot/tick/minimum kontrolü ve kademeli alıcı/satıcı tahmini, **IOC**: görünür miktarın dolduğu, kalanın iptal edildiği varsayılır. Bir simge + snapshot kimliği yalnız bir kez kullanılır; bu kimliği ve veriyi çağıran sağlar, harici borsadan doğrulanmaz.
- Varsayımlar: girişte en fazla 30 bps spread, pozisyon başına 250 ve toplam 500 USDT notional, toplam 4 pozisyon, en fazla 3x model kaldıracı, pozisyon başına tahmini stop risk %0,5, portföy stop riski %2, ücret %0,05/yön, model bakım marjı %0,5. Sayılar örnektir ve yatırım önerisi değildir. Giriş stop riski, açık pozisyonların taze markı ve funding takvimi doğrulanır; spread ve stop değerleri gap kaybına üst sınır koymaz.
- Aynı SQLite transaction'ında sanal fill, ücret, pozisyon, nakit/marj ve olay/bildirim kaydı. İlgili komut ID'si ve içerik hash'iyle tekrar idempotent; aynı kimlik farklı içerikle reddedilir. Kasa+marj = ilk kasa + ücret/funding/realize PnL eşitliği her değişiklikte kontrol edilir. Bu, hileye karşı kriptografik denetim veya borsa mutabakatı değildir.
- Funding zamanı geldiğinde pozisyonun o dönemde açık olduğuna dair basit kontrol ve caller'ın sağladığı kesinleşmiş oran/fiyat üzerinden tek kez marj muhasebesi. Eksik settlement, işlem açma/kapatmayı engeller; takvim caller tarafından güncellenir. Kaynak doğrulanmaz, kısmi değişim zamanına göre bilinmeyen geçmiş pozisyonlar tahmin edilmez.
- `on_book` taze kitap ortasını mark **vekili** olarak kullanır; önce basit izole marj/maintenance eşiği, ardından stop ve hedef kontrol edilir. Gözlenen derinlikle sentetik kısmi/tam çıkış deneyebilir. Koruyucu çıkış kısmi/başarısızsa veya funding gecikmişse girişler kilitlenir; durum ve tazelik uygun olduğunda operatör açıkça `unlock` talep eder.
- Her finansal/lock olayıyla yerel bildirim dizisine kayıt ve `status --format omni` ile yalnız salt okunur, sınırlı alanlı OmniStudio JSON sözleşmesi. Bu, Salesforce'a bağlanılmış veya bir OmniScript/FlexCard deploy edilmiş demek değildir. İsteğe bağlı Telegram gönderim taslağı vardır; gerçek teslim doğrulanmadı. WhatsApp/e-posta/webhook adaptörü yoktur.

## Güvenlik ve doğruluk sınırları

1. **Gerçek borsa likidasyonu değildir.** Sabit maintenance oranlı, izole-teminat varsayımlı, sürekli olmayan bir eşik modelidir. Kontrat çarpanı, katmanlı bakım marjı, cross margin, likidasyon ücretleri, sigorta fonu, ADL ve gerçek mark/index fiyatı yoktur. BBO ortası özellikle ani hareketlerde kötü vekildir. Eşik izole teminat varsaysa da model, gerçekleşen zarar teminatı aşarsa farkı ortak nakde yansıtır; borsanın gerçek izole zarar sınırı/sigorta mekanizması olarak yorumlanmamalıdır. Eksik likidite gerçekçi garantili dolum olarak gösterilmez.
2. Offline çalışma biçiminde her `book`, lot/tick, fonlama ve zaman bilgisi kullanıcı girdisidir; opsiyonel public adaptör gerçek veride henüz doğrulanmadı. Hesaplar fiyat manipülasyonu/gerçek piyasa uygunluğu doğrulamaz. Kitap ID'si farklı verilirse aynı verinin tekrar kullanımı teknik olarak önlenemez; harici feed kimliği ve doğrulaması gerekir.
3. `on_book` iş akışında mark, koruma, fill, kilit ve olay kaydı **tek transaction**dur. Enjekte edilmiş hata, işlem ortasında ve commit sonrası süreç sonlandırma senaryoları denendi; bunlar uzun süreli crash/restart, tüm dosya sistemi hataları veya tüm yarış senaryolarını kanıtlamaz. Ağ kesintisi/yeterli veri yokluğu borsada stop emri yaratmaz.
4. Funding oranı, takvimi ve fiyatı doğrulanmış bir gerçek settlement kaynağından otomatik alınmaz. Offline funding hesabı ayrı araştırma modellerine göre daha birleşiktir ama bu, gerçek borsa hesap özdeşliği değildir.
5. Bildirimler yerel SQLite olaylarıdır; isteğe bağlı Telegram adaptörü yalnız açık `--send` komutuyla çalışır. Gerçek gönderim test edilmedi. OmniStudio JSON şekli örnektir; gerçek Salesforce org, OAuth, Apex/Integration Procedure/FlexCard kurulumu, yetkilendirme ve bağlantı testi yapılmadı. Modeller/haber kaynakları yoktur.
6. Otomatik retry idempotency **aynı komut kimliği ve aynı içerik** için geçerlidir. Tek `run` dosyasındaki her olay ayrı commit'tir; sonraki olay hata verirse önceki olaylar geri alınmaz. Çıktı dosyası üzerine yazılmaz; yeni adla tekrar denenebilir.
7. Başarıyla geçen çevrimdışı testler, kârlılık, yatırım uygunluğu, 7/24 dayanıklılık veya gerçek emir için güvenlik kanıtı değildir. Açık anahtar eklenmemiştir; geçmiş özel Telegram tokenının sağlayıcıdan iptal/yenilenmesi gerekir.

## Çalıştırma: yalnız sentetik ve çevrimdışı

Python 3.10+; workspace kökünde:

```bash
python -W error::ResourceWarning -m unittest discover -s tests -q
python -m examples.birlesik_bot_senaryosu
python unified_cli.py init --db /tmp/acar-ornek-yeni.sqlite --cash 1000
python unified_cli.py run --db /tmp/acar-ornek-yeni.sqlite --events examples/birlesik_olaylar.jsonl --out /tmp/acar-ornek-sonuclar.jsonl
python unified_cli.py status --db /tmp/acar-ornek-yeni.sqlite --format omni
```

`init` var olan veritabanının üzerine yazmaz; örnek adları önceden mevcutsa yeni ad seçin. `run` çıktı dosyasını yalnız yeni açar. `examples/birlesik_olaylar.jsonl` satırları sırasıyla `candles`, `book`, `funding`, `book`, `unlock` türlerini gösterir; şema dosyanın kendisinde ve `event_execute` fonksiyonundadır. `candles` için 220 mum, `book` için fiyat/miktar kademeleri ve lot kuralları verilir. Kayıtlar artan zamanlı olmalıdır. `add` satırı aynı-yön risk kontrollü ekleme; `exit_config` sonraki snapshotlardan geçerli stop ayarı; `lock`/`unlock` ise açık operatör isteğidir. `status --format omni` bağlantı durumunu açıkça `DEPLOYMENT_NOT_VERIFIED` olarak gösterir.

## Tekrarlanabilir örnek ve kapsam

`examples/birlesik_senaryo_ciktisi.json`: iki sentetik long sinyali, ortak kasa, BTC'de kısmi koruyucu çıkış ve giriş kilidi, ETH funding debit, ETH hedef çıkışı, BTC kalan çıkışı ve açık operatör kilit kaldırma. Aynı varsayımlı örnekte final nakit `1000.945595` olsa da, bu yalnız **elle oluşturulmuş sentetik senaryo sonucudur**, botun piyasa performansı değildir. Tüm pozisyonlar kapanmıştır, ancak uzun izleme boşluğu nedeniyle ETH ve BTC son kapanışları `execution_uncertain=true` ve hesap sonucu güvenilmezdir. Ayrıntılı olaylar dosyadadır.

En güncel test: `python -W error::ResourceWarning -m unittest discover -s tests -q`, **275 test**. Çoklu piyasa ortak kasa, kısmi giriş/çıkış, DCA risk sınırı, idempotency/çakışma, funding, borsa eşiğinin basit modeli, bayat/gelecek veriyi reddetme, eşzamanlı tekrar, defter bozulması, kilit, çıkış tekrarları ve bağımsız CLI senaryoları içerir. Testler sentetik ve ağsızdır. Önceki özellik haritası, eklenmemiş kaynak grupları açısından hâlâ geçerlidir; bu dosya yeni offline birleşik çekirdeğin durumunu günceller.

**Son düzeltme:** Kotasyon/mark tazeliği işleme zamanından değil, verinin beyan edilen gözlem zamanından ölçülür; geriye giden gözlemler reddedilir. Bu, çağıranın zaman bilgisinin gerçekliğini doğrulamaz.


## Sonraki korumalar ve gözlem

- **UTC günlük kayıp:** %2 örnek sınır, tüm açık pozisyonların markları taze ve funding'i belirli olduğunda gözlenen toplam equity üzerinden uygulanır. Gün başlangıcı, UTC 00:00'da garanti edilmiş bir fiyat değil, o gün elde edilen ilk eksiksiz gözlemdir. Eksik veride yeni giriş zaten kapanır; eşik gerçek kaybın üst sınırı değildir.
- **Çıkış ayarı:** `exit_config` örnek `data`: `{"symbol":"BTC","entry_stop_at_r":"1","trailing_distance":"1","now":1704080400}`. Sıfır ilgili seçeneği kapatır. `entry_stop_at_r` mevcut kazanç ilk risk aralığının katına ulaştığında stopu giriş fiyatına taşıyabilir; komisyon/kaymayı karşılamaz, finansal başabaş garantisi değildir. `trailing_distance` fiyat birimi cinsindedir. Önce eski stop kontrol edilir, değişen stop yalnız sonraki snapshotta etkin olur; stop gevşetilmez. DCA sonrasında başlangıç R ilk girişin mesafesidir.
- **Opsiyonel korelasyon kapısı:** `candles.data.correlation_histories` içinde, her açık simge için aynı zamanlı kapalı `Bar` nesneleri sağlanırsa son 30 bir dakikalık getirinin Pearson korelasyonu ve pozisyon yönü değerlendirilir; `0.85` üzeri aynı yönlü maruziyet engellenir. Geçmiş eksik, sabit, yanlış hizalı veya bayatsa fail-closed. Geçmiş verilmezse bu koruma uygulanmaz (`NOT_REQUESTED`); piyasa korelasyonu değişebilir, bu bir garanti değildir. Kontrol sonrası portföy değişirse giriş transaction'da reddedilir.
- **İzlenebilirlik:** İşlem olmayan sinyal olayları da kalıcı saat/komut kimliği alır; daha eski olaylar reddedilir. Sinyal girdisinin SHA-256'sı kaydedilir; bu gerçek veri doğrulaması değildir.
- `status --format risk --as-of <epoch_saniye>` ayrıntılı stop-senaryosu riski ve bakım teminatı tahminini gösterir; mark/funding eksikse equity alanını boş bırakır. Bunlar gerçek borsa marj kuralları değildir.
- Birleşik defter şeması **v4**; önceki birleşik aday **v1/v2/v3 otomatik açılmaz veya göç edilmez**. Önceki kayıtları silmeyin; yeni örnek için farklı DB oluşturun. İlk tek-piyasa `paper.sqlite` bu çekirdek ile de uyumlu değildir.

## Telegram: isteğe bağlı ve gerçek test edilmemiş

Bu tur hiçbir dış mesaj gönderilmedi. Eski arşivde açığa çıkan tokenı kullanmayın; sağlayıcıdan iptal/yenileme önerilir. Yerel olay numarasının durumuna bakmak ağ kullanmaz:

```bash
python unified_cli.py telegram --db /tmp/yeni-birlesik.sqlite --seq 1
```

Gerçek gönderim istenirse, kullanıcı kendi güvenilir ortamında yeni Telegram bot tokenını `ACAR_TELEGRAM_TOKEN`, alıcı kimliğini `ACAR_TELEGRAM_CHAT_ID` ortam değişkenine güvenli şekilde yerleştirip **açıkça** şu komutu kullanabilir:

```bash
python unified_cli.py telegram --db /tmp/yeni-birlesik.sqlite --seq 1 --send --attempt attempt-1
```

Kimlik bilgilerini komut argümanına, dosyaya veya destek mesajına yazmayın. İstekler yalnız sabit Telegram HTTPS adresine yapılır, token/yanıt hata metinlerinde yazdırılmaz ve yerel deftere kaydedilmez. Başarı sağlayıcının `ok=true` yanıtıdır, mesajın okunması değildir. Ağ hatası veya süreç kesintisiyle sonuç `UNCERTAIN`/`IN_FLIGHT` ise **otomatik yeniden gönderim yoktur**. Operatör dışarıdan gerçekten doğruladıysa `telegram-resolve --decision CONFIRMED_SENT`; aksi halde bilinçli olarak `--decision RETRY_APPROVED` kullanabilir. Tekrar onayı çift mesaj riski taşır. Testler fake transport kullanmıştır; gerçek Telegram teslimi, Salesforce bağlantısı ve harici servis güvenilirliği doğrulanmamıştır.

## Bu tur public ve izleme hazırlığı

`okx_public_adapter`, açık bayraklı tek tur/sürekli worker ve loopback bearer status gateway eklendi; OKX public detay uçları BTC için kısaca okundu, PAPER worker başlatılmadı. Funding tahmini settlement değildir; belirsiz funding otomatik uydurulmaz. Uzun izleme boşluğu giriş kilidi ve kalıcı belirsizlik etiketi doğurur; kapandıktan sonra bile geçmiş belirsizlik raporlanır. Kapsam, kontrat çarpanı, eksiksiz geçmiş, worker sınırları ve henüz kurulmamış Salesforce için `GUVENLI_KURULUM_VE_SONRAKI_PAPER.md` belgesini okuyun.

## Güncel OKX teslimi

Varsayılan tarama yalnız OKX, pozisyon izleme önceliği, 180 saniye önleyici funding çıkışı, yerel salt-okunur panel ve açık onaylı manuel settlement/operatör işlemleri için `OKX_SON_SURUM_KILAVUZ.md` belgesine bakın. Binance işleme bağlanmadı; PAPER aşaması henüz başlatılmadı.
