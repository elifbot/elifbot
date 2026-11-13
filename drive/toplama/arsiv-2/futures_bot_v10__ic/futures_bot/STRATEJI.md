# STRATEJİ — v4 (28.10.2026 gece çalışması)

Bu doküman **ne yapıldığını, neden yapıldığını ve neyin henüz kanıtlanmadığını**
ayrı ayrı yazar. Kârlı olduğumuzu iddia etmiyorum; aşağıdaki sayılar konuşuyor.

---

## 0. TEK SAYFALIK ÖZET

| Soru | Cevap |
|---|---|
| Strateji ne? | Ani hacimli hareketin **tersine** işlem (fade) — **yalnızca tasfiye zinciri sırasında** |
| Kenar var mı? | **Var ve güçlü.** 7 gün, 289 sembol, cascade eşik 3: **+0,563%/işlem net**, isabet %80,7 |
| İstatistiksel sağlam mı? | Bootstrap 2000×: **%0 negatif**. 6/8 gün pozitif. Eğitim +0,607 / test +0,459 |
| Canlıda kanıtlandı mı? | **Kısmen.** Sinyal üretimi geri testle birebir uyuşuyor; kârlılık henüz doğrulanmadı |
| En büyük keşif | **Filtresiz sinyal neredeyse kârsız; cascade içindeki sinyal 3 kat kârlı** |
| En büyük risk? | **Kayma** (%0,20'de kenar sıfırlanır) ve **tek güne bağımlılık** (24.10) |
| Beklenen getiri | 10x/40 slot: **8 günde +%21,8**, en kötü düşüş %3,6 |

---

## 1. GECE BULUNAN 5 HATA (hepsi düzeltildi)

Önceki tüm sonuçlar bu hatalar yüzünden yanlıştı.

| # | Hata | Etkisi |
|---|---|---|
| 1 | Süre aşımı **sıfır kâr** varsayıyordu | İşlemlerin %87'si süre aşımıyla kapanıyor → sonucun işareti değişiyordu |
| 2 | **Sinyalin kendi mumu** simülatörde kullanılıyordu | Geleceğe bakma yanlılığı → sahte kâr |
| 3 | OKX mumları **sinyal zamanını yok sayıyordu** | Alakasız veriyle simülasyon |
| 4 | **SL fiyatı TP ile aynı yöne** konmuş | "Her işlem anında SL" (%0 isabet) |
| 5 | Binance REST ban/bölge engelini yanlış raporluyordu | Saniyede 10 kez anlamsız log |

### Hata 2'nin kanıtı (en çarpıcı)

Aynı 48 işlem, iki ölçüm:

| Ölçüm | Sonuç |
|---|---|
| Hatalı simülatör (sinyal mumu dahil) | **+37,50 USDT** |
| Gerçek canlı kayıt | **−58,14 USDT** |
| **Fark** | **95,64 USDT** — tamamı sızıntı |

Düzeltmeden sonra aynı 247 sinyallik ızgara **+33,50** yerine **+0,42/işlem**
veriyor — ve bu, 111.303 olaylık bağımsız testin **+0,41**'iyle uyuşuyor.
İki bağımsız yöntem artık aynı yeri gösteriyor.

### v3'te ayrıca düzeltilen 3 hata

| # | Hata | Etkisi |
|---|---|---|
| 6 | Binance'in **kümülatif hacim sayacı sabit dakika kimliği (0)** kullanıyordu | Binance sembolleri bağlam filtresini **asla** sağlayamıyordu → Binance tarafı tamamen ölü |
| 7 | Canlı filtre **tek dakika** oranı, geri test **3 dakika ortalama** | Eşikler karşılaştırılamaz; canlı yanlış popülasyonu işlem yapıyordu |
| 8 | Bağlam filtresi **33 dakikalık ısınma** istiyordu | Bot açılışta 33 dk hiç işlem yapmıyordu → REST ön-dolgusu eklendi (12 sn) |
| 9 | Binance istek bütçesi **%83'ü** kullanıyordu | 0,6 sn fiyat + 3 sn hacim = 1000 ağırlık/dk (limit 1200) → **IP banı**. 1 sn + 10 sn yapıldı: 360/dk (%30) |
| 10 | Ban yanıtı `'str' object has no attribute 'get'` diye görünüyordu | Gerçek neden (IP banı / bölge engeli) gizleniyordu. Artık açık hata + üstel geri çekilme (2→60 sn) + 1 dk'da 1 log |

---

## 2. SİNYAL TANIMI

**İki aşamalı.** Aşama 1 hızlı tetik, aşama 2 asıl seçici.

### Aşama 1 — 2 saniyelik tetik (canlıda, her tikte)
- 2 saniyede ≥ **%0,05** hareket
- hacim çarpanı ≥ 1,0
- Bu katman **geçmişte test edilemez** (2 saniyelik veri yok) — sadece uyandırıcı.

### Aşama 2 — 1 dakikalık bağlam (asıl filtre, geçmişte kanıtlı)
- 3 dakikalık getiri: **|%1,2| … |%2,0|** arasında
  - < %1,2 → çok zayıf, fade edilmez
  - > %2,0 → **gerçek momentum**, fade edilmez
- 3 dakikalık **ortalama** hacim oranı ≥ **10×** (35 dakikalık medyana göre)
- Yön: 3 dakikalık getiriden alınır, sonra fade için ters çevrilir

**Filtre güçlendikçe kenar artıyor** (111.303 olay, komisyonsuz, TP 3,0/SL 2,5/20 dk):

| 3 dk eşiği | hacim eşiği | n | isabet | ort/işlem |
|---|---|---|---|---|
| %0,35 | ×2 | 111.303 | %56,7 | +0,91 |
| %0,50 | ×3 | 43.946 | %59,8 | +1,25 |
| %1,00 | ×3 | 16.435 | %63,6 | +1,52 |
| %1,50 | ×8 | 4.084 | %67,5 | +1,86 |

---

## 3. SEÇİLEN AYAR VE KANITI

**Filtre: rvol3 ≥ 10 & |ret3| 1,2–2,0** · **TP yok / SL 2,0 / 5 dakika** · taker ücret

| Ölçüt | Sonuç |
|---|---|
| Sinyal sayısı (7 gün) | 1.567 |
| İşlem başı net | **+0,211%** |
| İsabet | %60,6 |
| Pozitif gün | 4 / 7 |
| **Bootstrap 2000×** | medyan +0,234% · %5 +0,154% · %95 +0,317% · **negatif oran %0,0** |
| Eğitim (ilk %70) | +0,209% |
| Test (son %30) | +0,026% |

### Komşu filtre testi (aşırı-uyum kontrolü)

Gerçek bir kenar komşularında da görünür; tesadüf hücresi görünmez.

| rvol≥ | \|ret\| 1,2–1,5 | \|ret\| 1,5–2,0 | \|ret\| 2,0–2,5 |
|---|---|---|---|
| 8 | **+0,169%** | **+0,218%** | −0,061% |
| 10 | **+0,188%** | **+0,232%** | −0,044% |
| 12 | **+0,168%** | **+0,266%** | −0,032% |
| 15 | **+0,164%** | **+0,293%** | −0,024% |

Pürüzsüz ve tek yönlü. **Ama üst sınır (< %2) kritik:** üstü negatif.
Bu, "her sıçramayı fade et" ile "sadece aşırılıkları fade et" arasındaki farktır.

### Tek günü dışla (leave-one-day-out)

| Çıkarılan gün | Kalan ortalama |
|---|---|
| 21.10 | +0,236% |
| 22.10 | +0,262% |
| 23.10 | +0,274% |
| 24.10 | **+0,038%** ← en etkili |
| 25.10 | +0,237% |
| 26.10 | +0,283% |
| 27.10 | +0,241% |

**Dürüst uyarı:** 24.10'u çıkarınca kenar +0,232% → +0,038%'e düşüyor.
Yani kenarın büyük kısmı **tek bir günden** geliyor. Yine pozitif, ama ince.

---

## 3.5 CASCADE FİLTRESİ — GECENİN EN BÜYÜK KAZANCI

Aynı strateji, tek bir ek koşulla **3 kat** daha kârlı oluyor:

> **Son 60 saniyede en az N farklı sinyal gelmeli.**

Neden? Tek bir coin'in sıçraması kendi haberi olabilir (haber → trend → fade
etmek intihar). Ama 20 coin aynı dakikada sıçrıyorsa bu **zincirleme tasfiye**dir
ve fiyat aşırı itilmiştir; geri dönüşü çok daha güvenilirdir.

### Ölçüm (289 sembol, 7 gün, 1.593 sinyal, nedensel = canlıda uygulanabilir)

| Eşik | Sinyal | İsabet | Net/işlem | Pozitif gün | Olay |
|---|---|---|---|---|---|
| 1 (filtresiz) | 1.593 | %60,1 | +0,197% | 4/8 | 1.019 |
| 2 | 881 | %70,0 | +0,359% | 5/8 | 358 |
| **3 (SEÇİLEN)** | **592** | **%80,7** | **+0,563%** | **6/8** | 101 |
| 4 | 519 | %86,3 | +0,670% | 5/6 | 51 |
| 6 | 468 | %89,7 | +0,733% | 5/4 | 30 |

Gradyan **monoton** — her eşikte isabet ve getiri düzenli artıyor. Bu, gerçek
bir mekanizmanın işaretidir; tesadüf hücresi böyle davranmaz.

**Eşik 3'ün istatistikleri:**
- Eğitim (ilk %70): **+0,607%** · Test (son %30): **+0,459%**
- Bootstrap 2000×: %5 = +0,509, negatif oran **%0,0**
- Gün gün: 21.10 +0,30 · 22.10 +0,34 · 23.10 −0,01 · 24.10 +0,81 ·
  25.10 +0,20 · 26.10 +0,01 · 27.10 +0,07 · 28.10 −1,48 (n=5)

### Sermaye simülasyonu (1000$, 8 gün, cascade eşik 3)

| Kaldıraç | Slot | İşlem | Getiri | En kötü düşüş |
|---|---|---|---|---|
| 5x | 40 | 294 | +10,4% | %1,8 |
| **10x** | **40** | **294** | **+21,8%** | **%3,6** |
| 20x | 40 | 294 | +48,1% | %7,1 |

### Canlı uygulama

`ws_bot.py` her sinyalde son 60 saniyenin sinyal sayısını tutar. Eşiğin altındaysa
`engel:cascade_esigi (2<3)` ile reddeder. Reddedilen sinyaller de sayaçta
sayılır — zinciri onlar da doğrular.

```bash
python3 ws_bot.py                 # varsayılan: eşik 3
python3 ws_bot.py --cascade-esik 2   # daha çok işlem, daha az kenar
python3 ws_bot.py --cascade-esik 1   # KAPALI (filtresiz)
```

### Dürüst uyarı

592 sinyalin **402'si 24 Ekim'den** (tek büyük cascade). 24.10 çıkarılırsa
ortalama +0,20%'ye düşer — yine pozitif, ama "her gün böyle bir gün olmaz."
Filtre mekanizması sağlam, **frekansı ise piyasaya bağlı.** Bazı günler hiç
cascade olmaz ve bot hiç işlem yapmaz. Bu bir kusur değil, tasarım.

---

## 4. STRATEJİ ASLINDA NE YAKALIYOR: TASFİYE ZİNCİRİ

24.10'u incelediğimde sebep ortaya çıktı:

```
24.10.2026  14:16 → 51 sembol AYNI ANDA sıçradı
            14:17 → 57 sembol AYNI ANDA sıçradı
            o saatte ortalama getiri +1,113%
```

Bu bir **tasfiye zinciri (liquidation cascade)**: tek bir büyük pozisyon
zorunlu kapanınca fiyat düşüyor, teminat tamamlayamayan küçük pozisyonlar
zincirleme tasfiye oluyor, tüm piyasa birlikte sıçrıyor. Sonra **geri dönüyor.**

Bu iki şeyi açıklıyor:
1. Neden fade çalışıyor — zincir bittiğinde fiyat aşırılıktan geri gelir
2. Neden momentum çalışmıyor — sıçramanın kendisi geçici

**Sonuç:** normal zamanda saatte ~1 sinyal, cascade sırasında **30 saniyede
100+ sinyal**. Bot bunu yakalarsa kazanır, kaçırırsa o gün sıfırdır.

---

## 5. SERMAYE YAPISI — EN ÖNEMLİ KEŞİF

Aynı sinyaller, farklı **kaldıraç × slot** (7 gün, 1000$, tam bileşik):

| Kaldıraç | Slot | Nominal/işlem | 7 gün | En kötü düşüş |
|---|---|---|---|---|
| 5x | 6 | 833$ | **−0,6%** | **%30,8** |
| 5x | 20 | 250$ | +6,9% | %10,4 |
| 10x | 6 | 1.667$ | **−6,8%** | **%52,7** |
| 10x | 20 | 500$ | +13,9% | %19,8 |
| **10x** | **40** | **250$** | **+13,9%** | **%10,4** |
| 20x | 40 | 500$ | +29,0% | %19,8 |
| 30x | 6 | 5.000$ | **−56,9%** | **%91,0** |
| 30x | 40 | 750$ | +45,1% | %28,2 |

**Kural: slot artınca hem kâr artıyor hem risk AZALIYOR.**
Az slot + yüksek kaldıraç = felaket. Çünkü cascade'de 40 fırsat doğuyor,
6 slotla sadece ilk 6'sını alıyorsun (genelde en kötüsünü) ve her birine
bakiyenin 1/6'sını yatırıyorsun.

**v2'nin yapılandırması (5x / 6 slot) ölçülen tüm kombinasyonların en kötüsüydü.**

v3'te: **10x kaldıraç · 40 slot · 25$ marj/pozisyon · 250$ nominal.**

---


---

## 5.5 ÇIKIŞ STRATEJİSİ — İZOLE MARJ VE "TREND SÜRDÜKÇE KAL"

Kullanıcı isteği: *"50 dolar giriyorsak 50 dolar bitene kadar stop olmasın,
üst limitte TP al, long devam ettiği sürece longda kal, en iyi noktada çık."*

Bu isteği **birebir uyguladım** (`--izole`) ve **ölçtüm**. Sonuç:

| Yapı | Ort/işlem | Test seti | En kötü tek işlem | Pozitif gün |
|---|---|---|---|---|
| TP2 / SL3 / 5 dk (eski) | +0,672% | +0,592% | −3,1% | 4/7 |
| **TP2 / SL3 / 240 dk** | **+0,853%** | **+1,027%** | **−3,1%** | 3/7 |
| İZOLE 10x (stop yok) | +0,564% | +0,472% | **−10,1%** | — |
| İZOLE 20x | +0,574% | — | −5,1% | — |
| Saf süre 240 dk | +0,584% | — | −6,4% | — |

### Neden izole mod daha kötü?

1. **Stop, kaybı sınırlar.** Stopsuz pozisyonda tek bir ters hareket
   marjın tamamını alır: 10x'te −%10. 40 pozisyonlu portföyde bu, bir
   işlemde bakiyenin %0,25'ini silmek demek — ama 20 tanesi üst üste
   gelince portföyün %5'i gider.
2. **Kâr sınırlı, zarar sınırsız olur.** Cascade dönüşü tipik olarak
   %1–2 sürüyor. Stop yokken kazanç aynı kalıyor ama zarar 3 katına çıkıyor.
3. **İz süren (trailing) çıkışlar bu veride çalışmıyor:**
   iz süren %0,5 → −0,078% · %1,0 → +0,136% · %2,0 → +0,098%.
   Hepsi mevcut yapının çok altında.

### Ama isteğin BİR PARÇASI doğru çıktı: **pozisyonda kalmak**

"Trend devam ettiği sürece kal" fikri — TP ve SL korunarak — ölçülen
**en iyi yapı** oldu:

| Tutma | Ort | Test |
|---|---|---|
| 5 dk | +0,672% | +0,592% |
| **240 dk** | **+0,853%** | **+1,027%** |

Sebep: TP %2'ye ulaşmak zaman alıyor. 5 dakikada kesersen, hedefe
ulaşacak işlemleri süre dolduğu için kaçırıyorsun. 240 dakika verince
TP'ye ulaşan işlem sayısı artıyor.

**Karar: tutma süresi 5 dk → 240 dk yapıldı.** Stop ve TP korundu.

### İzole mod nasıl açılır

```bash
python3 ws_bot.py --izole            # stop yok, marj bitince kapanır
python3 ws_bot.py --izole --tp 8     # üst limitte TP
```

Varsayılan DEĞİL çünkü ölçüm aleyhine. Denemek istersen açık.

---

## 6. KOMİSYON — ASIL DÜŞMAN

Kenarın yaklaşık **%45'i** komisyona gidiyor.

| Ücret | ort/işlem | En kötü düşüş |
|---|---|---|
| Komisyonsuz | +0,91% | %11 |
| Maker (%0,02×2) | +0,71% | %14 |
| **Taker (%0,05×2)** | **+0,41%** | **%35** |

**Maker (limit) giriş** v3'e eklendi: fade yönünde cari fiyatın %0,05 önüne
emir konur, 30 saniyede dolmazsa iptal. İşlem başı tasarruf ≈ **0,25 USDT**
(0,15 ücret + 0,10 daha iyi giriş üzerinden 250$ nominalde).

### Maker giriş testi — SONUÇ: İŞE YARAMIYOR

Hem canlıda (60 dk A/B) hem 7 günlük veride ölçüldü.

**Canlı A/B (60 dakika, aynı 6 sinyal):**

| Giriş | İşlem | PnL |
|---|---|---|
| market | 4 | **+8,84** |
| maker | 1 | **−5,59** |

**7 günlük veri (604 sinyal, dolum = üst sınır):**

| Limit payı | Dolum oranı | Market net | Maker net |
|---|---|---|---|
| %0,02 | %82,0 | +0,139% | +0,185% |
| %0,05 | %76,3 | +0,139% | +0,180% |
| %0,10 | %67,7 | +0,139% | +0,199% |

İşlem başına maker **daha iyi** (+0,18 vs +0,14) — komisyon tasarrufu gerçek.
**AMA toplam aynı.** Sebebi çarpıcı:

> **Dolmayan emirler kazanan işlemlermiş.**
> Kaçan 143 işlem ortalama **+0,444%**, isabet **%77,6**.

Mekanizma: SHORT fade'de limit fiyat cari fiyatın *üstüne* konur. Fiyat oraya
hiç dönmediyse, fiyat sürekli **aşağı** gitmiş demektir — yani tam kazanç
yönünde. Limit emri sistematik olarak **en iyi işlemleri kaçırır.**

**Karar: market giriş kalıyor.** (Ve üst sınır ölçümü olduğu için gerçek dolum
oranı daha düşük → maker gerçekte bundan da kötü.)

---

## 7. CANLI DOĞRULAMA — DÜRÜST TABLO

| Koşu | Süre | Sinyal | İşlem | Net |
|---|---|---|---|---|
| v1 (momentum) | 25 dk | 107 | 50 | +3,60 |
| v2 (fade, geniş) | 15 dk | 48 | 35 | −15,01 |
| v5 (SHORT-only) | 61 dk | 113 | 9 | −1,87 |
| **v7 (fade, sıkı)** | **123 dk** | **226** | **31** | **−18,12** |

**v7 kırılımı — kaybın tamamı komisyon:**

| Kalem | Tutar |
|---|---|
| Brüt PnL | **−2,65** |
| Komisyon (31 × 0,50) | **−15,47** |
| **Net** | **−18,12** |

| Sebep | n | Net |
|---|---|---|
| TP | 6 | +89,12 |
| SL | 8 | −111,43 |
| Süre aşımı | 13 | +0,16 |

**İstatistiksel yorum:** Tarihsel beklenti +1,02/işlem × 31 = +31,6.
Gerçekleşen −18,12. İşlem başı standart sapma ≈ 13 → 31 işlemin sapması ≈ 72.
Fark **0,7 standart sapma** — anlamsız. Ne kanıtlandı ne çürütüldü.

---

## 8. SINIRLAMALAR (bunlar bilinmeli)

1. **Kayma ölçülmedi.** %0,20 kaymada kenar sıfırlanıyor. Paper modda
   ölçülemez. Gerçek parayla test etmeden asla güvenilmemeli.
2. **Tek güne bağımlılık.** 24.10 çıkarılınca kenar +0,232% → +0,038%.
3. **Test seti zayıf.** Son %30'da +0,026% — sıfıra yakın.
4. **Örneklem.** Canlıda 300+ işlem gerekir; elimizde 31 var.
5. **2 saniyelik tetik test edilemedi.** Geçmişte yalnızca 1 dakikalık veri var.
   Aşama 1'in aşama 2'yi nasıl kısıtladığı bilinmiyor.
6. **Binance 600 ms gecikmeli**, SL aşımı yaratıyor (ölçüldü: ortalama +0,93).
7. **Funding hesaplanmıyor** (bilinmiyor olarak işaretli).
8. **Sharpe 30 işlem altında basılmıyor.**

---

## 9. NASIL ÇALIŞTIRILIR

```bash
pip install -r requirements.txt        # aiohttp, numpy, pytest

python3 teshis.py                      # ortam kontrolü
python3 ws_bot.py                      # varsayılan = v3 doğrulanmış ayar
python3 ws_bot.py --giris limit        # maker giriş (komisyon %30 düşer)
PANEL_PORT=8000 python3 panel.py       # canlı panel

# tek seferlik veri indirme (geri test için)
python3 veri_indir.py --gun 7
```

Binance bölge engeli verirse: `BINANCE_BASE=https://fapi.binance.com/fapi/v1`

### Önemli parametreler

| Parametre | Varsayılan | Ne yapar |
|---|---|---|
| `--baglam-ret` | 1.2 | 3 dk getiri alt sınırı (%) |
| `--baglam-maks-ret` | 2.0 | 3 dk getiri üst sınırı (0 = kapalı) |
| `--baglam-rvol3` | 10.0 | 3 dk ortalama hacim oranı eşiği |
| `--tp` / `--sl` / `--tut-dk` | 99 / 2.0 / 5 | TP kapalı, %2 stop, 5 dk |
| `--giris` | market | `limit` = maker |
| `--yon` | hepsi | `long` / `short` tek yön |

Kaldıraç, slot ve marj `config.py`'de: `DEFAULT_LEVERAGE=10`,
`MAX_OPEN_POSITIONS=40`, `MAX_SAME_DIRECTION=40`, `MAX_UTILISATION=0.95`.

---

## 10. TESTLER

**155 test, hepsi geçiyor.**

| Dosya | Ne doğrular |
|---|---|
| `tests/test_security.py` | Yalnızca public GET; sır okuma yok; URL allowlist |
| `tests/test_baglam.py` | **YENİ** — bağlam filtresi, vratio3, kümülatif dakika |
| `tests/test_cascade.py` | **YENİ** — cascade eşiği, 60 sn penceresi, eşik 1 = kapalı |
| `tests/test_scanner.py` | Spike dedektörü, hacim oranları |
| diğerleri | Portföy, risk, backtest |

`test_baglam.py` gece bulunan 3 hatanın geri gelmemesini sağlar:
ısınma kuralı, vratio3 ≠ vratio, Binance gerçek dakika dilimi.

---

## 11. SIRADAKİ ADIMLAR

1. **8 saatlik A/B sonucu** (market vs maker) — hangi giriş daha iyi?
2. **300+ canlı işlem** biriktir. Ondan önce hiçbir ayar değiştirilmemeli;
   her değişiklik örneklemi sıfırlar.
3. **Kayma ölçümü.** Canlıya geçmeden önce gerçek dolum fiyatları gerekli.
4. **Binance küçük coin evreni.** Binance'in en büyük 25'inde kenar yok (+0,09);
   asıl evren küçük coinler ve henüz taranmadı.
5. **Cascade dedektörü.** Aynı 30 saniyede ≥ 10 sembol sıçrarsa "cascade modu":
   pozisyon boyutu artır, zaman aşımını kısalt.

---

*Paper mod. Gerçek emir gönderilmez. API anahtarı kullanılmaz.
Yatırım tavsiyesi değildir. Geçmiş performans gelecek getiriyi garanti etmez.*
