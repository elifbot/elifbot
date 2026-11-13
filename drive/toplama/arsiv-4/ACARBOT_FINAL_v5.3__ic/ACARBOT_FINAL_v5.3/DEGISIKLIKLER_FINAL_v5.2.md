# ACARBOT FINAL v5.2 — DEĞİŞİKLİK GÜNLÜĞÜ

**Sürüm:** `5.2-final` · **Önceki:** `5.1-final`
**Test:** 602 → **721 passed** (119 yeni test, skip yok)

Bu sürüm yeni özellik sürümü değil, **kanıt dürüstlüğü sürümüdür**. v5.1
raporunun kendi etiketleriyle çelişen üç sorunu düzeltildi, kullanıcının
önerdiği 6. madde (dinamik risk ölçekleme) uygulandı ve inceleme sırasında
**dördüncü bir hata** daha bulundu.

---

## 0. Kullanıcı tespitleri ve karşılıkları

| # | Tespit | Durum | Nerede |
|---|---|---|---|
| 1 | "1m yol" etiketi doğru değil (`real_coverage_ratio: 0.0`) | ✅ düzeltildi | iki geçişli hedefli 1m + kapsama türevli etiket |
| 2 | Hüküm negatif sonucu gizliyor | ✅ düzeltildi | `backtest/verdict.py` |
| 3 | WF satırı liste basıyor / "ölçülmüş" etiketi yanlış / tek koşu | ✅ düzeltildi | `tools/validate_strategy.py`, `backtest/costs.py` |
| 4 | Ölçüm tabanı ince (tek an, 4 örnek, 6 sembol) | ✅ genişletildi | `tools/measure_costs.py` |
| 5 | Dosya adı v5.1.1, içi `5.1-final`; changelog'lar aynı | ✅ düzeltildi | tek sürüm kaynağı + bu dosya |
| 6 | Dinamik risk ölçekleme yapılmamış | ✅ uygulandı | `core/risk_scaling.py` |
| **7** | **(bu sürümde bulundu)** WF maliyet/mum içi yol aktarmıyor | ✅ düzeltildi | `backtest/walkforward.py` |

---

## 1. Hüküm motoru — walk-forward öncelikli

**Sorun.** v5.1'in `_verdict()` fonksiyonu önce birincil koşunun işlem
sayısına bakıyordu:

```python
if count < min_trades:
    return "örneklem yetersiz"
```

Aynı raporun walk-forward bölümünde **61 işlem, 0/6 kârlı pencere,
−433,64 USDT** vardı. Hüküm bunları görmüyordu. Üstelik birincil koşudaki
5 işlem zaten yapay olarak küçüktü: **1.117 giriş** drawdown korumasıyla
reddedilmişti. Yani "az işlem" bir belirsizlik değil, kaybın sonucuydu.

**Çözüm.** Yeni `backtest/verdict.py` modülü, kanıtın tamamına bakar ve
şu sırayla değerlendirir:

```
0. maliyetler kapalı        → INVALID_OPTIMISTIC   (⛔ kanıt sayılmaz)
1. WF yeterli işlem + net≤0
   + 0/N pencere kârlı      → NO_EDGE              (🔴 örneklem bahanesi YOK)
2. toplam kanıt < min_trades→ INSUFFICIENT_SAMPLE  (🔴)
3. net≤0 veya MC kayıp>%50  → NO_EDGE              (🔴)
4. risk hedefi sapması      → EDGE_RISK_DRIFT      (🟡)
5. aksi                     → EDGE_CANDIDATE       (🟢)
```

Hüküm artık düz metin değil **yapılandırılmış nesne**: `code`, `severity`,
`headline`, `reasons[]`, `evidence{}`. Regresyon kapısı makine okuyabilir.

Ek kurallar:
- `min_trades_source="all"` (yeni varsayılan): örneklem eşiği birincil +
  WF toplamına uygulanır.
- `min_wf_trades=30`: WF'de "kenar yok" demek için asgari işlem.
- **Kesilme tespiti**: drawdown redleri açılan işlem başına ≥2 ve ≥10 ise
  örneklem "KESİLMİŞ" diye işaretlenir. Oran tüm redlere göre
  hesaplanamaz — `dusuk_hacim` (126.652) payı boğar ve kesilmeyi gizler.
- Örneklem yetersiz hükmü bile WF toplamı negatifse bunu **açıkça uyarır**.
- Kapsama %0 ise "gerçek 1m ile DOĞRULANMADI" gerekçeye eklenir.

**v5.1 raporuyla test:** `test_v51_bug_replay_no_edge_not_insufficient`
aynı girdiyi verir ve artık `NO_EDGE` döner.

---

## 2. İki geçişli 1m — "−40 mı −25 mi?" artık cevaplanabilir

**Kök neden bulundu.** v5.1 raporu "OKX 1m geçmişi ~3 gün" diye varsayıyordu.
**Bu yanlıştı.** Ölçüm:

```
3 gün önce:  100 bar ✓      30 gün önce: 100 bar ✓
10 gün önce: 100 bar ✓      60 gün önce: 100 bar ✓
90 gün önce: 100 bar ✓
```

OKX `history-candles` 1m barı **90+ gün** geriye gidiyor. Sorun verinin
yokluğu değil, `--fine-days 3` ile yalnızca son 3 günü **istememizdi**.

**Çözüm.** `tools/download_history.py`'ye hedefli aralık indirme eklendi:
- `fetch_okx_range(inst_id, start_ms, end_ms, interval)` — `after` imleci
  ile geriye sayfalanır, aralık dışına taşmaz.
- `fetch_okx_windows(...)` — aralıkları birleştirir, istek bütçesi uygular.
- `merge_windows(...)` — çakışan aralıkları birleştirir.

`tools/validate_strategy.py` artık **yinelemeli iki geçiş** yapar:

```
1. 5m ile koş (sentetik yol)
2. İşlem açılan aralıkları topla — yalnız giriş barı değil, TÜM TUTMA
   SÜRESİ (stopun hangi 1m barda tetiklendiği asıl sorudur)
3. Yalnız o aralıkların 1m'ini indir
4. Yeniden koş → kapsama arttı mı? → gerekirse 3. geçiş
```

Yeni bayraklar: `--fine-mode targeted|head|off` (varsayılan **targeted**),
`--fine-passes 3`, `--fine-max-requests 600`. `--fine-days` varsayılanı
**0** oldu. Önbellek: `data/validation/fine_targeted/`.

**Dürüst etiket.** Koşu etiketi artık gerçek kapsama oranından türetilir:

| Kapsama | Etiket |
|---|---|
| %100 | `gerçek 1m yol` |
| %0 < x < %100 | `karma yol (gerçek 1m %X)` |
| %0 | `sentetik yol (1m YOK)` |

v5.1 kapsama %0 iken "1m yol" yazıyordu. Bir daha yazamaz.

---

## 3. Rapor hataları

### 3a. Walk-forward satırı
```diff
- f"{wf.get('profitable_windows', 0)}/{wf.get('windows', 0)} pencere kârlı"
+ f"{wf.get('profitable_windows', 0)}/{wf.get('total_windows', 0)} pencere kârlı"
```
`windows` bir **liste**; `0/[{...}] pencere` basıyordu. Ayrıca her koşu için
pencere tablosu eklendi (işlem, net PnL, kazanma, DD, kârlı mı) ve toplam
işlem sayısı gösteriliyor.

### 3b. "ÖLÇÜLMÜŞ" etiketi
`CostModel.summary_text()` her borsaya "ÖLÇÜLMÜŞ" diyordu; oysa Binance
hiç ölçülmemişti ve OKX'in 3,0/4,0 kayma değerleri varsayılandı.

Yeni API:
- `measured_exchanges()` — gerçekten ölçümü olan borsalar
- `symbol_provenance(symbol)` → `measured | default | disabled`
- `exchange_provenance()` → borsa bazında kaynak + ölçülen sembol listesi
- `coverage(symbols)` — veri kümesinin kaçta kaçı ölçülmüş

Özet artık şöyle:
```
binance: VARSAYIM (ÖLÇÜLMEDİ) spread 1.50bps, kayma 2.00bps, …
okx: 6 sembol ÖLÇÜLDÜ (sembol bazlı değerler kullanılır); ölçülmeyenler
     için VARSAYIM spread 0.99bps, …
· VERİ KÜMESİ KAPSAMASI 6/6 (%100)
```
Rapora provenance tablosu + ölçülmeyen sembol uyarısı eklendi.

### 3c. Tek koşu → karşılaştırmalar VARSAYILAN AÇIK
- `--bounds` → **varsayılan True** (`--no-bounds` ile kapanır)
- `--compare-no-costs` → **varsayılan True** (`--no-compare-no-costs`)

Rapora iki yeni bölüm:
- **İyimserlik farkı**: maliyetli − maliyetsiz net PnL farkı
- **Sentetik sınır aralığı**: ALT/ÜST net PnL + genişlik; aralık sıfırı
  kapsıyorsa "tek sayı ile kârlılık iddia edilemez" uyarısı

### 3d. Geçersiz JSON (bu sürümde bulundu)
`by_symbol.XRP.profit_factor = inf` JSON'a kaçıyordu; dosya katı JSON
olarak geçersizdi. `json_safe()` özyinelemeli temizler ve yazım
`allow_nan=False` ile yapılır — artık sessizce bozuk dosya üretilemez.

---

## 4. (Yeni bulunan hata) Walk-forward maliyet aktarmıyordu

`walk_forward()` imzasında `cost_model` **yoktu**:

```python
result = engine.run(sliced, funding_rates=..., btc_symbol=...)
```

Yani WF pencereleri **varsayılan maliyetle ve mum içi yol olmadan**
koşuyordu. Birincil koşu ölçülmüş maliyet + intrabar kullanırken WF
kullanmıyordu — iki sonuç **karşılaştırılabilir değildi**.

Düzeltme: `cost_model`, `intrabar`, `tick_sizes` parametreleri eklendi ve
pencerelere aktarılıyor. Her pencere **kendi** `IntrabarPath` nesnesini
alır; paylaşılsa kapsama sayaçları pencereler arasında şişerdi.

---

## 5. Ölçüm tabanı genişletildi

| | v5.1 | v5.2 |
|---|---|---|
| Tur sayısı | 1 (tek an) | **4** (`--rounds`) |
| Tur arası | — | **45 sn** (`--round-gap`) |
| Tur başına örnek | 4 | **6** (`--samples`) |
| Toplam örnek/sembol | 4 | **24** |
| Planlama değeri | medyan | **p75** (`--percentile`) |
| Ham istatistik | yok | p50/p75/p90/p95/maks |
| Kalite etiketi | yok | `measurement_quality.grade` |
| Ölçülmeyen varsayılanı | sabit 3,0/4,0 | **ölçülen p90 × 1,5** + `fallback_basis` |

`grade_measurement()` tabanı `thin | limited | adequate` diye etiketler
(örnek <12, tur <3, pencere <120 sn, sembol <8 kriterleri). Raporda
"Ölçüm tabanı İNCE" uyarısı ve "küçük coinlerde kayma daha kötü olabilir"
notu görünür.

---

## 6. Dinamik risk ölçekleme (kullanıcı önerisi madde 6)

**Neden gerekli.** v5.1'de risk sabitti: hep 25 USDT. Sonuç: ilk
zararlardan sonra %8 drawdown koruması duvar gibi devreye girip **1.117
girişi** kesti. Kademeli küçülme olmadığı için koruma bir uçurumdu.
İkinci sorun: DOGE'de ölçülen gidiş-dönüş kayması ~46 bps; dar stopta
25 USDT'lik bütçenin %80'i kaymaya gidiyordu.

**Yeni modül:** `core/risk_scaling.py` → `RiskScaler`, `RiskScalingConfig`,
`RiskBudget`. Bütçe, şu ölçeklerin **en küçüğüdür**:

| Bileşen | Kural |
|---|---|
| `drawdown` | tepeden %2'de küçülmeye başlar, %8'de tabana iner (doğrusal) |
| `streak` | ilk 2 kayıp bedava, sonra her kayıp −%15, taban %25 |
| `expectancy` | ≥20 işlemden sonra son 50 işlemin ort. R'i negatifse orantılı |
| `cost` | maliyet payı >%35 ise küçülür, **>%60 ise işlem HİÇ açılmaz** |
| `recovery` | histerezis: 3 kazanç başına +%10; tek kazançla tam boyuta dönülmez |

Kurallar:
- **Asla yukarı ölçeklenmez.** Tavan = taban risk. Kanıtlanmamış kenarda
  boyut büyütmek kaybı hızlandırır.
- Taban `min_risk_usdt = 2.5` (kullanıcının önerdiği 2,5–5 aralığı).
- Sert maliyet kapısı `MALIYET_BUTCESI_ASIMI` red sayacı üretir.
- Deterministik: aynı işlem dizisi + aynı equity → aynı bütçe.

**Bağlandığı yerler:**
- `core/risk.py::plan(..., risk_budget=None)` — bütçe sabit tavanı geçersiz kılar
- `backtest/engine.py` — tepe equity takibi, kapanan işlemleri besleme,
  bütçeyi plana ve bekleyen emre taşıma, `result.risk_scaling` istatistiği
- `exec/paper.py::bind_plan(..., risk_budget=)` — **kritik düzeltme:**
  ızgara hizalaması bütçeyi sabit tavanla **eziyordu**; artık ezmiyor
- `app/executor.py` — canlı/paper yol da aynı ölçekleyiciyi kullanır
- `core/config.py::SuperConfig.risk_scaling`

**Ölçülen etki** (fixture, drawdown koruması gevşetilmiş):
```
KAPALI  hedef riskler: 24.14 25.0 24.2 25.0 24.39 25.0 24.39 25.0
ACIK    hedef riskler: 24.14 25.0 24.2 25.0 15.65 15.65 17.5 17.5
                                            ↑ küçülme    ↑ toparlanma
```

`--no-risk-scaling` ile karşılaştırma koşulabilir.

---

## 7. Sürüm ve paketleme tutarlılığı

- `app/__init__.py` → `__version__ = "5.2-final"` (tek doğruluk kaynağı)
- Zip adı, iç sürüm ve README aynı: **v5.2**
- Bu changelog v5.1'den **farklı** (test bunu doğrular:
  `test_changelogs_are_not_duplicates`)
- `docs/backtest_referans.json` bu sürümle yeniden üretildi
- Regresyon kapısı sürüm uyuşmazlığında pipeline'ı kırar

---

## 8. Test kapsamı

`tests/test_v52_hardening.py` — **94 yeni test**:

| Sınıf | Sayı | Kapsam |
|---|---|---|
| `TestVerdictWalkForwardPriority` | 17 | WF önceliği, v5.1 hata tekrarı, kesilme, kapsama ifşası |
| `TestRiskScalingConfig` | 11 | geçersiz ayar reddi (parametrik) |
| `TestRiskScalerComponents` | 21 | merdiven, seri, beklenti, maliyet kapısı, histerezis, determinizm |
| `TestRiskScalingIntegration` | 4 | plan bütçesi, ızgara ezmesi, motor entegrasyonu, sert ret |
| `TestTargetedFineData` | 15 | aralık indirme, birleştirme, bütçe, önbellek, dürüst etiket |
| `TestReportFixes` | 5 | json_safe, WF satırı, sınır aralığı, bayrak varsayılanları |
| `TestCostProvenance` | 7 | borsa etiketi, kapsama, sembol kaynağı |
| `TestWalkForwardCostPropagation` | 3 | maliyet aktarımı, sayaç paylaşımı |
| `TestMeasurementQuality` | 7 | yüzdelik, kalite notu, çok turlu ölçüm |
| `TestVersionConsistency` | 4 |
| `TestPackageRelease` | 11 | sürüm, referans, changelog tekliği |

Mevcut 602 test korunarak **721 passed**.

---

## 9. Hâlâ açık olanlar (dürüst liste)

Bu sürüm **raporlama dürüstlüğünü** düzeltir; stratejinin kenarını
düzeltmez. Aşağıdakiler açık:

- **Kenar yok.** v5.2 hükmü artık bunu doğru söylüyor. Sinyal tarafı
  (R:R asimetrisi, hacim kapısı kalibrasyonu) ayrı çalışma gerektirir.
- Gerçek testnet/demo oturumu yapılmadı (`live/` yalnız mock testli).
- Tam pazar modunda MTF + order flow kapalı (rate limiti).
- Ajanlar backtest'te etkisiz.
- Binance vadeli tickSize doğrulanamıyor (bölgesel 451/202).
- Binance maliyetleri **hiç ölçülmedi**; varsayım olarak etiketli.
- Ölçüm tabanı hâlâ sınırlı sayıda sembolde; küçük coinlerde daha kötü
  olabilir (raporda uyarı var).
- Dinamik risk ölçekleme **kâr üretmez**; kaybı yavaşlatır ve maliyeti
  risk bütçesini yiyen sembolleri eler.

---

## 10. ÖLÇÜM SONUÇLARI (90 gün, 6 sembol, OKX)

**Hüküm değişti:** v5.1 "örneklem yetersiz" diyordu → v5.2 **`NO_EDGE`**:
**"KENAR YOK — walk-forward tüm pencerelerde zararlı."**

| | v5.1 | v5.2 |
|---|---|---|
| Gerçek 1m kapsama | %0,0 | **%92.9** |
| Birincil işlem / net | 5 / −87,11 | **14 / -80.48** |
| WF işlem | 61 | **242** |
| WF kârlı pencere | 0/6 | **0/6** |
| WF net | −433,64 | **-390.61** |
| Ort. kayıp | −21,94 | **-8.70** |
| MC kayıp olasılığı | %99,6 | **%99.9** |
| Maliyet kapısı reddi | — | **90** |
| Ölçüm kalitesi | *(etiket yok)* | **adequate** |

- Hedefli 1m: **21 istek / 1310 bar** ile %0 → %92.9
  kapsama (v5.1: 25.920 bar peşin indirme, %0 kapsama).
- Dinamik ölçekleme: 1031 bütçe, ort ölçek 0.0055,
  **90 giriş maliyet kapısıyla engellendi**.
- Sınır aralığı 0.2267 USDT genişlikte ve **sıfırı kapsıyor
  değil** — her iki uçta zarar. Belirsizlik savunması kapandı.
- Kapılar: regresyon **YEŞİL**, rapor tutarlılık **YEŞİL**, paket **GEÇTİ**,
  katı JSON **GEÇTİ**, **721 test**, lint temiz.

Ayrıntı: `ANALIZ_v5.2_KANIT.md` §9 · Rapor: `docs/dogrulama_v5.2.md`
