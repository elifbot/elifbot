# 🤖 KRIPTO-BOT v3 — Kurumsal Seviye Hızlı İşlem, Arbitraj & Komuta Sistemi

WebSocket ile **milisaniyeler içinde tepki veren**, 13 indikatör + para akışı (Açık Faiz & Likidasyon Squeeze) + haber/psikoloji + Makine Öğrenmesi (ML) yön tahminini birleştiren, SQLite durum kalıcılığı, Circuit Breaker sigortası ve Gerçek Zamanlı Web Paneli içeren tam donanımlı kripto işlem botu.

> ⚠️ **RİSK UYARISI:** 20x kaldıraçlı kripto işlemleri çok yüksek risk içerir, paranızın tamamını kaybedebilirsiniz. Her zaman önce `paper` (sanal para) modda deneyin. Asla kaybetmeyi göze alamayacağınız parayla işlem yapmayın.

---

## 🔥 Tüm Özellikler Özeti

| Modül / Kural | Açıklama |
|---|---|
| **%10 Kasa × Sürekli 20x Kaldıraç** | Her girişte kasanın **%10'u marj (teminat)** olarak ayrılır ve **sürekli 20x kaldıraçla** (`Büyüklük = Kasa × 2.0`) işlem açılır. |
| **%5 Zarar Stop + +%10→+%5 Kâr Kilidi** | Zarar stopu **%5** sabittir. Kâr **+%10**'u geçince stop **+%5 kâra** kilitlenir; zirveden %5 dönüşte trailing stop çalışır. |
| **Artıda Oldukça Sınırsız Pozisyon Eklemesi (Pyramiding)** | Mevcut pozisyon(lar) **artıda (kârda)** olduğu sürece üst sınır olmaksızın yeni kademe (%10 kasa × 20x) ve yeni pozisyon eklemesi yapılır. |
| **Terste Kalan Pozisyonu Çapraz Kurtarma (İkili Kapama)** | Açık pozisyonlardan **biri artıda, biri ekside (terste)** ise; ikisinin toplam net K/Z'si ufak bir kâr ya da ufak bir zararla dengelendiğinde **iki pozisyon aynı anda kapatılarak** tersteki işlem kurtarılır. |
| **1. Gerçek Zamanlı Web Paneli (`src/dashboard.py`)** | Tarayıcıdan canlı açık pozisyonları, kâr/zarar eğrisini (Equity Curve), aktif skorları izleme; **Tek Tuşla Botu Durdurma** ve **Acil Durum "Kill Switch" (Tüm Pozisyonları Kapat)** düğmeleri. |
| **2. Açık Faiz (OI) & Likidasyon Takibi (`src/moneyflow.py`)** | Vadeli işlemlerdeki toplam açık pozisyon (Open Interest) değişimini ve anlık Long/Short tasfiyelerini (`forceOrder`) takip ederek **Short Squeeze** ve **Long Squeeze** patlamalarını önceden yakalar. |
| **3. Çapraz Borsa Arbitrajı (`src/arbitrage.py`)** | Binance ve OKX arasındaki anlık alış/satış fiyat ayrışmalarını komisyon + kayma düşüldükten sonra yakalar (ucuz borsadan AL, pahalı borsadan SAT). |
| **4. Makine Öğrenmesi Yön Tahmini (`src/ml_predictor.py`)** | 14 nedensel teknik özelliği LightGBM / XGBoost / Saf NumPy GBDT modeline besleyerek kısa vadeli yükseliş olasılığını ve `-100..+100` ML skorunu üretir. |
| **A. Durum Kalıcılığı — SQLite (`src/state_store.py`)** | Elektrik/internet kesintisinde veya sunucu yeniden başladığında açık pozisyonları, kademeleri, stop ve kâr kilidi durumlarını `bot_state.db` (WAL) üzerinden otomatik kurtarır ve kaldığı yerden devam eder. |
| **B. Event-Driven & Sıfır Look-Ahead Backtest (`src/backtest.py`)** | Gelecekteki veriyi geçmişe kesinlikle sızdırmayan (`MarketEvent → SignalEvent → OrderEvent → FillEvent`) olay tabanlı bar-bar/tick-tick simülasyon motoru. |
| **C. Circuit Breaker — Acil Durum Sigortası (`src/circuit_breaker.py`)** | **Ard arda 3 emir hatası**, **günlük %5 zarar** veya **WebSocket bağlantısının 10 sn'den uzun kopması** durumunda botu otomatik olarak acil durdurur (Kill-Switch). |

---

## 🚀 Hızlı Başlangıç Komutları

```bash
cd kripto-bot

# 1) Tüm 17 modül ve 55 kuralın doğrulama testini çalıştırın
python3 test_hizli.py

# 2) Gerçek Zamanlı Web Panelini (Dashboard + Kill-Switch) başlatın (Port 8501)
python -m src.dashboard

# 3) Ana Asenkron Borsa Botunu başlatın
python -m src.main

# 4) Event-Driven (Look-Ahead Bias İçermeyen) Backtest çalıştırın
python -m src.backtest verileriniz.csv
```

---

## 📁 Proje Dosya Yapısı

```
kripto-bot/
├── config.yaml              ← Tüm strateji, %10 kasa × 20x, risk, ML, arbitraj ve sigorta ayarları
├── .env.example             ← API anahtar şablonu
├── src/
│   ├── main.py              ← Ana asenkron işlem döngüsü
│   ├── dashboard.py         ← Gerçek Zamanlı Web Paneli + Kill-Switch + Canlı Simülasyon (Port 8501)
│   ├── risk.py              ← %5 stop, +%10→+%5 kilit, %10 kasa 20x, sınırsız ekleme, çapraz kurtarma
│   ├── sizing.py            ← %10 Kasa × 20x Kaldıraç + ATR + Kelly Criterion boyutlandırma
│   ├── executor.py          ← Pozisyon, kademe (pyramiding), ikili kurtarma ve koruma yöneticisi
│   ├── moneyflow.py         ← Para giriş/çıkış + Balina + CVD + Açık Faiz (OI) + Likidasyon Squeeze
│   ├── arbitrage.py         ← Binance ↔ OKX çapraz borsa arbitraj motoru
│   ├── ml_predictor.py      ← LightGBM / XGBoost / NumPy GBDT yön tahmin modeli
│   ├── state_store.py       ← SQLite (WAL) durum kalıcılığı ve kesinti sonrası kurtarma
│   ├── circuit_breaker.py   ← Acil durum sigortası (3 emir hatası / %5 günlük zarar / 10sn WS kopma)
│   ├── backtest.py          ← Event-Driven & Sıfır Look-Ahead Bias backtest motoru
│   ├── indicators.py        ← 13 teknik indikatör motoru
│   ├── news.py              ← Haber + Korku/Açgözlülük + 3 katmanlı VETO
│   ├── sentiment_ai.py      ← Yerel + LLM psikoloji analizi
│   ├── strategy.py          ← İndikatör + Akış + Haber + ML sinyal birleştirici
│   ├── walkforward.py       ← Kayan pencereli parametre optimizasyonu
│   ├── exchanges.py         ← Binance + OKX + 20x kaldıraç + Maker + OCO/Stop koruması
│   ├── market_data.py       ← Spot + Vadeli Likidasyon WebSocket akışları
│   └── telegram.py          ← Telegram bildirimcisi
└── test_hizli.py            ← 17 bölüm, 55 kapsamlı doğrulama testi
```
