# ACARBOT FINAL v5.3 — Değişiklik Günlüğü

**Sürüm:** `5.3-final` · **Tarih:** 2026-11-08 · **Test:** 790 passed · lint temiz

**Tema:** *"Kapılar bizi kârdan mı etti?" sorusunu ölçülebilir kılmak.*
v5.2 kanıt dürüstlüğünü getirdi. v5.3 **kapı atfını** getiriyor: hangi
kapının hangi adayı reddettiği, o adayın açılması durumunda ne olacağı
ve backtest ile canlı arasındaki kalan sapmalar.

> **Hüküm değişmedi: KENAR YOK.** Bu sürüm stratejiyi düzeltmez;
> sorunun nerede olduğunu **ölçer**. Ölçüm, önceki iki teşhisimi
> çürüttü ve gerçek kök nedeni buldu.

---

## 1. KAPI ATIF ANALİZİ — yeni yetenek

**Soru:** Maliyet kapısı 13 giriş reddetti. Hacim kapısı barların %85'ini
reddediyor. Emirlerin %83'ü dolmuyor. Bunlar bizi kârdan mı etti?

v5.2'de bu soru **cevaplanamıyordu**: reddedilen adaylar hiçbir yerde
kaydedilmiyordu. Gölge izleyici yalnız haber/sweep/ajan kapılarına
bağlıydı ve maliyet kapısı `return` ile sessizce çıkıyordu.

### İki kapı sınıfı, iki yöntem

| Sınıf | Örnek | Yön/stop | Yöntem |
|---|---|---|---|
| **A** — oluşmuş sinyalin reddi | maliyet, drawdown, dolmayan limit | var | karşı-olgusal simülasyon |
| **B** — sinyal hiç oluşmadı | `dusuk_hacim`, `fake_breakout` | **yok** | ablasyon |

B sınıfında "açsaydık ne olurdu?" sorusu **tanımsızdır** — ortada yön
yok. Bunu atlasyıp "hacim kapısı X USDT kârı engelledi" demek uydurma
olurdu. Bu ayrım koda ve rapora işlendi.

### Yeni dosyalar
- **`tools/gate_attribution.py`** — A sınıfı. Her adayı portföyden
  bağımsız, gerçek çıkış kuralları ve ölçülmüş maliyetlerle sonuna
  kadar simüle eder. Giriş anında doldurulur (kapı sorusu dolum
  sorusundan ayrılır).
- **`tools/ablate_gates.py`** — B sınıfı. 12 varyant; aynı veri, aynı
  motor, aynı maliyet, tek değişken ilgili eşik.
- **`engine.gate_probe`** — kancası. Varsayılan `None`; açıkken sonuç
  değişmez (test bunu doğrular).

### Ölçüm sonuçları (90 gün, 6 OKX sembolü)

| Kapı | Aday | Açsaydık net | Kazanma | Ödül/risk | Gereken kazanma |
|---|---|---|---|---|---|
| Drawdown koruması | 1.012 | **−5.539,83** | %49,1 | 0,614 | %62,0 |
| Maliyet kapısı | 90 | **−1.485,74** | **%18,9** | 0,625 | %61,5 |
| Dolmayan limit | 19 | −201,74 | %36,8 | 0,584 | %63,1 |

**Üçü de zarardan kurtardı.** Maliyet kapısının reddettiklerinin kazanma
oranı (%18,9), kabul edilenlerin (%28,6) altında — kapı doğru seçiyor.

---

## 2. İKİ TEŞHİS DÜZELTİLDİ

### 2.1 "Hacim kapısı sistemi kilitliyor" — YANLIŞTI

RVOL eşiği 1,5 → 0,5:

| Red nedeni | TEMEL | RVOL 0,5 |
|---|---|---|
| `dusuk_hacim` | 126.455 | **43.452** (−%66) |
| `fade_kosulu_yok` | 12.703 | **61.054** (+%381) |
| `guclu_trend_fade_kapali` | 5.696 | **26.066** (+%358) |

Sonuç: işlem sayısı **14 → 14** (değişmedi), net −80,65 → **−82,25**
(kötüleşti), kazanma %28,6 → **%21,4**.

Hacim kapısı zincirin **ilk** halkası, darboğaz değil. Kaldırınca
redler bir sonraki filtreye kayıyor. Bu iş öncelik listesinden çıkarıldı.

### 2.2 "Dolum anında stop ötesini iptal et" — YANLIŞTI

15 dk canlı testte GNO emri 26 sn bekledi, fiyat stopun ötesine geçti,
emir doldu ve aynı tick'te stop oldu (`hold_ms=0`, −31,37 USDT).
Kalkan yazdım; **6 test kırıldı**. Kırılan test şunu yazıyordu:

> *"Ters seçilim… Yeni model bu gerçeği simüle eder; **eski kod kaybı
> gizliyordu**."*

Bu davranış **kasıtlı gerçekçilik**. Kalkan, v5.0'da bilinçli olarak
kaldırılan kayıp-gizlemeyi geri getirecekti.

**Çözüm:** varsayılan gerçekçi bırakıldı, yerine **ölçüm** eklendi:

| Alan | Anlamı |
|---|---|
| `adverse_selection.fills_beyond_stop` | stop ötesinde dolan emir |
| `adverse_selection.born_dead_closes` | `hold_ms=0` kapanış |
| `adverse_selection.stale_fill_cancels` | iptal (yalnız opt-in) |
| `adverse_selection.optimistic_stale_cancel` | iyimser politika açık mı |
| `adverse_selection.policy` | `GERÇEKÇİ` / `İYİMSER` |

`exit.cancel_on_stop_breach_at_fill` varsayılan **False**. Açılırsa
rapor **İYİMSER** diye etiketlenir.

---

## 3. CANLI/BACKTEST MALİYET EŞİTLİĞİ — gerçek sapma kapatıldı

Ölçülmüş `CostModel` **yalnız backtest'te** kullanılıyordu. Canlı yol
`config.account`'un düz oranlarını (**15 bps**) kullanıyordu. DOGE'nin
ölçülen ~45 bps'si canlıda görünmüyordu → **canlı backtest'ten
iyimserdi**, iki yol karşılaştırılamıyordu.

- **`--costs PATH`** CLI bayrağı eklendi.
- `CostModel.fee_rates()` ve `round_trip_rate()` public API.
- `PaperBroker.set_symbol_costs()` / `cost_of()` / `exit_cost_rate()` /
  `cost_provenance()` — sembol başına ölçülmüş maliyet.
- Broker dolumları, risk ölçekleyicinin maliyet kapısı ve backtest artık
  **aynı maliyet tanımını** kullanıyor.
- Ölçülmeyen sembol etiketli varsayılanla işlem görür.

15 dk testte ölçüm **1046 sembole** uygulandı.

---

## 4. CANLI RİSK ÖLÇEKLEME KANITI

v5.2'de ölçekleyici canlı yolda vardı ama **raporlanmıyordu**.
"Yazılmış ama etkisiz" hatası (v5.0'da ajanlarda yaşanmıştı) tekrar
edebilirdi: bütçe hesaplanır, `_align_plan_to_grid()` onu ezerdi.

`risk_scaling` bloğu iki şeyi **ayrı** ölçer:
- `budgets_issued` → ölçekleyici çalıştı mı?
- `scaled_down_positions` → bütçe pozisyona yansıdı mı?

`live_effective` ancak ikisi birlikte varsa `true`. Hiç pozisyon
yoksa `null` (**"gözlenemedi"**, "etkisiz" değil). `scaled_up_positions
> 0` ise **ihlal** — log'a ERROR düşer.

**Kanıt (15 dk B turu):** OFC pozisyonu 25,00 yerine **12,9574 USDT**
net riskle açıldı (ölçek 0,5183) → `live_effective=true`.

---

## 5. GÖLGE İZLEYİCİ — iyimser metrik kaldırıldı

Eski özet `would_have_won = max(returns.values()) > 0` kullanıyordu.
Bu **ufuklardan en iyisini seçmek** = ileriye bakıp kiraz toplama.
Fiyat önce stopu vurup sonra yükselse bile "kazanırdı" sayıyordu.

**Yeni:** stop-farkındalıklı **ilk temas**.

| Alan | Anlamı |
|---|---|
| `first_exit` | `STOP` / `HEDEF` — hangisine önce dokundu |
| `once_stop` / `once_hedef` | hangi taraf önce |
| `hedef_orani` | hedef önce oranı |
| `mfe_pct` / `mae_pct` | en yüksek lehimize / aleyhimize hareket |
| `ort_son_getiri_pct` | eldeki en uzun ufkun getirisi |

Aynı gözlemde ikisi de varsa **STOP** sayılır (muhafazakâr).
`would_have_won` ve `avg_best_return_pct` **kaldırıldı**.

**Ufuklar 1/5/15/30/60/120 dk** oldu (eski: 30/60/120). Eski en kısa
ufuk 30 dk idi; 15 dakikalık oturumda **hiçbir gölge olgunlaşmıyordu**.

**Maliyet kapısı reddi artık gölgeye kaydediliyor** — bir daha bu
soruyu cevaplayamaz hale gelmeyelim.

---

## 6. BACKTEST DOLUM İYİMSERLİĞİ — ölçüldü

| | Dolum oranı |
|---|---|
| Backtest (90 gün) | 19 emir → 14 dolum = **%74** |
| Canlı (2 × 15 dk) | 12 emir → 2 dolum = **%17** |

Kök neden `engine._limit_ttl_ms()`:
```python
# Canlıdaki 45 sn TTL'in mum ölçeğinde karşılığı: bir mum boyunca geçerli.
return self.base_config.data.timeframe_ms      # 300.000 ms = 5 dakika
```
Yaklaşım kodda yorum olarak yazılıydı ama **büyüklüğü hiç ölçülmemişti**:
pencere **6,7×** geniş.

**Kanıt:** TTL 45 → 300 sn ablasyonu sonucu **birebir değiştirmedi**
(−80,6453 / 14 işlem / %28,6). Backtestte dolumu TTL değil mum aralığı
belirliyor.

**Yeni ölçüm:** `BacktestResult.fill_optimism` — `toplimit_dolum`,
`ttl_disi_dolum`, `ttl_disi_oran`, `ttl_ms`, `kaba_bar_ms` + uyarı.
30 günlük ölçüm: 39 dolumun **3'ü (%7,7)** 5 dk TTL'den bile sonra.

> Bu sürüm sapmayı **ölçer**, düzeltmez. Düzeltmek 1m yol gerektirir ve
> tüm backtest sonuçlarını değiştirir; ayrı bir iş.

---

## 7. KÖK NEDEN BULUNDU: ÇIKIŞ GEOMETRİSİ

90 günlük birincil koşudaki 14 işlemin tamamı:

| Çıkış nedeni | Adet | Ortalama R | Aralık |
|---|---|---|---|
| `trailing_stop` (kazananların tamamı) | 4 | **+0,439** | +0,189 … +0,787 |
| `stop_loss` | 8 | −0,918 | −0,933 … −0,912 |
| `position_loss_stop` | 2 | **−1,182** | −1,346 … −1,018 |

**Kazananların hiçbiri 1R'ye ulaşmadı. `tp1_r_multiple=1,0` olan TP1
90 günde bir kez bile tetiklenmedi.**

Mekanizma: trailing **0,75R**'de aktifleşiyor ama **2 ATR = 1,33R**
geriden geliyor (ilk stop 1,5 ATR = 1R). Kâr kilitlenemiyor; normal
geri çekilme trailing'i vuruyor. TP1 ve başa baş (ikisi de 1,0R) bu
yüzden hiç devreye girmiyor.

| Ölçüt | Değer |
|---|---|
| Ödül/risk | **0,452** |
| Kazanma | %28,6 |
| Beklenti | **−0,568R** |
| Başabaş için gereken kazanma | **%68,9** |
| Başabaş için gereken ödül/risk | **2,500** |
| **Mevcut oran ihtiyacın kaç katı küçük** | **5,53×** |

### En güçlü kanıt
Drawdown korumasının reddettiği 1.012 aday **%49,1** kazanma oranına
sahipti — neredeyse yazı-tura. Sağlıklı ödül/risk ile kârlı olurdu.
Mevcut geometriyle **−5.539,83 USDT**. **Sorun seçicilik değil.**

### Çıkışı düzeltme denemesi (`RR_KOMBINE`)
TP1 0,5R + trail aktivasyon 1,5R + trail mesafe 0,75 ATR + başa baş 0,4R:

| | TEMEL | RR_KOMBINE |
|---|---|---|
| Kazanma | %28,6 | **%62,5** |
| İşlem | 14 | **40** |
| Ortalama kazanç | +1,546 | **+0,409** |
| Ödül/risk | 0,178 | **0,067** |
| Profit factor | 0,071 | **0,112** |
| Net | −80,6453 | −81,3704 |

Kazanma ikiye katlandı ama ödül çöktü; beklenti negatif kaldı.
**Bu bir düğme ayarı işi değil, çıkış tasarımı işi.** %62,5 isabet
elde edilebiliyor — o isabetle başabaş için ödül/risk ≥ 0,6 yeter,
yani kazananları ~1,0R'de kapatmak gerekiyor.

---

## 8. Test ve kapılar

| | v5.2 | v5.3 |
|---|---|---|
| Test | 721 | **790** |
| Lint | temiz | temiz |
| Sürüm regresyon kapısı | YEŞİL | YEŞİL |
| Rapor tutarlılık kapısı | YEŞİL | YEŞİL |
| Katı JSON | temiz | temiz |

**+69 test:** canlı ölçekleme raporu (15), maliyet eşitliği (16),
ters seçilim dürüstlüğü (13), kapı atfı (13), gölge stop-farkındalığı (8),
kısa ufuklar (4).

Deterministik fixture parmak izi **değişmedi** — strateji mantığı aynı;
tüm değişiklikler canlı yol, raporlama ve analiz araçlarında.

---

## 9. CANLI PAPER TESTİ — 15 dakika

**2026-11-08 07:08:19 → 07:23:19 UTC · 900,0 sn · çıkış 0.**
Ayrıntı: `TEST_RAPORU_15dk_v5.3.md`.

| | |
|---|---|
| Traceback / grid ihlali / ERROR | **0 / 0 / 0** |
| Giriş emri → dolum → kapanış | **4 → 1 → 0** |
| Bakiye / equity | 1000,00 → 999,1416 / **994,7249** |
| Gerçekleşen / gerçekleşmeyen | **0,0000 / −4,4167** |

Dolan: `binance:MUBARAKUSDT` LONG, oturum sonunda hâlâ açık.

### Yeni gölge mekanizması ilk kez canlı veri üretti

Maliyet kapısının reddettiği **3 OKX sinyali** (`PENG`, `INFQ`, `GMX`)
15 dakikalık ufukta olgunlaştı — önceki sürümlerde en kısa ufuk 30 dk
olduğu için 15 dakikalık testte **hiçbiri olgunlaşamıyordu**.

```
blocked 3 · matured 3 · karar_veren 1
once_stop 1 · once_hedef 0
ort_mfe +%0,0784 · ort_mae −%0,1898
```

Karar veren sinyal **önce stop'a dokundu**. Yön, 90 günlük kapı atfıyla
tutarlı (orada reddedilenlerin kazanma oranı %18,9 < kabul %28,6).
**Ancak örneklem 1 gözlemdir** — mekanizmanın çalıştığını kanıtlar,
kapının kârlılığını kanıtlamaz.

### Risk ölçekleme

7 bütçe, 3 engel; bağlayıcı kısıt `drawdown` 6 / `cost` 1.
`GRASS-USDT-SWAP` bütçesi 2,50 USDT tabanına küçültüldü (ölçek 0,0016)
ama emir dolmadı. Dolan tek pozisyon ölçeklenmemişti (net risk 25,00),
bu yüzden **`live_effective = null`**. `never_scaled_up = true`.

**Dürüst sınır:** bu tur kapanmış işlem üretmedi; canlı ölçekleme
etkinliği bu oturumda **kanıtlanmadı**. v5.2 B turundaki
`live_effective = true` kanıtı (OFC, ölçek 0,5183) geçerli ve duruyor.

---

## 10. Yeni dosyalar

| Dosya | İçerik |
|---|---|
| `tools/gate_attribution.py` | A sınıfı kapı karşı-olgusal analizi |
| `tools/ablate_gates.py` | B sınıfı ablasyon (13 varyant tanımlı, 5 koşuldu) |
| `ANALIZ_KAPI_ATFI.md` | 11 bölüm — tüm ölçüm sonuçları |
| `TEST_RAPORU_15dk_v5.2_2tur.md` | 2 turluk canlı test raporu |
| `docs/kapi_atif_v5.2.json` | 1.121 adayın kapı atfı |
| `docs/ablasyon_v5.2.json` | 5 varyantın tam metrikleri |
| `docs/dolum_iyimserligi.json` | TTL dışı dolum ölçümü |
| `canli_kanit_v5.2_15dk_2tur.json` | İki turun birleşik canlı kanıtı |
| **`TEST_RAPORU_15dk_v5.3.md`** | **v5.3 canlı paper testi (9 bölüm)** |
| **`session_report_15min_v53.json`** | **Ham oturum raporu + gölge verisi** |
| **`docs/dogrulama_v5.3.json` / `.md`** | **90 gün doğrulama — `NO_EDGE`** |

---

## 11. Öncelik listesi — ölçümle değişti

| Öncelik | İş | Gerekçe |
|---|---|---|
| **1** | **Çıkış tasarımı** | Ödül/risk 0,452; gereken 2,5 → **5,53× açık** |
| **2** | **Backtest dolum modeli** | 5 dk pencere vs 45 sn gerçek → tüm backtest iyimser |
| 3 | Acil net stop sınırı | −1,35R hedef riski aşıyor |
| ~~—~~ | ~~Hacim kapısı kalibrasyonu~~ | **Ölçüm öncelik olmaktan çıkardı** |
| ~~—~~ | ~~Maker TTL ayarı~~ | Ablasyon etkisiz olduğunu gösterdi |

---

## 12. Açık sınırlar

- **Kenar YOK.** Gerçek paraya ölçekleme yapılmamalı;
  `max_loss_per_position` **2,5–5 USDT** aralığında kalmalı.
- Karşı-olgusal simülasyon portföy etkileşimini model dışı bırakır.
- Karşı-olgusal giriş anında doldu varsayıldı → iyimser; gerçek zarar
  daha büyük olabilirdi.
- Karşı-olgusal yol 5m; 1m doğrulaması yok (ablasyonlar aynı yolu
  kullandı, karşılaştırma geçerli).
- Backtest dolum modeli hâlâ iyimser — ölçüldü, düzeltilmedi.
- Gerçek testnet oturumu yok.
- Tam pazarda MTF + order flow kapalı; ajanlar backtest'te etkisiz.
- Binance vadeli tickSize doğrulanamıyor (HTTP 202/451).
- Binance maliyetleri hiç ölçülmedi — varsayım, etiketli.
- Ölçüm 10 sembolle sınırlı; küçük coinlerde kayma daha kötü olabilir.

---

## 13. Yeniden üretme

```bash
# Kapı atfı (A sınıfı)
python3 -m tools.gate_attribution --days 90 \
  --costs docs/maliyet_olcum_v5.2.json --out docs/kapi_atif_v5.2.json

# Ablasyon (B sınıfı)
python3 -m tools.ablate_gates --days 90 \
  --only TEMEL,MALIYET_KAPISI_KAPALI,HACIM_RVOL_0.5,MAKER_TTL_300,RR_KOMBINE \
  --out docs/ablasyon_v5.2.json

# 15 dk canlı test (ölçülmüş maliyet + gölge izleme)
python3 -m app.main --mode paper --paper --exchange all --scan-all \
  --profile apex --motors trend --balance 1000 --duration-minutes 15 \
  --costs docs/maliyet_olcum_v5.2.json \
  --state test15_v53.sqlite3 --report-file session_report_15min_v53.json

# Paket
python3 -m tools.package_release --check-only
python3 -m tools.package_release --out-dir ..
```
