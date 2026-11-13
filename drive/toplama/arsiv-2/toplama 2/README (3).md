# 🛡️ KRIPTO-BOT v6 — Kurumsal, Zırhlı, Multi-Timeframe 1h/4h, 20 Kademe Emir Defteri, Discord/PagerDuty & Multi-Exchange Failover Kripto Botu

Binance ve OKX vadeli/spot piyasalarında çalışan; **Multi-Timeframe (1h / 4h) Ana Trend Filtresi**, **20 Kademe Emir Defteri Derinlik Analizi (`Bid/Ask Ratio`)**, **Discord Webhook & PagerDuty Acil Sesli Telefon Alarmı**, **Multi-Exchange Failover (Borsa Kesinti Sigortası)**, **SQLite WAL Modu & 24 Saatlik `VACUUM` Çöp Toplayıcı**, **Prometheus `/metrics` ve `/health` Canlı Sağlık Endpoint'i**, **Kritik Güvenlik Zırhlaması (Security Hardening)**, **%10 Kasa × Dinamik 20x/10x/5x Kaldıraç**, **%0.30 Maksimum Kayma (Slippage) & Chase Order**, **%5 Zarar Stop + Kâr Kilidi**, **Artıda Sınırsız Kademe Ekleme (Pyramiding)** ve **Çapraz İkili Kurtarma** özelliklerine sahip tam donanımlı alım-satım sistemi.

---

## 🆕 v6 Sinyal Kalitesi & Acil Alarm Yükseltmeleri

### 1. Multi-Timeframe (Çoklu Zaman Dilimi — `1h` / `4h`) Ana Trend Filtresi (`src/indicators.py`, `src/strategy.py`, `src/executor.py`)
- **Sorun:** Bot hızlı zaman dilimlerinde (`1m` veya `5m`) anlık verilerle işlem yaparken, `1h` veya `4h` ana trend sert düşüşteyken (`BEARISH`) küçük bir tepki yükselişine aldanıp `LONG` açma riski taşıyabilir.
- **Çözüm (`compute_htf_trend` & `multi_timeframe_filter`):**
  - Arka planda her sembol için `1h` (%45 ağırlık) ve `4h` (%55 ağırlık) mumları üzerinde **EMA 20 / EMA 50 / EMA 200 dizilimi**, **EMA20 eğimi**, **MACD Histogram**, **ADX (+DI/-DI)** ve **RSI** birleştirilerek `-100 .. +100` arası büyük trend skoru hesaplanır.
  - **Ana Trend Aşağı Yönlüyse (`BEARISH`, skor `<= -15.0`):** `allow_long = False` olur; `1m`/`5m` grafikteki küçük tepki yükselişlerinde **kesinlikle `LONG` açılmaz** (`MTF TREND FİLTRESİ (1h/4h BEARISH)`), yalnızca ana trend yönündeki `SHORT` sinyallerine izin verilir.
  - **Ana Trend Yukarı Yönlüyse (`BULLISH`, skor `>= +15.0`):** `allow_short = False` olur; küçük düzeltmelerde ana trende ters `SHORT` açılmaz, yalnızca `LONG` yönlü işlemlere izin verilir.

### 2. 20 Kademe Emir Defteri Derinlik Analizi (`Order Book 20-Level Depth Imbalance` & `Bid/Ask Ratio` — `src/moneyflow.py`, `src/market_data.py`)
- **20 Kademe Canlı Derinlik (`@depth20@100ms`):**
  - `MarketData` Binance `@depth20@100ms` akışından ve OKX derinlik kanalından anlık **20 kademe** alıcı (`bids`) ve satıcı (`asks`) emir defterini okur.
- **`MoneyFlow.update_book(bids, asks, depth=20)` Metrikleri:**
  - **`bid_depth_usdt` & `ask_depth_usdt`:** İlk 20 kademedeki toplam Alıcı ve Satıcı duvarlarının USDT büyüklüğü.
  - **`bid_ask_ratio` (`Bid/Ask Ratio`):** `Bid_20 / Ask_20` hacim oranı (örn. `2.80x` → alıcı duvarları satıcı duvarlarının 2.8 katı).
  - **`weighted_obi`:** Fiyata yakın kademelere üstel olarak (`exp(-0.12 * i)`) daha yüksek ağırlık veren mesafe-ağırlıklı derinlik dengesizliği (`-1.0 .. +1.0`).
  - **`wall_signal`:** `ALICI_DUVARI`, `SATICI_DUVARI` veya `DENGELI` tespiti ve doğrudan Para Akışı skoruna **`-25 .. +25` puan** (`depth_score_boost`) katkı.

### 3. Discord Webhook & PagerDuty Acil Durum Sesli Alarm Entegrasyonu (`src/alerts.py`, `src/telegram.py`, `src/config.py`)
- Telegram bildirimlerine ek olarak, sunucu tarafında kritik bir durum (`Circuit Breaker` tetiklenmesi, 3 ardışık emir/yetki hatası, %5 günlük zarar limiti, `Multi-Exchange Failover`, `Flash Crash`, `>10sn WS Kopması`, `Kill-Switch`) oluştuğunda `MultiChannelAlerter` devreye girer:
  1. **Discord Webhook (`DISCORD_WEBHOOK_URL`):** `@everyone 🚨 **ACİL DURUM: KRIPTO-BOT KRİTİK UYARI**` başlığı ve kırmızı (`0xEF4444`) zengin **Embed** kartı ile ekibe anında bildirim düşer.
  2. **PagerDuty Events API v2 (`PAGERDUTY_ROUTING_KEY`):** `https://events.pagerduty.com/v2/enqueue` uç noktasına `event_action: "trigger"` ve `severity: "critical"` göndererek doğrudan telefonunuza **acil durum sesli arama / SMS / yüksek öncelikli push alarmı** çaldırır. Sigorta sıfırlandığında (`reset_breaker`) otomatik olarak `event_action: "resolve"` gönderir.
  3. **Sıfır Sır Sızıntısı:** Hem `DISCORD_WEBHOOK_URL` hem `PAGERDUTY_ROUTING_KEY` yalnızca `.env` üzerinden okunur ve `security.register_secret()` ile maskelenir.

---

## 🧱 v5 & v4 Zırhlı Altyapı Özellikleri (Tamamı Aktif)

- **Multi-Exchange Failover (`src/exchanges.py`):** Binance API üst üste 3 timeout verirse işlemleri kesintisiz olarak yedek borsaya (**OKX**) kaydırır.
- **SQLite WAL Modu & 24 Saatlik `VACUUM` Çöp Toplayıcı (`src/state_store.py`):** `PRAGMA journal_mode=WAL` + her 24 saatte bir eski kayıtları `.jsonl.gz` olarak arşivleyip `VACUUM` ile veritabanı şişmesini önler.
- **Gerçek Zamanlı `/health`, `/healthz` ve Prometheus `/metrics` (`src/health.py`):** Dış izleme araçlarının her saniye botun sağlık ve metriklerini kontrol etmesini sağlar.
- **%10 Kasa × Dinamik 20x / 10x / 5x Kaldıraç + %0.30 Kayma & Chase Order + %5 Stop + Artıda Sınırsız Ekleme + Çapraz İkili Kurtarma**
- **İki Yönlü Telegram Botu (`/durum`, `/kill`, `/durdur`, `/baslat`, `/sigorta`)**

---

## 🚀 Hızlı Başlangıç ve Komutlar

```bash
# 1) Tüm 28 bölümdeki 87 kapsamlı çevrimdışı testi çalıştırın
python3 test_hizli.py

# 2) Gerçek Zamanlı Web Panelini + /health & /metrics sunucusunu başlatın (Port 8501)
python3 -m src.dashboard

# 3) Canlı sağlık ve Prometheus metriklerini sorgulayın
curl http://localhost:8501/health
curl http://localhost:8501/metrics

# 4) Botu Paper (Sanal Para) modunda başlatın
python3 -m src.main
```
