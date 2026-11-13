# V5.6 — ZARARIN KÖK NEDENİ VE GİDERİLMESİ

**Sürüm:** 5.6-final · **Tarih:** 2026-11-08
**Önceki sürüm:** 5.5-final (ZIP'lenmedi) · **Temel:** 5.4-final (teslim edildi)

> Bu belgede yazan her sayı bu depodaki bir ölçüm dosyasından gelir.
> Ölçülmeyen şey "0" değil, "ÖLÇÜLMEDİ" olarak yazılır.

---

## 0. YÖNETİCİ ÖZETİ — İKİ AYRI KUSUR, İKİ AYRI SONUÇ

| # | Kusur | Etkisi | Durum |
|---|---|---|---|
| 1 | Acil stop sıralaması (v5.5'te bulundu) | 5,64 USDT / zararın %5,6'sı | **DÜZELTİLDİ** |
| 2 | **Pozisyon boyutu sınırsız** (v5.6'da bulundu) | Marj **9,19×** şişiyor | **DÜZELTİLDİ** |
| 3 | **Maliyet / stop oranı** (v5.6'da ölçüldü) | Beklentiyi tek başına öldürüyor | **YAPISAL — düzeltilemedi** |

**Kusur 2'nin düzeltilmesi zararı −95,43 → −23,32 USDT'ye indirdi**
(aynı %36,4 mum içi kapsamada karşılaştırma).
**Ama bu bir KENAR değildir.** Zarar, pozisyon küçüldüğü için azaldı.

**Nihai koşu** (daha iyi %63,5 kapsama, sürüm 5.6-final):
net **−13,64 USDT**, beklenti **−0,32R**, walk-forward **0/3 kârlı**,
Monte Carlo kayıp olasılığı **%98,9** → **HÜKÜM `NO_EDGE`.**

Şartname "zarar azaltma değil, pozitif net beklenti" diyordu —
**o hedefe ulaşılmadı.**

---

## 1. KUSUR #2 — POZİSYON BOYUTU SINIRSIZDI

### 1.1 Bulgu

`apex` profilinde:

```
margin_per_position      = 0     ← 0 = SINIRSIZ
max_notional_per_position = 0     ← 0 = SINIRSIZ
leverage                 = 10
max_loss_per_position    = 25 USDT
```

`core/risk.py::plan()` miktarı **stop mesafesinden** hesaplar:

```
notional = hedef_risk / (stop_oranı + maliyet_oranı)
```

Stop daraldıkça notional büyür. Tavan olmadığı için:

| Ölçülen stop | Notional (USDT) | Marj (USDT) | Kasanın payı |
|---|---:|---:|---:|
| **%0,330** (medyan) | **5.102,04** | **510,20** | **%51,0** |
| %1,000 | 2.155,17 | 215,52 | %21,6 |
| %4,786 | ~500 | ~50 | %5,0 |

**Bot, 25 USDT risk hedeflerken 510 USDT marj bağlıyordu.**
Kullanıcının şartnamesi 50 USDT marj diyordu → **9,19× ihlal.**

### 1.2 Bu neden bir "bug" değil, şartname tutarsızlığı?

`core/risk.py` docstring'i bunu zaten kabul ediyordu:
> "25 USDT bir TAVAN, garanti değil."

Yani kod yanlış hesaplamıyordu — **istenen davranış matematiksel olarak
imkânsızdı.** Üç şart birbirini dışlıyor:

```
marj 50 USDT  ×  kaldıraç 10  =  notional 500 USDT
notional 500  ×  stop 0,33%   =  1,65 USDT brüt risk
                              +  1,07 USDT maliyet
                              =  2,72 USDT   ← 25 DEĞİL
```

25 USDT riski **50 USDT marjla** almak için gereken stop:

```
stop = (25 / 500) − 0,002139 = %4,7861
```

**Ölçülen medyan stop %0,330 → 14,5× daha dar.**

### 1.3 Düzeltme — `kasa1000` profili

`app/main.py`'ye yeni profil eklendi:

| Alan | apex (eski) | **kasa1000 (yeni)** |
|---|---:|---:|
| margin_per_position | 0 (sınırsız) | **50** |
| max_notional_per_position | 0 (sınırsız) | **500** |
| leverage | 10 | 10 |
| max_loss_per_position | 25 | 25 |
| max_positions | 0 (sınırsız) | 6 |
| total_open_risk_cap | — | 150 |
| gross_notional_cap | — | 3000 |

`apex` **silinmedi** — araştırma için duruyor, ama `--profile` yardım
metnine "YALNIZ ARAŞTIRMA" uyarısı eklendi.

### 1.4 Ölçülen etki (90 gün, 6 sembol, rolling DD, aynı veri)

| Metrik | apex (v5.5) | **kasa1000 (v5.6)** | Değişim |
|---|---:|---:|---|
| Net PnL | −95,4263 | **−23,3172** | **−%75,6 zarar** |
| Max drawdown | %10,11 | **%2,30** | **−%77** |
| İşlem | 20 | 21 | +1 |
| Kazanma | %25,0 | %28,6 | +3,6 pp |
| Profit Factor | 0,064 | 0,18 | ↑ ama hâlâ <1 |
| **Beklenti (R)** | **−0,4023** | **−0,5400** | **KÖTÜLEŞTİ** |
| Komisyon | 16,10 | 5,54 | −%66 |
| Kayma | 14,66 | 3,95 | −%73 |

**DİKKAT — beklenti R cinsinden KÖTÜLEŞTİ.** Sebep §2.

**Kanıt:** `docs/arsiv/dogrulama_v5.6_kasa1000_ON.json` (ara koşu, exit 0,
HÜKÜM `INSUFFICIENT_SAMPLE`, 1m kapsama %36,4).

**Nihai kanıt:** `docs/dogrulama_v5.6_final.json` — 1m kapsama %63,5,
20 işlem, net **−13,6393**, maxDD **%1,6**, beklenti **−0,32R**,
WF **0/3 kârlı**, HÜKÜM **`NO_EDGE`**.

> İki koşu doğrudan karşılaştırılamaz; mum içi veri kapsaması farklı.
> Yukarıdaki tablo **aynı kapsamada** (%36,4) yapılmış tek geçerli
> karşılaştırmadır.

---

## 2. KUSUR #3 — MALİYET / STOP ORANI (YAPISAL)

### 2.1 Matematik

Gidiş-dönüş maliyeti notional'in sabit bir oranıdır (~%0,2139 ölçülen
model; taker varsayımı %0,14). Stop ise notional'in **değişken** bir
oranıdır. R cinsinden maliyet:

```
maliyet_R = maliyet_oranı / stop_oranı
```

| Stop | Maliyet / R | Yorum |
|---|---:|---|
| %0,22 | **%97** | Neredeyse tüm risk bütçesi maliyete |
| %0,33 | **%39,3** | Her işlemde 0,39R handicap |
| %1,00 | %17,6 | |
| %2,09 | %10,2 | |
| **%4,786** | **%4,3** | Şartnamenin ima ettiği rejim |

**5m'de %0,33 stopla işlem yapmak, her işleme 0,39R kayıpla başlamaktır.**
Hiçbir giriş mantığı bunu tek başına yenemez — nitekim §4'te 6 yeni
stratejinin 6'sı da 5m'de elendi.

### 2.2 kasa1000'de beklenti neden kötüleşti?

Marj 50'ye sabitlenince risk 25 → 2,72 USDT'ye düştü. Ama maliyet
notional'e bağlı olduğu için **oransal olarak aynı kaldı**:

```
maliyet 1,07 USDT / risk 2,72 USDT = %39,3
```

Yani mutlak zarar düştü, **R başına verim düşmedi — artan maliyet payı
yüzünden düştü.** Bu, "daha küçük oyna" çözümünün neden çözüm
olmadığının kanıtıdır.

### 2.3 Zaman dilimi ölçeği

ATR ≈ √zaman varsayımıyla %0,33 → %4,786 için gereken ölçek:

```
zaman katsayısı = (4,7861 / 0,33)² = 210,35×
5 dakika × 210,35 = 1.051,7 dakika ≈ 17,5 SAAT
```

**Şartname bir SWING şartnamesidir; 5 dakikalık grafikte uygulanamaz.**
Bu varsayım gerçek ATR ile doğrulanmalıdır (§4'te kısmen doğrulandı).

---

## 3. KUSUR #1 — ACİL STOP SIRALAMASI (v5.5'te düzeltildi, korundu)

Şartname "düzeltilmiş stop sırasını geri alma" dedi → **korundu.**

**Önce:** mum içinde acil stop, yapısal stoptan ÖNCE ve daha kötü
fiyattan dolduruluyordu.
**Sonra:** yapısal stop önce değerlendiriliyor.

| | ÖNCE | SONRA |
|---|---:|---:|
| Net PnL (apex) | −101,0655 | −95,4263 |
| `position_loss_stop` sayısı | 2 | **0** |
| Ödeme oranı | 0,1909 | 0,2924 |

**Birim test kanıtı:** stop 99,7 / mum dibi 99,0 / hedef 25 USDT
→ eski dolum 98,9208 (−113,37 USDT / −4,535R)
→ yeni dolum 99,6502 (−40,47 USDT / −1,619R)

**Katkı: 5,64 USDT = zararın %5,6'sı.** Ana suçlu değildi.

> **Dürüstlük notu:** Bu düzeltme için önce "~34 USDT / %33" denmişti.
> O sayı sentetik birim testinden gerçek örnekleme yanlış taşınmıştı ve
> **geri alındı.** Gerçek ölçüm %5,6'dır.

---

## 4. ÇIKIŞ GEOMETRİSİ SUÇLU DEĞİL (yeniden doğrulandı)

20 eşleşmiş işlem, İLK stop + BRÜT R üzerinden:

| | Ortalama brüt R |
|---|---:|
| Gerçek çıkış geometrisi | −0,4102 |
| Simetrik ±1R (kısmi kâr/trailing yok) | **−0,4405** |
| **Geometrinin katkısı** | **+0,0303** |

Yani mevcut çıkış yönetimi, çıplak ±1R'den **daha iyi**. Trailing'i
kaldırmak zararı azaltmaz, artırır. F bölümündeki 4 varyant deneyi
bunu ayrıca sınamaktadır (`docs/trailing_*.json`).

---

## 5. NELER YAPILMADI (dürüst liste)

| Madde | Durum |
|---|---|
| Pozitif net beklenti | **YOK** — WF 0/3, Monte Carlo kayıp %98,9 |
| ≥300 gerçek maker dolumu | **YOK** — altyapı hazır, veri toplanmadı |
| 12 ay veri | **YOK** — 90 gün |
| 30–50 sembol | **YOK** — 6 sembol |
| Testnet canlı doğrulama | **YOK** |
| Gerçek Binance komisyon oranı | **VARSAYIM** (ölçülen OKX spread + varsayılan fee) |
| Tick seviyesi dolum modeli | **YOK** — 1m bar + sentetik yol |
| Funding tam kapsama | **EKSIK** — bağlandı ama tarihsel CSV yok |

---

## 6. SONUÇ VE TAVSİYE

1. **Boyut kusuru gerçekti ve giderildi.** Marj artık 50 USDT, notional
   500 USDT, risk tavanı 25 USDT — şartnameye uygun.
2. **Bu, kârlılık getirmedi.** Zarar küçüldü çünkü pozisyon küçüldü.
3. **Asıl engel yapısal:** 5m stopları maliyeti karşılayamayacak kadar dar.
4. **Kanıtlanmış yön:** üst zaman dilimi. `liquidity_sweep_mss` 1h'de
   +0,108R, 4h'de +0,205R nokta tahmini verdi — **ama örneklem 41 ve 15,
   istatistiksel olarak anlamsız.** Umut verici, kanıtlanmış DEĞİL.
5. **Gerçek para YASAK.** Canlı giriş kapısı varsayılan olarak tüm zaman
   dilimlerine kapalı (`live_allowed_timeframes = ()`).

### Önerilen sonraki adım (kanıt üretmek için)

- 12 ay × 30–50 sembol **1h ve 4h** veri topla
- `liquidity_sweep_mss`'i üretim motorunda, walk-forward + OOS ile koş
- Eşik: n ≥ 300, PF ≥ 1,30, OOS pozitif, WF çoğunluk pozitif
- Ancak o zaman `live_allowed_timeframes` açılabilir

---

## 7. KANIT DOSYALARI

| Dosya | İçerik |
|---|---|
| `docs/dogrulama_v5.6_final.json` | **Nihai doğrulama, NO_EDGE, exit 0** |
| `docs/arsiv/dogrulama_v5.6_kasa1000_ON.json` | Ara koşu (%36,4 kapsama) |
| `docs/trailing_{A,B,C,D}*.json` | 4 trailing varyantı |
| `docs/dogrulama_v5.5.json` | apex karşılaştırması |
| `docs/zarar_atfi_ONCE.json` / `_SONRA.json` | Stop düzeltmesi önce/sonra |
| `docs/strateji_lab_v56{,_1h,_4h}.json` | 6 strateji × 3 zaman dilimi |
| `docs/giris_kenari_v55_*.json` | Mevcut motorun giriş kenarı |
| `core/sizing_audit.py` | Şartname tutarlılık denetimi |
| `tests/test_v56_sizing.py` | 14 test |