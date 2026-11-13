# Gerçek piyasa testi durumu

Bu paket gerçek Binance public veri bağlantısını içerir ve API anahtarı gerektirmez.

Bu geliştirme oturumunda çalıştırma ortamından `fapi.binance.com` DNS/erişim isteği başarısız olduğu için **gerçek Binance mumlarıyla bu oturum içinde dürüstçe doğrulanmış bir canlı sinyal sonucu verilemedi**. Bu nedenle canlı sinyal üretilmiş gibi raporlanmadı.

Buna karşılık sinyal motoru gerçekçi sentetik trend verisiyle çalıştırıldı ve şu sözleşme doğrulandı:

- LONG sinyali üretildi
- veto yok
- score >= minimum
- maliyet sonrası edge >= minimum
- RR >= minimum

Canlı makinede:

```bash
python -m src.main --mode live-paper --symbols BTCUSDT ETHUSDT SOLUSDT --once
```

çıktısı gerçek Binance public market data üzerinden alınmalıdır.
