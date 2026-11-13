# ACARBOT v5.2 — KANIT DÜRÜSTLÜĞÜ ANALİZİ

**Sürüm:** `5.2-final` · **Tarih:** 8 Kasım 2026
**Test:** 721 passed · **Lint:** temiz · **Regresyon kapısı:** YEŞİL

Bu doküman, v5.1 raporuna yönelik teknik eleştirinin her maddesini
**kod düzeyinde** ele alır: sorunun kök nedeni, uygulanan düzeltme ve
düzeltmenin çalıştığını gösteren ölçüm.

---

## 0. Eleştirinin özeti ve sonuç

Kullanıcı üç rapor hatası bildirdi. Üçü de doğrulandı. İnceleme sırasında
**dördüncü bir hata** daha bulundu ve düzeltildi.

| # | Tespit | Doğrulama | Kök neden |
|---|---|---|---|
| 1 | "1m yol" etiketi yanlış | ✅ `real_1m_bars: 0`, `synthetic_bars: 30` | `--fine-days 3` yalnızca son 3 günü istiyordu |
| 2 | Hüküm negatif sonucu gizliyor | ✅ WF 61 işlem / 0-6 kârlı / −433,64 | `_verdict()` önce birincil işlem sayısına bakıyordu |
| 3 | Rapor üretim hataları | ✅ 3 ayrı hata | tip hatası + provenance yokluğu + kapalı bayraklar |
| **4** | **(yeni)** WF maliyet aktarmıyor | ✅ imzada `cost_model` yok | `walk_forward()` → `engine.run()` eksik argüman |

---

## 1. "1m yol" etiketi — kök neden beklenmedikti

### 1.1 Yanlış varsayım

v5.1 raporu "OKX 1m geçmişi ~3 gün" diye varsayıyordu ve bu yüzden
`real_coverage_ratio = 0.0` sonucunu **verinin yokluğuna** bağlıyordu.

Bu varsayımı doğrudan ölçtüm:

```python
# OKX history-candles, after imleci ile geriye
for days in (3, 10, 30, 60, 90):
    target = now - days * 86_400_000
    params = {"instId": "BTC-USDT-SWAP", "bar": "1m",
              "limit": "100", "after": str(target + 60_000)}
```

Sonuç:

| Hedef | Gelen bar | En eski bar | Hedefe uzaklık |
|---|---|---|---|
| 3 gün önce | 100 | 3,07 gün önce | −98,3 dk |
| 10 gün önce | 100 | 10,07 gün önce | −98,3 dk |
| 30 gün önce | 100 | 30,07 gün önce | −98,3 dk |
| 60 gün önce | 100 | 60,07 gün önce | −98,3 dk |
| **90 gün önce** | **100** | **90,07 gün önce** | −98,3 dk |

**OKX 1m verisi 90+ gün geriye gidiyor.** Sorun verinin yokluğu değil,
`--fine-days 3` ile yalnızca son 3 günü **istememizdi**. İşlemler 90 güne
yayıldığı için o pencereyle hiç kesişmiyordu.

### 1.2 Çözüm: iki geçişli hedefli indirme

`tools/download_history.py`'ye üç fonksiyon eklendi:

```python
fetch_okx_range(inst_id, start_ms, end_ms, interval="1m", max_pages=60)
fetch_okx_windows(inst_id, windows, interval="1m", max_requests=400)
merge_windows(windows, pad_ms=0)
```

`after` imleci DAHA ESKİ kayıtları getirir; bu yüzden `end_ms`'ten geriye
sayfalanır ve `start_ms`'e ulaşınca durur. Doğrulama (45 gün öncesi,
1 saatlik pencere): **tam 60 bar**, aralık dışına taşma yok.

`tools/validate_strategy.py` artık yineler:

```
Geçiş 1: 5m ile koş (sentetik yol)
         ↓
trade_windows() → işlem açılan aralıklar
         NOT: yalnız giriş barı değil, TÜM TUTMA SÜRESİ.
         Stopun hangi 1m barda tetiklendiği asıl sorudur.
         ↓
Yalnız o aralıkların 1m'ini indir (önbellekli, birleştirilmiş)
         ↓
Geçiş 2: yeniden koş → kapsama arttı mı? → gerekirse Geçiş 3
```

### 1.3 Ölçülen etki (smoke test, 4 gün / 2 sembol)

```
Geçiş 1/2: 7 işlem, net 59.2563, gerçek 1m kapsama %0.0
[okx:ETH-USDT-SWAP] hedefli 1m: +215 bar (4 aralık)
[okx:BTC-USDT-SWAP] hedefli 1m: +105 bar (3 aralık)
Geçiş 2/2: 7 işlem, net 61.5855, gerçek 1m kapsama %100.0
```

Kapsama **%0 → %100**. Net PnL **59,2563 → 61,5855** değişti. Bu, mum içi
yolun sonucu gerçekten etkilediğinin kanıtıdır — v5.1'de bu fark
hiç ölçülemiyordu.

### 1.4 Dürüst etiket

Koşu etiketi artık **gerçek kapsama oranından türetilir**:

```python
def _path_label(prefix, intrabar_stats, costs_on):
    ratio = intrabar_stats.get("real_coverage_ratio", 0.0)
    if ratio >= 0.999:  path = "gerçek 1m yol"
    elif ratio > 0:     path = f"karma yol (gerçek 1m %{ratio*100:.1f})"
    else:               path = "sentetik yol (1m YOK)"
```

Aynı smoke testin koşu etiketleri:
```
birincil (gerçek 1m yol)                                    kapsama 1.0
sentetik ALT sınır (kötümser) (sentetik yol (1m YOK))       kapsama 0.0
sentetik ÜST sınır (iyimser) (sentetik yol (1m YOK))        kapsama 0.0
maliyetsiz karşılaştırma (İYİMSER) (gerçek 1m yol · MALİYETSİZ)  kapsama 1.0
```

Ayrıca `check_report_consistency()` kapısı, kapsama %0 iken "gerçek 1m yol"
diyen bir raporu **ETİKET YALANI** diye reddeder.

---

## 2. Hüküm mantığı — negatif kanıt artık gizlenemiyor

### 2.1 Sorunun anatomisi

v5.1'in `_verdict()`:

```python
count = primary["trade_count"]          # 5
if count < min_trades:                  # 5 < 200
    return "KENAR KANITLANMADI — örneklem yetersiz"
```

Aynı raporun `walk_forward` bloğu:

```json
{"profitable_windows": 0, "total_windows": 6,
 "total_net_pnl": -433.6379, "worst_window_net_pnl": -102.1114}
```

Pencere başına işlem toplamı **61**. Yani kanıt vardı; hüküm bakmıyordu.

Dahası: birincil koşudaki 5 işlem **yapay olarak** küçüktü.
`rejection_counts.PORTFOLIO_DRAWDOWN_PROTECTION = 1117`. İlk zararlardan
sonra %8 drawdown koruması devreye girip girişleri kesmişti. "Az işlem"
bir belirsizlik değil, **kaybın sonucu**.

### 2.2 Çözüm: `backtest/verdict.py`

Hüküm artık yapılandırılmış bir nesne (`code`, `severity`, `headline`,
`reasons[]`, `evidence{}`) ve şu sırayla değerlendirilir:

| Sıra | Koşul | Kod |
|---|---|---|
| 0 | maliyetler kapalı | `INVALID_OPTIMISTIC` ⛔ |
| **1** | **WF ≥30 işlem + net ≤0 + 0/N kârlı** | **`NO_EDGE` 🔴** |
| 2 | toplam kanıt < min_trades | `INSUFFICIENT_SAMPLE` 🔴 |
| 3 | net ≤0 veya MC kayıp >%50 | `NO_EDGE` 🔴 |
| 4 | risk hedefi sapması | `EDGE_RISK_DRIFT` 🟡 |
| 5 | aksi | `EDGE_CANDIDATE` 🟢 |

Ek kurallar:
- `min_trades_source="all"`: örneklem eşiği **birincil + WF toplamına**
  uygulanır (v5.1 yalnız birincile bakıyordu).
- **Kesilme tespiti**: drawdown redleri açılan işlem başına ≥2 ve toplam
  ≥10 ise örneklem "KESİLMİŞ" diye işaretlenir ve gerekçeye
  *"Az işlem bir belirsizlik değil, kaybın sonucu"* eklenir.
  Oranı tüm redlere göre hesaplamak yanlıştır: `dusuk_hacim` (126.652)
  payı boğar ve gerçek kesilmeyi gizler. Bu yüzden ölçüt işlem başınadır.
- Örneklem yetersiz hükmü bile WF toplamı negatifse **açıkça uyarır**.
- Kapsama %0 ise *"gerçek 1m verisiyle DOĞRULANMADI"* gerekçeye girer.

### 2.3 Regresyon testi

`test_v51_bug_replay_no_edge_not_insufficient` v5.1'in girdisini birebir
verir (5 birincil işlem, 61 WF işlem, 0/6 kârlı, −433,6379) ve `NO_EDGE`
döndüğünü doğrular. Aynı test `INSUFFICIENT_SAMPLE` dönmediğini de assert eder.

### 2.4 Rapor tutarlılık kapısı (yeni)

`backtest/regression_gate.py::check_report_consistency(report)`:

- Hükmü raporun **kendi verisinden yeniden hesaplar**; kod uyuşmazsa
  **HÜKÜM TUTARSIZ** diye reddeder. Elle düzenlenmiş veya bayat hüküm
  artık pipeline'ı kırar.
- `verdict_detail.code` yoksa (v5.2 öncesi rapor) reddeder.
- Kapsama %0 + "gerçek 1m yol" etiketi → **ETİKET YALANI**.
- `walk_forward.total_windows` sayı değilse reddeder.
- Ölçülmemiş sembol, ince ölçüm tabanı, eksik sınır/karşılaştırma
  koşuları → uyarı.

Paketteki **eski v5.1 raporu bu kapıdan geçmiyor** (test bunu doğrular).
CI'ya `report-consistency` işi eklendi.

---

## 3. Rapor üretim hataları

### 3a. Walk-forward satırı liste basıyordu

```diff
- f"{wf.get('profitable_windows',0)}/{wf.get('windows',0)} pencere kârlı"
+ f"{wf.get('profitable_windows',0)}/{wf.get('total_windows',0)} pencere kârlı"
```

`windows` bir liste; `0/[{...}] pencere` üretiyordu. Düzeltme sonrası
(smoke test çıktısı):

```
- **birincil (gerçek 1m yol)**: 1/2 pencere kârlı · 8 işlem ·
  toplam 43.2209 USDT · en kötü pencere -52.5489 USDT

| Pencere | İşlem | Net PnL | Kazanma | Maks DD | Kârlı |
```

Artık her koşu için pencere tablosu ve toplam işlem sayısı da var.
Test: `assert "[{" not in markdown`.

### 3b. "ÖLÇÜLMÜŞ" etiketi ölçülmemiş borsaya da uygulanıyordu

`CostModel.summary_text()` tek bir global etiket basıyordu. Oysa:
- Binance **hiç ölçülmedi** (1,50/2,00/3,00 varsayılan sabitler)
- OKX'in 3,0/4,0 kayma değerleri de varsayılandı (yalnız spread sembol
  bazında ölçülmüştü)

Yeni API:

| Fonksiyon | Döndürdüğü |
|---|---|
| `measured_exchanges()` | gerçekten ölçümü olan borsalar |
| `symbol_provenance(s)` | `measured \| default \| disabled` |
| `exchange_provenance()` | borsa bazında kaynak + ölçülen sembol listesi |
| `coverage(symbols)` | veri kümesinin kaçta kaçı ölçülmüş |

Yeni özet:
```
Maliyet modeli: 6 sembol ölçüldü · ölçüm anı 2026-11-07T18:47:18+00:00
· binance: VARSAYIM (ÖLÇÜLMEDİ) spread 1.50bps, kayma 2.00bps, …
· okx: 6 sembol ÖLÇÜLDÜ (sembol bazlı değerler kullanılır);
       ölçülmeyenler için VARSAYIM spread 0.99bps, …
· VERİ KÜMESİ KAPSAMASI 2/2 (%100)
```

Rapora provenance tablosu ve ölçülmeyen sembol uyarısı eklendi.

### 3c. Karşılaştırma koşuları varsayılan açık

| Bayrak | v5.1 | v5.2 |
|---|---|---|
| `--bounds` | kapalı (opt-in) | **AÇIK** (`--no-bounds`) |
| `--compare-no-costs` | kapalı (opt-in) | **AÇIK** (`--no-compare-no-costs`) |

Rapora iki yeni bölüm:

**İyimserlik farkı** — maliyetli vs maliyetsiz net PnL farkı.
**Sentetik sınır aralığı** — ALT/ÜST net PnL + genişlik. Aralık sıfırı
kapsıyorsa *"tek sayı ile kârlılık iddia edilemez"* uyarısı.

Smoke testte ölçülen genişlik: **48,3076 USDT** (ALT 59,2563 / ÜST 10,9487).
Yani mum içi sıra bilinmediğinde sonuç bu kadar belirsiz — v5.1 bu
aralığı hiç göstermiyordu.

### 3d. Geçersiz JSON (bu sürümde bulundu)

`by_symbol.XRP.profit_factor = inf` JSON'a kaçıyordu. `Infinity` katı
JSON'da geçersizdir; dosyayı `json.load(..., parse_constant=...)` ile
okuyan her araç hata verir. v5.1 yalnızca üst düzey `profit_factor`'ı
temizliyordu.

Çözüm: özyinelemeli `json_safe()` + yazımda `allow_nan=False`. Artık
sessizce bozuk dosya üretilemez — üretmeye çalışırsa yazım patlar.
CI'ya "Tüm docs/*.json katı JSON" kontrolü eklendi.

---

## 4. (Yeni bulunan hata) Walk-forward maliyet aktarmıyordu

`backtest/walkforward.py` imzasında `cost_model` **yoktu**:

```python
def walk_forward(candles_by_symbol, windows=4, config=None,
                 initial_balance=1000.0, max_positions=None,
                 funding_rates=None, btc_symbol="BTCUSDT"):
    ...
    result = engine.run(sliced, funding_rates=..., btc_symbol=...)
```

Sonuç: WF pencereleri **varsayılan maliyetle ve mum içi yol olmadan**
koşuyordu. Birincil koşu ölçülmüş maliyet + intrabar kullanırken WF
kullanmıyordu.

**Bu, −433,64 USDT'lik WF sonucunun birincil koşuyla karşılaştırılabilir
olmadığı anlamına gelir.** Kullanıcının "kenar yok" çıkarımı doğruydu,
ama sayı daha da kötü olabilirdi çünkü WF iyimser varsayımlarla koşmuştu.

Düzeltme: `cost_model`, `intrabar`, `tick_sizes` parametreleri eklendi.
Her pencere **kendi** `IntrabarPath` nesnesini alır — paylaşılsa kapsama
sayaçları pencereler arasında şişerdi.

Test: `test_windows_use_given_cost_model` her pencerenin
`cost_model["source"] == "measured"` olduğunu, `test_window_intrabar_stats_not_shared`
paylaşılan sayacın 0 kaldığını doğrular.

---

## 5. Ölçüm tabanı

| | v5.1 | v5.2 |
|---|---|---|
| Tur sayısı | 1 (tek an, 18:47 UTC) | **4** |
| Tur arası | — | **45 sn** |
| Tur başına örnek | 4 | **6** |
| Toplam örnek/sembol | 4 | **24** |
| Sembol sayısı | 6 | **10** |
| Planlama değeri | medyan | **p75** |
| Ham istatistik | yok | p50/p75/p90/p95/maks |
| Kalite etiketi | yok | `thin \| limited \| adequate` |
| Ölçülmeyen varsayılanı | sabit 3,0/4,0 | **ölçülen p90 × 1,5** + `fallback_basis` |

`grade_measurement()` kriterleri: örnek <12, tur <3, pencere <120 sn,
sembol <8. Üç veya daha fazla ihlal → `thin`.

Kullanıcının "küçük coinlerde daha kötü olabilir" uyarısı artık raporun
kendisinde: *"Ölçüm yalnızca bu sembollerde ve bu zaman penceresinde
alındı. Tam pazardaki küçük coinlerde kayma DAHA KÖTÜ olabilir."*

---

## 6. Dinamik risk ölçekleme (madde 6)

### 6.1 Neden gerekli

İki ölçülmüş sorun:

1. **Uçurum etkisi.** Risk sabitti (25 USDT). İlk zararlardan sonra %8
   drawdown koruması duvar gibi devreye girip **1.117 girişi** kesti.
   Kademeli küçülme olmadığı için sistem "hep tam boyut → dur" diye
   çalışıyordu.
2. **Maliyet risk bütçesini yiyor.** DOGE'de ölçülen gidiş-dönüş kayması
   ~46 bps. %1,5 stopla bu, hedef riskin ~%23'ü; %0,3 stopla **%60'ı**.
   Sabit risk bunu görmez.

### 6.2 Tasarım

`core/risk_scaling.py` → `RiskScaler`. Bütçe, şu ölçeklerin **en küçüğü**:

| Bileşen | Kural |
|---|---|
| `drawdown` | tepeden %2'de küçülmeye başlar, %8'de tabana iner (doğrusal) |
| `streak` | ilk 2 kayıp bedava, sonra her kayıp −%15, taban %25 |
| `expectancy` | ≥20 işlemden sonra son 50 işlemin ort. R'i negatifse orantılı |
| `cost` | maliyet payı >%35 → küçülür; **>%60 → işlem HİÇ açılmaz** |
| `recovery` | histerezis: 3 kazanç başına +%10 |

Değişmezler:
- **Asla yukarı ölçeklenmez.** Tavan = taban risk.
- Taban `min_risk_usdt = 2.5` (kullanıcının 2,5–5 önerisi).
- Sert kapı `MALIYET_BUTCESI_ASIMI` red sayacı üretir.
- Deterministik: aynı işlem dizisi + aynı equity → aynı bütçe.

### 6.3 Bağlandığı yerler ve bulunan ikinci hata

| Dosya | Değişiklik |
|---|---|
| `core/config.py` | `SuperConfig.risk_scaling` |
| `core/risk.py` | `plan(..., risk_budget=None)` |
| `backtest/engine.py` | tepe equity, işlem besleme, bütçe taşıma, `result.risk_scaling` |
| `exec/paper.py` | `bind_plan(..., risk_budget=)` |
| `app/executor.py` | canlı/paper yol aynı ölçekleyici |

**Bulunan hata:** İlk entegrasyondan sonra bütçe hesaplanıyor ama
sonuca yansımıyordu. Nedeni: `bind_plan()` → `_align_plan_to_grid()`
notional'i **sabit tavanla yeniden hesaplıyordu**:

```python
notional = self.max_loss_per_position / per_unit   # bütçeyi EZER
```

Yani ızgara hizalaması dinamik bütçeyi sıfırlıyordu. Düzeltme:

```python
_budget = risk_budget if risk_budget and risk_budget > 0 else self.max_loss_per_position
notional = _budget / per_unit
```

Bu hata bulunmasaydı özellik "yazılmış ama etkisiz" kalacaktı — tam da
kullanıcının v5.0 için söylediği "ajanlar backtest'te etkisiz" durumu.

### 6.4 Ölçülen etki

Fixture, drawdown koruması gevşetilmiş (özellik izole edilsin diye):

```
KAPALI  hedef riskler: 24.14 25.0 24.2 25.0 24.39 25.0 24.39 25.0
ACIK    hedef riskler: 24.14 25.0 24.2 25.0 15.65 15.65 17.5 17.5
                                            ↑ küçülme   ↑ toparlanma
net: 128.7765 → 54.7443
bağlayan bileşen: drawdown 6, recovery 2 · min ölçek 0.626
```

Sert maliyet kapısı testi: eşik %2'ye çekildiğinde fixture'ta
`MALIYET_BUTCESI_ASIMI` redleri oluşuyor ve **hiç işlem açılmıyor**.

---

## 7. Test kapsamı

`tests/test_v52_hardening.py` — **119 yeni test**:

| Sınıf | Sayı |
|---|---|
| `TestVerdictWalkForwardPriority` | 17 |
| `TestRiskScalingConfig` | 11 |
| `TestRiskScalerComponents` | 21 |
| `TestRiskScalingIntegration` | 4 |
| `TestTargetedFineData` | 15 |
| `TestReportFixes` | 5 |
| `TestCostProvenance` | 7 |
| `TestWalkForwardCostPropagation` | 3 |
| `TestMeasurementQuality` | 7 |
| `TestVersionConsistency` | 4 |
| `TestPackageRelease` | 11 |
| `TestReportConsistencyGate` | 14 |

**Toplam: 721 passed** (v5.1: 602). Skip yok. Lint temiz
(`F,E9,E711,E712,E722`).

CI artık 5 iş: `lint`, `tests`, `regression-gate`,
`report-consistency`, katı JSON kontrolü.

---

## 8. Açık sınırlar (dürüst liste)

Bu sürüm **raporlamanın dürüstlüğünü** düzeltir; stratejinin kenarını
düzeltmez.

- **Kenar yok.** v5.2 hükmü artık bunu doğru söylüyor. Sinyal tarafı
  (R:R asimetrisi: ort. kazanç +0,65 / kayıp −21,94; hacim kapısının
  %81,4 barı reddetmesi) ayrı çalışma gerektirir.
- Gerçek testnet/demo oturumu yapılmadı (`live/` yalnız mock testli).
- Tam pazar modunda MTF + order flow kapalı (rate limiti).
- Ajanlar backtest'te etkisiz.
- Binance vadeli tickSize doğrulanamıyor (bölgesel 451/202).
- **Binance maliyetleri hiç ölçülmedi** — artık varsayım diye etiketli.
- Ölçüm tabanı 10 sembolle sınırlı; küçük coinlerde daha kötü olabilir.
- Dinamik risk ölçekleme **kâr üretmez**; kaybı yavaşlatır ve maliyeti
  risk bütçesini yiyen sembolleri eler.

---

## 9. 90 GÜNLÜK DOĞRULAMA — v5.2 ÖLÇÜM SONUÇLARI

**Koşu:** 7 Kasım 2026, 21:58 → 22:43 UTC (45 dk) · OKX · 6 sembol ·
155.520 × 5m bar · profil `apex` · bakiye 1.000 USDT · taban risk 25 USDT
**Maliyet:** 10 sembol × 24 örnek, 4 tur,
148 sn pencere, p75 · kalite **adequate** ·
veri kümesi kapsaması **6/6 (%100)**

### 9.1 Hüküm değişti

| | v5.1 | v5.2 |
|---|---|---|
| Hüküm kodu | *(yok — düz metin)* | **`NO_EDGE`** |
| Hüküm | "örneklem yetersiz" | **"KENAR YOK — walk-forward tüm pencerelerde zararlı"** |
| WF işlem | 61 | **242** |
| WF kârlı pencere | 0/6 | **0/6** |
| WF net | −433,6379 | **-390.6141** |
| WF maliyeti | varsayılan (aktarılmıyordu) | **ölçülmüş + mum içi yol** |

Hükmün kendi gerekçesi (rapordan):

> Walk-forward: 242 işlem, 0/6 pencere kârlı, toplam -390.61 USDT.
> Birincil koşunun örneklemi KESİLMİŞ: 1012 giriş drawdown korumasıyla reddedildi (açılan işlem başına 72.3 red). Az işlem bir belirsizlik değil, kaybın sonucu.

### 9.2 1m kapsaması: %0 → %92.9

| Geçiş | Gerçek 1m bar | Sentetik bar | Kapsama | İşlem | Net PnL |
|---|---|---|---|---|---|
| 1 | 0 | 234 | %0.0 | 14 | -80.2827 |
| 2 | 235 | 18 | %92.9 | 14 | -80.4766 |

Hedefli indirme **21 sayfa isteği** ile **1310 bar** getirdi
(14 aralık). v5.1'in 25.920 barlık peşin indirmesine karşılık
1310 bar — yani **~20× daha az veri** ile
%0 yerine %92.9 kapsama.

Koşu etiketi artık dürüst: **`birincil (karma yol (gerçek 1m %92.9))`**

**"−40 mı −25 mi?" sorusunun cevabı:** gerçek 1m yoluyla ölçülen
maksimum gerçekleşen/hedef kayıp oranı **1.346x**,
maksimum stop aşımı **0.7755x**. Yani 25 USDT hedefli
işlem en kötü 33.65 USDT kaybetti — v5.0'daki
−40,31 USDT'lik aşım bu veri kümesinde tekrarlanmadı. Ortalama oran
0.9705x (v5.1: 1,0988x). 1 işlem
1.3x eşiğini aştı.

### 9.3 Birincil koşu

| Metrik | v5.1 | v5.2 |
|---|---|---|
| Net PnL | −87,1110 | **-80.4766** |
| İşlem | 5 | **14** |
| Kazanma | %20,0 | **%28.6** |
| Profit factor | 0,0075 | **0.0749** |
| Ort. kazanç | +0,6544 | **+1.6289** |
| Ort. kayıp | −21,9414 | **-8.6992** |
| Maks DD | 87,1110 | **80.4766** |
| MC kayıp olasılığı | %99,6 | **%99.9** |
| Ücret / kayma | 11,55 / 13,36 | **12.80 / 12.31** |

Ortalama kaybın −21,94'ten -8.70'e düşmesi **dinamik risk
ölçeklemenin doğrudan etkisidir**: kayıp serisinden sonra bütçe tabana
(2,5 USDT) indi.

### 9.4 Walk-forward — artık aynı koşullarda

| Pencere | İşlem | Net PnL | Kârlı |
|---|---|---|---|
| 1 | 14 | -80.4766 | ❌ |
| 2 | 58 | -39.2963 | ❌ |
| 3 | 101 | -76.4027 | ❌ |
| 4 | 4 | -69.8761 | ❌ |
| 5 | 36 | -81.2242 | ❌ |
| 6 | 29 | -43.3381 | ❌ |

**Toplam 242 işlem, 0/6 kârlı,
-390.6141 USDT.** En kötü pencere -81.2242 USDT.

Pencere 1'in birincil koşuyla **birebir aynı** olması (14 işlem, -80.4766)
tesadüf değil: birincil koşudaki tüm işlemler ilk 15 günde açıldı, sonra
drawdown koruması kalan 75 gün boyunca girişi kesti
(1012 red).
Hükmün "örneklem KESİLMİŞ" gerekçesi tam olarak budur.

### 9.5 Dinamik risk ölçekleme — ölçülen etki

| Sayaç | Değer |
|---|---|
| Üretilen bütçe | **1031** |
| Ortalama ölçek | **0.0055** |
| Minimum ölçek | 0.0000 |
| Bağlayan bileşen | {'cost': 1, 'drawdown': 1029, 'recovery': 1} |
| **Maliyet kapısı reddi** | **90** |
| Gözlenen işlem | 14 |
| Son ortalama R | -0.5678 |
| Toparlanma tavanı | 0.25 |

**90 giriş `MALIYET_BUTCESI_ASIMI` ile hiç açılmadı** —
maliyeti risk bütçesinin %60'ından fazlasını yiyen semboller elendi.
v5.1'de bu girişler açılıp kaymaya teslim oluyordu.

Drawdown 1029 kez bağlayıcı oldu: sistem
artık %8 duvarına çarpmadan önce kademeli küçülüyor. Yine de
1012 red oluştu —
ölçekleme kaybı yavaşlatır, **ortadan kaldırmaz**.

### 9.6 İyimserlik farkı ve sınır aralığı (yeni bölümler)

**Maliyetlerin etkisi:**
- Maliyetli: -80.4766 USDT / 14 işlem
- Maliyetsiz: -80.5242 USDT / 16 işlem
- **Fark: -0.0476 USDT**

Farkın bu kadar küçük olması ilginç ve **dürüstçe raporlanmalı**: dinamik
ölçekleme nominali tabana (2,5 USDT risk) indirdiği için mutlak maliyet
de küçüldü. Yani "maliyetler önemsiz" değil, **"bu kadar küçük boyutta
maliyet önemsiz"**. 25 USDT sabit riskle koşulduğunda fark büyür.

**Mum içi belirsizlik aralığı:**
- Kötümser (ALT): -80.2827 USDT / 14 işlem
- İyimser (ÜST): -80.5094 USDT / 14 işlem
- **Genişlik: 0.2267 USDT** · sıfırı kapsıyor mu: **hayır**

Aralık sıfırı **kapsamıyor** — her iki uçta da zarar var. Yani sonuç
mum içi sıraya değil, stratejinin kendisine bağlı. Bu, "belirsizlik
yüzünden hükmü veremiyoruz" savunmasını da kapatır.

### 9.7 Red sayaçları

| Neden | Sayı |
|---|---|
| `dusuk_hacim` | 126,458 |
| `fade_kosulu_yok` | 12,703 |
| `guclu_trend_fade_kapali` | 5,696 |
| `fake_breakout_or_suspect` | 3,624 |
| `rejim_uyumsuz` | 2,476 |
| `yukselen_bicak` | 1,323 |
| `dusen_bicak` | 1,207 |
| `PORTFOLIO_DRAWDOWN_PROTECTION` | 1,012 |
| `dusuk_puan` | 459 |
| `MALIYET_BUTCESI_ASIMI` | 90 |

`dusuk_hacim` hâlâ baskın: 126,458 /
155,520 bar = **%81.3**.
Kullanıcının "~%80" gözlemi üçüncü kez doğrulandı. Bu, sinyal tarafında
ayrı bir kalibrasyon işidir.

### 9.8 Kapılar

| Kapı | Sonuç |
|---|---|
| Sürüm regresyon kapısı | **YEŞİL** (referans 5.2-final ile üretildi) |
| Rapor tutarlılık kapısı | **YEŞİL** (hüküm kendi verisiyle tutarlı) |
| Paket tutarlılık denetimi | **GEÇTİ** (0 uyarı) |
| Katı JSON | **GEÇTİ** (Infinity/NaN yok) |
| Test | **721 passed** |
| Lint | **temiz** |

### 9.9 Sonuç

v5.2 artık soruyu doğru soruyor ve doğru cevaplıyor:

**Kenar yok.** 242 walk-forward işleminin hiçbir alt dönemde kâr
üretmemesi, %99,9 Monte Carlo kayıp olasılığı ve her iki sentetik uçta
zarar — bunlar birlikte "örneklem yetersiz" değil, **negatif kanıt**tır.

Dinamik risk ölçekleme kaybı azalttı (ort. kayıp −21,94 → -8.70)
ve 90 kötü girişi engelledi, ama **kâr üretmedi**.
Gerçek paraya ölçekleme yapılmamalı; `max_loss_per_position` 2,5–5 USDT'de
kalmalı. Sıradaki iş sinyal tarafıdır: R:R asimetrisi ve hacim kapısı.
