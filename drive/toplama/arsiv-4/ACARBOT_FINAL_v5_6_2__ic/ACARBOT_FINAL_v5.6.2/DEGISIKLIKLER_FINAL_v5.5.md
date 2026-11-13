# ACARBOT v5.5 — DENETİM DÜZELTMELERİ

**Önceki sürüm:** 5.4-final
**Bu sürüm:** 5.5-final
**Tarih:** 2026-11-08
**Test:** 862 passed (819 → +43) · Lint: temiz

---

## 1. BU SÜRÜM NE YAPAR

Dış denetim v5.4'te 6 kusur bildirdi. **Altısı da kodda doğrulandı**,
biri sanılandan daha kötü çıktı. Bu sürüm o 6 kusuru düzeltir ve
ölçümleri **yeniden koşar**.

Bu bir strateji sürümü **değildir**. Yeni indikatör, yeni strateji,
yeni arayüz yok. Yalnızca ölçüm katmanı dürüstleştirildi.

---

## 2. DÜZELTİLEN 6 KUSUR

### 2.1 Brüt/net etiketi ✅

`simetrik_1R` maliyet düşmüyordu ama tablo "net" diyordu.
Alan `simetrik_1R_brut` oldu; ayrı `simetrik_1R_net` eklendi.

### 2.2 Drawdown kilidi ✅

`equity_peak = max(...)` — tüm zamanların tepesi, hiç sıfırlanmıyor.
90 günlük koşuda **1.013 aday** `OLCEK_TABAN_ALTINDA` ile engellendi.

Yeni: `drawdown_peak_mode` = `all_time` | `rolling` | `daily`.
Varsayılan `all_time` (v5.4 davranışı, geriye dönük uyumlu).
Motor `result.drawdown_peak` içinde sıfırlama anlarını raporlar.

CLI: `--drawdown-peak-mode rolling --drawdown-peak-days 7`

### 2.3 "Kapısız" aday evreni ✅

`gate_probe` kaydı cooldown → pipeline → hız limiti → açık pozisyon
kontrollerinden **sonra** yapılıyordu. Aday evreni işlemlere bağlıydı.

Yeni: `backtest/candidate_scan.py` — portföy/broker/cooldown/hız
limiti **hiç kurulmaz**.

**Dürüstlük notu:** tarama "kapısız"dır, "filtresiz" değildir.
Pipeline'ın hacim/trend/rejim/fake-breakout filtreleri sinyal
tanımının parçasıdır. Ölçülen soru: *"sinyalin kendi filtrelerinden
geçenlerinde yön bilgisi var mı?"* — ham fiyat sorusu değil.

### 2.4 Bağımsızlık varsayımı ✅ — durum sanılandan KÖTÜ

Denetim %26 kümeleme tahmin ediyordu; **ölçülen %46,9**.

Yeni: `backtest/robust_stats.py`
- 12 bar küme tekilleştirme (kümede en yüksek skor tutulur)
- **Gün bazlı küme bootstrap** (gün içi bağımlılık korunur)
- Bonferroni (15 hipotez)

Ölçülen SE genişlemesi: 5m ×1,117 · 15m ×1,152 · 1h ×1,069.

### 2.5 Hüküm ikiliydi ✅

`kenar_var_mi` yoksa "KENAR YOK" deniyordu. Oysa n=105 ve GA üst
sınırı maliyetin üstündeyse kenar **elenmiş değil, ölçülememiş**.

Yeni dört durum: `GIRIS_KENARI_VAR` / `GIRIS_KENARI_YOK` /
`YETERSIZ_ORNEKLEM` / `BELIRSIZ`. Eşik: bağımsız n ≥ 300.

### 2.6 Uzun ufuk stopsuzdu ✅

`horizon_return` kapanıştan kapanışa stopsuz getiriydi.
Yeni `stopped_horizon()`: 1R stop yola uygulanır, iki sınır korunur.

---

## 3. YENİDEN ÖLÇÜLEN SONUÇLAR

Bağımsız tarama + küme istatistiği + 90 gün + 6 OKX majör:

| TF | Ham aday | Küme | Bağımsız n | Gün | Net | Net GA (küme) | Hüküm |
|---|---:|---:|---:|---:|---:|---|---|
| **5m** | 1.116 | %46,9 | **818** | 90 | −0,5601 | [−0,6728, −0,5150] | **KENAR ELENDİ** |
| **15m** | 406 | %46,6 | **302** | 86 | −0,2570 | [−0,4350, −0,1742] | **KENAR ELENDİ** |
| **1h** | 89 | %40,5 | **67** | 41 | −0,1088 | [−0,3381, +0,1603] | **YETERSİZ ÖRNEKLEM** |

**Değişen yorum:**
- 5m sonucu **sağlamlaştı**: artık "bulunamadı" değil, istatistiksel
  olarak **elendi** (GA üst sınırı −0,515 ≤ 0, n=818).
- 15m **yeni hüküm aldı**: bağımsız n=302 eşiği geçti ve GA üst
  sınırı −0,174 ≤ 0 → **elendi**. v5.4'te belirsizdi.
- 1h **doğru etiketlendi**: n=67, GA üst +0,160 → kenar elenmiş
  değil, **ölçülememiş**. v5.4 bunu yanlışlıkla "KENAR YOK" sayıyordu.

---

## 4. STOP'LU UFUK TESTİ — hipotez çürüdü

Denetimin (f) maddesi: uzun ufuk işaretleri stopsuz getiriden
geliyordu. Ölçüm bunu doğruladı:

| TF | Ufuk | Stopsuz brüt | **Stoplu brüt** | Stopa takılan |
|---|---|---:|---:|---:|
| 5m | 48 bar | +0,266 | +0,154 | %68 |
| **15m** | **48 bar** | **+0,106** | **−0,111** | **%75** |
| 1h | 48 bar | +1,748 | +1,034 | %71 |

**15m'de işaret DÖNÜYOR.** Stopsuz +0,106R görünen yol, 1R stop
uygulanınca −0,111R oluyor. Adayların %75'i stopa takılıyor.

1h'de stoplu brüt +1,034R kalıyor ama net GA [−0,509, +2,673] —
belirsizlik devasa, n=67.

### Bonferroni (15 hipotez)

| TF | Ufuk | Ham p | **Düzeltilmiş p** |
|---|---|---:|---:|
| 5m | 48 | 0,0279 | **0,419** |
| 1h | 48 | 0,0220 | **0,329** |

İkisi de 0,05'in çok üstünde. v5.4'ün "uzun ufukta işaret var"
gözlemi **çoklu karşılaştırma artefaktı** idi.

---

## 5. DEĞİŞEN DOSYALAR

| Dosya | Değişiklik |
|---|---|
| `backtest/candidate_scan.py` | **YENİ** — bağımsız tarama (163 satır) |
| `backtest/robust_stats.py` | **YENİ** — küme istatistiği (250 satır) |
| `tools/entry_edge.py` | `stopped_horizon()`, 5 yeni CLI bayrağı, brüt/net ayrımı, küme GA, 4 durumlu hüküm |
| `core/portfolio.py` | `configure_peak()`, `_track_peak()`, `peak_resets` |
| `core/config.py` | `drawdown_peak_mode`, `drawdown_peak_window_days` |
| `backtest/engine.py` | Tepe penceresi bağlantısı, `result.drawdown_peak` |
| `tools/validate_strategy.py` | `--drawdown-peak-mode`, `--drawdown-peak-days` |
| `tests/test_v55_audit.py` | **YENİ** — 29 regresyon testi |
| `docs/test_ciktisi_v5.5.txt` | **YENİ** — gerçek pytest çıktısı |

**Geriye dönük uyumluluk:** varsayılanlar v5.4 davranışını korur
(`drawdown_peak_mode="all_time"`). Eski koşu `--legacy-probe` ile
tekrarlanabilir.

---

## 6. YENİDEN ÜRETME

```bash
# Bağımsız tarama + küme istatistiği (varsayılan)
python3 -m tools.entry_edge --exchange okx --days 90 \
    --resample-minutes 60 --costs docs/maliyet_olcum_v5.2.json \
    --permutations 500 --bootstrap 3000 --tests-m 15 \
    --out docs/giris_kenari_v55_1h.json

# Eski (bulaşık) evrenle karşılaştırma
python3 -m tools.entry_edge --legacy-probe ...

# Drawdown kilidi açık backtest
python3 -m tools.validate_strategy --exchange okx --days 90 \
    --drawdown-peak-mode rolling --drawdown-peak-days 7 \
    --costs docs/maliyet_olcum_v5.2.json --out docs/dogrulama_v55_rolling.json
```

---

## 6b. EK: ZARAR ATFI VE BİR YÜRÜTME HATASI (aynı turda)

Kullanıcı "neden zarar var?" diye sordu. Ölçüm yapıldı
(`tools/loss_attribution.py`, `ZARAR_ANALIZI_v5.5.md`).

**Zararın bileşenleri (20 işlem, −101,07 USDT):**

| Bileşen | Pay |
|---|---:|
| Ters fiyat hareketi | **%69,6** |
| Komisyon | %15,9 |
| Kayma | %14,5 |
| Funding | ~%0 — ÖLÇÜLMEDİ |

**Ana neden:** dolan işlemler adil ±1R çıkışla bile **%70 kaybediyor**.
Çıkış geometrisinin katkısı **+0,03R** — yani suçlu değil.

**Bulunan ve düzeltilen yürütme hatası:** acil sabit-zarar stopu,
yapısal stopla çakıştığında **mumun en kötü fiyatından + ekstra
kaymayla** kapatıyordu. Birim testi: yapısal stop 99,7 iken dolum
98,92'den, zarar 113,37 USDT (4,5R). Düzeltme sonrası 99,65'ten,
40,47 USDT.

90 günlük gerçek etkisi: **−101,07 → −95,43 USDT (%5,6 iyileşme)**,
ödeme oranı 0,19 → 0,29. `position_loss_stop` çıkışı 2 → 0.

**Dürüstlük notu:** ilk taslakta bu hatanın "zararın %33'ü" olduğunu
yazmıştım — yanlıştı, yapay testteki farkı gerçek örnekleme
taşımıştım. Gerçek aşım 9,10 USDT idi.

**Bu turda kendi 3 ölçüm hatamı buldum ve düzelttim:**
1. Simetrik karşılaştırmada trailing sonrası stop kullanımı →
   pozisyona `initial_stop_loss` eklendi
2. Motorun kendi `peak_equity`'si portföy penceresini baypas ediyordu
   → tek kaynağa bağlandı
3. `slippage` çift sayımı ve `gross_pnl`'in TP1 kârını içermemesi
   → muhasebe testlerle kilitlendi

**Bir eski test hatayı kodluyordu:** `test_real_1m_reduces_emergency_stop_loss`
"kaba bar daha çok kaybettirmeli" diye bekliyordu; bu fark hatadan
geliyordu. Düzeltme sonrası eşitlik doğru davranış — test güncellendi.

## 7. AÇIK KALANLAR (yapılmadı)

Bu sürümde **yapılmayan** işler — v6.0 kapsamı:

- Funding hâlâ backtest'e bağlanmıyor (`validate_strategy` içinde 0 geçiş)
- Testnet uçtan uca doğrulaması yapılmadı
- Markout analizi yok
- Web panel yok
- 1 yıllık veri yok, 30–50 sembol yok
- Binance maliyeti hâlâ VARSAYIM
- Tick dolum modeli yok
- Yeni strateji yok

Detay: `V6_ANALIZ_RAPORU.md` §4, `V6_GELISTIRME_PLANI.md`

---

## 8. HÜKÜM

**Gerçek para YASAK.** Pozisyon başına azami kayıp 2,5–5 USDT.

5m ve 15m'de giriş kenarı **istatistiksel olarak elendi**. 1h'de
**ölçülemedi**. Çıkış parametresi optimize etmek bu tabloyu
değiştirmez.

Sıradaki doğru iş: örneklem altyapısı (1 yıl × 30–50 sembol), sonra
yeni giriş mantığı. Faz sırası `V6_GELISTIRME_PLANI.md`'de.
