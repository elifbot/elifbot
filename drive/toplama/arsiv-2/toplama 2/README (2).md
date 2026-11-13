# 🛡️ KRIPTO-BOT v5 — Kurumsal, Zırhlı, Multi-Exchange Failover & Makine Öğrenmesi Destekli Kripto Botu

Binance ve OKX vadeli/spot piyasalarında çalışan; **Multi-Exchange Failover (Borsa Kesinti Sigortası)**, **SQLite WAL Modu & 24 Saatlik `VACUUM` Çöp Toplayıcı**, **Prometheus `/metrics` ve `/health` Canlı Sağlık Endpoint'i**, **Kritik Güvenlik Zırhlaması (Security Hardening)**, **%10 Kasa × Dinamik 20x/10x/5x Kaldıraç**, **%0.30 Maksimum Kayma (Slippage) & Chase Order**, **%5 Zarar Stop + Kâr Kilidi**, **Artıda Sınırsız Kademe Ekleme (Pyramiding)**, **Çapraz İkili Kurtarma**, **İki Yönlü Telegram Uzaktan Komuta (`/durum`, `/kill`)**, **Out-of-Sample (OOS) Aşırı Uyum Testi** ve **WebSocket Keep-Alive (Ping/Pong) + SQLite Durum Kurtarma** özelliklerine sahip tam donanımlı alım-satım sistemi.

---

## 🆕 v5 Altyapı & Dayanıklılık Yükseltmeleri

### A. Multi-Exchange Failover (Borsa Kesinti Sigortası — `src/exchanges.py`)
- **Otomatik Yedek Borsaya Geçiş:** Bot hem **Binance** hem **OKX** bağlantılarını aktif tutar.
- Birincil borsadan (örn. **Binance** API) ardı ardına **3 kez Timeout / Ağ Kesintisi (`RequestTimeout`, `DDoSProtection`, `ExchangeNotAvailable`, `NetworkError`)** hatası alınırsa:
  1. `ExchangeManager.record_exchange_timeout("binance", err)` kesintili borsayı soğuma süresince (`failover.soguma_saniye: 300`) devre dışı bırakır.
  2. İşlem ağırlığını, piyasa verisi sorgularını ve yeni açılacak pozisyonları **botu durdurmadan otomatik olarak yedek borsaya (`OKX`)** kaydırır (`broker.primary == "okx"`).
  3. Birincil borsa tekrar sağlıklı yanıt verdiğinde (`record_exchange_success`) otomatik olarak normale döner.

### B. SQLite WAL Modu, Gzip Log Rotation & 24 Saatlik `VACUUM` Çöp Toplayıcı (`src/state_store.py`)
- **Otomatik WAL (Write-Ahead Logging):** `bot_state.db` her bağlantıda otomatik olarak `PRAGMA journal_mode=WAL;`, `PRAGMA synchronous=NORMAL;`, `PRAGMA wal_autocheckpoint=1000;` ve `64 MB` WAL boyut sınırı ile çalışır.
- **24 Saatlik Çöp Toplayıcı (Garbage Collector & Gzip Arşivleme):**
  - `StateStore.run_garbage_collector()` ve arka plan `maintenance_loop()` görevi her **24 saatte bir** (veya Web Paneli / komut üzerinden anında) çalışır.
  - Aktif tablolardaki (`trade_history`, `equity_history`, `arb_history`) eski kayıtları silmeden önce `archives/state_archive_YYYYMMDD.jsonl.gz` dosyasına **Gzip sıkıştırmalı** olarak arşivler.
  - İşlenmiş `command_queue` satırlarını temizler ve ardından `PRAGMA wal_checkpoint(TRUNCATE);`, `VACUUM;` ve `PRAGMA optimize;` komutlarıyla SQLite dosyasını fiziksel olarak küçültür.

### C. Gerçek Zamanlı Sağlık & Prometheus Metrik Endpoint'i (`src/health.py`, `src/dashboard.py`, `src/main.py`)
- Bulut sunucularda (VPS / Docker / Kubernetes / UptimeRobot / Prometheus) dışarıdan bir izleme aracının **her saniye** botun hayatta ve sağlıklı olduğunu kontrol etmesi için ultra-hafif HTTP uç noktaları sunulur:
  - `GET /health` ve `GET /healthz`:
    - Bot sağlıklıysa **`200 OK`** (`status: "healthy"` veya `"degraded_failover"`), Acil Kill-Switch / Devre Kesici kilitliyse **`503 Service Unavailable`** (`status: "unhealthy"`) döner.
    - Yanıt içeriği: `alive`, `healthy`, `uptime_sec`, `active_exchange`, `failover_active`, `open_positions_count`, `equity_usdt`, `sqlite.wal_active`, `sqlite.db_size_bytes`.
  - `GET /metrics`:
    - Standart **Prometheus (0.0.4)** formatında gerçek zamanlı metrikler (`kriptobot_up`, `kriptobot_healthy`, `kriptobot_equity_usdt`, `kriptobot_open_positions_total`, `kriptobot_failover_active`, `kriptobot_sqlite_wal_active`, `kriptobot_sqlite_db_size_bytes`, `kriptobot_exchange_consecutive_timeouts`).

---

## 🔒 Kritik Güvenlik ve Zırhlama (Security Hardening)

1. **Asla Hassas Bilgi Sızdırma (`src/security.py`):**
   - `SecretMaskingFilter` ve `mask_secrets()` tüm `logging`, `print`, `Exception` ve Telegram mesajlarını gerçek zamanlı tarar; `API_KEY`, `API_SECRET`, `PASSPHRASE` ve `TELEGRAM_BOT_TOKEN` değerlerini otomatik olarak `***MASKED_SECRET***` ile gizler.
2. **Sıkı Çevresel Değişken İzolasyonu (`src/config.py`):**
   - Tüm API anahtarları **yalnızca `.env` ve `os.getenv()`** üzerinden okunur.
3. **Konteyner İçi Yetki Kısıtlaması (`Dockerfile` & `docker-compose.yml`):**
   - Uygulama `root` olarak değil, kısıtlı **`appuser` (UID 10001)** kullanıcısı altında, `no-new-privileges:true` ve `cap_drop: [ALL]` ile çalışır.
4. **Hatalı API İsteği Sigortası (`src/circuit_breaker.py`):**
   - Borsadan ardı ardına **3 kez yetki veya kimlik doğrulama hatası (`AuthenticationError` / `PermissionDenied`)** gelirse **Emergency Kill-Switch + Sistem Kilidi** devreye girer.
5. **Girdi Temizleme (`src/news.py` & `src/security.py`):**
   - RSS ve haber kaynaklarından gelen tüm metinler `sanitize_external_text()` ile HTML, `<script>`, SQL/Prompt Injection ve zararlı linklerden arındırılır.

---

## ⚙️ Strateji, Dinamik Kaldıraç & Slippage Koruması

- **%10 Kasa × Dinamik 20x / 10x / 5x Kaldıraç (`src/risk.py`, `src/sizing.py`):**
  - Sakin piyasada **20x**, yüksek oynaklıkta (`ATR/Fiyat >= %1.5`) **10x**, aşırı oynaklıkta (`ATR/Fiyat >= %3.0`) veya haber VETO eşiğinde **5x** kaldıraç otomatik uygulanır.
- **Maksimum Kayma Toleransı (%0.30) & Chase Order (`src/exchanges.py`):**
  - Anlık fiyat sinyal fiyatından **>%0.30** uzaklaşmışsa Market emri iptal edilir ve **Chase Order (Limit Takip Emri)** devreye girer.
- **%5 Zarar Stop & +%10 → +%5 Kâr Kilidi + Artıda Sınırsız Ekleme + Çapraz İkili Kurtarma**
- **İki Yönlü Telegram Botu (`/durum`, `/kill`, `/durdur`, `/baslat`, `/sigorta`)**
- **Out-of-Sample (OOS) Aşırı Uyum Testi (%70 Öğrenme / %30 Görmediği Veri)**

---

## 🚀 Hızlı Başlangıç ve Komutlar

```bash
# 1) Tüm 25 modülün 78 kapsamlı çevrimdışı testini çalıştırın
python3 test_hizli.py

# 2) Gerçek Zamanlı Web Panelini + /health & /metrics sunucusunu başlatın (Port 8501)
python3 -m src.dashboard

# 3) Canlı sağlık ve Prometheus metriklerini sorgulayın
curl http://localhost:8501/health
curl http://localhost:8501/metrics

# 4) Botu Paper (Sanal Para) modunda başlatın
python3 -m src.main
```
