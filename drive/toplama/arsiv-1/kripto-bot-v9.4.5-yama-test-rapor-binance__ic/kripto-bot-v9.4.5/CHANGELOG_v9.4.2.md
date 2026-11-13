# v9.4.2 — Veri akışı onarımı (işlem kuralları DEĞİŞMEDİ)

## Kök neden
Binance USDⓈ-M vadeli WS 2026-03-06 duyurusuyla /public, /market, /private diye bölündü; eski `/stream` ve `/ws` 2026-04-23'te kapatıldı. Taşınmamış bağlantı yalnız /public (bookTicker) alır; /market (aggTrade, ticker, kline) susar. v9.4.1 paper testindeki 'BBO 1.77M, aggTrade 0, hata 133' bu yüzdendir.

## Değişiklikler
- `src/feed_health.py` (yeni): kategori bazlı URL üretimi; bilinmeyen akışta ValueError (sessiz susma yok); BBO ve trade-tape ayrı sağlık.
- `src/live_runner.py`: aggTrade -> /market, bookTicker -> /public; venue_stats'a last_bbo_ts/last_trade_ts ve akış başına hata sayacı; `healthy` artık BBO VE trade-tape; trade-tape yoksa operational_health alarmı ve /health 503; dashboard varsayılanı healthy:false.
- `scanner/ws_scanner.py`: `!ticker@arr` -> /market/ws/.
- config/pyproject/test sürüm assert'leri 9.4.2.

## Dokunulmayan
Strateji, risk, çıkış, executor, unified_engine, backtests: değişmedi. NOT: `src/live_runner.py` v9.4.0 donmuş 13 dosyadan biriydi; artık hash'i farklıdır (yalnız veri-akışı/sağlık satırları). Diğer 12 dosya aynıdır.

## Doğrulama durumu
- 9 yeni saf-fonksiyon testi geçti. Tam 78+9 test ve 15 dk canlı paper bu ortamda ÇALIŞTIRILMADI (ağ/bağımlılık yok).
- Kabul: Binance `ticks>0`, `errors_aggTrade≈0`, `trade_tape_healthy=true`, /health 200.

## Yeni SHA-256
```
993345a61d410913f3d9f9c9676d318f55dff875746d7658781c4bc4f974980e  src/feed_health.py
438498c7be8bbb289ac1874e7da8213834e7aea03d2adfb43c69d747b3329a8a  src/live_runner.py
09993d4aca72f443a91489a8c12bca06827a5cfc4f3befcb51b2351e60b86413  scanner/ws_scanner.py
b6df5f3721739d48024f06ad27960ecec67edcfc9d7956e5180df312223a8cc1  configs/v9-canonical-production.json
28103fda1825bbca353ca1b3a80af369ec148e9d726ef285ca1cf3f8c3ae9ae3  tests/test_v942_feed_health.py
7ea787a46a986a0a33ef3a228c74201f6cdf8f12fc31bed8fe25b78dadea8814  pyproject.toml
```