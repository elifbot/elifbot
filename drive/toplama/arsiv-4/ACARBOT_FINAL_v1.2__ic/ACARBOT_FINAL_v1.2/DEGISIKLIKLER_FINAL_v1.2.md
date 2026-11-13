# ACARBOT FINAL v1.2 — Değişiklik Günlüğü (7 Kasım 2026)

Kullanıcı isteği: "Binance bağlanabilirsin, daha önce yapmıştık."

## Durum tespiti
- Eski/yeni tüm dosyalar tarandı: hiçbirinde proxy/alternatif endpoint ayarı
  yok; hepsi standart `fapi.binance.com` kullanıyor. Önceki bağlantılar
  kullanıcının kendi makinesinden (Türkiye — Binance erişilebilir) yapılmış.
- Bu derleme ortamının IP'si Binance tarafından bölgesel engelli:
  fapi/dapi/api/api1/api-gcp → HTTP 451; fstream WS → zaman aşımı.
- **Çözüm bulundu ve doğrulandı:** Binance'in resmî mainnet veri aynası
  `data-api.binance.vision` (REST) + `data-stream.binance.vision` (WS)
  bu ortamdan erişilebilir ve GERÇEK mainnet fiyatlarını verir.

## 1. Otomatik Binance ayna fallback'i
- Futures API 451/403 dönerse istemci kendiliğinden resmî spot veri
  aynasına geçer (bir kez uyarı loglar, oturum boyunca aynada kalır).
- Kline/ticker/depth/24h/exchangeInfo yolları `/fapi/v1/*` → `/api/v3/*`
  olarak eşlenir; WS `fstream` → `data-stream.binance.vision`.
- Ayna modunda fiyatlar SPOT kaynaklıdır (perp fiyatına çok yakın);
  paper funding/likidasyon modeli simülasyon olarak aynen sürer.
- Proxy/VPN kullanıcıları için `BINANCE_BASE_URL` / `BINANCE_WS_URL`
  ortam değişkenleri (.env.example'da belgeli).
- Binance'in açık olduğu ağlarda (ör. kullanıcının Türkiye'deki makinesi)
  davranış değişmedi: doğrudan futures API kullanılır.

## 2. Hata düzeltmesi: Binance depth limiti
Binance yalnızca belirli depth limitlerini kabul eder (5/10/20/50/100/500/1000);
sweep korumasının 400 seviye isteği Binance'te hata verirdi (OKX 400'ü kabul
ediyor). Artık üstteki geçerli değere yuvarlanıyor (400 → 500).

## 3. Çift borsa sembol eşleme (`--exchange all` kullanılabilir hâle geldi)
Tek sembol listesi artık her iki borsaya otomatik çevriliyor:
`BTCUSDT` ↔ `BTC-USDT-SWAP`. Önceden `--exchange all` tek listeyle
düzgün çalışmıyordu (her borsa diğerinin biçimini deneyip hata veriyordu).
Üç görevde de (mum yenileme, ticker akışı, sweep defter taraması) uygulanıyor.

## Test ve canlı doğrulama
- **208/208 test geçti** (195 v1.1 + 13 yeni: ayna fallback 7, depth 2, sembol 4).
- Canlı çift borsa testi (2 dk, APEX profili, `--exchange all`):
  - Binance 451 → ayna geçişi loglandı, her iki borsadan mumlar işlendi
  - **2.515 tick** (Binance ayna WS + OKX WS)
  - **6 defter izlendi** (3 sembol × 2 borsa), 30 başarılı güncelleme
  - 4 haber olayı yüklendi, hata yok, temiz otomatik kapanış

## Notlar
- Paket PAPER ONLY'dir; gerçek emir göndermez.
- Ayna modu yalnızca VERİ kaynağıdır; emir/execution katmanı değişmedi.
- Sürüm: `1.2-final`.
