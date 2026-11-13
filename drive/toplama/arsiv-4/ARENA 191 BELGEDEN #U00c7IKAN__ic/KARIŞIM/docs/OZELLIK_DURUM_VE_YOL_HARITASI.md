# Özellik kapsamı ve kalan iş haritası

**Tarihsel not:** Bu tablo birleşik çevrimdışı çekirdekten önce yazıldı. Çoklu piyasa, DCA ve ortak defterin yeni araştırma kapsamı için `BIRLESIK_BOT_KULLANIM_VE_DOGRULAMA.md` belgesine bakın; harici bağlantı ve üretim eksikleri devam eder.

Bu tablo 191 dosyanın statik sınıflandırmasını ürün kapsamına bağlar; tüm kaynaklar, bütün davranışları ile aktarılmış veya kanıtlanmış değildir. Kaynak düzeyindeki kanıt ve satırlar `TUM_191_KAYNAK_IZLENEBILIRLIK.md`, kritik örnekler `KRITIK_BULGULAR.md` içindedir. Kaynak kodunun çalıştırılmaması kasıtlıdır; özellikle eski gerçek emir yolları yeniden kullanılmamıştır.

| Özellik grubu | Bugün çalışan durum | Eksik / karar |
|---|---|---|
| Kapalı mum, veri kaynağı, üst zaman | OKX BTC tek piyasa public OHLC/BBO/funding; kapalı mum, UTC tam kova ve kesinti kilitleri PAPER motorunda | Birden fazla borsa ve ürün, websocket snapshot/checksum, veri geçmişi ve sözleşme uygunluğu yok |
| EMA/RSI/MACD/ATR/hacim, kırılım | Mevcut PAPER stratejilerinde bağımsız uygulama | Eski bütün varyantlarla parite yok; geçmiş sonuç performans kanıtı değil |
| 10 oy: EMA, MACD, RSI, ADX, stokastik, OBV, CCI, Supertrend, VWAP, Bollinger | `confluence10.py`, yalnız çevrimdışı araştırma | Eksiksiz UTC gün ve 220 mum gerekir; bağımsız referansla her gösterge paritesi ve PAPER entegrasyonu yok |
| Alternatif indikatörler, rejim, divergence, VWAP varyantları | Bazı göstergeler mevcut | Arşivde görülen KAMA, HMA, FRAMA, Hurst, divergence, volume profile ve diğer varyantların çoğu taşınmadı; doğrulama gerekiyor |
| Tek pozisyon, stop/target, maliyet, cooldown | PAPER motorunda mevcut | Stop borsada tutulmaz; polling, boşluklar, marj/likidasyon ve gerçek execution modellenmez |
| DCA, pyramiding, gelişmiş trailing ve kurtarma | Bazı trailing seçenekleri yalnız OHLC araştırmasında | PAPER motorunda DCA/pyramiding/hedge/çift kurtarma yok; risk artırdığı için test ve tasarım olmadan etkinleştirilmez |
| Portföy ve risk | Aday stop riski ve yönsel risk hesabı; PAPER'da tek aday için kapı | Ortak kasalı çok sembollü yürütme, korelasyon kümesi, margin/likidasyon ve stres senaryoları yok |
| Funding önleme | Mevcut PAPER motorunda eksik/bayat ve yakın settlement korumaları | Funding tutarı mevcut PAPER defterine muhasebeleştirilmez |
| Funding ödeme araştırması | `funding_store_research.py`: ayrı, atomik ve tekrara dayanıklı deney defteri | Kaynak settlement verisi getirip doğrulamaz; mevcut defter/motorla bağlantısı, tarihsel uzlaşma ve gerçek borsa muhasebesi yok |
| Emir defteri ve akış | `SequenceBook` genel sıra kontrolü; `depth_research.py` statik snapshot ile maliyet/kısmi tahmin | İkisi PAPER motoruna bağlı değil; borsaya özel checksum, güncel derinlik akışı, queue ve piyasa etkisi yok |
| Kısmi dolum ve mutabakat | `order_journal_research.py` ayrı SQLite; dolum kimliği idempotent, aşırı dolum reddi, iptal/belirsizlik durumları | Gerçek broker/harici kanıt doğrulama yok. Pozisyonları bu günlüğe bağlayan ortak defter, yeniden başlatma kurtarma ve uçtan uca motor entegrasyonu yok |
| Borsa adım/minimum kuralları | Derinlik araştırması için elle verilen qty/tick/minimum kuralları | Kaynak doğrulanmaz, sözleşme çarpanı ve borsadan kural toplama yok; gerçek emir için uygunluk kanıtı değil |
| Geriye dönük araştırma | OHLC replay, basit performans özeti, önceden belirlenen ücret/spread/kayma senaryoları, 2/3/4 walk-forward, 10 oy seçeneği | OHLC motoru PAPER ile aynı değil; 10 oy için ayrı walk-forward, sağlam örneklem dışı test, çoklu deneme kontrolü ve daha gerçekçi veri yok |
| Defter, gözlem ve recovery | Mevcut PAPER SQLite atomik işlem ve aritmetik denetim, kesinti uyarıları | Uzun süreli restart/crash dayanıklılığı, harici rekonsiliasyon ve açık emirlerin otoritatif recovery'si yok |
| Görsel panel | PAPER durum, gösterge, defter uyarıları | Görsel tarayıcı testi ve kullanıcı/erişim yönetimi yok; güvenilmeyen ağlara açılmamalı |
| Bildirim ve operasyon | Panelde uyarılar | Telegram/WhatsApp/Discord/PagerDuty entegrasyonları yok; sırların güvenli yönetimi ve kimlik doğrulama yok |
| YZ/haber/duygu | Bağlı model yok | Haber akışı, sağlam veri kaynakları, API/servis izinleri, doğrulama ve güvenli fallback yok; model kullanılmış gibi gösterilmez |
| Salesforce OmniStudio | Bağlantı yok | Salesforce hesabı/bağlayıcı ve erişim sağlanmadan gerçek entegrasyon yapılamaz |
| Çoklu borsa arbitrajı ve gerçek emir | Bilerek yok | Kullanıcının PAPER koşuluyla gerçek emir, borsa anahtarları ve üretim yürütücüsü eklenmemiştir. Bağımsız tasarım/izin ve güvenlik incelemesi gerekir |

## Güvenli ilerleme sırası

1. Bağımsız sayısal gösterge parite fixture'ları ve UTC/veri boşluğu sınır testlerini genişlet; 10 oylu araştırmayı mevcut motorla karıştırma.
2. Emir ve funding deney defterlerini bir **yeni, ayrı** araştırma sistemi üzerinde ortak pozisyon defteriyle birleştir; partial-fill, zaman aşımı, çökme, yarış ve tekrar kayıtların deterministik testlerini yap. Mevcut kilitli defteri taşımadan/yeniden kullanmadan önce migrasyon ve geri dönüş planı gerekir.
3. Harici veri/doğru settlement, borsa kuralları ve derinlik için kaynak/protokol doğrulaması; ücret/kontrat/likidasyon modelleri; çoklu piyasa ve ortak kasa riskini geliştir.
4. Çevrimdışı sağlam maliyetli deneyler, out-of-sample karşılaştırma, veri kalitesi ve izleme/operasyon testleri. Ek model ve entegrasyonlar ancak yetki, güvenli sır yönetimi ve doğrulama ile değerlendirilir.
5. Yalnız kullanıcının ayrıca talimatıyla, korunmuş eski kayıtları değiştirmeden yeni ve ölçülebilir ileriye dönük PAPER protokolü. Bu rapor PAPER veya gerçek para hazırlık onayı değildir.
