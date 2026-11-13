# Giriş filtresi / aynı mum kilidi — teşhis testi

## Kısa sonuç

**İlk ret sonrası aynı sembol ve kapanmış mumun yeniden değerlendirilmemesi doğrulandı.** Bu davranış sadece sabit mum koşullarını değil, değişebilen spread, canlı fiyat sapması ve lider veri erişimini de etkiliyor. Ancak bunun kaç gerçek doluma veya kârlı işleme mal olduğu mevcut kayıtlardan hesaplanamaz.

**Operasyonel kod, filtre eşiği, risk, giriş/çıkış veya emir mantığı değiştirilmedi. Yeni canlı/PAPER koşusu başlatılmadı. Gerçek emir yok.** Daha önce teslim edilen v9.4.5 ZIP'i ve dondurulmuş 100 kaynak dosyası aynen korundu.

## 1. Testin kapsamı

- Kullanılan gerçek sınıflar: değiştirilmemiş `V94LiveRouter`, `V94DecisionCore`, `AdaptivePolicy`.
- Girdiler kontrollü/sentetik mum ve Features verileridir. Özellik üretimi testte kontrollü olarak verilir; çekirdek karar kuralları ve router gerçekten çalışır.
- Executor yerine yalnız çağrıları kaydeden stub kullanılır. Emir dolumu veya finansal yaşam döngüsü simüle edilmez. LONG sonucu bir sinyal ve stub'a çağrı demektir; gerçekleşen işlem değildir.
- Referans, aynı yeni girdiyi temiz bir router belleğinde değerlendirir. Bu, tüketilmiş deneme hakkının etkisini ayırır; dağıtıma uygun bir retry yaması veya korumaları kaldırma önerisi değildir.
- Yeni teşhis testleri: **16 geçti / 0.42 saniye**.
- Mevcut sürümün yeniden çalıştırılan regresyonu: **158 geçti / 15.85 saniye**. Ayrı süitlerdir; doğal piyasa kanıtı veya 174 bağımsız işlem diye toplanmaz.
- Mevcut paket denetimi: **SOURCE OK 100 / PACKAGE OK 259**. Bu aşamada Docker yeniden çalıştırılmadı; bu sonuç yeni host çalıştırmasıdır.

## 2. Kontrollü deneyler

| Senaryo | İlk değerlendirme | Aynı mumda ikinci değerlendirme | Temiz bellekli referans / sonuç |
|---|---|---|---|
| Spread iyileşmesi | %0.06 spread → SPREAD_TOO_WIDE | %0.01 spread → ONE_ATTEMPT_PER_CLOSED_BAR | Diğer koşullar uygunken LONG ve kayıt stub'ına çağrı |
| Fiyat sapması düzelmesi | Kapanış 100, ATR 0.25, mark 100.20 → LIVE_ENTRY_DRIFT | Mark 100.00 → tekrar kilidi | Diğer koşullar uygunken LONG ve stub'a çağrı |
| Lider verisinin gelmesi | İki lider yok → LEADERS_UNAVAILABLE_OR_STALE | İki lider gelse de tekrar kilidi | Diğer koşullar uygunken LONG |
| Sabit yetersiz kapanmış-mum akışı | Flow skoru 2 → INSUFFICIENT_REAL_FLOW | Canlı mark değişse de tekrar kilidi | Kilit olmasa bile aynı flow yine reddediliyor |
| Koşullar değişmeden 20 tekrar | Spread uygunsuz | 20 tekrar kilidi | Referansların 20'si de spread nedeniyle reddediyor; yeni uygun aday yok |
| Tazelik sınırı | Kapanıştan tam 180000 ms sonra | İlk değerlendirmeye izin | Diğer koşullar uygunsa stub'a çağrı |
| Tazelik sınırı +1 ms | 180001 ms sonra ilk değerlendirme | STALE_SIGNAL_BAR | Çekirdek karar/emir çağrısı yok |
| İlk değerlendirmeden beri bayat mum | 3 kez sorgu | 3 STALE_SIGNAL_BAR | Deneme hakkı tüketilmiyor; sayaç aynı mumda tekrar artabiliyor |
| Önce reddedilmiş, sonra bayatlamış mum | İlk spread reddi | 180001 ms sonra hâlâ ONE_ATTEMPT | Temiz referans STALE döndürüyor; ret sırası asıl nedeni örtebiliyor |
| Sonraki kapanmış mum | Önceki mum spread reddi | Yeni mumda karar tekrar çalışıyor | Kilit kalıcı değil, sembol–mum bazlı |
| Binance→OKX geçişi | Binance spread reddi | OKX daha uygun girdilerle de tekrar kilidi | Kilit venue değil sembol–mum bazlı |
| Oluşmakta olan mum / eksik mark / drenaj | Erken korumadan ret | Geçerli şartlarla aynı mum tekrar değerlendirilebiliyor | Bu üç erken kontrol deneme hakkını tüketmiyor |
| Emir yoluna gönderim, stub dolum üretmiyor | EXECUTION_GUARD_OR_UNFILLED | Tekrar kilidi | Aynı mumda ikinci emir çağrısı yok; koruyucu davranış da mevcut |
| Aynı timestampte özellik değişikliği enjeksiyonu | Eski özellik cache'e giriyor | Eski cache ve tekrar kilidi korunuyor | Sadece cache davranışı; doğal mum verisi değiştirildiği iddiası değil |

Testler mevcut davranışı bekleyerek yazılmış teşhis testleridir. Geçmeleri **kilit sorunu giderildi** anlamına gelmez.

## 3. Gerçek, tamamlanmış koşuların salt-okunur iz analizi

Aşağıdaki rakamlar `(sembol, karar mumu açılış zamanı)` anahtarına göre gruplandı. Bu anahtarlar bağımsız ekonomik fırsat veya olgun 15 dakikalık örneklem değildir.

| Gözlem | Önceki v9.4.4 | Son v9.4.5 |
|---|---:|---:|
| Toplam karar kaydı | 13886 | 14478 |
| Farklı sembol–mum anahtarı (tüm ret/bekleme/drenaj/pozisyon halleri dahil) | 223 | 228 |
| İlk nedeni spread olan anahtar | 37 | 46 |
| Bunlardan sonrasında aynı mumda giriş tekrar kilidi görülen | 31 | 46 |
| İlk nedeni fiyat sapması olan anahtar | 0 | 1 |
| Bunlardan sonrasında tekrar kilidi görülen | 0 | 1 |
| İlk nedeni yetersiz akış olan anahtar | 29 | 31 |
| Bunlardan sonrasında tekrar kilidi görülen | 23 | 31 |
| Ham STALE_SIGNAL_BAR kayıtları | 227 | 421 |
| STALE görülen farklı sembol–mum anahtarı | 10 | 16 |

**421 bayatlık kaydı, 421 ayrı kaçırılmış sinyal değildir:** son koşuda yalnız 16 farklı sembol–mum anahtarında görülmüştür. Bayatlık kontrolü `seen` güncellemesinden önce olduğu için bu ret aynı mumda tekrar tekrar sayılır.

Son koşuda spread nedeniyle ilk reddedilen 46 anahtarın 11'inde daha sonra best_venue değişimi de görülür. Bu, başka borsaya geçilse bile sembol–mum kilidinin korunduğunu gösteren izlerle uyumludur; yeni borsadaki spreadin gerçekten kabul edilebilir olduğunu kanıtlamaz.

### Gerçek kayıttan belirlenemeyenler

- Karar JSONL dosyaları her değerlendirmedeki mark, spread, karar `now_ms` ve tüm market-context girdilerini saklamıyor. Daha sonraki tekrar kaydında Features da genellikle yok.
- Dolayısıyla 46 grubun kaçında spread düzeldiği, diğer tüm filtrelerin geçtiği, emrin dolacağı veya net kâr oluşacağı bilinmiyor.
- Router ilk ret nedeninde durur. Spread reddedilen bir adayın RSI, trend veya akış şartlarını da sağlayıp sağlamadığı bu kayıttan çıkarılamaz.
- Bayatlık gruplarının kaynağı yalnız bu analizle mum yenileme gecikmesi / başlangıç zamanı / yük ayrımına indirgenemez.

## 4. Önceki açıklamanın düzeltilmesi

Önceki mesajdaki “akış aynı mumda sonradan düzelirse” varsayımı bu mimaride genel olarak doğru değildir. `flow_score`, `last_delta`, `rvol` kapanmış mumdan hesaplanır ve `(sembol, timestamp)` cache'inde tutulur. Canlı mark veya anlık işlem akışı değişmesi bunları güncellemez. Akış filtresi için kör retry aynı retleri tekrar üretir.

Spread ve mark ayrı canlı girdilerdir; lider bağlamı da çerçeveler güncellendiğinde değişebilir. Testte yeniden değerlendirme etkisi bu değişkenlerde gösterildi. Sabit kapanmış-mum tezini canlı verilerle değiştirmek test edilmedi ve yapılmadı.

## 5. Sonuç ve sonraki adımın sınırı

**“Bütün filtreleri biraz gevşetelim” sonucu çıkmadı.** Somut bulgu, *mumun tezini bir kez değerlendirmek* ile *değişken yürütme koşullarına yalnız bir şans vermek* davranışlarının aynı `seen` kilidinde birleştirilmesidir.

Sonraki aday çalışma: mevcut davranışı koruyan bir referansla, yalnız spread/fiyat sapması gibi geçici koşullarda, henüz emir gönderilmemişken, 180 saniyelik tazelik penceresi içinde sınırlı yeniden değerlendirmeyi **önce emir göndermeyen shadow ölçümde** karşılaştırmak. Yeni denemede tüm çekirdek koşullar, mükerrer emir/CAS, PENDING, risk, marj, cooldown ve veri sağlığı korumaları korunmalı; limitler başlamadan kaydedilmelidir.

Bu aday henüz uygulanmadı. RSI, trend, akış, spread eşiği, 3 dakikalık tazelik ve risk parametreleri aynıdır. Kârlılık, yürütme güvenilirliği veya gerçek para onayı yoktur.

## Dosyalar / tekrar çalıştırma

- `test_router_lock.py`: kontrollü 16 teşhis testi.
- `audit_recorded_decisions.py`: mevcut iki doğal koşunun salt-okunur gruplaması.
- `plan.json`: testten önce kaydedilen kapsam ve hashler.
- `SONUC.json`: ayrıntılı gruplama, doğal örnekler, karar dosyası SHA'ları ve değişmezlik kontrolleri.
- `pytest.txt`, `pytest.xml`, `pytest_regression.txt`, `integrity.txt`: gerçek çalıştırma çıktıları.

Aynı çalışma alanında tekrar: `PYTHONPATH=/home/user/kripto-bot-v9.4.5 python -m pytest -v /home/user/filtre-kilit-testi/test_router_lock.py`. Başka makinede yollar uyarlanmalı ve v9.4.5 bağımlılıkları kurulmalıdır. Testler internete veya bir borsaya bağlanmaz.
