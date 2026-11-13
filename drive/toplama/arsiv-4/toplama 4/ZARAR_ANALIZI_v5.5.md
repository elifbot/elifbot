# ZARAR ANALİZİ — Para Nereye Gidiyor?

**Sürüm:** v5.5 · **Tarih:** 2026-11-08
**Ölçüm:** 90 gün, 6 OKX majör, drawdown kilidi AÇIK (`rolling`, 7 gün)
**Kanıt:** `docs/zarar_atfi_ONCE.json`, `docs/zarar_atfi_SONRA.json`,
`docs/zarar_atfi_ONCE_trades.json`

> Bu rapor üç kez düzeltildi. İlk iki taslakta **kendi ölçüm
> hatalarım** vardı; ikisi de aşağıda açıkça işaretlendi. Sonuçlar
> üçüncü ve doğru ölçümdür.

---

## 0. TEK PARAGRAFLIK CEVAP

Zararın **%69,6'sı ters fiyat hareketinden**, **%30,4'ü doğrudan
maliyetten** (komisyon + kayma) geliyor. Girişlerin yön bilgisi yok:
gerçekten dolan işlemler, **adil ±1R çıkışla bile %70 kaybediyor**.
Çıkış geometrisi suçlu değil — ölçülen katkısı **+0,03R**.

Ayrıca gerçek bir **yürütme hatası** bulundu ve düzeltildi: acil
sabit-zarar stopu, yapısal stopla çakıştığında mumun en kötü
fiyatından kapatıyordu. Düzeltme zararı **%5,6 azalttı** — yani
hata gerçek ama **ana neden değil**.

---

## 1. ZARARIN BİLEŞENLERİ

20 işlem, net **−101,0655 USDT** (düzeltme öncesi):

| Bileşen | Tutar | Pay |
|---|---:|---:|
| Komisyon (giriş + çıkış) | 16,0959 | %15,9 |
| Kayma (slippage) | 14,6647 | %14,5 |
| **Doğrudan maliyet** | **30,7606** | **%30,4** |
| Ters fiyat hareketi | 70,3472 | %69,6 |
| Funding | −0,0424 | ~%0 — **ÖLÇÜLMEDİ** |

R cinsinden (R tabanı 8,0853 USDT):

| | R/işlem |
|---|---:|
| Brüt | −0,4350 |
| Maliyet | 0,1902 |
| **Net** | **−0,6250** |

> **Muhasebe notu:** `slippage` ayrı bir kesinti değildir; kötü dolum
> fiyatı zaten brüt PnL'in içindedir. Net'ten ayrıca düşmek çift
> sayım olurdu. `gross_pnl` alanı TP1 kısmi kârını içermez; brüt
> olarak kullanılamaz. İkisi de test ile kilitlendi.

> **Funding uyarısı:** `validate_strategy` funding oranlarını
> iletmiyor. ~0 değeri "önemsiz" değil, **ölçülmedi** demektir.

---

## 2. ANA NEDEN: GİRİŞLER ZATEN KAYBEDİYOR

### 2.1 Belirleyici test — aynı girişler, adil çıkış

Gerçekten **dolan** 20 işlemi, **açılış stopuyla** simetrik ±1R
çıkışla yeniden simüle ettim:

| | Brüt R |
|---|---:|
| Gerçek çıkış geometrisi | **−0,4102** |
| Simetrik ±1R çıkış | **−0,4405** |
| **Çıkış geometrisinin katkısı** | **+0,0303** |

**Çıkış geometrisi suçlu değil.** Katkısı sıfıra yakın, hafif pozitif.
Simetrik çıkış da aynı girişlerde kaybediyor.

Simetrik çıkışta kazanma oranı **%30** (6/20). Yani dolan girişler
adil bir çıkışla bile **%70 ters gidiyor**.

### 2.2 Kapısız evrenle karşılaştırma — ters seçilim şüphesi

| Evren | n | Simetrik kazanma |
|---|---:|---:|
| Kapısız aday taraması | 1.116 | ~%48,6 (yazı-tura) |
| **Gerçekten dolan girişler** | **20** | **%30** |

Maker limit emri fiyat geri geldiğinde dolar — bu, sinyal tersine
gittiğinde daha sık olur. Klasik **ters seçilim** mekanizması.

**Ama kanıtlanmadı:** n=20, 6 kazanç. p=0,486 altında beklenen
9,7 ± 2,24 → **z = −1,66**. İstatistiksel olarak zayıf.

> ⚠️ **DÜZELTİLEN ÖLÇÜM HATAM #1:** ilk ölçümde simetrik kazanma
> oranını %16,7 bulmuştum. Sebep: `stop_loss` alanını kullanmıştım,
> oysa o alan trailing/breakeven ile **hareket ediyor**. Sıfıra
> çekilmiş stop `r_price=0` verip işlemi simülasyon dışı bırakıyordu.
> Pozisyona `initial_stop_loss` ekleyip açılış stopunu kullandım;
> doğru değer **%30**. Ayrıca gerçek tarafı net R ile değil **brüt R**
> ile karşılaştırmak gerekiyordu; o da düzeltildi.

### 2.3 Bağımsız kenar ölçümü (v5.5)

| TF | Bağımsız n | Net R | Net GA | Hüküm |
|---|---:|---:|---|---|
| 5m | 818 | −0,5601 | [−0,673, −0,515] | **KENAR ELENDİ** |
| 15m | 302 | −0,2570 | [−0,435, −0,174] | **KENAR ELENDİ** |
| 1h | 67 | −0,1088 | [−0,338, +0,160] | **YETERSİZ ÖRNEKLEM** |

5m'de simetrik brüt beklenti **−0,0267R**, maliyet **0,5334R**.
Zarar = kenarsız girişe ödenen ücret.

---

## 3. BULUNAN YÜRÜTME HATASI — gerçek ama küçük

### 3.1 Mekanizma (kodda doğrulandı)

`exec/paper.py` çıkış kontrol sırası:

```
1. likidasyon
2. position_loss_stop   ← mumun EN KÖTÜ fiyatıyla kontrol
3. stop_loss            ← yapısal stop fiyatı
```

Pozisyon, yapısal stopta net riski `max_loss_per_position` (25 USDT)
olacak şekilde boyutlanır:

```
net_risk_at_stop = notional × (stop_kesri + maliyet_oranı)
```

Yani **tam boyutlu işlemde acil eşik ile yapısal stop aynı fiyata
denk gelir.** Eski kod bu durumda acil stopu seçip **mumun en kötü
fiyatından + ekstra kaymayla** kapatıyordu.

### 3.2 Birim testiyle kanıt

Yapısal stop 99,7 · mum dibi 99,0 · hedef risk 25 USDT:

| | Dolum | Net | R |
|---|---:|---:|---:|
| **Eski** | 98,9208 | **−113,37** | −4,535 |
| **Yeni** | 99,6502 | **−40,47** | −1,619 |

Dolum fiyatı mum dibinin de **altına** iniyordu (ekstra kayma).
Fiyat 99,0'a inmek için önce 99,7'yi geçmek zorunda — yani eski
davranış mantıksal olarak da yanlıştı.

### 3.3 Düzeltme ve gerçek etkisi

Aynı mumda iki tetik varsa **girişe yakın olan** kazanır; acil stop
yalnız yapısal stop vurmayacaksa devreye girer.

90 günlük gerçek örneklemde:

| | ÖNCE | SONRA |
|---|---:|---:|
| Net PnL | −101,0655 | **−95,4263** |
| Brüt R | −0,4350 | −0,4023 |
| Ödeme oranı | 0,1909 | **0,2924** |
| Kazanma oranı | %25 | %25 (değişmedi) |
| `position_loss_stop` çıkışı | 2 | **0** |

**İyileşme: +5,6392 USDT (%5,6).**

> ⚠️ **DÜZELTİLEN İDDİAM #2:** ilk taslakta bu hatanın "zararın
> ~%33'ünü" açıkladığını yazmıştım. **Yanlıştı.** Yapay birim
> testindeki 113→40 farkını gerçek örnekleme taşımıştım. Gerçek
> aşım yalnız **9,10 USDT** idi; düzeltme 5,64 USDT geri kazandırdı.

### 3.4 Peki 2 işlem zararın %58'ini neden yaptı?

**Pozisyon büyüklüğü yüzünden, hata yüzünden değil:**

| | Planlanan risk | Pay |
|---|---:|---:|
| 2 tam boyutlu işlem | 50,01 USDT | **%42** |
| Diğer 18 işlem | 67,87 USDT | %58 |
| **Toplam** | **117,88 USDT** | |

Risk ölçekleyici ilk zararlardan sonra pozisyonları 1,27–8,49 USDT'ye
küçülttü. İlk iki işlem 25'er USDT ile **tüm riskin %42'sini**
taşıyordu. Zararın yoğunlaşması bunun doğal sonucu.

### 3.5 Brief uyumu

Brief §2 yasaklar listesinde *"Sabit zarar tutarına göre pozisyon
kapatma"* var. Bu mekanizma hâlâ kodda (güvenlik ağı olarak), ama
artık yapısal stopu ezmiyor. Tamamen kaldırılması **Faz 3** kararı.

---

## 4. ÖDEME ORANI — kötü ama suçlu değil

| | ÖNCE | SONRA |
|---|---:|---:|
| Ortalama kazanç | +0,170 R | — |
| Ortalama kayıp | −0,890 R | — |
| Ödeme oranı | 0,1909 | **0,2924** |
| Kazanma oranı | %25,0 | %25,0 |
| Başabaş için gereken | %84,0 | **%77,4** |

Mekanizma: `trail_activation_r = 0,75`, TP1 = 1,0R. Trailing TP1'den
**önce** aktifleşiyor; 2,0 ATR = 1,33R takip mesafesi başabaş için
+1,33R gerektiriyor, ama TP1 +1,0R'de yarısını kapatıyor. Kazanan
5 işlemin 5'i de `trailing_stop` + TP1 yapılmış, ortalama +0,370R.

**Ancak §2.1 gösteriyor ki** simetrik alternatif de kurtarmıyor
(−0,44R vs −0,41R). Ödeme oranını düzeltmek, kaybeden girişleri
kârlı yapmaz.

---

## 5. KIRILIMLAR

### 5.1 Rejim

| Rejim | İşlem | Net | Kazanma |
|---|---:|---:|---:|
| **TREND_DOWN** | 6 | **−66,35** | %33 |
| TREND_UP | 8 | −25,97 | **%12** |
| STRONG_TREND_DOWN | 2 | −7,10 | %50 |
| STRONG_TREND_UP | 2 | −1,74 | %0 |
| UNCERTAIN | 2 | +0,09 | %50 |

`TREND_DOWN` + `TREND_UP` = zararın **%91'i**.

### 5.2 Yön · 5.3 Motor

| Yön | n | Net | Kazanma | | Motor | n | Net |
|---|---:|---:|---:|---|---|---:|---:|
| SHORT | 10 | −73,36 | %40 | | trend | 17 | −95,44 |
| LONG | 10 | −27,71 | **%10** | | fade | 3 | −5,62 |

Zararın %94'ü trend motorundan. **n=10 yön iddiası için yetersiz** —
`MIN_DIRECTIONAL_N=30` kuralı burada da geçerli.

---

## 6. DRAWDOWN KİLİDİNİ AÇMAK ZARARI ARTIRDI

| Mod | İşlem | Net | Kilit reddi |
|---|---:|---:|---:|
| `all_time` (v5.4) | 12 | −80,52 | 1.013 |
| `rolling` (7 gün) | **20** | **−101,07** | 989 |
| `daily` | **20** | **−102,82** | 979 |

Kilidi açmak işlemi **%67 artırdı**, zararı **%26 büyüttü**.

**Yorum:** kilit bir hata değildi, **kenarsız stratejiyi frenliyordu**.
Bu, "12 işlem 90 günlük örneklem değil" eleştirisini haklı çıkarır
ama kilidi açmanın çözüm olmadığını gösterir.

> ⚠️ **DÜZELTİLEN ÖLÇÜM HATAM #3:** ilk düzeltmem işe yaramadı —
> motor kendi `peak_equity` değişkenini tutuyor, portföyün pencere
> mantığını baypas ediyordu. İki koşu tıpatıp aynı çıktı verdi.
> Tek kaynağa bağlandıktan sonra mod etkili oldu.

---

## 7. ÖNCELİK SIRASI — ÖLÇÜME DAYALI

| # | İş | Ölçülen/beklenen etki | Durum |
|---|---|---|---|
| **1** | Acil stop / yapısal stop sırası | **+5,64 USDT (%5,6)** | ✅ **YAPILDI** |
| **2** | Funding'i backtest'e bağla | Net PnL doğru olur | ⬜ |
| **3** | Dolum kalitesi testi (n≥300) | Ters seçilimi kanıtla/çürüt | ⬜ |
| **4** | Örneklem altyapısı (1 yıl × 30–50) | 1h hükmü netleşir | ⬜ |
| **5** | Yeni giriş mantığı | Asıl sorun bu | ⬜ |
| **6** | Trailing aktivasyonu TP1 sonrası | Ödeme oranı ↑, kâr garantisi yok | ⬜ |

**Kritik uyarı:** 1 ve 6 zararı **azaltır**, kâr **üretmez**.
§2'deki ölçüm giriş kenarının olmadığını gösteriyor. Kenar olmadan
yürütme düzeltmeleri yalnızca kaybı yavaşlatır.

---

## 8. SINIRLAR

- **20 işlem** — çok küçük örneklem. §3'teki bulgu bir **mekanizma
  kanıtıdır** (birim testi), istatistiksel genelleme değildir.
- Rejim/yön kırılımlarında n=2..10 → yön iddiası yasak.
- Ters seçilim şüphesi z=−1,66 ile **kanıtlanmadı**.
- Funding ölçülmedi.
- 90 gün tek rejim, 6 majör, Binance maliyeti VARSAYIM.
- Simetrik karşılaştırma açılış stopunu gerektirir; trailing
  sonrası stop kullanılırsa ölçüm bozulur (yapıldı ve düzeltildi).

---

## 9. HÜKÜM

**Gerçek para YASAK.** Pozisyon başına azami kayıp 2,5–5 USDT.

Zararın kaynakları, ölçülen büyüklükleriyle:

1. **Giriş kenarının olmaması** — baskın neden. Adil çıkışla bile
   dolan işlemlerin %70'i kaybediyor. 5m/15m'de istatistiksel olarak
   elendi.
2. **Maliyet** — zararın %30,4'ü. Yapısal: maliyet/stop = %51.
3. **Yürütme hatası** — gerçek, kanıtlandı, düzeltildi; etkisi %5,6.

Çıkış geometrisi **suçlu değil** (+0,03R). Parametre optimizasyonu
bu tabloyu değiştirmez. Sıradaki iş: örneklem altyapısı, sonra yeni
giriş mantığı.
