# S7 · Sinyal kıyaslama

1. Aynı veri, aynı seed, aynı kasa — yalnızca **bir** sinyal değişkeni.
2. Tablo: sinyal başına tetik, dönüşüm (tetik→işlem), WR, başabaş WR, PF, ort. tepe kâr.
3. "Sinyal çok üretiyor ama işlem az" → risk filtresi kesiyor demektir; red sayaçlarına bak.
4. Bir sinyali kaldırmadan önce: o sinyalin işlemlerinin **net katkısını** hesapla.
5. Karar eşiği: katkı negatif **ve** örneklem ≥ 100 ise kaldır.

Kabul: her sinyal için karar + gerekçe rapora yazılır.
