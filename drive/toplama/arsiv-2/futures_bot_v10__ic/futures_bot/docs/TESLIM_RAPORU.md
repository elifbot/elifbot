# TESLİM RAPORU — futures_bot (Paper-Only Vadeli İşlem Araştırma Botu)

**Tarih:** 2026-10-27 · **Sürüm:** 1.0.0
**Kaynak:** Crew projesi `binance_okx_paper_futures_bot` (v1) görev tanımları

---

## 1. UYGULANANLAR

### Phase A — Çekirdek (tam çalışır)
- `main.py`: CLI, oturum zamanlayıcısı, `(exchange, symbol)` anahtarlı durum,
  heartbeat logu, mod koruması (`live`/`testnet` → `exit 1`).
- `config.py`: tüm sabitler + 4 uç noktalı allowlist.
- `data/`: Binance FAPI ve OKX V5 public feed'leri; `confirm == "1"` filtresi,
  `ctVal` hacim çevrimi, tick/step boyutu, 429/451/timeout davranışı.
- `indicators/`: EMA şeridi (düzeltilmiş yön), SMA, Bollinger (ddof=1),
  RSI (Wilder), MACD, ATR (Wilder), ADX/+DI/−DI, Stoch-RSI, Supertrend;
  ayrıca OBV, Session VWAP, MFI, CCI, Williams %R, Donchian, Keltner,
  BB-Keltner squeeze, hacim z-skoru.
- `strategies/`: üç aday — trend takip (A), ortalamaya dönüş (B),
  sıkışma kırılımı (C); **üçü de `SHADOW`**; her örnek kendi durumuna sahip;
  aile bazlı ablasyon anahtarı (`disabled_families`).
- `portfolio/paper_futures.py`: LONG/SHORT, marj, komisyon, limitler,
  likidasyon koruması, günlük zarar limiti, bayat fiyat koruması.
- `logger/`: allowlist'li CSV (funding = `bilinmiyor`).
- `reports/`: PnL raporu; Sharpe < 30 işlemde bastırılır.

### Phase B — Gösterge envanteri
`indicators/catalog.py`: A–G ailelerinde **64 gösterge**, her biri
`input_columns`, `period_warmup`, `data_source`, `status`
(`ACTIVE`/`SHADOW`/`MISSING`/`DATA_UNAVAILABLE`), `last_verified_date` ile.

### Phase C — Genişletilmiş veri (stub)
`funding_feed.py`, `oi_feed.py`, `markprice_feed.py` → hepsi
`DataUnavailableError("… unverified or unavailable")` fırlatır.
Funding hiçbir PnL hesabına **dahil edilmez**.

### Phase D — Backtest
- `backtests/engine.py` — mum-mum besleme, lookahead koruması, aynı
  `PaperPortfolio` ile muhasebe.
- `backtests/walk_forward.py` — pencere planı + parametre izi (SHA-256).
- `backtests/ablation.py` — aile ayrıştırma (BASE + A/B/C/D).
- `backtests/report.py` — tablo çıktıları, uyarı metinleriyle.

### Ek
- `run_backtest.py` — tek komutla backtest + walk-forward + ablasyon.
- `scripts/make_synthetic_fixture.py` — açıkça "SENTETİK" etiketli veri üretimi.
- `crew/` — güncellenmiş CrewAI projesi (`FileWriterTool` ile).

## 2. EKSİKLER

| Eksik | Neden | Etki |
|---|---|---|
| Funding / OI / mark price | Uç noktalar doğrulanmadı | PnL funding **hariç**; etiketli |
| Binance canlı veri | Ortamdan **451** | Binance yolu yalnızca mock ile test edildi |
| Emir defteri / CVD / likidasyon | Public erişim doğrulanmadı | F ailesi sinyalde kullanılmıyor |
| Sentiment | Doğrulanmış public kaynak yok | G ailesinde `MISSING` |
| Sharpe | 30+ kapalı işlem gerekir | Kısa oturumlarda "hesaplanamaz" |
| Sembol çakışma filtresi | Binance engeli | Kural var, canlı doğrulama yok |
| Otomatik tetikleyici | Bilinçli olarak yok | `run_with_trigger` bilinen sorun |

## 3. GERÇEKTEN ÇALIŞTIRILAN TESTLER VE ÇIKTILARI

**Komut:** `python -m pytest -q`

```
119 passed in 3.09s
```

Kapsam (11 test dosyası, 1.357 satır): PnL muhasebesi (18), göstergeler (14),
stratejiler (11), veri yardımcıları (14), feed'ler (13, ağ mock'lu), raporlar (8),
log (5), güvenlik (9), oturum/CLI (10), backtest (9), conftest.

**Formül doğrulaması (kod içi assertion, her açılışta çalışır):**

```
LONG  5 birim, 100 → 101, taker %0.05  →  net +4.4975  ✔
SHORT 5 birim, 100 →  99, taker %0.05  →  net +4.5025  ✔
```

**Bağımlılık taraması:** `pip-audit -r requirements.txt` →
`No known vulnerabilities found`.

**Ablasyon (sentetik veri, strateji A):** A ailesi kapatıldığında işlem
sayısı 4 → 40'a çıktı, ΔPnL +0.1436; B ailesi kapatıldığında ΔPnL +0.2312.
**Yorum:** A ve B kısıtlayıcı; ancak örneklem küçük, bu bir nedensellik
kanıtı değildir.

**Gerçek veri (OKX BTC-USDT-SWAP, 299 mum, 27 Eki 11:30–16:28 UTC):**
backtest → 3 işlem, net **−2.7910 USDT**, MDD 2.7910, Sharpe bastırıldı.

**Canlı paper oturumu (60 dk, OKX BTC + ETH):** `logs/live_run.log`
içinde dakikalık heartbeat. Sonuçlar oturum kapandığında
`live_report.txt` + `live_trades.csv` dosyalarına yazılır.

## 4. ÇALIŞTIRILMAYANLAR

- Crew'in kendisi (`crewai run`) — `OPENAI_API_KEY` yok, maliyetli API çağrısı
  gerektirir. Bot kodu crew'e bağımlı olmadan üretildi.
- Binance canlı feed testi — 451 bölgesel engel.
- Gerçek emir — **tasarım gereği yok**.
- Uzun süreli (gün/hafta) backtest — elde 299 dakikalık gerçek veri var.
- **KRIPTO-BOT v7.8 çalıştırılmadı** — yalnızca statik olarak okundu
  (`mod=paper|testnet|live` destekliyor ve gerçek emir gönderebiliyor;
  bu yüzden çalıştırmak gerçek para riski taşıyordu).

## 5. GÜVENLİK / RİSK SINIRLARI

- Yalnızca **4 public GET** uç noktası; allowlist koda gömülü ve test ediliyor.
- Kimlik bilgisi yok, `os.environ` erişimi yok, `.env` okunmuyor.
- `--mode live|testnet` → ağ çağrısından **önce** `exit 1` (test edildi).
- İzole marj varsayımı: bakiye negatife düşemez (likidasyon koruması).
- Tüm sonuçlar paper; funding **bilinmiyor**; Sharpe < 30 işlemde bastırılır.
- Detaylı 13 kategori: `docs/GUVENLIK_DENETIMI.md`.

## 6. GÖSTERGE ENVANTERİ (özet)

| Aile | Gösterge | ACTIVE | SHADOW | MISSING | DATA_UNAVAILABLE |
|---|---|---|---|---|---|
| A Trend | 13 | 3 | 10 | 0 | 0 |
| B Momentum | 14 | 2 | 12 | 0 | 0 |
| C Volatilite | 10 | 4 | 6 | 0 | 0 |
| D Hacim | 9 | 2 | 7 | 0 | 0 |
| E Yapı | 7 | 0 | 7 | 0 | 0 |
| F Mikroyapı | 7 | 0 | 0 | 4 | 3 |
| G Bağlam | 3 | 0 | 2 | 1 | 0 |

Tam liste: `python main.py --show-catalog`.

## 7. KAYNAK VE ARAÇ ERİŞİMİ

| Kaynak | Durum |
|---|---|
| OKX public API | ✅ 200 (canlı doğrulandı) |
| Binance FAPI | ❌ 451 (bölgesel kısıtlama) |
| PyPI / pip-audit | ✅ çalıştı |
| GitHub API | ✅ erişilebilir (kimlik bilgisi yok) |
| CrewAI çalıştırma | ❌ API anahtarı yok |
| Freqtrade / Hummingbot kaynak kodu | ❌ incelenmedi (yalnızca doküman bilgisi) |
| KRIPTO-BOT v7.8 ZIP | ✅ **AÇILDI ve İNCELENDİ** (78 dosya, 24.047 satır) — bkz. `docs/V78_KARSILASTIRMA.md` |

## 8. TESLİM EDİLEN DOSYALAR

```
futures_bot/
├── main.py, config.py, run_backtest.py, setup.py
├── requirements.txt, requirements-dev.txt, README.md
├── data/            (7 dosya; extended/ stub'ları dahil)
├── indicators/      (core, volume, catalog)
├── strategies/      (base, 3 aday, composite)
├── portfolio/       paper_futures.py
├── logger/          trade_logger.py
├── reports/         pnl_report.py
├── backtests/       engine, walk_forward, ablation, report, engine_interface
├── scripts/         make_synthetic_fixture.py
├── tests/           11 dosya — 119 test
├── data/fixtures/   sentetik + GERÇEK OKX snapshot'ları
├── docs/            VERI_ARASTIRMA_RAPORU, GUVENLIK_DENETIMI,
│                    CREW_ZIP_FARK, V78_KARSILASTIRMA, TESLIM_RAPORU
└── crew/            güncellenmiş CrewAI projesi (FileWriterTool)
```

### Hızlı başlangıç (3 komut)

```bash
pip install -r requirements.txt
python main.py --mode replay --replay-csv data/fixtures/synthetic_btc_1m.csv
python -m pytest -q
```
