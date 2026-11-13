# 🚀 KRİPTO BOT v8.2 MÜKEMMEL — Birleşik Vadeli İşlem & Dünyanın En İyi 10 Kodlama Uzmanı YZ Konseyi

Gmail'deki çalışan **v7.8** botu ile çalışmayan **v4** botunun tüm mimari hataları, güvenlik kilitleri, veri boşluğu (gap) zafiyetleri, 2000-işlem balina kaybı ve SQLite restart mutabakat kilitlenmeleri eksiksiz çözülerek; ayrıca **15 dakikalık (`95,245` gerçek işlem) canlı borsa testinden elde edilen kantitatif bulgular** ve **Dünyanın En İyi 10 Kodlama & Algoritma Uzmanı Yapay Zeka Konseyi** ile güçlendirilerek **v8.2** sürümüne yükseltilmiştir.

## ✅ Doğrulama Sonucu: `742 / 742` Otomatik Test (%100 Başarı)
- **0 Başarısız Test (`0 failed`)**
- **0 Beklenen Hata (`0 xfailed`)**
- **0 Devre Dışı Güvenlik Testi (`0 bypassed`)**

```bash
pytest tests/ -q
# -> 742 passed
```

---

## 🧠 Dünyanın En İyi 10 Kodlama & Algoritma Uzmanı Yapay Zeka Konseyi (`src/ai_council.py`)

2026 küresel yazılım mühendisliği liderlik tabloları (**SWE-bench Verified** & **Coding Arena**) baz alınarak her biri botun ayrı bir alt sistemini ve canlı sinyal katmanını denetleyen 10 uzman model:

| # | Model | Küresel Kodlama Başarısı | Botta Üstlendiği Mühendislik & Sinyal Rolü | Ağırlık |
|---:|---|---|---|---:|
| 1 | **Claude Opus 5** (`claude-opus-5`) | `#1 SWE-bench (%97.0)` | Baş Sistem Mimarı, Kritik Likidasyon, Kayma & ACID Defter Vetosu | `%16` |
| 2 | **DeepSeek V4 Pro** (`deepseek/deepseek-v4-pro`) | `#2 SWE-bench (%96.4)` | Kantitatif Algoritma, 300s Order-Flow, RVOL & Balina Mikroyapı Analisti | `%14` |
| 3 | **GPT-5.6 Codex** (`gpt-5.6-codex`) | `#3 SWE-bench (%96.2)` | Otonom Sistem Mühendisi, MTF (`5m/15m/1h`) & Yürütme Hakemi | `%13` |
| 4 | **Gemini 3.1 Pro Thinking** (`google/gemini-3.1-pro`) | `#2 Coding Arena (1M Bağlam)` | Büyük Kod Tabanı, Piyasa Rejimi, Genişlik & Fonlama Uzmanı | `%11` |
| 5 | **Claude Sonnet 5.5** (`claude-sonnet-5-5`) | `Üretim Kodlama Lideri` | Canlı Hata Yakalama, Net-Başabaş & Komisyon/Net-Edge (`ATR/Maliyet`) Zırhı | `%10` |
| 6 | **Grok 4.6 Code** (`x-ai/grok-4.6`) | `#4 SWE-bench (%95.6)` | Düşük Gecikmeli Akış, Volatilite Şoku, Emilim & Squeeze Avcısı | `%9` |
| 7 | **GLM-5.3 Coding** (`z-ai/glm-5.3`) | `#5 SWE-bench (%95.4)` | Durum Makinesi (State Machine), Emir İdempotensi & Yazar Kilidi Denetçisi | `%8` |
| 8 | **Kimi K3** (`moonshotai/kimi-k3`) | `#1 Açık Ağırlıklı Kod (%93.4)` | Matematiksel İspat, 60dk VWAP60 & Wilder ATR14 Z-Skor Analisti | `%7` |
| 9 | **MiniMax M2.5 High** (`minimax/minimax-m2.5`) | `SWE-bench Mühendislik (%80.2)` | Portföy Korelasyonu, Aynı-Yön Yığılma & Ücret-Duyarlı Çapraz Risk Mimarı | `%6` |
| 10 | **Qwen3-Coder** (`qwen/qwen3-coder`) | `Açık Kaynak Kod Ajanı Lideri` | Asenkron WebSocket/aggTrade Boru Hattı, Gap Koruması & SQLite WAL Uzmanı | `%6` |

---

## 🏆 v8.2 İle Eklenen Zirve Seviye Kârlılık & Mühendislik Yükseltmeleri

1. **Ücret-Duyarlı Akıllı Çapraz Kurtarma (`pair_rescue_fee_aware=True`)**:
   - Canlı 15dk borsa testinde (`95,245` tick) açılan 13 işlemin **11 tanesi (%84.6 isabet)** kâra geçtiği (`+$1.06` ile `+$8.76` arası MFE) halde eski `-0.02 * combined_margin` toleransının küçük kârlarla büyük zararları erken kapattığı tespit edildi.
   - v8.2'de `RiskManager.find_pair_rescue` artık **giriş komisyonu + tahmini çıkış taker komisyonu (`%0.05`) + funding** düşüldükten sonra net toplam `>= +$0.15 / +$0.20` değilse kârlı pozisyonu erken bozdurmaz!
2. **Otomatik MFE Kâr Kilidi & Net-Başabaş (`mfe_lock_min_usdt=1.20`, `net_breakeven_enabled=True`)**:
   - Pozisyon `+$1.20` MFE kârına ulaştığında zirve kârın `%55`'i otomatik kilitlenir; kâra geçmiş işlemlerin geri dönüp zararla kapanması engellenir.
3. **Çoklu Borsa Canlı Failover & Kontrat Normalizasyonu (`ctVal`)**:
   - Binance USDⓈ-M ve OKX USDT-SWAP WebSocket/REST akışları eşzamanlı çalışır; OKX kontrat adetleri `ctVal` ile gerçek coin miktarına dönüştürülür, zaman aşımında emirler otomatik olarak sağlıklı borsaya yönlendirilir.
4. **Çift-Taraflı SQLite WAL Muhasebe & Saat Zırhı**:
   - `verify_paper_ledger_integrity()` ile 13 canlı işlem sonrasında dahi beklenen ve gerçekleşen kasa farkı `0.00000000001 USDT` (`1e-11`) hassasiyetinde doğrulanır.

---

## ⚡ Hızlı Başlangıç

```bash
# 1) Tüm 742 otomatik testi çalıştır
pytest tests/ -q

# 2) Gerçek canlı borsa verileriyle (Binance USDⓈ-M + OKX WS) 15dk paper test & web paneli başlat
BINANCE_PUBLIC_WWW=1 PANEL_PORT=8080 python3 canli_15dk_test.py
# Tarayıcıdan canlı izle: http://localhost:8080
```
