# 15 Dakikalık Canlı Paper Testi — 2 Tur (2026-11-08)

**Sürüm:** `5.2-final` + test sonrası 3 iyileştirme (aşağıda §7)
**Test paketi:** 765 passed · lint temiz
**Mod:** paper / tam pazar (Binance + OKX) / apex / trend motoru / **ölçülmüş maliyet AÇIK**
**Evren:** 518 Binance + 528 OKX = **1046 feed**

> Gerçek emir gönderilmedi. Tüm dolumlar yerel simülatörde.

---

## 1. Özet

| | A turu | B turu | Toplam |
|---|---|---|---|
| Saat (UTC) | 05:20:57 → 05:35:57 | 05:41:21 → 05:56:21 | 30 dk |
| Süre | 900,0 sn | 900,0 sn | tam |
| Bakiye | 1000 → 968,63 | 1000 → 984,32 | — |
| **Net PnL** | **−31,3734** | **−15,6826** | **−47,0560** |
| Açılan pozisyon | 1 | 1 | 2 |
| Kapanan işlem | 1 | 1 | 2 |
| Kazanan | 0 | 0 | **0** |
| Konan giriş emri | 6 | 6 | 12 |
| Dolan emir | 1 | 1 | 2 |
| Maliyet kapısı reddi | 6 | 7 | **13** |
| Traceback | 0 | 0 | **0** |
| Çıkış kodu | 0 | 0 | temiz |

**İki turda 12 giriş emri kondu, yalnız 2'si doldu.** Kalan 10'u TTL (45 sn) içinde dolmadan süresi doldu. Bu, maker limit stratejisinin düşük dolum oranını gösteriyor — ayrı bir kalibrasyon konusu.

---

## 2. En önemli sonuç: dinamik risk ölçekleme canlıda ETKİN

v5.2'nin 6. maddesi (dinamik risk ölçekleme) backtest'te çalışıyordu. Canlıda gerçekten pozisyona yansıyıp yansımadığı **ilk kez bu testte ölçüldü**.

| | A turu | B turu |
|---|---|---|
| Üretilen bütçe | 6 | 7 |
| Sert maliyet engeli | 6 | 7 |
| Ortalama ölçek | 0,7454 | 0,7771 |
| Minimum ölçek | 0,2309 | **0,0715** |
| Bağlayan bileşen | drawdown 5, cost 1 | drawdown 4, cost 2, recovery 1 |
| Açılan pozisyon | 1 | 1 |
| **Küçültülen pozisyon** | **0** | **1** |
| Büyüyen pozisyon | 0 | 0 |
| Pozisyonun net riski | 25,0000 | **12,9574** |
| **`live_effective`** | `null` (gözlenemedi) | **`true` (KANITLANDI)** |

**B turu belirleyici:** OFC-USDT-SWAP pozisyonu 25,00 USDT yerine **12,9574 USDT** net riskle açıldı — ölçek 0,5183. Bütçe ızgara hizalamasında ezilmedi.

A turunda `live_effective=null` çıktı ve bu **doğru** bir sonuç: ilk pozisyon henüz drawdown yokken açıldı (ölçek 1,0), sonraki küçültülmüş bütçeler pozisyona dönüşmedi. Rapor bunu "etkisiz" diye değil, **"gözlenemedi"** diye işaretliyor. İki durumu ayırmak için ayrı test yazıldı.

### Neden bu ayrım önemli
v5.0'da ajanlar "yazılmış ama etkisiz"di. Aynı hata ölçekleyicide de olabilirdi: bütçe hesaplanır, `_align_plan_to_grid()` onu sabit tavanla ezerdi. Bu yüzden rapora **iki ayrı alan** koydum:
- `budgets_issued` → ölçekleyici çalıştı mı?
- `scaled_down_positions` → çalışan bütçe pozisyona yansıdı mı?

Yalnız birincisi varsa özellik etkisizdir. `scaled_up_positions > 0` ise **ihlal** bildirilir (log'a ERROR düşer).

---

## 3. Ölçülmüş maliyet kapısı canlıda ETKİN

İki turda **13 giriş hiç açılmadı** — `MALIYET_BUTCESI_ASIMI`. Örnekler: PIPPIN, TRX, CRM (OKX).

Bu semboller ölçümde yok; OKX yedek varsayımı uygulanıyor: gidiş-dönüş **56 bps**. Dar stopla (%0,35) maliyet payı %61,6'ya çıkıyor → sert eşik %60 aşılıyor → işlem açılmıyor. Doğru davranış.

### Testten önce kapatılan gerçek sapma
Ölçülmüş `CostModel` **yalnız backtest'te** kullanılıyordu. Canlı yol `config.account`'un düz oranlarını (**15 bps**) kullanıyordu. Sonuç: DOGE'nin ölçülen ~45 bps'si canlıda görünmüyor, **canlı backtest'ten iyimser** oluyordu. İki yol karşılaştırılamıyordu.

Düzeltme: `--costs` bayrağı eklendi. Bu testte ölçüm **1046 sembole** uygulandı:
```
ÖLÇÜLMÜŞ MALİYET: docs/maliyet_olcum_v5.2.json | 1046 sembole uygulandı
binance: VARSAYIM (ÖLÇÜLMEDİ) spread 1.50bps, kayma 2.00bps, çıkış 3.00bps
okx: 10 sembol ÖLÇÜLDÜ; ölçülmeyenler için VARSAYIM spread 1.13 / kayma 23.56 / çıkış 25.63bps
```
Broker dolumları, risk ölçekleyicinin maliyet kapısı ve backtest artık **aynı maliyet tanımını** kullanıyor.

---

## 4. Bulduğum hata sandığım şey — ve neden hata değildi

A turunda GNO-USDT SHORT:
```
05:21:38  GİRİŞ EMRİ: SHORT limit=111.92238 qty=48.38 ttl=45s net_risk=25.00
05:22:04  ENTRY_FILLED @ 111.92238
05:22:04  CLOSE  reason=position_loss_stop  hold_ms=0  pnl=-31.3734
```
Emir 26 sn bekledi; bu sırada fiyat 112,45'e çıktı — stopun (112,26) **ötesine**. Maker simülatörü emri limit fiyatından doldurdu ve pozisyon **aynı tick'te** stop oldu.

İlk tepkim "dolum anında stop ötesini iptal et" oldu ve bir kalkan yazdım. **6 test kırıldı.** Kırılan testlerden biri şunu yazıyordu:

> `test_adverse_selection_gap_fills_then_stops`
> *"Ters seçilim: limit doldu, fiyat stopun da altındaysa aynı tick'te stop. Maker emir tam da fiyatın aleyhte döndüğü anda dolar. Yeni model bu gerçeği simüle eder; **eski kod kaybı gizliyordu**."*

Yani bu davranış **kasıtlı bir gerçekçilik özelliği**. Benim kalkanım v5.0'da bilinçli olarak kaldırılan kayıp-gizlemeyi geri getirecekti. **Kalkanı varsayılan olmaktan çıkardım.**

Doğru çözüm ölçmek oldu:

| Alan | Anlamı |
|---|---|
| `adverse_selection.fills_beyond_stop` | Stop ötesinde dolan emir sayısı |
| `adverse_selection.born_dead_closes` | `hold_ms=0` kapanış sayısı |
| `adverse_selection.stale_fill_cancels` | İptal edilen (yalnız opt-in) |
| `adverse_selection.optimistic_stale_cancel` | İyimser politika açık mı |
| `adverse_selection.policy` | `GERÇEKÇİ` / `İYİMSER` etiketi |

`exit.cancel_on_stop_breach_at_fill` varsayılan **False**. Açılırsa rapor **İYİMSER** diye etiketlenir — çünkü gerçek borsada iptalin dolmadan önce yetişeceği garanti değildir.

**Sonuç: GNO'nun −31,37 USDT'si bir hata değil, gerçekçi bir ters seçilim kaybı.** Bu, tam da senin başından beri istediğin türden dürüstlük.

---

## 5. Risk denetimi

| | A turu | B turu | v5.1 (kıyas) |
|---|---|---|---|
| Zararlı işlem | 1 | 1 | 1 |
| Gerçekleşen / hedef | **1,2549x** | **1,2103x** | 0,9133x |
| Eşik üstü aşım | 0/1 | 0/1 | 0/1 |
| Maks stop aşımı | 0,6877x | 0,4027x | 0,1632x |
| Hedef net risk | 25,00 | **12,9574** | 25,00 |

İki turda da 1,3x eşiği aşılmadı. Ancak **oran v5.1'den yüksek** (0,91 → 1,25 / 1,21). Sebep: her iki işlem de stop tarafında kaymayla kapandı; B turunda hedef küçüldüğü için aynı mutlak kayma daha büyük bir oran üretiyor. Bu, ölçeklemenin beklenen bir yan etkisi — **oran** kötüleşirken **mutlak kayıp** düşüyor (−31,37 → −15,68).

90 günlük backtestteki 1,346x aşım bu iki turda tekrarlanmadı.

---

## 6. Diğer canlı gözlemler

| Gözlem | A turu | B turu |
|---|---|---|
| Izgara sembolü | 1046 | 1046 |
| Izgara yeniden hizalama | 6 | 6 |
| Teminat kilidi iptali | 0 | 0 |
| Bayat sinyal iptali (emir öncesi) | 0 | **1** |
| Gözlenen tick | 1.224.782 | ~1,2 M |
| Izgara ihlali | **0** | **0** |
| İşlem dışı bırakılan sembol | 0 | 0 |
| Düşük likidite reddi | 1842 | — |
| RVOL şüpheli | 40 | — |
| Tam tarama döngüsü | 10 | 10 |

**Red dağılımı (log):**

| Neden | A | B |
|---|---|---|
| `dusuk_hacim` | 2892 (%85,0) | 3024 (%84,5) |
| `trend_onayi_yok` | 366 | 352 |
| `fake_breakout_or_suspect` | 68 | 63 |
| `geri_cekilme_yok` | 65 | 102 |
| `rejim_uyumsuz` | 12 | 35 |
| `dusuk_puan` | 1 | 3 |
| **Toplam** | **3404** | **3579** |

Hacim kapısı canlıda da **%85** red üretiyor — 90 günlük backtestteki %81,3 ile aynı yön. Üçüncü değil, **dördüncü kez** doğrulandı. Bu artık ayrı bir kalibrasyon işi.

**Binance tick doğrulaması yine başarısız:** `binance_fapi3: boş yanıt (HTTP 202)` → 518 sembol `unverified`. Uyuşmazlık 0, dışlanan 0. Canlı ızgara gözlemi (1,2 M tick, 0 ihlal) tek kanıt olarak kullanıldı. Bu sınır değişmedi.

---

## 7. Test sonrası yapılan 3 iyileştirme

Test sırasında bulundu ve kapatıldı. **Teslim edilen v5.2 zip'inde bunlar YOK.**

| # | İyileştirme | Etki |
|---|---|---|
| 1 | Canlı oturum raporuna `risk_scaling` bloğu | Ölçeklemenin canlıda etkin olduğu artık ölçülebilir |
| 2 | `--costs` ile canlı/backtest maliyet eşitliği | Canlı artık backtest'ten iyimser değil |
| 3 | Ters seçilim ölçümü + opt-in iptal politikası | "Doğuşta ölü" dolumlar gizlenmiyor |

**Test sayısı:** 721 → **765** (+44: 15 canlı ölçekleme raporu, 16 maliyet eşitliği, 13 ters seçilim dürüstlüğü)

**Kapılar (yeniden koşuldu):**
- Sürüm regresyon kapısı: **YEŞİL** — deterministik fixture parmak izi **değişmedi** (`c1f0b061…`), yani strateji mantığı aynı. Üç iyileştirme yalnız canlı yol + raporlamayı etkiledi.
- Rapor tutarlılık kapısı: **YEŞİL** (0 hata, 0 uyarı)
- Lint: temiz

---

## 8. Hüküm

**Kenar yok.** İki turun 2 işlemi de zararlı, toplam −47,06 USDT. 30 dakikada 2 işlem **kanıt için fazla küçük** — bu, 90 günlük walk-forward'ın (242 işlem, 0/6 kârlı pencere) yerine geçmez, onu çürütmez de.

**Ancak iki mühendislik kanıtı netleşti:**
1. Dinamik risk ölçekleme canlıda **gerçekten çalışıyor** (B turu: 25,00 → 12,9574 USDT).
2. Ölçülmüş maliyet kapısı canlıda **gerçekten işlem engelliyor** (13 red).

**Gerçek paraya ölçekleme YAPILMAMALI.** `max_loss_per_position` 2,5–5 USDT aralığında kalmalı.

### Açık sınırlar (değişmeyen)
- Gerçek testnet oturumu yok; tüm dolumlar simülasyon.
- Tam pazarda MTF + order flow kapalı.
- Ajanlar backtest'te etkisiz.
- Binance vadeli tickSize doğrulanamıyor (HTTP 202/451).
- Binance maliyetleri hiç ölçülmedi — varsayım, etiketli.
- Ölçüm 10 sembolle sınırlı; küçük coinlerde kayma daha kötü olabilir.
- Maker dolum oranı düşük (12 emir → 2 dolum); ayrı kalibrasyon gerekiyor.
- R:R asimetrisi düzeltilmedi.

### Sıradaki iş (sinyal tarafı)
1. **Hacim kapısı kalibrasyonu** — %85 red, sistemi fiilen kilitliyor.
2. **R:R asimetrisi** — 90 günde ort. kazanç +1,63 / ort. kayıp −8,70.
3. **Maker dolum oranı** — emirlerin %83'ü dolmadan süresi doluyor.

---

## 9. Dosyalar

| Dosya | İçerik |
|---|---|
| `session_report_15min_v52.json` | A turu tam oturum raporu |
| `session_report_15min_v53_b.json` | B turu tam oturum raporu |
| `canli_kanit_v5.2_15dk_2tur.json` | İki turun birleşik kanıt özeti + v5.1 kıyası |
| `test15_v52.sqlite3` / `test15_v53b.sqlite3` | Ayrı durum veritabanları |
| `paper_bot.log` | Her iki turun logu (zaman damgasıyla ayrılabilir) |

### Yeniden üretme
```bash
python3 -m app.main --mode paper --paper --exchange all --scan-all \
  --profile apex --motors trend --balance 1000 --duration-minutes 15 \
  --costs docs/maliyet_olcum_v5.2.json \
  --state test15.sqlite3 --report-file session_report_15min.json
```
