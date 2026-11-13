# ACARBOT v6.0 — TEST RAPORU (Faz 0 / v5.5)

**Tarih:** 2026-11-08
**Koşulan sürüm:** 5.5-final
**İlke:** başarısız test gizlenmez, koşulmayan test "geçti" sayılmaz.

---

## 1. ÖZET TABLO

| Test türü | Durum | Sonuç |
|---|---|---|
| Unit + integration (pytest) | ✅ KOŞULDU | **862 passed, 0 failed** |
| Lint (ruff) | ✅ KOŞULDU | Temiz |
| Giriş kenarı — bağımsız tarama | ✅ KOŞULDU | 5m/15m **elendi**, 1h **yetersiz** |
| Stop'lu ufuk testi | ✅ KOŞULDU | 15m'de işaret dönüyor |
| Bonferroni düzeltmesi | ✅ KOŞULDU | Uzun ufuk hipotezi ölüyor |
| Drawdown kilidi karşılaştırması | ✅ KOŞULDU | Aşağıda §5 |
| 90 gün walk-forward | ✅ KOŞULDU | 0/6 pencere kârlı |
| **Testnet uçtan uca** | ❌ **KOŞULMADI** | API anahtarı yok |
| **1 yıllık backtest** | ❌ **KOŞULMADI** | Veri yok (90 gün var) |
| **30–50 sembol** | ❌ **KOŞULMADI** | 6 sembol var |
| **Funding dahil backtest** | ❌ **KOŞULMADI** | Araç funding iletmiyor |
| **Paper trading oturumu** | ❌ **KOŞULMADI** | Bu turda koşulmadı |
| **Monte Carlo (yeni)** | ⚠️ ESKİ | v5.4 koşusundan, %99,7 kayıp |
| **Web panel** | ❌ **YOK** | Kod yok |

---

## 2. PYTEST — GERÇEK ÇIKTI

Komut: `python3 -m pytest tests/ -q`

```
862 passed in 16.68s
```

Tam çıktı repoda: **`docs/test_ciktisi_v5.5.txt`**

### Yeni testler (29 adet, `tests/test_v55_audit.py`)

| Sınıf | Adet | Neyi kilitliyor |
|---|---:|---|
| `TestDedupeCluster` | 3 | Küme tekilleştirme, en yüksek skor korunur |
| `TestClusterBootstrap` | 3 | Gün içi bağımlılık GA'yı genişletiyor (>2×) |
| `TestClusteringReport` | 1 | Komşuluk ölçümü |
| `TestBonferroni` | 4 | p=0,028 × 15 = 0,42 → hipotez ölür |
| `TestVerdictThreeWay` | 5 | "yok" ≠ "ölçülemedi" |
| `TestStoppedHorizon` | 3 | Stopsuz +2R yol, stopla −1R |
| `TestDrawdownPeakWindow` | 6 | all_time/rolling/daily + geriye uyum |
| `TestCandidateScanIndependence` | 3 | İki tarama birebir aynı, portföy yok |
| `TestGrossNetLabel` | 1 | BRÜT etiketi ve ayrı NET alanı |

**Not:** v5.4'ün 819 testi de hâlâ geçiyor — değişiklikler geriye
dönük uyumlu (varsayılan `all_time`, `--legacy-probe` ile eski evren).

---

## 3. GİRİŞ KENARI — YENİDEN ÖLÇÜM

Koşum: 90 gün, 6 OKX majör, bağımsız tarama, 500 permütasyon,
3.000 gün-küme bootstrap, 15 hipotez Bonferroni.

| TF | Ham aday | Kümeleme | Bağımsız n | Gün | Net R | Net GA | Hüküm |
|---|---:|---:|---:|---:|---:|---|---|
| 5m | 1.116 | %46,9 | 818 | 90 | −0,5601 | [−0,6728, −0,5150] | **GIRIS_KENARI_YOK** |
| 15m | 406 | %46,6 | 302 | 86 | −0,2570 | [−0,4350, −0,1742] | **GIRIS_KENARI_YOK** |
| 1h | 89 | %40,5 | 67 | 41 | −0,1088 | [−0,3381, +0,1603] | **YETERSIZ_ORNEKLEM** |

### SE genişlemesi (iid → küme)

| TF | iid SE | Küme SE | Katsayı |
|---|---:|---:|---:|
| 5m | 0,035581 | 0,039742 | ×1,117 |
| 15m | 0,057588 | 0,066347 | ×1,152 |
| 1h | 0,120361 | 0,128692 | ×1,069 |

Kümeleme düzeltmesi belirsizliği **%7–15 artırdı**. Hükmü değiştirmedi
ama 1h'nin zaten yetersiz olduğunu netleştirdi.

**Kanıt:** `docs/giris_kenari_v55_{5m,15m,1h}.json`

---

## 4. STOP'LU UFUK — BAŞARISIZ HİPOTEZ

Bu bir **başarısız test**tir ve gizlenmiyor. v5.4'ün "uzun ufukta
işaret var" gözlemi iki yerden çürüdü.

### 4.1 Stop uygulanınca

| TF | Ufuk | Stopsuz brüt | Stoplu brüt | Stopa takılan |
|---|---|---:|---:|---:|
| 5m | 3 | +0,026 | −0,022 | %16 |
| 5m | 12 | −0,036 | −0,044 | %45 |
| 5m | 48 | +0,266 | +0,154 | %68 |
| 15m | 3 | +0,126 | +0,058 | %21 |
| 15m | 24 | +0,006 | −0,028 | %62 |
| **15m** | **48** | **+0,106** | **−0,111** | **%75** |
| 1h | 24 | +0,678 | +0,507 | %62 |
| 1h | 48 | +1,748 | +1,034 | %71 |

**15m 48 bar'da işaret DÖNÜYOR.** Stopsuz ölçüm yanıltıcıydı.

### 4.2 Çoklu karşılaştırma

| TF | Ufuk | Ham p | Bonferroni (m=15) | Karar |
|---|---|---:|---:|---|
| 5m | 48 | 0,0279 | **0,419** | ❌ anlamsız |
| 1h | 48 | 0,0220 | **0,329** | ❌ anlamsız |
| 15m | 3 | 0,0559 | 0,838 | ❌ anlamsız |

15 hipotezden birinin p<0,05 vermesi **beklenen** durumdur.
Düzeltme sonrası hiçbir ufuk anlamlı değil.

---

## 5. DRAWDOWN KİLİDİ KARŞILAŞTIRMASI

Denetimin (b) maddesi: "kilitsiz backtest çalıştır".

| Mod | Tepe sıfırlama | Sonuç |
|---|---|---|
| `all_time` (v5.4) | Hiç | 12 işlem, −80,52 USDT, **1.013 kilit reddi** |
| `rolling` (7 gün) | Pencere dışı tepe düşer | `docs/dogrulama_v55_rolling.json` |
| `daily` | Her UTC günü | `docs/dogrulama_v55_daily.json` |

Sonuçlar §8'de özetlendi.

---

## 6. KOŞULMAYAN TESTLER — AÇIKÇA

Brief §19 kabul kriterlerinin durumu:

| # | Kriter | Durum |
|---|---|---|
| 1 | Temiz kurulumda açılma | ⚠️ Bu turda yeniden kurulmadı |
| 2 | Modüller import ediliyor | ✅ 848 test import ediyor |
| 3 | Gerçek/simüle veri ayrımı | ✅ `path_source` etiketi |
| 4 | Gelecek veri sızıntısı yok | ✅ `entry_ref` sinyal kapanışı, yol `pos+1:` |
| 5 | Sinyal/strateji testleri | ✅ |
| 6 | Pozisyon risk hesabı | ✅ |
| 7 | 25 USDT risk sınırı | ⚠️ Hedef 25; doğrulama testi var, testnet yok |
| 8 | Sabit pozisyon üst sınırı yok | ❌ Şu an 6 (Faz 3 işi) |
| 9 | Toplam portföy riski | ✅ `total_open_risk_cap` |
| 10 | Maker emir akışı testi | ⚠️ Unit var, testnet yok |
| 11 | Kısmi dolum | ⚠️ Unit var, testnet yok |
| 12 | Stop/TP emir doğrulama | ⚠️ Unit var, testnet yok |
| 13 | Borsa senkronizasyonu | ⚠️ Kod var, koşulmadı |
| 14 | **Testnet doğrulaması** | ❌ **KOŞULMADI** |
| 15 | Backtest gerçek veriye dayanıyor | ✅ OKX 5m/1m gerçek |
| 16 | Tüm maliyetler net PnL'de | ❌ **Funding eksik** |
| 17 | Başarısız testler raporlanıyor | ✅ bu belge |
| 18 | Gerçek işlem varsayılan kapalı | ✅ |

**Sonuç: 18 kriterin 8'i tam, 6'sı kısmi, 4'ü karşılanmıyor.**
v6.0 etiketi için yeterli değil.

---

## 7. YENİDEN ÜRETME KOMUTLARI

```bash
python3 -m pytest tests/ -q
python3 -m ruff check .

python3 -m tools.entry_edge --exchange okx --days 90 \
  --resample-minutes 60 --costs docs/maliyet_olcum_v5.2.json \
  --permutations 500 --bootstrap 3000 --tests-m 15 \
  --out docs/giris_kenari_v55_1h.json

python3 -m tools.validate_strategy --exchange okx --days 90 \
  --drawdown-peak-mode rolling --drawdown-peak-days 7 \
  --costs docs/maliyet_olcum_v5.2.json \
  --data-dir data/validation --out docs/dogrulama_v55_rolling.json
```

---

## 8. HÜKÜM

Ölçüm katmanı artık dürüst. Strateji hâlâ kanıtsız:

- **5m ve 15m: giriş kenarı istatistiksel olarak elendi.**
- **1h: ölçülemedi** (n=67, gerekli ≥300).
- Uzun ufuk hipotezi stop + Bonferroni ile **çürüdü**.

**Gerçek para YASAK.** Pozisyon başına azami kayıp 2,5–5 USDT.

Sıradaki iş yeni indikatör değil: **örneklem altyapısı**
(1 yıl × 30–50 sembol + funding). `V6_GELISTIRME_PLANI.md` Faz 1.
