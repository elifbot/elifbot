# Birleşik Para Akışı ve Hacim Momentum Botu (Binance & OKX Futures)

Bu trading botu, gönderdiğiniz iki versiyonun en güçlü yönlerini bir araya getirerek, tamamen sizin belirttiğiniz ticaret kurallarına göre yeniden dizayn edilmiştir.

## 🛠️ Temel Öncelik ve Çalışma Yapısı
1. **1. Öncelik: Gerçek Zamanlı Para Giriş/Çıkış Taraması (`VolumeFlowScanner`):** Bot, alfabetik sıralamayı tamamen reddeder. Binance ve OKX Vadeli İşlem (Futures) piyasasındaki tüm coinleri 10 saniyede bir tarayarak, içeri giren nakit gücüne, anlık hacim katlanmalarına ve momentum yönüne bakar.
2. **2. Öncelik: Destekleyici Haber Filtresi (`NewsGuard`):** Haber akışı botu tek başına yönlendirmez. Bir coinde para akışı yönü (Long/Short) tespit edildikten sonra, arka planda küresel haber duyarlılığı taranır. Eğer haber yönü trendi destekliyorsa işlem açılır; haber trendin tam zıttı bir spekülasyon içeriyorsa kasa koruması için o parite pas geçilir.
3. **3. En Düşük Komisyon Sistemi (Maker / Post-Only):** Bot, işlemlerinizi piyasadan doğrudan emir emerek (Taker) açmaz. **Post-Only (Limit Maker)** emir mimarisi kullanır. Bu sayede borsaya komisyon cezası (Taker ücreti) ödemezsiniz; aksine emir defterine likidite sağladığınız için en düşük komisyon bareminden faydalanırsınız.

## 🚀 Çalıştırma Talimatları
1. Gerekli kütüphaneleri yükleyin:
   ```bash
   pip install -r requirements.txt
   ```
2. `.env.example` dosyasını `.env` olarak değiştirip Binance ve OKX borsalarından aldığınız API anahtarlarınızı girin.
3. Botu başlatın:
   ```bash
   python app/main.py
   ```
