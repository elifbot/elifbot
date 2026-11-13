# KRIPTO-BOT v7.8 — 1 Kasım 2026 çalışma kopyası

Gmail v7.8 paketinden alınmıştır. Strateji/risk eşikleri değiştirilmedi.
Değişiklik: src/main.py içinde bağımsız status_heartbeat_loop, 10 saniyede bir güncel durum yazar; uzun REST taraması artık sağlık kaydını bekletmez.
59 regresyon testi ve stale→fresh kontrolü geçti.
İki tamamlanan 10 dk paper oturumu: net -6.83014768 USDT ve -1.8635 USDT. Raporlar ektedir; kârlılık doğrulaması değildir.
Bazı eski README/banner etiketleri v7.2/v7.7 olarak kalmıştır; kaynak v7.8 e-posta paketidir.

## Kurulum (Python 3.10+)
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r requirements.txt

## Yeni 10 dakikalık paper test (Linux/macOS)
MODE=paper PAPER_SESSION_HOURS=0.16666666666666666 BOT_DB_FILE=yeni_test.db BINANCE_PUBLIC_WWW=1 python -u -m src.main

Her yeni test için benzersiz DB adı kullanın; tamamlanmamış oturum DB'si devam ettirilebilir.
Bot live/testnet desteği içerir. Burada yalnız PAPER test edildi; gerçek para kullanmayın.
API anahtarı/.env pakete konulmadı. Strateji parametreleri config.yaml içindedir.

## Standart panel
Panelin doğru DB'yi okuması için config.yaml > veritabani > dosya alanını test DB adıyla eşleştirin.
MODE=paper python -m src.dashboard
Standart panel 8501, sağlık 8502/health üzerindedir. Standart panel güvenlik kısıtları korunur.
Workspace'e özel salt okunur src/workspace_panel.py dağıtıma eklenmedi.
Arşivdeki test DB'leri sonuç inceleme içindir; temiz testte yeni DB kullanın.


## .env dahil güncellemesi
Paket köküne paper ayarlı .env ve .env.example eklendi; gerçek anahtarlar boş. Proje kökünde python -m src.main ile başlatın. Yeni oturumlarda BOT_DB_FILE için yeni ad seçin. Standart panelin DB ayarı config.yaml içinde ayrıca eşleştirilmelidir.
