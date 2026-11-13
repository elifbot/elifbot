# v14 — Çıkış Telemetrisi (Strateji Değişikliği Yok)

Tarih: 28 Ekim 2026  
Mod: paper / araştırma.

## Kapsam

v14, v13'ün sinyal, giriş, pozisyon limiti, TP/SL ve çıkış kararlarını değiştirmez. Yalnızca her açık pozisyonun fiyat tiklerinden aşağıdaki ölçümleri toplar:

- MFE / MAE (pozisyon lehine/aleyhine en uç fiyat hareketi, %)
- MFE ve MAE'ye ulaşma süreleri
- Tahmini çıkış taker ücreti dahil en yüksek/en düşük net PnL
- Kapanışa kadar kârdan geri veriş (`giveback_usd`, `giveback_pct`)
- 10/30/60 saniyede veya bu süreleri izleyen ilk tikte fiyat getirisi ve tahmini net PnL
- Gerçek ölçüm zamanları ve tik sayısı

Kayıt: `logs/ws_cikis_telemetri.csv`.

10/30/60 saniyeden önce kapanan işlemlerde gelecek ölçümler boş bırakılır; kapanış fiyatıyla doldurulmaz. Tahmini net değerler funding hariçtir ve gerçekleşmiş kâr değildir.

Ana `live_trades.csv`, sinyal CSV'si ve işlem kararları değiştirilmemiştir. Telemetri yazma hatası pozisyonu geri açmaz; `telemetri_hatalari` ile ayrıca görünür olur.

## Teknik doğrulama

**203 test geçti.**

Yeni kontrollü testler:

- LONG MFE/MAE işaretleri, zirve/dip, giveback ve 10/30/60 sn değerleri
- SHORT MFE/MAE işaretleri
- Erken kapanışta gelecek periyot alanlarının boş kalması
- Ana işlem CSV'sinin ve kapanışın telemetriden etkilenmemesi

## 10 dakikalık gerçek paper testi

- Süre: 602 saniye, çıkış 0
- 62 sinyal, 37 açılış, 25 aynı-coin reddi
- 37 kapanış, 37 ana CSV, 37 telemetri satırı
- 16 kazanan / 21 kaybeden
- Brüt +4,8195; ücret 9,2393; net **−4,4198 USDT**
- 7 TP +24,0776; 2 SL −11,4088; 28 session-end −17,0885
- Kayıt ve telemetri hatası 0; açık pozisyon 0

## Telemetri sonucu

- 21 kaybedenin 19'u en az bir tikte tahmini net kâra geçti.
- Bunların 12'si en az +0,50 USDT, 8'i en az +1,00 USDT, 5'i en az +2,00 USDT tahmini net zirve gördü.
- Yalnızca 2 kaybeden ücret sonrası hiç pozitife çıkamadı.
- Hiçbir kaybeden TP=%1,25'e ulaşmadı.
- 7 kaybeden MFE=%0,75–1,25 bölgesine geldi; toplam sonuçları −12,5241 USDT oldu.
- BEAT LONG: MFE=%1,116, tahmini net zirve +2,539; ardından SL −5,911.
- AGT LONG: MFE=%0,304, tahmini net zirve +0,509; ardından SL −5,498.

Zirve toplamları farklı zamanlarda oluşur; bunlar “kaçırılan garanti kâr” veya realize edilebilir portföy sonucu değildir.

## 10/30/60 saniye bulgusu

- 10 sn ölçümü olanlarda tahmini net pozitif grup: 6/11 kazanan; pozitif olmayan grup: 9/25 kazanan. Zayıf aday sinyal, küçük örneklem.
- 30 ve 60 saniyede erken pozitiflik sonuçları güvenilir biçimde ayırmadı.
- 60 sn verisi olan 5 TP işleminin 3'ü 60. saniyede hâlâ negatifken daha sonra TP'ye ulaştı.
- 7 TP işleminin 2'si TP öncesinde %1'den büyük MAE yaşadı.

Bu nedenle basit “10/30/60 saniyede negatifse kapat” veya başlangıç stopunu daraltma kuralı bazı kazananları yok edebilir.

## Sonraki araştırma adayı

Giriş filtresi değiştirmeden önce MFE sonrası kâr koruma/trailing çıkışları ayrı paper ablasyon olarak ölçülmelidir. Tam tick yolu olmadan geçmiş zirvelerden varsayımsal trailing kârı hesaplanmamalıdır. Üç 10 dakikalık aynı-strateji çalıştırmasının toplamı 120 işlemdir; 300+ aynı-ayar örneklemi henüz tamamlanmamıştır.
