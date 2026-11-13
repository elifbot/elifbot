# V5.6 — YENİ GİRİŞ STRATEJİLERİ

**Sürüm:** 5.6-final · **Tarih:** 2026-11-08

> **HÜKÜM: 6 stratejinin 6'sı da 5m'de ELENDİ.**
> Üst zaman diliminde 1 tanesi (`liquidity_sweep_mss`) pozitif **nokta
> tahmini** verdi — ama örneklem 41 ve 15, **istatistiksel olarak
> anlamsız. Canlıya hiçbir strateji aktarılmadı.**

---

## 1. YÖNTEM

Şartname: "mevcut stratejinin yalnız parametreleriyle kârlılık arama;
yeni strateji üret, bağımsız test et."

**6 yeni giriş mantığı yazıldı** (`core/entry_strategies.py`), her biri
bağımsız, **3 zaman diliminde**, **6 sembolde**, **90 günde** tarandı.

### 1.1 Tarama simülatörünün sınırları (AÇIKÇA)

`tools/strategy_lab.py` **üretim motoru DEĞİLDİR.** Bir eleme aracıdır:

| Özellik | Tarama | Üretim motoru |
|---|---|---|
| Kısmi kâr alma (TP1) | YOK | var |
| Trailing stop | YOK | var |
| Portföy limitleri | YOK | var |
| Drawdown kilidi | YOK | var |
| Maker/taker ayrımı | YOK (taker, kötümser) | var |
| Çıkış | stop veya +1R | karmaşık |

**Amaç:** giriş sinyalinin HAM kenarını ölçmek, çıkış yönetiminin
etkisini dışarıda bırakmak. Bu yüzden sonuçlar **üretim performans
tahmini değildir.**

### 1.2 Look-ahead koruması (test edildi)

- Sinyal yalnız `candles[:i+1]` kullanır — i. mumun **kapanışına** kadar
- Giriş, sinyalden **sonraki** mumun **açılışından**
- Aynı mumda hem stop hem hedef varsa **ÖNCE STOP** (kötümser)
- Örtüşen işlem yok (pozisyon kapanmadan yeni sinyal alınmaz)
- MTF üst zaman dilimi yalnız **kapanmış** üst-TF mumlarıyla verilir

**Test:** `test_no_lookahead_future_candles_cannot_change_signal` —
i'den sonraki tüm mumlar 3× fiyatla değiştiriliyor, sinyal
**değişmemek zorunda.** 5 stratejide geçti (MTF ayrı test).

### 1.3 Maliyet modeli

```
gidiş-dönüş maliyet = 2 × taker_fee + 2 × kayma
                    = 2 × 0,0005 + 2 × 0,0002 = %0,14
maliyet_R = 0,0014 / stop_oranı
```

Taker kullanıldı (kötümser). Maker varsayımı iyimserlik üretirdi.

---

## 2. STRATEJİLER

| # | Strateji | Mantık |
|---|---|---|
| 1 | `liquidity_sweep_mss` | Önceki dip/tepe süpürülür, kapanış geri döner + önceki mum aşılır (MSS) |
| 2 | `breakout_retest_volume` | 20 mumluk seviye hacimle kırılır, geri test tutar, hacim onayı |
| 3 | `vwap_cvd_momentum` | VWAP geri kazanımı/kaybı + CVD yönü + momentum |
| 4 | `order_block_fvg_structure` | 3 mumlu FVG boşluğuna dönüş + EMA50 yapı yönü |
| 5 | `oi_volume_price_divergence` | Fiyat yükselirken hacim düşüyor + zayıf gövde → tükenme |
| 6 | `trend_continuation_mtf` | Üst TF EMA50 yönü + alt TF EMA20 geri çekilme dönüşü |

### 2.1 Veri dürüstlüğü — YAKLAŞIKLIKLAR

| Strateji | Yaklaşıklık | Gerçek veri gerekli |
|---|---|---|
| `vwap_cvd_momentum` | **CVD**, mum gövdesi oranı × hacim ile yaklaşıklandı | Gerçek alış/satış hacmi ayrımı (order-flow) |
| `oi_volume_price_divergence` | **OI verisi YOK**; hacim vekil kullanıldı | Gerçek open-interest |
| `trend_continuation_mtf` | Üst TF, 5m veriden yeniden örneklendi | Gerçek üst-TF akışı (eşdeğer) |

Bu yaklaşıklıklar her sinyalde `approximation` alanında taşınır ve
rapor JSON'unda listelenir. **Gerçek CVD/OI ölçülmedi.**

`oi_volume_price_divergence` adı bu yüzden yanıltıcıdır — ölçülen şey
**hacim-fiyat uyumsuzluğu**dur, OI değil.

---

## 3. SONUÇLAR — 5m (25.920 bar/sembol, 90 gün)

| Strateji | n | Brüt R | **Net R** | GA95 | PF | WR | Stop % | Hüküm |
|---|---:|---:|---:|---|---:|---:|---:|---|
| liquidity_sweep_mss | 839 | −0,0080 | **−0,6116** | [−0,690, −0,533] | 0,280 | %42,9 | 0,41 | **NEGATİF** |
| breakout_retest_volume | 4.706 | −0,0351 | **−0,7348** | [−0,768, −0,702] | 0,213 | %39,6 | 0,32 | **NEGATİF** |
| vwap_cvd_momentum | 5.599 | −0,0379 | **−0,6275** | [−0,657, −0,598] | 0,270 | %41,4 | 0,40 | **NEGATİF** |
| order_block_fvg_structure | 15.002 | −0,0214 | **−0,9055** | [−0,926, −0,885] | 0,156 | %35,0 | 0,28 | **NEGATİF** |
| oi_volume_price_divergence | 10.819 | −0,0267 | **−1,0673** | [−1,095, −1,039] | 0,108 | %31,1 | 0,22 | **NEGATİF** |
| trend_continuation_mtf | 6.838 | −0,0155 | **−0,6635** | [−0,691, −0,636] | 0,248 | %41,7 | 0,34 | **NEGATİF** |

### 3.1 Kritik gözlem — BRÜT beklenti de negatif

Altı stratejinin brüt beklentisi −0,008 ile −0,038 R arasında.
Yani **maliyet öncesi de kenar yok** (veya ölçülemeyecek kadar küçük).

Ama asıl katil maliyet:

```
örnek: oi_volume_price_divergence
  stop %0,22 → maliyet_R = 0,14 / 0,22 = 0,64R
  brüt −0,027 − 0,64 ≈ −0,67   (ölçülen −1,07; kayma/timeout etkisi ekleniyor)
```

**Sinyal kalitesi ikinci dereceden; birinci dereceden sorun stop/maliyet oranı.**

---

## 4. SONUÇLAR — 1h (5m'den 12× yeniden örnekleme, 2.160 bar/sembol)

| Strateji | n | Brüt R | **Net R** | GA95 | PF | Stop % | Hüküm |
|---|---:|---:|---:|---|---:|---:|---|
| **liquidity_sweep_mss** | **41** | **+0,2116** | **+0,1081** | **[−0,197, +0,413]** | **1,248** | **2,09** | **ANLAMSIZ** |
| breakout_retest_volume | 289 | +0,0096 | −0,1500 | [−0,266, −0,034] | 0,739 | 1,40 | NEGATİF |
| vwap_cvd_momentum | 383 | −0,0017 | −0,1397 | [−0,240, −0,039] | 0,754 | 1,61 | NEGATİF |
| order_block_fvg_structure | 1.006 | −0,0233 | −0,2251 | [−0,287, −0,163] | 0,631 | 1,11 | NEGATİF |
| oi_volume_price_divergence | 800 | −0,0314 | −0,2669 | [−0,336, −0,198] | 0,577 | 0,80 | NEGATİF |
| trend_continuation_mtf | 345 | −0,0399 | −0,1801 | [−0,285, −0,075] | 0,693 | 1,35 | NEGATİF |

---

## 5. SONUÇLAR — 4h (48× yeniden örnekleme, 540 bar/sembol)

| Strateji | n | Brüt R | **Net R** | GA95 | PF | Stop % | Hüküm |
|---|---:|---:|---:|---|---:|---:|---|
| **liquidity_sweep_mss** | **15** | **+0,2474** | **+0,2052** | **[−0,287, +0,697]** | **1,554** | **3,88** | **YETERSİZ ÖRNEKLEM** |
| breakout_retest_volume | 57 | −0,2982 | −0,3633 | [−0,615, −0,112] | 0,476 | 3,29 | NEGATİF |
| vwap_cvd_momentum | 111 | −0,1070 | −0,1698 | [−0,354, +0,014] | 0,705 | 3,19 | ANLAMSIZ |
| order_block_fvg_structure | 259 | −0,0336 | −0,1217 | [−0,244, +0,000] | 0,783 | 2,27 | ANLAMSIZ |
| oi_volume_price_divergence | 167 | −0,0081 | −0,1111 | [−0,261, +0,039] | 0,796 | 1,71 | ANLAMSIZ |
| trend_continuation_mtf | 0 | — | — | — | — | — | SİNYAL YOK |

> 4h'de MTF sinyali yok çünkü üst TF (12×4h = 48h) için yeterli
> geçmiş kalmıyor. Bu bir hata değil, veri sınırı.

---

## 6. ANA BULGU — ZAMAN DİLİMİ ÖLÇEĞİ

`liquidity_sweep_mss` için net beklenti, stop genişledikçe **monoton
iyileşiyor**:

| Zaman dilimi | Ortalama stop | Maliyet/R | **Net beklenti** |
|---|---:|---:|---:|
| 5m | %0,41 | %34 | **−0,6116 R** |
| 1h | %2,09 | %6,7 | **+0,1081 R** |
| 4h | %3,88 | %3,6 | **+0,2052 R** |

Bu, `core/sizing_audit.py`'nin bağımsız olarak öngördüğü sonuca
**deneysel destek** veriyor:

> Şartname (50 USDT marj / 10x / 25 USDT stop) **%4,786 stop** ister.
> 4h'de ölçülen ortalama stop **%3,88** — aynı mertebede.
> 5m'de ölçülen %0,41 — **11,7× daha dar.**

**Şartname bir swing şartnamesidir ve 4h civarı bir rejim gerektirir.**

### 6.1 AMA — bu kanıt DEĞİL

| Neden | Açıklama |
|---|---|
| **Örneklem** | 1h: n=41 · 4h: n=15. Eşik 300. |
| **Güven aralığı** | Her ikisi de sıfırı geniş biçimde kapsıyor |
| **Çoklu test** | 6 strateji × 3 TF = 18 test. Bonferroni ile eşik α/18 = 0,0028. Hiçbiri geçmez. |
| **Seçim yanlılığı** | 18 sonuçtan en iyisini seçmek, tanımı gereği iyimserdir |
| **OOS yok** | Aynı 90 gün; out-of-sample doğrulama yapılmadı |
| **Sembol sayısı** | 6 (şartname 30–50 istiyor) |
| **Süre** | 90 gün (şartname 12 ay istiyor) |
| **Tarama motoru** | Üretim motoru değil; TP1/trailing/DD kilidi yok |

**Bu yüzden `canliya_aday = []` — hiçbir strateji canlıya aktarılmadı.**

---

## 7. NEGATİF BEKLENTİLİ STRATEJİLER CANLIYA ALINMADI

Şartname maddesi karşılandı. `core/gates.py` içine sert kapı eklendi:

```python
live_allowed_timeframes: tuple[str, ...] = ()   # HİÇBİRİ
live_requires_edge_proof: bool = True
```

`ENTRY_EDGE_VERDICTS` sözlüğünde hiçbir zaman dilimi
`GIRIS_KENARI_VAR` değil. Kapı iki koşulu **birlikte** arar;
listeye eklemek tek başına yetmez.

`live/sync.py::mirror_open` bu kapıyı çağırır ve reddedilen girişi
`logger.error` ile kaydeder. **7 test** (`tests/test_v56_live_gate.py`).

---

## 8. ÖNERİLEN SONRAKİ ADIM

**Tek umut verici yön `liquidity_sweep_mss` @ 1h/4h.** Doğrulamak için:

1. **12 ay × 30–50 likit sembol** 1h ve 4h veri topla
2. Yalnız bu stratejiyi **üretim motorunda** koş (TP1/trailing dahil)
3. Walk-forward + **ayrı OOS** penceresi
4. Monte Carlo ile drawdown dağılımı
5. Eşikler: **n ≥ 300**, **PF ≥ 1,30**, **OOS pozitif**, **WF çoğunluk pozitif**
6. Bonferroni: tek strateji test edildiği için m=1 (çoklu test cezası yok)
7. Ancak hepsi geçerse `live_allowed_timeframes = ("4h",)` ve
   `ENTRY_EDGE_VERDICTS["4h"] = "GIRIS_KENARI_VAR"`

**Tahmini veri ihtiyacı:** 12 ay × 4h = 2.190 bar/sembol × 40 sembol
= 87.600 bar. Mevcut: 540 bar × 6 = 3.240. **27× daha fazla veri gerekli.**

---

## 9. KANIT DOSYALARI

| Dosya | İçerik |
|---|---|
| `core/entry_strategies.py` | 6 strateji |
| `tools/strategy_lab.py` | Tarama simülatörü + yeniden örnekleme |
| `docs/strateji_lab_v56.json` | 5m sonuçları |
| `docs/strateji_lab_v56_1h.json` | 1h sonuçları |
| `docs/strateji_lab_v56_4h.json` | 4h sonuçları |
| `tests/test_v56_strategies.py` | 8 test (look-ahead dahil) |
| `tests/test_v56_live_gate.py` | 7 test (canlı kapısı) |