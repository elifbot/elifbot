# ACARBOT v5.1 — KANIT SERTLEŞTİRME ANALİZİ

**Tarih:** 7 Kasım 2026 · **Sürüm:** `5.1-final` · **Test:** 601 passed + 1 koşullu

Bu doküman, v5.0 incelemesinde tespit edilen boşlukların **nasıl
kapatıldığını** ve **hangilerinin hâlâ açık kaldığını** anlatır.
v5.0 birleşiminin analizi için `ANALIZ_v5.0_DETAYLI.md`.

---

## 0. Neden bu sürüm?

v5.0 doğru bir risk motoru üretti ama **kanıtı zayıftı**:

| Boşluk | Sonucu |
|---|---|
| Belgedeki backtest v3/v4'ten kalma | v5.0'ın sonucu hiç ölçülmemişti |
| Mum içi yol bilinmiyor | "−40 mı −25 mi?" ayırt edilemiyordu |
| Spread/kayma/gecikme sıfır | Backtest yapısal olarak iyimserdi |
| Tek sembol, 7 gün, 8 işlem | İstatistiksel olarak anlamsız |
| Optimizasyon/walk-forward çıktısı yok | Modüller var, kanıt yok |
| Tick kaynağı doğrulanmamış | Izgara hizalama yanlış ızgaraya göre çalışabilirdi |

v5.1 **yeni sinyal eklemez**; bu altı boşluğu araçlaştırır.

---

## 1. Mum içi yol modeli — sorunun kökü ve çözümü

### Kök neden

`exec/paper.py::manage_position_candle` acil net-risk stopunu şöyle
hesaplıyordu:

```python
worst_price = candle.low if position.side == "LONG" else candle.high
if position.net_pnl(worst_price, ...) <= -max_loss_per_position:
    close_position_market(symbol, worst_price, "position_loss_stop", ...)
```

Yani **mumun en kötü ucundan** kapatıyordu. 5 dakikalık bir mumda stop
75.475'te ama iğne 75.810'a gitmişse, pozisyon 75.810'dan kapatılıyor ve
25 USDT hedef 40,31 USDT'ye (1,61R) dönüşüyordu.

**Bu gerçek bir gap mi, yoksa modelin kötümserliği mi?** 5m veriyle
cevaplanamaz: mum içinde fiyatın hangi sırayla hangi seviyeleri gördüğü
bilinmiyor. Gerçekte stop 75.475'te tetiklenmiş olabilir; iğne sonra
gelmiş olabilir.

### Çözüm: `backtest/intrabar.py`

**Birincil yol — gerçek 1m:**
```
5m bar [100.0 → 92.0 iğne → 99.0 kapanış]
  ├─ 1m #1: 99.5 → 98.9   ← stop burada tetiklenir, kayıp ≈ hedef
  ├─ 1m #2: 99.0 → 92.0   (pozisyon artık kapalı)
  └─ ...
```
Stop, tetiklendiği **ilk 1m barda** ve o barın çok daha dar ucundan
kapanır. Regresyon testi bu farkın **%20'den büyük** olduğunu doğruluyor.

**İkincil yol — sentetik sınırlar:** 1m yoksa OHLC'den deterministik yol
üretilir ve iki uç koşulur:
- `adverse_first`: open → aleyhte uç → lehte uç → close (**kötümser**)
- `favorable_first`: open → lehte uç → aleyhte uç → close (**iyimser**)

Tek sayı yerine **aralık** raporlanır. Sentetik yol stop/TP sırasını
belirler ama mum ucunu daraltmaz — bu yüzden acil stop kaybı yine uçtan
hesaplanır. **Gerçek daralma yalnız 1m ile gelir.** Bu ayrım raporda
`path_source` alanında açıkça yazılıdır.

### Güvenlik denetimleri

| Durum | Davranış | Sayaç |
|---|---|---|
| 1m kapsaması eksik | sentetiğe düş | `partial_coverage_bars` |
| 1m uçları 5m ile çelişiyor | sentetiğe düş | `inconsistent_bars` |
| 1m hiç yok | sentetik veya tek adım | `synthetic_bars` |
| Alt mum bar sayacını şişirmesin | `intrabar=True` | — |

Son madde kritik: alt mumlar `bars_held`'i artırsaydı zaman bazlı çıkış
5 kat erken tetiklenirdi. Test ediliyor.

### Yeni ölçüm: stop aşımı

```python
overshoot_ratio(side, entry, stop_level, exit_price)
# 0.0 → tam stop seviyesinden kapandı
# 0.5 → stop mesafesinin yarısı kadar daha kötü
# >1.0 → stop mesafesinden fazla kayma (gap veya model kötümserliği)
```

---

## 2. Gerçek maliyet modeli

### Ölçüm yöntemi — `tools/measure_costs.py`

Canlı emir defterinden, sembol başına N örnek:
- **spread** = (ask1 − bid1) / orta fiyat, baz puan
- **giriş kayması** = hedef nominali **satış** defterinden süpürmenin VWAP sapması
- **çıkış kayması** = aynı süpürme **alış** defterinde
- **gecikme** = REST gidiş-dönüş süresi (gerçek ölçüm)

Medyan alınır; defter yeterince derin değilse örnek sayılmaz ve
`shallow_book_samples` olarak raporlanır.

### Gerçek sonuçlar (OKX, 3.000 USDT nominal, 4 örnek/sembol)

| Sembol | Spread | Giriş kayması | Çıkış kayması | Gecikme |
|---|---|---|---|---|
| BTC-USDT-SWAP | 0,01 bps | 0,0066 bps | 0,0066 bps | 200 ms |
| ETH-USDT-SWAP | 0,04 bps | 0,0224 bps | 0,0224 bps | 191 ms |
| SOL-USDT-SWAP | 1,12 bps | 0,5576 bps | 0,5576 bps | 150 ms |
| XRP-USDT-SWAP | 0,86 bps | 2,7908 bps | 1,9976 bps | 148 ms |
| **DOGE-USDT-SWAP** | 1,39 bps | **21,8745 bps** | **23,9115 bps** | 150 ms |
| **ADA-USDT-SWAP** | 5,50 bps | **14,2751 bps** | **14,4538 bps** | 148 ms |

**Yorum:** BTC/ETH'de 3.000 USDT hiç kayma yaratmıyor. Ama DOGE'de
**%0,22**, ADA'da **%0,14**. 25 USDT hedef net riskle açılan bir DOGE
pozisyonunda nominal ~4.400 USDT olur; gidiş-dönüş kayma tek başına
**~20 USDT** eder — yani hedef riskin **%80'i**. Maliyetleri sıfır sayan
bir backtest bu işlemi kârlı gösterebilir; gerçekte değildir.

Bu, "likidite tabanı 5 USDT/sn" filtresinin neden yetmediğini de gösterir:
taban hacim yeterli olsa bile **anlık defter derinliği** yetersiz olabilir.

### Model davranışı

| Kaynak | Etiket | Kapı |
|---|---|---|
| Ölçülmüş JSON | `measured` / "ÖLÇÜLMÜŞ" | geçer |
| Varsayılan | `defaults_conservative` / "ölçülmedi" | uyarı |
| Bilinçli kapalı | `disabled` / "İYİMSER" | **KIRMIZI** |

Maliyetler artık **varsayılan açık**. Çıkış bacağına kayma uygulanması
yenidir (eski model yalnız girişi kaydırıyordu).

---

## 3. Çok sembollü doğrulama koşucusu

`tools/validate_strategy.py` tek komutla sekiz adım çalıştırır ve
**tek JSON + tek Markdown** üretir. İndirme önbelleklidir; aynı veri
tekrar çekilmez.

**Hüküm mantığı** (öncelik sırasıyla):
1. İşlem sayısı < eşik (varsayılan 200) → **"örneklem yetersiz"**
2. Net PnL ≤ 0 veya MC kayıp olasılığı > %50 → **"kenar yok"**
3. Risk aşımı varsa → **"kenar var ama risk hedefi sapıyor"**
4. Hiçbiri → **"kenar adayı"** (yine de testnet şartı not edilir)

Bu sıralama önemli: **az işlemle pozitif sonuç "kenar var" sayılmaz.**
v3/v4'ün 8 işlemi tam olarak bu tuzağa düşüyordu.

---

## 4. Sürüm regresyon kapısı

`docs/backtest_referans.json` bir **kanıt parmak izi**:

```json
{
  "version": "5.1-final",
  "generated_at": "...",
  "dataset": { "symbols": 6, "days": 90, "total_bars": ..., "fine_bars": ... },
  "cost_model": { "source": "measured", "enabled": true, ... },
  "fixture_metrics": {
    "fingerprint": "sha256...", "trade_count": 4, "net_pnl": -96.471059,
    "win_rate": 0.5, "profit_factor": 0.539367, "rejection_counts": {...}
  },
  "real_metrics": { ... },
  "verdict": "..."
}
```

**Kapının zorunlu kıldığı dört şey:**
1. `version` == paket `__version__` → **bayat sonuç KIRMIZI**
2. Maliyetler açık → **iyimser backtest KIRMIZI**
3. Deterministik fixture yeniden üretilebiliyor (parmak izi + metrikler +
   red sayaçları) → **motor değiştiyse KIRMIZI**
4. Veri kümesi ≥3 sembol / ≥90 gün

Fixture ağ gerektirmez: iki sembol, 400 bar, FADE kurulumu taklidi,
her üçüncü çevrim stopla biter (sonsuz profit_factor'ı önlemek için).
CI'da çevrimdışı yeniden koşulur.

**CI'ya `regression-gate` işi eklendi.** Sürüm numarası atlanıp kanıt
güncellenmezse pipeline kırılır. v5.0'daki bayat backtest dosyası bu
kapıyla otomatik yakalanırdı.

---

## 5. Tick/lot doğrulaması

### Ağ gerçekleri (bu ortamda ölçüldü)

| Kaynak | Sonuç |
|---|---|
| `fapi.binance.com/fapi/v1/exchangeInfo` | **451** |
| `fapi1/2/3.binance.com` | **202, boş gövde** (bot koruması) |
| `dapi.binance.com` | **451** |
| `www.binance.com/bapi/futures/...` | **404** |
| `data-api.binance.vision/api/v3/` (spot) | **200 ✓** |
| `www.okx.com/api/v5/public/instruments` | **200 ✓** |

Yani **Binance vadeli tickSize bu bölgeden doğrulanamıyor.** OKX zaten
kendi kaynağından alıyor, sorun yok.

### İki katmanlı savunma

**Katman 1 — `TickVerifier`:** vadeli kaynakları sırayla dener.
- uyuşma → işlem görür
- **UYUŞMAZLIK → işlem dışı** (politikadan bağımsız, her zaman)
- erişilemiyor → `--tick-policy warn` (varsayılan) veya `strict`

**Katman 2 — `GridObserver`:** API'ye ihtiyaç duymayan ampirik kanıt.
Borsa bir fiyat verdiyse o fiyat gerçek ızgaranın üzerindedir. İddia
edilen tick ile uyuşmuyorsa ızgara **yanlıştır**. Varsayılan 3 ihlalde
sembol işlem dışı kalır, `tick_sizes`'dan düşer ve girişi engellenir.

### Canlı testte gözlenen

```
TICK DOĞRULAMA: vadeli kaynakların HİÇBİRİ yanıt vermedi
  (binance_fapi3: boş yanıt (HTTP 202))
TICK DOĞRULAMA [binance]: kaynak=YOK | eşleşen=0 | UYUŞMAZ=0
  | doğrulanamayan=518 | dışlanan=0 (politika=warn)
TICK DOĞRULAMA [binance]: vadeli kaynak erişilemedi — spot tickSize
  DOĞRULANMADI. Canlı ızgara gözlemi devrede.
```

**Dürüstlük:** `unverified` ≠ "doğrulandı". 518 sembol doğrulanamıyor ve
bu raporda açıkça yazıyor. Sıkı politika istenirse `--tick-policy strict`
ile tümü işlem dışı bırakılır (bot yalnız OKX'te işlem görür).

---

## 7. Oturum sonu risk denetimi

CLOSE kaydına `target_net_risk` ve `stop_loss` eklendi. `audit_trade_risk()`
her kapanış için:

```
realized_over_target = |pnl| / target_net_risk     (yalnızca zararlı işlemlerde)
stop_overshoot_ratio = (stop - çıkış) / stop_mesafesi
breach = realized_over_target > 1.3
```

Rapor bloğu:
```json
"realized_vs_target": {
  "breach_ratio_threshold": 1.3,
  "losing_trades": 3,
  "breach_count": 1,
  "max_realized_over_target": 1.6124,
  "mean_realized_over_target": 1.21,
  "max_stop_overshoot_ratio": 0.61,
  "breaches": [ { "symbol": ..., "pnl": -40.31, "realized_over_target": 1.6124 } ]
}
```

Aşım varsa log'a `RİSK AŞIMI: [sembol] gerçekleşen 40.31 / hedef 25.00 =
1.61x (eşik 1.30x) · stop aşımı 0.61x` düşer. Kullanıcının canlı örneği
artık otomatik yakalanıyor ve test ediliyor.

---

## 6. Paket hijyeni düzeltmeleri

| Bulgu | Düzeltme |
|---|---|
| README dizin ağacı v4.0, "483 test" | v5.1 ağacı, 601 test, 8 yeni modül |
| `requirements.txt` başlığı v3.0 | v5.1 |
| Analiz `safety/` = "kill switch, deadman" diyordu | **Yanlışmış.** `safety/` = `alerts.py` (Telegram, 195 satır), `news_guard.py` (175), `security.py` (sır maskeleme, **19**). Kill switch `core/risk.py`, deadman `app/main.py` + `live/broker_clients.py`, acil düzleştirme `live/sync.py` |
| Analizde kişisel e-posta | Kaldırıldı |
| CI yalnızca kritik ruff | `F,E9,E711,E712,E722` + `regression-gate` işi; **54 lint bulgusu temizlendi** |
| Backtest ızgara uygulamıyordu | `engine.run(tick_sizes=...)` eklendi |

---

## 7b. 15 DAKİKALIK CANLI TEST — v5.1'in ilk gerçek emir kanıtı

**7 Kasım 2026, 18:57:46 → 19:12:46 UTC · tam pazar · apex · trend · 1000 USDT**

v5.0'ın canlı oturumunda **0 emir** vardı; yeni özellikler gerçek akışta
hiç sınanmamıştı. v5.1 testinde durum değişti:

| Ölçüm | Sonuç |
|---|---|
| Süre | **900,0 sn** (tam 15 dk) |
| Feed / ızgara | 1046 sembol / 1046 tickSize |
| Açılan pozisyon | **2** |
| Kapanan işlem | **1** |
| Her pozisyonun hedef net riski | **[25,0 · 25,0]** — tam isabet |
| Izgara yeniden hizalama | **7 kez** |
| `STOP_IZGARA_KABA` reddi | **1** (binance:USTCUSDT) |
| Teminat kilidi iptali | 0 |
| Traceback / kritik hata | **0 / 0** |
| Bakiye | 1000,00 → 976,32 |

### Kapanan işlem — hedef risk denetimi

```
okx:JTO-USDT-SWAP · LONG · TREND_UP · skor 74,9
giriş            : 0,33803238
stop (ızgaralı)  : 0,337
tetikleyici fiyat: 0,337
gerçekleşen çıkış: 0,33683150
brüt zarar       : −19,0830
giriş ücreti     : −1,0743
çıkış ücreti     : −2,6763
kayma            : −2,6776
NET              : −22,8336 USDT
hedef            : 25,0000 USDT
gerçekleşen/hedef: 0,9133x   ← hedefin ALTINDA
stop aşımı       : 0,1632x
1,3x aşımı       : YOK
```

**Yorum:** Stop, ızgaraya hizalanmış (0,337) ve gerçekleşen net zarar
hedefin **%91,3'ü** oldu. v1.8'deki BTTC vakasında bu oran **1,124x**
(−28,10 / 25) idi. Izgara hizalama + gerçek dolum fiyatından boyutlama
canlıda çalışıyor.

### Canlı ızgara gözlemi — tick şüphesine ampirik cevap

```
symbols_checked : 1041
ticks_checked   : 1.290.426
violations      : {} (SIFIR)
rejected_symbols: []
```

**1,29 milyon gerçek borsa fiyatı**, iddia edilen tickSize ızgaralarının
üzerindeydi. Bu, "spot aynası tick'i vadeliyle farklı olabilir" şüphesini
**bu sembol evreni için** ampirik olarak çürütür. Vadeli API hâlâ
erişilemez (518 sembol `unverified`), ama fiyat akışının kendisi ızgaranın
doğru olduğunu gösteriyor. Yine de bu bir ikame kanıttır, resmi doğrulama
değildir.

### Hacim filtresi

| Sayaç | Değer |
|---|---|
| `LİKİDİTE DÜŞÜK` | 1602 |
| `RVOL ŞÜPHELİ` | 35 |
| Bastırılan tekrar | 196 |

Örnek: `okx:OPENAI-USDT-SWAP rvol=778,9 | taban 0,0828 USDT/sn` →
likiditesizlik olarak etiketlendi, veri hatası olarak DEĞİL. Eski sürüm
bunu `ERROR` seviyesinde "birim/veri hatası" diye logluyordu.

---

## 7c. Performans düzeltmesi (bonus)

Doğrulama koşucusu ilk denemede 90 günlük veriyi işleyemedi: **2000 bar
15 saniye** sürüyordu (7,5 ms/bar) ve geçmiş büyüdükçe yavaşlıyordu.

**Kök neden:** `core/indicators.py::_series` her çağrıda tüm geçmişi iki
geçişte doğruluyordu; motor sınırsız geçmiş taşıdığı için maliyet O(n²)'ye
çıkıyordu. 600 barlık profilde **5,4 milyon `isfinite` çağrısı** görüldü.

**Düzeltme:**
1. `_series` tek geçişe indirildi (dönüştür + doğrula aynı döngüde)
2. `_ohlc` yüksek/düşük kontrolü generator yerine indeks döngüsü
3. Motor **400 barlık kayan pencere** taşıyor (göstergeler en fazla ~200
   bar ister: EMA200, ADX14, yapı 60)

**Sonuç:** 2,23 ms/bar (2000 bar) → 2,40 ms/bar (8000 bar). **3,3× hızlanma**
ve artık sabit maliyetli (O(n)). 155.520 barlık koşu ~20 dakikadan ~6
dakikaya indi. Anlam değişmedi; 601 test hâlâ yeşil.

---

## 7d. 90 GÜNLÜK ÇOK SEMBOLLÜ DOĞRULAMA — ilk gerçek hüküm

**Veri:** OKX · 6 sembol (BTC, ETH, SOL, XRP, DOGE, ADA) · 90 gün ·
**155.520** adet 5m bar + **25.920** adet 1m bar · maliyetler **ÖLÇÜLMÜŞ**

### Birincil koşu sonucu

| Metrik | Değer |
|---|---|
| Net PnL | **−87,1110 USDT** |
| İşlem sayısı | **5** |
| Kazanma oranı | **%20** |
| Profit factor | **0,0075** |
| Ortalama kazanç | +0,6544 |
| Ortalama kayıp | **−21,9414** |
| Maksimum drawdown | 87,1110 USDT |
| Monte Carlo kayıp olasılığı | **%99,6** (2000 simülasyon) |

### Hüküm

> 🔴 **KENAR KANITLANMADI — örneklem yetersiz.** Birincil koşuda 5 işlem
> var; istatistiksel hüküm için en az 200 gerekir. Bu sonuçla gerçek
> paraya ölçekleme **YAPILMAMALIDIR**.

### Yeni denetim bir aşımı YAKALADI

```
okx:ETH-USDT-SWAP · position_loss_stop
pnl                : −33,6577
hedef net risk     : 25,0050
gerçekleşen/hedef  : 1,346x   ← 1,3 eşiği AŞILDI, İŞARETLENDİ
stop aşımı         : 0,7755x
```

Bu, kullanıcının bildirdiği 1,61R sapmasının aynısı ve artık **otomatik**
yakalanıyor. 5 işlemin 4'ü zararlı, 1'i (%25) eşiği aştı.

### Red sayaçları — darboğaz doğrulandı

| Gerekçe | Adet | Oran |
|---|---|---|
| **`dusuk_hacim`** | **126.652** | **%81,4** |
| `fade_kosulu_yok` | 12.728 | %8,2 |
| `guclu_trend_fade_kapali` | 5.704 | %3,7 |
| `fake_breakout_or_suspect` | 3.624 | %2,3 |
| `rejim_uyumsuz` | 2.480 | %1,6 |

155.520 barın **%81'i hacim filtresinde eleniyor.** İncelemede söylenen
"~%80" gözlemi doğruydu. Bot bu yüzden 90 günde yalnızca 5 işlem açıyor.

### Dürüst not: 1m kapsaması işlem barlarına denk gelmedi

```
real_1m_bars        : 0
synthetic_bars      : 30
real_coverage_ratio : 0,0
path_source         : adverse_first (sentetik kötümser sınır)
```

1m veri yalnızca **son 3 günü** kapsıyor (OKX geçmişi sınırlı); işlemler
90 günün başka noktalarında oluştu. Bu yüzden birincil koşu sentetik
kötümser yolla sonuçlandı. **Mum içi yol modeli çalışıyor ama bu veri
kümesinde gerçek 1m kanıtı üretmedi.** Gerçek alt çözünürlük için işlem
günlerini kapsayan 1m verisi gerekir.

### Yorum

Bu sonuç v5.0 incelemesindeki şüpheyi **doğrular**: strateji maliyetler
altında kâr üretmiyor. Ortalama kazanç +0,65 / ortalama kayıp −21,94 →
**R:R ≈ 0,03**. %20 kazanma oranıyla bu matematiksel olarak yıkıcıdır.

**v5.1 bunu düzeltmez — ölçülebilir hâle getirir.** Öneri net:
`max_loss_per_position` **2,5–5 USDT**'de tutulmalı, gerçek paraya
geçilmemeli, önce R:R kalibrasyonu yapılmalı.

---

## 8. Hâlâ AÇIK olan sınırlar

Bunlar v5.1'de **kapatılmadı**; dürüstçe listeleniyor:

1. **Gerçek testnet/demo oturumu yok.** `live/` katmanı yalnızca mock
   testlerle sınanmış. Sıradaki adım bu olmalı.
2. **Tam pazar modunda MTF ve order flow kapalı.** 1046 sembolde REST
   yenileme rate limitlerine sığmıyor. En güçlü iki uzman, en geniş modda
   devre dışı. Dar evrende (≤50 sembol) tam çalışır.
3. **Ajanlar backtest'te etkisiz.** Analist/ABD piyasası/RSS/kongre
   yalnızca gözlem üretir; v4.0 backtest'inin v3.0 ile aynı çıkmasının
   sebebi bu.
4. **Binance vadeli tickSize doğrulanamıyor** (bölgesel 451/202). Canlı
   ızgara gözlemi tek ampirik kanıt; bu bir ikame, eşdeğer değil.
5. **1000 USDT bakiyede 25 USDT risk** ancak ~2 eşzamanlı pozisyona yeter.
6. **Kazanç/kayıp asimetrisi düzeltilmedi.** v5.1 ölçüm altyapısı kurar;
   R:R kalibrasyonu strateji işidir ve ayrı bir çalışma gerektirir.
7. **1m kapsaması sınırlı.** 90 günlük 5m veriye karşılık yalnızca son
   birkaç günün 1m verisi indirilebilir (OKX geçmişi sınırlı). Kapsama
   oranı raporda `real_coverage_ratio` olarak yazılır; kalan barlar
   sentetik yolla koşulur.

---

## 9. Ölçekleme önerisi (değişmedi, artık ölçülebilir)

v5.0 analizindeki öneri geçerli, ama artık **veriye dayalı** uygulanabilir:

1. `tools/measure_costs.py` ile maliyetleri ölç (yapıldı)
2. `tools/validate_strategy.py --days 90` ile kenarı test et
3. Hüküm "kenar yok" veya "örneklem yetersiz" ise **`max_loss_per_position`
   2,5–5 USDT'de kalsın**
4. Hüküm "kenar adayı" ise önce **testnet oturumu**, sonra kademeli ölçek
5. Her sürümde `tools/make_reference` ile kanıtı tazele; CI kapısı
   bayatlamayı yakalar
