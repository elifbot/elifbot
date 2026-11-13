# Proje kararlari (kullanici tarafindan belirtilenler)

- Borsalar: Binance ve OKX futures, ayni anda.
- Bakiye: 1000 dolar. Islem basina giris 50 dolar, 10x kaldirac.
- Islem basina zarar: stop, bir islem 25 dolar kaybettirecek sekilde ayarlanir.
- Emirler: komisyonu dusuk tutmak icin maker (limit) emir tercih edilir.
- Taranacak evren: yaklasik 800 coin, anlik para girisi/cikisi tespiti.
- Take-profit botun kendisi karar verir (para girisi durunca kapat; RSI/MACD donusu gibi).
- Teknik ariza olursa bot gecici bekler, sorun giderilince kullanici devam ettirir.
- Gunluk zarar limiti ve acik pozisyon limiti: kullanici "yok" dedi (bkz. acik konular).
- Yayina alma sirasi: once deneme/testnet, canli test en son, sonra surekli iyilestirme.
- Ajanlar: tarayici, haber, giris, cikis, zaman dilimleri, risk, emir, alarm, analist, ABD piyasasi/Kongre.

## Acik konular (inceleme bulgulari, karar bekliyor)
1. Gunluk zarar limiti ve kill switch: 10x kaldiracla ust uste stop'lar bakiyeyi hizli eritebilir.
2. Ayni coinin Binance ve OKX'te iki kez acilmasi ve BTC korelasyonu.
3. Dusuk likidite filtresi ve OKX'teki hisse benzeri kontratlar.
4. Maker emir dolum modeli (simdilik tum emirler taker varsayiliyor).
5. Para girisi sinyali icin OI, taker akisi, likidasyon, funding verisi.
6. Geri test: aylik gecmis veri, funding dahil, hayatta kalma yanliligi duzeltilmis.
