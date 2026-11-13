# 🤖 Kripto Bot Ekibi — İsimli AI Botlar + Konsensus Sinyal Sistemi

Bilgisayarında çalışan masaüstü yazılımı. Burada işi **yapay zekâ botları yapar**:
her AI modeli kadroda **isimli, emojili, rollü bir bot** olarak çalışır
(🧭 Kaptan, 🛡️ Denetçi, 🎯 Nişancı, 📡 Tarayıcı, ⚖️ Hakem). Botlara
**Bot Odası**'ndan doğal dilde görev verirsin; botlar görevi yürütür,
**birbirlerini kontrol eder ve doğrular**, kararı birlikte verirler.

---

## 🧠 Nasıl Çalışıyor?

```
        SEN (Bot Odası'na görev yazarsın)
         │  "BTC analiz et" / "piyasayı tara" / "Hakem ne düşünür?"
         ▼
 ┌───────────────────────────────┐
 │  BOT KADROSU (SQLite'ta saklı)│   Her bot = ayrı AI modeli
 │  🧭 Kaptan    → evren-glm     │   İsim/emoji/rol/model senin seçimin
 │  🛡️ Denetçi   → evren-deepseek│   ➕ Bot Ekle ile yeni bot kurabilirsin
 │  🎯 Nişancı   → evren-qwen    │   Pasife alabilir / silebilirsin
 │  📡 Tarayıcı  → evren-gemma   │
 │  ⚖️ Hakem     → evren-auto    │
 └──────────────┬────────────────┘
                ▼
 ┌───────────────────────────────────────────────┐
 │  GÖREV YÜRÜTME (Bot Odası'na canlı akar)       │
 │  • TARAMA  : tüm piyasa taranır, Tarayıcı      │
 │    bot yorumuyla özetler                      │
 │  • ANALİZ  : canlı veri her bota aynı gider → │
 │    her bot BAĞIMSIZ JSON oy verir, oyu odaya   │
 │    anlık düşer → oylar bölünürse ⚖️ Hakem      │
 │    devreye girer → 🏁 SONUÇ (SL/TP/kaldıraç)   │
 │  • SOHBET  : bot yanıtlar; '@Denetçi' yazarsan │
 │    gerçekten Denetçi'nin modeli devreye girer  │
 └──────────────┬────────────────────────────────┘
                ▼
 ┌───────────────────────────────────────────────┐
 │  KARAR + DOĞRULAMA                             │
 │  Oydaşlık ≥ %75 GÜÇLÜ KONSENSÜS                │
 │  Oydaşlık ≥ %50 KONSENSÜS                      │
 │  Oydaşlık < %50 → HAKEM KARARI                 │
 │  Geçer sinyal → kayıt + 🔔 masaüstü bildirimi   │
 └───────────────────────────────────────────────┘
```

**Bir botun modeli dolarsa** (HTTP 503) sistem çökmez: odaya "oy veremedi"
mesajı düşer, kalan botlarla konsensus kurulur. Botlar meşgulken yeni görev
**kuyruğa girer**, sıra gelince otomatik çalışır.

---

## 🚀 Kurulum (Windows)

1. Python 3.10+ kur: <https://www.python.org/downloads/> — kurulumda
   **"Add Python to PATH"** kutusunu işaretle.
2. Bu klasörü bilgisayarına çıkar.
3. **`KriptoPanel-Baslat.bat`** dosyasına çift tıkla.
   - İlk çalıştırmada paketleri otomatik kurar (1-2 dk).
   - Panel açılır: **http://127.0.0.1:8543** (tarayıcı otomatik açılır).

macOS / Linux: `chmod +x baslat.sh && ./baslat.sh`

### EVREN API anahtarı
`.env` dosyasında `EVREN_API_KEY` zaten dolu — 5 bot EVREN (SAYZEK) modelleri
üzerinden çalışır hazır gelir. Anahtarın geçerliliği EVREN platformuna bağlıdır;
şartlar v1 kabul edilmiş durumdadır (kabul kaydı: 2026-11-08). Kredi/bakiye
durumunu EVREN panelinden takip et.

> Anahtar olmasaydı bile sistem çalışırdı: gömülü GLM + Pollinations
> (ücretsiz, anahtarsız) ile yedek kadro kurulur.

### Opsiyonel: gömülü GLM yedeği (Node.js)
Gömülü GLM modelini de kullanmak istersen: [Node.js](https://nodejs.org) kur,
klasörde `npm install` çalıştır (bir kere). Kurmasan da EVREN + Pollinations
yeterlidir.

---

## 💬 Bot Odası — ne yapabilirsin?

| Görev örneği | Ne olur |
|---|---|
| `BTC analiz et` | Kaptan görevi alır → tüm botlar canlı veriyle oy verir (oylar anlık odaya düşer) → gerekirse Hakem kararı → 🏁 SONUÇ + Nişancı'nın plan değerlendirmesi |
| `piyasayı tara` | Tarayıcı bot 8 coini tarar, skor tablosu + AI yorumu odaya düşer |
| `En güçlü fırsat hangisi?` | Tarama + özet |
| `Botlar kendini tanıtsın` | Her bot kendi modeliyle konuşarak kendini tanıtır |
| `@Denetçi ETH long mantıklı mı?` | Mesaj doğrudan Denetçi'nin modeline gider; Denetçi başka bota yönlendirirse o da devreye girer |
| Serbest soru | Rol botu (Kaptan) cevaplar, gerekirse uzman bota danışır |

**Bot Kadrosu** kartından: her botun modelini değiştirebilir, rolünü
güncelleyebilir, aktif/pasif yapabilir, kadrodan çıkarabilir; ➕ Bot Ekle ile
yeni bot kurabilirsin (ad + emoji + rol + model seç).

---

## 🎛 Panel Bölümleri

| Bölüm | Ne yapar |
|---|---|
| **Bot Odası** | Canlı bot sohbeti. Görev ver, botların birbirini kontrol etmesini izle. |
| **Bot Kadrosu** | Bot ekle/sil/model değiştir/pasife al. |
| **Sembol Analizi** | Sembol gir → bot ekibi konsensus analizi (~30-60 sn). Oy kartları, güven barları, hakem kararı, teknik gerekçeler, SL/TP planı. |
| **Piyasa Taraması** | Popüler 8 coini teknik skorla sıralar; "🧠 Analiz" ile bot ekibine götürür. |
| **İzleme Listesi** | Sembol ekle → her N dakikada otomatik taranır. Eşik aşılırsa bot ekibi doğrular; güven ≥ %60 + oydaşlık ≥ %50 ise masaüstü bildirimi + alarm kaydı. |
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
`.env` içindeki anahtar alanlarını doldurunca **bot olarak atanabilir** hale gelir:
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`,
`DASHSCOPE_API_KEY`, `MISTRAL_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`.
Herhangi bir OpenAI-uyumlu adres için: `CUSTOM_BASE_URL` + `CUSTOM_MODEL` +
`CUSTOM_API_KEY`. Yerel modeller için: [Ollama](https://ollama.com) kur →
`ollama pull llama3.2` → botuna "Ollama yerel" modelini ata.

---

## 📁 Dosyalar

| Dosya | Görev |
|---|---|
| `panel.py` | Web panel sunucusu + otomatik tarama işi + bot/oda API'leri |
| `botlar.py` | **Bot ekibinin beyni**: kadro, kişilikler, görev yönlendirme, bot-to-bot oda protokolü |
| `konsensus.py` | Bot oyları + Hakem + oydaşlık hesabı (oylar odaya canlı düşer) |
| `signal_engine.py` | Teknik analiz (EMA, RSI, MACD, ATR, funding, OI) |
| `market_data.py` | Bybit v5 veri katmanı (yedek OKX) |
| `providers.py` | Çoklu-AI sağlayıcı katmanı + yedekleme zinciri |
| `llm_bridge.mjs` | Gömülü GLM köprüsü (Node.js, opsiyonel yedek) |
| `database.py` | SQLite: botlar, oda mesajları, analizler, alarmlar, izleme |
| `bildirim.py` | Masaüstü bildirimi (plyer) |
| `static/` | Panel arayüzü (HTML/CSS/JS) |
| `bot_data.db` | Panel verileri (ilk çalıştırmada oluşur) |

## 🔧 Sorun Giderme

- **"Model şu anda dolu" (HTTP 503)** — EVREN modeli geçici kapasite dolu.
  Sistem 3 kez yeniden dener; olmazsa kalan botlarla devam eder, odaya şeffaf
  hata mesajı düşer.
- **Görevim çalışmadı** — Botlar meşgulse görev kuyruğa girer ("⏳ sırada"
  mesajı odaya düşer); sıra gelince çalışır.
- **Veri alınamıyor** — Bybit engelliyse OKX otomatik devreye girer. İkisi de
  gidiyorsa internet/VPN kontrol et.
- **Port çakışması** — `.env`'e `PANEL_PORT=8599` gibi farklı port yaz.
- **Bildirim gelmiyor** — Windows'ta bildirim iznini kontrol et; panel başlıkta
  bildirim türünü gösterir (`native` / `konsol`).
- **Sıfırlama** — `bot_data.db` dosyasını sil; panel temiz başlar (bot kadrosu
  varsayılan 5 botla yeniden kurulur).

## ⚠️ Risk Uyarısı

Bu yazılım **yalnızca otomatik teknik analiz ve AI bot yorumu** sunar —
**yatırım tavsiyesi değildir**. Vadeli işlemler kaldıraç nedeniyle yüksek risk
taşır; pozisyonun tamamını kaybedebilirsin. Botlar hata yapabilir, hatta
birbirine ters oy verebilir — bu sistemin bir parçasıdır. Kendi araştırmanı yap,
kaybını göze alamayacağın parayla işlem yapma.
