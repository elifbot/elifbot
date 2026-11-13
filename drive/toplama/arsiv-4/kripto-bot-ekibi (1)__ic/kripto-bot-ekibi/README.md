# 🤖 Kripto Bot Ekibi — İsimli AI Botlar + OTO İŞLEM (Binance/OKX Futures)

Bilgisayarında çalışan masaüstü yazılımı. Burada işi **yapay zekâ botları yapar**:
her AI modeli kadroda **isimli, emojili, rollü bir bot** olarak çalışır
(🧭 Kaptan, 🛡️ Denetçi, 🎯 Nişancı, 📡 Tarayıcı, ⚖️ Hakem). Botlara
**Bot Odası**'ndan doğal dilde görev verirsin; botlar görevi yürütür,
**birbirlerini kontrol eder ve doğrular**, kararı birlikte verirler.

**⚡ OTO İŞLEM**: "Başlat" dediğinde zekâlar senin yerine işlem yapar —
**tüm futures pazarını tarar** (hacimli tüm USDT perpetual'lar), teknik motorla
eleme yapar, en güçlü adaylarda **birbirini kontrol ederek oy verir**, konsensus
sağlarsa **Binance veya OKX Futures'te otomatik pozisyon AÇAR**, stop-loss /
take-profit / süre dolunca **otomatik KAPATIR**. Her açılış-kapanış masaüstü
bildirimi + trade logu + Bot Odası'na canlı mesaj olarak düşer.

```
  TÜM FUTURES EVRENİ (hacim sırasına göre 40 sembol)
        │
        ▼
  TEKNİK ÖN ELEME (EMA/RSI/MACD/funding/OI skoru, |skor|≥20)
        │  en güçlü 2 aday
        ▼
  AI BOT KONSENSÜSÜ ── her bot bağımsız JSON oy verir, birbirini
        │               kontrol eder; bölünürse ⚖️ Hakem devreye girer
        ▼
  RİSK KAPISI ── güven ≥ %65 • oydaşlık ≥ %50 • maks 3 pozisyon
        │        • soğuma • günlük zarar limiti • kaldıraç tavanı
        ▼
  POZİSYON AÇ (kağıt / testnet / gerçek) ── SL ve TP kaydı ile
        ▼
  YÖNETİM DÖNGÜSÜ (45 sn'de bir) ── 🛑 Stop-Loss / ✅ Take-Profit /
        ⏱ Süre doldu → POZİSYON KAPAT → PnL + bildirim
```

---

## ⚡ OTO İŞLEM — Modlar (çok önemli)

| Mod | Ne yapar | Para riski |
|---|---|---|
| **KAĞIT** (varsayılan ✅) | Sanal 1000 USDT bakiyeyle simülasyon; emirler canlı piyasa fiyatıyla doldurulur, PnL gerçek akışta hesaplanır | **YOK** — önce burada öğren |
| **TESTNET** | Binance Futures test ağı veya OKX demo trading — sahte para, gerçek API akışı | Yok |
| **GERÇEK** | Kendi API anahtarınla **gerçek emirler** | **VAR** — kaldıraçlı vadeli işlemlerde pozisyonun tamamını kaybedebilirsin |

Modu panelde **⚙️ Oto İşlem Ayarları**'ndan seçebilirsin (GERÇEK modu için ayrıca
onay kutusu şart) ya da `.env`'de `TRADE_MODE=` yaz.

### Risk kapıları (hepsi panelden ayarlanır)
- **Pozisyon büyüklüğü**: bakiyenin %'si (varsayılan %10 marjin)
- **Maks pozisyon**: 3
- **Kaldıraç tavanı**: 5x (bot asla aşamaz)
- **Günlük zarar limiti**: −%5 → trading otomatik durur (manuel "Pasifi Sıfırla" gerekir)
- **AI güven eşiği**: konsensus güveni %65'in altındaysa işlem YOK
- **Soğuma**: kapanan sembole 4 saat dönüş yok
- **KILL SWITCH**: tek tıkla tüm pozisyonları kapat + trader durdur

### Borsa API anahtarları (yalnızca testnet/gerçek mod için)
1. **Binance Futures**: Binance.com → Profil → API Management → Create API.
   **Futures Trading iznini aç, para çekme (Withdrawals) iznini KAPALI bırak.**
   `.env`'e `BINANCE_API_KEY` ve `BINANCE_API_SECRET` yaz.
2. **OKX Swap**: OKX.com → Varlıklar → API → anahtar oluştur (Trade izni).
   Demo için OKX'in "Demo Trading" anahtarını kullan. `.env`'e
   `OKX_API_KEY`, `OKX_API_SECRET`, `OKX_PASSPHRASE` yaz.

> Not: Kredi kartı/sicil gerekmez; anahtarlar yalnızca senin bilgisayarındaki
> `.env` dosyasında kalır. Binance/OKX bölgesel erişim kısıtları olabilir —
> erişim sorununda OKX'i (veya tersini) dene.

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
| **⚡ OTO İŞLEM** | Başlat/Durdur/KILL SWITCH. Bakiye, bugünkü ve toplam PnL, açık pozisyonlar (güncel fiyat + canlı PnL ile), kapanan işlem geçmişi, trade logu, mod/borsa/risk ayarları. "Şimdi Tara" ile tarama turunu hemen çalıştırır. |
| **Bot Odası** | Canlı bot sohbeti. Görev ver, botların birbirini kontrol etmesini izle. OTO İŞLEM açıkken her pozisyon açılışı/kapanışı da buraya canlı düşer. |
| **Bot Kadrosu** | Bot ekle/sil/model değiştir/pasife al. |
| **Sembol Analizi** | Sembol gir → bot ekibi konsensus analizi (~30-60 sn). Oy kartları, güven barları, hakem kararı, teknik gerekçeler, SL/TP planı. |
| **Piyasa Taraması** | Popüler 8 coini teknik skorla sıralar; "🧠 Analiz" ile bot ekibine götürür. |
| **İzleme Listesi** | Sembol ekle → her N dakikada otomatik taranır. Eşik aşılırsa bot ekibi doğrular; güven ≥ %60 + oydaşlık ≥ %50 ise masaüstü bildirimi + alarm kaydı. |
| **Ayarlar** | Tarama aralığı (5-240 dk) ve alarm eşiği (10-80). |

## ⚙️ Ayarlar (.env)

| Değişken | Açıklama | Varsayılan |
|---|---|---|
| `TRADE_MODE` | kagit / testnet / gercek | kagit |
| `TRADE_EXCHANGE` | binance / okx | binance |
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | Binance Futures API (testnet/gerçek için) | boş |
| `OKX_API_KEY` / `OKX_API_SECRET` / `OKX_PASSPHRASE` | OKX Swap API | boş |
| `RISK_POS_PCT` | Pozisyon başına bakiyenin %'si (marjin) | 10 |
| `RISK_MAX_POSITIONS` | Aynı anda maks pozisyon | 3 |
| `RISK_MAX_LEVERAGE` | Kaldıraç tavanı | 5 |
| `RISK_DAILY_LOSS_PCT` | Günlük zarar limiti (%'de dur) | 5 |
| `RISK_MIN_GUVEN` | AI güven eşiği (%'nin altında işlem yok) | 65 |
| `SCAN_MAX_SYMBOLS` | Tur başına taranan sembol | 40 |
| `MIN_VOLUME_USDT` | Min 24s hacim filtresi | 20.000.000 |
| `OTO_MAX_ADAY` | Tur başına AI'ya giden aday | 2 |
| `POS_TIMEOUT_H` | Pozisyon maks. süresi (saat) | 24 |
| `POS_COOLDOWN_H` | Kapanan sembole soğuma (saat) | 4 |
| `PAPER_BALANCE` | Kağıt mod sanal bakiyesi | 1000 |
| `SCAN_INTERVAL_MIN` | Sinyal tarama sıklığı (dk) | 15 |
| `STRONG_ALERT_SCORE` | Alarm için teknik skor eşiği | 45 |
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
| `panel.py` | Web panel sunucusu + otomatik tarama işi + bot/oda/oto-işlem API'leri |
| **`oto_trader.py`** | **Oto-işlem beyni**: evren taraması → teknik eleme → AI konsensus → risk kapısı → pozisyon aç → SL/TP/süre ile kapat |
| **`exchange_trader.py`** | **Emir katmanı**: KAĞIT simülasyon / Binance Futures (HMAC imzalı) / OKX Swap (base64 imzalı) |
| `botlar.py` | **Bot ekibinin beyni**: kadro, kişilikler, görev yönlendirme, bot-to-bot oda protokolü |
| `konsensus.py` | Bot oyları + Hakem + oydaşlık hesabı (oylar odaya canlı düşer) |
| `signal_engine.py` | Teknik analiz (EMA, RSI, MACD, ATR, funding, OI) |
| `market_data.py` | Bybit v5 veri katmanı (yedek OKX) + tüm futures evreni taraması |
| `providers.py` | Çoklu-AI sağlayıcı katmanı + yedekleme zinciri |
| `llm_bridge.mjs` | Gömülü GLM köprüsü (Node.js, opsiyonel yedek) |
| `database.py` | SQLite: botlar, oda mesajları, analizler, alarmlar, pozisyonlar, trade logu |
| `bildirim.py` | Masaüstü bildirimi (plyer; başsız ortamda güvenli konsol modu) |
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
- **"API anahtarları eksik"** — testnet/gerçek mod için `.env`'e borsa
  anahtarlarını yaz (yukarıdaki bölüme bak) ve paneli yeniden başlat.
- **Pozisyon açılmıyor / "miktar minimumun altında"** — bakiye az veya
  `RISK_POS_PCT` düşük; değerleri yükselt (Binance'te çoğu coin için emir
  minimumu ~100 USDT notional'dır).
- **Günlük zarar limiti devrede** — "🔓 Pasifi Sıfırla" düğmesine bas; ama
  önce neden zarara girildiğini trade logundan incele.
- **Port çakışması** — `.env`'e `PANEL_PORT=8599` gibi farklı port yaz.
- **Bildirim gelmiyor** — Windows'ta bildirim iznini kontrol et; panel başlıkta
  bildirim türünü gösterir (`native` / `konsol`).
- **Sıfırlama** — `bot_data.db` dosyasını sil; panel temiz başlar (bot kadrosu
  varsayılan 5 botla yeniden kurulur, pozisyon geçmişi temizlenir).

## ⚠️ Risk Uyarısı

Bu yazılım **yalnızca otomatik teknik analiz ve AI bot yorumu** sunar —
**yatırım tavsiyesi değildir**. OTO İŞLEM gerçek modda **senin hesabına gerçek
emirler gönderir**: kaldıraçlı vadeli işlemlerde tüm pozisyonunu kaybedebilir,
likide olabilirsin. AI botlar hata yapabilir, hatta birbirine ters oy verebilir
— bu sistemin bir parçasıdır; konsensus da garantili kâr getirmez.

**Kurallar:** 1) En az 1-2 hafta KAĞIT modda çalıştır, sonuçları değerlendir.
2) Testnet ile API akışını doğrula. 3) Gerçek modu küçük bakiye ve düşük
kaldıraçla başlat. 4) Para çekme izni KAPALI API anahtarı kullan. 5) Kaybını
göze alamayacağın parayla asla işlem yapma. Her emrin yasal sorumluluğu
kullanıcıya aittir.
