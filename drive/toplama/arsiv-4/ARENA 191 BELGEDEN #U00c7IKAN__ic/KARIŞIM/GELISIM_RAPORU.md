> **Tarihsel belge:** Aşağıdaki ifadeler yazıldıkları aşamanın durumunu anlatır. Güncel kullanım ve funding sınırları için `README.md` ve `docs/OKX_SON_SURUM_KILAVUZ.md` önceliklidir.

# ACAR Paper — geliştirme ve ilk araştırma kaydı

## Yapılan geliştirmeler

1. **Sanal defter aritmetiği:** başlangıç nakdi, kapanmış işlemlerin neti ve açık pozisyonun giriş ücreti karşılaştırılıyor. İşlem sayısı, giriş/çıkış, miktar, brüt/net ve ücret alanları denetleniyor. Tutarsızlıkta yeni kayıt işlemi reddediliyor. Bu yalnızca uygulamanın PAPER aritmetiğidir; gerçek borsa veya funding mutabakatı değildir.
2. **Atomik ve eşzamanlı yazma:** eski durumun değişmediği kontrol edilerek SQLite transaction içinde durum, olay, işlem ve mumlar yazılıyor. Eski duruma dayanan eşzamanlı ikinci güncelleme reddediliyor. Kapsam tek yerel SQLite ve bu uygulamanın senaryolarıdır; kapsamlı çok düğümlü recovery iddiası yoktur.
3. **İzleme kesintisinde dürüstlük:** kotasyon/mum kesintisinden sonra belirsiz kalan pozisyonun sanal kapanışı `execution_uncertain` olarak işaretleniyor. Görülen son fiyat, kesinti sırasında stopun nerede çalışacağını ispatlamaz.
4. **Mum arşivi:** OKX kapanmış 1 dakikalık mumlar SQLite'a ekleniyor. İlk geçmiş veriler `warmup`, beklenen sırada gözlenen yeni mumlar `observed`, sonradan tamamlananlar `backfill` etiketi taşır. Onaylanmış mum değişirse sessizce üzerine yazmak yerine kayıt durdurulur. Arşiv sadece tek piyasa OHLCV'dir; geçmiş bid/ask, funding, likidasyon veya emir defteri kayıtları içermez.
5. **Araştırma:** arşiv CSV dışa aktarımı, iki ayrı strateji karşılaştırması ve confluence eşikleri için basit walk-forward. Sonuç JSON'unda girdi SHA-256'sı, ayarlar, işlem/olaylar ve kısıtlar bulunur. Önceki çıktıların üzerine otomatik yazılmaz.
6. **Panel:** defter durumu, arşivdeki mum sayısı, RSI ve ATR; günün başından itibaren kesintisiz veri varsa UTC günlük VWAP gösterilir. Eksik gün verisinden tam günlük VWAP uydurulmaz. Bunlar bilgi amaçlıdır, ayrıca emir onayı vermez.

## Mevcut oturumun güvenlik durumu

Önceki oturumun SQLite yedeği `data/paper-before-upgrade.sqlite` olarak korundu. Uzun kotasyon/mum kesintisi sırasında önceki sanal pozisyonun ara fiyat yolu bilinmiyor. Yeniden bağlantıdaki sanal STOP kapanışı **belirsiz** olarak işaretlendi; yeni giriş kilidi kaldırılmadı. Görünen hesap aritmetiği mutabık olsa da bu, kesinti sırasında gerçekçi bir dolum olduğunu veya getiri sonucunun güvenilir olduğunu göstermez. Bu paket içinde kişisel oturum veritabanı dağıtılmamıştır.

## Örnek: arşivden ilk kısa araştırma

- Kaynak: OKX BTC-USDT-SWAP; 9 Kasım 2026, 14:53–19:52 UTC civarı, 299 kapanmış 1 dakikalık mum. Bunların tamamı ilk yüklenen **warmup** geçmişidir; ileriye dönük gözlem değildir. Tam zaman aralığı CSV ve JSON'da bulunur.
- Verinin SHA-256'sı: `bb4b2b3da8e241f0ce19d9d4b8391b13c5bc51c4db93966beaac85a8658caefc`.
- Bağımsız confluence araştırma simülasyonu: **12 kapanmış işlem, -6,29 USDT net**, maksimum gözlenen equity düşüşü yaklaşık %0,65. Bağımsız breakout: 7 işlem, -2,61 USDT net. Her ikisi aynı veride örneklem içi karşılaştırmadır.
- Walk-forward: 200 eğitim / 60 test mumu, **tek test penceresi ve 0 test işlemi**. Bu gözlem, seçilen eşik veya bot için başarı kanıtı değildir.
- OHLC araştırma motoru sonraki mum açılışında dolum ve sabit spread/kayma varsayar. Canlı PAPER motoru iki strateji uyumu ve güncel bid/ask/funding kapıları kullanır; **birebir aynı motor değildir.** Funding maliyeti, likidasyon ve kısmi dolum araştırma sonucuna dahil değildir. İncelenen süre ve işlem sayısı çok azdır; sonuçlar gelecekteki performansı öngörmez.

Dosyalar: `reports/okx-btc-kapanmis-mumlar.csv`, `reports/arastirma-ilk-kosu.json`. CSV'nin `origin` ve `captured_at` alanları veri kökenini gösterir.

## Kontrol ve çalıştırma

Bu geliştirmeler için **27 çevrimdışı test** geçti. Testler mutabakat bozulması, işlemsel geri alma, yarışan yazıcılar, geçmiş mumların değiştirilmemesi, kesinti uyarısı, funding eksikliği ve walk-forward zaman sınırlarını kapsar. Uzun süreli canlı çalışma, gerçek yürütme veya kârlılık doğrulaması değildir.

```bash
python -m unittest discover -s tests -v
python app.py --port 8000 --db data/paper.sqlite
python export_history.py --db data/paper.sqlite --out reports/yeni-veri.csv
python backtest.py reports/yeni-veri.csv --out reports/yeni-arastirma.json --walk-forward --train-bars 200 --test-bars 60
```

Yeni CSV ve JSON dosya adları mevcut olmamalıdır. Eksik/yinelenen mum varsa araştırma motoru seriyi reddeder. `--walk-forward` veri yetersizse açıkça hata verir.

## Henüz yapılmadı

Çoklu sembol/ortak portföy, gerçekçi kısmi dolum ve sıra modeli, funding muhasebesi, borsa lot/likidasyon kuralları, güvenilir çökme sonrası recovery, çoklu borsa, bağımsız uzun prospektif test, yapay zekâ modelleri ve Salesforce OmniStudio entegrasyonu yok. Hiçbir gerçek emir yolu veya özel API anahtarı eklenmedi. Önceki derin inceleme ve özellik kaynakları `191-parca-derin-analiz-ve-tasarim.zip` dosyasındadır.

---

# Sonraki geliştirme ve 191 kaynak işleme kaydı — 9 Kasım 2026

## Ne işlendi, ne anlama geliyor?

191 kaynağın her biri statik indeksle taranıp `docs/TUM_191_KAYNAK_IZLENEBILIRLIK.md` matrisine girdi: kaynak adı, türü, satır sayısı, konu deseni ve kaynak satır referansı, uygulama/sakınma kararı. Bunun yanında önceki derin incelemedeki 14 sürüm çifti farkları ve kritik bulgular bu pakette ayrı belgelendi. Makine-okunur indeks yalnız satır/metaveri içerir; ham dosyalar, mesaj içerikleri, API anahtarları ve tokenlar paketlenmez. `file_176` içindeki Telegram tokenının aktifliği bilinmiyor: ilgili hizmetten iptal/yenileme önerilir.

**Sınır:** Otomatik konu eşleşmesi semantik inceleme değildir; örnek veya yorumdan eşleşebilir. Her kaynak için kategori kararı verilmiştir, ancak 191 dosyanın her birindeki tüm özelliklerin eksiksiz taşındığı, satır satır güvenlik denetiminden geçtiği veya 193 eski testin çalıştırıldığı iddia edilmez. Bazı modül ve kritik satırlar ayrıca incelendi; `docs/KRITIK_BULGULAR.md` ayrıntıları verir. Hiçbir eski canlı emir uygulaması çalıştırılmadı.

## Bu tur yapılanlar

1. **10 gösterge:** EMA hizası, MACD kesişimi, RSI, ADX/EMA, stokastik, OBV, CCI, Supertrend, UTC günlük VWAP ve Bollinger oyları ile araştırma skoru. Tam UTC gününün açılışından süreklilik, 220 mum ve geçerli OHLCV gerekir; aksi halde sonuç üretilmez. Eski sürümlerle algoritma/parametre paritesi doğrulanmadı. Bu strateji sadece çevrimdışı araştırmadadır; üretimdeki PAPER stratejisi değiştirilmedi. Mevcut yaklaşık beş saatlik CSV gün başını kapsamadığından, bu örnekte adayın çoğu zamana ait sinyal üretmemesi beklenir.
2. **Portföy risk hesabı:** taraf, varlık, adet, stop ve mark verisinin doğrulanması; işlem/varlık/adet/toplam ve yönsel maruziyet limitleri ve maliyet dahil stop-senaryosu tahmini. Tek BTC PAPER girişinde aday kapısı olarak kullanılır; çoklu piyasa yürütme ve korelasyon/ortak portföy altyapısı tamamlanmadı. Stop aralığı olası kaybın garantisi değildir; kesinti, gap ve yetersiz likidite önemli açık risklerdir.
3. **Funding araştırması:** kesinleşmiş settlement, mark/funding değerleri, pozisyon yönü ve zamanına dayalı, işlem kimliği/olay tekrarında idempotent bağımsız hesap; çatışma ve eksik veride hata. Canlı motora veya SQLite'a yazmaz, geçmiş funding ödemesiyle doğrulanmadı.
4. **Araştırma modu ayrımı:** `--walk-forward` yalnız önceki Confluence 2/3/4 eşikleri içindir. `--strategy confluence10` veya `breakout` ile aynı komutta kullanılmasına izin verilmez. `strategy_comparison` yine yalnız eski Confluence/Breakout karşılaştırmasıdır.
5. **Yazılım doğrulaması:** `python -W error::ResourceWarning -m unittest discover -s tests -q` ile **72 test geçti**. Testler diğerlerinin yanında sayısal ADX/VWAP ve oy örneği, prefix/geleceğe bakmama, UTC gün değişimi, eksik/bozuk mum, portföy yön/toplam/tekrar varlık, funding yinelenme/çakışma ve CLI uyumsuz seçeneklerini içerir. Bunlar üretilmiş verili, ağsız yazılım testleridir; forward PAPER koşusu veya piyasa başarımı değildir. Dashboard JS sözdizimi `node --check -` ile doğrulandı; gerçek tarayıcı görsel testi yapılmadı.

## Durum ve PAPER öncesi kalanlar

- Kullanıcının talimatı gereği bu tur **PAPER koşusu veya canlı API bağlantısı başlatılmadı**; mevcut kilitli sanal defter ve yedeği korunmuştur, teslim ZIP'inde yoktur. Önceki oturumdaki `KACIRILMIS_MUM`, belirsiz kapanış ve defter uyarıları bu değişikliklerle çözülmüş sayılmaz.
- 191 dosyadan henüz taşınmamış yeteneklerin önceliklendirilmesi, semantik inceleme ve karşılaştırmalı testleri; göstergelerin güvenilir bağımsız referans verilerle parite doğrulaması.
- Finansman verisi alma/doğrulama ve deftere atomik, yeniden başlatmada idempotent entegrasyon; fonlamanın eksikliği/çakışması için fail-closed çalışma senaryoları.
- Çoklu borsa/simge için zaman/lot kuralları, pozisyon rekonsiliasyonu, korelasyon/kümelenme riskleri; gerçekçi derinlik, slip, kısmi dolum, likidasyon/marj ve gap modelleri. Bunlar şu an yoktur.
- Bağımsız uzun süreli dayanıklılık/recovery ve veri kaynağı testleri, yeterli çeşitlilikte geçmiş veri ve gerçekçi maliyet varsayımları; kullanıcı onayladığında yeni ve açıkça tanımlanmış ileriye dönük PAPER planı.
- Salesforce OmniStudio ve ayrı YZ modelleri bağlantısı yok; kurulu veya denenmiş gibi gösterilmez. Bu belge, botun PAPER testine veya gerçek paraya hazır olduğuna dair onay değildir.

---

# Son geliştirme: kısmi dolum ve deneysel muhasebe — 9 Kasım 2026

Kullanıcının tüm özellikleri geliştirme talebi üzerine, eski arşivdeki riskli kısmi dolum/iptal yolunu aynen taşımak yerine üç **çevrimdışı araştırma bileşeni** eklendi:

- `acar/depth_research.py`: alış/satışta görünür fiyat kademelerine göre tahmini ağırlıklı fiyat, kısmi miktar, kalan, komisyon ve en iyi fiyata kıyasla fiyat etkisi. Eksik/bayat/gelecekten snapshot, ters defter, bozuk sıralama veya kullanıcı tarafından sağlanan adım/minimum kurallarına aykırılık reddedilir. Bu, gerçek emir defterinden veri çekmez; veri/kural doğruluğu ve sıra, likidite yenilenmesi, piyasa etkisi bilinmez. Her çağrı bağımsızdır; aynı snapshot'ın birden çok çağrıda yeniden kullanılmasının likidite tüketimini modellemediği unutulmamalıdır.
- `acar/order_journal_research.py`: yalnız yeni ayrı bir SQLite dosyasında PENDING/OPEN/PARTIAL/CANCEL_PENDING/CANCELED/FILLED/UNCERTAIN durumları; dolum kimliği tekrarı, çelişki/aşırı dolum reddi, işlem içi atomik güncelleme, son durumdaki kümülatif miktar farkında belirsizlik ve bazı yerel bütünlük kontrolleri. İptal isteği pozisyon veya kalan miktarı otomatik silmez. Nihai uzlaşma sonucu dış kaynaktan çekilmez veya kanıtlanmaz; çağıranın beyan ettiği araştırma girdisidir. Günlük pozisyonları, gerçek borsa ve mevcut PAPER defteri ile bağlı değildir; denetim kriptografik değişmezlik değildir.
- `acar/funding_store_research.py`: yeni ayrı bir SQLite'da kullanıcının verdiği kesinleşmiş settlement olaylarını atomik hesaplayıp tekrarı tek kez işler; olay tekrar çatışması veya aritmetik/basit olay tutarsızlığı yazmayı durdurur. Harici settlement gerçeği doğrulanmaz. Yalnız araştırma parasıdır; mevcut PAPER defterine funding kaydı eklemez.

Her iki SQLite araştırma modülü yeni dosyayı münhasır oluşturur ve var olan dosyanın üzerine yazmaz; mevcut PAPER veritabanını açıp dönüştürmez. Finansal yuvarlama, borsanın sözleşme çarpanı, para birimleri ve fee rebate kuralları birebir modellenmediği için bu modüller üretim mutabakatı değildir. Emir günlüğünde sayısal tutarlar decimal metin; funding araştırmasında önceki float hesabı kullanılır.

**Örnek:** `python -m examples.yerel_arastirma_ornegi`. Tamamen uydurma tek snapshot ve funding olayı kullanır; geçici ayrı veritabanlarını siler. Çıktı `examples/sentetik_arastirma_ciktisi.json` örnek dosyasındadır. Funding örneği emir günlüğünden bağımsızdır. Bu bir PAPER testi değildir.

**Doğrulama:** `python -W error::ResourceWarning -m unittest discover -s tests -q` ile **112 ağsız test geçti**. Önceki 27/72 sayıları ilgili tarihsel sürümlerin kayıtlarıdır. Yeni testler kademeli ve kısmi dolum, fiyat/lot, limit, bayat veri, tekrarlı/çelişkili dolum, iptal yarışları, belirsizlik, yeniden açma, eşzamanlı yinelenme, aritmetik bozulma ve ayrı funding olaylarını kapsar. Üretilmiş veriler ve SQLite yerel testlerdir; borsa entegrasyonu, uzun süreli recovery, ileriye dönük PAPER veya kârlılık testi değildir.

**Kalan kapsam:** `docs/OZELLIK_DURUM_VE_YOL_HARITASI.md` listesinde her özellik grubunun çalışan/eksik durumu ve sıralaması yer alır. Bu geliştirme tüm 191 dosyanın tüm özelliklerini tamamlamış değildir. Özellikle ortak pozisyon defteri, gerçekçi funding/likidasyon ve lot doğrulama, çoklu sembol, veri akışı, model/bildirim/Salesforce bağlantıları eksiktir. Kullanıcı daha sonra isteyene kadar PAPER başlatılmadı. Eski kilitli defter ve yedeği değiştirilmedi ve teslimde bulunmaz.

**Ek maliyet duyarlılığı:** `acar/stress_research.py`, önceden tanımlanan ücret, spread ve kayma senaryolarını aynı OHLC veri setinde başlangıç bakiyesi bağımsız olarak karşılaştırır. İşlemler maliyet filtresi nedeniyle senaryoya göre değişebilir. Bu özellik funding, likidite veya likidasyon modellemez; örneklem içi karşılaştırmadır ve gelecekteki başarıyı göstermez.

---

# Birleşik bot geliştirme ve uçtan uca test kaydı — 9 Kasım 2026

Daha önce birbirinden ayrı duran araştırma parçalarından sonra, yeni bir **ağsız birleşik simülasyon çekirdeği** oluşturuldu. `acar/unified_simulator.py` tek bir SQLite transaction içinde çoklu simge pozisyonları, paylaşılan nakit/izole marj, gerçekleşmiş PnL/ücret/funding, snapshot başına kademeli IOC dolum ve yerel olay/bildirimleri kaydeder. `acar/unified_bot.py` 10 oylu kapalı mum sinyalini, koruyucu stop/hedef/basit likidasyon eşiğini buna bağlar; `unified_cli.py` zamanlı JSONL olaylarını işler. Kontrollü aynı-yön DCA/piramitleme, toplam pozisyonun ve portföyün stop riskini yeniden denetleyen açık komuttur.

Kapsam ve varsayımlar, ayrı eski PAPER uygulamasıyla farklar, örnek JSONL girdi ve komutlar `docs/BIRLESIK_BOT_KULLANIM_VE_DOGRULAMA.md` içindedir. Önceden kullanılan 191 dosyanın tamamındaki tüm yetenekler bu sürüme taşınmış veya bütün eski sürümlerle parite doğrulanmış değildir. Bu nedenle **nihai üretim sürümü** veya her özelliği tamamlanmış sürüm iddia edilmemektedir.

**Bu tur doğrulama:** **148 çevrimdışı test geçti.** Ek olarak sentetik iki piyasalı senaryo hem Python giriş noktası hem de CLI ile çalıştı; ortak pozisyonlar, BTC kısmi stop, ETH funding ve iki çıkış işlendi; son kasa `1000.945595` ve pozisyon sayısı 0. Tamamı uydurma fiyat/likiditeyle deterministik yazılım testi; canlı PAPER, borsa veya kârlılık kanıtı değildir. Bu tarihsel sürümde mark ve koruyucu çıkış ayrı transaction idi; aşağıdaki sonraki geliştirme kaydında tek transactiona taşınmıştır.

**Kalan önemli sınırlamalar:** gerçek borsa kuralları/kademeli marj ve likidasyon, doğrulanmış funding ve book akışı, tam model/haber ve harici bildirim servisleri, gerçek Salesforce OmniStudio entegrasyonu, gerçek borsayla mutabakat ve kaynaklardaki diğer tüm strateji varyantları mevcut değildir. Salesforce için yalnız yerel salt-okunur JSON sözleşmesi vardır; org, yetki ve gerçek ortam testleri yapılmadı. Kullanıcının önceki talimatı gereği canlı PAPER veya özel API çağrısı yapılmadı; eski SQLite ve kilit değiştirilmedi.

Son güvenlik gözden geçirmesinde veri tazeliğinin işlem zamanından değil gerçek *beyan edilen* snapshot gözlem zamanından hesaplanması düzeltildi; geriye tarihli marklar reddedilir. Basitleştirilmiş likidasyon simülasyonunda kayıp tahsisli marjı aşarsa ortak nakde de yansıyabilir; gerçek borsanın izole marj kurallarıyla eşdeğer değildir.


---

# Kesintisiz geliştirme kaydı — 9 Kasım 2026

1. Mark, koruma kararı, kısmi/tam IOC dolum, kilit ve olay aynı SQLite transaction'a alındı. Hata enjeksiyonu ve ayrı süreçte işlem içi `os._exit` geri alma, commit sonrası `os._exit` ardından aynı kimlikte tek-dolum tekrar testleri geçti. Bu, tüm çökme koşullarına veya 7/24 dayanıklılığa ilişkin iddia değildir.
2. İlk eksiksiz UTC günü equity gözlemine bağlı örnek %2 günlük kayıp kilidi, tazelik/funding kontrolleri ve gün sonu sıfırlama; sıradaki kitapta etkin izleyen stop ve ücretleri kapsamayan giriş-fiyat stopu eklendi. Eksik markta gün açılışı uydurulmaz.
3. Stop-senaryosu ve basitleştirilmiş bakım marjı için okunur risk raporu; bozulmuş risk ayarı, hatalı pozisyon ve finansal olay detayına uymayan delta fail-closed denetimi eklendi. Bu kontroller saldırgana dayanıklı bağımsız mutabakat değildir.
4. Kapanmış mum/getiri geçmişi sağlandığında isteğe bağlı yönsel korelasyon risk kapısı ve kontrol sonrası portföy değişikliği denetimi eklendi; varsayılan olarak geçmiş sağlanmazsa koruma etkin değildir. Kaynaklar ve gelecekteki korelasyon doğrulanmaz.
5. Sinyal üretmeyen olaylar bile işlem zamanını ve kimliğini kalıcılaştırır; açılışlarda kaynak içeriği parmak izi korunur. Bu geçmiş verinin güvenilirliğini ispatlamaz.
6. İsteğe bağlı Telegram teslim adaptörü, yalnız yeni ortam değişkenleri ve açık `--send` komutuyla; `IN_FLIGHT`/`UNCERTAIN` durumunda otomatik tekrar yoktur. Uygulama fake transport ile test edildi; **gerçek Telegram çağrısı veya Salesforce entegrasyonu yapılmadı**.
7. Şema v2, önceki birleşik v1'i otomatik göç etmez; mevcut tek-piyasa PAPER defterine dokunulmadı.

**190 çevrimdışı test** geçti. Canlı PAPER koşusu başlatılmadı. Tam özellik paritesi, harici Salesforce/market bağlantıları, gerçek borsa likidasyonu ve uzun vadeli dayanıklılık henüz gösterilmediği için bu bir nihai üretim onayı değildir.


## Son geliştirme — public-data/PAPER hazırlığı ve Salesforce taslağı

- Anahtarsız OKX public GET için kısıtlı adaptör, `ctMult=1` lineer USDT dönüşümü, kapalı mum ve sayfalı eksiksiz UTC geçmiş, kitap/tahmini funding kontrolleri; açık `--confirm-public-paper` gerektiren tek tur ve kontrollü döngü eklendi. Gerçek OKX bağlantısı veya ileriye dönük PAPER **bu turda yapılmadı**. Kullanıcının `min_notional` girişi borsa doğrulaması değildir; tahmini funding gerçekleşmiş settlement değildir ve otomatik settlement yoktur.
- Açık pozisyonda 30 saniyeyi aşan mark/izleme boşluğu defter olayı ve giriş kilidi üretir; yeniden fiyat gelmesi geçmiş yürütmeyi bilinir yapmaz. Kapanışlar `execution_uncertain` olarak kaydedilir, geçmiş belirsizlik sonraki risk ve Omni görünümünde korunur. Enstrüman kaynak özeti ve kuralları değişirse açık pozisyon sessizce işlem görmez.
- Salt-okunur bearer-korumalı gateway yalnız loopback üzerinde; duvar saatiyle tazelik gösterir ve worker canlılığını doğruladığını iddia etmez. Salesforce Named Credential/Apex/HttpCalloutMock kaynak taslağı vardır; org, proxy, deployment, org testi ve gerçek bağlantı yapılmadı.
- Birleşik DB şeması artık v4; v1/v2/v3 otomatik göç edilmez. Eski SQLite/yedeğe dokunulmadı ve dağıtıma eklenmedi.
- `python -W error::ResourceWarning -m unittest discover -s tests -q`: **228 ağsız/yerel test geçti**. Yeni örnek 9 defter olayı ve sıfır pozisyonla sonuçlanır; `1000.945595` sentetik kasa, iki belirsiz kapanış nedeniyle geçerli piyasa performansı veya doğrulanmış equity değildir.
- Bu hâl bütün 191 kaynağın özellik paritesi, tam otomatik settlement, 7/24 operasyon, ileriye dönük test veya üretim onayı değildir. Kapsam ve kullanıcının daha sonraki çalıştırma adımları `docs/GUVENLI_KURULUM_VE_SONRAKI_PAPER.md` içindedir.


## OKX / Binance public veri evreni — 9 Kasım 2026 UTC

- Gerçek OKX public enstrüman/ticker erişimiyle 543 SWAP kaydı incelendi; 15 lineer USDT kapsamı dışı ve 239 kripto dışı/belirsiz enstrüman elenince OKX `instCategory=1` esaslı **289 kripto USDT perpetual** sözleşmesi kaydedildi. 283 ön filtre sonucu bu görüntü anına ait olup sinyal veya sürekli canlılık kanıtı değildir. Bir önceki ara gözlemdeki 528 sayısı kripto dışı ürünleri de içeriyordu.
- Binance Futures exchangeInfo ve ayrı erişim denemesinde ticker HTTP 451; kısıt aşılmadı, Binance gerçek sembol/fiyat adedi bilinmiyor. Toplu parser, izole hata durumları ve detay veri adaptörü sahte transport ile test edildi; Binance veri kaynağını ve Binance PAPER motorunu gerçek ortamda test etmek mümkün olmadı.
- Kayıtlı JSON ve CSV yalnız anlık görüntüdür; `market_universe_cli.py` taze public veri tarar, `market_watchlist_cli.py` en fazla dört OKX simgeli çalışan ayarı üretir, PAPER başlatmaz. 1.400 sentetik Binance kontratıyla kapasite testi 1.400 gerçek kontrat bulunduğu anlamına gelmez. 1000 simgede eşzamanlı mum/sinyal analizi ve Binance PAPER bağlantısı yoktur.
- Son doğrulama **252 ağsız/yerel test**; gerçek OKX toplu veri -> en fazla dört simgeli worker konfigürasyonu testi yapıldı, PAPER/gerçek emir başlatılmadı. Güvenli kullanım ve kısıtlar `docs/OKX_BINANCE_PUBLIC_VERI_EVRENI.md`.

- OKX BTC-USDT-SWAP public enstrüman/derinlik/funding ve 1267 kesintisiz kapalı UTC 1m mumuyla detay veri okuma denendi; ilk kitap denemesinde yanıt öncesi saat kullanımının yanlış gelecek-timestamp reddine yol açtığı görüldü, üretim istemcisinde yanıt sonrası saatle düzeltildi ve yeniden doğrulandı. Gerçek işlem/PAPER yok.


## Önceki Binance erişim belgesi ve son veri testi

`file_64_KURULUM_VE_DEVIR.md` ve `file_78_exchanges.py` public www uyumluluk yolunu tarif ediyor. Yeni doğrudan ölçümde belgelenmiş fapi 451, www public 200 verdi; OKX 289 ve Binance 519 olmak üzere **808 borsa-sözleşmesi** alındı. BTC derinlik/funding/mum ve 1273 kapalı mumlu tek-simge araştırma hesabı okundu. 200, Binance bölgesel/hesap erişim yetkisi veya endpoint garantisi değildir; otomatik fallback, API sırrı, proxy, PAPER ve gerçek emir kullanılmadı. Binance PAPER ve 1000 simgede sürekli hesaplama tamamlanmamıştır. Ayrıntı: `docs/BINANCE_ONCEKI_BELGE_INCELEMESI.md`.

Son ağsız/yerel doğrulama **258 test**.


## OKX teslim adımı — Binance sonraya bırakıldı

- Varsayılan public tarama yalnız OKX; Binance yalnız `--venues both` açık seçimiyle sorgulanır. Eski Binance kaynakları referans amaçlı korunmuştur.
- Sürekli worker tüm açık pozisyonları önce izler; açık pozisyon varken diğer sembollerde geçmiş çekimi yapılmaz. Ayarda olmayan açık pozisyon worker durması ve kilit denemesine yol açar. Bu güvenlik politikası yeni çoklu eşzamanlı girişleri bilinçli olarak sınırlar; zamanında izleme garantisi değildir.
- Public OKX köprüsü funding'e 180 sn kalınca eldeki ilk geçerli book'ta sanal `FUNDING_PREEMPT` kapanışı dener. Kısmi/başarısız çıkış kilitlidir; funding zaten gelmiş veya veri yoksa kesinleşmiş settlement otomatik uydurulmaz.
- Salt okunur birleşik panel, yerel bearer gateway ve `paper_operator.py` ile açık onaylı, operatörce doğrulanmış manuel settlement/unlock eklendi. Operatör aracı worker lock kullanır ve borsa verisini doğrulamaz. UI tarayıcı görsel testi ve Salesforce org deploy yapılmadı.
- **275 ağsız/yerel test** geçti. Gerçek PAPER, gerçek emir, ileriye dönük performans, 7/24 ve borsa paritesi doğrulanmadı; örnek sentetik sonuçlar kazanç kanıtı değildir. Belgeler: `docs/OKX_SON_SURUM_KILAVUZ.md`.
