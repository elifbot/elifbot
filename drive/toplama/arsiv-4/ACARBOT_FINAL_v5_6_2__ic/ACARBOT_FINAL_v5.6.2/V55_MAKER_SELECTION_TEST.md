# V5.6 — MAKER TERS SEÇİLİM TESTİ

**Sürüm:** 5.6-final · **Tarih:** 2026-11-08

> **HÜKÜM: TERS SEÇİLİM KANITLANMADI — ama "yok" da denemez.**
> Örneklem 20 dolum; şartname eşiği 300. Altyapı kuruldu, veri toplanmadı.

---

## 1. SORU

Maker (post-only) emirlerimiz, fiyat bize doğru gelirken değil,
**bize karşı giderken** mi doluyor? Öyleyse beklenen kazancın bir
kısmı dolum anında kaybediliyor demektir.

---

## 2. MEVCUT KANIT (v5.5 ölçümü — sınırlı)

Kapısız evrende, sinyalden sonra işlemin kazanma oranı ile fiilen
dolan işlemlerin kazanma oranı karşılaştırıldı:

| Grup | n | Kazanma |
|---|---:|---:|
| Kapısız evren (tüm sinyaller) | 1.116 | **%48,6** |
| Fiilen dolan işlemler | 20 | **%30,0** |

Beklenen dolan-kazanan sayısı: 9,7 ± 2,24 → gözlenen 6
**z = −1,66** (tek kuyruk p ≈ 0,048, çift kuyruk p ≈ 0,097).

### Neden bu kanıt SAYILMAZ?

1. **n = 20.** Şartname 300 istiyor. 20 gözlemle %30 vs %48,6 farkı
   gürültüden ayrıştırılamaz.
2. **Çoklu karşılaştırma.** Bu, onlarca bakılan metrikten biriydi;
   düzeltme uygulanınca anlamlılık kayboluyor.
3. **Karşılaştırma kirli.** "Kapısız evren" ile "dolan işlemler" farklı
   filtrelerden geçmiş kümeler — aynı emirlerin dolan/dolmayan
   ayrımı DEĞİL.
4. **Markout ölçülmedi.** Ters seçilimin doğrudan ölçüsü dolum sonrası
   fiyat hareketidir; kazanma oranı değil.

**Sonuç: hipotez ne doğrulandı ne çürütüldü.**

---

## 3. KURULAN ALTYAPI — `exec/markout.py`

### 3.1 Kayıt şeması (`FillRecord`)

Şartnamenin istediği tüm alanlar:

| Grup | Alanlar |
|---|---|
| **Sinyal** | `signal_ts_ms`, `signal_price` |
| **Gönderim** | `submit_ts_ms`, `submit_price`, `submit_best_bid`, `submit_best_ask`, `submit_spread_bps`, `submit_book_imbalance` |
| **Dolum öncesi** | `pre_move_bps` (çoklu ufuk) |
| **Dolum** | `filled`, `fill_ts_ms`, `fill_price`, `fill_qty`, `fill_latency_ms` |
| **Dolum sonrası** | `post_prices` → **1 / 5 / 15 / 30 dakika** |
| **Piyasa** | `market_post_returns` (arındırma için) |
| **Maliyet** | `fee_paid`, `slippage_bps` |
| **İptal** | `cancelled`, `cancel_reason` |

**Dolmayan emirler de kaydedilir** — karşılaştırma grubu onlar.

### 3.2 Markout tanımı

```
markout(T) = yön × (fiyat(t_dolum + T) − fiyat_dolum) / fiyat_dolum × 10⁴  [bps]
yön = +1 LONG, −1 SHORT
```

- Pozitif → dolum sonrası fiyat lehimize gitmiş (iyi dolum)
- Negatif → aleyhimize gitmiş (ters seçilim işareti)

### 3.3 Piyasa sürüklenmesinden arındırma (kritik)

Ham markout yanıltıcıdır: piyasa düşerken LONG markout'u negatif çıkar,
bu ters seçilim değil **beta**dır. Bu yüzden iki seri raporlanır:

```
arındırılmış_markout(T) = ham_markout(T) − yön × piyasa_getirisi(T)
```

> **Sınır:** beta = 1 varsayılır. Sembol betası **tahmin edilmedi**;
> bu bir yaklaşıklıktır ve raporda öyle işaretlenir.

### 3.4 Dolmayan emirlerle karşılaştırma

Dolmayan emirler için **karşı-olgusal** hesap: gönderim fiyatına göre
"dolmuş olsaydı" markout'u. Gerçek dolum DEĞİLDİR ve çıktıda
`"NOT": "...gerçek dolum DEĞİL"` etiketiyle ayrılır.

### 3.5 Hüküm kuralları (otomatik)

| Koşul | Hüküm |
|---|---|
| Kayıt yok | `VERI_YOK` |
| n < 300 | `YETERSIZ_ORNEKLEM` |
| GA95 üst sınırı < 0 | `TERS_SECILIM_VAR` |
| GA95 alt sınırı > 0 | `TERS_SECILIM_YOK_POZITIF` |
| GA95 sıfırı kapsıyor | `ANLAMSIZ` |

**Örneklem eşiğinin altında asla "ters seçilim yok" denmez.**

---

## 4. ŞU ANDAKİ ÇIKTI

```
hüküm: VERI_YOK
neden: "Hiç emir kaydı yok. Testnet/paper dolumu toplanmadan ölçüm yapılamaz."
dolan: 0 · dolmayan: 0 · dolum_orani: null
```

**Bu bir başarısızlık değil, ölçümün yapılmadığının açık beyanıdır.**
Sıfır markout yazılmadı.

---

## 5. VERİ TOPLAMA PLANI (henüz uygulanmadı)

1. Testnet'te `--live-testnet --profile kasa1000` ile **post_only** modda
   çalıştır (market fallback KAPALI).
2. Her emirde `FillRecord` doldur — dolmayanlar dahil.
3. Dolum sonrası 1/5/15/30 dk fiyatlarını ayrı bir izleyiciyle kaydet.
4. Aynı pencerede eşit-ağırlıklı evren getirisini kaydet.
5. **300 dolum** birikince `analyze_fills()` çağır.
6. 300 dolum için tahmini süre: mevcut sinyal sıklığıyla (~20 işlem/90 gün)
   **~3,7 yıl** → **sinyal sıklığı artırılmalı veya çok sembole yayılmalı.**
   Bu, tek başına önemli bir bulgudur: mevcut motor bu ölçümü makul
   sürede üretemiyor.

---

## 6. TERS SEÇİLİM DOĞRULANIRSA — hazır müdahale listesi

Şartnamenin istediği müdahaleler. **Hiçbiri şu an aktif değil** çünkü
hipotez doğrulanmadı; kanıtsız müdahale iyi çalışan bir mekanizmayı bozar.

| Müdahale | Nerede yapılmalı | Durum |
|---|---|---|
| Fiyatlama algoritması (limit'i kaydır) | `live/sync.py::_post_only_entry` | hazır değil |
| Spread filtresi | `core/gates.py` | **VAR** (spread kapısı mevcut) |
| Order book dengesi | `submit_book_imbalance` alanı hazır | mantık yok |
| Dolum öncesi momentum kontrolü | `pre_move_bps` alanı hazır | mantık yok |
| Uygunsuz emri iptal et | `cancel_reason` alanı hazır | mantık yok |
| Dolum olasılığı × beklenti | — | **yok** |

> **Uyarı:** `cancel_on_stop_breach_at_fill` ayarı zaten var ama
> varsayılanı `False` (ters seçilimi modeller). `True` yapmak
> **iyimserlik üretir** — gerçek borsada iptalin dolmadan önce
> yetişeceği garanti değildir. Kanıt olmadan açılmamalı.

---

## 7. TESTLER

`tests/test_v56_markout.py` — **11 test, hepsi geçti:**

- LONG/SHORT işaret doğruluğu
- Eksik fiyat → `None` (0 değil)
- Dolmayan emrin markout'u yok
- Piyasa sürüklenmesi arındırması
- Kayıt yok → `VERI_YOK`
- 50 dolum → `YETERSIZ_ORNEKLEM` (300 eşiği)
- 300 negatif dolum → `TERS_SECILIM_VAR`
- 300 pozitif dolum → `TERS_SECILIM_YOK_POZITIF`
- Dolan/dolmayan sayımı ve dolum oranı
- Ufuklar 1/5/15/30 dk

---

## 8. KANIT DOSYALARI

| Dosya | İçerik |
|---|---|
| `exec/markout.py` | Ölçüm altyapısı |
| `tests/test_v56_markout.py` | 11 test |
| `docs/giris_kenari_v55_5m.json` | Dolan/evren karşılaştırmasının kaynağı |
| `docs/dogrulama_v5.5.json` | 20 işlemlik örneklem |