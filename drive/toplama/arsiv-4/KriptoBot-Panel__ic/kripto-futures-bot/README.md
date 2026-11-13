# 🤖 KriptoBot Panel — 4 Model AI Konsensus Sinyal Sistemi

Bilgisayarında çalışan, **kripto vadeli (futures) piyasa için long/short sinyal**
üreten masaüstü panel. 4 yapay zekâ modeli aynı canlı piyasa verisini inceleyip
**bağımsız oy** verir, birbirinin kararını kontrol eder; uyumsuzluk olursa
**hakem model** nihaî kararı verir. İzleme listesindeki semboller otomatik
tarandığında geçerli sinyaller için **masaüstü bildirimi** gelir.

---

## 🧠 Nasıl Çalışıyor?

```
                 ┌──────────────────────────────┐
                 │  Canlı Piyasa Verisi          │
                 │  Bybit → (yedek: OKX)         │
                 │  mumlar, RSI, EMA, MACD,      │
                 │  funding, açık pozisyon (OI)  │
                 └──────────────┬───────────────┘
                                │
                 ┌──────────────▼───────────────┐
                 │  Teknik Motor (skor ±82)      │
                 │  → LONG / SHORT / NÖTR        │
                 └──────────────┬───────────────┘
                                │  aynı veri 4 modele gider
        ┌───────────┬───────────┼───────────┬───────────┐
        ▼           ▼           ▼           ▼
   EVREN GLM   DeepSeek-V4   Qwen3.8     Gemma-4      ← her model BAĞIMSIZ
   -5.3        .1-Flash      -Flash      -31B            oy verir (JSON)
        │           │           │           │
        └───────────┴───────────┴─────┬─────┘
                                      ▼
                     ┌────────────────────────────────┐
                     │  OYDAŞLIK HESABI               │
                     │  ≥ %75 → GÜÇLÜ KONSENSÜS       │
                     │  ≥ %50 → KONSENSÜS             │
                     │  < %50 → ⚖️ HAKEM ÇAĞRILIR     │
                     └────────────────┬───────────────┘
                                      ▼
                     ┌────────────────────────────────┐
                     │  NİHAİ KARAR + MASAÜSTÜ BİLDİRİM│
                     └────────────────────────────────┘
```

**Bir model çalışmazsa** (kapasite dolu, ağ hatası) sistem çökmez: diğer
modellerle konsensus kurulur, hata veren model panelde şeffaf şekilde
gösterilir. Teknik motor her zaman bağımsız bir oy olarak bandda görünür.

---

## 🚀 Kurulum

### Windows
1. Python 3.10+ kur: <https://www.python.org/downloads/> — kurulumda
   **"Add Python to PATH"** kutusunu işaretle.
2. Bu klasörü bilgisayarına çıkar.
3. **`KriptoPanel-Baslat.bat`** dosyasına çift tıkla.
   - İlk çalıştırmada gerekli paketleri otomatik kurar (1-2 dk).
   - Panel açılır: **http://127.0.0.1:8543** (tarayıcı otomatik açılır).

### macOS / Linux
```bash
cd kripto-futures-bot
chmod +x baslat.sh
./baslat.sh
```

### EVREN API anahtarı
`.env` dosyasında `EVREN_API_KEY` zaten dolu — 4 model kurulu hazır.
Anahtarın geçerliliği EVREN (SAYZEK) platformuna bağlıdır; kullanım şartları
v1 hesap tarafından kabul edilmiş durumdadır (kabul kaydı: 2026-11-08).
Kotaya/ücretlendirmeye ilişkin güncel durumu EVREN panelinden takip et.

> EVREN anahtarı olmasaydı bile panel çalışırdı: gömülü GLM + Pollinations
> (ücretsiz, anahtarsız) ile 2 kişilik kurul kurulur.

---

## 🎛 Kullanım

| Bölüm | Ne yapar |
|---|---|
| **Sembol Analizi** | Sembol gir → 4 model konsensus analizi (~30-60 sn). Oy kartları, güven barları, hakem kararı, teknik gerekçeler, SL/TP planı. |
| **Piyasa Taraması** | Popüler 8 coini teknik skorla sıralar. Satırdaki "🧠 Analiz" ile konsensusa götürür. |
| **İzleme Listesi** | Sembol ekle → her N dakikada otomatik taranır. Teknik skor eşik aşarsa 4 model doğrular; güven ≥ %60 ise masaüstü bildirimi + alarm kaydı. |
| **Ayarlar** | Tarama aralığı (5-240 dk) ve alarm eşiği (10-80). |

## ⚙️ Ayarlar (.env)

| Değişken | Açıklama | Varsayılan |
|---|---|---|
| `SCAN_INTERVAL_MIN` | Otomatik tarama sıklığı (dk) | 15 |
| `STRONG_ALERT_SCORE` | Alarm için teknik skor eşiği (|skor|) | 45 |
| `ALERT_COOLDOWN_H` | Aynı sembol+yöne tekrar alarm soğuması (saat) | 2 |
| `PANEL_PORT` | Panel portu | 8543 |
| `OLLAMA_MODEL` | Yerel Ollama modeli (opsiyonel) | llama3.2 |

### Diğer AI modelleri (opsiyonel)
`.env` içindeki anahtar alanlarını doldurunca **otomatik aktifleşir**:
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`,
`DASHSCOPE_API_KEY`, `MISTRAL_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`.
Herhangi bir OpenAI-uyumlu adres için: `CUSTOM_BASE_URL` + `CUSTOM_MODEL` +
`CUSTOM_API_KEY` (anahtar gerektirmeyen uçlar için boş bırakabilirsin).
Yerel modeller için: [Ollama](https://ollama.com) kur → `ollama pull llama3.2`.

---

## 📁 Dosyalar

| Dosya | Görev |
|---|---|
| `panel.py` | Web panel sunucusu + otomatik tarama işi |
| `konsensus.py` | 4 model oyu + hakem + oydaşlık hesabı |
| `signal_engine.py` | Teknik analiz (EMA, RSI, MACD, ATR, funding, OI) |
| `market_data.py` | Bybit v5 veri katmanı (yedek OKX) |
| `providers.py` | Çoklu-AI sağlayıcı katmanı + yedekleme zinciri |
| `llm_bridge.mjs` | Gömülü GLM köprüsü (Node.js, opsiyonel yedek) |
| `database.py` | SQLite: analizler, alarmlar, izleme, ayarlar |
| `bildirim.py` | Masaüstü bildirimi (plyer) |
| `static/` | Panel arayüzü (HTML/CSS/JS) |
| `bot_data.db` | Panel verileri (ilk çalıştırmada oluşur) |

## 🔧 Sorun Giderme

- **"Model şu anda dolu" (HTTP 503)** — EVREN modeli geçici kapasite dolu.
  Sistem otomatik 3 kez yeniden dener; olmazsa diğer modellerle devam eder.
- **Veri alınamıyor** — Bybit engelliyse OKX otomatik devreye girer. İkisi de
  gidiyorsa internet/VPN kontrol et.
- **Port çakışması** — `.env`'e `PANEL_PORT=8599` gibi farklı port yaz.
- **Bildirim gelmiyor** — Windows'ta bildirim iznini kontrol et; panel başlıkta
  bildirim türünü gösterir (`native` / `konsol`).
- **Sıfırlama** — `bot_data.db` dosyasını sil; panel temiz başlar.

## ⚠️ Risk Uyarısı

Bu yazılım **yalnızca otomatik teknik analiz ve AI yorumu** sunar —
**yatırım tavsiyesi değildir**. Vadeli işlemler kaldıraç nedeniyle yüksek risk
taşır; pozisyonun tamamını kaybedebilirsin. Sinyaller hata içerebilir;
kendi araştırmanı yap, kaybını göze alamayacağın parayla işlem yapma.
