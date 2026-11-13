# Crypto Futures Algoritmik İşlem Botu

Bu proje, Kripto Vadeli İşlem (Futures) piyasalarında API anahtarı olmadan **Paper Trading (Sanal Simülasyon)** modunda test imkanı sunan, aynı zamanda tek bir ayarlamayla **Binance Futures** ve **OKX Futures** canlı API'lerine geçebilen modüler bir bot altyapısıdır.

## Proje Yapısı

- `config.py`: Risk parametreleri, kaldıraç ayarları ve borsa çalışma modu.
- `exchange_adapter.py`: Borsa entegrasyon katmanı (Paper Trading, Binance, OKX).
- `strategy.py`: Algoritmik işlem stratejisi ve sinyal motoru.
- `risk_manager.py`: Stop-Loss ve Take-Profit kontrol mekanizması.
- `bot_runner.py`: Botu başlatan ana çalıştırma script'i.
- `requirements.txt`: Gerekli Python kütüphaneleri.

## Çalıştırma

Test modunda çalıştırmak için:
```bash
python bot_runner.py
```

Canlı API'lere geçmek için `config.py` içerisindeki `MODE` değişkenini `"BINANCE"` veya `"OKX"` olarak değiştirmeniz ve API anahtarlarını girmeniz yeterlidir.
