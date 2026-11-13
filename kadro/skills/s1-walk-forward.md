# S1 · Walk-forward doğrulama

1. Veriyi **zamana göre** dilimle: %50 eğitim, %25 doğrulama, %25 test. Karıştırma yok.
2. Eşikleri yalnızca eğitimde seç.
3. Doğrulamada parametre seçimini dondur.
4. Testi **bir kez** çalıştır; sonucu görünce parametre değiştirdiysen test yanmıştır, yeniden dilimle.
5. Her dilim için: işlem sayısı, net, WR, başabaş WR, PF, maksDD.
6. Rapor: `runs/<etiket>/walkforward.json` + dilim tablosu.

Kabul: test diliminde PF > 1.1 **ve** işlem ≥ 100 **ve** maksDD < kasanın %15'i.
