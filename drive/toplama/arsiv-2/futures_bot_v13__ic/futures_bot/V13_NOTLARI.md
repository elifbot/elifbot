# v13 — Yapay Pozisyon Açma Limitleri Kapalı

Tarih: 28 Ekim 2026  
Mod: paper / araştırma; canlı emir gönderimi yoktur.

## Kullanıcı kararı

Kullanıcı, gelen sinyallerin pozisyon açma sayısı/hızı bakımından sınırlandırılmamasını; aynı coin iki borsadan geldiğinde ise yalnızca birinin alınmasını istedi.

v13, `ws_bot` için aşağıdaki yapay limitleri kapatır:

| Kontrol | v13 `ws_bot` değeri |
|---|---|
| 10 saniye açılış freni | `0` / kapalı |
| Toplam açık pozisyon limiti | `None` / kapalı |
| Aynı-yön pozisyon limiti | `None` / kapalı |
| Marj kullanım oranı limiti | `None` / kapalı |
| Bakiye rezerv tabanı | `0.0` / rezerv yok |
| Günlük zarar yeni-giriş kilidi | `None` / kapalı |

`PaperPortfolio` sınıfının genel varsayılanları değiştirilmemiştir. Diğer motorlar eski limitleriyle çalışabilir; sınırsız değerler yalnızca v13 `ws_bot` tarafından açıkça verilir.

## Korunanlar

### Aynı coin iki borsadan gelirse yalnızca biri

`_base_sembol()` karşılaştırması korunur. Aynı base varlık için açık veya bekleyen pozisyon varken ikinci sinyal `engel:cift_borsa` ile reddedilir. OKX `BTC-USDT-SWAP` ile Binance `BTCUSDT` ve `1000PEPEUSDT` / `PEPE-USDT-SWAP` gibi biçimler aynı base olarak değerlendirilir.

İlk pozisyon kapandıktan sonra yeni bir sinyal tekrar değerlendirilebilir; geçmişte açılmış olmak kalıcı engel değildir.

### Gerçek bakiye ve muhasebe zorunlulukları

- Kullanılabilir özsermaye/marj, pozisyon marjını karşılamalıdır.
- Pozisyon açılışı sonrası bakiye negatif olamaz.
- Fiyat, miktar, kaldıraç ve miktar-adımı kontrolleri korunur.

Bunlar yapay pozisyon sayısı sınırı değil, paper hesabın aritmetik bütünlüğüdür.

### Diğer davranışlar

- Sinyal üretim eşikleri ve piyasa genişliği/cascade filtreleri değiştirilmemiştir.
- v11 izole çıkış ve CSV mutabakatı korunur.
- v12'nin isteğe bağlı `--acilis-freni N` seçeneği korunur; v13 varsayılanı yine 0'dır.

`ws_durum.json` içinde limitlerin güncel değerleri `toplam_pozisyon_limiti`, `ayni_yon_pozisyon_limiti`, `marj_kullanim_limiti`, `gunluk_zarar_giris_limiti`, `bakiye_rezerv_tabani` ve `acilis_freni_10sn` alanlarından izlenebilir.

## Testler

**200 test geçti.**

Yeni testler:

- v13 `ws_bot` varsayılanında bütün yapay açılış limitlerinin kapalı olduğu doğrulanır.
- Eski 40 pozisyon tavanının üzerinde, aynı kısa pencerede **45 farklı sembolün 45'i de açılır**.
- Aynı coinin OKX ve Binance sinyallerinden yalnızca ilki alınır.
- Gerçek bakiye yeterli değilse yeni pozisyon `engel:marj_yetersiz` olur.
- Günlük zarar yeni-giriş kilidinin v13'te kapalı olduğu doğrulanır.
- Önceki PaperPortfolio varsayılan limitleri ve bütün eski regresyon testleri çalışmaya devam eder.

## Risk ve performans sınırı

Bu sürüm sinyallerin pozisyona dönüşme kapsamını artırır; “daha kârlı” olduğu anlamına gelmez. v12'nin 10 dakikalık testi negatifti ve limitleri kaldırmak korelasyonlu zararları da büyütebilir. v13 için yeni 10/15 dakikalık test ve 300+ aynı-ayar işlem örneklemi ayrıca gerekir. Bu pakette yeni canlı/paper performans testi tamamlanmış sayılmaz.
