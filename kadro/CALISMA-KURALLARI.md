# Çalışma kuralları

## 1. Kural değişmez
`bot/v8/config.py::KasaKurallari` içindeki altı sayı kullanıcı kararıdır:
1.000 $ kasa · 50 $ teminat · 10x · CROSS · pozisyon limiti yok · net −10 $ stop.
Bu sayıları değiştiren PR reddedilir. Değiştirmek isteyen, önce kullanıcıdan yazılı onay alır.

## 2. Kanıt zorunluluğu
Her PR'da üç şeyden biri olmalı:
- **Test:** yeni/düzeltilen davranışı kilitleyen test
- **Ölçüm:** öncesi/sonrası sayı (aynı veri, aynı seed)
- **Neden:** kod okumasıyla kanıtlanan hata (satır referansı)

"İyileştirdim" cümlesi tek başına kanıt değildir.

## 3. Sayı dürüstlüğü
- WR tek başına yazılmaz; başabaş WR ile birlikte.
- Açık PnL ile realize karıştırılmaz.
- Pozisyon kaldıracı (10x) ile hesap kaldıracı ayrı etiketlenir.
- Örneklem < 100 ise "yön göstergesi" denir, "kanıt" denmez.
- Sentetik veri sonucu "kenar ölçümü" sayılmaz; dosya/rapor adında belirtilir.

## 4. Simülatör iyimser olamaz
Teminat reddi, kayma, komisyon, funding ve gap modelde yoksa sonuç geçersizdir.

## 5. Canlı para
Varsayılan kapalı. Açmak için `ACARBOT_CANLI_ONAY=EVET-RISKI-ANLIYORUM` + `skills/s8` kapısı.

## 6. Dil
Kod, yorum, doküman Türkçe; değişken adları Türkçe (mevcut kod tabanıyla uyumlu).
Harici API alan adları İngilizce kalır.

## 7. Commit
`<alan>: <ne yapıldı> (<kanıt>)` — örn. `risk: stop -10$ testi eklendi (test_v8_kural)`.
