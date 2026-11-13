# Gelişmiş Otomatik Ticaret Sistemi (v2.0 ULTRA+) - Çalıştırma Kılavuzu

## 1. Kurulum ve Bağımlılıklar
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Ortam Değişkenleri (.env)
`.env.example` dosyasını `.env` olarak kopyalayın ve borsa API bilgilerinizi girin.

## 3. Tüm Test Paketlerini Çalıştırma
```bash
pytest tests/
```

## 4. Paper Trading Botunu Başlatma
```bash
python -m app.main
```
