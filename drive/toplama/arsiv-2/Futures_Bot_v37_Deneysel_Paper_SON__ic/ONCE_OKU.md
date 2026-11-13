# v37 deneysel PAPER paketi

ÖNEMLİ: H-01 açık; 19/71 saniye daha sıkı fail-closed kabulü kullanıcı izniyle bu paper denemesinde muaf tutuldu. Bu testler geçmedi. Gerçek para/gerçek emir yok. Kârlılık/Windows veya veri tamlığı garanti edilmez.

Aktif giriş: son 60 TAM bir dakikalık mum quote/base VWAP, kapalı mum Wilder ATR(14)/fiyat >= %0,10. VWAP saniye hassasiyetli kayan 60 dakika değildir; cari dakika dışlanır. LONG > VWAP, SHORT < VWAP; eksik, kopuk, bayat veri kapalı. Yön, fade ters çevrildikten sonraki paper giriş yönüdür; teyit ve limit dolumunda tekrar kontrol edilir.

Mevcut REST ön-dolgu isteklerinde 45 yerine 65 mum istenir, ek endpoint/istek eklenmez. OKX kapalı mum websocket, Binance aggTrade'den sonraki mumlar belleğe alınır; akış kopmalarında Binance gösterge geçmişi temizlenir. Veri eksikliği 60 dakikalık warmup veya tüm test boyunca kapalı olmasına neden olabilir. Gecikmiş olaylar RVOL yolunda işlenme zamanına göre örneklenir.

`pip install -r requirements.txt` ve kullanıcının komutu proje klasöründe uygulanabilir. Canlı veriyle 5 dakikalık sonuç bu e-postadan sonra üretilecektir. Önceki CSV/JSON verilerinin ayrı yedeği workspace'te korunur.

Durum dosyası göstergelerin anlık mum ve taze fiyat hazır sayısını borsa bazında kaydeder. Tam regresyon: 407 test; 12 aktif gösterge testi bunun içindedir. 2 katı gap güvenlik testi kullanıcı onayıyla yalnız paper denemesinde muaf tutuldu.
