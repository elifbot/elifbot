# ACARBOT v6.0 — AŞAMA 1: MEVCUT SİSTEM ANALİZİ

**Başlangıç sürümü:** v5.4-final → bu turda v5.5 (denetim düzeltmeleri)
**Analiz tarihi:** 2026-11-08
**Kapsam:** 115 Python dosyası, ~30.000 satır (testler dahil)

> Bu rapor yalnızca **kodda doğrulanmış** olguları içerir. Yapılmamış iş
> yapılmış gibi gösterilmez. Her bölümün sonunda "kanıt" olarak dosya
> yolu veya ölçüm verilir.

---

## 0. YÖNETİCİ ÖZETİ

Üç cümle:

1. **Mühendislik altyapısı gerçekten var** — borsa adaptörleri, koruyucu
   stop, kill switch, durum kalıcılığı, 819 test. Bu kısım sıfırdan
   yazılmamalı.
2. **Strateji tarafında ölçülmüş bir avantaj yok.** 5m'de kenar
   istatistiksel olarak **elendi**; 15m/1h'de **ölçülemedi** (örneklem
   yetersiz). Bu ikisi farklı şeylerdir ve v5.4 bunları karıştırıyordu.
3. **v6.0'ın birinci işi yeni indikatör eklemek değil**, ölçüm
   katmanını dürüstleştirmek ve örneklemi büyütmektir. Bu turda ölçüm
   katmanı düzeltildi (v5.5).

---

## 1. DOSYA AĞACI VE BÜYÜKLÜK

| Katman | Dosya | Satır | İşlev |
|---|---:|---:|---|
| `app/` | 3 | 3.354 | CLI, oturum döngüsü, yapılandırma |
| `core/` | 19 | 5.678 | Sinyal, risk, portföy, rejim, skor |
| `backtest/` | 12 | 3.489 | Motor, maliyet, yol, kapı, istatistik |
| `infra/` | 9 | 1.895 | Borsa API, veri akışı, tick doğrulama |
| `exec/` | 3 | 1.290 | Emir üretimi, paper broker |
| `live/` | 4 | 2.113 | Borsa istemcileri, senkronizasyon |
| `tools/` | 9 | 3.481 | Doğrulama, paketleme, analiz araçları |
| `agents/` | 5 | 586 | Haber/kongre/makro bağlam |
| `monitor/` | 3 | 475 | Panel, rapor |
| `safety/` | 4 | 389 | Alarm, haber freni, güvenlik |
| `state/` | 2 | 370 | Kalıcı durum |
| `tests/` | 42 | 11.312 | 819 test |

**Kullanıcı arayüzü:** JavaScript/HTML/React dosyası **YOK**.
`monitor/dashboard.py` metin tabanlı bir panel üreticisi. v6.0'ın
"modern koyu temalı panel" maddesi **sıfırdan** yapılacak iştir;
mevcut bir web arayüzü geliştirilecek diye bir şey yok.

---

## 2. ÇALIŞAN ÖZELLİKLER (korunacak)

| Özellik | Kanıt |
|---|---|
| Binance USD-M + OKX adaptörleri | `live/broker_clients.py` — `place_entry`, `place_protective_stop`, `place_reduce_only_exit`, `place_post_only`, `cancel_all_after` |
| Koruyucu stop borsaya gönderiliyor | `place_protective_stop` her iki borsada |
| Post-only maker | `place_post_only` (OKX), `post_only` 6 dosyada |
| Kill switch (soft/hard) | `core/risk.py` `evaluate_kill_switch` |
| Korelasyon grupları | `core/config.py` `DEFAULT_CORRELATION_GROUPS` (5 grup) |
| Portföy risk tavanları | `total_open_risk_cap`, `gross_notional_cap`, `net_directional_notional_cap` |
| Order flow iskeleti | `core/orderflow.py` |
| Rejim tespiti | `core/regime.py` — `RegimeDetector` + `SmartRegimeDetector` |
| Çoklu zaman dilimi | `core/mtf.py` `MtfAnalyzer` |
| Durum kalıcılığı | `state/store.py` |
| Canlı eşleme | `live/sync.py` — paper → testnet/demo |
| Maliyet modeli (ölçülmüş) | `docs/maliyet_olcum_v5.2.json`, 10 sembol |
| Regresyon kapısı | `backtest/regression_gate.py`, `tools/package_release.py` |

**Kural:** bu dosyalar yeniden yazılmayacak; genişletilecek.

---

## 3. BU TURDA BULUNAN VE DÜZELTİLEN KUSURLAR (v5.5)

Dış denetim 6 kusur bildirdi. **Altısı da kodda doğrulandı.**
Bir tanesi sanılandan daha kötü çıktı.

### 3.1 Brüt/net etiketi yanlıştı ✅ düzeltildi

`simetrik_1R` maliyet düşülmeden hesaplanıyordu ama zaman dilimi
tablosunda "Simetrik **net**" diye geçiyordu.

Ölçülen gerçek tablo:

| TF | Brüt | Maliyet | **Net** |
|---|---:|---:|---:|
| 5m | −0,0246 | 0,5352 | **−0,5598** |
| 15m | +0,0729 | 0,3319 | **−0,2590** |
| 1h | +0,0669 | 0,1543 | **−0,0874** |

**Düzeltme:** alan adı `simetrik_1R_brut` oldu, ayrı
`simetrik_1R_net` eklendi (küme bootstrap GA ile).

### 3.2 Drawdown kilidi hiç çözülmüyordu ✅ düzeltildi

`core/portfolio.py`: `equity_peak = max(equity_peak, value)` — tüm
zamanların tepesi, **hiç sıfırlanmıyor**. 90 günlük koşuda %8 drawdown
bir kez görülünce ölçekleyici dönem sonuna kadar kilitli kaldı.

**Kanıt:** `docs/dogrulama_v5.4.json` → `OLCEK_TABAN_ALTINDA: 1013`.
Yani "90 günde 12 işlem" aslında "ilk düşüşten sonra ölü dönem".

**Düzeltme:** `drawdown_peak_mode` = `all_time` (varsayılan, geriye
dönük uyumlu) | `rolling` (N gün) | `daily`. Motor
`result.drawdown_peak` içinde tepe sıfırlamalarını ve kilit sayısını
raporluyor.

### 3.3 "Kapısız" aday evreni kapılıydı ✅ düzeltildi

`gate_probe` kaydı şunlardan **sonra** yapılıyordu:
`cooldown.blocked()` → `pipeline.evaluate()` → `rate_limiter.allow()`
ve çağıran döngüde `symbol not in positions and not in pending_limits`.

Yani aday evreni simüle edilen işlemlere bağlıydı.

**Düzeltme:** `backtest/candidate_scan.py` — portföy, broker, cooldown,
hız limiti **hiç kurulmaz**. Yalnız `pipeline.evaluate` çağrılır.

**Dürüstlük notu:** bu tarama "kapısız"dır, "filtresiz" **değildir**.
Pipeline'ın hacim/trend/rejim/fake-breakout filtreleri sinyal
tanımının parçasıdır ve uygulanır. Ölçülen soru: *"sinyalin kendi
filtrelerinden geçenlerinde yön bilgisi var mı?"*

### 3.4 Adaylar bağımsız değildi ✅ düzeltildi — durum sanılandan KÖTÜ

Denetim %26 kümeleme tahmin ediyordu. **Ölçülen %45,9.**

| TF | Aday | Komşulu | Bağımsız | Ayrı gün |
|---|---:|---:|---:|---:|
| 5m | 1.121 | **%45,9** | 818 | 90 |
| 15m | 412 | %46,4 | — | 86 |
| 1h | 105 | %35,2 | — | **46** |

**Düzeltme:** `backtest/robust_stats.py` — 12 bar küme tekilleştirme,
**gün bazlı küme bootstrap**, Bonferroni (15 test).

### 3.5 Hüküm "yok" ile "ölçülemedi"yi karıştırıyordu ✅ düzeltildi

n=105 ve GA üst sınırı maliyetin üstünde olan 1h sonucu "KENAR YOK"
diye damgalanıyordu. O sonuç kenarı **elemiyor**, **ölçemiyor**.

**Düzeltme:** dört durumlu hüküm —
`GIRIS_KENARI_VAR` / `GIRIS_KENARI_YOK` / `YETERSIZ_ORNEKLEM` / `BELIRSIZ`.
Eşik: bağımsız n ≥ 300 **ve** GA üst sınırı ≤ 0 ise "elendi".

### 3.6 Uzun ufuk getirisi stopsuzdu ✅ düzeltildi

`horizon_return` kapanıştan kapanışa, **stopsuz** getiri ölçüyordu.
48 bar +1,48R gibi değerler, gerçek işlemde 1R stopun kestiği
yollardan geliyordu.

**Düzeltme:** `stopped_horizon()` — 1R stop yola uygulanır, mum içi
belirsizlik yine iki sınır. Rapor artık `stopa_takilan_orani` veriyor.

---

## 4. HÂLÂ AÇIK OLAN KUSURLAR (düzeltilmedi)

Bunlar **yapılmadı**; v6.0 iş listesidir.

| # | Eksik | Kanıt | Etki |
|---|---|---|---|
| A | **Funding backtest'e bağlanmıyor** | `tools/validate_strategy.py` içinde `funding` **0 kez** geçiyor | Net PnL eksik hesaplanıyor |
| B | **Testnet doğrulaması yapılmadı** | Kod var (`live/sync.py`), koşu kaydı yok | Emir akışı gerçek ortamda kanıtlanmadı |
| C | **Markout analizi yok** | `markout` kodda **0 dosya** | Dolum kalitesi ölçülmüyor |
| D | **Web panel yok** | JS/HTML dosyası yok | İzleme metin tabanlı |
| E | **1 yıllık veri yok** | Önbellek 90 gün × 6 sembol | Rejim çeşitliliği yok |
| F | **30–50 sembol yok** | 6 majör | Maliyet yalnız majörlerde ölçüldü |
| G | **Binance maliyeti ÖLÇÜLMEDİ** | `maliyet_olcum_v5.2.json` → binance: VARSAYIM | Binance'te gerçek maliyet bilinmiyor |
| H | **Tick/aggTrade dolum modeli yok** | 1m en ince çözünürlük | 45 sn TTL tam çözülemiyor |
| I | **Yapay zekâ modülü yok** | — | İstenen adaptif öğrenme yok |

---

## 5. RİSK YÖNETİMİ: MEVCUT DURUM

### 5.1 Var olanlar

- Pozisyon başı net risk hedefi (komisyon + kayma dahil)
- `total_open_risk_cap` = 150 USDT
- `daily_soft_loss` = 100, `daily_hard_loss` = 150
- Korelasyon grubu başına pozisyon ve notional sınırı
- Brüt/net yönlü notional tavanı
- Kill switch (soft: yeni giriş yok, hard: hepsi kapat)
- Borsada koruyucu stop emri
- v5.5: tepe equity penceresi seçenekleri

### 5.2 Eksik olanlar

| İstenen | Durum |
|---|---|
| Likidasyon mesafesi kontrolü | Kısmi — likidasyon simülasyonu var, giriş öncesi mesafe kontrolü yok |
| Art arda kayıpta soğuma | Var (`RiskScaler` ardışık kayıp bileşeni) |
| Ani volatilitede risk küçültme | Kısmi — spike guard var, boyuta yansımıyor |
| Haftalık/aylık zarar denetimi | **Yok** — yalnız günlük |
| Açık pozisyon stres testi | Kısmi — `BtcShockTester` var |
| Sembol/borsa bazlı risk bütçesi | **Yok** |
| Dolumda gerçek stop riskinin yeniden hesabı | **Yok** |

### 5.3 Sabit pozisyon sayısı sınırı

Brief "sabit üst sınır olmasın" diyor. Mevcut: `max_positions = 6`.
Kod zaten `max_positions = 0 → sınırsız` destekliyor
(`core/risk.py` yorumu). **Ancak** sınırsız pozisyon, ancak
`total_open_risk_cap` ve teminat kontrolü sıkı tutulursa güvenlidir.
Bu değişiklik **Faz 2** işidir ve önce portföy stres testi gerekir.

---

## 6. NEDEN PARA KAYBEDİYOR? — ÖLÇÜLMÜŞ CEVAP

Spekülasyon değil, ölçüm:

```
Gözlenen beklenti (v5.3)      : −0,5679 R
Yazı-tura + maliyet tahmini   : −0,535  R
Simetrik çıkış brüt beklenti  : −0,0246 R   (GA sıfırı kapsıyor)
Skor–ileri getiri korelasyonu :  0,040
```

**Yorum:** giriş yön bilgisi taşımıyor; zarar, kenarsız girişe ödenen
maliyetten ibaret. Çıkış geometrisi bunu değiştirmiyor — ölçüldü:
önerilen geometri iyileşmesinin **%98,6'sı maliyet tasarrufu**,
trailing katkısı yok.

**Yapısal kaldıraç:** `maliyet_payı = maliyet_oranı / stop_kesri`.
Ölçülen %51,0. %15 hedefi için stop 3,40× genişlemeli →
ATR ≈ √zaman → ~1 saat. 1h ölçümü bunu doğruladı (%15,4).

---

## 7. TEST KAPSAMI

- **819 test** (v5.4) → **862 test** (v5.5, +29)
- Kapsam: risk hesabı, emir üretimi, TTL, maliyet, kapı atfı,
  istatistik, paket tutarlılığı
- **Kapsam DIŞI:** gerçek borsa entegrasyonu, testnet uçtan uca,
  web arayüzü, yapay zekâ

Test çıktısı repoda: `docs/test_ciktisi_v5.5.txt`

---

## 8. SONUÇ VE ÖNERİ

v5.4 "iyi mühendislik, kanıtsız strateji" idi. v5.5 ölçüm katmanını
dürüstleştirdi; strateji hâlâ kanıtsız.

**v6.0'a geçiş sırası brief'teki gibi olmalı**, ancak bir düzeltmeyle:
Faz 1'den önce **örneklem altyapısı** (1 yıl × 30–50 sembol) kurulmalı.
Yoksa yeni stratejiler de aynı yetersiz örneklemde test edilir ve
aynı belirsizliği üretir.

Detaylı plan: `V6_GELISTIRME_PLANI.md`
