# v11 — Çapraz Kurtarma İncelemesi ve Hata Düzeltmeleri

Tarih: 28 Ekim 2026  
Kapsam: paper / araştırma. Canlı emir gönderimi yoktur. Strateji eşikleri, TP/SL yüzdeleri, pozisyon boyutu, cascade ve timeout varsayılanları değiştirilmemiştir.

## 1. Çapraz kurtarma incelemesi

Kod tabanında `kurtarma`, `recovery`, `rescue`, `hedge`, `cross`, `fallback`, `telafi`, `martingale`, yeniden giriş ve bütün `open_position` çağrıları tarandı.

**Zarardaki pozisyonu başka borsada açmak, ters pozisyonla telafi etmek, zarar sonrası yeniden giriş yapmak veya pozisyon üstüne ekleme yapmak üzerine kurulu bir ticari çapraz-kurtarma mekanizması bulunamadı.** Bu nedenle kapatılacak aktif bir ticaret kurtarma modu veya uydurma bir `CROSS_RECOVERY` anahtarı eklenmedi.

Kapanış yolu artık testle de sabitlenmiştir: izole pozisyon stop/likidasyonla kapandığında yeni veya karşıt pozisyon açılmaz; `bot.acilan` sayısı değişmez.

### Birbirinden ayrılan mekanizmalar

- **Binance REST yedek adres geçişi:** Bağlantı hatasında `fapi`, `fapi1`, `www` adresleri arasında geçiş yapan veri-ağ dayanıklılığıdır; pozisyon kurtarma değildir. Bu sürümde değiştirilmedi.
- **WebSocket yeniden bağlanması:** Veri akışını sürdürür; ticari kurtarma değildir.
- **`engel:cift_borsa`:** Aynı base varlığın OKX ve Binance'te iki kez açılmasını engeller. Bu bir risk azaltma korumasıdır ve korunmuştur.
- **Marj modeli:** Pozisyon bazında izole marj varsayımıdır. Dokümandaki yanlış “çapraz marj” ifadeleri düzeltildi.

Eğer amaç yalnızca ağ yedek adres geçişini de devre dışı bırakmaksa bu ayrı bir davranış değişikliğidir; v11'de kullanıcı bundan farklı bir ticari kurtarma kastı olabileceği için ağ dayanıklılığı kapatılmamıştır.

## 2. Düzeltilen hatalar

### 2.1 İzole modda yanlış SL kullanımı

**Eski davranış:** `--izole` açıkken pozisyon açılışında stop marj-bitiş seviyesine konuyor, fakat `cikis_yonetimi` bundan bağımsız olarak genel `--sl` yüzdesini kullanıyordu. Örneğin izole stop %10 iken pozisyon %2/%3 zararda erken kapanabiliyordu.

**Yeni davranış:** Çıkış yöneticisi her pozisyonun kendi `stop_price` ve `take_profit_price` değerlerini kullanır.

- LONG: fiyat `stop_price` altına/eşitse stop, `take_profit_price` üstüne/eşitse TP.
- SHORT: koşullar yönüne göre ters uygulanır.
- Stop kontrolü TP'den önce yapılır.
- Zaman aşımı yalnızca SL/TP oluşmamışsa değerlendirilir.
- Normal modda açılışta hesaplanan yüzdesel seviyeler korunur; izole modda artık gerçek marj-bitiş seviyesi uygulanır.

### 2.2 Kapanan işlem CSV mutabakatı

**Eski risk:** Pozisyonun kapanması, sayaçların artması ve CSV yazımı ayrı adımlardı. Yazım/kopya sorununda durum dosyası ile CSV farklı sayıda işlem gösterebiliyordu; v9 testinde 42/41 uyuşmazlığı görülmüştü.

**Yeni davranış:**

- Bütün `ws_bot` kapanışları `_kapat_ve_kaydet()` üzerinden geçer.
- `TradeLogger.log_trades()` yazım sonrası `flush + os.fsync` uygular.
- CSV hatası kapanmış pozisyonu geri açmaz; `kayit_hatalari` artırılır ve hata loglanır.
- Oturum sonunda `TradeLogger.log_missing()` portföydeki kapanışları CSV anahtarlarıyla karşılaştırır ve yalnızca eksik kayıtları ekler; mevcut satırları çoğaltmaz.
- Bu yalnızca kayıt mutabakatıdır; ticaret kurtarma/geri alma değildir.

`ws_durum.json` alanları:

- `kapanan_islem`
- `csv_kapanan_islem`
- `kayit_mutabakati`
- `kayit_hatalari`
- `mutabakat_eklenen`

### 2.3 Başlangıçta durum raporu sağlamlığı

Akış nesnesi henüz oluşturulmadan `durum_yaz()` çağrıldığında oluşabilen `_bnc` `AttributeError` hatası giderildi. Akış yoksa sembol sayısı güvenli biçimde 0 kabul edilir.

### 2.4 Marj dokümantasyonu

`docs/VERI_ARASTIRMA_RAPORU.md` ve Crew görev/agent metinlerindeki yanlış `cross-margin` ifadeleri `isolated-margin` olarak düzeltildi.

## 3. Testler

### Birim/regresyon

**191 test geçti.**

Yeni testler:

- İzole LONG pozisyonu, genel %3 SL ayarına rağmen %3 düşüşte kapanmaz.
- Gerçek izole marj-bitiş seviyesinde kapanır ve `LIQUIDATION:stop_loss` olarak kaydedilir.
- Kapanışta yeni/karşıt kurtarma pozisyonu açılmaz.
- Normal modda pozisyonun kendi TP seviyesi çalışır.
- `log_missing` yalnızca eksik kapanışı ekler; ikinci çağrıda çoğaltmaz.
- CSV yazım hatası kapanışı geri almaz; sonraki mutabakat eksik satırı tamamlar.
- Durum JSON'unda CSV/kapanış sayıları ve mutabakat alanı doğrulanır.

### Çalışma-zamanı smoke testi

Ayrı ve temiz çalışma dizininde varsayılan strateji ayarlarıyla 2 dakikalık paper testi:

- Süre: **120 saniye**
- Çıkış kodu: **0**
- Log: `Traceback`, `Exception`, `ERROR` yok
- Sinyal: 10
- Açılan: 6
- Kapanan: 6
- CSV satırı: 6
- `csv_kapanan_islem`: 6
- `kayit_mutabakati`: **true**
- `kayit_hatalari`: 0
- `mutabakat_eklenen`: 0
- Açık pozisyon: 0
- Kapanış nedeni: 6 `session_end`
- Net: **−0,4247 USDT** (funding hariç)

Bu kısa test yalnızca teknik çalışma ve kayıt doğrulamasıdır; performans/kenar kanıtı değildir. 300+ aynı-yapılandırma işlem örneklemi hedefi bu paketle tamamlanmış sayılmaz.

## 4. Değişen başlıca dosyalar

- `ws_bot.py`
- `logger/trade_logger.py`
- `tests/test_v11_duzeltmeler.py`
- `docs/VERI_ARASTIRMA_RAPORU.md`
- `crew/src/binance_okx_paper_futures_bot/config/tasks.yaml`
- `crew/src/binance_okx_paper_futures_bot/config/agents.yaml`

v10'daki gecikme/kayma stresi ve olay bazlı funding muhasebesi korunmuştur; funding verisi bulunmadığında sonuçlar hâlâ `bilinmiyor` olarak etiketlenir.
