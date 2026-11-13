# KRIPTO-BOT v7.3 — Kalıcı Sistem Mimarisi, Kurallar ve Oturum Hafıza Kaydı

> **Son Güncelleme:** 2026-10-25 (TSİ)
> **Aktif Dal:** `arena/9f6488eb-newkripto` (`omeraca56/newkripto`)
> **Doğrulanmış Test Kapsamı:** `125 / 125` pytest testi başarılı (`tests/test_v73_upgrades.py` dahil)

---

## 1. Çekirdek Kasa, Boyutlandırma ve Risk Kuralları

| Parametre | Aktif Değer | Açıklama |
|---|---|---|
| **Mod & Borsalar** | `paper` (`binance` + `okx`) | Çift borsa eşzamanlı canlı WebSocket + Multi-Exchange Failover |
| **Başlangıç Paper Kasası** | `$1,000.00 USDT` | Kontrollü 60 dk / 120 dk test profili (`configs/paper-60-v2-control.json`) |
| **İşlem Başına Marj** | **Sabit `$50.00 USDT`** | Kademesiz (`max_kademe: 1`), sabit `$50` marj |
| **Kaldıraç** | **Sabit `10x`** | Pozisyon büyüklüğü `$500 USDT` |
| **Başlangıç Zarar Kes (SL)** | **`$40.00 USDT`** | Marjın `%80`'i (`marj_zarar_orani: 0.80`), likidasyon mesafesinin önünde |
| **Toplam Marj Tavanı** | **`%60.0`** | Kasadaki bakiyenin en fazla `%60`'ı marj olarak bağlanır (`%40` nakit tamponu korunur) |
| **Günlük / Haftalık Zarar Tavanı** | `%5.0` / `%12.0` | Aşıldığında `CircuitBreaker` yeni girişleri otomatik durdurur |
| **Üst Zaman Dilimi (MTF) Filtresi** | `1h` + `4h` aktif | Ana trend düşüşteyken (`<= -15`) ters LONG, yükselişteyken (`>= +15`) ters SHORT engellenir |

---

## 2. 1 Saatlik İlk Canlı Test Özeti (`Run #40174169361`) ve Öğrenilen Bulgular

- **Tarih / Süre:** `2026-10-25 10:48:26 – 11:49:24 TSİ` (60 dakika tam oturum)
- **Sonuç:** `$1,000.00 -> $1,031.89 USDT` (**Net `+$31.89` / `+%3.19`**, Brüt `+$41.84`, Komisyon `-$9.98`, Funding `+$0.03`)
- **İstatistik:** `20` açılan / `20` bot-kapanış (`0` açık, `0` süre-sonu zoraki kapanış), **`%65.0` Net Win Rate (13K / 7Z)**, **Profit Factor `4.23`**, **Max DD `$7.21` (`%0.72`)**
- **En Güçlü Çıkış Motoru:** `KÂR KOŞUSU — ORDER-FLOW DÖNÜŞÜ` **`7/7` (`%100` isabet)** ile net **`+$30.36`** üretti.
- **Tespit Edilip v7.3'te Kapatılan 5 Eksik:**
  1. **Flash Crash Kapsam Sorunu (`LIGHT/USDT %8.20`):** Portföyde bulunmayan sığ bir altcoinin `%8.20` hareketi tüm portföyü kapatmıştı. **Çözüldü:** Global Flash Crash sigortası artık yalnızca **`BTC/USDT` ve `ETH/USDT`** şoklarında tüm portföyü kapatır (`sigorta.global_sok_sembolleri`); altcoin şokları ise yalnızca ilgili altcoinde açık pozisyon varsa o pozisyonu kapatır ve o sembolü `900 sn` (15 dk) molaya alır.
  2. **Kripto-Dışı Sentetik Kontrat Sızıntısı (`-$4.82`):** `AMZN`, `US500`, `CSOPSAMSUNG2L`, `BITO` gibi düşük volatiliteli sentetik hisse/endeks/ETF kontratları 7 zararın 4'ünü oluşturmuştu (saf kripto paritelerde `%81.25` WR, `+$36.71` net kâr). **Çözüldü:** `src/futures_catalog.py` içinde `is_non_crypto_or_pegged_perp()` filtresi devreye alındı (`futures.kripto_disi_filtre: true`).
  3. **İkiz Dayanak Varlık Çakışması (`SATS` + `1000SATS`):** OKX'te `SATS/USDT` açıkken Binance'te `1000SATS/USDT` açılmıştı. **Çözüldü:** `canonical_underlying_asset()` ile `1000*` / `1M*` çarpanlı ikiz semboller ortak köke indirgenerek aynı anda çifte pozisyon açılması engellendi (`sinyal.ikiz_varlik_korumasi: true`).
  4. **Düşük Volatilite & Komisyon-Altı Trailing Sızıntısı:** Shadow Lab şampiyonları olan **`volatility-gate`** (`sinyal.min_bb_genisligi_yuzde: 0.20`, `min_atr_yuzde: 0.10`) ve **`net-exit`** (`cikis.net_basabas_aktif: true`, `net_kar_tamponu_usdt: 0.05`) canlı motora entegre edildi.
  5. **Shadow `flow-confidence` Emir Defteri Alan Hatası & Likidasyon Bildirim Gürültüsü:** `MoneyFlow.depth_snapshot()` içine `book_levels` eklendi (`20` kademe) ve Telegram `LONG_SQUEEZE / SHORT_SQUEEZE` bildirimlerine minimum `$25,000` tekil tasfiye + `300 sn` sembol bazlı mola eklendi (strateji değerlendirmesi anlık çalışmaya devam eder).

---

## 3. PDF v2 + PDF v3 İndikatör ve Ücretsiz Türev İstihbarat Mimarisi

1. **Çekirdek Sinyal & Mikro-Yapı (`src/indicators.py`, `src/moneyflow.py`, `src/strategy.py`):**
   - EMA Trend, Supertrend iz takibi, ADX/DI, Donchian + Hacim Z-Skoru kırılımı, Taker Delta, CVD Eğimi & Uyumsuzluk, Emilim (Absorption), 20 Kademe Ağırlıklı OBI, Gerçek Tick VPVR (`POC/VAH/VAL`), Açık Faiz (OI) Matrisi, Numpy GBDT ML Tahmincisi.
2. **PDF v2 Paketi (`src/pdf_indicators.py`):**
   - KAMA, HMA, DEMA, TEMA, TRIX, WaveTrend, Squeeze Momentum, Connors RSI, Waddah Attar Explosion, Choppiness, Hurst Üssü, Parkinson & Garman-Klass Volatilite, Fair Value Gap (FVG), Piyasa Yapısı (BOS/CHoCH).
3. **PDF v3 Paketi (`src/pdf_v3_prep.py` + `src/derivatives_intel.py`):**
   - **Adaptif Ortalamalar & Bantlar:** Wilder RMA, Tillson T3, Ehlers FRAMA, Chande VIDYA, Jurik-tipi JMA yaklaşımı, 8'li EMA Ribbon istif/genişleme skoru, Elder SafeZone Stop.
   - **İstatistiksel Rejim & Likidasyon Haritası:** Getiri çarpıklık/basıklık + z-skor rejim sınıflandırıcısı, HVN/LVN hacim düğümleri, kaldıraç bazlı tahmini likidasyon kümeleri (`magnet_bias`), BTC makro rejim ve 60-mum korelasyon bağlamı.
   - **Ücretsiz Public Türev İstihbaratı (`DerivativesIntelEngine`):** Binance + OKX Mark–Index Basis (%), Cross-Exchange Funding farkı (bps), Global L/S & Top Trader L/S oranı, Taker Buy/Sell oranı ve Deribit DVOL / Put-Call şeması. **Perakende aşırı kalabalık + Top Trader ters ayrışma tuzağını** canlı girişlerde otomatik filtreler (`pdf_v3.asiri_kalabalik_engeli: true`).
   - **Shadow Lab 8. Kohort (`pdf-v3-confluence`):** Tüm PDF v3 + türev oylarını izole sanal kasada eşzamanlı ölçer.

---

## 4. Operasyonel Komutlar ve İş Akışı

- **Testleri Çalıştırma:** `.venv/bin/pytest -v`
- **60 Dakikalık Canlı Paper Oturumu Başlatma:** `configs/paper-60-v2-request.json` dosyasını güncelleyip `arena/9f6488eb-newkripto` dalına pushlamak (`.github/workflows/paper-live.yml` otomatik tetiklenir, Telegram `getMe` + `sendMessage` ve çift borsa ön-kontrolünü doğrular, bitişte `analysis/run_<RUN_ID>/` kanıt dosyalarını dala yazar).
- **Acil Durdurma:** Telegram üzerinden `/kill` veya `/durdur`, ya da `configs/paper-stop-request.json` pushlamak.
