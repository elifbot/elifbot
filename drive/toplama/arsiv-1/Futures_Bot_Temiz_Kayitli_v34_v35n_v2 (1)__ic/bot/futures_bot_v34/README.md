# futures_bot — Paper-Only Çok Göstergeli Vadeli İşlem Araştırma Botu (v18)

> ⚠️ **PAPER-ONLY.** Bu proje gerçek emir GÖNDERMEZ, kimlik doğrulamalı hiçbir
> uç nokta çağırmaz, API anahtarı istemez veya saklamaz. Çıktıların tamamı
> simülasyondur ve yatırım tavsiyesi değildir.

> 🎯 **KAPSAM: SADECE KALDIRAÇLI KRİPTO VADELİ İŞLEM.**
> Binance USDⓈ-M **PERPETUAL** + OKX **USDT-SWAP**. Spot işlem yoktur,
> ABD hisse/ETF/emtia/pre-IPO kontratları taranmaz.

Binance USDⓈ-M Futures ve OKX USDT-linear SWAP **public** verisiyle çalışan,
çok göstergeli bir araştırma botu. Üç aday strateji `SHADOW` durumundadır;
yani hiçbiri "kârlı" veya "aktif" kabul edilmez, yalnızca gözlemlenir.

### Güncel v17: iki-borsa akış gölgesi ve doğal çıkış bekleme

```bash
python3 ws_bot.py --sure-dk 15 --cikis-tamamlama-dk 10 --akis-golge
```

`--akis-golge` OKX ve Binance üretim gerçek taker işlemlerinden ayrı bir
CVD15+VWAP60 / ATR paper gölgesi çalıştırır; varsayılan kapalıdır ve ana
baseline'ı değiştirmez. Aynı base varlığın iki borsadaki sinyalinde yalnız bir
gölge aday/pozisyon bulunur. `--cikis-tamamlama-dk` tarama sonunda yeni girişleri
keser ve açık pozisyonlara üst süre sınırlı doğal çıkış olanağı verir; süre de
dolarsa kalanlar `drain_end` olur. Ayrıntı ve doğrulama sonuçları:
[`V17_NOTLARI.md`](V17_NOTLARI.md).

---

## 1. Kurulum

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt                 # yalnızca test için
```

Gereksinim: Python 3.10+ (`requests`, `pandas`, `numpy`, `tabulate`).

## 2. Hızlı başlangıç (3 komut)

```bash
pip install -r requirements.txt
python main.py --mode replay --replay-csv data/fixtures/synthetic_btc_1m.csv
python -m pytest -q
```

Canlı public veriyle paper oturumu:

```bash
python main.py --mode paper --pairs "okx:BTC-USDT-SWAP,okx:ETH-USDT-SWAP" --duration-min 60
```

Backtest + walk-forward + ablasyon:

```bash
python run_backtest.py --csv data/fixtures/okx_BTC-USDT-SWAP_1m_real_snapshot.csv --strategy trend
```

## 3. CLI

| Bayrak | Açıklama |
|---|---|
| `--mode paper\|replay` | `live` ve `testnet` **reddedilir** (`exit 1`) |
| `--duration-min N` | Oturum süresi (varsayılan 60) |
| `--pairs "okx:BTC-USDT-SWAP,..."` | Boşsa `config.EXCHANGE_SYMBOL_PAIRS` |
| `--scan` | Hacim odaklı tarama modu (alfabetik değil) |
| `--scan-fetch N` | Mum verisi çekilecek aday sayısı (vars. 12) |
| `--scan-pick N` | İşlem için seçilecek sembol sayısı (vars. 3) |
| `--scan-log PATH` | Tarama tablosu CSV'si (vars. `logs/scan_log.csv`) |
| `--replay-csv PATH` | Replay modu için CSV (`open_time,open,high,low,close,volume`) |
| `--log-path PATH` | İşlem CSV'si (varsayılan `trades.csv`) |
| `--report-path PATH` | PnL raporu (varsayılan `pnl_report.txt`) |
| `--show-catalog` | Gösterge envanterini (A–G) yazdırır |
| `--verbose` | DEBUG seviyesinde log |

## 4. Veri kaynakları

Temel `main.py` veri yolunda allowlist'li dört public REST uç noktası kullanılır
(`config.py`):

- `https://fapi.binance.com/fapi/v1/klines`
- `https://fapi.binance.com/fapi/v1/exchangeInfo`
- `https://www.okx.com/api/v5/market/candles`
- `https://www.okx.com/api/v5/public/instruments`

Sürekli tarayıcı `ws_bot.py` ayrıca OKX public WebSocket kanallarını, Binance
public market/ticker REST uç noktalarını ve üretim
`wss://fstream.binance.com/market/stream` aggTrade kanalını kullanır. Bunların
hiçbiri kimlik doğrulamalı değildir. Hiçbir istek `POST/PUT/DELETE` değildir;
hiçbir istekte imza/anahtar yoktur.

> **Bölgesel erişim notu:** Bu geliştirme ortamında **Binance 451** (bölgesel
> kısıtlama) döndürmektedir; **OKX erişilebilir** durumdadır. Deneme oturumları
> OKX üzerinde yapılmıştır. Ayrıntı: `docs/VERI_ARASTIRMA_RAPORU.md`.

## 4b. Hacim odaklı tarama (`--scan`)

Sabit liste yerine **piyasadan sembol seçen** mod. Sıralama **alfabetik değildir**.

```bash
python main.py --mode paper --scan --scan-fetch 12 --scan-pick 3 --duration-min 60
```

### Nasıl seçiyor?

1. **Evren**: Binance `/fapi/v1/ticker/24hr` + OKX `/api/v5/market/tickers`
   (yalnızca vadeli). Ticker listesi `scanner/universe.py` içinde normalize edilir.
2. **Sadece kripto vadeli**:
   - Binance: `contractType == PERPETUAL`, `quoteAsset == USDT`, `status == TRADING`,
     `underlyingType == COIN`. `quoteVolume` doğrudan **USDT notional**'dır.
   - OKX: `-USDT-SWAP` **ve** base paritesinin OKX **spot** piyasasında `-USDT`
     paritesi bulunmalı. Hisse/emtia kontratlarının (SNDK, SOXL, SKHYNIX, XAU, CL…)
     spot paritesi yoktur → elenir. Bu filtre canlı doğrulandı:
     tek turda **268 kontrat** "spot_paritesi_yok" + **25** "hisse_denylist"
     gerekçesiyle elendi.
   - Ayrıca `STOCK_LIKE_DENYLIST` ikinci savunma katmanı olarak çalışır.
3. **USD hacim**: OKX `volCcy24h × last`, Binance `quoteVolume`.
   ⚠️ Ham `volCcy24h` ile sıralama YANLIŞTIR: SATS'ta 2,99e13 görünür ama
   USD karşılığı yalnızca ~$303 bin; BTC'de ise $4,5 milyar.
4. **Aday seçimi = hacim liderleri + en çok hareket edenler.** Yalnızca hacme
   bakmak, patlamasını yeni yapmış coinleri kaçırır (ör. BTW 24s +%66 ama
   hacim sıralamasında 15.).
5. **Spike ölçümü** (her aday için 1m mumlar):

   | Ölçüt | Formül | Varsayılan eşik |
   |---|---|---|
   | `rvol` | son mum hacmi / son 60 mumun **medyan** hacmi | ≥ 2.0 |
   | `volume_z` | son hacmin z-skoru (ddof=1) | bilgi amaçlı |
   | `ret_k` | son **5 mumdaki** % fiyat değişimi | \|ret\| ≥ 0.35% |
   | `range_exp` | son mum aralığı / ATR(14) | bilgi amaçlı |
   | `spike_score` | \|ret_k\| × min(rvol,10)/10 × range_exp | sıralama |

   `ANI_YUKSELIS` / `ANI_DUSUS` etiketi alanlar skora göre sıralanır, ilk
   `--scan-pick` tanesi strateji değerlendirmesine girer.

### Denetim izi
Her tur `logs/scan_log.csv`'ye yazılır: `ts_utc, symbol, last, rvol, volume_z,
ret_k_pct, range_expansion, spike_score, label`. Böylece "neden bu coin
seçildi / neden seçilmedi" sonradan kanıtlanabilir.

### Dürüst sınır
`ANI_YUKSELIS` sonrası hareketin **süreceği kanıtlanmamıştır**. İlgili aday
(`spike_momentum_D`) `SHADOW` durumundadır ve tek başına işlem kararı vermez.

## 5. Mimari

```
main.py                CLI, oturum döngüsü, mod koruması, heartbeat
config.py              tüm sabitler + allowlist
data/
  feed_utils.py        mum doğrulama, kapalı-mum filtresi, URL allowlist
  binance_futures_feed.py
  okx_swap_feed.py     confirm=1 filtresi + ctVal hacim çevrimi
  extended/            Phase C — funding / OI / mark price (DataUnavailableError)
indicators/
  core.py              EMA ribbon, Bollinger(ddof=1), RSI, MACD, ATR, ADX, Supertrend
  volume.py            OBV, VWAP, MFI, CCI, Donchian, Keltner, squeeze, volume z
  catalog.py           Phase B — A–G aile envanteri (ACTIVE/SHADOW/MISSING/DATA_UNAVAILABLE)
scanner/
  universe.py          hacim sıralı kripto-vadeli evren + hisse filtresi
  spike.py             rvol / hacim z-skoru / ani hareket etiketi
strategies/
  trend_follower.py    Aday A (SHADOW)
  spike_momentum.py    Aday D — ani hareket momentumu (SHADOW)
  mean_reversion.py    Aday B (SHADOW)
  squeeze_breakout.py  Aday C (SHADOW)
  composite.py         aile bazlı skor (aile başına cap)
portfolio/paper_futures.py   LONG/SHORT, marj, komisyon, limitler, likidasyon
logger/trade_logger.py       allowlist'li CSV
reports/pnl_report.py        PnL/Sharpe (n<30 bastırılır)
backtests/                   engine, walk_forward, ablation, report
```

## 6. Muhasebe kuralları (özet)

- Kaldıraç **yalnızca** miktarı belirler: `notional = margin × leverage`;
  PnL'e ikinci kez çarpılmaz.
- Giriş komisyonu marjla **tek adımda** düşülür: `balance -= (margin + entry_fee)`.
- Pozisyon limitleri **açılış sonrası** duruma göre kontrol edilir
  (toplam 6, aynı yönde 4 — sayım **borsa bazındadır**).
- Marj kullanımı ≤ %45; bakiye tabanı 100 USDT; günlük zarar limiti %5
  (özsermaye üzerinden ölçülür, kilitli marj zarar sayılmaz).
- **Sürekli `ws_bot.py` (v18):** risk limitleri varsayılan AÇIKTIR ve yukarıdaki
  config değerlerini kullanır (40 / 40 / %95 / bakiye tabanı 100 / günlük %5).
  Eski v13 limitsiz davranışı yalnızca açıkça `--risk-limitleri-kapali` ile
  seçilir ve durum JSON'unda `risk_limitleri: false` olarak görünür. Aynı base
  varlığı iki borsada mükerrer açmama koruması her iki modda da korunur.
  Ayrıca CLI varsayılanı %0,05 olumsuz kayma uygular (`--kayma-pct`) ve açık
  pozisyonlar `logs/ws_state.json` ile `--durum-devam` kullanılarak kurtarılabilir.
- İzole marj varsayımı: kayıp marjı aşarsa pozisyon likide sayılır, bakiye
  negatife düşmez.
- Referans doğrulama (kod içinde assertion): LONG `+4.4975`, SHORT `+4.5025`.

## 7. Bilinen sınırlamalar

- **Funding yok:** funding/OI/mark-price uç noktaları doğrulanmadı; tüm
  sonuçlar "funding hariç / bilinmiyor" etiketlidir. `funding_fee` alanı
  CSV'de `bilinmiyor` olarak yazılır — teyitli sıfır değildir.
- **Sharpe:** 30'dan az kapalı işlemde `hesaplanamaz — yetersiz veri`.
- **Sembol çakışması:** Binance `BB` (BounceBit) ile OKX `BB` (BlackBerry)
  farklı varlıklardır; borsalar hiçbir zaman birleştirilmez. Fiyat farkı
  >%1.5 olan çakışmalar uyarı üretir (bkz. `docs/VERI_ARASTIRMA_RAPORU.md`).
- **KNOWING ISSUE — `run_with_trigger`:** `pyproject.toml`'da (Crew projesinde)
  hedef fonksiyonu olmayan bir kısayol bulunur. Bu projede otomatik tetikleyici
  YOKTUR ve uygulanmamıştır; ilgili satır silinebilir veya yok sayılabilir.
- **Gerçek veri ≠ garanti:** 1 saatlik paper oturumu performans kanıtı değildir.
- Sinyal sıklığı düşüktür: Aday A dört koşulun aynı anda sağlanmasını ister
  (EMA şeridi + ADX ≥ 20 + MACD yönü + Supertrend). Saatlik ölçümlerde
  bağlayıcı kısıt genellikle ADX'tir.

## 8. Test

```bash
python -m pytest -q          # v17: 235 test
```

Testlerde tüm ağ çağrıları mock'lanmıştır; gerçek HTTP yapılmaz.
