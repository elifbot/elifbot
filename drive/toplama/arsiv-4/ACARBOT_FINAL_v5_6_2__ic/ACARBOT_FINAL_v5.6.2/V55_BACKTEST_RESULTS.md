# V5.6 — BACKTEST SONUÇLARI (TÜM ÖLÇÜMLER)

**Sürüm:** 5.6-final · **Tarih:** 2026-11-08
**Veri:** OKX USD-M swap · 6 sembol · 90 gün · 25.920 × 5m bar/sembol
**Profil:** `kasa1000` (marj 50 USDT, kaldıraç 10x, maks kayıp 25 USDT)

> ## 🔴 NİHAİ HÜKÜM: `NO_EDGE` — KENAR YOK
> Walk-forward'ın **0/3** penceresi kârlı. Monte Carlo kayıp olasılığı **%98,9**.
> **Şartnamenin başarı kriteri (maliyetler dahil pozitif net beklenti)
> KARŞILANMADI. Gerçek para modu AÇILMADI.**

---

## 1. BİRİNCİL KOŞU — `docs/dogrulama_v5.6_final.json`

**Koşu:** `--profile kasa1000 --windows 3 --drawdown-peak-mode rolling`
**Çıkış kodu:** 0 · **Sürüm damgası:** 5.6-final
**Mum içi yol:** karma — gerçek 1m kapsama **%63,5**, kalan sentetik

| Metrik | Değer |
|---|---:|
| **Net PnL** | **−13,6393 USDT** |
| İşlem sayısı | 20 |
| Kazanma oranı | %45,0 |
| **Profit Factor** | **0,30** |
| Sharpe | −0,49 |
| Max drawdown | 15,66 USDT (**%1,6**) |
| **Beklenti** | **−0,682 USDT / −0,32 R** |
| Ortalama kazanç | +0,65 R |
| Ortalama kayıp | −1,77 R |
| Ardışık kayıp | 4 |
| Komisyon | 4,20 USDT |
| Funding | −0,04 USDT — **UYGULANMADI** (§5) |
| Kayma | 3,00 USDT |
| Kısmi dolum | 11 |

### 1.1 Maliyet payı

```
komisyon + kayma = 7,20 USDT
toplam zarar     = 13,64 USDT
maliyet payı     = %52,8
```

**Zararın yarısından fazlası işlem maliyeti.** Bu, kök neden
belgesindeki yapısal bulguyu doğruluyor.

### 1.2 Motor / rejim / yön kırılımı

| Kırılım | İşlem | Net | PF / WR |
|---|---:|---:|---|
| trend | 18 | −11,83 | PF 0,321 |
| fade | 2 | −1,81 | PF 0,136 |
| TREND_DOWN | 9 | −3,18 | WR %44 |
| TREND_UP | 5 | −8,40 | WR %20 |
| STRONG_TREND_DOWN | 3 | −1,26 | WR %67 |
| STRONG_TREND_UP | 2 | −1,09 | WR %50 |
| UNCERTAIN | 1 | **+0,28** | WR %100 |
| **LONG** | 7 | **−9,49** | **PF 0,024** |
| **SHORT** | 13 | −4,15 | PF 0,576 |

**LONG tarafı neredeyse hiç kazanmıyor** (PF 0,024). 7 işlemde 1 kazanç.

---

## 2. WALK-FORWARD — 3 PENCERE

| Metrik | Değer |
|---|---:|
| WF işlem sayısı | 66 |
| **Kârlı pencere** | **0 / 3** |
| WF toplam net | **−28,42 USDT** |
| En kötü pencere | −13,64 USDT |

> Motorun kendi yorumu: *"Hiçbir alt dönemde kâr yok — tek dönemlik
> şans açıklaması geçersiz."*

**Bu, `INSUFFICIENT_SAMPLE`'dan daha güçlü bir olumsuz sonuçtur.**
Örneklem yetersiz olsa bile tüm alt dönemler zararlı.

### 2.1 Monte Carlo

| Metrik | Değer |
|---|---:|
| Kayıp olasılığı | **%98,9** |

---

## 3. TRAILING VARYANT DENEYİ (F bölümü)

**Koşu:** `--profile kasa1000 --windows 0 --drawdown-peak-mode rolling`
Her varyant ayrı koşu, aynı veri ve önbellek.

| Varyant | Trail aktivasyon | ATR | BE | 1m kapsama | n | Net | WR | PF | DD% | R |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| **A** mevcut | 0,75R | 2,0 | açık | %63,5 | 20 | −13,64 | %45,0 | 0,30 | 1,6 | −0,32 |
| **B** TP1 sonrası | 1,00R | 2,0 | **kapalı** | %63,5 | 20 | −13,64 | %45,0 | 0,30 | 1,6 | −0,32 |
| **C** TP1 + BE | 1,00R | 2,0 | açık | %63,5 | 20 | −13,64 | %45,0 | 0,30 | 1,6 | −0,32 |
| **D** ATR dinamik | 1,00R | **3,0** | açık | **%57,0** | 20 | −13,46 | %45,0 | 0,31 | 1,5 | −0,32 |

### 3.1 A = B = C — neden özdeş?

Üç varyant **aynı 20 işlemi, aynı çıkışları** üretti. Yapılandırmalar
farklı (doğrulandı: log satırları ve config denetimi), ama bu örneklemde
**hiçbir çıkışı değiştirmediler.**

Sebep: 2 ATR takip mesafesi ≈ 1,333R. 0,75R'de aktive olan takip stopu
−0,58R'ye denk gelir; yapısal stop −1R'de olduğu için ikisi de aynı
mumlarda tetikleniyor. Break-even da 1,0R'de devreye giriyor ve TP1
zaten orada kısmi kâr alıyor — bu örneklemde ek etki üretmiyor.

**Yorum:** Çıkış ince ayarı bu örneklemde **hiçbir şey değiştirmiyor.**
Bu, v5.5'in "çıkış geometrisi ana suçlu değil" bulgusunu bağımsız
olarak destekliyor.

### 3.2 D karşılaştırılabilir DEĞİL

D'nin gerçek 1m kapsaması **%57,0**, diğerlerinin **%63,5**. Farklı
ATR çarpanı farklı pozisyon süreleri → farklı hedefli 1m pencere
talebi → farklı mum içi veri. **D'nin 0,18 USDT "iyileşmesi" bir
varyant etkisi değil, veri farkı olabilir.**

**Bu yüzden D seçilmedi.**

### 3.3 Seçim kararı

```
seçilen: HICBIRI
neden: "Hiçbir varyant hem in-sample hem out-of-sample pozitif net
        beklenti göstermedi. Zarar azaltmak seçim ölçütü değildir."
```

Ayrıca **OOS koşusu yapılmadı** (`--windows 0`), bu yüzden seçim kuralı
zaten hiçbir varyantı seçemezdi. Bu bir eksiklik ve açıkça yazıldı.

### 3.4 Düzeltilen deney tasarım hatası

İlk tanımda B ve C **yapılandırma olarak özdeşti** — çünkü
`breakeven_enabled` varsayılan olarak zaten `True` idi ve B'de de
`True` bırakılmıştı. Fark edildi, B'de `False` yapıldı, B ve C
**yeniden koşuldu.** Regresyon testi eklendi:
`test_all_four_variants_are_configurationally_distinct`.

---

## 4. YENİ STRATEJİ TARAMASI (D bölümü)

6 strateji × 3 zaman dilimi × 6 sembol. **Tarama simülatörü** (üretim
motoru değil; TP1/trailing/DD kilidi yok, taker komisyonu).

### 4.1 Net beklenti (R) — tüm sonuçlar

| Strateji | 5m | 1h | 4h |
|---|---:|---:|---:|
| liquidity_sweep_mss | −0,6116 (n=839) | **+0,1081** (n=41) | **+0,2052** (n=15) |
| breakout_retest_volume | −0,7348 (n=4.706) | −0,1500 (n=289) | −0,3633 (n=57) |
| vwap_cvd_momentum | −0,6275 (n=5.599) | −0,1397 (n=383) | −0,1698 (n=111) |
| order_block_fvg_structure | −0,9055 (n=15.002) | −0,2251 (n=1.006) | −0,1217 (n=259) |
| oi_volume_price_divergence | −1,0673 (n=10.819) | −0,2669 (n=800) | −0,1111 (n=167) |
| trend_continuation_mtf | −0,6635 (n=6.838) | −0,1801 (n=345) | sinyal yok |

**Hiçbiri istatistiksel olarak pozitif değil.** `liquidity_sweep_mss`
1h/4h'de pozitif nokta tahmini verdi ama GA95 sıfırı kapsıyor
([−0,197, +0,413] ve [−0,287, +0,697]) ve n çok küçük.

**18 test yapıldı → Bonferroni eşiği α/18 = 0,0028. Hiçbiri geçmez.**

### 4.2 Zaman dilimi etkisi (ana bulgu)

`liquidity_sweep_mss`:

| TF | Stop | Maliyet/R | Net R |
|---|---:|---:|---:|
| 5m | %0,41 | %34 | −0,6116 |
| 1h | %2,09 | %6,7 | +0,1081 |
| 4h | %3,88 | %3,6 | +0,2052 |

Şartnamenin ima ettiği stop **%4,786** — 4h ölçümüyle aynı mertebede.

---

## 5. FUNDING — UYGULANMADI

```
durum: UYGULANMADI
neden: "Tarihsel funding verisi yüklenmedi. Backtest funding'i
        HESAPLAMADI; bu 'funding sıfır' anlamına GELMEZ."
sembol_sayisi: 0
```

Rapordaki `Funding: -0.04` değeri motorun pozisyon süresi
varsayılanından gelen artıktır, **tarihsel ödeme değildir.**

Funding artık motora **bağlı** (`backtest/funding.py` + 4 blok), ama
depoda `*_funding.csv` yok. **Bu bir eksikliktir ve kapatılmadı.**

---

## 6. MAKER TERS SEÇİLİM — VERİ YOK

```
hüküm: VERI_YOK
dolan: 0 · dolmayan: 0 · eşik: 300
```

Altyapı kuruldu (`exec/markout.py`, 11 test), **veri toplanmadı.**
"Ters seçilim yok" denmedi.

---

## 7. KABUL KRİTERLERİ — TAMAMI BAŞARISIZ

| Kriter | Eşik | Ölçülen | Sonuç |
|---|---|---|---|
| **Net beklenti** | **> 0** | **−0,32 R** | 🔴 |
| Profit Factor | ≥ 1,30 | 0,30 | 🔴 |
| OOS pozitif | gerekli | koşulmadı | 🔴 |
| WF çoğunluk pozitif | gerekli | **0/3** | 🔴 |
| Örneklem | ≥ 200 | 20 + 66 WF = 86 | 🔴 |
| Veri süresi | ≥ 12 ay | 90 gün | 🔴 |
| Sembol | 30–50 | 6 | 🔴 |
| Maker dolum | ≥ 300 | 0 | 🔴 |
| Funding kapsama | tam | yok | 🔴 |
| Eksik mum kontrolü | gerekli | yapılmadı | 🔴 |
| Gerçek komisyon | gerekli | varsayım | 🔴 |

---

## 8. ÖNCEKİ KOŞULARLA KARŞILAŞTIRMA (dikkat)

| Koşu | Profil | 1m kapsama | n | Net | DD% | R | Hüküm |
|---|---|---:|---:|---:|---:|---:|---|
| v5.5 | apex | %36,4 | 20 | −95,43 | 10,11 | −0,40 | INSUFFICIENT |
| v5.6 ara | kasa1000 | %36,4 | 21 | −23,32 | 2,30 | −0,54 | INSUFFICIENT |
| **v5.6 final** | **kasa1000** | **%63,5** | **20** | **−13,64** | **1,60** | **−0,32** | **NO_EDGE** |

> **UYARI:** Bu üç koşu **doğrudan karşılaştırılamaz.** Mum içi veri
> kapsaması farklı (%36,4 → %63,5). Kapsama arttıkça sentetik yol
> payı azalıyor ve sonuç değişiyor.
>
> **Aynı kapsamada tek geçerli karşılaştırma:**
> apex %36,4 (−95,43) ↔ kasa1000 %36,4 (−23,32) → **boyut düzeltmesi
> zararı %75,6 azalttı, drawdown'u %77 azalttı.**
>
> Ama beklenti hâlâ negatif ve WF 0/3 → **kenar yok.**

Ara koşu arşivlendi: `docs/arsiv/dogrulama_v5.6_kasa1000_ON.json`

---

## 9. TEST DURUMU

```
920 passed in 26.57s
```

**0 başarısız.** ruff temiz. Ham çıktı: `docs/test_ciktisi_v5.6.txt`

| Yeni test dosyası | Test |
|---|---:|
| test_v56_sizing.py | 14 |
| test_v56_live_gate.py | 7 |
| test_v56_markout.py | 11 |
| test_v56_funding.py | 7 |
| test_v56_trailing.py | 11 |
| test_v56_strategies.py | 8 |
| **TOPLAM** | **58** |

---

## 10. SONUÇ

**Bot kârlı değil.** Boyut kusuru giderildi, risk kontrolü şartnameye
uyduruldu, drawdown %10'dan %1,6'ya indi — ama **kenar yok.**

**Yapılan iş bir "kazanan bot" üretmedi; kaybeden bir botun neden
kaybettiğini ölçülebilir biçimde ortaya koydu:**

1. İşlem maliyeti zararın **%52,8**'i
2. 5m stopları (%0,33) maliyeti karşılayamayacak kadar dar → **0,39R handicap**
3. 6 yeni strateji de aynı duvara çarptı
4. Tek umut verici yön üst zaman dilimi — **ama kanıtlanmadı**

**Gerçek para YASAK.** İki kilit aktif: `live.enabled = False` ve
`live_allowed_timeframes = ()`.