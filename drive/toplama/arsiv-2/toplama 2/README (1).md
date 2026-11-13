# 🛡️ KRIPTO-BOT v4 — Zırhlı Kurumsal Hızlı İşlem, Arbitraj & Komuta Sistemi

WebSocket ile **milisaniyeler içinde tepki veren**, 13 indikatör + para akışı (Açık Faiz & Likidasyon Squeeze) + haber/psikoloji + Makine Öğrenmesi (ML) yön tahminini birleştiren; **5 Katmanlı Güvenlik Zırhlaması (Security Hardening)**, **%0.30 Kayma Filtresi & Chase Order**, **Dinamik Kaldıraç (20x → 10x → 5x)**, **İki Yönlü Telegram Botu**, **Out-of-Sample (OOS) Testi**, **SQLite Durum Kalıcılığı**, **Circuit Breaker** ve **Gerçek Zamanlı Web Paneli** içeren tam donanımlı kripto işlem sistemi.

> ⚠️ **RİSK UYARISI:** Kaldıraçlı kripto işlemleri çok yüksek risk içerir, paranızın tamamını kaybedebilirsiniz. Her zaman önce `paper` (sanal para) modda deneyin. Asla kaybetmeyi göze alamayacağınız parayla işlem yapmayın.

---

## 🔒 Kritik Güvenlik ve Zırhlama (Security Hardening — `src/security.py`)

1. **Asla Hassas Bilgi Sızdırma (No Secret Leakage):**
   - `mask_secrets()`, `safe_exception_msg()` ve root `SecretMaskingFilter` sayesinde konsol, log dosyaları, hata yakalamalar ve Telegram mesajlarında `API_KEY`, `API_SECRET`, `PASSPHRASE` veya `TOKEN` değerleri asla açık yazdırılmaz; otomatik olarak `***MASKED***` ile maskelenir.
2. **Çevresel Değişken Güvenliği (Environment Isolation):**
   - Tüm API anahtarları yalnızca `.env` dosyasından ve `os.getenv()` üzerinden okunur (`src/config.py`). `config.yaml` içine yanlışlıkla anahtar yazılsa bile reddedilir ve temizlenir. Kaynak kodda hardcode anahtar bulunmadığı `verify_no_hardcoded_secrets()` ile doğrulanır.
3. **Güvenli Docker Yapılandırması (Non-Root User `appuser`):**
   - `Dockerfile` ve `docker-compose.yml` içinde bot `root` olarak değil, yetkileri kısıtlanmış `appuser` (`no-new-privileges:true`, `chmod 750`) ile çalıştırılır.
4. **Kimlik Doğrulama & Yetki Hatası Sigortası (Auth Circuit Breaker):**
   - Borsa API'sinden ard arda **3 kez kimlik doğrulama veya yetki hatası** (`401`, `403`, `Invalid API-key`, `Invalid signature`, `PermissionDenied`) gelirse `CircuitBreaker` otomatik olarak **`Emergency Kill-Switch`** açar, açık pozisyonları kapatır ve sistemi kilitler (`system_locked = True`).
5. **Girdi Doğrulama (Input Sanitization):**
   - `news.py` ile RSS veya harici sitelerden çekilen tüm başlık, özet ve URL verileri `sanitize_external_text()` ve `sanitize_url()` ile `<script>`, HTML etiketleri, kontrol karakterleri ve SQL/Shell/Prompt enjeksiyon kalıplarından temizlendikten sonra işlenir.

---

## ⚡ Yeni Ticaret, Risk ve Altyapı Özellikleri

| Özellik | Açıklama |
|---|---|
| **A. Maksimum Kayma Filtresi (%0.30) & Chase Order (`src/exchanges.py`, `src/risk.py`)** | Fiyat sinyal/emir seviyesinden **>%0.30** uzaklaşmışsa market emri iptal edilir ve **"Chase Order" (fiyatı takip eden limit emir)** devreye girerek kaymayı maksimum `%0.30` sınırında tutar ve maker komisyon avantajı sağlar. |
| **B. Dinamik Kaldıraç (20x → 10x → 5x) (`src/risk.py`, `src/executor.py`)** | Piyasa sakin ve trend uyumluyken **20x** kaldıraç kullanılır; oynaklık yükseldiğinde (`ATR >= %1.5`) **10x**'e, aşırı oynaklıkta (`ATR >= %3.0`) veya haberlerden **VETO yaklaştığında** otomatik olarak **5x**'e düşürülür. |
| **C. İki Yönlü İnteraktif Telegram Botu (`src/telegram.py`)** | Yalnızca yetkili `TELEGRAM_CHAT_ID` sahibinden komut kabul eder: `/durum` ile anlık Kasa + Açık Pozisyon PnL tablosunu gönderir; `/kill` komutuyla web panelini beklemeden **tüm pozisyonları acilen kapatıp** botu kilitler (`/durdur`, `/baslat`, `/sigorta` dahil). |
| **D. Out-of-Sample (OOS) Aşırı Uyum Testi (`src/backtest.py`)** | Geçmiş verinin ilk **%70'inde (In-Sample)** öğrenip parametre seçer, hiç görmediği son **%30 veride (Out-of-Sample)** dondurulmuş parametrelerle test ederek overfitting olup olmadığını raporlar. |
| **Gizli Tuzak Koruması: WebSocket Keep-Alive (Ping/Pong) & SQLite Reconnect (`src/market_data.py`)** | Düzenli `ping/pong` döngüsü + `recv_timeout` bekçisi + 23 saatte bir proaktif oturum yenilemesi yapar. Kopma anında `handle_reconnect()` ile SQLite (`bot_state.db`) durumunu okuyarak açık pozisyonları ve kâr kilidini anında geri yükler. |
| **%10 Kasa + Artıda Sınırsız Ekleme + Çapraz Kurtarma** | Her girişte kasanın **%10'u marj** olarak kullanılır; pozisyon artıda oldukça **sınırsız kademe (pyramiding)** eklenir; **biri artıda biri ekside (terste)** iki pozisyon varsa ufak kâr/zararla **ikisi birlikte kapatılarak** tersteki işlem kurtarılır. |

---

## 🚀 Hızlı Başlangıç ve Doğrulama

```bash
cd kripto-bot

# 1) Tüm 22 bölüm ve 69 güvenlik/strateji/altyapı testini çalıştırın
python3 test_hizli.py

# 2) Zırhlı Gerçek Zamanlı Web Panelini başlatın (Port 8501)
python -m src.dashboard

# 3) Ana Asenkron Borsa Botunu başlatın
python -m src.main

# 4) Event-Driven + Out-of-Sample (OOS) Backtest çalıştırın
python -m src.backtest verileriniz.csv
```
