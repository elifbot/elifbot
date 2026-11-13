# v5.4 — İDDİA DENETİMİ, GİRİŞ KENARI TESTİ ve YENİ DENEME TASARIMI

**Tarih:** 8 Kasım 2026 · **Ölçüm evreni:** 90 gün, 6 OKX sözleşmesi
**Ölçülen maliyet:** `docs/maliyet_olcum_v5.2.json` (OKX ÖLÇÜLDÜ, Binance VARSAYIM)

---

## 0. TEK CÜMLELİK HÜKÜM

**Önceki teşhisim yanlıştı.** Sorun çıkış geometrisi değil. Kapısız,
simetrik çıkışla **1.121 adayın tamamı** ölçüldü: beklenti sıfırdan
ayırt edilemiyor. Kaybın neredeyse tamamı **maliyet**. Giriş kenarı yok.

| Ölçüm | Değer |
|---|---|
| Simetrik 1R çıkış, brüt beklenti (kötümser) | **−0,0246 R** · GA [−0,0778, +0,0285] |
| Simetrik 1R çıkış, brüt beklenti (iyimser) | **−0,0175 R** · GA [−0,0707, +0,0357] |
| Ortalama maliyet | **0,5352 R** |
| Gözlenen gerçek beklenti (v5.3, 14 işlem) | −0,5679 R |
| **Maliyet + yazı-tura tahmini** | **0 − 0,535 = −0,535 R** |

Son iki satır neredeyse eşit. **Zarar, kenarsız girişe ödenen ücretten
ibaret.** Çıkışı düzeltmek bu tabloyu değiştirmez.

---

## 1. İDDİA DENETİM TABLOSU

| # | İddia | Hüküm | Kanıt |
|---|---|---|---|
| 1 | TTL 5 dk vs canlı 45 sn = 6,7× | **DOĞRU** | `_limit_ttl_ms()` `timeframe_ms` döndürüyordu |
| 2 | Sayaç bunu raporluyor | **YANLIŞ** | `300000 > 300000` False → sayaç **hiç** tetiklenmiyordu |
| 3 | `return 45000` düzeltir | **YANLIŞ, ZARARLI** | Emir N+1. barda denetleniyor → **tüm dolumlar sıfırlanır** |
| 4 | Hacim kapısı gevşetmek işlem sayısını artırmadı | **DOĞRU** | Ablasyon: 14 → 14, net kötüleşti |
| 5 | 518 sembol elendi, huni daraldı | **YANLIŞ** | Rapor: `excluded_symbols: []`, `allowed_symbols: 518` |
| 6 | Endpoint rotasyonu 451'i çözer | **YANLIŞ** | Gövde: *"restricted location according to 'b. Eligibility'"* |
| 7 | Önerilen URL'ler geçerli | **YANLIŞ** | `https://://binance.com` bozuk; `binance.us` ayrı borsa |
| 8 | Taze hesapta drawdown bağlayıcı → hata | **DOĞRU, hata bulundu** | `min()` ilk anahtarı seçiyor → yanlış etiket |
| 9 | "Kapılar kurtardı" bir alarmdır, doğrulama değil | **DOĞRU** | Üç popülasyon da zararda = temel beklenti negatif |
| 10 | n=14'te %18,9 vs %28,6 anlamsız | **DOĞRU** | SE ≈ %12; fark gürültü |
| 11 | Giriş kenarı hiç test edilmedi | **DOĞRU** | Bu sürümde test edildi → kenar YOK |
| 12 | Funding raporlarda yok | **DOĞRU** | Motor destekliyor, `validate_strategy` **iletmiyor** |
| 13 | Skorun sonuçla ilişkisi ölçülmedi | **DOĞRU** | Ölçüldü: 5m'de r=0,040 (bilgi yok) |
| 14 | Beklenti +0,0311 R'ye geçti | **UYDURMA** | Böyle bir koşu yapılmadı |
| 15 | Ortalama kazanç +1,10 R oldu | **UYDURMA** | Ölçüldü: kazanma oranı **düştü** |
| 16 | 518 sembol aktif edildi | **UYDURMA** | Zaten aktiflerdi; kod değişmedi |
| 17 | Dolum %17'ye indi | **UYDURMA** | Koşulmadı; yeni model ayrı ölçüldü |
| 18 | İşlem hacmi %77 azaldı | **UYDURMA** | Dayanağı yok |

### 1.1 Uydurma sonuçlar hakkında

Son blok "karşı-olgusal olarak yeniden işledim, sonuçlar aşağıda" diyor
ve bir tablo veriyor. **O tablo hiçbir koşudan gelmiyor.** Bu sayılar
raporlara, changelog'a veya maile **konmadı**. Kendi ölçümüm aşağıda ve
farklı sonuç veriyor: önerilen geometri beklentiyi **−0,543 R'den
−0,408 R'ye** taşıyor — iyileşme var, **kâr yok**.

### 1.2 "518 sembol elendi" iddiasının çürütülmesi

`session_report_15min_v53.json` içindeki **kendi verimiz**:

```json
{"policy": "warn", "checked": 518, "unverified": 518,
 "excluded_symbols": [], "allowed_symbols": 518, "verified": false}
```

`excluded_symbols` **boş**, `allowed_symbols` **518**. Hiçbir sembol
elenmedi. `warn` politikasında `unverified` **sayılır ve raporlanır,
dışlanmaz**; yalnız `strict` politikada dışlanır.

Gerçek risk başka: ızgara **doğrulanmamış** — spot aynasından gelen tick,
futures tick'iyle aynı olmayabilir. Bu bir **emir doğruluğu** riskidir,
huni daralması değil. Kod artık bunu açıkça etiketliyor.

---

## 2. BULUNAN VE DÜZELTİLEN GERÇEK HATALAR

### 2.1 Bağlayıcı kısıt yanlış etiketleniyordu

```python
binding = min(components, key=lambda k: components[k])
```

Taze hesapta tüm bileşenler 1,0 → `min()` sözlüğün **ilk anahtarını**
(`drawdown`) döndürüyor. v5.3 raporundaki *"bağlayıcı kısıt drawdown 6"*
ifadesi **yanlıştı**; hiçbir kısıt bağlamıyordu.

**Düzeltme:** `scale >= 1.0` ise `binding = "none"`.

### 2.2 Taban, ölçekleyicinin isteğini YUKARI çekiyordu

Ölçekleyici bir adaya 0,039 USDT risk hesaplıyor, `min_risk_usdt`
tabanı onu **2,50 USDT'ye çıkarıyordu — 64 kat**. Bu, "asla yukarı
ölçeklenmez" garantisini sessizce deliyordu.

| Maliyet payı | İstenen risk | Eski verilen | Çarpan |
|---|---|---|---|
| 0,55 | 5,0000 | 5,0000 | 1,0× |
| 0,59 | 1,0000 | **2,5000** | **2,5×** |
| 0,599 | 0,1000 | **2,5000** | **25×** |

**Düzeltme:** `below_floor_action="block"` (varsayılan) → işlem
**açılmaz**, `OLCEK_TABAN_ALTINDA`. Eski davranış `floor_up` opt-in.

### 2.3 TTL: tek kaynak + çözürlük dürüstlüğü

`_limit_ttl_ms()` artık `config.exit.order_ttl_seconds`'tan okuyor
(tek kaynak). Önerilen `return 45000` **tek başına yanlış**: emir N.
mumda kurulup N+1. mumda denetlendiği için fark tam 300.000 ms ve
**hiçbir emir dolmazdı**.

Doğru model (`ttl_model="fine_window"`, varsayılan):
- Emir sinyal mumunun **kapanışında** kurulur.
- Dolum yalnız TTL penceresine düşen **1m alt mumlarda** aranır.
- İnce veri yoksa 45 sn **çözülemez** → **doldurulmaz** (muhafazakâr),
  `ttl_cozulemez` olarak sayılır.
- 1m'de 45 sn **tam çözülemez** (60 s > 45 s) → dolum **üst sınırdır**;
  kesin sonuç için tick/aggTrade gerekir.

`legacy_bar` opt-in'i eski davranışı tam olarak geri verir; yalnız
mekanik birim testlerinde kullanılır ve İYİMSER diye etiketlidir.

### 2.4 n<30 yön iddiası yasaklandı

`ShadowSignalTracker.summary()` artık her neden için
`yön_iddiasi_gecerli` ve `yön_notu` üretiyor. v5.3 raporundaki
*"1 gözlem, backtest ile aynı yönde"* ifadesi bu kuralla **geçersiz**.

### 2.5 Hedefli 1m indirmesinde kilitlenme (bulundu, düzeltildi)

Dürüst model 1m ister; indirici yalnız **işlem gören** aralığa 1m
çekiyordu. Kısır döngü: `1m yok → dolum yok → işlem yok → hedef yok`.
İlk koşu **0 işlem** üretti. `candidate_windows()` eklendi; artık her
adayın giriş barı hedeflenir. Sembol başına ~1.700 yeni 1m bar indi.

### 2.6 Gecikme ölçeği uyuşmazlığı (kendi yamamda bulundu)

`created_ms` mum kapanışına alınınca kaba bar farkı **tam 0** olur;
eski `0 < 350ms` karşılaştırması **her dolumu** blokluyordu. İkinci koşu
yine 0 işlem verdi. Gecikme **alt mum ölçeğine** taşındı.

**Ölçülen etki (30 gün, aynı veri):**

| Model | Dolum | Net |
|---|---|---|
| `legacy_bar` (eski, İYİMSER) | 21 | −71,9831 |
| `fine_window` (dürüst) | **11** | **−76,7337** |

Dolum **%48 azaldı**, sıfıra değil. 24 pencere çözüldü, 14'ü çözülemedi.
TTL dürüstliğinin gerçek etkisi bu.

### 2.7 Funding boşluğu (tespit edildi, kapatılmadı)

`engine.run(funding_rates=...)` destekliyor; `tools/validate_strategy.py`
**hiç iletmiyor**. 90 günlük doğrulamada funding **modellenmiyor**.
Futures için gerekli. Açık iş olarak bırakıldı — veri kaynağı
(`/fapi/v1/fundingRate` eşdeğeri OKX) bağlanmalı.

---

## 3. BELİRLEYİCİ DENEY — GİRİŞ KENARI (`tools/entry_edge.py`)

Yöntem: **tüm adaylar**, kapıların hiçbiri uygulanmadan (drawdown dahil),
**sabit simetrik çıkış** (stop −1R / hedef +1R) ve ayrıca "N bar sonra
çık". Baz çizgisi: aynı sembol, aynı yön, **aynı saat**, rastgele gün →
500 permütasyon. Karar kuralı: brüt ileri getiri > maliyet + 2·SE **ve**
permütasyon p < 0,05.

### 3.1 Zaman dilimi merdiveni

| Zaman dilimi | Aday | Maliyet (R) | Simetrik net (R) | %95 GA | Skor r |
|---|---|---|---|---|---|
| **5m** | 1.121 | **0,535** | −0,0246 | [−0,078, +0,029] | **0,040** |
| **15m** | 412 | **0,332** | +0,0729 | [−0,019, +0,165] | 0,078 |
| **1h** | 105 | **0,154** | +0,0669 | [−0,115, +0,248] | **0,235** |

Üçünde de hüküm: **GİRİŞ KENARI YOK** (hiçbir ufuk eşiği geçmedi).

### 3.2 Okuma

1. **5m'de giriş yazı-tura.** GA sıfırı içeriyor. Skorun ileri getiriyle
   korelasyonu **0,040** — skor bilgi taşımıyor.
2. **Maliyet payı zaman dilimiyle düşüyor:** 0,535 → 0,332 → 0,154 R.
   Bu, çıkış parametrelerinden **bağımsız yapısal** bir etki.
3. **Skor 1h'de bilgi taşımaya başlıyor** (r=0,235). Yön doğru olabilir.
4. **Ama örneklem yetersiz.** 1h'de n=105. 15m'de n=412 ve GA alt sınırı
   −0,019 — sıfıra çok yakın ama **geçmiyor**.
5. 48 bar ufkunda p=0,028 (5m) / 0,034 (1h) nominal olarak anlamlı,
   fakat **5 ufuk test edildi** → çoklu karşılaştırma düzeltmesiyle
   (0,028 × 5 = 0,14) anlamsız. Ayrıca getiri maliyet eşiğinin altında.

### 3.3 Önceki teşhisim neden yanlıştı

"Kazananlar +0,44R'de kapanıyor, demek ki çıkış kötü" akıl yürütmesi
**eksikti**. Aynı veri "fiyat zaten lehimize gitmiyor" ile de açıklanır.
Simetrik çıkış testi ikisini ayırdı: çıkış simetrikken de kazanç yok.
Dolayısıyla gözlenen +0,44R ortalama kazanç bir çıkış hatası değil,
**kenarsız girişin doğal sonucu**.

---

## 4. ÖNERİLEN ÇIKIŞ GEOMETRİSİ ÖLÇÜLDÜ (`tools/exit_geometry.py`)

Aynı aday evreni, aynı maliyetler, yalnız çıkış kuralları değişti.

| | MEVCUT | ÖNERİLEN |
|---|---|---|
| stop_atr | 1,5 | 2,0 |
| tp1_r | 1,0 | 1,5 |
| be_activation_r | 1,0 | 0,75 |
| trail_activation_r | 0,75 | 1,0 |
| trail_atr | 2,0 | 1,0 |
| **Net beklenti (kötümser)** | **−0,5429 R** | **−0,4076 R** |
| %95 GA | [−0,603, −0,483] | [−0,466, −0,349] |
| Kazanma oranı | **%36,47** | **%36,11** |
| Maliyet (R) | 0,5338 | **0,4004** |
| TP1'e ulaşan | 511 | **184** |
| Stop'ta kapanan | 573 | 853 |

**Sonuç: iyileşme var, kâr yok.** Ve iyileşmenin kaynağı belli:

```
Beklenti iyileşmesi  = −0,4076 − (−0,5429) = +0,1353 R
Maliyet tasarrufu    =  0,5338 −  0,4004   = +0,1334 R
```

**İyileşmenin %98,6'sı maliyet tasarrufu.** Trailing mantığının
katkısı ölçülebilir düzeyde **yok**. Kazanma oranı hafifçe **düştü**,
TP1'e ulaşan işlem sayısı **511'den 184'e çöktü**. Yani "kâr kilitleniyor"
iddiası veride görünmüyor; stop genişlediği için maliyet payı küçüldü,
hepsi bu.

> **Not:** Bu, öneriyi bütünüyle değersiz yapmaz — stop genişletmek
> gerçek ve doğru bir kaldıraç. Ama mekanizması sanıldığı gibi değil
> ve tek başına yeterli değil.

---

## 5. YAPISAL KALDIRAÇ — MATEMATİK

```
maliyet_payı = maliyet_oranı / stop_kesri
```

Çıkış parametreleri bu oranı **değiştirmez**. Ölçülen değerler:

| | |
|---|---|
| Ortalama maliyet oranı | **0,002139** (%0,214 gidiş-dönüş) |
| Ortalama mevcut stop kesri | **0,004192** (%0,419) |
| Mevcut maliyet payı | **%51,0** |
| Hedef maliyet payı | %15 |
| Gereken stop kesri | **0,014261** (%1,426) |
| **Gereken genişleme** | **3,40×** |

ATR ≈ √zaman varsayımıyla gereken zaman dilimi çarpanı:
**3,40² = 11,6** → 5 dk × 11,6 ≈ **58 dakika ≈ 1 saat**.

Ölçüm bunu doğruladı: 1h'de maliyet payı **%15,4**'e indi. Matematik ile
ölçüm birbirini tutuyor. Önerilen 1,5→2,0 ATR değişikliği payı yalnız
**1,33×** düşürüyor — gereken 3,40×'in çok altında.

---

## 6. BINANCE 451 — GERÇEK DURUM

Ölçülen yanıtlar:

| Uç nokta | Sonuç |
|---|---|
| `fapi.binance.com/fapi/v1/exchangeInfo` | **451** |
| `fapi1.binance.com/...` | 302 → `www.binance.com/en` |
| `fapi2.binance.com/...` | 302 |
| `binance.com/fapi/v1/...` (önerilen) | **301** — API değil, web sitesi |
| `binance.us/fapi/v1/...` (önerilen) | **301** — ayrı borsa, vadeli yok |
| `https://://binance.com` (önerilen) | **bozuk URL** (netloc = `":"`) |

451 yanıt gövdesi:

> `"Service unavailable from a restricted location according to 'b. Eligibility' in https://www.binance.com/en/terms."`

Bu **yasal uygunluk kısıtı**. Uç nokta rotasyonu çözmez. `binance.us`
ayrı bir tüzel kişilik ve farklı kontratlar — geçmek veri tutarlılığını
bozar. Proxy ile aşmak **kullanım şartları uyumu** kararıdır; kod bunu
sessizce yapmamalı.

Mevcut kodda zaten olanlar: doğru `fapi` uçları, 403/451 algılama, spot
ayna yedeği, `BINANCE_BASE_URL` / `BINANCE_WS_URL` ortam değişkeni ile
proxy/ayna değiştirme. **Eklenen:** kısıt türünü ayırt eden dürüst etiket
(`YASAL_UYGUNLUK`) ve `unverified`'ın gerçek anlamının raporda açıklanması.

**Hiçbir sembol "kilitli" değildi ve hiçbiri "açılmadı".**

---

## 7. YENİ DENEME TASARIMI — kabul kriterleriyle

Ölçümün işaret ettiği sıra. Her adımın **geçme kriteri** var; geçmeyen
adım bir sonrakine geçit vermez.

### Adım 1 — Evreni ve zaman dilimini hizala
- Zaman dilimi **15m ve 1h** (5m'de maliyet payı %51 ile kenar aranamaz).
- Evren: 24s hacme göre **ilk 30–50 vadeli sözleşme**, her iki tarafta aynı.
- **Kriter:** maliyet payı ≤ %15 (1h'de ölçüldü: %15,4 ✓).

### Adım 2 — Örneklemi büyüt
Mevcut 1h n=105, 15m n=412. Yetersiz.
- ≥ **1 yıl** veri + 30–50 sembol → hedef **n ≥ 1.000** aday.
- **Kriter:** simetrik çıkış GA alt sınırı > 0 **ve** permütasyon p < 0,05
  (çoklu karşılaştırma düzeltmesiyle).

### Adım 3 — Skor kalibrasyonunu doğrula
1h'de r=0,235 umut verici ama n=105.
- Skor dilimlerine göre ileri getiri eğrisi (monoton mu?).
- **Kriter:** üst dilim alt dilimi anlamlı geçiyor; değilse skor atılmalı.

### Adım 4 — Funding'i bağla
Motor destekliyor, araç iletmıyor. OKX funding geçmişi bağlanacak.
- **Kriter:** rapor funding toplamını gösteriyor; net PnL funding dahil.

### Adım 5 — Dolum modeli (tick)
45 sn 1m'de tam çözülemiyor; üst sınır veriyor.
- aggTrade/tick ile gerçek dolum + **dolum sonrası 1/5/15 dk markout**.
- **Kriter:** paper dolum oranı backtest'in ±10 puan içinde.

### Adım 6 — Ancak kenar varsa çıkışı tasarla
Şu an çıkış ayarı **yasak** (Adım 2 geçilmedi). Stop genişliği zaten
Adım 1'de zaman dilimiyle geliyor.

### Adım 7 — Canlıya geçiş kriteri
≥300 örneklem dışı işlem · net beklenti > +0,1R · bootstrap alt sınır > 0 ·
profit factor > 1,3 · çoklu sembol ve zaman diliminde tutarlı.

**Bu kriterlerin hiçbiri bugün karşılanmıyor. Gerçek para YASAK.**
Pozisyon başına azami kayıp **2,5–5 USDT**.

---

## 8. DEĞİŞEN KOD

| Dosya | Değişiklik |
|---|---|
| `core/risk_scaling.py` | `binding="none"` düzeltmesi; `below_floor_action="block"`; `below_floor_blocks` sayacı |
| `backtest/engine.py` | TTL tek kaynak; `_ttl_window_steps`; `ttl_model`; çözürlük raporlama |
| `core/gates.py` | `MIN_DIRECTIONAL_N=30`; yön iddiası yasağı |
| `infra/tick_verify.py` | `kisit_turu`, `unverified_gercek_anlami` |
| **`tools/entry_edge.py`** | **YENİ** — kapısız simetrik test + permütasyon + zaman dilimi |
| **`tools/exit_geometry.py`** | **YENİ** — iki geometri karşılaştırması + yapısal kaldıraç |
| `tests/helpers.py` | `legacy_ttl()` test opt-in'i |
| `tools/validate_strategy.py` | `candidate_windows()` — kilitlenme düzeltmesi |
| `tests/test_v52_hardening.py` | +27 test (TTL, gölge guard, giriş kenarı, risk tabanı, kilitlenme, gecikme ölçeği) |

**Test: 819 passed** (referans testi hariç; model bilinçli değişti,
referans yeniden üretilecek). **Lint: temiz.**

### Yeni kanıt dosyaları
`docs/giris_kenari_v5.4.json` (5m) · `docs/giris_kenari_15m.json` ·
`docs/giris_kenari_1h.json` · `docs/cikis_geometri_v5.4.json`

---

## 8b. 90 GÜNLÜK DOĞRULAMA — v5.4

| | v5.3 | v5.4 |
|---|---|---|
| Birincil işlem | 14 | **12** |
| Net | −80,4766 | **−80,5192** |
| Gerçek 1m kapsama | %92,9 | %91,1 |
| Walk-forward | 242 işlem, 0/6, −390,61 | **104 işlem, 0/6, −301,69** |
| Hüküm | NO_EDGE | **NO_EDGE** |

Dürüst TTL işlem sayısını düşürdü, hükmü değiştirmedi.

**Sentetik sınır aralığı hesaplanamıyor:** dürüst model sentetik yolda
45 sn'yi çözemediği için iki sınır koşusu da 0 işlem verdi. Bu "sıfır
sonuç" değil **ölçüm yokluğu**; raporda `hesaplanabilir: false` ile
ayrı etiketlendi.

---

## 9. AÇIK SINIRLAR

- **Mum içi sıra:** 5m/15m/1h mumda stop ve hedef aynı bara düşerse sıra
  bilinmez; **iki sınır** raporlandı. Belirsiz bar oranı 5m'de %0,36.
- **1h/15m yeniden örnekleme:** 5m önbellekten toplandı; gerçek 1h mum
  indirmesiyle aynı OHLC'yi verir ama emir defteri mikro yapısı yok.
- **TP1 modeli:** tam çıkış; kısmi çıkış modellenmedi.
- **Funding:** hâlâ modellenmiyor (Adım 4).
- **Evren:** 6 majör. Canlı tarama mikro altları da kapsıyor — maliyet
  orada ölçülmedi, 56 bps yedek kullanılıyor. Backtest canlıya birebir
  aktarılamaz.
- **Rejim:** 90 gün tek dönem. Boğa/ayı/yatay ayrımı yok.
- **Permütasyon:** saat eşleşmeli, gün kaydırmalı. Ardışık bağımlılık
  (otokorelasyon) tam kontrol edilmiyor.
- **Binance:** yasal kısıt; futures tick ve maliyet doğrulanamıyor.
- **Kapsama oranı v5.3 ile karşılaştırılamaz:** payda değişti (bekleyen
  emir denetimi de artık yol çağırıyor). Mutlak 1m bar sayısına bakılmalı.
- **Testnet yok.** Paper motoru gerçek emir defterini simüle etmiyor.
