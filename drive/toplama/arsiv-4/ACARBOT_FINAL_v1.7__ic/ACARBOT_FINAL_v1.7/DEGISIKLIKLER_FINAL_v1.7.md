# ACARBOT FINAL v1.7 — Bayat Sinyal Giriş Koruması (7 Kasım 2026)

## Kullanıcı sorusu
"FTTUSDT SHORT neden kapandı, doğru muydu? Bizde stop 25 dolar zararla
olacaktı, onu analiz et."

## Analiz bulguları
### 1) FTT neden anında kapandı? (hold_ms=0, -4.44 USDT)
- Sinyal, ~4 dk önce kapanan 5dk mumundan üretildi (entry_ref=0.2288).
- O sırada CANLI fiyat 0.2306'ya çıkmıştı — yani stop seviyesi (0.2306)
  zaten piyasa fiyatının altındaydı (SHORT için stop yukarıda).
- Limit emir 0.2288'den doldu, ama piyasa zaten stopun ötesinde olduğu için
  AYNI SANİYE stop_loss tetiklendi. Bu bir "bayat sinyal" hatasıydı.
- Gerçek mum verisi doğruladı: 10:30 kapanış 0.2288, 10:34 fiyat 0.2306.

### 2) 25 USDT meselesi — TAVAN, sabit stop değil
- `max_loss_per_position=25` bir ÜST SINIR (garanti değil).
- Pozisyon boyutu = min(500 USDT nominal, 25 USDT riske sığan nominal).
- FTT'de stop dar (%0.77) olduğundan 500 USDT nominal bile sadece ~3.8
  USDT risk taşıyor → asıl sınırlayıcı 500 USDT nominal tavanı.
- Gerçekleşen zarar 4.44 USDT (maliyet+kayma ile 1.17R). 25'e hiç
  yaklaşılmadı çünkü stop dardı ve nominal 500'de cap'liydi.
- NOT: Her işlemin 25 USDT risk taşıması İSTENİYORSA nominal tavan
  kaldırılmalı/yükseltilmeli (ayrı bir karar; mevcut APEX bunu yapmaz).

## Düzeltme (v1.7)
Giriş emri verilmeden ÖNCE canlı fiyat kontrolü:
- Canlı fiyat zaten stopun ötesindeyse (LONG: live<=stop, SHORT: live>=stop)
  giriş İPTAL edilir ("GİRİŞ İPTAL: bayat sinyal").
- Böylece FTT tipi anında stop-out (-4.44 USDT) engellenir.
- Canlı fiyat yoksa eski davranış korunur (geriye uyum).

## Test
**264/264 geçti** (258 v1.6 + 6 bayat sinyal koruması testi).
Testler kilitler: SHORT/LONG stop ötesi iptal, stop içi giriş yapılır,
canlı fiyat yoksa giriş yapılır.

## Panel
Panele "⏸ bayat sinyal iptali" sayacı ve olay akışı eklendi.
