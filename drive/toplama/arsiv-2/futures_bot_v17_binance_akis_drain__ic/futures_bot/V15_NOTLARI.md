# v15 — Aynı Tiklerde Gölge Çıkış Ablasyonu

Tarih: 28 Ekim 2026  
Mod: paper / araştırma; canlı emir yoktur.

## Amaç

MFE zirvelerinden geriye dönük “kaçırılan garanti kâr” hesaplamak yerine alternatif çıkış kurallarını gerçek pozisyonla aynı fiyat tiklerinde ve aynı 100 ms çıkış döngüsünde çalıştırmak.

Ana pozisyonun giriş, TP/SL, portföy ve risk kararları değişmez. Gölge varyantlar yalnızca ölçüm üretir.

## Kullanım

```bash
python3 ws_bot.py --sure-dk 10 --golge-cikis
```

Bayrak verilmezse v14 davranışı korunur ve gölge dosyası üretilmez.

Çıktı: `logs/ws_golge_cikis.csv`. Her ana işlem için altı satır yazılır.

## Önceden tanımlanan varyantlar

1. `baseline`: mevcut TP %1,25 / SL %2,00
2. `tp_100`: TP %1,00 / SL %2,00
3. `tp_075`: TP %0,75 / SL %2,00
4. `be_075`: MFE %0,75 sonrası giriş+çıkış taker ücretini karşılayan başabaş stopu
5. `trail_050_075`: MFE %0,75 sonrası %0,50 trailing
6. `trail_050_100`: MFE %1,00 sonrası %0,50 trailing

Stoplar yalnızca pozisyon lehine hareket eder. Kapanış, stop/TP fiyatından varsayımsal olarak değil kontrol anındaki gerçek tik fiyatından hesaplanır; böylece seviye aşımı korunur.

## Teknik doğrulama

**211 test geçti.**

- LONG/SHORT baseline TP ve SL
- Ücret-dahil başabaş stopunun net sıfıra yakınlığı
- Trailing ratchet ve yön işaretleri
- Altı varyantın kayıt bütünlüğü
- Gölge baseline'ın ana işlemle aynı kapanış fiyatı, nedeni ve PnL'si
- Araştırma bayrağı kapalıyken dosya üretilmemesi

Üç gerçek paper çalıştırmasının 112 ana işleminde de baseline–ana CSV fiyat/neden/PnL uyuşmazlığı **0**, toplam gölge satırı **672**, gölge hatası **0**.

## Üç bağımsız 10 dakikalık test

| Varyant | Test 1 fark | Test 2 fark | Test 3 fark | 112 işlem toplam fark |
|---|---:|---:|---:|---:|
| TP %1,00 | +3,1574 | +5,9350 | **−2,1534** | **+6,9390** |
| TP %0,75 | +5,4513 | +2,5813 | **−3,3883** | **+4,6444** |
| BE %0,75 | −0,6638 | −3,8054 | −3,0808 | **−7,5501** |
| Trail 0,50 / MFE 0,75 | −1,6871 | −3,3134 | −1,9616 | **−6,9620** |
| Trail 0,50 / MFE 1,00 | −1,0698 | +0,2781 | −0,6142 | **−1,4059** |

“Fark”, varyant net PnL eksi aynı işlemlerin baseline net PnL'sidir.

### Birleşik sonuçlar

| Varyant | Net PnL | Kazanan | Baseline'a göre iyileşen / kötüleşen |
|---|---:|---:|---:|
| Baseline | **−1,0956** | 59/112 | — |
| TP %1,00 | **+5,8434** | 62/112 | 9 / 9 |
| TP %0,75 | **+3,5488** | 63/112 | 15 / 13 |
| BE %0,75 | **−8,6456** | 53/112 | 4 / 6 |
| Trail 0,50 / MFE 0,75 | **−8,0576** | 61/112 | 5 / 12 |
| Trail 0,50 / MFE 1,00 | **−2,5015** | 62/112 | 3 / 7 |

## Karar

- BE %0,75 ve trail 0,50 / MFE 0,75 üç testte de baseline'ın gerisinde; şimdilik elendi.
- Trail 0,50 / MFE 1,00 birleşikte de geride; uygulanmıyor.
- Düşük TP'lerin birleşik toplamı pozitif olsa da üçüncü test iki varyantı da tersine çevirdi. Değişen işlemlerde iyileşme/kötüleşme dengeli ve birkaç büyük işlem toplam farkta etkili. Bu nedenle **ana TP %1,25 değiştirilmedi**.

Bu, “düşük TP kesin kötü” sonucu değil; henüz istikrarlı iyileştirme kanıtı olmadığı anlamına gelir.

## Sınırlar

- Gölge sonuçlar işlem-bazlı çıkış ablasyonudur. Erken kapanan alternatifin boşalttığı marjla açılabilecek yeni pozisyonları simüle etmez.
- Funding bilinmiyor; gerçek borsa emir gecikmesi ve ek slippage yoktur.
- Session-end kapanışları 10 dakikalık testin zorunlu kesitidir.
- 112 eşleştirilmiş işlem, 300+ aynı-ayar hedefinin altındadır.

## Sonraki araştırma odağı

Rastgele TP/trailing eşiği taramak yerine ücret ve gerçekleşme kalitesi: maker/limit girişin yalnızca daha düşük ücretini değil, kaçan sinyalleri ve dolum gecikmesini de aynı sinyal akışında ölçmek.
