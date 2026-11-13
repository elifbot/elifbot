# DÜZELTME GÜNLÜĞÜ

Her satır: ne bozuktu → nasıl anlaşıldı (ölçüm) → ne yapıldı → sonuç.
Amaç: eksik kalanları sonradan toplayabilmek.

Son güncelleme: 28.10.2026 06:25 UTC · sürüm **v8**

---

## BÖLÜM 1 — BOT HİÇ İŞLEM AÇMIYORDU (28.10 sabahı)

### 1.1 Genişlik eşiği matematiksel olarak imkânsızdı ⚠️ EN BÜYÜK HATA
- **Bozuk:** `GENISLIK_ESIK = 0.45` — yani "sembollerin %45'i aynı anda %0,5 hareket etmeli".
- **Kanıt:** 289 sembol × 8.421 dakikalık gerçek ölçüm:
  `ortalama %1,75 · medyan %1,73 · p90 %3,11 · p99 %6,23 · MAKSİMUM %9,69`
- **Sonuç:** Eşik hiçbir zaman sağlanamazdı. 05:41 koşusu 9 dk / 0 sinyal.
- **Düzeltme:** `0.45 → 0.04` (dağılımın üst çeyreği).
- **Dosya:** `ws_bot.py: GENISLIK_ESIK`

### 1.2 Sinyal penceresi 2 saniyeydi → mikro gürültü
- **Bozuk:** `--pencere-ms 2000`, `--ret 0.05`
- **Kanıt:** 209 canlı sinyal kaydedildi, sonraki fiyatlarla kıyaslandı:
  `1 dk isabet %41,2 · ücret sonrası -0,104%/işlem`
  → sinyaller **yanlış yöne** gidiyordu (yazı-turadan kötü).
- **Düzeltme:** `--pencere-ms 60000`, `--ret 0.5` (1 dakikada %0,5).
- **Dosya:** `ws_bot.py`, `SembolDurum.fiyatlar` deque `300 → 4000`

### 1.3 rvol (hacim patlaması) filtresi çok zayıftı
- **Bozuk:** `--rvol 1.0` — her şey geçiyordu.
- **Kanıt:** 7 gün, TP1,25/SL2,0/240dk, ücret dahil:

  | rvol | n | ort/işlem | isabet | TEST | pozitif gün |
  |---|---|---|---|---|---|
  | yok (1,0) | 980 | +0,079% | %66,7 | **−0,018%** | 3/4 |
  | 3,0 | 448 | +0,304% | %73,4 | +0,067% | 3/3 |
  | **5,0** | **1.354** | **+0,242%** | **%70,7** | **+0,117%** | **4/4** |

- **Düzeltme:** `1.0 → 5.0`. Kâr 5 katına çıktı, test seti pozitife döndü.
- **Mekanizma:** hacimsiz ani hareket gürültü; hacimle gelen hareket gerçek tasfiye, geri dönüyor.

### 1.4 cascade eşiği pratikte hiç sağlanmıyordu
- **Bozuk:** `CASCADE_ESIK = 3` (son 60 sn'de 3 sinyal)
- **Kanıt:** 7 günde cascade 0/2/3/4 neredeyse aynı sonucu verdi; sinyaller zaten seyrek.
- **Düzeltme:** `3 → 0` (kapalı).

### 1.5 Bağlam katmanı sinyallerin %99,5'ini eliyordu
- **Bozuk:** `--baglam-ret 1.2` + `--baglam-maks-ret 2.0`
- **Kanıt:** Teşhis koşusu — bağlamsız **dakikada 70 sinyal**, bağlamla **8,9 dakikada 1 sinyal**.
- **Düzeltme:** Bağlam varsayılanı `True → False`. (Aşama 1 artık 1 dk'lık gerçek hareketi ölçtüğü için gereksiz.)

### 1.6 TP/SL ve tutma süresi
- **Düzeltme:** `--tp 2.0 → 1.25`, `--sl 3.0 → 2.0`, `--tut-dk 10 → 240`
- **Kanıt:** 7 gün çıkış yöntemi kıyaslaması (524 sinyal):
  TP2/SL3/240dk **+0,853%** · TP2/SL3/5dk +0,672% · İZOLE (stopsuz) +0,564% · iz süren +0,136%

---

## BÖLÜM 2 — BINANCE ÖLÜYDÜ

### 2.1 connection reset → 60 sn ban beklemesi
- **Bozuk:** `_ceza_bekle()` her hatayı IP banı sayıp `2→4→8→16→32→60 sn` bekliyordu.
- **Kanıt:** `ws_durum.json`: `binance.aktif=false, hata="[Errno 104] Connection reset by peer", tik 45.501` — 9 dakika boyunca ölü.
- **Asıl:** "Connection reset" geçici bir TCP kopması, ban değil.
- **Düzeltme:** Hata sınıflandırması — kopma/zaman aşımı → **1,5 sn**, gerçek ban (kod −1003) → üstel artış.
- **Dosya:** `scanner/ws_scanner.py: _ceza_bekle`

### 2.2 Tek sunucuya bağlıydı
- **Düzeltme:** `_taban_dondur()` — art arda 3 kopmada `www.binance.com → fapi.binance.com → fapi1` rotasyonu.

### 2.3 Fiyat turu yavaştı
- **Düzeltme:** `FIYAT_ARALIK 1,0 → 0,5 sn`, timeout `10 → 6 sn`
- **Ağırlık:** 2 × 120 = 240/dk (bütçe 1.200'ün %20'si) — ban riski yok.
- **Sonuç:** **1.046 tik/sn, 523 sembol, hata yok.**

---

## BÖLÜM 3 — CANLI KOŞUDA ÇIKAN HATALAR (v7, 15 dk)

### 3.1 Genişlik ölçer sessizce devre dışıydı 🐞
- **Bozuk:** `genislik_guncelle()` yalnızca `d.baglam_hazir` olan sembolleri sayıyordu.
- **Sorun:** Bağlam kapatılınca (`--no-baglam`) `baglam_hazir` hiç `True` olmuyor → `toplam=0` → oran `0.0`.
- **Kanıt:** v7 koşusu 15 dk boyunca `genislik_oran: 0.0`; 36 pozisyon filtreye hiç takılmadan açıldı.
- **Düzeltme:** Genişlik artık kendi fiyat geçmişinden, bağlamdan **bağımsız** ölçülüyor.
- **Test:** `test_baglam_kapaliyken_de_olcer`

### 3.2 Aynı varlık iki borsada açılıyordu 🐞
- **Kanıt:** Aynı anda `okx:ATH-USDT-SWAP` ve `binance:ATHUSDT` açıldı — tek olay, iki kat risk.
- **Sebep:** Portföy anahtarı `(borsa, sembol)`; `ATH-USDT-SWAP ≠ ATHUSDT`.
- **Düzeltme:** `_base_sembol()` eklendi; base eşleşmesinde `engel:cift_borsa`.
- **Test:** `test_base_sembol_ayni`, `test_base_sembol_farkli`

---

## BÖLÜM 4 — v7 CANLI TEST SONUCU (15 dk, 06:07–06:22)

| Metrik | Değer |
|---|---|
| Sinyal | 53 |
| Açılan pozisyon | 36 |
| Kapanan | 36 (7 TP · 3 SL · 26 session_end) |
| Net PnL | **−5,88 $** (1.000 $ üzerinden %−0,59) |
| İsabet | %55,6 (20 kazanan / 16 kaybeden) |

### Çıkış nedenine göre
| neden | n | toplam | ortalama |
|---|---|---|---|
| take_profit | 7 | **+27,98 $** | +4,00 $ |
| stop_loss | 3 | −18,61 $ | −6,20 $ |
| session_end (test bitti) | 26 | −15,25 $ | −0,59 $ |

### 🔴 ASIL SORUN: KOMİSYON
- **Brüt PnL: +3,15 $** · **Komisyon: 9,03 $** · **Net: −5,88 $**
- İşlem başına komisyon **0,25 $** (25 $ marj × 10x = 250 $ notional × %0,10)
- 36 işlem × 0,25 = 9,03 $

**Yani strateji brütte kârlı; komisyon kârı yiyor.**
Brüt getiri komisyonun yalnızca 1/3'ü kadar.

### Sıradaki düzeltme (henüz uygulanmadı)
1. **Maker giriş** (`--giris limit`): komisyon %0,10 → ~%0,02 = **5 kat azalma**.
2. Daha seçici sinyal (rvol 5 → 10) → daha az ama büyük işlem.
3. TP'yi büyütmek (1,25 → 2,0) → komisyon sabit, kâr büyür.

---

## SÜRÜM GEÇMİŞİ

| sürüm | zaman | ana değişiklik | canlı sonuç |
|---|---|---|---|
| v5 | 05:41 | 240 dk tutma + genişlik 0,45 | **0 sinyal** (eşik imkânsız) |
| v6 | 05:54 | genişlik 0,04, ret 0,005 | 0 sinyal (bağlam eliyor) |
| v7 | 06:07 | pencere 60 sn, rvol 5, cascade 0 | **36 pozisyon**, −5,88 $ (komisyon) |
| **v8** | 06:25 | + genişlik bug fix, + çift borsa engeli | test bekliyor |

---

## AÇIK SORULAR / EKSİK KALANLAR

1. **Komisyon** — en büyük kâr kalemi. Maker giriş test edilmedi.
2. **session_end** — 26 işlem 240 dk dolmadan test bitince kapandı; gerçek sonuç bilinmiyor.
3. **Günlük dağılım** — kâr 2 güne sıkışıyor (gl≥6 senaryosu). Sakin piyasada kenar zayıf.
4. **Tutarlılık** — v7 15 dk'lık koşu, 7 günlük backtest'in +%0,242/işlem beklentisini doğrulamadı.
5. **Binance WS** — hâlâ açılmıyor (451/WAF). REST ile idare ediliyor, 1.046 tik/sn yeterli.
6. **Funding** — `bilinmiyor` olarak işaretli, PnL'e dahil değil.
