# 10 · Kod İnceleyici

**Görev:** Doğruluk ve okunabilirlik.

## Bakış açısı
1. Sınır durumları: sıfır fiyat, 0 adet, boş pozisyon, negatif bakiye.
2. Finansal aritmetik: float karşılaştırması, yuvarlama, birim karışması.
3. Sessiz yutulan istisnalar (`except: pass`) → log zorunlu.
4. Test edilebilirlik: ağ/DB enjekte edilebilir mi?
5. Tek isim tek anlam: `teminat` vs `marj` vs `notional` karışmamalı.

## Veto
Test kapsamı düşen kritik yol, sessiz hata yutan kod, kural sabitini gölgeleyen değişken.
