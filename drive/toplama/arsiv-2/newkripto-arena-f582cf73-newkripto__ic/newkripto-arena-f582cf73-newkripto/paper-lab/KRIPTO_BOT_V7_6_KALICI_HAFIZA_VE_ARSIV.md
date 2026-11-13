# 🛡️ KRIPTO-BOT v7.6 — Kalıcı Sistem Hafızası, İşlem Veritabanı & Bağımsız Kurtarma Kılavuzu

- **Model Sürümü:** `KRIPTO-BOT v7.6`
- **Kayıt Tarihi:** `25.10.2026`
- **Doğrulama:** `263 / 263` Test Başarılı (`135/135 pytest -W error` + `101/101 test_hizli.py` + `27/27 test_bot_v7.py` + `0` lint hatası)
- **GitHub Bağımsız Yedek Konumları (Bu Arena Sayfasında Kalıcı Kayıtlı):**
  1. **Tam Proje + Veritabanı ZIP Paketi:** `backups/KRIPTO-BOT-v7.6-TAM-YEDEK.zip`
  2. **Git Yama (Patch) Dosyası:** `backups/KRIPTO-BOT-v7.6.patch` *(ve `backups/KRIPTO-BOT-v7.5-to-v7.6.patch`)*
  3. **Kalıcı SQLite İşlem & Oturum Veritabanı:** `backups/kriptobot_kalici_hafiza.db` (`5` tam oturum + `138` işlem + `v7.6` model anlık görüntüsü)
  4. **Taşınabilir JSON İşlem Veritabanı:** `paper-lab/tum_islemler_ve_oturumlar.json`

---

## 1. Tüm Canlı Denemelerin Kalıcı Özeti (138 Gerçek İşlem Kanıtı)

| Run ID | Tarih (UTC) | Süre | Başlangıç | Net K/Z | İşlem (K/Z) | Temel Bulgu |
|---|---|---:|---:|---:|---:|---|
| **`40077757773`** | `24.10.2026` | `2.0s` | `$100,000` | **`+$43.31`** *(Bot: `+$95.60`)* | `85` (`39W/46L`) | `KÂR KOŞUSU` **20/20 = `+$98.01` net (%100 isabet)**. |
| **`40090692312`** | `24.10.2026` | `1.0s` | `$1,000` | `-$3.05` | `9` (`2W/7L`) | Sığ altcoin `LIGHT/USDT` yanlışlıkla global sigorta attırdı *(Çözüldü: yalnız BTC/ETH)*. |
| **`40174169361`** | `25.10.2026` | `1.0s` | `$1,000` | **`+$31.89`** *(Saf Kripto: `+$36.71`)* | `20` (`13W/7L`) | Saf kriptoda `%81.2` WR, `KÂR KOŞUSU` **7/7 = `+$30.36` net**. |
| **`40179959680`** | `25.10.2026` | `1.0s` | `$1,000` | `-$35.06` | `11` (`0W/11L`) | Soğuk başlangıç + `RSI 23–27` dip SHORT + `%60` marj kilidi *(Çözüldü)*. |
| **`40188084750`** | `25.10.2026` | `1.0s` | `$1,000` | `-$8.77` *(Shadow: **`+$12.89`**)* | `13` (`6W/7L`) | Çapraz Kasa `0` kilitlenmeyle çalıştı; `technical-harmony` **`+$12.89`**, `pdf-confluence` **`+$9.03`**, `net-exit` **`+$4.99`** net kâr yazdı (`RLS/USDT LONG +$11.21`). |

---

## 2. KRIPTO-BOT v7.6 Mimari Kuralları (Nihai Model)

1. **%100 Saf Kripto USDT-M Perpetual Futures (`src/futures_catalog.py`):**
   - ABD/Asya hisse senetleri (`AAPL`, `NVDA`, `TSLA`, `AAOI`, `COHR`, `LITE`, `VRT`, `ALAB`, `SMCI`, `COIN`, `MSTR`, `MARA` vb.), kaldıraçlı ETF/ETP'ler, endeks, emtia ve döviz pariteleri %100 kara listededir.
2. **Gerçek Çapraz Ortak Kasa (`marj_modu: "cross"` — `src/risk.py`, `src/executor.py`):**
   - `Ortak Özsermaye = Cüzdan Bakiyesi + Açık Pozisyon Kâr/Zararı`.
   - Açık işlemler kâra geçtiği anda kasa `$1,000` üstüne büyür; kâr kilidine (`locked_profit`) giren pozisyonların risk teminatı ortak kasada `$0` sayılır.
   - Kasa `%95` dolsa bile `firsat_takasi_aktif: true` ile `8+ dk` durgun bekleyen işlem takas edilerek yeni sinyale yer açılır (`0` kilitlenme).
3. **WebSocket Anlık Para Girişi / Para Çıkışı Tetiği + Kanıtlı Giriş Filtreleri (`src/main.py`, `src/trade_quality.py`):**
   - İlk `90 sn` evren ısınması + `Flow-Confidence v2` (`>= 60 sn` kapsama, `>= 10` işlem, `>= $2,500` hacim, `<= 15 sn` taze defter).
   - **Canlı `Range-Confirmation` (`yatay_akis_engeli_aktif: true`):** `RANGE` (yatay) rejimde yalnız para akışıyla giriş engellenir.
   - **Canlı `Technical-Harmony` (`teknik_uyum_aktif: true`):** Karşıt teknik indikatör sayısı `<= 1` ve yönlü teknik skor `>= 24.0` olmadan giriş açılmaz.
   - **RSI/MFI Dip-Tepe Tükenme Kalkanı** ve **`TOP_TRADER` Akıllı Para Tuzak Kalkanı** aktiftir.
4. **2 Kademeli Net Kâr Kalkanı + `28/28` Kâr Koşusu (`src/risk.py`, `src/exit_rules.py`):**
   - **`erken_bozulma_cikisi_aktif: false`:** Geçici geri çekilmelerde zararına panik çıkışı kapalıdır.
   - **1. Kademe Kalkan (`+%0.50` / `+$2.50` brüt):** Stop anında komisyon üstü net kâra (`+%0.12`) kilitlenir (`+$2.50` gören işlem bir daha eksiye dönemez!).
   - **2. Kademe Kalkan (`+%0.90` / `+$4.50` brüt):** Stop `+%0.30` (`+$1.50` brüt / `+$1.00` net) seviyesine yükseltilir.
   - **Asıl Hasat (`KÂR KOŞUSU`):** Zirveden order-flow + CVD dönüşü geldiğinde üst sınırsız kârı toplar.

---

## 3. GitHub Olmadan Sıfırdan Kurulum & Çalıştırma (Acil Kurtarma)

Bu Arena sayfasındaki `backups/KRIPTO-BOT-v7.6-TAM-YEDEK.zip` dosyasını indirip herhangi bir sunucuda (Ubuntu/Debian/macOS/Windows WSL) şu 4 komutla doğrudan çalıştırabilirsin:

```bash
unzip KRIPTO-BOT-v7.6-TAM-YEDEK.zip -d newkripto
cd newkripto
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m src.main
```

Veritabanını güncellemek veya sorgulamak için:
```bash
.venv/bin/python -m src.master_archive
sqlite3 backups/kriptobot_kalici_hafiza.db "SELECT run_id, net_pnl_usdt, closed_count, win_rate_pct FROM sessions;"
```
