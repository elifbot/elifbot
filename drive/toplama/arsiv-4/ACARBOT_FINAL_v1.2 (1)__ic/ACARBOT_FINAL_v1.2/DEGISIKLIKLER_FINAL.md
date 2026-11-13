# ACARBOT Mimari Eksikler ve Yol Haritası Kontrol Listesi

## 1. Yüksek Öncelik
- [x] **Beta Ayarlı Net Yön Tavanı:** Pozisyon maruziyetleri düz nominal yerine BTC betası ile ağırlıklandırıldı.
- [x] **Giriş Hız Limiti:** Saniyede/dakikada maksimum sinyal giriş limiti getirildi, sinyaller skora göre sıralandı.
- [x] **BTC Şoku Stres Testi:** -%3 ani BTC düşüş senaryosunda özkaynak (equity) koruma filtresi eklendi.
- [x] **Yedek Fiyat ve Veri Kesintisi Yönetimi:** REST yedek beslemesi sağlandı.

## 2. Canlıya Geçiş ve Operasyon
- [x] **Gerçek Emir Katmanı:** `clientOrderId` takibi ve tekrar gönderim engelleme mekanizması.
- [x] **Borsa Tarafında Reduce-Only Stop:** Sunucu çökse bile borsada aktif kalan stop emirleri.
- [x] **Başlangıç Mutabakatı:** Açılışta borsa emir/pozisyon durumu ile yerel store senkronizasyonu.
