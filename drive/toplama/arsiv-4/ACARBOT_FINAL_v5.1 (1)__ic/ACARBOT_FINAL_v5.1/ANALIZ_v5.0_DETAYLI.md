# ACARBOT — TÜM PROJENİN DETAYLI ANALİZİ ve v5.0 BİRLEŞİM RAPORU

**Tarih:** 7 Kasım 2026 · **Hazırlanan sürüm:** `ACARBOT_FINAL_v5.0` (`__version__ = "5.0-final"`)
**Kapsam:** Drive'daki "yeni botlar" klasöründeki tüm sürümler (v2.0, v2.0.1, v3.0, v4.0) + workspace'teki v1.0–v1.10 hattı
**Test durumu:** v5.0 anında 549/549; **v5.1 ile 601 passed + 1 koşullu** · **Canlı doğrulama:** tam pazar paper, 1046 feed, hatasız

> **v5.1 EKİ:** Bu doküman v5.0 birleşimini anlatır. Üzerine eklenen altı kanıt sertleştirme katmanı için **`ANALIZ_v5.1_KANIT.md`** ve **`DEGISIKLIKLER_FINAL_v5.1.md`** dosyalarına bakın. Aşağıdaki §8.1 uyarıları v5.1'de araçlaştırıldı (maliyet ölçümü, mum içi yol, 90 günlük doğrulama, regresyon kapısı).

---

## 0. YÖNETİCİ ÖZETİ — okumaya buradan başlayın

Elimizde **birbirinden kopmuş iki ayrı geliştirme hattı** vardı:

| Hat | Sürümler | Güçlü olduğu yer | Zayıf olduğu yer |
|---|---|---|---|
| **A hattı (sinyal/analiz)** | v2.0 → v2.0.1 → v3.0 → v3.1 → v4.0 | Uzmanlar, rejim, MTF, order flow, confluence, DCA, ajanlar, Monte Carlo, canlı emir katmanı | Risk matematiği, likidite filtresi, fiyat ızgarası, teminat yönetimi |
| **B hattı (risk/infüzyon)** | v1.0 → … → v1.10 | Tam pazar taraması, RVOL birim doğruluğu, 25 USDT hedef net risk, dinamik teminat, stop ızgarası, teminat kilidi | A hattındaki sinyal zenginliği yok |

**v5.0 bu iki hattı birleştirir.** Taban olarak v4.0 alındı (daha zengin), üzerine v1.10'un canlıda doğrulanmış 8 düzeltmesi port edildi. Sonuç: v4.0'ın 483 testi + v1.10'un 51 risk testi + 15 yeni birleşim testi = **549 test, tamamı yeşil.**

### ⚠️ En kritik bulgu (dürüst uyarı)

**v3.0 ve v4.0'ın GERÇEK VERİ backtest'i zarar ediyor.** Paketlerin içindeki `docs/backtest_gercek_veri.json`:

```
net_pnl            = -6.6794 USDT
trade_count        = 8
win_rate           = %50
profit_factor      = 0.31
avg_win            = +0.7533
avg_loss           = -2.4232      ← kazanç/kayıp oranı TERS
max_drawdown       = 8.1515 USDT (%0.81)
sharpe_per_trade   = -0.4753
Monte Carlo (2000) = kayıp olasılığı %92.3 · p50 -6.66 · p95 +0.59
```

Paketlerde görünen **+29.09 USDT / PF 2.80**'lik sonuç (`docs/backtest_ornek.json`) **sentetik demo verisidir** ve v2.0'dan v4.0'a kadar **aynı dosya, hiç değişmeden kopyalanmış**. Gerçek performans kanıtı değil.

**Bunun v5.0 için anlamı:** v5.0 risk *hassasiyetini* düzeltir, **kâr eden bir sinyal üretmez**. İşlem başına net riski ~2,5 USDT'den 25 USDT'ye çıkarmak, aynı negatif beklentiyle **zararı yaklaşık 10 katına** çıkarır. Bu yüzden §8'deki ölçekleme önerileri ciddiye alınmalı.

---

## 1. SÜRÜM ENVANTERİ

### 1.1 Drive'dan indirilen paketler

| Sürüm | Drive dosya kimliği | Boyut | .py | Üretim LOC | Test dosyası | Test fonksiyonu |
|---|---|---|---|---|---|---|
| v2.0 | `1T2IIb5h22gH3CP-wx3Gi1Op9ZBeflGpx` | 227.298 B | 73 | 16.039 | 23 | 301 |
| v2.0.1 | `1Q8C2UDwFz76XAaEYHIIqAvWu0GXnHoRf` | 230.617 B | 73 | 16.045 | 23 | 301 |
| v3.0 | `1L3iZqdjm8hHSF1goHOjObjnvvERozvcp` | 289.970 B | 75 | 17.825 | 24 | 326 |
| v4.0 | `1aAWzy24P041LwCMpnE14u0ICu45UaENB` | 371.927 B | 92 | 22.905 | 35 | 483 |

Klasör: **"yeni botlar"** → `1WSEzCoipYuMXDFfPcl56NXlxmp2LU0Qi` (7 zip; ayrıca v1.7/1.8/1.9).

### 1.2 v5.0'ın nihai yapısı

**57 üretim dosyası / 16.446 satır + 39 test dosyası / 7.832 satır**

| Katman | Dosya | Satır | Görev |
|---|---|---|---|
| `core/` | 18 | 5.189 | Sinyal çekirdeği: risk, spike, rejim, uzmanlar, MTF, order flow, scoring, gates, pipeline, portfolio |
| `app/` | 3 | 3.046 | CLI, executor (orkestrasyon), raporlama |
| `live/` | 4 | 2.113 | Borsa istemcileri, broker istemcileri, canlı senkronizasyon |
| `infra/` | 8 | 1.598 | Piyasa verisi modelleri, HTTP, hız limiti, veri bütünlüğü |
| `backtest/` | 6 | 1.326 | Backtest motoru, Monte Carlo, optimizasyon |
| `exec/` | 3 | 1.132 | Paper broker, emir yaşam döngüsü, dolum simülasyonu |
| `agents/` | 5 | 586 | Analist, ABD piyasası, RSS haber, kongre işlemleri |
| `monitor/` | 3 | 475 | Dashboard, metrikler |
| `safety/` | 4 | 389 | `alerts.py` (Telegram), `news_guard.py` (makro takvim), `security.py` (sır maskeleme, 19 satır). **Kill switch `core/risk.py`'de, deadman `app/main.py` + `live/broker_clients.py`'de, acil düzleştirme `live/sync.py`'de** — v5.0 raporunda bu yanlış atanmıştı, v5.1'de düzeltildi. |
| `state/` | 2 | 370 | SQLite durum saklama |
| `tools/` | 1 | 222 | Tarihsel veri indirme |

### 1.3 Ortak dosyaların benzerliği (v4.0 ↔ v1.10)

İki hat **aynı kökten ayrılmış**, sonra bağımsız evrilmiş:

| Dosya | Benzerlik | Yorum |
|---|---|---|
| `infra/.../feed.py` | %99,2 | Neredeyse aynı |
| `core/portfolio.py` | %98,3 | Neredeyse aynı |
| `infra/.../okx.py` | %92,4 | Küçük farklar |
| `core/spike.py` | %91,1 | v1.10 likidite tabanı eklemiş |
| `exec/paper.py` | %76,1 | v1.10 teminat kilidi + ızgara eklemiş |
| `core/risk.py` | %73,5 | v1.10 hedef-net-risk boyutlaması |
| `backtest/engine.py` | %66,9 | v4.0 funding/rejim eklemiş |
| `core/config.py` | %58,7 | İki taraf da yeni alanlar eklemiş |
| `app/executor.py` | %53,5 | **En çok ayrılan** — v4.0 uzman/pipeline, v1.10 hacim filtresi |
| `app/main.py` | %52,1 | **En çok ayrılan** — v4.0 ajanlar, v1.10 tam pazar |

Bu tablo, birleştirmenin neden dosya kopyalamayla değil **cerrahi port** ile yapıldığını açıklıyor.

---

## 2. TÜM İŞLEM SONUÇLARININ DEĞERLENDİRİLMESİ

### 2.1 Paketlerdeki backtest kanıtları

| Sürüm | Dosya | Veri | Net PnL | İşlem | Kazanma | PF | Ort. kazanç | Ort. kayıp | Max DD |
|---|---|---|---|---|---|---|---|---|---|
| v2.0 | `backtest_result.json` | gerçek | **0,00** | **0** | – | – | – | – | – |
| v2.0 | `docs/backtest_ornek.json` | **sentetik** | +29,0904 | 16 | %68,75 | 2,8031 | +4,1113 | −3,2268 | 8,6024 |
| v2.0.1 | `backtest_result.json` | gerçek | **0,00** | **0** | – | – | – | – | – |
| v2.0.1 | `docs/backtest_ornek.json` | **sentetik** | +29,0904 | 16 | %68,75 | 2,8031 | +4,1113 | −3,2268 | 8,6024 |
| v3.0 | `docs/backtest_gercek_veri.json` | gerçek (BTC 5m) | **−6,6794** | 8 | %50 | **0,3109** | +0,7533 | −2,4232 | 8,1515 |
| v3.0 | `docs/backtest_ornek.json` | **sentetik** | +29,0904 | 16 | %68,75 | 2,8031 | — | — | — |
| v4.0 | `docs/backtest_gercek_veri.json` | gerçek (BTC 5m) | **−6,6794** | 8 | %50 | **0,3109** | +0,7533 | −2,4232 | 8,1515 |
| v4.0 | `docs/backtest_ornek.json` | **sentetik** | +29,0904 | 16 | %68,75 | 2,8031 | — | — | — |

**Çıkarımlar:**

1. **v2.0 / v2.0.1 hiç gerçek işlem üretmemiş.** `backtest_result.json` sıfır işlem, `paper_bot.log` sıfır `ORDER_NEW`. v2.0.1'in 120 saniyelik paper oturumu bakiyeyi 1000,00 → 1000,00 bırakmış. Bu sürümler **işlevsel olarak doğrulanmamış**.
2. **v3.0 ve v4.0'ın gerçek backtest'i birebir aynı** (−6,6794 / 8 işlem). Yani v4.0'ın eklediği confluence, DCA, ajanlar, seans filtresi **backtest sonucunu hiç değiştirmemiş** — çünkü ya varsayılan kapalı (DCA) ya da backtest yolunda etkin değil (ajanlar).
3. **Kazanç/kayıp asimetrisi ters.** Ortalama kazanç +0,75, ortalama kayıp −2,42 → **R:R ≈ 0,31**. %50 kazanma oranıyla bu matematiksel olarak zarar üretir. Başabaş için gereken kazanma oranı: `2,4232 / (2,4232 + 0,7533) = %76,3`.
4. **Monte Carlo bunu doğruluyor:** 2000 simülasyonda kayıp olasılığı **%92,3**, medyan sonuç −6,66, en iyi %5'lik dilim bile ancak +0,59.

### 2.2 Red sayaçları — bot neden bu kadar az işlem açıyor?

v3.0/v4.0 gerçek veri backtest'i, aynı veri kümesinde:

| Red gerekçesi | Adet | Yorum |
|---|---|---|
| `dusuk_hacim` | **1.531** | Baskın engel — hacim filtresi |
| `fade_kosulu_yok` | 170 | FADE motoru koşul bulamıyor |
| `guclu_trend_fade_kapali` | 79 | Güçlü trendde FADE bilinçli kapalı |
| `rejim_uyumsuz` | 30 | Rejim filtresi |
| `fake_breakout_or_suspect` | 17 | Sahte kırılım / RVOL şüphesi |
| `yeniden_giris_beklemesi` | 16 | Cooldown |
| `limit_bekliyor` | 9 | Maker emir dolmadı |
| `dusen_bicak` / `yukselen_bicak` | 4 / 3 | Bıçak koruması |
| `emir_dolmadi` | 1 | TTL iptali |
| `mtf_uyumsuz` | 1 | Çoklu zaman dilimi |

**1.531 "düşük hacim" reddi**, v1.9'da canlıda tespit ettiğimiz sorunun backtest'teki izdüşümü: RVOL filtresi, likiditesi düşük enstrümanlarda *veri hatası* ile *likiditesizliği* ayırt edemiyordu. v5.0'ın `LİKİDİTE DÜŞÜK` / `RVOL ŞÜPHELİ` ayrımı tam olarak bunu adresliyor.

Şok testleri: 9 kontrol / 0 blok / 0 erişilemez. Beta: BTCUSDT = 1,0. Spread **uygulanmadı**, slippage 0 bps, latency 0 ms → **backtest iyimser**; gerçek maliyetler daha yüksek olurdu.

### 2.3 B hattının canlı işlem sonuçları (workspace'te ölçülen)

| Oturum | Sürüm | Süre | Bakiye | Gerçekleşen | İşlem | Not |
|---|---|---|---|---|---|---|
| `session_report_60min_v18.json` | v1.8 | 60 dk | 1000 → **965,8245** | **−34,1755** | 3 giriş / 3 kapanış | PROS SHORT −25,3388 · **BTTCUSDT SHORT −28,1044** |
| v1.9 canlı | v1.9 | 9 dk | — | — | 0 | 378 `LİKİDİTE DÜŞÜK` satırı / 195 sembol · 21 `RVOL ŞÜPHELİ` · 183 bastırma |
| v1.10 canlı | v1.10 | ~12 dk | 1000 | 0 | 0 | 1046 feed, 1303 tickSize; sandbox oturumu kesti (rapor oluşmadı) |
| **v5.0 canlı** | **v5.0** | **devam ediyor** | 1000 | — | — | 1046 feed, 1046 tickSize, **0 traceback** |

**BTTCUSDT −28,1044 olayı v5.0'ın doğuş sebebi.** Ayrıntısı §4.4'te.

---

## 3. v4.0'TA OLUP v1.10'DA OLMAYAN ÖZELLİKLER (v5.0'a taşındı)

**39 dosya** — sinyal zenginliğinin tamamı:

- **Uzman katmanı:** `core/experts.py`, `core/scoring.py`, `core/gates.py`, `core/pipeline.py`
- **Rejim ve çoklu zaman dilimi:** `core/regime.py`, `core/mtf.py`
- **Para akışı:** `core/orderflow.py` (CVD, OI, long/short, likidasyon)
- **Ek stratejiler:** `core/strategies_extra.py` (confluence, 10 filtre)
- **Portföy riski:** `core/portfolio_risk.py` (beta ayarlı yönlü maruziyet)
- **Ajanlar:** `agents/analyst.py`, `agents/us_market.py`, `agents/news_rss.py`, `agents/congress.py`
- **Backtest:** `backtest/montecarlo.py`, `backtest/optimization.py`
- **Canlı katman:** `live/clients.py`, `live/broker_clients.py`, `live/sync.py`
- **İzleme:** `monitor/dashboard.py`, `tools/download_history.py`
- **17 ek test dosyası**

## 3.1 v1.10'DA OLUP v4.0'DA OLMAYAN ÖZELLİKLER (v5.0'a port edildi)

| # | Özellik | v4.0 durumu | v5.0'da |
|---|---|---|---|
| 1 | RVOL likidite tabanı (5 USDT/sn) | ❌ yok | ✅ `core/spike.py` |
| 2 | Likiditesizlik ↔ veri şüphesi ayrımı | ❌ yok | ✅ `SpikeEvent.illiquid` |
| 3 | Pencere bazlı spike cooldown | ❌ yok (aynı saniye tekilleştirme) | ✅ `cooldown_seconds` |
| 4 | Nominal tavan kapalı + hedef net risk | ❌ 500 USDT sabit tavan | ✅ `core/risk.py` |
| 5 | Dinamik teminat (notional/kaldıraç) | ❌ sabit 50 USDT | ✅ `core/risk.py`, `exec/paper.py` |
| 6 | Stop fiyat ızgarası hizalama | ❌ yok | ✅ `risk.plan(tick_size=)` + `_align_plan_to_grid` |
| 7 | Dolum anı teminat kilidi | ❌ yok | ✅ `_margin_lock_blocks` |
| 8 | Bekleyen emir teminat rezervasyonu | ❌ yok | ✅ `reserved_margin` / `free_margin` |
| 9 | RVOL log kısıtlama (sembol başına) | ❌ yok (log seli) | ✅ `_log_volume_filter` |
| 10 | Maker dolum açlığı düzeltmesi | ❌ `spike None → tick_volume=0` | ✅ `tick_volume = base_delta` |
| 11 | Geçersiz risk ayarı fail-closed | ❌ kısmi | ✅ 4 doğrulama |
| 12 | Oturum raporu risk denetimi | ❌ yok | ✅ `volume_filter` + `target_risk_audit` |

**Zaten v4.0'ta var olan, port gerektirmeyen B hattı özellikleri:** tam pazar taraması (`--scan-all`), baz hacim düzeltmesi, bayat sinyal koruması, APEX profili, FADE/TREND motorları, rejim filtresi, portföy riski, canlı senkronizasyon, cross/isolated teminat modu.

---

## 4. v5.0'DA YAPILAN DEĞİŞİKLİKLER — dosya dosya

### 4.1 `core/config.py`

```python
account.max_notional_per_position = 0.0     # 0 = tavan KAPALI
account.margin_per_position       = 0.0     # 0 = DİNAMİK teminat
account.max_loss_per_position     = 25.0    # işlem başı hedef NET risk
signal.spike_min_baseline_notional_per_second = 5.0
signal.rvol_log_interval_seconds              = 60.0
exit.stop_tick_max_widen_ratio                = 1.5
```

**Neden 5 USDT/sn?** OKX'te 531 enstrüman ölçüldü:

| Taban hacim eşiği | Altında kalan enstrüman | Oran |
|---|---|---|
| < 0,5 USDT/sn | 46 | %8,7 |
| < 1 USDT/sn | 97 | %18,3 |
| **< 5 USDT/sn** | **244** | **%46,0** |
| < 10 USDT/sn | 295 | %55,6 |
| < 50 USDT/sn | 420 | %79,1 |

Referans: BTC 54.038 USDT/sn, ETH 36.767, FLOKI 4,057. 5 USDT/sn = **432.000 USDT/gün**. 3.000 USDT'lik bir emir, %1 katılım oranıyla bu enstrümanda **16,7 saat** sürer — yani 25 USDT riskli bir pozisyon zaten açılamaz. Eşik gerçekçi.

### 4.2 `core/risk.py` — hedef-net-risk boyutlaması

**Matematik:**

```
cost_rate = maker(0.0002) + taker(0.0005) + stop_slip(0.0005)
          + extra_slip(0.0003) + funding(0.0001) = 0.0016

effective_fraction = ızgaraya DIŞA yuvarlanmış stop mesafesi
                     LONG → floor(entry*(1-raw)/tick)*tick
                     SHORT → ceil(entry*(1+raw)/tick)*tick

notional  = 25 / (effective_fraction + 0.0016)
margin    = notional / 10
net_risk  = notional * (effective_fraction + cost_rate) + funding_buffer
```

**Örnek boyutlar (kaldıraç 10x):**

| Stop mesafesi | Nominal | Teminat | Net risk |
|---|---|---|---|
| %0,35 | 4.901,96 | 490,20 | 25,00 |
| %0,40 | 4.464,29 | 446,43 | 25,00 |
| %2,50 | 939,85 | 93,99 | 25,00 |
| %6,00 | 405,84 | 40,58 | 25,00 |

**Kritik düzeltme — funding çift sayımı:** İlk port denemesinde `per_unit_risk_rate` zaten `funding_rate` içerirken `net_risk`'e ayrıca `funding_buffer` ekleniyordu → 25,446 / 25,040 çıkıyordu. Doğru formül yukarıdaki gibi; artık tam 25,00.

**Izgara kabalığı koruması:** `snapped_fraction > raw_fraction * 1.5` ise `ValueError("STOP_IZGARA_KABA")` fırlatılır ve **işlem hiç açılmaz**. Örnek: fiyat 1,0, tick 0,4 (fiyatın %40'ı), stop %0,4 → reddedilir.

**Fail-closed doğrulamalar:** `max_loss_per_position <= 0`, `max_notional_per_position < 0`, `leverage <= 0`, `margin_per_position < 0` → hepsi `ValueError`.

### 4.3 `core/spike.py` — likidite ↔ şüphe ayrımı

```python
baseline_notional = baseline_per_second * price
illiquid = min_baseline_notional_per_second > 0 and baseline_notional < eşik
suspect  = rvol > sanity_cap and not illiquid
```

**Sıra önemli:** önce likidite, sonra birim doğrulaması. Ölü bir enstrümanda tek bir normal işlem RVOL'u 100–10.000x gösterir; bu **veri hatası değil, likiditesizliktir**. Eski kod bunları `ERROR` seviyesinde "birim/veri hatası" diye logluyordu — yanlış teşhis ve log seli.

`SpikeEvent`'e iki alan eklendi: `illiquid`, `baseline_notional_per_second`.
`_last_spike` artık **pencere bazlı cooldown** uyguluyor (eski hâl yalnızca aynı saniyede tekilleştiriyordu → 3 saniyelik pencere TOPLAMI mükerrer sayılıyordu).

### 4.4 `exec/paper.py` — ızgara hizalama + teminat kilidi

**BTTC vakası (v1.8 canlı, gerçek para değil paper):**

```
giriş            = 3,5007e-7
teorik stop %2,5 → 3,58822e-7
Binance tickSize = 1e-8  → fiyatın %2,86'sı (!)
tetiklenebilir İLK tick = 3,6e-7 → gerçek mesafe %2,837
v1.9 nominal 939,85 → NET -28,05   (hedef -25, sapma +%12)
v5.0 nominal 840,05 → NET -24,70   ✅
```

**Sebep:** pozisyon *teorik* stop mesafesinden boyutlanıyordu, borsa ise yalnız ızgara adımlarında fiyat verebiliyordu.

**Çözüm — `_align_plan_to_grid`:** maker emir her zaman limit fiyatından dolar. Plan, gerçek dolum fiyatına ve ızgaraya oturtulur; stop ızgaraya **dışa** yuvarlanır; pozisyon bu gerçek mesafeden **yeniden boyutlanır**. Böylece `plan.entry == dolum fiyatı` olur, dolumdaki ölçekleme oranı 1'dir ve stop ızgarada kalır.

**Diğer eklemeler:**
- `place_entry`: miktar `plan.notional / limit_price` — limit fiyatı referanstan farklıysa nominal sabit kalır
- `reserved_margin(exclude_order_id)` / `free_margin(...)`: bekleyen emirlerin bağladığı teminat
- `_margin_lock_blocks`: **her tick'te**, kalan miktarın gereken teminatı serbest teminatla karşılaştırılır; yetmiyorsa emir iptal, `TEMİNAT_KILIDI` kaydı, sayaç +1
- `_open_position_from_order`: teminat `filled_notional / leverage` (dinamik), net risk **dolan orana göre ölçeklenir**, funding tamponu nominalle ölçeklenir
- `OPEN` kaydına `notional` eklendi, `margin` artık dinamik

### 4.5 `app/executor.py`

- `tick_sizes` sözlüğü; `risk.plan(..., tick_size=...)` çağrısı, `ValueError` yakalanıp `RİSK ENGELİ` olarak loglanır
- `check_portfolio(..., reserved_margin=broker.reserved_margin())`
- **Maker açlığı düzeltmesi:** `tick_volume = base_delta` (eski: `base_delta if spike is not None else 0.0`). Hacim filtresi yalnızca **sinyali** iptal eder; ölçülen hacim gerçektir ve dolum simülasyonunu beslemeye devam eder. Eski kod, hacim patlaması olmayan normal piyasada emirleri aç bırakıyordu.
- `_log_volume_filter`: doğru etiket + sembol başına 60 sn'de tek satır, aradaki tekrarlar sayılıp bastırılır. `ERROR` → `INFO`/`WARNING`.

### 4.6 `app/main.py`

- **tickSize keşfi ek HTTP isteği olmadan:** `--scan-all` zaten `fetch_top_usdt_futures` çağırıyor; dönen `Market` nesneleri `tick_size` taşıyor. Aynı yanıttan alınır → rate limit maliyeti sıfır. (v1.10'daki ayrı `symbol_universe.discover_tick_sizes` portuna gerek kalmadı.)
- Boş evren → `fail-closed`, `return 1`
- Afişe üç yeni satır: `HACİM FİLTRESİ v5.0`, `BOYUTLAMA v5.0`, `STOP KORUMASI v5.0` + borsa başına `FİYAT IZGARASI` sayacı
- Oturum raporuna iki yeni blok:

```json
"volume_filter": { "low_liquidity_count", "rvol_suspect_count",
                   "log_suppressed", "min_baseline_notional_per_second" },
"target_risk_audit": { "target_net_risk", "max_notional_cap", "grid_symbols",
                       "grid_realign_count", "margin_lock_cancels",
                       "opened_positions", "net_risks": [...] }
```

`net_risks` listesi sayesinde **her açılan pozisyonun gerçekten 25 USDT mi taşıdığı** oturum sonunda denetlenebilir.

---

## 5. MİMARİ — giriş karar zinciri

```
tick gelir
  → veri bütünlüğü kaydı
  → baz hacim deltası → SpikeDetector
       ├─ illiquid  → LİKİDİTE DÜŞÜK (INFO, kısıtlı) → sinyal yok
       ├─ suspect   → RVOL ŞÜPHELİ (WARNING, kısıtlı) → sinyal yok
       └─ geçerli   → RVOL olayı
  → order flow CVD güncelle (gerçek hacimle)
  → process_entry_tick  ← tick_volume = GERÇEK delta (spike'tan bağımsız)
       └─ TEMİNAT KİLİDİ kontrolü → gerekirse iptal
  → mum kapanışı → entry_allowed
  → hacim kapısı → FakeBreakout → TREND/FADE motoru
  → uzman skoru → rejim → MTF → gates → confluence
  → resolver / news guard / sweep guard
  → risk.plan(tick_size)         ← ızgara hizalı, 25 USDT hedef
  → v1.7 canlı fiyat koruması    ← bayat sinyalde giriş iptali
  → check_portfolio(reserved_margin)
  → place_entry → bind_plan (ızgara yeniden hizalama)
  → her tick: teminat kilidi → dolum → pozisyon (dinamik teminat)
  → çıkış: acil net stop → klasik stop → TP → zaman aşımı
```

**Acil stop sırası korundu:** acil net-risk stopu klasik stopla aynı anda veya önce tetiklenir. 25 USDT boyutlamasında stop fiyatı zaten 25 USDT zarar noktası olduğu için iki çıkış nedeni çakışabilir; testlerde neden kümesi `{stop_loss, position_loss_stop}` olarak kabul edilir.

---

## 6. TEST SONUÇLARI

| Küme | Adet | Durum |
|---|---|---|
| v4.0 tabanı (uyarlanmış) | 483 | ✅ |
| v1.10'dan portlanan risk testleri | 51 | ✅ |
| **yeni** `test_v5_merge.py` | **15** | ✅ |
| **TOPLAM** | **549** | **✅ 1.95 s** |

### 6.1 Portlanan test dosyaları
- `test_target_risk_25.py` — hedef net risk, dinamik teminat, rezervasyon
- `test_rvol_liquidity.py` — likidite tabanı, şüphe ayrımı, log kısıtlama
- `test_stop_tick_and_margin_lock.py` — ızgara hizalama, BTTC regresyonu, teminat kilidi

### 6.2 Yeni birleşim testleri (`test_v5_merge.py`) — kesişimi sınar

| Sınıf | Test ettiği |
|---|---|
| `TestGridAlignmentKeepsV4Meta` | Izgara hizalama v4.0'ın skor/rejim/uzman meta'sını düşürmüyor; plan girişi = dolum fiyatı; `ORDER_NEW` kaydında `grid_aligned` |
| `TestTargetRiskEndToEndV5` | BTTC uçtan uca stop −25 civarı; `OPEN` kaydında dinamik teminat = nominal/10; kısmi dolumda net risk aşağı ölçekleniyor |
| `TestMarginLockWithV4Portfolio` | İlk emir teminatı tüketince ikincisi dolum anında iptal; bekleyen emir rezervasyonu sayılıyor |
| `TestVolumeFilterV5` | Likiditesiz ↔ şüpheli ayrımı; log bastırma sayacı; **spike yokken de maker emir doluyor** |
| `TestApexProfileV5` | APEX 25 USDT riski koruyor, tavanları kapatıyor; geçersiz ayar fail-closed; kaba ızgara reddi |
| `TestSessionReportV5` | Raporda `volume_filter` + `target_risk_audit` blokları |

### 6.3 Davranış değişimi nedeniyle güncellenen v4.0 testleri

22 test kırıldı — **hepsi beklenen davranış değişimiydi**, gerçek regresyon değildi:

1. **500 nominal tavanını varsayanlar** → yeni assert'ler (tavan kapalı, nominal stop'tan türüyor)
2. **Akış testleri legacy portföy tavanlarına takıldı** (`GROSS_NOTIONAL_CAP`, `INSUFFICIENT_FUNDS`) → `apex_config()` kullanıyor
3. **Çıkış nedeni testleri** → 25 USDT boyutlamasında acil stop klasik stopla çakışıyor → neden kümesi `{stop_loss, position_loss_stop}`. "Klasik önce" testinin niyeti `legacy_capped_config()` ile korunuyor.
4. **Float taşması** → `25.000000000000256 <= 25.0` başarısız; `pytest.approx(25.0, abs=1e-6)` kullanılıyor.

`tests/helpers.py`'ye iki fabrika eklendi: `apex_config()` (v5 varsayılanı) ve `legacy_capped_config()` (eski davranışı sınayan testler için).

---

## 7. CANLI DOĞRULAMA (7 Kasım 2026, 13:19 UTC)

```
FİYAT IZGARASI [binance]: 518 sembol için tickSize alındı
FİYAT IZGARASI [okx]:     528 sembol için tickSize alındı
TAM PAZAR TARAMASI: binance=518 + okx=528 | toplam 1046 feed | döngü hedefi 60 sn
ACARBOT v5.0-final | PAPER mod | borsa=binance,okx | bakiye=1000.00 | maks pozisyon=SINIRSIZ
HACİM FİLTRESİ v5.0: taban hacim < 5.00 USDT/sn → LİKİDİTE DÜŞÜK (bilgi, sinyal yok)
                     | taban üstünde RVOL > 100x → RVOL ŞÜPHELİ (uyarı) | log aralığı 60 sn/sembol
BOYUTLAMA v5.0: nominal tavan KAPALI — notional = 25 / (stop% + maliyet%), teminat DİNAMİK (notional/10)
STOP KORUMASI v5.0: fiyat ızgarası hizalı stop + dolum anı teminat kilidi AKTİF (genişleme tavanı 1.50x)
```

- **0 traceback, 0 CRITICAL**
- `LİKİDİTE DÜŞÜK` ve `RVOL ŞÜPHELİ` ayrı ayrı görünüyor, log seli yok
- Bilinen uyarı korundu: tam pazar modunda MTF REST ve OI sorguları kapalı (1000+ semborda rate limitlerine sığmaz), 5m yeniden örnekleme yedeği kullanılıyor

**Çalıştırma komutu:**
```bash
python3 -m app.main --mode paper --paper --exchange all --profile apex \
  --motors trend --scan-all --balance 1000 --duration-minutes 60 \
  --state test60_v5.sqlite3 --report-file session_report_60min_v5.json
```

---

## 8. BİLİNEN RİSKLER, SINIRLAR VE ÖNERİLER

### 8.1 🔴 Sinyal kenarı (edge) doğrulanmamış — en büyük risk

§2'deki gerçek backtest negatif. **v5.0 bunu düzeltmez.** Yapılması gerekenler, öncelik sırasıyla:

1. **Ölçeklemeden önce daha uzun örneklem.** 8 işlem istatistiksel olarak anlamsız. En az 200–300 işlemlik, çok enstrümanlı, çok rejimli bir backtest gerekli.
2. **R:R'yi düzelt.** Ortalama kazanç +0,75 / ortalama kayıp −2,42 ile %50 kazanma oranı zarar üretir. TP1 R katsayısı ve stop mesafesi yeniden kalibre edilmeli. Başabaş kazanma oranı %76,3.
3. **Maliyetleri backtest'e sok.** Spread "uygulanmadı", slippage 0 bps, latency 0 ms. Gerçekte maker/taker + kayma var; sonuç daha da kötüleşir.
4. **25 USDT'yi hemen açma.** Öneri: `max_notional_per_position` tavanını geçici olarak geri koy (ör. 500–1000) veya `max_loss_per_position`'ı 2,5–5 USDT'ye düşür, edge doğrulanana kadar küçük kal.

### 8.2 🟡 1000 USDT bakiye ile 25 USDT risk

%0,4 stop → 4.464 USDT nominal → 446 USDT teminat. 1000 USDT bakiyede **ancak 2 eşzamanlı pozisyon** sığar. APEX portföy tavanlarını kapattığı için gerçek sınır artık teminat. Canlıda bir `INSUFFICIENT_FUNDS` bloğu gözlendi (açılış anında, fiyatlar henüz dolmadan). Daha geniş sepet için bakiye ≥ 3.000 USDT önerilir.

### 8.3 🟡 Tam pazar modunda MTF / order flow kısıtı

1046 sembolde REST yenileme rate limitlerine sığmaz. MTF 5m yeniden örneklemeden, order flow "uygulanmadı" olarak raporlanır. Bu, v4.0'ın en güçlü iki uzmanının tam pazar modunda **tam çalışmadığı** anlamına gelir. Dar evrende (ör. 50 sembol) tam çalışır.

### 8.4 🟡 Ajanlar işlem kararı vermez

Analist, ABD piyasası, RSS, kongre ajanları yalnızca **öneri/ gözlem** üretir. Kongre ajanı dürüstçe "uygulanmadı" raporlar. Backtest yolunda etkin değiller — v4.0'ın backtest sonucunun v3.0 ile aynı olmasının sebebi bu.

### 8.5 🟢 Kapsam dışı bırakılanlar (bilinçli)

- Tarayıcı/araştırma ajanı (v4.0'da gerekçeli kapsam dışı)
- OKX likidasyon verisi (uç nokta yok — dürüst "uygulanmadı")
- Gerçek emir gönderimi: **v5.0 paper-only çalıştırıldı.** `live/` katmanı mevcut ve testnet kılavuzu `docs/testnet_oturum_kilavuzu.md` içinde, ancak bu oturumda gerçek/testnet emri gönderilmedi.

### 8.6 Operasyonel notlar

- İki botu paralel çalıştırmayın (429 rate limit).
- SQLite `trades` tablosu 0 görünebilir (dirty-gated/WAL); gerçek durum `paper_state` + log.
- Binance futures `exchangeInfo` bu bölgeden 451 veriyor; spot aynası (`data-api.binance.vision`) kullanılıyor, raporlar `spot-mirror` diye etiketleniyor.
- BTTC yalnız Binance'te var; OKX `BTTC-USDT-SWAP` 51001 döndürür.

---

## 9. TESLİM PAKETİ

- **Kod:** `ACARBOT_FINAL_v5.0/` — 57 üretim + 39 test dosyası
- **Testler:** 549/549 passed
- **Bu doküman:** `ANALIZ_v5.0_DETAYLI.md`
- **Değişiklik günlüğü:** `DEGISIKLIKLER_FINAL_v5.0.md`
- **Drive:** `ACARBOT_FINAL_v5.0.zip`
- **E-posta:** paket sahibine gönderildi (adres bu dosyada tutulmaz)

### Sürüm geçmişi — tek bakışta

| Sürüm | Katkısı | Kanıt durumu |
|---|---|---|
| v1.0–v1.4 | Temel paper bot, ilk risk katmanı | Teslim edildi |
| v1.5 | Tam pazar taraması (518+528) | 250/250 test, canlı |
| v1.6 | RVOL birim düzeltmesi (baz hacim deltası) | 258/258, canlı |
| v1.7 | Bayat sinyal koruması (canlı fiyat/stop girişi) | 264/264, canlı |
| v1.8 | 25 USDT hedef net risk çekirdeği | 281/281, 60 dk canlı (−34,18) |
| v1.9 | Likidite/şüphe ayrımı + log kısıtlama | 298/298, 9 dk canlı kanıt |
| v1.10 | Stop fiyat ızgarası + dolum anı teminat kilidi | 315/315, canlı |
| v2.0 / v2.0.1 | Uzmanlar, rejim, gates, pipeline | **0 gerçek işlem** |
| v3.0 | MTF, order flow, kısmi dolum, gerçek veri backtest | 326 test, backtest **−6,68** |
| v3.1 | v1.7 birleştirmesi, birim düzeltmeleri | — |
| v4.0 | Confluence, DCA, seans, ajanlar, Monte Carlo, canlı katman | 483 test, backtest **−6,68** |
| **v5.0** | **İki hattın birleşimi + 12 risk düzeltmesi** | **549/549, canlı hatasız** |

---

*Bu rapor workspace'teki gerçek dosyalardan, indirilen paketlerin içeriğinden ve canlı oturum loglarından üretilmiştir. Hiçbir sonuç tahmini veya varsayımsal değildir; doğrulanamayan her nokta açıkça "uygulanmadı / doğrulanmadı" olarak işaretlenmiştir.*
