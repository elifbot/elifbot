# ACARBOT v4.0 — Değişiklik Günlüğü (7 Kasım 2026)

Girdi: kullanıcının Faz listesi (Faz 1: v1.7 birleştirmesi — v3.1'de
tamamlandı; Faz 2: HTML'deki özellikler; Faz 4: doğrulama/yayına alma) ve
**"bunları da incele, en son final sürüme geçelim"** talimatı.

Yöntem: her madde tek tek incelendi; uygulanabilir olanlar v3.1 mimarisine
uyarlandı, uygulanamayacaklar **gerekçesiyle "uygulanmadı" olarak
belgelendi** (sahte yer tutucu YOK). Mevcut davranış korundu: **208 v1.2
testi hiç değişmeden geçer**; toplam **483/483 test** (208 v1.2 + 118
v2/v3 + 63 v3.1 + 94 v4.0).

---

## 1. Faz 1 — v1.7 birleştirmesi (v3.1'de tamamlandı)

`--scan-all`, `--motors`, baz hacim düzeltmesi, bayat sinyal koruması,
CLI eşikleri — bkz. `DEGISIKLIKLER_FINAL_v3.1.md`. Bu sürümde aynen
korunur (63 v3.1 testi geçer).

## 2. Faz 2 — HTML'deki özellikler

### 2.1 Madde 6 — Confluence stratejisi (10 filtre, eşik ayarlı) ✅

`core/strategies_extra.py::ConfluenceEngine` — 10 filtre ağırlıklı oyu:
EMA20/EMA50, fiyat/EMA200 (kısa geçmişte EMA50 çapası), MACD histogram,
RSI bölgesi, RVOL onaylı mum yönü, 20 mumluk yapı kırılımı, BTC 15dk uyumu,
ATR genişlemesi, 3 mumluk momentum serisi, EMA20 eğimi. Puan [-1,1]
normalize edilir; `--confluence-threshold` (vars. 0.6) aşılırsa yön.
**Eşitlik nötr** (`_sign`): düz piyasada sahte ayı/boğa oyu yok.
Gerekçe şeffaf: red kodunda tüm filtre oyları görünür
(`confluence puan=0.42 < eşik 0.60 | ema20_ema50=+1 ...`).

### 2.2 Madde 7 — Seçilebilir stratejiler ✅

`--strategy classic|confluence|rsirev|macd|bollkir|bolldon`:

| Strateji | Motor | Mantık (özet) |
|---|---|---|
| classic | FADE/TREND + resolver (v1.2, varsayılan) | aynen korunur; v3.1 `--motors` kapısıyla birleşir |
| rsirev | RsiRevEngine | RSI<30 + yukarı dönüş → LONG; RSI>70 + aşağı dönüş → SHORT |
| macd | MacdEngine | MACD histogram sıfır kesişimi + RVOL kapısı |
| bollkir | BollBreakEngine | Bollinger (20,2) bant kırılımı + hacim + sahte kırılım filtresi |
| bolldon | BollRevEngine | bant dışı + RSI aşırı uç → ortalamaya dönüş |

Tümü pipeline'ın "temel sinyal" katmanına bağlanır → Hakem/MTF/skor/risk
kapıları AYNEN çalışır; canlı ve backtest aynı kural (tek kapı ilkesi).
Stop mesafesi ATR tabanlı, ExitConfig min/max fraksiyonuna kırpılır.

### 2.3 Madde 8 — DCA güvenlik emirleri ✅ (varsayılan KAPALI, yalnız LONG)

`--dca` ile açılır (`DcaConfig`: 2 güvenlik emri, ilk adım %1, adım 1.5x,
hacim 1.0x). Tetik: fiyat ortalama girişin adım altına düşer.
Güvenlik kuralları (fail-closed):
- YALNIZ LONG (SHORT'ta DCA sonsuz riskli taraftır — yapılmaz).
- DCA sonrası toplam net risk (maliyetler dâhil) **pozisyon başı 25 USDT
  tavanını aşamaz** → aşarsa DCA ATLANIR.
- Serbest bakiye ek marjı kaldıramıyorsa ATLANIR.
- **STOP FİYATI DEĞİŞMEZ** (risk zemini korunur).
- Canlı eşlemede DCA → borsaya market ek giriş (`mirror_dca`);
  koruyucu stop (closePosition/closeFraction) tüm pozisyonu kapsar.
- Muhasebe: taker ücreti + ek marj + ortalama giriş güncellenir;
  `dca_count` snapshot/restore ile kalıcıdır; raporda `DCA` kayıtları.

### 2.4 Madde 9 — Seans (saat) filtresi ✅

`--session off|asia|eu|us|"HH-HH"` (UTC): asia 00-08, eu 07-16, us 13-22,
özel `"08-17"`, gece saran `"22-06"`. Kapı `SignalPipeline.evaluate`
içindedir → **canlı ve backtest ORTAK** (mum zaman damgasından UTC saat).
Kapalı pencerede yeni giriş yok; açık pozisyon yönetimi sürer.
Geçersiz yapılandırma fail-open'tur (oturum kilitlenmez).

### 2.5 Madde 10 — Canlı emir katmanı sertleştirme ✅

- **429/Retry-After:** transport 429'u `LiveRateLimited(Retry-After)` olarak
  yükseltir; istemci Retry-After süresi kadar bekleyip (tavan 60 sn)
  `rate_retries` (vars. 2) kadar yeniden dener. 5xx → üstel geri çekilme.
  4xx yeniden denenmez (emir idempotent clientOrderId taşır).
- **Zaman senkronu:** `sync_time()` sunucu saatini ölçer (Binance
  `/fapi/v1/time`, OKX `/api/v5/public/time`); imzalı istekler
  `local + offset` ile damgalanır; |ofset| > 1 sn uyarı loglanır;
  **-1021 / 50102** zaman sapma hatasında TEK kez resync + retry.
- **Hedge mode:** başlangıçta borsadan algılanır (Binance
  `positionSide/dual`, OKX `account/config posMode`). Hedge modda emirlere
  `positionSide=LONG/SHORT` (Binance) / `posSide=long/short` (OKX) eklenir;
  çıkışlarda hedge modda `reduceOnly` çıkarılır (borsa kuralı: hedge/long-
  short modda reduceOnly parametresi beklenmez; yön+tarafr zaten azaltıcıdır).
  `--position-mode auto|one_way|hedge`; istek ↔ hesap çelişkisinde HATA
  loglanır ve GERÇEK hesap modu kullanılır (fail-safe).
- **Post-only maker giriş:** `--live-entry-style`
  - `post_only_market_fallback` (varsayılan): paper dolum fiyatında
    post-only LIMIT (Binance GTX / OKX `ordType=post_only`); dolum
    `openOrders` yoklamasıyla izlenir (TTL 60 sn); dolmazsa/kısmen dolarsa
    iptal + **kalan miktar MARKET yedek** (yüksek sesle log; `entry_fallbacks`).
    Red (-5022 vb.) → MARKET yedek.
  - `post_only`: saf maker — dolum yoksa eşleme ATLANIR (borsada pozisyon
    oluşmaz; mutabakat `local_only` raporlar; `entry_skipped`).
  - `market`: v3.0 davranışı.
  Stop kurulamazsa pozisyon yine korumasız kalmaz (v3.0 kuralı aynen).

### 2.6 Madde 17 — Para akışı verileri ✅ (OKX likidasyonu hariç — dürüst not)

- **OI + CVD:** v2.0'dan beri var (aynen).
- **Gerçek funding oranı:** public `premiumIndex` (Binance) / `funding-rate`
  (OKX) → açık pozisyon sembolleri için periyodik çekilir; paper funding
  ödemeleri ARTIK GERÇEK oranla hesaplanır (oran gelmezse config
  varsayılanı — uydurulmaz). Backtest tarafı: madde 23.
- **Long/short hesap oranı:** `futures/data/globalLongShortAccountRatio`
  (Binance) / `rubik long-short-account-ratio` (OKX, uç yoksa None).
- **Likidasyon akışı:** Binance `!forceOrder@arr` WS (tüm pazar) —
  `parse_force_order` (SELL → LONG likide), executor'da 5 dk penceresinde
  long/short likidasyon toplamı (USD). Kopma → 5 sn'de yeniden bağlanma.
  **OKX likidasyon kanalı: uygulanmadı** — kanal şeması bu pakette
  doğrulanamadı; sahte veri üretmek yerine dürüst kayıt bırakıldı
  (`liquidation_stream_task` docstring + panel "uygulanmadı" bilgisi).
- Para akışı verileri **gösterge/kayıt katmanıdır; skorlamaya dokunmaz**
  (v2 skor testleri aynen korunur). Panelde sembol başına L/S + likidasyon
  + funding satırı; oturum raporunda `money_flow`.

### 2.7 Madde 18 — ABD piyasası ajanı ✅

`agents/us_market.py::USMarketAgent` — Yahoo Finance chart API (anahtarsız):
^GSPC, ^IXIC, DX-Y.NYB, ^VIX. Deterministik kural: **risk_off** = VIX ≥ 25
veya (SPX günlük ≤ -%1.5 VE NDX ≤ -%2.0); **risk_on** = VIX ≤ 18 ve SPX ≥ 0;
arada **neutral**. Veri yoksa `unavailable` + **fail-open** (yanlış veriyle
engel yapılmaz). Modlar: `--us-market flag` (vars.: yalnız bayrak) |
`block` (risk_off taze iken yeni giriş engellenir) | `off`.
**Canlı duman testi (7 Kasım): ajan gerçek veriyle `risk_off (VIX 25.6 |
SPX +0.31% | NDX +1.09%)` bayrağı üretti** — panel ve rapora yazıldı.

### 2.8 Madde 19 — RSS haber ajanı ✅

`agents/news_rss.py::RssNewsAgent` — CoinDesk/Cointelegraph RSS
(yapılandırılabilir), xml.etree ile başlık taraması (harici bağımlılık
yok). Risk sözlüğü (hack 0.9, exploit 0.9, ban 0.8, depeg 0.8, lawsuit 0.7,
outage 0.6, ...). Pencere 45 dk; eşik 0.6; bayrak TTL 90 dk.
**Yalnızca risk bayrağı üretir, işlem AÇMAZ**; `--news-rss flag` (vars.) |
`block` | `off`. Tek feed hatası ölümcül değildir.

### 2.9 Madde 20 — Kongre işlemleri ajanı ✅ (dürüst "uygulanmadı")

`agents/congress.py::CongressAgent` — güvenilir, ücretsiz, programatik
veri kaynağı YOKTUR (QuiverQuant vb. ücretlidir; scraping tos ihlali +
kararsızdır). Kullanıcının kendi notu da "veri kaynağı gerekir"dir.
Ajan ŞEFFAF durum raporlar: `{"available": false, "reason": "uygulanmadı:
..."}`; bilgi sinyali olarak tasarlanmıştır, **asla engellemez/işlem
tetiklemez**. Gelecekte kaynak bağlanacaksa arabirim hazır.

### 2.10 Madde 21 — Analist ajanı ✅

`agents/analyst.py::AnalystAgent` — oturum raporunu yorumlar:
- **Kurallı katman (varsayılan, çevrimdışı):** motor performansı, bayat
  iptalleri, hız limiti beklemeleri, net sonuç, güvenli mod, kısa oturum
  uyarısı → okunabilir gözlem + öneri listesi (örn. "momentum_hunter 5
  işlemde -0.9R ile en zayıf...", "kısa denemelerde --min-rvol 1.2 deneyin").
- **Opsiyonel LLM katmanı:** `analyst_llm=true` + `ACARBOT_LLM_API_URL` +
  `ACARBOT_LLM_API_KEY` (OpenAI-uyumlu uç) verilirse rapor özeti yorumlanır;
  her hata sessizce kurallı katmana düşer (rapor bozulmaz).
**İşlem kararı VERMEZ** — yalnız log + rapor (`analyst` alanı).

### 2.11 Madde 22 — Tarayıcı/araştırma ajanı — KAPSAM DIŞI (gerekçeli)

Bot çalışma zamanına genel amaçlı tarayıcı gömmek tasarım gereği
reddedildi: (1) borsa verisi zaten birinci elden WS/REST'ten gelir,
(2) tarayıcı = ağır bağımlılık + saldırı yüzeyi + kararsız scraping,
(3) RSS ajanı web başlık katmanını zaten karşılar. İstendiğinde ayrı bir
araştırma aracı olarak (bot dışı) eklenebilir. Bu karar kodda ve bu
dosyada belgelenmiştir.

## 3. Faz 4 — Doğrulama ve yayına alma

### 3.1 Madde 23 — Tarihsel funding + çok rejimli backtest ✅

- `tools/download_history.py --funding [--funding-periods 90]`:
  `<SYM>_funding.csv` (timestamp,rate) — OKX funding-rate-history /
  Binance /fapi/v1/fundingRate (imzasız, anahtarsız, sayfalı).
- Backtest motoru v3.0'dan beri `funding_rates` parametresini destekler;
  v4.0 `run_backtest` artık `*_funding.csv` dosyalarını yükleyip GERÇEK
  oranları motor'a verir (dosya yoksa config varsayılanı — dürüst).
- **Rejim bazlı döküm:** `backtest.metrics.regime_breakdown` — her CLOSE
  işlemi açılış anındaki akıllı rejime (TREND_UP/TREND_DOWN/RANGE) göre
  gruplanır; terminal tablosu + `backtest_result.json`'da
  `regime_breakdown` alanı → boğa/ayı/yatay ayrımı. `run_backtest`
  çıktısına `strategy/session_filter/dca_enabled/funding_history_loaded`
  alanları eklendi.

### 3.2 Madde 24 — 24-48 saatlik testnet oturumu — KILAVUZ TESLİM EDİLDİ

24-48 saatlik kesintisiz oturum ancak botun çalışacağı makinede
koşulabilir; geliştirme ortamında sahte bir rapor üretilmedi.
Bunun yerine: `docs/testnet_oturum_kilavuzu.md` (senaryo + saat saat
kontrol listesi + kabul kriterleri) ve `run_testnet_session.sh`
(tek komutla nohup başlatma, pytest ön şartı, rapor/log/pid adları,
acil durum komutu). Oturum sonunda `session_report.json` paylaşıldığında
Analist ajanı çıktısıyla değerlendirme yapılır.

## 4. Test paketi (483)

- `tests/test_v4_strategies.py` (17): seans filtresi (pencere, sarma,
  özel aralık, fail-open, pipeline entegrasyonu), strateji motorları
  (rsirev/bollkir/macd motor etiketleri, confluence 10 filtre + yükselen
  trend → LONG + düz → HOLD + bilinmeyen strateji dürüst HOLD), CLI
  (strategy/eşik doğrulama/session/dca/ajanlar/live bayrakları).
- `tests/test_v4_dca.py` (6): varsayılan kapalı, LONG tetik + ortalama/stop
  muhasebesi, adım ölçekleme + max_safety_orders, SHORT asla, risk tavanı
  bloğu, snapshot turu.
- `tests/test_v4_live_hardening.py` (21): 429/Retry-After + tükenme,
  5xx backoff, 4xx deneme yok, ofset damgası, sync_time (Binance+OKX),
  -1021 resync+retry, hedge/one-way emir gövdeleri (giriş/çıkış/stop),
  -2013 → None, OKX net vs long_short posSide/reduceOnly, OKX post-only
  gövde, post-only dolum/TTL-yedek/saf-skip/kısmi dolum/red-yedek,
  mirror_dca + idempotency, geçersiz entry_style reddi.
- `tests/test_v4_moneyflow.py` (11): Binance/OKX funding + L/S
  (başarı + hata → None), forceOrder ayrıştırma + bozuk şema, likidasyon
  penceresi toplam/süre, L/S bayatlık, gerçek oranıyla funding ödemesi,
  money_flow_summary.
- `tests/test_v4_agents.py` (17): ABD piyasası (risk_off/risk_on/neutral,
  ağ hatası fail-open, block/flag modlar, bayat bayrak fail-open, off),
  RSS (ayrıştırma, anahtar ağırlıkları, taze başlık bayrağı, block modu,
  TTL bitişi, ağ hatası), kongre dürüst durum, analist (kurallı gözlem/
  öneriler, boş oturum, LLM kapalı, dürüst pozitif not).
- `tests/test_v4_backtest_funding.py` (6): `_funding_rate_at` seçim,
  motor funding parametresi duman testi, rejim dökümü gruplama/boş/UNKNOWN,
  funding CSV'nin mum verisine karışmaması.
- **208 v1.2 testi hiç değişmeden aynen geçer**; 181 v2/v3/v3.1 testi de.

## 5. Canlı duman testi (bu paketle, gerçek veri, 7 Kasım 2026)

```
ACARBOT v4.0-final | PAPER mod | borsa=okx
v4.0: strateji=confluence (confluence eşiği 0.55) | seans=off | DCA=kapalı
AJANLAR: us_market=flag, rss_news=flag | kongre=uygulanmadı
ajan ABD piyasası: risk_off (VIX 25.6 | SPX +0.31% | NDX +1.09%)   ← GERÇEK veri
ajan RSS haber: sakin
SİNYAL YOK: [okx:BTC-USDT-SWAP] confluence_yetersiz                  ← zincir çalışıyor
rapor: agents + money_flow + analyst alanları dolu
```

## 6. Bilinçli olarak KAPSAM DIŞI / UYGULANMADI listesi

| Madde | Durum | Gerekçe |
|---|---|---|
| OKX likidasyon akışı | uygulanmadı | WS kanal şeması bu pakette doğrulanamadı; sahte veri üretilmez. Binance tarafı çalışıyor. |
| Kongre işlemleri verisi | uygulanmadı | Güvenilir ücretsiz kaynak yok (ücretli API). Ajan dürüst durum raporlar. |
| Tarayıcı/araştırma ajanı | kapsam dışı | Bot çalışma zamanına tarayıcı gömmek reddedildi (bkz. §2.11). |
| 24-48h testnet oturumu | kullanıcı makinesinde | Bu ortamda uzun süreli süreç yaşatılamaz; kılavuz + senaryo + kabul kriterleri teslim edildi. |
| PostgreSQL/TimescaleDB | kapsam dışı | Tek süreçli bot için SQLite (WAL) yeterli (v3.0 gerekçesi). |

## 7. Kullanım hız referansı

```bash
# Confluence + seans + DCA + ajanlar (paper)
python -m app.main --mode paper --paper --exchange okx --symbols BTCUSDT \
  --strategy confluence --confluence-threshold 0.6 --session us --dca \
  --us-market flag --news-rss flag

# Tam pazar + testnet eşleme + post-only (24 saat)
./run_testnet_session.sh 1440 binance

# Gerçek funding + çok rejimli backtest
python tools/download_history.py --exchange okx --symbol BTC-USDT-SWAP \
  --out-symbol BTCUSDT --bars 6000 --funding
python -m app.main --mode backtest --data-dir data --symbols BTCUSDT
```

Paket PAPER ONLY'dir; gerçek emir gönderilmez (testnet/demo eşleme ayrıca
ve açıkça istenir). Strateji kârlılığı KANITLANMAMIŞTIR — backtest/paper
sonucu gelecek getirinin garantisi değildir.
