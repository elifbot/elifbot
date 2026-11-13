# Kripto Bot v9.4.1 — PAPER araştırma adayı

**Gerçek para onayı yoktur. Araştırma kabul ölçütleri BAŞARISIZ: aday performans yükseltmesi olarak terfi ettirilmedi.**

Tamamlanan baz tarihsel sonuç −354.98 USDT; ücret/kayma sıfır teşhisi bile −86.25 USDT.
15 dakikalık paper penceresi tamamlandı ama hiç dolum olmadı. Binance BBO verisi gelirken
aggTrade ticki 0, bağlantı hatası 133; genel `healthy=true` bu ayrımı yakalamadı.
Bu nedenle tam çift-venue trade-tape / emir-yürütme doğrulaması da geçilmiş sayılmaz.
Sorunlar donmuş dosyaları değiştirerek örtülmedi; bir sonraki ayrı sürümde onarım ve yeniden test gerekir.
Nihai rapor: `reports/v941_nihai_detayli_rapor.md`.

Bu pakette iki ayrı iş vardır: v9.4'te kurulmuş ortak karar/risk altyapısı ve
v9.4.1'de eklenmiş ölçüm/raporlama düzeltmeleri. İyi test/muhasebe altyapısı,
stratejinin pozitif beklentiye sahip olduğu anlamına gelmez. Nihai karar için
`reports/v94_historical_validation.json` ve nihai Türkçe raporu okuyun.

## Çalıştırma

Python 3.10+:

```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python -m pytest -q
python -m scripts.run_v941_paper --duration-sec 900 --max-drain-sec 180 --port 8080 --report-prefix yeni_paper_oturumu
```

Panel `http://localhost:8080`, durum `/api/state`, sağlık `/health`.
Paper testinde gerçek borsa emri gönderilmez. Piyasa verileri için internet gerekir.
Aynı rapor önekini kullanmak önceki oturum defterini sıfırlar; yeni testte yeni önek seçin.
Kapanış beklemesi yaklaşık 180 saniyedir; olay döngüsü nedeniyle birkaç saniye aşılabilir.
Kalan açık pozisyonlar kapanmış kâr gibi sayılmaz. Süre sonundaki açık risk, gerçek
para oturumunda korumasız bırakılacak bir durum gibi yorumlanmamalıdır; bu bir paper kayıt testidir.

`python -m src.live_runner` aynı donmuş işlem çekirdeğini çalıştırır, ancak yeni yönlü
cohort ölçümü için yukarıdaki `scripts.run_v941_paper` sarmalayıcısı kullanılmalıdır.

## Korunan sınırlar ve v9.4 değişiklikleri

- Sabit $50 marj ve 10x; $1,000 kasa. Dinamik kaldıraç, kazanana ekleme ve fırsat takası kapalı.
- %8 fiyat / yaklaşık -$40 brüt acil tavan korunur; günlük işlem yönetimi daha yakın ATR taktik stopla başlar.
- Taktik stop 1.8 ATR, min %0.35, max %1.20. Aday seçimiyle dondurulan ayarlar tek üretim
  konfigürasyonundadır: `configs/v9-canonical-production.json`.
- 1.5R sonrasında 2 ATR takip; küçük her fiyat fitilinin %65–80'ini kilitleyen dolar eşiği yerine oynaklık ölçeği.
- Açık stop-bazlı risk toplamı özsermayenin %2, tek yönde %1.5 sınırı. Gap ve likidite riski bu sınırı aşabilir.
- Aynı kapalı-mum karar çekirdeği canlı ve replay tarafından kullanılır. Gerçek maker/tick dolumları aynı olmak zorunda değildir.
- Kapanmış mum ticker ile değiştirilmez; live mark ayrı taşınır. Yalnız eksiksiz kapanmış HTF kovaları kullanılır.
- Binance quote-taker hacmi gerçek veri olarak tutulur. OKX nötr taker vekili gerçek sayılmaz; veri eksikse giriş reddedilir.
- Spot+perpAnchor fiyatları v9.4 futures yürütme BBO'su olarak kullanılmaz; gerçek futures WS/REST gerekir.
- Backtest tek $1,000 cüzdan ve ortak zaman çizgisidir. t kapanışı kararı t+1 açılışında işlenir;
  giriş barı stopu atlanmaz. Sonradan oluşan intrabar çıkış geliri önceki açılışta harcanmaz.
- Önceki stop önce test edilir; yeni MFE ile aynı mumda geriye dönük stop yaratılmaz.

## v9.4.1: yalnız ölçüm/raporlama düzeltmesi

v9.4.0 kesintili koşusu başarılı test sayılmadı. Arşivi `reports/v94_0_interrupted/` altında.
`reports/v94_freeze_manifest.json` içindeki `source_equality_proof`, 13 strateji/risk/çıkış/
yönlendirme/replay dosyasının v9.4.0 donma kaydıyla byte-byte aynı SHA-256'ya sahip olduğunu gösterir.
Sürüm metadatası 9.4.1'dir; API'de işlem kodu temeli 9.4.0 olarak ayrıca belirtilir.

Ölçüm sarmalayıcısı orijinal kararın dönüş nesnesini değiştirmez. Ayrı gözlemci ve rapor
hesapları çalışır; ek CPU zamanının canlı zamanlamayı hiç etkilemediği iddia edilmez.

Yeni raporlama:

- Ham kapı tekrar sayısı ≠ tekilleştirilmiş cohort ≠ olgunlaşmış 15m gözlem sayısı.
- LONG/SHORT, 5m/15m olgunlaşmış, bekleyen ve gözlem penceresi kaçırılmış sayılar ayrıdır.
- Venue-specific cohort yalnız aynı venue fiyatlarıyla güncellenir. İlk 30s içinde fiyat gelmezse
  çok geç fiyat 15m etiketiyle doldurulmaz.
- Brüt ileri mark getirisi, varsayımsal maliyet senaryosu ve gerçekleşen işlem neti ayrı kavramlardır.
- %0.035/yön komisyon = 7bps round trip. 8bps/yön kaymayla 23bps; spread/funding bunun dışındadır.
  Referans 1.5bps spread eklenirse 24.5bps maliyet senaryosu olur.
- MAE/MFE ve başlangıç taktik / %8 acil bariyer temasları kaydedilir. Gözlenmiş fiyat yolu veya
  OHLC bariyer teması gerçek maker dolumu/dinamik stop işleminin tam simülasyonu değildir.
- Kapı-yön başına en az 50 olgunlaşmış gözlem, 3 sembol, 10 UTC günü yoksa güven aralığı verilmez.
- İki günlük hareketli blok bootstrap, bütün sembolleri UTC gününde birlikte kümeler. Üç kapı × iki
  yön için altı nominal aile karşılaştırması düzeltilir. Pozitif fırsat maliyeti bayrağı için 8bps/yön
  maliyet sonrasında düzeltilmiş alt sınır +1bps üstünde olmalıdır. Bu otomatik kapı kaldırma kararı değildir.

Başarı ölçütleri testten önce `configs/v941_validation_criteria.json` ve donma kaydına yazılmıştır.
15 dakikalık canlı test 10 UTC günü koşulunu karşılayamaz; bu testten güvenli gate etkisi sonucu çıkarılmaz.

## Doğrulama tasarımı ve dürüst sınırlar

Önceki v9.3 1500-bar görüntüsü artık geliştirme verisidir; eski holdout yeniden OOS diye sunulmaz.
Yalnız iki önceden belirlenen ATR takip adayı denendi; ikisi de negatifti. Daha az kaybeden A,
üretime onay değil, test edilecek araştırma adayı olarak seçildi.

Eski veriyle örtüşmeyen 4,800 bar/sembol tarihsel blok mühürlendi; ilk 600 bar ısınma,
son 4,200 bar testtir. Sekiz sembol, ortak saat, tek cüzdan. Bu blok geliştirme tarihinden
ÖNCE olduğundan tam bağımsız prospektif/kronolojik ileri-OOS veya rolling walk-forward değildir.
Başarı ölçütleri v9.3/kullanıcı analizinden etkilenmiştir; bağımsız doğrulayıcı deney iddiası yoktur.

Dondurulmuş koşu:

```bash
python -m scripts.validate_v94
```

Tamamlanmış rapor varsa yeniden çalıştırmayı reddeder; sonucu okuyun. Kesintili aynı donma
kaydı varsa tamamlanmış kollar checkpoint'ten alınabilir. Donmuş kaynak/veri değişirse durur.
Parametreler sonuçlara göre yeniden seçilmez. Yeni deney için yeni veri ve ayrı kayıt gerekir.

Karşılaştırma eski v9.3 kurallarını yeni ortak saat/cüzdanda çalıştırır; eski teslimin birebir
tekrarı değildir. Yeni risk bütçesi ve giriş/çıkış birlikte değiştiğinden fark saf alfa katkısı sayılamaz.

Dört operasyonel ablasyon, 8/15bps-yön kayma, ek-bar gecikmesi ve fee/slippage sıfırlama
teşhis kolu raporlanır. Sıfır fee/kayma kolunda funding ve karar içindeki maliyet başlığı kapısı
kalır. MARKET ablasyonu yeni başka bir filtre eklemez. Upstream trend/flow özellikleri ortak
olduğundan bu kollar tam ortogonal, bağımsız nedensel deneyler değildir.

Funding gerçek tarihsel oranlarla, settlement anındaki 5m açılış-mark yaklaşımıyla uygulanır.
Paper muhasebesinin miras likidasyon varsayımı marjı aşan boşluk kayıplarını sınırlar; gerçek
cross-margin kuyruk kaybı daha büyük olabilir. Sabit sembol seçimi survivorship yanlılığı taşır.

10 bağımsız LLM çalıştırıldığı iddia edilmez. On uzmanlık açısından inceleme raporu vardır;
eski deterministik kural konseyleri v9.4 etkin karar yolunun oylayıcıları değildir.

## Kanıt dosyaları

- `reports/v94_on_uzman_inceleme_ve_kararlar.md`
- `reports/v941_user_tables_verified.json`: altı kapının v9.3 kayıtlarıyla doğrulaması; eski olgunlaşmış n bilinmiyor.
- `reports/v94_development_results.json`
- `reports/v94_freeze_manifest.json`, `v94_sealed_data_metadata.json`, `v94_sealed_historical_holdout.json.gz`
- `reports/v94_historical_validation.json`, `v941_gate_cohort_audit.json`
- `reports/v94_canli_15dk_summary.json`, karar/sağlık günlükleri
- `reports/v94_pytest.txt`
- Nihai Türkçe rapor ve `RELEASE_STATUS.json`

**Negatif beklenti veya önceden belirlenen ölçütlerden başarısızlık varsa gerçek para için terfi yoktur.**
