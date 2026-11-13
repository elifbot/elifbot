# ACARBOT FINAL v1.1 — Değişiklik Günlüğü (7 Kasım 2026)

Kullanıcı isteği üzerine: APEX v1.1 profili geri eklendi + eski sürümlerde
taslak kalan iki özellik gerçek implementasyonla tamamlandı.

## 1. APEX v1.1 profili (`--profile apex`) — KULLANICI TERCİHİ
Eski APEX v1.1'deki davranış birebir geri geldi:
- **Sınırsız pozisyon**: sabit adet tavanı yok; doğal sınır serbest
  bakiye/teminat (50 USDT teminat × kullanılabilir bakiye).
- **Günlük fren YOK**: günlük -100 soft / -150 hard kapıları kapalı;
  günlük PnL yeni girişleri otomatik durdurmaz.
- Portföy tavanları kapalı: grup başına adet/nominal, brüt/yönsel nominal,
  toplam açık risk tavanı (bunlar pozisyon adedini dolaylı sınırlıyordu).

**Korunan güvenlik katmanları** (APEX v1.1'de de vardı / bağımsız):
- Pozisyon başı **25 USDT NET risk tavanı** (ücret+kayma+funding dâhil)
- Teminat yeterliliği kontrolü, izole teminat likidasyon modeli
- Portföy drawdown koruması (%8 tepe-dipte → yeni giriş yok)
- Veri bütünlüğü/güvenli mod, kill switch altyapısı (günlük tetikleyicisiz)

CLI: `--max-positions 0` = sınırsız (her profilde); `--no-daily-brake`
tek başına da kullanılabilir. CLI argümanları profile baskındır
(ör. `--profile apex --max-positions 3` → 3 pozisyon, fren yok).
Varsayılan profil `guarded`dır (eski davranış); başlatıcılar `apex` kullanır.

## 2. Makro haber koruması (`safety/news_guard.py`) — GERÇEK implementasyon
ultra_plus'taki 13 satırlık taslak (hep `False` döndüren hook) yerine:
- Forex Factory haftalık ekonomik takvimi (anahtarsız JSON, doğrulandı).
- Yüksek etkili **USD** olayları (FOMC, CPI, NFP, işsizlik...) ±30 dk
  penceresinde **yeni giriş engellenir**; stoplar/çıkışlar çalışmaya devam eder.
- 15 dk'da bir tazeleme, hata durumunda eski veriyle devam (fail-open),
  isteğe bağlı yerel olay dosyası (`local_events_file`), `fail_closed` seçeneği.
- CLI: `--no-news-guard`, `--news-buffer-minutes N`.

## 3. Stop-hunt / likidasyon duvarı koruması (`core/sweep_guard.py`) — GERÇEK implementasyon
ultra_plus'taki 15 satırlık prototip (beslenmeyen veri bekleyen) yerine:
- Gerçek REST orderbook (OKX 400 seviye, kontrat→baz dönüşümü mevcut).
- ±%0.5 aralık %0.1 bantlara bölünür; bant nominali hem ≥500k$ hem de
  medyanın ≥8 katıysa **duvar** sayılır.
- Duvar fiyatın ±%0.35 içindeyse yeni giriş engellenir (mıknatıs/stop-avı
  riski); 25 sn'de bir tazeleme, 60 sn TTL (bayat defter karar dışı).
- Gerçek likidasyon ısı haritası değil, defter temelli muhafazakâr filtredir.
- CLI: `--no-sweep-guard`.

## 4. Hata düzeltmesi: OKX orderbook canlıda hiç çalışmıyordu
OKX `/api/v5/market/books` yanıtı `instId` alanı DÖNDÜRMEZ (yalnızca
asks/bids/ts/seqId). Taban kod `result["instId"]` ile KeyError → "malformed
order book" veriyordu. Düzeltildi + regresyon testi eklendi
(`tests/test_okx_orderbook_fix.py`). Canlı doğrulama: 400 seviye, kontrat
dönüşümü doğru, 3 sembolde 8 başarılı defter çekimi.

## 5. Diğer
- Oturum raporuna eklendi: profil, max_positions, günlük fren durumu,
  haber/sweep koruma istatistikleri (yüklenen olay, izlenen defter, blokaj).
- RiskManager: limit değerlerinde **0 = kapalı** semantiği (varsayılanlar
  değişmedi, guarded davranış birebir korundu).
- Backtest de profil/CLI overrides ile uyumlu (`--profile apex` backtest'te
  de sınırsız pozisyon uygular).
- Sürüm: `1.1-final`.

## Test durumu
**195/195 test geçti** (152 v1.0 + 43 yeni: APEX profili 15, haber 14, sweep 12, OKX regresyon 2).
Canlı doğrulama (1 dk duman testi, APEX profili): sınırsız pozisyon + fren
kapalı afişi, 4 haber olayı yüklendi, 3 sembolde defter izleme aktif,
1.072 tick, hatasız otomatik kapanış, JSON raporda profil/koruma durumları.

## Notlar
- Binance bu derleme ortamında HTTP 451 (bölgesel engel); OKX kullanılıyor.
- Paket PAPER ONLY'dir; gerçek emir göndermez, kârlılık kanıtı değildir.
- Sınırsız pozisyon + frensiz mod bilinçli kullanıcı tercihidir; risk
  pozisyon başı 25 USDT tavanı ve teminatla sınırlıdır, toplam risk
  pozisyon sayısıyla büyüyebilir.
