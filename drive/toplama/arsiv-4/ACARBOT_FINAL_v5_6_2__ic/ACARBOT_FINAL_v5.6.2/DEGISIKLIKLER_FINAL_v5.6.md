# V5.6 — DEĞİŞİKLİK GÜNLÜĞÜ

**Sürüm:** 5.5-final → **5.6-final** · **Tarih:** 2026-11-08
**Temel:** v5.4-final (teslim edilmiş, Drive `1m7xqfaxJzTFAg_J5owvqGd4yT1Nzisa9`)

> **Mevcut bot sıfırdan yazılmadı.** v5.4 → v5.5 → v5.6 aşamalı
> dönüştürme sürdürüldü. Çalışan özellikler sebepsiz kaldırılmadı.
> Her değişiklik testle doğrulandı. Başarısız sonuçlar gizlenmedi.

---

## 1. ÖZET — NE DEĞİŞTİ

| Bölüm | İş | Durum |
|---|---|---|
| **A** | Güvenlik: canlı giriş kapısı + `kasa1000` profili | **YAPILDI** |
| **B** | Maker ters seçilim ölçüm altyapısı (≥300 dolum) | **ALTYAPI YAPILDI, veri toplanmadı** |
| **C** | Funding backtest'e bağlandı + kapsama denetimi | **YAPILDI, tarihsel veri yok** |
| **D** | 6 yeni giriş stratejisi × 3 zaman dilimi | **YAPILDI — 6'sı da elendi** |
| **E** | Maliyet görünürlüğü (maliyet/R analizi) | **YAPILDI** |
| **F** | 4 trailing varyantı ayrı deney | **YAPILDI — hiçbiri seçilmedi** |
| **G** | 12 ay / 30–50 sembol veri | **YAPILMADI — 90 gün / 6 sembol** |
| **H** | 6 belge + ZIP + mail | **YAPILDI** |

---

## 2. YENİ DOSYALAR

### 2.1 Çekirdek

| Dosya | Satır | İçerik |
|---|---:|---|
| `core/sizing_audit.py` | ~170 | Şartname tutarlılık denetimi: `SizingSpec`, `audit()`, `required_timeframe_scale()` |
| `core/entry_strategies.py` | ~330 | 6 bağımsız giriş stratejisi + `EntrySignal` |
| `exec/markout.py` | ~230 | `FillRecord`, `markout_bps`, `markout_excess_bps`, `analyze_fills` |
| `backtest/funding.py` | ~180 | `load_funding_csv`, `load_funding_dir`, `FundingCoverage`, `funding_status` |
| `backtest/trailing_experiment.py` | ~160 | 4 varyant, `apply_variant`, `evaluate_variant`, `pick_best` |
| `tools/strategy_lab.py` | ~250 | Bağımsız tarama simülatörü + `resample()` |

### 2.2 Testler

| Dosya | Test | Kapsam |
|---|---:|---|
| `tests/test_v56_sizing.py` | **14** | Şartname tutarlılığı, marj şişmesi, kayıp tavanı |
| `tests/test_v56_live_gate.py` | **7** | Canlı giriş kapısı, varsayılan kapalı |
| `tests/test_v56_markout.py` | **11** | Markout işaretleri, arındırma, 300 eşiği |
| `tests/test_v56_funding.py` | **7** | Kapsama, sahte sıfır yasağı, regresyon kilidi |
| `tests/test_v56_trailing.py` | **11** | Varyant ayrımı, OOS seçim kuralı |
| `tests/test_v56_strategies.py` | **8** | **Look-ahead yasağı**, yaklaşıklık beyanı |
| **TOPLAM YENİ** | **58** | |

### 2.3 Belgeler

| Dosya | İçerik |
|---|---|
| `V55_ROOT_CAUSE_FIX.md` | Kök neden: 3 kusur, matematik, önce/sonra |
| `V55_MAKER_SELECTION_TEST.md` | Ters seçilim: kanıt yok, altyapı hazır |
| `V55_FUNDING_VALIDATION.md` | Funding kusuru ve düzeltmesi |
| `V55_NEW_ENTRY_STRATEGIES.md` | 6 strateji × 3 TF, tüm sonuçlar |
| `V55_BACKTEST_RESULTS.md` | Tüm ölçümler, kabul kriterleri |
| `V55_CHANGELOG.md` | Bu dosya |

---

## 3. DEĞİŞEN DOSYALAR

### 3.1 `core/config.py`

```python
class LiveSyncConfig:
    enabled: bool = False
+   live_allowed_timeframes: tuple[str, ...] = ()      # HİÇBİRİ
+   live_requires_edge_proof: bool = True
```

**Gerekçe:** 5m ve 15m kenarı istatistiksel olarak elendi; 1h yetersiz
örneklem. Kanıt olmadan hiçbir zaman dilimi canlıya açık olmamalı.

### 3.2 `core/gates.py`

```python
+ ENTRY_EDGE_VERDICTS = {"5m": "GIRIS_KENARI_YOK", "15m": "GIRIS_KENARI_YOK",
+                        "1h": "YETERSIZ_ORNEKLEM", ...}
+ def canli_giris_izinli(timeframe, live_cfg) -> (bool, str)
```

İki koşul **birlikte** aranır: listede olmak **ve** kenar kanıtı.
Listeye eklemek tek başına yetmez.

### 3.3 `live/sync.py`

- `LiveMirror.__init__` → `entry_timeframe`, `live_cfg` parametreleri
- `mirror_open()` → giriş öncesi kapı kontrolü; reddedilirse
  `logger.error("EŞLEME REDDEDİLDİ ...")` ve `entry_skipped` kaydı

### 3.4 `app/main.py`

- **`kasa1000` profili eklendi:** marj 50, notional 500, kaldıraç 10,
  maks kayıp 25; portföy: 6 pozisyon, 150 toplam risk, 3000 brüt notional
- `--profile` choices'a `kasa1000`; `apex`'e "YALNIZ ARAŞTIRMA" uyarısı
- 2 `LiveMirror(...)` çağrısına `entry_timeframe` + `live_cfg` geçirildi

### 3.5 `tools/validate_strategy.py`

- **Funding bağlandı:** bir kez yükle, 4 bloğa geçir, rapor JSON'una yaz
- **`--trailing-variant`** bayrağı (4 seçenek)
- `_run_block()` imzasına `funding_rates`, `funding_info`

### 3.6 `app/__init__.py`, `requirements.txt`

`5.5-final` → **`5.6-final`**

---

## 4. KORUNAN ŞEYLER (geri alınmadı)

Şartname "düzeltilmiş stop sırasını geri alma" dedi:

| Mekanizma | Durum |
|---|---|
| Yapısal stop → acil stop sıralaması (v5.5) | **KORUNDU** |
| `Position.initial_stop_loss` | **KORUNDU** |
| `drawdown_peak_mode` (rolling/daily/all_time) | **KORUNDU** |
| Tek kaynak `broker.portfolio.equity_peak` | **KORUNDU** |
| Risk motoru (`core/risk.py`) | **DOKUNULMADI** |
| `apex` profili | **SİLİNMEDİ** (araştırma için) |
| `cancel_on_stop_breach_at_fill = False` | **DOKUNULMADI** |
| RVOL `sanity_cap = 100` | **DOKUNULMADI** |
| `below_floor_action = "block"` | **KORUNDU** |

---

## 5. DÜZELTİLEN KENDİ HATALARIM (dürüstlük kaydı)

Bu turda kendi kodumda 5 hata bulundu ve düzeltildi:

| # | Hata | Nasıl bulundu | Düzeltme |
|---|---|---|---|
| 1 | Geniş stopta "sabit marjda risk 25'in altında" varsayımı yanlıştı (500 × %8,21 = 41,07 > 25) | Elle hesap | `KAYIP_TAVANI_BAGLAYICI` hükmü + marj küçültme |
| 2 | `backtest/funding.py` kapsama kontrolü `start_ts_ms > 0` sentinel'i — 0 geçerli sınır | **Test yakaladı** | `end_ts_ms > 0 and end_ts_ms > start_ts_ms` |
| 3 | `core/entry_strategies.py` göstergeleri her barda tüm geçmişi hesaplıyordu → O(n²), tarama kilitlendi | İlk koşu 4 dk'da tek sembol bitmedi | `_IND_WINDOW = 200` pencere sınırı |
| 4 | Testlerde dondurulmuş config'e atama denendi | `FrozenInstanceError` | `dataclasses.replace` |
| 5 | **Trailing B ve C varyantları yapılandırma olarak ÖZDEŞti** (break-even zaten açıktı, B'de de açık bırakıldı) | A=B=C özdeş çıktı görülünce config denetimi | B'de break-even `False`; B ve C yeniden koşuldu; regresyon testi eklendi |

### 5.1 Ölçüm karıştırıcısı (confound) — açıkça bildirildi

Trailing D varyantının gerçek 1m kapsaması **%57,0**, diğer üçünün
**%63,5** çıktı. Farklı ATR çarpanı → farklı pozisyon süreleri →
farklı hedefli 1m talebi. **D'nin 0,18 USDT farkı varyant etkisi
değil, veri farkı olabilir.** Bu yüzden D seçilmedi.

Aynı şekilde v5.6 ara koşu (%36,4) ile nihai koşu (%63,5) **doğrudan
karşılaştırılamaz**; ara koşu `docs/arsiv/` altına taşındı ve nedeni
`docs/arsiv/OKUBENI.md` dosyasında yazıldı.

### 5.2 Önceki turdan geri alınan iddia

**"Stop düzeltmesi ~34 USDT / zararın %33'ü"** — sentetik birim testinden
gerçek örnekleme yanlış taşınmıştı. **Geri alındı.**
Gerçek ölçüm: **5,64 USDT = %5,6.**

---

## 6. TEST DURUMU

| Paket | Sonuç |
|---|---|
| `tests/test_v55_audit.py` | 43 passed |
| **v5.6 yeni testler (6 dosya)** | **58 passed** |
| **Tam paket** | **920 passed, 0 failed** — `docs/test_ciktisi_v5.6.txt` |
| ruff | **temiz** |

**Önceki turda bayat olan 5 test bu turda YEŞİLE döndü:**

```
test_v51_hardening::TestRegressionGate::test_shipped_reference_is_current
test_v52_hardening::TestVersionConsistency::test_reference_version_matches_when_present
test_v52_hardening::TestPackageRelease::test_consistency_passes_on_shipped_tree
```

Bunlar `docs/backtest_referans.json`'ın sürümünü kontrol ediyor.
Hepsi düzeltildi → **920 passed / 0 failed.**

> **Not:** Önceki turda kullanıcı "sandbox'ta pytest kuramadım, 809/819
> passed iddiasını siz doğrulayın" dedi. Bu turda test çıktısı dosyaya
> yazıldı: `docs/test_ciktisi_v5.6.txt` — ham çıktı, özet değil.

---

## 7. KABUL KRİTERLERİ — KARŞILANMADI

| Kriter | Eşik | Ölçülen | Durum |
|---|---|---|---|
| **Pozitif net beklenti** | > 0 | **−0,32 R** | **BAŞARISIZ** |
| Profit Factor | ≥ 1,30 | **0,30** | **BAŞARISIZ** |
| OOS pozitif | gerekli | koşulmadı | **BAŞARISIZ** |
| WF çoğunluk pozitif | gerekli | **0/3 pencere** | **BAŞARISIZ** |
| Örneklem | ≥ 200–300 | 86 (20 + 66 WF) | **BAŞARISIZ** |
| Veri süresi | ≥ 12 ay | 90 gün | **BAŞARISIZ** |
| Sembol sayısı | 30–50 | 6 | **BAŞARISIZ** |
| Maker dolum | ≥ 300 | 0 | **BAŞARISIZ** |

**→ GERÇEK PARA MODU AÇILMADI. Açılmamalı.**

`live.enabled = False` ve `live_allowed_timeframes = ()` — çift kilit.

---

## 8. KULLANIM

### 8.1 Doğrulama (önerilen)

```bash
python -m tools.validate_strategy \
  --profile kasa1000 \
  --windows 3 \
  --drawdown-peak-mode rolling \
  --out docs/dogrulama.json
```

### 8.2 Şartname tutarlılık denetimi

```bash
python -c "
from core.sizing_audit import SizingSpec, audit
print(audit(0.0033, SizingSpec()))   # SARTNAME_IHLALI
print(audit(0.047861, SizingSpec())) # TUTARLI
"
```

### 8.3 Yeni strateji taraması

```bash
python -m tools.strategy_lab --resample 12 --out docs/lab_1h.json
```

### 8.4 Trailing varyantı

```bash
python -m tools.validate_strategy --profile kasa1000 \
  --trailing-variant B_tp1_sonrasi --windows 0 --out docs/trail_B.json
```

### 8.5 Canlı (ŞU AN KAPALI — açmak için)

```python
# ANCAK kenar kanıtlandıktan sonra, bilinçli olarak:
config.v2.live.live_allowed_timeframes = ("4h",)
ENTRY_EDGE_VERDICTS["4h"] = "GIRIS_KENARI_VAR"
```

---

## 9. YEDEK

v5.4 teslim ZIP'i korundu: `/home/user/ACARBOT_FINAL_v5.4.zip`
Bu turda kaynak ağaç üzerinde çalışıldı; tüm değişiklikler bu
günlükte listelendi ve testlerle doğrulandı.

---

## 10. SONRAKİ TUR İÇİN ÖNCELİK

1. **Veri:** 12 ay × 30–50 sembol, **1h ve 4h** (en yüksek öncelik)
2. **Tek strateji:** `liquidity_sweep_mss` @ 4h — üretim motorunda,
   OOS + WF + Monte Carlo
3. **Funding:** tarihsel CSV'leri indir, kapsama testini geç
4. **Markout:** testnet'te 300 dolum topla (sinyal sıklığı sorunu var)
5. **Gerçek komisyon:** Binance USD-M oranlarını doğrula (şu an varsayım)