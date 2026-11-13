# v9.5.3 — saat kesintisinde güvenli sonlandırma

Önceki yaklaşık 519,797 saniyelik UTC/monotonik sapmada giriş kilidi doğru kapandı; uygulama yanlış biçimde ACTIVE kalıp 600 monotonik saniyeyi bekledi. Yazılımın yaşam-döngüsü hatası düzeltildi. Hostun saatini veya VM askısını tamir ettiğimiz iddia edilmiyor; altyapı nedeni kesin doğrulanmış değil.

## Yeni davranış
- Alarmda aktif test penceresi bırakılır. Açık pozisyon varsa en çok yapılandırılmış güvenlik drenajı; sonuç DISCONTINUOUS. Başarılı test sayılmaz, otomatik yeniden giriş izni açılmaz.
- Eski BBO/fiyat-alım önbelleği geçersizleştirilir. Finansal durum veya pozisyonlar silinmez.
- İlk olay mühürlenir, giriş kontrolü ve periyodik kontroldeki tekrar gözlemler ayrı sayılır.
- CLOCK_BOOTTIME mevcutsa yalnız teşhis içindir. Kesinti sınıflaması şüphe düzeyindedir, doğrulanmış kök neden gibi sunulmaz.
- Yeni test bu yanıt içinde **sonlu foreground gözeticiyle tamamlanana kadar beklenerek** yürütülecek. Alt süreç çıkış kodu, bağımsız HTTP/SQLite örnekleri ve son rapor saklanır. Platformun kill/askı davranışını engelleme garantisi yok.

## Korunanlar
v9.5.2 mild eşikleri (0,17 / 6 / 0,85), karar çekirdeği, gerçek taker ve tazelik şartı, spread/maliyet, Executor, PAPER broker, SQLite defteri, ATR/adaptif risk, dolum öncesi güvenlik kapısı byte-identical. Maker emre otomatik piyasa emri takibi eklenmedi. Daha fazla işlem veya dolum garantisi yok.

## Kanıt
- Native ccxt 4.5.91: **271 test geçti, 29.42 sn**.
- Temiz ZIP açılımı: **271 test geçti, 29.99 sn**.
- Test sonrası **363 mühürlü dosya** hash doğrulaması temiz.
- 12 yeni kesinti/cleanup/cache/provenans testi; eski testler atılmadı. Tam fark ve açık izin listeleri pakette.
- Önceki v952 süreç bulunamadı ve nihai sonuç dosyası yoktu. Eski exit nedeni tahmin edilmedi, sahte sonuç yazılmadı. Salt-okunur DB incelemesinde açık/kapanan/intent: 0/0/0.

Ana kod ZIP: `kripto-bot-v9.5.3-PAPER-RC1-kod-test-rapor.zip`  
Boyut: 5832522 bayt  
SHA-256: `455a575c9c33454ef61dc2346f0d7a113db7002198731277e41dfd141552b41b`

Bu bir test öncesi teslim raporudur; yeni doğal 600 saniye koşunun sonucu henüz değildir. E-posta doğrulamasından sonra yeni prefix/boş DB ile 600 aktif + en çok 120 drenaj + ısınma; üst gözetici bütçesi 850 sn. Gerçek para/özel emir API'si/ücretli API/dış model yok. Omnistudio çevrimdışı inceleme sayfası hazır; Docker veya model onayı iddia edilmez.
