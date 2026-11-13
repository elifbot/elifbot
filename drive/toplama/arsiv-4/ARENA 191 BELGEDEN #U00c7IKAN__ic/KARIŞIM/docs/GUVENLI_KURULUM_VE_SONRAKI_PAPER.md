> **Tarihsel belge:** Aşağıdaki ifadeler yazıldıkları aşamanın durumunu anlatır. Güncel kullanım ve funding sınırları için `README.md` ve `docs/OKX_SON_SURUM_KILAVUZ.md` önceliklidir.

# ACAR birleşik aday: güvenli kurulum ve sonraki PAPER hazırlığı

## Durum

Bu paket sıfırdan oluşturulmuş **sanal işlem adayını** ve sonraki aşamada kullanılabilecek OKX public-data worker'ını içerir. Bu çalışma sırasında OKX toplu metadata/ticker verisi okundu, ancak **public-data PAPER çalıştırılmadı**, gerçek emir gönderilmedi, gerçek Salesforce org'u kullanılmadı. Bu aşama canlı/ileri dönük piyasa testi, üretim sürümü, kârlılık kanıtı veya 191 kaynağın özellik/parametre paritesi değildir.

Gereksinim: Python 3.10+, Linux/WSL, Python standart kütüphanesi. Windows yerel Python'da `fcntl` işçi kilidi yoktur. `app.py` eski, ayrı tek-simgeli botu başlatır; birleşik worker değildir. Eski SQLite ve yedeklerinizi koruyun, ZIP içinde yoktur. Birleşik şema **v4**; eski birleşik v1/v2/v3 ve eski `paper.sqlite` otomatik göç edilmez, açılmaz veya silinmez.

## Şimdi: ağsız doğrulama

```bash
python -W error::ResourceWarning -m unittest discover -s tests -q
python -m examples.birlesik_bot_senaryosu
```

Bunlar sentetik veri kullanır; örnek geçici ayrı DB oluşturur. Testler dahil hiçbir işlem gerçek emir değildir. `examples/birlesik_senaryo_ciktisi.json` kayıtlı sentetik örnektir. Örnekte izleme boşluğu vardır; son iki kapanış **belirsiz** etiketlenir ve sonuç geçmiş yürütmenin gerçekliği/başarısı olarak yorumlanmaz.

## Daha sonra: explicit onayla public-data PAPER

Aşağıdaki komutlar **şimdi çalıştırılmamıştır**; kullanıcı PAPER aşamasını özellikle başlattığında kendi güvendiği Linux/WSL ortamında kullanabilir. Bağlantı public OKX GET istekleridir; API anahtarı ve özel emir uçları yoktur. İnternet bağlantısı gerekir; OKX toplu enstrüman/ticker uçları ve BTC için public detay/sayfalı geçmiş kısaca denendi; PAPER worker ileriye dönük PAPER olarak doğrulanmadı.

1. Yeni, boş bir yol seçin; eski DB'yi kullanmayın. `init` var olan bir dosyayı overwrite etmez. Örneğin:

```bash
mkdir -p data
python unified_cli.py init --db ./data/yeni-birlesik-v4.sqlite --cash 1000
cp public_paper_config.example.json ./data/kendi-public-ayarim.json
```

2. Ayarı dikkatle kontrol edin. Örnek `BTC-USDT-SWAP`, `0.01` temel varlık, `2` model kaldıracı, `5` USDT elle seçilmiş asgari notional ve 10 saniyelik hedef periyottur; **bunlar tavsiye veya borsanın gerçek sınırlarının garantisi değildir**. `quantity` base para birimi cinsindendir, OKX lotlarına çevrilir. `min_notional` kullanıcı seçer; OKX'ten otomatik doğrulanmaz. 1–4 eşsiz lineer USDT SWAP ve 5–30 saniye hedeflenebilir; ağ ve istek süresi nedeniyle bu kesin bir izleme aralığı değildir. Açık pozisyon yokken işçi seçili giriş adayları için gerekli public geçmişi yeniden alır; açık pozisyonları izleme önceliklidir; defter doğrulaması işlem geçmişi büyüdükçe daha fazla iş yapar ve uzun süreli performans/7-24 dayanıklılık testi yapılmamıştır; çoklu simge/geç istek aralığı 30 saniyeyi aşabilir. Tek worker/client içi istekler arasında en az 0,15 sn vardır; ayrı makineler/diğer uygulamalar arasında rate-limit koordinasyonu yoktur.
3. Yalnız kesinleşmiş, tutarlı ve bir dakikalık kesintisiz en az 220 mum ve son UTC gün başlangıcından itibaren eksiksiz geçmiş varsa sinyal değerlendirilir. Sayfalama 20 sayfa ile sınırlıdır; eksik/hatalı veri yeni işlemi engeller. Kapanmış son mum belirlenen tazelik sınırının dışındaysa giriş engellenir; geçmişe dönük işlem açılmaz. Her mum kimliği yalnız bir kez işlenir. Enstrüman OKX `instCategory=1` kripto, `ruleType=normal`, `ctMult=1`, USDT teminatlı/linear ve temel varlık kontrat değeri teyit edilmiş kurallarla sınırlıdır; farklı/eksik özellikler reddedilir. Sembol, fiyat tick/lot ve minimum kontrat kuralları doğrulanır.
4. Tek tur veya sürekli worker'dan **yalnız birini** kullanın. İkisi de aynı DB için işletim sistemi lock dosyası kullanır. CLI dışı doğrudan Python çağrıları veya bağımsız eski `app.py` bu işçi kilidini paylaşmaz; çalışırken başka mutasyon yapmayın. İşçi durunca dosya kilidi bırakılır; `.worker.lock` dosyasının varlığı tek başına çalışan süreç demek değildir.

```bash
# Tek tur (sürekli izleme değildir; açık pozisyonu korumaya yetmez):
python public_paper_once.py --db ./data/yeni-birlesik-v4.sqlite --symbol BTC-USDT-SWAP --quantity 0.01 --leverage 2 --min-notional 5 --confirm-public-paper

# Alternatif: kullanıcının denetiminde sürekli döngü; durdurma Ctrl+C
python public_paper_loop.py --db ./data/yeni-birlesik-v4.sqlite --config ./data/kendi-public-ayarim.json --confirm-public-paper
```

Onay bayrağı olmadan iki CLI veri/DB/lock işlemi başlatmadan çıkar. `--confirm-public-paper` unutulursa hiçbir otomatik başlangıç yapılmaz. Bu komutlar *sanal* işlem defterini değiştirebilir; gerçek borsa emri göndermez.
5. Ayrı terminalden ağsız durum sorgulama:

```bash
python unified_cli.py status --db ./data/yeni-birlesik-v4.sqlite --format omni
python unified_cli.py status --db ./data/yeni-birlesik-v4.sqlite --format risk --as-of $(date +%s)
```

CLI Omni görünümü varsayılan olarak son **işlenmiş olay zamanını** esas alır; worker'ın hâlâ çalıştığı anlamına gelmez. Risk görünümü için `--as-of` geçerli zaman olmalıdır. Gateway gerçek yerel duvar saatini kullanır, fakat ayrıca worker canlılık doğrulaması yapmaz (`NOT_OBSERVED`).

## Funding ve kesinti: en önemli sınırlar

- OKX'in yayınladığı sonraki funding oranı **tahmindir, gerçekleşmiş settlement değildir**. Worker otomatik gerçekleşmiş oran/fiyat/sonraki takvim mutabakatı yapmaz. Süre gelirse açık pozisyon/hesap kilitlenir; sahte kapanış veya sıfır funding kaydı üretilmez. Kullanıcı/operatör doğrulanmış settlement verisiyle ayrı yönetim süreci kurmalıdır; şu anda otomatik tam settlement hizmeti yoktur. Bu nedenle worker kesintisiz otonom çalışmaya hazır değildir.
- Açık pozisyon 30 saniyeden (DB `max_age`) uzun izlenmemişse sonradan alınan ilk mark/kitap ya da gecikmiş settlement `MONITORING_GAP` kaydeder; koruma eşiği aradaki dönemde çalışmış mı bilinmez. Pozisyon `execution_uncertain` olur, yeni giriş kilitlenir, belirsiz açık pozisyon varken operatör kilidi kaldıramaz. Yeni kitabın gösterdiği olası sanal çıkış, **belirsiz yürütme** işaretli bir modeldir; geçmişte gerçek fiyattan çıkılmış sayılmaz. Gerçek borsada stop emri oluşturulmamıştır.
- Pozisyonlar kapatılabilse bile eski belirsiz kapanış kayıtları korunur; risk/Omni çıktısı hesap sonucunun güvenilir olmadığını bildirmeye devam eder. Çıkışlardan sonra operatör kayıtları inceler ve ancak bilinçli `unlock` uygular. Kilidi atlamak için kayıt silmeyin, DB düzenlemeyin. İşçi beklenmeyen hata ile durursa kilit yazmayı dener; DB arızasında bu da başarısız olabilir, log'u kontrol edin. Zamanında veri, 7/24 süreklilik ve zararın sınırlanması garanti edilmez.
- İşlem başlangıcındaki enstrüman kuralları ve kaynak özelliklerinin SHA-256 parmak izi pozisyonla saklanır; farklı/missing metadata işçi tarafından kilitlenir. Bu özet bir özgünlük veya borsa uyumu kanıtı değildir. Fiyat/miktar, tahmini defter derinliği ve basit likidasyon modeli gerçek fill/ADL/mark-price veya borsa mutabakatı değildir.

## Salesforce/OmniStudio taslağı

`salesforce/README.md` ve `salesforce/force-app/` Named Credential kullanan GET-only Apex taslağı ve `HttpCalloutMock` içerir. Gateway `127.0.0.1` dışında dinlemez; güçlü yeni bearer sırrı `ACAR_GATEWAY_TOKEN` ortam değişkeninden okunur. Salesforce localhost'a doğrudan erişemez: TLS, ağ kısıtlaması, güvenli reverse proxy, External Credential/principal, org izinleri ve audit ayrı kurulmalıdır. Gateway'i ve kimlik doğrulamasız eski paneli doğrudan internete açmayın. Burada TLS proxy, org deployment, Apex derleme/test, Integration Procedure/FlexCard metadata ve gerçek bağlantı yapılmadı. JSON'daki `DEPLOYMENT_NOT_VERIFIED` gerçek entegrasyon kanıtı değildir. Gerekli güvenlik ve lisans şartlarını Salesforce sandbox'ta doğrulayın.

Güncel adım adım OKX kontrol, yerel panel, izleme önceliği ve manuel funding işlemleri için `OKX_SON_SURUM_KILAVUZ.md` dosyasını kullanın.

OKX/Binance public piyasa listesi, gözlenen Binance 451 yanıtı ve en fazla 4 OKX simgeli izleme-listesi üretimi için `OKX_BINANCE_PUBLIC_VERI_EVRENI.md` belgesine bakın.
