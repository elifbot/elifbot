# PHOENIX V15_1 (4.5.1-hardened-v15) — Detaylı Test Raporu

**Tarih / saat:** 10 Kasım 2026, 20:10 – 20:21 UTC (23:10 – 23:21 Türkiye)
**Paket:** `PHOENIX_V4_SUPER_FINAL_15_HARDENED_V15_1.zip` · Drive ID `1dV-xBTFgN6Y4sv4Bk2W1L-naJurmq6gO` · 49.271 bayt · sürüm `4.5.1-hardened-v15`
**Ortam:** Python 3.13.16 · ccxt 4.5.92 · pytest 8.4.2 · sandbox (bulut çıkış IP)
**Komut:** `PHOENIX_BINANCE_PUBLIC_WWW=1 python -m run_live_binance_www --duration 600 --poll 15 --detail-per-cycle 0`
**Durum:** ✅ **Tamamlandı** — çıkış kodu 0, süre 695 sn, rapor JSON yazıldı (v15'te yaşanan "rapor yazılamadı" sorunu çözülmüş)

---

## 1. Yönetici özeti

| Soru | Cevap |
|---|---|
| Test tamamlandı mı? | ✅ Evet, 695 sn, exit 0, `final: true` raporu yazıldı |
| Çökme / hata var mı? | ❌ Yok — 0 hata, 0 düşen snapshot, 28/28 birim testi geçti |
| Evren büyüdü mü? | ✅ 528 → **1.288** (Binance www rotası çalıştı) |
| Sinyal var mı? | ❌ **0** — ama artık **nedeni ölçülebiliyor** |
| Sinyal neden yok? | 705 snapshot'ın **tamamı** yalnızca `min_score` yüzünden elendi (`strategy_rejections: {below_min_score: 705}`) |
| Skor durumu | min −0.416 · **max 0.453** · ortalama −0.020 · **0.5 üzerinde tek snapshot yok** |

**İki kritik bulgu:**

1. **Binance hâlâ fiilen taranmıyor** — ama sebebi 451 değil artık. İki ayrı katman daha var: ccxt `fetch_tickers` swap+future karışık listede patlıyor, ve Binance 24hr ticker'ında `bid/ask` yok (spread filtresi hepsini 99.999 bps sayıp eliyor). **Düzeltilirse taranan aday 176 → ~694 (3,9 kat).**
2. **Eşik hâlâ ulaşılamaz, ama v15_1'de ölçülebilir hale geldi.** OI düzeltmesi skor tavanını 0.264 → **0.453**'e çıkardı; yine de 0.72'nin altında.

---

## 2. v15 → v15_1 değişiklikleri (CHANGELOG 4.5.1)

- ✅ Binance public WWW FAPI rotası entegre edildi (`binance_www_route.py`, `run_live_binance_www.py`) — 451 çözüldü
- ✅ Döngü kontrol raporları, snapshot düşüş sebepleri, strateji red sayaçları, skor min/max/ortalama **ve histogram**
- ✅ İşaretli OI yönü düzeltmesi + yapılandırılabilir OI geri bakış/normalizasyonu
- ✅ Stop-loss bütçesi kontrat büyüklüğüne duyarlı hale getirildi
- ✅ Kontrollü **0.72 vs 0.30 kalibrasyon koşucusu** (`RUN_SIGNAL_CALIBRATION.bat`), üretim varsayılanı değişmeden
- ✅ Mod etiketi düzeldi: rapor artık `"mode": "READ_ONLY"` (v15'te `PAPER` yazıyordu)
- ✅ Test sayısı 24 → **28**

---

## 3. Test yürütme

### 3.1 Ön kontroller

| Kontrol | Sonuç |
|---|---|
| `pytest -q` | **28 passed** (0,52 s) |
| `compileall -q phoenix tests` | **OK** |

### 3.2 Canlı test zaman çizelgesi

```
20:10:10  Cycle 1: universe=1288 detailed=176
20:13:02  Cycle 2: universe=1288 detailed=180
20:16:00  Cycle 3: universe=1288 detailed=175
20:18:51  Cycle 4: universe=1288 detailed=174
20:21:35  DONE cycles=4 universe=1288 detailed_snapshots=705 signals=0
          unique_signals=0 errors=0 duration=695s
```

| Metrik | v15 (önceki) | **v15_1 (bu test)** |
|---|---|---|
| Evren | 528 | **1.288** |
| Döngü | 4 | 4 |
| Döngü başına aday | 179–181 | 174–180 |
| Toplam snapshot | ~720 (tahmin) | **705 (ölçüldü)** |
| Sinyal | 0 | 0 |
| Hata | 0 | **0** |
| Rapor yazıldı | ❌ hayır | ✅ evet |
| Mod etiketi | PAPER | **READ_ONLY** |
| Skor telemetrisi | yok | ✅ tam |

### 3.3 Rapor JSON (tam)

```json
{
  "version": "4.5.1-hardened-v15",
  "mode": "READ_ONLY",
  "duration_sec": 695,
  "cycles": 4,
  "universe": 1288,
  "detailed_snapshots": 705,
  "signals_seen": 0,
  "unique_signals": 0,
  "errors": 0,
  "exchanges": ["BINANCE", "OKX"],
  "detail_per_cycle": 0,
  "score_min": -0.41617580941973686,
  "score_max": 0.4530495519914169,
  "score_mean": -0.020230997572367744,
  "score_histogram": {
    "0.0-0.1": 390, "0.1-0.2": 205, "0.2-0.3": 67,
    "0.3-0.4": 38,  "0.4-0.5": 5,   "0.5-0.6": 0,
    "0.6-0.7": 0,   "0.7-0.8": 0,   "0.8-0.9": 0, "0.9-1.0": 0
  },
  "snapshot_dropped": {},
  "strategy_rejections": { "below_min_score": 705 },
  "signals_by_exchange": {},
  "signals_by_side": {},
  "final": true
}
```

---

## 4. BULGU 1 — Binance üç katmanlı olarak kırık (451 çözüldü, ikisi kaldı)

### Katman 1 — 451 coğrafi blok: ✅ **ÇÖZÜLDÜ**
www rotası çalıştı: evren 528 → 1.288, market keşfi hatasız. Logda tek bir 451 uyarısı bile yok.

### Katman 2 — `fetch_tickers` karışık tip hatası: ❌ **YENİ / DEVAM EDİYOR**
Her döngüde (4/4) aynı uyarı:

```
WARNING BINANCE ticker batch failed: binance symbols must be of the same type, either swap or future.
```

Sebep (`ccxt/base/exchange.py` ~satır 5227, `sameTypeOnly=True`): ccxt `binance`, `fetch_tickers` çağrısında **swap ve vadeli (dated future) sembollerin karışmasına izin vermiyor**. PHOENIX evrene ikisini de aldığı için batch her seferinde patlıyor.

Doğrulama (ayrı prob):
```
karisik batch HATA: BadRequest binance symbols must be of the same type, either swap or future.
sadece swap listesiyle: fetch_tickers OK (756 sembol)
```

**Etki:** Binance'ten döngü başına **0 aday** → taranan 176 sembolün tamamı OKX'ten geliyor. Rapor `universe: 1288` yazıyor ama **gerçek taranabilen evren 176** (%13,7).

### Katman 3 — Binance 24hr ticker'ında `bid/ask` yok: ❌ **YENİ**
`fapi/v1/ticker/24hr` bid/ask döndürmüyor. Ölçüm:

```
BTC/USDT:USDT 24hr ticker -> bid=None  ask=None  last=73666.3  quoteVolume=12.438.103.692
```

PHOENIX `_rank_tickers` içinde spread'i buradan hesaplıyor: `bid/ask` yoksa `spread = 99999 bps` → **12 bps filtresini hiçbir Binance sembolü geçemez.** Yani katman 2 düzelse bile katman 3 tek başına Binance'i yine sıfırlar.

Doğrulama (`fetch_bids_asks` = `/fapi/v1/ticker/bookTicker`):

```
sadece hacim filtresini geçen (≥1M USD):              573
bookTicker ile bid/ask alınırsa geçen aday sayısı:     518
```

** Birleşik etki: ** İki katman düzeltilirse döngü başına aday **176 → ~694 (176 OKX + 518 Binance)**, yani **3,9 kat** tarama kapasitesi.

### Önerilen düzeltme (`phoenix/live.py`)

```python
def _rank_tickers(self):
    for ex, ad in self.adapters.items():
        ms = [m for m in self.markets if m.exchange == ex]
        try:
            ticks = ad.tickers([m.symbol for m in ms])
        except Exception:
            # ccxt binance: swap + future aynı batch'te gönderilemez
            ticks = {}
            for group in ({"swap"}, {"future"}):
                sub = [m.symbol for m in ms if m.contract_type in group]
                if sub:
                    ticks.update(ad.tickers(sub))
        # Binance fapi 24hr ticker'ında bid/ask yok -> bookTicker'dan tamamla
        missing = [s for s, t in ticks.items() if not (t.get("bid") and t.get("ask"))]
        if missing and ad.client.has.get("fetchBidsAsks"):
            for s, x in ad.bids_asks(missing).items():
                ticks[s] = {**ticks.get(s, {}), "bid": x.get("bid"), "ask": x.get("ask")}
        ...
```
Adapter'a da `bids_asks(symbols)` sarmalayıcısı eklenmeli (retry politikasıyla).

---

## 5. BULGU 2 — Sinyal yokluğunun matematiksel kanıtı

Artık tahmin yok, ölçüm var: `strategy_rejections: {"below_min_score": 705}` → **705 snapshot'ın hepsi yalnızca eşik yüzünden elendi.** Veri kaynaklı düşüş (`snapshot_dropped`) **sıfır**.

### 5.1 Skor dağılımı (705 snapshot)

| \|skor\| aralığı | Adet | % | Kümülatif ≥ eşik |
|---|---:|---:|---:|
| 0.0 – 0.1 | 390 | 55,3 % | — |
| 0.1 – 0.2 | 205 | 29,1 % | — |
| 0.2 – 0.3 | 67 | 9,5 % | — |
| 0.3 – 0.4 | 38 | 5,4 % | 43 (eşik 0.30) |
| 0.4 – 0.5 | 5 | 0,7 % | 5 (eşik 0.40) |
| 0.5 + | **0** | 0 % | 0 (eşik 0.50+) |

**En yüksek \|skor\| = 0.453** — eşik 0.72'nin %37 altında. Dağılım 0.5'in üzerinde tamamen boş.

### 5.2 Eşik → sinyal sayısı projeksiyonu (695 sn / 4 döngü)

| `PHOENIX_MIN_SCORE` | Bu testte üretilecek sinyal | Saatte ≈ |
|---:|---:|---:|
| 0.72 (mevcut) | **0** | 0 |
| 0.50 | 0 – 1 | ~0–5 |
| 0.45 | ~1 – 3 | ~5–15 |
| 0.40 | ~5 – 8 | ~26–41 |
| **0.35** | **~15 – 25** | **~78–130** |
| 0.30 | ~43 – 70 | ~223–363 |

> Projeksiyon: histogram kovaları üzerinden; kova içi dağılım düzgün varsayıldı. Kesin sayı için `RUN_SIGNAL_CALIBRATION.bat` ile 0.72 vs 0.30 karşılaştırması çalıştırılmalı.

### 5.3 v15 → v15_1 ilerleme

OI düzeltmesi (işaretli yön + yapılandırılabilir geri bakış/normalizasyon) **işe yaramış**:

| | v15 | v15_1 | Değişim |
|---|---:|---:|---:|
| Ölçülen en yüksek \|skor\| | 0.264 | **0.453** | **+72 %** |
| 0.3 üzeri snapshot | bilinmiyor | **43 / 705** | — |

Skor tavanı yükseliyor; 0.72 hâlâ çok yüksek ama artık "ne kadar yüksek" sorusunun **sayısal cevabı var**.

### 5.4 Neden 0.5 civarında tavan var? (yapısal açıklama)

`score = Σ(ağırlık × bileşen) / Σ(ağırlık)` bir **ağırlıklı ortalama**. En büyük ağırlıklar `trend` (0.35) ve `htf` (0.20); bu ikisi ATR'ye normalize edildiği için pratikte 0.1–0.5 bandında doyuyor. Kolay doyan `funding` (0.05) ve `book` (0.15) ise küçük ağırlıklı. Yani **en büyük ağırlıklar en zor doyan bileşenlerde** → skor sistematik olarak 0'a doğru baskılanıyor. Likidasyon bileşeni OKX'ta hiç yok (ccxt desteklemiyor) → toplam ağırlık 0.90'a düşüyor, kalanların ortalaması daha da yüksek olmalı.

---

## 6. Bulgu ve risk tablosu

| # | Önem | Bulgu | Kanıt |
|---|---|---|---|
| 1 | **Yüksek** | Binance `fetch_tickers` swap+future karışık batch → BadRequest; her döngü 0 Binance adayı | 4/4 döngü uyarısı + prob |
| 2 | **Yüksek** | Binance 24hr ticker'da `bid/ask` yok → spread 99.999 bps → tüm Binance sembolleri filtreye takılır | `bid=None ask=None` + 518 aday probu |
| 3 | **Yüksek** | `min_score=0.72` ulaşılamaz; ölçülen max 0.453, 0.5 üzeri hiç snapshot yok | `score_histogram`, `score_max` |
| 4 | **Orta** | Rapor `universe: 1288` ama gerçek taranan 176 → metrik yanıltıcı | detailed=174–180 vs universe=1288 |
| 5 | **Orta** | Likidasyon bileşeni OKX/Binance'ta yok → toplam ağırlık 0.90, eşik buna göre esnetilmiyor | ccxt `fetchLiquidations` desteği yok |
| 6 | **Düşük** | `--duration 600` → gerçek 695 sn (%16 taşma); döngü kontrolü döngü başında | zaman damgaları |
| 7 | **Düşük** | Kapasite riski: Binance açılırsa aday ~694'e çıkar → döngü süresi ~3 dk → **~11 dk**; `--poll 15` ve `--duration` anlamsızlaşır | 176 sembol = 174 sn |
| 8 | **Bilgi** | `signals_by_exchange` / `signals_by_side` boş kaldığı için hangi borsanın sinyal ürettiği görülemiyor (bu testte sinyal yok) | rapor JSON |

**Çözülenler (v15'e göre):** 451 erişim sorunu · rapor yazılamaması · mod etiketi (`PAPER`→`READ_ONLY`) · telemetri eksikliği · OI yön/normalizasyon · kontrat büyüklüğü duyarlı stop bütçesi.

---

## 7. Öncelikli öneriler

1. **Binance'i gerçekten aç (katman 2 + 3).** Yukarıdaki `_rank_tickers` yaması + adapter'a `bids_asks()`. Beklenen kazanç: taranan evren 176 → ~694, sinyal olasılığı ~4 kat.
2. **Eşiği kalibre et, tahmin etme.** Önce `RUN_SIGNAL_CALIBRATION.bat` ile 0.72 vs 0.30 karşılaştırmasını çalıştır; sonra histograma bakıp **hedef işlem sıklığına** göre seç. Benim önerim: **0.35** (bu testte ~15–25 sinyal / 11,5 dk) ile başla, `walk_forward` + komisyon/slippage ile doğrula.
3. **Likidasyon bileşenini ya kaldır ya besle.** Kaldırırsan ağırlıkları normalize et: trend 0.389 / htf 0.222 / oi 0.167 / book 0.167 / funding 0.056.
4. **Raporu ayır:** `universe_discovered` (1288) ve `universe_scanned` (176) ayrı alanlar olsun; `exchange_scanned: {OKX: 176, BINANCE: 0}` eklensin.
5. **Kapasite planı:** döngü süresi sınırı veya `--max-cycles` ekle; aksi halde Binance açılınca tek döngü ~11 dk sürecek.
6. **Başabaş uyarısı:** R = 2.2 ve ~14 bps gidiş-dönüş maliyetle başabaş isabet oranı **≈ %33–35**. Eşiği düşürmek sinyal üretir, **kâr garantisi değildir** — OOS/walk-forward doğrulaması şart.

---

## 8. Sonuç

v15_1, v15'e göre **belirgin ve ölçülebilir bir ilerleme**: Binance erişimi açıldı (evren 2,4 kat), telemetri eklendi, rapor artık kaybolmuyor, OI düzeltmesi skor tavanını %72 yükseltti, mod etiketi düzeldi, test sayısı 28'e çıktı. **Yazılım olarak sağlam: 0 hata, 0 düşen snapshot, temiz tamamlanma.**

Sinyal çıkmamasının sebebi artık kesin olarak kanıtlandı: **yalnızca eşik** (705/705 red `below_min_score`). Ama Binance tarafındaki iki yeni katman, tarama kapasitesinin %86'sını boşa harcıyor — bu düzeltilmeden eşik kalibrasyonu da eksik veriyle yapılmış olur.

Bu paket kârlılık iddiası taşımıyor; bu rapor **yazılım doğruluğu** değerlendirmesidir, yatırım tavsiyesi değildir.

---

## 9. Üretilen dosyalar

| Dosya | İçerik |
|---|---|
| `PHOENIX_V15_1_TEST_RAPORU_2026-11-10.md` | Bu rapor |
| `test_reports/live_10min_report.json` | v15_1 final rapor JSON (skor histogramı dahil) |
| `test_reports/live_10min.log` | Zaman damgalı canlı log |
| `phoenix_v15_1/…/binance_www_route.py`, `run_live_binance_www.py` | Pakete entegre www rota çözümü |
| `test_reports/run_live_v15_1.sh` | Tekrarlanabilir koşu betiği |
| `BINANCE_451_COZUM_BELGESI.md` | 451 çözüm belgesi (katman 1) |
| `PHOENIX_V15_TEST_RAPORU_2026-11-10.md` | v15 (önceki sürüm) raporu |
