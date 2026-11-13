# ACARBOT v1.2 - Gelişmiş Algoritmik Ticaret Botu

ACARBOT, kripto para borsalarında (Binance, OKX) veri odaklı ve yüksek frekanslı sinyalleri işleyen, gelişmiş risk yönetimi ve güvenlik guard modülleriyle donatılmış kurumsal düzeyde bir trading botudur.

## Yeni Eklenen Gelişmiş Özellikler (v1.2)
- **Beta Ayarlı Net Yön Tavanı:** Klasik net yön limitleri yerine, açık pozisyonların BTC'ye olan anlık betası hesaplanarak dinamik risk maruziyeti belirlenir.
- **Sinyal Giriş Hız Limiti:** Aynı saniyede veya dakika içinde gelen yoğun sinyaller skora göre sıralanır ve rate-limit uygulanır.
- **BTC Şoku Stres Testi (Crash Test):** Yeni işleme girmeden önce, BTC'nin ani -%3 hareketinde tüm portföyün beta ağırlıklı kaybı simüle edilir.
- **Veri Kesintisi ve Yedek Fiyat Katmanı:** Websocket kesintilerinde REST API yedek katmanı ve ikincil borsadan referans fiyat kontrolü devreye girer.
- **Gelişmiş Canlı Emir Yönetimi:** `clientOrderId` eşleştirmesi, mükerrer emir engelleme ve borsada `reduce-only` stop-loss emri entegrasyonu.
