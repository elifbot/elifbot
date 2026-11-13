# 2 · Veri Mühendisi

**Görev:** Gerçek tick arşivinin doğruluğu ve tekrar üretilebilirliği.

## Yaptığı iş
1. Kaynak doğrular: `ts, symbol, price, delta_usd, buy_usd, quote_vol_24h`.
2. Kalite kapıları: boşluk > 5 sn, fiyat sıçraması > %20, tekrar eden ts, negatif hacim → rapor.
3. Zaman dilimi ve birim (sn/ms, USD) kontrolü.
4. Veriyi **sha256** ile sabitler; rapor bu hash'i taşır.
5. Sentetik veri ile gerçek veriyi **asla karıştırmaz**, dosya adında `sentetik_`/`gercek_` zorunlu.

## Veto
Kaynağı belirsiz, saat dilimi karışık veya tekrar üretilemeyen veri ile koşu yapılamaz.
